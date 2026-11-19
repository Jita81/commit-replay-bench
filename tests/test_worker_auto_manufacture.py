"""The worker's wiring of the automatic build (ADR-0060): the sweep in the timed intake poll.

Navigation
----------
What it is:   The worker half of the automatic build: the sweep the timed intake poll runs
              after it tells the tickets, and the delivery-route check it hands the sweep.
What it does: Pins that with the switch off the sweep is never called and nothing new is
              written; that with it on a consented registration gets exactly one capped,
              delivering factory run through ``Worker._poll_one`` and a second poll queues
              none; that ``_delivery_route`` answers ``found`` for a GitHub App installation
              that may deliver and for an Azure Repos remote the tracker token may reach
              (ADR-0057), ``none`` for neither, and ``error`` when GitHub cannot be asked (a
              network error), which the poll treats as a wait and never as a final skip; that
              a lease lost before the sweep, or a pass out of time, queues nothing and a later
              pass still queues; that a sealed worker skips; and that a sweep that raises
              never fails the poll.
How:          A real ``Worker`` over a SQLite store under ``tmp_path`` with the in-memory
              ``FakeTracker`` (an empty column), a consented registration written on the real
              hash chain, the real submit gate (its credential and login checks stubbed), and
              a GitHub App client replaced by a fake or by a real client over an
              ``httpx.MockTransport``. No model, no network, no money.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0060-a-clean-probe-queues-one-capped-build.md,
              docs/adr/0057-azure-repos-pr-delivery.md
Works with:   src/crb/server/worker.py (``_poll_one`` and ``_delivery_route`` — under test),
              src/crb/server/intake.py (``manufacture_registered``, the sweep it calls),
              tests/test_intake_auto_manufacture.py (the sweep's own suite),
              tests/fixtures/intake.py (the fake tracker)
Tested by:    tests/test_worker_auto_manufacture.py
Touch when:   never for a new repository; the worker gains a delivery route, or the sweep
              moves out of the timed poll.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, update

from crb.factory.backlog import KIND_CODE, BacklogItem
from crb.factory.evidence import EV_INTAKE_MANUFACTURE_REQUESTED, EV_INTAKE_MANUFACTURE_SKIPPED
from crb.server import intake as sv
from crb.server import worker as w
from crb.server.factory_state import FactoryHome
from crb.server.github_app import GitHubApp, GitHubAppError
from crb.server.settings import FactorySettings, GitHubAppSettings, IntakeSettings
from crb.store import init_db, make_engine, make_session_factory
from crb.store.models import LEASE_ROW_PREFIX, Repo, Run, User, WorkerRow
from fixtures.intake import FakeTracker
from fixtures.proven_cells import every_cell_proven

PUBLIC = "https://crb.invalid"
RUNG = "claude_code:claude-sonnet-5"
GITHUB_REMOTE = "https://github.com/acme/alpha"
AZURE_BOARD = "https://dev.azure.com/acme"
AZURE_REMOTE = "https://dev.azure.com/acme/Payments/_git/ledger"
_ON: dict[str, Any] = {
    "gap_probe": True,
    "gap_probe_rung": RUNG,
    "auto_manufacture": True,
    "auto_manufacture_rung": RUNG,
    "auto_manufacture_max_cost_usd": 6.0,
    "auto_manufacture_max_rework": 2,
}
_OFF: dict[str, Any] = {"gap_probe": True, "gap_probe_rung": RUNG}


def _intake(**kw: Any) -> IntakeSettings:
    base: dict[str, Any] = {"tracker": "fake", "column": "Ready", **_ON}
    base.update(kw)
    return IntakeSettings(**base)


def _github(**kw: Any) -> GitHubAppSettings:
    """An enabled app: ``enabled`` asks only for an id and a key; the client is replaced."""
    base: dict[str, Any] = {"app_id": "4242", "private_key": "not-read-by-a-fake-client"}
    base.update(kw)
    return GitHubAppSettings(**base)


class _App:
    """The GitHub App client as ``_delivery_route`` uses it: one installation lookup."""

    def __init__(self, *, can_deliver: bool = True, error: bool = False) -> None:
        self.can_deliver = can_deliver
        self.error = error
        self.asked: list[int] = []

    def installation(self, installation_id: int) -> Any:
        self.asked.append(installation_id)
        if self.error:
            raise GitHubAppError(0, "connection refused")
        return SimpleNamespace(can_deliver=self.can_deliver)


def _item(item_id: str = "fake-4711") -> BacklogItem:
    return BacklogItem(
        id=item_id,
        title=f"Item {item_id}",
        kind=KIND_CODE,
        capability_class="bug.fix",
        structural_facts=("reproduction: it breaks", "expected_behaviour: it works"),
    )


class Stack:
    """A worker, a store, one repository with its listener on, and an empty board."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        intake: IntakeSettings | None = None,
        github: GitHubAppSettings | None = None,
        factory: FactorySettings | None = None,
        url: str = GITHUB_REMOTE,
        config: dict[str, Any] | None = None,
        refuse_unsealed: bool = False,
        app: Any = None,
    ) -> None:
        self.home = tmp_path / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{self.home / 'crb.db'}"
        engine = make_engine(db_url)
        init_db(engine)
        self.factory = make_session_factory(engine)
        self.worker = w.Worker(
            w.WorkerSettings(
                database_url=db_url,
                home=self.home,
                worker_id="w-auto",
                intake=intake if intake is not None else _intake(),
                github=github if github is not None else _github(),
                factory=factory if factory is not None else FactorySettings(),
                public_url=PUBLIC,
                refuse_unsealed=refuse_unsealed,
            ),
            engine=engine,
        )
        self.app = app if app is not None else _App()
        self.worker._github_app_client = self.app
        cfg = {"intake": {"enabled": True}, "github": {"installation_id": 77}}
        if config is not None:
            cfg = config
        with self.factory() as s:
            s.add(Repo(name="alpha", language="python", runner="pytest", url=url, config_json=cfg))
            s.add(User(id="ada", subject="local:ada", role="operator"))
            s.commit()
        self.tracker = FakeTracker()
        self.chain = FactoryHome(self.home, "alpha")

    def consent(self) -> None:
        """A registration an operator's act consented to, after a clean probe."""
        self.chain.register_backlog([_item()], actor="t")
        self.chain.evidence(actor="operator:ada").append(
            sv.EV_REGISTERED,
            "fake-4711",
            tracker="fake",
            key="4711",
            how="frozen",
            supersedes="",
            url=f"{PUBLIC}/factory?item=fake-4711",
            approved_by="operator:ada",
            manufacture="auto",
            content_revision="c-1",
        )

    def poll(self) -> None:
        self.worker._poll_one("alpha", self.tracker, sv.ListenerState(enabled=True))

    def runs(self) -> list[Run]:
        with self.factory() as s:
            return list(s.scalars(select(Run).where(Run.kind == "factory")))

    def of(self, kind: str) -> list[Any]:
        return [e for e in self.chain.events() if e.kind == kind]

    def skipped(self) -> list[str]:
        return [str(e.payload["reason"]) for e in self.of(EV_INTAKE_MANUFACTURE_SKIPPED)]


