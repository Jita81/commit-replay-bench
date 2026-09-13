"""The append-only, hash-chained grade ledger and its cell statistics.

A :class:`GradeRow` is one graded trial, reduced to what capability statistics
and audit need. Rows are **append-only** and **hash-chained**: each row carries
``prev_hash`` (the previous row's ``row_hash``) and ``row_hash`` (SHA-256 of its
own canonical JSON). :func:`verify_chain` walks a ledger and proves nothing was
edited, reordered or removed.

Two invariants are enforced at *write* time, not read time:

* **false-Q1 = 0** — a row with ``clean=True`` must have every recorded belt
  ``True``, no disqualification and no error (:class:`FalseQ1Violation`);
* **no pack ⇒ no Q1** — a clean row must carry a non-empty ``evidence_pack_hash``.

Legacy census rows graded before belt 4 existed carry ``belt_set="v3-legacy"``
and ``provenance="imported:…"``; the invariant applies to the three belts they
recorded, and the capability layer reports them as a separate apparatus.

The JSONL implementation here is the portable, stdlib reference. The server
stores the same rows in a database with the same chain (see ``crb.store``).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.evidence import BuilderRef, canonical_json, sha256_text, utc_now_iso
from crb.core.grade import BELT_NAMES, FalseQ1Violation, GradeResult
from crb.core.spec import TaskSpec
from crb.core.stats import Interval, mean, wilson_interval
from crb.core.version import APPARATUS_VERSION

GRADE_SCHEMA = "crb.grade.v2"
BELT_SET_V4 = "v4"
BELT_SET_V3_LEGACY = "v3-legacy"
PROCESS_REPLAY = "replay"
PROCESS_FACTORY = "factory"

GENESIS_HASH = "0" * 64


class LedgerIntegrityError(RuntimeError):
    """The hash chain does not verify."""


@dataclass(frozen=True)
class CellKey:
    """The unit of measurement. Carries NO task id, NO repo, NO free text."""

    process_step: str
    capability_class: str
    size: str
    language: str
    builder: str
    model: str
    provider: str

    def to_tuple(self) -> tuple[str, ...]:
        return (
            self.process_step,
            self.capability_class,
            self.size,
            self.language,
            self.builder,
            self.model,
            self.provider,
        )

    def to_dict(self) -> dict[str, str]:
        return dict(zip(CELL_FIELDS, self.to_tuple(), strict=True))

    @property
    def label(self) -> str:
        return "|".join(self.to_tuple())


CELL_FIELDS: tuple[str, ...] = (
    "process_step",
    "capability_class",
    "size",
    "language",
    "builder",
    "model",
    "provider",
)


@dataclass(frozen=True)
class GradeRow:
    repo: str
    task_id: str
    clean: bool
    tests_unmodified: bool | None
    target_green: bool | None
    no_new_failures: bool | None
    source_changed: bool | None
    capability_class: str = ""
    size: str = ""
    language: str = ""
    pool: str = "standard"
    mode: str = "sighted"
    process_step: str = PROCESS_REPLAY
    builder: str = ""
    model: str = ""
    provider: str = ""
    run_id: str = ""
    trial: str = ""
    actor: str = ""
    created: str = field(default_factory=utc_now_iso)
    disqualified: bool = False
    dq_reason: str = ""
    error: str = ""
    new_failures_count: int = 0
    attempts: int = 1
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_s: float = 0.0
    oracle_strength: float | None = None
    gold_clean: bool | None = None
    evidence_pack_hash: str = ""
    apparatus_version: str = APPARATUS_VERSION
    belt_set: str = BELT_SET_V4
    provenance: str = "measured"
    labels: Mapping[str, str] = field(default_factory=dict)
    schema: str = GRADE_SCHEMA
    row_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", dict(self.labels))
        if not self.row_id:
            object.__setattr__(self, "row_id", uuid.uuid4().hex)
        if self.belt_set not in {BELT_SET_V4, BELT_SET_V3_LEGACY}:
            raise ValueError(f"belt_set must be {BELT_SET_V4!r} or {BELT_SET_V3_LEGACY!r}")
        self.assert_invariants()

    # --- invariants ------------------------------------------------------------
    def recorded_belts(self) -> tuple[str, ...]:
        return BELT_NAMES[:3] if self.belt_set == BELT_SET_V3_LEGACY else BELT_NAMES

    def belts_all_true(self) -> bool:
        return all(getattr(self, b) is True for b in self.recorded_belts())

    def assert_invariants(self) -> None:
        if self.clean:
            if not self.belts_all_true():
                raise FalseQ1Violation(
                    f"ledger refuses clean row {self.task_id[:10]} ({self.repo}): belts="
                    f"{ {b: getattr(self, b) for b in self.recorded_belts()} }"
                )
            if self.disqualified or self.error:
                raise FalseQ1Violation(
                    f"ledger refuses clean row {self.task_id[:10]}: disqualified={self.disqualified} error={self.error!r}"
                )
            if not self.evidence_pack_hash:
                raise FalseQ1Violation(
                    f"ledger refuses clean row {self.task_id[:10]}: no evidence pack (no pack ⇒ no Q1)"
                )

    # --- keys ------------------------------------------------------------------
    @property
    def cell(self) -> CellKey:
        return CellKey(
            self.process_step,
            self.capability_class,
            self.size,
            self.language,
            self.builder,
            self.model,
            self.provider,
        )

    @property
    def eligible(self) -> bool:
        """Counts toward a cell's denominator: graded (not DQ) on a judgeable oracle."""
        return not self.disqualified and self.gold_clean is not False

    # --- hashing ---------------------------------------------------------------
    def body(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "row_hash"}
        d["labels"] = dict(self.labels)
        return d

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> GradeRow:
        """Return a copy with ``prev_hash`` set and ``row_hash`` computed."""
        d = self.body()
        d["prev_hash"] = prev_hash
        row = GradeRow(**d)
        object.__setattr__(row, "row_hash", row.compute_hash())
        return row

    def verify_hash(self) -> bool:
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> GradeRow:
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


