"""crb.core.grade — the four-belt grader on real pytest runs against the fixture repo.

Every test here runs the actual ``PytestRunner`` under the actual ``LocalExecutor``:
the belts are judged by pytest's own exit code and short summary, never by a stub.
Stubs are used only to inject harness *failures* (timeouts, exceptions) that a
healthy fixture cannot produce on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from crb.core import grade as g
from crb.core.execution import LocalExecutor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.oracle import controls as nc  # read-only here: the env_poison transform
from crb.core.runners import base as rb
from crb.core.runners import get_runner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs  # type: ignore[no-redef]

Events = list[tuple[str, dict[str, Any]]]


def _collector() -> tuple[Events, Callable[[str, Any], None]]:
    events: Events = []

    def on_event(action: str, payload: Any) -> None:
        events.append((action, dict(payload)))

    return events, on_event


def _grade(
    ws: Workspace,
    task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    **kw: Any,
) -> g.GradeResult:
    return g.grade(ws, task, config=pyrepo.config, runner=runner, executor=executor, **kw)


# ---------------------------------------------------------------------------
# The invariant: GradeResult cannot be clean with a failed belt
# ---------------------------------------------------------------------------

_ALL_TRUE = g.Belts(True, True, True, True)


def test_belts_all_true_and_round_trip() -> None:
    assert _ALL_TRUE.all_true
    assert not g.Belts(True, True, True, None).all_true
    assert not g.Belts(True, True, False, True).all_true
    assert not g.Belts().all_true
    d = g.Belts(True, False, None, True).to_dict()
    assert d == {
        "tests_unmodified": True,
        "target_green": False,
        "no_new_failures": None,
        "source_changed": True,
        "repo_lint_clean": None,
    }
    assert g.Belts.from_dict(d) == g.Belts(True, False, None, True)
    assert g.Belts.from_dict({}) == g.Belts()


def test_belt_five_is_optional_none_is_not_evaluated_false_is_never_clean() -> None:
    """ADR-0011: belt 5 ``None`` = not evaluated (clean still possible); ``False`` = not
    clean; ``True`` = the repo's own linter accepted the changed files."""
    assert (*g.CORE_BELT_NAMES, "repo_lint_clean") == g.BELT_NAMES
    assert g.OPTIONAL_BELT_NAMES == ("repo_lint_clean",)
    assert g.Belts(True, True, True, True, None).all_true
    assert g.Belts(True, True, True, True, True).all_true
    assert not g.Belts(True, True, True, True, False).all_true
    # a lint pass never rescues a failed core belt
    assert not g.Belts(True, True, False, True, True).all_true
    assert g.Belts(True, True, True, True, None).evaluated == g.CORE_BELT_NAMES
    assert g.Belts(True, True, True, True, False).evaluated == g.BELT_NAMES
    assert g.Belts(True, None, None, None, None).evaluated == ("tests_unmodified",)
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult(
            "a" * 40, "r", g.MODE_SIGHTED, clean=True, belts=g.Belts(True, True, True, True, False)
        )
    ok = g.GradeResult(
        "a" * 40, "r", g.MODE_SIGHTED, clean=True, belts=g.Belts(True, True, True, True, True)
    )
    assert ok.to_dict()["repo_lint_clean"] is True and ok.to_dict()["lint_run"] is None
    core = dict.fromkeys(g.CORE_BELT_NAMES, True)
    assert g.derive_clean(core)  # absent = not evaluated
    assert g.derive_clean({**core, "repo_lint_clean": None})
    assert g.derive_clean({**core, "repo_lint_clean": True})
    assert not g.derive_clean({**core, "repo_lint_clean": False})


@pytest.mark.parametrize(
    "belts",
    [
        g.Belts(False, True, True, True),
        g.Belts(True, False, True, True),
        g.Belts(True, True, False, True),
        g.Belts(True, True, True, False),
        g.Belts(True, True, True, None),
        g.Belts(),
    ],
)
def test_clean_with_a_failed_belt_is_a_false_q1_violation(belts: g.Belts) -> None:
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult("a" * 40, "r", g.MODE_SIGHTED, clean=True, belts=belts)


def test_clean_with_disqualification_or_error_is_a_false_q1_violation() -> None:
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult("a" * 40, "r", g.MODE_SIGHTED, clean=True, belts=_ALL_TRUE, disqualified=True)
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult("a" * 40, "r", g.MODE_SIGHTED, clean=True, belts=_ALL_TRUE, error="boom")


def test_false_q1_violation_is_an_assertion_error() -> None:
    assert issubclass(g.FalseQ1Violation, AssertionError)


def test_grade_result_accepts_clean_only_when_everything_holds() -> None:
    r = g.GradeResult("a" * 40, "r", g.MODE_BLIND, clean=True, belts=_ALL_TRUE, extra={"k": 1})
    assert r.clean and r.extra == {"k": 1}
    d = r.to_dict()
    assert d["mode"] == "blind"
    assert d["diff"] is None and d["target_run"] is None and d["belt_run"] is None
    assert all(d[b] is True for b in g.CORE_BELT_NAMES) and d["repo_lint_clean"] is None
    assert g.GradeResult("a" * 40, "r", g.MODE_SIGHTED, clean=False, belts=_ALL_TRUE).clean is False


def test_grade_result_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        g.GradeResult("a" * 40, "r", "peek", clean=False, belts=g.Belts())


def test_derive_clean() -> None:
    ok = dict.fromkeys(g.BELT_NAMES, True)
    assert g.derive_clean(ok)
    assert not g.derive_clean({**ok, "source_changed": False})
    assert not g.derive_clean({**ok, "no_new_failures": None})
    assert not g.derive_clean(ok, disqualified=True)
    assert not g.derive_clean(ok, error="x")
    assert not g.derive_clean({})


