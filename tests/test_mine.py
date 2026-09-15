"""crb.core.mine — candidate discovery, RED-check, baseline, gold on the fixture repo.

Navigation
----------
What it is:   The miner's test suite — candidate discovery, the RED check, the baseline and the
              gold check on the fixture repository.
What it does: Pins the pool caps, which commits are candidates (the feat commit, never the docs
              or root commit; the hard pool excludes single-file commits), that ``qualify`` skips
              a target that is green at the parent or times out, that a gold which breaks the
              belt, fails its target, times out or errors is never ``gold_clean``, that a
              declared linter's verdict reaches the gold check only after the core belts hold,
              that support files under the test layout are overlaid but never targets
              (mesh-client, DL-023) and that three consecutive harness-errored candidates stop
              the run instead of failing it. Toolchain cases pin gofmt / ruff on the gold.
How:          ``iter_candidates`` / ``qualify`` / ``mine`` on ``pyrepo`` through the real
              ``PytestRunner`` and ``LocalExecutor``; a fake lint script stands in for the
              repository's linter.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/mine.py (under test), tests/fixtures/pyrepo.py (the history and its
              opt-in green / bad-gold commits), src/crb/core/lint.py (the gold's belt 5),
              src/crb/core/spec.py (``POOL_*`` and ``RepoConfig``), tests/conftest.py
Tested by:    tests/test_mine.py
Touch when:   the candidate rule changes (what counts as coupled source + test, the pools); the
              gold check gains a belt; a new repository layout needs a support-file rule.
"""

from __future__ import annotations

import re
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from crb.core import mine as m
from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.lint import LintRun, LintStep
from crb.core.runners import base as rb
from crb.core.runners import get_runner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import POOL_HARD, POOL_STANDARD, Language, RepoConfig
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs  # type: ignore[no-redef]

_gorepo = langs.fixture_module("gorepo")
_pyrepo_min = langs.fixture_module("pyrepo_min")
_fx = langs.fixture_module("__init__")

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
    # the miner assigns the PATH axis only; the intent label is a later, separate step
    assert task.path_class == "bug.fix" and task.intent is None
    assert task.capability_class == "bug.fix" and task.class_source == "path"
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
    # no linter configured for the fixture: belt 5 was not evaluated on the gold
    assert events[2][1]["lint"] is None


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
    assert gold_events == [{"sha": sha, "clean": False, "note": task.gold_note, "lint": None}]


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
            (
                "mine.gold",
                {"sha": pyrepo.feat_sha, "clean": False, "note": task.gold_note, "lint": None},
            )
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


