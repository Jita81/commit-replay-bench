"""The decisions inbox, derived on the server, and the clock over it (G-516).

The inbox is a DERIVATION: every point where a human act is due, folded from the capability
map, the repository's sign-offs and the factory chain. The screen has always derived it
(``ui/src/screens/Decisions/decisions.ts``), which meant a decision existed only while
somebody had the page open — nothing could say that a cell had been waiting eleven days for
an approver, because nothing had written down when it started waiting.

This module is that derivation in Python, plus the clock: :func:`decision_rows` folds the
same seven kinds from the same readings, and :func:`record_due` stamps, per ``(repo, kind,
key)``, the moment a row FIRST became due, the last time it was still due, and when it
stopped. The rule for a row that comes back: ``resolved`` is cleared and ``first_due``
stays. A wait a person actually experienced is not reset by a flicker — a cell that a
re-measurement briefly lifted out of the inbox and back into it has been waiting since it
first arrived, and the reading says so.

The derivation is deliberately duplicated, not shared, and the duplication is bounded: the
screen keeps deriving what it renders (it has the data already, and a person should not wait
for a round trip to see their own inbox), while this side owns the CLOCK — the one thing a
screen cannot know. The two agree on the row identity (``kind`` and ``key``) and nothing
else has to match: ``ui/src/screens/Decisions/decisions.ts`` names this module in its
navigation header, and a key that drifted would show as a missing age, never as a wrong one.

One difference is deliberate: where the screen asks "is there any active sign-off for this
cell", this side asks the capability map whether the cell is EARNED — which is the same
question with the apparatus and the false-Q1 floor applied (:func:`crb.core.signoff.
apply_signoffs`). A stale sign-off therefore puts a cell back in this reading's inbox, which
is what ADR-0015 says it should mean.

Navigation
----------
What it is:   ``decision_rows`` (the inbox's rows for one repository) and ``record_due`` /
              ``due_records`` (the clock: when each row first became due).
What it does: Derives the seven inbox kinds from the capability cells and the factory task
              views, and keeps one ``decisions_due`` row per derived row so the age of a
              decision survives nobody looking at it. Never decides anything and never
              writes to the ledger: a row here is a pointer at an act a person must take.
How:          Pure ``decision_rows`` over ``CapabilityCell`` and ``TaskView``; ``record_due``
              upserts under the caller's session (the caller commits), stamping ``first_due``
              on arrival, ``last_seen`` every pass and ``resolved`` when a row goes.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md (the routes the cell rows quote),
              docs/adr/0015-signoffs-expire-with-the-apparatus.md (why a stale sign-off puts a
              cell back in the inbox)
Works with:   src/crb/server/routes/decisions.py (serves it), src/crb/server/worker.py (the
              idle pass that keeps the clock running with nobody watching),
              src/crb/store/models.py (``DecisionDue``), src/crb/core/capability.py
              (``CapabilityCell`` — the cell rows), src/crb/server/factory_state.py
              (``TaskView`` — the item rows), ui/src/screens/Decisions/decisions.ts (the
              screen's own derivation of the same rows, joined to these ages by key)
Tested by:    tests/test_server_decisions.py
Touch when:   a human act is added to the product — a kind here AND in decisions.ts, with the
              same key.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.capability import CapabilityCell
from crb.core.routing import ROUTE_DELIVER, ROUTE_DO_NOT_SHIP, ROUTE_HUMAN
from crb.server.factory_state import TaskView
from crb.store.models import DecisionDue

#: The inbox's kinds, in the order that decides what blocks what — the same order and the
#: same words as ``ui/src/screens/Decisions/decisions.ts``'s ``ORDER``.
KIND_DO_NOT_SHIP = "do_not_ship"
KIND_GAP_UNSIGNED = "gap_unsigned"
KIND_SIGNOFF_DUE = "signoff_due"
KIND_REWORK = "rework"
KIND_DELIVERY_WITHHELD = "delivery_withheld"
KIND_ITEM_HUMAN = "item_human"
KIND_ROUTED_HUMAN = "routed_human"

#: kind → its rank in the list (lower blocks more).
ORDER: dict[str, int] = {
    KIND_DO_NOT_SHIP: 0,
    KIND_GAP_UNSIGNED: 1,
    KIND_SIGNOFF_DUE: 2,
    KIND_REWORK: 3,
    KIND_DELIVERY_WITHHELD: 4,
    KIND_ITEM_HUMAN: 5,
    KIND_ROUTED_HUMAN: 6,
}

#: The multiplication sign the product writes a cell with, as a name (ruff refuses the
#: ambiguous character inline, and the screen's rows read "bug.fix × XS").
_TIMES = "\u00d7"

ROLE_APPROVER = "approver"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

#: The review verdicts that put an item in front of a person again.
_REWORK_VERDICTS = frozenset({"accept_with_edit", "reject"})
#: The item statuses at which a withheld delivery is the item's final state.
_FINISHED = frozenset({"accepted", "rejected"})


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class DecisionRow:
    """One point where a human act is due. ``key`` identifies WHAT the act is about — the
    cell (``<class>|<size>``) or the item id — and ``(kind, key)`` is the row's identity,
    the same identity the screen computes so an age can be joined to it."""

    kind: str
    key: str
    title: str
    role: str

    @property
    def order(self) -> int:
        return ORDER.get(self.kind, len(ORDER))


def cell_key(capability_class: str, size: str) -> str:
    """``<class>|<size>`` — the screen's ``cellKeyOf``."""
    return f"{capability_class}|{size}"


