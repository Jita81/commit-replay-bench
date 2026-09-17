"""crb.core.signoff — human attestations: append-only, hash-chained, revocable, and
NEVER able to lift a false-Q1 cell (refused at write, re-checked at read).

Ports the upstream test_signoff_ledger cases onto crb types and adds the chain,
the write-boundary refusal (→ HTTP 409 at the API), the scope rules and — since
``signoff-policy.v1`` — the policy decision: every refusal code, the non-overridable
clauses, the operator-adjustable bounds, the v2 snapshot and the v1-record tolerance.
``signoff-policy.v2`` (2026-09-14, the fable-decider's ``signoff-policy: adjust``)
adds the third non-overridable clause: the cell's oracle strength must be MEASURED
(``oracle_unmeasured``), not merely "≥ 0.80 when measured".

Navigation
----------
What it is:   The sign-off ledger's test suite — human attestations that are append-only,
              hash-chained, revocable and never able to lift a false-Q1 cell.
What it does: Pins the record's required fields and redaction, the policy decision under
              ``signoff-policy.v2`` — every refusal code, the non-overridable clauses (false-Q1
              first, ``oracle_unmeasured``, attestation missing), the operator-adjustable bounds
              from the environment, the v1-record tolerance — the chain and its tamper detection,
              that a write refuses a false-Q1, unmeasured, thin or scope-mismatched cell, that
              apply elevates only the matching cell and never downgrades or changes the route,
              and that a revoked record does not elevate.
How:          Synthetic cells through ``crb.core.capability``; ``check_signable`` / ``append`` /
              ``apply_signoffs`` on a temp JSONL ledger.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/signoff.py (under test), src/crb/core/capability.py (the cells it
              decides on), src/crb/core/routing.py (``ControlsVerdict`` and the route the policy
              wraps), tests/test_server_routes_signoffs.py (the same decision as HTTP 409),
              docs/EVIDENCE-AND-CLAIMS.md (what a signed cell may be claimed to mean)
Tested by:    tests/test_signoff.py
Touch when:   the policy gains a clause or a version (a refusal case, the defaults case and the
              older-record tolerance case together; update docs/EVIDENCE-AND-CLAIMS.md and the
              decision log).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from crb.core import capability as cap
from crb.core import signoff as so
from crb.core.ledger import GradeRow, LedgerIntegrityError
from crb.core.routing import ROUTE_DELIVER, ROUTE_HUMAN, ControlsVerdict
from crb.core.version import APPARATUS_VERSION

PACK = "b" * 64
ROW_HASH = "c" * 64
#: The rows' own oracle strength (census-imported rows carry one); ``None`` = unmeasured.
ORACLE = 0.9

#: A controls verdict that clears the policy: passed, 5 of 7 constructible, no escape.
PASSED = ControlsVerdict(passed=True, constructible=5, total=7, escapes=0, run_id="ctl00001")


def _row(
    *,
    clean: bool = True,
    cls: str = "frontend.component.add",
    size: str = "S",
    language: str = "python",
    model: str = "gpt-oss-120b",
    repo: str = "todo",
    task_id: str = "0123456789abcdef",
    oracle_strength: float | None = ORACLE,
) -> GradeRow:
    return GradeRow(
        repo=repo,
        task_id=task_id,
        clean=clean,
        tests_unmodified=True,
        target_green=clean,
        no_new_failures=True,
        source_changed=True,
        capability_class=cls,
        size=size,
        language=language,
        builder="cline",
        model=model,
        provider="cerebras",
        evidence_pack_hash=PACK if clean else "",
        oracle_strength=oracle_strength,
    )


def _rows(n: int, clean: int, **kw: object) -> list[GradeRow]:
    return [_row(clean=i < clean, task_id=f"{i:016x}", **kw) for i in range(n)]  # type: ignore[arg-type]


def _cell(
    rows: list[GradeRow], *, controls: ControlsVerdict | None = None, **key: str
) -> cap.CapabilityCell:
    return cap.build_capability_map(rows, controls=controls).get(**key)


def _attestation(**kw: str) -> so.Attestation:
    base = {
        "reviewed_task_id": "0000000000000000",
        "reviewed_row_hash": ROW_HASH,
        "statement": "I read the accepted diff for task 0 and it does what the commit says.",
        "at": "2026-09-14T09:00:00+00:00",
    }
    base.update(kw)
    return so.Attestation(**base)


def _signoff(
    cls: str = "frontend.component.add",
    *,
    repo: str = "todo",
    size: str = "*",
    verifier: str = "alice@x.com",
    revoked: bool = False,
    tier: str = cap.TIER_HUMAN_VERIFIED,
    note: str = "reviewed evidence",
    attested: bool = True,
    **scope: str,
) -> so.SignoffRecord:
    return so.SignoffRecord(
        repo=repo,
        capability_class=cls,
        size=size,
        verifier=verifier,
        verified_at="2026-06-05T01:00:00+00:00",
        note=note,
        revoked=revoked,
        tier=tier,
        attestation=_attestation() if attested else None,
        **scope,
    )


def _signable_cell(**key: str) -> cap.CapabilityCell:
    """16 clean rows (oracle 0.9 measured on the rows) under a passing controls verdict →
    routes ``deliver`` (Wilson lower 0.806 ≥ 0.80; twelve clean rows would only reach
    0.758)."""
    key = key or {"capability_class": "frontend.component.add", "size": "S"}
    return _cell(_rows(16, 16), controls=PASSED, **key)


def _codes(refusals: tuple[so.SignoffRefusal, ...]) -> list[str]:
    return [r.code for r in refusals]


# ---------------------------------------------------------------------------
# record invariants
# ---------------------------------------------------------------------------


def test_record_requires_class_verifier_and_earned_tier() -> None:
    with pytest.raises(ValueError, match="capability_class"):
        _signoff("*")
    with pytest.raises(ValueError, match="verifier"):
        _signoff(verifier="")
    with pytest.raises(ValueError, match="tier must be"):
        _signoff(tier=cap.TIER_AUTOMATED_PASS)
    with pytest.raises(ValueError, match="repo is required"):
        _signoff(repo="")


def test_record_refuses_false_q1_snapshot_and_redacts_note() -> None:
    with pytest.raises(so.SignoffRefused) as ei:
        so.SignoffRecord(repo="todo", capability_class="c", verifier="v", false_q1_at_signoff=1)
    assert ei.value.code == so.REFUSAL_FALSE_Q1 and ei.value.observed == 1
    rec = _signoff(note="token=sk-live-abcdefghijklmnopqrstuvwxyz0123")
    assert "sk-live" not in rec.note and "REDACTED" in rec.note


def test_attestation_requires_row_task_and_statement_and_redacts() -> None:
    with pytest.raises(ValueError, match="reviewed_task_id"):
        _attestation(reviewed_task_id="")
    with pytest.raises(ValueError, match="reviewed_row_hash"):
        _attestation(reviewed_row_hash="")
    with pytest.raises(ValueError, match="statement"):
        _attestation(statement="   ")
    att = _attestation(statement="read it; key sk-live-abcdefghijklmnopqrstuvwxyz0123")
    assert "sk-live" not in att.statement and "REDACTED" in att.statement
    assert so.Attestation.from_dict(att.to_dict()) == att


def test_record_roundtrip_and_hash_v2() -> None:
    rec = _signoff().chained("0" * 64)
    assert rec.schema == so.SIGNOFF_SCHEMA and rec.verify_hash()
    d = json.loads(json.dumps(rec.to_dict()))
    assert d["attestation"]["reviewed_row_hash"] == ROW_HASH  # nested, hashed
    again = so.SignoffRecord.from_dict(d)
    assert again == rec and again.verify_hash()
    assert rec.key() == ("todo", "*", "frontend.component.add", "*", "*", "*", "*", "*")
    # the attestation is covered by the hash: change it → the row no longer verifies
    tampered = so.SignoffRecord.from_dict(
        {**d, "attestation": {**d["attestation"], "statement": "x"}}
    )
    assert not tampered.verify_hash()


def test_policy_v1_record_still_verifies_and_reads_as_v1() -> None:
    """A record signed under ``signoff-policy.v1`` (schema v2, thresholds without
    ``require_oracle_measured``) keeps its hash and its stamped version after the
    policy moved to v2 — the bar it cleared is the bar it says it cleared."""
    v1_thresholds = {
        "n_min": 10,
        "require_route_deliver": True,
        "require_controls_passed": True,
        "max_controls_escapes": 0,
        "min_constructible_share": 0.5,
        "min_oracle_strength": 0.8,
        "require_attestation": True,
    }
    rec = so.SignoffRecord(
        repo="todo",
        capability_class="frontend.component.add",
        verifier="alice@x.com",
        n_at_signoff=16,
        point_at_signoff=1.0,
        ci_low_at_signoff=0.806,
        oracle_strength_at_signoff=None,
        policy_version=so.SIGNOFF_POLICY_VERSION_V1,
        policy_thresholds=v1_thresholds,
        route_at_signoff="deliver",
        route_reason_code="deliver",
        controls_verdict="passed",
        attestation=_attestation(),
    ).chained("0" * 64)
    assert rec.verify_hash() and so.verify_signoff_chain([rec]) == 1
    again = so.SignoffRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert again == rec and again.verify_hash()
    assert again.policy_version == "signoff-policy.v1"
    assert "require_oracle_measured" not in again.policy_thresholds
    assert again.oracle_strength_at_signoff is None  # what it saw: unmeasured, under v1
    # a v2 record chains after it (the version is data on the record, not a constant)
    nxt = so.stamp_evidence(_signoff(), _signable_cell(), controls=PASSED).chained(rec.row_hash)
    assert nxt.policy_version == "signoff-policy.v2"
    assert so.verify_signoff_chain([rec, nxt]) == 2


def test_v1_record_still_verifies_and_loads_with_defaults() -> None:
    """A record written before the policy (schema v1, ten snapshot fields) keeps its
    hash after this module learned the v2 fields — an old chain never breaks."""
    v1 = {
        "repo": "todo",
        "capability_class": "frontend.component.add",
        "verifier": "alice@x.com",
        "size": "*",
        "language": "*",
        "builder": "*",
        "model": "*",
        "provider": "*",
        "process_step": "*",
        "tier": "human-verified",
        "note": "reviewed evidence",
        "revoked": False,
        "verified_at": "2026-06-05T01:00:00+00:00",
        "n_at_signoff": 12,
        "point_at_signoff": 1.0,
        "false_q1_at_signoff": 0,
        "apparatus_version": "2.0",
        "schema": so.SIGNOFF_SCHEMA_V1,
        "record_id": "a" * 32,
        "prev_hash": "0" * 64,
    }
    # the hash a v1 writer produced: canonical JSON of exactly these fields
    from crb.core.evidence import canonical_json, sha256_text

    v1["row_hash"] = sha256_text(canonical_json({k: v for k, v in v1.items() if k != "row_hash"}))
    rec = so.SignoffRecord.from_dict(v1)
    assert rec.verify_hash()
    assert rec.attestation is None and rec.policy_version == "" and rec.controls_k == 0
    assert so.verify_signoff_chain([rec]) == 1
    # and it round-trips as v1 (the schema is data, not a constant applied on read)
    assert so.SignoffRecord.from_dict(json.loads(json.dumps(rec.to_dict()))).verify_hash()


# ---------------------------------------------------------------------------
# policy: defaults, bounds, environment
# ---------------------------------------------------------------------------


def test_policy_defaults_are_the_published_ones() -> None:
    """signoff-policy.v2 keeps every v1 number (DL-014) and adds the measured-oracle
    clause as a stamped, non-relaxable switch."""
    p = so.DEFAULT_SIGNOFF_POLICY
    assert p.policy_version == "signoff-policy.v2" == so.SIGNOFF_POLICY_VERSION
    assert so.SIGNOFF_POLICY_VERSION_V1 == "signoff-policy.v1"
    assert p.thresholds() == {
        "n_min": 10,
        "require_route_deliver": True,
        "require_controls_passed": True,
        "max_controls_escapes": 0,
        "min_constructible_share": 0.5,
        "min_oracle_strength": 0.8,
        "require_oracle_measured": True,
        "require_attestation": True,
    }
    assert not p.relaxed
    d = p.to_dict()
    assert d["non_overridable"] == ["false_q1", "oracle_unmeasured", "attestation_missing"]
    assert d["bounds"]["n_min"] == [1, 10_000]
    assert "require_oracle_measured" not in so.POLICY_BOUNDS  # a switch with no knob


def test_policy_bounds_and_non_relaxable_attestation() -> None:
    with pytest.raises(ValueError, match="require_attestation cannot be relaxed"):
        so.SignoffPolicy(require_attestation=False)
    with pytest.raises(ValueError, match="require_oracle_measured cannot be relaxed"):
        so.SignoffPolicy(require_oracle_measured=False)
    with pytest.raises(ValueError, match="n_min=0 outside"):
        so.SignoffPolicy(n_min=0)
    with pytest.raises(ValueError, match=r"min_constructible_share=1\.5 outside"):
        so.SignoffPolicy(min_constructible_share=1.5)
    with pytest.raises(ValueError, match="max_controls_escapes=-1 outside"):
        so.SignoffPolicy(max_controls_escapes=-1)
    assert so.SignoffPolicy(n_min=5, max_controls_escapes=1).relaxed


def test_policy_from_env_parses_relaxes_and_fails_closed() -> None:
    assert so.SignoffPolicy.from_env({}) == so.DEFAULT_SIGNOFF_POLICY
    p = so.SignoffPolicy.from_env(
        {
            "CRB_SIGNOFF__N_MIN": "5",
            "CRB_SIGNOFF__MAX_CONTROLS_ESCAPES": "1",
            "CRB_SIGNOFF__MIN_CONSTRUCTIBLE_SHARE": "0.25",
            "CRB_SIGNOFF__MIN_ORACLE_STRENGTH": "0.7",
            "CRB_SIGNOFF__REQUIRE_ROUTE_DELIVER": "false",
            "CRB_SIGNOFF__REQUIRE_CONTROLS_PASSED": "off",
            "CRB_SIGNOFF__REQUIRE_ATTESTATION": "yes",
            "CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED": "true",
            "CRB_SIGNOFF__UNKNOWN": "ignored",
        }
    )
    assert (p.n_min, p.max_controls_escapes, p.min_constructible_share) == (5, 1, 0.25)
    assert p.min_oracle_strength == 0.7
    assert not p.require_route_deliver and not p.require_controls_passed
    assert p.require_attestation and p.require_oracle_measured and p.relaxed
    with pytest.raises(ValueError, match="cannot be relaxed"):
        so.SignoffPolicy.from_env({"CRB_SIGNOFF__REQUIRE_ATTESTATION": "0"})
    with pytest.raises(ValueError, match="require_oracle_measured cannot be relaxed"):
        so.SignoffPolicy.from_env({"CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED": "false"})
    with pytest.raises(ValueError, match="not an integer"):
        so.SignoffPolicy.from_env({"CRB_SIGNOFF__N_MIN": "ten"})
    with pytest.raises(ValueError, match="not a boolean"):
        so.SignoffPolicy.from_env({"CRB_SIGNOFF__REQUIRE_ROUTE_DELIVER": "maybe"})
    with pytest.raises(ValueError, match="outside the permitted bounds"):
        so.SignoffPolicy.from_env({"CRB_SIGNOFF__N_MIN": "0"})


# ---------------------------------------------------------------------------
# policy: every refusal code
# ---------------------------------------------------------------------------


def test_signable_cell_has_no_refusals() -> None:
    cell = _signable_cell()
    assert cell.route == ROUTE_DELIVER
    assert so.evaluate_signoff(_signoff(), cell, controls=PASSED, repo="todo") == ()
    so.check_signable(_signoff(), cell, controls=PASSED, repo="todo")  # does not raise


def test_refusal_false_q1_is_first_alone_and_not_overridable() -> None:
    bad = _row()
    object.__setattr__(bad, "target_green", False)  # a false-Q1 row that bypassed write
    cell = _cell(
        [*_rows(12, 12), bad],
        controls=PASSED,
        capability_class="frontend.component.add",
        size="S",
    )
    assert cell.false_q1 == 1
    # thin, unmeasured controls, no attestation … none of it is even listed
    refusals = so.evaluate_signoff(_signoff(attested=False), cell, controls=None, repo="todo")
    assert _codes(refusals) == ["false_q1"]
    assert refusals[0].threshold == 0 and refusals[0].observed == 1
    assert not refusals[0].overridable
    with pytest.raises(so.SignoffRefused, match="false_q1=1") as ei:
        so.check_signable(_signoff(), cell, controls=PASSED, repo="todo")
    assert ei.value.code == "false_q1" and [r.code for r in ei.value.refusals] == ["false_q1"]
    # no policy can switch it off
    relaxed = so.SignoffPolicy(n_min=1, require_route_deliver=False, require_controls_passed=False)
    with pytest.raises(so.SignoffRefused):
        so.check_signable(_signoff(), cell, policy=relaxed, repo="todo")


def test_refusal_thin_cell_names_n_and_n_min() -> None:
    cell = _cell(_rows(4, 4), controls=PASSED, capability_class="frontend.component.add", size="S")
    refusals = so.evaluate_signoff(_signoff(), cell, controls=PASSED, repo="todo")
    thin = refusals[0]
    assert thin.code == "thin_cell" and thin.threshold == 10 and thin.observed == 4
    assert "n=4 < n_min=10" in thin.message and thin.overridable
    # the route clause fails too (n_below_min) — both are listed, the route one suffixed
    assert _codes(refusals) == ["thin_cell", "route_not_deliver:n_below_min"]
    # relaxing n_min (within bounds) clears it; the route clause still holds at n=4
    relaxed = so.SignoffPolicy(n_min=4)
    assert _codes(
        so.evaluate_signoff(_signoff(), cell, controls=PASSED, policy=relaxed, repo="todo")
    ) == ["route_not_deliver:n_below_min"]
    assert (
        so.evaluate_signoff(
            _signoff(),
            cell,
            controls=PASSED,
            policy=so.SignoffPolicy(n_min=4, require_route_deliver=False),
            repo="todo",
        )
        == ()
    )


def test_refusal_unmeasured_cell_is_thin() -> None:
    empty = _cell([], capability_class="frontend.component.add", size="S")
    refusals = so.evaluate_signoff(_signoff(), empty, controls=PASSED, repo="todo")
    assert refusals[0].code == "thin_cell" and refusals[0].observed == 0
    assert "no measured evidence" in refusals[0].message
    assert "route_not_deliver:unrouted" in _codes(refusals)


def test_refusal_controls_unmeasured_failed_escapes_thin() -> None:
    rows = _rows(16, 16)
    key = {"capability_class": "frontend.component.add", "size": "S"}
    # none evaluated (the CLI / a unit test) and the honest sentinel both read as unmeasured
    for controls in (None, ControlsVerdict.unmeasured()):
        cell = _cell(rows, controls=controls, **key)
        codes = _codes(so.evaluate_signoff(_signoff(), cell, controls=controls, repo="todo"))
        assert "controls_unmeasured" in codes, codes
    failed = ControlsVerdict(passed=False, constructible=7, total=7, escapes=0, run_id="ctlfail1")
    cell = _cell(rows, controls=failed, **key)
    refusals = so.evaluate_signoff(_signoff(), cell, controls=failed, repo="todo")
    assert _codes(refusals) == ["controls_failed", "route_not_deliver:controls_failed"]
    assert refusals[0].observed == "failed" and "ctlfail1" in refusals[0].message
    escaped = ControlsVerdict(passed=True, constructible=7, total=7, escapes=1, run_id="ctlesc01")
    cell = _cell(rows, controls=escaped, **key)
    refusals = so.evaluate_signoff(_signoff(), cell, controls=escaped, repo="todo")
    assert _codes(refusals) == ["controls_escapes", "route_not_deliver:controls_escapes"]
    assert refusals[0].threshold == 0 and refusals[0].observed == 1
    assert cell.route == ROUTE_HUMAN
    thin = ControlsVerdict(passed=True, constructible=3, total=7, escapes=0, run_id="ctlthin1")
    cell = _cell(rows, controls=thin, **key)
    refusals = so.evaluate_signoff(_signoff(), cell, controls=thin, repo="todo")
    assert _codes(refusals) == ["controls_thin", "route_not_deliver:controls_thin"]
    assert refusals[0].threshold == 0.5 and refusals[0].observed == pytest.approx(0.4286, abs=1e-4)
    # a deployment may allow one escape / a thinner gate — the route clause is then the bar
    relaxed = so.SignoffPolicy(max_controls_escapes=1, min_constructible_share=0.4)
    assert _codes(
        so.evaluate_signoff(
            _signoff(),
            _cell(rows, controls=escaped, **key),
            controls=escaped,
            policy=relaxed,
            repo="todo",
        )
    ) == ["route_not_deliver:controls_escapes"]
    # … or switch the controls clauses off entirely (the routing rule still refuses)
    off = so.SignoffPolicy(require_controls_passed=False)
    assert _codes(
        so.evaluate_signoff(
            _signoff(),
            _cell(rows, controls=failed, **key),
            controls=failed,
            policy=off,
            repo="todo",
        )
    ) == ["route_not_deliver:controls_failed"]


def test_refusal_oracle_weak_uses_the_measured_strength() -> None:
    rows = _rows(16, 16, oracle_strength=0.5)
    cell = _cell(rows, controls=PASSED, capability_class="frontend.component.add", size="S")
    refusals = so.evaluate_signoff(_signoff(), cell, controls=PASSED, repo="todo")
    assert _codes(refusals) == ["oracle_weak", "route_not_deliver:oracle_weak"]
    assert refusals[0].threshold == 0.8 and refusals[0].observed == 0.5
    strong = _cell(
        _rows(16, 16, oracle_strength=0.9),
        controls=PASSED,
        capability_class="frontend.component.add",
        size="S",
    )
    assert so.evaluate_signoff(_signoff(), strong, controls=PASSED, repo="todo") == ()
    # the caller's measurement wins over the rows' own for the oracle clauses — and only
    # for them: the route stays the capability map's (routed on the rows), so the two can
    # never disagree about the route
    refusals = so.evaluate_signoff(
        _signoff(), cell, controls=PASSED, oracle_strength=0.95, repo="todo"
    )
    assert _codes(refusals) == ["route_not_deliver:oracle_weak"]
    refusals = so.evaluate_signoff(
        _signoff(), strong, controls=PASSED, oracle_strength=0.55, repo="todo"
    )
    assert _codes(refusals) == ["oracle_weak"] and refusals[0].observed == 0.55


def test_refusal_oracle_unmeasured_is_not_overridable() -> None:
    """signoff-policy.v2: a cell whose oracle was never scored is refused — under every
    policy a deployment can configure — until a task-level mutation score exists."""
    rows = _rows(16, 16, oracle_strength=None)
    key = {"capability_class": "frontend.component.add", "size": "S"}
    cell = _cell(rows, controls=PASSED, **key)
    assert cell.route == ROUTE_DELIVER  # the routing rule does not see an unmeasured oracle
    refusals = so.evaluate_signoff(_signoff(), cell, controls=PASSED, repo="todo")
    assert _codes(refusals) == ["oracle_unmeasured"]
    r = refusals[0]
    assert r.threshold == "measured" and r.observed is None and not r.overridable
    assert "mutation score" in r.message and "cannot be relaxed" in r.message
    assert r.to_dict() == {
        "code": "oracle_unmeasured",
        "message": r.message,
        "threshold": "measured",
        "observed": None,
        "overridable": False,
    }
    with pytest.raises(so.SignoffRefused, match="mutation score") as ei:
        so.check_signable(_signoff(), cell, controls=PASSED, repo="todo")
    assert ei.value.code == "oracle_unmeasured" and ei.value.observed is None
    # the most relaxed policy there is still refuses it
    relaxed = so.SignoffPolicy(
        n_min=1,
        max_controls_escapes=100,
        min_constructible_share=0.0,
        min_oracle_strength=0.0,
        require_route_deliver=False,
        require_controls_passed=False,
    )
    assert _codes(so.evaluate_signoff(_signoff(), cell, policy=relaxed, repo="todo")) == [
        "oracle_unmeasured"
    ]
    # … and no knob exists to drop the clause
    with pytest.raises(ValueError, match="require_oracle_measured cannot be relaxed"):
        so.SignoffPolicy.from_env({"CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED": "off"})
    # the caller's measurement (the server: the cell's tasks' latest mutation scores)
    # clears it — a strong one signs, a weak one is `oracle_weak`
    assert (
        so.evaluate_signoff(_signoff(), cell, controls=PASSED, oracle_strength=0.85, repo="todo")
        == ()
    )
    weak = so.evaluate_signoff(_signoff(), cell, controls=PASSED, oracle_strength=0.5, repo="todo")
    assert _codes(weak) == ["oracle_weak"] and weak[0].observed == 0.5
    # the resolver: caller > decision > rows, never 0.0 for "unmeasured"
    assert so.resolve_oracle_strength(cell) is None
    assert so.resolve_oracle_strength(cell, oracle_strength=0.85) == 0.85
    measured = _cell(_rows(16, 16, oracle_strength=0.7), controls=PASSED, **key)
    assert so.resolve_oracle_strength(measured) == pytest.approx(0.7)
    assert so.resolve_oracle_strength(measured, oracle_strength=0.85) == 0.85
    # evaluation order: the clause sits after the controls clauses, before the route
    thin = _cell(_rows(2, 2, oracle_strength=None), controls=None, **key)
    assert _codes(so.evaluate_signoff(_signoff(attested=False), thin, repo="todo")) == [
        "thin_cell",
        "controls_unmeasured",
        "oracle_unmeasured",
        "route_not_deliver:n_below_min",
        "attestation_missing",
    ]


def test_refusal_route_not_deliver_carries_the_reason_code() -> None:
    # 12 rows, 10 clean: point 0.83 < 0.90 → calibrate(point_below_bar); everything else holds
    cell = _cell(
        _rows(12, 10), controls=PASSED, capability_class="frontend.component.add", size="S"
    )
    refusals = so.evaluate_signoff(_signoff(), cell, controls=PASSED, repo="todo")
    assert _codes(refusals) == ["route_not_deliver:point_below_bar"]
    r = refusals[0]
    assert r.threshold == "deliver" and r.observed == "calibrate" and "point" in r.message
    assert so.refusal_family(r.code) == "route_not_deliver" and r.overridable
    # XL is split before it is attempted — never signable under the default policy
    xl = _cell(
        _rows(16, 16, size="XL"),
        controls=PASSED,
        capability_class="frontend.component.add",
        size="XL",
    )
    assert _codes(so.evaluate_signoff(_signoff(size="XL"), xl, controls=PASSED, repo="todo")) == [
        "route_not_deliver:granularize"
    ]


def test_refusal_attestation_missing_is_last_and_not_overridable() -> None:
    cell = _signable_cell()
    refusals = so.evaluate_signoff(_signoff(attested=False), cell, controls=PASSED, repo="todo")
    assert _codes(refusals) == ["attestation_missing"] and not refusals[0].overridable
    with pytest.raises(so.SignoffRefused, match="must name one accepted") as ei:
        so.check_signable(_signoff(attested=False), cell, controls=PASSED, repo="todo")
    assert ei.value.code == "attestation_missing"
    # there is no policy that drops the clause (construction refuses it)
    with pytest.raises(ValueError):
        so.SignoffPolicy(require_attestation=False)


def test_check_signable_raises_the_first_clause_with_all_attached() -> None:
    cell = _cell(_rows(2, 2), controls=None, capability_class="frontend.component.add", size="S")
    with pytest.raises(so.SignoffRefused) as ei:
        so.check_signable(_signoff(attested=False), cell, repo="todo")
    assert ei.value.code == "thin_cell" and ei.value.observed == 2 and ei.value.threshold == 10
    assert [r.code for r in ei.value.refusals] == [
        "thin_cell",
        "controls_unmeasured",
        "route_not_deliver:n_below_min",
        "attestation_missing",
    ]
    assert all(isinstance(r.to_dict()["overridable"], bool) for r in ei.value.refusals)


def test_revocation_never_fails_the_policy() -> None:
    cell = _cell(_rows(2, 2), capability_class="frontend.component.add", size="S")
    assert so.evaluate_signoff(_signoff(revoked=True, attested=False), cell, repo="todo") == ()


def test_refusal_code_vocabulary_is_closed() -> None:
    with pytest.raises(ValueError, match="refusal code"):
        so.SignoffRefusal("made_up", "x")
    assert so.SignoffRefusal("route_not_deliver:ci_low_below_bar", "x").overridable
    assert not so.SignoffRefusal("oracle_unmeasured", "x").overridable
    assert so.NON_OVERRIDABLE_REFUSALS == ("false_q1", "oracle_unmeasured", "attestation_missing")


# ---------------------------------------------------------------------------
# stamp_evidence: the snapshot the record carries
# ---------------------------------------------------------------------------


def test_stamp_evidence_records_the_whole_decision() -> None:
    cell = _signable_cell()
    rec = so.stamp_evidence(_signoff(), cell, controls=PASSED)
    assert rec.n_at_signoff == 16 and rec.point_at_signoff == 1.0
    assert rec.ci_low_at_signoff == pytest.approx(0.806, abs=1e-3)
    assert rec.false_q1_at_signoff == 0 and rec.apparatus_version == APPARATUS_VERSION
    assert rec.oracle_strength_at_signoff == pytest.approx(ORACLE)  # the rows' own
    assert rec.policy_version == "signoff-policy.v2"
    assert rec.policy_thresholds == so.DEFAULT_SIGNOFF_POLICY.thresholds()
    assert rec.policy_thresholds["require_oracle_measured"] is True
    # the caller's measurement is what gets stamped when given; unmeasured stays None
    assert (
        so.stamp_evidence(_signoff(), cell, oracle_strength=0.85).oracle_strength_at_signoff == 0.85
    )
    unmeasured = _cell(
        _rows(16, 16, oracle_strength=None),
        controls=PASSED,
        capability_class="frontend.component.add",
        size="S",
    )
    assert so.stamp_evidence(_signoff(), unmeasured).oracle_strength_at_signoff is None
    assert rec.route_at_signoff == "deliver" and rec.route_reason_code == "deliver"
    assert (rec.controls_verdict, rec.controls_run_id) == ("passed", "ctl00001")
    assert (rec.controls_k, rec.controls_total, rec.controls_escapes) == (5, 7, 0)
    assert rec.attestation == _attestation()  # the approver's, untouched
    # the controls verdict defaults to the decision's when the caller passes none
    assert so.stamp_evidence(_signoff(), cell).controls_run_id == "ctl00001"
    # a relaxed policy is stamped as the bar that was in force
    relaxed = so.SignoffPolicy(n_min=5)
    assert so.stamp_evidence(_signoff(), cell, policy=relaxed).policy_thresholds["n_min"] == 5


# ---------------------------------------------------------------------------
# ledger: append / load / chain / revoke (upstream cases)
# ---------------------------------------------------------------------------


def test_append_load_roundtrip(tmp_path: Path) -> None:
    rows = _rows(16, 16)
    cell = _cell(rows, controls=PASSED, capability_class="frontend.component.add", size="S")
    p = tmp_path / "signoff.jsonl"
    led = so.JsonlSignoffLedger(p)
    a = led.append(_signoff(repo="todo"), cell, repo="todo", controls=PASSED)
    b = led.append(_signoff(repo="cart"), cell, repo="cart", controls=PASSED)
    loaded = list(led.records())
    assert [r.repo for r in loaded] == ["todo", "cart"]
    assert loaded[0].verifier == "alice@x.com"
    # evidence snapshot stamped from the live cell
    assert a.n_at_signoff == 16 and a.point_at_signoff == 1.0 and a.false_q1_at_signoff == 0
    assert a.apparatus_version == APPARATUS_VERSION  # stamped from the instrument, never a literal
    assert a.policy_version == "signoff-policy.v2" and a.controls_verdict == "passed"
    assert a.oracle_strength_at_signoff == pytest.approx(ORACLE)
    assert loaded[0].attestation == _attestation()
    # chained
    assert a.prev_hash == "0" * 64 and b.prev_hash == a.row_hash
    assert led.verify() == 2


def test_chain_detects_tamper(tmp_path: Path) -> None:
    rows = _rows(16, 16)
    cell = _cell(rows, controls=PASSED, capability_class="frontend.component.add", size="S")
    p = tmp_path / "signoff.jsonl"
    led = so.JsonlSignoffLedger(p)
    led.append(_signoff(), cell, repo="todo", controls=PASSED)
    led.append(_signoff(verifier="bob@x.com"), cell, repo="todo", controls=PASSED)
    lines = p.read_text().splitlines()
    d = json.loads(lines[0])
    d["verifier"] = "mallory@x.com"
    lines[0] = json.dumps(d, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(LedgerIntegrityError, match="row_hash mismatch"):
        led.verify()
    # editing the attestation is a tamper too
    d = json.loads(lines[1])
    d["attestation"]["reviewed_row_hash"] = "d" * 64
    p.write_text(lines[0].replace("mallory@x.com", "alice@x.com") + "\n" + json.dumps(d) + "\n")
    with pytest.raises(LedgerIntegrityError, match="sign-off 2"):
        led.verify()
    # removing a record breaks the chain too
    p.write_text(lines[1] + "\n")
    with pytest.raises(LedgerIntegrityError, match="prev_hash mismatch"):
        led.verify()


def test_active_signoffs_latest_wins_and_revoke_drops(tmp_path: Path) -> None:
    rows = _rows(16, 16)
    cell = _cell(rows, controls=PASSED, capability_class="frontend.component.add", size="S")
    led = so.JsonlSignoffLedger(tmp_path / "signoff.jsonl")
    led.append(_signoff(verifier="alice@x.com"), cell, repo="todo", controls=PASSED)
    led.append(_signoff(verifier="bob@x.com"), cell, repo="todo", controls=PASSED)
    active = so.active_signoffs(led.records())
    key = _signoff().key()
    assert active[key].verifier == "bob@x.com"
    led.append(_signoff(verifier="bob@x.com", revoked=True, attested=False))  # needs no cell
    assert key not in so.active_signoffs(led.records())
    assert led.verify() == 3


# ---------------------------------------------------------------------------
# write boundary: refusals (→ 409)
# ---------------------------------------------------------------------------


def test_write_refuses_false_q1_cell(tmp_path: Path) -> None:
    bad = _row()
    object.__setattr__(bad, "target_green", False)  # a false-Q1 row that bypassed write
    cell = _cell(
        [*_rows(16, 16), bad],
        controls=PASSED,
        capability_class="frontend.component.add",
        size="S",
    )
    assert cell.false_q1 == 1
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    with pytest.raises(so.SignoffRefused, match="false_q1=1"):
        led.append(_signoff(), cell, repo="todo", controls=PASSED)
    assert not (tmp_path / "s.jsonl").exists()  # nothing written


def test_write_refuses_unmeasured_cell_and_missing_cell(tmp_path: Path) -> None:
    empty = _cell([], capability_class="frontend.component.add", size="S")
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    with pytest.raises(so.SignoffRefused, match="no measured evidence") as ei:
        led.append(_signoff(), empty, repo="todo", controls=PASSED)
    assert ei.value.code == "thin_cell"
    with pytest.raises(so.SignoffRefused, match="needs the live cell"):
        led.append(_signoff())


def test_write_refuses_thin_cell_unmeasured_controls_and_no_attestation(tmp_path: Path) -> None:
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    thin = _cell(_rows(3, 3), controls=PASSED, capability_class="frontend.component.add", size="S")
    with pytest.raises(so.SignoffRefused, match="n=3 < n_min=10") as ei:
        led.append(_signoff(), thin, repo="todo", controls=PASSED)
    assert ei.value.code == "thin_cell"
    # a cell routed without a verdict, and none handed in → the policy reads "unmeasured"
    unrouted = _cell(_rows(16, 16), capability_class="frontend.component.add", size="S")
    with pytest.raises(so.SignoffRefused, match="never run") as ei:
        led.append(_signoff(), unrouted, repo="todo")
    assert ei.value.code == "controls_unmeasured"
    ok = _signable_cell()
    with pytest.raises(so.SignoffRefused, match="must name one accepted") as ei:
        led.append(_signoff(attested=False), ok, repo="todo", controls=PASSED)
    assert ei.value.code == "attestation_missing"
    # an unmeasured oracle is refused at the write boundary too; the caller's
    # measurement is what lets it through, and it is what the record carries
    unscored = _cell(
        _rows(16, 16, oracle_strength=None),
        controls=PASSED,
        capability_class="frontend.component.add",
        size="S",
    )
    with pytest.raises(so.SignoffRefused, match="mutation score") as ei:
        led.append(_signoff(), unscored, repo="todo", controls=PASSED)
    assert ei.value.code == "oracle_unmeasured"
    assert not (tmp_path / "s.jsonl").exists()  # nothing written by any refusal
    rec = led.append(_signoff(), unscored, repo="todo", controls=PASSED, oracle_strength=0.88)
    assert rec.oracle_strength_at_signoff == 0.88 and rec.policy_version == "signoff-policy.v2"
    assert led.verify() == 1


def test_write_refuses_scope_mismatch(tmp_path: Path) -> None:
    cell = _cell(
        _rows(12, 12), controls=PASSED, capability_class="frontend.component.add", size="S"
    )
    led = so.JsonlSignoffLedger(tmp_path / "s.jsonl")
    with pytest.raises(so.SignoffRefused, match="does not cover") as ei:
        led.append(_signoff("bug.fix"), cell, repo="todo", controls=PASSED)
    assert ei.value.code == "scope_mismatch"
    with pytest.raises(so.SignoffRefused, match="does not cover"):
        led.append(_signoff(repo="todo"), cell, repo="cart", controls=PASSED)  # another repo
    # a language-scoped record does not cover a class-wide (language="*") cell
    with pytest.raises(so.SignoffRefused, match="does not cover"):
        led.append(_signoff(language="python"), cell, repo="todo", controls=PASSED)


# ---------------------------------------------------------------------------
# read overlay
# ---------------------------------------------------------------------------


def test_apply_signoffs_elevates_matching_cell_only() -> None:
    rows = _rows(12, 12, repo="todo") + _rows(12, 12, cls="bug.fix", repo="cart")
    m = cap.build_capability_map(rows)
    out = so.apply_signoffs_to_map(m, [_signoff()], repo="todo")
    assert (
        out.get(capability_class="frontend.component.add", size="S").verification_tier
        == "human-verified"
    )
    assert out.get(capability_class="frontend.component.add", size="S").earned
    assert out.get(capability_class="bug.fix", size="S").verification_tier == "automated-pass"
    # the original map is untouched (new cells)
    assert (
        m.get(capability_class="frontend.component.add", size="S").verification_tier
        == "automated-pass"
    )


def test_invariant_false_q1_can_never_be_signed_off_at_read() -> None:
    # An attestation exists (say, written before the dirty row appeared). New evidence
    # with false-Q1 arrives → the overlay refuses to lift; the gate self-heals.
    bad = _row()
    object.__setattr__(bad, "target_green", False)
    m = cap.build_capability_map([*_rows(12, 12), bad])
    out = so.apply_signoffs(m.cells, [_signoff()], repo="todo")
    assert out[0].verification_tier == cap.TIER_UNTRUSTED


def test_signoff_made_on_an_earlier_apparatus_is_stale_and_lifts_nothing() -> None:
    """Evidence expires when the apparatus changes (EVIDENCE §4): a sign-off stamped at
    an earlier apparatus is kept on the record but lifts nothing at read; one that
    covers every version the cell is read at still does."""
    m = cap.build_capability_map(_rows(12, 12))
    cell = m.cells[0]
    assert cell.stats is not None and cell.stats.apparatus_versions
    current = ",".join(cell.stats.apparatus_versions)
    old = replace(_signoff(), apparatus_version="1.9")
    assert old.is_stale(cell) and not old.covers_apparatus(cell)
    out = so.apply_signoffs(m.cells, [old], repo="todo")
    assert out[0].verification_tier == "automated-pass"
    fresh = replace(_signoff(), apparatus_version=current)
    assert fresh.covers_apparatus(cell)
    assert so.apply_signoffs(m.cells, [fresh], repo="todo")[0].verification_tier == "human-verified"
    # a v1 record with no stamp is not judged stale here
    unstamped = replace(_signoff(), apparatus_version="")
    assert unstamped.covers_apparatus(cell)


def test_revoked_signoff_does_not_elevate() -> None:
    m = cap.build_capability_map(_rows(12, 12))
    out = so.apply_signoffs(m.cells, [_signoff(), _signoff(revoked=True)], repo="todo")
    assert out[0].verification_tier == "automated-pass"


def test_unscoped_read_applies_only_repo_agnostic_records() -> None:
    m = cap.build_capability_map(_rows(12, 12))
    # attested for "todo" only → an unscoped read must not borrow it
    assert (
        so.apply_signoffs(m.cells, [_signoff(repo="todo")])[0].verification_tier == "automated-pass"
    )
    # a "*" attestation applies everywhere
    assert so.apply_signoffs(m.cells, [_signoff(repo="*")], repo="anything")[0].earned


def test_highest_matching_tier_wins_and_never_downgrades() -> None:
    m = cap.build_capability_map(_rows(12, 12))
    recs = [_signoff(verifier="a"), _signoff(verifier="b", tier=cap.TIER_AB_CONFIRMED, size="S")]
    out = so.apply_signoffs(m.cells, recs, repo="todo")
    assert out[0].verification_tier == cap.TIER_AB_CONFIRMED
    # applying a lower tier on top does not downgrade
    out2 = so.apply_signoffs(out, [_signoff(verifier="c")], repo="todo")
    assert out2[0].verification_tier == cap.TIER_AB_CONFIRMED


def test_class_wide_attestation_covers_every_size_but_not_vice_versa() -> None:
    rows = _rows(12, 12, size="S") + _rows(12, 12, size="M")
    m = cap.build_capability_map(rows)
    out = so.apply_signoffs_to_map(m, [_signoff(size="*")], repo="todo")
    assert all(c.earned for c in out.cells)
    out2 = so.apply_signoffs_to_map(m, [_signoff(size="S")], repo="todo")
    assert out2.get(capability_class="frontend.component.add", size="S").earned
    assert not out2.get(capability_class="frontend.component.add", size="M").earned
    # a size-scoped attestation never lifts the class-level aggregate
    cm = cap.build_capability_map(rows, projection=cap.PROJECTION_CLASS)
    assert not so.apply_signoffs(cm.cells, [_signoff(size="S")], repo="todo")[0].earned


def test_signoff_does_not_change_the_route() -> None:
    m = cap.build_capability_map(_rows(5, 5))  # calibrate: n<10
    out = so.apply_signoffs(m.cells, [_signoff()], repo="todo")
    assert out[0].earned and out[0].route != ROUTE_DELIVER  # trust ≠ evidence


def test_load_and_apply_is_noop_without_ledger(tmp_path: Path) -> None:
    led = so.JsonlSignoffLedger(tmp_path / "missing.jsonl")
    assert list(led.records()) == [] and led.verify() == 0
    m = cap.build_capability_map(_rows(12, 12))
    assert so.apply_signoffs_to_map(m, led.records(), repo="todo") == m
