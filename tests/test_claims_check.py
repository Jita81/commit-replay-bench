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
              that ``--check`` exits non-zero while the default report exits zero; and that
              every numbered action in a review's Actions table has a record in
              docs/DECISION-LOG.md that names the review, the action and its state — so an
              action cannot disappear without one (the critical friend's #8 and #9 did).
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


# ─── a review's actions never disappear without a record ────────────────────────────────

REVIEW = (
    "# A review\n\n## 8. Actions, in priority order\n\n"
    "| # | Action | Kind | Owner |\n|---|---|---|---|\n"
    "| 1 | Extend belt 1. | product | core |\n"
    "| 2 | Rotate the token. | security | operator |\n\n"
    "## 9. What the evidence licenses\n\n| 3 | not an action | x | y |\n"
)


def _review_tree(tree: Path, log_rows: str) -> None:
    (tree / "docs" / "reviews").mkdir(parents=True, exist_ok=True)
    _write(tree, "docs/reviews/2026-09-13-friend.md", REVIEW)
    _write(
        tree, "docs/DECISION-LOG.md", f"# Decision log\n\n| Id | Decision |\n|---|---|\n{log_rows}"
    )


def test_a_review_action_without_a_record_is_a_finding(tree: Path) -> None:
    _review_tree(tree, "| DL-001 | Something else entirely. |\n")
    findings = cc.check_review_actions(tree)
    assert [(f.path, f.reason) for f in findings] == [
        ("docs/reviews/2026-09-13-friend.md", "review action #1 has no record"),
        ("docs/reviews/2026-09-13-friend.md", "review action #2 has no record"),
    ]
    # only the Actions table is read: row 3 sits under the next heading
    assert all("#3" not in f.reason for f in findings)


def test_a_record_names_the_review_the_action_and_its_state(tree: Path) -> None:
    rows = (
        "| DL-002 | `2026-09-13-friend` action #1: closed (ADR-0001); "
        "action #2: [gap] no dated rotation is on record. |\n"
    )
    _review_tree(tree, rows)
    assert cc.check_review_actions(tree) == []

    # a mention without a state is not a record: "action #2" alone says nothing about it
    _review_tree(tree, "| DL-002 | `2026-09-13-friend` action #1: closed; action #2 is noted. |\n")
    assert [f.reason for f in cc.check_review_actions(tree)] == ["review action #2 has no record"]

    # the record must name the review it closes: another review's #2 is not this one's
    _review_tree(
        tree,
        "| DL-002 | `2026-09-13-friend` action #1: closed. |\n"
        "| DL-003 | `2026-09-14-other` action #2: closed. |\n",
    )
    assert [f.reason for f in cc.check_review_actions(tree)] == ["review action #2 has no record"]


def test_main_fails_on_an_unrecorded_review_action(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tree, "README.md", "# t\n\nNothing quantified here.\n")
    _review_tree(tree, "| DL-001 | nothing |\n")
    assert cc.main(["--check", "--root", str(tree), "--allow", "README.md"]) == 1
    assert "review action #1 has no record" in capsys.readouterr().err


def test_every_review_action_in_the_repository_has_a_record() -> None:
    """The critical friend's ten actions (2026-09-13 §8) each carry a dated state."""
    assert cc.check_review_actions(ROOT) == []


def test_a_state_is_a_whole_word(tree: Path) -> None:
    """``opening`` is not ``open``: a state must stand as a word, or any prose passes."""
    rows = "| DL-002 | `2026-09-13-friend` action #1: closed; action #2: opening soon. |\n"
    _review_tree(tree, rows)
    assert [f.reason for f in cc.check_review_actions(tree)] == ["review action #2 has no record"]


def test_a_recorded_action_that_left_its_review_is_a_finding(tree: Path) -> None:
    """The record and the table are checked both ways, so neither can vanish alone: an
    action recorded in the log but gone from the review's Actions table (a deleted row, a
    renamed heading) is a finding against the decision log."""
    rows = (
        "| DL-002 | `2026-09-13-friend` action #1: closed; action #2: open; "
        "action #3: [gap] a third action. |\n"
    )
    _review_tree(tree, rows)
    assert [(f.path, f.reason) for f in cc.check_review_actions(tree)] == [
        (
            "docs/DECISION-LOG.md",
            "2026-09-13-friend action #3 is recorded but the review has no such action",
        ),
    ]

    # renaming the heading empties the table as the checker reads it: every record now
    # points at an action the review no longer lists
    _review_tree(tree, "| DL-002 | `2026-09-13-friend` action #1: closed; action #2: open. |\n")
    renamed = REVIEW.replace("## 8. Actions, in priority order", "## 8. Next steps")
    _write(tree, "docs/reviews/2026-09-13-friend.md", renamed)
    assert [f.reason for f in cc.check_review_actions(tree)] == [
        "2026-09-13-friend action #1 is recorded but the review has no such action",
        "2026-09-13-friend action #2 is recorded but the review has no such action",
    ]


#: The critical friend's Actions table (2026-09-13 §8) as it was reviewed: ten actions.
#: Deleting a row AND its record together passes the two-way check, so the set is pinned.
CRITICAL_FRIEND = "2026-09-13-critical-friend"


def test_the_critical_friends_ten_actions_are_all_still_listed() -> None:
    text = (ROOT / "docs" / "reviews" / f"{CRITICAL_FRIEND}.md").read_text(encoding="utf-8")
    assert [n for n, _ in cc.review_actions(text)] == list(range(1, 11))
    log = (ROOT / "docs" / "DECISION-LOG.md").read_text(encoding="utf-8")
    assert cc.recorded_actions(log, CRITICAL_FRIEND) == set(range(1, 11))
