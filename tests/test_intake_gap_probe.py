"""The gap probe (ADR-0059): one blind trial build of an approved ticket, asked what it guessed.

Navigation
----------
What it is:   The gap probe's suite: ``parse_guesses``, the settings that refuse an unsafe
              probe, the poll's and the Register act's probe step against a fake tracker and
              a fake queue, and the worker's ``gap_probe`` run kind against a fake builder.
What it does: Pins that the probe is off by default and changes nothing when off; that it
              runs once per ticket content and never again because of its own writes; that
              questions go in the existing readiness comment with ``crb:needs-info`` and the
              move back; that a clean probe registers under the approval that asked for it,
              with no second approval and no second probe; that a failed, dead or reclaimed
              probe fails closed; that every question is redacted and the builder's guess
              dropped; and that the run kind cannot be created through the API.
How:          A real ``FactoryHome`` under ``tmp_path`` (the real hash chain), the
              ``FakeTracker``, an injected :class:`~crb.server.intake.GapProbe` whose enqueue
              only records, and a monkeypatched builder and workspace for the worker. No
              model, no network, no money.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0059-a-gap-probe-asks-what-the-build-guessed.md
Works with:   src/crb/intake/gap_probe.py (parse_guesses and probe_state under test),
              src/crb/server/intake.py (the poll and the Register act's probe step),
              src/crb/server/worker.py (the gap_probe run kind),
              src/crb/server/settings.py (the start-up refusals),
              src/crb/server/routes/runs.py (the probe run's served cost),
              tests/fixtures/intake.py (the fake tracker)
Tested by:    tests/test_intake_gap_probe.py
Touch when:   never for a new repository; the probe gains a state or a step.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from crb.builders.base import BuildOutcome
from crb.core.spec import Language, RepoConfig
from crb.factory.evidence import (
    EV_INTAKE_GAP_PROBE_FAILED,
    EV_INTAKE_GAP_PROBE_FINISHED,
    EV_INTAKE_GAP_PROBE_REQUESTED,
)
from crb.factory.standard import Readers, Standard
from crb.intake import client as c
from crb.intake import gap_probe as gp
from crb.server import intake as sv
from crb.server.factory_state import FactoryHome
from crb.server.settings import IntakeSettings
from crb.store.jobs import KIND_GAP_PROBE
from fixtures.intake import FakeTracker

READY_AC = (
    "method_path: POST /health",
    "request_shape: no body",
    "response_shape: 200 with {status: string}",
    "error_contract: 503 when a dependency is down",
)
PROVEN = Readers(standard_for=lambda cell: Standard("S1@claude-sonnet-5", signed=True))
TRUSTED = sv.ApprovalPolicy(allow_authors=("ada@example.invalid",))
PROBE_KINDS = (
    EV_INTAKE_GAP_PROBE_REQUESTED,
    EV_INTAKE_GAP_PROBE_FINISHED,
    EV_INTAKE_GAP_PROBE_FAILED,
)


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
        "author": "ada@example.invalid",
    }
    base.update(kw)
    return c.Ticket(**base)


def _tracker(ticket: c.Ticket) -> FakeTracker:
    t = FakeTracker({ticket.key: ticket})
    t.column = [c.TicketRef(key=ticket.key, revision=ticket.revision, title=ticket.title)]
    return t


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


def _url(item_id: str) -> str:
    return f"https://crb.invalid/factory?item={item_id}"


def _poll(home: FactoryHome, tracker: FakeTracker, **kw: Any) -> sv.PollReport:
    defaults: dict[str, Any] = {
        "tracker": tracker,
        "listener": sv.ListenerState(enabled=True),
        "column": "Ready",
        "home": home,
        "route_for": lambda item: _deliver(),
        "item_url": _url,
        "approval": TRUSTED,
        "gate": PROVEN,
    }
    defaults.update(kw)
    return sv.poll_repository("alpha", **defaults)


class Queue:
    """The probe's queue seam: records each request, answers a settable run status, and
    records each run it was asked to cancel."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status: dict[str, str | None] = {}
        self.refuse = refuse
        self.cancelled: list[str] = []

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)
        self.status[run_id] = "cancelled"

    def enqueue(self, request: Any) -> str:
        if self.refuse:
            raise RuntimeError("queue is full")
        run_id = f"probe-{len(self.requests) + 1}"
        self.requests.append(dict(request))
        self.status[run_id] = "queued"
        return run_id

    def run_status(self, run_id: str) -> str | None:
        return self.status.get(run_id)

    def probe(self, n: int = 5) -> sv.GapProbe:
        return sv.GapProbe(self.enqueue, self.run_status, n, self.cancel)


def _finish(home: FactoryHome, queue: Queue, questions: list[dict[str, str]]) -> None:
    """What the worker writes when the probe's build ends: the result, keyed on the request."""
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
        questions=questions,
        cost_usd=0.4,
        tokens=100,
    )
    queue.status[run_id] = "succeeded"


def _kinds(home: FactoryHome) -> list[str]:
    return [e.kind for e in home.events()]


def _probe_events(home: FactoryHome) -> list[Any]:
    return [e for e in home.events() if e.kind in PROBE_KINDS]


@pytest.fixture
def home(tmp_path: Path) -> FactoryHome:
    return FactoryHome(tmp_path, "alpha")


ASKED = [{"decision": "error_text", "question": "What exact text does the 503 body carry?"}]


# --- parse_guesses ----------------------------------------------------------------------


def test_parse_guesses_keeps_plain_known_questions_and_drops_the_guess() -> None:
    raw = [
        {"decision": "name", "question": "What is the route's handler called?", "guessed": "h"},
        {"decision": "format", "question": "  Which date format?  ", "guessed": "ISO"},
    ]
    out = gp.parse_guesses(raw, 5)
    assert [(g.decision, g.question) for g in out] == [
        ("name", "What is the route's handler called?"),
        ("format", "Which date format?"),
    ]
    assert all("guessed" not in g.to_doc() for g in out)


@pytest.mark.parametrize(
    "entry",
    [
        {"decision": "colour", "question": "An unknown decision kind?"},
        {"decision": "name", "question": "two\nlines"},
        {"decision": "name", "question": "carriage\rreturn"},
        {"decision": "name", "question": "a fence ``` inside"},
        {"decision": "name", "question": "x" * (gp.MAX_QUESTION_CHARS + 1)},
        {"decision": "name", "question": ""},
        {"question": "no decision"},
        {"decision": "name", "question": None},
        {"decision": "name", "question": 42},
        "not a mapping",
    ],
)
def test_parse_guesses_drops_an_entry_that_is_not_one_plain_line_of_a_known_kind(
    entry: Any,
) -> None:
    assert gp.parse_guesses([entry], 5) == []


