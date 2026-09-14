"""The worker's ``label`` run kind on the temp SQLite harness: every task lacking an
intent label is labelled through a (scripted) labeller, ``tasks.spec_json`` and the
``capability_class`` column are rewritten with the RESOLVED class, one ``label.task``
event per task carries the label, ``counts_json`` carries the per-class summary with
its n, human labels are never overwritten, and an all-errors run is not a success."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core import classify as c
from crb.core.spec import TaskSpec
from crb.observability.events import StepStatus
from crb.server import worker as worker_mod
from crb.store.jobs import KIND_LABEL, RUN_KINDS, STATUS_FAILED, STATUS_SUCCEEDED
from crb.store.models import Task
from fixtures import pyrepo as pr
from test_worker import Harness


class ScriptedLabeller:
    """Returns the scripted label per call; records exactly what it was shown."""

    def __init__(self, replies: Sequence[tuple[str, float]]) -> None:
        self.replies = list(replies)
        self.seen: list[dict[str, Any]] = []
        self.usage = _Usage()

    @property
    def name(self) -> str:
        return "fake_llm:m@p"

    def describe(self) -> dict[str, Any]:
        return {"labeller": self.name}

    def label(
        self,
        *,
        subject: str,
        message: str,
        diff_stats: Sequence[c.PathStat],
        changed_paths: Sequence[str],
        path_class: str,
    ) -> c.IntentLabel:
        self.seen.append(
            {
                "subject": subject,
                "message": message,
                "diff_stats": [s.to_dict() for s in diff_stats],
                "changed_paths": list(changed_paths),
                "path_class": path_class,
            }
        )
        digest = c.evidence_hash(subject, message, diff_stats, changed_paths, path_class)
        cls, conf = self.replies.pop(0) if self.replies else ("unclassified", 0.0)
        self.usage.calls += 1
        if cls == "ERROR":
            self.usage.errors += 1
            return c.unclassified_label(self.name, reason="model_error: boom", evidence_hash=digest)
        if cls == "LIMIT":
            # the Claude CLI answers a usage-limit with a RESULT event, not a transport error:
            # usage.errors stays 0 but the label is a model_error (2026-09-14, live label runs)
            return c.unclassified_label(
                self.name,
                reason="model_error: success: You've hit your limit",
                evidence_hash=digest,
            )
        return c.parse_label_reply(
            f'{{"class": "{cls}", "confidence": {conf}, "rationale": "scripted"}}',
            labeller=self.name,
            evidence_hash=digest,
        )


class _Usage:
    def __init__(self) -> None:
        self.calls = 0
        self.errors = 0
        self.last: dict[str, Any] = {"cost_usd": 0.001, "latency_s": 0.2}

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "errors": self.errors, "cost_usd": 0.001 * self.calls}


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    """The worker harness of ``test_worker`` with the repo and its one mined task."""
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"labeller": ScriptedLabeller([("feature.add", 0.9)]), "calls": []}

    def fake_make(builder: str, **kw: Any) -> ScriptedLabeller:
        box["calls"].append((builder, kw))
        return box["labeller"]

    monkeypatch.setattr(worker_mod, "make_labeller", fake_make)
    return box


def _second_task(h: Harness, **changes: Any) -> TaskSpec:
    """A second task (the fixture's bad-gold commit), authored AFTER the feat task so the
    worker's oldest-first order is deterministic: feat, then this one."""
    sha = h.pyrepo.add_bad_gold_commit()
    return TaskSpec.from_dict(h.pyrepo.feat_task().to_dict()).with_(
        task_id=sha, gold_clean=False, authored="2030-01-01T00:00:00+00:00", **changes
    )


def _task_row(h: Harness, task_id: str) -> Task:
    with h.factory() as s:
        row = s.get(Task, (pr.REPO_NAME, task_id))
        assert row is not None
        return row


def test_label_kind_is_registered() -> None:
    assert KIND_LABEL == "label" and KIND_LABEL in RUN_KINDS
    assert worker_mod.stage_for("label.task") == "mine"


def test_label_run_labels_every_unlabelled_task_and_rewrites_the_resolved_class(
    h: Harness, scripted: dict[str, Any]
) -> None:
    dirty = _second_task(h, subject="bad gold")  # gold-dirty: classes apply to it too
    h.add_task(dirty)
    scripted["labeller"] = ScriptedLabeller([("feature.add", 0.9), ("refactor", 0.5)])
    run = h.enqueue(
        "label",
        builder="openai_agent",
        model="gpt-oss-120b",
        provider="cerebras",
        params_json={"builder_config": {"temperature": 0}},
    )
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    # the factory was given the run's identity triple + builder_config
    ((builder, kw),) = scripted["calls"]
    assert builder == "openai_agent" and kw["model"] == "gpt-oss-120b"
    assert kw["provider"] == "cerebras" and kw["builder_config"] == {"temperature": 0}
    # what the labeller saw: metadata + stats, never the code
    seen = scripted["labeller"].seen
    # …read from git for each commit (not the stored subject: the second task's record
    # says "bad gold", the commit says otherwise), oldest first
    assert [s["subject"] for s in seen] == [
        "feat: add subtract",
        "feat: add multiply (breaks add)",
    ]
    assert seen[0]["path_class"] == "bug.fix" and pr.SRC in seen[0]["changed_paths"]
    assert "def subtract" not in str(seen)
    # task 1: confident → intent wins; the column AND the spec carry the resolved class
    feat = _task_row(h, h.pyrepo.feat_sha)
    assert feat.capability_class == "feature.add"
    spec = TaskSpec.from_dict(feat.spec_json)
    assert spec.capability_class == "feature.add" and spec.path_class == "bug.fix"
    assert spec.class_source == "intent" and spec.intent is not None
    assert spec.intent.labeller == "fake_llm:m@p" and spec.intent.evidence_hash
    assert (
        spec.intent.evidence_hash
        == c.commit_evidence(h.pyrepo.repo, h.pyrepo.feat_sha, path_class="bug.fix").digest()
    )
    # everything the miner measured is untouched
    before = h.pyrepo.feat_task().to_dict()
    after = spec.to_dict()
    for k in before:
        if k not in {"capability_class", "intent", "class_source"}:
            assert after[k] == before[k], k
    # task 2: below threshold → path stands, label recorded
    bad = _task_row(h, dirty.task_id)
    assert bad.capability_class == "bug.fix"
    bad_spec = TaskSpec.from_dict(bad.spec_json)
    assert bad_spec.intent is not None and bad_spec.intent.intent_class == "refactor"
    assert bad_spec.class_source == "path" and "below threshold" in bad_spec.class_reason
    # counts: per-class summary with n, sources, usage, threshold
    cts = done.counts_json
    assert cts["tasks"] == 2 and cts["total"] == 2 and cts["labelled"] == 2
    assert cts["kept_human"] == 0 and cts["kept_labelled"] == 0 and cts["complete"] is True
    assert cts["labeller"] == "fake_llm:m@p" and cts["min_confidence"] == 0.7
    assert cts["labels"]["classes"] == {"feature.add": 1, "refactor": 1}
    assert cts["labels"]["n"] == 2 and cts["labels"]["unclassified"] == 0
    assert cts["labels"]["mean_confidence"] == 0.7 and cts["labels"]["mean_confidence_n"] == 2
    assert cts["resolved_sources"] == {"intent": 1, "path": 1}
    assert cts["resolved_classes"] == {"bug.fix": 1, "feature.add": 1}
    assert cts["usage"]["calls"] == 2
    assert (done.progress_done, done.progress_total) == (2, 2)
    assert done.apparatus_json["labeller"] == "fake_llm:m@p"
    assert done.apparatus_json["min_confidence"] == 0.7 and "runner" not in done.apparatus_json
    # events: one label.task per task, on the mine stage, carrying the label
    ev = [e for e in h.events(run.id) if e.action == "label.task"]
    assert len(ev) == 2 and all(e.stage == "mine" for e in ev)
    first = next(e for e in ev if e.task_id == h.pyrepo.feat_sha)
    assert first.payload["intent_class"] == "feature.add" and first.payload["confidence"] == 0.9
    assert first.payload["capability_class"] == "feature.add"
    assert first.payload["class_source"] == "intent" and first.payload["changed"] is True
    assert (
        first.payload["previous_class"] == "bug.fix" and first.payload["labeller"] == "fake_llm:m@p"
    )
    assert first.status == StepStatus.OK
    second = next(e for e in ev if e.task_id == dirty.task_id)
    assert second.payload["changed"] is False and second.payload["class_source"] == "path"


def test_label_run_skips_labelled_tasks_unless_relabel_and_never_a_human(
    h: Harness, scripted: dict[str, Any]
) -> None:
    human = h.pyrepo.feat_task().with_(intent=c.human_label("perf", by="reviewer"))
    h.add_task(human)
    model_labelled = _second_task(h, intent=c.IntentLabel("refactor", 0.9, "old", "fake_llm:old"))
    h.add_task(model_labelled)
    # default: nothing to do — one human, one already labelled
    h.enqueue("label", builder="claude_code", model="claude-sonnet-5")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["labelled"] == 0 and done.counts_json["total"] == 0
    assert done.counts_json["kept_human"] == 1 and done.counts_json["kept_labelled"] == 1
    assert scripted["labeller"].seen == []
    # relabel: the model-labelled task is redone; the human's stands, untouched
    scripted["labeller"] = ScriptedLabeller([("behavior.change", 0.95)])
    h.enqueue(
        "label", builder="claude_code", model="claude-sonnet-5", params_json={"relabel": True}
    )
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["labelled"] == 1 and done.counts_json["kept_human"] == 1
    assert TaskSpec.from_dict(_task_row(h, human.task_id).spec_json) == human
    assert _task_row(h, human.task_id).capability_class == "perf"
    redone = TaskSpec.from_dict(_task_row(h, model_labelled.task_id).spec_json)
    assert redone.capability_class == "behavior.change" and redone.intent is not None
    assert redone.intent.labeller == "fake_llm:m@p"


def test_label_run_honours_task_ids_and_limit(h: Harness, scripted: dict[str, Any]) -> None:
    other = _second_task(h)
    h.add_task(other)
    h.enqueue("label", builder="openai_agent", model="m", params_json={"limit": 1})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED and done.counts_json["labelled"] == 1
    assert done.counts_json["total"] == 1  # the limit bounds the run, oldest first
    labelled = [
        t.task_id
        for t in (TaskSpec.from_dict(r.spec_json) for r in h.tasks())
        if t.intent is not None
    ]
    assert labelled == [h.pyrepo.feat_sha]
    scripted["labeller"] = ScriptedLabeller([("perf", 0.8)])
    h.enqueue("label", builder="openai_agent", model="m", params_json={"task_ids": [other.task_id]})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED and done.counts_json["labelled"] == 1
    assert _task_row(h, other.task_id).capability_class == "perf"


def test_label_run_where_every_call_errors_is_failed_not_succeeded(
    h: Harness, scripted: dict[str, Any]
) -> None:
    scripted["labeller"] = ScriptedLabeller([("ERROR", 0.0)])
    run = h.enqueue("label", builder="openai_agent", model="m")
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert "all 1 label call(s) errored: model_error: boom" in done.error
    # the label is still recorded honestly (unclassified, confidence 0) and the path stands
    spec = TaskSpec.from_dict(_task_row(h, h.pyrepo.feat_sha).spec_json)
    assert spec.intent is not None and spec.intent.unclassified
    assert spec.capability_class == "bug.fix" and spec.class_source == "path"
    (ev,) = [e for e in h.events(run.id) if e.action == "label.task"]
    assert ev.status == StepStatus.ERROR
    assert done.counts_json["labels"]["unclassified"] == 1


def test_label_run_needs_a_builder_and_rejects_unknown_ones(h: Harness) -> None:
    h.enqueue("label")
    done = h.run_one()
    assert done.status == STATUS_FAILED and "needs a builder" in done.error
    h.enqueue("label", builder="fixture_gold", model="m")
    done = h.run_one()
    assert done.status == STATUS_FAILED and "no labeller for builder" in done.error


def test_label_run_cancel_between_tasks_keeps_partial_counts(
    h: Harness, scripted: dict[str, Any]
) -> None:
    h.add_task(_second_task(h))

    class CancellingLabeller(ScriptedLabeller):
        def label(self, **kw: Any) -> c.IntentLabel:
            out = super().label(**kw)
            h.queue.request_cancel(run.id)
            return out

    scripted["labeller"] = CancellingLabeller([("feature.add", 0.9), ("perf", 0.9)])
    run = h.enqueue("label", builder="openai_agent", model="m")
    done = h.run_one()
    assert done.status == "cancelled" and done.counts_json["labelled"] == 1
    assert done.counts_json["complete"] is False
    with h.factory() as s:
        n_labelled = sum(
            1
            for r in s.execute(select(Task)).scalars().all()
            if TaskSpec.from_dict(r.spec_json).intent is not None
        )
    assert n_labelled == 1


def test_label_run_whose_labels_are_all_outage_text_is_failed_and_relabels_without_relabel(
    h: Harness, scripted: dict[str, Any]
) -> None:
    """Three live label runs 'succeeded' with every label reading the CLI's usage-limit
    text (usage.errors == 0). An outage is not a label: the run fails, and the next run
    re-labels those tasks without ``relabel``."""
    scripted["labeller"] = ScriptedLabeller([("LIMIT", 0.0)])
    h.enqueue("label", builder="openai_agent", model="m")
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert "errored" in done.error and "hit your limit" in done.error
    assert done.counts_json["errors"] == 1
    scripted["labeller"] = ScriptedLabeller([("feature.add", 0.9)])
    h.enqueue("label", builder="openai_agent", model="m")  # no relabel flag
    done2 = h.run_one()
    assert done2.status != STATUS_FAILED
    assert done2.counts_json["kept_labelled"] == 0 and done2.counts_json["labelled"] == 1
    spec = TaskSpec.from_dict(_task_row(h, h.pyrepo.feat_sha).spec_json)
    assert spec.capability_class == "feature.add" and spec.class_source != "path"
