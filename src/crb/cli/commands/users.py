"""``crb users list | create | set-password | activate | deactivate`` — the break-glass
account verbs, run on the API host against the same database ``crb serve`` uses.

Why a CLI: an administrator who forgets or mistypes the only admin password has no way
back in through the API. Access to the host and its database *is* the credential here,
so the verbs take no login; they take the database ``crb serve`` resolves
(``--database-url`` → ``CRB_DATABASE_URL`` → ``$CRB_HOME/crb.db``). A password is never
an argument (it would land in shell history and ``ps``): it comes from an interactive
prompt, or from the file ``CRB_USERS_PASSWORD_FILE`` names when there is no terminal.
Every change goes through the same primitives as the routes (``set_password``,
``set_user_active`` with the last-admin guard) and appends the same ``user.*`` event,
with the actor ``cli:<os user>`` — so the audit trail reads the same whichever door was
used. The password never reaches an event, a log line or stdout.

Navigation
----------
What it is:   ``crb users …`` — the break-glass account CLI (list, create, set-password,
              activate, deactivate) over the server's own database.
What it does: Resolves the same database as ``crb serve``, reads a password from a prompt or
              ``CRB_USERS_PASSWORD_FILE`` (never argv), applies the change through the auth
              primitives (last-admin guard, ≥ 12 characters, local accounts only) and writes
              one ``user.*`` event with actor ``cli:<os user>`` in the same transaction.
How:          Lazy imports of the store and server layers (the base CLI works without the
              ``[server]`` extra); ``ApiError`` from the primitives becomes a ``CliError``
              (exit 2) with the same message the API would give.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/auth.py (``create_local_user``, ``set_password``,
              ``set_user_active``, ``find_local_user`` — the one implementation),
              src/crb/server/routes/admin.py (``record_user_event`` — the same events the
              API writes), src/crb/store/db.py (``database_url`` — the same resolution as
              ``crb serve`` and ``crb migrate``), src/crb/cli/main.py (registers the verb),
              docs/OPERATOR.md#9-users (the forgot-the-admin-password procedure)
Tested by:    tests/test_cli_users.py
Touch when:   never for a new repository; a new account action needs a verb here, a route in
              src/crb/server/routes/admin.py and the same ``user.*`` event in both.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from crb.cli.commands import EXIT_OK, CliError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from crb.store.models import User

_SERVER_HINT = "the server layer is not installed — `pip install 'commit-replay-bench[server]'`"
PASSWORD_FILE_ENV = "CRB_USERS_PASSWORD_FILE"  # noqa: S105 — a variable NAME, not a value


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb users`` and its five verbs."""
    users = sub.add_parser(
        "users",
        help="break-glass account admin on the host: list, create, set-password, activate, deactivate",
    )
    verbs = users.add_subparsers(dest="verb", metavar="<verb>")

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--database-url", default=None, help="overrides CRB_DATABASE_URL")

    ls = verbs.add_parser("list", help="every account: username, role, active, last login")
    _common(ls)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    create = verbs.add_parser(
        "create", help="create a local account (password from a prompt or the password file)"
    )
    _common(create)
    create.add_argument("username")
    create.add_argument("--role", default="viewer", help="viewer | operator | approver | admin")
    create.add_argument("--display-name", default="")
    create.add_argument("--email", default="")
    create.set_defaults(func=cmd_create)

    setpw = verbs.add_parser(
        "set-password",
        help="set a local account's password (its sessions end); prompt or password file",
    )
    _common(setpw)
    setpw.add_argument("username")
    setpw.set_defaults(func=cmd_set_password)

    act = verbs.add_parser("activate", help="re-enable an account")
    _common(act)
    act.add_argument("username")
    act.set_defaults(func=cmd_activate)

    deact = verbs.add_parser(
        "deactivate", help="disable an account (never the last active admin); its sessions end"
    )
    _common(deact)
    deact.add_argument("username")
    deact.set_defaults(func=cmd_deactivate)

    users.set_defaults(func=lambda args: _usage(users))