def test_parse_guesses_drops_casefold_duplicates_and_caps_at_n() -> None:
    raw = [
        {"decision": "name", "question": "What is it called?"},
        {"decision": "rule", "question": "WHAT IS IT CALLED?"},
        *({"decision": "value", "question": f"Which limit, number {i}?"} for i in range(9)),
    ]
    out = gp.parse_guesses(raw, 3)
    assert [g.question for g in out] == [
        "What is it called?",
        "Which limit, number 0?",
        "Which limit, number 1?",
    ]
    assert gp.parse_guesses(raw, 0) == [] and gp.parse_guesses("junk", 5) == []
    assert gp.MAX_QUESTION_CHARS == 240


def test_parse_guesses_redacts_every_question() -> None:
    """Critique: a question goes to a ticket other people read, so a secret the build saw
    must never reach it."""
    token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789AB"
    out = gp.parse_guesses(
        [{"decision": "value", "question": f"Should the token {token} be used?"}], 5
    )
    (q,) = out
    assert token not in q.question and "[REDACTED" in q.question


# --- settings ---------------------------------------------------------------------------


def _settings(**kw: Any) -> IntakeSettings:
    base: dict[str, Any] = {"tracker": "fake", "column": "Ready"}
    base.update(kw)
    return IntakeSettings(**base)


def test_the_probe_is_off_by_default_with_the_designed_defaults() -> None:
    s = _settings()
    assert s.gap_probe is False and s.gap_probe_rung == ""
    assert s.gap_probe_max_questions == 5 and s.gap_probe_max_cost_usd == 2.0
    assert {"gap_probe", "gap_probe_rung", "gap_probe_max_questions"} <= set(s.redacted())


def test_settings_refuse_a_probe_on_with_no_rung() -> None:
    with pytest.raises(ValidationError, match="gap_probe_rung is empty"):
        _settings(gap_probe=True)


def test_settings_refuse_a_rung_that_is_not_claude_code() -> None:
    """Critique: only claude_code reports its guesses; any other builder would 'find' none."""
    with pytest.raises(ValidationError, match="only claude_code"):
        _settings(gap_probe=True, gap_probe_rung="aider:claude-sonnet-5")
    with pytest.raises(ValidationError, match="only claude_code"):
        _settings(gap_probe_rung="openai_api:gpt-x")  # refused even while off


def test_settings_refuse_an_unattended_probe() -> None:
    """Critique: with approval off, every edit to any ticket would spend on a probe."""
    with pytest.raises(ValidationError, match="require_approval"):
        _settings(
            gap_probe=True, gap_probe_rung="claude_code:claude-sonnet-5", require_approval=False
        )


@pytest.mark.parametrize(
    "kw",
    [
        {"gap_probe_max_questions": 0},
        {"gap_probe_max_questions": 11},
        {"gap_probe_max_cost_usd": 0},
        {"gap_probe_max_cost_usd": -1.0},
        {"gap_probe_max_cost_usd": float("inf")},
        {"gap_probe_max_cost_usd": 0.00001},
        {"gap_probe_max_cost_usd": 1_000_001.0},
    ],
)
def test_settings_refuse_out_of_range_bounds(kw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _settings(**kw)


def test_settings_accept_a_complete_probe() -> None:
    s = _settings(gap_probe=True, gap_probe_rung=" claude_code:claude-sonnet-5 ")
    assert s.gap_probe_rung == "claude_code:claude-sonnet-5"


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("claude_code : claude-sonnet-5", "claude_code:claude-sonnet-5"),
        (" claude_code: claude-sonnet-5 @ anthropic ", "claude_code:claude-sonnet-5@anthropic"),
    ],
)
def test_settings_store_the_probe_rung_as_one_canonical_label(raw: str, label: str) -> None:
    """Review: the check stripped each part but the label was stored as typed, so the run
    queued under it named builder ``'claude_code '``, not the one validated."""
    assert _settings(gap_probe=True, gap_probe_rung=raw).gap_probe_rung == label


#: Each names claude_code and passed the old start-up check, then the probe's own run
#: request refused its model or its one-label ladder (at most 128 characters, letters,
#: digits and ``._:/@-``) at the first poll that tried to queue a probe.
_REFUSED_PROBE_RUNGS = [
    "claude_code:" + "m" * 129,
    "claude_code:claude-sonnet-5@" + "p" * 65,
    "claude_code:" + "m" * 120 + "@" + "p" * 8,
    "claude_code:claude sonnet-5",
    "claude_code:claude-sonnet-5#1",
]


@pytest.mark.parametrize("rung", _REFUSED_PROBE_RUNGS)
@pytest.mark.parametrize("on", [True, False])
def test_settings_refuse_a_rung_the_probe_run_request_refuses(rung: str, on: bool) -> None:
    """Such a rung passed start-up, then the first poll failed to build the probe's run
    request. ADR-0060 decision 9 applied to the probe: start-up builds that request."""
    kw = {**_ON, "gap_probe_rung": rung} if on else {"gap_probe_rung": rung}
    with pytest.raises(ValidationError, match=r"gap_probe_rung .*a run request refuses it"):
        _settings(**kw)


def test_the_longest_probe_rung_start_up_accepts_builds_a_real_run_request() -> None:
    """The request is built here by hand, not through the shared helper, so a helper that
    drifts from what the probe's gate reads fails this test."""
    from crb.server.schemas import RunCreateRequest

    rung = "claude_code:" + "m" * (128 - len("claude_code:"))
    s = _settings(**{**_ON, "gap_probe_rung": rung})
    assert s.gap_probe_rung == rung and len(rung) == 128
    builder, _, model = rung.partition(":")
    body = RunCreateRequest(
        repo="alpha",
        kind="blind",
        mode="blind",
        builder=builder,
        model=model,
        ladder=[rung],
        max_cost_usd=1.5,
    )
    assert body.stored_ladder() == [rung]
    with pytest.raises(ValidationError, match="a run request refuses it"):
        _settings(**{**_ON, "gap_probe_rung": rung + "m"})


