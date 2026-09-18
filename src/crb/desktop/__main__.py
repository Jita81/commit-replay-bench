"""``python -m crb.desktop`` — the launcher the macOS app bundle double-click runs.

The order matters and is the whole program: resolve the state directory → resolve ``crb``
and the built interface → pre-flight → persist the secrets → build the child environment →
pick a port → migrate → serve → wait for ``/api/v1/health/live`` → open the browser → block
until the server exits or the user quits.

Exit codes follow the CLI's contract (docs/OPERATOR.md): 0 when the server ran and stopped
cleanly, 1 when it failed to come up, 2 when the machine is not in a state to launch from —
no ``crb``, no built interface, or migrations that refused.

Navigation
----------
What it is:   The desktop entry point — ``python -m crb.desktop``, and what the .app bundle
              executes.
What it does: Wires the launcher together in launch order, prints the pre-flight report and
              the first-run credentials, opens the browser at the ready server (unless
              ``--no-browser``) and blocks until the server exits or the user interrupts,
              stopping the child cleanly on the way out. ``--port`` asks for a specific
              port; a taken one is reported, not silently replaced.
How:          ``argparse`` → :mod:`crb.desktop.paths` → :mod:`crb.desktop.preflight` →
              :mod:`crb.desktop.config` → :mod:`crb.desktop.server`; SIGTERM is forwarded to
              the child and ``KeyboardInterrupt`` is caught, so both quit paths terminate it.
Layer:        desktop — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/desktop/server.py (port, spawn, readiness, shutdown),
              src/crb/desktop/config.py (the secrets and the child environment),
              src/crb/desktop/preflight.py (what is printed before anything is spawned),
              src/crb/desktop/paths.py (the state directory, ``crb`` and the interface),
              src/crb/cli/main.py (the exit-code contract this follows), docs/OPERATOR.md
Tested by:    tests/test_desktop_launcher.py
Touch when:   the launch order changes, a flag is added to the desktop app, or the bundle
              needs a different exit-code contract; never for a new repository.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import signal
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from crb.core.version import __version__
from crb.desktop.config import (
    DesktopConfigError,
    build_environment,
    ensure_admin_credentials,
    ensure_secret_key,
)
from crb.desktop.paths import (
    ensure_state_home,
    resolve_crb_binary,
    resolve_ui_dist,
    state_home,
)
from crb.desktop.preflight import run_preflight
from crb.desktop.server import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    SERVER_LOG_FILE,
    ServerHandle,
    ServerStartError,
    choose_port,
    port_is_free,
    run_migrations,
    start_and_wait,
    stop_server,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNUSABLE = 2


def build_parser() -> argparse.ArgumentParser:
    """The launcher's two flags — everything else is discovered, not configured."""
    parser = argparse.ArgumentParser(
        prog="crb-desktop",
        description="Run Commit Replay Bench as a local application.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port to serve on (default: {DEFAULT_PORT}, or a free one if it is taken)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser window",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _print_credentials(url: str, username: str, password: str, path: Path, first: bool) -> None:
    """The one thing a first-time user must read before the browser steals their attention."""
    heading = "Sign in with these credentials" if first else "Your sign-in details"
    print("")
    print(f"  {heading}:")
    print(f"    address:  {url}")
    print(f"    username: {username}")
    print(f"    password: {password}")
    print(f"  Stored (owner-readable only) at {path}")
    print("")


def _line_buffer_stdout() -> None:
    """Make progress and the credentials appear as they happen, not at exit.

    Python block-buffers stdout whenever it is not a terminal, which is every case that
    matters here: launched from Finder, piped to a log, or captured by the smoke test. The
    credentials would then sit in an 8 KiB buffer until the process ended — so a user who
    ran the app from Terminal and read the screen would see nothing at all.
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)


def _forward_termination(handle: ServerHandle) -> None:
    """Quitting the app sends SIGTERM here; the child must get it too."""

    def _stop(signum: int, frame: FrameType | None) -> None:
        handle.process.terminate()

    with contextlib.suppress(ValueError):  # not the main thread: nothing to install
        signal.signal(signal.SIGTERM, _stop)


def _resolve_port(requested: int | None) -> int:
    """The requested port if it is free, otherwise the preferred one or an OS-assigned one."""
    if requested is None:
        return choose_port()
    if not port_is_free(requested):
        raise ServerStartError(f"port {requested} is already in use")
    return requested


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the application; returns the process exit code."""
    args = build_parser().parse_args(argv)
    _line_buffer_stdout()

    home = ensure_state_home(state_home())
    crb_bin = resolve_crb_binary()
    ui_dist = resolve_ui_dist()

    report = run_preflight(crb_bin=crb_bin, ui_dist=ui_dist)
    for line in report.lines():
        print(line)
    if report.blockers:
        print("cannot start:", file=sys.stderr)
        for finding in report.blockers:
            print(f"  {finding.detail} — {finding.remedy}", file=sys.stderr)
        return EXIT_UNUSABLE
    assert crb_bin is not None  # guaranteed by the blocking pre-flight check above
    assert ui_dist is not None

    try:
        secret_key = ensure_secret_key(home)
        admin = ensure_admin_credentials(home)
    except (DesktopConfigError, OSError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE

    env = build_environment(home=home, ui_dist=ui_dist, secret_key=secret_key, admin=admin)

    migrated = run_migrations(crb_bin, env=env)
    if migrated.returncode != 0:
        print("cannot start: `crb migrate` failed", file=sys.stderr)
        for stream in (migrated.stderr, migrated.stdout):
            if stream and stream.strip():
                print(stream.strip(), file=sys.stderr)
        return EXIT_UNUSABLE

    try:
        port = _resolve_port(args.port)
        handle = start_and_wait(
            crb_bin, env=env, port=port, log_path=home / SERVER_LOG_FILE, host=LOOPBACK_HOST
        )
    except ServerStartError as exc:
        print(f"the server did not start: {exc}", file=sys.stderr)
        if exc.log_tail:
            print(exc.log_tail, file=sys.stderr)
        return EXIT_FAILED

    _forward_termination(handle)
    print(f"Commit Replay Bench is running at {handle.base_url}")
    _print_credentials(handle.base_url, admin.username, admin.password, admin.path, admin.created)
    if not args.no_browser:
        webbrowser.open(handle.base_url)
    print("Press Ctrl-C to stop.")

    try:
        handle.process.wait()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        stop_server(handle)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — the bundle's entry point
    sys.exit(main())
