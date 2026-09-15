"""Test fixtures: tiny, fast, hermetic repositories the core engine is exercised on.

Navigation
----------
What it is:   The ``fixtures`` package marker: tiny, fast, hermetic repositories the engine is
              exercised on.
What it does: Makes ``from fixtures import pyrepo`` (and ``.langs``, ``.oracle_repo``,
              ``.server_seed`` …) importable from the tests directory; carries no code.
How:          pytest's default import mode puts ``tests/`` on ``sys.path`` when it loads
              ``tests/conftest.py``; the walkthrough script sets ``PYTHONPATH=tests`` for the same
              reason.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/pyrepo.py (the core fixture), tests/fixtures/langs/__init__.py (the
              per-language fixtures), tests/fixtures/server_seed.py (the seeded store),
              scripts/walkthrough.sh (imports ``fixtures.pyrepo`` from outside pytest)
Tested by:    tests/test_grade.py (any test importing ``fixtures``)
Touch when:   never — add a new fixture module beside it, not code here.
"""
