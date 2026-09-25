"""The replay run: prep → build → grade → evidence → ledger, task by task.

The orchestrator is in ``core`` so it stays stdlib-only; the builder is injected
as a plain callable (:data:`BuildFn`) so ``crb.builders`` can adapt any adapter
to it without the core knowing about model SDKs.

Every *attempt* is one ledger row (``trial`` = ``r1``, ``r2`` …), so both
first-pass accuracy (``r1`` rows only) and the solve rate under the attempt
budget (any clean row per task) are derivable from the ledger — the two numbers
the essay insists must never be conflated.

The escalation ladder is a tuple of *rung labels*; the build callable maps a
label to a (builder, model) pair. A task climbs the ladder only while its grade
is not clean and not disqualified; a disqualified attempt (tamper, malformed
oracle) stops the task — the observation is excluded, not retried.

The worktree the builder edited is graded exactly as ``crb grade`` grades one:
:func:`~crb.core.grade.grade` runs :meth:`~crb.core.workspace.Workspace.enforce_integrity`
first (``HEAD`` still the parent, no index bits, the shared ``info/exclude``
restored) and enumerates the builder's changes from the tree, not from git's
views. The independent review pass (2026-09-14, finding 1(b)) found this path
graded a worktree whose builder had committed the poison ``clean`` while the CLI
refused it on its own HEAD check; both paths now share the one check inside
``grade()`` (``tests/test_run.py`` pins it here).

Navigation
----------
What it is:   The replay orchestrator — ``run`` / ``run_task`` drive one task through prep,
              build, grade, evidence pack and ledger row, with the builder injected as a
              callable.
What it does: Creates a fresh worktree per attempt, overlays the tests in sighted mode only,
              calls the builder, grades the tree under the belts, writes the evidence pack
              before the row (no pack ⇒ no Q1), appends one ledger row per attempt, climbs
              the escalation ladder only while the grade is neither clean nor disqualified,
              and skips tasks whose gold is known-bad. A builder crash is recorded and graded
              anyway; only a sandbox failure or cancellation stops the run.
How:          ``run`` iterates tasks (checking ``stop`` and ``gold_clean``) → ``run_task``
              loops the ladder: ``Workspace.create`` → ``build_fn`` → ``grade`` →
              ``EvidencePack`` → ``write_pack`` → ``ledger.append(row_from(...))`` →
              ``Workspace.remove`` → ``RunSummary`` with first-pass and any-attempt counts
              kept separate.
Layer:        core — docs/ARCHITECTURE.md#51-a-replay-run-sighted
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0006-zero-raw-retention-and-evidence-packs.md,
              docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/grade.py (the belts), src/crb/core/ledger.py (the row and the
              chain), src/crb/core/evidence.py (the pack and the apparatus stamp),
              src/crb/core/workspace.py (one worktree per attempt), src/crb/builders/adapter.py
              (turns a Builder into a BuildFn), src/crb/server/worker.py (the server's caller
              — a replay run's ``counts_json`` is the RunSummary), src/crb/cli/commands/grade.py
              (``crb grade``: the same ``grade()`` over a worktree the operator supplies)
Tested by:    tests/test_run.py, tests/test_builders_adapter.py, tests/test_worker.py,
              tests/test_worker_budget_ladder.py
Touch when:   never for a new repository (mode, ladder and budget are run settings); adding a
              stage between build and ledger, or a field to the pack or the row, changes the
              evidence every consumer reads — update src/crb/core/evidence.py, the store
              (src/crb/store/ledger.py) and docs/API.md together.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.grade import MODE_BLIND, MODE_SIGHTED, MODES, GradeResult, grade
from crb.core.ledger import PROCESS_REPLAY, GradeRow, JsonlLedger, grade_row_from_result
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace

EventFn = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True)
class BuildAttempt:
    """What the builder reports back. ``builder`` carries cost/tokens/turns; ``error``
    is an infrastructure failure (the grader still runs — an empty worktree simply
    fails belt 2/4 — but the error is recorded on the row)."""

    builder: BuilderRef
    error: str = ""
    transcript_ref: str = ""
    #: attempt-level facts for the row's ``labels`` (a pre-flight record); never a verdict
    labels: Mapping[str, str] = field(default_factory=dict)
    #: attempt-level provenance merged into the pack's ``notes`` (an unconfirmed container
    #: kill: ``{kill_confirmed: False, container}``); never a verdict
    notes: Mapping[str, Any] = field(default_factory=dict)


#: ``build_fn(workspace, task, mode, rung) -> BuildAttempt``. The whole contract between
#: the core and a builder: it edits ``workspace.root`` and reports what it spent. It is
#: never given the belt scope, the baseline or the grader (ADR-0004).
BuildFn = Callable[[Workspace, TaskSpec, str, str], BuildAttempt]


@dataclass(frozen=True)
class RunSpec:
    """Everything one run holds constant across its tasks: the repository, the
    instruments (runner, executor), where evidence and rows go, the mode, the
    escalation ladder and the apparatus provenance (``corpus_sha``,
    ``policy_version``) stamped into every pack."""

    run_id: str
    config: RepoConfig
    runner: BaseRunner
    executor: Executor
    scratch: Path
    ledger: JsonlLedger
    evidence_dir: Path
    mode: str = MODE_SIGHTED
    ladder: tuple[str, ...] = ("r1",)
    actor: str = ""
    timeout: int = 0
    process_step: str = PROCESS_REPLAY
    corpus_sha: str = ""
    policy_version: str = ""
    keep_worktrees: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)
    #: belt 6 ``api_stable`` (ADR-0021): OFF unless the run or the repository's
    #: ``checks.api_stable`` switches it on (the worker resolves it)
    evaluate_api: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not self.ladder:
            raise ValueError("ladder must have at least one rung")
        object.__setattr__(self, "extra", dict(self.extra))

    def apparatus(self) -> ApparatusStamp:
        """The stamp every pack of this run carries: which instrument produced it."""
        return ApparatusStamp(
            runner=self.runner.name,
            executor=self.executor.describe(),
            corpus_sha=self.corpus_sha,
            policy_version=self.policy_version,
            extra=dict(self.extra),
        )


@dataclass(frozen=True)
class TaskOutcome:
    """One task's result over the ladder: its rows (one per attempt), the pack hashes,
    and whether the LAST attempt was clean or disqualified."""

    task_id: str
    attempts: int
    clean: bool
    disqualified: bool
    rows: tuple[GradeRow, ...]
    packs: tuple[str, ...]  # evidence pack hashes
    duration_s: float


@dataclass(frozen=True)
class RunSummary:
    """The run's counts. ``clean`` is tasks with a clean row at ANY rung (solve rate
    under the attempt budget); ``first_pass_clean`` is tasks whose ``r1`` row was
    clean — reported side by side, never blended. ``stopped_reason`` is non-empty
    when the run ended before its tasks did."""

    run_id: str
    tasks: int
    clean: int
    disqualified: int
    errors: int
    first_pass_clean: int
    rows: int
    duration_s: float
    stopped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tasks": self.tasks,
            "clean": self.clean,
            "disqualified": self.disqualified,
            "errors": self.errors,
            "first_pass_clean": self.first_pass_clean,
            "rows": self.rows,
            "duration_s": round(self.duration_s, 3),
            "stopped_reason": self.stopped_reason,
        }


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def write_pack(pack: EvidencePack, evidence_dir: Path) -> Path:
    """Store the pack content-addressed (``<pack_hash>.json``). Written to a temp file
    and renamed so a crash mid-write cannot leave a half pack under the hash the
    ledger row will cite; an existing pack with that hash is by definition identical."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    p = evidence_dir / f"{pack.pack_hash}.json"
    if not p.exists():
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(pack.to_json(), encoding="utf-8")
        tmp.replace(p)
    return p


