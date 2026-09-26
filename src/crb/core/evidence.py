"""The per-task evidence pack. "No pack ⇒ no Q1."

An :class:`EvidencePack` is the complete, redacted, self-describing record of
one graded trial: the task, the four belts with their test-run tails, the diff
statistics (hash + counts, never the raw diff by default), who built it with what
model at what cost, and the **apparatus stamp** that says which grader, runner,
executor and policy produced the verdict. Its canonical-JSON hash is what the
ledger row carries; a ledger row without a pack hash cannot be written.

Packs are what an auditor opens. They contain no secrets (everything passes
through :mod:`crb.core.redact`) and, by default, no raw model output.

Navigation
----------
What it is:   The evidence pack — ``EvidencePack`` (task + grade + apparatus + builder),
              its content hash, and the three helpers the ledgers share (canonical JSON,
              SHA-256, UTC timestamps).
What it does: Assembles the complete, redacted record of one graded trial and hashes its
              canonical form; the hash is what a ledger row must cite before it can be
              clean. Carries the apparatus stamp so every verdict names the instrument
              that produced it, and the builder's spend so cost and latency are evidence,
              not estimates. Never holds a raw diff or transcript inline.
How:          ``EvidencePack.body`` serialises each part with its own ``to_dict`` →
              ``canonical_json`` (sorted keys, no whitespace) → ``sha256_text`` =
              ``pack_hash``; ``verify_pack`` recomputes it from a stored pack.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/ledger.py (the row that cites ``pack_hash``; reuses the
              helpers for its own chain), src/crb/core/run.py (builds and writes the pack
              before the row), src/crb/core/grade.py (the GradeResult inside),
              src/crb/core/version.py (the apparatus and crb versions stamped),
              src/crb/store/models.py (the ``evidence`` table keyed by pack hash),
              src/crb/core/redact.py (what the test tails passed through)
Tested by:    tests/test_evidence.py, tests/test_run.py, tests/test_ledger.py,
              tests/test_store_ledger.py
Touch when:   never for a new repository; adding a field to the pack changes every future
              ``pack_hash`` (old packs still verify — the hash is over what they contain) —
              bump ``EVIDENCE_SCHEMA``, keep ``verify_pack`` schema-agnostic, and update
              docs/DATA-RETENTION.md#2-retention-defaults-zero-raw-retention if the field
              holds raw material.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from crb.core.grade import GradeResult
from crb.core.spec import TaskSpec
from crb.core.version import APPARATUS_VERSION, __version__

EVIDENCE_SCHEMA = "crb.evidence.v1"


def canonical_json(obj: Any) -> str:
    """The ONE serialisation every hash in the product is taken over: sorted keys, no
    whitespace, UTF-8 as is. Two processes (the JSONL ledger and the database) must
    produce the same bytes for the same row or their chains would not match."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    """Hex SHA-256 of ``text`` (UTF-8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    """Now, in UTC, to the second, ISO-8601 with offset — the timestamp every record
    carries (whole seconds: the same string whichever store it round-trips through)."""
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ApparatusStamp:
    """Which instrument produced a verdict. Evidence expires with its apparatus.

    ``apparatus_version`` is the meaning of the verdict (belts, size table, taxonomy —
    ``crb.core.version``); ``crb_version`` the code that ran; ``runner`` / ``executor``
    the toolchain and the sandbox; ``corpus_sha`` and ``policy_version`` which task set
    and routing rule. Numbers from different stamps are never blended.
    """

    apparatus_version: str = APPARATUS_VERSION
    crb_version: str = __version__
    grader: str = "crb.core.grade"
    runner: str = ""
    executor: Mapping[str, Any] = field(default_factory=dict)
    corpus_sha: str = ""
    policy_version: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)
    #: The posture the verdict was graded in (``Posture.to_dict()``, ADR-0019) — part of
    #: the instrument. Written only when set, so a pack from before it existed hashes as
    #: it always did.
    posture: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "executor", dict(self.executor))
        object.__setattr__(self, "extra", dict(self.extra))
        object.__setattr__(self, "posture", dict(self.posture))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "apparatus_version": self.apparatus_version,
            "crb_version": self.crb_version,
            "grader": self.grader,
            "runner": self.runner,
            "executor": dict(self.executor),
            "corpus_sha": self.corpus_sha,
            "policy_version": self.policy_version,
            "extra": dict(self.extra),
        }
        if self.posture:
            d["posture"] = dict(self.posture)
        return d


@dataclass(frozen=True)
class BuilderRef:
    """Who built the trial, at what cost. ``transcript_ref`` is an opt-in pointer
    to raw model output stored elsewhere under a retention policy — never inline.

    ``name`` / ``model`` / ``provider`` become three fields of the cell key, so they
    must be the SAME strings across runs for rows to pool. ``note`` starts with the
    builder's stop reason (``max_turns; …``) — the ledger reads it to name a
    ``budget`` failure — and carries ``cost unknown`` when tokens were metered but no
    price was known.
    """

    name: str = ""
    model: str = ""
    provider: str = ""
    mode: str = "sighted"
    attempts: int = 1
    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0  # prompt-cache reads (Anthropic); not billed as input
    cost_usd: float = 0.0
    latency_s: float = 0.0
    transcript_ref: str = ""
    budget: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget", dict(self.budget))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "provider": self.provider,
            "mode": self.mode,
            "attempts": self.attempts,
            "turns": self.turns,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "cost_usd": round(self.cost_usd, 6),
            "latency_s": round(self.latency_s, 3),
            "transcript_ref": self.transcript_ref,
            "budget": dict(self.budget),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> BuilderRef:
        """Rebuild from :meth:`to_dict`; unknown keys are ignored."""
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class EvidencePack:
    """The record of one graded trial (module docstring). ``trial`` is the ladder
    position (``r1`` …), ``actor`` who ran it, ``notes`` free-form provenance the
    orchestrator adds (the rung label, a transcript reference)."""

    task: TaskSpec
    grade: GradeResult
    apparatus: ApparatusStamp
    builder: BuilderRef | None = None
    run_id: str = ""
    trial: str = ""
    actor: str = ""
    created: str = field(default_factory=utc_now_iso)
    notes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "notes", dict(self.notes))

    def body(self) -> dict[str, Any]:
        """Everything that is hashed."""
        return {
            "schema": EVIDENCE_SCHEMA,
            "task": self.task.to_dict(),
            "grade": self.grade.to_dict(),
            "apparatus": self.apparatus.to_dict(),
            "builder": self.builder.to_dict() if self.builder else None,
            "run_id": self.run_id,
            "trial": self.trial,
            "actor": self.actor,
            "created": self.created,
            "notes": dict(self.notes),
        }

    @property
    def pack_hash(self) -> str:
        """SHA-256 of the canonical body — the pack's identity and the ledger's citation."""
        return sha256_text(canonical_json(self.body()))

    def to_dict(self) -> dict[str, Any]:
        """The body plus its own ``pack_hash`` (what is written to disk / the store)."""
        d = self.body()
        d["pack_hash"] = self.pack_hash
        return d

    def to_json(self) -> str:
        """Human-readable JSON (indented) — the hash is over the canonical form, not this."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=1, ensure_ascii=False)


def verify_pack(d: Mapping[str, Any]) -> bool:
    """Recompute the hash of a serialised pack and compare."""
    body = {k: v for k, v in d.items() if k != "pack_hash"}
    return sha256_text(canonical_json(body)) == d.get("pack_hash")
