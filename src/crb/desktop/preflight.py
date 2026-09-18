"""What the launcher checks before it spawns anything — and the remedy it prints when a check fails.

A desktop user has no terminal to read a stack trace in, so every failed check carries one
sentence of remedy in the user's language. The checks are deliberately cheap and offline:
is there a ``crb`` to run, is there a built SPA to serve, is ``git`` on ``PATH``.

``git`` is the interesting one. Its absence does not stop the server starting — liveness only
needs the process and its database — but the ``toolchains`` probe reports ``down``, so
``/api/v1/health`` answers 503 and the app looks broken to anyone who opens the health page.
On a fresh Mac the fix is one command, so the finding names it rather than merely reporting
the absence. Nothing here exits or raises: the caller decides what a blocking finding means.

Navigation
----------
What it is:   The desktop launcher's pre-flight checks — ``crb``, the built SPA, and ``git``.
What it does: Returns a structured report of findings, each with a detail line and, when it
              failed, a remedy; marks the executable and the SPA as blocking and ``git`` as
              a warning, because a run without git starts but reports 503 from deep health.
              It never exits, never raises and never installs anything.
How:          ``shutil.which`` for ``git`` (injectable so a test can deny it), an
              ``index.html`` test for the SPA, and a presence test for the executable the
              resolver returned; the findings are collected into a frozen report that knows
              its own blockers.
Layer:        desktop — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/desktop/__main__.py (prints this report and decides whether to stop),
              src/crb/desktop/paths.py (resolves the executable and SPA these checks judge),
              src/crb/observability/probes.py (the ``toolchains`` probe whose ``down`` this
              anticipates), src/crb/server/routes/system.py (the 503 a missing git causes),
              docs/OPERATOR.md (the same prerequisites for a server install)
Tested by:    tests/test_desktop_launcher.py
Touch when:   the server grows a prerequisite a desktop user can be missing (add a check and
              its remedy here, not a raise deeper down); the macOS remedy changes.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: How a Mac without developer tools gets ``git``; named verbatim in the remedy.
GIT_REMEDY = "install Apple's command line tools: run `xcode-select --install` in Terminal."
#: How a source checkout gets a built SPA.
UI_REMEDY = (
    "build the interface with `npm --prefix ui install && npm --prefix ui run build`, "
    "or set CRB_UI_DIST to a directory containing index.html."
)
#: How a launcher that cannot see the command-line tool gets one.
CRB_REMEDY = (
    "reinstall the application, or set CRB_DESKTOP_CRB_BIN to the `crb` executable of an "
    "environment with `pip install 'commit-replay-bench[server]'`."
)

#: ``shutil.which``'s shape, so a test can deny a tool without touching ``PATH``.
Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Finding:
    """One check: what was looked for, whether it is there, and what to do if it is not."""

    name: str
    ok: bool
    detail: str
    remedy: str = ""
    #: True when the launcher cannot usefully continue without it.
    blocking: bool = False

    def line(self) -> str:
        """One printable line — ``ok``/``warn``/``fail``, the detail, then the remedy."""
        mark = "ok  " if self.ok else ("fail" if self.blocking else "warn")
        remedy = f" — {self.remedy}" if (self.remedy and not self.ok) else ""
        return f"[{mark}] {self.name}: {self.detail}{remedy}"


@dataclass(frozen=True)
class PreflightReport:
    """Every finding of one pre-flight pass."""

    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        """True when every check passed, warnings included."""
        return all(finding.ok for finding in self.findings)

    @property
    def blockers(self) -> tuple[Finding, ...]:
        """The failed checks the launcher cannot continue past."""
        return tuple(f for f in self.findings if not f.ok and f.blocking)

    def lines(self) -> list[str]:
        """Every finding as a printable line, in the order they were checked."""
        return [finding.line() for finding in self.findings]


def check_git(which: Which | None = None) -> Finding:
    """Is ``git`` on ``PATH``? Its absence makes ``/api/v1/health`` answer 503."""
    lookup = shutil.which if which is None else which
    found = lookup("git")
    if found:
        return Finding("git", True, f"found at {found}")
    return Finding(
        "git",
        False,
        "not on PATH — the server starts, but the toolchains probe reports down and "
        "/api/v1/health answers 503",
        GIT_REMEDY,
    )


def check_ui_dist(ui_dist: Path | None) -> Finding:
    """Is there a built SPA to serve? Without one the app has nothing to open."""
    if ui_dist is None:
        return Finding("interface", False, "no built interface found", UI_REMEDY, blocking=True)
    if not (ui_dist / "index.html").is_file():
        return Finding(
            "interface",
            False,
            f"{ui_dist} holds no index.html",
            UI_REMEDY,
            blocking=True,
        )
    return Finding("interface", True, f"serving {ui_dist}")


def check_crb_binary(crb_bin: Path | None) -> Finding:
    """Is there a ``crb`` executable to spawn?"""
    if crb_bin is None:
        return Finding("crb", False, "no `crb` executable found", CRB_REMEDY, blocking=True)
    return Finding("crb", True, f"found at {crb_bin}")


def run_preflight(
    *, crb_bin: Path | None, ui_dist: Path | None, which: Which | None = None
) -> PreflightReport:
    """Every check, in the order a reader of the output wants them."""
    return PreflightReport((check_crb_binary(crb_bin), check_ui_dist(ui_dist), check_git(which)))
