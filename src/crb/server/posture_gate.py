"""The worker's posture gate: nothing is built for a task not qualified where it is graded.

ADR-0019 §3. Before a replay spends anything the worker resolves the posture it will
grade in (live: the image by content id, the toolchain probed inside it, the tree, the
dependency mode), admits only the tasks qualified in THAT posture — qualifying the others
first when ``qualify_first`` is on, for no model money — and hands the core one grade
context per task: its qualification there, its dependency bindings and the gold witness
that makes any blame true.

This module is what the worker calls; it keeps the worker's own changes to a few lines.

Navigation
----------
What it is:   The posture gate a build run passes through: ``PostureGate`` (admit, context,
              refusal counts) and the posture resolution it starts from.
What it does: Resolves the live posture; qualifies each task in it (``qualify_task``, no
              builder); keeps only qualified tasks and counts the rest by refusal code with
              the fix; gives ``RunSpec.context_for`` a context per admitted task with a
              ``GoldWitness`` bound to the task's gold dependency set.
How:          ``resolve_run_posture`` → ``PostureGate.admit`` (qualify, count) →
              ``PostureGate.context_for`` (``crb.core.qualify.context_for`` + witness).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/qualify.py (``qualify_task``, ``context_for``, ``GoldWitness``),
              src/crb/core/posture.py (``resolve_posture``), src/crb/core/deps.py (the
              provider the bindings come from), src/crb/server/worker.py (the caller:
              replay, blind, oracle, controls), src/crb/core/run.py (``RunSpec.context_for``
              consumes the contexts)
Tested by:    tests/test_worker.py, tests/test_run.py
Touch when:   a run kind starts grading (give it the gate); a posture-level stop is added
              (its code in ``crb.core.qualify`` and ADR-0019's table first).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from crb.core.deps import DepsProvider, TaskDeps
from crb.core.execution import Executor
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED, GradeContext, grade
from crb.core.ledger import GradeRow, is_environment_error
from crb.core.posture import Posture, PostureMismatch, resolve_posture
from crb.core.qualify import (
    POSTURE_CANARY_FAILED,
    POSTURE_DRIFT,
    POSTURE_UNQUALIFIED,
    QUAL_ENV_WITNESS_RED,
    GoldWitness,
    Qualification,
    code_view,
    context_for,
    qualify_task,
)
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from crb.store import qualifications as store_q

#: Two environment rows in a row stop a build run (``params.env_stop``; 0 disables).
DEFAULT_ENV_STOP = 2


@dataclass(frozen=True)
class GateDecision:
    """What the gate decided before any builder call: the admitted tasks, or the stop
    (``code`` + ``reason``, a run-scope code) that ends the run at $0."""

    tasks: tuple[TaskSpec, ...]
    code: str = ""
    reason: str = ""

    @property
    def stopped(self) -> bool:
        return bool(self.code)


EventFn = Callable[[str, Mapping[str, Any]], None]


def resolve_run_posture(
    executor: Executor,
    runner: BaseRunner,
    config: RepoConfig,
    provider: DepsProvider,
    *,
    root: Path,
) -> Posture:
    """The posture this run grades in, measured live (never read from a record)."""
    return resolve_posture(
        executor, runner, deps_mode=provider.mode(config, executor.name), root=root
    )


class PostureGate:
    """Admits tasks qualified in ``posture`` and builds their grade contexts."""

    def __init__(
        self,
        *,
        repo: GitRepo,
        config: RepoConfig,
        runner: BaseRunner,
        executor: Executor,
        scratch: Path,
        provider: DepsProvider,
        posture: Posture,
        timeout: int = 0,
        run_id: str = "",
        on_event: EventFn | None = None,
        session_factory: sessionmaker[Session] | None = None,
        actor: str = "",
    ) -> None:
        #: The store the records are read from and appended to (``None``: in-run only).
        self.session_factory = session_factory
        self.actor = actor
        self.repo, self.config = repo, config
        self.runner, self.executor = runner, executor
        self.scratch, self.provider, self.posture = Path(scratch), provider, posture
        self.timeout, self.run_id, self.on_event = timeout, run_id, on_event
        #: task id → the qualification in force for this posture (qualified or not)
        self.qualifications: dict[str, Qualification] = {}
        self._deps: dict[str, TaskDeps] = {}
        #: refusal code → how many tasks it kept out of the run
        self.refusals: Counter[str] = Counter()

    # --- admission -----------------------------------------------------------------
    def qualify(self, task: TaskSpec) -> Qualification:
        """Measure ``task`` in this posture (no builder, no model) and keep the record."""
        q = qualify_task(
            self.repo,
            self.config,
            task,
            posture=self.posture,
            deps=self.provider,
            runner=self.runner,
            executor=self.executor,
            scratch=self.scratch,
            timeout=self.timeout,
            run_id=self.run_id,
            on_event=self.on_event,
        )
        if self.session_factory is not None:
            with self.session_factory() as s:
                store_q.append(s, q)
        self.qualifications[task.task_id] = q
        return q

    def known(self, task_ids: Sequence[str] | None = None) -> dict[str, Qualification]:
        """Each task's record in force in THIS posture, from the store."""
        if self.session_factory is None:
            return {}
        with self.session_factory() as s:
            return store_q.latest_by_task(
                s, self.config.name, self.posture.posture_id, list(task_ids or []) or None
            )

    def drifted_from(self) -> list[str]:
        """The postures this repository was qualified in for the same executor and image
        name when THIS posture has no record at all — the image's bytes, the toolchain,
        a limit or the runner's environment moved since (``POSTURE_DRIFT``)."""
        if self.session_factory is None:
            return []
        with self.session_factory() as s:
            here = store_q.counts_by_code(s, self.config.name, self.posture.posture_id)
            if here:
                return []
            last = store_q.latest_posture_for(
                s,
                self.config.name,
                executor=self.posture.executor,
                image_ref=self.posture.image_ref,
            )
        return [last] if last and last != self.posture.posture_id else []

    def admit(
        self,
        tasks: Iterable[TaskSpec],
        *,
        known: Mapping[str, Qualification] | None = None,
        qualify_first: bool = True,
        stop: Callable[[], bool] | None = None,
    ) -> list[TaskSpec]:
        """The tasks qualified in this posture, in order. ``known`` is each task's latest
        record for THIS posture (the store's); a task with none is qualified first when
        ``qualify_first`` is on, else refused ``POSTURE_UNQUALIFIED``."""
        admitted: list[TaskSpec] = []
        for task in tasks:
            if stop is not None and stop():
                break
            q = (known or {}).get(task.task_id)
            if q is not None and q.state == "revoked" and qualify_first:
                q = None  # revoked when the posture moved under it: measure it again
            if q is not None:
                self.qualifications[task.task_id] = q
            elif qualify_first:
                q = self.qualify(task)
            if q is None or not q.is_qualified:
                code = q.code if q is not None else POSTURE_UNQUALIFIED
                self.refusals[code or POSTURE_UNQUALIFIED] += 1
                continue
            admitted.append(task)
        return admitted

    def prepare(
        self,
        tasks: Iterable[TaskSpec],
        *,
        qualify_first: bool = True,
        canary: bool = True,
        stop: Callable[[], bool] | None = None,
    ) -> GateDecision:
        """Everything before the first builder call (ADR-0019 §3), for no model money:
        drift, admission (qualifying first when asked), and the canary. A stop is a
        :class:`GateDecision` with its code and what to do."""
        candidates = list(tasks)
        if not candidates:
            return GateDecision(())  # nothing selected: nothing to qualify, nothing to spend
        if not qualify_first:
            drift = self.drifted_from()
            if drift:
                return GateDecision(
                    (),
                    POSTURE_DRIFT,
                    f"{POSTURE_DRIFT}: this repository was qualified in {drift[0]}, and the "
                    f"posture is now {self.posture.posture_id} ({self.posture.posture_class}) "
                    f"— {code_view(POSTURE_DRIFT)['fix']}",
                )
        admitted = self.admit(
            candidates,
            known=self.known([t.task_id for t in candidates]),
            qualify_first=qualify_first,
            stop=stop,
        )
        if not admitted:
            by_code = ", ".join(f"{c} x {n}" for c, n in self.refusals.most_common()) or "none"
            return GateDecision(
                (),
                POSTURE_UNQUALIFIED,
                f"{POSTURE_UNQUALIFIED}: 0 of {len(candidates)} task(s) qualified in posture "
                f"{self.posture.posture_id} ({self.posture.posture_class}); refusals: {by_code} "
                f"— {code_view(POSTURE_UNQUALIFIED)['fix']}",
            )
        if canary:
            reason = self.canary(admitted[0])
            if reason:
                return GateDecision(tuple(admitted), POSTURE_CANARY_FAILED, reason)
        return GateDecision(tuple(admitted))

    def canary(self, task: TaskSpec) -> str:
        """Grade ``task``'s OWN gold through the real path (context, dependencies, belts),
        writing no row. ``""`` when it is clean; else the ``POSTURE_CANARY_FAILED`` reason
        with the tail to read. Emits ``run.canary``."""
        ctx = self.context_for(task)
        spec = ctx.spec(task)
        dest = self.scratch / f"canary-{self.config.name}-{task.short_id}-{uuid.uuid4().hex[:6]}"
        with Workspace.create(self.repo, task.task_id, dest, config=self.config) as ws:
            ws.overlay_tests(task.test_files)
            ws.overlay_sources(task.src_files)
            result = grade(
                ws,
                spec,
                ctx=ctx,
                config=self.config,
                runner=self.runner,
                executor=self.executor,
                mode=MODE_SIGHTED,
                timeout=self.timeout,
            )
        why = result.error or result.note or result.dq_reason
        if self.on_event is not None:
            self.on_event(
                "run.canary",
                {
                    "task": task.task_id,
                    "clean": result.clean,
                    "posture_id": self.posture.posture_id,
                    "why": redact_and_cap(why, max_chars=300),
                },
            )
        if result.clean:
            return ""
        tail = result.target_run.tail if result.target_run is not None else ""
        return redact_and_cap(
            f"{POSTURE_CANARY_FAILED}: the gold of {task.short_id} did not grade clean in "
            f"{self.posture.posture_id}: {why} — {code_view(POSTURE_CANARY_FAILED)['fix']}"
            + (f"\n{tail}" if tail else ""),
            max_chars=1000,
        )

    def on_environment(self, task: TaskSpec, row: GradeRow) -> None:
        """``RunSpec.on_environment``: the trial's gold control was red in this posture —
        the posture moved under the qualification, so it is revoked (a new record, never an
        edit) and the task is not built again in this run."""
        q = self.qualifications.get(task.task_id)
        if q is None or not q.is_qualified:
            return
        reason = redact_and_cap(row.error, max_chars=300)
        if self.session_factory is not None:
            with self.session_factory() as s:
                revoked = store_q.revoke(
                    s, q, QUAL_ENV_WITNESS_RED, self.actor or "worker", reason, run_id=self.run_id
                )
        else:
            revoked = Qualification.from_dict(
                {
                    **q.to_dict(),
                    "qualification_id": "",
                    "state": "revoked",
                    "code": QUAL_ENV_WITNESS_RED,
                    "message": reason,
                    "fingerprint": "",
                }
            )
        self.qualifications[task.task_id] = revoked

    @staticmethod
    def environment_streak(rows: Sequence[GradeRow]) -> int:
        """How many of the LAST rows in a row are environment rows (``error:
        environment: …``) — what ``env_stop`` compares against."""
        n = 0
        for row in reversed(rows):
            if not is_environment_error(row.error):
                break
            n += 1
        return n

    def refusals_view(self) -> list[dict[str, Any]]:
        """``[{code, n, fix, doc}]`` — why tasks were kept out, most common first."""
        return [{**code_view(code), "n": n} for code, n in self.refusals.most_common()]

    # --- contexts ------------------------------------------------------------------
    def deps_for(self, task: TaskSpec) -> TaskDeps:
        """The task's bindings (resolved once per run from git objects, never a worktree)."""
        deps = self._deps.get(task.task_id)
        if deps is None:
            deps = self.provider.resolve(
                self.repo,
                self.config,
                parent=self.repo.parent(task.task_id),
                gold=task.task_id,
                executor_name=self.executor.name,
                on_event=self.on_event,
            )
            self._deps[task.task_id] = deps
        return deps

    def context_for(self, task: TaskSpec) -> GradeContext:
        """``RunSpec.context_for``: the task's context in this posture, with the gold
        witness. Raises :class:`PostureMismatch` for a task not qualified here."""
        q = self.qualifications.get(task.task_id)
        if q is None:
            raise PostureMismatch(
                f"{task.task_id[:10]} has no qualification in {self.posture.posture_id} — "
                f"{code_view(POSTURE_UNQUALIFIED)['fix']}"
            )
        deps = self.deps_for(task)
        self.provider.verify(deps)
        witness = GoldWitness(
            self.repo,
            self.config,
            task,
            runner=self.runner,
            executor=self.executor,
            scratch=self.scratch,
            binding=deps.gold,
            timeout=self.timeout,
        )
        return context_for(task, posture=self.posture, qualification=q, deps=deps, witness=witness)


__all__ = ["DEFAULT_ENV_STOP", "GateDecision", "PostureGate", "resolve_run_posture"]
