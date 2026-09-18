"""The two secrets the desktop app must remember, and the environment the server is given.

Both secrets are generated once and read back for ever after. A secret key that changed per
launch would invalidate every session cookie on restart; an administrator password that
changed per launch would be a lie, because the bootstrap administrator is seeded only while
the users table is still empty. Each file is created with ``os.open(..., 0o600)`` so it is
never world-readable, not even for the instant between ``open`` and ``chmod``, and a file
that some earlier copy left looser is hardened on the way past.

``build_environment`` is the whole contract with ``crb serve`` in one place: production
settings, an explicit ``CRB_COOKIE_SECURE=false`` (Safari drops a ``Secure`` cookie on
``http://127.0.0.1``, and production defaults it to true), ``CRB_ROLE=api`` so the docker
sandbox probe reports ``skipped`` rather than ``down`` on a Mac without Docker, and a local
executor. Every function takes the home directory explicitly, so a test drives it with
``tmp_path`` and never touches the real one.

Navigation
----------
What it is:   The desktop launcher's persisted secrets — the secret key and the first-run
              administrator credentials — and the environment dictionary for ``crb serve``.
What it does: Generates ``CRB_SECRET_KEY`` (48 url-safe bytes) and a ≥12 character admin
              password once per installation, stores them 0600 under the state directory,
              reads them back unchanged on every later launch, and builds the child
              process's environment with an absolute tilde-free ``CRB_HOME``. It refuses a
              secret key shorter than 32 characters or a credentials file it cannot parse.
How:          ``os.open`` with ``O_CREAT | O_EXCL`` and mode 0600 writes the file or loses
              the race harmlessly; the value is then read back from disk, so two launchers
              racing converge on one secret. ``build_environment`` copies the caller's
              environment and overlays the nine variables the server needs.
Layer:        desktop — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0016-a-double-clickable-macos-app.md
Works with:   src/crb/server/settings.py (every variable set here, and the 12-character
              password floor), src/crb/desktop/paths.py (the state directory these files
              live in), src/crb/desktop/__main__.py (prints the credentials on first run),
              src/crb/desktop/server.py (spawns the child with this environment),
              src/crb/server/auth.py (what the seeded administrator may then do)
Tested by:    tests/test_desktop_launcher.py
Touch when:   a setting the desktop run depends on is added or renamed in
              src/crb/server/settings.py (add it to ``build_environment`` and to the test
              that lists the required keys); never for a new repository.
"""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: The persisted ``CRB_SECRET_KEY``, relative to the state directory.
SECRET_KEY_FILE = "secret_key"  # noqa: S105
#: The persisted administrator credentials, relative to the state directory.
CREDENTIALS_FILE = "first-run-credentials.txt"
#: The bootstrap administrator's username; the password is generated, the name is not.
ADMIN_USERNAME = "admin"
#: Entropy for the generated values, in bytes before url-safe encoding.
SECRET_KEY_BYTES = 48
ADMIN_PASSWORD_BYTES = 18
#: The server refuses a shorter secret key; mirrored here because the core cannot import it.
MIN_SECRET_KEY_LENGTH = 32
#: ``crb.server.settings.MIN_PASSWORD_LENGTH``, mirrored for the same reason.
MIN_ADMIN_PASSWORD_LENGTH = 12
#: Owner read/write only — both files hold a live credential.
SECRET_FILE_MODE = 0o600

_USERNAME_PREFIX = "Username:"
_PASSWORD_PREFIX = "Password:"  # noqa: S105


class DesktopConfigError(RuntimeError):
    """A persisted secret is missing, unreadable or too weak to launch with."""


@dataclass(frozen=True)
class AdminCredentials:
    """The bootstrap administrator, as stored on disk."""

    username: str
    password: str
    path: Path
    #: True when this launch generated the credentials — the moment to print them loudly.
    created: bool


