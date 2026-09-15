"""``/repos`` — list/detail shapes, config validation, the audit event + trail, probe, profile, tasks.

Navigation
----------
What it is:   ``/repos``'s test suite — list / detail shapes, config validation, the audit event
              and trail, probe, profile, tasks.
What it does: Pins the list shape (probe, counts, last run), pagination, viewer reads, anonymous
              401, detail with config and 404, create RBAC / validation / the recorded event /
              duplicate 409 / invalid config 422, update RBAC with a redacted diff event, the
              per-repo audit trail newest first, probe RBAC and enqueue (queue unavailable
              handled), profile computed / cached / refreshed and 409 without a clone, and the
              task list with filters.
How:          ``make_env`` over the seed; ``fake_jobs`` stands in for ``crb.store.jobs`` and
              persists the run so the API can read it back.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/routes/repos.py (under test), src/crb/core/spec.py
              (``RepoConfig`` validation), src/crb/store/jobs.py (the probe enqueue),
              tests/fixtures/server_seed.py, docs/API.md (repos), docs/OPERATOR.md (configuring
              a repository from the UI, §2.0)
Tested by:    tests/test_server_routes_repos.py
Touch when:   a ``RepoConfig`` field is added (a validation case and the redacted-diff case; the
              UI form in ui/src/api/types.ts); a repo-level route is added.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.server.app import API_PREFIX
from crb.server.routes.runs import system_trace_id
from crb.store.models import Event, Run
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, BETA, Env, assert_rbac, envelope, login, make_env


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as admin, torn down after the test."""
    with make_env(tmp_path) as e:
        yield e


@pytest.fixture
def fake_jobs(monkeypatch: pytest.MonkeyPatch) -> list[Run]:
    """A stand-in ``crb.store.jobs`` that persists the run and records the call."""
    calls: list[Run] = []

    def enqueue(factory: Any, run: Run) -> Run:
        calls.append(run)
        with factory() as s:
            s.add(run)
            s.commit()
        return run

    def request_cancel(factory: Any, run_id: str) -> bool:
        return True

    mod = types.ModuleType("crb.store.jobs")
    mod.enqueue = enqueue  # type: ignore[attr-defined]
    mod.request_cancel = request_cancel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "crb.store.jobs", mod)
    return calls


class TestList:
    def test_shape_probe_counts_last_run(self, env: Env) -> None:
        r = env.get("/repos")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"items", "total", "limit", "offset"}
        assert body["total"] == 2 and body["limit"] == 50 and body["offset"] == 0
        alpha, beta = body["items"]
        assert alpha["name"] == ALPHA and beta["name"] == BETA
        assert set(alpha) >= {
            "name",
            "language",
            "runner",
            "url",
            "probe",
            "task_counts",
            "last_run",
            "created",
            "updated",
        }
        assert alpha["probe"] == {
            "status": "ok",
            "run_id": env.info.run_ids["probe"],
            "checked": "2026-08-25T09:00:30+00:00",
            "detail": "pytest 8.3 on python 3.12",
        }
        assert alpha["task_counts"] == {
            "total": 8,
            "standard": 7,
            "hard": 1,
            "gold_clean": 7,
            "gold_failed": 0,
            "unchecked": 1,
        }
        assert alpha["last_run"] == {
            "id": env.info.run_ids["running"],
            "kind": "replay",
            "status": "running",
            "finished": None,
        }
        assert beta["probe"]["status"] == "not_probed" and beta["probe"]["run_id"] is None
        assert beta["task_counts"]["total"] == 0 and beta["last_run"] is None

    def test_pagination(self, env: Env) -> None:
        r = env.get("/repos?limit=1&offset=1")
        assert r.json()["items"][0]["name"] == BETA
        assert r.json()["total"] == 2
        assert env.get("/repos?limit=0").status_code == 422
        assert env.get("/repos?limit=501").status_code == 422

    def test_viewer_can_read(self, env: Env) -> None:
        login(env.client, "viewer")
        assert env.get("/repos").status_code == 200
        assert env.get(f"/repos/{ALPHA}").status_code == 200

    def test_anonymous_401(self, env: Env) -> None:
        env.client.cookies.clear()
        r = env.get("/repos")
        assert r.status_code == 401
        assert envelope(r)["code"] == "unauthenticated"


