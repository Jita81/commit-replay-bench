"""``/signoffs`` — human attestations; the verification tier is EARNED, never asserted.

The ``signoffs`` table is append-only and hash-chained on its own (``prev_hash`` =
the previous sign-off's ``row_hash``; ``row_hash`` = SHA-256 of the canonical JSON
of the row minus ``row_hash``). A revocation is a new row with ``revoke=True`` for
the same scope; the latest row per ``(repo, scope)`` wins.

A sign-off is a policy decision, refused at write (``signoff-policy.v2``,
:mod:`crb.core.signoff`). ``POST /signoffs``:

1. counts the cell's **false-Q1** in SQL over the STORED belts (the same predicate
   ``/health`` uses) so a row that bypassed the write path is caught — ``> 0`` →
   **409 false_q1_refused**, first and non-overridable;
2. reduces the cell's rows under the ONE routing rule with the repo's latest
   negative-controls verdict (:func:`crb.server.routes.oracle.latest_controls_verdict`
   — the same helper the capability map routes under, so the two can never disagree)
   and measures the cell's **oracle strength** from the repo's task-level mutation
   scores (:func:`cell_oracle_strength`: the latest ``oracle.score`` per task, the same
   per-task reduction ``/oracle/{repo}`` serves, averaged over the cell's scored tasks;
   ``None`` when no task of the cell has been scored);
3. resolves the approver's **attestation** — the accepted row they name must exist in
   the ledger, belong to this cell and be ``clean`` (else **422**);
4. applies the policy (:func:`crb.core.signoff.evaluate_signoff`): a thin cell, a
   controls gate that failed / was never run / let a control escape / was thin, an
   **unmeasured** oracle (``oracle_unmeasured``, never overridable since v2), a weak
   oracle, a route other than ``deliver``, or a missing attestation → **409
   signoff_refused** with ``detail.code``, ``detail.thresholds`` and ``detail.observed``
   plus every failing clause; nothing is written and the refusal is recorded as a
   ``system/signoff.refused`` event;
5. stamps the whole decision (n, point, Wilson lower, false-Q1, oracle strength, route +
   reason code, controls verdict / run / k of N / escapes, the policy and its thresholds,
   the attestation) into the row, hash-covered.

``GET /signoffs/preview`` runs steps 1–4 without writing and answers what the record
WOULD carry and every refusal that would apply, plus the cell's accepted rows the
approver may name — the UI shows the bar before the approver tries.

At read, every listed attestation carries ``current_false_q1`` and ``active`` (latest
for its scope, not revoked, and the cell's CURRENT false-Q1 is 0); the capability /
forecast overlays use :func:`crb.core.signoff.apply_signoffs`, which refuses to lift a
cell whose false-Q1 is now > 0. A later violation auto-invalidates the attestation.

A deployment relaxes the numeric thresholds through ``CRB_SIGNOFF__*`` (see
``docs/API.md``); a value outside the published bounds — or an attempt to switch off a
non-overridable clause — makes every sign-off answer **503 signoff_policy_invalid**
rather than run under a bar nobody chose. A record signed under ``signoff-policy.v1``
is served with the version it was signed under; its chain still verifies.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import ValidationError
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from crb.core.capability import (
    WILDCARD,
    CapabilityCell,
    empty_cell,
    key_matches,
    measure_cell,
    task_oracle_strength,
)
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import (
    BELT_SET_V3_LEGACY,
    BELT_SET_V5,
    CELL_FIELDS,
    GENESIS_HASH,
    CellKey,
    GradeRow,
    LedgerIntegrityError,
)
from crb.core.redact import redact
from crb.core.routing import ControlsVerdict
from crb.core.signoff import (
    REFUSAL_FALSE_Q1,
    SIGNOFF_SCHEMA,
    SIGNOFF_SCHEMA_V1,
    Attestation,
    SignoffPolicy,
    SignoffRecord,
    SignoffRefusal,
    SignoffRefused,
    evaluate_signoff,
    resolve_oracle_strength,
    stamp_evidence,
)
from crb.core.version import APPARATUS_VERSION
from crb.observability.events import StepStatus
from crb.server.auth import ApproverDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope
from crb.server.routes.grades import grade_to_dict
from crb.server.routes.oracle import (
    latest_controls_verdict,
    oracle_by_task,
    verdict_dict,
)
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas import Page, PageDep, SignoffCreateRequest, SignoffRevokeRequest
from crb.server.schemas_capability import ControlsVerdictOut, FailureSplitOut
from crb.server.schemas_signoff import (
    AcceptedRowOut,
    AttestationIn,
    AttestationOut,
    SignoffControlsSnapshot,
    SignoffCreateWithAttestationRequest,
    SignoffEvidenceWithOracle,
    SignoffOracleOut,
    SignoffPolicyOut,
    SignoffPreviewEvidence,
    SignoffPreviewOut,
    SignoffRefusalOut,
    SignoffRouteOut,
    SignoffWithPolicyOut,
)
from crb.store.models import Grade, Repo, Signoff, Task

router = APIRouter(tags=["signoffs"])
_ERR = {"model": ErrorEnvelope}

#: Snapshot keys stored (as strings) next to the scope in ``cell_json``.
_EV_N = "evidence_n"
_EV_POINT = "evidence_point"
_EV_CI_LOW = "evidence_ci_low"
_EV_CI_HIGH = "evidence_ci_high"
_EV_FQ1 = "evidence_false_q1"
_EV_APPARATUS = "evidence_apparatus"
# signoff-policy.v1+ snapshot keys (absent on rows written before the policy).
_EV_ORACLE = "evidence_oracle_strength"
_POLICY_VERSION = "policy_version"
_POLICY_THRESHOLDS = "policy_thresholds"
_ROUTE = "route"
_ROUTE_REASON = "route_reason"
_ROUTE_REASON_CODE = "route_reason_code"
_CTL_VERDICT = "controls_verdict"
_CTL_RUN = "controls_run_id"
_CTL_CREATED = "controls_created"
_CTL_K = "controls_k"
_CTL_TOTAL = "controls_total"
_CTL_ESCAPES = "controls_escapes"
_ATT_TASK = "attestation_reviewed_task_id"
_ATT_ROW = "attestation_reviewed_row_hash"
_ATT_STATEMENT = "attestation_statement"
_ATT_AT = "attestation_at"

#: Envelope codes: the floor keeps its historical code; every policy clause is one.
CODE_FALSE_Q1 = "false_q1_refused"
CODE_REFUSED = "signoff_refused"
CODE_POLICY_INVALID = "signoff_policy_invalid"

#: How many accepted rows a preview lists for the attestation picker.
ACCEPTED_ROWS_LIMIT = 50

#: A clean row whose STORED belts are not all True (legacy rows: three belts).
FALSE_Q1_PREDICATE = or_(
    Grade.tests_unmodified.is_not(True),
    Grade.target_green.is_not(True),
    Grade.no_new_failures.is_not(True),
    (Grade.belt_set != BELT_SET_V3_LEGACY) & Grade.source_changed.is_not(True),
    # belt 5 exists only from v5 on: a recorded False is a violation, an absent value is not
    (Grade.belt_set == BELT_SET_V5) & Grade.repo_lint_clean.is_(False),
)


# ---------------------------------------------------------------------------
# Policy in force
# ---------------------------------------------------------------------------


def effective_policy() -> SignoffPolicy:
    """The sign-off policy this deployment runs under (``CRB_SIGNOFF__*``); fail closed
    on a value outside the published bounds."""
    try:
        return SignoffPolicy.from_env(os.environ)
    except ValueError as exc:
        raise ApiError(
            503,
            CODE_POLICY_INVALID,
            f"the sign-off policy is misconfigured: {exc}",
            detail={"prefix": "CRB_SIGNOFF__"},
        ) from exc


# ---------------------------------------------------------------------------
# Row hashing (the table's own chain)
# ---------------------------------------------------------------------------


def signoff_body(row: Signoff) -> dict[str, Any]:
    """Everything that is hashed: the row minus ``row_hash`` (and minus the store's ``seq``).
    ``cell_json`` carries the scope AND the whole evidence / policy / attestation
    snapshot, so all of it is chain-covered."""
    return {
        "signoff_id": row.signoff_id,
        "repo": row.repo,
        "cell": dict(row.cell_json or {}),
        "tier": row.tier,
        "verifier": row.verifier,
        "note": row.note,
        "revoke": bool(row.revoke),
        "evidence_rows": int(row.evidence_rows),
        "created": row.created,
        "prev_hash": row.prev_hash,
    }


def signoff_hash(row: Signoff) -> str:
    return sha256_text(canonical_json(signoff_body(row)))


def verify_signoff_rows(rows: Iterable[Signoff]) -> int:
    """Walk the sign-off chain in ``seq`` order; raise :class:`LedgerIntegrityError`."""
    prev = GENESIS_HASH
    n = 0
    for r in rows:
        n += 1
        if r.prev_hash != prev:
            raise LedgerIntegrityError(f"sign-off {n} ({r.signoff_id[:8]}) prev_hash mismatch")
        if r.row_hash != signoff_hash(r):
            raise LedgerIntegrityError(f"sign-off {n} ({r.signoff_id[:8]}) row_hash mismatch")
        prev = r.row_hash
    return n


def _lock(session: Session) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    elif dialect == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7332)"))


def _last_hash(session: Session) -> str:
    last = session.execute(
        select(Signoff.row_hash).order_by(Signoff.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return str(last) if last else GENESIS_HASH


def _chain_and_add(session: Session, row: Signoff) -> Signoff:
    row.prev_hash = _last_hash(session)
    row.row_hash = signoff_hash(row)
    session.add(row)
    return row


# ---------------------------------------------------------------------------
# Scope ↔ core records
# ---------------------------------------------------------------------------


def scope_of(row: Signoff) -> CellKey:
    cj = dict(row.cell_json or {})
    return CellKey(**{f: str(cj.get(f, WILDCARD) or WILDCARD) for f in CELL_FIELDS})


def _scope_key(row: Signoff) -> tuple[str, ...]:
    return (row.repo, *scope_of(row).to_tuple())


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _thresholds_of(cj: dict[str, str]) -> dict[str, Any]:
    raw = cj.get(_POLICY_THRESHOLDS, "")
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except ValueError:
        return {}
    return dict(d) if isinstance(d, dict) else {}


def _attestation_of(cj: dict[str, str]) -> Attestation | None:
    if not cj.get(_ATT_ROW):
        return None
    return Attestation(
        reviewed_task_id=str(cj.get(_ATT_TASK, "")),
        reviewed_row_hash=str(cj.get(_ATT_ROW, "")),
        statement=str(cj.get(_ATT_STATEMENT, "")),
        at=str(cj.get(_ATT_AT, "")),
    )


def to_record(row: Signoff) -> SignoffRecord:
    """The :class:`~crb.core.signoff.SignoffRecord` view of a stored row (for the overlay).
    A row written before the policy comes back as a ``crb.signoff.v1`` record."""
    cj = dict(row.cell_json or {})
    scope = scope_of(row)
    v2 = _POLICY_VERSION in cj
    return SignoffRecord(
        repo=row.repo,
        capability_class=scope.capability_class,
        verifier=row.verifier,
        size=scope.size,
        language=scope.language,
        builder=scope.builder,
        model=scope.model,
        provider=scope.provider,
        process_step=scope.process_step,
        tier=row.tier,
        note=row.note,
        revoked=bool(row.revoke),
        verified_at=row.created,
        n_at_signoff=_int(cj.get(_EV_N, row.evidence_rows)),
        point_at_signoff=_float_or_none(cj.get(_EV_POINT)) or 0.0,
        false_q1_at_signoff=_int(cj.get(_EV_FQ1, 0)),
        apparatus_version=str(cj.get(_EV_APPARATUS, "") or ""),
        ci_low_at_signoff=_float_or_none(cj.get(_EV_CI_LOW)) or 0.0,
        oracle_strength_at_signoff=_float_or_none(cj.get(_EV_ORACLE)),
        policy_version=str(cj.get(_POLICY_VERSION, "") or ""),
        policy_thresholds=_thresholds_of(cj),
        route_at_signoff=str(cj.get(_ROUTE, "") or ""),
        route_reason_code=str(cj.get(_ROUTE_REASON_CODE, "") or ""),
        controls_verdict=str(cj.get(_CTL_VERDICT, "") or ""),
        controls_run_id=str(cj.get(_CTL_RUN, "") or ""),
        controls_k=_int(cj.get(_CTL_K, 0)),
        controls_total=_int(cj.get(_CTL_TOTAL, 0)),
        controls_escapes=_int(cj.get(_CTL_ESCAPES, 0)),
        attestation=_attestation_of(cj) if not row.revoke else None,
        schema=SIGNOFF_SCHEMA if v2 else SIGNOFF_SCHEMA_V1,
        record_id=row.signoff_id,
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
    )


def load_signoff_rows(session: Session, repo: str | None = None) -> list[Signoff]:
    q = select(Signoff).order_by(Signoff.seq)
    if repo:
        q = q.where(Signoff.repo.in_([repo, WILDCARD]))
    return list(session.execute(q).scalars())


def load_signoff_records(session: Session, repo: str | None = None) -> list[SignoffRecord]:
    """Every stored sign-off (attestations and revocations) as core records, chain order.
    Feed these to :func:`crb.core.signoff.apply_signoffs_to_map`, which collapses to the
    latest per scope and re-checks the cell's current false-Q1."""
    return [to_record(r) for r in load_signoff_rows(session, repo)]


# ---------------------------------------------------------------------------
# Cell evidence from the ledger
# ---------------------------------------------------------------------------


def _scope_where(q: Any, repo: str, scope: CellKey) -> Any:
    q = q.where(Grade.repo == repo)
    for field in CELL_FIELDS:
        value = getattr(scope, field)
        if value != WILDCARD:
            q = q.where(getattr(Grade, field) == value)
    return q


def cell_false_q1(session: Session, repo: str, scope: CellKey) -> tuple[int, list[str]]:
    """``(count, row_ids)`` of clean rows in scope whose stored belts are not all True."""
    q = _scope_where(
        select(Grade.row_id).where(Grade.clean.is_(True), FALSE_Q1_PREDICATE), repo, scope
    )
    ids = [str(r) for r in session.execute(q.order_by(Grade.seq)).scalars()]
    return len(ids), ids


def cell_rows(session: Session, repo: str, scope: CellKey) -> list[GradeRow]:
    """The scope's SIGHTED rows on the CURRENT apparatus as :class:`GradeRow` (raises
    ``FalseQ1Violation`` on a bad row — call :func:`cell_false_q1` first so the refusal
    is explicit, not incidental). A sign-off is a claim about the current instrument on
    the sighted measurement: rows from an older belt set, or blind attempts, never lift
    the cell (EVIDENCE-AND-CLAIMS §5; the capability map applies the same defaults)."""
    q = (
        _scope_where(select(Grade), repo, scope)
        .where(Grade.mode == "sighted", Grade.apparatus_version == APPARATUS_VERSION)
        .order_by(Grade.seq)
    )
    return [GradeRow.from_dict(grade_to_dict(g)) for g in session.execute(q).scalars()]


def _projection(scope: CellKey) -> tuple[str, ...]:
    return tuple(f for f in CELL_FIELDS if getattr(scope, f) != WILDCARD)


def measured_cell(
    rows: Sequence[GradeRow],
    scope: CellKey,
    controls: ControlsVerdict,
    oracle_by_task: Mapping[str, float | None] | None = None,
) -> CapabilityCell:
    """The scope's cell routed under the repo's controls verdict and its task-level
    oracle scores — exactly as the capability map routes it; the honest-empty cell
    when there are no rows."""
    proj = _projection(scope)
    if not rows:
        return empty_cell(scope, proj)
    return measure_cell(rows, proj, controls=controls, oracle_by_task=oracle_by_task)


def _grade_key(g: Grade) -> CellKey:
    return CellKey(**{f: str(getattr(g, f) or "") for f in CELL_FIELDS})


@dataclass(frozen=True)
class CellOracle:
    """The cell's oracle strength as the repo's oracle ledger knows it: the mean of the
    latest task-level mutation score of every task in the cell that has a scoreable
    one (``strength``; ``None`` = no task of the cell was ever scored — *unmeasured*,
    never 0.0), with ``scored`` of ``tasks`` distinct tasks for the approver."""

    strength: float | None
    scored: int
    tasks: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "strength": None if self.strength is None else round(self.strength, 4),
            "scored": self.scored,
            "tasks": self.tasks,
        }


