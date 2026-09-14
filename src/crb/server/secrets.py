"""Operator-supplied secrets for the API: the thin admin wrapper over
:mod:`crb.core.secrets_file`.

What lives here and nowhere else
--------------------------------
* The registry of secrets the API is willing to hold (:data:`SECRETS`) — today one:
  ``claude_code_oauth_token``, the ``claude setup-token`` credential a ``cli``-mode
  ``claude_code`` build forwards as ``CLAUDE_CODE_OAUTH_TOKEN``.
* Shape validation per secret (:func:`validate_claude_code_token`): prefix, length
  bounds, alphabet. A shape check never proves a token works — :func:`verify` does,
  by running the CLI once through the builder's own environment.
* The verify rate limit (:class:`VerifyRateLimiter`): one probe per
  :data:`VERIFY_MIN_INTERVAL_S` for the whole deployment, so the button cannot be
  used to burn subscription quota.

Invariants
----------
* A value enters through ``SecretsFile.set`` and leaves only as an environment
  variable of a child ``claude`` process. It is never in the database, an event, an
  evidence pack, a log line, an exception message or an API response —
  :class:`SecretStatus` (presence, ≤4-char fingerprint, ``set_at``/``set_by``) is
  all the API ever reports.
* Storage is :class:`~crb.core.secrets_file.SecretsStore` under ``CRB_SECRETS_DIR``
  or ``<Settings.home>/secrets`` (the same resolution the builder uses with
  ``CRB_HOME``), so the API host and a worker that shares ``CRB_HOME`` see one file.
  A worker on another host needs the token in its own environment or its own
  ``CRB_SECRETS_DIR`` mount — see ``docs/OPERATOR.md``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from crb.builders.claude_code import (
    CLI_TOKEN_SECRET,
    VERIFY_TIMEOUT_S,
    LoginCheck,
    verify_login,
)
from crb.core.secrets_file import (
    SECRETS_DIR_ENV,
    SECRETS_SUBDIR,
    SecretsError,
    SecretsInsecure,
    SecretsStore,
    SecretStatus,
)
from crb.server.deps import SettingsDep
from crb.server.settings import Settings

log = logging.getLogger("crb.server.secrets")

#: ``claude setup-token`` tokens: a fixed prefix, then a base64url-ish body.
CLAUDE_CODE_TOKEN_PREFIX = "sk-ant-oat01-"  # noqa: S105 — a prefix, not a value
CLAUDE_CODE_TOKEN_MIN_LEN = 40
CLAUDE_CODE_TOKEN_MAX_LEN = 512
_CLAUDE_CODE_TOKEN_RE = re.compile(r"^sk-ant-oat01-[A-Za-z0-9_-]+$")

#: Minimum seconds between two verify probes (deployment-wide).
VERIFY_MIN_INTERVAL_S = 10.0


def validate_claude_code_token(token: str) -> str:
    """The stripped token, or ``ValueError`` naming the *shape* problem (never the value)."""
    cleaned = (token or "").strip()
    if not cleaned.startswith(CLAUDE_CODE_TOKEN_PREFIX):
        raise ValueError(
            f"a Claude Code token starts with {CLAUDE_CODE_TOKEN_PREFIX!r} "
            "(mint one with `claude setup-token`)"
        )
    if len(cleaned) < CLAUDE_CODE_TOKEN_MIN_LEN:
        raise ValueError(f"token too short (< {CLAUDE_CODE_TOKEN_MIN_LEN} characters)")
    if len(cleaned) > CLAUDE_CODE_TOKEN_MAX_LEN:
        raise ValueError(f"token too long (> {CLAUDE_CODE_TOKEN_MAX_LEN} characters)")
    if not _CLAUDE_CODE_TOKEN_RE.match(cleaned):
        raise ValueError("token contains characters outside [A-Za-z0-9_-]")
    return cleaned


@dataclass(frozen=True)
class SecretSpec:
    """A secret the API will hold: its file name, a label, and its shape validator."""

    name: str
    label: str
    validate: Callable[[str], str]


SECRETS: dict[str, SecretSpec] = {
    CLI_TOKEN_SECRET: SecretSpec(
        name=CLI_TOKEN_SECRET,
        label="Claude Code login (claude setup-token)",
        validate=validate_claude_code_token,
    ),
}


def secrets_dir_for(settings: Settings) -> Path:
    """``CRB_SECRETS_DIR`` → ``<Settings.home>/secrets`` (``Settings.home`` is ``CRB_HOME``)."""
    explicit = (os.environ.get(SECRETS_DIR_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path(settings.home).expanduser() / SECRETS_SUBDIR


class SecretsFile:
    """The API's view of the store: registry-checked names, statuses, never values out."""

    def __init__(self, directory: Path) -> None:
        self._store = SecretsStore(directory)

    @classmethod
    def for_settings(cls, settings: Settings) -> SecretsFile:
        return cls(secrets_dir_for(settings))

    @property
    def path(self) -> Path:
        return self._store.path

    def __repr__(self) -> str:
        return f"SecretsFile({str(self.path)!r})"

    @staticmethod
    def spec(name: str) -> SecretSpec:
        try:
            return SECRETS[name]
        except KeyError:
            raise KeyError(f"unknown secret {name!r}; known: {sorted(SECRETS)}") from None

    def set(self, name: str, value: str, *, set_by: str = "") -> SecretStatus:
        """Validate the shape, store owner-only, log the *fingerprint*. Raises
        ``ValueError`` (shape) or :class:`SecretsInsecure` (directory refused)."""
        spec = self.spec(name)
        cleaned = spec.validate(value)
        status = self._store.set(name, cleaned, set_by=set_by)
        log.info(
            "secret set",
            extra={"secret": name, "fingerprint": status.fingerprint, "set_by": set_by},
        )
        return status

    def get(self, name: str) -> str | None:
        """The value — for the verify probe and nothing else."""
        self.spec(name)
        return self._store.get(name)

    def delete(self, name: str) -> SecretStatus:
        self.spec(name)
        existed = self._store.delete(name)
        log.info("secret removed", extra={"secret": name, "existed": existed})
        return self._store.status(name)

    def status(self, name: str) -> SecretStatus:
        self.spec(name)
        return self._store.status(name)

    def statuses(self) -> list[SecretStatus]:
        """Every registered secret's status; an insecure file is reported as absent
        with the reason in the log, never as a value."""
        out: list[SecretStatus] = []
        for name in SECRETS:
            try:
                out.append(self._store.status(name))
            except SecretsError as exc:
                log.warning("secret unreadable", extra={"secret": name, "reason": str(exc)})
                out.append(SecretStatus(name=name, present=False))
        return out

    def verify(self, name: str, *, timeout_s: int = VERIFY_TIMEOUT_S) -> LoginCheck | None:
        """Run the builder's login probe with the stored token; ``None`` when absent."""
        value = self.get(name)
        if not value:
            return None
        return verify_login(token=value, timeout_s=timeout_s)


