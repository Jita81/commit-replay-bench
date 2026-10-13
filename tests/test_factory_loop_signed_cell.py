"""crb.factory.loop — the sign-off clause, its one-run override, and the delivered cell's licence.

Navigation
----------
What it is:   The factory loop's sign-off-clause tests, moved out of tests/test_factory_loop.py so
              the suite's shards stay inside their time budget (files are the shard unit).
What it does: Pins that an item whose cell's proven standard carries no active sign-off stops
              ``unsigned_cell`` before any spend, delivery on or off (ADR-0018, on by default),
              that the setting removes this clause and no other, that a second approver's
              per-run override lifts it alone and is named on the chain and in the pull request
              — never the run's own actor (GOV-4), and never when any cell the size rule reads
              carries false-Q1 (GOV-1) — and that a change larger than its estimate is
              delivered only into a signed cell, its licence line read from the delivered cell,
              never the estimate's (P-391).
How:          The ``Rig`` and ``_rig`` harness of tests/test_factory_loop.py over ``pyrepo``, with
              the gate's ``Readers`` signed or unsigned per cell and a builder edit padded past
              the signed sizes.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0018-a-signed-cell-licenses-delivery.md,
              docs/adr/0026-the-context-standard.md
Works with:   src/crb/factory/loop.py (under test), src/crb/factory/standard.py (the entry gate's
              sign-off clause and its override), src/crb/factory/delivery.py (the licence line in
              the pull-request body), tests/test_factory_loop.py (the shared harness),
              tests/test_factory_loop_route_gate.py (the route clause the override never lifts)
Tested by:    tests/test_factory_loop_signed_cell.py
Touch when:   never for a new repository; the sign-off clause, its override or the licence line
              changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.builders.brief import ARM_S2
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory.backlog import BacklogItem
from crb.factory.standard import Readers, Standard
from crb.observability.events import StepStatus
from fixtures import pyrepo as pr
from test_factory_build import authored_multiply, multiply_item
from test_factory_loop import (
    DELIVER_ROUTE,
    FALSE_Q1_ROUTE,
    HUMAN_ROUTE,
    UNSIGNED,
    MultiBuilder,
    Rig,
    _creds,
    _lifted,
    _override_refusals,
    _padded,
    _rig,
    _signed_only,
)

# --- the signed-cell clause (ADR-0018, G-517) ---------------------------------------


class TestSignedCellClause:
    """The sign-off clause (ADR-0018 as amended by ADR-0026 item 8), on the entry gate: an
    item whose cell's PROVEN standard carries no active sign-off stops BEFORE ANY SPEND,
    whether or not delivery is on — nothing is authored, built or reviewed — with its own
    status and the entry gate's one event (on by default). A second approver's per-run
    override lifts this clause and no other, and the pull request says which licence opened
    it: a signed cell, the override, or a deployment that does not require a signed cell."""

    @staticmethod
    def _nothing_spent(rig: Rig) -> None:
        assert rig.builder.calls == 0 and not rig.author.calls
        kinds = rig.kinds("I-1")
        assert fe.EV_RED_PROOF not in kinds and fe.EV_BUILD not in kinds
        assert fe.EV_DELIVERY not in kinds and not rig.pushes and not rig.prs

    UNSIGNED_S2 = Readers(standard_for=lambda cell: Standard(ARM_S2, signed=False))
    SIGNED_S2 = Readers(standard_for=lambda cell: Standard(ARM_S2, signed=True))

    def test_the_clause_is_on_by_default(self) -> None:
        assert fl.FactorySpec.__dataclass_fields__["require_signed_cell"].default is True

    @pytest.mark.parametrize("deliver", [True, False], ids=["delivery-on", "delivery-off"])
    def test_an_unsigned_standard_stops_before_any_spend(
        self, pyrepo: pr.PyRepo, tmp_path: Path, deliver: bool
    ) -> None:
        rig = _rig(pyrepo, tmp_path, deliver=deliver, creds=_creds(), readers=self.UNSIGNED_S2)
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_UNSIGNED_CELL == "unsigned_cell"
        assert out.proof is None and not out.builds and out.delivery is None
        self._nothing_spent(rig)
        (refused,) = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)
        assert refused.payload["code"] == "unsigned_cell"
        emitted = [e for e in rig.sink.events if e.action == "entry.refused"]
        assert len(emitted) == 1 and emitted[0].status is StepStatus.SKIPPED
        assert emitted[0].payload["code"] == "unsigned_cell"
        assert not [e for e in rig.sink.events if e.action == "delivery.override"]
        assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha

    def test_a_signed_standard_is_built_and_delivered_and_the_pull_request_says_which_licence(
        self, pyrepo: pr.PyRepo, tmp_path: Path
    ) -> None:
        rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), readers=self.SIGNED_S2)
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
        assert len(rig.pushes) == 1 and len(rig.prs) == 1
        assert not [e for e in rig.sink.events if e.action == "entry.refused"]
        body = rig.prs[0]["body"]
        assert (
            "- licence: **signed cell** — the cell's proven standard (`S2`) carries an active "
            "sign-off" in body
        )

    def test_the_setting_removes_this_clause_and_only_this_clause(
        self, pyrepo: pr.PyRepo, tmp_path: Path
    ) -> None:
        """``require_signed_cell=False`` (``CRB_FACTORY__REQUIRE_SIGNED_CELL=false``): the same
        unsigned standard is built and delivered, and the pull request says no person signed
        it. The route clause still stands."""
        rig = _rig(
            pyrepo,
            tmp_path,
            deliver=True,
            creds=_creds(),
            require_signed_cell=False,
            readers=self.UNSIGNED_S2,
        )
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
        assert len(rig.prs) == 1
        assert (
            "- licence: **unsigned cell** — this deployment does not require a signed cell"
            in rig.prs[0]["body"]
        )
        routed_human = _rig(
            pyrepo,
            tmp_path / "h",
            deliver=True,
            creds=_creds(),
            require_signed_cell=False,
            readers=self.UNSIGNED_S2,
            route_decision_for=lambda item: HUMAN_ROUTE,
        )
        out = routed_human.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.delivery is None and not routed_human.prs

    def test_an_approver_may_lift_the_clause_for_one_run_and_is_named_for_it(
        self, pyrepo: pr.PyRepo, tmp_path: Path
    ) -> None:
        rig = _rig(
            pyrepo,
            tmp_path,
            deliver=True,
            creds=_creds(),
            readers=self.UNSIGNED_S2,
            deliver_override_by="approver:ada",
        )
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
        lifted = [
            e.payload
            for e in rig.evidence.events_for("I-1", fe.EV_ROUTE)
            if e.payload.get("override_by") == "approver:ada"
        ]
        assert len(lifted) == 1
        assert "sign-off clause lifted by approver:ada for this run" in lifted[0]["reason"]
        # recorded at the entry gate, before anything was spent
        kinds = rig.kinds("I-1")
        assert kinds.index(fe.EV_ROUTE) < kinds.index(fe.EV_RED_PROOF) < kinds.index(fe.EV_BUILD)
        assert not [e for e in rig.sink.events if e.action == "entry.refused"]
        # and the reader who merges it is never told a person signed the cell
        assert (
            "- licence: **unsigned cell** — opened under a per-run override of the sign-off "
            "clause by approver `approver:ada`, not a human attestation of the cell"
            in rig.prs[0]["body"]
        )

    def test_the_clause_leaves_a_cell_that_routes_elsewhere_to_the_route_clause(
        self, pyrepo: pr.PyRepo, tmp_path: Path
    ) -> None:
        """A signed standard in a cell that does not route ``deliver`` is the ROUTE clause's:
        it is built, and delivery is refused with the route's own code — the clauses are not
        interchangeable."""
        rig = _rig(
            pyrepo,
            tmp_path,
            deliver=True,
            creds=_creds(),
            readers=self.SIGNED_S2,
            route_decision_for=lambda item: HUMAN_ROUTE,
        )
        out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
        assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
        ev = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[0].payload
        assert ev["reason"].startswith("route gate:") and ev["reason_code"] == "oracle_weak"


# --- the one-run override: a second approver, never on false-Q1 (GOV-1, GOV-4) ------


def test_no_override_lifts_anything_on_a_false_q1_cell(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """GOV-1 (governance review 2026-09-27) under ADR-0026 item 8: false-Q1 = 0 is the honesty
    floor. A sign-off can never lift a false-Q1 cell (``NON_OVERRIDABLE_REFUSALS``), and
    neither can the one-run override of the sign-off clause: the refusal on the chain names
    the floor and the approver whose override it refused, and the item stops unsigned before
    any spend — nothing built, nothing pushed."""
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: FALSE_Q1_ROUTE,
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_UNSIGNED_CELL and out.delivery is None
    assert not out.builds and not rig.pushes and not rig.prs
    (refused,) = _override_refusals(rig)
    assert refused["override_refused"] == "false_q1" and refused["override_by"] == "approver:ada"
    assert "false-Q1" in refused["reason"] and "no override" in refused["reason"]
    assert not _lifted(rig)  # nothing was lifted
    # a cell whose summary carries a false-Q1 row is held to the floor whatever its word
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: {**HUMAN_ROUTE, "false_q1": 2},
        deliver_override_by="approver:ada",
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_UNSIGNED_CELL and not rig2.prs
    assert _override_refusals(rig2)[-1]["override_refused"] == "false_q1"


def test_the_sign_off_override_is_never_the_runs_own_actor(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-4 under ADR-0026 item 8: the override lifts the sign-off clause, so — like a
    sign-off (ADR-0016) — it is never granted by the actor of the run that produces the
    evidence. The loop refuses it at the entry gate and records the refusal; an override read
    live at the gate (a second approver's act while the run works) is honoured, lifts only
    the sign-off, and never opens a pull request the route gate withholds."""
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
        deliver_override_by="tester",  # the rig's run actor
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_UNSIGNED_CELL and not out.builds and not rig.prs
    (refused,) = _override_refusals(rig)
    assert refused["override_refused"] == "same_actor" and refused["override_by"] == "tester"
    # the live seam: nobody granted when the loop was made, a second approver before the gate
    grants: list[str] = []
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: HUMAN_ROUTE,
        deliver_override_for=lambda: grants[-1] if grants else "",
    )
    loop2 = rig2.loop()
    grants.append("approver:grace")
    out2 = loop2.run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_ACCEPTED and out2.builds  # the sign-off was lifted
    (lifted,) = _lifted(rig2)
    assert lifted["override_by"] == "approver:grace"
    # ... and only the sign-off: the route gate still withholds the pull request
    assert out2.delivery is None and not rig2.prs
    # the live seam naming the run's actor is refused the same way
    rig3 = _rig(
        pyrepo,
        tmp_path / "c",
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
        deliver_override_for=lambda: "tester",
    )
    out3 = rig3.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out3.status == fl.STATUS_UNSIGNED_CELL and not rig3.prs
    assert _override_refusals(rig3)[-1]["override_refused"] == "same_actor"


