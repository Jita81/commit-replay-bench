"""README's [measured] claims, re-derived from the rows the repository carries (G-660).

A ``[measured]`` tag on README names its rows (``rows: data/<campaign>/``, enforced by
``scripts/claims_check.py``). This file does what a reader would: it verifies the rows'
checksum manifest, recomputes the campaign's figures from the rows with the product's own
code, and fails when the claim does not state a figure in its role — "49 of 55" is the
cell's clean count of its attempts, "point 0.891" its point, "0.78 to 0.95" its interval —
when it states any other number, anywhere the tag covers, or when it names another
apparatus. A figure is bound to its role, never to whichever figure it happens to equal:
"false-Q1 = 1" fails although a point rounds to 1 (P-242). Every number the tag covers is
read, in digits or in words, bare or in a ratio ("54", "ninety percent", "9-in-10"); only
dates, apparatus versions, confidence levels and numbers that name rather than count are
not figures (P-247). A tag in a table cell, a heading or a checklist item is re-derived like
one in prose (P-246). A claim that stops being true fails here rather than waiting for a
reader.

Navigation
----------
What it is:   The re-derivation test for every README ``[measured]`` claim that names rows.
What it does: Finds each README block, in any rendered shape, whose ``[measured]`` tag names
              ``rows: data/<campaign>/``, with every sentence of the block and every list or
              checklist item it introduces; checks the campaign's manifest; derives its
              figures and renders the phrases its derivation says a claim states
              (``DERIVATIONS``); requires each phrase and refuses any number left over, in
              digits or in words; and checks the apparatus. A locator with no
              derivation fails, so a new campaign cannot be cited without one. The
              branch-protection reading is compared with the workflow vendored beside it,
              never with the working tree's ci.yml.
How:          ``claims_check.blocks_of`` / ``claim_numbers`` / ``verify_manifest`` read the
              page; ``crb.core.legacy.import_census`` and ``crb.core.ledger.cell_stats``
              recompute the census; ``check_branch_protection.job_contexts`` /
              ``compare`` read the vendored workflow and the reading.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md (false-Q1 at write)
Works with:   README.md (the claims), data/census-2026-07-08/ and
              data/branch-protection-2026-09-27/ (the rows, and the workflow the reading was
              compared with), scripts/claims_check.py (the locator rule),
              scripts/check_branch_protection.py (the workflow's check names),
              tests/test_census_gate.py (the census's own invariants), docs/dod/product.md
              (product.claims.201, G-660)
Tested by:    (this is a test file)
Touch when:   never for a new repository; README gains a [measured] claim on a new campaign — vendor
              its rows with a manifest under data/ and add its derivation, with the phrases the
              claim states, to ``DERIVATIONS`` in the same change.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cc = _load("claims_check")
bp = _load("check_branch_protection")


@dataclass(frozen=True)
class Derived:
    """What a campaign's rows give: its apparatus, its figures, and the phrases a claim on
    them states — each a template naming the figure in its role (``"{cell_clean} of
    {cell_n}"``), so a number is held to the figure it is meant to be, never to whichever
    figure it happens to equal (P-242)."""

    apparatus: str
    figures: dict[str, float]
    says: tuple[str, ...]

    def phrases(self) -> list[str]:
        """The phrases rendered from the rows, in the order they are matched."""
        return [t.format(**self.figures) for t in self.says]


def _census(root: Path) -> Derived:
    """The vendored census: all rows' false-Q1 and the ``bug.fix`` XS four-belt sighted
    cell, through the product's importer and cell statistics."""
    from crb.core.ledger import cell_stats, false_q1_total
    from crb.core.legacy import import_census

    data = root / "data" / "census-2026-07-08"
    rows = [
        g.row for g in import_census(data / "grades.jsonl", data / "tasks", data / "configs.json")
    ]
    cell = [
        r
        for r in rows
        if (r.capability_class, r.size, r.mode, r.belt_set) == ("bug.fix", "XS", "sighted", "v4")
    ]
    stats = cell_stats(cell)
    apparatus = {r.apparatus_version for r in rows}
    assert len(apparatus) == 1, f"the census rows carry {sorted(apparatus)}"
    assert {r.builder for r in cell} == {"claude-code-workflow"}
    assert {r.model for r in cell} == {"sonnet"}
    return Derived(
        apparatus.pop(),
        {
            "rows": len(rows),
            "false_q1": false_q1_total(rows),
            "cell_n": stats.n,
            "cell_clean": stats.clean,
            "cell_point": stats.point,
            "cell_ci_low": stats.ci.low,
            "cell_ci_high": stats.ci.high,
        },
        (
            "{cell_clean} of {cell_n}",
            "point {cell_point:.3f}",
            "{cell_ci_low:.2f} to {cell_ci_high:.2f}",
            "of the {rows:,}",
            "false-Q1 = {false_q1}",
            "n = {cell_n} attempts",
            "{rows:,} rows",
        ),
    )


def _branch_protection(root: Path) -> Derived:
    """The vendored reading of main's required checks, which must be exactly the jobs of the
    workflow in force when it was read (the claim is that every job was required), vendored
    beside it. It is never compared with the working tree's ci.yml: a pull request that adds
    a job cannot be required before it merges, and ``scripts/check_branch_protection.py`` is
    the operator's live comparison."""
    data = root / "data" / "branch-protection-2026-09-27"
    reading = json.loads((data / "required_status_checks.json").read_text(encoding="utf-8"))
    workflow = json.loads((data / "workflow_jobs.json").read_text(encoding="utf-8"))
    problems = bp.compare(workflow["jobs"], reading["contexts"], reading["strict"])
    assert problems == [], (
        f"the reading does not match the workflow it was read against: {problems}"
    )
    return Derived(
        reading["_apparatus"],
        {"required_checks": len(reading["contexts"])},
        ("n = {required_checks} required checks", "{required_checks} required checks"),
    )


#: Every campaign a README [measured] tag may cite, and how its figures are derived.
DERIVATIONS: dict[str, Callable[[Path], Derived]] = {
    "data/census-2026-07-08": _census,
    "data/branch-protection-2026-09-27": _branch_protection,
}

_NUM = r"\d[\d,]*(?:\.\d+)?"
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_APPARATUS_TEXT = re.compile(r"\bapparatus\s+[0-9][\w.-]*", re.I)
_DATE = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}\s+(?:{_MONTHS})(?:\s+\d{{4}}(?!-))?\b"
    rf"|\b(?:{_MONTHS})\s+\d{{4}}\b"
)
#: A number that names rather than counts: a dotted version ("2.0.0a1"), one touching a
#: letter ("v5", "P0"), after "§", "#" or a lettered prefix and a hyphen
#: ("§2", "ADR-0013", "Apache-2.0"), or after an acronym ("PEP 440", "ISO 25010").
_IDENTIFIER = re.compile(
    rf"(?:\d+(?:\.\d+){{2,}}|[A-Za-z]{_NUM}|{_NUM}[A-Za-z]|[§#]\s?{_NUM}|[A-Za-z]-{_NUM}|\b[A-Z]{{2,}}\s+{_NUM})"
    rf"[\w.]*"
)
#: A number written in words, unless it names a part of the text ("three files", a
#: structural noun) or forms a compound adjective ("four-belt"). "one" is absent, as it is
#: from the gate's own list: "every one of them" counts nothing.
_WORD_NUMBER = re.compile(
    rf"\b({cc._NUMBER_WORD}|zero)\b(?!-(?!(?:{'|'.join(cc.NUMBER_WORDS)}|one)\b)[a-z])"
    r"(?:\s+([a-z]+))?",
    re.I,
)
_FIGURE = re.compile(rf"(?<![\d.,]){_NUM}(?![\d])")


