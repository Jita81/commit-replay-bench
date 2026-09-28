"""The forward reading: the one thing that promotes an ``S3`` ceiling (ADR-0026 items 4, 5, 8).

Navigation
----------
What it is:   The core suite for G-679 (``product.truth.215``): a forward reading of a ceiling,
              its enrolment of calibration builds, how it counts their held-out-graded first
              attempts, and the promotion it alone can make.
What it does: Pins that a forward reading registers only on a cell that reads ``ceiling`` and
              spends from THAT cell's one error budget; that its pool is the calibration builds
              whose held-out tests were written after it, in the order they were written; that
              it counts only an ``S2`` row graded on held-out tests (``acceptance: held_out``),
              at rung ``r1``, graded after it, and reads a held-out ``fail`` as a miss and an
              ``error``, another builder or a harness row as leaving the pool; that twenty passes
              promote the ceiling to an ``S2`` standard, while more ``S3`` rows, a pending or an
              insufficient forward reading never do; and that the ledger's routing first attempts
              read the same rule (P-690).
How:          ``fixtures.readings`` for the ceiling reading and its sealed rows;
              ``register_forward`` and ``with_enrolment`` over ``HeldOutTests`` records;
              factory ``S2`` rows built with ``fixtures.posture.posture_row``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (items 2, 4, 5 and 8)
Works with:   src/crb/core/reading.py (under test), src/crb/core/acceptance.py (the record and
              the rule), src/crb/core/ledger.py (``first_attempts``), tests/fixtures/readings.py
              (the ceiling's reading and its sealed rows)
Tested by:    this file
Touch when:   never for a new repository; the forward pool rule or the look rule changes (an ADR
              amending ADR-0026 first).
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core.acceptance import (
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    WHY_NOT_FIRST,
    HeldOutTests,
    held_out_labels,
    none_labels,
)
from crb.core.ledger import GradeRow, first_attempts
from crb.core.reading import (
    LEFT_HARNESS,
    LEFT_HELD_OUT_ERROR,
    LEFT_OTHER_CELL,
    OUTCOME_CEILING,
    OUTCOME_STANDARD,
    POOL_RULE_CALIBRATION,
    REFUSAL_BUDGET_SPENT,
    REFUSAL_NOT_A_CEILING,
    RULE_LOOK_V1_LATE,
    STATE_DELIVER,
    STATE_INSUFFICIENT,
    STATE_LOOK_PENDING,
    Reading,
    ReadingOutcome,
    ReadingRefused,
    budget_spent,
    evaluate,
    latest_outcome,
    register_forward,
    rule_spend,
    with_enrolment,
)
from fixtures.posture import posture_row
from fixtures.readings import CELL, REPO, S1, commits, register_reading, rows_for

FWD_AT = "2026-09-27T12:00:00+00:00"
WRITTEN = "2026-09-27T13:00:00+00:00"
GRADED = "2026-09-27T14:00:00+00:00"
BUILDER, MODEL, PROVIDER = "claude_code", "claude-sonnet-5", "anthropic"
FACTORY_CELL = {**CELL, "process_step": "factory"}


def _ceiling() -> tuple[Reading, list[GradeRow], ReadingOutcome]:
    """A reading whose ``S3`` delivered 20 of 20 and whose ``S1`` missed three: a ceiling."""
    pool = commits(20)
    reading = register_reading(pool, hierarchy=("S3", S1))
    rows = rows_for([True] * 20, pool, arm="S3") + rows_for([True] * 17 + [False] * 3, pool, arm=S1)
    outcome = evaluate(reading, rows)
    assert outcome.state == OUTCOME_CEILING and outcome.chain == ("S3",)
    return reading, rows, outcome


def _forward(ceiling: ReadingOutcome, **kw: Any) -> Reading:
    return register_forward(
        ceiling=ceiling,
        builder=BUILDER,
        model=MODEL,
        provider=PROVIDER,
        actor="op-1",
        existing=[ceiling.reading],
        now=FWD_AT,
        **kw,
    )


def _record(i: int, *, written_at: str = WRITTEN, **kw: Any) -> HeldOutTests:
    base: dict[str, Any] = {
        "repo": REPO,
        "item_id": f"T-{i}",
        "grant": f"grant-{i}",
        "files": (("tests/test_held_out.py", f"def test_it():\n    assert {i} == {i}\n"),),
        "author": "operator:bea",
        "written_at": written_at,
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "go",
    }
    base.update(kw)
    return HeldOutTests(**base)


def _s2_row(
    rec: HeldOutTests,
    *,
    result: str = RESULT_PASS,
    clean: bool = True,
    trial: str = "r1",
    created: str = GRADED,
    labels: dict[str, str] | None = None,
    **kw: Any,
) -> GradeRow:
    """A factory ``S2`` first attempt of ``rec``'s ticket, graded on its held-out tests."""
    stamp = held_out_labels(rec, result) if labels is None else labels
    fields: dict[str, Any] = {
        "repo": REPO,
        "task_id": f"oracle-{rec.item_id}",
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean,
        "no_new_failures": True,
        "source_changed": True,
        "repo_lint_clean": None,
        "evidence_pack_hash": "h" * 64 if clean else "",
        "apparatus_version": "2.4",
        "created": created,
        "trial": trial,
        "mode": "sighted",
        **FACTORY_CELL,
        **kw,
    }
    return posture_row(
        **fields,
        labels={
            "posture_class": "docker/copy/sealed",
            "builder_executor": "docker",
            "context_arm": "S2",
            "taxonomy": "global/classes@v1",
            "item_id": rec.item_id,
            "calibration": "true",
            **stamp,
        },
    )


