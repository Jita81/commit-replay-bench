"""A replay whose runner tool is missing is refused before any builder call — never graded as a
harness failure after the builder has been paid.

On nhsuk-react-components six attempts reached the builder and were then graded ``harness``
because ``jest`` was not in the repository's environment (``errclass`` EJ in the 2026-09-25
ledger export; docs/PREVENTION.md P-004). The grader's first command could never have run, so
every one of those attempts was spend on a certain failure.

Navigation
----------
What it is:   The test suite for src/crb/builders/toolcheck.py and its call in the adapter's
              ``build`` step.
What it does: Pins that a test command whose first word does not resolve on the host refuses
              the attempt with ``runner tool missing: <tool>`` BEFORE the builder is
              instantiated or called (nothing spent), that the refusal is a ``harness`` row by
              the product's own failure rule, that a tool that does resolve (the real pytest
              runner) lets the builder run, that a repository-relative tool must exist and be
              executable, that the node runners' missing ``jest`` is named, and that a sandbox
              executor is not second-guessed from the host.
How:          The pyrepo fixture with the real ``PytestRunner``, and a runner whose command
              starts with a tool that does not exist; a counting fake builder registered for
              the test.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/builders/toolcheck.py (under test), src/crb/builders/adapter.py (the call
              before the builder), src/crb/core/ledger.py (``derive_failure_kind``),
              src/crb/core/runners/node_runners.py (the jest case), docs/PREVENTION.md (P-004)
Tested by:    (this is a test file)
Touch when:   a runner whose command does not start with its tool is added (teach
              ``runner_tool_missing`` where the tool is).
"""

from __future__ import annotations

import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import STOP_DONE, Budget, BuildBrief, BuildOutcome, EscalationLadder, Rung
from crb.builders.toolcheck import RUNNER_TOOL_MISSING, runner_tool_missing
from crb.core.execution import Command, Executor, LocalExecutor
from crb.core.ledger import FAILURE_HARNESS, derive_failure_kind
from crb.core.runners.node_runners import JestRunner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import Language, RepoConfig
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

MISSING_TOOL = "crb-no-such-test-tool-7f3a"


class CountingBuilder:
    """Counts every instantiation and every build; builds nothing."""

    name = "counting"
    made: ClassVar[int] = 0
    built: ClassVar[int] = 0

    def __init__(self, *, model: str, provider: str = "", **_: Any) -> None:
        self.model, self.provider = model, provider
        CountingBuilder.made += 1

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Budget, **_: Any
    ) -> BuildOutcome:
        CountingBuilder.built += 1
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=True,
            stop_reason=STOP_DONE,
            cost_usd=0.5,
            budget=budget,
        )


class MissingToolRunner(PytestRunner):
    """The real pytest runner, except its test command starts with a tool that is not there."""

    def command(
        self, root: Path, scope: Sequence[str], *, executor: Executor, timeout: int
    ) -> Command:
        cmd = super().command(root, scope, executor=executor, timeout=timeout)
        return Command((MISSING_TOOL, *cmd.argv[1:]), root=cmd.root, cwd_rel=cmd.cwd_rel)


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "counting", CountingBuilder)
    CountingBuilder.made = 0
    CountingBuilder.built = 0


def _attempt(pyrepo: pr.PyRepo, tmp_path: Path, runner: PytestRunner, mode: str) -> Any:
    ladder = EscalationLadder((Rung("counting", "m"),))
    fn = adapter.build_fn_for(
        ladder, budget=Budget(), runner=runner, executor=LocalExecutor(), config=pyrepo.config
    )
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=mode == "sighted")
    try:
        return fn(ws, pyrepo.feat_task(), mode, "counting:m")
    finally:
        ws.remove()


@pytest.mark.parametrize("mode", ["sighted", "blind"])
def test_a_missing_runner_tool_refuses_the_attempt_before_any_builder_call(
    pyrepo: pr.PyRepo, tmp_path: Path, mode: str
) -> None:
    attempt = _attempt(pyrepo, tmp_path, MissingToolRunner(pyrepo.config), mode)
    assert attempt.error.startswith(RUNNER_TOOL_MISSING + MISSING_TOOL)
    assert "refused before any builder call" in attempt.error
    assert CountingBuilder.made == 0 and CountingBuilder.built == 0  # nothing spent
    # the product's own rule names it an instrument failure, never the model's
    assert (
        derive_failure_kind(clean=False, disqualified=False, error=attempt.error) == FAILURE_HARNESS
    )


def test_a_tool_that_resolves_lets_the_builder_run(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    attempt = _attempt(pyrepo, tmp_path, PytestRunner(pyrepo.config), "blind")
    assert attempt.error == "" and CountingBuilder.built == 1


def test_a_repository_relative_tool_must_exist_and_be_executable(tmp_path: Path) -> None:
    runner = MissingToolRunner(RepoConfig(name="r", language=Language.PYTHON))
    ex = LocalExecutor()
    tool = tmp_path / "gradlew"

    def check(argv0: str) -> str:
        class R(MissingToolRunner):
            def command(self, root: Path, scope: Sequence[str], **_: Any) -> Command:
                return Command((argv0, "test"), root=root)

        return runner_tool_missing(R(runner.config), ex, tmp_path)

    assert check("./gradlew").startswith(RUNNER_TOOL_MISSING + "gradlew")
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    assert check("./gradlew").startswith(RUNNER_TOOL_MISSING)  # present but not executable
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    assert check("./gradlew") == "" and check(str(tool)) == ""
    assert check("git") == ""  # a bare name on PATH
    assert check(MISSING_TOOL).startswith(RUNNER_TOOL_MISSING + MISSING_TOOL)


def test_jest_missing_from_the_repository_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nhsuk-react-components case: ``node_modules/.bin`` exists (setup ran) but holds no
    ``jest``, and there is none on PATH."""
    (tmp_path / "node_modules" / ".bin").mkdir(parents=True)
    (tmp_path / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    runner = JestRunner(RepoConfig(name="r", language=Language.JAVASCRIPT, runner="jest"))
    why = runner_tool_missing(runner, LocalExecutor(), tmp_path)
    assert why.startswith(RUNNER_TOOL_MISSING + "jest")
    assert "crb repo setup" in why


def test_a_sandbox_executor_is_not_second_guessed_from_the_host(pyrepo: pr.PyRepo) -> None:
    class Sandboxed(LocalExecutor):
        name = "docker"

    runner = MissingToolRunner(pyrepo.config)
    assert runner_tool_missing(runner, Sandboxed(), pyrepo.path) == ""
