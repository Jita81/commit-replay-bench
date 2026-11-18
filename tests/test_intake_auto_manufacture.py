"""The automatic build (ADR-0060): one capped factory run after a consented, clean probe.

Navigation
----------
What it is:   The automatic build's suite: the settings that refuse an unsafe switch, the
              consent the Register act records, the sweep that queues at most one run per
              ticket content, the run it queues, and the worker's one-item refusal.
What it does: Pins that the switch is off by default and changes nothing when off; that only
              an operator's act made while the switch is on consents; that content which goes
              back to an earlier probe needs a new act; that one run is queued per
              ``(tracker, key, content_revision)``, even when two passes race; that each final
              skip is recorded once and each wait writes nothing; that the run delivers, keeps
              ``max_rework`` and shares the cap per attempt; and that the worker builds the
              item only while it is active and depends on nothing.
How:          A real ``FactoryHome`` under ``tmp_path`` (the real hash chain), the
              ``FakeTracker``, a fake :class:`~crb.server.intake.AutoManufacture` that only
              records, and a SQLite store for the real enqueue. No model, no network, no money.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0060-a-clean-probe-queues-one-capped-build.md
Works with:   src/crb/server/intake.py (the consent marks and the sweep under test),
              src/crb/intake/gap_probe.py (the probe state the mark reads),
              src/crb/server/settings.py (the start-up refusals),
              src/crb/server/worker.py (the one-item refusal),
              tests/fixtures/intake.py (the fake tracker)
Tested by:    tests/test_intake_auto_manufacture.py
Touch when:   never for a new repository; the automatic build gains a skip, a wait or a field.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from crb.factory.backlog import KIND_CODE, BacklogItem
from crb.factory.evidence import (
    EV_BUILD,
    EV_INTAKE_GAP_PROBE_FINISHED,
    EV_INTAKE_GAP_PROBE_REQUESTED,
    EV_INTAKE_MANUFACTURE_REQUESTED,
    EV_INTAKE_MANUFACTURE_SKIPPED,
    EV_ITEM_OUTCOME,
)
from crb.factory.standard import Readers, Standard
from crb.intake import client as c
from crb.server import intake as sv
from crb.server.factory_state import FactoryHome
from crb.server.settings import IntakeSettings
from fixtures.intake import FakeTracker

READY_AC = (
    "method_path: POST /health",
    "request_shape: no body",
    "response_shape: 200 with {status: string}",
    "error_contract: 503 when a dependency is down",
)
PROVEN = Readers(standard_for=lambda cell: Standard("S1@claude-sonnet-5", signed=True))
OPERATORS_ONLY = sv.ApprovalPolicy()
TRUSTED = sv.ApprovalPolicy(allow_authors=("ada@example.invalid",))
RUNG = "claude_code:claude-sonnet-5"
_PROBE: dict[str, Any] = {"gap_probe": True, "gap_probe_rung": RUNG}
_ON: dict[str, Any] = {
    **_PROBE,
    "auto_manufacture": True,
    "auto_manufacture_rung": RUNG,
    "auto_manufacture_max_cost_usd": 6.0,
    "auto_manufacture_max_rework": 2,
}


def _ticket(**kw: Any) -> c.Ticket:
    base: dict[str, Any] = {
        "key": "4711",
        "title": "Add a POST /health route",
        "body": "a new HTTP endpoint on the api",
        "acceptance_criteria": READY_AC,
        "revision": "1",
        "url": "https://tracker.invalid/4711",
        "points": 2.0,
        "state": "Ready",
        "author": "mallory@example.invalid",
    }
    base.update(kw)
    return c.Ticket(**base)


def _tracker(ticket: c.Ticket) -> FakeTracker:
    t = FakeTracker({ticket.key: ticket})
    t.column = [c.TicketRef(key=ticket.key, revision=ticket.revision, title=ticket.title)]
    return t


def _edit(tracker: FakeTracker, revision: str, **kw: Any) -> None:
    ticket = _ticket(revision=revision, **kw)
    tracker.tickets[ticket.key] = ticket
    tracker.column = [c.TicketRef(key=ticket.key, revision=revision, title=ticket.title)]


def _url(item_id: str) -> str:
    return f"https://crb.invalid/factory?item={item_id}"


def _deliver() -> dict[str, Any]:
    return {
        "route": "deliver",
        "reason": "every bar cleared",
        "n": 42,
        "point": 0.81,
        "ci_low": 0.67,
        "ci_high": 0.9,
        "apparatus_versions": ["2.2"],
    }


class Queue:
    """The probe's queue seam: records each request and answers a settable run status."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status: dict[str, str | None] = {}

    def enqueue(self, request: Any) -> str:
        run_id = f"probe-{len(self.requests) + 1}"
        self.requests.append(dict(request))
        self.status[run_id] = "queued"
        return run_id

    def probe(self, *, auto: bool) -> sv.GapProbe:
        return sv.GapProbe(
            self.enqueue, self.status.get, 5, lambda run_id: None, auto_manufacture=auto
        )