def _usage(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


# --- plumbing ---------------------------------------------------------------------------


def actor() -> str:
    """Who the events name: ``cli:<os user>`` — the host login that ran the verb."""
    try:
        who = getpass.getuser()
    except (KeyError, OSError):
        who = str(os.getuid()) if hasattr(os, "getuid") else "unknown"
    return f"cli:{who}"


def read_password(*, confirm: bool) -> str:
    """The password from ``CRB_USERS_PASSWORD_FILE`` (first line, newline stripped) or an
    interactive prompt (twice when ``confirm``). Never from argv, never echoed. A run with
    neither a file nor a terminal fails with the instruction instead of hanging."""
    path = os.environ.get(PASSWORD_FILE_ENV, "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                pw = fh.readline().rstrip("\r\n")
        except OSError as exc:
            raise CliError(f"cannot read {PASSWORD_FILE_ENV}={path}: {exc.strerror}") from exc
        if not pw:
            raise CliError(f"{PASSWORD_FILE_ENV}={path} is empty")
        return pw
    if not sys.stdin.isatty():
        raise CliError(
            f"no terminal to prompt on — put the password in a file and set {PASSWORD_FILE_ENV}"
        )
    pw = getpass.getpass("Password: ")
    if confirm and getpass.getpass("Confirm password: ") != pw:
        raise CliError("passwords do not match")
    return pw


def _open(database_url: str | None) -> Any:
    """A bound session factory over the database ``crb serve`` would use; refuses an
    uninitialised one with the ``crb migrate`` instruction."""
    try:
        from sqlalchemy import inspect  # noqa: PLC0415 — optional extra, see service.py

        from crb.store import db as store_db  # noqa: PLC0415
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    engine = store_db.make_engine(store_db.database_url(database_url))
    if "users" not in inspect(engine).get_table_names():
        raise CliError("database not initialised — run `crb migrate`")
    return store_db.make_session_factory(engine)


def _row(user: User) -> dict[str, Any]:
    from crb.server.auth import LOCAL_ISSUER  # noqa: PLC0415

    return {
        "id": user.id,
        "username": (
            user.subject.removeprefix("local:") if user.issuer == LOCAL_ISSUER else user.subject
        ),
        "issuer": user.issuer,
        "role": user.role,
        "active": user.active,
        "display_name": user.display_name,
        "email": user.email,
        "created": user.created,
        "last_login": user.last_login,
    }


def _local_user(db: Session, username: str) -> User:
    from crb.server.auth import find_local_user  # noqa: PLC0415

    user = find_local_user(db, username)
    if user is None:
        raise CliError(f"no local account {username!r}")
    return user


def _run(database_url: str | None, fn: Any) -> int:
    """Open the database, run ``fn(db)`` in one transaction, commit; an ``ApiError`` from
    the shared primitives becomes the same message the API would give, exit 2."""
    try:
        from crb.server.deps import ApiError  # noqa: PLC0415
    except ImportError as e:
        raise CliError(f"{_SERVER_HINT} ({e})") from e
    factory = _open(database_url)
    with factory() as db:
        try:
            result = fn(db)
            db.commit()
        except ApiError as exc:
            db.rollback()
            raise CliError(f"{exc.code}: {exc.message}") from None
    return int(result)


# --- verbs ------------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    """Every account, oldest first — never a hash."""
    from sqlalchemy import select  # noqa: PLC0415

    from crb.store.models import User  # noqa: PLC0415

    def _go(db: Session) -> int:
        rows = [_row(u) for u in db.execute(select(User).order_by(User.created, User.id)).scalars()]
        if args.json:
            print(json.dumps(rows, indent=1, sort_keys=True))
            return EXIT_OK
        header = f"{'username':<24} {'role':<9} {'active':<7} {'issuer':<10} last_login"
        print(header)
        print("-" * len(header))
        for r in rows:
            active = "yes" if r["active"] else "no"
            print(
                f"{r['username']:<24} {r['role']:<9} {active:<7} {r['issuer']:<10} "
                f"{r['last_login'] or '-'}"
            )
        if not rows:
            print("(no accounts — `crb users create <name> --role admin`)")
        return EXIT_OK

    return _run(args.database_url, _go)


def cmd_create(args: argparse.Namespace) -> int:
    """Create a local account; the password is read AFTER the arguments validate."""
    from crb.server.auth import create_local_user, validate_role, validate_username  # noqa: PLC0415
    from crb.server.routes.admin import record_user_event  # noqa: PLC0415

    def _go(db: Session) -> int:
        validate_username(args.username)
        validate_role(args.role)
        password = read_password(confirm=True)
        user = create_local_user(
            db,
            username=args.username,
            password=password,
            role=args.role,
            display_name=args.display_name,
            email=args.email,
        )
        record_user_event(db, action="user.created", actor=actor(), target=user)
        print(f"created {args.username} ({args.role})")
        return EXIT_OK

    return _run(args.database_url, _go)


def cmd_set_password(args: argparse.Namespace) -> int:
    """Set a local account's password; every session it holds ends."""
    from crb.server.auth import set_password  # noqa: PLC0415
    from crb.server.routes.admin import record_user_event  # noqa: PLC0415

    def _go(db: Session) -> int:
        user = _local_user(db, args.username)
        password = read_password(confirm=True)
        set_password(user, password)
        record_user_event(db, action="user.password_set", actor=actor(), target=user, by="cli")
        print(f"password set for {args.username}; its sessions have ended")
        return EXIT_OK

    return _run(args.database_url, _go)


def _set_active(args: argparse.Namespace, active: bool) -> int:
    from crb.server.auth import set_user_active  # noqa: PLC0415
    from crb.server.routes.admin import record_user_event  # noqa: PLC0415

    verb = "activated" if active else "deactivated"

    def _go(db: Session) -> int:
        user = _local_user(db, args.username)
        if user.active == active:
            print(f"{args.username} is already {verb}")
            return EXIT_OK
        set_user_active(db, user, active)
        record_user_event(db, action=f"user.{verb}", actor=actor(), target=user)
        print(f"{verb} {args.username}")
        return EXIT_OK

    return _run(args.database_url, _go)


def cmd_activate(args: argparse.Namespace) -> int:
    """Re-enable an account."""
    return _set_active(args, True)


def cmd_deactivate(args: argparse.Namespace) -> int:
    """Disable an account (never the last active admin); its sessions end at once."""
    return _set_active(args, False)


__all__: Sequence[str] = ("PASSWORD_FILE_ENV", "actor", "read_password", "register")
