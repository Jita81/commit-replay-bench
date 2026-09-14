"""Belt 5 — ``repo_lint_clean`` (ADR-0011): :mod:`crb.core.lint` and its wiring.

Three layers, each proving one thing:

* **the rule** (pure): exit codes → verdicts, the plan from ``RepoConfig.lint``, the
  per-language detection on synthetic repositories (cobra / click / koa shapes);
* **the grader** (real ``LocalExecutor``, fake linters — small scripts that exit as the
  real tools do): a rejecting linter ⇒ ``repo_lint_clean=False``, not clean,
  ``failure_kind="lint"``; a timeout ⇒ ``False``; a linter that cannot run ⇒ harness
  error; no linter ⇒ ``None`` and ``clean`` unchanged; deleted files are never linted;
* **the toolchains** (gated on PATH): the maintainers' own patch with its formatting
  broken grades ``repo_lint_clean=False`` under the real ``gofmt``, ``ruff`` and
  ``cargo fmt``; the untouched gold grades ``True``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from crb.core import grade as g
from crb.core import ledger as lg
from crb.core import lint as lint_mod
from crb.core.execution import Command, ExecResult, LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import qualify
from crb.core.runners import get_runner
from crb.core.runners.base import BaseRunner
from crb.core.spec import Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs  # type: ignore[no-redef]

gorepo = langs.fixture_module("gorepo")
pyrepo_min = langs.fixture_module("pyrepo_min")
noderepo = langs.fixture_module("noderepo")
rustrepo = langs.fixture_module("rustrepo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class FakeExecutor:
    """Returns scripted :class:`ExecResult`s; records every command it was given."""

    name = "local"

    def __init__(self, *results: ExecResult, raise_oserror: bool = False) -> None:
        self._results = list(results)
        self.commands: list[Command] = []
        self._raise = raise_oserror

    def run(self, cmd: Command) -> ExecResult:
        self.commands.append(cmd)
        if self._raise:
            raise FileNotFoundError(2, "No such file or directory", cmd.argv[0])
        return self._results.pop(0)

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or name

    def describe(self) -> dict[str, Any]:
        return {"executor": "fake"}


def _res(rc: int, out: str = "", err: str = "", *, timed_out: bool = False) -> ExecResult:
    return ExecResult(rc, out, err, timed_out, 0.01)


def _script(path: Path, body: str) -> Path:
    """An executable POSIX shell script (a fake linter)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _mine(repo: GitRepo, config: RepoConfig, feat_sha: str, scratch: Path) -> TaskSpec:
    runner = get_runner(config)
    cand = langs.feat_candidate(repo, config, feat_sha)
    outcome = qualify(
        repo, config, cand, runner=runner, executor=LocalExecutor(), scratch=scratch / "mine"
    )
    assert outcome.task is not None, outcome.skipped_reason
    return outcome.task


def _trial(repo: GitRepo, config: RepoConfig, task: TaskSpec, dest: Path) -> Workspace:
    cand = langs.feat_candidate(repo, config, task.task_id)
    return langs.trial_worktree(repo, cand, dest, config)


def _grade(ws: Workspace, task: TaskSpec, config: RepoConfig, **kw: Any) -> g.GradeResult:
    return g.grade(
        ws, task, config=config, runner=get_runner(config), executor=LocalExecutor(), **kw
    )


# ---------------------------------------------------------------------------
# 1. the rule: exit codes → verdicts, fail closed
# ---------------------------------------------------------------------------

_RUFF = lint_mod.LintTool("ruff", ("ruff", "check"), exts=(".py",))
_GOFMT = lint_mod.LintTool(
    "gofmt", ("gofmt", "-l"), exts=(".go",), findings_rcs=frozenset({2}), stdout_is_findings=True
)
_CARGO_FMT = lint_mod.LintTool(
    "cargo-fmt",
    ("cargo", "fmt", "--check"),
    lint_mod.PATHS_ALL,
    unrunnable_re=lint_mod._RUSTUP_MISSING_RE,
)


@pytest.mark.parametrize(
    ("tool", "result", "verdict", "error"),
    [
        (_RUFF, _res(0), True, ""),
        (_RUFF, _res(1, "E501 line too long"), False, ""),
        (_RUFF, _res(2, err="ruff panicked"), None, "ruff: tool failed (rc=2)"),
        (_RUFF, _res(127, err="not found"), None, "ruff: not runnable (rc=127)"),
        (_RUFF, _res(126), None, "ruff: not runnable (rc=126)"),
        (_RUFF, _res(124, timed_out=True), False, ""),
        (_GOFMT, _res(0), True, ""),
        (_GOFMT, _res(0, "calc/sub.go\n"), False, ""),  # gofmt -l lists, exits 0
        (_GOFMT, _res(2, err="expected ';'"), False, ""),  # parse error = rejected
        (_GOFMT, _res(1), None, "gofmt: tool failed (rc=1)"),
        # a rustup proxy exits 1 (the findings code) when the component is missing
        (
            _CARGO_FMT,
            _res(1, err="error: 'cargo-fmt' is not installed for the toolchain 'stable'."),
            None,
            "cargo-fmt: not runnable (rc=1: error: 'cargo-fmt' is not installed for the "
            "toolchain 'stable'.)",
        ),
        (_CARGO_FMT, _res(1, "Diff in src/lib.rs:1:"), False, ""),
        (_CARGO_FMT, _res(0), True, ""),
    ],
)
def test_read_exit_is_the_one_place_an_exit_code_is_interpreted(
    tool: lint_mod.LintTool, result: ExecResult, verdict: bool | None, error: str
) -> None:
    assert lint_mod._read_exit(tool, result) == (verdict, error)


def test_run_plan_verdicts_and_records(tmp_path: Path) -> None:
    plan = lint_mod.LintPlan((_RUFF,), "ruff")
    ok = lint_mod.run_plan(plan, FakeExecutor(_res(0)), tmp_path, ["a.py", "b.py", "c.md"])
    assert ok.ok is True and ok.error == "" and ok.detected.startswith("ruff")
    assert ok.steps[0].files == ("a.py", "b.py") and ok.steps[0].verdict is True
    assert ok.steps[0].argv == ("ruff", "check", "a.py", "b.py")

    rejected = lint_mod.run_plan(plan, FakeExecutor(_res(1, "E501")), tmp_path, ["a.py"])
    assert rejected.ok is False and rejected.error == "" and "rejected" in rejected.note
    assert rejected.steps[0].tail == "E501" and rejected.steps[0].rc == 1

    timed = lint_mod.run_plan(plan, FakeExecutor(_res(124, timed_out=True)), tmp_path, ["a.py"])
    assert timed.ok is False and timed.error == "" and "timed out" in timed.note
    assert timed.steps[0].timed_out and timed.steps[0].verdict is False

    crashed = lint_mod.run_plan(plan, FakeExecutor(_res(2, err="boom")), tmp_path, ["a.py"])
    assert crashed.ok is False and crashed.error == "ruff: tool failed (rc=2)"
    assert crashed.steps[0].verdict is None and crashed.note == crashed.error

    missing = lint_mod.run_plan(plan, FakeExecutor(raise_oserror=True), tmp_path, ["a.py"])
    assert missing.ok is False and "not runnable" in missing.error
    assert missing.steps[0].rc == 127 and "FileNotFoundError" in missing.steps[0].tail

    nothing = lint_mod.run_plan(plan, FakeExecutor(), tmp_path, ["README.md"])
    assert nothing.ok is None and nothing.steps == () and "not evaluated" in nothing.note

    d = rejected.to_dict()
    assert lint_mod.LintRun.from_dict(d).to_dict() == d  # durations rounded to 3 dp on the way out
    assert d["steps"][0]["verdict"] is False and d["ok"] is False


