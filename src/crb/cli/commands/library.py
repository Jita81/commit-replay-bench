"""``crb library`` — what the library's miners would propose from a repository, at no model cost.

``crb library miners`` lists the registry. ``crb library mine <repo>`` pins the repository's
clone at one commit and runs the miners over it, with the workdir's mined tasks and graded rows
for the change profile, and prints every proposal and every outcome. The command writes
nothing: the workdir holds no library, and the library's two-person record lives in the
server's store — ``POST /library/{repo}/mine`` runs the same miners and appends their
proposals there, unsigned.

Navigation
----------
What it is:   The ``crb library`` verbs: ``miners`` (the registry) and ``mine`` (a dry run of
              the miners over a workdir repository at a pinned commit).
What it does: Resolves the repository's clone, pins ``--commit`` (default ``HEAD``) to its full
              sha, feeds the workdir's tasks and ledger rows to the run, and prints the
              proposals and outcomes as a table or as JSON (``--json``); exits 0, or 2 for an
              unknown repository, miner or commit.
How:          ``Workdir.require_clone`` → ``GitRepo`` → ``source_from_git`` → ``run_miners``
              with no standing library → ``print_json`` / ``table``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/core/miners.py (the registry and the run), src/crb/cli/commands/__init__.py
              (the workdir and the output helpers), src/crb/cli/main.py (registers the verb),
              src/crb/server/routes/library.py (the same run, appended to the library)
Tested by:    tests/test_cli_library.py
Touch when:   never for a new repository; a miner is added in src/crb/core/miners.py and
              appears here by itself.
"""

from __future__ import annotations

import argparse
from typing import Any

from crb.cli.commands import (
    EXIT_OK,
    CliError,
    add_common,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.git import GitError, GitRepo
from crb.core.ledger import JsonlLedger
from crb.core.miners import (
    GradedRow,
    MinedTask,
    describe_miners,
    miner_names,
    run_miners,
    source_from_git,
)


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb library miners`` and ``crb library mine``."""
    p = sub.add_parser("library", help="the context library's miners (proposals, never signed)")
    verbs = p.add_subparsers(dest="library_command", metavar="<verb>", required=True)
    m = verbs.add_parser("miners", help="list the registered miners, in the order a run applies")
    add_common(m)
    m.set_defaults(func=cmd_miners)
    r = verbs.add_parser(
        "mine", help="what the miners would propose from a repository at a pinned commit"
    )
    r.add_argument("repo", help="a repository added with `crb repo add`")
    r.add_argument("--commit", default="HEAD", help="the commit to pin (default HEAD)")
    r.add_argument(
        "--miner",
        action="append",
        default=[],
        help="run only this miner (repeatable; default every registered miner)",
    )
    add_common(r)
    r.set_defaults(func=cmd_mine)


def cmd_miners(args: argparse.Namespace) -> int:
    rows = describe_miners()
    if args.json:
        print_json({"miners": rows})
        return EXIT_OK
    print_lines(
        table(
            ["miner", "proposer", "kinds", "reads"],
            [[r["name"], r["proposer"], ", ".join(r["kinds"]), r["reads"]] for r in rows],
        )
    )
    return EXIT_OK


def cmd_mine(args: argparse.Namespace) -> int:
    """A dry run: every draft is compared with an empty library, so the output is what a
    first ``POST /library/{repo}/mine`` would propose."""
    wd = workdir_of(args)
    _config, path = wd.require_clone(args.repo)
    unknown = [n for n in args.miner if n not in miner_names()]
    if unknown:
        raise CliError(f"no miner registered as {', '.join(unknown)}; one of {miner_names()}")
    commit = str(args.commit)
    if commit.startswith("-"):
        raise CliError(f"--commit names a commit, never an option: {commit!r}")
    tasks = [
        MinedTask(
            task_id=t.task_id,
            capability_class=t.capability_class,
            size=t.size,
            src_files=tuple(t.src_files),
            test_files=tuple(t.test_files),
        )
        for t in wd.load_tasks(args.repo)
    ]
    graded = [
        GradedRow(row_hash=r.row_hash, task_id=r.task_id, clean=r.clean)
        for r in JsonlLedger(wd.ledger_path).rows()
        if r.repo == args.repo and r.row_hash
    ]
    try:
        source = source_from_git(GitRepo(path), args.repo, commit, tasks=tasks, graded=graded)
    except GitError as e:
        raise CliError(f"{commit} names no commit of {args.repo}'s clone at {path}") from e
    run = run_miners(source, names=list(dict.fromkeys(args.miner)) or None)
    out: dict[str, Any] = run.to_dict()
    out["writes"] = "nothing: POST /library/{repo}/mine appends these proposals, unsigned"
    if args.json:
        print_json(out)
        return EXIT_OK
    counts = ", ".join(f"{k} {v}" for k, v in run.counts().items() if v)
    print_lines([f"{args.repo} at {run.commit} — {counts or 'nothing found'}"])
    print_lines(
        table(
            ["outcome", "miner", "subject", "reason"],
            [[o.outcome, o.miner, o.subject, o.reason] for o in run.outcomes],
        )
    )
    print_lines(["Nothing was written: the server's POST /library/{repo}/mine appends them."])
    return EXIT_OK