def cell_oracle_strength(
    session: Session,
    repo: str,
    rows: Sequence[GradeRow],
    *,
    by_task: Mapping[str, float | None] | None = None,
) -> CellOracle:
    """Measure the cell's oracle from the repo's ``oracle.score`` events — the same
    latest-per-task reduction ``GET /oracle/{repo}`` serves (:func:`oracle_report`), so
    the Oracle page and the sign-off can never disagree about a task's strength.

    The cell's tasks are the distinct ``task_id`` of its rows; a task whose latest score
    is unscoreable (``strength: null``) counts in ``tasks`` but not in ``scored``.
    """
    task_ids = {r.task_id for r in rows if r.task_id}
    if not task_ids:
        return CellOracle(None, 0, 0)
    if by_task is None:
        by_task = oracle_by_task(session, repo)
    scored = sum(1 for tid in task_ids if by_task.get(tid) is not None)  # unscoreable = None
    return CellOracle(task_oracle_strength(rows, by_task), scored, len(task_ids))


def _subjects(session: Session, repo: str, task_ids: Iterable[str]) -> dict[str, str]:
    ids = sorted(set(task_ids))
    if not ids:
        return {}
    q = select(Task.task_id, Task.subject).where(Task.repo == repo, Task.task_id.in_(ids))
    return {str(tid): str(subj or "") for tid, subj in session.execute(q)}


