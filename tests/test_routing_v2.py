"""routing.v2 (ADR-0025 as ADR-0026 amends it): deliver only on a proven standard arm.

Navigation
----------
What it is:   Tests for ``crb.core.routing.route`` under routing.v2, driven through the
              capability map as the product drives it: a registered reading, sealed 2.4 rows,
              the oracle evidence and the controls verdict.
What it does: Shows a cell of many attempts on few commits routing ``calibrate``; an
              unmeasured or thin oracle routing ``calibrate`` — read over the commits the
              reading counted only; only the standard of several delivering certifying arms
              delivering, and a sign-off refused on the others; host-posture rows never
              delivering; the hierarchy stopping at the first arm that does not deliver (an
              ``S1`` standard, an ``S3`` ceiling that licenses nothing, no standard at all);
              every failing clause listed with its next act; a report of another apparatus
              or an incomplete one never passing; and the published bar refusing to relax.
How:          ``build_capability_map`` over one arm's rows with a ``ReadingBook`` of the
              repository's readings; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/core/routing.py (the rule under test),
              src/crb/core/reading.py (the reading each arm is routed on),
              src/crb/core/capability.py (``build_capability_map`` — the product's path),
              tests/fixtures/readings.py (sealed rows and registered readings)
Tested by:    this file
Touch when:   never for a new repository; a clause, its order or a reason code changes (an ADR
              first).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from crb.core import signoff as so
from crb.core.capability import (
    PROJECTION_CELL,
    CapabilityCell,
    ReadingBook,
    build_capability_map,
)
from crb.core.context_arm import rows_for_context_arm
from crb.core.ledger import GradeRow, cell_stats
from crb.core.reading import Reading
from crb.core.routing import (
    DEFAULT_POLICY,
    POLICY_VERSION,
    REASON_CEILING,
    REASON_CONTROLS_UNMEASURED,
    REASON_DELIVER,
    REASON_INSUFFICIENT,
    REASON_LEANER_STANDARD,
    REASON_LOOK_PENDING,
    REASON_ORACLE_THIN,
    REASON_ORACLE_UNMEASURED,
    REASON_POSTURE_UNSEALED,
    REASON_READING_UNREGISTERED,
    ROUTE_CALIBRATE,
    ROUTE_DELIVER,
    ROUTE_HUMAN,
    ControlsVerdict,
    RoutingPolicy,
    route,
)
from fixtures.readings import BEFORE, REPO, S1, commits, register_reading, rows_for, sealed_row

PASSED = ControlsVerdict(
    passed=True, constructible=6, total=7, escapes=0, run_id="ctl-1", apparatus_version="2.4"
)


def cell_of(
    arm: str,
    rows: Sequence[GradeRow],
    readings: Sequence[Reading] = (),
    *,
    oracle: dict[str, float | None] | None = None,
    controls: ControlsVerdict | None = PASSED,
) -> CapabilityCell:
    """The one full cell of ``arm``, routed as the capability map routes it."""
    book = ReadingBook.evaluate(readings, rows)
    arm_rows = rows_for_context_arm(rows, arm)
    scores = oracle if oracle is not None else {r.task_id: 0.9 for r in rows}
    cmap = build_capability_map(
        arm_rows,
        projection=PROJECTION_CELL,
        controls=controls,
        oracle_by_task=scores,
        readings=book,
    )
    assert len(cmap.cells) == 1
    return cmap.cells[0]


def proven(pool_size: int = 40) -> tuple[Reading, list[GradeRow]]:
    """A reading whose S3 and S1 arms both read 20 of the first 20 clean."""
    reading = register_reading(commits(pool_size))
    rows = [
        *rows_for([True] * 20, reading.pool, arm="S3"),
        *rows_for([True] * 20, reading.pool, arm=S1),
    ]
    return reading, rows


# --- the kept tests ---------------------------------------------------------------


def test_a_cell_of_twelve_attempts_on_three_commits_routes_calibrate() -> None:
    three = commits(3)
    rows = [
        sealed_row(c, arm=S1, trial=f"r{k}" if k > 1 else "r1") for c in three for k in (1, 1, 2, 3)
    ]
    assert len(rows) == 12
    stats = cell_stats(rows)
    assert (stats.n, stats.n_tasks, stats.task_clean) == (12, 3, 3)
    unregistered = cell_of(S1, rows)
    assert unregistered.route == ROUTE_CALIBRATE
    assert unregistered.reason_code == REASON_READING_UNREGISTERED
    reading = register_reading([*three, *commits(37, "x")])
    rows = [sealed_row(c, arm=S1) for c in three for _ in range(4)]
    read = cell_of(S1, rows, [reading])
    assert read.route == ROUTE_CALIBRATE and read.decision is not None
    # the hierarchy reads S3 first, and S3 has no attempt yet: 20 commits still needed
    assert read.decision.reason_code == REASON_LOOK_PENDING
    assert read.decision.needed == 20


def test_an_unmeasured_oracle_routes_calibrate() -> None:
    reading, rows = proven()
    assert cell_of(S1, rows, [reading]).route == ROUTE_DELIVER
    none = cell_of(S1, rows, [reading], oracle={})
    assert none.route == ROUTE_CALIBRATE and none.reason_code == REASON_ORACLE_UNMEASURED
    counted = none.verdict.counted_commits if none.verdict else ()
    thin = cell_of(S1, rows, [reading], oracle=dict.fromkeys(counted[:8], 0.95))
    assert thin.route == ROUTE_CALIBRATE and thin.reason_code == REASON_ORACLE_THIN
    assert thin.decision is not None and thin.decision.oracle_scored_tasks == 8
    weak = cell_of(S1, rows, [reading], oracle=dict.fromkeys(counted, 0.5))
    assert weak.route == ROUTE_HUMAN


def test_the_oracle_is_read_over_the_commits_the_reading_counted_only() -> None:
    """product.truth.202: "an oracle strength of at least 0.80 measured on at least half of
    THOSE commits" — the ones the look counted. Scores on rows of the cell graded before the
    registration (outside the counted prefix) never stand in for the counted commits'."""
    reading, rows = proven()
    old = [sealed_row(c, arm=S1, created=BEFORE) for c in commits(30, "old")]
    old_scores: dict[str, float | None] = {r.task_id: 0.6 for r in old}
    unmeasured = cell_of(S1, [*rows, *old], [reading], oracle=old_scores)
    assert unmeasured.route == ROUTE_CALIBRATE
    assert unmeasured.reason_code == REASON_ORACLE_UNMEASURED
    assert unmeasured.oracle is not None and unmeasured.oracle.n_tasks == 20
    counted = unmeasured.verdict.counted_commits if unmeasured.verdict else ()
    thin = cell_of(
        S1, [*rows, *old], [reading], oracle={**old_scores, **dict.fromkeys(counted[:8], 0.95)}
    )
    assert thin.route == ROUTE_CALIBRATE and thin.reason_code == REASON_ORACLE_THIN
    assert thin.decision is not None and thin.decision.oracle_scored_tasks == 8


