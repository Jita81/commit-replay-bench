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

``belt_set`` says which belts a row's apparatus recorded and is never
re-interpreted: ``v3-legacy`` (census rows graded before belt 4 existed,
``provenance="imported:…"``) the first three; ``v4`` the first four; ``v5``
(apparatus 2.2, ADR-0011) all five, where belt 5 ``repo_lint_clean`` may be
``None`` = *not evaluated* (the repository configures no linter) — a fact the row
commits to, neither a pass nor a fail. On a ``v3-legacy`` / ``v4`` row belt 5 is
*unrecorded*: it must be ``None``, is not part of the hashed body (so every row
written before belt 5 existed still verifies byte-for-byte) and is never shown
as a belt. The invariant applies to the belts the row recorded; the capability
layer reports each belt set as its own apparatus.

**``belt_set`` must agree with the apparatus** (:func:`expected_belt_sets`): a row
may claim only the belt set its ``apparatus_version`` could have recorded. A
measured row stamped ``2.0``/``2.1`` is ``v4``; ``2.2`` and later is ``v5``;
``v3-legacy`` (and a four-belt ``v4`` stamped ``1.0-census``) exist only for rows
``provenance="imported:…"`` carrying a census stamp, and a ``v3-legacy`` row
records no ``source_changed``. Anything else — a measured ``2.2`` row claiming
``v3-legacy`` to have its ``source_changed=False`` ignored (independent review
pass 2026-09-14, finding 4) — is a :class:`LedgerIntegrityError` at construction,
so at write (``append``) and at read (``from_dict`` → ``verify_chain``) alike.

Every non-clean row also says **why** it is not clean, in one word
(:attr:`GradeRow.failure_kind`, vocabulary :data:`FAILURE_KINDS`), so a rate can
be split into "the model failed", "the model wrote working but non-conforming
code" (``lint``) and "the instrument failed" wherever it is shown — a naive clean rate over rows that include harness errors misdescribes
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

Navigation
----------
What it is:   The ledger — the append-only, hash-chained record of every graded trial
              (``GradeRow``), its portable JSONL implementation, and the per-cell statistics
              read back from it.
What it does: Constructs rows that cannot be clean with a failed belt, without an evidence
              pack, or under a belt set their apparatus could not have recorded; chains each
              row to the previous one by SHA-256 and verifies a chain; names why every
              non-clean row failed by ONE rule; reduces rows to a cell's ``n``, clean count,
              Wilson interval, failure split and false-Q1 count (which must read 0).
How:          ``grade_row_from_result`` reduces a ``GradeResult`` + pack hash to a row and
              pins its failure kind and cost-known labels → ``GradeRow.__post_init__``
              asserts the invariants → ``JsonlLedger.append`` chains on the last row's hash
              and fsyncs the line → ``verify_chain`` re-hashes every row in order →
              ``failure_split`` / ``cell_stats`` group eligible rows by ``CellKey``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md,
              docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/grade.py (the GradeResult a row reduces; the belt vocabulary),
              src/crb/core/evidence.py (pack hash, canonical JSON, sha256, timestamps),
              src/crb/store/ledger.py (the database ledger — same rows, same chain),
              src/crb/core/routing.py (consumes CellStats), src/crb/core/capability.py (the
              map built from the rows), src/crb/core/legacy.py (census import — the only
              writer of v3-legacy rows), src/crb/core/stats.py (the Wilson interval)
Tested by:    tests/test_ledger.py, tests/test_store_ledger.py, tests/test_census_gate.py,
              tests/test_run.py
Touch when:   never for a new repository; adding a belt, a failure kind, a cell-key field or a
              hashed label changes what the chain commits to — needs an ADR, an apparatus bump
              (src/crb/core/version.py), a store migration (as
              src/crb/store/migrations/versions/v0002_belt5_repo_lint_clean.py was for belt 5)
              and a docs/EVIDENCE-AND-CLAIMS.md update; a new builder stop reason must be
              mirrored in ``BUDGET_STOP_REASONS`` (tests/test_ledger.py pins the mirror).
