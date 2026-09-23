"""The flow fold — how long each value stream takes, what it spent, and what nobody measured.

Every value stream in ``docs/dod/streams/`` carries a MEASURE criterion: *the product shows
this stream's own numbers*. This module is the arithmetic that answers it, and nothing else.
It derives; it never stores. The server hands it pairs of timestamps that are already in the
store (events, runs, graded rows, sign-offs, the factory's evidence chain) and pairs of
``(cost_usd, cost_known)``, and it reduces them to:

* a **lead time** per named milestone pair — n, median, minimum, maximum, and how many pairs
  were dropped because a stamp was unreadable or the end preceded the start;
* the **spend** — the sum of the rows whose cost is a measurement. An unknown cost is never
  counted as zero (``GradeRow.cost_known``): the sum is over priced rows only and the reading
  says how many rows were unpriced, so a reader can see how much of the money is missing;
* the **figures nobody measured** — named, with why, and with the gap id that would close
  them. A number the product does not capture is stated as absent, never derived from a
  neighbouring number that happens to exist.

Two rules hold everywhere: **an unmeasured figure is ``None``, never 0**, and **n travels with
every figure**. A median of no durations is not zero seconds, and a spend of no priced rows is
not $0.00.

Navigation
----------
What it is:   The pure fold behind ``GET /flow``: ``LeadTime``, ``Spend``, ``NotCaptured``,
              ``StreamFlow``, ``FlowReading`` and the four reductions that build them.
What it does: Reduces (start, end) timestamp pairs to a lead time with n / median / min / max,
              reduces ``(cost_usd, cost_known)`` pairs to a spend that honours an unknown cost,
              divides a known spend per unit, and names the figures the product does not
              capture so a screen can say so instead of inventing them.
How:          ``datetime.fromisoformat`` (``Z`` accepted, a naive stamp read as UTC) → seconds
              → ``statistics.median``; dataclasses with ``to_dict`` for the API; stdlib only,
              so ``crb.core`` stays dependency-free.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/flow.py (gathers the pairs this module reduces, one per stream),
              src/crb/server/routes/flow.py (serves the reading at ``GET /flow``),
              src/crb/core/ledger.py (``GradeRow.cost_known`` — the flag the spend honours),
              src/crb/core/version.py (``APPARATUS_VERSION`` — the stamp a reading carries),
              ui/src/components/FlowPanel.tsx (renders one stream's figures on its own screen)
Tested by:    tests/test_flow.py, tests/test_server_routes_flow.py
Touch when:   a value stream is added (one entry in ``STREAM_NAMES``); never for a new
              repository, and never to make an unmeasured figure read as zero.
"""

from __future__ import annotations

import datetime as _dt
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The value streams, in the order a reader meets them, with the name each screen shows.
STREAM_NAMES: dict[str, str] = {
    "connect-and-prove": "Connect & prove",
    "measure": "Measure",
    "decide-and-license": "Decide & license",
    "manufacture-and-deliver": "Manufacture & deliver",
    "learn": "Learn",
    "run-the-platform": "Run the platform",
}


def parse_ts(value: str) -> _dt.datetime | None:
    """One stored timestamp as an aware UTC ``datetime``, or ``None`` when it cannot be read.

    The store writes second-precision ISO-8601 UTC and the event stream writes milliseconds;
    both parse. A ``Z`` suffix is accepted, and a stamp with no offset is read as UTC — every
    writer in this product stamps UTC. An unreadable stamp is ``None``, never "now" and never
    the epoch: a lead time built on a guessed stamp would be a fabricated number.
    """
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = f"{s[:-1]}+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.replace(tzinfo=_dt.UTC) if dt.tzinfo is None else dt.astimezone(_dt.UTC)


def median(values: Sequence[float]) -> float | None:
    """The median of ``values``, or ``None`` when there are none (never 0.0)."""
    return statistics.median(values) if values else None


@dataclass(frozen=True)
class LeadTime:
    """How long one named milestone pair took, with its n.

    ``median_s`` / ``min_s`` / ``max_s`` are ``None`` when ``n`` is 0 — an unmeasured
    duration, not a zero one. ``dropped`` counts pairs this fold refused: a stamp it could
    not read, or an end before its start (a clock or an ordering defect the reader should
    see rather than a negative duration folded into a median). ``reason`` says why nothing
    was measured, and is empty once anything was.
    """

    key: str
    label: str
    n: int = 0
    median_s: float | None = None
    min_s: float | None = None
    max_s: float | None = None
    dropped: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "n": self.n,
            "median_s": self.median_s,
            "min_s": self.min_s,
            "max_s": self.max_s,
            "dropped": self.dropped,
            "reason": self.reason,
        }


