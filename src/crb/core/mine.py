"""Find replayable commits; prove them RED; capture the baseline; prove the gold GREEN.

A commit is a *candidate* when it couples source and test changes within the
pool's size caps. A candidate becomes a *task* only after three facts are
measured, never assumed:

1. **RED**  — at the parent, with only the commit's tests overlaid, the target
   scope fails (and does not time out).
2. **Baseline** — the belt scope's failing set at that same state (pre-existing
   failures are recorded, so belt 3 is baseline-relative).
3. **GOLD** — overlaying the commit's own source turns the target GREEN with no
   new belt failures. A task whose gold does not pass is kept but flagged
   ``gold_clean=False`` and is excluded from capability statistics: the oracle
   could not be satisfied by the humans' own patch, so it cannot judge a builder.

The miner assigns the **path class** only (:func:`~crb.core.spec.classify_commit`);
the intent label is a separate step (:mod:`crb.core.classify`) so mining never
needs a model.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.execution import Executor
from crb.core.git import GitRepo
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
    src_min: int
    src_max: int
    files_max: int


def pool_caps(config: RepoConfig, pool: str) -> PoolCaps:
    jvm = config.language.value == "jvm"
    if pool == POOL_HARD:
        return PoolCaps(4, 8, 14)
    if pool == POOL_STANDARD:
        return PoolCaps(1, 6 if jvm else 3, 8 if jvm else 6)
    raise ValueError(f"unknown pool {pool!r}")


@dataclass(frozen=True)
class Candidate:
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
) -> Iterator[Candidate]:
    """Walk history newest→oldest yielding commits that fit the pool's shape."""
    caps = pool_caps(config, pool)
    n = log_n or int(config.mining.get("log_n", 3000))
    for sha in repo.log_shas(n, ref=ref):
        if sha in skip:
            continue
        if not repo.run("rev-parse", "--verify", "--quiet", f"{sha}^1").ok:
            continue  # root commit: no parent to replay from
        files = repo.changed_files(sha)
        src = [f for f in files if config.is_src(f)]
        tests = [f for f in files if config.is_test(f)]
        lang_files = config.language_files(files)
        if not (src and tests):
            continue
        if not (caps.src_min <= len(src) <= caps.src_max and len(lang_files) <= caps.files_max):
            continue
        yield Candidate(sha, tuple(files), tuple(src), tuple(tests))


@dataclass(frozen=True)
class MineOutcome:
    sha: str
    task: TaskSpec | None
    skipped_reason: str = ""
    duration_s: float = 0.0


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
) -> MineOutcome:
    """RED-check + baseline (+ gold) one candidate in a fresh worktree."""
    started = time.monotonic()
    sha = cand.sha
    dest = Path(scratch) / f"mine-{config.name}-{sha[:10]}"
    _emit(on_event, "mine.candidate", repo=config.name, sha=sha, pool=pool)
    with Workspace.create(repo, sha, dest, config=config) as ws:
        ws.overlay_tests(cand.test_files)
        target_scope = runner.target_scope(cand.test_files)
        red = runner.run(executor, ws.root, target_scope, timeout=timeout)
        if red.timed_out:
            _emit(on_event, "mine.skip", sha=sha, reason="target timeout at parent")
            return MineOutcome(sha, None, "target timeout at parent", time.monotonic() - started)
        if red.green:
            _emit(on_event, "mine.skip", sha=sha, reason="target green at parent (not RED)")
            return MineOutcome(sha, None, "target green at parent", time.monotonic() - started)

        belt_scope = runner.belt_scope(target_scope, cand.test_files)
        base = runner.run(executor, ws.root, belt_scope, timeout=timeout)
        if base.timed_out:
            _emit(on_event, "mine.skip", sha=sha, reason="baseline timeout")
            return MineOutcome(sha, None, "baseline timeout", time.monotonic() - started)

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
        if gold:
            task = gold_check(
                ws, task, runner=runner, executor=executor, timeout=timeout, on_event=on_event
            )
    return MineOutcome(sha, task, "", time.monotonic() - started)


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
    """
    try:
        ws.overlay_sources(task.src_files)
        tgt = runner.run(executor, ws.root, task.target_tests, timeout=timeout)
        if not tgt.green:
            note = (
                "gold target timed out"
                if tgt.timed_out
                else f"gold target not green (rc={tgt.returncode})"
            )
            _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note)
            return task.with_(gold_clean=False, gold_note=note)
        belt = runner.run(executor, ws.root, task.belt_scope, timeout=timeout)
        if belt.timed_out or belt.parse_error:
            note = (
                "gold belt timed out"
                if belt.timed_out
                else f"gold belt unattributed: {belt.parse_error}"
            )
            _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note)
            return task.with_(gold_clean=False, gold_note=note)
        new = set(belt.failing) - set(task.baseline_failing)
        clean = not new
        note = "" if clean else f"gold introduced {len(new)} belt failure(s)"
        _emit(on_event, "mine.gold", sha=task.task_id, clean=clean, note=note)
        return task.with_(gold_clean=clean, gold_note=note)
    except Exception as exc:  # never credit a task on a harness error
        note = f"gold error: {type(exc).__name__}: {exc}"[:300]
        _emit(on_event, "mine.gold", sha=task.task_id, clean=False, note=note)
        return task.with_(gold_clean=False, gold_note=note)


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
    gold: bool = True,
    timeout: int = 0,
    ref: str = "HEAD",
    on_event: EventFn | None = None,
) -> Iterator[MineOutcome]:
    """Yield qualification outcomes until ``target_count`` tasks are found or
    ``max_candidates`` candidates were examined."""
    want = target_count or int(
        config.mining.get("target_valid" if pool == POOL_STANDARD else "hard_target", 25)
    )
    cap = max_candidates or int(config.mining.get("max_candidates", 1000))
    found = examined = 0
    for cand in iter_candidates(repo, config, pool=pool, ref=ref, skip=known):
        if found >= want or examined >= cap:
            break
        examined += 1
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
        )
        if outcome.task is not None:
            found += 1
        yield outcome
    _emit(on_event, "mine.done", repo=config.name, pool=pool, found=found, examined=examined)
