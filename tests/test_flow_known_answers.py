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
              factory chain), folds it, and compares every served lead time and cost per unit
              with ``KNOWN`` / ``KNOWN_PER_UNIT``.
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

from crb.core.flow import LeadTime
from crb.core.ledger import LABEL_COST_KNOWN, PROCESS_FACTORY, GradeRow
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
    # registered 08:00 → the first PASSED controls report 09:00 (an escaped one at 08:30)
    "registered_to_controls": (1, 3600.0, 3600.0, 3600.0),
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
    return dataclasses.replace(
        base,
        run_id=run_id,
        capability_class=capability_class,
        size="S",
        apparatus_version=apparatus,
        mode="sighted",
        created=at(hhmm),
        cost_usd=cost or 0.0,
        labels=labels,
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
        escaped = {"n_rows": 14, "escapes": 1, "not_constructible": 2, "passed": True}
        event(s, n := n + 1, "controls.report", at("08:30"), escaped, repo=ALPHA)
        passed = {"n_rows": 14, "escapes": 0, "not_constructible": 2, "passed": True}
        event(s, n := n + 1, "controls.report", at("09:00"), passed, repo=ALPHA)
        # the two measured runs, queued at chosen moments
        s.add(Run(id=RUN_A, repo=ALPHA, kind="replay", created=at("09:50")))
        s.add(Run(id=RUN_B, repo=ALPHA, kind="replay", created=at("10:15")))
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
            s, repo=ALPHA, rows=rows, signoffs=[record], factory_events=chain, admin=True
        )
    return reading.to_dict()


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
