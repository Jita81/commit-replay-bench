"""The decisions inbox derived on the server, and the clock over it (G-516).

Navigation
----------
What it is:   The test suite for ``crb.server.decisions`` (``decision_rows``, ``record_due``,
              ``age_seconds``) and ``GET /decisions``.
What it does: Pins that the derivation produces the same eight kinds and the same row
              identities the screen computes — the cell rows keyed ``<class>|<size>`` and the
              item rows keyed by item id — that a cell nobody has measured is not a decision,
              that a STALE sign-off puts its cell back in the inbox (ADR-0015), that "sign-off
              due" is the entry gate's reading of the cell's standard and never the map's tier
              — a cell the map reads earned but the gate unsigned asks, one the gate reads
              signed does not, in the derivation and over a real store (G-738), that the
              clock stamps ``first_due`` once and keeps it when a row goes away and comes
              back, that a row that stops being due is resolved rather than deleted, that a
              first stamp another reader committed meanwhile is joined rather than collided
              with (P-357), and that the route serves each row with its age, needs only a
              viewer and answers 404 for a repository nobody connected.
How:          The seeded server (``fixtures.server_seed``) for the route; hand-built
              ``CapabilityCell`` and ``TaskView`` objects for the derivation, so the rules
              are pinned without a ledger, with ``gate`` standing in for the entry gate's
              reader; the clock is moved by passing ``now`` rather than by sleeping.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0015-signoffs-expire-with-the-apparatus.md
Works with:   src/crb/server/decisions.py and src/crb/server/routes/decisions.py (under
              test), src/crb/factory/standard.py (``cell_signed``, the gate's reading),
              src/crb/store/models.py (``DecisionDue``),
              ui/src/screens/Decisions/decisions.ts (the screen's own derivation of the same
              rows — the kinds and keys pinned here are the join)
Tested by:    tests/test_server_decisions.py
Touch when:   never for a new repository; a human act is added to the product (a kind in
              both derivations).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from crb.core.capability import CapabilityCell
from crb.core.ledger import CellKey, CellStats
from crb.core.routing import RouteDecision, Shortfall
from crb.core.stats import Interval
from crb.factory.standard import STOP_UNSIGNED_CELL, CellRef, Standard, StandardFor, decide_entry
from crb.server import decisions as dec
from crb.server.factory_state import TaskView
from crb.server.routes.signoffs import posture_now
from crb.server.worker import DECISIONS_REFRESH_S
from crb.store.models import DecisionDue
from fixtures.server_seed import (
    ALPHA,
    BETA,
    DELIVER_CELL,
    Env,
    envelope,
    login,
    logout,
    make_env,
)
from fixtures.signoff_seed import attested_body, clear_policy


@pytest.fixture
def env(tmp_path: Path) -> Any:
    with make_env(tmp_path) as e:
        yield e


def cell(
    *,
    capability_class: str = "bug.fix",
    size: str = "S",
    route: str = "deliver",
    n: int = 12,
    tier: str | None = None,
    reason: str = "every bar cleared",
    reason_code: str = "deliver",
) -> CapabilityCell:
    """A (class x size) cell as the signed map hands it over."""
    key = CellKey(
        process_step="*",
        capability_class=capability_class,
        size=size,
        language="*",
        builder="*",
        model="*",
        provider="*",
    )
    if n <= 0:
        # honest-empty: no rows means no stats, no decision and no tier
        return CapabilityCell(
            key=key,
            projection=("capability_class", "size"),
            stats=None,
            decision=None,
            verification_tier=None,
            sigma=None,
            repos=0,
            rows=0,
            belt_sets=(),
            cost_known=False,
            latency_known=False,
        )
    stats = CellStats(
        cell=key,
        n=n,
        clean=n,
        disqualified=0,
        errors=0,
        false_q1=0,
        point=1.0,
        ci=Interval(0.8, 1.0),
        cost_usd_mean=0.0,
        latency_s_mean=0.0,
        oracle_strength_mean=0.9,
        apparatus_versions=("2.2",),
    )
    return CapabilityCell(
        key=key,
        projection=("capability_class", "size"),
        stats=stats,
        decision=RouteDecision(
            route=route,
            reason=reason,
            cell=key.to_dict(),
            n=n,
            point=1.0,
            ci_low=0.8,
            ci_high=1.0,
            false_q1=0,
            oracle_strength=0.9,
            policy_version="routing.v1",
            reason_code=reason_code,
        ),
        verification_tier=tier,
        sigma=0.0,
        repos=1,
        rows=n,
        belt_sets=("v5",),
        cost_known=False,
        latency_known=False,
    )


def replace_decision(c: CapabilityCell, **over: Any) -> CapabilityCell:
    """``c`` with its route decision's fields replaced."""
    assert c.decision is not None
    return dataclasses.replace(c, decision=dataclasses.replace(c.decision, **over))


def task(**over: Any) -> TaskView:
    base: dict[str, Any] = {
        "id": "I-1",
        "title": "Multiply",
        "capability_class": "bug.fix",
        "size": "XS",
        "kind": "code",
        "status": "pending",
        "outcome_reason": "",
        "dor_gaps": (),
        "route_hint": "build",
        "red_proof": None,
        "build_status": "not_started",
        "pr_url": None,
        "review_verdict": None,
        "last_event": "",
    }
    base.update(over)
    return TaskView(**base)


def gate(*signed: str, arm: str = "S2") -> StandardFor:
    """The entry gate's reader as ``decision_rows`` is handed it: a proven ``arm`` standard
    for every (class × size) cell, carrying an active sign-off for the ``<class>|<size>``
    keys named and for no other."""

    def standard_for(ref: CellRef) -> Standard:
        key = f"{ref.capability_class}|{ref.size}"
        return Standard(arm, signed=key in signed, reading_id="rdg_test")

    return standard_for


# --- the derivation -------------------------------------------------------------------


