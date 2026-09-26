"""``/signoffs`` — human attestations; the verification tier is EARNED, never asserted.

The ``signoffs`` table is append-only and hash-chained on its own (``prev_hash`` =
the previous sign-off's ``row_hash``; ``row_hash`` = SHA-256 of the canonical JSON
of the row minus ``row_hash``). A revocation is a new row with ``revoke=True`` for
the same scope; the latest row per ``(repo, scope)`` wins.

A sign-off is a policy decision, refused at write (``signoff-policy.v3``,
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
   the ledger, belong to this cell and be ``clean`` (else **422**) — and the **actors
   behind the evidence** for the two-person rule: the attested row's ``Grade.actor`` and
   its run's ``Run.actor`` (:func:`resolve_attestation`), and the same for EVERY accepted
   row of the measured cell (:func:`cell_actors`);
4. applies the policy (:func:`crb.core.signoff.evaluate_signoff`): a thin cell, a
   controls gate that failed / was never run / let a control escape / was thin, an
   **unmeasured** oracle (``oracle_unmeasured``, never overridable since v2), a weak
   oracle, a route other than ``deliver``, a missing attestation, or ``same_actor``
   (never overridable since v3): the approver is refused when they are the actor of the
   attested row (``Grade.actor``), the actor of the run that produced it (``Run.actor``),
   or the only person behind the cell's accepted evidence; non-person actors — the
   worker, ``cli:…``, ``import`` — never count (the core's ``is_person_actor`` decides)
   → **409 signoff_refused** with ``detail.code``, ``detail.thresholds`` and
   ``detail.observed`` plus every failing clause; nothing is written and the refusal is
   recorded as a ``system/signoff.refused`` event;
5. stamps the whole decision (n, point, Wilson lower, false-Q1, oracle strength, route +
   reason code, controls verdict / run / k of N / escapes, the policy and its thresholds,
   the attestation, and the signing account's ``verifier_kind`` — ``local`` | ``oidc``
   from the approver's issuer; ``service`` is reserved, never minted here) into the row,
   hash-covered.

``GET /signoffs/preview`` runs steps 1–4 without writing and answers what the record
WOULD carry and every refusal that would apply — ``same_actor`` included, judged for the
VIEWER as the would-be approver, so the sentence "you queued the run that produced this
row — a second approver must sign" shows before anyone tries — plus the cell's accepted
rows the approver may name.

At read, every listed attestation carries ``current_false_q1`` and ``active`` (latest
for its scope, not revoked, and the cell's CURRENT false-Q1 is 0); the capability /
forecast overlays use :func:`crb.core.signoff.apply_signoffs`, which refuses to lift a
cell whose false-Q1 is now > 0. A later violation auto-invalidates the attestation.

A deployment relaxes the numeric thresholds through ``CRB_SIGNOFF__*`` (see
``docs/API.md``); a value outside the published bounds — or an attempt to switch off a
non-overridable clause — makes every sign-off answer **503 signoff_policy_invalid**
rather than run under a bar nobody chose. A record signed under ``signoff-policy.v1``
is served with the version it was signed under; its chain still verifies.

Navigation
----------
What it is:   The ``/signoffs`` route module — human attestations of a cell under
              ``signoff-policy.v3``, refused at write, on their own hash chain.
What it does: ``POST`` runs the five steps of the module docstring: the false-Q1 floor over
              the STORED belts (409, non-overridable) → the cell routed under the repo's
              latest controls verdict and task-level oracle strength → the approver's
              attestation resolved to an accepted row of THIS cell, plus the actors behind
              that row and behind every accepted row of the cell → the policy's clauses,
              the two-person rule among them (409 ``signoff_refused`` with every failing
              clause, recorded as an event) → the whole decision, ``verifier_kind``
              included, stamped into the row and chained. ``preview`` runs steps 1–4
              without writing; a revocation is a new row; at read every attestation says
              whether it is still ``active`` (latest, not revoked, false-Q1 still 0) and
              what kind of account signed it.
How:          ``_floor`` → ``cell_rows`` (sighted, current apparatus, the repo's own checks
              arm — ``checks_arm_in``) → ``measured_cell`` +
              ``cell_oracle_strength`` → ``resolve_attestation`` + ``cell_actors`` (``Grade.actor``,
              ``Run.actor``) → ``evaluate_signoff`` → ``stamp_evidence`` → ``_lock`` /
              ``_chain_and_add`` → ``signoff.created``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0003-one-routing-rule.md,
              docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0024-working-by-construction.md (a sign-off reads, stamps and lifts
              one checks arm)
Works with:   src/crb/core/signoff.py (the policy, ``SignoffRecord``, ``evaluate_signoff``,
              ``stamp_evidence``, ``verifier_kind_for_issuer``; its ``is_person_actor`` decides
              personhood — this module only gathers actors),
              src/crb/server/auth.py (``Principal.issuer`` — what ``verifier_kind`` is
              stamped from), src/crb/core/capability.py (``measure_cell``,
              ``task_oracle_strength``), src/crb/server/routes/oracle.py
              (``latest_controls_verdict`` / ``oracle_by_task`` — shared with the map),
              src/crb/server/routes/capability.py (overlays ``load_signoff_records``),
              src/crb/server/schemas_signoff.py (the v3 shapes), src/crb/store/models.py
              (``Signoff``, ``Grade.actor``, ``Run.actor``), ui/src/screens/Signoff,
              docs/EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity (§6a)
Tested by:    tests/test_server_routes_signoffs.py, tests/test_server_routes_capability.py
Touch when:   never for a new repository; relaxing a threshold is deployment configuration
              (``CRB_SIGNOFF__*``, docs/API.md), not code; adding a policy clause means
              src/crb/core/signoff.py + a snapshot key here + the schema + the UI + the
              EVIDENCE-AND-CLAIMS section; a new belt means ``FALSE_Q1_PREDICATE`` here
              and the twin in src/crb/server/routes/system.py.
Claims:       An active sign-off licenses auto-delivery of that cell under the recorded
              policy and thresholds — and nothing once its cell's false-Q1 is > 0
              (docs/EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity, §6a).
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
from crb.core.checks import ARM_OFF, LABEL_CHECKS, arm_from_label
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import (
    BELT_SET_V3_LEGACY,
    BELT_SET_V5,
    CELL_FIELDS,
    GENESIS_HASH,
    LABEL_API_STABLE,
    CellKey,
    GradeRow,
    LedgerIntegrityError,
    rows_for_checks,
)
from crb.core.redact import redact
from crb.core.routing import ControlsVerdict
from crb.core.signoff import (
    REFUSAL_FALSE_Q1,
    SIGNOFF_SCHEMA,
    SIGNOFF_SCHEMA_V1,
    SIGNOFF_SCHEMA_V2,
    SIGNOFF_SCHEMA_V3,
    Attestation,
    SignoffPolicy,
    SignoffRecord,
    SignoffRefusal,
    SignoffRefused,
    evaluate_signoff,
    resolve_oracle_strength,
    stamp_evidence,
    verifier_kind_for_issuer,
)
from crb.core.version import APPARATUS_VERSION
from crb.observability.events import StepStatus
from crb.server.auth import ApproverDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, Principal
from crb.server.prevention_state import checks_arm_in
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
from crb.store.models import Grade, Repo, Run, Signoff, Task, User

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
# crb.signoff.v3 (F34): the kind of account that signed (absent on rows written before).
_VERIFIER_KIND = "verifier_kind"
# crb.signoff.v4 (ADR-0024): the checks arm the evidence was read on (absent before).
_EV_CHECKS = "evidence_checks_arm"

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
    """SHA-256 of the canonical JSON of :func:`signoff_body`."""
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
    """Serialise sign-off writes so two approvers cannot both chain onto one head."""
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    elif dialect == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7335)"))  # signoffs — one id per table


def _last_hash(session: Session) -> str:
    """The sign-off chain's head, or the genesis hash."""
    last = session.execute(
        select(Signoff.row_hash).order_by(Signoff.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return str(last) if last else GENESIS_HASH


def _chain_and_add(session: Session, row: Signoff) -> Signoff:
    """Set ``prev_hash`` / ``row_hash`` and stage the row (the caller commits)."""
    row.prev_hash = _last_hash(session)
    row.row_hash = signoff_hash(row)
    session.add(row)
    return row


# ---------------------------------------------------------------------------
# Scope ↔ core records
# ---------------------------------------------------------------------------


def scope_of(row: Signoff) -> CellKey:
    """The cell a sign-off names (wildcards for the fields it leaves open)."""
    cj = dict(row.cell_json or {})
    return CellKey(**{f: str(cj.get(f, WILDCARD) or WILDCARD) for f in CELL_FIELDS})


def _scope_key(row: Signoff) -> tuple[str, ...]:
    """``(repo, *cell)`` — what "latest per scope" is keyed on."""
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
    """The policy thresholds snapshot (stored as a JSON string inside ``cell_json``)."""
    raw = cj.get(_POLICY_THRESHOLDS, "")
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except ValueError:
        return {}
    return dict(d) if isinstance(d, dict) else {}


def _attestation_of(cj: dict[str, str]) -> Attestation | None:
    """The stamped attestation, or ``None`` on a pre-policy row."""
    if not cj.get(_ATT_ROW):
        return None
    return Attestation(
        reviewed_task_id=str(cj.get(_ATT_TASK, "")),
        reviewed_row_hash=str(cj.get(_ATT_ROW, "")),
        statement=str(cj.get(_ATT_STATEMENT, "")),
        at=str(cj.get(_ATT_AT, "")),
    )


def _schema_of(cj: dict[str, str]) -> str:
    """The record schema a stored row was written under, read from the keys it carries:
    the checks arm → v4, ``verifier_kind`` → v3, a policy snapshot → v2, none → v1 (never
    assumed)."""
    if _EV_CHECKS in cj:
        return SIGNOFF_SCHEMA
    if _VERIFIER_KIND in cj:
        return SIGNOFF_SCHEMA_V3
    return SIGNOFF_SCHEMA_V2 if _POLICY_VERSION in cj else SIGNOFF_SCHEMA_V1


def to_record(row: Signoff) -> SignoffRecord:
    """The :class:`~crb.core.signoff.SignoffRecord` view of a stored row (for the overlay).
    A row written before the policy comes back as a ``crb.signoff.v1`` record, one written
    before F34 as ``crb.signoff.v2`` with ``verifier_kind: ""``."""
    cj = dict(row.cell_json or {})
    scope = scope_of(row)
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
        verifier_kind=str(cj.get(_VERIFIER_KIND, "") or ""),
        checks_arm=str(cj.get(_EV_CHECKS, "") or ""),
        schema=_schema_of(cj),
        record_id=row.signoff_id,
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
    )


def load_signoff_rows(session: Session, repo: str | None = None) -> list[Signoff]:
    """Every sign-off row in chain order; a ``repo`` filter also keeps wildcard rows."""
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
    """Restrict a ``Grade`` query to the scope's non-wildcard fields."""
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
    row_ids: Iterable[str] = session.execute(q.order_by(Grade.seq)).scalars()
    ids = [str(r) for r in row_ids]
    return len(ids), ids


def cell_rows(session: Session, repo: str, scope: CellKey, arm: str) -> list[GradeRow]:
    """The scope's SIGHTED rows on the CURRENT apparatus and on the ``checks`` ``arm`` as
    :class:`GradeRow` (raises ``FalseQ1Violation`` on a bad row — call :func:`cell_false_q1`
    first so the refusal is explicit, not incidental). A sign-off is a claim about the
    current instrument on the sighted measurement: rows from an older belt set, blind
    attempts, or rows graded with the format step or belt 6 switched differently never lift
    the cell (EVIDENCE-AND-CLAIMS §5, ADR-0024; the capability map applies the same
    defaults — its ``checks`` default is :func:`checks_arm_in`)."""
    q = (
        _scope_where(select(Grade), repo, scope)
        .where(Grade.mode == "sighted", Grade.apparatus_version == APPARATUS_VERSION)
        .order_by(Grade.seq)
    )
    grades: Iterable[Grade] = session.execute(q).scalars()
    rows = [GradeRow.from_dict(grade_to_dict(g)) for g in grades]
    return rows_for_checks(rows, arm)


def _grade_arm(g: Grade) -> str:
    """The ``checks`` arm of a stored row (ADR-0024) — read from its hashed labels exactly as
    :attr:`crb.core.ledger.GradeRow.checks_arm` reads them."""
    labels = dict(g.labels_json or {})
    return arm_from_label(labels.get(LABEL_CHECKS, ""), belt6_recorded=LABEL_API_STABLE in labels)


def _projection(scope: CellKey) -> tuple[str, ...]:
    """The cell fields a scope pins — the projection its cell is measured under."""
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
    """The full cell key of a stored row."""
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
    session: Session, repo: str, scope: CellKey, arm: str, *, limit: int = ACCEPTED_ROWS_LIMIT
) -> list[AcceptedRowOut]:
    """The cell's accepted rows — clean and not disqualified, on the ``checks`` ``arm`` the
    cell is read on — newest first, with the graded task's subject, for the attestation
    picker."""
    q = _scope_where(
        select(Grade).where(Grade.clean.is_(True), Grade.disqualified.is_(False)), repo, scope
    )
    newest_first: Iterable[Grade] = session.execute(q.order_by(Grade.seq.desc())).scalars()
    grades: list[Grade] = []
    for g in newest_first:
        if _grade_arm(g) == arm:
            grades.append(g)
            if len(grades) >= limit:
                break
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


