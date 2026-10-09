"""Each onboarding step a person spends time or money on says how much (G-479).

ONBOARDING-A-REPO's Steps 1, 3 and 5 state their minutes and their cost; Step 7 (sign off)
stated neither, so an approver asked to sign could not tell whether it was a minute's work or
an afternoon's, or whether it spent anything. This pins that Step 7 states its time, that it
costs £0 because a sign-off reads rows already kept, and what a re-sign after an apparatus
change costs — and that Steps 1 and 3 keep theirs.

Navigation
----------
What it is:   The guard on the time-and-cost sentences of docs/ONBOARDING-A-REPO.md.
What it does: Cuts the guide into its ``## Step n`` sections and asserts Step 7 names its
              minutes, £0 and the re-sign cost with the step that re-sign waits on; that Step 5
              (read the map) names £0 and about ten minutes, marked as unmeasured (G-447); that
              Step 1 says its 30 minutes is an estimate and where the measured time is shown
              (G-302); and that Steps 1 and 3 still carry theirs in their headings.
How:          A regex split on the level-2 headings; plain substring checks.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0015-signoffs-expire-with-the-apparatus.md (why a re-sign follows a
              re-measurement)
Works with:   docs/ONBOARDING-A-REPO.md (the guide whose step sections it reads),
              docs/dod/journeys/sign-off-a-cell.md (time-cost.17 cites it),
              docs/dod/journeys/read-the-map-and-decide.md (time-cost.14 cites it),
              ui/src/screens/Results/ResultsPage.cost.test.tsx (the About block's twin),
              docs/adr/0015-signoffs-expire-with-the-apparatus.md (why a re-sign follows a
              re-measurement)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a step of the guide gains or loses a cost.
"""

from __future__ import annotations

import re
from pathlib import Path

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "ONBOARDING-A-REPO.md"


def _steps() -> dict[str, tuple[str, str]]:
    text = GUIDE.read_text(encoding="utf-8")
    out: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r"^## (Step (\d+) — [^\n]*)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        out[m.group(2)] = (m.group(1), m.group(3))
    return out


def test_step_7_says_how_long_it_takes_what_it_costs_and_what_a_re_sign_costs() -> None:
    heading, body = _steps()["7"]
    assert heading == "Step 7 — Sign off (approver)"  # the anchor every link uses stays put
    assert "**Time and cost.**" in body
    assert re.search(r"\b30\s+minutes\b|half an hour", body)
    assert "**£0**" in body and "calls no model" in body
    assert "re-sign after an apparatus" in body and "Step 4" in body
    # the minutes are not a measurement, and the sentence says so
    assert "[hypothesis" in body and "no approver's time has been measured" in body


def test_step_5_says_it_costs_nothing_and_how_long_it_takes() -> None:
    """G-447: Step 5 (read the map) states its cost and its minutes like Steps 1, 3 and 7. The
    heading keeps its words — ``step-5--read-the-map-everyone`` is the anchor the Baseline's
    Read more link uses — and the minutes are marked as nobody's measurement."""
    heading, raw = _steps()["5"]
    body = " ".join(raw.split())  # a wrapped line is one sentence to a reader
    assert heading == "Step 5 — Read the map (everyone)"
    assert "**Time and cost.**" in body and "£0" in body
    assert "calls no model" in body and "starts no run" in body
    assert "about ten minutes" in body
    assert "[hypothesis — no reader's time measured]" in body


def test_step_1_says_its_minutes_are_an_estimate_and_where_the_measured_time_is() -> None:
    """G-302: the 30 minutes of Step 1 is the guide's estimate, and the walk's panel shows the
    measured time from registration to the first green probe."""
    heading, raw = _steps()["1"]
    body = " ".join(raw.split())
    assert heading == "Step 1 — Register the repository (developer, 30 minutes)"
    assert "guide's estimate [hypothesis" in body
    assert "How this flows" in body and "first green probe" in body


def test_steps_1_and_3_keep_their_time_and_cost() -> None:
    steps = _steps()
    assert "30 minutes" in steps["1"][0]
    assert "£0" in steps["3"][0]
