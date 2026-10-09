"""``/ledger/*`` — verify the chain, export it, export the abstract cells, import rows.

``/ledger/verify`` never raises: it walks the ``grades`` table in ``seq`` order,
recomputes every ``row_hash`` from the STORED columns (the same canonical body
:class:`~crb.core.ledger.GradeRow` hashes, without constructing one — a tampered
or false-Q1 row must be REPORTED, not hidden behind an exception), checks each
``prev_hash`` link, and counts false-Q1 over the stored belts; it also counts the clean
rows measured here whose evidence pack is absent or does not re-hash to its name, and
walks the sign-off and review chains (``signoffs`` / ``reviews``) and the audit trail's
own chain (``events``, ADR-0029), serving the grade and event heads — the last
``row_hash`` of each — as values an operator records outside the store (G-601). ``ok`` is
``chain_ok and false_q1_total == 0 and clean_without_pack == 0``, both of the sign-off and
review chains intact and ``events.chain_ok``.

``/ledger/export`` streams the stored rows verbatim (chain fields included), so an
UNFILTERED JSONL export verifies standalone with
:func:`crb.core.ledger.verify_chain`; a ``repo``-filtered export is a subsequence —
each row's own hash still verifies, the ``prev_hash`` links do not.

``/ledger/import`` accepts crb JSONL rows only. Census rows (``repo/task/clean`` with
no ``schema``) need their task files and repo configs to be classified honestly;
the error points at ``crb ledger import-census``.

Navigation
----------
What it is:   The ``/ledger/*`` route module — verify the chain, export it, export the
              abstract cells, import crb JSONL rows.
What it does: ``verify`` walks the stored rows recomputing every hash from the columns (a
              tampered or false-Q1 row is REPORTED, never hidden behind an exception),
              re-counts false-Q1 in SQL, walks the ``events`` chain (only the new events
              between full walks; in full on an operator's ``?full=true``), serves both
              heads and the ``disqualified`` block — rows disqualified per builder over the
              last seven days against DL-312's threshold, the Ledger tile's figure (G-400);
              ``export`` streams rows verbatim as JSONL (verifies standalone when
              unfiltered) or formula-safe CSV; ``export/abstract`` emits
              only the allowlisted cell fields; every export first commits one
              ``ledger.exported`` event naming who took it, the format and the filter;
              ``import`` re-chains foreign rows, skips ones already held, and refuses
              census rows (they need tasks and configs).
How:          Batched ``select(Grade)`` by ``seq`` → ``row_hash_from_stored`` (belt-set
              aware, as ``GradeRow.body`` is) → the ``LedgerVerifyOut``; export = generator
              → ``StreamingResponse``; import = ``parse_import`` → dedupe → ``import_rows``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0007-abstract-cell-export-only.md, docs/adr/0011-repo-lint-belt.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/core/ledger.py (``GradeRow.body`` — the hashing this must mirror),
              src/crb/store/ledger.py (``import_rows`` / ``count``),
              src/crb/store/events.py (``verify_events_in`` — the audit trail's walk),
              src/crb/core/federated.py (``export_abstract`` and its allowlist),
              src/crb/server/routes/grades.py (``grade_to_dict`` / ``ROW_FIELDS``) and
              src/crb/server/routes/system.py (``disqualified_counts`` — the block verify
              serves),
              src/crb/server/routes/signoffs.py (``FALSE_Q1_PREDICATE``),
              src/crb/server/routes/runs.py (``append_system_event`` — the export's audit
              event, DATA-RETENTION §4),
              src/crb/cli/commands/ledger.py (the CLI twin, incl. ``import-census``, whose
              verify procedure REPRODUCING-THE-CENSUS walks end to end)
Tested by:    tests/test_server_routes_ledger.py, tests/test_ledger_disqualified.py
Touch when:   never for a new repository; when ``GradeRow.body`` changes what it hashes
              (``row_hash_from_stored`` must change identically, and the ADR); when a
              field is added to the abstract export (that is the allowlist in
              src/crb/core/federated.py plus docs/DATA-RETENTION.md#5-cross-organisation-sharing).
Claims:       ``ok: true`` from verify means the chain is intact and false-Q1 = 0 over the
              stored belts at that moment — a statement about the ledger's integrity, not
              about any cell's capability
              (docs/EVIDENCE-AND-CLAIMS.md#2-clean-semantic-q1-and-false-q1).
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import canonical_json, sha256_text
from crb.core.federated import export_abstract
from crb.core.grade import BELT_NAMES, OPTIONAL_BELT_NAMES, FalseQ1Violation
from crb.core.ledger import (
    GENESIS_HASH,
    PROVENANCE_MEASURED,
    RECORDED_BELTS,
    GradeRow,
    LedgerIntegrityError,
    verify_chain,
)
from crb.core.redact import redact
from crb.observability.events import StepStatus
from crb.server.auth import AdminDep, OperatorDep, ViewerDep, require_role_now
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.grades import ROW_FIELDS, grade_to_dict, pack_verified
from crb.server.routes.reviews import verify_reviews
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.routes.signoffs import FALSE_Q1_PREDICATE, verify_signoffs
from crb.server.routes.system import disqualified_counts
from crb.server.schemas import (
    ChainVerifyOut,
    DisqualifiedOut,
    EventsVerifyOut,
    LedgerImportOut,
    LedgerVerifyOut,
)
from crb.server.schemas_review import ReviewVerifyOut
from crb.store.events import EventChainVerifier, verify_events_in
from crb.store.ledger import DbLedger
from crb.store.models import EvidencePackRow, Grade

router = APIRouter(tags=["ledger"])
_ERR = {"model": ErrorEnvelope}

EXPORT_BATCH = 1000
MAX_IMPORT_BYTES = 64 * 1024 * 1024
FORMATS: tuple[str, ...] = ("jsonl", "csv")
#: Hashed labels the CSV export also carries as their own columns, beside ``builder`` and
#: ``model``, so a reading can be re-derived outside the product (ADR-0026 items 1 and 9): the
#: context arm and the class-set version never pool, so a reader must be able to split on them.
EXPORT_LABEL_COLUMNS: tuple[str, ...] = ("context_arm", "taxonomy")

#: Census row markers (``bench.py`` output): a verdict keyed by ``task``/``wave`` with no schema.
_CENSUS_KEYS = frozenset({"task", "wave", "blind_mode", "regraded_calm"})


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def row_hash_from_stored(g: Grade) -> str:
    """Recompute ``row_hash`` from the stored columns — the same canonical body
    :meth:`GradeRow.body` produces: every field but ``row_hash``, ``labels`` as a dict,
    minus any optional belt the row's ``belt_set`` does not record (ADR-0011: a
    ``v4`` / ``v3-legacy`` row never hashed ``repo_lint_clean``). An unknown ``belt_set``
    (a tampered row) hashes every belt and fails the comparison as it should."""
    recorded = RECORDED_BELTS.get(g.belt_set, BELT_NAMES)
    unrecorded = set(OPTIONAL_BELT_NAMES) - set(recorded)
    body = {
        k: v
        for k, v in grade_to_dict(g).items()
        if k not in ("row_hash", "seq") and k not in unrecorded
    }
    return sha256_text(canonical_json(body))


def _iter_grades(session: Session, batch: int = EXPORT_BATCH) -> Iterator[Grade]:
    """Every row in ``seq`` order, keyset-paged so a large ledger never loads at once."""
    last = 0
    while True:
        chunk = list(
            session.execute(select(Grade).where(Grade.seq > last).order_by(Grade.seq).limit(batch))
            .scalars()
            .all()
        )
        if not chunk:
            return
        yield from chunk
        last = chunk[-1].seq


def verify_ledger(
    session: Session, *, events_verifier: EventChainVerifier | None = None, full: bool = False
) -> LedgerVerifyOut:
    """The chain walk + false-Q1 in SQL + the clean rows with no evidence to show
    (:func:`clean_without_pack`) + the sign-off and review chains (EI-6) + the audit trail's
    chain + the ``disqualified`` count per builder over the last seven days
    (:func:`crb.server.routes.system.disqualified_counts`, G-400); never raises — the first break is reported by ``seq`` and the walk continues to
    count rows. The audit trail is walked by ``events_verifier`` (the app's, which re-hashes
    only new events between full walks — P-257) or, without one, in full."""
    rows = 0
    prev = GENESIS_HASH
    broken_at: int | None = None
    detail = ""
    for g in _iter_grades(session):
        rows += 1
        if broken_at is None:
            if g.prev_hash != prev:
                broken_at, detail = g.seq, f"seq {g.seq}: prev_hash mismatch"
            elif g.row_hash != row_hash_from_stored(g):
                broken_at, detail = g.seq, f"seq {g.seq}: row_hash mismatch (row edited)"
        prev = g.row_hash
    fq1 = int(
        session.execute(
            select(func.count(Grade.seq)).where(Grade.clean.is_(True), FALSE_Q1_PREDICATE)
        ).scalar_one()
    )
    no_pack = clean_without_pack(session)
    signoffs = verify_signoffs(session)
    reviews = verify_reviews(session)
    others = [
        (name, chain)
        for name, chain in (("sign-off", signoffs), ("review", reviews))
        if not chain.chain_ok
    ]
    chain_ok = broken_at is None
    if chain_ok and fq1 == 0 and no_pack == 0:
        detail = f"{rows} rows, chain intact, false_q1=0"
    elif chain_ok:
        detail = f"chain intact but false_q1={fq1}, clean_without_pack={no_pack}"
    if others:
        detail += "; " + "; ".join(f"{n} chain broken at {c.detail}" for n, c in others)
    events = (
        events_verifier.verify(session, full=full)
        if events_verifier is not None
        else verify_events_in(session)
    )
    if not events.ok:
        detail = f"{detail}; events chain broken — {events.detail}"
    return LedgerVerifyOut(
        rows=rows,
        ok=chain_ok and fq1 == 0 and no_pack == 0 and not others and events.ok,
        false_q1_total=fq1,
        chain_ok=chain_ok,
        broken_at=broken_at,
        detail=detail,
        clean_without_pack=no_pack,
        signoffs=_chain(signoffs),
        reviews=_chain(reviews),
        verified_at=_now(),
        head_row_hash=prev if rows else "",
        events=EventsVerifyOut(**events.to_dict()),
        # the rising-disqualified stop condition, served beside the chains (G-400, DL-312):
        # a count the Ledger tile and OPERATOR §8 read; it never changes ``ok``
        disqualified=DisqualifiedOut(**disqualified_counts(session)),
    )


def _chain(v: ChainVerifyOut | ReviewVerifyOut) -> ChainVerifyOut:
    """The chain part of a table's verify answer (rows, chain_ok, broken_at, detail)."""
    return ChainVerifyOut(rows=v.rows, chain_ok=v.chain_ok, broken_at=v.broken_at, detail=v.detail)


