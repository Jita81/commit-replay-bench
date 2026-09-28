"""The factory's entry-gate readers, bound to the store's registered readings (ADR-0026 item 8).

The factory's gate (:func:`crb.factory.standard.gate_for`) is given three readers, bound once per
run before any build: a cell's proven context standard, its arms' readings for the ticket comment,
and whether the points-to-churn agreement has passed. This module binds the first two to
routing.v2's registered readings (``crb.core.reading``, ``POST /readings``) on ONE apparatus,
class-set version, checks arm and posture class — the repository's own checks arm and the
deployment's posture class — and marks a standard signed only when an active sign-off of its
cell was made on that arm, class-set version, reading and apparatus, read through the one
sign-off reader, which lifts nothing from a broken chain (P-336).

Navigation
----------
What it is:   The server-side binding of the factory entry gate's readers to the store: the
              one place a factory cell (class × size, or a licence's class × size × builder
              × model × provider × arm) is answered from the registered readings.
What it does: Reads every registered reading of the repository and the ledger's rows once;
              for a cell, evaluates the readings registered on a cell of that class and size
              (and, for a licence, that builder, model and provider) at the current apparatus
              and the global class set, on the repository's checks arm and the deployment's posture
              class, and answers the latest proven standard (or its ``S3`` ceiling) as the
              factory's :class:`~crb.factory.standard.Standard`, signed only by an active
              sign-off bound to its arm, class-set version and reading; a licence read of an
              arm answers only a standard of that arm. The arms' look states feed the ticket
              comment; ``forward_states`` serves each ceiling's forward reading with its n.
How:          ``readers_in`` / ``bind_readers`` → one read of readings, rows and sign-offs →
              closures over them; ``crb.core.reading.outcomes_for_cell`` per matching reading cell →
              ``latest_outcome`` → ``Standard``.
Layer:        server — docs/ARCHITECTURE.md#41-c4-level-2--containers
ADRs:         docs/adr/0026-the-context-standard.md (items 2, 6 and 8),
              docs/adr/0025-routing-v2.md (the one apparatus a reading counts)
Works with:   src/crb/factory/standard.py (the gate, ``Readers``, ``CellRef``),
              src/crb/core/reading.py (the look rule and the outcome),
              src/crb/server/routes/readings.py (``load_readings``, ``standard_for``),
              src/crb/server/prevention_state.py (``current_checks_arm``),
              src/crb/server/posture_view.py (``deployment_posture_class``),
              src/crb/server/worker.py (binds it once per run and per intake pass),
              src/crb/server/routes/factory.py (the task preview, calibration and polls)
Tested by:    tests/test_factory_standard_binding.py,
              tests/test_governed_delivery_e2e.py, tests/test_forward_reading_e2e.py
Touch when:   never for a new repository; a new scope a reading counts on (bind it here,
              beside the checks arm and the posture class); the sign-off's binding changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from crb.core.capability import WILDCARD
from crb.core.context_arm import BASE_S2
from crb.core.ledger import GradeRow
from crb.core.reading import (
    OUTCOME_CEILING,
    OUTCOME_STANDARD,
    Reading,
    ReadingOutcome,
    evaluate,
    latest_outcome,
    outcomes_for_cell,
)
from crb.core.signoff import SignoffRecord, active_signoffs
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.core.version import APPARATUS_VERSION
from crb.factory.standard import ArmReading, CellRef, Readers, Standard, points_agreement_passed
from crb.server.routes.readings import load_readings
from crb.server.routes.signoffs import load_signoff_records
from crb.store.ledger import rows_in


def _matches(reading_cell: Mapping[str, str], cell: CellRef) -> bool:
    """A reading's (full) cell answers a factory cell of the same class and size — and, for a
    licence read, of the same builder, model and provider (P-340)."""
    if reading_cell.get("capability_class") != cell.capability_class:
        return False
    if reading_cell.get("size") != cell.size:
        return False
    if cell.builder and reading_cell.get("builder", "") != cell.builder:
        return False
    if cell.provider and reading_cell.get("provider", "") != cell.provider:
        return False
    return not (cell.model and reading_cell.get("model", "") != cell.model)


def outcome_for(
    readings: Sequence[Reading],
    rows: Sequence[GradeRow],
    *,
    repo: str,
    cell: CellRef,
    checks_arm: str,
    posture_class: str,
    apparatus: str = APPARATUS_VERSION,
    taxonomy: str = GLOBAL_CLASS_SET,
) -> ReadingOutcome | None:
    """The reading that speaks for ``cell`` (a proven standard over a ceiling over one still
    reading, the latest registration breaking ties), over every reading registered on a cell
    that matches it, at one apparatus, class-set version, checks arm and posture class."""
    outcomes: list[ReadingOutcome] = []
    seen: set[str] = set()
    for r in readings:
        if r.repo != repo or not _matches(r.cell, cell) or r.cell_key in seen:
            continue
        seen.add(r.cell_key)
        outcomes += outcomes_for_cell(
            readings,
            rows,
            repo=repo,
            cell=r.cell,
            apparatus=apparatus,
            taxonomy=taxonomy,
            checks_arm=checks_arm,
            posture_class=posture_class,
        )
    return latest_outcome(outcomes)


def standard_from(outcome: ReadingOutcome | None, *, signed: bool) -> Standard | None:
    """The factory's view of an outcome: the standard arm (or the ``S3`` ceiling), or
    ``None`` when no certifying arm delivered and no ceiling was reached."""
    if outcome is None or outcome.state not in (OUTCOME_STANDARD, OUTCOME_CEILING):
        return None
    arm = outcome.standard or (outcome.chain[-1] if outcome.chain else "")
    if not arm:
        return None
    return Standard(arm=arm, signed=signed, reading_id=outcome.reading.reading_id)


def arm_readings_of(outcome: ReadingOutcome | None) -> tuple[ArmReading, ...]:
    """Every arm of the speaking reading, as the ticket comment quotes it."""
    if outcome is None:
        return ()
    out = []
    for a in outcome.arms.values():
        ci = a.look.ci
        out.append(
            ArmReading(
                arm=a.arm,
                state=a.state,
                n=a.look.counted,
                clean=a.look.clean,
                ci_low=round(ci.low, 4),
                ci_high=round(ci.high, 4),
            )
        )
    return tuple(out)


#: ``(cell, arm, reading_id) -> bool`` — whether an active sign-off covers the standard.
SignedFn = Callable[[CellRef, str, str], bool]


def signed_by(
    records: Sequence[SignoffRecord],
    cell: CellRef,
    *,
    arm: str,
    reading_id: str,
    checks_arm: str,
    posture_class: str,
    apparatus: str = APPARATUS_VERSION,
    taxonomy: str = GLOBAL_CLASS_SET,
) -> bool:
    """An active, untampered sign-off covers ``cell``'s standard only when it was made on that
    arm, class-set version and reading (ADR-0026 item 6), on this apparatus (a record with no
    apparatus stamp lifts nothing — GOV-6), on the same checks arm and posture class, and its
    scope names the cell's class and size (or ``*``). Pure: the records are read once."""
    for rec in active_signoffs(records).values():
        if rec.capability_class not in (cell.capability_class, WILDCARD):
            continue
        if rec.size not in (cell.size, WILDCARD):
            continue
        stamped = {v.strip() for v in rec.apparatus_version.split(",") if v.strip()}
        if apparatus not in stamped:
            continue
        if (rec.context_arm, rec.taxonomy, rec.reading_id) != (arm, taxonomy, reading_id):
            continue
        if rec.arm != checks_arm:
            continue
        if rec.posture_class and rec.posture_class != posture_class:
            continue
        return True
    return False


