"""The module headers stay readable at 100 columns — a ratchet that only moves down.

docs/FILE-HEADER-STANDARD.md says "Wrap at 100 columns", and nothing checked it. On
2026-09-25 (this register's P-012) a mechanical edit that replaced one header sentence with a
longer one joined the rest of the old line onto the new one, three times over, and only a
hand-run width check caught it. This test makes that check permanent: it counts the header
lines over 100 columns — module docstrings in ``src/``, ``scripts/`` and ``tests/``, and the
leading ``/** … */`` block of every ``ui/src`` TypeScript file — and fails when a scope's
count rises above its recorded baseline. Wrap a line you touch and lower the baseline with
it. (The first version read ``src/`` and ``scripts/`` only; the value wave added a 119-column
line to a UI header it could not see, and swapped a wrapped line for a new 144-column one
inside the same count — P-012.)

Navigation
----------
What it is:   The width ratchet over every file header: the module docstring in src/,
              scripts/ and tests/, and the leading doc comment in ui/src.
What it does: Counts header lines longer than 100 characters per scope, fails when a count
              exceeds its ``BASELINES`` entry (naming every offending line), and fails too when
              it has fallen below it — so a baseline is lowered in the change that earned it and
              can never drift back up unnoticed.
How:          ``ast.parse`` each Python file, take the first statement's line span when it is
              the module docstring; the first ``/** … */`` block of each .ts/.tsx file.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   docs/FILE-HEADER-STANDARD.md (the 100-column rule), scripts/code_map.py (the
              header gate this complements), docs/PREVENTION.md (P-012)
Tested by:    (this is a test file)
Touch when:   you wrapped long header lines — lower ``BASELINE`` to the new count.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 100
#: Header lines over 100 columns per scope — src/ + scripts/ set on 2026-09-25 (24, one
#: wrapped since); tests/ and ui/src added by the value merge at the count main carried,
#: each one lower after the merge train rewrote one known line in each (integration/next).
BASELINES: dict[str, int] = {"python": 23, "tests": 10, "ui": 54}
#: The same lines by identity (path + a digest of the line), so a new long line cannot
#: hide behind one wrapped elsewhere in the same count (the swap the value wave made).
KNOWN = Path(__file__).parent / "fixtures" / "header_width_known.txt"
_UI_HEADER = re.compile(r"\s*/\*\*.*?\*/", re.S)


def _identity(path: Path, root: Path, line: str) -> str:
    digest = hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:12]
    return f"{path.relative_to(root)}#{digest}"


def _docstring_lines(path: Path, root: Path, *, ids: bool = False) -> list[str]:
    text = path.read_text(encoding="utf-8")
    mod = ast.parse(text)
    if not mod.body or ast.get_docstring(mod, clean=False) is None:
        return []
    first = mod.body[0]
    end = first.end_lineno or first.lineno
    return [
        _identity(path, root, line) if ids else f"{path.relative_to(root)}:{n}: {len(line)} chars"
        for n, line in enumerate(text.splitlines()[first.lineno - 1 : end], start=first.lineno)
        if len(line) > WIDTH
    ]


def _ui_header_lines(path: Path, root: Path, *, ids: bool = False) -> list[str]:
    text = path.read_text(encoding="utf-8")
    m = _UI_HEADER.match(text)
    if m is None:
        return []
    start = text[: m.start()].count("\n") + 1
    return [
        _identity(path, root, line) if ids else f"{path.relative_to(root)}:{n}: {len(line)} chars"
        for n, line in enumerate(m.group(0).lstrip("\n").splitlines(), start=start)
        if len(line) > WIDTH
    ]


def long_header_lines(root: Path = ROOT, scope: str = "python", *, ids: bool = False) -> list[str]:
    """``path:line: <n> chars`` (or ``path#digest`` with ``ids``) for every header line wider
    than ``WIDTH`` in ``scope``."""
    if scope == "ui":
        ui = root / "ui" / "src"
        files = sorted([*ui.rglob("*.ts"), *ui.rglob("*.tsx")])
        return [x for p in files for x in _ui_header_lines(p, root, ids=ids)]
    if scope == "tests":
        files = sorted((root / "tests").rglob("*.py"))
    else:
        files = sorted([*(root / "src").rglob("*.py"), *(root / "scripts").glob("*.py")])
    return [x for p in files for x in _docstring_lines(p, root, ids=ids)]


def test_no_new_long_header_line_hides_behind_a_wrapped_one() -> None:
    """Identity, not only count: every long header line is one already known. Wrap a line
    and delete its entry; a line you lengthen is new, so wrap it."""
    known = set(KNOWN.read_text(encoding="utf-8").split())
    found = {x for scope in BASELINES for x in long_header_lines(scope=scope, ids=True)}
    assert not found - known, "new long header lines — wrap them: " + ", ".join(
        sorted(found - known)
    )
    assert not known - found, (
        "wrapped lines still listed — remove them from "
        + str(KNOWN.relative_to(ROOT))
        + ": "
        + ", ".join(sorted(known - found))
    )


@pytest.mark.parametrize("scope", sorted(BASELINES))
def test_file_headers_do_not_grow_wider_than_100_columns(scope: str) -> None:
    found = long_header_lines(scope=scope)
    baseline = BASELINES[scope]
    assert len(found) <= baseline, (
        f"{len(found)} {scope} header lines are wider than {WIDTH} columns (the ratchet allows "
        f"{baseline}); wrap the new ones (docs/FILE-HEADER-STANDARD.md):\n" + "\n".join(found)
    )
    assert len(found) == baseline, (
        f"only {len(found)} long {scope} header lines remain — lower BASELINES[{scope!r}] to "
        f"{len(found)} so the ratchet holds the gain"
    )


def test_the_ui_scope_reads_the_leading_doc_comment(tmp_path: Path) -> None:
    ui = tmp_path / "ui" / "src"
    ui.mkdir(parents=True)
    (ui / "A.tsx").write_text(f"/**\n * {'w' * 110}\n */\nconst x = '{'y' * 120}'\n")
    (ui / "b.ts").write_text("export const ok = 1\n")
    assert long_header_lines(tmp_path, "ui") == ["ui/src/A.tsx:2: 113 chars"]
