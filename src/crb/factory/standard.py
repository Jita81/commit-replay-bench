"""The entry gate and the licence: a ticket is built only on its cell's proven standard.

ADR-0026 item 8. Before any spend, an item enters manufacturing only when its (class ×
size) cell has a **proven context standard** — the arm (``S1@<author>``, ``S2``, with
``+L`` when the loop is part of it) whose registered reading delivers — and the item
carries what that arm needs: the structural slots the test author reads for ``S1``, a
failing test a person attached for ``S2``. Otherwise it stops, named, whether or not
delivery is switched on:

``granularize``          the size rule reads an ``XL`` cell (an ``L`` item until the
                         points-to-churn agreement passes);
``no_proven_standard``   a cell it reads has no standard, or only an ``S3`` ceiling;
``needs_context``        the item lacks what the standard arm needs;
``unsigned_cell``        where a signed cell is required, the standard has no active
                         sign-off — the ONE clause an approver's ``deliver_override`` lifts;
``not_licensed``         with delivery on, no rung of the ladder holds a licence at the
                         item's size (its builder and model; never a projection that pools
                         models).

An approver may fund an item stopped ``no_proven_standard`` or ``needs_context`` as a
**calibration build**: evented as one, stamped with its arm, and never able to open a
pull request (``calibration_build``). After an accepted review the delivered change's
OWN cell — its class, the size tier of the build's churn, the final rung's builder and
model — must license delivery, or the item stops ``size_exceeds_licence`` (the build is
larger than its estimate) or ``cell_not_licensed``.

**The size rule.** Until the organisation's points-to-churn agreement passes
(:func:`points_agreement_passed`), the gate reads the cell the estimate names AND the
next larger one and applies the more demanding (ADR-0026 [operator] value): no standard
is more demanding than a ceiling, a ceiling than ``S2``, ``S2`` than ``S1``. An item
without an estimate is ``unsized`` and goes to a person — it can never claim a smaller
cell.

**Seams** (each one named function, wired at integration): :func:`standard_for` and
:func:`arm_readings_for` are stream R's registered readings (routing.v2); until they land
no cell has a proven standard, which is the truth on this branch — every item stops
``no_proven_standard`` and only a calibration build is built. :func:`points_agreement_passed`
is ADR-0026 item 9's validity report (Wave 4); until it exists the agreement has not
passed.

Navigation
----------
What it is:   The entry gate, the calibration grant and the licence of the delivered change
              (ADR-0026 item 8, ADR-0025 item 12) — pure functions over a reader of cell
              standards.
What it does: ``decide_entry`` returns the stop (or the entry) for one item before any spend:
              the size rule, the standard, what the ticket must carry, the sign-off clause and
              the override that lifts only it, the calibration grant; ``licensing_rungs`` and
              ``own_cell_licence`` read the builder × model licence before the build and on the
              delivered change's measured cell after it.
How:          ``CellRef`` → ``StandardFor`` (a callable the worker binds to the pre-run map) →
              ``Standard`` (arm, ceiling, signed); ``more_demanding`` orders two cells;
              ``Entry`` / ``Licence`` are the recorded decisions.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 8),
              docs/adr/0003-one-routing-rule.md (the route gate; superseded in part)
Works with:   src/crb/factory/loop.py (``_assess`` calls ``decide_entry``; ``_deliver`` calls
              ``own_cell_licence``), src/crb/server/worker.py (binds the readers once per run,
              before any build), src/crb/intake/feedback.py (the ticket's words for each stop),
              src/crb/server/routes/factory.py (the calibration route and the task view)
Tested by:    tests/test_factory_entry_gate.py
Touch when:   stream R's readings land (replace the three seams' bodies with the real
              readers); the operator fixes ADR-0026 item 8's size value; a new stop is added
              (a code here, a status in loop.py, a sentence in feedback.py and the UI).
Claims:       a proven standard licenses an attempt on its arm, never a merge; "not built" is
              the gate's word, never "built and withheld" (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.core.spec import SIZE_TIER_NAMES
from crb.factory.backlog import ITEM_SIZES, SIZE_UNSIZED, BacklogItem
from crb.factory.readiness import Readiness

#: The size the routing policy sends to be split before any attempt.
SIZE_GRANULARIZE = "XL"

STOP_UNSIZED = "unsized"
STOP_GRANULARIZE = "granularize"
STOP_NO_PROVEN_STANDARD = "no_proven_standard"
STOP_NEEDS_CONTEXT = "needs_context"
STOP_UNSIGNED_CELL = "unsigned_cell"
STOP_NOT_LICENSED = "not_licensed"
STOP_SIZE_EXCEEDS_LICENCE = "size_exceeds_licence"
STOP_CELL_NOT_LICENSED = "cell_not_licensed"
STOP_CALIBRATION_BUILD = "calibration_build"
#: The stops an approver's calibration build answers (ADR-0026 item 8) — no other.
CALIBRATABLE: frozenset[str] = frozenset({STOP_NO_PROVEN_STANDARD, STOP_NEEDS_CONTEXT})
#: The one stop ``deliver_override`` lifts (ADR-0026 item 8) — no other.
OVERRIDABLE: frozenset[str] = frozenset({STOP_UNSIGNED_CELL})

#: ``no_proven_standard``'s two reasons: nothing is proven, or only a ceiling.
REASON_NONE = "none"
REASON_CEILING = "ceiling"

BASE_S1 = "S1"
BASE_S2 = "S2"
BASE_S3 = "S3"
MODIFIER_LOOP = "+L"
#: The bases that certify (license) a cell; ``S3`` alone is a ceiling (ADR-0026 item 4).
CERTIFYING_BASES: frozenset[str] = frozenset({BASE_S1, BASE_S2})

#: What each certifying arm asks the ticket for, in words a person can act on.
NEEDS: dict[str, str] = {
    BASE_S1: "the structural facts the test author reads, one `slot: text` line each",
    BASE_S2: "a failing test a person wrote, attached to the ticket before any build",
}


def _base(arm: str) -> str:
    return arm.split("+", 1)[0].split("@", 1)[0]


@dataclass(frozen=True)
class CellRef:
    """One cell to read: its class and size, and — for a licence — the building rung's
    builder and model (empty for the class × size standard)."""

    capability_class: str
    size: str
    builder: str = ""
    model: str = ""

    def key(self) -> str:
        parts = [self.capability_class, self.size]
        if self.builder or self.model:
            parts += [self.builder, self.model]
        return "|".join(parts)

    def to_dict(self) -> dict[str, str]:
        out = {"capability_class": self.capability_class, "size": self.size}
        if self.builder or self.model:
            out |= {"builder": self.builder, "model": self.model}
        return out


@dataclass(frozen=True)
class Standard:
    """A cell's proven context standard as the signed map serves it: the arm id
    (ADR-0026 item 1's grammar), whether it carries an active sign-off, and the reading it
    came from. ``S3`` alone is a CEILING: it licenses nothing."""

    arm: str
    signed: bool = False
    reading_id: str = ""

    def __post_init__(self) -> None:
        if _base(self.arm) not in (BASE_S1, BASE_S2, BASE_S3):
            raise ValueError(f"a standard's arm is S1@<author>, S2 or S3, got {self.arm!r}")

    @property
    def base(self) -> str:
        return _base(self.arm)

    @property
    def plus_l(self) -> bool:
        """The loop's switch is part of the arm: its overlay and lines reach the brief."""
        return MODIFIER_LOOP[1:] in self.arm.split("+")[1:]

    @property
    def ceiling(self) -> bool:
        return self.base == BASE_S3

    @property
    def licenses(self) -> bool:
        return self.base in CERTIFYING_BASES

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "signed": self.signed,
            "reading_id": self.reading_id,
            "ceiling": self.ceiling,
        }


