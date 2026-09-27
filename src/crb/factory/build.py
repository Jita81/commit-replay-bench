"""Build under the four belts — forward mode, graded by the unchanged replay grader.

The replay grader (:func:`crb.core.grade.grade`) judges a worktree at a commit's
*parent* against that commit's own test files. Forward mode has no commit, so
this module manufactures the smallest honest one:

1. **Stage the oracle.** The RED-proven authored test — and ONLY it — is
   committed on a throwaway factory branch ``crb/factory/<item_id>/test`` with
   HEAD as its parent (:func:`stage_oracle_commit`). The commit is verified to
   touch exactly that path and to carry exactly the RED-proof bytes
   (:class:`OracleTampered` otherwise). That commit is the synthetic task id.
2. **Build at the parent with the test overlaid**, exactly as replay does:
   ``Workspace.create(repo, oracle_sha)`` checks out HEAD, ``overlay_tests``
   brings the authored test in, the belt-3 baseline is captured *before* the
   builder runs, and the builder gets a sighted :class:`BuildBrief` carrying the
   item's description, acceptance criteria and structural facts.
3. **Grade with the ordinary path.** ``tests_byte_identical`` compares against
   ``git show <oracle_sha>:<path>`` — the RED-proof bytes — so belt 1 is the real
   belt 1; belts 2–4 are unchanged. The result is an :class:`EvidencePack` and a
   :class:`GradeRow` with ``process_step="factory"``; false-Q1 = 0 is enforced by
   the same write-time invariants.

Identity: the builder that builds the source is refused if it is the identity
that authored the oracle (:func:`crb.factory.testfirst.assert_distinct_identity`).

Navigation
----------
What it is:   Build under the four belts in forward mode — the smallest honest commit that
              lets the unchanged replay grader judge new work.
What it does: Commits ONLY the RED-proven test on a throwaway branch parented at HEAD
              (refusing any bytes that differ from the proof — ``OracleTampered``), builds
              at the parent with the test overlaid exactly as replay does, grades with the
              ordinary grader so belt 1 is the real belt 1, writes the evidence pack and a
              ``process_step="factory"`` ledger row; ``build_ladder`` climbs the escalation
              rungs until clean or disqualified, refusing any rung that authored the oracle.
How:          ``stage_oracle_commit`` → ``Workspace.create(repo, oracle_sha)`` +
              ``overlay_tests`` → baseline → ``factory_brief`` → builder → ``grade`` →
              ``EvidencePack`` + ``write_pack`` → ``factory_row`` → ``JsonlLedger.append``.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md,
              docs/adr/0004-builder-registry-sighted-and-blind.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/grade.py (the grader, unchanged), src/crb/core/workspace.py (the
              trial tree), src/crb/factory/testfirst.py (``RedProof`` / identity check),
              src/crb/builders/base.py (``Builder``, ``BuildBrief``, ``Rung``),
              src/crb/core/ledger.py (``GradeRow`` with ``PROCESS_FACTORY``),
              src/crb/factory/delivery.py (commits the kept workspace),
              src/crb/factory/review.py (replays the edits it recorded)
Tested by:    tests/test_factory_build.py, tests/test_factory_loop.py
Touch when:   never for a new repository; when ``GradeRow`` gains a field (``factory_row``
              maps it — keep it in step with ``grade_row_from_result`` in the core); when
              the oracle-commit convention changes (the review probes read the same branch).
Claims:       A clean factory row is the same mechanical observation as a replay row, on an
              oracle the factory manufactured — the oracle's strength is a separate
              measurement (docs/EVIDENCE-AND-CLAIMS.md#2-clean-semantic-q1-and-false-q1).
"""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.builders.base import Budget, BuildBrief, Builder, BuildOutcome, Rung
from crb.core.deps import NullDepsProvider, TaskDeps
from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack, utc_now_iso
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED, GradeContext, GradeResult, grade
from crb.core.ledger import BELT_SET_V5, PROCESS_FACTORY, GradeRow, JsonlLedger, posture_labels
from crb.core.posture import Posture, resolve_posture
from crb.core.qualify import STATE_QUALIFIED, EnvProbeWitness, Qualification
from crb.core.redact import redact_and_cap
from crb.core.run import write_pack
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec, size_tier
from crb.core.workspace import Workspace
from crb.factory.backlog import BacklogItem
from crb.factory.testfirst import (
    AuthoredTest,
    RedProof,
    assert_distinct_identity,
    worktree_at,
    write_authored,
)

