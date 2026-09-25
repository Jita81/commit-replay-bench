"""Find replayable commits; prove them RED; capture the baseline; prove the gold GREEN.

A commit is a *candidate* when it couples source and test changes within the
pool's size caps. A candidate becomes a *task* only after three facts are
measured, never assumed:

1. **RED**  — at the parent, with only the commit's tests overlaid, the target
   scope fails (and does not time out).
2. **Baseline** — the belt scope's failing set at that same state (pre-existing
   failures are recorded, so belt 3 is baseline-relative).
3. **GOLD** — overlaying the commit's own source turns the target GREEN with no
   new belt failures, **and** the repository's own linter (belt 5, ADR-0011)
   accepts the overlaid source files. A task whose gold does not pass is kept but
   flagged ``gold_clean=False`` and is excluded from capability statistics: the
   oracle could not be satisfied by the humans' own patch, so it cannot judge a
   builder. Belt 5 on the gold is the fair correction for pre-existing lint debt:
   the belt reproduces the repository's CI verdict on the *changed files*, so a
   file the maintainers themselves left non-conforming would count against every
   builder that touches it — excluding the task from the denominator is honest;
   attributing the debt to the model is not.

The miner assigns the **path class** only (:func:`~crb.core.spec.classify_commit`);
the intent label is a separate step (:mod:`crb.core.classify`) so mining never
needs a model.

Navigation
----------
What it is:   The miner — the stage that turns a repository's history into ``TaskSpec``s
              whose oracle is proven RED at the parent and satisfiable by the humans' own
              patch.
What it does: Walks commits newest-first and keeps those that couple source and test
              changes within the pool's caps; for each, in a fresh worktree, measures RED,
              the baseline failing set and (unless told not to) the gold under belts 2, 3
              and 5; skips a candidate whose target is green, times out or defines no test;
              stops the run after three consecutive harness errors rather than skipping
              history silently. Never assigns an intent label and never needs a model.
How:          ``iter_candidates`` (git log + changed files + layout rules) → ``qualify``
              (``Workspace.create`` → ``overlay_tests`` → target run → belt-scope run →
              ``TaskSpec``) → ``gold_check`` (``overlay_sources`` → target → belt → lint) →
              ``mine`` drives the loop to ``target_count`` and emits ``mine.*`` events.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md,
              docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/spec.py (RepoConfig layout rules, TaskSpec, size tiers, path
              class), src/crb/core/workspace.py (the worktree and overlays),
              src/crb/core/runners/base.py (target scope, belt scope, oracle validity, lint
              plan), src/crb/core/git.py (log, changed files, churn), src/crb/core/grade.py
              (applies the same belts to a builder's patch), src/crb/core/lint.py (belt 5 on
              the gold), src/crb/cli/commands/mine.py (the ``crb mine`` command)
Tested by:    tests/test_mine.py, tests/test_runners_go.py, tests/test_runners_jvm.py,
              tests/test_runners_node.py, tests/test_runners_cargo.py
Touch when:   onboarding a repository whose commits do not fit the pool caps (``pool_caps``)
              or whose skip reasons dominate (``crb mine`` reports them: fix the layout,
              probe scope or ``mining`` limits in the repo config first —
              docs/OPERATOR.md#2-configure-a-repository); changing a cap or a qualification
              rule changes which commits become tasks — bump src/crb/core/version.py.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.deps import SCOPE_RUN, DepsProvider, NullDepsProvider, ProvisionRefused, TaskDeps
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.lint import LintRun, run_plan
from crb.core.posture import Posture, resolve_posture
from crb.core.qualify import (
    QUAL_BASELINE_TIMEOUT,
    QUAL_BASELINE_UNATTRIBUTED,
    QUAL_ENV_UNLOADABLE,
    QUAL_NOT_RED,
    QUAL_RED_TIMEOUT,
    QUAL_TREE_COPY_FAILED,
    Qualification,
    qualify_task,
)
from crb.core.runners.base import BaseRunner
from crb.core.spec import (
    POOL_HARD,
    POOL_STANDARD,
    RepoConfig,
    TaskSpec,
    classify_commit,
    size_tier,
)
from crb.core.workspace import Workspace

EventFn = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True)
class PoolCaps:
    """The shape a commit must have to enter a pool: how many SOURCE files it may
    touch (``src_min``–``src_max``) and how many language files in total."""

    src_min: int
    src_max: int
    files_max: int


def pool_caps(config: RepoConfig, pool: str) -> PoolCaps:
    """The census caps. JVM gets wider caps because one change there spans code plus
    templates and properties under ``src/main/`` (``RepoConfig.is_src``)."""
    jvm = config.language.value == "jvm"
    if pool == POOL_HARD:
        return PoolCaps(4, 8, 14)
    if pool == POOL_STANDARD:
        return PoolCaps(1, 6 if jvm else 3, 8 if jvm else 6)
    raise ValueError(f"unknown pool {pool!r}")


@dataclass(frozen=True)
class Candidate:
    """A commit that fits the pool's shape but has not yet been proven replayable."""

    sha: str
    files: tuple[str, ...]
    src_files: tuple[str, ...]
    test_files: tuple[str, ...]


