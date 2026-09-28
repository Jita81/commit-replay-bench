"""Engine / session factory / schema init, including the append-only triggers.

The triggers are the store-level half of the honesty invariant: the ledger
tables can be appended to and read, never rewritten. They are installed for
SQLite (``RAISE(ABORT)``) and PostgreSQL (a trigger function raising an
exception). Alembic migrations (``crb.store.migrations``) call the same helper
so a migrated database carries the same protection as a freshly created one.

Short of DDL (on the tables or on their triggers), which only the tables' owner can
issue, no statement the product's connections can issue rewrites or removes an
append-only row: ``UPDATE`` and ``DELETE`` meet the row triggers; SQLite's ``REPLACE``
meets the delete trigger because every connection turns ``recursive_triggers`` on;
PostgreSQL's ``TRUNCATE`` meets a statement-level trigger and its ``ON CONFLICT DO
UPDATE`` the update trigger. Table DDL (``ALTER TABLE … ALTER COLUMN … TYPE … USING``,
``DROP COLUMN``, ``DROP TABLE``) rewrites or removes rows with no trigger firing, and
trigger DDL (``DROP``/``DISABLE``/a ``WHEN`` that never holds) stops the triggers; the
``append_only`` probe watches the triggers, ``verify`` catches a rewrite it did not
re-hash, and a separate owner role removes all of that DDL from the application's reach
on PostgreSQL (docs/DEPLOYMENT.md §3.3).

Navigation
----------
What it is:   The engine / session factory / schema-init module of the store, and the home of
              the append-only trigger SQL.
What it does: Resolves the database URL (``CRB_DATABASE_URL`` → explicit → SQLite under
              ``CRB_HOME``), builds a SQLAlchemy engine with the SQLite pragmas the ledger
              relies on (WAL, foreign keys, ``synchronous=FULL``, recursive triggers so a
              ``REPLACE`` fires the delete trigger), and installs the ``UPDATE``/``DELETE``-
              refusing triggers on every append-only table — plus, on PostgreSQL, a
              statement-level ``TRUNCATE``-refusing one. Refuses any dialect other than
              SQLite or PostgreSQL rather than run without the triggers.
How:          ``database_url`` → ``make_engine`` (per-connection pragmas via an event
              listener) → ``init_db`` = ``create_all`` + ``install_append_only_triggers``;
              ``expected_triggers`` is the one list the installer, the ``/health`` probe and
              the tests share; ``session_scope`` is the commit-or-rollback context for
              callers outside FastAPI.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/models.py (``Base`` and ``APPEND_ONLY_TABLES``),
              src/crb/store/migrate.py (installs the same triggers on Alembic's connection),
              src/crb/store/ledger.py (relies on the triggers and the WAL/busy-timeout
              settings), src/crb/server/app.py (calls ``make_engine`` / ``init_db`` in the
              lifespan), src/crb/server/settings.py (the URL the server passes in),
              src/crb/server/routes/system.py (the ``append_only`` probe counts
              ``expected_triggers``)
Tested by:    tests/test_store_db.py, tests/test_store_migrate.py, tests/test_store_ledger.py
Touch when:   never for a new repository (the database is per deployment, not per repo);
              adding an append-only table means adding it to ``APPEND_ONLY_TABLES`` in
              models.py AND pinning it in the migration that creates it; changing a pragma
              or the trigger SQL needs a note in docs/adr/0002-append-only-hash-chained-ledger.md.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Connection, Engine, Result, create_engine, event, text
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
            # REPLACE (``INSERT OR REPLACE`` / ``REPLACE INTO``) deletes the conflicting row
            # before it inserts, and that implicit delete fires the ``BEFORE DELETE``
            # append-only trigger only with recursive triggers on — without it a whole row
            # was rewritten in place and verified clean once re-hashed (EI-5, DL-081).
            cur.execute("PRAGMA recursive_triggers=ON")
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


#: The trigger kinds each dialect installs on every append-only table, with the event each
#: refuses. SQLite has no ``TRUNCATE`` (its truncate is ``DELETE`` without ``WHERE``, which
#: the row trigger refuses); PostgreSQL's ``TRUNCATE`` is a STATEMENT event no ``FOR EACH
#: ROW`` trigger sees, so it gets its own statement-level trigger (EI-4, DL-081).
TRIGGER_KINDS: dict[str, tuple[tuple[str, str], ...]] = {
    "sqlite": (("no_update", "UPDATE"), ("no_delete", "DELETE")),
    "postgresql": (("no_update", "UPDATE"), ("no_delete", "DELETE"), ("no_truncate", "TRUNCATE")),
}

#: The body of ``crb_append_only()`` exactly as installed — the live check compares it, so a
#: function its owner replaced with a no-op does not count as protection.
_PG_FUNCTION_SRC = """
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
"""
_PG_FUNCTION = (
    "CREATE OR REPLACE FUNCTION crb_append_only() RETURNS trigger AS $$"
    + _PG_FUNCTION_SRC
    + "$$ LANGUAGE plpgsql;"
)


def expected_triggers(
    dialect: str, tables: tuple[str, ...] = APPEND_ONLY_TABLES
) -> tuple[tuple[str, str], ...]:
    """``(table, trigger name)`` for every append-only trigger ``dialect`` must carry — the
    one list the installer, ``/health``'s ``append_only`` probe and the tests share. An
    unsupported dialect has none (it is refused before anything is written)."""
    kinds = TRIGGER_KINDS.get(dialect, ())
    return tuple((t, f"{t}_{kind}") for t in tables for kind, _ in kinds)


def _event_of(name: str, dialect: str) -> str:
    return next(ev for kind, ev in TRIGGER_KINDS[dialect] if name.endswith(f"_{kind}"))


def _sqlite_trigger_sql(table: str, name: str) -> str:
    return (
        f"CREATE TRIGGER {name} BEFORE {_event_of(name, 'sqlite')} ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
    )


def _pg_trigger_sql(table: str, name: str) -> str:
    event = _event_of(name, "postgresql")
    level = "STATEMENT" if event == "TRUNCATE" else "ROW"
    return (
        f"CREATE TRIGGER {name} BEFORE {event} ON {table} "
        f"FOR EACH {level} EXECUTE FUNCTION crb_append_only();"
    )


def _normalised(sql: str) -> str:
    """``sql`` with its whitespace collapsed and any trailing ``;`` dropped — how a stored
    trigger definition is compared with the installer's own."""
    return " ".join(sql.split()).rstrip(";").rstrip()


