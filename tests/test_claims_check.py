"""scripts/claims_check.py — the claim-tag gate, on a throwaway documentation tree.

Navigation
----------
What it is:   Unit tests for the claims gate (every public claim carries a permitted tag).
What it does: Pins that a tagged claim passes and an untagged one fails; that a ``[measured]``
              tag without an ``n``, without an apparatus version or without a method fails;
              that a list item is covered by the paragraph that introduces the list; that the
              allowlist is honoured (a file off it is never read) and that the shipped
              allowlist is the real repository's; that the documented exemptions — headings,
              table rows, fenced code, a lead-in ending in a colon, a confidence level, a
              year, a leading-zero identifier — are not claims; that a count written without
              digit grouping (``1200``) and a result standing beside a confidence interval
              *are*; that a tag written inside inline code does not cover the claim around it;
              and that ``--check`` exits non-zero while the default report exits zero.
How:          Writes small Markdown files under ``tmp_path``, points the module's ``ROOT`` at
              it with ``monkeypatch``, and calls ``check_tree`` / ``main([...])`` in process.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/claims_check.py (the code under test), docs/EVIDENCE-AND-CLAIMS.md
              (the claim-tag rule these tests enforce a shape for), .github/workflows/ci.yml
              (the claims job that runs --check)
Tested by:    (this is a test file)
Touch when:   a tag is added to the policy, the heuristic changes, or a file joins the
              allowlist (add the case here in the same change).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "claims_check", ROOT / "scripts" / "claims_check.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["claims_check"] = mod
    spec.loader.exec_module(mod)
    return mod


cc = _load()

MEASURED = (
    "[measured 2026-09-22 — a count of the job keys in the workflow file, "
    "n = 13 jobs, apparatus n/a (a repository setting, not a graded number)]"
)


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(cc, "ROOT", tmp_path)
    monkeypatch.setattr(cc, "ALLOWLIST", ("README.md",))
    return tmp_path


def _write(tree: Path, rel: str, body: str) -> None:
    (tree / rel).write_text(body, encoding="utf-8")


def test_a_tagged_claim_passes_and_an_untagged_one_fails(tree: Path) -> None:
    _write(tree, "README.md", f"# t\n\nCI runs eleven jobs on every pull request. {MEASURED}\n")
    assert cc.check_tree(tree, ("README.md",)) == []

    _write(tree, "README.md", "# t\n\nCI runs eleven jobs on every pull request.\n")
    findings = cc.check_tree(tree, ("README.md",))
    assert [f.reason for f in findings] == ["no claim tag"]
    assert findings[0].path == "README.md" and findings[0].line == 3
    assert "eleven jobs" in findings[0].sentence


def test_measured_needs_an_n_a_method_and_an_apparatus(tree: Path) -> None:
    def reasons(tag: str) -> list[str]:
        _write(tree, "README.md", f"# t\n\nCI runs eleven jobs on every pull request. {tag}\n")
        return [f.reason for f in cc.check_tree(tree, ("README.md",))]

    assert reasons(MEASURED) == []
    assert reasons("[measured]") == [
        "[measured] without n",
        "[measured] without a method",
        "[measured] without an apparatus version",
    ]
    assert reasons("[measured — counted by hand in the workflow file, apparatus 2.2]") == [
        "[measured] without n"
    ]
    assert reasons("[measured — counted by hand in the workflow file, n = 13]") == [
        "[measured] without an apparatus version"
    ]
    assert reasons("[measured n = 13, apparatus 2.2]") == ["[measured] without a method"]
    # the other three tags carry their evidence in prose; the gate asks only that they are there
    assert reasons("[aspiration]") == []
    assert reasons("[hypothesis]") == []
    assert reasons("[gap]") == []


def test_a_list_item_is_covered_by_the_paragraph_that_introduces_the_list(tree: Path) -> None:
    lead = f"Everything below is measured on the host executor posture. {MEASURED}"
    _write(tree, "README.md", f"# t\n\n{lead}\n\n- The suite ran eleven jobs, 22 of 24 green.\n")
    assert cc.check_tree(tree, ("README.md",)) == []

    _write(tree, "README.md", "# t\n\nSome prose with no claim in it.\n\n- Eleven jobs ran.\n")
    findings = cc.check_tree(tree, ("README.md",))
    assert [f.reason for f in findings] == ["no claim tag"]
    assert findings[0].line == 5


def test_the_allowlist_is_honoured_and_only_the_files_on_it_are_read(tree: Path) -> None:
    _write(tree, "README.md", "# t\n\nNothing quantified here.\n")
    _write(tree, "docs/UNCOVERED.md", "# u\n\nThe product delivers eleven changes an hour.\n")
    assert cc.check_tree(tree, ("README.md",)) == []
    assert [f.path for f in cc.check_tree(tree, ("README.md", "docs/UNCOVERED.md"))] == [
        "docs/UNCOVERED.md"
    ]


def test_a_missing_allowlisted_file_is_itself_a_finding(tree: Path) -> None:
    findings = cc.check_tree(tree, ("docs/GONE.md",))
    assert [(f.path, f.reason) for f in findings] == [
        ("docs/GONE.md", "on the allowlist but absent")
    ]


@pytest.mark.parametrize(
    "body",
    [
        "## Eleven jobs and what they gate\n\nProse.\n",  # a heading is not a claim
        "| job | n |\n|---|---|\n| lint | eleven jobs |\n",  # a table row is not examined
        "```\nCI runs eleven jobs.\n```\n",  # fenced code is not examined
        "The workflow runs three jobs in order:\n\n1. build\n",  # a lead-in to what it counts
        "Every rate carries a Wilson 95% interval and its apparatus.\n",  # a confidence level
        "Each rate carries a 95% confidence interval.\n",  # the level, written the other way
        "Each rate carries a 95% CI.\n",  # and abbreviated
        "Each rate is quoted at a confidence of 95%.\n",  # the percentage IS the confidence
        "Rule DL-0052 covers stopped items.\n",  # a leading zero is an identifier, not 52
        "The June 2026 v1 contents are tagged and frozen.\n",  # a year is not a count
        "Exactly one process reaches the model endpoint.\n",  # "one" never counts a plural
        "The package version is one number in three files.\n",  # a structural noun
        "The fixture repository carries `12 tasks` in it.\n",  # inline code is stripped
    ],
)
def test_prose_that_makes_no_claim_is_not_flagged(tree: Path, body: str) -> None:
    _write(tree, "README.md", f"# t\n\n{body}")
    assert cc.check_tree(tree, ("README.md",)) == []


@pytest.mark.parametrize(
    "body",
    [
        "The instrument reproduced 97.5% of the corpus.\n",
        "Four public libraries were mined and scored.\n",
        "The gate found 12 defects in the last sweep.\n",
        # a count is a count however it is punctuated: 1200 is not exempt for want of a comma
        "1200 tasks were completed.\n",
        "The corpus holds 12000 commits.\n",
        # a result standing beside a confidence interval is still a result
        "65% passed (Wilson 95% interval).\n",
        "97.5% passed, with a 95% confidence interval.\n",
        # the word "confidence" alone is not an interval: this is an outcome claim, and the
        # exemption used to swallow it because the "interval|level" half was optional
        "There is 65% confidence that the builder can deliver.\n",
        "The reviewer had 80% confidence in the verdict.\n",
    ],
)
def test_a_quantified_assertion_in_prose_is_a_claim(tree: Path, body: str) -> None:
    _write(tree, "README.md", f"# t\n\n{body}")
    assert [f.reason for f in cc.check_tree(tree, ("README.md",))] == ["no claim tag"]


def test_a_tag_written_inside_inline_code_does_not_cover_the_claim_around_it(tree: Path) -> None:
    """A page may document the tag vocabulary; documenting it is not claiming it."""
    body = "The run passed 12 tests; see `[hypothesis]` for the tag syntax.\n"
    _write(tree, "README.md", f"# t\n\n{body}")
    findings = cc.check_tree(tree, ("README.md",))
    assert [f.reason for f in findings] == ["no claim tag"]

    _write(tree, "README.md", "# t\n\nThe run passed 12 tests. [hypothesis]\n")
    assert cc.check_tree(tree, ("README.md",)) == []


def test_check_exits_non_zero_and_the_default_report_exits_zero(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tree, "README.md", "# t\n\nCI runs eleven jobs on every pull request.\n")
    assert cc.main(["--check", "--root", str(tree), "--allow", "README.md"]) == 1
    assert "no claim tag" in capsys.readouterr().err

    assert cc.main(["--root", str(tree), "--allow", "README.md"]) == 0
    assert "1 claim" in capsys.readouterr().out

    _write(tree, "README.md", f"# t\n\nCI runs eleven jobs. {MEASURED}\n")
    assert cc.main(["--check", "--root", str(tree), "--allow", "README.md"]) == 0


def test_the_repository_itself_passes_the_gate() -> None:
    """The allowlist is not aspirational: every file on it is clean on this tree."""
    assert cc.check_tree(ROOT, cc.ALLOWLIST) == []
    assert all((ROOT / rel).exists() for rel in cc.ALLOWLIST)


def test_the_allowlist_only_grows() -> None:
    """A page that has been cleaned never leaves the gate. CONTRIBUTING joined when PR #51's
    review found a verdict claim there that the evidence did not support."""
    assert {"README.md", "docs/RELEASING.md", "docs/CONTRIBUTING.md"} <= set(cc.ALLOWLIST)
