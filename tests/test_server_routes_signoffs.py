"""``/signoffs`` — earned tiers: 201 on evidence, 409 on false-Q1 or no evidence, revoke, chain."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.server.routes.runs import system_trace_id
from crb.server.routes.signoffs import signoff_hash, verify_signoff_rows
from crb.store.models import Event, Grade, Signoff
from fixtures.server_seed import ALPHA, BETA, Env, assert_rbac, envelope, login, make_env

DELIVER = {"capability_class": "bug.fix", "size": "S"}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
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


class TestCreate:
    def test_rbac_is_approver(self, env: Env) -> None:
        assert_rbac(
            env, "POST", "/signoffs", min_role="approver", json={"repo": ALPHA, "cell": DELIVER}
        )

    def test_201_on_the_deliver_cell(self, env: Env) -> None:
        r = env.post(
            "/signoffs", json={"repo": ALPHA, "cell": DELIVER, "note": "reviewed 40 packs"}
        )
        assert r.status_code == 201, r.text
        d = r.json()
        assert set(d) == {
            "id",
            "repo",
            "cell",
            "tier",
            "note",
            "approver",
            "created",
            "revoked",
            "revoked_by",
            "revoked_at",
            "active",
            "current_false_q1",
            "evidence",
            "prev_hash",
            "row_hash",
        }
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
        assert d["evidence"]["n"] == 40 and d["evidence"]["point"] == 0.95
        assert d["evidence"]["ci_low"] == pytest.approx(0.835, abs=0.001)
        assert d["evidence"]["false_q1"] == 0 and d["evidence"]["apparatus_versions"] == ["2.0"]
        assert d["prev_hash"] == GENESIS_HASH and len(d["row_hash"]) == 64
        assert d["approver"]  # the approver's principal id
        # persisted, chained, evidence snapshot covered by the hash
        rows = _signoffs(env)
        assert len(rows) == 1 and rows[0].row_hash == signoff_hash(rows[0])
        assert rows[0].evidence_rows == 40 and rows[0].cell_json["evidence_n"] == "40"
        assert verify_signoff_rows(rows) == 1
        # ... and recorded as a system event on the repo's sign-off trace
        with env.factory() as s:
            ev = s.execute(
                select(Event).where(Event.trace_id == system_trace_id("signoffs", ALPHA))
            ).scalar_one()
        assert ev.action == "signoff.created" and ev.payload_json["n"] == 40

    def test_full_cell_scope_and_second_attestation_chains(self, env: Env) -> None:
        r1 = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER})
        r2 = env.post(
            "/signoffs",
            json={
                "repo": ALPHA,
                "cell": env.info.deliver_cell,
                "note": "full cell",
                "tier": "ab-confirmed",
            },
        )
        assert r1.status_code == 201 and r2.status_code == 201, r2.text
        assert r2.json()["prev_hash"] == r1.json()["row_hash"]
        assert r2.json()["tier"] == "ab-confirmed" and r2.json()["cell"] == env.info.deliver_cell
        assert verify_signoff_rows(_signoffs(env)) == 2
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 2

    def test_409_unmeasured_cell(self, env: Env) -> None:
        r = env.post(
            "/signoffs",
            json={"repo": ALPHA, "cell": {"capability_class": "docs.update", "size": "S"}},
        )
        assert r.status_code == 409
        e = envelope(r)
        assert e["code"] == "false_q1_refused" and e["detail"]["reason"] == "not_measured"
        assert e["detail"]["cell"]["capability_class"] == "docs.update"
        assert _signoffs(env) == []
        r = env.post("/signoffs", json={"repo": BETA, "cell": DELIVER})
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"

    def test_409_false_q1_row_inserted_around_the_ledger(self, env: Env) -> None:
        bad = _seed_false_q1_row(env)
        r = env.post(
            "/signoffs",
            json={"repo": ALPHA, "cell": {"capability_class": "docs.update", "size": "S"}},
        )
        assert r.status_code == 409, r.text
        e = envelope(r)
        assert e["code"] == "false_q1_refused"
        assert e["detail"]["false_q1"] == 1 and e["detail"]["rows"] == [bad]
        assert "false_q1=1" in e["message"]
        assert _signoffs(env) == []  # nothing written
        # the refusal is on the record
        with env.factory() as s:
            ev = s.execute(
                select(Event).where(Event.trace_id == system_trace_id("signoffs", ALPHA))
            ).scalar_one()
        assert ev.action == "signoff.refused" and ev.status == "invalid"
        assert ev.payload_json["rows"] == [bad]
        # the unaffected deliver cell can still be signed (the check is scoped to the cell)
        assert env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER}).status_code == 201

    def test_read_time_check_invalidates_a_signed_cell(self, env: Env) -> None:
        assert env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER}).status_code == 201
        _seed_false_q1_row(env, cls="bug.fix", size="S")  # the same cell, after the fact
        item = env.get(f"/signoffs?repo={ALPHA}&include_revoked=true").json()["items"][0]
        assert item["revoked"] is False
        assert item["current_false_q1"] == 1 and item["active"] is False  # self-healed
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 1  # listed, flagged
        # and a new attestation on that cell is refused
        r = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER})
        assert r.status_code == 409 and envelope(r)["detail"]["false_q1"] == 1

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
        ],
    )
    def test_422(self, env: Env, body: dict[str, Any]) -> None:
        r = env.post("/signoffs", json=body)
        assert r.status_code == 422, r.text
        assert envelope(r)["code"] == "validation_error"

    def test_unknown_repo_404(self, env: Env) -> None:
        assert env.post("/signoffs", json={"repo": "nope", "cell": DELIVER}).status_code == 404

    def test_note_is_redacted(self, env: Env) -> None:
        r = env.post(
            "/signoffs",
            json={
                "repo": ALPHA,
                "cell": DELIVER,
                "note": "key sk-live-abcdefghijklmnopqrstuvwxyz0123",
            },
        )
        assert r.status_code == 201 and "sk-live" not in r.json()["note"]


class TestListAndRevoke:
    def test_list_active_and_history(self, env: Env) -> None:
        assert env.get("/signoffs").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
        sid = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER}).json()["id"]
        login(env.client, "viewer")
        page = env.get(f"/signoffs?repo={ALPHA}").json()
        assert page["total"] == 1 and page["items"][0]["id"] == sid
        assert env.get("/signoffs").json()["total"] == 1
        assert env.get(f"/signoffs?repo={BETA}").json()["total"] == 0

    def test_revoke_rbac(self, env: Env) -> None:
        sid = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER}).json()["id"]
        assert_rbac(env, "POST", f"/signoffs/{sid}/revoke", min_role="approver")

    def test_revoke_appends_and_hides(self, env: Env) -> None:
        sid = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER}).json()["id"]
        assert (
            env.get(f"/capability-map?repo={ALPHA}").json()["cells"][1]["verification_tier"]
            == "human-verified"
        )
        r = env.post(f"/signoffs/{sid}/revoke", json={"note": "evidence re-examined"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["id"] == sid and d["revoked"] is True and d["active"] is False
        assert d["revoked_by"] and d["revoked_at"]
        rows = _signoffs(env)
        assert [x.revoke for x in rows] == [False, True]
        assert rows[1].prev_hash == rows[0].row_hash and rows[1].note == "evidence re-examined"
        assert verify_signoff_rows(rows) == 2
        # hidden from the active list, present in the history, tier back to automated-pass
        assert env.get(f"/signoffs?repo={ALPHA}").json()["total"] == 0
        hist = env.get(f"/signoffs?repo={ALPHA}&include_revoked=true").json()
        assert hist["total"] == 1 and hist["items"][0]["revoked"] is True
        assert (
            env.get(f"/capability-map?repo={ALPHA}").json()["cells"][1]["verification_tier"]
            == "automated-pass"
        )
        # twice → 409; unknown → 404; the revocation row itself is not an attestation id
        r = env.post(f"/signoffs/{sid}/revoke")
        assert r.status_code == 409 and envelope(r)["code"] == "already_revoked"
        assert env.post("/signoffs/nope/revoke").status_code == 404
        assert env.post(f"/signoffs/{rows[1].signoff_id}/revoke").status_code == 404

    def test_re_attest_after_revoke(self, env: Env) -> None:
        sid = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER}).json()["id"]
        env.post(f"/signoffs/{sid}/revoke")
        r = env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER, "note": "again"})
        assert r.status_code == 201 and r.json()["active"] is True
        page = env.get(f"/signoffs?repo={ALPHA}").json()
        assert page["total"] == 1 and page["items"][0]["note"] == "again"
        assert verify_signoff_rows(_signoffs(env)) == 3

    def test_chain_detects_tampering(self, env: Env) -> None:
        env.post("/signoffs", json={"repo": ALPHA, "cell": DELIVER})
        env.post("/signoffs", json={"repo": ALPHA, "cell": env.info.deliver_cell})
        with env.factory() as s:
            s.execute(text("DROP TRIGGER signoffs_no_update"))
            s.execute(text("UPDATE signoffs SET note = 'edited' WHERE seq = 1"))
            s.commit()
        with pytest.raises(LedgerIntegrityError, match="sign-off 1"):
            verify_signoff_rows(_signoffs(env))
