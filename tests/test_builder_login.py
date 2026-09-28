"""A run cannot start on a dead builder login (pilot D1, P-205).

The pilot queued a canary on a Claude Code login that answered HTTP 401: the submit gate
checked the credential's presence, the ``/health`` ``builders`` probe read ``ok`` from the
same presence, and the row was filed as a provider outage. These tests pin the prevention:
a build run is refused before it is queued, and before any spend, when its builder's login
failed its last verification; a submit with no fresh verification verifies once first; the
refusal names the builder, the auth mode and the token source label (never the token) and is
recorded; the health probe reads verified / unverified / invalid with its age and never calls
a model; Verify on Settings records what the next submit reads.

Navigation
----------
What it is:   The tests of the builder-login verification cache, the submit gate, the health
              probe's login reading and the two ``/builders`` routes.
What it does: Drives ``POST /runs`` and the Learn-queue gate through ``submit_refusals`` with a
              fake verifier that counts its calls; reads the recorded events; scrapes ``/health``
              repeatedly to prove the probe never verifies; holds every registered builder to a
              verify or a named exemption.
How:          ``fixtures.server_seed.make_env`` (a seeded app), ``FakeJobs`` from the runs-route
              suite (the queue), ``CountingVerifier`` installed over the suite's own fake in
              ``LOGIN_VERIFIERS``; verifications are seeded with ``record_verification``.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/server/builder_login.py (under test), src/crb/server/routes/runs.py
              (``submit_refusals``), src/crb/server/routes/builders.py (the list and the
              Verify),
              src/crb/server/routes/system.py (``probe_builder_logins``), tests/conftest.py
              (``_no_real_builder_login`` — the suite never runs the real CLI)
Tested by:    tests/test_builder_login.py
Touch when:   never for a new repository; when a builder gains a verify, or the refusal's
              words or detail change.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.builders.claude_code import LoginCheck, default_auth
from crb.server import builder_login as bl
from crb.server.app import API_PREFIX
from crb.store.models import Event
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env
from test_server_routes_runs import FakeJobs

SONNET = {"builder": "claude_code", "model": "claude-sonnet-5"}
#: A token-shaped value that must never appear in a response, an event or a log.
TOKEN_TAIL = "Zq9x"


class CountingVerifier:
    """A fake verify: answers ``check`` and counts its calls; ``source`` is what a build would
    resolve now (the cache is compared with it)."""

    def __init__(
        self,
        status: str = "ok",
        source: tuple[str, str] = ("keychain", ""),
        *,
        present: frozenset[str] = frozenset({"cli"}),
    ) -> None:
        self.status = status
        self.source = source
        #: the auth modes whose credential is present — never read from this machine
        self.present = present
        self.calls: list[tuple[str, str]] = []

    def missing(self, auth: str, *, secrets_dir: Path | None = None) -> str:
        del secrets_dir
        return "" if auth in self.present else f"no {auth} credential"

    def verify(self, auth: str, binary: str) -> LoginCheck:
        self.calls.append((auth, binary))
        detail = "pong" if self.status == "ok" else "authentication failed (HTTP 401)"
        return LoginCheck(self.status, detail, source=self.source[0], cli_version="2.1.275")

    def install(self, monkeypatch: pytest.MonkeyPatch) -> CountingVerifier:
        monkeypatch.setitem(
            bl.LOGIN_VERIFIERS,
            "claude_code",
            bl.LoginVerifier(self.verify, lambda auth: self.source, default_auth, self.missing),
        )
        return self


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)
    # the pilot's posture: the deployment's builders log in with the CLI login (auth cli), and
    # the credential is PRESENT (P-003's presence gate passes); whether it WORKS is the question
    monkeypatch.setenv("CRB_CLAUDE_CODE_AUTH", "cli")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-placeholder-not-a-token")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        login(e.client, "operator")
        yield e


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    return FakeJobs().install(monkeypatch)


def _submit(env: Env, **over: Any) -> Any:
    body = {"repo": ALPHA, "kind": "blind", **SONNET, "builder_config": {"auth": "cli"}, **over}
    return env.post("/runs", json=body)


def _events(env: Env, action: str) -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(select(Event).where(Event.action == action).order_by(Event.id)).scalars()
        )


def _seed(
    env: Env,
    status: str,
    *,
    age_s: float = 5.0,
    source: tuple[str, str] = ("keychain", ""),
    auth: str = "cli",
) -> None:
    """A verification of the claude_code ``auth`` login recorded ``age_s`` seconds ago."""
    when = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=age_s)).isoformat(timespec="seconds")
    bl.append_event(
        env.factory,
        trace_id=bl.login_trace("claude_code", auth),
        stage="system",
        action=bl.VERIFIED_ACTION,
        payload={
            "builder": "claude_code",
            "auth": auth,
            "status": status,
            "detail": "pong" if status == "ok" else "authentication failed (HTTP 401)",
            "source": source[0],
            "fingerprint": source[1],
            "checked_at": when,
            "trigger": "settings",
        },
    )


# --- the submit gate ---------------------------------------------------------------------


def test_a_run_on_a_login_last_verified_invalid_is_refused_before_it_is_queued(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pilot's canary, prevented: the login failed its verification a moment ago, so the
    submit is refused with the builder, the auth mode and the source label — nothing queued,
    nothing spent, the verify not run again — and the refusal is an event."""
    fake = CountingVerifier("invalid").install(monkeypatch)
    _seed(env, "invalid")
    r = _submit(env)
    assert r.status_code == 422, r.text
    err = envelope(r)
    assert err["code"] == bl.LOGIN_INVALID_CODE
    assert "Nothing was queued and nothing was spent" in err["message"]
    assert bl.FIX_WHERE in err["message"]
    d = err["detail"]
    assert d["builder"] == "claude_code" and d["auth"] == "cli" and d["source"] == "keychain"
    assert d["state"] == bl.STATE_INVALID and d["status"] == "invalid"
    # the way forward names the mode that was refused, so Settings verifies THAT login
    assert d["age_s"] is not None and d["fix_path"] == "/settings?auth=cli#claude-code-login"
    assert jobs.enqueued == [] and fake.calls == []
    (refused,) = _events(env, bl.REFUSED_ACTION)
    assert refused.payload_json["builder"] == "claude_code" and refused.repo == ALPHA
    assert refused.actor  # the operator who submitted