def decision_rows(
    cells: Iterable[CapabilityCell] = (), tasks: Iterable[TaskView] = ()
) -> list[DecisionRow]:
    """The inbox's rows for one repository, ordered by what blocks what.

    ``cells`` are the (class × size) cells of the repository's SIGNED map — the sign-offs
    already overlaid, so ``cell.earned`` is "a human has attested this, on this apparatus,
    with the false-Q1 floor intact". ``tasks`` are the factory items' latest states.
    An unmeasured cell (``n == 0``) is not a decision: nobody is waiting on it.
    """
    out: list[DecisionRow] = []
    for c in cells:
        if c.n <= 0:
            continue
        # the screen's own words for a cell, so the recorded title reads like the row
        label = f"{c.key.capability_class} {_TIMES} {c.key.size}"
        key = cell_key(c.key.capability_class, c.key.size)
        if c.route == ROUTE_DO_NOT_SHIP:
            out.append(
                DecisionRow(
                    KIND_DO_NOT_SHIP,
                    key,
                    f"{label} must not ship — false-Q1 in the cell",
                    ROLE_VIEWER,
                )
            )
        elif c.route == ROUTE_DELIVER and not c.earned:
            out.append(
                DecisionRow(
                    KIND_SIGNOFF_DUE,
                    key,
                    f"{label} clears the bar — attest it or decline",
                    ROLE_APPROVER,
                )
            )
        elif c.route == ROUTE_HUMAN:
            out.append(
                DecisionRow(
                    KIND_ROUTED_HUMAN, key, f"{label} routed to a human — {c.reason}", ROLE_VIEWER
                )
            )
    for t in tasks:
        label = f"{t.id} {t.title}"
        if t.dor_gaps:
            n = len(t.dor_gaps)
            out.append(
                DecisionRow(
                    KIND_GAP_UNSIGNED,
                    t.id,
                    f"{label} is blocked on {n} structural gap{'' if n == 1 else 's'}",
                    ROLE_APPROVER,
                )
            )
        elif t.route_hint == ROUTE_HUMAN and t.status != "accepted":
            out.append(
                DecisionRow(KIND_ITEM_HUMAN, t.id, f"{label} routed to a human", ROLE_OPERATOR)
            )
        if t.review_verdict in _REWORK_VERDICTS:
            said = str(t.review_verdict).replace("_", " ")
            out.append(
                DecisionRow(KIND_REWORK, t.id, f"{label} — the review said {said}", ROLE_OPERATOR)
            )
        if (
            t.build_status == "clean"
            and not t.pr_url
            and t.status in _FINISHED
            and t.last_event == "delivery.refused"
        ):
            out.append(
                DecisionRow(
                    KIND_DELIVERY_WITHHELD,
                    t.id,
                    f"{label} built clean — delivery withheld",
                    ROLE_APPROVER,
                )
            )
    return sorted(out, key=lambda r: (r.order, r.title))


def due_records(db: Session, repo: str = "") -> list[DecisionDue]:
    """Every clock row, for one repository or all of them, oldest wait first."""
    stmt = select(DecisionDue).order_by(DecisionDue.first_due)
    if repo:
        stmt = stmt.where(DecisionDue.repo == repo)
    return list(db.execute(stmt).scalars().all())


def record_due(
    db: Session, repo: str, rows: Sequence[DecisionRow], *, now: str = ""
) -> dict[tuple[str, str], DecisionDue]:
    """Stamp this pass over ``repo``'s inbox; the CALLER COMMITS.

    A row that is new gets ``first_due = now``. A row that is still there gets a fresh
    ``last_seen``. A row that has come back (``resolved`` set) is re-opened with its
    ORIGINAL ``first_due`` — the wait is the person's, not the derivation's. A clock row
    whose decision has gone gets ``resolved = now`` and is kept: how long something took is
    worth as much as how long it has taken.

    Returns the clock rows of the decisions that are due NOW, keyed ``(kind, key)``.
    """
    stamp = now or _now()
    existing = {(r.kind, r.key): r for r in due_records(db, repo)}
    live: dict[tuple[str, str], DecisionDue] = {}
    for row in rows:
        ident = (row.kind, row.key)
        rec = existing.get(ident)
        if rec is None:
            rec = DecisionDue(
                id=uuid.uuid4().hex,
                repo=repo,
                kind=row.kind,
                key=row.key,
                title=row.title,
                role=row.role,
                first_due=stamp,
                last_seen=stamp,
                resolved="",
            )
            db.add(rec)
        else:
            rec.title = row.title
            rec.role = row.role
            rec.last_seen = stamp
            rec.resolved = ""
        live[ident] = rec
    for ident, rec in existing.items():
        if ident not in live and not rec.resolved:
            rec.resolved = stamp
    return live


def age_seconds(first_due: str, *, now: str = "") -> int:
    """How long a row has been due, in whole seconds; 0 when the stamp cannot be read."""
    try:
        started = _dt.datetime.fromisoformat(first_due)
    except ValueError:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=_dt.UTC)
    end = _dt.datetime.fromisoformat(now) if now else _dt.datetime.now(_dt.UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=_dt.UTC)
    return max(int((end - started).total_seconds()), 0)


__all__ = [
    "KIND_DELIVERY_WITHHELD",
    "KIND_DO_NOT_SHIP",
    "KIND_GAP_UNSIGNED",
    "KIND_ITEM_HUMAN",
    "KIND_REWORK",
    "KIND_ROUTED_HUMAN",
    "KIND_SIGNOFF_DUE",
    "ORDER",
    "DecisionRow",
    "age_seconds",
    "cell_key",
    "decision_rows",
    "due_records",
    "record_due",
]
