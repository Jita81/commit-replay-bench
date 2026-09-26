"""Every axe scan in the browser walkthrough goes through ``axeScan``, which waits for CSS
transitions to settle first (P-051).

Navigation
----------
What it is:   A source gate over ``ui/e2e/walkthrough``: no spec builds its own ``AxeBuilder``.
What it does: Fails when any walkthrough file other than ``support.ts`` imports or constructs
              ``AxeBuilder``, and when ``support.ts``'s ``axeScan`` stops calling
              ``settleTransitions`` before it analyses. A scan that runs mid-transition reads a
              colour no person sees — the 07 sweep failed on 2026-09-26 on a button half-way
              from outlined to filled (3.05:1) — so the wait is built into the one scan helper
              and this test keeps it the only way in.
How:          Reads the spec sources as text; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/support.ts (``axeScan``, ``settleTransitions``),
              ui/e2e/walkthrough/07-settings-and-a11y.spec.ts and
              ui/e2e/walkthrough/11-screens.spec.ts (the sweeps that call it),
              docs/PREVENTION.md (row P-051)
Tested by:    tests/test_walkthrough_axe_scan.py
Touch when:   the walkthrough's scan helper is renamed or moves out of support.ts.
"""

from __future__ import annotations

import re
from pathlib import Path

WALKTHROUGH = Path(__file__).resolve().parents[1] / "ui" / "e2e" / "walkthrough"


def test_no_walkthrough_spec_builds_its_own_axe_scan() -> None:
    offenders = [
        p.name
        for p in sorted(WALKTHROUGH.glob("*.ts"))
        if p.name != "support.ts" and "AxeBuilder" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"use axeScan from support.ts, not AxeBuilder, in: {offenders}"


def test_the_one_scan_helper_waits_for_transitions_before_it_analyses() -> None:
    src = (WALKTHROUGH / "support.ts").read_text(encoding="utf-8")
    m = re.search(r"export async function axeScan\([^)]*\)[^{]*\{(?P<body>.*?)\n\}", src, re.S)
    assert m, "support.ts no longer exports axeScan"
    body = m.group("body")
    assert "settleTransitions(page)" in body, "axeScan must wait for transitions to settle"
    assert body.index("settleTransitions(page)") < body.index(".analyze()"), (
        "the wait must come before the scan"
    )
    assert "CSSTransition" in src, "settleTransitions must wait on CSS transitions"
