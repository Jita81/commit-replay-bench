"""Programmatic Alembic for crb.store: ``upgrade`` / ``current`` / ``check``.

Used by the container entrypoint (``python -m crb.store.migrate upgrade``), the compose
``migrate`` one-shot and the Helm pre-upgrade Job. ``crb serve`` itself does NOT migrate: its
lifespan runs ``init_db`` (``create_all`` + the append-only triggers), which is complete for a
fresh database and a no-op on a migrated one — a store behind by a revision must be migrated
by the entrypoint/Job before ``serve`` (``migrate check`` exits 1 when it is).

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
  model table but no ``alembic_version`` row was created by ``Base.metadata.create_all``
  — by *some* release's models. It is *stamped* at the revision its schema corresponds
  to (:data:`REVISION_MARKERS`: the newest revision whose added column it carries; none
  → the initial revision) and then upgraded to head, so a database created by an older
  release receives exactly the revisions it lacks and one created by this release (which
  equals head — the parity test proves it) receives none. A table a later revision ADDS
  (:data:`REVISION_TABLES`) may be absent from an older release's ``create_all`` schema
  without making it partial; any other missing table, or a schema at head that still
  differs from the models, is refused: that is a partial or foreign schema and the
  operator must look.
* The URL comes from the caller or ``CRB_DATABASE_URL``; it is never written to disk and
  never logged (a PostgreSQL URL can embed a password).

Navigation
----------
What it is:   The programmatic Alembic entry point — ``upgrade`` / ``current`` / ``check`` /
              ``head_status`` and the ``python -m crb.store.migrate`` CLI the container
              entrypoint runs.
What it does: Migrates a database to the packaged head in one transaction, adopts an
              unversioned ``init_db`` database by stamping it at the revision its schema
              matches, and refuses a partial or foreign schema rather than guess. Re-asserts
              the append-only triggers after every upgrade; never logs the URL.
              ``head_status`` is the one head check ``/health``'s ``migrations`` probe and
              ``crb doctor`` both read: the applied revision against the packaged head, and
              for an unversioned store the revision its fingerprints correspond to.
How:          ``upgrade`` = engine → ``_adopt_unversioned_schema`` (marker walk, parity
              diff at head) → ``command.upgrade`` on the same connection →
              ``install_append_only_triggers``; ``install_append_only_triggers_on`` adapts an
              open connection so revision scripts reuse the one trigger helper;
              ``head_status_on`` reads ``alembic_version`` and reuses the adoption walk.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/migrations/env.py (receives the connection through
              ``config.attributes``), src/crb/store/migrations/versions/v0001_initial_schema.py
              (the revision that equals ``create_all``), src/crb/store/db.py (the engine and
              the trigger helper), src/crb/store/models.py (``Base.metadata`` for the parity
              diff), deploy/entrypoint.sh (runs ``upgrade`` before serving),
              src/crb/cli/commands/service.py (``crb migrate``; ``crb doctor`` reads
              ``head_status``), src/crb/server/routes/system.py (the ``migrations`` probe
              reads ``head_status_on``)
Tested by:    tests/test_store_migrate.py
Touch when:   never for a new repository; every new revision that ADDS a column appends a
              ``REVISION_MARKERS`` entry and one that ADDS a table appends a
              ``REVISION_TABLES`` entry — or adoption of a newer ``init_db`` database
              breaks; the upgrade procedure is documented in docs/DEPLOYMENT.md#6-upgrade.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

from alembic import command
from alembic.autogenerate import compare_metadata
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
#: The revision that equalled ``Base.metadata.create_all`` at the time it was written.
INITIAL_REVISION = "0001"
#: ``(revision, table, column)`` — the column each revision after the initial one ADDS.
#: An unversioned ``create_all`` schema is at the newest revision whose column it
#: carries (checked in order; the first missing marker stops the walk). Every migration
#: that adds a column appends its marker here, or adoption of a newer ``init_db``
#: database would try to add a column it already has.
REVISION_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("0002", "grades", "repo_lint_clean"),
    ("0003", "reviews", "review_id"),
    ("0006", "repos", "github_full_name"),
    ("0008", "workers", "unconfirmed_containers"),
)
#: ``(revision, table)`` — the TABLE each revision after the initial one ADDS. An older
#: release's ``create_all`` schema lacks it and is still a complete schema *for its
#: release*: adoption tolerates its absence (the revision that adds it will create it).
REVISION_TABLES: tuple[tuple[str, str], ...] = (
    ("0003", "reviews"),
    ("0005", "github_installations"),
    ("0007", "workers"),
)
#: ``(revision, table, index)`` — the INDEX a revision adds when it adds no column or table.
#: Walked after :data:`REVISION_MARKERS` in the same way: a ``create_all`` schema that
#: carries the index is at least at that revision.
REVISION_INDEXES: tuple[tuple[str, str, str], ...] = (("0004", "events", "uq_events_trace_seq"),)


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
    """``(present, expected)`` model table names in the connection's default schema
    (``present`` is intersected with the models so foreign tables are ignored)."""
    present = set(inspect(connection).get_table_names())
    expected = set(Base.metadata.tables)
    return present & expected, expected


#: The tables a later revision adds — optional in an unversioned schema (see above).
_LATER_TABLES: frozenset[str] = frozenset(t for _rev, t in REVISION_TABLES)


def _current_heads(connection: Connection) -> tuple[str, ...]:
    return MigrationContext.configure(connection).get_current_heads()


def _unversioned_revision(connection: Connection) -> str:
    """The revision an unversioned (``create_all``) schema corresponds to — see
    :data:`REVISION_MARKERS`."""
    insp = inspect(connection)
    tables = set(insp.get_table_names())

    def has_column(table: str, column: str) -> bool:
        return table in tables and column in {c["name"] for c in insp.get_columns(table)}

    def has_index(table: str, index: str) -> bool:
        return table in tables and index in {ix["name"] for ix in insp.get_indexes(table)}

    # every revision's fingerprint — a column, an index or a table — walked in REVISION
    # order whatever kind it is: the first fingerprint missing stops the walk, and the
    # schema is at the last revision whose fingerprint it carries
    fingerprints: list[tuple[str, Callable[[], bool]]] = [
        *((rev, partial(has_column, table, column)) for rev, table, column in REVISION_MARKERS),
        *((rev, partial(has_index, table, index)) for rev, table, index in REVISION_INDEXES),
        *((rev, partial(tables.__contains__, table)) for rev, table in REVISION_TABLES),
    ]
    revision = INITIAL_REVISION
    for rev, present in sorted(fingerprints, key=lambda x: x[0]):
        if not present():
            return revision
        revision = rev
    return revision


def _adopt_unversioned_schema(connection: Connection, cfg: Config) -> None:
    """Stamp a ``create_all`` database at the revision its schema is at; refuse a
    partial one, and refuse one that claims to be at head but differs from the models."""
    if _current_heads(connection):
        return
    present, expected = _model_tables_present(connection)
    if not present:
        return
    if present != expected and (expected - present) - _LATER_TABLES:
        missing = sorted(expected - present)
        raise SchemaStateError(
            "database has some crb tables but no alembic_version and is missing "
            f"{missing}; refusing to guess — restore from backup or drop the partial schema"
        )
    revision = _unversioned_revision(connection)
    if revision == head_revision():
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        if diff:
            raise SchemaStateError(
                "database has every crb table, no alembic_version, and a schema that is "
                f"neither a known release's create_all nor the current models ({len(diff)} "
                "difference(s)); refusing to guess — restore from backup or migrate by hand"
            )
    log.info("adopting unversioned create_all schema: stamping %s", revision)
    command.stamp(cfg, revision)


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


@dataclass(frozen=True)
class HeadStatus:
    """Where a database stands against the packaged revision chain — what the ``/health``
    ``migrations`` probe and ``crb doctor`` report.

    ``database`` is the applied revision (several, comma-joined, when the store reports more
    than one head; ``None`` when there is no ``alembic_version`` row — an empty store or a
    ``create_all`` one). ``head`` is the code's single head. ``at_head`` is True only when
    the applied revision IS the head. For an UNVERSIONED store with crb tables,
    ``unversioned_at`` is the revision its fingerprints correspond to (the same walk
    ``upgrade`` uses to adopt it) and ``matches_models`` says whether that revision is the
    head AND the schema equals the current models — i.e. ``upgrade`` would stamp it
    without applying anything. Both are ``None`` / ``False`` for a versioned or empty store.
    """

    database: str | None
    head: str
    at_head: bool
    unversioned_at: str | None = None
    matches_models: bool = False

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "database": self.database,
            "head": self.head,
            "at_head": self.at_head,
            "unversioned_at": self.unversioned_at,
            "matches_models": self.matches_models,
        }


def head_status_on(connection: Connection) -> HeadStatus:
    """:class:`HeadStatus` for an open connection (a request-scoped session's, in ``/health``)."""
    head = head_revision()
    applied = tuple(sorted(_current_heads(connection)))
    if applied:
        return HeadStatus(",".join(applied), head, applied == (head,))
    present, _expected = _model_tables_present(connection)
    if not present:
        return HeadStatus(None, head, False)
    at = _unversioned_revision(connection)
    matches = at == head and not compare_metadata(
        MigrationContext.configure(connection), Base.metadata
    )
    return HeadStatus(None, head, False, unversioned_at=at, matches_models=matches)


def head_status(url: str | None = None) -> HeadStatus:
    """:class:`HeadStatus` for ``url`` (default: ``CRB_DATABASE_URL``); opens and disposes
    its own engine, so ``crb doctor`` can call it from a bare shell."""
    engine = make_engine(database_url(url))
    try:
        with engine.connect() as connection:
            return head_status_on(connection)
    finally:
        engine.dispose()


def check(url: str | None = None) -> bool:
    """``True`` iff the database is at the packaged head (no pending, no unknown revisions)."""
    return head_status(url).at_head


# ---------------------------------------------------------------------------
# ``python -m crb.store.migrate``
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """The ``python -m crb.store.migrate`` argument parser."""
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
    """CLI entry: ``upgrade`` (default) / ``current`` / ``check``; ``check`` exits 1 when the
    database is not at head so an entrypoint or a Helm hook can gate on it."""
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
    "REVISION_INDEXES",
    "REVISION_MARKERS",
    "REVISION_TABLES",
    "HeadStatus",
    "SchemaStateError",
    "alembic_config",
    "check",
    "current",
    "head_revision",
    "head_status",
    "head_status_on",
    "install_append_only_triggers_on",
    "main",
    "upgrade",
]
