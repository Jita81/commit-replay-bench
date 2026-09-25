"""``/factory/{repo}/intake`` — the listener, its consent gate, and the column it serves.

Navigation
----------
What it is:   The intake routes' suite: the role ladder, the default-OFF listener, the
              switch that records who threw it, the on-demand poll against a FAKE tracker,
              and the refusals (listener off, no tracker configured, tracker unreachable).
What it does: Pins that a viewer can read the column but only an operator can switch the
              listener or poll, that the served state says ``off`` until somebody switches
              it on, that a poll writes the comment and the label and leaves a ready ticket
              as a draft until an operator's Register act registers it (ADR-0022; a moved
              revision is refused), that a poll while another pass holds the repository's
              lease is 409 ``intake_busy``, that the served row carries the cell route the
              ticket was told about, and that the tracker credential is never in a response.
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


def _env_without_token(tmp_path: Path, settings: Any) -> Any:
    """The same stack with NO tracker credential stored — the state a deployment is in
    between an admin setting the connection and an admin setting the token."""
    from fastapi.testclient import TestClient

    from crb.server.app import create_app
    from fixtures.server_seed import add_users, make_factory, seed

    factory = make_factory(tmp_path)
    info = seed(factory)
    add_users(factory)
    with TestClient(create_app(settings, factory)) as client:
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
    # ADR-0022: the Register act (a key nothing drafted: the operator gets 409, not 403)
    assert_rbac(
        env,
        "POST",
        f"/factory/{ALPHA}/intake/9999/register",
        min_role="operator",
        json={"revision": "1"},
    )


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


def test_a_poll_comments_and_labels_and_the_register_act_registers_the_ticket(
    env: Env, tmp_path: Path
) -> None:
    login(env.client, "operator")
    _switch(env, True)
    r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    assert r.status_code == 200, r.text
    body = dict(r.json())
    assert body["last_poll"]["read"] == 1
    # ADR-0022: the ready ticket waits for an operator; the Register act registers it
    assert body["last_poll"]["registered"] == 0 and body["last_poll"]["awaiting"] == 1
    r = _register(env)
    assert r.status_code == 200, r.text
    body = dict(r.json())
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
    assert _register(env).status_code == 200  # ADR-0022: the operator registers the draft
    first = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").json()
    # the person answers, and the tracker's revision moves
    board = json.loads(path.read_text(encoding="utf-8"))
    board["tickets"]["4711"]["revision"] = "2"
    board["tickets"]["4711"]["title"] = "Fix the crash when the cart is empty (revised)"
    path.write_text(json.dumps(board), encoding="utf-8")
    body = dict(env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").json())
    assert body["last_poll"]["awaiting"] == 1  # the evolution is a draft too
    assert _register(env, revision="2").status_code == 200
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
    _register(env)
    chain = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/evidence").json()
    kinds = [e["kind"] for e in chain["items"]]
    assert "intake.feedback.posted" in kinds
    assert "intake.awaiting_approval" in kinds
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


# --- the consent gate leaves a record, and it checks what it promises -----------------


def _events(env: Env, action: str) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from crb.store.models import Event

    with env.factory() as s:
        rows = s.execute(select(Event).where(Event.action == action)).scalars().all()
        return [
            {"actor": r.actor, "repo": r.repo, "payload": dict(r.payload_json or {})} for r in rows
        ]


def test_every_switch_of_the_listener_is_an_event_naming_the_operator(env: Env) -> None:
    """`switched_by` is ONE mutable field: switching off and on again overwrites it. Without
    the event, writes made on somebody's tickets under the earlier consent would appear to
    have been consented by whoever switched it last."""
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    login(env.client, "admin")
    assert _switch(env, False).status_code == 200
    assert _switch(env, True, column="Another column").status_code == 200

    events = _events(env, "intake.listener.switched")
    assert [e["payload"]["enabled"] for e in events] == [True, False, True]
    assert len({e["actor"] for e in events}) == 2  # the first consent is still readable
    assert all(e["repo"] == ALPHA for e in events)
    assert events[-1]["payload"]["column"] == "Another column"
    assert events[0]["payload"]["tracker"] == "fake"


def test_switching_a_listener_on_with_no_credential_stored_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route's own 422 message promised that an admin stores the tracker token first.
    It accepted the switch anyway, told the operator "the listener is on", and then every
    poll stopped `no_secret` — advice arriving after the act it was meant to prevent."""
    monkeypatch.setenv(FAKE_TRACKER_ENV, "1")
    settings = make_settings(
        tmp_path,
        intake={
            "tracker": "ado",
            "url": "https://dev.azure.invalid/contoso",
            "project": "Widgets",
            "column": "Ready for manufacture",
        },
    )
    for env in _env_without_token(tmp_path, settings):
        login(env.client, "operator")
        r = _switch(env, True)
        assert r.status_code == 422
        assert envelope(r)["code"] == "intake_no_credential"
        assert "admin" in envelope(r)["message"]
        assert _get(env)["listener"]["enabled"] is False
        break