def test_run_plan_stops_at_the_first_rejection_and_passes_paths_all_no_files(
    tmp_path: Path,
) -> None:
    clippy = lint_mod.LintTool(
        "clippy", ("cargo", "clippy"), lint_mod.PATHS_ALL, findings_rcs=frozenset({101})
    )
    plan = lint_mod.LintPlan((_RUFF, clippy), "ruff+clippy")
    ex = FakeExecutor(_res(1, "E501"), _res(0))
    run = lint_mod.run_plan(plan, ex, tmp_path, ["a.py"])
    assert run.ok is False and len(run.steps) == 1 and len(ex.commands) == 1
    ex = FakeExecutor(_res(0), _res(101, err="warning: unused"))
    run = lint_mod.run_plan(plan, ex, tmp_path, ["a.py"])
    assert run.ok is False and [s.tool for s in run.steps] == ["ruff", "clippy"]
    assert ex.commands[1].argv == ("cargo", "clippy")  # paths=all: nothing appended
    ex = FakeExecutor(_res(0))
    run = lint_mod.run_plan(plan, ex, tmp_path, ["README.md"])  # ruff skipped, clippy still runs
    assert run.ok is True and [s.tool for s in run.steps] == ["clippy"]


def test_lint_run_invariants_and_redaction() -> None:
    with pytest.raises(ValueError, match="cannot be ok"):
        lint_mod.LintRun("ruff", (lint_mod.LintStep("ruff", ("ruff",), (), 1, False),), True)
    with pytest.raises(ValueError, match="fails closed"):
        lint_mod.LintRun("ruff", (), None, error="ruff: not runnable")
    step = lint_mod.LintStep("ruff", ("ruff",), (), 1, False, tail="token=ghp_" + "a" * 40)
    assert "ghp_" + "a" * 40 not in step.tail
    with pytest.raises(ValueError):
        lint_mod.LintTool("", ("x",))
    with pytest.raises(ValueError):
        lint_mod.LintTool("x", ())
    with pytest.raises(ValueError, match="paths"):
        lint_mod.LintTool("x", ("x",), paths="some")
    with pytest.raises(ValueError, match="at least one tool"):
        lint_mod.LintPlan((), "x")


# ---------------------------------------------------------------------------
# 2. RepoConfig.lint — the declared plan
# ---------------------------------------------------------------------------


def test_plan_from_config_shapes() -> None:
    assert lint_mod.plan_from_config(None) is None
    assert lint_mod.plan_from_config({}) is None
    assert lint_mod.plan_from_config({"command": []}) is None
    assert lint_mod.plan_from_config({"disabled": True}) is None and lint_mod.lint_disabled(
        {"disabled": True}
    )
    assert not lint_mod.lint_disabled({}) and not lint_mod.lint_disabled(None)
    plan = lint_mod.plan_from_config(
        {"command": ["golangci-lint", "run"], "paths": "all", "timeout": 30, "findings_rc": [1, 3]}
    )
    assert plan is not None and plan.detected == "config" and plan.timeout == 30
    tool = plan.tools[0]
    assert tool.name == "config" and tool.paths == lint_mod.PATHS_ALL
    assert tool.argv == ("golangci-lint", "run") and tool.findings_rcs == frozenset({1, 3})
    with pytest.raises(ValueError, match="argv list"):
        lint_mod.plan_from_config({"command": "ruff check"})
    with pytest.raises(ValueError, match="paths"):
        lint_mod.plan_from_config({"command": ["x"], "paths": "nope"})


def test_repo_config_validates_and_round_trips_lint() -> None:
    cfg = RepoConfig(name="r", language=Language.PYTHON, lint={"command": ["ruff", "check"]})
    assert cfg.lint == {"command": ["ruff", "check"]}
    assert RepoConfig.from_dict("r", cfg.to_dict()).lint == cfg.lint
    assert RepoConfig.from_dict("r", {"language": "py"}).lint == {}
    with pytest.raises(ValueError, match="argv list"):
        RepoConfig(name="r", language=Language.PYTHON, lint={"command": "ruff"})
    runner = get_runner(cfg)
    plan = runner.lint_plan(Path("."), LocalExecutor())
    assert plan is not None and plan.detected == "config"
    off = get_runner(RepoConfig(name="r", language=Language.GO, lint={"disabled": True}))
    assert off.lint_plan(Path("."), LocalExecutor()) is None


# ---------------------------------------------------------------------------
# 3. detection on the shapes of the evidence repositories
# ---------------------------------------------------------------------------


def test_go_detection_is_gofmt_for_any_module(tmp_path: Path) -> None:
    assert lint_mod.go_plan(tmp_path, "gofmt") is None  # not a module
    (tmp_path / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")
    plan = lint_mod.go_plan(tmp_path, "/usr/bin/gofmt")
    assert plan is not None and plan.detected == "gofmt"
    assert plan.tools[0].argv == ("/usr/bin/gofmt", "-l") and plan.tools[0].stdout_is_findings
    assert plan.tools[0].files_for(["a.go", "b.py", "c_test.go"]) == ("a.go", "c_test.go")


def test_python_detection_follows_click(tmp_path: Path) -> None:
    assert lint_mod.python_ruff_evidence(tmp_path) == (False, False)
    assert lint_mod.python_plan(tmp_path, "ruff") is None  # no evidence → not evaluated
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
    assert lint_mod.python_ruff_evidence(tmp_path) == (True, False)
    plan = lint_mod.python_plan(tmp_path, "/venv/bin/ruff")
    assert plan is not None and plan.detected.startswith("ruff") and "+" not in plan.detected
    assert plan.tools[0].argv == ("/venv/bin/ruff", "check", "--no-fix")
    # click: ruff-check + ruff-format pre-commit hooks
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    hooks:\n"
        "      - id: ruff-check\n      - id: ruff-format\n"
    )
    assert lint_mod.python_ruff_evidence(tmp_path) == (True, True)
    plan = lint_mod.python_plan(tmp_path, "ruff")
    assert plan is not None and re.fullmatch(r"ruff(@[\d.]+)?\+ruff-format", plan.detected)
    assert [t.name for t in plan.tools] == ["ruff", "ruff-format"]
    assert plan.tools[1].argv == ("ruff", "format", "--check")
    # a [tool.ruff.format] table alone also evidences the formatter
    (tmp_path / ".pre-commit-config.yaml").unlink()
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n[tool.ruff.format]\nquote-style='d'\n")
    assert lint_mod.python_ruff_evidence(tmp_path) == (True, True)
    # ruff.toml alone is evidence for check
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "ruff.toml").write_text("line-length = 100\n")
    assert lint_mod.python_ruff_evidence(tmp_path) == (True, False)


