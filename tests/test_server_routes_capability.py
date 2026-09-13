"""``/capability-map`` and ``/routes`` — honest cells, the one rule, sign-off overlay."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.ledger import CELL_FIELDS
from crb.core.routing import DEFAULT_POLICY
from crb.store.models import Grade
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, BETA, Env, envelope, login, make_env


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _cells(env: Env, query: str = "") -> dict[str, dict[str, object]]:
    r = env.get(f"/capability-map?repo={ALPHA}{query}")
    assert r.status_code == 200, r.text
    return {str(c["label"]): c for c in r.json()["cells"]}


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
        }
        assert body["repo"] == ALPHA and body["by"] == ["capability_class", "size"]
        assert body["classes"] == ["backend.route.add", "bug.fix", "test.add"]
        assert body["sizes"] == ["XS", "S", "M"]  # tier order, not alphabetical
        assert body["languages"] == ["python"]
        assert body["models"] == ["gpt-oss-120b", "sonnet"]
        assert body["policy"] == DEFAULT_POLICY.to_dict()
        labels = {c["label"] for c in body["cells"]}
        assert labels == {"backend.route.add|M", "bug.fix|S", "test.add|XS"}
        # NOT_YET_MEASURED cells are absent, never fabricated
        assert "docs.update|S" not in labels and "bug.fix|XL" not in labels
        for c in body["cells"]:
            assert c["n"] > 0 and c["route"] != "NOT_YET_MEASURED"
            assert set(c) >= {
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
                "verification_tier",
                "apparatus_versions",
                "belt_set",
            }
            assert c["capability_class"] != "*" and c["size"] != "*" and c["language"] == "*"

    def test_deliver_cell_is_routed_deliver(self, env: Env) -> None:
        c = _cells(env)["bug.fix|S"]
        assert c["n"] == 40 and c["clean"] == 38 and c["point"] == 0.95
        assert c["ci_low"] == pytest.approx(0.835, abs=0.001)
        assert c["route"] == "deliver" and c["false_q1"] == 0
        assert "n=40" in str(c["reason"]) and "false_q1=0" in str(c["reason"])
        assert c["verification_tier"] == "automated-pass"
        assert c["apparatus_versions"] == ["2.0"] and c["belt_set"] == "v4"
        assert c["cost_usd_mean"] == pytest.approx(0.012) and c["latency_s_mean"] == 42.0
        assert c["cost_known"] is True and c["oracle_strength_mean"] is None

    def test_thin_cell_calibrates(self, env: Env) -> None:
        c = _cells(env)["backend.route.add|M"]
        assert c["n"] == 4 and c["clean"] == 2 and c["errors"] == 1
        assert c["route"] == "calibrate" and "n=4 < 10" in str(c["reason"])

    def test_legacy_cell_is_a_separate_apparatus(self, env: Env) -> None:
        c = _cells(env)["test.add|XS"]
        assert c["belt_set"] == "v3-legacy" and c["belt_sets"] == ["v3-legacy"]
        assert c["apparatus_versions"] == ["1.0-census"]
        assert c["n"] == 6 and c["clean"] == 5 and c["route"] == "calibrate"
        assert c["cost_known"] is False and c["cost_usd_mean"] == 0.0

    def test_summary_without_profile(self, env: Env) -> None:
        s = env.get(f"/capability-map?repo={ALPHA}").json()["summary"]
        assert s["trusted_autonomy_coverage"] is None  # no profile → not fabricated
        assert s["earned_coverage"] is None and s["profile_commits"] is None
        assert s["measured_cells"] == 3 and s["deliver_cells"] == 1
        assert s["total_cells"] == 9  # 3 classes × 3 sizes seen
        assert s["cells_by_route"]["deliver"] == 1 and s["cells_by_route"]["calibrate"] == 2
        assert s["n_total"] == 50 and s["rows"] == 50 and s["false_q1_total"] == 0
        assert s["apparatus_versions"] == ["1.0-census", "2.0"]
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
        assert by_model["bug.fix|S|gpt-oss-120b"]["route"] == "deliver"
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
        assert env.get("/capability-map?repo=nope").status_code == 404
        assert env.get("/capability-map").status_code == 422

    def test_signoff_overlay_lifts_tier(self, env: Env) -> None:
        login(env.client, "approver")
        r = env.post(
            "/signoffs",
            json={
                "repo": ALPHA,
                "cell": {"capability_class": "bug.fix", "size": "S"},
                "note": "ok",
            },
        )
        assert r.status_code == 201, r.text
        cells = _cells(env)
        assert cells["bug.fix|S"]["verification_tier"] == "human-verified"
        assert cells["backend.route.add|M"]["verification_tier"] == "automated-pass"
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
        assert env.get(f"/capability-map?repo={BETA}").status_code == 200  # other repos unaffected

    def test_viewer_reads(self, env: Env) -> None:
        login(env.client, "viewer")
        assert env.get(f"/capability-map?repo={ALPHA}").status_code == 200
        assert env.get(f"/routes?repo={ALPHA}").status_code == 200


class TestRoutes:
    def test_decisions_per_full_cell(self, env: Env) -> None:
        r = env.get(f"/routes?repo={ALPHA}")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"repo", "by", "policy", "decisions"}
        assert body["by"] == list(CELL_FIELDS) and body["policy"]["version"] == "routing.v1"
        by_label = {d["label"]: d for d in body["decisions"]}
        deliver = by_label["replay|bug.fix|S|python|editblock|gpt-oss-120b|cerebras"]
        assert deliver["route"] == "deliver" and deliver["n"] == 40
        assert deliver["cell"] == env.info.deliver_cell
        assert deliver["point"] == 0.95 and deliver["ci_low"] == pytest.approx(0.835, abs=0.001)
        assert deliver["false_q1"] == 0 and deliver["policy_version"] == "routing.v1"
        assert deliver["verification_tier"] == "automated-pass"
        assert deliver["apparatus_versions"] == ["2.0"]
        legacy = by_label["replay|test.add|XS|python|claude-code-workflow|sonnet|anthropic"]
        assert legacy["route"] == "calibrate" and legacy["apparatus_versions"] == ["1.0-census"]
        assert set(by_label) == {
            "replay|backend.route.add|M|python|editblock|gpt-oss-120b|cerebras",
            "replay|bug.fix|S|python|editblock|gpt-oss-120b|cerebras",
            "replay|test.add|XS|python|claude-code-workflow|sonnet|anthropic",
        }

    def test_projection_and_empty(self, env: Env) -> None:
        r = env.get(f"/routes?repo={ALPHA}&by=class")
        assert r.json()["by"] == ["capability_class"]
        assert {d["label"] for d in r.json()["decisions"]} == {
            "backend.route.add",
            "bug.fix",
            "test.add",
        }
        assert env.get(f"/routes?repo={BETA}").json()["decisions"] == []
        assert env.get("/routes?repo=nope").status_code == 404
