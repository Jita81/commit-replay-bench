"""``/campaigns`` and ``POST /runs`` under a campaign (G-957): the product holds the ceiling.

Until G-957 the only money limit the product kept was one run's ``max_cost_usd``; a
campaign's ceiling — Wave 3's £80 in two stages, £40 released — was held by the operator's
hand. Here the campaign is a record (its ceiling in pounds, its rate, its decision, hashed into
its id), every run filed under it is admitted only while spent plus held plus the run's own
cap and headroom stay under the released line — the run's rows AND its ``S1`` test author's
calls counted (P-775) — and a run that would pass it is refused 409 ``campaign_ceiling`` with
nothing queued and nothing spent.

Navigation
----------
What it is:   The route suite of campaigns and of a run filed under one.
What it does: Registers a campaign (201; its line $54.00 at 1.35; a name registered twice is
              409), releases a stage (the line rises to $108.00; a release that lowers it or
              passes the ceiling is 409), serves it to a viewer (404 for an unknown id or a
              record that does not re-hash); admits runs until the line and refuses the next
              with nothing queued, counts rows and author calls in the tally, holds an
              active run's admitted headroom while it is the larger and none for a finished
              one (its ``headroom_usd`` 0.00, its ``admitted_headroom_usd`` kept), stops on
              a cost not known and on an overrun read against the headroom a run was
              admitted with (a first attempt dearer than the $5.00 held), refuses a run
              without a cap, an unbounded ``S1`` run, a non-build kind and a run of a
              campaign-named reading filed under no campaign or another one
              (``campaign_required``, DL-382), admits no more than the line under concurrent
              submits, and shows a campaign-named reading reads a run's rows only when the
              campaign admitted the run (a run posted without ``campaign_id`` is invisible to
              it, so each commit is read by its first admitted attempt and none leaves for a
              run outside; a legacy reading counts it as before).
How:          ``make_env`` over the seed; ``fixture_gold`` rungs (no credential, priced
              without a table); rows through ``DbLedger`` and author calls through
              ``append_event``; four threads through ``admit_under_campaign``; the admissions
              reader and ``GET /readings`` under a campaign also on the ``backend`` fixture
              (PostgreSQL when it is configured).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md
Works with:   src/crb/server/routes/campaigns.py (the routes under test),
              src/crb/server/campaigns.py (the store readers and the served view),
              src/crb/server/routes/runs.py (``campaign_refusal``, ``admit_under_campaign``),
              src/crb/core/campaign.py (the tally and its refusal codes),
              src/crb/server/reading_book.py (``load_readings`` reads the admissions),
              tests/conftest_store.py (the backends),
              docs/API.md#campaigns-a-campaigns-money-ceiling (the routes documented)
Tested by:    tests/test_server_campaigns.py
Touch when:   never for a new repository; a campaign route, its refusals or the admission change.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from crb.core.campaign import CAMPAIGN_ADMITTED, CAMPAIGN_REGISTERED
from crb.core.reading import arm_reading
from crb.server.app import create_app
from crb.server.campaigns import admitted_runs
from crb.server.deps import ApiError
from crb.server.reading_book import load_readings
from crb.server.routes.runs import admit_under_campaign, new_run
from crb.server.schemas import RunCreateRequest
from crb.store.db import init_db
from crb.store.events import append_event
from crb.store.ledger import DbLedger
from crb.store.models import Event, Run
from fixtures.proven import CELL, LATER, write_reading
from fixtures.readings import sealed_row
from fixtures.server_seed import (
    ALPHA,
    Env,
    add_users,
    assert_rbac,
    envelope,
    login,
    make_env,
    make_settings,
    seed,
)

try:  # the store backends: SQLite always, PostgreSQL when CRB_TEST_POSTGRES_URL is set
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401

WAVE3 = {
    "name": "wave-3",
    "ceiling_gbp": 80,
    "released_gbp": 40,
    "rate_usd_per_gbp": 1.35,
    "decision": "DECISION 8 (2026-10-11): stage 1 £40 yes",
}
#: A build run on a rung that needs no credential and whose price is known without a table.
GOLD = {"repo": ALPHA, "kind": "replay", "builder": "fixture_gold", "model": "gold"}
#: An S1 blind replay on the same rung, its test author another fixture model.
S1 = {**GOLD, "kind": "blind", "arm": "S1", "test_author": "fixture_gold:author"}
#: Three commits an S1 run names (git shas).
SHAS = ["1" * 40, "2" * 40, "3" * 40]


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, role="operator") as e:
        yield e


def _register(env: Env, **kw: Any) -> dict[str, Any]:
    r = env.post("/campaigns", json={**WAVE3, **kw})
    assert r.status_code == 201, r.text
    return dict(r.json())


def _admitted(env: Env, campaign_id: str) -> list[dict[str, Any]]:
    with env.factory() as s:
        evs = s.execute(
            select(Event)
            .where(Event.trace_id == campaign_id, Event.action == CAMPAIGN_ADMITTED)
            .order_by(Event.id)
        ).scalars()
        return [dict(e.payload_json) for e in evs]


def _runs(env: Env) -> set[str]:
    with env.factory() as s:
        return {r.id for r in s.execute(select(Run)).scalars()}


def _row(run_id: str, commit: str, cost: float, *, known: bool = True) -> Any:
    return sealed_row(
        commit,
        repo=ALPHA,
        run_id=run_id,
        cost_usd=cost,
        labels={"cost_known": "true" if known else "false"},
    )


def test_a_campaign_is_registered_with_its_line_in_pounds_at_its_rate(env: Env) -> None:
    out = _register(env)
    assert out["campaign_id"].startswith("cmp_") and len(out["campaign_id"]) == 28
    assert out["ceiling_gbp"] == 80 and out["released_gbp"] == 40
    assert out["rate_usd_per_gbp"] == 1.35 and out["actor"]
    assert out["line_gbp"] == 40 and out["line_usd"] == 54.0 and out["ceiling_usd"] == 108.0
    assert out["spent_usd"] == 0 and out["held_usd"] == 0 and out["left_usd"] == 54.0
    assert out["stopped"] is None and out["runs"] == [] and out["releases"] == []
    assert env.get(f"/campaigns/{out['campaign_id']}").json() == out
    assert [c["campaign_id"] for c in env.get("/campaigns").json()["items"]] == [out["campaign_id"]]
    again = env.post("/campaigns", json={**WAVE3, "ceiling_gbp": 90})
    assert again.status_code == 409 and envelope(again)["code"] == "campaign_exists"


@pytest.mark.parametrize(
    "bad",
    [
        {"released_gbp": 90},  # more released than the ceiling
        {"rate_usd_per_gbp": 0},
        {"ceiling_gbp": -1},
        {"decision": "  "},
        {"name": ""},
    ],
)
def test_a_campaign_the_tally_could_not_keep_is_refused(env: Env, bad: dict[str, Any]) -> None:
    r = env.post("/campaigns", json={**WAVE3, **bad})
    assert r.status_code == 422, r.text
    assert env.get("/campaigns").json()["items"] == []


def test_a_release_raises_the_line_never_down_and_never_above_the_ceiling(env: Env) -> None:
    cid = _register(env)["campaign_id"]
    for wanted in (40, 30, 81):
        r = env.post(f"/campaigns/{cid}/release", json={"released_gbp": wanted, "decision": "x"})
        assert r.status_code == 409, (wanted, r.text)
        assert envelope(r)["code"] == "campaign_release_invalid"
    r = env.post(f"/campaigns/{cid}/release", json={"released_gbp": 80, "decision": "stage 2"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["line_gbp"] == 80 and out["line_usd"] == 108.0
    assert [x["released_gbp"] for x in out["releases"]] == [80]
    assert out["releases"][0]["previous_gbp"] == 40
    r = env.post(
        f"/campaigns/{'cmp_' + '0' * 24}/release", json={"released_gbp": 80, "decision": "x"}
    )
    assert r.status_code == 404 and envelope(r)["code"] == "campaign_unknown"


def test_a_viewer_reads_campaigns_and_only_an_operator_writes_them(env: Env) -> None:
    cid = _register(env)["campaign_id"]
    assert_rbac(env, "GET", "/campaigns", min_role="viewer")
    assert_rbac(env, "GET", f"/campaigns/{cid}", min_role="viewer")
    assert_rbac(env, "POST", "/campaigns", min_role="operator", json={**WAVE3, "name": "w4"})
    unknown = env.get(f"/campaigns/{'cmp_' + 'f' * 24}")
    assert unknown.status_code == 404 and envelope(unknown)["code"] == "campaign_unknown"


def test_runs_are_admitted_until_the_line_and_the_next_is_refused_with_nothing_queued(
    env: Env,
) -> None:
    """$54.00 line, nothing priced yet (headroom $5.00): a $20 run holds $25, a second
    $25 — $50 held, $4 left — so a third run capped at $0.01 would pass the line."""
    cid = _register(env)["campaign_id"]
    ids = []
    for _ in range(2):
        r = env.post("/runs", json={**GOLD, "max_cost_usd": 20, "campaign_id": cid})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "queued"
        ids.append(r.json()["id"])
    with env.factory() as s:
        run = s.get(Run, ids[0])
        assert run is not None and run.params_json["campaign_id"] == cid
    admitted = _admitted(env, cid)
    assert [a["run_id"] for a in admitted] == ids
    assert admitted[1]["held_usd"] == 25.0 and admitted[1]["left_usd_after"] == 4.0
    before = _runs(env)
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 0.01, "campaign_id": cid})
    assert r.status_code == 409, r.text
    err = envelope(r)
    assert err["code"] == "campaign_ceiling" and "nothing was queued" in err["message"]
    assert err["detail"]["left_usd"] == 4.0 and err["detail"]["headroom_usd"] == 5.0
    assert _runs(env) == before and len(_admitted(env, cid)) == 2
    view = env.get(f"/campaigns/{cid}").json()
    assert view["held_usd"] == 50.0 and view["left_usd"] == 4.0
    assert [x["run_id"] for x in view["runs"]] == ids
    # a run that finished releases what was held for it; a cancelled one too
    with env.factory() as s:
        for rid in ids:
            got = s.get(Run, rid)
            assert got is not None
            got.status = "cancelled"
        s.commit()
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 20, "campaign_id": cid})
    assert r.status_code == 201, r.text


def test_the_tally_counts_each_runs_rows_and_its_s1_authors_calls(env: Env) -> None:
    """P-775's hole closed at the campaign: an S1 replay's author writes no ledger row,
    so its calls are read from its ``author.attempt`` events and counted as spend. Once the
    run finishes the view holds nothing for it — ``headroom_usd`` reads 0.00 — while
    ``admitted_headroom_usd`` keeps the figure it was admitted with."""
    cid = _register(env)["campaign_id"]
    r = env.post("/runs", json={**S1, "max_cost_usd": 10, "task_ids": SHAS, "campaign_id": cid})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    admitted = _admitted(env, cid)[0]
    # $5.00 before a priced attempt, plus 3 commits x $0.15 before a priced author call
    assert admitted["s1"] is True and admitted["commits"] == 3
    assert admitted["headroom_usd"] == pytest.approx(5.45)
    DbLedger(env.factory).append(_row(rid, SHAS[0], 1.25))
    for cost in (0.08, 0.12):
        append_event(
            env.factory,
            trace_id=rid,
            stage="factory",
            action="author.attempt",
            payload={"cost_usd": cost, "cost_known": True},
        )
    view = env.get(f"/campaigns/{cid}").json()
    assert view["spent_usd"] == pytest.approx(1.45)
    assert view["authoring_usd"] == pytest.approx(0.20)
    assert view["dearest_attempt_usd"] == 1.25 and view["dearest_author_call_usd"] == 0.12
    run = view["runs"][0]
    assert run["commits_done"] == 1 and run["spent_usd"] == pytest.approx(1.45)
    # held: cap less spent (10 - 1.45), plus the larger of the $5.45 it was admitted with
    # and its headroom now (1.25 and 2 commits left x 0.12 = $1.49)
    assert run["admitted_headroom_usd"] == pytest.approx(5.45)
    assert run["headroom_usd"] == pytest.approx(5.45)
    assert view["held_usd"] == pytest.approx(8.55 + 5.45)
    assert view["left_usd"] == pytest.approx(54.0 - 1.45 - 14.0)
    # once it has finished the run holds nothing: its headroom now reads $0.00 while the
    # $5.45 it was admitted with stays on the record the overrun stop reads against
    with env.factory() as s:
        got = s.get(Run, rid)
        assert got is not None
        got.status = "succeeded"
        s.commit()
    done = env.get(f"/campaigns/{cid}").json()
    run = done["runs"][0]
    assert run["status"] == "succeeded"
    assert run["headroom_usd"] == 0.0
    assert run["admitted_headroom_usd"] == pytest.approx(5.45)
    assert done["held_usd"] == 0.0
    assert done["left_usd"] == pytest.approx(54.0 - 1.45)


def test_a_cost_the_tally_cannot_know_stops_the_campaign(env: Env) -> None:
    cid = _register(env)["campaign_id"]
    rid = env.post("/runs", json={**S1, "max_cost_usd": 5, "limit": 2, "campaign_id": cid}).json()[
        "id"
    ]
    append_event(
        env.factory,
        trace_id=rid,
        stage="factory",
        action="author.attempt",
        payload={"cost_usd": 0.0, "cost_known": False},
    )
    view = env.get(f"/campaigns/{cid}").json()
    assert view["stopped"]["code"] == "campaign_cost_unknown"
    assert view["stopped"]["run_ids"] == [rid]
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 1, "campaign_id": cid})
    assert r.status_code == 409 and envelope(r)["code"] == "campaign_cost_unknown"
    assert len(_admitted(env, cid)) == 1


def test_a_run_that_overran_its_cap_and_admitted_headroom_stops_the_campaign(env: Env) -> None:
    """A $1.00 run admitted with the $5.00 held before any priced attempt may reach $6.00;
    its one attempt cost $6.01. That attempt is now the campaign's dearest, so the headroom
    NOW ($6.01) would cover it — the overrun is read against what it was admitted with."""
    cid = _register(env)["campaign_id"]
    rid = env.post("/runs", json={**GOLD, "max_cost_usd": 1, "campaign_id": cid}).json()["id"]
    assert _admitted(env, cid)[0]["headroom_usd"] == 5.0
    DbLedger(env.factory).append(_row(rid, "c1", 6.01))
    view = env.get(f"/campaigns/{cid}").json()
    assert view["stopped"]["code"] == "campaign_overrun"
    assert view["stopped"]["run_ids"] == [rid]
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 1, "campaign_id": cid})
    assert r.status_code == 409 and envelope(r)["code"] == "campaign_overrun"
    assert envelope(r)["detail"]["run_ids"] == [rid]


def test_a_first_attempt_dearer_than_the_five_dollars_held_stops_the_campaign(env: Env) -> None:
    """The overshoot the stop exists for: others spent $48.90 (no attempt dearer than
    $5.00); a run is admitted at a $0.10 cap plus $5.00 headroom — exactly the $54.00 line —
    and its first attempt costs $9.00. The campaign has spent $57.90 of $54.00: the view
    shows the stop and the next run under it is refused ``campaign_overrun``."""
    cid = _register(env)["campaign_id"]
    first = env.post("/runs", json={**GOLD, "max_cost_usd": 45, "campaign_id": cid}).json()["id"]
    for i in range(9):
        DbLedger(env.factory).append(_row(first, f"a{i}", 5.0))
    DbLedger(env.factory).append(_row(first, "a9", 3.9))
    with env.factory() as s:
        got = s.get(Run, first)
        assert got is not None
        got.status = "succeeded"
        s.commit()
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 0.10, "campaign_id": cid})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    admitted = _admitted(env, cid)[-1]
    assert admitted["headroom_usd"] == 5.0 and admitted["left_usd_after"] == pytest.approx(0.0)
    DbLedger(env.factory).append(_row(rid, "b0", 9.0))
    view = env.get(f"/campaigns/{cid}").json()
    assert view["spent_usd"] == pytest.approx(57.90)
    assert view["stopped"] is not None and view["stopped"]["code"] == "campaign_overrun"
    assert view["stopped"]["run_ids"] == [rid]
    before = _runs(env)
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 0.01, "campaign_id": cid})
    assert r.status_code == 409, r.text
    assert envelope(r)["code"] == "campaign_overrun"
    assert envelope(r)["detail"] == {"campaign_id": cid, "run_ids": [rid]}
    assert _runs(env) == before and len(_admitted(env, cid)) == 2


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({**GOLD}, 422, "campaign_cap_required"),
        ({**S1, "max_cost_usd": 5}, 422, "campaign_s1_unbounded"),
    ],
)
def test_a_run_the_campaign_could_not_hold_is_refused_before_anything_is_queued(
    env: Env, body: dict[str, Any], status: int, code: str
) -> None:
    cid = _register(env)["campaign_id"]
    before = _runs(env)
    r = env.post("/runs", json={**body, "campaign_id": cid})
    assert r.status_code == status, r.text
    assert envelope(r)["code"] == code
    assert _runs(env) == before and _admitted(env, cid) == []


def test_a_run_under_no_verified_campaign_is_refused(env: Env) -> None:
    before = _runs(env)
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 5, "campaign_id": "cmp_" + "a" * 24})
    assert r.status_code == 404 and envelope(r)["code"] == "campaign_unknown"
    bad = env.post("/runs", json={**GOLD, "max_cost_usd": 5, "campaign_id": "wave-3"})
    assert bad.status_code == 422
    mine = env.post("/runs", json={"repo": ALPHA, "kind": "mine", "campaign_id": "cmp_" + "a" * 24})
    assert mine.status_code == 422 and "campaign_id applies to build runs only" in mine.text
    assert _runs(env) == before


def test_a_run_of_a_reading_that_names_a_campaign_is_filed_under_that_campaign(env: Env) -> None:
    """DL-382: a reading names its campaign at birth, so every run of it spends under that
    campaign's ceiling. A run of it filed under no campaign, or under another verified one,
    is refused 409 ``campaign_required`` naming the reading and its campaign, with nothing
    queued and no admission written; filed under its own, it is admitted. A reading under no
    campaign takes runs as before."""
    env.settings.builder.executor = "docker"
    cid = _register(env)["campaign_id"]
    other = _register(env, name="wave-4")["campaign_id"]
    reading = write_reading(env.factory, ["1" * 40], repo=ALPHA, campaign_id=cid)
    filed = {**GOLD, "executor": "docker", "reading_id": reading.reading_id, "max_cost_usd": 5}
    before = _runs(env)
    for body in (filed, {**filed, "campaign_id": other}):
        r = env.post("/runs", json=body)
        assert r.status_code == 409, r.text
        err = envelope(r)
        assert err["code"] == "campaign_required" and "nothing was queued" in err["message"]
        assert err["detail"] == {"reading_id": reading.reading_id, "campaign_id": cid}
    assert _runs(env) == before and _admitted(env, cid) == [] and _admitted(env, other) == []
    r = env.post("/runs", json={**filed, "campaign_id": cid})
    assert r.status_code == 201, r.text
    assert [a["run_id"] for a in _admitted(env, cid)] == [r.json()["id"]]
    with env.factory() as s:
        run = s.get(Run, r.json()["id"])
        assert run is not None
        assert (run.params_json["reading_id"], run.params_json["campaign_id"]) == (
            reading.reading_id,
            cid,
        )
    legacy = write_reading(env.factory, ["2" * 40], repo=ALPHA)
    r = env.post("/runs", json={**filed, "reading_id": legacy.reading_id})
    assert r.status_code == 201, r.text


def test_a_run_outside_a_readings_campaign_writes_rows_the_reading_never_counts(env: Env) -> None:
    """DL-382, the reading's side: a run of a campaign-named reading's pool commit posted
    WITHOUT the campaign's ``campaign_id`` is queued outside the campaign — no
    ``campaign.admitted`` event names it — and its sealed row is invisible to the reading,
    however clean: it counts nothing and makes no commit leave, so the commit stays pending
    until a run admitted under the campaign attempts it, and that row counts. A reading under
    no campaign counts a loose run's row as before."""
    env.settings.builder.executor = "docker"
    cid = _register(env)["campaign_id"]
    sha, inside, plain = "1" * 40, "3" * 40, "2" * 40
    named = write_reading(
        env.factory, [sha, inside], repo=ALPHA, campaign_id=cid, hierarchy=("S3",)
    )
    legacy = write_reading(env.factory, [plain], repo=ALPHA, hierarchy=("S3",))
    loose = env.post("/runs", json={**GOLD, "executor": "docker", "task_ids": [sha, plain]})
    assert loose.status_code == 201, loose.text
    assert _admitted(env, cid) == []
    filed = {**GOLD, "executor": "docker", "task_ids": [sha, inside], "max_cost_usd": 5}
    admitted = env.post("/runs", json={**filed, "reading_id": named.reading_id, "campaign_id": cid})
    assert admitted.status_code == 201, admitted.text
    assert [a["run_id"] for a in _admitted(env, cid)] == [admitted.json()["id"]]

    def arms() -> dict[str, dict[str, Any]]:
        got = env.get("/readings", params={"repo": ALPHA}).json()["readings"]
        return {o["reading_id"]: o["arms"][0] for o in got}

    def row(run_id: str, commit: str) -> Any:
        return sealed_row(commit, repo=ALPHA, run_id=run_id, arm="S3", cell=CELL, created=LATER)

    ledger = DbLedger(env.factory)
    ledger.append(row(loose.json()["id"], sha))
    ledger.append(row(loose.json()["id"], plain))
    got = arms()
    assert (got[named.reading_id]["counted"], got[legacy.reading_id]["counted"]) == (0, 1)
    assert got[named.reading_id]["left"] == []
    served = env.get("/readings", params={"repo": ALPHA}).json()["readings"]
    assert {o["reading_id"]: o["admitted_runs"] for o in served} == {
        named.reading_id: 1,
        legacy.reading_id: None,
    }
    assert not any(o["admissions_unread"] for o in served)
    ledger.append(row(admitted.json()["id"], sha))
    ledger.append(row(admitted.json()["id"], inside))
    got = arms()
    assert (got[named.reading_id]["counted"], got[legacy.reading_id]["counted"]) == (2, 1)
    assert sorted(got[named.reading_id]["counted_commits"]) == [sha, inside]
    assert got[named.reading_id]["left"] == []


