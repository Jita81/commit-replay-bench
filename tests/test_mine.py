"""crb.core.mine — candidate discovery, RED-check, baseline, gold on the fixture repo."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from crb.core import mine as m
from crb.core.execution import LocalExecutor
from crb.core.runners import base as rb
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import POOL_HARD, POOL_STANDARD, Language, RepoConfig
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

Events = list[tuple[str, dict[str, Any]]]


def _collector() -> tuple[Events, Callable[[str, Any], None]]:
    events: Events = []

    def on_event(action: str, payload: Any) -> None:
        events.append((action, dict(payload)))

    return events, on_event


# ---------------------------------------------------------------------------
# pool caps + candidate discovery
# ---------------------------------------------------------------------------


def test_pool_caps() -> None:
    py = RepoConfig(name="p", language=Language.PYTHON)
    jvm = RepoConfig(name="j", language=Language.JVM)
    assert m.pool_caps(py, POOL_STANDARD) == m.PoolCaps(1, 3, 6)
    assert m.pool_caps(jvm, POOL_STANDARD) == m.PoolCaps(1, 6, 8)
    assert m.pool_caps(py, POOL_HARD) == m.PoolCaps(4, 8, 14)
    with pytest.raises(ValueError, match="unknown pool"):
        m.pool_caps(py, "easy")


def test_iter_candidates_finds_the_feat_commit_and_not_the_docs_commit(pyrepo: pr.PyRepo) -> None:
    cands = {c.sha: c for c in m.iter_candidates(pyrepo.repo, pyrepo.config)}
    assert pyrepo.feat_sha in cands
    assert pyrepo.docs_sha not in cands  # README only: no source, no test
    feat = cands[pyrepo.feat_sha]
    assert feat.src_files == (pr.SRC,)
    assert feat.test_files == (pr.TEST_SUBTRACT,)
    assert feat.files == (pr.SRC, pr.TEST_SUBTRACT)


def test_root_commit_is_not_a_candidate(pyrepo: pr.PyRepo) -> None:
    shas = [c.sha for c in m.iter_candidates(pyrepo.repo, pyrepo.config)]
    assert pyrepo.initial_sha not in shas


def test_iter_candidates_respects_skip_log_n_and_ref(pyrepo: pr.PyRepo) -> None:
    repo, cfg = pyrepo.repo, pyrepo.config
    assert pyrepo.feat_sha not in [
        c.sha for c in m.iter_candidates(repo, cfg, skip=frozenset({pyrepo.feat_sha}))
    ]
    assert [c.sha for c in m.iter_candidates(repo, cfg, log_n=1)] == []  # only docs examined
    assert [c.sha for c in m.iter_candidates(repo, cfg, log_n=2)] == [pyrepo.feat_sha]
    assert [c.sha for c in m.iter_candidates(repo, cfg, log_n=1, ref=pyrepo.feat_sha)] == [
        pyrepo.feat_sha
    ]


def test_iter_candidates_uses_mining_log_n_from_config(pyrepo: pr.PyRepo) -> None:
    cfg = pr.default_config(mining={"log_n": 1})
    assert list(m.iter_candidates(pyrepo.repo, cfg)) == []


def test_iter_candidates_hard_pool_excludes_single_file_commits(pyrepo: pr.PyRepo) -> None:
    # hard pool needs 4..8 source files; the feat commit has 1
    assert list(m.iter_candidates(pyrepo.repo, pyrepo.config, pool=POOL_HARD)) == []


# ---------------------------------------------------------------------------
# qualify: RED → baseline → gold
# ---------------------------------------------------------------------------


def _feat_candidate(pyrepo: pr.PyRepo) -> m.Candidate:
    return next(
        c for c in m.iter_candidates(pyrepo.repo, pyrepo.config) if c.sha == pyrepo.feat_sha
    )


def test_qualify_produces_a_gold_clean_task(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    events, on_event = _collector()
    scratch = tmp_path / "scratch"
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        _feat_candidate(pyrepo),
        runner=runner,
        executor=executor,
        scratch=scratch,
        on_event=on_event,
    )
    assert out.skipped_reason == ""
    assert out.duration_s > 0
    task = out.task
    assert task is not None
    assert task.task_id == pyrepo.feat_sha
    assert task.repo == pr.REPO_NAME
    assert task.subject == "feat: add subtract"
    assert task.language == "python"
    assert task.test_files == (pr.TEST_SUBTRACT,)
    assert task.src_files == (pr.SRC,)
    assert task.target_tests == (pr.TEST_SUBTRACT,)
    assert task.belt_scope == ("tests/",)  # AFFECTED_DIRS
    assert task.red_checked is True
    assert task.baseline_failing == (pr.TEST_SUBTRACT,)  # collection error at the parent
    assert task.src_churn == pr.FEAT_SRC_CHURN
    assert task.size == "XS"
    assert task.capability_class == "bug.fix"
    assert task.gold_clean is True
    assert task.gold_note == ""
    assert task.labels == {}
    # the hand-built task the grade tests use is exactly what the miner measures
    assert task == pyrepo.feat_task()
    # the mining worktree is gone
    assert not (scratch / f"mine-{pr.REPO_NAME}-{pyrepo.feat_sha[:10]}").exists()
    kinds = [k for k, _ in events]
    assert kinds == ["mine.candidate", "mine.red", "mine.gold"]
    assert events[1][1] == {
        "sha": pyrepo.feat_sha,
        "size": "XS",
        "cls": "bug.fix",
        "baseline_failing": 1,
    }
    assert events[2][1]["clean"] is True


def test_qualify_without_gold_leaves_gold_clean_unset(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        _feat_candidate(pyrepo),
        runner=runner,
        executor=executor,
        scratch=tmp_path,
        gold=False,
    )
    assert out.task is not None
    assert out.task.gold_clean is None
    assert out.task.red_checked is True


def test_qualify_skips_when_target_is_green_at_parent(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    sha = pyrepo.add_green_commit()
    cand = next(c for c in m.iter_candidates(pyrepo.repo, pyrepo.config) if c.sha == sha)
    assert cand.test_files == (pr.TEST_CALC,)
    events, on_event = _collector()
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        cand,
        runner=runner,
        executor=executor,
        scratch=tmp_path,
        on_event=on_event,
    )
    assert out.task is None
    assert out.skipped_reason == "target green at parent"
    assert events[-1][0] == "mine.skip"
    assert "not RED" in events[-1][1]["reason"]


def test_qualify_skips_on_target_timeout(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "run",
        lambda *a, **k: rb.TestRun(124, frozenset(), "…", timed_out=True, duration_s=1.0),
    )
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        _feat_candidate(pyrepo),
        runner=runner,
        executor=executor,
        scratch=tmp_path,
    )
    assert out.task is None
    assert out.skipped_reason == "target timeout at parent"


def test_qualify_skips_on_baseline_timeout(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run = runner.run
    calls: list[tuple[str, ...]] = []

    def run(ex: Any, root: Path, scope: Any, *, timeout: int = 0) -> rb.TestRun:
        calls.append(tuple(scope))
        if len(calls) == 1:
            return real_run(ex, root, scope, timeout=timeout)  # the real RED check
        return rb.TestRun(124, frozenset(), "", timed_out=True)

    monkeypatch.setattr(runner, "run", run)
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        _feat_candidate(pyrepo),
        runner=runner,
        executor=executor,
        scratch=tmp_path,
    )
    assert out.task is None
    assert out.skipped_reason == "baseline timeout"
    assert calls == [(pr.TEST_SUBTRACT,), ("tests/",)]


def test_qualify_records_baseline_parse_error_as_label(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run = runner.run
    n = 0

    def run(ex: Any, root: Path, scope: Any, *, timeout: int = 0) -> rb.TestRun:
        nonlocal n
        n += 1
        if n == 2:  # the baseline belt run: rc≠0 with no attributable ids
            return rb.TestRun(1, frozenset(), "crash", parse_error="unattributed failure (rc=1)")
        return real_run(ex, root, scope, timeout=timeout)

    monkeypatch.setattr(runner, "run", run)
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        _feat_candidate(pyrepo),
        runner=runner,
        executor=executor,
        scratch=tmp_path,
        gold=False,
    )
    assert out.task is not None
    assert out.task.baseline_failing == ()
    assert out.task.labels["baseline_parse_error"].startswith("unattributed")


# ---------------------------------------------------------------------------
# gold_check
# ---------------------------------------------------------------------------


def test_gold_check_false_when_gold_breaks_the_belt(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    sha = pyrepo.add_bad_gold_commit()
    cand = next(c for c in m.iter_candidates(pyrepo.repo, pyrepo.config) if c.sha == sha)
    assert cand.test_files == (pr.TEST_MULTIPLY,)
    events, on_event = _collector()
    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        cand,
        runner=runner,
        executor=executor,
        scratch=tmp_path,
        on_event=on_event,
    )
    task = out.task
    assert task is not None  # kept, but flagged
    assert task.red_checked is True
    assert task.baseline_failing == (pr.TEST_MULTIPLY,)
    assert task.gold_clean is False
    assert task.gold_note == "gold introduced 2 belt failure(s)"
    gold_events = [p for k, p in events if k == "mine.gold"]
    assert gold_events == [{"sha": sha, "clean": False, "note": task.gold_note}]


def test_gold_check_false_when_gold_target_not_green(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=pyrepo.config)
    try:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        monkeypatch.setattr(runner, "run", lambda *a, **k: rb.TestRun(1, frozenset({"x"}), ""))
        task = m.gold_check(ws, pyrepo.feat_task(gold_clean=None), runner=runner, executor=executor)
        assert task.gold_clean is False
        assert task.gold_note == "gold target not green (rc=1)"
        monkeypatch.setattr(
            runner, "run", lambda *a, **k: rb.TestRun(124, frozenset(), "", timed_out=True)
        )
        task = m.gold_check(ws, pyrepo.feat_task(gold_clean=None), runner=runner, executor=executor)
        assert task.gold_note == "gold target timed out"
    finally:
        ws.remove()


def test_gold_check_false_when_belt_times_out_or_is_unattributed(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=pyrepo.config)
    try:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        runs = iter([rb.TestRun(0, frozenset()), rb.TestRun(124, frozenset(), "", timed_out=True)])
        monkeypatch.setattr(runner, "run", lambda *a, **k: next(runs))
        task = m.gold_check(ws, pyrepo.feat_task(gold_clean=None), runner=runner, executor=executor)
        assert task.gold_clean is False and task.gold_note == "gold belt timed out"

        runs = iter(
            [
                rb.TestRun(0, frozenset()),
                rb.TestRun(1, frozenset(), "", parse_error="compile error"),
            ]
        )
        task = m.gold_check(ws, pyrepo.feat_task(gold_clean=None), runner=runner, executor=executor)
        assert (
            task.gold_clean is False and task.gold_note == "gold belt unattributed: compile error"
        )
    finally:
        ws.remove()


def test_gold_check_never_credits_on_harness_error(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=pyrepo.config)
    try:

        def boom(*a: Any, **k: Any) -> rb.TestRun:
            raise RuntimeError("runner exploded")

        monkeypatch.setattr(runner, "run", boom)
        events, on_event = _collector()
        task = m.gold_check(
            ws,
            pyrepo.feat_task(gold_clean=None),
            runner=runner,
            executor=executor,
            on_event=on_event,
        )
        assert task.gold_clean is False
        assert task.gold_note == "gold error: RuntimeError: runner exploded"
        assert events == [
            ("mine.gold", {"sha": pyrepo.feat_sha, "clean": False, "note": task.gold_note})
        ]
    finally:
        ws.remove()


# ---------------------------------------------------------------------------
# mine(): the loop
# ---------------------------------------------------------------------------


def test_mine_stops_at_target_count(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    events, on_event = _collector()
    outcomes = list(
        m.mine(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=executor,
            scratch=tmp_path,
            target_count=1,
            on_event=on_event,
        )
    )
    assert [o.sha for o in outcomes] == [pyrepo.feat_sha]
    assert outcomes[0].task is not None and outcomes[0].task.gold_clean is True
    assert events[-1] == (
        "mine.done",
        {"repo": pr.REPO_NAME, "pool": POOL_STANDARD, "found": 1, "examined": 1},
    )


def test_mine_honours_known_and_max_candidates(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    # everything known → nothing examined
    outcomes = list(
        m.mine(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=executor,
            scratch=tmp_path,
            known=frozenset({pyrepo.feat_sha, pyrepo.initial_sha}),
        )
    )
    assert outcomes == []
    # max_candidates=0 falls back to config mining.max_candidates
    cfg = pr.default_config(mining={"max_candidates": 1, "target_valid": 5})
    events, on_event = _collector()
    outcomes = list(
        m.mine(
            pyrepo.repo,
            cfg,
            runner=runner,
            executor=executor,
            scratch=tmp_path,
            gold=False,
            on_event=on_event,
        )
    )
    assert len(outcomes) == 1
    assert events[-1][1]["examined"] == 1


def test_mine_continues_past_a_skipped_candidate(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    """The newest candidate is green-at-parent (skipped); the feat commit still qualifies."""
    green = pyrepo.add_green_commit()
    events, on_event = _collector()
    outcomes = list(
        m.mine(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=executor,
            scratch=tmp_path,
            target_count=1,
            gold=False,
            on_event=on_event,
        )
    )
    assert [(o.sha, o.task is not None, o.skipped_reason) for o in outcomes] == [
        (green, False, "target green at parent"),
        (pyrepo.feat_sha, True, ""),
    ]
    assert events[-1][1] == {"repo": pr.REPO_NAME, "pool": POOL_STANDARD, "found": 1, "examined": 2}


def test_mine_outcome_dataclass_defaults() -> None:
    o = m.MineOutcome("abc", None)
    assert o.skipped_reason == "" and o.duration_s == 0.0
