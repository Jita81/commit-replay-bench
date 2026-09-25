"""What the API can say about a repository's posture without resolving one (ADR-0019).

The API host does not run tests, so it cannot measure a posture live; the worker does
that before every run. What the API reads is the RECORD: the posture most recently
recorded for the repository under the deployment's executor and image, how many of its
tasks are qualified there, why the others are not (each code with its fix), and how the
record differs from the repository's other postures. Two callers: ``POST /runs`` refuses
an unqualified replay at submit (``409 posture_unqualified``) when ``qualify_first`` is
off, and ``GET /repos/{name}/posture`` serves the Posture panel.

Navigation
----------
What it is:   The API's reading of the qualification records — the posture summary of one
              repository and the submit-time gate.
What it does: Picks the latest posture recorded for (repository, executor, image); counts
              qualified tasks and refusals by code with their fixes; names why the record is
              stale (none yet, another apparatus); refuses a build run with nothing qualified.
How:          Store reads (``crb.store.qualifications``) → plain dicts the routes serve.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/store/qualifications.py (the records), src/crb/server/routes/runs.py
              (the 409), src/crb/server/routes/repos.py (``GET /repos/{name}/posture``),
              src/crb/core/qualify.py (codes, fixes, deltas), src/crb/server/settings.py (the
              deployment's executor, image and provisioning)
Tested by:    tests/test_server_routes_runs.py, tests/test_server_routes_repos.py
Touch when:   the panel or the 409 needs another fact from the records.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crb.core.qualify import (
    POSTURE_UNQUALIFIED,
    Qualification,
    code_view,
    delta_against,
)
from crb.core.version import APPARATUS_VERSION
from crb.server.deps import ApiError
from crb.store import qualifications as sq
from crb.store.models import Repo, Task, TaskQualification

#: The fix the submit-time refusal names: a qualify run, which spends nothing.
QUALIFY_FIX = "POST /runs {kind: qualify, repo} — no model spend"
#: Kinds the submit-time gate covers when ``qualify_first`` is off. A factory run is not
#: here: it qualifies every item in-run from its own RED proof (ADR-0019 §5).
GATED_KINDS: frozenset[str] = frozenset({"replay", "blind", "oracle", "controls"})


def deployment_executor(settings: Any, requested: str = "") -> str:
    """The executor a run would use: the request's, else the deployment's."""
    return (requested or str(getattr(settings.sandbox, "executor", "") or "local")).lower()


def deployment_image(settings: Any, repo: Repo | None) -> str:
    """The sandbox image a docker run of ``repo`` would use (its own, else the default)."""
    image = ""
    if repo is not None:
        image = str(dict(repo.config_json or {}).get("sandbox_image") or "")
    return image or str(getattr(settings.sandbox, "image", "") or "")


def deployment_posture_class(settings: Any) -> str:
    """The posture class this deployment grades in — ``executor/tree/dependency mode`` —
    from its settings alone (the map's default filter; the worker measures the full
    posture live before every run). Docker is the sealed mode with the read-only tree
    until provisioning lands (ADR-0019 stream D); local is the host's own environment."""
    executor = deployment_executor(settings)
    if executor == "docker":
        tree = str(getattr(settings.sandbox, "tree", "") or "readonly")
        return f"docker/{tree}/sealed"
    return "local/inplace/host-env"


