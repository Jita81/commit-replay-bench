"""The per-task evidence pack. "No pack ⇒ no Q1."

An :class:`EvidencePack` is the complete, redacted, self-describing record of
one graded trial: the task, the four belts with their test-run tails, the diff
statistics (hash + counts, never the raw diff by default), who built it with what
model at what cost, and the **apparatus stamp** that says which grader, runner,
executor and policy produced the verdict. Its canonical-JSON hash is what the
ledger row carries; a ledger row without a pack hash cannot be written.

Packs are what an auditor opens. They contain no secrets (everything passes
through :mod:`crb.core.redact`) and, by default, no raw model output.
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
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ApparatusStamp:
    """Which instrument produced a verdict. Evidence expires with its apparatus."""

    apparatus_version: str = APPARATUS_VERSION
    crb_version: str = __version__
    grader: str = "crb.core.grade"
    runner: str = ""
    executor: Mapping[str, Any] = field(default_factory=dict)
    corpus_sha: str = ""
    policy_version: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "executor", dict(self.executor))
        object.__setattr__(self, "extra", dict(self.extra))

    def to_dict(self) -> dict[str, Any]:
        return {
            "apparatus_version": self.apparatus_version,
            "crb_version": self.crb_version,
            "grader": self.grader,
            "runner": self.runner,
            "executor": dict(self.executor),
            "corpus_sha": self.corpus_sha,
            "policy_version": self.policy_version,
            "extra": dict(self.extra),
        }


@dataclass(frozen=True)
class BuilderRef:
    """Who built the trial, at what cost. ``transcript_ref`` is an opt-in pointer
    to raw model output stored elsewhere under a retention policy — never inline."""

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
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class EvidencePack:
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
        return sha256_text(canonical_json(self.body()))

    def to_dict(self) -> dict[str, Any]:
        d = self.body()
        d["pack_hash"] = self.pack_hash
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=1, ensure_ascii=False)


def verify_pack(d: Mapping[str, Any]) -> bool:
    """Recompute the hash of a serialised pack and compare."""
    body = {k: v for k, v in d.items() if k != "pack_hash"}
    return sha256_text(canonical_json(body)) == d.get("pack_hash")
