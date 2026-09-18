"""Picking a port, running the migrations, spawning ``crb serve``, and knowing when it is up.

Three details of the runtime contract are load-bearing here and each has cost a debugging
session:

* ``crb serve`` ignores ``CRB_BIND_PORT`` — the port is a command-line flag or it is the
  default, whatever the environment says.
* readiness is ``GET /api/v1/health/live``. ``/health`` is not a readiness signal from
  outside the API: the SPA catch-all answers any unmatched path with ``index.html`` and a
  200, so a poller aimed there reports "ready" before the API exists.
* ``crb serve`` runs no migrations. ``crb migrate`` runs first, and is idempotent.

The child's output goes to a log file rather than a pipe: a pipe nobody drains fills and
wedges the server, and when startup fails the tail of that file is the only explanation the
user will get (a settings error is a single stderr line and exit code 2). The poller watches
the child as well as the socket, so a child that dies in the first second is reported in that
second instead of after the whole readiness deadline.

Navigation
----------
What it is:   The desktop launcher's process and port management — free-port selection, the
              migrate-then-serve spawn, the readiness poll and clean termination.
What it does: Picks the preferred port or an OS-assigned free one, runs ``crb migrate``,
              spawns ``crb serve --host --port`` with its output captured to a log file,
              polls ``/api/v1/health/live`` until 200 or the deadline, and stops the child
              with SIGTERM then SIGKILL. A child that exits during startup raises with the
              tail of its log rather than waiting out the deadline.
How:          A bind test without ``SO_REUSEADDR`` (so a socket in TIME_WAIT still counts as
              taken) then ``bind(port 0)`` as the fallback; ``subprocess.run`` for migrate
              and ``Popen`` for serve; ``urllib.request`` with a capped exponential backoff
              and a ``poll()`` of the child on every turn.
Layer:        desktop — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/desktop/__main__.py (the caller: migrate, serve, open the browser),
              src/crb/server/routes/system.py (``/health/live``, the endpoint polled here),
              src/crb/cli/commands/service.py (the ``crb serve`` and ``crb migrate`` verbs
              spawned here), src/crb/desktop/config.py (the environment the child is given),
              src/crb/server/app.py (the SPA catch-all that makes ``/health`` a false ready)
Tested by:    tests/test_desktop_launcher.py
Touch when:   the readiness endpoint moves or the API prefix changes; ``crb serve`` grows a
              flag the desktop run must pass; never for a new repository.
"""

from __future__ import annotations

import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

#: The desktop app's preferred port; a free one is chosen when it is taken.
DEFAULT_PORT = 8765
#: The desktop app binds the loopback interface only — it is a local application.
LOOPBACK_HOST = "127.0.0.1"
#: Readiness. NOT ``/health``: the SPA catch-all answers that with 200 and index.html.
READINESS_PATH = "/api/v1/health/live"
#: How long a first launch may take (migrations on a cold database included).
READY_TIMEOUT_SECONDS = 90.0
#: Backoff for the readiness poll.
POLL_INITIAL_SECONDS = 0.1
POLL_MAX_SECONDS = 0.75
#: Timeout of one readiness request; short, because it is retried.
PROBE_TIMEOUT_SECONDS = 2.0
#: How long ``crb migrate`` may take before the launcher gives up on it.
MIGRATE_TIMEOUT_SECONDS = 300.0
#: How long the child gets after SIGTERM before SIGKILL.
STOP_GRACE_SECONDS = 10.0
#: The child's stdout and stderr, under the state directory.
SERVER_LOG_FILE = "desktop-server.log"
#: Lines of that log shown when startup fails.
LOG_TAIL_LINES = 25


class ServerStartError(RuntimeError):
    """The server could not be brought up; ``log_tail`` is what the child said about it."""

    def __init__(self, message: str, *, log_tail: str = "") -> None:
        super().__init__(message)
        self.log_tail = log_tail


class SupportsPoll(Protocol):
    """A child process, as the readiness poll needs to see it."""

    def poll(self) -> int | None:
        """``None`` while it runs, the exit status once it has exited."""


@dataclass(frozen=True)
class ServerHandle:
    """A running ``crb serve`` and where to reach it."""

    process: subprocess.Popen[bytes]
    host: str
    port: int
    log_path: Path

    @property
    def base_url(self) -> str:
        """The URL to open in a browser."""
        return f"http://{self.host}:{self.port}/"

    @property
    def readiness_url(self) -> str:
        """The URL the readiness poll asks."""
        return readiness_url(self.port, host=self.host)


