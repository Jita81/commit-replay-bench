"""``/signoffs`` under ``signoff-policy.v2`` — a sign-off is a policy decision, refused at write.

The seed's deliver cell (``bug.fix|S``, n = 40, point 0.95, Wilson lower 0.835) sits under a
controls report with ONE escape, so it is REFUSED (409 ``signoff_refused`` /
``controls_escapes``) until a clean controls run lands (``pass_controls``); its oracle is
MEASURED from the seed's ``oracle.score`` events at 0.58 over 3 of its 4 tasks, so it is
still ``oracle_weak`` until strong scores land (``score_oracle``); then it signs — with an
attestation naming an accepted row — and the record carries the whole snapshot. A cell
whose tasks were never scored is ``oracle_unmeasured``: refused under every deployment
knob (the v2 clause). Also: the false-Q1 floor (first, non-overridable, its historical
envelope code), the preview, attestation validation (422), the policy endpoint and the
deployment knobs, revoke, the chain, and records signed under v1 served as such.

Navigation
----------
What it is:   ``/signoffs``'s test suite under ``signoff-policy.v2`` — a sign-off is a policy
              decision, refused at write.
What it does: Pins that the seed's deliver cell is refused on its controls escape (409
              ``signoff_refused`` / ``controls_escapes``), signs (201) once the controls gate is
              clean AND the oracle is strong, is ``oracle_weak`` at the seed's measured 0.58 and
              ``oracle_unmeasured`` (not overridable) when never scored; full-cell scope and a
              second attestation chaining; every clause listed with observed vs threshold on a
              thin cell; attestation missing not overridable; the false-Q1 floor first and its
              historical envelope code; the read-time check invalidating a signed cell; 422
              bodies and the accepted-row rule; redaction; the policy endpoint, relaxed
              thresholds applied and stamped, the non-relaxable clauses; the preview as a viewer
              read; list, legacy and v1 records served honestly, revoke RBAC / append-and-hide /
              re-attest, and chain tamper detection including the attestation.
How:          ``make_env`` over the seed; ``pass_controls`` / ``score_oracle`` / ``attested_body``
              from the sign-off seed to clear each clause the honest way; a false-Q1 row inserted
              with the ORM on purpose.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/routes/signoffs.py (under test), src/crb/core/signoff.py (the
              policy), tests/fixtures/signoff_seed.py (the clause-clearing helpers),
              tests/fixtures/server_seed.py, src/crb/server/schemas_signoff.py (the shapes),
              docs/EVIDENCE-AND-CLAIMS.md (what a signed cell may be claimed to mean, §6a),
              docs/API.md
Tested by:    tests/test_server_routes_signoffs.py
Touch when:   the policy gains a clause (a 409 case naming its code, a helper that clears it,
              the preview case and ui/src/api/types.ts); never to make a clause overridable
              without the decision log.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from crb.core.ledger import BELT_SET_V5, GENESIS_HASH, LedgerIntegrityError
from crb.core.version import APPARATUS_VERSION
from crb.server.routes.runs import system_trace_id
from crb.server.routes.signoffs import signoff_hash, verify_signoff_rows
from crb.store.models import Event, Grade, Signoff
from fixtures.server_seed import (
    ALPHA,
    BETA,
    THIN_CELL,
    Env,
    assert_rbac,
    envelope,
    login,
    make_env,
)
from fixtures.signoff_seed import (
    CLEAN_CONTROLS_RUN,
    STATEMENT,
    STRONG_ORACLE,
    accepted_row,
    attestation_for,
    attested_body,
    clear_policy,
    pass_controls,
    score_oracle,
)

DELIVER = {"capability_class": "bug.fix", "size": "S"}
THIN = {"capability_class": THIN_CELL["capability_class"], "size": THIN_CELL["size"]}
OUT_KEYS = {
    "id",
    "repo",
    "cell",
    "tier",
    "note",
    "approver",
    "approver_name",
    "stale",
    "apparatus_current",
    "created",
    "revoked",
    "revoked_by",
    "revoked_by_name",
    "revoked_at",
    "active",
    "current_false_q1",
    "evidence",
    "prev_hash",
    "row_hash",
    "schema",
    "policy_version",
    "policy_thresholds",
    "route",
    "controls",
    "attestation",
}
DEFAULT_THRESHOLDS = {
    "n_min": 10,
    "require_route_deliver": True,
    "require_controls_passed": True,
    "max_controls_escapes": 0,
    "min_constructible_share": 0.5,
    "min_oracle_strength": 0.8,
    "require_oracle_measured": True,
    "require_attestation": True,
}
#: The seed's measured oracle on the deliver cell: (0.9 + 0.5 + 0.3333) / 3 over 3 of 4 tasks.
SEED_ORACLE = 0.5778


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as APPROVER (the role that signs), torn down after
    the test."""
    with make_env(tmp_path, role="approver") as e:
        yield e


def _seed_false_q1_row(env: Env, *, cls: str = "docs.update", size: str = "S") -> str:
    """Insert a clean row with a failed belt STRAIGHT through the ORM — deliberately
    bypassing DbLedger's write-time invariant — into its own cell."""
    with env.factory() as s:
        s.add(
            Grade(
                row_id="bad-row",
                schema="crb.grade.v2",
                repo=ALPHA,
                task_id="deadbeef" * 5,
                created="2026-09-01T00:00:00+00:00",
                clean=True,
                tests_unmodified=True,
                target_green=False,
                no_new_failures=True,
                source_changed=True,
                capability_class=cls,
                size=size,
                language="python",
                builder="editblock",
                model="gpt-oss-120b",
                provider="cerebras",
                evidence_pack_hash="p" * 64,
                apparatus_version="2.0",
                belt_set="v4",
                prev_hash="x" * 64,
                row_hash="y" * 64,
            )
        )
        s.commit()
    return "bad-row"


def _signoffs(env: Env) -> list[Signoff]:
    with env.factory() as s:
        return list(s.execute(select(Signoff).order_by(Signoff.seq)).scalars())


def _events(env: Env, action: str) -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(
                select(Event)
                .where(Event.trace_id == system_trace_id("signoffs", ALPHA), Event.action == action)
                .order_by(Event.id)
            ).scalars()
        )


def _codes(refusals: list[dict[str, Any]]) -> list[str]:
    return [r["code"] for r in refusals]