@pytest.fixture(autouse=True)
def _gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real submit gate, less the two checks that read a host's credentials and login."""
    from crb.server.routes import runs as runs_route

    monkeypatch.setattr(runs_route, "credential_refusal", lambda run, settings: None)
    monkeypatch.setattr(runs_route, "login_refusal", lambda *a, **k: None)
    every_cell_proven(monkeypatch, "S1@claude-sonnet-5")


class _Sweeps:
    """Counts the sweep's calls through the worker, and runs the real one."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[dict[str, Any]] = []
        real = sv.manufacture_registered

        def sweep(home: FactoryHome, **kw: Any) -> str:
            self.calls.append(kw)
            return real(home, **kw)

        monkeypatch.setattr(w, "manufacture_registered", sweep)


# --- the switch -------------------------------------------------------------------------


def test_with_the_switch_off_the_sweep_is_never_called_and_nothing_new_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registration marked while the switch was on stays unbuilt once it is off: the
    poll neither sweeps nor asks the delivery route, and the chain gains no sweep event."""
    sweeps = _Sweeps(monkeypatch)
    stack = Stack(tmp_path, intake=_intake(**{**_OFF, "auto_manufacture": False}))
    stack.consent()
    before = [e.kind for e in stack.chain.events()]
    stack.poll()
    stack.poll()
    assert sweeps.calls == [] and stack.app.asked == []
    assert stack.runs() == []
    after = [e.kind for e in stack.chain.events()]
    assert after[: len(before)] == before
    assert not {EV_INTAKE_MANUFACTURE_REQUESTED, EV_INTAKE_MANUFACTURE_SKIPPED} & set(after)
    with stack.factory() as s:
        from crb.store.models import Event

        traces = s.scalars(select(Event).where(Event.action == sv.ACTION_MANUFACTURE_QUEUED))
        assert list(traces) == []