def test_js_detection_follows_koa_a_binary_without_its_config_is_not_evidence(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    assert lint_mod.js_plan(tmp_path, bin_dir) is None  # no package.json
    # koa: eslint present only as standard's dependency, no eslint config, "lint": "standard"
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"lint": "standard"}}))
    (bin_dir / "eslint").write_text("")
    assert lint_mod.js_plan(tmp_path, bin_dir) is None  # eslint binary alone: not evidence
    (bin_dir / "standard").write_text("")
    plan = lint_mod.js_plan(tmp_path, bin_dir)
    assert plan is not None and plan.detected == "standard"
    assert plan.tools[0].argv == (str(bin_dir / "standard"),)
    # an eslint config + the binary: eslint wins over the script
    (tmp_path / "eslint.config.js").write_text("export default [];\n")
    plan = lint_mod.js_plan(tmp_path, bin_dir)
    assert plan is not None and plan.detected == "eslint"
    # prettier config + binary: both, eslint first
    (tmp_path / ".prettierrc").write_text("{}")
    assert lint_mod.js_plan(tmp_path, bin_dir) is not None
    assert lint_mod.js_plan(tmp_path, bin_dir).detected == "eslint"  # type: ignore[union-attr]
    (bin_dir / "prettier").write_text("")
    plan = lint_mod.js_plan(tmp_path, bin_dir)
    assert plan is not None and plan.detected == "eslint+prettier"
    assert plan.tools[1].argv[1] == "--check"
    assert plan.tools[0].files_for(["a.ts", "b.tsx", "c.css"]) == ("a.ts", "b.tsx")
    # under a sandbox (bin_dir None) the image's PATH resolves the tool: config evidence only
    plan = lint_mod.js_plan(tmp_path, None)
    assert plan is not None and plan.tools[0].argv == ("eslint",)
    # package.json#eslintConfig (legacy) is config evidence too
    (tmp_path / "eslint.config.js").unlink()
    (tmp_path / ".prettierrc").unlink()
    (tmp_path / "package.json").write_text(json.dumps({"eslintConfig": {"root": True}}))
    assert lint_mod.js_plan(tmp_path, bin_dir).detected == "eslint"  # type: ignore[union-attr]


def test_jvm_detection_follows_the_pom(tmp_path: Path) -> None:
    assert lint_mod.jvm_plan(tmp_path, "mvn", (), {}) is None
    (tmp_path / "pom.xml").write_text("<project><build/></project>")
    assert lint_mod.jvm_plan(tmp_path, "mvn", (), {}) is None  # no lint plugin declared
    (tmp_path / "pom.xml").write_text(
        "<project><build><plugins><plugin><artifactId>spotless-maven-plugin</artifactId>"
        "</plugin><plugin><artifactId>maven-checkstyle-plugin</artifactId></plugin>"
        "</plugins></build></project>"
    )
    plan = lint_mod.jvm_plan(tmp_path, "./mvnw", ("-Pfast",), {"JAVA_HOME": "/j"})
    assert plan is not None and plan.detected == "spotless+checkstyle"
    assert plan.tools[0].argv == ("./mvnw", "-o", "-q", "-B", "-Pfast", "spotless:check")
    assert plan.tools[1].argv[-1] == "checkstyle:check"
    assert all(t.paths == lint_mod.PATHS_ALL for t in plan.tools)
    assert plan.tools[0].env == {"JAVA_HOME": "/j"} and "target" in plan.tools[0].writable_paths


def test_rust_detection_follows_clap(tmp_path: Path) -> None:
    assert lint_mod.rust_plan(tmp_path, "cargo", {}) is None
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "c"\nversion = "0.1.0"\n')
    assert lint_mod.rust_plan(tmp_path, "cargo", {}) is None  # nothing configured
    (tmp_path / ".clippy.toml").write_text("")
    plan = lint_mod.rust_plan(tmp_path, "cargo", {})
    assert plan is not None and plan.detected == "clippy"
    assert plan.tools[0].argv == ("cargo", "clippy", "--offline", "--", "-D", "warnings")
    assert plan.tools[0].findings_rcs == frozenset({101})
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("jobs:\n  rustfmt:\n    steps:\n      - run: cargo fmt --check\n")
    plan = lint_mod.rust_plan(tmp_path, "cargo", {})
    assert plan is not None and plan.detected == "cargo-fmt+clippy"
    assert plan.tools[0].argv == ("cargo", "fmt", "--check")


def test_runner_hooks_detect_per_language(tmp_path: Path) -> None:
    """Each runner's ``detect_lint`` reaches the module-level detector with its own
    tool resolution; the base runner detects nothing."""
    ex = LocalExecutor()
    (tmp_path / "go.mod").write_text("module m\n")
    go = get_runner(RepoConfig(name="g", language=Language.GO, runner_opts={"gofmt": "/x/gofmt"}))
    plan = go.lint_plan(tmp_path, ex)
    assert plan is not None and plan.tools[0].argv[0] == "/x/gofmt"
    py = get_runner(RepoConfig(name="p", language=Language.PYTHON))
    assert py.lint_plan(tmp_path, ex) is None  # no [tool.ruff]
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    plan = py.lint_plan(tmp_path, ex)
    assert plan is not None and plan.tools[0].argv[0].endswith("ruff")
    assert (
        BaseRunner(RepoConfig(name="b", language=Language.PYTHON)).detect_lint(tmp_path, ex) is None
    )


def test_pytest_runner_prefers_the_configured_interpreters_ruff(tmp_path: Path) -> None:
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("")
    (venv_bin / "ruff").write_text("")
    py = get_runner(
        RepoConfig(
            name="p", language=Language.PYTHON, runner_opts={"python": str(venv_bin / "python")}
        )
    )
    assert py.ruff_for(tmp_path, LocalExecutor()) == str(venv_bin / "ruff")  # type: ignore[attr-defined]
    bare = get_runner(RepoConfig(name="p", language=Language.PYTHON))
    assert bare.ruff_for(tmp_path, LocalExecutor()) == (shutil.which("ruff") or "ruff")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 4. the grader with fake linters (real executor, real worktree, no toolchain)
# ---------------------------------------------------------------------------


@pytest.fixture
def pyfix(tmp_path: Path) -> tuple[GitRepo, str, RepoConfig]:
    root, feat_sha = pyrepo_min.build(tmp_path)
    return GitRepo(root), feat_sha, pyrepo_min.config()


def _fake_lint_config(script: Path, **extra: Any) -> dict[str, Any]:
    return {"command": [str(script)], **extra}


def _config_with(base: RepoConfig, **changes: Any) -> RepoConfig:
    d = base.to_dict()
    d.update(changes)
    return RepoConfig.from_dict(base.name, d)


