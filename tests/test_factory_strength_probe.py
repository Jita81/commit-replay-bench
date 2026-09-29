"""The strength probe is required: a build whose oracle cannot be scored never pushes.

Navigation
----------
What it is:   The suite for G-662 (``product.truth.203``, assessment C2): the mutation
              strength probe is REQUIRED and scoreable (ADR-0025 item 12).
What it does: Pins that a build whose authored test the probe cannot score stops
              ``oracle_not_scoreable`` before any push, with its way forward; that an
              approver's waiver bound to the authored test's exact bytes is the only way past
              it, and that the pull request then names the approver and the reason; that a
              waiver for other bytes does not apply; and that a weak (scored, below the floor)
              oracle keeps its own path — a major ``weak_oracle`` finding, never a required
              failure.
How:          The loop rig of ``tests/test_factory_loop.py`` with the REAL
              ``MutationStrengthProbe``; the mutation API's ``score_task`` is replaced in the
              review module by one that returns an unscoreable score, so the probe's own
              logic is what decides.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0021-factory-review-before-delivery.md,
              docs/adr/0026-the-context-standard.md
Works with:   src/crb/factory/review.py (the probe and the waiver), src/crb/factory/loop.py
              (the stop), src/crb/factory/evidence.py (``review.probe_waived``),
              src/crb/factory/delivery.py (the pull request's waiver section)
Tested by:    tests/test_factory_strength_probe.py
Touch when:   never for a new repository; the probe's required-ness changes (an ADR); the waiver's
              binding changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core.oracle.mutation import CommitOracleScore
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import review as rv
from fixtures import pyrepo as pr
from test_factory_build import authored_multiply, multiply_item
from test_factory_loop import _creds, _rig


def _unscoreable(ws: Any, task: Any, **_: Any) -> CommitOracleScore:
    return CommitOracleScore(
        task_id=task.task_id,
        repo=task.repo,
        src_paths=tuple(task.src_files),
        capability_class=task.capability_class,
        size=task.size,
        total=0,
        killed=0,
        oracle_strength=None,
        note="no mutants could be planted in the changed lines",
    )


def test_the_strength_probe_is_required_on_a_scoreable_oracle() -> None:
    """The probe is constructed required; an unscoreable result is a required failure."""
    probe = rv.MutationStrengthProbe()
    assert probe.required is True
    failed = rv.ProbeResult(probe.name, None, "not scoreable", required=True)
    assert failed.failed


def test_a_build_whose_oracle_cannot_be_scored_stops_before_any_push(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-662: the probe cannot score the authored test → the item stops
    ``oracle_not_scoreable`` after the verdict is on the record and before anything is
    pushed; the reason carries the way forward (a superseding item with a scoreable test, or
    an approver's waiver for these bytes)."""
    monkeypatch.setattr(rv, "score_task", _unscoreable)
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ORACLE_NOT_SCOREABLE
    assert out.delivery is None and not rig.pushes and not rig.prs
    (verdict,) = out.verdicts
    mut = next(p for p in verdict.probes if p.name == rv.MutationStrengthProbe.name)
    assert mut.required and mut.passed is None
    assert "superseding item" in out.error and "waive" in out.error
    kinds = rig.kinds("I-1")
    assert fe.EV_VERDICT in kinds and fe.EV_DELIVERY not in kinds
    route = rig.evidence.events_for("I-1", fe.EV_ROUTE)[-1].payload
    assert route["route"] == "human" and route["reason_code"] == "oracle_not_scoreable"


