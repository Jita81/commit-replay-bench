"""``crb repo`` — register repositories, prove their toolchain, import census configs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_NEGATIVE,
    EXIT_OK,
    CliError,
    add_common,
    add_executor,
    build_executor,
    parse_kv,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.git import GitRepo
from crb.core.legacy import import_repo_configs
from crb.core.runners import get_runner
from crb.core.spec import (
    BELT_AFFECTED_DIRS,
    BELT_BARE,
    BELT_TARGET_ONLY,
    RUNNERS,
    Language,
    RepoConfig,
)

_BELT_POLICIES = (BELT_TARGET_ONLY, BELT_AFFECTED_DIRS, BELT_BARE)


def _parse_belt_scope(value: str | None) -> str | tuple[str, ...]:
    if not value:
        return BELT_TARGET_ONLY
    v = value.strip()
    if v.upper() in _BELT_POLICIES:
        return v.upper()
    return tuple(s.strip() for s in v.split(",") if s.strip())


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("repo", help="register repos, probe toolchains, import configs")
    rs = p.add_subparsers(dest="repo_cmd", metavar="<subcommand>")

    a = rs.add_parser("add", help="register a local clone as a benchmark repo")
    a.add_argument("name", help="short id, lowercase [a-z0-9._-]")
    a.add_argument("--path", required=True, help="path to the local git clone")
    a.add_argument("--language", required=True, help="python|go|javascript|jvm|rust (or py/js/…)")
    a.add_argument(
        "--runner", default="", help=f"one of {', '.join(RUNNERS)} (default per language)"
    )
    a.add_argument("--src-prefix", default="", help="source layout prefix, e.g. src/pkg/")
    a.add_argument("--test-prefix", default="", help="test layout prefix, e.g. tests/")
    a.add_argument("--ext", default="", help="source extension (default per language)")
    a.add_argument("--test-mode", default="prefix", choices=("prefix", "suffix"))
    a.add_argument("--test-suffix", default="", help="e.g. .test.ts when --test-mode suffix")
    a.add_argument(
        "--belt-scope",
        default="",
        help="TARGET_ONLY | AFFECTED_DIRS | BARE | comma-separated explicit scopes",
    )
    a.add_argument("--probe", default="", help="known-green test scope for `crb repo probe`")
    a.add_argument("--sandbox-image", default="", help="container image for --executor docker")
    a.add_argument("--url", default="", help="upstream URL (informational)")
    a.add_argument(
        "--runner-opt",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="runner option (python=…, pythonpath_suffix=…, maven_flags=…); repeatable",
    )
    a.add_argument("--force", action="store_true", help="replace an existing registration")
    add_common(a)
    a.set_defaults(func=cmd_add)

    pr = rs.add_parser("probe", help="run the config's probe scope to prove the toolchain")
    pr.add_argument("name")
    add_executor(pr)
    add_common(pr)
    pr.set_defaults(func=cmd_probe)

    ic = rs.add_parser("import-configs", help="import a census-style configs.json")
    ic.add_argument("configs", help="path to configs.json ({name: {...}})")
    ic.add_argument(
        "--repos-dir",
        default="",
        help="directory holding one clone per repo name (<repos-dir>/<name>); omit for config-only",
    )
    ic.add_argument("--force", action="store_true", help="replace existing registrations")
    add_common(ic)
    ic.set_defaults(func=cmd_import_configs)

    ls = rs.add_parser("list", help="list registered repos")
    add_common(ls)
    ls.set_defaults(func=cmd_list)

    p.set_defaults(func=lambda args: _usage(p))


def _usage(p: argparse.ArgumentParser) -> int:
    p.print_help()
    return 2


def cmd_add(args: argparse.Namespace) -> int:
    wd = workdir_of(args)
    clone = Path(args.path).expanduser().resolve()
    if not clone.is_dir():
        raise CliError(f"--path {clone} is not a directory")
    if not GitRepo(clone).is_repo():
        raise CliError(f"--path {clone} is not a git repository")
    try:
        config = RepoConfig(
            name=args.name,
            language=Language.parse(args.language),
            runner=args.runner,
            src_prefix=args.src_prefix,
            test_prefix=args.test_prefix,
            ext=args.ext,
            test_mode=args.test_mode,
            test_suffix=args.test_suffix,
            belt_scope=_parse_belt_scope(args.belt_scope),
            probe=args.probe,
            url=args.url,
            runner_opts=parse_kv(args.runner_opt),
            sandbox_image=args.sandbox_image,
        )
    except ValueError as e:
        raise CliError(str(e)) from e
    f = wd.save_repo(config, clone, force=args.force)
    out: dict[str, Any] = {"repo": config.name, "file": str(f), "path": str(clone)}
    out["config"] = config.to_dict()
    if args.json:
        print_json(out)
    else:
        print_lines([f"registered {config.name} ({config.language.value}/{config.runner}) -> {f}"])
    return EXIT_OK


def cmd_probe(args: argparse.Namespace) -> int:
    wd = workdir_of(args)
    config, clone = wd.require_clone(args.name)
    if not config.probe:
        raise CliError(f"repo {args.name!r} has no probe scope configured (--probe on `repo add`)")
    runner = get_runner(config)
    executor = build_executor(args.executor, config)
    run = runner.run(executor, clone, (config.probe,), timeout=args.timeout)
    out = {
        "repo": config.name,
        "probe": config.probe,
        "runner": runner.name,
        "executor": executor.describe(),
        "green": run.green,
        **run.to_dict(),
    }
    if args.json:
        print_json(out)
    else:
        status = "GREEN" if run.green else "RED"
        print_lines(
            [
                f"{config.name}: probe {config.probe} -> {status} (rc={run.returncode}, "
                f"failing={len(run.failing)}, timed_out={run.timed_out}, "
                f"{run.duration_s:.1f}s)"
            ]
            + ([f"  parse_error: {run.parse_error}"] if run.parse_error else [])
            + [f"  {f}" for f in sorted(run.failing)[:20]]
        )
    return EXIT_OK if run.green else EXIT_NEGATIVE


def cmd_import_configs(args: argparse.Namespace) -> int:
    wd = workdir_of(args)
    src = Path(args.configs).expanduser()
    if not src.is_file():
        raise CliError(f"{src} is not a file")
    configs = import_repo_configs(src)
    repos_dir = Path(args.repos_dir).expanduser().resolve() if args.repos_dir else None
    written: list[dict[str, Any]] = []
    skipped: list[str] = []
    for name, config in configs.items():
        clone = (repos_dir / name) if repos_dir else None
        if clone is not None and not clone.is_dir():
            clone = None
        if wd.repo_file(name).exists() and not args.force:
            skipped.append(name)
            continue
        f = wd.save_repo(config, clone, force=args.force)
        written.append({"repo": name, "file": str(f), "path": str(clone) if clone else ""})
    out = {"imported": written, "skipped_existing": skipped, "source": str(src)}
    if args.json:
        print_json(out)
    else:
        print_lines(
            [f"imported {len(written)} config(s) from {src}; skipped {len(skipped)} existing"]
        )
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    wd = workdir_of(args)
    rows: list[dict[str, Any]] = []
    for name in wd.repo_names():
        config, path = wd.load_repo(name)
        rows.append(
            {
                "repo": name,
                "language": config.language.value,
                "runner": config.runner,
                "path": str(path) if path else "",
                "tasks": len(wd.load_tasks(name)),
                "sandbox_image": config.sandbox_image,
            }
        )
    if args.json:
        print_json({"workdir": str(wd.root), "repos": rows})
    else:
        print_lines(
            table(
                ("repo", "language", "runner", "tasks", "path"),
                [(r["repo"], r["language"], r["runner"], r["tasks"], r["path"]) for r in rows],
            )
        )
    return EXIT_OK
