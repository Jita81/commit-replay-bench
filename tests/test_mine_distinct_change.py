"""A distinct commit is a distinct change (G-954; DL-093).

The miner walks ``git log --no-merges``, which lists a cherry-pick beside its original and a
revert beside the commit it reverts. The commit census of 2026-09-27 found both in click's
``bug.fix`` S cell, one pair in the ledger with opposite outcomes, so one change counted as
two distinct commits. Now the walk keeps one commit per change — the older of a same-patch
pair, the original of a revert pair — skips the other with a ``mine.skip`` naming the one
kept, and stamps the change's identity (``change_id``) on the task; a replay row carries it
(from apparatus 2.4 the ledger refuses a replay row without it).

Navigation
----------
What it is:   The tests of the distinct-change rule in the miner and the replay path.
What it does: Pins that two cherry-picks of one change mine as one task (the older kept),
              that a revert and its original mine as one (the original kept), that both
              commits of a pair share one change identity, that a revert whose original lies
              outside the walk is still never kept, that a change the store already holds is
              never mined again whichever of its commits the store holds (in the walk or
              outside it), that a replay of a task mined before the rule stamps the identity on
              its 2.4 row, and that a row below 2.4 carries none (P-296, P-297).
How:          ``tests/fixtures/distinct_changes.py`` (pyrepo plus the two pairs, dated a day
              apart) through ``iter_candidates``, ``mine`` (no gold: RED and baseline only) and
              ``run_task`` with the gold patch.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md; DL-093
Works with:   src/crb/core/mine.py (``ChangeIndex``, ``change_identity``, ``iter_candidates``),
              src/crb/core/run.py (stamps a missing identity), src/crb/core/ledger.py
              (``LABEL_CHANGE_ID``), tests/fixtures/distinct_changes.py (the two same-change
              pairs)
Tested by:    tests/test_mine_distinct_change.py
Touch when:   the rule for which commit of a change is kept changes (DL-093 first).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core import ledger as lg
from crb.core import mine as m
from crb.core import version as crb_version
from crb.core.evidence import BuilderRef
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger
from crb.core.run import BuildAttempt, RunSpec, run_task
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import distinct_changes as dc
from fixtures import pyrepo as pr
from fixtures.posture import witnessed_context_for

Events = list[tuple[str, dict[str, Any]]]


@pytest.fixture
def two(tmp_path: Path) -> dc.DistinctRepo:
    return dc.build(tmp_path / "repo")


def _walk(repo: dc.DistinctRepo, **kw: Any) -> tuple[list[m.Candidate], Events]:
    events: Events = []
    cands = list(
        m.iter_candidates(
            repo.repo, repo.config, on_event=lambda a, p: events.append((a, dict(p))), **kw
        )
    )
    return cands, events


def _skip(events: Events, sha: str) -> str:
    return next(p["reason"] for a, p in events if a == "mine.skip" and p["sha"] == sha)


def test_two_cherry_picks_of_one_change_mine_as_one_distinct_change(
    two: dc.DistinctRepo,
) -> None:
    cands, events = _walk(two)
    shas = [c.sha for c in cands]
    assert two.pick_old in shas and two.pick_new not in shas  # the older is kept
    reason = _skip(events, two.pick_new)
    assert reason.startswith("duplicate change") and two.pick_old[:12] in reason
    kept = next(c for c in cands if c.sha == two.pick_old)
    assert kept.change_id == m.change_identity(two.repo, two.pick_new)
    assert kept.change_id and not kept.change_id.startswith("commit:")


def test_a_revert_and_its_original_mine_as_one_distinct_change(two: dc.DistinctRepo) -> None:
    cands, events = _walk(two)
    shas = [c.sha for c in cands]
    assert two.original in shas and two.revert not in shas  # the original is kept
    reason = _skip(events, two.revert)
    assert reason.startswith("revert of") and two.original[:12] in reason
    original = next(c for c in cands if c.sha == two.original)
    assert m.change_identity(two.repo, two.revert) == original.change_id


def test_every_kept_commit_is_a_different_change(two: dc.DistinctRepo) -> None:
    cands, _ = _walk(two)
    assert {c.sha for c in cands} == {two.feat_sha, two.pick_old, two.original}
    assert len({c.change_id for c in cands}) == len(cands)


def test_a_revert_whose_original_is_outside_the_walk_is_still_never_kept(
    two: dc.DistinctRepo,
) -> None:
    cands, events = _walk(two, log_n=1)  # the walk sees the revert alone
    assert cands == []
    assert _skip(events, two.revert).startswith("revert of")


def test_a_change_already_mined_under_its_newer_copy_is_not_mined_again(
    two: dc.DistinctRepo,
) -> None:
    """The store may hold the NEWER copy (mined before the rule, or in a smaller window):
    the walk must not then mine the older copy as a second task of the same change."""
    cands, events = _walk(two, skip=frozenset({two.pick_new}))
    assert two.pick_old not in {c.sha for c in cands}
    reason = _skip(events, two.pick_old)
    assert reason.startswith("already mined") and two.pick_new[:12] in reason


def test_a_change_already_mined_as_its_revert_is_not_mined_again(two: dc.DistinctRepo) -> None:
    cands, events = _walk(two, skip=frozenset({two.revert}))
    assert two.original not in {c.sha for c in cands}
    reason = _skip(events, two.original)
    assert reason.startswith("already mined") and two.revert[:12] in reason


def test_a_known_task_outside_the_walk_still_holds_its_change(two: dc.DistinctRepo) -> None:
    """A known sha the window does not reach is identified on its own (``change_identity``);
    a known sha the repository does not hold holds no change and skips nothing."""
    # the window holds revert, original and pick_new; the known pick_old lies below it
    cands, events = _walk(two, log_n=3, skip=frozenset({two.pick_old, "f" * 40}))
    assert {c.sha for c in cands} == {two.original}
    assert two.pick_old[:12] in _skip(events, two.pick_new)


def test_extending_a_mine_never_adds_a_second_task_for_a_known_change(
    two: dc.DistinctRepo, tmp_path: Path
) -> None:
    outcomes = list(
        m.mine(
            two.repo,
            two.config,
            runner=PytestRunner(two.config),
            executor=LocalExecutor(),
            scratch=tmp_path / "scratch",
            gold=False,
            target_count=10,
            known=frozenset({two.pick_new, two.revert}),
        )
    )
    held = {m.change_identity(two.repo, two.pick_new), m.change_identity(two.repo, two.revert)}
    mined = {o.task.labels[m.LABEL_CHANGE_ID] for o in outcomes if o.task is not None}
    assert mined and mined.isdisjoint(held)
    assert {o.sha for o in outcomes}.isdisjoint({two.pick_old, two.original})


def test_the_mine_records_one_task_per_change_with_its_identity(
    two: dc.DistinctRepo, tmp_path: Path
) -> None:
    runner = PytestRunner(two.config)
    events: Events = []
    outcomes = list(
        m.mine(
            two.repo,
            two.config,
            runner=runner,
            executor=LocalExecutor(),
            scratch=tmp_path / "scratch",
            gold=False,
            target_count=10,
            on_event=lambda a, p: events.append((a, dict(p))),
        )
    )
    tasks = {o.sha: o.task for o in outcomes if o.task is not None}
    assert two.pick_old in tasks and two.pick_new not in tasks
    assert two.original in tasks and two.revert not in tasks
    for sha, task in tasks.items():
        assert task.labels[m.LABEL_CHANGE_ID] == m.change_identity(two.repo, sha)
    assert {o.sha for o in outcomes}.isdisjoint({two.pick_new, two.revert})


def _gold_spec(
    pyrepo: pr.PyRepo, runner: PytestRunner, executor: LocalExecutor, tmp_path: Path
) -> RunSpec:
    return RunSpec(
        run_id="run-change",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp_path / "scratch",
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        evidence_dir=tmp_path / "evidence",
        ladder=("r1",),
        context_for=witnessed_context_for(
            pyrepo.repo, pyrepo.config, runner=runner, executor=executor, scratch=tmp_path / "s"
        ),
    )


def _apply_gold(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
    pr.apply_gold(ws)
    return BuildAttempt(BuilderRef(name="fixture", model="m", provider="p", mode="sighted"))


def test_a_replay_row_below_2_4_carries_no_change_identity(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The identity is a 2.4 label: a replay at 2.3 writes the row a 2.3 replay always
    wrote, whether or not its task was mined with one (DL-094 (2))."""
    monkeypatch.setattr(crb_version, "APPARATUS_VERSION", "2.3")
    for task in (
        feat_task.with_(labels={}),
        feat_task.with_(labels={lg.LABEL_CHANGE_ID: "e" * 40}),
    ):
        outcome = run_task(
            _gold_spec(pyrepo, runner, executor, tmp_path / task.labels.get("change_id", "x")),
            pyrepo.repo,
            task,
            _apply_gold,
        )
        (row,) = outcome.rows
        assert row.apparatus_version == "2.3" and row.clean
        assert lg.LABEL_CHANGE_ID not in row.labels


