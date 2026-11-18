"""``GET /quote/mapping`` — the mapping quote served: tasks, cost, time and precision.

Navigation
----------
What it is:   ``GET /quote/mapping``'s test suite — the price, time and precision of a first
              mapping of a repository, before any spend.
What it does: Pins the served quote over the seed (mined cells, the repo-cell basis, the fixed
              statements), cell selection with per-cell n, an unknown model served as ``null``
              never 0, the deployment basis from another repository's rows and only under the
              target's checks arm and posture class, the S3 first-rung basis, the declared
              band, every 422, 404, the viewer floor, 409 ``no_tasks``, the profile fallback
              as an upper bound and only for a repository never mined, that the route writes
              nothing, that no key names an outcome or an arm, byte stability across two
              reads, the unpriced-model flag and an unreadable price table.
How:          ``make_env`` over the seed; rows appended to BETA through ``DbLedger`` in the
              seed's own way; a profile written into a config row for the fallback.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0058-mapping-quote.md
Works with:   src/crb/server/routes/quote.py (under test), src/crb/core/quote.py (the
              arithmetic), tests/fixtures/server_seed.py (the seed and ``assert_rbac``),
              tests/test_quote.py (the core suite), docs/API.md (the documented contract)
Tested by:    tests/test_server_routes_quote.py
Touch when:   never for a new repository; a parameter, an error code or a response field of the
              quote changes (mirror docs/API.md and docs/MCP.md).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, update

from crb.core import quote as q
from crb.core.capability import RepoChangeProfile
from crb.store.ledger import DbLedger
from crb.store.models import Event, Grade, Repo, Run, Task
from fixtures.posture import posture_row
from fixtures.server_seed import (
    ALPHA,
    BETA,
    BUILDER,
    MODEL,
    Env,
    assert_rbac,
    envelope,
    make_env,
)

BASE = f"/quote/mapping?repo={ALPHA}&builder={BUILDER}&model={MODEL}"
FORBIDDEN_KEY_PARTS = (
    "clean",
    "arm",
    "context",
    "verdict",
    "route",
    "pass",
    "fail",
    "reading",
    "trial",
)


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as a viewer (the quote's floor)."""
    with make_env(tmp_path, role="viewer") as e:
        yield e


def _cells(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["label"]: c for c in body["cells"]}


def _beta_rows(
    env: Env, *, arm: str = "", n: int = 4, imported: bool = False, **labels: str
) -> None:
    """``n`` rows for BETA in test.add/XS by the seed's builder and model, through the write
    path, alternating $0.01 / $0.03 and 30 s / 90 s; ``labels`` overlay the seed's own."""
    if arm:
        labels["context_arm"] = arm
    rows = [
        posture_row(
            repo=BETA,
            task_id=f"{i:040x}",
            clean=i % 2 == 0,
            tests_unmodified=True,
            target_green=i % 2 == 0,
            no_new_failures=True,
            source_changed=True,
            capability_class="test.add",
            size="XS",
            language="go",
            builder=BUILDER,
            model=MODEL,
            provider="cerebras",
            run_id="b" * 32,
            trial="r1",
            cost_usd=0.01 if i % 2 else 0.03,
            latency_s=30.0 if i % 2 else 90.0,
            tokens_in=1000,
            evidence_pack_hash=("e" * 64) if i % 2 == 0 else "",
            gold_clean=True,
            labels=labels,
        )
        for i in range(n)
    ]
    ledger = DbLedger(env.factory)
    if imported:
        ledger.import_rows(rows, imported_by="admin-1", imported_at="2026-11-18T00:00:00+00:00")
    else:
        ledger.append_many(rows)


