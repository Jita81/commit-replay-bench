"""The decisions inbox derived on the server, and the clock over it (G-516).

Navigation
----------
What it is:   The test suite for ``crb.server.decisions`` (``decision_rows``, ``record_due``,
              ``age_seconds``) and ``GET /decisions``.
What it does: Pins that the derivation produces the same seven kinds and the same row
              identities the screen computes — the cell rows keyed ``<class>|<size>`` and the
              item rows keyed by item id — that a cell nobody has measured is not a decision,
              that a STALE sign-off puts its cell back in the inbox (ADR-0015), that the
              clock stamps ``first_due`` once and keeps it when a row goes away and comes
              back, that a row that stops being due is resolved rather than deleted, and that
              the route serves each row with its age and needs only a viewer.
How:          The seeded server (``fixtures.server_seed``) for the route; hand-built
              ``CapabilityCell`` and ``TaskView`` objects for the derivation, so the rules
              are pinned without a ledger; the clock is moved by passing ``now`` rather than
              by sleeping.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0015-signoffs-expire-with-the-apparatus.md
Works with:   src/crb/server/decisions.py and src/crb/server/routes/decisions.py (under
              test), src/crb/store/models.py (``DecisionDue``),
              ui/src/screens/Decisions/decisions.ts (the screen's own derivation of the same
              rows — the kinds and keys pinned here are the join)
Tested by:    tests/test_server_decisions.py
Touch when:   a human act is added to the product (a kind in both derivations).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core.capability import CapabilityCell
from crb.core.ledger import CellKey, CellStats
from crb.core.routing import RouteDecision
from crb.core.stats import Interval
from crb.server import decisions as dec
from crb.server.factory_state import TaskView
from crb.store.models import DecisionDue
from fixtures.server_seed import ALPHA, Env, envelope, login, logout, make_env


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


# --- the derivation -------------------------------------------------------------------


def test_the_seven_kinds_and_their_keys_are_the_ones_the_screen_computes() -> None:
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
                reason="oracle strength 0.58 < 0.80",
                reason_code="oracle_weak",
            ),
            cell(route="deliver", size="L", tier="human-verified"),  # signed: not a decision
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
    assert "oracle strength" in by_kind["routed_human"].title


def test_a_stale_signoff_puts_its_cell_back_in_the_inbox() -> None:
    """ADR-0015: the map's overlay lifts a cell only while the attestation covers the cell's
    apparatus, so a cell whose sign-off went stale reads unsigned here — which is what a
    reader needs to see: somebody has to sign it again."""
    assert [r.kind for r in dec.decision_rows(cells=[cell(tier="human-verified")])] == []
    # the overlay did not lift it (stale, revoked, or a false-Q1 row since): a decision
    assert [r.kind for r in dec.decision_rows(cells=[cell(tier="automated-pass")])] == [
        "signoff_due"
    ]


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
        assert rec.resolved == "" and rec.role == "approver"
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


# --- the route ------------------------------------------------------------------------


def test_the_route_serves_the_age_with_the_row_and_records_it_for_next_time(env: Env) -> None:
    """The seeded repository's deliver cell is refused by the controls gate, so it routes
    `human`: a decision either way. The first read stamps it; the second reads the SAME
    ``due_since``, which is the whole point — the age is the decision's, not the reader's."""
    login(env.client, "viewer")
    body = env.get("/decisions").json()
    assert body["total"] >= 1 and ALPHA in body["repos"]
    rows = {(r["repo"], r["kind"], r["key"]): r for r in body["items"]}
    (first,) = [r for k, r in rows.items() if k[0] == ALPHA and k[1] == "routed_human"]
    assert first["due_since"] and first["age_s"] >= 0
    assert first["role"] == "viewer" and first["title"]
    # read again: the moment it became due does not move
    again = env.get(f"/decisions?repo={ALPHA}").json()
    assert again["repos"] == [ALPHA]
    same = next(r for r in again["items"] if r["kind"] == "routed_human")
    assert same["due_since"] == first["due_since"]
    # and it is on the record, so the clock runs with nobody looking
    with env.factory() as db:
        assert ("routed_human", same["key"]) in _due(db)
    # a signed-out caller reads nothing
    logout(env.client)
    r = env.get("/decisions")
    assert r.status_code == 401 and envelope(r)["code"] in {"unauthenticated", "forbidden"}
