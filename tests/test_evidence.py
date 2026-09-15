"""crb.core.evidence — the per-task pack: stable hash, verification, tamper detection.

Navigation
----------
What it is:   The evidence pack's test suite — canonical JSON, the stable pack hash, verification
              and tamper detection.
What it does: Pins that ``canonical_json`` is key-order independent, that the pack hash is stable
              under key order and repeat but changes with content, the ``to_dict`` shape, a JSON
              round trip through ``verify_pack``, that every mutated field fails verification, and
              that a pack without a hash never verifies.
How:          Small in-memory packs over a fixed ``TaskSpec`` and ``GradeResult``; the mutations
              are parametrised.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/evidence.py (under test), src/crb/core/ledger.py (the row that
              carries ``evidence_pack_hash``), src/crb/core/version.py (the apparatus stamp),
              tests/test_server_routes_grades.py (the pack served and re-verified by the API)
Tested by:    tests/test_evidence.py
Touch when:   a field is added to the pack (it is hashed — add it to the mutation table and note
              the apparatus consequence in docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from crb.core import evidence as ev
from crb.core.grade import Belts, GradeResult
from crb.core.spec import TaskSpec
from crb.core.version import APPARATUS_VERSION, __version__

SHA = "b7c6251293a287542ac8568cad7505b710fa3532"


def _task() -> TaskSpec:
    return TaskSpec(
        task_id=SHA,
        repo="r",
        subject="s",
        authored="2026-01-01T00:00:00+00:00",
        test_files=["tests/test_a.py"],
        src_files=["src/a.py"],
        target_tests=["tests/test_a.py"],
        belt_scope=["tests/"],
        red_checked=True,
        gold_clean=True,
    )


def _grade(clean: bool = True) -> GradeResult:
    belts = Belts(True, True, True, True) if clean else Belts(True, False)
    return GradeResult(
        SHA,
        "r",
        "sighted",
        clean=clean,
        belts=belts,
        note="" if clean else "target not green (rc=1)",
    )


def _pack(**kw: Any) -> ev.EvidencePack:
    base: dict[str, Any] = {
        "task": _task(),
        "grade": _grade(),
        "apparatus": ev.ApparatusStamp(runner="pytest", executor={"executor": "local"}),
        "builder": ev.BuilderRef(name="agentic", model="m", provider="p", cost_usd=0.0123456789),
        "run_id": "run-1",
        "trial": "t1",
        "actor": "ci",
        "created": "2026-09-13T12:00:00+00:00",
        "notes": {"k": "v"},
    }
    base.update(kw)
    return ev.EvidencePack(**base)


def test_canonical_json_is_key_order_independent() -> None:
    a = ev.canonical_json({"b": 1, "a": {"d": 2, "c": [3, {"z": 1, "y": 2}]}})
    b = ev.canonical_json({"a": {"c": [3, {"y": 2, "z": 1}], "d": 2}, "b": 1})
    assert a == b == '{"a":{"c":[3,{"y":2,"z":1}],"d":2},"b":1}'
    assert (
        ev.sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", ev.utc_now_iso())


def test_apparatus_stamp_defaults_and_to_dict() -> None:
    s = ev.ApparatusStamp()
    assert s.apparatus_version == APPARATUS_VERSION and s.crb_version == __version__
    assert s.grader == "crb.core.grade"
    d = ev.ApparatusStamp(runner="go", executor={"executor": "docker"}, extra={"x": 1}).to_dict()
    assert (
        d["runner"] == "go" and d["executor"] == {"executor": "docker"} and d["extra"] == {"x": 1}
    )
    assert set(d) == {
        "apparatus_version",
        "crb_version",
        "grader",
        "runner",
        "executor",
        "corpus_sha",
        "policy_version",
        "extra",
    }


def test_builder_ref_round_trip_and_rounding() -> None:
    b = ev.BuilderRef(
        name="agentic",
        model="gpt-oss-120b",
        provider="cerebras",
        mode="blind",
        attempts=2,
        turns=7,
        tokens_in=1000,
        tokens_out=200,
        cost_usd=0.0123456789,
        latency_s=12.34567,
        transcript_ref="s3://bucket/key",
        budget={"max_turns": 10},
        note="n",
    )
    d = b.to_dict()
    assert d["cost_usd"] == 0.012346 and d["latency_s"] == 12.346
    json.dumps(d)
    back = ev.BuilderRef.from_dict({**d, "unknown": "ignored"})
    assert back.model == "gpt-oss-120b" and back.budget == {"max_turns": 10} and back.attempts == 2
    assert back.cost_usd == 0.012346  # rounded through the round trip, by design
    assert ev.BuilderRef.from_dict({}) == ev.BuilderRef()
    assert ev.BuilderRef().mode == "sighted"


def test_pack_hash_is_stable_under_key_order_and_repeat() -> None:
    p = _pack()
    h1 = p.pack_hash
    assert len(h1) == 64
    assert p.pack_hash == h1
    body = p.body()
    shuffled = json.loads(json.dumps(dict(reversed(list(body.items())))))
    assert ev.sha256_text(ev.canonical_json(shuffled)) == h1
    assert _pack().pack_hash == h1  # same content → same hash


def test_pack_hash_changes_with_content() -> None:
    assert _pack().pack_hash != _pack(notes={"k": "w"}).pack_hash
    assert _pack().pack_hash != _pack(grade=_grade(clean=False)).pack_hash
    assert _pack().pack_hash != _pack(builder=None).pack_hash
    assert _pack().pack_hash != _pack(created="2026-09-13T12:00:01+00:00").pack_hash


def test_pack_body_and_to_dict_shape() -> None:
    p = _pack()
    d = p.to_dict()
    assert d["schema"] == ev.EVIDENCE_SCHEMA == "crb.evidence.v1"
    assert d["task"]["task_id"] == SHA
    assert d["grade"]["clean"] is True
    assert d["apparatus"]["runner"] == "pytest"
    assert d["builder"]["name"] == "agentic"
    assert d["run_id"] == "run-1" and d["trial"] == "t1" and d["actor"] == "ci"
    assert d["notes"] == {"k": "v"}
    assert d["pack_hash"] == p.pack_hash
    assert "pack_hash" not in p.body()
    assert _pack(builder=None).to_dict()["builder"] is None


def test_verify_pack_round_trip_through_json() -> None:
    p = _pack()
    text = p.to_json()
    loaded = json.loads(text)
    assert ev.verify_pack(loaded)
    assert ev.verify_pack(json.loads(json.dumps(loaded, sort_keys=False)))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["grade"].__setitem__("clean", False),
        lambda d: d["grade"].__setitem__("no_new_failures", False),
        lambda d: d["task"].__setitem__("gold_clean", False),
        lambda d: d["builder"].__setitem__("cost_usd", 0.0),
        lambda d: d["notes"].__setitem__("added", 1),
        lambda d: d.__setitem__("pack_hash", "0" * 64),
        lambda d: d.pop("actor"),
    ],
)
def test_tampered_pack_fails_verification(mutate: Any) -> None:
    d = json.loads(_pack().to_json())
    assert ev.verify_pack(d)
    mutate(d)
    assert not ev.verify_pack(d)


def test_verify_pack_without_hash_is_false() -> None:
    d = _pack().body()
    assert not ev.verify_pack(d)


def test_pack_default_created_is_now_and_notes_copied() -> None:
    notes = {"a": 1}
    p = ev.EvidencePack(_task(), _grade(), ev.ApparatusStamp(), notes=notes)
    notes["a"] = 2
    assert p.notes == {"a": 1}
    assert p.created.endswith("+00:00")
    assert p.builder is None and p.run_id == ""
