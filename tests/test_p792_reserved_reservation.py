"""P-792, the reservation: a reading's run reserves each commit once, before its r1 build.

Part of the P-792 channel tests; tests/test_p792_reserved.py holds the rigs and the rule's own
tests. The reservation is per (reading, arm, commit), written under the events lock before
anything the attempt shows, only at r1, and only by a reserved.v1 reading's run; a claim that
is no longer the run's own reaches the ledger refused, and ``/readings`` registers every
reading under reserved.v1 and serves each one's rule, treatment pins and reserved commits.
The tests that reproduce a channel failed on the code before the worker reserved; the legacy
reading's run, which never reserves, is green on both by design.

Navigation
----------
What it is:   The P-792 tests of the reservation itself: where and how often the worker writes
              it, what a lost claim's append meets, and how ``/readings`` registers and serves
              it.
What it does: S3 and A0 reserving one commit apart, each arm decided by its own row; a
              reservation only at r1 (a two-rung ladder refused at claim; past it, no second
              reservation at r2) and before every outcome event; two claims racing for one
              commit (one wins, on SQLite and PostgreSQL); a settled claim's row refused up to
              ``execute`` (``AttemptSettled``) and, F87-5, a reclaimed run's row no reservation
              names (``ClaimLost``: no row and no finish, on both backends); a legacy
              reading's run never reserving; ``POST /readings`` registering reserved.v1 only
              (DL-385: the bare body reserved.v1, a legacy rule or a re-run refused 422); and
              ``GET /readings`` serving ``attempt_rule``, ``pinned_treatment`` and
              ``reserved`` (null before the first reservation), a legacy reading as
              ``first_observed.v0`` with ``p792: "open on this rule"``, and
              ``settled_unrowed`` per arm, the count the tally charges.
How:          The worker tests drive P-792's worker rig (``_w_rig``, SQLite or the ``backend``
              fixture's database; the race from two threads); the ``POST /readings`` test runs
              the app on a seeded SQLite store, and the ``GET /readings`` tests serve the rig's
              store (``_w_served``).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/server/worker.py (the reserver, under test),
              src/crb/store/jobs.py and src/crb/store/ledger.py (``claim_guard`` and
              ``reclaim_stale``; ``AttemptSettled``: a lost claim's append refused),
              src/crb/server/routes/readings.py (the reserved.v1 registration and
              ``served_reading``: the rule, the pins and the reserved counts, under test),
              src/crb/server/reading_book.py and src/crb/server/campaigns.py
              (``load_readings`` and ``treatment_pins``; ``unplaced_attempts``, served),
              tests/test_p792_reserved.py (the worker rig and ``_w_served``, imported),
              tests/test_worker.py (``Harness`` and ``FakeBuilder``, under the rig),
              docs/PREVENTION.md (P-792, the row these tests close)
Tested by:    tests/test_p792_reserved_reservation.py
Touch when:   never for a new repository; where, when or how often a reading's run reserves
              changes, or what ``/readings`` registers or serves for the attempt rule (its test
              here, failing first).
"""

from __future__ import annotations

import threading
import types
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.ledger import GradeRow
from crb.core.reading import (
    ATTEMPT_RULE_LEGACY,
    ATTEMPT_RULE_RESERVED,
    DEFAULT_MAX_RERUNS,
    LABEL_RESERVATION,
    READING_EVENT_ACTION,
    REFUSAL_RUN_FIELDS,
    SKIP_COMMIT_RESERVED,
)
from crb.core.spend import PROFILE_DEFAULT
from crb.server import campaigns as campaigns_mod
from crb.server import worker
from crb.store.jobs import STATUS_FAILED, STATUS_QUEUED, ClaimLost
from crb.store.ledger import AttemptSettled
from crb.store.models import Event
from test_p792_reserved import (
    _W_CELL,
    _w_event_ids,
    _w_rig,
    _w_served,
    _worker_defaults_cleared,  # noqa: F401 — autouse: the builder's env defaults cleared
)
from test_worker import FakeBuilder

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


