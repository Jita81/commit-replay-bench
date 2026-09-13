"""``crb worker`` — the process entrypoint for :class:`crb.server.worker.Worker`.

    crb worker [--database-url URL] [--home DIR] [--executor local|docker]
               [--image IMAGE] [--worker-id ID] [--poll SECONDS] [--once]
               [--heartbeat SECONDS] [--stale-after SECONDS] [--kinds replay,blind]
               [--log-format json|text] [--log-level LEVEL]

``--once`` processes at most one queued run and exits (``0`` if a run was
executed, ``3`` if the queue was empty) — what tests and one-shot CI jobs use.
Without it the worker polls until ``SIGINT``/``SIGTERM``.

Environment fallbacks: ``CRB_DATABASE_URL`` (see :func:`crb.store.db.database_url`),
``CRB_HOME`` (default ``./.crb``), ``CRB_EXECUTOR``, ``CRB_SANDBOX_IMAGE``,
``CRB_WORKER_ID``. Flags win over the environment.

The CLI package wires ``crb worker`` to :func:`main`; this module does not
import :mod:`crb.cli`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crb.core.execution import DockerSettings, SandboxUnavailable
from crb.observability.logging import configure_logging
from crb.server.worker import Worker, WorkerSettings
from crb.store.jobs import RUN_KINDS

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_IDLE = 3

HOME_ENV = "CRB_HOME"
EXECUTOR_ENV = "CRB_EXECUTOR"
IMAGE_ENV = "CRB_SANDBOX_IMAGE"
WORKER_ID_ENV = "CRB_WORKER_ID"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crb worker",
        description="Execute queued runs: probe, mine, replay, blind, oracle, controls.",
    )
    p.add_argument(
        "--database-url",
        default="",
        help="SQLAlchemy URL (default: $CRB_DATABASE_URL, else sqlite under --home)",
    )
    p.add_argument("--home", default="", help="work directory (default: $CRB_HOME or ./.crb)")
    p.add_argument(
        "--executor",
        choices=("local", "docker"),
        default="",
        help="default executor kind for runs that do not name one (default: $CRB_EXECUTOR or local)",
    )
    p.add_argument(
        "--image",
        default="",
        help="sandbox image for --executor docker (default: $CRB_SANDBOX_IMAGE or the repo's)",
    )
    p.add_argument("--worker-id", default="", help="stable worker identity (default: host-pid)")
    p.add_argument("--poll", type=float, default=2.0, help="seconds between polls when idle")
    p.add_argument("--heartbeat", type=float, default=10.0, help="seconds between heartbeats")
    p.add_argument(
        "--stale-after",
        type=float,
        default=120.0,
        help="reclaim a running run whose heartbeat is older than this many seconds",
    )
    p.add_argument(
        "--kinds",
        default="",
        help=f"comma-separated run kinds to accept (default: all of {', '.join(RUN_KINDS)})",
    )
    p.add_argument("--once", action="store_true", help="process at most one run, then exit")
    p.add_argument("--keep-worktrees", action="store_true", help="do not remove trial worktrees")
    p.add_argument("--log-format", choices=("json", "text"), default="json")
    p.add_argument("--log-level", default="INFO")
    return p


def settings_from_args(
    args: argparse.Namespace, env: dict[str, str] | None = None
) -> WorkerSettings:
    e = env if env is not None else dict(os.environ)
    home = Path(args.home or e.get(HOME_ENV) or ".crb").expanduser()
    executor = (args.executor or e.get(EXECUTOR_ENV) or "local").strip().lower()
    image = (args.image or e.get(IMAGE_ENV) or "").strip()
    docker = DockerSettings(image=image) if image else None
    kinds = tuple(k.strip() for k in str(args.kinds).split(",") if k.strip())
    unknown = [k for k in kinds if k not in RUN_KINDS]
    if unknown:
        raise ValueError(f"unknown run kind(s) {unknown!r}; expected {RUN_KINDS}")
    return WorkerSettings(
        database_url=args.database_url or "",
        home=home,
        executor=executor,
        docker=docker,
        worker_id=args.worker_id or e.get(WORKER_ID_ENV, ""),
        poll_s=float(args.poll),
        heartbeat_s=float(args.heartbeat),
        stale_after_s=float(args.stale_after),
        kinds=kinds,
        keep_worktrees=bool(args.keep_worktrees),
    )


def _run_summary(run: Any) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "repo": run.repo,
        "kind": run.kind,
        "status": run.status,
        "counts": dict(run.counts_json or {}),
        "error": run.error,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    configure_logging(fmt=args.log_format, level=args.log_level)
    try:
        settings = settings_from_args(args)
    except (ValueError, SandboxUnavailable) as exc:
        parser.error(str(exc))  # exits 2
    try:
        worker = Worker(settings)
    except Exception as exc:  # DB unreachable, bad URL: say so and stop
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return EXIT_ERROR

    if args.once:
        run = worker.run_once()
        if run is None:
            print(json.dumps({"status": "idle", "worker_id": worker.worker_id}))
            return EXIT_IDLE
        print(json.dumps(_run_summary(run), sort_keys=True))
        return EXIT_OK

    stop = threading.Event()

    def _stop(_signum: int, _frame: Any) -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):  # not the main thread / unsupported
            signal.signal(sig, _stop)
    worker.run_forever(stop)
    return EXIT_OK


__all__ = ["EXIT_ERROR", "EXIT_IDLE", "EXIT_OK", "build_parser", "main", "settings_from_args"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