def accepted_rows(
    session: Session, repo: str, scope: CellKey, *, limit: int = ACCEPTED_ROWS_LIMIT
) -> list[AcceptedRowOut]:
    """The cell's accepted rows — clean and not disqualified — newest first, with the
    graded task's subject, for the attestation picker."""
    q = _scope_where(
        select(Grade).where(Grade.clean.is_(True), Grade.disqualified.is_(False)), repo, scope
    )
    grades = list(session.execute(q.order_by(Grade.seq.desc()).limit(limit)).scalars())
    subjects = _subjects(session, repo, (g.task_id for g in grades))
    return [
        AcceptedRowOut(
            row_hash=g.row_hash,
            row_id=g.row_id,
            task_id=g.task_id,
            subject=subjects.get(g.task_id, ""),
            created=g.created,
            run_id=g.run_id,
            trial=g.trial,
            builder=g.builder,
            model=g.model,
            evidence_pack_hash=g.evidence_pack_hash,
        )
        for g in grades
    ]


def _attestation_422(msg: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        msg,
        detail={
            "errors": [
                {
                    "loc": ["body", "attestation", "reviewed_row_hash"],
                    "msg": msg,
                    "type": "value_error",
                }
            ]
        },
    )


def resolve_attestation(
    session: Session, repo: str, scope: CellKey, att: AttestationIn
) -> tuple[Attestation, str]:
    """The approver's attestation with ``reviewed_task_id`` resolved from the ledger,
    plus the task's subject. 422 unless the row exists, is this repo's, sits in the
    cell and is an ACCEPTED row (clean, not disqualified) — an approver can only
    attest to a diff the instrument accepted."""
    g = session.execute(
        select(Grade).where(Grade.row_hash == att.reviewed_row_hash)
    ).scalar_one_or_none()
    if g is None:
        raise _attestation_422(f"no ledger row with row_hash {att.reviewed_row_hash[:12]}…")
    if g.repo != repo:
        raise _attestation_422(
            f"row {att.reviewed_row_hash[:12]}… belongs to repo {g.repo!r}, not {repo!r}"
        )
    if not key_matches(scope, _grade_key(g)):
        raise _attestation_422(
            f"row {att.reviewed_row_hash[:12]}… is in cell {_grade_key(g).label!r}, "
            f"outside the attested scope {scope.label!r}"
        )
    if not g.clean or g.disqualified:
        raise _attestation_422(
            f"row {att.reviewed_row_hash[:12]}… is not an accepted row "
            f"(clean={bool(g.clean)}, disqualified={bool(g.disqualified)}) — "
            "an approver attests to a diff the instrument accepted"
        )
    subject = _subjects(session, repo, [g.task_id]).get(g.task_id, "")
    return (
        Attestation(
            reviewed_task_id=g.task_id,
            reviewed_row_hash=g.row_hash,
            statement=att.statement,
            at=utc_now_iso(),
        ),
        subject,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _evidence(row: Signoff) -> SignoffEvidenceWithOracle:
    cj = dict(row.cell_json or {})
    apparatus = str(cj.get(_EV_APPARATUS, "") or "")
    return SignoffEvidenceWithOracle(
        n=_int(cj.get(_EV_N, row.evidence_rows)),
        point=_float_or_none(cj.get(_EV_POINT)) or 0.0,
        ci_low=_float_or_none(cj.get(_EV_CI_LOW)) or 0.0,
        ci_high=_float_or_none(cj.get(_EV_CI_HIGH)) or 0.0,
        false_q1=_int(cj.get(_EV_FQ1, 0)),
        apparatus_versions=[a for a in apparatus.split(",") if a],
        oracle_strength=_float_or_none(cj.get(_EV_ORACLE)),
    )


def _attestation_out(session: Session, row: Signoff) -> AttestationOut | None:
    cj = dict(row.cell_json or {})
    att = _attestation_of(cj) if not row.revoke else None
    if att is None:
        return None
    subject = _subjects(session, row.repo, [att.reviewed_task_id]).get(att.reviewed_task_id, "")
    return AttestationOut(**att.to_dict(), subject=subject)


def _revocation_for(row: Signoff, all_rows: Sequence[Signoff]) -> Signoff | None:
    key = _scope_key(row)
    for r in all_rows:
        if r.seq > row.seq and r.revoke and _scope_key(r) == key:
            return r
    return None


def _superseded(row: Signoff, all_rows: Sequence[Signoff]) -> bool:
    key = _scope_key(row)
    return any(r.seq > row.seq and not r.revoke and _scope_key(r) == key for r in all_rows)


def signoff_out(
    session: Session, row: Signoff, all_rows: Sequence[Signoff]
) -> SignoffWithPolicyOut:
    revocation = _revocation_for(row, all_rows)
    current_fq1, _ = (
        cell_false_q1(session, row.repo, scope_of(row)) if row.repo != WILDCARD else (0, [])
    )
    active = revocation is None and not _superseded(row, all_rows) and current_fq1 == 0
    cj = dict(row.cell_json or {})
    return SignoffWithPolicyOut(
        id=row.signoff_id,
        repo=row.repo,
        cell=scope_of(row).to_dict(),
        tier=row.tier,
        note=row.note,
        approver=row.verifier,
        created=row.created,
        revoked=revocation is not None,
        revoked_by=revocation.verifier if revocation is not None else None,
        revoked_at=revocation.created if revocation is not None else None,
        active=active,
        current_false_q1=current_fq1,
        evidence=_evidence(row),
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
        schema=SIGNOFF_SCHEMA if _POLICY_VERSION in cj else SIGNOFF_SCHEMA_V1,
        policy_version=str(cj.get(_POLICY_VERSION, "") or ""),
        policy_thresholds=_thresholds_of(cj),
        route=SignoffRouteOut(
            route=str(cj.get(_ROUTE, "") or ""),
            reason=str(cj.get(_ROUTE_REASON, "") or ""),
            reason_code=str(cj.get(_ROUTE_REASON_CODE, "") or ""),
        ),
        controls=SignoffControlsSnapshot(
            verdict=str(cj.get(_CTL_VERDICT, "") or ""),
            run_id=str(cj.get(_CTL_RUN, "") or ""),
            k=_int(cj.get(_CTL_K, 0)),
            total=_int(cj.get(_CTL_TOTAL, 0)),
            escapes=_int(cj.get(_CTL_ESCAPES, 0)),
            created=str(cj.get(_CTL_CREATED, "") or ""),
        ),
        attestation=_attestation_out(session, row),
    )


def _refusal_out(r: SignoffRefusal) -> SignoffRefusalOut:
    return SignoffRefusalOut(**r.to_dict())


def _observed(
    cell: CapabilityCell, controls: ControlsVerdict, oracle: CellOracle, policy: SignoffPolicy
) -> dict[str, Any]:
    s = cell.stats
    d = cell.decision
    strength = resolve_oracle_strength(cell, oracle_strength=oracle.strength)
    return {
        "n": cell.n,
        "n_tasks": cell.n_tasks,
        "point": None if s is None else round(s.point, 4),
        "ci_low": None if s is None else round(s.ci.low, 4),
        "false_q1": cell.false_q1,
        "oracle_strength": None if strength is None else round(strength, 4),
        "oracle": oracle.to_dict(),
        "route": cell.route,
        "reason_code": cell.reason_code,
        "controls": {
            "verdict": controls.state(
                min_share=policy.min_constructible_share, max_escapes=policy.max_controls_escapes
            ),
            "run_id": controls.run_id,
            "k": controls.constructible,
            "total": controls.total,
            "escapes": controls.escapes,
        },
        "route_decision": None if d is None else d.to_dict(),
    }


def _would_record(stamped: SignoffRecord) -> dict[str, Any]:
    """The snapshot a record would carry — the record minus its identity / chain fields."""
    d = stamped.to_dict()
    for k in ("record_id", "prev_hash", "row_hash", "verified_at", "verifier"):
        d.pop(k, None)
    return d


# ---------------------------------------------------------------------------
# The decision (shared by POST and preview)
# ---------------------------------------------------------------------------


def _refuse(
    db: Session,
    *,
    repo: str,
    actor: str,
    scope: CellKey,
    reason: str,
    detail: dict[str, Any],
    code: str = CODE_REFUSED,
) -> ApiError:
    """Record the refusal as a system event (committed) and build the 409."""
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", repo),
        action="signoff.refused",
        repo=repo,
        actor=actor,
        status=StepStatus.INVALID,
        error=reason,
        payload={"cell": scope.to_dict(), "envelope_code": code, **detail},
    )
    db.commit()
    return ApiError(
        409,
        code,
        reason,
        detail={"cell": scope.to_dict(), "repo": repo, **detail},
    )


