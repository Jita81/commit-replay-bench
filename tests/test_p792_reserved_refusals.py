"""P-792, the refusals: a run the reading cannot count is refused or halted before it reserves.

Part of the P-792 channel tests; tests/test_p792_reserved.py holds the rigs and the rule's own
tests. A reserved.v1 reading counts a commit by the one attempt its reservation names, so a
run that would spend that attempt on another treatment stops before the reservation, the
commit left pending: at submit (``POST /runs`` 422 ``reading_run_fields`` or 409
``reading_required``), at claim (``run.refused``), or in the reserver itself under the events
lock (``cancel_requested``, ``run_not_owned``, ``reading_checks_arm_mismatch``). Each test
failed on the code before its refusal.

Navigation
----------
What it is:   The P-792 tests of every refusal and halt that stops a reading's run before it
              reserves: the reserver's recheck, the claim, the submit gate, lint and the
              checks arm.
What it does: The reserver's recheck under the lock (a run cancelled, or reclaimed and claimed
              again by another worker or by one with this one's id, between claim and reserve
              halted ``cancel_requested`` or ``run_not_owned``, the commit pending); C5 and C7
              at claim (a ``timeout`` or another budget profile refused
              ``reading_run_fields``); PW-7's ``outage_stop`` and ``env_stop`` held at 1 at
              submit and at claim. The submit gate: C7 (the budget profile and the learning
              switch), the request-field ratchet (C17: free, default, refused and factory
              fields; their stored ``params`` keys are ``RESERVED_RUN_PARAMS``), the pin that
              ``new_run``'s empty ladder is ``RESERVED_RUN_LADDER``, 409 ``reading_required``
              (C19), the step-6 re-measure bodies admitted, and both refusals re-checked under
              the events lock. Lint (P-796): a run of a reading on a repository whose lint is
              off refused 409 ``lint_disabled`` at submit and ``run.refused`` at claim, and
              lint switched after the first reservation refusing or halting the next. NEW-1:
              an ``A0+L`` run filed on ``A0``'s misses alone refused at claim. The checks arm
              (RT2B-1): an ``A0+L`` run resolving ``fmt`` against a reading frozen ``off``
              halting ``reading_checks_arm_mismatch`` before any reservation or build, and the
              team's own ``checks.format_step`` keeping it on the reading's arm.
How:          The claim and reserver tests drive P-792's worker rig (``_w_rig``, SQLite or the
              ``backend`` fixture's database), storing each run as ``POST /runs`` stores one
              the whitelist admits and editing it past the route; the submit-gate tests
              (``_r_stack``) run the app on the ``backend`` fixture's store (SQLite and
              PostgreSQL) with the Wave 3 rehearsal's campaign and registrations, settling
              each admitted run so the campaign's line is free for the next.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/server/routes/runs.py (``submit_refusals`` and ``admit_under_campaign``:
              the run-field, lint and campaign refusals, under test),
              src/crb/server/worker.py (the claim's refusals and the reserver's recheck under
              the lock, under test), src/crb/core/reading.py (``reading_run_refusal``, the
              whitelist both checks share),
              tests/test_p792_reserved.py (the worker rig and the submit-gate stack, imported),
              tests/test_wave3_registration_rehearsal.py (the campaign, the registrations and
              the step-6 bodies posted), docs/PREVENTION.md (P-792; P-796, the lint switch)
Tested by:    tests/test_p792_reserved_refusals.py
Touch when:   never for a new repository; a field, refusal or halt a reading's run meets before
              its reservation is added or changed (its test here, failing first), or
              ``RunCreateRequest`` gains a field (the ratchet fails until it is classified).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from crb.core.lint import LINT_DISABLED_BY_CONFIG
from crb.core.reading import (
    HALT_CANCEL_REQUESTED,
    HALT_CHECKS_ARM_MISMATCH,
    HALT_RUN_NOT_OWNED,
    HALT_TREATMENT_MISMATCH,
    REFUSAL_READING_REQUIRED,
    REFUSAL_RUN_FIELDS,
    RESERVED_RUN_LADDER,
    RESERVED_RUN_PARAMS,
    Reading,
)
from crb.core.spend import PROFILE_CALIBRATED, PROFILE_DEFAULT
from crb.server.routes import runs as runs_routes
from crb.server.schemas import RunCreateRequest
from crb.store.jobs import STATUS_CANCELLED, STATUS_FAILED, STATUS_RUNNING, STATUS_SUCCEEDED
from crb.store.models import Run
from fixtures import pyrepo as pr
from test_p792_reserved import (
    _R_COLUMNS,
    _R_DEFAULT,
    _R_FACTORY,
    _R_FREE,
    _R_REFUSED,
    _r_admit,
    _r_admitted,
    _r_fields,
    _r_lint,
    _r_refused,
    _r_stack,
    _w_a0l,
    _w_before_reserve,
    _w_format_step_in_force,
    _w_loop_on,
    _w_loop_pair,
    _w_rig,
    _worker_defaults_cleared,  # noqa: F401 — autouse: the builder's env defaults cleared
)
from test_wave3_registration_rehearsal import _a0, _s3_body, a0l_body, campaign_body
from test_worker import FakeBuilder

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


# --- the worker: a reserved.v1 reading's run reserves each commit before its r1 build ------


@pytest.mark.parametrize("how", ["cancel", "reclaim", "reclaim_same_worker"])
def test_p792_reserve_rechecks_the_run_under_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """The reserve transaction re-reads the run under the events lock: a cancel asked, or a
    reclaim and a claim — by another worker, or by a worker with this one's id (two
    processes sharing a configured id, or a restart repeating hostname-pid) — landing after
    the run's own stop check and before the reservation halts the run there —
    ``cancel_requested``, or ``run_not_owned`` naming the status, the owner, the claim it
    reserved under and the claim the run is at now — with no ``reading.reserved`` written,
    nothing built and the commit still pending. Pinned by mutation: without the re-read's
    cancel check the ``cancel`` case is reserved and built, and without its claim check the
    ``reclaim_same_worker`` case, whose owner never moves (R3-HON-1). The owner check is
    pinned only with the claim check: through the queue a run changes owner only by a
    reclaim, which moves the claim too."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["b"] = "gold"
    owner = rig.h.worker.worker_id if how == "reclaim_same_worker" else "worker-2"
    if how == "cancel":
        _w_before_reserve(
            rig, monkeypatch, lambda r: rig.h.queue.request_cancel(r.id, actor="op-1")
        )
    else:

        def steal(r: Run) -> None:
            assert [x.id for x in rig.h.queue.reclaim_stale(0.0)] == [r.id]
            other = rig.h.queue.claim_next(owner)
            assert other is not None and (other.id, other.worker_id) == (r.id, owner)

        _w_before_reserve(rig, monkeypatch, steal)
    with contextlib.suppress(Exception):
        rig.h.run_one()
    (halted,) = rig.payloads(run.id, "run.halted")
    if how == "cancel":
        assert halted["reason"] == HALT_CANCEL_REQUESTED
    else:
        assert halted["reason"] == HALT_RUN_NOT_OWNED
        detail = halted["detail"]
        assert {k: detail[k] for k in ("status", "owner", "claim", "at_claim")} == {
            "status": STATUS_RUNNING,
            "owner": owner,
            "claim": 0,
            "at_claim": 1,
        }, detail
    assert rig.reservations(reading) == []
    assert "build.start" not in rig.actions(run.id)
    assert rig.rows(run.id) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")