def test_start_up_and_the_probe_build_their_request_through_one_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check is only worth having if start-up builds the request the probe queues: both
    call ``schemas.gap_probe_request``, and the probe's gate reads exactly what it returns."""
    from crb.server import schemas
    from crb.server import settings as st

    assert sv.gap_probe_request is schemas.gap_probe_request
    assert st.gap_probe_request is schemas.gap_probe_request
    real = schemas.gap_probe_request
    calls: list[tuple[str, str, float]] = []

    def spy(repo: str, rung: str, *, max_cost_usd: float) -> Any:
        calls.append((repo, rung, max_cost_usd))
        return real(repo, rung, max_cost_usd=max_cost_usd)

    monkeypatch.setattr(st, "gap_probe_request", spy)
    monkeypatch.setattr(sv, "gap_probe_request", spy)
    bodies: list[Any] = []
    monkeypatch.setattr(sv, "submit_refusals", lambda db, settings, body, run: bodies.append(body))
    on = _deployment(**_ON)
    rung = "claude_code:claude-sonnet-5"
    assert calls == [("start-up-check", rung, 1.5)]
    probe = sv.gap_probe_for(on, _queue_with_repo(tmp_path), "alpha")
    assert probe is not None
    probe.enqueue({"key": "4711", "approved_by": "operator:ada"})
    assert calls[1:] == [("alpha", rung, 1.5)]
    (body,) = bodies
    assert body.model_dump() == real("alpha", rung, max_cost_usd=1.5).model_dump()
    assert (body.kind, body.mode, body.builder, body.model) == (
        "blind",
        "blind",
        "claude_code",
        "claude-sonnet-5",
    )


# --- the run kind -----------------------------------------------------------------------


def test_the_probe_kind_is_a_worker_kind_but_never_client_creatable() -> None:
    """Critique: a client that could create a probe run could spend without an approval."""
    from crb.server import schemas
    from crb.store import jobs

    assert KIND_GAP_PROBE == "gap_probe" and KIND_GAP_PROBE in jobs.RUN_KINDS
    assert KIND_GAP_PROBE not in schemas.RUN_KINDS
    with pytest.raises(ValidationError):
        schemas.RunCreateRequest(repo="alpha", kind=KIND_GAP_PROBE)


def _queue_with_repo(tmp_path: Path) -> Any:
    from crb.store import init_db, make_engine, make_session_factory
    from crb.store.models import Repo

    engine = make_engine(f"sqlite:///{tmp_path / 'q.db'}")
    init_db(engine)
    sessions = make_session_factory(engine)
    with sessions() as s:
        s.add(Repo(name="alpha", language="python", runner="pytest", config_json={}))
        s.commit()
    return sessions


def _deployment(**intake: Any) -> SimpleNamespace:
    return SimpleNamespace(intake=_settings(**intake), factory=None)


_ON: dict[str, Any] = {
    "gap_probe": True,
    "gap_probe_rung": "claude_code:claude-sonnet-5",
    "gap_probe_max_cost_usd": 1.5,
    "gap_probe_max_questions": 3,
}


def test_gap_probe_for_is_none_when_off_and_queues_one_blind_run_when_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.store.jobs import JobQueue

    gated: list[tuple[str, str, Any]] = []
    monkeypatch.setattr(
        sv,
        "submit_refusals",
        lambda db, settings, body, run: gated.append((body.kind, run.kind, settings)),
    )
    sessions = _queue_with_repo(tmp_path)
    assert sv.gap_probe_for(_deployment(), sessions, "alpha") is None
    on = _deployment(**_ON)
    probe = sv.gap_probe_for(on, sessions, "alpha")
    assert probe is not None and probe.max_questions == 3
    run_id = probe.enqueue({"key": "4711", "approved_by": "operator:ada"})
    run = JobQueue(sessions).get(run_id)
    assert run is not None and run.kind == KIND_GAP_PROBE and run.mode == "blind"
    assert (run.builder, run.model) == ("claude_code", "claude-sonnet-5")
    assert run.actor == "operator:ada"
    assert run.params_json["max_cost_usd"] == 1.5 and run.params_json["key"] == "4711"
    assert probe.run_status(run_id) == "queued" and probe.run_status("nope") is None
    # the probe met the one submit gate, read as the blind build it runs (P-160)
    assert gated == [("blind", "blind", on)]


def test_a_probe_the_submit_gate_refuses_is_never_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the probe queued a spending run past ``submit_refusals``. An unpriced
    model under the probe's cap is refused by the real gate and nothing reaches the queue."""
    from crb.server.deps import ApiError
    from crb.server.routes import runs as runs_route
    from crb.store.models import Run

    monkeypatch.setattr(runs_route, "credential_refusal", lambda run, settings: None)
    monkeypatch.setattr(runs_route, "login_refusal", lambda *a, **k: None)
    sessions = _queue_with_repo(tmp_path)
    probe = sv.gap_probe_for(
        _deployment(**{**_ON, "gap_probe_rung": "claude_code:zzz-unknown"}), sessions, "alpha"
    )
    assert probe is not None
    with pytest.raises(ApiError) as refused:
        probe.enqueue({"key": "4711", "approved_by": "operator:ada"})
    assert refused.value.code == "spend_cap_unpriced"
    with sessions() as s:
        assert s.query(Run).count() == 0


# --- off: byte-identical ----------------------------------------------------------------


def _strip(home: FactoryHome) -> list[tuple[str, str, dict[str, Any]]]:
    return [(e.kind, e.item_id, dict(e.payload)) for e in home.events()]


@pytest.mark.parametrize("ac", [READY_AC, READY_AC[:2]])
def test_with_the_probe_off_the_poll_writes_exactly_what_it_wrote_before(
    ac: tuple[str, ...], tmp_path: Path
) -> None:
    a, b = FactoryHome(tmp_path / "a", "alpha"), FactoryHome(tmp_path / "b", "alpha")
    ta, tb = _tracker(_ticket(acceptance_criteria=ac)), _tracker(_ticket(acceptance_criteria=ac))
    _poll(a, ta)
    _poll(b, tb, gap_probe=None)
    assert ta.calls == tb.calls and ta.comments == tb.comments and ta.labels == tb.labels
    assert _strip(a) == _strip(b)
    assert not _probe_events(a)
    reads = [e.payload for e in a.events() if e.kind == sv.EV_READ]
    assert reads and all("gap_probe_run_id" not in p and "gap_probe_state" not in p for p in reads)


# --- the poll ---------------------------------------------------------------------------


def test_an_approved_ready_ticket_is_probed_once_and_not_registered_while_it_runs(
    home: FactoryHome,
) -> None:
    queue = Queue()
    tracker = _tracker(_ticket())
    report = _poll(home, tracker, gap_probe=queue.probe())
    assert report.registered == 0 and home.load_backlog() is None
    (row,) = report.rows
    assert row.stopped == sv.REASON_GAP_PROBE_PENDING and not row.registered
    (req,) = queue.requests
    assert req["approved_by"] == "allowlist:ada@example.invalid"
    assert req["subject"] == "Add a POST /health route" and "POST /health" in req["message"]
    (ev,) = _probe_events(home)
    assert ev.kind == EV_INTAKE_GAP_PROBE_REQUESTED and ev.payload["run_id"] == "probe-1"
    # polled again while it runs: still one request, still nothing registered
    for _ in range(3):
        _poll(home, tracker, gap_probe=queue.probe())
    assert len(queue.requests) == 1 and home.load_backlog() is None


