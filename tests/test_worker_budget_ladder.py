"""The budget ladder (Wave C8): a ladder entry may be an OBJECT rung
``{builder, model, provider?, budget?}``; its budget overrides the run's ``params.budget``,
which overrides the builder's defaults (rung > run > default, per field); every ledger row
is stamped ``labels.budget_tier`` (``<max_tool_calls>/<max_turns>/<wall_clock_s>``) and
``labels.rung_index`` so a blind sweep can be split by tier after the fact. Read with
the NHS review (§3): 6 of 8 blind misses were ``budget`` — before any blind claim, the
budget has to be a measured variable. No docker, no network, no model.

Navigation
----------
What it is:   The budget ladder's test suite (Wave C8) — object rungs, precedence and the
              ``labels.budget_tier`` / ``labels.rung_index`` stamps.
What it does: Pins the tier string (``<max_tool_calls>/<max_turns>/<wall_clock_s>`` plus any
              extra cap), that trial labels are positional and use the effective budget, that
              ``rung_from_object`` keeps only budget fields in the config, that object rungs mix
              with labels, that the precedence is rung > run > default per field, that a ladder
              of object rungs needs no run builder, that a bad rung budget fails the run closed
              before any task (end to end too), that a 25 → 50 → 100 sweep stamps tier and index
              on every row, that a plain ladder is stamped with the run budget, and that the stamp
              can never change a verdict. Read with the NHS review (§3): six of eight blind misses
              were ``budget``.
How:          ``test_worker``'s harness with the fake builder re-registered per test;
              ``RunContext`` built directly for the ladder-only cases.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/server/worker.py (under test), src/crb/builders/budget.py
              (``budget_for_rung``), src/crb/builders/base.py (``Budget`` / ``Rung``),
              tests/test_server_routes_runs.py (the API's half of the ladder), tests/test_worker.py
              (the harness)
Tested by:    tests/test_worker_budget_ladder.py
Touch when:   a budget cap is added (the tier string and the precedence case); the rung shape
              accepted by ``POST /runs`` changes (mirror the route suite).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import crb.builders as builders_pkg
from crb.builders.base import Budget, EscalationLadder, Rung
from crb.builders.budget import budget_for_rung
from crb.core.ledger import GradeRow, verify_chain
from crb.server.worker import (
    LABEL_BUDGET_TIER,
    LABEL_RUNG_INDEX,
    RunContext,
    budget_tier,
    rung_from_object,
    trial_labels_for,
)
from crb.store.jobs import STATUS_FAILED, STATUS_SUCCEEDED
from crb.store.models import Run
from fixtures import pyrepo as pr
from fixtures.posture import posture_row
from test_worker import FakeBuilder, Harness

SONNET = {"builder": "fake", "model": "sonnet"}


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    """``test_worker``'s autouse registration is module-local; restore ``fake`` per test."""
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    """The worker harness with the repo registered and its one mined task on file."""
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


def ctx_for(h: Harness, **fields: Any) -> RunContext:
    """A :class:`RunContext` for ``_ladder`` alone — it reads the run only (emitter, config
    and git are never touched by ladder parsing), so the rest is left unset."""
    base: dict[str, Any] = {"repo": pr.REPO_NAME, "kind": "blind", "actor": "tester"}
    base.update(fields)
    return RunContext(
        run=Run(**base), emitter=cast(Any, None), config=cast(Any, None), git=cast(Any, None)
    )


def tiers(rows: list[GradeRow]) -> list[tuple[str, str, str]]:
    """``(trial, rung_index, budget_tier)`` per row — what a blind sweep is
    split by after the fact.
    """
    return [(r.trial, r.labels[LABEL_RUNG_INDEX], r.labels[LABEL_BUDGET_TIER]) for r in rows]


# --- the tier label -------------------------------------------------------------------------


