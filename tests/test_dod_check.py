"""The definition-of-done checker: artefacts are validated, evidence must resolve, the roll-up
is mechanical, and the gap analysis is generated — never hand-written.

Navigation
----------
What it is:   The test suite for scripts/dod_check.py, on a throwaway repository tree.
What it does: Pins that a well-formed artefact tree passes; that ``met`` without resolving
              evidence is demoted to ``partial`` and reported; that ``partial``/``unmet`` need
              a defined gap; that every ``App.tsx`` route and ``JOURNEY_STEPS`` entry needs an
              artefact; that parent/child links must agree; that the roll-up makes a journey
              ``partial`` while a child page is; that every evidence prefix resolves against
              the real file shapes (test defs, vitest/spec titles, ratchet SCREENS keys,
              help.ts routes, hint ids, API.md rows, code symbols, doc anchors, CI jobs, ADRs,
              decision-log rows) while a quoted title containing " · " stays one reference;
              that a gap line must name the change and a known owner layer, that one gap id
              carries one line across the tree, and that an F-/B- id must be a row of the
              ordered backlog and is named in the ranking; that the rank counts how many
              criteria a gap blocks and doubles a `partial` in the honesty categories; that
              ``--check`` fails on a stale GAP-ANALYSIS.md; and that the prevention register
              (docs/PREVENTION.md) must exist and refuses an entry closed without an
              executable artefact that resolves, an advisory closure, a pending entry with no
              gap, an unknown level or status, a duplicate id and a missing first-seen.
How:          Builds a minimal tree under ``tmp_path`` (App.tsx, Layout.tsx, hints.ts, help.ts,
              a ratchet file, API.md, ci.yml, a test file, a spec, an ADR, the decision log),
              points the module's path constants at it with ``monkeypatch``, and calls
              ``main([...])`` in-process.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/dod_check.py (under test), docs/dod/STANDARD.md (the format),
              docs/dod/TEMPLATE.md (the shape the fixtures copy)
Tested by:    (this is a test file)
Touch when:   a category, level or evidence prefix is added to the standard — add the fixture
              and the assertion here in the same change.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dod_check", ROOT / "scripts" / "dod_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dod_check"] = mod
    spec.loader.exec_module(mod)
    return mod


PAGE = """---
id: dod.page.results
level: page
name: Baseline
scope: /results
parent: dod.journey.read-the-map
children: []
persons: [viewer]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Baseline

**Purpose.** The map.

**Entry → exit.** Nav → Decisions.

**Non-goals.** Not a report.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| results.purpose.1 | PURPOSE | About block | `hint:about:/results` | met | |
| results.entry-exit.2 | ENTRY-EXIT | Next step | `code:ui/src/App.tsx::App` | met | |
| results.truth.3 | TRUTH | n on every rate | `vitest:ui/src/screens/Results/MapTable.test.tsx::"every cell carries n"` | met | |
| results.actions.4 | ACTIONS | Open a cell | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"viewer @ 375"` | met | |
| results.explanation.5 | EXPLANATION | Ratchet | `hint:ratchet:/results` · `hint:id:tile.results.n` | met | |
| results.evidence.6 | EVIDENCE | Tested | `test:tests/test_x.py::test_one` | met | |
| results.roles.7 | ROLES | Viewer reads | `route:GET /health` | met | |
| results.operations.8 | OPERATIONS | Documented | `doc:docs/OPERATOR.md#5-sign-off` · `ci:code-map` | met | |
| results.accessibility.9 | ACCESSIBILITY | axe | `adr:0016` · `dl:DL-047` | met | |
| results.non-goals.10 | NON-GOALS | Stated | absent | {NG_STATE} | {NG_GAP} |

## Gaps
- **G-001** — non-goals not on the About block · add one sentence · ui
"""

JOURNEY = """---
id: dod.journey.read-the-map
level: journey
name: Read the map
scope: read-the-map
parent: dod.stream.measure
children: [dod.page.results]
persons: [viewer]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Read the map

**Purpose.** See the baseline.

**Entry → exit.** Home → Decisions.

**Non-goals.** None.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
{ROWS}

