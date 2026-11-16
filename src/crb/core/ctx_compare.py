"""The paired context-set reader — one run against another over one set's tasks (ADR-0050).

:func:`ctx_pair` pairs two runs of one context set task by task: the ``control`` side (a
plain ``A0`` control run of the set, or an entries run the treatment is linked to) and the
``treatment`` side (an entries run of the set, or of its placebo). Each side is read by its
first attempts (:func:`crb.core.ledger.first_attempts`, the rule every reader uses) and paired
by task id over the set's tasks in set order (the set holds one task per change, so this is
pairing by change). It reports ``b`` (clean under the treatment alone), ``c`` (clean under the
control alone), the exact two-sided McNemar ``p`` (:func:`crb.core.reading.mcnemar_p`), each
side's ``k``/``n`` with its Wilson interval, the delivered dose (entries and characters, from
the rows' ``ctx_delivered`` and ``ctx_chars``) with ``dose_imbalance``, and the same counts per
``ctx_gap`` stratum (descriptive only).

**Fail closed** (NEW-1, as :func:`crb.core.reading.loop_pair`): a task with no first attempt
on a side counts clean under the control and a miss under the treatment and is named in
``pending``; the pair is ``complete`` only when ``pending`` is empty, and an incomplete pair
supports no claim. **Refusals**, each raised as :class:`CtxPairRefused` with its reason:
``ctx_pair_mixed_arm`` (a side holds more than one arm), ``ctx_pair_unlinked`` (the treatment
is not a context-set arm of a known set, or the control's ``ctx_set`` is neither the
treatment set's digest nor, for a placebo, its ``matched_to``), ``ctx_pair_blend`` (the sides
differ in, or a side holds more than one of, apparatus, posture class, builder executor,
checks arm, builder, model, taxonomy or mode), ``ctx_pair_unsealed`` (a row whose builder did
not run in the sealed container) and ``ctx_gap_mismatch`` (the sides disagree on a task's
``ctx_gap`` or mix gap rules). A hindsight treatment (``ctx.oracle*``) is a ``ceiling`` and
every rendering leads with :data:`CEILING_BANNER`.

**Stated requirements** (``ctx.req*``, ADR-0052): the rendering leads with
:data:`STATED_BANNER` and a provenance line (the treatment's ``ctx_prov`` counts), strata by
whether an entry holds a ``tests_only`` item, and the control may be an entries run of
another stated set with the same items digest, repo and tasks (a structure contrast, read
``head_to_head``); against any other set it is ``ctx_pair_items_mismatch``. Every pair also
reports a per-side cost block (``cost_usd``, tokens, ``ctx_turns``), the paired cost
difference (median and IQR), each side's ``created`` window and a descriptive ``drift`` flag.

Navigation
----------
What it is:   The one reader of context-set arms: ``ctx_pair`` → ``CtxPair`` (``to_dict``),
              its refusals (``CtxPairRefused``, ``REASONS``) and ``CEILING_BANNER``.
What it does: Pairs two runs' first attempts over a set's tasks, failing closed on pending
              tasks; computes b, c, the exact McNemar p, per-side Wilson intervals, the
              delivered dose and its imbalance, and per-gap strata; refuses blends, unlinked
              or unsealed runs and gap disagreements. Never writes, never calls a model.
How:          Pure functions over ``GradeRow`` values and parsed ``CtxSet`` values the caller
              passes in (it reads no store).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md, docs/adr/0052-stated-requirement-arms.md,
              docs/adr/0025-routing-v2.md (first attempts)
Works with:   src/crb/core/ctxset.py (the set record), src/crb/core/ledger.py
              (``first_attempts``), src/crb/core/reading.py (``mcnemar_p``),
              src/crb/core/stats.py (``wilson_interval``), src/crb/server/routes/ctxsets.py
              (``GET /ctxsets/compare``), src/crb/cli/commands/ctxset.py
              (``crb ctxset compare``, which prints this reading)
Tested by:    tests/test_ctx_compare.py, tests/test_ctx_compare_stated.py
Touch when:   never for a new repository; a pooling key every reader refuses to blend is
              added (it joins ``BLEND_FIELDS``), or ADR-0050's comparison changes.
Claims:       ``clean`` is mechanical; a hindsight treatment is a CEILING — a brief that may
              restate the answer, never a builder capability; ``ctx_gap`` is descriptive and
              no stratum is a primary test (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from crb.core import stated as _stated
from crb.core.context_arm import (
    BASE_A0,
    CTX_SOURCE_CONTROL,
    LABEL_CTX_CHARS,
    LABEL_CTX_DELIVERED,
    LABEL_CTX_GAP,
    LABEL_CTX_GAP_RULE,
    LABEL_CTX_PROV,
    LABEL_CTX_SET,
    LABEL_CTX_SOURCE,
    LABEL_CTX_TURNS,
    ctx_set_name,
    hindsight_arm,
    stated_arm,
)
from crb.core.ctxset import CtxSet
from crb.core.ledger import BUILDER_EXECUTOR_SEALED, GradeRow, first_attempts
from crb.core.reading import mcnemar_p
from crb.core.stats import wilson_interval

#: The fixed banner every rendering of a hindsight comparison leads with (ADR-0050 R6).
CEILING_BANNER = (
    "CEILING - a hindsight brief that may restate the answer; not a builder capability; "
    "never certifies, licenses or routes"
)

#: The banner a stated-requirement comparison leads with instead (ADR-0052 item 6): its items
#: were written with sight of the change, so it is read beside its provenance line, never alone.
STATED_BANNER = (
    "STATED REQUIREMENTS - items written with sight of the change, leak-guarded and labelled "
    "by provenance; measurement only; never certifies, licenses or routes"
)

REASON_MIXED_ARM = "ctx_pair_mixed_arm"
REASON_UNLINKED = "ctx_pair_unlinked"
REASON_BLEND = "ctx_pair_blend"
REASON_UNSEALED = "ctx_pair_unsealed"
REASON_GAP_MISMATCH = "ctx_gap_mismatch"
#: A stated treatment read against a set that does not state the same items (ADR-0052 item 6):
#: a non-req set, or a req set whose items digest, repo or tasks differ.
REASON_ITEMS_MISMATCH = "ctx_pair_items_mismatch"
REASONS: tuple[str, ...] = (
    REASON_MIXED_ARM,
    REASON_UNLINKED,
    REASON_BLEND,
    REASON_UNSEALED,
    REASON_GAP_MISMATCH,
    REASON_ITEMS_MISMATCH,
)

#: The ``GradeRow`` attributes no reader blends: each side holds one value of each, and the
#: two sides hold the same one.
BLEND_FIELDS: tuple[str, ...] = (
    "apparatus_version",
    "posture_class",
    "builder_executor",
    "checks_arm",
    "builder",
    "model",
    "taxonomy",
    "mode",
)

#: ``dose_imbalance`` is set when the two sides' delivered characters differ by more than this
#: share of the larger, or their delivered-entry fractions by more than this many points.
DOSE_TOLERANCE = 0.10
#: ``drift`` is set when the two sides ran more than this many days apart.
DRIFT_DAYS = 7


def _ts(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


class CtxPairRefused(ValueError):
    """A pair the reader will not read; ``reason`` is one of :data:`REASONS`."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in REASONS:
            raise ValueError(f"unknown context-pair refusal reason {reason!r}")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SideDose:
    """What one side's first attempts delivered: entries that reached the brief, those that
    did not (refused by admission or the leak guard, or the attempt failed before compose),
    and the delivered characters. A control side delivers nothing."""

    delivered: int = 0
    refused: int = 0
    chars: int = 0

    @property
    def fraction(self) -> float | None:
        """Delivered entries over the side's first attempts; ``None`` with none."""
        n = self.delivered + self.refused
        return self.delivered / n if n else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivered_entries": self.delivered,
            "refused_entries": self.refused,
            "delivered_fraction": None if self.fraction is None else round(self.fraction, 4),
            "delivered_chars": self.chars,
        }


