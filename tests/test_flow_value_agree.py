"""The flow reading and the value scorecard read money and "clean" the same way.

Navigation
----------
What it is:   The agreement suite between ``GET /flow`` (``crb.server.flow``) and ``GET /value``
              (``crb.core.value``) — the two readers of a repository's spend.
What it does: Folds one set of graded rows through both and pins that they agree: the blind
              spend the scorecard divides by is the measure stream's spend over the same rows
              (priced rows summed, unpriced rows counted apart and never as zero, in both),
              and the clean attempts both count are the rows the ledger calls clean. If either
              reader stops using THE spend rule (``crb.core.flow.spend_of_rows``) or its own
              idea of a clean row, a case here fails.
How:          ``GradeRow`` built by the posture fixture — some priced, one unpriced (no builder
              reported a cost), all blind, current apparatus, the ``off`` checks arm, so the
              scorecard's headline scope and the measure stream's rows are the same rows.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md (the one checks arm the headline reads)
Works with:   src/crb/core/flow.py (``spend_of_rows`` — the one rule), src/crb/server/flow.py
              (``measure`` — the stream both readers overlap on), src/crb/core/value.py
              (``value_report`` — the north star's spend and clean count),
              tests/fixtures/posture.py (``posture_row``), docs/dod/streams/measure.md
              (the criterion this agreement closes)
Tested by:    tests/test_flow_value_agree.py
Touch when:   either reader changes what it sums or what it counts as clean — change both
              together, never one.
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core.ledger import GradeRow
from crb.core.value import value_report, value_row_from_grade
from crb.server.flow import measure
from fixtures.posture import posture_row


def row(i: int, *, clean: bool, cost: float) -> GradeRow:
    kw: dict[str, Any] = {
        "repo": "alpha",
        "task_id": f"{i:040x}",
        "run_id": "run-1",
        "mode": "blind",
        "capability_class": "bug.fix",
        "size": "S",
        "created": f"2026-09-20T10:{i:02d}:00+00:00",
        "cost_usd": cost,
        "tests_unmodified": True,
        "target_green": clean,
        "no_new_failures": True if clean else None,
        "source_changed": True if clean else None,
        "clean": clean,
    }
    if clean:
        kw["repo_lint_clean"] = True
        kw["evidence_pack_hash"] = f"{i:064x}"
    return posture_row(**kw).chained("0" * 64)


@pytest.fixture
def rows() -> list[GradeRow]:
    out = [row(i, clean=i < 3, cost=0.25) for i in range(8)]
    out.append(row(20, clean=False, cost=0.0))  # nobody reported this row's cost
    assert [r.cost_known for r in out].count(False) == 1
    return out


def test_the_scorecards_blind_spend_is_the_measure_streams_spend(rows: list[GradeRow]) -> None:
    flow = measure(rows, {"run-1": "blind"}, {"run-1": "2026-09-20T09:00:00+00:00"})
    ns = value_report([value_row_from_grade(r) for r in rows], []).to_dict()["north_star"]
    assert flow.spend.usd == pytest.approx(ns["spend_usd"]) == pytest.approx(8 * 0.25)
    assert flow.spend.rows_priced == ns["spend_rows_priced"] == 8
    assert flow.spend.rows_unpriced == ns["spend_rows_unpriced"] == 1
    # the unpriced row withholds the per-pound figure rather than read as £0
    assert ns["per_pound"] is None and ns["per_pound_withheld"]


def test_both_count_the_rows_the_ledger_calls_clean(rows: list[GradeRow]) -> None:
    ns = value_report([value_row_from_grade(r) for r in rows], []).to_dict()["north_star"]
    assert ns["clean"] == sum(1 for r in rows if r.clean) == 3
    assert all(value_row_from_grade(r).clean == r.clean for r in rows)