## Gaps
"""

STREAM = (
    JOURNEY.replace("dod.journey.read-the-map", "dod.stream.measure")
    .replace("level: journey", "level: stream")
    .replace("scope: read-the-map", "scope: measure")
    .replace("parent: dod.stream.measure", "parent: dod.product")
    .replace("children: [dod.page.results]", "children: [dod.journey.read-the-map]")
)
PRODUCT = (
    JOURNEY.replace("dod.journey.read-the-map", "dod.product")
    .replace("level: journey", "level: product")
    .replace("scope: read-the-map", "scope: product")
    .replace("parent: dod.stream.measure", "parent: —")
    .replace("children: [dod.page.results]", "children: [dod.stream.measure]")
)


#: A minimal prevention register: one closed row (an executable artefact that resolves) and one
#: pending row (a gap with an owner).
REGISTER = """# Prevention register

## Register

| id | bug | class | first seen | artefact | level | status | gap |
|---|---|---|---|---|---|---|---|
| P-001 | A long job name | ci-name | PR #48 | `test:tests/test_x.py::test_one` · `ci:code-map` | gate | closed | |
| P-002 | Patches thrown away | retention | 2026-09-25 export | pending | construction | pending | G-701 |

## Gaps
- **G-701** — clean patches are not kept · store the graded patch · server
"""


def _rows(prefix: str, cats: list[str]) -> str:
    return "\n".join(
        f"| {prefix}.{c.lower()}.{i} | {c} | ok | `code:ui/src/App.tsx::App` | met | |"
        for i, c in enumerate(cats, start=1)
    )


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    mod = _load()
    (tmp_path / "ui/src/components").mkdir(parents=True)
    (tmp_path / "ui/src/help").mkdir(parents=True)
    (tmp_path / "ui/src/screens/Results").mkdir(parents=True)
    (tmp_path / "ui/e2e/walkthrough").mkdir(parents=True)
    (tmp_path / "docs/dod/pages").mkdir(parents=True)
    (tmp_path / "docs/dod/journeys").mkdir(parents=True)
    (tmp_path / "docs/dod/streams").mkdir(parents=True)
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "docs/reviews").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / "ui/src/App.tsx").write_text(
        'export function App() {\n  return <Route path="/results" element={<X />} />\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "ui/src/components/Layout.tsx").write_text(
        "export const JOURNEY_STEPS = [\n  { label: 'Baseline', to: '/results' },\n]\n",
        encoding="utf-8",
    )
    (tmp_path / "ui/src/help/hints.ts").write_text(
        "  'tile.results.n':\n    'How many rows.',\n", encoding="utf-8"
    )
    (tmp_path / "ui/src/help/help.ts").write_text(
        "export const HELP = [\n  {\n    route: '/results',\n  },\n]\n", encoding="utf-8"
    )
    (tmp_path / "ui/src/help/hints-ratchet.onramp.tsx").write_text(
        "const SCREENS = {\n  '/results': {\n    path: '/results',\n  },\n}\n", encoding="utf-8"
    )
    (tmp_path / "ui/src/screens/Results/MapTable.test.tsx").write_text(
        "it('every cell carries n', () => {})\n", encoding="utf-8"
    )
    (tmp_path / "ui/e2e/walkthrough/11-screens.spec.ts").write_text(
        "test('viewer @ 375', async () => {})\n", encoding="utf-8"
    )
    (tmp_path / "tests/test_x.py").write_text(
        "def test_one() -> None:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "docs/API.md").write_text(
        "| GET | `/health` | viewer | probes |\n", encoding="utf-8"
    )
    (tmp_path / "docs/OPERATOR.md").write_text("## 5. Sign off\n\ntext\n", encoding="utf-8")
    (tmp_path / "docs/DECISION-LOG.md").write_text(
        "| DL-047 | 2026-09-21 | x | y |\n", encoding="utf-8"
    )
    (tmp_path / "docs/adr/0016-two-person.md").write_text("# ADR-0016\n", encoding="utf-8")
    (tmp_path / "docs/reviews/backlog.md").write_text(
        "## 9. Ordered front-end backlog\n\n"
        "| # | Item | Size | Persona | Pattern | Notes |\n"
        "|---|---|---|---|---|---|\n"
        "| F23 | **User lifecycle** — deactivate, reset a password | S | P6 | NHS IG | x |\n"
        "| B-9 | **Merge outcome and review minutes** | M | P8 | DORA | y |\n",
        encoding="utf-8",
    )
    (tmp_path / ".github/workflows/ci.yml").write_text(
        "jobs:\n  code-map:\n    name: code-map\n", encoding="utf-8"
    )
    (tmp_path / "docs/PREVENTION.md").write_text(REGISTER, encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DOD", tmp_path / "docs/dod")
    monkeypatch.setattr(mod, "OUT", tmp_path / "docs/dod/GAP-ANALYSIS.md")
    monkeypatch.setattr(mod, "APP", tmp_path / "ui/src/App.tsx")
    monkeypatch.setattr(mod, "LAYOUT", tmp_path / "ui/src/components/Layout.tsx")
    monkeypatch.setattr(mod, "HINTS", tmp_path / "ui/src/help/hints.ts")
    monkeypatch.setattr(mod, "HELP", tmp_path / "ui/src/help/help.ts")
    monkeypatch.setattr(mod, "API_DOC", tmp_path / "docs/API.md")
    monkeypatch.setattr(mod, "CI", tmp_path / ".github/workflows/ci.yml")
    monkeypatch.setattr(mod, "DECISION_LOG", tmp_path / "docs/DECISION-LOG.md")
    monkeypatch.setattr(mod, "ADR_DIR", tmp_path / "docs/adr")
    monkeypatch.setattr(mod, "BACKLOG", tmp_path / "docs/reviews/backlog.md")
    monkeypatch.setattr(mod, "PREVENTION", tmp_path / "docs/PREVENTION.md")
    return mod, tmp_path


def _write_all(root: Path, *, ng_state: str = "n/a", ng_gap: str = "not applicable here") -> None:
    (root / "docs/dod/pages/results.md").write_text(
        PAGE.replace("{NG_STATE}", ng_state).replace("{NG_GAP}", ng_gap), encoding="utf-8"
    )
    jcats = [
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
        "STEPS",
        "PROOF",
        "TIME-COST",
        "RECOVERY",
    ]
    scats = [*jcats[:10], "TRIGGER", "OUTCOME", "HANDOFF", "MEASURE", "AUTOMATION"]
    pcats = [
        "VALUE",
        *jcats[:10],
        "IDENTITY",
        "GO-LIVE",
        "CLAIMS",
        "RELEASE",
        "POSTURE",
        "SUPPORT",
        "EXTENSIBILITY",
    ]
    (root / "docs/dod/journeys/read-the-map.md").write_text(
        JOURNEY.replace("{ROWS}", _rows("read-the-map", jcats)), encoding="utf-8"
    )
    (root / "docs/dod/streams/measure.md").write_text(
        STREAM.replace("{ROWS}", _rows("measure", scats)), encoding="utf-8"
    )
    (root / "docs/dod/product.md").write_text(
        PRODUCT.replace("{ROWS}", _rows("product", pcats)), encoding="utf-8"
    )


def test_a_well_formed_tree_generates_the_gap_analysis_and_rolls_up(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root)
    assert mod.main([]) == 0
    out = (root / "docs/dod/GAP-ANALYSIS.md").read_text(encoding="utf-8")
    assert "4 of 4 artefacts done" in out
    assert "status: done" in (root / "docs/dod/pages/results.md").read_text(encoding="utf-8")
    assert mod.main(["--check"]) == 0
    assert "gap analysis current" in capsys.readouterr().out


def test_every_evidence_prefix_resolves_against_the_real_file_shapes(
    tree: tuple[ModuleType, Path],
) -> None:
    mod, root = tree
    _write_all(root)
    art, errs = mod.parse_artefact(root / "docs/dod/pages/results.md")
    assert errs == []
    for c in art.criteria[:9]:
        mod.resolve(c)
        assert c.unresolved == [], c.id
        assert c.resolved, c.id


def test_met_without_resolving_evidence_is_demoted_and_reported(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root)
    page = root / "docs/dod/pages/results.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("::test_one", "::test_missing"), encoding="utf-8"
    )
    assert mod.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "evidence does not resolve: test:tests/test_x.py::test_missing" in out
    art, _ = mod.parse_artefact(page)
    mod.resolve(art.criteria[5])
    assert art.criteria[5].effective_state == "partial"


def test_partial_and_unmet_need_a_defined_gap(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root, ng_state="unmet", ng_gap="")
    assert mod.main(["--check"]) == 1
    assert "unmet needs a gap id" in capsys.readouterr().out
    _write_all(root, ng_state="unmet", ng_gap="G-009")
    assert mod.main(["--check"]) == 1
    assert "gap G-009 is not defined" in capsys.readouterr().out
    _write_all(root, ng_state="unmet", ng_gap="G-001")
    mod.main([])
    out = (root / "docs/dod/GAP-ANALYSIS.md").read_text(encoding="utf-8")
    assert "| 1 |" in out and "G-001" in out and "non-goals not on the About block" in out
    assert "**partial**" in out  # the page, and therefore the journey above it, is no longer done
    assert "0 of 4 artefacts done" in out


def test_every_route_and_journey_step_needs_an_artefact(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root)
    (root / "ui/src/App.tsx").write_text(
        '<Route path="/results" element={<X />} />\n<Route path="/repos/:name" element={<Y />} />\n',
        encoding="utf-8",
    )
    (root / "ui/src/components/Layout.tsx").write_text(
        "export const JOURNEY_STEPS = [\n  { to: '/results' },\n  { to: '/factory' },\n]\n",
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "route /repos/:name has no page artefact (docs/dod/pages/repos-name.md)" in out
    assert "JOURNEY_STEPS entry /factory belongs to no journey" in out


def test_parent_and_children_must_agree_and_a_missing_category_is_a_defect(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root)
    j = root / "docs/dod/journeys/read-the-map.md"
    text = j.read_text(encoding="utf-8").replace("children: [dod.page.results]", "children: []")
    text = "\n".join(line for line in text.split("\n") if "read-the-map.proof." not in line)
    j.write_text(text, encoding="utf-8")
    assert mod.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "parent dod.journey.read-the-map does not list it under children" in out
    assert "no criterion for category PROOF" in out


def test_the_products_value_criteria_come_first(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The value the product exists to deliver heads its definition of done; a product
    artefact whose table does not open with VALUE is a defect, and one without it is too."""
    mod, root = tree
    _write_all(root)
    p = root / "docs/dod/product.md"
    lines = p.read_text(encoding="utf-8").split("\n")
    value = next(i for i, line in enumerate(lines) if "| VALUE |" in line)
    moved = lines[:value] + lines[value + 1 :]
    last = max(i for i, line in enumerate(moved) if line.startswith("| product."))
    moved.insert(last + 1, lines[value])
    p.write_text("\n".join(moved), encoding="utf-8")
    assert mod.main(["--check"]) == 1
    assert "the product's VALUE criteria come first" in capsys.readouterr().out
    p.write_text("\n".join(lines[:value] + lines[value + 1 :]), encoding="utf-8")
    assert mod.main(["--check"]) == 1
    assert "no criterion for category VALUE" in capsys.readouterr().out