def clean_without_pack(session: Session) -> int:
    """Clean rows MEASURED HERE with no evidence to show for their Q1: an empty
    ``evidence_pack_hash``, a pack the ``evidence`` table does not hold, or a stored pack
    that does not re-hash to its name (:func:`pack_verified`). An imported row cites a pack
    of its source's; it licenses nothing here, and only its empty hash is counted (the
    write gate refuses that at construction anyway) — EI-3, 2026-09-27."""
    empty = int(
        session.execute(
            select(func.count(Grade.seq)).where(
                Grade.clean.is_(True), Grade.evidence_pack_hash == ""
            )
        ).scalar_one()
    )
    measured_clean = (
        select(Grade.seq, Grade.evidence_pack_hash, EvidencePackRow.body_json)
        .outerjoin(EvidencePackRow, EvidencePackRow.pack_hash == Grade.evidence_pack_hash)
        .where(
            Grade.clean.is_(True),
            Grade.provenance == PROVENANCE_MEASURED,
            Grade.evidence_pack_hash != "",
        )
        .order_by(Grade.seq)
    )
    unproven = 0
    for _seq, pack_hash, body in session.execute(measured_clean):
        if body is None or not pack_verified(str(pack_hash), dict(body)):
            unproven += 1
    return empty + unproven


