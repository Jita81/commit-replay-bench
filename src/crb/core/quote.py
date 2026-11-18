"""The mapping quote — what a first mapping of a repository would run, cost and take.

A first mapping is a sighted replay, one attempt per task (ladder ``["r1"]``). Before anything
is spent, the quote says, per (class x size) cell: how many tasks would run (capped at the
gold-clean tasks available, with the shortfall and what is left for a later reading), the
precision those tasks would buy (the Wilson 95% half-width at an assumed p of 0.5), and the
recorded product cost and builder time they would take, as a range drawn from recorded rows.

Honest by construction
----------------------
* The cost basis is one tier per cell, best first: this repository's rows in the cell, then
  every other repository's rows on this deployment (``[hypothesis]``: the cost is assumed to
  transfer), then the caller's declared band, then ``unknown``. An unknown cell is ``null``
  with a reason, never $0.
* A basis row is what a first mapping would write: a sighted replay attempt of the builder
  and model on rung ``r1`` and the ``S3`` brief (the commit's own tests; a row from before
  2.4, which carries no arm, at its own apparatus). Later rungs (only the tasks that failed
  ``r1``), other arms (bigger briefs) and context-set arms never enter a basis.
* A tier reads only the newest apparatus among its candidate rows (never pooled) and needs
  ``MIN_BASIS_ROWS`` rows with a known, metered cost; an unknown cost is never read as zero,
  and a row that metered nothing (no cost, no token: the provider refused the call, or the
  attempt ended before it) observed no cost and is left out.
* Every metered attempt that recorded a cost counts, whatever its outcome: money spent on an
  attempt later disqualified was still spent. This is also what keeps the quote blind to
  outcomes.
* The quote reads rows through :class:`CostRow` only — fifteen fields, none an outcome. The
  rung and the arm are read only to keep the rows above, never served. It is never evidence,
  routes nothing and feeds nothing.

Pure: stdlib and core only, no I/O, no clock.

Navigation
----------
What it is:   The core mapping quote — tasks, recorded cost, builder time and precision for a
              sighted single-rung replay of a repository, before any spend.
What it does: Caps each cell's tasks at the gold-clean tasks available (shortfall and
              ``left_after`` served), picks one cost basis per cell (repo cell, deployment cell
              ``[hypothesis]``, declared band, unknown), prices the sum of the attempts with a
              Student-t prediction interval, adds the priced cells into totals that name what
              they leave out, and serves the Wilson half-width at p = 0.5 as a projection.
How:          ``mapping_quote`` → ``_index`` (one pass: first-mapping rows of the builder and
              model, grouped by cell) → ``_cells`` (selection and ``class:*`` expansion) → per
              cell ``_basis`` (metered rows, newest apparatus, ``MIN_BASIS_ROWS``) →
              ``mean_estimate`` for the per-attempt basis and ``sum_range`` for the band, with
              ``_caution`` naming a thin or spreadless basis → ``MappingQuote.to_dict``
              (sorted, rounded to 6 places, no timestamp).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0058-mapping-quote.md
Works with:   src/crb/core/economics.py (``mean_estimate``, the per-attempt basis),
              src/crb/core/context_arm.py (``BASE_S3``, the arm a first mapping writes),
              src/crb/core/stats.py (``t_975`` and ``Z_95`` for the two intervals),
              src/crb/core/reading.py (``rule_looks`` for the default n; ``pool_seen``),
              src/crb/server/routes/quote.py (serves it as ``GET /quote/mapping``),
              src/crb/core/forecast.py (prices a mix from measured cells; this prices a first
              mapping, including cells never measured)
Tested by:    tests/test_quote.py, tests/test_server_routes_quote.py
Touch when:   never for a new repository; a basis tier, the range method, the precision
              projection or a fixed statement changes (with docs/adr/0058-mapping-quote.md and
              docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
Claims:       every figure is ``[hypothesis]`` until a mapping's spend is compared with its
              quote; recorded product cost, not a provider invoice.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from crb.core.context_arm import BASE_S3
from crb.core.economics import Estimate, mean_estimate
from crb.core.ledger import PROCESS_REPLAY, is_v2_apparatus
from crb.core.reading import rule_looks
from crb.core.routing import DEFAULT_POLICY
from crb.core.spec import SIZE_TIER_NAMES
from crb.core.stats import Z_95, mean, stddev, t_975

QUOTE_SCHEMA = "crb.quote.v1"
#: An interval needs two known rows (economics' own rule).
MIN_BASIS_ROWS = 2
#: Below this many basis rows a band's reason says the basis is thin.
THIN_BASIS_ROWS = 5

MODE_SIGHTED = "sighted"
LADDER = ("r1",)
#: The arm a first mapping's sighted replay writes: the commit's own tests in the brief.
MAPPING_ARM = BASE_S3

AVAILABILITY_MINED = "mined"
AVAILABILITY_PROFILE = "profile"
AVAILABILITY_NOTES = {
    AVAILABILITY_MINED: "gold-clean mined tasks in this repository's pool",
    AVAILABILITY_PROFILE: (
        "[upper bound] the change profile's commit counts: the repository is not mined yet, "
        "and mining keeps fewer"
    ),
}

TIER_REPO = "repo_cell"
TIER_DEPLOYMENT = "deployment_cell"
TIER_DECLARED = "declared"
TIER_UNKNOWN = "unknown"
TIER_TAGS = {
    TIER_REPO: "this repository's own recorded rows in the cell",
    TIER_DEPLOYMENT: (
        "[hypothesis] other repositories' rows in the cell on this deployment: assumes their "
        "cost and time per attempt transfer to this repository"
    ),
    TIER_DECLARED: "[declared] the caller's own band per attempt, echoed; not the server's",
    TIER_UNKNOWN: "",
}

METHOD_SUM = (
    "t prediction interval for the sum of A attempts: A*m +/- t975(k-1)*s*sqrt(A + A*A/k), "
    "low floored at 0"
)
METHOD_DECLARED = "declared band per attempt x attempts"
METHOD_NONE = "none"

REASON_NOTHING_RUNS = "no task to run: nothing runs, nothing is spent"
REASON_NO_SPREAD = (
    "the {k} basis rows are identical, so the band has no width: that is not certainty"
)
REASON_THIN = "a thin basis of {k} rows (under {thin}): the t factor widens the band"
REASON_DECLARED_NO_EXPECTED = "a declared band has no mid-point: the server has no data for one"
REASON_DECLARED_NO_TIME = "a declared band carries no time: the server has no data for one"

ESTIMATE_OF = (
    "recorded product cost: the product's price table applied to the tokens the builder "
    "metered. It is not a provider invoice."
)
CLAIM = (
    "[hypothesis] a projection from recorded rows, not a measurement. It routes nothing, "
    "licenses nothing and is never evidence for a cell."
)
TIME_BASIS = (
    "builder wall clock per attempt, summed as if run one after another. Grading, set-up, "
    "mining and queue time are not included."
)
SEEN_NOTE = (
    "every task a replay grades becomes seen: a reserved reading registered later refuses it "
    "(pool_seen, ADR-0026). [gap] tasks already replayed are not subtracted: available counts "
    "them, so tasks_to_run may include tasks already graded and left_after may overstate what "
    "is still unseen for a reading."
)
BASIS_ROWS = (
    "a basis row is a sighted replay attempt of this builder and model on rung r1 with the "
    "S3 brief (the commit's own tests), at the newest apparatus among the tier's rows, in this "
    "repository's checks arm and posture class; a row with no known cost, a negative cost, "
    "or that metered nothing (no cost and no token), is left out"
)
PRECISION_NOTE = (
    "wilson_half_width_p50 is the Wilson 95% half-width at an assumed p of 0.5 for the tasks "
    "that would run: a projection of precision, never a rate"
)
TOTALS_NOTE = (
    "each total adds only the cells it counts (unpriced and untimed name the rest); "
    "cost_usd_expected is null while any priced cell has no expected figure (no_expected "
    "names them); low and high add each cell's bounds, which is not a calibrated joint 95% "
    "interval; tasks run one after another"
)

#: The whole interface the quote may read from a row: no outcome. ``trial`` and
#: ``context_arm`` are read only to keep a first mapping's rows, never served.
COST_ROW_FIELDS = (
    "repo",
    "capability_class",
    "size",
    "builder",
    "model",
    "mode",
    "process_step",
    "trial",
    "context_arm",
    "apparatus_version",
    "cost_known",
    "cost_usd",
    "tokens_in",
    "tokens_out",
    "latency_s",
)


class CostRow(Protocol):
    """The ONLY fields the quote reads. ``GradeRow`` satisfies it as it stands."""

    @property
    def repo(self) -> str: ...
    @property
    def capability_class(self) -> str: ...
    @property
    def size(self) -> str: ...
    @property
    def builder(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def mode(self) -> str: ...
    @property
    def process_step(self) -> str: ...
    @property
    def trial(self) -> str: ...
    @property
    def context_arm(self) -> str: ...
    @property
    def apparatus_version(self) -> str: ...
    @property
    def cost_known(self) -> bool: ...
    @property
    def cost_usd(self) -> float: ...
    @property
    def tokens_in(self) -> int: ...
    @property
    def tokens_out(self) -> int: ...
    @property
    def latency_s(self) -> float: ...


CellKey = tuple[str, str]


def default_n() -> int:
    """The default tasks per cell: the first look of the default look rule."""
    return min(rule_looks(DEFAULT_POLICY.rule))


def half_width_at_half(n: int) -> float:
    """The Wilson 95% half-width at p = 0.5 over ``n`` tasks: ``z / (2 * sqrt(n + z*z))``.

    At ``n = 0`` it is 0.5, the house rule that an empty sample is [0, 1]."""
    return Z_95 / (2 * math.sqrt(max(n, 0) + Z_95 * Z_95))


@dataclass(frozen=True)
class SumRange:
    """The 95% prediction range for the sum of ``attempts`` new attempts."""

    low: float
    expected: float
    high: float
    k: int
    method: str


def sum_range(values: Sequence[float], attempts: int) -> SumRange:
    """The Student-t 95% prediction interval for the sum of ``attempts`` attempts drawn like
    the ``k`` recorded ``values``: the ``A*A/k`` term is the doubt about the mean, the ``A``
    term the spread between attempts. Refuses fewer than two values."""
    xs = sorted(float(v) for v in values)
    k = len(xs)
    if k < MIN_BASIS_ROWS:
        raise ValueError(f"a sum range needs at least {MIN_BASIS_ROWS} values, got {k}")
    a = max(int(attempts), 0)
    m = mean(xs)
    expected = a * m
    half = t_975(k - 1) * stddev(xs) * math.sqrt(a + a * a / k)
    return SumRange(max(0.0, expected - half), expected, expected + half, k, METHOD_SUM)


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def _version_key(v: str) -> tuple[tuple[int, ...], str]:
    """``"2.10"`` sorts after ``"2.9"``; non-numeric parts as 0, the text breaks ties."""
    parts: list[int] = []
    for part in v.split("."):
        digits = re.match(r"\d+", part)
        parts.append(int(digits.group(0)) if digits else 0)
    return tuple(parts), v


def _label(key: CellKey) -> str:
    cls, size = key
    return f"{cls}/{size}" if size else cls


def _size_index(size: str) -> int:
    if not size:
        return -1
    return SIZE_TIER_NAMES.index(size) if size in SIZE_TIER_NAMES else len(SIZE_TIER_NAMES)


def _cell_sort(key: CellKey) -> tuple[str, int, str]:
    return key[0], _size_index(key[1]), key[1]


@dataclass(frozen=True)
class Band:
    """One axis of a cell (or a total): ``low`` / ``expected`` / ``high`` or ``None``."""

    low: float | None
    expected: float | None
    high: float | None
    method: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "low": _r(self.low),
            "expected": _r(self.expected),
            "high": _r(self.high),
            "method": self.method,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Basis:
    tier: str
    n_rows: int
    n_time_rows: int
    n_repos: int
    apparatus_version: str | None
    cost_values: tuple[float, ...]
    time_values: tuple[float, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        priced_by_rows = self.tier in (TIER_REPO, TIER_DEPLOYMENT)
        cost = mean_estimate(list(self.cost_values), "cost") if priced_by_rows else None
        secs = mean_estimate(list(self.time_values), "latency") if priced_by_rows else None
        return {
            "tier": self.tier,
            "tag": TIER_TAGS[self.tier],
            "n_rows": self.n_rows,
            "n_time_rows": self.n_time_rows,
            "n_repos": self.n_repos,
            "apparatus_version": self.apparatus_version,
            "cost_per_attempt": _estimate(cost),
            "seconds_per_attempt": _estimate(secs),
            "reason": self.reason,
        }


def _estimate(e: Estimate | None) -> dict[str, Any] | None:
    return None if e is None else e.to_dict()


@dataclass(frozen=True)
class QuoteCell:
    key: CellKey
    requested: int
    available: int
    basis: Basis
    cost: Band
    minutes: Band

    @property
    def tasks_to_run(self) -> int:
        return min(self.requested, self.available)

    @property
    def priced(self) -> bool:
        return self.cost.low is not None

    def to_dict(self) -> dict[str, Any]:
        n = self.tasks_to_run
        return {
            "capability_class": self.key[0],
            "size": self.key[1],
            "label": _label(self.key),
            "requested": self.requested,
            "available": self.available,
            "tasks_to_run": n,
            "shortfall": self.requested - n,
            "left_after": self.available - n,
            "attempts": n * len(LADDER),
            "wilson_half_width_p50": _r(half_width_at_half(n)),
            "cost_usd": self.cost.to_dict(),
            "minutes": self.minutes.to_dict(),
            "basis": self.basis.to_dict(),
        }


@dataclass(frozen=True)
class MappingQuote:
    repo: str
    builder: str
    model: str
    n_default: int
    availability_source: str
    declared: tuple[float, float] | None
    cells: tuple[QuoteCell, ...]

    def totals(self) -> dict[str, Any]:
        priced = [c for c in self.cells if c.priced]
        no_expected = [c for c in priced if c.cost.expected is None]
        timed = [c for c in self.cells if c.minutes.low is not None]

        def add(cells: list[QuoteCell], pick: Any) -> float | None:
            return _r(sum(pick(c) for c in cells)) if cells else None

        return {
            "cells": len(self.cells),
            "cells_priced": len(priced),
            "cells_unknown": len(self.cells) - len(priced),
            "tasks_to_run": sum(c.tasks_to_run for c in self.cells),
            "tasks_priced": sum(c.tasks_to_run for c in priced),
            "cost_usd_low": add(priced, lambda c: c.cost.low),
            # over the same cells as low and high, or not at all: never an expected below low
            "cost_usd_expected": None if no_expected else add(priced, lambda c: c.cost.expected),
            "cost_usd_high": add(priced, lambda c: c.cost.high),
            "minutes_low": add(timed, lambda c: c.minutes.low),
            "minutes_expected": add(timed, lambda c: c.minutes.expected),
            "minutes_high": add(timed, lambda c: c.minutes.high),
            "unpriced": [_label(c.key) for c in self.cells if not c.priced],
            "no_expected": [_label(c.key) for c in no_expected],
            "untimed": [_label(c.key) for c in self.cells if c.minutes.low is None],
            "note": TOTALS_NOTE,
        }

    def to_dict(self) -> dict[str, Any]:
        first_look = default_n()
        return {
            "schema": QUOTE_SCHEMA,
            "repo": self.repo,
            "builder": self.builder,
            "model": self.model,
            "run": {
                "kind": PROCESS_REPLAY,
                "mode": MODE_SIGHTED,
                "ladder": list(LADDER),
                "attempts_per_task": len(LADDER),
                "look_rule": DEFAULT_POLICY.rule,
                "first_look": first_look,
            },
            "n_default": self.n_default,
            "availability_source": self.availability_source,
            "availability_note": AVAILABILITY_NOTES.get(self.availability_source, ""),
            "declared": (
                None
                if self.declared is None
                else {"low": _r(self.declared[0]), "high": _r(self.declared[1])}
            ),
            "estimate_of": ESTIMATE_OF,
            "claim": CLAIM,
            "time_basis": TIME_BASIS,
            "seen_note": SEEN_NOTE,
            "basis_rows": BASIS_ROWS,
            "precision_note": PRECISION_NOTE,
            "cells": [c.to_dict() for c in self.cells],
            "totals": self.totals(),
        }


def _first_mapping_row(r: CostRow, builder: str, model: str) -> bool:
    """A row a first mapping by ``builder:model`` would write: sighted replay, rung ``r1``,
    the ``S3`` brief (a row from before 2.4 carries no arm and is kept at its own apparatus).
    The rung and the arm are read here only, as a filter."""
    if not (
        r.builder == builder
        and r.model == model
        and r.mode == MODE_SIGHTED
        and r.process_step == PROCESS_REPLAY
        and r.trial in LADDER
    ):
        return False
    return r.context_arm == MAPPING_ARM or (
        not r.context_arm and not is_v2_apparatus(r.apparatus_version)
    )


def _index(rows: Iterable[CostRow], builder: str, model: str) -> dict[CellKey, list[CostRow]]:
    """The first-mapping rows of ``builder:model`` grouped by cell, in one pass."""
    out: dict[CellKey, list[CostRow]] = {}
    for r in rows:
        if _first_mapping_row(r, builder, model):
            out.setdefault((r.capability_class, r.size), []).append(r)
    return out


def _metered(r: CostRow) -> bool:
    """The row observed a cost: a known, finite, non-negative cost, and the builder metered
    something (a row with no cost and no token — a refused call, an attempt that ended before
    it — observed nothing). A negative cost is not a price and would invert the band."""
    if not (r.cost_known and math.isfinite(r.cost_usd) and r.cost_usd >= 0):
        return False
    return r.cost_usd > 0 or r.tokens_in > 0 or r.tokens_out > 0


def _newest(rows: list[CostRow]) -> tuple[str | None, list[CostRow]]:
    """The newest apparatus among ``rows`` and the rows at it — never pooled, never older."""
    if not rows:
        return None, []
    newest = max((r.apparatus_version for r in rows), key=_version_key)
    return newest, [r for r in rows if r.apparatus_version == newest]


@dataclass(frozen=True)
class _Tier:
    version: str | None
    costs: tuple[float, ...]
    times: tuple[float, ...]
    repos: int

    @property
    def qualifies(self) -> bool:
        return len(self.costs) >= MIN_BASIS_ROWS


def _tier(rows: list[CostRow]) -> _Tier:
    version, kept = _newest([r for r in rows if _metered(r)])
    costs = tuple(sorted(float(r.cost_usd) for r in kept))
    times = tuple(sorted(float(r.latency_s) for r in kept if r.latency_s > 0))
    repos = len({r.repo for r in kept})
    return _Tier(version, costs, times, repos)


def _basis(
    key: CellKey,
    *,
    builder: str,
    model: str,
    own: Mapping[CellKey, list[CostRow]],
    other: Mapping[CellKey, list[CostRow]],
    declared: tuple[float, float] | None,
) -> Basis:
    mine = _tier(own.get(key, []))
    if mine.qualifies:
        return Basis(
            TIER_REPO, len(mine.costs), len(mine.times), 1, mine.version, mine.costs, mine.times, ""
        )
    theirs = _tier(other.get(key, []))
    if theirs.qualifies:
        return Basis(
            TIER_DEPLOYMENT,
            len(theirs.costs),
            len(theirs.times),
            theirs.repos,
            theirs.version,
            theirs.costs,
            theirs.times,
            "",
        )
    tier = TIER_DECLARED if declared is not None else TIER_UNKNOWN
    reason = (
        f"too few first-rung sighted replay rows of {builder}:{model} in {_label(key)} with a "
        "known, metered cost "
        f"at the newest apparatus on this repository ({len(mine.costs)}, needs "
        f"{MIN_BASIS_ROWS}) or any other on this deployment ({len(theirs.costs)}, needs "
        f"{MIN_BASIS_ROWS})"
    )
    reason += (
        ": priced from the declared band" if declared is not None else ", and no declared figure"
    )
    return Basis(tier, 0, 0, 0, None, (), (), reason)


def _caution(values: Sequence[float]) -> str:
    """Why a row-priced band deserves less trust than its width says: no spread at all, or a
    thin basis. ``""`` otherwise."""
    k = len(values)
    if k and min(values) == max(values):
        return REASON_NO_SPREAD.format(k=k)
    if k < THIN_BASIS_ROWS:
        return REASON_THIN.format(k=k, thin=THIN_BASIS_ROWS)
    return ""


def _bands(basis: Basis, attempts: int, declared: tuple[float, float] | None) -> tuple[Band, Band]:
    if attempts == 0:
        zero = Band(0.0, 0.0, 0.0, METHOD_NONE, REASON_NOTHING_RUNS)
        return zero, zero
    if basis.tier in (TIER_REPO, TIER_DEPLOYMENT):
        c = sum_range(basis.cost_values, attempts)
        cost = Band(c.low, c.expected, c.high, c.method, _caution(basis.cost_values))
        if len(basis.time_values) >= MIN_BASIS_ROWS:
            t = sum_range(basis.time_values, attempts)
            minutes = Band(
                t.low / 60, t.expected / 60, t.high / 60, t.method, _caution(basis.time_values)
            )
        else:
            minutes = Band(
                None,
                None,
                None,
                METHOD_NONE,
                f"too few rows with a builder time in this basis ({len(basis.time_values)}, "
                f"needs {MIN_BASIS_ROWS}); time never falls through to another tier",
            )
        return cost, minutes
    if basis.tier == TIER_DECLARED and declared is not None:
        low, high = declared
        cost = Band(
            attempts * low, None, attempts * high, METHOD_DECLARED, REASON_DECLARED_NO_EXPECTED
        )
        return cost, Band(None, None, None, METHOD_NONE, REASON_DECLARED_NO_TIME)
    unknown = Band(None, None, None, METHOD_NONE, basis.reason)
    return unknown, unknown


def _cells(
    available: Mapping[CellKey, int], selection: Mapping[CellKey, int] | None, n_default: int
) -> dict[CellKey, int]:
    """The cells to quote and the tasks requested in each. No selection: every cell with a
    task, at ``n_default``. ``(class, "")`` in a selection expands to each available size of
    the class (or stays as itself, with nothing available); an explicit size wins."""
    if selection is None:
        return {k: n_default for k, v in available.items() if v > 0}
    out: dict[CellKey, int] = {}
    for (cls, size), n in selection.items():
        if size:
            continue
        sizes = [k for k, v in available.items() if k[0] == cls and v > 0]
        for k in sizes or [(cls, "")]:
            out[k] = n
    for (cls, size), n in selection.items():
        if size:
            out[(cls, size)] = n
    return out


def mapping_quote(
    *,
    repo: str,
    builder: str,
    model: str,
    available: Mapping[CellKey, int],
    availability_source: str,
    own_rows: Iterable[CostRow],
    other_rows: Iterable[CostRow],
    n_default: int,
    selection: Mapping[CellKey, int] | None,
    declared: tuple[float, float] | None,
) -> MappingQuote:
    """The quote for a sighted single-rung replay of ``repo`` by ``builder:model``."""
    own = _index(own_rows, builder, model)
    other = _index(other_rows, builder, model)
    requested = _cells(available, selection, n_default)
    cells: list[QuoteCell] = []
    for key in sorted(requested, key=_cell_sort):
        avail = max(int(available.get(key, 0)), 0)
        n = max(int(requested[key]), 0)
        basis = _basis(key, builder=builder, model=model, own=own, other=other, declared=declared)
        cost, minutes = _bands(basis, min(n, avail) * len(LADDER), declared)
        cells.append(QuoteCell(key, n, avail, basis, cost, minutes))
    return MappingQuote(
        repo=repo,
        builder=builder,
        model=model,
        n_default=n_default,
        availability_source=availability_source,
        declared=declared,
        cells=tuple(cells),
    )


__all__ = [
    "AVAILABILITY_MINED",
    "AVAILABILITY_PROFILE",
    "BASIS_ROWS",
    "COST_ROW_FIELDS",
    "MAPPING_ARM",
    "MIN_BASIS_ROWS",
    "QUOTE_SCHEMA",
    "TIER_DECLARED",
    "TIER_DEPLOYMENT",
    "TIER_REPO",
    "TIER_UNKNOWN",
    "CostRow",
    "MappingQuote",
    "QuoteCell",
    "SumRange",
    "default_n",
    "half_width_at_half",
    "mapping_quote",
    "sum_range",
]