def test_with_the_switch_on_one_capped_run_is_queued_and_a_second_poll_queues_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sweeps = _Sweeps(monkeypatch)
    stack = Stack(tmp_path)
    stack.consent()
    stack.poll()
    (run,) = stack.runs()
    assert run.id == sv.manufacture_run_id("alpha", "fake", "4711", "c-1")
    assert run.status == "queued" and run.actor == "ada"
    assert (run.builder, run.model) == ("claude_code", "claude-sonnet-5")
    p = dict(run.params_json or {})
    assert p["deliver"] is True and p["max_rework"] == 2 and p["max_cost_usd"] == 6.0
    assert p["intake_item"] == "fake-4711" and p["intake_auto"]["content_revision"] == "c-1"
    (named,) = stack.of(EV_INTAKE_MANUFACTURE_REQUESTED)
    assert named.payload["run_id"] == run.id and named.item_id == "fake-4711"
    # the sweep was handed the fenced tracker's name and the pass's own lease
    (call,) = sweeps.calls
    assert call["tracker"] == "fake" and call["auto"].rung == RUNG
    assert getattr(call["renew"], "__self__", None) is not None
    assert isinstance(call["renew"].__self__, sv.IntakeLease)
    # outside review: the insert transaction re-checks that same lease
    assert call["fence"].__func__ is sv.IntakeLease.renew_in
    assert call["fence"].__self__ is call["renew"].__self__
    assert stack.app.asked == [77]
    stack.poll()
    assert len(sweeps.calls) == 2
    assert [r.id for r in stack.runs()] == [run.id]
    assert len(stack.of(EV_INTAKE_MANUFACTURE_REQUESTED)) == 1 and stack.skipped() == []


def test_a_sealed_worker_skips_the_build_for_good(tmp_path: Path) -> None:
    stack = Stack(tmp_path, refuse_unsealed=True)
    stack.consent()
    stack.poll()
    stack.poll()
    assert stack.runs() == [] and stack.skipped() == [sv.SKIP_SEALED]


# --- the delivery route -----------------------------------------------------------------


def _azure(
    tmp_path: Path, *, switch: bool = True, token: str = "azpat-token", url: str = AZURE_REMOTE
) -> Stack:
    stack = Stack(
        tmp_path,
        intake=_intake(tracker="ado", url=AZURE_BOARD, project="Payments"),
        github=GitHubAppSettings(),  # no GitHub App on this deployment
        factory=FactorySettings(azure_repos_delivery=switch),
        url=url,
        config={"intake": {"enabled": True}},
    )
    stack.worker._tracker_token = lambda: token  # type: ignore[method-assign]
    return stack


