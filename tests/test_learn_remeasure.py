"""``remeasure_plan`` read from the registered readings (ADR-0026 items 2 and 3, G-565, P-602).

Navigation
----------
What it is:   Tests for ``crb.core.learn.remeasure_plan`` as the look rule counts: a cell's
              top-up is its registered reading's pending commits, in the seeded order, and a
              cell with no reading is offered registration — never a replay whose rows could
              not count.
What it does: Shows a cell with rows and no reading offered ``register`` with no request, and
              that a reading registered afterwards over the cell's fresh commits is not refused
              ``pool_seen`` (the plan burned nothing); a registered reading's top-up naming
              exactly its pending commits among the next look, in the seeded order, and the
              plan reading the same ``counted`` and ``needed`` the Capability page reads; the
              four ways counting attempts misread a cell (repeats on five commits, blind ladder
              rungs, re-runs of one miss, two context arms); an ``insufficient`` or
              ``undecided`` reading named in ``cannot_clear`` with its reason; the arms a replay
              cannot write (``S2``, ``+L``, another test author, another posture) offered no
              request; gold-clean and relabelled commits left out; valid ``POST /runs`` bodies;
              unknown cost; determinism; and the CLI rendering.
How:          Sealed 2.4 rows and readings from ``tests.fixtures.readings``; rows of an older
              apparatus from ``tests.fixtures.posture``; no model, no docker, no store.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (items 2 and 3), docs/adr/0025-routing-v2.md
Works with:   src/crb/core/learn.py (``remeasure_plan``, under test), src/crb/core/reading.py
              (the readings it reads), tests/fixtures/readings.py (sealed rows, readings),
              tests/test_server_routes_learn.py (the same plan at the route and its queue)
Tested by:    this file
Touch when:   never for a new repository; the look rule or the counting changes (an ADR
              amending ADR-0026 first); a run body gains a field a reading's arm needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core import learn
from crb.core.capability import ReadingBook
from crb.core.ledger import GradeRow
from crb.core.reading import (
    REFUSAL_POOL_SEEN,
    STATE_INSUFFICIENT,
    STATE_UNDECIDED,
    ReadingRefused,
    evaluate,
    verdict_for,
)
from fixtures.posture import posture_row
from fixtures.readings import (
    AUTHOR,
    CELL,
    REPO,
    S1,
    SEALED,
    commits,
    register_reading,
    rows_for,
    sealed_row,
)

LABEL = "|".join(CELL.values())
CUR = "2.4"


def _book(*readings: Any, rows: list[GradeRow]) -> ReadingBook:
    return ReadingBook.evaluate(readings, rows)


def _plan(rows: list[GradeRow], *readings: Any, **kw: Any) -> learn.RemeasurePlan:
    """The plan at 2.4 over ``rows`` and ``readings`` (every task of the pools labelled the
    fixture cell and gold-clean unless a test says otherwise)."""
    pools = [c for r in readings for c in r.pool]
    labels = kw.pop("task_labels", dict.fromkeys(pools, (CELL["capability_class"], CELL["size"])))
    gold = kw.pop("gold_clean_tasks", pools)
    return learn.remeasure_plan(
        rows,
        readings=_book(*readings, rows=rows).outcomes,
        current_apparatus=CUR,
        task_labels=labels,
        gold_clean_tasks=gold,
        **kw,
    )


def _old(task: str, **kw: Any) -> GradeRow:
    """A clean sighted row of the fixture cell graded under apparatus 2.0 (no arm)."""
    base: dict[str, Any] = {
        "repo": REPO,
        "task_id": task,
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "evidence_pack_hash": "h" * 64,
        "apparatus_version": "2.0",
        "belt_set": "v4",
        "mode": "sighted",
        "cost_usd": 0.3,
        "latency_s": 60.0,
        **CELL,
    }
    base.update(kw)
    return posture_row(**base)


# --- no reading: register first, replay nothing -----------------------------------------


def test_a_cell_with_no_reading_is_offered_registration_and_no_replay() -> None:
    """ADR-0026 item 2: a cell is licensed only by a reading registered before its first
    attempt, and only rows graded after it count. A top-up queued without one buys rows no
    reading can count AND makes those commits seen, so a later registration over them is
    refused ``pool_seen``. So a cell with rows and no reading is offered ``register``, with no
    request and nothing priced — and the reading registered afterwards is not refused."""
    graded = commits(5, "graded")
    fresh = commits(40, "fresh")
    rows = [sealed_row(c, cost_usd=0.5) for c in graded]
    labels = dict.fromkeys(graded + fresh, (CELL["capability_class"], CELL["size"]))
    plan = learn.remeasure_plan(
        rows, readings=(), current_apparatus=CUR, task_labels=labels, gold_clean_tasks=fresh
    )
    (c,) = plan.cells
    assert (c.reason, c.next_act, c.arm) == (learn.REASON_THIN, learn.NEXT_REGISTER, "S3")
    assert c.requests == () and c.n_requested == 0 and c.est_cost_usd == 0.0
    assert (c.n_current, c.n_needed) == (5, 20)  # five distinct commits; the first look is 20
    assert "register a reading" in c.note and "never count" in c.note
    # the plan asked for nothing, so the fresh commits are still unseen: the registration a
    # thin top-up used to make impossible (pool_seen) goes through
    reading = register_reading(fresh, rows=rows)
    assert len(reading.pool) == 40
    # and once registered, the same cell is topped up on that reading's commits
    (p,) = _plan(rows, reading).cells
    assert p.next_act == learn.NEXT_REPLAY and p.reason == learn.REASON_PENDING
    assert p.requests[0].task_ids == reading.pool[:20]


def test_a_stale_cell_is_offered_a_reading_at_the_running_apparatus() -> None:
    """Rows of an older apparatus license nothing at this one, and a replay of their commits
    graded before any reading at this apparatus would never count: register first."""
    old = [_old(c) for c in commits(7, "old")]
    plan = learn.remeasure_plan(old, readings=(), current_apparatus=CUR)
    (c,) = plan.cells
    assert (c.reason, c.next_act, c.requests) == (learn.REASON_STALE, learn.NEXT_REGISTER, ())
    assert (c.n_stale, c.stale_versions, c.n_current) == (7, ("2.0",), 0)
    assert "apparatus 2.4" in c.note
    # the stale commits were never graded at 2.4, so a reading may hold them
    assert register_reading([r.task_id for r in old], rows=old).pool


# --- a registered reading: its pending commits, in the seeded order ----------------------


def test_a_readings_top_up_is_its_pending_commits_in_the_seeded_order() -> None:
    """The top-up asks for exactly the commits the reading still needs before its next look:
    the pool's first ``next_look`` commits, in the seeded order, that have no observed first
    attempt graded after registration. A commit whose attempt was a harness failure is still
    pending and is asked for again; a commit beyond the look is not asked for."""
    reading = register_reading(commits(40), hierarchy=("S3",))
    pool = reading.pool
    rows = rows_for([True] * 12, pool, cost_usd=0.25, latency_s=30.0)
    rows[5] = sealed_row(
        pool[5],
        clean=False,
        error="harness: sandbox failed to start",
        cost_usd=0.25,
        latency_s=30.0,
    )
    plan = _plan(rows, reading)
    (c,) = plan.cells
    assert (c.reason, c.next_act, c.arm, c.mode) == (
        learn.REASON_PENDING,
        learn.NEXT_REPLAY,
        "S3",
        "sighted",
    )
    assert (c.n_current, c.next_look, c.n_needed) == (5, 20, 9)
    (req,) = c.requests
    assert req.task_ids == (pool[5], *pool[12:20]) and req.limit == 9
    assert (req.kind, req.mode, req.learning, req.arm) == ("replay", "sighted", "off", "")
    assert c.reading_id == reading.reading_id and (c.n_requested, c.short_by) == (9, 0)
    assert c.cost_known and c.est_cost_usd == pytest.approx(0.25 * 9)
    # graded, the reading reads its look and the cell leaves the plan
    done = rows + rows_for([True] * 9, [pool[5], *pool[12:20]])
    after = _plan(done, reading)
    assert after.cells == () and after.up_to_date == (f"{LABEL}|S3",)


def test_the_api_docs_describe_up_to_date_as_the_served_label_and_arm() -> None:
    """P-428: each ``up_to_date`` entry is ``<cell label>|<arm>`` — the cell whose reading has
    delivered, with the arm it delivered on — not a bare cell label, so a client that compares
    it with ``cells[].label`` never finds a match. Every ``docs/API.md`` description of the
    field must name the shape the plan serves."""
    reading = register_reading(commits(40), hierarchy=("S3",))
    rows = rows_for([True] * 20, reading.pool)
    (entry,) = _plan(rows, reading).up_to_date
    label, _, arm = entry.rpartition("|")
    assert (label, arm) == (LABEL, "S3") and label.count("|") == 6
    api = (Path(__file__).resolve().parents[1] / "docs" / "API.md").read_text()
    described = [line for line in api.splitlines() if "up_to_date[]" in line]
    assert len(described) == 2
    for line in described:
        assert "up_to_date[] (one `<cell label>|<arm>` string" in line, line


def test_the_plan_reads_the_numbers_the_capability_page_reads() -> None:
    """The Learn page and the Capability page cannot disagree: the plan's counted and needed
    are the reading verdict's for the arm the cell waits on."""
    reading = register_reading(commits(40))
    rows = rows_for([True] * 19 + [False] + [True] * 4, reading.pool)
    (c,) = _plan(rows, reading).cells
    v = verdict_for(evaluate(reading, rows), "S3")
    assert (c.n_current, c.n_needed, c.next_look) == (v.counted, v.needed, v.next_look)
    assert (c.n_needed, c.next_look) == (6, 30)