def _subject(env: Env, task_id: str) -> str:
    return next(t.subject for t in env.info.tasks if t.task_id == task_id)


def _preview(env: Env, cell: dict[str, str], **extra: str) -> Any:
    q = "&".join(f"{k}={v}" for k, v in {"repo": ALPHA, **cell, **extra}.items())
    return env.get(f"/signoffs/preview?{q}")


# ---------------------------------------------------------------------------
# POST — the policy decision
# ---------------------------------------------------------------------------


class TestCreate:
    def test_rbac_is_approver(self, env: Env) -> None:
        assert_rbac(
            env, "POST", "/signoffs", min_role="approver", json={"repo": ALPHA, "cell": DELIVER}
        )

    def test_seeded_deliver_cell_is_refused_on_the_controls_escape(self, env: Env) -> None:
        """The seed's controls report has one escape: the cell routes ``human`` and the
        policy refuses it — with every failing clause, observed vs threshold, and the
        refusal on the record. Nothing is written."""
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 409, r.text
        e = envelope(r)
        assert e["code"] == "signoff_refused"
        d = e["detail"]
        assert d["code"] == "controls_escapes" and d["threshold"] == 0 and d["observed_value"] == 1
        assert "1 measurement control(s) graded clean" in e["message"]
        assert "max_controls_escapes=0" in e["message"]
        assert d["policy_version"] == "signoff-policy.v2" and d["thresholds"] == DEFAULT_THRESHOLDS
        # the map routes the cell under the seed's task-level oracle (0.58): the routing
        # rule's first refusal is the weak oracle, before the controls escape
        assert _codes(d["refusals"]) == [
            "controls_escapes",
            "oracle_weak",
            "route_not_deliver:oracle_weak",
        ]
        obs = d["observed"]
        assert obs["n"] == 40 and obs["point"] == 0.95 and obs["false_q1"] == 0
        # the oracle as the seed's task-level scores measure it: 3 of the cell's 4 tasks
        assert obs["oracle_strength"] == SEED_ORACLE
        assert obs["oracle"] == {"strength": SEED_ORACLE, "scored": 3, "tasks": 4}
        assert obs["route"] == "human" and obs["reason_code"] == "oracle_weak"
        assert obs["controls"] == {
            "verdict": "escaped",
            "run_id": "0" * 32,
            "k": 12,
            "total": 14,
            "escapes": 1,
        }
        assert d["cell"]["capability_class"] == "bug.fix" and d["repo"] == ALPHA
        assert _signoffs(env) == []
        (ev,) = _events(env, "signoff.refused")
        assert ev.status == "invalid" and ev.payload_json["code"] == "controls_escapes"
        assert ev.payload_json["envelope_code"] == "signoff_refused"

    def test_201_once_the_controls_gate_is_clean_and_the_oracle_is_strong(self, env: Env) -> None:
        clear_policy(env)
        row = accepted_row(env, DELIVER)
        r = env.post("/signoffs", json=attested_body(env, DELIVER, note="reviewed 40 packs"))
        assert r.status_code == 201, r.text
        d = r.json()
        assert set(d) == OUT_KEYS
        assert (
            d["repo"] == ALPHA
            and d["tier"] == "human-verified"
            and d["note"] == "reviewed 40 packs"
        )
        assert d["cell"] == {
            "process_step": "*",
            "capability_class": "bug.fix",
            "size": "S",
            "language": "*",
            "builder": "*",
            "model": "*",
            "provider": "*",
        }
        assert d["revoked"] is False and d["active"] is True and d["current_false_q1"] == 0
        # the ledger keeps the approver's id; the reader gets the name resolved at read
        assert d["approver"] != "appr1" and d["approver_name"] == "appr1"
        assert d["revoked_by_name"] is None
        # the evidence snapshot: n, point, the interval, false-Q1, oracle, apparatus
        ev = d["evidence"]
        assert ev["n"] == 40 and ev["point"] == 0.95
        assert ev["ci_low"] == pytest.approx(0.835, abs=0.001)
        assert ev["false_q1"] == 0 and ev["apparatus_versions"] == [APPARATUS_VERSION]
        # the rows carry no strength; the stamped one is the task-level measurement
        assert ev["oracle_strength"] == pytest.approx(STRONG_ORACLE)
        # the policy decision
        assert d["schema"] == "crb.signoff.v2"
        assert d["policy_version"] == "signoff-policy.v2"
        assert d["policy_thresholds"] == DEFAULT_THRESHOLDS
        assert d["route"]["route"] == "deliver" and d["route"]["reason_code"] == "deliver"
        assert "n=40" in d["route"]["reason"]
        assert d["controls"] == {
            "verdict": "passed",
            "run_id": CLEAN_CONTROLS_RUN,
            "k": 12,
            "total": 14,
            "escapes": 0,
            "created": d["controls"]["created"],
        }
        assert d["controls"]["created"]
        # the attestation, resolved to the task the row graded
        att = d["attestation"]
        assert att["reviewed_row_hash"] == row.row_hash
        assert att["reviewed_task_id"] == row.task_id
        assert att["subject"] == _subject(env, row.task_id)
        assert att["statement"] == STATEMENT and att["at"]
        assert d["prev_hash"] == GENESIS_HASH and len(d["row_hash"]) == 64
        assert d["approver"]  # the approver's principal id
        # persisted, chained, the WHOLE snapshot covered by the hash
        rows = _signoffs(env)
        assert len(rows) == 1 and rows[0].row_hash == signoff_hash(rows[0])
        cj = rows[0].cell_json
        assert rows[0].evidence_rows == 40 and cj["evidence_n"] == "40"
        assert cj["policy_version"] == "signoff-policy.v2"
        assert cj["evidence_oracle_strength"] == f"{STRONG_ORACLE:.6f}"
        assert '"require_oracle_measured": true' in cj["policy_thresholds"]
        assert cj["route_reason_code"] == "deliver" and cj["controls_verdict"] == "passed"
        assert cj["controls_run_id"] == CLEAN_CONTROLS_RUN and cj["controls_escapes"] == "0"
        assert cj["attestation_reviewed_row_hash"] == row.row_hash
        assert verify_signoff_rows(rows) == 1
        # ... and recorded as a system event on the repo's sign-off trace
        (created,) = _events(env, "signoff.created")
        assert created.payload_json["n"] == 40
        assert created.payload_json["controls_verdict"] == "passed"
        assert created.payload_json["oracle_strength"] == pytest.approx(STRONG_ORACLE)
        assert (created.payload_json["oracle_scored"], created.payload_json["oracle_tasks"]) == (
            4,
            4,
        )
        assert created.payload_json["reviewed_row_hash"] == row.row_hash
        # served back by id
        got = env.get(f"/signoffs/{d['id']}")
        assert got.status_code == 200 and got.json() == d

    def test_409_oracle_weak_is_the_seed_s_measurement(self, env: Env) -> None:
        """With the controls gate clean the seed's cell is still refused: its oracle IS
        measured — 0.58 over 3 of 4 tasks — and below the bar. A deployment may lower
        the numeric bar (the clause is overridable); the route — the capability map's,
        routed under the same task-level strength — refuses independently."""
        pass_controls(env)
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 409, r.text
        d = envelope(r)["detail"]
        assert d["code"] == "oracle_weak" and d["threshold"] == 0.8
        assert d["observed_value"] == SEED_ORACLE
        assert _codes(d["refusals"]) == ["oracle_weak", "route_not_deliver:oracle_weak"]
        assert d["refusals"][0]["overridable"] is True
        assert d["observed"]["oracle"] == {"strength": SEED_ORACLE, "scored": 3, "tasks": 4}
        assert d["observed"]["route"] == "human"  # the map's route, under the same oracle
        assert _signoffs(env) == []

    def test_409_oracle_unmeasured_is_not_overridable(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """signoff-policy.v2: a cell none of whose tasks carries a mutation score cannot be
        signed — under any ``CRB_SIGNOFF__*`` setting; there is no knob, and trying to set
        one is a misconfiguration (503), not a lower bar. A later oracle run clears it."""
        pass_controls(env)
        # the latest score per task wins: unscoreable scores on every task of the cell
        # make the cell read as unmeasured (0 of 4)
        score_oracle(env, strength=None, run_id="8" * 32)
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 409, r.text
        e = envelope(r)
        assert e["code"] == "signoff_refused"
        d = e["detail"]
        assert d["code"] == "oracle_unmeasured"
        assert d["threshold"] == "measured" and d["observed_value"] is None
        assert "mutation score" in e["message"] and "cannot be relaxed" in e["message"]
        assert _codes(d["refusals"]) == ["oracle_unmeasured"]
        assert d["refusals"][0]["overridable"] is False
        assert d["observed"]["oracle_strength"] is None
        assert d["observed"]["oracle"] == {"strength": None, "scored": 0, "tasks": 4}
        assert d["observed"]["route"] == "deliver"
        (ev,) = _events(env, "signoff.refused")
        assert ev.payload_json["code"] == "oracle_unmeasured"
        assert _signoffs(env) == []
        # the most relaxed numeric bar there is does not touch it …
        monkeypatch.setenv("CRB_SIGNOFF__MIN_ORACLE_STRENGTH", "0")
        monkeypatch.setenv("CRB_SIGNOFF__N_MIN", "1")
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_CONTROLS_PASSED", "false")
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ROUTE_DELIVER", "false")
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 409 and envelope(r)["detail"]["code"] == "oracle_unmeasured"
        # … and there is no switch: setting one is a misconfigured policy, fail closed
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED", "false")
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 503 and envelope(r)["code"] == "signoff_policy_invalid"
        assert "require_oracle_measured cannot be relaxed" in envelope(r)["message"]
        assert env.get("/signoffs/policy").status_code == 503
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED", "true")  # the only value
        assert env.get("/signoffs/policy").status_code == 200
        # a newer oracle run that scores the cell's tasks measures it — and signs
        score_oracle(env, run_id="9" * 32)
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 201, r.text
        assert r.json()["evidence"]["oracle_strength"] == pytest.approx(STRONG_ORACLE)
        assert r.json()["policy_version"] == "signoff-policy.v2"

    def test_full_cell_scope_and_second_attestation_chains(self, env: Env) -> None:
        clear_policy(env)
        r1 = env.post("/signoffs", json=attested_body(env, DELIVER))
        r2 = env.post(
            "/signoffs",
            json=attested_body(env, env.info.deliver_cell, note="full cell", tier="ab-confirmed"),
        )
        assert r1.status_code == 201 and r2.status_code == 201, r2.text
        assert r2.json()["prev_hash"] == r1.json()["row_hash"]
        assert r2.json()["tier"] == "ab-confirmed" and r2.json()["cell"] == env.info.deliver_cell
        assert verify_signoff_rows(_signoffs(env)) == 2
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 2

    def test_409_thin_cell_lists_every_clause_with_observed_vs_threshold(self, env: Env) -> None:
        clear_policy(env)
        r = env.post("/signoffs", json=attested_body(env, THIN))
        assert r.status_code == 409, r.text
        e = envelope(r)
        assert e["code"] == "signoff_refused"
        d = e["detail"]
        assert d["code"] == "thin_cell" and d["threshold"] == 10 and d["observed_value"] == 4
        assert "n=4 < n_min=10" in e["message"]
        # the thin cell's tasks: one unscoreable seed score, one never scored → unmeasured
        assert _codes(d["refusals"]) == [
            "thin_cell",
            "oracle_unmeasured",
            "route_not_deliver:n_below_min",
        ]
        route = d["refusals"][2]
        assert route["threshold"] == "deliver" and route["observed"] == "calibrate"
        assert [r["overridable"] for r in d["refusals"]] == [True, False, True]
        assert d["observed"]["oracle"] == {"strength": None, "scored": 0, "tasks": 2}
        assert _signoffs(env) == []

    def test_409_attestation_missing_is_not_overridable(self, env: Env) -> None:
        clear_policy(env)
        r = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER, "note": "no row named"})
        assert r.status_code == 409, r.text
        d = envelope(r)["detail"]
        assert d["code"] == "attestation_missing"
        assert _codes(d["refusals"]) == ["attestation_missing"]
        assert d["refusals"][0]["overridable"] is False
        assert _signoffs(env) == []

    def test_409_controls_unmeasured_failed_and_thin(self, env: Env) -> None:
        # beta never ran controls: the cell is unmeasured AND the gate is unmeasured
        r = env.post("/signoffs", json={"repo": BETA, "cell": DELIVER})
        assert r.status_code == 409
        d = envelope(r)["detail"]
        assert d["code"] == "thin_cell" and d["observed_value"] == 0
        assert _codes(d["refusals"]) == [
            "thin_cell",
            "controls_unmeasured",
            "oracle_unmeasured",
            "route_not_deliver:unrouted",
            "attestation_missing",
        ]
        # a FAILED gate on alpha (the oracle scored strong, so only the gate is at issue)
        score_oracle(env)
        pass_controls(env, passed=False, run_id="6" * 32)
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        d = envelope(r)["detail"]
        assert r.status_code == 409 and d["code"] == "controls_failed"
        assert _codes(d["refusals"]) == ["controls_failed", "route_not_deliver:controls_failed"]
        assert d["observed"]["controls"]["verdict"] == "failed"
        # a thin gate: only 4 of 14 constructible
        pass_controls(env, not_constructible=10, run_id="7" * 32)
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        d = envelope(r)["detail"]
        assert r.status_code == 409 and d["code"] == "controls_thin"
        assert d["threshold"] == 0.5 and d["observed_value"] == pytest.approx(0.2857, abs=1e-4)
        assert _codes(d["refusals"]) == ["controls_thin", "route_not_deliver:controls_thin"]

    def test_409_false_q1_row_inserted_around_the_ledger_is_first(self, env: Env) -> None:
        clear_policy(env)
        bad = _seed_false_q1_row(env)
        r = env.post(
            "/signoffs",
            json={"repo": ALPHA, "cell": {"capability_class": "docs.update", "size": "S"}},
        )
        assert r.status_code == 409, r.text
        e = envelope(r)
        assert e["code"] == "false_q1_refused"  # the floor keeps its historical code
        d = e["detail"]
        assert d["code"] == "false_q1" and d["false_q1"] == 1 and d["rows"] == [bad]
        assert d["thresholds"] == {"false_q1": 0} and d["observed"] == {"false_q1": 1}
        assert _codes(d["refusals"]) == ["false_q1"] and d["refusals"][0]["overridable"] is False
        assert "false_q1=1" in e["message"]
        assert _signoffs(env) == []  # nothing written
        # the refusal is on the record
        (ev,) = _events(env, "signoff.refused")
        assert ev.status == "invalid" and ev.payload_json["rows"] == [bad]
        assert ev.payload_json["envelope_code"] == "false_q1_refused"
        # the unaffected deliver cell can still be signed (the check is scoped to the cell)
        assert env.post("/signoffs", json=attested_body(env, DELIVER)).status_code == 201

    def test_read_time_check_invalidates_a_signed_cell(self, env: Env) -> None:
        clear_policy(env)
        assert env.post("/signoffs", json=attested_body(env, DELIVER)).status_code == 201
        _seed_false_q1_row(env, cls="bug.fix", size="S")  # the same cell, after the fact
        item = env.get(f"/signoffs?repo={ALPHA}&include_revoked=true").json()["items"][0]
        assert item["revoked"] is False
        assert item["current_false_q1"] == 1 and item["active"] is False  # self-healed
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 1  # listed, flagged
        # and a new attestation on that cell is refused — by the floor, before anything else
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"
        assert envelope(r)["detail"]["false_q1"] == 1

    @pytest.mark.parametrize(
        "body",
        [
            {"repo": ALPHA, "cell": {"size": "S"}},  # no class
            {"repo": ALPHA, "cell": {"capability_class": "*"}},
            {"repo": ALPHA, "cell": {"capability_class": "bug.fix", "size": "XXL"}},
            {"repo": ALPHA, "cell": {"capability_class": "bug.fix", "colour": "red"}},
            {"repo": ALPHA, "cell": DELIVER, "tier": "automated-pass"},  # not an earned tier
            {"repo": ALPHA, "cell": DELIVER, "extra": 1},
            {"cell": DELIVER},
            {
                "repo": ALPHA,
                "cell": DELIVER,
                "attestation": {"reviewed_row_hash": "abc", "statement": "x"},
            },
            {
                "repo": ALPHA,
                "cell": DELIVER,
                "attestation": {"reviewed_row_hash": "g" * 64, "statement": "x"},
            },
            {
                "repo": ALPHA,
                "cell": DELIVER,
                "attestation": {"reviewed_row_hash": "a" * 64, "statement": "  "},
            },
            {"repo": ALPHA, "cell": DELIVER, "attestation": {"reviewed_row_hash": "a" * 64}},
            {
                "repo": ALPHA,
                "cell": DELIVER,
                "attestation": {"reviewed_row_hash": "a" * 64, "statement": "x", "at": "now"},
            },
        ],
    )
    def test_422(self, env: Env, body: dict[str, Any]) -> None:
        r = env.post("/signoffs", json=body)
        assert r.status_code == 422, r.text
        assert envelope(r)["code"] == "validation_error"

    def test_422_attestation_row_must_be_an_accepted_row_of_this_cell(self, env: Env) -> None:
        clear_policy(env)
        loc = ["body", "attestation", "reviewed_row_hash"]

        def post(hash_: str) -> Any:
            return env.post(
                "/signoffs",
                json={
                    "repo": ALPHA,
                    "cell": DELIVER,
                    "attestation": {"reviewed_row_hash": hash_, "statement": STATEMENT},
                },
            )

        # unknown row
        r = post("a" * 64)
        assert r.status_code == 422 and envelope(r)["detail"]["errors"][0]["loc"] == loc
        assert "no ledger row" in envelope(r)["message"]
        # a red row of the cell (T3's r1 attempt) — not accepted
        red = accepted_row(env, DELIVER, clean=False)
        r = post(red.row_hash)
        assert r.status_code == 422 and "not an accepted row" in envelope(r)["message"]
        # an accepted row of ANOTHER cell (the thin cell) — outside the attested scope
        other = accepted_row(env, THIN)
        r = post(other.row_hash)
        assert r.status_code == 422 and "outside the attested scope" in envelope(r)["message"]
        # a row of another repo: alpha's row named on beta
        r = env.post(
            "/signoffs",
            json={"repo": BETA, "cell": DELIVER, "attestation": attestation_for(env, DELIVER)},
        )
        assert r.status_code == 422 and "belongs to repo" in envelope(r)["message"]
        assert _signoffs(env) == []
        # a class-wide scope covers the S row (the scope check is key_matches, not equality)
        r = env.post(
            "/signoffs",
            json={**attested_body(env, DELIVER), "cell": {"capability_class": "bug.fix"}},
        )
        assert r.status_code == 201, r.text

    def test_unknown_repo_404(self, env: Env) -> None:
        assert env.post("/signoffs", json={"repo": "nope", "cell": DELIVER}).status_code == 404

    def test_note_and_statement_are_redacted(self, env: Env) -> None:
        clear_policy(env)
        secret = "sk-live-abcdefghijklmnopqrstuvwxyz0123"
        r = env.post(
            "/signoffs",
            json=attested_body(
                env, DELIVER, note=f"key {secret}", statement=f"read it; token {secret}"
            ),
        )
        assert r.status_code == 201, r.text
        assert (
            "sk-live" not in r.json()["note"]
            and "sk-live" not in r.json()["attestation"]["statement"]
        )
        assert "sk-live" not in str(_signoffs(env)[0].cell_json)