@dataclass(frozen=True)
class ArmReading:
    """One measured arm of a cell, as the ticket comment quotes it: its state (the look
    rule's word), distinct commits, clean commits and the 95 % Wilson interval."""

    arm: str
    state: str
    n: int = 0
    clean: int = 0
    ci_low: float = 0.0
    ci_high: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "state": self.state,
            "n": self.n,
            "clean": self.clean,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
        }


#: ``cell → Standard | None`` — the reader the gate is given (bound to the pre-run map).
StandardFor = Callable[[CellRef], "Standard | None"]


# --- the seams (stream R's readings; ADR-0026 item 9's report) ---------------------------


def standard_for(repo: str, cell: CellRef) -> Standard | None:
    """SEAM (stream R, routing.v2): the cell's proven standard from the current signed map,
    or ``None`` when no registered reading of a certifying arm delivers there. Until R's
    readings land nothing has been registered, so nothing is proven — the true answer on
    this branch is ``None`` for every cell. The integration replaces this body with R's
    ``crb.core.reading`` reader; the worker binds it once per run, before any build."""
    del repo, cell
    return None


def arm_readings_for(repo: str, cell: CellRef) -> tuple[ArmReading, ...]:
    """SEAM (stream R): every measured arm of the cell with its state, n and interval, for
    the ticket comment. Empty until R's registered readings land."""
    del repo, cell
    return ()