def test_a_clean_probe_registers_under_the_approval_that_asked_for_it(
    home: FactoryHome,
) -> None:
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    _finish(home, queue, [])
    report = _poll(home, tracker, gap_probe=queue.probe())
    assert report.registered == 1 and len(queue.requests) == 1
    (reg,) = [e for e in home.events() if e.kind == sv.EV_REGISTERED]
    assert reg.payload["approved_by"] == "allowlist:ada@example.invalid"
    assert tracker.labels["4711"] == c.LABEL_QUEUED


def test_questions_go_in_the_existing_comment_with_needs_info_and_one_move_back(
    home: FactoryHome,
) -> None:
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe(), return_state="New")
    _finish(home, queue, ASKED)
    report = _poll(home, tracker, gap_probe=queue.probe(), return_state="New")
    assert report.registered == 0 and home.load_backlog() is None
    marker = c.marker_for("fake", "4711")
    assert list(tracker.comments["4711"]) == [marker]  # the existing marker, no new comment
    assert ASKED[0]["question"] in tracker.comments["4711"][marker]
    assert tracker.labels["4711"] == c.LABEL_NEEDS_INFO
    assert tracker.states["4711"] == "New"
    writes = len(tracker.calls)
    # polled again: nothing more is written, nothing more is asked
    _poll(home, tracker, gap_probe=queue.probe(), return_state="New")
    assert [v for v, _ in tracker.calls[writes:] if v != "entered"] == []
    assert [v for v, _ in tracker.calls].count("transition") == 1
    assert len(queue.requests) == 1


def test_the_products_own_writes_never_ask_for_a_second_probe(home: FactoryHome) -> None:
    """Critique: the probe's comment, label and move bump a tracker's revision; keyed on the
    revision, each would have asked for (and spent on) another probe."""
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe(), return_state="New")
    _finish(home, queue, ASKED)
    _poll(home, tracker, gap_probe=queue.probe(), return_state="New")
    # the board bumps the revision for the comment and the label; the words are the same
    for rev in ("2", "3"):
        bumped = _ticket(revision=rev, state="New")
        tracker.tickets["4711"] = bumped
        tracker.column = [c.TicketRef(key="4711", revision=rev, title=bumped.title)]
        _poll(home, tracker, gap_probe=queue.probe(), return_state="New")
    assert len(queue.requests) == 1
    assert [e.kind for e in _probe_events(home)].count(EV_INTAKE_GAP_PROBE_REQUESTED) == 1


def test_an_edit_to_the_tickets_words_asks_for_a_new_probe(home: FactoryHome) -> None:
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    _finish(home, queue, ASKED)
    _poll(home, tracker, gap_probe=queue.probe())
    edited = _ticket(revision="2", body="a new HTTP endpoint; the 503 body says 'down'")
    tracker.tickets["4711"] = edited
    tracker.column = [c.TicketRef(key="4711", revision="2", title=edited.title)]
    _poll(home, tracker, gap_probe=queue.probe())
    assert len(queue.requests) == 2
    assert queue.requests[0]["content_revision"] != queue.requests[1]["content_revision"]


def test_a_failed_probe_fails_closed_and_is_never_retried(home: FactoryHome) -> None:
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    req = queue.requests[0]
    home.evidence(actor="worker").append(
        EV_INTAKE_GAP_PROBE_FAILED,
        req["item_id"],
        tracker="fake",
        key="4711",
        revision="1",
        content_revision=req["content_revision"],
        run_id="probe-1",
        reason=gp.FAIL_COST_UNKNOWN,
    )
    for _ in range(2):
        report = _poll(home, tracker, gap_probe=queue.probe())
        (row,) = report.rows
        assert row.stopped == sv.REASON_GAP_PROBE_FAILED
    assert len(queue.requests) == 1 and home.load_backlog() is None
    assert sv.EV_REGISTERED not in _kinds(home)


def test_switching_the_probe_off_alone_never_registers_a_failed_ticket(
    home: FactoryHome,
) -> None:
    """Review: the failed row's advice once said only "switch the gap probe off", but an
    unforced pass at the same revision serves the cached failed row; the advice must name
    the re-post."""
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    queue.status["probe-1"] = "failed"
    _poll(home, tracker, gap_probe=queue.probe())
    (row,) = _poll(home, tracker, gap_probe=None).rows
    assert row.stopped == sv.REASON_GAP_PROBE_FAILED
    assert home.load_backlog() is None
    assert "Post the feedback again" in sv.GAP_PROBE_FAILED_ADVICE
    assert row.stopped_advice == sv.GAP_PROBE_FAILED_ADVICE


@pytest.mark.parametrize("status", [None, "failed", "cancelled", "succeeded"])
def test_a_probe_whose_run_died_without_a_result_is_recorded_failed_once(
    status: str | None, home: FactoryHome
) -> None:
    """Critique: a probe run that vanished or ended without writing its result would have
    held the ticket as pending for ever."""
    queue = Queue()
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    queue.status["probe-1"] = status
    for _ in range(3):
        report = _poll(home, tracker, gap_probe=queue.probe())
    (row,) = report.rows
    assert row.stopped == sv.REASON_GAP_PROBE_FAILED
    failed = [e for e in home.events() if e.kind == EV_INTAKE_GAP_PROBE_FAILED]
    assert len(failed) == 1 and failed[0].payload["reason"] == gp.FAIL_RUN_ENDED
    assert len(queue.requests) == 1 and home.load_backlog() is None


def test_an_unapproved_author_is_not_probed_and_waits_for_the_operator(
    home: FactoryHome,
) -> None:
    queue = Queue()
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    report = _poll(home, tracker, gap_probe=queue.probe())
    assert report.awaiting == 1 and queue.requests == [] and not _probe_events(home)


def test_a_queue_that_refuses_stops_the_ticket_and_records_no_request(
    home: FactoryHome,
) -> None:
    queue = Queue(refuse=True)
    report = _poll(home, _tracker(_ticket()), gap_probe=queue.probe())
    (row,) = report.rows
    assert row.stopped == sv.REASON_REFUSED and not row.registered
    assert not _probe_events(home)
    (stop,) = [e for e in home.events() if e.kind == sv.EV_STOPPED]
    assert stop.payload["step"] == "gap_probe" and "queue is full" in stop.payload["detail"]


# --- the Register act -------------------------------------------------------------------


def _register(home: FactoryHome, tracker: FakeTracker, queue: Queue) -> sv.IntakeRow:
    return sv.register_approved(
        "alpha",
        "4711",
        revision="1",
        tracker=tracker,
        home=home,
        item_url=_url,
        approver="operator:ada",
        gap_probe=queue.probe(),
    )


