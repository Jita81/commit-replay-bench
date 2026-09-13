"""``/runs`` — list/filters, create → enqueue, cancel, per-task table, event log, SSE."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.observability.events import StepEvent, StepStatus
from crb.server.app import API_PREFIX
from crb.server.routes import runs as runs_mod
from crb.server.routes.runs import event_stream, event_to_model
from crb.store.models import Run
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, login, make_env, task_id


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


class FakeJobs:
    """Records every queue call; ``enqueue`` persists the run so the API can read it back."""

    def __init__(self) -> None:
        self.enqueued: list[Run] = []
        self.cancelled: list[str] = []
        self.listed: list[dict[str, Any]] = []
        self.cancel_result = True

    def install(self, monkeypatch: pytest.MonkeyPatch, *, with_list: bool = False) -> FakeJobs:
        mod = types.ModuleType("crb.store.jobs")

        def enqueue(factory: Any, run: Run) -> Run:
            self.enqueued.append(run)
            with factory() as s:
                s.add(run)
                s.commit()
            return run

        def request_cancel(factory: Any, run_id: str) -> bool:
            self.cancelled.append(run_id)
            if self.cancel_result:
                with factory() as s:
                    run = s.get(Run, run_id)
                    assert run is not None
                    run.cancel_requested = True
                    if run.status == "queued":
                        run.status = "cancelled"
                    s.commit()
            return self.cancel_result

        def list_runs(factory: Any, **kw: Any) -> tuple[list[Run], int]:
            self.listed.append(kw)
            with factory() as s:
                q = select(Run)
                if kw.get("repo"):
                    q = q.where(Run.repo == kw["repo"])
                if kw.get("kind"):
                    q = q.where(Run.kind == kw["kind"])
                if kw.get("status"):
                    q = q.where(Run.status == kw["status"])
                items = list(s.execute(q.order_by(Run.created.desc())).scalars())
            lim, off = int(kw.get("limit", 50)), int(kw.get("offset", 0))
            return items[off : off + lim], len(items)

        mod.enqueue = enqueue  # type: ignore[attr-defined]
        mod.request_cancel = request_cancel  # type: ignore[attr-defined]
        if with_list:
            mod.list_runs = list_runs  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "crb.store.jobs", mod)
        return self


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    return FakeJobs().install(monkeypatch)


# --- list / get -----------------------------------------------------------------------


class TestList:
    def test_list_shape_and_order(self, env: Env) -> None:
        r = env.get("/runs")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 8 and len(body["items"]) == 8
        created = [i["created"] for i in body["items"]]
        assert created == sorted(created, reverse=True)  # newest first
        run = body["items"][0]
        assert set(run) >= {
            "id",
            "repo",
            "kind",
            "status",
            "mode",
            "builder",
            "model",
            "provider",
            "ladder",
            "executor",
            "timeout",
            "pool",
            "limit",
            "task_ids",
            "actor",
            "created",
            "started",
            "finished",
            "cancel_requested",
            "error",
            "cost_usd",
            "apparatus_version",
            "counts",
            "progress",
        }

    def test_filters_and_pagination(self, env: Env) -> None:
        assert env.get("/runs?status=queued").json()["total"] == 1
        assert env.get("/runs?kind=replay").json()["total"] == 3
        assert env.get(f"/runs?repo={ALPHA}&kind=oracle").json()["total"] == 1
        assert env.get("/runs?repo=beta").json()["total"] == 0
        page = env.get("/runs?limit=3&offset=6").json()
        assert page["total"] == 8 and len(page["items"]) == 2
        assert page["limit"] == 3 and page["offset"] == 6

    def test_list_prefers_queue_lister_when_present(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs = FakeJobs().install(monkeypatch, with_list=True)
        r = env.get("/runs?kind=replay&limit=2&offset=1")
        assert r.status_code == 200 and r.json()["total"] == 3 and len(r.json()["items"]) == 2
        assert jobs.listed == [
            {"repo": None, "kind": "replay", "status": None, "limit": 2, "offset": 1}
        ]

    def test_get_run_counts_progress_cost(self, env: Env) -> None:
        ok = env.info.run_ids["succeeded"]
        r = env.get(f"/runs/{ok}")
        assert r.status_code == 200
        run = r.json()
        assert run["status"] == "succeeded" and run["kind"] == "replay"
        assert run["counts"] == {
            "tasks": 4,
            "clean": 4,
            "disqualified": 0,
            "errors": 0,
            "first_pass_clean": 3,
            "rows": 5,
            "duration_s": 210.5,
            "stopped_reason": "",
        }
        assert run["progress"] == {"done": 4, "total": 4, "current_task_id": None}
        assert run["cost_usd"] == pytest.approx(5 * 0.012)
        assert run["apparatus_version"] == "2.0" and run["ladder"] == ["r1", "r2"]
        assert run["executor"] == "local" and run["timeout"] == 600 and run["limit"] is None
        assert run["task_ids"] == [task_id(i) for i in (1, 2, 3, 4)]
        assert run["started"] and run["finished"]

    def test_get_run_derives_counts_when_worker_wrote_none(self, env: Env) -> None:
        failed = env.info.run_ids["failed"]
        run = env.get(f"/runs/{failed}").json()
        assert run["counts"]["tasks"] == 1 and run["counts"]["rows"] == 1
        assert run["counts"]["errors"] == 1 and run["counts"]["clean"] == 0
        assert run["error"].startswith("SandboxUnavailable")
        assert run["finished"] is not None and run["heartbeat"] is None

    def test_running_run_progress(self, env: Env) -> None:
        run = env.get(f"/runs/{env.info.run_ids['running']}").json()
        assert run["progress"] == {"done": 2, "total": 8, "current_task_id": task_id(3)}
        assert run["worker_id"] == "worker-1" and run["heartbeat"]
        assert run["counts"]["tasks"] == 2

    def test_404(self, env: Env) -> None:
        r = env.get("/runs/nope")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"


# --- create ---------------------------------------------------------------------------


class TestCreate:
    def test_rbac(self, env: Env, jobs: FakeJobs) -> None:
        assert_rbac(env, "POST", "/runs", min_role="operator", json={"repo": ALPHA, "kind": "mine"})

    def test_create_enqueues_with_right_fields(self, env: Env, jobs: FakeJobs) -> None:
        login(env.client, "operator")
        body = {
            "repo": ALPHA,
            "kind": "replay",
            "builder": "editblock",
            "model": "gpt-oss-120b",
            "provider": "cerebras",
            "ladder": ["r1", "r2", "editblock:claude-sonnet:anthropic"],
            "task_ids": [task_id(1), task_id(2)],
            "limit": 2,
            "pool": "standard",
            "executor": "docker",
            "timeout": 900,
        }
        r = env.post("/runs", json=body)
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["status"] == "queued" and out["mode"] == "sighted"
        assert len(jobs.enqueued) == 1
        run = jobs.enqueued[0]
        assert run.repo == ALPHA and run.kind == "replay" and run.status == "queued"
        assert run.mode == "sighted" and run.builder == "editblock"
        assert run.model == "gpt-oss-120b" and run.provider == "cerebras"
        assert run.ladder_json == ["r1", "r2", "editblock:claude-sonnet:anthropic"]
        assert run.params_json == {
            "task_ids": [task_id(1), task_id(2)],
            "limit": 2,
            "pool": "standard",
            "executor": "docker",
            "timeout": 900,
        }
        assert run.actor and len(run.id) == 32
        assert out["id"] == run.id
        assert out["task_ids"] == [task_id(1), task_id(2)] and out["executor"] == "docker"
        # readable straight away, and listed
        assert env.get(f"/runs/{run.id}").json()["status"] == "queued"
        assert env.get("/runs?status=queued").json()["total"] == 2

    def test_blind_kind_implies_blind_mode(self, env: Env, jobs: FakeJobs) -> None:
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", "builder": "editblock"})
        assert r.status_code == 201 and r.json()["mode"] == "blind"
        assert jobs.enqueued[-1].mode == "blind" and jobs.enqueued[-1].ladder_json == ["r1"]
        r = env.post(
            "/runs", json={"repo": ALPHA, "kind": "blind", "builder": "b", "mode": "sighted"}
        )
        assert r.status_code == 422 and envelope(r)["code"] == "validation_error"

    def test_non_build_kinds_need_no_builder(self, env: Env, jobs: FakeJobs) -> None:
        for kind in ("mine", "oracle", "controls", "probe"):
            r = env.post("/runs", json={"repo": ALPHA, "kind": kind})
            assert r.status_code == 201, (kind, r.text)
            assert r.json()["kind"] == kind and r.json()["builder"] == ""

    @pytest.mark.parametrize(
        "body",
        [
            {"repo": ALPHA, "kind": "factory"},
            {"repo": ALPHA, "kind": "replay"},  # builder required
            {"repo": ALPHA, "kind": "replay", "builder": "b", "ladder": ["r1", "r1"]},
            {"repo": ALPHA, "kind": "replay", "builder": "b", "ladder": ["bad label!"]},
            {"repo": ALPHA, "kind": "mine", "limit": 0},
            {"repo": ALPHA, "kind": "mine", "pool": "easy"},
            {"repo": ALPHA, "kind": "mine", "executor": "podman"},
            {"repo": ALPHA, "kind": "mine", "task_ids": ["not-a-sha"]},
            {"repo": ALPHA, "kind": "mine", "timeout": -1},
            {"repo": ALPHA, "kind": "mine", "surprise": True},
        ],
    )
    def test_validation_422(self, env: Env, jobs: FakeJobs, body: dict[str, Any]) -> None:
        r = env.post("/runs", json=body)
        assert r.status_code == 422, r.text
        assert envelope(r)["code"] == "validation_error"
        assert jobs.enqueued == []

    def test_unknown_repo_404_and_queue_unavailable_503(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "crb.store.jobs", None)
        r = env.post("/runs", json={"repo": "nope", "kind": "mine"})
        assert r.status_code == 404
        r = env.post("/runs", json={"repo": ALPHA, "kind": "mine"})
        assert r.status_code == 503 and envelope(r)["code"] == "queue_unavailable"

    def test_jobqueue_class_adapter(self, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
        """The in-flight store exposes a ``JobQueue`` class; the seam adapts to it too."""
        seen: list[Run] = []

        class JobQueue:
            def __init__(self, factory: Any) -> None:
                self.factory = factory

            def enqueue(self, run: Run) -> Run:
                seen.append(run)
                with self.factory() as s:
                    s.add(run)
                    s.commit()
                return run

            def request_cancel(self, run_id: str) -> Run | None:
                with self.factory() as s:
                    run = s.get(Run, run_id)
                    if run is None:
                        return None
                    run.cancel_requested = True
                    s.commit()
                    return run

            def list_runs(self, **kw: Any) -> tuple[list[Run], int]:
                with self.factory() as s:
                    items = list(s.execute(select(Run)).scalars())
                return items[: kw["limit"]], len(items)

        mod = types.ModuleType("crb.store.jobs")
        mod.JobQueue = JobQueue  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "crb.store.jobs", mod)
        r = env.post("/runs", json={"repo": ALPHA, "kind": "mine"})
        assert r.status_code == 201 and len(seen) == 1
        r = env.post(f"/runs/{seen[0].id}/cancel")
        assert r.status_code == 200 and r.json()["cancel_requested"] is True
        assert env.get("/runs?limit=2").json()["total"] == 9


# --- cancel ---------------------------------------------------------------------------


class TestCancel:
    def test_rbac(self, env: Env, jobs: FakeJobs) -> None:
        assert_rbac(env, "POST", f"/runs/{env.info.run_ids['running']}/cancel", min_role="operator")

    def test_cancel_calls_queue(self, env: Env, jobs: FakeJobs) -> None:
        running = env.info.run_ids["running"]
        r = env.post(f"/runs/{running}/cancel")
        assert r.status_code == 200, r.text
        assert jobs.cancelled == [running]
        assert r.json()["cancel_requested"] is True and r.json()["status"] == "running"
        queued = env.info.run_ids["queued"]
        r = env.post(f"/runs/{queued}/cancel")
        assert r.status_code == 200 and r.json()["status"] == "cancelled"

    def test_terminal_409_and_404(self, env: Env, jobs: FakeJobs) -> None:
        for key in ("succeeded", "failed", "cancelled"):
            r = env.post(f"/runs/{env.info.run_ids[key]}/cancel")
            assert r.status_code == 409 and envelope(r)["code"] == "run_terminal"
        assert jobs.cancelled == []
        assert env.post("/runs/nope/cancel").status_code == 404

    def test_queue_says_unknown_404(self, env: Env, jobs: FakeJobs) -> None:
        jobs.cancel_result = False
        r = env.post(f"/runs/{env.info.run_ids['running']}/cancel")
        assert r.status_code == 404


# --- tasks / event log ----------------------------------------------------------------


class TestTasks:
    def test_per_task_table(self, env: Env) -> None:
        ok = env.info.run_ids["succeeded"]
        r = env.get(f"/runs/{ok}/tasks")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 4 and len(body["items"]) == 4
        by_id = {t["task_id"]: t for t in body["items"]}
        t3 = by_id[task_id(3)]
        assert t3["trials"] == 2 and t3["clean"] is True and t3["first_pass_clean"] is False
        assert t3["belts"] == {
            "tests_unmodified": True,
            "target_green": True,
            "no_new_failures": True,
            "source_changed": True,
        }
        assert t3["cost_usd"] == pytest.approx(0.024) and t3["latency_s"] == pytest.approx(84.0)
        assert len(t3["pack_hashes"]) == 2 and len(t3["row_ids"]) == 2
        assert (
            t3["capability_class"] == "bug.fix" and t3["size"] == "S" and t3["pool"] == "standard"
        )
        t1 = by_id[task_id(1)]
        assert t1["trials"] == 1 and t1["first_pass_clean"] is True and t1["disqualified"] is False
        # rows are in chain order (T1, T2, T3, T4)
        assert [t["task_id"] for t in body["items"]] == [task_id(i) for i in (1, 2, 3, 4)]
        # every pack hash resolves
        for h in t3["pack_hashes"]:
            assert env.get(f"/evidence/{h}").json()["verified"] is True

    def test_error_row_surfaces(self, env: Env) -> None:
        r = env.get(f"/runs/{env.info.run_ids['failed']}/tasks")
        t = r.json()["items"][0]
        assert t["clean"] is False and t["error"].startswith("SandboxUnavailable")
        assert t["belts"]["target_green"] is None

    def test_pagination_and_empty(self, env: Env) -> None:
        ok = env.info.run_ids["succeeded"]
        page = env.get(f"/runs/{ok}/tasks?limit=1&offset=3").json()
        assert page["total"] == 4 and len(page["items"]) == 1
        assert env.get(f"/runs/{env.info.run_ids['queued']}/tasks").json()["total"] == 0
        assert env.get("/runs/nope/tasks").status_code == 404


class TestEventLog:
    def test_log_paginated_and_redacted(self, env: Env) -> None:
        ok = env.info.run_ids["succeeded"]
        r = env.get(f"/runs/{ok}/events/log")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 6 and [e["seq"] for e in body["items"]] == [1, 2, 3, 4, 5, 6]
        ev = body["items"][2]
        assert ev["stage"] == "grade" and ev["action"] == "grade.belt" and ev["status"] == "ok"
        assert ev["payload"] == {"belt": "tests_unmodified", "value": True}
        assert ev["trace_id"] == ok and ev["task_id"] == task_id(1)
        assert set(ev) == {
            "event_id",
            "seq",
            "timestamp",
            "trace_id",
            "step_id",
            "parent_step_id",
            "stage",
            "action",
            "status",
            "actor",
            "repo",
            "task_id",
            "input_ref",
            "output_ref",
            "error_code",
            "error_message",
            "duration_ms",
            "cost_usd",
            "payload",
        }
        assert "sk-live" not in r.text and "[REDACTED" in r.text
        page = env.get(f"/runs/{ok}/events/log?limit=2&offset=4").json()
        assert [e["seq"] for e in page["items"]] == [5, 6] and page["total"] == 6
        assert env.get("/runs/nope/events/log").status_code == 404
        login(env.client, "viewer")
        assert env.get(f"/runs/{ok}/events/log").status_code == 200


# --- SSE -------------------------------------------------------------------------------


def _frames(text: str) -> list[dict[str, str]]:
    """Parse ``event:`` / ``id:`` / ``data:`` frames; comments are kept as ``{"comment": …}``."""
    out: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        frame: dict[str, str] = {}
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            elif ":" in line:
                k, v = line.split(":", 1)
                frame[k] = v.strip()
        out.append(frame)
    return out


class TestSse:
    def test_replays_then_done_for_terminal_run(self, env: Env) -> None:
        ok = env.info.run_ids["succeeded"]
        with env.client.stream("GET", f"{API_PREFIX}/runs/{ok}/events?after=0") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["cache-control"] == "no-cache, no-store"
            text = "".join(r.iter_text())
        frames = _frames(text)
        steps = [f for f in frames if f.get("event") == "step"]
        assert len(steps) == 6
        assert [int(f["id"]) for f in steps] == [1, 2, 3, 4, 5, 6]
        import json

        first = json.loads(steps[0]["data"])
        assert first["seq"] == 1 and first["action"] == "prep.start" and first["trace_id"] == ok
        assert first["stage"] == "prep" and first["status"] == "in_progress"
        assert "sk-live" not in text
        done = frames[-1]
        assert done["event"] == "done"
        assert json.loads(done["data"]) == {"run_id": ok, "status": "succeeded", "last_seq": 6}

    def test_after_resumes(self, env: Env) -> None:
        ok = env.info.run_ids["succeeded"]
        with env.client.stream("GET", f"{API_PREFIX}/runs/{ok}/events?after=4") as r:
            text = "".join(r.iter_text())
        frames = _frames(text)
        assert [f["id"] for f in frames if f.get("event") == "step"] == ["5", "6"]
        assert frames[-1]["event"] == "done"

    def test_terminal_run_without_events(self, env: Env) -> None:
        cancelled = env.info.run_ids["cancelled"]
        with env.client.stream("GET", f"{API_PREFIX}/runs/{cancelled}/events") as r:
            text = "".join(r.iter_text())
        frames = _frames(text)
        assert len(frames) == 1 and frames[0]["event"] == "done"

    def test_404_and_401(self, env: Env) -> None:
        r = env.get("/runs/nope/events")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"
        env.client.cookies.clear()
        assert env.get(f"/runs/{env.info.run_ids['succeeded']}/events").status_code == 401

    def test_live_poll_keepalive_and_done(self, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
        """The generator polls: a keepalive while idle, then new events, then done once the
        run flips to a terminal status (status is read BEFORE events, so nothing is lost)."""
        monkeypatch.setattr(runs_mod, "SSE_POLL_S", 0.01)
        monkeypatch.setattr(runs_mod, "SSE_KEEPALIVE_S", 0.0)
        queued = env.info.run_ids["queued"]
        disconnected = {"yes": False}

        class Req:
            async def is_disconnected(self) -> bool:
                return disconnected["yes"]

        async def drive() -> list[str]:
            gen = event_stream(Req(), env.factory, queued, 0)  # type: ignore[arg-type]
            out = [await gen.__anext__()]  # idle → keepalive
            with env.factory() as s:
                s.add(
                    event_to_model(
                        StepEvent(
                            trace_id=queued, stage="mine", action="mine.start", seq=1, repo=ALPHA
                        )
                    )
                )
                s.commit()
            while not out[-1].startswith("event: step"):
                out.append(await gen.__anext__())  # the new event arrives on the next poll
            with env.factory() as s:
                run = s.get(Run, queued)
                assert run is not None
                run.status = "cancelled"
                s.add(
                    event_to_model(
                        StepEvent(
                            trace_id=queued,
                            stage="system",
                            action="run.cancelled",
                            status=StepStatus.SKIPPED,
                            seq=2,
                            repo=ALPHA,
                        )
                    )
                )
                s.commit()
            while not out[-1].startswith("event: done"):
                out.append(await gen.__anext__())
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            return out

        chunks = asyncio.run(drive())
        assert chunks[0] == ": keepalive\n\n"
        frames = [c for c in chunks if not c.startswith(":")]
        assert frames[0].startswith("event: step\nid: 1\n")
        assert frames[1].startswith("event: step\nid: 2\n")  # written before the flip: not lost
        assert frames[2].startswith("event: done\n") and '"last_seq":2' in frames[2]
        assert len(frames) == 3

    def test_disconnect_stops_polling(self, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runs_mod, "SSE_POLL_S", 0.01)
        monkeypatch.setattr(runs_mod, "SSE_KEEPALIVE_S", 3600.0)

        class Req:
            async def is_disconnected(self) -> bool:
                return True

        async def drive() -> list[str]:
            gen = event_stream(Req(), env.factory, env.info.run_ids["running"], 0)  # type: ignore[arg-type]
            return [chunk async for chunk in gen]

        assert asyncio.run(drive()) == []  # no events for the running run; client went away
