"""``/forecast/build`` and ``/forecast/readiness`` — honest ex-ante numbers and the punch-list."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.server.routes.forecast import parse_mix
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, BETA, Env, envelope, login, make_env
from fixtures.signoff_seed import attested_body, pass_controls


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


class TestParseMix:
    def test_shapes(self) -> None:
        assert parse_mix("bug.fix:S:4,docs.update::1,test.add:2") == {
            ("bug.fix", "S"): 4,
            ("docs.update", ""): 1,
            ("test.add", ""): 2,
        }
        assert parse_mix("bug.fix:*:3, bug.fix:S:1 ,bug.fix:S:2") == {
            ("bug.fix", ""): 3,
            ("bug.fix", "S"): 3,
        }

    @pytest.mark.parametrize(
        "bad", ["", "bug.fix", "bug.fix:S:x", "bug.fix:S:-1", "bug.fix:XXL:1", "a:b:c:d", ":S:1"]
    )
    def test_malformed_422(self, bad: str) -> None:
        with pytest.raises(Exception) as exc:
            parse_mix(bad)
        assert getattr(exc.value, "status_code", None) == 422


class TestBuild:
    def test_forecast_shape_and_numbers(self, env: Env) -> None:
        r = env.get(
            f"/forecast/build?repo={ALPHA}&mix=bug.fix:S:4,backend.route.add:M:2,docs.update::1"
        )
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["repo"] == ALPHA
        assert f["mix"] == [
            {"capability_class": "bug.fix", "size": "S", "count": 4},
            {"capability_class": "backend.route.add", "size": "M", "count": 2},
            {"capability_class": "docs.update", "size": "", "count": 1},
        ]
        assert f["components"] == 7 and f["measured_components"] == 6
        assert f["unmeasured"] == ["docs.update"]  # never priced, never routed
        assert f["deliver"] == 4 and f["calibrate"] == 2 and f["human"] == 0
        assert f["units_by_route"]["not_yet_measured"] == 1
        # 6 costed units at $0.012 each; 42 s each → 4.2 min
        assert f["cost_usd_mean"] == pytest.approx(0.072) and f["cost_usd_std"] == 0.0
        assert f["costed_components"] == 6 and f["timed_components"] == 6
        assert f["minutes"] == pytest.approx(4.2)
        # p_clean: 4 × 0.95 + 2 × 0.5 = 4.8 of 6 → 0.8
        assert f["buildable_p"] == pytest.approx(0.8) and f[
            "expected_clean_units"
        ] == pytest.approx(4.8)
        assert f["buildable_p_stddev"] > 0 and f["single_rep_band"] is False
        assert f["coverage"] == pytest.approx(6 / 7, abs=1e-4)
        assert f["policy_version"] == "routing.v1"
        per = {c["component"]: c for c in f["per_component"]}
        assert per["bug.fix/S"]["route"] == "deliver" and per["bug.fix/S"]["n"] == 40
        assert per["bug.fix/S"]["config"] == "editblock/gpt-oss-120b@cerebras"
        assert per["bug.fix/S"]["unit_cost_usd"] == pytest.approx(0.012)
        assert per["docs.update"]["route"] == "not_yet_measured" and per["docs.update"]["n"] == 0
        assert per["docs.update"]["why"] == "no rows for this cell"
        assert per["backend.route.add/M"]["route"] == "calibrate"

    def test_errors(self, env: Env) -> None:
        r = env.get(f"/forecast/build?repo={ALPHA}&mix=bug.fix:S:x")
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"
        assert env.get(f"/forecast/build?repo={ALPHA}").status_code == 422
        assert env.get("/forecast/build?repo=nope&mix=bug.fix:S:1").status_code == 404
        r = env.get(f"/forecast/build?repo={BETA}&mix=bug.fix:S:1")
        assert r.status_code == 200 and r.json()["unmeasured"] == ["bug.fix/S"]

    def test_viewer_reads(self, env: Env) -> None:
        login(env.client, "viewer")
        assert env.get(f"/forecast/build?repo={ALPHA}&mix=bug.fix:S:1").status_code == 200
        env.client.cookies.clear()
        assert env.get(f"/forecast/build?repo={ALPHA}&mix=bug.fix:S:1").status_code == 401


class TestReadiness:
    def test_with_mix_not_ready_then_ready_after_signoff(self, env: Env) -> None:
        r = env.get(f"/forecast/readiness?repo={ALPHA}&mix=bug.fix:S:4,backend.route.add:M:1")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is False and d["mix_source"] == "mix"
        assert d["total"] == 5 and d["measured"] == 5 and d["coverage"] == 1.0
        assert d["false_q1_total"] == 0 and d["min_reps_seen"] == 4
        assert d["thresholds"]["max_false_q1"] == 0 and d["thresholds"]["version"] == "readiness.v1"
        gaps = "\n".join(d["gaps"])
        assert "under 5 trials" in gaps and "backend.route.add/M (n=4)" in gaps
        assert "not earned-trusted" in gaps and "bug.fix/S (automated-pass)" in gaps
        assert d["buildable_units"] == 4 and d["buildable_frac"] == 0.8  # ≥ 80%: no gap
        # sign off the deliver cell → the earned-tier gap for it closes. Under
        # signoff-policy.v1 that needs a clean controls gate (the seed's has an escape)
        # and an attestation naming an accepted row of the cell.
        login(env.client, "approver")
        pass_controls(env)
        cell = {"capability_class": "bug.fix", "size": "S"}
        assert (
            env.post("/signoffs", json=attested_body(env, cell, note="reviewed")).status_code == 201
        )
        d2 = env.get(f"/forecast/readiness?repo={ALPHA}&mix=bug.fix:S:4").json()
        assert d2["ok"] is True and d2["gaps"] == [] and d2["earned_units"] == 4
        assert d2["buildable_units"] == 4 and d2["buildable_frac"] == 1.0

    def test_unmeasured_mix(self, env: Env) -> None:
        d = env.get(f"/forecast/readiness?repo={ALPHA}&mix=docs.update:S:3").json()
        assert d["ok"] is False and d["measured"] == 0
        assert any("coverage 0%" in g and "docs.update/S" in g for g in d["gaps"])

    def test_without_mix_needs_profile(self, env: Env) -> None:
        r = env.get(f"/forecast/readiness?repo={ALPHA}")
        assert r.status_code == 409 and envelope(r)["code"] == "no_profile"

    def test_from_profile(self, tmp_path: Path) -> None:
        repo = pr.build(tmp_path / "pyrepo")
        with make_env(tmp_path, clone_path=str(repo.path)) as env:
            assert env.get(f"/repos/{ALPHA}/profile").status_code == 200
            d = env.get(f"/forecast/readiness?repo={ALPHA}").json()
            assert d["mix_source"] == "profile"
            assert d["mix"] == [{"capability_class": "bug.fix", "size": "XS", "count": 1}]
            assert d["ok"] is False and d["measured"] == 0  # bug.fix/XS is unmeasured here

    def test_errors(self, env: Env) -> None:
        assert env.get("/forecast/readiness?repo=nope").status_code == 404
        r = env.get(f"/forecast/readiness?repo={ALPHA}&mix=oops")
        assert r.status_code == 422
