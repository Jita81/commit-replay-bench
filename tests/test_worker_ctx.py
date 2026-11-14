"""The worker's claim-time check of a context-set run (ADR-0050 items 5 and 6).

At claim the worker re-reads the run's stored set and re-checks it exactly as ``POST /runs``
did, plus what only the clone can check: a ``mech*`` entry drafted at its task's parent, and
each task's gap label (rule ``anchor.v1``) read from the commit message and the parent tree.
It hands the adapter the set's tasks in set order, the stamps every row carries, the entries
(the ``entries`` role only) and the arm's set name. Any refusal is a ``run.refused`` event
before anything is qualified or built; a context-set run never reserves a reading's commit.

Navigation
----------
What it is:   The tests of ``crb.server.worker``'s ``_ctx_plan``, ``tree_has_at``, the
              replay path's refusal and the reserver's refusal for a context-set run.
What it does: Pins each refusal reason; the plan of each role (tasks, stamps, entries,
              arm); the gap label against ``ctx_gap_anchor``; the refused run's event.
How:          A worker shell (``Worker.__new__``) over a SQLite store holding the ``pyrepo``
              fixture's feat task, its clone as the run's git, and sets written where
              ``POST /ctxsets`` stores them.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/server/worker.py (under test), src/crb/core/ctxset.py (the set, the gap
              rule, the stamps), src/crb/server/routes/runs.py (``stored_ctxset``),
              tests/fixtures/pyrepo.py (the tiny git repository the worker runs over)
Tested by:    tests/test_worker_ctx.py
Touch when:   never for a new repository; the claim-time checks of a context-set run, or what the
              worker hands the adapter, change.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from crb.core import context_arm as ca
from crb.core import ctxset
from crb.core.ctxset import CtxSetRefused
from crb.core.git import GitError
from crb.core.ledger import ctx_label_violation
from crb.observability.events import StepStatus
from crb.server import worker as worker_mod
from crb.server.routes.runs import CTXSET_DIR
from crb.server.worker import Worker
from crb.store import init_db, make_engine, make_session_factory
from crb.store.jobs import STATUS_FAILED
from crb.store.models import Repo, Task
from fixtures import pyrepo as pr

DRAFTER = "some-model-v1@" + "c" * 64
WHEN = "2026-01-01T00:00:00+00:00"
TEXT = "The calculator module keeps one function per operation."


def _doc(task_id: str, *, source: str, parent: str = "") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "task_id": task_id,
        "entry_id": "e-1",
        "version": "1",
        "text": TEXT,
        "produced_at": WHEN,
        "mechanical": source.startswith("mech"),
    }
    doc: dict[str, Any] = {
        "schema": ctxset.SCHEMA,
        "source": source,
        "repo": pr.REPO_NAME,
        "method": "drafted at the parent commit" if parent else "written from the change",
        "entries": [entry],
    }
    if source.startswith("mech"):
        entry["source_rev"] = parent
        doc["drafter"] = DRAFTER
    return doc


def _store(home: Path, doc: dict[str, Any]) -> ctxset.CtxSet:
    parsed = ctxset.parse(doc)
    root = home / CTXSET_DIR
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{parsed.digest}.json").write_text(json.dumps(doc), encoding="utf-8")
    return parsed


class _Rig:
    def __init__(self, tmp_path: Path, pyrepo: pr.PyRepo) -> None:
        self.pyrepo = pyrepo
        self.home = tmp_path / "home"
        self.home.mkdir()
        engine = make_engine(f"sqlite:///{tmp_path / 'w.db'}")
        init_db(engine)
        self.factory = make_session_factory(engine)
        task = pyrepo.feat_task()
        self.task = task
        with self.factory() as s:
            s.add(Repo(name=pr.REPO_NAME, language="python", runner="pytest", config_json={}))
            s.flush()
            s.add(
                Task(
                    repo=pr.REPO_NAME,
                    task_id=task.task_id,
                    pool=task.pool,
                    size=task.size,
                    capability_class=task.capability_class,
                    language=task.language,
                    authored=task.authored,
                    subject=task.subject,
                    red_checked=task.red_checked,
                    gold_clean=task.gold_clean,
                    spec_json=task.to_dict(),
                )
            )
            s.commit()
        self.parent = pyrepo.repo.parent(task.task_id)
        self.worker = Worker.__new__(Worker)
        self.worker.settings = cast(
            Any,
            SimpleNamespace(home=self.home, executor="docker", builder_executor="docker"),
        )
        self.worker.factory = self.factory
        self.events: list[tuple[str, dict[str, Any]]] = []

    def ctx(self, **params: Any) -> Any:
        def emit(_who: str, action: str, **kw: Any) -> None:
            self.events.append((action, kw))

        return SimpleNamespace(
            params={"learning": "off", **params},
            run=SimpleNamespace(repo=pr.REPO_NAME, id="run-1"),
            git=self.pyrepo.repo,
            emit=emit,
            counts={},
        )

    def plan(self, mode: str = "blind", **params: Any) -> Any:
        return self.worker._ctx_plan(self.ctx(**params), mode=mode)


@pytest.fixture
def rig(tmp_path: Path, pyrepo: pr.PyRepo) -> _Rig:
    return _Rig(tmp_path, pyrepo)


def _refused(reason: str) -> Any:
    return pytest.raises(CtxSetRefused, match=f"^{reason}:")


# --- the plan -------------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["mech", "oracle"])
def test_the_entries_plan_carries_the_sets_tasks_stamps_entries_and_arm(
    rig: _Rig, source: str
) -> None:
    ctx = _store(rig.home, _doc(rig.task.task_id, source=source, parent=rig.parent))
    plan = rig.plan(context_set=ctx.name, context_role="entries")
    assert [t.task_id for t in plan.tasks] == [rig.task.task_id]
    assert plan.arm_set == ctx.name and plan.role == "entries"
    (entry,) = plan.entries.values()
    assert entry.text == TEXT and entry.mechanical is (source == "mech")
    assert entry.source_rev == (rig.parent if source == "mech" else "")
    stamps = plan.stamps[rig.task.task_id]
    assert stamps[ca.LABEL_CTX_SET] == ctx.digest
    gap = ctxset.ctx_gap_anchor(
        rig.pyrepo.repo.message(rig.task.task_id),
        worker_mod.tree_has_at(rig.pyrepo.repo, rig.parent),
    )
    assert stamps[ca.LABEL_CTX_GAP] == gap
    assert ctx_label_violation(f"A0+library@{ctx.name}", stamps) == ""


def test_the_control_plan_carries_the_stamps_and_nothing_to_deliver(rig: _Rig) -> None:
    ctx = _store(rig.home, _doc(rig.task.task_id, source="oracle"))
    plan = rig.plan(context_set=ctx.name, context_role="control")
    assert plan.arm_set == "" and plan.entries == {}
    stamps = plan.stamps[rig.task.task_id]
    assert stamps[ca.LABEL_CTX_SOURCE] == ca.CTX_SOURCE_CONTROL
    assert ctx_label_violation(ca.BASE_A0, stamps) == ""


def test_the_role_defaults_to_entries(rig: _Rig) -> None:
    ctx = _store(rig.home, _doc(rig.task.task_id, source="oracle"))
    assert rig.plan(context_set=ctx.name).arm_set == ctx.name


# --- the refusals ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "over"),
    [
        ("sighted", {}),
        ("blind", {"arm": "S1"}),
        ("blind", {"learning": "on"}),
        ("blind", {"learning": None}),
        ("blind", {"context_role": "treatment"}),
        ("blind", {"task_ids": ["x"]}),
        ("blind", {"limit": 1}),
    ],
)
def test_a_run_off_blind_a0_is_refused_mode(rig: _Rig, mode: str, over: dict[str, Any]) -> None:
    ctx = _store(rig.home, _doc(rig.task.task_id, source="oracle"))
    with _refused(ctxset.REASON_MODE):
        rig.plan(mode, context_set=ctx.name, **over)


@pytest.mark.parametrize(
    ("run_executor", "builder_executor"), [("local", "docker"), ("docker", "host")]
)
def test_an_unsealed_run_is_refused_posture(
    rig: _Rig, run_executor: str, builder_executor: str
) -> None:
    ctx = _store(rig.home, _doc(rig.task.task_id, source="oracle"))
    rig.worker.settings = cast(
        Any,
        SimpleNamespace(home=rig.home, executor="docker", builder_executor=builder_executor),
    )
    with _refused(ctxset.REASON_POSTURE):
        rig.plan(context_set=ctx.name, executor=run_executor)


def test_a_set_not_stored_is_refused(rig: _Rig) -> None:
    with _refused(ctxset.REASON_DIGEST):
        rig.plan(context_set="ctx.oracle." + "0" * 12)


def test_a_set_of_another_repository_or_unknown_tasks_is_refused(rig: _Rig) -> None:
    other = _doc(rig.task.task_id, source="oracle")
    other["repo"] = "elsewhere"
    with _refused(ctxset.REASON_REPO):
        rig.plan(context_set=_store(rig.home, other).name)
    unknown = _doc("f" * 40, source="oracle")
    with _refused(ctxset.REASON_COVERAGE):
        rig.plan(context_set=_store(rig.home, unknown).name)


def test_a_mechanical_entry_not_drafted_at_the_parent_is_refused(rig: _Rig) -> None:
    ctx = _store(rig.home, _doc(rig.task.task_id, source="mech", parent="0" * 40))
    with _refused(ctxset.REASON_MECHANICAL):
        rig.plan(context_set=ctx.name)


def _placebo(treatment: ctxset.CtxSet, text: str) -> dict[str, Any]:
    doc = _doc(treatment.task_ids[0], source=treatment.source + ctxset.PLACEBO_SUFFIX)
    doc["matched_to"] = treatment.digest
    doc["entries"][0]["text"] = text
    return doc


def _oracle_with(task_id: str, text: str) -> dict[str, Any]:
    doc = _doc(task_id, source="oracle")
    doc["entries"][0]["text"] = text
    return doc


def test_a_matched_placebo_plans(rig: _Rig) -> None:
    treatment = _store(rig.home, _doc(rig.task.task_id, source="oracle"))
    unrelated = ("Rivers and hills. " * 9)[: len(TEXT)]
    placebo = _store(rig.home, _placebo(treatment, unrelated))
    assert rig.plan(context_set=placebo.name).arm_set == placebo.name


def test_a_placebo_whose_treatment_is_not_stored_is_refused(rig: _Rig) -> None:
    treatment = _store(rig.home, _doc(rig.task.task_id, source="oracle"))
    unrelated = ("Rivers and hills. " * 9)[: len(TEXT)]
    placebo = _store(rig.home, _placebo(treatment, unrelated))
    (rig.home / CTXSET_DIR / f"{treatment.digest}.json").unlink()
    with _refused(ctxset.REASON_PLACEBO_UNMATCHED):
        rig.plan(context_set=placebo.name)


def test_a_hand_written_placebo_copying_its_treatment_is_refused(rig: _Rig) -> None:
    named = "The `calc.add` function keeps one operation per module."
    treatment = _store(rig.home, _oracle_with(rig.task.task_id, named))
    placebo = _store(rig.home, _placebo(treatment, named))
    with _refused(ctxset.REASON_PLACEBO_OVERLAP):
        rig.plan(context_set=placebo.name)


def test_a_refused_set_fails_the_run_before_anything_is_built(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_select(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("tasks were selected for a refused context-set run")

    monkeypatch.setattr(rig.worker, "_select_tasks", no_select, raising=False)
    ctx = rig.ctx(context_set="ctx.oracle." + "0" * 12)
    status, _counts, why = rig.worker._run_replay(ctx, mode="blind")
    assert status == STATUS_FAILED and why.startswith(f"{ctxset.REASON_DIGEST}:")
    ((action, kw),) = rig.events
    assert action == "run.refused" and kw["code"] == ctxset.REASON_DIGEST
    assert kw["status"] == StepStatus.ERROR
    assert kw["context_set"] == "ctx.oracle." + "0" * 12


def test_a_context_set_run_never_reserves(rig: _Rig) -> None:
    ctx = rig.ctx(context_set="ctx.oracle." + "0" * 12)
    none = cast(Any, None)
    with pytest.raises(ValueError, match="measurement only"):
        rig.worker._replay_reserver(
            ctx,
            none,
            mode="blind",
            ladder=none,
            budget=none,
            learning=none,
            spend=none,
            container=none,
            preflight=none,
            s1_author=none,
            checks_arm="off",
            ledger=none,
        )


# --- tree_has_at ----------------------------------------------------------------------------


def test_tree_has_at_reads_the_parent_tree_only(rig: _Rig) -> None:
    at_parent = worker_mod.tree_has_at(rig.pyrepo.repo, rig.parent)
    at_commit = worker_mod.tree_has_at(rig.pyrepo.repo, rig.task.task_id)
    assert at_parent("def add") and at_commit("def add")
    # the feat commit introduces subtract: the parent tree does not hold it
    assert not at_parent("def subtract") and at_commit("def subtract")


def test_tree_has_at_raises_on_a_broken_read(rig: _Rig) -> None:
    with pytest.raises(GitError):
        worker_mod.tree_has_at(rig.pyrepo.repo, "0" * 40)("add")
