"""``crb serve`` / ``crb worker`` / ``crb doctor`` / ``crb migrate`` — the service verbs.

These import the server layer lazily: the core CLI must keep working on a host
that has only the base package installed (``pip install commit-replay-bench``
without the ``[server]`` extra).

Navigation
----------
What it is:   ``crb serve | worker | migrate | doctor`` — the service verbs, importing the
              server layer lazily so the base CLI works without the ``[server]`` extra.
What it does: ``serve`` hands off to uvicorn; ``worker`` forwards its flags to the worker
              entry point; ``migrate`` runs Alembic to head; ``doctor`` aggregates the
              toolchain, docker, builder, Claude Code login and database probes into one
              report (exit 1 only on ``down``). ``probe_claude_code`` never prints a token
              — a fingerprint of at most four characters.
How:          Each ``cmd_*`` imports inside the function and turns ``ImportError`` into a
              ``CliError`` naming the extra; ``doctor`` = ``probes.aggregate`` over the
              observability probes plus the store's ``assert_append_only``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/main.py (``serve``), src/crb/server/worker_main.py (``main``),
              src/crb/store/migrate.py (``upgrade``), src/crb/observability/probes.py (the
              probe vocabulary and ``aggregate``), src/crb/builders/claude_code.py
              (``auth_status`` / ``verify_login``), docs/OPERATOR.md#1-install
Tested by:    tests/test_cli_doctor.py, tests/test_cli.py
Touch when:   never for a new repository; when a worker flag is added (mirror it in the
              forwarding table and in src/crb/server/worker_main.py); when a new probe
              should appear in ``doctor``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from crb.cli.commands import EXIT_OK, CliError

if TYPE_CHECKING:
    from crb.observability.probes import ProbeResult

_SERVER_HINT = "the server layer is not installed — `pip install 'commit-replay-bench[server]'`"


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb serve``, ``crb worker``, ``crb migrate`` and ``crb doctor``."""
    serve = sub.add_parser("serve", help="run the HTTP API (+ the UI when built)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--database-url", default=None, help="overrides CRB_DATABASE_URL")
    serve.set_defaults(func=cmd_serve)

    worker = sub.add_parser("worker", help="run the job worker (mine / replay / oracle / probe)")
    worker.add_argument("--database-url", default=None)
    worker.add_argument("--home", default=None, help="evidence + events dir (CRB_HOME)")
    worker.add_argument("--executor", choices=("local", "docker"), default=None)
    worker.add_argument("--image", default=None, help="sandbox image for --executor docker")
    worker.add_argument("--worker-id", default=None)
    worker.add_argument("--poll", type=float, default=None, help="seconds between queue polls")
    worker.add_argument("--once", action="store_true", help="process one job then exit")
    worker.set_defaults(func=cmd_worker)

    migrate = sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    migrate.add_argument("--database-url", default=None)
    migrate.set_defaults(func=cmd_migrate)

    doctor = sub.add_parser(
        "doctor", help="check toolchains, sandbox, builders, Claude Code login, database"
    )
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--database-url", default=None)
    doctor.add_argument(
        "--verify",
        action="store_true",
        help="also run the Claude Code login probe (one no-tool Haiku turn; ~2 s when invalid)",
    )
    doctor.set_defaults(func=cmd_doctor)


def cmd_serve(args: argparse.Namespace) -> int:
    """Block in uvicorn (``--database-url`` becomes ``CRB_DATABASE_URL`` for the app)."""
    if args.database_url:
        os.environ["CRB_DATABASE_URL"] = args.database_url
    try:
        from crb.server.main import serve
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    serve(host=args.host, port=args.port)
    return EXIT_OK


def cmd_worker(args: argparse.Namespace) -> int:
    """Forward the flags to the worker entry point (which owns the defaults)."""
    try:
        import crb.server.worker_main as worker_main_mod
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    argv: list[str] = []
    for flag, value in (
        ("--database-url", args.database_url),
        ("--home", args.home),
        ("--executor", args.executor),
        ("--image", args.image),
        ("--worker-id", args.worker_id),
        ("--poll", args.poll),
    ):
        if value is not None:
            argv += [flag, str(value)]
    if args.once:
        argv.append("--once")
    return int(worker_main_mod.main(argv))


def cmd_migrate(args: argparse.Namespace) -> int:
    """Alembic to head (plus the append-only triggers) on the resolved URL."""
    try:
        import crb.store.migrate as migrate_mod
        from crb.store.db import database_url
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    url = database_url(args.database_url)
    migrate_mod.upgrade(url)
    print(f"migrated {url}")
    return EXIT_OK