def posture_summary(
    s: Session, repo: Repo, *, executor: str, image_ref: str, provisioning: dict[str, Any]
) -> dict[str, Any]:
    """The Posture panel's reading of ``repo`` (see the module docstring)."""
    name = repo.name
    posture_id = sq.latest_posture_for(
        s, name, executor=executor, image_ref=image_ref if executor == "docker" else ""
    )
    total = int(
        s.execute(select(func.count()).select_from(Task).where(Task.repo == name)).scalar_one()
    )
    out: dict[str, Any] = {
        "repo": name,
        "executor": executor,
        "image_ref": image_ref if executor == "docker" else "",
        "posture_id": posture_id,
        "posture_class": "",
        "posture": {},
        "provisioning": provisioning,
        "qualified": 0,
        "total": total,
        "refusals_by_code": [],
        "delta": [],
        "stale_reason": "",
    }
    if not posture_id:
        out["stale_reason"] = (
            f"no task has been qualified under {executor}"
            + (f" with {image_ref}" if executor == "docker" and image_ref else "")
            + " yet — qualify the repository (no model spend)"
        )
        return out
    records = sq.latest_by_task(s, name, posture_id)
    any_q = next(iter(records.values()), None)
    if any_q is not None:
        out["posture"] = dict(any_q.posture)
        out["posture_class"] = any_q.posture_class
        if any_q.apparatus_version != APPARATUS_VERSION:
            out["stale_reason"] = (
                f"these records were measured by apparatus {any_q.apparatus_version}; the "
                f"instrument is now {APPARATUS_VERSION} — qualify again"
            )
    counts: Counter[str] = Counter(q.code for q in records.values() if not q.is_qualified)
    out["qualified"] = sum(1 for q in records.values() if q.is_qualified)
    unmeasured = max(0, total - len(records))
    if unmeasured:
        counts[POSTURE_UNQUALIFIED] += unmeasured
    out["refusals_by_code"] = [
        {**code_view(code), "n": n} for code, n in counts.most_common() if code
    ]
    out["delta"] = _deltas(s, name, records)
    return out


def _deltas(
    s: Session, repo: str, here: dict[str, Qualification], limit: int = 20
) -> list[dict[str, Any]]:
    """For each task qualified here, how its record differs from its latest record in
    another posture (only the tasks where it does)."""
    rows = s.execute(
        select(TaskQualification)
        .where(TaskQualification.repo == repo, TaskQualification.task_id.in_(list(here)))
        .order_by(TaskQualification.seq)
    ).scalars()
    others: dict[str, list[Qualification]] = {}
    for row in rows:
        others.setdefault(row.task_id, []).append(Qualification.from_dict(row.body_json))
    out: list[dict[str, Any]] = []
    for tid, q in here.items():
        d = delta_against(q, others.get(tid, []))
        if d and not d.get("same_fingerprint"):
            out.append({"task_id": tid, **d})
        if len(out) >= limit:
            break
    return out


def refuse_unqualified(
    s: Session,
    repo: Repo,
    *,
    kind: str,
    task_ids: list[str],
    executor: str,
    image_ref: str,
) -> None:
    """``409 posture_unqualified`` when no task this run would select is qualified in the
    latest posture recorded for (repository, executor, image) — the run could only fail
    ``POSTURE_UNQUALIFIED`` on the worker, so it is refused before it is queued."""
    if kind not in GATED_KINDS:
        return
    posture_id = sq.latest_posture_for(
        s, repo.name, executor=executor, image_ref=image_ref if executor == "docker" else ""
    )
    records = sq.latest_by_task(s, repo.name, posture_id, task_ids or None) if posture_id else {}
    qualified = sum(1 for q in records.values() if q.is_qualified)
    if qualified:
        return
    wanted = task_ids or list(
        s.execute(select(Task.task_id).where(Task.repo == repo.name)).scalars()
    )
    reasons: Counter[str] = Counter(q.code for q in records.values() if q.code)
    unmeasured = len(set(wanted) - set(records))
    if unmeasured:
        reasons[POSTURE_UNQUALIFIED] += unmeasured
    raise ApiError(
        409,
        "posture_unqualified",
        f"no task of {repo.name!r} is qualified in the posture that would grade it "
        f"({executor}{' ' + image_ref if executor == 'docker' and image_ref else ''}); "
        "qualify it first (no model spend), or leave qualify_first on",
        detail={
            "qualified": 0,
            "unqualified": len(wanted),
            "posture_id": posture_id,
            "reasons": dict(reasons),
            "fix": QUALIFY_FIX,
        },
    )


__all__ = [
    "GATED_KINDS",
    "QUALIFY_FIX",
    "deployment_executor",
    "deployment_image",
    "deployment_posture_class",
    "posture_summary",
    "refuse_unqualified",
]