def test_the_blocking_arm_is_topped_up_and_s1_carries_its_author() -> None:
    """The hierarchy is read richest first and stops at the first arm that does not deliver:
    only that arm's commits are asked for. ``S1@<author>`` is a blind replay with ``arm: S1``
    and is asked for only when the deployment's test author is that model — another author's
    rows are another arm and would never count."""
    reading = register_reading(commits(40))  # S3, then S1@claude-opus-5
    rows = rows_for([True] * 20, reading.pool)  # S3 delivers at its first look
    (c,) = _plan(rows, reading, s1_author_model=AUTHOR).cells
    assert (c.arm, c.mode, c.n_needed) == (S1, "blind", 20)
    (req,) = c.requests
    assert (req.kind, req.mode, req.arm, req.learning) == ("blind", "blind", "S1", "off")
    assert req.task_ids == reading.pool[:20]
    for other in ("", "gpt-oss-120b"):
        (o,) = _plan(rows, reading, s1_author_model=other).cells
        assert o.requests == () and o.next_act == learn.NEXT_BY_HAND and AUTHOR in o.note


def test_a_replay_is_never_asked_for_rows_the_reading_cannot_count() -> None:
    """P-602: ``S2`` counts only factory rows on held-out tests, ``+L`` only rows graded with
    the repository's loop switch on, and every replayed arm only rows graded in the reading's
    posture class — a replay this plan composed could write none of them."""
    s2 = register_reading(
        commits(40, "s2"), hierarchy=("S2",), cell={**CELL, "process_step": "factory"}
    )
    (c,) = _plan([], s2).cells
    assert c.requests == () and c.next_act == learn.NEXT_BY_HAND and "factory" in c.note
    loop = register_reading(commits(40, "loop"), hierarchy=("S3+L",))
    (lp,) = _plan([], loop).cells
    assert lp.requests == () and "loop switch" in lp.note
    reading = register_reading(commits(40), hierarchy=("S3",))
    (host,) = _plan([], reading, deployment_posture="local/inplace/host-env").cells
    assert host.requests == () and SEALED in host.note and "local/inplace/host-env" in host.note
    (ok,) = _plan([], reading, deployment_posture=SEALED).cells
    assert ok.requests and ok.requests[0].task_ids == reading.pool[:20]