@router.get(
    "/ledger/verify",
    response_model=LedgerVerifyOut,
    responses={401: _ERR},
    summary="Walk the hash chain and re-count false-Q1 over the stored belts (never raises)",
)
def ledger_verify(
    request: Request,
    viewer: ViewerDep,
    db: DbDep,
    full: bool = Query(
        False,
        description="Re-hash every audit event now rather than only those appended since the "
        "last full walk (operator; each is a walk of the whole trail)",
    ),
) -> LedgerVerifyOut:
    if full:
        require_role_now(viewer, "operator")
    return verify_ledger(db, events_verifier=events_verifier(request.app), full=full)


def events_verifier(app: Any) -> EventChainVerifier:
    """The app's one audit-trail verifier (made on first use)."""
    v = getattr(app.state, "events_verifier", None)
    if v is None:
        v = app.state.events_verifier = EventChainVerifier()
    return v


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _export_rows(factory: sessionmaker[Session], repo: str | None) -> Iterator[dict[str, Any]]:
    """Stored rows as ``GradeRow.to_dict`` shapes (the store's ``seq`` removed), streamed
    from their own session so the response can outlive the request's session."""
    with factory() as s:
        last = 0
        while True:
            q = select(Grade).where(Grade.seq > last)
            if repo:
                q = q.where(Grade.repo == repo)
            chunk = list(s.execute(q.order_by(Grade.seq).limit(EXPORT_BATCH)).scalars().all())
            if not chunk:
                return
            for g in chunk:
                d = grade_to_dict(g)
                d.pop("seq", None)
                yield d
            last = chunk[-1].seq


