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
              Since the PR #55 review: that the Register act is refused while the listener is
              off or once the deployment has lost its public address, that ``approved_by``
              is the operator's account id, and — as prevention — that no route builds a
              tracker except through the listener check, that check re-applies the switch's
              readiness rule, and no approval identity (``approved_by`` / ``approver`` / an
              ``operator:`` f-string) is built from a display name. Since its re-review:
              that a switch-off is refused while a pass holds the lease, that a pass which
              read the switch before the lease reads and writes nothing, that Register reads
              the live ticket and refuses one edited since the last poll, and — as prevention
              — that every served pass hands over a fresh ``intake_lease``.
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
from crb.server import intake as sv
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


# --- PR #55 review: the Register act is a board write, so the switch gates it too --------


def test_the_register_act_is_refused_while_the_listener_is_off(env: Env, tmp_path: Path) -> None:
    """The switch is the consent to write on that board (ADR-0017): after an operator
    switches the listener off, a draft read while it was on can no longer be registered —
    422 ``intake_listener_off``, nothing on the frozen backlog, not one write on the board.
    Switched back on, the same draft registers."""
    login(env.client, "operator")
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    _switch(env, False)
    board = fake_tracker_path(tmp_path)
    before = board.read_text(encoding="utf-8")
    r = _register(env)
    assert r.status_code == 422, r.text
    assert envelope(r)["code"] == "intake_listener_off"
    assert board.read_text(encoding="utf-8") == before
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404
    assert _events(env, "intake.approved") == []
    _switch(env, True)
    assert _register(env).status_code == 200


def test_the_approver_on_the_record_is_the_operators_stable_id_not_their_name(
    env: Env,
) -> None:
    """PR #55 review: ``approved_by`` once recorded the operator's display name — mutable
    and not unique, so two accounts called "Ada" were one approver on the hash chain and a
    renamed account could not be traced. It is the account id; the name rides alongside as
    ``approved_by_name`` for a human reader."""
    login(env.client, "operator")
    me = env.client.get(f"{API_PREFIX}/auth/me").json()
    _switch(env, True)
    env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    assert _register(env).status_code == 200
    chain = env.client.get(f"{API_PREFIX}/factory/{ALPHA}/evidence").json()
    (reg,) = [e for e in chain["items"] if e["kind"] == "intake.registered"]
    assert reg["payload"]["approved_by"] == f"operator:{me['id']}"
    assert reg["payload"]["approved_by_name"] == me["display_name"]
    (approved,) = _events(env, "intake.approved")
    assert approved["payload"]["approved_by"] == f"operator:{me['id']}"
    assert approved["payload"]["approved_by_name"] == me["display_name"]