def test_a_campaign_reading_reads_each_commit_by_its_first_admitted_attempt(
    backend: Backend, tmp_path: Path
) -> None:
    """DL-382, option (b), through ``GET /readings`` on each store: a campaign-named reading
    reads only rows of runs its campaign admitted, so each commit is read by its first
    ADMITTED attempt. A miss from a run posted outside the campaign, then a clean row from an
    admitted run, counts clean; a clean row outside, then an admitted miss, counts the miss.
    The rows outside buy nothing here: no commit leaves the pool, and each is decided by
    the admitted run's row (its own ``row_hash``, read back through ``load_readings``)."""
    init_db(backend.engine)
    info = seed(backend.factory)
    add_users(backend.factory)
    settings = make_settings(tmp_path)
    settings.builder.executor = "docker"
    shas = ["1" * 40, "2" * 40, "3" * 40]
    with TestClient(create_app(settings, backend.factory)) as client:
        login(client, "operator")
        env = Env(client=client, factory=backend.factory, info=info, settings=settings)
        cid = _register(env)["campaign_id"]
        named = write_reading(env.factory, shas, repo=ALPHA, campaign_id=cid, hierarchy=("S3",))
        loose = env.post("/runs", json={**GOLD, "executor": "docker", "task_ids": shas})
        assert loose.status_code == 201, loose.text
        filed = {**GOLD, "executor": "docker", "task_ids": shas, "max_cost_usd": 5}
        admitted = env.post(
            "/runs", json={**filed, "reading_id": named.reading_id, "campaign_id": cid}
        )
        assert admitted.status_code == 201, admitted.text
        # each commit's outside row reads the opposite of its admitted row
        truth = dict(zip(shas, (True, False, True), strict=True))
        ledger = DbLedger(env.factory)
        written = [
            ledger.append(
                sealed_row(
                    sha,
                    repo=ALPHA,
                    run_id=run.json()["id"],
                    arm="S3",
                    cell=CELL,
                    created=LATER,
                    clean=truth[sha] if run is admitted else not truth[sha],
                )
            )
            for sha in shas
            for run in (loose, admitted)
        ]
        (served,) = env.get("/readings", params={"repo": ALPHA}).json()["readings"]
    arm = served["arms"][0]
    assert served["admitted_runs"] == 1 and served["admissions_unread"] is False
    assert (arm["counted"], arm["clean"], arm["misses"]) == (3, 2, 1)
    assert arm["left"] == []
    assert len({r.row_hash for r in written}) == len(written)
    with backend.factory() as s:
        (reading,) = load_readings(s, ALPHA)
    decided = {c.commit: c.row_hash for c in arm_reading(reading, "S3", written).commits}
    aid = admitted.json()["id"]
    assert decided == {r.task_id: r.row_hash for r in written if r.run_id == aid}