@dataclass(frozen=True)
class SideRate:
    """One side's first attempts: ``k`` clean of ``n`` observed tasks, with its interval."""

    k: int
    n: int

    def to_dict(self) -> dict[str, Any]:
        ci = wilson_interval(self.k, self.n)
        return {
            "k": self.k,
            "n": self.n,
            "point": round(self.k / self.n, 4) if self.n else None,
            "ci_low": round(ci.low, 4),
            "ci_high": round(ci.high, 4),
        }


@dataclass(frozen=True)
class Stratum:
    """The pair's counts within one ``ctx_gap`` value (descriptive only)."""

    gap: str
    b: int
    c: int
    control: SideRate
    treatment: SideRate

    def to_dict(self) -> dict[str, Any]:
        return {
            "ctx_gap": self.gap,
            "b": self.b,
            "c": self.c,
            "control": self.control.to_dict(),
            "treatment": self.treatment.to_dict(),
        }


@dataclass(frozen=True)
class ProvStratum:
    """The pair's counts over the tasks whose stated entry does (or does not) hold an item
    only the held-out tests state (ADR-0052 review note 8; descriptive only)."""

    tests_only: bool
    b: int
    c: int
    control: SideRate
    treatment: SideRate

    def to_dict(self) -> dict[str, Any]:
        return {
            "tests_only": self.tests_only,
            "b": self.b,
            "c": self.c,
            "control": self.control.to_dict(),
            "treatment": self.treatment.to_dict(),
        }