def test_the_cell_and_item_kinds_and_their_keys_are_the_ones_the_screen_computes() -> None:
    """The row identity is the join with the screen's own derivation: a cell row is keyed
    ``<class>|<size>`` and an item row by its item id (``decisions.ts``'s ``cellKeyOf`` and
    ``t.id``). The kinds and the order are that file's words too."""
    rows = dec.decision_rows(
        cells=[
            cell(route="do_not_ship", capability_class="feature.add", reason_code="false_q1"),
            cell(route="deliver"),  # measured, unsigned → an attestation is due
            cell(
                route="human",
                size="M",
                reason="the reading decided against the arm",
                reason_code="insufficient",
            ),
            cell(route="deliver", size="L"),  # the gate reads it signed: not a decision
            cell(
                route="calibrate", size="XL", n=0, reason_code="n_below_min"
            ),  # unmeasured: nobody is waiting
        ],
        tasks=[
            task(id="I-2", dor_gaps=("method_path", "response_shape")),
            task(id="I-3", route_hint="human"),
            task(id="I-4", review_verdict="accept_with_edit"),
            task(
                id="I-5",
                build_status="clean",
                status="accepted",
                last_event="delivery.refused",
            ),
        ],
        standard_for=gate("bug.fix|L"),
    )
    assert [(r.kind, r.key) for r in rows] == [
        ("do_not_ship", "feature.add|S"),
        ("gap_unsigned", "I-2"),
        ("signoff_due", "bug.fix|S"),
        ("rework", "I-4"),
        ("delivery_withheld", "I-5"),
        ("item_human", "I-3"),
        ("routed_human", "bug.fix|M"),
    ]
    by_kind = {r.kind: r for r in rows}
    assert by_kind["signoff_due"].role == "approver"
    assert by_kind["item_human"].role == "operator"
    assert by_kind["do_not_ship"].role == "viewer"
    assert "2 structural gaps" in by_kind["gap_unsigned"].title
    assert "decided against" in by_kind["routed_human"].title


def test_the_prevention_rows_carry_the_keys_the_screen_computes() -> None:
    """ADR-0020 §9: the prevention loop's three rows — a filed item nobody registered, a class
    that reopened, a change retired for harm — are decisions on the server too, keyed
    ``<signature>|owner|<item id>``, ``<signature>|reopened`` and ``<signature>|harm``
    (``decisions.ts``'s ``preventionDecisions``). A registered or product-scoped proposal is
    nobody's wait. Without this kind the clock would resolve a row the screen still shows."""
    sig = "protocol:network:go mod"
    register = {
        "entries": [
            {
                "signature": sig,
                "proposals": [
                    {"item_id": "P-1", "title": "Pin the module proxy", "scope": "repo"},
                    {"item_id": "P-2", "title": "Record a command", "scope": "product"},
                    {"item_id": "P-3", "title": "Done", "scope": "repo", "registered": {"x": 1}},
                ],
                "qualifiers": ["reopened"],
                "history": [{"kind": "decided", "summary": "harm"}],
            }
        ]
    }
    rows = dec.decision_rows(register=register)
    assert [(r.kind, r.key, r.role) for r in rows] == [
        ("prevention", f"{sig}|harm", "viewer"),
        ("prevention", f"{sig}|owner|P-1", "operator"),
        ("prevention", f"{sig}|reopened", "viewer"),
    ]
    assert rows[1].title == f"A prevention needs an owner — {sig}: Pin the module proxy"
    # between a withheld delivery and an item routed to a human, as the screen orders it
    assert dec.ORDER["delivery_withheld"] < dec.ORDER["prevention"] < dec.ORDER["item_human"]
    assert dec.decision_rows(register=None) == []


def test_a_stale_signoff_puts_its_cell_back_in_the_inbox() -> None:
    """ADR-0015: the entry gate reads a sign-off only while it was made on the apparatus the
    cell is read at, so a cell whose sign-off went stale reads unsigned to the gate — and so
    here, which is what a reader needs to see: somebody has to sign it again."""
    assert dec.decision_rows(cells=[cell()], standard_for=gate("bug.fix|S")) == []
    # the gate no longer reads it (stale, revoked, another reading since): a decision
    assert [r.kind for r in dec.decision_rows(cells=[cell()], standard_for=gate())] == [
        "signoff_due"
    ]


# --- G-738: "sign-off due" is the entry gate's reading, never the map's tier ----------


def test_a_cell_the_map_reads_earned_but_the_gate_reads_unsigned_is_a_sign_off_due() -> None:
    """G-738 (P-411): the map's overlay and the entry gate match sign-offs by two rules. A cell
    the overlay lifted to ``human-verified`` whose proven standard the gate reads unsigned
    still has its items stopped ``unsigned_cell`` — so a sign-off is due, and the inbox never
    reads "nothing is waiting" while the gate refuses to build."""
    earned = cell(tier="human-verified")
    assert earned.earned  # the map's rule says signed
    rows = dec.decision_rows(cells=[earned], repo="alpha", standard_for=gate())
    assert [(r.kind, r.key, r.role, r.act) for r in rows] == [
        ("signoff_due", "bug.fix|S", "approver", "Attest")
    ]


def test_a_cell_the_gate_reads_signed_is_no_sign_off_due_whatever_its_tier() -> None:
    """G-738, the converse: a sign-off the gate reads (an approver's attestation of one
    builder's cell, which never lifts the pooled map cell) licenses the cell's items, so the
    inbox does not ask for it again while the map's tier still reads ``automated-pass``."""
    unearned = cell(tier="automated-pass")
    assert not unearned.earned  # the map's rule says unsigned
    assert dec.decision_rows(cells=[unearned], standard_for=gate("bug.fix|S")) == []


def test_the_inbox_reads_signed_through_the_gates_own_predicate() -> None:
    """One rule (P-411): the gate's reader is asked for the cell's class and size, and its
    answer is read by the gate's own ``standard_signed`` — an ``S3`` ceiling licenses
    nothing even when signed, a cell with no proven standard is never signed, and a caller
    with no reader (no store) reads every deliver cell as unsigned, whatever its tier."""
    asked: list[CellRef] = []

    def ceiling(ref: CellRef) -> Standard:
        asked.append(ref)
        return Standard("S3", signed=True)

    rows = dec.decision_rows(cells=[cell(size="M")], standard_for=ceiling)
    assert [r.kind for r in rows] == ["signoff_due"] and asked == [CellRef("bug.fix", "M")]
    assert [r.kind for r in dec.decision_rows(cells=[cell()], standard_for=lambda ref: None)] == [
        "signoff_due"
    ]
    assert [r.kind for r in dec.decision_rows(cells=[cell(tier="human-verified")])] == [
        "signoff_due"
    ]
    # the reader is asked about deliver cells only: every other route is its own row
    held = cell(route="human", reason_code="insufficient")
    assert [r.kind for r in dec.decision_rows(cells=[held], standard_for=ceiling)] == [
        "routed_human"
    ]
    assert asked == [CellRef("bug.fix", "M")]


