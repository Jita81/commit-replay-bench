"""Context-set fixtures: a parsed set and the ledger rows a run of it writes (ADR-0050).

Navigation
----------
What it is:   Builders for a ``crb.ctxset.v1`` document, its parsed ``CtxSet`` and the grade
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


__all__ = ["PACK", "REPO", "TASKS", "ctx_doc", "ctx_row", "ctx_set", "side"]