def test_mined_task_serialises_both_class_axes_and_survives_a_label(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> None:
    """What ``crb mine`` writes carries ``path_class`` + ``intent: null``; a later label
    (the ``label`` run / ``crb tasks label``) changes the resolved class and nothing the
    miner measured."""
    from crb.core.classify import IntentLabel
    from crb.core.spec import TaskSpec

    out = m.qualify(
        pyrepo.repo,
        pyrepo.config,
        _feat_candidate(pyrepo),
        runner=runner,
        executor=executor,
        scratch=tmp_path / "scratch",
    )
    assert out.task is not None
    d = out.task.to_dict()
    assert d["path_class"] == "bug.fix" and d["intent"] is None and d["class_source"] == "path"
    labelled = out.task.with_(intent=IntentLabel("feature.add", 0.9, "adds subtract", "m"))
    assert labelled.capability_class == "feature.add" and labelled.path_class == "bug.fix"
    unchanged = {
        k: v
        for k, v in labelled.to_dict().items()
        if k not in {"capability_class", "intent", "class_source"}
    }
    assert unchanged == {
        k: v for k, v in d.items() if k not in {"capability_class", "intent", "class_source"}
    }
    assert TaskSpec.from_dict(labelled.to_dict()) == labelled


# ---------------------------------------------------------------------------
# gold_check: belt 5 on the gold (ADR-0011 follow-up)
# ---------------------------------------------------------------------------
#
# The maintainers' own patch must pass the repository's own linter too. A gold that
# fails belt 5 is ``gold_clean=False`` with ``gold_note="gold fails belt 5 (<detected>): …"``
# so pre-existing lint debt is EXCLUDED from the denominator rather than counted against
# the builder. A linter that cannot run is a harness error (never a pass); no linter, or
# nothing lintable, leaves belt 5 not evaluated and the gold verdict unchanged.


def _lint_script(path: Path, body: str) -> Path:
    """An executable POSIX shell script standing in for a repository's linter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _qualify_with_lint(
    pyrepo: pr.PyRepo, lint: dict[str, Any], tmp_path: Path
) -> tuple[m.MineOutcome, Events]:
    cfg = pr.default_config(lint=lint)
    cand = next(c for c in m.iter_candidates(pyrepo.repo, cfg) if c.sha == pyrepo.feat_sha)
    events, on_event = _collector()
    out = m.qualify(
        pyrepo.repo,
        cfg,
        cand,
        runner=get_runner(cfg),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        on_event=on_event,
    )
    return out, events


def test_gold_check_declared_linter_rejecting_the_gold_marks_it_dirty(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A declared ``RepoConfig.lint`` that rejects the maintainers' own file: the task
    is kept, ``gold_clean=False``, and the note names belt 5 and the detected plan."""
    script = _lint_script(tmp_path / "bin" / "house-lint", 'echo "debt in $@"\nexit 1\n')
    out, events = _qualify_with_lint(pyrepo, {"command": [str(script)]}, tmp_path)
    task = out.task
    assert task is not None and task.red_checked is True
    assert task.gold_clean is False
    assert task.gold_note == "gold fails belt 5 (config): config rejected 1 changed file(s)"
    gold = [p for k, p in events if k == "mine.gold"]
    assert gold == [{"sha": pyrepo.feat_sha, "clean": False, "note": task.gold_note, "lint": False}]


def test_gold_check_declared_linter_accepting_the_gold_keeps_it_clean(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    script = _lint_script(tmp_path / "bin" / "house-lint", "exit 0\n")
    out, events = _qualify_with_lint(pyrepo, {"command": [str(script)]}, tmp_path)
    task = out.task
    assert task is not None and task.gold_clean is True and task.gold_note == ""
    gold = [p for k, p in events if k == "mine.gold"]
    assert gold == [{"sha": pyrepo.feat_sha, "clean": True, "note": "", "lint": True}]


def test_gold_check_linter_that_cannot_run_never_credits_the_gold(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The instrument, not the patch: a missing binary is a harness error — the gold is
    not credited and the note says the linter could not run (not that the gold failed)."""
    missing = str(tmp_path / "bin" / "no-such-linter")
    out, events = _qualify_with_lint(pyrepo, {"command": [missing]}, tmp_path)
    task = out.task
    assert task is not None and task.gold_clean is False
    assert task.gold_note.startswith("gold lint could not run (config): config: not runnable")
    assert "gold fails belt 5" not in task.gold_note
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [False]


def test_gold_check_lint_timeout_is_a_failure_never_a_pass(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    script = _lint_script(tmp_path / "bin" / "slow-lint", "sleep 5\nexit 0\n")
    out, _ = _qualify_with_lint(pyrepo, {"command": [str(script)], "timeout": 1}, tmp_path)
    task = out.task
    assert task is not None and task.gold_clean is False
    assert task.gold_note == "gold fails belt 5 (config): config timed out"


def test_gold_check_disabled_lint_leaves_belt_five_unevaluated(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    out, events = _qualify_with_lint(pyrepo, {"disabled": True}, tmp_path)
    task = out.task
    assert task is not None and task.gold_clean is True and task.gold_note == ""
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [None]


def test_gold_check_lint_runs_only_after_the_core_belts_hold(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A gold that breaks the belt is reported as such; belt 5 is not consulted (the
    linter would have rejected it too, and its verdict would only obscure the finding)."""
    script = _lint_script(tmp_path / "bin" / "house-lint", "exit 1\n")
    cfg = pr.default_config(lint={"command": [str(script)]})
    sha = pyrepo.add_bad_gold_commit()
    cand = next(c for c in m.iter_candidates(pyrepo.repo, cfg) if c.sha == sha)
    events, on_event = _collector()
    out = m.qualify(
        pyrepo.repo,
        cfg,
        cand,
        runner=get_runner(cfg),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        on_event=on_event,
    )
    task = out.task
    assert task is not None and task.gold_clean is False
    assert task.gold_note == "gold introduced 2 belt failure(s)"
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [None]


def test_read_gold_lint_is_the_one_place_the_verdict_is_read() -> None:
    assert m._read_gold_lint(None) == (True, "")
    assert m._read_gold_lint(LintRun("gofmt", (), None, "nothing to lint")) == (True, "")
    ok = LintRun("gofmt", (LintStep("gofmt", ("gofmt", "-l"), ("a.go",), 0, True),), True)
    assert m._read_gold_lint(ok) == (True, "")
    rejected = LintRun(
        "ruff+ruff-format",
        (LintStep("ruff", ("ruff", "check"), ("a.py",), 1, False, "F401"),),
        False,
        "ruff rejected 1 changed file(s)",
    )
    assert m._read_gold_lint(rejected) == (
        False,
        "gold fails belt 5 (ruff+ruff-format): ruff rejected 1 changed file(s)",
    )
    harness = LintRun(
        "ruff",
        (LintStep("ruff", ("ruff",), ("a.py",), 127, None, "", False, 0.0, "ruff: not runnable"),),
        False,
        "ruff: not runnable",
        "ruff: not runnable",
    )
    assert m._read_gold_lint(harness) == (
        False,
        "gold lint could not run (ruff): ruff: not runnable",
    )


# --- the real toolchains: the maintainers' patch, mis-formatted on purpose -------------


def _qualify_sha(
    repo: GitRepo, config: RepoConfig, sha: str, scratch: Path
) -> tuple[m.MineOutcome, Events]:
    cand = langs.feat_candidate(repo, config, sha)
    events, on_event = _collector()
    out = m.qualify(
        repo,
        config,
        cand,
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=scratch,
        on_event=on_event,
    )
    return out, events


@pytest.mark.toolchain("go")
@pytest.mark.skipif(
    not (langs.has_tool("go") and langs.has_tool("gofmt")), reason="go/gofmt not on PATH"
)
def test_go_gold_that_gofmt_rejects_is_not_gold_clean(tmp_path: Path) -> None:
    """The fixture's feat commit is gofmt-clean: the gold passes belt 5 (``lint=True``).
    A later commit whose source the maintainers left un-gofmt'd — cobra #1559's shape,
    but in the gold itself — is kept and flagged: pre-existing lint debt, not a builder
    observation."""
    root, feat_sha = _gorepo.build(tmp_path)
    repo, config = GitRepo(root), _gorepo.config()
    out, events = _qualify_sha(repo, config, feat_sha, tmp_path / "mine-clean")
    assert out.task is not None and out.task.gold_clean is True and out.task.gold_note == ""
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [True]

    _fx.write_files(
        root,
        {
            "calc/mul.go": (
                "package calc\n\n// Mul returns a * b.\nfunc Mul(a,b int) int {\n\treturn a*b\n  }\n"
            ),
            "calc/mul_test.go": (
                'package calc\n\nimport "testing"\n\n'
                "func TestMul(t *testing.T) {\n"
                "\tif got := Mul(3, 2); got != 6 {\n"
                '\t\tt.Fatalf("Mul(3, 2) = %d, want 6", got)\n'
                "\t}\n}\n"
            ),
        },
    )
    ugly_sha = _fx.commit_all(root, "feat: add mul (unformatted)")
    out, events = _qualify_sha(repo, config, ugly_sha, tmp_path / "mine-ugly")
    task = out.task
    assert task is not None and task.red_checked is True  # kept, but flagged
    assert task.gold_clean is False
    assert task.gold_note == "gold fails belt 5 (gofmt): gofmt rejected 1 changed file(s)"
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [False]


def _ruff_binary() -> str | None:
    sibling = Path(sys.executable).parent / "ruff"
    if sibling.exists():
        return str(sibling)
    return shutil.which("ruff")


@pytest.mark.skipif(_ruff_binary() is None, reason="ruff not available")
def test_python_gold_that_ruff_rejects_is_not_gold_clean(tmp_path: Path) -> None:
    """click's apparatus (``[tool.ruff]`` + the ``ruff-format`` hook): the feat gold is
    clean; a later gold with an unused import is flagged, and the note names the plan."""
    extra = {
        "pyproject.toml": "[tool.ruff]\nline-length = 88\n[tool.ruff.lint]\nselect = ['E', 'F']\n",
        ".pre-commit-config.yaml": (
            "repos:\n  - hooks:\n      - id: ruff-check\n      - id: ruff-format\n"
        ),
    }
    root, feat_sha = _pyrepo_min.build(tmp_path, extra=extra)
    repo = GitRepo(root)
    config = _pyrepo_min.config(runner_opts={"python": sys.executable})
    out, events = _qualify_sha(repo, config, feat_sha, tmp_path / "mine-clean")
    assert out.task is not None and out.task.gold_clean is True, out.task
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [True]

    _fx.write_files(
        root,
        {
            "pkg/mul.py": "import os\n\n\ndef mul(a: int, b: int) -> int:\n    return a * b\n",
            "tests/test_mul.py": (
                "from pkg.mul import mul\n\n\ndef test_mul():\n    assert mul(3, 2) == 6\n"
            ),
        },
    )
    ugly_sha = _fx.commit_all(root, "feat: add mul (unused import)")
    out, events = _qualify_sha(repo, config, ugly_sha, tmp_path / "mine-ugly")
    task = out.task
    assert task is not None and task.gold_clean is False
    assert re.fullmatch(
        r"gold fails belt 5 \(ruff(@[\d.]+)?\+ruff-format\): ruff rejected 1 changed file\(s\)",
        task.gold_note,
    )
    assert [p["lint"] for k, p in events if k == "mine.gold"] == [False]
    # the gold source stays as the maintainers wrote it: `ruff check --no-fix` never edits
    assert (root / "pkg" / "mul.py").read_text().startswith("import os\n")


def test_support_file_under_the_test_layout_is_overlaid_but_never_a_target(
    tmp_path: Path,
) -> None:
    """mesh-client commits change ``tests/mock_server.py`` (no tests) alongside real test
    files; graded as a target it disqualified every negative control as a 'malformed
    oracle' (2026-09-15). Support files ride along with the overlay; only files that
    define tests are targets, and a candidate with no such file is skipped."""
    root, _feat_sha = _pyrepo_min.build(tmp_path)
    repo = GitRepo(root)
    config = _pyrepo_min.config(runner_opts={"python": sys.executable})
    _fx.write_files(
        root,
        {
            "pkg/mul.py": "def mul(a: int, b: int) -> int:\n    return a * b\n",
            "tests/helpers.py": "def three() -> int:\n    return 3\n",
            "tests/test_mul.py": (
                "from pkg.mul import mul\nfrom tests.helpers import three\n\n\n"
                "def test_mul():\n    assert mul(three(), 2) == 6\n"
            ),
        },
    )
    sha = _fx.commit_all(root, "feat: add mul with a helper")
    out, _ = _qualify_sha(repo, config, sha, tmp_path / "mine-support")
    assert out.task is not None, out.skipped_reason
    assert set(out.task.test_files) == {"tests/helpers.py", "tests/test_mul.py"}
    assert out.task.target_tests == ("tests/test_mul.py",)
    # a commit whose only test-layout change is support is not a task
    _fx.write_files(
        root,
        {
            "pkg/mul.py": "def mul(a: int, b: int) -> int:\n    return b * a\n",
            "tests/helpers.py": "def three() -> int:\n    return 1 + 2\n",
        },
    )
    sha2 = _fx.commit_all(root, "chore: helper tweak")
    out2, _ = _qualify_sha(repo, config, sha2, tmp_path / "mine-support-only")
    assert out2.task is None and "support only" in (out2.skipped_reason or "")


def test_mine_skips_a_candidate_whose_harness_errored_and_stops_after_three_in_a_row(
    pyrepo: pr.PyRepo, executor: LocalExecutor, tmp_path: Path
) -> None:
    """A dependency era that would not install failed the WHOLE re-qualification run at
    0/11 (nhsuk-react-components, 2026-09-15). One candidate's harness error is that
    candidate's skip; three in a row is a broken instrument and stops the run."""

    class Flaky(PytestRunner):
        calls = 0

        def run_for(self, executor, root, scope, *, timeout=0, authored):  # type: ignore[override]
            Flaky.calls += 1
            raise RuntimeError("node era x: npm install rc=1")

    runner = Flaky(pyrepo.config)
    events, on_event = _collector()
    # one candidate on its own: skipped with the reason, the loop finishes normally
    outcomes = list(
        m.mine(
            pyrepo.repo,
            pyrepo.config,
            runner=runner,
            executor=executor,
            scratch=tmp_path / "one",
            max_candidates=1,
            on_event=on_event,
        )
    )
    assert len(outcomes) == 1 and outcomes[0].task is None
    assert outcomes[0].skipped_reason.startswith("harness error: RuntimeError: node era x")
    assert ("mine.skip", {"sha": pyrepo.feat_sha, "reason": outcomes[0].skipped_reason}) in events
    assert events[-1][0] == "mine.done"
    # three in a row (three candidates, every one erroring) → the run stops with the reason
    shas = [pyrepo.feat_sha]
    for i in range(2):
        (pyrepo.path / "src" / "calc" / f"extra{i}.py").write_text(
            f"X{i} = {i}\n", encoding="utf-8"
        )
        (pyrepo.path / "tests" / f"test_extra{i}.py").write_text(
            f"from calc.extra{i} import X{i}\n\n\ndef test_x{i}():\n    assert X{i} == {i}\n",
            encoding="utf-8",
        )
        shas.append(pr._commit(pyrepo.path, f"feat: extra {i}"))
    with pytest.raises(RuntimeError, match=r"3 candidates in a row failed on a harness error"):
        list(
            m.mine(
                pyrepo.repo,
                pyrepo.config,
                runner=runner,
                executor=executor,
                scratch=tmp_path / "three",
                only=frozenset(shas),
            )
        )