def test_budget_tier_is_tool_calls_turns_wall_clock_and_names_extra_caps() -> None:
    """``<max_tool_calls>/<max_turns>/<wall_clock_s>``; a token or dollar cap is appended
    because attempts that differ only there were not the same experiment."""
    assert budget_tier(Budget()) == "25/25/900"
    assert budget_tier(Budget(max_tool_calls=100, max_turns=40, wall_clock_s=1800)) == "100/40/1800"
    assert budget_tier(Budget(max_tokens=200_000)) == "25/25/900/tok=200000"
    assert budget_tier(Budget(max_cost_usd=0.5)) == "25/25/900/usd=0.5"
    assert budget_tier(Budget(max_tokens=10, max_cost_usd=2)) == "25/25/900/tok=10/usd=2"


def test_trial_labels_are_positional_and_use_the_effective_budget() -> None:
    """Trial ``r<i+1>`` is rung ``i``; the tier is :func:`budget_for_rung` over the run's
    base — the SAME call the build adapter makes, so label and cap cannot disagree."""
    base = Budget(max_tool_calls=40)  # the run's budget
    ladder = EscalationLadder(
        (
            Rung("fake", "m"),  # inherits the run's 40
            Rung("fake", "m", config={"max_tool_calls": 50}),
            Rung("fake", "m", config={"max_tool_calls": 100, "wall_clock_s": 1800}),
        )
    )
    labels = trial_labels_for(ladder, base)
    assert labels == {
        "r1": {LABEL_RUNG_INDEX: "0", LABEL_BUDGET_TIER: "40/25/900"},
        "r2": {LABEL_RUNG_INDEX: "1", LABEL_BUDGET_TIER: "50/25/900"},
        "r3": {LABEL_RUNG_INDEX: "2", LABEL_BUDGET_TIER: "100/25/1800"},
    }
    for i, rung in enumerate(ladder):
        assert labels[f"r{i + 1}"][LABEL_BUDGET_TIER] == budget_tier(budget_for_rung(rung, base))


# --- object rungs -----------------------------------------------------------------------------


def test_rung_from_object_keeps_only_budget_fields_in_config() -> None:
    rung = rung_from_object(
        {"builder": "fake", "model": "m", "provider": "p", "budget": {"max_tool_calls": 50}}
    )
    assert rung == Rung("fake", "m", "p", config={"max_tool_calls": 50})
    assert rung_from_object({"builder": "fake", "model": "m"}, default_provider="cerebras") == Rung(
        "fake", "m", "cerebras"
    )
    assert rung_from_object({"builder": "fake", "model": "m", "provider": "own"}).provider == "own"
    with pytest.raises(ValueError, match="unknown field"):
        rung_from_object({"builder": "fake", "model": "m", "api_key": "sk-x"})
    with pytest.raises(ValueError, match="unknown field"):
        rung_from_object({"builder": "fake", "model": "m", "budget": {"max_cost": 1}})
    with pytest.raises(ValueError, match="builder name and a model"):
        rung_from_object({"builder": "fake"})


def test_ladder_parses_object_rungs_mixed_with_labels(h: Harness) -> None:
    """Strings and objects mix in one ladder: a bare label is the run's own rung, an
    explicit label a rung as written, an object rung carries its budget in ``config``."""
    ctx = ctx_for(
        h,
        builder="fake",
        model="own",
        provider="p",
        ladder_json=[
            "r1",
            {**SONNET, "budget": {"max_tool_calls": 50}},
            "fake:strong@q",
            {**SONNET, "provider": "z", "budget": {"max_tool_calls": 100, "max_turns": 60}},
        ],
        params_json={"budget": {"max_tool_calls": 30}},
    )
    ladder = h.worker._ladder(ctx)
    assert [r.to_dict() for r in ladder] == [
        {"builder": "fake", "model": "own", "provider": "p", "config": {}},
        {"builder": "fake", "model": "sonnet", "provider": "p", "config": {"max_tool_calls": 50}},
        {"builder": "fake", "model": "strong", "provider": "q", "config": {}},
        {
            "builder": "fake",
            "model": "sonnet",
            "provider": "z",
            "config": {"max_tool_calls": 100, "max_turns": 60},
        },
    ]


