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

Every non-clean row also says **why** it is not clean, in one word
(:attr:`GradeRow.failure_kind`, vocabulary :data:`FAILURE_KINDS`), so a rate can
be split into "the model failed" and "the instrument failed" wherever it is
shown — a naive clean rate over rows that include harness errors misdescribes
the model, and a rate that silently drops them overclaims. The kind is derived
by ONE rule (:func:`derive_failure_kind`) from fields the row already hashes;
a non-clean row written today additionally pins it into ``labels`` — with the
builder's stop reason, the one input the rule needs that the row does not
otherwise carry — so the hash chain commits to the classification and a SQL
``GROUP BY`` can read it. A clean row needs no label (its kind is ``""`` by
definition) and is byte-identical to one written before the label existed;
rows without a label derive the kind on read from the same rule — never
guessed. :attr:`GradeRow.cost_known` likewise distinguishes a true ``$0`` (a
fixture, a metered subscription) from a cost nobody measured; its label is
written only when the builder's report contradicts what the row alone implies
(tokens metered, no price for the model).

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

# --- failure kinds -------------------------------------------------------------
#: A clean row has no failure kind.
FAILURE_CLEAN = ""
#: The MODEL failed the task: target not green, a regression, or no source change,
#: with the builder having finished on its own terms.
FAILURE_BUILDER_RED = "builder_red"
#: The builder's :class:`Budget` was exhausted (wall clock, turns, tool calls, tokens or
#: cost) before it finished — neither the model failing nor an instrument error.
FAILURE_BUDGET = "budget"
#: The builder was REFUSED by a guard (tamper / archaeology / network …): an
#: instrument decision, recorded as ``protocol violation: …``.
FAILURE_PROTOCOL = "protocol"
#: The instrument failed: executor / sandbox / parse / timeout / setup / model-API
#: error. Fail-closed — counted against autonomy, never against the model.
FAILURE_HARNESS = "harness"
#: Tamper or malformed oracle — the observation is excluded, not counted either way.
FAILURE_DISQUALIFIED = "disqualified"
FAILURE_KINDS: tuple[str, ...] = (
    FAILURE_CLEAN,
    FAILURE_BUILDER_RED,
    FAILURE_BUDGET,
    FAILURE_PROTOCOL,
    FAILURE_HARNESS,
    FAILURE_DISQUALIFIED,
)
#: The kinds that are the INSTRUMENT's doing (the model never got a fair attempt).
INSTRUMENT_FAILURE_KINDS: tuple[str, ...] = (FAILURE_PROTOCOL, FAILURE_HARNESS)

#: ``crb.builders.adapter.attempt_error`` prefixes every guard refusal with this.
PROTOCOL_VIOLATION_PREFIX = "protocol violation:"
#: The builder stop reasons that mean "the Budget ran out" — mirrors
#: ``crb.builders.base.STOP_MAX_TURNS`` … ``STOP_WALL_CLOCK`` (the core is
#: stdlib-only and cannot import them; ``tests/test_ledger.py`` pins the mirror).
BUDGET_STOP_REASONS: tuple[str, ...] = (
    "max_turns",
    "max_tool_calls",
    "max_tokens",
    "max_cost_usd",
    "wall_clock",
)
#: The marker ``BuildOutcome.builder_ref`` puts in :attr:`BuilderRef.note` when the
#: builder metered tokens but had no price for the model.
COST_UNKNOWN_MARK = "cost unknown"

#: Label keys new rows carry. They are HASHED (labels are part of the body), so the
#: chain commits to the classification; older rows lack them and derive on read.
LABEL_FAILURE_KIND = "failure_kind"
LABEL_COST_KNOWN = "cost_known"
LABEL_STOP_REASON = "stop_reason"


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


