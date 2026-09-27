"""A run's spend cap (F5b): ``max_cost_usd`` summed over the run's attempts, kept by the run.

A :class:`~crb.builders.base.Budget` caps one attempt. A run of thirty attempts had no
ceiling, so the Measure and Factory pages could only state an estimate. A build run
(replay, blind, factory) may now declare ``max_cost_usd``, and the worker asks this module
before every attempt (a factory run: before every item) whether the next one could take the
run's spend past it:

* **spent** is what the run's ledger rows cost, as the run page shows it (``cost_usd``
  summed over ``grades`` rows with this ``run_id``), so a reclaimed run counts the attempts
  its first claim made;
* **the reserve** is the most the next attempt may cost: its own cost cap when it has one
  (a guarantee: the builder stops at it), else the dearest attempt the run has made so far
  (a guard, not a guarantee: nothing bounds a first attempt with no cost cap). A factory
  item is reserved at every rung, once and again for each rework;
* the attempt is admitted while ``spent + reserve <= cap``; otherwise the run stops before
  it, ``failed`` with ``stopped_code: spend_cap`` and a ``run.spend_cap`` event naming what
  was spent, the cap and the reserve;
* an attempt whose cost was not known stops a capped run at once: a cap that cannot see a
  cost cannot be kept. ``POST /runs`` refuses a capped run with a rung whose model has no
  known price (:func:`unpriced_rungs`), so this is the second line, not the first.

Navigation
----------
What it is:   The per-run spend cap's rules — what has been spent, what the next attempt or
              item is reserved at, and whether it is admitted — and the priced-model check.
What it does: ``SpendCap.check`` answers "may the next attempt run?" with ``None`` or a
              ``Halt`` (the reason and the event's payload); ``Spend.of_rows`` reads what a
              run's rows cost; ``unpriced_rungs`` names the rungs whose cost the cap could not
              see.
How:          Pure functions over ``GradeRow.cost_usd`` / ``cost_known`` and
              ``crb.builders.budget.price_for``; the worker wires ``check`` into
              ``RunSpec.admit`` (replay, blind) and the factory's ``stop`` (per item).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/worker.py (asks before each attempt or item),
              src/crb/core/run.py (``RunSpec.admit``), src/crb/server/routes/runs.py (stores
              ``params.max_cost_usd`` and refuses an unpriced capped run),
              src/crb/builders/budget.py (``price_for``, ``budget_for_rung``)
Tested by:    tests/test_worker_spend_cap.py, tests/test_server_spend_cap.py
Touch when:   a new kind of spend is recorded outside the run's ledger rows (count it in
              ``Spend``), or a new unit of work needs a reserve.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.builders.budget import Pricing, price_for
from crb.core.ledger import GradeRow

#: ``counts.stopped_code`` of a run that stopped itself at its spend cap.
STOP_SPEND_CAP = "spend_cap"
#: Builders whose price is known without a table: the fixture spends nothing and says so.
PRICED_WITHOUT_TABLE = frozenset({"fixture_gold"})
#: Cents are the ledger's precision; a sum of float costs may miss the cap by less.
_EPSILON = 1e-9


@dataclass(frozen=True)
class Spend:
    """What a run has spent: the total, its dearest attempt, and how many attempts had no
    known cost."""

    spent: float
    dearest: float
    unknown: int = 0

    @classmethod
    def of_rows(cls, rows: Iterable[GradeRow]) -> Spend:
        spent = dearest = 0.0
        unknown = 0
        for r in rows:
            spent += r.cost_usd
            dearest = max(dearest, r.cost_usd)
            unknown += int(not r.cost_known)
        return cls(spent, dearest, unknown)


@dataclass(frozen=True)
class Halt:
    """A refused attempt or item: the run's stop reason and the event's payload."""

    reason: str
    payload: Mapping[str, Any] = field(default_factory=dict)


def _usd(v: float) -> str:
    return f"${v:,.2f}"


@dataclass(frozen=True)
class SpendCap:
    """``params.max_cost_usd`` of one run."""

    cap_usd: float

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> SpendCap | None:
        raw = params.get("max_cost_usd")
        return cls(float(raw)) if raw else None

    def check(
        self,
        spend: Spend,
        *,
        reserve: float,
        unit: str = "attempt",
        attempts: int = 1,
    ) -> Halt | None:
        """``None`` admits the next ``unit``; a :class:`Halt` refuses it. For an attempt,
        ``reserve`` is its own cost cap (``0`` when it has none, and then the dearest attempt
        so far stands in); for an item, the caller's reserve over its ``attempts``."""
        payload: dict[str, Any] = {
            "cap_usd": self.cap_usd,
            "spent_usd": round(spend.spent, 6),
            "unit": unit,
        }
        if spend.unknown:
            reason = (
                f"spend cap: an attempt's cost was not known ({spend.unknown} of this run's "
                "attempts), so the cap cannot be kept and the run stopped"
            )
            return Halt(reason, {**payload, "reserve_usd": None, "reserve_from": "unknown_cost"})
        if unit == "attempt" and reserve > 0:
            source, why = "attempt_cap", f"up to its own cost cap of {_usd(reserve)}"
        elif unit == "attempt":
            reserve = spend.dearest
            source = "dearest_attempt"
            why = (
                "an amount no cap of its own bounds, counted at the dearest attempt this run "
                f"has made, {_usd(reserve)}"
            )
        else:
            source = unit
            why = f"up to {_usd(reserve)} ({attempts} attempts: every rung, once more per rework)"
        if spend.spent + reserve <= self.cap_usd + _EPSILON:
            return None
        reason = (
            f"spend cap: {_usd(spend.spent)} of {_usd(self.cap_usd)} spent; the next {unit} "
            f"could cost {why}, which would pass the cap, so the run stopped before it"
        )
        return Halt(reason, {**payload, "reserve_usd": round(reserve, 6), "reserve_from": source})

    def admit(
        self, spend: Spend, *, reserve: float, unit: str = "attempt", attempts: int = 1
    ) -> str:
        """:meth:`check` as the stop reason (``""`` admits)."""
        halt = self.check(spend, reserve=reserve, unit=unit, attempts=attempts)
        return halt.reason if halt is not None else ""


def item_reserve(
    attempt_caps: Sequence[float], spend: Spend, *, max_rework: int
) -> tuple[float, int]:
    """``(reserve, attempts)`` for one factory item: every rung, and every rung again for
    each rework, each at its own cost cap or, without one, the dearest attempt so far."""
    per_pass = sum(c if c > 0 else spend.dearest for c in attempt_caps)
    passes = 1 + max(0, max_rework)
    return per_pass * passes, len(attempt_caps) * passes


def unpriced_rungs(
    rungs: Iterable[tuple[str, str]], table: Mapping[str, Pricing]
) -> list[tuple[str, str]]:
    """The ``(builder, model)`` pairs whose cost the cap could not see: no known price for
    the model in ``table`` (``price_for``'s exact → prefix → provider rule), and not a
    builder whose price is known without one."""
    out: list[tuple[str, str]] = []
    for builder, model in rungs:
        if builder in PRICED_WITHOUT_TABLE:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            known = price_for(model, table).known
        if not known and (builder, model) not in out:
            out.append((builder, model))
    return out


__all__ = [
    "PRICED_WITHOUT_TABLE",
    "STOP_SPEND_CAP",
    "Halt",
    "Spend",
    "SpendCap",
    "item_reserve",
    "unpriced_rungs",
]
