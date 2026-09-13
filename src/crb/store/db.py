"""Engine / session factory / schema init, including the append-only triggers.

The triggers are the store-level half of the honesty invariant: the ledger
tables can be appended to and read, never rewritten. They are installed for
SQLite (``RAISE(ABORT)``) and PostgreSQL (a trigger function raising an
exception). Alembic migrations (``crb.store.migrations``) call the same helper
so a migrated database carries the same protection as a freshly created one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
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
    resolved = database_url(url)
    if resolved.startswith("sqlite"):
        path = resolved.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            resolved, echo=echo, connect_args={"check_same_thread": False, "timeout": 30}
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=FULL")
            cur.close()

        return engine
    return create_engine(resolved, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
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
