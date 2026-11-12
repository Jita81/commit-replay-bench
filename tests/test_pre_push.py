"""The local pre-push set cannot drift from CI: every pull-request ``run:`` line is accounted.

PR #136 met two CI failures its author had not run (docs/PREVENTION.md P-818). The cure is
one command, ``scripts/pre_push.py``, that runs CI's static gates and the suite; this file
keeps it whole. It reads every ``run:`` line of every workflow a pull request triggers and
fails on one that ``pre_push`` neither mirrors with a gate, nor lists as not run here with a
reason, nor knows as plumbing — so a gate added to CI turns this suite red until the local
command runs it or says it cannot.

Navigation
----------
What it is:   The drift ratchet between the pull-request workflows and scripts/pre_push.py,
              plus the title check's reuse of the commit-subject rule.
What it does: Fails when a workflow command is unaccounted for (one chained after ``cd`` or
              an install included), when a job listed as not run holds a command shaped like
              a static gate that nothing names, when an entry in pre_push names a job or a
              command CI no longer has, when the pull-request workflows are not the ones
              pre_push reads, when ``--title`` disagrees with scripts/check_commit_subject.py
              on the squash subject, and when a missing base, a gate not run or a dirty tree
              is not reported as pre_push promises (exit 2, exit 3, a warning).
How:          yaml-loads each workflow, splits each ``run:`` into lines (a folded block is one
              line, a backslash continues one), collapses whitespace, splits each line into
              commands with ``pre_push.commands``, prefixes the job id and matches pre_push's
              ``Gate.mirrors`` / ``UNCOVERED_STEPS`` / ``SETUP`` in full.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/pre_push.py (the set it holds to CI), .github/workflows/ci.yml (the jobs
              it reads), .github/workflows/commit-subjects.yml (the title job it reads),
              scripts/check_commit_subject.py (the rule the title check must reuse),
              tests/test_version_consistency.py (the same run-line reading for CONTRIBUTING)
Tested by:    tests/test_pre_push.py
Touch when:   never for a new repository; a workflow step is added (give scripts/pre_push.py a
              gate for it or an UNCOVERED_STEPS entry, not an exception here).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pre_push", ROOT / "scripts" / "pre_push.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_push"] = mod
    spec.loader.exec_module(mod)
    return mod


pre_push = _load()
#: The module pre_push imports the rule from: scripts/check_commit_subject.py itself.
check_commit_subject = pre_push.ccs
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def run_lines(workflow: dict[str, Any]) -> list[tuple[str, str]]:
    """Every ``(job id, command line)`` the workflow's ``run:`` steps hold, whitespace
    collapsed, comments and blank lines dropped, backslash continuations joined."""
    out: list[tuple[str, str]] = []
    for job, body in workflow["jobs"].items():
        for step in body.get("steps", []):
            if "run" not in step:
                continue
            pending = ""
            for raw in str(step["run"]).splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.endswith("\\"):
                    pending += line[:-1] + " "
                    continue
                out.append((job, " ".join((pending + line).split())))
                pending = ""
    return out


def _load(rel: str) -> dict[str, Any]:
    data = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def all_lines() -> list[tuple[str, str]]:
    return [pair for rel in pre_push.WORKFLOWS for pair in run_lines(_load(rel))]


def _mirrored(job: str, line: str) -> bool:
    return any(pre_push.matches(g.mirrors, f"{job}: {line}") for g in pre_push.GATES)


def _listed(job: str, line: str) -> bool:
    return any(j in ("*", job) and re.fullmatch(p, line) for j, p, _ in pre_push.UNCOVERED_STEPS)


def _unaccounted_command(job: str, cmd: str) -> bool:
    if _mirrored(job, cmd) or _listed(job, cmd):
        return False
    if job in pre_push.UNCOVERED_JOBS:
        return re.fullmatch(pre_push.STATIC_SHAPE, cmd) is not None
    return not pre_push.matches(pre_push.SETUP, cmd)


def unaccounted(lines: list[tuple[str, str]]) -> list[str]:
    """Each line holding a command no gate mirrors, no entry lists and no plumbing pattern
    explains. In a job pre_push lists as not run, only a command shaped like a static gate
    must be named. Each command is read on its own, so plumbing cannot cover a gate chained
    after it."""
    return [
        f"{job}: {line}"
        for job, line in lines
        if any(_unaccounted_command(job, cmd) for cmd in pre_push.commands(line))
    ]


def all_commands() -> list[tuple[str, str]]:
    return [(job, cmd) for job, line in all_lines() for cmd in pre_push.commands(line)]


def test_every_pull_request_run_line_is_a_local_gate_or_listed_as_not_run() -> None:
    missing = unaccounted(all_lines())
    assert not missing, (
        "a CI step scripts/pre_push.py neither runs nor lists as not run here — add a Gate "
        "that mirrors it, or an UNCOVERED_STEPS entry with the reason:\n  " + "\n  ".join(missing)
    )


def test_a_new_static_gate_in_any_job_is_caught() -> None:
    """The check refuses a planted gate in a mirrored job and in a job listed as not run, and
    refuses a mirrored line whose words changed."""
    planted = [
        ("lint", "python scripts/new_gate.py --check"),
        ("security", "python3 scripts/new_gate.py --check"),
        ("types", ".venv/bin/mypy --some-new-flag"),
        # a gate chained after a plumbing word is still a gate
        ("lint", "cd ui && npx eslint ."),
        ("types", "uv pip install foo && .venv/bin/mypy --strict tests"),
        ("lint", "mkdir -p x && python scripts/new_gate.py --check"),
        ("security", "uv venv -q .x; python3 scripts/new_gate.py --check"),
        # shell and npm gates in a job listed as not run
        ("security", "bash scripts/x.sh"),
        ("security", "npm run lint"),
    ]
    assert unaccounted(planted) == [f"{j}: {line}" for j, line in planted]
    assert unaccounted([("lint", ".venv/bin/ruff check src tests")]) == []
    assert unaccounted([("lint", "cd ui && mkdir -p x")]) == []


def test_commands_split_outside_quotes_only() -> None:
    line = """if grep -q 'a | b' x.xml; then echo "::error::no; really" && exit 1; fi"""
    assert pre_push.commands(line) == [
        "grep -q 'a | b' x.xml",
        'echo "::error::no; really"',
        "exit 1",
        "fi",
    ]
    assert pre_push.commands("(cd ui && npm run typecheck || true)") == [
        "cd ui",
        "npm run typecheck",
        "true",
    ]


def test_every_entry_names_a_job_and_a_line_ci_still_has() -> None:
    """A stale entry would let a removed or renamed gate look covered."""
    lines = all_commands()
    jobs = {job for job, _ in lines}
    assert set(pre_push.UNCOVERED_JOBS) <= jobs, set(pre_push.UNCOVERED_JOBS) - jobs
    for gate in pre_push.GATES:
        for pattern in gate.mirrors:
            assert any(re.fullmatch(pattern, f"{j}: {line}") for j, line in lines), (
                f"{gate.name}: no CI line matches {pattern!r}"
            )
    for job, pattern, _ in pre_push.UNCOVERED_STEPS:
        assert any(job in ("*", j) and re.fullmatch(pattern, line) for j, line in lines), (
            f"UNCOVERED_STEPS ({job}, {pattern!r}) matches no CI line"
        )


def test_pre_push_reads_exactly_the_pull_request_workflows() -> None:
    triggered = set()
    for path in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        on = _load(path.relative_to(ROOT).as_posix()).get(True) or {}  # yaml reads `on` as True
        if "pull_request" in on:
            triggered.add(path.relative_to(ROOT).as_posix())
    assert triggered == set(pre_push.WORKFLOWS)


def test_every_ratchet_test_exists() -> None:
    for rel in pre_push.RATCHET_TESTS:
        assert (ROOT / rel).is_file(), rel


def test_the_title_check_is_the_commit_subject_rule_on_the_squash_subject() -> None:
    """``--title`` imports the rule; the same title gets the same verdict, suffix included."""
    rule = ROOT / "scripts" / "check_commit_subject.py"
    assert Path(check_commit_subject.__file__).resolve() == rule
    good = "fix(api): refuse an empty name"
    assert pre_push.check_title(good, 136) == (True, "")
    long_title = "docs(crb): " + "x" * 58  # 69 characters alone, 75 with " (#136)"
    ok, detail = pre_push.check_title(long_title, 136)
    expected = check_commit_subject.check_subject(f"{long_title} (#136)")
    assert not ok and expected and expected[0] in detail
    ok, detail = pre_push.check_title("Fixed the thing", None)
    assert not ok and "Conventional Commits" in detail


def test_list_names_every_gate_and_every_job_it_does_not_run() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pre_push.py"), "--list"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for gate in pre_push.GATES:
        assert f"gate     {gate.name}" in out
    for job in pre_push.UNCOVERED_JOBS:
        assert f"not run  job {job}:" in out


def test_a_changed_file_maps_to_the_tests_its_header_names() -> None:
    tests, notes = pre_push.tests_for(["scripts/check_commit_subject.py", "tests/conftest.py"])
    assert "tests/test_check_commit_subject.py" in tests
    assert notes == [notes[0]] and "tests/conftest.py" in notes[0]
    assert pre_push.tests_for(["tests/test_pre_push.py"]) == (["tests/test_pre_push.py"], [])


def test_a_changed_file_that_maps_to_no_test_gets_a_note() -> None:
    tests, notes = pre_push.tests_for(["docs/CONTRIBUTING.md"])
    assert tests == []
    assert len(notes) == 1 and notes[0].startswith("docs/CONTRIBUTING.md maps to no test")


def _gates(*required: str | None) -> tuple[Any, ...]:
    """Gates that pass at once, each needing ``required`` (``None``: nothing) to run."""
    return tuple(
        pre_push.Gate(f"gate {i}", ("python", "-c", "pass"), (), requires=req)
        for i, req in enumerate(required)
    )


def test_a_missing_base_exits_2_with_one_line_naming_the_fetch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert pre_push.main(["--base", "no-such-ref/for-pre-push"]) == 2
    captured = capsys.readouterr()
    err = captured.err.strip().splitlines()
    assert len(err) == 1 and "git fetch origin main" in err[0]
    assert captured.out == ""


def test_a_gate_not_run_exits_3_unless_skips_are_allowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pre_push, "GATES", _gates(None, "no/such/dir"))
    monkeypatch.setattr(pre_push, "dirty_paths", lambda: [])
    assert pre_push.main(["--base", "HEAD"]) == 3
    out = capsys.readouterr().out.strip().splitlines()
    assert "1 passed, 0 failed, 1 not run" in out
    assert "1 gate(s) not run" in out[-1]
    assert pre_push.main(["--base", "HEAD", "--allow-skip"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "1 passed, 0 failed, 1 not run"
    monkeypatch.setattr(pre_push, "GATES", _gates(None))
    assert pre_push.main(["--base", "HEAD"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "1 passed, 0 failed, 0 not run"


def test_a_dirty_tree_is_named_in_a_warning_that_does_not_change_the_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pre_push, "GATES", _gates(None))
    monkeypatch.setattr(pre_push, "dirty_paths", lambda: ["src/crb/x.py", "notes.txt"])
    assert pre_push.main(["--base", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "CI sees only commits" in out
    assert "  src/crb/x.py\n" in out and "  notes.txt\n" in out


def test_dirty_paths_reads_uncommitted_and_untracked_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert pre_push.dirty_paths(tmp_path) == []
    (tmp_path / "new.txt").write_text("x", encoding="utf-8")
    assert pre_push.dirty_paths(tmp_path) == ["new.txt"]


def test_not_run_names_the_python_versions_and_the_shard_processes() -> None:
    lines = pre_push.not_run_here()
    here = f"Python {sys.version_info.major}.{sys.version_info.minor}"
    assert any("3.12 and 3.13" in line and here in line for line in lines)
    assert any("in its own process" in line for line in lines)


def test_the_coverage_floor_is_read_from_ci() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f"coverage report --fail-under={pre_push._floor()}" in text
