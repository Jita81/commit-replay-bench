"""Every axe sweep in the live-stack walkthrough reads a settled page — a ratchet.

On 2026-09-26 (docs/PREVENTION.md P-085) the tier-1 walkthrough failed three runs in four on a
colour-contrast violation on `/connect/<repo>`: the Baseline button turns from outlined to
filled when the walk's data lands, it carries ``transition-colors``, and axe read a frame in
the middle of the transition (3.7:1). The page a person sees was fine; the sweep was reading a
moment that does not last. ``settled(page)`` in ``ui/e2e/walkthrough/support.ts`` waits for
every finite transition and animation to finish, and this test fails when a walkthrough spec
runs ``.analyze()`` without calling it first.

Navigation
----------
What it is:   The ratchet over axe sweeps in ui/e2e/walkthrough: each ``.analyze()`` call is
              preceded, within its few lines, by ``await settled(``.
What it does: Finds every ``.analyze()`` in the walkthrough specs and fails on one with no
              ``settled(`` call in the lines just above it, naming the file and line; the two
              specs owned by other streams that still sweep unsettled are listed in
              ``UNSETTLED`` under gap G-988, and the test fails too when one of them is fixed
              and still listed, so the list only shrinks.
How:          A line scan: for each line holding ``.analyze()``, look back ``WINDOW`` lines
              for ``settled(``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/support.ts (``settled`` — the wait itself),
              ui/e2e/walkthrough/07-settings-and-a11y.spec.ts and
              13-recover-an-account.spec.ts (the sweeps that call it), docs/PREVENTION.md
              (P-085, G-988 — the two sweeps still to move)
Tested by:    (this is a test file)
Touch when:   you add an axe sweep to a walkthrough spec (call ``settled`` first), or move
              one of the ``UNSETTLED`` specs onto ``settled`` (remove it from the list).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALKTHROUGH = ROOT / "ui" / "e2e" / "walkthrough"

#: How many lines above ``.analyze()`` the ``settled(`` call may sit.
WINDOW = 3

#: Specs another stream owns whose sweep still reads an unsettled page (G-988).
UNSETTLED = frozenset({"11-screens.spec.ts", "repo-config.spec.ts"})


def _unsettled_sweeps() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(WALKTHROUGH.glob("*.ts")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if ".analyze()" not in line:
                continue
            before = lines[max(0, i - WINDOW) : i + 1]
            if not any("settled(" in b for b in before):
                found.setdefault(path.name, []).append(i + 1)
    return found


def test_the_walkthrough_has_axe_sweeps_to_check() -> None:
    sweeps = sum(
        p.read_text(encoding="utf-8").count(".analyze()") for p in WALKTHROUGH.glob("*.ts")
    )
    assert sweeps >= 4, "the scan found no axe sweeps: has the walkthrough moved?"


def test_every_axe_sweep_waits_for_a_settled_page() -> None:
    unsettled = _unsettled_sweeps()
    new = {name: lines for name, lines in unsettled.items() if name not in UNSETTLED}
    assert not new, (
        "an axe sweep reads the page before its transitions finish — call "
        f"`await settled(page)` (ui/e2e/walkthrough/support.ts) first (P-085): {new}"
    )


def test_the_unsettled_list_only_shrinks() -> None:
    fixed = UNSETTLED - set(_unsettled_sweeps())
    assert not fixed, f"these specs now call settled(): remove them from UNSETTLED — {fixed}"