def iter_candidates(
    repo: GitRepo,
    config: RepoConfig,
    *,
    pool: str = POOL_STANDARD,
    log_n: int = 0,
    ref: str = "HEAD",
    skip: frozenset[str] = frozenset(),
    only: frozenset[str] | None = None,
) -> Iterator[Candidate]:
    """Walk history newest→oldest yielding commits that fit the pool's shape.

    ``only`` restricts the walk to those shas (re-qualifying known tasks after the
    miner changed); ``skip`` drops shas already mined."""
    caps = pool_caps(config, pool)
    n = log_n or int(config.mining.get("log_n", 3000))
    for sha in repo.log_shas(n, ref=ref):
        if sha in skip or (only is not None and sha not in only):
            continue
        if not repo.run("rev-parse", "--verify", "--quiet", f"{sha}^1").ok:
            continue  # root commit: no parent to replay from
        files = repo.changed_files(sha)
        src = [f for f in files if config.is_src(f)]
        tests = [f for f in files if config.is_test(f)]
        lang_files = config.language_files(files)
        if not (src and tests):
            continue  # no oracle, or nothing for the oracle to judge

        if not (caps.src_min <= len(src) <= caps.src_max and len(lang_files) <= caps.files_max):
            continue
        yield Candidate(sha, tuple(files), tuple(src), tuple(tests))


