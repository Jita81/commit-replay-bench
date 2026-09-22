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
without a resolvable evidence reference, ``partial``/``unmet`` without a gap id, or a gap id
defined nowhere; an evidence reference that does not resolve; and a ``GAP-ANALYSIS.md`` or a
``status:`` line that differs from what the artefacts generate. It never edits a criterion.

Navigation
----------
What it is:   The definition-of-done checker and gap-analysis generator (stdlib only; CI's
              ``dod`` job runs ``--check``).
What it does: Parses every artefact under docs/dod/, validates ids, categories, states, gaps
              and parent/child links, resolves each typed evidence reference against the tree
              (tests, vitest titles, walkthrough specs, hint registry and ratchet, API routes,
              code symbols, doc anchors, CI jobs, ADRs, decision-log rows), computes the
              four-level roll-up and writes docs/dod/GAP-ANALYSIS.md; --check exits non-zero
              on any defect or drift.
How:          Walk docs/dod/{pages,journeys,streams}/*.md + product.md → parse front matter
              and the criteria table → resolve evidence (one resolver per prefix) → demote
              ``met`` with no resolving reference → roll up child → parent → render.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/dod/STANDARD.md (the format it enforces), docs/dod/GAP-ANALYSIS.md (its
              output), ui/src/App.tsx (the routes every page artefact must cover),
              ui/src/components/Layout.tsx (JOURNEY_STEPS), ui/src/help/hints.ts and
              hints-ratchet*.tsx (hint: references), docs/API.md (route: references),
              .github/workflows/ci.yml (the dod job that runs --check)
Tested by:    tests/test_dod_check.py
Touch when:   a level or category is added to the standard (update CATEGORIES / LEVELS and the
              standard together); a new evidence prefix is needed (add a resolver and a row to
              STANDARD.md §3); a route or journey step is added (write its artefact — the
              check tells you which).
"""

from __future__ import annotations

import argparse
import re
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
ADR_DIR = ROOT / "docs" / "adr"

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
    "product": ("IDENTITY", "GO-LIVE", "CLAIMS", "RELEASE", "POSTURE", "SUPPORT", "EXTENSIBILITY"),
}
#: Category weight for the gap ranking — what blocks a governance reviewer outranks polish.
WEIGHT: dict[str, int] = {
    "TRUTH": 5,
    "ROLES": 5,
    "GO-LIVE": 5,
    "CLAIMS": 5,
    "POSTURE": 5,
    "EVIDENCE": 4,
    "PROOF": 4,
    "OUTCOME": 4,
    "AUTOMATION": 4,
    "HANDOFF": 4,
    "ACTIONS": 3,
    "RECOVERY": 3,
    "OPERATIONS": 3,
    "MEASURE": 3,
    "TRIGGER": 3,
    "STEPS": 3,
    "EXPLANATION": 2,
    "ACCESSIBILITY": 2,
    "ENTRY-EXIT": 2,
    "PURPOSE": 1,
    "TIME-COST": 1,
    "NON-GOALS": 1,
    "IDENTITY": 1,
    "RELEASE": 2,
    "SUPPORT": 2,
    "EXTENSIBILITY": 3,
}
LEVEL_WEIGHT: dict[str, int] = {"product": 4, "stream": 3, "journey": 2, "page": 1}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.[a-z-]+\.\d+$")
_GAP_RE = re.compile(r"^(G-\d{3}|F\d+[a-z]?|B-\d+[a-z]?)$")
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


def parse_artefact(path: Path) -> tuple[Artefact, list[str]]:
    errors: list[str] = []
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
            m = re.match(r"^- \*\*(G-\d{3})\*\*\s*[—-]\s*(.+)$", s)
            if m:
                gaps[m.group(1)] = m.group(2)
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
    rel, _, symbol = ref.partition("::")
    p = _file(rel)
    if p is None:
        return False
    if not symbol:
        return True
    text = p.read_text(encoding="utf-8")
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
    h = heading.strip().lower()
    h = re.sub(r"[`*_]", "", h)
    h = re.sub(r"[^\w\s-]", "", h)
    return re.sub(r"\s+", "-", h.strip())


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


def split_refs(evidence: str) -> list[str]:
    """References are separated by ` · ` or `;`; a `measured:` reference may contain anything."""
    if evidence.strip() in ("", "absent"):
        return []
    parts = re.split(r"\s·\s|;\s*", evidence)
    return [p.strip().strip("`") for p in parts if p.strip()]


def resolve(criterion: Criterion) -> None:
    for ref in split_refs(criterion.evidence):
        prefix, _, rest = ref.partition(":")
        if prefix == "measured":
            continue  # never resolved; allowed only beside another reference
        fn = RESOLVERS.get(prefix)
        if fn is not None and fn(rest):
            criterion.resolved.append(ref)
        else:
            criterion.unresolved.append(ref)


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


# ------------------------------------------------------------------ rendering


def _rank(arts: list[Artefact]) -> list[tuple[int, Artefact, Criterion]]:
    rows: list[tuple[int, Artefact, Criterion]] = []
    for a in arts:
        for c in a.criteria:
            if c.effective_state in ("partial", "unmet"):
                score = (
                    LEVEL_WEIGHT.get(a.level, 1)
                    * WEIGHT.get(c.category, 1)
                    * (2 if c.effective_state == "unmet" else 1)
                )
                rows.append((score, a, c))
    rows.sort(key=lambda r: (-r[0], r[1].id, r[2].id))
    return rows


def render(arts: list[Artefact]) -> str:
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
        "criteria are met (`docs/dod/STANDARD.md` §5). The ranked list is the order of work: the first "
        "line unblocks the most done.",
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
    out += [
        "## Open gaps, ranked",
        "",
        "| rank | score | level | artefact | criterion | category | state | gap | what is missing |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, (score, a, c) in enumerate(_rank(arts), start=1):
        what = a.gaps.get(c.gap, "") if c.gap.startswith("G-") else f"backlog {c.gap}"
        out.append(
            f"| {i} | {score} | {a.level} | {a.id} | {c.id} | {c.category} | {c.effective_state} | {c.gap} | {what} |"
        )
    out.append("")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="validate and fail on any defect or drift; write nothing",
    )
    args = ap.parse_args(argv)
    arts: list[Artefact] = []
    errors: list[str] = []
    for path in artefact_files():
        a, errs = parse_artefact(path)
        arts.append(a)
        errors.extend(errs)
    errors.extend(validate(arts))
    roll_up(arts)
    rendered = render(arts)
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
