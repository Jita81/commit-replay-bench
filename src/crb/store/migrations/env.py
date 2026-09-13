"""Alembic ``env.py`` for crb.store.

Where the database comes from, in precedence order:

1. ``config.attributes["connection"]`` — a live :class:`sqlalchemy.Connection` handed in
   by :mod:`crb.store.migrate` (the server / entrypoint path). The whole upgrade runs in
   the caller's transaction, so on PostgreSQL a failed migration leaves nothing behind.
2. ``-x url=<url>`` on the ``alembic`` command line.
3. ``sqlalchemy.url`` set programmatically on the config (never in ``alembic.ini``).
4. ``CRB_DATABASE_URL`` / the ``CRB_HOME`` SQLite default via :func:`crb.store.db.database_url`.

Engines are always built with :func:`crb.store.db.make_engine` so a migrated SQLite file
carries the same pragmas (WAL, foreign keys, synchronous=FULL) as one created by
:func:`crb.store.db.init_db`.

Invariant checked by ``tests/test_store_migrate.py``: ``alembic upgrade head`` on an empty
database and ``Base.metadata.create_all`` produce the same schema (autogenerate diff is
empty; on SQLite the ``sqlite_master`` rows are identical), and both carry the append-only
triggers.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from crb.store.db import database_url, make_engine
from crb.store.models import Base

config = context.config
target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    return str(x_args.get("url") or config.get_main_option("sqlalchemy.url") or database_url())


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade head --sql``) — for change review, not for use."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied = config.attributes.get("connection")
    if isinstance(supplied, Connection):
        _run(supplied)
        return
    engine = make_engine(_resolve_url())
    try:
        with engine.begin() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
