"""The suite-wide ``CRB_*`` environment guard: no test hands its settings to the next (P-302).

Navigation
----------
What it is:   The generator the autouse fixture ``_no_crb_env_leak`` in tests/conftest.py
              wraps around every test.
What it does: Records every ``CRB_*`` variable before a test and, after it, removes the ones
              the test added and restores the ones it changed or deleted — so a test (or the
              code under test, as ``worker_main.settings_from_args`` does with ``CRB_HOME``)
              can never point a later test at a home, an env or a setting it did not choose.
              Variables outside ``CRB_*`` are left alone.
How:          A snapshot of ``os.environ`` filtered by prefix, restored in ``finally``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/conftest.py (the autouse fixture), src/crb/server/worker_main.py (a writer
              of ``CRB_HOME`` into the process environment), tests/test_lint.py (asserts the
              suite never runs against a real home — the test the leak failed)
Tested by:    tests/test_env_guard.py
Touch when:   never for a new repository; the product reads configuration from a variable outside
              ``CRB_*``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

#: Every variable the product reads its configuration from starts with this.
CRB_ENV_PREFIX = "CRB_"


def crb_env_restored() -> Iterator[None]:
    """Yield once; afterwards the ``CRB_*`` variables are exactly as they were before."""
    before = {k: v for k, v in os.environ.items() if k.startswith(CRB_ENV_PREFIX)}
    try:
        yield
    finally:
        for key in [k for k in os.environ if k.startswith(CRB_ENV_PREFIX) and k not in before]:
            del os.environ[key]
        os.environ.update(before)
