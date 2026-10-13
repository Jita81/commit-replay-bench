"""P-792, the rows: whatever row the reserved attempt writes decides its commit.

Part of the P-792 channel tests; tests/test_p792_reserved.py holds the rigs and the rule's own
tests. Under the legacy rule a harness, outage, environment or out-of-scope row was passed
over, so a later attempt decided the commit; under reserved.v1 the row the reserved attempt
writes decides it whatever its kind, a later run skips the commit, and a run of the reading
stops at its first outage or environment row, so one episode cannot spend the arm (PW-7).
Each test failed on the code before the worker reserved.

Navigation
----------
What it is:   The P-792 tests of the reserved attempt's row deciding its commit, whatever its
              kind, end to end through the worker.
What it does: C5: ``POST /runs`` with its own ``timeout`` refused 422 ``reading_run_fields``
              (a), a gold control that timed out a miss a later clean row never changes (b),
              and a ``runner_opts`` edit after the first reservation halting the next run
              ``reading_treatment_mismatch`` (c); PW-7: a run stopping at its first outage row
              and at its first environment row, the second commit pending and unreserved; C9:
              a row from a clock rolled back a miss (``out_of_scope``); C11: an attempt in
              flight across a ``RepoConfig`` edit graded on the claim's snapshot (a hit), the
              next run halting; C12: a demoted row a miss (``harness``); F87-1: the ``S1``
              arm's env-probe harness row a miss, and a re-filed run skipping the commit
              (``commit_reserved``) without calling the author again.
How:          Each test drives P-792's worker rig (``_w_rig``, the fake builder and a local
              sandbox over the pyrepo fixture) and reads the commit's verdict after each run;
              ``_w_peek`` acts the moment belt 2 reads red, and C5(a) posts to the submit-gate
              stack (``_r_stack``, on SQLite and PostgreSQL).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/server/worker.py (the reserver, the reading run's stop rules and the
              treatment-pin halt, under test),
              src/crb/core/reading.py (the reserved.v1 verdict each row reads),
              src/crb/server/routes/runs.py (C5(a)'s ``timeout`` refusal at submit),
              tests/test_p792_reserved.py (the worker rig and the submit-gate stack, imported),
              tests/test_worker.py (``Harness`` and ``FakeBuilder``, under the rig),
              docs/PREVENTION.md (P-792, the row these tests close)
Tested by:    tests/test_p792_reserved_rows.py
Touch when:   never for a new repository; a kind of row the reserved attempt can write is added
              or read differently (its test here, failing first), or a reading run's stop rule
              changes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from crb.core.execution import ExecResult
from crb.core.ledger import AUTHORING_HARNESS_ERROR, FAILURE_HARNESS, GradeRow
from crb.core.reading import (
    HALT_TREATMENT_MISMATCH,
    LABEL_RESERVATION,
    LABEL_TREATMENT,
    SKIP_COMMIT_RESERVED,
)
from crb.core.runners.pytest_runner import PytestRunner
from crb.server import worker
from crb.store.jobs import STATUS_FAILED
from fixtures.readings import AUTHOR, S1
from test_p792_reserved import (
    _r_admit,
    _r_fields,
    _r_stack,
    _w_peek,
    _w_rig,
    _worker_defaults_cleared,  # noqa: F401 — autouse: the builder's env defaults cleared
)
from test_wave3_registration_rehearsal import _a0
from test_worker import FakeBuilder

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


# --- the worker: a reserved.v1 reading's run reserves each commit before its r1 build ------


def test_p792_c5_timeout_refused_and_gold_red_is_a_miss(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5, measured in round 4: a short timeout turned an honest attempt red, a gold control
    that timed out (blame ``GOLD_CONTROL_RED``) wrote a harness row the legacy rule passes
    over, and a later clean row of another run decided the commit; and a ``RepoConfig`` edit
    moved what later attempts ran under while the reading read on. (a) ``POST /runs`` filed
    under a reserved.v1 reading with its own ``timeout`` is refused 422 ``reading_run_fields``
    naming ``timeout``, nothing queued (201 before the route's check), on ``backend``'s
    store. (b) Now the timed-out control's row is the reserved attempt's: a miss, which a
    later clean row never changes. (c) A ``runner_opts`` edit after the first reservation
    halts the next run ``reading_treatment_mismatch`` before ``build.start``, naming the
    field that moved."""
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        _r_fields(w, {**a0, "timeout": 1}, ["timeout"])
        _r_admit(w, a0)

    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    # (b) the reserved attempt's gold control times out
    run = rig.enqueue(reading)
    rig.state["b"] = "noop"
    _w_peek(rig, monkeypatch, lambda _: rig.state.update(exec="timeout"))
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert row.labels["env_code"] == "GOLD_CONTROL_RED"
    assert "gold control red" in row.error
    miss = rig.verdicts(reading, "A0")[rig.first]
    assert miss == (False, "harness")
    # a later clean row of another admitted run, under no reading, changes nothing
    rig.state.update(b="gold", exec="")
    other = rig.enqueue(None)
    rig.h.run_one()
    (clean,) = rig.rows(other.id)
    assert clean.clean and LABEL_RESERVATION not in clean.labels
    assert rig.verdicts(reading, "A0")[rig.first] == miss

    # (c) the repository's runner options move after the first reservation
    cfg = rig.h.pyrepo.config.to_dict()
    rig.edit_config(runner_opts={**dict(cfg.get("runner_opts") or {}), "p792_edit": "1"})
    rig.state["b"] = "multiply"
    moved = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error == HALT_TREATMENT_MISMATCH
    (halted,) = rig.payloads(moved.id, "run.halted")
    assert halted["reason"] == HALT_TREATMENT_MISMATCH
    detail = halted["detail"]
    assert detail["half"] == "deployment"
    assert detail["pinned"] == dict(res.payload_json)["deployment_fp"]
    assert detail["ours"] != detail["pinned"]
    assert detail["pinned_by"] == res.event_id
    assert detail["fields"] == ["repo_config"]
    assert "build.start" not in rig.actions(moved.id)
    assert rig.rows(moved.id) == []
    assert len(rig.reservations(reading)) == 1
    assert rig.verdicts(reading, "A0")[rig.second] == (None, "pending")