@dataclass(frozen=True)
class MineOutcome:
    """What qualifying one candidate produced: a ``task`` (possibly ``gold_clean=False``)
    or ``None`` with the ``skipped_reason`` the run reports."""

    sha: str
    task: TaskSpec | None
    skipped_reason: str = ""
    duration_s: float = 0.0
    #: The candidate's qualification in the mine's own posture (ADR-0019 §2): the record
    #: the task's discovery fields were read from, kept whether it qualified or not.
    #: ``None`` when the mine ran without the gold check (discovery values only).
    qualification: Qualification | None = None


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def qualify(
    repo: GitRepo,
    config: RepoConfig,
    cand: Candidate,
    *,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    pool: str = POOL_STANDARD,
    gold: bool = True,
    timeout: int = 0,
    on_event: EventFn | None = None,
    posture: Posture | None = None,
    deps: TaskDeps | DepsProvider | None = None,
    run_id: str = "",
) -> MineOutcome:
    """RED-check + baseline (+ gold) one candidate in a fresh worktree.

    With the gold check (the default) the facts are measured by
    :func:`crb.core.qualify.qualify_task` in the mine's own posture (``posture``, resolved
    live when not given) and the outcome carries that :class:`Qualification`: the
    discovery ``TaskSpec``'s RED, baseline and gold fields are read from it (ADR-0019 §2).
    Without it, the discovery values are measured as before and no record is made.

    Every test run is bound to the commit's author date (``authored``) so a declared
    service (:mod:`crb.core.services`) answers in the era variant that commit was
    written against. A skip is a fact about the candidate (not RED, timed out, no
    oracle); a harness exception propagates to :func:`mine`, which counts it.
    """
    started = time.monotonic()
    sha = cand.sha
    dest = Path(scratch) / f"mine-{config.name}-{sha[:10]}"
    _emit(on_event, "mine.candidate", repo=config.name, sha=sha, pool=pool)
    with Workspace.create(repo, sha, dest, config=config) as ws:
        ws.overlay_tests(cand.test_files)
        # a file under the test layout that defines no tests (tests/mock_server.py,
        # tests/helpers.py) is SUPPORT: overlaid alongside the oracle, never a target —
        # graded as a target it disqualified every mesh-client control as a "malformed
        # oracle" (2026-09-15)
        oracles = [t for t in cand.test_files if runner.is_valid_oracle(ws.root, t)]
        if not oracles:
            _emit(
                on_event, "mine.skip", sha=sha, reason="no test file defines a test (support only)"
            )
            return MineOutcome(
                sha, None, "no test file defines a test (support only)", time.monotonic() - started
            )
        target_scope = runner.target_scope(oracles)
        if gold:
            discovery = _discovery_spec(
                repo, config, cand, runner, target_scope=target_scope, pool=pool
            )
    if gold:
        return _qualified_outcome(
            repo,
            config,
            discovery,
            runner=runner,
            executor=executor,
            scratch=scratch,
            timeout=timeout,
            on_event=on_event,
            posture=posture,
            deps=deps,
            run_id=run_id,
            started=started,
        )
    with Workspace.create(repo, sha, dest, config=config) as ws:
        ws.overlay_tests(cand.test_files)
        red = runner.run_for(
            executor, ws.root, target_scope, timeout=timeout, authored=repo.author_date(cand.sha)
        )
        # a timeout is not RED: a target that never finishes at the parent cannot be
        # told apart from one that fails, and a builder could "pass" it by making it hang
        if red.timed_out:
            _emit(on_event, "mine.skip", sha=sha, reason="target timeout at parent")
            return MineOutcome(sha, None, "target timeout at parent", time.monotonic() - started)
        if red.green:
            _emit(on_event, "mine.skip", sha=sha, reason="target green at parent (not RED)")
            return MineOutcome(sha, None, "target green at parent", time.monotonic() - started)

        belt_scope = runner.belt_scope(target_scope, cand.test_files)
        base = runner.run_for(
            executor, ws.root, belt_scope, timeout=timeout, authored=repo.author_date(cand.sha)
        )
        if base.timed_out:
            _emit(on_event, "mine.skip", sha=sha, reason="baseline timeout")
            return MineOutcome(sha, None, "baseline timeout", time.monotonic() - started)

        # size is the SOURCE churn only: the tests are the oracle, not the change
        churn = repo.numstat_churn(f"{sha}~1", sha, list(cand.src_files))
        task = TaskSpec(
            task_id=sha,
            repo=config.name,
            subject=repo.subject(sha)[:160],
            authored=repo.author_date(sha),
            test_files=cand.test_files,
            src_files=cand.src_files,
            target_tests=target_scope,
            belt_scope=belt_scope,
            pool=pool,
            src_churn=churn,
            size=size_tier(churn),
            # The path axis only: intent labels are a separate, later step (`label` run /
            # ``crb tasks label``), so a freshly mined task resolves to its path class.
            path_class=classify_commit(list(cand.src_files)),
            intent=None,
            language=config.language.value,
            baseline_failing=tuple(sorted(base.failing)),
            red_checked=True,
            labels={"baseline_parse_error": base.parse_error} if base.parse_error else {},
        )
        _emit(
            on_event,
            "mine.red",
            sha=sha,
            size=task.size,
            cls=task.capability_class,
            baseline_failing=len(task.baseline_failing),
        )
    return MineOutcome(sha, task, "", time.monotonic() - started)


#: The skip reason each qualification refusal of the PARENT reads as in a mine report
#: (the words ``crb mine`` has always printed for the same facts).
_SKIP_REASON: dict[str, str] = {
    QUAL_NOT_RED: "target green at parent",
    QUAL_RED_TIMEOUT: "target timeout at parent",
    QUAL_BASELINE_TIMEOUT: "baseline timeout",
}
#: Refusals about the PARENT: the candidate is not a task in this posture at all.
_PARENT_CODES: frozenset[str] = frozenset(
    {
        QUAL_NOT_RED,
        QUAL_RED_TIMEOUT,
        QUAL_BASELINE_TIMEOUT,
        QUAL_BASELINE_UNATTRIBUTED,
        QUAL_ENV_UNLOADABLE,
        QUAL_TREE_COPY_FAILED,
    }
)


