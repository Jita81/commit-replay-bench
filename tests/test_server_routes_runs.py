"""``/runs`` — list/filters, create → enqueue, cancel, per-task table, event log, SSE.

Navigation
----------
What it is:   ``/runs``'s test suite — list / filters, create → enqueue, cancel, the per-task
              table, the event log and SSE.
What it does: Pins the list shape and order, filters and pagination, the queue lister when
              present, counts / progress / cost (derived when the worker wrote none), 404; create
              RBAC, the enqueued fields, blind kind implies blind mode, non-build kinds need no
              builder, 422 validation, unknown repo 404 and queue unavailable 503, the
              ``JobQueue`` class adapter; a ``claude_code`` auth with no credential refused
              at submit (422 ``builder_credential_missing``, presence only, nothing queued —
              docs/PREVENTION.md P-003); the budget ladder (forwarded only as set, object rungs
              stored as sent, mixed ladders, bounds and rung shape 422, repeated rungs refused
              unless the budget differs, ``labels.budget_tier`` on task rows); cancel RBAC /
              queue call / terminal 409 / 404; the task table and error rows; the paginated,
              redacted event log; and SSE replay-then-done, resume with ``after``, 404 / 401,
              live polling with keepalives, and disconnect stopping the poll.
How:          ``make_env`` over the seed; ``FakeJobs`` records queue calls and persists the run;
              SSE frames parsed from the streamed text.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/server/routes/runs.py (under test), src/crb/store/jobs.py (the queue
              contract the fake mirrors), src/crb/store/events.py (the event log and SSE
              source), tests/test_worker_budget_ladder.py (the worker's half of the ladder),
              tests/fixtures/server_seed.py, docs/API.md (runs, SSE event shape)
Tested by:    tests/test_server_routes_runs.py
Touch when:   a run parameter is added (a create case, a 422 bound and the worker's reading of
              it); a run kind is added (RUN_KINDS, the create cases and ui/src/api/types.ts).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.evidence import ApparatusStamp, BuilderRef, EvidencePack
from crb.core.ledger import GradeRow, grade_row_from_result
from crb.observability.events import StepEvent, StepStatus
from crb.server.app import API_PREFIX
from crb.server.routes import runs as runs_mod
from crb.server.routes.runs import event_stream, event_to_model
from crb.store.ledger import DbLedger
from crb.store.models import Run
from fixtures.server_seed import (
    ALPHA,
    Env,
    assert_rbac,
    envelope,
    login,
    make_env,
    task_id,
)
from fixtures.server_seed import _result as seed_result


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)
    # POST /runs refuses a claude_code run whose auth has no credential (P-003). These
    # cases are about everything else, so the worker's key is PRESENT — a placeholder, never
    # a real key; TestCredentialPresence removes it on purpose.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-not-a-key")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as admin, torn down after the test."""
    with make_env(tmp_path) as e:
        yield e