EventFn = Callable[[str, Mapping[str, Any]], None]

FACTORY_BRANCH_PREFIX = "crb/factory/"
FACTORY_IDENTITY: tuple[str, ...] = (
    "-c",
    "user.name=crb factory",
    "-c",
    "user.email=factory@crb.invalid",
    "-c",
    "commit.gpgsign=false",
)

#: ``TaskSpec`` needs ≥1 source file; forward mode cannot know them before the
#: build. When the builder changed nothing this sentinel records exactly that
#: (belt 4 fails on it — the row is honest).
NO_SOURCE_CHANGE = "(no source change)"


class OracleTampered(ValueError):
    """The bytes about to be built against are not the RED-proof bytes."""


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    """Call the optional event callback (no-op when none was given)."""
    if on_event is not None:
        on_event(action, payload)


def builder_label(builder: Builder) -> str:
    """The rung label (``name:model``) compared against the oracle author's."""
    return f"{builder.name}:{builder.model}"


def oracle_branch(item_id: str) -> str:
    """The throwaway branch that carries an item's oracle commit."""
    return f"{FACTORY_BRANCH_PREFIX}{item_id}/test"


# ---------------------------------------------------------------------------
# 1. stage the oracle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleCommit:
    """The staged oracle: the synthetic task id (``sha``), its parent (HEAD at staging),
    the branch, and the test path + hash the commit was verified to carry."""

    sha: str
    parent: str
    branch: str
    test_path: str
    test_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha": self.sha,
            "parent": self.parent,
            "branch": self.branch,
            "test_path": self.test_path,
            "test_sha256": self.test_sha256,
        }


def stage_oracle_commit(
    repo: GitRepo,
    item: BacklogItem,
    authored: AuthoredTest,
    proof: RedProof,
    *,
    scratch: Path,
    base_ref: str = "",
) -> OracleCommit:
    """Commit ONLY the authored test on ``crb/factory/<item>/test``, parented at HEAD.

    Refuses (:class:`OracleTampered`) unless the authored bytes hash to the RED
    proof's ``test_sha256`` and the resulting commit touches exactly that path with
    exactly those bytes. The branch ref is forced to the new commit so a rework
    (same item, new proof) supersedes the old oracle cleanly.
    """
    if authored.path != proof.test_path or authored.sha256 != proof.test_sha256:
        raise OracleTampered(
            f"authored test {authored.path!r} ({authored.sha256[:12]}) is not the RED-proven "
            f"oracle {proof.test_path!r} ({proof.test_sha256[:12]})"
        )
    head = repo.rev_parse(base_ref or proof.base_sha)
    if head != proof.base_sha:
        raise OracleTampered(
            f"base moved: RED proof is against {proof.base_sha[:12]}, staging at {head[:12]}"
        )
    dest = Path(scratch) / f"stage-{item.id}-{head[:10]}"
    ws = worktree_at(repo, head, dest)
    try:
        write_authored(ws, authored)
        repo.run("add", "--", authored.path, cwd=ws.root, check=True)
        repo.run(
            *FACTORY_IDENTITY,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"crb factory oracle: {item.id}\n\ntest: {authored.path}\nsha256: {authored.sha256}",
            cwd=ws.root,
            check=True,
        )
        sha = repo.run(
            "rev-parse", "--verify", "HEAD^{commit}", cwd=ws.root, check=True
        ).stdout.strip()
    finally:
        ws.remove()
        shutil.rmtree(dest, ignore_errors=True)
    branch = oracle_branch(item.id)
    repo.run("branch", "-f", branch, sha, check=True)
    # Verify the commit from git's own view, not from what we think we wrote: belt 1
    # will later compare against ``git show <sha>:<path>``, so THAT must be the proof.
    changed = repo.changed_files(sha)
    if changed != [authored.path]:
        raise OracleTampered(f"oracle commit touches {changed}, expected only {authored.path!r}")
    staged = repo.show_file(sha, authored.path)
    if staged is None or hashlib.sha256(staged.encode("utf-8")).hexdigest() != proof.test_sha256:
        raise OracleTampered("staged oracle bytes do not match the RED proof hash")
    if repo.parent(sha) != head:
        raise OracleTampered("oracle commit is not parented at the proven base")
    return OracleCommit(sha, head, branch, authored.path, proof.test_sha256)


