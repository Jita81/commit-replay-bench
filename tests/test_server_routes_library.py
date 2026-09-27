"""``/library`` over HTTP: propose as a sponsor, sign as a second person, read the work-type page.

Navigation
----------
What it is:   Route tests of ``crb.server.routes.library`` on the seeded test app.
What it does: Walks an entry from proposal (an operator, who becomes its sponsor) to signature
              (an approver who is not the sponsor), and pins the refusals: the sponsor
              signing their own entry (409 ``same_person``), a signature on a version that
              is no longer current, an invalid statement (422); the role gates of every act;
              the event each act writes with its actor and target; staleness from a changed
              file; revocation and retirement by appending; the page per work type — its
              definition, what a ticket must carry, the signed context with sponsor, signer
              and ``unmeasured`` effect, "no proven standard" per size with the next
              measurement, a proven standard through the reader seam, and the quality section
              through the table seam — and that nothing is served as reaching a brief.
How:          ``fixtures.server_seed.make_env`` (SQLite, the four role accounts, the ``alpha``
              repository and its mined tasks) and ``login`` per role.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/server/routes/library.py (the routes under test),
              src/crb/store/library.py (the ledger they write), src/crb/core/library.py (the
              rule they apply), tests/fixtures/server_seed.py (the accounts and the
              repository), docs/API.md#library (the contract the bodies are held to)
Tested by:    this file
Touch when:   never for a new repository; a route, a field or an act of ``/library``
              changes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.library import ProvenStandard
from crb.server.routes import library as library_routes
from crb.store.models import Event
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, login, logout, make_env, user_id

ENTRY = {
    "kind": "convention",
    "slug": "errors-wrap",
    "title": "Wrap errors with context",
    "statement": "Every returned error is wrapped with fmt.Errorf and %w, naming the operation.",
    "work_types": ["bug.fix"],
}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, role="operator") as e:
        yield e


def _as(env: Env, role: str) -> None:
    logout(env.client)
    login(env.client, role)


def _propose(env: Env, **over: Any) -> dict[str, Any]:
    r = env.post(f"/library/{ALPHA}/entries", json={**ENTRY, **over})
    assert r.status_code == 201, r.text
    return dict(r.json())


def _events(env: Env) -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(select(Event).where(Event.action.like("library.%")).order_by(Event.id))
            .scalars()
            .all()
        )


def test_an_operator_proposes_and_sponsors_and_a_second_person_signs(env: Env) -> None:
    proposed = _propose(env)
    assert proposed["status"] == "proposed"
    assert proposed["sponsor"] == user_id("op1") and proposed["sponsor_name"] == "op1"
    assert proposed["entry"]["provenance"]["kind"] == "person"
    assert proposed["effect"] == "unmeasured" and proposed["evidence"] == "advisory"
    _as(env, "approver")
    r = env.post(
        f"/library/{ALPHA}/entries/convention/errors-wrap/sign",
        json={"version": proposed["version"]},
    )
    assert r.status_code == 200, r.text
    signed = r.json()
    assert signed["status"] == "signed"
    assert (signed["approver"], signed["approver_name"]) == (user_id("appr1"), "appr1")
    actions = [(e.action, e.actor, e.payload_json["entry_id"]) for e in _events(env)]
    assert actions == [
        ("library.proposed", user_id("op1"), "convention/errors-wrap"),
        ("library.signed", user_id("appr1"), "convention/errors-wrap"),
    ]
    index = env.get(f"/library/{ALPHA}").json()
    assert [e["entry_id"] for e in index["entries"]] == ["convention/errors-wrap"]
    assert index["reaches_briefs"] is False and index["statement_max"] == 400
    assert env.get("/library/verify").json() == {"ok": True, "acts": 2, "error": ""}


def test_the_sponsor_can_never_sign_their_own_entry(env: Env) -> None:
    _as(env, "admin")
    proposed = _propose(env)
    r = env.post(
        f"/library/{ALPHA}/entries/convention/errors-wrap/sign",
        json={"version": proposed["version"]},
    )
    assert r.status_code == 409, r.text
    err = envelope(r)
    assert (err["code"], err["detail"]["code"]) == ("library_refused", "same_person")
    assert "second person" in err["message"]
    state = env.get(f"/library/{ALPHA}").json()["entries"][0]
    assert state["status"] == "proposed" and state["approver"] == ""
    refused = [e for e in _events(env) if e.action == "library.refused"]
    assert len(refused) == 1 and refused[0].actor == user_id("root")
    assert refused[0].payload_json["code"] == "same_person"


def test_a_signature_on_a_version_that_is_no_longer_current_is_refused(env: Env) -> None:
    first = _propose(env)
    _propose(env, statement=ENTRY["statement"] + " Always.")
    _as(env, "approver")
    r = env.post(
        f"/library/{ALPHA}/entries/convention/errors-wrap/sign", json={"version": first["version"]}
    )
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "version_mismatch"


def test_an_invalid_entry_is_a_422_that_names_the_rule(env: Env) -> None:
    r = env.post(f"/library/{ALPHA}/entries", json={**ENTRY, "statement": "x" * 401})
    assert r.status_code == 422
    r = env.post(f"/library/{ALPHA}/entries", json={**ENTRY, "kind": "standard", "slug": "s"})
    assert r.status_code == 422 and "characteristic it refines" in envelope(r)["message"]
    r = env.post(f"/library/{ALPHA}/entries", json={**ENTRY, "slug": "Bad Slug"})
    assert r.status_code == 422
    assert env.post("/library/nope/entries", json=ENTRY).status_code == 404


def test_every_act_is_gated_by_role(env: Env) -> None:
    proposed = _propose(env)
    base = f"/library/{ALPHA}/entries/convention/errors-wrap"
    assert_rbac(env, "GET", f"/library/{ALPHA}", min_role="viewer")
    assert_rbac(env, "GET", f"/library/{ALPHA}/work-types/bug.fix", min_role="viewer")
    assert_rbac(env, "GET", "/library/verify", min_role="viewer")
    assert_rbac(env, "POST", f"/library/{ALPHA}/entries", min_role="operator", json=ENTRY)
    assert_rbac(env, "POST", f"{base}/sponsor", min_role="operator", json={"version": "0" * 64})
    assert_rbac(
        env, "POST", f"{base}/sign", min_role="approver", json={"version": proposed["version"]}
    )
    assert_rbac(env, "POST", f"{base}/revoke", min_role="approver", json={"reason": "x"})
    assert_rbac(
        env,
        "POST",
        f"/library/{ALPHA}/freshness",
        min_role="operator",
        json={"head_commit": "1" * 40, "digests": {}},
    )


def test_revocation_and_retirement_are_appended_with_their_reasons(env: Env) -> None:
    proposed = _propose(env)
    _propose(env, slug="second")
    _as(env, "approver")
    base = f"/library/{ALPHA}/entries/convention"
    env.post(f"{base}/errors-wrap/sign", json={"version": proposed["version"]})
    r = env.post(f"{base}/errors-wrap/revoke", json={"reason": "superseded by a decision"})
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert r.json()["revoked"]["reason"] == "superseded by a decision"
    r = env.post(f"{base}/errors-wrap/sign", json={"version": proposed["version"]})
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "already_final"
    r = env.post(f"{base}/second/retire", json={"reason": "no longer true"})
    assert r.status_code == 200 and r.json()["retired"]["by"] == "person"
    assert env.post(f"{base}/missing/retire", json={"reason": "x"}).status_code == 404
    acts = [e.action for e in _events(env) if e.action != "library.refused"]
    assert acts[-2:] == ["library.revoked", "library.retired"]


def test_an_entry_read_from_a_file_goes_stale_when_the_head_changes(env: Env) -> None:
    prov = {"kind": "file", "path": ".golangci.yml", "commit": "1" * 40, "digest": "d" * 64}
    proposed = _propose(env, slug="lint", provenance=prov, check="golangci-lint")
    assert proposed["entry"]["provenance"]["path"] == ".golangci.yml"
    _as(env, "approver")
    env.post(
        f"/library/{ALPHA}/entries/convention/lint/sign", json={"version": proposed["version"]}
    )
    _as(env, "operator")
    same = env.post(
        f"/library/{ALPHA}/freshness",
        json={"head_commit": "2" * 40, "digests": {".golangci.yml": "d" * 64}},
    )
    assert same.json()["stale"] == []
    changed = env.post(
        f"/library/{ALPHA}/freshness",
        json={"head_commit": "2" * 40, "digests": {".golangci.yml": "e" * 64}},
    )
    assert changed.json()["stale"] == ["convention/lint"]
    entry = env.get(f"/library/{ALPHA}").json()["entries"][0]
    assert entry["status"] == "stale" and entry["stale"]["head_commit"] == "2" * 40
    assert [e.action for e in _events(env)][-1] == "library.stale"


def test_the_work_type_page_shows_what_it_is_what_a_ticket_carries_and_signed_context(
    env: Env,
) -> None:
    proposed = _propose(env)
    _propose(env, slug="unsigned")
    _as(env, "approver")
    env.post(
        f"/library/{ALPHA}/entries/convention/errors-wrap/sign",
        json={"version": proposed["version"]},
    )
    page = env.get(f"/library/{ALPHA}/work-types/bug.fix").json()
    assert page["definition"].startswith("Repairs a defect") and page["parent_class"] == "bug.fix"
    assert page["examples"], "the page names example commits of this kind"
    assert {s["name"] for s in page["ticket_slots"]}, "readiness's slots for the class"
    [ctx] = page["context"]  # the unsigned entry is never signed context
    assert (ctx["entry_id"], ctx["sponsor_name"], ctx["approver_name"]) == (
        "convention/errors-wrap",
        "op1",
        "appr1",
    )
    assert ctx["effect"] == "unmeasured" and ctx["signed_at"]
    assert ctx["provenance_label"] == "written by a person"
    assert all(s["standard"] is None and "Register a reading" in s["next"] for s in page["sizes"])
    assert page["reaches_briefs"] is False
    assert "target_green" in page["quality"]["switched_on"]
    r = env.get(f"/library/{ALPHA}/work-types/not-a-type")
    assert r.status_code == 404


def test_the_page_reads_a_proven_standard_and_the_quality_table_through_their_seams(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reader(repo: str, cls: str, size: str) -> ProvenStandard | None:
        return (
            ProvenStandard("S3", 20, 20, 0.839, 1.0, "2.4", ceiling=True) if size == "XS" else None
        )

    class Ev:
        check, label, sub, runs = "target_green", "belt 2", "functional correctness", "always"

    class Ch:
        name, counted, note = "Functional suitability", (Ev(),), ""

    monkeypatch.setattr(library_routes, "STANDARD_READER", [reader])
    monkeypatch.setattr(library_routes, "quality_model", lambda: (Ch(),))
    page = env.get(f"/library/{ALPHA}/work-types/bug.fix").json()
    xs = page["sizes"][0]
    assert xs["standard"]["arm"] == "S3" and xs["standard"]["ceiling"] is True
    assert (xs["standard"]["n"], xs["standard"]["apparatus"]) == (20, "2.4")
    assert page["quality"]["served"] is True
    [row] = page["quality"]["rows"]
    assert row["characteristic"] == "Functional suitability" and row["evidenced"] is True


def test_the_quality_table_seam_reads_stream_cs_module_or_says_it_is_absent() -> None:
    try:
        import crb.core.quality_model as qm  # type: ignore[import-not-found,unused-ignore]
    except ModuleNotFoundError:
        assert library_routes.quality_model() is None
        return
    assert library_routes.quality_model() == tuple(qm.QUALITY_MODEL)