# --- the worker: a reserved.v1 reading's run reserves each commit before its r1 build ------


def test_p792_s3_and_a0_share_commits_without_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reservation is per (reading, arm, commit): a sighted replay (S3) and a blind run
    (A0) of the same commit each reserve it on their own arm, neither skips, and each arm's
    commit is decided by its own reservation's row."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    sighted = rig.enqueue(reading, kind="replay")
    rig.h.run_one()
    blind = rig.enqueue(reading, kind="blind")
    rig.h.run_one()
    s3, a0 = rig.reservations(reading)
    assert [(e.step_id, e.task_id) for e in (s3, a0)] == [("S3", rig.first), ("A0", rig.first)]
    assert rig.skips(sighted.id) == [] and rig.skips(blind.id) == []
    ((s3_row,), (a0_row,)) = rig.rows(sighted.id), rig.rows(blind.id)
    assert s3_row.labels[LABEL_RESERVATION] == s3.event_id
    assert a0_row.labels[LABEL_RESERVATION] == a0.event_id
    assert rig.verdicts(reading, "S3")[rig.first] == (True, "")
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")
    # the arms share the deployment half: the blind run's reservation is pinned by the S3 one
    assert dict(a0.payload_json)["pinned_by"] == s3.event_id
    assert dict(a0.payload_json)["deployment_fp"] == dict(s3.payload_json)["deployment_fp"]


def test_p792_reserve_only_at_r1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reserved run reserves before its r1 build only. The claim's whitelist refuses a
    two-rung ladder before anything is built (``reading_run_fields``, the ladder named); past
    it — the claim check stubbed, as a run that reached the reserver by another path — a
    two-rung run whose r1 misses climbs to r2 without a second reservation and is not halted;
    the r2 row carries no reservation, so it never decides the commit — the r1 miss does."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    rig.state["by_model"] = {"m": "noop", "m2": "gold"}
    ladder = ["fake:m@p", "fake:m2@p"]
    refused = rig.enqueue(reading, ladder_json=ladder)
    assert rig.h.run_one().status == STATUS_FAILED
    (why,) = rig.payloads(refused.id, "run.refused")
    assert (why["code"], why["fields"]) == (REFUSAL_RUN_FIELDS, ["ladder"])
    assert "build.start" not in rig.actions(refused.id) and rig.reservations(reading) == []
    monkeypatch.setattr(rig.h.worker, "_reading_run_fields", lambda run, emitter: None)
    run = rig.enqueue(reading, ladder_json=ladder)
    rig.h.run_one()
    assert "run.halted" not in rig.actions(run.id)
    (res,) = rig.reservations(reading)
    r1, r2 = rig.rows(run.id)
    assert (r1.trial, r1.clean, r2.trial, r2.clean) == ("r1", False, "r2", True)
    assert r1.labels[LABEL_RESERVATION] == res.event_id
    assert LABEL_RESERVATION not in r2.labels
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "miss")


def test_p792_reservation_precedes_outcome_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C6's companion: the reservation is written before anything the attempt shows — its
    ``Event.id`` is below the task's ``build.start`` and every ``grade.*`` event of the run,
    so no outcome can be seen before the commit is spent."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    ids = _w_event_ids(rig, run.id)
    outcome = [i for action, got in ids.items() if action.startswith("grade.") for i in got]
    assert ids["build.start"] and outcome
    assert int(res.id) < min([*ids["build.start"], *outcome])


