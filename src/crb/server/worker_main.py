"""``crb worker`` — the process entrypoint for :class:`crb.server.worker.Worker`.

    crb worker [--database-url URL] [--home DIR] [--executor local|docker]
               [--image IMAGE] [--worker-id ID] [--poll SECONDS] [--once]
               [--heartbeat SECONDS] [--stale-after SECONDS] [--kinds replay,blind]
               [--metrics-port PORT] [--log-format json|text] [--log-level LEVEL]

``--once`` processes at most one queued run and exits (``0`` if a run was
executed, ``3`` if the queue was empty) — what tests and one-shot CI jobs use.
Without it the worker polls until ``SIGINT``/``SIGTERM``.

Environment fallbacks: ``CRB_DATABASE_URL`` (see :func:`crb.store.db.database_url`),
``CRB_HOME`` (default ``./.crb``), ``CRB_EXECUTOR``, ``CRB_SANDBOX_IMAGE``,
``CRB_WORKER_ID``, ``CRB_METRICS_PORT`` (default 9464; ``0`` = off) and
``CRB_METRICS_ENABLED``. Flags win over the environment.

The worker serves its own Prometheus exposition on ``CRB_METRICS_PORT`` before it
starts polling (not with ``--once``): the build / grade / cost series are recorded in
this process and the API's ``/metrics`` never carries them (J-TEL-1).

The CLI package wires ``crb worker`` to :func:`main`; this module does not
import :mod:`crb.cli`.

Navigation
----------
What it is:   ``crb worker`` — the argument parser and process entry point for the queue
              consumer.
What it does: Turns flags and ``CRB_*`` fallbacks into ``WorkerSettings``, refuses unknown run
              kinds, builds a ``Worker`` (a bad database URL is reported and exits 2), then
              either processes one run (``--once``; exit 3 when idle) or polls until a stop
              signal arrives.
How:          ``build_parser`` → ``settings_from_args`` (sets ``CRB_HOME`` for the builders'
              secrets lookup; reads ``CRB_GITHUB__*`` / ``CRB_METRICS_*`` through a
              pydantic-settings view of the same environment the API reads) → ``Worker`` →
              ``metrics.start_worker_exposition`` → ``run_once`` | ``run_forever(stop)``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/worker.py (``Worker`` / ``WorkerSettings`` — everything this
              file configures), src/crb/store/jobs.py (``RUN_KINDS`` for ``--kinds``),
              src/crb/observability/metrics.py (the worker's exposition server),
              src/crb/cli/commands/service.py (``crb worker`` forwards its argv here),
              deploy/entrypoint.sh (the container's ``worker`` role), deploy/docker-compose.yml
              and deploy/helm/crb/templates/worker-deployment.yaml (expose the metrics port),
              src/crb/core/execution.py (``DockerSettings`` for ``--image``)
Tested by:    tests/test_worker.py
Touch when:   never for a new repository (the sandbox image is per repository, set in its
              config); adding a worker flag means adding it to ``WorkerSettings`` and to the
              ``crb worker`` forwarding table in src/crb/cli/commands/service.py.
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

from pydantic_settings import BaseSettings, SettingsConfigDict

from crb.core.execution import DockerSettings, SandboxUnavailable
from crb.observability import metrics
from crb.observability.logging import configure_logging
from crb.server.settings import GitHubAppSettings
from crb.server.worker import Worker, WorkerSettings
from crb.store.jobs import RUN_KINDS

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_IDLE = 3

HOME_ENV = "CRB_HOME"
EXECUTOR_ENV = "CRB_EXECUTOR"
IMAGE_ENV = "CRB_SANDBOX_IMAGE"
WORKER_ID_ENV = "CRB_WORKER_ID"
METRICS_PORT_ENV = "CRB_METRICS_PORT"
METRICS_ENABLED_ENV = "CRB_METRICS_ENABLED"
DEFAULT_METRICS_PORT = 9464


def build_parser() -> argparse.ArgumentParser:
    """The ``crb worker`` parser (defaults are blank so the environment can fill them)."""
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
    p.add_argument(
        "--metrics-port",
        type=int,
        default=None,
        help=f"serve this worker's Prometheus /metrics on this port (default: ${METRICS_PORT_ENV} "
        f"or {DEFAULT_METRICS_PORT}; 0 = off)",
    )
    p.add_argument("--once", action="store_true", help="process at most one run, then exit")
    p.add_argument("--keep-worktrees", action="store_true", help="do not remove trial worktrees")
    p.add_argument("--log-format", choices=("json", "text"), default="json")
    p.add_argument("--log-level", default="INFO")
    return p


def settings_from_args(
    args: argparse.Namespace, env: dict[str, str] | None = None
) -> WorkerSettings:
    """Flags win over ``env`` (``os.environ`` by default) win over the built-in defaults.
    ``ValueError`` names an unknown run kind; the parser turns it into exit 2."""
    e = env if env is not None else dict(os.environ)
    home = Path(args.home or e.get(HOME_ENV) or ".crb").expanduser()
    # Builders resolve the secrets dir from the environment only (core has no settings
    # object): a worker started with --home but no CRB_HOME would otherwise look under
    # ./.crb/secrets for the Claude Code token the Settings UI stored under <home>.
    os.environ.setdefault(HOME_ENV, str(home))
    executor = (args.executor or e.get(EXECUTOR_ENV) or "local").strip().lower()
    image = (args.image or e.get(IMAGE_ENV) or "").strip()
    docker = DockerSettings(image=image) if image else None
    kinds = tuple(k.strip() for k in str(args.kinds).split(",") if k.strip())
    unknown = [k for k in kinds if k not in RUN_KINDS]
    if unknown:
        raise ValueError(f"unknown run kind(s) {unknown!r}; expected {RUN_KINDS}")
    shared = _shared_settings(e)
    port = args.metrics_port if args.metrics_port is not None else shared.metrics_port
    if not 0 <= int(port) <= 65535:
        raise ValueError(f"{METRICS_PORT_ENV} must be 0 (off) or a port 1-65535, got {port}")
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
        # the same CRB_GITHUB__* / CRB_METRICS_* the API reads (pydantic-settings parses them)
        github=shared.github,
        metrics_enabled=shared.metrics_enabled,
        metrics_port=int(port),
    )


class _SharedWithApi(BaseSettings):
    """Just the keys the worker shares with the API — ``CRB_GITHUB__*``, ``CRB_METRICS_ENABLED``
    and ``CRB_METRICS_PORT`` — read the way :class:`Settings` reads them (same prefix, same
    nested delimiter) and nothing else: the worker must not fail on an unrelated server
    setting it does not use, and must not START on a malformed GitHub one — a bad
    ``CRB_GITHUB__API_URL`` is a configuration error the operator fixes, not a worker that
    quietly runs without the enterprise connection."""

    model_config = SettingsConfigDict(
        env_prefix="CRB_", env_nested_delimiter="__", extra="ignore", case_sensitive=False
    )
    github: GitHubAppSettings = GitHubAppSettings()
    metrics_enabled: bool = True
    #: The worker's own exposition port (the API keeps ``/metrics`` on its HTTP port).
    metrics_port: int = DEFAULT_METRICS_PORT


def _shared_settings(env: dict[str, str] | None = None) -> _SharedWithApi:
    """``CRB_GITHUB__APP_ID`` / ``__PRIVATE_KEY`` / ``__PRIVATE_KEY_FILE`` / ``__API_URL`` …
    and ``CRB_METRICS_ENABLED`` / ``CRB_METRICS_PORT``, read the way the API reads them, so
    one environment configures both processes. A malformed value raises
    (``pydantic.ValidationError``) and the worker does not start. ``env`` (tests) stands
    in for ``os.environ``."""
    if env is None:
        return _SharedWithApi()
    return _SharedWithApi(**_keys_for(env))


def _keys_for(env: dict[str, str]) -> dict[str, Any]:
    """The subset of an explicit ``env`` mapping that ``_SharedWithApi`` reads, as its
    field values (pydantic-settings only reads ``os.environ`` on its own)."""
    out: dict[str, Any] = {}
    if METRICS_ENABLED_ENV in env:
        out["metrics_enabled"] = env[METRICS_ENABLED_ENV]
    if METRICS_PORT_ENV in env:
        out["metrics_port"] = env[METRICS_PORT_ENV]
    github = {
        k.removeprefix("CRB_GITHUB__").lower(): v
        for k, v in env.items()
        if k.upper().startswith("CRB_GITHUB__")
    }
    if github:
        out["github"] = github
    return out


def _run_summary(run: Any) -> dict[str, Any]:
    """What ``--once`` prints on stdout (one JSON object; a CI job can parse it)."""
    return {
        "run_id": run.id,
        "repo": run.repo,
        "kind": run.kind,
        "status": run.status,
        "counts": dict(run.counts_json or {}),
        "error": run.error,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Process entry point; see the module docstring for the exit codes."""
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
        # a one-shot worker leaves: stamp its row stopped so the health probe does not
        # read the exiting process as a worker that stopped checking in
        worker.checkin(stopped=True)
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
    metrics.start_worker_exposition(settings.metrics_port, enabled=settings.metrics_enabled)
    worker.run_forever(stop)
    return EXIT_OK


__all__ = ["EXIT_ERROR", "EXIT_IDLE", "EXIT_OK", "build_parser", "main", "settings_from_args"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