def test_the_register_act_asks_for_the_probe_and_the_poll_registers_its_clean_result(
    home: FactoryHome,
) -> None:
    """Critique: the act wrote no read, so the poll would have treated the ticket as finished
    with and never acted on the probe it asked for; and the clean result must register
    under the operator's approval without asking them again or probing again."""
    queue = Queue()
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    _poll(home, tracker, gap_probe=queue.probe(), approval=sv.ApprovalPolicy())
    row = _register(home, tracker, queue)
    assert row.stopped == sv.REASON_GAP_PROBE_PENDING and not row.awaiting_approval
    assert not row.registered and home.load_backlog() is None
    (req,) = queue.requests
    assert req["approved_by"] == "operator:ada"
    _finish(home, queue, [])
    report = _poll(home, tracker, gap_probe=queue.probe(), approval=sv.ApprovalPolicy())
    assert report.registered == 1 and report.awaiting == 0 and len(queue.requests) == 1
    (reg,) = [e for e in home.events() if e.kind == sv.EV_REGISTERED]
    assert reg.payload["approved_by"] == "operator:ada"
    assert _kinds(home).count(sv.EV_AWAITING) == 1  # no second approval wait


def test_the_register_act_refuses_while_the_probe_runs_failed_or_asked(
    home: FactoryHome,
) -> None:
    queue = Queue()
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    _poll(home, tracker, gap_probe=queue.probe(), approval=sv.ApprovalPolicy())
    _register(home, tracker, queue)
    with pytest.raises(sv.ApprovalRefused) as err:
        _register(home, tracker, queue)
    assert err.value.code == sv.REASON_GAP_PROBE_PENDING and len(queue.requests) == 1
    _finish(home, queue, ASKED)
    with pytest.raises(sv.ApprovalRefused) as err:
        _register(home, tracker, queue)
    assert err.value.code == "gap_probe_questions"
    assert home.load_backlog() is None and len(queue.requests) == 1


def test_the_register_act_refuses_a_failed_probe(home: FactoryHome) -> None:
    queue = Queue()
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    _poll(home, tracker, gap_probe=queue.probe(), approval=sv.ApprovalPolicy())
    _register(home, tracker, queue)
    queue.status["probe-1"] = None  # the run vanished
    with pytest.raises(sv.ApprovalRefused) as err:
        _register(home, tracker, queue)
    assert err.value.code == sv.REASON_GAP_PROBE_FAILED and home.load_backlog() is None


def test_a_register_act_whose_queue_refuses_registers_nothing(home: FactoryHome) -> None:
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    _poll(home, tracker, approval=sv.ApprovalPolicy())
    with pytest.raises(sv.ApprovalRefused) as err:
        _register(home, tracker, Queue(refuse=True))
    assert err.value.code == "register_refused"
    assert not _probe_events(home) and home.load_backlog() is None


# --- the worker's run kind --------------------------------------------------------------


class _Builder:
    def __init__(self, outcome: BuildOutcome | None = None, boom: bool = False) -> None:
        self.outcome = outcome
        self.boom = boom
        self.built = 0

    def build(self, ws: Any, brief: Any, budget: Any) -> BuildOutcome:
        self.built += 1
        assert brief.mode == "blind" and budget.max_cost_usd == 1.5
        if self.boom:
            raise RuntimeError("the builder fell over")
        assert self.outcome is not None
        return self.outcome


class _Workspaces:
    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.removed: list[Path] = []

    @contextmanager
    def at_ref(self, git: Any, ref: str, dest: Path, config: Any = None) -> Any:
        self.opened.append(dest)
        try:
            yield SimpleNamespace(path=dest)
        finally:
            self.removed.append(dest)


def _outcome(**kw: Any) -> BuildOutcome:
    base: dict[str, Any] = {
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "mode": "blind",
        "cost_usd": 0.37,
        "tokens_in": 1000,
        "tokens_out": 200,
        "done": True,
        "stop_reason": "done",
        "extra": {
            "assumptions": [
                {"decision": "error_text", "question": "What does the 503 say?", "guessed": "x"},
                {"decision": "bogus", "question": "dropped"},
            ]
        },
    }
    base.update(kw)
    return BuildOutcome(**base)


def _worker(tmp_path: Path, **settings: Any) -> Any:
    from crb.server.worker import Worker, WorkerSettings
    from crb.store import init_db, make_engine

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{home / 'crb.db'}"
    engine = make_engine(url)
    init_db(engine)
    return Worker(
        WorkerSettings(database_url=url, home=home, worker_id="w-probe", **settings),
        engine=engine,
    )


def _ctx(*, model: str = "claude-sonnet-5", builder: str = "claude_code", reclaims: int = 0):
    from crb.store.models import Run

    run = Run(
        id="probe-run-1",
        repo="alpha",
        kind=KIND_GAP_PROBE,
        mode="blind",
        builder=builder,
        model=model,
        actor="operator:ada",
        params_json={
            "tracker": "fake",
            "key": "4711",
            "revision": "1",
            "content_revision": "c-1",
            "item_id": "fake-4711",
            "subject": "Add a POST /health route",
            "message": "a new HTTP endpoint",
            "rung": f"{builder}:{model}",
            "max_cost_usd": 1.5,
            "max_questions": 5,
        },
        counts_json={"reclaims": reclaims} if reclaims else {},
    )
    emitted: list[tuple[str, str, dict[str, Any]]] = []
    ctx = SimpleNamespace(
        run=run,
        params=dict(run.params_json),
        claim=reclaims,
        config=RepoConfig(name="alpha", language=Language.PYTHON, runner="pytest"),
        git=SimpleNamespace(rev_parse=lambda ref: "a" * 40),
        emit=lambda stage, action, **kw: emitted.append((stage, action, kw)),
    )
    return ctx, emitted


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    import crb.server.worker as w

    s = SimpleNamespace(builder=_Builder(_outcome()), ws=_Workspaces(), rung_kw=[])

    def builder_for_rung(rung: Any, **kw: Any) -> Any:
        s.rung_kw.append(kw)
        return s.builder

    monkeypatch.setattr(w, "builder_for_rung", builder_for_rung)
    monkeypatch.setattr(w, "Workspace", s.ws)
    return s


def _chain(worker: Any) -> list[Any]:
    return [e for e in FactoryHome(worker.home, "alpha").events() if e.kind in PROBE_KINDS]


def test_a_probe_run_records_its_questions_and_discards_its_worktree(
    tmp_path: Path, seams: SimpleNamespace
) -> None:
    worker = _worker(tmp_path)
    ctx, emitted = _ctx()
    status, counts, error = worker._run_gap_probe(ctx)
    assert status == "succeeded" and counts == {"gap_probe": "finished", "questions": 1}
    assert error == "" and seams.rung_kw == [{"gap_probe": True}]
    assert seams.ws.opened == seams.ws.removed and len(seams.ws.removed) == 1
    (done,) = _chain(worker)
    assert done.kind == EV_INTAKE_GAP_PROBE_FINISHED and done.item_id == "fake-4711"
    assert done.payload["questions"] == [
        {"question": "What does the 503 say?", "decision": "error_text"}
    ]
    assert done.payload["run_id"] == "probe-run-1" and done.payload["content_revision"] == "c-1"
    assert done.payload["cost_usd"] == 0.37
    ((stage, action, kw),) = emitted
    assert (stage, action, kw["cost_usd"]) == ("build", gp.GAP_PROBE_BUILD_ACTION, 0.37)