def test_p792_concurrent_reserve_one_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """Two runs of the reading, claimed at once, race to reserve the same (reading, arm,
    commit) from two threads: one reservation is written and the other run skips the commit
    — the events lock decides, on SQLite and on PostgreSQL."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    for _ in range(2):
        rig.enqueue(reading)
    w = rig.h.worker
    task = rig.h.pyrepo.feat_task()
    reservers = []
    for _ in range(2):
        run = rig.h.queue.claim_next(w.worker_id)
        assert run is not None
        emitter = w._emitter(run)
        config, git = w._load_repo(run.repo, emitter, kind=run.kind)
        reservers.append(
            w._reserver(
                worker.RunContext(run=run, emitter=emitter, config=config, git=git),
                reading.reading_id,
                arm="A0",
                checks_arm=reading.checks_arm,
                deployment={"d": 1},
                arm_body_for=lambda t: {"a": 1},
                hold_usd=None,
                ledger=types.SimpleNamespace(reserved={}),  # type: ignore[arg-type]
            )
        )
    gate = threading.Barrier(2)
    got: list[Any] = [None, None]

    def race(i: int) -> None:
        gate.wait()
        got[i] = reservers[i](task)

    threads = [threading.Thread(target=race, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted((r.status, r.reason) for r in got) == [
        ("ok", ""),
        ("skip", SKIP_COMMIT_RESERVED),
    ]
    assert len(rig.reservations(reading)) == 1


def test_p792_attempt_settled_reaches_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reserved attempt whose run is reclaimed mid-build reaches the ledger as a claim that
    is no longer its own: the append raises ``AttemptSettled``, the worker writes neither the
    row nor the run's finish (``run.finish_refused``; the reclaimed run stays queued for its
    new claim), and the new claim skips the commit, which reads ``unobserved``."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    finished: list[tuple[Any, ...]] = []
    finish = rig.h.worker.queue.finish

    def spy(*a: Any, **kw: Any) -> Any:
        finished.append(a)
        return finish(*a, **kw)

    monkeypatch.setattr(rig.h.worker.queue, "finish", spy)
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.h.queue.reclaim_stale(0.0))
    rig.h.run_one()
    assert "run.finish_refused" in rig.actions(run.id)
    assert finished == []
    assert rig.rows(run.id) == []
    assert rig.status(run.id) == STATUS_QUEUED
    (res,) = rig.reservations(reading)

    monkeypatch.setattr(FakeBuilder, "hook", None)
    again = rig.h.run_one()
    assert again.id == run.id
    assert rig.skips(run.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.rows(run.id) == []
    assert [e.event_id for e in rig.reservations(reading)] == [res.event_id]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")


def test_p792_a_lost_claims_plain_row_is_refused_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """F87-5, through ``execute`` on SQLite and on PostgreSQL: a run filed under no reading is
    reclaimed mid-build, so its row is one no reservation names. Round 5 guarded reserved rows
    only, and this one landed in the reclaimed run; now every row of a claimed run is appended
    under ``claim_guard``: the append raises ``ClaimLost`` (an ``AttemptSettled``), no row is
    written, ``run.claim_lost`` is emitted once, and the run's finish is left to its next
    claim (``run.finish_refused``; the run stays queued)."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    run = rig.h.enqueue("replay", params_json={"task_ids": [rig.first]})
    finished: list[tuple[Any, ...]] = []
    finish = rig.h.worker.queue.finish
    raised: list[BaseException] = []
    append = worker._RunLedger.append

    def spy(*a: Any, **kw: Any) -> Any:
        finished.append(a)
        return finish(*a, **kw)

    def watch(self: worker._RunLedger, row: GradeRow) -> GradeRow:
        try:
            return append(self, row)
        except AttemptSettled as exc:
            raised.append(exc)
            raise

    monkeypatch.setattr(rig.h.worker.queue, "finish", spy)
    monkeypatch.setattr(worker._RunLedger, "append", watch)
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.h.queue.reclaim_stale(0.0))
    rig.h.run_one()
    assert [(r.task_id, r.trial) for r in rig.rows(run.id)] == []
    assert [type(e) for e in raised] == [ClaimLost]
    actions = rig.actions(run.id)
    assert actions.count("run.claim_lost") == 1 and "run.finish_refused" in actions
    assert "run.finished" not in actions and finished == []
    assert rig.status(run.id) == STATUS_QUEUED


