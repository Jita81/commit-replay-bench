"""``crb repo`` — register repositories, set up their environment, prove their
toolchain, import census configs.

``crb repo setup`` is the one network phase: it installs the repository's test
dependencies through the runner (a venv under ``<workdir>/envs/<name>`` for
Python, ``node_modules`` in the clone, warm module caches for Go / Maven /
Cargo) and records every step. ``crb repo probe`` runs it first whenever the
environment is not ready.

Navigation
----------
What it is:   ``crb repo add | setup | probe | import-configs | list`` — register a
              repository, build its test environment, prove its toolchain.
What it does: ``add`` validates the config (belt scope, runner, probe scope …) and records
              the clone path — or clones by URL under the same policy the worker uses;
              ``setup`` is the ONE network phase (installs test dependencies into
              ``<workdir>/envs/<name>`` through the runner and records it); ``probe`` runs
              the known-green scope in the executor (auto-running setup when the
              environment is not ready) and exits 1 when it is red; ``bound_runner`` is how
              every other verb gets a runner on that environment.
How:          ``parse_kv`` for ``--runner-opts``; ``RepoConfig`` → ``Workdir.save_repo``;
              ``get_runner(config)`` with ``env_dir`` bound → ``runner.setup`` /
              ``runner.run`` under ``build_executor``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/spec.py (``RepoConfig`` and the belt-scope vocabulary),
              src/crb/core/runners/base.py (``setup`` / ``environment_ready`` / ``run``),
              src/crb/core/git.py (``clone_repo`` and the URL policy), src/crb/core/legacy.py
              (``import_repo_configs``), src/crb/cli/commands/mine.py +
              src/crb/cli/commands/grade.py (call ``bound_runner``),
              docs/OPERATOR.md#2-configure-a-repository (the flags, per language)
Tested by:    tests/test_cli.py, tests/test_cli_repo_setup.py, tests/test_cli_repo_url.py
Touch when:   THIS is the verb a new repository starts with — as configuration
              (docs/OPERATOR.md#21-environment-setup--the-only-network-phase), not code;
              edit the file when ``RepoConfig`` gains a field (add the flag and the
              OPERATOR entry) or a runner gains a setup step worth surfacing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_NEGATIVE,
    EXIT_OK,
    CliError,
    Workdir,
    add_common,
    add_executor,
    build_executor,
    parse_kv,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.git import (
    DEFAULT_CLONE_TIMEOUT_S,
    CloneUrlError,
    GitError,
    GitRepo,
    clone_repo,
    redact_url,
    validate_clone_url,
)
from crb.core.legacy import import_repo_configs
from crb.core.runners import BaseRunner, SetupResult, get_runner
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
    """``--belt-scope``: a named policy (``BARE`` / ``TARGET_ONLY`` / ``AFFECTED_DIRS``,
    case-insensitive; default ``TARGET_ONLY``) or a comma-separated list of directories."""
    if not value:
        return BELT_TARGET_ONLY
    v = value.strip()
    if v.upper() in _BELT_POLICIES:
        return v.upper()
    return tuple(s.strip() for s in v.split(",") if s.strip())


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb repo add | setup | probe | import-configs | list``."""
    p = sub.add_parser("repo", help="register repos, probe toolchains, import configs")
    rs = p.add_subparsers(dest="repo_cmd", metavar="<subcommand>")

    a = rs.add_parser("add", help="register a benchmark repo (a local clone, or clone it by URL)")
    a.add_argument("name", help="short id, lowercase [a-z0-9._-]")
    a.add_argument(
        "--path",
        default="",
        help="path to an existing local git clone (or omit and give --url to clone now)",
    )
    a.add_argument(
        "--clone-timeout",
        type=int,
        default=DEFAULT_CLONE_TIMEOUT_S,
        help="wall clock for `git clone` when --url is used without --path (seconds)",
    )
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
    a.add_argument(
        "--url",
        default="",
        help=(
            "git URL (https:// or ssh://); with --path it is recorded as the upstream, "
            "without --path the repo is cloned now into <workdir>/repos/<name> (full history)"
        ),
    )
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

    su = rs.add_parser(
        "setup",
        help="install the repo's test dependencies (the only network phase; env under <workdir>/envs/<name>)",
    )
    su.add_argument("name")
    add_executor(su)
    add_common(su)
    su.set_defaults(func=cmd_setup)

    pr = rs.add_parser(
        "probe",
        help="run the config's probe scope to prove the toolchain (runs setup first if not ready)",
    )
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
    """``crb repo`` with no subcommand: help + usage-error exit."""
    p.print_help()
    return 2


