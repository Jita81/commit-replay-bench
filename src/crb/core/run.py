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
from crb.core.ledger import BELT_SET_V4, PROCESS_REPLAY, GradeRow, JsonlLedger
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


#: ``build_fn(workspace, task, mode, rung) -> BuildAttempt``
BuildFn = Callable[[Workspace, TaskSpec, str, str], BuildAttempt]


@dataclass(frozen=True)
class RunSpec:
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

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not self.ladder:
            raise ValueError("ladder must have at least one rung")
        object.__setattr__(self, "extra", dict(self.extra))

    def apparatus(self) -> ApparatusStamp:
        return ApparatusStamp(
            runner=self.runner.name,
            executor=self.executor.describe(),
            corpus_sha=self.corpus_sha,
            policy_version=self.policy_version,
            extra=dict(self.extra),
        )


@dataclass(frozen=True)
class TaskOutcome:
    task_id: str
    attempts: int
    clean: bool
    disqualified: bool
    rows: tuple[GradeRow, ...]
    packs: tuple[str, ...]  # evidence pack hashes
    duration_s: float


@dataclass(frozen=True)
class RunSummary:
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
    b = attempt.builder
    return GradeRow(
        repo=task.repo,
        task_id=task.task_id,
        clean=result.clean,
        tests_unmodified=result.belts.tests_unmodified,
        target_green=result.belts.target_green,
        no_new_failures=result.belts.no_new_failures,
        source_changed=result.belts.source_changed,
        capability_class=task.capability_class,
        size=task.size,
        language=task.language or spec.config.language.value,
        pool=task.pool,
        mode=spec.mode,
        process_step=spec.process_step,
        builder=b.name,
        model=b.model,
        provider=b.provider,
        run_id=spec.run_id,
        trial=trial,
        actor=spec.actor,
        disqualified=result.disqualified,
        dq_reason=result.dq_reason,
        error=result.error or attempt.error,
        new_failures_count=len(result.new_failures),
        attempts=b.attempts,
        cost_usd=b.cost_usd,
        tokens_in=b.tokens_in,
        tokens_out=b.tokens_out,
        latency_s=b.latency_s,
        gold_clean=task.gold_clean,
        evidence_pack_hash=pack.pack_hash,
        belt_set=BELT_SET_V4,
        provenance="measured",
        labels={"rung": trial, **{k: str(v) for k, v in task.labels.items()}},
    )


def run_task(
    spec: RunSpec,
    repo: GitRepo,
    task: TaskSpec,
    build_fn: BuildFn,
    *,
    on_event: EventFn | None = None,
) -> TaskOutcome:
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
            )
            pack = EvidencePack(
                task=task,
                grade=result,
                apparatus=spec.apparatus(),
                builder=attempt.builder,
                run_id=spec.run_id,
                trial=trial,
                actor=spec.actor,
                notes={"rung": rung, "transcript_ref": attempt.transcript_ref}
                if attempt.transcript_ref
                else {"rung": rung},
            )
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
