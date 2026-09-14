"""``/capability-map``, ``/routes`` and ``/failure-split`` — honest cells, the one rule,
the controls verdict (ADR-0003 amendment), the failure split, sign-off overlay.

The seed's latest ``controls.report`` (see ``fixtures/server_seed``) PASSED with
14 rows, 2 not constructible and **1 escape** — so the 40-row cell that delivers on
the numbers alone routes ``human`` (``controls_escapes``) on the product surface.
Tests that need another controls state append a NEWER ``controls.report`` event
(the latest wins) or remove them all (``unmeasured``); nothing bypasses the rule.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import CELL_FIELDS, GradeRow
from crb.core.routing import DEFAULT_POLICY
from crb.core.version import APPARATUS_VERSION
from crb.observability.events import StepEvent, StepStatus
from crb.store.ledger import DbLedger
from crb.store.models import Event, Grade, Run
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, BETA, RUN_IDS, Env, envelope, login, make_env
from fixtures.signoff_seed import attested_body, clear_policy

CELL_KEYS = {
    "n",
    "clean",
    "point",
    "ci_low",
    "ci_high",
    "false_q1",
    "cost_usd_mean",
    "latency_s_mean",
    "oracle_strength_mean",
    "route",
    "reason",
    "reason_code",
    "verification_tier",
    "apparatus_versions",
    "belt_set",
    "n_builder_red",
    "n_budget",
    "n_protocol",
    "n_harness",
    "n_disqualified",
    "model_n",
    "model_point",
    "model_ci_low",
    "model_ci_high",
    "failure_split",
}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _cells(env: Env, query: str = "") -> dict[str, dict[str, Any]]:
    r = env.get(f"/capability-map?repo={ALPHA}{query}")
    assert r.status_code == 200, r.text
    return {str(c["label"]): c for c in r.json()["cells"]}


def controls_report(
    env: Env,
    *,
    passed: bool = True,
    n_rows: int = 14,
    not_constructible: int = 2,
    escapes: int = 0,
    skipped: int = 0,
    run_id: str = "9" * 32,
    complete: bool = True,
) -> None:
    """Append a NEWER ``controls.report`` event for alpha (the latest report wins)."""
    ev = StepEvent(
        trace_id=run_id,
        stage="oracle",
        action="controls.report",
        status=StepStatus.OK,
        repo=ALPHA,
        actor="worker-1",
        seq=1,
        payload={
            "schema": "crb.negative_controls.v1",
            "apparatus": {"apparatus_version": "2.0", "complete": complete},
            "n_tasks": 2,
            "n_rows": n_rows,
            "violations": 0 if passed else 7,
            "escapes": escapes,
            "not_constructible": not_constructible,
            "skipped": skipped,
            "passed": passed,
            "escape_rows": [],
            "rows": [{"control": "gold", "verdict": "ok"}] * n_rows,
        },
    )
    d = ev.to_dict()
    payload = d.pop("payload")
    with env.factory() as s:
        s.add(Event(**d, payload_json=payload))
        s.commit()


def seed_beta_rows(env: Env, n: int = 40, clean: int = 39) -> None:
    """Rows for BETA (which has no controls report) through the write path — a cell
    that delivers on the numbers alone, on a repo whose controls were never run."""
    rows = [
        GradeRow(
            repo=BETA,
            task_id=f"{i:040x}",
            clean=i < clean,
            tests_unmodified=True,
            target_green=i < clean,
            no_new_failures=True,
            source_changed=True,
            capability_class="bug.fix",
            size="S",
            language="go",
            builder="editblock",
            model="m",
            provider="p",
            run_id="b" * 32,
            trial="r1",
            cost_usd=0.01,
            evidence_pack_hash=("e" * 64) if i < clean else "",
            gold_clean=True,
        )
        for i in range(n)
    ]
    DbLedger(env.factory).append_many(rows)


class TestCapabilityMap:
    def test_shape_measured_cells_only(self, env: Env) -> None:
        r = env.get(f"/capability-map?repo={ALPHA}")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {
            "repo",
            "by",
            "classes",
            "sizes",
            "languages",
            "models",
            "cells",
            "summary",
            "policy",
            "controls",
        }
        assert body["repo"] == ALPHA and body["by"] == ["capability_class", "size"]
        assert body["classes"] == ["backend.route.add", "bug.fix", "test.add"]
        assert body["sizes"] == ["XS", "S", "M"]  # tier order, not alphabetical
        assert body["languages"] == ["python"]
        assert body["models"] == ["gpt-oss-120b", "sonnet"]
        assert body["policy"] == DEFAULT_POLICY.to_dict()
        assert body["policy"]["controls_version"] == "controls-gate.v1"
        labels = {c["label"] for c in body["cells"]}
        assert labels == {"backend.route.add|M", "bug.fix|S", "test.add|XS"}
        # NOT_YET_MEASURED cells are absent, never fabricated
        assert "docs.update|S" not in labels and "bug.fix|XL" not in labels
        for c in body["cells"]:
            assert c["n"] > 0 and c["route"] != "NOT_YET_MEASURED"
            assert set(c) >= CELL_KEYS
            assert set(c["failure_split"]) == {
                "builder_red",
                "lint",
                "budget",
                "protocol",
                "harness",
                "disqualified",
                "lint_evaluated",
            }
            assert c["capability_class"] != "*" and c["size"] != "*" and c["language"] == "*"

    def test_the_seeds_controls_verdict_is_on_the_map(self, env: Env) -> None:
        body = env.get(f"/capability-map?repo={ALPHA}").json()
        v = body["controls"]
        assert v == {
            "measured": True,
            "passed": True,
            "complete": True,
            "constructible": 12,
            "total": 14,
            "share": round(12 / 14, 4),
            "escapes": 1,
            "run_id": RUN_IDS["controls"],
            "created": v["created"],
            "state": "escaped",
        }
        assert v["created"]
        # ONE source: the verdict the controls screen serves is the one the map routed under
        served = env.get(f"/oracle/{ALPHA}/controls").json()["verdict"]
        assert served == v

    def test_green_cell_routes_human_on_the_seeds_escape(self, env: Env) -> None:
        c = _cells(env)["bug.fix|S"]
        assert c["n"] == 40 and c["clean"] == 38 and c["point"] == 0.95
        assert c["ci_low"] == pytest.approx(0.835, abs=0.001)
        # the numbers deliver; the repo's oracle let a cheat through → human, and it says why
        assert c["route"] == "human" and c["reason_code"] == "controls_escapes"
        assert "1 measurement control(s) graded clean" in str(c["reason"])
        assert f"(controls run {RUN_IDS['controls'][:8]})" in str(c["reason"])
        assert c["false_q1"] == 0 and c["verification_tier"] == "automated-pass"
        assert c["apparatus_versions"] == [APPARATUS_VERSION] and c["belt_set"] == "v5"
        assert c["cost_usd_mean"] == pytest.approx(0.012) and c["latency_s_mean"] == 42.0
        assert c["cost_known"] is True and c["oracle_strength_mean"] is None
        # the split: 2 builder_red rows, no instrument rows → model point = all-rows point
        assert c["failure_split"] == {
            "builder_red": 2,
            "lint": 0,
            "budget": 0,
            "protocol": 0,
            "harness": 0,
            "disqualified": 0,
            "lint_evaluated": 0,  # the seed's repo configures no linter: belt 5 never evaluated
        }
        assert c["n_builder_red"] == 2 and c["model_n"] == 40 and c["model_point"] == 0.95
        assert c["model_ci_low"] == c["ci_low"] and c["model_ci_high"] == c["ci_high"]

    def test_deliver_only_with_passed_majority_constructible_and_zero_escapes(
        self, env: Env
    ) -> None:
        controls_report(env, escapes=0)
        body = env.get(f"/capability-map?repo={ALPHA}").json()
        assert body["controls"]["state"] == "passed" and body["controls"]["run_id"] == "9" * 32
        c = {x["label"]: x for x in body["cells"]}["bug.fix|S"]
        assert c["route"] == "deliver" and c["reason_code"] == "deliver"
        assert str(c["reason"]).endswith("controls=passed 12/14 escapes=0")
        assert body["summary"]["deliver_cells"] == 1 and body["summary"]["cells_by_route"] == {
            "deliver": 1,
            "calibrate": 2,
            "granularize": 0,
            "human": 0,
            "do_not_ship": 0,
            "not_yet_measured": 0,
        }

    def test_failed_gate_routes_every_cell_human(self, env: Env) -> None:
        controls_report(env, passed=False)
        body = env.get(f"/capability-map?repo={ALPHA}").json()
        assert body["controls"]["state"] == "failed" and body["controls"]["passed"] is False
        for c in body["cells"]:
            assert c["route"] == "human" and c["reason_code"] == "controls_failed", c["label"]
            assert "instrument defect" in str(c["reason"])
        assert body["summary"]["deliver_cells"] == 0
        assert body["summary"]["cells_by_route"]["human"] == 3

    def test_thin_controls_withhold_deliver(self, env: Env) -> None:
        controls_report(env, n_rows=56, not_constructible=32)  # 24/56: cobra / koa
        body = env.get(f"/capability-map?repo={ALPHA}").json()
        v = body["controls"]
        assert v["state"] == "thin" and v["constructible"] == 24 and v["total"] == 56
        assert v["share"] == round(24 / 56, 4)
        c = {x["label"]: x for x in body["cells"]}["bug.fix|S"]
        assert c["route"] == "calibrate" and c["reason_code"] == "controls_thin"
        assert "only 24 of 56 control rows were constructible" in str(c["reason"])
        # the thin cell still names n first — the more actionable reason
        thin = {x["label"]: x for x in body["cells"]}["backend.route.add|M"]
        assert thin["reason_code"] == "n_below_min"

    def test_unmeasured_controls_withhold_deliver(self, env: Env) -> None:
        seed_beta_rows(env)  # beta: 39/40 clean, never ran controls
        body = env.get(f"/capability-map?repo={BETA}").json()
        assert body["controls"] == {
            "measured": False,
            "passed": False,
            "complete": True,
            "constructible": 0,
            "total": 0,
            "share": 0.0,
            "escapes": 0,
            "run_id": "",
            "created": "",
            "state": "unmeasured",
        }
        c = {x["label"]: x for x in body["cells"]}["bug.fix|S"]
        assert c["n"] == 40 and c["point"] == 0.975 and c["ci_low"] > 0.8
        assert c["route"] == "calibrate" and c["reason_code"] == "controls_unmeasured"
        assert "run a 'controls' run" in str(c["reason"])
        assert body["summary"]["deliver_cells"] == 0
        # alpha's verdict is alpha's: nothing leaks across repos
        assert env.get(f"/capability-map?repo={ALPHA}").json()["controls"]["measured"] is True

    def test_verdict_falls_back_to_the_runs_counts_when_no_event(self, env: Env) -> None:
        """A finished controls RUN with counts but no report event (pruned) still counts."""
        seed_beta_rows(env)
        with env.factory() as s:
            s.add(
                Run(
                    id="7" * 32,
                    repo=BETA,
                    kind="controls",
                    status="failed",  # the gate said FAIL: exactly what routing must see
                    actor="op1",
                    error="negative-controls gate FAILED: 7 violation(s)",
                    counts_json={
                        "tasks": 8,
                        "total": 8,
                        "rows": 56,
                        "violations": 7,
                        "escapes": 0,
                        "not_constructible": 0,
                        "skipped": 0,
                        "passed": False,
                        "complete": True,
                    },
                    created="2026-09-10T09:00:00+00:00",
                    finished="2026-09-10T09:20:00+00:00",
                )
            )
            s.commit()
        body = env.get(f"/capability-map?repo={BETA}").json()
        v = body["controls"]
        assert v["state"] == "failed" and v["run_id"] == "7" * 32
        assert v["constructible"] == 56 and v["total"] == 56
        assert v["created"] == "2026-09-10T09:20:00+00:00"
        c = {x["label"]: x for x in body["cells"]}["bug.fix|S"]
        assert c["route"] == "human" and c["reason_code"] == "controls_failed"
        # a queued / running / cancelled controls run is not a measurement
        with env.factory() as s:
            s.add(
                Run(
                    id="6" * 32,
                    repo=BETA,
                    kind="controls",
                    status="cancelled",
                    actor="op1",
                    counts_json={"rows": 3, "passed": True, "complete": False},
                    created="2026-09-11T09:00:00+00:00",
                )
            )
            s.commit()
        assert env.get(f"/capability-map?repo={BETA}").json()["controls"]["run_id"] == "7" * 32

    def test_thin_cell_calibrates(self, env: Env) -> None:
        c = _cells(env)["backend.route.add|M"]
        assert c["n"] == 4 and c["clean"] == 2 and c["errors"] == 1
        assert c["route"] == "calibrate" and "n=4 < 10" in str(c["reason"])
        assert c["reason_code"] == "n_below_min"
        # 1 builder_red + 1 harness (the failed run's sandbox error) → model 2/3 vs all-rows 2/4
        assert c["failure_split"] == {
            "builder_red": 1,
            "lint": 0,
            "budget": 0,
            "protocol": 0,
            "harness": 1,
            "disqualified": 0,
            "lint_evaluated": 0,
        }
        assert c["point"] == 0.5 and c["model_n"] == 3 and c["model_point"] == round(2 / 3, 4)
        assert c["model_ci_low"] < c["model_point"] < c["model_ci_high"]

    def test_legacy_cell_is_a_separate_apparatus(self, env: Env) -> None:
        c = _cells(env)["test.add|XS"]
        assert c["belt_set"] == "v3-legacy" and c["belt_sets"] == ["v3-legacy"]
        assert c["apparatus_versions"] == ["1.0-census"]
        assert c["n"] == 6 and c["clean"] == 5 and c["route"] == "calibrate"
        assert c["cost_known"] is False and c["cost_usd_mean"] == 0.0
        # legacy rows carry no failure_kind label: derived on read → builder_red
        assert c["failure_split"]["builder_red"] == 1 and c["failure_split"]["harness"] == 0

    def test_summary_without_profile(self, env: Env) -> None:
        s = env.get(f"/capability-map?repo={ALPHA}").json()["summary"]
        assert s["trusted_autonomy_coverage"] is None  # no profile → not fabricated
        assert s["earned_coverage"] is None and s["profile_commits"] is None
        assert s["measured_cells"] == 3 and s["deliver_cells"] == 0  # the seed's escape
        assert s["total_cells"] == 9  # 3 classes × 3 sizes seen
        assert s["cells_by_route"]["human"] == 1 and s["cells_by_route"]["calibrate"] == 2
        assert s["n_total"] == 50 and s["rows"] == 50 and s["false_q1_total"] == 0
        assert s["apparatus_versions"] == ["1.0-census", APPARATUS_VERSION]
        assert s["signoffs_applied"] == 0

    def test_summary_with_profile_has_coverage(self, tmp_path: Path) -> None:
        repo = pr.build(tmp_path / "pyrepo")
        with make_env(tmp_path, clone_path=str(repo.path)) as env:
            assert env.get(f"/repos/{ALPHA}/profile").status_code == 200
            s = env.get(f"/capability-map?repo={ALPHA}").json()["summary"]
            # the fixture repo's change mix is bug.fix/XS — unmeasured here → 0.0 coverage, not null
            assert s["trusted_autonomy_coverage"] == 0.0 and s["earned_coverage"] == 0.0
            assert s["profile_commits"] == 1

    def test_projections(self, env: Env) -> None:
        by_lang = _cells(env, "&by=class,size,language")
        assert set(by_lang) == {
            "backend.route.add|M|python",
            "bug.fix|S|python",
            "test.add|XS|python",
        }
        assert by_lang["bug.fix|S|python"]["language"] == "python"
        by_model = _cells(env, "&by=class,size,model")
        assert by_model["bug.fix|S|gpt-oss-120b"]["route"] == "human"  # the seed's escape
        by_class = env.get(f"/capability-map?repo={ALPHA}&by=class").json()
        assert by_class["by"] == ["capability_class"]
        assert {c["label"] for c in by_class["cells"]} == {
            "backend.route.add",
            "bug.fix",
            "test.add",
        }
        full = env.get(f"/capability-map?repo={ALPHA}&by=cell").status_code
        assert full == 422  # 'cell' is not a field alias
        r = env.get(f"/capability-map?repo={ALPHA}&by=class,colour")
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"

    def test_empty_repo_and_404(self, env: Env) -> None:
        r = env.get(f"/capability-map?repo={BETA}")
        assert r.status_code == 200
        body = r.json()
        assert body["cells"] == [] and body["classes"] == []
        assert body["summary"]["measured_cells"] == 0 and body["summary"]["total_cells"] == 0
        assert body["controls"]["state"] == "unmeasured"  # beta never ran controls
        assert env.get("/capability-map?repo=nope").status_code == 404
        assert env.get("/capability-map").status_code == 422

    def test_signoff_overlay_lifts_tier(self, env: Env) -> None:
        login(env.client, "approver")
        # under signoff-policy.v2 the seeded cell is REFUSED while the controls gate has
        # an escape (its route is human) and its oracle measures weak — the sign-off never
        # lifts a route, so it can only be made once a clean controls run and strong
        # oracle scores land and the route is deliver
        cell = {"capability_class": "bug.fix", "size": "S"}
        r = env.post("/signoffs", json=attested_body(env, cell, note="ok"))
        assert r.status_code == 409 and envelope(r)["detail"]["code"] == "controls_escapes"
        assert _cells(env)["bug.fix|S"]["route"] == "human"
        clear_policy(env)
        r = env.post("/signoffs", json=attested_body(env, cell, note="ok"))
        assert r.status_code == 201, r.text
        cells = _cells(env)
        assert cells["bug.fix|S"]["verification_tier"] == "human-verified"
        assert cells["bug.fix|S"]["route"] == "deliver"
        assert cells["backend.route.add|M"]["verification_tier"] == "automated-pass"
        assert cells["backend.route.add|M"]["route"] == "calibrate"  # a tier never moves a route
        summary = env.get(f"/capability-map?repo={ALPHA}").json()["summary"]
        assert summary["signoffs_applied"] == 1
        # the attestation is repo-scoped: beta's (empty) map does not borrow it
        assert env.get(f"/capability-map?repo={BETA}").json()["summary"]["signoffs_applied"] == 0

    def test_false_q1_row_refuses_the_map(self, env: Env) -> None:
        """A false-Q1 row inserted straight through the ORM (bypassing DbLedger) makes the
        reducing read refuse with 409 — the map is never computed over untrusted rows."""
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
                    capability_class="docs.update",
                    size="S",
                    language="python",
                    evidence_pack_hash="p" * 64,
                    apparatus_version="2.0",
                    belt_set="v4",
                    prev_hash="x" * 64,
                    row_hash="y" * 64,
                )
            )
            s.commit()
        r = env.get(f"/capability-map?repo={ALPHA}")
        assert r.status_code == 409
        e = envelope(r)
        assert e["code"] == "false_q1_refused" and e["detail"] == {"exception": "FalseQ1Violation"}
        assert env.get(f"/routes?repo={ALPHA}").status_code == 409
        assert env.get(f"/failure-split?repo={ALPHA}").status_code == 409
        assert env.get(f"/capability-map?repo={BETA}").status_code == 200  # other repos unaffected

    def test_viewer_reads(self, env: Env) -> None:
        login(env.client, "viewer")
        assert env.get(f"/capability-map?repo={ALPHA}").status_code == 200
        assert env.get(f"/routes?repo={ALPHA}").status_code == 200
        assert env.get(f"/failure-split?repo={ALPHA}").status_code == 200


class TestRoutes:
    def test_decisions_per_full_cell(self, env: Env) -> None:
        r = env.get(f"/routes?repo={ALPHA}")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"repo", "by", "policy", "decisions", "controls"}
        assert body["by"] == list(CELL_FIELDS) and body["policy"]["version"] == "routing.v1"
        assert body["policy"]["controls_version"] == "controls-gate.v1"
        assert body["controls"]["state"] == "escaped"
        by_label = {d["label"]: d for d in body["decisions"]}
        green = by_label["replay|bug.fix|S|python|editblock|gpt-oss-120b|cerebras"]
        assert green["route"] == "human" and green["n"] == 40
        assert green["reason_code"] == "controls_escapes"
        assert green["controls_policy"] == "controls-gate.v1"
        assert green["controls"]["escapes"] == 1 and green["controls"]["state"] == "escaped"
        assert green["cell"] == env.info.deliver_cell
        assert green["point"] == 0.95 and green["ci_low"] == pytest.approx(0.835, abs=0.001)
        assert green["false_q1"] == 0 and green["policy_version"] == "routing.v1"
        assert green["verification_tier"] == "automated-pass"
        assert green["apparatus_versions"] == [APPARATUS_VERSION]
        assert green["model_n"] == 40 and green["model_point"] == 0.95
        assert green["failure_split"]["builder_red"] == 2
        legacy = by_label["replay|test.add|XS|python|claude-code-workflow|sonnet|anthropic"]
        assert legacy["route"] == "calibrate" and legacy["apparatus_versions"] == ["1.0-census"]
        assert legacy["reason_code"] == "n_below_min"
        assert set(by_label) == {
            "replay|backend.route.add|M|python|editblock|gpt-oss-120b|cerebras",
            "replay|bug.fix|S|python|editblock|gpt-oss-120b|cerebras",
            "replay|test.add|XS|python|claude-code-workflow|sonnet|anthropic",
        }

    def test_decisions_follow_the_latest_verdict(self, env: Env) -> None:
        controls_report(env, escapes=0)
        by_label = {d["label"]: d for d in env.get(f"/routes?repo={ALPHA}").json()["decisions"]}
        green = by_label["replay|bug.fix|S|python|editblock|gpt-oss-120b|cerebras"]
        assert green["route"] == "deliver" and green["reason_code"] == "deliver"
        controls_report(env, passed=False, run_id="8" * 32)
        r = env.get(f"/routes?repo={ALPHA}").json()
        assert r["controls"]["run_id"] == "8" * 32 and r["controls"]["state"] == "failed"
        assert {d["reason_code"] for d in r["decisions"]} == {"controls_failed"}

    def test_projection_and_empty(self, env: Env) -> None:
        r = env.get(f"/routes?repo={ALPHA}&by=class")
        assert r.json()["by"] == ["capability_class"]
        assert {d["label"] for d in r.json()["decisions"]} == {
            "backend.route.add",
            "bug.fix",
            "test.add",
        }
        assert env.get(f"/routes?repo={BETA}").json()["decisions"] == []
        assert env.get(f"/routes?repo={BETA}").json()["controls"]["state"] == "unmeasured"
        assert env.get("/routes?repo=nope").status_code == 404


class TestFailureSplit:
    def test_repo_split(self, env: Env) -> None:
        r = env.get(f"/failure-split?repo={ALPHA}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["repo"] == ALPHA and d["run_id"] == ""
        # 50 rows: 45 clean, 4 builder_red (2 deliver-cell + 1 thin + 1 legacy), 1 harness
        assert d["rows"] == 50 and d["n"] == 50 and d["clean"] == 45
        assert (d["builder_red"], d["budget"], d["protocol"], d["harness"]) == (4, 0, 0, 1)
        assert d["disqualified"] == 0
        assert d["point"] == 0.9 and d["ci_low"] < 0.9 < d["ci_high"]
        assert d["model_n"] == 49 and d["model_point"] == round(45 / 49, 4)
        assert d["model_ci_low"] < d["model_point"] < d["model_ci_high"]
        assert d["n"] == d["clean"] + d["builder_red"] + d["budget"] + d["protocol"] + d["harness"]
        # legacy rows name no builder-priced cost: 44 native rows known, 6 census rows unknown
        assert d["cost_known"] == 44 and d["cost_unknown"] == 6
        assert d["kinds"] == [
            "",
            "builder_red",
            "lint",
            "budget",
            "protocol",
            "harness",
            "disqualified",
        ]

    def test_run_split(self, env: Env) -> None:
        d = env.get(f"/failure-split?repo={ALPHA}&run_id={RUN_IDS['succeeded']}").json()
        assert d["run_id"] == RUN_IDS["succeeded"]
        assert d["rows"] == 5 and d["n"] == 5 and d["clean"] == 4 and d["builder_red"] == 1
        assert d["model_n"] == 5 and d["model_point"] == 0.8 and d["harness"] == 0
        failed = env.get(f"/failure-split?repo={ALPHA}&run_id={RUN_IDS['failed']}").json()
        assert failed["rows"] == 1 and failed["harness"] == 1 and failed["clean"] == 0
        assert failed["point"] == 0.0 and failed["model_n"] == 0 and failed["model_point"] == 0.0
        # an unknown run is an empty split, never an invented one
        empty = env.get(f"/failure-split?repo={ALPHA}&run_id={'f' * 32}").json()
        assert empty["rows"] == 0 and empty["n"] == 0 and empty["ci_low"] == 0.0
        assert empty["ci_high"] == 1.0

    def test_404_and_422(self, env: Env) -> None:
        assert env.get("/failure-split?repo=nope").status_code == 404
        assert env.get("/failure-split").status_code == 422
        assert env.get(f"/failure-split?repo={ALPHA}&run_id={'x' * 40}").status_code == 422
        assert env.get(f"/failure-split?repo={BETA}").json()["rows"] == 0