def _clone_for_add(args: argparse.Namespace, wd: Workdir) -> tuple[Path, str]:
    """``--url`` without ``--path``: clone into ``<workdir>/repos/<name>`` now.

    The same :func:`crb.core.git.clone_repo` the worker uses: policy-checked URL
    (https/ssh; ``file://`` only under ``CRB_ALLOW_LOCAL_CLONE=1``), full history,
    atomic, idempotent (an existing clone at the destination is reused). Returns
    ``(clone_path, head_sha)``; the URL in any error is redacted.
    """
    dest = wd.repos_dir / args.name
    try:
        validate_clone_url(args.url)
    except CloneUrlError as e:
        raise CliError(f"--url: {e}") from e
    print_lines([f"cloning {redact_url(args.url)} -> {dest} …"], stream=sys.stderr)
    try:
        head = clone_repo(args.url, dest, timeout=max(1, int(args.clone_timeout)))
    except (CloneUrlError, GitError) as e:
        raise CliError(f"clone failed: {e}") from e
    return dest, head


def cmd_add(args: argparse.Namespace) -> int:
    """Register a repo from ``--path`` (an existing clone) or ``--url`` (cloned now);
    the config is validated by ``RepoConfig`` before anything is written."""
    wd = workdir_of(args)
    head = ""
    if args.path:
        clone = Path(args.path).expanduser().resolve()
        if not clone.is_dir():
            raise CliError(f"--path {clone} is not a directory")
        if not GitRepo(clone).is_repo():
            raise CliError(f"--path {clone} is not a git repository")
    elif args.url:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", args.name):
            raise CliError(f"repo name {args.name!r} must be lowercase [a-z0-9._-], ≤64 chars")
        if wd.repo_file(args.name).exists() and not args.force:
            raise CliError(
                f"repo {args.name!r} already exists at {wd.repo_file(args.name)} (use --force to replace)"
            )
        clone, head = _clone_for_add(args, wd)
    else:
        raise CliError("one of --path (an existing clone) or --url (clone it now) is required")
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
    if head:
        out["cloned"] = {"url": redact_url(args.url), "head": head}
    out["config"] = config.to_dict()
    if args.json:
        print_json(out)
    else:
        lines = [f"registered {config.name} ({config.language.value}/{config.runner}) -> {f}"]
        if head:
            lines.insert(0, f"cloned {redact_url(args.url)} -> {clone} (HEAD {head[:12]})")
        print_lines(lines)
    return EXIT_OK


# ---------------------------------------------------------------------------
# environment (setup)
# ---------------------------------------------------------------------------


def env_dir_of(wd: Workdir, name: str) -> Path:
    """The repo's environment directory: what its config file records, else the
    default ``<workdir>/envs/<name>``."""
    try:
        d = json.loads(wd.repo_file(name).read_text(encoding="utf-8"))
        recorded = str(d.get("env_dir") or "")
    except (OSError, ValueError):
        recorded = ""
    return Path(recorded) if recorded else wd.root / "envs" / name


def record_env_dir(wd: Workdir, name: str, env_dir: Path) -> None:
    """Store ``env_dir`` alongside the config (``RepoConfig.from_dict`` ignores it)."""
    f = wd.repo_file(name)
    d = json.loads(f.read_text(encoding="utf-8"))
    d["env_dir"] = str(env_dir)
    f.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bound_runner(config: RepoConfig, env_dir: Path) -> BaseRunner:
    """The repo's runner with ``env_dir`` bound, so a pytest runner without
    ``runner_opts.python`` runs on the venv ``crb repo setup`` built. Every command
    that runs the repo's tests should build its runner here."""
    runner = get_runner(config)
    runner.env_dir = env_dir
    return runner