def test_load_readings_reads_each_campaigns_admissions_on_each_backend(backend: Backend) -> None:
    """DL-382 on both stores: ``load_readings`` fills a campaign-named reading with the
    ``run_id`` of every ``campaign.admitted`` event on ITS campaign's trace — not another
    campaign's, not another action's — and leaves a reading under no campaign without any
    (``admitted is None``, so it counts as before)."""
    init_db(backend.engine)
    cid, other = "cmp_" + "a" * 24, "cmp_" + "b" * 24
    named = write_reading(backend.factory, ["1" * 40], repo=ALPHA, campaign_id=cid)
    legacy = write_reading(backend.factory, ["2" * 40], repo=ALPHA)
    for trace, action, run_id in (
        (cid, CAMPAIGN_ADMITTED, "run-a"),
        (cid, CAMPAIGN_ADMITTED, "run-b"),
        (other, CAMPAIGN_ADMITTED, "run-c"),
        (cid, CAMPAIGN_REGISTERED, "run-d"),
    ):
        stored = append_event(
            backend.factory,
            trace_id=trace,
            stage="system",
            action=action,
            payload={"run_id": run_id},
        )
        assert stored is not None
    with backend.factory() as s:
        assert admitted_runs(s, cid) == {"run-a", "run-b"}
        got = {r.reading_id: r for r in load_readings(s, ALPHA)}
    assert got[named.reading_id].admitted == {"run-a", "run-b"}
    assert not got[named.reading_id].admissions_unread
    assert got[legacy.reading_id].admitted is None
    assert not got[legacy.reading_id].admissions_unread


