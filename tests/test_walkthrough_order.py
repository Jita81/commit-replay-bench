"""No walkthrough spec that runs before 06b opens a Baseline — the order 06b stands on.

Spec 06b (stream A2, DL-075) proves the transition of Home's task 6: it finds "Read the
baseline" Incomplete, opens the Baseline screen, which records the read, and finds it
Completed. That holds only while no earlier spec has opened a Baseline: the screen records a
read on every first visit. Stream M, built in parallel, added a Baseline check to spec 05, so
on the merged tree task 6 was already Completed when 06b looked, and the tier-1 walkthrough
failed (docs/PREVENTION.md P-180). The spec's own header named the precondition in prose;
this test makes it a gate.

Navigation
----------
What it is:   A source gate over the order of ``ui/e2e/walkthrough``'s specs.
What it does: Reads every spec file that Playwright runs before ``06b-baseline-read.spec.ts``
              (the files sort by name), and ``support.ts`` whose helpers any of them may call,
              and fails on any way to the Baseline — a path to ``/results`` in any quote style,
              with or without a query (the screen picks the latest repository and records the
              read either way), or a link or button named Baseline — naming the file and line.
              Negative controls pin that each form is caught; and 06b itself must still open
              the Baseline, so the gate cannot pass because the spec it protects moved.
How:          Text scan of the TypeScript sources; no browser, no stack. The spec itself is
              the second belt: 06b asserts task 6 Incomplete before it opens the Baseline.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/06b-baseline-read.spec.ts (the spec whose precondition this
              holds), ui/e2e/walkthrough/05-replay-fake.spec.ts (the spec that broke it),
              ui/src/screens/Results/ResultsPage.tsx (records the read on a visit),
              docs/PREVENTION.md (P-180)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the Baseline stops recording a read on a visit, 06b is
              renamed or moved, or the Baseline gains another way in (a new nav label, a redirect) —
              add its form to ``OPENS_A_BASELINE`` with a negative control.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WALKTHROUGH = Path(__file__).resolve().parent.parent / "ui" / "e2e" / "walkthrough"
GUARDED = "06b-baseline-read.spec.ts"
#: Every way a spec reaches the Baseline: the ``/results`` path in any string (a query or not
#: — ``ResultsPage`` defaults to the latest repository and records the read on any visit), or
#: a control whose accessible name is the nav's "Baseline" (a string or a regex name).
OPENS_A_BASELINE = (
    re.compile(r"""['"`]/results(?:[?/#'"`]|$)"""),
    re.compile(r"""name:\s*(?:['"`]|/\^?)Baseline"""),
    re.compile(r"""getByText\(\s*(?:['"`]|/\^?)Baseline"""),
)


def _opens_a_baseline(line: str) -> bool:
    if line.lstrip().startswith(("*", "//", "/*")):
        return False
    return any(p.search(line) for p in OPENS_A_BASELINE)


def _runs_before_06b() -> list[Path]:
    """The specs Playwright runs before 06b, and the helpers any of them may call."""
    specs = [p for p in sorted(WALKTHROUGH.glob("*.spec.ts")) if p.name < GUARDED]
    return [*specs, WALKTHROUGH / "support.ts"]


def test_no_spec_before_06b_opens_a_baseline() -> None:
    offenders = [
        f"{p.name}:{i}"
        for p in _runs_before_06b()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if _opens_a_baseline(line)
    ]
    assert offenders == [], (
        "a spec that runs before 06b (or a helper it may call) opens a Baseline, which records "
        f"the read 06b must see happen — move the check after 06b: {offenders}"
    )


@pytest.mark.parametrize(
    "line",
    [
        "    await page.goto(`/results?repo=${encodeURIComponent(repo)}`)",
        "    await page.goto('/results')",
        '    await page.goto("/results")',
        "    await page.goto('/results#flow-measure')",
        "    await page.getByRole('link', { name: 'Baseline' }).click()",
        '    await nav.getByRole("link", { name: "Baseline", exact: true }).click()',
        "    await page.getByRole('link', { name: /^Baseline$/ }).click()",
        "    await page.getByText('Baseline').click()",
    ],
)
def test_the_gate_catches_every_way_to_the_baseline(line: str) -> None:
    """Negative controls: each way to the Baseline the gate must refuse (P-180's guard once
    matched only the literal ``/results?repo=``)."""
    assert _opens_a_baseline(line)


@pytest.mark.parametrize(
    "line",
    [
        " * the Baseline's flow card is checked in 06b",
        "    // a later spec opens /results",
        "    await page.goto('/results-archive')",
        "    await expect(page.getByText('Read the baseline')).toBeVisible()",
    ],
)
def test_the_gate_leaves_what_does_not_open_the_baseline(line: str) -> None:
    assert not _opens_a_baseline(line)


def test_the_guard_still_has_a_spec_to_protect() -> None:
    assert len(_runs_before_06b()) > 1, "no spec sorts before 06b: has the walkthrough moved?"
    text = (WALKTHROUGH / GUARDED).read_text(encoding="utf-8")
    assert any(_opens_a_baseline(line) for line in text.splitlines()), (
        "06b no longer opens the Baseline it records"
    )
    assert "Incomplete" in text, "06b no longer checks task 6 Incomplete before the read"
