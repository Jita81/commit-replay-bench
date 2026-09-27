"""A role locator whose name is the start of another control's name is exact.

Playwright matches a role's accessible name as a substring unless ``exact: true`` is given.
Stream U put a "Sign out everywhere" button on every row of Settings › Users; stream A1,
built in parallel, looked for the shell's Sign out by ``{ name: 'Sign out' }``, so on the
merged tree the phone-menu check on ``/settings`` matched four Users-card buttons and failed
in strict mode (docs/PREVENTION.md P-114). A substring locator that happens to match one
element today can match another stream's control tomorrow, or the wrong one. The first gate
matched only the literal ``name: 'Sign out'``, so the same regression written with double
quotes or a regex passed; it now reads every quote style and a regex name.

Navigation
----------
What it is:   A source gate over ``ui/e2e/walkthrough``: a locator whose name is a prefix of
              another control's name (``PREFIX_NAMES``) is exact.
What it does: Fails on any ``name:`` locator, in single, double or back quotes or as a regex,
              whose name is one of ``PREFIX_NAMES`` and that is not exact (``exact: true``, or
              a regex anchored ``^…$``), naming the file and line; negative controls pin each
              form; and each longer name must still exist in ``ui/src``, so the table cannot go
              stale. It does not read the walkthrough's other non-exact name locators: a new
              prefix collision is added to ``PREFIX_NAMES`` when it is found.
How:          Text scan of the TypeScript sources; no browser, no stack.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/walkthrough/11-screens.spec.ts and ui/e2e/walkthrough/support.ts (the
              locators it holds), ui/src/screens/Settings/UsersCard.tsx ("Sign out
              everywhere", the name that collided), docs/PREVENTION.md (P-114)
Tested by:    (this is a test file)
Touch when:   the shell's Sign out is renamed, or a control is named with another control's
              name as its start (add the pair to ``PREFIX_NAMES``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WALKTHROUGH = ROOT / "ui" / "e2e" / "walkthrough"
#: A control's accessible name → a longer name another control carries that starts with it.
#: Playwright matches a string name as a substring, so the short one is ambiguous unless exact.
PREFIX_NAMES: dict[str, str] = {"Sign out": "Sign out everywhere"}


def _loose(line: str, name: str) -> bool:
    """``line`` locates ``name`` by a substring match: a quoted name without ``exact: true``,
    or a regex name not anchored at both ends."""
    if line.lstrip().startswith(("*", "//", "/*")):
        return False
    quoted = re.search(r"""name:\s*(['"`])""" + re.escape(name) + r"\1", line)
    if quoted and "exact: true" not in line:
        return True
    regex = re.search(r"name:\s*/(\^?)" + re.escape(name) + r"(\$?)/", line)
    return bool(regex and not (regex.group(1) and regex.group(2)))


def _matches(line: str, name: str) -> bool:
    return bool(
        re.search(r"""name:\s*(['"`])""" + re.escape(name) + r"\1", line)
        or re.search(r"name:\s*/\^?" + re.escape(name) + r"\$?/", line)
    )


def test_every_prefix_name_locator_is_exact() -> None:
    loose = [
        f"{p.name}:{i}: {name!r}"
        for p in sorted(WALKTHROUGH.glob("*.ts"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        for name in PREFIX_NAMES
        if _loose(line, name)
    ]
    assert loose == [], (
        "find these controls with exact: true (or a regex anchored ^…$) — each name is the "
        f"start of another control's name: {loose}"
    )


@pytest.mark.parametrize(
    "line",
    [
        "await page.getByRole('button', { name: 'Sign out' }).click()",
        'await page.getByRole("button", { name: "Sign out" }).click()',
        "await page.getByRole('button', { name: `Sign out` }).click()",
        "await page.getByRole('button', { name: /Sign out/ }).click()",
        "await page.getByRole('button', { name: /^Sign out/ }).click()",
        "await page.getByRole('button', { name: 'Sign out', exact: false }).click()",
    ],
)
def test_the_gate_catches_a_loose_locator_in_any_form(line: str) -> None:
    """Negative controls: the defect P-114 fixed, written every way the gate must refuse."""
    assert _loose(line, "Sign out")


@pytest.mark.parametrize(
    "line",
    [
        "await page.getByRole('button', { name: 'Sign out', exact: true }).click()",
        'await page.getByRole("button", { name: "Sign out", exact: true }).click()',
        "await page.getByRole('button', { name: /^Sign out$/ }).click()",
        "await page.getByRole('button', { name: 'Sign out everywhere' }).click()",
    ],
)
def test_the_gate_leaves_an_exact_locator(line: str) -> None:
    assert not _loose(line, "Sign out")


def test_each_longer_name_still_exists_and_the_gate_has_locators_to_check() -> None:
    ui = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "ui" / "src").rglob("*.tsx"))
    for short, longer in PREFIX_NAMES.items():
        assert longer in ui, f"{longer!r} no longer names a control: drop {short!r} from the table"
    found = sum(
        1
        for p in WALKTHROUGH.glob("*.ts")
        for line in p.read_text(encoding="utf-8").splitlines()
        for name in PREFIX_NAMES
        if _matches(line, name)
    )
    assert found >= 2, "no Sign out locator found: has the walkthrough moved?"
