"""Sealed corpus — commitment BEFORE measurement.

Turns a set of mined :class:`~crb.core.spec.TaskSpec` into a CORPUS MANIFEST the
operator can COMMIT TO before any model run — the substrate that makes
confirmatory (pre-registered) benchmark science possible instead of
exploratory-only runs.

Every task carries its git AUTHORED date (``%aI``, recorded by the miner) so
exposure-vs-model-cutoff analysis is a first-class column, not an afterthought:
``suspected_exposure`` stays ``None`` until the model set is chosen, then
:func:`suspected_exposure` gives the per-model comparison. Authored (not committer)
date is the honest exposure bound: it is when the change was written, unaffected
by later rebases that refresh the committer date.

Deterministic end-to-end (no randomness anywhere):

* **stratified sampling** — ``per_cell`` tasks per (class × size) cell; within a
  cell tasks are ordered by ``sha256(task_id)`` (a fixed pseudo-random order that
  does not favour recency) and the first N taken;
* **split assignment** — dev/val/sealed by hash of the task id mapped into [0, 1)
  against the split fractions (same input → same split, always, recomputable by
  anyone);
* **sealing** — sealed tasks appear in the PUBLIC manifest as id + split +
  ``detail_hash`` only; full detail lives in the operator-held PRIVATE manifest;
* **commitment** — ``manifest_hash`` = sha256 over the canonical JSON (sorted keys,
  compact separators, UTF-8) of the public manifest, written to
  ``corpus_commitment.txt`` for the operator to timestamp and commit BEFORE any
  model run. :func:`verify_outputs` re-derives every hash from the written files.

Navigation
----------
What it is:   The sealed-corpus builder — pure functions from mined ``TaskSpec``s to a
              stratified, hash-split, sealed pair of manifests and a commitment hash.
What it does: Samples ``per_cell`` tasks per (class × size) cell in ``sha256(task_id)``
              order, assigns dev/val/sealed by hash of the id, redacts sealed tasks in the
              public manifest to id + split + detail hash, writes both manifests and a
              commitment file, and re-verifies every hash from disk. No randomness, so
              anyone can recompute the split. Refuses to seal an empty corpus.
How:          ``sample_per_cell`` → ``build_task_record`` (authored date from the task or
              the repo; ``detail_hash`` over the record) → ``split_for_sha`` →
              ``build_manifests`` → ``write_outputs`` / ``verify_outputs``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/spec.py (``TaskSpec.authored`` and the cell fields),
              src/crb/core/evidence.py (``canonical_json``/``sha256_text`` — the same hashing
              as evidence packs), src/crb/core/git.py (``author_date`` fallback),
              src/crb/core/version.py (the apparatus stamped into every manifest),
              src/crb/core/oracle/__init__.py (the only current entry point — no CLI verb
              or route consumes this yet)
Tested by:    tests/test_oracle_sealed_corpus.py
Touch when:   never for a new repository; a new field in a task record changes every
              ``detail_hash`` and the public manifest — bump ``CORPUS_SCHEMA`` and say so in
              docs/EVIDENCE-AND-CLAIMS.md (a re-sealed corpus is a new commitment).
Claims:       A commitment proves the task set was fixed before a run, not that the model
              never saw the code — exposure is per-model reasoning on authored dates
              (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.evidence import canonical_json, sha256_text
from crb.core.git import GitRepo
from crb.core.spec import TaskSpec
from crb.core.version import APPARATUS_VERSION

CORPUS_SCHEMA = "crb.sealed-corpus.v1"
SPLITS: tuple[str, ...] = ("dev", "val", "sealed")
DEFAULT_SPLIT = "dev=0.4,val=0.3,sealed=0.3"
#: the ONLY keys a sealed task exposes in the public manifest.
REDACTED_KEYS: tuple[str, ...] = ("task_id", "split", "detail_hash")

PUBLIC_MANIFEST = "corpus_manifest.json"
PRIVATE_MANIFEST = "corpus_manifest.private.json"
COMMITMENT = "corpus_commitment.txt"

UNSEALED_PLACEHOLDER = (
    "sealed_at: <UNSEALED — operator: replace with ISO-8601 UTC timestamp "
    "and git-commit this file BEFORE any model run>"
)


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    """The commitment hash: sha256 over canonical JSON of the manifest."""
    return sha256_text(canonical_json(manifest))


# ---------------------------------------------------------------------------
# deterministic split + sampling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitFractions:
    """dev/val/sealed fractions; validated to sum to 1 (±1e-6), none negative."""

    dev: float = 0.4
    val: float = 0.3
    sealed: float = 0.3

    def __post_init__(self) -> None:
        for name in SPLITS:
            if getattr(self, name) < 0:
                raise ValueError(f"split '{name}' fraction must be >= 0")
        total = self.dev + self.val + self.sealed
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"split fractions must sum to 1.0, got {total}")

    @classmethod
    def parse(cls, text: str) -> SplitFractions:
        """``dev=0.4,val=0.3,sealed=0.3`` → fractions (validated)."""
        fractions: dict[str, float] = {}
        for part in text.split(","):
            name, _, raw = part.strip().partition("=")
            if name not in SPLITS:
                raise ValueError(f"unknown split '{name}' — expected {'/'.join(SPLITS)}")
            try:
                fractions[name] = float(raw)
            except ValueError as exc:
                raise ValueError(f"split '{name}' has non-numeric fraction {raw!r}") from exc
        missing = [s for s in SPLITS if s not in fractions]
        if missing:
            raise ValueError(f"missing split fraction(s): {', '.join(missing)}")
        return cls(**fractions)

    def to_dict(self) -> dict[str, float]:
        """``{"dev": …, "val": …, "sealed": …}`` in split order (stored in every manifest)."""
        return {name: getattr(self, name) for name in SPLITS}


DEFAULT_FRACTIONS = SplitFractions()


def parse_split(text: str) -> SplitFractions:
    """Module-level alias of :meth:`SplitFractions.parse` for CLI argument parsing."""
    return SplitFractions.parse(text)


def split_for_sha(sha: str, fractions: SplitFractions = DEFAULT_FRACTIONS) -> str:
    """Deterministic dev/val/sealed assignment: hash of the sha, no randomness."""
    # 64 bits of the digest as a uniform u in [0, 1); cumulative fractions bucket it.
    u = int(hashlib.sha256(sha.encode("utf-8")).hexdigest()[:16], 16) / 2**64
    cumulative = 0.0
    for name in SPLITS:
        cumulative += getattr(fractions, name)
        if u < cumulative:
            return name
    return SPLITS[-1]  # float-sum edge: u ≈ 1.0 lands in the last split


def cell_key(task: TaskSpec) -> str:
    """(class × size) cell key — the stratification unit."""
    return f"{task.capability_class}|{task.size}"


def sample_per_cell(tasks: Iterable[TaskSpec], per_cell: int) -> list[TaskSpec]:
    """First ``per_cell`` tasks per (class × size) cell in sha256(task_id) order.

    Hash order is a fixed pseudo-random shuffle: deterministic for a given corpus
    yet not biased toward recent commits the way mine-order (newest first) would
    be. ``per_cell <= 0`` means no cap.
    """
    by_cell: dict[str, list[TaskSpec]] = {}
    for task in tasks:
        by_cell.setdefault(cell_key(task), []).append(task)
    out: list[TaskSpec] = []
    for _, members in sorted(by_cell.items()):
        ordered = sorted(members, key=lambda t: sha256_text(t.task_id))
        out.extend(ordered if per_cell <= 0 else ordered[:per_cell])
    return out


# ---------------------------------------------------------------------------
# exposure reasoning
# ---------------------------------------------------------------------------


def _parse_iso(text: str) -> _dt.datetime | None:
    """An aware datetime from ISO-8601 text (naive → UTC), or ``None`` when unparseable."""
    try:
        d = _dt.datetime.fromisoformat(text.strip())
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=_dt.UTC)


def suspected_exposure(authored: str, cutoffs: Mapping[str, str]) -> dict[str, bool | None]:
    """Per model: was this change authored on/before the model's training cutoff?

    ``True`` = the change predates the cutoff (may have been seen); ``False`` = it
    was authored after; ``None`` = undecidable (missing/unparseable date). Cutoffs
    given as a bare date (``2025-03-01``) are read as end-of-day UTC.
    """
    when = _parse_iso(authored) if authored else None
    out: dict[str, bool | None] = {}
    for model, cutoff in cutoffs.items():
        raw = cutoff.strip()
        limit = _parse_iso(raw + "T23:59:59+00:00" if len(raw) == 10 else raw)
        out[model] = None if when is None or limit is None else when <= limit
    return out


# ---------------------------------------------------------------------------
# manifest construction
# ---------------------------------------------------------------------------


def build_task_record(
    task: TaskSpec,
    *,
    visibility: str = "private",
    fractions: SplitFractions = DEFAULT_FRACTIONS,
    repo: GitRepo | None = None,
) -> dict[str, Any]:
    """One FULL task record (private-manifest form) + its detail hash.

    ``authored`` comes from the task (the miner records ``%aI``); when it is empty
    and a ``repo`` is given it is looked up — a corpus without authored dates
    cannot reason about exposure, so the gap is filled rather than hidden.
    """
    authored = task.authored
    if not authored and repo is not None:
        authored = repo.author_date(task.task_id)
    record: dict[str, Any] = {
        "task_id": task.task_id,
        "repo": task.repo,
        "authored": authored,
        "subject": task.subject,
        "capability_class": task.capability_class,
        "size": task.size,
        "language": task.language,
        "pool": task.pool,
        "src_files": list(task.src_files),
        "test_files": list(task.test_files),
        "gold_clean": task.gold_clean,
        "visibility": visibility,
        # None until the model set is chosen; then suspected_exposure() fills it in.
        "suspected_exposure": None,
        "split": split_for_sha(task.task_id, fractions),
    }
    # The hash binds every field above; verify_outputs recomputes it without this key.
    record["detail_hash"] = sha256_text(canonical_json(record))
    return record


def redact_task(record: Mapping[str, Any]) -> dict[str, Any]:
    """Public form of a sealed task: id + split + detail hash only, nothing else."""
    return {k: record[k] for k in REDACTED_KEYS}


@dataclass(frozen=True)
class CorpusManifests:
    """``public`` is what gets committed to; ``private`` is operator-held."""

    public: Mapping[str, Any]
    private: Mapping[str, Any]

    @property
    def manifest_hash(self) -> str:
        """The commitment hash (over the PUBLIC manifest)."""
        return manifest_hash(self.public)

    @property
    def private_hash(self) -> str:
        """Hash of the operator-held manifest, recorded in the commitment file too."""
        return manifest_hash(self.private)

    @property
    def split_counts(self) -> dict[str, int]:
        """Tasks per split, from the public manifest."""
        counts = dict.fromkeys(SPLITS, 0)
        for task in self.public["tasks"]:
            counts[str(task["split"])] += 1
        return counts


def build_manifests(
    tasks: Iterable[TaskSpec],
    *,
    per_cell: int = 0,
    fractions: SplitFractions = DEFAULT_FRACTIONS,
    visibility: str = "private",
    repo: GitRepo | None = None,
) -> CorpusManifests:
    """Stratify → split → seal. The public manifest redacts sealed tasks to id +
    hashes; the private one carries full detail for every task."""
    if visibility not in {"private", "public"}:
        raise ValueError("visibility must be 'private' or 'public'")
    sampled = sample_per_cell(tasks, per_cell)
    records = [
        build_task_record(t, visibility=visibility, fractions=fractions, repo=repo) for t in sampled
    ]
    records.sort(key=lambda r: str(r["task_id"]))

    cells: dict[str, dict[str, int]] = {}
    for r in records:
        key = f"{r['capability_class']}|{r['size']}"
        counts = cells.setdefault(key, dict.fromkeys((*SPLITS, "total"), 0))
        counts[str(r["split"])] += 1
        counts["total"] += 1

    base: dict[str, Any] = {
        "schema": CORPUS_SCHEMA,
        "apparatus_version": APPARATUS_VERSION,
        "repos": sorted({str(r["repo"]) for r in records}),
        "visibility": visibility,
        "per_cell": per_cell if per_cell > 0 else None,
        "split_fractions": fractions.to_dict(),
        "cells": {k: cells[k] for k in sorted(cells)},
    }
    private = {**base, "tasks": records}
    public = {
        **base,
        "tasks": [redact_task(r) if r["split"] == "sealed" else r for r in records],
    }
    return CorpusManifests(public, private)


# ---------------------------------------------------------------------------
# sealing / output / verification
# ---------------------------------------------------------------------------


def commitment_text(manifests: CorpusManifests) -> str:
    """The ``corpus_commitment.txt`` body: both hashes, the method, the counts and the
    UNSEALED placeholder the operator replaces with a timestamp before any model run."""
    counts = manifests.split_counts
    return (
        "\n".join(
            [
                "crb sealed-corpus commitment v1",
                f"manifest: {PUBLIC_MANIFEST}",
                f"manifest_hash: sha256:{manifests.manifest_hash}",
                f"private_manifest_hash: sha256:{manifests.private_hash}",
                "hash_method: sha256 over canonical JSON "
                '(sort_keys=True, separators=(",", ":"), UTF-8)',
                f"apparatus_version: {APPARATUS_VERSION}",
                (
                    f"tasks: total={len(manifests.public['tasks'])} dev={counts['dev']} "
                    f"val={counts['val']} sealed={counts['sealed']}"
                ),
                UNSEALED_PLACEHOLDER,
                f"note: {PRIVATE_MANIFEST} is OPERATOR-HELD — never publish it; "
                "sealed tasks are id + hashes only in the public manifest.",
            ]
        )
        + "\n"
    )


def write_outputs(out_dir: str | Path, manifests: CorpusManifests) -> dict[str, str]:
    """Write both manifests + the commitment file. Refuses an empty corpus (no
    commitment over nothing). Returns paths and the hash."""
    if not manifests.public["tasks"]:
        raise ValueError("refusing to seal an empty corpus")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    public_path = out / PUBLIC_MANIFEST
    private_path = out / PRIVATE_MANIFEST
    commitment_path = out / COMMITMENT
    public_path.write_text(
        json.dumps(manifests.public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    private_path.write_text(
        json.dumps(manifests.private, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    commitment_path.write_text(commitment_text(manifests), encoding="utf-8")
    return {
        "public": str(public_path),
        "private": str(private_path),
        "commitment": str(commitment_path),
        "manifest_hash": manifests.manifest_hash,
    }


def _committed_hash(commitment: str, key: str) -> str:
    """The ``sha256:`` value on the ``<key>:`` line of a commitment file, else ``""``."""
    for line in commitment.splitlines():
        if line.startswith(key + ": sha256:"):
            return line.split("sha256:", 1)[1].strip()
    return ""


def verify_outputs(out_dir: str | Path) -> dict[str, Any]:
    """Re-derive every hash from the written files and compare with the commitment.

    Returns ``{"public_ok", "private_ok", "detail_ok", "sealed_at_set", "manifest_hash"}``.
    ``detail_ok`` checks each private record's ``detail_hash`` binds its content.
    """
    out = Path(out_dir)
    commitment = (out / COMMITMENT).read_text(encoding="utf-8")
    public = json.loads((out / PUBLIC_MANIFEST).read_text(encoding="utf-8"))
    public_hash = manifest_hash(public)
    result: dict[str, Any] = {
        "manifest_hash": public_hash,
        "public_ok": public_hash == _committed_hash(commitment, "manifest_hash"),
        "private_ok": None,
        "detail_ok": None,
        "sealed_at_set": "UNSEALED" not in commitment,
    }
    private_path = out / PRIVATE_MANIFEST
    if private_path.exists():
        private = json.loads(private_path.read_text(encoding="utf-8"))
        result["private_ok"] = manifest_hash(private) == _committed_hash(
            commitment, "private_manifest_hash"
        )
        result["detail_ok"] = all(
            sha256_text(canonical_json({k: v for k, v in r.items() if k != "detail_hash"}))
            == r.get("detail_hash")
            for r in private["tasks"]
        )
    return result