# ---------------------------------------------------------------------------
# 2 + 3. build at the parent, grade with the ordinary path
# ---------------------------------------------------------------------------


def factory_brief(
    item: BacklogItem,
    proof: RedProof,
    *,
    config: RepoConfig,
    facts: Sequence[str] = (),
    test_command: str = "",
) -> BuildBrief:
    """A sighted brief: the item's intent + structural facts + the visible oracle.
    Never a diff, never a file list."""
    lines = [item.description.strip()] if item.description.strip() else []
    if item.acceptance_criteria:
        lines += ["", "Acceptance criteria:"] + [f"  - {c}" for c in item.acceptance_criteria]
    return BuildBrief(
        subject=item.title,
        message="\n".join(lines) or item.title,
        repo=config.name,
        language=config.language.value,
        mode=MODE_SIGHTED,
        test_files=(proof.test_path,),
        target_tests=tuple(proof.target_scope),
        test_command=test_command,
        spec_facts=tuple(facts) or tuple(item.structural_facts),
        config=config,
    )


@dataclass(frozen=True)
class BuildResult:
    """One rung's build + grade. ``workspace`` is kept alive (not removed) so the
    delivery step can commit its diff; call :meth:`close` when done with it."""

    item_id: str
    rung: str
    trial: str
    oracle: OracleCommit
    task: TaskSpec
    grade: GradeResult
    pack: EvidencePack
    pack_path: Path
    row: GradeRow | None
    outcome: BuildOutcome | None
    changed_files: tuple[str, ...]
    duration_s: float
    workspace: Workspace | None = None
    error: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)
    #: The grade context the attempt was graded under (its in-run qualification and the
    #: environment-probe witness); the review's belt re-run grades under the same one.
    grade_context: GradeContext | None = None

    @property
    def clean(self) -> bool:
        """The grader's verdict (all evaluated belts held)."""
        return self.grade.clean

    @property
    def disqualified(self) -> bool:
        """The grader excluded the attempt (tampering, malformed oracle, integrity)."""
        return self.grade.disqualified

    @property
    def pack_hash(self) -> str:
        """The evidence pack's hash — the row's anchor and the review's key."""
        return self.pack.pack_hash

    @property
    def closed(self) -> bool:
        """Whether the build worktree is gone (no delivery or review can use it)."""
        return self.workspace is None or not self.workspace.root.exists()

    def close(self) -> None:
        """Remove the build worktree (idempotent)."""
        if self.workspace is not None and not self.closed:
            self.workspace.remove()

    def summary(self) -> dict[str, Any]:
        """What the factory evidence ledger and the loop's outcome record per build."""
        return {
            "item_id": self.item_id,
            "rung": self.rung,
            "trial": self.trial,
            "oracle_commit": self.oracle.sha,
            "test_sha256": self.oracle.test_sha256,
            "clean": self.clean,
            "disqualified": self.disqualified,
            "belts": self.grade.belts.to_dict(),
            "pack_hash": self.pack_hash,
            "row_id": self.row.row_id if self.row else "",
            "row_hash": self.row.row_hash if self.row else "",
            "changed_files": list(self.changed_files),
            "error": self.error or self.grade.error,
            "duration_s": round(self.duration_s, 3),
        }


