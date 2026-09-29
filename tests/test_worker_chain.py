"""The £0 stages chain from one act (DL-315): a passing stage queues the next, under the person
who switched it on, once, and never a stage that spends.

Navigation
----------
What it is:   The worker-side test suite of ``Worker._chain_next_stage`` and ``FREE_CHAIN``.
What it does: Pins that a green probe on a repository whose ``auto_stages`` switch is on
              queues ONE ``mine`` run — its actor the person whose ``repo.updated`` switched
              the setting on, ``params.chained_from`` the probe, a ``connect.stage.chained``
              event on the repository's trace — and that a second finish of the same run
              chains nothing more; that nothing is chained with the switch off; that a failed
              stage chains nothing; and that the chain never queues a ``BUILD_KINDS`` kind:
              the constant is disjoint from them, the last free stage chains nothing, and a
              chain that would name a build kind is refused at the seam.
How:          ``Harness`` from tests/test_worker.py runs a real probe on ``pyrepo`` through
              the local executor; the switch is seeded on the repository row and its
              ``repo.updated`` event through ``append_system_event``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md (the qualify stage in the chain)
Works with:   src/crb/server/worker.py (under test), src/crb/server/routes/runs.py
              (``new_run`` / ``submit_refusals`` — how the chained run is made),
              src/crb/server/routes/repos.py (``PUT /repos/{name}`` writes the switch),
              tests/test_worker.py (the harness)
Tested by:    tests/test_worker_chain.py
Touch when:   never for a new repository; a stage is added to ``FREE_CHAIN`` or a stage's pass
              fact changes (``stage_passed``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from crb.server import worker as worker_mod
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas import BUILD_KINDS
from crb.store.jobs import STATUS_FAILED, STATUS_QUEUED, STATUS_SUCCEEDED
from crb.store.models import Event, Run
from fixtures import pyrepo as pr
from test_worker import Harness

SWITCHER = "op-7"


def _switched_on(h: Harness, actor: str = SWITCHER) -> None:
    """The ``repo.updated`` event ``PUT /repos/{name} {auto_stages: true}`` records."""
    with h.factory() as s:
        append_system_event(
            s,
            trace_id=system_trace_id("repo", pr.REPO_NAME),
            action="repo.updated",
            repo=pr.REPO_NAME,
            actor=actor,
            payload={
                "diff": {"auto_stages": {"from": False, "to": True}},
                "fields": ["auto_stages"],
                "github_unlinked": False,
            },
        )
        s.commit()


def _runs(h: Harness) -> list[Run]:
    with h.factory() as s:
        return list(s.execute(select(Run).order_by(Run.created, Run.id)).scalars().all())


def _chain_events(h: Harness) -> list[Event]:
    with h.factory() as s:
        return list(
            s.execute(
                select(Event).where(
                    Event.repo == pr.REPO_NAME, Event.action == worker_mod.CHAIN_EVENT
                )
            )
            .scalars()
            .all()
        )


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    return Harness(tmp_path, pyrepo)


def test_a_passing_probe_queues_the_mine_when_the_switch_is_on(h: Harness) -> None:
    h.add_repo(auto_stages=True)
    _switched_on(h)
    probe = h.enqueue("probe")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    runs = _runs(h)
    assert [r.kind for r in runs] == ["probe", "mine"]
    mine = runs[1]
    assert mine.status == STATUS_QUEUED
    assert mine.params_json["chained_from"] == probe.id
    # the actor is the person whose repo.updated switched the setting on, never the worker
    assert mine.actor == SWITCHER
    events = _chain_events(h)
    assert len(events) == 1
    assert events[0].payload_json == {
        "chained_from": probe.id,
        "from_kind": "probe",
        "kind": "mine",
        "run_id": mine.id,
    }
    assert events[0].actor == SWITCHER
    # idempotent per finished run: a reclaimed run's second finish chains nothing more
    h.worker._chain_next_stage(done, done.counts_json)
    assert [r.kind for r in _runs(h)] == ["probe", "mine"]
    assert len(_chain_events(h)) == 1


def test_nothing_is_chained_with_the_switch_off(h: Harness) -> None:
    h.add_repo()  # auto_stages defaults to off
    _switched_on(h)  # an old switch-on event with the switch now off changes nothing
    done = h.run_one() if h.enqueue("probe") else None
    assert done is not None and done.status == STATUS_SUCCEEDED, done and done.error
    assert [r.kind for r in _runs(h)] == ["probe"]
    assert _chain_events(h) == []


def test_a_failed_stage_chains_nothing(h: Harness) -> None:
    # a probe scope that names no test: pytest exits 4, the probe is not green
    h.add_repo(auto_stages=True, probe="tests/test_no_such_file.py")
    _switched_on(h)
    h.enqueue("probe")
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert [r.kind for r in _runs(h)] == ["probe"]
    assert _chain_events(h) == []


def test_the_chain_never_queues_a_kind_that_spends_model_money(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the constant itself: no free stage is a build kind
    assert set(worker_mod.FREE_CHAIN).isdisjoint(BUILD_KINDS)
    assert worker_mod.FREE_CHAIN[-1] == "controls"
    # the last free stage chains nothing: nothing follows the controls
    assert h.worker._next_free_stage("controls") is None
    assert h.worker._next_free_stage("replay") is None
    # and the seam refuses a chain that would name a build kind, whatever the constant says
    monkeypatch.setattr(worker_mod, "FREE_CHAIN", ("probe", "replay"))
    h.add_repo(auto_stages=True)
    _switched_on(h)
    h.enqueue("probe")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert [r.kind for r in _runs(h)] == ["probe"]
    assert _chain_events(h) == []
