"""Response models for ``GET /flow`` — one value stream's lead time, spend and counts.

Nothing here is computed: every field is a :mod:`crb.core.flow` ``to_dict`` value re-typed so
the OpenAPI document is exact and a drift between the fold and the API is a diff. The optional
fields are optional *in the honest sense*: ``median_s``, ``usd`` and ``per_unit`` are ``None``
when the figure is unmeasured, and a client that renders ``None`` as ``0`` is wrong.

Navigation
----------
What it is:   The Pydantic shapes ``GET /flow`` answers with — ``FlowOut`` and the four nested
              models (lead time, spend, the figures nobody captured, one stream).
What it does: Re-types ``crb.core.flow``'s ``to_dict`` output field for field, so a reader of
              the OpenAPI document sees which figures can be ``null`` and why.
How:          Plain ``BaseModel`` subclasses with no arithmetic and no defaults that could
              turn an unmeasured figure into a zero.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/core/flow.py (the dataclasses these mirror), src/crb/server/flow.py
              (the gatherer whose reading is serialised here), src/crb/server/routes/flow.py
              (the only producer), ui/src/api/types.ts (the TypeScript twin),
              docs/API.md#flow-how-long-each-stream-takes-and-what-it-spent
Tested by:    tests/test_server_routes_flow.py
Touch when:   ``crb.core.flow`` gains a field — add it here in the same change, then
              ui/src/api/types.ts and docs/API.md; never to give a nullable figure a default.
"""

from __future__ import annotations

from pydantic import BaseModel


class LeadTimeOut(BaseModel):
    """One milestone pair's duration. ``median_s`` / ``min_s`` / ``max_s`` are ``null`` when
    ``n`` is 0 — unmeasured, not zero — and ``reason`` then says why. ``dropped`` counts pairs
    the fold refused (an unreadable stamp, or an end before its start)."""

    key: str
    label: str
    n: int
    median_s: float | None
    min_s: float | None
    max_s: float | None
    dropped: int
    reason: str


class SpendOut(BaseModel):
    """``usd`` sums only the rows whose cost is a measurement and is ``null`` when there are
    none; ``rows_unpriced`` is how many rows carried a cost the product cannot vouch for, so a
    reader knows the sum is a floor."""

    usd: float | None
    rows_priced: int
    rows_unpriced: int


class NotCapturedOut(BaseModel):
    """A figure the stream's definition of done asks for that nothing records, with why and
    the gap id that would close it."""

    figure: str
    why: str
    gap: str


class StreamFlowOut(BaseModel):
    """One value stream's own numbers."""

    stream: str
    name: str
    lead_times: list[LeadTimeOut]
    spend: SpendOut
    spend_label: str
    per_unit: float | None
    per_unit_label: str
    counts: dict[str, int]
    not_captured: list[NotCapturedOut]


class FlowOut(BaseModel):
    """Every stream's numbers for one repository, with the apparatus and the method that
    produced them (``method`` says it is a fold over stored records, not a live probe)."""

    repo: str
    apparatus: str
    generated: str
    method: str
    streams: list[StreamFlowOut]
