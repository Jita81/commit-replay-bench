"""``/oracle/{repo}`` and ``/oracle/{repo}/controls`` — strength, band, gate; 404 not_measured."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.oracle.adequacy import DEFAULT_POLICY
from crb.observability.events import StepEvent
from crb.server.routes.runs import event_to_model
from fixtures.server_seed import ALPHA, BETA, Env, envelope, login, make_env, task_id


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
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