def test_a_reclaimed_probe_run_is_recorded_failed_and_never_builds(
    tmp_path: Path, seams: SimpleNamespace
) -> None:
    """Critique: a reclaimed run may already have spent; building again would spend twice."""
    worker = _worker(tmp_path)
    ctx, _ = _ctx(reclaims=1)
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": gp.FAIL_RECLAIMED}
    assert seams.builder.built == 0 and seams.ws.opened == []
    (ev,) = _chain(worker)
    assert ev.kind == EV_INTAKE_GAP_PROBE_FAILED and ev.payload["reason"] == gp.FAIL_RECLAIMED


def test_a_sealed_production_worker_refuses_a_probe_run(
    tmp_path: Path, seams: SimpleNamespace
) -> None:
    from crb.server.worker import SandboxUnavailable

    worker = _worker(tmp_path, refuse_unsealed=True)
    ctx, _ = _ctx()
    with pytest.raises(SandboxUnavailable, match="gap probe"):
        worker._run_gap_probe(ctx)
    assert seams.builder.built == 0 and _chain(worker) == []


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"model": "zzz-unknown"}, gp.FAIL_UNPRICED),
        ({"builder": "aider"}, gp.FAIL_NOT_PROBE_BUILDER),
    ],
)
def test_a_probe_on_an_unpriced_or_wrong_rung_fails_before_it_builds(
    kw: dict[str, Any], reason: str, tmp_path: Path, seams: SimpleNamespace
) -> None:
    worker = _worker(tmp_path)
    ctx, _ = _ctx(**kw)
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": reason}
    assert seams.builder.built == 0
    (ev,) = _chain(worker)
    assert ev.payload["reason"] == reason


def test_a_probe_whose_cost_is_unknown_is_failed(tmp_path: Path, seams: SimpleNamespace) -> None:
    seams.builder = _Builder(_outcome(cost_known=False))
    worker = _worker(tmp_path)
    ctx, emitted = _ctx()
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": gp.FAIL_COST_UNKNOWN}
    assert len(emitted) == 1  # what it did spend is still on the run's step event
    (ev,) = _chain(worker)
    assert ev.kind == EV_INTAKE_GAP_PROBE_FAILED and seams.ws.removed == seams.ws.opened


def test_a_probe_whose_build_raised_is_failed_and_its_worktree_discarded(
    tmp_path: Path, seams: SimpleNamespace
) -> None:
    seams.builder = _Builder(boom=True)
    worker = _worker(tmp_path)
    ctx, emitted = _ctx()
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": gp.FAIL_BUILD_ERROR}
    assert emitted == [] and seams.ws.removed == seams.ws.opened != []
    (ev,) = _chain(worker)
    assert "fell over" in ev.payload["detail"]


def test_the_probe_dispatches_through_the_worker_and_writes_no_ledger_row(
    tmp_path: Path, seams: SimpleNamespace
) -> None:
    from sqlalchemy import func, select

    from crb.store.models import Grade

    worker = _worker(tmp_path)
    assert worker._handlers[KIND_GAP_PROBE] == worker._run_gap_probe
    ctx, _ = _ctx()
    worker._run_gap_probe(ctx)
    with worker.factory() as s:
        assert s.execute(select(func.count()).select_from(Grade)).scalar_one() == 0


class _TeardownFails(_Workspaces):
    @contextmanager
    def at_ref(self, git: Any, ref: str, dest: Path, config: Any = None) -> Any:
        from crb.core.git import GitError

        self.opened.append(dest)
        yield SimpleNamespace(path=dest)
        raise GitError("git worktree remove timed out")


def test_a_probe_whose_worktree_teardown_raised_still_records_its_spend(
    tmp_path: Path, seams: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: the build step event was emitted only after the workspace closed, so a
    teardown that raised after a priced build lost the spend from the run's served cost."""
    import crb.server.worker as w

    monkeypatch.setattr(w, "Workspace", _TeardownFails())
    worker = _worker(tmp_path)
    ctx, emitted = _ctx()
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": gp.FAIL_BUILD_ERROR}
    builds = [kw for stage, action, kw in emitted if action == gp.GAP_PROBE_BUILD_ACTION]
    assert [b["cost_usd"] for b in builds] == [0.37]
    (failed,) = _chain(worker)
    assert failed.payload["cost_usd"] == 0.37


def test_the_served_cost_of_a_probe_run_is_its_build_step_events(tmp_path: Path) -> None:
    from crb.server.routes.runs import run_out
    from crb.store import init_db, make_engine, make_session_factory
    from crb.store.models import Event, Repo, Run

    engine = make_engine(f"sqlite:///{tmp_path / 'c.db'}")
    init_db(engine)
    sessions = make_session_factory(engine)
    with sessions() as s:
        s.add(Repo(name="alpha", language="python", runner="pytest", config_json={}))
        s.add(Run(id="pr1", repo="alpha", kind=KIND_GAP_PROBE, status="succeeded", actor="a"))
        s.add(Run(id="fr1", repo="alpha", kind="factory", status="succeeded", actor="a"))
        for i, (trace, action, cost) in enumerate(
            [
                ("pr1", gp.GAP_PROBE_BUILD_ACTION, 0.25),
                ("pr1", gp.GAP_PROBE_BUILD_ACTION, 0.5),
                ("pr1", "run.started", 9.0),
                ("fr1", gp.GAP_PROBE_BUILD_ACTION, 3.0),
            ]
        ):
            s.add(
                Event(
                    event_id=f"e{i}",
                    trace_id=trace,
                    seq=i,
                    timestamp="2026-11-18T00:00:00Z",
                    stage="build",
                    action=action,
                    status="ok",
                    cost_usd=cost,
                    payload_json={},
                )
            )
        s.commit()
        probe = s.get(Run, "pr1")
        other = s.get(Run, "fr1")
        assert probe is not None and other is not None
        assert run_out(s, probe).cost_usd == pytest.approx(0.75)
        assert run_out(s, other).cost_usd == 0.0


# --- review regressions -----------------------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        # the model-error path: no structured answer, no assumptions key
        {"done": False, "stop_reason": "model_error", "errors": ("model_error: x",), "extra": {}},
        # a stream that ended "done" but never carried the structured answer
        {"extra": {}},
        # the spend cap stopped it, even though a partial list came back
        {"done": False, "stop_reason": "max_cost_usd", "extra": {"assumptions": []}},
        # a refused login killed the stream after it answered
        {"errors": ("model_error: auth_refused (HTTP 401)",), "extra": {"assumptions": []}},
    ],
)
def test_a_probe_build_that_stopped_without_its_answer_is_failed_not_clean(
    kw: dict[str, Any], tmp_path: Path, seams: SimpleNamespace
) -> None:
    """Review: a probe build that failed before its structured answer was recorded as
    finished with no questions, and the poll registered the ticket on no probe at all."""
    seams.builder = _Builder(_outcome(**kw))
    worker = _worker(tmp_path)
    ctx, emitted = _ctx()
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": gp.FAIL_BUILD_ERROR}
    (ev,) = _chain(worker)
    assert ev.kind == EV_INTAKE_GAP_PROBE_FAILED and ev.payload["cost_usd"] == 0.37
    assert len(emitted) == 1 and seams.ws.removed == seams.ws.opened