def _promoted(n: int = 20) -> tuple[ReadingOutcome, ReadingOutcome, Reading, list[HeldOutTests]]:
    _reading, _rows, ceiling = _ceiling()
    fwd = _forward(ceiling)
    recs = [_record(i) for i in range(n)]
    return ceiling, evaluate(with_enrolment(fwd, recs), [_s2_row(r) for r in recs]), fwd, recs


# --- registration --------------------------------------------------------------------


def test_a_forward_reading_registers_only_on_a_ceiling_and_reads_s2_on_the_factorys_cell() -> None:
    reading, rows, ceiling = _ceiling()
    fwd = _forward(ceiling)
    assert fwd.hierarchy == ("S2",) and fwd.pool == () and fwd.pool_rule == POOL_RULE_CALIBRATION
    assert fwd.cell == {**FACTORY_CELL, "builder": BUILDER, "model": MODEL, "provider": PROVIDER}
    assert fwd.promotes == reading.reading_id and fwd.verify()
    # the forward reading shares the ceiling's scope, so the factory's gate reads both at once
    assert (fwd.apparatus, fwd.taxonomy, fwd.posture_class, fwd.checks_arm) == (
        reading.apparatus,
        reading.taxonomy,
        reading.posture_class,
        reading.checks_arm,
    )
    # a cell still reading, or one with a proven standard, has no ceiling to promote
    pending = evaluate(reading, rows[:5])
    assert pending.state != OUTCOME_CEILING
    with pytest.raises(ReadingRefused) as exc:
        _forward(pending)
    assert exc.value.code == REFUSAL_NOT_A_CEILING


def test_a_forward_reading_spends_from_the_ceilings_one_budget() -> None:
    """ADR-0026 item 5: one budget per cell, across every phase — a forward reading spends
    from the ceiling's cell, never a fresh one; a second look.v1 would overspend 5%."""
    reading, _rows, ceiling = _ceiling()
    fwd = _forward(ceiling)
    assert fwd.budget_key == reading.budget_key
    assert budget_spent([reading, fwd], reading.budget_key) == pytest.approx(2 * fwd.spend)
    with pytest.raises(ReadingRefused) as exc:
        register_forward(
            ceiling=ceiling,
            builder=BUILDER,
            model=MODEL,
            provider=PROVIDER,
            actor="op-1",
            existing=[reading, fwd],
            now=FWD_AT,
        )
    assert exc.value.code == REFUSAL_BUDGET_SPENT
    late = register_forward(
        ceiling=ceiling,
        builder=BUILDER,
        model=MODEL,
        provider=PROVIDER,
        actor="op-1",
        existing=[reading, fwd],
        rule=RULE_LOOK_V1_LATE,
        now=FWD_AT,
    )
    assert late.spend == pytest.approx(rule_spend(RULE_LOOK_V1_LATE))


# --- enrolment ------------------------------------------------------------------------


def test_the_pool_is_the_calibration_builds_whose_tests_were_written_after_registration() -> None:
    _reading, _rows, ceiling = _ceiling()
    fwd = _forward(ceiling)
    recs = [
        _record(0, written_at="2026-09-27T11:00:00+00:00"),  # before the registration
        _record(1),
        _record(2, size="S"),  # another cell
        _record(3, capability_class="feature.add"),
        _record(4),
        _record(1, grant="grant-again"),  # the same ticket once
    ]
    assert with_enrolment(fwd, recs).pool == ("T-1", "T-4")
    # enrolment is read, never registered: the id and the registered digest are kept
    enrolled = with_enrolment(fwd, recs)
    assert enrolled.reading_id == fwd.reading_id and enrolled.pool_sha256 == fwd.pool_sha256
    # any other reading passes through unchanged
    _r, _rw, other = _ceiling()
    assert with_enrolment(other.reading, recs) is other.reading


# --- counting ---------------------------------------------------------------------------