def points_agreement_passed(repo: str) -> bool:
    """SEAM (ADR-0026 item 9's validity report, Wave 4): whether the organisation's
    points-to-churn agreement has passed for ``repo``. Until the report exists, it has not,
    so the size rule reads two cells."""
    del repo
    return False


# --- the size rule -----------------------------------------------------------------------


def next_size(size: str) -> str:
    """The next larger tier (``XL`` stays ``XL``)."""
    i = SIZE_TIER_NAMES.index(size)
    return SIZE_TIER_NAMES[min(i + 1, len(SIZE_TIER_NAMES) - 1)]


def sizes_to_read(size: str, *, agreement_passed: bool) -> tuple[str, ...]:
    """The cells the size rule reads for an estimate: the named one, and — until the
    points-to-churn agreement passes — the next larger one too (ADR-0026 item 8)."""
    if size not in SIZE_TIER_NAMES:
        raise ValueError(f"size {size!r} is not a tier")
    if agreement_passed or size == SIZE_GRANULARIZE:
        return (size,)
    return (size, next_size(size))


def _demand(standard: Standard | None) -> int:
    """How much a standard demands of a ticket: none > ceiling > S2 > S1."""
    if standard is None:
        return 4
    if standard.ceiling:
        return 3
    return 2 if standard.base == BASE_S2 else 1


def more_demanding(
    read: Sequence[tuple[str, Standard | None]],
) -> tuple[str, Standard | None]:
    """Of the cells read (size, standard), the more demanding; on a tie the LARGER size's,
    because that cell's licence covers the larger change."""
    best = read[0]
    for cand in read[1:]:
        if _demand(cand[1]) >= _demand(best[1]):
            best = cand
    return best


# --- the entry decision -----------------------------------------------------------------


@dataclass(frozen=True)
class Calibration:
    """An approver's funded calibration build for one item (``calibration.funded``)."""

    approver: str
    reason: str
    event_id: str = ""


@dataclass(frozen=True)
class Entry:
    """The gate's decision for one item. ``code`` is empty when the item enters; otherwise
    it is the stop, with the sentence, what the ticket must carry (``needs``), the cells the
    size rule read and the standard it applied."""

    code: str = ""
    reason: str = ""
    reason_code: str = ""
    needs: tuple[str, ...] = ()
    standard: Standard | None = None
    cells: tuple[Mapping[str, Any], ...] = ()
    #: An approver funded this build as a calibration build: it never delivers.
    calibration: Calibration | None = None
    #: An approver's override lifted the sign-off clause (and only that) for this run.
    override_by: str = ""

    @property
    def enters(self) -> bool:
        return not self.code

    @property
    def arm(self) -> str:
        return self.standard.arm if self.standard is not None else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "needs": list(self.needs),
            "standard": self.standard.to_dict() if self.standard is not None else None,
            "cells": [dict(c) for c in self.cells],
            "calibration": (
                {"approver": self.calibration.approver, "reason": self.calibration.reason}
                if self.calibration is not None
                else None
            ),
            "override_by": self.override_by,
        }


def _cells_view(read: Iterable[tuple[str, Standard | None]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "size": size,
            "standard": std.arm if std is not None else "",
            "ceiling": bool(std and std.ceiling),
        }
        for size, std in read
    )


def _cells(named: Sequence[str], *, possessive: bool = True) -> str:
    """``cell's`` / ``cells'`` (or ``cell`` / ``cells``) for the cells a sentence names."""
    one = len(named) == 1
    if possessive:
        return "cell's" if one else "cells'"
    return "cell" if one else "cells"