@pytest.mark.parametrize(
    ("build", "answer"),
    [
        # the GitHub App: an installation that may push and open a pull request
        (lambda p: Stack(p), sv.ROUTE_FOUND),
        # the GitHub App: an installation without Contents/Pull requests write
        (lambda p: Stack(p, app=_App(can_deliver=False)), sv.ROUTE_NONE),
        # the GitHub App: GitHub could not be asked — a wait, not an answer
        (lambda p: Stack(p, app=_App(error=True)), sv.ROUTE_ERROR),
        # a linked installation, but the remote is not on the app's host: no token goes there
        (lambda p: Stack(p, url="https://gitlab.invalid/acme/alpha"), sv.ROUTE_NONE),
        # no GitHub App on this deployment, whatever the repository's link says
        (lambda p: Stack(p, github=GitHubAppSettings()), sv.ROUTE_NONE),
        # no remote at all
        (lambda p: Stack(p, url=""), sv.ROUTE_NONE),
        # Azure Repos (ADR-0057): the switch on, the board's organisation, a token
        (lambda p: _azure(p), sv.ROUTE_FOUND),
        (lambda p: _azure(p, switch=False), sv.ROUTE_NONE),
        (lambda p: _azure(p, token=""), sv.ROUTE_NONE),
        (
            lambda p: _azure(p, url="https://dev.azure.com/other/Payments/_git/ledger"),
            sv.ROUTE_NONE,
        ),
    ],
    ids=[
        "github-can-deliver",
        "github-read-only",
        "github-unreachable",
        "github-other-host",
        "no-github-app",
        "no-remote",
        "azure",
        "azure-switch-off",
        "azure-no-token",
        "azure-other-organisation",
    ],
)
def test_the_delivery_route_answers(tmp_path: Path, build: Any, answer: str) -> None:
    assert build(tmp_path).worker._delivery_route("alpha") == answer


def test_an_unknown_repository_has_no_delivery_route(tmp_path: Path) -> None:
    assert Stack(tmp_path).worker._delivery_route("nobody") == sv.ROUTE_NONE


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def test_a_network_error_asking_github_is_an_error_not_no_route(tmp_path: Path) -> None:
    """The real client over a transport that cannot connect: the cannot-answer case."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings = _github(private_key=_pem())
    app = GitHubApp(settings, httpx.Client(transport=httpx.MockTransport(refuse)))
    stack = Stack(tmp_path, github=settings, app=app)
    assert stack.worker._delivery_route("alpha") == sv.ROUTE_ERROR


def test_no_delivery_route_is_a_final_skip_through_the_poll(tmp_path: Path) -> None:
    stack = Stack(tmp_path, app=_App(can_deliver=False))
    stack.consent()
    stack.poll()
    stack.app.can_deliver = True  # a route configured later does not revive this content
    stack.poll()
    assert stack.runs() == [] and stack.skipped() == [sv.SKIP_NO_DELIVERY_ROUTE]


def test_a_delivery_route_github_cannot_answer_waits_and_the_next_poll_queues(
    tmp_path: Path,
) -> None:
    """Spend review: a passing network error must not spend the consent on a final skip."""
    stack = Stack(tmp_path, app=_App(error=True))
    stack.consent()
    before = len(list(stack.chain.events()))
    stack.poll()
    assert stack.runs() == [] and stack.skipped() == []
    assert not stack.of(EV_INTAKE_MANUFACTURE_REQUESTED)
    # the poll's own events aside, the sweep wrote nothing
    assert all(
        e.kind not in (EV_INTAKE_MANUFACTURE_REQUESTED, EV_INTAKE_MANUFACTURE_SKIPPED)
        for e in list(stack.chain.events())[before:]
    )
    stack.app.error = False
    stack.poll()
    assert len(stack.runs()) == 1 and stack.skipped() == []


def test_an_azure_route_queues_the_run_through_the_poll(tmp_path: Path) -> None:
    stack = _azure(tmp_path)
    stack.consent()
    stack.poll()
    (run,) = stack.runs()
    assert dict(run.params_json or {})["deliver"] is True and stack.skipped() == []


def test_a_route_lookup_that_raises_never_fails_the_poll_and_the_next_pass_queues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = Stack(tmp_path)
    stack.consent()
    boom = {"on": True}
    real = stack.worker._delivery_route

    def route(repo: str) -> str:
        if boom["on"]:
            raise RuntimeError("the store fell over")
        return real(repo)

    monkeypatch.setattr(stack.worker, "_delivery_route", route)
    stack.poll()  # does not raise
    assert stack.runs() == [] and stack.skipped() == []
    boom["on"] = False
    stack.poll()
    assert len(stack.runs()) == 1


# --- the lease and the pass's time ------------------------------------------------------


def _steal_the_lease(stack: Stack) -> None:
    """Another pass takes the repository's intake lease over (its holder changes)."""
    with stack.factory() as s:
        s.execute(
            update(WorkerRow)
            .where(WorkerRow.worker_id.like(f"{LEASE_ROW_PREFIX}intake:alpha%"))
            .values(hostname="another-pass")
        )
        s.commit()