def test_ladder_precedence_rung_over_run_over_default(h: Harness) -> None:
    """Per field: the rung's budget > ``params.budget`` > ``Budget()`` defaults."""
    ctx = ctx_for(
        h,
        ladder_json=[
            SONNET,  # no rung budget → the run's
            {**SONNET, "budget": {"max_tool_calls": 100}},  # one field → the rest from the run
            {**SONNET, "budget": {"max_tool_calls": 200, "max_turns": 80, "wall_clock_s": 60}},
        ],
        params_json={"budget": {"max_tool_calls": 50, "wall_clock_s": 1200}},
    )
    ladder = h.worker._ladder(ctx)
    base = h.worker._budget(ctx)
    assert base == Budget(max_tool_calls=50, wall_clock_s=1200)  # run over default
    effective = [budget_for_rung(r, base) for r in ladder]
    assert effective == [
        Budget(max_tool_calls=50, max_turns=25, wall_clock_s=1200),
        Budget(max_tool_calls=100, max_turns=25, wall_clock_s=1200),
        Budget(max_tool_calls=200, max_turns=80, wall_clock_s=60),
    ]
    assert [x[LABEL_BUDGET_TIER] for x in trial_labels_for(ladder, base).values()] == [
        "50/25/1200",
        "100/25/1200",
        "200/80/60",
    ]


def test_ladder_of_object_rungs_needs_no_run_builder(h: Harness) -> None:
    ctx = ctx_for(h, ladder_json=[SONNET, {**SONNET, "budget": {"max_tool_calls": 50}}])
    assert [r.label for r in h.worker._ladder(ctx)] == ["fake:sonnet", "fake:sonnet"]


def test_ladder_fails_closed_on_a_bad_rung_budget_before_any_task(h: Harness) -> None:
    for budget, reason in [
        ({"max_tool_calls": 0}, "must be positive"),
        ({"wall_clock_s": -1}, "must be positive"),
        ({"max_turns": "many"}, "invalid budget"),
        ({"max_cost": 1}, "unknown field"),
    ]:
        ctx = ctx_for(h, ladder_json=[{**SONNET, "budget": budget}])
        with pytest.raises(ValueError, match=reason):
            h.worker._ladder(ctx)
    with pytest.raises(ValueError, match="unknown field"):
        h.worker._ladder(ctx_for(h, ladder_json=[{**SONNET, "effort": "high"}]))
    with pytest.raises(ValueError, match="needs builder \\+ model"):
        h.worker._ladder(ctx_for(h, ladder_json=["r1", SONNET]))


def test_bad_rung_budget_fails_the_run_closed_end_to_end(h: Harness) -> None:
    run = h.enqueue("blind", ladder_json=[{**SONNET, "budget": {"max_tool_calls": 0}}])
    done = h.run_one()
    assert done.status == STATUS_FAILED and "invalid budget" in done.error
    assert list(h.worker.ledger.rows(run_id=run.id)) == []
    # the run-level budget is checked the same way (a stored document, not a request)
    run = h.enqueue("blind", ladder_json=[SONNET], params_json={"budget": {"max_turns": "many"}})
    done = h.run_one()
    assert done.status == STATUS_FAILED and "run's budget is invalid" in done.error
    assert list(h.worker.ledger.rows(run_id=run.id)) == []


# --- labels on rows -----------------------------------------------------------------------------