def _poll(home: FactoryHome, tracker: FakeTracker, queue: Queue, *, auto: bool, **kw: Any) -> Any:
    args: dict[str, Any] = {
        "tracker": tracker,
        "listener": sv.ListenerState(enabled=True),
        "column": "Ready",
        "home": home,
        "route_for": lambda item: _deliver(),
        "item_url": _url,
        "approval": OPERATORS_ONLY,
        "gate": PROVEN,
        "gap_probe": queue.probe(auto=auto),
    }
    args.update(kw)
    return sv.poll_repository("alpha", **args)


def _act(
    home: FactoryHome, tracker: FakeTracker, queue: Queue, *, auto: bool, revision: str = "1"
) -> sv.IntakeRow:
    return sv.register_approved(
        "alpha",
        "4711",
        revision=revision,
        tracker=tracker,
        home=home,
        item_url=_url,
        approver="operator:ada",
        gap_probe=queue.probe(auto=auto),
    )


def _finish(home: FactoryHome, queue: Queue) -> None:
    """What the worker writes when the probe's build ends clean: no question."""
    req = queue.requests[-1]
    run_id = f"probe-{len(queue.requests)}"
    home.evidence(actor="worker").append(
        EV_INTAKE_GAP_PROBE_FINISHED,
        req["item_id"],
        tracker=req["tracker"],
        key=req["key"],
        revision=req["revision"],
        content_revision=req["content_revision"],
        run_id=run_id,
        questions=[],
        cost_usd=0.4,
        tokens=100,
    )
    queue.status[run_id] = "succeeded"


def _of(home: FactoryHome, kind: str) -> list[Any]:
    return [e for e in home.events() if e.kind == kind]


class Factory:
    """The automatic build's seams: records each run it was asked to queue."""

    def __init__(self) -> None:
        self.queued: list[dict[str, Any]] = []
        self.runs: dict[tuple[str, str, str], str] = {}
        self.route = sv.ROUTE_FOUND
        self.active = False
        self.inactive: set[str] = set()
        self.refuse: tuple[str, str] | None = None
        self.boom = False

    def find_run(self, key: Any) -> str:
        return self.runs.get((key["tracker"], key["key"], key["content_revision"]), "")

    def queue_run(self, request: Any) -> str:
        if self.refuse:
            raise sv.ManufactureRefused(*self.refuse)
        if self.boom:
            raise RuntimeError("the store fell over")
        run_id = f"run-{len(self.queued) + 1}"
        self.queued.append(dict(request))
        self.runs[(request["tracker"], request["key"], request["content_revision"])] = run_id
        return run_id

    def auto(self, *, sealed: bool = False) -> sv.AutoManufacture:
        return sv.AutoManufacture(
            rung=RUNG,
            max_cost_usd=6.0,
            max_rework=2,
            find_run=self.find_run,
            queue_run=self.queue_run,
            run_active=lambda: self.active,
            delivery_route=lambda: self.route,
            approver_active=lambda account: account not in self.inactive,
            sealed=sealed,
        )


def _sweep(home: FactoryHome, factory: Factory, **kw: Any) -> str:
    sealed = bool(kw.pop("sealed", False))
    kw.setdefault("renew", lambda: True)
    return sv.manufacture_registered(home, tracker="fake", auto=factory.auto(sealed=sealed), **kw)


