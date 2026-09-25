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
              exits non-zero on a finding; that each allowlisted exception is a whole word the
              rule needs, so no suffix is exempt ("agreed" is refused); and that CI runs the
              gate on pull requests, again when a title is edited, and on a push to main,
              under a job name shorter than 100 characters, with no trigger that checks
              nothing (read from the steps' ``if:`` conditions, never the whole file), and
              no push run cancelled by the next push.
How:          Calls ``check_subject`` directly for the rules; builds a small git repository
              under ``tmp_path`` for ``--range``; reads the workflow files as text.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/check_commit_subject.py (the code under test), docs/CONTRIBUTING.md
              (the commit convention it enforces), .github/workflows/commit-subjects.yml
              (the job that runs it, re-run when a title is edited)
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
        "fix(worker): need a clone before the fetch",
        "feat(mine): seed the pool from the newest commits",
        "perf(repos): speed up the pool's history walk",
        "fix(factory): proceed only when the RED proof holds",
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


#: Past tenses that end in ``-eed`` (review of PR #54: a blanket ``-eed`` exemption let
#: "Agreed migration plan" through). The heuristic refuses each one.
PAST_TENSE_EED = ("agreed", "freed", "guaranteed", "decreed", "refereed", "disagreed")


@pytest.mark.parametrize("word", PAST_TENSE_EED)
def test_a_past_tense_ending_in_eed_is_refused(word: str) -> None:
    problems = ccs.check_subject(f"docs: {word.capitalize()} migration plan")
    assert any("not imperative" in p for p in problems), (word, problems)


@pytest.mark.parametrize(
    ("allowlist", "suffix"),
    [("ENDS_ED_OK", "ed"), ("ENDS_ING_OK", "ing"), ("ENDS_S_OK", "s")],
)
def test_every_exception_is_a_whole_word_the_rule_would_otherwise_refuse(
    allowlist: str, suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exceptions are whole words, never a suffix: each allowlisted word passes, and each
    is refused once it is taken off its list — so every entry is needed, and a word that is
    not on the list is judged by the rule. A suffix-wide exemption (the ``-eed`` one) could
    not be written as an entry here, which is the point."""
    words = getattr(ccs, allowlist)
    assert words, allowlist
    for word in sorted(words):
        assert word.endswith(suffix), (allowlist, word)
        assert ccs.check_subject(f"feat: {word} the thing") == [], word
        monkeypatch.setattr(ccs, allowlist, frozenset(words - {word}))
        assert ccs.check_subject(f"feat: {word} the thing"), f"{word} is not needed on the list"
        monkeypatch.setattr(ccs, allowlist, words)


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
    # the job moved to its own workflow so an edited title re-runs it (see the next test)
    ci = _workflow_with("commit-subjects").read_text(encoding="utf-8")
    assert "scripts/check_commit_subject.py" in ci
    # every job's `name:` in every workflow stays under 100 characters (branch protection
    # matches on it)
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for name in re.findall(r"^    name: (.+)$", wf.read_text(encoding="utf-8"), re.M):
            assert len(name.strip().strip('"')) < 100, (wf.name, name)


def _workflow_with(job: str) -> Path:
    """The one workflow file under .github/workflows that defines ``job``."""
    hits = [
        p
        for p in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        if re.search(rf"^  {re.escape(job)}:\s*$", p.read_text(encoding="utf-8"), re.M)
    ]
    assert len(hits) == 1, hits
    return hits[0]


def test_an_edited_title_is_checked_again() -> None:
    """The title is checked because a squash merge writes it on main, so a title edited
    after CI passed must be re-checked: the gate's workflow listens for ``edited``. It sits
    in its own workflow so that editing a description does not re-run the whole CI."""
    wf = _workflow_with("commit-subjects")
    text = wf.read_text(encoding="utf-8")
    on = re.search(r"^on:\n((?:[ #].*\n|\n)+)", text, re.M)
    assert on, f"{wf.name} has no top-level on: block"
    pr = re.search(r"^  pull_request:\n    types: \[([^\]]*)\]", on.group(1), re.M)
    assert pr, f"{wf.name}: pull_request must list its types"
    types = {t.strip() for t in pr.group(1).split(",")}
    assert {"opened", "synchronize", "reopened", "edited"} <= types, types
    assert wf.name != "ci.yml", "an edited description must not re-run the whole CI"
    # the squash subject that actually landed is checked on main too (detection: the merge
    # dialog can rewrite the title after the last pull-request check)
    assert re.search(r"^  push:\n    branches: \[main\]", on.group(1), re.M)
    assert "github.event.before" in text and "github.event.after" in text


def _triggers(text: str) -> set[str]:
    """The event names under a workflow's top-level ``on:`` block."""
    on = re.search(r"^on:\n((?:[ #].*\n|\n)+)", text, re.M)
    assert on, "no top-level on: block"
    return set(re.findall(r"^  ([a-z_]+):", on.group(1), re.M))


def _unchecked_triggers(text: str) -> set[str]:
    """The triggers of a workflow that no step's ``if:`` condition names. Only the ``if:``
    lines are read: the concurrency block names events too, and it runs no check."""
    conditions = re.findall(r"^\s+if: (.+)$", text, re.M)
    checked = {e for c in conditions for e in re.findall(r"github\.event_name == '([a-z_]+)'", c)}
    return _triggers(text) - checked


def test_every_trigger_of_the_gate_runs_a_check() -> None:
    """Every step that runs the gate is conditioned on an event, so a trigger that no step
    names would run the job, check nothing and report success (review of PR #54: a manual
    ``workflow_dispatch`` did exactly that). Each trigger must be one a gate step runs on."""
    text = _workflow_with("commit-subjects").read_text(encoding="utf-8")
    unchecked = _unchecked_triggers(text)
    assert not unchecked, f"triggers that run no check and would pass: {sorted(unchecked)}"


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_a_step_that_names_the_wrong_event_is_caught(event: str) -> None:
    """The check above must read the steps, not the whole file: the concurrency block also
    names ``push`` and ``pull_request``, so a step condition misspelt as ``'pushed'`` would
    check nothing on that trigger and still pass a whole-file search (review of PR #54)."""
    text = _workflow_with("commit-subjects").read_text(encoding="utf-8")
    step_if = f"        if: github.event_name == '{event}'"
    assert step_if in text, f"no gate step runs on {event}"
    broken = text.replace(step_if, f"        if: github.event_name == '{event}ed'")
    assert _unchecked_triggers(broken) == {event}


def _concurrency(text: str) -> tuple[str, str]:
    """``(group, cancel-in-progress)`` of a workflow's top-level concurrency block."""
    block = re.search(r"^concurrency:\n((?:  .*\n)+)", text, re.M)
    assert block, "no top-level concurrency block"
    group = re.search(r"^  group: (.+)$", block.group(1), re.M)
    cancel = re.search(r"^  cancel-in-progress: (.+)$", block.group(1), re.M)
    return (group.group(1) if group else "", cancel.group(1).strip() if cancel else "false")


def test_a_check_scoped_to_one_push_is_never_cancelled_by_the_next() -> None:
    """A check that reads ``github.event.before..after`` sees only what its own push brought,
    so a later push cannot stand in for it: if the second push to main cancelled the first
    run, the first push's subjects would never be checked (review of PR #54). Any workflow
    that checks a push's own range gives each push run its own concurrency group (keyed on
    the run id) and cancels only superseded pull-request runs. CI's whole-tree jobs are not
    this class: the newer run checks a tree that contains the older one."""
    scoped = [
        p
        for p in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        if "github.event.before" in p.read_text(encoding="utf-8")
    ]
    assert scoped, "the commit-subjects workflow checks a push's own range"
    for wf in scoped:
        text = wf.read_text(encoding="utf-8")
        if not re.search(r"^concurrency:", text, re.M):
            continue  # no group: nothing is ever cancelled
        group, cancel = _concurrency(text)
        assert "github.run_id" in group and "'push'" in group, (wf.name, group)
        assert cancel != "true", f"{wf.name}: cancel-in-progress must not apply to a push run"
        assert "'pull_request'" in cancel, (wf.name, cancel)