def test_budget_sweep_ladder_stamps_tier_and_rung_index_on_every_row(h: Harness) -> None:
    """25 → 50 → 100 tool calls on one model: rungs 1–2 come back red (budget), rung 3 is
    clean. Every row carries the tier it ran under and its rung index; the pack's own
    ``builder.budget`` agrees with the label; the chain verifies over the stamped rows."""
    seen: list[Budget] = []

    def scripted(**cfg: Any) -> FakeBuilder:
        b = FakeBuilder(behaviour="noop", **cfg)
        real = b.build

        def build(workspace: Any, brief: Any, budget: Budget, **kw: Any) -> Any:
            seen.append(budget)
            b.behaviour = "gold" if budget.max_tool_calls >= 100 else "noop"
            return real(workspace, brief, budget, **kw)

        b.build = build  # type: ignore[method-assign]
        return b

    builders_pkg._REGISTRY["fake"] = scripted
    run = h.enqueue(
        "blind",
        builder="fake",
        model="sonnet",
        ladder_json=[
            {**SONNET, "budget": {"max_tool_calls": 25}},
            {**SONNET, "budget": {"max_tool_calls": 50}},
            {**SONNET, "budget": {"max_tool_calls": 100}},
        ],
    )
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    c = done.counts_json
    assert (c["tasks"], c["clean"], c["rows"], c["first_pass_clean"]) == (1, 1, 3, 0)
    # the builder was handed the escalating budget, rung by rung
    assert [b.max_tool_calls for b in seen] == [25, 50, 100]
    assert all(b.max_turns == 25 and b.wall_clock_s == 900 for b in seen)
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert [(r.trial, r.clean, r.failure_kind) for r in rows] == [
        ("r1", False, "budget"),
        ("r2", False, "budget"),
        ("r3", True, ""),
    ]
    assert tiers(rows) == [
        ("r1", "0", "25/25/900"),
        ("r2", "1", "50/25/900"),
        ("r3", "2", "100/25/900"),
    ]
    assert rows[0].labels["rung"] == "r1" and rows[0].stop_reason == "max_turns"
    # the label is in the hashed body: the chain verifies over the stamped rows
    assert verify_chain(rows) == 3 and h.worker.ledger.verify() == 3
    for row, budget in zip(rows, seen, strict=True):
        pack = h.worker.ledger.get_pack(row.evidence_pack_hash)
        assert pack is not None and pack["builder"]["budget"] == budget.to_dict()
        assert (
            budget_tier(Budget.from_dict(pack["builder"]["budget"]))
            == row.labels[LABEL_BUDGET_TIER]
        )
    # the apparatus records the ladder with its tiers, next to the run-level budget
    extra = done.apparatus_json["extra"]
    assert extra["budget"] == Budget().to_dict()
    assert [(e["model"], e[LABEL_BUDGET_TIER]) for e in extra["ladder"]] == [
        ("sonnet", "25/25/900"),
        ("sonnet", "50/25/900"),
        ("sonnet", "100/25/900"),
    ]


def test_plain_ladder_rows_carry_the_run_budget_tier(h: Harness) -> None:
    """A run with no object rungs is stamped too (the run-level budget IS the tier), so
    every new row can be split by tier — not only those from a sweep."""
    run = h.enqueue("replay", params_json={"budget": {"max_tool_calls": 40, "wall_clock_s": 600}})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.clean and tiers([row]) == [("r1", "0", "40/25/600")]
    assert done.apparatus_json["extra"]["ladder"] == [
        {"builder": "fake", "model": "m", "provider": "p", LABEL_BUDGET_TIER: "40/25/600"}
    ]


def test_stamp_cannot_change_a_verdict() -> None:
    """The stamp copies every verdict field verbatim and ``GradeRow`` re-runs its
    invariants: a red row stays red, a clean row keeps its pack. (``_RunLedger._stamp``
    is exercised end to end above; this pins the construction it relies on.)"""
    red = posture_row(
        repo="r",
        task_id="t" * 40,
        clean=False,
        tests_unmodified=True,
        target_green=False,
        no_new_failures=True,
        source_changed=True,
        trial="r1",
        labels={"rung": "r1"},
    )
    stamped = GradeRow(**{**red.fields(), "labels": {**red.labels, LABEL_BUDGET_TIER: "25/25/900"}})
    assert stamped.clean is False and stamped.target_green is False
    assert stamped.labels == {**red.labels, LABEL_BUDGET_TIER: "25/25/900"}
    assert stamped.row_id == red.row_id and stamped.created == red.created
