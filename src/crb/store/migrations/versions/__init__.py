"""Revision scripts: one linear chain, zero-padded integer revision ids (``0001`` …).

Create the next one with
``alembic -c src/crb/store/alembic.ini revision --rev-id 0002 -m "<slug>"``.

Navigation
----------
What it is:   The package holding the revision scripts (``v0001_…`` …), one linear chain.
What it does: Nothing at runtime; documents the naming rule and the command that creates the
              next revision.
How:          Packaging only.
Layer:        store — docs/ARCHITECTURE.md#73-data-model-store-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/migrations/versions/v0001_initial_schema.py (the base revision and
              the migration rules), src/crb/store/migrate.py (``REVISION_MARKERS`` /
              ``REVISION_TABLES`` — every new revision registers there),
              src/crb/store/models.py (what a revision must end up equal to)
Tested by:    tests/test_store_migrate.py
Touch when:   a new revision is added — keep the chain linear (one head) and zero-padded.
"""