#: ``IN`` lists are chunked under SQLite's default 999-parameter ceiling.
_IN_CHUNK = 500


def run_actors(session: Session, run_ids: Iterable[str]) -> dict[str, str]:
    """``run_id → Run.actor`` for the runs the store knows; a historical, CLI or census row
    may name a run that has no row here, and such a run has no actor."""
    ids = sorted({r for r in run_ids if r})
    out: dict[str, str] = {}
    for i in range(0, len(ids), _IN_CHUNK):
        q = select(Run.id, Run.actor).where(Run.id.in_(ids[i : i + _IN_CHUNK]))
        out.update({str(rid): str(actor or "") for rid, actor in session.execute(q)})
    return out


def cell_actors(session: Session, rows: Sequence[GradeRow]) -> frozenset[str]:
    """Every actor behind the cell's ACCEPTED rows (clean, not disqualified): each row's
    own ``actor`` and the ``actor`` of the run that produced it — the second ground of the
    two-person rule (:func:`crb.core.signoff.same_actor_refusal`). The core decides which
    of them are people; this only gathers them, non-person strings included."""
    accepted = [r for r in rows if r.clean and not r.disqualified]
    by_run = run_actors(session, (r.run_id for r in accepted))
    return frozenset({r.actor for r in accepted} | {by_run.get(r.run_id, "") for r in accepted})


