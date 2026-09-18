#!/usr/bin/env python3
"""The contents page, generated from every file's header — and the gate that keeps them honest.

Every source file carries a ``Navigation`` block at the end of its module docstring (Python)
or leading ``/** … */`` comment (TypeScript) — the standard is ``docs/FILE-HEADER-STANDARD.md``.
This script reads those blocks from every file under ``src/``, ``tests/``, ``ui/src/``,
``ui/e2e/``, ``scripts/`` and ``deploy/`` (Python, TypeScript, shell), validates them, and
writes ``docs/CODE-MAP.md``: one table per package — file, what it is, tested by, touch when —
with every path rendered as a link.

    python scripts/code_map.py            # rewrite docs/CODE-MAP.md
    python scripts/code_map.py --check    # CI: every file has a valid block AND the map is current

``--check`` fails on: a file with no block; a missing required key; a key out of order; a path
in ``Layer``/``ADRs``/``Works with``/``Tested by``/``Touch when``/``Claims`` that does not exist
in the repository (anchors are stripped before the check); a ``Tested by`` that is blank;
a ``docs/CODE-MAP.md`` that differs from what the headers generate. Files listed in
``EXEMPT`` (an explicit path → reason map; today only Vite's generated ambient types) are
skipped and listed at the end of the map so the exemption is visible. There is no size- or
name-based exemption: a thin ``__init__.py`` needs a block like every other file.

Navigation
----------
What it is:   The code-map generator and header gate (stdlib only; runs in CI's ``code-map`` job).
What it does: Parses every source file's Navigation block, validates keys, order and links,
              writes docs/CODE-MAP.md, and in --check mode exits non-zero on any defect or drift.
How:          Walk the source roots → extract the docstring / leading comment per language →
              parse ``Key: value`` lines (continuations indented) → resolve every path against
              the repository → render Markdown tables grouped by top-level package.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/FILE-HEADER-STANDARD.md (the format it enforces), docs/CODE-MAP.md (its
              output), .github/workflows/ci.yml (the code-map job that runs --check)
Tested by:    tests/test_code_map.py
Touch when:   a new source root or language is added; a key is added to the standard (update
              REQUIRED_KEYS, the standard and every header together).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "CODE-MAP.md"
SOURCE_ROOTS: tuple[str, ...] = ("src", "tests", "ui/src", "ui/e2e", "scripts", "deploy", "macos")
SUFFIXES: tuple[str, ...] = (".py", ".ts", ".tsx", ".sh")
SKIP_DIRS: frozenset[str] = frozenset({"node_modules", "__pycache__", "dist", ".venv"})
#: Files that legitimately carry no block (say why in the map).
EXEMPT: dict[str, str] = {
    "ui/src/vite-env.d.ts": "Vite's generated ambient types",
}
REQUIRED_KEYS: tuple[str, ...] = (
    "What it is",
    "What it does",
    "How",
    "Layer",
    "ADRs",
    "Works with",
    "Tested by",
    "Touch when",
)
OPTIONAL_KEYS: tuple[str, ...] = ("Claims",)
KEYS: tuple[str, ...] = REQUIRED_KEYS + OPTIONAL_KEYS
LINK_KEYS: tuple[str, ...] = ("Layer", "ADRs", "Works with", "Tested by", "Touch when", "Claims")
_PATH_RE = re.compile(r"(?<![\w/.-])((?:src|tests|ui|docs|deploy|scripts|macos|\.github)/[\w./-]+)")
_KEY_RE = re.compile(r"^(" + "|".join(re.escape(k) for k in KEYS) + r"):\s*(.*)$")


@dataclass
class Header:
    path: str
    summary: str
    fields: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------


def _leading_comment(text: str, suffix: str) -> str | None:
    """The module docstring (Python) or the leading block comment (TS/TSX/sh)."""
    if suffix == ".py":
        stripped = text.lstrip()
        if stripped.startswith("#!"):
            stripped = stripped.split("\n", 1)[1].lstrip() if "\n" in stripped else ""
        # skip `from __future__` never precedes the docstring in this repo; encoding comments may
        while stripped.startswith("#"):
            stripped = stripped.split("\n", 1)[1].lstrip() if "\n" in stripped else ""
        for quote in ('"""', "'''"):
            if stripped.startswith(quote):
                end = stripped.find(quote, 3)
                return stripped[3:end] if end > 0 else None
        return None
    if suffix in (".ts", ".tsx"):
        stripped = text.lstrip()
        if not stripped.startswith("/**"):
            return None
        end = stripped.find("*/")
        body = stripped[3:end] if end > 0 else ""
        return "\n".join(re.sub(r"^\s*\*\s?", "", ln) for ln in body.splitlines())
    if suffix == ".sh":
        lines = []
        for ln in text.splitlines():
            if ln.startswith("#!"):
                continue
            if ln.startswith("#"):
                lines.append(ln[1:].lstrip() if ln.startswith("# ") else ln[1:])
            elif ln.strip() == "":
                if lines:
                    break
            else:
                break
        return "\n".join(lines) if lines else None
    return None