class FakeJobs:
    """Records every queue call; ``enqueue`` persists the run so the API can read it back."""

    def __init__(self) -> None:
        self.enqueued: list[Run] = []
        self.cancelled: list[str] = []
        self.cancel_actors: list[str] = []
        self.listed: list[dict[str, Any]] = []
        self.cancel_result = True

    def install(self, monkeypatch: pytest.MonkeyPatch, *, with_list: bool = False) -> FakeJobs:
        """Replace ``crb.store.jobs`` with a module whose ``enqueue`` / ``request_cancel`` (and
        optionally ``list_runs``) record into this fake; returns self.
        """
        mod = types.ModuleType("crb.store.jobs")

        def enqueue(factory: Any, run: Run) -> Run:
            self.enqueued.append(run)
            with factory() as s:
                s.add(run)
                s.commit()
            return run

        def request_cancel(factory: Any, run_id: str, *, actor: str = "") -> bool:
            self.cancelled.append(run_id)
            self.cancel_actors.append(actor)
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
    """``FakeJobs`` installed for the test."""
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
            "detail": {},
        }
        assert run["progress"] == {"done": 4, "total": 4, "current_task_id": None}
        # a non-build kind keeps its own counters: served verbatim as counts.detail
        with env.factory() as s:
            mine = Run(
                id="m" * 32,
                repo=ALPHA,
                kind="mine",
                status="succeeded",
                params_json={},
                counts_json={"examined": 9, "found": 4, "gold_clean": 3, "pool": "standard"},
                actor="worker",
            )
            s.add(mine)
            s.commit()
        d = env.get(f"/runs/{'m' * 32}").json()["counts"]
        assert d["detail"] == {"examined": 9, "found": 4, "gold_clean": 3, "pool": "standard"}
        assert d["tasks"] == 0 and d["rows"] == 0
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

    def test_queue_position_is_served_while_queued(self, env: Env) -> None:
        """J-TEL-3: the queue is FIFO by ``created`` (claim order), so a queued run's place
        in the line is a fact — 1-based among queued runs created before it, with the kinds
        ahead of it — and ``null`` for anything not queued."""
        first = env.info.run_ids["queued"]  # seeded: kind mine, created 10:00
        with env.factory() as s:
            s.add(
                Run(
                    id="q1" * 16,
                    repo=ALPHA,
                    kind="oracle",
                    status="queued",
                    params_json={},
                    counts_json={},
                    actor="op1",
                    created="2026-09-01T10:00:30+00:00",
                )
            )
            s.add(
                Run(
                    id="r1" * 16,
                    repo=ALPHA,
                    kind="replay",
                    status="queued",
                    params_json={},
                    counts_json={},
                    actor="op1",
                    created="2026-09-01T10:00:45+00:00",
                )
            )
            s.commit()
        head = env.get(f"/runs/{first}").json()
        assert head["queue_position"] == 1 and head["queue_kinds_ahead"] == []
        third = env.get(f"/runs/{'r1' * 16}").json()
        assert third["queue_position"] == 3 and third["queue_kinds_ahead"] == ["mine", "oracle"]
        for key in ("running", "succeeded", "failed", "cancelled"):
            got = env.get(f"/runs/{env.info.run_ids[key]}").json()
            assert got["queue_position"] is None and got["queue_kinds_ahead"] == []

    def test_counts_branch_on_kind(self, env: Env) -> None:
        """J-TEL-5: replay / blind / factory serve the RunSummary mapping; every other kind
        serves its own counters VERBATIM under ``counts.detail`` — an oracle run's
        ``oracle_strength`` / ``mutants`` / ``killed``, a label run's ``usage.cost_usd`` —
        instead of being read as a build summary (``Clean 0.0 %`` over n labelled tasks)."""
        oracle_counts = {
            "tasks": 3,
            "total": 3,
            "scoreable": 2,
            "unscoreable": 1,
            "mutants": 20,
            "killed": 17,
            "escaped": 3,
            "errors": 1,
            "oracle_strength": 0.85,
            "oracle_strength_mean": 0.8,
            "cells": {},
        }
        label_counts = {
            "tasks": 4,
            "total": 4,
            "labelled": 4,
            "labels": {"bug.fix": 3, "feature.add": 1},
            "usage": {"calls": 4, "cost_usd": 0.0421, "cost_known": True, "errors": 0},
            "errors": 0,
        }
        controls_counts = {"tasks": 2, "rows": 8, "violations": 0, "escapes": 1, "passed": True}
        with env.factory() as s:
            for rid, kind, counts in (
                ("o1" * 16, "oracle", oracle_counts),
                ("l1" * 16, "label", label_counts),
                ("c1" * 16, "controls", controls_counts),
            ):
                s.add(
                    Run(
                        id=rid,
                        repo=ALPHA,
                        kind=kind,
                        status="succeeded",
                        params_json={},
                        counts_json={**counts, "current_task_id": "t9"},
                        actor="worker",
                    )
                )
            s.commit()
        for rid, counts in (("o1" * 16, oracle_counts), ("l1" * 16, label_counts)):
            c = env.get(f"/runs/{rid}").json()["counts"]
            assert c["detail"] == counts  # verbatim, current_task_id excluded
            assert c["tasks"] == 0 and c["clean"] == 0 and c["rows"] == 0 and c["errors"] == 0
        c = env.get(f"/runs/{'c1' * 16}").json()["counts"]
        assert c["detail"] == controls_counts and c["rows"] == 0
        # build kinds keep the RunSummary mapping (the seeded replay)
        ok = env.get(f"/runs/{env.info.run_ids['succeeded']}").json()["counts"]
        assert ok["tasks"] == 4 and ok["detail"] == {}

    def test_factory_run_serves_its_delivery_posture(self, env: Env) -> None:
        """J-FAC-6: a factory run says what it was allowed to do — delivery on/off, who
        overrode the route gate (id and the name resolved at read, as sign-offs do) and
        the backlog hash it worked; ``null`` for every other kind."""
        appr = hashlib.sha256(b"appr1").hexdigest()[:32]
        with env.factory() as s:
            s.add(
                Run(
                    id="f1" * 16,
                    repo=ALPHA,
                    kind="factory",
                    status="succeeded",
                    builder="claude_code",
                    model="claude-sonnet-5",
                    ladder_json=["r1"],
                    params_json={
                        "backlog_hash": "1644eba4" + "0" * 56,
                        "deliver": True,
                        "deliver_override_by": appr,
                    },
                    counts_json={"items": 1, "done": 1, "accepted": 1, "by_status": {}},
                    actor="op1",
                )
            )
            s.add(
                Run(
                    id="g1" * 16,
                    repo=ALPHA,
                    kind="factory",
                    status="queued",
                    params_json={"backlog_hash": "abc"},
                    counts_json={},
                    actor="op1",
                    created="2026-09-01T10:00:30+00:00",
                )
            )
            s.commit()
        f = env.get(f"/runs/{'f1' * 16}").json()
        assert f["factory"] == {
            "deliver": True,
            "deliver_override_by": appr,
            "deliver_override_by_name": "appr1",
            "backlog_hash": "1644eba4" + "0" * 56,
        }
        g = env.get(f"/runs/{'g1' * 16}").json()
        assert g["factory"] == {
            "deliver": False,
            "deliver_override_by": None,
            "deliver_override_by_name": None,
            "backlog_hash": "abc",
        }
        assert env.get(f"/runs/{env.info.run_ids['succeeded']}").json()["factory"] is None


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

            def request_cancel(self, run_id: str, *, actor: str = "") -> Run | None:
                assert actor  # the route names the operator (J-TEL-7)
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


