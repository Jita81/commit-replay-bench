"""Sealed corpus (``crb.core.oracle.sealed_corpus``): authored dates, deterministic
splits, sealing, stratification, commitment hash, exposure reasoning.

Hermetic: TaskSpecs built in memory (plus one tiny git repo for the authored-date
lookup) — no model calls, no network.
"""

from __future__ import annotations

import json
import re

import pytest

from crb.core.git import GitRepo
from crb.core.oracle import sealed_corpus as sc
from crb.core.spec import TaskSpec
from crb.core.version import APPARATUS_VERSION
from fixtures.oracle_repo import commit, init_repo

PINNED_DATE = "2020-01-02T03:04:05+00:00"


def _task(
    i: int, cls: str = "class-a", size: str = "S", authored: str = "2025-05-06T07:08:09+00:00"
) -> TaskSpec:
    sha = f"{i:040x}"
    return TaskSpec(
        task_id=sha,
        repo="corpus",
        subject=f"feat: add {cls}-{i}",
        authored=authored,
        test_files=(f"tests/test_{i}.py",),
        src_files=(f"src/{cls}/{i}.py",),
        target_tests=(f"tests/test_{i}.py",),
        belt_scope=("tests/",),
        capability_class=cls,
        size=size,
        language="python",
        red_checked=True,
        gold_clean=True,
    )


@pytest.fixture()
def corpus() -> list[TaskSpec]:
    """4 class-a + 2 class-b tasks; the first one has a pinned authored date."""
    return [
        _task(1, authored=PINNED_DATE),
        _task(2),
        _task(3),
        _task(4),
        _task(5, cls="class-b"),
        _task(6, cls="class-b"),
    ]


# ---------------------------------------------------------------------------
# authored dates (the contamination column)
# ---------------------------------------------------------------------------
def test_manifest_carries_authored_dates(corpus):
    m = sc.build_manifests(corpus)
    assert len(m.private["tasks"]) == 6
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
    for task in m.private["tasks"]:
        assert iso.match(task["authored"]), task
        assert task["suspected_exposure"] is None  # null until models chosen
        assert task["visibility"] == "private"
    pinned = [t for t in m.private["tasks"] if t["subject"] == "feat: add class-a-1"]
    assert len(pinned) == 1 and pinned[0]["authored"] == PINNED_DATE
    assert m.public["schema"] == "crb.sealed-corpus.v1"
    assert m.public["apparatus_version"] == APPARATUS_VERSION
    assert m.public["repos"] == ["corpus"]


def test_missing_authored_date_is_looked_up_from_git(tmp_path):
    repo = tmp_path / "r"
    init_repo(repo)
    sha = commit(
        repo,
        {"a.py": "x = 1\n", "tests/test_a.py": "def test_a():\n    assert True\n"},
        "a",
        author_date=PINNED_DATE,
    )
    task = _task(1).with_(task_id=sha, authored="")
    record = sc.build_task_record(task, repo=GitRepo(repo))
    assert record["authored"].startswith("2020-01-02T03:04:05")
    assert sc.build_task_record(task)["authored"] == ""  # no repo: recorded honestly empty


def test_suspected_exposure_per_model_cutoff():
    authored = "2025-05-06T07:08:09+00:00"
    out = sc.suspected_exposure(
        authored, {"old": "2024-12-31", "new": "2026-01-01", "same-day": "2025-05-06"}
    )
    assert out == {"old": False, "new": True, "same-day": True}
    assert sc.suspected_exposure("", {"m": "2026-01-01"}) == {"m": None}
    assert sc.suspected_exposure("not a date", {"m": "2026-01-01"}) == {"m": None}
    assert sc.suspected_exposure(authored, {"m": "garbage"}) == {"m": None}


# ---------------------------------------------------------------------------
# deterministic split assignment
# ---------------------------------------------------------------------------
def test_split_assignment_is_deterministic(corpus):
    fractions = sc.parse_split("dev=0.4,val=0.3,sealed=0.3")
    m1 = sc.build_manifests(corpus, fractions=fractions)
    m2 = sc.build_manifests(corpus, fractions=fractions)
    # same input -> byte-identical manifests and hash
    assert sc.canonical_json(m1.public) == sc.canonical_json(m2.public)
    assert m1.manifest_hash == m2.manifest_hash
    for task in m1.private["tasks"]:
        assert task["split"] in sc.SPLITS
        # assignment is a pure function of the sha — recomputable by anyone
        assert task["split"] == sc.split_for_sha(task["task_id"], fractions)


def test_split_edge_fractions_route_every_task():
    assert sc.split_for_sha("a" * 40, sc.parse_split("dev=0,val=0,sealed=1.0")) == "sealed"
    assert sc.split_for_sha("a" * 40, sc.parse_split("dev=1.0,val=0,sealed=0")) == "dev"
    assert sc.split_for_sha("a" * 40, sc.parse_split("dev=0,val=1.0,sealed=0")) == "val"


def test_parse_split_rejects_bad_input():
    with pytest.raises(ValueError):
        sc.parse_split("dev=0.5,val=0.5")  # missing sealed
    with pytest.raises(ValueError):
        sc.parse_split("dev=0.5,val=0.4,sealed=0.4")  # sums past 1
    with pytest.raises(ValueError):
        sc.parse_split("dev=0.5,val=0.3,holdout=0.2")  # unknown split name
    with pytest.raises(ValueError):
        sc.parse_split("dev=x,val=0.5,sealed=0.5")  # non-numeric
    with pytest.raises(ValueError):
        sc.SplitFractions(dev=-0.1, val=0.6, sealed=0.5)
    assert sc.SplitFractions.parse(sc.DEFAULT_SPLIT) == sc.DEFAULT_FRACTIONS
    assert sc.DEFAULT_FRACTIONS.to_dict() == {"dev": 0.4, "val": 0.3, "sealed": 0.3}


