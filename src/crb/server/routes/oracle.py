"""``/oracle/{repo}`` and ``/oracle/{repo}/controls`` — is the green worth anything?

Oracle runs (kind ``oracle``) score each task's target-test oracle by mutation
(:mod:`crb.core.oracle.mutation`) and emit one ``oracle`` StepEvent per scored
task whose payload is :meth:`CommitOracleScore.to_dict` (``oracle.score``; the
core's own ``oracle.mutation.scored`` is accepted too). Control runs (kind
``controls``) emit one ``controls.report`` event whose payload is
:meth:`ControlsReport.to_dict`. Both routes are READS of the events table — the
latest observation per task / the latest report wins — classified with
:mod:`crb.core.oracle.adequacy` so the band and the gate come from the same
frozen policy the router uses.

An unscoreable oracle (``strength: null``) is reported as ``unscoreable`` and never
averaged in; a repo with no controls report answers ``404 not_measured``.

:func:`latest_controls_verdict` reduces the same latest report to the
:class:`~crb.core.routing.ControlsVerdict` the capability map and ``/routes``
route under (ADR-0003 amendment) — ONE source for the controls screen and the
router, so they can never disagree. When no report event exists it falls back to
the latest finished ``controls`` run's ``counts_json``; when neither exists it
returns :meth:`ControlsVerdict.unmeasured` (an honest absence, never a pass). Every report
is reduced through :func:`crb.core.oracle.controls.controls_verdict_of`, so a passed report
with no gold witness (written before ``controls.v3``) reads as unmeasured too — on the
controls screen's verdict and for routing alike (P-372).

Navigation
----------
What it is:   The ``/oracle/{repo}`` and ``/oracle/{repo}/controls`` route module, and the
              home of ``latest_controls_verdict`` — the one source the router uses.
What it does: Reduces the store's ``oracle.score`` events to the latest strength per task
              and per (class × size) cell, banded and gated by the frozen adequacy policy;
              serves the latest negative-controls report with its routing-reduced
              verdict; answers ``unmeasured`` (never a pass) when no report exists, or when
              the latest passed report carries no gold witness (before ``controls.v3``). An
              unscoreable oracle is reported, never averaged in.
How:          ``select(Event)`` by stage / action in insertion order → latest per task →
              ``classify_oracle`` / ``routing_decision`` → grouped cells;
              ``latest_controls_verdict`` = latest ``controls.report`` event, else the
              latest finished ``controls`` run's counts, else ``ControlsVerdict.unmeasured``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0010-polyglot-negative-controls.md,
              docs/adr/0009-text-level-mutators.md
Works with:   src/crb/core/oracle/adequacy.py (the bands and the gate),
              src/crb/core/oracle/controls.py (``controls_verdict_of``, the reduction),
              src/crb/core/routing.py (``ControlsVerdict``), src/crb/server/worker.py (emits
              the events this reads), src/crb/server/routes/capability.py and
              src/crb/server/routes/signoffs.py (route under ``latest_controls_verdict`` and
              ``oracle_by_task``), src/crb/server/routes/learn.py (same score reader),
              ui/src/screens/Oracle, docs/API.md#oracle-adequacy
Tested by:    tests/test_server_routes_oracle.py, tests/test_server_routes_capability.py,
              tests/test_server_routes_signoffs.py
Touch when:   never for a new repository (mutation scoring is configured per run —
              docs/OPERATOR.md#31-oracle-adequacy--mutation-scoring); when the worker's
              event payload shape changes (both ``_task_row`` and the CLI's reader change
              with it); when the adequacy bands move (that is the core policy + an ADR).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.ledger import is_v2_apparatus
from crb.core.oracle.adequacy import (
    DEFAULT_POLICY,
    classify_oracle,
    licenses_autoship,
    routing_decision,
)
from crb.core.oracle.controls import controls_verdict_of
from crb.core.oracle.mutation import mutation_version
from crb.core.routing import DEFAULT_POLICY as ROUTING_POLICY
from crb.core.routing import ControlsVerdict, RoutingPolicy
from crb.core.spec import SIZE_TIER_NAMES
from crb.core.stats import mean
from crb.core.version import APPARATUS_VERSION
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope
from crb.server.routes.repos import get_repo_or_404
from crb.server.schemas import AdequacyPolicyOut, OracleCellOut, OracleReportOut, OracleTaskOut
from crb.store.models import Event, Run, Task

router = APIRouter(tags=["oracle"])
_ERR = {"model": ErrorEnvelope}

SCORE_ACTIONS: frozenset[str] = frozenset({"oracle.score", "oracle.mutation.scored"})
CONTROLS_ACTION = "controls.report"
CONTROLS_KIND = "controls"
#: Run statuses whose ``counts_json`` is a finished measurement (a FAILED controls
#: run is the gate saying FAIL — exactly the verdict routing must see).
CONTROLS_FINISHED: tuple[str, ...] = ("succeeded", "failed")


def _latest_controls_event(session: Session, repo: str) -> Event | None:
    """The newest ``controls.report`` event for ``repo``, or ``None``."""
    return session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == CONTROLS_ACTION)
        .order_by(Event.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_controls_verdict(
    session: Session, repo: str, *, apparatus: str = APPARATUS_VERSION
) -> ControlsVerdict:
    """The repo's latest negative-controls verdict AT ``apparatus`` (controls-gate.v2), for
    routing.

    Source order: the latest ``controls.report`` event of that apparatus (what
    ``/oracle/{repo}/controls`` serves when it is the latest); else the latest finished
    ``controls`` run's ``counts_json`` (the worker writes both, so this only matters for a
    report whose event was pruned) — from 2.4 only when the run's own apparatus stamp
    (``apparatus_json``) names that apparatus; else :meth:`ControlsVerdict.unmeasured`, naming
    why. A report of another apparatus is history and never read in this one's place.
    """
    events = session.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == CONTROLS_ACTION)
        .order_by(Event.id.desc())
    ).scalars()
    other = ""
    for ev in events:
        verdict = controls_verdict_of(
            dict(ev.payload_json or {}), run_id=ev.trace_id, created=ev.timestamp
        )
        if not is_v2_apparatus(apparatus) or verdict.apparatus_version == apparatus:
            return verdict
        other = other or verdict.apparatus_version or "unstamped"
    if other:
        return ControlsVerdict.unmeasured(
            f"no controls report at apparatus {apparatus}; the latest is of {other} (history)"
        )
    run = session.execute(
        select(Run)
        .where(Run.repo == repo, Run.kind == CONTROLS_KIND, Run.status.in_(CONTROLS_FINISHED))
        .order_by(Run.created.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is not None and "passed" in (run.counts_json or {}):
        stamp = str(dict(run.apparatus_json or {}).get("apparatus_version", "") or "")
        if not is_v2_apparatus(apparatus) or stamp == apparatus:
            return controls_verdict_of(
                {"apparatus_version": stamp, **dict(run.counts_json)},
                run_id=run.id,
                created=run.finished or run.created,
            )
    if is_v2_apparatus(apparatus):
        return ControlsVerdict.unmeasured(f"no controls report at apparatus {apparatus}")
    return ControlsVerdict.unmeasured()


def verdict_dict(
    verdict: ControlsVerdict, policy: RoutingPolicy = ROUTING_POLICY
) -> dict[str, Any]:
    """:meth:`ControlsVerdict.to_dict` + the ``state`` word under ``policy``'s bars."""
    return {
        **verdict.to_dict(),
        "state": verdict.state(
            min_share=policy.min_controls_share, max_escapes=policy.max_controls_escapes
        ),
    }