# --- a builder auth with no credential is refused at submit (P-003) -----------------------


class TestCredentialPresence:
    """Run 8d9c5e55 was queued for ``claude_code`` with no ``builder_config.auth``: the
    served default ``api_key`` met a deployment with no key, and all nine attempts failed at
    $0 in 5.4 s. ``POST /runs`` now refuses that at submit — a PRESENCE check only (the
    variable is set, the token file exists): no secret is read, returned or logged."""

    def _post(self, env: Env, **over: Any) -> Any:
        login(env.client, "operator")
        return env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, **over})

    def test_api_key_auth_with_no_key_is_refused_with_the_fix_and_nothing_queued(
        self, env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        r = self._post(env)
        assert r.status_code == 422, r.text
        err = envelope(r)
        assert err["code"] == "builder_credential_missing"
        assert "ANTHROPIC_API_KEY" in err["message"] and '{"auth": "cli"}' in err["message"]
        assert err["detail"] == {"builder": "claude_code", "auth": "api_key"}
        assert jobs.enqueued == []  # refused at submit: nothing reached the queue

    def test_a_rung_further_up_the_ladder_is_checked_too(
        self, env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        r = self._post(
            env,
            builder="openai_agent",
            model="gpt-oss-120b",
            ladder=["r1", "claude_code:claude-opus-5"],
        )
        assert r.status_code == 422 and envelope(r)["code"] == "builder_credential_missing"
        assert jobs.enqueued == []

    def test_present_credentials_are_accepted_and_never_echoed(
        self, env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        r = self._post(env)  # the placeholder key is present
        assert r.status_code == 201 and "sk-ant-test-placeholder" not in r.text
        # cli auth: a stored token file is enough — presence, not content
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        monkeypatch.setenv("PATH", str(tmp_path / "no-bin"))  # no `claude` on PATH either
        monkeypatch.setenv("CRB_SECRETS_DIR", str(tmp_path / "secrets"))
        r = self._post(env, builder_config={"auth": "cli"})
        assert r.status_code == 422 and envelope(r)["detail"]["auth"] == "cli"
        assert "claude setup-token" in envelope(r)["message"]
        (tmp_path / "secrets").mkdir(mode=0o700)
        token = tmp_path / "secrets" / "claude_code_oauth_token"
        token.write_text("x" * 80, encoding="utf-8")
        token.chmod(0o600)
        r = self._post(env, builder_config={"auth": "cli"})
        assert r.status_code == 201, r.text
        assert "x" * 20 not in r.text

    def test_a_build_free_kind_is_never_checked(
        self, env: Env, jobs: FakeJobs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        login(env.client, "operator")
        r = env.post("/runs", json={"repo": ALPHA, "kind": "mine"})
        assert r.status_code == 201, r.text


# --- budget + object rungs (C8) ------------------------------------------------------------


SONNET = {"builder": "claude_code", "model": "claude-sonnet-5"}
SWEEP = [
    {**SONNET, "budget": {"max_tool_calls": 25}},
    {**SONNET, "budget": {"max_tool_calls": 50}},
    {**SONNET, "budget": {"max_tool_calls": 100}},
]


class TestBudgetLadder:
    """``POST /runs`` carries a run-level ``budget`` (forwarded as ``params.budget``, only
    the fields set) and a ``ladder`` whose entries may be OBJECT rungs
    ``{builder, model, provider?, budget?}`` (stored in ``ladder_json`` as sent, echoed on
    the run). The worker applies rung > run > default per field; the schema's job is to
    bound every cap, refuse anything on a rung that is not identity + budget, and keep a
    mixed string/object ladder well-formed."""

    def test_budget_forwarded_only_as_set_and_echoed(self, env: Env, jobs: FakeJobs) -> None:
        login(env.client, "operator")
        r = env.post(
            "/runs",
            json={
                "repo": ALPHA,
                "kind": "blind",
                **SONNET,
                "budget": {"max_tool_calls": 50, "wall_clock_s": 1800},
            },
        )
        assert r.status_code == 201, r.text
        run = jobs.enqueued[-1]
        assert run.params_json["budget"] == {"max_tool_calls": 50, "wall_clock_s": 1800}
        assert run.ladder_json == ["r1"]
        out = r.json()
        assert out["budget"] == {"max_tool_calls": 50, "wall_clock_s": 1800}
        assert out["ladder"] == ["r1"] and out["mode"] == "blind"
        # a budget with nothing set is not stored (the worker applies the defaults)
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, "budget": {}})
        assert r.status_code == 201 and "budget" not in jobs.enqueued[-1].params_json
        assert r.json()["budget"] == {}

    def test_object_rungs_stored_as_sent_and_echoed(self, env: Env, jobs: FakeJobs) -> None:
        """The blind budget sweep: one model, 25 → 50 → 100 tool calls, one attempt per
        rung until clean. ``ladder_json`` is the declaration; the response echoes it."""
        login(env.client, "operator")
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, "ladder": SWEEP})
        assert r.status_code == 201, r.text
        run = jobs.enqueued[-1]
        assert run.ladder_json == SWEEP
        assert run.builder == "claude_code" and run.model == "claude-sonnet-5"
        assert r.json()["ladder"] == SWEEP  # echoed as declared: no null for an inherited cap
        assert env.get(f"/runs/{run.id}").json()["ladder"] == r.json()["ladder"]
        listed = env.get("/runs?kind=blind").json()["items"]
        assert any(x["id"] == run.id and x["ladder"] == r.json()["ladder"] for x in listed)

    def test_mixed_string_and_object_ladder(self, env: Env, jobs: FakeJobs) -> None:
        login(env.client, "operator")
        ladder = [
            "r1",
            {**SONNET, "budget": {"max_tool_calls": 50}},
            "claude_code:claude-opus-5:anthropic",
            {"builder": "claude_code", "model": "claude-opus-5", "provider": "anthropic"},
        ]
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, "ladder": ladder})
        assert r.status_code == 201, r.text
        assert jobs.enqueued[-1].ladder_json == ladder
        assert [e if isinstance(e, str) else e["model"] for e in r.json()["ladder"]] == [
            "r1",
            "claude-sonnet-5",
            "claude_code:claude-opus-5:anthropic",
            "claude-opus-5",
        ]

    def test_object_rungs_only_fill_the_runs_builder_from_the_first_rung(
        self, env: Env, jobs: FakeJobs
    ) -> None:
        """No run-level ``builder`` is needed when every entry is an object rung: the
        first rung names what climbs first (each ledger row names its own rung)."""
        login(env.client, "operator")
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", "ladder": SWEEP})
        assert r.status_code == 201, r.text
        run = jobs.enqueued[-1]
        assert (run.builder, run.model, run.provider) == ("claude_code", "claude-sonnet-5", "")
        r = env.post(
            "/runs",
            json={
                "repo": ALPHA,
                "kind": "replay",
                "ladder": [
                    {"builder": "editblock", "model": "gpt-oss-120b", "provider": "cerebras"}
                ],
            },
        )
        assert r.status_code == 201, r.text
        assert (jobs.enqueued[-1].builder, jobs.enqueued[-1].provider) == ("editblock", "cerebras")
        # a bare label still needs the run's builder — the worker would have nothing to resolve
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", "ladder": ["r1", SWEEP[0]]})
        assert r.status_code == 422 and "needs a builder" in r.text

    @pytest.mark.parametrize(
        ("field", "value", "why"),
        [
            ("max_turns", 0, "greater than or equal to 1"),
            ("max_turns", 1001, "less than or equal to 1000"),
            ("max_tool_calls", 0, "greater than or equal to 1"),
            ("max_tool_calls", 5001, "less than or equal to 5000"),
            ("max_tokens", -1, "greater than or equal to 0"),
            ("max_tokens", 50_000_001, "less than or equal to 50000000"),
            ("max_cost_usd", -0.01, "greater than or equal to 0"),
            ("max_cost_usd", 1000.5, "less than or equal to 1000"),
            ("wall_clock_s", 0, "greater than or equal to 1"),
            ("wall_clock_s", 24 * 3600 + 1, "less than or equal to 86400"),
            ("max_cost", 1, "Extra inputs are not permitted"),
            ("max_turns", "many", "valid integer"),
        ],
    )
    def test_budget_bounds_422(
        self, env: Env, jobs: FakeJobs, field: str, value: Any, why: str
    ) -> None:
        """Every cap is bounded at the request — on the run and on a rung alike."""
        for body in (
            {"repo": ALPHA, "kind": "blind", **SONNET, "budget": {field: value}},
            {
                "repo": ALPHA,
                "kind": "blind",
                **SONNET,
                "ladder": [{**SONNET, "budget": {field: value}}],
            },
        ):
            r = env.post("/runs", json=body)
            assert r.status_code == 422, r.text
            env_ = envelope(r)
            assert env_["code"] == "validation_error"
            assert any(why in e["msg"] for e in env_["detail"]["errors"]), env_
        assert jobs.enqueued == []

    @pytest.mark.parametrize(
        ("rung", "why"),
        [
            ({**SONNET, "api_key": "sk-x"}, "must not carry credentials"),
            ({**SONNET, "anthropic_token": "t"}, "must not carry credentials"),
            ({**SONNET, "name": "other"}, "must not set 'name'"),
            ({**SONNET, "config": {"effort": "high"}}, "must not set 'config'"),
            ({**SONNET, "effort": "high"}, "unknown rung field 'effort'"),
            ({"model": "claude-sonnet-5"}, "Field required"),
            ({"builder": "claude_code"}, "Field required"),
            ({"builder": "Claude Code", "model": "m"}, "not a builder name"),
            ({"builder": "claude_code", "model": "has space"}, "must match"),
            ({"builder": "claude_code", "model": "m", "provider": "bad provider"}, "must match"),
            ({**SONNET, "budget": "lots"}, "valid dictionary"),
        ],
    )
    def test_rung_shape_422(self, env: Env, jobs: FakeJobs, rung: dict[str, Any], why: str) -> None:
        """A rung is identity + budget and nothing else: identity overrides and credentials
        are refused like ``builder_config``; the error names the rung's own reason."""
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, "ladder": [rung]})
        assert r.status_code == 422, r.text
        errors = envelope(r)["detail"]["errors"]
        assert any(why in e["msg"] for e in errors), errors
        assert jobs.enqueued == []

    def test_repeated_object_rung_422_but_a_different_budget_is_a_ladder(
        self, env: Env, jobs: FakeJobs
    ) -> None:
        login(env.client, "operator")
        twice = [SWEEP[0], SWEEP[0]]
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, "ladder": twice})
        assert r.status_code == 422 and "repeated" in r.text
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, "ladder": SWEEP[:2]})
        assert r.status_code == 201, r.text
        r = env.post(
            "/runs",
            json={"repo": ALPHA, "kind": "blind", **SONNET, "ladder": [SWEEP[0]] * 17},
        )
        assert r.status_code == 422  # max 16 rungs, objects included

    def test_task_rows_carry_the_budget_tier(self, env: Env) -> None:
        """``/runs/{id}/tasks`` surfaces ``labels.budget_tier`` per attempt (and the
        decisive attempt's) so a blind rate is read next to the budget it ran under. The
        seed's rows predate the label (``""``); a budget-sweep run is appended here through
        ``DbLedger`` (pack first, rows chained — ``grades`` is append-only, so nothing can be
        stamped after the fact). The worker's own stamping is proved in
        ``test_worker_budget_ladder``."""
        ok = env.info.run_ids["succeeded"]
        before = {t["task_id"]: t for t in env.get(f"/runs/{ok}/tasks").json()["items"]}
        assert before[task_id(3)]["budget_tier"] == "" and before[task_id(3)]["budget_tiers"] == [
            "",
            "",
        ]
        run_id = "c8sweep0" * 4
        task = env.info.tasks[2]
        with env.factory() as s:
            s.add(Run(id=run_id, repo=ALPHA, kind="blind", mode="blind", status="succeeded"))
            s.commit()
        ledger = DbLedger(env.factory)
        rows: list[GradeRow] = []
        for i, clean in enumerate((False, False, True)):
            trial = f"r{i + 1}"
            result = seed_result(task, clean=clean)
            pack = EvidencePack(
                task=task,
                grade=result,
                apparatus=ApparatusStamp(runner="pytest", executor={"kind": "local"}),
                builder=BuilderRef(name="claude_code", model="claude-sonnet-5", mode="blind"),
                run_id=run_id,
                trial=trial,
            )
            ledger.store_pack(pack)
            rows.append(
                grade_row_from_result(
                    result,
                    task,
                    pack_hash=pack.pack_hash,
                    builder=pack.builder,
                    run_id=run_id,
                    trial=trial,
                    labels={"budget_tier": f"{25 * 2**i}/25/900", "rung_index": str(i)},
                )
            )
        ledger.append_many(rows)
        (t3,) = env.get(f"/runs/{run_id}/tasks").json()["items"]
        assert t3["task_id"] == task.task_id and t3["trials"] == 3 and t3["clean"] is True
        assert t3["budget_tiers"] == ["25/25/900", "50/25/900", "100/25/900"]
        assert t3["budget_tier"] == "100/25/900"  # the decisive (clean) attempt: r3
        # the label is part of every served row too
        served = env.get(f"/grades?repo={ALPHA}&run_id={run_id}").json()["items"]
        assert sorted(g["labels"]["budget_tier"] for g in served) == [
            "100/25/900",
            "25/25/900",
            "50/25/900",
        ]


# --- cancel ---------------------------------------------------------------------------


class TestCancel:
    def test_rbac(self, env: Env, jobs: FakeJobs) -> None:
        assert_rbac(env, "POST", f"/runs/{env.info.run_ids['running']}/cancel", min_role="operator")

    def test_cancel_calls_queue(self, env: Env, jobs: FakeJobs) -> None:
        running = env.info.run_ids["running"]
        r = env.post(f"/runs/{running}/cancel")
        assert r.status_code == 200, r.text
        assert jobs.cancelled == [running]
        # J-TEL-7: the queue seam receives the OPERATOR who clicked Cancel (the seeded run's
        # creator is op1; the env is logged in as admin root)
        assert jobs.cancel_actors == [hashlib.sha256(b"root").hexdigest()[:32]]
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
            "repo_lint_clean": None,  # v5 row, no linter configured: not evaluated
        }
        assert t3["belt_set"] == "v5"
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
