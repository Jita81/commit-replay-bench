"""A run's spend cap (F5b): ``max_cost_usd`` summed over the run's attempts, kept by the run.

Before this, a ``Budget`` capped one attempt only: a run of thirty attempts had no ceiling,
and the Measure and Factory pages could only state an estimate. The worker now asks before
every attempt (a factory run, before every item) whether the next one could take the run's
spend past its cap, and stops the run there — ``failed``, ``stopped_code: spend_cap``, a
``run.spend_cap`` event naming what was spent, the cap and the reserve it could not fit. No
docker, no network, no model: the fake builder costs a fixed amount per attempt.

Navigation
----------
What it is:   The worker suite for the per-run spend cap and the pure rules behind it.
What it does: Pins that a replay stops before the attempt whose own cost cap would pass the
              run's cap, with the reason, the code and the event, and never spends past it;
              that a run whose last attempt or item, with no cost cap of its own, passed the
              cap ends ``failed`` saying so (a guard, not a guarantee); that a factory run's
              test author's calls count as its spend, a reclaim included, and an author
              whose cost is not known stops a capped run; that every module that opens a
              model chat is one the cap can see;
              that an attempt with no cost cap of its own is reserved at the dearest attempt
              the run has made; that an attempt whose cost was not known halts the run (the
              cap cannot be kept blind); that a run with no cap climbs every rung; that a
              factory run stops before an item whose attempts could pass the cap; and that the
              priced-model check refuses an unpriced rung and admits the fixture builder.
How:          ``test_worker``'s harness with a fixed-cost fake builder; ``crb.server.spend_cap``
              called directly for the rules.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/spend_cap.py (the rules), src/crb/server/worker.py (where the
              run asks), src/crb/core/run.py (``RunSpec.admit``),
              tests/test_server_spend_cap.py (the API's half)
Tested by:    tests/test_worker_spend_cap.py
Touch when:   never for a new repository; what counts as spend changes, or the factory's reserve for
              an item changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders.base import STOP_MAX_TURNS, Budget, BuildBrief, BuildOutcome
from crb.core.workspace import Workspace
from crb.server import spend_cap as sc
from crb.store.jobs import STATUS_FAILED, STATUS_SUCCEEDED
from fixtures import pyrepo as pr
from fixtures.proven_cells import every_cell_proven
from test_worker import FakeBuilder, Harness, _multiply_backlog


@pytest.fixture(autouse=True)
def _proven(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory runs here BUILD, so every cell has a proven, signed standard (ADR-0026
    item 8): ``S2`` for the operator-authored item; the test author's own ``S1`` arm where
    a test author writes the oracle (:func:`_paid_author`)."""
    every_cell_proven(monkeypatch, "S2")


class PricedNoop:
    """Does nothing (the target stays red, so a task climbs) at a fixed cost per attempt."""

    name = "fake"
    cost = 0.4
    known = True

    def __init__(self, *, model: str, provider: str = "", **_: Any) -> None:
        self.model = model
        self.provider = provider

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self, workspace: Workspace, brief: BuildBrief, budget: Budget, **_: Any
    ) -> BuildOutcome:
        del workspace
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=False,
            stop_reason=STOP_MAX_TURNS,
            turns=1,
            tokens_in=100,
            tokens_out=10,
            cost_usd=PricedNoop.cost,
            cost_known=PricedNoop.known,
            budget=budget,
        )


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", PricedNoop)
    PricedNoop.cost, PricedNoop.known = 0.4, True
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


LADDER = ["fake:m0", "fake:m1", "fake:m2"]


def _stopped(h: Harness, run_id: str) -> list[Any]:
    return [e for e in h.events(run_id) if e.action == "run.spend_cap"]


def test_a_replay_stops_before_the_attempt_whose_own_cap_would_pass_the_runs(h: Harness) -> None:
    """Each attempt may cost up to $0.40 (its own cap); the run's cap is $1.00. Two attempts
    fit ($0.80), a third could reach $1.20, so the run stops before it — with the reason, the
    code and an event — and has spent no more than its cap."""
    run = h.enqueue(
        "replay",
        ladder_json=LADDER,
        params_json={"max_cost_usd": 1.0, "budget": {"max_cost_usd": 0.4}},
    )
    done = h.run_one()
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert [r.trial for r in rows] == ["r1", "r2"]
    assert sum(r.cost_usd for r in rows) <= 1.0
    assert done.status == STATUS_FAILED
    assert done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert done.error == done.counts_json["stopped_reason"]
    assert done.error.startswith("spend cap: $0.80 of $1.00 spent")
    assert "its own cost cap of $0.40" in done.error
    (event,) = _stopped(h, run.id)
    assert event.payload["cap_usd"] == 1.0 and event.payload["spent_usd"] == pytest.approx(0.8)
    assert event.payload["reserve_usd"] == 0.4 and event.payload["reserve_from"] == "attempt_cap"


