"""``/library`` over HTTP: propose as a sponsor, sign as a second person, read the work-type page.

Navigation
----------
What it is:   Route tests of ``crb.server.routes.library`` on the seeded test app.
What it does: Walks an entry from proposal (an operator, who becomes its sponsor) to signature
              (an approver who is not the sponsor), and pins the refusals: the sponsor
              signing their own entry (409 ``same_person``), a signature on a version that
              is no longer current, an invalid statement (422), a credential in any field
              (422, nothing written), rows the ledger does not hold (422) and an approver who
              produced the cited rows (409 ``same_actor``); the role gate of every route of the
              router; every ``library.*`` event the routes write, with its actor and target;
              409 ``library_integrity`` when the acts no longer fold; staleness from a changed
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

import ast
import importlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from crb.core.library import LibraryAct, LibraryEntry, Provenance, ProvenStandard
from crb.server.routes import library as library_routes
from crb.store.library import DbLibraryLedger, new_act
from crb.store.models import Event, Grade, LibraryActRow, Run
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


def _library_routes() -> list[APIRoute]:
    return [r for r in library_routes.router.routes if isinstance(r, APIRoute)]


def _template(method: str, path: str) -> tuple[str, str]:
    """The route a request reaches, matched in the router's own order."""
    for r in _library_routes():
        if method in r.methods and r.path_regex.match(path):
            return method, r.path
    raise AssertionError(f"no library route serves {method} {path}")


def test_every_act_is_gated_by_role(env: Env) -> None:
    """Each route's role gate, and — P-183 — every route of the router is probed: the retire
    route's gate once went untested because this list was typed by hand."""
    probed: set[tuple[str, str]] = set()

    def probe(method: str, path: str, *, min_role: str, json: Any = None) -> None:
        assert_rbac(env, method, path, min_role=min_role, json=json)
        probed.add(_template(method, path))

    proposed = _propose(env)
    _propose(env, slug="to-retire")
    base = f"/library/{ALPHA}/entries/convention/errors-wrap"
    probe("GET", f"/library/{ALPHA}", min_role="viewer")
    probe("GET", f"/library/{ALPHA}/work-types/bug.fix", min_role="viewer")
    probe("GET", "/library/verify", min_role="viewer")
    probe("POST", f"/library/{ALPHA}/entries", min_role="operator", json=ENTRY)
    probe("POST", f"{base}/sponsor", min_role="operator", json={"version": "0" * 64})
    probe("POST", f"{base}/sign", min_role="approver", json={"version": proposed["version"]})
    probe("POST", f"{base}/revoke", min_role="approver", json={"reason": "x"})
    probe(
        "POST",
        f"/library/{ALPHA}/entries/convention/to-retire/retire",
        min_role="approver",
        json={"reason": "x"},
    )
    probe(
        "POST",
        f"/library/{ALPHA}/freshness",
        min_role="operator",
        json={"head_commit": "1" * 40, "digests": {}},
    )
    assert probed == {(m, r.path) for r in _library_routes() for m in r.methods}


def _mined(env: Env, slug: str = "adr-0001") -> tuple[LibraryEntry, str]:
    prov = Provenance(kind="file", path="docs/adr/0001.md", commit="1" * 40, digest="d" * 64)
    e = LibraryEntry(
        repo=ALPHA, kind="decision", slug=slug, title="Record decisions",
        statement="Every architectural decision is an ADR under docs/adr.",
        provenance=prov, proposed_by="mined:adr@1",
    )  # fmt: skip
    DbLibraryLedger(env.factory).append(
        new_act(ALPHA, e.entry_id, e.version, "propose", "mined:adr@1", body={"entry": e.content()})
    )
    return e, e.version


def test_an_operator_sponsors_a_mined_proposal_and_a_second_person_signs_it(env: Env) -> None:
    e, version = _mined(env)
    r = env.post(f"/library/{ALPHA}/entries/decision/adr-0001/sponsor", json={"version": version})
    assert r.status_code == 200, r.text
    assert (r.json()["sponsor"], r.json()["sponsor_name"]) == (user_id("op1"), "op1")
    [ev] = [x for x in _events(env) if x.action == "library.sponsored"]
    assert (ev.actor, ev.payload_json["entry_id"]) == (user_id("op1"), e.entry_id)
    _as(env, "approver")
    r = env.post(f"/library/{ALPHA}/entries/decision/adr-0001/sign", json={"version": version})
    assert r.status_code == 200 and r.json()["status"] == "signed"


def test_every_act_writes_its_event_naming_the_actor_and_the_entry(env: Env) -> None:
    """P-183: every ``library.*`` event the routes write is produced here, by the act that
    writes it, naming the actor and the entry — a renamed or dropped event fails."""
    tree = ast.parse(Path(library_routes.__file__).read_text(encoding="utf-8"))
    written = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n.value.startswith("library.") and n.value.count(".") == 1
    }  # fmt: skip
    _e, version = _mined(env)
    _mined(env, slug="adr-0002")
    env.post(f"/library/{ALPHA}/entries/decision/adr-0001/sponsor", json={"version": version})
    prov = {"kind": "file", "path": ".golangci.yml", "commit": "1" * 40, "digest": "d" * 64}
    lint = _propose(env, slug="lint", provenance=prov)
    _propose(env, slug="gone")
    _as(env, "approver")
    base = f"/library/{ALPHA}/entries"
    env.post(f"{base}/convention/lint/sign", json={"version": lint["version"]})
    env.post(f"{base}/decision/adr-0001/sign", json={"version": "0" * 64})  # refused
    env.post(f"{base}/convention/gone/revoke", json={"reason": "wrong"})
    env.post(f"{base}/decision/adr-0002/retire", json={"reason": "superseded"})
    env.post(f"/library/{ALPHA}/freshness",
             json={"head_commit": "2" * 40, "digests": {".golangci.yml": "e" * 64}})  # fmt: skip
    events = _events(env)
    assert {e.action for e in events} == written, written
    for ev in events:
        assert ev.actor and ev.payload_json["entry_id"], ev.action


