"""Independent review — a different identity, adversarial probes, verdict BEFORE edit.

The essay's principle: independent evidence beats correlated judgement. Every
delivered change is reviewed by an identity that is neither its builder nor
its test author (enforced by rung label), and the review is mechanical first:

* **RED reproduction** — from a pristine worktree at the proven base, the
  oracle is taken from the oracle *commit* (never from the builder's worktree)
  and re-run; it must fail again, with attributable ids.
* **Belt re-run** — the delivered edits are replayed into a fresh worktree and
  the four belts are graded again with the ordinary grader. A second, independent
  observation of the same verdict.
* **Mutation strength** — deterministic AST mutants are planted in the delivered
  source and the oracle must kill them (:mod:`crb.core.oracle.mutation`). A weak
  oracle is a *major* finding: the change is accepted only with an edit that
  strengthens the test — and that edit re-enters the loop (RED proof → build →
  grade → fresh verdict).

Then the reviewer forms its opinion. The mechanical floor overrides the opinion
only in the safe direction: a failed required probe is a ``reject`` whatever
the reviewer says; a major finding caps the verdict at ``accept_with_edit``;
a reviewer may always be stricter.

The verdict is appended to the factory evidence ledger with
``recorded_before_edit=True`` **before** it is returned — and the ledger refuses
to record an edit for a build that has no verdict (:class:`EditBeforeVerdict`).
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from crb.core.evidence import utc_now_iso
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED, grade
from crb.core.oracle.mutation import changed_lines_from_diff, score_task
from crb.core.redact import redact_and_cap
from crb.core.routing import DEFAULT_POLICY
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace
from crb.factory.backlog import BacklogItem
from crb.factory.build import BuildResult
from crb.factory.evidence import FactoryEvidence, VerdictBeforeEditViolation
from crb.factory.testfirst import RedProof, SameIdentityError, assert_distinct_identity

EventFn = Callable[[str, Mapping[str, Any]], None]

VERDICT_ACCEPT = "accept"
VERDICT_ACCEPT_WITH_EDIT = "accept_with_edit"
VERDICT_REJECT = "reject"
VERDICTS: tuple[str, ...] = (VERDICT_ACCEPT, VERDICT_ACCEPT_WITH_EDIT, VERDICT_REJECT)
_VERDICT_RANK = {VERDICT_ACCEPT: 0, VERDICT_ACCEPT_WITH_EDIT: 1, VERDICT_REJECT: 2}

SEVERITY_INFO = "info"
SEVERITY_MINOR = "minor"
SEVERITY_MAJOR = "major"
SEVERITY_BLOCKING = "blocking"
SEVERITIES: tuple[str, ...] = (SEVERITY_INFO, SEVERITY_MINOR, SEVERITY_MAJOR, SEVERITY_BLOCKING)

#: The ledger's own guard, re-exported under the name the loop speaks.
EditBeforeVerdict = VerdictBeforeEditViolation


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


@dataclass(frozen=True)
class ReviewFinding:
    kind: str
    severity: str
    detail: str
    probe: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        object.__setattr__(self, "detail", redact_and_cap(self.detail, max_chars=2000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "probe": self.probe,
        }


@dataclass(frozen=True)
class ProbeResult:
    """``passed=None`` means the probe could not run — treated as failed when
    ``required`` (fail closed) and as an info finding otherwise."""

    name: str
    passed: bool | None
    detail: str = ""
    required: bool = True
    findings: tuple[ReviewFinding, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", redact_and_cap(self.detail, max_chars=2000))
        object.__setattr__(self, "data", dict(self.data))

    @property
    def failed(self) -> bool:
        return self.required and self.passed is not True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "detail": self.detail,
            "findings": [f.to_dict() for f in self.findings],
            "data": dict(self.data),
            "duration_s": round(self.duration_s, 3),
        }


@dataclass(frozen=True)
class ReviewContext:
    repo: GitRepo
    item: BacklogItem
    build: BuildResult
    proof: RedProof
    config: RepoConfig
    runner: BaseRunner
    executor: Executor
    scratch: Path
    pr_ref: str = ""
    timeout: int = 0
    on_event: EventFn | None = None


@runtime_checkable
class Probe(Protocol):
    name: str

    def run(self, ctx: ReviewContext) -> ProbeResult: ...


# ---------------------------------------------------------------------------
# replaying the delivered edits into a fresh worktree
# ---------------------------------------------------------------------------


def replay_edits(build: BuildResult, dest: Workspace) -> list[str]:
    """Copy the builder's SOURCE edits (never the oracle) from the build worktree
    into ``dest``; a file the builder deleted is deleted. Returns the paths."""
    src = build.workspace
    if src is None:
        raise ValueError("build workspace was closed — cannot replay its edits")
    out: list[str] = []
    for rel in build.changed_files:
        s = src.root / rel
        d = dest.root / rel
        if s.is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(s, d)
        elif d.exists():
            d.unlink()
        out.append(rel)
    return out


def _fresh(ctx: ReviewContext, tag: str) -> Workspace:
    dest = ctx.scratch / f"review-{tag}-{ctx.config.name}-{ctx.item.id}-{ctx.build.oracle.sha[:10]}"
    return Workspace.create(ctx.repo, ctx.build.oracle.sha, dest, config=ctx.config)


class RedReproductionProbe:
    """Re-run the RED proof from a pristine worktree; the oracle comes from the
    oracle commit, and its hash must equal the proof's."""

    name = "red_reproduction"

    def run(self, ctx: ReviewContext) -> ProbeResult:
        t0 = time.monotonic()
        proof, oracle = ctx.proof, ctx.build.oracle
        ws = _fresh(ctx, "red")
        try:
            ws.overlay_tests([oracle.test_path])
            h = ws.file_hash(oracle.test_path)
            if h != proof.test_sha256:
                return ProbeResult(
                    self.name,
                    False,
                    f"oracle in commit {oracle.sha[:12]} hashes to {h!r}, proof says {proof.test_sha256[:12]}",
                    duration_s=time.monotonic() - t0,
                )
            run = ctx.runner.run(ctx.executor, ws.root, proof.target_scope, timeout=ctx.timeout)
            if run.timed_out or run.green or run.parse_error or not run.failing:
                why = (
                    "timed out"
                    if run.timed_out
                    else "GREEN at base"
                    if run.green
                    else f"unattributable ({run.parse_error or 'no ids'})"
                )
                return ProbeResult(
                    self.name,
                    False,
                    f"RED proof did NOT reproduce from a pristine worktree: {why}",
                    data={"returncode": run.returncode},
                    duration_s=time.monotonic() - t0,
                )
            findings: list[ReviewFinding] = []
            if set(run.failing) != set(proof.failing_ids):
                findings.append(
                    ReviewFinding(
                        "red_ids_differ",
                        SEVERITY_MINOR,
                        f"failing ids differ from the proof: {sorted(run.failing)[:10]} vs {list(proof.failing_ids)[:10]}",
                        self.name,
                    )
                )
            return ProbeResult(
                self.name,
                True,
                f"RED reproduced: {len(run.failing)} failing id(s)",
                findings=tuple(findings),
                data={"failing": sorted(run.failing)[:50]},
                duration_s=time.monotonic() - t0,
            )
        except SandboxUnavailable:
            raise
        except Exception as exc:  # harness error is never a pass
            return ProbeResult(
                self.name, None, f"{type(exc).__name__}: {exc}", duration_s=time.monotonic() - t0
            )
        finally:
            ws.remove()


