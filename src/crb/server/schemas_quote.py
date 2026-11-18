"""Response models for ``GET /quote/mapping`` — the mapping quote.

Nothing here is computed: every field is :meth:`crb.core.quote.MappingQuote.to_dict` re-typed
so the OpenAPI document is honest and a drift between core and API is a diff — except
``model_priced`` and its reason, which the route fills from the price table. A figure the
server has no basis for is ``null``, never ``0``.

Navigation
----------
What it is:   The response models for ``GET /quote/mapping`` — the run, the cells with their
              basis and bands, and the totals of a first mapping's quote.
What it does: Re-types the core quote's ``to_dict`` (``QuoteCellOut``, ``QuoteBasisOut``,
              ``QuoteRangeOut``, ``QuoteTotalsOut``) into ``MappingQuoteOut``; the basis's
              per-attempt figures reuse ``EstimateOut``.
How:          Pydantic models; no arithmetic. A separate file keeps src/crb/server/schemas.py
              out of this change.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0058-mapping-quote.md
Works with:   src/crb/server/routes/quote.py (the only producer), src/crb/core/quote.py (the
              ``to_dict`` these mirror), src/crb/server/schemas_capability.py
              (``EstimateOut``), docs/API.md#capability-routing-forecast-sign-off (the row)
Tested by:    tests/test_server_routes_quote.py
Touch when:   never for a new repository; whenever the core quote's ``to_dict`` gains a field
              — add it here in the same change, then docs/API.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from crb.server.schemas_capability import EstimateOut


class QuoteRunOut(BaseModel):
    """What the quote prices: a sighted replay, one attempt per task, under the look rule."""

    kind: str
    mode: str
    ladder: list[str]
    attempts_per_task: int
    look_rule: str
    first_look: int


class QuoteDeclaredOut(BaseModel):
    """The caller's own band per attempt, echoed (USD)."""

    low: float
    high: float


class QuoteRangeOut(BaseModel):
    """One axis of a cell: ``null`` where the server has no basis, never ``0``."""

    low: float | None
    expected: float | None
    high: float | None
    method: str
    reason: str


class QuoteBasisOut(BaseModel):
    """The one tier a cell is priced from (``repo_cell``, ``deployment_cell``, ``declared``,
    ``unknown``) and what it counted."""

    tier: str
    tag: str
    n_rows: int
    n_time_rows: int
    n_repos: int
    apparatus_version: str | None
    cost_per_attempt: EstimateOut | None
    seconds_per_attempt: EstimateOut | None
    reason: str


class QuoteCellOut(BaseModel):
    """One (class x size) cell of the quote."""

    capability_class: str
    size: str
    label: str
    requested: int
    available: int
    tasks_to_run: int
    shortfall: int
    left_after: int
    attempts: int
    wilson_half_width_p50: float
    cost_usd: QuoteRangeOut
    minutes: QuoteRangeOut
    basis: QuoteBasisOut


class QuoteTotalsOut(BaseModel):
    """The cells added up; each total names the cells it leaves out."""

    cells: int
    cells_priced: int
    cells_unknown: int
    tasks_to_run: int
    tasks_priced: int
    cost_usd_low: float | None
    cost_usd_expected: float | None
    cost_usd_high: float | None
    minutes_low: float | None
    minutes_expected: float | None
    minutes_high: float | None
    unpriced: list[str]
    no_expected: list[str]
    untimed: list[str]
    note: str


class MappingQuoteOut(BaseModel):
    """``GET /quote/mapping``: a read-only projection, never evidence (ADR-0058)."""

    schema_: str = Field(alias="schema")
    repo: str
    builder: str
    model: str
    run: QuoteRunOut
    n_default: int
    availability_source: str
    availability_note: str
    declared: QuoteDeclaredOut | None
    estimate_of: str
    claim: str
    time_basis: str
    seen_note: str
    basis_rows: str
    precision_note: str
    cells: list[QuoteCellOut]
    totals: QuoteTotalsOut
    model_priced: bool | None
    model_priced_reason: str

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


__all__ = [
    "MappingQuoteOut",
    "QuoteBasisOut",
    "QuoteCellOut",
    "QuoteDeclaredOut",
    "QuoteRangeOut",
    "QuoteRunOut",
    "QuoteTotalsOut",
]
