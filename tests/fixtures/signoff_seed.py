"""Sign-off helpers on top of :mod:`fixtures.server_seed` for ``signoff-policy.v3``.

The seed's controls report carries ONE escape by design, so its deliver cell
(``bug.fix|S``, n = 40, point 0.95) is REFUSED at write — ``controls_escapes`` — and
routes ``human``. The seed's oracle scores are mixed by design too (0.9 / 0.5 / 0.33
on three of the cell's four tasks, one unscoreable elsewhere): under
``signoff-policy.v2`` the cell's oracle is MEASURED at 0.58 — ``oracle_weak``. A test
that needs a signable cell first appends a NEWER, clean controls report for ``alpha``
(:func:`pass_controls`) and NEWER, strong ``oracle.score`` events for the cell's tasks
(:func:`score_oracle`) — both the worker's own event shapes, through the ORM, never by
editing the seed; :func:`clear_policy` does both — then posts a body that names an
accepted row of the cell (:func:`attested_body`). The two-person rule
(``signoff-policy.v3``, ``same_actor``) is clear in the seed as shipped: ``op1`` queued
the ``succeeded`` run and the worker graded every row, so the approver ``appr1`` is
nobody's same actor — a test that wants the refusal re-stamps a run's actor to the
approver's id (``tests/test_server_routes_signoffs.py::TestTwoPersonRule``). Nothing here
bypasses the write path of the grade ledger.

Navigation
----------
What it is:   Sign-off helpers on top of ``fixtures.server_seed`` for ``signoff-policy.v3``.
What it does: Makes the seed's deliver cell signable the honest way: appends a NEWER, clean
              ``controls.report`` (``pass_controls``) and NEWER strong ``oracle.score`` events per
              task (``score_oracle``) — the worker's own event shapes, through the ORM, never by
              editing the seed — and builds a ``POST /signoffs`` body naming an accepted row of
              the cell (``attested_body``). The seed is refused by design (one controls escape;
              oracle measured at 0.58) so every test starts from a 409.
How:          ``clear_policy`` = ``pass_controls`` + ``score_oracle``; ``accepted_row`` picks the
              newest seeded row of the cell by ``row_hash``; ``attestation_for`` shapes the
              attestation the policy validates.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   tests/fixtures/server_seed.py (the seed it extends), src/crb/core/signoff.py (the
              policy the helpers satisfy clause by clause), src/crb/server/routes/signoffs.py
              (the route under test), tests/test_server_routes_signoffs.py,
              tests/test_server_routes_capability.py and tests/test_server_routes_forecast.py
              (the consumers)
Tested by:    tests/test_server_routes_signoffs.py, tests/test_server_routes_capability.py,
              tests/test_server_routes_forecast.py
Touch when:   never for a new repository; the sign-off policy gains a clause (add the helper that
              clears it honestly and a 409 case in the route tests); the ``oracle.score`` or
              ``controls.report`` event shape changes in the worker (mirror it here — the helpers
              must stay the worker's shapes).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select

from crb.core.ledger import CELL_FIELDS, GradeRow
from crb.core.oracle.mutation import mutation_version
from crb.core.spec import TaskSpec
from crb.core.version import APPARATUS_VERSION
from crb.observability.events import StepEvent, StepStatus
from crb.store.models import Event, Task
from fixtures.proven import S1, add_rows, add_tasks, write_reading
from fixtures.server_seed import ALPHA, DELIVER_CELL, RUN_IDS, Env

#: The clean controls run a signable test appends (distinct from the seed's ``0`` * 32).
CLEAN_CONTROLS_RUN = "5" * 32
#: The strong oracle run a signable test appends (distinct from the seed's ``f`` * 32).
STRONG_ORACLE_RUN = "9" * 32
#: The strength :func:`score_oracle` stamps on every task of the cell (≥ 0.80).
STRONG_ORACLE = 0.9
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
            "apparatus": {
                "apparatus_version": APPARATUS_VERSION,
                "complete": True,
                "controls_version": "controls.v3",
            },
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


def cell_task_ids(env: Env, cell: dict[str, str]) -> list[str]:
    """The distinct tasks of ``cell`` (seed order) — what the sign-off's oracle
    measurement averages over."""
    out: list[str] = []
    for r in env.info.rows:
        if _in_scope(r, cell) and r.task_id not in out:
            out.append(r.task_id)
    return out


def score_oracle(
    env: Env,
    *,
    repo: str = ALPHA,
    cell: dict[str, str] | None = None,
    task_ids: Iterable[str] | None = None,
    strength: float | None = STRONG_ORACLE,
    run_id: str = STRONG_ORACLE_RUN,
    total: int = 10,
) -> list[str]:
    """Append a NEWER ``oracle.score`` event per task of ``cell`` (default: the seed's
    deliver cell) — the worker's own event shape, latest-per-task wins in
    ``/oracle/{repo}`` and therefore in the sign-off's oracle measurement. ``strength``
    ``None`` writes an UNSCOREABLE score (``total`` 0) — the cell then reads as
    unmeasured again. Returns the task ids scored."""
    ids = list(task_ids) if task_ids is not None else cell_task_ids(env, cell or DELIVER_CELL)
    with env.factory() as s:
        for i, tid in enumerate(ids, start=1):
            mutants = 0 if strength is None else total
            ev = StepEvent(
                trace_id=run_id,
                stage="oracle",
                action="oracle.score",
                status=StepStatus.OK,
                repo=repo,
                task_id=tid,
                actor="worker-1",
                payload={
                    "schema": "crb.oracle_strength.v1",
                    "task_id": tid,
                    "total": mutants,
                    "killed": 0 if strength is None else round(strength * total),
                    "errors": 0,
                    "oracle_strength": strength,
                    "note": "" if mutants else "no mutants generated — not scoreable",
                    "provenance": {
                        "apparatus_version": APPARATUS_VERSION,
                        "mutator": "python-ast",
                        "mutation_version": mutation_version(APPARATUS_VERSION),
                    },
                },
                seq=i,
            )
            d = ev.to_dict()
            payload = d.pop("payload")
            s.add(Event(**d, payload_json=payload))
        s.commit()
    return ids


#: The tasks :func:`prove_deliver_cell` adds to the seed's deliver cell (one reading's pool).
PROVEN_TASKS = 20


def prove_deliver_cell(env: Env, *, n: int = PROVEN_TASKS) -> list[GradeRow]:
    """Prove the seed's deliver cell under routing.v2 (ADR-0025, ADR-0026) the honest way:
    the deployment grades in the sealed posture (``sandbox.executor`` docker, so the seed's
    host rows are another posture class and never read), ``n`` new qualified tasks of the cell
    each their own change, a reading of ``S1@<author>`` registered over them before any
    attempt, and one clean sealed first attempt per task graded by the worker — five from the
    ``succeeded`` run, the rest from historical runs, as the seed's own rows are — so the
    reading delivers at its first look. The rows join ``env.info.rows``
    (the attestation helpers pick the newest). Returns the chained rows."""
    env.settings.sandbox.executor = "docker"
    ids = add_tasks(env.factory, n, prefix="signable", cell=DELIVER_CELL)
    write_reading(
        env.factory, ids, cell=DELIVER_CELL, changes={c: f"change-signable-{c}" for c in ids}
    )
    # the seed's shape: the first five from the ``succeeded`` run (queued by ``op1``), the
    # rest from historical runs the store has no row for (nobody's), four rows a run
    rows: list[GradeRow] = []
    for k, c in enumerate(ids):
        run = RUN_IDS["succeeded"] if k < 5 else hashlib.md5(f"hist-{(k - 5) // 4}".encode())
        run_id = run if isinstance(run, str) else run.hexdigest()
        rows += add_rows(
            env.factory, [c], arm=S1, cell=DELIVER_CELL, run_id=run_id, actor="worker-1"
        )
    env.info.rows.extend(rows)
    with env.factory() as s:
        for t in s.execute(select(Task).where(Task.task_id.in_(ids))).scalars():
            env.info.tasks.append(TaskSpec.from_dict(dict(t.spec_json)))
    return rows


def add_red_row(env: Env) -> GradeRow:
    """One more qualified task of the deliver cell with a RED sealed first attempt on the
    standard arm — outside the reading's pool, so the reading is unchanged — for the tests
    that name a row the instrument did not accept. The row joins ``env.info.rows``."""
    (tid,) = add_tasks(env.factory, 1, prefix="red", cell=DELIVER_CELL)
    (row,) = add_rows(env.factory, [tid], arm=S1, cell=DELIVER_CELL, clean=False, actor="worker-1")
    env.info.rows.append(row)
    return row


def clear_policy(env: Env, *, repo: str = ALPHA) -> None:
    """Make the seed's deliver cell signable under ``signoff-policy.v4``: proven by a
    registered reading in the sealed posture (:func:`prove_deliver_cell`), a clean controls
    gate at this apparatus AND a measured, strong oracle on every task of the cell (the
    two-person rule holds in the seed as shipped — see the module docstring)."""
    prove_deliver_cell(env)
    pass_controls(env, repo=repo)
    score_oracle(env, repo=repo)


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
    """The attestation the policy validates: an accepted row of ``cell`` plus
    the human statement.
    """
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
    """A ``POST /signoffs`` body that clears the policy once the controls gate is clean
    and the cell's oracle is measured strong (:func:`clear_policy`)."""
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
    "STRONG_ORACLE",
    "STRONG_ORACLE_RUN",
    "accepted_row",
    "add_red_row",
    "attestation_for",
    "attested_body",
    "cell_task_ids",
    "clear_policy",
    "pass_controls",
    "prove_deliver_cell",
    "score_oracle",
]