def _median(xs: Sequence[float]) -> float | None:
    return round(statistics.median(xs), 6) if xs else None


@dataclass(frozen=True)
class SideCost:
    """What one side's first attempts spent: ``cost_usd``, tokens and ``ctx_turns`` (the
    builder's turns; rows written before ADR-0052 carry none and count in ``turns_missing``).
    ``cost_usd`` holds KNOWN costs only (``GradeRow.cost_known``); an attempt whose cost is a
    placeholder counts in ``cost_usd_missing``, never as a measured zero."""

    n: int = 0
    cost_usd: tuple[float, ...] = ()
    cost_usd_missing: int = 0
    tokens_in: tuple[int, ...] = ()
    tokens_out: tuple[int, ...] = ()
    turns: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "cost_usd_median": _median(self.cost_usd),
            "cost_usd_total": round(sum(self.cost_usd), 6),
            "cost_usd_missing": self.cost_usd_missing,
            "tokens_in_median": _median(self.tokens_in),
            "tokens_in_total": sum(self.tokens_in),
            "tokens_out_median": _median(self.tokens_out),
            "tokens_out_total": sum(self.tokens_out),
            "turns_median": _median(self.turns),
            "turns_total": sum(self.turns),
            "turns_missing": self.n - len(self.turns),
        }


@dataclass(frozen=True)
class PairedCost:
    """Treatment minus control ``cost_usd`` over the tasks observed on both sides with a KNOWN
    cost on both; a task observed on both sides but unpriced on either counts in ``n_missing``."""

    diffs: tuple[float, ...] = ()
    n_missing: int = 0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "n": len(self.diffs),
            "n_missing": self.n_missing,
            "median": _median(self.diffs),
        }
        if len(self.diffs) >= 2:
            q1, _, q3 = statistics.quantiles(self.diffs, n=4, method="inclusive")
            out["iqr"] = [round(q1, 6), round(q3, 6)]
        else:
            out["iqr"] = None
        return out


@dataclass(frozen=True)
class Window:
    """The ``created`` span of one side's first attempts (ISO-8601 UTC strings)."""

    first: str = ""
    last: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"first": self.first, "last": self.last}