@pytest.fixture
def home(tmp_path: Path) -> FactoryHome:
    return FactoryHome(tmp_path, "alpha")


def _consented(home: FactoryHome, tracker: FakeTracker, queue: Queue) -> None:
    """An operator acts with the switch on, the probe ends clean, and the poll registers."""
    _poll(home, tracker, queue, auto=True)
    _act(home, tracker, queue, auto=True)
    _finish(home, queue)
    _poll(home, tracker, queue, auto=True)


# --- settings ---------------------------------------------------------------------------


def _settings(**kw: Any) -> IntakeSettings:
    base: dict[str, Any] = {"tracker": "fake", "column": "Ready"}
    base.update(kw)
    return IntakeSettings(**base)


def test_the_automatic_build_is_off_by_default_with_the_designed_defaults() -> None:
    s = _settings()
    assert s.auto_manufacture is False and s.auto_manufacture_rung == ""
    assert s.auto_manufacture_max_cost_usd == 10.0 and s.auto_manufacture_max_rework == 1
    assert {"auto_manufacture", "auto_manufacture_rung", "auto_manufacture_max_cost_usd"} <= set(
        s.redacted()
    )


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({**_ON, "gap_probe": False, "gap_probe_rung": ""}, "needs gap_probe"),
        ({**_ON, "require_approval": False}, "require_approval"),
        ({**_ON, "auto_manufacture_rung": ""}, "auto_manufacture_rung is empty"),
        (
            {**_ON, "auto_manufacture_max_cost_usd": 5000.0, "auto_manufacture_max_rework": 1},
            "per attempt",
        ),
    ],
)
def test_settings_refuse_an_unsafe_automatic_build(kw: dict[str, Any], match: str) -> None:
    """Spend review: a cap whose share per attempt is above one run's budget limit raised
    inside every sweep instead of being refused at start-up."""
    with pytest.raises(ValidationError, match=match):
        _settings(**kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"auto_manufacture_max_rework": -1},
        {"auto_manufacture_max_rework": 6},
        {"auto_manufacture_max_cost_usd": 0},
        {"auto_manufacture_max_cost_usd": float("inf")},
    ],
)
def test_settings_refuse_out_of_range_bounds(kw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _settings(**kw)


def test_settings_accept_a_complete_switch_and_store_one_canonical_rung() -> None:
    s = _settings(**{**_ON, "auto_manufacture_rung": " claude_code : claude-sonnet-5 "})
    assert s.auto_manufacture is True and s.auto_manufacture_rung == RUNG


# --- off: unchanged ---------------------------------------------------------------------


def test_with_the_switch_off_the_probe_and_the_registration_carry_no_new_field(
    home: FactoryHome,
) -> None:
    """The chain a deployment with the switch off writes is the chain it wrote before."""
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, queue, auto=False)
    _act(home, tracker, queue, auto=False)
    _finish(home, queue)
    _poll(home, tracker, queue, auto=False)
    (req,) = _of(home, EV_INTAKE_GAP_PROBE_REQUESTED)
    assert set(req.payload) == {
        "tracker",
        "key",
        "revision",
        "content_revision",
        "approved_by",
        "approved_by_name",
        "run_id",
    }
    (reg,) = _of(home, sv.EV_REGISTERED)
    assert set(reg.payload) == {"tracker", "key", "how", "supersedes", "url", "approved_by"}
    assert all("manufacture" not in e.payload for e in home.events())


def test_auto_manufacture_for_is_none_while_the_switch_is_off(tmp_path: Path) -> None:
    sessions = _store(tmp_path)
    off = SimpleNamespace(intake=_settings(**_PROBE), home=tmp_path)
    assert (
        sv.auto_manufacture_for(
            off, sessions, "alpha", run_active=lambda: False, delivery_route=lambda: ""
        )
        is None
    )
    assert (
        sv.auto_manufacture_for(
            SimpleNamespace(),
            sessions,
            "alpha",
            run_active=lambda: False,
            delivery_route=lambda: "",
        )
        is None
    )


