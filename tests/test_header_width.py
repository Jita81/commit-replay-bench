"""The module headers stay readable at 100 columns — a ratchet that only moves down.

docs/FILE-HEADER-STANDARD.md says "Wrap at 100 columns", and nothing checked it. On
2026-09-25 (this register's P-012) a mechanical edit that replaced one header sentence with a
longer one joined the rest of the old line onto the new one, three times over, and only a
hand-run width check caught it. This test makes that check permanent: it counts the module
docstring lines over 100 columns across ``src/`` and ``scripts/`` and fails when the count
rises above the recorded baseline. Wrap a line you touch and lower the baseline with it.

Navigation
----------
What it is:   The width ratchet over every module header (the module docstring) in src/ and
              scripts/.
What it does: Counts docstring lines longer than 100 characters, fails when the count exceeds
              ``BASELINE`` (naming every offending line), and fails too when the count has
              fallen below it — so the baseline is lowered in the change that earned it and can
              never drift back up unnoticed.
How:          ``ast.parse`` each file, take the first statement's line span when it is the
              module docstring, count the long lines.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   docs/FILE-HEADER-STANDARD.md (the 100-column rule), scripts/code_map.py (the
              header gate this complements), docs/PREVENTION.md (P-012)
Tested by:    (this is a test file)
Touch when:   you wrapped long header lines — lower ``BASELINE`` to the new count.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 100
#: Module-docstring lines over 100 columns on main when the ratchet was set (2026-09-25).
BASELINE = 24


def long_header_lines(root: Path = ROOT) -> list[str]:
    """``path:line: <n> chars`` for every module-docstring line wider than ``WIDTH``."""
    out: list[str] = []
    files = sorted([*(root / "src").rglob("*.py"), *(root / "scripts").glob("*.py")])
    for path in files:
        text = path.read_text(encoding="utf-8")
        mod = ast.parse(text)
        if not mod.body or ast.get_docstring(mod, clean=False) is None:
            continue
        first = mod.body[0]
        end = first.end_lineno or first.lineno
        for n, line in enumerate(text.splitlines()[first.lineno - 1 : end], start=first.lineno):
            if len(line) > WIDTH:
                out.append(f"{path.relative_to(root)}:{n}: {len(line)} chars")
    return out


def test_module_headers_do_not_grow_wider_than_100_columns() -> None:
    found = long_header_lines()
    assert len(found) <= BASELINE, (
        f"{len(found)} module-docstring lines are wider than {WIDTH} columns (the ratchet allows "
        f"{BASELINE}); wrap the new ones (docs/FILE-HEADER-STANDARD.md):\n" + "\n".join(found)
    )
    assert len(found) == BASELINE, (
        f"only {len(found)} long header lines remain — lower BASELINE to {len(found)} so the "
        "ratchet holds the gain"
    )
