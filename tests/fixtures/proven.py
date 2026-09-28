"""A cell proven under routing.v2 in a seeded store: tasks, a reading, sealed rows, oracle.

Navigation
----------
What it is:   The store-side builder of a cell whose standard arm delivers under routing.v2 —
              what the server tests of the map, ``/routes``, ``/readings``, ``/value`` and the
              sign-off write path read.
What it does: ``add_tasks`` writes qualified tasks (gold checked, a change id each) of one cell;
              ``register_via_api`` registers a reading through ``POST /readings`` and
              ``write_reading`` writes the same event for a role that may not register;
              ``add_rows`` appends sealed 2.4 rows for the first commits of the reading's
              seeded order on each arm; ``add_oracle_and_controls`` writes ``mutation.v2``
              scores and a complete controls report at 2.4 as events.
How:          ``Task`` rows and ``DbLedger.append_many``; ``append_event`` for the scores and the
              report; rows are stamped a far-future ``created`` so they are graded after any
              registration a test makes.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md
Works with:   tests/fixtures/server_seed.py (the store it adds to), tests/fixtures/readings.py
              (the sealed rows), src/crb/server/routes/readings.py (``POST /readings``)
Tested by:    tests/test_server_readings.py
Touch when:   never for a new repository; the sealed posture's labels, the score payload or the
              report payload change.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import canonical_json, sha256_text
from crb.core.ledger import GradeRow
from crb.core.reading import READING_EVENT_ACTION, RULE_LOOK_V1, Reading, register
from crb.core.spec import TaskSpec
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.core.version import APPARATUS_VERSION
from crb.store.events import append_event
from crb.store.ledger import DbLedger
from crb.store.models import EvidencePackRow, Task
from fixtures.readings import SEALED, sealed_row
from fixtures.server_seed import ALPHA, BUILDER, MODEL, PROVIDER, Env

#: A cell the default seed does not hold (the seed's deliver cell is bug.fix × S).
CELL: dict[str, str] = {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "XS",
    "language": "python",
    "builder": BUILDER,
    "model": MODEL,
    "provider": PROVIDER,
}
AUTHOR = "claude-opus-5"
S1 = f"S1@{AUTHOR}"
#: Rows are graded "after" any registration a test makes.
LATER = "2099-01-01T00:00:00+00:00"


def commit(i: int, prefix: str = "proven") -> str:
    return hashlib.sha1(f"{prefix}-{i}".encode()).hexdigest()


def add_tasks(
    factory: sessionmaker[Session],
    n: int = 40,
    *,
    prefix: str = "proven",
    cell: Mapping[str, str] = CELL,
    authored: str = "2026-08-01T12:00:00+00:00",
) -> list[str]:
    """``n`` qualified tasks of ``cell`` (default :data:`CELL`) on ``alpha``, each its own
    change, authored at ``authored``."""
    ids = [commit(i, prefix) for i in range(n)]
    cls, size, language = cell["capability_class"], cell["size"], cell["language"]
    with factory() as s:
        for i, tid in enumerate(ids):
            spec = TaskSpec(
                task_id=tid,
                repo=ALPHA,
                subject=f"fix: proven {i}",
                authored=authored,
                test_files=(f"tests/test_p{i}.py",),
                src_files=(f"src/pkg/p{i}.py",),
                target_tests=(f"tests/test_p{i}.py",),
                belt_scope=("tests/",),
                size=size,
                src_churn=3,
                capability_class=cls,
                language=language,
                red_checked=True,
                gold_clean=True,
                labels={"change_id": f"change-{prefix}-{i}"},
            )
            s.add(
                Task(
                    repo=ALPHA,
                    task_id=tid,
                    pool=spec.pool,
                    size=spec.size,
                    capability_class=spec.capability_class,
                    language=spec.language,
                    authored=spec.authored,
                    subject=spec.subject,
                    red_checked=True,
                    gold_clean=True,
                    spec_json=spec.to_dict(),
                )
            )
        s.commit()
    return ids


def register_via_api(env: Env, *, hierarchy: Sequence[str] = ("S3", S1), **kw: Any) -> Any:
    """``POST /readings`` for :data:`CELL` in the sealed posture class."""
    body = {
        "repo": ALPHA,
        "cell": CELL,
        "hierarchy": list(hierarchy),
        "posture_class": SEALED,
        "author_model": AUTHOR if any(a.startswith("S1@") for a in hierarchy) else "",
        **kw,
    }
    return env.post("/readings", json=body)


def add_rows(
    factory: sessionmaker[Session],
    commits: Sequence[str],
    *,
    arm: str,
    clean: bool = True,
    labels: dict[str, str] | None = None,
    cell: Mapping[str, str] = CELL,
    **kw: Any,
) -> list[GradeRow]:
    """One sealed 2.4 first attempt per commit on ``arm`` in ``cell``; the chained rows. A
    clean row's evidence pack is STORED and re-hashes to its name, as the worker keeps it
    (EI-3): a row measured here is never clean without the pack an approver reads."""
    rows: list[GradeRow] = []
    packs: list[tuple[str, dict[str, Any], str]] = []
    for c in commits:
        extra = dict(kw)
        if clean and "evidence_pack_hash" not in extra:
            body = {"schema": "crb.fixture.pack.v1", "task_id": c, "arm": arm, "repo": ALPHA}
            extra["evidence_pack_hash"] = sha256_text(canonical_json(body))
            packs.append((extra["evidence_pack_hash"], body, c))
        rows.append(
            sealed_row(
                c,
                clean=clean,
                arm=arm,
                created=LATER,
                repo=ALPHA,
                cell=dict(cell),
                change=f"change-{c}",
                labels=labels,
                **extra,
            )
        )
    with factory() as s:
        for pack_hash, body, task_id in packs:
            if s.get(EvidencePackRow, pack_hash) is None:
                s.add(
                    EvidencePackRow(
                        pack_hash=pack_hash, repo=ALPHA, task_id=task_id, run_id="", body_json=body
                    )
                )
        s.commit()
    return DbLedger(factory).append_many(rows)


def write_reading(
    factory: sessionmaker[Session],
    pool: Sequence[str],
    *,
    cell: Mapping[str, str] = CELL,
    hierarchy: Sequence[str] = (S1,),
    changes: Mapping[str, str] | None = None,
) -> Reading:
    """Register a reading of ``cell`` on ``alpha`` with the core's rules and write it as the
    ``reading.registered`` event ``POST /readings`` writes — for a test logged in as a role
    that may not register one itself (a sign-off test's approver)."""
    reading = register(
        repo=ALPHA,
        cell=dict(cell),
        hierarchy=hierarchy,
        pool=list(pool),
        apparatus=APPARATUS_VERSION,
        taxonomy=GLOBAL_CLASS_SET,
        posture_class=SEALED,
        checks_arm="off",
        actor="op-seed",
        rule=RULE_LOOK_V1,
        author_model=AUTHOR if any(a.startswith("S1@") for a in hierarchy) else "",
        changes=dict(changes or {}),
    )
    append_event(
        factory,
        trace_id=f"readings:{ALPHA}",
        stage="system",
        action=READING_EVENT_ACTION,
        repo=ALPHA,
        payload=reading.to_dict(),
    )
    return reading


def add_oracle(
    factory: sessionmaker[Session], commits: Sequence[str], *, strength: float = 0.9
) -> None:
    """``mutation.v2`` scores at 2.4 for ``commits``."""
    for c in commits:
        append_event(
            factory,
            trace_id="oracle-proven",
            stage="oracle",
            action="oracle.score",
            repo=ALPHA,
            task_id=c,
            payload={
                "task_id": c,
                "oracle_strength": strength,
                "total": 10,
                "killed": round(strength * 10),
                "provenance": {"apparatus_version": "2.4", "mutation_version": "mutation.v2"},
            },
        )


def add_oracle_and_controls(
    factory: sessionmaker[Session], commits: Sequence[str], *, strength: float = 0.9
) -> None:
    """``mutation.v2`` scores at 2.4 for ``commits`` and a complete, passing controls report."""
    add_oracle(factory, commits, strength=strength)
    append_event(
        factory,
        trace_id="controls-proven",
        stage="oracle",
        action="controls.report",
        repo=ALPHA,
        payload={
            "passed": True,
            "n_rows": 7,
            "skipped": 0,
            "not_constructible": 1,
            "escapes": 0,
            "apparatus": {"apparatus_version": "2.4", "complete": True},
        },
    )