class TestDetail:
    def test_detail_has_config(self, env: Env) -> None:
        r = env.get(f"/repos/{ALPHA}")
        assert r.status_code == 200
        cfg = r.json()["config"]
        assert cfg["name"] == ALPHA and cfg["language"] == "python" and cfg["runner"] == "pytest"
        assert cfg["belt_scope"] == "AFFECTED_DIRS" and cfg["mining"] == {"log_n": 50}
        assert "profile" not in cfg
        assert r.json()["profile_computed_at"] is None

    def test_404(self, env: Env) -> None:
        r = env.get("/repos/nope")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"


class TestCreate:
    def test_rbac(self, env: Env) -> None:
        assert_rbac(
            env,
            "POST",
            "/repos",
            min_role="operator",
            json={"name": "gamma", "language": "python", "clone_path": "/srv/gamma"},
        )

    def test_create_validates_and_records_event(self, env: Env) -> None:
        login(env.client, "operator")
        body = {
            "name": "gamma",
            "language": "py",
            "clone_path": "/srv/gamma",
            "src_prefix": "gamma/",
            "test_prefix": "tests/",
            "belt_scope": ["tests/unit"],
            "runner_opts": {
                "python": "python3",
                "pip": "token=sk-live-abcdefghijklmnopqrstuvwxyz0123",
            },
            "mining": {"log_n": 10},
        }
        r = env.post("/repos", json=body)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["name"] == "gamma" and d["language"] == "python" and d["runner"] == "pytest"
        assert d["config"]["belt_scope"] == ["tests/unit"]
        assert d["config"]["path"] == "/srv/gamma" and d["clone_path"] == "/srv/gamma"
        assert d["probe"]["status"] == "not_probed"
        with env.factory() as s:
            ev = s.execute(select(Event).where(Event.repo == "gamma")).scalar_one()
        assert ev.stage == "system" and ev.action == "repo.created" and ev.seq == 1
        assert "sk-live" not in str(ev.payload_json)  # redacted at construction

    def test_duplicate_409(self, env: Env) -> None:
        r = env.post("/repos", json={"name": ALPHA, "language": "python", "url": "https://x/y.git"})
        assert r.status_code == 409 and envelope(r)["code"] == "already_exists"

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "gamma", "language": "python"},  # neither clone_path nor url
            {"name": "Gamma", "language": "python", "url": "u"},  # uppercase name
            {"name": "gamma", "language": "cobol", "url": "u"},  # unknown language
            {"name": "gamma", "language": "python", "url": "u", "runner": "make"},
            {"name": "gamma", "language": "python", "url": "u", "belt_scope": "EVERYTHING"},
            {"name": "gamma", "language": "python", "url": "u", "test_mode": "suffix"},
            {"name": "gamma", "language": "python", "url": "u", "extra": 1},
        ],
    )
    def test_invalid_config_422_envelope(self, env: Env, body: dict[str, Any]) -> None:
        r = env.post("/repos", json=body)
        assert r.status_code == 422, r.text
        e = envelope(r)
        assert e["code"] == "validation_error"
        assert e["detail"]["errors"]


