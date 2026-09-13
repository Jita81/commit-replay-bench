"""``crb config`` — show where state lives and what the defaults are."""

from __future__ import annotations

import argparse
import os
from typing import Any

from crb.cli.commands import (
    DEFAULT_WORKDIR,
    EXIT_OK,
    WORKDIR_ENV,
    add_common,
    executor_defaults,
    print_json,
    print_lines,
    workdir_of,
)
from crb.core.routing import DEFAULT_POLICY
from crb.core.runners import runner_names
from crb.core.version import APPARATUS_VERSION, __version__


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("config", help="show the effective configuration")
    cs = p.add_subparsers(dest="config_cmd", metavar="<subcommand>")
    show = cs.add_parser("show", help="workdir, ledger path, executor defaults, versions")
    add_common(show)
    show.set_defaults(func=cmd_show)
    p.set_defaults(func=lambda args: _usage(p))


def _usage(p: argparse.ArgumentParser) -> int:
    p.print_help()
    return 2


def describe(args: argparse.Namespace) -> dict[str, Any]:
    wd = workdir_of(args)
    source = (
        "--workdir"
        if getattr(args, "workdir", None)
        else (
            f"${WORKDIR_ENV}" if os.environ.get(WORKDIR_ENV) else f"default (./{DEFAULT_WORKDIR})"
        )
    )
    return {
        **wd.describe(),
        "workdir_source": source,
        "repos": wd.repo_names(),
        "executor": executor_defaults(),
        "runners": list(runner_names()),
        "routing_policy": DEFAULT_POLICY.to_dict(),
        "crb_version": __version__,
        "apparatus_version": APPARATUS_VERSION,
    }


def cmd_show(args: argparse.Namespace) -> int:
    d = describe(args)
    if args.json:
        print_json(d)
    else:
        print_lines(
            [
                f"workdir            {d['workdir']} ({d['workdir_source']}; exists={d['exists']})",
                f"ledger             {d['ledger']}",
                f"repos dir          {d['repos_dir']} ({len(d['repos'])} registered)",
                f"tasks dir          {d['tasks_dir']}",
                f"evidence dir       {d['evidence_dir']}",
                f"scratch dir        {d['scratch_dir']}",
                f"executor default   {d['executor']['default']} (kinds: {', '.join(d['executor']['kinds'])})",
                f"docker defaults    {d['executor']['docker']}",
                f"runners            {', '.join(d['runners'])}",
                f"routing policy     {d['routing_policy']}",
                f"crb version        {d['crb_version']}",
                f"apparatus version  {d['apparatus_version']}",
            ]
        )
    return EXIT_OK