def test_a_submit_with_no_fresh_verification_verifies_once_first(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CountingVerifier("ok").install(monkeypatch)
    assert _submit(env).status_code == 201
    assert fake.calls == [("cli", "")]  # one verification, for the mode the run will use
    assert _submit(env).status_code == 201
    assert len(fake.calls) == 1  # the second submit reads the fresh result
    (verified,) = _events(env, bl.VERIFIED_ACTION)
    assert verified.payload_json["trigger"] == bl.TRIGGER_SUBMIT
    assert len(jobs.enqueued) == 2


def test_a_first_verification_that_fails_refuses_the_submit_and_is_recorded(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CountingVerifier("invalid").install(monkeypatch)
    r = _submit(env)
    assert r.status_code == 422 and envelope(r)["code"] == bl.LOGIN_INVALID_CODE
    assert len(fake.calls) == 1 and jobs.enqueued == []
    assert len(_events(env, bl.VERIFIED_ACTION)) == 1
    assert _submit(env).status_code == 422
    assert len(fake.calls) == 1  # refused on the recorded outcome — no second spend


@pytest.mark.parametrize("status", ["cli_missing", "timeout", "error"])
def test_any_failed_verification_fails_closed(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    CountingVerifier(status).install(monkeypatch)
    r = _submit(env)
    assert r.status_code == 422 and envelope(r)["detail"]["status"] == status
    assert jobs.enqueued == []


def test_an_old_verification_is_verified_again(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CountingVerifier("ok").install(monkeypatch)
    _seed(env, "invalid", age_s=env.settings.builder.login_ttl_s + 60)
    assert _submit(env).status_code == 201
    assert len(fake.calls) == 1  # past the TTL the old failure no longer decides


def test_a_replaced_token_is_verified_again_rather_than_judged_by_the_old_one(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CountingVerifier("ok", source=("secrets_file", "wxyz")).install(monkeypatch)
    _seed(env, "invalid", source=("secrets_file", "abcd"))
    assert _submit(env).status_code == 201
    assert len(fake.calls) == 1


def test_a_run_that_calls_no_builder_is_not_gated(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CountingVerifier("invalid").install(monkeypatch)
    _seed(env, "invalid")
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine"})
    assert r.status_code == 201, r.text
    assert fake.calls == []


def test_the_refusal_never_carries_the_token(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    CountingVerifier("invalid", source=("env", TOKEN_TAIL)).install(monkeypatch)
    r = _submit(env)
    assert r.status_code == 422
    assert "placeholder-not-a-token" not in r.text
    stored = json.dumps([e.payload_json for e in _events(env, bl.VERIFIED_ACTION)])
    stored += json.dumps([e.payload_json for e in _events(env, bl.REFUSED_ACTION)])
    assert "placeholder-not-a-token" not in stored
    assert envelope(r)["detail"]["fingerprint"] == TOKEN_TAIL  # at most four characters


def test_every_registered_builder_has_a_verify_or_says_why_not() -> None:
    """A new builder cannot skip the login gate silently (P-205's class, ratcheted like P-003)."""
    from crb.builders import _REGISTRY

    names = {*_REGISTRY, "fixture_gold"}
    assert not set(bl.LOGIN_VERIFIERS) & set(bl.LOGIN_VERIFY_EXEMPT)
    for name in names:
        assert name in bl.LOGIN_VERIFIERS or name in bl.LOGIN_VERIFY_EXEMPT, name
    assert all(why.strip() for why in bl.LOGIN_VERIFY_EXEMPT.values())


def test_the_real_claude_code_verify_probes_the_mode_and_the_configured_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry's claude_code entry (the suite replaces it with a fake) calls the builder's
    one verify with the run's auth mode and the configured CLI — never another probe."""
    seen: dict[str, Any] = {}

    def fake_verify_login(**kw: Any) -> LoginCheck:
        seen.update(kw)
        return LoginCheck("ok")

    monkeypatch.setattr(bl, "verify_login", fake_verify_login)
    assert bl._claude_code_verify("api_key", "/opt/claude").status == "ok"
    assert seen == {"auth": "api_key", "binary": "/opt/claude"}


# --- the health probe and the routes -----------------------------------------------------


def _builders_probe(env: Env) -> dict[str, Any]:
    body = env.client.get(f"{API_PREFIX}/health").json()
    return next(p for p in body["probes"] if p["name"] == "builders")


def test_the_builders_probe_reads_the_login_from_the_cache_and_never_verifies(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never ``ok`` from presence: a present login is ``unverified`` until verified, ``invalid``
    with its age after a failed verification, ``verified`` after a good one — and no scrape
    runs the verify."""
    fake = CountingVerifier("ok").install(monkeypatch)
    probe = _builders_probe(env)
    (row,) = probe["data"]["logins"]
    assert row["present"] is True and row["state"] == bl.STATE_UNVERIFIED
    assert probe["status"] == "degraded" and "not verified" in probe["detail"]
    _seed(env, "invalid")
    probe = _builders_probe(env)
    assert probe["status"] == "degraded" and "login invalid" in probe["detail"]
    assert probe["data"]["logins"][0]["state"] == bl.STATE_INVALID
    assert probe["data"]["logins"][0]["age_s"] is not None
    _seed(env, "ok")
    probe = _builders_probe(env)
    assert probe["data"]["logins"][0]["state"] == bl.STATE_VERIFIED
    assert "verified" in probe["detail"]
    for _ in range(3):
        _builders_probe(env)
    assert fake.calls == []  # the probe reads; it never calls a model


def test_verify_on_settings_records_what_the_next_submit_reads(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CountingVerifier("ok").install(monkeypatch)
    listed = env.get("/builders/logins").json()["items"]
    assert [x["builder"] for x in listed] == ["claude_code"]
    assert listed[0]["state"] == bl.STATE_UNVERIFIED
    r = env.post("/builders/claude_code/login/verify")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == bl.STATE_VERIFIED and r.json()["trigger"] == bl.TRIGGER_SETTINGS
    assert _submit(env).status_code == 201
    assert len(fake.calls) == 1  # the submit read the Settings verification
    again = env.post("/builders/claude_code/login/verify")
    assert again.status_code == 429  # one deployment-wide limiter with the stored-token verify
    assert env.post("/builders/openai_agent/login/verify").status_code in (404, 429)


def test_the_verify_route_is_for_operators(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    CountingVerifier("ok").install(monkeypatch)
    login(env.client, "viewer")
    assert env.post("/builders/claude_code/login/verify").status_code == 403
    assert env.get("/builders/logins").status_code == 200


def test_the_stored_token_verify_records_only_when_builds_use_that_token(
    env: Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The existing Verify of the stored token (admin) feeds the cache only when that token is
    the login a ``cli`` build resolves; with a token in the worker's environment overriding
    it, the stored token's outcome says nothing about the builds, and nothing is recorded."""
    from crb.builders import claude_code as cc

    monkeypatch.setenv("CRB_SECRETS_DIR", str(tmp_path / "secrets"))
    login(env.client, "admin")
    token = "sk-ant-oat01-" + "a" * 40 + TOKEN_TAIL
    assert env.put("/settings/secrets/claude-code-token", json={"token": token}).status_code == 200

    def fake(**kw: Any) -> LoginCheck:
        return LoginCheck("ok", "pong", source="explicit", fingerprint=TOKEN_TAIL)

    monkeypatch.setattr("crb.server.secrets.verify_login", fake)
    assert env.post("/settings/secrets/claude-code-token/verify").status_code == 200
    assert _events(env, bl.VERIFIED_ACTION) == []  # the env token overrides it: not recorded
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.setattr(
        "crb.server.builder_login.LOGIN_VERIFIERS",
        {
            "claude_code": bl.LoginVerifier(
                lambda a, b: LoginCheck("ok"), cc.login_resolution, default_auth
            ),
        },
    )
    env.client.app.state.verify_limiter = None  # a fresh rate window
    assert env.post("/settings/secrets/claude-code-token/verify").status_code == 200
    (ev,) = _events(env, bl.VERIFIED_ACTION)
    assert ev.payload_json["trigger"] == bl.TRIGGER_STORED_TOKEN
    assert (
        ev.payload_json["source"] == "secrets_file" and ev.payload_json["fingerprint"] == TOKEN_TAIL
    )
    assert token not in json.dumps(ev.payload_json)


def test_a_factory_run_on_a_dead_login_is_refused_before_its_backlog_is_pinned(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The factory's submission meets the same gate, first: a factory run whose builder's
    login failed its verification is refused before the backlog is pinned or anything is
    queued — the same 422 and the same event as a replay."""
    CountingVerifier("invalid").install(monkeypatch)
    _seed(env, "invalid")
    r = env.post(
        "/runs",
        json={"repo": ALPHA, "kind": "factory", **SONNET, "builder_config": {"auth": "cli"}},
    )
    assert r.status_code == 422, r.text
    assert envelope(r)["code"] == bl.LOGIN_INVALID_CODE
    assert jobs.enqueued == []
    (refused,) = _events(env, bl.REFUSED_ACTION)
    assert refused.payload_json["run_kind"] == "factory"


# --- Q1's review: roles, every auth mode, odd input ---------------------------------------


def test_a_viewer_and_an_anonymous_health_read_never_carry_the_fingerprint(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A viewer is served a login's presence and state only — never its fingerprint, source,
    CLI version or the verification's own words (the F25 rule ``/settings/secrets`` keeps) —
    and ``/health``, which answers without a session, carries no more than a viewer gets.
    The operating roles still read the whole state."""
    CountingVerifier("invalid", source=("env", TOKEN_TAIL)).install(monkeypatch)
    _seed(env, "invalid", source=("env", TOKEN_TAIL))
    full = env.get("/builders/logins").json()["items"]
    assert any(x.get("fingerprint") == TOKEN_TAIL for x in full)  # the operator's view
    login(env.client, "viewer")
    r = env.get("/builders/logins")
    assert r.status_code == 200 and TOKEN_TAIL not in r.text
    for item in r.json()["items"]:
        assert set(item) <= bl.PUBLIC_LOGIN_FIELDS, item
    (cli,) = [x for x in r.json()["items"] if x["auth"] == "cli"]
    assert cli["state"] == bl.STATE_INVALID and cli["present"] is True
    logout(env.client)
    health = env.client.get(f"{API_PREFIX}/health")
    assert health.status_code in (200, 503) and TOKEN_TAIL not in health.text
    probe = next(p for p in health.json()["probes"] if p["name"] == "builders")
    for item in probe["data"]["logins"]:
        assert set(item) <= bl.PUBLIC_LOGIN_FIELDS | {"sentence"}, item
    assert "keychain" not in probe["detail"] and "env" not in probe["detail"].split()


def test_a_cli_refusal_on_an_api_key_default_deployment_is_shown_and_cleared_by_its_verify(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q1's review: the probe, the Settings list and Verify read only the deployment's DEFAULT
    auth mode (``api_key`` unless ``CRB_CLAUDE_CODE_AUTH`` says otherwise), while the run
    dialog's "Use my Claude Code login" submits ``auth: cli``. A ``cli`` login recorded
    invalid was invisible — ``/health`` read the builders ``ok`` from presence, the pilot's
    D1 words — and Verify checked ``api_key``, so the refused run stayed refused. Every mode
    with a present credential or a recorded verification is now read, and the way forward
    verifies the mode that was refused."""
    monkeypatch.delenv("CRB_CLAUDE_CODE_AUTH")
    fake = CountingVerifier("invalid", present=frozenset({"cli"})).install(monkeypatch)
    r = _submit(env)  # builder_config {"auth": "cli"}
    assert r.status_code == 422 and envelope(r)["code"] == bl.LOGIN_INVALID_CODE
    assert envelope(r)["detail"]["fix_path"] == "/settings?auth=cli#claude-code-login"
    probe = _builders_probe(env)
    assert probe["status"] == "degraded" and "login invalid" in probe["detail"], probe
    modes = {x["auth"]: x for x in probe["data"]["logins"]}
    assert modes["cli"]["state"] == bl.STATE_INVALID and modes["cli"]["present"] is True
    assert modes["api_key"]["default"] is True and modes["cli"]["default"] is False
    listed = {x["auth"]: x for x in env.get("/builders/logins").json()["items"]}
    assert listed["cli"]["state"] == bl.STATE_INVALID
    fake.status = "ok"
    v = env.post("/builders/claude_code/login/verify", params={"auth": "cli"})
    assert v.status_code == 200 and v.json()["auth"] == "cli", v.text
    assert fake.calls[-1] == ("cli", "")
    assert _submit(env).status_code == 201
    after = _builders_probe(env)
    assert "login invalid" not in after["detail"], after
    assert {x["auth"]: x["state"] for x in after["data"]["logins"]}["cli"] == bl.STATE_VERIFIED


@pytest.mark.parametrize("auth", ["CLI", "password"])
def test_an_auth_mode_the_builder_does_not_have_is_refused_by_name(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch, auth: str
) -> None:
    """Q1's review: ``{"auth": "CLI"}`` passed the presence check and then raised inside the
    real verify — a 500. It is refused 422 with the modes the builder has, nothing queued."""
    fake = CountingVerifier("ok").install(monkeypatch)
    r = _submit(env, builder_config={"auth": auth})
    assert r.status_code == 422, r.text
    err = envelope(r)
    assert err["code"] == "validation_error" and "api_key" in err["message"], err
    assert jobs.enqueued == [] and fake.calls == []


def test_a_verify_that_raises_is_recorded_and_refuses_the_run(
    env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verify that raises (a CLI that cannot run, a bug in a verifier) is a failed
    verification — recorded ``error`` with the exception's words, and the run refused
    ``builder_login_invalid`` — never an unnamed 500."""

    def boom(auth: str, binary: str) -> LoginCheck:
        raise RuntimeError("the verifier fell over")

    monkeypatch.setitem(
        bl.LOGIN_VERIFIERS,
        "claude_code",
        bl.LoginVerifier(boom, lambda a: ("keychain", ""), default_auth, lambda a, **k: ""),
    )
    r = _submit(env)
    assert r.status_code == 422, r.text
    assert envelope(r)["code"] == bl.LOGIN_INVALID_CODE
    assert envelope(r)["detail"]["status"] == "error"
    (verified,) = _events(env, bl.VERIFIED_ACTION)
    assert "the verifier fell over" in verified.payload_json["detail"]
    assert jobs.enqueued == []