def _record_from(
    repo: str, cell: dict[str, str], *, verifier: str, tier: str, note: str
) -> SignoffRecord:
    try:
        return SignoffRecord(
            repo=repo,
            capability_class=cell["capability_class"],
            verifier=verifier,
            size=cell.get("size", WILDCARD),
            language=cell.get("language", WILDCARD),
            builder=cell.get("builder", WILDCARD),
            model=cell.get("model", WILDCARD),
            provider=cell.get("provider", WILDCARD),
            process_step=cell.get("process_step", WILDCARD),
            tier=tier,
            note=note,
        )
    except SignoffRefused as exc:
        raise ApiError(409, CODE_FALSE_Q1, str(exc), detail={"code": exc.code}) from exc
    except ValueError as exc:
        raise ApiError(
            422,
            "validation_error",
            str(exc),
            detail={"errors": [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]},
        ) from exc


def _floor(db: Session, *, repo: str, actor: str, scope: CellKey) -> None:
    """Step 1 — false-Q1 over the STORED belts. 409 ``false_q1_refused``, nothing else
    evaluated: the cell is untrusted."""
    fq1, bad_ids = cell_false_q1(db, repo, scope)
    if fq1 > 0:
        message = f"cell has false_q1={fq1} > 0 — untrusted, cannot be signed off"
        raise _refuse(
            db,
            repo=repo,
            actor=actor,
            scope=scope,
            reason=message,
            code=CODE_FALSE_Q1,
            detail={
                "code": REFUSAL_FALSE_Q1,
                "false_q1": fq1,
                "rows": bad_ids,
                "thresholds": {"false_q1": 0},
                "observed": {"false_q1": fq1},
                "refusals": [
                    SignoffRefusal(REFUSAL_FALSE_Q1, message, threshold=0, observed=fq1).to_dict()
                ],
            },
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/signoffs",
    response_model=Page[SignoffWithPolicyOut],
    responses={401: _ERR},
    summary="Attestations (active by default; ?include_revoked=true for the history)",
)
def list_signoffs(
    viewer: ViewerDep,
    db: DbDep,
    page: PageDep,
    repo: str | None = Query(default=None, max_length=64),
    include_revoked: bool = Query(default=False),
) -> Page[SignoffWithPolicyOut]:
    del viewer
    rows = load_signoff_rows(db, repo)
    items = [signoff_out(db, r, rows) for r in rows if not r.revoke]
    if not include_revoked:
        items = [s for s in items if not s.revoked]
    items.reverse()  # newest first
    return Page[SignoffWithPolicyOut](
        items=items[page.offset : page.offset + page.limit],
        total=len(items),
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/signoffs/policy",
    response_model=SignoffPolicyOut,
    responses={401: _ERR, 503: _ERR},
    summary="The sign-off policy in force (signoff-policy.v2 defaults, or the deployment's relaxed thresholds)",
)
def signoff_policy(viewer: ViewerDep) -> SignoffPolicyOut:
    del viewer
    return SignoffPolicyOut(**effective_policy().to_dict())


