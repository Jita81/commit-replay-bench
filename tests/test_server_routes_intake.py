"""``/factory/{repo}/intake`` — the listener, its consent gate, and the column it serves.

Navigation
----------
What it is:   The intake routes' suite: the role ladder, the default-OFF listener, the
              switch that records who threw it, the on-demand poll against a FAKE tracker,
              and the refusals (listener off, no tracker configured, tracker unreachable).
What it does: Pins that a viewer can read the column but only an operator can switch the
              listener or poll, that the served state says ``off`` until somebody switches
              it on, that a poll writes the comment and the label and registers the item,
              that the served row carries the cell route the ticket was told about, and
              that the tracker credential is never in a response.
How:          The shared ``make_env`` stack with ``CRB_ENABLE_FAKE_TRACKER`` set and the
              file-backed :class:`crb.intake.fake.FileTracker` as the deployment's tracker.
              **No real Azure DevOps or Jira is contacted by this suite or by CI.**
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/server/routes/factory.py (the three routes under test),
              src/crb/server/intake.py (the service they call),
              src/crb/intake/fake.py (the board they poll),
              tests/fixtures/server_seed.py (the stack), tests/test_intake_service.py
Tested by:    tests/test_server_routes_intake.py
Touch when:   a field is added to the intake response (docs/API.md first, then the UI type).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.intake import client as c
from crb.intake.fake import FAKE_TRACKER_ENV, fake_tracker_path
from crb.server.app import API_PREFIX
from crb.server.secrets import TRACKER_TOKEN_SECRET
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, login, make_settings

READY_AC = [
    "reproduction: call /calc with an empty cart",
    "expected_behaviour: it returns 0 rather than crashing",
]


def _board(**over: Any) -> dict[str, Any]:
    ticket: dict[str, Any] = {
        "title": "Fix the crash when the cart is empty",
        "body": "steps to reproduce: open an empty cart. The page crashes.",
        "acceptance_criteria": READY_AC,
        "type": "Bug",
        "tags": ["area:checkout"],
        "points": 3,
        "revision": "1",
        "state": "Ready for manufacture",
        "changed": "2026-09-22T09:00:00Z",
        "url": "https://tracker.invalid/4711",
    }
    ticket.update(over)
    return {"tickets": {"4711": ticket}}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setenv(FAKE_TRACKER_ENV, "1")
    settings = make_settings(
        tmp_path,
        intake={
            "tracker": "fake",
            "url": "https://tracker.invalid",
            "project": "Widgets",
            "column": "Ready for manufacture",
        },
    )
    fake_tracker_path(tmp_path).write_text(json.dumps(_board()), encoding="utf-8")
    yield from _env_with(tmp_path, settings)


def _env_with(tmp_path: Path, settings: Any) -> Iterator[Env]:
    from fastapi.testclient import TestClient

    from crb.server.app import create_app
    from fixtures.server_seed import add_users, make_factory, seed

    factory = make_factory(tmp_path)
    info = seed(factory)
    add_users(factory)
    with TestClient(create_app(settings, factory)) as client:
        login(client, "admin")
        client.put(
            f"{API_PREFIX}/settings/secrets/tracker-token",
            json={"token": "a-tracker-token-value"},
        )
        yield Env(client=client, factory=factory, info=info, settings=settings)


def _get(env: Env) -> dict[str, Any]:
    r = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/intake")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _switch(env: Env, enabled: bool, column: str = "") -> Any:
    return env.client.put(
        f"{API_PREFIX}/factory/{ALPHA}/intake", json={"enabled": enabled, "column": column}
    )


# --- roles ---------------------------------------------------------------------------


def test_the_role_ladder_reading_is_a_viewer_switching_and_polling_are_an_operator(
    env: Env,
) -> None:
    assert_rbac(env, "GET", f"/factory/{ALPHA}/intake", min_role="viewer")
    assert_rbac(
        env, "PUT", f"/factory/{ALPHA}/intake", min_role="operator", json={"enabled": False}
    )
    assert_rbac(env, "POST", f"/factory/{ALPHA}/intake/poll", min_role="operator")


def test_an_unknown_repository_is_a_404(env: Env) -> None:
    r = env.client.get(f"{API_PREFIX}/factory/nope/intake")
    assert r.status_code == 404
    assert envelope(r)["code"] == "not_found"


# --- the default-OFF listener ----------------------------------------------------------


def test_every_repository_starts_with_its_listener_off_and_no_rows(env: Env) -> None:
    body = _get(env)
    assert body["listener"]["enabled"] is False
    assert body["rows"] == []
    assert body["last_poll"] is None


def test_the_connection_is_served_without_the_credential(env: Env) -> None:
    conn = _get(env)["connection"]
    assert conn["tracker"] == "fake"
    assert conn["configured"] is True
    assert conn["credential_set"] is True
    assert "a-tracker-token-value" not in json.dumps(conn)


def test_switching_the_listener_on_records_who_threw_it_and_when(env: Env) -> None:
    login(env.client, "operator")
    r = _switch(env, True, column="Ready for manufacture")
    assert r.status_code == 200, r.text
    listener = r.json()["listener"]
    assert listener["enabled"] is True
    assert listener["column"] == "Ready for manufacture"
    assert listener["switched_by"] and listener["switched_at"]


def test_switching_it_off_again_is_recorded_too_and_the_poll_is_then_refused(env: Env) -> None:
    login(env.client, "operator")
    _switch(env, True)
    _switch(env, False)
    assert _get(env)["listener"]["enabled"] is False
    r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    assert r.status_code == 422
    assert envelope(r)["code"] == "intake_listener_off"


# --- the poll ---------------------------------------------------------------------------


def test_a_poll_comments_labels_and_registers_the_ticket(env: Env, tmp_path: Path) -> None:
    login(env.client, "operator")
    _switch(env, True)
    r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    assert r.status_code == 200, r.text
    body = dict(r.json())
    assert body["last_poll"]["read"] == 1
    assert body["last_poll"]["registered"] == 1
    row = body["rows"][0]
    assert row["key"] == "4711"
    assert row["item_id"] == "fake-4711"
    assert row["capability_class"] == "bug.fix"
    assert row["registered"] is True
    assert row["label"] == c.LABEL_QUEUED
    # the board itself was written to, once
    board = json.loads(fake_tracker_path(tmp_path).read_text(encoding="utf-8"))
    ticket = board["tickets"]["4711"]
    assert c.LABEL_QUEUED in ticket["tags"]
    assert c.marker_for("fake", "4711") in ticket["comments"]
    # and the item is in the frozen backlog the factory route serves
    got = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog")
    assert got.status_code == 200
    assert [i["id"] for i in got.json()["items"]] == ["fake-4711"]


def test_the_served_row_carries_the_cell_route_the_ticket_was_told_about(env: Env) -> None:
    login(env.client, "operator")
    _switch(env, True)
    body = dict(env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").json())
    row = body["rows"][0]
    # the seed's deliver cell is bug.fix × S — exactly this ticket's cell
    assert row["cell_route"] is not None
    assert row["cell_route"]["n"] > 0
    assert str(row["cell_route"]["n"]) in row["feedback"]


def test_a_second_poll_of_an_unchanged_column_reads_nothing_again(env: Env) -> None:
    login(env.client, "operator")
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    second = dict(env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").json())
    assert second["last_poll"]["read"] == 0
    assert second["last_poll"]["skipped"] == 1


def test_a_needs_info_ticket_is_labelled_and_left_unregistered(env: Env, tmp_path: Path) -> None:
    fake_tracker_path(tmp_path).write_text(
        json.dumps(_board(acceptance_criteria=["reproduction: an empty cart"])), encoding="utf-8"
    )
    login(env.client, "operator")
    _switch(env, True)
    body = dict(env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").json())
    assert body["last_poll"]["registered"] == 0
    row = body["rows"][0]
    assert row["label"] == c.LABEL_NEEDS_INFO
    assert row["registered"] is False
    assert any("expected_behaviour" in q["ref"] for q in row["open_questions"])
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404


def test_a_ticket_edited_after_a_needs_info_read_registers_as_an_evolution(
    env: Env, tmp_path: Path
) -> None:
    path = fake_tracker_path(tmp_path)
    login(env.client, "operator")
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    first = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").json()
    # the person answers, and the tracker's revision moves
    board = json.loads(path.read_text(encoding="utf-8"))
    board["tickets"]["4711"]["revision"] = "2"
    board["tickets"]["4711"]["title"] = "Fix the crash when the cart is empty (revised)"
    path.write_text(json.dumps(board), encoding="utf-8")
    body = dict(env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").json())
    assert body["last_poll"]["registered"] == 1
    got = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").json()
    assert [e["id"] for e in got["evolutions"]] == ["fake-4711.r2"]
    assert got["evolutions"][0]["supersedes"] == "fake-4711"
    # the frozen record's own hash never moved — the evolution chains onto it, and the
    # effective backlog (``items``) shows the evolution in the superseded item's place
    assert got["hash"] == first["hash"]
    assert [i["id"] for i in got["items"]] == ["fake-4711.r2"]
    assert got["items"][0]["supersedes"] == "fake-4711"


def test_the_intake_events_are_on_the_repository_evidence_chain(env: Env) -> None:
    login(env.client, "operator")
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    chain = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/evidence").json()
    kinds = [e["kind"] for e in chain["items"]]
    assert "intake.feedback.posted" in kinds
    assert "intake.registered" in kinds
    assert "intake.read" in kinds
    assert "intake.polled" in kinds
    assert chain["verified"] is True  # the chain still verifies with the intake events on it


# --- refusals -----------------------------------------------------------------------------


def test_switching_a_listener_on_with_no_tracker_configured_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FAKE_TRACKER_ENV, "1")
    settings = make_settings(tmp_path)
    for env in _env_with(tmp_path, settings):
        login(env.client, "operator")
        r = _switch(env, True)
        assert r.status_code == 422
        assert envelope(r)["code"] == "intake_not_configured"
        break


def test_a_tracker_the_deployment_cannot_build_is_a_502_naming_the_way_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the fake tracker's gate is OFF: the deployment is configured for it but may not use it
    monkeypatch.delenv(FAKE_TRACKER_ENV, raising=False)
    settings = make_settings(
        tmp_path,
        intake={
            "tracker": "fake",
            "url": "https://tracker.invalid",
            "project": "W",
            "column": "Ready",
        },
    )
    for env in _env_with(tmp_path, settings):
        login(env.client, "operator")
        assert _switch(env, True).status_code == 200
        r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
        assert r.status_code == 502
        body = envelope(r)
        assert body["code"] == "tracker_error"
        assert body["message"]
        break


def test_an_unreadable_board_stops_the_poll_with_a_reason_rather_than_a_500(
    env: Env, tmp_path: Path
) -> None:
    fake_tracker_path(tmp_path).write_text("not json", encoding="utf-8")
    login(env.client, "operator")
    _switch(env, True)
    r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    assert r.status_code == 200
    last = r.json()["last_poll"]
    assert last["stopped"] == c.REASON_COLUMN_GONE
    assert last["advice"]


def test_the_stored_tracker_token_is_never_served_anywhere(env: Env) -> None:
    login(env.client, "admin")
    secrets = env.client.get(f"{API_PREFIX}/settings/secrets").json()
    names = {s["name"] for s in secrets["items"]}
    assert TRACKER_TOKEN_SECRET in names
    assert "a-tracker-token-value" not in json.dumps(secrets)
    assert "a-tracker-token-value" not in json.dumps(
        env.client.get(f"{API_PREFIX}/settings").json()
    )


def test_a_tracker_token_with_a_line_break_in_it_is_refused_with_advice(env: Env) -> None:
    login(env.client, "admin")
    r = env.client.put(
        f"{API_PREFIX}/settings/secrets/tracker-token",
        json={"token": "Authorization: Basic abcdefghijklmnop"},
    )
    assert r.status_code == 422
    assert "paste the token itself" in envelope(r)["message"]
