"""Request / response models for ``/signoffs`` under ``signoff-policy.v2``.

Extends the base shapes in :mod:`crb.server.schemas` (``SignoffOut``,
``SignoffCreateRequest``, ``SignoffEvidence``) with what the critical-friend review
asked the sign-off to carry (§5 play 06, §7 item 6): the policy in force, the route
+ reason code, the negative-controls verdict, the oracle strength, and the
approver's **attestation** that they read one specific accepted row of the cell.
``GET /signoffs/preview`` answers with :class:`SignoffPreviewOut` — what a sign-off
WOULD record and every refusal that would apply — so the UI can show the approver
the bar before they try. ``signoff-policy.v2`` adds the cell's oracle measurement
(:class:`SignoffOracleOut`: how many of the cell's tasks carry a mutation score) and
the non-relaxable ``require_oracle_measured`` switch on the policy.

Nothing here is computed: every field is a core ``to_dict`` value re-typed so the
OpenAPI document is honest and a drift is a diff.

Navigation
----------
What it is:   The request / response models for ``/signoffs`` under ``signoff-policy.v2`` —
              the attestation input, the policy, the refusals, the preview.
What it does: Validates the approver's attestation at the edge (64-hex row hash, non-blank
              statement, no extra fields) and re-types every core ``to_dict`` the sign-off
              carries (policy thresholds, refusal codes, route, controls snapshot, oracle
              measurement, accepted rows) so the OpenAPI document is exact; ``null``
              attestations pass the parser so the POLICY refuses them, with a reason.
How:          Pydantic subclasses of the base sign-off shapes in src/crb/server/schemas.py;
              validators pin ``code`` / ``state`` to the core's closed sets.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/signoffs.py (the producer and consumer),
              src/crb/core/signoff.py (``REFUSAL_CODES``, ``refusal_family``),
              src/crb/core/routing.py (``CONTROLS_STATES``), src/crb/server/schemas.py (the
              base ``SignoffOut`` / ``SignoffCreateRequest``), ui/src/api/types.ts (the
              TypeScript twin), docs/API.md#capability-routing-forecast-sign-off
Tested by:    tests/test_server_routes_signoffs.py
Touch when:   never for a new repository; when a policy clause or snapshot field is added in
              src/crb/core/signoff.py (mirror it here, then the UI type and docs/API.md).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from crb.core.routing import CONTROLS_STATES
from crb.core.signoff import REFUSAL_CODES, refusal_family
from crb.server.schemas import SignoffCreateRequest, SignoffEvidence, SignoffOut
from crb.server.schemas_capability import ControlsVerdictOut, FailureSplitOut

_ROW_HASH_LEN = 64


class AttestationIn(BaseModel):
    """The approver names the accepted (clean) row of the cell whose diff they read.
    The server resolves the row (must exist in the ledger for that cell and be
    ``clean`` — else 422) and stamps ``reviewed_task_id`` and ``at`` itself."""

    model_config = ConfigDict(extra="forbid")

    reviewed_row_hash: str = Field(min_length=_ROW_HASH_LEN, max_length=_ROW_HASH_LEN)
    statement: str = Field(min_length=1, max_length=4000)

    @field_validator("reviewed_row_hash")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = v.strip().lower()
        if any(ch not in "0123456789abcdef" for ch in v):
            raise ValueError("reviewed_row_hash must be a 64-character hex row hash")
        return v

    @field_validator("statement")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("statement must not be blank")
        return v.strip()


class SignoffCreateWithAttestationRequest(SignoffCreateRequest):
    """``POST /signoffs`` — the base body plus the attestation. ``null`` is accepted
    by the schema so the policy, not the parser, refuses it (409 ``attestation_missing``)."""

    attestation: AttestationIn | None = None


class AttestationOut(BaseModel):
    """:meth:`crb.core.signoff.Attestation.to_dict` + the reviewed task's subject."""

    reviewed_task_id: str
    reviewed_row_hash: str
    statement: str
    at: str
    subject: str = ""


class SignoffPolicyOut(BaseModel):
    """:meth:`crb.core.signoff.SignoffPolicy.to_dict` — the bar in force."""

    policy_version: str
    relaxed: bool
    non_overridable: list[str]
    bounds: dict[str, list[float]]
    n_min: int
    require_route_deliver: bool
    require_controls_passed: bool
    max_controls_escapes: int
    min_constructible_share: float
    min_oracle_strength: float
    require_oracle_measured: bool
    require_attestation: bool


