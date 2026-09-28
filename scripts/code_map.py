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
    python scripts/code_map.py --check --changed-since origin/main   # CI on a pull request

``--check`` fails on: a file with no block; a missing required key; a key out of order; a path
in ``Layer``/``ADRs``/``Works with``/``Tested by``/``Touch when``/``Claims`` that does not exist
in the repository (anchors are stripped before the check) — "in the repository" meaning what a
fresh clone would hold: tracked, or new and not ignored, never a git-ignored build output that
happens to be on this disk (P-355); a ``Tested by`` that is blank;
a ``Touch when`` whose first clause does not address onboarding a client repository (files
older than that rule are listed in ``scripts/code_map_onboarding_baseline.txt``, which only
shrinks — with ``--changed-since REF``, as CI runs it on a pull request, a listed file the
change edits and a path the change adds to the list are refused too); a ``docs/CODE-MAP.md``
that differs from what the headers generate. Files listed in
``EXEMPT`` (an explicit path → reason map; today only Vite's generated ambient types) are
skipped and listed at the end of the map so the exemption is visible. There is no size- or
name-based exemption: a thin ``__init__.py`` needs a block like every other file.

Navigation
----------
What it is:   The code-map generator and header gate (stdlib only; runs in CI's ``code-map`` job).
What it does: Parses every source file's Navigation block, validates keys, order, links and
              that ``Touch when`` speaks to onboarding a client repository first, writes
              docs/CODE-MAP.md, and in --check mode exits non-zero on any defect or drift.
How:          Walk the source roots → extract the docstring / leading comment per language →
              parse ``Key: value`` lines (continuations indented) → resolve every path against
              what a fresh clone holds (``git ls-files`` tracked + untracked-not-ignored, the
              disk outside a checkout) → render Markdown tables grouped by top-level package.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/FILE-HEADER-STANDARD.md (the format it enforces), docs/CODE-MAP.md (its
              output), .github/workflows/ci.yml (the code-map job that runs --check)
Tested by:    tests/test_code_map.py
Touch when:   never for a new repository; a new source root or language is added; a key is
              added to the standard (update REQUIRED_KEYS, the standard and every header
              together).
"""

from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "CODE-MAP.md"
SOURCE_ROOTS: tuple[str, ...] = ("src", "tests", "ui/src", "ui/e2e", "scripts", "deploy")
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
_PATH_RE = re.compile(r"(?<![\w/.-])((?:src|tests|ui|docs|deploy|scripts|\.github)/[\w./-]+)")
_KEY_RE = re.compile(r"^(" + "|".join(re.escape(k) for k in KEYS) + r"):\s*(.*)$")
#: ``Touch when`` speaks first to the developer onboarding a client repository
#: (docs/FILE-HEADER-STANDARD.md): its first clause — up to the first ``;``, sentence end,
#: dash or bracket — speaks about onboarding one ("never for a new repository; …").
_FIRST_CLAUSE_RE = re.compile(r";|\.\s|\s(?:—|\u2013|-)\s|\(")
#: Code spans and paths are removed before the match: ``GET /repos/{name}`` or
#: ``ui/src/screens/Repos/…`` names a route or a folder, not a repository being onboarded.
_NOT_PROSE_RE = re.compile(r"``.*?``|`[^`]*`|\S*/\S*")
#: The ecosystems a runner or recipe serves, as a first clause names them ("a Go repository
#: needs cgo"). A repository with no such word before it — "the image repository", "the
#: repository layer", "Add repo" — is not one being onboarded (P-116).
ONBOARDING_ECOSYSTEMS: tuple[str, ...] = (
    "Python", "Go", "Rust", "Cargo", "JavaScript", "TypeScript", "Node", "Maven", "Gradle",
    "JVM", "Java", "Kotlin",
)  # fmt: skip
_ONBOARDING_RE = re.compile(
    r"\bonboard"
    r"|\b(?:new|client|" + "|".join(map(re.escape, ONBOARDING_ECOSYSTEMS)) + r")\s+"
    r"repo(?:s|sitory|sitories)?\b",
    re.IGNORECASE,
)
#: Files whose ``Touch when`` is older than the onboarding check. The list only shrinks:
#: a file that now addresses onboarding first must leave it, and an entry for a file that is
#: gone fails ``--check`` (P-114).
ONBOARDING_BASELINE = "scripts/code_map_onboarding_baseline.txt"


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


def addresses_onboarding(touch_when: str) -> bool:
    """True when the first clause of ``Touch when``, its code spans and paths removed, speaks
    about onboarding a client repository: onboarding itself, or a new, client or
    ecosystem-named repository (``ONBOARDING_ECOSYSTEMS``)."""
    first = _FIRST_CLAUSE_RE.split(touch_when, maxsplit=1)[0]
    return bool(_ONBOARDING_RE.search(_NOT_PROSE_RE.sub(" ", first)))


def onboarding_baseline() -> frozenset[str]:
    path = ROOT / ONBOARDING_BASELINE
    if not path.exists():
        return frozenset()
    lines = (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return frozenset(ln for ln in lines if ln and not ln.startswith("#"))


def baseline_violations(
    baseline: frozenset[str], changed: set[str], before: frozenset[str] | None
) -> list[str]:
    """What a change owes the onboarding baseline: every baseline file it edits must leave
    the list (its ``Touch when`` fixed first), and no path may join it. ``before`` is the
    baseline at the change's base, ``None`` when the base had none (the list's first change)."""
    found = [
        f"{rel}: edited in this change but still in {ONBOARDING_BASELINE}: put onboarding a "
        "client repository first in its Touch when and delete its line"
        for rel in sorted(baseline & changed)
    ]
    if before is not None:
        found += [
            f"{rel}: added to {ONBOARDING_BASELINE}, which only shrinks: put onboarding first "
            "in its Touch when instead"
            for rel in sorted(baseline - before)
        ]
    return found


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def changed_since(ref: str) -> tuple[set[str], frozenset[str] | None]:
    """The paths added, modified or renamed since the merge base with ``ref`` (the working
    tree included), and the baseline at that base (``None`` when it had none). Raises
    ``subprocess.CalledProcessError`` when ``ref`` cannot be resolved: the caller fails."""
    base = _git("merge-base", ref, "HEAD").strip()
    changed = set(_git("diff", "--name-only", "--diff-filter=AMR", base).split())
    try:
        text = _git("show", f"{base}:{ONBOARDING_BASELINE}")
    except subprocess.CalledProcessError:
        return changed, None
    lines = (ln.strip() for ln in text.splitlines())
    return changed, frozenset(ln for ln in lines if ln and not ln.startswith("#"))


def _onboarding_problems(rel: str, fields: dict[str, str], baseline: frozenset[str]) -> list[str]:
    touch = fields.get("Touch when", "")
    if not touch:
        return []  # already reported as a missing or empty key
    if rel in baseline:
        if addresses_onboarding(touch):
            return [
                f"Touch when now addresses onboarding first: remove it from {ONBOARDING_BASELINE}"
            ]
        return []
    if addresses_onboarding(touch):
        return []
    return [
        "Touch when: its first clause does not address onboarding a client repository "
        "(name onboarding, a new or client repository, or an ecosystem in "
        "ONBOARDING_ECOSYSTEMS; write 'never for a new repository; …' when nothing here "
        "changes for one — docs/FILE-HEADER-STANDARD.md)"
    ]


@functools.lru_cache(maxsize=8)
def _clone_paths(root: Path) -> frozenset[str] | None:
    """Every file and directory a fresh clone of ``root`` would hold — tracked, or new and
    not ignored — or ``None`` when ``root`` is not the top of a git checkout (an exported
    tree, where nothing was ignored and the disk is the answer).

    A header that cites a git-ignored path (``ui/.tsbuild/``, the type-check's build info)
    resolved in the checkout that had built it and not in CI's fresh clone, so the gate
    passed on a dirty tree and failed in the required job (P-355). Resolving against this
    set instead of the disk makes the answer the same in every checkout."""
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if Path(top).resolve() != root.resolve():
            return None
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return None
    out: set[str] = set()
    for rel in filter(None, listed.split("\0")):
        parts = rel.split("/")
        out.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return frozenset(out)


def resolves(target: str) -> bool:
    """Whether a header path names something a fresh clone of the repository holds: it is on
    this disk AND (inside a git checkout) tracked or new-and-not-ignored."""
    rel = target.rstrip("/")
    if not (ROOT / rel).exists():
        return False
    listed = _clone_paths(ROOT)
    return listed is None or rel in listed


def _paths_in(value: str) -> list[str]:
    return [p.split("#", 1)[0].rstrip(".,;:)") for p in _PATH_RE.findall(value)]


def read_header(path: Path) -> Header:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    comment = _leading_comment(text, path.suffix)
    if comment is None:
        return Header(rel, "", {}, ["no leading docstring / comment"])
    summary, fields, problems = parse_block(comment)
    problems += _onboarding_problems(rel, fields, onboarding_baseline())
    for key in LINK_KEYS:
        for target in _paths_in(fields.get(key, "")):
            if not resolves(target):
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
        return f"[`{target}`](../{target}){trail}" if resolves(target) else raw

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
    ap.add_argument(
        "--changed-since",
        metavar="REF",
        help="with --check: refuse a baseline file this change edits, and any path it adds "
        "to the baseline (CI passes the pull request's base branch)",
    )
    args = ap.parse_args(argv)
    _clone_paths.cache_clear()  # one reading of the checkout per run, never a stale one
    headers: list[Header] = []
    exempt: dict[str, str] = {}
    for p in source_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            exempt[rel] = EXEMPT[rel]
            continue
        headers.append(read_header(p))
    bad = [h for h in headers if h.problems]
    gone = sorted(onboarding_baseline() - {h.path for h in headers})
    if args.list_missing:
        for h in bad:
            print(f"{h.path}: {'; '.join(h.problems)}")
        print(f"{len(bad)} of {len(headers)} files need work", file=sys.stderr)
        return 1 if bad else 0
    rendered = render([h for h in headers if not h.problems], exempt)
    if args.check:
        for h in bad:
            print(f"{h.path}: {'; '.join(h.problems)}", file=sys.stderr)
        for rel in gone:
            print(f"{ONBOARDING_BASELINE}: {rel} is not a source file: remove it", file=sys.stderr)
        owed: list[str] = []
        if args.changed_since:
            try:
                changed, before = changed_since(args.changed_since)
            except (subprocess.CalledProcessError, OSError) as exc:
                owed = [f"--changed-since {args.changed_since}: git could not diff it ({exc})"]
            else:
                owed = baseline_violations(onboarding_baseline(), changed, before)
        for line in owed:
            print(line, file=sys.stderr)
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        stale = current != rendered
        if stale:
            print(f"{OUT.relative_to(ROOT)} is stale: run scripts/code_map.py", file=sys.stderr)
        return 1 if (bad or stale or gone or owed) else 0
    OUT.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(headers) - len(bad)} files; {len(bad)} without a valid block"
    )
    for h in bad:
        print(f"  {h.path}: {'; '.join(h.problems)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
