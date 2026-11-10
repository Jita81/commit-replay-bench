"""Budget enforcement, cost metering and escalation-ladder helpers.

* :class:`Pricing` / :func:`load_pricing` — a small, configurable price table
  (USD per million tokens). Unknown models meter tokens but report
  ``cost_known=False`` with a warning rather than inventing a number: a ledger
  row that says ``$0.00`` for an unpriced model is a lie, so it is flagged.
* :class:`CostMeter` — accumulates tokens and cost; prefers a provider-reported
  cost when one exists.
* :func:`table_cost` — the product's own price of a build's tokens, with the
  provider's figure only as the fallback for an unpriced model, and which of the
  two it used (``cost_source``). Claude Code prices from it: the CLI's
  ``total_cost_usd`` uses the CLI's price list, not ours.
* :class:`BudgetTracker` — the one place the loop asks "may I continue?". It
  returns the *reason* it may not (:data:`crb.builders.base.STOP_REASONS`) so
  the outcome records which cap fired.
* :func:`parse_ladder` / :func:`default_ladder` / :func:`budget_for_rung` — the
  escalation ladder as data (``builder:model@provider,…``).

Navigation
----------
What it is:   The spend instruments every adapter shares — the price table, the ``CostMeter``,
              the ``BudgetTracker`` — and the ladder-as-data helpers.
What it does: Meters tokens and USD per build (a provider-reported cost wins; an unpriced
              model is ``cost_known=False`` with a warning, never a silent ``$0.00``), and
              answers "may the loop continue?" with the cap that fired, in the order wall
              clock → cost → tokens → turns → tool calls.
How:          ``price_for``: exact id → longest known prefix → provider placeholder →
              unknown. ``BudgetTracker.exceeded`` reads the meter and its own counters
              against the frozen ``Budget``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/base.py (``Budget``, ``Rung``, the stop reasons),
              src/crb/builders/openai_agent.py and src/crb/builders/claude_code.py (the loops
              that ask the tracker), src/crb/builders/adapter.py (``budget_for_rung`` per
              attempt), src/crb/server/worker.py (object rungs with a ``budget`` override)
Tested by:    tests/test_builders_base.py, tests/test_worker_budget_ladder.py
Touch when:   a model is added or re-priced — prefer ``CRB_PRICING_JSON`` (docs/OPERATOR.md)
              over editing ``DEFAULT_PRICING``; a new cap needs a stop reason in
              src/crb/builders/base.py and a place in ``exceeded``'s order.
Claims:       ``cost_usd`` with ``cost_known=False`` is metered tokens at price zero — it
              must never be summed as spend (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import json
import os
import time
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.builders.base import (
    STOP_MAX_COST,
    STOP_MAX_TOKENS,
    STOP_MAX_TOOL_CALLS,
    STOP_MAX_TURNS,
    STOP_WALL_CLOCK,
    Budget,
    EscalationLadder,
    Rung,
)

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens. ``known=False`` marks a placeholder (cost unknown)."""

    input_per_m: float
    output_per_m: float
    known: bool = True
    cached_input_per_m: float | None = None
    #: cache WRITES (Anthropic: 1.25x input at the default 5-minute TTL); ``None`` bills
    #: them at the input rate
    cache_write_per_m: float | None = None

    def cost(
        self, tokens_in: int, tokens_out: int, *, cached_in: int = 0, cache_write_in: int = 0
    ) -> float:
        """USD for one call; cached input (cache reads, a subset of ``tokens_in``) is
        billed at its own rate when the table has one, else at the input rate; cache writes
        (``cache_write_in``, a subset of the uncached input) likewise at
        ``cache_write_per_m``; an unknown price is always ``0.0``."""
        if not self.known:
            return 0.0
        uncached = max(0, tokens_in - cached_in)
        written = min(max(0, cache_write_in), uncached) if self.cache_write_per_m is not None else 0
        c = (uncached - written) * self.input_per_m / 1e6 + tokens_out * self.output_per_m / 1e6
        if written and self.cache_write_per_m is not None:
            c += written * self.cache_write_per_m / 1e6
        if cached_in and self.cached_input_per_m is not None:
            c += cached_in * self.cached_input_per_m / 1e6
        elif cached_in:
            c += cached_in * self.input_per_m / 1e6
        return c

    def to_dict(self) -> dict[str, Any]:
        """The shape ``CRB_PRICING_JSON`` uses per model (``cache_write_per_m`` only when
        set, so an entry without one keeps the shape it always had)."""
        d: dict[str, Any] = {
            "input_per_m": self.input_per_m,
            "output_per_m": self.output_per_m,
            "known": self.known,
            "cached_input_per_m": self.cached_input_per_m,
        }
        if self.cache_write_per_m is not None:
            d["cache_write_per_m"] = self.cache_write_per_m
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Pricing:
        """Inverse of :meth:`to_dict` (missing rates read as 0.0 — pair with ``known``)."""
        return cls(
            input_per_m=float(d.get("input_per_m", 0.0)),
            output_per_m=float(d.get("output_per_m", 0.0)),
            known=bool(d.get("known", True)),
            cached_input_per_m=(
                None if d.get("cached_input_per_m") is None else float(d["cached_input_per_m"])
            ),
            cache_write_per_m=(
                None if d.get("cache_write_per_m") is None else float(d["cache_write_per_m"])
            ),
        )