def test_no_linter_means_belt_five_none_and_clean_unchanged(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    events: list[tuple[str, dict[str, Any]]] = []
    res = _grade(ws, task, config, on_event=lambda a, p: events.append((a, dict(p))))
    assert res.clean and res.belts.repo_lint_clean is None and res.lint_run is None
    assert res.belts.evaluated == g.CORE_BELT_NAMES
    assert all(p.get("belt") != "repo_lint_clean" for _, p in events)
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.clean and row.belt_set == "v5" and row.repo_lint_clean is None
    assert row.failure_kind == "" and row.body()["repo_lint_clean"] is None


def test_rejecting_linter_is_not_clean_and_is_the_lint_kind(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    # The gold is mined under the repo's real (lint-less) config so it is lint-clean and
    # the task ELIGIBLE: a linter that rejected the maintainers' own patch would make
    # the task gold-dirty at mine time (the ADR-0011 follow-up) — a different finding.
    task = _mine(repo, config, feat_sha, tmp_path)
    assert task.gold_clean is True
    script = _script(tmp_path / "bin" / "lint", 'echo "$@: E501 line too long"\nexit 1\n')
    config = _config_with(config, lint=_fake_lint_config(script, exts=[".py"]))
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    events: list[tuple[str, dict[str, Any]]] = []
    res = _grade(ws, task, config, on_event=lambda a, p: events.append((a, dict(p))))
    assert res.clean is False and res.error == ""
    assert res.belts == g.Belts(True, True, True, True, False)
    assert res.lint_run is not None and res.lint_run.ok is False
    assert res.lint_run.detected == "config" and res.lint_run.steps[0].files == (
        pyrepo_min.SRC_SUB,
    )
    assert "E501" in res.lint_run.steps[0].tail and res.note.startswith("lint:")
    belt5 = next(p for a, p in events if a == "grade.belt" and p["belt"] == "repo_lint_clean")
    assert belt5["value"] is False and belt5["detected"] == "config"
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult(task.task_id, task.repo, "sighted", clean=True, belts=res.belts)
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert not row.clean and row.repo_lint_clean is False and row.belt_set == "v5"
    assert row.failure_kind == lg.FAILURE_LINT and row.labels["failure_kind"] == "lint"
    assert row.eligible and lg.failure_split([row]).lint == 1
    with pytest.raises(g.FalseQ1Violation):
        lg.GradeRow(**{**row.fields(), "clean": True, "evidence_pack_hash": "c" * 64})
    d = res.to_dict()
    assert d["repo_lint_clean"] is False and d["lint_run"]["ok"] is False


def test_accepting_linter_is_clean_and_true(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    script = _script(tmp_path / "bin" / "lint", "exit 0\n")
    config = _config_with(config, lint=_fake_lint_config(script))
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.clean and res.belts.repo_lint_clean is True
    assert res.belts.evaluated == g.BELT_NAMES
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.clean and row.repo_lint_clean is True and row.failure_kind == ""


def test_lint_timeout_fails_the_belt_closed(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    script = _script(tmp_path / "bin" / "lint", "sleep 30\nexit 0\n")
    config = _config_with(config, lint=_fake_lint_config(script, timeout=1))
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.clean is False and res.error == ""
    assert res.belts.repo_lint_clean is False
    assert res.lint_run is not None and res.lint_run.steps[0].timed_out
    assert "timed out" in res.note
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_LINT  # the tool ran; the patch did not pass it


def test_linter_that_cannot_run_is_a_harness_error_never_a_pass(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    config = _config_with(config, lint={"command": [str(tmp_path / "bin" / "no-such-linter")]})
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.clean is False and res.error.startswith("lint:") and "not runnable" in res.error
    assert res.belts.repo_lint_clean is False
    assert res.lint_run is not None and res.lint_run.error and res.lint_run.steps[0].rc == 127
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_HARNESS and not row.clean
    # a tool that ran but crashed (its own abnormal exit) is a harness error too
    script = _script(tmp_path / "bin" / "crash", "echo internal error >&2\nexit 2\n")
    config = _config_with(config, lint=_fake_lint_config(script))
    ws2 = _trial(repo, config, task, tmp_path / "t2")
    ws2.overlay_sources(task.src_files)
    res2 = _grade(ws2, task, config)
    assert res2.clean is False and "rc=2" in res2.error and res2.belts.repo_lint_clean is False


def test_lint_runs_only_on_changed_non_test_files_that_still_exist(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    """The builder deleted a source file and added another: only the existing, non-test
    changed files reach the linter (a deleted path would make any linter fail on
    'no such file' — a harness error dressed as a verdict)."""
    repo, feat_sha, config = pyfix
    seen = tmp_path / "seen.txt"
    script = _script(tmp_path / "bin" / "lint", f'echo "$@" >> "{seen}"\nexit 0\n')
    config = _config_with(config, lint=_fake_lint_config(script, exts=[".py"]))
    task = _mine(repo, config, feat_sha, tmp_path)
    # the gold check ran the same plan on the gold (pkg/sub.py) at mine time; this
    # test is about which files the GRADE hands the linter, so start the record afresh
    assert seen.read_text().split() == [pyrepo_min.SRC_SUB] and task.gold_clean is True
    seen.write_text("")
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    (ws.root / "pkg" / "extra.py").write_text("X = 1\n")
    (ws.root / "README.md").write_text("# not lintable by a .py-scoped tool\n")
    (
        ws.root / "pkg" / "calc.py"
    ).unlink()  # a deleted source file (belt 3 still passes: no test imports it)
    res = _grade(ws, task, config)
    assert res.belts.repo_lint_clean is True, res.to_dict()
    linted = seen.read_text().split()
    assert sorted(linted) == ["pkg/extra.py", "pkg/sub.py"]
    assert "pkg/calc.py" not in linted and "README.md" not in linted


def test_lint_is_not_evaluated_when_the_grade_stops_early(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    script = _script(tmp_path / "bin" / "lint", "exit 1\n")
    config = _config_with(config, lint=_fake_lint_config(script))
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")  # no-op builder: target stays RED
    res = _grade(ws, task, config)
    assert res.belts.target_green is False and res.belts.repo_lint_clean is None
    assert res.lint_run is None
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_BUILDER_RED


def test_lint_fails_and_a_core_belt_fails_is_builder_red_not_lint(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    repo, feat_sha, config = pyfix
    script = _script(tmp_path / "bin" / "lint", "exit 1\n")
    config = _config_with(config, lint=_fake_lint_config(script))
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    (ws.root / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b + 1\n")  # regression
    res = _grade(ws, task, config)
    assert res.belts.no_new_failures is False and res.belts.repo_lint_clean is False
    assert not res.clean
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_BUILDER_RED and not row.lint_only()


# ---------------------------------------------------------------------------
# 5. the toolchains: the gold patch with broken formatting is not clean
# ---------------------------------------------------------------------------


@pytest.mark.toolchain("go")
@pytest.mark.skipif(
    not (langs.has_tool("go") and langs.has_tool("gofmt")), reason="go/gofmt not on PATH"
)
def test_go_gofmt_rejects_a_misformatted_gold_patch(tmp_path: Path) -> None:
    """cobra #1559 (critical-friend §3.2 finding 1): working code ``gofmt -l`` would
    reformat. The maintainers' own patch passes; the same patch with its indentation
    broken grades ``repo_lint_clean=False`` — not clean, kind ``lint``."""
    root, feat_sha = gorepo.build(tmp_path)
    repo, config = GitRepo(root), gorepo.config()
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "gold")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.clean and res.belts.repo_lint_clean is True
    assert res.lint_run is not None and res.lint_run.detected == "gofmt"
    assert res.lint_run.steps[0].files == (gorepo.SRC_SUB,)
    ws.remove()

    ws = _trial(repo, config, task, tmp_path / "ugly")
    ws.overlay_sources(task.src_files)
    src = ws.root / gorepo.SRC_SUB
    src.write_text(
        src.read_text().replace(
            "func Sub(a, b int) int { return a - b }", "func Sub(a,b int) int {\n\treturn a-b\n  }"
        )
    )
    res = _grade(ws, task, config)
    assert res.belts.target_green is True and res.belts.no_new_failures is True
    assert res.belts.repo_lint_clean is False and res.clean is False
    assert res.lint_run is not None and gorepo.SRC_SUB in res.lint_run.steps[0].tail
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_LINT and row.belt_set == "v5"
    ws.remove()


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
def test_go_declared_lint_overrides_detection(tmp_path: Path) -> None:
    root, feat_sha = gorepo.build(tmp_path)
    repo = GitRepo(root)
    script = _script(tmp_path / "bin" / "vet-ish", 'echo "vet: $@"\nexit 1\n')
    config = _config_with(gorepo.config(), lint={"command": [str(script)], "paths": "all"})
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.lint_run is not None and res.lint_run.detected == "config"
    assert res.lint_run.steps[0].files == () and res.belts.repo_lint_clean is False
    ws.remove()


def _cargo_fmt_works() -> bool:
    import subprocess

    if not langs.has_tool("cargo"):
        return False
    try:
        p = subprocess.run(
            ["cargo", "fmt", "--version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


def _ruff_binary() -> str | None:
    sibling = Path(sys.executable).parent / "ruff"
    if sibling.exists():
        return str(sibling)
    return shutil.which("ruff")


@pytest.mark.skipif(_ruff_binary() is None, reason="ruff not available")
def test_python_ruff_rejects_a_misformatted_gold_patch(tmp_path: Path) -> None:
    """click's apparatus: ``[tool.ruff]`` + the ``ruff-format`` hook. The gold passes;
    the gold with an unused import and un-formatted code does not."""
    extra = {
        "pyproject.toml": "[tool.ruff]\nline-length = 88\n[tool.ruff.lint]\nselect = ['E', 'F']\n",
        ".pre-commit-config.yaml": "repos:\n  - hooks:\n      - id: ruff-check\n      - id: ruff-format\n",
    }
    root, feat_sha = pyrepo_min.build(tmp_path, extra=extra)
    repo = GitRepo(root)
    config = pyrepo_min.config(runner_opts={"python": sys.executable})
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "gold")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.clean and res.belts.repo_lint_clean is True, res.to_dict()
    assert res.lint_run is not None and re.fullmatch(
        r"ruff(@[\d.]+)?\+ruff-format", res.lint_run.detected
    )
    assert [s.tool for s in res.lint_run.steps] == ["ruff", "ruff-format"]
    ws.remove()

    ws = _trial(repo, config, task, tmp_path / "ugly")
    ws.overlay_sources(task.src_files)
    (ws.root / pyrepo_min.SRC_SUB).write_text(
        "import os\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n"
    )
    res = _grade(ws, task, config)
    assert res.belts.target_green is True and res.belts.repo_lint_clean is False
    assert not res.clean and res.lint_run is not None
    assert res.lint_run.steps[-1].tool == "ruff" and "F401" in res.lint_run.steps[-1].tail
    # the source stays as the builder left it: `ruff check` never fixed it
    assert (ws.root / pyrepo_min.SRC_SUB).read_text().startswith("import os\n")
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
    assert row.failure_kind == lg.FAILURE_LINT
    ws.remove()

    # formatting only (no lint finding): ruff check passes, ruff format --check rejects
    ws = _trial(repo, config, task, tmp_path / "unformatted")
    ws.overlay_sources(task.src_files)
    (ws.root / pyrepo_min.SRC_SUB).write_text("def sub(a: int, b: int) -> int:\n    return a-b\n")
    res = _grade(ws, task, config)
    assert res.belts.repo_lint_clean is False and res.lint_run is not None
    assert [s.tool for s in res.lint_run.steps] == ["ruff", "ruff-format"]
    assert res.lint_run.steps[0].verdict is True and res.lint_run.steps[1].verdict is False
    ws.remove()


@pytest.mark.skipif(_ruff_binary() is None, reason="ruff not available")
def test_builder_cannot_rewrite_the_linters_configuration(tmp_path: Path) -> None:
    """Independent review pass (2026-09-14), finding 2: with the parent's
    ``[tool.ruff.lint] select = ["E", "F"]`` an unused import is ``repo_lint_clean=False``;
    writing ``select = []`` into ``pyproject.toml``, or a nested ``pkg/ruff.toml`` with
    ``[lint] select = []``, graded CLEAN with ``repo_lint_clean=True`` on 842875b. Lint
    configuration is test infrastructure: both now disqualify under belt 1b before any
    test runs, and an honest ``[project]`` edit still grades clean."""
    extra = {
        "pyproject.toml": "[tool.ruff]\nline-length = 88\n[tool.ruff.lint]\nselect = ['E', 'F']\n"
    }
    root, feat_sha = pyrepo_min.build(tmp_path, extra=extra)
    repo = GitRepo(root)
    config = pyrepo_min.config(runner_opts={"python": sys.executable})
    task = _mine(repo, config, feat_sha, tmp_path)
    ugly = "import os\n\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n"

    ws = _trial(repo, config, task, tmp_path / "ugly")
    ws.overlay_sources(task.src_files)
    (ws.root / pyrepo_min.SRC_SUB).write_text(ugly)
    res = _grade(ws, task, config)
    assert res.clean is False and res.belts.repo_lint_clean is False
    ws.remove()

    ws = _trial(repo, config, task, tmp_path / "select-empty")
    ws.overlay_sources(task.src_files)
    (ws.root / pyrepo_min.SRC_SUB).write_text(ugly)
    pp = ws.root / "pyproject.toml"
    pp.write_text(pp.read_text().replace("select = ['E', 'F']", "select = []"))
    res = _grade(ws, task, config)
    assert res.disqualified and res.clean is False and res.belts.repo_lint_clean is None
    assert res.dq_reason == "test infrastructure modified: ['pyproject.toml']"
    assert res.tamper_files == ("pyproject.toml",) and res.target_run is None
    ws.remove()

    ws = _trial(repo, config, task, tmp_path / "nested-ruff-toml")
    ws.overlay_sources(task.src_files)
    (ws.root / pyrepo_min.SRC_SUB).write_text(ugly)
    (ws.root / "pkg" / "ruff.toml").write_text("[lint]\nselect = []\n")
    res = _grade(ws, task, config)
    assert res.disqualified and res.clean is False
    assert res.dq_reason == "test infrastructure modified: ['pkg/ruff.toml']"
    ws.remove()

    ws = _trial(repo, config, task, tmp_path / "honest")
    ws.overlay_sources(task.src_files)
    pp = ws.root / "pyproject.toml"
    pp.write_text(pp.read_text() + '\n[project]\nname = "pkg"\nversion = "0.2.0"\n')
    res = _grade(ws, task, config)
    assert res.clean is True and res.belts.repo_lint_clean is True
    assert "pyproject.toml" in res.changed_files
    ws.remove()


@pytest.mark.toolchain("cargo")
@pytest.mark.skipif(not langs.has_tool("cargo"), reason="cargo not on PATH")
def test_rust_missing_rustfmt_component_is_a_harness_error_not_a_verdict(tmp_path: Path) -> None:
    """The rustup proxy answers ``cargo fmt`` with rc 1 when rustfmt is not installed —
    the findings code. Belt 5 must read that as *not runnable* (harness), never as
    "the patch is unformatted". Runs whichever way the host is set up: with rustfmt
    installed the gold passes; without it the grade errors closed."""
    root, feat_sha = rustrepo.build(tmp_path, extra={"rustfmt.toml": 'edition = "2021"\n'})
    repo, config = GitRepo(root), rustrepo.config()
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "gold")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.lint_run is not None and res.lint_run.detected == "cargo-fmt"
    if _cargo_fmt_works():
        assert res.clean and res.belts.repo_lint_clean is True, res.to_dict()
    else:
        assert not res.clean and res.belts.repo_lint_clean is False
        assert "not runnable" in res.error and "not installed" in res.error
        row = lg.grade_row_from_result(res, task, pack_hash="c" * 64)
        assert row.failure_kind == lg.FAILURE_HARNESS  # the instrument, not the model
    ws.remove()


@pytest.mark.toolchain("cargo")
@pytest.mark.skipif(not _cargo_fmt_works(), reason="cargo fmt (rustfmt component) not available")
def test_rust_cargo_fmt_rejects_a_misformatted_gold_patch(tmp_path: Path) -> None:
    root, feat_sha = rustrepo.build(tmp_path, extra={"rustfmt.toml": 'edition = "2021"\n'})
    repo, config = GitRepo(root), rustrepo.config()
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "gold")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.clean and res.belts.repo_lint_clean is True, res.to_dict()
    assert res.lint_run is not None and res.lint_run.detected == "cargo-fmt"
    ws.remove()

    ws = _trial(repo, config, task, tmp_path / "ugly")
    ws.overlay_sources(task.src_files)
    (ws.root / rustrepo.SRC_SUB).write_text(
        "/// Returns a - b.\npub fn sub(a: i64,b: i64) -> i64 { a - b }\n"
    )
    res = _grade(ws, task, config)
    assert res.belts.target_green is True and res.belts.repo_lint_clean is False
    assert not res.clean
    assert lg.grade_row_from_result(res, task, pack_hash="c" * 64).failure_kind == "lint"
    ws.remove()


@pytest.mark.toolchain("node")
@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
def test_node_standard_script_is_detected_and_graded(tmp_path: Path) -> None:
    """koa's shape: ``"lint": "standard"`` and the binary under ``node_modules/.bin`` — here
    a fake ``standard`` that rejects anything containing a double-quoted string."""
    root, feat_sha = noderepo.build(
        tmp_path,
        "node",
        extra={
            "package.json": json.dumps(
                {
                    "name": "fx",
                    "version": "1.0.0",
                    "scripts": {"test": "node --test", "lint": "standard"},
                }
            )
        },
    )
    bin_dir = root / "node_modules" / ".bin"
    _script(
        bin_dir / "standard",
        'for f in "$@"; do grep -q \'"\' "$f" && { echo "$f: strings must use singlequote"; exit 1; }; done\nexit 0\n',
    )
    repo, config = GitRepo(root), noderepo.config("node")
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.lint_run is not None and res.lint_run.detected == "standard"
    assert res.lint_run.steps[0].files == (noderepo.SRC_SUB,)
    # the CommonJS fixture source carries "use strict" → the fake standard rejects it
    assert res.belts.repo_lint_clean is False and not res.clean
    ws.remove()


def test_lint_run_is_in_the_evidence_pack_and_survives_the_round_trip(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    from crb.core import evidence as ev

    repo, feat_sha, config = pyfix
    script = _script(tmp_path / "bin" / "lint", "echo secret=ghp_" + "b" * 40 + "\nexit 1\n")
    config = _config_with(config, lint=_fake_lint_config(script))
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    pack = ev.EvidencePack(
        task=task,
        grade=res,
        apparatus=ev.ApparatusStamp(runner="pytest", executor={"executor": "local"}),
        builder=None,
        run_id="r",
        trial="t1",
        actor="ci",
    )
    d = pack.to_dict()
    assert d["grade"]["lint_run"]["ok"] is False and d["grade"]["repo_lint_clean"] is False
    assert "ghp_" + "b" * 40 not in json.dumps(d)  # redacted at construction
    assert d["apparatus"]["apparatus_version"] == "2.2"
    assert os.environ.get("CRB_HOME") is None  # never the live stack


def test_evaluate_lint_false_leaves_belt_five_unevaluated_for_the_controls(
    pyfix: tuple[GitRepo, str, RepoConfig], tmp_path: Path
) -> None:
    """The negative controls measure the four ORACLE belts: with ``evaluate_lint=False``
    a configured, rejecting linter is not run at all and the result records belt 5 as
    not evaluated — an oracle escape can never hide behind a lint rejection."""
    repo, feat_sha, config = pyfix
    script = _script(tmp_path / "bin" / "lint", "exit 1\n")
    config = _config_with(config, lint=_fake_lint_config(script))
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config, evaluate_lint=False)
    assert res.clean and res.belts.repo_lint_clean is None and res.lint_run is None
    assert res.belts.evaluated == g.CORE_BELT_NAMES
    # the default evaluates it: the same worktree is then not clean
    ws2 = _trial(repo, config, task, tmp_path / "t2")
    ws2.overlay_sources(task.src_files)
    assert _grade(ws2, task, config).belts.repo_lint_clean is False


# ---------------------------------------------------------------------------
# 6. tsc — belt 5 runs the type checker where the repository's CI does (ADR-0011
#    amendment, 2026-09-14: 4 of 10 clean NHS rows failed their own `lint:types`)
# ---------------------------------------------------------------------------

_TSC_BIN = "node_modules/.bin/tsc"


def _tsc_tool(**kw: Any) -> lint_mod.LintTool:
    return lint_mod.LintTool(
        "tsc",
        ("tsc", "--build", "tsconfig.json", "--pretty", "false"),
        lint_mod.PATHS_ALL,
        exts=(".ts", ".tsx", ".mjs", ".js"),
        findings_rcs=frozenset({1, 2}),
        findings_re=lint_mod.TSC_FINDINGS_RE,
        **kw,
    )


def test_tsc_evidence_follows_the_nhs_repositories(tmp_path: Path) -> None:
    """nhsuk-frontend and nhsuk-react-components: ``"lint:types": "tsc --build
    tsconfig.json --pretty"`` (CI: ``npm run lint:types`` / ``yarn lint``) — honoured
    verbatim; without ``tsconfig.json`` nothing is evidenced; other scripts and a CI
    line are the weaker forms."""
    pkg: dict[str, Any] = {"scripts": {"lint:types": "tsc --build tsconfig.json --pretty"}}
    assert lint_mod.tsc_evidence(tmp_path, pkg) is None  # no tsconfig.json
    (tmp_path / "tsconfig.json").write_text('{"files": [], "references": []}')
    assert lint_mod.tsc_evidence(tmp_path, pkg) == (
        "tsc:lint:types",
        ["--build", "tsconfig.json", "--pretty"],
    )
    # ``npx tsc …`` / ``yarn tsc …`` scripts are the same tool
    assert lint_mod.tsc_evidence(tmp_path, {"scripts": {"lint:types": "npx tsc --noEmit"}}) == (
        "tsc:lint:types",
        ["--noEmit"],
    )
    # a chained lint:types cannot be honoured verbatim: the build form is used
    chained = {"scripts": {"lint:types": "tsc --build && echo ok"}}
    assert lint_mod.tsc_evidence(tmp_path, chained) == (
        "tsc:lint:types",
        ["--build", "tsconfig.json"],
    )
    # any other script invoking tsc: --build when it says so, else --noEmit -p
    assert lint_mod.tsc_evidence(tmp_path, {"scripts": {"typecheck": "tsc --noEmit"}}) == (
        "tsc:script:typecheck",
        ["--noEmit", "-p", "tsconfig.json"],
    )
    assert lint_mod.tsc_evidence(tmp_path, {"scripts": {"build": "tsc -b"}}) == (
        "tsc:script:build",
        ["--build", "tsconfig.json"],
    )
    # ``tsc --build --clean`` (nhsuk-frontend's postclean) checks nothing: not evidence
    assert (
        lint_mod.tsc_evidence(tmp_path, {"scripts": {"postclean": "tsc --build --clean"}}) is None
    )
    # a script that merely mentions tsc in another word is not tsc
    assert lint_mod.tsc_evidence(tmp_path, {"scripts": {"x": "tscribe run"}}) is None
    # typescript in devDependencies + a CI line running tsc
    dev = {"devDependencies": {"typescript": "^6.0.3"}}
    assert lint_mod.tsc_evidence(tmp_path, dev) is None  # no CI evidence yet
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("steps:\n  - run: npx tsc --noEmit\n")
    assert lint_mod.tsc_evidence(tmp_path, dev) == ("tsc:ci", ["--noEmit", "-p", "tsconfig.json"])


def test_js_plan_appends_tsc_after_the_linters_and_never_on_koa(tmp_path: Path) -> None:
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"lint:types": "tsc --build tsconfig.json --pretty"},
                "devDependencies": {"typescript": "^6.0.3"},
            }
        )
    )
    (tmp_path / "tsconfig.json").write_text("{}")
    # the evidence without the binary: nothing to run, nothing detected
    assert lint_mod.js_plan(tmp_path, bin_dir) is None
    (bin_dir / "tsc").write_text("")
    plan = lint_mod.js_plan(tmp_path, bin_dir)
    assert plan is not None and plan.detected == "tsc:lint:types"
    (tool,) = plan.tools
    assert tool.argv == (
        str(bin_dir / "tsc"),
        "--build",
        "tsconfig.json",
        "--pretty",
        "--pretty",
        "false",
    )  # the script verbatim, then --pretty false so the findings parse (the last wins)
    assert tool.paths == "all" and tool.findings_re == lint_mod.TSC_FINDINGS_RE
    assert tool.findings_rcs == frozenset({1, 2})
    assert tool.concerns(["src/a.mjs"]) and not tool.concerns(["README.md", "styles.scss"])
    # eslint + prettier first, tsc appended
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n")
    (tmp_path / ".prettierrc").write_text("{}")
    (bin_dir / "eslint").write_text("")
    (bin_dir / "prettier").write_text("")
    plan = lint_mod.js_plan(tmp_path, bin_dir)
    assert plan is not None and plan.detected == "eslint+prettier+tsc:lint:types"
    assert [t.name for t in plan.tools] == ["eslint", "prettier", "tsc"]
    # under a sandbox the image's PATH resolves it
    plan = lint_mod.js_plan(tmp_path, None)
    assert plan is not None and plan.tools[-1].argv[0] == "tsc"
    # koa: standard, no tsconfig → unchanged
    for f in ("eslint.config.mjs", ".prettierrc", "tsconfig.json"):
        (tmp_path / f).unlink()
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"lint": "standard"}}))
    (bin_dir / "standard").write_text("")
    plan = lint_mod.js_plan(tmp_path, bin_dir)
    assert plan is not None and plan.detected == "standard"


