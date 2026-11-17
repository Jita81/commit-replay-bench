"""An accepted-plan entry through the real build closure (ADR-0054).

Navigation
----------
What it is:   The tests that a ``ctx.plan*`` run's entry reaches the brief's own plan block
              only through ``plan_guard`` against the harness-side gold view the closure
              computes, and that its row carries the plan stamps the ledger accepts.
What it does: Builds a v3 set over the pyrepo ``feat: add subtract`` commit, drafted at the
              commit's parent; runs the closure with the ``ctxfake`` builder of
              tests/test_adapter_ctx.py; and checks the brief, the stamps and
              ``ctx_label_violation`` for a clean plan, a plan naming the held-out test file
              (withheld whole) and the control role (nothing delivered).
How:          ``ctxset.parse`` of ``fixtures.ctx_rows.plan_doc``; the ``ContextEntry`` built as
              ``crb.server.worker._ctx_plan`` builds it; ``adapter.build_fn_for``.
Layer:        tests — docs/ARCHITECTURE.md#45-c4-level-3--crbbuilders
ADRs:         docs/adr/0054-accepted-plan-context-arm.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/builders/adapter.py (under test), src/crb/builders/brief.py
              (``plan_guard``, ``gold_view``), tests/test_adapter_ctx.py (the fake builder),
              tests/test_adapter_req.py (the stated entry's own closure tests)
Tested by:    tests/test_adapter_plan.py
Touch when:   never for a new repository; the closure's gold view, the plan block or the plan
              stamps change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crb.builders import adapter
from crb.builders.base import Budget
from crb.builders.brief import LABEL_CONTEXT_ARM, ContextEntry
from crb.core import context_arm as ca
from crb.core import ctxset
from crb.core import plan as p
from crb.core.ledger import ctx_label_violation
from fixtures import pyrepo as pr
from fixtures.ctx_rows import PLAN, plan_doc
from test_adapter_ctx import CtxFakeBuilder, _ladder, _register, harness  # noqa: F401

CLEAN = {
    **PLAN,
    "summary": ["Add the missing arithmetic operation to the calculator"],
    "files": [pr.SRC],
    "steps": ["Add the new operation beside the existing one", "Keep add unchanged"],
    "tests": ["Cover the new operation with a unit test"],
}
LEAKY = {**CLEAN, "tests": [f"Extend {pr.TEST_SUBTRACT}"]}


def _run(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811 - the fixture
    *,
    plan: dict[str, Any],
    control: bool = False,
) -> Any:
    task = pyrepo.feat_task()
    parent = pyrepo.repo.parent(task.task_id)
    cset = ctxset.parse(plan_doc(tasks=[task.task_id], plan=plan, source_rev=parent))
    role = ctxset.ROLE_CONTROL if control else ctxset.ROLE_ENTRIES
    stamps = ctxset.run_stamps(cset, role, {task.task_id: "0"})
    (e,) = cset.entries
    entries = {
        task.task_id: ContextEntry(
            entry_id=e.entry_id,
            text=e.text,
            version=e.version,
            produced_at=e.produced_at,
            mechanical=e.mechanical,
            source_rev=e.source_rev,
            plan=e.plan,
        )
    }
    fn = adapter.build_fn_for(
        _ladder("noop"),
        budget=Budget(),
        context_set="" if control else cset.name,
        ctx_entries=None if control else entries,
        ctx_stamps=stamps,
        **harness,
    )
    ws = pyrepo.trial(tmp_path / "t", overlay_tests=False)
    try:
        return fn(ws, task, "blind", "ctxfake:m0"), e.text
    finally:
        ws.remove()


def test_a_guard_clean_plan_reaches_the_plan_block_and_is_stamped(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
) -> None:
    attempt, text = _run(pyrepo, tmp_path, harness, plan=CLEAN)
    assert text.startswith(p.PLAN_HEADER)
    (brief,) = CtxFakeBuilder.briefs
    assert brief.plan == text and text in brief.task_text()
    assert text not in brief.spec_facts
    labels = attempt.labels
    assert labels[ca.LABEL_CTX_DELIVERED] == "1"
    assert labels[ca.LABEL_CTX_PLAN_SAW] == "ticket,tree"
    assert labels[ca.LABEL_CTX_PLAN_NOVEL].isdecimal()
    assert ca.LABEL_CTX_PLAN_REFUSED not in labels
    assert ctx_label_violation(labels[LABEL_CONTEXT_ARM], labels) == ""


def test_a_plan_naming_the_held_out_test_file_is_withheld_whole(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
) -> None:
    attempt, _ = _run(pyrepo, tmp_path, harness, plan=LEAKY)
    (brief,) = CtxFakeBuilder.briefs
    assert brief.plan == ""
    assert "Keep add unchanged" not in brief.task_text()
    labels = attempt.labels
    assert labels[ca.LABEL_CTX_DELIVERED] == "0"
    assert p.REASON_TEST_PATH in labels[ca.LABEL_CTX_PLAN_REFUSED].split(",")
    assert ctx_label_violation(labels[LABEL_CONTEXT_ARM], labels) == ""


def test_a_control_row_carries_no_plan_and_no_plan_stamp(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
) -> None:
    attempt, _ = _run(pyrepo, tmp_path, harness, plan=CLEAN, control=True)
    (brief,) = CtxFakeBuilder.briefs
    assert brief.plan == ""
    labels = attempt.labels
    assert labels[LABEL_CONTEXT_ARM] == "A0"
    assert not any(k.startswith("ctx_plan_") for k in labels)
    assert ctx_label_violation("A0", labels) == ""