#: Default entries. Cerebras rates from the upstream ``model_pricing.py`` (verified
#: 2026-06-05 against published per-token rates); Anthropic rates from the
#: ``claude-api`` skill's model table (cached 2026-06-24); Anthropic cache writes at
#: 1.25x input (the 5-minute TTL — a 1-hour write is 2x, so one is still undercounted).
#: ``azure`` is a placeholder: Azure OpenAI pricing depends on the deployment — configure
#: it, or cost is unknown.
DEFAULT_PRICING: dict[str, Pricing] = {
    "gpt-oss-120b": Pricing(0.25, 0.69),
    "zai-glm-4.7": Pricing(2.25, 2.75),
    "claude-opus-5": Pricing(5.0, 25.0, cached_input_per_m=0.5, cache_write_per_m=6.25),
    "claude-opus-4-8": Pricing(5.0, 25.0, cached_input_per_m=0.5, cache_write_per_m=6.25),
    "claude-sonnet-5": Pricing(2.0, 10.0, cached_input_per_m=0.2, cache_write_per_m=2.5),
    "claude-haiku-4-5": Pricing(1.0, 5.0, cached_input_per_m=0.1, cache_write_per_m=1.25),
    "azure": Pricing(0.0, 0.0, known=False),
}

PRICING_ENV = "CRB_PRICING_JSON"


def load_pricing(path: str | Path | None = None) -> dict[str, Pricing]:
    """Defaults, overlaid with a JSON file ``{model: {input_per_m, output_per_m, …}}``
    from ``path`` or ``$CRB_PRICING_JSON``. A malformed file is an error, not a silent
    fallback — mispriced evidence is worse than no evidence."""
    table = dict(DEFAULT_PRICING)
    src = path or os.environ.get(PRICING_ENV, "")
    if not src:
        return table
    p = Path(src)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"pricing file {p} must be a JSON object keyed by model id")
    for model, entry in data.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"pricing entry for {model!r} must be an object")
        table[str(model)] = Pricing.from_dict(entry)
    return table


def price_for(model: str, table: Mapping[str, Pricing] | None = None) -> Pricing:
    """Exact match, then the longest key that prefixes the model id, then the
    provider placeholder (``azure:…``), then an unknown-price placeholder + warning."""
    t = table if table is not None else DEFAULT_PRICING
    if model in t:
        return t[model]
    prefixed = [k for k in t if model.startswith(k) and t[k].known]
    if prefixed:
        return t[max(prefixed, key=len)]
    provider = model.split(":", 1)[0] if ":" in model else ""
    if provider and provider in t:
        pr = t[provider]
        if not pr.known:
            warnings.warn(
                f"no pricing for {model!r}: cost will be reported as UNKNOWN (0.0); "
                f"configure {PRICING_ENV}",
                stacklevel=2,
            )
        return pr
    warnings.warn(
        f"no pricing for {model!r}: cost will be reported as UNKNOWN (0.0); configure {PRICING_ENV}",
        stacklevel=2,
    )
    return Pricing(0.0, 0.0, known=False)


#: ``cost_source`` values: which figure a build's ``cost_usd`` is.
COST_SOURCE_TABLE = "price_table"  # the product's own table priced the tokens
COST_SOURCE_CLI = "cli_reported"  # unpriced model: the CLI's own figure
COST_SOURCE_UNKNOWN = "unknown"  # neither: ``cost_known=False``
COST_SOURCE_MIXED = "mixed"  # a merged attempt whose calls were priced differently
#: ``BuildOutcome.extra`` (and pack ``notes``) keys for a build's cost provenance.
EXTRA_COST_SOURCE = "cost_source"
EXTRA_CLI_COST = "cli_cost_usd"