def _pg_definition_re(table: str, name: str) -> re.Pattern[str]:
    """What ``pg_get_triggerdef`` returns for :func:`_pg_trigger_sql`'s trigger: the same
    statement, the table schema-qualified (and the function too when it is not on the
    ``search_path``), no ``WHEN``, no column list, no arguments."""
    event = _event_of(name, "postgresql")
    level = "STATEMENT" if event == "TRUNCATE" else "ROW"
    schema = r'(?:(?:[a-z_][a-z0-9_$]*|"[^"]+")\.)?'
    return re.compile(
        f"CREATE TRIGGER {re.escape(name)} BEFORE {event} ON {schema}{re.escape(table)} "
        f"FOR EACH {level} EXECUTE FUNCTION {schema}crb_append_only\\(\\)"
    )


def _read(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> list[Any] | None:
    """The rows of ``sql``, or ``None`` on an offline (``alembic upgrade --sql``) connection,
    which emits statements and reads nothing — so every trigger is emitted there."""
    res = cast("Result[Any] | None", conn.execute(text(sql), params or {}))
    return None if res is None else list(res.all())


def _pg_function_src(conn: Connection) -> str | None:
    """The installed body of ``crb_append_only()``; ``None`` when absent or unreadable."""
    rows = _read(conn, "SELECT prosrc FROM pg_proc WHERE oid = to_regproc('crb_append_only')")
    return str(rows[0][0]) if rows else None


def live_triggers(conn: Connection) -> set[str]:
    """The expected append-only triggers that are LIVE on ``conn``'s database: on their own
    table, with the WHOLE definition the installer writes (so a ``WHEN`` clause or a column
    list that stops it firing is not live), and — on PostgreSQL — enabled and calling an
    unaltered ``crb_append_only()``. A trigger its table's owner disabled (``ALTER TABLE …
    DISABLE TRIGGER``), one of the right name hung on another table, one re-created with a
    never-true ``WHEN``, or a function rewritten to a no-op is not counted (EI-4), and so
    the installer re-creates it on the next start. ``/health``'s ``append_only`` probe and
    the installer both read it. Unsupported dialects: none."""
    dialect = conn.dialect.name
    expected = expected_triggers(dialect)
    wanted = set(expected)
    if dialect == "sqlite":
        rows = _read(conn, "SELECT tbl_name, name, sql FROM sqlite_master WHERE type = 'trigger'")
        if rows is None:
            return set()
        # the WHOLE definition must be the installer's own: a WHEN clause, a column list or
        # any other change can make a trigger that matches by name and text never fire
        found = {
            (str(t), str(n))
            for t, n, sql in rows
            if (str(t), str(n)) in wanted
            and _normalised(str(sql or "")) == _normalised(_sqlite_trigger_sql(str(t), str(n)))
        }
    elif dialect == "postgresql":
        if _pg_function_src(conn) != _PG_FUNCTION_SRC:
            return set()
        # tgenabled 'O' (origin) / 'A' (always) fire in an ordinary session; 'D' is disabled
        # and 'R' fires only on a replica. to_regclass resolves through the same search_path
        # the application's own statements use.
        rows = _read(
            conn,
            "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND t.tgenabled IN ('O', 'A') "
            "AND t.tgfoid = to_regproc('crb_append_only') "
            "AND c.relname = ANY(:tables) "
            "AND c.oid = to_regclass(quote_ident(c.relname))",
            {"tables": list(APPEND_ONLY_TABLES)},
        )
        if rows is None:
            return set()
        # pg_get_triggerdef is the catalogue's canonical text: it must be the installer's own
        # definition (a WHEN clause, a column list or FOR EACH changed is not live)
        found = {
            (str(t), str(n))
            for t, n, ddl in rows
            if (str(t), str(n)) in wanted
            and _pg_definition_re(str(t), str(n)).fullmatch(_normalised(str(ddl)))
        }
    else:  # pragma: no cover — unsupported by policy
        return set()
    return {name for table, name in expected if (table, name) in found}


def install_append_only_triggers(
    engine: Engine, tables: tuple[str, ...] = APPEND_ONLY_TABLES
) -> None:
    """Install every append-only trigger :func:`expected_triggers` names on ``tables`` that is
    not already live (idempotent): ``UPDATE`` and ``DELETE`` refused on both dialects, and a
    statement-level ``TRUNCATE`` on PostgreSQL.

    The one place the trigger SQL lives: ``init_db`` and every Alembic revision (through
    :func:`crb.store.migrate.install_append_only_triggers_on`) call this. A store whose
    triggers are all live gets NO DDL, so the API and the worker start under an application
    role that does not own the tables (which therefore cannot drop, disable or truncate
    them — docs/DEPLOYMENT.md §3.3); a trigger that is missing, disabled, moved or pointing
    at an altered function is re-created, which only the owner can do. An unsupported
    dialect raises rather than leaving the ledger rewritable.
    """
    dialect = engine.dialect.name
    if dialect not in TRIGGER_KINDS:  # pragma: no cover — other dialects are unsupported
        raise RuntimeError(f"append-only triggers not implemented for dialect {dialect!r}")
    with engine.begin() as conn:
        if dialect == "postgresql" and _pg_function_src(conn) != _PG_FUNCTION_SRC:
            conn.execute(text(_PG_FUNCTION))
        live = live_triggers(conn)
        for table, name in expected_triggers(dialect, tables):
            if name in live:
                continue
            if dialect == "sqlite":
                conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
                conn.execute(text(_sqlite_trigger_sql(table, name)))
            else:
                conn.execute(text(f"DROP TRIGGER IF EXISTS {name} ON {table}"))
                conn.execute(text(_pg_trigger_sql(table, name)))


def init_db(engine: Engine) -> None:
    """Create all tables and install the append-only triggers (idempotent)."""
    Base.metadata.create_all(engine)
    install_append_only_triggers(engine)
