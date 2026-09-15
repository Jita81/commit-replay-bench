"""The honest-shell corpus: the guard's regression suite against FALSE POSITIVES.

Critical-friend review 2026-09-13 (§4.2 reading 2, §5 play 04): four honest builds
became "protocol violation" rows because :class:`GitArchaeologyGuard` refused
ordinary developer shell (``$(pwd)``, quoted parentheses, ``python -m pip``, ``npx``).
Each was fixed after a build was lost. This module makes the NEXT one fail a test
first:

* every line of ``tests/fixtures/shell_corpus.txt`` (honest shell an agent runs while
  fixing a bug in a Python / Go / JS / JVM / Rust repo, including the exact
  ``sighted_test_command`` shapes the adapter puts in the brief) must return ``""``;
* every line of ``tests/fixtures/shell_corpus_refused.txt`` must be refused with the
  reason prefix the corpus states (``archaeology:`` / ``network:``).

Baseline, measured before the guard was fixed (on the first 414 honest / 406 refused
lines): the old guard refused 45 honest lines and let 149 refused lines through, with 15
reasons mislabelled (``git fetch`` as archaeology). The corpus then grew by 16 / 35 lines
for the 2026-09-14 inline-code addendum. After the fix: 0 / 0 / 0.

Both corpora run with a worktree-shaped ``cwd`` (``node_modules/.bin`` holding the
usual test binaries, a few source dirs) because the fixed guard *verifies* ``npx``
targets and ``git diff`` path arguments against the worktree instead of guessing.

Navigation
----------
What it is:   The honest-shell corpus — the guard's regression suite against FALSE POSITIVES
              (critical-friend review 2026-09-13, §4.2 / §5).
What it does: Pins that every line of ``tests/fixtures/shell_corpus.txt`` (honest shell an agent
              runs while fixing a bug in Python / Go / JS / JVM / Rust repositories, including the
              adapter's ``sighted_test_command`` shapes) is allowed and every line of
              ``tests/fixtures/shell_corpus_refused.txt`` is refused with the labelled prefix;
              that the corpora are substantial (≥ 150 / ≥ 60); that ``git stash`` is refused in
              every form with the reason (the stash stack is shared across worktrees); the
              ``npx`` policy (honest and offline exactly when ``node_modules/.bin/<bin>`` exists in
              the worktree; fail closed without); and that the 19 decider-settled refusal groups
              are pinned with provenance. Baseline before the fix: 45 honest refused / 149
              refused let through / 15 mislabelled; after: 0 / 0 / 0.
How:          Both corpora parametrised line by line through ``GitArchaeologyGuard`` with a
              worktree-shaped ``cwd`` (module-scoped) so ``npx`` targets and ``git diff`` paths
              are verified, not guessed.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/base.py (the guard under test), tests/fixtures/shell_corpus.txt
              and tests/fixtures/shell_corpus_refused.txt (the corpora), src/crb/core/learn.py
              (``apply_triage`` appends a human's decisions to these files),
              tests/test_builders_base.py (the guard's unit cases), docs/LEARNING-LOOP.md
Tested by:    tests/test_builders_guard_corpus.py
Touch when:   a builder is refused an honest command in a client repository (append the exact
              line to the honest corpus — through ``crb learn refusals --apply`` with a named
              decider — and let this suite fail before the guard is touched); a new refused
              shape is found (the refused corpus, with its ``archaeology:`` / ``network:`` label).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from crb.builders import base
from crb.builders.base import GitArchaeologyGuard

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
from builders_repo import make_fixture  # noqa: E402

HONEST = _FIXTURES / "shell_corpus.txt"
REFUSED = _FIXTURES / "shell_corpus_refused.txt"
PREFIXES = ("archaeology:", "network:")

#: binaries the corpus invokes through ``npx`` / ``npm exec`` — present in the fixture cwd
LOCAL_BINS = ("jest", "vitest", "mocha", "eslint", "standard", "tsc", "prettier")
#: paths the corpus names bare after ``git diff`` / ``git checkout`` (existence-verified)
LOCAL_PATHS = ("src/click/core.py", "pkg/command.go", "lib/request.js", "tests/x.py")


def _decode(raw: str) -> str:
    """Corpus lines carry the two-character sequence ``\\n`` for a real newline."""
    return raw.replace("\\n", "\n")


def load_corpus(path: Path) -> list[str]:
    """The non-blank, non-comment lines of a corpus file, backslash-n sequences decoded."""
    return [
        _decode(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def load_refused(path: Path) -> list[tuple[str, str]]:
    """``(command, prefix)`` pairs from the refused corpus; a line without a known prefix is a
    corpus error, not a test failure.
    """
    out: list[tuple[str, str]] = []
    for line in load_corpus(path):
        cmd, tab, prefix = line.partition("\t")
        assert tab, f"refused corpus line needs '<command><TAB><prefix>': {line!r}"
        prefix = prefix.strip()
        assert prefix in PREFIXES, f"unknown prefix {prefix!r} for {cmd!r}"
        out.append((cmd, prefix))
    return out


HONEST_LINES = load_corpus(HONEST)
REFUSED_LINES = load_refused(REFUSED)


@pytest.fixture(scope="module")
def worktree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A worktree-shaped ``cwd``: the usual test binaries under ``node_modules/.bin`` plus a few
    source paths, so ``npx`` targets and path arguments are verified against something real.
    """
    root = tmp_path_factory.mktemp("guard-corpus-wt")
    for b in LOCAL_BINS:
        p = root / "node_modules" / ".bin" / b
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#!/bin/sh\n", encoding="utf-8")
    for rel in LOCAL_PATHS:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    for d in ("packages/core", "doc", "src/main/java"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="module")