def _calls_in(path: Path, name: str) -> dict[str, int]:
    """How many times each top-level function in ``path`` calls ``name``."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef):
            n = sum(
                1
                for node in ast.walk(fn)
                if isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == name)
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
                )
            )
            if n:
                out[fn.name] = n
    return out


def test_a_route_reaches_the_board_only_through_the_listener_check() -> None:
    """The prevention for the class: no route builds a tracker client itself. The one way
    a route gets one is ``_consented_tracker``, which refuses when the repository's
    listener is off — so a new board-writing route cannot forget the consent check."""
    routes = Path(__file__).resolve().parents[1] / "src" / "crb" / "server" / "routes"
    callers = {
        f"{p.name}::{fn}": n
        for p in sorted(routes.glob("*.py"))
        for fn, n in _calls_in(p, "build_tracker").items()
    }
    assert callers == {"factory.py::_consented_tracker": 1}


#: The names an approval identity travels under, as a keyword argument, a dict key or an
#: assignment target. ``approved_by_name`` / ``approver_name`` are the human-readable
#: labels recorded BESIDE the identity, so they are deliberately not in this set.
_APPROVAL_IDENTITY_FIELDS = frozenset({"approved_by", "approver"})


def _display_name_offenders(tree: Any) -> list[int]:
    """Lines where an approval identity is built from a display name: an ``operator:<…>``
    f-string that reads ``display_name``, or a value that reads ``display_name`` (or a
    ``*_name`` variable holding one) bound to an ``approved_by`` / ``approver`` keyword
    argument, dict key or assignment target."""
    import ast

    def reads_a_name(value: Any) -> bool:
        return any(
            (isinstance(n, ast.Attribute) and n.attr == "display_name")
            or (isinstance(n, ast.Name) and (n.id == "display_name" or n.id.endswith("_name")))
            for n in ast.walk(value)
        )

    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and node.values:
            head = node.values[0]
            if (
                isinstance(head, ast.Constant)
                and isinstance(head.value, str)
                and head.value.startswith("operator:")
                and reads_a_name(node)
            ):
                lines.append(node.lineno)
        elif isinstance(node, ast.keyword):
            if node.arg in _APPROVAL_IDENTITY_FIELDS and reads_a_name(node.value):
                lines.append(node.value.lineno)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in _APPROVAL_IDENTITY_FIELDS
                    and reads_a_name(value)
                ):
                    lines.append(key.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            named = {t.id for t in targets if isinstance(t, ast.Name)} | {
                t.attr for t in targets if isinstance(t, ast.Attribute)
            }
            if named & _APPROVAL_IDENTITY_FIELDS and node.value and reads_a_name(node.value):
                lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "source",
    [
        'approved_by = f"operator:{operator.display_name}"',
        "approver = operator.display_name",
        "approver = operator.display_name or operator.id",
        "register(approved_by=operator.display_name)",
        "register(approver=approver_name)",
        'payload = {"approved_by": user.display_name}',
        "self.approver = operator.display_name",
    ],
)
def test_the_approval_identity_ratchet_catches_each_way_back(source: str) -> None:
    """The ratchet below is only as good as what it catches: each of these is a way the
    ``approved_by`` bug could come back, and each is flagged."""
    import ast

    assert _display_name_offenders(ast.parse(source)) != []


def test_no_approval_identity_is_built_from_a_display_name() -> None:
    """The prevention for the ``approved_by`` class (PR #55 review): an approval identity
    written to a record is built from the account id, never from a display name (mutable,
    not unique). Scans every module in the server package for the shapes
    ``_display_name_offenders`` names. It covers APPROVAL identities only: display labels
    such as ``switched_by`` are recorded beside an event whose ``actor`` is the id."""
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "crb" / "server"
    offenders = [
        f"{p.relative_to(src)}:{line}"
        for p in sorted(src.rglob("*.py"))
        for line in _display_name_offenders(ast.parse(p.read_text(encoding="utf-8")))
    ]
    assert offenders == []


# --- PR #55 review: readiness is rechecked on every board route, not only at the switch ---


def test_the_register_act_is_refused_when_the_deployment_has_lost_its_address(
    env: Env, tmp_path: Path
) -> None:
    """The switch checks that this deployment knows its own address, but consent outlives
    the check: a restart without ``CRB_PUBLIC_URL`` leaves the listener on. The Register
    act then wrote ``crb:queued``, a "Follow it here" comment and a link that were all a
    RELATIVE path — dead on the tracker's site, and refused by Azure DevOps as a relation.
    It is refused (422 ``intake_no_public_url``) and nothing reaches the board."""
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
    env.settings.public_url = ""  # a restart without CRB_PUBLIC_URL; the consent is stored
    board = fake_tracker_path(tmp_path)
    before = board.read_text(encoding="utf-8")
    r = _register(env)
    assert r.status_code == 422, r.text
    assert envelope(r)["code"] == "intake_no_public_url"
    assert "CRB_PUBLIC_URL" in envelope(r)["message"]
    assert board.read_text(encoding="utf-8") == before
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404
    assert _events(env, "intake.approved") == []


def test_every_board_route_rechecks_what_the_switch_checked() -> None:
    """The prevention for the class: the switch-time readiness rule lives in ONE function,
    and the one way a route reaches the board (``_consented_tracker``, held to that by
    ``test_a_route_reaches_the_board_only_through_the_listener_check``) calls it. So a new
    board-writing route cannot skip a check the switch made, however long ago it was made."""
    routes = Path(__file__).resolve().parents[1] / "src" / "crb" / "server" / "routes"
    assert _calls_in(routes / "factory.py", "_refuse_unless_ready_to_listen") == {
        "put_intake": 1,
        "_consented_tracker": 1,
    }


# --- PR #55 review: a switch-off never lands while a pass is reading or writing ---------


class _RecordingTracker:
    """A tracker that writes nothing and records every call a pass makes on it — so a
    test can say "not one read, not one write reached the board"."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, method: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            """Records the call, then refuses it: nothing may reach the board."""
            self.calls.append(method)
            raise AssertionError(f"the board was reached: {method}")

        return call


def test_switching_the_listener_off_while_a_pass_holds_the_lease_is_refused(env: Env) -> None:
    """The switch-off promises that nothing on the board is read or written afterwards.
    It committed while a pass held the repository's lease, and that pass kept reading
    and writing on the board. The switch-off now takes the same lease: while a pass holds
    it the switch is refused (409 ``intake_busy``) and the listener stays on, so the
    promise is never made while it cannot be kept."""
    from crb.server.intake import intake_lease

    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    held = intake_lease(env.factory, ALPHA, ttl_s=300)
    assert held.acquire()
    try:
        r = _switch(env, False)
        assert r.status_code == 409, r.text
        assert envelope(r)["code"] == "intake_busy"
        assert _get(env)["listener"]["enabled"] is True
        switched = [e["payload"]["enabled"] for e in _events(env, "intake.listener.switched")]
        assert switched == [True]
    finally:
        held.release()
    assert _switch(env, False).status_code == 200
    assert _get(env)["listener"]["enabled"] is False


def test_a_pass_that_read_consent_before_a_switch_off_reads_and_writes_nothing(
    env: Env, tmp_path: Path
) -> None:
    """Consent read before the lease is stale once the pass holds it: the poll route, the
    Register act and the worker all read the listener, then take the lease. A switch-off
    that landed in between left the pass free to read and write the board. Under the lease
    the pass now asks the committed switch again: the poll reads nothing and writes
    nothing, and the Register act is refused with ``intake_listener_off``."""
    from crb.server.factory_state import FactoryHome
    from crb.server.intake import (
        ApprovalRefused,
        IntakeStore,
        ListenerState,
        intake_lease,
        item_url_for,
        poll_repository,
        register_approved,
    )

    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
    stale = ListenerState(enabled=True)  # what the pass read before the switch-off
    assert _switch(env, False).status_code == 200
    home = FactoryHome(env.settings.home, ALPHA)
    board = fake_tracker_path(tmp_path)
    before = (board.read_text(encoding="utf-8"), len(home.events()))
    rows_before = IntakeStore(env.settings.home, ALPHA).rows()
    tracker: Any = _RecordingTracker()
    report = poll_repository(
        ALPHA,
        tracker=tracker,
        listener=stale,
        column="Ready for manufacture",
        home=home,
        route_for=lambda item: None,
        item_url=item_url_for(env.settings.public_url, ALPHA),
        lease=intake_lease(env.factory, ALPHA),
    )
    assert report.withdrawn and not report.busy
    assert tracker.calls == []
    with pytest.raises(ApprovalRefused) as refused:
        register_approved(
            ALPHA,
            "4711",
            revision="1",
            tracker=tracker,
            home=home,
            item_url=item_url_for(env.settings.public_url, ALPHA),
            approver="operator:1",
            lease=intake_lease(env.factory, ALPHA),
        )
    assert refused.value.code == "intake_listener_off"
    assert tracker.calls == []
    assert (board.read_text(encoding="utf-8"), len(home.events())) == before
    assert IntakeStore(env.settings.home, ALPHA).rows() == rows_before
    assert home.load_backlog() is None


# --- PR #55 review: the Register act checks the live ticket, not only the last read ----


def test_a_ticket_edited_after_the_last_poll_is_refused_at_register(
    env: Env, tmp_path: Path
) -> None:
    """The Register act compared the operator's revision only with the reads on the
    chain. A ticket edited after the last poll was invisible to it: the act froze the old
    draft and labelled the edited ticket ``crb:queued``, as if its new words were on the
    backlog. The act now reads the ticket under the lease and refuses (409
    ``revision_moved``) when its content no longer matches the waiting draft — nothing
    is registered and nothing is written on the board."""
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
    board = fake_tracker_path(tmp_path)
    edited = json.loads(board.read_text(encoding="utf-8"))
    edited["tickets"]["4711"]["title"] = "Fix the crash when the cart is empty or full"
    edited["tickets"]["4711"]["revision"] = "2"
    board.write_text(json.dumps(edited), encoding="utf-8")
    before = board.read_text(encoding="utf-8")
    r = _register(env, revision="1")
    assert r.status_code == 409, r.text
    assert envelope(r)["code"] == "revision_moved"
    assert "changed" in envelope(r)["message"]
    assert board.read_text(encoding="utf-8") == before
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404
    assert _events(env, "intake.approved") == []
    # the next poll reads the new words, and THAT draft registers
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
    assert _register(env, revision="2").status_code == 200


def test_a_ticket_that_cannot_be_read_at_register_is_a_502_and_nothing_is_written(
    env: Env, tmp_path: Path
) -> None:
    """The live read is part of the act: when the tracker cannot answer it, the act does
    not fall back to the stored read. It is 502 ``tracker_error`` with the published
    advice, and nothing is registered or written."""
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
    board = fake_tracker_path(tmp_path)
    gone = json.loads(board.read_text(encoding="utf-8"))
    del gone["tickets"]["4711"]
    board.write_text(json.dumps(gone), encoding="utf-8")
    r = _register(env, revision="1")
    assert r.status_code == 502, r.text
    assert envelope(r)["code"] == "tracker_error"
    assert board.read_text(encoding="utf-8") == json.dumps(gone)
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404
    assert _events(env, "intake.approved") == []


def test_a_poll_whose_lease_was_taken_over_is_a_409_and_writes_nothing_more(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #55 review: a pass that outlives its lease can be taken over while it still
    works. The served poll goes through the lease fence, so a pass that can no longer
    renew its lease must stop before its first tracker call and answer 409 ``intake_busy``
    rather than read and write beside the new holder."""
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    board = fake_tracker_path(tmp_path)
    before = board.read_text(encoding="utf-8")
    monkeypatch.setattr(sv.DbLease, "renew", lambda self: False)
    r = env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll")
    assert r.status_code == 409, r.text
    assert envelope(r)["code"] == "intake_busy"
    assert "took the column over" in envelope(r)["message"]
    assert board.read_text(encoding="utf-8") == before


def test_a_register_act_whose_lease_was_taken_over_is_a_409_and_writes_nothing(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Register act goes through the same fence: a lost lease at its live read must be
    409 ``intake_busy`` with nothing registered and nothing written on the board."""
    login(env.client, "operator")
    assert _switch(env, True).status_code == 200
    assert env.client.post(f"{API_PREFIX}/factory/{ALPHA}/intake/poll").status_code == 200
    board = fake_tracker_path(tmp_path)
    before = board.read_text(encoding="utf-8")
    monkeypatch.setattr(sv.DbLease, "renew", lambda self: False)
    r = _register(env, revision="1")
    assert r.status_code == 409, r.text
    assert envelope(r)["code"] == "intake_busy"
    assert board.read_text(encoding="utf-8") == before
    assert env.client.get(f"{API_PREFIX}/factory/{ALPHA}/backlog").status_code == 404
    assert _events(env, "intake.approved") == []


def _passes_without_the_lease(source: str) -> list[str]:
    """``function:line`` for every call of ``poll_repository`` / ``register_approved`` that
    does not pass ``lease=intake_lease(...)`` — a pass without it never asks the switch
    again under the lease."""
    import ast

    out: list[str] = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            if name not in {"poll_repository", "register_approved"}:
                continue
            lease = next((k.value for k in n.keywords if k.arg == "lease"), None)
            ok = (
                isinstance(lease, ast.Call)
                and isinstance(lease.func, ast.Name)
                and lease.func.id == "intake_lease"
            )
            if not ok:
                out.append(f"{fn.name}:{n.lineno}")
    return out


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    poll_repository('r', tracker=t)\n",
        "def f():\n    register_approved('r', 'k', lease=None)\n",
        "def f(held):\n    poll_repository('r', lease=held)\n",
    ],
)
def test_the_lease_ratchet_catches_each_way_back(source: str) -> None:
    assert _passes_without_the_lease(source) != []


def test_every_served_pass_asks_the_switch_again_under_the_lease() -> None:
    """The prevention for the class (PR #55 review): consent read before the lease can be
    stale once the pass holds it. ``IntakeLease`` asks the committed switch again, so
    every served call of a pass — the poll route, the Register act, the worker's timed
    poll — must hand over a fresh ``intake_lease(...)``, and the switch-off must take one
    before it commits."""
    src = Path(__file__).resolve().parents[1] / "src" / "crb" / "server"
    offenders = [
        f"{p.name}::{hit}"
        for p in (src / "worker.py", src / "routes" / "factory.py")
        for hit in _passes_without_the_lease(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert _calls_in(src / "routes" / "factory.py", "intake_lease")["put_intake"] == 1
