"""Every axe scan in the browser walkthrough goes through ``ui/e2e/axe.ts``, which waits for
the page to settle first (P-167).

Navigation
----------
What it is:   A source gate over ``ui/e2e/walkthrough``: no spec builds its own ``AxeBuilder``.
What it does: Fails when any walkthrough file imports or constructs ``AxeBuilder``, when
              ``ui/e2e/axe.ts``'s ``axeViolations`` stops calling ``settleTransitions`` before
              it analyses, and when the settle stops waiting for the network to go idle and for
              a quiet window with no DOM change (the class came back on 2026-09-27 when a
              button began its transition after the wait). A scan that runs mid-transition
              reads a colour no person sees — the 07 sweep failed on 2026-09-26 on a button
              half-way from outlined to filled (3.05:1) — so the wait is built into the one
              scan helper and this test keeps it the only way in. Stream A1 built the wait in
              ``support.ts``; the north-star integration moved it into ``ui/e2e/axe.ts``, the
              helper stream D had made the one path for every browser suite, and pointed these
              checks at it unchanged.
How:          Reads the spec sources as text; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/axe.ts (``axeViolations``, ``settleTransitions``),
              ui/e2e/walkthrough/07-settings-and-a11y.spec.ts and
              ui/e2e/walkthrough/11-screens.spec.ts (the sweeps that call it),
              tests/test_e2e_axe_settles.py (the same helper, across ui/e2e),
              docs/PREVENTION.md (row P-167)
Tested by:    tests/test_walkthrough_axe_scan.py
Touch when:   never for a new repository; the scan helper is renamed or moves out of ui/e2e/axe.ts.
"""

from __future__ import annotations

import re
from pathlib import Path

WALKTHROUGH = Path(__file__).resolve().parents[1] / "ui" / "e2e" / "walkthrough"
HELPER = Path(__file__).resolve().parents[1] / "ui" / "e2e" / "axe.ts"


def test_no_walkthrough_spec_builds_its_own_axe_scan() -> None:
    offenders = [
        p.name
        for p in sorted(WALKTHROUGH.glob("*.ts"))
        if "AxeBuilder" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"use axeViolations from ui/e2e/axe.ts, not AxeBuilder, in: {offenders}"


def test_the_one_scan_helper_waits_for_transitions_before_it_analyses() -> None:
    src = HELPER.read_text(encoding="utf-8")
    m = re.search(
        r"export async function axeViolations\([^)]*\)[^{]*\{(?P<body>.*?)\n\}", src, re.S
    )
    assert m, "ui/e2e/axe.ts no longer exports axeViolations"
    body = m.group("body")
    assert "settleTransitions(page)" in body, "axeViolations must wait for the page to settle"
    assert body.index("settleTransitions(page)") < body.index(".analyze()"), (
        "the wait must come before the scan"
    )
    assert "CSSTransition" in src, "settleTransitions must wait on CSS transitions"


def test_the_settle_waits_for_the_data_and_a_quiet_page_not_only_a_running_transition() -> None:
    # P-167 recurred on 2026-09-27: the settle returned while no transition was running, the
    # walk page's last stage then answered, the Baseline button began its outlined-to-filled
    # transition during the scan and axe read the blend (3.19:1). Waiting for "no transition
    # now" is not enough; the settle must wait for the network to go idle and for a window in
    # which nothing on the page changes.
    src = HELPER.read_text(encoding="utf-8")
    m = re.search(
        r"export async function settleTransitions\([^)]*\)[^{]*\{(?P<body>.*?)\n\}", src, re.S
    )
    assert m, "ui/e2e/axe.ts no longer exports settleTransitions"
    body = m.group("body")
    assert "networkidle" in body, "the settle must wait for the page's data to arrive"
    assert "MutationObserver" in body, "the settle must wait for a window with no DOM change"
    assert "CSSTransition" in body, "the settle must still wait for running transitions"