@dataclass(frozen=True)
class CtxPair:
    """Two runs of one context set, paired task by task (module docstring)."""

    control_arm: str
    treatment_arm: str
    #: The treatment set's full digest, and the ``ctx_set`` the control rows carry.
    treatment_set: str
    control_set: str
    tasks: tuple[str, ...]
    b: int
    c: int
    control: SideRate
    treatment: SideRate
    control_dose: SideDose
    treatment_dose: SideDose
    dose_imbalance: bool
    gap_rule: str
    strata: tuple[Stratum, ...]
    #: Tasks with no first attempt on either side, in set order (fail closed).
    pending: tuple[str, ...] = ()
    scope: Mapping[str, str] = field(default_factory=dict)
    control_cost: SideCost = SideCost()
    treatment_cost: SideCost = SideCost()
    paired_cost: PairedCost = PairedCost()
    control_window: Window = Window()
    treatment_window: Window = Window()
    #: A stated treatment's ``ctx_prov`` counts summed over its first attempts (ADR-0052).
    provenance: Mapping[str, int] = field(default_factory=dict)
    prov_strata: tuple[ProvStratum, ...] = ()
    #: The control is an entries run of another stated set with the same items: a structure
    #: (or drafter) contrast, read head to head.
    head_to_head: bool = False

    @property
    def stated(self) -> bool:
        """A stated-requirement treatment (``ctx.req*``, ADR-0052)."""
        return stated_arm(self.treatment_arm)

    @property
    def drift(self) -> bool:
        """The two sides ran more than :data:`DRIFT_DAYS` apart (the gap between one side's
        last first attempt and the other's first), so a model or provider change between
        them is not excluded (descriptive only; it refuses nothing)."""
        a, b = self.control_window, self.treatment_window
        if not (a.first and a.last and b.first and b.last):
            return False
        try:
            gap = max(_ts(b.first) - _ts(a.last), _ts(a.first) - _ts(b.last))
        except ValueError:
            return True  # an unreadable stamp: no claim the sides are close
        return gap > timedelta(days=DRIFT_DAYS)

    @property
    def complete(self) -> bool:
        return not self.pending

    @property
    def p(self) -> float:
        """The exact two-sided McNemar p over ``b`` and ``c``."""
        return mcnemar_p(self.b, self.c)

    @property
    def ceiling(self) -> bool:
        """A hindsight treatment: a ceiling, never a capability (ADR-0050 R6)."""
        return hindsight_arm(self.treatment_arm)

    @property
    def banner(self) -> str:
        if self.stated:
            return STATED_BANNER
        return CEILING_BANNER if self.ceiling else ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.banner:
            out["banner"] = self.banner  # leads every rendering
        out.update(
            {
                "ceiling": self.ceiling,
                "control_arm": self.control_arm,
                "treatment_arm": self.treatment_arm,
                "treatment_set": self.treatment_set,
                "control_set": self.control_set,
                "tasks": len(self.tasks),
                "b": self.b,
                "c": self.c,
                "p": round(self.p, 6),
                "complete": self.complete,
                "pending": list(self.pending),
                "control": {**self.control.to_dict(), **self.control_dose.to_dict()},
                "treatment": {**self.treatment.to_dict(), **self.treatment_dose.to_dict()},
                "dose_imbalance": self.dose_imbalance,
                "ctx_gap_rule": self.gap_rule,
                "strata": [s.to_dict() for s in self.strata],
                "cost": {
                    "control": self.control_cost.to_dict(),
                    "treatment": self.treatment_cost.to_dict(),
                    "paired_cost_usd_diff": self.paired_cost.to_dict(),
                },
                "windows": {
                    "control": self.control_window.to_dict(),
                    "treatment": self.treatment_window.to_dict(),
                },
                "drift": self.drift,
                **dict(self.scope),
            }
        )
        if self.stated:
            out["stated"] = True
            out["head_to_head"] = self.head_to_head
            out["provenance"] = dict(self.provenance)
            out["prov_strata"] = [s.to_dict() for s in self.prov_strata]
        return out


def _one_arm(rows: Sequence[GradeRow], side: str) -> str:
    arms = sorted({r.context_arm for r in rows})
    if len(arms) != 1:
        raise CtxPairRefused(
            REASON_MIXED_ARM, f"the {side} side holds {len(arms)} arms ({arms or 'none'})"
        )
    return arms[0]


