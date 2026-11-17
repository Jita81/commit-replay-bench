"""Context-set fixtures: a parsed set and the ledger rows a run of it writes (ADR-0050).

Navigation
----------
What it is:   Builders for a ``crb.ctxset.v1`` document (a ``crb.ctxset.v2``
              stated-requirement one, ADR-0052, and a ``crb.ctxset.v3`` accepted-plan one,
              ADR-0054), its parsed ``CtxSet`` and the grade
              rows a context-set run or its control writes, each stamped as
              ``crb.core.ctxset.run_stamps`` stamps it.
What it does: Keeps every ctx test's rows valid under ``ctx_label_violation`` (the ledger's
              own check) so a test exercises the reader, not a malformed row.
How:          ``ctx_doc`` → ``ctxset.parse``; ``ctx_row`` = ``posture_row`` at the current
              apparatus, blind, sealed (``builder_executor`` ``docker``) unless overridden.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctxset.py (``parse``, ``run_stamps``), src/crb/core/ledger.py
              (``ctx_label_violation``), tests/fixtures/posture.py (``posture_row``)
Tested by:    tests/test_ctx_compare.py, tests/test_server_ctxsets.py, tests/test_value_ctx.py,
              tests/test_capability_ctx.py
Touch when:   never for a new repository; the set record or the ctx stamps change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from crb.core import ctxset
from crb.core.context_arm import (
    LABEL_CONTEXT_ARM,
    LABEL_CTX_CHARS,
    LABEL_CTX_DELIVERED,
)
from crb.core.ledger import GradeRow, expected_belt_sets
from crb.core.version import APPARATUS_VERSION
from fixtures.posture import posture_row

REPO = "cobra"
TASKS: tuple[str, ...] = tuple(f"{i:040x}" for i in range(1, 7))
PACK = "b" * 64


def ctx_doc(
    source: str = ctxset.SOURCE_ORACLE,
    *,
    tasks: Sequence[str] = TASKS,
    text: str = "The handler in cmd/root.go reads the flag before parsing.",
    texts: Mapping[str, str] | None = None,
    matched_to: str = "",
    repo: str = REPO,
) -> dict[str, Any]:
    """A valid set document (sorted entries; a placebo names ``matched_to``)."""
    doc: dict[str, Any] = {
        "schema": ctxset.SCHEMA,
        "source": source,
        "repo": repo,
        "method": "fixture",
        "entries": [
            {
                "task_id": t,
                "entry_id": f"brief/{t[-6:]}",
                "version": "1",
                "text": (texts or {}).get(t, text),
                "produced_at": "2026-11-01T00:00:00Z",
                "mechanical": False,
            }
            for t in sorted(tasks)
        ],
    }
    if matched_to:
        doc["matched_to"] = matched_to
    return doc


def ctx_set(source: str = ctxset.SOURCE_ORACLE, **kw: Any) -> ctxset.CtxSet:
    return ctxset.parse(ctx_doc(source, **kw))


def req_doc(
    source: str = ctxset.SOURCE_REQ,
    *,
    structure: str = "prose",
    tasks: Sequence[str] = TASKS,
    statement: str = "The command keeps its existing flags working unchanged",
    provenance: str = "nowhere",
    statements: Mapping[str, str] | None = None,
    matched_to: str = "",
    repo: str = REPO,
) -> dict[str, Any]:
    """A valid ``crb.ctxset.v2`` stated-requirement document (ADR-0052): one item per task."""
    doc: dict[str, Any] = {
        "schema": ctxset.SCHEMA_V2,
        "source": source,
        "repo": repo,
        "method": "fixture",
        "structure": structure,
        "drafter": "human:fixture-01",
        "saw": ["diff", "tests"],
        "entries": [
            {
                "task_id": t,
                "entry_id": f"req/{t[-6:]}",
                "version": "1",
                "produced_at": "2026-11-01T00:00:00Z",
                "items": [
                    {
                        "item_id": "i01",
                        "kind": "rule",
                        "statement": (statements or {}).get(t, statement),
                        "provenance": provenance,
                        "discloses": [],
                    }
                ],
            }
            for t in sorted(tasks)
        ],
    }
    if matched_to:
        doc["matched_to"] = matched_to
    return doc


def req_set(source: str = ctxset.SOURCE_REQ, **kw: Any) -> ctxset.CtxSet:
    return ctxset.parse(req_doc(source, **kw))


#: The plan body ``plan_doc`` gives every entry unless told otherwise (ADR-0054).
PLAN: dict[str, list[str]] = {
    "summary": ["Refuse an empty name before the command runs"],
    "files": ["cmd/root.go"],
    "steps": ["Check the name where the flags are parsed", "Return an error for an empty name"],
    "decisions": ["Existing flags keep working unchanged"],
    "tests": ["Add a test that an empty name is refused"],
}
PLAN_PARENT = "f" * 40


def plan_doc(
    *,
    tasks: Sequence[str] = TASKS,
    plan: Mapping[str, Sequence[str]] | None = None,
    plans: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    source_rev: str = PLAN_PARENT,
    source_revs: Mapping[str, str] | None = None,
    saw: Sequence[str] = ("ticket", "tree"),
    accepted_by: str = "human:fixture-01",
    drafter: str = "human:fixture-01",
    repo: str = REPO,
) -> dict[str, Any]:
    """A valid ``crb.ctxset.v3`` accepted-plan document (ADR-0054): one plan per task."""
    return {
        "schema": ctxset.SCHEMA_V3,
        "source": ctxset.SOURCE_PLAN,
        "repo": repo,
        "method": "fixture",
        "drafter": drafter,
        "saw": list(saw),
        "accepted_by": accepted_by,
        "entries": [
            {
                "task_id": t,
                "entry_id": f"plan/{t[-6:]}",
                "version": "1",
                "produced_at": "2026-11-01T00:00:00Z",
                "source_rev": (source_revs or {}).get(t, source_rev),
                "plan": {k: list(v) for k, v in ((plans or {}).get(t) or plan or PLAN).items()},
            }
            for t in sorted(tasks)
        ],
    }


def plan_set(**kw: Any) -> ctxset.CtxSet:
    return ctxset.parse(plan_doc(**kw))


def ctx_row(
    cset: ctxset.CtxSet,
    task_id: str,
    *,
    clean: bool,
    role: str = ctxset.ROLE_ENTRIES,
    gap: str = "1",
    delivered: int = 1,
    chars: int = 100,
    run_id: str = "",
    labels: Mapping[str, str] | None = None,
    **kw: Any,
) -> GradeRow:
    """One first-attempt row of ``task_id`` on the set's arm (``role`` entries) or its
    control (``role`` control, arm ``A0``), stamped as the run stamps it."""
    stamps = dict(ctxset.run_stamps(cset, role, dict.fromkeys(cset.task_ids, gap))[task_id])
    if role == ctxset.ROLE_ENTRIES:
        stamps[LABEL_CTX_DELIVERED] = str(delivered)
        stamps[LABEL_CTX_CHARS] = str(chars if delivered else 0)
    stamps[LABEL_CONTEXT_ARM] = cset.arm if role == ctxset.ROLE_ENTRIES else "A0"
    stamps.setdefault("builder_executor", "docker")
    stamps.update(labels or {})
    base: dict[str, Any] = {
        "repo": cset.repo,
        "task_id": task_id,
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean,
        "no_new_failures": True if clean else None,
        "source_changed": True if clean else None,
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "go",
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "mode": "blind",
        "gold_clean": True,
        "cost_usd": 0.1,
        "latency_s": 30.0,
        "apparatus_version": APPARATUS_VERSION,
        "run_id": run_id,
        "labels": stamps,
    }
    if clean:
        base["evidence_pack_hash"] = PACK
    base.update(kw)
    base.setdefault(
        "belt_set", (expected_belt_sets(base["apparatus_version"], "measured") or ("v5",))[0]
    )
    return posture_row(**base)


def side(
    cset: ctxset.CtxSet,
    outcomes: Mapping[str, bool],
    *,
    role: str = ctxset.ROLE_ENTRIES,
    **kw: Any,
) -> list[GradeRow]:
    """One row per task in ``outcomes`` (task → clean)."""
    return [ctx_row(cset, t, clean=c, role=role, **kw) for t, c in outcomes.items()]


__all__ = [
    "PACK",
    "PLAN",
    "PLAN_PARENT",
    "REPO",
    "TASKS",
    "ctx_doc",
    "ctx_row",
    "ctx_set",
    "plan_doc",
    "plan_set",
    "req_doc",
    "req_set",
    "side",
]