def test_acts_that_no_longer_fold_answer_409_library_integrity(env: Env) -> None:
    proposed = _propose(env)
    forged = LibraryAct(
        act_id="f" * 32,
        repo=ALPHA,
        entry_id="convention/errors-wrap",
        version=proposed["version"],
        act="sign",
        actor=user_id("op1"),
        created="2026-09-28T10:00:00+00:00",
    ).chained(DbLibraryLedger(env.factory).acts()[-1].row_hash)  # the sponsor signs: refused
    with env.factory() as s:
        s.add(LibraryActRow(
            act_id=forged.act_id, schema=forged.schema, repo=forged.repo,
            entry_id=forged.entry_id, version=forged.version, act=forged.act,
            actor=forged.actor, body_json={}, created=forged.created,
            prev_hash=forged.prev_hash, row_hash=forged.row_hash,
        ))  # fmt: skip
        s.commit()
    assert env.get("/library/verify").json()["ok"] is True  # the chain holds; the rule does not
    for path in (f"/library/{ALPHA}", f"/library/{ALPHA}/work-types/bug.fix"):
        r = env.get(path)
        assert r.status_code == 409, (path, r.text)
        assert envelope(r)["code"] == "library_integrity"


TOKEN = "ghp_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8"


@pytest.mark.parametrize(
    "over",
    [
        {"provenance": {"kind": "file", "path": f"cfg/{TOKEN}.yml", "commit": "1" * 40,
                        "digest": "d" * 64}},
        {"check": TOKEN},
        {"components": [TOKEN]},
        {"work_types": [TOKEN]},
    ],
)  # fmt: skip
def test_a_credential_in_any_field_is_refused_and_nothing_is_written(
    env: Env, over: dict[str, Any]
) -> None:
    r = env.post(f"/library/{ALPHA}/entries", json={**ENTRY, **over})
    assert r.status_code == 422, r.text
    assert TOKEN not in r.text and "credential" in envelope(r)["message"]
    assert env.get(f"/library/{ALPHA}").json()["entries"] == []


def test_a_freshness_reading_names_hex_commits_and_digests(env: Env) -> None:
    for body in (
        {"head_commit": TOKEN[:40], "digests": {}},
        {"head_commit": "2" * 40, "digests": {"a.yml": TOKEN}},
    ):
        r = env.post(f"/library/{ALPHA}/freshness", json=body)
        assert r.status_code == 422, r.text
        assert TOKEN not in r.text


def _alpha_rows(env: Env) -> list[Grade]:
    with env.factory() as s:
        return list(s.execute(select(Grade).where(Grade.repo == ALPHA).order_by(Grade.seq))
                    .scalars().all())  # fmt: skip


def test_rows_provenance_names_graded_rows_of_this_repository(env: Env) -> None:
    r = env.post(
        f"/library/{ALPHA}/entries",
        json={**ENTRY, "provenance": {"kind": "rows", "rows": ["f" * 64, "e" * 64]}},
    )
    assert r.status_code == 422 and "2 graded rows" in envelope(r)["message"]
    row = _alpha_rows(env)[0]
    ok = _propose(env, provenance={"kind": "rows", "rows": [row.row_hash]})
    assert ok["entry"]["provenance"]["rows"] == [row.row_hash]


def test_an_approver_who_produced_the_cited_rows_cannot_sign_the_entry(env: Env) -> None:
    row = _alpha_rows(env)[0]
    with env.factory() as s:
        run = s.get(Run, row.run_id)
        assert run is not None
        run.actor = user_id("appr1")  # the approver queued the run that graded the row
        s.commit()
    proposed = _propose(env, provenance={"kind": "rows", "rows": [row.row_hash]})
    _as(env, "approver")
    base = f"/library/{ALPHA}/entries/convention/errors-wrap"
    r = env.post(f"{base}/sign", json={"version": proposed["version"]})
    assert r.status_code == 409 and envelope(r)["detail"]["code"] == "same_actor"
    _as(env, "admin")
    r = env.post(f"{base}/sign", json={"version": proposed["version"]})
    assert r.status_code == 200, r.text


def test_the_quality_table_seam_raises_when_the_table_fails_to_import_a_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = importlib.import_module

    def broken(name: str, *a: Any, **k: Any) -> Any:
        if name == "crb.core.quality_model":
            raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
        return real(name, *a, **k)

    monkeypatch.setattr(library_routes.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        library_routes.quality_model()

    def absent(name: str, *a: Any, **k: Any) -> Any:
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(library_routes.importlib, "import_module", absent)
    assert library_routes.quality_model() is None


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
