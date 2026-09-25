"""The spend rules bound to a real run: the measured escalation stop, the calibrated budget
profile, the per-repository switch, the patch kept for every attempt, and the records on the
row and the apparatus. No docker, no network, no model (the fake builder).

Navigation
----------
What it is:   The worker-level suite for stream K (value programme): what the spend rules do
              to a blind run's rows, end to end through the queue and the DB ledger.
What it does: Seeds the ledger with prior rows, runs a blind ladder with the fake builder, and
              pins: a rung whose prior escalations yielded under the bar is not climbed (one
              row, labelled ``stopped`` with the rule) and ``escalation: always`` — per run or
              per repository — climbs it; with no history the ladder climbs as before; a
              ``calibrated`` run hands the builder caps from prior clean completions (latency
              and the packs' turns) and records profile, calibration and the tier it ran under;
              a default run's builder budget is untouched and its rows carry no profile label;
              every attempt's pack keeps its patch; the policy is on the run's apparatus.
How:          ``test_worker``'s ``Harness`` and ``FakeBuilder``; prior rows appended through
              ``DbLedger``; prior packs inserted as ``EvidencePackRow``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/server/worker.py (``_spend_hooks``, ``_RunLedger._stamp``),
              src/crb/server/spend.py, src/crb/core/spend.py, src/crb/core/run.py,
              src/crb/builders/adapter.py (``budget_for_task``), tests/test_spend.py (the rules)
Tested by:    tests/test_worker_spend.py
Touch when:   a spend label or the apparatus record changes; the gate moves out of ``run_task``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders.base import Budget
from crb.core.ledger import GradeRow, verify_chain
from crb.core.patches import PatchStore, kept_patch_note
from crb.core.spend import (
    LABEL_BUDGET_CALIBRATION,
    LABEL_BUDGET_PROFILE,
    LABEL_ESCALATION,
    LABEL_ESCALATION_RULE,
)
from crb.store.jobs import STATUS_SUCCEEDED
from crb.store.models import EvidencePackRow
from fixtures import pyrepo as pr
from test_worker import FakeBuilder, Harness

SONNET = {"builder": "fake", "model": "sonnet"}


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


def _noop(**cfg: Any) -> FakeBuilder:
    return FakeBuilder(behaviour="noop", **cfg)


def _prior(h: Harness, *, n: int, trial: str, clean: bool, latency_s: float = 10.0) -> list[str]:
    """Append ``n`` prior blind rows in the fixture task's cell; return their pack hashes."""
    size = h.pyrepo.feat_task().size
    hashes: list[str] = []
    for _ in range(n):
        pack = uuid.uuid4().hex * 2
        hashes.append(pack)
        h.worker.ledger.append(
            GradeRow(
                repo=pr.REPO_NAME,
                task_id="b" * 40,
                clean=clean,
                tests_unmodified=True,
                target_green=clean,
                no_new_failures=True,
                source_changed=True,
                mode="blind",
                size=size,
                builder="fake",
                model="sonnet",
                trial=trial,
                latency_s=latency_s,
                evidence_pack_hash=pack,
            )
        )
    return hashes


def _packs_with_turns(h: Harness, hashes: list[str], turns: int) -> None:
    with h.factory() as s:
        for pack in hashes:
            s.add(
                EvidencePackRow(
                    pack_hash=pack,
                    repo=pr.REPO_NAME,
                    task_id="b" * 40,
                    run_id="prior",
                    body_json={"builder": {"turns": turns}},
                )
            )
        s.commit()


def _blind_ladder(h: Harness, **params: Any) -> list[GradeRow]:
    builders_pkg._REGISTRY["fake"] = _noop
    run = h.enqueue("blind", ladder_json=[SONNET, SONNET], params_json=params)
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    return list(h.worker.ledger.rows(run_id=run.id))


def test_a_rung_whose_prior_escalations_did_not_pay_is_not_climbed(h: Harness) -> None:
    _prior(h, n=12, trial="r2", clean=False)
    rows = _blind_ladder(h)
    (row,) = rows  # r2 was never paid for
    assert row.trial == "r1" and not row.clean
    assert row.labels[LABEL_ESCALATION] == "stopped"
    assert row.labels[LABEL_ESCALATION_RULE].endswith("yield=0/12<0.10")
    assert verify_chain(list(h.worker.ledger.rows())) == 13