# ---------------------------------------------------------------------------
# Sighted mode on the real fixture
# ---------------------------------------------------------------------------


def test_gold_patch_is_clean(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_gold(trial)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.clean is True
    assert res.belts == _ALL_TRUE
    assert not res.disqualified and res.error == "" and res.note == ""
    assert res.new_failures == ()
    assert res.changed_files == (pr.SRC,)
    assert res.diff is not None
    assert res.diff.files == (pr.SRC,)
    assert res.diff.additions == pr.FEAT_SRC_CHURN
    assert res.target_run is not None and res.target_run.green
    assert res.belt_run is not None and res.belt_run.green
    assert res.belt_run.failing == frozenset()
    assert res.duration_s > 0
    d = res.to_dict()
    assert d["clean"] is True and d["target_run"]["returncode"] == 0


def test_noop_leaves_target_red(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_noop(trial)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.clean is False
    assert res.belts.tests_unmodified is True
    assert res.belts.target_green is False
    assert res.belts.no_new_failures is None  # never reached
    assert res.belts.source_changed is None
    assert res.note.startswith("target not green (rc=")
    assert res.target_run is not None
    assert res.target_run.failing == frozenset({pr.TEST_SUBTRACT})  # collection error
    assert res.belt_run is None
    assert not res.disqualified


def test_tampered_target_test_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_tamper(trial)
    events, on_event = _collector()
    res = _grade(trial, feat_task, pyrepo, runner, executor, on_event=on_event)
    assert res.disqualified is True
    assert res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.belts.target_green is None  # nothing was run for a tampered oracle
    assert res.tamper_files == (pr.TEST_SUBTRACT,)
    assert "disqualified" in res.dq_reason
    assert res.target_run is None
    assert events == [
        ("grade.belt", {"task": feat_task.task_id, "belt": "tests_unmodified", "value": False})
    ]


def test_neighbouring_test_rewritten_is_disqualified_in_sighted_mode(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """Belt 1c: a regression hidden by rewriting the NEIGHBOURING test to ``assert True``
    graded clean on 2026-09-14 (human-review-guide exercise 3b) — the target stayed
    byte-identical and belt 3 saw no failure. Any touched non-target file under the
    test layout now disqualifies, in both modes."""
    pr.apply_regression(trial)
    (trial.root / pr.TEST_CALC).write_text("def test_add():\n    assert True\n", encoding="utf-8")
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.disqualified is True and res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.dq_reason.startswith("non-target test files modified")
    assert pr.TEST_CALC in res.tamper_files
    assert res.target_run is None  # nothing ran: the oracle's neighbourhood was touched


def test_regression_patch_fails_belt_three_with_new_failures_listed(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_regression(trial)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.clean is False
    assert res.belts.tests_unmodified is True
    assert res.belts.target_green is True
    assert res.belts.no_new_failures is False
    assert res.belts.source_changed is True
    assert res.new_failures == tuple(sorted(pr.TEST_CALC_IDS))
    assert res.note == "2 new failure(s)"
    assert res.belt_run is not None and res.belt_run.failing == frozenset(pr.TEST_CALC_IDS)
    assert res.changed_files == (pr.SRC,)
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult(res.task_id, res.repo, res.mode, clean=True, belts=res.belts)


def test_baseline_failures_are_not_new_failures(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """Belt 3 is baseline-relative: failures already recorded at the parent do not count."""
    pr.apply_regression(trial)
    task = feat_task.with_(baseline_failing=[*feat_task.baseline_failing, *pr.TEST_CALC_IDS])
    res = _grade(trial, task, pyrepo, runner, executor)
    assert res.belts.no_new_failures is True
    assert res.clean is True


def test_hardcoded_patch_passes_every_belt(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """A patch that special-cases the oracle's inputs IS clean under the four belts.

    This is exactly why oracle adequacy (mutation strength, negative controls) exists
    as a separate gate: the belts prove the builder satisfied the repo's tests; only a
    stronger oracle can prove the tests were worth satisfying. The grader records the
    observation honestly — it does not pretend to detect what it cannot.
    """
    pr.apply_hardcoded(trial)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.clean is True
    assert res.belts == _ALL_TRUE
    assert res.changed_files == (pr.SRC,)
    assert res.diff is not None and res.diff.additions > pr.FEAT_SRC_CHURN
    assert "(5, 3)" in trial.read(pr.SRC)  # the special-casing is really in the graded tree


def test_green_without_source_change_fails_belt_four(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    """A target that is already green at the parent with nothing changed is not an
    observation of capability: belt 4 refuses it with the build-cache-ghost note."""
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        res = _grade(ws, pyrepo.green_task(), pyrepo, runner, executor)
        assert res.clean is False
        assert res.belts == g.Belts(True, True, True, False)
        assert "no source change" in res.note
        assert res.changed_files == ()
    finally:
        ws.remove()


def test_test_only_patch_does_not_count_as_a_source_change(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    """Since belt 1c (2026-09-14) a NEW file under the test layout is a touched
    non-target test file and disqualifies before belt 4 is reached; the row is still
    never clean and still records no source change."""
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_test_only(ws)
        res = _grade(ws, pyrepo.green_task(), pyrepo, runner, executor)
        assert res.disqualified is True and res.clean is False
        assert res.belts.tests_unmodified is False
        assert res.belts.source_changed is None  # not reached
        assert "tests/test_extra.py" in res.tamper_files
    finally:
        ws.remove()


def test_malformed_oracle_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.write_files(trial, [("tests/test_nothing.py", "VALUE = 1\n")])
    task = feat_task.with_(
        test_files=["tests/test_nothing.py"], target_tests=["tests/test_nothing.py"]
    )
    events, on_event = _collector()
    res = _grade(trial, task, pyrepo, runner, executor, on_event=on_event)
    assert res.disqualified is True
    assert res.dq_reason.startswith("malformed oracle")
    assert "tests/test_nothing.py" in res.dq_reason
    assert res.belts == g.Belts()
    assert events == [
        ("grade.malformed_oracle", {"task": task.task_id, "files": ["tests/test_nothing.py"]})
    ]


def test_missing_oracle_file_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    task = feat_task.with_(test_files=["tests/test_absent.py"])
    res = _grade(trial, task, pyrepo, runner, executor)
    assert res.disqualified and "malformed oracle" in res.dq_reason


def test_events_are_emitted_per_belt_in_order(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_gold(trial)
    events, on_event = _collector()
    res = _grade(trial, feat_task, pyrepo, runner, executor, on_event=on_event)
    assert res.clean
    belts = [(p["belt"], p["value"]) for k, p in events if k == "grade.belt"]
    # the pyrepo fixture configures no linter: belt 5 is not evaluated and emits no event
    assert res.belts.repo_lint_clean is None and res.lint_run is None
    assert belts == [(b, True) for b in g.CORE_BELT_NAMES]
    target = next(p for k, p in events if p.get("belt") == "target_green")
    assert target["rc"] == 0 and target["timed_out"] is False
    belt3 = next(p for k, p in events if p.get("belt") == "no_new_failures")
    assert belt3["new"] == []


def test_grade_rejects_unknown_mode(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    with pytest.raises(ValueError, match="mode"):
        _grade(trial, feat_task, pyrepo, runner, executor, mode="peek")


# ---------------------------------------------------------------------------
# Blind mode
# ---------------------------------------------------------------------------


def test_blind_touching_a_test_pre_overlay_is_disqualified(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_gold(ws)
        pr.apply_test_only(ws, "tests/test_sneaky.py")  # any test file, not just the target
        events, on_event = _collector()
        res = _grade(ws, feat_task, pyrepo, runner, executor, mode=g.MODE_BLIND, on_event=on_event)
        assert res.disqualified is True
        assert res.dq_reason.startswith("blind:")
        assert res.tamper_files == ("tests/test_sneaky.py",)
        assert res.belts.tests_unmodified is False
        assert res.clean is False
        assert events == [
            ("grade.tamper", {"task": feat_task.task_id, "files": ["tests/test_sneaky.py"]})
        ]
        assert not ws.exists(pr.TEST_SUBTRACT)  # oracle never landed
    finally:
        ws.remove()


def test_blind_pre_written_target_test_is_disqualified(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    """Writing the target file itself pre-overlay would be silently erased by the
    overlay — belt 0 catches it before that can happen."""
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_gold(ws)
        pr.write_files(ws, [(pr.TEST_SUBTRACT, "def test_subtract():\n    assert True\n")])
        res = _grade(ws, feat_task, pyrepo, runner, executor, mode=g.MODE_BLIND)
        assert res.disqualified and res.tamper_files == (pr.TEST_SUBTRACT,)
    finally:
        ws.remove()


def test_blind_gold_is_clean_and_overlays_the_oracle_at_grade_time(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_gold(ws)
        assert not ws.exists(pr.TEST_SUBTRACT)
        res = _grade(ws, feat_task, pyrepo, runner, executor, mode=g.MODE_BLIND)
        assert res.mode == g.MODE_BLIND
        assert res.clean is True
        assert res.belts == _ALL_TRUE
        assert ws.read(pr.TEST_SUBTRACT) == pr.TEST_SUBTRACT_SRC
    finally:
        ws.remove()


def test_blind_noop_is_red(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        res = _grade(ws, feat_task, pyrepo, runner, executor, mode=g.MODE_BLIND)
        assert res.belts.target_green is False and not res.clean
    finally:
        ws.remove()


# ---------------------------------------------------------------------------
# Harness failures fail closed
# ---------------------------------------------------------------------------


def test_runner_exception_is_recorded_not_raised(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr.apply_gold(trial)

    def boom(*a: Any, **k: Any) -> rb.TestRun:
        raise RuntimeError("pytest binary vanished token=abcdef123456")

    monkeypatch.setattr(runner, "run", boom)
    events, on_event = _collector()
    res = _grade(trial, feat_task, pyrepo, runner, executor, on_event=on_event)
    assert res.clean is False
    assert res.error.startswith("RuntimeError: pytest binary vanished")
    assert "abcdef123456" not in res.error  # redacted
    assert "[REDACTED]" in res.error
    assert res.belts.tests_unmodified is True  # belt 1 had already been recorded
    assert res.belts.target_green is None
    assert events[-1][0] == "grade.error"
    assert "abcdef123456" in events[-1][1]["error"] or "RuntimeError" in events[-1][1]["error"]
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult(res.task_id, res.repo, res.mode, clean=True, belts=_ALL_TRUE, error=res.error)


def test_sandbox_unavailable_propagates(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*a: Any, **k: Any) -> rb.TestRun:
        raise SandboxUnavailable("no daemon")

    monkeypatch.setattr(runner, "run", unavailable)
    with pytest.raises(SandboxUnavailable, match="no daemon"):
        _grade(trial, feat_task, pyrepo, runner, executor)


def test_target_timeout_is_a_failed_belt_two(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr.apply_gold(trial)
    monkeypatch.setattr(
        runner, "run", lambda *a, **k: rb.TestRun(124, frozenset(), "…", timed_out=True)
    )
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.belts.target_green is False
    assert res.note == "target timed out"
    assert res.clean is False


@pytest.mark.parametrize(
    ("belt_run", "expected_note"),
    [
        (rb.TestRun(124, frozenset(), "", timed_out=True), "belt run timed out"),
        (
            rb.TestRun(1, frozenset(), "", parse_error="compile error"),
            "belt run unattributed: compile error",
        ),
    ],
)
def test_belt_timeout_or_unattributed_failure_fails_belt_three(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
    belt_run: rb.TestRun,
    expected_note: str,
) -> None:
    pr.apply_gold(trial)
    real_run = runner.run
    calls = 0

    def run(ex: Any, root: Path, scope: Any, *, timeout: int = 0) -> rb.TestRun:
        nonlocal calls
        calls += 1
        return real_run(ex, root, scope, timeout=timeout) if calls == 1 else belt_run

    monkeypatch.setattr(runner, "run", run)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.belts.target_green is True
    assert res.belts.no_new_failures is False
    assert res.belts.source_changed is True  # belt 4 is still evaluated and recorded
    assert res.note == expected_note
    assert res.new_failures == ()
    assert res.clean is False


def test_run_tails_are_redacted_in_the_result(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr.apply_gold(trial)
    leaky = rb.TestRun(
        0, frozenset(), "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG\nok", duration_s=0.1
    )
    monkeypatch.setattr(runner, "run", lambda *a, **k: leaky)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.target_run is not None and res.belt_run is not None
    assert "wJalrXUtnFEMI" not in res.target_run.tail
    assert "[REDACTED]" in res.target_run.tail
    assert res.target_run.tail.endswith("ok")
    assert res.belt_run.duration_s == 0.1  # everything else preserved


# ---------------------------------------------------------------------------
# Belt 1b: test INFRASTRUCTURE is part of the oracle (ADR-0001, 2026-09-13)
# ---------------------------------------------------------------------------

_INFRA_DQ = "test infrastructure modified"


def _assert_infra_dq(res: g.GradeResult, *files: str) -> None:
    assert res.disqualified is True and res.clean is False
    assert res.belts.tests_unmodified is False
    assert res.belts.target_green is None  # nothing was run
    assert res.target_run is None and res.belt_run is None
    assert res.dq_reason.startswith(_INFRA_DQ), res.dq_reason
    assert res.tamper_files == tuple(files)
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult(res.task_id, res.repo, res.mode, clean=True, belts=res.belts)


def test_new_root_conftest_is_disqualified_sighted(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """An UNTRACKED new root conftest.py — the env_poison shape — fails belt 1 before
    any test runs, even with the gold source in place."""
    pr.apply_gold(trial)
    pr.write_files(trial, [("conftest.py", "import os\nos.environ['X'] = '1'\n")])
    events, on_event = _collector()
    res = _grade(trial, feat_task, pyrepo, runner, executor, on_event=on_event)
    _assert_infra_dq(res, "conftest.py")
    assert events == [
        (
            "grade.tamper",
            {"task": feat_task.task_id, "files": ["conftest.py"], "kind": "test_infra"},
        ),
        ("grade.belt", {"task": feat_task.task_id, "belt": "tests_unmodified", "value": False}),
    ]


def test_edited_pytest_ini_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_gold(trial)
    (trial.root / "pytest.ini").write_text(pr.PYTEST_INI + "pythonpath = shim\n", encoding="utf-8")
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res, "pytest.ini")


def test_deleted_pytest_ini_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """Removing config (filterwarnings=error, required plugins…) is as much an edit
    to the oracle as adding it."""
    pr.apply_gold(trial)
    (trial.root / "pytest.ini").unlink()
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res, "pytest.ini")


def test_renamed_pytest_ini_is_disqualified_under_both_names(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """git's rename detection would otherwise collapse the deletion into the new
    name; touched_files reports both, and both are infra."""
    pr.apply_gold(trial)
    trial.repo.run("mv", "pytest.ini", "tests/pytest.ini", cwd=trial.root, check=True)
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res, "pytest.ini", "tests/pytest.ini")


def test_nested_conftest_and_sitecustomize_are_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_gold(trial)
    pr.write_files(trial, [("tests/conftest.py", "# x\n"), ("src/sitecustomize.py", "# y\n")])
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res, "src/sitecustomize.py", "tests/conftest.py")


def test_target_test_tamper_and_infra_report_both(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    pr.apply_tamper(trial)
    pr.write_files(trial, [("conftest.py", "# x\n")])
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    assert res.disqualified and res.belts.tests_unmodified is False
    assert res.dq_reason == "target test file modified — disqualified"
    assert res.tamper_files == (pr.TEST_SUBTRACT, "conftest.py")


def test_env_poison_control_transform_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """The exact negative-control edit that escaped 3/7 on click: an identity source
    tree plus a root conftest.py that execs the GOLD module at collection time. The
    controls vocabulary already accepts ``disqualified`` for env_poison, so the
    control's verdict becomes ``ok`` (caught) — never ``ESCAPE`` — from here on."""
    gold_src = trial.repo.show_file(trial.sha, pr.SRC) or ""
    assert "def subtract" in gold_src
    conftest = nc.env_poison_conftest(nc.module_name_for(pr.SRC, pyrepo.config), pr.SRC, gold_src)
    (trial.root / "conftest.py").write_text(conftest, encoding="utf-8")
    assert trial.read(pr.SRC) == pr.SRC_INITIAL  # the graded source is untouched

    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res, "conftest.py")
    assert nc.observe(res) == nc.OBS_DISQUALIFIED
    assert nc.OBS_DISQUALIFIED in nc.EXPECTED[nc.ENV_POISON]


def test_builder_authored_gitignore_cannot_hide_a_conftest(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """Ignoring the poison with a new .gitignore rule keeps it out of ``ls-files``;
    touched_files pierces builder-authored ignore rules, so belt 1 still sees it."""
    pr.apply_gold(trial)
    pr.write_files(trial, [(".gitignore", "conftest.py\n"), ("conftest.py", "# hidden\n")])
    assert (
        "conftest.py"
        not in trial.repo.run("ls-files", "--others", "--exclude-standard", cwd=trial.root).lines
    )
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res, "conftest.py")


# ---------------------------------------------------------------------------
# The builder cannot move the ground: the three false-pass paths of the independent
# review pass (2026-09-14, finding 1), each an identity source edit + a hidden poison
# conftest.py, must all disqualify — and the honest paths must still grade clean.
# ---------------------------------------------------------------------------

_POISON = 'import calc as _m\nexec("def subtract(a, b):\\n    return a - b\\n", _m.__dict__)\n'
_WT_DQ = "worktree integrity"


def _identity_edit(ws: Workspace) -> None:
    """A source change that changes nothing (belt 4 holds; the poison does the work)."""
    with (ws.root / pr.SRC).open("a", encoding="utf-8") as fh:
        fh.write("# touched\n")


def _assert_worktree_dq(res: g.GradeResult, *files: str) -> None:
    assert res.disqualified is True and res.clean is False
    assert res.belts.tests_unmodified is False and res.belts.target_green is None
    assert res.target_run is None and res.belt_run is None
    assert res.dq_reason.startswith(_WT_DQ), res.dq_reason
    assert res.tamper_files == tuple(files)
    with pytest.raises(g.FalseQ1Violation):
        g.GradeResult(res.task_id, res.repo, res.mode, clean=True, belts=res.belts)


def test_poison_hidden_in_info_exclude_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """Finding 1(a): ``echo conftest.py >> $(git rev-parse --git-path info/exclude)``
    graded CLEAN on 842875b. The pre-flight removes the line and disqualifies; and
    the poison is a touched file whatever the exclude file says."""
    (trial.root / "conftest.py").write_text(_POISON, encoding="utf-8")
    _identity_edit(trial)
    exclude = pyrepo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as fh:
        fh.write("conftest.py\n")
    events, on_event = _collector()
    res = _grade(trial, feat_task, pyrepo, runner, executor, on_event=on_event)
    _assert_worktree_dq(res, ".git/info/exclude")
    assert "info/exclude" in res.dq_reason
    assert "conftest.py" not in exclude.read_text(encoding="utf-8")  # restored
    tamper = [p for a, p in events if a == "grade.tamper"]
    assert tamper[0]["kind"] == "worktree" and tamper[0]["files"] == [".git/info/exclude"]
    assert tamper[0]["violations"][0]["kind"] == "exclude_edited"
    # a second grade of the same worktree: the exclude file is clean now, so the
    # poison itself is what disqualifies (belt 1b) — never a pass
    res2 = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_infra_dq(res2, "conftest.py")


def test_poison_hidden_in_info_exclude_is_disqualified_on_a_bound_worktree(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    """The CLI's ``crb grade`` binds a Workspace to a worktree it did not create (no
    exclude baseline to restore). The poison is still a touched file: belt 1b."""
    created = pyrepo.trial(tmp_path / "wt")
    try:
        (created.root / "conftest.py").write_text(_POISON, encoding="utf-8")
        _identity_edit(created)
        with (pyrepo.path / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
            fh.write("conftest.py\n")
        bound = Workspace(pyrepo.repo, created.root, sha=pyrepo.feat_sha, parent=pyrepo.initial_sha)
        res = _grade(bound, feat_task, pyrepo, runner, executor)
        _assert_infra_dq(res, "conftest.py")
    finally:
        created.remove()


def test_poison_committed_inside_the_worktree_is_disqualified(
    trial: Workspace,
    feat_task: TaskSpec,
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
) -> None:
    """Finding 1(b): ``git add conftest.py && git commit`` moved HEAD; ``grade()``
    (the ``run_task`` path, which had no HEAD check) returned CLEAN on 842875b."""
    (trial.root / "conftest.py").write_text(_POISON, encoding="utf-8")
    _identity_edit(trial)
    pr.git(trial.root, "add", "-f", "conftest.py")
    pr.git(trial.root, "commit", "-q", "-m", "hide the poison")
    assert "conftest.py" not in trial.repo.run("diff", "--name-only", "HEAD", cwd=trial.root).lines
    res = _grade(trial, feat_task, pyrepo, runner, executor)
    _assert_worktree_dq(res, ".git/HEAD")
    assert "is not the parent" in res.dq_reason


def test_poison_flagged_skip_worktree_is_disqualified(
    pyrepo: pr.PyRepo, executor: LocalExecutor, tmp_path: Path
) -> None:
    """Finding 1(c): a repo whose parent TRACKS an (empty) conftest.py; the builder
    poisons it and sets ``--skip-worktree`` / ``--assume-unchanged`` so ``git diff``
    never lists it. CLEAN on 842875b (HEAD unchanged, so the CLI's check did not help)."""
    (pyrepo.path / "conftest.py").write_text("", encoding="utf-8")
    pr.git(pyrepo.path, "add", "-A")
    pr.git(pyrepo.path, "commit", "-q", "-m", "chore: empty conftest")
    sha = _commit_multiply(pyrepo)
    task = pyrepo.feat_task(
        task_id=sha,
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[pr.TEST_MULTIPLY],
    )
    runner = PytestRunner(pyrepo.config)
    poison = 'import calc as _m\nexec("def multiply(a, b):\\n    return a * b\\n", _m.__dict__)\n'
    for flag, undo in (
        ("--skip-worktree", "--no-skip-worktree"),
        ("--assume-unchanged", "--no-assume-unchanged"),
    ):
        ws = Workspace.create(pyrepo.repo, sha, tmp_path / flag.strip("-"), config=pyrepo.config)
        try:
            ws.overlay_tests([pr.TEST_MULTIPLY])
            (ws.root / "conftest.py").write_text(poison, encoding="utf-8")
            _identity_edit(ws)
            ws.repo.run("update-index", flag, "conftest.py", cwd=ws.root, check=True)
            assert (
                "conftest.py" not in ws.repo.run("diff", "--name-only", "HEAD", cwd=ws.root).lines
            )
            res = g.grade(ws, task, config=pyrepo.config, runner=runner, executor=executor)
            _assert_worktree_dq(res, "conftest.py")
            assert "skip-worktree / assume-unchanged" in res.dq_reason
            # the flag alone, on an honest file, is still a DQ: the ground moved
            ws.repo.run("update-index", undo, "conftest.py", cwd=ws.root, check=True)
            res = g.grade(ws, task, config=pyrepo.config, runner=runner, executor=executor)
            _assert_infra_dq(res, "conftest.py")  # the poison, seen by belt 1b
        finally:
            ws.remove()


def test_gold_still_grades_clean_with_a_tracked_conftest_at_the_parent(
    pyrepo: pr.PyRepo, executor: LocalExecutor, tmp_path: Path
) -> None:
    """The honest counterpart of 1(c): an untouched tracked conftest.py is not a change."""
    (pyrepo.path / "conftest.py").write_text("# repo's own\n", encoding="utf-8")
    pr.git(pyrepo.path, "add", "-A")
    pr.git(pyrepo.path, "commit", "-q", "-m", "chore: conftest")
    sha = _commit_multiply(pyrepo)
    task = pyrepo.feat_task(
        task_id=sha,
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[pr.TEST_MULTIPLY],
    )
    ws = Workspace.create(pyrepo.repo, sha, tmp_path / "gold", config=pyrepo.config)
    try:
        ws.overlay_tests([pr.TEST_MULTIPLY])
        ws.overlay_sources([pr.SRC])
        res = g.grade(
            ws, task, config=pyrepo.config, runner=PytestRunner(pyrepo.config), executor=executor
        )
        assert res.clean is True and res.changed_files == (pr.SRC,)
    finally:
        ws.remove()


def _commit_multiply(pyrepo: pr.PyRepo) -> str:
    (pyrepo.path / pr.SRC).write_text(
        pr.SRC_FEAT + "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    (pyrepo.path / pr.TEST_MULTIPLY).write_text(pr.TEST_MULTIPLY_SRC, encoding="utf-8")
    pr.git(pyrepo.path, "add", "-A")
    pr.git(pyrepo.path, "commit", "-q", "-m", "feat: add multiply")
    return pr.git(pyrepo.path, "rev-parse", "HEAD")


def test_harness_written_conftest_is_not_a_builder_change_until_edited(
    pyrepo: pr.PyRepo, feat_task: TaskSpec, executor: LocalExecutor, tmp_path: Path
) -> None:
    """A post_create hook that writes conftest.py is the operator's fixup, not the
    builder's edit: gold grades clean. The builder editing that file IS tamper."""
    cfg = pr.default_config(
        runner_opts={
            **pyrepo.config.runner_opts,
            "post_create": [{"write_if_missing": {"path": "conftest.py", "content": "# op\n"}}],
        }
    )
    runner = PytestRunner(cfg)
    ws = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=cfg)
    try:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        pr.apply_gold(ws)
        res = g.grade(ws, feat_task, config=cfg, runner=runner, executor=executor)
        assert res.clean is True and res.changed_files == (pr.SRC,)
        (ws.root / "conftest.py").write_text("# op\nimport calc\n", encoding="utf-8")
        res = g.grade(ws, feat_task, config=cfg, runner=runner, executor=executor)
        _assert_infra_dq(res, "conftest.py")
    finally:
        ws.remove()


def _commit_pyproject_and_multiply(pyrepo: pr.PyRepo) -> str:
    """Two extra commits: ``pyproject.toml`` (no pytest config), then ``multiply`` +
    its test — a task whose PARENT carries a pyproject.toml the builder may edit."""
    pyrepo.add_pyproject_commit()
    (pyrepo.path / pr.SRC).write_text(
        pr.SRC_FEAT + "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    (pyrepo.path / pr.TEST_MULTIPLY).write_text(pr.TEST_MULTIPLY_SRC, encoding="utf-8")
    pr.git(pyrepo.path, "add", "-A")
    pr.git(pyrepo.path, "commit", "-q", "-m", "feat: add multiply")
    return pr.git(pyrepo.path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("edit", "tamper"),
    [
        (lambda t: t.replace('version = "0.1.0"', 'version = "0.2.0"'), False),
        (lambda t: t.replace('test = ["pytest"]', 'test = ["pytest", "rich"]'), False),
        (lambda t: t + '\n[tool.pytest.ini_options]\naddopts = "-p no:x"\n', True),
        (lambda t: t + '\n[project.entry-points.pytest11]\nshim = "shim"\n', True),
    ],
    ids=["version-bump", "extra-add", "pytest-table", "plugin-entry-point"],
)
def test_pyproject_edit_is_tamper_only_when_pytest_sections_change(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    edit: Callable[[str], str],
    tamper: bool,
) -> None:
    sha = _commit_pyproject_and_multiply(pyrepo)
    task = pyrepo.feat_task(
        task_id=sha,
        subject="feat: add multiply",
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[pr.TEST_MULTIPLY],
    )
    ws = Workspace.create(pyrepo.repo, sha, tmp_path / "ws", config=pyrepo.config)
    try:
        ws.overlay_tests([pr.TEST_MULTIPLY])
        ws.overlay_sources([pr.SRC])  # gold
        p = ws.root / pr.PYPROJECT
        p.write_text(edit(p.read_text(encoding="utf-8")), encoding="utf-8")
        res = _grade(ws, task, pyrepo, runner, executor)
        if tamper:
            _assert_infra_dq(res, pr.PYPROJECT)
        else:
            assert res.clean is True, res.to_dict()
            assert res.belts == _ALL_TRUE
            assert res.changed_files == (pr.PYPROJECT, pr.SRC)
    finally:
        ws.remove()


def test_blind_root_conftest_pre_overlay_is_disqualified(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    """Blind mode: the infra check runs alongside belt 0, before the oracle lands."""
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_gold(ws)
        pr.write_files(ws, [("conftest.py", "# x\n")])
        events, on_event = _collector()
        res = _grade(ws, feat_task, pyrepo, runner, executor, mode=g.MODE_BLIND, on_event=on_event)
        _assert_infra_dq(res, "conftest.py")
        assert res.mode == g.MODE_BLIND
        assert events == [
            (
                "grade.tamper",
                {"task": feat_task.task_id, "files": ["conftest.py"], "kind": "test_infra"},
            )
        ]
        assert not ws.exists(pr.TEST_SUBTRACT)  # oracle never landed
    finally:
        ws.remove()


def test_blind_test_file_and_infra_both_touched_reports_both(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_test_only(ws, "tests/test_sneaky.py")
        pr.write_files(ws, [("conftest.py", "# x\n")])
        res = _grade(ws, feat_task, pyrepo, runner, executor, mode=g.MODE_BLIND)
        assert res.disqualified and res.dq_reason.startswith("blind:")
        assert res.tamper_files == ("conftest.py", "tests/test_sneaky.py")
    finally:
        ws.remove()


# --- the other languages: belt 1b needs no toolchain (it fires before any run);
#     the "honest edit proceeds" half runs the real runner where the tool is on PATH.


def _lang_task(feat_sha: str, config: RepoConfig, test_file: str, src: str) -> TaskSpec:
    r = get_runner(config)
    target = r.target_scope([test_file])
    return TaskSpec(
        task_id=feat_sha,
        repo=config.name,
        subject="feat: add sub",
        authored="2026-01-01T00:00:00+00:00",
        test_files=(test_file,),
        src_files=(src,),
        target_tests=target,
        belt_scope=r.belt_scope(target, [test_file]),
        language=config.language.value,
        red_checked=True,
    )


def _lang_trial(
    tmp_path: Path, repo_path: Path, feat_sha: str, config: RepoConfig, test_file: str, src: str
) -> Workspace:
    ws = Workspace.create(GitRepo(repo_path), feat_sha, tmp_path / "trial", config=config)
    ws.overlay_tests([test_file])
    ws.overlay_sources([src])  # gold: every other belt would hold
    return ws


def _grade_lang(
    ws: Workspace, task: TaskSpec, config: RepoConfig, executor: LocalExecutor
) -> g.GradeResult:
    return g.grade(ws, task, config=config, runner=get_runner(config), executor=executor)


@pytest.mark.parametrize(
    ("tool", "rel", "content"),
    [
        ("jest", "jest.config.js", "module.exports = { setupFiles: ['./shim.js'] };\n"),
        ("jest", "src/__snapshots__/x.snap", "exports[`x`] = `1`;\n"),
        ("mocha", ".mocharc.yml", "require: ./shim.js\n"),
        ("vitest", "vite.config.ts", "export default { test: { setupFiles: ['./shim.ts'] } };\n"),
        ("node", "node.config.json", '{"testRunner": {}}\n'),
    ],
)
def test_javascript_new_test_config_is_disqualified(
    tmp_path: Path, executor: LocalExecutor, tool: str, rel: str, content: str
) -> None:
    noderepo = langs.fixture_module("noderepo")
    root, sha = noderepo.build(tmp_path, tool)
    cfg = noderepo.config(tool)
    test_file, src = noderepo.test_sub(tool), noderepo.SRC_SUB
    ws = _lang_trial(tmp_path, root, sha, cfg, test_file, src)
    try:
        pr.write_files(ws, [(rel, content)])
        res = _grade_lang(ws, _lang_task(sha, cfg, test_file, src), cfg, executor)
        _assert_infra_dq(res, rel)
    finally:
        ws.remove()


def test_javascript_package_json_test_script_is_disqualified_dependency_is_not(
    tmp_path: Path, executor: LocalExecutor
) -> None:
    noderepo = langs.fixture_module("noderepo")
    root, sha = noderepo.build(tmp_path, "node")
    cfg = noderepo.config("node")
    test_file, src = noderepo.test_sub("node"), noderepo.SRC_SUB
    task = _lang_task(sha, cfg, test_file, src)
    ws = _lang_trial(tmp_path, root, sha, cfg, test_file, src)
    try:
        p = ws.root / "package.json"
        original = p.read_text(encoding="utf-8")
        p.write_text(original.replace('"node --test"', '"true"'), encoding="utf-8")
        _assert_infra_dq(_grade_lang(ws, task, cfg, executor), "package.json")
        honest = original.replace('"private": true', '"private": true,\n  "dependencies": {}')
        p.write_text(honest, encoding="utf-8")
        res = _grade_lang(ws, task, cfg, executor)
        assert res.belts.tests_unmodified is True and not res.disqualified
        if langs.has_tool("node"):
            assert res.clean is True, res.to_dict()
            assert set(res.changed_files) == {"package.json", src}
    finally:
        ws.remove()


_GO_TESTMAIN = (
    'package calc\n\nimport (\n\t"os"\n\t"testing"\n)\n\n'
    "func TestMain(m *testing.M) { os.Exit(0) }\n"
)


@pytest.mark.parametrize(
    ("rel", "edit"),
    [
        ("go.mod", lambda t: t + "\nreplace example.com/other => ../shim\n"),
        ("calc/testdata/golden.txt", lambda t: "3\n"),
        ("calc/helper_test.go", lambda t: _GO_TESTMAIN),
    ],
    ids=["go.mod-replace", "testdata", "sibling-TestMain"],
)
def test_go_infra_edit_is_disqualified(
    tmp_path: Path, executor: LocalExecutor, rel: str, edit: Callable[[str], str]
) -> None:
    gorepo = langs.fixture_module("gorepo")
    root, sha = gorepo.build(tmp_path)
    cfg = gorepo.config()
    ws = _lang_trial(tmp_path, root, sha, cfg, gorepo.TEST_SUB, gorepo.SRC_SUB)
    try:
        before = ws.read(rel) if ws.exists(rel) else ""
        pr.write_files(ws, [(rel, edit(before))])
        res = _grade_lang(ws, _lang_task(sha, cfg, gorepo.TEST_SUB, gorepo.SRC_SUB), cfg, executor)
        _assert_infra_dq(res, rel)
    finally:
        ws.remove()


@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
@pytest.mark.toolchain("go")
def test_go_honest_go_mod_edit_proceeds_to_a_clean_grade(
    tmp_path: Path, executor: LocalExecutor
) -> None:
    gorepo = langs.fixture_module("gorepo")
    root, sha = gorepo.build(tmp_path)
    cfg = gorepo.config()
    ws = _lang_trial(tmp_path, root, sha, cfg, gorepo.TEST_SUB, gorepo.SRC_SUB)
    try:
        (ws.root / "go.mod").write_text(ws.read("go.mod") + "\n// honest\n", encoding="utf-8")
        res = _grade_lang(ws, _lang_task(sha, cfg, gorepo.TEST_SUB, gorepo.SRC_SUB), cfg, executor)
        assert res.clean is True, res.to_dict()
        assert set(res.changed_files) == {"go.mod", gorepo.SRC_SUB}
    finally:
        ws.remove()


@pytest.mark.parametrize(
    ("rel", "edit"),
    [
        (
            "src/test/resources/junit-platform.properties",
            lambda t: "junit.jupiter.extensions.autodetection.enabled=true\n",
        ),
        ("mvnw", lambda t: "#!/bin/sh\nexit 0\n"),
        (".mvn/maven.config", lambda t: "-DskipTests\n"),
        (
            "pom.xml",
            lambda t: t.replace("</properties>", "<skipTests>true</skipTests></properties>"),
        ),
    ],
    ids=["test-resource", "mvnw", "maven.config", "pom-properties"],
)
def test_jvm_infra_edit_is_disqualified(
    tmp_path: Path, executor: LocalExecutor, rel: str, edit: Callable[[str], str]
) -> None:
    jvmrepo = langs.fixture_module("jvmrepo")
    root, sha = jvmrepo.build(tmp_path)
    cfg = jvmrepo.config()
    ws = _lang_trial(tmp_path, root, sha, cfg, jvmrepo.TEST_SUB, jvmrepo.SRC_SUB)
    try:
        before = ws.read(rel) if ws.exists(rel) else ""
        pr.write_files(ws, [(rel, edit(before))])
        res = _grade_lang(
            ws, _lang_task(sha, cfg, jvmrepo.TEST_SUB, jvmrepo.SRC_SUB), cfg, executor
        )
        _assert_infra_dq(res, rel)
    finally:
        ws.remove()


@pytest.mark.skipif(not langs.has_tool("mvn"), reason="mvn not on PATH")
@pytest.mark.toolchain("mvn")
def test_jvm_honest_pom_version_bump_proceeds_to_a_clean_grade(
    tmp_path: Path, executor: LocalExecutor
) -> None:
    langs.maven_warmup(tmp_path)
    jvmrepo = langs.fixture_module("jvmrepo")
    root, sha = jvmrepo.build(tmp_path)
    cfg = jvmrepo.config(offline=True)
    ws = _lang_trial(tmp_path, root, sha, cfg, jvmrepo.TEST_SUB, jvmrepo.SRC_SUB)
    try:
        pom = ws.read("pom.xml")
        assert "<version>0.1.0</version>" in pom
        (ws.root / "pom.xml").write_text(
            pom.replace("<version>0.1.0</version>", "<version>0.2.0</version>"), encoding="utf-8"
        )
        res = _grade_lang(
            ws, _lang_task(sha, cfg, jvmrepo.TEST_SUB, jvmrepo.SRC_SUB), cfg, executor
        )
        assert res.belts.tests_unmodified is True and not res.disqualified
        assert res.clean is True, res.to_dict()
    finally:
        ws.remove()


@pytest.mark.skipif(not langs.has_tool("cargo"), reason="cargo not on PATH")
@pytest.mark.toolchain("cargo")
@pytest.mark.parametrize(
    ("rel", "edit", "tamper"),
    [
        ("build.rs", lambda t: 'fn main() { println!("cargo:rustc-cfg=shim"); }\n', True),
        ("Cargo.toml", lambda t: t + '\n[[test]]\nname = "sub"\nharness = false\n', True),
        ("tests/common/mod.rs", lambda t: "pub fn shim() {}\n", True),
        ("Cargo.toml", lambda t: t.replace('version = "0.1.0"', 'version = "0.2.0"'), False),
    ],
    ids=["build.rs", "cargo-[[test]]", "tests-helper", "honest-version-bump"],
)
def test_rust_infra_edit_is_disqualified_honest_version_bump_is_clean(
    tmp_path: Path,
    executor: LocalExecutor,
    rel: str,
    edit: Callable[[str], str],
    tamper: bool,
) -> None:
    rustrepo = langs.fixture_module("rustrepo")
    root, sha = rustrepo.build(tmp_path)
    cfg = rustrepo.config()
    ws = _lang_trial(tmp_path, root, sha, cfg, rustrepo.TEST_SUB, rustrepo.SRC_SUB)
    try:
        ws.overlay_sources([rustrepo.SRC_LIB])  # the feat also edits lib.rs (pub mod sub)
        before = ws.read(rel) if ws.exists(rel) else ""
        pr.write_files(ws, [(rel, edit(before))])
        task = _lang_task(sha, cfg, rustrepo.TEST_SUB, rustrepo.SRC_SUB)
        res = _grade_lang(ws, task, cfg, executor)
        if tamper:
            _assert_infra_dq(res, rel)
        else:
            assert res.clean is True, res.to_dict()
            assert "Cargo.toml" in res.changed_files
    finally:
        ws.remove()
