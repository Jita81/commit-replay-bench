"""``/health``, ``/metrics``, ``/version`` and the admin ``/settings`` view.

Navigation
----------
What it is:   ``/health``, ``/health/live``, ``/metrics``, ``/version`` and the admin
              ``/settings`` view's test suite.
What it does: Pins the health shape and its append-only probe (an UPDATE is proven refused), that
              a false-Q1 row bypassing the ledger is caught, that a stale worker heartbeat is
              flagged, that health needs no auth; the role-aware sandbox probe (an ``api``
              process reports it ``skipped`` and is not degraded by it; ``worker`` and ``all``
              probe it; the gate is at the function); liveness as a database-only probe that
              never touches the sandbox (the A11 container) and ignores a false-Q1 ledger but
              fails when the database is gone; the metrics exposition (HTTP and ledger series;
              can be disabled); the version carrying apparatus and policy; and the settings view
              requiring admin and redacting.
How:          ``create_app`` over a temp SQLite factory with probes patched at the function seam.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/routes/system.py (under test), src/crb/observability/probes.py
              (the probe results), src/crb/observability/metrics.py (``crb_false_q1_total`` must
              read 0), tests/test_deploy_health_probes.py (the deploy artefacts pointing at these
              endpoints), docs/API.md (health / metrics), docs/DEPLOYMENT.md
Tested by:    tests/test_server_system.py
Touch when:   a probe is added (its role gating and its degraded / down case; the Helm probes in
              tests/test_deploy_health_probes.py if it changes liveness); a metric series is added.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import BELT_SET_V3_LEGACY
from crb.core.routing import POLICY_VERSION
from crb.core.version import APPARATUS_VERSION, __version__
from crb.observability import metrics
from crb.observability.probes import ProbeResult
from crb.server.app import API_PREFIX, create_app
from crb.server.routes.system import ledger_counts, probe_sandbox, process_role
from crb.server.settings import Settings
from crb.store.db import make_engine, make_session_factory
from crb.store.models import Grade, Repo, Run

ROOT_PW = "correct-horse-battery-staple"
PROBE_NAMES = {"db", "append_only", "ledger", "sandbox", "toolchains", "builders", "worker"}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Dev ``Settings`` on ``tmp_path``; ``overrides`` win (``sandbox``, ``metrics_enabled``)."""
    base: dict[str, Any] = {
        "env": "dev",
        "home": tmp_path,
        "secret_key": SecretStr("s" * 40),
        "sandbox": {"executor": "local"},
        "bootstrap_admin": {"username": "root", "password": ROOT_PW},
        "log_format": "text",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory over a fresh SQLite file (tables are created by the app's lifespan)."""
    return make_session_factory(make_engine(f"sqlite:///{tmp_path / 'sys.db'}"))


@pytest.fixture
def client(tmp_path: Path, factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """A started app over ``factory`` behind a ``TestClient``."""
    with TestClient(create_app(make_settings(tmp_path), factory)) as c:
        yield c


def login(c: TestClient) -> None:
    """Log ``c`` in as the bootstrap admin and set the CSRF header."""
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ROOT_PW})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies["crb_csrf"]


def _grade(**overrides: Any) -> Grade:
    base: dict[str, Any] = {
        "row_id": "r" + str(overrides.get("seq", 1)),
        "schema": "grade.v1",
        "repo": "demo",
        "task_id": "t1",
        "created": "2026-01-01T00:00:00+00:00",
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "evidence_pack_hash": "p" * 64,
        "apparatus_version": APPARATUS_VERSION,
        "belt_set": "v4",
        "prev_hash": "0" * 64,
        "row_hash": ("h" + str(overrides.get("seq", 1))) * 8,
    }
    base.update({k: v for k, v in overrides.items() if k != "seq"})
    return Grade(**base)


def _probe(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in body["probes"] if p["name"] == name)


class TestHealth:
    def test_shape_and_append_only_probe(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in {"ok", "degraded"}
        assert {p["name"] for p in body["probes"]} == PROBE_NAMES
        for p in body["probes"]:
            assert set(p) == {"name", "status", "detail", "data"}
            assert p["status"] in {"ok", "degraded", "down", "skipped"}
        assert body["version"] == __version__ and body["apparatus"] == APPARATUS_VERSION
        assert body["role"] == "all"  # no CRB_ROLE: every probe evaluated
        ao = _probe(body, "append_only")
        assert ao["status"] == "ok"
        assert ao["data"] == {"triggers": 10, "expected": 10}
        assert _probe(body, "db")["status"] == "ok"
        assert _probe(body, "db")["data"]["users"] == 1
        assert _probe(body, "ledger") == {
            "name": "ledger",
            "status": "ok",
            "detail": "0 rows, false_q1=0",
            "data": {"rows": 0, "false_q1": 0},
        }
        sandbox = _probe(body, "sandbox")
        assert sandbox["status"] == "degraded" and sandbox["data"] == {"executor": "local"}
        assert _probe(body, "worker")["status"] == "ok"
        assert "no-store" in r.headers["Cache-Control"]

    def test_append_only_probe_proves_update_refused(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        with factory() as s:
            s.add(_grade(seq=1))
            s.commit()
        body = client.get(f"{API_PREFIX}/health").json()
        assert _probe(body, "append_only")["status"] == "ok"
        assert _probe(body, "ledger")["data"] == {"rows": 1, "false_q1": 0}

    def test_false_q1_row_bypassing_the_ledger_is_caught(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        # Written straight through the ORM (the DbLedger would refuse it): a clean row
        # with a failed belt. The store-level watch still catches it.
        with factory() as s:
            s.add(_grade(seq=1))
            s.add(_grade(seq=2, target_green=False))
            # v3-legacy rows record only three belts; source_changed=None is not a failure.
            s.add(_grade(seq=3, belt_set=BELT_SET_V3_LEGACY, source_changed=None))
            s.commit()
        assert ledger_counts(factory) == (3, 1)
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "down"
        ledger = _probe(body, "ledger")
        assert ledger["status"] == "down"
        assert ledger["data"] == {"rows": 3, "false_q1": 1}
        assert "honesty floor" in ledger["detail"]
        m = client.get(f"{API_PREFIX}/metrics").text
        assert "crb_false_q1_total 1.0" in m
        assert "crb_ledger_rows 3.0" in m

    def test_worker_probe_flags_stale_heartbeat(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        fresh = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()
        stale = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=600)).isoformat()
        with factory() as s:
            s.add(Repo(name="demo", language="python", runner="pytest", config_json={}))
            s.add(Run(id="run-fresh", repo="demo", status="running", heartbeat=fresh))
            s.add(Run(id="run-stale", repo="demo", status="running", heartbeat=stale))
            s.add(Run(id="run-noheart", repo="demo", status="running"))
            s.add(Run(id="run-q", repo="demo", status="queued"))
            s.commit()
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        worker = _probe(r.json(), "worker")
        assert worker["status"] == "degraded"
        assert worker["data"]["running"] == 3 and worker["data"]["queued"] == 1
        assert sorted(worker["data"]["stale"]) == ["run-noheart", "run-stale"]
        assert worker["data"]["stale_after_s"] == 120

    def test_health_needs_no_auth(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/health").status_code == 200
        assert client.get(f"{API_PREFIX}/health/live").status_code == 200
        assert client.get(f"{API_PREFIX}/version").status_code == 200
        assert client.get(f"{API_PREFIX}/metrics").status_code == 200


class TestRoleAwareSandboxProbe:
    """The sandbox is the worker's instrument: an ``api`` process reports it ``skipped``
    (never degraded/down — A11: the serve container has no docker socket by design and
    answered 503); ``worker`` / ``all`` (the default) probe it. The role comes from
    ``CRB_ROLE``; anything unrecognised falls back to ``all`` so no probe is hidden."""

    def test_process_role_contract(self) -> None:
        assert process_role({}) == "all"
        assert process_role({"CRB_ROLE": "api"}) == "api"
        assert process_role({"CRB_ROLE": " Worker "}) == "worker"
        assert process_role({"CRB_ROLE": "all"}) == "all"
        assert process_role({"CRB_ROLE": ""}) == "all"
        assert process_role({"CRB_ROLE": "sidecar"}) == "all"  # unrecognised: probe everything
        assert process_role() == "all"  # the autouse fixture cleared CRB_*

    def test_api_role_skips_the_sandbox_and_is_not_degraded_by_it(
        self, tmp_path: Path, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_ROLE", "api")
        # the docker executor with no daemon reachable from this process — the A11 shape
        settings = make_settings(tmp_path, sandbox={"executor": "docker"})
        with TestClient(create_app(settings, factory)) as c:
            r = c.get(f"{API_PREFIX}/health")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["role"] == "api"
            sandbox = _probe(body, "sandbox")
            assert sandbox["status"] == "skipped"
            assert sandbox["data"] == {"executor": "docker", "role": "api"}
            assert "worker's" in sandbox["detail"] and "CRB_ROLE=api" in sandbox["detail"]
            # skipped never lowers the aggregate: the other probes decide
            others = [p["status"] for p in body["probes"] if p["name"] != "sandbox"]
            assert body["status"] == ("degraded" if "degraded" in others else "ok")
            assert "down" not in others

    def test_worker_and_all_roles_probe_the_sandbox(
        self, tmp_path: Path, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path)  # local executor: probed → degraded (dev only)
        for role in ("worker", "all"):
            monkeypatch.setenv("CRB_ROLE", role)
            with TestClient(create_app(settings, factory)) as c:
                body = c.get(f"{API_PREFIX}/health").json()
                assert body["role"] == role
                sandbox = _probe(body, "sandbox")
                assert sandbox["status"] == "degraded"
                assert sandbox["data"] == {"executor": "local"}
        monkeypatch.delenv("CRB_ROLE")
        with TestClient(create_app(settings, factory)) as c:
            body = c.get(f"{API_PREFIX}/health").json()
            assert body["role"] == "all" and _probe(body, "sandbox")["status"] == "degraded"

    def test_probe_sandbox_docker_is_role_gated_at_the_function(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, sandbox={"executor": "docker"})
        assert probe_sandbox(settings, "api").status == "skipped"
        # worker / all consult the daemon (whatever it answers here, it is not "skipped")
        assert probe_sandbox(settings, "worker").status in {"ok", "degraded", "down"}
        assert probe_sandbox(settings).status in {"ok", "degraded", "down"}


class TestLiveness:
    """``/health/live``: the process is up and its database answers — one probe, no
    sandbox, no toolchains, no builders, no ledger. What the image HEALTHCHECK and the
    Helm liveness probe hit, so a dependency outage never restarts a healthy process."""

    def test_live_is_db_only(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health/live")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"status", "probes", "version", "apparatus", "role", "checked_at"}
        assert body["status"] == "ok" and body["role"] == "all"
        assert [p["name"] for p in body["probes"]] == ["db"]
        assert _probe(body, "db")["status"] == "ok"
        assert body["version"] == __version__ and body["apparatus"] == APPARATUS_VERSION
        assert "no-store" in r.headers["Cache-Control"]

    def test_live_never_probes_the_sandbox_even_when_it_would_be_down(
        self, tmp_path: Path, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The A11 container: role unset (``all``), docker executor, no socket. The deep
        probe reports the sandbox; liveness does not even look."""
        monkeypatch.setattr(
            "crb.server.routes.system.probes.probe_docker",
            lambda timeout=10: ProbeResult("sandbox", "down", "no docker socket"),
        )
        settings = make_settings(tmp_path, sandbox={"executor": "docker"})
        with TestClient(create_app(settings, factory)) as c:
            deep = c.get(f"{API_PREFIX}/health")
            assert deep.status_code == 503 and _probe(deep.json(), "sandbox")["status"] == "down"
            live = c.get(f"{API_PREFIX}/health/live")
            assert live.status_code == 200
            assert [p["name"] for p in live.json()["probes"]] == ["db"]

    def test_live_ignores_a_false_q1_ledger_but_fails_when_the_db_is_gone(
        self, client: TestClient, factory: sessionmaker[Session], tmp_path: Path
    ) -> None:
        with factory() as s:
            s.add(_grade(seq=1, target_green=False))  # a false-Q1 row: /health is down
            s.commit()
        assert client.get(f"{API_PREFIX}/health").status_code == 503
        assert client.get(f"{API_PREFIX}/health/live").status_code == 200  # still alive
        # the database gone AFTER startup (startup itself refuses a dead store): the
        # process is up, its store is not — liveness is honestly down (503)
        dead = make_session_factory(make_engine(f"sqlite:///{tmp_path / 'missing' / 'x.db'}"))
        client.app.state.session_factory = dead
        r = client.get(f"{API_PREFIX}/health/live")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "down" and _probe(body, "db")["status"] == "down"
        assert "OperationalError" in _probe(body, "db")["detail"]


class TestMetrics:
    def test_exposition_has_http_and_ledger_series(self, client: TestClient) -> None:
        if not metrics.available():
            pytest.skip("prometheus_client not installed")
        client.get(f"{API_PREFIX}/version")
        client.get(f"{API_PREFIX}/auth/me")  # 401
        r = client.get(f"{API_PREFIX}/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        text = r.text
        assert "crb_false_q1_total 0.0" in text
        assert (
            f'crb_http_requests_total{{method="GET",route="{API_PREFIX}/version",status="200"}}'
            in text
        )
        assert (
            f'crb_http_requests_total{{method="GET",route="{API_PREFIX}/auth/me",status="401"}}'
            in text
        )
        assert (
            f'crb_http_request_duration_seconds_count{{method="GET",route="{API_PREFIX}/version"}}'
            in text
        )
        # Route templates, never raw ids, reach the metrics endpoint.
        client.get(f"{API_PREFIX}/users/some-raw-id/role")
        text = client.get(f"{API_PREFIX}/metrics").text
        assert "some-raw-id" not in text

    def test_metrics_can_be_disabled(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path, metrics_enabled=False))) as c:
            r = c.get(f"{API_PREFIX}/metrics")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "metrics_disabled"


class TestVersion:
    def test_version_carries_apparatus_and_policy(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/version")
        assert r.status_code == 200
        body = r.json()
        assert body["crb"] == __version__
        assert body["apparatus"] == APPARATUS_VERSION
        assert body["policy"] == POLICY_VERSION
        assert isinstance(body["uptime_s"], int) and body["uptime_s"] >= 0


class TestSettingsView:
    def test_settings_requires_admin_and_redacts(self, tmp_path: Path) -> None:
        s = make_settings(
            tmp_path,
            database_url=f"sqlite:///{tmp_path / 'x.db'}",
            oidc={
                "issuer": "https://login.example",
                "client_id": "cid",
                "client_secret": "oidc-secret-value-123",
                "role_map": {"g": "operator"},
            },
            retention={"transcripts_days": 7},
        )
        with TestClient(create_app(s)) as c:
            assert c.get(f"{API_PREFIX}/settings").status_code == 401
            login(c)
            r = c.get(f"{API_PREFIX}/settings")
            assert r.status_code == 200
            body = r.json()
            dumped = json.dumps(body)
            assert "s" * 40 not in dumped
            assert ROOT_PW not in dumped
            assert "oidc-secret-value-123" not in dumped
            # the UI shape (ui/src/api/types.ts `Settings`) …
            assert body["oidc_enabled"] is True
            assert body["retention"] == {"transcripts_days": 7}
            assert body["sandbox_mode"] == "local"
            assert body["ledger_backend"] == "sqlite"
            assert body["apparatus_version"] and body["policy_version"]
            assert {b["name"] for b in body["builders"]} >= {"anthropic", "openai", "azure_openai"}
            assert all(isinstance(b["configured"], bool) for b in body["builders"])
            # … plus the full redacted settings under `raw`
            raw = body["raw"]
            assert raw["oidc"]["client_secret_configured"] is True
            assert raw["oidc"]["enabled"] is True
            assert raw["oidc"]["role_map"] == {"g": "operator"}
            assert raw["bootstrap_admin"]["password_configured"] is True
            assert raw["sandbox"]["executor"] == "local"
            assert raw["database"] == {"dialect": "sqlite"}
            assert raw["secret_key_configured"] is True
