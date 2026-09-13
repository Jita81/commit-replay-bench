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
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.oracle.adequacy import (
    DEFAULT_POLICY,
    classify_oracle,
    licenses_autoship,
    routing_decision,
)
from crb.core.spec import SIZE_TIER_NAMES
from crb.core.stats import mean
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope
from crb.server.routes.repos import get_repo_or_404
from crb.server.schemas import AdequacyPolicyOut, OracleCellOut, OracleReportOut, OracleTaskOut
from crb.store.models import Event, Task

router = APIRouter(tags=["oracle"])
_ERR = {"model": ErrorEnvelope}

SCORE_ACTIONS: frozenset[str] = frozenset({"oracle.score", "oracle.mutation.scored"})
CONTROLS_ACTION = "controls.report"


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _score_events(session: Session, repo: str) -> list[Event]:
    return list(
        session.execute(
            select(Event)
            .where(Event.repo == repo, Event.stage == "oracle", Event.action.in_(SCORE_ACTIONS))
            .order_by(Event.id)
        ).scalars()
    )


def _task_index(session: Session, repo: str, task_ids: set[str]) -> dict[str, Task]:
    if not task_ids:
        return {}
    return {
        t.task_id: t
        for t in session.execute(
            select(Task).where(Task.repo == repo, Task.task_id.in_(sorted(task_ids)))
        ).scalars()
    }


def _task_row(ev: Event, payload: Mapping[str, Any], spec: Task | None) -> OracleTaskOut:
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
    prov = payload.get("provenance")
    if isinstance(prov, Mapping) and prov.get("apparatus_version"):
        return str(prov["apparatus_version"])
    return str(payload.get("apparatus_version", "") or "")


def oracle_report(session: Session, repo: str) -> OracleReportOut:
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
    ev = db.execute(
        select(Event)
        .where(Event.repo == repo, Event.action == CONTROLS_ACTION)
        .order_by(Event.id.desc())
        .limit(1)
    ).scalar_one_or_none()
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
    return report


__all__ = ["CONTROLS_ACTION", "SCORE_ACTIONS", "oracle_report", "router"]
