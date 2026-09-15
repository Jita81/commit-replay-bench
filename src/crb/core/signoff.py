"""Human sign-off ledger — the verification tier is EARNED, never asserted.

The grade ledger records what was *measured*; it is never rewritten. A human
attestation that the evidence for a cell was reviewed lives in a SEPARATE
append-only, hash-chained JSONL ledger of :class:`SignoffRecord` rows, and is
overlaid onto a capability map at read time (:func:`apply_signoffs`), lifting a
cell's ``verification_tier`` from ``automated-pass`` to ``human-verified`` (or
``ab-confirmed``).

Scope
-----
A record is keyed by ``(repo, cell-or-class)``: the repo whose evidence the
human reviewed (``"*"`` = an attestation that is not repo-specific) and a cell
*pattern* over the seven key fields where ``"*"`` means "any". A record
matches a cell when every pattern field equals the cell's field or is ``"*"``;
a projected cell (``"*"`` in its own key) is matched only by a pattern that is
at least as wide — a Python-only attestation never lifts a class-wide cell.

A sign-off is a policy decision, refused at write (``signoff-policy.v2``)
--------------------------------------------------------------------------
The 2026-09-13 critical-friend review (§5 play 06, §7 item 6) found that the
sign-off accepted thin cells and never showed the approver the negative-controls
verdict. :class:`SignoffPolicy` is the bar an attestation must clear; it is
evaluated by :func:`evaluate_signoff` (every failing clause, for a preview) and
enforced by :func:`check_signable` (the first failing clause, as
:class:`SignoffRefused` → HTTP 409). The clauses, in evaluation order:

* ``false_q1``                       — the cell has a false-Q1 row. Always first,
  never overridable: a human can never make an objectively wrong cell look trusted.
* ``thin_cell``                      — ``n < n_min`` (default 10).
* ``controls_unmeasured`` / ``controls_failed`` / ``controls_escapes`` /
  ``controls_thin``                  — the repo's negative-controls gate was never
  run, FAILED, let a measurement control escape, or exercised fewer than
  ``min_constructible_share`` of its controls.
* ``oracle_unmeasured``              — no task of the cell has a mutation score: the
  oracle's strength is unknown. Never overridable (``signoff-policy.v2``, DL-016): signing a
  cell whose oracle was never scored is exactly the "a green suite proves
  correctness" claim ``EVIDENCE-AND-CLAIMS`` §7 forbids — the human would be
  attesting to a number whose *meaning* was never measured. The 2026-09-14 NHS
  reading is the evidence: an oracle of 0.36 (2 of 6 tasks scoreable) and 4 of 10
  clean rows failing their own repository's type check — a weak or unmeasured
  oracle is where a human sign-off is most likely to be wrong.
* ``oracle_weak``                    — the cell's measured oracle strength is below
  ``min_oracle_strength``.
* ``route_not_deliver:<reason_code>`` — the ONE routing rule does not say ``deliver``.
* ``attestation_missing``            — the approver has not named the accepted row
  they read. Never overridable: an approver must have read at least one accepted
  diff in the cell (review §7 item 6).

The cell's oracle strength is resolved in one place (:func:`resolve_oracle_strength`):
the caller's ``oracle_strength`` (the server passes the mean of the latest task-level
mutation scores of the cell's tasks — the same per-task reduction ``/oracle/{repo}``
serves), else the route decision's, else the rows' own mean (census-imported rows
carry one). It feeds the two oracle clauses and the stamped snapshot, never the
route: the route stays the capability map's, so the two can never disagree.

A deployment may relax the numeric thresholds and the two ``require_*`` route /
controls switches (:meth:`SignoffPolicy.from_env`, bounds in :data:`POLICY_BOUNDS`);
it can never relax ``false_q1``, ``require_oracle_measured`` or
``require_attestation`` (no ``CRB_SIGNOFF__*`` knob exists for them; setting one to
anything but true is a configuration error, not a lower bar). The thresholds in force
are stamped into every record (``policy_thresholds``) so an audit reads the bar the
approver actually cleared, not today's — a ``signoff-policy.v1`` record (no
``require_oracle_measured`` threshold) still verifies and is served as signed under v1.

Cardinal invariant, enforced in BOTH directions
-----------------------------------------------
* **At write** — :meth:`JsonlSignoffLedger.append` needs the live
  :class:`~crb.core.capability.CapabilityCell` and raises
  :class:`SignoffRefused` unless the policy holds. The record's evidence snapshot
  (n, point, Wilson lower, false-Q1, oracle strength, route + reason code, the
  controls verdict, the policy and the attestation) is stamped from the cell so
  the audit trail shows what the human actually saw.
* **At read** — :func:`apply_signoffs` re-checks the cell's *current*
  ``false_q1`` and refuses to lift it; a later false-Q1 auto-invalidates the
  attestation and the gate self-heals.

Revocation is another append: a record with ``revoked=True`` for the same
scope supersedes the earlier attestation (latest record per scope wins).
Withdrawing trust never needs evidence, a verdict or an attestation.

Schema
------
``crb.signoff.v1`` records (written before the policy) hash the original ten
snapshot fields only; ``crb.signoff.v2`` records hash everything. :meth:`SignoffRecord.body`
is schema-aware so an old chain still verifies after this module learned the new
fields, and :meth:`SignoffRecord.from_dict` tolerates either shape.

Navigation
----------
What it is:   The sign-off ledger — the separate append-only, hash-chained record of human
              attestations (``SignoffRecord``), the policy that decides whether one may be
              written (``SignoffPolicy`` / ``evaluate_signoff`` / ``check_signable``), and
              the read-time overlay that lifts a cell's verification tier.
What it does: Refuses an attestation on a false-Q1 cell, a thin cell, an unmeasured or
              failed controls gate, an unmeasured or weak oracle, a route other than
              ``deliver``, or without the approver naming the accepted row they read;
              stamps the evidence and the thresholds the approver actually cleared into the
              record; lifts tiers only for cells whose CURRENT false-Q1 is 0, so a later
              defect silently withdraws the trust. A revocation is another append and
              always writes.
How:          ``JsonlSignoffLedger.append`` → ``check_signable`` (first failing clause →
              ``SignoffRefused``, HTTP 409) → ``stamp_evidence`` (cell stats, route, controls,
              ``resolve_oracle_strength``, policy) → chain + fsync; readers call
              ``active_signoffs`` (latest per scope, revoked dropped) → ``apply_signoffs``
              (``key_matches`` on the cell pattern) → ``CapabilityCell.with_tier``.
Layer:        core — docs/ARCHITECTURE.md#54-a-sign-off-refused-with-409-p4
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/capability.py (the cell and the tiers it may reach),
              src/crb/core/routing.py (the decision and the controls verdict a sign-off is
              judged on), src/crb/server/routes/signoffs.py (the write boundary that holds
              the ledger and checks the attested row is clean), src/crb/store/models.py (the
              append-only ``signoffs`` table), src/crb/core/evidence.py (canonical JSON,
              sha256), src/crb/core/redact.py (notes and statements are redacted at write)
Tested by:    tests/test_signoff.py, tests/test_server_routes_signoffs.py, tests/test_capability.py
Touch when:   never for a new repository (run ``controls`` and ``oracle`` runs so its cells
              become signable — docs/OPERATOR.md#5-sign-off-p4); relaxing a threshold is a
              deployment setting (``CRB_SIGNOFF__*`` within ``POLICY_BOUNDS``), never an
              edit here; adding a clause or a snapshot field bumps ``SIGNOFF_POLICY_VERSION``
              / ``SIGNOFF_SCHEMA``, keeps the old body hashing byte-identical, and updates
              docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2.
Claims:       A signed cell licenses exactly the claim shape in
              docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2
              — a tier, never a route, a point or an interval.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from crb.core.capability import (
    EARNED_TIERS,
    TIER_AB_CONFIRMED,
    TIER_HUMAN_VERIFIED,
    WILDCARD,
    CapabilityCell,
    CapabilityMap,
    key_matches,
)
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import GENESIS_HASH, CellKey, LedgerIntegrityError
from crb.core.redact import redact
from crb.core.routing import ROUTE_DELIVER, ControlsVerdict, RouteDecision
from crb.core.version import APPARATUS_VERSION

SIGNOFF_SCHEMA_V1 = "crb.signoff.v1"
SIGNOFF_SCHEMA = "crb.signoff.v2"
SIGNOFF_POLICY_VERSION_V1 = "signoff-policy.v1"
SIGNOFF_POLICY_VERSION = "signoff-policy.v2"

#: Earned-tier precedence when several active attestations match one cell.
_TIER_RANK: dict[str, int] = {TIER_HUMAN_VERIFIED: 1, TIER_AB_CONFIRMED: 2}

#: The v1 hashed body: every field a ``crb.signoff.v1`` record carried, minus ``row_hash``.
_V1_BODY_FIELDS: tuple[str, ...] = (
    "repo",
    "capability_class",
    "verifier",
    "size",
    "language",
    "builder",
    "model",
    "provider",
    "process_step",
    "tier",
    "note",
    "revoked",
    "verified_at",
    "n_at_signoff",
    "point_at_signoff",
    "false_q1_at_signoff",
    "apparatus_version",
    "schema",
    "record_id",
    "prev_hash",
)

# --- refusal codes (the vocabulary of SignoffRefused.code / a preview) -------------------
REFUSAL_FALSE_Q1 = "false_q1"
REFUSAL_SCOPE_MISMATCH = "scope_mismatch"
REFUSAL_THIN_CELL = "thin_cell"
REFUSAL_CONTROLS_UNMEASURED = "controls_unmeasured"
REFUSAL_CONTROLS_FAILED = "controls_failed"
REFUSAL_CONTROLS_ESCAPES = "controls_escapes"
REFUSAL_CONTROLS_THIN = "controls_thin"
REFUSAL_ORACLE_UNMEASURED = "oracle_unmeasured"
REFUSAL_ORACLE_WEAK = "oracle_weak"
REFUSAL_ROUTE_NOT_DELIVER = "route_not_deliver"  # emitted as ``route_not_deliver:<reason_code>``
REFUSAL_ATTESTATION_MISSING = "attestation_missing"
REFUSAL_CODES: tuple[str, ...] = (
    REFUSAL_FALSE_Q1,
    REFUSAL_SCOPE_MISMATCH,
    REFUSAL_THIN_CELL,
    REFUSAL_CONTROLS_UNMEASURED,
    REFUSAL_CONTROLS_FAILED,
    REFUSAL_CONTROLS_ESCAPES,
    REFUSAL_CONTROLS_THIN,
    REFUSAL_ORACLE_UNMEASURED,
    REFUSAL_ORACLE_WEAK,
    REFUSAL_ROUTE_NOT_DELIVER,
    REFUSAL_ATTESTATION_MISSING,
)
#: Clauses no deployment setting can switch off (``signoff-policy.v2`` added the oracle one).
NON_OVERRIDABLE_REFUSALS: tuple[str, ...] = (
    REFUSAL_FALSE_Q1,
    REFUSAL_ORACLE_UNMEASURED,
    REFUSAL_ATTESTATION_MISSING,
)


def refusal_family(code: str) -> str:
    """``route_not_deliver:n_below_min`` → ``route_not_deliver``; every other code as is."""
    return code.split(":", 1)[0]


class SignoffRefused(ValueError):
    """The write boundary refused an attestation. Mapped to HTTP 409 by the API.

    ``code`` is the first failing clause (one of :data:`REFUSAL_CODES`, the route
    clause suffixed with the routing reason code); ``refusals`` every failing clause
    in evaluation order, each with the number that failed and the threshold it missed.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        threshold: Any = None,
        observed: Any = None,
        refusals: Iterable[SignoffRefusal] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.threshold = threshold
        self.observed = observed
        self.refusals: tuple[SignoffRefusal, ...] = tuple(refusals)