def test_a_reading_run_stops_at_its_first_outage_row(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PW-7: a run of a reserved.v1 reading stops at its FIRST outage row. Under the worker's
    general default (``outage_stop`` 3) one usage-limit episode reserved three commits and
    wrote three outage rows — three misses under reserved.v1, enough alone to read the arm
    ``insufficient`` under ``look.v1``. Now the run reserves the first commit, whose refused
    attempt is its miss (``outage``), and stops ``run.outage_stop`` before it reserves the
    second, which stays pending, unreserved, for a later run: the arm counts one miss."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    rig.state["b"] = "outage"
    run = rig.enqueue(reading, rig.first, rig.second)
    done = rig.h.run_one()
    assert (done.id, done.status) == (run.id, STATUS_FAILED)
    (stop,) = rig.payloads(run.id, "run.outage_stop")
    assert str(stop["reason"]).startswith("provider outage: 1 consecutive"), stop
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == ("A0", rig.first)
    (row,) = rig.rows(run.id)
    assert row.failure_kind == "outage" and row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0") == {
        rig.first: (False, "outage"),
        rig.second: (None, "pending"),
    }
    assert rig.look(reading, "A0") == (1, 1)


def test_a_reading_run_stops_at_its_first_environment_row(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PW-7: a run of a reserved.v1 reading stops at its FIRST environment row (``env_stop``
    1; the worker's general default is 2). The first commit's reserved attempt reads red and
    its gold control times out — an ``environment:`` row (``GOLD_CONTROL_RED``), that
    commit's miss under reserved.v1 — and the run stops ``run.environment_stop`` before it
    reserves the second, though the sandbox recovers at once: the second stays pending and
    unreserved, and the arm counts one miss."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    rig.state["b"] = "noop"
    _w_peek(rig, monkeypatch, lambda _: rig.state.update(exec="timeout"))
    append = rig.h.worker.ledger.append

    def recovered(row: GradeRow, *, guard: Any = None) -> GradeRow:
        # the sandbox recovers once the row is written, so only the stop knob stops the run
        try:
            return append(row, guard=guard)
        finally:
            rig.state["exec"] = ""

    monkeypatch.setattr(rig.h.worker.ledger, "append", recovered)
    run = rig.enqueue(reading, rig.first, rig.second)
    done = rig.h.run_one()
    assert (done.id, done.status) == (run.id, STATUS_FAILED)
    (stop,) = rig.payloads(run.id, "run.environment_stop")
    assert str(stop["reason"]).startswith("environment: 1 consecutive"), stop
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == ("A0", rig.first)
    (row,) = rig.rows(run.id)
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert row.labels["env_code"] == "GOLD_CONTROL_RED" and row.error.startswith("environment:")
    assert rig.verdicts(reading, "A0") == {
        rig.first: (False, "harness"),
        rig.second: (None, "pending"),
    }
    assert rig.look(reading, "A0") == (1, 1)


def test_p792_c9_reservation_before_registration_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C9, from enumeration.md by code reading (no probe ran): a row whose ``created`` does
    not fall after the registration — a worker clock rolled back — was out of the reading's
    scope, so the legacy rule passed over it and a later attempt decided the commit. Now the
    reserved attempt's row decides it even so: a miss (``out_of_scope``), and a second run
    skips the commit."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["created"] = reading.registered_at  # the worker's clock reads the registration
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.clean and row.created == reading.registered_at
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "out_of_scope")

    rig.state["created"] = ""
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "out_of_scope")


