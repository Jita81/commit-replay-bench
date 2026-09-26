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
matched or reported. The CLI itself runs with an allowlisted environment
(:func:`cli_environment`: ``PATH``, ``HOME``, a plain terminal, a no-op browser and a
``CLAUDE_CONFIG_DIR`` used by this sign-in only) — this helper inherits the API process's
environment, and the secret key, the database URL and the OIDC client secret in it are not
the CLI's to read (assessment 2026-09-25, D3).

Navigation
----------
What it is:   The ``claude setup-token`` PTY driver — the only process that ever sees the
              minted token before the secrets store does.
What it does: Runs the CLI, publishes the sign-in URL, types the pasted code, stores the
              token, reports state; gives up at the session TTL (``expired``) or on SIGTERM
              (``cancelled``); exits on its own.
How:          ``cli_environment`` → ``pty.fork`` + ``execvpe`` → non-blocking reads → ``URL_RE`` / ``TOKEN_RE`` over a stripped
              buffer → ``SecretsStore.set``; ``status.json`` written atomically, mode 0600.
Layer:        server — docs/ARCHITECTURE.md#71-security
ADRs:         none
Works with:   src/crb/server/claude_login.py (the broker that spawns and reads this),
              src/crb/core/secrets_file.py (the store), src/crb/builders/claude_code.py
              (``CLI_TOKEN_SECRET``, ``CLAUDE_CODE_TOKEN_PREFIX`` — the name and the shape),
              src/crb/core/redact.py (the detail that reaches the API is redacted)
Tested by:    tests/test_server_claude_login.py (a fake ``claude`` script replays the CLI's
              transcript: URL, paste prompt, token — and the failure wordings; another dumps
              the environment it was given)
Touch when:   the CLI changes its sign-in transcript (the URL host/path, the paste prompt, the
              token prefix) or needs another variable to run (add it to ``CLI_PASSTHROUGH``
              or ``CLI_NETWORK_PASSTHROUGH`` with the reason, never the whole environment);
              never for a new repository.
"""

from __future__ import annotations

import contextlib
import json
import os
import pty
import re
import select
import shutil
import signal
import sys
import time
from collections.abc import Mapping
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
#: The only variables the CLI inherits from the helper's environment (see
#: :func:`cli_environment`), and the ones it is given fixed values for.
CLI_PASSTHROUGH: tuple[str, ...] = ("PATH", "HOME")
#: How the host reaches the internet — an outbound proxy (both spellings of the convention)
#: and a private certificate authority. The sign-in has to reach the service, so these pass
#: through too; the allowlist limits what the CLI can READ, not where it can connect. A
#: proxy URL may carry the proxy's own credential: that is the host's egress credential,
#: which the CLI needs to connect at all.
CLI_NETWORK_PASSTHROUGH: tuple[str, ...] = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
CLI_FIXED: Mapping[str, str] = {"TERM": "dumb", "NO_COLOR": "1", "BROWSER": "/usr/bin/true"}
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


def cli_environment(parent: Mapping[str, str], config_dir: Path) -> dict[str, str]:
    """The whole environment ``claude setup-token`` runs with: ``PATH`` and ``HOME`` from
    ``parent`` (so the CLI can find itself and its runtime), a plain TUI (``TERM=dumb``,
    ``NO_COLOR``), a browser that does nothing (it must never open one on the server), and
    ``CLAUDE_CONFIG_DIR`` pointed at ``config_dir`` — a directory used by this sign-in only
    and removed when it ends, so the CLI neither reads nor writes the host account's own
    Claude configuration. The host's proxy and certificate-authority variables
    (:data:`CLI_NETWORK_PASSTHROUGH`) pass through so the sign-in works behind a proxy.
    Nothing else: the API process holds the secret key, the database URL and the OIDC
    client secret, and none of that is the CLI's business (D3)."""
    env = {
        key: parent[key] for key in (*CLI_PASSTHROUGH, *CLI_NETWORK_PASSTHROUGH) if key in parent
    }
    env.update(CLI_FIXED)
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


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

    config_dir = sdir / "cli-config"
    config_dir.mkdir(mode=0o700, exist_ok=True)
    child_env = cli_environment(os.environ, config_dir)

    pid, fd = pty.fork()
    if pid == 0:  # the CLI: the allowlisted environment only (D3)
        try:
            os.execvpe(binary, [binary, "setup-token"], child_env)  # noqa: S606 — the point
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
        shutil.rmtree(config_dir, ignore_errors=True)
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
