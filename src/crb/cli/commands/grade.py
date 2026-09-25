"""``crb prep`` / ``crb grade`` — prepare a trial worktree, then grade it under the four belts.

The lifecycle of one trial is::

    crb prep  <repo> <task> --dest <wt> [--mode sighted|blind]   # parent (+ tests, if sighted)
    …the builder edits <wt>…
    crb grade <repo> <task> --worktree <wt> [--mode …] [--ledger]  # four belts → verdict

``grade`` never writes a clean row without an evidence pack: with ``--ledger`` the
pack is written under ``<workdir>/evidence/<pack_hash>.json`` first and the row
carries its hash.

Navigation
----------
What it is:   ``crb prep`` / ``crb grade`` — the manual trial lifecycle: make a worktree at
              the task's parent, let a builder edit it, grade it under the belts.
What it does: ``prep`` creates the worktree and overlays the target tests only in sighted
              mode; ``grade`` refuses any worktree whose HEAD is not the task's parent (a
              harness error, never a verdict), runs the core grader, and with ``--ledger``
              writes the evidence pack FIRST and then the row that carries its hash. Exit
              0 clean, 1 not clean / disqualified, 2 harness error.
How:          ``_load`` → ``_worktree_for`` (integrity) → ``grade`` → ``EvidencePack`` →
              ``write_pack`` → ``grade_row_from_result`` → ``JsonlLedger.append``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md,
              docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/core/grade.py (the grader), src/crb/core/workspace.py (``Workspace``
              create / overlay), src/crb/core/evidence.py (``EvidencePack`` / stamps),
              src/crb/core/ledger.py (``grade_row_from_result`` — the ONE row mapping),
              src/crb/cli/commands/repo.py (``bound_runner``), src/crb/core/run.py (the
              automated equivalent the worker uses)
Tested by:    tests/test_cli.py
Touch when:   never for a new repository; when the ledger row or pack gains a field (the
              mapping lives in the core — this file only passes flags through).
Claims:       A clean exit here is one trial's mechanical verdict; a claim about a cell
              needs the ledger and ``crb route``
              (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
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
    Workdir,
    add_common,
    add_executor,
    build_executor,
    event_printer,
    print_json,
    print_lines,
    workdir_of,
)
from crb.cli.commands import repo as repo_cmd
from crb.core.deps import NullDepsProvider
from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack
from crb.core.execution import Executor
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED, MODES, GradeContext, GradeResult, grade
from crb.core.ledger import GradeRow, JsonlLedger, grade_row_from_result
from crb.core.posture import resolve_posture
from crb.core.qualify import (
    GoldWitness,
    JsonlQualifications,
    adhoc_context,
    context_for,
    qualify_task,
)
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb prep`` and ``crb grade``."""
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
    gp.add_argument(
        "--adhoc",
        action="store_true",
        help=(
            "grade against the task's discovery values with no witness (a quick look); "
            "never appends a row"
        ),
    )
    add_executor(gp)
    add_common(gp)
    gp.set_defaults(func=cmd_grade)


def _load(args: argparse.Namespace) -> tuple[RepoConfig, Path, TaskSpec]:
    """The repo config, its clone and the named task (prefix-resolved), or ``CliError``."""
    wd = workdir_of(args)
    config, clone = wd.require_clone(args.name)
    task = wd.find_task(args.name, args.task_id)
    return config, clone, task


def cmd_prep(args: argparse.Namespace) -> int:
    """Create the trial worktree; overlay the tests only when sighted."""
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
    """Thin wrapper over :func:`crb.core.ledger.grade_row_from_result` (the ONE mapping)."""
    return grade_row_from_result(
        result,
        task,
        pack_hash=pack_hash,
        builder=builder,
        run_id=run_id,
        trial=trial,
        actor=actor,
        language=task.language or config.language.value,
    )


def grade_context(
    wd: Workdir,
    name: str,
    config: RepoConfig,
    repo: GitRepo,
    task: TaskSpec,
    *,
    runner: BaseRunner,
    executor: Executor,
    timeout: int,
) -> tuple[TaskSpec, GradeContext]:
    """The task's grade context in the LIVE posture (ADR-0019): its latest qualification
    there from ``<workdir>/qualifications/<repo>.jsonl``. A task with no record in this
    posture is qualified first (no builder, no model spend) and the record appended; an
    unqualified one is refused with its code and what to do."""
    provider = NullDepsProvider()
    posture = resolve_posture(
        executor, runner, deps_mode=provider.mode(config, executor.name), root=repo.path
    )
    store = JsonlQualifications(wd.qualification_file(name))
    q = store.latest(task.task_id, posture.posture_id)
    if q is None:
        q = store.append(
            qualify_task(
                repo,
                config,
                task,
                posture=posture,
                deps=provider,
                runner=runner,
                executor=executor,
                scratch=wd.scratch_dir,
                timeout=timeout,
            )
        )
    if not q.is_qualified:
        raise CliError(
            f"{q.code}: {task.short_id} is not qualified in posture {posture.posture_id} "
            f"({posture.posture_class}): {q.message} — what to do: {q.fix}"
        )
    deps = provider.resolve(
        repo,
        config,
        parent=repo.parent(task.task_id),
        gold=task.task_id,
        executor_name=executor.name,
    )
    witness = GoldWitness(
        repo,
        config,
        task,
        runner=runner,
        executor=executor,
        scratch=wd.scratch_dir,
        binding=deps.gold,
        timeout=timeout,
    )
    ctx = context_for(task, posture=posture, qualification=q, deps=deps, witness=witness)
    return ctx.spec(task), ctx


def cmd_grade(args: argparse.Namespace) -> int:
    """Grade the worktree; with ``--ledger`` write the pack, then the row."""
    wd = workdir_of(args)
    config, clone, task = _load(args)
    repo = GitRepo(clone)
    ws = _worktree_for(repo, task, Path(args.worktree).expanduser().resolve())
    runner = repo_cmd.bound_runner(config, repo_cmd.env_dir_of(wd, args.name))
    executor = build_executor(args.executor, config)
    on_event = event_printer(sys.stderr) if args.events else None
    if args.adhoc and args.ledger is not None:
        raise CliError("--adhoc grades with no witness and never appends a row; drop --ledger")
    wd.scratch_dir.mkdir(parents=True, exist_ok=True)
    if args.adhoc:
        task, gctx = adhoc_context(task, executor=executor)
    else:
        task, gctx = grade_context(
            wd,
            args.name,
            config,
            repo,
            task,
            runner=runner,
            executor=executor,
            timeout=args.timeout,
        )

    result = grade(
        ws,
        task,
        ctx=gctx,
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
            apparatus=ApparatusStamp(
                runner=runner.name, executor=executor.describe(), posture=gctx.posture.to_dict()
            ),
            builder=builder,
            run_id=args.run_id,
            trial=args.trial,
            actor=args.actor,
        )
        # Pack before row: a row that cites a hash must never exist without the pack.
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
