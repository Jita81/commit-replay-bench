"""crb.core.value — a context set's rows never enter a value figure (ADR-0050 item 9).

Navigation
----------
What it is:   The exclusion suite for the value readers: a measurement-only arm's rows are
              dropped, a control run's plain ``A0`` rows are kept.
What it does: Pins that ``value_report`` and ``prospective_routing`` are identical with and
              without injected context-set rows, and that the control rows still count.
How:          Rows from tests/fixtures/ctx_rows.py adapted with ``value_row_from_grade``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/value.py (``without_measurement_only``), tests/fixtures/ctx_rows.py
              (the control and context-set rows), src/crb/core/context_arm.py
              (``measurement_only``, the predicate asserted on), src/crb/core/ctxset.py (the
              source and role constants)
Tested by:    tests/test_value_ctx.py
Touch when:   never for a new repository; a value reader is added or the measurement-only rule
              changes.
"""

from __future__ import annotations

from dataclasses import replace

from crb.core import ctxset
from crb.core.context_arm import measurement_only
from crb.core.value import (
    ReviewVerdict,
    ValueRow,
    north_star,
    prospective_routing,
    value_report,
    value_row_from_grade,
    without_measurement_only,
)
from fixtures.ctx_rows import TASKS, ctx_set, side

ORACLE = ctx_set(ctxset.SOURCE_ORACLE)
CONTROL = dict.fromkeys(TASKS, False) | {TASKS[0]: True}
TREAT = dict.fromkeys(TASKS, True)


def _rows(outcomes: dict[str, bool], role: str) -> list[ValueRow]:
    return [value_row_from_grade(r) for r in side(ORACLE, outcomes, role=role)]


def test_ctx_rows_are_dropped_control_rows_kept() -> None:
    control = _rows(CONTROL, ctxset.ROLE_CONTROL)
    treat = _rows(TREAT, ctxset.ROLE_ENTRIES)
    assert all(measurement_only(r.context_arm) for r in treat)
    assert not any(measurement_only(r.context_arm) for r in control)
    assert without_measurement_only([*control, *treat]) == control


def test_value_report_identical_with_and_without_ctx_rows() -> None:
    control = _rows(CONTROL, ctxset.ROLE_CONTROL)
    treat = _rows(TREAT, ctxset.ROLE_ENTRIES)
    plain = value_report(control, [], apparatus="all").to_dict()
    mixed = value_report([*control, *treat], [], apparatus="all").to_dict()
    assert mixed == plain


def test_control_rows_still_count() -> None:
    control = _rows(CONTROL, ctxset.ROLE_CONTROL)
    assert (
        value_report(control, [], apparatus="all").to_dict()
        != value_report([], [], apparatus="all").to_dict()
    )


def test_prospective_routing_ignores_ctx_rows() -> None:
    control = _rows(CONTROL, ctxset.ROLE_CONTROL)
    treat = _rows(TREAT, ctxset.ROLE_ENTRIES)
    assert prospective_routing([*control, *treat]) == prospective_routing(control)


def test_north_star_drops_verdicts_joined_to_ctx_rows() -> None:
    """A direct caller's verdicts on context-set patches never reach the precision basis:
    five mergeable reviews of treatment rows would otherwise make it a review basis."""
    control = _rows(CONTROL, ctxset.ROLE_CONTROL)
    treat = [
        replace(r, row_hash=f"{i:064x}") for i, r in enumerate(_rows(TREAT, ctxset.ROLE_ENTRIES))
    ]
    reviews = [
        ReviewVerdict(r.row_hash, r.repo, r.task_id, grade_clean=True, mergeable=True)
        for r in treat
    ]
    unjoined = ReviewVerdict("", control[0].repo, control[0].task_id, True, mergeable=False)
    plain = north_star(control, [unjoined], usd_per_gbp=1.25)
    mixed = north_star([*control, *treat], [unjoined, *reviews], usd_per_gbp=1.25, pooled=reviews)
    assert mixed == plain
    assert mixed.precision.review.n == 1  # the unjoined verdict is kept