def test_one_held_out_pass_reads_look_pending_with_its_n() -> None:
    _reading, _rows, ceiling = _ceiling()
    fwd = _forward(ceiling)
    recs = [_record(i) for i in range(3)]
    out = evaluate(with_enrolment(fwd, recs), [_s2_row(recs[0])])
    arm = out.arms["S2"]
    assert arm.look.state == STATE_LOOK_PENDING and arm.look.counted == 1 and arm.look.clean == 1
    assert arm.look.next_look == 20 and out.state == STATE_LOOK_PENDING
    # the ceiling still speaks for the cell
    assert latest_outcome([ceiling, out]) is ceiling


def test_only_a_held_out_graded_first_attempt_after_registration_counts() -> None:
    _reading, _rows, ceiling = _ceiling()
    fwd = with_enrolment(_forward(ceiling), [_record(i) for i in range(6)])
    r = [_record(i) for i in range(6)]
    rows = [
        _s2_row(r[0], labels=none_labels(WHY_NOT_FIRST)),  # not graded on held-out tests
        _s2_row(r[1], trial="r2"),  # a later attempt
        _s2_row(r[2], created="2026-09-27T11:30:00+00:00"),  # graded before registration
        _s2_row(r[3], labels={**held_out_labels(r[3], RESULT_PASS), "imported": "true"}),
        _s2_row(r[4], labels={"acceptance": "held_out"}),  # no digest: no positive evidence
    ]
    arm = evaluate(fwd, rows).arms["S2"]
    assert [c.outcome for c in arm.commits] == [None] * 6
    assert arm.look.counted == 0


def test_a_held_out_fail_is_a_miss_and_an_instrument_failure_leaves_the_pool() -> None:
    _reading, _rows, ceiling = _ceiling()
    recs = [_record(i) for i in range(5)]
    fwd = with_enrolment(_forward(ceiling), recs)
    rows = [
        _s2_row(recs[0], result=RESULT_PASS),
        _s2_row(recs[1], result=RESULT_FAIL),  # the build passed its own test, not theirs
        _s2_row(recs[2], result=RESULT_ERROR),  # the held-out tests could not be run
        _s2_row(recs[3], builder="editblock"),  # another builder: another cell
        _s2_row(recs[4], clean=False, error="harness: sandbox died"),
    ]
    arm = evaluate(fwd, rows).arms["S2"]
    by = {c.commit: c for c in arm.commits}
    assert by["T-0"].outcome is True and by["T-1"].outcome is False
    assert by["T-2"].left == LEFT_HELD_OUT_ERROR
    assert by["T-3"].left == LEFT_OTHER_CELL
    assert by["T-4"].left == LEFT_HARNESS
    assert arm.look.counted == 2 and arm.look.misses == 1


# --- promotion --------------------------------------------------------------------------


def test_twenty_held_out_passes_promote_the_ceiling_to_an_s2_standard() -> None:
    ceiling, fwd_out, _fwd, _recs = _promoted()
    assert fwd_out.arms["S2"].look.state == STATE_DELIVER
    assert fwd_out.state == OUTCOME_STANDARD and fwd_out.standard == "S2"
    best = latest_outcome([ceiling, fwd_out])
    assert best is fwd_out and not best.ceiling


def test_three_held_out_misses_read_insufficient_and_the_ceiling_stands() -> None:
    _reading, _rows, ceiling = _ceiling()
    recs = [_record(i) for i in range(20)]
    fwd = with_enrolment(_forward(ceiling), recs)
    rows = [_s2_row(r, result=RESULT_FAIL if i < 3 else RESULT_PASS) for i, r in enumerate(recs)]
    out = evaluate(fwd, rows)
    assert out.arms["S2"].look.state == STATE_INSUFFICIENT
    assert latest_outcome([ceiling, out]) is ceiling


def test_more_s3_rows_never_promote_a_ceiling() -> None:
    """``S3`` never certifies: an ``S3``-only reading of 40 clean commits stays a ceiling."""
    pool = commits(40, prefix="s3only")
    reading = register_reading(pool, hierarchy=("S3",))
    out = evaluate(reading, rows_for([True] * 40, pool, arm="S3"))
    assert out.state == OUTCOME_CEILING and out.standard == ""


def test_routing_first_attempts_read_the_same_held_out_rule() -> None:
    """P-690: the ledger's first attempts (the routing reader) and the reading apply the one
    rule the factory writes: a held-out ``fail`` is not clean, an unstamped S2 row is not
    gold-checked."""
    rec = _record(0)
    passed, failed, unstamped = (
        _s2_row(rec, result=RESULT_PASS),
        _s2_row(_record(1), result=RESULT_FAIL),
        _s2_row(_record(2), labels=none_labels(WHY_NOT_FIRST)),
    )
    fa = {f.task_id: f for f in first_attempts([passed, failed, unstamped])}
    assert fa["oracle-T-0"].gold_checked and fa["oracle-T-0"].clean
    assert fa["oracle-T-1"].gold_checked and not fa["oracle-T-1"].clean
    assert not fa["oracle-T-2"].gold_checked