def test_p792_claim_refuses_timeout_and_a_budget_profile_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5 and C7 at claim (C17: the whitelist is the claim's too, not only the submit's): a
    run of a reserved.v1 reading inserted past ``POST /runs`` with its own ``timeout`` (C5:
    a short timeout turns an honest attempt red), or spending on a budget profile other than
    the reading's (C7), fails at claim with ``run.refused`` ``reading_run_fields`` naming the
    field — nothing built, nothing reserved, the commit pending. The same run as submit stores
    it is claimed, builds and reserves, so the refusals are the fields' and nothing else's."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    for params, field in (
        ({"timeout": 5}, "timeout"),
        ({"budget_profile": PROFILE_CALIBRATED}, "budget_profile"),
    ):
        queued = rig.enqueue(reading, params=params)
        done = rig.h.run_one()
        assert (done.id, done.status) == (queued.id, STATUS_FAILED), field
        (why,) = rig.payloads(queued.id, "run.refused")
        assert (why["code"], why["fields"], why["arm"]) == (REFUSAL_RUN_FIELDS, [field], "A0")
        assert field in why["reasons"] and done.error.startswith(REFUSAL_RUN_FIELDS)
        assert "build.start" not in rig.actions(queued.id) and rig.rows(queued.id) == []
    assert FakeBuilder.briefs == [] and rig.reservations(reading) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")
    run = rig.enqueue(reading)
    rig.h.run_one()
    assert "run.refused" not in rig.actions(run.id)
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == ("A0", rig.first)
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")


