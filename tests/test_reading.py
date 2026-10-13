"""Registered readings (ADR-0026 items 2 to 5): the look rule, the seeded order, the budget.

Navigation
----------
What it is:   Tests for ``crb.core.reading`` — registration and its refusals, the seeded order,
              first observed attempts graded after registration, the look rule and its exact
              operating characteristic, and the per-cell error budget.
What it does: Reproduces ADR-0026's table from the in-code programme; reads 20 of 20 at the
              first look, 19 of 20 waiting for 30, a third miss as ``insufficient`` and a pool
              that ends before a look as ``undecided``; pins the seeded order's preimage byte
              for byte; shows a later re-run never changes which commits a look reads, a row
              graded before registration never counting, a commit the instrument cannot grade
              leaving the pool before its outcome is read, a re-run never replacing a
              commit's first attempt, an imported row never counting, a campaign-named
              reading reading only rows of runs its campaign admitted, each commit by its
              first admitted attempt, a row of any other run invisible whatever its failure
              kind and a look outside the campaign buying no selection (none when its
              admissions were not read; a legacy reading as before, DL-382), a descriptive
              arm counting only the commits observed among its first n on either attempt
              rule, every commit served with its outcome and row hash, the loop pair and its
              exact McNemar p (P-794), and registration refused ``reading_exists`` (a reading
              already registered, before the pool and the budget are read — P-793),
              ``pool_seen`` and ``budget_spent``, the budget counting each ``reading_id``
              once; and (P-795) an S1 authoring miss of a sealed run read as the arm's miss,
              and a row unsealed but in every other way the arm's read as a ``scope_fault`` on
              both attempt rules, outcome ``None`` and never a miss (VS1-2) — the arm, the
              outcome and the router ``undecided``, nothing
              needed or re-rolled, ``/learn/remeasure``'s ``audit``; and (FZ-2) a later
              hierarchy arm reading ``waiting`` while the arm before it is still being read
              and ``stopped`` once that arm reads insufficient or undecided, neither read
              toward the verdict.
How:         Sealed 2.4 rows from ``tests.fixtures.readings``; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (items 2 to 5)
Works with:   src/crb/core/reading.py (the code under test),
              src/crb/core/ledger.py (the rows a reading counts),
              src/crb/builders/adapter.py and src/crb/core/learn.py (P-795's writer and plan),
              tests/fixtures/readings.py (sealed rows and registered readings)
Tested by:    this file
Touch when:   never for a new repository; a rule, the counting or the budget changes (an ADR
              amending ADR-0026 first).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import Budget, EscalationLadder, Rung
from crb.builders.brief import S1Arm
from crb.builders.container import BuilderContainerSettings
from crb.core import learn
from crb.core.context_arm import BASE_S1, LABEL_CONTEXT_ARM, REPLAY_MODE
from crb.core.execution import LocalExecutor
from crb.core.ledger import FAILURE_OUTAGE, LABEL_FAILURE_KIND, GradeRow
from crb.core.reading import (
    ATTEMPT_RULE_LEGACY,
    ATTEMPT_RULE_RESERVED,
    CELL_ERROR_BUDGET,
    LABEL_CLAIM,
    LABEL_RESERVATION,
    LABEL_TREATMENT,
    LEFT_HARNESS,
    REFUSAL_BUDGET_SPENT,
    REFUSAL_POOL_SEEN,
    RULE_LOOK_V1,
    RULE_LOOK_V1_LATE,
    RULE_LOOK_V1_STRICT,
    SCOPE_UNSEALED,
    STATE_DELIVER,
    STATE_INSUFFICIENT,
    STATE_LOOK_PENDING,
    STATE_UNDECIDED,
    Reading,
    ReadingRefused,
    Reservation,
    arm_reading,
    budget_spent,
    canonical_cell_key,
    cell_error_budget,
    evaluate,
    first_per_id,
    look_state,
    loop_pair,
    mcnemar_p,
    p_deliver,
    seed_of,
    seeded_order,
    verdict_for,
    with_admissions,
    with_reservations,
)
from crb.core.runners.pytest_runner import PytestRunner
from fixtures import pyrepo as pr
from fixtures.readings import (
    AUTHOR,
    BEFORE,
    CELL,
    REPO,
    S1,
    commits,
    register_reading,
    rows_for,
    sealed_row,
)

# --- the look rule --------------------------------------------------------------


def test_the_look_rule_certifies_a_cell_at_0_80_in_2_10_percent_of_cases() -> None:
    """The in-code programme reproduces ADR-0026 items 3 and 5 exactly (no sampling)."""
    assert p_deliver(RULE_LOOK_V1, 0.80) == pytest.approx(0.0210, abs=0.0001)
    assert p_deliver(RULE_LOOK_V1, 0.90) == pytest.approx(0.2869, abs=0.0001)
    assert p_deliver(RULE_LOOK_V1, 0.95) == pytest.approx(0.7233, abs=0.0001)
    assert p_deliver(RULE_LOOK_V1, 0.97) == pytest.approx(0.902, abs=0.001)
    assert p_deliver(RULE_LOOK_V1_STRICT, 0.80) == pytest.approx(0.0122, abs=0.0001)
    assert p_deliver(RULE_LOOK_V1_LATE, 0.80) == pytest.approx(0.0022, abs=0.0001)
    # a perfect builder always delivers at the first look; a hopeless one never does
    assert p_deliver(RULE_LOOK_V1, 1.0) == pytest.approx(1.0)
    assert p_deliver(RULE_LOOK_V1, 0.0) == 0.0


def test_twenty_of_twenty_delivers_at_the_first_look() -> None:
    st = look_state([True] * 20 + [None] * 20, RULE_LOOK_V1)
    assert (st.state, st.counted, st.clean, st.decided_at) == (STATE_DELIVER, 20, 20, 20)


def test_nineteen_of_twenty_waits_for_the_look_at_thirty() -> None:
    outcomes: list[bool | None] = [True] * 19 + [False] + [None] * 20
    st = look_state(outcomes, RULE_LOOK_V1)
    assert st.state == STATE_LOOK_PENDING
    assert (st.next_look, st.needed, st.counted) == (30, 10, 20)
    # and 29 of the first 30 then delivers at that look, never before it
    assert look_state([True] * 19 + [False] + [True] * 9 + [None], RULE_LOOK_V1).state == (
        STATE_LOOK_PENDING
    )
    assert look_state([True] * 19 + [False] + [True] * 10, RULE_LOOK_V1).state == STATE_DELIVER


def test_the_third_miss_reads_insufficient_and_is_never_read_again() -> None:
    outcomes: list[bool | None] = [False, True, False, True, False] + [True] * 35
    st = look_state(outcomes, RULE_LOOK_V1)
    assert (st.state, st.decided_at, st.misses) == (STATE_INSUFFICIENT, 5, 3)
    # later clean commits change nothing: the decision rests on a prefix that cannot move
    assert look_state(outcomes + [True] * 10, RULE_LOOK_V1) == st


def test_a_pool_that_ends_before_a_look_reads_undecided() -> None:
    st = look_state([True] * 15, RULE_LOOK_V1)
    assert (st.state, st.next_look, st.needed) == (STATE_UNDECIDED, 20, 5)
    one_miss = look_state([True] * 19 + [False] + [True] * 5, RULE_LOOK_V1)
    assert (one_miss.state, one_miss.next_look) == (STATE_UNDECIDED, 30)


# --- the seeded order ---------------------------------------------------------------


def test_the_seeded_order_is_adr_0026_item_2s_sha256() -> None:
    """``sha256("crb.reading.v1|" + repo + "|" + canonical cell key + "|" + commit sha)``,
    byte for byte; the canonical cell key is the seven cell fields joined by ``|``."""
    key = canonical_cell_key(CELL)
    assert key == "replay|bug.fix|XS|go|claude_code|claude-sonnet-5|anthropic"
    sha = "0123456789abcdef0123456789abcdef01234567"
    preimage = b"crb.reading.v1|cobra|replay|bug.fix|XS|go|claude_code|claude-sonnet-5|anthropic|"
    assert seed_of("cobra", key, sha) == hashlib.sha256(preimage + sha.encode()).hexdigest()
    pool = commits(30)
    want = sorted(pool, key=lambda c: hashlib.sha256(preimage + c.encode()).hexdigest())
    assert seeded_order("cobra", key, pool) == want
    assert register_reading(pool).pool == tuple(want)


def test_a_harness_rerun_appended_later_does_not_change_which_commits_a_look_reads() -> None:
    reading = register_reading(commits(40))
    first = reading.pool[3]
    rows = rows_for([True] * 20, reading.pool)
    rows[3] = sealed_row(first, clean=False, error="harness: sandbox failed to start")
    before = arm_reading(reading, "S3", rows)
    assert before.look.state == STATE_LOOK_PENDING and before.look.needed == 1
    # the re-run of that commit lands later in the ledger, after other commits' rows
    later = [*rows, *rows_for([True] * 5, reading.pool[20:], arm="S3"), sealed_row(first)]
    after = arm_reading(reading, "S3", later)
    assert after.look.state == STATE_DELIVER
    assert after.counted_commits == reading.pool[:20]


def test_a_row_graded_before_its_reading_was_registered_never_counts() -> None:
    reading = register_reading(commits(40))
    early = rows_for([True] * 20, reading.pool, created=BEFORE)
    st = arm_reading(reading, "S3", early)
    assert st.look.counted == 0 and st.look.state == STATE_LOOK_PENDING and st.look.needed == 20
    # a row stamped the very second of registration does not count either
    same = rows_for([True] * 20, reading.pool, created=reading.registered_at)
    assert arm_reading(reading, "S3", same).look.counted == 0


def test_a_commit_the_instrument_cannot_grade_leaves_the_pool_before_its_outcome_is_read() -> None:
    reading = register_reading(commits(40))
    bad = reading.pool[0]
    harness = [sealed_row(bad, clean=False, error=f"harness: run {i}") for i in range(3)]
    rows = [*harness, *rows_for([True] * 21, reading.pool[1:])]
    got = arm_reading(reading, "S3", rows)
    assert [(c.commit, c.left) for c in got.left] == [(bad, LEFT_HARNESS)]
    assert got.look.state == STATE_DELIVER
    assert got.counted_commits == reading.pool[1:21]
    # the commit stays out: a clean row appended after it left is never read
    late = arm_reading(reading, "S3", [*rows, sealed_row(bad)])
    assert late.counted_commits == got.counted_commits


def test_two_cherry_picks_of_one_change_count_once() -> None:
    """click bug.fix S held two cherry-picks of one change with opposite outcomes: counted by
    commit they are two readings of one change. A reading counts the change once."""
    reading = register_reading(commits(40))
    a, b = reading.pool[0], reading.pool[1]
    rows = [
        sealed_row(a, clean=True, change="patch-1"),
        sealed_row(b, clean=False, change="patch-1"),
        *rows_for([True] * 20, reading.pool[2:]),
    ]
    got = arm_reading(reading, "S3", rows)
    assert [(c.commit, c.left) for c in got.left] == [(b, "same_change")]
    assert got.look.state == STATE_DELIVER and got.look.clean == 20


def test_a_reading_counts_only_rung_r1_in_the_sealed_posture() -> None:
    reading = register_reading(commits(40))
    host = rows_for([True] * 20, reading.pool, posture_class="local/inplace/host-env")
    assert arm_reading(reading, "S3", host).look.counted == 0
    unsealed_builder = rows_for([True] * 20, reading.pool, builder_executor="host")
    assert arm_reading(reading, "S3", unsealed_builder).look.counted == 0
    escalated = rows_for([True] * 20, reading.pool, trial="r2")
    assert arm_reading(reading, "S3", escalated).look.counted == 0


def test_a_reading_counts_no_row_of_another_checks_arm_or_class_set_version() -> None:
    """ADR-0024 and ADR-0026 item 9: a reading is registered on one checks arm and one
    class-set version, and a row graded under another counts nothing toward it — the same
    cell, after registration, sealed, rung ``r1``. Removing either clause of the count once
    passed every test (P-341)."""
    reading = register_reading(commits(40))
    assert reading.checks_arm == "off" and reading.taxonomy == "global/classes@v1"
    same = rows_for([True] * 20, reading.pool)
    assert arm_reading(reading, "S3", same).look.counted == 20
    other_checks = rows_for([True] * 20, reading.pool, labels={"checks": "fmt=1"})
    assert other_checks[0].checks_arm != reading.checks_arm
    assert arm_reading(reading, "S3", other_checks).look.counted == 0
    other_classes = rows_for([True] * 20, reading.pool, labels={"taxonomy": "acme/classes@v2"})
    assert other_classes[0].taxonomy != reading.taxonomy
    assert arm_reading(reading, "S3", other_classes).look.counted == 0


# --- registration --------------------------------------------------------------------


def test_registering_over_commits_already_graded_is_refused_pool_seen() -> None:
    pool = commits(40)
    graded = [sealed_row(pool[5], arm="S3", created=BEFORE)]
    with pytest.raises(ReadingRefused) as exc:
        register_reading(pool, rows=graded)
    assert exc.value.code == REFUSAL_POOL_SEEN and exc.value.detail["commits"] == [pool[5]]
    # graded under an arm the hierarchy does not name, the commit is not seen
    assert register_reading(pool, rows=[sealed_row(pool[5], arm="A0", created=BEFORE)])
    # nor may a twin of a graded change hide in the pool
    twin = [sealed_row("f" * 40, arm="S3", change="patch-7", created=BEFORE)]
    with pytest.raises(ReadingRefused) as twin_exc:
        register_reading(pool, rows=twin, changes={pool[0]: "patch-7"})
    assert twin_exc.value.code == REFUSAL_POOL_SEEN


def test_registering_beyond_the_cells_budget_is_refused_budget_spent() -> None:
    first = register_reading(commits(40, "a"))
    second = register_reading(commits(40, "b"), existing=[first])
    third = register_reading(commits(40, "c"), existing=[first, second], rule=RULE_LOOK_V1_LATE)
    spent = first.spend + second.spend + third.spend
    assert spent == pytest.approx(0.0442, abs=0.0001) and spent <= CELL_ERROR_BUDGET
    with pytest.raises(ReadingRefused) as exc:
        register_reading(commits(40, "d"), existing=[first, second, third])
    assert exc.value.code == REFUSAL_BUDGET_SPENT
    assert exc.value.detail["spent"] == pytest.approx(spent, abs=1e-6)
    # a tighter operator budget (2.5%) holds Phase 1 and one look.v1-late reading only
    with pytest.raises(ReadingRefused):
        register_reading(commits(40, "e"), existing=[first], budget=0.025)
    assert register_reading(
        commits(40, "e"), existing=[first], budget=0.025, rule=RULE_LOOK_V1_LATE
    )


def test_register_refuses_an_id_already_registered_before_budget() -> None:
    """P-793: a registration that is a reading already registered — the same id, or the same
    content under another second or actor — is refused ``reading_exists`` naming the first,
    before ``pool_seen`` and ``budget_spent`` are read: a retry is the reading once, never a
    second spend. Another rule on the same pool is another reading and registers."""
    first = register_reading(commits(40, "a"))
    second = register_reading(commits(40, "b"), existing=[first])
    later = "2026-09-27T10:00:07+00:00"
    graded = rows_for([True] * 3, list(first.pool))
    for retry in ({}, {"now": later}, {"rows": graded}, {"now": later, "rows": graded}):
        with pytest.raises(ReadingRefused) as exc:
            register_reading(commits(40, "a"), existing=[first, second], **retry)  # type: ignore[arg-type]
        assert exc.value.code == "reading_exists", (retry, exc.value.code)
        assert exc.value.detail == {"reading_id": first.reading_id}
    late = register_reading(commits(40, "a"), existing=[first, second], rule=RULE_LOOK_V1_LATE)
    assert late.reading_id != first.reading_id and late.pool_sha256 == first.pool_sha256


def test_the_budget_counts_each_reading_id_once() -> None:
    """P-793: readings read from a store that holds one twice spend it once, in the order
    first registered."""
    first = register_reading(commits(40, "a"))
    second = register_reading(commits(40, "b"), existing=[first])
    spent = budget_spent([first, first, second, first], first.budget_key)
    assert spent == pytest.approx(first.spend + second.spend)
    assert first_per_id([first, second, first, second]) == [first, second]


def test_the_budget_may_be_tightened_by_the_operator_never_loosened() -> None:
    assert cell_error_budget({}) == CELL_ERROR_BUDGET
    assert cell_error_budget({"CRB_READING__CELL_ERROR_BUDGET": "0.025"}) == 0.025
    for bad in ("0.10", "0", "lots"):
        with pytest.raises(ValueError):
            cell_error_budget({"CRB_READING__CELL_ERROR_BUDGET": bad})


def test_a_reading_names_its_full_cell_and_a_valid_hierarchy() -> None:
    pool = commits(40)
    with pytest.raises(ReadingRefused, match="descriptive"):
        register_reading(pool, hierarchy=("A0",))
    with pytest.raises(ReadingRefused, match="ceiling arm"):
        register_reading(pool, hierarchy=("S1@claude-opus-5", "S3"))
    with pytest.raises(ReadingRefused, match="prospectively"):
        register_reading(pool, hierarchy=("S3", "S2"))
    reading = register_reading(pool, descriptive=(("A0", 16), ("A0+L", 16)))
    assert reading.repo == REPO and reading.verify()
    assert reading.arms == ("S3", "S1@claude-opus-5", "A0", "A0+L")


def test_a_first_attempt_graded_with_belt_5_switched_off_leaves_the_pool() -> None:
    """ADR-0025 item 5 inside a reading: switching belt 5 off never helps a cell — the commit
    leaves the pool with its reason, before its outcome is read, and the next one takes its
    place."""
    reading = register_reading(commits(40))
    off = reading.pool[0]
    rows = [
        sealed_row(off, labels={"lint_reason": "disabled_by_config"}),
        *rows_for([True] * 20, reading.pool[1:]),
    ]
    got = arm_reading(reading, "S3", rows)
    assert [(c.commit, c.left) for c in got.left] == [(off, "lint_disabled")]
    assert off not in got.counted_commits and got.look.state == STATE_DELIVER


def test_a_miss_graded_with_belt_5_switched_off_is_still_a_miss() -> None:
    """P-342: a first attempt graded with belt 5 off left the pool whatever its outcome, so a
    MISS whose target test stayed red — nothing to do with the linter — was erased and the
    next commit took its place: switching belt 5 off turned a pending look into ``deliver``.
    Only an attempt belt 5 could have changed (one that passed every other belt) leaves; a
    lint-disabled miss counts as the miss it is."""
    reading = register_reading(commits(40))
    off = reading.pool[0]
    miss = {"lint_reason": "disabled_by_config"}
    rows = [
        sealed_row(off, clean=False, labels=miss, target_green=False),
        *rows_for([True] * 20, reading.pool[1:]),
    ]
    got = arm_reading(reading, "S3", rows)
    assert not got.left and off in got.counted_commits
    assert (got.look.counted, got.look.clean) == (21, 20)
    assert got.look.state != STATE_DELIVER
    on = [sealed_row(off, clean=False, target_green=False), *rows[1:]]
    assert arm_reading(reading, "S3", on).look.state == got.look.state
    # the cell's first attempts read the same rule: the lint-disabled miss routes, a
    # lint-disabled pass does not
    from crb.core.ledger import cell_stats

    stats = cell_stats(rows)
    assert stats.n_tasks_lint_disabled == 1
    assert (stats.n_tasks, stats.task_clean) == (21, 20)
    passed = cell_stats([sealed_row(off, labels=miss), *rows[1:]])
    assert (passed.n_tasks, passed.task_clean) == (20, 20)


def test_a_rerun_of_a_missed_commit_never_replaces_its_first_attempt() -> None:
    """ADR-0026 item 2, product.truth.202: each commit counts once, by its FIRST observed
    attempt. Re-running a missed commit at ``r1`` until it goes green would otherwise turn
    three misses into a delivering cell."""
    reading = register_reading(commits(40))
    first = rows_for([False] * 3 + [True] * 17, reading.pool)
    reruns = [sealed_row(c, clean=True) for c in reading.pool[:3]]
    got = arm_reading(reading, "S3", [*first, *reruns])
    assert [c.outcome for c in got.commits[:3]] == [False] * 3
    assert [c.row_hash for c in got.commits[:3]] == [r.row_hash for r in first[:3]]
    assert (got.look.state, got.look.counted, got.look.clean) == (STATE_INSUFFICIENT, 3, 0)


def test_an_imported_row_never_counts_toward_a_reading() -> None:
    """P-321: a row imported from another ledger is history, whatever its labels say."""
    reading = register_reading(commits(40))
    imported = rows_for([True] * 20, reading.pool, labels={"imported": "true"})
    assert arm_reading(reading, "S3", imported).look.counted == 0
    legacy = rows_for([True] * 20, reading.pool, labels={"source_row_hash": "f" * 64})
    assert arm_reading(reading, "S3", legacy).look.counted == 0


# --- a reading under a campaign (DL-382) ---------------------------------------------------

#: A campaign id, as ``POST /campaigns`` mints one.
CAMPAIGN = "cmp_" + "a" * 24


def test_a_campaign_readings_row_counts_only_when_its_run_was_admitted_under_the_campaign() -> None:
    """DL-382: a reading that names a campaign counts a row only when the run that wrote it was
    admitted under that campaign (a ``campaign.admitted`` event names it). A sealed row of a
    run filed outside the campaign — one posted without the campaign's ``campaign_id`` — never
    counts; the same row from an admitted run does."""
    reading = with_admissions(register_reading(commits(40), campaign_id=CAMPAIGN), {"run-in"})
    inside = rows_for([True] * 20, reading.pool, run_id="run-in")
    outside = rows_for([True] * 20, reading.pool, run_id="run-out")
    assert arm_reading(reading, "S3", inside).look.counted == 20
    assert arm_reading(reading, "S3", outside).look.counted == 0
    assert evaluate(reading, outside).arms["S3"].look.counted == 0
    # the admissions are read, never registered: the id and the record do not move
    assert reading.verify() and "admitted" not in reading.to_dict()


def test_a_campaign_reading_read_without_its_admissions_counts_no_row_and_says_so() -> None:
    """Fail closed: a campaign-named reading evaluated by a reader that never read the
    campaign's admissions (a file workdir, any caller that did not look) counts NONE of the
    rows — never all — and its outcome says the admissions were unread."""
    reading = register_reading(commits(40), campaign_id=CAMPAIGN)
    rows = rows_for([True] * 20, reading.pool, run_id="run-in")
    assert reading.admissions_unread
    assert arm_reading(reading, "S3", rows).look.counted == 0
    unread = evaluate(reading, rows).to_dict()
    assert unread["admissions_unread"] is True and unread["admitted_runs"] is None
    read = evaluate(with_admissions(reading, {"run-in"}), rows).to_dict()
    assert read["admissions_unread"] is False and read["admitted_runs"] == 1
    assert read["arms"][0]["counted"] == 20


def test_a_legacy_reading_under_no_campaign_counts_its_rows_as_before() -> None:
    """A reading that names no campaign counts by its own rule, whatever run wrote the row:
    there is nothing to admit under, so no admissions are needed and none change it."""
    reading = register_reading(commits(40))
    rows = rows_for([True] * 20, reading.pool, run_id="any-run")
    assert not reading.admissions_unread
    assert arm_reading(reading, "S3", rows).look.counted == 20
    assert arm_reading(with_admissions(reading, ()), "S3", rows).look.counted == 20
    legacy = evaluate(reading, rows).to_dict()
    assert legacy["admissions_unread"] is False and legacy["admitted_runs"] is None


def _hashed(rows: list[GradeRow]) -> list[GradeRow]:
    """``rows`` with a distinct ``row_hash`` each (``sealed_row``'s rows are unchained, so
    each one's hash is empty): the hash a commit is read by names the row that decided it."""
    return [
        replace(r, row_hash=hashlib.sha256(f"row-{i}".encode()).hexdigest())
        for i, r in enumerate(rows)
    ]


def test_a_campaign_reading_reads_each_commit_by_its_first_admitted_attempt() -> None:
    """DL-382, option (b): a campaign-named reading reads only rows of runs its campaign
    admitted, so a commit is read by its first ADMITTED attempt. A miss by a run outside the
    campaign, then a clean row by an admitted run, counts clean, decided by the admitted row;
    a clean row outside, then an admitted miss, counts the miss. No commit leaves the pool for
    a run outside it. A legacy reading reads the same rows by each commit's first attempt."""
    reading = with_admissions(register_reading(commits(40), campaign_id=CAMPAIGN), {"run-in"})
    first, second = reading.pool[:2]
    rows = _hashed(
        [
            sealed_row(first, clean=False, run_id="run-out"),
            sealed_row(first, clean=True, run_id="run-in"),
            sealed_row(second, clean=True, run_id="run-out"),
            sealed_row(second, clean=False, run_id="run-in"),
        ]
    )
    arm = arm_reading(reading, "S3", rows)
    assert [(c.outcome, c.left, c.row_hash) for c in arm.commits[:2]] == [
        (True, "", rows[1].row_hash),
        (False, "", rows[3].row_hash),
    ]
    assert (arm.look.counted, arm.look.clean, arm.look.misses) == (2, 1, 1)
    assert not any(c.left for c in arm.commits)
    assert evaluate(reading, rows).to_dict()["arms"][0]["left"] == []
    legacy = arm_reading(register_reading(commits(40)), "S3", rows)
    assert [c.row_hash for c in legacy.commits[:2]] == [rows[0].row_hash, rows[2].row_hash]


def test_a_row_of_an_unadmitted_run_is_invisible_whatever_its_failure_kind() -> None:
    """DL-382: a row of a run the campaign did not admit is not a first attempt, not a
    harness re-run toward ``max_reruns`` and not an outage — the reading never sees it.
    Three harness failures outside then an admitted clean row count clean (inside, they
    would have spent the two re-runs and the commit would have left ``harness``); an
    admitted harness failure, a miss outside, then an admitted clean row count clean; an
    outage outside then an admitted miss counts the miss; a commit whose only rows are
    outside the campaign is pending; and an outage outside never lends its change to its
    commit, so a later commit's admitted miss of that change is read, not left as the same
    change."""
    reading = with_admissions(register_reading(commits(40), campaign_id=CAMPAIGN), {"run-in"})
    first, second, third, fourth = reading.pool[:4]

    def harness(commit: str, run: str) -> GradeRow:
        return sealed_row(commit, clean=False, error="harness: sandbox failed", run_id=run)

    outage = {LABEL_FAILURE_KIND: FAILURE_OUTAGE}
    rows = _hashed(
        [
            *(harness(first, "run-out") for _ in range(3)),
            sealed_row(first, clean=True, run_id="run-in"),
            harness(second, "run-in"),
            sealed_row(second, clean=False, run_id="run-out"),
            sealed_row(second, clean=True, run_id="run-in"),
            sealed_row(third, clean=False, run_id="run-out", labels=outage),
            sealed_row(third, clean=False, run_id="run-in"),
            sealed_row(fourth, clean=False, run_id="run-out"),
            harness(fourth, "run-out"),
        ]
    )
    arm = arm_reading(reading, "S3", rows)
    assert [(c.outcome, c.left, c.row_hash) for c in arm.commits[:4]] == [
        (True, "", rows[3].row_hash),
        (True, "", rows[6].row_hash),
        (False, "", rows[8].row_hash),
        (None, "", ""),
    ]
    assert arm.look.state == STATE_LOOK_PENDING and arm.look.counted == 3
    # the loop skips an outage either way; only its change label could show, and it must
    # not: the commit keeps its own change and the later admitted miss of that change is read
    fifth, sixth = reading.pool[4:6]
    shared = _hashed(
        [
            sealed_row(fifth, clean=False, run_id="run-out", change="chg-a", labels=outage),
            sealed_row(sixth, clean=False, run_id="run-in", change="chg-a"),
        ]
    )
    got = arm_reading(reading, "S3", shared).commits[4:6]
    assert [(c.change, c.outcome, c.left, c.row_hash) for c in got] == [
        (fifth, None, "", ""),
        ("chg-a", False, "", shared[1].row_hash),
    ]
    # the same harness failures by an admitted run spend the re-runs: the commit leaves
    inside = [harness(first, "run-in") for _ in range(3)]
    assert arm_reading(reading, "S3", inside).commits[0].left == LEFT_HARNESS


@pytest.mark.parametrize(
    "look",
    [
        {"posture_class": "docker/copy/unsealed"},
        {"trial": "r2"},
        {"arm": S1},
        {"created": BEFORE},
    ],
    ids=["another-posture-class", "trial-r2", "the-other-arm", "before-registration"],
)
def test_a_look_outside_the_campaign_buys_no_selection(look: dict[str, str]) -> None:
    """DL-382, the round-3 verification's probe B as a regression: a run outside the arm's
    scope looks at every commit's outcome (another posture class, rung ``r2``, the other arm,
    before registration); the honest filing then files every in-scope attempt under the
    campaign, the gamed one files outside it the attempts at the commits the look saw miss.
    The gamed filing never reads better than the honest one: no commit leaves the pool, each
    looked-miss commit stays pending, and the arm waits at ``look_pending``, where the rule
    that let a commit first attempted outside the campaign leave read it ``deliver``."""
    reading = with_admissions(register_reading(commits(40), campaign_id=CAMPAIGN), {"run-in"})
    rng = random.Random(7)
    truth = {c: rng.random() < 0.6 for c in reading.pool}
    looks = [sealed_row(c, clean=truth[c], run_id="run-peek", **look) for c in reading.pool]
    honest = [*looks, *(sealed_row(c, clean=truth[c], run_id="run-in") for c in reading.pool)]
    gamed = [
        *looks,
        *(
            sealed_row(c, clean=truth[c], run_id="run-in" if truth[c] else "run-out")
            for c in reading.pool
        ),
    ]
    fair = arm_reading(reading, "S3", honest)
    assert (fair.look.state, fair.look.counted, fair.look.clean) == (STATE_INSUFFICIENT, 17, 14)
    got = arm_reading(reading, "S3", gamed)
    assert not any(c.left for c in got.commits)
    assert all(c.outcome is None for c in got.commits if not truth[c.commit])
    assert (got.look.state, got.look.counted, got.look.clean) == (STATE_LOOK_PENDING, 2, 2)
    assert got.look.state != STATE_DELIVER


# --- a descriptive arm's counted commits, and every commit served (F3, P-794) --------------

#: The ``Event.id`` of the registration a reserved.v1 reading is loaded beside.
_REG_EVENT = 10


def _registered(attempt_rule: str, **kw: Any) -> Reading:
    """``register_reading`` over 40 commits under ``attempt_rule`` (reserved.v1 re-runs
    nothing and names the budget profile its runs spend on)."""
    if attempt_rule == ATTEMPT_RULE_RESERVED:
        kw = {"attempt_rule": attempt_rule, "budget_profile": "default", "max_reruns": 0, **kw}
    return register_reading(commits(40), **kw)


def _first_attempts(
    reading: Reading, attempts: Mapping[str, Sequence[bool | None]]
) -> tuple[Reading, list[GradeRow]]:
    """``reading`` and one first attempt per arm and pool commit, in the seeded order:
    ``attempts[arm][i]`` is the ``i``-th commit's (``True`` clean, ``False`` a miss, ``None``
    no attempt yet). Under reserved.v1 each attempt is the row its reservation wrote, with
    the reservations loaded on the reading; on the legacy rule it is a plain first row."""
    if not reading.reserved:
        return reading, [
            r for arm, outs in attempts.items() for r in rows_for(outs, reading.pool, arm=arm)
        ]
    reservations: list[Reservation] = []
    rows: list[GradeRow] = []
    for arm, outs in attempts.items():
        for commit, clean in zip(reading.pool, outs, strict=False):
            if clean is None:
                continue
            res = Reservation(
                arm=arm,
                task_id=commit,
                run_id="run-1",
                event_id=f"ev-{arm}-{commit[:8]}",
                event_seq_id=_REG_EVENT + 1 + len(reservations),
                claim=0,
                treatment="treat-1",
                hold_usd=0.5,
                settled=True,
            )
            reservations.append(res)
            stamp = {LABEL_RESERVATION: res.event_id, LABEL_TREATMENT: res.treatment}
            labels = {**stamp, LABEL_CLAIM: str(res.claim)}
            rows.append(sealed_row(commit, clean=clean, arm=arm, run_id=res.run_id, labels=labels))
    return with_reservations(reading, reservations, _REG_EVENT), rows


@pytest.mark.parametrize("attempt_rule", [ATTEMPT_RULE_LEGACY, ATTEMPT_RULE_RESERVED])
def test_a_descriptive_arm_with_a_pending_commit_counts_only_its_observed_commits(
    attempt_rule: str,
) -> None:
    """F3 (the Wave 3 red team), P-794: a descriptive arm tallies the commits observed among
    its first n, so ``counted_commits`` must name exactly those. It named the first
    ``counted`` commits instead: with the 2nd of 16 pending and the other 15 observed, it named
    the pending commit and left out the 16th, which the tally counted — so the commits a loop
    pair is read on were the wrong ones. A commit past the first n is never counted, and a
    hierarchy arm's counted commits stay its contiguous prefix, up to its first pending one."""
    reading = _registered(attempt_rule, descriptive=(("A0", 16),))
    head: list[bool | None] = [True, None, *([True, True, False] * 4), True, True]
    beyond: list[bool | None] = [True] * 4  # observed, but past the arm's fixed count
    reading, rows = _first_attempts(reading, {"A0": head + beyond, "S3": [True, None, True]})
    out = evaluate(reading, rows)
    a0 = out.arms["A0"]
    want = tuple(c for i, c in enumerate(reading.pool[:16]) if i != 1)
    assert a0.descriptive and (a0.look.counted, a0.look.clean, a0.look.misses) == (15, 11, 4)
    assert a0.counted_commits == want
    assert reading.pool[1] not in a0.counted_commits and reading.pool[15] in a0.counted_commits
    served = {a["arm"]: a for a in out.to_dict()["arms"]}
    assert served["A0"]["counted_commits"] == list(want)
    assert verdict_for(out, "A0").counted_commits == want
    # a hierarchy arm reads a contiguous prefix: it stops at its first pending commit
    assert out.arms["S3"].counted_commits == (reading.pool[0],)


def test_arm_to_dict_serves_every_commits_outcome_and_row_hash() -> None:
    """F3, P-794: ``GET /readings`` serves every commit an arm reads, in the seeded order,
    with its outcome, why it left, the row that decided it, the reserved rule's reason and,
    for a scope fault, its kind (``scope``, RT2B-1; ``""`` here) — so the loop pair (the commits observed in both ``A0`` and ``A0+L``) can be computed from
    the API. It served the left commits and the counted ones' shas, never an outcome."""
    reading = register_reading(commits(40), descriptive=(("A0", 16),))
    p = reading.pool
    rows = _hashed(
        [
            sealed_row(p[0]),
            sealed_row(p[1], clean=False),
            sealed_row(p[2], labels={"lint_reason": "disabled_by_config"}),
            sealed_row(p[0], arm="A0"),
        ]
    )
    out = evaluate(reading, rows)
    s3 = out.arms["S3"]
    served = s3.to_dict()["commits"]
    assert served == [c.to_dict() for c in s3.commits] and len(served) == len(p)
    assert served[:4] == [
        {
            "commit": p[0],
            "change": f"change-{p[0]}",
            "outcome": True,
            "left": "",
            "row_hash": rows[0].row_hash,
            "reason": "",
            "scope": "",
        },
        {
            "commit": p[1],
            "change": f"change-{p[1]}",
            "outcome": False,
            "left": "",
            "row_hash": rows[1].row_hash,
            "reason": "",
            "scope": "",
        },
        {
            "commit": p[2],
            "change": f"change-{p[2]}",
            "outcome": None,
            "left": "lint_disabled",
            "row_hash": rows[2].row_hash,
            "reason": "",
            "scope": "",
        },
        {
            "commit": p[3],
            "change": p[3],
            "outcome": None,
            "left": "",
            "row_hash": "",
            "reason": "",
            "scope": "",
        },
    ]
    a0 = {a["arm"]: a for a in out.to_dict()["arms"]}["A0"]["commits"]
    assert (a0[0]["outcome"], a0[0]["row_hash"]) == (True, rows[3].row_hash)
    assert all(c["outcome"] is None and not c["row_hash"] for c in a0[1:])
    # a reserved.v1 arm serves each commit's reason beside its outcome and reserved row
    reserved, attempts = _first_attempts(
        _registered(ATTEMPT_RULE_RESERVED), {"S3": [True, False, None]}
    )
    attempts = _hashed(attempts)
    got = evaluate(reserved, attempts).to_dict()["arms"][0]["commits"]
    assert [(c["outcome"], c["row_hash"], c["reason"]) for c in got[:3]] == [
        (True, attempts[0].row_hash, ""),
        (False, attempts[1].row_hash, "miss"),
        (None, "", "pending"),
    ]


def test_loop_pair_counts_discordant_pairs_and_its_exact_p() -> None:
    """F3, P-794: the loop pair is read on the commits both ``A0`` and ``A0+L`` read among
    each arm's first 16 — ``b`` clean under ``A0+L`` alone, ``c`` under ``A0`` alone — with the
    exact two-sided McNemar p, ``min(1, 2·P(X ≤ min(b, c)))`` for ``X ~ Bin(b+c, ½)``. A commit
    past the first 16 never is a pair; one pending on either arm is read against the loop
    (NEW-1: it was left out, ``c`` 1 here)."""
    reading = register_reading(commits(40), descriptive=(("A0", 16), ("A0+L", 16)))
    t, f, n = True, False, None
    a0: list[bool | None] = [t, f, f, n, t, f, t, *([f] * 9), t]
    a0l: list[bool | None] = [t, t, t, t, f, f, n, *([t] * 9), f]
    rows = [*rows_for(a0, reading.pool, arm="A0"), *rows_for(a0l, reading.pool, arm="A0+L")]
    out = evaluate(reading, rows)
    got = loop_pair(out.arms["A0"], out.arms["A0+L"])
    p = reading.pool
    assert got.pairs == p[:16] and got.pending == (p[3], p[6])
    # p[3] (A0 pending, A0+L clean) reads concordant; p[6] (A0 clean, A0+L pending) reads c
    assert (got.b, got.c) == (11, 2)
    assert got.p == pytest.approx(184 / 8192)  # 2 · (C(13,0) + C(13,1) + C(13,2)) / 2^13
    assert got.to_dict() == {
        "pairs": list(p[:16]),
        "pending": [p[3], p[6]],
        "complete": False,
        "b": 11,
        "c": 2,
        "p": got.p,
    }
    # the exact test, by hand: no discordant pair is no evidence; one side alone halves per pair
    assert mcnemar_p(0, 0) == 1.0 and mcnemar_p(3, 3) == 1.0
    assert mcnemar_p(5, 0) == pytest.approx(0.0625) and mcnemar_p(0, 6) == pytest.approx(0.03125)
    assert mcnemar_p(11, 2) == got.p


@pytest.mark.parametrize("attempt_rule", [ATTEMPT_RULE_LEGACY, ATTEMPT_RULE_RESERVED])
def test_loop_pair_reads_a_commit_pending_on_either_arm_against_the_loop(
    attempt_rule: str,
) -> None:
    """NEW-1 (round 5), P-792: the pair was read on the commits observed in BOTH arms, so a
    commit left pending on one arm was simply not a pair. With ``A0``'s outcomes in hand, an
    ``A0+L`` filed on ``A0``'s misses alone left ``A0``'s clean commits pending on ``A0+L``,
    and ``c`` (clean under ``A0`` alone) was 0 by construction. Each commit both arms read
    among their first ``n`` is now a pair, and one still pending on either arm is read
    against the loop — a pending ``A0`` attempt as clean, a pending ``A0+L`` attempt as a
    miss — and named in ``pending``, so a gap or an early stop can only lower ``b`` and raise
    ``c``; the pair is ``complete`` only when no pair is pending."""
    reading = _registered(attempt_rule, descriptive=(("A0", 2), ("A0+L", 2)))
    p = reading.pool
    # the probe: A0 clean then a miss; A0+L filed on A0's miss alone, which it fixed
    reading_1, rows = _first_attempts(reading, {"A0": [True, False], "A0+L": [None, True]})
    out = evaluate(reading_1, rows)
    got = loop_pair(out.arms["A0"], out.arms["A0+L"])
    assert got.pairs == (p[0], p[1]) and got.pending == (p[0],)
    assert (got.b, got.c) == (1, 1) and not got.complete
    assert got.to_dict() == {
        "pairs": [p[0], p[1]],
        "pending": [p[0]],
        "complete": False,
        "b": 1,
        "c": 1,
        "p": 1.0,
    }
    # every way a pair can be pending: the side still pending reads against the loop
    reading_4 = _registered(attempt_rule, descriptive=(("A0", 4), ("A0+L", 4)))
    q = reading_4.pool
    t, f, n = True, False, None
    reading_4, rows = _first_attempts(reading_4, {"A0": [t, f, n, n], "A0+L": [n, n, t, f]})
    out = evaluate(reading_4, rows)
    got = loop_pair(out.arms["A0"], out.arms["A0+L"])
    assert got.pairs == q[:4] and got.pending == q[:4]
    # t/–: c; f/–: concordant (a miss each); –/t: concordant (clean each); –/f: c
    assert (got.b, got.c) == (0, 2)
    # complete: both arms observed on every pair, and the pair is read as it was observed
    done, rows = _first_attempts(
        _registered(attempt_rule, descriptive=(("A0", 4), ("A0+L", 4))),
        {"A0": [t, f, f, t], "A0+L": [t, t, t, f]},
    )
    out = evaluate(done, rows)
    got = loop_pair(out.arms["A0"], out.arms["A0+L"])
    assert got.complete and got.pending == () and (got.b, got.c) == (2, 1)


# --- a sealed run's row the reading cannot read (P-795) -------------------------------------


class _NoDaemon:
    """Stands in for the builder's container session: no daemon, no overrides."""

    def __init__(self, settings: BuilderContainerSettings, checkout: Any, **kw: Any) -> None:
        self.checkout = checkout

    def __enter__(self) -> _NoDaemon:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def overrides_for(self, builder: str) -> dict[str, Any]:
        return {}


class _NeverBuilds:
    """A sealable builder an ``S1`` authoring failure never reaches."""

    name = "fake"

    def __init__(self, *, model: str, provider: str = "", **cfg: Any) -> None:
        self.model = model
        self.provider = provider

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(self, *_a: Any, **_kw: Any) -> Any:
        raise AssertionError("an S1 authoring failure never reaches the builder")


def _author_fails(_ws: Any, _subject: str, _message: str) -> tuple[str, str]:
    raise RuntimeError("the author fell over")


def test_an_s1_authoring_miss_under_docker_reads_as_a_miss_not_pending(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-795 (the Wave 3 red team on c5b9e5ec): an ``S1`` authoring failure is the arm's miss
    (ADR-0026 item 1, DL-360), and its row is in the reading's cell (the rung's builder, model
    and provider). Under docker it carried no ``builder_executor``, so it read unsealed, the
    reading dropped it and the commit read pending — re-rolled until it was clean. The row the
    adapter's attempt writes is now read: the commit is the miss it is."""
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", _NeverBuilds)
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"fake"}))
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("fake", "m0", "p"),)),
        budget=Budget(),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        config=pyrepo.config,
        container=BuilderContainerSettings(image="crb-builder:test", user="10001:10001"),
        session_factory=_NoDaemon,
        s1=S1Arm(author=_author_fails, author_model=AUTHOR),
    )
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=False)
    try:
        attempt = fn(ws, pyrepo.feat_task(), REPLAY_MODE[BASE_S1], "fake:m0")
    finally:
        ws.remove()
    assert attempt.error.startswith("authoring:") and attempt.labels[LABEL_CONTEXT_ARM] == S1
    cell = {
        **CELL,
        "builder": attempt.builder.name,
        "model": attempt.builder.model,
        "provider": attempt.builder.provider,
    }
    reading = register_reading(commits(40), cell=cell)
    commit = reading.pool[0]
    row = sealed_row(
        commit,
        clean=False,
        arm=S1,
        error=attempt.error,
        cell=cell,
        # what the adapter recorded, never the fixture's sealed default
        builder_executor=attempt.labels.get("builder_executor", ""),
        labels=dict(attempt.labels),
    )
    got = evaluate(reading, [row]).arms[S1]
    assert got.commits[0].outcome is False and not got.commits[0].left
    assert (got.look.counted, got.look.misses) == (1, 1)
    assert got.scope_faults == () and got.unsealed_dropped == 0


