"""``/health``, ``/metrics``, ``/version`` and the admin ``/settings`` view.

Navigation
----------
What it is:   ``/health``, ``/health/live``, ``/metrics``, ``/version`` and the admin
              ``/settings`` view's test suite.
What it does: Pins the health shape and its append-only probe (an UPDATE is proven refused), that
              a false-Q1 row bypassing the ledger is caught, that a stale worker heartbeat is
              flagged, that the ``migrations`` probe is ok at head / degraded for an unstamped
              ``create_all`` store / down (503, revisions named where applicable) when the
              store is behind, ahead, empty or an older unversioned schema, that EVERY probe whose read raises serves one FIXED detail naming the
              request id (the exception logged under that id, never served — CWE-209 on an
              unauthenticated route), that health needs no auth; the role-aware sandbox probe (an ``api``
              process reports it ``skipped`` and is not degraded by it; ``worker`` and ``all``
              probe it; the gate is at the function); liveness as a database-only probe that
              never touches the sandbox (the A11 container) and ignores a false-Q1 ledger but
              fails when the database is gone; the metrics exposition (HTTP and ledger series;
              can be disabled); the version carrying apparatus and policy; and the settings view
              requiring admin and redacting; and that ``/health`` serves the served commits
              (server, checkout, UI bundle) with a ``stale`` flag and a degraded ``build``
              probe on any disagreement (docs/PREVENTION.md P-002).
How:          ``create_app`` over a temp SQLite factory with probes patched at the function seam.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/routes/system.py (under test), src/crb/observability/probes.py
              (the probe results), src/crb/store/migrate.py (``head_status`` behind the
              ``migrations`` probe), src/crb/observability/metrics.py (``crb_false_q1_total``
              must read 0), tests/test_deploy_health_probes.py (the deploy artefacts pointing at
              these endpoints), docs/API.md (health / metrics), docs/DEPLOYMENT.md (the go-live
              checklist that points at the ``migrations`` probe)
Tested by:    tests/test_server_system.py
Touch when:   a probe is added (its role gating and its degraded / down case; the Helm probes in
              tests/test_deploy_health_probes.py if it changes liveness); a metric series is added.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from crb.core.ledger import BELT_SET_V3_LEGACY
from crb.core.routing import POLICY_VERSION
from crb.core.version import APPARATUS_VERSION, __version__
from crb.observability import metrics
from crb.observability.probes import ProbeResult, failure_detail
from crb.server.app import API_PREFIX, create_app
from crb.server.routes.system import (
    collect_health,
    ledger_counts,
    migrations_result,
    probe_migrations,
    probe_sandbox,
    process_role,
)
from crb.server.settings import Settings
from crb.store import migrate
from crb.store.db import make_engine, make_session_factory
from crb.store.models import Grade, Repo, Run, WorkerRow

ROOT_PW = "correct-horse-battery-staple"
PROBE_NAMES = {
    "db",
    "intake",
    "migrations",
    "append_only",
    "ledger",
    "sandbox",
    "toolchains",
    "builders",
    "worker",
    "build",
}


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
        # a fresh store: no worker has checked in yet — honest, not ok (J-TEL-2)
        worker = _probe(body, "worker")
        assert worker["status"] == "degraded" and "no worker has checked in yet" in worker["detail"]
        assert worker["data"]["workers"] == [] and worker["data"]["queued"] == 0
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
            s.add(
                WorkerRow(
                    worker_id="w-1",
                    hostname="h",
                    executor="local",
                    kinds=[],
                    started=fresh,
                    heartbeat=fresh,
                    heartbeat_s=10.0,
                    current_run_id="run-fresh",
                )
            )
            s.commit()
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        worker = _probe(r.json(), "worker")
        assert worker["status"] == "degraded"
        assert worker["data"]["running"] == 3 and worker["data"]["queued"] == 1
        assert sorted(worker["data"]["stale"]) == ["run-noheart", "run-stale"]
        assert worker["data"]["stale_after_s"] == 120
        assert worker["data"]["workers"][0]["current_run_id"] == "run-fresh"

    def test_worker_probe_reads_the_workers_table(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        """J-TEL-2: liveness comes from the ``workers`` table the loop upserts even when
        idle — not from running runs' heartbeats. Queued work with no live worker is
        ``degraded`` with the queue depth and the last check-in (nothing will start) —
        never ``down``: ``/health`` is the API pod's readiness probe and the worker is a
        dependency the API does not own, so a crashed worker must not take the API (and
        the sentence) out of the Service. A worker that stopped checking in is named."""
        now = _dt.datetime.now(_dt.UTC)
        fresh = (now - _dt.timedelta(seconds=4)).isoformat(timespec="seconds")
        with factory() as s:
            s.add(Repo(name="demo", language="python", runner="pytest", config_json={}))
            s.add(Run(id="run-q1", repo="demo", status="queued"))
            s.add(Run(id="run-q2", repo="demo", status="queued"))
            s.add(
                WorkerRow(
                    worker_id="w-1",
                    hostname="node-a",
                    executor="docker",
                    kinds=["replay", "blind"],
                    started=fresh,
                    heartbeat=fresh,
                    heartbeat_s=10.0,
                    current_run_id="",
                    version="x",
                )
            )
            s.commit()
        worker = _probe(client.get(f"{API_PREFIX}/health").json(), "worker")
        assert worker["status"] == "ok"
        assert worker["detail"].startswith("1 worker, last check-in ")
        assert worker["detail"].endswith(" s ago · 2 runs queued")
        w = worker["data"]["workers"][0]
        assert w["worker_id"] == "w-1" and w["alive"] is True and w["hostname"] == "node-a"
        assert w["kinds"] == ["replay", "blind"] and w["current_run_id"] is None
        assert 3 <= w["heartbeat_age_s"] <= 10 and w["stale_after_s"] == 30.0
        assert worker["data"]["queued"] == 2 and worker["data"]["alive"] == 1

        # the worker stops checking in (> 3 × its own heartbeat_s): queued work → degraded,
        # and readiness stays 200 (the API pod is up; the worker is not its liveness)
        stale = (now - _dt.timedelta(seconds=360)).isoformat(timespec="seconds")
        with factory() as s:
            row = s.get(WorkerRow, "w-1")
            assert row is not None
            row.heartbeat = stale
            s.commit()
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "degraded"
        worker = _probe(r.json(), "worker")
        assert worker["status"] == "degraded"
        assert worker["detail"].startswith("2 runs queued, no worker has checked in for ")
        assert (
            "(w-1)" in worker["detail"] and "will not start until a worker does" in worker["detail"]
        )
        assert worker["data"]["workers"][0]["alive"] is False
        assert worker["data"]["alive"] == 0

        # nothing queued: a stale worker is degraded, named, with its age
        with factory() as s:
            for rid in ("run-q1", "run-q2"):
                run = s.get(Run, rid)
                assert run is not None
                run.status = "cancelled"
            s.commit()
        worker = _probe(client.get(f"{API_PREFIX}/health").json(), "worker")
        assert worker["status"] == "degraded"
        assert worker["detail"].startswith("worker w-1 last checked in ")

        # a clean stop is not a stale worker: it is listed as stopped and not alive
        with factory() as s:
            row = s.get(WorkerRow, "w-1")
            assert row is not None
            row.stopped = stale
            s.commit()
        worker = _probe(client.get(f"{API_PREFIX}/health").json(), "worker")
        assert worker["status"] == "degraded"
        assert "no worker has checked in yet" in worker["detail"]
        assert worker["data"]["workers"][0]["stopped"] == stale

        # queued work behind a cleanly stopped worker names the stop, never "for ever"
        with factory() as s:
            s.add(Run(id="run-q3", repo="demo", status="queued"))
            s.commit()
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        worker = _probe(r.json(), "worker")
        assert worker["status"] == "degraded"
        assert worker["detail"].startswith("1 run queued, the last worker (w-1) stopped ")
        assert " s ago — queued runs will not start until a worker does" in worker["detail"]
        assert "ever" not in worker["detail"].replace("never", "")

    def test_worker_probe_reports_unconfirmed_containers_as_degraded(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        """A live, idle worker whose check-in row says it is still reaping a container whose
        ``docker kill`` was never confirmed (revision 0008) is ``degraded`` with the count and
        what to do — the container may still be running on the worker host; ``ok`` again
        once the reaper has emptied its queue."""
        now = _dt.datetime.now(_dt.UTC)
        fresh = (now - _dt.timedelta(seconds=2)).isoformat(timespec="seconds")
        with factory() as s:
            s.add(
                WorkerRow(
                    worker_id="w-1",
                    hostname="node-a",
                    executor="docker",
                    kinds=[],
                    started=fresh,
                    heartbeat=fresh,
                    heartbeat_s=10.0,
                    version="x",
                    unconfirmed_containers=2,
                )
            )
            s.commit()
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200 and r.json()["status"] == "degraded"
        worker = _probe(r.json(), "worker")
        assert worker["status"] == "degraded"
        assert worker["detail"] == (
            "2 containers whose docker kill was not confirmed are being reaped by worker w-1 "
            "— each may still be running on its host; `docker ps` there names them and "
            "`docker rm -f <name>` reaps one by hand"
        )
        assert worker["data"]["unconfirmed_containers"] == 2
        assert worker["data"]["workers"][0]["unconfirmed_containers"] == 2
        with factory() as s:
            row = s.get(WorkerRow, "w-1")
            assert row is not None
            row.unconfirmed_containers = 0
            s.commit()
        worker = _probe(client.get(f"{API_PREFIX}/health").json(), "worker")
        assert worker["status"] == "ok" and worker["data"]["unconfirmed_containers"] == 0

    def test_migrations_probe_is_degraded_for_an_unstamped_create_all_store(
        self, client: TestClient
    ) -> None:
        """The lifespan's ``init_db`` builds a complete schema with no ``alembic_version``:
        complete, so not 503 — but unstamped until ``crb migrate`` runs, and the detail says so."""
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200
        m = _probe(r.json(), "migrations")
        head = migrate.head_revision()
        assert m["status"] == "degraded"
        assert m["detail"] == (
            f"schema matches head {head} but carries no alembic_version (a create_all store) "
            "— run `crb migrate` to stamp it"
        )
        assert m["data"] == {
            "database": None,
            "head": head,
            "at_head": False,
            "unversioned_at": head,
            "matches_models": True,
        }

    def test_migrations_probe_is_ok_at_head_and_down_when_behind(
        self, tmp_path: Path, factory: sessionmaker[Session]
    ) -> None:
        """A migrated store is ``ok`` (``database at <head> = code head``); one stamped behind
        answers 503 with BOTH revisions and the fix in the detail — a half-migrated database
        can no longer pass the go-live checklist."""
        url = f"sqlite:///{tmp_path / 'sys.db'}"
        migrate.upgrade(url)
        head = migrate.head_revision()
        with TestClient(create_app(make_settings(tmp_path), factory)) as c:
            r = c.get(f"{API_PREFIX}/health")
            assert r.status_code == 200
            m = _probe(r.json(), "migrations")
            assert m["status"] == "ok" and m["detail"] == f"database at {head} = code head"
            assert m["data"]["database"] == head and m["data"]["at_head"] is True

            command.stamp(migrate.alembic_config(url), migrate.INITIAL_REVISION)
            r = c.get(f"{API_PREFIX}/health")
            assert r.status_code == 503
            body = r.json()
            assert body["status"] == "down"
            m = _probe(body, "migrations")
            assert m["status"] == "down"
            assert m["detail"] == (
                f"database at {migrate.INITIAL_REVISION}, code head {head} — run `crb migrate` "
                "(the migrate Job / `python -m crb.store.migrate upgrade`)"
            )
            assert m["data"]["database"] == migrate.INITIAL_REVISION
            # liveness never reads the migration head: a pod behind stays up to be migrated
            assert c.get(f"{API_PREFIX}/health/live").status_code == 200

    def test_migrations_result_names_an_empty_and_an_older_store(self) -> None:
        """The shared renderer (``crb doctor`` uses it too): an empty store and an older
        release's unversioned schema are ``down`` and name what was found."""
        empty = migrations_result(migrate.HeadStatus(None, "0006", False))
        assert empty.status == "down"
        assert empty.detail.startswith("database not migrated (empty), code head 0006 — run")
        older = migrations_result(migrate.HeadStatus(None, "0006", False, unversioned_at="0001"))
        assert older.status == "down"
        assert "unversioned schema at 0001" in older.detail and "crb migrate" in older.detail
        ahead = migrations_result(migrate.HeadStatus("0007", "0006", False))
        assert ahead.status == "down" and "database at 0007, code head 0006" in ahead.detail

    def test_migrations_probe_hides_the_exception_from_the_unauthenticated_route(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CWE-209: when the head cannot be read the detail is the fixed sentence — never
        the exception's type or message (a driver error can carry a path, a DSN or SQL) —
        and the exception goes to the log instead."""
        secret = "postgresql://crb:hunter2@db.internal/crb — relation alembic_version"

        def _factory() -> Session:
            raise RuntimeError(secret)

        with caplog.at_level(logging.ERROR, logger="crb.observability.probes"):
            r = probe_migrations(_factory, request_id="rid-1")  # type: ignore[arg-type]
        assert r.status == "down"
        assert r.detail == failure_detail("migrations", "rid-1")
        assert r.detail == "migrations could not be read — see the API log, request id rid-1"
        assert "RuntimeError" not in r.detail and "hunter2" not in r.detail
        assert r.data == {}
        assert any(
            rec.message == "migrations probe failed (request_id=rid-1)" and rec.exc_info
            for rec in caplog.records
        )

    def test_every_raising_probe_serves_the_fixed_detail_and_logs_under_the_request_id(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole ``/health`` body, not one probe: a store that raises reaches ``db``,
        ``migrations``, ``append_only``, ``ledger`` and ``worker``; a probe module that
        raises reaches ``sandbox``, ``toolchains`` and ``builders``. Each serves ONE fixed
        sentence (``<probe> could not be read — see the API log, request id …``) with
        empty ``data``; the driver message — which for PostgreSQL carries host, user and
        DSN — appears nowhere in the body and once per probe in the log, with the id."""
        secret = (
            'connection to server at "db.internal" failed: FATAL password authentication '
            'failed for user "crb" (postgresql://crb:hunter2@db.internal/crb)'
        )

        def _factory() -> Session:
            raise RuntimeError(secret)

        def _boom(*_: Any, **__: Any) -> ProbeResult:
            raise OSError("/var/run/docker.sock: permission denied for uid 10001")

        for fn in ("probe_docker", "probe_toolchains", "probe_builders"):
            monkeypatch.setattr(f"crb.server.routes.system.probes.{fn}", _boom)
        monkeypatch.setattr("crb.server.routes.system.build_stamp.probe_build", _boom)
        settings = make_settings(tmp_path, sandbox={"executor": "docker"})
        with caplog.at_level(logging.ERROR, logger="crb.observability.probes"):
            body = collect_health(_factory, settings, role="all", request_id="req-42")  # type: ignore[arg-type]
        assert body["status"] == "down"
        assert {p["name"] for p in body["probes"]} == PROBE_NAMES
        for p in body["probes"]:
            assert p["status"] == "down", p
            assert p["detail"] == failure_detail(p["name"], "req-42"), p
            assert p["detail"].endswith("— see the API log, request id req-42"), p
            assert p["data"] == {}, p
        served = json.dumps(body)
        for leak in ("RuntimeError", "OSError", "hunter2", "db.internal", "docker.sock", "FATAL"):
            assert leak not in served, leak
        logged = [rec for rec in caplog.records if rec.message.endswith("(request_id=req-42)")]
        assert sorted(rec.message.split(" probe failed")[0] for rec in logged) == sorted(
            PROBE_NAMES
        )
        assert all(rec.exc_info and getattr(rec, "request_id", "") == "req-42" for rec in logged)
        assert any("hunter2" in str(rec.exc_info[1]) for rec in logged if rec.exc_info)

    def test_the_route_stamps_the_caller_s_request_id_into_the_fixed_detail(
        self, client: TestClient
    ) -> None:
        """Through HTTP: the id the middleware assigned (or accepted from ``X-Request-ID``)
        is the one the detail names and the response header echoes, so an operator can
        find the logged exception; the driver's message is not in the body."""
        secret = 'FATAL: password authentication failed for user "crb" (host db.internal)'

        def _dead() -> Session:
            raise RuntimeError(secret)

        client.app.state.session_factory = _dead
        r = client.get(f"{API_PREFIX}/health", headers={"X-Request-ID": "trace-abc"})
        assert r.status_code == 503 and r.headers["X-Request-ID"] == "trace-abc"
        body = r.json()
        for name in ("db", "migrations", "append_only", "ledger", "worker"):
            assert _probe(body, name)["detail"] == failure_detail(name, "trace-abc")
            assert _probe(body, name)["data"] == {}
        assert "RuntimeError" not in r.text and "db.internal" not in r.text
        # the id is assigned when the caller sends none — and still named
        r = client.get(f"{API_PREFIX}/health")
        rid = r.headers["X-Request-ID"]
        assert rid and _probe(r.json(), "db")["detail"] == failure_detail("db", rid)

    def test_health_serves_the_served_commits_and_a_stale_flag(
        self, tmp_path: Path, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P-002: the stack served code behind ``origin/main`` and a UI built from an older
        tree still, and nothing said so. ``/health`` now serves the server's commit (captured
        at start), the checkout's (now) and the bundle's (its build stamp) with ``stale``,
        and the ``build`` probe reads degraded — never 503: stale code still serves."""
        from crb.observability import build_stamp

        a, b = "a" * 40, "b" * 40
        monkeypatch.setattr(build_stamp, "process_commit", lambda: a)
        monkeypatch.setattr(build_stamp, "checkout_commit", lambda root=None: a)
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        stamp = dist / build_stamp.BUILD_STAMP_FILE
        stamp.write_text(json.dumps({"commit": a}), encoding="utf-8")
        settings = make_settings(tmp_path, ui_dist=str(dist))
        with TestClient(create_app(settings, factory)) as c:
            body = c.get(f"{API_PREFIX}/health").json()
            assert body["served"] == {
                "server_commit": a,
                "checkout_commit": a,
                "ui_commit": a,
                "ui_stamp": "stamped",
                "stale": False,
                "reasons": [],
            }
            assert _probe(body, "build")["status"] == "ok"
            # the bundle rebuilt from another tree: stale, with the fix in the sentence
            stamp.write_text(json.dumps({"commit": b}), encoding="utf-8")
            r = c.get(f"{API_PREFIX}/health")
            assert r.status_code == 200 and r.json()["served"]["stale"] is True
            build = _probe(r.json(), "build")
            assert build["status"] == "degraded" and "rebuild it" in build["detail"]
            # a `git pull` under a running server: the process still runs the old commit
            stamp.write_text(json.dumps({"commit": a}), encoding="utf-8")
            monkeypatch.setattr(build_stamp, "checkout_commit", lambda root=None: b)
            served = c.get(f"{API_PREFIX}/health").json()["served"]
            assert served["stale"] is True and "restart the server" in served["reasons"][0]

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
        # the same fixed sentence as the deep probe: the driver's message stays in the log
        assert _probe(body, "db")["detail"] == failure_detail("db", r.headers["X-Request-ID"])
        assert "OperationalError" not in r.text


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


# --- the intake line reports what the last real poll measured ---------------------------


def _intake_probe(tmp_path: Path, factory: sessionmaker[Session], **over: Any) -> ProbeResult:
    from crb.server.routes.system import probe_intake

    kw: dict[str, Any] = {
        "public_url": "https://crb.invalid",
        "intake": {
            "tracker": "ado",
            "url": "https://dev.azure.invalid/contoso",
            "project": "Widgets",
            "column": "Ready for manufacture",
        },
    }
    kw.update(over)
    settings = make_settings(tmp_path, **kw)
    from crb.server.secrets import SecretsFile

    SecretsFile.for_settings(settings).set("tracker_token", "a-tracker-token-value")
    return probe_intake(factory, settings)


def _switch_on(factory: sessionmaker[Session], repo: str) -> None:
    with factory() as s:
        s.add(
            Repo(
                name=repo,
                language="python",
                runner="pytest",
                config_json={"intake": {"enabled": True, "column": "Ready for manufacture"}},
            )
        )
        s.commit()


def test_the_intake_line_is_degraded_when_the_last_read_stopped(
    tmp_path: Path, factory: sessionmaker[Session]
) -> None:
    """A deployment whose every listener is failing ``unauthorised`` used to read
    ``intake: ok``, so monitoring never learned the front door was shut. The probe still
    contacts NO tracker: the stop it reports is the one the last real poll wrote to disk."""
    from crb.server.intake import IntakeStore, PollReport

    with TestClient(create_app(make_settings(tmp_path), factory)):
        pass  # the lifespan creates the tables
    _switch_on(factory, "alpha")
    ok = _intake_probe(tmp_path, factory)
    assert ok.status == "ok"
    assert "stopped at nothing" in ok.detail

    IntakeStore(tmp_path, "alpha").write(
        PollReport(
            repo="alpha",
            column="Ready for manufacture",
            stopped="unauthorised",
            detail="the tracker answered 401",
        )
    )
    bad = _intake_probe(tmp_path, factory)
    assert bad.status == "degraded"
    assert "unauthorised" in bad.detail
    assert "alpha" in bad.detail
    assert bad.data["stopped"] == [
        {"repo": "alpha", "reason": "unauthorised", "detail": "the tracker answered 401"}
    ]


def test_the_intake_line_asks_for_a_credential_only_where_one_is_needed(
    tmp_path: Path, factory: sessionmaker[Session]
) -> None:
    """``tracker: fake`` is the walkthrough's file-backed board and needs no token — the rule
    the consent gate and ``build_tracker`` both apply. The probe checked presence instead, so
    a walkthrough stack read ``intake: degraded`` and told an admin to set a credential while
    every poll was succeeding."""
    from crb.server.routes.system import probe_intake

    with TestClient(create_app(make_settings(tmp_path), factory)):
        pass
    _switch_on(factory, "alpha")
    settings = make_settings(
        tmp_path,
        public_url="https://crb.invalid",
        intake={
            "tracker": "fake",
            "url": "https://tracker.invalid",
            "project": "Widgets",
            "column": "Ready for manufacture",
        },
    )
    r = probe_intake(factory, settings)  # no credential is stored at all
    assert r.data["credential_set"] is False  # still reported, honestly
    assert r.status == "ok"
    assert "credential" not in r.detail


def test_the_intake_line_is_degraded_when_the_deployment_has_no_public_address(
    tmp_path: Path, factory: sessionmaker[Session]
) -> None:
    with TestClient(create_app(make_settings(tmp_path), factory)):
        pass
    r = _intake_probe(tmp_path, factory, public_url="")
    assert r.status == "degraded"
    assert "CRB_PUBLIC_URL" in r.detail
    assert r.data["public_url_set"] is False
