"""Test helpers for ADR-0019: grade contexts without measuring a posture every time.

Navigation
----------
What it is:   The test-only ways to hand ``grade()`` and ``RunSpec`` the posture context
              ADR-0019 makes required.
What it does: ``adhoc`` — an unwitnessed context from the task's discovery values (what the
              negative controls and ``crb grade --adhoc`` use); ``witnessed_context_for`` —
              a ``RunSpec.context_for`` whose qualification is the task's discovery values
              and whose witness is a real ``GoldWitness`` on the fixture repository, so a
              blamed row names a control that actually ran. Neither is a qualification a
              deployment would accept: that is measured by ``qualify_task``.
How:          Thin wrappers over ``crb.core.qualify``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/qualify.py (``adhoc_context``, ``GoldWitness``, ``Qualification``),
              src/crb/core/grade.py (``GradeContext``), src/crb/core/run.py
              (``RunSpec.context_for``), tests/test_run.py (the main caller)
Tested by:    tests/test_run.py, tests/test_grade.py
Touch when:   the grade context changes shape.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crb.core.deps import HOST_ENV_DEPS, NO_DEPS, TaskDeps
from crb.core.execution import Executor
from crb.core.git import GitRepo
from crb.core.grade import GradeContext, GradeResult, Witness, grade
from crb.core.ledger import GradeRow
from crb.core.posture import Posture
from crb.core.qualify import (
    STATE_QUALIFIED,
    GoldWitness,
    Qualification,
    adhoc_context,
    adhoc_posture,
)
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace


def adhoc(task: TaskSpec, executor: Executor) -> tuple[TaskSpec, GradeContext]:
    """An unwitnessed context from the discovery values (blame reads ``unwitnessed``)."""
    return adhoc_context(task, executor=executor)


def discovery_qualification(
    task: TaskSpec, executor: Executor, *, gold_lint: bool | None = None
) -> Qualification:
    """A ``qualified`` record built from the task's discovery values in an ad hoc posture
    (tests only — a deployment measures it with ``qualify_task``). ``gold_lint`` is the
    gold's belt 5 at qualification: ``None`` (the default) = never measured, so a lint
    rejection has no witness; ``True`` = the gold passed it."""
    posture = adhoc_posture(executor)
    return Qualification(
        qualification_id="",
        repo=task.repo,
        task_id=task.task_id,
        posture_id=posture.posture_id,
        posture=posture.to_dict(),
        state=STATE_QUALIFIED,
        red={"kind": "tests_failed", "failing": []},
        baseline_failing=task.baseline_failing,
        gold={"clean": True, "note": "", "lint": gold_lint},
    )


def context(
    task: TaskSpec,
    executor: Executor,
    *,
    witness: Witness | None = None,
    gold_lint: bool | None = None,
) -> tuple[TaskSpec, GradeContext]:
    """A qualified discovery-value context with ``witness`` (default: none)."""
    q = discovery_qualification(task, executor, gold_lint=gold_lint)
    ctx = GradeContext(
        posture=Posture.from_dict(q.posture),
        qualification=q,
        deps=TaskDeps.uniform(NO_DEPS if executor.name == "docker" else HOST_ENV_DEPS),
        witness=witness,
    )
    return q.project(task), ctx


def gold_witness(
    repo: GitRepo,
    config: RepoConfig,
    task: TaskSpec,
    *,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    timeout: int = 0,
) -> GoldWitness:
    """A real gold witness on the fixture repository."""
    return GoldWitness(
        repo,
        config,
        task,
        runner=runner,
        executor=executor,
        scratch=scratch,
        binding=NO_DEPS if executor.name == "docker" else HOST_ENV_DEPS,
        timeout=timeout,
    )


def witnessed_context_for(
    repo: GitRepo,
    config: RepoConfig,
    *,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    timeout: int = 0,
    gold_lint: bool | None = None,
) -> Callable[[TaskSpec], GradeContext]:
    """A ``RunSpec.context_for`` with a real ``GoldWitness`` per task (and the gold's belt 5
    at qualification, ``gold_lint``: ``None`` = never measured)."""

    def context_for(task: TaskSpec) -> GradeContext:
        w = gold_witness(
            repo, config, task, runner=runner, executor=executor, scratch=scratch, timeout=timeout
        )
        return context(task, executor, witness=w, gold_lint=gold_lint)[1]

    return context_for


def grade_adhoc(
    ws: Workspace,
    task: TaskSpec,
    *,
    executor: Executor,
    witness: Witness | None = None,
    gold_lint: bool | None = None,
    **kw: Any,
) -> GradeResult:
    """``grade()`` with a context built here: unwitnessed ad hoc by default, or a qualified
    discovery-value context carrying ``witness`` (and the gold's belt 5, ``gold_lint``)."""
    t, ctx = (
        context(task, executor, witness=witness, gold_lint=gold_lint)
        if witness is not None
        else adhoc(task, executor)
    )
    return grade(ws, t, ctx=ctx, executor=executor, **kw)


def grade_witnessed(
    ws: Workspace,
    task: TaskSpec,
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    **kw: Any,
) -> GradeResult:
    """``grade()`` under a qualified discovery-value context with a REAL gold witness on the
    worktree's own repository — for tests that turn the result into a ledger row."""
    w = gold_witness(
        ws.repo, config, task, runner=runner, executor=executor, scratch=ws.root.parent / "witness"
    )
    return grade_adhoc(ws, task, config=config, runner=runner, executor=executor, witness=w, **kw)


#: The posture a test row is stamped with when a factory does not name one.
TEST_POSTURE_ID = "pst_" + "5" * 24
TEST_POSTURE_CLASS = "local/inplace/host-env"
TEST_QUALIFICATION_ID = "q-test-fixture"


def with_posture_labels(fields: dict[str, Any]) -> dict[str, Any]:
    """``GradeRow`` keyword arguments with the ADR-0019 labels a measured row of the current
    apparatus must carry, filled in where the test did not name them: the posture, and on
    a row whose belts blame the model, the ``gold_green`` witness."""
    from crb.core.ledger import parse_apparatus_version
    from crb.core.version import APPARATUS_VERSION

    version = str(fields.get("apparatus_version") or APPARATUS_VERSION)
    parsed = parse_apparatus_version(version)
    if (
        str(fields.get("provenance") or "measured") != "measured"
        or parsed is None
        or parsed < (2, 3)
    ):
        return fields
    labels = dict(fields.get("labels") or {})
    labels.setdefault("posture_id", TEST_POSTURE_ID)
    labels.setdefault("posture_class", TEST_POSTURE_CLASS)
    labels.setdefault("qualification_id", TEST_QUALIFICATION_ID)
    if not fields.get("clean") and not fields.get("disqualified") and not fields.get("error"):
        # belt 6 alone (ADR-0024) is a fact about the diff, witnessed as ``api_diff``
        api_only = labels.get("api_stable") == "false" and all(
            fields.get(b) is True
            for b in ("tests_unmodified", "target_green", "no_new_failures", "source_changed")
        )
        labels.setdefault("blame_control", "api_diff" if api_only else "gold_green")
    return {**fields, "labels": labels}


def posture_result(*args: Any, **kw: Any) -> GradeResult:
    """A hand-built ``GradeResult`` stamped with the test posture (and, when its belts blame
    the builder, the ``gold_green`` witness) unless the test names them — what ``grade()``
    itself always writes. Positional arguments follow ``GradeResult``'s own order."""
    for name, value in zip(("task_id", "repo", "mode", "clean", "belts"), args, strict=False):
        kw[name] = value
    kw.setdefault("posture_id", TEST_POSTURE_ID)
    kw.setdefault("posture_class", TEST_POSTURE_CLASS)
    kw.setdefault("qualification_id", TEST_QUALIFICATION_ID)
    belts = kw.get("belts")
    blamed = (
        belts is not None
        and not kw.get("clean")
        and not kw.get("disqualified")
        and not kw.get("error")
        and any(
            v is False
            for v in (
                belts.target_green,
                belts.no_new_failures,
                belts.source_changed,
                belts.repo_lint_clean,
                belts.api_stable,
            )
        )
    )
    if blamed:
        # belt 6 alone (ADR-0024) is a fact about the diff, witnessed as ``api_diff``
        api_only = belts.api_stable is False and all(
            v is True
            for v in (
                belts.tests_unmodified,
                belts.target_green,
                belts.no_new_failures,
                belts.source_changed,
            )
        )
        kw.setdefault("blame_control", "api_diff" if api_only else "gold_green")
    return GradeResult(**kw)


def posture_row(**kw: Any) -> GradeRow:
    """``GradeRow(**kw)`` with :func:`with_posture_labels` applied — the test factories'
    shape for a measured row of the current apparatus."""
    return GradeRow(**with_posture_labels(kw))