def grade_row_from_result(
    result: GradeResult,
    task: TaskSpec,
    *,
    pack_hash: str,
    builder: BuilderRef | None = None,
    run_id: str = "",
    trial: str = "r1",
    actor: str = "",
    process_step: str = PROCESS_REPLAY,
    language: str = "",
    labels: Mapping[str, str] | None = None,
    builder_error: str = "",
) -> GradeRow:
    """Reduce a :class:`GradeResult` + its evidence-pack hash to the ledger row.

    The row's ``clean`` is the result's ``clean``; :class:`GradeRow` re-checks it
    against the belts at construction, so a disagreement between the grader and
    the ledger cannot be persisted. Shared by the CLI, the run orchestrator and
    the server so there is exactly ONE mapping.

    ``builder_error`` is the builder's *own* trouble (model error, budget stop,
    guard violation). It never changes the verdict — the belts are the truth
    about the worktree — so on a clean row it is recorded only as
    ``labels['builder_error']``; on a non-clean row it also fills ``error`` so
    the reason is visible where operators look first.
    """
    b = builder or BuilderRef(mode=result.mode)
    return GradeRow(
        repo=result.repo or task.repo,
        task_id=result.task_id,
        clean=result.clean,
        tests_unmodified=result.belts.tests_unmodified,
        target_green=result.belts.target_green,
        no_new_failures=result.belts.no_new_failures,
        source_changed=result.belts.source_changed,
        capability_class=task.capability_class,
        size=task.size,
        language=language or task.language,
        pool=task.pool,
        mode=result.mode,
        process_step=process_step,
        builder=b.name,
        model=b.model,
        provider=b.provider,
        run_id=run_id,
        trial=trial,
        actor=actor,
        disqualified=result.disqualified,
        dq_reason=result.dq_reason,
        error=result.error or ("" if result.clean else builder_error),
        new_failures_count=len(result.new_failures),
        attempts=b.attempts,
        cost_usd=b.cost_usd,
        tokens_in=b.tokens_in,
        tokens_out=b.tokens_out,
        latency_s=b.latency_s,
        gold_clean=task.gold_clean,
        evidence_pack_hash=pack_hash,
        belt_set=BELT_SET_V4,
        provenance="measured",
        labels={
            "rung": trial,
            **{k: str(v) for k, v in task.labels.items()},
            **({"builder_error": builder_error[:300]} if builder_error else {}),
            **dict(labels or {}),
        },
    )


# ---------------------------------------------------------------------------
# JSONL ledger (portable reference implementation)
# ---------------------------------------------------------------------------