def table_cost(
    pricing: Pricing,
    tokens_in: int,
    tokens_out: int,
    *,
    cached_in: int = 0,
    cache_write_in: int = 0,
    reported_cost: float | None = None,
) -> tuple[float, bool, str]:
    """``(cost_usd, cost_known, cost_source)`` for one build: the table price of its tokens
    when the model is priced (whatever the CLI reported — its figure is its own price
    list, not ours), else the CLI's figure, else ``0.0`` and unknown."""
    if pricing.known:
        cost = pricing.cost(
            tokens_in, tokens_out, cached_in=cached_in, cache_write_in=cache_write_in
        )
        return cost, True, COST_SOURCE_TABLE
    if reported_cost is not None:
        return float(reported_cost), True, COST_SOURCE_CLI
    return 0.0, False, COST_SOURCE_UNKNOWN


def cost_provenance(source: str, reported_cost: float | None) -> dict[str, Any]:
    """The ``extra`` / pack-notes entry recording where ``cost_usd`` came from, with the
    CLI's own figure beside it (``cli_cost_usd``) when it gave one."""
    out: dict[str, Any] = {EXTRA_COST_SOURCE: source}
    if reported_cost is not None:
        out[EXTRA_CLI_COST] = round(float(reported_cost), 6)
    return out


