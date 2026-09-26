"""Owner-only secrets on disk — the one place a credential the operator hands the
product may rest.

Layout (``CRB_SECRETS_DIR`` → ``$CRB_HOME/secrets`` → ``./.crb/secrets``)::

    <dir>/                      0700, owned by the process user
      <name>                    0600 — the raw value, nothing else
      <name>.meta.json          0600 — {set_at, set_by}; never the value

Invariants
----------
* **Values never leave as text.** :meth:`SecretsStore.status` reports presence, a
  fingerprint of at most :data:`FINGERPRINT_CHARS` trailing characters, and who set
  it when; ``repr`` / ``str`` of anything here never include a value; nothing logs.
* **Owner-only or nothing.** A store refuses to *write* unless its directory is a
  real directory owned by the current user with no group/other bits; it refuses to
  *read* a value file that has group/other bits (``SecretsInsecure``). It never
  fixes permissions silently — a widened mode is evidence, not a nuisance.
* **Atomic.** A value is written to an ``O_EXCL`` 0600 temp file in the same
  directory, fsynced, then renamed over the target: a reader sees the old value
  or the new one, never a torn one, and a crash leaves no half-written secret.
* **Mount-friendly.** A value file with no ``.meta.json`` (an operator-provided
  mount such as a Secrets Store CSI volume pointed at by ``CRB_SECRETS_DIR``) is
  read like any other; its ``set_at`` is the file's mtime and ``set_by`` is empty.
* Standard library only (``crb.core``): both the builders and the server use it.

Navigation
----------
What it is:   The on-disk secrets store — ``SecretsStore`` (set / get / delete / status of
              named, owner-only files) and the directory resolution every reader shares.
What it does: Keeps an operator-supplied credential (today: the Claude Code login token)
              as a 0600 file under a 0700 directory; refuses to write into, or read from,
              anything group- or world-accessible; writes atomically; reports presence and
              a four-character fingerprint but never a value; reads a mounted file with no
              metadata as an ordinary secret.
How:          ``resolve_secrets_dir`` (``CRB_SECRETS_DIR`` → ``$CRB_HOME/secrets`` →
              ``./.crb/secrets``) → ``validate_name`` (closed alphabet, never a path) →
              ``_check_dir_for_write`` / ``_check_file_for_read`` (stat, mode bits, owner)
              → ``_write_atomic`` (``mkstemp`` 0600, fsync, rename, fsync the directory).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/server/secrets.py (the server's view: which names exist and the
              verify step), src/crb/server/routes/admin.py (Settings → Claude Code login),
              src/crb/builders/claude_code.py (reads the token for ``auth: cli``),
              src/crb/cli/commands/service.py (``crb doctor`` reports the store's state)
Tested by:    tests/test_server_secrets.py, tests/test_builders_claude_code.py,
              tests/test_cli_doctor.py
Touch when:   never for a new repository; a new secret name is added where it is consumed
              (the store is name-agnostic) and documented in
              docs/SECURITY.md#331-secrets-at-rest--crbcoresecrets_file-crbserversecrets;
              never relax a permission check to accommodate a host — fix the mount.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SECRETS_DIR_ENV = "CRB_SECRETS_DIR"
HOME_ENV = "CRB_HOME"
DEFAULT_HOME = ".crb"
SECRETS_SUBDIR = "secrets"
META_SUFFIX = ".meta.json"
META_SCHEMA = "secret-meta.v1"
#: The fingerprint is the trailing characters of the value — never more than this.
FINGERPRINT_CHARS = 4
#: A value shorter than this gets no fingerprint at all (four of eight is half the secret).
MIN_FINGERPRINT_VALUE_LEN = 12
#: Names are a closed alphabet so a name can never be a path.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
#: Group/other permission bits; any of them set on a secret file or dir is insecure.
_INSECURE_BITS = 0o077
DIR_MODE = 0o700
FILE_MODE = 0o600


class SecretsError(Exception):
    """Base class; the message never carries a value."""


class SecretsInsecure(SecretsError):
    """The directory or file is readable by group/other, not owned by us, or not a
    regular file/directory. Fail closed: refuse to read or write."""


class SecretsNameError(SecretsError, ValueError):
    """A name outside :data:`NAME_RE`."""


def resolve_secrets_dir(env: Mapping[str, str] | None = None) -> Path:
    """``CRB_SECRETS_DIR`` → ``$CRB_HOME/secrets`` → ``./.crb/secrets`` (never created)."""
    e = os.environ if env is None else env
    explicit = (e.get(SECRETS_DIR_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home = (e.get(HOME_ENV) or "").strip() or DEFAULT_HOME
    return Path(home).expanduser() / SECRETS_SUBDIR


def fingerprint(value: str) -> str:
    """The last :data:`FINGERPRINT_CHARS` characters, or ``""`` for a short value."""
    if len(value) < MIN_FINGERPRINT_VALUE_LEN:
        return ""
    return value[-FINGERPRINT_CHARS:]


def validate_name(name: str) -> str:
    """``name`` if it is in the closed alphabet, else :class:`SecretsNameError` — so a
    name can never carry a separator, a dot-segment or a metadata suffix."""
    if not NAME_RE.match(name or ""):
        raise SecretsNameError(f"invalid secret name {name!r}: expected {NAME_RE.pattern}")
    return name


def _utc_now() -> str:
    return _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds")


def _mtime_iso(st: os.stat_result) -> str:
    """A mounted value file's ``set_at``: its modification time, in UTC."""
    return _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SecretStatus:
    """What anyone may learn about a stored secret. Never the value."""

    name: str
    present: bool
    fingerprint: str = ""
    set_at: str = ""
    set_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "present": self.present,
            "fingerprint": self.fingerprint,
            "set_at": self.set_at,
            "set_by": self.set_by,
        }