class VerifyRateLimiter:
    """At most one verify per ``min_interval_s``, deployment-wide. Thread-safe."""

    def __init__(
        self,
        min_interval_s: float = VERIFY_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None

    def acquire(self) -> float | None:
        """``None`` and mark the slot taken, or the seconds until the next slot."""
        now = self._clock()
        with self._lock:
            if self._last is not None:
                remaining = self.min_interval_s - (now - self._last)
                if remaining > 0:
                    return remaining
            self._last = now
            return None


def get_secrets_file(settings: SettingsDep) -> SecretsFile:
    return SecretsFile.for_settings(settings)


def get_verify_limiter(request: Request) -> VerifyRateLimiter:
    """One limiter per app, created lazily on ``app.state`` (the app factory is not ours)."""
    limiter = getattr(request.app.state, "verify_limiter", None)
    if limiter is None:
        limiter = VerifyRateLimiter()
        request.app.state.verify_limiter = limiter
    return limiter


SecretsDep = Annotated[SecretsFile, Depends(get_secrets_file)]
VerifyLimiterDep = Annotated[VerifyRateLimiter, Depends(get_verify_limiter)]

__all__ = [
    "CLAUDE_CODE_TOKEN_MAX_LEN",
    "CLAUDE_CODE_TOKEN_MIN_LEN",
    "CLAUDE_CODE_TOKEN_PREFIX",
    "SECRETS",
    "VERIFY_MIN_INTERVAL_S",
    "SecretSpec",
    "SecretsDep",
    "SecretsFile",
    "SecretsInsecure",
    "VerifyLimiterDep",
    "VerifyRateLimiter",
    "get_secrets_file",
    "get_verify_limiter",
    "secrets_dir_for",
    "validate_claude_code_token",
]
