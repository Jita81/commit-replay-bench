"""Programmatic Alembic for crb.store: ``upgrade`` / ``current`` / ``check``.

Used by the container entrypoint (``python -m crb.store.migrate upgrade``), the compose
``migrate`` one-shot, the Helm pre-upgrade Job, and ``crb serve`` on boot.

Invariants
----------
* **One transaction per upgrade.** The connection is handed to ``env.py`` through
  ``config.attributes["connection"]`` inside ``engine.begin()``; on PostgreSQL a failed
  migration rolls back completely. (SQLite autocommits DDL — a failure there leaves a
  partial schema, which is why SQLite is the development store, not the production one.)
* **A migrated database is protected.** The initial revision installs the append-only
  triggers through the *same* helper ``init_db`` uses
  (:func:`crb.store.db.install_append_only_triggers`), on the migration's own connection
  (:func:`install_append_only_triggers_on`), and :func:`upgrade` re-asserts them afterwards.
  There is no path through this module that leaves ``grades`` writable.
* **Adopting an ``init_db`` database is explicit.** A database that already has every
  model table but no ``alembic_version`` row was created by ``Base.metadata.create_all``;
  it is *stamped* at the initial revision (which is exactly ``create_all`` — the parity
  test proves it) and then upgraded. A database with only *some* of the tables is refused:
  that is a partial or foreign schema and the operator must look.
* The URL comes from the caller or ``CRB_DATABASE_URL``; it is never written to disk and
  never logged (a PostgreSQL URL can embed a password).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect

from crb.store.db import database_url, install_append_only_triggers, make_engine
from crb.store.models import APPEND_ONLY_TABLES, Base

log = logging.getLogger("crb.store.migrate")

STORE_DIR = Path(__file__).resolve().parent
INI_PATH = STORE_DIR / "alembic.ini"
MIGRATIONS_DIR = STORE_DIR / "migrations"
#: The revision that equals ``Base.metadata.create_all`` at the time it was written.
INITIAL_REVISION = "0001"


class SchemaStateError(RuntimeError):
    """The database is in a state the migrator refuses to guess about (partial schema)."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def alembic_config(url: str | None = None) -> Config:
    """An Alembic ``Config`` bound to the packaged ``alembic.ini`` and ``migrations/``.

    ``url`` (if given) is set as ``sqlalchemy.url`` with ``%`` escaped for configparser.
    """
    cfg = Config(str(INI_PATH))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head_revision() -> str:
    """The single head of the packaged revision chain (raises if the chain forks)."""
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    if len(heads) != 1:
        raise SchemaStateError(f"expected exactly one migration head, found {heads!r}")
    return heads[0]


# ---------------------------------------------------------------------------
# Triggers on an existing connection (used by revision scripts)
# ---------------------------------------------------------------------------


class _ConnectionAsEngine:
    """The two-member Engine surface :func:`install_append_only_triggers` uses
    (``.dialect`` and ``.begin()``), backed by an already-open connection.

    A revision script runs inside Alembic's transaction on Alembic's connection. Opening a
    *second* connection from the engine there would block on PostgreSQL (the tables just
    created are exclusively locked until the migration commits) and would race SQLite's
    write lock — so the triggers must land on the same connection, and this adapter is
    how the one canonical trigger helper gets there without a second copy of its SQL.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self.dialect = connection.dialect

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        yield self._connection


def install_append_only_triggers_on(
    connection: Connection, tables: tuple[str, ...] = APPEND_ONLY_TABLES
) -> None:
    """Install the append-only triggers on ``connection`` (inside the caller's transaction)."""
    install_append_only_triggers(cast(Engine, _ConnectionAsEngine(connection)), tables)


# ---------------------------------------------------------------------------
# State inspection
# ---------------------------------------------------------------------------


def _model_tables_present(connection: Connection) -> tuple[set[str], set[str]]:
    """``(present, expected)`` model table names in the connection's default schema."""
    present = set(inspect(connection).get_table_names())
    expected = set(Base.metadata.tables)
    return present & expected, expected


def _current_heads(connection: Connection) -> tuple[str, ...]:
    return MigrationContext.configure(connection).get_current_heads()


def _adopt_unversioned_schema(connection: Connection, cfg: Config) -> None:
    """Stamp a ``create_all`` database at the initial revision; refuse a partial one."""
    if _current_heads(connection):
        return
    present, expected = _model_tables_present(connection)
    if not present:
        return
    if present != expected:
        missing = sorted(expected - present)
        raise SchemaStateError(
            "database has some crb tables but no alembic_version and is missing "
            f"{missing}; refusing to guess — restore from backup or drop the partial schema"
        )
    log.info("adopting unversioned create_all schema: stamping %s", INITIAL_REVISION)
    command.stamp(cfg, INITIAL_REVISION)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def upgrade(url: str | None = None, *, revision: str = "head") -> None:
    """Run ``alembic upgrade <revision>`` against ``url`` (default: ``CRB_DATABASE_URL``).

    Idempotent: a database already at ``revision`` is left untouched except that the
    append-only triggers are re-asserted (``CREATE TRIGGER IF NOT EXISTS`` / ``DROP`` +
    ``CREATE`` on PostgreSQL).
    """
    resolved = database_url(url)
    engine = make_engine(resolved)
    try:
        cfg = alembic_config(resolved)
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            _adopt_unversioned_schema(connection, cfg)
            command.upgrade(cfg, revision)
        install_append_only_triggers(engine)
    finally:
        engine.dispose()


def current(url: str | None = None) -> str | None:
    """The database's current revision, or ``None`` when it has never been migrated."""
    engine = make_engine(database_url(url))
    try:
        with engine.connect() as connection:
            heads = _current_heads(connection)
    finally:
        engine.dispose()
    if not heads:
        return None
    if len(heads) != 1:
        raise SchemaStateError(f"database reports several current heads: {heads!r}")
    return heads[0]


def check(url: str | None = None) -> bool:
    """``True`` iff the database is at the packaged head (no pending, no unknown revisions)."""
    packaged = set(ScriptDirectory.from_config(alembic_config()).get_heads())
    engine = make_engine(database_url(url))
    try:
        with engine.connect() as connection:
            applied = set(_current_heads(connection))
    finally:
        engine.dispose()
    return bool(packaged) and applied == packaged


# ---------------------------------------------------------------------------
# ``python -m crb.store.migrate``
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m crb.store.migrate",
        description="Apply or inspect crb database migrations.",
    )
    p.add_argument(
        "action",
        nargs="?",
        default="upgrade",
        choices=("upgrade", "current", "check"),
        help="upgrade (default): migrate to head; current: print the revision; "
        "check: exit 0 iff at head",
    )
    p.add_argument(
        "--url",
        default=None,
        help="database URL (default: CRB_DATABASE_URL, then the CRB_HOME SQLite file)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="INFO logging to stderr")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if args.action == "upgrade":
        upgrade(args.url)
        print(f"ok: database at {current(args.url)}")
        return 0
    if args.action == "current":
        rev = current(args.url)
        print(rev or "(unversioned)")
        return 0
    ok = check(args.url)
    print(
        "ok: at head" if ok else f"pending: database at {current(args.url)}, head {head_revision()}"
    )
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover — exercised via tests calling main()
    sys.exit(main())


__all__ = [
    "INITIAL_REVISION",
    "SchemaStateError",
    "alembic_config",
    "check",
    "current",
    "head_revision",
    "install_append_only_triggers_on",
    "main",
    "upgrade",
]