def test_escalation_always_per_run_climbs_every_rung(h: Harness) -> None:
    _prior(h, n=12, trial="r2", clean=False)
    rows = _blind_ladder(h, escalation="always")
    assert [r.trial for r in rows] == ["r1", "r2"]
    assert rows[0].labels[LABEL_ESCALATION_RULE] == "always"


def test_escalation_always_per_repository_climbs_every_rung(
    tmp_path: Path, pyrepo: pr.PyRepo
) -> None:
    h = Harness(tmp_path, pyrepo)
    h.add_repo(spend={"escalation": "always"})
    h.add_task(pyrepo.feat_task())
    _prior(h, n=12, trial="r2", clean=False)
    rows = _blind_ladder(h)
    assert [r.trial for r in rows] == ["r1", "r2"]
    run = h.worker.queue.get(rows[0].run_id)
    assert run is not None
    assert run.apparatus_json["extra"]["spend"]["sources"]["escalation"] == "repository"


def test_without_history_the_ladder_climbs_as_before_and_says_why(h: Harness) -> None:
    rows = _blind_ladder(h)
    assert [r.trial for r in rows] == ["r1", "r2"]
    assert rows[0].labels[LABEL_ESCALATION] == "climbed"
    assert rows[0].labels[LABEL_ESCALATION_RULE].startswith("measured:insufficient:n=0<10")
    assert LABEL_ESCALATION not in rows[1].labels  # the last rung has nowhere to climb


def test_a_calibrated_run_gets_caps_from_prior_clean_completions(h: Harness) -> None:
    hashes = _prior(h, n=8, trial="r1", clean=True, latency_s=1000.0)
    _packs_with_turns(h, hashes, turns=30)
    seen: list[Budget] = []

    def scripted(**cfg: Any) -> FakeBuilder:
        b = FakeBuilder(behaviour="gold", **cfg)
        real = b.build

        def build(workspace: Any, brief: Any, budget: Budget, **kw: Any) -> Any:
            seen.append(budget)
            return real(workspace, brief, budget, **kw)

        b.build = build  # type: ignore[method-assign]
        return b

    builders_pkg._REGISTRY["fake"] = scripted
    run = h.enqueue("blind", ladder_json=[SONNET], params_json={"budget_profile": "calibrated"})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    # wall clock: p90 1000 s × 1.5 = 1500; turns: p90 30 × 1.5 = 45; tool calls scale with turns
    assert seen == [Budget(max_turns=45, max_tool_calls=45, wall_clock_s=1500)]
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.clean
    assert row.labels[LABEL_BUDGET_PROFILE] == "calibrated"
    assert row.labels[LABEL_BUDGET_CALIBRATION].startswith("repo+mode+size=")
    assert row.labels["budget_tier"] == "45/45/1500"  # what it ran under, not the rung's
    spend = done.apparatus_json["extra"]["spend"]
    assert spend["budget_profile"] == "calibrated" and spend["sources"]["budget_profile"] == "run"


def test_a_default_run_hands_the_builder_its_declared_budget_and_no_profile_label(
    h: Harness,
) -> None:
    hashes = _prior(h, n=8, trial="r1", clean=True, latency_s=1000.0)
    _packs_with_turns(h, hashes, turns=30)
    rows = _blind_ladder(h)
    assert all(LABEL_BUDGET_PROFILE not in r.labels for r in rows)
    assert all(r.labels["budget_tier"] == "25/25/900" for r in rows)


def test_every_attempt_of_a_run_keeps_its_patch(h: Harness) -> None:
    rows = _blind_ladder(h, escalation="always")
    store = PatchStore.under(h.home / "evidence")
    for row in rows:
        note = kept_patch_note(h.worker.ledger.get_pack(row.evidence_pack_hash))
        assert note and store.get(str(note["stored_sha256"])) is not None


def test_an_unreadable_history_measures_nothing_and_never_fails_the_run(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prior(h, n=12, trial="r2", clean=False)
    real = h.worker.ledger.rows

    def rows(*args: Any, **kw: Any) -> Any:
        if not args and not kw:  # the run-start snapshot only
            raise ValueError("a tampered row")
        return real(*args, **kw)

    monkeypatch.setattr(h.worker.ledger, "rows", rows)
    got = _blind_ladder(h)
    assert [r.trial for r in got] == ["r1", "r2"]  # no history → climbs as before
    events = [e for e in h.events(got[0].run_id) if e.action == "run.spend_history_unreadable"]
    assert events and "tampered" in (events[0].error_message + str(events[0].payload))
