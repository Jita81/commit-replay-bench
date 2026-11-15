"""A stated-requirement entry through the real build closure (ADR-0052 items 3 and 5).

Navigation
----------
What it is:   The tests that a ``ctx.req*`` run's entry reaches the brief only through
              ``req_guard`` against the harness-side gold view the closure computes, and that
              every context-set row carries the builder's ``ctx_turns``.
What it does: Builds a v2 set over the pyrepo ``feat: add subtract`` commit, runs the closure
              with the ``ctxfake`` builder of tests/test_adapter_ctx.py, and checks the brief,
              the stamps and ``ctx_label_violation``.
How:          ``ctxset.parse`` of ``fixtures.ctx_rows.req_doc``; the ``ContextEntry`` built as
              ``crb.server.worker._ctx_plan`` builds it; ``adapter.build_fn_for``.
Layer:        tests — docs/ARCHITECTURE.md#45-c4-level-3--crbbuilders
ADRs:         docs/adr/0052-stated-requirement-arms.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/builders/adapter.py (under test), src/crb/builders/brief.py
              (``req_guard``, ``gold_view``), tests/test_adapter_ctx.py (the fake builder)
Tested by:    tests/test_adapter_req.py
Touch when:   never for a new repository; the closure's gold view or ctx stamps change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.builders import adapter
from crb.builders.base import Budget
from crb.builders.brief import LABEL_CONTEXT_ARM, ContextEntry
from crb.core import context_arm as ca
from crb.core import ctxset
from crb.core import stated as st
from crb.core.ledger import ctx_label_violation
from fixtures import pyrepo as pr
from fixtures.ctx_rows import req_doc
from test_adapter_ctx import CtxFakeBuilder, _ladder, _register, harness  # noqa: F401

SAFE = "The calculator keeps the existing add function working unchanged"
LEAK = "Add a subtract function beside add"


def _run(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811 - the fixture
    *,
    statement: str,
    provenance: str = st.PROV_NOWHERE,
    discloses: list[str] | None = None,
    control: bool = False,
) -> Any:
    task = pyrepo.feat_task()
    doc = req_doc(tasks=[task.task_id], statement=statement, provenance=provenance)
    doc["entries"][0]["items"][0]["discloses"] = sorted(discloses or [])
    cset = ctxset.parse(doc)
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
            items=e.items,
            structure=cset.structure,
        )
    }
    fn = adapter.build_fn_for(
        _ladder(),
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


def test_a_guard_clean_stated_entry_is_delivered_and_stamped(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
) -> None:
    attempt, text = _run(pyrepo, tmp_path, harness, statement=SAFE)
    (brief,) = CtxFakeBuilder.briefs
    assert text in brief.spec_facts
    labels = attempt.labels
    assert labels[ca.LABEL_CTX_DELIVERED] == "1"
    assert labels[ca.LABEL_CTX_STATED] == "1"
    assert ca.LABEL_CTX_REQ_REFUSED not in labels
    assert labels[ca.LABEL_CTX_TURNS] == str(Budget().max_turns)
    assert ctx_label_violation(labels[LABEL_CONTEXT_ARM], labels) == ""


def test_an_undeclared_answer_is_withheld_with_the_guards_reason(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
) -> None:
    attempt, text = _run(pyrepo, tmp_path, harness, statement=LEAK)
    (brief,) = CtxFakeBuilder.briefs
    assert text not in brief.spec_facts and text not in brief.task_text()
    labels = attempt.labels
    assert labels[ca.LABEL_CTX_DELIVERED] == "0"
    assert st.REASON_UNDECLARED_NOVEL in labels[ca.LABEL_CTX_REQ_REFUSED].split(",")
    assert ctx_label_violation(labels[LABEL_CONTEXT_ARM], labels) == ""


@pytest.mark.parametrize(
    ("provenance", "delivered"),
    [(st.PROV_CHANGE_DETAIL, "1"), (st.PROV_NOWHERE, "0"), (st.PROV_TESTS_ONLY, "0")],
)
def test_a_declared_answer_is_delivered_only_at_its_true_provenance(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
    provenance: str,
    delivered: str,
) -> None:
    """``subtract`` is in the commit's source post-image, not the parent: change_detail."""
    attempt, _ = _run(
        pyrepo, tmp_path, harness, statement=LEAK, provenance=provenance, discloses=["subtract"]
    )
    assert attempt.labels[ca.LABEL_CTX_DELIVERED] == delivered
    if delivered == "0":
        assert st.REASON_PROVENANCE in attempt.labels[ca.LABEL_CTX_REQ_REFUSED]


def test_a_control_row_carries_turns_and_no_stated_stamp(
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    harness: dict[str, Any],  # noqa: F811
) -> None:
    attempt, text = _run(pyrepo, tmp_path, harness, statement=SAFE, control=True)
    (brief,) = CtxFakeBuilder.briefs
    assert text not in brief.spec_facts
    labels = attempt.labels
    assert labels[LABEL_CONTEXT_ARM] == "A0"
    assert labels[ca.LABEL_CTX_TURNS] == str(Budget().max_turns)
    assert ca.LABEL_CTX_STATED not in labels
    assert ctx_label_violation("A0", labels) == ""