def _refuse_blend(control: Sequence[GradeRow], treatment: Sequence[GradeRow]) -> dict[str, str]:
    scope: dict[str, str] = {}
    for attr in BLEND_FIELDS:
        left = {str(getattr(r, attr)) for r in control}
        right = {str(getattr(r, attr)) for r in treatment}
        if len(left) > 1 or len(right) > 1 or (left and right and left != right):
            raise CtxPairRefused(
                REASON_BLEND,
                f"{attr}: control {sorted(left)}, treatment {sorted(right)} — never blended",
            )
        scope[attr] = next(iter(right or left), "")
    return scope


def _refuse_unsealed(rows: Sequence[GradeRow]) -> None:
    unsealed = sorted({r.builder_executor or "-" for r in rows} - {BUILDER_EXECUTOR_SEALED})
    if unsealed:
        raise CtxPairRefused(
            REASON_UNSEALED,
            f"rows whose builder ran {unsealed}, not in the sealed container "
            f"({BUILDER_EXECUTOR_SEALED!r}): a context set is never read in the host posture",
        )


def _gaps(
    control: Sequence[GradeRow], treatment: Sequence[GradeRow], tasks: Sequence[str]
) -> tuple[str, dict[str, str]]:
    rows = [*control, *treatment]
    rules = sorted({r.labels.get(LABEL_CTX_GAP_RULE, "") for r in rows})
    if len(rules) > 1 or "" in rules:
        raise CtxPairRefused(REASON_GAP_MISMATCH, f"gap rules {rules} — one rule per pair")
    gaps: dict[str, str] = {}
    for tid in tasks:
        seen = {r.labels.get(LABEL_CTX_GAP, "") for r in rows if r.task_id == tid}
        if len(seen) > 1 or "" in seen:
            raise CtxPairRefused(REASON_GAP_MISMATCH, f"{tid}: ctx_gap {sorted(seen)}")
        if seen:
            gaps[tid] = next(iter(seen))
    return (rules[0] if rules else ""), gaps


def _outcomes(rows: Sequence[GradeRow]) -> dict[str, bool]:
    """Each task with a first attempt → whether it was clean (a harness-only task observed
    nothing: a miss, ADR-0025 item 2)."""
    return {fa.task_id: fa.clean for fa in first_attempts(rows)}


def _count(labels: Mapping[str, str], key: str) -> int:
    raw = labels.get(key, "0")
    return int(raw) if raw.isdecimal() else 0


def _dose(rows: Sequence[GradeRow], entries: bool) -> SideDose:
    if not entries:
        return SideDose()
    delivered = refused = chars = 0
    for fa in first_attempts(rows):
        n = _count(fa.row.labels, LABEL_CTX_DELIVERED)
        delivered += 1 if n else 0
        refused += 0 if n else 1
        chars += _count(fa.row.labels, LABEL_CTX_CHARS) if n else 0
    return SideDose(delivered, refused, chars)


def _imbalanced(a: SideDose, b: SideDose) -> bool:
    top = max(a.chars, b.chars)
    if top and abs(a.chars - b.chars) > DOSE_TOLERANCE * top:
        return True
    fa, fb = a.fraction, b.fraction
    return fa is not None and fb is not None and abs(fa - fb) > DOSE_TOLERANCE


def _pair_counts(
    tasks: Sequence[str],
    control: Mapping[str, bool],
    treatment: Mapping[str, bool],
) -> tuple[int, int, SideRate, SideRate]:
    """``b`` and ``c`` over ``tasks`` read fail-closed, and each side's observed ``k``/``n``."""
    b = c = 0
    for tid in tasks:
        left = control.get(tid, True)  # pending on the control: read clean
        right = treatment.get(tid, False)  # pending on the treatment: read a miss
        b += 1 if right and not left else 0
        c += 1 if left and not right else 0
    ctl = SideRate(sum(1 for t in tasks if control.get(t)), sum(1 for t in tasks if t in control))
    trt = SideRate(
        sum(1 for t in tasks if treatment.get(t)), sum(1 for t in tasks if t in treatment)
    )
    return b, c, ctl, trt