def test_pending_commits_that_are_not_gold_clean_or_were_relabelled_are_left_out() -> None:
    reading = register_reading(commits(40), hierarchy=("S3",))
    pool = reading.pool
    labels = dict.fromkeys(pool, (CELL["capability_class"], CELL["size"]))
    labels[pool[1]] = ("feature.add", "XS")
    (c,) = _plan([], reading, task_labels=labels, gold_clean_tasks=pool[2:]).cells
    assert c.relabelled == (pool[1],)
    assert c.requests[0].task_ids == pool[2:20] and (c.n_requested, c.short_by) == (18, 2)
    assert "gold-clean" in c.note and "relabelled" in c.note


# --- counting distinct first attempts, never attempts --------------------------------------


def test_repeated_attempts_on_five_commits_are_five_commits_not_the_bar() -> None:
    """Twenty rows on five commits are five distinct commits: the cell is not at the bar and
    does not disappear from the plan."""
    five = commits(5, "five")
    rows = [sealed_row(c, created=f"2026-09-27T1{i}:00:00+00:00") for i in range(4) for c in five]
    (c,) = learn.remeasure_plan(rows, readings=(), current_apparatus=CUR).cells
    assert c.n_current == 5 and c.next_act == learn.NEXT_REGISTER


def test_blind_ladder_rungs_are_not_first_attempts() -> None:
    reading = register_reading(commits(40), hierarchy=(S1,))
    pool = reading.pool
    rows = [
        sealed_row(c, arm=S1, trial=rung, clean=rung == "r3")
        for c in pool[:7]
        for rung in ("r1", "r2", "r3")
    ]
    plan = _plan(rows, reading, s1_author_model=AUTHOR)
    assert plan.cells == () and [x.state for x in plan.cannot_clear] == [STATE_INSUFFICIENT]
    clean_first = [sealed_row(c, arm=S1, trial=rung) for c in pool[:7] for rung in ("r1", "r2")]
    (c,) = _plan(clean_first, reading, s1_author_model=AUTHOR).cells
    assert (c.n_current, c.n_needed) == (7, 13)


