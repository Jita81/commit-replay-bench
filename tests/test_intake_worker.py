"""The worker's idle-loop listener — default OFF, on a timer, and it survives anything.

Navigation
----------
What it is:   The worker-side intake suite: which repositories are polled, when a poll is
              due, and that a tracker that cannot be built or reached leaves a reason on
              each repository's chain instead of stopping the worker.
What it does: Pins that a deployment with no tracker never polls, that a repository whose
              listener nobody switched on is never polled however the deployment is
              configured, that the poll runs on its own timer rather than every idle pass,
              that the worker keeps checking in for as long as a pass lasts (a slow board
              must not read as a stale worker), that a registration arriving during a factory
              run is queued, and that an exception inside one repository's poll does not
              touch the others.
How:          A ``Worker`` over a SQLite store under ``tmp_path`` with the file-backed
              fake tracker; nothing here reaches a network, a model or a real tracker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/server/worker.py (``poll_intake`` / ``intake_due`` / ``intake_repos``),
              src/crb/server/intake.py (the flow it drives),
              src/crb/intake/fake.py (the board), tests/test_server_routes_intake.py
Tested by:    tests/test_intake_worker.py
Touch when:   the idle loop gains another periodic job — give it its own timer and test.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from crb.intake import client as c
from crb.intake.fake import FAKE_TRACKER_ENV, fake_tracker_path
from crb.server.factory_state import FactoryHome
from crb.server.intake import IntakeStore, ListenerState
from crb.server.settings import IntakeSettings
from crb.server.worker import Worker, WorkerSettings
from crb.store.db import init_db, make_engine, make_session_factory
from crb.store.models import Repo, Run

#: The deployment's own address. Every link the listener writes on a ticket is built from
#: it, and a worker without one stops before it writes anything.
PUBLIC = "https://crb.invalid"

BOARD: dict[str, Any] = {
    "tickets": {
        "4711": {
            "title": "Fix the crash when the cart is empty",
            "body": "steps to reproduce: open an empty cart. it crashes.",
            "acceptance_criteria": [
                "reproduction: open an empty cart",
                "expected_behaviour: it shows an empty basket",
            ],
            "type": "Bug",
            "points": 3,
            "revision": "1",
            "state": "Ready",
            "changed": "2026-09-22T09:00:00Z",
        }
    }
}


def _intake(**kw: Any) -> IntakeSettings:
    base: dict[str, Any] = {
        "tracker": "fake",
        "url": "https://tracker.invalid",
        "project": "W",
        "column": "Ready",
        "poll_s": 30,
    }
    base.update(kw)
    return IntakeSettings(**base)


class Stack:
    """A worker, a store, a repository row and a board — nothing else."""

    def __init__(self, tmp_path: Path, intake: IntakeSettings, public_url: str = PUBLIC) -> None:
        self.home = tmp_path / "home"
        url = f"sqlite:///{self.home / 'crb.db'}"
        self.home.mkdir(parents=True, exist_ok=True)
        engine = make_engine(url)
        init_db(engine)
        self.factory = make_session_factory(engine)
        self.worker = Worker(
            WorkerSettings(
                database_url=url,
                home=self.home,
                worker_id="w-intake",
                poll_s=0.05,
                heartbeat_s=0.05,
                intake=intake,
                public_url=public_url,
            ),
            engine=engine,
        )
        fake_tracker_path(self.home).write_text(json.dumps(BOARD), encoding="utf-8")

    def add_repo(self, name: str, listener: dict[str, Any] | None = None) -> None:
        with self.factory() as s:
            s.add(
                Repo(
                    name=name,
                    language="python",
                    runner="pytest",
                    config_json={"intake": listener} if listener else {},
                )
            )
            s.commit()

    def queue_factory_run(self, repo: str) -> None:
        with self.factory() as s:
            s.add(Run(id="r-1", repo=repo, kind="factory", status="running", actor="someone"))
            s.commit()


@pytest.fixture(autouse=True)
def _fake_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FAKE_TRACKER_ENV, "1")


# --- default OFF ----------------------------------------------------------------------


def test_a_deployment_with_no_tracker_never_polls(tmp_path: Path) -> None:
    stack = Stack(tmp_path, IntakeSettings())
    stack.add_repo("alpha", {"enabled": True})
    assert stack.worker.intake_due() is False
    assert stack.worker.poll_intake() == 0


def test_a_repository_whose_listener_nobody_switched_on_is_never_polled(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha")  # no intake key at all
    stack.add_repo("beta", {"enabled": False})
    assert stack.worker.intake_repos() == []
    assert stack.worker.poll_intake() == 0
    assert FactoryHome(stack.home, "alpha").events() == []


def test_only_the_switched_on_repositories_are_polled(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    stack.add_repo("beta", {"enabled": False})
    assert [name for name, _ in stack.worker.intake_repos()] == ["alpha"]
    assert stack.worker.poll_intake() == 1
    assert IntakeStore(stack.home, "alpha").rows()
    assert IntakeStore(stack.home, "beta").rows() == []


# --- the timer -------------------------------------------------------------------------


def test_the_poll_runs_on_its_own_timer_not_on_every_idle_pass(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake(poll_s=30))
    stack.add_repo("alpha", {"enabled": True})
    assert stack.worker.poll_intake(now=1000.0) == 1
    assert stack.worker.intake_due(now=1010.0) is False
    assert stack.worker.poll_intake(now=1010.0) == 0
    assert stack.worker.intake_due(now=1031.0) is True


def test_the_worker_checks_in_while_a_slow_board_is_being_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The idle loop's check-in happens BETWEEN passes. One ticket costs about eleven
    synchronous tracker calls with a 20-second timeout each, so a slow board could hold the
    loop past the liveness window — and the health probe then reported this worker stale, and
    told an operator queued runs would not start, while it was working. The pass now keeps its
    own check-in running for as long as it lasts, and stops it however the pass ends."""
    stack = Stack(tmp_path, _intake())  # heartbeat_s = 0.05
    stack.add_repo("alpha", {"enabled": True})
    beats: list[str] = []
    monkeypatch.setattr(stack.worker, "checkin", lambda **kw: beats.append("beat"))

    def slow(repo: str, tracker: Any, state: ListenerState) -> None:
        time.sleep(0.4)  # one ticket making its tracker calls
        raise RuntimeError("and then the tracker refused")  # the pass must still stop it

    monkeypatch.setattr(stack.worker, "_poll_one", slow)
    assert stack.worker.poll_intake() == 1
    assert len(beats) >= 3  # ~8 at heartbeat_s=0.05; never 0, which is the bug
    before = len(beats)
    time.sleep(0.2)
    assert len(beats) == before  # the thread is stopped, not left beating for ever
    assert [t.name for t in threading.enumerate() if "crb-checkin" in t.name] == []


