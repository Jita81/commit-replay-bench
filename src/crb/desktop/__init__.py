"""``crb.desktop`` — crb as a double-clickable local application.

The brain of the macOS .app bundle: it prepares the state directory, persists the secrets a
local installation must keep, spawns ``crb serve`` on a free loopback port, waits for the API
to answer, and opens a browser at it. It is standard library only and imports no other crb
package except :mod:`crb.core.version`, so it stays importable — and unit-testable — on a
machine that has never installed the server extra, and so the layer contract stays honest:
the launcher talks to ``crb`` as a subprocess, exactly as an operator would.

Navigation
----------
What it is:   The desktop launcher package — the public surface of ``python -m crb.desktop``.
What it does: Re-exports the pieces the entry point and the tests use: the path resolvers,
              the persisted secret key and administrator credentials, the child environment,
              the pre-flight report, and the port/spawn/readiness helpers. It holds no logic
              of its own and starts nothing on import.
How:          Plain re-export from the four modules beside it; ``crb.desktop.__main__``
              wires them together in launch order.
Layer:        desktop — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/desktop/__main__.py (the entry point that uses all of this),
              src/crb/desktop/server.py (port, spawn, readiness, shutdown),
              src/crb/desktop/config.py (the secrets and the environment),
              src/crb/desktop/paths.py (state directory, ``crb``, built interface),
              src/crb/desktop/preflight.py (the checks printed before anything is spawned)
Tested by:    tests/test_desktop_launcher.py
Touch when:   a module is added beside this one, or a name here is renamed (the entry point
              and the tests import from here); never for a new repository.
"""

from crb.desktop.config import (
    AdminCredentials,
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
from crb.desktop.preflight import Finding, PreflightReport, run_preflight
from crb.desktop.server import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    READINESS_PATH,
    ServerHandle,
    ServerStartError,
    choose_port,
    readiness_url,
    run_migrations,
    start_and_wait,
    start_server,
    stop_server,
    wait_until_ready,
)

__all__ = [
    "DEFAULT_PORT",
    "LOOPBACK_HOST",
    "READINESS_PATH",
    "AdminCredentials",
    "DesktopConfigError",
    "Finding",
    "PreflightReport",
    "ServerHandle",
    "ServerStartError",
    "build_environment",
    "choose_port",
    "ensure_admin_credentials",
    "ensure_secret_key",
    "ensure_state_home",
    "readiness_url",
    "resolve_crb_binary",
    "resolve_ui_dist",
    "run_migrations",
    "run_preflight",
    "start_and_wait",
    "start_server",
    "state_home",
    "stop_server",
    "wait_until_ready",
]
