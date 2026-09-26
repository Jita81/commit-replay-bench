"""``/grades``, ``/tasks/{repo}/{task_id}``, ``/evidence/{pack_hash}`` — the audit surface.

These routes serialise ``grades`` rows STRAIGHT FROM THE STORE, column by column,
without constructing :class:`~crb.core.ledger.GradeRow`. That is deliberate:
``GradeRow.__post_init__`` refuses a false-Q1 row, so a row that somehow bypassed
the write path (tampering, a hand-written INSERT) would be unreadable through the
core type — and an auditor must be able to SEE the offending row. ``/grades`` shows
every row exactly as stored, chain fields included; ``/ledger/verify`` says whether
the chain and the floor hold; the capability routes (which reduce rows to numbers)
still go through ``GradeRow`` and therefore refuse with ``409 false_q1_refused``.

``/evidence/{hash}`` returns the stored pack body and ``verified`` = the canonical
SHA-256 of the body equals the key it was stored under (and, for a native pack, its
own ``pack_hash`` field).

Kept patches (ADR-0006 amendment of 2026-09-25). Every graded attempt keeps its patch at
grade time (:mod:`crb.core.patches`): redacted, capped, content-addressed under
``<home>/evidence/patches`` and named in the pack's ``notes.patch``. ``/grades/{row_hash}/patch``
serves those kept bytes FIRST (``X-CRB-Patch-Source: store``) — no worktree needed — and
falls back to a retained worktree only for a row that kept none.

Retained artefacts (ADR-0006 amendment). A run queued with ``retain.worktrees`` /
``retain.transcripts`` leaves the graded worktree under the worker's scratch and the
redacted transcript under ``<home>/transcripts/<run>``; nothing is stored twice.
``/grades/{row_hash}/patch`` serves the unified diff of that worktree, COMPUTED ON DEMAND
by the same procedure :meth:`crb.core.workspace.Workspace.diff_stats` hashed at grade
time (``git diff HEAD`` + every untracked file against ``/dev/null``, in path order),
redacted, capped at :data:`PATCH_MAX_BYTES`; the response says whether the bytes it
computed still hash to the pack's ``diff_sha256`` (``X-CRB-Patch-Verified``) and whether
redaction or the cap changed what was served (``X-CRB-Redacted`` / ``X-CRB-Truncated``).
The pack's hash is the anchor; a review attests to it (``/reviews``).
``/grades/{row_hash}/transcript`` serves the retained transcript file the pack refers
to — only from inside the transcripts directory. Both answer **404** with a one-line
``reason`` when the artefact was never retained or is gone.

Navigation
----------
What it is:   The audit route module — ``/grades``, ``/tasks/{repo}/{task_id}``,
              ``/evidence/{hash}`` and the retained patch / transcript behind a graded row.
What it does: Serves ledger rows exactly as stored (column by column, without the core
              type, so a false-Q1 row that bypassed the write path stays VISIBLE to an
              auditor); serves a pack with ``verified`` = its recomputed hash equals its
              key; recomputes a retained worktree's diff on demand by the grader's own
              procedure and says in headers whether it still hashes to the pack's anchor;
              refuses any transcript reference outside the transcripts directory.
How:          Filtered ``select(Grade)`` pages → ``grade_to_dict``; ``retained_status``
              decides reachability with a reason per artefact (the kept patch first);
              ``kept_patch`` reads ``notes.patch`` → ``PatchStore.get``;
              ``build_retained_patch`` = ``retained_patch_text`` → hash → redact → cap → headers.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/ledger.py (``GradeRow`` field order = ``ROW_FIELDS``),
              src/crb/core/evidence.py (``verify_pack``, canonical hashing; ``pack_diff_sha256``
              in src/crb/core/review.py is the review's anchor),
              src/crb/core/workspace.py (``diff_stats`` — the procedure the patch route
              must match byte-for-byte), src/crb/core/patches.py (the kept patch it serves
              first), src/crb/server/routes/reviews.py (attests to the served patch),
              src/crb/server/routes/ledger.py (reuses ``grade_to_dict`` for verify / export),
              ui/src/screens/Runs (the evidence drill-down; its contract is
              docs/API.md#tasks--grades--evidence)
Tested by:    tests/test_server_routes_grades.py, tests/test_server_routes_reviews.py,
              tests/test_patches.py
Touch when:   never for a new repository; when ``Workspace.diff_stats`` changes how it
              assembles the hashed text (``retained_patch_text`` must change identically —
              the reviews test is the drift guard); when ``GradeRow`` gains a field (the
              filters and docs/API.md).
Claims:       ``verified: true`` on a pack means the stored bytes hash to their key — not
              that the pack's contents are a sound measurement
              (docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from crb.core.evidence import canonical_json, sha256_text, verify_pack
from crb.core.git import GitError, GitRepo
from crb.core.ledger import GradeRow
from crb.core.patches import PatchStore, kept_patch_note
from crb.core.redact import redact
from crb.core.review import pack_diff_sha256
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.schemas import (
    EvidenceResponse,
    GradeRowOut,
    Page,
    PageDep,
    TaskDetail,
    TaskSpecOut,
)
from crb.server.schemas_review import RetainedArtefactStatus
from crb.store.models import EvidencePackRow, Grade, Run, Task

router = APIRouter(tags=["grades"])
_ERR = {"model": ErrorEnvelope}

#: A served patch is capped here (the hash is computed over the FULL diff first).
PATCH_MAX_BYTES = 1024 * 1024
#: The response headers the patch route answers with.
HDR_DIFF_SHA = "X-CRB-Diff-SHA256"  # the pack's anchor
HDR_PATCH_SHA = "X-CRB-Patch-SHA256"  # what the worktree hashes to now
HDR_VERIFIED = "X-CRB-Patch-Verified"  # the two are equal
HDR_REDACTED = "X-CRB-Redacted"  # redaction changed the served bytes
HDR_TRUNCATED = "X-CRB-Truncated"  # the cap changed the served bytes
HDR_SERVED_SHA = "X-CRB-Served-SHA256"  # what the served bytes hash to
HDR_SOURCE = "X-CRB-Patch-Source"  # "store" (kept at grade time) | "worktree" (retained)
PATCH_MEDIA_TYPE = "text/x-diff; charset=utf-8"
#: Where a served patch came from.
SOURCE_STORE = "store"
SOURCE_WORKTREE = "worktree"

#: The hashed body of a row, in ``GradeRow`` field order (``labels`` is stored as ``labels_json``).
ROW_FIELDS: tuple[str, ...] = tuple(GradeRow.__dataclass_fields__)


def grade_to_dict(g: Grade) -> dict[str, Any]:
    """:meth:`GradeRow.to_dict` shape from the ORM row, plus the store's ``seq``."""
    d: dict[str, Any] = {}
    for k in ROW_FIELDS:
        d[k] = dict(g.labels_json or {}) if k == "labels" else getattr(g, k)
    d["seq"] = g.seq
    return d


