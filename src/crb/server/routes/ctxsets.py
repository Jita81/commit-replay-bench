"""``/ctxsets`` — store a context set, read one's metadata, and compare two runs of one set.

A context set (ADR-0050) is a content-addressed record of one brief per task, named
``ctx.<source>.<digest[:12]>``. Its arm is **measurement-only**: no reading certifies it,
no route licenses it, no value or north-star figure counts it. The one place its rows are
read is the paired, fail-closed comparison served here.

* ``POST /ctxsets`` (operator) parses the body, verifies it against the repository's
  registered tasks (coverage) and, for a placebo, against the stored set it is matched to;
  then writes it once under ``<home>/ctxsets/<digest>.json``. The same body again is
  idempotent; a different body at one digest is 409 ``ctxset_conflict``. Each store is a
  ``system/ctxset.stored`` event; an identical retry writes that event when an earlier store
  published the file but never committed it. The file is published from a per-request
  temporary file by an atomic link that never replaces an existing one, so two identical
  submissions racing each other both answer the idempotent result.
* ``GET /ctxsets/compare?control=RUN&treatment=RUN`` (viewer) pairs the two runs' rows task
  by task (:func:`crb.core.ctx_compare.ctx_pair`); a refusal is 422 with its reason as the
  code. It is declared before ``GET /ctxsets/{name}`` so ``compare`` is never read as a name.
* ``GET /ctxsets/{name}`` (viewer) returns the set's metadata and task count, never an
  entry's text.

Navigation
----------
What it is:   The ``/ctxsets`` route module: the operator's store, the metadata read and the
              paired comparison of a context set's runs.
What it does: Maps :class:`~crb.core.ctxset.CtxSetRefused` and
              :class:`~crb.core.ctx_compare.CtxPairRefused` to 422 with the reason as the code;
              writes a set content-addressed and never overwrites a different body; loads the
              sets a comparison's rows name from the store.
How:          ``ctxset.parse`` → ``verify_coverage`` (+ ``verify_placebo``) → publish (a
              per-request temporary file, hard-linked into place) → ``append_system_event``
              → commit; ``rows_of_runs`` → ``ctx_pair``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0050-context-set-arms.md, docs/adr/0052-stated-requirements-source.md
Works with:   src/crb/core/ctxset.py (the record and its verifiers), src/crb/core/ctx_compare.py
              (the paired reader), src/crb/store/ledger.py (``rows_of_runs``),
              src/crb/cli/commands/ctxset.py (the CLI over these routes), docs/API.md (the
              Context sets table and the ``ctxset.stored`` event row)
Tested by:    tests/test_server_ctxsets.py
Touch when:   never for a new repository; the set record, its store layout or the comparison's
              refusals change (mirror docs/API.md#context-sets).
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, status
from sqlalchemy import select

from crb.core.context_arm import LABEL_CTX_SET
from crb.core.ctx_compare import CtxPairRefused, ctx_pair
from crb.core.ctxset import (
    REASON_PLACEBO_UNMATCHED,
    CtxSet,
    CtxSetRefused,
    canonical_json,
    parse,
    verify_coverage,
    verify_placebo,
)
from crb.core.spec import TaskSpec
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.routes.runs import (
    CTXSET_DIR,
    append_system_event,
    repo_task_specs,
    system_trace_id,
)
from crb.server.settings import Settings
from crb.store.events import lock_event_writes
from crb.store.ledger import rows_of_runs
from crb.store.models import Event, Repo, Run

router = APIRouter(tags=["ctxsets"])

_ERR: dict[str, Any] = {"model": ErrorEnvelope}

#: A different body already stored at one digest (never overwritten).
REFUSAL_CONFLICT = "ctxset_conflict"
#: The ``system`` event each stored set carries, once (on its trace ``ctxset:<digest>``).
ACTION_STORED = "ctxset.stored"
#: A stored set the request names (a placebo's treatment, a comparison's set) is absent.
REFUSAL_NOT_STORED = "ctxset_not_stored"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^ctx\.([a-z-]+)\.([0-9a-f]{12})$")


def store_dir(settings: Settings) -> Path:
    """``<home>/ctxsets`` — where the operator's sets live, one file per digest (the layout
    ``crb.server.routes.runs.stored_ctxset`` reads at submit and the worker at claim)."""
    return Path(settings.home) / CTXSET_DIR


def load_set(settings: Settings, digest: str) -> CtxSet | None:
    """The stored set at ``digest`` (re-parsed, so its digest is re-checked), or ``None``."""
    if not _DIGEST_RE.match(digest):
        return None
    path = store_dir(settings) / f"{digest}.json"
    if not path.is_file():
        return None
    ctxset = parse(path.read_text(encoding="utf-8"))
    if ctxset.digest != digest:
        raise ApiError(409, REFUSAL_CONFLICT, f"the stored set at {digest[:12]} is not its digest")
    return ctxset


def find_by_name(settings: Settings, name: str) -> CtxSet | None:
    """The stored set named ``ctx.<source>.<hex12>``, or ``None`` (an unknown or ambiguous
    prefix is not found)."""
    m = _NAME_RE.match(name)
    root = store_dir(settings)
    if m is None or not root.is_dir():
        return None
    hits = sorted(root.glob(f"{m.group(2)}*.json"))
    found = [s for s in (load_set(settings, p.stem) for p in hits) if s is not None]
    match = [s for s in found if s.name == name]
    return match[0] if len(match) == 1 else None


def _refused(exc: CtxSetRefused | CtxPairRefused) -> ApiError:
    return ApiError(422, exc.reason, str(exc.detail), detail={"reason": exc.reason})


def _meta(ctxset: CtxSet) -> dict[str, Any]:
    """What a viewer may read of a set: never an entry's text (nor a stated item's statement).
    A stated set (ADR-0052) also names its structure, what its author saw and its items
    digest (the key a structure contrast links by); those fields are empty on a v1 set."""
    return {
        "name": ctxset.name,
        "digest": ctxset.digest,
        "schema": ctxset.schema,
        "arm": ctxset.arm,
        "source": ctxset.source,
        "kind": ctxset.kind,
        "stated": ctxset.stated,
        "structure": ctxset.structure,
        "saw": list(ctxset.saw),
        "items_digest": ctxset.items_digest,
        "repo": ctxset.repo,
        "method": ctxset.method,
        "matched_to": ctxset.matched_to,
        "drafter": ctxset.drafter,
        "hindsight": ctxset.hindsight,
        "measurement_only": True,
        "tasks": len(ctxset.task_ids),
    }


def _repo_tasks(db: DbDep, repo: str) -> list[TaskSpec]:
    if db.get(Repo, repo) is None:
        raise ApiError(404, "not_found", f"repository {repo!r} is not registered")
    return repo_task_specs(db, repo)


@router.post(
    "/ctxsets",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Store a context set (operator): verified, content-addressed, never overwritten",
)
def store_ctxset(
    operator: OperatorDep,
    db: DbDep,
    settings: SettingsDep,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    try:
        ctxset = parse(body)
        verify_coverage(ctxset, _repo_tasks(db, ctxset.repo))
        if ctxset.placebo:
            treatment = load_set(settings, ctxset.matched_to)
            if treatment is None:
                raise CtxSetRefused(
                    REASON_PLACEBO_UNMATCHED,
                    f"the placebo's treatment {ctxset.matched_to[:12]} is not stored",
                )
            verify_placebo(treatment, ctxset)
    except CtxSetRefused as exc:
        raise _refused(exc) from exc
    text = canonical_json(ctxset.to_doc())
    path = store_dir(settings) / f"{ctxset.digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    published = not path.is_file() and _publish(path, text)
    if not published:
        _same_body(path, text, ctxset)  # stored before, or a concurrent request won
        _sync_dir(path.parent)  # a retry acknowledges only a name that is on disk
    _sync_dir(path.parent.parent)  # the store directory's own name, created on a first store
    # every stored set carries exactly one event, checked and written under the events lock:
    # a retry of a store that published the file but never committed its event records it,
    # and a retry racing this request's own publish never leaves a second one
    lock_event_writes(db)
    if not _stored_event_exists(db, ctxset):
        _append_stored_event(db, ctxset, operator.id)
    db.commit()
    return {**_meta(ctxset), "stored": published}


def _same_body(path: Path, text: str, ctxset: CtxSet) -> None:
    """Refuse 409 when ``path`` holds a body other than ``text``: a set is never overwritten."""
    if path.read_text(encoding="utf-8") != text:
        raise ApiError(
            409,
            REFUSAL_CONFLICT,
            f"a different body is stored at {ctxset.digest[:12]}; a set is never overwritten",
        )


def _publish(path: Path, text: str) -> bool:
    """Write ``text`` to ``path`` atomically, never replacing an existing file: the body goes
    to a temporary file unique to this request, then is hard-linked into place (``link``
    fails when the destination exists, so two identical submissions cannot race on one
    temporary name or replace each other). ``False`` when ``path`` already existed."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        # the file keeps the owner-only mode ``mkstemp`` gave it: the server is its one reader
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())  # the body is on disk before its name is published
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        return True
    finally:
        tmp.unlink(missing_ok=True)
        _sync_dir(path.parent)  # the name is on disk before the stored event is committed


