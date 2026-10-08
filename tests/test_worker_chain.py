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
              chain that would name a build kind is refused at the seam; and that every
              attribute the API's submit gate reads for a chain body resolves on the
              worker's stand-in for the API's settings (P-676).
How:          ``Harness`` from tests/test_worker.py runs a real probe on ``pyrepo`` through
              the local executor; the switch is seeded on the repository row and its
              ``repo.updated`` event through ``append_system_event``. The stand-in check runs
              ``submit_refusals`` over the API's own ``Settings`` behind a proxy that
              records each attribute path read.
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

import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from crb.server import builder_login
from crb.server import worker as worker_mod
from crb.server.deps import ApiError
from crb.server.routes.runs import (
    append_system_event,
    new_run,
    submit_refusals,
    system_trace_id,
)
from crb.server.schemas import BUILD_KINDS
from crb.server.settings import Settings
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


def _finished(h: Harness, kind: str, status: str = STATUS_SUCCEEDED, **counts: object) -> Run:
    """A run of ``kind`` that already finished with ``status`` (a stage the walk holds)."""
    run = h.enqueue(kind)
    with h.factory() as s:
        row = s.get(Run, run.id)
        assert row is not None
        row.status = status
        row.finished = "2026-09-29T08:00:00+00:00"
        row.counts_json = dict(counts)
        s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def test_a_succeeded_stage_without_its_pass_fact_chains_nothing(h: Harness) -> None:
    """DL-315 (2): succeeded is not enough — the stage's OWN pass fact must hold. A mine
    that found no gold-clean task, a probe whose counts say not green, chain nothing; the
    same call with the fact present chains (the positive control proves the path is live)."""
    h.add_repo(auto_stages=True)
    _switched_on(h)
    mine = _finished(h, "mine", gold_clean=0, tasks=3)
    h.worker._chain_next_stage(mine, mine.counts_json)
    assert [r.kind for r in _runs(h)] == ["mine"]
    assert _chain_events(h) == []
    probe = _finished(h, "probe", green=False)
    h.worker._chain_next_stage(probe, probe.counts_json)
    assert sorted(r.kind for r in _runs(h)) == ["mine", "probe"]
    assert _chain_events(h) == []
    # the positive control: the same mine with one gold-clean task chains the qualify
    h.worker._chain_next_stage(mine, {"gold_clean": 1, "tasks": 3})
    assert sorted(r.kind for r in _runs(h)) == ["mine", "probe", "qualify"]
    assert [e.payload_json["kind"] for e in _chain_events(h)] == ["qualify"]