def port_is_free(port: int, *, host: str = LOOPBACK_HOST) -> bool:
    """Can we bind ``port`` right now?

    ``SO_REUSEADDR`` is deliberately NOT set: with it, a port held in ``TIME_WAIT`` by a
    previous run binds here and then fails in the child. This is still a race — the answer
    is true of the instant it was asked — so the caller treats a later bind failure as a
    startup failure, not as an impossibility.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(*, preferred: int = DEFAULT_PORT, host: str = LOOPBACK_HOST) -> int:
    """``preferred`` when it is free, otherwise a port the operating system picks."""
    if port_is_free(preferred, host=host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def readiness_url(port: int, *, host: str = LOOPBACK_HOST) -> str:
    """The liveness URL for a server on ``host:port``."""
    return f"http://{host}:{port}{READINESS_PATH}"


def probe_ready(url: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """One readiness request: ``True`` only on a 200.

    ``url`` is always the loopback URL built by :func:`readiness_url` — an http scheme and a
    host this process chose — so the audited-scheme warning is suppressed rather than guarded.
    """
    request = urllib.request.Request(url, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_until_ready(
    url: str,
    *,
    process: SupportsPoll | None = None,
    timeout: float = READY_TIMEOUT_SECONDS,
    probe: Callable[[str], bool] = probe_ready,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll ``url`` until it answers 200, the deadline passes, or ``process`` exits.

    Returns ``False`` rather than raising or hanging: a child that exits immediately (a
    settings error, an occupied port) is noticed on the next turn of the loop, and the
    caller reads the reason out of the child's log.
    """
    deadline = clock() + timeout
    delay = POLL_INITIAL_SECONDS
    while True:
        if process is not None and process.poll() is not None:
            return False
        if probe(url):
            return True
        if clock() >= deadline:
            return False
        sleep(delay)
        delay = min(delay * 2, POLL_MAX_SECONDS)


def run_migrations(
    crb_bin: Path, *, env: Mapping[str, str], timeout: float = MIGRATE_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """``crb migrate`` — idempotent, and required because ``crb serve`` runs no migrations."""
    return subprocess.run(
        [str(crb_bin), "migrate"],
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def start_server(
    crb_bin: Path,
    *,
    env: Mapping[str, str],
    port: int,
    log_path: Path,
    host: str = LOOPBACK_HOST,
) -> ServerHandle:
    """Spawn ``crb serve`` with its output appended to ``log_path``.

    The port is a flag because the server ignores ``CRB_BIND_PORT``; the output goes to a
    file because a pipe nobody reads fills up and stops the server mid-request.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("ab")
    try:
        process = subprocess.Popen(
            [str(crb_bin), "serve", "--host", host, "--port", str(port)],
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        stream.close()
    return ServerHandle(process=process, host=host, port=port, log_path=log_path)


def stop_server(handle: ServerHandle, *, grace: float = STOP_GRACE_SECONDS) -> int | None:
    """SIGTERM, then SIGKILL after ``grace`` seconds; returns the exit status."""
    process = handle.process
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace)
    return process.returncode


def read_log_tail(log_path: Path, *, lines: int = LOG_TAIL_LINES) -> str:
    """The last ``lines`` lines of the child's log, or "" when there is nothing to show."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def start_and_wait(
    crb_bin: Path,
    *,
    env: Mapping[str, str],
    port: int,
    log_path: Path,
    host: str = LOOPBACK_HOST,
    timeout: float = READY_TIMEOUT_SECONDS,
) -> ServerHandle:
    """Spawn ``crb serve`` and return it ready, or raise :class:`ServerStartError`.

    The two failures are told apart for the user: a child that exited (its log holds the
    reason — a settings error is one line and exit code 2) and a child still running that
    never answered (the deadline).
    """
    handle = start_server(crb_bin, env=env, port=port, log_path=log_path, host=host)
    if wait_until_ready(handle.readiness_url, process=handle.process, timeout=timeout):
        return handle
    status = handle.process.poll()
    stop_server(handle)
    tail = read_log_tail(log_path)
    if status is None:
        raise ServerStartError(
            f"the server did not answer {handle.readiness_url} within {timeout:.0f}s",
            log_tail=tail,
        )
    raise ServerStartError(f"the server exited with status {status} during startup", log_tail=tail)