def test_a_replay_of_a_task_mined_before_the_rule_names_its_change_on_the_row(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task stored before the rule carries no ``change_id``: the replay path measures it,
    and a 2.4 row — which the ledger refuses without it — carries it. The apparatus is pinned
    to 2.4 here, as stream R's bump sets it."""
    old_task = feat_task.with_(labels={})
    assert lg.LABEL_CHANGE_ID not in old_task.labels
    monkeypatch.setattr(crb_version, "APPARATUS_VERSION", "2.4")

    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        pr.apply_gold(ws)
        return BuildAttempt(BuilderRef(name="fixture", model="m", provider="p", mode="sighted"))

    spec = RunSpec(
        run_id="run-change",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp_path / "scratch",
        ledger=JsonlLedger(tmp_path / "ledger.jsonl"),
        evidence_dir=tmp_path / "evidence",
        ladder=("r1",),
        context_for=witnessed_context_for(
            pyrepo.repo, pyrepo.config, runner=runner, executor=executor, scratch=tmp_path / "s"
        ),
    )
    outcome = run_task(spec, pyrepo.repo, old_task, build_fn)
    (row,) = outcome.rows
    assert row.apparatus_version == "2.4" and row.clean
    assert row.labels[lg.LABEL_CHANGE_ID] == m.change_identity(pyrepo.repo, pyrepo.feat_sha)
    assert row.labels[lg.LABEL_FAILURE_KIND] == ""
    assert row.labels[lg.LABEL_LINT_REASON] == "none_detected"