def _setup_lines(name: str, result: SetupResult) -> list[str]:
    """The human rendering of a setup result: one line per step, tails on failure."""
    lines = [
        f"{name}: setup -> {'READY' if result.ok else 'FAILED'} ({result.note}; "
        f"{len(result.steps)} step(s), {result.duration_s:.1f}s)"
    ]
    for i, step in enumerate(result.steps, 1):
        how = "timed out" if step.timed_out else f"rc={step.rc}"
        lines.append(f"  [{i}] {how} {' '.join(step.argv)}")
        if not step.ok and step.tail:
            lines.extend("      " + t for t in step.tail.splitlines()[-12:])
    return lines


def cmd_setup(args: argparse.Namespace) -> int:
    """Build the repo's test environment through its runner; exit 1 when a step failed."""
    wd = workdir_of(args)
    config, clone = wd.require_clone(args.name)
    env_dir = env_dir_of(wd, args.name)
    runner = bound_runner(config, env_dir)
    executor = build_executor(args.executor, config)
    result = runner.setup(executor, clone, env_dir=env_dir, timeout=args.timeout)
    record_env_dir(wd, args.name, env_dir)
    out: dict[str, Any] = {
        "repo": config.name,
        "runner": runner.name,
        "executor": executor.describe(),
        "env_dir": str(env_dir),
        "ready": runner.environment_ready(clone, env_dir),
        **result.to_dict(),
    }
    if args.json:
        print_json(out)
    else:
        print_lines(_setup_lines(config.name, result))
    return EXIT_OK if result.ok else EXIT_NEGATIVE


def cmd_probe(args: argparse.Namespace) -> int:
    """Run the known-green probe scope; auto-setup first (host executor only — a docker
    sandbox carries its own toolchain); exit 1 when red or setup failed."""
    wd = workdir_of(args)
    config, clone = wd.require_clone(args.name)
    if not config.probe:
        raise CliError(f"repo {args.name!r} has no probe scope configured (--probe on `repo add`)")
    env_dir = env_dir_of(wd, args.name)
    runner = bound_runner(config, env_dir)
    executor = build_executor(args.executor, config)
    setup: SetupResult | None = None
    if executor.name != "docker" and not runner.environment_ready(clone, env_dir):
        setup = runner.setup(executor, clone, env_dir=env_dir, timeout=args.timeout)
        record_env_dir(wd, args.name, env_dir)
        if not setup.ok:
            out_fail: dict[str, Any] = {
                "repo": config.name,
                "probe": config.probe,
                "runner": runner.name,
                "executor": executor.describe(),
                "green": False,
                "setup": setup.to_dict(),
            }
            if args.json:
                print_json(out_fail)
            else:
                print_lines(
                    [
                        *_setup_lines(config.name, setup),
                        f"{config.name}: probe not run (setup failed)",
                    ]
                )
            return EXIT_NEGATIVE
    run = runner.run(executor, clone, (config.probe,), timeout=args.timeout)
    out = {
        "repo": config.name,
        "probe": config.probe,
        "runner": runner.name,
        "executor": executor.describe(),
        "green": run.green,
        **run.to_dict(),
    }
    if setup is not None:
        out["setup"] = setup.to_dict()
    if args.json:
        print_json(out)
    else:
        status = "GREEN" if run.green else "RED"
        print_lines(
            (_setup_lines(config.name, setup) if setup is not None else [])
            + [
                f"{config.name}: probe {config.probe} -> {status} (rc={run.returncode}, "
                f"failing={len(run.failing)}, timed_out={run.timed_out}, "
                f"{run.duration_s:.1f}s)"
            ]
            + ([f"  parse_error: {run.parse_error}"] if run.parse_error else [])
            + [f"  {f}" for f in sorted(run.failing)[:20]]
        )
    return EXIT_OK if run.green else EXIT_NEGATIVE


def cmd_import_configs(args: argparse.Namespace) -> int:
    """Register every repo of a census ``configs.json`` (clone paths from ``--repos-dir``
    when present); existing configs are skipped unless ``--force``."""
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
    """Registered repos with language, runner, clone path and task count."""
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
