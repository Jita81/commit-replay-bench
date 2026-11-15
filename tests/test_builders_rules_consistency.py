"""What a builder is told agrees with what is enforced.

The rules text (``DEFAULT_RULES``, every builder's task; claude_code's ``system_rules``) and
the guard's refusal messages are the builder's only description of the protocol. A sentence
there that the enforcement contradicts costs honest builds: the earlier stash advice named
``git checkout -- <paths>``, which claude_code's own deny rules refuse, and the rules said
every violation disqualifies when only tampering does. This module holds the text to the
enforcement:

* every backticked command in the rules and in the stash refusal passes the real guard
  (with and without a cwd) and matches no ``DENY_RULES`` entry;
* the one "run the tests without my edits" line does what it says on a real worktree with a
  staged edit and a staged sighted overlay, and leaves new untracked files alone;
* the rules name both outcomes, that a refused command still counts, and the unparseable
  forms; claude_code's rules name exactly the git set its deny rules refuse;
* every "could not parse" refusal names its real cause.
* no rule forbids the facts a blind context-set brief lists, and a blind brief is never
  told to finish on a target test command it was not handed.

Navigation
----------
What it is:   The rules/enforcement cross-check for builder briefs and guard refusal messages.
What it does: Extracts every backticked command from ``DEFAULT_RULES``, ``system_rules(…)``
              and the ``git stash`` refusal and checks each against ``GitArchaeologyGuard``
              (with and without a cwd) and an emulation of claude_code's ``DENY_RULES``
              matching; runs the test-without-my-edits line on a real git worktree; pins the
              outcome sentences, the refused git set and the parse-refusal causes.
How:          Plain asserts over the module constants and a throwaway ``git init`` worktree.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/base.py (``DEFAULT_RULES``, ``STASH_FREE_IDIOM``, the guard),
              src/crb/builders/claude_code.py (``system_rules``, ``DENY_RULES``),
              src/crb/builders/openai_agent.py (``SYSTEM_PROMPT``: no shell idiom)
Tested by:    tests/test_builders_rules_consistency.py
Touch when:   never for a new repository; the rules text, a guard refusal message or a
              deny rule changes.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from crb.builders import claude_code as cc
from crb.builders.base import (
    DEFAULT_RULES,
    STASH_FREE_IDIOM,
    Budget,
    BuildBrief,
    GitArchaeologyGuard,
)
from crb.builders.brief import ContextEntry, Ticket, compose
from crb.builders.openai_agent import SYSTEM_PROMPT

#: What a placeholder in the advised line stands for when the line is checked or run.
PATHS = "src/x.py"
TESTS = "python -m pytest -q tests/test_x.py"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "wt"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "src").mkdir()
    (root / "src" / "x.py").write_text("x = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test(): pass\n")
    _git(root, "add", ".")
    _git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "i")
    return root


def deny_hit(command: str) -> str:
    """An EMULATION of how the Claude Code CLI matches ``Bash(<prefix>:*)`` deny rules — the
    CLI's matcher is not importable here, so this is an inferred model, not the CLI: the line
    is split at ``;`` ``&&`` ``||`` ``|`` ``&`` and newlines, leading ``VAR=value``
    assignments are dropped, and a sub-command is refused when it equals a prefix or starts
    with the prefix and a space. Returns the matching rule or ``""``."""
    prefixes = [r[5:-3] for r in cc.DENY_RULES if r.startswith("Bash(") and r.endswith(":*)")]
    for sub in re.split(r"\|\||&&|[;|&\n]", command):
        s = re.sub(r"^(\w+=\S*\s+)+", "", sub.strip())
        for p in prefixes:
            if s == p or s.startswith(p + " "):
                return f"Bash({p}:*)"
    return ""


def _stash_refusal() -> str:
    return GitArchaeologyGuard().check_shell("git stash")


def _told() -> dict[str, str]:
    return {
        "DEFAULT_RULES": DEFAULT_RULES,
        "system_rules": cc.system_rules(Budget(), sighted=True),
        "system_rules (blind)": cc.system_rules(Budget(), sighted=False),
        "stash refusal": _stash_refusal(),
    }


def _backticked(text: str) -> list[str]:
    return [
        m.replace("<paths>", PATHS).replace("<tests>", TESTS)
        for m in re.findall(r"`([^`]+)`", text)
    ]


def test_every_command_the_builder_is_told_passes_the_guard_and_no_deny_rule(
    worktree: Path,
) -> None:
    commands = {(where, c) for where, text in _told().items() for c in _backticked(text)}
    assert {w for w, _ in commands} == {
        "system_rules",
        "system_rules (blind)",
        "stash refusal",
    }  # none lost
    with_cwd, without_cwd = GitArchaeologyGuard(cwd=worktree), GitArchaeologyGuard()
    for where, command in sorted(commands):
        assert with_cwd.check_shell(command) == "", (where, command)
        assert without_cwd.check_shell(command) == "", (where, command)
        assert deny_hit(command) == "", (where, command)
    # the emulation does catch what the earlier advice said (it is not vacuous)
    assert deny_hit("git diff > /tmp/p; git checkout -- src/x.py") == "Bash(git checkout:*)"


def test_the_advised_line_is_the_same_everywhere_and_never_git_dash_c() -> None:
    told = _told()
    assert f"`{STASH_FREE_IDIOM}`" in told["system_rules"]
    assert f"`{STASH_FREE_IDIOM}`" in told["system_rules (blind)"]
    assert f"`{STASH_FREE_IDIOM}`" in told["stash refusal"]
    assert "git -C" not in STASH_FREE_IDIOM
    # openai_agent has no shell and cannot write the worktree under docker: no shell idiom
    assert STASH_FREE_IDIOM not in DEFAULT_RULES and "git apply" not in SYSTEM_PROMPT


def test_the_advised_line_runs_the_tests_on_the_parent_and_restores_the_edits(
    worktree: Path, tmp_path: Path
) -> None:
    """On a real worktree: a staged AND an unstaged edit of the same file, the sighted overlay
    staged by checkout, and a new untracked file. While the tests run the source is at HEAD
    and the overlay is untouched; afterwards every edit is back; the untracked file is never
    in the patch (it stays on disk throughout)."""
    src, test = worktree / "src" / "x.py", worktree / "tests" / "test_x.py"
    src.write_text("x = 2\n")
    _git(worktree, "add", "src/x.py")
    src.write_text("x = 3\n")  # staged + unstaged
    test.write_text("def test(): assert 1\n")
    _git(worktree, "add", "tests/test_x.py")  # the overlay, staged as checkout stages it
    (worktree / "src" / "new.py").write_text("NEW = 1\n")
    patch = tmp_path / "mine.patch"
    line = (
        STASH_FREE_IDIOM.replace("/tmp/mine.patch", str(patch))
        .replace("<paths>", PATHS)
        .replace("<tests>", "cat src/x.py tests/test_x.py src/new.py")
    )
    seen = subprocess.run(
        ["sh", "-c", line], cwd=worktree, capture_output=True, text=True, check=True
    ).stdout
    assert seen == "x = 1\ndef test(): assert 1\nNEW = 1\n"
    assert src.read_text() == "x = 3\n" and test.read_text() == "def test(): assert 1\n"
    assert "new.py" not in patch.read_text()


def test_the_rules_name_both_outcomes_refused_commands_and_unparseable_forms() -> None:
    rules = DEFAULT_RULES
    assert "tampering: the run is DISQUALIFIED" in rules
    assert "ALL your source edits are discarded and the run fails" in rules
    assert "even when the tool refuses to run it" in rules
    for form in (
        "cannot be parsed",
        "unterminated quote",
        "sh -c or env -S string",
        "unbalanced $( )",
        "backtick",
        "here-document without a tag",
        "nested too deep",
        "computed from a variable or substitution",
        "eval",
        "fully quoted",
    ):
        assert form in rules, form
    assert "violations disqualify" not in rules and "DISQUALIFYING" not in rules
    sr = cc.system_rules(Budget(), sighted=True)
    assert "tampering: the run is DISQUALIFIED" in sr
    assert "even when the tool refuses it" in sr and "source edits are discarded" in sr
    assert "violations disqualify" not in sr and "DISQUALIFYING" not in sr


def test_system_rules_name_exactly_the_git_set_the_deny_rules_refuse() -> None:
    refused = [
        r[len("Bash(git ") : -len(":*)")]
        for r in cc.DENY_RULES
        if r.startswith("Bash(git ") and r.endswith(":*)")
    ]
    m = re.search(r"This tool refuses these git commands: ([^.]+)\.", cc.system_rules(Budget(), sighted=False))
    assert m is not None
    assert m.group(1).split(", ") == refused
    assert {"checkout", "restore", "reset", "stash"} <= set(refused)


@pytest.mark.parametrize(
    ("command", "cause"),
    [
        ('echo "unterminated', "unterminated quote"),
        ("echo 'unterminated", "unterminated quote"),
        ('grep -n "a(b" f.py "rest', "unterminated quote"),
        ("echo hi \\", "trailing backslash"),
        ("echo `pwd", "unmatched backtick"),
        ("echo $(pwd", "unbalanced substitution"),
        ("echo hi (", "unbalanced substitution"),
        ('sh -c "echo \'x"', "unterminated quote"),
        ('timeout 5 sh -c "echo \'x"', "unterminated quote"),
        ("cat <<", "here-document tag"),
        ("cat <<'EOF", "here-document tag"),
        ("cat <<EOF\n$(pwd\nEOF", "unbalanced substitution"),
        ('env -S "echo \'x"', "wrapper command string"),
    ],
)
def test_every_could_not_parse_refusal_names_its_real_cause(command: str, cause: str) -> None:
    for guard in (GitArchaeologyGuard(), GitArchaeologyGuard(cwd=Path.cwd())):
        reason = guard.check_shell(command)
        assert reason == f"archaeology: could not parse the command safely ({cause})", (
            command,
            reason,
        )


def test_substitutions_nested_too_deep_are_refused_as_the_rules_say() -> None:
    """The rules name "substitutions nested too deep"; the guard's refusal says the same."""
    command = "echo " + "$(echo " * 6 + "hi" + ")" * 6
    reason = GitArchaeologyGuard().check_shell(command)
    assert reason == "archaeology: command substitution nested too deep to check"
    assert "nested too deep" in DEFAULT_RULES