def test_tsc_findings_are_attributed_to_changed_files_only(tmp_path: Path) -> None:
    """A whole-project ``tsc`` reports every error in the tree; only the ones in CHANGED
    files are the builder's."""
    tool = _tsc_tool()
    out = (
        "packages/nhsuk-frontend/src/nhsuk/components/scroll.mjs(47,12): error TS2339: "
        "Property 'x' does not exist on type 'Y'.\n"
        "./shared/legacy.ts(3,1): error TS7006: Parameter 'a' implicitly has an 'any' type.\n"
        "some noise line\n"
        f"{tmp_path}/shared/legacy.ts(9,1): error TS2322: Type 'number' is not assignable.\n"
    )
    changed = ["packages/nhsuk-frontend/src/nhsuk/components/scroll.mjs"]
    assert lint_mod.attribute_findings(tool, out, tmp_path, changed) == (1, 2)
    assert lint_mod.attribute_findings(tool, out, tmp_path, ["shared/legacy.ts"]) == (2, 1)
    assert lint_mod.attribute_findings(tool, out, tmp_path, ["other.ts"]) == (0, 3)
    # the run: a finding in a changed file rejects (attributed), with both counts recorded
    ex = FakeExecutor(_res(1, out))
    run = lint_mod.run_plan(lint_mod.LintPlan((tool,), "tsc:lint:types"), ex, tmp_path, changed)
    assert run.ok is False and run.error == ""
    assert run.note == "tsc rejected 1 finding(s) in changed files (2 elsewhere, not counted)"
    (step,) = run.steps
    assert step.verdict is False and (step.findings_changed, step.findings_other) == (1, 2)
    assert step.files == ()  # whole-project: no file arguments
    assert ex.commands[0].argv == tool.argv
    # rc 2 (diagnostics present, outputs generated) is a findings code too
    run = lint_mod.run_plan(
        lint_mod.LintPlan((tool,), "tsc:lint:types"), FakeExecutor(_res(2, out)), tmp_path, changed
    )
    assert run.ok is False and run.steps[0].findings_changed == 1
    # the round trip keeps the counts
    again = lint_mod.LintRun.from_dict(json.loads(json.dumps(run.to_dict())))
    assert again.steps[0].findings_changed == 1 and again.steps[0].findings_other == 2


