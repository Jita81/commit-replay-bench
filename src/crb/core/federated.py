"""Federated abstract learning — the export boundary between one organisation and all.

A self-hosting organisation must (1) keep its code, commits, task ids and
timing entirely inside its own boundary and (2) still benefit from what every
other organisation has measured. The reconciliation is the CELL: an
:class:`AbstractCell` is the coordinate ``(process_step, capability_class,
size, language, builder, model, provider)`` plus aggregate statistics, and
NOTHING else. It carries no repo, no task id, no timestamp, no free text.

Three protections, in order:

* **ALLOWLIST** — :data:`ABSTRACT_ALLOWLIST` is the complete list of fields
  that may cross the boundary. :class:`AbstractCell` has exactly those fields
  (asserted at import, and by the ratchet test), so a new identifying field
  cannot leak by a forgotten redaction — it has to be added here, on purpose.
* **k-ANONYMITY** — :func:`aggregate_abstract_cells` releases a cell only when
  at least ``min_cohort_k`` DISTINCT organisations contributed to it; below
  that the cell is suppressed entirely. Organisations are identified only by an
  opaque hash that is counted and then dropped, never emitted.
* **DIFFERENTIAL PRIVACY (optional)** — with ``dp_epsilon`` set, calibrated
  Laplace noise is added to the released *means* (point, cost, latency), the
  released ``clean`` count is derived from the noised point so the exact count
  cannot be read back, and the interval is recomputed from the released
  counts. The noise is drawn from a caller-seeded RNG so every release is
  reproducible. Cohort size, ``n`` and ``false_q1`` are never noised — they gate
  trust and cohort and must stay exact. The sensitivity is a nominal module
  constant, not a calibrated privacy accounting; treat DP here as a designed
  boundary, not a proof.

The cardinal invariant crosses the boundary intact: a released
:class:`SharedCell` that aggregates ANY contributor with ``false_q1 > 0`` is
``trusted=False`` and its ``false_q1`` is the sum, so the signal cannot be
laundered away by averaging.

NOT IMPLEMENTED — by design, not by omission: **consumption** of shared cells
(cold-start priors for a new organisation's router, cross-org self-improvement).
This module only builds the boundary and the aggregator; nothing in ``crb``
reads a shared cell back into a routing decision. That is the "designed
boundary, not demonstrated" line from the essay, and it stays that way until a
consumption path has its own evidence.

Navigation
----------
What it is:   The federated export boundary — ``AbstractCell`` (exactly the allowlisted
              fields of one cell), ``export_abstract`` (what leaves an organisation) and
              ``aggregate_abstract_cells`` (the k-anonymous, optionally noised merge across
              organisations).
What it does: Projects ``CellStats`` onto the allowlist and nothing else; refuses at import
              time to let the dataclass and the allowlist drift; releases a cross-org cell
              only when ``min_cohort_k`` distinct organisations contributed; keeps a
              contributor's false-Q1 visible in the sum so averaging cannot hide it; adds
              seeded Laplace noise to released means when asked. Consumes nothing back
              into routing — by design.
How:          ``all_cell_stats`` → ``to_abstract_cell`` (redacted key strings, ``None`` for
              an unmeasured axis) → sorted dicts; aggregation groups contributions by
              key → cohort check → pooled counts, n-weighted means, Wilson interval
              recomputed → optional DP → ``SharedCell``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0007-abstract-cell-export-only.md
Works with:   src/crb/core/ledger.py (CellStats and the cell key — the abstraction
              boundary), src/crb/core/redact.py (defence in depth on key strings),
              src/crb/core/stats.py (the recomputed interval),
              src/crb/cli/commands/ledger.py (``crb ledger export --abstract``),
              src/crb/server/routes/ledger.py (``GET /ledger/export/abstract``)
Tested by:    tests/test_federated.py, tests/test_server_routes_ledger.py
Touch when:   never for a new repository; adding a field to the export is a privacy decision
              — it must be added to ``ABSTRACT_ALLOWLIST`` on purpose (the import-time
              assertion and tests/test_federated.py refuse a drift), justified in
              docs/adr/0007-abstract-cell-export-only.md and
              docs/DATA-RETENTION.md#5-cross-organisation-sharing.
Claims:       DP here is a designed boundary with a nominal sensitivity, not a calibrated
              privacy proof; no consumption path exists yet
              (docs/EVIDENCE-AND-CLAIMS.md#1-claim-tags — ``[aspiration]``).
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from crb.core.ledger import CellKey, CellStats, GradeRow, all_cell_stats
from crb.core.redact import redact
from crb.core.stats import wilson_interval

#: The ONLY fields that may leave an organisation's boundary. Cell key fields plus
#: aggregate counts and means. NO repo, NO task ids, NO timestamps, NO free text.
ABSTRACT_ALLOWLIST: tuple[str, ...] = (
    "process_step",
    "capability_class",
    "size",
    "language",
    "builder",
    "model",
    "provider",
    "n",
    "clean",
    "false_q1",
    "point",
    "ci_low",
    "ci_high",
    "cost_usd_mean",
    "latency_s_mean",
)

#: Nominal Laplace sensitivity of each released mean (scale = sensitivity / ε).
DP_SENSITIVITY: float = 1.0

#: Default minimum number of DISTINCT organisations before a cell is released.
DEFAULT_MIN_COHORT_K = 3

AbstractKey = tuple[str, str, str, str, str, str, str]


@dataclass(frozen=True)
class AbstractCell:
    """One organisation's non-identifying view of one cell. Fields == the allowlist."""

    process_step: str
    capability_class: str
    size: str
    language: str
    builder: str
    model: str
    provider: str
    n: int
    clean: int
    false_q1: int
    point: float
    ci_low: float
    ci_high: float
    cost_usd_mean: float | None
    latency_s_mean: float | None

    def __post_init__(self) -> None:
        if self.n < 0 or self.clean < 0 or self.false_q1 < 0:
            raise ValueError("counts cannot be negative")
        if self.clean > self.n:
            raise ValueError("clean cannot exceed n")

    @property
    def key(self) -> AbstractKey:
        """The seven key fields as a tuple — what contributions are grouped on."""
        return (
            self.process_step,
            self.capability_class,
            self.size,
            self.language,
            self.builder,
            self.model,
            self.provider,
        )

    @property
    def cell(self) -> CellKey:
        """The same key as the ledger's ``CellKey``."""
        return CellKey(*self.key)

    def to_dict(self) -> dict[str, Any]:
        """The allowlisted fields, in allowlist order — the bytes that leave."""
        return {f: getattr(self, f) for f in ABSTRACT_ALLOWLIST}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AbstractCell:
        """Rebuild an imported cell; an extra field is refused, never dropped silently
        (a foreign bundle carrying an identifier must fail loudly)."""
        extra = set(d) - set(ABSTRACT_ALLOWLIST)
        if extra:
            raise ValueError(f"abstract cell carries non-allowlisted field(s): {sorted(extra)}")
        return cls(**{f: d[f] for f in ABSTRACT_ALLOWLIST})


