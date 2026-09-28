"""The decisions inbox, derived on the server, and the clock over it (G-516, F6).

The inbox is a DERIVATION: every point where a human act is due, folded from the capability
map, the repository's sign-offs, the factory chain, the prevention register, the context
library and the re-measurement plan. Until F6 the screen derived it
(``ui/src/screens/Decisions/decisions.ts``) from five queries per repository, on every screen,
for the nav badge; since F6 this module derives it once and ``GET /decisions`` serves it — one
endpoint the platform team can watch and cache. The screen keeps only the labels and the
render.

This module is that derivation plus the clock: :func:`decision_rows` folds every kind from the
readings, and :func:`record_due` stamps, per ``(repo, kind, key)``, the moment a row FIRST
became due, the last time it was still due, and when it stopped. The rule for a row that
comes back: ``resolved`` is cleared and ``first_due`` stays. A wait a person actually
experienced is not reset by a flicker — a cell that a re-measurement briefly lifted out of
the inbox and back into it has been waiting since it first arrived, and the reading says so.

The Results page still folds the cell and item rows for one repository in the browser
(``decisionsFor``), so the two derivations are pinned to each other: one fixture,
``tests/fixtures/decisions_parity.json``, is read by ``tests/test_server_decisions.py`` and
``ui/src/screens/Decisions/decisions.test.ts``, and both must produce its expected rows.

Two rows are the server's alone, because only it holds their inputs without a fan-out:
``strengthen`` (G-535 — a cell held by its oracle or its controls, the reasons
:data:`crb.core.learn.STRENGTHEN_REASONS` names, which the Learn page's strengthening backlog
lists) and ``remeasure`` (a cell whose evidence predates the apparatus in force, from
:func:`crb.core.learn.remeasure_plan`; only STALE cells — a thin cell's top-up stays on Learn,
where the plan offers it, so the inbox does not fill with every early cell). A held cell is
one row, never two: ``strengthen`` replaces ``routed_human`` for it.

A sign-off that went stale is its own row, ``signoff_stale``, keyed by the sign-off's id and
carrying the sign-off as served; its cell is then no ``signoff_due`` row as well, so a cell is
counted once (ADR-0015: the cell is back in the inbox, asking for a re-sign or a revoke).

Navigation
----------
What it is:   ``decision_rows`` (the inbox's rows for one repository), ``for_viewer`` (the
              row as one person reads it: the act only for a role that can take it, and an
              entry they sponsored never theirs to sign) and ``record_due`` / ``due_records``
              (the clock: when each row first became due).
What it does: Derives every inbox kind from the capability cells, the factory tasks as
              ``GET /factory/{repo}/tasks`` serves them, the prevention register, the library
              index, the stale sign-offs and the re-measurement plan, and keeps one
              ``decisions_due`` row per derived row so the age of a decision survives nobody
              looking at it. Never decides anything and never writes to the ledger: a row
              here is a pointer at an act a person must take.
How:          Pure ``decision_rows`` over ``CapabilityCell`` and served mappings;
              ``record_due`` upserts under the caller's session (the caller commits),
              stamping ``first_due`` on arrival (``INSERT … ON CONFLICT DO NOTHING``, so a
              concurrent first stamp is joined — P-357), ``last_seen`` every pass and
              ``resolved`` when a row goes.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md (the routes the cell rows quote, and the
              inputs the rule does not read),
              docs/adr/0015-signoffs-expire-with-the-apparatus.md (why a stale sign-off puts a
              cell back in the inbox), docs/adr/0026-the-context-standard.md (item 8: an item
              not built; item 10: the library's rows)
Works with:   src/crb/server/routes/decisions.py (reads the inputs and serves it),
              src/crb/server/worker.py (the idle pass that keeps the clock running with nobody
              watching), src/crb/store/models.py (``DecisionDue``), src/crb/core/capability.py
              (``CapabilityCell`` — the cell rows), src/crb/core/learn.py
              (``STRENGTHEN_REASONS``, ``held_by_oracle``, ``remeasure_plan``),
              ui/src/screens/Decisions/decisions.ts (the labels, the render, and the Results
              page's own fold of the cell and item rows)
Tested by:    tests/test_server_decisions.py, tests/test_decisions_kinds.py
Touch when:   never for a new repository (its inbox is derived, not configured); a human act
              is added to the product — a kind here AND in decisions.ts, with the same key.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from crb.core.capability import CapabilityCell
from crb.core.learn import STRENGTHEN_REASONS, held_by_oracle, hold_reason
from crb.core.routing import ROUTE_DELIVER, ROUTE_DO_NOT_SHIP, ROUTE_HUMAN
from crb.server.factory_state import TaskView
from crb.store.models import DecisionDue

#: The inbox's kinds, in the order that decides what blocks what — the same order and the
#: same words as ``ui/src/screens/Decisions/decisions.ts``'s ``ORDER``.
KIND_DO_NOT_SHIP = "do_not_ship"
KIND_GAP_UNSIGNED = "gap_unsigned"
KIND_NOT_BUILT = "not_built"
KIND_SIGNOFF_DUE = "signoff_due"
KIND_SIGNOFF_STALE = "signoff_stale"
KIND_REWORK = "rework"
KIND_DELIVERY_WITHHELD = "delivery_withheld"
KIND_PREVENTION = "prevention"
KIND_ENTRY_STALE = "entry_stale"
KIND_ENTRY_TO_SIGN = "entry_to_sign"
KIND_ITEM_HUMAN = "item_human"
KIND_STRENGTHEN = "strengthen"
KIND_ROUTED_HUMAN = "routed_human"
KIND_REMEASURE = "remeasure"
KIND_ENTRY_RETIRED = "entry_retired"

#: kind → its rank in the list (lower blocks more).
ORDER: dict[str, int] = {
    KIND_DO_NOT_SHIP: 0,
    KIND_GAP_UNSIGNED: 1,
    KIND_NOT_BUILT: 2,
    KIND_SIGNOFF_DUE: 3,
    KIND_SIGNOFF_STALE: 4,
    KIND_REWORK: 5,
    KIND_DELIVERY_WITHHELD: 6,
    KIND_PREVENTION: 7,
    KIND_ENTRY_STALE: 8,
    KIND_ENTRY_TO_SIGN: 9,
    KIND_ITEM_HUMAN: 10,
    KIND_STRENGTHEN: 11,
    KIND_ROUTED_HUMAN: 12,
    KIND_REMEASURE: 13,
    KIND_ENTRY_RETIRED: 14,
}

#: The kinds the worker's idle pass cannot see in full, so it never resolves them: a
#: ``not_built`` row for an item no run has reached comes from the entry gate's preview, which
#: reads the API's own settings (``GET /factory/{repo}/tasks``). The pass stamps the rows it
#: does derive; ``GET /decisions`` resolves the kind.
IDLE_KEEPS_OPEN: frozenset[str] = frozenset({KIND_NOT_BUILT})

#: The reasons a ``strengthen`` row is raised for: the routing reasons test-strengthening work
#: can move (G-535). ``tests/test_decisions_kinds.py`` pins that ``decisions.ts`` lists the same.
STRENGTHEN_KIND_REASONS: tuple[str, ...] = STRENGTHEN_REASONS

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
    cell (``<class>|<size>``), the item id, the library entry, the sign-off id, or the full
    cell and mode of a re-measurement — and ``(kind, key)`` is the row's identity, the
    identity the clock is kept under.

    ``act`` is the verb on the button, ``href`` the screen where the act is recorded or read,
    ``evidence`` the line under the title and ``reason_code`` the routing code at its tail.
    ``sponsor`` and ``mine_title`` let :func:`for_viewer` show an entry's sponsor the
    read-only row the API's ``same_person`` refusal implies; ``signoff`` is the stale
    sign-off as ``GET /signoffs`` serves it."""

    kind: str
    key: str
    title: str
    role: str
    evidence: str = ""
    act: str = ""
    href: str = ""
    reason_code: str = ""
    sponsor: str = ""
    mine_title: str = ""
    signoff: Mapping[str, Any] | None = None

    @property
    def order(self) -> int:
        return ORDER.get(self.kind, len(ORDER))