def _sync_dir(directory: Path) -> None:
    """Flush ``directory``'s entries to disk, so a published name survives a machine failure."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stored_event_exists(db: DbDep, ctxset: CtxSet) -> bool:
    trace_id = system_trace_id("ctxset", ctxset.digest)
    found = db.execute(
        select(Event.id).where(Event.trace_id == trace_id, Event.action == ACTION_STORED).limit(1)
    ).first()
    return found is not None


def _append_stored_event(db: DbDep, ctxset: CtxSet, actor: str) -> None:
    append_system_event(
        db,
        trace_id=system_trace_id("ctxset", ctxset.digest),
        action=ACTION_STORED,
        repo=ctxset.repo,
        actor=actor,
        payload={
            "digest": ctxset.digest,
            "name": ctxset.name,
            "source": ctxset.source,
            "repo": ctxset.repo,
            "tasks": len(ctxset.task_ids),
        },
    )


@router.get(
    "/ctxsets/compare",
    responses={401: _ERR, 404: _ERR, 422: _ERR},
    summary="Pair a control run with a context-set run, task by task (fail-closed)",
)
def compare_ctxsets(
    _viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    control: Annotated[str, Query(min_length=1)],
    treatment: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    for run_id in (control, treatment):
        if db.get(Run, run_id) is None:
            raise ApiError(404, "not_found", f"run {run_id!r} not found")
    c_rows = rows_of_runs(db, [control])
    t_rows = rows_of_runs(db, [treatment])
    sets: dict[str, CtxSet] = {}
    for digest in sorted({r.labels.get(LABEL_CTX_SET, "") for r in (*c_rows, *t_rows)}):
        if not digest:
            continue
        found = load_set(settings, digest)
        if found is None:
            raise ApiError(
                404, REFUSAL_NOT_STORED, f"the rows name a set {digest[:12]} that is not stored"
            )
        sets[digest] = found
    t_digests = {r.labels.get(LABEL_CTX_SET, "") for r in t_rows}
    tset = sets.get(next(iter(t_digests))) if len(t_digests) == 1 else None
    if tset is not None and tset.placebo and tset.matched_to not in sets:
        matched = load_set(settings, tset.matched_to)
        if matched is not None:
            sets[matched.digest] = matched
    try:
        pair = ctx_pair(c_rows, t_rows, task_ids=tset.task_ids if tset else (), sets=sets)
    except CtxPairRefused as exc:
        raise _refused(exc) from exc
    return {"control_run": control, "treatment_run": treatment, **pair.to_dict()}


@router.get(
    "/ctxsets/{name}",
    responses={401: _ERR, 404: _ERR},
    summary="A stored context set's metadata and task count (never an entry's text)",
)
def get_ctxset(name: str, _viewer: ViewerDep, settings: SettingsDep) -> dict[str, Any]:
    found = find_by_name(settings, name)
    if found is None:
        raise ApiError(404, "not_found", f"context set {name!r} is not stored")
    return _meta(found)


__all__ = [
    "ACTION_STORED",
    "REFUSAL_CONFLICT",
    "REFUSAL_NOT_STORED",
    "find_by_name",
    "load_set",
    "router",
    "store_dir",
]
