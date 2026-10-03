"""B11 — question planner."""

from collections.abc import Sequence

from mandate.gaps import Gap


def next_question(
    gaps: Sequence[Gap], *, turns_used: int, budget: int, user_themes: frozenset[str] = frozenset()
) -> str | None:
    remaining = budget - turns_used
    if remaining <= 0:
        return None
    eligible = [g for g in gaps if g.reason != "unconfirmed"]
    if remaining <= 2:
        eligible = [g for g in eligible if g.required]
    for gap in eligible:
        if gap.group in user_themes:
            return gap.slot_id
    return eligible[0].slot_id if eligible else None