def test_host_posture_rows_never_deliver() -> None:
    reading = register_reading(commits(40))
    host = {"posture_class": "local/inplace/host-env", "builder_executor": "host"}
    rows = [
        *rows_for([True] * 40, reading.pool, arm="S3", **host),
        *rows_for([True] * 40, reading.pool, arm=S1, **host),
    ]
    cell = cell_of(S1, rows, [reading])
    assert cell.route == ROUTE_CALIBRATE
    assert cell.reason_code == REASON_POSTURE_UNSEALED
    assert cell.decision is not None and cell.decision.counted == 0
    # a sealed tests sandbox with the builder on the host is not the sealed posture either
    half = rows_for([True] * 40, reading.pool, arm=S1, builder_executor="host")
    assert cell_of(S1, [*rows_for([True] * 20, reading.pool), *half], [reading]).route != (
        ROUTE_DELIVER
    )


# --- the hierarchy -----------------------------------------------------------------


def test_the_hierarchy_stops_at_the_first_arm_that_does_not_deliver() -> None:
    # S3 and S1 deliver → the standard is S1, the leanest certifying arm of the chain
    reading, rows = proven()
    s1 = cell_of(S1, rows, [reading])
    s3 = cell_of("S3", rows, [reading])
    assert s1.route == ROUTE_DELIVER and s1.reason_code == REASON_DELIVER
    assert s1.decision is not None and s1.decision.standard == S1
    assert s3.route == ROUTE_CALIBRATE and s3.reason_code == REASON_CEILING
    # S3 delivers and S1 reads insufficient → an S3 ceiling that licenses nothing
    reading = register_reading(commits(40, "k"))
    misses = [False, False, False] + [True] * 17
    rows = [*rows_for([True] * 20, reading.pool), *rows_for(misses, reading.pool, arm=S1)]
    s3 = cell_of("S3", rows, [reading])
    s1 = cell_of(S1, rows, [reading])
    assert s3.route == ROUTE_CALIBRATE and s3.reason_code == REASON_CEILING
    assert s1.route == ROUTE_HUMAN and s1.reason_code == REASON_INSUFFICIENT
    assert s1.decision is not None and s1.decision.standard == ""
    # S3 reads insufficient and S1's rows are perfect → no standard: S1 is never read
    reading = register_reading(commits(40, "m"))
    rows = [*rows_for(misses, reading.pool), *rows_for([True] * 40, reading.pool, arm=S1)]
    s1 = cell_of(S1, rows, [reading])
    assert s1.route == ROUTE_HUMAN and s1.reason_code == REASON_INSUFFICIENT
    assert s1.verdict is not None and s1.verdict.blocking == "S3"
    assert s1.decision is not None and s1.decision.standard == ""


RICHER = f"{S1}+facts@gpt-oss-120b"