def _write_private(path: Path, text: str) -> bool:
    """Create ``path`` 0600 with ``text``; ``False`` when it already existed.

    ``O_EXCL`` plus the mode argument means the file is never world-readable, and a second
    launcher racing this one loses the race without clobbering the winner's value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_FILE_MODE)
    except FileExistsError:
        return False
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(text)
    return True


def _harden(path: Path) -> None:
    """Re-apply 0600 to a file a copy or an earlier version left readable by others."""
    if stat.S_IMODE(path.stat().st_mode) != SECRET_FILE_MODE:
        path.chmod(SECRET_FILE_MODE)


def ensure_secret_key(home: Path) -> str:
    """The installation's ``CRB_SECRET_KEY``, generating and persisting it on first call."""
    path = home / SECRET_KEY_FILE
    _write_private(path, secrets.token_urlsafe(SECRET_KEY_BYTES) + "\n")
    _harden(path)
    key = path.read_text(encoding="utf-8").strip()
    if len(key) < MIN_SECRET_KEY_LENGTH:
        raise DesktopConfigError(
            f"{path} holds a secret key of {len(key)} characters; the server requires at "
            f"least {MIN_SECRET_KEY_LENGTH}. Delete the file to have a new one generated "
            "(every existing session is signed out)."
        )
    return key


def credentials_document(username: str, password: str) -> str:
    """The text of the credentials file — written once, read by a human and by us."""
    return (
        "Commit Replay Bench — administrator credentials for this machine\n"
        "\n"
        "Generated at first launch and reused on every launch after it. The administrator\n"
        "is seeded only while the user table is empty, so changing this file changes\n"
        "nothing once the account exists — change the password in the app instead.\n"
        "\n"
        f"{_USERNAME_PREFIX} {username}\n"
        f"{_PASSWORD_PREFIX} {password}\n"
    )


def _field(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def ensure_admin_credentials(home: Path) -> AdminCredentials:
    """The bootstrap administrator, generating and persisting it on first call."""
    path = home / CREDENTIALS_FILE
    password = secrets.token_urlsafe(ADMIN_PASSWORD_BYTES)
    created = _write_private(path, credentials_document(ADMIN_USERNAME, password))
    _harden(path)
    text = path.read_text(encoding="utf-8")
    username, stored = _field(text, _USERNAME_PREFIX), _field(text, _PASSWORD_PREFIX)
    if not username or len(stored) < MIN_ADMIN_PASSWORD_LENGTH:
        raise DesktopConfigError(
            f"{path} does not hold a usable username and a password of at least "
            f"{MIN_ADMIN_PASSWORD_LENGTH} characters. Delete the file and launch again to "
            "have new credentials generated (they seed nothing once the account exists)."
        )
    return AdminCredentials(username=username, password=stored, path=path, created=created)


def absolute_str(path: Path) -> str:
    """``path`` as the child process must see it: absolute, expanded, no tilde."""
    return str(path.expanduser().resolve())


def build_environment(
    *,
    home: Path,
    ui_dist: Path,
    secret_key: str,
    admin: AdminCredentials,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The environment for ``crb migrate`` and ``crb serve`` in a desktop run.

    Note what is *not* here: the bind port. ``crb serve`` ignores ``CRB_BIND_PORT``, so the
    port is a command-line flag (see :mod:`crb.desktop.server`).
    """
    env = dict(os.environ if base is None else base)
    env.update(
        {
            "CRB_HOME": absolute_str(home),
            "CRB_SECRET_KEY": secret_key,
            "CRB_ENV": "prod",
            "CRB_COOKIE_SECURE": "false",
            "CRB_UI_DIST": absolute_str(ui_dist),
            "CRB_ROLE": "api",
            "CRB_SANDBOX__EXECUTOR": "local",
            "CRB_BOOTSTRAP_ADMIN__USERNAME": admin.username,
            "CRB_BOOTSTRAP_ADMIN__PASSWORD": admin.password,
        }
    )
    return env