def readers_over(
    readings: Sequence[Reading],
    rows: Sequence[GradeRow],
    *,
    repo: str,
    checks_arm: str,
    posture_class: str,
    signed: SignedFn | None = None,
    agreement_passed: bool = False,
) -> Readers:
    """The gate's readers over readings and rows already read (pure: the tests' seam)."""

    def outcome(cell: CellRef) -> ReadingOutcome | None:
        return outcome_for(
            readings,
            rows,
            repo=repo,
            cell=cell,
            checks_arm=checks_arm,
            posture_class=posture_class,
        )

    def standard_for(cell: CellRef) -> Standard | None:
        o = outcome(cell)
        std = standard_from(o, signed=False)
        if std is None:
            return None
        if cell.arm and std.arm != cell.arm:
            return None  # a licence read asks about THAT arm, and no other
        is_signed = bool(signed(cell, std.arm, std.reading_id)) if signed is not None else False
        return Standard(arm=std.arm, signed=is_signed, reading_id=std.reading_id)

    return Readers(
        standard_for=standard_for,
        agreement_passed=agreement_passed,
        arm_readings=lambda cell: arm_readings_of(outcome(cell)),
    )


def forward_states(session: Session, repo: str) -> dict[str, dict[str, Any]]:
    """Each ceiling's forward reading, keyed by the ceiling's reading id (ADR-0026 items 4 and
    8): the latest registered forward reading promoting it, evaluated over the repository's
    rows — its id, rule, look state, the tickets it counted and the clean ones, the tickets
    enrolled, the next look and the tickets still needed to it."""
    readings = load_readings(session, repo)
    forwards = [r for r in readings if r.prospective and r.promotes]
    if not forwards:
        return {}
    rows = rows_in(session, repo)
    out: dict[str, dict[str, Any]] = {}
    for r in forwards:  # registration order: a later forward reading of one ceiling wins
        arm = evaluate(r, rows).arms.get(BASE_S2)
        if arm is None:
            continue
        out[r.promotes] = {
            "reading_id": r.reading_id,
            "rule": r.rule,
            "registered_at": r.registered_at,
            "state": arm.state,
            "counted": arm.look.counted,
            "clean": arm.look.clean,
            "enrolled": len(r.pool),
            "next_look": arm.look.next_look,
            "needed": arm.look.needed,
        }
    return out