def test_a_clean_build_with_an_empty_answer_still_finishes_with_no_questions(
    tmp_path: Path, seams: SimpleNamespace
) -> None:
    seams.builder = _Builder(_outcome(extra={"assumptions": []}))
    worker = _worker(tmp_path)
    ctx, _ = _ctx()
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "succeeded" and counts == {"gap_probe": "finished", "questions": 0}


@pytest.mark.parametrize(
    "assumptions",
    [
        [{"decision": "name", "question": "", "guessed": "status"}],
        [{"decision": "not-a-decision", "question": "Which name?", "guessed": "x"}],
        [{"decision": "name", "question": "one\ntwo", "guessed": "x"}],
        "not a list",
    ],
)
def test_a_probe_whose_every_reported_guess_is_unusable_is_failed_not_clean(
    assumptions: Any, tmp_path: Path, seams: SimpleNamespace
) -> None:
    """Review: a build that reported guesses, none of which could be asked, was recorded
    as finished with no questions — the same record as a build that guessed nothing."""
    seams.builder = _Builder(_outcome(extra={"assumptions": assumptions}))
    worker = _worker(tmp_path)
    ctx, _ = _ctx()
    status, counts, _ = worker._run_gap_probe(ctx)
    assert status == "failed" and counts == {"gap_probe": gp.FAIL_BUILD_ERROR}
    (ev,) = _chain(worker)
    assert ev.kind == EV_INTAKE_GAP_PROBE_FAILED and ev.payload["cost_usd"] == 0.37


class _LateQueue(Queue):
    """A probe run that finishes DURING a poll pass: the first time its status is asked,
    the worker writes its result to the chain and then ends the run, as the worker does."""

    def __init__(self, home: FactoryHome, questions: list[dict[str, str]]) -> None:
        super().__init__()
        self.home, self.questions, self.armed = home, questions, False

    def run_status(self, run_id: str) -> str | None:
        if self.armed:
            self.armed = False
            _finish(self.home, self, self.questions)
        return super().run_status(run_id)


def test_a_probe_that_finishes_during_a_poll_pass_is_never_recorded_failed(
    home: FactoryHome,
) -> None:
    """Review: the pass read the chain at its start but the run's status live, so a probe
    that finished mid-pass was recorded failed beside its own result and the row told the
    person to edit the ticket."""
    queue = _LateQueue(home, [])
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    queue.armed = True
    report = _poll(home, tracker, gap_probe=queue.probe())
    assert EV_INTAKE_GAP_PROBE_FAILED not in _kinds(home)
    assert report.registered == 1 and len(queue.requests) == 1
    (row,) = report.rows
    assert row.stopped != sv.REASON_GAP_PROBE_FAILED


class _StillRunningQueue(_LateQueue):
    """The result lands during the pass while the run is still ``running``: the pass judges
    the probe pending and writes its read AFTER the result."""

    def run_status(self, run_id: str) -> str | None:
        if self.armed:
            self.armed = False
            _finish(self.home, self, self.questions)
            self.status[run_id] = "running"
        return Queue.run_status(self, run_id)


def test_a_read_that_judged_the_probe_pending_does_not_act_on_its_result(
    home: FactoryHome,
) -> None:
    """Review: a read written after a mid-pass result counted as acting on it, so the next
    pass at the same revision served the cached pending row and never registered."""
    queue = _StillRunningQueue(home, [])
    tracker = _tracker(_ticket())
    _poll(home, tracker, gap_probe=queue.probe())
    queue.armed = True
    (row,) = _poll(home, tracker, gap_probe=queue.probe()).rows
    assert row.stopped == sv.REASON_GAP_PROBE_PENDING
    read = [e for e in home.events() if e.kind == sv.EV_READ][-1]
    assert read.payload["gap_probe_state"] == gp.STATE_PENDING
    assert not sv.already_handled(
        list(home.events()), "fake", "4711", read.payload["revision"], probing=True
    )
    report = _poll(home, tracker, gap_probe=queue.probe())
    assert report.registered == 1 and len(queue.requests) == 1


def test_a_register_act_racing_a_finishing_probe_is_not_refused_as_failed(
    home: FactoryHome,
) -> None:
    queue = _LateQueue(home, ASKED)
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    _poll(home, tracker, gap_probe=queue.probe(), approval=sv.ApprovalPolicy())
    _register(home, tracker, queue)
    queue.armed = True
    with pytest.raises(sv.ApprovalRefused) as err:
        _register(home, tracker, queue)
    assert err.value.code == "gap_probe_questions"
    assert EV_INTAKE_GAP_PROBE_FAILED not in _kinds(home)


