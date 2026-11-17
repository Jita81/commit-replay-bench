"""crb.core.ctx_compare reads an accepted-plan set's runs and never pools them (ADR-0054).

Navigation
----------
What it is:   The paired reader's accepted-plan cases.
What it does: Pins that a ``ctx.plan*`` entries run pairs with its plain ``A0`` control
              and reads as planned, not as a ceiling and not as stated; and that pairing a
              plan arm with an entries run of another kind (a hindsight set) is refused as a
              blend, either way round.
How:          Rows from tests/fixtures/ctx_rows.py, stamped as a run stamps them.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctx_compare.py (under test), tests/fixtures/ctx_rows.py
              (``plan_set``, ``side``), tests/test_ctx_compare.py (the reader's own suite)
Tested by:    tests/test_ctx_compare_plan.py
Touch when:   never for a new repository; the reader's plan rule changes (an ADR first).
"""

from __future__ import annotations

import pytest

from crb.core import ctx_compare as cc
from crb.core import ctxset
from fixtures.ctx_rows import TASKS, ctx_set, plan_set, side

PLAN = plan_set()
ORACLE = ctx_set(ctxset.SOURCE_ORACLE)
SETS = {PLAN.digest: PLAN, ORACLE.digest: ORACLE}
CONTROL = dict.fromkeys(TASKS, False) | {TASKS[5]: True}
TREAT = dict.fromkeys(TASKS, True) | {TASKS[5]: False}


def test_a_plan_run_pairs_with_its_control_and_reads_as_planned() -> None:
    pair = cc.ctx_pair(
        side(PLAN, CONTROL, role=ctxset.ROLE_CONTROL),
        side(PLAN, TREAT),
        task_ids=PLAN.task_ids,
        sets=SETS,
    )
    assert pair.planned
    assert not pair.ceiling
    assert not pair.stated
    assert (pair.b, pair.c) == (5, 1)
    assert pair.complete


@pytest.mark.parametrize("plan_is_treatment", [True, False])
def test_a_plan_arm_never_pools_with_another_kind(plan_is_treatment: bool) -> None:
    plan_rows, oracle_rows = side(PLAN, TREAT), side(ORACLE, CONTROL)
    control, treatment = (oracle_rows, plan_rows) if plan_is_treatment else (plan_rows, oracle_rows)
    with pytest.raises(cc.CtxPairRefused) as exc:
        cc.ctx_pair(control, treatment, task_ids=TASKS, sets=SETS)
    assert exc.value.reason == cc.REASON_BLEND
