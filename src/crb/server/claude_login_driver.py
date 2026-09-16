"""The detached helper behind a Claude login session: runs ``claude setup-token`` in a PTY.

Started by :class:`crb.server.claude_login.LoginBroker` as ``python -m
crb.server.claude_login_driver <session dir>``, in its own process session so nothing that
happens to the API can interrupt a sign-in. It talks to the API only through files in the
session directory:

* reads ``meta.json`` (the binary, the secrets directory, the TTL);
* writes ``url.txt`` + ``status.json = awaiting_code`` when the CLI has printed its
  authorisation URL;
* polls for ``code.txt`` (written by the API when the person pastes the code), types it into
  the CLI and deletes the file at once;
* reads the token off the CLI's output, stores it through
  :class:`crb.core.secrets_file.SecretsStore` (owner-only file, same registry name the
  manual path uses), scrubs its buffer, writes ``status.json = done`` with the token's
  four-character fingerprint; or ``failed`` with a redacted, capped detail.

The token is never written anywhere but the secrets store; the pasted code is never
written anywhere but the PTY. Terminal escape sequences are stripped before any text is
matched or reported.

Navigation
----------
What it is:   The ``claude setup-token`` PTY driver — the only process that ever sees the
              minted token before the secrets store does.
What it does: Runs the CLI, publishes the sign-in URL, types the pasted code, stores the
              token, reports state; gives up at the session TTL (``expired``) or on SIGTERM
              (``cancelled``); exits on its own.
How:          ``pty.fork`` → non-blocking reads → ``URL_RE`` / ``TOKEN_RE`` over a stripped
              buffer → ``SecretsStore.set``; ``status.json`` written atomically, mode 0600.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/claude_login.py (the broker that spawns and reads this),
              src/crb/core/secrets_file.py (the store), src/crb/builders/claude_code.py
              (``CLI_TOKEN_SECRET``, ``CLAUDE_CODE_TOKEN_PREFIX`` — the name and the shape),
              src/crb/core/redact.py (the detail that reaches the API is redacted)
Tested by:    tests/test_server_claude_login.py (a fake ``claude`` script replays the CLI's
              transcript: URL, paste prompt, token — and the failure wordings)
Touch when:   the CLI changes its sign-in transcript (the URL host/path, the paste prompt, the
              token prefix); never for a new repository.
"""

from __future__ import annotations

import contextlib
import json
import os
import pty
import re
import select
import signal
import sys
import time
from pathlib import Path

from crb.core.redact import redact_and_cap
from crb.core.secrets_file import SecretsStore
from crb.server.claude_login import (
    STATE_AWAITING_CODE,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_EXPIRED,
    STATE_FAILED,
    URL_RE,
)

