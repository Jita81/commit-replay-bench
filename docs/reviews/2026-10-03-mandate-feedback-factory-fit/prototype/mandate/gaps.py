"""B10 — gap analyser."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mandate.coverage import CoverageState
from mandate.schema import Slot

_REASONS = {
    CoverageState.UNCOVERED: "uncovered",
    CoverageState.MENTIONED: "vague",
    CoverageState.SPECIFIC: "unconfirmed",
}
_RANK = {"vague": 0, "uncovered": 1, "unconfirmed": 2}


@dataclass(frozen=True)
class Gap:
    slot_id: str
    group: str
    required: bool
    reason: str  # "vague" | "uncovered" | "unconfirmed"


def find_gaps(slots: Sequence[Slot], coverage: Mapping[str, CoverageState]) -> list[Gap]:
    gaps: list[tuple[tuple[bool, int, int, str], Gap]] = []
    for slot in slots:
        state = coverage.get(slot.id, CoverageState.UNCOVERED)
        reason = _REASONS.get(state)
        if reason is None:
            continue
        key = (not slot.required, slot.priority, _RANK[reason], slot.id)
        gaps.append((key, Gap(slot.id, slot.group, slot.required, reason)))
    gaps.sort(key=lambda item: item[0])
    return [gap for _, gap in gaps]
