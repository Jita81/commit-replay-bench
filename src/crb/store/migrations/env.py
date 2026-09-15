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

Navigation
----------
What it is:   Alembic's ``env.py`` — how a migration run finds its database connection.
What it does: Prefers the live connection src/crb/store/migrate.py hands in (one transaction
              for the whole upgrade), else builds an engine from ``-x url``, the config, or
              ``CRB_DATABASE_URL``; enables SQLite batch mode so column drops work there;
              offline mode emits SQL for review only.
How:          ``run_migrations_online`` → ``_run`` with ``target_metadata = Base.metadata``,
              ``compare_type=True``, ``render_as_batch`` on SQLite; ``run_migrations_offline``
              renders with literal binds.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/migrate.py (sets ``config.attributes["connection"]``),
              src/crb/store/db.py (``make_engine`` so a migrated SQLite file carries the same
              pragmas), src/crb/store/models.py (``Base.metadata`` for autogenerate)
Tested by:    tests/test_store_migrate.py
Touch when:   never for a new repository; only if the connection-resolution order or the
              autogenerate options change (then update the parity test).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from crb.store.db import database_url, make_engine
from crb.store.models import Base

config = context.config
target_metadata = Base.metadata


def _resolve_url() -> str:
    """Precedence 2–4 of the module docstring (the live connection, 1, bypasses this)."""
    x_args = context.get_x_argument(as_dictionary=True)
    return str(x_args.get("url") or config.get_main_option("sqlalchemy.url") or database_url())


def _run(connection: Connection) -> None:
    """Run the revision scripts on ``connection`` inside Alembic's transaction context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER a column in place; batch mode rewrites the table for it.
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
    """Migrate against a live database: the caller's connection when one was supplied,
    otherwise an engine of our own (disposed afterwards)."""
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
