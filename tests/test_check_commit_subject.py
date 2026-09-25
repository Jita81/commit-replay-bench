"""scripts/check_commit_subject.py — the commit-subject gate, on subjects and a throwaway repo.

Navigation
----------
What it is:   Unit tests for the commit-subject gate (Conventional Commits, an imperative
              subject, at most 72 characters).
What it does: Pins that a well-formed subject passes and that each rule refuses its own
              defect with a reason a contributor can act on: no Conventional Commits type,
              an unknown type, a subject over 72 characters, a description that starts with
              a past tense, a gerund, a third-person verb or an article (the squash titles
              that reached ``main`` before this gate — "the work arrives from the board" —
              are the class); that ``--range`` reads every non-merge commit of a pull request
              from git and skips its merge commits; that ``--title`` checks the pull request
              title that a squash merge writes as the subject on ``main``; that ``--check``
              exits non-zero on a finding; and that CI runs the gate on pull requests under a
              job name shorter than 100 characters.
How:          Calls ``check_subject`` directly for the rules; builds a small git repository
              under ``tmp_path`` for ``--range``; reads ``.github/workflows/ci.yml`` as text.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/check_commit_subject.py (the code under test), docs/CONTRIBUTING.md
              (the commit convention it enforces), .github/workflows/ci.yml (the
              commit-subjects job that runs it)
Tested by:    (this is a test file)
Touch when:   a Conventional Commits type is added to the convention, or the imperative
              heuristic changes (add the case here in the same change).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_commit_subject", ROOT / "scripts" / "check_commit_subject.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_commit_subject"] = mod
    spec.loader.exec_module(mod)
    return mod


ccs = _load()


@pytest.mark.parametrize(
    "subject",
    [
        "feat(core): refuse deliver when the oracle is unmeasured",
        "fix(ui): stop the probe pill reading OK on a timeout",
        "docs: add the two-page summary for assurance readers",
        "ci: run the commit-subject gate on pull requests",
        "test(claims): pin that a review action needs a record",
        "refactor(ui): extract the timeout and abort guard",
        "chore!: drop the legacy census importer",
        "ci(deps): bump the github-actions group with 2 updates",
        "fix(runners): address the Maven false-green",
        "feat(core): embed the apparatus stamp in every pack",
    ],
)
def test_a_well_formed_subject_passes(subject: str) -> None:
    assert ccs.check_subject(subject) == []


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        ("Add the summary page", "not a Conventional Commits subject"),
        ("update: the summary page", "unknown type"),
        ("feat(ui) add the summary page", "not a Conventional Commits subject"),
        ("feat: " + "x" * 70, "longer than 72 characters"),
        ("feat(intake): the work arrives from the board", "not imperative"),
        ("fix(ui): fixed the probe pill", "not imperative"),
        ("fix(ui): fixing the probe pill", "not imperative"),
        ("fix(ui): fixes the probe pill", "not imperative"),
        ("docs: a summary for assurance readers", "not imperative"),
        ("feat: ", "not a Conventional Commits subject"),
    ],
)
def test_each_rule_refuses_its_defect(subject: str, reason: str) -> None:
    problems = ccs.check_subject(subject)
    assert problems, subject
    assert any(reason in p for p in problems), problems


def test_the_squash_titles_that_reached_main_would_have_been_refused() -> None:
    # PR #48's title, as it landed on main: too long, and not in the imperative
    title = (
        "feat(intake,factory,ci): the work arrives from the board — a ticket in a watched "
        "column becomes the backlog item, and the factory writes its own failing test (wave 1)"
    )
    problems = ccs.check_subject(title)
    assert any("longer than 72 characters" in p for p in problems)
    assert any("not imperative" in p for p in problems)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "commit.gpgsign", "false")
    (r / "a").write_text("0")
    _git(r, "add", "a")
    _git(r, "commit", "-q", "-m", "chore: start")
    return r


def _commit(repo: Path, name: str, subject: str) -> None:
    (repo / name).write_text(subject)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", subject)


def test_range_reads_every_non_merge_commit_and_skips_merges(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "b", "feat: add b")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "c", "fix: repair c")
    _git(repo, "merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
    head = _git(repo, "rev-parse", "HEAD")
    assert ccs.main(["--repo", str(repo), "--range", f"{base}..{head}", "--check"]) == 0

    _commit(repo, "d", "Updated d")
    head = _git(repo, "rev-parse", "HEAD")
    assert ccs.main(["--repo", str(repo), "--range", f"{base}..{head}", "--check"]) == 1
    # the default report exits zero; --check is what CI runs
    assert ccs.main(["--repo", str(repo), "--range", f"{base}..{head}"]) == 0


def test_title_is_checked_because_a_squash_merge_writes_it_on_main(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    ok = ["--repo", str(repo), "--range", f"{head}..{head}", "--check"]
    assert ccs.main([*ok, "--title", "docs: add the summary"]) == 0
    assert ccs.main([*ok, "--title", "docs: the summary, and more"]) == 1


def test_ci_runs_the_gate_on_pull_requests_under_a_short_job_name() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/check_commit_subject.py" in ci
    assert re.search(r"^  commit-subjects:\s*$", ci, re.M)
    # every job's `name:` stays under 100 characters (branch protection matches on it)
    for name in re.findall(r"^    name: (.+)$", ci, re.M):
        assert len(name.strip().strip('"')) < 100, name
