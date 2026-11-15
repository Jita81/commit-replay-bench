"""A context set's arm never certifies, licenses or routes (ADR-0050 item 9).

Navigation
----------
What it is:   The exclusion suite for the readers that certify, license or route a cell.
What it does: Pins that ``ReadingBook.standard_rows`` drops measurement-only rows (a control
              run's plain ``A0`` rows stay), that ``?arm=`` naming a context-set arm is 422
              ``measurement_only_arm``, that ``crb route --arm`` refuses one and names
              ``crb ctxset compare``, that no reading registers one in its hierarchy or as a
              descriptive arm, and that the re-measure plan lists no measurement-only cell.
How:          Rows from tests/fixtures/ctx_rows.py; readings from tests/fixtures/readings.py.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/capability.py (``ReadingBook.standard_rows`` drops the rows),
              src/crb/server/routes/capability.py (``rows_for_arm_param``, the 422),
              src/crb/cli/commands/route.py (``crb route --arm`` refuses the arm),
              src/crb/core/reading.py (``ReadingRefused`` for a measurement-only arm),
              src/crb/core/learn.py (``remeasure_plan`` lists no such cell),
              tests/fixtures/ctx_rows.py (the control and context-set rows)
Tested by:    tests/test_capability_ctx.py
Touch when:   never for a new repository; a reader that certifies, licenses or routes is added.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.cli.main import main
from crb.core import ctxset, learn
from crb.core.capability import PROJECTION_CELL, ReadingBook
from crb.core.context_arm import measurement_only
from crb.core.ledger import GradeRow, JsonlLedger
from crb.core.reading import ReadingRefused
from crb.server.deps import ApiError
from crb.server.routes.capability import REFUSAL_MEASUREMENT_ONLY_ARM, rows_for_arm_param
from fixtures.ctx_rows import TASKS, ctx_set, side
from fixtures.readings import AUTHOR, CELL, commits, register_reading, sealed_row

ORACLE = ctx_set(ctxset.SOURCE_ORACLE)
CONTROL = dict.fromkeys(TASKS, False) | {TASKS[0]: True}
TREAT = dict.fromkeys(TASKS, True)


def test_standard_rows_drop_ctx_rows_and_keep_control() -> None:
    control = side(ORACLE, CONTROL, role=ctxset.ROLE_CONTROL)
    treat = side(ORACLE, TREAT)
    kept = ReadingBook().standard_rows([*control, *treat], PROJECTION_CELL)
    assert kept and not any(measurement_only(r.context_arm) for r in kept)
    assert sorted(r.task_id for r in kept) == sorted(r.task_id for r in control)
    # a cell holding the treatment alone has no standard: under the old reader it fell back
    # to the first arm it held, the context-set arm itself
    assert ReadingBook().standard_rows(treat, PROJECTION_CELL) == []


def test_arm_param_refuses_a_ctx_arm() -> None:
    rows = side(ORACLE, TREAT)
    with pytest.raises(ApiError) as exc:
        rows_for_arm_param(rows, ORACLE.arm)
    assert exc.value.status_code == 422
    assert exc.value.code == REFUSAL_MEASUREMENT_ONLY_ARM
    assert exc.value.detail == {"arm": ORACLE.arm, "compare": "/ctxsets/compare"}
    # the plain control arm is an honest arm and is still served
    assert rows_for_arm_param(side(ORACLE, CONTROL, role=ctxset.ROLE_CONTROL), "A0")


def test_cli_route_refuses_a_ctx_arm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "ledger.jsonl"
    JsonlLedger(path).append_many(side(ORACLE, TREAT))
    capsys.readouterr()
    code = main(
        ["route", "--arm", ORACLE.arm, "--workdir", str(tmp_path / ".crb"), "--path", str(path)]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "measurement-only" in err and "crb ctxset compare" in err


def test_no_reading_names_a_ctx_arm() -> None:
    pool = commits(40)
    with pytest.raises(ReadingRefused, match="measurement-only"):
        register_reading(pool, hierarchy=("S3", ORACLE.arm))
    with pytest.raises(ReadingRefused, match="measurement-only"):
        register_reading(pool, descriptive=(("A0", 16), (ORACLE.arm, 16)))


def test_remeasure_plan_lists_no_ctx_cell() -> None:
    rows = [*side(ORACLE, TREAT), *side(ORACLE, CONTROL, role=ctxset.ROLE_CONTROL)]
    plan = learn.remeasure_plan(rows, readings=())
    arms = [c.to_dict()["arm"] for c in plan.cells]
    assert arms == ["A0"]  # the control's honest cell is still planned
    assert learn.remeasure_plan(side(ORACLE, TREAT), readings=()).cells == ()


def test_remeasure_plan_never_prices_a_top_up_from_ctx_rows() -> None:
    """A pending reading's top-up is priced and timed from the cell's honest rows only: a
    context-set row of the same cell and mode (blind) never moves the estimate."""
    reading = register_reading(commits(40), hierarchy=(f"S1@{AUTHOR}",))
    pool = list(reading.pool)
    priced = [sealed_row(x, arm="A0", cost_usd=0.4, latency_s=30.0) for x in commits(3, "p")]
    ctx_rows = side(ORACLE, TREAT, cost_usd=99.0, latency_s=900.0)
    assert {r.cell.label for r in ctx_rows} == {"|".join(CELL.values())}

    def plan(rows: list[GradeRow]) -> learn.RemeasureCell:
        (c,) = learn.remeasure_plan(
            rows,
            readings=ReadingBook.evaluate([reading], rows).outcomes,
            task_labels=dict.fromkeys(pool, (CELL["capability_class"], CELL["size"])),
            gold_clean_tasks=pool,
            s1_author_model=AUTHOR,
        ).cells
        return c

    honest, mixed = plan(priced), plan([*priced, *ctx_rows])
    assert mixed.cost_usd_mean == pytest.approx(0.4) == honest.cost_usd_mean
    assert mixed.latency_s_mean == pytest.approx(30.0) == honest.latency_s_mean
    assert mixed.est_cost_usd == honest.est_cost_usd and mixed.n_stale == honest.n_stale
