"""Every cell proven at the store-bound seam: the factory entry gate's readers, patched.

Navigation
----------
What it is:   A test helper that makes every cell of every repository read as a proven, signed
              context standard of one arm, at the ONE place the server binds the entry gate's
              readers to the store (``crb.server.factory_standard``).
What it does: ``every_cell_proven(monkeypatch, arm)`` patches ``bind_readers`` (the worker's
              binding, once per run and per intake pass) and ``readers_in`` (the factory
              routes' preview) to answer ``Standard(arm, signed=True)`` for every cell.
How:          ``monkeypatch.setattr`` on the module both callers reach it through.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/server/factory_standard.py (the seam), tests/test_worker.py,
              tests/test_worker_fetch.py, tests/test_intake_worker.py,
              tests/test_server_routes_factory.py, tests/test_server_routes_intake.py
Tested by:    the tests above (a factory run builds only when a cell is proven)
Touch when:   never for a new repository; the binding's signature changes.
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.factory.standard import Readers, Standard
from crb.server import factory_standard


def every_cell_proven(monkeypatch: pytest.MonkeyPatch, arm: str = "S2") -> None:
    """Every cell has a proven, signed standard of ``arm`` (ADR-0026 item 8)."""
    readers = Readers(standard_for=lambda cell: Standard(arm, signed=True))

    def bound(*_a: Any, **_kw: Any) -> Readers:
        return readers

    monkeypatch.setattr(factory_standard, "bind_readers", bound)
    monkeypatch.setattr(factory_standard, "readers_in", bound)


__all__ = ["every_cell_proven"]