@router.get(
    "/signoffs/preview",
    response_model=SignoffPreviewOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 503: _ERR},
    summary="What a sign-off of this cell WOULD record, and every refusal that would apply",
)
def preview_signoff(
    viewer: ViewerDep,
    db: DbDep,
    *,
    repo: str = Query(min_length=1, max_length=64),
    capability_class: str = Query(min_length=1, max_length=64),
    size: str = Query(default=WILDCARD, max_length=4),
    language: str = Query(default=WILDCARD, max_length=16),
    builder: str = Query(default=WILDCARD, max_length=64),
    model: str = Query(default=WILDCARD, max_length=128),
    provider: str = Query(default=WILDCARD, max_length=64),
    process_step: str = Query(default=WILDCARD, max_length=16),
    reviewed_row_hash: str = Query(default="", max_length=64),
    statement: str = Query(default="", max_length=4000),
) -> SignoffPreviewOut:
    """Steps 1–4 of ``POST /signoffs`` without writing. ``reviewed_row_hash`` (with an
    optional ``statement``) lets the approver's chosen row be validated the way the
    POST would (422 when it is not an accepted row of this cell); without it the
    ``attestation_missing`` refusal is listed, as it would be."""
    if db.get(Repo, repo) is None:
        raise ApiError(404, "not_found", f"no repo {repo!r}")
    policy = effective_policy()
    cell_in = {
        k: v
        for k, v in {
            "capability_class": capability_class,
            "size": size,
            "language": language,
            "builder": builder,
            "model": model,
            "provider": provider,
            "process_step": process_step,
        }.items()
        if v and v != WILDCARD
    }
    try:  # the same cell validation the POST body gets (known fields, a size tier …)
        cell_in = SignoffCreateRequest(repo=repo, cell=cell_in).cell
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"] if exc.errors() else str(exc)
        raise ApiError(
            422,
            "validation_error",
            msg,
            detail={"errors": [{"loc": ["query", "cell"], "msg": msg, "type": "value_error"}]},
        ) from exc
    record = _record_from(repo, cell_in, verifier=viewer.id, tier="human-verified", note="")
    scope = record.scope()
    fq1, bad_ids = cell_false_q1(db, repo, scope)
    if fq1 > 0:
        raise ApiError(
            409,
            CODE_FALSE_Q1,
            f"cell has false_q1={fq1} > 0 — untrusted, cannot be signed off",
            detail={
                "cell": scope.to_dict(),
                "repo": repo,
                "code": REFUSAL_FALSE_Q1,
                "false_q1": fq1,
                "rows": bad_ids,
            },
        )
    rows = cell_rows(db, repo, scope)
    controls = latest_controls_verdict(db, repo)
    by_task = oracle_by_task(db, repo)
    cell = measured_cell(rows, scope, controls, by_task)
    oracle = cell_oracle_strength(db, repo, rows, by_task=by_task)
    strength = resolve_oracle_strength(cell, oracle_strength=oracle.strength)
    attestation_out: AttestationOut | None = None
    if reviewed_row_hash:
        try:
            att_in = AttestationIn(
                reviewed_row_hash=reviewed_row_hash, statement=statement or "(preview)"
            )
        except ValidationError as exc:
            raise _attestation_422(exc.errors()[0]["msg"] if exc.errors() else str(exc)) from exc
        att, subject = resolve_attestation(db, repo, scope, att_in)
        record = replace(record, attestation=att)
        attestation_out = AttestationOut(**att.to_dict(), subject=subject)
    refusals = evaluate_signoff(
        record,
        cell,
        controls=controls,
        oracle_strength=oracle.strength,
        policy=policy,
        repo=repo,
    )
    stamped = (
        stamp_evidence(
            record, cell, controls=controls, oracle_strength=oracle.strength, policy=policy
        )
        if cell.stats is not None
        else record
    )
    s = cell.stats
    return SignoffPreviewOut(
        repo=repo,
        cell=scope.to_dict(),
        policy=SignoffPolicyOut(**policy.to_dict()),
        evidence=SignoffPreviewEvidence(
            measured=cell.measured,
            n=cell.n,
            n_tasks=cell.n_tasks,
            clean=0 if s is None else s.clean,
            point=None if s is None else round(s.point, 4),
            ci_low=None if s is None else round(s.ci.low, 4),
            ci_high=None if s is None else round(s.ci.high, 4),
            false_q1=cell.false_q1,
            oracle_strength=None if strength is None else round(strength, 4),
            oracle=SignoffOracleOut(**oracle.to_dict()),
            apparatus_versions=[] if s is None else list(s.apparatus_versions),
            belt_sets=list(cell.belt_sets),
            model_n=cell.model_n,
            model_point=None if cell.model_point is None else round(cell.model_point, 4),
            failure_split=FailureSplitOut(
                builder_red=cell.n_builder_red,
                budget=cell.n_budget,
                protocol=cell.n_protocol,
                harness=cell.n_harness,
                disqualified=cell.n_disqualified,
                lint=cell.stats.n_lint if cell.stats is not None else 0,
                lint_evaluated=cell.stats.n_lint_evaluated if cell.stats is not None else 0,
                outage=cell.n_outage,
            ),
        ),
        route=SignoffRouteOut(route=cell.route, reason=cell.reason, reason_code=cell.reason_code),
        controls=ControlsVerdictOut(**verdict_dict(controls)),
        refusals=[_refusal_out(r) for r in refusals],
        signable=not refusals,
        would_record=_would_record(stamped),
        accepted_rows=accepted_rows(db, repo, scope),
        attestation=attestation_out,
    )