# Fail at import if the dataclass and the allowlist ever drift — the boundary's
# guarantee is that an AbstractCell carries EXACTLY the allowlisted fields.
_ABSTRACT_FIELDS: frozenset[str] = frozenset(AbstractCell.__dataclass_fields__)
assert frozenset(ABSTRACT_ALLOWLIST) == _ABSTRACT_FIELDS, (
    "AbstractCell fields drifted from ABSTRACT_ALLOWLIST: "
    f"cell-only={sorted(_ABSTRACT_FIELDS - set(ABSTRACT_ALLOWLIST))}, "
    f"allowlist-only={sorted(set(ABSTRACT_ALLOWLIST) - _ABSTRACT_FIELDS)}"
)


def to_abstract_cell(stats: CellStats) -> AbstractCell:
    """Project :class:`CellStats` onto the allowlist. Key strings are redacted as
    defence in depth; an unmeasured axis (``0.0`` in CellStats) becomes ``None``."""
    k = stats.cell
    return AbstractCell(
        process_step=redact(k.process_step),
        capability_class=redact(k.capability_class),
        size=redact(k.size),
        language=redact(k.language),
        builder=redact(k.builder),
        model=redact(k.model),
        provider=redact(k.provider),
        n=stats.n,
        clean=stats.clean,
        false_q1=stats.false_q1,
        point=stats.point,
        ci_low=stats.ci.low,
        ci_high=stats.ci.high,
        cost_usd_mean=stats.cost_usd_mean if stats.cost_usd_mean > 0 else None,
        latency_s_mean=stats.latency_s_mean if stats.latency_s_mean > 0 else None,
    )


