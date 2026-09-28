"""Belt 5 says why (ADR-0025 item 5): ``lint_status`` on the grade, in the pack, on a 2.4 row.

``repo_lint_clean = None`` used to mean three different things — the repository has no
linter, the operator switched belt 5 off, or the grade stopped before belt 5 — so a cell
could route ``deliver`` on rows whose lint belt was off (external assessment 2026-09-25, A3;
G-973). Each value of ``crb.core.lint.LINT_STATUSES`` is produced here by a real grade on the
minimal Python fixture, recorded in the evidence pack's grade, and written as the hashed
``lint_reason`` label on a row of apparatus 2.4.

Navigation
----------
What it is:   One test per ``lint_status`` value through the real grader, plus the pack and
              the 2.4 row that carry it.
What it does: Pins ``evaluated`` (accepted and rejected), ``none_detected`` (no linter; a linter
              that concerns no changed file), ``disabled_by_config``, ``error``,
              ``not_reached`` and ``not_requested``; that ``GradeResult`` refuses a status that
              contradicts belt 5; that the pack records the status and a 2.4 row its label.
How:          ``pyrepo_min`` mined and graded with fake linter scripts on a real
              ``LocalExecutor`` (the same shape as tests/test_lint.py's grader layer).
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md; ADR-0025 item 5 (stream G; the draft stream R
              commits)
Works with:   src/crb/core/lint.py (``LINT_STATUSES``, ``lint_status``), src/crb/core/grade.py
              (stamps it), src/crb/core/ledger.py (``lint_reason`` on a 2.4 row),
              tests/test_lint.py (the belt's own suite)
Tested by:    tests/test_lint_status.py
Touch when:   never for a new repository; a status joins ``LINT_STATUSES`` or the grade reaches belt
              5 by another path.
"""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from crb.core import grade as g
from crb.core import ledger as lg
from crb.core import lint as lint_mod
from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import qualify
from crb.core.runners import get_runner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace
from fixtures.posture import grade_witnessed

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs  # type: ignore[no-redef]

pyrepo_min = langs.fixture_module("pyrepo_min")


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _config_with(base: RepoConfig, **changes: Any) -> RepoConfig:
    d = base.to_dict()
    d.update(changes)
    return RepoConfig.from_dict(base.name, d)


@pytest.fixture
def pyfix(tmp_path: Path) -> tuple[GitRepo, str, RepoConfig, TaskSpec]:
    """The minimal fixture and its task, mined under its real (lint-less) configuration so
    the gold is clean whatever linter a case declares for the trial."""
    root, feat_sha = pyrepo_min.build(tmp_path)
    repo, config = GitRepo(root), pyrepo_min.config()
    cand = langs.feat_candidate(repo, config, feat_sha)
    out = qualify(
        repo,
        config,
        cand,
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=tmp_path / "mine",
    )
    assert out.task is not None, out.skipped_reason
    return repo, feat_sha, config, out.task


def _grade(
    repo: GitRepo,
    config: RepoConfig,
    task: TaskSpec,
    dest: Path,
    *,
    gold: bool = True,
    **kw: Any,
) -> g.GradeResult:
    ws: Workspace = langs.trial_worktree(
        repo, langs.feat_candidate(repo, config, task.task_id), dest, config
    )
    if gold:
        ws.overlay_sources(task.src_files)
    return grade_witnessed(
        ws,
        task,
        config=config,
        runner=get_runner(config),
        executor=LocalExecutor(),
        gold_lint=True,
        **kw,
    )


Case = Callable[[Path, RepoConfig], tuple[RepoConfig, dict[str, Any]]]


