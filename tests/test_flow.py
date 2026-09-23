"""The flow fold — lead times, spend and counts, and what it refuses to invent.

Navigation
----------
What it is:   The unit suite of ``crb.core.flow`` — the pure arithmetic behind ``GET /flow``.
What it does: Pins the timestamp parser (second and millisecond precision, ``Z`` and offsets),
              the lead-time reduction (median / min / max, a pair whose end precedes its start
              dropped and counted, an empty set unmeasured with its reason), the spend rule (an
              unknown cost is never counted as zero, and the reading says how many rows were
              unpriced), the per-unit division and the stream registry every reading is keyed by.
How:          Plain function calls over literal timestamps and ``(cost, cost_known)`` pairs; no
              database, no clock, no I/O.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/flow.py (under test — every function here is one of its rules),
              src/crb/server/flow.py (the caller that gathers the pairs this fold reduces),
              tests/test_server_routes_flow.py (the same rules seen through the endpoint),
              docs/dod/streams/measure.md (the MEASURE criterion this arithmetic serves)
Tested by:    tests/test_flow.py
Touch when:   a stream is added to ``STREAM_NAMES``; the unmeasured contract changes (a median
              of an empty set must stay ``None``, never 0).
"""

from __future__ import annotations

import pytest

from crb.core.flow import (
    STREAM_NAMES,
    LeadTime,
    NotCaptured,
    Spend,
    lead_time,
    median,
    parse_ts,
    per_unit,
    spend_of,
)


class TestParseTs:
    def test_second_and_millisecond_precision(self) -> None:
        a = parse_ts("2026-09-01T10:00:00+00:00")
        b = parse_ts("2026-09-01T10:00:30.500+00:00")
        assert a is not None and b is not None
        assert (b - a).total_seconds() == pytest.approx(30.5)

    def test_zulu_suffix_is_utc(self) -> None:
        assert parse_ts("2026-09-01T10:00:00Z") == parse_ts("2026-09-01T10:00:00+00:00")

    def test_a_naive_stamp_is_read_as_utc(self) -> None:
        assert parse_ts("2026-09-01T10:00:00") == parse_ts("2026-09-01T10:00:00+00:00")

    @pytest.mark.parametrize("bad", ["", "   ", "not a time", "2026-13-01T10:00:00+00:00"])
    def test_unparseable_is_none_never_zero(self, bad: str) -> None:
        assert parse_ts(bad) is None


class TestMedian:
    def test_odd_and_even(self) -> None:
        assert median([3.0, 1.0, 2.0]) == 2.0
        assert median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_empty_is_none(self) -> None:
        assert median([]) is None


class TestLeadTime:
    def test_median_min_and_max_over_the_pairs(self) -> None:
        lt = lead_time(
            "registered_to_controls",
            "registered → controls passed",
            [
                ("2026-09-01T10:00:00+00:00", "2026-09-01T10:00:10+00:00"),
                ("2026-09-01T10:00:00+00:00", "2026-09-01T10:01:00+00:00"),
                ("2026-09-01T10:00:00+00:00", "2026-09-01T10:00:20+00:00"),
            ],
        )
        assert lt.n == 3
        assert lt.median_s == 20.0 and lt.min_s == 10.0 and lt.max_s == 60.0
        assert lt.dropped == 0 and lt.reason == ""

    def test_a_pair_whose_end_precedes_its_start_is_dropped_and_counted(self) -> None:
        lt = lead_time(
            "k",
            "a → b",
            [
                ("2026-09-01T10:00:00+00:00", "2026-09-01T09:00:00+00:00"),
                ("2026-09-01T10:00:00+00:00", "2026-09-01T10:00:30+00:00"),
            ],
        )
        assert lt.n == 1 and lt.dropped == 1 and lt.median_s == 30.0

    def test_an_unparseable_stamp_is_dropped_not_guessed(self) -> None:
        lt = lead_time("k", "a → b", [("", "2026-09-01T10:00:00+00:00")])
        assert lt.n == 0 and lt.dropped == 1 and lt.median_s is None

    def test_no_pairs_is_unmeasured_with_its_reason_never_zero(self) -> None:
        lt = lead_time("k", "a → b", [], reason="no repository has reached b yet")
        assert lt.n == 0
        assert lt.median_s is None and lt.min_s is None and lt.max_s is None
        assert lt.reason == "no repository has reached b yet"
        assert lt.to_dict()["median_s"] is None

    def test_a_reason_is_kept_only_while_nothing_is_measured(self) -> None:
        lt = lead_time(
            "k",
            "a → b",
            [("2026-09-01T10:00:00+00:00", "2026-09-01T10:00:30+00:00")],
            reason="nothing has reached b yet",
        )
        assert lt.n == 1 and lt.reason == ""

    def test_to_dict_carries_the_key_the_label_and_the_n(self) -> None:
        d = LeadTime(key="k", label="a → b", n=0).to_dict()
        assert d["key"] == "k" and d["label"] == "a → b" and d["n"] == 0


class TestSpend:
    def test_an_unknown_cost_is_never_counted_as_zero(self) -> None:
        s = spend_of([(0.010, True), (0.020, True), (5.0, False)])
        assert s.usd == pytest.approx(0.030)
        assert s.rows_priced == 2 and s.rows_unpriced == 1

    def test_a_real_zero_is_counted(self) -> None:
        s = spend_of([(0.0, True)])
        assert s.usd == 0.0 and s.rows_priced == 1 and s.rows_unpriced == 0

    def test_no_priced_row_is_unmeasured_not_zero(self) -> None:
        s = spend_of([(1.0, False), (2.0, False)])
        assert s.usd is None and s.rows_priced == 0 and s.rows_unpriced == 2
        assert s.to_dict()["usd"] is None

    def test_no_rows_at_all_is_unmeasured(self) -> None:
        assert spend_of([]) == Spend(usd=None, rows_priced=0, rows_unpriced=0)


class TestPerUnit:
    def test_divides_a_known_spend_by_the_units(self) -> None:
        assert per_unit(Spend(usd=1.0, rows_priced=4, rows_unpriced=0), 4) == pytest.approx(0.25)

    def test_no_units_or_no_known_spend_is_none(self) -> None:
        assert per_unit(Spend(usd=1.0, rows_priced=4, rows_unpriced=0), 0) is None
        assert per_unit(Spend(usd=None, rows_priced=0, rows_unpriced=3), 4) is None


class TestNotCaptured:
    def test_a_figure_nobody_measured_names_its_gap(self) -> None:
        nc = NotCaptured(
            figure="reviewer minutes", why="POST /reviews takes no minutes", gap="G-557"
        )
        assert nc.to_dict() == {
            "figure": "reviewer minutes",
            "why": "POST /reviews takes no minutes",
            "gap": "G-557",
        }


class TestStreams:
    def test_every_stream_the_definition_of_done_names_has_a_name_here(self) -> None:
        assert set(STREAM_NAMES) == {
            "connect-and-prove",
            "measure",
            "decide-and-license",
            "manufacture-and-deliver",
            "learn",
            "run-the-platform",
        }