def test_a_lease_lost_before_the_sweep_queues_nothing_and_a_later_pass_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lease is taken over after the outcome writes and before the sweep: the sweep's
    first renewal fails, and it stops before it asks for a run."""
    stack = Stack(tmp_path)
    stack.consent()
    real = w.apply_outcome_map
    steal = {"on": True}

    def then_lost(tracker: Any, **kw: Any) -> Any:
        out = real(tracker, **kw)
        if steal["on"]:
            _steal_the_lease(stack)
        return out

    monkeypatch.setattr(w, "apply_outcome_map", then_lost)
    stack.poll()
    assert stack.runs() == [] and stack.skipped() == []
    assert not stack.of(EV_INTAKE_MANUFACTURE_REQUESTED)
    assert stack.app.asked == []  # stopped before the route was asked, too
    steal["on"] = False
    _clear_leases(stack)
    stack.poll()
    assert len(stack.runs()) == 1


def _clear_leases(stack: Stack) -> None:
    from sqlalchemy import delete

    with stack.factory() as s:
        s.execute(delete(WorkerRow).where(WorkerRow.worker_id.like(f"{LEASE_ROW_PREFIX}%")))
        s.commit()


def test_a_tracker_whose_lease_was_lost_on_a_write_never_reaches_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that outlived the lease marks the fenced tracker lost: no sweep follows."""
    sweeps = _Sweeps(monkeypatch)
    stack = Stack(tmp_path)
    stack.consent()

    def lost_on_a_write(tracker: Any, **kw: Any) -> None:
        tracker.lost = True

    monkeypatch.setattr(w, "apply_outcome_map", lost_on_a_write)
    stack.poll()
    assert sweeps.calls == [] and stack.runs() == [] and stack.skipped() == []


class _Clock:
    """``time`` for the worker module, with a ``monotonic`` the test moves."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def test_a_pass_out_of_time_queues_nothing_and_the_next_pass_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep measures the pass from its start in ``_poll_one``, against its budget."""
    stack = Stack(tmp_path)
    stack.consent()
    clock = _Clock(w.time)
    monkeypatch.setattr(w, "time", clock)
    real = w.apply_outcome_map
    late = {"on": True}

    def slow(tracker: Any, **kw: Any) -> Any:
        if late["on"]:
            clock.now += float(stack.worker.settings.intake.poll_budget_s) + 1
        return real(tracker, **kw)

    monkeypatch.setattr(w, "apply_outcome_map", slow)
    stack.poll()
    assert stack.runs() == [] and stack.skipped() == []
    late["on"] = False
    stack.poll()
    assert len(stack.runs()) == 1
