"""The worker and the prevention loop — what a run is given, what its rows record, and a tick
that never fails a run (ADR-0020 §4, §8, §10).

Navigation
----------
What it is:   The worker-side test suite of the prevention loop, over the fake builder.
What it does: Pins that every row of a replay carries the ``learn*`` labels of the snapshot it
              ran under (``learn: off`` when the switch is off); that a run which opts out
              (``params.learning = "off"``) sees no line and no overlay; that the brief renders
              the lines as the operating-notes checklist after the harness line and records them
              in ``to_dict``; that a failing snapshot or tick never fails the run; and that the
              team's own configuration keys outrank the loop's overlay.
How:          ``Harness`` from tests/test_worker.py; the chain seeded through
              ``EventsPreventionStore``; ``FakeBuilder.briefs`` holds what the builder read.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/server/worker.py (under test), src/crb/server/prevention_state.py (the
              snapshot and the tick), src/crb/builders/adapter.py (the lines reach the brief
              here), tests/test_worker.py (the harness and the fake builder)
Tested by:    tests/test_worker_learning.py
Touch when:   a label is added to what a row records about the loop, or the snapshot's
              inputs change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.core.playbook import PlaybookSignal, render_line
from crb.core.prevention import (
    LABEL_CHANGES,
    LABEL_DROPPED,
    LABEL_LEARN,
    LABEL_LINES,
    LABEL_OVERLAY,
    LABEL_PLAYBOOK,
    PreventionRecord,
)
from crb.server import worker as worker_mod
from crb.server.prevention_state import EventsPreventionStore, learning_snapshot
from crb.store.jobs import STATUS_SUCCEEDED
from fixtures import pyrepo as pr
from test_worker import FakeBuilder, Harness

TAUGHT = ("a" * 40, "b" * 40, "c" * 40)
KEY = "2.2|fake|m|crb.prevention.sig.v1"


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


def _rec(kind: str, payload: dict[str, Any], i: int) -> PreventionRecord:
    return PreventionRecord(
        kind,
        pr.REPO_NAME,
        payload,
        actor="op-1" if kind == "switched" else "loop",
        on_behalf_of="op-1",
        reason="fixture",
        created=f"2026-01-01T00:00:{i:02d}+00:00",
    )


def _line() -> dict[str, Any]:
    line = render_line(
        PlaybookSignal("T-NET", "protocol:network:pip install", {"head": "pip install"}, TAUGHT)
    )
    assert line is not None
    return line.to_dict()


def _applied(lever: str, family: str, what: dict[str, Any], i: int, cid: str) -> PreventionRecord:
    sig = "protocol:network:pip install"
    return _rec(
        "applied",
        {
            "change_id": cid,
            "lever_id": lever,
            "family": family,
            "level": "advisory" if family == "context" else "mistake-proofing",
            "targets": [sig],
            "stratum": {"mode": "blind"},
            "key": KEY,
            "what": what,
            "before": {sig: {"k0": 3, "n0": 10, "decisive_n": 11}},
        },
        i,
    )


def _seed(h: Harness, *records: PreventionRecord) -> None:
    with h.factory() as s:
        store = EventsPreventionStore(s, pr.REPO_NAME)
        for r in records:
            store.append(r)
        s.commit()


GATE = {"section": "checks", "key": "finish_gate", "value": True}


def test_every_row_carries_the_learning_labels(h: Harness) -> None:
    # the switch has never been thrown: every row says so
    run = h.enqueue("replay")
    done = h.run_one()
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.labels[LABEL_LEARN] == "off" and LABEL_LINES not in row.labels
    assert done.apparatus_json["extra"]["learning"]["auto_apply"] == "off"
    # context, with one line in force
    line = _line()
    _seed(
        h,
        _rec("switched", {"auto_apply": "context"}, 1),
        _applied("line:T-NET", "context", line, 2, "c1"),
    )
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.labels[LABEL_LEARN] == "context"
    assert row.labels[LABEL_LINES] == line["line_id"]
    assert len(row.labels[LABEL_PLAYBOOK]) == 16 and LABEL_DROPPED not in row.labels
    assert (
        LABEL_CHANGES not in row.labels
    )  # a line is named by learn_lines, a switch by learn_changes
    assert done.apparatus_json["extra"]["learning"]["lines"] == [line["line_id"]]
    # the labels are hashed: the chain commits to what the builder was given
    assert h.worker.ledger.verify() == 2


def test_a_run_that_opts_out_sees_no_line_and_no_overlay(h: Harness) -> None:
    _seed(
        h,
        _rec("switched", {"auto_apply": "config"}, 1),
        _applied("line:T-NET", "context", _line(), 2, "c1"),
        _applied("finish_gate", "config", GATE, 3, "c2"),
    )
    run = h.enqueue("replay")
    h.run_one()
    (on,) = h.worker.ledger.rows(run_id=run.id)
    assert on.labels[LABEL_LEARN] == "config" and on.labels[LABEL_CHANGES] == "c2"
    assert on.labels[LABEL_OVERLAY] and on.labels[LABEL_LINES]
    assert FakeBuilder.briefs[-1].playbook
    off = h.enqueue("replay", params_json={"learning": "off"})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED
    (row,) = h.worker.ledger.rows(run_id=off.id)
    assert row.labels[LABEL_LEARN] == "off"
    for label in (LABEL_CHANGES, LABEL_OVERLAY, LABEL_LINES, LABEL_PLAYBOOK):
        assert label not in row.labels
    assert FakeBuilder.briefs[-1].playbook == ()
    assert done.apparatus_json["extra"]["learning"]["opted_out"] is True


def test_the_brief_renders_the_lines_after_the_harness_line(h: Harness) -> None:
    line = _line()
    _seed(
        h,
        _rec("switched", {"auto_apply": "context"}, 1),
        _applied("line:T-NET", "context", line, 2, "c1"),
    )
    h.enqueue("blind")
    assert h.run_one().status == STATUS_SUCCEEDED
    (brief,) = FakeBuilder.briefs
    text = brief.task_text()
    harness = text.index("The test environment is provisioned")
    notes = text.index("Operating notes for this repository (a checklist):")
    rules = text.index("RULES (violations disqualify the run):")
    assert harness < notes < rules
    assert f"  - {line['text']}" in text
    assert brief.to_dict()["playbook"] == [line["text"]]


def test_a_tick_failure_never_fails_the_run(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def boom_tick(*_: Any, **__: Any) -> list[PreventionRecord]:
        calls.append("tick")
        raise RuntimeError("the chain is on fire")

    def boom_snapshot(*_: Any, **__: Any) -> Any:
        raise RuntimeError("cannot read the chain")

    monkeypatch.setattr(worker_mod, "learning_tick", boom_tick)
    monkeypatch.setattr(worker_mod, "learning_snapshot", boom_snapshot)
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert calls == ["tick"]
    (row,) = h.worker.ledger.rows(run_id=run.id)
    assert row.labels[LABEL_LEARN] == "off"  # an unreadable chain gives learn: off — true


def test_config_section_lets_the_teams_keys_win(tmp_path: Path, pyrepo: pr.PyRepo) -> None:
    team = Harness(tmp_path / "team", pyrepo)
    team.add_repo(checks={"finish_gate": False})
    _seed(
        team,
        _rec("switched", {"auto_apply": "config"}, 1),
        _applied("finish_gate", "config", GATE, 2, "c2"),
    )
    snap = learning_snapshot(team.factory, pr.REPO_NAME, {})
    assert snap.changes == () and snap.overlay == {}
    assert snap.config_section("checks", {"finish_gate": False}) == {"finish_gate": False}
    free = Harness(tmp_path / "free", pyrepo)
    free.add_repo()
    _seed(
        free,
        _rec("switched", {"auto_apply": "config"}, 1),
        _applied("finish_gate", "config", GATE, 2, "c2"),
    )
    snap = learning_snapshot(free.factory, pr.REPO_NAME, {})
    assert [c.change_id for c in snap.changes] == ["c2"]
    assert snap.config_section("checks", {}) == {"finish_gate": True}
    # a run parameter outranks both
    assert (
        learning_snapshot(free.factory, pr.REPO_NAME, {"checks": {"finish_gate": False}}).changes
        == ()
    )