@router.get(
    "/signoffs/{signoff_id}",
    response_model=SignoffWithPolicyOut,
    responses={401: _ERR, 404: _ERR},
    summary="One attestation with the snapshot it was made on",
)
def get_signoff(signoff_id: str, viewer: ViewerDep, db: DbDep) -> SignoffWithPolicyOut:
    del viewer
    row = db.execute(
        select(Signoff).where(Signoff.signoff_id == signoff_id, Signoff.revoke.is_(False))
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", f"no attestation {signoff_id!r}")
    return signoff_out(db, row, load_signoff_rows(db, row.repo))


@router.post(
    "/signoffs",
    response_model=SignoffWithPolicyOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 503: _ERR},
    summary="Attest a cell (approver) under signoff-policy.v2; 409 false_q1_refused / signoff_refused",
)
def create_signoff(
    body: SignoffCreateWithAttestationRequest, approver: ApproverDep, db: DbDep
) -> SignoffWithPolicyOut:
    if db.get(Repo, body.repo) is None:
        raise ApiError(404, "not_found", f"no repo {body.repo!r}")
    policy = effective_policy()
    record = _record_from(
        body.repo, body.cell, verifier=approver.id, tier=body.tier, note=body.note
    )
    scope = record.scope()

    # 1. The floor, over the STORED belts — catches rows that bypassed the write path.
    _floor(db, repo=body.repo, actor=approver.id, scope=scope)
    # 2. Evidence: the cell routed under the repo's latest controls verdict, and its
    #    oracle strength from the repo's task-level mutation scores.
    rows = cell_rows(db, body.repo, scope)
    controls = latest_controls_verdict(db, body.repo)
    by_task = oracle_by_task(db, body.repo)
    cell = measured_cell(rows, scope, controls, by_task)
    oracle = cell_oracle_strength(db, body.repo, rows, by_task=by_task)
    # 3. The attestation: the named row must be an accepted row of THIS cell.
    if body.attestation is not None:
        att, _subject = resolve_attestation(db, body.repo, scope, body.attestation)
        record = replace(record, attestation=att)
    # 4. The policy.
    refusals = evaluate_signoff(
        record,
        cell,
        controls=controls,
        oracle_strength=oracle.strength,
        policy=policy,
        repo=body.repo,
    )
    if refusals:
        first = refusals[0]
        raise _refuse(
            db,
            repo=body.repo,
            actor=approver.id,
            scope=scope,
            reason=redact(first.message),
            code=CODE_FALSE_Q1 if first.code == REFUSAL_FALSE_Q1 else CODE_REFUSED,
            detail={
                "code": first.code,
                "threshold": first.threshold,
                "observed_value": first.observed,
                "policy_version": policy.policy_version,
                "thresholds": policy.thresholds(),
                "observed": _observed(cell, controls, oracle, policy),
                "refusals": [r.to_dict() for r in refusals],
                "false_q1": cell.false_q1,
            },
        )
    # 5. Stamp the decision and write.
    stamped = stamp_evidence(
        record, cell, controls=controls, oracle_strength=oracle.strength, policy=policy
    )
    assert cell.stats is not None and stamped.attestation is not None  # by the policy
    cell_json: dict[str, str] = {
        **scope.to_dict(),
        _EV_N: str(cell.stats.n),
        _EV_POINT: f"{cell.stats.point:.6f}",
        _EV_CI_LOW: f"{cell.stats.ci.low:.6f}",
        _EV_CI_HIGH: f"{cell.stats.ci.high:.6f}",
        _EV_FQ1: str(cell.stats.false_q1),
        _EV_APPARATUS: ",".join(cell.stats.apparatus_versions),
        _EV_ORACLE: ""
        if stamped.oracle_strength_at_signoff is None
        else f"{stamped.oracle_strength_at_signoff:.6f}",
        _POLICY_VERSION: stamped.policy_version,
        _POLICY_THRESHOLDS: json.dumps(stamped.policy_thresholds, sort_keys=True),
        _ROUTE: stamped.route_at_signoff,
        _ROUTE_REASON: cell.reason,
        _ROUTE_REASON_CODE: stamped.route_reason_code,
        _CTL_VERDICT: stamped.controls_verdict,
        _CTL_RUN: stamped.controls_run_id,
        _CTL_CREATED: controls.created,
        _CTL_K: str(stamped.controls_k),
        _CTL_TOTAL: str(stamped.controls_total),
        _CTL_ESCAPES: str(stamped.controls_escapes),
        _ATT_TASK: stamped.attestation.reviewed_task_id,
        _ATT_ROW: stamped.attestation.reviewed_row_hash,
        _ATT_STATEMENT: stamped.attestation.statement,
        _ATT_AT: stamped.attestation.at,
    }
    _lock(db)
    row = _chain_and_add(
        db,
        Signoff(
            signoff_id=uuid.uuid4().hex,
            repo=body.repo,
            cell_json=cell_json,
            tier=stamped.tier,
            verifier=approver.id,
            note=stamped.note,
            revoke=False,
            evidence_rows=cell.stats.n,
            created=utc_now_iso(),
        ),
    )
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", body.repo),
        action="signoff.created",
        repo=body.repo,
        actor=approver.id,
        payload={
            "signoff_id": row.signoff_id,
            "cell": scope.to_dict(),
            "tier": row.tier,
            "n": cell.stats.n,
            "point": round(cell.stats.point, 4),
            "ci_low": round(cell.stats.ci.low, 4),
            "policy_version": stamped.policy_version,
            "route_reason_code": stamped.route_reason_code,
            "controls_verdict": stamped.controls_verdict,
            "controls_run_id": stamped.controls_run_id,
            "oracle_strength": stamped.oracle_strength_at_signoff,
            "oracle_scored": oracle.scored,
            "oracle_tasks": oracle.tasks,
            "reviewed_row_hash": stamped.attestation.reviewed_row_hash,
            "row_hash": row.row_hash,
        },
    )
    db.commit()
    return signoff_out(db, row, load_signoff_rows(db, body.repo))