def _cost(rows: Sequence[GradeRow]) -> SideCost:
    fas = first_attempts(rows)
    turns = [int(t) for fa in fas if (t := fa.row.labels.get(LABEL_CTX_TURNS, "")).isdecimal()]
    return SideCost(
        n=len(fas),
        cost_usd=tuple(float(fa.row.cost_usd) for fa in fas if fa.row.cost_known),
        cost_usd_missing=sum(1 for fa in fas if not fa.row.cost_known),
        tokens_in=tuple(int(fa.row.tokens_in) for fa in fas),
        tokens_out=tuple(int(fa.row.tokens_out) for fa in fas),
        turns=tuple(turns),
    )


def _paired_cost(
    control: Sequence[GradeRow], treatment: Sequence[GradeRow], tasks: Sequence[str]
) -> PairedCost:
    # ``None`` marks an observed attempt whose cost is unknown: it is never a measured zero.
    def priced(rows: Sequence[GradeRow]) -> dict[str, float | None]:
        return {
            fa.task_id: float(fa.row.cost_usd) if fa.row.cost_known else None
            for fa in first_attempts(rows)
        }

    left, right = priced(control), priced(treatment)
    both = [t for t in tasks if t in left and t in right]
    diffs = tuple(r - c for t in both if (c := left[t]) is not None and (r := right[t]) is not None)
    return PairedCost(diffs, n_missing=len(both) - len(diffs))


def _window(rows: Sequence[GradeRow]) -> Window:
    stamps = sorted(fa.row.created for fa in first_attempts(rows) if fa.row.created)
    return Window(stamps[0], stamps[-1]) if stamps else Window()


def _provenance(rows: Sequence[GradeRow]) -> dict[str, int]:
    """The treatment's ``ctx_prov`` counts summed over its first attempts."""
    total = dict.fromkeys((*_stated.PROVENANCES, _stated.PROV_ATTESTED), 0)
    for fa in first_attempts(rows):
        raw = fa.row.labels.get(LABEL_CTX_PROV, "")
        if not _stated.PROV_LABEL_RE.match(raw):
            continue
        for part in raw.replace(";", ",").split(","):
            key, _, n = part.partition(":")
            total[key] += int(n)
    return total


def _link_stated(
    tset: CtxSet, c_digests: set[str], linked: set[str], sets: Mapping[str, CtxSet]
) -> bool:
    """Extend ``linked`` with each control set that states the treatment's items (another
    structure over the same items digest, repo and tasks); ``True`` when one did. Refuses a
    stated treatment against any other set. The caller reads ``True`` as head to head only
    when the control is an entries run; a control run of that set is a shared control."""
    head = False
    for d in sorted(c_digests - linked):
        other = sets.get(d)
        if other is None:
            raise CtxPairRefused(REASON_UNLINKED, f"the control's set {d[:12]} is not stored")
        if not other.stated:
            raise CtxPairRefused(
                REASON_ITEMS_MISMATCH,
                f"a stated treatment {tset.name} is read against a stated set or its own "
                f"control only, not {other.name}",
            )
        if (other.items_digest, other.repo, other.task_ids) != (
            tset.items_digest,
            tset.repo,
            tset.task_ids,
        ):
            raise CtxPairRefused(
                REASON_ITEMS_MISMATCH,
                f"{other.name} does not state the same items over the same tasks as {tset.name}",
            )
        linked.add(d)
        head = True
    return head


