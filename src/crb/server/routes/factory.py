"""``/factory/{repo}/*`` — phase P6, not implemented yet.

The four paths exist so the UI's empty state can key on a real, stable code
(``501 not_implemented`` with ``detail.phase == "P6"``) instead of a 404 it cannot
tell apart from a typo. Role gates are already in force (401/403 come before 501),
so the RBAC contract in API.md holds from day one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from crb.server.auth import ApproverDep, OperatorDep, ViewerDep
from crb.server.deps import ApiError, ErrorEnvelope

router = APIRouter(tags=["factory"])
_ERR = {"model": ErrorEnvelope}
PHASE = "P6"


def not_implemented(path: str) -> ApiError:
    return ApiError(
        501,
        "not_implemented",
        f"{path} arrives in phase {PHASE} "
        "(factory: backlog freeze, DoR gaps, RED proof, build, PR, review)",
        detail={"phase": PHASE, "path": path},
    )


@router.get("/factory/{repo}/backlog", responses={401: _ERR, 501: _ERR})
def get_backlog(repo: str, viewer: ViewerDep) -> dict[str, Any]:
    del viewer
    raise not_implemented(f"/factory/{repo}/backlog")


@router.post("/factory/{repo}/backlog", responses={401: _ERR, 403: _ERR, 501: _ERR})
def freeze_backlog(repo: str, operator: OperatorDep) -> dict[str, Any]:
    del operator
    raise not_implemented(f"/factory/{repo}/backlog")


@router.get("/factory/{repo}/tasks", responses={401: _ERR, 501: _ERR})
def get_factory_tasks(repo: str, viewer: ViewerDep) -> dict[str, Any]:
    del viewer
    raise not_implemented(f"/factory/{repo}/tasks")


@router.post(
    "/factory/{repo}/tasks/{task_id}/signoff-gap", responses={401: _ERR, 403: _ERR, 501: _ERR}
)
def signoff_gap(repo: str, task_id: str, approver: ApproverDep) -> dict[str, Any]:
    del approver
    raise not_implemented(f"/factory/{repo}/tasks/{task_id}/signoff-gap")


@router.get("/factory/{repo}/evidence", responses={401: _ERR, 501: _ERR})
def get_factory_evidence(repo: str, viewer: ViewerDep) -> dict[str, Any]:
    del viewer
    raise not_implemented(f"/factory/{repo}/evidence")


__all__ = ["PHASE", "not_implemented", "router"]