def test_tsc_errors_only_in_unchanged_files_are_debt_not_the_builders(tmp_path: Path) -> None:
    tool = _tsc_tool()
    out = "shared/legacy.ts(3,1): error TS7006: Parameter 'a' implicitly has an 'any' type.\n"
    plan = lint_mod.LintPlan((tool,), "tsc:lint:types")
    run = lint_mod.run_plan(plan, FakeExecutor(_res(1, out)), tmp_path, ["src/new.ts"])
    assert run.ok is True and run.error == ""
    assert run.note == (
        "tsc: 1 pre-existing finding(s) in unchanged files, 0 in changed files — not "
        "attributed to the patch"
    )
    (step,) = run.steps
    assert step.verdict is True and step.rc == 1
    assert (step.findings_changed, step.findings_other) == (0, 1)
    # a later step still runs after an attributed-away rejection
    ruff = lint_mod.LintTool("after", ("after",), lint_mod.PATHS_ALL)
    ex = FakeExecutor(_res(1, out), _res(0))
    run = lint_mod.run_plan(lint_mod.LintPlan((tool, ruff), "x"), ex, tmp_path, ["src/new.ts"])
    assert run.ok is True and len(run.steps) == 2 and len(ex.commands) == 2
    # a rejection that names NO file cannot be attributed: harness error, never a pass
    run = lint_mod.run_plan(
        plan,
        FakeExecutor(_res(1, "error TS5083: Cannot read file 'tsconfig.dev.json'.\n")),
        tmp_path,
        ["src/new.ts"],
    )
    assert run.ok is False and "no finding attributable to a file" in run.error
    assert run.steps[0].verdict is None
    # a read-only sandbox mount (tsbuildinfo cannot be written) is a harness error too
    tool_ro = _tsc_tool(unrunnable_re=r"error TS5033: Could not write file")
    run = lint_mod.run_plan(
        lint_mod.LintPlan((tool_ro,), "x"),
        FakeExecutor(_res(1, "error TS5033: Could not write file 'x.tsbuildinfo': EROFS\n")),
        tmp_path,
        ["src/new.ts"],
    )
    assert run.ok is False and "not runnable" in run.error
    # a timeout is a failure, attributed or not
    run = lint_mod.run_plan(plan, FakeExecutor(_res(1, out, timed_out=True)), tmp_path, ["a.ts"])
    assert run.ok is False and run.steps[0].timed_out
    # rc 3 (invalid project) is the tool's own failure
    run = lint_mod.run_plan(plan, FakeExecutor(_res(3, "")), tmp_path, ["a.ts"])
    assert run.ok is False and "tool failed (rc=3)" in run.error
    # nothing type-checkable changed: the step is skipped, the belt not evaluated
    run = lint_mod.run_plan(plan, FakeExecutor(), tmp_path, ["README.md"])
    assert run.ok is None and run.steps == ()
    with pytest.raises(ValueError, match="named group 'file'"):
        lint_mod.LintTool("x", ("x",), findings_re=r"\d+")


