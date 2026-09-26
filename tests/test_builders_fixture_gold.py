"""The test-only ``fixture_gold`` builder: opt-in registration, unmistakable identity,
zero spend, and an end-to-end build the core grader marks clean (the instrument
check the browser walkthrough relies on).

Navigation
----------
What it is:   The test-only ``fixture_gold`` builder's test suite — opt-in registration,
              unmistakable identity, zero spend, and a build the grader marks clean.
What it does: Pins that exactly one switch (``CRB_ENABLE_FIXTURE_BUILDER``) registers it and
              that without the switch it is absent, that its identity is forced (it can never
              masquerade as a real model), that it overlays only non-test files, that build then
              grade is clean on all four belts, that blind mode works without test paths —
              the instrument check the browser walkthrough relies on — and that an
              ``attempt`` the real guard refuses is recorded as a protocol violation (never
              run), while an allowed one records nothing.
How:          Re-imports ``crb.builders`` under the switch; ``trial`` + ``feat_task`` from
              ``conftest.py``; the real ``grade``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/fixture_gold.py (under test), src/crb/builders/__init__.py (the
              registry and the switch), scripts/walkthrough.sh (sets the switch for the
              hermetic tier), ui/e2e/walkthrough/05-replay-fake.spec.ts (the replay it drives)
Tested by:    tests/test_builders_fixture_gold.py
Touch when:   never for a new repository; only if the registry's opt-in mechanism changes (the
              "absent without the switch" case is the production guarantee).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import crb.builders as builders_pkg
from crb.builders import base
from crb.builders import fixture_gold as fg
from crb.core.execution import LocalExecutor
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.posture import grade_adhoc as grade

# --- the switch -----------------------------------------------------------------------


def test_switch_is_exactly_one() -> None:
    assert fg.fixture_builder_enabled({}) is False
    assert fg.fixture_builder_enabled({fg.ENABLE_ENV: "1"}) is True
    assert fg.fixture_builder_enabled({fg.ENABLE_ENV: " 1 "}) is True
    for off in ("0", "true", "yes", "", "2"):
        assert fg.fixture_builder_enabled({fg.ENABLE_ENV: off}) is False, off


def test_unregistered_without_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fg.ENABLE_ENV, raising=False)
    importlib.reload(builders_pkg)
    assert fg.NAME not in builders_pkg.builder_names()
    with pytest.raises(ValueError, match="unknown builder"):
        builders_pkg.get_builder(fg.NAME, model="gold")


def test_registered_with_the_switch_and_identity_is_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(fg.ENABLE_ENV, "1")
    try:
        importlib.reload(builders_pkg)
        assert fg.NAME in builders_pkg.builder_names()
        # whatever the rung says, the recorded identity is the fixture's
        b = builders_pkg.builder_for_rung(base.Rung(fg.NAME, "claude-sonnet-5", "anthropic"))
        assert (b.name, b.model, b.provider) == (fg.NAME, fg.MODEL, fg.PROVIDER)
        assert isinstance(b, base.Builder)
        d = b.describe()
        assert d["fixture"] is True and "archaeology" in d["warning"]
    finally:
        monkeypatch.delenv(fg.ENABLE_ENV, raising=False)
        importlib.reload(builders_pkg)
        assert fg.NAME not in builders_pkg.builder_names()


# --- the build ------------------------------------------------------------------------


def _brief(task: TaskSpec, config: RepoConfig, *, mode: str = "sighted") -> base.BuildBrief:
    return base.BuildBrief.from_task(task, mode=mode, config=config)


def test_overlays_only_non_test_files(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, trial: Workspace
) -> None:
    b = fg.FixtureGoldBuilder()
    brief = _brief(feat_task, pyrepo.config)
    assert b.source_files(trial, brief) == [pr.SRC]  # tests/test_subtract.py is excluded
    events: list[tuple[str, dict[str, object]]] = []
    out = b.build(trial, brief, base.Budget(), on_event=lambda a, p: events.append((a, dict(p))))
    assert trial.read(pr.SRC) == pr.SRC_FEAT
    assert out.builder == fg.NAME and out.model == fg.MODEL and out.provider == fg.PROVIDER
    assert out.done is False  # never a claim
    assert out.cost_usd == 0.0 and out.cost_known is True
    assert out.tokens_in == 0 and out.tokens_out == 0 and out.transcript == ()
    assert out.stop_reason == base.STOP_DONE and out.errors == ()
    assert out.extra["fixture"] is True and out.extra["files"] == [pr.SRC]
    assert [a for a, _ in events] == ["build.attempt", "build.done"]
    ref = out.builder_ref()
    assert ref.name == fg.NAME and ref.cost_usd == 0.0


def test_build_then_grade_is_clean_on_all_four_belts(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, trial: Workspace, tmp_path: Path
) -> None:
    b = fg.FixtureGoldBuilder()
    b.build(trial, _brief(feat_task, pyrepo.config), base.Budget())
    res = grade(
        trial,
        feat_task,
        config=pyrepo.config,
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
    )
    assert res.clean and res.belts.all_true
    assert not res.disqualified and res.error == ""


def test_blind_mode_works_without_test_paths(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, tmp_path: Path
) -> None:
    ws = pyrepo.trial(tmp_path / "blind", overlay_tests=False)
    try:
        b = fg.FixtureGoldBuilder()
        out = b.build(ws, _brief(feat_task, pyrepo.config, mode="blind"), base.Budget())
        assert out.mode == "blind"
        assert ws.read(pr.SRC) == pr.SRC_FEAT
        assert not ws.exists(pr.TEST_SUBTRACT)  # the oracle stays held out
    finally:
        ws.remove()


# --- a refusal on purpose (G-913: the Learn walkthrough needs a real one) ----------------


def test_an_attempted_command_the_guard_refuses_is_recorded_as_a_protocol_violation(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, trial: Workspace
) -> None:
    """``builder_config {"attempt": …}`` asks the REAL shell guard about one command, as a
    builder's tool call would. A refusal is recorded exactly as the agentic builders record
    one (``<reason> (attempted: <cmd>)``), so the row lands as ``protocol`` and the Learn
    page's refusal triage reads it like any other — the command itself is never run."""
    from crb.builders.adapter import attempt_error
    from crb.core.learn import parse_violations

    b = fg.FixtureGoldBuilder(attempt="git log -p")
    assert b.describe()["attempt"] == "git log -p"
    out = b.build(trial, _brief(feat_task, pyrepo.config), base.Budget())
    assert out.violated and len(out.errors) == 1
    assert out.errors[0].startswith("archaeology:")
    assert out.errors[0].endswith("(attempted: git log -p)")
    error = attempt_error(out)
    assert error.startswith("protocol violation: archaeology:")
    [violation] = parse_violations(error)
    assert violation.prefix == "archaeology" and violation.command == "git log -p"
    assert out.extra["attempt"] == "git log -p"
    assert out.cost_usd == 0.0 and out.done is False  # still spends and claims nothing
    # a refused attempt stops there, as a builder whose one move was refused would: no patch,
    # so the grade is not clean and the row lands as `protocol` (a clean grade outranks it)
    assert out.extra["files"] == [] and trial.read(pr.SRC) != pr.SRC_FEAT