class BeltRerunProbe:
    """Replay the delivered edits into a fresh worktree and grade all four belts again."""

    name = "belt_rerun"

    def run(self, ctx: ReviewContext) -> ProbeResult:
        t0 = time.monotonic()
        ws = _fresh(ctx, "belts")
        try:
            ws.overlay_tests([ctx.build.oracle.test_path])
            replay_edits(ctx.build, ws)
            result = grade(
                ws,
                ctx.build.task,
                config=ctx.config,
                runner=ctx.runner,
                executor=ctx.executor,
                mode=MODE_SIGHTED,
                timeout=ctx.timeout,
                on_event=ctx.on_event,
            )
            belts = result.belts.to_dict()
            if not result.clean:
                return ProbeResult(
                    self.name,
                    False,
                    f"belts did not hold on re-run: {belts} {result.note or result.dq_reason or result.error}",
                    data={"belts": belts, "new_failures": list(result.new_failures)[:20]},
                    duration_s=time.monotonic() - t0,
                )
            return ProbeResult(
                self.name,
                True,
                "all four belts held on an independent re-run",
                data={
                    "belts": belts,
                    "diff_sha256": result.diff.diff_sha256 if result.diff else "",
                },
                duration_s=time.monotonic() - t0,
            )
        except SandboxUnavailable:
            raise
        except Exception as exc:
            return ProbeResult(
                self.name, None, f"{type(exc).__name__}: {exc}", duration_s=time.monotonic() - t0
            )
        finally:
            ws.remove()


