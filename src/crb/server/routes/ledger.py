"""``/ledger/*`` — verify the chain, export it, export the abstract cells, import rows.

``/ledger/verify`` never raises: it walks the ``grades`` table in ``seq`` order,
recomputes every ``row_hash`` from the STORED columns (the same canonical body
:class:`~crb.core.ledger.GradeRow` hashes, without constructing one — a tampered
or false-Q1 row must be REPORTED, not hidden behind an exception), checks each
``prev_hash`` link, and counts false-Q1 over the stored belts. ``ok`` is
``chain_ok and false_q1_total == 0 and clean_without_pack == 0``.

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
              tampered or false-Q1 row is REPORTED, never hidden behind an exception) and
              re-counts false-Q1 in SQL; ``export`` streams rows verbatim as JSONL (verifies
              standalone when unfiltered) or formula-safe CSV; ``export/abstract`` emits
              only the allowlisted cell fields; ``import`` re-chains foreign rows, skips
              ones already held, and refuses census rows (they need tasks and configs).
How:          Batched ``select(Grade)`` by ``seq`` → ``row_hash_from_stored`` (belt-set
              aware, as ``GradeRow.body`` is) → the ``LedgerVerifyOut``; export = generator
              → ``StreamingResponse``; import = ``parse_import`` → dedupe → ``import_rows``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0007-abstract-cell-export-only.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/ledger.py (``GradeRow.body`` — the hashing this must mirror),
              src/crb/store/ledger.py (``import_rows`` / ``count``),
              src/crb/core/federated.py (``export_abstract`` and its allowlist),
              src/crb/server/routes/grades.py (``grade_to_dict`` / ``ROW_FIELDS``),
              src/crb/server/routes/signoffs.py (``FALSE_Q1_PREDICATE``),
              src/crb/cli/commands/ledger.py (the CLI twin, incl. ``import-census``),
              docs/REPRODUCING-THE-CENSUS.md (the verify procedure end to end)
Tested by:    tests/test_server_routes_ledger.py
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
import io
import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.evidence import canonical_json, sha256_text
from crb.core.federated import export_abstract
from crb.core.grade import BELT_NAMES, OPTIONAL_BELT_NAMES, FalseQ1Violation
from crb.core.ledger import (
    GENESIS_HASH,
    RECORDED_BELTS,
    GradeRow,
    LedgerIntegrityError,
    verify_chain,
)
from crb.core.redact import redact
from crb.server.auth import AdminDep, OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.grades import ROW_FIELDS, grade_to_dict
from crb.server.routes.signoffs import FALSE_Q1_PREDICATE
from crb.server.schemas import LedgerImportOut, LedgerVerifyOut
from crb.store.ledger import DbLedger
from crb.store.models import Grade

router = APIRouter(tags=["ledger"])
_ERR = {"model": ErrorEnvelope}

EXPORT_BATCH = 1000
MAX_IMPORT_BYTES = 64 * 1024 * 1024
FORMATS: tuple[str, ...] = ("jsonl", "csv")

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


def verify_ledger(session: Session) -> LedgerVerifyOut:
    """The chain walk + the two SQL counts (false-Q1, clean-without-pack); never raises —
    the first break is reported by ``seq`` and the walk continues to count rows."""
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
    no_pack = int(
        session.execute(
            select(func.count(Grade.seq)).where(
                Grade.clean.is_(True), Grade.evidence_pack_hash == ""
            )
        ).scalar_one()
    )
    chain_ok = broken_at is None
    if chain_ok and fq1 == 0 and no_pack == 0:
        detail = f"{rows} rows, chain intact, false_q1=0"
    elif chain_ok:
        detail = f"chain intact but false_q1={fq1}, clean_without_pack={no_pack}"
    return LedgerVerifyOut(
        rows=rows,
        ok=chain_ok and fq1 == 0 and no_pack == 0,
        false_q1_total=fq1,
        chain_ok=chain_ok,
        broken_at=broken_at,
        detail=detail,
        clean_without_pack=no_pack,
        verified_at=_now(),
    )


@router.get(
    "/ledger/verify",
    response_model=LedgerVerifyOut,
    responses={401: _ERR},
    summary="Walk the hash chain and re-count false-Q1 over the stored belts (never raises)",
)
def ledger_verify(viewer: ViewerDep, db: DbDep) -> LedgerVerifyOut:
    del viewer
    return verify_ledger(db)


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
    w.writerow(ROW_FIELDS)
    yield buf.getvalue().encode("utf-8")
    for d in _export_rows(factory, repo):
        buf.seek(0)
        buf.truncate()
        w.writerow([_csv_value(d.get(k)) for k in ROW_FIELDS])
        yield buf.getvalue().encode("utf-8")


@router.get(
    "/ledger/export",
    responses={401: _ERR, 422: _ERR},
    summary="Stream the ledger (JSONL verifies standalone when unfiltered; CSV has a header)",
    response_class=StreamingResponse,
)
def ledger_export(
    viewer: ViewerDep,
    factory: SessionFactoryDep,
    format: str = Query(default="jsonl", max_length=8),  # API.md names it `format`
    repo: str | None = Query(default=None, max_length=64),
) -> StreamingResponse:
    del viewer
    if format not in FORMATS:
        raise ApiError(
            422, "validation_error", f"format must be one of {FORMATS}", detail={"format": format}
        )
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
def ledger_export_abstract(operator: OperatorDep, factory: SessionFactoryDep) -> StreamingResponse:
    del operator
    cells = export_abstract(DbLedger(factory).rows())

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
    del admin
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
    imported = ledger.import_rows(fresh) if fresh else 0
    return LedgerImportOut(
        imported=imported,
        skipped=len(rows) - len(fresh),
        read=read,
        rows=ledger.count(),
        source_chain_ok=source_chain_ok,
    )


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
    "FORMATS",
    "MAX_IMPORT_BYTES",
    "parse_import",
    "router",
    "row_hash_from_stored",
    "verify_ledger",
]