def decide_entry(
    *,
    capability_class: str,
    size: str,
    standard_for: StandardFor,
    agreement_passed: bool,
    missing_slots: Sequence[str],
    person_test: bool,
    calibration: Calibration | None = None,
    require_signed_cell: bool = False,
    override_by: str = "",
) -> Entry:
    """The entry gate for one item, before any spend (ADR-0026 item 8).

    ``missing_slots`` are the unsigned structural slots readiness found; ``person_test`` is
    whether a person attached a failing test. ``calibration`` is an approver's grant: it
    admits an item stopped ``no_proven_standard`` or ``needs_context`` (never any other
    stop) as a calibration build. ``override_by`` lifts ``unsigned_cell`` and nothing else.
    """
    if size == SIZE_UNSIZED or size not in SIZE_TIER_NAMES:
        return Entry(
            STOP_UNSIZED,
            "the item carries no size estimate, so it cannot claim a cell — a person sizes it "
            "(story points on the ticket, or an operator's estimate)",
            reason_code=STOP_UNSIZED,
            calibration=None,
        )
    sizes = sizes_to_read(size, agreement_passed=agreement_passed)
    if SIZE_GRANULARIZE in sizes:
        return Entry(
            STOP_GRANULARIZE,
            f"the size rule reads {' and '.join(sizes)} for an estimate of {size}"
            + ("" if agreement_passed else " (the points-to-churn agreement has not passed)")
            + f", and {SIZE_GRANULARIZE} changes are split before any attempt: split the "
            "ticket into smaller ones",
            reason_code=STOP_GRANULARIZE,
            cells=tuple({"size": s, "standard": "", "ceiling": False} for s in sizes),
        )
    read = [(s, standard_for(CellRef(capability_class, s))) for s in sizes]
    cells = _cells_view(read)
    _chosen, standard = more_demanding(read)
    # every cell read that is as demanding as the one applied is named: "the XS and S cells"
    named = [sz for sz, st in read if _demand(st) == _demand(standard)]
    cell = f"{capability_class} {' and '.join(named)}"
    stop: Entry | None = None
    if standard is None or standard.ceiling:
        ceiling = standard is not None
        stop = Entry(
            STOP_NO_PROVEN_STANDARD,
            (
                f"the {cell} {_cells(named)} standard is an S3 ceiling — the commits' own tests, which "
                "a ticket never carries — so it licenses nothing"
                if ceiling
                else f"no context standard is proven for the {cell} {_cells(named, possessive=False)}"
            )
            + ": it is not built. Measure the cell, or an approver may fund one calibration "
            "build, which never opens a pull request",
            reason_code=REASON_CEILING if ceiling else REASON_NONE,
            standard=standard,
            cells=cells,
        )
    elif standard.base == BASE_S1 and missing_slots:
        stop = Entry(
            STOP_NEEDS_CONTEXT,
            f"the {cell} {_cells(named)} standard is {standard.arm}, which needs {NEEDS[BASE_S1]}; "
            f"missing: {', '.join(missing_slots)}",
            reason_code=BASE_S1,
            needs=tuple(missing_slots),
            standard=standard,
            cells=cells,
        )
    elif standard.base == BASE_S2 and not person_test:
        stop = Entry(
            STOP_NEEDS_CONTEXT,
            f"the {cell} {_cells(named)} standard is {standard.arm}, which needs {NEEDS[BASE_S2]}",
            reason_code=BASE_S2,
            needs=("a failing test",),
            standard=standard,
            cells=cells,
        )
    if stop is not None:
        if calibration is not None and stop.code in CALIBRATABLE:
            return Entry(
                standard=standard,
                cells=cells,
                calibration=calibration,
                reason=f"calibration build funded by {calibration.approver}: "
                f"{calibration.reason} (answers {stop.code})",
                reason_code=stop.code,
            )
        return stop
    assert standard is not None  # every path without one stopped above
    if require_signed_cell and not standard.signed:
        if not override_by:
            return Entry(
                STOP_UNSIGNED_CELL,
                f"the {cell} {_cells(named)} standard {standard.arm} is proven but has no active "
                "sign-off: it is not built. A second person signs the cell, or an approver's "
                "named override licenses this one run (it lifts only the sign-off)",
                reason_code=STOP_UNSIGNED_CELL,
                standard=standard,
                cells=cells,
            )
        return Entry(standard=standard, cells=cells, override_by=override_by)
    return Entry(standard=standard, cells=cells)


# --- the licence of a build -------------------------------------------------------------


@dataclass(frozen=True)
class Licence:
    """What licensed (or refused) a delivery: the cell read, its standard, and the stop."""

    code: str
    reason: str
    cell: CellRef
    standard: Standard | None = None
    estimate: str = ""
    measured: str = ""

    @property
    def licensed(self) -> bool:
        return not self.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "cell": self.cell.to_dict(),
            "standard": self.standard.to_dict() if self.standard is not None else None,
            "estimate": self.estimate,
            "measured": self.measured,
        }


def licensing_rungs(
    capability_class: str,
    size: str,
    rungs: Iterable[tuple[str, str]],
    *,
    standard_for: StandardFor,
) -> list[tuple[str, str]]:
    """The ``(builder, model)`` rungs whose own cell at ``size`` licenses delivery — the
    class × size × builder × model projection, never one that pools models."""
    out: list[tuple[str, str]] = []
    for builder, model in rungs:
        std = standard_for(CellRef(capability_class, size, builder, model))
        if std is not None and std.licenses:
            out.append((builder, model))
    return out


