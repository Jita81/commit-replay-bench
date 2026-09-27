"""``GET /golive`` and ``PUT`` / ``DELETE /settings/attestations/{line}`` (ADR-0045).

Navigation
----------
What it is:   The route tests of the go-live checklist and its attestation record.
What it does: Pins that every signed-in role reads every line with its state and source and
              that nobody signed out does; that only an admin records or withdraws an
              attestation, each as one ``golive.*`` event naming the admin and never
              anything else; the refusals (404 ``unknown_line``, 409 ``proven_by_product``,
              409 ``not_attested``, 422 on an empty statement or a future day); that
              ``/version`` serves the belt set, the sign-off policy and the licence the
              Deployment page shows, with the licence pinned to pyproject.toml; and that the
              platform stream's ``/flow`` counts the lines the way ``/golive`` reads them.
How:          ``create_app`` over a temp SQLite store with the bootstrap admin; accounts of
              each role created through ``POST /users``; events read from the table.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0045-go-live-lines-are-proven-or-attested.md
Works with:   src/crb/server/routes/golive.py (under test), src/crb/server/golive.py (the
              lines and checks), src/crb/server/routes/system.py (``/version``),
              src/crb/server/routes/flow.py (the platform stream's counts), docs/API.md#admin
              (the contract asserted)
Tested by:    tests/test_server_routes_golive.py
Touch when:   never for a new repository; a go-live route or its refusals change.
"""

from __future__ import annotations

import datetime as _dt
import os
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from crb.server import golive
from crb.server.app import API_PREFIX, create_app
from crb.server.auth import CSRF_COOKIE
from crb.server.routes.system import LICENCE
from crb.server.settings import Settings
from crb.store.models import Event, Repo

ROOT = Path(__file__).resolve().parent.parent
ROOT_PW = "correct-horse-battery-staple"
USER_PW = "another-long-password"


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            env="dev",
            home=tmp_path,
            secret_key=SecretStr("s" * 40),
            sandbox={"executor": "local"},
            bootstrap_admin={"username": "root", "password": ROOT_PW},
            log_format="text",
        )
    )
    with TestClient(app) as c:
        yield c


def login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> None:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies[CSRF_COOKIE]


def create(c: TestClient, username: str, role: str) -> None:
    r = c.post(
        f"{API_PREFIX}/users", json={"username": username, "password": USER_PW, "role": role}
    )
    assert r.status_code == 201, r.text


def err(r: Any) -> str:
    return str(r.json()["error"]["code"])


def line(body: dict[str, Any], line_id: str) -> dict[str, Any]:
    return next(ln for ln in body["lines"] if ln["id"] == line_id)


def golive_events(c: TestClient) -> list[Event]:
    with c.app.state.session_factory() as s:  # type: ignore[attr-defined]
        rows = list(
            s.execute(
                select(Event).where(Event.trace_id == golive.TRACE_ID).order_by(Event.seq)
            ).scalars()
        )
        s.expunge_all()
        return rows


YESTERDAY = (_dt.datetime.now(_dt.UTC).date() - _dt.timedelta(days=1)).isoformat()
TOMORROW = (_dt.datetime.now(_dt.UTC).date() + _dt.timedelta(days=2)).isoformat()


def test_every_signed_in_role_reads_every_line_with_its_state_and_source(
    client: TestClient,
) -> None:
    assert client.get(f"{API_PREFIX}/golive").status_code == 401
    login(client)
    for role in ("viewer", "operator", "approver"):
        create(client, role, role)
    for role in ("viewer", "operator", "approver", "root"):
        login(client, role, USER_PW if role != "root" else ROOT_PW)
        r = client.get(f"{API_PREFIX}/golive")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [ln["id"] for ln in body["lines"]] == [ln.id for ln in golive.LINES]
        for ln in body["lines"]:
            assert ln["state"] in golive.STATES and ln["source"] and ln["doc"] and ln["detail"]
        c = body["counts"]
        assert c["lines"] == 14 == c["proven"] + c["attested"] + c["unproven"]
        # a development stack: local executor, local sign-in on, the bootstrap admin configured
        assert line(body, "sealed-posture")["state"] == "unproven"
        assert "local sign-in is on" in line(body, "sign-in")["detail"]
        assert line(body, "egress-denied")["detail"] == "no attestation is recorded"