# --- consent ----------------------------------------------------------------------------


def test_an_operators_act_with_the_switch_on_queues_one_build_once(home: FactoryHome) -> None:
    queue, factory = Queue(), Factory()
    tracker = _tracker(_ticket())
    _consented(home, tracker, queue)
    (req,) = _of(home, EV_INTAKE_GAP_PROBE_REQUESTED)
    assert req.payload["manufacture"] == "auto"
    (reg,) = _of(home, sv.EV_REGISTERED)
    assert reg.payload["manufacture"] == "auto"
    assert reg.payload["content_revision"] == req.payload["content_revision"]
    assert _sweep(home, factory) == "run-1"
    (asked,) = factory.queued
    assert asked == {
        "tracker": "fake",
        "key": "4711",
        "content_revision": req.payload["content_revision"],
        "item_id": reg.item_id,
        "approved_by": "operator:ada",
    }
    (named,) = _of(home, EV_INTAKE_MANUFACTURE_REQUESTED)
    assert named.payload["run_id"] == "run-1" and named.payload["max_cost_usd"] == 6.0
    assert named.payload["rung"] == RUNG
    # every later pass finds the content settled: no second run, no second event
    for _ in range(3):
        assert _sweep(home, factory) == ""
    assert len(factory.queued) == 1 and len(_of(home, EV_INTAKE_MANUFACTURE_REQUESTED)) == 1


def test_an_act_made_while_the_switch_was_off_never_becomes_consent(home: FactoryHome) -> None:
    """Spend review: consent was decided at registration, so an act made with the switch
    off was spent on a paid build once the switch was turned on before the poll."""
    queue, factory = Queue(), Factory()
    tracker = _tracker(_ticket())
    _poll(home, tracker, queue, auto=False)
    _act(home, tracker, queue, auto=False)
    _finish(home, queue)
    _poll(home, tracker, queue, auto=True)  # switched on after the act
    (reg,) = _of(home, sv.EV_REGISTERED)
    assert "manufacture" not in reg.payload
    assert _sweep(home, factory) == "" and factory.queued == []
    assert not _of(home, EV_INTAKE_MANUFACTURE_SKIPPED)


def test_a_second_act_with_the_switch_on_consents_at_that_act(home: FactoryHome) -> None:
    """The act path decides the mark before the registration is written (spend review)."""
    queue, factory = Queue(), Factory()
    tracker = _tracker(_ticket())
    _poll(home, tracker, queue, auto=False)
    _act(home, tracker, queue, auto=False)
    _finish(home, queue)
    row = _act(home, tracker, queue, auto=True)  # registers now, the switch on at this act
    assert row.registered
    (reg,) = _of(home, sv.EV_REGISTERED)
    assert reg.payload["manufacture"] == "auto" and reg.payload["approved_by"] == "operator:ada"
    assert _sweep(home, factory) == "run-1"


def test_switching_off_before_the_registration_drops_the_consent(home: FactoryHome) -> None:
    queue, factory = Queue(), Factory()
    tracker = _tracker(_ticket())
    _poll(home, tracker, queue, auto=True)
    _act(home, tracker, queue, auto=True)
    _finish(home, queue)
    _poll(home, tracker, queue, auto=False)
    (reg,) = _of(home, sv.EV_REGISTERED)
    assert "manufacture" not in reg.payload and _sweep(home, factory) == ""


def test_an_allowlisted_author_never_consents(home: FactoryHome) -> None:
    queue, factory = Queue(), Factory()
    tracker = _tracker(_ticket(author="ada@example.invalid"))
    _poll(home, tracker, queue, auto=True, approval=TRUSTED)
    _finish(home, queue)
    _poll(home, tracker, queue, auto=True, approval=TRUSTED)
    (req,) = _of(home, EV_INTAKE_GAP_PROBE_REQUESTED)
    assert "manufacture" not in req.payload
    (reg,) = _of(home, sv.EV_REGISTERED)
    assert "manufacture" not in reg.payload and _sweep(home, factory) == ""