def test_re_runs_of_a_miss_are_one_miss() -> None:
    """Two commits missed at their first attempt, each re-run once: two misses, which the last
    look still allows — the cell is topped up, not declared unable to clear."""
    reading = register_reading(commits(40), hierarchy=("S3",))
    pool = reading.pool
    rows = rows_for([False, False] + [True] * 3, pool)
    rows += [sealed_row(pool[0], created="2026-09-27T12:00:00+00:00")]
    rows += [sealed_row(pool[1], clean=False, created="2026-09-27T12:00:00+00:00")]
    plan = _plan(rows, reading)
    assert plan.cannot_clear == ()
    (c,) = plan.cells
    assert (c.n_current, c.next_look, c.n_needed) == (5, 40, 35)


def test_two_context_arms_are_never_pooled_into_one_count() -> None:
    ten = commits(20, "arm")
    rows = [sealed_row(c, arm="S3") for c in ten[:10]]
    rows += [sealed_row(c, arm="S3+L") for c in ten[10:]]
    plan = learn.remeasure_plan(rows, readings=(), current_apparatus=CUR)
    assert sorted((c.arm, c.n_current) for c in plan.cells) == [("S3", 10), ("S3+L", 10)]


# --- decided readings --------------------------------------------------------------------


def test_a_decided_reading_is_named_with_its_reason_and_offered_nothing() -> None:
    insufficient = register_reading(commits(40), hierarchy=("S3",))
    rows = rows_for([False, False, False], insufficient.pool)
    plan = _plan(rows, insufficient)
    assert plan.cells == ()
    (x,) = plan.cannot_clear
    assert (x.label, x.state, x.next_act) == (LABEL, STATE_INSUFFICIENT, "new_reading")
    assert "third miss" in x.reason and x.to_dict()["state"] == STATE_INSUFFICIENT
    small = register_reading(commits(15, "small"), hierarchy=("S3",))
    (u,) = _plan(rows_for([True] * 15, small.pool), small).cannot_clear
    assert (u.state, u.next_act) == (STATE_UNDECIDED, "mine")
    assert "pool" in u.reason and "labelled" in u.reason


# --- bodies, cost, determinism -----------------------------------------------------------


def test_requests_are_valid_post_runs_bodies() -> None:
    pytest.importorskip("pydantic")
    from crb.server.schemas import RunCreateRequest

    reading = register_reading(commits(40))
    rows = rows_for([True] * 20, reading.pool)
    for plan in (_plan([], reading), _plan(rows, reading, s1_author_model=AUTHOR)):
        for c in plan.cells:
            for r in c.requests:
                body = r.to_dict()
                body.pop("note", None)
                req = RunCreateRequest(**body)
                assert req.kind in ("replay", "blind") and req.task_ids == list(r.task_ids)


def test_unknown_cost_is_honest_and_a_blind_top_up_is_priced_per_rung() -> None:
    reading = register_reading(commits(40), hierarchy=(S1,))
    (c,) = _plan([], reading, s1_author_model=AUTHOR).cells
    assert not c.cost_known and c.est_cost_usd == 0.0
    assert "?" in learn.render_remeasure(_plan([], reading, s1_author_model=AUTHOR))
    priced = [sealed_row(x, arm="A0", cost_usd=0.4) for x in commits(3, "priced")]
    (b,) = _plan(priced, reading, s1_author_model=AUTHOR).cells
    assert b.cost_known and b.est_cost_usd == pytest.approx(0.4 * 20 * 3)


def test_deterministic_and_rendered() -> None:
    reading = register_reading(commits(40))
    rows = rows_for([True] * 7, reading.pool) + [_old(c, size="S") for c in commits(3, "old")]
    a = learn.dumps(_plan(rows, reading).to_dict())
    b = learn.dumps(_plan(list(reversed(rows)), reading).to_dict())
    assert a == b and "nothing here was sent" in a
    text = learn.render_remeasure(_plan(rows, reading))
    assert "apparatus 2.4" in text and "| look_pending |" in text and "| register |" in text


def test_a_reading_already_seen_is_refused_so_a_burned_pool_is_visible() -> None:
    """The failure this plan now prevents, pinned from the other side: rows graded on a
    commit before a reading holds it make that commit seen."""
    fresh = commits(20, "burn")
    burned = [sealed_row(c) for c in fresh]
    with pytest.raises(ReadingRefused) as exc:
        register_reading(fresh, rows=burned)
    assert exc.value.code == REFUSAL_POOL_SEEN