def test_a_reading_run_body_naming_outage_stop_3_is_refused(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PW-7 at submit and at claim: a run of a reserved.v1 reading takes ``outage_stop`` and
    ``env_stop`` only as 1 (or unset, which the worker defaults to 1 on such a run). On
    ``backend``'s store ``POST /runs`` naming ``outage_stop`` 3, ``env_stop`` 2 or either at 0
    is refused 422 ``reading_run_fields`` naming the knob, nothing queued (201 before); the
    step-6 body with both at 1 is admitted. A row queued past ``POST /runs`` carrying 3, 2,
    ``null`` or ``true`` fails at claim (``run.refused``), nothing built or reserved."""
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        for knob, value in (("outage_stop", 3), ("env_stop", 2), ("outage_stop", 0)):
            reason = _r_fields(w, {**a0, knob: value}, [knob])["reasons"][knob]
            assert "first outage or environment row" in reason, reason
        _r_fields(w, {**a0, "outage_stop": 3, "env_stop": 2}, ["env_stop", "outage_stop"])
        stored = dict(_r_admit(w, {**a0, "outage_stop": 1, "env_stop": 1}).params_json or {})
        assert (stored["outage_stop"], stored["env_stop"]) == (1, 1)

    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    for knob, value in (
        ("outage_stop", 3),
        ("env_stop", 2),
        ("outage_stop", None),
        ("env_stop", True),
    ):
        queued = rig.enqueue(reading, params={knob: value})
        done = rig.h.run_one()
        assert (done.id, done.status) == (queued.id, STATUS_FAILED), knob
        (why,) = rig.payloads(queued.id, "run.refused")
        assert (why["code"], why["fields"], why["arm"]) == (REFUSAL_RUN_FIELDS, [knob], "A0")
        assert "build.start" not in rig.actions(queued.id) and rig.rows(queued.id) == []
    assert rig.reservations(reading) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")


# --- the submit gate (POST /runs): 422 reading_run_fields and 409 reading_required --------


def test_p792_c7_budget_profile_mismatch_refused(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C7 and C17 at submit, reproducing the probe ``test_in_scope_reads_no_run_parameter``
    (the reading's scope reads no run parameter, so a run's own profile was counted as the
    reading's): a non-loop arm spending on a budget profile other than the reading's
    (``calibrated`` against ``default``), a non-loop arm without ``learning: off``, and the
    ``+L`` arm naming a budget profile are each refused 422 ``reading_run_fields`` naming
    what moved, nothing queued (201 before the route's check). ``learning: on`` is the
    schema's 422 (green before: the loop is opted out, never in). The step-6 ``A0`` and
    ``A0+L`` bodies are admitted."""
    with _r_stack(backend, tmp_path, monkeypatch) as w:
        key = ("cobra", "XS")
        a0 = _a0(w, key)
        a0l = a0l_body(a0)
        s3 = _s3_body(w, key)
        assert a0["budget_profile"] == w.readings[key]["budget_profile"] == PROFILE_DEFAULT
        cases: list[tuple[dict[str, Any], list[str], str]] = [
            ({**a0, "budget_profile": PROFILE_CALIBRATED}, ["budget_profile"], "A0"),
            ({k: v for k, v in a0.items() if k != "learning"}, ["learning"], "A0"),
            ({**a0l, "budget_profile": PROFILE_CALIBRATED}, ["budget_profile", "learning"], "A0"),
            ({**s3, "budget_profile": PROFILE_CALIBRATED}, ["budget_profile"], "S3"),
        ]
        for body, fields, arm in cases:
            assert _r_fields(w, body, fields)["arm"] == arm, fields
        err = _r_refused(w, {**a0, "learning": "on"}, 422, "validation_error")
        assert "learning" in json.dumps(err)
        assert _r_admit(w, a0).params_json["learning"] == "off"
        assert "learning" not in _r_admit(w, a0l).params_json


def test_p792_run_fields_ratchet(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C17, the ratchet: every ``RunCreateRequest`` field is classified (``_R_FREE``,
    ``_R_DEFAULT``, ``_R_REFUSED``, ``_R_FACTORY``), so a field added to the request fails
    here until it is; the ``params`` keys the admitted classes store are exactly the core's
    :data:`RESERVED_RUN_PARAMS`, and no refused field's is one. Each class behaves as named
    on ``POST /runs`` filed under a reserved.v1 reading: a free field admitted, a default
    field admitted at its default and refused 422 ``reading_run_fields`` naming it
    otherwise, a refused field refused naming it, a factory field 422 ``validation_error`` —
    each refusal with nothing queued."""
    classes = [set(_R_FREE), set(_R_DEFAULT), set(_R_REFUSED), set(_R_FACTORY)]
    assert sum(len(c) for c in classes) == len(set().union(*classes))  # disjoint
    assert set(RunCreateRequest.model_fields) == set().union(*classes)
    assert (set(_R_FREE) | set(_R_DEFAULT)) - _R_COLUMNS == RESERVED_RUN_PARAMS
    assert RESERVED_RUN_PARAMS.isdisjoint(_R_REFUSED) and RESERVED_RUN_PARAMS.isdisjoint(_R_FACTORY)
    with _r_stack(backend, tmp_path, monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        for name, over in _R_FREE.items():
            assert over or name in a0, name
            run = _r_admit(w, {**a0, **over})
            stored = dict(run.params_json or {})
            assert name in _R_COLUMNS or name in stored, (name, stored)
        for name, (default, other) in _R_DEFAULT.items():
            run = _r_admit(w, {**a0, **default})
            assert run.ladder_json == list(RESERVED_RUN_LADDER), name
            _r_fields(w, {**a0, **other}, [name])
        for name, value in _R_REFUSED.items():
            _r_fields(w, {**a0, name: value}, [name])
        for name, value in _R_FACTORY.items():
            err = _r_refused(w, {**a0, name: value}, 422, "validation_error")
            assert name in err["message"], (name, err)


def test_p792_empty_ladder_default_is_what_new_run_stores() -> None:
    """The one ladder a reserved.v1 reading's run climbs (:data:`RESERVED_RUN_LADDER`) is
    what ``new_run`` stores for a body naming none, and ``pool``, ``executor`` and
    ``timeout`` are stored at the defaults the whitelist keeps — so a step-6 body, which
    names none of them, is the run the whitelist admits. A pin: green before the route's
    check, it fails if either side's default moves without the other."""
    for kind in ("replay", "blind"):
        body = RunCreateRequest(
            repo="cobra",
            kind=kind,
            builder="claude_code",
            model="claude-sonnet-5",
            provider="anthropic",
            task_ids=[],
        )
        run = runs_routes.new_run(body, actor="u")
        assert run.ladder_json == list(RESERVED_RUN_LADDER) == ["r1"], kind
        params = dict(run.params_json or {})
        assert {k: params[k] for k in ("pool", "executor", "timeout")} == {
            "pool": "",
            "executor": "",
            "timeout": 0,
        }
        assert set(params) <= RESERVED_RUN_PARAMS, params


def test_p792_reading_required_for_campaign_runs(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C19: a run filed under a campaign that holds a reserved.v1 reading on its repository
    names its reading — without ``reading_id`` it is refused 409 ``reading_required``
    (``detail: {campaign_id, reading_ids}``) with nothing queued and nothing admitted (201
    and admitted before the route's check), since it would spend the campaign's line while
    no reading's gate (``reading_run_fields``, sealed, posture) checked it. A repository
    whose readings in the campaign are all legacy is admitted as before; a run under no
    campaign, or under another campaign holding no reading, is unaffected."""
    legacy = (("click", "XS"), ("click", "S"))
    with _r_stack(backend, tmp_path, monkeypatch, legacy=legacy) as w:
        cobra = {k: v for k, v in _a0(w, ("cobra", "XS")).items() if k != "reading_id"}
        err = _r_refused(w, cobra, 409, REFUSAL_READING_REQUIRED)
        held = sorted(w.readings[("cobra", s)]["reading_id"] for s in ("XS", "S"))
        assert err["detail"] == {"campaign_id": w.cid, "reading_ids": held}
        assert "nothing was queued" in err["message"]
        click = {k: v for k, v in _a0(w, ("click", "XS")).items() if k != "reading_id"}
        _r_admit(w, click)
        outside = {k: v for k, v in cobra.items() if k != "campaign_id"}
        admitted = _r_admitted(w)
        _r_admit(w, outside)
        assert _r_admitted(w) == admitted
        r = w.send("POST", "/api/v1/campaigns", json={**campaign_body(), "name": "p792-other"})
        assert r.status_code == 201, r.text
        other = str(r.json()["campaign_id"])
        assert other != w.cid
        r = w.send("POST", "/api/v1/runs", json={**cobra, "campaign_id": other})
        assert r.status_code == 201, r.text


def test_p792_remeasure_bodies_are_admitted(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec risk 6, the whitelist against the real step-6 bodies on an opt-in reserved.v1
    reading: the ``GET /learn/remeasure`` plan's own request plus the three filing fields
    and the profile (``S3``), and the record's ``A0`` and ``A0+L`` bodies, are each
    admitted 201 and stored as the record words them; a body asking to ``retain`` its
    worktrees is refused 422 ``reading_run_fields`` (on purpose: allowing it would be a
    registration amendment)."""
    with _r_stack(backend, tmp_path, monkeypatch) as w:
        key = ("cobra", "XS")
        a0 = _a0(w, key)
        runs = [_r_admit(w, b) for b in (_s3_body(w, key), a0, a0l_body(a0))]
        assert [r.kind for r in runs] == ["replay", "blind", "blind"]
        assert [dict(r.params_json or {}).get("learning") for r in runs] == ["off", "off", None]
        assert all(r.ladder_json == list(RESERVED_RUN_LADDER) for r in runs)
        _r_fields(w, {**a0, "retain": {"worktrees": True}}, ["retain"])


def test_p792_admission_rechecks_both_refusals_under_the_lock(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``admit_under_campaign`` re-runs the submit gate under the events write lock, so both
    new refusals hold there too: when the readings read before the lock are still legacy
    and the ones read under it are reserved.v1 (an opt-in landing between the two reads),
    a run setting ``timeout`` is refused 422 ``reading_run_fields`` and a run without
    ``reading_id`` 409 ``reading_required`` — each with nothing queued and nothing admitted
    (both 201 before the route's checks)."""
    real = runs_routes.load_readings
    calls: list[str] = []

    def first_read_legacy(db: Any, repo: str) -> list[Reading]:
        got = list(real(db, repo))
        calls.append(repo)
        if len(calls) == 1:
            return [dataclasses.replace(r, attempt_rule="") for r in got]
        return got

    with _r_stack(backend, tmp_path, monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        monkeypatch.setattr(runs_routes, "load_readings", first_read_legacy)
        _r_fields(w, {**a0, "timeout": 1}, ["timeout"])
        assert len(calls) == 2
        calls.clear()
        no_reading = {k: v for k, v in a0.items() if k != "reading_id"}
        _r_refused(w, no_reading, 409, REFUSAL_READING_REQUIRED)
        assert len(calls) == 2


# --- an operator's lint switch never reshapes what a reading counts (P-796) ------------------


def test_p792_a_run_of_a_reading_on_a_lint_disabled_repo_is_refused(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-796 (the Wave 3 red team's F7, by code reading): a row graded with belt 5 switched
    off lets its commit leave a legacy reading ``lint_disabled`` and is a reserved.v1
    reading's miss, and the switch is the operator's to throw after outcomes are seen. Now a
    run filed under a reading of either rule on a repository whose lint is disabled is
    refused 409 ``lint_disabled`` at submit, nothing queued or admitted (201 before), and a
    run that reached the queue past the gate is refused at claim — ``run.refused``
    ``lint_disabled``, failed before any build, nothing reserved, every commit still pending
    (built and reserved before)."""
    off = {"disabled": True}
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch, legacy=[("click", "XS")]) as w:
        for key in (("cobra", "XS"), ("click", "XS")):
            body = _a0(w, key)
            _r_lint(w, key[0], off)
            err = _r_refused(w, body, 409, "lint_disabled")
            assert err["detail"] == {
                "reading_id": body["reading_id"],
                "repo": key[0],
                "reason": LINT_DISABLED_BY_CONFIG,
            }, key
            _r_lint(w, key[0], {})
            assert _r_admit(w, body).status == STATUS_CANCELLED

    (tmp_path / "claim").mkdir()
    rig = _w_rig(tmp_path / "claim", monkeypatch)
    for reading in (rig.register(), rig.register(legacy=True)):
        rig.edit_config(lint=off)
        run = rig.enqueue(reading)
        done = rig.h.run_one()
        assert done.status == STATUS_FAILED and done.error.startswith("lint_disabled"), done.error
        (refused,) = rig.payloads(run.id, "run.refused")
        assert (refused["code"], refused["reading_id"]) == ("lint_disabled", reading.reading_id)
        assert (refused["repo"], refused["reason"]) == (pr.REPO_NAME, LINT_DISABLED_BY_CONFIG)
        assert "build.start" not in rig.actions(run.id)
        assert rig.rows(run.id) == [] and rig.reservations(reading) == []
        assert rig.verdicts(reading, "A0")[rig.first][0] is None
        rig.edit_config(lint={})


def test_p792_toggling_lint_after_the_first_reservation_halts_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-796 against the treatment pin: once a reserved.v1 reading's first reservation has
    pinned the repository's configuration, switching belt 5 off refuses the next run at
    claim (``lint_disabled``, before any reservation — it halted on the pin before the claim
    check), and switching it back on under another lint block (``{"disabled": false}`` is
    not the ``{}`` pinned) halts the next ``reading_treatment_mismatch`` on the repository
    digest, before ``build.start``. The second commit stays pending throughout, and the
    first keeps the verdict its reservation gave it."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    rig.state["b"] = "multiply"
    rig.edit_config(lint={"disabled": True})
    off = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("lint_disabled"), done.error
    (refused,) = rig.payloads(off.id, "run.refused")
    assert refused["code"] == "lint_disabled"
    assert rig.payloads(off.id, "run.halted") == []
    assert "build.start" not in rig.actions(off.id)

    rig.edit_config(lint={"disabled": False})
    on = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.error == HALT_TREATMENT_MISMATCH
    (halted,) = rig.payloads(on.id, "run.halted")
    assert halted["detail"]["fields"] == ["repo_config"]
    assert "build.start" not in rig.actions(on.id)
    assert [e.event_id for e in rig.reservations(reading)] == [res.event_id]
    assert rig.verdicts(reading, "A0") == {rig.first: (True, ""), rig.second: (None, "pending")}


def test_p792_a0l_on_a0s_misses_alone_is_refused_at_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """NEW-1 (round 5), reproducing the probe end to end: with ``A0`` clean on the first
    commit of the seeded order and a miss on the second, an ``A0+L`` run filed on ``A0``'s miss
    alone reserved it, built it clean, and the loop pair read ``b`` 1, ``c`` 0 — ``A0``'s clean
    commit never a pair. The claim now refuses it (``run.refused`` ``reading_run_fields`` on
    ``task_ids``, before any reservation or build), and while ``A0+L`` is pending the pair
    names both commits pending and reads them against the loop (``c`` 1). The record's body —
    both commits, in the seeded order — is claimed, and the pair reads complete."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register(hierarchy=("S3",), descriptive=(("A0", 2), ("A0+L", 2)))
    _w_loop_on(rig)  # A0 runs carry learning: off, so they stay A0
    head, miss = reading.pool
    for commit, how in ((head, "gold"), (miss, "noop")):
        rig.state["b"] = how
        rig.enqueue(reading, commit)
        rig.h.run_one()
    assert rig.verdicts(reading, "A0") == {head: (True, ""), miss: (False, "miss")}

    rig.state["b"] = "gold"
    for tasks in ([miss], [miss, head]):
        run = _w_a0l(rig, reading, *tasks)
        done = rig.h.run_one()
        assert done.status == STATUS_FAILED, (tasks, done.status)
        (refused,) = rig.payloads(run.id, "run.refused")
        assert (refused["code"], refused["fields"], refused["arm"]) == (
            REFUSAL_RUN_FIELDS,
            ["task_ids"],
            "A0+L",
        ), refused
        assert "build.start" not in rig.actions(run.id)
        assert [e.step_id for e in rig.reservations(reading)] == ["A0", "A0"]
    pair = _w_loop_pair(rig, reading)
    assert pair.pairs == (head, miss) and pair.pending == (head, miss)
    assert (pair.b, pair.c, pair.complete) == (0, 1, False)

    run = _w_a0l(rig, reading, head, miss)
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, rig.actions(run.id)[-6:]
    assert rig.verdicts(reading, "A0+L") == {head: (True, ""), miss: (True, "")}
    pair = _w_loop_pair(rig, reading)
    assert (pair.pairs, pair.pending, pair.b, pair.c) == ((head, miss), (), 1, 0)


def test_reserver_halts_when_the_runs_checks_arm_differs_from_the_readings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """RT2B-1 (round 6): a reading freezes its checks arm (``off`` here), and the scope rule
    reads a reserved row on another checks arm as out of the reading's scope — so with the
    loop's ``format_step`` switch in force and the team's ``checks`` block silent on it, an
    ``A0+L`` run (the loop on, its body free of ``learning``) resolves ``fmt`` and reserved a
    commit its row could never count for, burning the attempt. It now halts
    ``reading_checks_arm_mismatch`` (``{frozen, run}``) before the reservation and before
    ``build.start``, and the commit stays pending."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register(hierarchy=("S3",), descriptive=(("A0", 2), ("A0+L", 2)))
    assert reading.checks_arm == "off"
    _w_format_step_in_force(rig)
    head, _ = reading.pool
    rig.state["b"] = "gold"
    run = _w_a0l(rig, reading, head)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED and done.error == HALT_CHECKS_ARM_MISMATCH, done.error
    (halted,) = rig.payloads(run.id, "run.halted")
    assert (halted["reason"], halted["detail"]) == (
        HALT_CHECKS_ARM_MISMATCH,
        {"frozen": "off", "run": "fmt"},
    ), halted
    assert "build.start" not in rig.actions(run.id)
    assert rig.reservations(reading) == [] and rig.rows(run.id) == []
    assert rig.verdicts(reading, "A0+L")[head] == (None, "pending")


def test_a_team_set_format_step_keeps_a0l_on_the_readings_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """The pin beside RT2B-1: the team's own ``checks.format_step`` wins over the loop's
    switch (``config_section`` merges the repository's block over the overlay), so with the
    same ``format_step`` change on the chain and the team's block setting it ``false``, the
    change is not in force, an ``A0+L`` run resolves the reading's ``off`` arm, and it
    reserves and builds."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register(hierarchy=("S3",), descriptive=(("A0", 2), ("A0+L", 2)))
    _w_format_step_in_force(rig)
    rig.edit_config(checks={"format_step": False})
    head, _ = reading.pool
    rig.state["b"] = "gold"
    run = _w_a0l(rig, reading, head)
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, rig.actions(run.id)[-6:]
    assert rig.payloads(run.id, "run.halted") == []
    assert "build.start" in rig.actions(run.id)
    assert [(e.step_id, e.task_id) for e in rig.reservations(reading)] == [("A0+L", head)]
    assert rig.verdicts(reading, "A0+L")[head] == (True, "")
