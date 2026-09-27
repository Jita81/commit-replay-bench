"""No walkthrough spec that runs before 06b opens a Baseline — the order 06b stands on.

Spec 06b (stream A2, DL-074) proves the transition of Home's task 6: it finds "Read the
baseline" Incomplete, opens the Baseline screen, which records the read, and finds it
Completed. That holds only while no earlier spec has opened a Baseline: the screen records a
read on every first visit. Stream M, built in parallel, added a Baseline check to spec 05, so
on the merged tree task 6 was already Completed when 06b looked, and the tier-1 walkthrough
failed (docs/PREVENTION.md P-113). The spec's own header named the precondition in prose;
this test makes it a gate.

Navigation
----------
What it is:   A source gate over the order of ``ui/e2e/walkthrough``'s specs.
What it does: Reads every spec file that Playwright runs before ``06b-baseline-read.spec.ts``
              (the files sort by name) and fails when one navigates to ``/results?repo=``,
              naming the file and line; and checks that 06b itself still opens the Baseline,
              so the gate cannot pass because the spec it protects moved.
How:          Text scan of the TypeScript sources; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/06b-baseline-read.spec.ts (the spec whose precondition this
              holds), ui/e2e/walkthrough/05-replay-fake.spec.ts (the spec that broke it),
              ui/src/screens/Results/ResultsPage.tsx (records the read on a visit),
              docs/PREVENTION.md (P-113)
Tested by:    (this is a test file)
Touch when:   the Baseline stops recording a read on a visit, or 06b is renamed or moved.
"""

from __future__ import annotations

from pathlib import Path

WALKTHROUGH = Path(__file__).resolve().parent.parent / "ui" / "e2e" / "walkthrough"
GUARDED = "06b-baseline-read.spec.ts"
OPENS_A_BASELINE = "/results?repo="


def _specs_before_06b() -> list[Path]:
    return [p for p in sorted(WALKTHROUGH.glob("*.spec.ts")) if p.name < GUARDED]


def test_no_spec_before_06b_opens_a_baseline() -> None:
    offenders = [
        f"{p.name}:{i}"
        for p in _specs_before_06b()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if OPENS_A_BASELINE in line and not line.lstrip().startswith(("*", "//"))
    ]
    assert offenders == [], (
        "a spec that runs before 06b opens a Baseline, which records the read 06b must see "
        f"happen — move the check after 06b: {offenders}"
    )


def test_the_guard_still_has_a_spec_to_protect() -> None:
    assert _specs_before_06b(), "no spec sorts before 06b: has the walkthrough moved?"
    text = (WALKTHROUGH / GUARDED).read_text(encoding="utf-8")
    assert OPENS_A_BASELINE in text, "06b no longer opens the Baseline it records"