def row_from(
    spec: RunSpec,
    task: TaskSpec,
    result: GradeResult,
    *,
    pack: EvidencePack,
    attempt: BuildAttempt,
    trial: str,
) -> GradeRow:
    """The one mapping from a graded attempt to its ledger row (delegates to
    :func:`~crb.core.ledger.grade_row_from_result` so the CLI, worker and this
    orchestrator cannot drift)."""
    return grade_row_from_result(
        result,
        task,
        pack_hash=pack.pack_hash,
        builder=attempt.builder,
        run_id=spec.run_id,
        trial=trial,
        actor=spec.actor,
        process_step=spec.process_step,
        language=task.language or spec.config.language.value,
        builder_error=attempt.error,
        labels=dict(attempt.labels),
    )


def run_task(
    spec: RunSpec,
    repo: GitRepo,
    task: TaskSpec,
    build_fn: BuildFn,
    *,
    on_event: EventFn | None = None,
) -> TaskOutcome:
    """Climb the ladder for one task: a fresh worktree, a build, a grade, a pack and
    a row per rung, stopping at the first clean or disqualified attempt. Raises only
    :class:`SandboxUnavailable` (the run cannot continue); every other failure is a
    recorded row."""
    started = time.monotonic()
    rows: list[GradeRow] = []
    packs: list[str] = []
    clean = disqualified = False
    for i, rung in enumerate(spec.ladder, start=1):
        trial = f"r{i}"
        dest = spec.scratch / f"run-{spec.config.name}-{task.short_id}-{spec.run_id[:8]}-{trial}"
        _emit(on_event, "prep.start", task=task.task_id, trial=trial, rung=rung)
        ws = Workspace.create(repo, task.task_id, dest, config=spec.config)
        try:
            # blind: the held-out tests reach the worktree only inside grade()
            if spec.mode == MODE_SIGHTED:
                ws.overlay_tests(task.test_files)
            _emit(
                on_event, "build.start", task=task.task_id, trial=trial, rung=rung, mode=spec.mode
            )
            t0 = time.monotonic()
            try:
                attempt = build_fn(ws, task, spec.mode, rung)
            except SandboxUnavailable:
                raise
            except Exception as exc:  # builder infrastructure failure — recorded, graded anyway
                attempt = BuildAttempt(
                    BuilderRef(name=rung, mode=spec.mode),
                    error=f"{type(exc).__name__}: {exc}"[:500],
                )
            _emit(
                on_event,
                "build.done",
                task=task.task_id,
                trial=trial,
                rung=rung,
                builder=attempt.builder.name,
                model=attempt.builder.model,
                turns=attempt.builder.turns,
                tokens_in=attempt.builder.tokens_in,
                tokens_out=attempt.builder.tokens_out,
                cost_usd=attempt.builder.cost_usd,
                latency_s=round(time.monotonic() - t0, 3),
                error=attempt.error,
            )
            result = grade(
                ws,
                task,
                config=spec.config,
                runner=spec.runner,
                executor=spec.executor,
                mode=spec.mode if spec.mode == MODE_BLIND else MODE_SIGHTED,
                timeout=spec.timeout,
                on_event=on_event,
                evaluate_api=spec.evaluate_api,
            )
            pack = EvidencePack(
                task=task,
                grade=result,
                apparatus=spec.apparatus(),
                builder=attempt.builder,
                run_id=spec.run_id,
                trial=trial,
                actor=spec.actor,
                notes={
                    "rung": rung,
                    **(
                        {"transcript_ref": attempt.transcript_ref} if attempt.transcript_ref else {}
                    ),
                    **dict(attempt.notes),
                },
            )
            # pack first, row second: a row exists only for a pack that is on disk
            write_pack(pack, spec.evidence_dir)
            row = spec.ledger.append(
                row_from(spec, task, result, pack=pack, attempt=attempt, trial=trial)
            )
            rows.append(row)
            packs.append(pack.pack_hash)
            _emit(
                on_event,
                "ledger.append",
                task=task.task_id,
                trial=trial,
                clean=row.clean,
                disqualified=row.disqualified,
                pack=pack.pack_hash,
                row_hash=row.row_hash,
            )
            clean, disqualified = result.clean, result.disqualified
        finally:
            if not spec.keep_worktrees:
                ws.remove()
        # a disqualified attempt is excluded, not retried: climbing would let a
        # tampering builder buy itself another observation
        if clean or disqualified:
            break
    return TaskOutcome(
        task.task_id,
        len(rows),
        clean,
        disqualified,
        tuple(rows),
        tuple(packs),
        time.monotonic() - started,
    )


