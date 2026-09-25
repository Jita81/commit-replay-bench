"""The loop cannot game its own metric — each attack a loop (or a person) could try, refused.

Navigation
----------
What it is:   The prevention loop's anti-gaming suite (ADR-0020 §1, §6; "What we must never do").
What it does: Pins that the register, the measurement and the tick take no argument that
              could drop a row, a task or a class; that every grader key is refused by name
              and nothing is ever switched off; that a change id forged onto a row (before the
              change, or never applied) is not exposure; that a lever the loop retired is not
              re-applied under the same apparatus and a lever a person reverted is never
              re-applied; that re-deriving decisions from a filtered ledger is refused; and
              that the team's own configuration outranks the loop's overlay.
How:          The fixture ledger and ``Loop`` from tests/test_prevention_rule.py; the public
              functions' signatures by ``inspect``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/prevention.py (under test), tests/test_prevention_rule.py (the
              ``Loop`` and the ladder), tests/prevention_fixtures.py (the rows)
Tested by:    tests/test_prevention_gaming.py
Touch when:   a parameter is added to a public function of the loop (it must not filter), or
              a key joins ``WRITABLE`` (with an ADR-0020 amendment).
"""

from __future__ import annotations

import inspect

import pytest

from crb.core.prevention import (
    AUTO_CONFIG,
    AUTO_CONTEXT,
    FORBIDDEN_EXAMPLES,
    LEVERS,
    WRITABLE,
    Mechanisms,
    NotWritable,
    PreventionRecord,
    build_register,
    check_writable,
    choose_lever,
    measure,
    snapshot,
    tick,
    verify_decisions,
)
from prevention_fixtures import NET_SIG, REPO, at, attempt, change_labels, line_labels, task
from test_prevention_rule import Loop, _ladder_to_closed, _ladder_to_line

_FILTERISH = ("filter", "exclude", "skip", "only", "include", "ignore", "drop", "where", "tasks")


def test_register_and_measure_take_no_filter_argument() -> None:
    for fn in (build_register, measure, tick, verify_decisions):
        names = list(inspect.signature(fn).parameters)
        bad = [n for n in names if any(w in n.lower() for w in _FILTERISH)]
        assert not bad, f"{fn.__name__} takes {bad}: nothing may drop a row, a task or a class"


def test_the_loop_refuses_every_grader_key() -> None:
    for name in FORBIDDEN_EXAMPLES:
        section, _, key = name.rpartition(".")
        with pytest.raises(NotWritable, match="not a key the prevention loop may write"):
            check_writable(section, key, True)
    # the loop never switches anything off, and never writes another value
    with pytest.raises(NotWritable, match="never switches anything off"):
        check_writable("checks", "finish_gate", False)
    with pytest.raises(NotWritable):
        check_writable("spend", "budget_profile", "default")
    # the allowlist and the catalogue's switches are the same three, and nothing else
    config_levers = {lv.lever_id for lv in LEVERS if lv.family == "config"}
    assert (
        config_levers
        == {w.lever_id for w in WRITABLE}
        == {
            "format_step",
            "finish_gate",
            "budget_calibrated",
        }
    )
    for w in WRITABLE:
        check_writable(w.section, w.key, w.value)
    # every switch a tick applies passes the guard
    loop = Loop(
        [
            attempt(i=i, task_id=task(i % 10), kind="protocol" if i % 3 == 0 else "clean")
            for i in range(30)
        ],
        mechanisms=Mechanisms(shipped=frozenset({"finish_gate"})),
    )
    loop.switch(AUTO_CONFIG, 40)
    loop.tick(50)
    applied = loop.records("applied")
    assert applied and all(
        check_writable(
            r.payload["what"]["section"], r.payload["what"]["key"], r.payload["what"]["value"]
        )
        is None
        for r in applied
        if r.payload["family"] == "config"
    )


def test_a_forged_change_id_on_a_row_is_not_exposure() -> None:
    loop, line_id = _ladder_to_line()
    applied_at = loop.applied("line:T-NET").created
    # rows stamped before the change that name it (forged or back-dated), and rows naming a
    # change that was never applied, are not exposure
    loop.add(
        [attempt(i=60 + j, task_id=task(10 + j), labels=line_labels(line_id)) for j in range(15)]
        + [
            attempt(i=101 + j, task_id=task(10 + j), labels=line_labels("feedfeedfeed"))
            for j in range(15)
        ]
        + [
            attempt(i=120 + j, task_id=task(10 + j), labels=change_labels("0" * 16))
            for j in range(15)
        ]
    )
    assert at(60) < applied_at
    m = loop.register().entry(NET_SIG).measurement  # type: ignore[union-attr]
    assert m is not None and m.exposed_n == 0 and m.unexposed_n == 30
    assert loop.tick(140) == []  # nothing to decide on