#: The secret's registry name and the token shape (kept in step with the builder module;
#: imported lazily there to keep this helper's start-up cheap).
SECRET_NAME = "claude_code_oauth_token"  # noqa: S105 — a name, not a value
TOKEN_RE = re.compile(r"sk-ant-oat01-[A-Za-z0-9_-]{20,}")
#: The CLI's prompt for the code; matched loosely (the TUI drops spaces on a dumb terminal).
PASTE_PROMPT = re.compile(r"paste\s*code\s*here", re.I)
#: Wordings the CLI uses when the exchange fails; reported (redacted) as ``failed``.
FAILURE_HINTS = re.compile(
    r"invalid|expired|denied|unauthori[sz]ed|error|failed|subscription|not logged in", re.I
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(path)


def _status(sdir: Path, state: str, detail: str = "", **extra: str) -> None:
    _write_private(sdir / "status.json", json.dumps({"state": state, "detail": detail, **extra}))


def _scrub(text: str) -> str:
    """Strip terminal control sequences and any token-shaped run before the text is kept."""
    return TOKEN_RE.sub("sk-ant-oat01-[REDACTED]", ANSI_RE.sub("", text))


def run(session_dir: str) -> int:
    sdir = Path(session_dir)
    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    binary = str(meta["binary"])
    ttl_s = float(meta.get("ttl_s", 600))
    deadline = time.monotonic() + ttl_s
    store = SecretsStore(meta["secrets_dir"])
    cancelled = {"flag": False}

    def _on_term(_sig: int, _frame: object) -> None:
        cancelled["flag"] = True

    signal.signal(signal.SIGTERM, _on_term)

    pid, fd = pty.fork()
    if pid == 0:  # the CLI: never let it open a browser on the server, keep the TUI plain
        os.environ["BROWSER"] = "/usr/bin/true"
        os.environ["TERM"] = "dumb"
        os.environ["NO_COLOR"] = "1"
        try:
            os.execvp(binary, [binary, "setup-token"])  # noqa: S606 — the whole point of this helper
        except OSError:
            os._exit(127)

    buf = ""
    url_sent = False
    code_sent = False
    typed = ""
    outcome = STATE_FAILED
    detail = "the claude CLI exited before printing a token"
    fingerprint = ""
    try:
        while True:
            if cancelled["flag"]:
                outcome, detail = STATE_CANCELLED, "cancelled"
                break
            if time.monotonic() > deadline:
                outcome, detail = STATE_EXPIRED, "the sign-in was not completed in time"
                break
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 8192)
                except OSError:
                    chunk = b""
                if not chunk:
                    break  # the CLI exited
                buf += ANSI_RE.sub("", chunk.decode("utf-8", "replace"))
            # the token: the whole point — store it, scrub it, done
            m = TOKEN_RE.search(buf)
            if m:
                token = m.group(0)
                buf = _scrub(buf)
                status = store.set(SECRET_NAME, token, set_by=f"login:{meta.get('started_by', '')}")
                token = ""
                fingerprint = status.fingerprint
                outcome, detail = STATE_DONE, "token stored"
                break
            if not url_sent:
                um = URL_RE.search(buf)
                if um:
                    _write_private(sdir / "url.txt", um.group(0) + "\n")
                    _status(
                        sdir,
                        STATE_AWAITING_CODE,
                        "sign in on Anthropic's page, then paste the code it shows",
                    )
                    url_sent = True
                    buf = buf[um.end() :]
            elif not code_sent:
                code_file = sdir / "code.txt"
                if code_file.exists():
                    typed = code_file.read_text(encoding="utf-8").strip()
                    code_file.unlink(missing_ok=True)
                    os.write(fd, (typed + "\n").encode())
                    code_sent = True
                    buf = ""
            elif FAILURE_HINTS.search(buf) and len(buf) > 40:
                # the CLI said something after the code that is not a token: report it
                # redacted and capped, and give the CLI a moment in case the token follows
                time.sleep(1.0)
                try:
                    r2, _, _ = select.select([fd], [], [], 0.5)
                    if r2:
                        buf += ANSI_RE.sub("", os.read(fd, 8192).decode("utf-8", "replace"))
                except OSError:
                    pass
                if not TOKEN_RE.search(buf):
                    outcome = STATE_FAILED
                    # the PTY echoes what was typed: the code never leaves this process
                    said = _scrub(buf).replace(typed, "[code]") if typed else _scrub(buf)
                    detail = "the claude CLI refused the code: " + redact_and_cap(
                        " ".join(said.split())[-400:], max_chars=400
                    )
                    break
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.3)
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        with contextlib.suppress(OSError):
            os.close(fd)
        (sdir / "code.txt").unlink(missing_ok=True)
        (sdir / "url.txt").unlink(missing_ok=True)
        buf = ""
        typed = ""
        _status(sdir, outcome, detail, fingerprint=fingerprint)
    return 0 if outcome == STATE_DONE else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m crb.server.claude_login_driver <session dir>", file=sys.stderr)
        return 2
    return run(args[0])


if __name__ == "__main__":
    sys.exit(main())
