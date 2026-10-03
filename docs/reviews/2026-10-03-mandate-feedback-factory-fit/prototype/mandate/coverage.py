"""B9 — per-slot coverage state machine."""

from enum import Enum


class CoverageState(Enum):
    UNCOVERED = "uncovered"
    MENTIONED = "mentioned"
    SPECIFIC = "specific"
    CONFIRMED = "confirmed"
    DECLINED = "declined"


class InvalidTransition(ValueError):
    pass


def advance(state: CoverageState, event: str) -> CoverageState:
    c = CoverageState
    if event == "mention":
        if state in (c.UNCOVERED, c.DECLINED):
            return c.MENTIONED
        return state
    if event == "specify":
        return state if state is c.CONFIRMED else c.SPECIFIC
    if event == "confirm":
        if state in (c.SPECIFIC, c.CONFIRMED):
            return c.CONFIRMED
        raise InvalidTransition(f"cannot confirm from {state.name}")
    if event == "decline":
        if state is c.CONFIRMED:
            raise InvalidTransition("cannot decline a confirmed slot")
        return c.DECLINED
    if event == "correct":
        if state is c.CONFIRMED:
            return c.SPECIFIC
        raise InvalidTransition(f"cannot correct from {state.name}")
    raise InvalidTransition(f"unknown event {event!r}")


def is_closed(state: CoverageState) -> bool:
    return state in (CoverageState.CONFIRMED, CoverageState.DECLINED)