class MutationStrengthProbe:
    """Mutation-score the oracle against the delivered source. Not required (an
    unscoreable change is not a defect) but a weak oracle is a MAJOR finding."""

    name = "mutation_strength"

    def __init__(
        self, *, floor: float = DEFAULT_POLICY.min_oracle_strength, max_mutants: int = 12
    ) -> None:
        self.floor = floor
        self.max_mutants = max_mutants

    def run(self, ctx: ReviewContext) -> ProbeResult:
        t0 = time.monotonic()
        ws = _fresh(ctx, "mut")
        try:
            ws.overlay_tests([ctx.build.oracle.test_path])
            paths = replay_edits(ctx.build, ws)
            present = [p for p in paths if ws.exists(p)]
            if present:
                ctx.repo.run("add", "-N", "--", *present, cwd=ws.root)
            changed: dict[str, set[int]] = {}
            for p in present:
                text = ctx.repo.run("diff", "-U0", "HEAD", "--", p, cwd=ws.root).stdout
                changed[p] = changed_lines_from_diff(text)
            task = ctx.build.task.with_(src_files=present or list(ctx.build.task.src_files))
            score = score_task(
                ws,
                task,
                config=ctx.config,
                runner=ctx.runner,
                executor=ctx.executor,
                max_mutants=self.max_mutants,
                changed_lines=changed,
                timeout=ctx.timeout,
                on_event=ctx.on_event,
            )
            data = {
                "total": score.total,
                "killed": score.killed,
                "oracle_strength": score.oracle_strength,
                "note": score.note,
                "escaped": [o.description for o in score.escaped][:10],
            }
            if score.oracle_strength is None:
                return ProbeResult(
                    self.name,
                    None,
                    f"not scoreable: {score.note}",
                    required=False,
                    findings=(
                        ReviewFinding("oracle_unscoreable", SEVERITY_INFO, score.note, self.name),
                    ),
                    data=data,
                    duration_s=time.monotonic() - t0,
                )
            if score.oracle_strength < self.floor:
                return ProbeResult(
                    self.name,
                    False,
                    f"oracle strength {score.oracle_strength:.2f} < {self.floor:.2f}: "
                    f"{len(score.escaped)} escaped mutant(s)",
                    required=False,
                    findings=(
                        ReviewFinding(
                            "weak_oracle",
                            SEVERITY_MAJOR,
                            "the oracle misses fault classes in the delivered change — strengthen the test: "
                            + "; ".join(o.description for o in score.escaped[:5]),
                            self.name,
                        ),
                    ),
                    data=data,
                    duration_s=time.monotonic() - t0,
                )
            return ProbeResult(
                self.name,
                True,
                f"oracle strength {score.oracle_strength:.2f} ({score.killed}/{score.total})",
                required=False,
                data=data,
                duration_s=time.monotonic() - t0,
            )
        except SandboxUnavailable:
            raise
        except Exception as exc:
            return ProbeResult(
                self.name,
                None,
                f"{type(exc).__name__}: {exc}",
                required=False,
                duration_s=time.monotonic() - t0,
            )
        finally:
            ws.remove()


