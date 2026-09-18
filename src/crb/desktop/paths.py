"""Where the desktop app keeps its state, and where it finds ``crb`` and the built SPA.

A double-clicked .app inherits no shell profile: there is no virtualenv on ``PATH``, no
``CRB_HOME`` exported by an operator, and ``~`` means whatever the resolver that expands it
thinks it means. Every path this module returns is therefore absolute and already expanded —
the child process is handed strings, never a tilde.

The bundle layout this assumes is the one ``macos/build_app.sh`` writes: the embedded
interpreter and ``crb`` at ``Contents/Resources/python/bin/``, and the built SPA one level
above the runtime at ``Contents/Resources/ui/index.html`` — the SPA is not part of the Python
installation and is not kept inside it. A source checkout is the fallback so ``python -m
crb.desktop`` works on Linux. The launcher exports ``CRB_UI_DIST`` explicitly, so these
candidates are a safety net rather than the normal path; they are kept correct anyway,
because a wrong implicit layout only shows up on the day the export is missed.

Navigation
----------
What it is:   The desktop launcher's path resolver — the per-user state directory, the
              bundled ``crb`` executable and the built SPA directory.
What it does: Returns an absolute, tilde-free state directory (macOS ``Library/Application
              Support/crb``; elsewhere ``$XDG_DATA_HOME/crb`` or ``~/.local/share/crb``,
              with ``CRB_HOME`` winning when it is set), and locates ``crb`` and the SPA
              inside the bundle, falling back to ``PATH`` and to a source checkout. It
              never creates the executable or the SPA — a missing one is reported, not
              invented.
How:          Candidate paths in priority order, each tested on disk (``os.access`` with
              ``X_OK`` for the executable, ``index.html`` for the SPA); the state directory
              is ``expanduser`` then ``resolve``, and ``ensure_state_home`` creates it 0700.
Layer:        desktop — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/desktop/config.py (writes the secret key and credentials into the
              directory this resolves), src/crb/desktop/__main__.py (the caller, in launch
              order), src/crb/desktop/preflight.py (turns a missing executable or SPA into a
              remedy), src/crb/server/settings.py (``CRB_HOME`` and ``CRB_UI_DIST`` as the
              server reads them), ui/vite.config.ts (what builds the SPA directory)
Tested by:    tests/test_desktop_launcher.py
Touch when:   never for a new repository; when the bundle layout moves (change the candidate
              lists here and the packaging script together), or when a platform other than
              macOS and Linux needs its own state directory.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

#: Directory name under the platform's per-user data directory.
APP_DIR_NAME = "crb"
#: The state directory the server reads; set, it wins over the platform default.
HOME_ENV = "CRB_HOME"
#: Absolute path to the built SPA; set, it wins over the bundled and checked-out copies.
UI_DIST_ENV = "CRB_UI_DIST"
#: Points the launcher at a specific ``crb`` executable (the tests, and a developer's venv).
CRB_BIN_ENV = "CRB_DESKTOP_CRB_BIN"
#: The state directory is private to the user who launched the app.
STATE_DIR_MODE = 0o700


def _user_home(env: Mapping[str, str]) -> Path:
    """The user's home directory, taken from ``env`` so callers can redirect it in a test."""
    configured = env.get("HOME", "").strip()
    return Path(configured) if configured else Path.home()


def _absolute(path: Path) -> Path:
    """``path`` expanded and made absolute — the result never contains a tilde."""
    return path.expanduser().resolve()


def state_home(*, env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """The per-user state directory, absolute and tilde-free.

    ``CRB_HOME`` wins when it is set and non-empty (an operator pointing the app at an
    existing installation); otherwise macOS gets ``~/Library/Application Support/crb`` and
    every other platform ``$XDG_DATA_HOME/crb`` or ``~/.local/share/crb``.
    """
    environ = os.environ if env is None else env
    system = sys.platform if platform is None else platform
    configured = environ.get(HOME_ENV, "").strip()
    if configured:
        return _absolute(Path(configured))
    home = _user_home(environ)
    if system == "darwin":
        return _absolute(home / "Library" / "Application Support" / APP_DIR_NAME)
    xdg = environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else home / ".local" / "share"
    return _absolute(base / APP_DIR_NAME)


def ensure_state_home(home: Path) -> Path:
    """Create ``home`` (and its parents) 0700 if it does not exist, and return it."""
    home.mkdir(parents=True, exist_ok=True, mode=STATE_DIR_MODE)
    return home


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def resolve_crb_binary(
    *, env: Mapping[str, str] | None = None, executable: str | None = None
) -> Path | None:
    """The ``crb`` executable to spawn, or ``None`` when there is none to spawn.

    The bundled copy beside the launcher's interpreter wins, so an app that ships its own
    Python never picks up a different ``crb`` from the user's ``PATH``. ``CRB_DESKTOP_CRB_BIN``
    comes next and is honoured exactly: if it names something that is not executable the
    answer is ``None``, never a silent fall back to ``PATH``.
    """
    environ = os.environ if env is None else env
    interpreter = Path(executable if executable is not None else sys.executable)
    for candidate in (interpreter.parent / "crb", interpreter.parent.parent / "bin" / "crb"):
        if _is_executable(candidate):
            return candidate.resolve()
    override = environ.get(CRB_BIN_ENV, "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate.resolve() if _is_executable(candidate) else None
    found = shutil.which("crb", path=environ.get("PATH"))
    return Path(found).resolve() if found else None


def repo_ui_dist() -> Path:
    """``ui/dist`` of a source checkout — the developer's copy, absent from a wheel."""
    return Path(__file__).resolve().parents[3] / "ui" / "dist"


def resolve_ui_dist(
    *, env: Mapping[str, str] | None = None, executable: str | None = None
) -> Path | None:
    """The directory holding the built SPA's ``index.html``, or ``None`` when none is built."""
    environ = os.environ if env is None else env
    candidates: list[Path] = []
    configured = environ.get(UI_DIST_ENV, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    interpreter = Path(executable if executable is not None else sys.executable)
    # Resources/ui, one level above the embedded runtime: bin/ -> python/ -> Resources/.
    candidates.append(interpreter.parent.parent.parent / "ui")
    # A layout that keeps the SPA inside the runtime directory itself.
    candidates.append(interpreter.parent.parent / "ui")
    candidates.append(repo_ui_dist())
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate.resolve()
    return None