# ---------------------------------------------------------------------------
# sealed redaction
# ---------------------------------------------------------------------------
def test_sealed_redaction_holds(corpus):
    m = sc.build_manifests(corpus, fractions=sc.parse_split("dev=0,val=0,sealed=1.0"))
    assert len(m.public["tasks"]) == 6
    serialized = sc.canonical_json(m.public)
    for task in m.public["tasks"]:
        assert task["split"] == "sealed"
        assert set(task) == set(sc.REDACTED_KEYS)  # id + split + hash only, nothing else
    # no full-detail leakage anywhere in the public manifest body
    for leak in ("feat: add", "src/class-a", "src/class-b", "tests/test_"):
        assert leak not in serialized
    # private manifest keeps full detail, and detail_hash binds it
    for task in m.private["tasks"]:
        record = {k: v for k, v in task.items() if k != "detail_hash"}
        assert task["detail_hash"] == sc.sha256_text(sc.canonical_json(record))
    # dev/val tasks are NOT redacted
    open_m = sc.build_manifests(corpus, fractions=sc.parse_split("dev=1.0,val=0,sealed=0"))
    assert all("subject" in t and "src_files" in t for t in open_m.public["tasks"])
    assert m.split_counts == {"dev": 0, "val": 0, "sealed": 6}


# ---------------------------------------------------------------------------
# commitment hash
# ---------------------------------------------------------------------------
def test_manifest_hash_reproducible_from_written_files(corpus, tmp_path):
    m = sc.build_manifests(corpus)
    out = tmp_path / "out"
    paths = sc.write_outputs(out, m)

    commitment = (out / sc.COMMITMENT).read_text()
    assert f"manifest_hash: sha256:{paths['manifest_hash']}" in commitment
    assert "UNSEALED" in commitment  # operator timestamps + commits BEFORE any model run
    assert f"apparatus_version: {APPARATUS_VERSION}" in commitment

    # an independent verifier re-derives the hash from the published file alone
    reloaded = json.loads((out / sc.PUBLIC_MANIFEST).read_text())
    assert sc.manifest_hash(reloaded) == paths["manifest_hash"]
    reloaded_private = json.loads((out / sc.PRIVATE_MANIFEST).read_text())
    assert f"private_manifest_hash: sha256:{sc.manifest_hash(reloaded_private)}" in commitment

    v = sc.verify_outputs(out)
    assert v["public_ok"] and v["private_ok"] and v["detail_ok"]
    assert v["sealed_at_set"] is False and v["manifest_hash"] == paths["manifest_hash"]


def test_verify_outputs_detects_a_tampered_manifest(corpus, tmp_path):
    out = tmp_path / "out"
    sc.write_outputs(out, sc.build_manifests(corpus))
    public = json.loads((out / sc.PUBLIC_MANIFEST).read_text())
    public["tasks"][0]["split"] = "dev" if public["tasks"][0]["split"] != "dev" else "val"
    (out / sc.PUBLIC_MANIFEST).write_text(json.dumps(public))
    assert sc.verify_outputs(out)["public_ok"] is False
    # and a sealed-at line set by the operator is recognised
    c = (
        (out / sc.COMMITMENT)
        .read_text()
        .replace(sc.UNSEALED_PLACEHOLDER, "sealed_at: 2026-01-01T00:00:00Z")
    )
    (out / sc.COMMITMENT).write_text(c)
    assert sc.verify_outputs(out)["sealed_at_set"] is True


def test_write_outputs_refuses_an_empty_corpus(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="empty corpus"):
        sc.write_outputs(out, sc.build_manifests([]))
    assert not out.exists()  # nothing written — no commitment over nothing


def test_visibility_is_validated(corpus):
    with pytest.raises(ValueError):
        sc.build_manifests(corpus, visibility="secret")
    assert sc.build_manifests(corpus, visibility="public").public["visibility"] == "public"


# ---------------------------------------------------------------------------
# stratification
# ---------------------------------------------------------------------------
def test_stratification_respects_per_cell(corpus):
    m = sc.build_manifests(corpus, per_cell=2)
    by_class: dict[str, int] = {}
    for task in m.private["tasks"]:
        by_class[task["capability_class"]] = by_class.get(task["capability_class"], 0) + 1
    assert by_class == {"class-a": 2, "class-b": 2}  # 4 class-a capped to 2; class-b intact
    assert m.public["per_cell"] == 2
    for counts in m.public["cells"].values():
        assert counts["total"] <= 2
        assert counts["total"] == sum(counts[s] for s in sc.SPLITS)
    assert set(m.public["cells"]) == {"class-a|S", "class-b|S"}
    # uncapped run keeps all 6
    uncapped = sc.build_manifests(corpus)
    assert len(uncapped.private["tasks"]) == 6 and uncapped.public["per_cell"] is None


def test_per_cell_sampling_is_deterministic_and_hash_ordered(corpus):
    a = sc.build_manifests(corpus, per_cell=2)
    b = sc.build_manifests(corpus, per_cell=2)
    assert [t["task_id"] for t in a.private["tasks"]] == [t["task_id"] for t in b.private["tasks"]]
    sampled = sc.sample_per_cell(corpus, 2)
    class_a = [t for t in corpus if t.capability_class == "class-a"]
    expected = sorted(class_a, key=lambda t: sc.sha256_text(t.task_id))[:2]
    assert [t.task_id for t in sampled if t.capability_class == "class-a"] == [
        t.task_id for t in expected
    ]
    assert sc.cell_key(corpus[0]) == "class-a|S"
