"""Stream S's seam — the prevention register behind the scorecard's ``BugRegister``.

Navigation
----------
What it is:   The seam test between ``crb.core.prevention.PreventionRegister`` and stream S's
              ``crb.core.value.BugRegister`` protocol.
What it does: Pins that ``class_of`` accepts a ``GradeRow``, an object carrying one as
              ``.grade`` (S's ``ValueRow``), or a row with only ``failure_kind`` / ``detail`` (a
              family-level class), and returns ``None`` for a working row or an outage; and that
              ``statuses`` gives ``.signature``, ``.repo``, ``.status`` in the scorecard's five
              and ``.lever`` in ``process`` / ``context`` / ``""``.
How:          The ladder from tests/test_prevention_rule.py; small stand-in row objects.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/prevention.py (``PreventionRegister``), tests/test_prevention_rule.py
              (the ladder), tests/prevention_fixtures.py (the rows)
Tested by:    tests/test_prevention_register_seam.py
Touch when:   stream S's protocol changes (the merge adds an equality test of the status
              vocabularies beside these).
"""

from __future__ import annotations

from dataclasses import dataclass

from crb.core.ledger import GradeRow
from crb.core.prevention import STATUSES, PreventionRegister
from prevention_fixtures import NET_SIG, REPO, attempt, task
from test_prevention_rule import _ladder_to_closed


@dataclass(frozen=True)
class _WithGrade:
    grade: GradeRow
    repo: str = REPO


@dataclass(frozen=True)
class _Loose:
    repo: str
    clean: bool
    failure_kind: str
    detail: str = ""


def test_class_of_accepts_a_grade_row_or_a_row_with_grade() -> None:
    reg = PreventionRegister()
    row = attempt(i=0, task_id=task(1), kind="protocol")
    assert reg.class_of(row) == NET_SIG
    assert reg.class_of(_WithGrade(row)) == NET_SIG
    assert reg.class_of(attempt(i=0, task_id=task(1))) is None
    assert reg.class_of(attempt(i=0, task_id=task(1), kind="outage")) is None
    assert reg.class_of(_Loose(REPO, False, "budget", "max_turns")) == "budget:max_turns"
    assert reg.class_of(_Loose(REPO, False, "protocol")) == "protocol:*"
    assert reg.class_of(_Loose(REPO, True, "")) is None
    assert reg.class_of(_Loose(REPO, False, "outage")) is None
    assert reg.source == "crb.prevention.register.v1"


def test_statuses_carry_status_and_lever_in_the_scorecards_vocabulary() -> None:
    loop = _ladder_to_closed()
    reg = PreventionRegister(loop.records(), mechanisms=loop.mech)
    got = reg.statuses(
        [_WithGrade(r) for r in loop.rows] + [_Loose("other", False, "budget", "wall_clock")]
    )
    assert got and all(s.status in STATUSES for s in got)
    assert all(s.lever in ("process", "context", "") for s in got)
    by = {(s.repo, s.signature): s for s in got}
    assert (by[(REPO, NET_SIG)].status, by[(REPO, NET_SIG)].lever) == ("closed", "process")
    assert by[("other", "budget:wall_clock")].status == "open"