def export_abstract(rows: Iterable[GradeRow]) -> list[dict[str, Any]]:
    """``crb ledger export --abstract``: every full-key cell, allowlisted, key-sorted."""
    cells = [to_abstract_cell(s) for s in all_cell_stats(rows)]
    cells.sort(key=lambda c: c.key)
    return [c.to_dict() for c in cells]


# ---------------------------------------------------------------------------
# Aggregation across organisations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrgContribution:
    """One organisation's bundle, keyed by an OPAQUE hash used only to count distinct
    contributors. ``opted_in=False`` contributions are dropped before aggregation."""

    org_hash: str
    cells: tuple[AbstractCell, ...]
    opted_in: bool = True

    def __post_init__(self) -> None:
        if not self.org_hash:
            raise ValueError("org_hash is required (an opaque, salted token)")
        object.__setattr__(self, "cells", tuple(self.cells))


@dataclass(frozen=True)
class SharedCell:
    """A released cross-organisation aggregate for one cell key.

    ``contributor_count`` ≥ ``min_cohort_k`` by construction. ``trusted`` is
    ``False`` whenever any contributor reported ``false_q1 > 0``; ``false_q1``
    is the SUM, so the signal never vanishes. ``dp_epsilon`` records the budget
    spent on the released means (``None`` = exact).
    """

    process_step: str
    capability_class: str
    size: str
    language: str
    builder: str
    model: str
    provider: str
    contributor_count: int
    n: int
    clean: int
    false_q1: int
    point: float
    ci_low: float
    ci_high: float
    cost_usd_mean: float | None
    latency_s_mean: float | None
    trusted: bool
    dp_epsilon: float | None = None

    @property
    def key(self) -> AbstractKey:
        """The seven key fields as a tuple."""
        return (
            self.process_step,
            self.capability_class,
            self.size,
            self.language,
            self.builder,
            self.model,
            self.provider,
        )

    def to_dict(self) -> dict[str, Any]:
        """The released shape (means rounded; ``None`` where no contributor had the axis)."""
        return {
            "process_step": self.process_step,
            "capability_class": self.capability_class,
            "size": self.size,
            "language": self.language,
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "contributor_count": self.contributor_count,
            "n": self.n,
            "clean": self.clean,
            "false_q1": self.false_q1,
            "point": round(self.point, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "cost_usd_mean": None if self.cost_usd_mean is None else round(self.cost_usd_mean, 6),
            "latency_s_mean": None
            if self.latency_s_mean is None
            else round(self.latency_s_mean, 3),
            "trusted": self.trusted,
            "dp_epsilon": self.dp_epsilon,
        }


def _weighted_mean(pairs: Iterable[tuple[float | None, int]]) -> float | None:
    """n-weighted mean over ``(value, n)``; ``None`` values are skipped; ``None``
    when no contributor carried the axis; unweighted when every weight is 0."""
    vals = [(v, w) for v, w in pairs if v is not None]
    if not vals:
        return None
    total_w = sum(w for _, w in vals)
    if total_w <= 0:
        return sum(v for v, _ in vals) / len(vals)
    return sum(v * w for v, w in vals) / total_w


def _laplace(scale: float, rng: random.Random) -> float:
    """One Laplace(0, scale) draw from the SEEDED rng (inverse-CDF)."""
    if scale <= 0:
        return 0.0
    u = rng.random() - 0.5
    sign = 1.0 if u >= 0 else -1.0
    return -scale * sign * math.log(1.0 - 2.0 * abs(u))


def _normalise(
    contributions: Mapping[str, Iterable[AbstractCell]] | Iterable[OrgContribution],
) -> list[tuple[str, tuple[AbstractCell, ...]]]:
    """Both accepted input shapes → ``[(org_hash, cells)]``, opted-out bundles dropped."""
    if isinstance(contributions, Mapping):
        return [(str(h), tuple(cells)) for h, cells in contributions.items()]
    return [(c.org_hash, c.cells) for c in contributions if c.opted_in]


def aggregate_abstract_cells(
    contributions: Mapping[str, Iterable[AbstractCell]] | Iterable[OrgContribution],
    *,
    min_cohort_k: int = DEFAULT_MIN_COHORT_K,
    dp_epsilon: float | None = None,
    seed: int | None = None,
    rng: random.Random | None = None,
) -> list[SharedCell]:
    """Merge per-organisation abstract cells into k-anonymous, trust-preserving
    :class:`SharedCell` rows.

    ``contributions`` is either ``{opaque_org_hash: cells}`` (every key assumed
    opted-in) or an iterable of :class:`OrgContribution` (filtered on
    ``opted_in``). For each key: suppress if fewer than ``min_cohort_k``
    distinct organisations; else pool the counts (``n``, ``clean``,
    ``false_q1`` are sums), take n-weighted means for cost and latency, and
    recompute the point and its Wilson interval from the pooled counts. With
    ``dp_epsilon`` the released means are noised (see the module docstring).
    Sorted by key. Pure.
    """
    if min_cohort_k < 1:
        raise ValueError(f"min_cohort_k must be >= 1, got {min_cohort_k}")
    if dp_epsilon is not None and dp_epsilon <= 0:
        raise ValueError(f"dp_epsilon must be > 0 when set, got {dp_epsilon}")
    noise = rng if rng is not None else random.Random(seed)  # noqa: S311 — DP noise, seeded
    scale = (DP_SENSITIVITY / dp_epsilon) if dp_epsilon is not None else 0.0

    by_key: dict[AbstractKey, list[tuple[str, AbstractCell]]] = {}
    for org_hash, cells in _normalise(contributions):
        for cell in cells:
            by_key.setdefault(cell.key, []).append((org_hash, cell))

    shared: list[SharedCell] = []
    for key in sorted(by_key):
        entries = by_key[key]
        orgs = {h for h, _ in entries}
        if len(orgs) < min_cohort_k:
            continue  # suppressed: no released number is attributable to one organisation
        group = [c for _, c in entries]
        n = sum(c.n for c in group)
        clean = sum(c.clean for c in group)
        fq1 = sum(c.false_q1 for c in group)
        cost = _weighted_mean((c.cost_usd_mean, c.n) for c in group)
        latency = _weighted_mean((c.latency_s_mean, c.n) for c in group)
        point = (clean / n) if n else 0.0
        if dp_epsilon is not None:
            # the released clean count is DERIVED from the noised point, so the exact
            # count cannot be read back; n and false_q1 stay exact (they gate trust)
            point = min(1.0, max(0.0, point + _laplace(scale, noise)))
            clean = min(n, max(0, round(point * n)))
            if cost is not None:
                cost = max(0.0, cost + _laplace(scale, noise))
            if latency is not None:
                latency = max(0.0, latency + _laplace(scale, noise))
        ci = wilson_interval(clean, n)
        shared.append(
            SharedCell(
                *key,
                contributor_count=len(orgs),
                n=n,
                clean=clean,
                false_q1=fq1,
                point=point,
                ci_low=ci.low,
                ci_high=ci.high,
                cost_usd_mean=cost,
                latency_s_mean=latency,
                trusted=(fq1 == 0),
                dp_epsilon=dp_epsilon,
            )
        )
    return shared