def derive_failure_kind(
    *,
    clean: bool,
    disqualified: bool,
    error: str = "",
    builder_error: str = "",
    stop_reason: str = "",
) -> str:
    """THE rule that names why a row is not clean. Deterministic; first match wins.

    1. ``clean``                                            → ``""``
    2. ``disqualified``                                     → ``disqualified``
    3. ``error`` or ``builder_error`` starts with
       ``protocol violation:``                              → ``protocol``
       (the builder was refused by a guard; the belts then judge an empty patch)
    4. any other non-empty ``error``                        → ``harness``
       (grader exception, sandbox, parse, timeout, setup, ``model_error: …``)
    5. ``stop_reason`` in :data:`BUDGET_STOP_REASONS`       → ``budget``
       (the attempt was cut short by its own Budget; the belts judged a partial patch)
    6. otherwise                                            → ``builder_red``
       (the builder finished on its own terms and the belts failed it)

    Instrument causes come before ``budget`` because an errored grade is not a
    valid observation of the patch at all; ``budget`` comes before ``builder_red``
    because a patch the model never finished is not evidence the model cannot
    finish it. ``protocol`` outranks ``harness``: a refusal happened first and is
    the reason the row exists.
    """
    if clean:
        return FAILURE_CLEAN
    if disqualified:
        return FAILURE_DISQUALIFIED
    if error.startswith(PROTOCOL_VIOLATION_PREFIX) or builder_error.startswith(
        PROTOCOL_VIOLATION_PREFIX
    ):
        return FAILURE_PROTOCOL
    if error:
        return FAILURE_HARNESS
    if stop_reason in BUDGET_STOP_REASONS:
        return FAILURE_BUDGET
    return FAILURE_BUILDER_RED


def derive_cost_known(
    *,
    cost_usd: float,
    tokens_in: int,
    tokens_out: int,
    builder_reported: bool,
    pricing_known: bool = True,
) -> bool:
    """Is ``cost_usd`` a measurement or a placeholder?

    * the builder metered tokens but had no price for the model → ``False`` (the
      tokens are known, the dollars are not);
    * any positive cost or any token count → ``True`` (a ``$0`` with tokens is a
      real zero: a subscription or a free tier, metered);
    * ``$0`` and no tokens → ``True`` only if an identified builder reported it (a
      fixture's price is a known zero); a row with no builder record reported nothing.
    """
    if not pricing_known:
        return False
    if cost_usd > 0 or tokens_in > 0 or tokens_out > 0:
        return True
    return builder_reported


def builder_stop_reason(builder: BuilderRef | None) -> str:
    """The stop reason a :class:`BuilderRef` carries (its ``note`` starts with it —
    written by ``BuildOutcome.builder_ref``), or ``""``."""
    if builder is None or not builder.note:
        return ""
    return builder.note.split(";", 1)[0].strip()