def guard(worktree: Path) -> GitArchaeologyGuard:
    """The guard bound to the worktree ``cwd`` (module-scoped: the corpus is large)."""
    return GitArchaeologyGuard(cwd=worktree)


def test_corpora_are_substantial() -> None:
    """The review asked for a corpus, not a sample: ≥150 honest, ≥60 refused lines."""
    assert len(HONEST_LINES) >= 150, len(HONEST_LINES)
    assert len(REFUSED_LINES) >= 60, len(REFUSED_LINES)
    assert len(set(HONEST_LINES)) == len(HONEST_LINES), "duplicate honest lines"
    honest_set = set(HONEST_LINES)
    overlap = [c for c, _ in REFUSED_LINES if c in honest_set]
    assert not overlap, f"a line cannot be both honest and refused: {overlap}"


@pytest.mark.parametrize("command", HONEST_LINES, ids=lambda c: c[:60])
def test_honest_shell_is_never_refused(guard: GitArchaeologyGuard, command: str) -> None:
    reason = guard.check_shell(command)
    assert reason == "", f"FALSE POSITIVE on honest shell:\n  {command!r}\n  -> {reason}"


@pytest.mark.parametrize(("command", "prefix"), REFUSED_LINES, ids=lambda x: str(x)[:60])
def test_dishonest_shell_is_refused_with_the_right_label(
    guard: GitArchaeologyGuard, command: str, prefix: str
) -> None:
    reason = guard.check_shell(command)
    assert reason, f"BYPASS: {command!r} was allowed"
    assert reason.startswith(prefix), f"{command!r}: expected {prefix} got {reason!r}"


def test_summary_counts(capsys: pytest.CaptureFixture[str]) -> None:
    """One line of counts for the report (``pytest -s`` shows it)."""
    by_prefix = {p: sum(1 for _, q in REFUSED_LINES if q == p) for p in PREFIXES}
    print(
        f"\nshell corpus: {len(HONEST_LINES)} honest lines pass; "
        f"{len(REFUSED_LINES)} refused lines ({by_prefix['archaeology:']} archaeology, "
        f"{by_prefix['network:']} network) refused with the right label"
    )
    assert by_prefix["archaeology:"] > 0 and by_prefix["network:"] > 0