def own_cell_licence(
    *,
    capability_class: str,
    estimate: str,
    measured: str,
    builder: str,
    model: str,
    standard_for: StandardFor,
) -> Licence:
    """The delivered change's OWN cell — its class, the size tier of the build's churn and
    the final rung's builder and model — must license delivery (ADR-0025 item 12). A change
    larger than its estimate whose own cell does not license it stops
    ``size_exceeds_licence``; any other unlicensed cell stops ``cell_not_licensed``."""
    cell = CellRef(capability_class, measured, builder, model)
    std = standard_for(cell)
    if std is not None and std.licenses:
        return Licence("", "", cell, std, estimate, measured)
    larger = (
        estimate in SIZE_TIER_NAMES
        and measured in SIZE_TIER_NAMES
        and SIZE_TIER_NAMES.index(measured) > SIZE_TIER_NAMES.index(estimate)
    )
    what = "no standard" if std is None else f"only {std.arm}, a ceiling"
    if larger:
        return Licence(
            STOP_SIZE_EXCEEDS_LICENCE,
            f"the change built is {measured} (its churn) where the item was estimated "
            f"{estimate}, and the {capability_class} {measured} cell for {builder}:{model} has "
            f"{what}: no pull request",
            cell,
            std,
            estimate,
            measured,
        )
    return Licence(
        STOP_CELL_NOT_LICENSED,
        f"the delivered change's own cell ({capability_class} {measured}, {builder}:{model}) "
        f"has {what}: no pull request",
        cell,
        std,
        estimate,
        measured,
    )


@dataclass(frozen=True)
class Readers:
    """The three readers one run is given, bound once before any build."""

    standard_for: StandardFor
    agreement_passed: bool = False
    arm_readings: Callable[[CellRef], tuple[ArmReading, ...]] = field(default=lambda cell: ())


def gate_for(
    item: BacklogItem,
    readiness: Readiness,
    readers: Readers,
    *,
    person_test: bool = False,
    calibration: Calibration | None = None,
    require_signed_cell: bool = False,
    override_by: str = "",
) -> Entry:
    """:func:`decide_entry` for one backlog item and its readiness — the ONE call the loop's
    pre-build check and the intake's ticket feedback both make, so the ticket, the intake
    row and the factory item name the same stop."""
    return decide_entry(
        capability_class=item.capability_class,
        size=item.size_estimate,
        standard_for=readers.standard_for,
        agreement_passed=readers.agreement_passed,
        missing_slots=[g.slot for g in readiness.blocking_gaps],
        person_test=person_test,
        calibration=calibration,
        require_signed_cell=require_signed_cell,
        override_by=override_by,
    )


def bind(repo: str) -> Readers:
    """The seams bound to ``repo`` — what the worker and the intake poll hand the gate."""
    return Readers(
        standard_for=lambda cell: standard_for(repo, cell),
        agreement_passed=points_agreement_passed(repo),
        arm_readings=lambda cell: arm_readings_for(repo, cell),
    )


__all__ = [
    "BASE_S1",
    "BASE_S2",
    "BASE_S3",
    "CALIBRATABLE",
    "CERTIFYING_BASES",
    "ITEM_SIZES",
    "MODIFIER_LOOP",
    "NEEDS",
    "OVERRIDABLE",
    "REASON_CEILING",
    "REASON_NONE",
    "SIZE_GRANULARIZE",
    "SIZE_UNSIZED",
    "STOP_CALIBRATION_BUILD",
    "STOP_CELL_NOT_LICENSED",
    "STOP_GRANULARIZE",
    "STOP_NEEDS_CONTEXT",
    "STOP_NOT_LICENSED",
    "STOP_NO_PROVEN_STANDARD",
    "STOP_SIZE_EXCEEDS_LICENCE",
    "STOP_UNSIGNED_CELL",
    "STOP_UNSIZED",
    "ArmReading",
    "Calibration",
    "CellRef",
    "Entry",
    "Licence",
    "Readers",
    "Standard",
    "StandardFor",
    "arm_readings_for",
    "bind",
    "decide_entry",
    "gate_for",
    "licensing_rungs",
    "more_demanding",
    "next_size",
    "own_cell_licence",
    "points_agreement_passed",
    "sizes_to_read",
    "standard_for",
]
