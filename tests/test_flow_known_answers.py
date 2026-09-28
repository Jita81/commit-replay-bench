"""Every figure the flow reading serves, pinned to a known answer — so no fold can drift unseen.

The class this gate closes (P-143): a flow figure was flipped ``met`` on tests that asserted
only its shape — ``n == 1``, ``median_s is not None``, ``"n ="`` somewhere in a tile — so a
fold could time to the wrong end point (a cell's last row for its tenth, "now" for a
signature), report 0 s, pair a stamp of another scope or another cell, or divide the wrong
money, and every cited test still passed. Here ONE fixture gives every milestone pair of every
stream stamps this test chose, with a decoy for each way a pairing can go wrong (another cell,
another scope, another repository, a stamp after the end, a row after the tenth), and asserts
the whole reading against a table of hand-computed answers. Two ratchets keep it whole:

* a lead time the reading serves that the table does not name fails (a new figure must arrive
  with its known answer), and a table key the reading no longer serves fails too;
* every lead time is compared on ``(n, median_s, min_s, max_s)``, and every cost per unit on
  its value, so any fold that moves an end point, pools across a scope or reads a floor as the
  whole bill changes a number here.

Navigation
----------
What it is:   The known-answer gate over ``crb.server.flow.build_flow`` — the prevention
              artefact for "a flow figure evidenced without its value" (P-143) and for "a flow
              pairing that pools what the map splits" recurring in a fold P-138 did not cover.
What it does: Builds one store with chosen stamps (install, health, registration, controls,
              runs, graded rows, deliver stamps in and out of scope, reviews, a recovery, a
              factory chain, probes, qualifies, mine / oracle / controls runs and a prevention
              register with a decoy verdict), folds it, and compares every served lead time
              and cost per unit with ``KNOWN`` / ``KNOWN_PER_UNIT``.
How:          ``make_factory`` + install events first (so the install is observed), then
              ``seed`` + ``add_users``; events, runs and reviews through the ORM and the review
              ledger; rows, sign-off records and factory events handed to ``build_flow``
              directly (they are its arguments), with ``admin=True``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0028-the-moments-flow-needs-are-recorded.md
Works with:   src/crb/server/flow.py (the folds under test), src/crb/core/flow.py (the
              arithmetic), src/crb/server/flow_record.py (the scoped deliver stamps),
              tests/fixtures/server_seed.py (the seed and users), tests/test_server_routes_flow.py
              (the route-level cases), docs/PREVENTION.md (P-143, P-144)
Tested by:    tests/test_flow_known_answers.py
Touch when:   never for a new repository; a stream gains or changes a milestone pair or a cost per
              unit — add or change its row in ``KNOWN`` with the stamps that produce it, never
              loosen a comparison.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from crb.core.context_arm import LABEL_CONTEXT_ARM
from crb.core.flow import LeadTime
from crb.core.ledger import (
    FAILURE_PROTOCOL,
    LABEL_COST_KNOWN,
    LABEL_FAILURE_KIND,
    PROCESS_FACTORY,
    GradeRow,
    labels_at_apparatus,
)
from crb.core.prevention import MemoryPreventionStore, PreventionRecord, Register, build_register
from crb.core.review import ReviewRecord
from crb.core.signoff import Attestation, SignoffRecord
from crb.core.version import APPARATUS_VERSION
from crb.factory.evidence import (
    EV_BACKLOG_EVOLVED,
    EV_BACKLOG_FROZEN,
    EV_DELIVERY,
    EV_DELIVERY_MERGED,
    EV_RED_REFUSED,
    FactoryEvent,
)
from crb.server.flow import build_flow
from crb.server.flow_record import scope_key
from crb.store.ledger import DbReviewLedger
from crb.store.models import Event, Run, User
from fixtures.server_seed import ALPHA, BETA, add_users, make_factory, seed, user_id

#: Every lead time the reading serves: ``key → (n, median_s, min_s, max_s)``, computed by hand
#: from the stamps below.
KNOWN: dict[str, tuple[int, float | None, float | None, float | None]] = {
    # registered 08:00 → the first PASSED controls report 09:00 (an escaped one at 08:30, an
    # unwitnessed controls.v2 one at 08:45)
    "registered_to_controls": (1, 3600.0, 3600.0, 3600.0),
    # registered 08:00 → the first probe that finished GREEN at 08:40 (a failed one at 08:10,
    # one that succeeded without green at 08:30, a later green one at 09:30)
    "registered_to_probe_green": (1, 2400.0, 2400.0, 2400.0),
    # step 2: the first red probe after registration 08:10 → the first qualify that qualified
    # a task 09:10 (one that qualified nothing at 08:20; the seed's probe of 2026-08-25
    # predates registration and never starts it)
    "step_2_span": (1, 3600.0, 3600.0, 3600.0),
    # two succeeded mine runs of 5 and 20 minutes; a failed one of 2 hours never counts
    "mine_run": (2, 750.0, 300.0, 1200.0),
    # one succeeded oracle run of 30 minutes (the seed's has no start stamp: never timed)
    "oracle_run": (1, 1800.0, 1800.0, 1800.0),
    # one succeeded controls run of 10 minutes
    "controls_run": (1, 600.0, 600.0, 600.0),
    # the network class first seen 07:00 → its change's first decided look 11:00 (a decided
    # record at 10:00 names it under a change that does not target it, and a later look at
    # 12:00 is not the first)
    "finding_to_remeasurement": (1, 14400.0, 14400.0, 14400.0),
    # run A queued 09:50, last row 10:11 (21 min); run B queued 10:15, last row 10:22 (7 min)
    "queued_to_graded": (2, 840.0, 420.0, 1260.0),
    # cell A's first row 10:00 → its TENTH 10:09 (it has twelve); the split cell never counts
    "first_row_to_bar": (1, 540.0, 540.0, 540.0),
    # the attested row graded 10:00 → signed 12:00
    "accepted_to_signed": (1, 7200.0, 7200.0, 7200.0),
    # the cell first routed deliver in the record's scope at 11:00 → signed 12:00
    "routed_deliver_to_signed": (1, 3600.0, 3600.0, 3600.0),
    # two reviews stated 12 and 30 minutes; a third stated nothing
    "review_minutes": (2, 1260.0, 720.0, 1800.0),
    # item I-1: registered 09:00 → PR opened 10:00 → merged 12:00
    "registered_to_pr": (1, 3600.0, 3600.0, 3600.0),
    "pr_to_merged": (1, 7200.0, 7200.0, 7200.0),
    "registered_to_merged": (1, 10800.0, 10800.0, 10800.0),
    # refusal 09:00 → the evolution that supersedes it 09:45
    "refusal_to_strengthening": (1, 2700.0, 2700.0, 2700.0),
    # an admin reset viewer1 at 10:00 → viewer1 signed in 10:30
    "password_set_to_signed_in": (1, 1800.0, 1800.0, 1800.0),
    # installed 10:00 → first green /health 10:45
    "installed_to_healthy": (1, 2700.0, 2700.0, 2700.0),
}

#: Every cost per unit the reading serves: ``stream → per_unit`` ($).
KNOWN_PER_UNIT: dict[str, float | None] = {
    # cell A's FIRST TEN rows at $0.01 — not its eleventh (unpriced) or twelfth ($1), not the
    # thin cell's $15
    "measure": 0.10,
    # one factory row at $2 over one merged pull request
    "manufacture-and-deliver": 2.0,
}

DAY = "2026-09-01"
POSTURE = "local/inplace/host-env"
ARM = "off"
RUN_A, RUN_B = "e1" * 16, "e2" * 16


def at(hhmm: str) -> str:
    return f"{DAY}T{hhmm}:00+00:00"


def graded(
    base: GradeRow,
    *,
    hhmm: str,
    cost: float | None,
    run_id: str,
    capability_class: str = "bug.fix",
    apparatus: str = APPARATUS_VERSION,
    process_step: str | None = None,
) -> GradeRow:
    labels = {**base.labels, LABEL_COST_KNOWN: "false" if cost is None else "true"}
    if process_step == PROCESS_FACTORY:  # a factory row's context arm is its test author's
        labels[LABEL_CONTEXT_ARM] = "S1@fixture-author"
    return dataclasses.replace(
        base,
        run_id=run_id,
        capability_class=capability_class,
        size="S",
        apparatus_version=apparatus,
        mode="sighted",
        created=at(hhmm),
        cost_usd=cost or 0.0,
        labels=labels_at_apparatus(labels, apparatus),
        process_step=process_step or base.process_step,
        row_hash=f"{run_id[:4]}-{capability_class}-{apparatus}-{hhmm}".ljust(64, "0"),
    )


def event(s: Session, n: int, action: str, ts: str, payload: dict[str, Any], **kw: Any) -> None:
    s.add(
        Event(
            event_id=f"{n:032x}",
            trace_id="k" * 32,
            seq=n,
            timestamp=ts,
            stage="system",
            action=action,
            status="ok",
            payload_json=payload,
            **kw,
        )
    )


def stamp(s: Session, n: int, ts: str, repo: str, cls: str, **scope: str) -> None:
    full = {"apparatus": APPARATUS_VERSION, "posture_class": POSTURE, "checks_arm": ARM, **scope}
    payload = {"capability_class": cls, "size": "S", "moment": "observed", **full}
    event(s, n, "cell.routed_deliver", ts, {**payload, "scope": scope_key(full)}, repo=repo)


@pytest.fixture
def served(tmp_path: Path) -> dict[str, Any]:
    factory: sessionmaker[Session] = make_factory(tmp_path)
    with factory() as s:
        # the install, observed, before anything else is written
        event(s, 1, "deployment.installed", at("10:00"), {"moment": "observed"})
        event(s, 2, "deployment.first_healthy", at("10:45"), {"status": "ok"})
        s.commit()
    info = seed(factory)
    add_users(factory)
    base = info.rows[0]

    cell_a = [graded(base, hhmm=f"10:{i:02d}", cost=0.01, run_id=RUN_A) for i in range(10)]
    cell_a += [graded(base, hhmm="10:10", cost=None, run_id=RUN_A)]
    cell_a += [graded(base, hhmm="10:11", cost=1.0, run_id=RUN_A)]
    thin = [
        graded(base, hhmm=f"10:2{i}", cost=5.0, run_id=RUN_B, capability_class="docs.update")
        for i in range(3)
    ]
    # ten rows of one class — but five of apparatus 2.2: two cells of five, no bar
    split = [
        graded(
            base,
            hhmm=f"10:3{i}",
            cost=0.0 if i else None,
            run_id="e3" * 16,
            capability_class="test.add",
            apparatus="2.2" if i % 2 else APPARATUS_VERSION,
        )
        for i in range(10)
    ]
    factory_row = graded(
        base, hhmm="11:30", cost=2.0, run_id="e4" * 16, process_step=PROCESS_FACTORY
    )
    rows = cell_a + thin + split + [factory_row]

    with factory() as s:
        n = 10
        # registration → controls: an escaped report first, then the first that passed
        event(s, n := n + 1, "repo.created", at("08:00"), {}, repo=ALPHA)
        v3 = {"controls_version": "controls.v3"}
        escaped = {"n_rows": 14, "escapes": 1, "not_constructible": 2, "passed": True, **v3}
        event(s, n := n + 1, "controls.report", at("08:30"), escaped, repo=ALPHA)
        # a clean report from before the gold witness (P-372) is not a pass either
        unwitnessed = {**escaped, "escapes": 0, "controls_version": "controls.v2"}
        event(s, n := n + 1, "controls.report", at("08:45"), unwitnessed, repo=ALPHA)
        passed = {"n_rows": 14, "escapes": 0, "not_constructible": 2, "passed": True, **v3}
        event(s, n := n + 1, "controls.report", at("09:00"), passed, repo=ALPHA)
        # the two measured runs, queued at chosen moments
        s.add(Run(id=RUN_A, repo=ALPHA, kind="replay", created=at("09:50")))
        s.add(Run(id=RUN_B, repo=ALPHA, kind="replay", created=at("10:15")))
        # the proving runs: probes, qualifies, mines, an oracle and a controls run
        for rid, kind, status, start, end, counts in (
            ("p1", "probe", "failed", "08:05", "08:10", {"green": False}),
            ("p2", "probe", "succeeded", "08:25", "08:30", {}),
            ("p3", "probe", "succeeded", "08:35", "08:40", {"green": True}),
            ("p4", "probe", "succeeded", "09:25", "09:30", {"green": True}),
            ("q1", "qualify", "succeeded", "08:15", "08:20", {"qualified": 0}),
            ("q2", "qualify", "succeeded", "09:05", "09:10", {"qualified": 2}),
            ("q3", "qualify", "succeeded", "09:40", "09:45", {"qualified": 5}),
            ("m1", "mine", "succeeded", "08:15", "08:20", {}),
            ("m2", "mine", "succeeded", "08:25", "08:45", {}),
            ("m3", "mine", "failed", "09:00", "11:00", {}),
            ("o1", "oracle", "succeeded", "09:00", "09:30", {}),
            ("c1", "controls", "succeeded", "08:50", "09:00", {}),
        ):
            s.add(
                Run(
                    id=rid.ljust(32, "0"),
                    repo=ALPHA,
                    kind=kind,
                    status=status,
                    created=at(start),
                    started=at(start),
                    finished=at(end),
                    counts_json=counts,
                )
            )
        # the true deliver stamp; every decoy is LATER and must never be the start
        stamp(s, n := n + 1, at("11:00"), ALPHA, "bug.fix")
        stamp(s, n := n + 1, at("11:10"), ALPHA, "docs.update")
        stamp(s, n := n + 1, at("11:20"), ALPHA, "bug.fix", apparatus="1.0")
        stamp(s, n := n + 1, at("11:25"), ALPHA, "bug.fix", posture_class="docker/gvisor/sealed")
        stamp(s, n := n + 1, at("11:30"), ALPHA, "bug.fix", checks_arm="on")
        stamp(s, n := n + 1, at("11:40"), BETA, "bug.fix")
        stamp(s, n := n + 1, at("12:30"), ALPHA, "bug.fix")
        # an admin recovers viewer1, who signs in 30 minutes later
        event(
            s,
            n := n + 1,
            "user.password_set",
            at("10:00"),
            {"target": user_id("viewer1")},
            actor=user_id("root"),
        )
        viewer = s.get(User, user_id("viewer1"))
        assert viewer is not None
        viewer.last_login = at("10:30")
        s.commit()

    reviews = DbReviewLedger(factory)
    for i, minutes in enumerate((12, None, 30)):
        r = info.rows[i]
        reviews.append(
            ReviewRecord(
                grade_row_hash=r.row_hash,
                repo=ALPHA,
                task_id=r.task_id,
                reviewer="op",
                statement="looked, could not review",
                verdict="not_reviewed",
                evidence_pack_hash=r.evidence_pack_hash,
                minutes=minutes,
            )
        )

    record = SignoffRecord(
        repo=ALPHA,
        capability_class="bug.fix",
        size="S",
        verifier="appr1",
        verified_at=at("12:00"),
        apparatus_version=APPARATUS_VERSION,
        checks_arm=ARM,
        posture_class=POSTURE,
        attestation=Attestation(
            reviewed_task_id=cell_a[0].task_id,
            reviewed_row_hash=cell_a[0].row_hash,
            statement="I read the accepted diff.",
            at=at("12:00"),
        ),
    )
    chain = [
        FactoryEvent(kind=EV_BACKLOG_FROZEN, created=at("09:00"), payload={"item_ids": ["I-1"]}),
        FactoryEvent(kind=EV_DELIVERY, item_id="I-1", created=at("10:00")),
        FactoryEvent(kind=EV_DELIVERY_MERGED, item_id="I-1", created=at("12:00")),
        FactoryEvent(kind=EV_RED_REFUSED, item_id="I-9", created=at("09:00")),
        FactoryEvent(
            kind=EV_BACKLOG_EVOLVED,
            item_id="I-10",
            created=at("09:45"),
            payload={"supersedes": "I-9"},
        ),
    ]
    with factory() as s:
        reading = build_flow(
            s,
            repo=ALPHA,
            rows=rows,
            signoffs=[record],
            factory_events=chain,
            admin=True,
            register=prevention_register(base),
        )
    return reading.to_dict()


#: The prevention class the register below carries: the network guard refusing ``go mod``.
NET_ERR = (
    "protocol violation: network: 'go' is not allowed (no network access) (attempted: go mod tidy)"
)
NET_SIG = "protocol:network:go mod"


def prevention_register(base: GradeRow) -> Register:
    """A register whose one class was first seen at 07:00, with a change applied to it at
    09:00 and decided at its first look at 11:00 — plus a decoy decided record at 10:00 that
    names the class under a change that does not target it, and a later look at 12:00."""
    refused = dataclasses.replace(
        graded(base, hhmm="07:00", cost=0.1, run_id="e5" * 16),
        clean=False,
        target_green=False,
        error=NET_ERR,
        labels={**base.labels, "builder_error": NET_ERR, LABEL_FAILURE_KIND: FAILURE_PROTOCOL},
        row_hash="net".ljust(64, "0"),
    )
    store = MemoryPreventionStore()
    for kind, created, payload in (
        (
            "applied",
            "09:00",
            {"change_id": "c-net", "lever_id": "line:T-NET", "targets": [NET_SIG]},
        ),
        ("applied", "09:30", {"change_id": "c-other", "lever_id": "x", "targets": ["other:x"]}),
        ("decided", "10:00", {"change_id": "c-other", "signature": NET_SIG, "verdict": "keep"}),
        ("decided", "11:00", {"change_id": "c-net", "signature": NET_SIG, "verdict": "continue"}),
        ("decided", "12:00", {"change_id": "c-net", "signature": NET_SIG, "verdict": "keep"}),
    ):
        store.append(PreventionRecord(kind=kind, repo=ALPHA, payload=payload, created=at(created)))
    records = store.records()
    return build_register([refused], records=records, repo=ALPHA)


def lead_times(body: dict[str, Any]) -> dict[str, LeadTime]:
    out: dict[str, LeadTime] = {}
    for stream in body["streams"]:
        for lt in stream["lead_times"]:
            assert lt["key"] not in out, f"two streams serve {lt['key']}"
            out[lt["key"]] = LeadTime(**lt)
    return out


def test_every_lead_time_the_reading_serves_has_a_known_answer(served: dict[str, Any]) -> None:
    assert set(lead_times(served)) == set(KNOWN)


def test_every_lead_time_is_its_known_answer(served: dict[str, Any]) -> None:
    got = {k: (lt.n, lt.median_s, lt.min_s, lt.max_s) for k, lt in lead_times(served).items()}
    assert got == KNOWN
    assert all(lt.dropped == 0 for lt in lead_times(served).values())


def test_every_cost_per_unit_is_its_known_answer(served: dict[str, Any]) -> None:
    got = {s["stream"]: s["per_unit"] for s in served["streams"] if s["per_unit_label"]}
    assert set(got) == set(KNOWN_PER_UNIT)
    assert got == pytest.approx(KNOWN_PER_UNIT)
