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

Navigation
----------
What it is:   The ``crb.store`` package — its public surface (engine, session factory,
              ``init_db``, ``DbLedger``, ``Base``) and the layer's contract in one place.
What it does: Re-exports the five names the server, worker and CLI need to open a database
              and write to the ledger, so callers never import ``crb.store.models`` or
              ``crb.store.db`` directly for the common path.
How:          Plain re-exports; no logic. The docstring above is the layer's contract.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/store/db.py (engine, session, triggers), src/crb/store/ledger.py (the
              DB ledger), src/crb/store/models.py (the tables), src/crb/store/migrate.py (the
              schema's versioned path), src/crb/server/app.py (the lifespan that opens the
              store for the API)
Tested by:    tests/test_store_db.py, tests/test_store_ledger.py, tests/test_store_migrate.py
Touch when:   never for a new repository; only when a new store-level object becomes part of
              the public surface (add the re-export and the name to ``__all__`` together).
"""

from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.ledger import DbLedger
from crb.store.models import Base

__all__ = ["Base", "DbLedger", "init_db", "make_engine", "make_session_factory"]
