"""``/factory/{repo}/acceptance`` — a second person's held-out acceptance tests.

ADR-0026 item 8. A calibration build on a ticket that carries a person's failing test is graded,
on its first attempt, on held-out acceptance tests a second person writes from the ticket alone:

* ``GET /factory/{repo}/acceptance`` (viewer) — every ticket that needs held-out tests or has
  them: its title, description, acceptance criteria, class and size, the grant and who funded
  it, the state (``open``, ``written``, ``building``, ``graded``) and the result once graded,
  and whether the signed-in person may write the tests (``can_write``) or why not
  (``why_not``). Never the ticket's failing test and never a build.
* ``POST /factory/{repo}/items/{item_id}/acceptance`` (operator) — write them: ``{files:
  [{path, content}]}`` → **201** the record's public view (author, time, digest, paths).
  Refused **409** ``acceptance_not_needed`` (the ticket carries no person's failing test),
  ``no_calibration_build`` (no grant), ``build_started`` (the grant is claimed),
  ``already_built`` (the ticket was built before) or ``acceptance_written`` (one record per
  grant); **403** ``acceptance_same_person`` (the ticket's author or the funding approver);
  **422** for a path outside the repository, a file its runner does not treat as a test, the
  ticket's own test file, too many or too large files, or content the redaction would change.

Navigation
----------
What it is:   The route module of held-out acceptance tests: the assignment list and the write.
What it does: Lists each ticket's assignment for the signed-in person; writes one record per
              calibration grant after the two-person rule, the build-not-started rule and the
              file checks, under the events write lock.
How:          ``FactoryHome`` (the backlog, the ticket's failing test, the chain) →
              ``crb.server.acceptance.assignment`` per ticket; the write builds a
              ``HeldOutTests`` and calls ``write_held_out``.
Layer:        server — docs/ARCHITECTURE.md#41-c4-level-2--containers
ADRs:         docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/server/acceptance.py (the store and the assignment),
              src/crb/core/acceptance.py (the record and the two-person rule),
              src/crb/server/routes/factory.py (funds the calibration build this answers),
              src/crb/server/factory_state.py (the backlog and the chain),
              ui/src/screens/Factory/AcceptancePage.tsx (the screen)
Tested by:    tests/test_server_acceptance.py, tests/test_forward_reading_e2e.py
Touch when:   never for a new repository; a refusal or a field changes (docs/API.md's Factory
              table and ui/src/api/types.ts first).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from crb.core.acceptance import (
    MAX_FILE_BYTES,
    MAX_FILES,
    HeldOutTests,
    path_refusal,
    writer_refusal,
)
from crb.core.evidence import utc_now_iso
from crb.core.redact import redact
from crb.core.spec import RepoConfig
from crb.factory.backlog import BacklogItem
from crb.factory.evidence import EV_BUILD, spent_grants, ticket_authors
from crb.server.acceptance import (
    AcceptanceRefused,
    assignment,
    latest_grant,
    load_held_out,
    write_held_out,
)
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import FactoryHome
from crb.server.routes.repos import get_repo_or_404
from crb.server.settings import ROLE_RANK

router = APIRouter(tags=["factory"])
_ERR = {"model": ErrorEnvelope}


class HeldOutFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=MAX_FILE_BYTES)


class HeldOutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[HeldOutFileIn] = Field(min_length=1, max_length=MAX_FILES)


class HeldOutRecordOut(BaseModel):
    record_id: str
    item_id: str
    grant: str
    author: str
    written_at: str
    sha256: str
    paths: list[str]


class AssignmentOut(BaseModel):
    item_id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    capability_class: str
    size: str
    grant: str
    funded_by: str
    funded_at: str
    #: ``open`` (tests needed), ``written``, ``building`` (the grant is claimed), ``graded``.
    status: str
    can_write: bool
    why_not: str
    record: HeldOutRecordOut | None = None
    #: ``pass`` / ``fail`` / ``error`` once the build's first attempt is graded; else "".
    result: str = ""


class AssignmentsOut(BaseModel):
    repo: str
    assignments: list[AssignmentOut]


def _items(home: FactoryHome) -> list[BacklogItem]:
    backlog = home.load_backlog()
    return [] if backlog is None else [*backlog.items, *backlog.evolutions]


def _config(repo_row: Any) -> RepoConfig:
    return RepoConfig.from_dict(repo_row.name, dict(repo_row.config_json or {}))


@router.get(
    "/factory/{repo}/acceptance",
    response_model=AssignmentsOut,
    responses={401: _ERR, 404: _ERR},
    summary="Tickets whose calibration build needs a second person's held-out acceptance tests",
)
def list_assignments(
    repo: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> AssignmentsOut:
    get_repo_or_404(db, repo)
    home = FactoryHome(settings.home, repo)
    events = home.events()
    authored = home.authored()
    records = load_held_out(db, repo)
    may_write = ROLE_RANK.get(viewer.role, -1) >= ROLE_RANK["operator"]
    out: list[AssignmentOut] = []
    for item in _items(home):
        a = assignment(
            item,
            events,
            authored.get(item.id),
            records,
            viewer=viewer.id,
            viewer_may_write=may_write,
        )
        if a is not None:
            out.append(AssignmentOut(**a))
    return AssignmentsOut(repo=repo, assignments=out)


@router.post(
    "/factory/{repo}/items/{item_id}/acceptance",
    response_model=HeldOutRecordOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Write the held-out acceptance tests of a calibration build (a second person)",
)
def write_assignment(  # noqa: PLR0917 — FastAPI dependencies + path/body
    repo: str,
    item_id: str,
    body: HeldOutIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> HeldOutRecordOut:
    repo_row = get_repo_or_404(db, repo)
    home = FactoryHome(settings.home, repo)
    item = next((i for i in _items(home) if i.id == item_id), None)
    if item is None:
        raise ApiError(404, "not_found", f"no item {item_id!r} in the backlog of {repo!r}")
    authored = home.authored().get(item_id)
    if authored is None or not authored.operator_authored:
        raise ApiError(
            409,
            "acceptance_not_needed",
            "held-out acceptance tests grade a calibration build on a ticket that carries a "
            "person's failing test; this ticket carries none",
        )
    chain = home.events()
    events = [e for e in chain if e.item_id == item_id]
    grant = latest_grant(events)
    if grant is None:
        raise ApiError(
            409,
            "no_calibration_build",
            "no calibration build is funded for this ticket: an approver funds one first",
        )
    if grant.event_id in spent_grants(events):
        raise ApiError(
            409,
            "build_started",
            "the calibration build has started: tests written now could not be held out",
        )
    if any(e.kind == EV_BUILD for e in events):
        raise ApiError(
            409,
            "already_built",
            "the ticket was built before, so its next attempt is never graded on held-out tests",
        )
    refused = writer_refusal(
        operator.id,
        ticket_authors=ticket_authors(chain, item_id, authored.author),
        sponsor=str(grant.payload.get("approver", "")),
    )
    if refused:
        raise ApiError(403, "acceptance_same_person", refused)
    config = _config(repo_row)
    files = _checked_files(body, config, authored.path)
    record = HeldOutTests(
        repo=repo,
        item_id=item_id,
        grant=grant.event_id,
        files=tuple(files),
        author=f"operator:{operator.id}",
        written_at=utc_now_iso(),
        capability_class=item.capability_class,
        size=item.size_estimate,
        language=config.language.value,
    )
    try:
        write_held_out(factory, record)
    except AcceptanceRefused as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    return HeldOutRecordOut(**record.public())


def _checked_files(body: HeldOutIn, config: RepoConfig, ticket_test: str) -> list[tuple[str, str]]:
    """The files as written, or 422 naming the first that cannot hold a held-out test."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for f in body.files:
        path = f.path.strip()
        why = path_refusal(path)
        if not why and path in seen:
            why = f"{path!r} is named twice"
        if not why and path == ticket_test:
            why = f"{path!r} is a file the ticket already carries: choose another name"
        if not why and not config.is_test(path):
            why = f"{path!r} is not a test file under this repository's layout"
        if not why and redact(f.content) != f.content:
            why = f"{path!r} holds text shaped like a credential: remove it"
        if why:
            raise ApiError(422, "validation_error", why, detail={"field": "files", "path": path})
        seen.add(path)
        out.append((path, f.content))
    return out


__all__ = ["router"]