def test_plan_from_config_accepts_findings_re() -> None:
    plan = lint_mod.plan_from_config(
        {
            "command": ["tsc", "--noEmit", "--pretty", "false"],
            "paths": "all",
            "exts": [".ts"],
            "findings_rc": [1, 2],
            "findings_re": lint_mod.TSC_FINDINGS_RE,
        }
    )
    assert plan is not None and plan.tools[0].findings_re == lint_mod.TSC_FINDINGS_RE
    assert plan.tools[0].to_dict()["findings_re"] == lint_mod.TSC_FINDINGS_RE


def _fake_tsc(bin_dir: Path, *, broken_files: tuple[str, ...], debt: tuple[str, ...] = ()) -> Path:
    """A fake ``tsc`` in the NHS output shape: an error line per ``broken_files`` entry
    that exists and per ``debt`` entry (pre-existing, always), exit 1 when any."""
    lines = ["n=0"]
    for f in broken_files:
        lines.append(
            f'[ -f "{f}" ] && grep -q "TYPE_ERROR" "{f}" && {{ echo "{f}(2,9): error TS2322: Type \'number\' is not assignable to type \'string\'."; n=1; }}'
        )
    for f in debt:
        lines.append(
            f"echo \"{f}(1,1): error TS7006: Parameter 'a' implicitly has an 'any' type.\"; n=1"
        )
    lines.append('[ "$n" = "1" ] && exit 1\nexit 0\n')
    return _script(bin_dir / "tsc", "\n".join(lines))


