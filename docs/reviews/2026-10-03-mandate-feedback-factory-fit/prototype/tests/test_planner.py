"""B11 oracle: question planner. Returns the slot id to ask about next, or None (go to playback).

1. turns_used >= budget -> None.
2. "unconfirmed" gaps are never asked (they are settled at playback) - drop them.
3. If budget - turns_used <= 2 (fatigue), only required gaps are eligible.
4. Among eligible gaps, prefer the first (in the given order) whose group is in user_themes;
   otherwise the first eligible gap. No eligible gap -> None.
The input order is the gap analyser's order and must be respected, never re-sorted.
"""

from mandate.gaps import Gap
from mandate.planner import next_question

G = [
    Gap("net_target", "scale", True, "uncovered"),
    Gap("work_limit", "categories", False, "vague"),
    Gap("criteria_rank", "criteria", False, "uncovered"),
    Gap("gross_targets", "gross_net", True, "unconfirmed"),
]


def test_first_gap_by_default():
    assert next_question(G, turns_used=0, budget=10) == "net_target"


def test_budget_exhausted():
    assert next_question(G, turns_used=10, budget=10) is None
    assert next_question(G, turns_used=11, budget=10) is None


def test_no_gaps():
    assert next_question([], turns_used=0, budget=10) is None


def test_user_theme_preferred():
    q = next_question(G, turns_used=0, budget=10, user_themes=frozenset({"criteria"}))
    assert q == "criteria_rank"


def test_unconfirmed_never_asked():
    only = [Gap("gross_targets", "gross_net", True, "unconfirmed")]
    assert next_question(only, turns_used=0, budget=10) is None
    q = next_question(G, turns_used=0, budget=10, user_themes=frozenset({"gross_net"}))
    assert q == "net_target"


def test_fatigue_only_required():
    q = next_question(G, turns_used=8, budget=10, user_themes=frozenset({"criteria"}))
    assert q == "net_target"


def test_fatigue_no_required_left():
    assert next_question(G[1:], turns_used=9, budget=10) is None


def test_fatigue_boundary():
    assert next_question(G[1:], turns_used=7, budget=10) == "work_limit"


def test_order_respected_not_resorted():
    gaps = [Gap("z", "g1", False, "uncovered"), Gap("a", "g1", False, "uncovered")]
    assert next_question(gaps, turns_used=0, budget=10) == "z"
