"""``/health``, ``/metrics``, ``/version`` and the admin ``/settings`` view."""

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
from crb.server.app import API_PREFIX, create_app
from crb.server.routes.system import ledger_counts
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
    return make_session_factory(make_engine(f"sqlite:///{tmp_path / 'sys.db'}"))


@pytest.fixture
def client(tmp_path: Path, factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(tmp_path), factory)) as c:
        yield c


def login(c: TestClient) -> None:
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
            assert p["status"] in {"ok", "degraded", "down"}
        assert body["version"] == __version__ and body["apparatus"] == APPARATUS_VERSION
        ao = _probe(body, "append_only")
        assert ao["status"] == "ok"
        assert ao["data"] == {"triggers": 8, "expected": 8}
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
        assert client.get(f"{API_PREFIX}/version").status_code == 200
        assert client.get(f"{API_PREFIX}/metrics").status_code == 200


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
            assert body["oidc"]["client_secret_configured"] is True
            assert body["oidc"]["enabled"] is True
            assert body["oidc"]["role_map"] == {"g": "operator"}
            assert body["bootstrap_admin"]["password_configured"] is True
            assert body["retention"] == {"transcripts_days": 7}
            assert body["sandbox"]["executor"] == "local"
            assert body["database"] == {"dialect": "sqlite"}
            assert body["secret_key_configured"] is True