Claims:       ``point`` is the fail-closed all-rows rate; ``model_point`` may be shown only
              next to it (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method);
              false-Q1 = 0 here is the mechanical sense only
              (docs/EVIDENCE-AND-CLAIMS.md#2-clean-semantic-q1-and-false-q1).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.evidence import BuilderRef, canonical_json, sha256_text, utc_now_iso
from crb.core.grade import (
    BELT_NAMES,
    BLAME_CONTROLS,
    CORE_BELT_NAMES,
    ENVIRONMENT_PREFIX,
    OPTIONAL_BELT_NAMES,
    FalseQ1Violation,
    GradeResult,
    MisattributionViolation,
)
from crb.core.spec import TaskSpec
from crb.core.stats import Interval, mean, wilson_interval
from crb.core.version import APPARATUS_VERSION

GRADE_SCHEMA = "crb.grade.v2"
#: Five belts (apparatus ≥ 2.2): belt 5 ``repo_lint_clean`` recorded (``None`` = not evaluated).
BELT_SET_V5 = "v5"
#: Four belts (apparatus 2.0–2.1); belt 5 unrecorded.
BELT_SET_V4 = "v4"
#: Three belts (the census); belts 4 and 5 unrecorded.
BELT_SET_V3_LEGACY = "v3-legacy"
BELT_SETS: tuple[str, ...] = (BELT_SET_V5, BELT_SET_V4, BELT_SET_V3_LEGACY)
#: The belts each set records, in belt order.
RECORDED_BELTS: dict[str, tuple[str, ...]] = {
    BELT_SET_V3_LEGACY: BELT_NAMES[:3],
    BELT_SET_V4: BELT_NAMES[:4],
    BELT_SET_V5: BELT_NAMES,
}
PROCESS_REPLAY = "replay"
PROCESS_FACTORY = "factory"

GENESIS_HASH = "0" * 64

#: ``provenance`` prefix of every row that was imported rather than measured here.
IMPORTED_PROVENANCE_PREFIX = "imported:"
#: The apparatus stamps a census import carries (``crb.core.legacy.CENSUS_APPARATUS_VERSION``
#: mirrors this — the core cannot import ``legacy``, which imports this module). Only
#: rows with one of these may claim ``v3-legacy``, or ``v4`` without a ``2.x`` stamp.
LEGACY_APPARATUS_VERSIONS: frozenset[str] = frozenset({"1.0-census"})
#: The first apparatus that recorded belt 4 / belt 5 (ADR-0001 / ADR-0011).
_FIRST_V4_APPARATUS = (2, 0)
_FIRST_V5_APPARATUS = (2, 2)
_APPARATUS_RE = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?$")


def parse_apparatus_version(version: str) -> tuple[int, int] | None:
    """``"2.2"`` → ``(2, 2)``; ``None`` for a stamp that is not ``major.minor[.patch]``
    (a census stamp, free text)."""
    m = _APPARATUS_RE.match(version.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def expected_belt_sets(apparatus_version: str, provenance: str) -> tuple[str, ...]:
    """The belt sets a row stamped ``apparatus_version`` under ``provenance`` may
    claim (empty = no belt set is consistent with that stamp; the row is refused).

    * ``imported:…`` with a census stamp → ``v3-legacy`` or ``v4`` (the census recorded
      three belts, later four);
    * any row with a ``2.x`` stamp → ``v4`` for ``2.0``–``2.1``, ``v5`` from ``2.2`` — a
      federated import keeps its source's meaning;
    * a measured row with a census stamp, or any unparsable stamp → nothing.
    """
    imported = provenance.startswith(IMPORTED_PROVENANCE_PREFIX)
    if apparatus_version in LEGACY_APPARATUS_VERSIONS:
        return (BELT_SET_V3_LEGACY, BELT_SET_V4) if imported else ()
    parsed = parse_apparatus_version(apparatus_version)
    if parsed is None or parsed < _FIRST_V4_APPARATUS:
        return ()
    return (BELT_SET_V5,) if parsed >= _FIRST_V5_APPARATUS else (BELT_SET_V4,)


# --- failure kinds -------------------------------------------------------------
#: A clean row has no failure kind.
FAILURE_CLEAN = ""
#: The MODEL failed the task: target not green, a regression, or no source change,
#: with the builder having finished on its own terms.
FAILURE_BUILDER_RED = "builder_red"
#: The model wrote WORKING but NON-CONFORMING code: belts 1–4 held and only belt 5
#: (the repository's own formatter/linter) rejected the changed files (ADR-0011).
FAILURE_LINT = "lint"
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
#: The model provider refused the CALL itself — a usage limit, a quota, a 429/5xx, a
#: dead credential: the builder never ran, so the row is not an observation of the
#: builder, the oracle or the harness. Excluded from every rate (``n``) and counted
#: separately; 237 such rows landed in one evening when the operator's Claude Code
#: quota ran out mid-campaign (2026-09-14) and read as ``harness`` — a harness that
#: worked perfectly.
FAILURE_OUTAGE = "outage"
FAILURE_KINDS: tuple[str, ...] = (
    FAILURE_CLEAN,
    FAILURE_BUILDER_RED,
    FAILURE_LINT,
    FAILURE_BUDGET,
    FAILURE_PROTOCOL,
    FAILURE_HARNESS,
    FAILURE_OUTAGE,
    FAILURE_DISQUALIFIED,
)
#: Error texts that identify a provider outage (the builders record the provider's own
#: words after ``model_error:``). Matched case-insensitively; kept narrow on purpose —
#: an unknown error stays ``harness`` (fail-closed).
OUTAGE_ERROR_MARKERS: tuple[str, ...] = (
    "hit your limit",
    "usage limit",
    "rate_limit",
    "rate limit",
    "429",
    "overloaded",
    "quota",
    "insufficient credit",
    "credit balance",
    "authentication failed",
    "oauth access token is invalid",
    "402",
    "503",
    "529",
)


def is_outage_error(error: str) -> bool:
    """``True`` when ``error`` is the provider refusing the call (see
    :data:`OUTAGE_ERROR_MARKERS`) — only for ``model_error:`` texts, so a grader
    timeout that happens to say "429" in a test log is not an outage."""
    e = error.lower()
    if not e.startswith("model_error"):
        return False
    return any(m in e for m in OUTAGE_ERROR_MARKERS)


#: The kinds where the model finished and was judged on its own terms (the
#: denominator of ``model_point`` together with clean).
MODEL_FAILURE_KINDS: tuple[str, ...] = (FAILURE_BUILDER_RED, FAILURE_LINT)
#: The kinds that are the INSTRUMENT's doing (the model never got a fair attempt).
INSTRUMENT_FAILURE_KINDS: tuple[str, ...] = (FAILURE_PROTOCOL, FAILURE_HARNESS)

#: ``crb.builders.adapter.attempt_error`` prefixes every guard refusal with this.
PROTOCOL_VIOLATION_PREFIX = "protocol violation:"
#: The longest ``trial`` a row may carry: the rung POSITION label (``r1`` … ``r16``);
#: ``grades.trial`` is ``VARCHAR(16)``, which PostgreSQL enforces at INSERT and SQLite
#: does not — refused at the row so both dialects fail the same way (CI, 2026-09-15).
TRIAL_MAX_LEN = 16
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
#: The posture labels every measured row of apparatus 2.3 or later carries (ADR-0019):
#: where it was graded, the class statistics pool on, and the qualification it subtracted.
LABEL_POSTURE_ID = "posture_id"
LABEL_POSTURE_CLASS = "posture_class"
LABEL_QUALIFICATION = "qualification_id"
POSTURE_LABELS: tuple[str, ...] = (LABEL_POSTURE_ID, LABEL_POSTURE_CLASS, LABEL_QUALIFICATION)
#: The witness that makes a model-failure row's blame true (``crb.core.grade.BLAME_CONTROLS``).
LABEL_BLAME_CONTROL = "blame_control"
#: Why an ``environment:`` row's instrument failed (``GOLD_CONTROL_RED`` …).
LABEL_ENV_CODE = "env_code"
#: The first apparatus whose measured rows must carry their posture and witness.
POSTURE_APPARATUS: tuple[int, int] = (2, 3)


class LedgerIntegrityError(RuntimeError):
    """The hash chain does not verify."""


@dataclass(frozen=True)
class CellKey:
    """The unit of measurement. Carries NO task id, NO repo, NO free text.

    Every statistic the product shows is a statement about one cell, and the cell is
    also the abstraction boundary of the federated export (ADR-0007): a key that named
    a task or a repository could not leave the tenant.
    """

    process_step: str
    capability_class: str
    size: str
    language: str
    builder: str
    model: str
    provider: str

    def to_tuple(self) -> tuple[str, ...]:
        """The key as a tuple in :data:`CELL_FIELDS` order (the grouping key)."""
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
        """The key as ``{field: value}`` — the shape exports and the API carry."""
        return dict(zip(CELL_FIELDS, self.to_tuple(), strict=True))

    @property
    def label(self) -> str:
        """The key as one ``|``-joined string, for log lines and map headings."""
        return "|".join(self.to_tuple())


#: The cell-key fields in key order. Adding one changes every cell's identity
#: (rows written before it cannot be regrouped), so it is an apparatus change.
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
    lint_only: bool = False,
) -> str:
    """THE rule that names why a row is not clean. Deterministic; first match wins.

    1. ``clean``                                            → ``""``
    2. ``disqualified``                                     → ``disqualified``
    3. ``error`` or ``builder_error`` starts with
       ``protocol violation:``                              → ``protocol``
       (the builder was refused by a guard; the belts then judge an empty patch)
    4. a ``model_error: …`` naming a provider refusal (usage
       limit, 429, quota, dead credential)                   → ``outage``
       (the call never happened: no observation of anything; excluded from ``n``)
    4b. any other non-empty ``error``                       → ``harness``
       (grader exception, sandbox, parse, timeout, setup, other ``model_error: …``,
       a linter that could not run)
    5. ``stop_reason`` in :data:`BUDGET_STOP_REASONS`       → ``budget``
       (the attempt was cut short by its own Budget; the belts judged a partial patch)
    6. ``lint_only`` — belts 1–4 all ``True`` and belt 5
       ``False``                                            → ``lint``
       (the model wrote working code the repository's own linter rejects)
    7. otherwise                                            → ``builder_red``
       (the builder finished on its own terms and the belts failed it)

    Instrument causes come before ``budget`` because an errored grade is not a
    valid observation of the patch at all; ``budget`` comes before ``lint`` and
    ``builder_red`` because a patch the model never finished is not evidence the
    model cannot finish it; ``lint`` is named only when the code otherwise works —
    a patch that fails a core belt is ``builder_red`` whatever the linter said.
    ``protocol`` outranks ``harness``: a refusal happened first and is the reason
    the row exists.
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
        return FAILURE_OUTAGE if is_outage_error(error) else FAILURE_HARNESS
    if stop_reason in BUDGET_STOP_REASONS:
        return FAILURE_BUDGET
    if lint_only:
        return FAILURE_LINT
    return FAILURE_BUILDER_RED


def is_environment_error(error: str) -> bool:
    """``True`` for an error the grader recorded because the POSTURE failed, not the patch
    (``environment: …`` — ADR-0019 §5). The failure-kind rule reads it as ``harness``
    like any other grader error; this only lets a caller name it (stop a ladder, revoke
    a qualification). It never decides a classification."""
    return error.startswith(ENVIRONMENT_PREFIX)


def lint_only_failure(belts: Mapping[str, Any]) -> bool:
    """``True`` iff belts 1–4 all held and belt 5 rejected — the ``lint`` kind's input."""
    return belts.get("repo_lint_clean") is False and all(
        belts.get(b) is True for b in CORE_BELT_NAMES
    )


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
    """Labels are ``str → str`` (hashed as such), so a boolean label is spelt out."""
    return "true" if v else "false"


@dataclass(frozen=True)
class GradeRow:
    """One graded trial as the ledger records it — the row every statistic is built from.

    Immutable once constructed; ``__post_init__`` runs :meth:`assert_invariants`, so a row
    that would be a false-Q1, that lacks its evidence pack, or whose ``belt_set``
    contradicts its ``apparatus_version`` cannot exist in memory, let alone on disk.
    ``prev_hash`` / ``row_hash`` are empty until :meth:`chained` (the ledger's ``append``
    fills them). Field order is the constructor shape ``from_dict`` relies on; the hashed
    body (:meth:`body`) is every field but ``row_hash``, minus belts the row's belt set
    does not record.
    """

    repo: str
    task_id: str
    clean: bool
    tests_unmodified: bool | None
    target_green: bool | None
    no_new_failures: bool | None
    source_changed: bool | None
    repo_lint_clean: bool | None = None
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
    belt_set: str = BELT_SET_V5
    provenance: str = "measured"
    labels: Mapping[str, str] = field(default_factory=dict)
    schema: str = GRADE_SCHEMA
    row_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        # a private copy: the caller's mapping must not be able to change a hashed body
        object.__setattr__(self, "labels", dict(self.labels))
        if not self.row_id:
            object.__setattr__(self, "row_id", uuid.uuid4().hex)
        if len(self.trial) > TRIAL_MAX_LEN:
            raise ValueError(
                f"trial longer than {TRIAL_MAX_LEN} (the rung position, r1…): {self.trial[:20]!r}…"
            )
        if self.belt_set not in BELT_SETS:
            raise ValueError(f"belt_set must be one of {BELT_SETS}")
        if self.belt_set != BELT_SET_V5 and self.repo_lint_clean is not None:
            raise ValueError(
                f"belt 5 (repo_lint_clean) is unrecorded under belt_set={self.belt_set!r}; "
                "a row from a pre-belt-5 apparatus is never re-interpreted"
            )
        self.assert_invariants()

    # --- invariants ------------------------------------------------------------
    def recorded_belts(self) -> tuple[str, ...]:
        """The belts this row's apparatus recorded (``v3-legacy`` 3, ``v4`` 4, ``v5`` 5)."""
        return RECORDED_BELTS[self.belt_set]

    def belts_all_true(self) -> bool:
        """The clean predicate over the RECORDED belts: every recorded core belt
        ``True`` and no recorded optional belt ``False`` (``None`` there = the
        repository has no linter; the row says so and may still be clean)."""
        recorded = self.recorded_belts()
        return all(getattr(self, b) is True for b in recorded if b in CORE_BELT_NAMES) and all(
            getattr(self, b) is not False for b in recorded if b not in CORE_BELT_NAMES
        )

    def lint_only(self) -> bool:
        """Belts 1–4 held and belt 5 rejected (the ``lint`` failure kind)."""
        return lint_only_failure({b: getattr(self, b) for b in self.recorded_belts()})

    def assert_invariants(self) -> None:
        """The write-time gate (ADR-0001, ADR-0002): false-Q1 = 0, no pack ⇒ no Q1, a
        pinned ``failure_kind`` that agrees with ``clean`` / ``disqualified``, a
        well-formed ``cost_known`` label, and a belt set the apparatus could record.
        Called at construction and again by the ledger before chaining."""
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
            # a clean row has the empty kind and a non-clean row a named one: a label
            # that says otherwise is a false-Q1 by another route
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
        self.assert_belt_set_matches_apparatus()
        self.assert_posture_and_witness()

    @property
    def carries_posture(self) -> bool:
        """``True`` for a measured row of apparatus 2.3 or later — the rows that must name
        their posture, and their witness when they blame the model (ADR-0019)."""
        parsed = parse_apparatus_version(self.apparatus_version)
        return self.provenance == "measured" and parsed is not None and parsed >= POSTURE_APPARATUS

    def assert_posture_and_witness(self) -> None:
        """ADR-0019 §5, at write and at read alike: a measured row of apparatus 2.3 or later
        carries its posture labels, and a row in a model-failure kind names the witness
        that makes the blame true. Rows of 2.2 and earlier are never re-interpreted."""
        if not self.carries_posture:
            return
        missing = [k for k in POSTURE_LABELS if not self.labels.get(k)]
        if missing:
            raise MisattributionViolation(
                f"ledger refuses row {self.task_id[:10]} ({self.repo}): apparatus "
                f"{self.apparatus_version} row without its posture labels {missing}"
            )
        if self.failure_kind in MODEL_FAILURE_KINDS:
            witness = self.labels.get(LABEL_BLAME_CONTROL, "")
            if witness not in BLAME_CONTROLS:
                raise MisattributionViolation(
                    f"ledger refuses row {self.task_id[:10]} ({self.repo}): failure_kind="
                    f"{self.failure_kind!r} blames the model without a witness from its posture "
                    f"(blame_control={witness or '-'!r}; expected one of {BLAME_CONTROLS})"
                )

    @property
    def posture_id(self) -> str:
        """The posture this row was graded in (``""`` before apparatus 2.3)."""
        return self.labels.get(LABEL_POSTURE_ID, "")

    @property
    def posture_class(self) -> str:
        """The posture class this row pools under (``""`` before apparatus 2.3)."""
        return self.labels.get(LABEL_POSTURE_CLASS, "")

    def assert_belt_set_matches_apparatus(self) -> None:
        """``belt_set`` is the one the row's apparatus could have recorded (module
        docstring). Refused with :class:`LedgerIntegrityError` — at construction, so
        at write and on read alike — never re-interpreted."""
        allowed = expected_belt_sets(self.apparatus_version, self.provenance)
        if self.belt_set not in allowed:
            raise LedgerIntegrityError(
                f"ledger refuses row {self.task_id[:10]} ({self.repo}): belt_set="
                f"{self.belt_set!r} is not what apparatus {self.apparatus_version!r} "
                f"(provenance {self.provenance!r}) records — expected "
                f"{' or '.join(allowed) if allowed else 'no belt set at all'}"
            )
        if self.belt_set == BELT_SET_V3_LEGACY and self.source_changed is not None:
            raise LedgerIntegrityError(
                f"ledger refuses row {self.task_id[:10]} ({self.repo}): a v3-legacy row "
                f"records no belt 4, got source_changed={self.source_changed!r}"
            )

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
            # a row pinned ``harness`` before ``outage`` existed reads as the outage it
            # was — the error text is hashed into the row, so the re-reading is honest
            if pinned == FAILURE_HARNESS and is_outage_error(self.error):
                return FAILURE_OUTAGE
            return pinned
        return derive_failure_kind(
            clean=self.clean,
            disqualified=self.disqualified,
            error=self.error,
            builder_error=self.labels.get("builder_error", ""),
            stop_reason=self.stop_reason,
            lint_only=self.lint_only(),
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
        """The cell this row is an observation of (the grouping key of every statistic)."""
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
        """Counts toward a cell's denominator: graded (not DQ) on a judgeable oracle,
        and the call actually happened (an ``outage`` row observed nothing)."""
        return (
            not self.disqualified
            and self.gold_clean is not False
            and self.failure_kind != FAILURE_OUTAGE
        )

    # --- hashing ---------------------------------------------------------------
    def fields(self) -> dict[str, Any]:
        """Every field except ``row_hash`` (``labels`` copied) — the constructor shape."""
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "row_hash"}
        d["labels"] = dict(self.labels)
        return d

    def body(self) -> dict[str, Any]:
        """The HASHED body: :meth:`fields` minus any belt added after the row schema
        froze (:data:`~crb.core.grade.OPTIONAL_BELT_NAMES`) that this row's
        ``belt_set`` does not record. A ``v4`` / ``v3-legacy`` row therefore hashes
        byte-for-byte as it did before belt 5 existed — including its ``source_changed``
        (``None`` on ``v3-legacy``), which was always in the body — so an existing
        ledger keeps verifying after the apparatus grew (ADR-0002 rule 2, amended by
        ADR-0011). A ``v5`` row hashes ``repo_lint_clean``, ``None`` included: "not
        evaluated" is a fact the chain commits to."""
        unrecorded = set(OPTIONAL_BELT_NAMES) - set(self.recorded_belts())
        return {k: v for k, v in self.fields().items() if k not in unrecorded}

    def compute_hash(self) -> str:
        """SHA-256 of the canonical JSON of :meth:`body` — includes ``prev_hash``, which
        is what makes the rows a chain rather than a list of checksums."""
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> GradeRow:
        """Return a copy with ``prev_hash`` set and ``row_hash`` computed."""
        d = self.fields()
        d["prev_hash"] = prev_hash
        row = GradeRow(**d)
        # the only place row_hash is ever set; the dataclass is frozen so it cannot drift
        object.__setattr__(row, "row_hash", row.compute_hash())
        return row

    def verify_hash(self) -> bool:
        """``True`` iff the stored ``row_hash`` is the hash of the body as read back.
        An unchained row (empty hash) never verifies."""
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    # --- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Every field + ``row_hash`` + the two derived fields (``failure_kind``,
        ``cost_known``). The derived fields are a function of the hashed body (and,
        on new rows, pinned inside its ``labels``); :meth:`from_dict` drops the
        top-level copies on read. An unrecorded belt is written as ``null`` — the
        honest value — and is simply not part of the hash."""
        d = self.fields()
        d["row_hash"] = self.row_hash
        d["failure_kind"] = self.failure_kind
        d["cost_known"] = self.cost_known
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> GradeRow:
        """Rebuild a row from its stored dict. Keys that are not constructor fields —
        the derived top-level ``failure_kind`` / ``cost_known`` that :meth:`to_dict`
        writes for readers — are dropped, never re-trusted; the invariants run again
        on the way in, so a stored row that contradicts itself is refused on read."""
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
    # the grader's own error always wins; the builder's trouble surfaces as `error`
    # only on a non-clean row (on a clean row it is a label — the belts judged the tree)
    error = result.error or ("" if result.clean else builder_error)
    stop_reason = builder_stop_reason(builder)
    kind = derive_failure_kind(
        clean=result.clean,
        disqualified=result.disqualified,
        error=error,
        builder_error=builder_error,
        stop_reason=stop_reason,
        lint_only=lint_only_failure(result.belts.to_dict()),
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
        repo_lint_clean=result.belts.repo_lint_clean,
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
        belt_set=BELT_SET_V5,
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
            **posture_labels(result),
        },
    )


def posture_labels(result: GradeResult) -> dict[str, str]:
    """The labels a result's posture stamp and witness become on its row (ADR-0019)."""
    out: dict[str, str] = {}
    if result.posture_id:
        out[LABEL_POSTURE_ID] = result.posture_id
    if result.posture_class:
        out[LABEL_POSTURE_CLASS] = result.posture_class
    if result.qualification_id:
        out[LABEL_QUALIFICATION] = result.qualification_id
    if result.blame_control:
        out[LABEL_BLAME_CONTROL] = result.blame_control
    if result.env_code:
        out[LABEL_ENV_CODE] = result.env_code
    return out


