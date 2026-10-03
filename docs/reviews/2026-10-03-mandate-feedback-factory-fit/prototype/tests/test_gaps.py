"""B10 oracle: gap analyser.

A slot missing from `coverage` counts as UNCOVERED. Closed slots (CONFIRMED, DECLINED) are not
gaps. reason: UNCOVERED -> "uncovered", MENTIONED -> "vague", SPECIFIC -> "unconfirmed".
Order: required slots first; then priority ascending; then reason rank vague < uncovered <
unconfirmed (follow up what the person raised before opening new ground); then slot id.
Coverage keys that name no slot are ignored.
"""

from mandate.coverage import CoverageState as C
from mandate.gaps import Gap, find_gaps
from mandate.schema import Slot

SLOTS = [
    Slot("net_target", "scale", 1, required=True),
    Slot("gross_targets", "gross_net", 2),
    Slot("work_limit", "categories", 2),
    Slot("student_limit", "categories", 3),
    Slot("criteria_rank", "criteria", 1),
    Slot("entrench", "implementation", 4),
]


def ids(gaps):
    return [g.slot_id for g in gaps]


def test_empty_coverage_all_uncovered_in_order():
    gaps = find_gaps(SLOTS, {})
    assert ids(gaps) == [
        "net_target",
        "criteria_rank",
        "gross_targets",
        "work_limit",
        "student_limit",
        "entrench",
    ]
    assert {g.reason for g in gaps} == {"uncovered"}


def test_gap_fields():
    g = find_gaps(SLOTS, {"net_target": C.MENTIONED})[0]
    assert g == Gap("net_target", "scale", True, "vague")


def test_closed_slots_excluded():
    cov = {s.id: C.CONFIRMED for s in SLOTS}
    cov["entrench"] = C.DECLINED
    assert find_gaps(SLOTS, cov) == []


def test_reason_rank_breaks_priority_ties():
    cov = {
        "net_target": C.CONFIRMED,
        "criteria_rank": C.CONFIRMED,
        "gross_targets": C.SPECIFIC,
        "work_limit": C.MENTIONED,
    }
    gaps = find_gaps(SLOTS, cov)
    assert ids(gaps) == ["work_limit", "gross_targets", "student_limit", "entrench"]
    assert [g.reason for g in gaps] == ["vague", "unconfirmed", "uncovered", "uncovered"]


def test_slot_id_breaks_full_ties():
    slots = [Slot("b", "g", 1), Slot("a", "g", 1)]
    assert ids(find_gaps(slots, {})) == ["a", "b"]


def test_unknown_coverage_keys_ignored():
    assert ids(find_gaps([Slot("a", "g", 1)], {"zzz": C.MENTIONED})) == ["a"]