@pytest.mark.parametrize("attempt_rule", [ATTEMPT_RULE_LEGACY, ATTEMPT_RULE_RESERVED])
def test_an_unsealed_row_of_an_admitted_run_makes_the_arm_undecided_scope_fault(
    attempt_rule: str,
) -> None:
    """P-795: a row of a run the reading admits, on the arm, the cell and the posture class
    the reading names, but recording no sealed builder, is one the reading cannot read. It was
    dropped in silence, so its commit read pending — re-rolled until a row came back clean, a
    false deliver. Now the arm is ``undecided`` and names the commit (``scope_faults``): never
    pending, never re-rolled, whatever its look says; on either rule the commit reads
    ``(None, "scope_fault")`` — no hit and no miss (VS1-2: under reserved.v1 it read
    ``False``, a miss in the served look). Nothing asks for another attempt."""
    reading, rows = _first_attempts(_registered(attempt_rule), {"S3": [True] * 20})
    faulted = reading.pool[1]
    rows = [
        replace(r, labels={**r.labels, "builder_executor": "host"}) if r.task_id == faulted else r
        for r in rows
    ]
    out = evaluate(reading, rows)
    s3 = out.arms["S3"]
    assert (s3.scope_faults, s3.unsealed_dropped) == ((faulted,), 1)
    assert s3.state == STATE_UNDECIDED and out.state == STATE_UNDECIDED
    assert out.needed == 0 and out.standard == "" and not out.chain
    assert verdict_for(out, "S3").state == STATE_UNDECIDED
    served = {a["arm"]: a for a in out.to_dict()["arms"]}["S3"]
    assert (served["state"], served["scope_faults"], served["unsealed_dropped"]) == (
        STATE_UNDECIDED,
        [faulted],
        1,
    )
    c = s3.commits[1]
    assert (c.outcome, c.reason) == (None, "scope_fault")
    assert (served["misses"], served["counted"]) == (0, 1)  # the look stops at it, no miss
    # which scope fault (RT2B-1 names a second): the row reads unsealed, on either rule
    assert c.scope == SCOPE_UNSEALED == c.to_dict()["scope"]
    # never re-rolled: the plan asks for no attempt on the faulted arm, and says why
    plan = learn.remeasure_plan(rows, readings=(out,), current_apparatus="2.4")
    assert not plan.pending and not plan.up_to_date
    (blocked,) = plan.cannot_clear
    assert (blocked.arm, blocked.state, blocked.next_act) == ("S3", STATE_UNDECIDED, "audit")
    assert faulted in blocked.reason
    # the same rows, every one sealed: the arm reads by its look, as before
    resealed = [replace(r, labels={**r.labels, "builder_executor": "docker"}) for r in rows]
    sealed = evaluate(reading, resealed).arms["S3"]
    assert sealed.scope_faults == () and sealed.state == STATE_DELIVER