@pytest.mark.toolchain("node")
@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
def test_node_tsc_type_error_in_a_changed_file_is_a_lint_failure(tmp_path: Path) -> None:
    """The NHS shape (``lint:types`` + ``tsconfig.json`` + ``node_modules/.bin/tsc``): a
    patch that leaves a type error in a file it touched grades ``repo_lint_clean=False``,
    not clean, ``failure_kind="lint"`` — the row the repository's own CI would reject."""
    root, feat_sha = noderepo.build(tmp_path, "node", extra=noderepo.ts_extra("node"))
    bin_dir = root / "node_modules" / ".bin"
    _fake_tsc(bin_dir, broken_files=(noderepo.SRC_TYPES,))
    repo, config = GitRepo(root), noderepo.config("node")
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)
    # the builder also edited the type-checked module and got it wrong
    (ws.root / noderepo.SRC_TYPES).write_text(
        noderepo.TYPES_OK.replace(
            "return `n=${n}`;", "const out: string = n; // TYPE_ERROR\n  return out;"
        )
    )
    res = _grade(ws, task, config)
    assert res.lint_run is not None and res.lint_run.detected == "tsc:lint:types"
    assert res.lint_run.steps[0].argv[1:] == (
        "--build",
        "tsconfig.json",
        "--pretty",
        "--pretty",
        "false",
    )
    assert res.belts.target_green is True and res.belts.repo_lint_clean is False
    assert not res.clean and res.error == ""
    assert (res.lint_run.steps[0].findings_changed, res.lint_run.steps[0].findings_other) == (1, 0)
    assert lg.grade_row_from_result(res, task, pack_hash="c" * 64).failure_kind == "lint"
    ws.remove()


@pytest.mark.toolchain("node")
@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
def test_node_tsc_pre_existing_error_in_an_unchanged_file_is_not_attributed(tmp_path: Path) -> None:
    """The maintainers' type debt in a file the builder never touched: belt 5 stays
    ``True`` and the run's note records the debt — never the builder's ``lint``."""
    root, feat_sha = noderepo.build(tmp_path, "node", extra=noderepo.ts_extra("node"))
    bin_dir = root / "node_modules" / ".bin"
    _fake_tsc(bin_dir, broken_files=(), debt=(noderepo.SRC_TYPES,))
    repo, config = GitRepo(root), noderepo.config("node")
    task = _mine(repo, config, feat_sha, tmp_path)
    ws = _trial(repo, config, task, tmp_path / "t")
    ws.overlay_sources(task.src_files)  # touches src/sub.js only; src/types.ts is untouched
    res = _grade(ws, task, config)
    assert res.lint_run is not None and res.lint_run.detected == "tsc:lint:types"
    assert res.belts.repo_lint_clean is True and res.clean
    assert "1 pre-existing finding(s) in unchanged files" in res.lint_run.note
    (step,) = res.lint_run.steps
    assert step.rc == 1 and step.verdict is True
    assert (step.findings_changed, step.findings_other) == (0, 1)
    ws.remove()


@pytest.mark.toolchain("tsc")
@pytest.mark.skipif(
    not (langs.has_tool("node") and langs.has_tool("tsc")), reason="tsc not on PATH"
)
def test_real_tsc_attributes_type_errors_by_file(tmp_path: Path) -> None:
    """The real TypeScript compiler (whatever version is on PATH): its ``file(line,col):
    error TSnnnn`` lines parse under ``TSC_FINDINGS_RE``; a type error the builder
    introduced rejects, the maintainers' pre-existing one does not."""
    tsc_host = Path(shutil.which("tsc") or "")
    extra = noderepo.ts_extra("node", lint_types=noderepo.LINT_TYPES_NOEMIT)
    extra["src/legacy.ts"] = noderepo.TYPES_BROKEN  # the maintainers' debt, untouched
    root, feat_sha = noderepo.build(tmp_path, "node", extra=extra)
    bin_dir = root / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "tsc").symlink_to(tsc_host.resolve())
    repo, config = GitRepo(root), noderepo.config("node")
    task = _mine(repo, config, feat_sha, tmp_path)
    # 1. the gold patch alone: legacy.ts's error is pre-existing → belt True, noted
    ws = _trial(repo, config, task, tmp_path / "t1")
    ws.overlay_sources(task.src_files)
    res = _grade(ws, task, config)
    assert res.lint_run is not None, res
    assert res.lint_run.detected == "tsc:lint:types" and res.lint_run.error == ""
    assert res.belts.repo_lint_clean is True and res.clean, res.lint_run
    (step,) = res.lint_run.steps
    assert step.rc in (1, 2) and (step.findings_changed, step.findings_other) == (0, 1)
    assert "src/legacy.ts(2," in step.tail
    ws.remove()
    # 2. the builder breaks the module it touched → attributed, belt False, kind lint
    ws2 = _trial(repo, config, task, tmp_path / "t2")
    ws2.overlay_sources(task.src_files)
    (ws2.root / noderepo.SRC_TYPES).write_text(noderepo.TYPES_BROKEN)
    res2 = _grade(ws2, task, config)
    assert res2.lint_run is not None and res2.belts.repo_lint_clean is False and not res2.clean
    (step2,) = res2.lint_run.steps
    assert (step2.findings_changed, step2.findings_other) == (1, 1)
    assert lg.grade_row_from_result(res2, task, pack_hash="c" * 64).failure_kind == "lint"
    ws2.remove()


def test_pinned_ruff_spec_reads_the_commit_not_the_host(tmp_path: Path) -> None:
    """Belt 5 applies the repository's linter VERSION (mesh-client: host ruff 0.16 rejected
    the maintainers' patches under a ``^0.2`` pin, 2026-09-14)."""
    from crb.core.lint import _poetry_to_pep440, pinned_ruff_spec

    assert pinned_ruff_spec(tmp_path) == ""
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.4.4\n"
        "    hooks:\n      - id: ruff\n",
        encoding="utf-8",
    )
    assert pinned_ruff_spec(tmp_path) == "==0.4.4"
    (tmp_path / ".pre-commit-config.yaml").unlink()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n[project.optional-dependencies]\n'
        'dev = ["pytest", "ruff>=0.5,<0.6"]\n',
        encoding="utf-8",
    )
    assert pinned_ruff_spec(tmp_path) == ">=0.5,<0.6"
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\nversion = "0"\n[tool.poetry.dev-dependencies]\nruff = "^0.2.0"\n',
        encoding="utf-8",
    )
    assert pinned_ruff_spec(tmp_path) == ">=0.2.0,<0.3.0"
    assert _poetry_to_pep440("~1.4") == ">=1.4.0,<1.5.0" and _poetry_to_pep440("0.4.4") == "==0.4.4"