def readers_in(session: Session, repo: str, *, checks_arm: str, posture_class: str) -> Readers:
    """The gate's readers for ``repo``, read ONCE in ``session`` (the pre-run map): its
    registered readings, its rows and its sign-offs — none when the sign-off chain is broken."""
    readings = load_readings(session, repo)
    # the ONE sign-off reader (P-336): a broken chain, or a row the audit trail names that
    # the chain lacks, lifts nothing — never a per-row filter of its own
    records = load_signoff_records(session, repo)
    rows = rows_in(session, repo)

    def signed(cell: CellRef, arm: str, reading_id: str) -> bool:
        return signed_by(
            records,
            cell,
            arm=arm,
            reading_id=reading_id,
            checks_arm=checks_arm,
            posture_class=posture_class,
        )

    return readers_over(
        readings,
        rows,
        repo=repo,
        checks_arm=checks_arm,
        posture_class=posture_class,
        signed=signed,
        agreement_passed=points_agreement_passed(repo),
    )


def bind_readers(
    factory: sessionmaker[Session],
    repo: str,
    *,
    checks_arm: str,
    posture_class: str,
) -> Readers:
    """:func:`readers_in` in a session of its own — the worker's binding, once per run."""
    with factory() as s:
        return readers_in(s, repo, checks_arm=checks_arm, posture_class=posture_class)


__all__ = [
    "arm_readings_of",
    "bind_readers",
    "forward_states",
    "outcome_for",
    "readers_in",
    "readers_over",
    "signed_by",
    "standard_from",
]