def _float_or_none(v: Any) -> float | None:
    """Lenient float from an event payload; ``None`` for absent or unparseable."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int:
    """Lenient int from an event payload; ``0`` for absent or unparseable."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _score_events(session: Session, repo: str) -> list[Event]:
    """Every ``oracle.score`` event for ``repo`` in insertion order (latest last)."""
    return list(
        session.execute(
            select(Event)
            .where(Event.repo == repo, Event.stage == "oracle", Event.action.in_(SCORE_ACTIONS))
            .order_by(Event.id)
        ).scalars()
    )


def _task_index(session: Session, repo: str, task_ids: set[str]) -> dict[str, Task]:
    """``task_id → Task`` for the scored tasks (class / size fall back to the spec)."""
    if not task_ids:
        return {}
    return {
        t.task_id: t
        for t in session.execute(
            select(Task).where(Task.repo == repo, Task.task_id.in_(sorted(task_ids)))
        ).scalars()
    }


def _task_row(ev: Event, payload: Mapping[str, Any], spec: Task | None) -> OracleTaskOut:
    """One scored task from its event: strength, band and gate under the frozen policy."""
    strength = _float_or_none(payload.get("oracle_strength", payload.get("strength")))
    total = _int(payload.get("total", payload.get("mutants")))
    if total == 0:
        strength = None  # a score with no mutants cannot carry a strength
    return OracleTaskOut(
        task_id=str(ev.task_id or payload.get("task_id") or payload.get("task") or ""),
        capability_class=str(
            payload.get("capability_class") or (spec.capability_class if spec else "") or ""
        ),
        size=str(payload.get("size") or (spec.size if spec else "") or ""),
        strength=strength,
        band=classify_oracle(strength, policy=DEFAULT_POLICY),
        mutants=total,
        killed=_int(payload.get("killed")),
        errors=_int(payload.get("errors")),
        gate=routing_decision(True, strength, policy=DEFAULT_POLICY),
        run_id=ev.trace_id,
        scored_at=ev.timestamp,
        note=str(payload.get("note", "") or ""),
    )


