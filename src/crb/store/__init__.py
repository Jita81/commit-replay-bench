"""crb.store — durable storage for the server: SQLAlchemy 2 models, the DB-backed
hash-chained ledger, and JSONL import/export.

* SQLite by default (``sqlite:///./.crb/crb.db``), PostgreSQL for production.
* ``grades``, ``events`` and ``signoffs`` are **append-only**: database triggers refuse
  ``UPDATE`` and ``DELETE`` (see :func:`crb.store.db.install_append_only_triggers`).
* :class:`crb.store.ledger.DbLedger` has the same contract as
  :class:`crb.core.ledger.JsonlLedger` — ``append`` validates the false-Q1 invariant,
  chains ``prev_hash``/``row_hash`` under a write lock, and ``verify`` walks the chain.
* Rows exported to JSONL carry their chain hashes and verify standalone with
  :func:`crb.core.ledger.verify_chain`.
"""

from crb.store.db import Base, init_db, make_engine, make_session_factory
from crb.store.ledger import DbLedger

__all__ = ["Base", "DbLedger", "init_db", "make_engine", "make_session_factory"]