def test_only_an_admin_records_an_attestation_and_it_is_one_event(client: TestClient) -> None:
    login(client)
    create(client, "op", "operator")
    login(client, "op", USER_PW)
    body = {"statement": "egress to 1.1.1.1 from worker-0 timed out", "performed_on": YESTERDAY}
    r = client.put(f"{API_PREFIX}/settings/attestations/egress-denied", json=body)
    assert r.status_code == 403
    login(client)
    r = client.put(f"{API_PREFIX}/settings/attestations/egress-denied", json=body)
    assert r.status_code == 200, r.text
    got = line(r.json(), "egress-denied")
    assert got["state"] == "attested"
    a = got["attestation"]
    assert (a["by"], a["performed_on"], a["statement"]) == ("root", YESTERDAY, body["statement"])
    evs = golive_events(client)
    assert [e.action for e in evs] == ["golive.attested"]
    assert evs[0].payload_json == {
        "line": "egress-denied",
        "by": "root",
        "performed_on": YESTERDAY,
        "statement": body["statement"],
    }
    assert evs[0].actor == a["actor"] and evs[0].stage == "system"
    # a viewer reads the attestation (the review board reads who and when)
    create(client, "vw", "viewer")
    login(client, "vw", USER_PW)
    assert (
        line(client.get(f"{API_PREFIX}/golive").json(), "egress-denied")["attestation"]["by"]
        == "root"
    )


def test_a_withdrawal_is_an_event_and_the_line_reads_unproven_again(client: TestClient) -> None:
    login(client)
    r = client.delete(f"{API_PREFIX}/settings/attestations/doctor")
    assert r.status_code == 409 and err(r) == "not_attested"
    client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "both hosts ok", "performed_on": YESTERDAY},
    )
    r = client.delete(f"{API_PREFIX}/settings/attestations/doctor")
    assert r.status_code == 200 and line(r.json(), "doctor")["state"] == "unproven"
    assert [e.action for e in golive_events(client)] == ["golive.attested", "golive.withdrawn"]


def test_the_refusals(client: TestClient) -> None:
    login(client)
    ok = {"statement": "done", "performed_on": YESTERDAY}
    r = client.put(f"{API_PREFIX}/settings/attestations/health-green", json=ok)
    assert r.status_code == 409 and err(r) == "proven_by_product"
    r = client.put(f"{API_PREFIX}/settings/attestations/made-up", json=ok)
    assert r.status_code == 404 and err(r) == "unknown_line"
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "   ", "performed_on": YESTERDAY},
    )
    assert r.status_code == 422 and err(r) == "invalid_attestation"
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "done", "performed_on": TOMORROW},
    )
    assert r.status_code == 422 and err(r) == "invalid_attestation"
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "x" * 501, "performed_on": YESTERDAY},
    )
    assert r.status_code == 422
    assert golive_events(client) == []


def test_version_serves_what_the_deployment_page_used_to_state(client: TestClient) -> None:
    d = client.get(f"{API_PREFIX}/version").json()
    assert (d["belt_set"], d["signoff_policy"], d["licence"]) == (
        "v5",
        "signoff-policy.v3",
        LICENCE,
    )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == LICENCE


def test_the_platform_stream_counts_the_lines_as_golive_reads_them(client: TestClient) -> None:
    login(client)
    with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
        s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
        s.commit()
    client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "both hosts ok", "performed_on": YESTERDAY},
    )
    want = client.get(f"{API_PREFIX}/golive").json()["counts"]
    r = client.get(f"{API_PREFIX}/flow", params={"repo": "calc"})
    assert r.status_code == 200, r.text
    platform = next(s for s in r.json()["streams"] if s["stream"] == "run-the-platform")
    assert {k: platform["counts"][f"golive_{k}"] for k in want} == want
    assert want["attested"] == 1
    assert platform["not_captured"] == []