def ctx_pair(
    control: Sequence[GradeRow],
    treatment: Sequence[GradeRow],
    *,
    task_ids: Sequence[str],
    sets: Mapping[str, CtxSet],
) -> CtxPair:
    """Pair ``control`` with ``treatment`` over ``task_ids`` (the treatment set's tasks, in set
    order); ``sets`` maps a full digest to its parsed set (the treatment's, and for a placebo
    the treatment it is matched to). Raises :class:`CtxPairRefused` (module docstring)."""
    control, treatment = list(control), list(treatment)
    if not treatment:
        raise CtxPairRefused(REASON_UNLINKED, "the treatment run has no rows to link to a set")
    t_arm = _one_arm(treatment, "treatment")
    name = ctx_set_name(t_arm)
    if not name:
        raise CtxPairRefused(REASON_UNLINKED, f"the treatment arm {t_arm!r} names no context set")
    t_digests = {r.labels.get(LABEL_CTX_SET, "") for r in treatment}
    t_digest = next(iter(t_digests)) if len(t_digests) == 1 else ""
    tset = sets.get(t_digest)
    if tset is None or tset.name != name:
        raise CtxPairRefused(
            REASON_UNLINKED, f"the treatment rows' ctx_set is not the stored set {name!r}"
        )
    if tuple(task_ids) != tset.task_ids:
        raise CtxPairRefused(REASON_UNLINKED, "task_ids are not the treatment set's tasks")
    linked = {tset.digest, *([tset.matched_to] if tset.placebo else [])}

    c_arm = _one_arm(control, "control") if control else BASE_A0
    c_digests = {r.labels.get(LABEL_CTX_SET, "") for r in control}
    head_to_head = False
    if tset.stated and len(c_digests) == 1:
        # a control run (plain A0) or an entries run of any stated set over the same items
        # links: two structures over one items digest share one control (ADR-0052 item 5);
        # only an entries run against an entries run is the head-to-head contrast
        linked_other = _link_stated(tset, c_digests, linked, sets)
        head_to_head = linked_other and bool(ctx_set_name(c_arm))
    elif not tset.stated and ctx_set_name(c_arm) and stated_arm(c_arm):
        raise CtxPairRefused(
            REASON_ITEMS_MISMATCH, f"a stated control {c_arm!r} against a non-stated treatment"
        )
    if len(c_digests) > 1 or not c_digests <= linked:
        raise CtxPairRefused(
            REASON_UNLINKED,
            f"the control rows' ctx_set {sorted(d[:12] for d in c_digests)} is not the "
            f"treatment set {tset.name} or the set it is matched to",
        )
    control_set = next(iter(c_digests), "")
    c_entries = bool(ctx_set_name(c_arm))
    if not c_entries and (
        c_arm != BASE_A0
        or any(r.labels.get(LABEL_CTX_SOURCE) != CTX_SOURCE_CONTROL for r in control)
    ):
        raise CtxPairRefused(
            REASON_UNLINKED, f"the control arm {c_arm!r} is neither a control run nor a set's"
        )
    if c_entries and (c_arm == t_arm or control_set not in linked):
        raise CtxPairRefused(REASON_UNLINKED, "the control is not the set the treatment names")
    stray = sorted({r.task_id for r in (*control, *treatment)} - set(task_ids))
    if stray:
        raise CtxPairRefused(REASON_UNLINKED, f"rows of tasks outside the set: {stray[:5]}")

    scope = _refuse_blend(control, treatment)
    _refuse_unsealed([*control, *treatment])
    rule, gaps = _gaps(control, treatment, task_ids)

    left = _outcomes(control)
    right = _outcomes(treatment)
    tasks = tuple(task_ids)
    pending = tuple(t for t in tasks if t not in left or t not in right)
    b, c, ctl, trt = _pair_counts(tasks, left, right)
    c_dose = _dose(control, c_entries)
    t_dose = _dose(treatment, True)
    strata = []
    for gap in sorted(set(gaps.values())):
        in_gap = [t for t in tasks if gaps.get(t) == gap]
        sb, sc, sl, sr = _pair_counts(in_gap, left, right)
        strata.append(Stratum(gap, sb, sc, sl, sr))
    prov_strata: list[ProvStratum] = []
    provenance: dict[str, int] = {}
    if tset.stated:
        provenance = _provenance(treatment)
        flag = {t: _stated.any_tests_only(tset.entry_for(t).items) for t in tasks}
        for value in (False, True):
            in_s = [t for t in tasks if flag[t] is value]
            if in_s:
                sb, sc, sl, sr = _pair_counts(in_s, left, right)
                prov_strata.append(ProvStratum(value, sb, sc, sl, sr))
    return CtxPair(
        control_arm=c_arm,
        treatment_arm=t_arm,
        treatment_set=tset.digest,
        control_set=control_set,
        tasks=tasks,
        b=b,
        c=c,
        control=ctl,
        treatment=trt,
        control_dose=c_dose,
        treatment_dose=t_dose,
        dose_imbalance=c_entries and _imbalanced(c_dose, t_dose),
        gap_rule=rule,
        strata=tuple(strata),
        pending=pending,
        scope=scope,
        control_cost=_cost(control),
        treatment_cost=_cost(treatment),
        paired_cost=_paired_cost(control, treatment, tasks),
        control_window=_window(control),
        treatment_window=_window(treatment),
        provenance=provenance,
        prov_strata=tuple(prov_strata),
        head_to_head=head_to_head,
    )