# ---------------------------------------------------------------------------
# Ownership decisions the corpus encodes
# ---------------------------------------------------------------------------


def test_shell_edits_to_tests_are_belt_1_not_the_shell_guard(tmp_path: Path) -> None:
    """``sed -i`` on a test file through the shell is NOT the shell guard's job: it is
    path-blind and cannot classify tests (detecting writes in arbitrary shell is
    unbounded). Belt 1 — :meth:`~crb.builders.base.TestFileGuard.tampered` over the worktree bytes — owns
    it and catches the edit however it was made. Both halves of that decision are
    asserted here so a future "helpful" shell-side check cannot silently take over."""
    g = GitArchaeologyGuard(cwd=tmp_path)
    for cmd in (
        "sed -i 's/a - b/a + b/' pkg/calc_test.go",
        "sed -i '' 's/assert add(2, 3) == 5/pass/' tests/test_calc.py",
        "echo 'def test_x(): pass' > tests/test_new.py",
        "cp /tmp/mine.py tests/test_calc.py",
    ):
        assert g.check_shell(cmd) == "", cmd  # path-blind by design

    fx = make_fixture(tmp_path / "repo")
    ws = fx.workspace(tmp_path / "wt", mode="sighted")
    try:
        tfg = base.TestFileGuard(ws.root, fx.config, fx.task.test_files, mode="sighted")
        assert tfg.tampered(ws) == []
        # the "shell edit": bytes change on disk, no tool call involved
        target = ws.root / "tests" / "test_calc.py"
        target.write_text(target.read_text(encoding="utf-8").replace("== 5", "== 5 or True"))
        (ws.root / "tests" / "test_new.py").write_text("def test_x():\n    pass\n")
        assert tfg.tampered(ws) == ["tests/test_calc.py", "tests/test_new.py"]
    finally:
        ws.remove()


def test_git_stash_refused_in_every_form_and_says_why(guard: GitArchaeologyGuard) -> None:
    """Policy (2026-09-13): the stash stack is shared across every worktree of the clone
    (measured: ``git stash list``/``show -p``/``pop`` in one worktree reach and steal
    another worktree's entry), so no subset of ``git stash`` is safe. The refusal names
    the working-tree-only idiom the builder should use instead — and that idiom passes."""
    for cmd in (
        "git stash",
        "git stash push -m wip",
        "git stash list",
        "git stash show -p stash@{0}",
        "git stash apply",
        "git stash pop",
        "git stash drop",
        "git stash && npm test 2>&1 | tail -10; git stash pop",
    ):
        reason = guard.check_shell(cmd)
        assert reason.startswith("archaeology: 'git stash'"), (cmd, reason)
        assert "shared" in reason and "git checkout -- <paths>" in reason
    idiom = (
        "git diff > /tmp/mine.patch && git checkout -- lib/request.js && npm test 2>&1 | tail -5; "
        "git apply /tmp/mine.patch"
    )
    assert guard.check_shell(idiom) == ""