@router.post(
    "/signoffs/{signoff_id}/revoke",
    response_model=SignoffWithPolicyOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR},
    summary="Withdraw an attestation (appends a revocation row; never edits)",
)
def revoke_signoff(
    signoff_id: str,
    approver: ApproverDep,
    db: DbDep,
    body: SignoffRevokeRequest | None = None,
) -> SignoffWithPolicyOut:
    row = db.execute(
        select(Signoff).where(Signoff.signoff_id == signoff_id, Signoff.revoke.is_(False))
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", f"no attestation {signoff_id!r}")
    all_rows = load_signoff_rows(db, row.repo)
    if _revocation_for(row, all_rows) is not None:
        raise ApiError(409, "already_revoked", f"attestation {signoff_id!r} is already revoked")
    note = body.note if body is not None else ""
    _lock(db)
    _chain_and_add(
        db,
        Signoff(
            signoff_id=uuid.uuid4().hex,
            repo=row.repo,
            cell_json=scope_of(row).to_dict(),
            tier=row.tier,
            verifier=approver.id,
            note=redact(note) or f"revokes {signoff_id}",
            revoke=True,
            evidence_rows=0,
            created=utc_now_iso(),
        ),
    )
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", row.repo),
        action="signoff.revoked",
        repo=row.repo,
        actor=approver.id,
        payload={"signoff_id": signoff_id, "cell": scope_of(row).to_dict()},
    )
    db.commit()
    return signoff_out(db, row, load_signoff_rows(db, row.repo))


__all__ = [
    "ACCEPTED_ROWS_LIMIT",
    "CODE_FALSE_Q1",
    "CODE_POLICY_INVALID",
    "CODE_REFUSED",
    "FALSE_Q1_PREDICATE",
    "CellOracle",
    "accepted_rows",
    "cell_false_q1",
    "cell_oracle_strength",
    "cell_rows",
    "effective_policy",
    "load_signoff_records",
    "load_signoff_rows",
    "measured_cell",
    "resolve_attestation",
    "router",
    "scope_of",
    "signoff_body",
    "signoff_hash",
    "signoff_out",
    "to_record",
    "verify_signoff_rows",
]
