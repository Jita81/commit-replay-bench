"""``crb prep`` / ``crb grade`` — prepare a trial worktree, then grade it under the four belts.

The lifecycle of one trial is::

    crb prep  <repo> <task> --dest <wt> [--mode sighted|blind]   # parent (+ tests, if sighted)
    …the builder edits <wt>…
    crb grade <repo> <task> --worktree <wt> [--mode …] [--ledger]  # four belts → verdict

``grade`` never writes a clean row without an evidence pack: with ``--ledger`` the
pack is written under ``<workdir>/evidence/<pack_hash>.json`` first and the row
carries its hash.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_ERROR,
    EXIT_NEGATIVE,
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
from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED, MODES, GradeResult, grade
from crb.core.ledger import BELT_SET_V4, PROCESS_REPLAY, GradeRow, JsonlLedger
from crb.core.runners import get_runner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    pp = sub.add_parser("prep", help="create a trial worktree at the task's parent")
    pp.add_argument("name", help="registered repo")
    pp.add_argument("task_id", help="task sha (or unique prefix ≥7)")
    pp.add_argument("--dest", required=True, help="worktree path to create (must not exist)")
    pp.add_argument("--mode", choices=MODES, default=MODE_SIGHTED)
    pp.add_argument("--force", action="store_true", help="replace an existing worktree at --dest")
    add_common(pp)
    pp.set_defaults(func=cmd_prep)

    gp = sub.add_parser("grade", help="grade a trial worktree under the four belts")
    gp.add_argument("name", help="registered repo")
    gp.add_argument("task_id", help="task sha (or unique prefix ≥7)")
    gp.add_argument("--worktree", required=True, help="the trial worktree (from `crb prep`)")
    gp.add_argument("--mode", choices=MODES, default=MODE_SIGHTED)
    gp.add_argument(
        "--ledger",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="append a GradeRow (+ evidence pack) to PATH (default <workdir>/ledger.jsonl)",
    )
    gp.add_argument("--builder", default="", help="builder name for the cell key")
    gp.add_argument("--model", default="", help="model id for the cell key")
    gp.add_argument("--provider", default="", help="provider for the cell key")
    gp.add_argument("--run-id", default="", help="campaign / wave id")
    gp.add_argument("--trial", default="", help="trial id within the run")
    gp.add_argument("--actor", default="", help="who ran this (audit)")
    gp.add_argument("--events", action="store_true", help="stream grade.* events on stderr")
    add_executor(gp)
    add_common(gp)
    gp.set_defaults(func=cmd_grade)


def _load(args: argparse.Namespace) -> tuple[RepoConfig, Path, TaskSpec]:
    wd = workdir_of(args)
    config, clone = wd.require_clone(args.name)
    task = wd.find_task(args.name, args.task_id)
    return config, clone, task


def cmd_prep(args: argparse.Namespace) -> int:
    config, clone, task = _load(args)
    dest = Path(args.dest).expanduser().resolve()
    if dest.exists() and not args.force:
        raise CliError(f"--dest {dest} already exists (use --force to replace it)")
    repo = GitRepo(clone)
    ws = Workspace.create(repo, task.task_id, dest, config=config)
    overlaid: list[str] = []
    if args.mode == MODE_SIGHTED:
        ws.overlay_tests(task.test_files)
        overlaid = list(task.test_files)
    out = {
        "repo": config.name,
        "task_id": task.task_id,
        "parent": ws.parent,
        "worktree": str(ws.root),
        "mode": args.mode,
        "tests_overlaid": overlaid,
        "target_tests": list(task.target_tests),
        "subject": task.subject,
    }
    if args.json:
        print_json(out)
    else:
        print_lines(
            [
                f"prepared {task.short_id} ({config.name}) at {ws.root} [{args.mode}] "
                f"parent={ws.parent[:10]} tests_overlaid={len(overlaid)}"
            ]
        )
    return EXIT_OK


def _worktree_for(repo: GitRepo, task: TaskSpec, path: Path) -> Workspace:
    """A worktree is only gradeable if it IS a worktree of the clone at the task's parent.
    Anything else is a harness error, never a verdict."""
    if not path.is_dir():
        raise CliError(f"--worktree {path} is not a directory")
    wt = GitRepo(path)
    if not wt.is_repo():
        raise CliError(f"--worktree {path} is not a git worktree")
    parent = repo.parent(task.task_id)
    head = wt.rev_parse("HEAD")
    if head != parent:
        raise CliError(
            f"--worktree HEAD {head[:10]} is not the task's parent {parent[:10]}; "
            f"prepare it with `crb prep`"
        )
    return Workspace(repo, path, sha=task.task_id, parent=parent)


def row_from_result(
    result: GradeResult,
    task: TaskSpec,
    config: RepoConfig,
    *,
    pack_hash: str,
    builder: BuilderRef,
    run_id: str,
    trial: str,
    actor: str,
) -> GradeRow:
    """Reduce a :class:`GradeResult` + its pack hash to the ledger row.

    The row's ``clean`` is the result's ``clean``; the write-time invariant in
    :class:`GradeRow` re-checks it against the belts, so a disagreement between
    the grader and the ledger is impossible to persist.
    """
    return GradeRow(
        repo=result.repo,
        task_id=result.task_id,
        clean=result.clean,
        tests_unmodified=result.belts.tests_unmodified,
        target_green=result.belts.target_green,
        no_new_failures=result.belts.no_new_failures,
        source_changed=result.belts.source_changed,
        capability_class=task.capability_class,
        size=task.size,
        language=task.language or config.language.value,
        pool=task.pool,
        mode=result.mode,
        process_step=PROCESS_REPLAY,
        builder=builder.name,
        model=builder.model,
        provider=builder.provider,
        run_id=run_id,
        trial=trial,
        actor=actor,
        disqualified=result.disqualified,
        dq_reason=result.dq_reason,
        error=result.error,
        new_failures_count=len(result.new_failures),
        attempts=builder.attempts,
        cost_usd=builder.cost_usd,
        tokens_in=builder.tokens_in,
        tokens_out=builder.tokens_out,
        latency_s=builder.latency_s,
        gold_clean=task.gold_clean,
        evidence_pack_hash=pack_hash,
        apparatus_version=APPARATUS_VERSION,
        belt_set=BELT_SET_V4,
        provenance="measured",
    )


def cmd_grade(args: argparse.Namespace) -> int:
    wd = workdir_of(args)
    config, clone, task = _load(args)
    repo = GitRepo(clone)
    ws = _worktree_for(repo, task, Path(args.worktree).expanduser().resolve())
    runner = get_runner(config)
    executor = build_executor(args.executor, config)
    on_event = event_printer(sys.stderr) if args.events else None

    result = grade(
        ws,
        task,
        config=config,
        runner=runner,
        executor=executor,
        mode=args.mode,
        timeout=args.timeout,
        on_event=on_event,
    )
    out: dict[str, Any] = result.to_dict()

    if args.ledger is not None:
        ledger_path = Path(args.ledger).expanduser() if args.ledger else wd.ledger_path
        builder = BuilderRef(
            name=args.builder, model=args.model, provider=args.provider, mode=args.mode
        )
        pack = EvidencePack(
            task=task,
            grade=result,
            apparatus=ApparatusStamp(runner=runner.name, executor=executor.describe()),
            builder=builder,
            run_id=args.run_id,
            trial=args.trial,
            actor=args.actor,
        )
        pack_path = wd.write_pack(pack.pack_hash, pack.to_dict())
        row = row_from_result(
            result,
            task,
            config,
            pack_hash=pack.pack_hash,
            builder=builder,
            run_id=args.run_id,
            trial=args.trial,
            actor=args.actor,
        )
        chained = JsonlLedger(ledger_path).append(row)
        out["evidence_pack_hash"] = pack.pack_hash
        out["evidence_pack"] = str(pack_path)
        out["ledger"] = str(ledger_path)
        out["row_hash"] = chained.row_hash

    if args.json:
        print_json(out)
    else:
        verdict = (
            "CLEAN" if result.clean else ("DISQUALIFIED" if result.disqualified else "NOT CLEAN")
        )
        if result.error:
            verdict = "HARNESS ERROR"
        lines = [
            f"{task.short_id} ({config.name}) [{result.mode}]: {verdict}",
            "  belts: " + ", ".join(f"{k}={v}" for k, v in result.belts.to_dict().items()),
        ]
        if result.note:
            lines.append(f"  note: {result.note}")
        if result.dq_reason:
            lines.append(f"  dq_reason: {result.dq_reason}")
        if result.error:
            lines.append(f"  error: {result.error}")
        if result.new_failures:
            lines.append(
                f"  new failures ({len(result.new_failures)}): "
                + ", ".join(result.new_failures[:10])
            )
        if "row_hash" in out:
            lines.append(
                f"  ledgered: {out['ledger']} row={out['row_hash'][:12]} pack={out['evidence_pack_hash'][:12]}"
            )
        print_lines(lines)

    if result.error:
        return EXIT_ERROR
    return EXIT_OK if result.clean else EXIT_NEGATIVE