def test_content_that_goes_back_to_an_earlier_probe_needs_a_new_act(home: FactoryHome) -> None:
    """Governance review: A built, B built, then the words reverted to A. The old probe at A
    registered a new item with no act, and a dedupe keyed on the item id built A again."""
    queue, factory = Queue(), Factory()
    tracker = _tracker(_ticket())
    _consented(home, tracker, queue)
    assert _sweep(home, factory) == "run-1"
    _edit(tracker, "2", body="a new HTTP endpoint; the 503 body says 'down'")
    _poll(home, tracker, queue, auto=True)
    _act(home, tracker, queue, auto=True, revision="2")
    _finish(home, queue)
    _poll(home, tracker, queue, auto=True)
    assert _sweep(home, factory) == "run-2"
    _edit(tracker, "3")  # back to the words of revision 1
    _poll(home, tracker, queue, auto=True)
    _poll(home, tracker, queue, auto=True)
    marked = [e for e in _of(home, sv.EV_REGISTERED) if e.payload.get("manufacture")]
    assert len(marked) == 2
    assert _sweep(home, factory) == "" and len(factory.queued) == 2


# --- the sweep: skips and waits ---------------------------------------------------------


def _item(item_id: str, **kw: Any) -> BacklogItem:
    base: dict[str, Any] = {
        "id": item_id,
        "title": f"Item {item_id}",
        "kind": KIND_CODE,
        "capability_class": "bug.fix",
        "structural_facts": ("reproduction: it breaks", "expected_behaviour: it works"),
    }
    base.update(kw)
    return BacklogItem(**base)


def _mark(
    home: FactoryHome,
    item_id: str = "fake-4711",
    *,
    key: str = "4711",
    content: str = "c-1",
    approved_by: str = "operator:ada",
) -> None:
    home.evidence(actor="operator:ada").append(
        sv.EV_REGISTERED,
        item_id,
        tracker="fake",
        key=key,
        how="frozen",
        supersedes="",
        url=_url(item_id),
        approved_by=approved_by,
        manufacture="auto",
        content_revision=content,
    )


def _skipped(home: FactoryHome) -> list[str]:
    return [str(e.payload["reason"]) for e in _of(home, EV_INTAKE_MANUFACTURE_SKIPPED)]


@pytest.fixture
def one(home: FactoryHome) -> FactoryHome:
    home.register_backlog([_item("fake-4711")], actor="t")
    _mark(home)
    return home


def test_a_superseded_item_is_skipped_for_good(home: FactoryHome) -> None:
    home.register_backlog([_item("fake-4711")], actor="t")
    home.register_evolution(_item("fake-4711.r2", supersedes="fake-4711"), actor="t")
    _mark(home)
    factory = Factory()
    assert _sweep(home, factory) == "" and _sweep(home, factory) == ""
    assert _skipped(home) == [sv.SKIP_ITEM_SUPERSEDED] and factory.queued == []


def test_an_item_with_dependencies_is_skipped(home: FactoryHome) -> None:
    home.register_backlog([_item("fake-1"), _item("fake-4711", depends_on=("fake-1",))], actor="t")
    _mark(home)
    factory = Factory()
    assert _sweep(home, factory) == ""
    assert _skipped(home) == [sv.SKIP_HAS_DEPENDENCIES] and factory.queued == []


@pytest.mark.parametrize("kind", [EV_BUILD, EV_ITEM_OUTCOME])
def test_an_item_a_run_built_after_the_registration_is_already_built(
    kind: str, one: FactoryHome
) -> None:
    """Governance review: a run already active built the item (and failed); the sweep only
    asked whether a pull request was opened, so it paid for a second build."""
    one.evidence(actor="worker").append(kind, "fake-4711", status="rejected")
    factory = Factory()
    assert _sweep(one, factory) == ""
    assert _skipped(one) == [sv.SKIP_ALREADY_BUILT] and factory.queued == []


def test_a_build_before_the_registration_does_not_count(home: FactoryHome) -> None:
    home.register_backlog([_item("fake-4711")], actor="t")
    home.evidence(actor="worker").append(EV_ITEM_OUTCOME, "fake-4711", status="rejected")
    _mark(home)
    factory = Factory()
    assert _sweep(home, factory) == "run-1" and not _skipped(home)


