"""README's [measured] claims, re-derived from the rows the repository carries (G-660).

A ``[measured]`` tag on README names its rows (``rows: data/<campaign>/``, enforced by
``scripts/claims_check.py``). This file does what a reader would: it verifies the rows'
checksum manifest, recomputes the campaign's figures from the rows with the product's own
code, and fails when any number the claim states — a count, a fraction, a point, an interval
bound, a percentage — or the apparatus it names is not what the rows give. A claim that stops
being true fails here rather than waiting for a reader.

Navigation
----------
What it is:   The re-derivation test for every README ``[measured]`` claim that names rows.
What it does: Finds each README block whose ``[measured]`` tag names ``rows: data/<campaign>/``;
              checks the campaign's manifest; derives its figures (``DERIVATIONS``); and
              compares every number the claim sentences and the tag state, at the precision
              they state it, and the apparatus, with what the rows give. A locator with no
              derivation fails, so a new campaign cannot be cited without one.
How:          ``claims_check.blocks_of`` / ``claim_numbers`` / ``verify_manifest`` read the
              page; ``crb.core.legacy.import_census`` and ``crb.core.ledger.cell_stats``
              recompute the census; ``check_branch_protection.job_contexts`` reads ci.yml.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md (false-Q1 at write)
Works with:   README.md (the claims), data/census-2026-07-08/ and
              data/branch-protection-2026-09-27/ (the rows), scripts/claims_check.py (the
              locator rule), scripts/check_branch_protection.py (the workflow's check names),
              tests/test_census_gate.py (the census's own invariants), docs/dod/product.md
              (product.claims.201, G-660)
Tested by:    (this is a test file)
Touch when:   README gains a [measured] claim on a new campaign — vendor its rows with a
              manifest under data/ and add its derivation to ``DERIVATIONS`` in the same change.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
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
    """What a campaign's rows give: its apparatus and every figure a claim may state."""

    apparatus: str
    figures: dict[str, float]


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
    )


def _branch_protection(root: Path) -> Derived:
    """The vendored reading of main's required checks, which must be exactly ci.yml's jobs
    (the claim is that every job is required)."""
    reading = json.loads(
        (root / "data" / "branch-protection-2026-09-27" / "required_status_checks.json").read_text(
            encoding="utf-8"
        )
    )
    jobs = bp.job_contexts((root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    problems = bp.compare(jobs, reading["contexts"], reading["strict"])
    assert problems == [], f"the reading no longer matches ci.yml: {problems}"
    return Derived(reading["_apparatus"], {"required_checks": len(reading["contexts"])})


#: Every campaign a README [measured] tag may cite, and how its figures are derived.
DERIVATIONS: dict[str, Callable[[Path], Derived]] = {
    "data/census-2026-07-08": _census,
    "data/branch-protection-2026-09-27": _branch_protection,
}

_NUM = r"\d[\d,]*(?:\.\d+)?"
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_APPARATUS_TEXT = re.compile(r"\bapparatus\s+[0-9][\w.-]*", re.I)
_DATE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}\s+(?:{_MONTHS})\b")


def stated_numbers(text: str) -> list[str]:
    """Every figure the text states: the gate's own claim figures (counts, percentages), a
    fraction's two sides ("49 of 55", "22/22"), a value after "=" ("n = 55", "false-Q1 = 0")
    and a proportion written as a decimal ("0.891", "0.78"). Dates, apparatus versions and
    confidence levels are not figures."""
    text = cc._strip_markup(text)
    text = _APPARATUS_TEXT.sub(" ", text)
    text = _DATE.sub(" ", text)
    text = cc._CONFIDENCE_PERCENT_RE.sub(" ", text)
    out: list[str] = []
    for sentence in cc._SENTENCE_SPLIT.split(text):
        out += cc.claim_numbers(sentence)
    for m in re.finditer(rf"(?<![\d.])({_NUM})\s*(?:/|\bof\b)\s*({_NUM})(?![\d.])", text):
        out += [m.group(1), m.group(2)]
    out += re.findall(rf"=\s*({_NUM})", text)
    out += re.findall(r"(?<![\d.])0\.\d+(?![\d.])", text)
    return out


def _matches(stated: str, derived: dict[str, float]) -> bool:
    """``stated`` equals some derived figure at the precision it is written with."""
    percent = stated.endswith("%")
    raw = stated.rstrip("%").strip().replace(",", "")
    places = len(raw.split(".")[1]) if "." in raw else 0
    value = float(raw)
    for fig in derived.values():
        candidate = fig * 100 if percent else fig
        if round(candidate, places) == round(value, places):
            return True
    return False


@dataclass(frozen=True)
class Claim:
    line: int
    campaign: str
    tag: str
    text: str


def measured_claims(text: str) -> list[Claim]:
    """Each README block's [measured] tag that names rows, with the block's claim text."""
    out: list[Claim] = []
    for block in cc.blocks_of(text):
        prose = cc._CODE_RE.sub(" ", cc._COMMENT_RE.sub(" ", block.text))
        for name, detail in cc._TAG_RE.findall(prose):
            if name.lower() != "measured":
                continue
            claims = [s for s in cc._SENTENCE_SPLIT.split(block.text) if cc.is_claim(s)]
            for campaign in cc.rows_locators(detail):
                out.append(Claim(block.line, campaign, detail, " ".join(claims)))
    return out


def problems(claim: Claim, root: Path = ROOT) -> list[str]:
    """Why ``claim`` is not what its rows give; empty when every stated number and the
    apparatus re-derive."""
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
    numbers = stated_numbers(f"{claim.text} {claim.tag}")
    if not numbers:
        found.append("the claim states no number to re-derive")
    for n in numbers:
        if not _matches(n, derived.figures):
            found.append(f"{n} is not what the rows give ({derived.figures})")
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
    text = (
        "On 27 September 2026-09-27, 49 of 55 attempts were clean (Wilson 95% interval "
        "0.78 to 0.95), n = 55; apparatus 1.0-census"
    )
    assert sorted(stated_numbers(text)) == sorted(["55", "49", "55", "55", "0.78", "0.95"])