def merge_cost_provenance(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """Two calls' provenance as one attempt's: the CLI figures summed (only when both
    calls have one, else a partial sum would pass for the whole), the source kept when the
    calls agree, else ``mixed``. Empty when neither call recorded any."""
    sa, sb = a.get(EXTRA_COST_SOURCE), b.get(EXTRA_COST_SOURCE)
    if sa is None and sb is None:
        return {}
    if sa is None or sb is None:
        return cost_provenance(str(sa or sb), (a if sa else b).get(EXTRA_CLI_COST))
    pa, pb = a.get(EXTRA_CLI_COST), b.get(EXTRA_CLI_COST)
    cli = float(pa) + float(pb) if pa is not None and pb is not None else None
    return cost_provenance(str(sa) if sa == sb else COST_SOURCE_MIXED, cli)


# ---------------------------------------------------------------------------
# Meter + tracker
# ---------------------------------------------------------------------------


class CostMeter:
    """Accumulate tokens and USD across the calls of one build."""

    def __init__(self, pricing: Pricing | None = None, *, model: str = "") -> None:
        self.pricing = pricing if pricing is not None else price_for(model)
        self.model = model
        self.tokens_in = 0
        self.tokens_out = 0
        self.cached_in = 0
        self.calls = 0
        self._reported_cost = 0.0
        self._any_reported = False

    def add(
        self,
        tokens_in: int,
        tokens_out: int,
        *,
        cached_in: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        """Record one model call. A provider-reported ``cost_usd`` switches the meter to
        reported mode for the whole build (the table is then only a fallback)."""
        self.tokens_in += max(0, int(tokens_in or 0))
        self.tokens_out += max(0, int(tokens_out or 0))
        self.cached_in += max(0, int(cached_in or 0))
        self.calls += 1
        if cost_usd is not None:
            self._reported_cost += float(cost_usd)
            self._any_reported = True

    @property
    def cost_known(self) -> bool:
        """``True`` when a provider reported cost or the model is in the price table."""
        return self._any_reported or self.pricing.known

    @property
    def cost_usd(self) -> float:
        """Reported cost when any call reported one, else the table price of the tokens."""
        if self._any_reported:
            return self._reported_cost
        return self.pricing.cost(self.tokens_in, self.tokens_out, cached_in=self.cached_in)

    @property
    def total_tokens(self) -> int:
        """Input + output (what ``Budget.max_tokens`` caps)."""
        return self.tokens_in + self.tokens_out

    def to_dict(self) -> dict[str, Any]:
        """The meter's totals as an outcome / event carries them."""
        return {
            "model": self.model,
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cached_in": self.cached_in,
            "cost_usd": round(self.cost_usd, 6),
            "cost_known": self.cost_known,
        }


class BudgetTracker:
    """Counts turns / tool calls / spend / wall clock against a :class:`Budget`.

    ``exceeded()`` returns the first cap that is hit (a stop reason) or ``""``.
    Checked in the order wall clock → cost → tokens → turns → tool calls, so the
    reason recorded is the most external one.
    """

    def __init__(
        self,
        budget: Budget,
        meter: CostMeter,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.budget = budget
        self.meter = meter
        self._clock = clock or time.monotonic  # resolved here so tests can patch time
        self._started = self._clock()
        self.turns = 0
        self.tool_calls = 0

    @property
    def elapsed_s(self) -> float:
        """Seconds since the tracker was created (the build's start)."""
        return self._clock() - self._started

    @property
    def remaining_s(self) -> float:
        """Wall clock left, floored at 0 — what a subprocess adapter passes as its timeout."""
        return max(0.0, self.budget.wall_clock_s - self.elapsed_s)

    def note_turn(self) -> None:
        """One model round-trip happened."""
        self.turns += 1

    def note_tool_call(self) -> None:
        """One tool call happened (refused calls count too — they cost a turn of attention)."""
        self.tool_calls += 1

    def exceeded(self) -> str:
        """The first cap hit, as a stop reason, or ``""`` (the class docstring has the order)."""
        b = self.budget
        if self.elapsed_s >= b.wall_clock_s:
            return STOP_WALL_CLOCK
        if b.max_cost_usd and self.meter.cost_usd >= b.max_cost_usd:
            return STOP_MAX_COST
        if b.max_tokens and self.meter.total_tokens >= b.max_tokens:
            return STOP_MAX_TOKENS
        if self.turns >= b.max_turns:
            return STOP_MAX_TURNS
        if self.tool_calls >= b.max_tool_calls:
            return STOP_MAX_TOOL_CALLS
        return ""

    def can_call_tool(self) -> str:
        """Reason a further tool call is refused, or ``""``."""
        if self.tool_calls >= self.budget.max_tool_calls:
            return STOP_MAX_TOOL_CALLS
        return self.exceeded()

    def to_dict(self) -> dict[str, Any]:
        """Counters + meter + the budget they were checked against."""
        return {
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "elapsed_s": round(self.elapsed_s, 3),
            **self.meter.to_dict(),
            "budget": self.budget.to_dict(),
        }


# ---------------------------------------------------------------------------
# Ladder helpers
# ---------------------------------------------------------------------------


def parse_rung(spec: str) -> Rung:
    """``builder:model[@provider]`` → :class:`Rung`."""
    s = spec.strip()
    if ":" not in s:
        raise ValueError(f"rung {spec!r} must look like builder:model[@provider]")
    builder, rest = s.split(":", 1)
    model, _, provider = rest.partition("@")
    return Rung(builder=builder.strip(), model=model.strip(), provider=provider.strip())


def parse_ladder(spec: str) -> EscalationLadder:
    """``"editblock:gpt-oss-120b@cerebras,claude_code:claude-sonnet-5@anthropic"``."""
    rungs = tuple(parse_rung(part) for part in spec.split(",") if part.strip())
    return EscalationLadder(rungs)


def default_ladder() -> EscalationLadder:
    """Cheap one-shot → cheap agentic → agentic Claude Code (the census's measured path)."""
    return EscalationLadder(
        (
            Rung("editblock", "gpt-oss-120b", "cerebras"),
            Rung("openai_agent", "gpt-oss-120b", "cerebras"),
            Rung("claude_code", "claude-sonnet-5", "anthropic"),
            Rung("claude_code", "claude-opus-5", "anthropic"),
        )
    )


def budget_for_rung(rung: Rung, base: Budget) -> Budget:
    """A rung may override budget fields via its ``config`` (e.g. a bigger wall clock
    for an agentic rung). Unknown keys are ignored; the result is validated."""
    d = base.to_dict()
    for k in d:
        if k in rung.config:
            d[k] = rung.config[k]
    return Budget.from_dict(d)


__all__ = [
    "COST_SOURCE_CLI",
    "COST_SOURCE_MIXED",
    "COST_SOURCE_TABLE",
    "COST_SOURCE_UNKNOWN",
    "DEFAULT_PRICING",
    "EXTRA_CLI_COST",
    "EXTRA_COST_SOURCE",
    "PRICING_ENV",
    "BudgetTracker",
    "CostMeter",
    "Pricing",
    "budget_for_rung",
    "cost_provenance",
    "default_ladder",
    "load_pricing",
    "merge_cost_provenance",
    "parse_ladder",
    "parse_rung",
    "price_for",
    "table_cost",
]