@dataclass(frozen=True)
class SignoffRefusal:
    """One failing policy clause: the code, a sentence naming the number that failed
    and the bar it missed, and both values so a UI can show *observed vs threshold*."""

    code: str
    message: str
    threshold: Any = None
    observed: Any = None

    def __post_init__(self) -> None:
        if refusal_family(self.code) not in REFUSAL_CODES:
            raise ValueError(f"refusal code {self.code!r} not in {REFUSAL_CODES}")

    @property
    def overridable(self) -> bool:
        """Could a deployment setting have made this clause pass? (The UI says so.)"""
        return refusal_family(self.code) not in NON_OVERRIDABLE_REFUSALS

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "threshold": self.threshold,
            "observed": self.observed,
            "overridable": self.overridable,
        }


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: ``(low, high)`` inclusive bounds a deployment may move each numeric threshold within.
POLICY_BOUNDS: Mapping[str, tuple[float, float]] = {
    "n_min": (1, 10_000),
    "max_controls_escapes": (0, 100),
    "min_constructible_share": (0.0, 1.0),
    "min_oracle_strength": (0.0, 1.0),
}
#: Environment prefix a deployment relaxes the policy through (``CRB_SIGNOFF__N_MIN=…``).
POLICY_ENV_PREFIX = "CRB_SIGNOFF__"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class SignoffPolicy:
    """The bar an attestation must clear. Defaults are the published ones (DL-014;
    ``signoff-policy.v2`` keeps every number and adds the measured-oracle clause).

    ``require_attestation`` and ``require_oracle_measured`` are fields so the record
    can say they were in force; neither can be ``False`` — construction refuses it,
    as does :meth:`from_env`.
    """

    n_min: int = 10
    require_route_deliver: bool = True
    require_controls_passed: bool = True
    max_controls_escapes: int = 0
    min_constructible_share: float = 0.5
    min_oracle_strength: float = 0.80
    require_oracle_measured: bool = True
    require_attestation: bool = True
    policy_version: str = SIGNOFF_POLICY_VERSION

    def __post_init__(self) -> None:
        if not self.require_attestation:
            raise ValueError(f"require_attestation cannot be relaxed ({SIGNOFF_POLICY_VERSION})")
        if not self.require_oracle_measured:
            raise ValueError(
                f"require_oracle_measured cannot be relaxed ({SIGNOFF_POLICY_VERSION}): an "
                "unmeasured oracle is the 'green proves correctness' claim §7 forbids"
            )
        for name, (lo, hi) in POLICY_BOUNDS.items():
            v = getattr(self, name)
            if not lo <= v <= hi:
                raise ValueError(f"{name}={v!r} outside the permitted bounds [{lo}, {hi}]")
        if not self.policy_version:
            raise ValueError("policy_version is required")

    def thresholds(self) -> dict[str, Any]:
        """The numbers and switches in force — stamped into every record."""
        return {
            "n_min": self.n_min,
            "require_route_deliver": self.require_route_deliver,
            "require_controls_passed": self.require_controls_passed,
            "max_controls_escapes": self.max_controls_escapes,
            "min_constructible_share": self.min_constructible_share,
            "min_oracle_strength": self.min_oracle_strength,
            "require_oracle_measured": self.require_oracle_measured,
            "require_attestation": self.require_attestation,
        }

    @property
    def relaxed(self) -> bool:
        """True when any threshold differs from the published defaults."""
        return self.thresholds() != DEFAULT_SIGNOFF_POLICY.thresholds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "relaxed": self.relaxed,
            "non_overridable": list(NON_OVERRIDABLE_REFUSALS),
            "bounds": {k: list(v) for k, v in POLICY_BOUNDS.items()},
            **self.thresholds(),
        }

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, *, prefix: str = POLICY_ENV_PREFIX
    ) -> SignoffPolicy:
        """The policy a deployment configured: ``<prefix>N_MIN``, ``<prefix>MAX_CONTROLS_ESCAPES``,
        ``<prefix>MIN_CONSTRUCTIBLE_SHARE``, ``<prefix>MIN_ORACLE_STRENGTH``,
        ``<prefix>REQUIRE_ROUTE_DELIVER``, ``<prefix>REQUIRE_CONTROLS_PASSED``. Unset →
        the default; a value outside :data:`POLICY_BOUNDS`, a non-number, or an attempt
        to set ``<prefix>REQUIRE_ATTESTATION`` / ``<prefix>REQUIRE_ORACLE_MEASURED`` to
        anything but true → ``ValueError`` (fail closed: a misconfigured bar is not a
        lower bar)."""
        source = os.environ if env is None else env
        kw: dict[str, Any] = {}

        def _get(name: str) -> str | None:
            v = source.get(f"{prefix}{name.upper()}")
            return v.strip() if isinstance(v, str) and v.strip() else None

        for name in ("n_min", "max_controls_escapes"):
            raw = _get(name)
            if raw is not None:
                try:
                    kw[name] = int(raw)
                except ValueError as exc:
                    raise ValueError(f"{prefix}{name.upper()}={raw!r} is not an integer") from exc
        for name in ("min_constructible_share", "min_oracle_strength"):
            raw = _get(name)
            if raw is not None:
                try:
                    kw[name] = float(raw)
                except ValueError as exc:
                    raise ValueError(f"{prefix}{name.upper()}={raw!r} is not a number") from exc
        for name in (
            "require_route_deliver",
            "require_controls_passed",
            "require_oracle_measured",
            "require_attestation",
        ):
            raw = _get(name)
            if raw is None:
                continue
            low = raw.lower()
            if low in _TRUE:
                kw[name] = True
            elif low in _FALSE:
                kw[name] = False
            else:
                raise ValueError(f"{prefix}{name.upper()}={raw!r} is not a boolean")
        return cls(**kw)


