"""Alembic environment for :mod:`crb.store` (``env.py``, ``script.py.mako``, ``versions/``).

Driven by :mod:`crb.store.migrate`; application code never imports this package.

Navigation
----------
What it is:   The Alembic script directory as a Python package (so ``env.py`` and the
              revision scripts ship inside the wheel).
What it does: Holds nothing but the docstring; Alembic locates ``env.py`` and ``versions/``
              through the ``script_location`` that src/crb/store/migrate.py sets.
How:          Packaging only.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/migrate.py (the driver), src/crb/store/migrations/env.py (the
              environment), src/crb/store/migrations/versions/__init__.py (the revisions)
Tested by:    tests/test_store_migrate.py
Touch when:   never.
"""
