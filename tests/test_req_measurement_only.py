"""A stated-requirement set's rows never pool, certify, license or route (ADR-0052 item 1).

Navigation
----------
What it is:   The exclusion suite of tests/test_value_ctx.py and tests/test_capability_ctx.py
              run over ``ctx.req`` and ``ctx.req-placebo`` rows.
What it does: Pins that a req arm is measurement-only, that the value readers, the capability
              standard rows, the arm parameter, the readings and the re-measure plan drop or
              refuse its rows while the control's plain ``A0`` rows still count.
How:          Rows from tests/fixtures/ctx_rows.py (``req_set``, ``side``).
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0052-stated-requirement-arms.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/context_arm.py (``measurement_only``), src/crb/core/value.py (the
              value readers), src/crb/core/capability.py (``standard_rows``),
              src/crb/server/routes/capability.py (the arm parameter), src/crb/core/learn.py (the
              re-measure plan)
Tested by:    tests/test_req_measurement_only.py
Touch when:   never for a new repository; a reader that certifies, licenses or routes is added.
"""

from __future__ import annotations

import pytest

from crb.core import ctxset, learn
from crb.core.capability import PROJECTION_CELL, ReadingBook
from crb.core.context_arm import measurement_only
from crb.core.reading import ReadingRefused
from crb.core.value import (
    prospective_routing,
    value_report,
    value_row_from_grade,
    without_measurement_only,
)
from crb.server.deps import ApiError
from crb.server.routes.capability import REFUSAL_MEASUREMENT_ONLY_ARM, rows_for_arm_param
from fixtures.ctx_rows import TASKS, req_set, side
from fixtures.readings import commits, register_reading

REQ = req_set()
PLACEBO = req_set(
    ctxset.SOURCE_REQ_PLACEBO,
    statement="Weather over the hills stays calm through the long afternoon",
    matched_to=REQ.digest,
)
CONTROL = dict.fromkeys(TASKS, False) | {TASKS[0]: True}
TREAT = dict.fromkeys(TASKS, True)
SETS = pytest.mark.parametrize("cset", [REQ, PLACEBO], ids=["req", "req-placebo"])


@SETS
def test_a_req_arm_is_measurement_only(cset: ctxset.CtxSet) -> None:
    assert measurement_only(cset.arm)
    assert all(measurement_only(r.context_arm) for r in side(cset, TREAT))
    assert not any(
        measurement_only(r.context_arm) for r in side(cset, CONTROL, role=ctxset.ROLE_CONTROL)
    )


@SETS
def test_value_readers_drop_req_rows_and_keep_control(cset: ctxset.CtxSet) -> None:
    control = [value_row_from_grade(r) for r in side(cset, CONTROL, role=ctxset.ROLE_CONTROL)]
    treat = [value_row_from_grade(r) for r in side(cset, TREAT)]
    assert without_measurement_only([*control, *treat]) == control
    assert (
        value_report([*control, *treat], [], apparatus="all").to_dict()
        == value_report(control, [], apparatus="all").to_dict()
    )
    assert prospective_routing([*control, *treat]) == prospective_routing(control)


@SETS
def test_capability_and_routing_never_read_a_req_arm(cset: ctxset.CtxSet) -> None:
    control = side(cset, CONTROL, role=ctxset.ROLE_CONTROL)
    treat = side(cset, TREAT)
    kept = ReadingBook().standard_rows([*control, *treat], PROJECTION_CELL)
    assert sorted(r.task_id for r in kept) == sorted(r.task_id for r in control)
    with pytest.raises(ApiError) as exc:
        rows_for_arm_param(treat, cset.arm)
    assert exc.value.code == REFUSAL_MEASUREMENT_ONLY_ARM
    with pytest.raises(ReadingRefused, match="measurement-only"):
        register_reading(commits(40), hierarchy=("S3", cset.arm))
    plan = learn.remeasure_plan([*treat, *control], readings=())
    assert [c.to_dict()["arm"] for c in plan.cells] == ["A0"]