# --- the hierarchy: a later arm waits on the arm before it, then stops (FZ-2) ---------------


@pytest.mark.parametrize("attempt_rule", [ATTEMPT_RULE_LEGACY, ATTEMPT_RULE_RESERVED])
def test_a_later_arm_reads_waiting_while_its_blocker_is_still_running(attempt_rule: str) -> None:
    """FZ-2 (the verdict fuzz): every arm after the first one that did not deliver read
    ``stopped``, so ``S1`` read stopped while ``S3`` was still ``look_pending``. REG:32 and
    ADR-0026 stop an arm only once the arm before it has decided against. With ``S1`` 20 of 20
    clean and no ``S3`` row yet, ``S1`` reads ``waiting`` on ``S3`` and keeps its own look
    numbers. It is a label only: the reading, its needed count and the router's verdict all
    read ``S3``'s look, as before. The served word is pinned as the UI keys on it."""
    reading, rows = _first_attempts(_registered(attempt_rule), {S1: [True] * 20})
    out = evaluate(reading, rows)
    s3, s1 = out.arms["S3"], out.arms[S1]
    assert s3.state == STATE_LOOK_PENDING and out.stopped_at == "S3"
    assert (s1.state, s1.stopped_by) == ("waiting", "S3")
    assert (s1.look.state, s1.look.counted, s1.look.clean) == (STATE_DELIVER, 20, 20)
    served = {a["arm"]: a for a in out.to_dict()["arms"]}[S1]
    assert (served["state"], served["stopped_by"], served["look_state"]) == (
        "waiting",
        "S3",
        STATE_DELIVER,
    )
    # never read toward the verdict: the reading waits on S3 and nothing is a standard
    assert (out.state, out.standard, out.chain, out.needed) == (STATE_LOOK_PENDING, "", (), 20)
    v = verdict_for(out, S1)
    assert (v.state, v.blocking, v.needed, v.next_look) == (STATE_LOOK_PENDING, "S3", 20, 20)