def test_p792_a_legacy_readings_run_never_reserves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run filed under a legacy (``first_observed.v0``) reading reserves nothing: no
    ``reading.reserved`` event, no reservation label on its row, and a second run builds the
    commit again, as it always did. Green before the change by design — it pins that the
    worker's reserver is wired only for a reserved.v1 reading."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register(legacy=True)
    first = rig.enqueue(reading)
    rig.h.run_one()
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert rig.reservations(reading) == []
    rows = [*rig.rows(first.id), *rig.rows(second.id)]
    assert len(rows) == 2 and all(LABEL_RESERVATION not in r.labels for r in rows)
    assert "build.start" in rig.actions(second.id)
    assert rig.skips(first.id) == rig.skips(second.id) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")


def test_p792_post_readings_registers_reserved_only(tmp_path: Path) -> None:
    """Step 13 of the round-5 spec (DL-385): ``POST /readings`` registers every reading
    under reserved.v1. A body naming no rule is stored ``attempt_rule`` reserved.v1,
    ``max_reruns`` 0 and the ``default`` budget profile, with no ``p792`` "open" mark when
    served; the same body naming the rule outright is the same reading (409
    ``reading_exists``); a body asking for the legacy rule, or for any re-run, is refused 422
    ``validation_error`` and writes nothing. Before the flip the bare body registered under
    the legacy rule, ``first_observed.v0`` with ``max_reruns`` 2."""
    from fixtures.proven import add_tasks, register_via_api
    from fixtures.readings import SEALED_SETTINGS, qualify_pool
    from fixtures.server_seed import ALPHA, envelope, make_env

    def registered(env: Any) -> int:
        with env.factory() as s:
            return len(list(s.execute(select(Event).where(Event.action == READING_EVENT_ACTION))))

    with make_env(tmp_path, **SEALED_SETTINGS) as env:
        qualify_pool(env.factory, ALPHA, add_tasks(env.factory))
        bare = register_via_api(env)
        assert bare.status_code == 201, bare.text
        got = bare.json()
        assert got["attempt_rule"] == ATTEMPT_RULE_RESERVED, got
        assert (got["max_reruns"], got["budget_profile"]) == (0, PROFILE_DEFAULT)
        (served,) = env.get(f"/readings?repo={ALPHA}").json()["readings"]
        assert served["attempt_rule"] == ATTEMPT_RULE_RESERVED and "p792" not in served
        named = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED, max_reruns=0)
        assert named.status_code == 409, named.text
        assert envelope(named)["detail"] == {"reading_id": got["reading_id"]}
        before = registered(env)
        assert before == 1
        for ask in (
            {"attempt_rule": ATTEMPT_RULE_LEGACY},
            {"attempt_rule": ""},
            {"max_reruns": DEFAULT_MAX_RERUNS},
            {"attempt_rule": ATTEMPT_RULE_RESERVED, "max_reruns": 1},
        ):
            refused = register_via_api(env, hypothesis=f"{ask}", **ask)
            assert refused.status_code == 422, (ask, refused.text)
            assert envelope(refused)["code"] == "validation_error", ask
        assert registered(env) == before


def test_p792_get_readings_serves_the_attempt_rule_and_the_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /readings`` serves a reserved.v1 reading's rule, its treatment pins and its
    reserved commits per arm (P-792): before any run, ``pinned_treatment`` is null and every
    arm has reserved none; after the first run the deployment half and its arm are pinned
    by that run's reservation — the body, the digest and the event, exactly as the
    reservation stored them — and a second arm's first run pins its own arm half while the
    deployment half stays the campaign's first."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    before = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert before["attempt_rule"] == ATTEMPT_RULE_RESERVED and "p792" not in before
    assert before["pinned_treatment"] is None
    assert before["reserved"] == {"S3": 0, "A0": 0}

    rig.enqueue(reading)
    rig.h.run_one()
    (a0,) = rig.reservations(reading)
    p = dict(a0.payload_json or {})

    def pin(half: str, ev: Event) -> dict[str, Any]:
        body = dict(ev.payload_json or {})
        return {
            "body": body["treatment_body"][half],
            "digest": body[f"{half}_fp"],
            "event_id": ev.event_id,
        }

    after = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert after["pinned_treatment"] == {
        "deployment": pin("deployment", a0),
        "arms": {"A0": pin("arm", a0)},
    }
    assert after["pinned_treatment"]["deployment"]["digest"] == p["deployment_fp"]
    assert after["reserved"] == {"S3": 0, "A0": 1}

    rig.enqueue(reading, kind="replay")
    rig.h.run_one()
    _, s3 = rig.reservations(reading)
    assert s3.step_id == "S3"
    later = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert later["pinned_treatment"] == {
        "deployment": pin("deployment", a0),
        "arms": {"A0": pin("arm", a0), "S3": pin("arm", s3)},
    }
    assert later["reserved"] == {"S3": 1, "A0": 1}


