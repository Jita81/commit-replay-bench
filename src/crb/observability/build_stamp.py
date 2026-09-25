"""The served-commit stamp: which source the server runs, which the UI bundle was built from.

On 2026-09-25 the operator's stack served stale code: the checkout it ran was behind
``origin/main`` and ``ui/dist`` had been built from an older tree still, and nothing in the
product could say so — a fix that had merged was "not working" because it was not running
(docs/PREVENTION.md P-002). This module makes that state a reading instead of a surprise:

* the **server commit** is captured ONCE, when the process first asks (``create_app`` asks at
  start-up): ``CRB_SOURCE_COMMIT`` when set (an image is stamped at build time — it carries no
  ``.git``), else ``git rev-parse HEAD`` of the checkout the ``crb`` package was imported from;
* the **checkout commit** is read again at every check — the code on disk now;
* the **UI commit** is what ``ui/vite.config.ts``'s ``buildStamp`` plugin wrote into
  ``<dist>/build-stamp.json`` when the bundle was built.

``stale`` is ``True`` when any two known commits disagree (the process runs code the checkout
no longer holds → restart; the bundle was built from another commit → rebuild), or when a
bundle is served that carries no stamp (built before stamping existed or outside
``npm run build`` — its source cannot be named, so it is not trusted). A commit that cannot be
read is ``""`` and is never compared: unknown is reported as unknown, not as fresh.

Navigation
----------
What it is:   The served-commit stamp — the server's commit (captured at start), the
              checkout's commit (now), the UI bundle's commit (from its build stamp) and the
              ``stale`` verdict ``/health`` serves and ``crb doctor`` fails on.
What it does: ``served_report`` compares the three commits and names each disagreement with
              the fix in the sentence; ``probe_build`` turns it into a probe (``degraded`` on
              ``/health`` — a stale server still serves; ``down`` under ``crb doctor``, which
              exits 1); ``commits_behind`` counts how far the checkout trails a local
              ``origin/main`` ref (offline — never a fetch). It never serves a path.
How:          ``git rev-parse`` / ``git rev-list`` with a short timeout, only when the package
              root holds a ``.git``; ``process_commit`` caches its first answer for the life
              of the process; the bundle stamp is ``json`` read from the dist directory.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/server/routes/system.py (``/health`` serves ``served`` and the ``build``
              probe), src/crb/cli/commands/service.py (``crb doctor``'s ``build`` line),
              src/crb/server/app.py (captures the server commit at start-up;
              ``resolve_ui_dist``), ui/vite.config.ts (the ``buildStamp`` plugin that writes
              the bundle's stamp), deploy/Dockerfile (``CRB_SOURCE_COMMIT`` for an image),
              docs/PREVENTION.md (P-002 — the bug this closes)
Tested by:    tests/test_build_stamp.py, tests/test_server_system.py, tests/test_cli_doctor.py
Touch when:   never for a new repository; the bundle's stamp file or its fields change (the
              vite plugin and ``BUILD_STAMP_FILE`` change together, and the contract test in
              tests/test_build_stamp.py pins both).
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from crb.observability.probes import DEGRADED, OK, SKIPPED, ProbeResult

#: The file the UI build writes into its output directory (``ui/vite.config.ts``).
BUILD_STAMP_FILE = "build-stamp.json"
#: An image has no ``.git``: the build passes the commit in (deploy/Dockerfile ARG → ENV).
SOURCE_COMMIT_ENV = "CRB_SOURCE_COMMIT"
#: The ref ``commits_behind`` compares with — local, as of the last fetch; never fetched.
UPSTREAM_REF = "origin/main"
#: The UI bundle's stamp states: no bundle served, a bundle with no stamp, a stamp that
#: could not be read, a readable stamp.
UI_ABSENT = "absent"
UI_UNSTAMPED = "unstamped"
UI_UNREADABLE = "unreadable"
UI_STAMPED = "stamped"
_GIT_TIMEOUT_S = 5


def source_root() -> Path:
    """The directory three levels above this file's package — the repository root of a
    source checkout (``src/crb/observability/`` → root), site-packages' parent for a wheel.
    Located from ``__file__``, never ``crb.__file__``: ``crb`` is a namespace package (no
    ``__init__.py``), so its ``__file__`` is ``None`` (docs/PREVENTION.md P-011)."""
    return Path(__file__).resolve().parents[3]


def _git(root: Path, *args: str) -> str:
    """``git -C root <args>`` stdout, stripped; ``""`` on any failure (no git, no repo, a
    timeout). Only asked when ``root`` itself holds a ``.git`` (a directory, or the file a
    worktree has), so an unrelated repository above a wheel install is never read."""
    if not (root / ".git").exists():
        return ""
    binary = shutil.which("git")
    if not binary:
        return ""
    try:
        r = subprocess.run(
            [binary, "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def checkout_commit(root: Path | None = None) -> str:
    """The commit the checkout holds NOW (``""`` when the package is not in a checkout)."""
    return _git(root or source_root(), "rev-parse", "HEAD")


def commits_behind(root: Path | None = None, upstream: str = UPSTREAM_REF) -> int | None:
    """How many commits ``upstream`` has that ``HEAD`` does not, by the LOCAL ref (as of the
    last fetch); ``None`` when there is no checkout or no such ref."""
    out = _git(root or source_root(), "rev-list", "--count", f"HEAD..{upstream}")
    return int(out) if out.isdigit() else None


@functools.cache
def process_commit() -> str:
    """The commit THIS process runs: ``CRB_SOURCE_COMMIT``, else the checkout's commit at
    the first call. Cached for the life of the process — ``create_app`` calls it at
    start-up, so a later ``git pull`` shows up as a disagreement, not as fresh code."""
    return os.environ.get(SOURCE_COMMIT_ENV, "").strip() or checkout_commit()


def ui_stamp(dist: Path | None) -> tuple[str, str]:
    """``(commit, state)`` of the UI bundle at ``dist`` — state ∈ ``absent`` (no bundle),
    ``unstamped``, ``unreadable`` or ``stamped``."""
    if dist is None:
        return "", UI_ABSENT
    path = Path(dist) / BUILD_STAMP_FILE
    if not path.is_file():
        return "", UI_UNSTAMPED
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", UI_UNREADABLE
    commit = str(body.get("commit", "") if isinstance(body, dict) else "").strip()
    return (commit, UI_STAMPED) if commit else ("", UI_UNREADABLE)


def _short(commit: str) -> str:
    return commit[:12] if commit else "unknown"


def served_report(*, server: str, checkout: str, dist: Path | None) -> dict[str, Any]:
    """The comparison ``/health`` serves as ``served``: the three commits, the bundle's stamp
    state, ``stale`` and one sentence per disagreement (with its fix). Never a path."""
    ui_commit, ui_state = ui_stamp(dist)
    reasons: list[str] = []
    if server and checkout and server != checkout:
        reasons.append(
            f"the server was started from {_short(server)} but the checkout now holds "
            f"{_short(checkout)} — restart the server (and the worker) to run it"
        )
    reference = server or checkout
    if ui_state == UI_STAMPED and reference and ui_commit != reference:
        reasons.append(
            f"the UI bundle was built from {_short(ui_commit)} but the server runs "
            f"{_short(reference)} — rebuild it (`npm --prefix ui run build`) and restart"
        )
    elif ui_state in (UI_UNSTAMPED, UI_UNREADABLE) and reference:
        reasons.append(
            f"the UI bundle carries no readable {BUILD_STAMP_FILE} — it was built before "
            "stamping existed or outside `npm run build`, so its source cannot be named; "
            "rebuild it (`npm --prefix ui run build`)"
        )
    return {
        "server_commit": server,
        "checkout_commit": checkout,
        "ui_commit": ui_commit,
        "ui_stamp": ui_state,
        "stale": bool(reasons),
        "reasons": reasons,
    }


def probe_build(
    dist: Path | None,
    *,
    server: str | None = None,
    checkout: str | None = None,
    stale_status: str = DEGRADED,
) -> ProbeResult:
    """``build``: the served commits agree. ``stale_status`` is ``degraded`` for ``/health``
    (a stale server still serves; readiness is not lost) and ``down`` for ``crb doctor``
    (which then exits 1). Nothing to compare (no checkout, no ``CRB_SOURCE_COMMIT``) is
    ``skipped`` with the reason — unknown is never reported as fresh."""
    server = process_commit() if server is None else server
    checkout = checkout_commit() if checkout is None else checkout
    report = served_report(server=server, checkout=checkout, dist=dist)
    if report["stale"]:
        return ProbeResult("build", stale_status, "STALE: " + "; ".join(report["reasons"]), report)
    if not (server or checkout):
        return ProbeResult(
            "build",
            SKIPPED,
            f"source commit unknown: not a git checkout and {SOURCE_COMMIT_ENV} is unset — "
            "nothing to compare (an image is stamped at build time with that variable)",
            report,
        )
    ui = (
        "UI built from the same commit"
        if report["ui_stamp"] == UI_STAMPED
        else "no UI bundle served"
    )
    return ProbeResult("build", OK, f"serving {_short(server or checkout)} · {ui}", report)


__all__ = [
    "BUILD_STAMP_FILE",
    "SOURCE_COMMIT_ENV",
    "UI_ABSENT",
    "UI_STAMPED",
    "UI_UNREADABLE",
    "UI_UNSTAMPED",
    "UPSTREAM_REF",
    "checkout_commit",
    "commits_behind",
    "probe_build",
    "process_commit",
    "served_report",
    "source_root",
    "ui_stamp",
]