def run(
    spec: RunSpec,
    repo: GitRepo,
    tasks: Iterable[TaskSpec],
    build_fn: BuildFn,
    *,
    on_event: EventFn | None = None,
    stop: Callable[[], bool] | None = None,
) -> RunSummary:
    """Run every task; stop early (recorded) on cancellation or a sandbox failure."""
    started = time.monotonic()
    n = clean = dq = err = first = rows = 0
    stopped = ""
    _emit(
        on_event,
        "run.start",
        run_id=spec.run_id,
        repo=spec.config.name,
        mode=spec.mode,
        ladder=list(spec.ladder),
    )
    for task in tasks:
        if stop is not None and stop():
            stopped = "cancelled"
            break
        # None (never gold-checked) is allowed through; only a MEASURED bad gold skips
        if task.gold_clean is False:
            _emit(
                on_event,
                "run.skip",
                task=task.task_id,
                reason="gold not clean — oracle cannot judge",
            )
            continue
        try:
            outcome = run_task(spec, repo, task, build_fn, on_event=on_event)
        except SandboxUnavailable as exc:
            stopped = f"sandbox unavailable: {exc}"
            _emit(on_event, "run.error", error=stopped)
            break
        n += 1
        rows += outcome.attempts
        clean += int(outcome.clean)
        dq += int(outcome.disqualified)
        err += sum(1 for r in outcome.rows if r.error)
        first += int(bool(outcome.rows) and outcome.rows[0].clean)
    summary = RunSummary(
        spec.run_id, n, clean, dq, err, first, rows, time.monotonic() - started, stopped
    )
    _emit(on_event, "run.done", **summary.to_dict())
    return summary


def load_tasks(path: Path) -> list[TaskSpec]:
    """Read a ``tasks/<repo>.jsonl`` file (one TaskSpec per line)."""
    out: list[TaskSpec] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(TaskSpec.from_dict(json.loads(line)))
    return out
