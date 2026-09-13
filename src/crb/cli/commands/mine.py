"""``crb mine`` — find replayable commits, prove them RED, capture baselines, gold-check."""

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
    event_printer,
    print_json,
    print_lines,
    workdir_of,
)
from crb.cli.commands import repo as repo_cmd
from crb.core.git import GitRepo
from crb.core.mine import mine
from crb.core.spec import POOL_HARD, POOL_STANDARD


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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
    ):
        examined += 1
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