def factory_row(
    task: TaskSpec,
    result: GradeResult,
    *,
    pack: EvidencePack,
    builder: BuilderRef,
    error: str,
    run_id: str,
    trial: str,
    actor: str,
    labels: Mapping[str, str],
) -> GradeRow:
    """The ledger row for a factory grade — the same fields as a replay row with
    ``process_step=factory`` and the belt-5 set; ``GradeRow`` enforces false-Q1 = 0."""
    return GradeRow(
        repo=task.repo,
        task_id=task.task_id,
        clean=result.clean,
        tests_unmodified=result.belts.tests_unmodified,
        target_green=result.belts.target_green,
        no_new_failures=result.belts.no_new_failures,
        source_changed=result.belts.source_changed,
        repo_lint_clean=result.belts.repo_lint_clean,
        capability_class=task.capability_class,
        size=task.size,
        language=task.language,
        pool=task.pool,
        mode=MODE_SIGHTED,
        process_step=PROCESS_FACTORY,
        builder=builder.name,
        model=builder.model,
        provider=builder.provider,
        run_id=run_id,
        trial=trial,
        actor=actor,
        disqualified=result.disqualified,
        dq_reason=result.dq_reason,
        error=result.error or error,
        new_failures_count=len(result.new_failures),
        attempts=builder.attempts,
        cost_usd=builder.cost_usd,
        tokens_in=builder.tokens_in,
        tokens_out=builder.tokens_out,
        latency_s=builder.latency_s,
        gold_clean=None,
        evidence_pack_hash=pack.pack_hash,
        belt_set=BELT_SET_V5,
        provenance="measured",
        labels={"rung": trial, **dict(labels), **posture_labels(result)},
    )


