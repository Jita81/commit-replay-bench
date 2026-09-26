"""``crb mine`` — find replayable commits, prove them RED, capture baselines, gold-check.

Navigation
----------
What it is:   ``crb mine`` — walk a registered repo's history for replayable commits and
              write the qualified ones as tasks.
What it does: Streams the core's ``mine`` outcomes (RED check → baseline → gold check),
              appends each qualified task to ``<workdir>/tasks/<repo>.jsonl`` AS IT IS
              FOUND so an interrupted run keeps what it proved, and reports what was
              examined, found and skipped by reason. Never re-mines a task already on file.
How:          ``require_clone`` → ``bound_runner`` + ``build_executor`` → ``mine(...)``
              generator → ``append_tasks`` per outcome → summary.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/mine.py (the qualification pipeline), src/crb/cli/commands/repo.py
              (``bound_runner`` / ``env_dir_of`` — the runner on the set-up environment),
              src/crb/cli/commands/__init__.py (``Workdir.append_tasks``, ``known_task_ids``),
              src/crb/cli/commands/grade.py (consumes the task file), docs/OPERATOR.md#3-run-a-sweep
Tested by:    tests/test_cli.py
Touch when:   never for a new repository (pool caps and candidate limits are repo config —
              docs/OPERATOR.md#2-configure-a-repository); when ``mine`` gains a parameter
              worth exposing as a flag.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Any

from crb.cli.commands import (
    EXIT_OK,
    CliError,
    add_common,
    add_executor,
    build_executor,
    deps_provider,
    event_printer,
    print_json,
    print_lines,
    workdir_of,
)
from crb.cli.commands import repo as repo_cmd
from crb.core.git import GitRepo
from crb.core.mine import mine
from crb.core.qualify import JsonlQualifications
from crb.core.spec import POOL_HARD, POOL_STANDARD


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb mine``."""
    p = sub.add_parser("mine", help="mine replayable commits into <workdir>/tasks/<name>.jsonl")
    p.add_argument("name", help="registered repo")
    p.add_argument("--pool", choices=(POOL_STANDARD, POOL_HARD), default=POOL_STANDARD)
    p.add_argument("--target", type=int, default=0, help="stop after N new tasks (0 = config)")
    p.add_argument(
        "--max-candidates", type=int, default=0, help="examine at most N candidates (0 = config)"
    )
    p.add_argument(
        "--no-gold", action="store_true", help="skip the gold check (tasks stay unjudged)"
    )
    p.add_argument("--ref", default="HEAD", help="history to walk (default HEAD)")
    p.add_argument(
        "--events", action="store_true", help="stream mine.* events as JSON lines on stderr"
    )
    add_executor(p)
    add_common(p)
    p.set_defaults(func=cmd_mine)


def cmd_mine(args: argparse.Namespace) -> int:
    """Run the miner and append qualified tasks as they are proved."""
    wd = workdir_of(args)
    config, clone = wd.require_clone(args.name)
    repo = GitRepo(clone)
    if not repo.is_repo():
        raise CliError(f"{clone} is not a git repository")
    runner = repo_cmd.bound_runner(config, repo_cmd.env_dir_of(wd, args.name))
    executor = build_executor(args.executor, config)
    known = wd.known_task_ids(args.name)
    on_event = event_printer(sys.stderr) if args.events else None
    wd.scratch_dir.mkdir(parents=True, exist_ok=True)

    found: list[str] = []
    quals = JsonlQualifications(wd.qualification_file(args.name))
    skipped: Counter[str] = Counter()
    examined = 0
    for outcome in mine(
        repo,
        config,
        runner=runner,
        executor=executor,
        scratch=wd.scratch_dir,
        pool=args.pool,
        target_count=args.target,
        max_candidates=args.max_candidates,
        known=known,
        gold=not args.no_gold,
        timeout=args.timeout,
        ref=args.ref,
        on_event=on_event,
        # the deployment's dependency provider (CRB_PROVISION__*), as the worker's mine
        deps=deps_provider(executor),
    ):
        examined += 1
        if outcome.qualification is not None:
            # the record, qualified or not, in the mine's own posture (ADR-0019)
            quals.append(outcome.qualification)
        if outcome.task is None:
            skipped[outcome.skipped_reason or "unqualified"] += 1
            continue
        # Append as we go so an interrupted run keeps what it proved.
        wd.append_tasks(args.name, [outcome.task])
        found.append(outcome.task.task_id)

    out: dict[str, Any] = {
        "repo": config.name,
        "pool": args.pool,
        "examined": examined,
        "found": len(found),
        "skipped": dict(skipped),
        "known_before": len(known),
        "tasks": found,
        "file": str(wd.task_file(args.name)),
        "gold_checked": not args.no_gold,
        "executor": executor.describe(),
    }
    if args.json:
        print_json(out)
    else:
        lines = [
            f"{config.name} [{args.pool}]: examined {examined}, found {len(found)} "
            f"(known before: {len(known)}) -> {out['file']}"
        ]
        lines += [f"  skipped {n}: {reason}" for reason, n in skipped.most_common()]
        lines += [f"  + {t[:10]}" for t in found]
        print_lines(lines)
    return EXIT_OK