def test_an_attempt_with_no_cost_cap_is_reserved_at_the_dearest_attempt_so_far(
    h: Harness,
) -> None:
    run = h.enqueue("replay", ladder_json=LADDER, params_json={"max_cost_usd": 1.0})
    done = h.run_one()
    assert [r.trial for r in h.worker.ledger.rows(run_id=run.id)] == ["r1", "r2"]
    assert done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert "the dearest attempt this run has made, $0.40" in done.error
    (event,) = _stopped(h, run.id)
    assert event.payload["reserve_from"] == "dearest_attempt"


def test_an_attempt_whose_cost_was_not_known_halts_a_capped_run(h: Harness) -> None:
    """A cap that cannot see an attempt's cost cannot be kept: the run stops at once."""
    PricedNoop.known = False
    run = h.enqueue("replay", ladder_json=LADDER, params_json={"max_cost_usd": 100.0})
    done = h.run_one()
    assert len(list(h.worker.ledger.rows(run_id=run.id))) == 1
    assert done.status == STATUS_FAILED and done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert "cost was not known" in done.error


def test_a_run_without_a_cap_climbs_every_rung(h: Harness) -> None:
    run = h.enqueue("replay", ladder_json=LADDER)
    done = h.run_one()
    assert [r.trial for r in h.worker.ledger.rows(run_id=run.id)] == ["r1", "r2", "r3"]
    assert done.status == STATUS_SUCCEEDED and "stopped_code" not in done.counts_json
    assert _stopped(h, run.id) == []


@pytest.mark.parametrize("cap", [0.4, 0.79, 0.8, 1.19, 1.2, 5.0])
def test_a_run_whose_attempts_are_capped_never_spends_past_its_cap(h: Harness, cap: float) -> None:
    run = h.enqueue(
        "replay",
        ladder_json=LADDER,
        params_json={"max_cost_usd": cap, "budget": {"max_cost_usd": 0.4}},
    )
    h.run_one()
    rows = list(h.worker.ledger.rows(run_id=run.id))
    expected = 0  # attempts admitted: each while what is spent plus $0.40 fits the cap
    while expected < len(LADDER) and 0.4 * (expected + 1) <= cap + 1e-9:
        expected += 1
    assert len(rows) == expected
    assert sum(r.cost_usd for r in rows) <= cap + 1e-9


def test_a_factory_run_stops_before_an_item_whose_attempts_could_pass_the_cap(
    h: Harness,
) -> None:
    """An item may take every rung, once and again for each rework: one rung, one rework
    and a $0.02 attempt cap reserve $0.04 for it. Under a $0.03 cap nothing is built; under
    $0.05 the item is built."""
    _multiply_backlog(h)
    run = h.enqueue(
        "factory",
        ladder_json=["fake:m0"],
        params_json={"max_cost_usd": 0.03, "budget": {"max_cost_usd": 0.02}},
    )
    done = h.run_one()
    assert list(h.worker.ledger.rows(run_id=run.id)) == []
    assert done.status == STATUS_FAILED and done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert "the next item could cost up to $0.04" in done.error
    assert _stopped(h, run.id)[0].payload["reserve_usd"] == pytest.approx(0.04)
    ok = h.enqueue(
        "factory",
        ladder_json=["fake:m0"],
        params_json={"max_cost_usd": 0.05, "budget": {"max_cost_usd": 0.02}},
    )
    built = h.run_one()
    assert built.status == STATUS_SUCCEEDED, built.error
    assert len(list(h.worker.ledger.rows(run_id=ok.id))) == 1


@pytest.mark.parametrize("ladder", [["fake:m0"], LADDER], ids=["one_rung", "three_rungs"])
def test_a_capped_run_of_attempts_with_no_cost_cap_is_a_guard_and_ends_failed_past_it(
    h: Harness, ladder: list[str]
) -> None:
    """The pages send a run cap and no cost cap per attempt, so an attempt is counted at the
    dearest attempt so far — nothing at first. A run capped at $0.10 whose first attempt,
    with no cost cap of its own, costs $5.00 has passed its cap by then: a guard, not a
    guarantee. It makes no further attempt, and whether or not one was left to make it
    ends ``failed`` with ``stopped_code: spend_cap``, the amount and the event — never
    ``succeeded`` in silence."""
    PricedNoop.cost = 5.0
    run = h.enqueue("replay", ladder_json=ladder, params_json={"max_cost_usd": 0.10})
    done = h.run_one()
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert [r.cost_usd for r in rows] == [5.0]
    assert done.status == STATUS_FAILED
    assert done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert done.error.startswith("spend cap: $5.00 of $0.10 spent")
    (event,) = _stopped(h, run.id)
    assert event.payload["cap_usd"] == 0.10 and event.payload["spent_usd"] == 5.0