# --- the rules agree with every arm's brief (a blind context-set run included) -------------

_CTX_FACT = "Helpers live in calc.py."


def _blind_context_set_brief() -> BuildBrief:
    """A blind ``ctx.oracle`` brief carrying one entry, as a context-set run composes it
    (ADR-0050: every context-set run is blind, so it hands no failing test and no target
    test command)."""
    composed = compose(
        "A0+library@ctx.oracle.0123456789ab",
        Ticket("feat: add subtract", "feat: add subtract"),
        repo="pyrepo",
        language="python",
        mode="blind",
        harness_command="python -m pytest -q",
        library=(ContextEntry("e-1", _CTX_FACT, "1", ""),),
    )
    assert composed.brief.spec_facts == (_CTX_FACT,)
    return composed.brief


def _appended_rules(brief: BuildBrief, tmp_path: Path) -> str:
    argv = cc.ClaudeCodeBuilder().argv(brief, Budget(), tmp_path / "wt")
    return argv[argv.index("--append-system-prompt") + 1]


def test_no_rule_forbids_the_facts_a_context_set_brief_hands_over(tmp_path: Path) -> None:
    """A rule that says "solve from the code and the failing tests only" forbids the very
    context a context-set arm measures, and a blind brief has no failing tests at all."""
    brief = _blind_context_set_brief()
    task = brief.task_text(worktree="/wt")
    assert "Known facts:" in task and _CTX_FACT in task
    for where, text in {
        "DEFAULT_RULES": DEFAULT_RULES,
        "system_rules": _appended_rules(brief, tmp_path),
    }.items():
        solve = next(s for s in text.split("\n") if "Solve " in s)
        assert "facts it lists" in solve, (where, solve)
        assert "the failing tests only" not in solve, (where, solve)


def test_a_blind_brief_is_never_told_to_finish_on_a_target_test_command(
    tmp_path: Path,
) -> None:
    brief = _blind_context_set_brief()
    assert brief.test_command == "" and not brief.sighted
    blind = _appended_rules(brief, tmp_path)
    assert "target test" not in blind, blind
    assert "done=true" in blind
    # the sighted rules still name it: a sighted brief is handed that command
    assert "the target test command exits 0" in cc.system_rules(Budget(), sighted=True)