def _discovery_spec(
    repo: GitRepo,
    config: RepoConfig,
    cand: Candidate,
    runner: BaseRunner,
    *,
    target_scope: tuple[str, ...],
    pool: str,
) -> TaskSpec:
    """The candidate's shape as a ``TaskSpec`` before anything is measured."""
    sha = cand.sha
    # size is the SOURCE churn only: the tests are the oracle, not the change
    churn = repo.numstat_churn(f"{sha}~1", sha, list(cand.src_files))
    return TaskSpec(
        task_id=sha,
        repo=config.name,
        subject=repo.subject(sha)[:160],
        authored=repo.author_date(sha),
        test_files=cand.test_files,
        src_files=cand.src_files,
        target_tests=target_scope,
        belt_scope=runner.belt_scope(target_scope, cand.test_files),
        pool=pool,
        src_churn=churn,
        size=size_tier(churn),
        path_class=classify_commit(list(cand.src_files)),
        intent=None,
        language=config.language.value,
    )


def _qualified_outcome(
    repo: GitRepo,
    config: RepoConfig,
    discovery: TaskSpec,
    *,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    timeout: int,
    on_event: EventFn | None,
    posture: Posture | None,
    deps: TaskDeps | DepsProvider | None,
    run_id: str,
    started: float,
) -> MineOutcome:
    """Qualify ``discovery`` in the mine's posture and read the task's fields from it."""
    provider: TaskDeps | DepsProvider = deps if deps is not None else NullDepsProvider()
    if posture is None:
        mode = (
            provider.mode(config, executor.name)
            if not isinstance(provider, TaskDeps)
            else NullDepsProvider().mode(config, executor.name)
        )
        posture = resolve_posture(executor, runner, deps_mode=mode, root=repo.path)
    q = qualify_task(
        repo,
        config,
        discovery,
        posture=posture,
        deps=provider,
        runner=runner,
        executor=executor,
        scratch=scratch,
        timeout=timeout,
        run_id=run_id,
        on_event=on_event,
    )
    sha = discovery.task_id
    if q.code in _PARENT_CODES:
        reason = _SKIP_REASON.get(q.code, f"{q.code}: {q.message}")[:300]
        said = "target green at parent (not RED)" if q.code == QUAL_NOT_RED else reason
        _emit(on_event, "mine.skip", sha=sha, reason=said, code=q.code)
        return MineOutcome(sha, None, reason, time.monotonic() - started, q)
    labels = {"posture_id": q.posture_id, "posture_class": q.posture_class}
    if q.red.get("baseline_parse_error"):
        labels["baseline_parse_error"] = str(q.red["baseline_parse_error"])
    if q.is_qualified:
        task = discovery.with_(
            baseline_failing=sorted(q.baseline),
            red_checked=True,
            gold_clean=True,
            gold_note="",
            labels={**discovery.labels, **labels},
        )
    else:
        task = discovery.with_(
            baseline_failing=sorted(q.baseline),
            red_checked=True,
            gold_clean=False,
            gold_note=(q.gold.get("note") or f"{q.code}: {q.message}")[:300],
            labels={**discovery.labels, **labels, "qualification_code": q.code},
        )
    _emit(
        on_event,
        "mine.red",
        sha=sha,
        size=task.size,
        cls=task.capability_class,
        baseline_failing=len(task.baseline_failing),
    )
    _emit(
        on_event,
        "mine.gold",
        sha=sha,
        clean=bool(task.gold_clean),
        note=task.gold_note,
        lint=q.gold.get("lint"),
    )
    return MineOutcome(sha, task, "", time.monotonic() - started, q)