def default_probes() -> tuple[Probe, ...]:
    return (RedReproductionProbe(), BeltRerunProbe(), MutationStrengthProbe())


# ---------------------------------------------------------------------------
# the reviewer and the verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewOpinion:
    verdict: str
    findings: tuple[ReviewFinding, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")
        object.__setattr__(self, "summary", redact_and_cap(self.summary, max_chars=4000))


@runtime_checkable
class Reviewer(Protocol):
    """An identity that forms an opinion on a delivered change given the probe
    results. Its opinion can only tighten the mechanical floor, never loosen it."""

    name: str
    model: str
    provider: str

    def assess(self, ctx: ReviewContext, probes: Sequence[ProbeResult]) -> ReviewOpinion: ...

    def describe(self) -> dict[str, Any]: ...


def reviewer_label(reviewer: Reviewer) -> str:
    return f"{reviewer.name}:{reviewer.model}"


class MechanicalReviewer:
    """The default reviewer: accepts exactly what the probes license."""

    name = "mechanical"
    model = "probes"
    provider = "crb"

    def assess(self, ctx: ReviewContext, probes: Sequence[ProbeResult]) -> ReviewOpinion:
        return ReviewOpinion(VERDICT_ACCEPT, summary="no opinion beyond the mechanical probes")

    def describe(self) -> dict[str, Any]:
        return {"reviewer": self.name, "model": self.model}


@dataclass(frozen=True)
class ReviewVerdict:
    item_id: str
    verdict: str
    reviewer: str
    builder: str
    test_author: str
    pack_hash: str
    pr_ref: str
    red_reproduced: bool
    probes: tuple[ProbeResult, ...] = ()
    findings: tuple[ReviewFinding, ...] = ()
    summary: str = ""
    oracle_strength: float | None = None
    recorded_before_edit: bool = True
    created: str = field(default_factory=utc_now_iso)
    event_id: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")

    @property
    def accepted(self) -> bool:
        return self.verdict == VERDICT_ACCEPT

    @property
    def rework_required(self) -> bool:
        return self.verdict == VERDICT_ACCEPT_WITH_EDIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "verdict": self.verdict,
            "reviewer": self.reviewer,
            "builder": self.builder,
            "test_author": self.test_author,
            "pack_hash": self.pack_hash,
            "pr_ref": self.pr_ref,
            "red_reproduced": self.red_reproduced,
            "probes": [p.to_dict() for p in self.probes],
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "oracle_strength": self.oracle_strength,
            "recorded_before_edit": self.recorded_before_edit,
            "created": self.created,
            "event_id": self.event_id,
        }


def derive_verdict(opinion: ReviewOpinion, probes: Sequence[ProbeResult]) -> tuple[str, str]:
    """Mechanical floor: required-probe failure ⇒ reject; major/blocking finding ⇒
    at least accept_with_edit; the opinion may be stricter, never looser."""
    if any(p.failed for p in probes):
        names = [p.name for p in probes if p.failed]
        return VERDICT_REJECT, f"required probe(s) failed: {', '.join(names)}"
    floor = VERDICT_ACCEPT
    reason = "mechanical probes passed"
    sev = {f.severity for p in probes for f in p.findings} | {f.severity for f in opinion.findings}
    if SEVERITY_BLOCKING in sev:
        floor, reason = VERDICT_REJECT, "a blocking finding was recorded"
    elif SEVERITY_MAJOR in sev:
        floor, reason = VERDICT_ACCEPT_WITH_EDIT, "a major finding requires an edit (and rework)"
    if _VERDICT_RANK[opinion.verdict] > _VERDICT_RANK[floor]:
        return opinion.verdict, f"reviewer opinion: {opinion.summary or opinion.verdict}"
    return floor, reason