def test_an_active_run_that_did_not_build_the_item_still_leaves_one_run(
    one: FactoryHome,
) -> None:
    factory = Factory()
    factory.active = True
    assert _sweep(one, factory) == "" and factory.queued == [] and not _skipped(one)
    factory.active = False
    assert _sweep(one, factory) == "run-1" and _sweep(one, factory) == ""
    assert len(factory.queued) == 1


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda f: f.inactive.add("ada"), sv.SKIP_APPROVER_INACTIVE),
        (lambda f: setattr(f, "route", sv.ROUTE_NONE), sv.SKIP_NO_DELIVERY_ROUTE),
        (lambda f: setattr(f, "refuse", ("spend_cap_unpriced", "no price")), "refused:"),
    ],
)
def test_each_final_skip_is_recorded_once(one: FactoryHome, setup: Any, reason: str) -> None:
    factory = Factory()
    setup(factory)
    for _ in range(3):
        assert _sweep(one, factory) == ""
    (skipped,) = _skipped(one)
    assert skipped.startswith(reason) and factory.queued == []
    (ev,) = _of(one, EV_INTAKE_MANUFACTURE_SKIPPED)
    assert ev.payload["key"] == "4711" and ev.payload["content_revision"] == "c-1"
    assert ev.payload["detail"]


def test_a_sealed_worker_skips(one: FactoryHome) -> None:
    factory = Factory()
    assert _sweep(one, factory, sealed=True) == ""
    assert _skipped(one) == [sv.SKIP_SEALED]


@pytest.mark.parametrize(
    "wait",
    [
        {"out_of_time": lambda: True},
        {"renew": lambda: False},
    ],
)
def test_a_wait_writes_nothing_and_the_next_pass_queues(one: FactoryHome, wait: Any) -> None:
    factory = Factory()
    before = len(list(one.events()))
    assert _sweep(one, factory, **wait) == ""
    assert len(list(one.events())) == before and factory.queued == []
    assert _sweep(one, factory) == "run-1"


def test_a_delivery_route_that_cannot_be_read_waits(one: FactoryHome) -> None:
    """Spend review: a passing GitHub error was a final skip that spent the consent."""
    factory = Factory()
    factory.route = sv.ROUTE_ERROR
    assert _sweep(one, factory) == "" and not _skipped(one) and factory.queued == []
    factory.route = sv.ROUTE_FOUND
    assert _sweep(one, factory) == "run-1"


def test_a_store_failure_records_nothing_and_the_next_pass_retries(one: FactoryHome) -> None:
    factory = Factory()
    factory.boom = True
    assert _sweep(one, factory) == "" and not _skipped(one)
    assert not _of(one, EV_INTAKE_MANUFACTURE_REQUESTED)
    factory.boom = False
    assert _sweep(one, factory) == "run-1"


def test_a_run_the_chain_never_named_is_named_never_queued_again(one: FactoryHome) -> None:
    factory = Factory()
    factory.runs[("fake", "4711", "c-1")] = "run-earlier"
    assert _sweep(one, factory) == ""
    (named,) = _of(one, EV_INTAKE_MANUFACTURE_REQUESTED)
    assert named.payload["run_id"] == "run-earlier" and factory.queued == []


def test_one_run_per_pass_oldest_first(home: FactoryHome) -> None:
    home.register_backlog([_item("fake-1"), _item("fake-2")], actor="t")
    _mark(home, "fake-1", key="1")
    _mark(home, "fake-2", key="2")
    factory = Factory()
    assert _sweep(home, factory) == "run-1"
    assert [q["key"] for q in factory.queued] == ["1"]
    assert _sweep(home, factory) == "run-2"
    assert [q["key"] for q in factory.queued] == ["1", "2"]


def test_the_lease_is_renewed_before_the_find_and_before_the_enqueue(one: FactoryHome) -> None:
    """Governance review: the sweep ran after a lease lost in the tracker writes, unfenced."""
    calls: list[str] = []
    factory = Factory()

    def renew() -> bool:
        calls.append("renew")
        return len(calls) < 2  # lost between the find and the enqueue

    assert _sweep(one, factory, renew=renew) == ""
    assert calls == ["renew", "renew"] and factory.queued == [] and not _skipped(one)