@pytest.mark.parametrize("attempt_rule", [ATTEMPT_RULE_LEGACY, ATTEMPT_RULE_RESERVED])
def test_a_later_arm_reads_stopped_once_its_blocker_reads_insufficient(attempt_rule: str) -> None:
    """FZ-2's pin: once the arm before it has decided against, a later arm reads ``stopped``
    — ``S3`` insufficient at its third miss, or ``S3`` undecided because a row could not be
    read (a ``scope_fault``, P-795). ``S1``'s 20 clean commits are never read toward the
    verdict either way: the reading reads ``S3``'s state and names no standard."""
    reading, rows = _first_attempts(_registered(attempt_rule), {"S3": [False] * 3, S1: [True] * 20})
    out = evaluate(reading, rows)
    s1 = out.arms[S1]
    assert out.arms["S3"].state == STATE_INSUFFICIENT
    assert (s1.state, s1.stopped_by, s1.look.state) == ("stopped", "S3", STATE_DELIVER)
    assert {a["arm"]: a for a in out.to_dict()["arms"]}[S1]["state"] == "stopped"
    assert (out.state, out.standard, out.chain) == (STATE_INSUFFICIENT, "", ())
    assert verdict_for(out, S1).state == STATE_INSUFFICIENT
    # S3 undecided by a scope fault (its other 19 commits clean): S1 reads stopped too
    reading, rows = _first_attempts(_registered(attempt_rule), {"S3": [True] * 20, S1: [True] * 20})
    faulted = reading.pool[4]
    rows = [
        replace(r, labels={**r.labels, "builder_executor": "host"})
        if (r.task_id, r.context_arm) == (faulted, "S3")
        else r
        for r in rows
    ]
    out = evaluate(reading, rows)
    assert out.arms["S3"].state == STATE_UNDECIDED and out.state == STATE_UNDECIDED
    assert (out.arms[S1].state, out.arms[S1].stopped_by) == ("stopped", "S3")
    assert verdict_for(out, S1).state == STATE_UNDECIDED
