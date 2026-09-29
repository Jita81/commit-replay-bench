"""What operating costs, measured: a thousand rows exported and verified, and the store's
growth (G-401; the figures OPERATOR §6.1 states).

OPERATOR said what a sweep might cost as an example and nothing about the routine, the
minutes a verify-and-export takes or the storage a thousand rows add. Those last two are
properties of the code, so they are measured here on synthetic rows and the guide quotes
them with this test as the apparatus. The bounds are loose — several times the observed
value on a loaded laptop — so the test states an order of magnitude, never a benchmark.

Navigation
----------
What it is:   The measurement behind OPERATOR §6.1's export-and-verify time and store growth.
What it does: Appends 1000 synthetic ``GradeRow``s through the ledger's own writer into a
              temporary SQLite store, streams them through the JSONL export the API serves,
              re-verifies the chain the way ``GET /ledger/verify`` does, and asserts each
              finished inside a loose bound and that the store file grew by at most a loose
              bound; prints the observed figures so a re-measurement can update the guide.
How:          ``DbLedger.append_many`` → ``_jsonl`` (routes/ledger.py) → ``verify_ledger``;
              ``time.perf_counter`` and the store file's size before and after.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   docs/OPERATOR.md#61-what-operating-costs-in-time-money-and-storage (quotes the
              figures), src/crb/store/ledger.py (``DbLedger``), src/crb/server/routes/ledger.py
              (``_jsonl`` and ``verify_ledger``), src/crb/core/ledger.py (``GradeRow``),
              docs/dod/journeys/operate.md (journey-operate.time-cost.13)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the row shape grows (re-measure and change §6.1's
              figures with the bounds here), or the export or verify path changes.
"""

from __future__ import annotations

import time
from pathlib import Path

from crb.core.ledger import GradeRow
from crb.server.routes.ledger import _jsonl, verify_ledger
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.ledger import DbLedger
from fixtures.posture import posture_row

ROWS = 1000
#: Loose bounds (seconds; bytes): several times what one run observed on a loaded M-series
#: laptop — see OPERATOR §6.1 for the observed figures and their date.
EXPORT_BOUND_S = 30.0
VERIFY_BOUND_S = 30.0
GROWTH_BOUND_BYTES = 4 * 1024 * 1024


def _row(i: int) -> GradeRow:
    """One synthetic measured row with the posture labels this apparatus requires."""
    return posture_row(
        repo="synthetic",
        task_id=f"{i:040x}",
        clean=i % 3 == 0,
        tests_unmodified=True,
        target_green=i % 3 == 0,
        no_new_failures=True,
        source_changed=True,
        repo_lint_clean=True,
        capability_class="feature_add",
        size="S",
        language="python",
        builder="fixture_gold",
        model="gold",
        run_id="r" * 32,
        trial="r1",
        actor="test",
        # a clean row cites its pack; the pack's presence is verify's clean_without_pack
        # count, not the chain, so the hash alone is enough for a timing
        evidence_pack_hash=f"{i:064x}" if i % 3 == 0 else "",
        labels={"source": "synthetic"},
    )


def test_a_thousand_rows_export_and_verify_within_bound_and_grow_the_store_by_at_most_bound(
    tmp_path: Path,
) -> None:
    store = tmp_path / "cost.db"
    engine = make_engine(f"sqlite:///{store}")
    init_db(engine)
    factory = make_session_factory(engine)
    before = store.stat().st_size

    DbLedger(factory).append_many(_row(i) for i in range(ROWS))
    engine.dispose()
    grown = store.stat().st_size - before
    # a wal/journal file would hide growth: measure the main file after the engine is gone
    assert not (tmp_path / "cost.db-wal").exists() or (tmp_path / "cost.db-wal").stat().st_size == 0

    t0 = time.perf_counter()
    exported = sum(len(chunk) for chunk in _jsonl(factory, None))
    export_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    with factory() as s:
        verdict = verify_ledger(s)
    verify_s = time.perf_counter() - t0

    print(
        f"\noperating-costs: rows={ROWS} store_growth_bytes={grown} "
        f"export_s={export_s:.3f} export_bytes={exported} verify_s={verify_s:.3f}"
    )
    assert verdict.rows == ROWS and verdict.chain_ok
    assert exported > ROWS * 200  # every row left as a full JSON line
    assert export_s < EXPORT_BOUND_S, f"export of {ROWS} rows took {export_s:.1f} s"
    assert verify_s < VERIFY_BOUND_S, f"verify of {ROWS} rows took {verify_s:.1f} s"
    assert 0 < grown <= GROWTH_BOUND_BYTES, f"{ROWS} rows grew the store by {grown} bytes"
