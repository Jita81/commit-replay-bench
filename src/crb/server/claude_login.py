"""Sign in to a Claude account from the front end: a server-driven ``claude setup-token``.

The Claude Code CLI's long-lived credential is minted by ``claude setup-token``: the CLI
prints an authorisation URL on ``claude.com``, the person signs in and approves in a
browser, Anthropic's page then shows a short code, the person pastes it back, and the CLI
prints the token (``sk-ant-oat01-…``). Until now an admin ran that in a terminal and pasted
the token into Settings. This module runs the same flow *behind the API*:

1. ``POST /settings/secrets/claude-code-token/login`` starts a **login session**: a small
   detached helper (:mod:`crb.server.claude_login_driver`) runs ``claude setup-token`` in
   a pseudo-terminal and writes the authorisation URL to the session directory. The
   response carries the URL; the front end opens it in a new tab.
2. The person approves on Anthropic's page and copies the code it shows.
3. ``POST …/login/{id}/code`` hands the code to the helper, which types it into the CLI.
4. The helper reads the token off the CLI's output and stores it through the same
   owner-only :class:`~crb.core.secrets_file.SecretsStore` the manual path uses. **The
   token never travels to the browser and never appears in a response, an event or a log**
   — the front end only ever sees a :class:`SessionState`.

Why a detached helper and a directory, not an in-process object: the API may run several
uvicorn workers, and the request that starts the session and the one that delivers the code
can land on different processes. The session directory (owner-only, under the secrets
directory) is the shared state: ``url.txt`` (the helper → the API), ``code.txt`` (the API →
the helper; removed the moment it is read), ``status.json`` (the helper → everyone). The
helper is started with its own session id so an API restart does not kill a login in
progress; it exits on its own after :data:`SESSION_TTL_S`.

Navigation
----------
What it is:   The login-session broker: start a ``claude setup-token`` helper, read its state,
              deliver the pasted code, cancel. The HTTP surface is in
              src/crb/server/routes/admin.py.
What it does: ``LoginBroker.start`` creates the owner-only session directory, spawns the driver
              detached and waits for the authorisation URL; ``state`` reads ``status.json``;
              ``submit_code`` validates the code's shape and writes ``code.txt``; ``cancel``
              signals the helper. One session per deployment at a time (a second start while
              one is pending is refused); sessions expire after ``SESSION_TTL_S``.
How:          Files under ``<secrets dir>/claude-code-login/<id>/`` with mode 0700/0600;
              ``subprocess.Popen(..., start_new_session=True)`` of ``python -m
              crb.server.claude_login_driver``; the state file is the single source of truth.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/claude_login_driver.py (the helper this spawns),
              src/crb/core/secrets_file.py (where the helper stores the token),
              src/crb/server/secrets.py (``secrets_dir_for`` — the parent directory; the
              registry entry the token is stored under), src/crb/builders/claude_code.py
              (``CLI_TOKEN_SECRET``, ``verify_login`` — the consumer), docs/OPERATOR.md
              (the operator's walkthrough), docs/SECURITY.md#33-credentials
Tested by:    tests/test_server_claude_login.py (a fake ``claude`` script drives every path)
Touch when:   the CLI changes the wording of its sign-in prompt (``URL_RE`` / the driver's
              ``PASTE_PROMPT``) or its token prefix; never for a new repository.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import secrets as _secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Where a session lives, under the secrets directory (shared by every API worker).
SESSIONS_SUBDIR = "claude-code-login"
#: A session that has not finished by then is abandoned by the helper and reported ``expired``.
SESSION_TTL_S = 600
#: How long ``start`` waits for the CLI to print its authorisation URL.
URL_WAIT_S = 30.0
#: The authorisation URL the CLI prints (host and path as of Claude Code 2.1; the query is
#: opaque to us and passed to the browser verbatim).
URL_RE = re.compile(r"https://claude\.com/[A-Za-z0-9_./-]*oauth/authorize\?[^\s]+")
#: What the person pastes back from Anthropic's page: the code, optionally ``#state``.
CODE_RE = re.compile(r"^[A-Za-z0-9_\-#]{8,512}$")

STATE_PENDING_URL = "pending_url"  # helper started, URL not yet printed
STATE_AWAITING_CODE = "awaiting_code"  # URL known; waiting for the person's code
STATE_EXCHANGING = "exchanging"  # code typed; waiting for the CLI to print the token
STATE_DONE = "done"  # token stored
STATE_FAILED = "failed"  # the CLI refused (bad code, no subscription…) — see ``detail``
STATE_EXPIRED = "expired"
STATE_CANCELLED = "cancelled"
TERMINAL_STATES = frozenset({STATE_DONE, STATE_FAILED, STATE_EXPIRED, STATE_CANCELLED})


class LoginError(RuntimeError):
    """A session could not be started, found or advanced; ``code`` names the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SessionState:
    """What the API serves about a session — never a code, never a token."""

    id: str
    state: str
    url: str
    detail: str
    started_at: str
    expires_at: str
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "url": self.url,
            "detail": self.detail,
            "started_at": self.started_at,
            "expires_at": self.expires_at,
            "fingerprint": self.fingerprint,
        }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _write_private(path: Path, text: str) -> None:
    """Create-or-replace ``path`` with mode 0600 (never a moment world-readable)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(path)


class LoginBroker:
    """Start, read, advance and cancel login sessions under ``secrets_dir``."""

    def __init__(
        self,
        secrets_dir: Path,
        *,
        claude_binary: str = "",
        python: str = sys.executable,
        driver_module: str = "crb.server.claude_login_driver",
        ttl_s: int = SESSION_TTL_S,
        url_wait_s: float = URL_WAIT_S,
    ) -> None:
        self.secrets_dir = Path(secrets_dir)
        self.claude_binary = claude_binary
        self.python = python
        self.driver_module = driver_module
        self.ttl_s = ttl_s
        self.url_wait_s = url_wait_s

    # --- paths ------------------------------------------------------------------
    @property
    def sessions_dir(self) -> Path:
        return self.secrets_dir / SESSIONS_SUBDIR

    def session_dir(self, session_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise LoginError("not_found", "no such login session")
        return self.sessions_dir / session_id

    # --- lifecycle ----------------------------------------------------------------
    def start(self, *, started_by: str) -> SessionState:
        """Spawn the helper and wait for the authorisation URL. Refuses while another
        session is pending (``login_in_progress``) or when the CLI is absent
        (``cli_missing``)."""
        binary = shutil.which(self.claude_binary or "claude") or ""
        if not binary:
            raise LoginError(
                "cli_missing",
                "the claude CLI is not on the API host's PATH"
                if not self.claude_binary
                else f"the configured claude binary {self.claude_binary!r} is not executable",
            )
        active = self.active()
        if active is not None:
            raise LoginError(
                "login_in_progress",
                f"a login session ({active.id[:8]}) is {active.state}; finish or cancel it first",
            )
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.sessions_dir, 0o700)
        session_id = _secrets.token_hex(16)
        sdir = self.session_dir(session_id)
        sdir.mkdir(mode=0o700)
        started = _now_iso()
        expires = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + self.ttl_s))
        meta = {
            "id": session_id,
            "started_by": started_by,
            "started_at": started,
            "expires_at": expires,
            "ttl_s": self.ttl_s,
            "binary": binary,
            "secrets_dir": str(self.secrets_dir),
        }
        _write_private(sdir / "meta.json", json.dumps(meta))
        _write_private(
            sdir / "status.json",
            json.dumps({"state": STATE_PENDING_URL, "detail": "starting the claude CLI"}),
        )
        # Detached: its own session id, no inherited stdio — an API restart or a request
        # timeout must not kill a sign-in the person is half-way through.
        proc = subprocess.Popen(
            [self.python, "-m", self.driver_module, str(sdir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        _write_private(sdir / "pid", str(proc.pid))
        deadline = time.monotonic() + self.url_wait_s
        while time.monotonic() < deadline:
            st = self.state(session_id)
            if st.state == STATE_AWAITING_CODE:
                return st
            if st.state in TERMINAL_STATES:
                detail = (
                    "the session expired before the claude CLI printed its sign-in URL"
                    if st.state == STATE_EXPIRED
                    else st.detail or "the claude CLI exited before printing a sign-in URL"
                )
                raise LoginError("cli_failed", detail)
            time.sleep(0.2)
        self.cancel(session_id, reason="the claude CLI did not print a sign-in URL in time")
        raise LoginError("cli_timeout", "the claude CLI did not print a sign-in URL in time")

    def state(self, session_id: str) -> SessionState:
        """The session as recorded by the helper; ``expired`` once past its TTL."""
        sdir = self.session_dir(session_id)
        if not (sdir / "meta.json").exists():
            raise LoginError("not_found", "no such login session")
        meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
        try:
            status = json.loads((sdir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            status = {"state": STATE_PENDING_URL, "detail": ""}
        state = str(status.get("state", STATE_PENDING_URL))
        url = ""
        if state == STATE_AWAITING_CODE:
            with_url = sdir / "url.txt"
            url = with_url.read_text(encoding="utf-8").strip() if with_url.exists() else ""
        if state not in TERMINAL_STATES and time.time() > _parse_iso(meta["expires_at"]):
            state = STATE_EXPIRED
        return SessionState(
            id=session_id,
            state=state,
            url=url,
            detail=str(status.get("detail", "")),
            started_at=str(meta.get("started_at", "")),
            expires_at=str(meta.get("expires_at", "")),
            fingerprint=str(status.get("fingerprint", "")),
        )

    def active(self) -> SessionState | None:
        """The one non-terminal session, if any (newest first)."""
        if not self.sessions_dir.exists():
            return None
        for sdir in sorted(
            self.sessions_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            if not sdir.is_dir() or not (sdir / "meta.json").exists():
                continue
            try:
                st = self.state(sdir.name)
            except LoginError:
                continue
            if st.state not in TERMINAL_STATES:
                return st
        return None

    def submit_code(self, session_id: str, code: str) -> SessionState:
        """Hand the pasted code to the helper. The code is written once, owner-only, and
        the helper deletes the file as soon as it has typed it."""
        st = self.state(session_id)
        if st.state != STATE_AWAITING_CODE:
            raise LoginError("wrong_state", f"the session is {st.state}, not awaiting a code")
        cleaned = code.strip()
        if not CODE_RE.fullmatch(cleaned):
            raise LoginError("invalid_code", "that does not look like the code Anthropic shows")
        _write_private(self.session_dir(session_id) / "code.txt", cleaned + "\n")
        _write_private(
            self.session_dir(session_id) / "status.json",
            json.dumps({"state": STATE_EXCHANGING, "detail": "exchanging the code for a token"}),
        )
        return self.state(session_id)

    def cancel(self, session_id: str, *, reason: str = "cancelled by the operator") -> SessionState:
        """Stop the helper (SIGTERM its process group) and mark the session cancelled."""
        sdir = self.session_dir(session_id)
        st = self.state(session_id)
        if st.state in TERMINAL_STATES:
            return st
        pid_file = sdir / "pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ValueError, OSError, ProcessLookupError):
                pass
        for name in ("code.txt", "url.txt"):
            (sdir / name).unlink(missing_ok=True)
        _write_private(
            sdir / "status.json", json.dumps({"state": STATE_CANCELLED, "detail": reason})
        )
        return self.state(session_id)

    def sweep(self, *, keep: int = 5) -> int:
        """Delete terminal session directories beyond the newest ``keep``; returns the count."""
        if not self.sessions_dir.exists():
            return 0
        dirs = sorted(
            (p for p in self.sessions_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        removed = 0
        for p in dirs[keep:]:
            try:
                if self.state(p.name).state in TERMINAL_STATES:
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
            except LoginError:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        return removed


def _parse_iso(value: str) -> float:
    """``2026-09-16T10:00:00+00:00`` → epoch seconds (UTC only, as this module writes it;
    ``calendar.timegm`` reads the struct as UTC — ``mktime`` would apply the host's DST)."""
    try:
        return float(calendar.timegm(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return 0.0


def dir_is_private(path: Path) -> bool:
    """True when ``path`` is a directory with no group/other bits (the store's rule)."""
    try:
        st = path.stat()
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not (st.st_mode & 0o077)


__all__ = [
    "CODE_RE",
    "SESSION_TTL_S",
    "STATE_AWAITING_CODE",
    "STATE_CANCELLED",
    "STATE_DONE",
    "STATE_EXCHANGING",
    "STATE_EXPIRED",
    "STATE_FAILED",
    "STATE_PENDING_URL",
    "TERMINAL_STATES",
    "URL_RE",
    "LoginBroker",
    "LoginError",
    "SessionState",
    "dir_is_private",
]