def gold_check(
    ws: Workspace,
    task: TaskSpec,
    *,
    runner: BaseRunner,
    executor: Executor,
    timeout: int = 0,
    on_event: EventFn | None = None,
) -> TaskSpec:
    """Overlay the commit's own sources and prove the oracle can be satisfied.

    Expects ``ws`` to be at the parent with the tests already overlaid. Leaves the
    sources overlaid (callers use a fresh worktree for trials anyway).

    Three facts, in order, each fail-closed: the target turns GREEN; the belt
    scope shows no failure the baseline did not have; and belt 5 — the same lint
    plan :func:`crb.core.grade.grade` would run on a builder's changed files
    (``runner.lint_plan``: the declared ``RepoConfig.lint``, else the language's
    detection, else nothing) — accepts the overlaid source files that still exist.
    A gold that fails belt 5 is ``gold_clean=False`` with
    ``gold_note="gold fails belt 5 (<detected>): …"`` so the maintainers' own lint
    debt is excluded from the denominator instead of being counted against the
    builder (ADR-0011, consequences). A linter that *cannot run* is a harness
    error: the gold is not credited (never a pass) and the note names the
    instrument, not the patch. No plan, or no lintable overlaid file, leaves belt 5
    *not evaluated* — neither a pass nor a fail, and the gold verdict unchanged.

    The ``mine.gold`` event carries ``lint``: ``True`` / ``False`` / ``None`` (not
    evaluated), the same value semantics as ``GradeResult.belts.repo_lint_clean``.
    """
    try:
        ws.overlay_sources(task.src_files)
        tgt = runner.run_for(
            executor, ws.root, task.target_tests, timeout=timeout, authored=task.authored
        )
        if not tgt.green:
            note = (
                "gold target timed out"
                if tgt.timed_out
                else f"gold target not green (rc={tgt.returncode})"
            )
            _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note, lint=None)
            return task.with_(gold_clean=False, gold_note=note)
        belt = runner.run_for(
            executor, ws.root, task.belt_scope, timeout=timeout, authored=task.authored
        )
        if belt.timed_out or belt.parse_error:
            note = (
                "gold belt timed out"
                if belt.timed_out
                else f"gold belt unattributed: {belt.parse_error}"
            )
            _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note, lint=None)
            return task.with_(gold_clean=False, gold_note=note)
        new = set(belt.failing) - set(task.baseline_failing)
        if new:
            note = f"gold introduced {len(new)} belt failure(s)"
            _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note, lint=None)
            return task.with_(gold_clean=False, gold_note=note)
        # belt 5 on the gold: the same plan a builder's patch would face, over the
        # overlaid source files that still exist (a deletion cannot be linted).
        lint_run = _gold_lint(ws, task, runner=runner, executor=executor)
        lint = lint_run.ok if lint_run is not None else None
        clean, note = _read_gold_lint(lint_run)
        _emit(on_event, "mine.gold", sha=task.task_id, clean=clean, note=note, lint=lint)
        return task.with_(gold_clean=clean, gold_note=note)
    except Exception as exc:  # never credit a task on a harness error
        note = f"gold error: {type(exc).__name__}: {exc}"[:300]
        _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note, lint=None)
        return task.with_(gold_clean=False, gold_note=note)


def _gold_lint(
    ws: Workspace, task: TaskSpec, *, runner: BaseRunner, executor: Executor
) -> LintRun | None:
    """Run belt 5's plan on the overlaid gold sources; ``None`` when the repository
    has no linter (the belt is then not evaluated for the gold, as for a trial)."""
    plan = runner.lint_plan(ws.root, executor)
    if plan is None:
        return None
    present = [f for f in task.src_files if ws.exists(f)]
    # the plan's own wall clock governs (RepoConfig.lint.timeout or the lint default),
    # exactly as in grade(): the test-run timeout is a different budget
    return run_plan(plan, executor, ws.root, present)


def _read_gold_lint(lint_run: LintRun | None) -> tuple[bool, str]:
    """``(gold_clean, gold_note)`` from belt 5's record on the gold — the ONE place
    the gold's lint verdict is read. ``None`` (no plan, or nothing to lint) leaves
    the gold clean; a rejection or a timeout is the maintainers' own lint debt; a
    linter that could not run is a harness error and is never a pass."""
    if lint_run is None or lint_run.ok is None:
        return True, ""
    if lint_run.ok:
        return True, ""
    if lint_run.error:
        note = f"gold lint could not run ({lint_run.detected}): {lint_run.error}"
    else:
        note = f"gold fails belt 5 ({lint_run.detected}): {lint_run.note}"
    return False, note[:300]