# ---------------------------------------------------------------------------
# The deployment's knobs
# ---------------------------------------------------------------------------


class TestPolicy:
    def test_policy_endpoint_reports_the_defaults(self, env: Env) -> None:
        login(env.client, "viewer")
        d = env.get("/signoffs/policy").json()
        assert d["policy_version"] == "signoff-policy.v2" and d["relaxed"] is False
        assert {k: d[k] for k in DEFAULT_THRESHOLDS} == DEFAULT_THRESHOLDS
        assert d["non_overridable"] == ["false_q1", "oracle_unmeasured", "attestation_missing"]
        assert d["bounds"]["n_min"] == [1, 10000]
        assert "require_oracle_measured" not in d["bounds"]  # a switch with no knob

    def test_relaxed_thresholds_are_applied_and_stamped(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deployment allowing one escape and a 0.5 oracle signs the seeded cell WITHOUT
        a clean re-run — and the record says which bar it cleared."""
        monkeypatch.setenv("CRB_SIGNOFF__MAX_CONTROLS_ESCAPES", "1")
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ROUTE_DELIVER", "false")  # the route is human
        monkeypatch.setenv("CRB_SIGNOFF__MIN_ORACLE_STRENGTH", "0.5")  # the seed's is 0.58
        assert env.get("/signoffs/policy").json()["relaxed"] is True
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["policy_thresholds"]["max_controls_escapes"] == 1
        assert d["policy_thresholds"]["require_route_deliver"] is False
        assert d["policy_thresholds"]["min_oracle_strength"] == 0.5
        assert d["policy_thresholds"]["require_oracle_measured"] is True  # never relaxable
        assert d["route"]["route"] == "human" and d["controls"]["verdict"] == "passed"
        assert d["controls"]["escapes"] == 1  # the count is still the truth
        assert d["evidence"]["oracle_strength"] == pytest.approx(SEED_ORACLE, abs=1e-4)

    def test_false_q1_oracle_measured_and_attestation_cannot_be_relaxed(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ATTESTATION", "false")
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 503 and envelope(r)["code"] == "signoff_policy_invalid"
        assert "require_attestation cannot be relaxed" in envelope(r)["message"]
        assert env.get("/signoffs/policy").status_code == 503
        monkeypatch.delenv("CRB_SIGNOFF__REQUIRE_ATTESTATION")
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED", "no")
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 503 and envelope(r)["code"] == "signoff_policy_invalid"
        assert "require_oracle_measured cannot be relaxed" in envelope(r)["message"]
        monkeypatch.delenv("CRB_SIGNOFF__REQUIRE_ORACLE_MEASURED")
        # every numeric knob has bounds; outside them the policy is invalid, not lower
        monkeypatch.setenv("CRB_SIGNOFF__N_MIN", "0")
        assert env.post("/signoffs", json=attested_body(env, DELIVER)).status_code == 503
        monkeypatch.setenv("CRB_SIGNOFF__N_MIN", "1")
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_CONTROLS_PASSED", "false")
        monkeypatch.setenv("CRB_SIGNOFF__REQUIRE_ROUTE_DELIVER", "false")
        # the most relaxed policy there is still refuses false-Q1 …
        _seed_false_q1_row(env, cls="bug.fix", size="S")
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"
        # … an unmeasured oracle (the thin cell's tasks carry no score) …
        r = env.post("/signoffs", json={"repo": ALPHA, "cell": THIN})
        assert r.status_code == 409 and envelope(r)["detail"]["code"] == "oracle_unmeasured"
        assert _codes(envelope(r)["detail"]["refusals"]) == [
            "oracle_unmeasured",
            "attestation_missing",
        ]
        # … and a missing attestation
        score_oracle(env, cell=THIN_CELL)
        r = env.post("/signoffs", json={"repo": ALPHA, "cell": THIN})
        assert r.status_code == 409 and envelope(r)["detail"]["code"] == "attestation_missing"


# ---------------------------------------------------------------------------
# Preview — the bar, before the approver tries
# ---------------------------------------------------------------------------


class TestPreview:
    def test_preview_is_a_viewer_read(self, env: Env) -> None:
        assert_rbac(
            env,
            "GET",
            f"/signoffs/preview?repo={ALPHA}&capability_class=bug.fix&size=S",
            min_role="viewer",
        )

    def test_preview_of_the_seeded_deliver_cell_lists_the_refusals(self, env: Env) -> None:
        login(env.client, "viewer")
        r = _preview(env, DELIVER)
        assert r.status_code == 200, r.text
        d = r.json()
        assert (
            d["repo"] == ALPHA
            and d["cell"]["capability_class"] == "bug.fix"
            and d["cell"]["size"] == "S"
        )
        assert d["signable"] is False
        assert _codes(d["refusals"]) == [
            "controls_escapes",
            "oracle_weak",
            "route_not_deliver:oracle_weak",
            "attestation_missing",
        ]
        esc = d["refusals"][0]
        assert esc["threshold"] == 0 and esc["observed"] == 1 and esc["overridable"] is True
        weak = d["refusals"][1]
        assert weak["threshold"] == 0.8 and weak["observed"] == SEED_ORACLE
        assert d["refusals"][3]["overridable"] is False
        # what the approver must see: n / point / Wilson-low / false-Q1 / oracle / split
        ev = d["evidence"]
        assert (
            ev["measured"] is True and ev["n"] == 40 and ev["clean"] == 38 and ev["point"] == 0.95
        )
        assert ev["ci_low"] == pytest.approx(0.835, abs=0.001) and ev["ci_high"] > 0.95
        assert ev["false_q1"] == 0 and ev["oracle_strength"] == SEED_ORACLE
        assert ev["oracle"] == {"strength": SEED_ORACLE, "scored": 3, "tasks": 4}
        assert ev["apparatus_versions"] == [APPARATUS_VERSION] and ev["belt_sets"] == [BELT_SET_V5]
        assert ev["failure_split"] == {
            "builder_red": 2,
            "budget": 0,
            "protocol": 0,
            "harness": 0,
            "disqualified": 0,
            "lint": 0,
            "lint_evaluated": 0,
            "outage": 0,
        }
        assert ev["model_n"] == 40 and ev["model_point"] == 0.95
        # the controls verdict (k of N, escapes, run id, date) and the route + reason
        assert d["controls"]["state"] == "escaped" and d["controls"]["escapes"] == 1
        assert d["controls"]["constructible"] == 12 and d["controls"]["total"] == 14
        assert d["controls"]["run_id"] == "0" * 32 and d["controls"]["created"]
        assert d["route"] == {
            "route": "human",
            "reason": d["route"]["reason"],
            "reason_code": "oracle_weak",
        }
        assert "oracle strength 0.58" in d["route"]["reason"]
        # the policy in force and what the record would carry
        assert d["policy"]["policy_version"] == "signoff-policy.v2"
        assert d["policy"]["require_oracle_measured"] is True
        wr = d["would_record"]
        assert wr["n_at_signoff"] == 40 and wr["route_reason_code"] == "oracle_weak"
        assert wr["controls_verdict"] == "escaped" and wr["controls_escapes"] == 1
        assert wr["oracle_strength_at_signoff"] == pytest.approx(SEED_ORACLE, abs=1e-4)
        assert wr["policy_version"] == "signoff-policy.v2"
        assert wr["policy_thresholds"] == DEFAULT_THRESHOLDS and wr["attestation"] is None
        assert "row_hash" not in wr and "record_id" not in wr
        # the accepted rows the approver may name: clean, newest first, with subjects
        rows = d["accepted_rows"]
        assert len(rows) == 38 and rows[0]["row_hash"] == accepted_row(env, DELIVER).row_hash
        assert all(len(x["row_hash"]) == 64 and x["subject"].startswith("fix: task") for x in rows)
        assert rows[0]["task_id"] == accepted_row(env, DELIVER).task_id
        assert d["attestation"] is None

    def test_preview_lists_oracle_unmeasured_with_observed_null(self, env: Env) -> None:
        """The v2 clause in the preview: ``observed: null`` (nothing was measured — never
        0), threshold ``measured``, non-overridable; the oracle block says 0 of 4 tasks."""
        pass_controls(env)
        score_oracle(env, strength=None)  # every task of the cell: latest score unscoreable
        d = _preview(env, DELIVER).json()
        assert _codes(d["refusals"]) == ["oracle_unmeasured", "attestation_missing"]
        unm = d["refusals"][0]
        assert unm["observed"] is None and unm["threshold"] == "measured"
        assert unm["overridable"] is False and "mutation score" in unm["message"]
        assert d["evidence"]["oracle_strength"] is None
        assert d["evidence"]["oracle"] == {"strength": None, "scored": 0, "tasks": 4}
        assert d["would_record"]["oracle_strength_at_signoff"] is None
        assert d["signable"] is False and d["route"]["route"] == "deliver"

    def test_preview_becomes_signable_with_a_clean_gate_and_a_named_row(self, env: Env) -> None:
        clear_policy(env)
        d = _preview(env, DELIVER).json()
        assert _codes(d["refusals"]) == ["attestation_missing"] and d["signable"] is False
        assert d["evidence"]["oracle"] == {"strength": STRONG_ORACLE, "scored": 4, "tasks": 4}
        row = accepted_row(env, DELIVER)
        d = _preview(env, DELIVER, reviewed_row_hash=row.row_hash, statement="read-it").json()
        assert d["refusals"] == [] and d["signable"] is True
        assert d["attestation"]["reviewed_task_id"] == row.task_id
        assert d["attestation"]["subject"] == _subject(env, row.task_id)
        assert d["attestation"]["statement"] == "read-it"
        assert d["would_record"]["attestation"]["reviewed_row_hash"] == row.row_hash
        assert d["would_record"]["route_at_signoff"] == "deliver"
        assert d["controls"]["state"] == "passed" and d["controls"]["run_id"] == CLEAN_CONTROLS_RUN
        # and the POST the UI then sends agrees with the preview
        assert env.post("/signoffs", json=attested_body(env, DELIVER)).status_code == 201

    def test_preview_thin_and_unmeasured_cells(self, env: Env) -> None:
        clear_policy(env)
        d = _preview(env, THIN).json()
        assert d["evidence"]["n"] == 4 and d["refusals"][0]["code"] == "thin_cell"
        assert d["refusals"][0]["observed"] == 4 and d["refusals"][0]["threshold"] == 10
        assert d["refusals"][1]["code"] == "oracle_unmeasured"  # the thin cell's tasks: unscored
        assert d["evidence"]["oracle"] == {"strength": None, "scored": 0, "tasks": 2}
        assert d["route"]["reason_code"] == "n_below_min"
        assert len(d["accepted_rows"]) == 2
        d = _preview(env, {"capability_class": "docs.update", "size": "S"}).json()
        assert d["evidence"]["measured"] is False and d["evidence"]["n"] == 0
        assert d["evidence"]["point"] is None and d["route"]["route"] == "not_yet_measured"
        assert _codes(d["refusals"])[0] == "thin_cell" and d["accepted_rows"] == []
        assert "oracle_unmeasured" in _codes(d["refusals"])
        assert d["evidence"]["oracle"] == {"strength": None, "scored": 0, "tasks": 0}
        assert d["would_record"]["policy_version"] == ""  # nothing stamped for an unmeasured cell

    def test_preview_validates_the_named_row_like_the_post(self, env: Env) -> None:
        clear_policy(env)
        red = accepted_row(env, DELIVER, clean=False)
        r = _preview(env, DELIVER, reviewed_row_hash=red.row_hash)
        assert r.status_code == 422 and "not an accepted row" in envelope(r)["message"]
        r = _preview(env, DELIVER, reviewed_row_hash="zz")
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"
        r = _preview(env, DELIVER, reviewed_row_hash=accepted_row(env, THIN).row_hash)
        assert r.status_code == 422 and "outside the attested scope" in envelope(r)["message"]

    def test_preview_errors(self, env: Env) -> None:
        assert env.get("/signoffs/preview?repo=nope&capability_class=bug.fix").status_code == 404
        assert env.get(f"/signoffs/preview?repo={ALPHA}").status_code == 422
        r = env.get(f"/signoffs/preview?repo={ALPHA}&capability_class=bug.fix&size=XXL")
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"
        _seed_false_q1_row(env)
        r = _preview(env, {"capability_class": "docs.update", "size": "S"})
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"
        assert envelope(r)["detail"]["code"] == "false_q1"
        assert _events(env, "signoff.refused") == []  # a preview is not an attempt


# ---------------------------------------------------------------------------
# List, get, revoke, chain
# ---------------------------------------------------------------------------


class TestListAndRevoke:
    def test_list_active_and_history(self, env: Env) -> None:
        clear_policy(env)
        assert env.get("/signoffs").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
        sid = env.post("/signoffs", json=attested_body(env, DELIVER)).json()["id"]
        login(env.client, "viewer")
        page = env.get(f"/signoffs?repo={ALPHA}").json()
        assert page["total"] == 1 and page["items"][0]["id"] == sid
        assert (
            page["items"][0]["attestation"]["reviewed_row_hash"]
            == accepted_row(env, DELIVER).row_hash
        )
        assert env.get("/signoffs").json()["total"] == 1
        assert env.get(f"/signoffs?repo={BETA}").json()["total"] == 0
        assert env.get(f"/signoffs/{sid}").json()["id"] == sid
        assert env.get("/signoffs/nope").status_code == 404

    def test_legacy_row_without_the_snapshot_is_served_honestly(self, env: Env) -> None:
        """A row written before the policy (no policy / attestation keys) lists as
        ``crb.signoff.v1`` with empty route / controls and no attestation — never a
        fabricated snapshot — and its chain still verifies."""
        from crb.core.evidence import utc_now_iso
        from crb.server.routes.signoffs import signoff_hash as _hash

        with env.factory() as s:
            row = Signoff(
                signoff_id="legacy00" * 4,
                repo=ALPHA,
                cell_json={
                    **dict.fromkeys(
                        ("process_step", "language", "builder", "model", "provider"), "*"
                    ),
                    "capability_class": "bug.fix",
                    "size": "S",
                    "evidence_n": "40",
                    "evidence_point": "0.950000",
                    "evidence_ci_low": "0.835000",
                    "evidence_ci_high": "0.985000",
                    "evidence_false_q1": "0",
                    "evidence_apparatus": "2.0",
                },
                tier="human-verified",
                verifier="old-approver",
                note="signed before the policy",
                revoke=False,
                evidence_rows=40,
                created=utc_now_iso(),
                prev_hash=GENESIS_HASH,
            )
            row.row_hash = _hash(row)
            s.add(row)
            s.commit()
        item = env.get(f"/signoffs?repo={ALPHA}").json()["items"][0]
        assert item["schema"] == "crb.signoff.v1" and item["policy_version"] == ""
        assert item["policy_thresholds"] == {} and item["attestation"] is None
        assert item["route"] == {"route": "", "reason": "", "reason_code": ""}
        assert item["controls"]["verdict"] == "" and item["controls"]["k"] == 0
        assert item["evidence"]["n"] == 40 and item["evidence"]["oracle_strength"] is None
        # trust once given stands until revoked / false-Q1 — or until the apparatus moves:
        # this legacy row was stamped at 2.0 and the instrument now reads at a later one
        assert item["stale"] is True and item["active"] is False
        assert verify_signoff_rows(_signoffs(env)) == 1
        # a new attestation chains after it
        clear_policy(env)
        assert env.post("/signoffs", json=attested_body(env, DELIVER)).status_code == 201
        assert verify_signoff_rows(_signoffs(env)) == 2

    def test_row_signed_under_policy_v1_is_served_as_v1_and_still_verifies(self, env: Env) -> None:
        """A record written under ``signoff-policy.v1`` (its thresholds carry no
        ``require_oracle_measured``, its oracle snapshot may be empty) keeps the version
        it was signed under, its chain verifies, and a v2 record chains after it."""
        from crb.core.evidence import utc_now_iso
        from crb.server.routes.signoffs import signoff_hash as _hash

        v1_thresholds = {
            k: v for k, v in DEFAULT_THRESHOLDS.items() if k != "require_oracle_measured"
        }
        row_hash = accepted_row(env, DELIVER).row_hash
        with env.factory() as s:
            row = Signoff(
                signoff_id="policyv1" * 4,
                repo=ALPHA,
                cell_json={
                    **dict.fromkeys(
                        ("process_step", "language", "builder", "model", "provider"), "*"
                    ),
                    "capability_class": "bug.fix",
                    "size": "S",
                    "evidence_n": "40",
                    "evidence_point": "0.950000",
                    "evidence_ci_low": "0.835000",
                    "evidence_ci_high": "0.985000",
                    "evidence_false_q1": "0",
                    "evidence_apparatus": "2.1",
                    "evidence_oracle_strength": "",
                    "policy_version": "signoff-policy.v1",
                    "policy_thresholds": json.dumps(v1_thresholds, sort_keys=True),
                    "route": "deliver",
                    "route_reason": "n=40",
                    "route_reason_code": "deliver",
                    "controls_verdict": "passed",
                    "controls_run_id": CLEAN_CONTROLS_RUN,
                    "controls_created": "2026-09-14T00:00:00+00:00",
                    "controls_k": "12",
                    "controls_total": "14",
                    "controls_escapes": "0",
                    "attestation_reviewed_task_id": accepted_row(env, DELIVER).task_id,
                    "attestation_reviewed_row_hash": row_hash,
                    "attestation_statement": "read under v1",
                    "attestation_at": "2026-09-14T00:00:00+00:00",
                },
                tier="human-verified",
                verifier="v1-approver",
                note="signed under signoff-policy.v1",
                revoke=False,
                evidence_rows=40,
                created=utc_now_iso(),
                prev_hash=GENESIS_HASH,
            )
            row.row_hash = _hash(row)
            s.add(row)
            s.commit()
        item = env.get(f"/signoffs?repo={ALPHA}").json()["items"][0]
        assert item["schema"] == "crb.signoff.v2" and item["policy_version"] == "signoff-policy.v1"
        assert item["policy_thresholds"] == v1_thresholds
        assert "require_oracle_measured" not in item["policy_thresholds"]
        assert item["evidence"]["oracle_strength"] is None  # what it saw, not today's measurement
        assert item["attestation"]["reviewed_row_hash"] == row_hash
        # stamped at apparatus 2.1 and read at the current one: STALE — served, verifying,
        # but lifting nothing until re-signed (evidence expires when the apparatus changes)
        assert item["stale"] is True and item["active"] is False
        assert item["apparatus_current"] == APPARATUS_VERSION
        assert verify_signoff_rows(_signoffs(env)) == 1
        clear_policy(env)
        r = env.post("/signoffs", json=attested_body(env, DELIVER))
        assert r.status_code == 201 and r.json()["policy_version"] == "signoff-policy.v2"
        assert verify_signoff_rows(_signoffs(env)) == 2

    def test_revoke_rbac(self, env: Env) -> None:
        clear_policy(env)
        sid = env.post("/signoffs", json=attested_body(env, DELIVER)).json()["id"]
        assert_rbac(env, "POST", f"/signoffs/{sid}/revoke", min_role="approver", json={"note": "x"})

    def test_revoke_appends_and_hides(self, env: Env) -> None:
        clear_policy(env)
        sid = env.post("/signoffs", json=attested_body(env, DELIVER)).json()["id"]
        assert (
            env.get(f"/capability-map?repo={ALPHA}").json()["cells"][1]["verification_tier"]
            == "human-verified"
        )
        r = env.post(f"/signoffs/{sid}/revoke", json={"note": "evidence re-examined"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["id"] == sid and d["revoked"] is True and d["active"] is False
        assert d["revoked_by"] and d["revoked_at"] and d["revoked_by_name"] == "appr1"
        assert d["attestation"] is not None  # the attestation that WAS made stays on the record
        rows = _signoffs(env)
        assert [x.revoke for x in rows] == [False, True]
        assert rows[1].prev_hash == rows[0].row_hash and rows[1].note == "evidence re-examined"
        assert verify_signoff_rows(rows) == 2
        # J-TEL-8: the audit event ties itself to the chain by hash — the revocation row's
        # hash, the hash of the row it revokes, and the reason — so an auditor reconciling
        # the events trace against the sign-off chain never has to search by scope and time
        (revoked,) = _events(env, "signoff.revoked")
        assert revoked.actor == d["revoked_by"]
        assert revoked.payload_json["signoff_id"] == sid
        assert revoked.payload_json["row_hash"] == rows[1].row_hash
        assert revoked.payload_json["revokes_row_hash"] == rows[0].row_hash
        assert revoked.payload_json["note"] == "evidence re-examined"
        assert revoked.payload_json["cell"] == rows[1].cell_json  # the scope, as the row says
        # hidden from the active list, present in the history, tier back to automated-pass
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 0
        hist = env.get(f"/signoffs?repo={ALPHA}&include_revoked=true").json()
        assert hist["total"] == 1 and hist["items"][0]["revoked"] is True
        assert (
            env.get(f"/capability-map?repo={ALPHA}").json()["cells"][1]["verification_tier"]
            == "automated-pass"
        )
        # twice → 409; unknown → 404; the revocation row itself is not an attestation id
        why = {"note": "again"}
        r = env.post(f"/signoffs/{sid}/revoke", json=why)
        assert r.status_code == 409 and envelope(r)["code"] == "already_revoked"
        assert env.post("/signoffs/nope/revoke", json=why).status_code == 404
        assert env.post(f"/signoffs/{rows[1].signoff_id}/revoke", json=why).status_code == 404
        assert env.get(f"/signoffs/{rows[1].signoff_id}").status_code == 404

    def test_revoke_needs_a_reason_at_the_api_not_just_in_the_ui(self, env: Env) -> None:
        clear_policy(env)
        sid = env.post("/signoffs", json=attested_body(env, DELIVER)).json()["id"]
        # no body, an empty note and a blank note are all refused before anything is written
        assert env.post(f"/signoffs/{sid}/revoke").status_code == 422
        assert env.post(f"/signoffs/{sid}/revoke", json={}).status_code == 422
        assert env.post(f"/signoffs/{sid}/revoke", json={"note": ""}).status_code == 422
        assert env.post(f"/signoffs/{sid}/revoke", json={"note": "   "}).status_code == 422
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 1
        assert [x.revoke for x in _signoffs(env)] == [False]
        r = env.post(f"/signoffs/{sid}/revoke", json={"note": "  evidence re-examined  "})
        assert r.status_code == 200 and _signoffs(env)[1].note == "evidence re-examined"

    def test_re_attest_after_revoke(self, env: Env) -> None:
        clear_policy(env)
        sid = env.post("/signoffs", json=attested_body(env, DELIVER)).json()["id"]
        env.post(f"/signoffs/{sid}/revoke", json={"note": "re-examined"})
        r = env.post("/signoffs", json=attested_body(env, DELIVER, note="again"))
        assert r.status_code == 201 and r.json()["active"] is True
        page = env.get(f"/signoffs?repo={ALPHA}").json()
        assert page["total"] == 1 and page["items"][0]["note"] == "again"
        assert verify_signoff_rows(_signoffs(env)) == 3

    def test_chain_detects_tampering_including_the_attestation(self, env: Env) -> None:
        clear_policy(env)
        env.post("/signoffs", json=attested_body(env, DELIVER))
        env.post("/signoffs", json=attested_body(env, env.info.deliver_cell))
        with env.factory() as s:
            s.execute(text("DROP TRIGGER signoffs_no_update"))
            s.execute(text("UPDATE signoffs SET note = 'edited' WHERE seq = 1"))
            s.commit()
        with pytest.raises(LedgerIntegrityError, match="sign-off 1"):
            verify_signoff_rows(_signoffs(env))
        with env.factory() as s:
            s.execute(
                text(
                    "UPDATE signoffs SET note = 'reviewed the packs and one accepted diff' WHERE seq = 1"
                )
            )
            s.execute(
                text(
                    "UPDATE signoffs SET cell_json = json_set(cell_json, '$.attestation_reviewed_row_hash', :h) WHERE seq = 2"
                ),
                {"h": "f" * 64},
            )
            s.commit()
        with pytest.raises(LedgerIntegrityError, match="sign-off 2"):
            verify_signoff_rows(_signoffs(env))
