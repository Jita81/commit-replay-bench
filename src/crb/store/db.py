"""Engine / session factory / schema init, including the append-only triggers.

The triggers are the store-level half of the honesty invariant: the ledger
tables can be appended to and read, never rewritten. They are installed for
SQLite (``RAISE(ABORT)``) and PostgreSQL (a trigger function raising an
exception). Alembic migrations (``crb.store.migrations``) call the same helper
so a migrated database carries the same protection as a freshly created one.

Navigation
----------
What it is:   The engine / session factory / schema-init module of the store, and the home of
              the append-only trigger SQL.
What it does: Resolves the database URL (``CRB_DATABASE_URL`` → explicit → SQLite under
              ``CRB_HOME``), builds a SQLAlchemy engine with the SQLite pragmas the ledger
              relies on (WAL, foreign keys, ``synchronous=FULL``), and installs the
              ``UPDATE``/``DELETE``-refusing triggers on every append-only table. Refuses any
              dialect other than SQLite or PostgreSQL rather than run without the triggers.
How:          ``database_url`` → ``make_engine`` (per-connection pragmas via an event
              listener) → ``init_db`` = ``create_all`` + ``install_append_only_triggers``;
              ``session_scope`` is the commit-or-rollback context for callers outside FastAPI.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Base`` and ``APPEND_ONLY_TABLES``),
              src/crb/store/migrate.py (installs the same triggers on Alembic's connection),
              src/crb/store/ledger.py (relies on the triggers and the WAL/busy-timeout
              settings), src/crb/server/app.py (calls ``make_engine`` / ``init_db`` in the
              lifespan), src/crb/server/settings.py (the URL the server passes in)
Tested by:    tests/test_store_db.py, tests/test_store_migrate.py, tests/test_store_ledger.py
Touch when:   never for a new repository (the database is per deployment, not per repo);
              adding an append-only table means adding it to ``APPEND_ONLY_TABLES`` in
              models.py AND pinning it in the migration that creates it; changing a pragma
              or the trigger SQL needs a note in docs/adr/0002-append-only-hash-chained-ledger.md.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from crb.store.models import APPEND_ONLY_TABLES, Base

DEFAULT_SQLITE_PATH = ".crb/crb.db"


def database_url(url: str | None = None) -> str:
    """``CRB_DATABASE_URL`` env → explicit ``url`` → local SQLite under ``CRB_HOME``."""
    if url:
        return url
    env = os.environ.get("CRB_DATABASE_URL")
    if env:
        return env
    home = Path(os.environ.get("CRB_HOME", ".crb"))
    return f"sqlite:///{home / 'crb.db'}"


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """An engine for ``url`` (resolved by :func:`database_url`), configured per dialect.

    SQLite gets the pragmas the ledger's write lock and durability depend on; PostgreSQL
    gets ``pool_pre_ping`` so a connection dropped by the server is replaced, not raised.
    """
    resolved = database_url(url)
    parsed = make_url(resolved)
    if parsed.get_backend_name() == "sqlite":
        # ``make_url`` rather than string-stripping: ``sqlite+pysqlite:///``, ``sqlite://``
        # (memory) and ``?mode=…`` query forms all parse; the old prefix strip left the
        # driver in the path and created a directory named after it (CodeRabbit, PR #4).
        path = parsed.database or ""
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the API serves requests from a thread pool and the worker
        # shares the file; timeout=30: the busy timeout that makes BEGIN IMMEDIATE wait for a
        # concurrent writer instead of failing with "database is locked".
        engine = create_engine(
            resolved, echo=echo, connect_args={"check_same_thread": False, "timeout": 30}
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
            # Per connection, because SQLite pragmas are connection-scoped. WAL lets readers
            # (SSE, the UI) proceed while the worker writes; FULL fsyncs every commit so a
            # ledger row that was acknowledged survives a crash.
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=FULL")
            cur.close()

        return engine
    return create_engine(resolved, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """The session factory every store class takes. ``expire_on_commit=False`` so a row
    returned from a closed session (the API's common case) is still readable."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session that commits on success, rolls back on any exception, always closes."""
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _sqlite_trigger_sql(table: str) -> list[str]:
    # IF NOT EXISTS makes re-installation (init_db on an existing file, migrate.upgrade)
    # a no-op rather than an error.
    return [
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;",
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;",
    ]


_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION crb_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def _pg_trigger_sql(table: str) -> list[str]:
    # PostgreSQL has no CREATE TRIGGER IF NOT EXISTS; DROP + CREATE gives the same
    # idempotence (the function above is CREATE OR REPLACE for the same reason).
    return [
        f"DROP TRIGGER IF EXISTS {table}_no_update ON {table};",
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION crb_append_only();",
        f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table};",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION crb_append_only();",
    ]


def install_append_only_triggers(
    engine: Engine, tables: tuple[str, ...] = APPEND_ONLY_TABLES
) -> None:
    """Install the ``UPDATE``/``DELETE``-refusing triggers on ``tables`` (idempotent).

    The one place the trigger SQL lives: ``init_db`` and every Alembic revision (through
    :func:`crb.store.migrate.install_append_only_triggers_on`) call this. An unsupported
    dialect raises rather than leaving the ledger rewritable.
    """
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            for t in tables:
                for stmt in _sqlite_trigger_sql(t):
                    conn.execute(text(stmt))
        elif dialect == "postgresql":
            conn.execute(text(_PG_FUNCTION))
            for t in tables:
                for stmt in _pg_trigger_sql(t):
                    conn.execute(text(stmt))
        else:  # pragma: no cover — other dialects are unsupported by policy
            raise RuntimeError(f"append-only triggers not implemented for dialect {dialect!r}")


def init_db(engine: Engine) -> None:
    """Create all tables and install the append-only triggers (idempotent)."""
    Base.metadata.create_all(engine)
    install_append_only_triggers(engine)