DEFAULT_SIGNOFF_POLICY = SignoffPolicy()


# ---------------------------------------------------------------------------
# Attestation + record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attestation:
    """The approver's statement that they read ONE specific accepted row of the cell.

    ``reviewed_row_hash`` names the ledger row (its chain hash) whose accepted diff the
    approver read; ``reviewed_task_id`` the task it graded. The write boundary that has
    the ledger (the API) checks the row exists in the cell and is ``clean``; the core
    only insists the fields are present. ``statement`` is free text, redacted.
    """

    reviewed_task_id: str
    reviewed_row_hash: str
    statement: str
    at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.reviewed_task_id:
            raise ValueError("attestation.reviewed_task_id is required")
        if not self.reviewed_row_hash:
            raise ValueError("attestation.reviewed_row_hash is required")
        if not self.statement or not self.statement.strip():
            raise ValueError("attestation.statement is required")
        object.__setattr__(self, "statement", redact(self.statement.strip()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewed_task_id": self.reviewed_task_id,
            "reviewed_row_hash": self.reviewed_row_hash,
            "statement": self.statement,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Attestation:
        return cls(
            reviewed_task_id=str(d.get("reviewed_task_id", "")),
            reviewed_row_hash=str(d.get("reviewed_row_hash", "")),
            statement=str(d.get("statement", "")),
            at=str(d.get("at", "") or utc_now_iso()),
        )


@dataclass(frozen=True)
class SignoffRecord:
    """One human attestation about a cell scope, with the evidence it was made on."""

    repo: str
    capability_class: str
    verifier: str
    size: str = WILDCARD
    language: str = WILDCARD
    builder: str = WILDCARD
    model: str = WILDCARD
    provider: str = WILDCARD
    process_step: str = WILDCARD
    tier: str = TIER_HUMAN_VERIFIED
    note: str = ""
    revoked: bool = False
    verified_at: str = field(default_factory=utc_now_iso)
    # Evidence snapshot — what the human saw (stamped at write time from the cell).
    n_at_signoff: int = 0
    point_at_signoff: float = 0.0
    false_q1_at_signoff: int = 0
    apparatus_version: str = APPARATUS_VERSION
    # v2 snapshot — the policy decision (stamped by ``stamp_evidence``).
    ci_low_at_signoff: float = 0.0
    oracle_strength_at_signoff: float | None = None
    policy_version: str = ""
    policy_thresholds: dict[str, Any] = field(default_factory=dict)
    route_at_signoff: str = ""
    route_reason_code: str = ""
    controls_verdict: str = ""
    controls_run_id: str = ""
    controls_k: int = 0
    controls_total: int = 0
    controls_escapes: int = 0
    attestation: Attestation | None = None
    schema: str = SIGNOFF_SCHEMA
    record_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if not self.repo:
            raise ValueError("repo is required ('*' for an attestation not tied to one repo)")
        if not self.capability_class or self.capability_class == WILDCARD:
            raise ValueError("an attestation must name a capability_class")
        if not self.verifier:
            raise ValueError("verifier is required (who signed, or who revoked)")
        if self.tier not in EARNED_TIERS:
            raise ValueError(f"tier must be one of {EARNED_TIERS}, got {self.tier!r}")
        # the one clause that holds even on a record rebuilt from disk: a stored
        # attestation over false-Q1 evidence cannot be re-instantiated, let alone applied
        if self.false_q1_at_signoff > 0 and not self.revoked:
            raise SignoffRefused(
                "an attestation cannot be made on evidence with false-Q1 > 0",
                code=REFUSAL_FALSE_Q1,
                threshold=0,
                observed=self.false_q1_at_signoff,
            )
        object.__setattr__(self, "note", redact(self.note))
        object.__setattr__(self, "policy_thresholds", dict(self.policy_thresholds))
        if not self.record_id:
            object.__setattr__(self, "record_id", uuid.uuid4().hex)

    # --- scope -------------------------------------------------------------------
    def scope(self) -> CellKey:
        """The cell pattern this attestation covers (``"*"`` = any)."""
        return CellKey(
            process_step=self.process_step,
            capability_class=self.capability_class,
            size=self.size,
            language=self.language,
            builder=self.builder,
            model=self.model,
            provider=self.provider,
        )

    def key(self) -> tuple[str, ...]:
        """Identity for latest-wins collapse: ``(repo, *scope)``."""
        return (self.repo, *self.scope().to_tuple())

    def matches(self, cell: CapabilityCell, *, repo: str = WILDCARD) -> bool:
        """True when the record's repo covers ``repo`` and its scope covers the cell."""
        return self.repo in (WILDCARD, repo) and key_matches(self.scope(), cell.key)

    # --- hashing ------------------------------------------------------------------
    def body(self) -> dict[str, Any]:
        """Everything hashed: the v1 fields for a ``crb.signoff.v1`` record (so an old
        chain still verifies), every field but ``row_hash`` otherwise."""
        names = (
            _V1_BODY_FIELDS
            if self.schema == SIGNOFF_SCHEMA_V1
            else tuple(k for k in self.__dataclass_fields__ if k != "row_hash")
        )
        out: dict[str, Any] = {}
        for k in names:
            v = getattr(self, k)
            out[k] = v.to_dict() if isinstance(v, Attestation) else v
        return out

    def compute_hash(self) -> str:
        """SHA-256 of the canonical JSON of :meth:`body` (``prev_hash`` included)."""
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> SignoffRecord:
        """A copy with ``prev_hash`` set and ``row_hash`` computed (the ledger's job)."""
        rec = replace(self, prev_hash=prev_hash)
        object.__setattr__(rec, "row_hash", rec.compute_hash())
        return rec

    def verify_hash(self) -> bool:
        """``True`` iff the stored ``row_hash`` is the hash of the body as read back."""
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation --------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Every field, the attestation and thresholds as plain dicts."""
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["attestation"] = None if self.attestation is None else self.attestation.to_dict()
        d["policy_thresholds"] = dict(self.policy_thresholds)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SignoffRecord:
        """Tolerates a v1 record (no policy / attestation fields → their defaults) and a
        v2 one; unknown keys are ignored."""
        kw = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        att = kw.get("attestation")
        kw["attestation"] = Attestation.from_dict(att) if isinstance(att, Mapping) else None
        if not isinstance(kw.get("policy_thresholds"), Mapping):
            kw["policy_thresholds"] = {}
        return cls(**kw)


def resolve_oracle_strength(
    cell: CapabilityCell,
    *,
    decision: RouteDecision | None = None,
    oracle_strength: float | None = None,
) -> float | None:
    """The ONE resolution of a cell's oracle strength for the sign-off policy.

    ``oracle_strength`` is the caller's measurement (the server: the mean of the
    latest task-level mutation scores of the cell's tasks, from the oracle events —
    ``None`` = it found none); else the route decision's (``decision`` defaults to
    the cell's own); else the rows' own mean (census-imported rows carry one).
    ``None`` all the way down means *unmeasured* — never 0.0, never a pass.
    """
    if oracle_strength is not None:
        return oracle_strength
    d = decision if decision is not None else cell.decision
    if d is not None and d.oracle_strength is not None:
        return d.oracle_strength
    return cell.stats.oracle_strength_mean if cell.stats is not None else None


def stamp_evidence(
    record: SignoffRecord,
    cell: CapabilityCell,
    *,
    controls: ControlsVerdict | None = None,
    decision: RouteDecision | None = None,
    oracle_strength: float | None = None,
    policy: SignoffPolicy = DEFAULT_SIGNOFF_POLICY,
) -> SignoffRecord:
    """Copy the cell's current evidence, the route decision, the controls verdict, the
    resolved oracle strength and the policy in force into the record's snapshot
    fields (the attestation is the approver's and stays as given)."""
    if cell.stats is None:
        raise SignoffRefused(
            f"cell {cell.label!r} has no measured evidence to attest to",
            code=REFUSAL_THIN_CELL,
            threshold=policy.n_min,
            observed=0,
        )
    d = decision if decision is not None else cell.decision
    c = controls if controls is not None else (d.controls if d is not None else None)
    strength = resolve_oracle_strength(cell, decision=d, oracle_strength=oracle_strength)
    return replace(
        record,
        n_at_signoff=cell.stats.n,
        point_at_signoff=cell.stats.point,
        ci_low_at_signoff=cell.stats.ci.low,
        false_q1_at_signoff=cell.stats.false_q1,
        apparatus_version=",".join(cell.stats.apparatus_versions) or record.apparatus_version,
        oracle_strength_at_signoff=strength,
        policy_version=policy.policy_version,
        policy_thresholds=policy.thresholds(),
        route_at_signoff=d.route if d is not None else "",
        route_reason_code=d.reason_code if d is not None else "",
        controls_verdict=_controls_state(c, policy),
        controls_run_id=c.run_id if c is not None else "",
        controls_k=c.constructible if c is not None else 0,
        controls_total=c.total if c is not None else 0,
        controls_escapes=c.escapes if c is not None else 0,
    )


def _controls_state(c: ControlsVerdict | None, policy: SignoffPolicy) -> str:
    """The one-word verdict under the SIGN-OFF policy's bars (``unmeasured`` when the
    caller evaluated none)."""
    if c is None:
        return "unmeasured"
    return c.state(
        min_share=policy.min_constructible_share, max_escapes=policy.max_controls_escapes
    )


# ---------------------------------------------------------------------------
# The policy decision
# ---------------------------------------------------------------------------


def evaluate_signoff(
    record: SignoffRecord,
    cell: CapabilityCell,
    *,
    controls: ControlsVerdict | None = None,
    decision: RouteDecision | None = None,
    oracle_strength: float | None = None,
    policy: SignoffPolicy = DEFAULT_SIGNOFF_POLICY,
    repo: str = WILDCARD,
) -> tuple[SignoffRefusal, ...]:
    """Every clause of ``policy`` that ``record`` fails against ``cell``, in the order
    the module docstring publishes. Empty ⇒ signable.

    ``decision`` defaults to the cell's own; ``controls`` to the decision's verdict
    (``None`` = the caller evaluated none, which the policy reads as *unmeasured*);
    ``oracle_strength`` is the caller's measurement of the cell's oracle (see
    :func:`resolve_oracle_strength`; ``None`` = it found none, and the cell falls
    back to what its decision / rows carry — *unmeasured* when nothing does).
    A false-Q1 cell or a scope mismatch is returned alone — nothing else about such
    a cell matters. A revocation never fails (withdrawing trust needs no evidence).
    """
    if record.revoked:
        return ()
    # scope and false-Q1 are returned ALONE: listing thin_cell etc. beside them would
    # invite fixing the wrong thing
    if not record.matches(cell, repo=repo):
        return (
            SignoffRefusal(
                REFUSAL_SCOPE_MISMATCH,
                f"attestation scope {record.key()} does not cover cell {cell.key.label!r} "
                f"for repo {repo!r}",
            ),
        )
    fq1 = cell.stats.false_q1 if cell.stats is not None else 0
    if fq1 > 0 or record.false_q1_at_signoff > 0:
        observed = max(fq1, record.false_q1_at_signoff)
        return (
            SignoffRefusal(
                REFUSAL_FALSE_Q1,
                f"cell {cell.label!r} has false_q1={observed} > 0 — untrusted, cannot be signed off",
                threshold=0,
                observed=observed,
            ),
        )

    out: list[SignoffRefusal] = []
    n = cell.stats.n if cell.stats is not None else 0
    if n < policy.n_min:
        what = "no measured evidence" if cell.stats is None else f"n={n}"
        out.append(
            SignoffRefusal(
                REFUSAL_THIN_CELL,
                f"cell {cell.label!r} is thin: {what} < n_min={policy.n_min}",
                threshold=policy.n_min,
                observed=n,
            )
        )

    d = decision if decision is not None else cell.decision
    c = controls if controls is not None else (d.controls if d is not None else None)
    if policy.require_controls_passed:
        if c is None or not c.measured:
            out.append(
                SignoffRefusal(
                    REFUSAL_CONTROLS_UNMEASURED,
                    "the negative-controls gate was never run for this repo — nothing "
                    "measured here can be signed off until a 'controls' run passes",
                    threshold="measured",
                    observed="unmeasured",
                )
            )
        else:
            run = f" (controls run {c.run_id[:8]})" if c.run_id else ""
            if not c.passed:
                out.append(
                    SignoffRefusal(
                        REFUSAL_CONTROLS_FAILED,
                        f"the negative-controls gate FAILED on this repo{run} — an instrument "
                        "defect; nothing measured under it can be signed off",
                        threshold="passed",
                        observed="failed",
                    )
                )
            if c.escapes > policy.max_controls_escapes:
                out.append(
                    SignoffRefusal(
                        REFUSAL_CONTROLS_ESCAPES,
                        f"{c.escapes} measurement control(s) graded clean on this repo{run} "
                        f"> max_controls_escapes={policy.max_controls_escapes} — the oracle "
                        "cannot tell an implementation from a cheat",
                        threshold=policy.max_controls_escapes,
                        observed=c.escapes,
                    )
                )
            if c.thin(policy.min_constructible_share):
                out.append(
                    SignoffRefusal(
                        REFUSAL_CONTROLS_THIN,
                        f"only {c.constructible} of {c.total} control rows were constructible"
                        f"{run}: share {c.share:.2f} < min_constructible_share="
                        f"{policy.min_constructible_share:.2f} — 'passed' means the easy "
                        "controls passed",
                        threshold=policy.min_constructible_share,
                        observed=round(c.share, 4),
                    )
                )

    strength = resolve_oracle_strength(cell, decision=d, oracle_strength=oracle_strength)
    if strength is None:
        # signoff-policy.v2: "≥ min_oracle_strength when measured" became "measured AND ≥".
        # No knob turns this off — an unmeasured oracle is the §7 claim in disguise.
        out.append(
            SignoffRefusal(
                REFUSAL_ORACLE_UNMEASURED,
                f"no task of cell {cell.label!r} has a mutation score — the oracle's "
                "strength is unknown, so a green here is not evidence; run an 'oracle' run "
                "on this repo before signing (cannot be relaxed)",
                threshold="measured",
                observed=None,
            )
        )
    elif strength < policy.min_oracle_strength:
        out.append(
            SignoffRefusal(
                REFUSAL_ORACLE_WEAK,
                f"oracle strength {strength:.2f} < min_oracle_strength="
                f"{policy.min_oracle_strength:.2f} — green cannot license auto-delivery",
                threshold=policy.min_oracle_strength,
                observed=round(strength, 4),
            )
        )

    if policy.require_route_deliver:
        if d is None:
            out.append(
                SignoffRefusal(
                    f"{REFUSAL_ROUTE_NOT_DELIVER}:unrouted",
                    f"cell {cell.label!r} has no route decision — nothing to sign off",
                    threshold=ROUTE_DELIVER,
                    observed="",
                )
            )
        elif d.route != ROUTE_DELIVER:
            out.append(
                SignoffRefusal(
                    f"{REFUSAL_ROUTE_NOT_DELIVER}:{d.reason_code or 'unknown'}",
                    f"the routing rule says {d.route!r} ({d.reason_code}): {d.reason}",
                    threshold=ROUTE_DELIVER,
                    observed=d.route,
                )
            )

    if policy.require_attestation and record.attestation is None:
        out.append(
            SignoffRefusal(
                REFUSAL_ATTESTATION_MISSING,
                "the approver must name one accepted (clean) row of this cell whose diff "
                "they have read, with a statement",
                threshold="reviewed_row_hash + statement",
                observed="",
            )
        )
    return tuple(out)


def check_signable(
    record: SignoffRecord,
    cell: CapabilityCell,
    *,
    controls: ControlsVerdict | None = None,
    decision: RouteDecision | None = None,
    oracle_strength: float | None = None,
    policy: SignoffPolicy = DEFAULT_SIGNOFF_POLICY,
    repo: str = WILDCARD,
) -> None:
    """Raise :class:`SignoffRefused` (the first failing clause, all of them attached)
    unless ``record`` may be written against ``cell`` under ``policy``.

    A revocation is always writable (withdrawing trust never needs evidence).
    """
    refusals = evaluate_signoff(
        record,
        cell,
        controls=controls,
        decision=decision,
        oracle_strength=oracle_strength,
        policy=policy,
        repo=repo,
    )
    if refusals:
        first = refusals[0]
        raise SignoffRefused(
            first.message,
            code=first.code,
            threshold=first.threshold,
            observed=first.observed,
            refusals=refusals,
        )


# ---------------------------------------------------------------------------
# JSONL ledger (append-only, hash-chained)
# ---------------------------------------------------------------------------


class JsonlSignoffLedger:
    """Portable stdlib sign-off ledger. Same chain discipline as the grade ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        """The last record's ``row_hash`` (tail read, as the grade ledger does), or
        :data:`GENESIS_HASH` for an empty or absent file."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        last = ""
        with self.path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            step = min(size, 65536)
            f.seek(size - step)
            chunk = f.read().decode("utf-8", errors="replace")
        for line in reversed(chunk.splitlines()):
            if line.strip():
                last = line
                break
        if not last:
            return GENESIS_HASH
        row_hash = str(json.loads(last).get("row_hash", ""))
        if not row_hash:
            raise LedgerIntegrityError(f"last record in {self.path} has no row_hash")
        return row_hash

    def append(
        self,
        record: SignoffRecord,
        cell: CapabilityCell | None = None,
        *,
        repo: str = WILDCARD,
        controls: ControlsVerdict | None = None,
        oracle_strength: float | None = None,
        policy: SignoffPolicy = DEFAULT_SIGNOFF_POLICY,
    ) -> SignoffRecord:
        """Check, stamp, chain and append. Returns the chained record.

        ``cell`` is the live cell the human reviewed; it is required for an
        attestation (the write boundary applies ``policy`` against it, the repo's
        ``controls`` verdict and the caller's ``oracle_strength`` measurement) and
        optional for a revocation.
        """
        if not record.revoked:
            if cell is None:
                raise SignoffRefused(
                    "an attestation needs the live cell it is made on",
                    code=REFUSAL_THIN_CELL,
                    threshold=policy.n_min,
                    observed=0,
                )
            check_signable(
                record,
                cell,
                controls=controls,
                oracle_strength=oracle_strength,
                policy=policy,
                repo=repo,
            )
            record = stamp_evidence(
                record, cell, controls=controls, oracle_strength=oracle_strength, policy=policy
            )
        chained = record.chained(self._last_hash())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return chained

    def records(self) -> Iterator[SignoffRecord]:
        """Every record in file order; nothing for an absent file."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield SignoffRecord.from_dict(json.loads(line))

    def verify(self) -> int:
        """Walk the chain; return the record count; raise on any break."""
        return verify_signoff_chain(self.records())


def verify_signoff_chain(records: Iterable[SignoffRecord]) -> int:
    """Prove ``records`` is an unbroken chain from genesis (the sign-off twin of
    :func:`~crb.core.ledger.verify_chain`); raises :class:`LedgerIntegrityError`."""
    prev = GENESIS_HASH
    n = 0
    for rec in records:
        n += 1
        if rec.prev_hash != prev:
            raise LedgerIntegrityError(f"sign-off {n} ({rec.record_id[:8]}) prev_hash mismatch")
        if not rec.verify_hash():
            raise LedgerIntegrityError(f"sign-off {n} ({rec.record_id[:8]}) row_hash mismatch")
        prev = rec.row_hash
    return n


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


def active_signoffs(records: Iterable[SignoffRecord]) -> dict[tuple[str, ...], SignoffRecord]:
    """Collapse the log to the latest record per scope; drop revoked scopes."""
    latest: dict[tuple[str, ...], SignoffRecord] = {}
    for rec in records:
        latest[rec.key()] = rec
    return {k: r for k, r in latest.items() if not r.revoked}


def apply_signoffs(
    cells: Iterable[CapabilityCell],
    signoffs: Iterable[SignoffRecord],
    *,
    repo: str = WILDCARD,
) -> list[CapabilityCell]:
    """Lift matching cells to their attested tier; return NEW cells.

    A cell is lifted only when it is measured, its CURRENT ``false_q1`` is 0 and
    an active attestation covers it for ``repo`` (``"*"`` applies only records
    that are themselves repo-agnostic — an unscoped read never borrows another
    repo's attestation). The highest matching earned tier wins. Everything else
    passes through unchanged.
    """
    active = list(active_signoffs(signoffs).values())
    out: list[CapabilityCell] = []
    for cell in cells:
        # the read-time half of the invariant: trust is withheld the moment the
        # cell's own evidence stops deserving it, whatever was signed earlier
        if cell.stats is None or cell.stats.false_q1 > 0:
            out.append(cell)
            continue
        tiers = [r.tier for r in active if r.matches(cell, repo=repo)]
        if not tiers:
            out.append(cell)
            continue
        best = max(tiers, key=lambda t: _TIER_RANK.get(t, 0))
        current = _TIER_RANK.get(cell.verification_tier or "", 0)
        out.append(cell.with_tier(best) if _TIER_RANK[best] > current else cell)
    return out


def apply_signoffs_to_map(
    cmap: CapabilityMap, signoffs: Iterable[SignoffRecord], *, repo: str = WILDCARD
) -> CapabilityMap:
    """:func:`apply_signoffs` over a whole map; returns a new map, same projection."""
    return cmap.with_cells(apply_signoffs(cmap.cells, signoffs, repo=repo))