@dataclass(frozen=True)
class ResolvedAttestation:
    """The approver's attestation resolved against the ledger: the core record's
    ``attestation``, the graded task's ``subject`` for display, and — for the two-person
    rule — the ``actors`` behind the row (its own ``Grade.actor`` and its run's
    ``Run.actor``) with the ``run_id`` that produced it (``""`` when the row names none)
    and that run's ``run_actor`` on its own (``""`` when the store knows no such run), so
    a caller can tell WHICH half of ``actors`` is the run's before naming the run in a
    refusal (:func:`attested_run_id_for`)."""

    attestation: Attestation
    subject: str
    actors: frozenset[str]
    run_id: str
    run_actor: str


def attested_run_id_for(attested: ResolvedAttestation | None, approver: str) -> str:
    """The run id the ``same_actor`` sentence may name for ``approver``: the attested row's
    run only when ``approver`` is that run's actor — "queued run X, which produced the
    attested row" must be true of the person it is said to. When the row's OWN
    ``Grade.actor`` is the approver (a ``crb grade --actor`` row, a run the store never
    saw), ``""``: the core then states the ground without a run."""
    if attested is None or not attested.run_id:
        return ""
    return attested.run_id if attested.run_actor == approver else ""


def _attestation_422(msg: str) -> ApiError:
    """A 422 located at ``body.attestation.reviewed_row_hash``."""
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
    session: Session, repo: str, scope: CellKey, att: AttestationIn, arm: str
) -> ResolvedAttestation:
    """The approver's attestation with ``reviewed_task_id`` resolved from the ledger,
    plus the task's subject and the actors behind the row. 422 unless the row exists, is
    this repo's, sits in the cell — on the ``checks`` ``arm`` the cell is read on — and is
    an ACCEPTED row (clean, not disqualified) — an approver can only attest to a diff the
    instrument accepted."""
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
    if _grade_arm(g) != arm:
        raise _attestation_422(
            f"row {att.reviewed_row_hash[:12]}… was graded on the checks arm "
            f"{_grade_arm(g)!r}, not the arm {arm!r} this cell is read on (ADR-0024)"
        )
    if not g.clean or g.disqualified:
        raise _attestation_422(
            f"row {att.reviewed_row_hash[:12]}… is not an accepted row "
            f"(clean={bool(g.clean)}, disqualified={bool(g.disqualified)}) — "
            "an approver attests to a diff the instrument accepted"
        )
    subject = _subjects(session, repo, [g.task_id]).get(g.task_id, "")
    run_actor = run_actors(session, [g.run_id]).get(g.run_id, "")
    return ResolvedAttestation(
        attestation=Attestation(
            reviewed_task_id=g.task_id,
            reviewed_row_hash=g.row_hash,
            statement=att.statement,
            at=utc_now_iso(),
        ),
        subject=subject,
        actors=frozenset({str(g.actor or ""), run_actor}),
        run_id=str(g.run_id or ""),
        run_actor=run_actor,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _evidence(row: Signoff) -> SignoffEvidenceWithOracle:
    """The evidence snapshot a row was signed on (never recomputed at read)."""
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
    """The stamped attestation with the task's subject joined, for display."""
    cj = dict(row.cell_json or {})
    att = _attestation_of(cj) if not row.revoke else None
    if att is None:
        return None
    subject = _subjects(session, row.repo, [att.reviewed_task_id]).get(att.reviewed_task_id, "")
    return AttestationOut(**att.to_dict(), subject=subject)


def _revocation_for(row: Signoff, all_rows: Sequence[Signoff]) -> Signoff | None:
    """The later revocation row for the same scope, if any."""
    key = _scope_key(row)
    for r in all_rows:
        if r.seq > row.seq and r.revoke and _scope_key(r) == key:
            return r
    return None


def _superseded(row: Signoff, all_rows: Sequence[Signoff]) -> bool:
    """Whether a later attestation of the same scope exists (latest wins)."""
    key = _scope_key(row)
    return any(r.seq > row.seq and not r.revoke and _scope_key(r) == key for r in all_rows)


def _display_name(session: Session, user_id: str) -> str:
    """The name a reader sees for a ledger actor: resolved from the users table at read
    time (the session's identity map makes repeats free), empty when the account is
    gone. The ledger row keeps the id — a name may change, the hash chain may not."""
    user = session.get(User, user_id)
    return (user.display_name or user.subject.removeprefix("local:")) if user is not None else ""


def signoff_out(
    session: Session, row: Signoff, all_rows: Sequence[Signoff]
) -> SignoffWithPolicyOut:
    """One attestation as served: the stored snapshot plus the LIVE ``active`` /
    ``current_false_q1`` — a cell that has since acquired a false-Q1 row is shown
    inactive even though its row is untouched."""
    revocation = _revocation_for(row, all_rows)
    current_fq1, _ = (
        cell_false_q1(session, row.repo, scope_of(row)) if row.repo != WILDCARD else (0, [])
    )
    cj = dict(row.cell_json or {})
    # stale = stamped on an apparatus that no longer matches the instrument reading now;
    # a v1 record (no stamp) is not judged here
    stamped = {v.strip() for v in str(cj.get(_EV_APPARATUS, "") or "").split(",") if v.strip()}
    # … or signed on a checks arm other than the one the repository's cells are read on now
    # (ADR-0024); a record from before the switchboard was signed on ``off``
    signed_arm = str(cj.get(_EV_CHECKS, "") or "") or ARM_OFF
    arm_now = checks_arm_in(session, row.repo) if row.repo != WILDCARD else ""
    stale = (bool(stamped) and APPARATUS_VERSION not in stamped) or (
        bool(arm_now) and signed_arm != arm_now
    )
    active = (
        revocation is None and not _superseded(row, all_rows) and current_fq1 == 0 and not stale
    )
    return SignoffWithPolicyOut(
        id=row.signoff_id,
        repo=row.repo,
        cell=scope_of(row).to_dict(),
        tier=row.tier,
        note=row.note,
        approver=row.verifier,
        approver_name=_display_name(session, row.verifier),
        verifier_kind=str(cj.get(_VERIFIER_KIND, "") or ""),
        created=row.created,
        revoked=revocation is not None,
        revoked_by=revocation.verifier if revocation is not None else None,
        revoked_by_name=(
            _display_name(session, revocation.verifier) if revocation is not None else None
        ),
        revoked_at=revocation.created if revocation is not None else None,
        active=active,
        current_false_q1=current_fq1,
        stale=stale,
        apparatus_current=APPARATUS_VERSION,
        checks_arm=signed_arm,
        checks_arm_current=arm_now,
        evidence=_evidence(row),
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
        schema=_schema_of(cj),
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
    """A policy refusal as the API serves it."""
    return SignoffRefusalOut(**r.to_dict())


def _observed(
    cell: CapabilityCell, controls: ControlsVerdict, oracle: CellOracle, policy: SignoffPolicy
) -> dict[str, Any]:
    """What the policy saw — served in ``detail.observed`` next to the thresholds so a
    refused approver can see exactly which number fell short."""
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


#: The envelope code when the signing account's ``users.issuer`` is blank — a defect of the
#: users table (no product path writes one), not of the request; nothing is written.
CODE_ISSUER_MISSING = "account_issuer_missing"


def verifier_kind_of(principal: Principal) -> str:
    """The ``verifier_kind`` ``principal`` stamps (:func:`verifier_kind_for_issuer`), or a
    **503 account_issuer_missing** envelope when its issuer is blank — the core fails
    closed with a ``ValueError``; here that becomes a diagnosed answer naming the account
    to repair, never a 500, and never a guessed kind. Called before any lock is taken."""
    try:
        return verifier_kind_for_issuer(principal.issuer)
    except ValueError as exc:
        raise ApiError(
            503,
            CODE_ISSUER_MISSING,
            f"account {principal.id} has no issuer; verifier_kind cannot be stamped — "
            "repair the users row",
            detail={"user": principal.id},
        ) from exc


def _record_from(
    repo: str,
    cell: dict[str, str],
    *,
    verifier: str,
    verifier_kind: str,
    tier: str,
    note: str,
) -> SignoffRecord:
    """The unstamped core record for a request body; the core's own validation errors
    become 409 (a refusal) or 422 (a malformed scope). ``verifier_kind`` is what the
    caller derived from the signing account's issuer (:func:`verifier_kind_for_issuer`)."""
    try:
        return SignoffRecord(
            repo=repo,
            capability_class=cell["capability_class"],
            verifier=verifier,
            verifier_kind=verifier_kind,
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
    """Attestation rows (revocation rows are folded into ``revoked`` on their target)."""
    del viewer
    rows = load_signoff_rows(db, repo)
    # Filter and slice on the in-memory chain first; ``signoff_out`` runs the live
    # false-Q1 query per row, so it is called for the page only (CodeRabbit on PR #4,
    # 2026-09-15 — the whole table used to be serialised per request).
    attestations = [
        r for r in rows if not r.revoke and (include_revoked or _revocation_for(r, rows) is None)
    ]
    attestations.reverse()  # newest first
    window = attestations[page.offset : page.offset + page.limit]
    return Page[SignoffWithPolicyOut](
        items=[signoff_out(db, r, rows) for r in window],
        total=len(attestations),
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
    """The thresholds every sign-off is judged under (503 if misconfigured)."""
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
    record = _record_from(
        repo,
        cell_in,
        verifier=viewer.id,
        verifier_kind=verifier_kind_of(viewer),
        tier="human-verified",
        note="",
    )
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
    arm = checks_arm_in(db, repo)
    rows = cell_rows(db, repo, scope, arm)
    controls = latest_controls_verdict(db, repo)
    by_task = oracle_by_task(db, repo)
    cell = measured_cell(rows, scope, controls, by_task)
    oracle = cell_oracle_strength(db, repo, rows, by_task=by_task)
    strength = resolve_oracle_strength(cell, oracle_strength=oracle.strength)
    attestation_out: AttestationOut | None = None
    attested: ResolvedAttestation | None = None
    if reviewed_row_hash:
        try:
            att_in = AttestationIn(
                reviewed_row_hash=reviewed_row_hash, statement=statement or "(preview)"
            )
        except ValidationError as exc:
            raise _attestation_422(exc.errors()[0]["msg"] if exc.errors() else str(exc)) from exc
        attested = resolve_attestation(db, repo, scope, att_in, arm)
        record = replace(record, attestation=attested.attestation)
        attestation_out = AttestationOut(**attested.attestation.to_dict(), subject=attested.subject)
    # the two-person rule is judged for the viewer as the would-be approver, so the
    # refusal shows BEFORE they try (the POST resolves the same actors)
    refusals = evaluate_signoff(
        record,
        cell,
        controls=controls,
        oracle_strength=oracle.strength,
        policy=policy,
        repo=repo,
        attested_actors=None if attested is None else attested.actors,
        cell_actors=cell_actors(db, rows),
        attested_run_id=attested_run_id_for(attested, viewer.id),
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
            checks_arm=arm,
            belt_sets=list(cell.belt_sets),
            model_n=cell.model_n,
            model_point=None if cell.model_point is None else round(cell.model_point, 4),
            model_ci_low=None
            if cell.model_point is None or s is None
            else round(s.model_ci.low, 4),
            model_ci_high=None
            if cell.model_point is None or s is None
            else round(s.model_ci.high, 4),
            failure_split=FailureSplitOut(
                builder_red=cell.n_builder_red,
                budget=cell.n_budget,
                protocol=cell.n_protocol,
                harness=cell.n_harness,
                disqualified=cell.n_disqualified,
                lint=cell.stats.n_lint if cell.stats is not None else 0,
                lint_evaluated=cell.stats.n_lint_evaluated if cell.stats is not None else 0,
                api=cell.stats.n_api if cell.stats is not None else 0,
                outage=cell.n_outage,
            ),
        ),
        route=SignoffRouteOut(route=cell.route, reason=cell.reason, reason_code=cell.reason_code),
        controls=ControlsVerdictOut(**verdict_dict(controls)),
        refusals=[_refusal_out(r) for r in refusals],
        signable=not refusals,
        would_record=_would_record(stamped),
        accepted_rows=accepted_rows(db, repo, scope, arm),
        attestation=attestation_out,
    )


@router.get(
    "/signoffs/{signoff_id}",
    response_model=SignoffWithPolicyOut,
    responses={401: _ERR, 404: _ERR},
    summary="One attestation with the snapshot it was made on",
)
def get_signoff(signoff_id: str, viewer: ViewerDep, db: DbDep) -> SignoffWithPolicyOut:
    """One attestation (a revocation row's id is not addressable here)."""
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
    """The five-step decision of the module docstring; writes only when no clause fails."""
    if db.get(Repo, body.repo) is None:
        raise ApiError(404, "not_found", f"no repo {body.repo!r}")
    policy = effective_policy()
    record = _record_from(
        body.repo,
        body.cell,
        verifier=approver.id,
        verifier_kind=verifier_kind_of(approver),
        tier=body.tier,
        note=body.note,
    )
    scope = record.scope()

    # 1. The floor, over the STORED belts — catches rows that bypassed the write path.
    _floor(db, repo=body.repo, actor=approver.id, scope=scope)
    # 2. Evidence: the cell routed under the repo's latest controls verdict, and its
    #    oracle strength from the repo's task-level mutation scores.
    arm = checks_arm_in(db, body.repo)
    rows = cell_rows(db, body.repo, scope, arm)
    controls = latest_controls_verdict(db, body.repo)
    by_task = oracle_by_task(db, body.repo)
    cell = measured_cell(rows, scope, controls, by_task)
    oracle = cell_oracle_strength(db, body.repo, rows, by_task=by_task)
    # 3. The attestation: the named row must be an accepted row of THIS cell — and the
    #    actors behind it and behind every accepted row, for the two-person rule.
    attested: ResolvedAttestation | None = None
    if body.attestation is not None:
        attested = resolve_attestation(db, body.repo, scope, body.attestation, arm)
        record = replace(record, attestation=attested.attestation)
    # 4. The policy.
    refusals = evaluate_signoff(
        record,
        cell,
        controls=controls,
        oracle_strength=oracle.strength,
        policy=policy,
        repo=body.repo,
        attested_actors=None if attested is None else attested.actors,
        cell_actors=cell_actors(db, rows),
        attested_run_id=attested_run_id_for(attested, approver.id),
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
        _EV_CHECKS: stamped.checks_arm,
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
        _VERIFIER_KIND: stamped.verifier_kind,
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
            "verifier_kind": stamped.verifier_kind,
            "row_hash": row.row_hash,
        },
    )
    db.commit()
    return signoff_out(db, row, load_signoff_rows(db, body.repo))


@router.post(
    "/signoffs/{signoff_id}/revoke",
    response_model=SignoffWithPolicyOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 503: _ERR},
    summary="Withdraw an attestation (appends a revocation row; never edits)",
)
def revoke_signoff(
    signoff_id: str,
    body: SignoffRevokeRequest,
    approver: ApproverDep,
    db: DbDep,
) -> SignoffWithPolicyOut:
    """Append a revocation row for the attestation's scope; the original row is untouched
    and is returned with ``revoked: true``. The body's ``note`` — the reason — is required
    (422 without one), the same rule the UI applies. The revocation row carries the
    revoker's ``verifier_kind`` too (who withdrew trust is as auditable as who gave it)."""
    row = db.execute(
        select(Signoff).where(Signoff.signoff_id == signoff_id, Signoff.revoke.is_(False))
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "not_found", f"no attestation {signoff_id!r}")
    all_rows = load_signoff_rows(db, row.repo)
    if _revocation_for(row, all_rows) is not None:
        raise ApiError(409, "already_revoked", f"attestation {signoff_id!r} is already revoked")
    note = body.note
    kind = verifier_kind_of(approver)  # a diagnosed 503 before the lock, never a 500 under it
    _lock(db)
    revocation = _chain_and_add(
        db,
        Signoff(
            signoff_id=uuid.uuid4().hex,
            repo=row.repo,
            cell_json={**scope_of(row).to_dict(), _VERIFIER_KIND: kind},
            tier=row.tier,
            verifier=approver.id,
            note=redact(note),
            revoke=True,
            evidence_rows=0,
            created=utc_now_iso(),
        ),
    )
    # the event carries both hashes so it can be reconciled against the chain without a
    # search by scope and time (J-TEL-8): the revocation row's, and the revoked row's
    append_system_event(
        db,
        trace_id=system_trace_id("signoffs", row.repo),
        action="signoff.revoked",
        repo=row.repo,
        actor=approver.id,
        payload={
            "signoff_id": signoff_id,
            "cell": scope_of(row).to_dict(),
            "row_hash": revocation.row_hash,
            "revokes_row_hash": row.row_hash,
            "note": revocation.note,
        },
    )
    db.commit()
    return signoff_out(db, row, load_signoff_rows(db, row.repo))


__all__ = [
    "ACCEPTED_ROWS_LIMIT",
    "CODE_FALSE_Q1",
    "CODE_ISSUER_MISSING",
    "CODE_POLICY_INVALID",
    "CODE_REFUSED",
    "FALSE_Q1_PREDICATE",
    "CellOracle",
    "ResolvedAttestation",
    "accepted_rows",
    "attested_run_id_for",
    "cell_actors",
    "cell_false_q1",
    "cell_oracle_strength",
    "cell_rows",
    "effective_policy",
    "load_signoff_records",
    "load_signoff_rows",
    "measured_cell",
    "resolve_attestation",
    "router",
    "run_actors",
    "scope_of",
    "signoff_body",
    "signoff_hash",
    "signoff_out",
    "to_record",
    "verifier_kind_of",
    "verify_signoff_rows",
]
