"""``/oracle/{repo}`` and ``/oracle/{repo}/controls`` — strength, band, gate; 404 not_measured.

Navigation
----------
What it is:   ``/oracle/{repo}`` and ``/oracle/{repo}/controls``'s test suite — strength, band,
              gate; 404 ``not_measured``.
What it does: Pins the report's shape, bands and gates over the seed's ``oracle.score`` events,
              that the latest score per task wins and the class comes from the task table, the
              empty repo and 404, anonymous 401; and that the controls route serves the latest
              report, 404s when not measured, and admins read too; and that a passed report
              or run with no gold witness (before ``controls.v3``, or unstamped) is served as
              written but reads as unmeasured for routing and on its own verdict, while a
              witnessed one reads as written (P-176).
How:          ``make_env`` over the seed; extra ``oracle.score`` events appended through the ORM
              in the worker's shape.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/oracle.py (under test), src/crb/core/oracle/adequacy.py
              (the bands and gates), src/crb/server/routes/runs.py (``event_to_model``),
              tests/fixtures/server_seed.py, docs/API.md (oracle adequacy)
Tested by:    tests/test_server_routes_oracle.py
Touch when:   never for a new repository; the ``oracle.score`` or ``controls.report`` event
              shape changes in the worker (the seed and these cases together).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core.oracle.adequacy import DEFAULT_POLICY
from crb.core.oracle.controls import CONTROLS_VERSION
from crb.observability.events import StepEvent
from crb.server.routes.oracle import latest_controls_verdict
from crb.server.routes.runs import event_to_model
from crb.store.models import Run
from fixtures.server_seed import ALPHA, BETA, Env, envelope, login, make_env, task_id


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as VIEWER (the read routes need no more), torn
    down after the test."""
    with make_env(tmp_path, role="viewer") as e:
        yield e