def _none(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    return cfg, {}


def _disabled(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    return _config_with(cfg, lint={"disabled": True}), {}


def _accepting(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    script = _script(tmp / "bin" / "ok", "exit 0\n")
    return _config_with(cfg, lint={"command": [str(script)]}), {}


def _rejecting(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    script = _script(tmp / "bin" / "no", 'echo "$@: E501"\nexit 1\n')
    return _config_with(cfg, lint={"command": [str(script)], "exts": [".py"]}), {}


def _unrunnable(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    return _config_with(cfg, lint={"command": [str(tmp / "bin" / "absent")]}), {}


def _other_language(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    script = _script(tmp / "bin" / "rs", "exit 1\n")
    return _config_with(cfg, lint={"command": [str(script)], "exts": [".rs"]}), {}


def _not_requested(tmp: Path, cfg: RepoConfig) -> tuple[RepoConfig, dict[str, Any]]:
    script = _script(tmp / "bin" / "no", "exit 1\n")
    return _config_with(cfg, lint={"command": [str(script)]}), {"evaluate_lint": False}


@pytest.mark.parametrize(
    ("case", "status", "belt", "clean"),
    [
        (_none, lint_mod.LINT_NONE_DETECTED, None, True),
        (_other_language, lint_mod.LINT_NONE_DETECTED, None, True),
        (_disabled, lint_mod.LINT_DISABLED_BY_CONFIG, None, True),
        (_accepting, lint_mod.LINT_EVALUATED, True, True),
        (_rejecting, lint_mod.LINT_EVALUATED, False, False),
        (_unrunnable, lint_mod.LINT_ERROR, False, False),
        (_not_requested, lint_mod.LINT_NOT_REQUESTED, None, True),
    ],
    ids=[
        "none_detected",
        "none_detected-no-changed-file-concerned",
        "disabled_by_config",
        "evaluated-accepted",
        "evaluated-rejected",
        "error",
        "not_requested",
    ],
)
def test_every_lint_status_from_a_real_grade(
    pyfix: tuple[GitRepo, str, RepoConfig, TaskSpec],
    tmp_path: Path,
    case: Case,
    status: str,
    belt: bool | None,
    clean: bool,
) -> None:
    repo, _, base, task = pyfix
    config, kw = case(tmp_path, base)
    res = _grade(repo, config, task, tmp_path / "t", **kw)
    assert (res.lint_status, res.belts.repo_lint_clean, res.clean) == (status, belt, clean)
    assert res.to_dict()["lint_status"] == status  # the evidence pack's grade records it
    if status == lint_mod.LINT_NOT_REQUESTED:
        return  # the negative controls: a grade that writes no row
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64, apparatus_version="2.4")
    assert row.labels[lg.LABEL_LINT_REASON] == status
    assert row.labels[lg.LABEL_FAILURE_KIND] == row.failure_kind


def test_a_grade_that_stops_before_belt_5_is_not_reached(
    pyfix: tuple[GitRepo, str, RepoConfig, TaskSpec], tmp_path: Path
) -> None:
    repo, _, base, task = pyfix
    config, _ = _rejecting(tmp_path, base)
    res = _grade(repo, config, task, tmp_path / "t", gold=False)  # no-op: target stays RED
    assert res.belts.target_green is False and res.belts.repo_lint_clean is None
    assert res.lint_status == lint_mod.LINT_NOT_REACHED
    row = lg.grade_row_from_result(res, task, pack_hash="c" * 64, apparatus_version="2.4")
    assert row.labels[lg.LABEL_LINT_REASON] == lint_mod.LINT_NOT_REACHED
    assert row.failure_kind == lg.FAILURE_BUILDER_RED


@pytest.mark.parametrize(
    ("status", "belt", "clean"),
    [
        (lint_mod.LINT_EVALUATED, None, True),
        (lint_mod.LINT_DISABLED_BY_CONFIG, True, True),
        (lint_mod.LINT_ERROR, True, True),
        ("off", None, True),
    ],
)
def test_a_grade_result_refuses_a_status_that_contradicts_belt_5(
    status: str, belt: bool | None, clean: bool
) -> None:
    belts = g.Belts(True, True, True, True, belt)
    with pytest.raises(ValueError, match="lint status"):
        g.GradeResult("a" * 40, "r", "sighted", clean=clean, belts=belts, lint_status=status)


def test_the_statuses_are_the_adr_vocabulary() -> None:
    assert lint_mod.LINT_STATUSES == (
        "evaluated",
        "none_detected",
        "disabled_by_config",
        "error",
        "not_reached",
        "not_requested",
    )