def render(pair: CtxPair) -> str:
    """The pair as text: the banner first (ceiling, or stated with its provenance line)."""
    lines = [pair.banner] if pair.banner else []
    d = pair.to_dict()
    if pair.stated:
        lines.append("provenance " + " ".join(f"{k}={v}" for k, v in pair.provenance.items()))
    lines.append(f"control   {pair.control_arm}  k/n {d['control']['k']}/{d['control']['n']}")
    lines.append(f"treatment {pair.treatment_arm}  k/n {d['treatment']['k']}/{d['treatment']['n']}")
    lines.append(f"b={pair.b} c={pair.c} exact McNemar p={d['p']}")
    if pair.pending:
        lines.append(f"PENDING {len(pair.pending)} task(s): no claim until complete")
    if pair.dose_imbalance:
        lines.append("dose_imbalance: the two sides delivered different doses (read ITT)")
    if pair.stated:
        lines.extend(prov_strata_lines(d.get("prov_strata") or []))
    if pair.drift:
        lines.append(
            "drift: the two sides ran in disjoint windows (a model change is not excluded)"
        )
    return "\n".join(lines)


def prov_strata_lines(strata: Sequence[Mapping[str, Any]]) -> list[str]:
    """One text line per provenance stratum of a stated pair (``to_dict``'s ``prov_strata``):
    the tasks whose entry holds a ``tests_only`` item, and the rest, each with its paired
    counts and both sides' k/n (ADR-0052 item 6). Both strata are always printed, an empty
    one as ``n 0``, so a pooled stated effect is never read without its split."""
    by_flag = {bool(s.get("tests_only")): s for s in strata}
    out: list[str] = []
    for flag, label in ((True, "tests_only"), (False, "no_tests_only")):
        s = by_flag.get(flag)
        if s is None:
            out.append(f"stratum {label}  n 0")
            continue
        ctl, trt = s["control"], s["treatment"]
        out.append(
            f"stratum {label}  n {trt['n']}  b={s['b']} c={s['c']}  "
            f"control k/n {ctl['k']}/{ctl['n']}  treatment k/n {trt['k']}/{trt['n']}"
        )
    return out


__all__ = [
    "BLEND_FIELDS",
    "CEILING_BANNER",
    "DOSE_TOLERANCE",
    "DRIFT_DAYS",
    "REASONS",
    "REASON_BLEND",
    "REASON_GAP_MISMATCH",
    "REASON_ITEMS_MISMATCH",
    "REASON_MIXED_ARM",
    "REASON_UNLINKED",
    "REASON_UNSEALED",
    "STATED_BANNER",
    "CtxPair",
    "CtxPairRefused",
    "PairedCost",
    "ProvStratum",
    "SideCost",
    "SideDose",
    "SideRate",
    "Stratum",
    "Window",
    "ctx_pair",
    "prov_strata_lines",
    "render",
]