# ---------------------------------------------------------------------------
# JSONL ledger (portable reference implementation)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def jsonl_append_lock(path: Path) -> Iterator[None]:
    """An OS-level exclusive lock on ``<path>.lock`` for the read-head-then-append of a
    hash-chained JSONL file. A ``threading.Lock`` covers one interpreter; the API and the
    worker open the same factory evidence file from two processes, and two appenders that
    both read the same head write two records with the same ``prev_hash`` — a permanent
    chain break (CodeRabbit on PR #4, 2026-09-15). POSIX ``flock``; a platform without it
    gets the in-process lock only."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as fh:
        locked = False
        try:
            import fcntl  # noqa: PLC0415 — POSIX only; guarded

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass
        try:
            yield
        finally:
            if locked:
                with contextlib.suppress(OSError):
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def jsonl_last_line(path: Path) -> str:
    """The last non-blank line of a JSONL file, read from the tail. The window starts at
    64 KiB and doubles until it holds a line boundary before the last line (or the whole
    file): a last row longer than the window used to be parsed from its middle and every
    later append failed (CodeRabbit on PR #3, 2026-09-15). ``""`` for an empty file."""
    if not path.exists() or path.stat().st_size == 0:
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        step = min(size, 65536)
        f.seek(size - step)
        chunk = f.read()
        while step < size and b"\n" not in chunk.rstrip(b"\n"):
            step = min(size, step * 2)
            f.seek(size - step)
            chunk = f.read()
    for line in reversed(chunk.decode("utf-8", errors="replace").splitlines()):
        if line.strip():
            return line
    return ""


class JsonlLedger:
    """The portable ledger: one JSON object per line, appended and fsynced, chained on
    the previous line's ``row_hash``. Stdlib only, so an export can be verified anywhere
    (``crb ledger verify``); the store keeps the identical chain in a database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        """The ``row_hash`` of the last non-blank line, or :data:`GENESIS_HASH` for an
        empty or absent file (:func:`jsonl_last_line` reads only the tail)."""
        last = jsonl_last_line(self.path)
        if not last:
            return GENESIS_HASH
        row_hash = str(json.loads(last).get("row_hash", ""))
        if not row_hash:
            raise LedgerIntegrityError(f"last row in {self.path} has no row_hash")
        return row_hash

    def append(self, row: GradeRow) -> GradeRow:
        """Chain, validate and append. Returns the chained row (with hashes)."""
        row.assert_invariants()
        with jsonl_append_lock(self.path):
            chained = row.chained(self._last_hash())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())  # a row that was returned is a row that is on disk
        return chained

    def append_many(self, rows: Iterable[GradeRow]) -> list[GradeRow]:
        """Append in order; each row chains on the one before it."""
        return [self.append(r) for r in rows]

    def rows(self) -> Iterator[GradeRow]:
        """Every row in file order (each re-validated by ``from_dict``); nothing for
        an absent file."""
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
    """Prove ``rows`` is an unbroken chain from genesis: every ``prev_hash`` is the
    previous ``row_hash`` and every ``row_hash`` re-computes. Returns the row count;
    raises :class:`LedgerIntegrityError` naming the first bad row. Shared by the JSONL
    ledger, the store and ``crb ledger verify`` so there is one notion of "verifies"."""
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
    lint + budget + protocol + harness``; ``disqualified`` and ``outage`` are counted
    over all rows and sit outside ``n``. ``point`` is the all-rows rate (``clean / n``): the
    fail-closed number, where every instrument error counts against autonomy.
    ``model_point`` is ``clean / (clean + builder_red + lint)`` — how often the
    model succeeded when it got a fair, finished attempt (``lint`` is such an
    attempt: the code worked and the repository rejected it) — reported NEXT TO
    ``point``, never instead of it, with its own n (``model_n``) and Wilson
    interval. ``cost_known`` / ``cost_unknown`` split the eligible rows by
    :attr:`GradeRow.cost_known`. ``lint_evaluated`` counts the eligible rows that
    carried belt 5 at all (a ``v5`` row whose repository has a linter) — the
    number a reader needs before quoting ``lint``.
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
    lint: int = 0
    lint_evaluated: int = 0
    #: Provider outages (usage limit, 429, dead credential): the call never happened.
    #: Counted over all rows, outside ``n`` — like ``disqualified``.
    outage: int = 0

    def __post_init__(self) -> None:
        # the split must partition n exactly: a kind that is dropped or double-counted
        # would let a rate be quoted over a denominator nobody can reconstruct
        kinds = self.clean + self.builder_red + self.lint + self.budget + self.protocol
        if self.n != kinds + self.harness:
            raise ValueError("a FailureSplit's n must equal the sum of its eligible kinds")

    @property
    def point(self) -> float:
        """The fail-closed rate: clean over every eligible row."""
        return self.clean / self.n if self.n else 0.0

    @property
    def ci(self) -> Interval:
        """Wilson 95% interval of :attr:`point`."""
        return wilson_interval(self.clean, self.n)

    @property
    def model_n(self) -> int:
        """Rows where the model finished and was judged on its own terms."""
        return self.clean + self.builder_red + self.lint

    @property
    def model_point(self) -> float:
        """Clean over :attr:`model_n` — shown next to :attr:`point`, never instead."""
        return self.clean / self.model_n if self.model_n else 0.0

    @property
    def model_ci(self) -> Interval:
        """Wilson 95% interval of :attr:`model_point`."""
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
            "lint": self.lint,
            "budget": self.budget,
            "protocol": self.protocol,
            "harness": self.harness,
            "disqualified": self.disqualified,
            "outage": self.outage,
            "rows": self.rows,
            "lint_evaluated": self.lint_evaluated,
            "point": round(self.point, 4),
            "ci_low": round(self.ci.low, 4),
            "ci_high": round(self.ci.high, 4),
            "model_n": self.model_n,
            # an unmeasured rate (no fair, finished attempt) is null with its interval — never
            # a fabricated 0.0 / [0, 1] (CodeRabbit on PR #6, 2026-09-16)
            "model_point": None if self.model_n == 0 else round(self.model_point, 4),
            "model_ci_low": None if self.model_n == 0 else round(self.model_ci.low, 4),
            "model_ci_high": None if self.model_n == 0 else round(self.model_ci.high, 4),
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
        lint=kinds[FAILURE_LINT],
        lint_evaluated=sum(1 for r in eligible if r.repo_lint_clean is not None),
        outage=sum(1 for r in rs if r.failure_kind == FAILURE_OUTAGE),
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
    n_outage: int = 0  # provider outages: outside n, reported so a reader sees the gap
    #: DISTINCT tasks among the eligible rows. ``n`` counts attempts: a cell of 16 rows on
    #: 4 commits is a statement about 4 commits — the clustering EVIDENCE-AND-CLAIMS §3
    #: forbids hiding (decider pass 2, 2026-09-15). Shown next to ``n`` everywhere.
    n_tasks: int = 0
    model_n: int = 0
    model_point: float = 0.0
    model_ci: Interval = field(default_factory=lambda: Interval(0.0, 1.0))
    n_lint: int = 0
    n_lint_evaluated: int = 0
    #: The postures the cell's rows were graded in (ADR-0019 §8) — listed like the
    #: apparatus versions, so a reader sees what a number pools.
    posture_ids: tuple[str, ...] = ()

    @property
    def n_disqualified(self) -> int:
        """Alias of ``disqualified`` under the ``n_*`` naming the API and UI use."""
        return self.disqualified

    @property
    def n_instrument(self) -> int:
        """Rows the instrument, not the model, failed (``protocol`` + ``harness``)."""
        return self.n_protocol + self.n_harness

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.cell.to_dict(),
            "n": self.n,
            "n_tasks": self.n_tasks,
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
            "n_lint": self.n_lint,
            "n_budget": self.n_budget,
            "n_protocol": self.n_protocol,
            "n_harness": self.n_harness,
            "n_outage": self.n_outage,
            "n_disqualified": self.n_disqualified,
            "n_lint_evaluated": self.n_lint_evaluated,
            "model_n": self.model_n,
            "model_point": round(self.model_point, 4),
            "model_ci_low": round(self.model_ci.low, 4),
            "model_ci_high": round(self.model_ci.high, 4),
        }


def cell_stats(rows: Iterable[GradeRow]) -> CellStats:
    """Reduce the rows of ONE cell (the caller groups; the first row's key is taken as
    the cell's) to :class:`CellStats`. Pure and re-derivable from any export: the router,
    the capability map and the API all read the same numbers."""
    rs = list(rows)
    if not rs:
        raise ValueError("cell_stats needs at least one row")
    cell = rs[0].cell
    eligible = [r for r in rs if r.eligible]
    n = len(eligible)
    clean = sum(1 for r in eligible if r.clean)
    # re-checked at read time over ALL rows, not just eligible ones: the write-time
    # gate should make this 0, and a reader must be able to see that it is
    fq1 = sum(1 for r in rs if r.clean and not r.belts_all_true())
    # means over the rows that carry a value — a $0 / 0 s is "not measured" here, not
    # a free, instant trial (cost_known tells the two apart per row)
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
        posture_ids=tuple(sorted({r.posture_id for r in rs if r.posture_id})),
        n_builder_red=split.builder_red,
        n_budget=split.budget,
        n_protocol=split.protocol,
        n_harness=split.harness,
        n_outage=split.outage,
        n_tasks=len({r.task_id for r in eligible if r.task_id}),
        model_n=split.model_n,
        model_point=split.model_point,
        model_ci=split.model_ci,
        n_lint=split.lint,
        n_lint_evaluated=split.lint_evaluated,
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
    """One :class:`CellStats` per full cell key present in ``rows``."""
    return [cell_stats(g) for g in group_by_cell(rows).values()]


def false_q1_total(rows: Iterable[GradeRow]) -> int:
    """The number everything else defends. Must be 0."""
    return sum(1 for r in rows if r.clean and not r.belts_all_true())