def test_a_retired_lever_is_not_reapplied_under_the_same_apparatus() -> None:
    loop, line_id = _ladder_to_line()
    from prevention_fixtures import exposed_to

    loop.add(
        exposed_to(
            start=101,
            n=22,
            recur={0, 4, 8, 13, 18},
            first_task=10,
            labels=line_labels(line_id),
            run="run-3",
        )
    )
    loop.tick(130)
    loop.switch(AUTO_CONTEXT, 131)  # a person throws the switch again
    assert loop.tick(132) == []
    assert len(loop.records("applied")) == 1
    retired = frozenset({(NET_SIG, "line:T-NET", "2.2")})
    assert (
        choose_lever(NET_SIG, apparatus="2.2", switch=AUTO_CONTEXT, retired=retired).lever_id == ""
    )
    # under a new apparatus the measurement starts again, so the lever is admissible again
    assert (
        choose_lever(NET_SIG, apparatus="2.3", switch=AUTO_CONTEXT, retired=retired).lever_id
        == "line:T-NET"
    )


def test_a_person_reverted_lever_is_never_reapplied_by_the_loop() -> None:
    loop, _ = _ladder_to_line()
    cid = loop.applied("line:T-NET").payload["change_id"]
    loop.store.append(
        PreventionRecord(
            "reverted",
            REPO,
            {"change_id": cid, "by": "person", "veto": True},
            actor="op-2",
            on_behalf_of="op-2",
            reason="the line confused the builder in review",
            created=at(101),
        )
    )
    reg = loop.register()
    assert reg.playbook == ()  # removed from the next run
    for i in range(3):
        loop.switch(AUTO_CONTEXT, 110 + i)
        assert [r for r in loop.tick(120 + i) if r.kind == "applied"] == []
    e = loop.register().entry(NET_SIG)
    assert e is not None and ("line:T-NET", "advisory", "a person reverted it for this class") in (
        e.recommendation.passed_over
    )


def test_verify_decisions_refuses_a_filtered_ledger() -> None:
    loop = _ladder_to_closed()
    assert verify_decisions(loop.records(), loop.rows) == []
    exposed = [r for r in loop.rows if "learn_changes" in r.labels]
    filtered = [r for r in loop.rows if r.row_hash != exposed[3].row_hash]
    problems = verify_decisions(loop.records(), filtered)
    assert problems and all("filtered" in p for p in problems)
    # reclassifying a recurrence as something else is caught too
    loop2 = _ladder_to_closed()
    first_red = next(
        r for r in loop2.rows if "learn_lines" in r.labels and r.failure_kind == "protocol"
    )
    swapped = [
        attempt(i=0, task_id=first_red.task_id, labels=dict(first_red.labels))
        if r.row_hash == first_red.row_hash
        else r
        for r in loop2.rows
    ]
    assert verify_decisions(loop2.records(), swapped)


def test_the_teams_own_configuration_outranks_the_overlay() -> None:
    base = {"checks": {"finish_gate": False}}
    choice = choose_lever(
        NET_SIG,
        apparatus="2.2",
        switch=AUTO_CONFIG,
        mechanisms=Mechanisms(shipped=frozenset({"finish_gate"})),
        base_config=base,
    )
    assert ("finish_gate", "mistake-proofing", "the team set checks.finish_gate itself") in (
        choice.passed_over
    )
    # a change in force before the team set the key: the team wins, the register says so
    rows = [
        attempt(i=i, task_id=task(i % 10), kind="protocol" if i % 3 == 0 else "clean")
        for i in range(30)
    ]
    loop = Loop(rows, mechanisms=Mechanisms(shipped=frozenset({"finish_gate"})))
    loop.switch(AUTO_CONFIG, 40)
    loop.tick(50)
    snap = snapshot(loop.records(), repo=REPO, base_config=base)
    assert snap.changes == () and snap.config_section("checks", base["checks"]) == {
        "finish_gate": False
    }
    free = snapshot(loop.records(), repo=REPO)
    assert free.config_section("checks", {}) == {"finish_gate": True}
    assert free.config_section("checks", {"finish_gate": False}) == {"finish_gate": False}
    # a run parameter outranks both
    ran = snapshot(loop.records(), repo=REPO, params={"checks": {"finish_gate": False}})
    assert ran.changes == ()
    reg = build_register(
        loop.rows, records=loop.records(), repo=REPO, mechanisms=loop.mech, base_config=base
    )
    e = reg.entry(NET_SIG)
    assert e is not None and "overridden" in e.qualifiers
