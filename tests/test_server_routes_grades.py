"""``/grades``, ``/grades/{row_id}``, ``/tasks/{repo}/{task_id}``, ``/evidence/{hash}``."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from crb.core.ledger import GradeRow
from crb.core.version import APPARATUS_VERSION
from crb.store.models import Grade
from fixtures.server_seed import ALPHA, Env, envelope, login, make_env, task_id


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


class TestGrades:
    def test_list_in_chain_order_with_stored_fields(self, env: Env) -> None:
        r = env.get("/grades?limit=500")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 50 and len(body["items"]) == 50
        seqs = [g["seq"] for g in body["items"]]
        assert seqs == sorted(seqs)
        first = body["items"][0]
        # exactly GradeRow.to_dict() + seq
        assert set(first) == set(GradeRow.__dataclass_fields__) | {"seq"}
        assert first["schema"] == "crb.grade.v2" and first["belt_set"] == "v5"
        assert first["prev_hash"] == "0" * 64 and len(first["row_hash"]) == 64
        # every row round-trips into a GradeRow that verifies its own hash
        prev = "0" * 64
        for g in body["items"]:
            row = GradeRow.from_dict(g)
            assert row.verify_hash() and row.prev_hash == prev
            prev = row.row_hash

    def test_filters(self, env: Env) -> None:
        assert env.get("/grades?clean=false").json()["total"] == 5
        assert env.get("/grades?clean=true").json()["total"] == 45
        assert env.get(f"/grades?task_id={task_id(3)}").json()["total"] == 11
        assert env.get("/grades?builder=claude-code-workflow").json()["total"] == 6
        assert env.get("/grades?belt_set=v3-legacy").json()["total"] == 6
        assert env.get("/grades?capability_class=bug.fix&size=S").json()["total"] == 40
        assert env.get("/grades?language=python&mode=sighted").json()["total"] == 50
        assert env.get("/grades?model=gpt-oss-120b&provider=cerebras").json()["total"] == 44
        assert env.get(f"/grades?run_id={env.info.run_ids['succeeded']}").json()["total"] == 5
        assert env.get("/grades?repo=beta").json()["total"] == 0
        assert env.get("/grades?pool=hard").json()["total"] == 2
        assert env.get("/grades?disqualified=true").json()["total"] == 0

    def test_pagination(self, env: Env) -> None:
        page = env.get("/grades?limit=10&offset=45").json()
        assert page["total"] == 50 and len(page["items"]) == 5
        assert page["limit"] == 10 and page["offset"] == 45
        assert page["items"][0]["seq"] == 46

    def test_get_one_and_404(self, env: Env) -> None:
        row = env.info.rows[0]
        r = env.get(f"/grades/{row.row_id}")
        assert r.status_code == 200
        assert r.json()["row_hash"] == row.row_hash and r.json()["task_id"] == row.task_id
        r = env.get("/grades/nope")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"

    def test_viewer_reads_anonymous_401(self, env: Env) -> None:
        login(env.client, "viewer")
        assert env.get("/grades").status_code == 200
        env.client.cookies.clear()
        assert env.get("/grades").status_code == 401

    def test_audit_surface_shows_a_false_q1_row(self, env: Env) -> None:
        """A row that bypassed the write path (ORM insert) is visible here — the auditor must
        see it — while the reducing routes refuse it (409)."""
        with env.factory() as s:
            s.execute(text("DROP TRIGGER grades_no_update"))
            s.execute(
                text("UPDATE grades SET target_green = 0 WHERE seq = 1")
            )  # tamper: clean stays True
            s.commit()
        r = env.get("/grades?limit=1")
        assert r.status_code == 200
        g = r.json()["items"][0]
        assert g["clean"] is True and g["target_green"] is False
        assert env.get("/ledger/verify").json()["false_q1_total"] == 1
        r = env.get(f"/capability-map?repo={ALPHA}")
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"


class TestTaskDetail:
    def test_spec_and_grades(self, env: Env) -> None:
        r = env.get(f"/tasks/{ALPHA}/{task_id(3)}")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"spec", "grades"}
        assert (
            body["spec"]["task_id"] == task_id(3) and body["spec"]["capability_class"] == "bug.fix"
        )
        assert body["spec"]["gold_clean"] is True and body["spec"]["belt_scope"] == ["tests/"]
        assert len(body["grades"]) == 11
        assert [g["trial"] for g in body["grades"][:2]] == ["r1", "r2"]
        assert body["grades"][0]["clean"] is False and body["grades"][1]["clean"] is True

    def test_404(self, env: Env) -> None:
        assert env.get(f"/tasks/{ALPHA}/{'0' * 40}").status_code == 404
        assert env.get(f"/tasks/beta/{task_id(1)}").status_code == 404


class TestEvidence:
    def test_native_pack_verified(self, env: Env) -> None:
        row = env.info.rows[0]
        r = env.get(f"/evidence/{row.evidence_pack_hash}")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {
            "pack",
            "verified",
            "pack_hash",
            "schema",
            "repo",
            "task_id",
            "run_id",
            "created",
        }
        assert body["verified"] is True and body["schema"] == "crb.evidence.v1"
        pack = body["pack"]
        assert pack["pack_hash"] == row.evidence_pack_hash
        assert pack["task"]["task_id"] == row.task_id
        assert pack["grade"]["clean"] is True and pack["grade"]["target_green"] is True
        assert pack["apparatus"]["apparatus_version"] == APPARATUS_VERSION
        assert pack["builder"]["model"] == "gpt-oss-120b"
        assert body["repo"] == ALPHA and body["task_id"] == row.task_id

    def test_imported_pack_verified(self, env: Env) -> None:
        legacy = next(r for r in env.info.rows if r.belt_set == "v3-legacy")
        r = env.get(f"/evidence/{legacy.evidence_pack_hash}")
        assert r.status_code == 200
        assert r.json()["verified"] is True and r.json()["schema"] == "crb.evidence.imported.v1"
        assert r.json()["pack"]["row"]["task"] == legacy.task_id

    def test_tampered_pack_not_verified(self, env: Env) -> None:
        row = env.info.rows[1]
        with env.factory() as s:
            s.execute(text("DROP TRIGGER evidence_no_update"))
            s.execute(
                text(
                    "UPDATE evidence SET body_json = json_set(body_json, '$.actor', 'mallory') WHERE pack_hash = :h"
                ),
                {"h": row.evidence_pack_hash},
            )
            s.commit()
        r = env.get(f"/evidence/{row.evidence_pack_hash}")
        assert r.status_code == 200 and r.json()["verified"] is False

    def test_404(self, env: Env) -> None:
        r = env.get(f"/evidence/{'f' * 64}")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"

    def test_every_clean_row_has_a_resolvable_pack(self, env: Env) -> None:
        with env.factory() as s:
            hashes = {g.evidence_pack_hash for g in s.query(Grade).filter(Grade.clean.is_(True))}
        assert "" not in hashes
        for h in sorted(hashes)[:5]:
            assert env.get(f"/evidence/{h}").json()["verified"] is True