def review(
    build: BuildResult,
    pr_ref: str,
    *,
    reviewer: Reviewer,
    item: BacklogItem,
    proof: RedProof,
    repo: GitRepo,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    evidence: FactoryEvidence,
    probes: Sequence[Probe] | None = None,
    timeout: int = 0,
    on_event: EventFn | None = None,
) -> ReviewVerdict:
    """Run the probes, take the reviewer's opinion, derive the verdict, and RECORD
    IT before returning. Raises :class:`SameIdentityError` if the reviewer is the
    builder or the test author."""
    label = reviewer_label(reviewer)
    assert_distinct_identity(build.rung, label, role="reviewer")
    assert_distinct_identity(proof.author, label, role="reviewer")
    ctx = ReviewContext(
        repo=repo,
        item=item,
        build=build,
        proof=proof,
        config=config,
        runner=runner,
        executor=executor,
        scratch=scratch,
        pr_ref=pr_ref,
        timeout=timeout,
        on_event=on_event,
    )
    _emit(on_event, "review.start", item=item.id, reviewer=label, builder=build.rung, pr_ref=pr_ref)
    results: list[ProbeResult] = []
    for probe in probes if probes is not None else default_probes():
        res = probe.run(ctx)
        results.append(res)
        _emit(
            on_event,
            "review.probe",
            item=item.id,
            probe=res.name,
            passed=res.passed,
            required=res.required,
            detail=res.detail,
        )
    opinion = reviewer.assess(ctx, results)
    verdict, reason = derive_verdict(opinion, results)
    red = next((p for p in results if p.name == RedReproductionProbe.name), None)
    mut = next((p for p in results if p.name == MutationStrengthProbe.name), None)
    strength = mut.data.get("oracle_strength") if mut is not None else None
    findings = tuple(f for p in results for f in p.findings) + tuple(opinion.findings)
    v = ReviewVerdict(
        item_id=item.id,
        verdict=verdict,
        reviewer=label,
        builder=build.rung,
        test_author=proof.author,
        pack_hash=build.pack_hash,
        pr_ref=pr_ref,
        red_reproduced=bool(red is not None and red.passed),
        probes=tuple(results),
        findings=findings,
        summary=f"{reason}; {opinion.summary}".strip("; "),
        oracle_strength=float(strength) if isinstance(strength, int | float) else None,
        recorded_before_edit=True,
    )
    ev = evidence.record_verdict(v.to_dict())
    v = replace(v, event_id=ev.event_id)
    _emit(
        on_event, "review.verdict", item=item.id, verdict=verdict, reason=reason, event=ev.event_id
    )
    return v


def permit_edit(
    evidence: FactoryEvidence, item_id: str, *, pack_hash: str, editor: str, note: str = ""
) -> str:
    """Record that a human edit of build ``pack_hash`` is permitted. Raises
    :class:`EditBeforeVerdict` when no verdict for that build is on the record."""
    return evidence.record_edit(item_id, pack_hash=pack_hash, editor=editor, note=note).event_id


__all__ = [
    "SEVERITIES",
    "SEVERITY_BLOCKING",
    "SEVERITY_INFO",
    "SEVERITY_MAJOR",
    "SEVERITY_MINOR",
    "VERDICTS",
    "VERDICT_ACCEPT",
    "VERDICT_ACCEPT_WITH_EDIT",
    "VERDICT_REJECT",
    "BeltRerunProbe",
    "EditBeforeVerdict",
    "MechanicalReviewer",
    "MutationStrengthProbe",
    "Probe",
    "ProbeResult",
    "RedReproductionProbe",
    "ReviewContext",
    "ReviewFinding",
    "ReviewOpinion",
    "ReviewVerdict",
    "Reviewer",
    "SameIdentityError",
    "default_probes",
    "derive_verdict",
    "permit_edit",
    "replay_edits",
    "review",
    "reviewer_label",
]
