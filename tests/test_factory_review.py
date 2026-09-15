"""crb.factory.review — different identity, probes reproduce the evidence, verdict before edit.

Navigation
----------
What it is:   The factory review step's test suite — a different identity, probes that reproduce
              the evidence, verdict before edit.
What it does: Pins that the reviewer's identity must differ from builder and author, that on the
              accept path the probes reproduce and the verdict is recorded FIRST, that
              verdict-before-edit is enforced both ways, that a hardcoded source yields a weak
              oracle and accept-with-edit, that a required probe's failure rejects whatever the
              reviewer says, that a reviewer may be stricter never looser, that a tampered oracle
              branch is caught by RED reproduction, and that the evidence chain detects a
              rewritten verdict.
How:          ``OpinionReviewer`` plus ``FailingProbe`` / ``MajorProbe`` over a build from
              ``test_factory_build``'s harness.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/factory/review.py (under test), src/crb/factory/evidence.py (the chain),
              src/crb/factory/testfirst.py (``RedProof`` reproduced), src/crb/factory/build.py
              (``BuildResult``), tests/test_factory_build.py (the harness)
Tested by:    tests/test_factory_review.py
Touch when:   a probe kind is added (a required-failure case); the verdict vocabulary changes
              (stricter-never-looser must survive).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import LedgerIntegrityError
from crb.factory import evidence as fe
from crb.factory import review as rv
from crb.factory.build import BuildResult
from crb.factory.testfirst import RedProof, SameIdentityError
from test_factory_build import (
    MULTIPLY_HARDCODED,
    FakeBuilder,
    Harness,
    append_src,
    authored_multiply,
    harness,
    multiply_item,
)

__all__ = ["harness"]


@dataclass
class OpinionReviewer:
    """A reviewer that answers a fixed verdict and findings (and records the probes it was shown)."""

    verdict: str = rv.VERDICT_ACCEPT
    name: str = "reviewer"
    model: str = "r1"
    provider: str = "fake"
    findings: tuple[rv.ReviewFinding, ...] = ()
    seen: list[Sequence[rv.ProbeResult]] | None = None

    def assess(self, ctx: rv.ReviewContext, probes: Sequence[rv.ProbeResult]) -> rv.ReviewOpinion:
        if self.seen is not None:
            self.seen.append(probes)
        return rv.ReviewOpinion(self.verdict, self.findings, summary=f"opinion: {self.verdict}")

    def describe(self) -> dict[str, Any]:
        return {"reviewer": self.name}


class FailingProbe:
    """A required probe that always fails — the reviewer's opinion must not override it."""

    name = "adversarial_fail"

    def run(self, ctx: rv.ReviewContext) -> rv.ProbeResult:
        return rv.ProbeResult(self.name, False, "found a vector")


class MajorProbe:
    """A probe that fails with a ``major`` finding, for the stricter-never-looser case."""

    name = "major_only"

    def run(self, ctx: rv.ReviewContext) -> rv.ProbeResult:
        return rv.ProbeResult(
            self.name,
            False,
            "weak",
            required=False,
            findings=(rv.ReviewFinding("weak_oracle", rv.SEVERITY_MAJOR, "strengthen", self.name),),
        )


def _evidence(tmp_path: Path) -> fe.FactoryEvidence:
    return fe.FactoryEvidence(fe.JsonlFactoryStore(tmp_path / "evidence.jsonl"), actor="tester")


def _built(harness: Harness, builder: FakeBuilder | None = None) -> tuple[BuildResult, RedProof]:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    return harness.build(item, authored, proof, builder or FakeBuilder()), proof


def _review(
    harness: Harness, build: BuildResult, proof: RedProof, ev: fe.FactoryEvidence, **kw: Any
) -> rv.ReviewVerdict:
    kw.setdefault("reviewer", OpinionReviewer())
    return rv.review(
        build,
        "https://github.invalid/pr/1",
        item=multiply_item(),
        proof=proof,
        repo=harness.repo.repo,
        config=harness.repo.config,
        runner=harness.runner,
        executor=harness.executor,
        scratch=harness.scratch,
        evidence=ev,
        **kw,
    )


def test_reviewer_identity_must_differ_from_builder_and_author(
    harness: Harness, tmp_path: Path
) -> None:
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    try:
        with pytest.raises(SameIdentityError):
            _review(harness, build, proof, ev, reviewer=OpinionReviewer(name="fake", model="good"))
        with pytest.raises(SameIdentityError):
            _review(
                harness,
                build,
                proof,
                ev,
                reviewer=OpinionReviewer(name="operator", model="po@example"),
            )
        assert ev.events() == []  # nothing recorded on a refused review
    finally:
        build.close()


def test_accept_path_probes_reproduce_and_verdict_is_recorded_first(
    harness: Harness, tmp_path: Path
) -> None:
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    reviewer = OpinionReviewer(seen=[])
    events: list[tuple[str, dict[str, Any]]] = []
    try:
        v = _review(
            harness,
            build,
            proof,
            ev,
            reviewer=reviewer,
            on_event=lambda a, p: events.append((a, dict(p))),
        )
    finally:
        build.close()
    assert v.verdict == rv.VERDICT_ACCEPT and v.accepted and not v.rework_required
    assert (
        v.reviewer == "reviewer:r1" and v.builder == "fake:good" and v.test_author == proof.author
    )
    assert v.red_reproduced and v.recorded_before_edit
    by_name = {p.name: p for p in v.probes}
    assert by_name["red_reproduction"].passed is True
    assert (
        by_name["belt_rerun"].passed is True
        and by_name["belt_rerun"].data["belts"]["source_changed"] is True
    )
    assert by_name["mutation_strength"].passed is True and v.oracle_strength == 1.0
    # the verdict is on the ledger, chained, with the pack hash, BEFORE we got it back
    rec = ev.verdict_for("I-1", build.pack_hash)
    assert rec is not None and rec.event_id == v.event_id
    assert rec.payload["verdict"] == "accept" and rec.payload["recorded_before_edit"] is True
    assert ev.verify() == 1
    assert [a for a, _ in events][:2] == ["review.start", "review.probe"]
    assert reviewer.seen and len(reviewer.seen[0]) == 3
    # fresh worktrees were used and removed
    assert not any(harness.scratch.glob("review-*"))