# --- the run it queues ------------------------------------------------------------------


def _store(tmp_path: Path) -> Any:
    from crb.store import init_db, make_engine, make_session_factory
    from crb.store.models import Repo, User

    engine = make_engine(f"sqlite:///{tmp_path / 'q.db'}")
    init_db(engine)
    sessions = make_session_factory(engine)
    with sessions() as s:
        s.add(Repo(name="alpha", language="python", runner="pytest", config_json={}))
        s.add(User(id="ada", subject="local:ada", role="operator"))
        s.add(User(id="bob", subject="local:bob", role="viewer"))
        s.add(User(id="eve", subject="local:eve", role="operator", active=False))
        s.commit()
    return sessions


def _real(tmp_path: Path, sessions: Any, **intake: Any) -> sv.AutoManufacture:
    FactoryHome(tmp_path, "alpha").register_backlog([_item("fake-4711")], actor="t")
    deployment = SimpleNamespace(intake=_settings(**{**_ON, **intake}), home=tmp_path)
    auto = sv.auto_manufacture_for(
        deployment, sessions, "alpha", run_active=lambda: False, delivery_route=lambda: "found"
    )
    assert auto is not None
    return auto


_REQUEST = {
    "tracker": "fake",
    "key": "4711",
    "content_revision": "c-1",
    "item_id": "fake-4711",
    "approved_by": "operator:ada",
}


def _runs(sessions: Any) -> list[Any]:
    from crb.store.models import Run

    with sessions() as s:
        return list(s.scalars(select(Run)))


def _traces(sessions: Any) -> list[Any]:
    from crb.store.models import Event

    with sessions() as s:
        return list(s.scalars(select(Event).where(Event.action == sv.ACTION_MANUFACTURE_QUEUED)))


def test_the_run_delivers_keeps_its_rework_and_shares_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spend review: ``new_run`` drops ``deliver`` and ``max_rework``, so the run built and
    never opened a pull request, and its per-attempt budget did not match the worker's."""
    gated: list[str] = []
    monkeypatch.setattr(sv, "submit_refusals", lambda db, s, body, run: gated.append(body.kind))
    sessions = _store(tmp_path)
    auto = _real(tmp_path, sessions)
    run_id = auto.queue_run(_REQUEST)
    assert run_id == sv.manufacture_run_id("alpha", "fake", "4711", "c-1")
    (run,) = _runs(sessions)
    assert run.id == run_id and run.kind == "factory" and gated == ["factory"]
    assert (run.builder, run.model) == ("claude_code", "claude-sonnet-5")
    assert run.actor == "ada" and run.status == "queued"
    p = run.params_json
    assert p["deliver"] is True and p["max_rework"] == 2
    assert p["max_cost_usd"] == 6.0 and p["budget"]["max_cost_usd"] == 2.0
    assert p["backlog_hash"] == FactoryHome(tmp_path, "alpha").load_backlog().backlog_hash
    assert p["intake_item"] == "fake-4711" and p["intake_auto"] == _REQUEST
    (trace,) = _traces(sessions)
    assert trace.payload_json["run_id"] == run_id and trace.actor == "ada"
    assert auto.find_run(_REQUEST) == run_id
    assert auto.find_run({**_REQUEST, "content_revision": "c-2"}) == ""