def test_quote_serves_mined_cells_with_repo_basis(env: Env) -> None:
    r = env.get(BASE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == q.QUOTE_SCHEMA and body["availability_source"] == "mined"
    assert body["n_default"] == q.default_n() == 20
    assert body["estimate_of"] == q.ESTIMATE_OF and body["claim"] == q.CLAIM
    assert body["time_basis"] == q.TIME_BASIS and body["seen_note"] == q.SEEN_NOTE
    assert body["basis_rows"] == q.BASIS_ROWS
    assert body["run"]["ladder"] == ["r1"] and body["run"]["mode"] == "sighted"
    assert body["declared"] is None
    cells = _cells(body)
    assert set(cells) == {"bug.fix/S", "backend.route.add/M", "test.add/XS"}
    bug = cells["bug.fix/S"]
    assert bug["available"] == 4 and bug["tasks_to_run"] == 4 and bug["shortfall"] == 16
    assert bug["basis"]["tier"] == q.TIER_REPO and bug["basis"]["n_rows"] >= 2
    assert bug["cost_usd"]["expected"] == pytest.approx(4 * 0.012)
    assert bug["minutes"]["expected"] == pytest.approx(4 * 42 / 60)
    # the seed's rows all cost the same: a band with no width says so
    assert "not certainty" in bug["cost_usd"]["reason"]
    # the census rows in test.add/XS are another builder: they never price this one
    assert cells["test.add/XS"]["basis"]["tier"] == q.TIER_UNKNOWN
    assert cells["test.add/XS"]["available"] == 1
    assert body["totals"]["unpriced"] == ["test.add/XS"]
    assert body["model_priced"] is True


def test_quote_cell_selection_and_per_cell_n(env: Env) -> None:
    r = env.get(f"{BASE}&cells=bug.fix:S:3,test.add:*:5")
    assert r.status_code == 200, r.text
    cells = r.json()["cells"]
    assert [c["label"] for c in cells] == ["bug.fix/S", "test.add/XS"]
    assert [(c["requested"], c["tasks_to_run"], c["left_after"]) for c in cells] == [
        (3, 3, 1),
        (5, 1, 0),
    ]
    # the pool narrows what is available: task 6 is the only hard task
    cells = _cells(env.get(f"{BASE}&pool=hard&cells=backend.route.add:M:2").json())
    assert cells["backend.route.add/M"]["available"] == 1


def test_quote_unknown_model_is_null_with_reason(env: Env) -> None:
    body = env.get(f"/quote/mapping?repo={ALPHA}&builder={BUILDER}&model=never-run-model").json()
    for c in body["cells"]:
        assert c["basis"]["tier"] == q.TIER_UNKNOWN
        assert c["cost_usd"]["expected"] is None and c["cost_usd"]["low"] is None
        assert c["cost_usd"]["reason"]
    t = body["totals"]
    assert t["cost_usd_low"] is None and t["cost_usd_high"] is None and t["cells_priced"] == 0


def test_quote_uses_other_repository_rows_when_repo_has_none(env: Env) -> None:
    _beta_rows(env)
    c = _cells(env.get(f"{BASE}&cells=test.add:XS:5").json())["test.add/XS"]
    assert c["basis"]["tier"] == q.TIER_DEPLOYMENT and c["basis"]["n_repos"] == 1
    assert c["basis"]["n_rows"] == 4 and c["basis"]["tag"].startswith("[hypothesis]")
    assert c["tasks_to_run"] == 1
    assert c["cost_usd"]["expected"] == pytest.approx(0.02)
    assert c["minutes"]["expected"] == pytest.approx(1.0)


def test_quote_never_prices_from_imported_rows(env: Env) -> None:
    """An imported row is someone else's measurement: it prices no cell, in either tier."""
    _beta_rows(env, imported=True)
    assert all(r.imported for r in DbLedger(env.factory).rows(repo=BETA))
    c = _cells(env.get(f"{BASE}&cells=test.add:XS:5").json())["test.add/XS"]
    assert c["basis"]["tier"] not in (q.TIER_DEPLOYMENT, q.TIER_REPO)
    assert c["basis"]["n_rows"] == 0


def test_quote_declared_band_echoed_and_tagged(env: Env) -> None:
    body = env.get(f"{BASE}&cells=test.add:XS:5&declared=0.01:0.05").json()
    assert body["declared"] == {"low": 0.01, "high": 0.05}
    c = _cells(body)["test.add/XS"]
    assert c["basis"]["tier"] == q.TIER_DECLARED and c["basis"]["tag"].startswith("[declared]")
    assert c["cost_usd"]["low"] == pytest.approx(0.01) and c["cost_usd"]["high"] == 0.05
    assert c["cost_usd"]["expected"] is None and c["minutes"]["expected"] is None


@pytest.mark.parametrize(
    "query",
    [
        f"{BASE}&cells=bug.fix",
        f"{BASE}&cells=bug.fix:S:0",
        # a zero item is refused before repeated items are summed
        f"{BASE}&cells=bug.fix:S:0,bug.fix:S:2",
        f"{BASE}&cells=bug.fix:S:1001",
        f"{BASE}&n=0",
        f"{BASE}&n=1001",
        f"{BASE}&declared=0.5:0.1",
        f"{BASE}&declared=cheap",
        f"{BASE}&declared=-1:2",
        # finite, but scaled by the attempts it would overflow to infinity
        f"{BASE}&declared=1e308:1e308",
        f"{BASE}&pool=weird",
        f"{BASE}&n=5&cells=bug.fix:S:3",
        f"/quote/mapping?repo={ALPHA}&builder={BUILDER}",
    ],
)
def test_quote_validation_errors(env: Env, query: str) -> None:
    r = env.get(query)
    assert r.status_code == 422, (query, r.text)
    assert envelope(r)["code"] == "validation_error"


def test_quote_unknown_repo_404(env: Env) -> None:
    r = env.get(f"/quote/mapping?repo=nope&builder={BUILDER}&model={MODEL}")
    assert r.status_code == 404 and envelope(r)["code"] == "not_found"


def test_quote_rbac(env: Env) -> None:
    assert_rbac(env, "GET", BASE, min_role="viewer")


def test_quote_no_tasks_no_profile_409(env: Env) -> None:
    r = env.get(f"/quote/mapping?repo={BETA}&builder={BUILDER}&model={MODEL}")
    assert r.status_code == 409 and envelope(r)["code"] == "no_tasks"


def _save_profile(env: Env, repo_name: str) -> None:
    profile = RepoChangeProfile(
        repo=repo_name,
        n_commits=9,
        examined=12,
        skipped=3,
        cells={("bug.fix", "S"): 7, ("docs.update", "S"): 2},
    )
    with env.factory() as s:
        repo = s.get(Repo, repo_name)
        assert repo is not None
        repo.config_json = {
            **dict(repo.config_json or {}),
            "profile": {"profile": profile.to_dict()},
        }
        s.commit()


def test_quote_falls_back_to_profile_counts_as_upper_bound(env: Env) -> None:
    _save_profile(env, BETA)
    body = env.get(f"/quote/mapping?repo={BETA}&builder={BUILDER}&model={MODEL}").json()
    assert body["availability_source"] == "profile"
    assert body["availability_note"].startswith("[upper bound]")
    cells = _cells(body)
    assert cells["bug.fix/S"]["available"] == 7 and cells["bug.fix/S"]["tasks_to_run"] == 7


def test_quote_profile_fallback_refuses_a_pool(env: Env) -> None:
    # a change profile counts commits, not pools: it cannot answer a pool question
    _save_profile(env, BETA)
    r = env.get(f"/quote/mapping?repo={BETA}&builder={BUILDER}&model={MODEL}&pool=standard")
    assert r.status_code == 409 and envelope(r)["code"] == "no_tasks"
    assert "pool" in envelope(r)["message"]


def test_quote_never_falls_back_when_tasks_are_mined(env: Env) -> None:
    # ALPHA is mined; its one hard task stops being gold-clean, so the hard pool is empty.
    # Its profile must not stand in: it would quote seven bug fixes that do not exist.
    _save_profile(env, ALPHA)
    with env.factory() as s:
        s.execute(
            update(Task).where(Task.repo == ALPHA, Task.pool == "hard").values(gold_clean=False)
        )
        s.commit()
    r = env.get(f"{BASE}&pool=hard")
    assert r.status_code == 409 and envelope(r)["code"] == "no_tasks"
    assert "mined" in envelope(r)["message"] and envelope(r)["detail"]["pool"] == "hard"
    # a named cell is quoted at nothing available, from the mined tasks
    body = env.get(f"{BASE}&pool=hard&cells=backend.route.add:M:2").json()
    assert body["availability_source"] == "mined"
    c = _cells(body)["backend.route.add/M"]
    assert (c["available"], c["tasks_to_run"], c["shortfall"]) == (0, 0, 2)


def _counts(env: Env) -> tuple[int, int, int, Any]:
    with env.factory() as s:
        grades = s.scalar(select(func.count()).select_from(Grade))
        runs = s.scalar(select(func.count()).select_from(Run))
        events = s.scalar(select(func.count()).select_from(Event))
        repo = s.get(Repo, ALPHA)
        assert repo is not None
        return int(grades or 0), int(runs or 0), int(events or 0), dict(repo.config_json or {})


def test_quote_writes_nothing(env: Env) -> None:
    before = _counts(env)
    assert env.get(f"{BASE}&cells=bug.fix:S:3&declared=0.01:0.02").status_code == 200
    assert env.get(BASE).status_code == 200
    assert _counts(env) == before


def _keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def test_quote_response_carries_no_outcome_or_arm_field(env: Env) -> None:
    _beta_rows(env)
    r = env.get(f"{BASE}&declared=0.01:0.02")
    assert r.status_code == 200, r.text  # an error envelope would pass the walk vacuously
    body = r.json()
    bad = {k for k in _keys(body) for part in FORBIDDEN_KEY_PARTS if part in k.lower()}
    assert not bad, bad


@pytest.mark.parametrize(
    ("labels", "tier"),
    [
        ({}, q.TIER_DEPLOYMENT),
        # another arm carries another brief: never a first mapping's cost
        ({"arm": "S1@t1"}, q.TIER_UNKNOWN),
        ({"arm": "S3+L"}, q.TIER_UNKNOWN),
        # another checks arm or posture class than the target's is never pooled
        ({"checks": "fmt=1"}, q.TIER_UNKNOWN),
        ({"posture_class": "docker/copy/sealed"}, q.TIER_UNKNOWN),
    ],
)
def test_quote_basis_is_the_first_mapping_arm_under_target_checks_and_posture(
    env: Env, labels: dict[str, str], tier: str
) -> None:
    _beta_rows(env, **labels)
    r = env.get(f"{BASE}&cells=test.add:XS:5")
    assert r.status_code == 200, r.text
    assert _cells(r.json())["test.add/XS"]["basis"]["tier"] == tier


def test_quote_is_byte_stable_across_two_reads(env: Env) -> None:
    ra, rb = env.get(BASE), env.get(BASE)
    assert ra.status_code == rb.status_code == 200, (ra.text, rb.text)
    a, b = ra.content, rb.content
    assert a == b and b"as_of" not in a


@pytest.mark.parametrize(
    ("labels", "tier"), [({"checks": "fmt=1"}, q.TIER_UNKNOWN), ({}, q.TIER_DEPLOYMENT)]
)
def test_quote_reads_other_rows_under_the_target_checks_arm(
    env: Env, labels: dict[str, str], tier: str
) -> None:
    # BETA grades with the format step on; ALPHA does not. BETA's rows are read under
    # ALPHA's arm, never under BETA's own: its format-step rows are not ALPHA's cost
    with env.factory() as s:
        beta = s.get(Repo, BETA)
        assert beta is not None
        beta.config_json = {**dict(beta.config_json or {}), "checks": {"format_step": True}}
        s.commit()
    _beta_rows(env, **labels)
    c = _cells(env.get(f"{BASE}&cells=test.add:XS:5").json())["test.add/XS"]
    assert c["basis"]["tier"] == tier


def test_quote_flags_unpriced_model(env: Env) -> None:
    body = env.get(f"/quote/mapping?repo={ALPHA}&builder={BUILDER}&model=azure:my-deploy").json()
    assert body["model_priced"] is False and body["model_priced_reason"]


def test_quote_unreadable_price_table_is_unknown_not_false(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "pricing.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("CRB_PRICING_JSON", str(bad))
    r = env.get(BASE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_priced"] is None and "could not be read" in body["model_priced_reason"]