#: A run stops after this many candidates IN A ROW fail on a harness error.
MAX_CONSECUTIVE_HARNESS_ERRORS = 3
#: A mine stops after this many candidates IN A ROW cannot load their dependencies in the
#: mine's posture (ADR-0019): the posture, not history, is the problem.
MAX_CONSECUTIVE_UNLOADABLE = 3


def mine(
    repo: GitRepo,
    config: RepoConfig,
    *,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    pool: str = POOL_STANDARD,
    target_count: int = 0,
    max_candidates: int = 0,
    known: frozenset[str] = frozenset(),
    only: frozenset[str] | None = None,
    gold: bool = True,
    timeout: int = 0,
    ref: str = "HEAD",
    on_event: EventFn | None = None,
    posture: Posture | None = None,
    deps: TaskDeps | DepsProvider | None = None,
    run_id: str = "",
) -> Iterator[MineOutcome]:
    """Yield qualification outcomes until ``target_count`` tasks are found or
    ``max_candidates`` candidates were examined (``only``: just these shas).

    A task counts as found whatever its ``gold_clean`` — the miner's job is to
    record the fact, and the statistics exclude a false gold later. ``known`` shas
    are skipped so re-mining a repository extends its tasks rather than repeating
    them.
    """
    want = target_count or int(
        config.mining.get("target_valid" if pool == POOL_STANDARD else "hard_target", 25)
    )
    cap = max_candidates or int(config.mining.get("max_candidates", 1000))
    found = examined = consecutive_errors = unloadable = 0
    if gold and posture is None:
        provider = deps if deps is not None else NullDepsProvider()
        mode = NullDepsProvider().mode(config, executor.name)
        if not isinstance(provider, TaskDeps):
            mode = provider.mode(config, executor.name)
        # one posture for the whole mine: every candidate is qualified in the same one
        posture = resolve_posture(executor, runner, deps_mode=mode, root=repo.path)
    for cand in iter_candidates(repo, config, pool=pool, ref=ref, skip=known, only=only):
        if found >= want or examined >= cap:
            break
        examined += 1
        started = time.monotonic()
        try:
            outcome = qualify(
                repo,
                config,
                cand,
                runner=runner,
                executor=executor,
                scratch=scratch,
                pool=pool,
                gold=gold,
                timeout=timeout,
                on_event=on_event,
                posture=posture,
                deps=deps,
                run_id=run_id,
            )
        except SandboxUnavailable:
            raise  # infrastructure: nothing else will qualify either
        except ProvisionRefused as exc:
            if exc.refusal.scope != SCOPE_RUN:  # pragma: no cover — qualify_task records it
                raise
            # a deployment setting: nothing in this posture will provision either
            raise RuntimeError(
                f"{exc.refusal.code}: {exc.refusal.message} — what to do: {exc.refusal.fix}"
            ) from exc
        except Exception as exc:
            # a harness error on ONE candidate (its dependency era would not install,
            # its service is missing) skips that candidate; MAX_CONSECUTIVE_HARNESS_ERRORS
            # in a row means the instrument itself is broken (a full disk, a dead
            # toolchain) and the run stops with that reason instead of skipping history
            consecutive_errors += 1
            reason = f"harness error: {type(exc).__name__}: {exc}"[:300]
            _emit(on_event, "mine.skip", sha=cand.sha, reason=reason)
            if consecutive_errors >= MAX_CONSECUTIVE_HARNESS_ERRORS:
                raise RuntimeError(
                    f"{consecutive_errors} candidates in a row failed on a harness error; "
                    f"last: {reason}"
                ) from exc
            yield MineOutcome(cand.sha, None, reason, time.monotonic() - started)
            continue
        consecutive_errors = 0
        q = outcome.qualification
        unloadable = unloadable + 1 if q is not None and q.code == QUAL_ENV_UNLOADABLE else 0
        if outcome.task is not None:
            found += 1
        yield outcome
        if unloadable >= MAX_CONSECUTIVE_UNLOADABLE:
            raise RuntimeError(
                f"{QUAL_ENV_UNLOADABLE}: {unloadable} candidates in a row could not load their "
                "dependencies offline — this posture cannot load the module graph — switch "
                "provisioning on and qualify"
            )
    _emit(on_event, "mine.done", repo=config.name, pool=pool, found=found, examined=examined)