class SignoffRefusalOut(BaseModel):
    """:meth:`crb.core.signoff.SignoffRefusal.to_dict` — one failing clause with the
    number that failed (``observed``) and the bar it missed (``threshold``)."""

    code: str
    message: str
    threshold: Any = None
    observed: Any = None
    overridable: bool

    @field_validator("code")
    @classmethod
    def _code_known(cls, v: str) -> str:
        if refusal_family(v) not in REFUSAL_CODES:
            raise ValueError(f"refusal code {v!r} not in {REFUSAL_CODES}")
        return v


class SignoffRouteOut(BaseModel):
    route: str
    reason: str
    reason_code: str


class SignoffControlsSnapshot(BaseModel):
    """The controls verdict as stamped into a record: the one-word verdict under the
    sign-off policy's bars plus the counts (``k`` = constructible)."""

    verdict: str
    run_id: str
    k: int
    total: int
    escapes: int
    created: str = ""

    @field_validator("verdict")
    @classmethod
    def _verdict_known(cls, v: str) -> str:
        if v and v not in CONTROLS_STATES:
            raise ValueError(f"controls verdict {v!r} not in {CONTROLS_STATES}")
        return v


class SignoffEvidenceWithOracle(SignoffEvidence):
    """The v1 snapshot plus the oracle strength (``null`` = unmeasured, never 0)."""

    oracle_strength: float | None = None


class SignoffWithPolicyOut(SignoffOut):
    """``SignoffOut`` + the policy decision the record was made under. A record
    written before the policy (``schema: crb.signoff.v1``) reports
    ``policy_version: ""``, an empty route / controls snapshot and no attestation."""

    schema_: str = Field(alias="schema", default="")
    evidence: SignoffEvidenceWithOracle
    policy_version: str
    policy_thresholds: dict[str, Any]
    route: SignoffRouteOut
    controls: SignoffControlsSnapshot
    attestation: AttestationOut | None

    model_config = ConfigDict(populate_by_name=True)


class AcceptedRowOut(BaseModel):
    """One accepted (clean, not disqualified) row of the cell an approver may attest
    to having read: its chain hash, the task it graded and that task's subject."""

    row_hash: str
    row_id: str
    task_id: str
    subject: str
    created: str
    run_id: str
    trial: str
    builder: str
    model: str
    evidence_pack_hash: str


class SignoffOracleOut(BaseModel):
    """:meth:`crb.server.routes.signoffs.CellOracle.to_dict` — the cell's oracle as the
    repo's task-level mutation scores measure it: ``strength`` is the mean over the
    ``scored`` of ``tasks`` distinct tasks that have a scoreable score (``null`` =
    unmeasured, never 0)."""

    strength: float | None
    scored: int
    tasks: int


class SignoffPreviewEvidence(BaseModel):
    """What the approver is shown before the button is enabled — every number with
    its n, its interval and its apparatus (brief non-negotiable 5). ``oracle_strength``
    is the resolved strength the policy judged (the task-level measurement, else the
    rows' own); ``oracle`` says how it was measured."""

    measured: bool
    n: int
    #: distinct tasks behind ``n`` — the clustering an approver must see (16 rows on 4 commits)
    n_tasks: int = 0
    clean: int
    point: float | None
    ci_low: float | None
    ci_high: float | None
    false_q1: int
    oracle_strength: float | None
    oracle: SignoffOracleOut
    apparatus_versions: list[str]
    belt_sets: list[str]
    model_n: int
    model_point: float | None
    #: ``null`` with ``model_point`` when unmeasured (``model_n == 0``).
    model_ci_low: float | None = None
    model_ci_high: float | None = None
    failure_split: FailureSplitOut


class SignoffPreviewOut(BaseModel):
    """``GET /signoffs/preview`` — the policy decision a ``POST /signoffs`` for this
    cell would make right now: the evidence, the route, the repo's controls verdict,
    every refusal that would apply (``signable`` ⇔ none), the snapshot the record
    would carry and the accepted rows the approver may name."""

    repo: str
    cell: dict[str, str]
    policy: SignoffPolicyOut
    evidence: SignoffPreviewEvidence
    route: SignoffRouteOut
    controls: ControlsVerdictOut
    refusals: list[SignoffRefusalOut]
    signable: bool
    would_record: dict[str, Any]
    accepted_rows: list[AcceptedRowOut]
    attestation: AttestationOut | None


__all__ = [
    "AcceptedRowOut",
    "AttestationIn",
    "AttestationOut",
    "SignoffControlsSnapshot",
    "SignoffCreateWithAttestationRequest",
    "SignoffEvidenceWithOracle",
    "SignoffOracleOut",
    "SignoffPolicyOut",
    "SignoffPreviewEvidence",
    "SignoffPreviewOut",
    "SignoffRefusalOut",
    "SignoffRouteOut",
    "SignoffWithPolicyOut",
]