def _jsonl(factory: sessionmaker[Session], repo: str | None) -> Iterator[bytes]:
    """One sorted-keys JSON object per line — byte-identical to ``DbLedger.export_jsonl``."""
    for d in _export_rows(factory, repo):
        yield (json.dumps(d, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


#: Leading characters a spreadsheet would treat as a formula (CSV injection).
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_value(v: Any) -> str:
    """Cell text: nulls empty, bools ``true``/``false``, mappings/lists as JSON, and any
    free-text value that starts like a formula prefixed with ``'`` so an exported error
    string can never execute in a spreadsheet."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Mapping | list):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    if isinstance(v, str) and v.startswith(_FORMULA_LEADERS):
        return "'" + v
    return str(v)


def _csv(factory: sessionmaker[Session], repo: str | None) -> Iterator[bytes]:
    """Header row then one row per grade, every cell through ``_csv_value``."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow((*ROW_FIELDS, *EXPORT_LABEL_COLUMNS))
    yield buf.getvalue().encode("utf-8")
    for d in _export_rows(factory, repo):
        buf.seek(0)
        buf.truncate()
        labels = dict(d.get("labels") or {})
        w.writerow(
            [
                *(_csv_value(d.get(k)) for k in ROW_FIELDS),
                *(_csv_value(labels.get(k, "")) for k in EXPORT_LABEL_COLUMNS),
            ]
        )
        yield buf.getvalue().encode("utf-8")


#: The audit action every ledger export writes (G-184; docs/DATA-RETENTION.md §4).
LEDGER_EXPORTED = "ledger.exported"
#: The one trace every export event lands on, so "who took the ledger" is one read.
EXPORT_TRACE = system_trace_id("ledger", "exports")
_EXPORT_RECORD_TRIES = 3


def record_export(db: Session, *, actor: str, fmt: str, repo: str | None) -> None:
    """Commit one ``ledger.exported`` event naming who took the export, in what format and
    with what filter, BEFORE the first byte streams: an export that cannot be recorded is not
    served. Two exports at the same moment race for the trace's next ``seq`` (unique); the
    loser re-reads it and tries again."""
    for attempt in range(_EXPORT_RECORD_TRIES):
        append_system_event(
            db,
            trace_id=EXPORT_TRACE,
            action=LEDGER_EXPORTED,
            repo=repo or "",
            actor=actor,
            payload={"format": fmt, "filter": {"repo": repo} if repo else {}, "at": _now()},
        )
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            if attempt == _EXPORT_RECORD_TRIES - 1:
                raise


@router.get(
    "/ledger/export",
    responses={401: _ERR, 422: _ERR},
    summary="Stream the ledger (JSONL verifies standalone when unfiltered; CSV has a header)",
    response_class=StreamingResponse,
)
def ledger_export(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    format: str = Query(default="jsonl", max_length=8),  # API.md names it `format`
    repo: str | None = Query(default=None, max_length=64),
) -> StreamingResponse:
    if format not in FORMATS:
        raise ApiError(
            422, "validation_error", f"format must be one of {FORMATS}", detail={"format": format}
        )
    record_export(db, actor=viewer.id, fmt=format, repo=repo)
    suffix = f"-{repo}" if repo else ""
    if format == "csv":
        body, media = _csv(factory, repo), "text/csv; charset=utf-8"
    else:
        body, media = _jsonl(factory, repo), "application/x-ndjson"
    return StreamingResponse(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="crb-ledger{suffix}.{format}"'},
    )


@router.get(
    "/ledger/export/abstract",
    responses={401: _ERR, 403: _ERR, 409: _ERR},
    summary="Abstract cells only (allowlisted fields; no repo, no ids, no code) — operator",
    response_class=StreamingResponse,
)
def ledger_export_abstract(
    operator: OperatorDep, db: DbDep, factory: SessionFactoryDep
) -> StreamingResponse:
    cells = export_abstract(DbLedger(factory).rows())  # a refused export (409) is not recorded
    record_export(db, actor=operator.id, fmt="abstract", repo=None)

    def _body() -> Iterator[bytes]:
        for c in cells:
            yield (json.dumps(c, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(
        _body(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="crb-abstract-cells.jsonl"'},
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _looks_like_census(d: Mapping[str, Any]) -> bool:
    """A ``bench.py`` verdict line (no schema, no task_id, census-only keys)."""
    return "schema" not in d and "task_id" not in d and bool(_CENSUS_KEYS & set(d))


def parse_import(text: str) -> tuple[list[GradeRow], int]:
    """JSONL → rows. Census rows are refused (they need tasks + configs); a row the
    ledger's invariants refuse is refused with its line number."""
    rows: list[GradeRow] = []
    read = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        read += 1
        try:
            d = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ApiError(
                422, "validation_error", f"line {line_no}: not JSON", detail={"line": line_no}
            ) from exc
        if not isinstance(d, Mapping):
            raise ApiError(
                422, "validation_error", f"line {line_no}: not an object", detail={"line": line_no}
            )
        if _looks_like_census(d):
            raise ApiError(
                422,
                "census_import_unsupported",
                f"line {line_no} is a census row (bench.py verdict); the HTTP importer accepts "
                "crb ledger rows only",
                detail={
                    "line": line_no,
                    "use": "crb ledger import-census --grades <grades.jsonl> "
                    "--tasks-dir <state/> --configs <configs.json>",
                },
            )
        try:
            rows.append(GradeRow.from_dict(d))
        except FalseQ1Violation as exc:
            raise ApiError(
                409,
                "false_q1_refused",
                f"line {line_no}: {redact(str(exc))}",
                detail={"line": line_no},
            ) from exc
        except (ValueError, TypeError) as exc:
            raise ApiError(
                422,
                "validation_error",
                f"line {line_no}: {redact(str(exc))}",
                detail={"line": line_no},
            ) from exc
    return rows, read


@router.post(
    "/ledger/import",
    response_model=LedgerImportOut,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 413: _ERR, 422: _ERR},
    summary="Import crb JSONL rows (admin); re-chained here, source hashes kept in labels",
)
def ledger_import(
    file: UploadFile, admin: AdminDep, db: DbDep, factory: SessionFactoryDep
) -> LedgerImportOut:
    """Import crb JSONL rows. Every row is stamped as imported inside its hashed body
    (:func:`crb.store.ledger.import_stamp`) and the import is one ``ledger.imported``
    event naming the admin, the file's SHA-256, the counts and whether the file's own
    chain verified. A file whose own chain is broken is still imported (re-chained) and
    says so on the response and the event. An imported row never licenses anything: the
    sign-off and the route the delivery gate reads count rows measured here only."""
    raw = file.file.read(MAX_IMPORT_BYTES + 1)  # read one byte past the cap to detect overflow
    if len(raw) > MAX_IMPORT_BYTES:
        raise ApiError(413, "payload_too_large", f"import exceeds {MAX_IMPORT_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(422, "validation_error", "file is not UTF-8") from exc
    rows, read = parse_import(text)
    source_chain_ok: bool | None
    try:
        verify_chain(rows)
        source_chain_ok = True
    except LedgerIntegrityError:
        source_chain_ok = False
    if not rows:
        source_chain_ok = None
    existing_ids = _existing(db, Grade.row_id, [r.row_id for r in rows])
    existing_packs = _existing(
        db, Grade.evidence_pack_hash, [r.evidence_pack_hash for r in rows if r.evidence_pack_hash]
    )
    # Dedupe on row_id AND on pack hash: a re-import of a re-chained export carries new
    # row hashes but the same ids and packs, and must not double-count.
    fresh = [
        r
        for r in rows
        if r.row_id not in existing_ids
        and not (r.evidence_pack_hash and r.evidence_pack_hash in existing_packs)
    ]
    ledger = DbLedger(factory)
    file_sha256 = hashlib.sha256(raw).hexdigest()
    chained = (
        ledger.import_rows(
            fresh, imported_by=admin.id, imported_at=_now(), import_sha256=file_sha256
        )
        if fresh
        else []
    )
    out = LedgerImportOut(
        imported=len(chained),
        skipped=len(rows) - len(fresh),
        read=read,
        rows=ledger.count(),
        source_chain_ok=source_chain_ok,
    )
    _record_import(db, admin_id=admin.id, file_sha256=file_sha256, out=out, rows=chained)
    return out


def _record_import(
    db: Session, *, admin_id: str, file_sha256: str, out: LedgerImportOut, rows: list[GradeRow]
) -> None:
    """The import's one audit event (``system/ledger.imported``), committed: who, which
    file, the counts, whether the source chain verified — and, when it did not, that the
    rows were accepted anyway, re-chained and stamped, and license nothing."""
    note = "rows re-chained onto this ledger and stamped imported; they license nothing"
    if out.source_chain_ok is False:
        note = "the file's own chain is broken; " + note
    append_system_event(
        db,
        trace_id=system_trace_id("ledger", "import"),
        action="ledger.imported",
        actor=admin_id,
        status=StepStatus.OK,
        payload={
            "file_sha256": file_sha256,
            "read": out.read,
            "imported": out.imported,
            "skipped": out.skipped,
            "source_chain_ok": out.source_chain_ok,
            "provenance": sorted({r.provenance for r in rows}) or [],
            "repos": sorted({r.repo for r in rows}),
            "first_row_hash": rows[0].row_hash if rows else "",
            "last_row_hash": rows[-1].row_hash if rows else "",
            "note": note,
        },
    )
    db.commit()


#: ``IN (...)`` lists are chunked to this many values: SQLite caps bound parameters
#: (999 on older builds, 32766 now) and Postgres dislikes a 100k-value list; a census
#: import carries thousands of rows (CodeRabbit on PR #4, 2026-09-15).
IN_CHUNK = 500


def _existing(db: Session, column: Any, values: list[str]) -> set[str]:
    """The subset of ``values`` already present in ``column``, queried in chunks."""
    found: set[str] = set()
    wanted = sorted(set(values))
    for i in range(0, len(wanted), IN_CHUNK):
        chunk = wanted[i : i + IN_CHUNK]
        present: Iterable[object] = db.execute(select(column).where(column.in_(chunk))).scalars()
        found.update(str(v) for v in present)
    return found


__all__ = [
    "EXPORT_BATCH",
    "EXPORT_TRACE",
    "FORMATS",
    "LEDGER_EXPORTED",
    "MAX_IMPORT_BYTES",
    "clean_without_pack",
    "parse_import",
    "record_export",
    "router",
    "row_hash_from_stored",
    "verify_ledger",
]
