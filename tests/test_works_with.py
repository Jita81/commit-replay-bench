"""Every header's "Works with" names three to eight neighbours, each with its reason.

docs/FILE-HEADER-STANDARD.md asks for "three to eight entries, each with WHY in parentheses",
and ``scripts/code_map.py --check`` does not count them, so the value wave added headers with
two entries, with nine, and with bare paths, and every gate stayed green (docs/PREVENTION.md
P-033). This ratchet reads the block in every Python and TypeScript header and fails on any
file that breaks the rule and is not already listed as a known offender — and on a listed file
that has since been fixed, so the list only shrinks.

Navigation
----------
What it is:   The "Works with" ratchet over every file header in src/, scripts/, tests/ and
              ui/src.
What it does: Parses each header's "Works with" block into entries (commas outside
              parentheses), flags a file with fewer than three or more than eight, or with an
              entry that gives no reason in parentheses, and compares the flagged set with
              the known offenders the rule predates.
How:          A text scan of the first 120 lines of each file; the known set is
              ``tests/fixtures/works_with_known.txt``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   docs/FILE-HEADER-STANDARD.md (the rule it holds), scripts/code_map.py (the header
              gate this complements), tests/test_header_width.py (the same ratchet idiom for
              width), docs/PREVENTION.md (P-033, the class it stops)
Tested by:    tests/test_works_with.py
Touch when:   you fix a listed header (delete its line from the known file).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN = Path(__file__).parent / "fixtures" / "works_with_known.txt"
_FIELDS = (
    "What it is:",
    "What it does:",
    "How:",
    "Layer:",
    "ADRs:",
    "Works with:",
    "Tested by:",
    "Touch when:",
)
_PREFIX = re.compile(r"^\s*(?:\*|#|//)?\s?")


def works_with(text: str) -> str | None:
    """The "Works with" block of a header as one line, or ``None`` when there is none."""
    lines = text.splitlines()[:120]
    for i, line in enumerate(lines):
        head = _PREFIX.sub("", line)
        if not head.startswith("Works with:"):
            continue
        out = [head[len("Works with:") :]]
        for nxt in lines[i + 1 :]:
            body = _PREFIX.sub("", nxt)
            if any(body.startswith(f) for f in _FIELDS) or body.strip() in ("", '"""', "*/"):
                break
            out.append(body)
        return " ".join(x.strip() for x in out)
    return None


def entries(block: str) -> list[str]:
    """Split on commas outside parentheses."""
    parts: list[str] = []
    depth, cur = 0, ""
    for ch in block:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def offence(text: str) -> str:
    """Why a header breaks the rule, or ``""``."""
    block = works_with(text)
    if block is None:
        return ""
    es = entries(block)
    why = [] if 3 <= len(es) <= 8 else [f"{len(es)} entries"]
    bare = [e for e in es if "(" not in e]
    if bare:
        why.append("no reason: " + "; ".join(bare))
    return ", ".join(why)


def offenders(root: Path = ROOT) -> dict[str, str]:
    files = [
        *root.glob("src/**/*.py"),
        *root.glob("scripts/*.py"),
        *root.glob("tests/**/*.py"),
        *root.glob("ui/src/**/*.ts"),
        *root.glob("ui/src/**/*.tsx"),
    ]
    out: dict[str, str] = {}
    for p in sorted(files):
        why = offence(p.read_text(encoding="utf-8"))
        if why:
            out[str(p.relative_to(root))] = why
    return out


def test_no_new_header_breaks_the_works_with_rule() -> None:
    known = set(KNOWN.read_text(encoding="utf-8").split())
    found = offenders()
    new = {k: v for k, v in found.items() if k not in known}
    assert not new, "Works with needs three to eight entries, each with its reason:\n" + "\n".join(
        f"{k}: {v}" for k, v in sorted(new.items())
    )
    fixed = sorted(known - set(found))
    assert not fixed, f"fixed headers still listed — remove them from {KNOWN.name}: {fixed}"


def test_the_rule_counts_entries_and_reasons() -> None:
    ok = "Works with:   a.py (x), b.py (y, z), c.py (w)\nTested by:    t.py\n"
    assert offence(ok) == ""
    assert offence("Works with:   a.py (x), b.py (y)\nTested by: t\n") == "2 entries"
    nine = ", ".join(f"f{i}.py (r)" for i in range(9))
    assert offence(f"Works with:   {nine}\nTested by: t\n") == "9 entries"
    bare = " * Works with:   a.ts (x), b.ts, c.ts (z)\n * Tested by: t\n"
    assert offence(bare) == "no reason: b.ts"
    assert offence("no header here\n") == ""
