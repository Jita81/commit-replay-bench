"""B9 oracle: coverage state machine.

Events: mention, specify, confirm, decline, correct. Unknown event -> InvalidTransition.
mention: UNCOVERED/DECLINED -> MENTIONED; otherwise unchanged (never downgrades).
specify: -> SPECIFIC from UNCOVERED/MENTIONED/SPECIFIC/DECLINED; CONFIRMED stays CONFIRMED.
confirm: SPECIFIC -> CONFIRMED; CONFIRMED stays; from any other state -> InvalidTransition.
decline: -> DECLINED from any state except CONFIRMED (CONFIRMED -> InvalidTransition).
correct: CONFIRMED -> SPECIFIC; from any other state -> InvalidTransition.
is_closed: True only for CONFIRMED and DECLINED.
"""

import pytest

from mandate.coverage import CoverageState as C
from mandate.coverage import InvalidTransition, advance, is_closed

OK = [
    (C.UNCOVERED, "mention", C.MENTIONED),
    (C.DECLINED, "mention", C.MENTIONED),
    (C.MENTIONED, "mention", C.MENTIONED),
    (C.SPECIFIC, "mention", C.SPECIFIC),
    (C.CONFIRMED, "mention", C.CONFIRMED),
    (C.UNCOVERED, "specify", C.SPECIFIC),
    (C.MENTIONED, "specify", C.SPECIFIC),
    (C.SPECIFIC, "specify", C.SPECIFIC),
    (C.DECLINED, "specify", C.SPECIFIC),
    (C.CONFIRMED, "specify", C.CONFIRMED),
    (C.SPECIFIC, "confirm", C.CONFIRMED),
    (C.CONFIRMED, "confirm", C.CONFIRMED),
    (C.UNCOVERED, "decline", C.DECLINED),
    (C.MENTIONED, "decline", C.DECLINED),
    (C.SPECIFIC, "decline", C.DECLINED),
    (C.DECLINED, "decline", C.DECLINED),
    (C.CONFIRMED, "correct", C.SPECIFIC),
]

BAD = [
    (C.UNCOVERED, "confirm"),
    (C.MENTIONED, "confirm"),
    (C.DECLINED, "confirm"),
    (C.CONFIRMED, "decline"),
    (C.UNCOVERED, "correct"),
    (C.SPECIFIC, "correct"),
    (C.MENTIONED, "shout"),
]


@pytest.mark.parametrize(("start", "event", "end"), OK)
def test_transitions(start, event, end):
    assert advance(start, event) is end


@pytest.mark.parametrize(("start", "event"), BAD)
def test_invalid(start, event):
    with pytest.raises(InvalidTransition):
        advance(start, event)


def test_closed():
    assert {s for s in C if is_closed(s)} == {C.CONFIRMED, C.DECLINED}