# --- the clock ------------------------------------------------------------------------


def _due(db: Any, repo: str = ALPHA) -> dict[tuple[str, str], DecisionDue]:
    return {(r.kind, r.key): r for r in dec.due_records(db, repo)}


def test_first_due_is_stamped_once_and_survives_a_row_coming_back(env: Env) -> None:
    """The wait is the person's: a row that goes away and comes back keeps the moment it
    first became due, and a row that stops being due is resolved, never deleted."""
    rows = dec.decision_rows(cells=[cell()])
    with env.factory() as db:
        dec.record_due(db, ALPHA, rows, now="2026-09-01T09:00:00+00:00")
        db.commit()
        rec = _due(db)[("signoff_due", "bug.fix|S")]
        assert rec.first_due == rec.last_seen == "2026-09-01T09:00:00+00:00"
        assert rec.resolved == "" and rec.act_role == "approver"
        # still due a day later: first_due holds, last_seen moves
        dec.record_due(db, ALPHA, rows, now="2026-09-02T09:00:00+00:00")
        db.commit()
        rec = _due(db)[("signoff_due", "bug.fix|S")]
        assert rec.first_due == "2026-09-01T09:00:00+00:00"
        assert rec.last_seen == "2026-09-02T09:00:00+00:00"
        # signed: the decision is gone, and how long it took is kept
        dec.record_due(db, ALPHA, [], now="2026-09-03T09:00:00+00:00")
        db.commit()
        rec = _due(db)[("signoff_due", "bug.fix|S")]
        assert rec.resolved == "2026-09-03T09:00:00+00:00"
        assert rec.first_due == "2026-09-01T09:00:00+00:00"
        # the sign-off goes stale and the cell is due again: the ORIGINAL wait, not a new one
        dec.record_due(db, ALPHA, rows, now="2026-09-04T09:00:00+00:00")
        db.commit()
        rec = _due(db)[("signoff_due", "bug.fix|S")]
        assert rec.resolved == "" and rec.first_due == "2026-09-01T09:00:00+00:00"
    assert dec.age_seconds("2026-09-01T09:00:00+00:00", now="2026-09-02T09:00:00+00:00") == 86400
    assert dec.age_seconds("not a time") == 0
    # a clock that reads backwards is never a negative age
    assert dec.age_seconds("2026-09-02T09:00:00+00:00", now="2026-09-01T09:00:00+00:00") == 0


def test_one_repositorys_clock_is_its_own(env: Env) -> None:
    rows = dec.decision_rows(cells=[cell()])
    with env.factory() as db:
        dec.record_due(db, ALPHA, rows, now="2026-09-01T09:00:00+00:00")
        dec.record_due(db, "beta", rows, now="2026-09-05T09:00:00+00:00")
        db.commit()
        assert _due(db, ALPHA)[("signoff_due", "bug.fix|S")].first_due.startswith("2026-09-01")
        assert _due(db, "beta")[("signoff_due", "bug.fix|S")].first_due.startswith("2026-09-05")
        assert len(dec.due_records(db)) == 2