def test_p792_c11_inflight_attempt_uses_claim_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C11, measured: the reading side re-confirmed by tests/test_zz_enum_fwd_lint_probe.py — a
    ``RepoConfig`` edit changed what later attempts were graded under while the reading read
    on. Now an attempt in flight when the configuration is edited is graded on the claim's
    snapshot and decides its commit on the treatment it reserved (a hit), and the next run,
    which loads the edit, halts ``reading_treatment_mismatch`` before ``build.start``."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    cfg = rig.h.pyrepo.config.to_dict()
    edit = {**dict(cfg.get("runner_opts") or {}), "p792_edit": "1"}
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.edit_config(runner_opts=edit))
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.clean
    assert row.labels[LABEL_TREATMENT] == dict(res.payload_json)["treatment"]
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    monkeypatch.setattr(FakeBuilder, "hook", None)
    rig.state["b"] = "multiply"
    later = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.error == HALT_TREATMENT_MISMATCH
    (halted,) = rig.payloads(later.id, "run.halted")
    assert halted["detail"]["fields"] == ["repo_config"]
    assert "build.start" not in rig.actions(later.id)
    assert rig.verdicts(reading, "A0") == {rig.first: (True, ""), rig.second: (None, "pending")}


def test_p792_c12_demoted_row_is_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C12, from enumeration.md by code reading (no probe ran): a clean row whose evidence
    pack could not be kept is demoted to a harness failure, which the legacy rule passed
    over, so a later attempt decided the commit. Now the demoted row keeps its reservation
    and decides the commit: a miss (``harness``), and a second run skips it."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    kept = worker._RunLedger._kept_pack
    monkeypatch.setattr(
        worker._RunLedger, "_kept_pack", lambda self, row: (None, "the pack store refused it")
    )
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert not row.clean and row.failure_kind == "harness"
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")

    monkeypatch.setattr(worker._RunLedger, "_kept_pack", kept)
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")


def test_s1_harness_row_after_reservation_is_a_miss_and_never_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """F87-1 (round 6): the ``S1`` arm's env-probe harness row is the reserved attempt's,
    so it decides the commit. The authored test's RED names no test (the run's sandbox times
    the command out) and the runner's env probe is red under the parent binding, so the author
    step writes ``authoring: harness error proving RED: the env probe is red ...`` — a
    ``harness`` row (rule 4b) that REPORTS the fault and buys no retry. Under reserved.v1 it
    reads ``(False, "harness")``, a miss, and a run re-filed under the reading skips the
    commit with ``commit_reserved``: the author is never called again and nothing is built
    (tests/test_replay_s1_arm.py::test_s1_unattributed_red_with_red_env_probe_is_harness
    pins the adapter half)."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register(hierarchy=("S3", S1))
    assert reading.author_model == AUTHOR
    authored: list[str] = []
    real_arm_of = worker.Worker._s1_arm_of

    def arm_of(self: worker.Worker, ctx: Any, author: Any) -> Any:
        def write(workspace: Any, subject: str, message: str) -> tuple[str, str]:
            authored.append(subject)
            rig.state["exec"] = "timeout"  # the RED under the parent names no test
            return "tests/test_s1_authored.py", "def test_s1_authored():\n    assert False\n"

        return dataclasses.replace(real_arm_of(self, ctx, author), author=write)

    def red_probe(self: PytestRunner, executor: Any, root: Path, *, timeout: int = 0) -> Any:
        rig.state["exec"] = ""  # the grade that follows runs as the posture does
        return ExecResult(1, "missing: attrs==23.2.0 (found None)\n", "")

    monkeypatch.setattr(worker.Worker, "_s1_arm_of", arm_of)
    monkeypatch.setattr(PytestRunner, "probe_environment", red_probe)
    s1_run = {"arm": "S1", "test_author": f"fake:{AUTHOR}"}
    run = rig.enqueue(reading, params=s1_run)
    rig.h.run_one()
    assert authored == ["feat: add subtract"]
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == (S1, rig.first)
    (row,) = rig.rows(run.id)
    assert row.error.startswith(f"authoring: {AUTHORING_HARNESS_ERROR} the env probe is red "), (
        row.error
    )
    assert not row.clean and row.failure_kind == FAILURE_HARNESS
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, S1)[rig.first] == (False, "harness")

    # the posture is mended and the run is re-filed: the reservation decided the commit
    monkeypatch.setattr(PytestRunner, "probe_environment", lambda *a, **kw: None)
    rig.state["b"] = "gold"
    second = rig.enqueue(reading, params=s1_run)
    rig.h.run_one()
    assert authored == ["feat: add subtract"], "the re-filed run authored the commit again"
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.rows(second.id) == []
    assert len(rig.reservations(reading)) == 1
    assert rig.verdicts(reading, S1)[rig.first] == (False, "harness")
