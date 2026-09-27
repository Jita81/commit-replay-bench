"""The shell's Sign out is found by its exact name in every walkthrough spec.

Playwright matches a role's accessible name as a substring unless ``exact: true`` is given.
Stream U put a "Sign out everywhere" button on every row of Settings › Users; stream A1,
built in parallel, looked for the shell's Sign out by ``{ name: 'Sign out' }``, so on the
merged tree the phone-menu check on ``/settings`` matched four Users-card buttons and failed
in strict mode (docs/PREVENTION.md P-114). A substring locator that happens to match one
element today can match another stream's control tomorrow, or the wrong one.

Navigation
----------
What it is:   A source gate over ``ui/e2e/walkthrough``: the "Sign out" locator is exact.
What it does: Fails on any ``getByRole(..., { name: 'Sign out' ... })`` in a walkthrough file
              that does not also say ``exact: true``, naming the file and line.
How:          Text scan of the TypeScript sources; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/11-screens.spec.ts and ui/e2e/walkthrough/support.ts (the
              locators it holds), ui/src/screens/Settings/UsersCard.tsx ("Sign out
              everywhere", the name that collided), docs/PREVENTION.md (P-114)
Tested by:    (this is a test file)
Touch when:   the shell's Sign out is renamed.
"""

from __future__ import annotations

import re
from pathlib import Path

WALKTHROUGH = Path(__file__).resolve().parent.parent / "ui" / "e2e" / "walkthrough"
SIGN_OUT = re.compile(r"name:\s*'Sign out'")


def test_every_sign_out_locator_is_exact() -> None:
    loose = [
        f"{p.name}:{i}"
        for p in sorted(WALKTHROUGH.glob("*.ts"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if SIGN_OUT.search(line) and "exact: true" not in line
    ]
    assert loose == [], (
        "find the shell's Sign out with exact: true — 'Sign out' also matches "
        f"'Sign out everywhere': {loose}"
    )


def test_the_gate_has_locators_to_check() -> None:
    found = sum(
        len(SIGN_OUT.findall(p.read_text(encoding="utf-8"))) for p in WALKTHROUGH.glob("*.ts")
    )
    assert found >= 2, "no Sign out locator found: has the walkthrough moved?"