def test_a_factory_run_whose_one_item_passed_its_cap_ends_failed_and_says_so(h: Harness) -> None:
    """The first item is reserved at the dearest attempt so far, nothing, so it is built;
    its $0.02 attempt passes a $0.01 cap, and the run says so rather than succeeding."""
    _multiply_backlog(h)
    run = h.enqueue("factory", ladder_json=["fake:m0"], params_json={"max_cost_usd": 0.01})
    done = h.run_one()
    assert [r.cost_usd for r in h.worker.ledger.rows(run_id=run.id)] == [0.02]
    assert done.status == STATUS_FAILED and done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert done.error.startswith("spend cap: $0.02 of $0.01 spent")
    assert "passed the cap" in done.error
    (event,) = _stopped(h, run.id)
    assert event.payload["reserve_from"] == "passed"


def _authorless_backlog(h: Harness, n: int) -> None:
    """``n`` items with no operator-authored test, so each one asks the test author."""
    from crb.factory.backlog import KIND_CODE, BacklogItem
    from crb.server.factory_state import FactoryHome

    items = [
        BacklogItem(
            id=f"I-{i}",
            title=f"Add multiply {i} to calc",
            kind=KIND_CODE,
            description="calc needs multiply(a, b).",
            acceptance_criteria=("multiply(3, 4) == 12",),
            capability_class="bug.fix",
            size_estimate="XS",
            structural_facts=(
                "reproduction: `from calc import multiply` raises ImportError",
                "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
                "exact_value: multiply(3, 4) == 12",
            ),
        )
        for i in range(1, n + 1)
    ]
    FactoryHome(h.home, pr.REPO_NAME).register_backlog(items, actor="tester")
    builders_pkg._REGISTRY["fake"] = lambda **cfg: FakeBuilder(behaviour="multiply", **cfg)


def _paid_author(monkeypatch: pytest.MonkeyPatch, reply: Any) -> None:
    """The run's test author: a priced model whose every reply is ``reply`` (unusable, so
    each item's authoring spends its attempts and stops the item)."""
    from crb.factory.author import RungTestAuthor
    from crb.server import worker as w

    def author(self: Any, ctx: Any, ladder: Any) -> RungTestAuthor:
        del self, ctx, ladder
        return RungTestAuthor(
            name="editblock", model="gpt-oss-120b", chat_fn=lambda _m: reply, attempts=2
        )

    monkeypatch.setattr(w.Worker, "_test_author", author)
    from crb.factory.testfirst import canonical_model

    every_cell_proven(monkeypatch, f"S1@{canonical_model('gpt-oss-120b')}")


