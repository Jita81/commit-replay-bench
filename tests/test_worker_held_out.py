"""The served worker binds the store's held-out acceptance tests into a factory run.

Navigation
----------
What it is:   The worker-level test of the one seam stream FWD injects into the factory loop:
              ``FactorySpec.held_out``, which the served worker binds to
              ``crb.server.acceptance.held_out_reader`` for the run's repository.
What it does: Pins, through ``Worker.run_once`` on the fixture repository (onboarding a client
              repository's first calibration build end to end), that a funded calibration build
              on a ceiling cell whose held-out tests a second person stored is graded on them:
              its ``r1`` row carries ``acceptance: held_out`` with the stored record's digest
              and ``acceptance.graded`` is on the chain. Deleting the worker's binding stamps
              every served calibration build ``acceptance: none`` and fails this test
              (verify_fwd_evidence W1 — the served default of an injected seam).
How:          ``tests/test_worker.py``'s harness and backlog helper; the store-bound readers
              patched at their one binding to read a ceiling (``S3``) everywhere; the record
              written through ``write_held_out``, the grant through the factory chain.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/server/worker.py (``_run_factory`` binds ``held_out``),
              src/crb/server/acceptance.py (``held_out_reader``, ``write_held_out``),
              src/crb/factory/loop.py (``_held_out``), tests/test_worker.py (the harness)
Tested by:    this file
Touch when:   never for a new repository; the worker's factory spec changes how it binds a
              seam of the loop.
"""

from __future__ import annotations

import pytest

from crb.core.acceptance import (
    ACCEPTANCE_HELD_OUT,
    LABEL_ACCEPTANCE,
    LABEL_ACCEPTANCE_RESULT,
    LABEL_ACCEPTANCE_SHA,
    RESULT_PASS,
    HeldOutTests,
)
from crb.factory import evidence as fe
from crb.factory.standard import Readers, Standard
from crb.server import factory_standard
from crb.server.acceptance import write_held_out
from crb.store.jobs import STATUS_SUCCEEDED
from fixtures import pyrepo as pr
from test_worker import Harness, _multiply_backlog, _register, h

__all__ = ["_register", "h"]  # the harness's fixtures, used here

HELD_OUT = (
    "from calc import multiply\n\n\n"
    "def test_multiply_held_out_by_a_second_person():\n"
    "    assert multiply(7, 6) == 42\n"
)


def _every_cell_a_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    readers = Readers(standard_for=lambda cell: Standard("S3"), agreement_passed=False)

    def bound(*_a: object, **_kw: object) -> Readers:
        return readers

    monkeypatch.setattr(factory_standard, "bind_readers", bound)
    monkeypatch.setattr(factory_standard, "readers_in", bound)


def test_the_served_worker_grades_a_calibration_build_on_the_stored_held_out_tests(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _every_cell_a_ceiling(monkeypatch)
    home, _item, _backlog = _multiply_backlog(h)
    grant = home.evidence(actor="approver:ada").record_calibration(
        "I-1", approver="approver:ada", reason="the forward reading"
    )
    record = HeldOutTests(
        repo=pr.REPO_NAME,
        item_id="I-1",
        grant=grant.event_id,
        files=(("tests/test_multiply_held_out.py", HELD_OUT),),
        author="operator:bea",
        written_at="2026-01-01T00:00:00+00:00",
        capability_class="bug.fix",
        size="XS",
        language="python",
    )
    write_held_out(h.factory, record)
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["by_status"] == {"calibration_build": 1}
    (row,) = list(h.worker.ledger.rows(run_id=run.id))
    assert row.trial == "r1" and row.context_arm == "S2"
    assert row.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_HELD_OUT
    assert row.labels[LABEL_ACCEPTANCE_SHA] == record.sha256
    assert row.labels[LABEL_ACCEPTANCE_RESULT] == RESULT_PASS
    (graded,) = [e for e in home.events() if e.kind == fe.EV_ACCEPTANCE_GRADED]
    assert graded.payload["row_hash"] == row.row_hash