class SecretsStore:
    """Named secrets under one owner-only directory (see the module docstring)."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._dir = Path(directory)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SecretsStore:
        """The store at :func:`resolve_secrets_dir` (the directory is not created)."""
        return cls(resolve_secrets_dir(env))

    @property
    def path(self) -> Path:
        return self._dir

    def __repr__(self) -> str:
        return f"SecretsStore({str(self._dir)!r})"

    # --- paths -------------------------------------------------------------------
    def value_path(self, name: str) -> Path:
        """``<dir>/<name>`` — the raw value file."""
        return self._dir / validate_name(name)

    def meta_path(self, name: str) -> Path:
        """``<dir>/<name>.meta.json`` — who set it and when; never the value."""
        return self._dir / (validate_name(name) + META_SUFFIX)

    # --- permission checks ---------------------------------------------------------
    def _check_dir_for_write(self) -> None:
        """The directory exists, is a directory, has no group/other bits and is ours;
        anything else is :class:`SecretsInsecure` (never repaired silently)."""
        try:
            st = os.stat(self._dir)
        except FileNotFoundError:
            raise SecretsInsecure(f"secrets directory {self._dir} does not exist") from None
        if not stat.S_ISDIR(st.st_mode):
            raise SecretsInsecure(f"secrets path {self._dir} is not a directory")
        if st.st_mode & _INSECURE_BITS:
            raise SecretsInsecure(
                f"secrets directory {self._dir} is group/world accessible "
                f"(mode {stat.S_IMODE(st.st_mode):04o}); refusing to store — chmod 0700 it"
            )
        if st.st_uid != os.geteuid():
            raise SecretsInsecure(
                f"secrets directory {self._dir} is owned by uid {st.st_uid}, "
                f"not the current user (uid {os.geteuid()}); refusing to store"
            )

    @staticmethod
    def _check_file_for_read(path: Path) -> os.stat_result | None:
        """``None`` when absent; raises :class:`SecretsInsecure` when readable by others."""
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(st.st_mode):
            raise SecretsInsecure(f"secret {path} is not a regular file")
        if st.st_mode & _INSECURE_BITS:
            raise SecretsInsecure(
                f"secret {path} is group/world readable (mode {stat.S_IMODE(st.st_mode):04o}); "
                "refusing to read — chmod 0600 it"
            )
        return st

    def stat_for_read(self, name: str) -> os.stat_result | None:
        """The value file's metadata as :meth:`get` would judge it — ``None`` when absent,
        :class:`SecretsInsecure` when :meth:`get` would refuse it — WITHOUT reading the
        value. A presence check that must agree with the read uses this."""
        return self._check_file_for_read(self.value_path(name))

    def ensure_dir(self) -> Path:
        """Create the directory 0700 when missing, then verify it is fit to write into."""
        if not self._dir.exists():
            self._dir.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(FileExistsError):
                os.mkdir(self._dir, DIR_MODE)
        # umask can only remove bits, but a pre-existing dir keeps its mode: verify.
        self._check_dir_for_write()
        return self._dir

    # --- atomic write --------------------------------------------------------------
    def _write_atomic(self, path: Path, data: str) -> None:
        """Temp file in the SAME directory (so the rename is atomic on one filesystem),
        0600 from creation, fsynced, renamed over ``path``, then the directory entry
        fsynced; a failure unlinks the temp file so no partial secret remains."""
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=self._dir)
        try:
            os.fchmod(fd, FILE_MODE)  # mkstemp already uses 0600; be explicit
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        dfd = os.open(self._dir, os.O_RDONLY)
        try:
            os.fsync(dfd)
        except OSError:
            pass
        finally:
            os.close(dfd)

    # --- API -----------------------------------------------------------------------
    def set(self, name: str, value: str, *, set_by: str = "") -> SecretStatus:
        """Store ``value`` (stripped) under ``name``; returns the new status, never the value."""
        vpath = self.value_path(name)
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"refusing to store an empty value for {name!r}")
        if any(ch in cleaned for ch in "\r\n\x00"):
            raise ValueError(f"refusing to store a value with line breaks or NUL for {name!r}")
        self.ensure_dir()
        meta = {
            "schema": META_SCHEMA,
            "name": name,
            "set_at": _utc_now(),
            "set_by": str(set_by or ""),
        }
        self._write_atomic(vpath, cleaned)
        self._write_atomic(self.meta_path(name), json.dumps(meta, sort_keys=True) + "\n")
        return self.status(name)

    def get(self, name: str) -> str | None:
        """The value, or ``None`` when absent. Raises :class:`SecretsInsecure` rather
        than return a value anyone else could read."""
        vpath = self.value_path(name)
        if self._check_file_for_read(vpath) is None:
            return None
        value = vpath.read_text(encoding="utf-8").strip()
        return value or None

    def delete(self, name: str) -> bool:
        """Remove the value and its metadata; ``True`` when a value existed."""
        vpath = self.value_path(name)
        mpath = self.meta_path(name)
        existed = vpath.exists()
        if existed or mpath.exists():
            self._check_dir_for_write()
        for p in (vpath, mpath):
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        return existed

    def status(self, name: str) -> SecretStatus:
        """Presence, fingerprint and provenance — what the UI and ``crb doctor`` show.
        A mounted value with no metadata reports the file's mtime and no ``set_by``."""
        vpath = self.value_path(name)
        st = self._check_file_for_read(vpath)
        if st is None:
            return SecretStatus(name=name, present=False)
        value = vpath.read_text(encoding="utf-8").strip()
        if not value:
            return SecretStatus(name=name, present=False)
        set_at, set_by = _mtime_iso(st), ""
        mpath = self.meta_path(name)
        if self._check_file_for_read(mpath) is not None:
            try:
                meta = json.loads(mpath.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
            if isinstance(meta, dict):
                set_at = str(meta.get("set_at") or set_at)
                set_by = str(meta.get("set_by") or "")
        return SecretStatus(
            name=name,
            present=True,
            fingerprint=fingerprint(value),
            set_at=set_at,
            set_by=set_by,
        )


__all__ = [
    "DEFAULT_HOME",
    "DIR_MODE",
    "FILE_MODE",
    "FINGERPRINT_CHARS",
    "HOME_ENV",
    "META_SUFFIX",
    "MIN_FINGERPRINT_VALUE_LEN",
    "NAME_RE",
    "SECRETS_DIR_ENV",
    "SECRETS_SUBDIR",
    "SecretStatus",
    "SecretsError",
    "SecretsInsecure",
    "SecretsNameError",
    "SecretsStore",
    "fingerprint",
    "resolve_secrets_dir",
    "validate_name",
]