def test_a_first_stamp_another_reader_committed_first_is_joined_not_collided(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker's idle pass and ``GET /decisions`` both stamp the clock, under a unique
    ``(repo, kind, key)``. When the other one commits the SAME first stamp between this
    pass's read and its write, the pass joins that row — keeps its ``first_due``, moves its
    ``last_seen`` — instead of an ``IntegrityError`` that killed the worker loop and gave the
    reader a 500 (the independent verifiers' attack on stream S, P-357)."""
    rows = dec.decision_rows(cells=[cell()])
    original = dec.due_records
    raced: list[bool] = []

    def racing(db: Any, repo: str = "") -> Any:
        seen = original(db, repo)
        if not raced:
            raced.append(True)
            with env.factory() as other:  # the other reader, in its own transaction
                dec.record_due(other, ALPHA, rows, now="2026-09-01T09:00:00+00:00")
                other.commit()
        return seen

    monkeypatch.setattr(dec, "due_records", racing)
    with env.factory() as db:
        live = dec.record_due(db, ALPHA, rows, now="2026-09-01T10:00:00+00:00")
        db.commit()
        assert raced and live[("signoff_due", "bug.fix|S")].first_due.startswith("2026-09-01T09:00")
    with env.factory() as db:
        (rec,) = dec.due_records(db, ALPHA)
        assert rec.first_due == "2026-09-01T09:00:00+00:00"
        assert rec.last_seen == "2026-09-01T10:00:00+00:00" and rec.resolved == ""


# --- the route ------------------------------------------------------------------------


def test_the_route_serves_the_age_with_the_row_and_records_it_for_next_time(env: Env) -> None:
    """The seeded repository's deliver cell, proven in the sealed posture with its controls
    and oracle measured (routing.v2), routes `deliver` and nobody has signed it: a sign-off
    is due. The first read stamps it; the second reads the SAME ``due_since``, which is the
    whole point — the age is the decision's, not the reader's."""
    clear_policy(env)
    login(env.client, "viewer")
    body = env.get("/decisions").json()
    assert body["total"] >= 1 and ALPHA in body["repos"]
    rows = {(r["repo"], r["kind"], r["key"]): r for r in body["items"]}
    (first,) = [r for k, r in rows.items() if k[0] == ALPHA and k[1] == "signoff_due"]
    assert first["due_since"] and first["age_s"] >= 0
    assert first["role"] == "approver" and first["title"]
    # read again: the moment it became due does not move
    again = env.get(f"/decisions?repo={ALPHA}").json()
    assert again["repos"] == [ALPHA]
    same = next(r for r in again["items"] if r["kind"] == "signoff_due")
    assert same["due_since"] == first["due_since"]
    # and it is on the record, so the clock runs with nobody looking
    with env.factory() as db:
        assert ("signoff_due", same["key"]) in _due(db)
    # a signed-out caller reads nothing
    logout(env.client)
    r = env.get("/decisions")
    assert r.status_code == 401 and envelope(r)["code"] in {"unauthenticated", "forbidden"}


def test_an_unknown_repository_is_a_404_and_writes_nothing(env: Env) -> None:
    """``?repo=`` names a repository the deployment has connected, or it is refused the way
    every other per-repository route refuses it — never a 200 with an empty inbox that
    reads as "nothing is waiting", and never an unchecked name handed on as a path."""
    login(env.client, "viewer")
    for name in ("../../etc", "x" * 400, "not-connected"):
        r = env.get("/decisions", params={"repo": name})
        assert r.status_code == 404, (name, r.text)
        assert envelope(r)["code"] == "not_found"
    with env.factory() as db:
        assert dec.due_records(db) == []


def _attestation_the_gate_does_not_read(env: Env) -> None:
    """A stored attestation of ``bug.fix × S`` written before the reading stamps (v4: the
    apparatus and the checks arm stamped, no context arm, class set or reading). The map's
    overlay lifts the pooled cell with it (``covers_reading`` does not judge an unstamped
    record); the entry gate does not read it (``signed_by`` matches the context arm and the
    reading exactly). It is the first row of the chain."""
    from crb.core.evidence import utc_now_iso
    from crb.core.ledger import GENESIS_HASH
    from crb.core.version import APPARATUS_VERSION
    from crb.server.routes.signoffs import signoff_hash
    from crb.store.models import Signoff

    with env.factory() as db:
        row = Signoff(
            signoff_id="unstamp0" * 4,
            repo=ALPHA,
            cell_json={
                **dict.fromkeys(("process_step", "language", "builder", "model", "provider"), "*"),
                "capability_class": "bug.fix",
                "size": "S",
                "evidence_n": "40",
                "evidence_false_q1": "0",
                "evidence_apparatus": APPARATUS_VERSION,
                "evidence_checks_arm": "off",
            },
            tier="human-verified",
            verifier="old-approver",
            note="signed before the reading stamps",
            revoke=False,
            evidence_rows=40,
            created=utc_now_iso(),
            prev_hash=GENESIS_HASH,
        )
        row.row_hash = signoff_hash(row)
        db.add(row)
        db.commit()


def _map_cell(env: Env, key: str) -> dict[str, Any]:
    body = env.get("/capability-map", params={"repo": ALPHA, "by": "class,size"}).json()
    return next(c for c in body["cells"] if c["label"] == key)


def _inbox(env: Env) -> set[tuple[str, str]]:
    items = env.get("/decisions", params={"repo": ALPHA}).json()["items"]
    return {(r["kind"], r["key"]) for r in items}


def _gate_standard(env: Env, db: Any) -> Standard | None:
    """The entry gate's reading of the seed's deliver cell's standard, bound as the next run's
    worker binds it."""
    from crb.server import factory_standard

    readers = factory_standard.deployment_readers(db, env.settings, ALPHA)
    return readers.standard_for(CellRef("bug.fix", "S"))


def _gate_entry(env: Env, db: Any) -> Any:
    """The entry gate's decision for a ready ``bug.fix × S`` item on a deployment that
    requires a signed cell."""
    from crb.server import factory_standard

    readers = factory_standard.deployment_readers(db, env.settings, ALPHA)
    return decide_entry(
        capability_class="bug.fix",
        size="S",
        standard_for=readers.standard_for,
        agreement_passed=True,
        missing_slots=(),
        person_test=True,
        require_signed_cell=True,
    )


def test_the_route_asks_for_a_cell_the_map_reads_earned_but_the_gate_reads_unsigned(
    env: Env,
) -> None:
    """G-738 over a real store: an attestation the map's overlay reads lifts the seed's
    deliver cell to ``human-verified`` while the entry gate reads the cell's standard
    unsigned and would stop its items ``unsigned_cell``. ``GET /decisions`` serves the
    sign-off due — the gate's reading, not the map's."""
    clear_policy(env)
    _attestation_the_gate_does_not_read(env)
    login(env.client, "viewer")
    assert _map_cell(env, "bug.fix|S")["verification_tier"] == "human-verified"
    assert ("signoff_due", "bug.fix|S") in _inbox(env)
    with env.factory() as db:  # the gate reads a proven, licensing standard — unsigned
        std = _gate_standard(env, db)
        assert std is not None and std.licenses and not std.signed
        assert _gate_entry(env, db).code == STOP_UNSIGNED_CELL


def test_the_route_asks_nobody_for_a_cell_the_gate_reads_signed(env: Env) -> None:
    """G-738, the converse over a real store: an approver attests the seed's deliver cell for
    its one builder (``POST /signoffs``). The entry gate reads that sign-off and would build
    the cell's items; the pooled class × size map cell is never lifted by a narrower
    sign-off (``key_matches``) and still reads ``automated-pass``. Nothing waits on a
    person, so the inbox serves no sign-off due for the cell."""
    clear_policy(env)
    login(env.client, "viewer")
    assert ("signoff_due", "bug.fix|S") in _inbox(env)
    logout(env.client)
    login(env.client, "approver")
    assert env.post("/signoffs", json=attested_body(env, DELIVER_CELL)).status_code == 201
    logout(env.client)
    login(env.client, "viewer")
    assert _map_cell(env, "bug.fix|S")["verification_tier"] == "automated-pass"
    assert ("signoff_due", "bug.fix|S") not in _inbox(env)
    with env.factory() as db:  # and the clock resolved the row rather than keep it waiting
        assert _due(db)[("signoff_due", "bug.fix|S")].resolved
        assert _gate_entry(env, db).code == ""  # the gate would build the cell's items


def test_a_revoked_sign_off_puts_the_cell_back_in_the_inbox(env: Env) -> None:
    """``decisions.truth.4`` over a real store: an active sign-off the gate reads clears the
    cell's row; once an approver revokes it the gate reads the standard unsigned again, and
    ``GET /decisions`` serves the sign-off due again."""
    clear_policy(env)
    login(env.client, "approver")
    r = env.post("/signoffs", json=attested_body(env, DELIVER_CELL))
    assert r.status_code == 201, r.text
    assert ("signoff_due", "bug.fix|S") not in _inbox(env)
    revoked = env.post(f"/signoffs/{r.json()['id']}/revoke", json={"note": "re-examined"})
    assert revoked.status_code == 200, revoked.text
    with env.factory() as db:
        std = _gate_standard(env, db)
        assert std is not None and std.licenses and not std.signed
    assert ("signoff_due", "bug.fix|S") in _inbox(env)


def _idle_worker(env: Env) -> Any:
    """A worker over the seeded store, graded in the API's posture class (the seed's rows are
    sealed docker rows), whose idle pass keeps the decisions clock."""
    from crb.server.worker import Worker, WorkerSettings

    engine = env.factory.kw["bind"]
    settings = WorkerSettings(
        database_url=str(engine.url), home=env.settings.home, worker_id="w-idle", executor="docker"
    )
    return Worker(settings, engine=engine)


def test_the_idle_pass_asks_until_the_gate_reads_the_cell_signed(env: Env) -> None:
    """P-411 on the worker's idle pass (``Worker.refresh_decisions``), which binds the gate's
    readers in its own posture class: the deliver cell is a sign-off due while the gate reads
    its standard unsigned, and the row resolves once an approver's attestation the gate reads
    exists — although the pooled map cell's tier stays ``automated-pass``."""
    clear_policy(env)
    worker = _idle_worker(env)
    with env.factory() as db:
        assert worker._deployment_posture_class(ALPHA) == posture_now(db, env.settings, ALPHA)
    assert worker.refresh_decisions(now=1000.0) == 2
    with env.factory() as db:
        assert _due(db)[("signoff_due", "bug.fix|S")].resolved == ""
    login(env.client, "approver")
    assert env.post("/signoffs", json=attested_body(env, DELIVER_CELL)).status_code == 201
    assert _map_cell(env, "bug.fix|S")["verification_tier"] == "automated-pass"
    assert worker.refresh_decisions(now=1000.0 + 10 * DECISIONS_REFRESH_S) == 2
    with env.factory() as db:
        assert _due(db)[("signoff_due", "bug.fix|S")].resolved


def test_the_idle_pass_keeps_asking_for_a_tier_the_gate_does_not_read(env: Env) -> None:
    """P-411, the converse on the idle pass: an attestation the map's overlay reads lifts the
    cell to ``human-verified``, but the gate does not read it — so the idle pass keeps the
    sign-off due open rather than resolving it on the tier."""
    clear_policy(env)
    _attestation_the_gate_does_not_read(env)
    worker = _idle_worker(env)
    login(env.client, "viewer")
    assert _map_cell(env, "bug.fix|S")["verification_tier"] == "human-verified"
    assert worker.refresh_decisions(now=1000.0) == 2
    with env.factory() as db:
        assert _due(db)[("signoff_due", "bug.fix|S")].resolved == ""


def test_the_inbox_binds_the_gates_readers_once_per_repository(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The inbox's "sign-off due", the factory items' preview and their cell routes read one
    binding of the entry gate's readers per repository and request — not one each."""
    from crb.server import factory_standard

    item = {
        "id": "I-1",
        "title": "Add multiply to calc",
        "kind": "code",
        "description": "calc needs a multiply(a, b) function.",
        "acceptance_criteria": ["multiply(3, 4) == 12"],
        "capability_class": "bug.fix",
        "size_estimate": "S",
        "structural_facts": [
            "reproduction: `from calc import multiply` raises ImportError",
            "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
        ],
    }
    login(env.client, "operator")
    assert env.post(f"/factory/{ALPHA}/backlog", json={"items": [item]}).status_code == 201
    bound: list[str] = []
    real = factory_standard.readers_in

    def counting(session: Any, repo: str, **kw: Any) -> Any:
        bound.append(repo)
        return real(session, repo, **kw)

    monkeypatch.setattr(factory_standard, "readers_in", counting)
    assert env.get("/decisions", params={"repo": ALPHA}).status_code == 200
    assert bound == [ALPHA]
    bound.clear()
    assert env.get("/decisions", params={"count": "1"}).status_code == 200
    assert sorted(bound) == sorted({ALPHA, BETA})
    bound.clear()
    assert env.get(f"/factory/{ALPHA}/tasks").status_code == 200
    assert bound == [ALPHA]


def test_the_idle_pass_binds_the_gate_in_the_workers_own_posture_class(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker's idle pass reads the gate in the worker's own posture class, which the API's
    settings do not carry: a worker grading on the host binds its readers there, never in the
    posture class the API would read for itself (P-411)."""
    from crb.server import factory_standard
    from crb.server.worker import Worker, WorkerSettings

    clear_policy(env)  # the API grades in the sealed posture (sandbox.executor docker)
    engine = env.factory.kw["bind"]
    worker = Worker(
        WorkerSettings(database_url=str(engine.url), home=env.settings.home, worker_id="w-host"),
        engine=engine,
    )
    with env.factory() as db:
        own, api = worker._deployment_posture_class(ALPHA), posture_now(db, env.settings, ALPHA)
    assert own != api  # the host executor against the API's sealed posture
    bound: list[tuple[str, str]] = []
    real = factory_standard.readers_in

    def recording(session: Any, repo: str, **kw: Any) -> Any:
        bound.append((repo, kw["posture_class"]))
        return real(session, repo, **kw)

    monkeypatch.setattr(factory_standard, "readers_in", recording)
    assert worker.refresh_decisions(now=1000.0) == 2
    assert sorted(bound) == [(ALPHA, own), (BETA, own)]


# --- G-535: a held cell and a stale apparatus are Decisions rows ----------------------


def test_a_cell_held_by_its_oracle_or_its_controls_is_one_strengthening_row() -> None:
    """G-535: a cell the rule holds for a reason test-strengthening work can move
    (``STRENGTHEN_REASONS``: a weak oracle, escaped or thin controls) is a ``strengthen`` row
    for an operator that links to the strengthening backlog on Learn — and it is ONE row, not a
    ``routed_human`` row beside it. A clause the rule lists as a shortfall counts too (routing.v2
    lists every failing clause), and the row names that clause, never the posture or a pending
    reading, which no test can fix."""
    weak = cell(route="human", size="M", reason="oracle strength 0.58", reason_code="oracle_weak")
    rows = dec.decision_rows(cells=[weak], repo="alpha")
    assert [(r.kind, r.key) for r in rows] == [("strengthen", "bug.fix|M")]
    (row,) = rows
    assert row.role == "operator" and row.act == "Strengthen the tests"
    assert row.href == "/learn?repo=alpha#strengthen"
    assert row.reason_code == "oracle_weak" and row.evidence.endswith(" · oracle_weak")
    # a calibrate cell whose shortfalls include thin controls: held, named by that clause
    thin = cell(route="calibrate", size="S", reason_code="reading_unregistered")
    assert thin.decision is not None
    thin_held = replace_decision(
        thin,
        shortfalls=(
            Shortfall("reading_unregistered", "calibrate", None, None, "register"),
            Shortfall("controls_thin", "calibrate", 0.2, 0.5, "controls"),
        ),
    )
    (held,) = dec.decision_rows(cells=[thin_held], repo="alpha")
    assert (held.kind, held.reason_code) == ("strengthen", "controls_thin")
    # a human cell held for another reason stays "routed to a human", read by anyone
    other = cell(route="human", size="L", reason_code="insufficient")
    assert [r.kind for r in dec.decision_rows(cells=[other])] == ["routed_human"]


def test_a_cell_whose_evidence_predates_the_apparatus_is_a_remeasurement_row() -> None:
    """G-535: each STALE cell of the re-measurement plan is a ``remeasure`` row for an operator,
    keyed by its full cell and mode, with the rows it needs and the estimate — or, when no row
    recorded a cost, "cost not known", never a $0 that reads as free. A cell whose queued runs
    have not finished asks nobody for anything; a plan with no stale cell raises no row."""
    key = {"capability_class": "bug.fix", "size": "S", "builder": "editblock", "model": "m"}
    plan = {
        "current_apparatus": "2.4",
        "cells": [
            {
                "cell": {**key, "provider": "p"},
                "label": "*|bug.fix|S|go|editblock|m|p",
                "mode": "sighted",
                "stale_versions": ["2.2"],
                "n_needed": 20,
                "est_cost_usd": 1.5,
                "cost_known": True,
            },
            {
                "cell": {**key, "size": "M", "provider": "p"},
                "label": "*|bug.fix|M|go|editblock|m|p",
                "mode": "blind",
                "stale_versions": ["2.2", "2.3"],
                "n_needed": 1,
                "est_cost_usd": 0.0,
                "cost_known": False,
            },
        ],
    }
    rows = dec.decision_rows(repo="alpha", remeasure=plan)
    assert [(r.kind, r.key, r.role) for r in rows] == [
        ("remeasure", "*|bug.fix|M|go|editblock|m|p|blind", "operator"),
        ("remeasure", "*|bug.fix|S|go|editblock|m|p|sighted", "operator"),
    ]
    by_key = {r.key.rsplit("|", 1)[1]: r for r in rows}
    assert by_key["sighted"].evidence.startswith("20 rows needed · est. $1.50")
    assert by_key["blind"].evidence.startswith("1 row needed · cost not known")
    assert "was measured under apparatus 2.2, 2.3, not 2.4" in by_key["blind"].title
    assert all(
        r.act == "Queue re-measurement" and r.href == "/learn?repo=alpha#remeasure" for r in rows
    )
    busy = {("*|bug.fix|S|go|editblock|m|p", "sighted")}
    assert [r.key for r in dec.decision_rows(remeasure=plan, in_flight=busy)] == [
        "*|bug.fix|M|go|editblock|m|p|blind"
    ]
    assert dec.decision_rows(remeasure={"current_apparatus": "2.4", "cells": []}) == []


def test_a_stale_signoff_is_its_own_row_and_its_cell_is_counted_once() -> None:
    """ADR-0015: a sign-off served ``stale`` is a ``signoff_stale`` row (revoke or re-sign),
    carrying the attestation as served, and its cell is then no ``signoff_due`` row as well —
    the inbox counts the cell once. A revoked sign-off is nobody's decision."""
    stale = {
        "id": "s-9",
        "cell": {"capability_class": "bug.fix", "size": "S"},
        "stale": True,
        "revoked": False,
        "stale_reason": "apparatus_moved",
        "created": "2026-09-01T10:00:00+00:00",
        "approver_name": "Grace",
    }
    rows = dec.decision_rows(cells=[cell()], repo="alpha", stale=[stale])
    assert [(r.kind, r.key) for r in rows] == [("signoff_stale", "s-9")]
    (row,) = rows
    assert row.signoff == stale and row.act == "Revoke or re-sign" and row.role == "approver"
    assert row.href == "/signoff?repo=alpha&cell=bug.fix%7CS"
    assert row.evidence == "signed 2026-09-01 by Grace · apparatus_moved"
    gone = {**stale, "revoked": True}
    assert [r.kind for r in dec.decision_rows(cells=[cell()], stale=[gone])] == ["signoff_due"]


def test_an_entry_its_sponsor_reads_is_never_theirs_to_sign() -> None:
    """ADR-0026 item 10: the sponsor of a proposed or stale library entry is refused their own
    signature (``same_person``), so the row they read names that another approver acts; the
    clock keeps the row everyone else reads, under the same key."""
    library = {
        "entries": [
            {
                "entry_id": "convention/x",
                "status": "proposed",
                "sponsor": "u-ada",
                "sponsor_name": "Ada",
                "entry": {"title": "X"},
            }
        ]
    }
    (row,) = dec.decision_rows(repo="alpha", library=library)
    assert (row.role, row.act) == ("approver", "Sign")
    mine = dec.for_viewer(row, "u-ada")
    assert (mine.key, mine.role, mine.act) == (row.key, "viewer", "Read")
    assert mine.title.endswith("— you sponsored it")
    assert dec.for_viewer(row, "u-ben") == row


def test_the_act_is_offered_only_to_a_role_that_can_take_it() -> None:
    """F6: the served row carries the act only for a role that can take it; anyone reads a
    viewer's row."""
    from crb.server.settings import ROLE_RANK

    (due,) = dec.decision_rows(cells=[cell()])
    assert not dec.can_act(due, "viewer", ROLE_RANK)
    assert not dec.can_act(due, "operator", ROLE_RANK)
    assert dec.can_act(due, "approver", ROLE_RANK) and dec.can_act(due, "admin", ROLE_RANK)
    (read,) = dec.decision_rows(cells=[cell(route="do_not_ship", reason_code="false_q1")])
    assert dec.can_act(read, "viewer", ROLE_RANK)


# --- F6: one derivation, pinned to the browser's ---------------------------------------

PARITY = Path(__file__).resolve().parents[1] / "ui/src/screens/Decisions/decisions.parity.json"


def _served_cell(c: dict[str, Any]) -> CapabilityCell:
    """A served map cell (``GET /capability-map``'s shape) as the core cell the server folds."""
    built = cell(
        capability_class=c["capability_class"],
        size=c["size"],
        route=c["route"],
        n=c["n"],
        tier=c["verification_tier"],
        reason=c["reason"],
        reason_code=c["reason_code"],
    )
    if built.stats is None or built.decision is None:
        return built
    stats = dataclasses.replace(
        built.stats,
        n_tasks=c["n_tasks"],
        point=c["point"],
        ci=Interval(c["ci_low"], c["ci_high"]),
    )
    shortfalls = tuple(
        Shortfall(s["code"], s["route"], s["observed"], s["threshold"], s["next"])
        for s in c["shortfalls"]
    )
    return dataclasses.replace(
        built, stats=stats, decision=dataclasses.replace(built.decision, shortfalls=shortfalls)
    )


def test_server_rows_match_the_ui_fixture() -> None:
    """F6: the server serves the inbox, and the Results page still folds the cell and item rows
    in the browser (``decisionsFor``). One fixture holds one repository's inputs and the rows
    both must produce — every field a person reads: kind, key, title, role, evidence, reason
    code, act and link. ``decisions.test.ts`` asserts the browser's side against the same file,
    so a word changed on one side only fails one of the two. A served cell's ``signed`` is the
    entry gate's reading of its standard (G-738), so it is the reader the server is handed."""
    fx = json.loads(PARITY.read_text(encoding="utf-8"))
    signed = [f"{c['capability_class']}|{c['size']}" for c in fx["cells"] if c["signed"]]
    rows = dec.decision_rows(
        [_served_cell(c) for c in fx["cells"]],
        fx["tasks"],
        fx["register"],
        repo=fx["repo"],
        library=fx["library"],
        standard_for=gate(*signed),
    )
    got = [
        {
            "kind": r.kind,
            "key": r.key,
            "title": r.title,
            "role": r.role,
            "evidence": r.evidence,
            "reason_code": r.reason_code,
            "act": r.act,
            "href": r.href,
        }
        for r in rows
    ]
    assert got == fx["expected"]
    # every kind the browser folds is exercised, so a kind added on one side is noticed
    assert {r["kind"] for r in got} == {
        "do_not_ship",
        "gap_unsigned",
        "not_built",
        "signoff_due",
        "rework",
        "delivery_withheld",
        "prevention",
        "entry_stale",
        "entry_to_sign",
        "item_human",
        "strengthen",
        "routed_human",
        "entry_retired",
    }


# --- F6: the count mode, the cache, the viewer's role, one broken repository -----------


def test_count_mode_does_not_write_the_clock_and_honours_the_etag(env: Env) -> None:
    """The nav badge reads ``?count=1`` on every screen: the total and the count per acting
    role, the same number the full list has, and NO clock row — a badge is not an observation.
    The count carries a strong ETag; sending it back is a 304 with no body, and it is
    revalidated on every read so an act is seen at once. The list carries its clock, so it has
    no ETag that could never match: it is served fresh (``no-store``)."""
    clear_policy(env)
    login(env.client, "viewer")
    r = env.get("/decisions", params={"count": "1"})
    assert r.status_code == 200, r.text
    counted = r.json()
    assert set(counted) == {"total", "by_role", "errors"}
    assert counted["total"] >= 1 and counted["total"] == sum(counted["by_role"].values())
    assert r.headers["Cache-Control"] == "private, no-cache"
    tag = r.headers["ETag"]
    assert tag.startswith('"') and tag.endswith('"') and not tag.startswith("W/")
    with env.factory() as db:
        assert dec.due_records(db) == []  # the badge wrote nothing
    same = env.get("/decisions", params={"count": "1"}, headers={"If-None-Match": tag})
    assert same.status_code == 304 and same.content == b"" and same.headers["ETag"] == tag
    # the list: the same total, the clock stamped, and served fresh with no ETag to revalidate
    full = env.get("/decisions")
    assert full.json()["total"] == counted["total"]
    assert full.headers["Cache-Control"] == "private, no-store" and "ETag" not in full.headers
    with env.factory() as db:
        assert len(dec.due_records(db)) == counted["total"]


def test_the_served_row_fits_the_viewers_role(env: Env) -> None:
    """F6: a viewer is served the approver's row with ``Read`` and ``can_act`` false; an
    approver the same row with its act; the link and the key do not change."""
    clear_policy(env)
    login(env.client, "viewer")
    seen = {(r["kind"], r["key"]): r for r in env.get("/decisions").json()["items"]}
    due = next(r for (k, _), r in seen.items() if k == "signoff_due")
    assert (due["act"], due["can_act"], due["role"]) == ("Read", False, "approver")
    logout(env.client)
    login(env.client, "approver")
    mine = {(r["kind"], r["key"]): r for r in env.get("/decisions").json()["items"]}
    same = mine[("signoff_due", due["key"])]
    assert (same["act"], same["can_act"]) == ("Attest", True)
    assert same["href"] == due["href"] and same["href"].startswith("/signoff?repo=")


def test_a_repository_whose_inputs_cannot_be_read_is_named_and_the_rest_are_served(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One repository whose library no longer folds (409 ``library_integrity``) is named in
    ``errors`` with its status, code and message, and every other repository is still served —
    the count is incomplete, never quietly smaller. The badge's count names it too."""
    from crb.server.deps import ApiError
    from crb.server.routes import decisions as route

    real = route.library_index

    def broken(repo: str, *a: Any, **kw: Any) -> Any:
        if repo == BETA:
            raise ApiError(409, "library_integrity", "the library's acts no longer fold")
        return real(repo, *a, **kw)

    monkeypatch.setattr(route, "library_index", broken)
    clear_policy(env)
    login(env.client, "viewer")
    body = env.get("/decisions").json()
    assert body["errors"] == [
        {
            "repo": BETA,
            "status": 409,
            "code": "library_integrity",
            "message": "the library's acts no longer fold",
        }
    ]
    assert {r["repo"] for r in body["items"]} == {ALPHA}
    assert ALPHA in body["measured"]
    assert env.get("/decisions", params={"count": "1"}).json()["errors"] == [BETA]


def test_the_idle_pass_never_resolves_a_row_it_cannot_see(env: Env) -> None:
    """F6: ``GET /decisions`` stamps a ``not_built`` row for an item no run has reached (the
    entry gate's preview); the worker's idle pass cannot read that preview, so it keeps the kind
    open (``IDLE_KEEPS_OPEN``) instead of resolving the route's row every pass. The route's own
    pass, which sees the item, resolves it when it goes."""
    row = dec.DecisionRow(
        dec.KIND_NOT_BUILT, "I-9", "I-9 x is not built — no proven standard", "approver"
    )
    with env.factory() as db:
        dec.record_due(db, ALPHA, [row], now="2026-09-01T09:00:00+00:00")
        dec.record_due(
            db, ALPHA, [], now="2026-09-02T09:00:00+00:00", keep_open=dec.IDLE_KEEPS_OPEN
        )
        db.commit()
        rec = _due(db)[("not_built", "I-9")]
        assert rec.resolved == "" and rec.first_due == "2026-09-01T09:00:00+00:00"
        dec.record_due(db, ALPHA, [], now="2026-09-03T09:00:00+00:00")
        db.commit()
        assert _due(db)[("not_built", "I-9")].resolved == "2026-09-03T09:00:00+00:00"
    assert frozenset({"not_built"}) == dec.IDLE_KEEPS_OPEN


# --- the served inbox's own wiring (verifier findings on F6, G-535) --------------------


def test_the_served_inbox_raises_a_stale_cell_until_its_runs_are_queued(env: Env) -> None:
    """G-535 through the route, not the derivation: the seed holds a cell graded under an
    earlier apparatus, so ``GET /decisions`` (and its count) serve a ``remeasure`` row for it
    with the link to Learn's plan and the rows needed and cost on its evidence line. While the
    runs an operator queued for that cell have not finished, the served inbox raises no row for
    it — the queue already answered it."""
    from crb.core.version import APPARATUS_VERSION
    from crb.server.routes.learn import ACTION_REMEASURE_QUEUED
    from crb.server.routes.runs import append_system_event
    from crb.store.models import Run

    clear_policy(env)
    login(env.client, "operator")
    plan = env.get(f"/learn/remeasure?repo={ALPHA}").json()
    # the plan also carries thin and pending cells (top-ups); only a stale one is a row
    stales = [c for c in plan["cells"] if c.get("reason", "stale") == "stale"]
    assert stales, "the seed must hold a stale cell"
    stale = stales[0]
    key = f"{stale['label']}|{stale['mode']}"

    def served() -> dict[str, Any]:
        body = env.get("/decisions", params={"repo": ALPHA}).json()
        return {r["key"]: r for r in body["items"] if r["kind"] == "remeasure"}

    rows = served()
    assert key in rows, sorted(rows)
    row = rows[key]
    assert row["href"] == f"/learn?repo={ALPHA}#remeasure"
    assert (row["role"], row["act"], row["can_act"]) == ("operator", "Queue re-measurement", True)
    needed = int(stale["n_needed"])
    assert row["evidence"].startswith(f"{needed} row{'' if needed == 1 else 's'} needed · ")
    assert ("est. $" in row["evidence"]) or ("cost not known" in row["evidence"])
    counted = env.get("/decisions", params={"count": "1"}).json()
    listed = env.get("/decisions").json()
    assert counted["total"] == listed["total"]

    # an operator queues the cell's runs: while they are unfinished the row is gone
    run_id = "cd" * 16
    with env.factory() as s:
        s.add(Run(id=run_id, repo=ALPHA, kind="replay", status="queued", mode=stale["mode"]))
        append_system_event(
            s,
            trace_id="learn-remeasure-test",
            action=ACTION_REMEASURE_QUEUED,
            repo=ALPHA,
            payload={
                "cell": stale["label"],
                "mode": stale["mode"],
                "apparatus": APPARATUS_VERSION,
                "run_ids": [run_id],
            },
        )
        s.commit()
    assert key not in served()
    assert env.get("/decisions", params={"count": "1"}).json()["total"] == counted["total"] - 1


def test_a_thin_cell_in_the_plan_raises_no_row() -> None:
    """The inbox raises a re-measurement for a STALE cell only. A plan cell that carries another
    reason (``thin``: its current rows do not reach the rule's first look, G-565's top-up) is
    not a Decisions row; a cell with no reason is read as stale, the plan's only kind today."""
    base = {
        "cell": {"capability_class": "bug.fix", "size": "S", "builder": "b", "model": "m"},
        "mode": "sighted",
        "stale_versions": ["2.2"],
        "n_needed": 3,
        "cost_known": False,
    }
    plan = {
        "current_apparatus": "2.4",
        "cells": [
            {**base, "label": "stale-no-reason"},
            {**base, "label": "stale-said", "reason": "stale"},
            {**base, "label": "thin", "reason": "thin"},
        ],
    }
    keys = [r.key for r in dec.decision_rows(remeasure=plan)]
    assert keys == ["stale-no-reason|sighted", "stale-said|sighted"]


def test_a_repository_that_fails_for_any_reason_is_named_and_the_rest_are_served(
    env: Env,
) -> None:
    """One repository's inputs failing with something other than a refusal (a factory backlog
    that no longer parses) is named in ``errors`` as a 500 ``internal_error`` and every other
    repository is still served, in the list and in the count: one broken repository must never
    blank everyone's inbox (P-612)."""
    from crb.server.factory_state import FactoryHome

    path = FactoryHome(env.settings.home, BETA).backlog_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    clear_policy(env)
    login(env.client, "viewer")
    r = env.get("/decisions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(e["repo"], e["status"], e["code"]) for e in body["errors"]] == [
        (BETA, 500, "internal_error")
    ]
    assert "could not be read" in body["errors"][0]["message"]
    assert {i["repo"] for i in body["items"]} == {ALPHA}
    c = env.get("/decisions", params={"count": "1"})
    assert c.status_code == 200 and c.json()["errors"] == [BETA]