def test_p792_a_legacy_reading_is_served_open_on_this_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy reading (registered under no attempt rule) is served under the rule's name,
    ``first_observed.v0``, with ``p792: "open on this rule"`` — the channels P-792 closes for
    a reserved.v1 reading stay open on it — and with no pins and no reserved counts, before
    and after a run (which reserves nothing). Its id never moves."""
    rig = _w_rig(tmp_path, monkeypatch)
    legacy = rig.register(legacy=True)
    reserved = rig.register()
    for when in ("before", "after"):
        served = _w_served(rig, tmp_path / "api")
        got = served[legacy.reading_id]
        assert (got["attempt_rule"], got["p792"]) == (ATTEMPT_RULE_LEGACY, "open on this rule")
        assert got["pinned_treatment"] is None and got["reserved"] is None, when
        assert served[reserved.reading_id]["attempt_rule"] == ATTEMPT_RULE_RESERVED
        assert "p792" not in served[reserved.reading_id]
        if when == "before":
            rig.enqueue(legacy)
            rig.h.run_one()
    assert rig.reservations(legacy) == []


def test_p792_settled_unrowed_is_served_per_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """``GET /readings`` serves ``settled_unrowed`` per arm of a reserved.v1 reading: its
    reservations among the campaign's unplaced attempts (F8) — the same count the tally
    charges, never a second one. The grade that raised after ``build.done`` (a lost sandbox)
    is the worker's own path: its run failed with no row, its reservation is settled, and the
    attempt is charged at the cost the worker's ``build.done`` wrote. A reservation with its
    row counts nothing; a legacy reading serves null."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    legacy = rig.register(legacy=True)
    reading = rig.register()
    served = _w_served(rig, tmp_path / "api")
    assert served[reading.reading_id]["settled_unrowed"] == {"S3": 0, "A0": 0}
    assert served[legacy.reading_id]["settled_unrowed"] is None

    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.state.update(exec="lost"))
    lost = rig.enqueue(reading)
    assert rig.h.run_one().status == STATUS_FAILED
    assert "build.done" in rig.actions(lost.id) and rig.rows(lost.id) == []
    (a0,) = rig.reservations(reading)
    want = campaigns_mod.UnplacedAttempt(
        run_id=lost.id,
        task_id=rig.first,
        trial="r1",
        # the rung label the worker resolved trial r1 to, as its build.done names it
        rung=f"{_W_CELL['builder']}:{_W_CELL['model']}",
        cost_usd=0.01,
        reservation_event_id=a0.event_id,
        reading_id=reading.reading_id,
    )
    with rig.h.factory() as s:
        assert campaigns_mod.unplaced_attempts(s, [lost.id]) == [want]

    monkeypatch.setattr(FakeBuilder, "hook", None)
    rig.state["exec"] = ""
    rowed = rig.enqueue(reading, kind="replay")
    rig.h.run_one()
    assert len(rig.rows(rowed.id)) == 1
    with rig.h.factory() as s:
        assert campaigns_mod.unplaced_attempts(s, [lost.id, rowed.id]) == [want]
    served = _w_served(rig, tmp_path / "api")
    after = served[reading.reading_id]
    assert after["reserved"] == {"S3": 1, "A0": 1}
    assert after["settled_unrowed"] == {"S3": 0, "A0": 1}
    assert served[legacy.reading_id]["settled_unrowed"] is None
