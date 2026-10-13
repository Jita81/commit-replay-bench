"""P-792, the losses: an attempt lost after its reservation is still the commit's one attempt.

Part of the P-792 channel tests; tests/test_p792_reserved.py holds the rigs and the rule's own
tests. A run filed under a reserved.v1 reading reserves each commit before its r1 build, so an
attempt lost after that — killed as belt 2 read red (C1), cancelled during the gold witness
(C2), its sandbox lost or its grade failing on the host (C10), or ending with no row the
ledger would take (C15) — is that commit's miss, and a later run skips the commit; a refusal
before the reservation (the claim's credential check, C13) writes nothing and leaves the
commit pending. A settled reservation with no row is charged once by the campaign's tally
(F8, C19's tally half). Each test failed on the code before the worker reserved.

Navigation
----------
What it is:   The P-792 tests of an attempt lost before or after its reservation, end to end
              through the worker.
What it does: C1 (SQLite and PostgreSQL): a kill as belt 2 reads red leaves the reservation,
              the reclaimed run skips the commit, which reads a miss once its claim is
              settled, and the killed claim's late append is refused; C2: a cancel during the
              gold witness writes a harness row that decides the commit; C10: a sandbox lost
              after the build reads ``unobserved`` and a full disk under the grader a
              ``harness`` miss; C13: a credential gone at claim leaves the commit pending, an
              outage after the reservation is its miss; C15: a failed discard after the
              builder raised writes a clean row naming the error, which decides the commit,
              and an attempt the ledger refuses reads a miss once its run has failed; the
              tally holding an in-flight attempt under the run's cap and charging a settled,
              unrowed one at its hold (``unplaced_spend``; ``campaign_cost_unknown`` with no
              hold).
How:          Each test drives P-792's worker rig (``_w_rig``: ``test_worker``'s ``Harness``
              over the pyrepo fixture with a second commit, the fake builder and a local
              sandbox on the run's cancel token, each row relabelled as a sealed worker writes
              it); ``_w_peek`` acts the moment belt 2 reads red, and ``_WKilled`` is the host
              killing the worker mid-grade.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/server/worker.py (the reserver and the run's exits after it, under test),
              src/crb/core/reading.py (the reserved.v1 verdict each lost attempt reads),
              src/crb/server/campaigns.py and src/crb/core/campaign.py (``unplaced_attempts``
              and ``tally``: the settled, unrowed reservation charged once),
              tests/test_p792_reserved.py (the worker rig and its helpers, imported),
              tests/test_worker.py (``Harness`` and ``FakeBuilder``, under the rig),
              docs/PREVENTION.md (P-792, the row these tests close)
Tested by:    tests/test_p792_reserved_losses.py
Touch when:   never for a new repository; a way to lose an attempt after its reservation is
              found (its test here, failing first), or what the worker writes or the tally
              charges when one is lost changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import crb.builders.adapter as adapter_mod
from crb.core.campaign import CAMPAIGN_ADMITTED, tally
from crb.core.ledger import GradeRow
from crb.core.reading import LABEL_CLAIM, LABEL_RESERVATION, SKIP_COMMIT_RESERVED
from crb.server import campaigns as campaigns_mod
from crb.store.events import append_event
from crb.store.jobs import STATUS_FAILED, STATUS_QUEUED, STATUS_RUNNING, claim_guard
from crb.store.ledger import AttemptSettled
from crb.store.models import Run
from fixtures import pyrepo as pr
from fixtures.readings import sealed_row
from test_p792_reserved import (
    _W_CID,
    _w_peek,
    _w_rig,
    _w_row_count,
    _WKilled,
    _worker_defaults_cleared,  # noqa: F401 — autouse: the builder's env defaults cleared
)
from test_worker import FakeBuilder

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401


# --- the worker: a reserved.v1 reading's run reserves each commit before its r1 build ------


def test_p792_c1_kill_after_peek_costs_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """C1, measured: reproduces the enumeration's kill probe (tests/test_zz_enum_kill_probe.py),
    which killed the worker as soon as belt 2 read red, before the row was written; the run was
    reclaimed and re-run with a clean builder, and the commit read a hit. Now the kill leaves
    the reservation: the reclaimed run skips the commit without building it, the commit reads
    a miss (``unobserved``) once its claim is settled, and a late append by the killed claim is
    refused under the grades lock."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["b"] = "noop"

    def kill(_: Run) -> None:
        raise _WKilled

    _w_peek(rig, monkeypatch, kill)
    with pytest.raises(_WKilled):
        rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == ("A0", rig.first)
    assert rig.status(run.id) == STATUS_RUNNING
    assert rig.rows(run.id) == []
    # the killed claim is still running: the commit waits for it
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")

    assert [r.id for r in rig.h.queue.reclaim_stale(0.0)] == [run.id]
    rig.state["b"] = "gold"
    again = rig.h.run_one()
    assert again.id == run.id
    assert rig.skips(run.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert len(FakeBuilder.briefs) == 1  # the killed attempt's build; the re-run built nothing
    assert rig.rows(run.id) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")
    assert len(rig.reservations(reading)) == 1

    # the killed claim's row, had it reached the ledger late, is refused and never stored
    before = _w_row_count(rig)
    late = sealed_row(
        rig.first,
        clean=False,
        arm="A0",
        repo=pr.REPO_NAME,
        labels={LABEL_RESERVATION: res.event_id, LABEL_CLAIM: "0"},
    )
    with pytest.raises(AttemptSettled):
        rig.h.worker.ledger.append(late, guard=claim_guard(run.id, "w-test", 0))
    assert _w_row_count(rig) == before
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")


def test_p792_c2_cancel_during_witness_is_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2, measured in round 4: a cancel asked as soon as belt 2 read red reached the gold
    witness, which the run's cancel token stopped; the row was a harness failure, which the
    legacy rule passes over, so a second run re-rolled the commit and it read a hit. Now the
    harness row is the reserved attempt's and decides the commit: a miss (``harness``), and
    the second run skips the commit without building it."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["b"] = "noop"
    _w_peek(rig, monkeypatch, lambda r: rig.h.queue.request_cancel(r.id, actor="op-1"))
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert row.failure_kind == "harness"
    assert row.labels["env_code"] == "GOLD_CONTROL_RED"
    (control,) = rig.payloads(run.id, "grade.control")
    assert (control["green"], control["rc"]) == (False, 130)
    assert rig.status(run.id) not in (STATUS_QUEUED, STATUS_RUNNING)
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")

    rig.state["b"] = "gold"
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")


def test_p792_c10_sandbox_loss_after_reserve_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C10, from enumeration.md by code reading (no probe ran): a sandbox lost after the
    build stopped the run with no row, and a host-side failure inside grading wrote a harness
    row; the legacy rule read the commit pending, or passed over the harness row, so a later
    attempt decided it. Now both are the reserved attempt's: the lost sandbox reads
    ``unobserved`` once the run has failed, and a second run skips the commit; a full disk
    under the grader is a ``harness`` miss."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.state.update(exec="lost"))
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith("sandbox unavailable")
    assert rig.rows(run.id) == []
    (res,) = rig.reservations(reading)
    assert res.task_id == rig.first
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")

    monkeypatch.setattr(FakeBuilder, "hook", None)
    rig.state["exec"] = ""
    again = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(again.id)
    assert rig.skips(again.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")

    # the second commit's grader fails on the host: a harness row, the reserved attempt's
    rig.state["b"] = "multiply"
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.state.update(exec="disk"))
    disk = rig.enqueue(reading, rig.second)
    rig.h.run_one()
    (row,) = rig.rows(disk.id)
    assert row.failure_kind == "harness"
    assert row.labels[LABEL_RESERVATION] == rig.reservations(reading)[1].event_id
    assert rig.verdicts(reading, "A0")[rig.second] == (False, "harness")


def test_p792_c13_credential_gone_before_reserve_stays_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C13, from enumeration.md by code reading (no probe ran): a provider outage row was an
    outage the legacy rule passed over, so a later attempt decided the commit. Now a refusal
    before the reservation — the claim's credential check — writes nothing and leaves the
    commit pending, while an outage after it is the reserved attempt's miss (``outage``),
    and the next run skips the commit."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    gone = "credential_missing: ANTHROPIC_API_KEY is unset"
    real = rig.h.worker._credential_gone
    monkeypatch.setattr(rig.h.worker, "_credential_gone", lambda run: gone)
    refused = rig.enqueue(reading)
    done = rig.h.run_one()
    assert (done.status, done.error) == (STATUS_FAILED, gone)
    assert "build.start" not in rig.actions(refused.id)
    assert rig.reservations(reading) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")

    monkeypatch.setattr(rig.h.worker, "_credential_gone", real)
    rig.state["b"] = "outage"
    run = rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.failure_kind == "outage" and row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "outage")

    rig.state["b"] = "gold"
    third = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(third.id)
    assert rig.skips(third.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "outage")