def grade_out(g: Grade) -> GradeRowOut:
    """The ORM row as the API serves it (no ``GradeRow`` construction — see the module
    docstring for why a false-Q1 row must still be readable here)."""
    return GradeRowOut(**grade_to_dict(g))


def _apply_filters(q: Select[Any], filters: dict[str, Any]) -> Select[Any]:
    """Equality filters over ``Grade`` columns; ``None`` / ``""`` means "no filter"."""
    for name, value in filters.items():
        if value is None or value == "":
            continue
        column = getattr(Grade, name)
        q = q.where(column.is_(value) if isinstance(value, bool) else column == value)
    return q


@router.get(
    "/grades",
    response_model=Page[GradeRowOut],
    responses={401: _ERR},
    summary="Ledger rows as stored (chain order), with filters",
)
def list_grades(
    viewer: ViewerDep,
    db: DbDep,
    page: PageDep,
    *,
    repo: str | None = Query(default=None, max_length=64),
    run_id: str | None = Query(default=None, max_length=32),
    task_id: str | None = Query(default=None, max_length=64),
    clean: bool | None = Query(default=None),
    mode: str | None = Query(default=None, max_length=16),
    builder: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=128),
    provider: str | None = Query(default=None, max_length=64),
    capability_class: str | None = Query(default=None, max_length=64),
    size: str | None = Query(default=None, max_length=4),
    language: str | None = Query(default=None, max_length=16),
    pool: str | None = Query(default=None, max_length=16),
    process_step: str | None = Query(default=None, max_length=16),
    belt_set: str | None = Query(default=None, max_length=16),
    disqualified: bool | None = Query(default=None),
) -> Page[GradeRowOut]:
    del viewer
    filters = {
        "repo": repo,
        "run_id": run_id,
        "task_id": task_id,
        "clean": clean,
        "mode": mode,
        "builder": builder,
        "model": model,
        "provider": provider,
        "capability_class": capability_class,
        "size": size,
        "language": language,
        "pool": pool,
        "process_step": process_step,
        "belt_set": belt_set,
        "disqualified": disqualified,
    }
    q = _apply_filters(select(Grade), filters)
    c = _apply_filters(select(func.count(Grade.seq)), filters)
    total = int(db.execute(c).scalar_one())
    rows: list[Grade] = list(
        db.execute(q.order_by(Grade.seq).limit(page.limit).offset(page.offset)).scalars()
    )
    return Page[GradeRowOut](
        items=[grade_out(g) for g in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/grades/{row_id}", response_model=GradeRowOut, responses={401: _ERR, 404: _ERR})
def get_grade(row_id: str, viewer: ViewerDep, db: DbDep) -> GradeRowOut:
    del viewer
    g = db.execute(select(Grade).where(Grade.row_id == row_id)).scalar_one_or_none()
    if g is None:
        raise ApiError(404, "not_found", f"no grade row {row_id!r}")
    return grade_out(g)


@router.get(
    "/tasks/{repo}/{task_id}",
    response_model=TaskDetail,
    responses={401: _ERR, 404: _ERR},
    summary="A mined task's spec + every grade row for it",
)
def get_task(repo: str, task_id: str, viewer: ViewerDep, db: DbDep) -> TaskDetail:
    del viewer
    task = db.get(Task, (repo, task_id))
    if task is None:
        raise ApiError(404, "not_found", f"no task {task_id!r} in repo {repo!r}")
    rows = list(
        db.execute(
            select(Grade).where(Grade.repo == repo, Grade.task_id == task_id).order_by(Grade.seq)
        ).scalars()
    )
    return TaskDetail(
        spec=TaskSpecOut(**TaskSpec.from_dict(task.spec_json).to_dict()),
        grades=[grade_out(g) for g in rows],
    )


def pack_verified(pack_hash: str, body: dict[str, Any]) -> bool:
    """A native pack carries ``pack_hash`` (checked with :func:`verify_pack`); an imported
    pack is hashed whole (:func:`crb.core.legacy.imported_pack_hash` semantics). Either
    way the recomputed hash must equal the key the pack is stored under."""
    if "pack_hash" in body:
        return verify_pack(body) and body.get("pack_hash") == pack_hash
    return sha256_text(canonical_json(body)) == pack_hash


def evidence_out(row: EvidencePackRow) -> EvidenceResponse:
    """The stored pack with ``verified`` recomputed on every read."""
    body = dict(row.body_json or {})
    return EvidenceResponse(
        pack=body,
        verified=pack_verified(row.pack_hash, body),
        pack_hash=row.pack_hash,
        schema=str(body.get("schema", "")),
        repo=row.repo,
        task_id=row.task_id,
        run_id=row.run_id,
        created=row.created,
    )


def get_pack_row(session: Session, pack_hash: str) -> EvidencePackRow:
    """The pack row, or 404."""
    row = session.get(EvidencePackRow, pack_hash)
    if row is None:
        raise ApiError(404, "not_found", f"no evidence pack {pack_hash!r}")
    return row


@router.get(
    "/evidence/{pack_hash}",
    response_model=EvidenceResponse,
    responses={401: _ERR, 404: _ERR},
    summary="The evidence pack (redacted at write) + verified: recomputed hash matches",
)
def get_evidence(pack_hash: str, viewer: ViewerDep, db: DbDep) -> EvidenceResponse:
    del viewer
    return evidence_out(get_pack_row(db, pack_hash))


# ---------------------------------------------------------------------------
# Retained artefacts: the patch and the transcript behind a graded row
# ---------------------------------------------------------------------------


def worktree_path(scratch: Path, *, repo: str, task_id: str, run_id: str, trial: str) -> Path:
    """Where ``crb.core.run.run_task`` left a row's worktree when the run retained
    worktrees: ``<scratch>/run-<repo>-<task[:10]>-<run[:8]>-<trial>``."""
    return scratch / f"run-{repo}-{task_id[:10]}-{run_id[:8]}-{trial}"


def _worktree_of(home: Path, g: Grade) -> Path:
    """Where row ``g``'s retained worktree would be under ``<home>/scratch``."""
    return worktree_path(
        home / "scratch", repo=g.repo, task_id=g.task_id, run_id=g.run_id, trial=g.trial
    )


def retained_patch_text(root: Path) -> str:
    """The unified diff of a retained worktree, assembled EXACTLY as
    :meth:`crb.core.workspace.Workspace.diff_stats` assembled the text it hashed:
    ``git diff HEAD`` plus every untracked, non-ignored file diffed against
    ``/dev/null`` (``--no-index``), appended in path order.
    ``tests/test_server_routes_reviews.py`` pins the two to the same hash on a real
    worktree — that test is the drift guard."""
    repo = GitRepo(root)
    ws = Workspace(repo, root, sha="HEAD", parent="HEAD")
    text = repo.diff_text("HEAD", cwd=root)
    tracked = set(repo.diff_names("HEAD", cwd=root))
    for rel in ws.touched_files():
        if rel in tracked:
            continue
        p = root / rel
        if not p.is_file() or p.is_symlink():
            continue
        r = repo.run("diff", "--no-index", "--", "/dev/null", rel, cwd=root)
        if r.stdout:
            text += ("" if text.endswith("\n") or not text else "\n") + r.stdout
    return text


@dataclass(frozen=True)
class RetainedPatch:
    """What the patch route computed: the full text's hash, the bytes to serve, flags."""

    diff_sha256: str  # the pack's anchor
    patch_sha256: str  # sha256 of the full recomputed text
    body: str  # redacted, capped
    redacted: bool
    truncated: bool

    @property
    def verified(self) -> bool:
        return bool(self.diff_sha256) and self.patch_sha256 == self.diff_sha256

    @property
    def served_sha256(self) -> str:
        return sha256_text(self.body)

    def headers(self, source: str = SOURCE_WORKTREE) -> dict[str, str]:
        """The hash check as response headers, so a client can trust (or not) the body
        without re-reading the pack."""
        return {
            HDR_SOURCE: source,
            HDR_DIFF_SHA: self.diff_sha256,
            HDR_PATCH_SHA: self.patch_sha256,
            HDR_SERVED_SHA: self.served_sha256,
            HDR_VERIFIED: "true" if self.verified else "false",
            HDR_REDACTED: "true" if self.redacted else "false",
            HDR_TRUNCATED: "true" if self.truncated else "false",
            "Cache-Control": "no-store",
        }


def build_retained_patch(
    root: Path, diff_sha256: str, *, cap: int = PATCH_MAX_BYTES
) -> RetainedPatch:
    """Recompute, hash, redact, cap — in that order: the hash must be of the FULL,
    unredacted text so it can equal what the grader hashed at grade time."""
    text = retained_patch_text(root)
    full_hash = sha256_text(text)
    body = redact(text)
    redacted = body != text
    raw = body.encode("utf-8")
    truncated = len(raw) > cap
    if truncated:
        body = raw[:cap].decode("utf-8", errors="ignore")
    return RetainedPatch(diff_sha256, full_hash, body, redacted, truncated)


def kept_patch(home: Path, pack: dict[str, Any] | None) -> tuple[RetainedPatch | None, str]:
    """The patch kept at grade time (crb.core.patches) for ``pack``, as a
    :class:`RetainedPatch`, or ``(None, reason)``. The stored bytes must hash to the
    ``stored_sha256`` the pack recorded (the store refuses anything else); ``verified`` is
    the pack's diff anchor equal to the full text's hash the pack recorded — for a red
    attempt with no diff anchor the pack's own record is the anchor."""
    note = kept_patch_note(pack)
    stored = str(note.get("stored_sha256", "") or "")
    if not note:
        return (
            None,
            "the evidence pack kept no patch (written before patches were kept, or the store is off)",
        )
    if not stored:
        return (
            None,
            f"the patch could not be kept at grade time: {note.get('error', 'no hash recorded')}",
        )
    data = PatchStore.under(home / "evidence").get(stored)
    if data is None:
        return None, "the kept patch is missing or no longer hashes to the name the pack recorded"
    anchor = pack_diff_sha256(pack) if pack else ""
    full = str(note.get("sha256", "") or "")
    return (
        RetainedPatch(
            diff_sha256=anchor or full,
            patch_sha256=full,
            body=data.decode("utf-8", errors="replace"),
            redacted=bool(note.get("redacted")),
            truncated=bool(note.get("truncated")),
        ),
        "",
    )


def _grade_by_hash(session: Session, row_hash: str) -> Grade:
    """The row by its chain hash (the identity a review attests to), or 404."""
    g = session.execute(select(Grade).where(Grade.row_hash == row_hash)).scalar_one_or_none()
    if g is None:
        raise ApiError(404, "not_found", f"no grade row with row_hash {row_hash[:12]}…")
    return g


def _run_retention(session: Session, run_id: str) -> tuple[bool, bool]:
    """``(worktrees, transcripts)`` the run asked to retain (``params.retain`` or the
    legacy ``keep_worktrees`` / ``keep_transcripts`` flags)."""
    run = session.get(Run, run_id) if run_id else None
    if run is None:
        return False, False
    params = dict(run.params_json or {})
    retain = dict(params.get("retain") or {})
    return (
        bool(retain.get("worktrees") or params.get("keep_worktrees")),
        bool(retain.get("transcripts") or params.get("keep_transcripts")),
    )


def _transcript_ref(pack: dict[str, Any] | None) -> str:
    """The transcript path a pack refers to (``builder.transcript_ref``, else ``notes``)."""
    if not pack:
        return ""
    builder = pack.get("builder")
    ref = str(builder.get("transcript_ref", "") or "") if isinstance(builder, dict) else ""
    if not ref:
        notes = pack.get("notes")
        ref = str(notes.get("transcript_ref", "") or "") if isinstance(notes, dict) else ""
    return ref


def _transcript_file(home: Path, ref: str) -> tuple[Path | None, str]:
    """The transcript file for ``ref`` if it lies inside ``<home>/transcripts`` — a
    reference anywhere else is refused, never opened (a pack is data, not a path)."""
    if not ref:
        return None, "the builder transcript was not retained (retain.transcripts was off)"
    base = (home / "transcripts").resolve()
    try:
        path = Path(ref).resolve()
    except OSError:
        return None, "the transcript reference is not a readable path"
    if base not in path.parents:
        return None, "the transcript reference points outside the transcripts directory — refused"
    if not path.is_file():
        return None, "the retained transcript no longer exists (removed by the retention sweep)"
    return path, ""


def retained_status(session: Session, home: Path, g: Grade) -> RetainedArtefactStatus:
    """What is reachable for row ``g`` right now, with a one-line reason per artefact."""
    pack_row = session.get(EvidencePackRow, g.evidence_pack_hash) if g.evidence_pack_hash else None
    pack = dict(pack_row.body_json or {}) if pack_row is not None else None
    diff_sha = pack_diff_sha256(pack) if pack else ""
    wt, tr = _run_retention(session, g.run_id)
    root = _worktree_of(home, g)
    kept, kept_reason = kept_patch(home, pack)
    if kept is not None:
        tpath, treason = _transcript_file(home, _transcript_ref(pack))
        return RetainedArtefactStatus(
            row_hash=g.row_hash,
            run_id=g.run_id,
            retain_worktrees=wt,
            retain_transcripts=tr,
            patch_available=True,
            patch_reason="",
            transcript_available=tpath is not None,
            transcript_reason=treason,
            diff_sha256=kept.diff_sha256,
            extra={"patch_source": SOURCE_STORE},
        )
    if pack is None:
        patch_ok, patch_reason = (
            False,
            "the row has no stored evidence pack — nothing to anchor a patch to",
        )
    elif not diff_sha:
        patch_ok, patch_reason = (
            False,
            "the evidence pack records no diff (the trial changed nothing)",
        )
    elif not root.is_dir():
        patch_ok, patch_reason = (
            False,
            (
                "the retained worktree no longer exists (removed by retention)"
                if wt
                else "the run did not retain worktrees (retain.worktrees was off) and none exists"
            ),
        )
    elif not (root / ".git").exists():
        patch_ok, patch_reason = False, "the retained directory is not a git worktree"
    else:
        patch_ok, patch_reason = True, ""
    if not patch_ok and pack is not None:
        patch_reason = f"{patch_reason}; {kept_reason}"
    tpath, treason = _transcript_file(home, _transcript_ref(pack))
    return RetainedArtefactStatus(
        row_hash=g.row_hash,
        run_id=g.run_id,
        retain_worktrees=wt,
        retain_transcripts=tr,
        patch_available=patch_ok,
        patch_reason=patch_reason,
        transcript_available=tpath is not None,
        transcript_reason=treason,
        diff_sha256=diff_sha,
        extra={"worktree": str(root), "patch_source": SOURCE_WORKTREE} if patch_ok else {},
    )


@router.get(
    "/grades/{row_hash}/retained",
    response_model=RetainedArtefactStatus,
    responses={401: _ERR, 404: _ERR},
    summary="Whether the row's retained patch / transcript are reachable, with reasons",
)
def get_grade_retained(
    row_hash: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> RetainedArtefactStatus:
    del viewer
    return retained_status(db, Path(settings.home), _grade_by_hash(db, row_hash))


@router.get(
    "/grades/{row_hash}/patch",
    responses={
        200: {"content": {"text/x-diff": {}}, "description": "The unified diff, redacted"},
        401: _ERR,
        404: _ERR,
    },
    summary="The attempt's unified diff — kept at grade time, else from a retained worktree (redacted, ≤ 1 MiB); headers carry the hash check",
)
def get_grade_patch(row_hash: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep) -> Response:
    del viewer
    g = _grade_by_hash(db, row_hash)
    home = Path(settings.home)
    status = retained_status(db, home, g)
    if not status.patch_available:
        raise ApiError(
            404,
            "patch_unavailable",
            status.patch_reason,
            detail={"reason": status.patch_reason, **status.model_dump(exclude={"extra"})},
        )
    if status.extra.get("patch_source") == SOURCE_STORE:
        pack_row = db.get(EvidencePackRow, g.evidence_pack_hash)
        kept, _ = kept_patch(home, dict(pack_row.body_json or {}) if pack_row else None)
        if kept is not None:
            return Response(
                content=kept.body, media_type=PATCH_MEDIA_TYPE, headers=kept.headers(SOURCE_STORE)
            )
    root = _worktree_of(home, g)
    try:
        patch = build_retained_patch(root, status.diff_sha256)
    except GitError as exc:
        reason = f"git could not read the retained worktree: {redact(str(exc))[:300]}"
        raise ApiError(404, "patch_unavailable", reason, detail={"reason": reason}) from exc
    return Response(content=patch.body, media_type=PATCH_MEDIA_TYPE, headers=patch.headers())


@router.get(
    "/grades/{row_hash}/transcript",
    responses={
        200: {"content": {"application/json": {}}, "description": "The retained transcript file"},
        401: _ERR,
        404: _ERR,
    },
    summary="The retained (redacted) builder transcript the row's pack refers to",
)
def get_grade_transcript(
    row_hash: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> Response:
    del viewer
    g = _grade_by_hash(db, row_hash)
    status = retained_status(db, Path(settings.home), g)
    if not status.transcript_available:
        raise ApiError(
            404,
            "transcript_unavailable",
            status.transcript_reason,
            detail={"reason": status.transcript_reason, **status.model_dump(exclude={"extra"})},
        )
    pack_row = db.get(EvidencePackRow, g.evidence_pack_hash)
    body = dict(pack_row.body_json or {}) if pack_row is not None else None
    path, _ = _transcript_file(Path(settings.home), _transcript_ref(body))
    assert path is not None  # retained_status said so
    # redacted at write by the adapter; passed through again as defence in depth
    text = redact(path.read_text(encoding="utf-8", errors="replace"))
    try:
        json.loads(text)
        media = "application/json"
    except ValueError:
        media = "text/plain; charset=utf-8"
    return Response(content=text, media_type=media, headers={"Cache-Control": "no-store"})


__all__ = [
    "HDR_DIFF_SHA",
    "HDR_PATCH_SHA",
    "HDR_REDACTED",
    "HDR_SERVED_SHA",
    "HDR_SOURCE",
    "HDR_TRUNCATED",
    "HDR_VERIFIED",
    "PATCH_MAX_BYTES",
    "ROW_FIELDS",
    "RetainedPatch",
    "build_retained_patch",
    "evidence_out",
    "grade_out",
    "grade_to_dict",
    "kept_patch",
    "pack_verified",
    "retained_patch_text",
    "retained_status",
    "router",
    "worktree_path",
]