def test_only_the_standard_arm_of_several_delivering_arms_routes_deliver() -> None:
    """ADR-0026 item 4, product.truth.202: when two certifying arms both deliver, the cell's
    standard is the LEANER one and only it routes ``deliver``; the richer arm routes
    ``calibrate`` (``leaner_standard``) and a sign-off on it is refused ``not_standard``."""
    reading = register_reading(commits(40, "r"), hierarchy=("S3", RICHER, S1))
    rows = [
        *rows_for([True] * 20, reading.pool),
        *rows_for([True] * 20, reading.pool, arm=RICHER),
        *rows_for([True] * 20, reading.pool, arm=S1),
    ]
    lean = cell_of(S1, rows, [reading])
    rich = cell_of(RICHER, rows, [reading])
    assert lean.route == ROUTE_DELIVER and lean.reason_code == REASON_DELIVER
    assert rich.route == ROUTE_CALIBRATE and rich.reason_code == REASON_LEANER_STANDARD
    assert rich.decision is not None and rich.decision.standard == S1
    record = so.SignoffRecord(
        repo=REPO,
        capability_class="bug.fix",
        size="XS",
        verifier="bob",
        verifier_kind="local",
        attestation=so.Attestation(
            reviewed_task_id="a" * 40,
            reviewed_row_hash="c" * 64,
            statement="I read the accepted diff and it does what the ticket asks.",
        ),
    )
    refused = [r.code for r in so.evaluate_signoff(record, rich, repo=REPO)]
    assert f"{so.REFUSAL_NOT_STANDARD}:leaner_standard" in refused
    assert so.evaluate_signoff(record, lean, repo=REPO) == ()


# --- shortfalls, controls and the published bar --------------------------------------------


def test_every_failing_clause_is_a_shortfall_with_its_next_act() -> None:
    three = commits(3)
    rows = [sealed_row(c, arm=S1) for c in three]
    cell = cell_of(S1, rows, oracle={}, controls=None)
    assert cell.decision is not None
    got = [(s.code, s.next, s.model_money) for s in cell.decision.shortfalls]
    assert got == [
        (REASON_READING_UNREGISTERED, "register", False),
        (REASON_ORACLE_UNMEASURED, "oracle", False),
        (REASON_CONTROLS_UNMEASURED, "controls", False),
    ]
    reading = register_reading([*three, *commits(37, "q")])
    pending = cell_of(S1, rows, [reading])
    assert pending.decision is not None
    first = pending.decision.shortfalls[0]
    assert (first.code, first.next, first.count, first.model_money) == (
        REASON_LOOK_PENDING,
        "replay",
        20,
        True,
    )


def test_a_report_of_another_apparatus_or_a_cancelled_run_never_passes() -> None:
    reading, rows = proven()
    old = ControlsVerdict(passed=True, constructible=6, total=7, escapes=0, apparatus_version="2.3")
    assert cell_of(S1, rows, [reading], controls=old).reason_code == REASON_CONTROLS_UNMEASURED
    cancelled = ControlsVerdict(
        passed=True, constructible=6, total=7, escapes=0, complete=False, apparatus_version="2.4"
    )
    assert (
        cell_of(S1, rows, [reading], controls=cancelled).reason_code == REASON_CONTROLS_UNMEASURED
    )
    failing = ControlsVerdict(
        passed=False, constructible=6, total=7, escapes=0, complete=False, apparatus_version="2.4"
    )
    assert cell_of(S1, rows, [reading], controls=failing).route == ROUTE_HUMAN


def test_the_published_bar_refuses_the_retired_rule_and_any_relaxation() -> None:
    assert DEFAULT_POLICY.version == POLICY_VERSION == "routing.v2"
    with pytest.raises(ValueError, match="retired"):
        RoutingPolicy(version="routing.v1")
    with pytest.raises(ValueError, match="relax"):
        RoutingPolicy(min_oracle_share=0.3, version="local.v1")
    with pytest.raises(ValueError, match="relax"):
        RoutingPolicy(min_oracle_share=0.4)
    with pytest.raises(ValueError, match="looser"):
        RoutingPolicy(min_oracle_strength=0.7)
    assert RoutingPolicy(rule="look.v1-strict").rule == "look.v1-strict"
    assert "20 of the first 20, 29 of the first 30 or 38 of the first 40" in (
        DEFAULT_POLICY.describe()
    )


def test_route_with_nothing_measured_reads_every_absence_as_unmeasured() -> None:
    stats = cell_stats([sealed_row(c, arm=S1) for c in commits(25)])
    d = route(stats)
    assert d.route == ROUTE_CALIBRATE and d.reason_code == REASON_READING_UNREGISTERED
    assert {s.code for s in d.shortfalls} >= {
        REASON_READING_UNREGISTERED,
        REASON_ORACLE_UNMEASURED,
        REASON_CONTROLS_UNMEASURED,
    }
    assert d.policy_version == "routing.v2" and d.controls_policy == "controls-gate.v2"