def _apparatus_of(payload: Mapping[str, Any]) -> str:
    """The apparatus stamp a score carries (``provenance.apparatus_version`` or top-level)."""
    prov = payload.get("provenance")
    if isinstance(prov, Mapping) and prov.get("apparatus_version"):
        return str(prov["apparatus_version"])
    return str(payload.get("apparatus_version", "") or "")


def oracle_by_task(
    session: Session, repo: str, *, apparatus: str = APPARATUS_VERSION
) -> dict[str, float | None]:
    """Each task's MINIMUM scoreable strength among its ``oracle.score`` events scored at
    ``apparatus`` under that apparatus's rule (``mutation.v2`` from 2.4) — ADR-0025 item 3. A
    minimum cannot rise when a flaky suite is re-scored, and a score of another apparatus or
    rule is history, never read. Below 2.4 the latest score per task is read, as it was. The
    capability map and the sign-off read this one reduction
    (:func:`~crb.core.capability.oracle_evidence`)."""
    if not is_v2_apparatus(apparatus):
        return {t.task_id: t.strength for t in oracle_report(session, repo).tasks}
    rule = mutation_version(apparatus)
    out: dict[str, float | None] = {}
    for ev in _score_events(session, repo):
        p = dict(ev.payload_json or {})
        prov = p.get("provenance") if isinstance(p.get("provenance"), Mapping) else {}
        assert isinstance(prov, Mapping)
        if _apparatus_of(p) != apparatus or str(prov.get("mutation_version", "")) != rule:
            continue
        strength = _float_or_none(p.get("oracle_strength", p.get("strength")))
        if _int(p.get("total", p.get("mutants"))) == 0:
            strength = None
        tid = str(ev.task_id or p.get("task_id") or p.get("task") or "")
        if not tid or strength is None:
            continue
        prior = out.get(tid)
        out[tid] = strength if prior is None else min(prior, strength)
    return out


