"""The app factory: settings, middleware, error envelope, router seam.

Hermetic: a temp SQLite database per test, no network, no docker (sandbox=local).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from crb.core.execution import SandboxUnavailable
from crb.core.grade import FalseQ1Violation
from crb.core.ledger import LedgerIntegrityError
from crb.server.app import API_PREFIX, SECURITY_HEADERS, create_app, register_routers
from crb.server.auth import require_role
from crb.server.settings import ROLE_LADDER, Settings

ROOT_PW = "correct-horse-battery-staple"


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
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def login(c: TestClient, username: str = "root", password: str = ROOT_PW) -> str:
    r = c.post(f"{API_PREFIX}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    token = c.cookies["crb_csrf"]
    c.headers["X-CSRF-Token"] = token
    return token


# --- settings --------------------------------------------------------------------------


class TestSettings:
    def test_prod_requires_secret_key(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="CRB_SECRET_KEY is required"):
            Settings(env="prod", home=tmp_path)

    def test_short_secret_key_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="at least 32"):
            Settings(env="dev", home=tmp_path, secret_key=SecretStr("short"))

    def test_dev_generates_key_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.settings"):
            s = Settings(env="dev", home=tmp_path)
        assert s.secret_key is not None
        assert len(s.secret_key_value) >= 32
        assert any("generated an ephemeral key" in r.message for r in caplog.records)

    def test_cookie_secure_defaults_by_env(self, tmp_path: Path) -> None:
        assert make_settings(tmp_path).resolved_cookie_secure is False
        prod = Settings(env="prod", home=tmp_path, secret_key=SecretStr("p" * 40))
        assert prod.resolved_cookie_secure is True
        assert make_settings(tmp_path, cookie_secure=True).resolved_cookie_secure is True
        assert (
            Settings(
                env="prod", home=tmp_path, secret_key=SecretStr("p" * 40), cookie_secure=False
            ).resolved_cookie_secure
            is False
        )

    def test_env_prefix_and_nested_delimiter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CRB_ENV", "dev")
        monkeypatch.setenv("CRB_HOME", str(tmp_path))
        monkeypatch.setenv("CRB_CORS_ORIGINS", "https://a.example, https://b.example")
        monkeypatch.setenv("CRB_OIDC__ISSUER", "https://login.example/tenant")
        monkeypatch.setenv("CRB_OIDC__CLIENT_ID", "cid")
        monkeypatch.setenv("CRB_OIDC__ROLE_MAP", '{"crb-admins": "admin", "crb-ops": "operator"}')
        monkeypatch.setenv("CRB_OIDC__ADMIN_GROUPS", '["grp-1"]')
        monkeypatch.setenv("CRB_SANDBOX__EXECUTOR", "local")
        monkeypatch.setenv("CRB_RETENTION__TRANSCRIPTS_DAYS", "14")
        s = Settings()
        assert s.cors_origins == ["https://a.example", "https://b.example"]
        assert s.oidc.enabled and s.oidc.role_map == {"crb-admins": "admin", "crb-ops": "operator"}
        assert s.oidc.admin_groups == ["grp-1"]
        assert s.sandbox.executor == "local"
        assert s.retention.transcripts_days == 14
        assert s.resolved_database_url == f"sqlite:///{tmp_path / 'crb.db'}"

    def test_role_map_unknown_role_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="unknown roles"):
            make_settings(tmp_path, oidc={"role_map": {"g": "superuser"}})

    def test_short_bootstrap_password_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="at least 12"):
            make_settings(tmp_path, bootstrap_admin={"username": "root", "password": "short"})

    def test_redacted_dict_has_no_secret_values(self, tmp_path: Path) -> None:
        s = make_settings(
            tmp_path,
            database_url="postgresql+psycopg://crb:dbpassword-xyz@db.internal/crb",
            oidc={
                "issuer": "https://login.example",
                "client_id": "cid",
                "client_secret": "oidc-client-secret-value",
            },
        )
        dumped = json.dumps(s.redacted_dict())
        for secret in ("s" * 40, ROOT_PW, "dbpassword-xyz", "oidc-client-secret-value"):
            assert secret not in dumped
        d = s.redacted_dict()
        assert d["database"] == {"dialect": "postgresql"}
        assert d["secret_key_configured"] is True
        assert d["oidc"]["client_secret_configured"] is True
        assert d["bootstrap_admin"] == {"username": "root", "password_configured": True}
        assert d["sandbox"] == {"executor": "local", "image": ""}


# --- factory + seam ---------------------------------------------------------------------


class TestFactory:
    def test_register_routers_mounts_core_modules(self, settings: Settings) -> None:
        app = create_app(settings, mount_routes=False)
        with TestClient(app) as c:
            assert c.get(f"{API_PREFIX}/version").status_code == 404
        mounted = register_routers(app)
        assert mounted == [  # core (W2-A) + domain (W2-B), sorted — the seam mounts every module
            "admin",
            "auth",
            "capability",
            "factory",
            "forecast",
            "grades",
            "ledger",
            "oracle",
            "repos",
            "runs",
            "signoffs",
            "system",
        ]
        with TestClient(app) as c:
            assert c.get(f"{API_PREFIX}/version").status_code == 200

    def test_lifespan_opens_db_and_bootstraps_once(
        self, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="crb.server.auth"):
            for _ in range(2):
                with TestClient(create_app(settings)) as c:
                    login(c)
                    users = c.get(f"{API_PREFIX}/users").json()
                    assert users["total"] == 1
                    assert users["items"][0]["role"] == "admin"
        notices = [r for r in caplog.records if "bootstrap admin" in r.message]
        assert len(notices) == 1
        assert ROOT_PW not in notices[0].getMessage()
        assert (settings.home / "crb.db").exists()

    def test_injected_session_factory_is_used(self, tmp_path: Path) -> None:
        from crb.store.db import make_engine, make_session_factory

        engine = make_engine(f"sqlite:///{tmp_path / 'injected.db'}")
        factory = make_session_factory(engine)
        s = make_settings(tmp_path / "unused")
        with TestClient(create_app(s, factory)) as c:
            assert c.get(f"{API_PREFIX}/health").status_code == 200
        assert (tmp_path / "injected.db").exists()
        assert not (tmp_path / "unused" / "crb.db").exists()

    def test_health_detects_dropped_triggers_and_restart_heals(self, tmp_path: Path) -> None:
        from sqlalchemy import text

        from crb.store.db import make_engine, make_session_factory

        engine = make_engine(f"sqlite:///{tmp_path / 'store.db'}")
        factory = make_session_factory(engine)
        with TestClient(create_app(make_settings(tmp_path), factory)) as c:
            with factory() as s:
                for t in ("grades_no_update", "grades_no_delete"):
                    s.execute(text(f"DROP TRIGGER {t}"))
                s.commit()
            r = c.get(f"{API_PREFIX}/health")
            assert r.status_code == 503
            assert r.json()["status"] == "down"
            probe = next(p for p in r.json()["probes"] if p["name"] == "append_only")
            assert probe["status"] == "down"
            assert probe["data"] == {"triggers": 6, "expected": 8}
        # init_db is idempotent: a restart reinstalls the missing triggers.
        with TestClient(create_app(make_settings(tmp_path), factory)) as c:
            r = c.get(f"{API_PREFIX}/health")
            probe = next(p for p in r.json()["probes"] if p["name"] == "append_only")
            assert probe["status"] == "ok"
            assert probe["data"] == {"triggers": 8, "expected": 8}


# --- middleware --------------------------------------------------------------------------


class TestMiddleware:
    def test_security_headers_present(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/version")
        for name, value in SECURITY_HEADERS.items():
            assert r.headers[name] == value
        assert r.headers["Cache-Control"] == "no-store"
        assert "Strict-Transport-Security" not in r.headers  # dev: cookie_secure False

    def test_hsts_when_secure(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path, cookie_secure=True))) as c:
            r = c.get(f"{API_PREFIX}/version")
        assert r.headers["Strict-Transport-Security"].startswith("max-age=")

    def test_request_id_generated_and_echoed(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/version")
        assert len(r.headers["X-Request-ID"]) == 32
        r = client.get(f"{API_PREFIX}/version", headers={"X-Request-ID": "trace-abc.1"})
        assert r.headers["X-Request-ID"] == "trace-abc.1"
        r = client.get(f"{API_PREFIX}/version", headers={"X-Request-ID": "bad id <script>"})
        assert r.headers["X-Request-ID"] != "bad id <script>"

    def test_access_log_is_structured_and_redacted(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="crb.server.access"):
            client.get(
                f"{API_PREFIX}/nope/sk-live-abcdefghijklmnopqrstuvwxyz012345?token=secret-value"
            )
            client.get(f"{API_PREFIX}/version", headers={"X-Request-ID": "req-1"})
        records = [r for r in caplog.records if r.name == "crb.server.access"]
        assert len(records) == 2
        first = records[0]
        assert first.status == 404  # type: ignore[attr-defined]
        assert "REDACTED" in first.path  # type: ignore[attr-defined]
        assert "secret-value" not in first.getMessage()
        second = records[1]
        assert second.route == f"{API_PREFIX}/version"  # type: ignore[attr-defined]
        assert second.request_id == "req-1"  # type: ignore[attr-defined]
        assert second.duration_ms >= 0  # type: ignore[attr-defined]

    def test_cors_only_when_configured(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path))) as c:
            r = c.options(
                f"{API_PREFIX}/version",
                headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "GET"},
            )
            assert "access-control-allow-origin" not in r.headers
        s = make_settings(tmp_path, cors_origins=["https://ui.example"])
        with TestClient(create_app(s)) as c:
            r = c.options(
                f"{API_PREFIX}/version",
                headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "GET"},
            )
            assert r.headers["access-control-allow-origin"] == "https://ui.example"
            assert r.headers["access-control-allow-credentials"] == "true"


# --- error envelope ---------------------------------------------------------------------


def _envelope(r: Any) -> dict[str, Any]:
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "detail"}
    return dict(body["error"])


class TestErrorEnvelope:
    def test_404_and_405(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/does-not-exist")
        assert r.status_code == 404
        assert _envelope(r)["code"] == "not_found"
        r = client.delete(f"{API_PREFIX}/version")
        assert r.status_code == 405
        assert _envelope(r)["code"] == "method_not_allowed"

    def test_422_validation_never_echoes_input(self, client: TestClient) -> None:
        r = client.post(f"{API_PREFIX}/auth/login", json={"username": "root", "password": ""})
        assert r.status_code == 422
        e = _envelope(r)
        assert e["code"] == "validation_error"
        assert e["detail"]["errors"][0]["loc"] == ["body", "password"]
        assert "input" not in e["detail"]["errors"][0]
        assert "url" not in e["detail"]["errors"][0]

    def test_domain_exceptions_map_to_reserved_codes(self, settings: Settings) -> None:
        app = create_app(settings)

        class SignoffRefused(Exception):  # a sibling workstream's type, matched by NAME
            pass

        def _false_q1() -> None:
            raise FalseQ1Violation("ledger refuses clean row with failed belt")

        def _signoff() -> None:
            raise SignoffRefused("false-Q1 present in cell")

        def _integrity() -> None:
            raise LedgerIntegrityError("chain broken at seq 7")

        def _sandbox() -> None:
            raise SandboxUnavailable("docker daemon unreachable; token=sk-live-abcdefghijklmnop")

        def _boom() -> None:
            raise RuntimeError("unexpected")

        app.add_api_route("/api/v1/_t/false_q1", _false_q1, methods=["GET"])
        app.add_api_route("/api/v1/_t/signoff", _signoff, methods=["GET"])
        app.add_api_route("/api/v1/_t/integrity", _integrity, methods=["GET"])
        app.add_api_route("/api/v1/_t/sandbox", _sandbox, methods=["GET"])
        app.add_api_route("/api/v1/_t/boom", _boom, methods=["GET"])
        with TestClient(app, raise_server_exceptions=False) as c:
            for path in ("false_q1", "signoff", "integrity"):
                r = c.get(f"/api/v1/_t/{path}")
                assert r.status_code == 409, path
                assert _envelope(r)["code"] == "false_q1_refused"
            r = c.get("/api/v1/_t/sandbox")
            assert r.status_code == 503
            e = _envelope(r)
            assert e["code"] == "sandbox_unavailable"
            assert "sk-live" not in e["message"]  # redacted
            assert e["detail"] == {"exception": "SandboxUnavailable"}
            r = c.get("/api/v1/_t/boom")
            assert r.status_code == 500
            e = _envelope(r)
            assert e["code"] == "internal_error"
            assert "unexpected" not in e["message"]
            assert e["detail"]["request_id"] == r.headers["X-Request-ID"]


# --- RBAC on a caller-registered route -----------------------------------------------


class TestRbacSeam:
    def test_require_role_ladder(self, settings: Settings) -> None:
        app = create_app(settings)
        for role in ROLE_LADDER:

            def _ok(role: str = role) -> dict[str, str]:
                return {"ok": role}

            app.add_api_route(
                f"/api/v1/_rbac/{role}",
                _ok,
                methods=["GET"],
                dependencies=[Depends(require_role(role))],
            )
        with TestClient(app) as c:
            r = c.get("/api/v1/_rbac/viewer")
            assert r.status_code == 401
            assert _envelope(r)["code"] == "unauthenticated"
            login(c)
            for name, role in (
                ("viewer1", "viewer"),
                ("op1", "operator"),
                ("appr1", "approver"),
            ):
                r = c.post(
                    f"{API_PREFIX}/users",
                    json={"username": name, "password": "long-enough-password", "role": role},
                )
                assert r.status_code == 201, r.text
            matrix = {
                "root": {"viewer": 200, "operator": 200, "approver": 200, "admin": 200},
                "appr1": {"viewer": 200, "operator": 200, "approver": 200, "admin": 403},
                "op1": {"viewer": 200, "operator": 200, "approver": 403, "admin": 403},
                "viewer1": {"viewer": 200, "operator": 403, "approver": 403, "admin": 403},
            }
            for username, expected in matrix.items():
                login(c, username, ROOT_PW if username == "root" else "long-enough-password")
                for role, status in expected.items():
                    r = c.get(f"/api/v1/_rbac/{role}")
                    assert r.status_code == status, (username, role, r.text)
                    if status == 403:
                        e = _envelope(r)
                        assert e["code"] == "forbidden"
                        assert e["detail"] == {"required": role, "actual": matrix_role(username)}


def matrix_role(username: str) -> str:
    return {"root": "admin", "appr1": "approver", "op1": "operator", "viewer1": "viewer"}[username]