def test_a_record_that_does_not_rehash_holds_no_ceiling(env: Env) -> None:
    """An edited ceiling is not a campaign: it is not served and no run is filed under it."""
    out = _register(env)
    cid = out["campaign_id"]
    with env.factory() as s:
        # forge a second registration on the same trace with a raised ceiling (no re-hash)
        forged = {k: out[k] for k in ("schema", "name", "released_gbp", "rate_usd_per_gbp")}
        forged |= {
            "ceiling_gbp": 800,
            "decision": "forged",
            "actor": "x",
            "registered_at": "x",
            "campaign_id": "cmp_" + "b" * 24,
        }
        s.add(
            Event(
                event_id="f" * 32,
                trace_id="cmp_" + "b" * 24,
                seq=1,
                timestamp="2026-10-11T00:00:00Z",
                stage="system",
                action=CAMPAIGN_REGISTERED,
                status="ok",
                payload_json=forged,
            )
        )
        s.commit()
    ids = [c["campaign_id"] for c in env.get("/campaigns").json()["items"]]
    assert ids == [cid]
    r = env.post("/runs", json={**GOLD, "max_cost_usd": 5, "campaign_id": "cmp_" + "b" * 24})
    assert r.status_code == 404 and envelope(r)["code"] == "campaign_unknown"


def test_concurrent_submits_never_both_take_the_last_of_the_line(env: Env) -> None:
    """The tally is read and the run staged under the events write lock: four $20 runs
    racing for a $54.00 line ($25 held each) admit exactly two."""
    cid = _register(env)["campaign_id"]
    body = RunCreateRequest.model_validate({**GOLD, "max_cost_usd": 20, "campaign_id": cid})
    barrier = threading.Barrier(4)
    outcomes: list[str] = []
    lock = threading.Lock()

    def submit() -> None:
        run = new_run(body, actor="op")
        barrier.wait()
        try:
            admit_under_campaign(env.factory, env.settings, body, run, actor="op")
            got = "admitted"
        except ApiError as exc:
            got = exc.code
        with lock:
            outcomes.append(got)

    threads = [threading.Thread(target=submit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(outcomes) == ["admitted", "admitted", "campaign_ceiling", "campaign_ceiling"]
    assert len(_admitted(env, cid)) == 2
    assert env.get(f"/campaigns/{cid}").json()["held_usd"] == 50.0