class TestUpdate:
    def test_rbac(self, env: Env) -> None:
        assert_rbac(env, "PUT", f"/repos/{ALPHA}", min_role="operator", json={"probe": "tests/"})

    def test_update_appends_redacted_diff_event(self, env: Env) -> None:
        r = env.put(
            f"/repos/{ALPHA}",
            json={
                "belt_scope": "TARGET_ONLY",
                "runner_opts": {"pip": "https://user:hunter2-secret-token@pypi.internal/simple"},
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["config"]["belt_scope"] == "TARGET_ONLY"
        assert r.json()["config"]["src_prefix"] == "src/"  # untouched fields survive
        trace = system_trace_id("repo", ALPHA)
        with env.factory() as s:
            events = list(
                s.execute(
                    select(Event).where(Event.trace_id == trace).order_by(Event.seq)
                ).scalars()
            )
        ev = events[-1]
        assert ev.action == "repo.updated" and ev.stage == "system"
        assert sorted(ev.payload_json["fields"]) == ["belt_scope", "runner_opts"]
        assert ev.payload_json["diff"]["belt_scope"] == {
            "from": "AFFECTED_DIRS",
            "to": "TARGET_ONLY",
        }
        assert "hunter2" not in str(ev.payload_json)
        # a second update chains seq within the repo's trace
        r = env.put(f"/repos/{ALPHA}", json={"probe": "tests/test_other.py"})
        assert r.status_code == 200
        with env.factory() as s:
            seqs = [
                e.seq for e in s.execute(select(Event).where(Event.trace_id == trace)).scalars()
            ]
        assert seqs == [1, 2]

    def test_update_invalid_422(self, env: Env) -> None:
        r = env.put(f"/repos/{ALPHA}", json={"runner": "cargo", "language": "python"})
        assert r.status_code == 200  # cargo is a known runner; config accepts it
        r = env.put(f"/repos/{ALPHA}", json={"belt_scope": "NOPE"})
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"
        r = env.put("/repos/nope", json={"probe": "x"})
        assert r.status_code == 404


class TestEvents:
    """``GET /repos/{name}/events`` — the config audit trail as stored, newest first."""

    def test_rbac(self, env: Env) -> None:
        assert_rbac(env, "GET", f"/repos/{ALPHA}/events", min_role="viewer")

    def test_404(self, env: Env) -> None:
        assert env.get("/repos/nope/events").status_code == 404

    def test_seeded_repo_has_no_trail(self, env: Env) -> None:
        # seeded directly into the table (no POST) → an honest empty page, never a
        # fabricated "created" row
        body = env.get(f"/repos/{ALPHA}/events").json()
        assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_trail_is_newest_first_redacted_and_paginated(self, env: Env) -> None:
        login(env.client, "operator")
        r = env.post(
            "/repos",
            json={"name": "gamma", "language": "python", "clone_path": "/srv/gamma"},
        )
        assert r.status_code == 201, r.text
        r = env.put(
            "/repos/gamma",
            json={
                "belt_scope": ["tests/", "tests/acceptance/"],
                "runner_opts": {"pip": ["https://user:hunter2-secret-token@pypi.internal/simple"]},
            },
        )
        assert r.status_code == 200, r.text
        r = env.put("/repos/gamma", json={"probe": "tests/test_smoke.py"})
        assert r.status_code == 200, r.text

        body = env.get("/repos/gamma/events").json()
        assert body["total"] == 3 and body["limit"] == 50 and body["offset"] == 0
        actions = [e["action"] for e in body["items"]]
        assert actions == ["repo.updated", "repo.updated", "repo.created"]
        assert [e["seq"] for e in body["items"]] == [3, 2, 1]
        newest, middle, created = body["items"]
        assert newest["stage"] == "system" and newest["repo"] == "gamma"
        assert newest["actor"]  # the operator's id
        assert newest["payload"]["fields"] == ["probe"]
        assert newest["payload"]["diff"]["probe"] == {"from": "", "to": "tests/test_smoke.py"}
        assert middle["payload"]["fields"] == ["belt_scope", "runner_opts"]
        assert middle["payload"]["diff"]["belt_scope"] == {
            "from": "TARGET_ONLY",
            "to": ["tests/", "tests/acceptance/"],
        }
        assert "hunter2" not in str(middle["payload"])  # redacted at write, served as stored
        assert created["payload"]["config"]["name"] == "gamma"
        assert set(newest) >= {"event_id", "seq", "timestamp", "trace_id", "action", "payload"}

        page = env.get("/repos/gamma/events?limit=1&offset=1").json()
        assert page["total"] == 3 and len(page["items"]) == 1 and page["items"][0]["seq"] == 2

        # a viewer reads the same trail
        login(env.client, "viewer")
        assert env.get("/repos/gamma/events").json()["total"] == 3

    def test_trail_is_per_repo(self, env: Env) -> None:
        login(env.client, "operator")
        assert env.put(f"/repos/{ALPHA}", json={"probe": "tests/x.py"}).status_code == 200
        assert env.get(f"/repos/{ALPHA}/events").json()["total"] == 1
        assert env.get(f"/repos/{BETA}/events").json()["total"] == 0


class TestProbe:
    def test_rbac(self, env: Env, fake_jobs: list[Run]) -> None:
        assert_rbac(env, "POST", f"/repos/{ALPHA}/probe", min_role="operator")

    def test_enqueues_probe_run(self, env: Env, fake_jobs: list[Run]) -> None:
        login(env.client, "operator")
        r = env.post(f"/repos/{ALPHA}/probe")
        assert r.status_code == 201, r.text
        run = r.json()
        assert run["kind"] == "probe" and run["status"] == "queued" and run["repo"] == ALPHA
        assert run["mode"] == "sighted" and run["ladder"] == ["r1"]
        assert len(fake_jobs) == 1
        queued = fake_jobs[0]
        assert queued.kind == "probe" and queued.params_json["probe"] == "tests/test_smoke.py"
        assert queued.actor  # the operator's id
        assert env.get(f"/runs/{run['id']}").status_code == 200

    def test_404_and_queue_unavailable(self, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "crb.store.jobs", None)
        r = env.post("/repos/nope/probe")
        assert r.status_code == 404
        r = env.post(f"/repos/{ALPHA}/probe")
        assert r.status_code == 503 and envelope(r)["code"] == "queue_unavailable"


class TestProfile:
    def test_no_clone_409(self, env: Env) -> None:
        r = env.get(f"/repos/{BETA}/profile")
        assert r.status_code == 409 and envelope(r)["code"] == "no_clone_path"

    def test_profile_computed_cached_refreshed(self, tmp_path: Path) -> None:
        repo = pr.build(tmp_path / "pyrepo")
        with make_env(tmp_path, clone_path=str(repo.path)) as env:
            r = env.get(f"/repos/{ALPHA}/profile")
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["repo"] == ALPHA and p["ref"] == "HEAD"
            # feat commit touches src/calc → bug.fix/XS; the docs commit has no source
            # file and the root commit has no parent — both are skipped, never guessed
            assert p["n_commits"] == 1 and p["examined"] == 3 and p["skipped"] == 2
            assert p["classes"] == ["bug.fix"] and p["sizes"] == ["XS"]
            assert p["cells"] == [
                {"capability_class": "bug.fix", "size": "XS", "count": 1, "share": 1.0}
            ]
            assert p["class_totals"] == {"bug.fix": 1} and p["size_totals"] == {"XS": 1}
            computed_at = p["computed_at"]
            assert computed_at
            # cached: same answer, same stamp, visible on the detail
            r2 = env.get(f"/repos/{ALPHA}/profile")
            assert r2.json()["computed_at"] == computed_at
            assert env.get(f"/repos/{ALPHA}").json()["profile_computed_at"] == computed_at
            assert "profile" not in env.get(f"/repos/{ALPHA}").json()["config"]
            # refresh recomputes (log_n honoured)
            r3 = env.get(f"/repos/{ALPHA}/profile?refresh=true&log_n=1")
            assert r3.status_code == 200 and r3.json()["examined"] == 1
            assert r3.json()["n_commits"] == 0 and r3.json()["cells"] == []
            assert r3.json()["computed_at"] >= computed_at
            # a viewer may read the profile
            login(env.client, "viewer")
            assert env.get(f"/repos/{ALPHA}/profile").status_code == 200

    def test_not_a_repo_409(self, tmp_path: Path) -> None:
        (tmp_path / "plain").mkdir()
        with make_env(tmp_path, clone_path=str(tmp_path / "plain")) as env:
            r = env.get(f"/repos/{ALPHA}/profile")
            assert r.status_code == 409 and envelope(r)["code"] == "clone_unavailable"


class TestTasks:
    def test_list_and_filters(self, env: Env) -> None:
        r = env.get(f"/repos/{ALPHA}/tasks")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 8 and len(body["items"]) == 8
        first = body["items"][0]
        assert set(first) >= {
            "task_id",
            "repo",
            "pool",
            "size",
            "capability_class",
            "gold_clean",
            "test_files",
            "src_files",
            "belt_scope",
        }
        assert first["authored"] >= body["items"][-1]["authored"]  # newest first
        assert env.get(f"/repos/{ALPHA}/tasks?pool=hard").json()["total"] == 1
        assert env.get(f"/repos/{ALPHA}/tasks?size=M").json()["total"] == 2
        assert env.get(f"/repos/{ALPHA}/tasks?capability_class=test.add").json()["total"] == 2
        assert env.get(f"/repos/{ALPHA}/tasks?gold_clean=true").json()["total"] == 7
        page = env.get(f"/repos/{ALPHA}/tasks?limit=3&offset=6").json()
        assert page["total"] == 8 and len(page["items"]) == 2 and page["offset"] == 6
        assert env.get(f"/repos/{BETA}/tasks").json()["total"] == 0
        assert env.get("/repos/nope/tasks").status_code == 404

    def test_route_paths_are_under_prefix(self, env: Env) -> None:
        # Without the prefix there is no API: either 404 (no UI built) or the SPA shell
        # (index.html deep-link fallback) — never a JSON list.
        r = env.client.get("/repos")
        assert r.status_code == 404 or r.headers["content-type"].startswith("text/html")
        assert env.client.get(f"{API_PREFIX}/repos").status_code == 200