def _bool_label(v: bool) -> str:
    return "true" if v else "false"


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
        kind = self.labels.get(LABEL_FAILURE_KIND)
        if kind is not None:
            if kind not in FAILURE_KINDS:
                raise ValueError(f"failure_kind label {kind!r} not in {FAILURE_KINDS}")
            if bool(kind) == self.clean:
                raise FalseQ1Violation(
                    f"ledger refuses row {self.task_id[:10]}: failure_kind={kind!r} "
                    f"contradicts clean={self.clean}"
                )
            if self.disqualified != (kind == FAILURE_DISQUALIFIED):
                raise ValueError(
                    f"failure_kind label {kind!r} contradicts disqualified={self.disqualified}"
                )
        ck = self.labels.get(LABEL_COST_KNOWN)
        if ck is not None and ck not in ("true", "false"):
            raise ValueError(f"cost_known label must be 'true' or 'false', got {ck!r}")

    # --- derived classification --------------------------------------------------
    @property
    def stop_reason(self) -> str:
        """The builder's stop reason when the row recorded it (new rows), else ``""``."""
        return self.labels.get(LABEL_STOP_REASON, "")

    @property
    def failure_kind(self) -> str:
        """Why the row is not clean (``""`` when it is) — see :func:`derive_failure_kind`.

        The label pinned at write time is the record; a row without one (written
        before the label existed) derives the kind from its own hashed fields.
        Such a row can never read ``budget`` — its stop reason was not recorded —
        and says ``builder_red`` for it, which is what the old rule said too.
        """
        pinned = self.labels.get(LABEL_FAILURE_KIND)
        if pinned is not None:
            return pinned
        return derive_failure_kind(
            clean=self.clean,
            disqualified=self.disqualified,
            error=self.error,
            builder_error=self.labels.get("builder_error", ""),
            stop_reason=self.stop_reason,
        )

    @property
    def cost_known(self) -> bool:
        """Is ``cost_usd`` a measurement? See :func:`derive_cost_known`. The label
        pinned at write time is the record; older rows derive it from cost, tokens
        and whether a builder reported through this ledger — an imported row
        (``provenance="imported:…"``) names a builder but never reported a cost."""
        pinned = self.labels.get(LABEL_COST_KNOWN)
        if pinned is not None:
            return pinned == "true"
        return derive_cost_known(
            cost_usd=self.cost_usd,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            builder_reported=bool(self.builder) and not self.provenance.startswith("imported:"),
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
        """The hashed body + ``row_hash`` + the two derived fields (``failure_kind``,
        ``cost_known``). The derived fields are a function of the hashed body (and,
        on new rows, pinned inside its ``labels``); :meth:`from_dict` drops the
        top-level copies on read."""
        d = self.body()
        d["row_hash"] = self.row_hash
        d["failure_kind"] = self.failure_kind
        d["cost_known"] = self.cost_known
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

    The row's ``failure_kind`` (:func:`derive_failure_kind` over the result, the
    builder error and the builder's stop reason) and ``cost_known``
    (:func:`derive_cost_known` over the :class:`BuilderRef`) are pinned into
    ``labels`` here — the ONE place the classification is decided at write time —
    so the hash chain commits to them. The builder's stop reason travels as
    ``labels['stop_reason']`` so the ``budget`` kind stays re-derivable.
    """
    b = builder or BuilderRef(mode=result.mode)
    error = result.error or ("" if result.clean else builder_error)
    stop_reason = builder_stop_reason(builder)
    kind = derive_failure_kind(
        clean=result.clean,
        disqualified=result.disqualified,
        error=error,
        builder_error=builder_error,
        stop_reason=stop_reason,
    )
    cost_known = derive_cost_known(
        cost_usd=b.cost_usd,
        tokens_in=b.tokens_in,
        tokens_out=b.tokens_out,
        builder_reported=builder is not None and bool(b.name),
        pricing_known=COST_UNKNOWN_MARK not in b.note,
    )
    # What a reader of the stored row would conclude without the builder's note.
    # The label is written only when the note changes the answer (no price for the
    # model) — a label that repeats what the row already says pins nothing new.
    cost_known_default = derive_cost_known(
        cost_usd=b.cost_usd,
        tokens_in=b.tokens_in,
        tokens_out=b.tokens_out,
        builder_reported=builder is not None and bool(b.name),
    )
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
        error=error,
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
            **({LABEL_FAILURE_KIND: kind} if kind else {}),
            **(
                {LABEL_COST_KNOWN: _bool_label(cost_known)}
                if cost_known != cost_known_default
                else {}
            ),
            **({LABEL_STOP_REASON: stop_reason} if stop_reason else {}),
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
class FailureSplit:
    """Rows of one group by :attr:`GradeRow.failure_kind`, with the two rates the
    split licenses.

    ``n`` counts ELIGIBLE rows (not disqualified, oracle not known-bad) — the same
    denominator :class:`CellStats` routes on — so ``n == clean + builder_red +
    budget + protocol + harness``; ``disqualified`` is counted over all rows and
    sits outside ``n``. ``point`` is the all-rows rate (``clean / n``): the
    fail-closed number, where every instrument error counts against autonomy.
    ``model_point`` is ``clean / (clean + builder_red)`` — how often the model
    succeeded when it got a fair, finished attempt — reported NEXT TO ``point``,
    never instead of it, with its own n (``model_n``) and Wilson interval.
    ``cost_known`` / ``cost_unknown`` split the eligible rows by
    :attr:`GradeRow.cost_known`.
    """

    n: int
    clean: int
    builder_red: int
    budget: int
    protocol: int
    harness: int
    disqualified: int
    rows: int
    cost_known: int
    cost_unknown: int

    def __post_init__(self) -> None:
        if self.n != self.clean + self.builder_red + self.budget + self.protocol + self.harness:
            raise ValueError("a FailureSplit's n must equal the sum of its eligible kinds")

    @property
    def point(self) -> float:
        return self.clean / self.n if self.n else 0.0

    @property
    def ci(self) -> Interval:
        return wilson_interval(self.clean, self.n)

    @property
    def model_n(self) -> int:
        return self.clean + self.builder_red

    @property
    def model_point(self) -> float:
        return self.clean / self.model_n if self.model_n else 0.0

    @property
    def model_ci(self) -> Interval:
        return wilson_interval(self.clean, self.model_n)

    @property
    def instrument(self) -> int:
        """Rows the instrument, not the model, failed (``protocol`` + ``harness``)."""
        return self.protocol + self.harness

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "clean": self.clean,
            "builder_red": self.builder_red,
            "budget": self.budget,
            "protocol": self.protocol,
            "harness": self.harness,
            "disqualified": self.disqualified,
            "rows": self.rows,
            "point": round(self.point, 4),
            "ci_low": round(self.ci.low, 4),
            "ci_high": round(self.ci.high, 4),
            "model_n": self.model_n,
            "model_point": round(self.model_point, 4),
            "model_ci_low": round(self.model_ci.low, 4),
            "model_ci_high": round(self.model_ci.high, 4),
            "cost_known": self.cost_known,
            "cost_unknown": self.cost_unknown,
        }


def failure_split(rows: Iterable[GradeRow]) -> FailureSplit:
    """Reduce rows to a :class:`FailureSplit` (pure; any grouping, e.g. a run)."""
    rs = list(rows)
    eligible = [r for r in rs if r.eligible]
    kinds = dict.fromkeys(FAILURE_KINDS, 0)
    for r in eligible:
        kinds[r.failure_kind] += 1
    return FailureSplit(
        n=len(eligible),
        clean=kinds[FAILURE_CLEAN],
        builder_red=kinds[FAILURE_BUILDER_RED],
        budget=kinds[FAILURE_BUDGET],
        protocol=kinds[FAILURE_PROTOCOL],
        harness=kinds[FAILURE_HARNESS],
        disqualified=sum(1 for r in rs if r.disqualified),
        rows=len(rs),
        cost_known=sum(1 for r in eligible if r.cost_known),
        cost_unknown=sum(1 for r in eligible if not r.cost_known),
    )


@dataclass(frozen=True)
class CellStats:
    """One cell's numbers. ``n`` / ``clean`` / ``point`` / ``ci`` are the all-rows,
    fail-closed statistics the router consumes; the ``n_*`` split and
    ``model_point`` (with ``model_n`` and ``model_ci``) say how much of the
    shortfall was the model's — see :class:`FailureSplit`."""

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
    n_builder_red: int = 0
    n_budget: int = 0
    n_protocol: int = 0
    n_harness: int = 0
    model_n: int = 0
    model_point: float = 0.0
    model_ci: Interval = field(default_factory=lambda: Interval(0.0, 1.0))

    @property
    def n_disqualified(self) -> int:
        return self.disqualified

    @property
    def n_instrument(self) -> int:
        return self.n_protocol + self.n_harness

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
            "n_builder_red": self.n_builder_red,
            "n_budget": self.n_budget,
            "n_protocol": self.n_protocol,
            "n_harness": self.n_harness,
            "n_disqualified": self.n_disqualified,
            "model_n": self.model_n,
            "model_point": round(self.model_point, 4),
            "model_ci_low": round(self.model_ci.low, 4),
            "model_ci_high": round(self.model_ci.high, 4),
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
    split = failure_split(rs)
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
        n_builder_red=split.builder_red,
        n_budget=split.budget,
        n_protocol=split.protocol,
        n_harness=split.harness,
        model_n=split.model_n,
        model_point=split.model_point,
        model_ci=split.model_ci,
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