def test_verdict_before_edit_is_enforced_both_ways(harness: Harness, tmp_path: Path) -> None:
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    try:
        with pytest.raises(rv.EditBeforeVerdict):
            rv.permit_edit(ev, "I-1", pack_hash=build.pack_hash, editor="human")
        v = _review(harness, build, proof, ev, probes=())
        assert v.accepted
        eid = rv.permit_edit(ev, "I-1", pack_hash=build.pack_hash, editor="human", note="typo")
        assert ev.edits_for("I-1", build.pack_hash)[0].event_id == eid
        # a verdict cannot claim to precede an edit that is already on the record
        with pytest.raises(fe.VerdictBeforeEditViolation):
            _review(harness, build, proof, ev, probes=())
        # but a post-edit verdict is recordable when it says so
        ev.record_verdict({**v.to_dict(), "recorded_before_edit": False})
        assert ev.verify() == 3
    finally:
        build.close()


def test_hardcoded_source_gives_weak_oracle_and_accept_with_edit(
    harness: Harness, tmp_path: Path
) -> None:
    build, proof = _built(harness, FakeBuilder(edit=append_src(MULTIPLY_HARDCODED)))
    ev = _evidence(tmp_path)
    try:
        assert build.clean  # the belts cannot see a hard-coded cheat …
        v = _review(harness, build, proof, ev)
    finally:
        build.close()
    # … but the mutation probe can: escaped mutants → major finding → rework required
    assert v.verdict == rv.VERDICT_ACCEPT_WITH_EDIT and v.rework_required
    assert v.oracle_strength is not None and v.oracle_strength < 0.8
    assert any(f.kind == "weak_oracle" and f.severity == rv.SEVERITY_MAJOR for f in v.findings)
    assert v.red_reproduced


def test_required_probe_failure_rejects_whatever_the_reviewer_says(
    harness: Harness, tmp_path: Path
) -> None:
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    try:
        v = _review(
            harness,
            build,
            proof,
            ev,
            probes=(FailingProbe(),),
            reviewer=OpinionReviewer(rv.VERDICT_ACCEPT),
        )
    finally:
        build.close()
    assert v.verdict == rv.VERDICT_REJECT and "adversarial_fail" in v.summary


def test_reviewer_may_be_stricter_never_looser(harness: Harness, tmp_path: Path) -> None:
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    try:
        strict = _review(
            harness, build, proof, ev, probes=(), reviewer=OpinionReviewer(rv.VERDICT_REJECT)
        )
        assert strict.verdict == rv.VERDICT_REJECT and "opinion" in strict.summary
        loose = _review(
            harness,
            build,
            proof,
            ev,
            probes=(MajorProbe(),),
            reviewer=OpinionReviewer(rv.VERDICT_ACCEPT),
        )
        assert loose.verdict == rv.VERDICT_ACCEPT_WITH_EDIT
        blocking = _review(
            harness,
            build,
            proof,
            ev,
            probes=(),
            reviewer=OpinionReviewer(
                rv.VERDICT_ACCEPT,
                findings=(rv.ReviewFinding("vector", rv.SEVERITY_BLOCKING, "sql path"),),
            ),
        )
        assert blocking.verdict == rv.VERDICT_REJECT
    finally:
        build.close()
    assert ev.verify() == 3


def test_tampered_oracle_branch_is_caught_by_red_reproduction(
    harness: Harness, tmp_path: Path
) -> None:
    """After the build, someone rewrites the oracle commit's test: the reviewer's
    pristine re-run compares the commit's bytes to the proof hash and rejects."""
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    repo = harness.repo.repo
    try:
        # forge a replacement oracle commit on the same branch and point the task at it
        forged = authored_multiply("def test_multiply():\n    assert True\n")
        from crb.factory.testfirst import worktree_at, write_authored

        ws = worktree_at(repo, build.oracle.parent, harness.scratch / "forge")
        write_authored(ws, forged)
        repo.run("add", "--", forged.path, cwd=ws.root, check=True)
        repo.run(
            "-c",
            "user.name=x",
            "-c",
            "user.email=x@x",
            "commit",
            "-q",
            "-m",
            "forge",
            cwd=ws.root,
            check=True,
        )
        sha = repo.run("rev-parse", "HEAD", cwd=ws.root, check=True).stdout.strip()
        ws.remove()
        from dataclasses import replace

        forged_build = replace(
            build, oracle=replace(build.oracle, sha=sha), task=build.task.with_(task_id=sha)
        )
        v = _review(harness, forged_build, proof, ev, probes=(rv.RedReproductionProbe(),))
    finally:
        build.close()
    assert v.verdict == rv.VERDICT_REJECT and not v.red_reproduced
    assert "hashes to" in v.probes[0].detail


def test_evidence_chain_detects_a_rewritten_verdict(harness: Harness, tmp_path: Path) -> None:
    build, proof = _built(harness)
    ev = _evidence(tmp_path)
    try:
        _review(harness, build, proof, ev, probes=())
    finally:
        build.close()
    p = tmp_path / "evidence.jsonl"
    text = p.read_text().replace('"verdict": "accept"', '"verdict": "reject"')
    p.write_text(text)
    with pytest.raises(LedgerIntegrityError):
        ev.verify()