@pytest.mark.parametrize(
    ("cap", "rework"),
    [(2.0, 2), (5.0, 2), (20.0, 2), (1.0, 5), (7.0, 5), (0.0001, 5), (6.0, 2), (0.3, 0)],
)
def test_the_spend_cap_admits_the_item_the_run_was_queued_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: float, rework: int
) -> None:
    """Spend review: the share was rounded to the nearest $0.0001, so $2 over 3 attempts
    gave $0.6667 each. The worker reserved $2.0001 for the item and stopped the run before
    it built, at $0 spent, and the sweep never tried that content again. The share must
    round down, and stay above 0, which a budget reads as no cap."""
    from crb.server.spend_cap import Spend, SpendCap, item_reserve

    monkeypatch.setattr(sv, "submit_refusals", lambda db, s, body, run: None)
    sessions = _store(tmp_path)
    auto = _real(
        tmp_path,
        sessions,
        auto_manufacture_max_cost_usd=cap,
        auto_manufacture_max_rework=rework,
    )
    auto.queue_run(_REQUEST)
    (run,) = _runs(sessions)
    p = run.params_json
    share = float(p["budget"]["max_cost_usd"])
    assert 0 < share <= cap / (rework + 1)
    spend_cap = SpendCap.from_params(p)
    assert spend_cap is not None and spend_cap.cap_usd == cap
    nothing = Spend.of_rows([])
    reserve, attempts = item_reserve([share], nothing, max_rework=int(p["max_rework"]))
    assert attempts == rework + 1 and reserve <= cap
    assert spend_cap.check(nothing, reserve=reserve, unit="item", attempts=attempts) is None


def test_two_passes_that_race_on_one_key_queue_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Governance review: two workers both passed the find before either committed. The
    derived run id makes the second insert fail, and that is read as "it exists"."""
    sessions = _store(tmp_path)
    first = _real(tmp_path, sessions)
    second = _real(tmp_path, sessions)
    raced: list[str] = []

    def gate(db: Any, s: Any, body: Any, run: Any) -> None:
        if not raced:  # the other pass commits between this pass's find and its insert
            raced.append("racing")
            raced.append(second.queue_run(_REQUEST))

    monkeypatch.setattr(sv, "submit_refusals", gate)
    assert first.queue_run(_REQUEST) == raced[1]
    (run,) = _runs(sessions)
    assert run.id == raced[1] and len(_traces(sessions)) == 1


def test_a_run_the_submit_gate_refuses_is_never_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "credential_refusal", lambda run, settings: None)
    monkeypatch.setattr(runs_route, "login_refusal", lambda *a, **k: None)
    sessions = _store(tmp_path)
    auto = _real(tmp_path, sessions, auto_manufacture_rung="claude_code:zzz-unknown")
    with pytest.raises(sv.ManufactureRefused) as refused:
        auto.queue_run(_REQUEST)
    assert refused.value.code == "spend_cap_unpriced"
    assert _runs(sessions) == [] and _traces(sessions) == []


def test_only_an_active_operator_counts_as_the_approver(tmp_path: Path) -> None:
    sessions = _store(tmp_path)
    auto = _real(tmp_path, sessions)
    assert auto.approver_active("ada")
    assert not auto.approver_active("bob")  # a viewer
    assert not auto.approver_active("eve")  # deactivated
    assert not auto.approver_active("nobody")


# --- the worker -------------------------------------------------------------------------


def _worker(tmp_path: Path) -> Any:
    from crb.server.worker import Worker, WorkerSettings
    from crb.store import init_db, make_engine

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{home / 'crb.db'}"
    engine = make_engine(url)
    init_db(engine)
    return Worker(WorkerSettings(database_url=url, home=home, worker_id="w-auto"), engine=engine)


@pytest.mark.parametrize(
    ("items", "match"),
    [
        ([_item("fake-1")], "no longer active"),
        ([_item("fake-1"), _item("fake-4711", depends_on=("fake-1",))], "depends on"),
    ],
)
def test_the_worker_refuses_an_item_that_is_gone_or_has_dependencies(
    tmp_path: Path, items: list[BacklogItem], match: str
) -> None:
    from crb.store.models import Run

    worker = _worker(tmp_path)
    FactoryHome(worker.home, "alpha").register_backlog(items, actor="t")
    run = Run(id="r1", repo="alpha", kind="factory", params_json={"intake_item": "fake-4711"})
    ctx = SimpleNamespace(run=run, params=dict(run.params_json))
    with pytest.raises(ValueError, match=match):
        worker._run_factory(ctx)


def test_the_gap_probe_seam_still_builds_positionally_with_the_switch_off() -> None:
    probe = sv.GapProbe(lambda r: "x", lambda r: None, 5)
    assert probe.auto_manufacture is False
    assert replace(probe, auto_manufacture=True).auto_manufacture is True
