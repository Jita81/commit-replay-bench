"""``crb serve`` / ``crb worker`` / ``crb doctor`` / ``crb migrate`` — the service verbs.

These import the server layer lazily: the core CLI must keep working on a host
that has only the base package installed (``pip install commit-replay-bench``
without the ``[server]`` extra).
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from crb.cli.commands import EXIT_OK, CliError

_SERVER_HINT = "the server layer is not installed — `pip install 'commit-replay-bench[server]'`"


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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

    doctor = sub.add_parser("doctor", help="check toolchains, sandbox, builders, database")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--database-url", default=None)
    doctor.set_defaults(func=cmd_doctor)


def cmd_serve(args: argparse.Namespace) -> int:
    if args.database_url:
        os.environ["CRB_DATABASE_URL"] = args.database_url
    try:
        from crb.server.main import serve
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    serve(host=args.host, port=args.port)
    return EXIT_OK


def cmd_worker(args: argparse.Namespace) -> int:
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
    try:
        import crb.store.migrate as migrate_mod  # type: ignore[import-untyped]  # W2-E

        from crb.store.db import database_url
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    url = database_url(args.database_url)
    migrate_mod.upgrade(url)
    print(f"migrated {url}")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from crb.observability import probes

    results = [probes.probe_toolchains(), probes.probe_docker(), probes.probe_builders()]
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
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:[REDACTED]@{host}"
    return url


__all__: Sequence[str] = ("register",)
