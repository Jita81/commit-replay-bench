"""Sign-off helpers on top of :mod:`fixtures.server_seed` for ``signoff-policy.v1``.

The seed's controls report carries ONE escape by design, so its deliver cell
(``bug.fix|S``, n = 40, point 0.95) is REFUSED at write — ``controls_escapes`` — and
routes ``human``. A test that needs a signable cell first appends a NEWER, clean
controls report for ``alpha`` (:func:`pass_controls`: the worker's own event shape,
through the ORM, never by editing the seed), then posts a body that names an
accepted row of the cell (:func:`attested_body`). Nothing here bypasses the write
path of the grade ledger.
"""

from __future__ import annotations

from typing import Any

from crb.core.ledger import CELL_FIELDS, GradeRow
from crb.observability.events import StepEvent, StepStatus
from crb.store.models import Event
from fixtures.server_seed import ALPHA, Env

#: The clean controls run a signable test appends (distinct from the seed's ``0`` * 32).
CLEAN_CONTROLS_RUN = "5" * 32
STATEMENT = "I have read the accepted diff for this row; it implements what the commit says."


def pass_controls(
    env: Env,
    *,
    repo: str = ALPHA,
    run_id: str = CLEAN_CONTROLS_RUN,
    escapes: int = 0,
    not_constructible: int = 2,
    passed: bool = True,
    n_rows: int = 14,
) -> str:
    """Append a newer ``controls.report`` event for ``repo`` (``latest_controls_verdict``
    reads the newest) — clean by default: passed, 12 of 14 constructible, no escape."""
    ev = StepEvent(
        trace_id=run_id,
        stage="oracle",
        action="controls.report",
        status=StepStatus.OK,
        repo=repo,
        actor="worker-1",
        payload={
            "schema": "crb.negative_controls.v1",
            "apparatus": {"apparatus_version": "2.1"},
            "n_tasks": 2,
            "n_rows": n_rows,
            "violations": 0 if passed else 1,
            "escapes": escapes,
            "not_constructible": not_constructible,
            "skipped": 0,
            "passed": passed,
            "escape_rows": [],
            "rows": [],
        },
        seq=1,
    )
    d = ev.to_dict()
    payload = d.pop("payload")
    with env.factory() as s:
        s.add(Event(**d, payload_json=payload))
        s.commit()
    return run_id


def _in_scope(row: GradeRow, cell: dict[str, str]) -> bool:
    return all(cell.get(f, "*") in ("*", getattr(row, f)) for f in CELL_FIELDS)


def accepted_row(env: Env, cell: dict[str, str], *, clean: bool = True) -> GradeRow:
    """The newest seeded row of ``cell`` that is (not) clean — its ``row_hash`` is what
    an approver names."""
    rows = [
        r for r in env.info.rows if _in_scope(r, cell) and r.clean == clean and not r.disqualified
    ]
    if not rows:
        raise LookupError(f"no {'clean' if clean else 'red'} seeded row in cell {cell}")
    return rows[-1]


def attestation_for(
    env: Env, cell: dict[str, str], *, statement: str = STATEMENT
) -> dict[str, str]:
    return {"reviewed_row_hash": accepted_row(env, cell).row_hash, "statement": statement}


def attested_body(
    env: Env,
    cell: dict[str, str],
    *,
    repo: str = ALPHA,
    note: str = "reviewed the packs and one accepted diff",
    tier: str | None = None,
    statement: str = STATEMENT,
) -> dict[str, Any]:
    """A ``POST /signoffs`` body that clears the policy once the controls gate is clean."""
    body: dict[str, Any] = {
        "repo": repo,
        "cell": cell,
        "note": note,
        "attestation": attestation_for(env, cell, statement=statement),
    }
    if tier is not None:
        body["tier"] = tier
    return body


__all__ = [
    "CLEAN_CONTROLS_RUN",
    "STATEMENT",
    "accepted_row",
    "attestation_for",
    "attested_body",
    "pass_controls",
]