def test_p792_c15_settled_reservation_without_a_row_is_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C15, from enumeration.md by code reading (no probe ran), and its mechanism measured
    here: on the replay path a discard that fails after the builder raised grades the edits
    as they are and writes a clean row naming the builder's error in its ``builder_error``
    label (the ledger refuses only a clean row with an ``error``), not no row as the
    enumeration read; that row is the reserved attempt's and decides the commit, and a later
    run skips the commit rather than re-rolling it. What C15's fix needs is that an attempt
    which ends with no row — here the ledger refusing the write — reads a miss
    (``unobserved``) once its run has failed, never pending for a later attempt to decide."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()

    def applied_then_raised(ws: Any, brief: Any) -> None:
        pr.apply_gold(ws)
        raise RuntimeError("the builder fell over after editing")

    def undiscardable(*_: Any, **__: Any) -> list[str]:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(FakeBuilder, "hook", applied_then_raised)
    monkeypatch.setattr(adapter_mod, "discard_source_edits", undiscardable)
    raised = rig.enqueue(reading)
    rig.h.run_one()
    assert "builder.discard.error" in rig.actions(raised.id)
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(raised.id)
    assert row.clean and not row.error
    assert row.labels["builder_error"].startswith("builder raised RuntimeError")
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    monkeypatch.setattr(FakeBuilder, "hook", None)
    reroll = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(reroll.id)
    assert rig.skips(reroll.id) == [(rig.first, SKIP_COMMIT_RESERVED)]

    # the second commit's row never reaches the ledger: a settled reservation with no row
    append = rig.h.worker.ledger.append

    def refused(row: GradeRow, *, guard: Any = None) -> GradeRow:
        if row.task_id == rig.second:
            raise OSError(28, "No space left on device")
        return append(row, guard=guard)

    monkeypatch.setattr(rig.h.worker.ledger, "append", refused)
    rig.state["b"] = "multiply"
    lost = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED
    assert rig.rows(lost.id) == []
    assert [e.task_id for e in rig.reservations(reading)] == [rig.first, rig.second]
    assert rig.verdicts(reading, "A0")[rig.second] == (False, "unobserved")

    monkeypatch.setattr(rig.h.worker.ledger, "append", append)
    again = rig.enqueue(reading, rig.second)
    rig.h.run_one()
    assert "build.start" not in rig.actions(again.id)
    assert rig.skips(again.id) == [(rig.second, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0") == {
        rig.first: (True, ""),
        rig.second: (False, "unobserved"),
    }


def test_p792_tally_charges_unrowed_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """C1's spend (F8, C19's tally half): a run killed after its reservation and before
    ``build.done`` leaves the reservation and no row. While its claim is live the attempt is
    in flight — held under the run's cap and headroom, never charged; once the run is
    reclaimed past that claim the attempt is settled, and the tally charges it at its
    reservation's hold and stops the campaign ``unplaced_spend`` (before, it charged nothing
    and admitted the next run). The reclaimed run skips the commit and ends, and the attempt
    is still charged once. A settled reservation whose hold is ``None`` (an r1 rung with no
    cost cap) is a cost the tally cannot know: ``campaign_cost_unknown``."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    hold: dict[str, float | None] = {"usd": 0.4}
    real = rig.h.worker._reserver
    monkeypatch.setattr(
        rig.h.worker,
        "_reserver",
        lambda *a, **kw: real(*a, **{**kw, "hold_usd": hold["usd"]}),
    )

    def killed(ws: Any, brief: Any) -> None:
        raise _WKilled

    def admitted(*tasks: str) -> Run:
        # filed as POST /runs admits it: a $1.00 cap and the $5.00 held before a priced attempt
        run = rig.enqueue(reading, *tasks, admit=False)
        append_event(
            rig.h.factory,
            trace_id=_W_CID,
            stage="system",
            action=CAMPAIGN_ADMITTED,
            payload={
                "campaign_id": _W_CID,
                "run_id": run.id,
                "cap_usd": 1.0,
                "s1": False,
                "commits": 1,
                "headroom_usd": 5.0,
            },
        )
        return run

    def tallied() -> tuple[list[Any], list[Any]]:
        with rig.h.factory() as s:
            ms = campaigns_mod.members(s, _W_CID)
            return campaigns_mod.unplaced_attempts(s, [m.run_id for m in ms]), ms

    monkeypatch.setattr(FakeBuilder, "hook", killed)
    run = admitted()
    with pytest.raises(_WKilled):
        rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert rig.status(run.id) == STATUS_RUNNING
    assert "build.done" not in rig.actions(run.id) and rig.rows(run.id) == []
    # in flight: the live claim's run holds its cap and headroom, and nothing is charged
    unplaced, ms = tallied()
    assert unplaced == [] and ms[0].spent_usd == 0.0
    live = tally(54.0, ms)
    assert live.held_usd == pytest.approx(1.0 + 5.0)
    assert live.refusal(cap_usd=1.0, s1=False, commits=0) is None

    assert [r.id for r in rig.h.queue.reclaim_stale(0.0)] == [run.id]
    want = campaigns_mod.UnplacedAttempt(
        run_id=run.id,
        task_id=rig.first,
        trial="r1",
        rung="",
        cost_usd=0.4,
        reservation_event_id=res.event_id,
        reading_id=reading.reading_id,
    )
    unplaced, ms = tallied()
    assert unplaced == [want]
    assert ms[0].unrowed_usd == pytest.approx(0.4) and ms[0].spent_usd == pytest.approx(0.4)
    stop = tally(54.0, ms).refusal(cap_usd=1.0, s1=False, commits=0)
    assert stop is not None and stop.code == "unplaced_spend"
    assert stop.detail == {"run_ids": [run.id]}

    # the reclaimed run skips the reserved commit and ends: the attempt is charged once
    monkeypatch.setattr(FakeBuilder, "hook", None)
    assert rig.h.run_one().id == run.id
    assert rig.skips(run.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.status(run.id) not in (STATUS_QUEUED, STATUS_RUNNING)
    unplaced, ms = tallied()
    assert unplaced == [want] and ms[0].spent_usd == pytest.approx(0.4)

    # a reservation held at None: settled, its cost unknown — the unknown cost stops first
    hold["usd"] = None
    monkeypatch.setattr(FakeBuilder, "hook", killed)
    second = admitted(rig.second)
    with pytest.raises(_WKilled):
        rig.h.run_one()
    assert [r.id for r in rig.h.queue.reclaim_stale(0.0)] == [second.id]
    unplaced, ms = tallied()
    assert [(u.run_id, u.task_id, u.cost_usd) for u in unplaced] == [
        (run.id, rig.first, 0.4),
        (second.id, rig.second, None),
    ]
    assert ms[1].unknown == 1 and ms[1].unrowed_usd == 0.0
    stop = tally(54.0, ms).refusal(cap_usd=1.0, s1=False, commits=0)
    assert stop is not None and stop.code == "campaign_cost_unknown"
    assert stop.detail == {"run_ids": [second.id]}
