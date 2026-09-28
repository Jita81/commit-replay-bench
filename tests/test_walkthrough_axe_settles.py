"""Every axe sweep in the live-stack walkthrough reads a settled page — a ratchet.

On 2026-09-26 (docs/PREVENTION.md P-152) the tier-1 walkthrough failed three runs in four on a
colour-contrast violation on `/connect/<repo>`: the Baseline button turns from outlined to
filled when the walk's data lands, it carries ``transition-colors``, and axe read a frame in
the middle of the transition (3.7:1). The page a person sees was fine; the sweep was reading a
moment that does not last. Stream D met the same class (P-130) and gave the browser suites one
helper, ``ui/e2e/axe.ts``, whose ``axeViolations`` settles the page and then runs axe; the
north-star integration moved every walkthrough sweep onto it, so this test now holds the
walkthrough's sweeps to that helper.

Navigation
----------
What it is:   The ratchet over axe sweeps in ui/e2e/walkthrough: each sweep is a call of the
              settling helper, and every ``.analyze()`` under ui/e2e is preceded, within its
              few lines, by a settle.
What it does: Counts the walkthrough's sweeps (calls of ``axeViolations(`` or ``axeScan(``) so
              a scan that finds none fails; fails on any ``.analyze()`` under ui/e2e with no
              ``settleTransitions(`` or ``settled(`` call in the lines just above it, naming the
              file and line. G-988 is closed: spec 11 and repo-config
              sweep through the helper since stream D's change.
How:          A line scan: for each line holding ``.analyze()``, look back ``WINDOW`` lines
              for a settle call.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/axe.ts (``settleTransitions`` and ``axeViolations`` — the wait and the
              sweep), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts and
              13-recover-an-account.spec.ts (sweeps that call it), tests/test_e2e_axe_settles.py
              (no spec builds its own AxeBuilder), docs/PREVENTION.md (P-152, P-130)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the axe helper is renamed or moves.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E2E = ROOT / "ui" / "e2e"
WALKTHROUGH = E2E / "walkthrough"

#: How many lines above ``.analyze()`` the settle call may sit.
WINDOW = 3
#: A sweep in a walkthrough spec: a call of the settling helper.
SWEEP = re.compile(r"\b(axeViolations|axeScan)\(")
SETTLE = ("settleTransitions(", "settled(")


def _unsettled_analyses() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(E2E.rglob("*.ts")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if ".analyze()" not in line or line.lstrip().startswith(("*", "//")):
                continue  # a comment names the call; it does not make one
            before = lines[max(0, i - WINDOW) : i + 1]
            if not any(s in b for b in before for s in SETTLE):
                found.setdefault(path.relative_to(ROOT).as_posix(), []).append(i + 1)
    return found


def test_the_walkthrough_has_axe_sweeps_to_check() -> None:
    sweeps = sum(
        len(SWEEP.findall(p.read_text(encoding="utf-8")))
        for p in WALKTHROUGH.glob("*.ts")
        if p.name != "support.ts"
    )
    assert sweeps >= 4, "the scan found no axe sweeps: has the walkthrough moved?"


def test_every_axe_sweep_waits_for_a_settled_page() -> None:
    unsettled = _unsettled_analyses()
    assert not unsettled, (
        "an axe sweep reads the page before its transitions finish — run it through "
        f"ui/e2e/axe.ts, which settles first (P-152, P-130): {unsettled}"
    )
