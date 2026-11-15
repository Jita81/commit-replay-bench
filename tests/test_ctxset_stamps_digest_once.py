"""``run_stamps`` hashes a stated set's items once per call, not once per task (PR 150 review).

Navigation
----------
What it is:   A regression test for ``crb.core.ctxset.run_stamps`` over a stated set.
What it does: Pins that the items digest is computed once per call and that every task's
              stamp carries that one digest.
How:          Counts calls to ``crb.core.stated.items_digest`` through ``monkeypatch`` over the
              stated document from tests/test_stated.py.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0052-stated-requirement-arms.md
Works with:   src/crb/core/ctxset.py (under test), src/crb/core/stated.py (``items_digest``),
              tests/test_stated.py (the stated document stamped here)
Tested by:    tests/test_ctxset_stamps_digest_once.py
Touch when:   never for a new repository; ``run_stamps`` changes how it stamps a stated set.
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core import ctxset, stated
from test_stated import T1, req_doc


def test_run_stamps_computes_the_items_digest_once_for_all_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = ctxset.parse(req_doc("checklist"))
    expected = s.items_digest
    calls: list[int] = []
    real = stated.items_digest

    def counting(*args: Any, **kw: Any) -> str:
        calls.append(1)
        return real(*args, **kw)

    monkeypatch.setattr(stated, "items_digest", counting)
    gaps = dict.fromkeys(s.task_ids, "0")
    assert len(gaps) >= 2 and T1 in gaps
    stamps = ctxset.run_stamps(s, "entries", gaps)
    assert len(calls) == 1
    assert {st["ctx_items"] for st in stamps.values()} == {expected}
