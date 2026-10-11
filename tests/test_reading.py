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
              admissions were not read; a legacy reading as before, DL-382), and registration
              refused ``pool_seen`` and ``budget_spent``.
How:          Sealed 2.4 rows from ``tests.fixtures.readings``; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (items 2 to 5)
Works with:   src/crb/core/reading.py (the code under test),
              src/crb/core/ledger.py (the rows a reading counts),
              tests/fixtures/readings.py (sealed rows and registered readings)
Tested by:    this file
Touch when:   never for a new repository; a rule, the counting or the budget changes (an ADR
              amending ADR-0026 first).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import replace

import pytest

from crb.core.ledger import FAILURE_OUTAGE, LABEL_FAILURE_KIND, GradeRow
from crb.core.reading import (
    CELL_ERROR_BUDGET,
    LEFT_HARNESS,
    REFUSAL_BUDGET_SPENT,
    REFUSAL_POOL_SEEN,
    RULE_LOOK_V1,
    RULE_LOOK_V1_LATE,
    RULE_LOOK_V1_STRICT,
    STATE_DELIVER,
    STATE_INSUFFICIENT,
    STATE_LOOK_PENDING,
    STATE_UNDECIDED,
    ReadingRefused,
    arm_reading,
    canonical_cell_key,
    cell_error_budget,
    evaluate,
    look_state,
    p_deliver,
    seed_of,
    seeded_order,
    with_admissions,
)
from fixtures.readings import (
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
    outage outside then an admitted miss counts the miss; and a commit whose only rows are
    outside the campaign is pending."""
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