def test_check_fails_on_a_stale_gap_analysis_or_status_line(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root)
    assert mod.main([]) == 0
    (root / "docs/dod/GAP-ANALYSIS.md").write_text("stale\n", encoding="utf-8")
    assert mod.main(["--check"]) == 1
    assert "GAP-ANALYSIS.md is out of date" in capsys.readouterr().out
    assert mod.main([]) == 0
    page = root / "docs/dod/pages/results.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("status: done", "status: partial"),
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    assert "the roll-up says 'done'" in capsys.readouterr().out


def test_a_reference_title_may_contain_the_journey_separator(
    tree: tuple[ModuleType, Path],
) -> None:
    """` · ` cuts between references, never inside a quoted test title."""
    mod, _root = tree
    title = 'vitest:ui/src/components/Layout.test.tsx::"derives "Journey · n of 4 · Step" from it"'
    refs = mod.split_refs(f"`{title}` · `hint:about:/results` · `route:GET /health`")
    assert refs == [title, "hint:about:/results", "route:GET /health"]
    assert mod.split_refs("absent") == []


def test_a_gap_line_names_the_change_and_a_known_owner(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    page = root / "docs/dod/pages/results.md"
    good = "- **G-001** — non-goals not on the About block · add one sentence · ui"
    _write_all(root, ng_state="unmet", ng_gap="G-001")
    page.write_text(
        page.read_text(encoding="utf-8").replace(good, "- **G-001** — no sentence on the page"),
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    assert "must read 'what is missing" in capsys.readouterr().out
    _write_all(root, ng_state="unmet", ng_gap="G-001")
    page.write_text(
        page.read_text(encoding="utf-8").replace(good, good[: -len("ui")] + "tests"),
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    assert "the owner must be one of" in capsys.readouterr().out


def test_one_gap_id_is_one_piece_of_work_across_the_tree(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Two files may share an id — but then they must share the line, word for word."""
    mod, root = tree
    _write_all(root, ng_state="unmet", ng_gap="G-001")
    j = root / "docs/dod/journeys/read-the-map.md"
    j.write_text(
        j.read_text(encoding="utf-8")
        + "\n## Gaps\n- **G-001** — something else entirely · change it · server\n",
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    assert "gap G-001 is defined differently in" in capsys.readouterr().out


def test_one_gap_id_is_one_piece_of_work_inside_a_single_file_too(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The blind spot the cross-file check left: gaps were collected into a per-artefact dict,
    so the SAME id twice in one file silently overwrote the first line and the register
    dropped a gap nobody had closed. An identical pair inside one file passed clean while the
    identical pair ACROSS two files failed."""
    mod, root = tree
    _write_all(root, ng_state="unmet", ng_gap="G-001")
    page = root / "docs/dod/pages/results.md"
    page.write_text(
        page.read_text(encoding="utf-8")
        + "- **G-001** \u2014 a different piece of work entirely \u00b7 change it \u00b7 server\n",
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    assert "is defined twice in this file" in capsys.readouterr().out


def test_an_anchor_resolves_by_githubs_own_slug_rule(
    tree: tuple[ModuleType, Path],
) -> None:
    """GitHub replaces EACH space with its own hyphen and does not collapse runs, so a heading
    with a stripped character between two spaces gets a DOUBLE hyphen. Collapsing them here
    made the checker accept an anchor a reader's click could not resolve."""
    mod, _ = tree
    assert (
        mod._slug("11. Intake — work arriving from a board")
        == "11-intake--work-arriving-from-a-board"
    )
    assert (
        mod._slug("3.1 Oracle adequacy — mutation scoring")
        == "31-oracle-adequacy--mutation-scoring"
    )
    # and the ordinary cases are unchanged
    assert mod._slug("Stop conditions") == "stop-conditions"
    assert mod._slug("`crb doctor`") == "crb-doctor"


def test_a_gap_record_needs_the_em_dash_and_measured_needs_an_apparatus_version(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Two grammar rules the standard declares and the checker now enforces: a gap record is
    ``- **G-nnn** \u2014 what \u00b7 change \u00b7 owner`` with an em dash, and a ``measured:``
    annotation names an apparatus VERSION, not the bare word."""
    mod, root = tree
    _write_all(root)
    page = root / "docs/dod/pages/results.md"
    good = page.read_text(encoding="utf-8")
    page.write_text(good.replace("- **G-001** \u2014 ", "- **G-001** - "), encoding="utf-8")
    assert mod.main(["--check"]) == 1
    assert "gap line must be" in capsys.readouterr().out
    page.write_text(
        good.replace(
            "`code:ui/src/App.tsx::App`",
            "`code:ui/src/App.tsx::App` \u00b7 `measured:n = 1, method: inspection, apparatus`",
            1,
        ),
        encoding="utf-8",
    )
    assert mod.main(["--check"]) == 1
    assert "evidence does not resolve: measured:n = 1, method: inspection, apparatus" in (
        capsys.readouterr().out
    )


def test_a_code_reference_needs_a_symbol_or_a_quoted_literal_and_measured_needs_its_metadata(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Two references that used to be unfalsifiable: a bare ``code:<file>`` (a file existing
    proves nothing) and a ``measured:`` annotation with no n, method or apparatus."""
    mod, root = tree
    _write_all(root)
    page = root / "docs/dod/pages/results.md"
    good = page.read_text(encoding="utf-8")
    for bad, message in (
        ("`code:ui/src/App.tsx`", "code:ui/src/App.tsx"),
        ('`code:ui/src/App.tsx::"no such text"`', 'code:ui/src/App.tsx::"no such text"'),
        ("`code:ui/src/App.tsx::Missing`", "code:ui/src/App.tsx::Missing"),
        (
            "`code:ui/src/App.tsx::App` \u00b7 `measured:the tiles show a mean`",
            "measured:the tiles show a mean",
        ),
    ):
        page.write_text(good.replace("`code:ui/src/App.tsx::App`", bad, 1), encoding="utf-8")
        assert mod.main(["--check"]) == 1, bad
        assert f"evidence does not resolve: {message}" in capsys.readouterr().out, bad
    # the quoted-literal form and a complete measured annotation both pass
    page.write_text(
        good.replace(
            "`code:ui/src/App.tsx::App`",
            '`code:ui/src/App.tsx::"<Route path="` \u00b7 '
            "`measured:n = 1 route, method: by inspection of App.tsx, apparatus 2.2`",
            1,
        ),
        encoding="utf-8",
    )
    assert mod.main([]) == 0


def test_a_backlog_row_that_names_a_pair_or_a_range_resolves_every_id_it_names(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The backlog merges rows as the audit lands them: ``B-51/F80`` and ``F90-F92`` are
    single rows that stand for several ids, and a criterion may cite any one of them."""
    mod, root = tree
    backlog = root / "docs/reviews/backlog.md"
    backlog.write_text(
        backlog.read_text(encoding="utf-8")
        + "| B-51/F80 | **Merge outcome as evidence** \u2014 the fate of the pull request | M |\n"
        + "| F90\u2013F92 | **Shippable-state gaps** \u2014 the 2026-09-21 audit | S |\n",
        encoding="utf-8",
    )
    for cited in ("B-51", "F80", "F90", "F91", "F92"):
        _write_all(root, ng_state="unmet", ng_gap=cited)
        assert mod.main([]) == 0, cited
        out = (root / "docs/dod/GAP-ANALYSIS.md").read_text(encoding="utf-8")
        title = "Merge outcome as evidence" if cited in ("B-51", "F80") else "Shippable-state gaps"
        assert title in out, cited  # the ranked row says what the backlog row is
    _write_all(root, ng_state="unmet", ng_gap="F93")  # inside neither row
    assert mod.main(["--check"]) == 1
    assert "gap F93 is in no backlog row under" in capsys.readouterr().out


def test_a_backlog_gap_must_be_a_row_in_the_ordered_backlog_and_the_ranking_names_it(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root, ng_state="unmet", ng_gap="F99")
    assert mod.main(["--check"]) == 1
    assert "gap F99 is in no backlog row under" in capsys.readouterr().out
    _write_all(root, ng_state="unmet", ng_gap="F23")
    assert mod.main([]) == 0
    out = (root / "docs/dod/GAP-ANALYSIS.md").read_text(encoding="utf-8")
    assert "backlog F23 — User lifecycle · S" in out


def test_the_rank_counts_what_a_gap_blocks_and_doubles_a_partial_in_the_honesty_categories(
    tree: tuple[ModuleType, Path],
) -> None:
    mod, root = tree
    _write_all(root, ng_state="unmet", ng_gap="G-001")
    page = root / "docs/dod/pages/results.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "| results.truth.3 | TRUTH | n on every rate | "
            '`vitest:ui/src/screens/Results/MapTable.test.tsx::"every cell carries n"` | met | |',
            "| results.truth.3 | TRUTH | n on every rate | `absent` | partial | G-001 |",
        ),
        encoding="utf-8",
    )
    arts = [mod.parse_artefact(p)[0] for p in mod.artefact_files()]
    mod.validate(arts)
    assert mod.blocked_by_gap(arts)["G-001"] == 2
    assert mod._state_factor("TRUTH", "partial") == 2
    assert mod._state_factor("STEPS", "partial") == 1
    assert mod._state_factor("STEPS", "unmet") == 2
    truth = next(r for r in mod._rank(arts) if r[3].id == "results.truth.3")
    # page 2 × TRUTH 5 × 2 criteria blocked × partial-in-an-honesty-category 2
    assert truth[0] == 40 and truth[1] == 2
    mod.roll_up(arts)
    assert "## Open gaps by fan-out" in mod.render(arts)


def test_an_open_value_criterion_outranks_every_other_open_criterion(
    tree: tuple[ModuleType, Path],
) -> None:
    """The operator's refocus is the order of work: the weakest open VALUE criterion (a
    product criterion blocking one) scores above the strongest possible other one (a product
    criterion in a weight-5 category blocking three or more, doubled)."""
    mod, _root = tree
    others = max(w for c, w in mod.WEIGHT.items() if c != "VALUE")
    strongest_other = mod.LEVEL_WEIGHT["product"] * others * 3 * 2
    weakest_value = mod.LEVEL_WEIGHT["product"] * mod.WEIGHT["VALUE"] * 1 * 1
    assert "VALUE" in mod.HONESTY and weakest_value * 2 > strongest_other
    assert mod.EXTRA["product"][0] == "VALUE"


def _register_row(row: str) -> str:
    return REGISTER.replace(
        "| P-002 | Patches thrown away | retention | 2026-09-25 export | pending | construction | pending | G-701 |",
        row,
    )


@pytest.mark.parametrize(
    ("row", "error"),
    [
        (
            "| P-002 | x | c | e | `code:ui/src/App.tsx::App` | gate | closed | |",
            "closed only by an artefact that fails when its class recurs",
        ),
        (
            "| P-002 | x | c | e | `test:tests/test_x.py::test_one` | advisory | closed | |",
            "advisory artefact cannot close a defect",
        ),
        ("| P-002 | x | c | e | pending | gate | pending | |", "pending needs a gap id"),
        (
            "| P-002 | x | c | e | `test:tests/test_x.py::test_nope` | gate | closed | |",
            "evidence does not resolve: test:tests/test_x.py::test_nope",
        ),
        ("| P-002 | x | c | e | pending | wishful | pending | G-701 |", "level must be one of"),
        ("| P-002 | x | c | e | pending | gate | parked | G-701 |", "status must be one of"),
        ("| P-001 | x | c | e | pending | gate | pending | G-701 |", "duplicate id P-001"),
        ("| P-002 | x | c | | pending | gate | pending | G-701 |", "needs a first-seen"),
        ("| P-002 | x | c | e | pending | gate | pending | G-799 |", "gap G-799 is not defined"),
    ],
)
def test_the_prevention_register_refuses_an_entry_without_a_working_artefact(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str], row: str, error: str
) -> None:
    """STANDARD.md §7: a defect is closed only with the artefact that fails if its class
    recurs. The register is checked like the artefacts: every reference resolves, a closed
    row carries an executable one (test / vitest / spec / ci), advisory text never closes a
    defect, and a pending row names its gap and owner."""
    mod, root = tree
    _write_all(root)
    assert mod.main([]) == 0
    (root / "docs/PREVENTION.md").write_text(_register_row(row), encoding="utf-8")
    assert mod.main(["--check"]) == 1
    assert error in capsys.readouterr().out


def test_the_register_must_exist_and_its_counts_reach_the_gap_analysis(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    mod, root = tree
    _write_all(root)
    assert mod.main([]) == 0
    out = (root / "docs/dod/GAP-ANALYSIS.md").read_text(encoding="utf-8")
    assert "## Our own bugs — the prevention register" in out
    assert "**2 registered · 1 closed (gate 1) · 1 pending.**" in out
    assert (
        "| P-002 | Patches thrown away | construction | G-701 | clean patches are not kept" in out
    )
    (root / "docs/PREVENTION.md").unlink()
    assert mod.main(["--check"]) == 1
    assert "docs/PREVENTION.md is missing" in capsys.readouterr().out


def test_two_streams_numbering_the_same_criterion_id_are_refused(
    tree: tuple[ModuleType, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """docs/PREVENTION.md P-016: three parallel streams each added ``measure.truth.16`` to
    the same file; the merge had to renumber them. A duplicate id must fail the gate, never
    silently shadow the other criterion."""
    mod, root = tree
    _write_all(root)
    stream = root / "docs/dod/streams/measure.md"
    lines = stream.read_text(encoding="utf-8").splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("| measure."))
    lines.insert(first + 1, lines[first])
    stream.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert mod.main(["--check"]) == 1
    assert "duplicate criterion id measure." in capsys.readouterr().out