def test_a_queued_probe_whose_request_cannot_be_recorded_is_cancelled(
    home: FactoryHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: the run was queued before its request was recorded, so a failed chain write
    left a paid probe running that no pass could see, and the next pass queued a second."""
    from crb.factory.evidence import FactoryEvidence

    real = FactoryEvidence.append

    def append(self: Any, kind: str, item_id: str = "", **payload: Any) -> Any:
        if kind == EV_INTAKE_GAP_PROBE_REQUESTED:
            raise OSError("disk full")
        return real(self, kind, item_id, **payload)

    queue = Queue()
    tracker = _tracker(_ticket())
    with monkeypatch.context() as m:
        m.setattr(FactoryEvidence, "append", append)
        report = _poll(home, tracker, gap_probe=queue.probe())
    (row,) = report.rows
    assert row.stopped == sv.REASON_REFUSED and not row.registered
    assert queue.cancelled == ["probe-1"] and not _probe_events(home)
    # a refusal is final at its revision; the operator's forced re-post asks again, and
    # only one probe is ever left to run
    _poll(home, tracker, gap_probe=queue.probe())
    assert len(queue.requests) == 1
    _poll(home, tracker, gap_probe=queue.probe(), force=True)
    assert len(queue.requests) == 2 and queue.cancelled == ["probe-1"]
    assert queue.status == {"probe-1": "cancelled", "probe-2": "queued"}


def test_a_register_act_whose_request_cannot_be_recorded_cancels_its_run(
    home: FactoryHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.factory.evidence import FactoryEvidence

    real = FactoryEvidence.append

    def append(self: Any, kind: str, item_id: str = "", **payload: Any) -> Any:
        if kind == EV_INTAKE_GAP_PROBE_REQUESTED:
            raise OSError("disk full")
        return real(self, kind, item_id, **payload)

    queue = Queue()
    tracker = _tracker(_ticket(author="mallory@example.invalid"))
    _poll(home, tracker, gap_probe=queue.probe(), approval=sv.ApprovalPolicy())
    monkeypatch.setattr(FactoryEvidence, "append", append)
    with pytest.raises(sv.ApprovalRefused) as err:
        _register(home, tracker, queue)
    assert err.value.code == "register_refused" and queue.cancelled == ["probe-1"]


def _interrupt_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from crb.factory.evidence import FactoryEvidence

    real = FactoryEvidence.append

    def append(self: Any, kind: str, item_id: str = "", **payload: Any) -> Any:
        if kind == EV_INTAKE_GAP_PROBE_REQUESTED:
            raise KeyboardInterrupt
        return real(self, kind, item_id, **payload)

    monkeypatch.setattr(FactoryEvidence, "append", append)


def test_an_interrupt_between_queue_and_request_still_cancels_the_run(
    home: FactoryHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: the cancel guard caught only ``Exception``, so an interrupt between the two
    writes left a paid run that no request names."""
    queue = Queue()
    with monkeypatch.context() as m:
        _interrupt_the_request(m)
        with pytest.raises(KeyboardInterrupt):
            _poll(home, _tracker(_ticket()), gap_probe=queue.probe())
    assert queue.cancelled == ["probe-1"]


def test_a_run_whose_request_died_with_the_process_is_reused_not_queued_again(
    home: FactoryHome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: a process that died after queueing the probe and before recording its
    request (nothing cancels then) left the next pass to queue a second paid probe."""
    import dataclasses

    from crb.store.models import Run

    monkeypatch.setattr(sv, "submit_refusals", lambda *a, **k: None)
    sessions = _queue_with_repo(tmp_path)
    probe = sv.gap_probe_for(_deployment(**_ON), sessions, "alpha")
    assert probe is not None
    tracker = _tracker(_ticket())
    with monkeypatch.context() as m:
        _interrupt_the_request(m)
        with pytest.raises(KeyboardInterrupt):
            _poll(home, tracker, gap_probe=dataclasses.replace(probe, cancel=None))
    _poll(home, tracker, gap_probe=probe)
    with sessions() as s:
        runs = s.query(Run).filter(Run.kind == KIND_GAP_PROBE).all()
        assert len(runs) == 1
        (request,) = [e for e in home.events() if e.kind == EV_INTAKE_GAP_PROBE_REQUESTED]
        assert request.payload["run_id"] == runs[0].id


def test_a_run_that_ended_before_its_request_was_recorded_is_named_not_queued_again(
    home: FactoryHome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: only a run still queued or running was reused, so an orphan a worker had
    already finished before the next pass left that pass to queue a second paid probe."""
    import dataclasses

    from crb.store.models import Run

    monkeypatch.setattr(sv, "submit_refusals", lambda *a, **k: None)
    sessions = _queue_with_repo(tmp_path)
    probe = sv.gap_probe_for(_deployment(**_ON), sessions, "alpha")
    assert probe is not None
    tracker = _tracker(_ticket())
    with monkeypatch.context() as m:
        _interrupt_the_request(m)
        with pytest.raises(KeyboardInterrupt):
            _poll(home, tracker, gap_probe=dataclasses.replace(probe, cancel=None))
    with sessions() as s:
        (orphan,) = s.query(Run).filter(Run.kind == KIND_GAP_PROBE).all()
        orphan.status, orphan.started, orphan.finished = "succeeded", "t1", "t2"
        s.commit()
    report = _poll(home, tracker, gap_probe=probe)
    with sessions() as s:
        runs = s.query(Run).filter(Run.kind == KIND_GAP_PROBE).all()
        assert len(runs) == 1
        (request,) = [e for e in home.events() if e.kind == EV_INTAKE_GAP_PROBE_REQUESTED]
        assert request.payload["run_id"] == runs[0].id
    # the request names a run with no result after it: fails closed, nothing registered
    assert report.registered == 0
    (row,) = _poll(home, tracker, gap_probe=probe).rows
    assert row.stopped == sv.REASON_GAP_PROBE_FAILED and home.load_backlog() is None


def test_the_timed_polls_probe_meets_the_whole_submit_gate_and_is_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: the timed poll handed ``WorkerSettings`` to the probe, and the submit gate's
    login check reads ``settings.builder``, which it lacks: every probe that cleared the free
    refusals raised ``AttributeError`` and none was ever queued."""
    import crb.server.worker as w
    from crb.server.routes import runs as runs_route
    from crb.store.jobs import JobQueue
    from crb.store.models import Repo

    worker = _worker(tmp_path, intake=_settings(**_ON))
    with worker.factory() as s:
        s.add(Repo(name="alpha", language="python", runner="pytest", config_json={}))
        s.commit()
    seen: dict[str, Any] = {}
    monkeypatch.setattr(w, "poll_repository", lambda repo, **kw: seen.update(kw))
    monkeypatch.setattr(runs_route, "credential_refusal", lambda run, settings: None)
    logins: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_route, "login_refusal", lambda *a, **k: logins.append(k))
    worker._poll_one("alpha", object(), sv.ListenerState(enabled=True))
    probe = seen["gap_probe"]
    assert probe is not None
    run_id = probe.enqueue({"key": "4711", "approved_by": "operator:ada"})
    run = JobQueue(worker.factory).get(run_id)
    assert run is not None and run.kind == KIND_GAP_PROBE
    assert logins and logins[0]["ttl_s"] == worker.settings.builder_login_ttl_s


def test_the_deployed_probe_cancels_a_queued_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.store.jobs import JobQueue

    monkeypatch.setattr(sv, "submit_refusals", lambda *a, **k: None)
    sessions = _queue_with_repo(tmp_path)
    probe = sv.gap_probe_for(_deployment(**_ON), sessions, "alpha")
    assert probe is not None and probe.cancel is not None
    run_id = probe.enqueue({"key": "4711", "approved_by": "operator:ada"})
    probe.cancel(run_id)
    run = JobQueue(sessions).get(run_id)
    assert run is not None and run.status == "cancelled"