def test_the_seam_itself_refuses_a_build_kind_and_says_so(
    h: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DL-315 (4): the refusal is the seam's own, observed as its error line — not
    ``RunCreateRequest`` refusing a builderless replay further down (which would be logged
    as a failed queueing, never as a refusal)."""
    monkeypatch.setattr(worker_mod, "FREE_CHAIN", ("probe", "replay"))
    h.add_repo(auto_stages=True)
    _switched_on(h)
    probe = _finished(h, "probe", green=True)
    with caplog.at_level("ERROR", logger=worker_mod._LOG.name):
        h.worker._chain_next_stage(probe, probe.counts_json)
    refusals = [
        r for r in caplog.records if "a stage that spends is never chained" in r.getMessage()
    ]
    assert len(refusals) == 1 and refusals[0].levelname == "ERROR"
    assert not [r for r in caplog.records if "queuing the next stage" in r.getMessage()]
    assert [r.kind for r in _runs(h)] == ["probe"]
    assert _chain_events(h) == []


def test_the_chain_never_re_walks_a_stage_already_done_or_in_flight(h: Harness) -> None:
    """DL-315 (5): a re-run of a free stage on a walked repository queues nothing the walk
    already holds — a next stage that succeeded, or is queued or running, is left alone; a
    failed one is chained again (it is the walk's Retry)."""
    h.add_repo(auto_stages=True)
    _switched_on(h)
    done_mine = _finished(h, "mine", gold_clean=2)
    probe = _finished(h, "probe", green=True)
    h.worker._chain_next_stage(probe, probe.counts_json)
    assert sorted(r.kind for r in _runs(h)) == ["mine", "probe"]
    assert _chain_events(h) == []
    # a next stage in flight (queued) is not doubled
    with h.factory() as s:
        row = s.get(Run, done_mine.id)
        assert row is not None
        row.status = STATUS_QUEUED
        s.commit()
    probe2 = _finished(h, "probe", green=True)
    h.worker._chain_next_stage(probe2, probe2.counts_json)
    assert sorted(r.kind for r in _runs(h)) == ["mine", "probe", "probe"]
    assert _chain_events(h) == []
    # a failed next stage is chained again: that is the walk's Retry
    with h.factory() as s:
        row = s.get(Run, done_mine.id)
        assert row is not None
        row.status = STATUS_FAILED
        s.commit()
    probe3 = _finished(h, "probe", green=True)
    h.worker._chain_next_stage(probe3, probe3.counts_json)
    assert sorted(r.kind for r in _runs(h)) == ["mine", "mine", "probe", "probe", "probe"]
    assert [e.payload_json["chained_from"] for e in _chain_events(h)] == [probe3.id]


def test_a_switch_set_at_registration_names_the_registrar_as_the_actor(h: Harness) -> None:
    """``POST /repos`` accepts ``auto_stages`` too, recorded as ``repo.created`` — the person
    who registered the repository with the switch on is the chain's actor, not the run's."""
    h.add_repo(auto_stages=True)
    with h.factory() as s:
        append_system_event(
            s,
            trace_id=system_trace_id("repo", pr.REPO_NAME),
            action="repo.created",
            repo=pr.REPO_NAME,
            actor="registrar-3",
            payload={"config": {**h.pyrepo.config.to_dict(), "auto_stages": True}},
        )
        s.commit()
    probe = _finished(h, "probe", green=True)
    h.worker._chain_next_stage(probe, probe.counts_json)
    runs = _runs(h)
    assert [r.kind for r in runs] == ["probe", "mine"]
    assert runs[1].actor == "registrar-3"
    assert _chain_events(h)[0].actor == "registrar-3"


class _Reads:
    """The API's settings behind a proxy that records each attribute path read through it
    (``factory.test_author``); a nested settings model is proxied in turn. A read the real
    settings cannot answer raises as it would and is not recorded: a ``getattr`` default
    the gate would take on the stand-in too."""

    def __init__(self, target: object, seen: set[str], prefix: str = "") -> None:
        self._target = target
        self._seen = seen
        self._prefix = prefix

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._target, name)
        path = self._prefix + name
        self._seen.add(path)
        return _Reads(value, self._seen, path + ".") if isinstance(value, BaseModel) else value


def _gate_reads(h: Harness) -> dict[str, set[str]]:
    """Every attribute path ``submit_refusals`` reads off the API's own ``Settings`` for each
    body the chain can build — the chain's own ``_chain_body`` for every kind in
    ``FREE_CHAIN`` (the probe, which nothing chains, included: a superset costs nothing),
    the gate called as the chain calls it. A refusal is the gate's answer, not drift: the
    reads made before it count."""
    api = Settings(env="dev", home=h.home)
    reads: dict[str, set[str]] = {}
    with h.factory() as db:
        for kind in worker_mod.FREE_CHAIN:
            body = h.worker._chain_body(pr.REPO_NAME, kind)
            seen: set[str] = set()
            with contextlib.suppress(ApiError):
                submit_refusals(db, _Reads(api, seen), body, new_run(body, actor=SWITCHER))
            reads[kind] = seen
    return reads


def _unresolved(paths: set[str], stand_in: object) -> list[str]:
    """The paths in ``paths`` that do not resolve on ``stand_in``, sorted."""
    missing: list[str] = []
    for path in paths:
        obj: object = stand_in
        for part in path.split("."):
            if not hasattr(obj, part):
                missing.append(path)
                break
            obj = getattr(obj, part)
    return sorted(missing)


def test_the_chain_gate_settings_carry_every_field_the_submit_gate_reads(h: Harness) -> None:
    """P-676, P-672's class come back: the chain hands ``submit_refusals`` a stand-in for the
    API's ``Settings``, and ``settings: Any`` keeps mypy blind to a field the gate reads that
    the stand-in lacks. Wave 4's login check read ``settings.builder``, the stand-in had
    none, and every chained stage raised — caught and logged, so none was ever queued. Every
    attribute path the gate reads off the API's own settings, for every body the chain
    builds, must resolve on the worker's stand-in."""
    h.add_repo()
    reads = _gate_reads(h)
    stand_in = h.worker._chain_gate_settings()
    missing = {kind: _unresolved(paths, stand_in) for kind, paths in reads.items()}
    assert not any(missing.values()), (
        f"the submit gate reads settings the chain's stand-in lacks: {missing} — carry them "
        "in Worker._chain_gate_settings (docs/PREVENTION.md P-676)"
    )
    # the stand-in's builder values feed a login check that cannot fire for a free stage
    assert set(worker_mod.FREE_CHAIN).isdisjoint(builder_login.GATED_KINDS)


def test_the_gate_settings_check_reports_a_stand_in_without_builder(h: Harness) -> None:
    """The negative control: the check sees the bug it exists for. Today's stand-in without
    ``builder`` — before 30c08b7b, ``home`` and ``factory`` only — is reported for every
    chain body, and for nothing else; and without any one field the gate reads, that field
    is reported."""
    h.add_repo()
    reads = _gate_reads(h)
    fields = vars(h.worker._chain_gate_settings())

    def dropped(name: str) -> SimpleNamespace:
        return SimpleNamespace(**{k: v for k, v in fields.items() if k != name})

    for kind, paths in reads.items():
        missing = _unresolved(paths, dropped("builder"))
        assert missing and {p.split(".")[0] for p in missing} == {"builder"}, (kind, missing)
    every = set().union(*reads.values())
    for top in {p.split(".")[0] for p in every}:
        assert top in _unresolved(every, dropped(top)), top
