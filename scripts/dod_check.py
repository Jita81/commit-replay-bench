#!/usr/bin/env python3
"""The definition-of-done roll-up — and the gate that keeps "done" a record, not a feeling.

Every page, journey, value stream and the product carry one artefact of the same shape under
``docs/dod/`` (the standard is ``docs/dod/STANDARD.md``): YAML front matter (id, level, scope,
parent, children, persons, owner) and one criteria table whose rows say what done means, what
proves it (a typed evidence reference) and how far it is (met / partial / unmet / n/a). This
script reads them all, resolves every evidence reference against the repository, computes the
roll-up (a level is done only when its children are done AND its own criteria are met), and
writes ``docs/dod/GAP-ANALYSIS.md``: per level the status, and the open gaps ranked so the
first line is the one that unblocks the most "done".

    python scripts/dod_check.py            # rewrite docs/dod/GAP-ANALYSIS.md and stamp status
    python scripts/dod_check.py --check    # CI: artefacts valid, evidence resolves, no drift

``--check`` fails on: a route in ``ui/src/App.tsx`` with no page artefact; a ``JOURNEY_STEPS``
entry with no journey; an artefact whose parent does not exist or whose children are not its
children; a criterion with a malformed id, an unknown category, an unknown state, ``met``
without a resolvable evidence reference, ``partial``/``unmet`` without a gap id, a gap id
defined nowhere, or an ``F-``/``B-`` id that is in no row of the backlog reviews; a gap
line that does not read "what is missing · the smallest change that closes it · owner", or
whose owner is not one of ui/server/factory/docs/deploy; the same gap id carrying two
different lines in two files (one id is one piece of work); a gap line that no criterion of
its file cites (or, in the register, no pending row); a ``PLAN.md`` wave item that is not a
gap id the record defines or has retired; a gap among the order of work's first ``TOP`` rows
that no wave names; a retired id that neither the artefacts' git history nor the base
branch's committed gap analysis shows was a gap (the generated file never vouches for
itself); a twin left in old words — a clause of at least ``TWIN_MIN_WORDS`` words that a
criterion reworded since the merge-base with the base branch dropped, still said by another
criterion that does not wait on the same gap (P-116); a criterion or gap line that states a
value a Proposed ADR leaves to the operator without ``ADR-nnnn [operator]`` on it, an
``[operator]`` marker the ADR's ``## Operator values`` table does not register, or the
marker left on after the ADR is accepted (P-117); an evidence reference that does not
resolve; and a ``GAP-ANALYSIS.md`` or a ``status:`` line that differs from what the
artefacts generate. It never edits a criterion.

    python scripts/dod_check.py --check --base origin/integration/next   # another base branch
    DOD_BASE=origin/integration/next python scripts/dod_check.py --check  # the same (CI's form)

Navigation
----------
What it is:   The definition-of-done checker and gap-analysis generator (stdlib only; CI's
              ``dod`` job runs ``--check``).
What it does: Parses every artefact under docs/dod/, validates ids, categories, states, gaps
              and parent/child links, resolves each typed evidence reference against the tree
              (tests, vitest titles, walkthrough specs, hint registry and ratchet, API routes,
              code symbols, doc anchors, CI jobs, ADRs, decision-log rows), computes the
              four-level roll-up and writes docs/dod/GAP-ANALYSIS.md (the order of work, the
              gaps by fan-out, the gap ids retired, and every open criterion); refuses a gap
              line nothing cites, a PLAN.md wave item that is not a gap, a top-ranked gap in
              no wave, a retired id that git history does not vouch for, a twin criterion
              left in the words another criterion dropped since the base (P-116), and a value
              a Proposed ADR leaves to the operator stated as settled (P-117); --check exits
              non-zero on any defect or drift.
How:          Walk docs/dod/{pages,journeys,streams}/*.md + product.md → parse front matter
              and the criteria table → resolve evidence (one resolver per prefix) → demote
              ``met`` with no resolving reference → compare each criterion with its words at
              the merge-base (git show) and each Proposed ADR's operator values → roll up
              child → parent → render.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/dod/STANDARD.md (the format it enforces, and the ``## Operator values`` table a
              Proposed ADR under docs/adr/ carries, as ADR-0026 does), docs/dod/GAP-ANALYSIS.md (its
              output), docs/reviews/2026-09-17-enterprise-front-end.md §9 (the F-/B- backlog a gap
              may cite), ui/src/App.tsx and ui/src/components/Layout.tsx (the routes and
              JOURNEY_STEPS every artefact must cover), ui/src/help/hints.ts and hints-ratchet*.tsx
              (hint: references), docs/API.md (route: references), .github/workflows/ci.yml (the dod
              job that runs --check, with full history and the pull request's base in DOD_BASE,
              since the artefacts' git history vouches for each retired id and the base's criteria
              are what a rewording is read against), docs/dod/PLAN.md (its wave items must be gap
              ids)
Tested by:    tests/test_dod_check.py
Touch when:   a level or category is added to the standard (update CATEGORIES / LEVELS and the
              standard together); a new evidence prefix is needed (add a resolver and a row to
              STANDARD.md §3); a route or journey step is added (write its artefact — the
              check tells you which).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOD = ROOT / "docs" / "dod"
OUT = DOD / "GAP-ANALYSIS.md"
APP = ROOT / "ui" / "src" / "App.tsx"
LAYOUT = ROOT / "ui" / "src" / "components" / "Layout.tsx"
HINTS = ROOT / "ui" / "src" / "help" / "hints.ts"
HELP = ROOT / "ui" / "src" / "help" / "help.ts"
API_DOC = ROOT / "docs" / "API.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DECISION_LOG = ROOT / "docs" / "DECISION-LOG.md"
BACKLOG = ROOT / "docs" / "reviews" / "2026-09-17-enterprise-front-end.md"
ADR_DIR = ROOT / "docs" / "adr"
PREVENTION = ROOT / "docs" / "PREVENTION.md"
PLAN = DOD / "PLAN.md"

LEVELS: tuple[str, ...] = ("page", "journey", "stream", "product")
LEVEL_DIR: dict[str, str] = {"page": "pages", "journey": "journeys", "stream": "streams"}
STATES: tuple[str, ...] = ("met", "partial", "unmet", "n/a")
STATUSES: tuple[str, ...] = ("done", "partial", "missing")
COMMON: tuple[str, ...] = (
    "PURPOSE",
    "ENTRY-EXIT",
    "TRUTH",
    "ACTIONS",
    "EXPLANATION",
    "EVIDENCE",
    "ROLES",
    "OPERATIONS",
    "ACCESSIBILITY",
    "NON-GOALS",
)
EXTRA: dict[str, tuple[str, ...]] = {
    "page": (),
    "journey": ("STEPS", "PROOF", "TIME-COST", "RECOVERY"),
    "stream": ("TRIGGER", "OUTCOME", "HANDOFF", "MEASURE", "AUTOMATION"),
    "product": (
        "VALUE",
        "IDENTITY",
        "GO-LIVE",
        "CLAIMS",
        "RELEASE",
        "POSTURE",
        "SUPPORT",
        "EXTENSIBILITY",
    ),
}
#: Category weight for the gap ranking — what blocks a governance reviewer outranks polish.
WEIGHT: dict[str, int] = {
    # the operator's refocus (2026-09-25): the value is what the rest is for, so an open VALUE
    # criterion outranks any other open criterion anywhere in the tree — even a product-level
    # one in a weight-5 category blocking three criteria (4 × 5 × 3 × 2 = 120 < 4 × 16 × 1 × 2)
    "VALUE": 16,
    "TRIGGER": 5,
    "OUTCOME": 5,
    "TRUTH": 5,
    "ROLES": 5,
    "GO-LIVE": 5,
    "CLAIMS": 5,
    "POSTURE": 5,
    "EVIDENCE": 4,
    "PROOF": 4,
    "HANDOFF": 4,
    "STEPS": 4,
    "MEASURE": 4,
    "ACCESSIBILITY": 4,
    "ACTIONS": 3,
    "RECOVERY": 3,
    "OPERATIONS": 3,
    "EXTENSIBILITY": 3,
    "EXPLANATION": 2,
    "ENTRY-EXIT": 2,
    "AUTOMATION": 2,
    "RELEASE": 2,
    "SUPPORT": 2,
    "PURPOSE": 1,
    "TIME-COST": 1,
    "NON-GOALS": 1,
    "IDENTITY": 1,
}
LEVEL_WEIGHT: dict[str, int] = {"product": 4, "stream": 3, "journey": 2, "page": 2}
#: How many ranked rows are "the order of work"; the rest sit under a collapsed heading.
TOP = 25
#: Categories where a half-built answer is as dishonest as no answer: `partial` scores like
#: `unmet`. Everywhere else `partial` means "some of it is there" and scores half.
HONESTY: tuple[str, ...] = ("VALUE", "TRUTH", "CLAIMS", "ROLES", "POSTURE")
#: The layers a gap can be owned by — the last field of a `## Gaps` line (STANDARD.md §2).
OWNERS: tuple[str, ...] = ("ui", "server", "factory", "docs", "deploy")
#: The reference prefixes; also the boundary the evidence splitter cuts on, so a `vitest:`
#: title may itself contain " · " (Layout's `Journey · n of 4 · Step`).
PREFIXES: tuple[str, ...] = (
    "test",
    "vitest",
    "spec",
    "hint",
    "route",
    "code",
    "doc",
    "ci",
    "adr",
    "dl",
    "measured",
)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.[a-z-]+\.\d+$")
_GAP_RE = re.compile(r"^(G-\d{3}|F\d+[a-z]?|B-\d+[a-z]?)$")
#: The prevention register (docs/PREVENTION.md, STANDARD.md §7): the levels of the prevention
#: hierarchy, strongest first; the states an entry may be in; and the reference prefixes that
#: can FAIL when the class recurs — a closed entry needs at least one of them.
PREVENTION_LEVELS: tuple[str, ...] = ("construction", "gate", "mistake-proofing", "advisory")
PREVENTION_STATES: tuple[str, ...] = ("closed", "pending")
EXECUTABLE_PREFIXES: tuple[str, ...] = ("test", "vitest", "spec", "ci")
_PREVENTION_ID_RE = re.compile(r"^P-\d{3}$")
_ART_ID_RE = re.compile(r"^dod\.(page|journey|stream)\.[a-z0-9][a-z0-9-]*$|^dod\.product$")


@dataclass
class Criterion:
    id: str
    category: str
    text: str
    evidence: str
    state: str
    gap: str
    line: int
    resolved: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def effective_state(self) -> str:
        """``met`` demoted to ``partial`` when nothing it cites resolves."""
        if self.state == "met" and not self.resolved:
            return "partial"
        return self.state


@dataclass
class Artefact:
    path: Path
    front: dict[str, str]
    criteria: list[Criterion]
    gaps: dict[str, str]
    status_line: int | None = None
    status: str = "partial"

    @property
    def id(self) -> str:
        return self.front.get("id", "")

    @property
    def level(self) -> str:
        return self.front.get("level", "")

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    def list_field(self, key: str) -> list[str]:
        raw = self.front.get(key, "")
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        return [x.strip().strip("'\"") for x in raw.split(",") if x.strip()]


# ------------------------------------------------------------------ parsing


def record_gap(gaps: dict[str, str], gid: str, body: str, where: str, errors: list[str]) -> None:
    """Record one ``## Gaps`` line — the ONE place every parser does it (the artefacts and
    the prevention register). The same id twice in one file with different text is refused
    and the FIRST line stands: an overwrite silently dropped a gap nobody had closed, or
    rendered the wrong "what is missing" (STANDARD §2: one id is one piece of work)."""
    if gid in gaps and gaps[gid] != body:
        errors.append(
            f"{where}: gap {gid} is defined twice in this file with different text — one id "
            "is one piece of work; renumber one of them"
        )
        return
    gaps[gid] = body


def parse_artefact(path: Path, text: str | None = None) -> tuple[Artefact, list[str]]:
    """One artefact, read from ``path`` — or from ``text`` when given (the twin check reads
    the base branch's copy through git, never from the work tree)."""
    errors: list[str] = []
    if text is None:
        text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return Artefact(path, {}, [], {}), [f"{path.name}: no front matter"]
    front: dict[str, str] = {}
    status_line: int | None = None
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        m = re.match(r"^([a-z_]+):\s*(.*?)\s*(#.*)?$", lines[i])
        if m:
            key, val = m.group(1), m.group(2)
            front[key] = val.strip()
            if key == "status":
                status_line = i
        i += 1
    if i >= len(lines):
        errors.append(f"{path.name}: front matter never closed")
    criteria: list[Criterion] = []
    gaps: dict[str, str] = {}
    in_table = False
    in_gaps = False
    for n, line in enumerate(lines[i + 1 :], start=i + 2):
        s = line.strip()
        if s.startswith("## "):
            in_table = s.lower().startswith("## definition of done")
            in_gaps = s.lower().startswith("## gaps")
            continue
        if in_table and s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 6 or cells[0] in ("id", "") or set(cells[0]) <= {"-", ":"}:
                continue
            crit_id, cat, txt, ev, st, gap = (cells + [""] * 6)[:6]
            criteria.append(Criterion(crit_id, cat, txt, ev.strip("`"), st, gap, n))
        if in_gaps and s.startswith("- **"):
            # the em dash is the grammar the standard declares; a hyphen here reads as a
            # different list style and the record stops being one shape (CodeRabbit, PR #47)
            m = re.match("^- \\*\\*(G-\\d{3})\\*\\*\\s*\u2014\\s*(.+)$", s)
            if m:
                body = m.group(2).strip()
                record_gap(gaps, m.group(1), body, f"{path.name}:{n}", errors)
                fields = body.split(" · ")
                if len(fields) < 3:
                    errors.append(
                        f"{path.name}:{n}: gap {m.group(1)} must read "
                        "'what is missing · the smallest change that closes it · owner'"
                    )
                elif fields[-1].strip().rstrip(".") not in OWNERS:
                    errors.append(
                        f"{path.name}:{n}: gap {m.group(1)} ends {fields[-1].strip()!r}; "
                        f"the owner must be one of {OWNERS}"
                    )
            else:
                errors.append(f"{path.name}:{n}: gap line must be '- **G-nnn** — text'")
    return Artefact(path, front, criteria, gaps, status_line), errors


def artefact_files() -> list[Path]:
    out: list[Path] = []
    for sub in LEVEL_DIR.values():
        out.extend(sorted((DOD / sub).glob("*.md")))
    product = DOD / "product.md"
    if product.exists():
        out.append(product)
    return out


# ------------------------------------------------------------------ evidence resolvers

_TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+(test_[A-Za-z0-9_]+)\s*\(", re.M)


def _file(rel: str) -> Path | None:
    p = ROOT / rel
    return p if p.is_file() else None


def _resolve_test(ref: str) -> bool:
    rel, _, name = ref.partition("::")
    p = _file(rel)
    if p is None or not name:
        return False
    names = {m.group(2) for m in _TEST_DEF.finditer(p.read_text(encoding="utf-8"))}
    return name.split("[", 1)[0] in names


def _resolve_title(ref: str) -> bool:
    rel, _, title = ref.partition("::")
    p = _file(rel)
    if p is None or not title:
        return False
    title = title.strip().strip("\"'")
    return title in p.read_text(encoding="utf-8")


def _resolve_hint(ref: str) -> bool:
    kind, _, key = ref.partition(":")
    if kind == "id":
        return HINTS.is_file() and f"'{key}':" in HINTS.read_text(encoding="utf-8")
    if kind == "ratchet":
        # a SCREENS entry is a top-level key of the route: `  '/results': {`
        for p in (ROOT / "ui" / "src" / "help").glob("hints-ratchet*.tsx"):
            if re.search(
                r"^  '" + re.escape(key) + r"':\s*\{", p.read_text(encoding="utf-8"), re.M
            ):
                return True
        return False
    if kind == "about":
        # help.ts HELP[] entries carry `route: '/home'`
        return HELP.is_file() and bool(
            re.search(r"route:\s*'" + re.escape(key) + r"'", HELP.read_text(encoding="utf-8"))
        )
    return False


def _resolve_route(ref: str) -> bool:
    """``GET /health`` — the path exactly as docs/API.md lists it (no ``/api/v1`` prefix)."""
    if not API_DOC.is_file():
        return False
    method, _, path = ref.partition(" ")
    text = API_DOC.read_text(encoding="utf-8")
    return bool(
        re.search(r"\|\s*" + re.escape(method) + r"\s*\|\s*`" + re.escape(path.strip()) + "`", text)
    )


def _resolve_code(ref: str) -> bool:
    """``code:<file>::<symbol>`` (the file defines it) or ``code:<file>::"<literal>"`` (the
    file contains that exact text). A bare ``code:<file>`` never resolves: a file existing
    proves nothing about the criterion, and an evidence reference that cannot fail is not
    evidence (CodeRabbit on PR #47).
    """
    rel, sep, symbol = ref.partition("::")
    p = _file(rel)
    if p is None or not sep or not symbol:
        return False
    text = p.read_text(encoding="utf-8")
    if symbol[0] in "\"'" and symbol[-1] == symbol[0] and len(symbol) > 2:
        return symbol[1:-1] in text
    return bool(
        re.search(
            r"^\s*(?:async\s+def|def|class|export\s+(?:const|function|class|type|interface)|const|function)\s+"
            + re.escape(symbol)
            + r"\b",
            text,
            re.M,
        )
    )


def _slug(heading: str) -> str:
    """A heading's anchor, by GitHub's rule — including the part that surprises people.

    GitHub replaces EACH space with its own hyphen and does not collapse runs, so a heading
    with a stripped character between two spaces (``§11. Intake — work``) gets a DOUBLE
    hyphen (``#11-intake--work``). Collapsing runs here made the checker accept an anchor a
    reader's click could not resolve, which is the opposite of what this gate is for.
    """
    h = heading.strip().lower()
    h = re.sub(r"[`*_]", "", h)
    h = re.sub(r"[^\w\s-]", "", h)
    return h.strip().replace(" ", "-")


def _resolve_doc(ref: str) -> bool:
    rel, _, anchor = ref.partition("#")
    p = _file(rel)
    if p is None:
        return False
    if not anchor:
        return True
    slugs = {
        _slug(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+)$", p.read_text(encoding="utf-8"), re.M)
    }
    return anchor in slugs


def _resolve_ci(ref: str) -> bool:
    return CI.is_file() and bool(
        re.search(r"^  " + re.escape(ref.strip()) + r":\s*$", CI.read_text(encoding="utf-8"), re.M)
    )


def _resolve_adr(ref: str) -> bool:
    return any(ADR_DIR.glob(f"{ref.strip()}-*.md"))


def _resolve_dl(ref: str) -> bool:
    return DECISION_LOG.is_file() and f"| {ref.strip()} |" in DECISION_LOG.read_text(
        encoding="utf-8"
    )


#: A §9 row names one id (``F23``), a pair (``B-9/F30``) or a range (``F36–F47``) — the
#: audit merges rows as it lands them, so a cited id may sit inside any of the three.
_BACKLOG_ROW = re.compile(
    r"^\|\s*((?:F\d+[a-z]?|B-\d+[a-z]?)(?:\s*[/,\u2013\u2014-]\s*(?:F\d+[a-z]?|B-\d+[a-z]?))*)\s*\|\s*(.+?)\s*\|\s*([^|]*?)\s*\|"
)
_ID_IN_CELL = re.compile(r"F\d+[a-z]?|B-\d+[a-z]?")


def _ids_in(cell: str) -> list[str]:
    """Every id a §9 id-cell names, expanding an ``Fnn–Fmm`` range end to end."""
    ids = _ID_IN_CELL.findall(cell)
    if len(ids) == 2 and re.search("[\u2013\u2014-]", cell) and "/" not in cell and "," not in cell:
        a, b = ids
        if a[0] == b[0] == "F" and a[1:].isdigit() and b[1:].isdigit():
            lo, hi = int(a[1:]), int(b[1:])
            if lo < hi:
                return [f"F{n}" for n in range(lo, hi + 1)]
    return ids


def backlog_index() -> dict[str, tuple[str, str]]:
    """``F23`` → (its bold title, its size), read from the ordered backlog (§9).

    A row may name several ids (``B-9/F30``) or a range (``F36-F47``); every id it names
    resolves to that row, and the first row to name an id wins (§9 is ordered). §9 is read
    first and then every other review under ``docs/reviews/``, because the backlog is spread
    over the reviews that raised each item (``B-9`` comes from the external assessment); a
    cited id must exist as a row somewhere in that record, not only in §9.

    A gap may cite a backlog row instead of defining a ``G-nnn``; the ranked list has to be
    able to say what that row is, so an id that §9 does not carry is a defect, not a link.
    """
    out: dict[str, tuple[str, str]] = {}
    sources = [BACKLOG, *sorted((ROOT / "docs" / "reviews").glob("*.md"))]
    lines: list[str] = []
    for src in sources:
        if src.is_file():
            lines.extend(src.read_text(encoding="utf-8").split("\n"))
    for line in lines:
        m = _BACKLOG_ROW.match(line.strip())
        if not m:
            continue
        ids, cell, size = _ids_in(m.group(1)), m.group(2), m.group(3)
        bold = re.search(r"\*\*(.+?)\*\*", cell)
        title = bold.group(1) if bold else cell.split("—")[0].strip()
        for item in ids:
            out.setdefault(item, (title, size.strip() or "—"))
    return out


RESOLVERS = {
    "test": _resolve_test,
    "vitest": _resolve_title,
    "spec": _resolve_title,
    "hint": _resolve_hint,
    "route": _resolve_route,
    "code": _resolve_code,
    "doc": _resolve_doc,
    "ci": _resolve_ci,
    "adr": _resolve_adr,
    "dl": _resolve_dl,
}


_SEP_RE = re.compile(r"(?:\s·\s|;\s+)(?=`{0,2}(?:" + "|".join(PREFIXES) + r"):)")


def split_refs(evidence: str) -> list[str]:
    """References are separated by ` · ` or `; `.

    The cut is made only where the next reference begins — a typed prefix from ``PREFIXES``
    — so a quoted ``vitest:`` / ``spec:`` title may itself contain " · " (Layout's
    ``Journey · n of 4 · Step``) without being torn into three unresolvable pieces.
    """
    if evidence.strip() in ("", "absent"):
        return []
    parts = _SEP_RE.split(evidence)
    return [p.strip().strip("`") for p in parts if p.strip()]


def resolve(criterion: Criterion) -> None:
    for ref in split_refs(criterion.evidence):
        prefix, _, rest = ref.partition(":")
        if prefix == "measured":
            # never resolved (it names a measurement, not a file); allowed only beside a
            # resolvable reference, and it must carry what a measured claim carries:
            # n, a method and an apparatus version (docs/dod/STANDARD.md §3).
            low = rest.lower()
            if not (
                re.search(r"\bn\s*=", low)
                and "method" in low
                and re.search(r"apparatus\s+\d+\.\d+", low)
            ):
                criterion.unresolved.append(ref)
            continue
        fn = RESOLVERS.get(prefix)
        if fn is not None and fn(rest):
            criterion.resolved.append(ref)
        else:
            criterion.unresolved.append(ref)


# ------------------------------------------------------------------ the prevention register


@dataclass
class Prevention:
    """One row of docs/PREVENTION.md: a bug of ours, its class, and what stops it recurring."""

    id: str
    bug: str
    cls: str
    first_seen: str
    artefact: str
    level: str
    status: str
    gap: str
    line: int


def parse_prevention(path: Path) -> tuple[list[Prevention], dict[str, str], list[str]]:
    """The register's rows and its ``## Gaps`` lines (the same grammar as an artefact's)."""
    if not path.is_file():
        return (
            [],
            {},
            ["docs/PREVENTION.md is missing — the register of our own bugs (STANDARD.md §7)"],
        )
    rows: list[Prevention] = []
    gaps: dict[str, str] = {}
    errors: list[str] = []
    section = ""
    for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        s = line.strip()
        if s.startswith("## "):
            section = s[3:].strip().lower()
            continue
        if section == "register" and s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells[0] in ("id", "") or set(cells[0]) <= {"-", ":"}:
                continue
            if len(cells) != 8:
                errors.append(f"PREVENTION.md:{n}: a register row has 8 cells, not {len(cells)}")
                continue
            pid, bug, cls, seen, art, level, status, gap = cells
            rows.append(Prevention(pid, bug, cls, seen, art.strip("`"), level, status, gap, n))
        elif section == "gaps" and s.startswith("- **"):
            m = re.match("^- \\*\\*(G-\\d{3})\\*\\*\\s*\u2014\\s*(.+)$", s)
            if not m:
                errors.append(f"PREVENTION.md:{n}: gap line must be '- **G-nnn** — text'")
                continue
            body = m.group(2).strip()
            fields = body.split(" · ")
            if len(fields) < 3 or fields[-1].strip().rstrip(".") not in OWNERS:
                errors.append(
                    f"PREVENTION.md:{n}: gap {m.group(1)} must read "
                    f"'what is missing · the smallest change that closes it · owner' ({OWNERS})"
                )
            record_gap(gaps, m.group(1), body, f"PREVENTION.md:{n}", errors)
    if not rows and not errors:
        errors.append("PREVENTION.md: no rows under '## Register'")
    return rows, gaps, errors


def validate_prevention(
    rows: list[Prevention], gaps: dict[str, str], backlog: dict[str, tuple[str, str]]
) -> list[str]:
    """STANDARD.md §7: a defect is closed only with the artefact that fails if its class
    recurs. Every reference resolves; a closed row carries at least one executable one
    (``test:`` / ``vitest:`` / ``spec:`` / ``ci:``) and is never ``advisory``; a pending row
    names a gap (with its owner) or a backlog id."""
    errors: list[str] = []
    seen: set[str] = set()
    for r in rows:
        where = f"docs/PREVENTION.md:{r.line}: {r.id}"
        if not _PREVENTION_ID_RE.match(r.id):
            errors.append(f"{where}: id must be P-nnn")
        if r.id in seen:
            errors.append(f"{where}: duplicate id {r.id}")
        seen.add(r.id)
        for name, value in (("a bug", r.bug), ("a class", r.cls), ("a first-seen", r.first_seen)):
            if not value:
                errors.append(f"{where}: needs {name} (the evidence of when it bit us)")
        if r.level not in PREVENTION_LEVELS:
            errors.append(f"{where}: level must be one of {PREVENTION_LEVELS}, got {r.level!r}")
        if r.status not in PREVENTION_STATES:
            errors.append(f"{where}: status must be one of {PREVENTION_STATES}, got {r.status!r}")
        refs = [] if r.artefact in ("", "pending", "absent") else split_refs(r.artefact)
        probe = Criterion(r.id, "", "", r.artefact, r.status, r.gap, r.line)
        if refs:
            resolve(probe)
        for ref in probe.unresolved:
            errors.append(f"{where}: evidence does not resolve: {ref}")
        if r.status == "closed":
            if r.level == "advisory":
                errors.append(
                    f"{where}: an advisory artefact cannot close a defect — text cannot fail "
                    "when the class recurs; keep it pending with a gap toward a gate"
                )
            if not any(ref.split(":", 1)[0] in EXECUTABLE_PREFIXES for ref in probe.resolved):
                errors.append(
                    f"{where}: a defect is closed only by an artefact that fails when its class "
                    f"recurs — cite a resolving {'/'.join(EXECUTABLE_PREFIXES)} reference"
                )
        if r.status == "pending":
            if not r.gap:
                errors.append(f"{where}: pending needs a gap id (an owner and the change)")
            elif r.gap.startswith("G-") and r.gap not in gaps:
                errors.append(f"{where}: gap {r.gap} is not defined under '## Gaps'")
            elif not r.gap.startswith("G-") and r.gap not in backlog:
                errors.append(f"{where}: gap {r.gap} is in no backlog row")
    return errors


def render_prevention(rows: list[Prevention], gaps: dict[str, str]) -> list[str]:
    """The register's section of GAP-ANALYSIS.md: the counts, then every pending row."""
    closed = [r for r in rows if r.status == "closed"]
    pending = [r for r in rows if r.status == "pending"]
    by_level = ", ".join(
        f"{lvl} {sum(1 for r in closed if r.level == lvl)}"
        for lvl in PREVENTION_LEVELS
        if any(r.level == lvl for r in closed)
    )
    out = [
        "## Our own bugs — the prevention register",
        "",
        f"**{len(rows)} registered · {len(closed)} closed ({by_level or 'none'}) · "
        f"{len(pending)} pending.** A defect is closed only with the artefact that fails if its "
        "class recurs (`docs/dod/STANDARD.md` §7); the register is `docs/PREVENTION.md`.",
        "",
    ]
    if pending:
        out += [
            "| id | bug | level | gap | what is missing |",
            "|---|---|---|---|---|",
            *(
                f"| {r.id} | {r.bug} | {r.level} | {r.gap} | {gaps.get(r.gap, '')} |"
                for r in pending
            ),
            "",
        ]
    return out


# ------------------------------------------------------------------ validation + roll-up


def app_routes() -> list[str]:
    if not APP.is_file():
        return []
    return [
        m.group(1) for m in re.finditer(r'<Route\s+path="([^"]+)"', APP.read_text(encoding="utf-8"))
    ]


def journey_steps() -> list[str]:
    if not LAYOUT.is_file():
        return []
    text = LAYOUT.read_text(encoding="utf-8")
    block = text.split("JOURNEY_STEPS", 1)[-1].split("]", 1)[0]
    return re.findall(r"to:\s*'([^']+)'", block)


def route_slug(route: str) -> str:
    s = route.strip("/").replace("/", "-").replace(":", "").replace("*", "not-found")
    return s or "root"


def validate(arts: list[Artefact]) -> list[str]:
    errors: list[str] = []
    by_id = {a.id: a for a in arts}
    backlog = backlog_index()
    # A gap id names one piece of work: the same id in two files must carry the same line,
    # or the ranked list cannot be grouped, counted or spoken about.
    defined: dict[str, tuple[str, str]] = {}
    for a in arts:
        for gid, text in a.gaps.items():
            norm = " ".join(text.split())
            first = defined.setdefault(gid, (norm, a.rel))
            if first[0] != norm:
                errors.append(
                    f"{a.rel}: gap {gid} is defined differently in {first[1]} — "
                    "one id is one piece of work; renumber or make the two lines identical"
                )
    seen_crit: set[str] = set()
    for a in arts:
        if not _ART_ID_RE.match(a.id):
            errors.append(f"{a.rel}: bad id {a.id!r}")
        if a.level not in LEVELS:
            errors.append(f"{a.rel}: level must be one of {LEVELS}")
            continue
        expected_dir = "product.md" if a.level == "product" else f"{LEVEL_DIR[a.level]}/"
        if expected_dir not in a.rel:
            errors.append(f"{a.rel}: a {a.level} artefact lives under docs/dod/{expected_dir}")
        for key in ("scope", "persons", "owner", "updated"):
            if not a.front.get(key):
                errors.append(f"{a.rel}: front matter needs {key}")
        parent = a.front.get("parent", "")
        if a.level == "product":
            if parent not in ("", "—", "-"):
                errors.append(f"{a.rel}: the product has no parent")
        elif parent not in by_id:
            errors.append(f"{a.rel}: parent {parent!r} is not an artefact")
        elif a.id not in by_id[parent].list_field("children"):
            errors.append(f"{a.rel}: parent {parent} does not list it under children")
        for child in a.list_field("children"):
            if child not in by_id:
                errors.append(f"{a.rel}: child {child!r} is not an artefact")
            elif by_id[child].front.get("parent") != a.id:
                errors.append(f"{a.rel}: child {child} names a different parent")
        cats = set(COMMON) | set(EXTRA[a.level])
        present = {c.category for c in a.criteria}
        for cat in cats - present:
            errors.append(
                f"{a.rel}: no criterion for category {cat} (mark n/a with a reason if it does not apply)"
            )
        if not a.criteria:
            errors.append(f"{a.rel}: no criteria table under '## Definition of done'")
        elif a.level == "product" and "VALUE" in present and a.criteria[0].category != "VALUE":
            # the value the product exists to deliver heads its definition of done
            errors.append(
                f"{a.rel}: the product's VALUE criteria come first — move them to the top "
                "of the table (STANDARD.md §4)"
            )
        cited = {c.gap for c in a.criteria}
        for gid in a.gaps:
            if gid not in cited:
                errors.append(
                    f"{a.rel}: gap {gid} is defined but no criterion in this file cites it — "
                    "delete the line if its work is closed, or cite it from the criterion it "
                    "blocks (a line nothing cites never reaches the order of work)"
                )
        for c in a.criteria:
            where = f"{a.rel}:{c.line}"
            if not _ID_RE.match(c.id):
                errors.append(f"{where}: criterion id {c.id!r} must be <scope>.<category>.<n>")
            if c.id in seen_crit:
                errors.append(f"{where}: duplicate criterion id {c.id}")
            seen_crit.add(c.id)
            if c.category not in cats:
                errors.append(f"{where}: unknown category {c.category!r} for a {a.level}")
            if c.state not in STATES:
                errors.append(f"{where}: state must be one of {STATES}, got {c.state!r}")
            resolve(c)
            for ref in c.unresolved:
                errors.append(f"{where}: evidence does not resolve: {ref}")
            refs = split_refs(c.evidence)
            if refs and all(r.startswith("measured:") for r in refs):
                errors.append(f"{where}: a measured: reference must sit beside a resolvable one")
            if c.state == "met" and not refs:
                errors.append(f"{where}: met needs evidence")
            if c.state in ("partial", "unmet"):
                if not c.gap:
                    errors.append(f"{where}: {c.state} needs a gap id")
                elif not _GAP_RE.match(c.gap):
                    errors.append(f"{where}: gap {c.gap!r} must be G-nnn or an F-/B- backlog id")
                elif c.gap.startswith("G-") and c.gap not in a.gaps:
                    errors.append(f"{where}: gap {c.gap} is not defined under '## Gaps'")
                elif not c.gap.startswith("G-") and c.gap not in backlog:
                    errors.append(
                        f"{where}: gap {c.gap} is in no backlog row under "
                        "docs/reviews/2026-09-17-enterprise-front-end.md §9"
                    )
            if c.state == "n/a" and not c.gap:
                errors.append(f"{where}: n/a needs a one-line reason in the gap column")
    # coverage
    page_scopes = {a.front.get("scope") for a in arts if a.level == "page"}
    for route in app_routes():
        if route not in page_scopes:
            errors.append(
                f"ui/src/App.tsx: route {route} has no page artefact (docs/dod/pages/{route_slug(route)}.md)"
            )
    journey_scopes = {a.front.get("scope") for a in arts if a.level == "journey"}
    journey_pages = {p for a in arts if a.level == "journey" for p in a.list_field("children")}
    for step in journey_steps():
        slug = route_slug(step)
        if f"dod.page.{slug}" not in journey_pages and step not in journey_scopes:
            errors.append(
                f"ui/src/components/Layout.tsx: JOURNEY_STEPS entry {step} belongs to no journey"
            )
    if "dod.product" not in by_id:
        errors.append("docs/dod/product.md is missing")
    return errors


def roll_up(arts: list[Artefact]) -> None:
    by_id = {a.id: a for a in arts}
    order = {"page": 0, "journey": 1, "stream": 2, "product": 3}
    for a in sorted(arts, key=lambda x: order.get(x.level, 9)):
        own = all(c.effective_state in ("met", "n/a") for c in a.criteria) and bool(a.criteria)
        kids = [by_id[k] for k in a.list_field("children") if k in by_id]
        missing_kids = [k for k in a.list_field("children") if k not in by_id]
        kids_done = all(k.status == "done" for k in kids) and not missing_kids
        a.status = "done" if own and kids_done else "partial"


# ------------------------------------------------------------------ the plan and retired ids

_ANY_GAP_ID = re.compile(r"\bG-\d{3}\b|\bF\d+[a-z]?\b|\bB-\d+[a-z]?\b")
RETIRED_HEAD = "## Gap ids retired"
_FANOUT_HEAD = "## Open gaps by fan-out"
_REGISTER_HEAD = "## Our own bugs"


def _gap_key(gid: str) -> tuple[str, int, str]:
    digits = re.sub(r"\D", "", gid)
    return (gid[0], int(digits) if digits else 0, gid)


def previous_ids(text: str) -> tuple[set[str], set[str]]:
    """(the ids the previous gap analysis carried as open work, the ids it had retired).

    Open work is the first cell of each *Open gaps by fan-out* row and the gap cell of each
    pending register row — ids the checker itself validated when it wrote them, so a typo can
    never reach this list. The retired list is read back from its own section.
    """
    open_ids: set[str] = set()
    retired: set[str] = set()
    section = ""
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("## "):
            section = s
            continue
        if section.startswith(RETIRED_HEAD):
            retired.update(_ANY_GAP_ID.findall(s))
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if section.startswith(_FANOUT_HEAD) and cells and _GAP_RE.match(cells[0]):
            open_ids.add(cells[0])
        elif section.startswith(_REGISTER_HEAD) and len(cells) > 3 and _GAP_RE.match(cells[3]):
            open_ids.add(cells[3])
    return open_ids, retired


def retired_ids(previous: str, defined: set[str]) -> list[str]:
    """Every id the order of work once carried that nothing defines any more — closed, or
    merged into another id. It only grows (an id defined again leaves it), so a wave that
    closes a gap never breaks the plan that named it.

    It is carried forward from the previous gap analysis; ``main`` keeps only the ids that
    ``history_gap_ids`` or ``base_gap_analysis_ids`` vouch for, so that file never vouches
    for itself."""
    open_ids, retired = previous_ids(previous)
    return sorted((open_ids | retired) - defined, key=_gap_key)


#: Where a gap id is defined or cited by hand: the artefacts and the register — never the
#: generated gap analysis, the plan or the standard's examples.
HISTORY_PATHS: tuple[str, ...] = (
    "docs/dod/pages",
    "docs/dod/journeys",
    "docs/dod/streams",
    "docs/dod/product.md",
    "docs/PREVENTION.md",
)
_HIST_GAP_LINE = re.compile(r"^\+\s*- \*\*(G-\d{3}|F\d+[a-z]?|B-\d+[a-z]?)\*\*\s*\u2014")
#: The branch whose committed gap analysis is trusted, when ``--base`` is not given.
DEFAULT_BASE = "origin/main"


def _git(root: Path, *args: str) -> str | None:
    """``git -C root …``'s stdout, or None when git fails or is missing."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _own_work_tree(root: Path) -> bool:
    """True only when ``root`` is itself the top of a git work tree. ``git -C`` walks up to the
    nearest repository, and a parent's history must never vouch for this tree's ids."""
    top = _git(root, "rev-parse", "--show-toplevel")
    return top is not None and Path(top.strip()).resolve() == root.resolve()


def history_gap_ids(root: Path) -> set[str]:
    """Every gap id that a commit reachable from ``HEAD`` added to an artefact or the register:
    a gap line (``- **G-nnn** — …``), or the gap cell of a criterion or pending register row
    (the only way a backlog ``F``/``B`` id becomes a gap). Merges are read against their first
    parent, so a line written while resolving a merge counts too. Empty when ``root`` is not
    its own work tree or has no commits."""
    if not _own_work_tree(root):
        return set()
    log = _git(
        root,
        "log",
        "-p",
        "--no-color",
        "--no-ext-diff",
        "--diff-merges=first-parent",
        "--format=",
        "HEAD",
        "--",
        *HISTORY_PATHS,
    )
    ids: set[str] = set()
    for line in (log or "").split("\n"):
        m = _HIST_GAP_LINE.match(line)
        if m:
            ids.add(m.group(1))
        elif line.startswith("+|"):
            cells = [c.strip() for c in line[1:].strip().strip("|").split("|")]
            if cells and _GAP_RE.match(cells[-1]):
                ids.add(cells[-1])
    return ids


def base_gap_analysis_ids(root: Path, base: str) -> set[str]:
    """The ids — open or retired — in the gap analysis committed at the merge-base of ``HEAD``
    and ``base``. That file passed this check on the pull request that wrote it, and it is
    where an id opened and closed inside a squash-merged branch survives (the squash drops the
    branch's own artefact commits). Empty when the base does not resolve."""
    if not _own_work_tree(root):
        return set()
    mb = _git(root, "merge-base", "HEAD", base)
    if mb is None:
        return set()
    rel = (
        OUT.relative_to(root).as_posix() if OUT.is_relative_to(root) else "docs/dod/GAP-ANALYSIS.md"
    )
    text = _git(root, "show", f"{mb.strip()}:{rel}")
    if text is None:
        return set()
    open_ids, retired = previous_ids(text)
    return open_ids | retired


def validate_retired(bad: list[str], base: str, root: Path) -> list[str]:
    """A retired id must have been a gap somewhere a person wrote it: in the artefacts' own
    history, or in the base branch's committed gap analysis. The generated file cannot vouch
    for itself: ``bad`` are the ids it carries that nothing else vouches for — the generator
    drops them, and ``--check`` names each one."""
    if not bad:
        return []
    hint = ""
    if not _own_work_tree(root):
        hint = " (this tree is not a git work tree, so no history can vouch for any id)"
    elif (_git(root, "rev-parse", "--is-shallow-repository") or "").strip() == "true":
        hint = " (the clone is shallow: fetch the full history, e.g. fetch-depth: 0)"
    return [
        f"docs/dod/GAP-ANALYSIS.md retires {gid}, but no artefact or register row in the git "
        f"history ever defined it and the gap analysis at the merge-base with {base} never "
        f"carried it{hint} — the list is generated: never edit docs/dod/GAP-ANALYSIS.md by "
        "hand; restore it (git checkout) and run scripts/dod_check.py"
        for gid in bad
    ]


def validate_plan_covers_the_top(
    ranked_gaps: list[str], items: list[tuple[int, str]], top: int = TOP
) -> list[str]:
    """STANDARD.md §6: the plan batches the order of work, so every gap among its first
    ``top`` rows is in some wave (the plan once left rank 1, G-653, in none)."""
    planned = {gid for _n, gid in items}
    errors: list[str] = []
    seen: set[str] = set()
    for rank, gid in enumerate(ranked_gaps[:top], start=1):
        if not gid or gid in planned or gid in seen:
            continue
        seen.add(gid)
        errors.append(
            f"docs/dod/PLAN.md: gap {gid} is rank {rank} in the order of work but in no wave — "
            "add it to the wave that will close it"
        )
    return errors


def plan_items(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    """``(line, id)`` for every wave item in PLAN.md: each id in the ``gaps`` column of any
    table that has one. A cell holds gap ids separated by commas and nothing else — the
    plan batches the order of work; it does not restate it."""
    if not path.is_file():
        return [], [
            "docs/dod/PLAN.md is missing — the batching of the order of work (STANDARD.md §6)"
        ]
    items: list[tuple[int, str]] = []
    errors: list[str] = []
    col: int | None = None
    tables = 0
    for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        s = line.strip()
        if not s.startswith("|"):
            col = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if col is None:
            low = [c.lower() for c in cells]
            col = low.index("gaps") if "gaps" in low else -1
            tables += col >= 0
            continue
        if col < 0 or all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        cell = cells[col] if col < len(cells) else ""
        tokens = [t.strip().strip("`") for t in cell.split(",")]
        for tok in tokens:
            if _GAP_RE.match(tok):
                items.append((n, tok))
            else:
                errors.append(f"docs/dod/PLAN.md:{n}: a wave item is a gap id, not {tok!r}")
    if not tables:
        errors.append("docs/dod/PLAN.md names no wave item — no table has a 'gaps' column")
    return items, errors


def validate_plan(items: list[tuple[int, str]], known: set[str]) -> list[str]:
    """PLAN.md's rule, as a gate: nothing enters a wave that is not a gap id.

    ``known`` is every gap the record defines — an artefact's gap line, a register gap, a
    backlog row a criterion or a pending row cites (a row nothing cites asks for no work) —
    plus the ids the order of work has retired."""
    return [
        f"docs/dod/PLAN.md:{n}: wave item {gid} is not a gap id defined under docs/dod "
        "(an artefact's gap line, a register gap, or a backlog row a criterion or a pending "
        "row cites), nor one the order of work has retired — fix the artefact first (add the "
        "criterion and its gap), then plan it"
        for n, gid in items
        if gid not in known
    ]


# ------------------------------------------------------------------ rendering


def _open(arts: list[Artefact]) -> list[tuple[Artefact, Criterion]]:
    return [(a, c) for a in arts for c in a.criteria if c.effective_state in ("partial", "unmet")]


def blocked_by_gap(arts: list[Artefact]) -> dict[str, int]:
    """How many open criteria across the whole tree each gap id blocks."""
    counts: dict[str, int] = {}
    for _a, c in _open(arts):
        if c.gap:
            counts[c.gap] = counts.get(c.gap, 0) + 1
    return counts


def _state_factor(category: str, state: str) -> int:
    """`unmet` is always double; in the honesty categories so is `partial`.

    "Built wrong" is not a lesser defect than "not built" where the criterion is about
    telling the truth — a screen that presents a fallback as an answer is the defect class
    this product exists to refuse.
    """
    if state == "unmet" or category in HONESTY:
        return 2
    return 1


def _rank(arts: list[Artefact]) -> list[tuple[int, int, Artefact, Criterion]]:
    """(score, fan-out, artefact, criterion), highest first.

    ``score`` is STANDARD.md §5's formula: level weight × criteria blocked × category
    severity, with the state factor. The fan-out factor is what finds the shared blocker —
    the single change that closes the most criteria in the tree — and is capped at 3 so one
    widely-cited gap cannot bury everything else.
    """
    counts = blocked_by_gap(arts)
    rows: list[tuple[int, int, Artefact, Criterion]] = []
    for a, c in _open(arts):
        fan = counts.get(c.gap, 1)
        score = (
            LEVEL_WEIGHT.get(a.level, 1)
            * WEIGHT.get(c.category, 1)
            * min(fan, 3)
            * _state_factor(c.category, c.effective_state)
        )
        rows.append((score, fan, a, c))
    rows.sort(key=lambda r: (-r[0], -r[1], -LEVEL_WEIGHT.get(r[2].level, 1), r[2].id, r[3].id))
    return rows


def render(
    arts: list[Artefact],
    register: tuple[list[Prevention], dict[str, str]] | None = None,
    retired: list[str] | None = None,
) -> str:
    by_level: dict[str, list[Artefact]] = {lvl: [] for lvl in LEVELS}
    for a in arts:
        by_level.setdefault(a.level, []).append(a)
    total = len(arts)
    done = sum(1 for a in arts if a.status == "done")
    crit = [c for a in arts for c in a.criteria]
    met = sum(1 for c in crit if c.effective_state == "met")
    na = sum(1 for c in crit if c.effective_state == "n/a")
    out = [
        "# Gap analysis — generated from the definition-of-done artefacts",
        "",
        "<!-- generated by scripts/dod_check.py — do not edit; edit the artefacts under docs/dod/ -->",
        "",
        f"**{done} of {total} artefacts done · {met} of {len(crit)} criteria met, {na} n/a, "
        f"{len(crit) - met - na} open.** A level is done only when its children are done and its own "
        "criteria are met (`docs/dod/STANDARD.md` §5). *The order of work* is the first "
        f"{TOP} open criteria, ranked; *Open gaps by fan-out* is the same work as one row per gap, "
        "so a change that closes eight criteria reads as one job.",
        "",
    ]
    for lvl in reversed(LEVELS):
        items = by_level.get(lvl, [])
        if not items:
            continue
        out += [
            f"## {lvl.capitalize()}s" if lvl != "product" else "## Product",
            "",
            "| artefact | name | status | met | open | n/a |",
            "|---|---|---|---|---|---|",
        ]
        for a in sorted(items, key=lambda x: x.id):
            m = sum(1 for c in a.criteria if c.effective_state == "met")
            n = sum(1 for c in a.criteria if c.effective_state == "n/a")
            o = len(a.criteria) - m - n
            out.append(
                f"| [{a.id}]({a.rel.removeprefix('docs/dod/')}) | {a.front.get('name', '')} | **{a.status}** | {m} | {o} | {n} |"
            )
        out.append("")
    backlog = backlog_index()
    gap_text: dict[str, str] = {}
    for a in arts:
        gap_text.update(a.gaps)

    def says(gap: str) -> str:
        if gap.startswith("G-"):
            return gap_text.get(gap, "")
        title, size = backlog.get(gap, ("", "—"))
        return f"backlog {gap} — {title} · {size}" if title else f"backlog {gap}"

    def owner_of(gap: str) -> str:
        if not gap.startswith("G-"):
            return "backlog"
        fields = gap_text.get(gap, "").split(" · ")
        return fields[-1].strip().rstrip(".") if len(fields) > 2 else "—"

    ranked = _rank(arts)
    head = "| rank | score | blocks | level | artefact | criterion | category | state | gap | what is missing |"
    rule = "|---|---|---|---|---|---|---|---|---|---|"
    out += [
        "## The order of work",
        "",
        f"The first {min(TOP, len(ranked))} of {len(ranked)} open criteria, by "
        "(level weight, the criteria this gap blocks, category severity and state). "
        "`blocks` is how many open criteria across the whole tree close with this one gap.",
        "",
        head,
        rule,
    ]
    for i, (score, fan, a, c) in enumerate(ranked[:TOP], start=1):
        out.append(
            f"| {i} | {score} | {fan} | {a.level} | {a.id} | {c.id} | {c.category} | "
            f"{c.effective_state} | {c.gap} | {says(c.gap)} |"
        )
    counts = blocked_by_gap(arts)
    levels: dict[str, set[str]] = {}
    for a, c in _open(arts):
        if c.gap:
            levels.setdefault(c.gap, set()).add(a.level)
    out += [
        "",
        "## Open gaps by fan-out",
        "",
        "One row per gap: the change, and how much of the tree it closes.",
        "",
        "| gap | criteria blocked | levels | owner | what is missing |",
        "|---|---|---|---|---|",
    ]
    for gap in sorted(counts, key=lambda g: (-counts[g], g)):
        touched = ", ".join(lvl for lvl in LEVELS if lvl in levels.get(gap, set()))
        out.append(f"| {gap} | {counts[gap]} | {touched} | {owner_of(gap)} | {says(gap)} |")
    out.append("")
    if register is not None:
        out += render_prevention(*register)
    if retired is not None:
        out += [
            RETIRED_HEAD,
            "",
            "Ids the order of work once carried that no artefact, register row or backlog row "
            "defines any more: each was closed, or merged into another id. `PLAN.md` may go on "
            "naming one; an id that was never a gap fails the check. Carried forward by the "
            "generator, and kept only while the git history of the artefacts, or the gap "
            "analysis committed on the base branch, shows the id was a gap — never because "
            "this file says so.",
            "",
            ", ".join(retired) if retired else "none",
            "",
        ]
    out += [
        "## Every open criterion, ranked",
        "",
        f"<details><summary>All {len(ranked)} open criteria</summary>",
        "",
        head,
        rule,
    ]
    for i, (score, fan, a, c) in enumerate(ranked, start=1):
        out.append(
            f"| {i} | {score} | {fan} | {a.level} | {a.id} | {c.id} | {c.category} | "
            f"{c.effective_state} | {c.gap} | {says(c.gap)} |"
        )
    out += ["", "</details>", ""]
    return "\n".join(out)


def stamp_status(arts: list[Artefact]) -> int:
    """Write each artefact's computed ``status:`` line; returns how many files changed."""
    changed = 0
    for a in arts:
        lines = a.path.read_text(encoding="utf-8").split("\n")
        if a.status_line is None:
            continue
        new = f"status: {a.status}                # WRITTEN BY THE CHECKER — never by hand"
        if lines[a.status_line] != new:
            lines[a.status_line] = new
            a.path.write_text("\n".join(lines), encoding="utf-8")
            changed += 1
    return changed


def status_drift(arts: list[Artefact]) -> list[str]:
    out: list[str] = []
    for a in arts:
        if a.front.get("status", "") != a.status:
            out.append(
                f"{a.rel}: status is {a.front.get('status', '')!r} but the roll-up says {a.status!r} — run scripts/dod_check.py"
            )
    return out


# ------------------------------------------------------------------ twins (P-116)

#: A clause shorter than this is common prose ("delivery is switched on"), not a twin.
TWIN_MIN_WORDS = 6
_CLAUSE_SPLIT = re.compile(r"[;:,.()\"\u201c\u201d\u2014]|\s-\s|\s\u00b7\s")


def _norm(text: str) -> str:
    return " ".join(text.replace("`", "").replace("*", "").lower().split())


def _clauses(text: str) -> set[str]:
    """The clauses of a criterion long enough to identify it, lower-cased and trimmed."""
    out: set[str] = set()
    for part in _CLAUSE_SPLIT.split(_norm(text)):
        words = part.split()
        while words and words[0] in ("and", "or", "that", "but", "so", "while"):
            words = words[1:]
        if len(words) >= TWIN_MIN_WORDS:
            out.add(" ".join(words))
    return out


def validate_twins(arts: list[Artefact], base: dict[str, str]) -> list[str]:
    """A clause that a reworded criterion drops must leave every other criterion too (P-116).

    ``base`` maps each criterion id to its words at the base. For every criterion whose words
    changed, each clause of its old words that its new words no longer hold is looked for in
    every other criterion; one that still says it is a twin left behind — two end states that
    cannot both hold — unless it waits on the same gap, which is the record saying the two
    change together. An empty ``base`` (no base branch to read) checks nothing."""
    errors: list[str] = []
    crits = [(a, c) for a in arts for c in a.criteria]
    for a, c in crits:
        old = base.get(c.id)
        if old is None or _norm(old) == _norm(c.text):
            continue
        now = _norm(c.text)
        dropped = sorted(cl for cl in _clauses(old) if cl not in now)
        for clause in dropped:
            for b, t in crits:
                if t.id == c.id or clause not in _norm(t.text):
                    continue
                if c.gap and t.gap == c.gap:
                    continue
                errors.append(
                    f'{b.rel}:{t.line}: {t.id} still says "{clause}", which '
                    f"{c.id} ({a.rel}) no longer says — reword it the same way, or have it "
                    f"wait on the same gap ({c.gap or 'none'}) and name it in that gap's line"
                )
    return errors


def base_criteria(root: Path, base: str) -> dict[str, str]:
    """Every criterion's words at the merge-base of ``HEAD`` and ``base``; empty when the base
    does not resolve or ``root`` is not its own work tree."""
    if not _own_work_tree(root):
        return {}
    mb = _git(root, "merge-base", "HEAD", base)
    if mb is None:
        return {}
    dod = DOD.relative_to(root).as_posix() if DOD.is_relative_to(root) else "docs/dod"
    listing = _git(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        mb.strip(),
        "--",
        *(f"{dod}/{sub}" for sub in LEVEL_DIR.values()),
        f"{dod}/product.md",
    )
    out: dict[str, str] = {}
    for rel in (listing or "").split():
        if not rel.endswith(".md"):
            continue
        text = _git(root, "show", f"{mb.strip()}:{rel}")
        if text is None:
            continue
        art, _errs = parse_artefact(root / rel, text)
        out.update({c.id: c.text for c in art.criteria})
    return out


# ------------------------------------------------------------------ provisional values (P-117)

_OPERATOR_RE = re.compile(r"\[operator\b")
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z]+)", re.M)
_OPERATOR_SECTION = "## Operator values"


def operator_values(adr_dir: Path) -> tuple[dict[str, tuple[bool, list[str]]], list[str]]:
    """Each ADR that leaves values to the operator: ``{number: (proposed, phrases)}``.

    A Proposed ADR that marks a value **[operator]** registers every such value in a
    ``## Operator values`` table whose last cell gives, in backticks, the words a criterion
    states it in; the table has one row per marker in the ADR's body (its Status line and the
    table's own section aside), so a marker cannot go unregistered."""
    out: dict[str, tuple[bool, list[str]]] = {}
    errors: list[str] = []
    if not adr_dir.is_dir():
        return out, errors
    for path in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        text = path.read_text(encoding="utf-8")
        number = path.name[:4]
        status = _STATUS_RE.search(text)
        proposed = status is not None and status.group(1).lower() == "proposed"
        body, _, section = text.partition(_OPERATOR_SECTION)
        section = section.split("\n## ", 1)[0]
        markers = sum(
            len(_OPERATOR_RE.findall(line))
            for line in body.split("\n")
            if not line.startswith("**Status:**")
        )
        rows = [
            ln
            for ln in section.split("\n")
            if ln.startswith("|") and not ln.startswith("| item") and not ln.startswith("|---")
        ]
        phrases = [
            p.lower() for ln in rows for p in re.findall(r"`([^`]+)`", ln.strip("|").split("|")[-1])
        ]
        if proposed and markers and not section:
            errors.append(
                f"docs/adr/{path.name}: {markers} [operator] markers and no '{_OPERATOR_SECTION}' "
                "table — register each value with the words a criterion states it in"
            )
        elif proposed and section and markers != len(rows):
            errors.append(
                f"docs/adr/{path.name}: {markers} [operator] markers but {len(rows)} rows under "
                f"'{_OPERATOR_SECTION}' — one row per value the operator fixes"
            )
        if section or markers:
            out[number] = (proposed, phrases)
    return out, errors


def validate_operator_values(arts: list[Artefact], adr_dir: Path) -> list[str]:
    """A criterion or gap line that states a value a Proposed ADR leaves to the operator
    carries ``ADR-nnnn [operator]``; once the ADR is accepted the marker must go (P-117)."""
    values, errors = operator_values(adr_dir)
    for a in arts:
        texts = [(f"{a.rel}:{c.line}: {c.id}", c.text) for c in a.criteria]
        texts += [(f"{a.rel}: gap {gid}", body) for gid, body in a.gaps.items()]
        for where, text in texts:
            low = text.lower()
            for number, (proposed, phrases) in values.items():
                mark = f"adr-{number} [operator]"
                if proposed:
                    said = [p for p in phrases if p in low]
                    if said and mark not in low:
                        errors.append(
                            f'{where} states "{said[0]}", a value ADR-{number} leaves to the '
                            f"operator — say so on the row (ADR-{number} [operator] values; the "
                            "row follows the operator's choice)"
                        )
                elif mark in low:
                    errors.append(
                        f"{where} still marks ADR-{number} [operator], but the ADR is accepted "
                        "— state the value the operator fixed and drop the marker"
                    )
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="validate and fail on any defect or drift; write nothing",
    )
    ap.add_argument(
        "--base",
        default=os.environ.get("DOD_BASE") or DEFAULT_BASE,
        help="the branch whose committed gap analysis may vouch for a retired id "
        f"(default $DOD_BASE, else {DEFAULT_BASE}; CI sets DOD_BASE to the pull request's base)",
    )
    args = ap.parse_args(argv)
    arts: list[Artefact] = []
    errors: list[str] = []
    for path in artefact_files():
        a, errs = parse_artefact(path)
        arts.append(a)
        errors.extend(errs)
    errors.extend(validate(arts))
    errors.extend(validate_operator_values(arts, ADR_DIR))
    errors.extend(validate_twins(arts, base_criteria(ROOT, args.base)))
    prevention, pgaps, perrs = parse_prevention(PREVENTION)
    errors.extend(perrs)
    backlog = backlog_index()
    errors.extend(validate_prevention(prevention, pgaps, backlog))
    pending_gaps = {r.gap for r in prevention if r.status == "pending"}
    for gid in pgaps:
        if gid not in pending_gaps:
            errors.append(
                f"docs/PREVENTION.md: gap {gid} is defined but no pending row cites it — "
                "delete the line when its row closes"
            )
    # one gap id is one piece of work across the register AND the artefacts
    art_gaps = {gid: " ".join(t.split()) for a in arts for gid, t in a.gaps.items()}
    for gid, text in pgaps.items():
        if gid in art_gaps and art_gaps[gid] != " ".join(text.split()):
            errors.append(f"docs/PREVENTION.md: gap {gid} is defined differently in an artefact")
    # a backlog row is a gap of the record only while a criterion or a pending row cites it
    cited_rows = {c.gap for a in arts for c in a.criteria} | pending_gaps
    defined = {g for a in arts for g in a.gaps} | set(pgaps) | (set(backlog) & cited_rows)
    previous = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
    carried = retired_ids(previous, defined)
    # the previous file cannot vouch for itself: an id stays retired only while the artefacts'
    # history or the base's committed gap analysis shows it was a gap (P-060)
    vouched = history_gap_ids(ROOT) | base_gap_analysis_ids(ROOT, args.base)
    retired = [gid for gid in carried if gid in vouched]
    unvouched = validate_retired([g for g in carried if g not in vouched], args.base, ROOT)
    items, plan_errors = plan_items(PLAN)
    errors.extend(plan_errors)
    errors.extend(validate_plan(items, defined | set(retired)))
    if args.check:
        errors.extend(unvouched)
    else:
        for note in unvouched:
            print(f"dropped from the retired list: {note}")
    roll_up(arts)
    if PLAN.is_file():
        ranked_gaps = [c.gap for _s, _f, _a, c in _rank(arts)]
        errors.extend(validate_plan_covers_the_top(ranked_gaps, items))
    rendered = render(arts, (prevention, pgaps), retired)
    if args.check:
        errors.extend(status_drift(arts))
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != rendered:
            errors.append(
                "docs/dod/GAP-ANALYSIS.md is out of date — run scripts/dod_check.py and commit it"
            )
        for e in errors:
            print(e)
        if errors:
            print(f"{len(errors)} defect(s)")
            return 1
        print(
            f"dod: {len(arts)} artefacts, {sum(len(a.criteria) for a in arts)} criteria, gap analysis current"
        )
        return 0
    for e in errors:
        print(e)
    n = stamp_status(arts)
    OUT.write_text(rendered, encoding="utf-8")
    print(
        f"wrote docs/dod/GAP-ANALYSIS.md: {len(arts)} artefacts; {n} status line(s) updated; {len(errors)} defect(s)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
