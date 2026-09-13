"""Human sign-off ledger — the verification tier is EARNED, never asserted.

The grade ledger records what was *measured*; it is never rewritten. A human
attestation that the evidence for a cell was reviewed lives in a SEPARATE
append-only, hash-chained JSONL ledger of :class:`SignoffRecord` rows, and is
overlaid onto a capability map at read time (:func:`apply_signoffs`), lifting a
cell's ``verification_tier`` from ``automated-pass`` to ``human-verified`` (or
``ab-confirmed``).

Scope
-----
A record is keyed by ``(repo, cell-or-class)``: the repo whose evidence the
human reviewed (``"*"`` = an attestation that is not repo-specific) and a cell
*pattern* over the seven key fields where ``"*"`` means "any". A record
matches a cell when every pattern field equals the cell's field or is ``"*"``;
a projected cell (``"*"`` in its own key) is matched only by a pattern that is
at least as wide — a Python-only attestation never lifts a class-wide cell.

Cardinal invariant, enforced in BOTH directions
-----------------------------------------------
* **At write** — :meth:`JsonlSignoffLedger.append` needs the live
  :class:`~crb.core.capability.CapabilityCell` and raises
  :class:`SignoffRefused` if the cell has ``false_q1 > 0``, has no measured
  evidence, or does not match the record's scope. The API maps the refusal to
  HTTP 409. The record's evidence snapshot (n, point, false-Q1, apparatus) is
  stamped from the cell so the audit trail shows what the human actually saw.
* **At read** — :func:`apply_signoffs` re-checks the cell's *current*
  ``false_q1`` and refuses to lift it; a later false-Q1 auto-invalidates the
  attestation and the gate self-heals. A human can never make an objectively
  wrong cell look trusted.

Revocation is another append: a record with ``revoked=True`` for the same
scope supersedes the earlier attestation (latest record per scope wins).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from crb.core.capability import (
    EARNED_TIERS,
    TIER_AB_CONFIRMED,
    TIER_HUMAN_VERIFIED,
    WILDCARD,
    CapabilityCell,
    CapabilityMap,
    key_matches,
)
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import GENESIS_HASH, CellKey, LedgerIntegrityError
from crb.core.redact import redact
from crb.core.version import APPARATUS_VERSION

SIGNOFF_SCHEMA = "crb.signoff.v1"

#: Earned-tier precedence when several active attestations match one cell.
_TIER_RANK: dict[str, int] = {TIER_HUMAN_VERIFIED: 1, TIER_AB_CONFIRMED: 2}


class SignoffRefused(ValueError):
    """The write boundary refused an attestation (false-Q1 > 0, no evidence, scope
    mismatch). Mapped to HTTP 409 by the API."""


@dataclass(frozen=True)
class SignoffRecord:
    """One human attestation about a cell scope, with the evidence it was made on."""

    repo: str
    capability_class: str
    verifier: str
    size: str = WILDCARD
    language: str = WILDCARD
    builder: str = WILDCARD
    model: str = WILDCARD
    provider: str = WILDCARD
    process_step: str = WILDCARD
    tier: str = TIER_HUMAN_VERIFIED
    note: str = ""
    revoked: bool = False
    verified_at: str = field(default_factory=utc_now_iso)
    # Evidence snapshot — what the human saw (stamped at write time from the cell).
    n_at_signoff: int = 0
    point_at_signoff: float = 0.0
    false_q1_at_signoff: int = 0
    apparatus_version: str = APPARATUS_VERSION
    schema: str = SIGNOFF_SCHEMA
    record_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if not self.repo:
            raise ValueError("repo is required ('*' for an attestation not tied to one repo)")
        if not self.capability_class or self.capability_class == WILDCARD:
            raise ValueError("an attestation must name a capability_class")
        if not self.verifier:
            raise ValueError("verifier is required (who signed, or who revoked)")
        if self.tier not in EARNED_TIERS:
            raise ValueError(f"tier must be one of {EARNED_TIERS}, got {self.tier!r}")
        if self.false_q1_at_signoff > 0 and not self.revoked:
            raise SignoffRefused("an attestation cannot be made on evidence with false-Q1 > 0")
        object.__setattr__(self, "note", redact(self.note))
        if not self.record_id:
            object.__setattr__(self, "record_id", uuid.uuid4().hex)

    # --- scope -------------------------------------------------------------------
    def scope(self) -> CellKey:
        """The cell pattern this attestation covers (``"*"`` = any)."""
        return CellKey(
            process_step=self.process_step,
            capability_class=self.capability_class,
            size=self.size,
            language=self.language,
            builder=self.builder,
            model=self.model,
            provider=self.provider,
        )

    def key(self) -> tuple[str, ...]:
        """Identity for latest-wins collapse: ``(repo, *scope)``."""
        return (self.repo, *self.scope().to_tuple())

    def matches(self, cell: CapabilityCell, *, repo: str = WILDCARD) -> bool:
        """True when the record's repo covers ``repo`` and its scope covers the cell."""
        return self.repo in (WILDCARD, repo) and key_matches(self.scope(), cell.key)

    # --- hashing ------------------------------------------------------------------
    def body(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "row_hash"}

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> SignoffRecord:
        rec = replace(self, prev_hash=prev_hash)
        object.__setattr__(rec, "row_hash", rec.compute_hash())
        return rec

    def verify_hash(self) -> bool:
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation --------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignoffRecord:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def stamp_evidence(record: SignoffRecord, cell: CapabilityCell) -> SignoffRecord:
    """Copy the cell's current evidence into the record's snapshot fields."""
    if cell.stats is None:
        raise SignoffRefused(f"cell {cell.label!r} has no measured evidence to attest to")
    return replace(
        record,
        n_at_signoff=cell.stats.n,
        point_at_signoff=cell.stats.point,
        false_q1_at_signoff=cell.stats.false_q1,
        apparatus_version=",".join(cell.stats.apparatus_versions) or record.apparatus_version,
    )


