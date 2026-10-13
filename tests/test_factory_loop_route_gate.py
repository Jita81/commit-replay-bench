"""crb.factory.loop — the route gate: one reading of the map, read on the change's measured cell.

Navigation
----------
What it is:   The factory loop's route-gate tests, moved out of tests/test_factory_loop.py so the
              suite's shards stay inside their time budget (files are the shard unit).
What it does: Pins that a clean, reviewed build in a cell that does not route ``deliver``, or in
              no measured cell, opens no pull request and names the measured route on the chain
              (DL-038), that an approver's override never lifts the route gate, that the map is
              read ONCE per item at readiness, before any build, and that this one reading gates
              the delivery and is quoted in the pull-request body (DL-045), and that the licence
              is the MEASURED cell's whichever way the size moved: a larger change is withheld
              ``size_exceeds_licence``, a smaller one on its own cell's reason, and a larger one
              is delivered when its measured cell routes ``deliver`` (GOV-2, P-335).
How:          The ``Rig`` and ``_rig`` harness of tests/test_factory_loop.py over ``pyrepo``, with
              ``route_decision_for`` scripted per size and a builder edit padded past XS.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/factory/loop.py (under test), src/crb/factory/standard.py (the measured
              cell's licence), src/crb/factory/delivery.py (the pull-request body that quotes
              the reading), tests/test_factory_loop.py (the shared harness),
              tests/test_factory_loop_signed_cell.py (the sign-off clause the override lifts)
Tested by:    tests/test_factory_loop_route_gate.py
Touch when:   never for a new repository; the route gate, the one-reading rule (DL-045) or the
              measured cell's licence changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import readiness as rd
from crb.factory.backlog import BacklogItem
from fixtures import pyrepo as pr
from test_factory_build import MULTIPLY_HARDCODED, authored_multiply, multiply_item
from test_factory_loop import (
    DELIVER_ROUTE,
    FALSE_Q1_ROUTE,
    HUMAN_ROUTE,
    S2_EVERYWHERE,
    STRONGER_MULTIPLY,
    MultiBuilder,
    Rig,
    _creds,
    _padded,
    _rig,
)

# --- the route gate (DL-038) --------------------------------------------------------


def test_route_gate_withholds_delivery_when_the_cell_does_not_route_deliver(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The capability map decides what the factory may deliver: a clean build in a cell
    that routes `human` is built, graded and reviewed, but no branch is pushed and no PR
    opened; the withholding names the measured route on the evidence chain."""
    rig = _rig(
        pyrepo, tmp_path, deliver=True, creds=_creds(), route_decision_for=lambda item: HUMAN_ROUTE
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None  # reviewed, not delivered
    assert not rig.pushes and not rig.prs
    refused = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    assert len(refused) == 1
    ev = refused[0].payload
    assert ev["reason"].startswith("route gate: the cell routes human (oracle_weak)")
    assert ev["measured_route"] == "human" and ev["reason_code"] == "oracle_weak"
    assert ev["policy_version"] == "routing.v1"
    assert fe.EV_DELIVERY not in rig.kinds("I-1")
    assert pyrepo.repo.rev_parse("main") == pyrepo.docs_sha


def test_route_gate_withholds_delivery_when_nothing_is_measured(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(pyrepo, tmp_path, deliver=True, creds=_creds(), route_decision_for=None)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    ev = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[0].payload
    assert "no capability-map route" in ev["reason"] and ev["measured_route"] == ""


def test_route_gate_is_not_lifted_by_an_approvers_override(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """ADR-0026 item 8: ``deliver_override`` lifts the sign-off clause and nothing else — a
    cell whose route is not ``deliver`` still opens no pull request, override or not."""
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        route_decision_for=lambda item: HUMAN_ROUTE,
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    ev = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[0].payload
    assert ev["reason"].startswith("route gate: the cell routes human")


# --- the measured cell's licence (GOV-2, P-335) -------------------------------------


def test_a_change_larger_than_its_licence_is_withheld_size_exceeds_licence(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-2 (governance review 2026-09-27): the route gate read the cell of the item's
    DECLARED size (a ticket's story points); the build's row records the MEASURED size of
    the diff. A cell licensed for XS changes never licenses a larger one: the measured cell
    is read (from the same pre-run map) and, when it does not route ``deliver``, the item
    is withheld ``size_exceeds_licence`` with both sizes on the chain."""
    edit, oracle = _padded(12)
    reads: list[str] = []

    def route_for(item: BacklogItem) -> dict[str, Any] | None:
        reads.append(item.size_estimate)
        return DELIVER_ROUTE if item.size_estimate == "XS" else HUMAN_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=S2_EVERYWHERE,
        route_decision_for=route_for,
    )
    item = multiply_item()
    assert item.size_estimate == "XS"
    out = rig.loop().run_item(item, authored=oracle)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert measured not in ("XS", "")  # the change that would be delivered is larger
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    assert reads == ["XS", measured]  # the declared cell at readiness, the measured one after
    (refused,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    ev = refused.payload
    assert ev["reason_code"] == "size_exceeds_licence"
    assert ev["size_estimate"] == "XS" and ev["size_measured"] == measured
    assert ev["measured_route"] == "human"
    # no override stretches an XS route over the measured cell's refusal (ADR-0026 item 8:
    # an override lifts the sign-off clause only, never the route gate)
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=S2_EVERYWHERE,
        route_decision_for=lambda item: (
            DELIVER_ROUTE if item.size_estimate == "XS" else FALSE_Q1_ROUTE
        ),
        deliver_override_by="approver:ada",
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=oracle)
    assert out2.delivery is None and not rig2.prs


def test_a_change_smaller_than_its_estimate_is_licensed_by_its_own_measured_cell(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-335: the route gate re-read the measured cell only when the change measured LARGER
    than its estimate, so a change estimated S that measured XS was delivered on the S
    cell's route although the XS cell — the change's own — routed ``human`` (a weak oracle
    there). ``manufacture-and-deliver.truth.16`` and ADR-0025 item 12 name the measured
    cell's route whatever the direction: a smaller change whose cell does not route
    ``deliver`` is withheld with both sizes and the measured cell's own reason."""
    reads: list[str] = []

    def route_for(item: BacklogItem) -> dict[str, Any] | None:
        reads.append(item.size_estimate)
        return DELIVER_ROUTE if item.size_estimate == "S" else HUMAN_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        readers=S2_EVERYWHERE,
        route_decision_for=route_for,
    )
    out = rig.loop().run_item(multiply_item(size_estimate="S"), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED, (out.status, out.error)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert measured == "XS"  # the change that would be delivered is smaller
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is None
    assert not rig.pushes and not rig.prs
    assert reads == ["S", "XS"]  # the declared cell at readiness, the measured one after
    (refused,) = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)
    ev = refused.payload
    assert ev["reason_code"] == "oracle_weak" and ev["measured_route"] == "human"
    assert ev["size_estimate"] == "S" and ev["size_measured"] == "XS"
    # the same change in a measured cell that routes deliver is delivered
    rig2 = _rig(
        pyrepo,
        tmp_path / "b",
        deliver=True,
        creds=_creds(),
        readers=S2_EVERYWHERE,
        route_decision_for=lambda item: DELIVER_ROUTE,
    )
    assert (
        rig2.loop()
        .run_item(multiply_item(size_estimate="S"), authored=authored_multiply())
        .delivery
        is not None
    )
    assert len(rig2.prs) == 1


def test_a_larger_change_is_delivered_when_its_measured_cell_routes_deliver(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """GOV-2: the licence is the measured cell's — when it routes ``deliver`` the pull
    request opens, its body names both sizes and quotes the measured cell's route."""
    edit, oracle = _padded(12)
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        builder=MultiBuilder(first_edit=edit),
        readers=S2_EVERYWHERE,
        route_decision_for=lambda item: {
            **DELIVER_ROUTE,
            "n": 30 if item.size_estimate != "XS" else 12,
        },
    )
    out = rig.loop().run_item(multiply_item(), authored=oracle)
    measured = [r for r in rig.ledger.rows() if r.clean][-1].size
    assert out.delivery is not None and len(rig.prs) == 1
    body = rig.prs[0]["body"]
    assert (
        f"- size: estimated `XS`, measured `{measured}` — licensed on the (`bug.fix`, "
        f"`{measured}`) cell" in body
    )
    assert "- route: **deliver**" in body


# --- one reading of the map per item, at readiness (DL-045) -------------------------


def test_route_is_read_once_per_item_at_readiness_before_any_build(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """DL-045 (B-1b finding 2): the map that licenses a delivery is the map as it stood
    BEFORE the run — read once per item at readiness, never after the item's own row has
    landed; the gate and the PR body use that one reading, and the ``route.decided`` event
    records it (n, point, ci_low, false_q1, apparatus) so the chain quotes the pre-run map."""
    rig_holder: dict[str, Rig] = {}
    calls: list[tuple[str, int]] = []  # (item id, builder calls so far at the time of the read)

    def route_for(item: BacklogItem) -> dict[str, Any]:
        calls.append((item.id, rig_holder["rig"].builder.calls))
        return DELIVER_ROUTE

    rig = _rig(
        pyrepo,
        tmp_path,
        builder=MultiBuilder(first_edit=MULTIPLY_HARDCODED),  # forces one rework
        rework_test=lambda item, verdict, previous: STRONGER_MULTIPLY,  # a CHANGED oracle
        deliver=True,
        creds=_creds(),
        route_decision_for=route_for,
    )
    rig_holder["rig"] = rig
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.reworks == 1 and out.delivery is not None
    # exactly one read, before the first build — and NOT again for the rework's delivery
    assert calls == [("I-1", 0)] and rig.builder.calls == 2
    # the reading is on the chain, in the readiness route event, summarised
    (route,) = rig.evidence.events_for("I-1", fe.EV_ROUTE)
    assert route.payload["route"] == rd.ROUTE_BUILD
    assert route.payload["cell_route"] == {
        "route": "deliver",
        "reason": DELIVER_ROUTE["reason"],
        "reason_code": "deliver",
        "n": 12,
        "point": 1.0,
        "ci_low": 0.76,
        "false_q1": 0,
        "policy_version": "routing.v1",
        "apparatus_versions": ["2.2"],
        "verification_tier": "human-verified",
    }
    kinds = rig.kinds("I-1")
    assert kinds.index(fe.EV_ROUTE) < kinds.index(fe.EV_RED_PROOF) < kinds.index(fe.EV_BUILD)
    # the PR body quotes that reading
    assert "route: **deliver** — n=12 point=1.000 ci_low=0.76 false_q1=0" in rig.prs[0]["body"]
    emitted = [e for e in rig.sink.events if e.action == "route.decided"]
    assert len(emitted) == 1 and emitted[0].payload["cell_route"]["n"] == 12


def test_route_read_once_is_what_gates_delivery_even_if_the_map_moves_later(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A map that would say `human` after the build cannot reach the gate: the decision the
    item carries is the one taken at readiness (and an unmeasured cell is recorded as
    ``cell_route: None``)."""
    answers = iter([DELIVER_ROUTE, HUMAN_ROUTE, HUMAN_ROUTE])
    rig = _rig(
        pyrepo,
        tmp_path,
        deliver=True,
        creds=_creds(),
        route_decision_for=lambda item: next(answers),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None and len(rig.prs) == 1
    # the reverse: nothing measured at readiness → withheld, and the chain says so
    rig2 = _rig(pyrepo, tmp_path / "b", deliver=True, creds=_creds(), route_decision_for=None)
    out2 = rig2.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_ACCEPTED and out2.delivery is None
    (route,) = rig2.evidence.events_for("I-1", fe.EV_ROUTE)
    assert route.payload["cell_route"] is None