def test_a_factory_runs_test_author_spends_against_the_cap(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test author makes model calls of its own. Each call's cost is on its
    ``author.attempt`` event and counted as the run's spend, so a capped run stops before
    the next item once authoring alone has spent the cap — and the next item's reserve
    counts one authoring pass."""
    from crb.builders.openai_client import ChatReply

    _authorless_backlog(h, 2)
    _paid_author(monkeypatch, ChatReply("no file line", cost_usd=0.03))
    run = h.enqueue("factory", ladder_json=["fake:m0"], params_json={"max_cost_usd": 0.05})
    done = h.run_one()
    attempts = [e for e in h.events(run.id) if e.action == "author.attempt"]
    assert [e.cost_usd for e in attempts] == [0.03, 0.03]
    assert all(e.payload["cost_known"] is True for e in attempts)
    assert done.status == STATUS_FAILED and done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert done.error.startswith("spend cap: $0.06 of $0.05 spent")


def test_a_reclaimed_factory_run_counts_the_authoring_its_first_claim_spent(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The author's calls of a first claim are on the run's events, not on the author the
    second claim builds: they are read back, so a reclaim cannot forget them."""
    from crb.builders.openai_client import ChatReply
    from crb.store.events import append_event

    _authorless_backlog(h, 1)
    _paid_author(monkeypatch, ChatReply("no file line", cost_usd=0.01))
    run = h.enqueue("factory", ladder_json=["fake:m0"], params_json={"max_cost_usd": 0.05})
    append_event(
        h.factory,
        trace_id=run.id,
        stage="factory",
        action="author.attempt",
        payload={"cost_usd": 0.06, "cost_known": True},
    )
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert done.error.startswith("spend cap: $0.06 of $0.05 spent; the next item")
    assert [e for e in h.events(run.id) if e.action == "author.start"] == []


def test_a_test_author_whose_cost_is_not_known_stops_a_capped_factory_run(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reply that carries no usage is a call the cap cannot see: the run stops."""
    _authorless_backlog(h, 2)
    _paid_author(monkeypatch, "no file line")
    run = h.enqueue("factory", ladder_json=["fake:m0"], params_json={"max_cost_usd": 5.0})
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.counts_json["stopped_code"] == sc.STOP_SPEND_CAP
    assert "cost was not known" in done.error
    (attempt, *_) = [e for e in h.events(run.id) if e.action == "author.attempt"]
    assert attempt.payload["cost_known"] is False


# --- the rules ---------------------------------------------------------------------------


def test_the_admission_rule_counts_the_reserve_against_what_is_left() -> None:
    cap = sc.SpendCap(1.0)
    assert cap.admit(sc.Spend(0.0, 0.0), reserve=1.0, unit="attempt") == ""
    assert cap.admit(sc.Spend(0.6, 0.6), reserve=0.4, unit="attempt") == ""
    refused = cap.admit(sc.Spend(0.61, 0.61), reserve=0.4, unit="attempt")
    assert refused.startswith("spend cap: $0.61 of $1.00 spent; the next attempt could cost")
    # no cap of its own: the dearest attempt so far is the reserve (nothing before the first)
    assert cap.admit(sc.Spend(0.0, 0.0), reserve=0.0, unit="attempt") == ""
    assert "dearest attempt" in cap.admit(sc.Spend(0.7, 0.35), reserve=0.0, unit="attempt")
    assert "cost was not known" in cap.admit(
        sc.Spend(0.1, 0.1, unknown=1), reserve=0.1, unit="attempt"
    )
    assert sc.SpendCap.from_params({}) is None
    # a run that has already passed its cap, by an attempt no cap of its own bounded
    assert cap.passed(sc.Spend(0.99, 0.5)) is None
    over = cap.passed(sc.Spend(1.5, 1.5))
    assert over is not None and over.payload["reserve_from"] == "passed"
    assert over.reason.startswith("spend cap: $1.50 of $1.00 spent")
    # authoring spend: every author.attempt event's cost, and one it could not see
    events = [
        {"action": "author.attempt", "cost_usd": 0.25, "cost_known": True},
        {"action": "author.attempt", "cost_usd": 0.0, "cost_known": False},
        {"action": "author.start"},
    ]
    authored = sc.Spend(0.5, 0.5).with_authoring(events)
    assert authored.spent == 0.75 and authored.unknown == 1 and authored.dearest == 0.5
    assert authored.dearest_authoring == 0.25
    # an item's reserve counts one authoring pass at the dearest authoring call so far
    assert sc.item_reserve([0.1], authored, max_rework=0, author_attempts=2) == (0.6, 1)
    assert sc.SpendCap.from_params({"max_cost_usd": 2}) == sc.SpendCap(2.0)


def test_a_rung_is_priced_when_its_model_has_a_known_price_or_it_is_the_fixture() -> None:
    table = {"known-model": builders_pkg.Pricing(1.0, 2.0)}
    assert sc.unpriced_rungs([("openai_agent", "known-model")], table) == []
    assert sc.unpriced_rungs([("openai_agent", "known-model-v2")], table) == []  # prefix
    assert sc.unpriced_rungs([("openai_agent", "mystery")], table) == [("openai_agent", "mystery")]
    assert sc.unpriced_rungs([("fixture_gold", "fixture-gold")], table) == []


#: Every module that opens a model chat (``make_chat``), and how that call's cost reaches a
#: run's spend cap. A call site added without a way in is spend the cap cannot see (P-252).
METERED = {
    "src/crb/builders/editblock.py": "a build attempt: BuildOutcome.cost_usd on its row",
    "src/crb/builders/openai_agent.py": "a build attempt: BuildOutcome.cost_usd on its row",
    "src/crb/factory/author.py": "the test author: each call's cost on its author.attempt event",
    "src/crb/builders/labeller.py": "label runs only, a kind that takes no spend cap",
}


def test_every_model_call_site_is_one_the_spend_cap_can_see() -> None:
    root = Path(__file__).resolve().parent.parent
    found = {
        p.relative_to(root).as_posix()
        for p in (root / "src" / "crb").rglob("*.py")
        if "make_chat(" in (text := p.read_text(encoding="utf-8")) and "def make_chat(" not in text
    }
    assert found == set(METERED), (
        "a module opens a model chat the spend cap was not told about — count its cost in "
        "crb.server.spend_cap.Spend (or refuse a cap on its run kind) and add it to METERED: "
        f"{sorted(found ^ set(METERED))}"
    )
    from crb.server.schemas import BUILD_KINDS

    assert "label" not in BUILD_KINDS  # the labeller's runs cannot declare a cap