def test_the_override_is_refused_when_any_cell_the_size_rule_reads_carries_false_q1(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-1 over every cell the size rule reads (Wave 4 attack): the override lifts the
    sign-off clause on the estimate cell AND the next larger one, so the honesty floor is
    read on both — a false-Q1 row in the next larger cell refuses it, on the chain, and the
    item stops unsigned before any spend."""
    reads: list[str] = []

    def route_for(item: BacklogItem) -> dict[str, Any]:
        reads.append(item.size_estimate)
        return DELIVER_ROUTE if item.size_estimate == "XS" else FALSE_Q1_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=UNSIGNED,
        require_signed_cell=True,
        route_decision_for=route_for,
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert "S" in reads  # the next larger cell's route was read
    assert out.status == fl.STATUS_UNSIGNED_CELL and not out.builds and not rig.prs
    (refused,) = _override_refusals(rig)
    assert refused["override_refused"] == "false_q1" and refused["override_by"] == "approver:ada"
    assert not _lifted(rig)


# --- the delivered cell's own sign-off and licence line (P-391) ---------------------


def test_a_change_larger_than_its_estimate_is_delivered_only_into_a_signed_cell(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-391 (the Wave 4 attack): the entry gate checks the signatures of the cells the size
    rule reads from the ESTIMATE (XS and S for an XS ticket); a change that measures larger
    lands in a cell nobody may have signed. With the clause on, the delivered change's own
    cell must carry an active sign-off too — or the item stops ``unsigned_cell`` at delivery,
    with both sizes on the chain — and the pull request's licence line is the DELIVERED
    cell's, never the estimate's."""
    edit, oracle = _padded(40)
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=_signed_only("XS", "S"),
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
    )
    out = rig.loop().run_item(multiply_item(), authored=oracle)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert measured not in ("XS", "S", "")  # the change lands beyond the cells signed
    assert out.status == fl.STATUS_UNSIGNED_CELL and out.delivery is None
    assert not rig.pushes and not rig.prs
    (refused,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    ev = refused.payload
    assert ev["reason_code"] == "unsigned_cell"
    assert ev["estimate"] == "XS" and ev["measured"] == measured
    assert f"bug.fix {measured}" in ev["reason"] and "no active sign-off" in ev["reason"]
    # a second approver's override lifts that clause at delivery too — and the pull request
    # says so, naming the delivered cell's licence, never "signed cell"
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=_signed_only("XS", "S"),
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
        deliver_override_by="approver:ada",
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=oracle)
    assert out2.status == fl.STATUS_ACCEPTED and out2.delivery is not None
    body = rig2.prs[0]["body"]
    assert "**signed cell**" not in body
    assert (
        "- licence: **unsigned cell** — opened under a per-run override of the sign-off "
        "clause by approver `approver:ada`" in body
    )
    (delivered,) = rig2.evidence.events_for("I-1", fe.EV_DELIVERY)
    assert delivered.payload["licence"]["override_by"] == "approver:ada"
    # the override is still refused for the run's own actor at delivery
    rig3 = _rig(
        pyrepo,
        tmp_path / "c",
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=_signed_only("XS", "S"),
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
        deliver_override_by="tester",
    )
    out3 = rig3.loop().run_item(multiply_item(), authored=oracle)
    assert out3.status == fl.STATUS_UNSIGNED_CELL and not rig3.prs
    (ev3,) = rig3.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    assert ev3.payload["override_refused"] == "same_actor"
    # a delivered cell that IS signed says so, quoting its own standard
    rig4 = _rig(
        pyrepo,
        tmp_path / "d",
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=_signed_only("XS", "S", measured),
        require_signed_cell=True,
        route_decision_for=lambda item: DELIVER_ROUTE,
    )
    out4 = rig4.loop().run_item(multiply_item(), authored=oracle)
    assert out4.status == fl.STATUS_ACCEPTED and len(rig4.prs) == 1
    assert "- licence: **signed cell**" in rig4.prs[0]["body"]


def test_the_licence_line_is_the_delivered_cells_not_the_estimates(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-391: with the clause off, a change delivered into an unsigned larger cell is never
    described as a signed cell because its ESTIMATE cell happened to be signed."""
    edit, oracle = _padded(40)
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=_signed_only("XS", "S"),
        require_signed_cell=False,
        route_decision_for=lambda item: DELIVER_ROUTE,
    )
    out = rig.loop().run_item(multiply_item(), authored=oracle)
    assert out.status == fl.STATUS_ACCEPTED and len(rig.prs) == 1
    body = rig.prs[0]["body"]
    assert "**signed cell**" not in body
    assert "- licence: **unsigned cell** — this deployment does not require a signed cell" in body
