"""``GET /golive`` and ``PUT`` / ``DELETE /settings/attestations/{line}`` (ADR-0031).

Navigation
----------
What it is:   The route tests of the go-live checklist and its attestation record.
What it does: Pins that every signed-in role reads every line with its state and source and
              that nobody signed out does; that only an admin records or withdraws an
              attestation, each as one ``golive.*`` event naming the admin and never
              anything else (an operator, approver or viewer DELETE is refused and writes
              nothing); that only an admin reads local admins' login names; that the day
              after the UTC day is accepted; the refusals (404 ``unknown_line``, 409
              ``proven_by_product``, 409 ``not_attested``, 422 on an empty statement or a
              future day); that
              ``/version`` serves the belt set, the sign-off policy and the licence the
              Deployment page shows, with the licence pinned to pyproject.toml; and that the
              platform stream's ``/flow`` counts the lines the way ``/golive`` reads them, from
              a reading at most a minute old, never running the deep probes on every read.
How:          ``create_app`` over a temp SQLite store with the bootstrap admin; accounts of
              each role created through ``POST /users``; events read from the table.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
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


def day(offset: int) -> str:
    """The UTC calendar day ``offset`` days from now, read when the test runs — never at import.
    A module constant froze the suite's first day: a run that crossed 00:00 UTC then dated an act
    two days before the install (refused, six tests) and its "future" day one day ahead
    (accepted, the refusal test) — P-770."""
    return (_dt.datetime.now(_dt.UTC).date() + _dt.timedelta(days=offset)).isoformat()


def yesterday() -> str:
    """One day before the server's today: inside every bound :func:`golive._check_day` sets."""
    return day(-1)


def beyond_tomorrow() -> str:
    """Two days on: the first day the server refuses as the future everywhere."""
    return day(2)


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
        assert c["lines"] == 15 == c["proven"] + c["attested"] + c["unproven"]
        # a development stack: local executor, local sign-in on, the bootstrap admin configured
        assert line(body, "sealed-posture")["state"] == "unproven"
        assert "local sign-in is on" in line(body, "sign-in")["detail"]
        assert line(body, "egress-denied")["detail"] == "no attestation is recorded"


def test_only_an_admin_records_an_attestation_and_it_is_one_event(client: TestClient) -> None:
    login(client)
    create(client, "op", "operator")
    login(client, "op", USER_PW)
    body = {"statement": "egress to 1.1.1.1 from worker-0 timed out", "performed_on": yesterday()}
    r = client.put(f"{API_PREFIX}/settings/attestations/egress-denied", json=body)
    assert r.status_code == 403
    login(client)
    r = client.put(f"{API_PREFIX}/settings/attestations/egress-denied", json=body)
    assert r.status_code == 200, r.text
    got = line(r.json(), "egress-denied")
    assert got["state"] == "attested"
    a = got["attestation"]
    assert (a["by"], a["performed_on"], a["statement"]) == ("root", yesterday(), body["statement"])
    evs = golive_events(client)
    assert [e.action for e in evs] == ["golive.attested"]
    assert evs[0].payload_json == {
        "line": "egress-denied",
        "by": "root",
        "performed_on": yesterday(),
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
        json={"statement": "both hosts ok", "performed_on": yesterday()},
    )
    r = client.delete(f"{API_PREFIX}/settings/attestations/doctor")
    assert r.status_code == 200 and line(r.json(), "doctor")["state"] == "unproven"
    assert [e.action for e in golive_events(client)] == ["golive.attested", "golive.withdrawn"]


def test_the_refusals(client: TestClient) -> None:
    login(client)
    ok = {"statement": "done", "performed_on": yesterday()}
    r = client.put(f"{API_PREFIX}/settings/attestations/health-green", json=ok)
    assert r.status_code == 409 and err(r) == "proven_by_product"
    r = client.put(f"{API_PREFIX}/settings/attestations/made-up", json=ok)
    assert r.status_code == 404 and err(r) == "unknown_line"
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "   ", "performed_on": yesterday()},
    )
    assert r.status_code == 422 and err(r) == "invalid_attestation"
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "done", "performed_on": beyond_tomorrow()},
    )
    assert r.status_code == 422 and err(r) == "invalid_attestation"
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "x" * 501, "performed_on": yesterday()},
    )
    assert r.status_code == 422
    assert golive_events(client) == []


