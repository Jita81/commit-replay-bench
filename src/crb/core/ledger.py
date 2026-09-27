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
              Wilson interval, failure split and false-Q1 count (which must read 0); refuses
              to reduce rows of two ``checks`` arms to one cell and keeps one arm on request.
How:          ``grade_row_from_result`` reduces a ``GradeResult`` + pack hash to a row and
              pins its failure kind and cost-known labels (from apparatus 2.4 through
              ``row_labels_at_write``, the one helper the factory's row uses too: the kind on
              every row, ``lint_reason`` and ``change_id``) → ``GradeRow.__post_init__``
              asserts the invariants (a 2.4 row without its own classification is refused;
              a row below 2.4 is read by the rule frozen at 2.3) → ``JsonlLedger.append``
              chains on the last row's hash and fsyncs the line → ``verify_chain`` re-hashes
              every row in order →
              ``failure_split`` / ``cell_stats`` group eligible rows by ``CellKey``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md,
              docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0024-working-by-construction.md; ADR-0025 items 5 and 6 (stream G)
Works with:   src/crb/core/checks.py (the arm a row's ``checks`` stamp names),
              src/crb/core/grade.py (the GradeResult a row reduces; the belt vocabulary),
              src/crb/core/evidence.py (pack hash, canonical JSON, sha256, timestamps),
              src/crb/store/ledger.py (the database ledger — same rows, same chain),
              src/crb/core/routing.py (consumes CellStats), src/crb/core/capability.py (the
              map built from the rows), src/crb/core/legacy.py (census import — the only
              writer of v3-legacy rows), src/crb/core/stats.py (the Wilson interval)
Tested by:    tests/test_ledger.py, tests/test_store_ledger.py, tests/test_census_gate.py,
              tests/test_run.py, tests/test_grade_api_belt.py, tests/test_checks_pooling.py,
              tests/test_ledger_classification.py, tests/test_failure_rule_golden.py
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

from crb.core import version as _version
from crb.core.checks import ARM_OFF, ARMS, LABEL_CHECKS, arm_from_label
from crb.core.context_arm import (
    BASE_S1,
    BASE_S2,
    LABEL_CONTEXT_ARM,
    TEST_AUTHORED,
    TEST_PERSON,
    ContextArmsPooled,
    context_arm_for,
    is_arm,
    loop_on,
    parse_arm,
)
from crb.core.evidence import BuilderRef, canonical_json, sha256_text, utc_now_iso
from crb.core.grade import (
    BELT_API_STABLE,
    BELT_NAMES,
    BLAME_CONTROLS,
    CORE_BELT_NAMES,
    ENVIRONMENT_PREFIX,
    OPTIONAL_BELT_NAMES,
    FalseQ1Violation,
    GradeResult,
    MisattributionViolation,
)
from crb.core.lint import LINT_DISABLED_BY_CONFIG, LINT_NOT_REQUESTED, lint_status_violation
from crb.core.spec import TaskSpec
from crb.core.spend import is_escalated_trial
from crb.core.stats import Interval, mean, wilson_interval
from crb.core.taxonomy import (
    GLOBAL_CLASS_SET,
    LABEL_TAXONOMY,
    ClassSetsPooled,
    is_class_set_version,
)
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
#: The model wrote WORKING code that CHANGES THE PUBLIC API in a way the maintainers' own
#: commit did not: belts 1–4 held and belt 6 ``api_stable`` (opt-in, ADR-0024) failed.
FAILURE_API = "api"
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
    FAILURE_API,
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
    return _outage(error, OUTAGE_ERROR_MARKERS)


def _outage(error: str, markers: Sequence[str]) -> bool:
    e = error.lower()
    if not e.startswith("model_error"):
        return False
    return any(m in e for m in markers)


#: The outage markers as they stood at apparatus 2.3, FROZEN: the rows of 2.3 and earlier
#: are read by them and by nothing else (ADR-0025 item 6), so an edit to the live list above
#: can no longer move an old row's classification or a denominator built from it.
#: ``tests/test_failure_rule_golden.py`` pins this tuple's SHA-256.
OUTAGE_ERROR_MARKERS_V1: tuple[str, ...] = (
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


def is_outage_error_v1(error: str) -> bool:
    """:func:`is_outage_error` against the frozen :data:`OUTAGE_ERROR_MARKERS_V1`."""
    return _outage(error, OUTAGE_ERROR_MARKERS_V1)


#: The kinds where the model finished and was judged on its own terms (the
#: denominator of ``model_point`` together with clean).
MODEL_FAILURE_KINDS: tuple[str, ...] = (FAILURE_BUILDER_RED, FAILURE_LINT, FAILURE_API)
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
#: The first apparatus whose measured rows carry their own classification from write
#: (ADR-0025 items 5 and 6): ``failure_kind`` (``""`` on a clean row), ``lint_reason`` and,
#: on a replay row, ``change_id``. Rows below it are read by the rule frozen at 2.3. Nothing
#: here moves when the constant is read: the row's own stamp decides, and
#: ``crb.core.version.APPARATUS_VERSION`` decides the stamp a new row gets.
V2_APPARATUS: tuple[int, int] = (2, 4)
#: Why belt 5 holds what it holds (``crb.core.lint.LINT_STATUSES``) — hashed, from 2.4.
LABEL_LINT_REASON = "lint_reason"
#: The change a replay row observed (``crb.core.mine.change_identity``: the commit's
#: ``git patch-id --stable``, a revert's that of its original) — hashed, from 2.4, so a
#: reader counts distinct CHANGES, never two commits of one change.
LABEL_CHANGE_ID = "change_id"
#: Where the builder ran (``docker`` = the sealed container of ADR-0012, ``host``) — written
#: by the builder adapter on every attempt, kept on a row from 2.4: with the posture class it
#: says whether the row was graded in the SEALED posture a reading counts (ADR-0026 item 2).
LABEL_BUILDER_EXECUTOR = "builder_executor"
#: The builder's sealed container (``crb.builders.container.EXECUTOR_DOCKER``).
BUILDER_EXECUTOR_SEALED = "docker"
#: Belt 6 (ADR-0024) is recorded as this hashed label — ``true`` / ``false`` / ``none``
#: (switched on, not evaluated) — and is absent when the belt was switched off.
LABEL_API_STABLE = BELT_API_STABLE
#: The belt-6 findings as one compact line (``kind:unit:symbol;…``, capped).
LABEL_API_FINDINGS = "api_findings"


class LedgerIntegrityError(RuntimeError):
    """The hash chain does not verify."""


class ChecksArmsPooled(ValueError):
    """Rows graded under two ``checks`` arms reached one cell (ADR-0024): a row graded with
    the format step or belt 6 on answers a different question from one graded without, so
    a reader must choose one arm (:func:`rows_for_checks`) before it reduces a cell."""


class ApparatusPooled(ValueError):
    """Rows of two apparatus versions reached one cell (ADR-0025 item 1): evidence expires
    with the apparatus, so a reader chooses one version before it reduces a cell."""


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
    api_only: bool = False,
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
    6. ``api_only`` — belts 1–4 all ``True`` and belt 6
       ``False`` (opt-in, ADR-0024)                          → ``api``
       (the model wrote working code that changes the public API in a way the
       maintainers' own commit did not)
    7. ``lint_only`` — belts 1–4 all ``True`` and belt 5
       ``False``                                            → ``lint``
       (the model wrote working code the repository's own linter rejects)
    8. otherwise                                            → ``builder_red``
       (the builder finished on its own terms and the belts failed it)

    Instrument causes come before ``budget`` because an errored grade is not a
    valid observation of the patch at all; ``budget`` comes before ``lint`` and
    ``builder_red`` because a patch the model never finished is not evidence the
    model cannot finish it; ``lint`` is named only when the code otherwise works —
    a patch that fails a core belt is ``builder_red`` whatever the linter said.
    ``api`` outranks ``lint`` when both belts failed: a formatter fixes a lint finding
    mechanically, while an API break changes what callers compile against and needs a
    person or a repair turn — the row names the more serious reason.
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
    if api_only:
        return FAILURE_API
    if lint_only:
        return FAILURE_LINT
    return FAILURE_BUILDER_RED


def derive_failure_kind_v1(
    *,
    clean: bool,
    disqualified: bool,
    error: str = "",
    builder_error: str = "",
    stop_reason: str = "",
    lint_only: bool = False,
    api_only: bool = False,
) -> str:
    """The failure rule as it stood at apparatus 2.3, FROZEN (ADR-0025 item 6): the rule a
    row below :data:`V2_APPARATUS` without a pinned label is read by, over the frozen
    :data:`OUTAGE_ERROR_MARKERS_V1`. Never edited: a change to the rule goes in
    :func:`derive_failure_kind` with an apparatus bump, and the golden table in
    ``tests/test_failure_rule_golden.py`` holds this one to the 2.3 outputs."""
    if clean:
        return FAILURE_CLEAN
    if disqualified:
        return FAILURE_DISQUALIFIED
    if error.startswith(PROTOCOL_VIOLATION_PREFIX) or builder_error.startswith(
        PROTOCOL_VIOLATION_PREFIX
    ):
        return FAILURE_PROTOCOL
    if error:
        return FAILURE_OUTAGE if is_outage_error_v1(error) else FAILURE_HARNESS
    if stop_reason in BUDGET_STOP_REASONS:
        return FAILURE_BUDGET
    if api_only:
        return FAILURE_API
    if lint_only:
        return FAILURE_LINT
    return FAILURE_BUILDER_RED


def is_v2_apparatus(apparatus_version: str) -> bool:
    """``True`` for a stamp of :data:`V2_APPARATUS` or later — a row that carries its own
    classification from write."""
    parsed = parse_apparatus_version(apparatus_version)
    return parsed is not None and parsed >= V2_APPARATUS


def row_labels_at_write(
    result: GradeResult,
    *,
    apparatus_version: str,
    error: str,
    builder_error: str = "",
    stop_reason: str = "",
    change_id: str = "",
    pin_kind_below_v2: bool = True,
    process_step: str = PROCESS_REPLAY,
    loop: bool = False,
    context_arm: str = "",
    taxonomy: str = GLOBAL_CLASS_SET,
) -> dict[str, str]:
    """THE row-labelling helper: the classification a new row carries from write, for a
    replay row (:func:`grade_row_from_result`) and a factory row
    (``crb.factory.build.factory_row``) alike (ADR-0025 items 5 and 6).

    From :data:`V2_APPARATUS` every row pins ``failure_kind`` — ``""`` on a clean row —
    and ``lint_reason`` (the grade's ``lint_status``), and a row that observed a mined
    commit pins its ``change_id``. It also pins the **context arm** its brief carried
    (``context_arm``: the composer's statement, else ``crb.core.context_arm.context_arm_for``
    over the step, the grade's mode and whether the loop reached the brief — ADR-0026 item 1)
    and the **class-set version** its class was read under (``taxonomy``, the global
    vocabulary unless an organisation's set is named — item 9). Below it each writer keeps
    exactly what it always wrote, so a row of 2.3 hashes as it did: a replay row pins a
    non-empty kind (``pin_kind_below_v2``), a factory row pins none.
    """
    kind = derive_failure_kind(
        clean=result.clean,
        disqualified=result.disqualified,
        error=error,
        builder_error=builder_error,
        stop_reason=stop_reason,
        lint_only=lint_only_failure(result.belts.to_dict()),
        api_only=api_only_failure(
            {**result.belts.to_dict(), BELT_API_STABLE: result.belts.api_stable}
        ),
    )
    if not is_v2_apparatus(apparatus_version):
        return {LABEL_FAILURE_KIND: kind} if kind and pin_kind_below_v2 else {}
    out = {LABEL_FAILURE_KIND: kind, LABEL_LINT_REASON: result.lint_status}
    if change_id:
        out[LABEL_CHANGE_ID] = change_id
    out[LABEL_CONTEXT_ARM] = context_arm or context_arm_for(
        process_step=process_step, mode=result.mode, loop=loop
    )
    out[LABEL_TAXONOMY] = taxonomy
    return out


def context_arm_of_factory_author(test_author: str, canonical: str = "") -> str:
    """The ``test_source`` / ``test_author`` pair a factory row's arm is decided from:
    ``operator:<name>`` is a person's failing test (``S2``); a rung label ``name:model`` is an
    authored one, named by ``canonical`` (the caller's ``canonical_model`` of the model).
    Returns the arm id (ADR-0026 item 1) with no loop modifier — the caller adds ``+L``."""
    author = (test_author or "").strip()
    if author.startswith("operator:"):
        return context_arm_for(
            process_step=PROCESS_FACTORY, mode="sighted", test_source=TEST_PERSON
        )
    model = canonical or (author.split(":", 1)[1] if ":" in author else author)
    return context_arm_for(
        process_step=PROCESS_FACTORY,
        mode="sighted",
        test_source=TEST_AUTHORED,
        test_author=model,
    )


def is_sealed_class(posture_class: str) -> bool:
    """A posture class whose tests run in the docker sandbox's sealed mode (ADR-0019 §8,
    ADR-0023): ``docker/<tree>/sealed``."""
    return posture_class.startswith("docker/") and posture_class.endswith("/sealed")


#: The labels only apparatus 2.4 defines (DL-106 (2)): a row below 2.4 never carries one,
#: whichever writer built it — refused by the row itself, at write and on read (P-127). A
#: writer that is handed one for an older apparatus writes the row as a 2.3 row always was.
V2_ONLY_LABELS: frozenset[str] = frozenset(
    {LABEL_LINT_REASON, LABEL_CHANGE_ID, LABEL_CONTEXT_ARM, LABEL_TAXONOMY}
)
#: The labels a replay row KEEPS only from 2.4: the helper's (:data:`V2_ONLY_LABELS`) and
#: the builder executor the adapter writes on every attempt, which a row below 2.4 drops.
V2_KEPT_LABELS: frozenset[str] = V2_ONLY_LABELS | {LABEL_BUILDER_EXECUTOR}


def is_environment_error(error: str) -> bool:
    """``True`` for an error the grader recorded because the POSTURE failed, not the patch
    (``environment: …`` — ADR-0019 §5). The failure-kind rule reads it as ``harness``
    like any other grader error; this only lets a caller name it (stop a ladder, revoke
    a qualification). It never decides a classification."""
    return error.startswith(ENVIRONMENT_PREFIX)


def api_only_failure(belts: Mapping[str, Any]) -> bool:
    """``True`` iff belts 1–4 all held and belt 6 rejected — the ``api`` kind's input.
    ``belts[BELT_API_STABLE]`` may be a bool (a grade) or the row label's string."""
    value = belts.get(BELT_API_STABLE)
    return (value is False or value == "false") and all(
        belts.get(b) is True for b in CORE_BELT_NAMES
    )


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

    def api_only(self) -> bool:
        """Belts 1–4 held and belt 6 — recorded as the ``api_stable`` label — rejected
        (the ``api`` failure kind)."""
        belts: dict[str, Any] = {b: getattr(self, b) for b in self.recorded_belts()}
        belts[BELT_API_STABLE] = self.labels.get(LABEL_API_STABLE)
        return api_only_failure(belts)

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
            # belt 6 lives in a label (ADR-0024): a clean row that records it failed is a
            # false-Q1 by the one route the column checks above cannot see
            if self.labels.get(LABEL_API_STABLE) == "false":
                raise FalseQ1Violation(
                    f"ledger refuses clean row {self.task_id[:10]}: belt 6 api_stable=false"
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
        self.assert_own_classification()

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
    def carries_classification(self) -> bool:
        """``True`` for a measured row of :data:`V2_APPARATUS` or later — the rows that
        carry their own classification from write (ADR-0025 items 5 and 6)."""
        return self.provenance == "measured" and is_v2_apparatus(self.apparatus_version)

    def assert_own_classification(self) -> None:
        """ADR-0025 items 5 and 6, at write and at read alike: a measured row of 2.4 or later
        pins its ``failure_kind`` and a ``lint_reason`` that agrees with belt 5, and a
        replay row names the change it observed and was gold-checked clean. Rows below 2.4
        are never re-interpreted, and never carry a label only 2.4 defines
        (:data:`V2_ONLY_LABELS`, P-127)."""
        if not is_v2_apparatus(self.apparatus_version):
            leaked = [k for k in V2_ONLY_LABELS if k in self.labels]
            if leaked:
                raise LedgerIntegrityError(
                    f"ledger refuses row {self.task_id[:10]} ({self.repo}) of "
                    f"{self.apparatus_version}: {leaked} are labels of apparatus 2.4, which no "
                    "row below 2.4 carries (DL-106 (2))"
                )
        if not self.carries_classification:
            return
        where = f"ledger refuses row {self.task_id[:10]} ({self.repo}) of {self.apparatus_version}"
        if LABEL_FAILURE_KIND not in self.labels:
            raise LedgerIntegrityError(f"{where}: no failure_kind label (stamped at write)")
        reason = self.labels.get(LABEL_LINT_REASON)
        if reason is None:
            raise LedgerIntegrityError(f"{where}: no lint_reason label (stamped at write)")
        if reason == LINT_NOT_REQUESTED:
            raise LedgerIntegrityError(
                f"{where}: lint_reason 'not_requested' — a grade that skipped belt 5 writes no row"
            )
        why = lint_status_violation(reason, self.repo_lint_clean, clean=self.clean)
        if why:
            raise LedgerIntegrityError(f"{where}: {why}")
        arm = self.labels.get(LABEL_CONTEXT_ARM, "")
        if not is_arm(arm):
            raise LedgerIntegrityError(
                f"{where}: context_arm {arm!r} is missing or outside the grammar (ADR-0026 "
                "item 1; stamped at write through context_arm_for)"
            )
        base = parse_arm(arm).base
        if (self.process_step == PROCESS_REPLAY and base == BASE_S2) or (
            self.process_step == PROCESS_FACTORY and base not in (BASE_S1, BASE_S2)
        ):
            raise LedgerIntegrityError(
                f"{where}: context arm {arm!r} on a {self.process_step} row — S2 is a factory "
                "arm only, and a factory row's arm is S1@<author> or S2"
            )
        taxonomy = self.labels.get(LABEL_TAXONOMY, "")
        if not is_class_set_version(taxonomy):
            raise LedgerIntegrityError(
                f"{where}: taxonomy {taxonomy!r} is missing or not a class-set version "
                f"(ADR-0026 item 9; the global vocabulary is {GLOBAL_CLASS_SET!r})"
            )
        if self.process_step == PROCESS_REPLAY:
            if self.gold_clean is not True:
                raise LedgerIntegrityError(
                    f"{where}: a replay row must be gold-checked clean (gold_clean="
                    f"{self.gold_clean!r}); qualify the task in this posture first"
                )
            if not self.labels.get(LABEL_CHANGE_ID):
                raise LedgerIntegrityError(
                    f"{where}: a replay row names the change it observed (change_id)"
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
    def checks_arm(self) -> str:
        """The arm this row pools in (ADR-0024): read from its hashed ``checks`` stamp and
        belt 6's own label — ``off`` for a row graded with neither grader-side switch on,
        which is every row written before the switchboard."""
        return arm_from_label(
            self.labels.get(LABEL_CHECKS, ""),
            belt6_recorded=LABEL_API_STABLE in self.labels,
        )

    @property
    def stop_reason(self) -> str:
        """The builder's stop reason when the row recorded it (new rows), else ``""``."""
        return self.labels.get(LABEL_STOP_REASON, "")

    @property
    def lint_reason(self) -> str:
        """Why belt 5 holds what it holds (``crb.core.lint.LINT_STATUSES``) — pinned on every
        measured row of apparatus 2.4 or later; ``""`` on an older row (never re-derived).
        What routing.v2 reads to leave a row graded with belt 5 switched off out of a cell's
        count (``disabled_by_config``)."""
        return self.labels.get(LABEL_LINT_REASON, "")

    @property
    def change_id(self) -> str:
        """The change this row observed (``crb.core.mine.change_identity``) — pinned on every
        measured replay row of apparatus 2.4 or later; ``""`` when the row does not carry
        it. A reader that counts distinct commits counts distinct values of this."""
        return self.labels.get(LABEL_CHANGE_ID, "")

    @property
    def context_arm(self) -> str:
        """The context arm the row's brief carried (``labels.context_arm``, ADR-0026 item 1) —
        pinned on every measured row of apparatus 2.4 or later; ``""`` on an older row, which
        is never re-derived."""
        return self.labels.get(LABEL_CONTEXT_ARM, "")

    @property
    def taxonomy(self) -> str:
        """The class-set version the row's class was read under (``labels.taxonomy``,
        ADR-0026 item 9); ``""`` on a row from before 2.4."""
        return self.labels.get(LABEL_TAXONOMY, "")

    @property
    def builder_executor(self) -> str:
        """Where the builder ran (``docker`` = its sealed container), when the row kept it."""
        return self.labels.get(LABEL_BUILDER_EXECUTOR, "")

    @property
    def sealed(self) -> bool:
        """Graded in the SEALED posture (ADR-0026 item 2; ADR-0025 as amended): the tests in
        the docker sandbox's sealed mode (a ``docker/<tree>/sealed`` posture class, ADR-0019)
        and the builder in its sealed container (ADR-0012). A row that does not record where
        its builder ran is not sealed — fail closed."""
        return is_sealed_class(self.posture_class) and (
            self.builder_executor == BUILDER_EXECUTOR_SEALED
        )

    @property
    def failure_kind(self) -> str:
        """Why the row is not clean (``""`` when it is) — see :func:`derive_failure_kind`.

        From apparatus 2.4 the label pinned at write IS the kind, read verbatim (a measured
        row cannot exist without it; an imported one without it derives by the live rule).
        Below 2.4 the rule frozen at 2.3 reads the row (:func:`derive_failure_kind_v1`):
        the pinned label, re-read as ``outage`` only against the frozen
        :data:`OUTAGE_ERROR_MARKERS_V1`; a row without one derives its kind from its own
        hashed fields, can never read ``budget`` (its stop reason was not recorded) and
        says ``builder_red`` for it, which is what the old rule said too.
        """
        pinned = self.labels.get(LABEL_FAILURE_KIND)
        v2 = is_v2_apparatus(self.apparatus_version)
        if pinned is not None:
            # below 2.4, a row pinned ``harness`` before ``outage`` existed reads as the
            # outage it was — the error text is hashed into the row and the markers frozen
            if not v2 and pinned == FAILURE_HARNESS and is_outage_error_v1(self.error):
                return FAILURE_OUTAGE
            return pinned
        rule = derive_failure_kind if v2 else derive_failure_kind_v1
        return rule(
            clean=self.clean,
            disqualified=self.disqualified,
            error=self.error,
            builder_error=self.labels.get("builder_error", ""),
            stop_reason=self.stop_reason,
            lint_only=self.lint_only(),
            api_only=self.api_only(),
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
    apparatus_version: str = "",
    context_arm: str = "",
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
    ``labels['stop_reason']`` so the ``budget`` kind stays re-derivable. From apparatus 2.4
    the labels come from :func:`row_labels_at_write` (the kind on every row, belt 5's
    reason and the task's ``change_id``, the context arm and the class-set version);
    ``apparatus_version`` is the stamp, read from ``crb.core.version`` at call time when not
    given. ``context_arm`` is the brief composer's statement of the arm it built (a
    ``context_arm`` label among ``labels`` says the same); without either the arm is decided
    from the mode and whether the run's loop reached the brief (the ``learn`` label).
    """
    b = builder or BuilderRef(mode=result.mode)
    apparatus = apparatus_version or _version.APPARATUS_VERSION
    # the grader's own error always wins; the builder's trouble surfaces as `error`
    # only on a non-clean row (on a clean row it is a label — the belts judged the tree)
    error = result.error or ("" if result.clean else builder_error)
    stop_reason = builder_stop_reason(builder)
    given = dict(labels or {})
    written = row_labels_at_write(
        result,
        apparatus_version=apparatus,
        error=error,
        builder_error=builder_error,
        stop_reason=stop_reason,
        change_id=str(task.labels.get(LABEL_CHANGE_ID, "")),
        process_step=process_step,
        loop=loop_on(given),
        context_arm=context_arm or str(given.get(LABEL_CONTEXT_ARM, "")),
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
        apparatus_version=apparatus,
        belt_set=BELT_SET_V5,
        provenance="measured",
        labels={
            "rung": trial,
            # the change identity is a 2.4 label (DL-106 (2)): a mined task carries it at
            # any apparatus, but a row below 2.4 is written as a 2.3 row always was — as
            # are the builder executor, the context arm and the class-set version
            **{
                k: str(v)
                for k, v in task.labels.items()
                if k not in V2_KEPT_LABELS or is_v2_apparatus(apparatus)
            },
            **({"builder_error": builder_error[:300]} if builder_error else {}),
            **{
                k: v
                for k, v in given.items()
                if k not in V2_KEPT_LABELS or is_v2_apparatus(apparatus)
            },
            **written,
            **(
                {LABEL_COST_KNOWN: _bool_label(cost_known)}
                if cost_known != cost_known_default
                else {}
            ),
            **({LABEL_STOP_REASON: stop_reason} if stop_reason else {}),
            **posture_labels(result),
            **_api_labels(result),
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


def _api_labels(result: GradeResult) -> dict[str, str]:
    """Belt 6's hashed labels — only when the belt was switched on for the grade."""
    run = result.api_run
    if run is None:
        return {}
    out = {LABEL_API_STABLE: run.label}
    if run.findings:
        out[LABEL_API_FINDINGS] = run.summary()
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
    #: Belt 6 (opt-in, ADR-0024): working code that changed the public API unlike the gold.
    api: int = 0
    #: Provider outages (usage limit, 429, dead credential): the call never happened.
    #: Counted over all rows, outside ``n`` — like ``disqualified``.
    outage: int = 0

    def __post_init__(self) -> None:
        # the split must partition n exactly: a kind that is dropped or double-counted
        # would let a rate be quoted over a denominator nobody can reconstruct
        kinds = self.clean + self.builder_red + self.lint + self.api + self.budget + self.protocol
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
        return self.clean + self.builder_red + self.lint + self.api

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
            "api": self.api,
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
        api=kinds[FAILURE_API],
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
    #: The posture classes those rows pool under (ADR-0019 §8) — one for a map read in one
    #: class; what a sign-off stamps and must match to lift the cell (``crb.signoff.v4``).
    posture_classes: tuple[str, ...] = ()
    #: belt 6 (opt-in, ADR-0024): working code that changed the public API unlike the gold
    n_api: int = 0
    #: The ``checks`` arm every row of the cell was graded under (ADR-0024) — one, always.
    checks_arm: str = ARM_OFF
    #: Eligible rows whose cost is KNOWN (``GradeRow.cost_known``) — the denominator of
    #: ``cost_usd_mean``. ``0`` means the mean is unknown, never ``$0``: a reader decides
    #: known-ness from this count, never by comparing the mean with zero (P-064).
    n_cost_known: int = 0
    # --- routing.v2 (ADR-0025 items 1 and 2 as ADR-0026 amends them) -------------------
    #: The one apparatus, context arm and class-set version every row of the cell carries
    #: (``""`` for a row from before the stamp) — a cell never pools two of any.
    apparatus_version: str = ""
    context_arm: str = ""
    taxonomy: str = ""
    #: Distinct tasks among the eligible rows (the pre-2.4 meaning of ``n_tasks``).
    n_tasks_eligible: int = 0
    #: The ROUTING tasks: distinct changes, each counted once by its first observed attempt
    #: (:func:`first_attempts`), gold-checked and graded with belt 5 not switched off.
    task_clean: int = 0
    task_ci: Interval = field(default_factory=lambda: Interval(0.0, 1.0))
    n_tasks_gold_unchecked: int = 0
    n_tasks_lint_disabled: int = 0
    #: Routing tasks whose first observed attempt was graded in the sealed posture.
    n_tasks_sealed: int = 0
    #: Eligible rows NOT graded in the sealed posture (``GradeRow.sealed``): a replayed arm's
    #: cell holding any routes ``calibrate`` (``posture_unsealed``) — ADR-0025 as amended.
    n_unsealed: int = 0

    @property
    def task_point(self) -> float:
        """``task_clean / n_tasks`` — ``0.0`` for no routing task."""
        return self.task_clean / self.n_tasks if self.n_tasks else 0.0

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
            "n_api": self.n_api,
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
            "checks_arm": self.checks_arm,
            "apparatus_version": self.apparatus_version,
            "context_arm": self.context_arm,
            "taxonomy": self.taxonomy,
            "n_tasks_eligible": self.n_tasks_eligible,
            "task_clean": self.task_clean,
            "task_point": round(self.task_point, 4),
            "task_ci_low": round(self.task_ci.low, 4),
            "task_ci_high": round(self.task_ci.high, 4),
            "n_tasks_gold_unchecked": self.n_tasks_gold_unchecked,
            "n_tasks_lint_disabled": self.n_tasks_lint_disabled,
            "n_tasks_sealed": self.n_tasks_sealed,
            "n_unsealed": self.n_unsealed,
        }


#: The hashed label a factory row carries when its first attempt was graded on held-out
#: acceptance tests the builder never saw (ADR-0026 item 8) — the only factory row that routes,
#: and only for arm ``S2`` (ADR-0026 item 6, amending ADR-0025 item 2).
LABEL_HELD_OUT = "held_out_acceptance"


@dataclass(frozen=True)
class FirstAttempt:
    """One distinct change of a cell, read by its first observed attempt (ADR-0025 item 2)."""

    change: str
    row: GradeRow
    #: ``False`` when every non-escalated eligible row of the change was ``harness``: the
    #: first of them stands, as a failed task, until an attempt observes the builder.
    observed: bool = True

    @property
    def task_id(self) -> str:
        return self.row.task_id

    @property
    def clean(self) -> bool:
        return self.observed and self.row.clean

    @property
    def gold_checked(self) -> bool:
        """A replay row whose gold was checked clean, or a factory ``S2`` row graded on
        held-out acceptance tests. Every other factory row is graded on a test a model
        wrote: the factory never licenses itself."""
        if self.row.process_step == PROCESS_FACTORY:
            return (
                is_arm(self.row.context_arm)
                and parse_arm(self.row.context_arm).base == BASE_S2
                and self.row.labels.get(LABEL_HELD_OUT) == "true"
            )
        return self.row.gold_clean is True

    @property
    def lint_disabled(self) -> bool:
        return self.row.lint_reason == LINT_DISABLED_BY_CONFIG

    @property
    def routes(self) -> bool:
        """Counts toward the bar: gold-checked and graded with belt 5 not switched off."""
        return self.gold_checked and not self.lint_disabled


def change_of(row: GradeRow) -> str:
    """The distinct unit a row observed: its ``change_id`` (two cherry-picks of one change,
    or a revert and its original, share one), else its task id."""
    return row.change_id or row.task_id


def first_attempts(rows: Iterable[GradeRow]) -> list[FirstAttempt]:
    """Each distinct change's first observed attempt, in LEDGER order (ADR-0025 item 2): the
    first row that is eligible, is not an escalation rung (:func:`is_escalated_trial`) and
    observed the builder (its failure kind is not ``harness``). A change whose every such row
    is ``harness`` counts, by its first, as not clean. Distinct means distinct change
    (:func:`change_of`), never distinct commit id. Order: first seen."""
    observed: dict[str, FirstAttempt] = {}
    harness: dict[str, GradeRow] = {}
    order: dict[str, None] = {}
    for r in rows:
        if not r.eligible or is_escalated_trial(r.trial):
            continue
        ch = change_of(r)
        if ch in observed:
            continue
        order.setdefault(ch, None)
        if r.failure_kind == FAILURE_HARNESS:
            harness.setdefault(ch, r)
            continue
        observed[ch] = FirstAttempt(ch, r)
    return [observed.get(ch) or FirstAttempt(ch, harness[ch], observed=False) for ch in order]


def _one(rows: Sequence[GradeRow], attr: str, what: str, exc: type[ValueError]) -> str:
    values = sorted({getattr(r, attr) for r in rows})
    if len(values) > 1:
        raise exc(
            f"one cell holds rows of {len(values)} {what}s ({', '.join(v or '-' for v in values)}): "
            f"a reading has one {what} — choose one before reducing a cell"
        )
    return str(values[0])


def cell_stats(rows: Iterable[GradeRow]) -> CellStats:
    """Reduce the rows of ONE cell (the caller groups; the first row's key is taken as
    the cell's) to :class:`CellStats`. Pure and re-derivable from any export: the router,
    the capability map and the API all read the same numbers."""
    rs = list(rows)
    if not rs:
        raise ValueError("cell_stats needs at least one row")
    arms = sorted({r.checks_arm for r in rs}, key=ARMS.index)
    if len(arms) > 1:
        raise ChecksArmsPooled(
            f"one cell holds rows graded under the checks arms {', '.join(arms)}: a row graded "
            "with the format step or belt 6 on is a different measurement from one graded "
            "without (ADR-0024) — choose one arm with rows_for_checks before reducing a cell"
        )
    # ADR-0025 item 1 and ADR-0026 items 1 and 9: one apparatus, one context arm and one
    # class-set version per reading, refused like two checks arms (ADR-0024)
    apparatus = _one(rs, "apparatus_version", "apparatus version", ApparatusPooled)
    arm = _one(rs, "context_arm", "context arm", ContextArmsPooled)
    taxonomy = _one(rs, "taxonomy", "class-set version", ClassSetsPooled)
    cell = rs[0].cell
    eligible = [r for r in rs if r.eligible]
    firsts = first_attempts(rs)
    routing = [a for a in firsts if a.routes]
    task_clean = sum(1 for a in routing if a.clean)
    n = len(eligible)
    clean = sum(1 for r in eligible if r.clean)
    # re-checked at read time over ALL rows, not just eligible ones: the write-time
    # gate should make this 0, and a reader must be able to see that it is
    fq1 = sum(1 for r in rs if r.clean and not r.belts_all_true())
    # means over the rows that carry a value: a cost is a row fact (``cost_known`` — a
    # known $0 counts as $0, an unknown cost is left out, never read as $0); a 0 s
    # latency is "not recorded", never an instant trial (crb.core.economics, F35)
    costs = [r.cost_usd for r in eligible if r.cost_known]
    lats = [r.latency_s for r in eligible if r.latency_s > 0]
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
        posture_classes=tuple(sorted({r.posture_class for r in rs if r.posture_class})),
        n_builder_red=split.builder_red,
        n_budget=split.budget,
        n_protocol=split.protocol,
        n_harness=split.harness,
        n_outage=split.outage,
        n_tasks=len(routing),
        n_tasks_eligible=len({r.task_id for r in eligible if r.task_id}),
        task_clean=task_clean,
        task_ci=wilson_interval(task_clean, len(routing)),
        n_tasks_gold_unchecked=sum(1 for a in firsts if not a.gold_checked),
        n_tasks_lint_disabled=sum(1 for a in firsts if a.gold_checked and a.lint_disabled),
        n_tasks_sealed=sum(1 for a in routing if a.row.sealed),
        n_unsealed=sum(1 for r in eligible if not r.sealed),
        apparatus_version=apparatus,
        context_arm=arm,
        taxonomy=taxonomy,
        model_n=split.model_n,
        model_point=split.model_point,
        model_ci=split.model_ci,
        n_lint=split.lint,
        n_lint_evaluated=split.lint_evaluated,
        n_api=split.api,
        checks_arm=arms[0],
        n_cost_known=len(costs),
    )


def rows_for_checks(rows: Iterable[GradeRow], arm: str) -> list[GradeRow]:
    """The rows graded under one ``checks`` arm (ADR-0024) — the read filter every reader
    that reduces cells applies, as it applies the mode and the apparatus version. There is
    no pooled view: ``arm`` is one of :data:`crb.core.checks.ARMS`."""
    if arm not in ARMS:
        raise ValueError(f"unknown checks arm {arm!r}; expected one of {ARMS}")
    return [r for r in rows if r.checks_arm == arm]


#: The arm a reader that names none reads (``S3``: the arm every sighted replay row of 2.4
#: carries — the commit's own tests). The capability map reads each cell's own standard.
DEFAULT_READ_ARM = "S3"


def rows_for_reading(
    rows: Iterable[GradeRow],
    *,
    apparatus: str,
    arm: str = DEFAULT_READ_ARM,
    taxonomy: str = GLOBAL_CLASS_SET,
) -> list[GradeRow]:
    """The rows ONE reading may reduce (ADR-0025 item 1, ADR-0026 items 1 and 9): one
    apparatus; from 2.4 also one context arm and one class-set version. A row below 2.4
    carries neither stamp and is kept at its own apparatus (the reader splits it by mode, as
    it always did). Use before ``cell_stats`` / ``build_capability_map`` over mixed rows."""
    out: list[GradeRow] = []
    for r in rows:
        if r.apparatus_version != apparatus:
            continue
        stamped = bool(r.context_arm or r.taxonomy)
        if stamped and (r.context_arm != arm or r.taxonomy != taxonomy):
            continue
        out.append(r)
    return out


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


def reading_key(row: GradeRow) -> tuple[str, str, str, str]:
    """What one reading of a cell never pools: the checks arm (ADR-0024), the apparatus
    (ADR-0025), the context arm and the class-set version (ADR-0026)."""
    return (row.checks_arm, row.apparatus_version, row.context_arm, row.taxonomy)


def all_cell_stats(rows: Iterable[GradeRow]) -> list[CellStats]:
    """One :class:`CellStats` per full cell key, ``checks`` arm, apparatus, context arm and
    class-set version present in ``rows`` — two of any of those are two cells, never one."""
    rs = list(rows)
    out: list[CellStats] = []
    for arm in ARMS:
        groups: dict[tuple[str, ...], list[GradeRow]] = {}
        for r in rows_for_checks(rs, arm):
            groups.setdefault((*reading_key(r), *r.cell.to_tuple()), []).append(r)
        out.extend(cell_stats(g) for g in groups.values())
    return out


def false_q1_total(rows: Iterable[GradeRow]) -> int:
    """The number everything else defends. Must be 0."""
    return sum(1 for r in rows if r.clean and not r.belts_all_true())