def check_signable(record: SignoffRecord, cell: CapabilityCell, *, repo: str = WILDCARD) -> None:
    """Raise :class:`SignoffRefused` unless ``record`` may be written against ``cell``.

    A revocation is always writable (withdrawing trust never needs evidence).
    """
    if record.revoked:
        return
    if not record.matches(cell, repo=repo):
        raise SignoffRefused(
            f"attestation scope {record.key()} does not cover cell {cell.key.label!r} for repo {repo!r}"
        )
    if cell.stats is None:
        raise SignoffRefused(f"cell {cell.label!r} has no measured evidence — nothing to sign off")
    if cell.stats.false_q1 > 0:
        raise SignoffRefused(
            f"cell {cell.label!r} has false_q1={cell.stats.false_q1} > 0 — untrusted, cannot be signed off"
        )


# ---------------------------------------------------------------------------
# JSONL ledger (append-only, hash-chained)
# ---------------------------------------------------------------------------


class JsonlSignoffLedger:
    """Portable stdlib sign-off ledger. Same chain discipline as the grade ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        last = ""
        with self.path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            step = min(size, 65536)
            f.seek(size - step)
            chunk = f.read().decode("utf-8", errors="replace")
        for line in reversed(chunk.splitlines()):
            if line.strip():
                last = line
                break
        if not last:
            return GENESIS_HASH
        row_hash = str(json.loads(last).get("row_hash", ""))
        if not row_hash:
            raise LedgerIntegrityError(f"last record in {self.path} has no row_hash")
        return row_hash

    def append(
        self,
        record: SignoffRecord,
        cell: CapabilityCell | None = None,
        *,
        repo: str = WILDCARD,
    ) -> SignoffRecord:
        """Check, stamp, chain and append. Returns the chained record.

        ``cell`` is the live cell the human reviewed; it is required for an
        attestation (the write boundary re-checks false-Q1 = 0 against it) and
        optional for a revocation.
        """
        if not record.revoked:
            if cell is None:
                raise SignoffRefused("an attestation needs the live cell it is made on")
            check_signable(record, cell, repo=repo)
            record = stamp_evidence(record, cell)
        chained = record.chained(self._last_hash())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return chained

    def records(self) -> Iterator[SignoffRecord]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield SignoffRecord.from_dict(json.loads(line))

    def verify(self) -> int:
        return verify_signoff_chain(self.records())


def verify_signoff_chain(records: Iterable[SignoffRecord]) -> int:
    prev = GENESIS_HASH
    n = 0
    for rec in records:
        n += 1
        if rec.prev_hash != prev:
            raise LedgerIntegrityError(f"sign-off {n} ({rec.record_id[:8]}) prev_hash mismatch")
        if not rec.verify_hash():
            raise LedgerIntegrityError(f"sign-off {n} ({rec.record_id[:8]}) row_hash mismatch")
        prev = rec.row_hash
    return n


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


def active_signoffs(records: Iterable[SignoffRecord]) -> dict[tuple[str, ...], SignoffRecord]:
    """Collapse the log to the latest record per scope; drop revoked scopes."""
    latest: dict[tuple[str, ...], SignoffRecord] = {}
    for rec in records:
        latest[rec.key()] = rec
    return {k: r for k, r in latest.items() if not r.revoked}


def apply_signoffs(
    cells: Iterable[CapabilityCell],
    signoffs: Iterable[SignoffRecord],
    *,
    repo: str = WILDCARD,
) -> list[CapabilityCell]:
    """Lift matching cells to their attested tier; return NEW cells.

    A cell is lifted only when it is measured, its CURRENT ``false_q1`` is 0 and
    an active attestation covers it for ``repo`` (``"*"`` applies only records
    that are themselves repo-agnostic — an unscoped read never borrows another
    repo's attestation). The highest matching earned tier wins. Everything else
    passes through unchanged.
    """
    active = list(active_signoffs(signoffs).values())
    out: list[CapabilityCell] = []
    for cell in cells:
        if cell.stats is None or cell.stats.false_q1 > 0:
            out.append(cell)
            continue
        tiers = [r.tier for r in active if r.matches(cell, repo=repo)]
        if not tiers:
            out.append(cell)
            continue
        best = max(tiers, key=lambda t: _TIER_RANK.get(t, 0))
        current = _TIER_RANK.get(cell.verification_tier or "", 0)
        out.append(cell.with_tier(best) if _TIER_RANK[best] > current else cell)
    return out


def apply_signoffs_to_map(
    cmap: CapabilityMap, signoffs: Iterable[SignoffRecord], *, repo: str = WILDCARD
) -> CapabilityMap:
    return cmap.with_cells(apply_signoffs(cmap.cells, signoffs, repo=repo))
