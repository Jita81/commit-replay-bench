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
from crb.core.runners import base as rb
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

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
    }
    assert g.Belts.from_dict(d) == g.Belts(True, False, None, True)
    assert g.Belts.from_dict({}) == g.Belts()


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
    assert all(d[b] is True for b in g.BELT_NAMES)
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
    ws = pyrepo.trial(tmp_path / "ws", overlay_tests=False)
    try:
        pr.apply_test_only(ws)
        res = _grade(ws, pyrepo.green_task(), pyrepo, runner, executor)
        assert res.belts.source_changed is False
        assert res.clean is False
        assert res.changed_files == ()
        assert res.diff is not None and res.diff.files == ()  # untracked test file: no diff
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
    assert belts == [(b, True) for b in g.BELT_NAMES]
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