class TestOracleReport:
    def test_shape_bands_gates(self, env: Env) -> None:
        r = env.get(f"/oracle/{ALPHA}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d) == {"repo", "policy", "tasks", "cells", "apparatus_versions", "runs"}
        assert d["repo"] == ALPHA and d["policy"] == DEFAULT_POLICY.to_dict()
        assert d["policy"]["autoship_floor"] == 0.8 and d["policy"]["adequate_floor"] == 0.5
        assert d["apparatus_versions"] == ["2.0"] and d["runs"] == [env.info.run_ids["oracle"]]
        by_task = {t["task_id"]: t for t in d["tasks"]}
        assert set(by_task) == {task_id(1), task_id(2), task_id(3), task_id(5)}
        t1 = by_task[task_id(1)]
        assert set(t1) == {
            "task_id",
            "capability_class",
            "size",
            "strength",
            "band",
            "mutants",
            "killed",
            "errors",
            "gate",
            "run_id",
            "scored_at",
            "note",
        }
        assert t1["strength"] == 0.9 and t1["band"] == "strong" and t1["gate"] == "auto_ship"
        assert t1["mutants"] == 10 and t1["killed"] == 9 and t1["capability_class"] == "bug.fix"
        t2 = by_task[task_id(2)]
        assert t2["strength"] == 0.5 and t2["band"] == "adequate" and t2["gate"] == "human_review"
        t3 = by_task[task_id(3)]
        assert t3["strength"] == 0.3333 and t3["band"] == "weak" and t3["gate"] == "human_review"
        t5 = by_task[task_id(5)]
        assert (
            t5["strength"] is None and t5["band"] == "unscoreable" and t5["gate"] == "human_review"
        )
        assert t5["mutants"] == 0 and "not scoreable" in t5["note"]
        # cells: a mean over SCORED tasks only; unscoreable never averaged in
        cells = {(c["capability_class"], c["size"]): c for c in d["cells"]}
        bf = cells[("bug.fix", "S")]
        assert bf["n"] == 3 and bf["tasks"] == 3
        assert (
            bf["strength_mean"] == pytest.approx(0.5778, abs=1e-4) and bf["strength_min"] == 0.3333
        )
        assert bf["band"] == "adequate" and bf["gate"] == "human_review"
        br = cells[("backend.route.add", "M")]
        assert br["n"] == 0 and br["tasks"] == 1 and br["strength_mean"] is None
        assert br["band"] == "unscoreable" and br["gate"] == "human_review"

    def test_latest_score_per_task_wins_and_class_from_task_table(self, env: Env) -> None:
        # a later oracle run re-scores T3 as strong, with a lean payload (no class/size)
        with env.factory() as s:
            s.add(
                event_to_model(
                    StepEvent(
                        trace_id="2" * 32,
                        stage="oracle",
                        action="oracle.mutation.scored",
                        repo=ALPHA,
                        task_id=task_id(3),
                        seq=1,
                        payload={"total": 12, "killed": 11, "errors": 1, "oracle_strength": 0.9167},
                    )
                )
            )
            s.commit()
        d = env.get(f"/oracle/{ALPHA}").json()
        t3 = next(t for t in d["tasks"] if t["task_id"] == task_id(3))
        assert t3["strength"] == 0.9167 and t3["band"] == "strong" and t3["run_id"] == "2" * 32
        assert t3["capability_class"] == "bug.fix" and t3["size"] == "S"  # from the tasks table
        assert t3["errors"] == 1
        assert d["runs"] == [env.info.run_ids["oracle"], "2" * 32]
        bf = next(c for c in d["cells"] if c["capability_class"] == "bug.fix")
        assert bf["strength_mean"] == pytest.approx((0.9 + 0.5 + 0.9167) / 3, abs=1e-4)
        assert bf["band"] == "adequate"

    def test_empty_repo_and_404(self, env: Env) -> None:
        d = env.get(f"/oracle/{BETA}").json()
        assert d["tasks"] == [] and d["cells"] == [] and d["apparatus_versions"] == []
        r = env.get("/oracle/nope")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"

    def test_anonymous_401(self, env: Env) -> None:
        env.client.cookies.clear()
        assert env.get(f"/oracle/{ALPHA}").status_code == 401


class TestControls:
    def test_latest_report(self, env: Env) -> None:
        r = env.get(f"/oracle/{ALPHA}/controls")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["schema"] == "crb.negative_controls.v1" and d["passed"] is True
        assert d["violations"] == 0 and d["escapes"] == 1 and d["n_rows"] == 14
        assert d["escape_rows"][0]["control"] == "hardcode_cheat"
        assert d["escape_rows"][0]["verdict"] == "ESCAPE"
        assert d["run_id"] == env.info.run_ids["controls"] and d["reported_at"]

    def test_not_measured_404(self, env: Env) -> None:
        r = env.get(f"/oracle/{BETA}/controls")
        assert r.status_code == 404
        e = envelope(r)
        assert e["code"] == "not_measured" and e["detail"] == {"repo": BETA}
        assert env.get("/oracle/nope/controls").status_code == 404
        assert envelope(env.get("/oracle/nope/controls"))["code"] == "not_found"

    def test_admin_reads_too(self, env: Env) -> None:
        login(env.client, "admin")
        assert env.get(f"/oracle/{ALPHA}/controls").status_code == 200

    @pytest.mark.parametrize("stamp", ["controls.v2", "controls.v1", None])
    def test_a_passed_report_with_no_gold_witness_licenses_nothing(
        self, env: Env, stamp: str | None
    ) -> None:
        """P-176: a report written before ``controls.v3`` has no gold witness beside any catch,
        so its "caught" rows may be an environment that could not build. It is served as it
        was written, but routing reads it as unmeasured — re-run the controls — never as
        passed, whatever its counts say."""
        _controls_event(env, BETA, _passed_report(stamp))
        with env.factory() as s:
            v = latest_controls_verdict(s, BETA)
        assert v.measured is False and v.passed is False
        d = env.get(f"/oracle/{BETA}/controls").json()
        assert d["passed"] is True  # the report as it was written…
        assert d["verdict"]["state"] == "unmeasured"  # …licenses nothing
        assert env.get(f"/capability-map?repo={BETA}").json()["controls"]["state"] == "unmeasured"

    def test_a_witnessed_report_reads_as_written(self, env: Env) -> None:
        _controls_event(env, BETA, _passed_report(CONTROLS_VERSION))
        with env.factory() as s:
            v = latest_controls_verdict(s, BETA)
        assert v.measured is True and v.passed is True
        assert env.get(f"/oracle/{BETA}/controls").json()["verdict"]["state"] == "passed"

    @pytest.mark.parametrize(("witnessed", "measured"), [(False, False), (True, True)])
    def test_a_passed_run_is_read_only_when_its_counts_carry_the_witness(
        self, env: Env, witnessed: bool, measured: bool
    ) -> None:
        """The run fallback (a report event pruned): a controls run's counts carry
        ``witnessed`` from ``controls.v3``; counts without it are from before the witness."""
        counts: dict[str, Any] = {"tasks": 3, "total": 3, "rows": 21, "violations": 0}
        counts |= {"escapes": 0, "not_constructible": 0, "skipped": 0}
        counts |= {"passed": True, "complete": True}
        if witnessed:
            counts |= {"witnessed": 15, "witness_failures": 0, "controls_version": CONTROLS_VERSION}
        with env.factory() as s:
            s.add(
                Run(
                    id="8" * 32,
                    repo=BETA,
                    kind="controls",
                    status="succeeded",
                    actor="op1",
                    counts_json=counts,
                    created="2026-09-10T09:00:00+00:00",
                    finished="2026-09-10T09:20:00+00:00",
                )
            )
            s.commit()
            v = latest_controls_verdict(s, BETA)
        assert v.measured is measured and v.passed is measured


def _passed_report(stamp: str | None) -> dict[str, Any]:
    """A clean, passed ``controls.report`` payload stamped ``stamp`` (``None``: unstamped)."""
    apparatus: dict[str, Any] = {"apparatus_version": "2.3"}
    if stamp:
        apparatus["controls_version"] = stamp
    return {
        "schema": "crb.negative_controls.v1",
        "apparatus": apparatus,
        "n_tasks": 3,
        "n_rows": 21,
        "violations": 0,
        "escapes": 0,
        "not_constructible": 0,
        "skipped": 0,
        "passed": True,
        "escape_rows": [],
        "rows": [],
    }


def _controls_event(env: Env, repo: str, payload: dict[str, Any]) -> None:
    with env.factory() as s:
        s.add(
            event_to_model(
                StepEvent(
                    trace_id="9" * 32,
                    stage="oracle",
                    action="controls.report",
                    repo=repo,
                    seq=1,
                    payload=payload,
                )
            )
        )
        s.commit()