def test_npx_policy_local_bin_verified_against_cwd(
    guard: GitArchaeologyGuard, tmp_path: Path
) -> None:
    """``npx <bin>`` is honest and offline exactly when ``node_modules/.bin/<bin>`` exists
    at the (cd-tracked) cwd or an ancestor up to the worktree root. Without a cwd the
    guard cannot verify and refuses (as before); ``--no-install`` is offline by
    construction and passes anywhere."""
    assert guard.check_shell("npx jest test/foo.test.js") == ""
    assert guard.check_shell("npm exec -- jest test/foo.test.js") == ""
    assert guard.check_shell("cd packages/core && npx vitest run") == ""  # hoisted to root
    assert "not in node_modules/.bin" in guard.check_shell("npx some-tool-not-installed")
    assert "names a package" in guard.check_shell("npx jest@29")
    assert "may fetch" in guard.check_shell("npx -p typescript tsc")
    blind = GitArchaeologyGuard()
    assert "cannot be verified" in blind.check_shell("npx jest")
    assert blind.check_shell("npx --no-install jest") == ""
    assert blind.check_shell("npx --no jest") == ""
    # a sub-project's own bin, below the worktree root
    sub = tmp_path / "packages" / "web"
    (sub / "node_modules" / ".bin").mkdir(parents=True)
    (sub / "node_modules" / ".bin" / "webpack").write_text("")
    g = GitArchaeologyGuard(cwd=tmp_path)
    assert g.check_shell("cd packages/web && npx webpack --mode development") == ""
    assert "not in node_modules/.bin" in g.check_shell("npx webpack")  # not at the root


# ---------------------------------------------------------------------------
# The 2026-09-14 decider's verdicts (fable-rationale §4): 9 honest / 10 refuse
# ---------------------------------------------------------------------------

#: Every corpus line the decider pinned carries this provenance comment shape.
DECIDED_MARK = "# decided 2026-09-14 by fable-decider from "


def _decided_lines(path: Path) -> list[str]:
    """The corpus lines that directly follow a ``# decided …`` provenance comment."""
    out: list[str] = []
    pending = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(DECIDED_MARK):
            pending = True
            continue
        if pending and raw.strip() and not raw.startswith("#"):
            out.append(_decode(raw))
            pending = False
    return out


def test_the_decided_groups_are_all_pinned_with_provenance() -> None:
    """The independent decider settled the 19 refusal groups of the NHS + public
    measurement: 9 honest, 10 refused. Each verdict is a corpus line that follows a
    ``# decided 2026-09-14 by fable-decider from <repo>/<task>`` comment, so the guard
    can regress on none of them silently."""
    honest = _decided_lines(HONEST)
    refused = _decided_lines(REFUSED)
    assert len(honest) == 9, honest
    assert len(refused) == 10, refused
    assert all(cmd in HONEST_LINES for cmd in honest)
    assert all(
        cmd in {c for c, _ in REFUSED_LINES} for cmd in (r.partition("\t")[0] for r in refused)
    )
    # the one verdict that overturned the pre-fill: koa's own linter is honest to run
    assert "npx standard lib/request.js 2>&1" in honest
    # every git stash form the measurement produced stays refused
    assert sum(1 for r in refused if r.startswith("git stash")) == 3


def test_npx_standard_is_honest_with_the_worktree_cwd_and_fail_closed_without(
    guard: GitArchaeologyGuard,
) -> None:
    """The decider's finding on ``npx standard lib/request.js`` (group a6d6356ee5430e7e):
    the board's "not in node_modules/.bin" came from a cwd-less check — the guard's
    documented fail-closed path — not from koa. With the worktree as cwd (koa's
    ``node_modules/.bin/standard``, a direct devDependency, ``scripts.lint``, belt 5's
    tool) it is ALLOWED. Triage must always evaluate a refusal with the row's cwd."""
    assert guard.check_shell("npx standard lib/request.js 2>&1") == ""
    assert guard.check_shell("npx tsc --build 2>&1 | tail -60") == ""
    blind = GitArchaeologyGuard()
    reason = blind.check_shell("npx standard lib/request.js 2>&1")
    assert reason.startswith("network:") and "cannot be verified" in reason
    # the stash refusal's message names the diff/checkout idiom (the decider asked for the
    # message to be asserted, not only the prefix, so it cannot regress)
    reason = guard.check_shell("git stash && node --test 2>&1 | tail -10; git stash pop")
    assert "git diff > /tmp/mine.patch" in reason and "git apply /tmp/mine.patch" in reason
    assert "shared with every other worktree" in reason