def build_item(
    repo: GitRepo,
    item: BacklogItem,
    authored: AuthoredTest,
    proof: RedProof,
    *,
    builder: Builder,
    budget: Budget,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    evidence_dir: Path,
    ledger: JsonlLedger | None = None,
    run_id: str = "",
    trial: str = "r1",
    actor: str = "",
    facts: Sequence[str] = (),
    timeout: int = 0,
    keep_workspace: bool = True,
    on_event: EventFn | None = None,
    posture: Posture | None = None,
    deps: TaskDeps | None = None,
) -> BuildResult:
    """Stage the oracle, build at the parent with it overlaid, grade, pack, ledger.

    Never returns a clean result it did not observe: a builder exception is
    recorded and the (unchanged) worktree is still graded — it fails belts 2/4.

    ADR-0019: the attempt is graded under an in-run qualification — the RED proof and
    the baseline measured here, in ``posture`` (resolved live when not given) — and a
    verdict that would blame the builder is witnessed by the environment probe on a
    fresh base tree (a factory item has no gold).
    """
    started = time.monotonic()
    label = builder_label(builder)
    assert_distinct_identity(authored.author, label, role="builder")
    oracle = stage_oracle_commit(repo, item, authored, proof, scratch=scratch)
    _emit(on_event, "build.oracle_staged", item=item.id, sha=oracle.sha, branch=oracle.branch)

    dest = Path(scratch) / f"build-{config.name}-{item.id}-{oracle.sha[:10]}-{trial}"
    ws = Workspace.create(repo, oracle.sha, dest, config=config)
    keep = keep_workspace
    try:
        ws.overlay_tests([oracle.test_path])
        if ws.file_hash(oracle.test_path) != proof.test_sha256:
            raise OracleTampered("overlaid oracle does not hash to the RED proof")
        scope = runner.target_scope([oracle.test_path])
        belt_scope = runner.belt_scope(scope, [oracle.test_path])
        null = NullDepsProvider()
        deps = deps or null.for_executor(executor.name)
        posture = posture or resolve_posture(
            executor, runner, deps_mode=null.mode(config, executor.name), root=ws.root
        )
        base = runner.run_for(
            executor, ws.root, belt_scope, timeout=timeout, authored=None, deps=deps.parent
        )
        base_labels: dict[str, str] = {}
        if base.timed_out:
            base_labels["baseline_timeout"] = "true"
        if base.parse_error:
            base_labels["baseline_parse_error"] = base.parse_error

        brief = factory_brief(item, proof, config=config, facts=facts)
        _emit(on_event, "build.start", item=item.id, trial=trial, rung=label, mode=MODE_SIGHTED)
        t0 = time.monotonic()
        outcome: BuildOutcome | None = None
        error = ""
        try:
            outcome = builder.build(ws, brief, budget, on_event=on_event)
        except SandboxUnavailable:
            raise  # the one exception that must stop a run: no isolation, no measurement
        except Exception as exc:  # builder infrastructure failure — recorded, graded anyway
            error = redact_and_cap(f"{type(exc).__name__}: {exc}", max_chars=500)
        bref = (
            outcome.builder_ref()
            if outcome is not None
            else BuilderRef(
                name=builder.name, model=builder.model, provider=builder.provider, mode=MODE_SIGHTED
            )
        )
        _emit(
            on_event,
            "build.done",
            item=item.id,
            trial=trial,
            rung=label,
            latency_s=round(time.monotonic() - t0, 3),
            cost_usd=bref.cost_usd,
            error=error,
        )

        touched = ws.touched_files()
        changed = tuple(f for f in touched if f != oracle.test_path and not config.is_test(f))
        stats = ws.diff_stats(exclude=[oracle.test_path])
        churn = stats.additions + stats.deletions
        task = TaskSpec(
            task_id=oracle.sha,
            repo=config.name,
            subject=item.title[:160],
            authored=utc_now_iso(),
            test_files=(oracle.test_path,),
            src_files=changed or (NO_SOURCE_CHANGE,),
            target_tests=scope,
            belt_scope=belt_scope,
            src_churn=churn,
            size=size_tier(churn),
            capability_class=item.capability_class,
            language=config.language.value,
            baseline_failing=tuple(sorted(base.failing)),
            red_checked=True,
            gold_clean=None,
            labels={
                "item_id": item.id,
                "process": PROCESS_FACTORY,
                "red_proof": proof.test_sha256,
                "size_estimate": item.size_estimate,
                "kind": item.kind,
                "level": item.level,
                **base_labels,
            },
        )
        # the in-run qualification: the RED proof and the baseline just measured, in
        # this posture — a factory item has no gold, so there is no gold fact to record
        qualification = Qualification(
            qualification_id="",
            repo=config.name,
            task_id=oracle.sha,
            posture_id=posture.posture_id,
            posture=posture.to_dict(),
            state=STATE_QUALIFIED,
            deps=deps.to_dict(),
            red={"kind": "red_proof", "test_sha256": proof.test_sha256, "failing": []},
            baseline_failing=tuple(sorted(base.failing)),
            gold={"clean": None, "note": "a factory item has no gold", "lint": None},
            run_id=run_id,
        )
        task = qualification.project(task).with_(gold_clean=None)

        def fresh_base() -> Workspace:
            dest_probe = (
                Path(scratch)
                / f"envprobe-{config.name}-{item.id}-{oracle.sha[:10]}-{uuid.uuid4().hex[:6]}"
            )
            return Workspace.create(repo, oracle.sha, dest_probe, config=config)

        gctx = GradeContext(
            posture=posture,
            qualification=qualification,
            deps=deps,
            witness=EnvProbeWitness(
                fresh_base,
                runner=runner,
                executor=executor,
                binding=deps.parent,
                test_files=(oracle.test_path,),
                timeout=timeout,
            ),
        )
        result = grade(
            ws,
            task,
            ctx=gctx,
            config=config,
            runner=runner,
            executor=executor,
            mode=MODE_SIGHTED,
            timeout=timeout,
            on_event=on_event,
        )
        apparatus = ApparatusStamp(
            runner=runner.name,
            executor=executor.describe(),
            extra={"process_step": PROCESS_FACTORY, "oracle_branch": oracle.branch},
            posture=posture.to_dict(),
        )
        pack = EvidencePack(
            task=task,
            grade=result,
            apparatus=apparatus,
            builder=bref,
            run_id=run_id,
            trial=trial,
            actor=actor,
            notes={
                "item_id": item.id,
                "rung": label,
                "oracle_commit": oracle.sha,
                "red_proof": proof.to_dict(),
                "test_author": authored.author,
                "builder_error": error,
            },
        )
        pack_path = write_pack(pack, evidence_dir)
        row_labels = {"item_id": item.id, "test_author": authored.author, **base_labels}
        row = (
            ledger.append(
                factory_row(
                    task,
                    result,
                    pack=pack,
                    builder=bref,
                    error=error,
                    run_id=run_id,
                    trial=trial,
                    actor=actor,
                    labels=row_labels,
                )
            )
            if ledger is not None
            else None
        )
        _emit(
            on_event,
            "ledger.append",
            item=item.id,
            trial=trial,
            clean=result.clean,
            disqualified=result.disqualified,
            pack=pack.pack_hash,
            row_hash=row.row_hash if row else "",
        )
        return BuildResult(
            item_id=item.id,
            rung=label,
            trial=trial,
            oracle=oracle,
            task=task,
            grade=result,
            pack=pack,
            pack_path=pack_path,
            row=row,
            outcome=outcome,
            changed_files=changed,
            duration_s=time.monotonic() - started,
            workspace=ws if keep else None,
            error=error,
            labels=row_labels,
            grade_context=gctx,
        )
    except BaseException:
        keep = False
        raise
    finally:
        if not keep:
            ws.remove()