# --- what a poll does --------------------------------------------------------------------


def test_a_poll_registers_the_ticket_and_writes_the_row_the_screen_reads(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    stack.worker.poll_intake()
    home = FactoryHome(stack.home, "alpha")
    backlog = home.load_backlog()
    assert backlog is not None and [i.id for i in backlog.items] == ["fake-4711"]
    rows = IntakeStore(stack.home, "alpha").rows()
    assert [r.key for r in rows] == ["4711"]
    assert rows[0].label == c.LABEL_QUEUED
    board = json.loads(fake_tracker_path(stack.home).read_text(encoding="utf-8"))
    assert c.LABEL_QUEUED in board["tickets"]["4711"]["tags"]


def test_a_registration_during_a_factory_run_is_queued_not_lost(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    stack.queue_factory_run("alpha")
    stack.worker.poll_intake(now=1000.0)
    home = FactoryHome(stack.home, "alpha")
    assert home.load_backlog() is None
    assert "intake.queued" in [e.kind for e in home.events()]
    # the run finishes, and the next poll picks it up
    with stack.factory() as s:
        s.get(Run, "r-1").status = "succeeded"  # type: ignore[union-attr]
        s.commit()
    stack.worker.poll_intake(now=2000.0)
    assert home.load_backlog() is not None


def test_a_column_override_on_the_repository_wins_over_the_deployments(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake(column="Somewhere else"))
    stack.add_repo("alpha", {"enabled": True, "column": "Ready"})
    stack.worker.poll_intake()
    assert IntakeStore(stack.home, "alpha").last_poll()["column"] == "Ready"  # type: ignore[index]


# --- refusals ------------------------------------------------------------------------------


def test_a_tracker_that_cannot_be_built_leaves_a_reason_on_every_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FAKE_TRACKER_ENV, raising=False)
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    stack.add_repo("beta", {"enabled": True})
    assert stack.worker.poll_intake() == 0
    for repo in ("alpha", "beta"):
        stops = [e for e in FactoryHome(stack.home, repo).events() if e.kind == "intake.stopped"]
        assert stops and stops[-1].payload["reason"] == c.REASON_NOT_CONFIGURED


def test_an_unreadable_board_stops_that_repository_and_leaves_the_worker_running(
    tmp_path: Path,
) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    fake_tracker_path(stack.home).write_text("not json", encoding="utf-8")
    assert stack.worker.poll_intake() == 1
    last = IntakeStore(stack.home, "alpha").last_poll()
    assert last is not None and last["stopped"] == c.REASON_COLUMN_GONE


def test_one_repositorys_failure_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    stack.add_repo("beta", {"enabled": True})
    real = stack.worker._poll_one
    calls: list[str] = []

    def boom(repo: str, tracker: Any, state: ListenerState) -> None:
        calls.append(repo)
        if repo == "alpha":
            raise RuntimeError("something inside the poll went wrong")
        real(repo, tracker, state)

    monkeypatch.setattr(stack.worker, "_poll_one", boom)
    assert stack.worker.poll_intake() == 2
    assert calls == ["alpha", "beta"]
    assert IntakeStore(stack.home, "beta").rows()


# --- the outcome map ---------------------------------------------------------------------


def test_the_default_outcome_map_moves_no_ticket(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    stack.worker.poll_intake(now=1000.0)
    FactoryHome(stack.home, "alpha").evidence(actor="t").append(
        "delivery.merged", "fake-4711", pr_url="https://pr/1"
    )
    stack.worker.poll_intake(now=2000.0)
    board = json.loads(fake_tracker_path(stack.home).read_text(encoding="utf-8"))
    assert board["tickets"]["4711"]["state"] == "Ready"


def test_a_configured_outcome_map_moves_the_ticket_after_the_merge(tmp_path: Path) -> None:
    stack = Stack(tmp_path, _intake(outcome_map={"merged": "Done"}))
    stack.add_repo("alpha", {"enabled": True})
    stack.worker.poll_intake(now=1000.0)
    FactoryHome(stack.home, "alpha").evidence(actor="t").append(
        "delivery.merged", "fake-4711", pr_url="https://pr/1"
    )
    stack.worker.poll_intake(now=2000.0)
    board = json.loads(fake_tracker_path(stack.home).read_text(encoding="utf-8"))
    assert board["tickets"]["4711"]["state"] == "Done"
    assert "intake.transitioned" in [e.kind for e in FactoryHome(stack.home, "alpha").events()]


def test_a_worker_that_does_not_know_the_deployments_address_writes_nothing(
    tmp_path: Path,
) -> None:
    """The listener's links are the product's own pages. Relative, they resolve against the
    TRACKER's host on the customer's board, so the pass stops before it writes anything and
    the stop names the setting to put right."""
    stack = Stack(tmp_path, _intake(), public_url="")
    stack.add_repo("alpha", {"enabled": True})
    assert stack.worker.poll_intake() == 1
    last = IntakeStore(stack.home, "alpha").last_poll() or {}
    assert last["stopped"] == c.REASON_NO_PUBLIC_URL
    assert "CRB_PUBLIC_URL" in last["advice"]
    board = json.loads(fake_tracker_path(stack.home).read_text(encoding="utf-8"))
    assert board["tickets"]["4711"].get("comments") in (None, {})


# --- C6 (assessment 2026-09-25): approval by default, the allowlist, the lease -----------


def test_the_served_worker_leaves_a_ready_ticket_waiting_for_an_operator(tmp_path: Path) -> None:
    """The deployment default (``IntakeSettings()`` — no ``require_approval`` given): the
    worker's timed poll drafts the ready ticket and registers nothing (ADR-0022)."""
    stack = Stack(
        tmp_path,
        IntakeSettings(
            tracker="fake", url="https://tracker.invalid", project="W", column="Ready", poll_s=30
        ),
    )
    stack.add_repo("alpha", {"enabled": True})
    stack.worker.poll_intake()
    home = FactoryHome(stack.home, "alpha")
    assert home.load_backlog() is None
    (row,) = IntakeStore(stack.home, "alpha").rows()
    assert row.awaiting_approval and not row.registered


def test_the_worker_honours_the_deployments_author_allowlist(tmp_path: Path) -> None:
    board = json.loads(json.dumps(BOARD))
    board["tickets"]["4711"]["author"] = "ada@example.invalid"
    stack = Stack(tmp_path, _intake(require_approval=True, approve_authors=["ada@example.invalid"]))
    fake_tracker_path(stack.home).write_text(json.dumps(board), encoding="utf-8")
    stack.add_repo("alpha", {"enabled": True})
    stack.worker.poll_intake()
    backlog = FactoryHome(stack.home, "alpha").load_backlog()
    assert backlog is not None and [i.id for i in backlog.items] == ["fake-4711"]


def test_a_worker_poll_takes_the_repositorys_lease(tmp_path: Path) -> None:
    """C6(c): a pass the worker starts while another pass holds the repository's lease
    reads nothing and writes nothing."""
    from crb.server.intake import intake_lease

    stack = Stack(tmp_path, _intake(require_approval=False))
    stack.add_repo("alpha", {"enabled": True})
    held = intake_lease(stack.factory, "alpha", ttl_s=300)
    assert held.acquire()
    try:
        stack.worker.poll_intake()
        home = FactoryHome(stack.home, "alpha")
        assert home.load_backlog() is None and home.events() == []
        board = json.loads(fake_tracker_path(stack.home).read_text(encoding="utf-8"))
        assert "comments" not in board["tickets"]["4711"]
    finally:
        held.release()
    stack.worker.poll_intake(now=time.time() + 3600)
    assert FactoryHome(stack.home, "alpha").load_backlog() is not None
