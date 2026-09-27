"""Every accessibility scan in the browser suites reads the page after its colours settle.

axe computes contrast from the colours the page shows at that instant. A control whose
colours change with a CSS transition (the Connection screen's "baseline" link turns from
outlined to filled when the last stage finishes, with ``transition-colors``) is read half
way, as a blend that fails WCAG 2.1 AA although neither end state does. Walkthrough spec 07
failed this way twice in a row on 2026-09-27 (docs/PREVENTION.md P-130), and spec 11 had
already met the same class for a fading hint bubble and fixed it only in its own file. So one
helper, ``ui/e2e/axe.ts``, waits for every running CSS transition to finish before it runs
axe, and no spec may build an ``AxeBuilder`` itself.

Navigation
----------
What it is:   The ratchet that routes every axe scan in ui/e2e through the settling helper.
What it does: Fails when a file under ui/e2e other than ui/e2e/axe.ts constructs an
              ``AxeBuilder``, when the helper stops waiting for CSS transitions before it
              analyses, and when a spec that runs axe does not import the helper.
How:          Reads the TypeScript sources as text (no browser): a construction is the
              literal ``new AxeBuilder``; the helper must await ``getAnimations()`` filtered to
              ``CSSTransition`` before ``.analyze()``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/e2e/axe.ts (the helper under test), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
              and ui/e2e/walkthrough/11-screens.spec.ts (the sweeps that met the class),
              docs/PREVENTION.md (P-130)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a spec needs an axe option the helper does not offer (add
              it to the helper, never a second construction).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E2E = ROOT / "ui" / "e2e"
HELPER = E2E / "axe.ts"


def _sources() -> list[Path]:
    return sorted(p for p in E2E.rglob("*.ts") if p.is_file())


def test_no_spec_builds_its_own_axe_scan() -> None:
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in _sources()
        if p != HELPER and "new AxeBuilder" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "run axe through ui/e2e/axe.ts (it waits for CSS transitions to settle), "
        f"never a direct AxeBuilder: {offenders}"
    )


def test_the_helper_waits_for_css_transitions_before_it_analyses() -> None:
    text = HELPER.read_text(encoding="utf-8")
    settle = text.find("getAnimations()")
    analyse = text.find(".analyze()")
    assert settle != -1 and analyse != -1, "the helper must settle transitions, then analyse"
    assert settle < analyse, "the helper must settle transitions BEFORE it analyses"
    assert "CSSTransition" in text, (
        "wait for CSS transitions only: an infinite animation (a spinner) never finishes"
    )
    assert re.search(r"\.finished", text), "wait on each transition's finished promise"


def test_every_spec_that_runs_axe_imports_the_helper() -> None:
    uses = [
        p
        for p in _sources()
        if p != HELPER and "@axe-core/playwright" in p.read_text(encoding="utf-8")
    ]
    assert not uses, (
        "import axe from ui/e2e/axe.ts, never @axe-core/playwright directly: "
        f"{[p.relative_to(ROOT).as_posix() for p in uses]}"
    )