def oracle_report(session: Session, repo: str) -> OracleReportOut:
    """The full ``GET /oracle/{repo}`` body: latest task rows, cells grouped by
    (class × size) in tier order, the apparatus versions and runs seen."""
    events = _score_events(session, repo)
    payloads = [(ev, dict(ev.payload_json or {})) for ev in events]
    task_ids = {
        str(ev.task_id or p.get("task_id") or p.get("task") or "") for ev, p in payloads
    } - {""}
    specs = _task_index(session, repo, task_ids)
    latest: dict[str, OracleTaskOut] = {}
    apparatus: set[str] = set()
    runs: list[str] = []
    for ev, p in payloads:
        row = _task_row(
            ev, p, specs.get(str(ev.task_id or p.get("task_id") or p.get("task") or ""))
        )
        if not row.task_id:
            continue
        latest[row.task_id] = row  # events are in insertion order: the latest wins
        if a := _apparatus_of(p):
            apparatus.add(a)
        if ev.trace_id not in runs:
            runs.append(ev.trace_id)
    tasks = sorted(latest.values(), key=lambda t: (t.capability_class, t.size, t.task_id))
    groups: dict[tuple[str, str], list[OracleTaskOut]] = {}
    for t in tasks:
        groups.setdefault((t.capability_class, t.size), []).append(t)
    cells: list[OracleCellOut] = []
    for (cls, size), ts in sorted(
        groups.items(),
        key=lambda kv: (
            kv[0][0],
            SIZE_TIER_NAMES.index(kv[0][1]) if kv[0][1] in SIZE_TIER_NAMES else 99,
        ),
    ):
        scored = [t.strength for t in ts if t.strength is not None]
        smean = round(mean(scored), 4) if scored else None
        cells.append(
            OracleCellOut(
                capability_class=cls,
                size=size,
                n=len(scored),
                tasks=len(ts),
                strength_mean=smean,
                strength_min=round(min(scored), 4) if scored else None,
                band=classify_oracle(smean, policy=DEFAULT_POLICY),
                gate=(
                    "auto_ship"
                    if licenses_autoship(smean, policy=DEFAULT_POLICY)
                    else "human_review"
                ),
            )
        )
    return OracleReportOut(
        repo=repo,
        policy=AdequacyPolicyOut(**DEFAULT_POLICY.to_dict()),
        tasks=tasks,
        cells=cells,
        apparatus_versions=sorted(apparatus),
        runs=runs,
    )


@router.get(
    "/oracle/{repo}",
    response_model=OracleReportOut,
    responses={401: _ERR, 404: _ERR},
    summary="Per-task and per-cell oracle strength with the adequacy band and gate",
)
def get_oracle(repo: str, viewer: ViewerDep, db: DbDep) -> OracleReportOut:
    del viewer
    get_repo_or_404(db, repo)
    return oracle_report(db, repo)


@router.get(
    "/oracle/{repo}/controls",
    responses={401: _ERR, 404: _ERR},
    summary="Latest negative-controls report (ControlsReport.to_dict) or 404 not_measured",
)
def get_controls(repo: str, viewer: ViewerDep, db: DbDep) -> dict[str, Any]:
    del viewer
    get_repo_or_404(db, repo)
    ev = _latest_controls_event(db, repo)
    if ev is None:
        raise ApiError(
            404,
            "not_measured",
            f"no negative-controls report for repo {repo!r}; run a 'controls' run first",
            detail={"repo": repo},
        )
    report = dict(ev.payload_json or {})
    report.setdefault("run_id", ev.trace_id)
    report.setdefault("reported_at", ev.timestamp)
    # the routing-reduced view of this same report (what the capability map gates on)
    report["verdict"] = verdict_dict(
        controls_verdict_of(report, run_id=ev.trace_id, created=ev.timestamp)
    )
    return report


__all__ = [
    "CONTROLS_ACTION",
    "SCORE_ACTIONS",
    "latest_controls_verdict",
    "oracle_report",
    "router",
    "verdict_dict",
]