def test_switching_a_listener_on_with_no_public_address_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every link the product writes on a ticket is built from this deployment's own
    address. Without one they are relative paths, which resolve against the TRACKER's host
    on the customer's board — so the switch is refused rather than writing dead links."""
    monkeypatch.setenv(FAKE_TRACKER_ENV, "1")
    settings = make_settings(
        tmp_path,
        public_url="",
        intake={
            "tracker": "fake",
            "url": "https://tracker.invalid",
            "project": "Widgets",
            "column": "Ready for manufacture",
        },
    )
    for env in _env_with(tmp_path, settings):
        login(env.client, "operator")
        r = _switch(env, True)
        assert r.status_code == 422
        assert envelope(r)["code"] == "intake_no_public_url"
        assert "CRB_PUBLIC_URL" in envelope(r)["message"]
        break


def test_the_link_written_on_a_ticket_is_absolute(env: Env) -> None:
    login(env.client, "operator")
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    _register(env)
    row = _get(env)["rows"][0]
    assert row["item_url"].startswith("http://localhost:8000/factory?repo=")
    board = json.loads(fake_tracker_path(env.settings.home).read_text(encoding="utf-8"))
    ticket = board["tickets"]["4711"]
    assert ticket["links"] == [row["item_url"]]
    assert ticket["link_titles"][row["item_url"]] == c.LINK_ITEM
    comment = "\n".join(str(v) for v in ticket["comments"].values())
    assert "Follow it here: http" in comment


# --- the credential never travels in clear, and never appears anywhere ------------------