def build_ladder(
    repo: GitRepo,
    item: BacklogItem,
    authored: AuthoredTest,
    proof: RedProof,
    *,
    rungs: Sequence[Rung],
    builder_for: Callable[[Rung], Builder],
    budget: Budget,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    evidence_dir: Path,
    ledger: JsonlLedger | None = None,
    run_id: str = "",
    actor: str = "",
    facts: Sequence[str] = (),
    timeout: int = 0,
    trial_prefix: str = "r",
    on_event: EventFn | None = None,
    posture: Posture | None = None,
    deps: TaskDeps | None = None,
) -> list[BuildResult]:
    """Climb the escalation ladder: one graded, ledgered attempt per rung until a
    rung is clean or an attempt is disqualified. Every rung's label is checked
    against the oracle's author identity before it runs. Workspaces of
    non-final attempts are removed; the final attempt's is kept for delivery."""
    if not rungs:
        raise ValueError("ladder must have at least one rung")
    for r in rungs:
        assert_distinct_identity(authored.author, r.label, role="builder")
    results: list[BuildResult] = []
    for i, rung in enumerate(rungs, start=1):
        if results:
            results[-1].close()
        res = build_item(
            repo,
            item,
            authored,
            proof,
            builder=builder_for(rung),
            budget=budget,
            config=config,
            runner=runner,
            executor=executor,
            scratch=scratch,
            evidence_dir=evidence_dir,
            ledger=ledger,
            run_id=run_id,
            trial=f"{trial_prefix}{i}",
            actor=actor,
            facts=facts,
            timeout=timeout,
            on_event=on_event,
            posture=posture,
            deps=deps,
        )
        results.append(res)
        if res.clean or res.disqualified:
            break
    return results


__all__ = [
    "FACTORY_BRANCH_PREFIX",
    "FACTORY_IDENTITY",
    "NO_SOURCE_CHANGE",
    "BuildResult",
    "OracleCommit",
    "OracleTampered",
    "build_item",
    "build_ladder",
    "builder_label",
    "factory_brief",
    "factory_row",
    "oracle_branch",
    "stage_oracle_commit",
    "worktree_at",
]