class JsonlLedger:
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
            raise LedgerIntegrityError(f"last row in {self.path} has no row_hash")
        return row_hash

    def append(self, row: GradeRow) -> GradeRow:
        """Chain, validate and append. Returns the chained row (with hashes)."""
        row.assert_invariants()
        chained = row.chained(self._last_hash())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return chained

    def append_many(self, rows: Iterable[GradeRow]) -> list[GradeRow]:
        return [self.append(r) for r in rows]

    def rows(self) -> Iterator[GradeRow]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield GradeRow.from_dict(json.loads(line))

    def verify(self) -> int:
        """Walk the chain; return the row count; raise on any break."""
        return verify_chain(self.rows())


def verify_chain(rows: Iterable[GradeRow]) -> int:
    prev = GENESIS_HASH
    n = 0
    for row in rows:
        n += 1
        if row.prev_hash != prev:
            raise LedgerIntegrityError(f"row {n} ({row.task_id[:10]}) prev_hash mismatch")
        if not row.verify_hash():
            raise LedgerIntegrityError(f"row {n} ({row.task_id[:10]}) row_hash mismatch")
        prev = row.row_hash
    return n


# ---------------------------------------------------------------------------
# Cell statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellStats:
    cell: CellKey
    n: int  # eligible graded trials
    clean: int
    disqualified: int
    errors: int
    false_q1: int  # clean rows whose recorded belts are not all True (must be 0)
    point: float
    ci: Interval
    cost_usd_mean: float
    latency_s_mean: float
    oracle_strength_mean: float | None
    apparatus_versions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.cell.to_dict(),
            "n": self.n,
            "clean": self.clean,
            "disqualified": self.disqualified,
            "errors": self.errors,
            "false_q1": self.false_q1,
            "point": round(self.point, 4),
            "ci_low": round(self.ci.low, 4),
            "ci_high": round(self.ci.high, 4),
            "cost_usd_mean": round(self.cost_usd_mean, 6),
            "latency_s_mean": round(self.latency_s_mean, 3),
            "oracle_strength_mean": (
                None if self.oracle_strength_mean is None else round(self.oracle_strength_mean, 4)
            ),
            "apparatus_versions": list(self.apparatus_versions),
        }


def cell_stats(rows: Iterable[GradeRow]) -> CellStats:
    rs = list(rows)
    if not rs:
        raise ValueError("cell_stats needs at least one row")
    cell = rs[0].cell
    eligible = [r for r in rs if r.eligible]
    n = len(eligible)
    clean = sum(1 for r in eligible if r.clean)
    fq1 = sum(1 for r in rs if r.clean and not r.belts_all_true())
    costs = [r.cost_usd for r in eligible if r.cost_usd]
    lats = [r.latency_s for r in eligible if r.latency_s]
    strengths = [r.oracle_strength for r in eligible if r.oracle_strength is not None]
    return CellStats(
        cell=cell,
        n=n,
        clean=clean,
        disqualified=sum(1 for r in rs if r.disqualified),
        errors=sum(1 for r in rs if r.error),
        false_q1=fq1,
        point=(clean / n) if n else 0.0,
        ci=wilson_interval(clean, n),
        cost_usd_mean=mean(costs),
        latency_s_mean=mean(lats),
        oracle_strength_mean=mean(strengths) if strengths else None,
        apparatus_versions=tuple(sorted({r.apparatus_version for r in rs})),
    )


def group_by_cell(
    rows: Iterable[GradeRow], *, key_fields: Sequence[str] = CELL_FIELDS
) -> dict[tuple[str, ...], list[GradeRow]]:
    """Group rows by (a projection of) the cell key. Projections let the UI roll
    up e.g. by (class × size) across models."""
    groups: dict[tuple[str, ...], list[GradeRow]] = {}
    for r in rows:
        k = tuple(getattr(r, f) for f in key_fields)
        groups.setdefault(k, []).append(r)
    return groups


def all_cell_stats(rows: Iterable[GradeRow]) -> list[CellStats]:
    return [cell_stats(g) for g in group_by_cell(rows).values()]


def false_q1_total(rows: Iterable[GradeRow]) -> int:
    """The number everything else defends. Must be 0."""
    return sum(1 for r in rows if r.clean and not r.belts_all_true())