def probe_claude_code(*, verify: bool = False) -> ProbeResult:
    """The ``claude_code`` builder's readiness for ``auth: cli``: where the login would
    come from (``env`` | ``secrets_file`` (…xxxx) | ``keychain`` | ``none``), whether
    ``claude`` is on PATH and its version, and — with ``verify`` — the real probe.

    ``down`` when the secrets file exists but is refused (group/world readable): that
    is a finding, not a nuisance. ``degraded`` when the CLI is missing, when neither a
    cli-mode login nor ``ANTHROPIC_API_KEY`` is available, or when the probe does not
    come back ``ok``. Never prints or returns a token; the fingerprint is ≤4 chars.
    """
    from crb.builders import claude_code as cc
    from crb.core.secrets_file import resolve_secrets_dir
    from crb.observability import probes

    source, fp, detail = cc.auth_status()
    version = cc.cli_version()
    cli_present = bool(version) or bool(shutil.which("claude"))
    data: dict[str, Any] = {
        "auth": source,
        "fingerprint": fp,
        "cli": cli_present,
        "cli_version": version,
        "secrets_dir": str(resolve_secrets_dir()),
        "api_key": bool(os.environ.get(cc.API_KEY_ENV, "").strip()),
    }
    label = {
        cc.TOKEN_SOURCE_ENV: "env",
        cc.TOKEN_SOURCE_SECRETS_FILE: f"secrets file (…{fp})" if fp else "secrets file",
        cc.TOKEN_SOURCE_KEYCHAIN: "keychain",
        cc.TOKEN_SOURCE_NONE: "none",
        cc.VERIFY_CLI_MISSING: "unknown (no CLI)",
        cc.VERIFY_ERROR: "REFUSED",
    }.get(source, source)
    parts = [f"auth: {label}"]
    if source == cc.VERIFY_ERROR:
        parts.append(detail)
    parts.append(f"claude {version}" if version else "claude: not on PATH")
    parts.append(f"secrets dir {data['secrets_dir']}")
    if source == cc.VERIFY_ERROR:
        status = probes.DOWN
    elif not cli_present:
        status = probes.DEGRADED
    elif source in {cc.TOKEN_SOURCE_NONE, cc.VERIFY_CLI_MISSING} and not data["api_key"]:
        status = probes.DEGRADED
        parts.append("no cli-mode login and no ANTHROPIC_API_KEY — run `claude setup-token`")
    else:
        status = probes.OK
    if verify and status != probes.DOWN:
        check = cc.verify_login()
        data["verify"] = check.to_dict()
        parts.append(f"verify: {check.status} ({check.duration_s:.1f}s)")
        if check.status != cc.VERIFY_OK:
            status = probes.DEGRADED
            if check.detail:
                parts.append(check.detail)
    return probes.ProbeResult("claude_code", status, " · ".join(parts), data)


def cmd_doctor(args: argparse.Namespace) -> int:
    """One report over every readiness probe; exit 1 only when something is ``down``."""
    from crb.observability import probes

    results = [
        probes.probe_toolchains(),
        probes.probe_docker(),
        probes.probe_builders(),
        probe_claude_code(verify=bool(getattr(args, "verify", False))),
    ]
    try:
        from sqlalchemy import inspect

        from crb.store.db import database_url, make_engine, make_session_factory
        from crb.store.ledger import assert_append_only

        url = database_url(args.database_url)

        def _db() -> dict[str, str]:
            engine = make_engine(url)
            if "grades" not in inspect(engine).get_table_names():
                raise RuntimeError("database not initialised — run `crb migrate`")
            factory = make_session_factory(engine)
            assert_append_only(factory)
            return {"url": _redact_url(url), "append_only": "verified"}

        results.append(probes.probe_callable("database", _db))
    except ImportError:
        results.append(probes.ProbeResult("database", probes.DEGRADED, _SERVER_HINT))
    report = probes.aggregate(results)
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        for r in report["probes"]:
            print(f"{r['status']:>8}  {r['name']:<12} {r['detail']}")
        print(f"\noverall: {report['status']}")
    return EXIT_OK if report["status"] != probes.DOWN else 1


def _redact_url(url: str) -> str:
    """A database URL with its password replaced (the user name is kept)."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:[REDACTED]@{host}"
    return url


__all__: Sequence[str] = ("probe_claude_code", "register")