def test_a_probe_waiver_bound_to_the_tests_bytes_is_the_only_way_past(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An approver's waiver on the chain for the authored test's exact SHA-256 lets the
    build through; the pull request names the approver and the reason. A waiver for other
    bytes is not a waiver."""
    monkeypatch.setattr(rv, "score_task", _unscoreable)
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    authored = authored_multiply()
    rig.evidence.record_probe_waiver(
        "I-1", approver="approver:ada", reason="a docs-only change", test_sha256="0" * 64
    )
    stale = rig.loop().run_item(multiply_item(), authored=authored)
    assert stale.status == fl.STATUS_ORACLE_NOT_SCOREABLE and not rig.prs

    rig.evidence.record_probe_waiver(
        "I-1",
        approver="approver:ada",
        reason="the change is a constant table",
        test_sha256=authored.sha256,
    )
    out = rig.loop().run_item(multiply_item(), authored=authored)
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    (pr_call,) = rig.prs
    assert "approver:ada" in pr_call["body"] and "the change is a constant table" in pr_call["body"]
    mut = next(p for p in out.verdicts[-1].probes if p.name == rv.MutationStrengthProbe.name)
    assert not mut.required and any(f.kind == rv.FINDING_PROBE_WAIVED for f in mut.findings)


def test_the_runs_own_actor_never_waives_its_strength_probe(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-339: a waiver on the chain whose approver is the run's own actor is not a waiver —
    one person would take an unscoreable oracle to a pull request (GOV-4's two-person rule,
    as the route-gate override and the sign-off apply it). The loop records the refusal and
    stops ``oracle_not_scoreable``; the same waiver from another approver lets it through."""
    monkeypatch.setattr(rv, "score_task", _unscoreable)
    authored = authored_multiply()
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), actor="approver:ada")
    rig.evidence.record_probe_waiver(
        "I-1", approver="approver:ada", reason="mine to waive", test_sha256=authored.sha256
    )
    out = rig.loop().run_item(multiply_item(), authored=authored)
    assert out.status == fl.STATUS_ORACLE_NOT_SCOREABLE and not rig.prs and not rig.pushes
    refused = rig.evidence.events_for("I-1", fe.EV_ROUTE)
    assert any(e.payload.get("waiver_refused") == "same_actor" for e in refused)
    rig.evidence.record_probe_waiver(
        "I-1", approver="approver:bea", reason="a constant table", test_sha256=authored.sha256
    )
    assert rig.loop().run_item(multiply_item(), authored=authored).delivery is not None


def test_a_weak_oracle_is_a_major_finding_never_a_required_failure(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scored below the floor: the oracle is weak, which asks for a stronger test
    (``oracle_needs_strengthening`` with no author to strengthen it) — the scoreable path,
    not ``oracle_not_scoreable``."""

    def weak(ws: Any, task: Any, **_: Any) -> CommitOracleScore:
        return CommitOracleScore(
            task_id=task.task_id,
            repo=task.repo,
            src_paths=tuple(task.src_files),
            capability_class=task.capability_class,
            size=task.size,
            total=4,
            killed=1,
            oracle_strength=0.25,
        )

    monkeypatch.setattr(rv, "score_task", weak)
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ORACLE_NEEDS_STRENGTHENING and not rig.prs
    mut = next(p for p in out.verdicts[-1].probes if p.name == rv.MutationStrengthProbe.name)
    assert mut.passed is False and not mut.failed


def test_a_probe_that_crashes_while_scoring_stops_the_item_before_any_push(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe fails closed when scoring itself raises (a harness failure): the result is
    a required failure, so the item stops ``oracle_not_scoreable`` with nothing pushed —
    a crashed probe is never an accepted, delivered build."""

    def crash(ws: Any, task: Any, **_: Any) -> CommitOracleScore:
        raise RuntimeError("the mutant runner could not start")

    monkeypatch.setattr(rv, "score_task", crash)
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ORACLE_NOT_SCOREABLE
    assert out.delivery is None and not rig.pushes and not rig.prs
    mut = next(p for p in out.verdicts[-1].probes if p.name == rv.MutationStrengthProbe.name)
    assert mut.required and mut.passed is None and mut.failed
    assert "RuntimeError" in mut.detail and "could not start" in out.error