def cell_key(capability_class: str, size: str) -> str:
    """``<class>|<size>`` — the screen's ``cellKeyOf``."""
    return f"{capability_class}|{size}"


def _enc(s: str) -> str:
    """``encodeURIComponent``: the links the screen built, built here byte for byte."""
    return quote(s, safe="!~*'()")


def pct(x: float) -> str:
    """``(x * 100).toFixed(0)`` with its ``%`` — JavaScript rounds the EXACT value half up, so
    this does too (Python's ``round`` would give 12 % where the screen said 13 %)."""
    exact = Decimal(float(x) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{exact}%"


def _learn(repo: str, anchor: str, **params: str) -> str:
    extra = "".join(f"&{k}={_enc(v)}" for k, v in params.items())
    return f"/learn?repo={_enc(repo)}{extra}#{anchor}"


def prevention_rows(register: Mapping[str, Any] | None, repo: str = "") -> list[DecisionRow]:
    """The prevention loop's rows (ADR-0020 §9), from the register as ``GET /learn/register``
    serves it: a filed item nobody has registered (an operator's act — "a prevention needs
    an owner"), a class that reopened after it closed, and a change the loop retired for harm
    (both for anyone to read). A product-scoped proposal is never a row: it is the product's
    to fix, not the team's. Keys are the class signature with what is due —
    ``<signature>|owner|<item id>``, ``<signature>|reopened``, ``<signature>|harm``."""
    if not register:
        return []
    out: list[DecisionRow] = []
    for e in register.get("entries", []) or []:
        sig = str(e.get("signature", ""))
        st = dict(e.get("stratum") or {})
        ev = (
            f"{st.get('k', 0)} of {st.get('n', 0)} {st.get('mode', '')} first attempts on "
            f"{e.get('tasks', 0)} tasks · {e.get('status', '')}"
        )
        href = _learn(repo, "prevention", **{"class": sig})
        for p in e.get("proposals", []) or []:
            if p.get("registered") or p.get("scope") == "product":
                continue
            out.append(
                DecisionRow(
                    KIND_PREVENTION,
                    f"{sig}|owner|{p.get('item_id', '')}",
                    f"A prevention needs an owner — {sig}: {p.get('title', '')}",
                    ROLE_OPERATOR,
                    evidence=f"{ev} · {p.get('level', '')}",
                    act="Register",
                    href=href,
                )
            )
        if "reopened" in (e.get("qualifiers") or []):
            out.append(
                DecisionRow(
                    KIND_PREVENTION,
                    f"{sig}|reopened",
                    f"{sig} reopened after it was closed",
                    ROLE_VIEWER,
                    evidence=ev,
                    act="Read why",
                    href=href,
                )
            )
        if any(
            h.get("kind") == "decided" and h.get("summary") == "harm"
            for h in e.get("history", []) or []
        ):
            out.append(
                DecisionRow(
                    KIND_PREVENTION,
                    f"{sig}|harm",
                    f"A change for {sig} was retired for harm",
                    ROLE_VIEWER,
                    evidence=ev,
                    act="Read why",
                    href=href,
                )
            )
    return out


def library_rows(library: Mapping[str, Any] | None, repo: str = "") -> list[DecisionRow]:
    """The context library's rows (ADR-0026 item 10), from ``GET /library/{repo}``'s entries:
    a proposal nobody sponsored (an operator's Sponsor), a sponsored entry waiting for its
    second person (an approver's Sign), a signed entry whose source changed (an approver signs
    again or retires it) and an entry the measurement retired (anyone reads why). The entry's
    sponsor rides on the row: :func:`for_viewer` gives them the read-only row, because the API
    refuses a sponsor's own signature ``same_person``."""
    if not library:
        return []
    out: list[DecisionRow] = []
    href = f"/library/{_enc(repo)}#index"
    for e in library.get("entries", []) or []:
        eid = str(e.get("entry_id", ""))
        rec = dict(e.get("entry") or {})
        status = str(e.get("status", ""))
        sponsor = str(e.get("sponsor", "") or "")
        who = str(e.get("sponsor_name", "") or "") or sponsor
        if status == "proposed" and not sponsor:
            out.append(
                DecisionRow(
                    KIND_ENTRY_TO_SIGN,
                    eid,
                    f"{eid} was proposed by {rec.get('proposed_by', '')} and needs a person to "
                    "sponsor it",
                    ROLE_OPERATOR,
                    evidence=f"{rec.get('kind', '')} · {rec.get('title', '')}",
                    act="Sponsor",
                    href=href,
                )
            )
        elif status == "proposed":
            out.append(
                DecisionRow(
                    KIND_ENTRY_TO_SIGN,
                    eid,
                    f"{eid} waits for a second person to sign it",
                    ROLE_APPROVER,
                    evidence=f"sponsored by {who} · {rec.get('title', '')}",
                    act="Sign",
                    href=href,
                    sponsor=sponsor,
                    mine_title=f"{eid} waits for another approver to sign it — you sponsored it",
                )
            )
        elif status == "stale":
            stale = dict(e.get("stale") or {})
            path = str(stale.get("path", "") or "") or "its source file"
            head = str(stale.get("head_commit", "") or "")
            approver = str(e.get("approver_name", "") or "") or str(e.get("approver", "") or "")
            signed = f"signed by {approver}" if e.get("approver") else "not yet signed"
            out.append(
                DecisionRow(
                    KIND_ENTRY_STALE,
                    eid,
                    f"{eid} went stale: {path} changed or went",
                    ROLE_APPROVER,
                    evidence=f"at {head[:12] if head else 'the head'} · {signed}",
                    act="Sign again or retire",
                    href=href,
                    sponsor=sponsor,
                    mine_title=(
                        f"{eid} went stale: {path} changed or went — you sponsored it, so "
                        "another approver signs it again"
                    ),
                )
            )
        elif status == "retired" and dict(e.get("retired") or {}).get("by") == "measurement":
            ret = dict(e.get("retired") or {})
            out.append(
                DecisionRow(
                    KIND_ENTRY_RETIRED,
                    eid,
                    f"{eid} was retired by measurement",
                    ROLE_VIEWER,
                    evidence=f"reading {ret.get('reading_id', '')} · {ret.get('reason', '')}",
                    act="Read why",
                    href=href,
                )
            )
    return out


def stale_signoff_rows(stale: Iterable[Mapping[str, Any]], repo: str = "") -> list[DecisionRow]:
    """One ``signoff_stale`` row per attestation ``GET /signoffs`` serves ``stale`` and not
    revoked: signed on an earlier apparatus, checks arm or posture class, or by an approver who
    has since left (ADR-0015, DL-120). An approver revokes it or signs again; it licenses
    nothing meanwhile."""
    out: list[DecisionRow] = []
    for s in stale:
        if not s.get("stale") or s.get("revoked"):
            continue
        cell = dict(s.get("cell") or {})
        cls, size = str(cell.get("capability_class", "")), str(cell.get("size", ""))
        who = str(s.get("approver_name", "") or "") or str(s.get("approver", "") or "")
        out.append(
            DecisionRow(
                KIND_SIGNOFF_STALE,
                str(s.get("id", "")),
                f"{cls} {_TIMES} {size} was signed on an earlier instrument — revoke or re-sign",
                ROLE_APPROVER,
                evidence=f"signed {str(s.get('created', ''))[:10]} by {who} · "
                f"{s.get('stale_reason', '') or 'stale'}",
                act="Revoke or re-sign",
                href=f"/signoff?repo={_enc(repo)}&cell={_enc(cell_key(cls, size))}",
                signoff=s,
            )
        )
    return out


def remeasure_rows(
    plan: Mapping[str, Any] | None,
    repo: str = "",
    *,
    in_flight: Iterable[tuple[str, str]] = (),
) -> list[DecisionRow]:
    """One ``remeasure`` row per cell of the re-measurement plan (:func:`crb.core.learn.
    remeasure_plan`, as ``GET /learn/remeasure`` serves it): its evidence predates the
    apparatus in force and the current rows do not reach the rule's first look. A cell whose
    queued runs have not finished (``in_flight``: ``(label, mode)``) asks nobody for anything.
    The evidence line says the rows needed and the estimate, or that the cost is not known —
    never a zero that reads as free."""
    if not plan:
        return []
    busy = set(in_flight)
    current = str(plan.get("current_apparatus", ""))
    out: list[DecisionRow] = []
    for c in plan.get("cells", []) or []:
        label, mode = str(c.get("label", "")), str(c.get("mode", ""))
        if (label, mode) in busy:
            continue
        cell = dict(c.get("cell") or {})
        cls, size = str(cell.get("capability_class", "")), str(cell.get("size", ""))
        was = ", ".join(str(v) for v in c.get("stale_versions", []) or []) or "an earlier one"
        n = int(c.get("n_needed", 0) or 0)
        cost = (
            f"est. ${float(c.get('est_cost_usd', 0.0) or 0.0):.2f}"
            if c.get("cost_known")
            else "cost not known"
        )
        config = f"{cell.get('builder', '')}/{cell.get('model', '')}@{cell.get('provider', '')}"
        out.append(
            DecisionRow(
                KIND_REMEASURE,
                f"{label}|{mode}",
                f"{cls} {_TIMES} {size} ({mode}) was measured under apparatus {was}, not {current}",
                ROLE_OPERATOR,
                evidence=f"{n} row{'' if n == 1 else 's'} needed · {cost} · {config}",
                act="Queue re-measurement",
                href=_learn(repo, "remeasure"),
            )
        )
    return out


def _task(t: TaskView | Mapping[str, Any]) -> Mapping[str, Any]:
    return t.to_dict() if isinstance(t, TaskView) else t


def _cell_rows(
    cells: Iterable[CapabilityCell], repo: str, stale_cells: frozenset[str]
) -> list[DecisionRow]:
    q = f"repo={_enc(repo)}"
    out: list[DecisionRow] = []
    for c in cells:
        if c.n <= 0:
            continue
        # the screen's own words for a cell, so the recorded title reads like the row
        label = f"{c.key.capability_class} {_TIMES} {c.key.size}"
        key = cell_key(c.key.capability_class, c.key.size)
        s = c.stats
        held = held_by_oracle(c)
        code = hold_reason(c) if held and c.route != ROUTE_DO_NOT_SHIP else c.reason_code
        ev = (
            f"n={c.n} on {s.n_tasks if s is not None else 0} tasks · "
            f"{pct(round(s.point, 4) if s else 0.0)} "
            f"[{pct(round(s.ci.low, 4) if s else 0.0)}, {pct(round(s.ci.high, 4) if s else 0.0)}]"
            f"{f' · {code}' if code else ''}"
        )
        if c.route == ROUTE_DO_NOT_SHIP:
            out.append(
                DecisionRow(
                    KIND_DO_NOT_SHIP,
                    key,
                    f"{label} must not ship — false-Q1 in the cell",
                    ROLE_VIEWER,
                    evidence=ev,
                    act="Investigate",
                    href=f"/ledger?{q}",
                    reason_code=code,
                )
            )
        elif c.route == ROUTE_DELIVER and not c.earned:
            if key in stale_cells:
                continue  # its stale sign-off is the row: revoke or re-sign (ADR-0015)
            out.append(
                DecisionRow(
                    KIND_SIGNOFF_DUE,
                    key,
                    f"{label} clears the bar — attest it or decline",
                    ROLE_APPROVER,
                    evidence=ev,
                    act="Attest",
                    href=f"/signoff?{q}&cell={_enc(key)}",
                    reason_code=code,
                )
            )
        elif held:
            # G-535: held by its oracle or its controls — ONE row, the strengthening work
            out.append(
                DecisionRow(
                    KIND_STRENGTHEN,
                    key,
                    f"{label} is held until its tests are stronger",
                    ROLE_OPERATOR,
                    evidence=ev,
                    act="Strengthen the tests",
                    href=_learn(repo, "strengthen"),
                    reason_code=code,
                )
            )
        elif c.route == ROUTE_HUMAN:
            out.append(
                DecisionRow(
                    KIND_ROUTED_HUMAN,
                    key,
                    f"{label} routed to a human — {c.reason}",
                    ROLE_VIEWER,
                    evidence=ev,
                    act="Read why",
                    href=f"/routing?{q}",
                    reason_code=code,
                )
            )
    return out


def _item_rows(tasks: Iterable[TaskView | Mapping[str, Any]], repo: str) -> list[DecisionRow]:
    q = f"repo={_enc(repo)}"
    out: list[DecisionRow] = []
    for raw in tasks:
        t = _task(raw)
        tid = str(t.get("id", ""))
        href = f"/factory?{q}&item={_enc(tid)}"
        label = f"{tid} {t.get('title', '')}"
        cell = f"{t.get('capability_class', '')} {_TIMES} {t.get('size', '')}"
        status = str(t.get("status", ""))
        entry = t.get("entry")
        gaps = list(t.get("dor_gaps") or ())
        if entry:
            # ADR-0026 item 8 — the item waits here, NOT BUILT: an approver may fund one
            # calibration build (never a pull request), or the ticket gains what its cell's
            # standard needs. A funded calibration build waits on the next run.
            if not t.get("calibration"):
                fund = dict(t.get("way_forward") or {}).get("action") == "fund_calibration"
                needs = [str(n) for n in dict(entry).get("needs") or ()]
                attach = f" · attach {', '.join(needs)}" if needs else ""
                stop = str(dict(entry).get("code", "")).replace("_", " ")
                out.append(
                    DecisionRow(
                        KIND_NOT_BUILT,
                        tid,
                        f"{label} is not built — {stop}",
                        ROLE_APPROVER if fund else ROLE_OPERATOR,
                        evidence=f"{cell}{attach}",
                        act="Fund a calibration build" if fund else "Decide",
                        href=href,
                    )
                )
        elif gaps:
            n = len(gaps)
            out.append(
                DecisionRow(
                    KIND_GAP_UNSIGNED,
                    tid,
                    f"{label} is blocked on {n} structural gap{'' if n == 1 else 's'}",
                    ROLE_APPROVER,
                    evidence=", ".join(str(g) for g in gaps),
                    act="Sign a gap",
                    href=href,
                )
            )
        elif t.get("route_hint") == ROUTE_HUMAN and status != "accepted":
            out.append(
                DecisionRow(
                    KIND_ITEM_HUMAN,
                    tid,
                    f"{label} routed to a human",
                    ROLE_OPERATOR,
                    evidence=f"{cell} · {status}",
                    act="Decide",
                    href=href,
                )
            )
        verdict = t.get("review_verdict")
        if verdict in _REWORK_VERDICTS:
            out.append(
                DecisionRow(
                    KIND_REWORK,
                    tid,
                    f"{label} — the review said {str(verdict).replace('_', ' ')}",
                    ROLE_OPERATOR,
                    evidence=f"build {t.get('build_status', '')} · {status}",
                    act="Review",
                    href=href,
                )
            )
        if (
            t.get("build_status") == "clean"
            and not t.get("pr_url")
            and status in _FINISHED
            and t.get("last_event") == "delivery.refused"
        ):
            out.append(
                DecisionRow(
                    KIND_DELIVERY_WITHHELD,
                    tid,
                    f"{label} built clean — delivery withheld by the route",
                    ROLE_APPROVER,
                    evidence=cell,
                    act="See the route",
                    href=href,
                )
            )
    return out


def decision_rows(
    cells: Iterable[CapabilityCell] = (),
    tasks: Iterable[TaskView | Mapping[str, Any]] = (),
    register: Mapping[str, Any] | None = None,
    *,
    repo: str = "",
    library: Mapping[str, Any] | None = None,
    stale: Sequence[Mapping[str, Any]] = (),
    remeasure: Mapping[str, Any] | None = None,
    in_flight: Iterable[tuple[str, str]] = (),
) -> list[DecisionRow]:
    """The inbox's rows for one repository, ordered by what blocks what.

    ``cells`` are the (class × size) cells of the repository's SIGNED map — the sign-offs
    already overlaid, so ``cell.earned`` is "a human has attested this, on this apparatus,
    with the false-Q1 floor intact". ``tasks`` are the factory items as ``GET
    /factory/{repo}/tasks`` serves them (a ``TaskView`` is read through its ``to_dict``).
    ``register`` is the prevention register (``Register.to_dict()``), ``library`` the library
    index, ``stale`` the stale sign-offs as served, ``remeasure`` the re-measurement plan with
    ``in_flight`` the ``(label, mode)`` cells whose queued runs have not finished. An
    unmeasured cell (``n == 0``) is not a decision: nobody is waiting on it.
    """
    stale_list = [s for s in stale if s.get("stale") and not s.get("revoked")]
    stale_cells = frozenset(
        cell_key(
            str(dict(s.get("cell") or {}).get("capability_class", "")),
            str(dict(s.get("cell") or {}).get("size", "")),
        )
        for s in stale_list
    )
    out: list[DecisionRow] = [
        *_cell_rows(cells, repo, stale_cells),
        *stale_signoff_rows(stale_list, repo),
        *_item_rows(tasks, repo),
        *prevention_rows(register, repo),
        *library_rows(library, repo),
        *remeasure_rows(remeasure, repo, in_flight=in_flight),
    ]
    return sorted(out, key=lambda r: (r.order, r.title))


def can_act(row: DecisionRow, role: str, rank: Mapping[str, int]) -> bool:
    """Whether a person of ``role`` can take the row's act: anyone reads a viewer's row; any
    other act needs the row's role or higher (``ROLE_RANK``)."""
    return row.role == ROLE_VIEWER or rank.get(role, -1) >= rank.get(row.role, len(rank))


def for_viewer(row: DecisionRow, me: str) -> DecisionRow:
    """The row as the person ``me`` reads it: an entry they sponsored is never theirs to sign
    or sign again (the API refuses it ``same_person``), so it becomes a read-only row naming
    that another approver acts. Every other row is the same for everyone."""
    if row.sponsor and me and row.sponsor == me:
        return replace(row, title=row.mine_title or row.title, act="Read", role=ROLE_VIEWER)
    return row


def due_records(db: Session, repo: str = "") -> list[DecisionDue]:
    """Every clock row, for one repository or all of them, oldest wait first."""
    stmt = select(DecisionDue).order_by(DecisionDue.first_due)
    if repo:
        stmt = stmt.where(DecisionDue.repo == repo)
    return list(db.execute(stmt).scalars().all())


def record_due(
    db: Session,
    repo: str,
    rows: Sequence[DecisionRow],
    *,
    now: str = "",
    keep_open: frozenset[str] = frozenset(),
) -> dict[tuple[str, str], DecisionDue]:
    """Stamp this pass over ``repo``'s inbox; the CALLER COMMITS.

    A row that is new gets ``first_due = now``. A row that is still there gets a fresh
    ``last_seen``. A row that has come back (``resolved`` set) is re-opened with its
    ORIGINAL ``first_due`` — the wait is the person's, not the derivation's. A clock row
    whose decision has gone gets ``resolved = now`` and is kept: how long something took is
    worth as much as how long it has taken.

    ``keep_open`` names the kinds this pass cannot see in full: it stamps the rows of them it
    derived and resolves none of them. The worker's idle pass has no entry-gate preview, so
    it keeps ``not_built`` open (:data:`IDLE_KEEPS_OPEN`) — otherwise it would resolve every
    row ``GET /decisions`` stamped for an item no run has reached, and the two passes would
    flip each other's rows.

    Returns the clock rows of the decisions that are due NOW, keyed ``(kind, key)``.
    """
    stamp = now or _now()
    existing = {(r.kind, r.key): r for r in due_records(db, repo)}
    live: dict[tuple[str, str], DecisionDue] = {}
    for row in rows:
        ident = (row.kind, row.key)
        rec = existing.get(ident)
        if rec is None:
            rec = _first_stamp(db, repo, row, stamp)
        rec.title = row.title
        rec.act_role = row.role
        rec.last_seen = stamp
        rec.resolved = ""
        live[ident] = rec
    for ident, rec in existing.items():
        if ident not in live and not rec.resolved and rec.kind not in keep_open:
            rec.resolved = stamp
    return live


def _first_stamp(db: Session, repo: str, row: DecisionRow, stamp: str) -> DecisionDue:
    """The clock row for a decision this pass saw arrive — inserted, or JOINED when another
    stamper got there first.

    Two stampers run: the worker's idle pass and every ``GET /decisions``. Both read the
    clock, then write it, under the unique ``(repo, kind, key)``; when the other commits the
    same first stamp in between, a plain insert raised ``IntegrityError`` — out of the
    worker's pass, ending the loop, and out of the route as a 500 (P-357). So the insert is
    ``ON CONFLICT DO NOTHING`` on that identity, in the dialect's own words (SQLite and
    PostgreSQL both say it), and the row is then read back: ours, or the earlier one with its
    earlier ``first_due`` — the wait is the decision's, whoever stamped it first."""
    values = {
        "id": uuid.uuid4().hex,
        "repo": repo,
        "kind": row.kind,
        "key": row.key,
        "title": row.title,
        "act_role": row.role,
        "first_due": stamp,
        "last_seen": stamp,
        "resolved": "",
    }
    identity = ["repo", "kind", "key"]
    if db.get_bind().dialect.name == "postgresql":
        stmt: Any = (
            pg_insert(DecisionDue).values(**values).on_conflict_do_nothing(index_elements=identity)
        )
    else:
        stmt = (
            sqlite_insert(DecisionDue)
            .values(**values)
            .on_conflict_do_nothing(index_elements=identity)
        )
    db.execute(stmt)
    return db.execute(
        select(DecisionDue).where(
            DecisionDue.repo == repo, DecisionDue.kind == row.kind, DecisionDue.key == row.key
        )
    ).scalar_one()


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
    "IDLE_KEEPS_OPEN",
    "KIND_DELIVERY_WITHHELD",
    "KIND_DO_NOT_SHIP",
    "KIND_ENTRY_RETIRED",
    "KIND_ENTRY_STALE",
    "KIND_ENTRY_TO_SIGN",
    "KIND_GAP_UNSIGNED",
    "KIND_ITEM_HUMAN",
    "KIND_NOT_BUILT",
    "KIND_PREVENTION",
    "KIND_REMEASURE",
    "KIND_REWORK",
    "KIND_ROUTED_HUMAN",
    "KIND_SIGNOFF_DUE",
    "KIND_SIGNOFF_STALE",
    "KIND_STRENGTHEN",
    "ORDER",
    "STRENGTHEN_KIND_REASONS",
    "DecisionRow",
    "age_seconds",
    "can_act",
    "cell_key",
    "decision_rows",
    "due_records",
    "for_viewer",
    "library_rows",
    "pct",
    "prevention_rows",
    "record_due",
    "remeasure_rows",
    "stale_signoff_rows",
]