def test_version_serves_what_the_deployment_page_used_to_state(client: TestClient) -> None:
    d = client.get(f"{API_PREFIX}/version").json()
    assert (d["belt_set"], d["signoff_policy"], d["licence"]) == (
        "v5",
        "signoff-policy.v4",
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
        json={"statement": "both hosts ok", "performed_on": yesterday()},
    )
    want = client.get(f"{API_PREFIX}/golive").json()["counts"]
    r = client.get(f"{API_PREFIX}/flow", params={"repo": "calc"})
    assert r.status_code == 200, r.text
    platform = next(s for s in r.json()["streams"] if s["stream"] == "run-the-platform")
    assert {k: platform["counts"][f"golive_{k}"] for k in want} == want
    assert want["attested"] == 1
    assert platform["not_captured"] == []


def test_below_admin_nobody_withdraws_an_attestation(client: TestClient) -> None:
    """``settings.actions.16``: the API refuses both writes below admin — the withdrawal too,
    which would otherwise let an operator turn an attested line back to unproven."""
    login(client)
    body = {"statement": "egress to 1.1.1.1 from worker-0 timed out", "performed_on": yesterday()}
    assert (
        client.put(f"{API_PREFIX}/settings/attestations/egress-denied", json=body).status_code
        == 200
    )
    for role in ("operator", "approver", "viewer"):
        create(client, f"{role}-w", role)
    for role in ("operator", "approver", "viewer"):
        login(client, f"{role}-w", USER_PW)
        r = client.delete(f"{API_PREFIX}/settings/attestations/egress-denied")
        assert r.status_code == 403, (role, r.text)
    assert [e.action for e in golive_events(client)] == ["golive.attested"]
    login(client)
    assert line(client.get(f"{API_PREFIX}/golive").json(), "egress-denied")["state"] == "attested"


def test_a_viewer_is_told_how_many_local_admins_are_stale_never_their_names(
    client: TestClient,
) -> None:
    login(client)
    create(client, "vic", "viewer")
    admin_detail = line(client.get(f"{API_PREFIX}/golive").json(), "sign-in")["detail"]
    assert "never had its password set since it was created: root" in admin_detail
    login(client, "vic", USER_PW)
    assert client.get(f"{API_PREFIX}/users").status_code == 403
    seen = line(client.get(f"{API_PREFIX}/golive").json(), "sign-in")["detail"]
    assert "root" not in seen
    assert "1 active local admin has never had its password set" in seen


def test_the_day_after_the_utc_day_is_accepted_and_the_one_after_refused(
    client: TestClient,
) -> None:
    """East of UTC the admin's today is the server's tomorrow; the form defaults to it."""
    login(client)
    today = _dt.datetime.now(_dt.UTC).date()
    ahead = (today + _dt.timedelta(days=1)).isoformat()
    r = client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "both hosts ok", "performed_on": ahead},
    )
    assert r.status_code == 200, r.text
    assert line(r.json(), "doctor")["attestation"]["performed_on"] == ahead


def test_the_flow_reading_does_not_run_the_deep_probes_on_every_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/flow`` feeds a panel on five screens; its go-live counts reuse a reading taken in
    the last minute rather than walking the ledger and probing docker on every read."""
    from crb.server.routes import golive as golive_routes

    calls = {"health": 0, "ledger": 0}
    real_health, real_ledger = golive_routes.collect_health, golive_routes.verify_ledger

    def health(*a: Any, **kw: Any) -> Any:
        calls["health"] += 1
        return real_health(*a, **kw)

    def ledger(*a: Any, **kw: Any) -> Any:
        calls["ledger"] += 1
        return real_ledger(*a, **kw)

    monkeypatch.setattr(golive_routes, "collect_health", health)
    monkeypatch.setattr(golive_routes, "verify_ledger", ledger)
    login(client)
    with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
        s.add(Repo(name="calc", language="go", runner="go", config_json={"language": "go"}))
        s.commit()
    for _ in range(3):
        assert client.get(f"{API_PREFIX}/flow", params={"repo": "calc"}).status_code == 200
    assert calls == {"health": 1, "ledger": 1}
    # an attestation is in the next /flow reading at once: the write refreshes the reading
    client.put(
        f"{API_PREFIX}/settings/attestations/doctor",
        json={"statement": "both hosts ok", "performed_on": yesterday()},
    )
    r = client.get(f"{API_PREFIX}/flow", params={"repo": "calc"})
    platform = next(s for s in r.json()["streams"] if s["stream"] == "run-the-platform")
    assert platform["counts"]["golive_attested"] == 1
    assert calls == {"health": 2, "ledger": 2}
    # /golive itself is always read afresh: "proven" is a check run for that request
    client.get(f"{API_PREFIX}/golive")
    assert calls == {"health": 3, "ledger": 3}