def test_an_attempted_command_the_guard_allows_records_nothing(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, trial: Workspace
) -> None:
    """An honest command is not a violation: the fixture only asks the guard, so an allowed
    command leaves the build exactly as the plain fixture's (clean-gradeable, no errors)."""
    out = fg.FixtureGoldBuilder(attempt="ls -la").build(
        trial, _brief(feat_task, pyrepo.config), base.Budget()
    )
    assert out.errors == () and not out.violated
    assert trial.read(pr.SRC) == pr.SRC_FEAT


def test_a_refused_attempt_grades_as_a_protocol_row_not_a_clean_one(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, trial: Workspace
) -> None:
    """Through the grader and the ledger's one failure rule: the refused attempt's grade is
    not clean, so the row's kind is ``protocol``. The first walkthrough of the Learn spec
    found the opposite — the gold was overlaid after the refusal, the grade came back clean
    and a clean grade outranks the refusal — so no protocol row reached the report (P-052)."""
    from crb.builders.adapter import attempt_error
    from crb.core.ledger import FAILURE_PROTOCOL, derive_failure_kind

    out = fg.FixtureGoldBuilder(attempt="git log -p").build(
        trial, _brief(feat_task, pyrepo.config), base.Budget()
    )
    res = grade(
        trial,
        feat_task,
        config=pyrepo.config,
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
    )
    assert not res.clean
    kind = derive_failure_kind(
        clean=res.clean,
        disqualified=res.disqualified,
        error=res.error,
        builder_error=attempt_error(out),
    )
    assert kind == FAILURE_PROTOCOL