def lead_time(
    key: str,
    label: str,
    pairs: Iterable[tuple[str, str]],
    *,
    reason: str = "",
) -> LeadTime:
    """Reduce ``(start, end)`` stamps to one :class:`LeadTime`.

    ``reason`` is carried only while ``n`` is 0: once a duration is measured, the honest
    empty sentence is no longer true and is dropped.
    """
    seconds: list[float] = []
    dropped = 0
    for start, end in pairs:
        a, b = parse_ts(start), parse_ts(end)
        if a is None or b is None or b < a:
            dropped += 1
            continue
        seconds.append((b - a).total_seconds())
    if not seconds:
        return LeadTime(key=key, label=label, n=0, dropped=dropped, reason=reason)
    return LeadTime(
        key=key,
        label=label,
        n=len(seconds),
        median_s=median(seconds),
        min_s=min(seconds),
        max_s=max(seconds),
        dropped=dropped,
    )


@dataclass(frozen=True)
class Spend:
    """What a stream spent, with how much of the money is missing.

    ``usd`` sums the rows whose cost is a measurement and is ``None`` when there are none —
    an unpriced row is never counted as zero. ``rows_unpriced`` is how many rows carried a
    cost the product cannot vouch for (``GradeRow.cost_known`` is false), so a reader knows
    the sum is a floor.
    """

    usd: float | None = None
    rows_priced: int = 0
    rows_unpriced: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "usd": self.usd,
            "rows_priced": self.rows_priced,
            "rows_unpriced": self.rows_unpriced,
        }


def spend_of(rows: Iterable[tuple[float, bool]]) -> Spend:
    """Reduce ``(cost_usd, cost_known)`` pairs to a :class:`Spend`."""
    priced = [cost for cost, known in rows if known]
    unpriced = sum(1 for _, known in rows if not known)
    return Spend(
        usd=round(sum(priced), 6) if priced else None,
        rows_priced=len(priced),
        rows_unpriced=unpriced,
    )


def per_unit(spend: Spend, units: int) -> float | None:
    """A known spend divided by ``units`` (the cost of one certified change), or ``None``.

    ``None`` when nothing is priced or there are no units: a cost per change with no change
    to divide by is not zero, it is unmeasured.
    """
    if spend.usd is None or units <= 0:
        return None
    return round(spend.usd / units, 6)


@dataclass(frozen=True)
class NotCaptured:
    """A figure the stream's criterion asks for that the product does not record.

    It is served, not hidden: the screen prints the figure's name, why it is absent and the
    gap id that would close it, so nobody reads its absence as a zero.
    """

    figure: str
    why: str
    gap: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"figure": self.figure, "why": self.why, "gap": self.gap}


@dataclass(frozen=True)
class StreamFlow:
    """One value stream's own numbers: its lead times, its spend, its counts, its absences.

    ``spend_label`` says in words WHICH rows the spend covers, because the streams do not all
    buy the same thing — one measures the £0 stages, one the whole repository's bill, and two
    buy nothing at all and say so. ``per_unit`` is the spend divided by the thing the stream
    delivers (a merged pull request), with ``per_unit_label`` naming the unit; it is ``None``
    when either side is unmeasured.
    """

    stream: str
    name: str
    lead_times: tuple[LeadTime, ...] = ()
    spend: Spend = field(default_factory=Spend)
    spend_label: str = ""
    per_unit: float | None = None
    per_unit_label: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)
    not_captured: tuple[NotCaptured, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "name": self.name,
            "lead_times": [lt.to_dict() for lt in self.lead_times],
            "spend": self.spend.to_dict(),
            "spend_label": self.spend_label,
            "per_unit": self.per_unit,
            "per_unit_label": self.per_unit_label,
            "counts": dict(self.counts),
            "not_captured": [nc.to_dict() for nc in self.not_captured],
        }


@dataclass(frozen=True)
class FlowReading:
    """Every stream's numbers for one repository, with the apparatus that produced them."""

    repo: str
    apparatus: str
    generated: str
    method: str
    streams: tuple[StreamFlow, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "apparatus": self.apparatus,
            "generated": self.generated,
            "method": self.method,
            "streams": [s.to_dict() for s in self.streams],
        }
