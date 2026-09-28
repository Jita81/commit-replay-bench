"""Test helpers for registered readings (ADR-0026 items 2 to 6): sealed 2.4 rows, a reading.

Navigation
----------
What it is:   Builders for the rows and readings the routing.v2 tests read: a row of apparatus
              2.4 graded in the sealed posture on one full cell, and a reading registered over
              a pool of commits.
What it does: ``sealed_row`` stamps the posture class ``docker/copy/sealed``, the builder's
              sealed container, rung ``r1``, a context arm, the class-set version and a
              change id, with a ``created`` time after the registration; ``register_reading``
              registers a hierarchy over a pool at a fixed time; ``commits`` makes shas.
How:          Thin wrappers over ``tests.fixtures.posture.posture_row`` and
              ``crb.core.reading.register``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md, docs/adr/0025-routing-v2.md
Works with:   src/crb/core/reading.py (``register`` — the readings built here),
              src/crb/core/ledger.py (the sealed 2.4 rows the ledger admits),
              tests/fixtures/posture.py (``posture_row`` — the labels a 2.4 row carries)
Tested by:    tests/test_reading.py, tests/test_routing_v2.py, tests/test_signoff_v5.py
Touch when:   the sealed posture's labels or the reading's shape change.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any

from crb.core.capability import ReadingBook
from crb.core.context_arm import parse_arm
from crb.core.ledger import GradeRow
from crb.core.reading import RULE_LOOK_V1, Reading, register
from crb.core.routing import ControlsVerdict
from crb.core.taxonomy import GLOBAL_CLASS_SET
from fixtures.posture import posture_row

REPO = "cobra"
SEALED = "docker/copy/sealed"
REGISTERED_AT = "2026-09-27T10:00:00+00:00"
AFTER = "2026-09-27T11:00:00+00:00"
BEFORE = "2026-09-27T09:00:00+00:00"
CELL = {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "XS",
    "language": "go",
    "builder": "claude_code",
    "model": "claude-sonnet-5",
    "provider": "anthropic",
}
AUTHOR = "claude-opus-5"
S1 = f"S1@{AUTHOR}"


def commits(n: int, prefix: str = "c") -> list[str]:
    """``n`` distinct 40-hex shas, stable for a prefix."""
    return [hashlib.sha1(f"{prefix}{i}".encode()).hexdigest() for i in range(n)]


def sealed_row(
    commit: str,
    *,
    clean: bool = True,
    arm: str = "S3",
    created: str = AFTER,
    trial: str = "r1",
    change: str = "",
    posture_class: str = SEALED,
    builder_executor: str = "docker",
    error: str = "",
    labels: dict[str, str] | None = None,
    repo: str = REPO,
    cell: dict[str, str] | None = None,
    **kw: Any,
) -> GradeRow:
    """A row of apparatus 2.4 on :data:`CELL`, graded in the sealed posture by default."""
    fields: dict[str, Any] = {
        "repo": repo,
        "task_id": commit,
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean and not error,
        "no_new_failures": True,
        "source_changed": True,
        "repo_lint_clean": None,
        "evidence_pack_hash": "h" * 64 if clean else "",
        "apparatus_version": "2.4",
        "created": created,
        "trial": trial,
        "error": error,
        "mode": "blind" if arm.startswith("A0") else "sighted",
        **(cell or CELL),
        **kw,
    }
    if error:
        fields["target_green"] = None
        fields["no_new_failures"] = None
        fields["source_changed"] = None
    return posture_row(
        **fields,
        labels={
            "posture_class": posture_class,
            "builder_executor": builder_executor,
            "context_arm": arm,
            "taxonomy": GLOBAL_CLASS_SET,
            "change_id": change or f"change-{commit}",
            **(labels or {}),
        },
    )


def rows_for(
    outcomes: Sequence[bool | None], pool: Sequence[str], *, arm: str = "S3", **kw: Any
) -> list[GradeRow]:
    """One first attempt per pool commit, in pool order: ``True`` clean, ``False`` a miss,
    ``None`` no row yet (pending)."""
    return [
        sealed_row(c, clean=o, arm=arm, **kw)
        for c, o in zip(pool, outcomes, strict=False)
        if o is not None
    ]


def register_reading(
    pool: Iterable[str],
    *,
    hierarchy: Sequence[str] = ("S3", S1),
    rule: str = RULE_LOOK_V1,
    existing: Iterable[Reading] = (),
    rows: Iterable[GradeRow] = (),
    descriptive: Sequence[tuple[str, int]] = (),
    now: str = REGISTERED_AT,
    budget: float | None = None,
    changes: dict[str, str] | None = None,
    repo: str = REPO,
    cell: dict[str, str] | None = None,
) -> Reading:
    """A reading of :data:`CELL` on :data:`REPO`, registered at :data:`REGISTERED_AT`."""
    return register(
        repo=repo,
        cell=cell or CELL,
        hierarchy=hierarchy,
        pool=list(pool),
        apparatus="2.4",
        taxonomy=GLOBAL_CLASS_SET,
        posture_class=SEALED,
        checks_arm="off",
        actor="op-1",
        existing=existing,
        rows=rows,
        rule=rule,
        descriptive=descriptive,
        author_model=AUTHOR if any(a.startswith("S1@") for a in hierarchy) else "",
        now=now,
        budget=budget,
        changes=changes,
    )


# --- a proven world for any rows (routing.v2 for tests of what reads the map) ---------------

#: A complete, passing controls report at apparatus 2.4.
LIVE_PASSED = ControlsVerdict(
    passed=True, constructible=56, total=56, escapes=0, run_id="c" * 32, apparatus_version="2.4"
)


def live_labels(task_id: str, *, arm: str = S1) -> dict[str, Any]:
    """The ``GradeRow`` keyword arguments that make a measured row of 2.4 one a reading counts:
    sealed, rung ``r1``, graded after :data:`REGISTERED_AT`, on ``arm``, its own change."""
    return {
        "created": AFTER,
        "trial": "r1",
        "labels": {
            "posture_class": SEALED,
            "builder_executor": "docker",
            "context_arm": arm,
            "taxonomy": GLOBAL_CLASS_SET,
            "change_id": f"change-{task_id}",
        },
    }


def book_for(rows: Sequence[GradeRow], *, arm: str = S1) -> ReadingBook:
    """One reading per full cell of the stamped 2.4 rows, registered at :data:`REGISTERED_AT`
    over the cell's commits, with ``arm`` alone in its hierarchy."""
    groups: dict[tuple[str, Any], list[str]] = {}
    for r in rows:
        if r.context_arm == arm and r.apparatus_version == "2.4":
            groups.setdefault((r.repo, r.cell), []).append(r.task_id)
    readings = [
        register(
            repo=repo,
            cell=cell.to_dict(),
            hierarchy=(arm,),
            pool=list(dict.fromkeys(ids)),
            apparatus="2.4",
            taxonomy=GLOBAL_CLASS_SET,
            posture_class=SEALED,
            checks_arm="off",
            actor="op-1",
            author_model=parse_arm(arm).author,
            now=REGISTERED_AT,
        )
        for (repo, cell), ids in groups.items()
    ]
    return ReadingBook.evaluate(readings, rows)


def world_for(
    rows: Sequence[GradeRow], *, oracle: float | None = 0.9, controls: ControlsVerdict | None = None
) -> dict[str, Any]:
    """The readings, per-task oracle and controls a proven cell of ``rows`` is routed under."""
    return {
        "readings": book_for(rows),
        "oracle_by_task": {} if oracle is None else {r.task_id: oracle for r in rows},
        "controls": controls or LIVE_PASSED,
    }
