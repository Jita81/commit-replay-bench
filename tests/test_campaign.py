"""A campaign's money ceiling as a pure record and tally (G-957): the rule the product keeps.

Navigation
----------
What it is:   The unit suite of ``crb.core.campaign``.
What it does: Pins the record (its id is its hash, an edited ceiling no longer verifies, the
              line is the released pounds at the stored rate and never above the ceiling), the
              tally (spent counts author calls, only queued or running runs are held, headroom
              is $5.00 then the dearest attempt, an ``S1`` run's commits times $0.15 then the
              dearest author call), the stops (a cost not known, an overrun) and the ceiling's
              boundary (admitted at exactly the line, refused a cent over).
How:          ``Campaign`` and ``MemberRun`` built by hand; no store.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md
Works with:   src/crb/core/campaign.py (under test),
              src/crb/server/campaigns.py (builds each ``MemberRun`` from the store),
              tests/test_server_campaigns.py (the same rule through the routes)
Tested by:    tests/test_campaign.py
Touch when:   never for a new repository; the registration's tally or stop rule changes.
"""

from __future__ import annotations

import dataclasses

import pytest

from crb.core.campaign import (
    AUTHOR_CALL_FIRST_USD,
    HEADROOM_FIRST_USD,
    REFUSAL_CEILING,
    REFUSAL_COST_UNKNOWN,
    REFUSAL_OVERRUN,
    Campaign,
    MemberRun,
    planned_commits,
    tally,
)


def _wave3(**kw: object) -> Campaign:
    fields: dict[str, object] = {
        "name": "wave-3",
        "ceiling_gbp": 80.0,
        "released_gbp": 40.0,
        "rate_usd_per_gbp": 1.35,
        "decision": "DECISION 8: stage 1 £40 yes",
        "actor": "op",
        "registered_at": "2026-10-11T00:00:00Z",
    }
    fields.update(kw)
    return Campaign(**fields)  # type: ignore[arg-type]


def test_the_id_is_the_records_hash_and_an_edited_ceiling_no_longer_verifies() -> None:
    c = _wave3()
    assert c.campaign_id.startswith("cmp_") and len(c.campaign_id) == 28
    assert c.verify()
    assert Campaign.from_dict(c.to_dict()) == c
    # the same body hashes to the same id; any other ceiling, rate or release does not
    assert _wave3().campaign_id == c.campaign_id
    assert _wave3(ceiling_gbp=800.0).campaign_id != c.campaign_id
    edited = Campaign.from_dict({**c.to_dict(), "ceiling_gbp": 800.0})
    assert not edited.verify()
    assert not Campaign.from_dict({**c.to_dict(), "rate_usd_per_gbp": 13.5}).verify()


@pytest.mark.parametrize(
    ("ceiling", "released", "rate", "ok"),
    [
        (80, 40, 1.35, True),
        (80, 80, 1.35, True),
        (80, 90, 1.35, False),
        (80, 0, 1.35, False),
        (80, 40, 0, False),
    ],
)
def test_a_record_the_tally_cannot_keep_does_not_verify(
    ceiling: float, released: float, rate: float, ok: bool
) -> None:
    c = _wave3(ceiling_gbp=ceiling, released_gbp=released, rate_usd_per_gbp=rate)
    assert c.verify() is ok


def test_the_line_is_the_released_pounds_at_the_stored_rate_never_above_the_ceiling() -> None:
    c = _wave3()
    assert c.usd(40) == 54.00 and c.usd(80) == 108.00
    assert c.line_gbp() == 40.0
    assert c.line_gbp([80.0]) == 80.0
    assert c.line_gbp([120.0]) == 80.0  # never above the ceiling
    assert c.line_gbp([10.0]) == 40.0  # never below the registration's own release


def test_planned_commits_counts_named_commits_at_most_the_limit() -> None:
    assert planned_commits([], None) is None
    assert planned_commits(["a", "b", "c"], None) == 3
    assert planned_commits([], 5) == 5
    assert planned_commits(["a", "b", "c"], 2) == 2


def test_headroom_is_five_dollars_until_an_attempt_is_priced_then_the_dearest() -> None:
    empty = tally(54.0, [])
    assert empty.headroom(s1=False, commits_left=10) == HEADROOM_FIRST_USD
    priced = tally(54.0, [MemberRun("r1", "succeeded", 5.0, rows_usd=3.0, dearest_row_usd=1.25)])
    assert priced.dearest_attempt_usd == 1.25
    assert priced.headroom(s1=False, commits_left=10) == 1.25