def test_a_plain_http_tracker_url_is_refused_at_start_up(tmp_path: Path) -> None:
    """The PAT travels on this URL as ``Authorization: Basic``. Nothing pinned this rule:
    deleting the validator let a deployment start on ``http://`` and send the credential
    unencrypted on every poll, with the whole suite still green."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="https"):
        make_settings(
            tmp_path,
            intake={
                "tracker": "ado",
                "url": "http://dev.azure.invalid/contoso",
                "project": "Widgets",
                "column": "Ready for manufacture",
            },
        )
    ok = make_settings(
        tmp_path,
        intake={
            "tracker": "ado",
            "url": "https://dev.azure.invalid/contoso/",
            "project": "Widgets",
            "column": "Ready for manufacture",
        },
    )
    assert ok.intake.url == "https://dev.azure.invalid/contoso"  # the trailing slash is stripped


def test_the_tracker_token_is_in_no_log_no_event_no_state_file_and_no_error(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """ADR-0017 and SECURITY §2 forbid a credential in a URL, a log, an event or an error
    message, and nothing enforced it: a careless edit put the token in a log line and the
    whole suite stayed green. One test covers the whole sentence."""
    import logging

    token = "a-tracker-token-value"  # what the fixture stored
    login(env.client, "operator")
    _switch(env, True)
    with caplog.at_level(logging.DEBUG):
        assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
        # and a poll that cannot reach its tracker, which is where a detail is built
        fake_tracker_path(env.settings.home).write_text("not json", encoding="utf-8")
        env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")

    assert token not in caplog.text
    assert token not in json.dumps(_get(env))
    state = (env.settings.home / "factory" / ALPHA / "intake-state.json").read_text("utf-8")
    assert token not in state
    chain = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/evidence").json()
    assert token not in json.dumps(chain)
    settings_body = env.client.get(f"{API_PREFIX}/settings").json()
    assert token not in json.dumps(settings_body)


def test_the_walkthroughs_fake_board_needs_no_credential_to_switch_on(env: Env) -> None:
    """The consent gate asks the SAME question `build_tracker` asks — it must, or a gate can
    refuse a switch the poll would have honoured. The file-backed fake board has no
    authentication, so demanding a stored token for it broke the walkthrough while every unit
    test passed."""
    from crb.server.intake import needs_credential

    assert needs_credential("ado") and needs_credential("jira")
    assert not needs_credential("fake") and not needs_credential("none")
    # the fixture stack IS the fake tracker; clearing the token must not close the gate
    login(env.client, "admin")
    assert env.client.delete(f"{API_PREFIX}/settings/secrets/tracker-token").status_code in (
        200,
        204,
    )
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    assert _get(env)["listener"]["enabled"] is True


# --- C6 (assessment 2026-09-25): approval by default, and one pass at a time ------------


def _register(env: Env, key: str = "4711", revision: str = "1") -> Any:
    return env.client.post(
        f"{API_PREFIX}/factory/{ALPHA}/intake/{key}/register", json={"revision": revision}
    )


def test_approval_is_required_by_default_and_the_allowlist_is_empty() -> None:
    """ADR-0022: the deployment default is that an operator registers every ready ticket;
    only an explicit allowlist of tracker authors may bypass it."""
    from crb.server.settings import IntakeSettings

    s = IntakeSettings()
    assert s.require_approval is True and s.approve_authors == []
    view = s.redacted()
    assert view["require_approval"] is True and view["approve_authors"] == []


def test_a_ready_ticket_lands_as_a_draft_until_an_operator_registers_it(
    env: Env, tmp_path: Path
) -> None:
    login(env.client, "operator")
    _switch(env, True)
    body = dict(env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").json())
    assert body["last_poll"]["registered"] == 0 and body["last_poll"]["awaiting"] == 1
    (row,) = body["rows"]
    assert row["awaiting_approval"] is True and row["registered"] is False
    # unqueued, and labelled with the product's readiness word for this deployment: the
    # test cell routes nothing to `deliver`, so the draft reads not-deliverable (not ready)
    assert row["label"] == c.LABEL_NOT_DELIVERABLE
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404
    # the Register act is an operator's (the role ladder test pins the refusals below it),
    # and it names the revision the operator read
    r = _register(env)
    assert r.status_code == 200, r.text
    (row,) = r.json()["rows"]
    assert row["registered"] is True and row["awaiting_approval"] is False
    assert row["label"] == c.LABEL_QUEUED
    got = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog")
    assert got.status_code == 200 and [i["id"] for i in got.json()["items"]] == ["fake-4711"]
    # the act is evented: on the chain with who approved it
    chain = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/evidence").json()
    (reg,) = [e for e in chain["items"] if e["kind"] == "intake.registered"]
    assert reg["payload"]["approved_by"].startswith("operator")
    board = json.loads(fake_tracker_path(tmp_path).read_text(encoding="utf-8"))
    assert c.LABEL_QUEUED in board["tickets"]["4711"]["tags"]
    # a second Register is refused: there is nothing waiting any more
    again = _register(env)
    assert again.status_code == 409 and envelope(again)["code"] == "nothing_to_register"


def test_registering_a_revision_that_has_moved_is_refused(env: Env, tmp_path: Path) -> None:
    login(env.client, "operator")
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    r = _register(env, revision="0")
    assert r.status_code == 409 and envelope(r)["code"] == "revision_moved"
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404


def test_a_poll_while_another_pass_holds_the_repositorys_lease_is_refused_as_busy(
    env: Env,
) -> None:
    """C6(c): the on-demand poll takes the same per-repository lease the worker's timed
    poll takes; while another pass holds it, the route writes nothing and says so."""
    from crb.server.intake import intake_lease

    login(env.client, "operator")
    _switch(env, True)
    held = intake_lease(env.factory, ALPHA, ttl_s=300)
    assert held.acquire()
    try:
        r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
        assert r.status_code == 409 and envelope(r)["code"] == "intake_busy"
        assert _get(env)["rows"] == []
        reg = _register(env)
        assert reg.status_code == 409 and envelope(reg)["code"] == "intake_busy"
    finally:
        held.release()
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
