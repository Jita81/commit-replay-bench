"""The served worker's two class-set bindings: the intake pass stamps, a replay run stamps.

Navigation
----------
What it is:   Tests of the worker's own bindings of an organisation's class set (ADR-0026 item
              9): ``Worker._poll_one`` hands the intake ``class_set_state.draft_stamper`` for the
              repository, and ``Worker._run_replay`` hands ``RunSpec`` the run's ``taxonomy``.
What it does: Pins, on the served default of each injected seam (P-392's lesson, P-689), that a
              routing version in the store reaches a ticket the worker's poll registers — its
              item carries ``taxonomy``, ``org_class`` and ``class_by`` — and that a queued
              replay run naming a version grades every row under it, inside the row's hash.
              The function-level tests of the stamper and ``row_from`` pass the hook and the
              field directly; these fail if the worker stops passing them.
How:          ``test_intake_worker.Stack`` (a worker, a store and the fake board) and
              ``test_worker.Harness`` (a worker over the Python fixture repository and the fake
              builder); the version is written straight into the store by
              ``fixtures.class_sets.seed_routing_version``. No model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   src/crb/server/worker.py (the bindings under test),
              src/crb/server/class_set_state.py (the stamper), src/crb/core/run.py (the row's
              stamp), tests/fixtures/class_sets.py (the organisation)
Tested by:    this file
Touch when:   onboarding a client repository never needs it; the worker's intake pass or its
              replay run changes how it binds a class set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import crb.builders as builders_pkg
from crb.intake.fake import FAKE_TRACKER_ENV, fake_tracker_path
from crb.server.factory_state import FactoryHome
from crb.store.jobs import STATUS_SUCCEEDED
from fixtures import pyrepo as pr
from fixtures.class_sets import add_commits, seed_routing_version
from fixtures.proven_cells import every_cell_proven
from test_intake_worker import BOARD, Stack, _intake
from test_worker import FakeBuilder, Harness

V1 = "acme/classes@v1"


def test_the_worker_intake_pass_stamps_a_ticket_with_the_routing_class_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FAKE_TRACKER_ENV, "1")
    every_cell_proven(monkeypatch, "S1@claude-sonnet-5")
    stack = Stack(tmp_path, _intake())
    stack.add_repo("alpha", {"enabled": True})
    board = json.loads(json.dumps(BOARD))
    board["tickets"]["4711"]["title"] = "The parser drops the last token of a document"
    fake_tracker_path(stack.home).write_text(json.dumps(board), encoding="utf-8")
    add_commits(stack.factory)
    assert seed_routing_version(stack.factory) == V1
    assert stack.worker.poll_intake() == 1
    backlog = FactoryHome(stack.home, "alpha").load_backlog()
    assert backlog is not None and [i.id for i in backlog.items] == ["fake-4711"]
    item = backlog.items[0]
    assert (
        item.labels.get("taxonomy"),
        item.labels.get("org_class"),
        item.labels.get("class_by"),
    ) == (
        V1,
        "parser-fix",
        "rule",
    )
    assert item.capability_class == "bug.fix"


def test_a_queued_replay_run_naming_a_class_set_grades_every_row_under_it(
    tmp_path: Path, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None
    h = Harness(tmp_path, pyrepo)
    h.add_repo()
    h.add_task(pyrepo.feat_task())
    run = h.enqueue("replay", params_json={"taxonomy": V1})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert rows and {r.taxonomy for r in rows} == {V1}
    assert all(r.verify_hash() for r in rows)
    plain = h.enqueue("replay")
    h.run_one()
    assert {r.taxonomy for r in h.worker.ledger.rows(run_id=plain.id)} == {"global/classes@v1"}