def parse_block(comment: str) -> tuple[str, dict[str, str], list[str]]:
    """``(summary, fields, problems)`` from a docstring/comment body."""
    lines = comment.strip("\n").splitlines()
    summary = lines[0].strip() if lines else ""
    problems: list[str] = []
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "Navigation")
    except StopIteration:
        return summary, {}, ["no Navigation block"]
    fields: dict[str, str] = {}
    order: list[str] = []
    current: str | None = None
    for ln in lines[start + 1 :]:
        if ln.strip().startswith("---"):
            continue
        m = _KEY_RE.match(ln.strip())
        if m:
            current = m.group(1)
            if current in fields:
                problems.append(f"duplicate key {current!r}")
            fields[current] = m.group(2).strip()
            order.append(current)
        elif current and ln.strip():
            fields[current] = (fields[current] + " " + ln.strip()).strip()
        elif not ln.strip() and current:
            continue
    for key in REQUIRED_KEYS:
        if key not in fields:
            problems.append(f"missing key {key!r}")
        elif not fields[key]:
            problems.append(f"empty key {key!r}")
    expected = [k for k in KEYS if k in fields]
    if order != expected:
        problems.append(f"keys out of order: {order} (expected {expected})")
    return summary, fields, problems


def _paths_in(value: str) -> list[str]:
    return [p.split("#", 1)[0].rstrip(".,;:)") for p in _PATH_RE.findall(value)]


def read_header(path: Path) -> Header:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    comment = _leading_comment(text, path.suffix)
    if comment is None:
        return Header(rel, "", {}, ["no leading docstring / comment"])
    summary, fields, problems = parse_block(comment)
    for key in LINK_KEYS:
        for target in _paths_in(fields.get(key, "")):
            if not (ROOT / target).exists():
                problems.append(f"{key}: {target} does not exist")
    return Header(rel, summary, fields, problems)


def source_files() -> list[Path]:
    out: list[Path] = []
    for root in SOURCE_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix not in SUFFIXES or not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
                continue
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _link(rel: str) -> str:
    return f"[`{rel}`](../{rel})"


def _linkify(value: str) -> str:
    def repl(m: re.Match[str]) -> str:
        raw = m.group(1)
        target = raw.split("#", 1)[0].rstrip(".,;:)")
        trail = raw[len(target) :]
        return f"[`{target}`](../{target}){trail}" if (ROOT / target).exists() else raw

    return _PATH_RE.sub(repl, value).replace("|", "\\|")


def _package(rel: str) -> str:
    parts = rel.split("/")
    if rel.startswith("src/crb/"):
        return "src/crb/" + parts[2] if len(parts) > 3 else "src/crb"
    if rel.startswith("ui/src/"):
        return "ui/src/" + parts[2] if len(parts) > 3 else "ui/src"
    return (
        parts[0] if len(parts) == 1 else "/".join(parts[:2]) if rel.startswith("ui/") else parts[0]
    )


def render(headers: Iterable[Header], exempt: dict[str, str]) -> str:
    hs = sorted(headers, key=lambda h: h.path)
    by_pkg: dict[str, list[Header]] = {}
    for h in hs:
        by_pkg.setdefault(_package(h.path), []).append(h)
    out = [
        "# Code map — every file, what it is, what proves it, when you touch it",
        "",
        "Generated by `scripts/code_map.py` from the `Navigation` block at the top of every file",
        "(the standard: [FILE-HEADER-STANDARD.md](FILE-HEADER-STANDARD.md)); CI's `code-map` job",
        "refuses a file without one, a dangling link, or a stale map. Read the",
        "[README](../README.md) first for what the product is and claims; read",
        "[ARCHITECTURE.md](ARCHITECTURE.md) for how the layers fit; then use this page to find the",
        "file. `Touch when` is written for a developer onboarding a client repository.",
        "",
        f"{len(hs)} files with a header · {len(exempt)} exempt (listed at the end).",
        "",
    ]
    for pkg, items in by_pkg.items():
        out.append(f"## `{pkg}` ({len(items)} files)")
        out.append("")
        out.append("| File | What it is | Tested by | Touch when |")
        out.append("|---|---|---|---|")
        for h in items:
            f = h.fields
            out.append(
                f"| {_link(h.path)} | {_linkify(f.get('What it is', h.summary))} | "
                f"{_linkify(f.get('Tested by', ''))} | {_linkify(f.get('Touch when', ''))} |"
            )
        out.append("")
    if exempt:
        out.append("## Exempt (no header, by design)")
        out.append("")
        for rel, why in sorted(exempt.items()):
            out.append(f"- {_link(rel)} — {why}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true", help="validate and compare; write nothing")
    ap.add_argument("--list-missing", action="store_true", help="print files without a valid block")
    args = ap.parse_args(argv)
    headers: list[Header] = []
    exempt: dict[str, str] = {}
    for p in source_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            exempt[rel] = EXEMPT[rel]
            continue
        headers.append(read_header(p))
    bad = [h for h in headers if h.problems]
    if args.list_missing:
        for h in bad:
            print(f"{h.path}: {'; '.join(h.problems)}")
        print(f"{len(bad)} of {len(headers)} files need work", file=sys.stderr)
        return 1 if bad else 0
    rendered = render([h for h in headers if not h.problems], exempt)
    if args.check:
        for h in bad:
            print(f"{h.path}: {'; '.join(h.problems)}", file=sys.stderr)
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        stale = current != rendered
        if stale:
            print(f"{OUT.relative_to(ROOT)} is stale: run scripts/code_map.py", file=sys.stderr)
        return 1 if (bad or stale) else 0
    OUT.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(headers) - len(bad)} files; {len(bad)} without a valid block"
    )
    for h in bad:
        print(f"  {h.path}: {'; '.join(h.problems)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