def _unwrap_code(text: str) -> str:
    """``text`` in NFKC (``⅔`` → ``2⁄3``) with every inline code span replaced by its
    content, so a figure in backticks is read as the figure it is (P-348)."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"(`+)(.+?)\1", lambda m: f" {m.group(2)} ", text)


def stated_numbers(text: str) -> list[str]:
    """Every figure the text states, once each, where it stands: every number in digits
    ("49", "0.891", "1,071", "54", the 9 and the 10 of "9-in-10") and every number written
    in words ("ninety", "fifty-four"). Dates, apparatus versions, confidence levels and
    numbers that name rather than count (``_IDENTIFIER``) are not figures (P-247). A figure
    inside inline code is still a figure, and a Unicode fraction ("⅔") reads as its digits
    (NFKC): the code span is unwrapped, never dropped, so only what ``_IDENTIFIER`` names
    (`mutation.v2`, `r1`) is skipped (P-348)."""
    text = cc._strip_markup(_unwrap_code(text))
    text = _APPARATUS_TEXT.sub(" ", text)
    text = _DATE.sub(" ", text)
    text = cc._CONFIDENCE_PERCENT_RE.sub(" ", text)
    text = _IDENTIFIER.sub(" ", text)
    text = re.sub(r"\bdata/[\w./-]+", " ", text)  # a rows locator is a path, not a figure
    out = [m.group(0).rstrip(",.") for m in _FIGURE.finditer(text)]
    for m in _WORD_NUMBER.finditer(text):
        if (m.group(2) or "").lower() not in cc.STRUCTURAL:
            out.append(m.group(1))
    return out


def _phrase_re(phrase: str) -> re.Pattern[str]:
    """``phrase`` as whole figures: "49 of 55" is not found inside "149 of 555"."""
    return re.compile(rf"(?<![\d.,]){re.escape(phrase)}(?![.,]?\d)")


@dataclass(frozen=True)
class Claim:
    line: int
    campaign: str
    tag: str
    text: str


def measured_claims(text: str) -> list[Claim]:
    """Each README block's [measured] tag that names rows, with ALL the text the tag covers:
    every sentence of its block, whether or not the gate counts it as a claim, and every
    list item the block introduces (the gate lets the intro's tag cover them)."""
    out: list[Claim] = []
    blocks = cc.blocks_of(text, rendered=True)  # a heading, a table cell, a checklist item
    for i, block in enumerate(blocks):
        prose = cc._CODE_RE.sub(" ", cc._COMMENT_RE.sub(" ", block.text))
        for name, detail in cc._TAG_RE.findall(prose):
            if name.lower() != "measured":
                continue
            covered = [block.text]
            covered += [b.text for b in blocks[i + 1 :] if b.cover == f"{block.text} {b.text}"]
            for campaign in cc.rows_locators(detail):
                out.append(Claim(block.line, campaign, detail, " ".join(covered)))
    return out


def problems(claim: Claim, root: Path = ROOT) -> list[str]:
    """Why ``claim`` is not what its rows give; empty when it states every phrase its
    derivation renders from the rows, states no other figure, and names the rows' apparatus.
    Each phrase binds a number to its role, so a real figure in the wrong role fails."""
    derive = DERIVATIONS.get(claim.campaign)
    if derive is None:
        return [f"{claim.campaign} has no derivation in tests/test_measured_claims.py"]
    found = [f"manifest: {p}" for p in cc.verify_manifest(root, claim.campaign)]
    derived = derive(root)
    stated_apparatus = re.findall(r"\bapparatus\s+([0-9][\w.-]*[\w])", claim.tag, re.I)
    if derived.apparatus not in stated_apparatus:
        found.append(
            f"the tag names apparatus {stated_apparatus}; the rows are {derived.apparatus}"
        )
    # the tag is part of the text; code spans are unwrapped, never dropped (P-348)
    rest = " ".join(cc._strip_markup(_unwrap_code(claim.text)).split())
    for phrase in derived.phrases():
        pattern = _phrase_re(phrase)
        if not pattern.search(rest):
            found.append(f"the claim does not state {phrase!r}, which is what the rows give")
        rest = pattern.sub(" ", rest)
    for n in stated_numbers(rest):
        found.append(f"{n} is stated, but no figure the rows give is bound to it")
    return found


def _live() -> list[Claim]:
    return measured_claims(README.read_text(encoding="utf-8"))


def test_every_readme_measured_claim_names_rows_with_a_derivation() -> None:
    claims = _live()
    assert {c.campaign for c in claims} == set(DERIVATIONS), (
        "every README [measured] claim cites a campaign with a derivation, and every "
        "derivation is cited (a stale one would re-derive nothing)"
    )
    assert cc.check_rows(ROOT) == []


@pytest.mark.parametrize("claim", _live(), ids=lambda c: f"README:{c.line}:{c.campaign}")
def test_every_number_a_readme_measured_claim_states_is_re_derived_from_its_rows(
    claim: Claim,
) -> None:
    assert problems(claim) == []


def test_a_number_the_rows_do_not_give_fails() -> None:
    """The re-derivation can fail: the census claim with one count, one bound or the
    apparatus changed is refused."""
    census = next(c for c in _live() if c.campaign == "data/census-2026-07-08")
    assert problems(census) == []
    for wrong, right in (("49 of 55", "48 of 55"), ("0.78 to", "0.79 to"), ("1,071", "1,070")):
        assert wrong in census.text, f"the census claim no longer states {wrong!r}"
        bent = Claim(census.line, census.campaign, census.tag, census.text.replace(wrong, right))
        assert any(right.split()[0] in p for p in problems(bent)), right
    other = Claim(
        census.line, census.campaign, census.tag.replace("1.0-census", "2.2"), census.text
    )
    assert any("apparatus" in p for p in problems(other))
    unknown = Claim(census.line, "data/nowhere", census.tag, census.text)
    assert problems(unknown) == ["data/nowhere has no derivation in tests/test_measured_claims.py"]


def test_stated_numbers_skip_dates_versions_and_confidence_levels() -> None:
    """Each figure once, where it stands; dates, apparatus versions, confidence levels and
    identifiers are not figures."""
    text = (
        "On 27 September 2026-09-27, 49 of 55 attempts were clean (Wilson 95% interval "
        "0.78 to 0.95), n = 55; apparatus 1.0-census. In June 2026, v2.0.0a1 of P0-P7 per "
        "PEP 440 and ADR-0013 §2 ran in four-belt mode on data/census-2026-07-08/."
    )
    assert stated_numbers(text) == ["49", "55", "0.78", "0.95", "55"]


def test_a_measured_tag_in_a_table_is_re_derived(tmp_path: Path) -> None:
    """A [measured] tag in a table cell names its rows (the gate) and is re-derived from
    them like any other (P-246): a cell that does not state what the rows give fails."""
    tag = (
        "[measured — n = 55 attempts; method: the census rows re-imported and read by the "
        "product's cell statistics; rows: data/census-2026-07-08/; apparatus 1.0-census]"
    )
    page = f"# t\n\n| cell | result |\n|---|---|\n| bug.fix XS | 99% clean {tag} |\n"
    claims = measured_claims(page)
    assert [c.campaign for c in claims] == ["data/census-2026-07-08"]
    assert problems(claims[0]) != []


#: A stated figure swapped for ANOTHER figure the rows give: each is a number the rows do
#: give, in the wrong role, so a bag-of-figures comparison accepted every one (P-242).
COINCIDENT: tuple[tuple[str, str], ...] = (
    ("false-Q1 = 0", "false-Q1 = 1"),
    ("false-Q1 = 0", "false-Q1 = 55"),
    ("point 0.891", "point 0.95"),
    ("49 of 55", "55 of 55"),
    ("49 of 55", "1 of 55"),
    ("0.78 to 0.95", "0.95 to 0.78"),
    ("of the 1,071", "of the 55"),
    ("n = 55 attempts", "n = 1,071 attempts"),
)


@pytest.mark.parametrize(("right", "wrong"), COINCIDENT)
def test_a_real_figure_in_the_wrong_role_fails(right: str, wrong: str) -> None:
    census = next(c for c in _live() if c.campaign == "data/census-2026-07-08")
    assert right in f"{census.text} {census.tag}", f"the census claim no longer states {right!r}"
    bent = Claim(
        census.line,
        census.campaign,
        census.tag.replace(right, wrong),
        census.text.replace(right, wrong),
    )
    assert problems(bent) != [], wrong


def _census_paragraph() -> str:
    census = next(c for c in _live() if c.campaign == "data/census-2026-07-08")
    text = README.read_text(encoding="utf-8")
    return next(b.text for b in cc.blocks_of(text) if b.line == census.line)


@pytest.mark.parametrize(
    "page",
    [
        # a list item the measured paragraph introduces is covered by its tag, so it is read
        "{p}\n\n- 99% of all 1,071 rows were clean.\n",
        # a sentence of the block with numbers but no count of a plural noun is read too
        "{p} Its Wilson interval is 0.10 to 0.20.\n",
        # a bare number, a percentage in words and a k-in-n ratio are figures too (P-247)
        "{p} The cell's clean count was 54.\n",
        "{p} In all, ninety percent of the cell's attempts were clean.\n",
        "{p} That is 9-in-10 clean.\n",
        "{p} Its clean count was fifty-four.\n",
        # a figure in inline code, and a Unicode fraction, are figures too (P-348)
        "{p} (`90%` of all attempts)\n",
        "{p} Two thirds, ⅔, were clean.\n",
        # a checklist item the measured paragraph introduces is covered by its tag too
        "{p}\n\n- [x] 99% of all 1,071 rows were clean.\n",
    ],
)
def test_every_number_the_tag_covers_is_re_derived(page: str) -> None:
    claims = measured_claims("# t\n\n" + page.format(p=_census_paragraph()))
    assert [c.campaign for c in claims] == ["data/census-2026-07-08"]
    assert problems(claims[0]) != []


def test_the_branch_protection_reading_is_compared_with_the_workflow_it_was_read_against(
    tmp_path: Path,
) -> None:
    """The reading is compared with the workflow in force when it was taken, vendored beside
    it — never with the working tree's ci.yml, which a later pull request may change before
    an admin can honestly require the new job."""
    import shutil

    campaign = "data/branch-protection-2026-09-27"
    shutil.copytree(ROOT / campaign, tmp_path / campaign)
    derived = _branch_protection(tmp_path)
    assert derived.figures["required_checks"] == 16


def test_the_vendored_workflow_is_ci_yml_at_the_commit_it_names() -> None:
    snapshot = json.loads(
        (ROOT / "data" / "branch-protection-2026-09-27" / "workflow_jobs.json").read_text(
            encoding="utf-8"
        )
    )
    import subprocess

    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{snapshot['commit']}:.github/workflows/ci.yml"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        pytest.skip(f"this clone does not hold {snapshot['commit']} (a shallow clone)")
    assert bp.job_contexts(shown.stdout) == snapshot["jobs"]