def test_an_s1_runs_headroom_adds_its_commits_times_the_author_call() -> None:
    empty = tally(54.0, [])
    assert empty.headroom(s1=True, commits_left=10) == pytest.approx(
        HEADROOM_FIRST_USD + 10 * AUTHOR_CALL_FIRST_USD
    )
    seen = tally(
        54.0,
        [
            MemberRun(
                "r1",
                "succeeded",
                5.0,
                s1=True,
                commits=2,
                commits_done=2,
                rows_usd=1.0,
                dearest_row_usd=0.5,
                authoring_usd=0.4,
                dearest_author_usd=0.3,
            )
        ],
    )
    assert seen.dearest_author_usd == 0.3
    assert seen.headroom(s1=True, commits_left=4) == pytest.approx(0.5 + 4 * 0.3)


def test_spent_counts_author_calls_and_only_queued_or_running_runs_are_held() -> None:
    runs = [
        # finished: its spend counts, nothing is held for it
        MemberRun("done", "succeeded", 10.0, rows_usd=4.0, dearest_row_usd=2.0),
        # running S1 with 3 of 5 commits left: cap less spent, plus its headroom
        MemberRun(
            "s1",
            "running",
            10.0,
            s1=True,
            commits=5,
            commits_done=2,
            rows_usd=1.0,
            dearest_row_usd=0.5,
            authoring_usd=0.6,
            dearest_author_usd=0.3,
        ),
        MemberRun("queued", "queued", 6.0),
        MemberRun("gone", "cancelled", 50.0),
    ]
    t = tally(54.0, runs)
    assert t.spent_usd == pytest.approx(4.0 + 1.0 + 0.6)
    assert t.authoring_usd == pytest.approx(0.6)
    # held: s1 (10 - 1.6) + 2.0 + 3 * 0.3 ; queued 6 + 2.0 ; finished and cancelled none
    assert t.held_usd == pytest.approx((10 - 1.6) + 2.0 + 0.9 + 6.0 + 2.0)
    assert t.left_usd == pytest.approx(54.0 - t.spent_usd - t.held_usd)


def test_the_ceiling_admits_at_exactly_the_line_and_refuses_a_cent_over() -> None:
    # nothing spent: a run capped at $49.00 with $5.00 headroom fits $54.00 exactly
    t = tally(54.0, [])
    assert t.refusal(cap_usd=49.0, s1=False, commits=0) is None
    refused = t.refusal(cap_usd=49.01, s1=False, commits=0)
    assert refused is not None and refused.code == REFUSAL_CEILING
    assert "nothing was queued" in str(refused)
    assert refused.detail["cap_usd"] == 49.01 and refused.detail["headroom_usd"] == 5.0
    assert refused.detail["line_usd"] == 54.0
    # an S1 run's author headroom counts: 10 commits x $0.15 = $1.50 more
    assert t.refusal(cap_usd=47.5, s1=True, commits=10) is None
    s1 = t.refusal(cap_usd=47.51, s1=True, commits=10)
    assert s1 is not None and s1.code == REFUSAL_CEILING


def test_a_cost_the_tally_cannot_know_stops_the_campaign() -> None:
    for unknown in (
        MemberRun("r1", "succeeded", 5.0, rows_unknown=1),
        MemberRun("r1", "succeeded", 5.0, s1=True, commits=1, authors_unknown=1),
    ):
        refused = tally(54.0, [unknown]).refusal(cap_usd=0.01, s1=False, commits=0)
        assert refused is not None and refused.code == REFUSAL_COST_UNKNOWN
        assert refused.detail == {"run_ids": ["r1"]}


def test_a_run_that_spent_past_its_cap_and_headroom_stops_the_campaign() -> None:
    # dearest attempt $2.00 → headroom $2.00: a $5.00 cap may reach $7.00, not $7.01
    at_edge = MemberRun("r1", "succeeded", 5.0, rows_usd=7.0, dearest_row_usd=2.0)
    assert tally(54.0, [at_edge]).overrun_runs == ()
    over = dataclasses.replace(at_edge, rows_usd=7.01)
    t = tally(54.0, [over])
    assert t.overrun_runs == ("r1",)
    refused = t.refusal(cap_usd=0.01, s1=False, commits=0)
    assert refused is not None and refused.code == REFUSAL_OVERRUN
    # a finished S1 run keeps the author headroom of all its commits
    s1 = MemberRun(
        "s1",
        "succeeded",
        5.0,
        s1=True,
        commits=4,
        commits_done=4,
        rows_usd=6.8,
        dearest_row_usd=2.0,
        authoring_usd=0.4,
        dearest_author_usd=0.1,
    )
    # 7.20 spent passes 5 + 2.00 but not 5 + 2.00 + 4 x 0.10
    assert tally(54.0, [s1]).overrun_runs == ()
