"""``/capability-map``, ``/routes`` and ``/failure-split`` — what the ledger licenses,
per cell, honestly.

All three routes are pure reads: the repo's rows come out of the store as
:class:`~crb.core.ledger.GradeRow` (so a false-Q1 row that bypassed the write path
refuses to load and the request answers ``409 false_q1_refused`` — the map is never
computed over untrusted rows), are reduced by
:func:`crb.core.capability.build_capability_map` under the ONE routing rule, and
the active human sign-offs are overlaid at read time
(:func:`crb.core.signoff.apply_signoffs_to_map`, which re-checks false-Q1 = 0).

The repo's negative-controls verdict is ALWAYS evaluated here
(:func:`crb.server.routes.oracle.latest_controls_verdict` — the same latest report
``/oracle/{repo}/controls`` serves, or ``unmeasured`` when there is none), so a
cell can never reach ``deliver`` on the product surface while the gate failed, was
never run, or exercised fewer than half its controls (ADR-0003 amendment). Every
cell and decision carries the ``failure_kind`` split and ``model_point`` next to
the all-rows point, and the decision's ``reason_code``.

Honest-empty: only MEASURED cells are returned. A (class × size) the ledger has
never seen is absent — the UI renders absence as ``NOT_YET_MEASURED`` — and
``summary.trusted_autonomy_coverage`` is ``null`` until the repo has a change
profile to weight the cells by.

Navigation
----------
What it is:   The ``/capability-map``, ``/routes`` and ``/failure-split`` route module — the
              product's central read: what the ledger licenses per cell.
What it does: Loads the repo's rows as ``GradeRow`` (a false-Q1 row refuses to load →
              409), filters to one mode, one apparatus (never pooled by default; the
              default ``current`` counts rows measured here only, never imported ones) and one
              ``checks`` arm (never pooled at all — the repository's own by default),
              reduces them under the ONE routing rule with the repo's latest controls
              verdict and task-level oracle scores, overlays active sign-offs at read time,
              and returns only MEASURED cells — absence is honest-empty; every cell and the
              map carry their economics (known counts, t intervals, apparatus — F35).
How:          ``rows_for_mode`` → ``rows_for_apparatus`` → ``rows_for_arm`` → ``signed_map``
              (= ``build_capability_map`` + ``apply_signoffs_to_map``) → ``cell_out`` per
              measured cell; ``parse_by`` maps the ``?by=`` aliases onto ``CELL_FIELDS``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/capability.py (``build_capability_map``, ``CapabilityCell`` — its
              ``economics`` and the map's come from src/crb/core/economics.py),
              src/crb/core/routing.py (``DEFAULT_POLICY``, ``ControlsVerdict``),
              src/crb/server/routes/oracle.py (``latest_controls_verdict`` /
              ``oracle_by_task`` — the one source shared with sign-off),
              src/crb/server/routes/signoffs.py (``load_signoff_records`` for the overlay),
              src/crb/server/schemas_capability.py (the response shapes),
              src/crb/server/factory_state.py (``delivery_counts`` — the factory chain's
              pull requests per cell, served as ``n_delivered`` / ``n_merged``),
              ui/src/screens/Capability (the map screen),
              docs/API.md#capability-routing-forecast-sign-off
Tested by:    tests/test_server_routes_capability.py, tests/test_server_routes_signoffs.py,
              tests/test_checks_pooling.py
Touch when:   never for a new repository; adding a cell-key field means ``BY_ALIASES`` here,
              ``CELL_FIELDS`` in src/crb/core/ledger.py, the schema and the UI type; changing
              the default ``mode`` / ``apparatus`` filter is a claims decision
              (docs/EVIDENCE-AND-CLAIMS.md#5-the-legacy-belt-caveat-on-the-census-ledger).
Claims:       A ``deliver`` cell here is the routing rule's output over measured rows with
              the controls gate applied — a licence to auto-deliver THAT cell, nothing wider
              (docs/EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session, sessionmaker

from crb.core.capability import (
    PROJECTION_CELL,
    PROJECTION_CLASS_SIZE,
    CapabilityCell,
    CapabilityMap,
    RepoChangeProfile,
    build_capability_map,
    trusted_autonomy_coverage,
)
from crb.core.checks import ARMS
from crb.core.context_arm import arms_present, is_arm
from crb.core.economics import Economics, fold_economics
from crb.core.ledger import (
    CELL_FIELDS,
    GradeRow,
    failure_split,
    rows_for_checks,
    rows_measured_here,
)
from crb.core.reading import Reading, budget_spent, cell_error_budget
from crb.core.routing import DEFAULT_POLICY, ROUTE_DELIVER, ControlsVerdict
from crb.core.signoff import apply_signoffs_to_map
from crb.core.spec import SIZE_TIER_NAMES
from crb.core.taxonomy import GLOBAL_CLASS_SET, is_class_set_version
from crb.core.version import APPARATUS_VERSION
from crb.server.auth import ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import DeliveryCounts, FactoryHome, delivery_counts_matching
from crb.server.posture_view import deployment_posture_class
from crb.server.prevention_state import current_checks_arm
from crb.server.routes.oracle import latest_controls_verdict, oracle_by_task, verdict_dict
from crb.server.routes.readings import (
    ARM_STANDARD,
    load_readings,
    reading_book,
    rows_on_standard_arms,
)
from crb.server.routes.repos import cached_profile, get_repo_or_404
from crb.server.routes.signoffs import load_signoff_records
from crb.server.schemas import CapabilitySummary
from crb.server.schemas_capability import (
    CapabilityCellSplitOut,
    CapabilityMapWithControlsOut,
    ControlsVerdictOut,
    EconomicsOut,
    FailureSplitOut,
    FailureSplitResponse,
    RouteDecisionWithControlsOut,
    RoutesWithControlsResponse,
    RoutingPolicyWithControlsOut,
)
from crb.store import qualifications as store_qualifications
from crb.store.ledger import DbLedger, rows_in
from crb.store.models import Repo, Run

router = APIRouter(tags=["capability"])
_ERR = {"model": ErrorEnvelope}

#: ``?by=`` vocabulary (the CLI's ``--by`` aliases).
BY_ALIASES: dict[str, str] = {
    "class": "capability_class",
    "capability_class": "capability_class",
    "size": "size",
    "language": "language",
    "lang": "language",
    "model": "model",
    "builder": "builder",
    "provider": "provider",
    "step": "process_step",
    "process_step": "process_step",
}
DEFAULT_BY = "class,size"


def resolve_apparatus(apparatus: str) -> str:
    """``current`` (or empty) → :data:`APPARATUS_VERSION`; a named version as given."""
    return APPARATUS_VERSION if apparatus in ("", "current") else apparatus


def rows_for_apparatus(rows: Iterable[GradeRow], apparatus: str) -> list[GradeRow]:
    """ADR-0025 item 1 (superseding ADR-0015 §3): a reading has one apparatus. The map reads
    the CURRENT apparatus (``crb.core.version.APPARATUS_VERSION``) by default, or a named
    version as history; ``all`` is refused with 422 ``apparatus_pooling_refused`` naming the
    versions present — evidence expires with the apparatus and two are never pooled.

    ``current`` is also the reading every licensing gate uses (the delivery gate, the
    factory's cell routes), so it counts the rows THIS deployment measured only
    (:func:`crb.core.ledger.rows_measured_here`): an imported row stamped with the current
    apparatus is someone else's measurement and never routes a cell here (EI-2). A named
    version is a reader's view of history and includes imported rows."""
    rs = list(rows)
    if apparatus == "all":
        raise ApiError(
            422,
            "apparatus_pooling_refused",
            "a reading has one apparatus (ADR-0025 item 1): read the current one, or name a "
            "version to read it as history",
            detail={"versions": sorted({r.apparatus_version for r in rs})},
        )
    want = resolve_apparatus(apparatus)
    if apparatus in ("", "current"):
        return [r for r in rows_measured_here(rs) if r.apparatus_version == want]
    return [r for r in rs if r.apparatus_version == want]


#: ``?arm=standard`` (the default): each cell is read on ITS proven standard arm (see
#: :func:`crb.server.routes.readings.rows_on_standard_arms`). Any arm id selects that arm for
#: every cell; ``all`` is refused (ADR-0026 item 1).
DEFAULT_ARM = ARM_STANDARD


def _pooled(what: str, adr: str, values: Iterable[str]) -> ApiError:
    return ApiError(
        422,
        f"{what}_pooling_refused",
        f"a reading has one {what.replace('_', ' ')} ({adr}): name one",
        detail={"present": sorted({v for v in values if v})},
    )


def rows_for_arm_param(rows: Iterable[GradeRow], arm: str) -> list[GradeRow]:
    """ADR-0026 item 1: one context arm per reading. ``all`` → 422; an arm outside the
    grammar → 422. A row from before 2.4 carries no arm and is kept (it is read only at its
    own apparatus, as history, where mode still splits it)."""
    rs = list(rows)
    if arm == "all":
        raise _pooled("context_arm", "ADR-0026 item 1", (r.context_arm for r in rs))
    if arm == ARM_STANDARD:
        return rs  # resolved per cell by :func:`rows_on_standard_arms`
    if not is_arm(arm):
        raise ApiError(422, "validation_error", f"arm {arm!r} is outside the context-arm grammar")
    return [r for r in rs if r.context_arm == arm or (not r.context_arm and not r.taxonomy)]


def rows_for_taxonomy_param(rows: Iterable[GradeRow], taxonomy: str) -> list[GradeRow]:
    """ADR-0026 item 9: one class-set version per reading; ``all`` → 422. Rows from before
    2.4 carry none and are kept, as history."""
    rs = list(rows)
    if taxonomy == "all":
        raise _pooled("class_set", "ADR-0026 item 9", (r.taxonomy for r in rs))
    if not is_class_set_version(taxonomy):
        raise ApiError(422, "validation_error", f"taxonomy {taxonomy!r} is not a class-set version")
    return [r for r in rs if r.taxonomy == taxonomy or not r.taxonomy]


def apparatus_block(rows: Sequence[GradeRow], apparatus: str) -> dict[str, Any]:
    """What the map reads and what it holds as history (ADR-0025 item 1)."""
    read = resolve_apparatus(apparatus)
    others = [r for r in rows if r.apparatus_version != read]
    return {
        "current": APPARATUS_VERSION,
        "read": read,
        "superseded_rows": len(others),
        "superseded_versions": sorted({r.apparatus_version for r in others}),
    }


#: ``?posture=`` values beside a posture class: the deployment's own class (the default)
#: and the explicit pooled view.
POSTURE_DEPLOYMENT = "deployment"
POSTURE_ALL = "all"
#: The class a pre-2.3 row derives from its run's apparatus stamp (``legacy:<executor>``).
LEGACY_CLASS_PREFIX = "legacy:"
#: What a pre-2.3 row the HOST graded measured: the host's own environment against the
#: discovery baseline — the class it may be read with, and no other (provisioning did not
#: exist before 2.3, so never ``local/inplace/sealed``).
LEGACY_LOCAL_EQUIVALENT = "local/inplace/host-env"


def comparable_class(cls: str) -> str:
    """The class a row is compared as: its own, and ``legacy:local`` as
    :data:`LEGACY_LOCAL_EQUIVALENT`."""
    return LEGACY_LOCAL_EQUIVALENT if cls == LEGACY_CLASS_PREFIX + "local" else cls


@dataclass(frozen=True)
class PostureFilter:
    """What :func:`rows_for_posture` kept and why it left the rest out."""

    rows: list[GradeRow]
    posture_class: str
    excluded_posture_divergent: int = 0
    unqualified_posture: int = 0


def row_posture_class(row: GradeRow, legacy_executor_of: Callable[[str], str]) -> str:
    """A row's posture class: its label (apparatus 2.3 and later), else
    ``legacy:<executor>`` read from its run's apparatus stamp (never from the row)."""
    if row.posture_class:
        return row.posture_class
    return LEGACY_CLASS_PREFIX + (legacy_executor_of(row.run_id) or "local")


def rows_for_posture(
    rows: Iterable[GradeRow],
    posture: str,
    *,
    fingerprints: Callable[[Iterable[str]], Mapping[str, Mapping[str, str]]],
    legacy_executor_of: Callable[[str], str],
) -> PostureFilter:
    """ADR-0019 §8: posture is a filter, never a blend.

    * a row stamped before 2.3 whose run graded it under ``docker`` was graded against a
      baseline measured somewhere else: excluded from every rate, counted
      ``unqualified_posture``;
    * ``posture`` is a posture class (``docker/copy/sealed``): only that class's rows,
      and a ``legacy:local`` row only under ``local/inplace/host-env`` (the host graded it
      in its own environment);
    * ``all``: every class, pooled ONLY over tasks whose qualification fingerprints match
      in every class present — the rest are counted ``excluded_posture_divergent``. A
      legacy row has no fingerprint, so it is pooled only when every row reads as ONE
      class (``legacy:local`` with ``local/inplace/host-env``), never with another.
    """
    unqualified = 0
    classified: list[tuple[str, GradeRow]] = []
    for r in rows:
        cls = row_posture_class(r, legacy_executor_of)
        if cls == LEGACY_CLASS_PREFIX + "docker":
            unqualified += 1
            continue
        classified.append((cls, r))
    if posture != POSTURE_ALL:
        kept = [r for cls, r in classified if comparable_class(cls) == posture]
        return PostureFilter(kept, posture, unqualified_posture=unqualified)
    if len({comparable_class(cls) for cls, _ in classified}) <= 1:
        return PostureFilter(
            [r for _, r in classified], POSTURE_ALL, unqualified_posture=unqualified
        )
    present = sorted({cls for cls, _ in classified if not cls.startswith(LEGACY_CLASS_PREFIX)})
    fps = fingerprints(present) if len(present) > 1 else {}
    kept, divergent = [], 0
    for cls, r in classified:
        if cls.startswith(LEGACY_CLASS_PREFIX):
            divergent += 1  # a legacy row has no fingerprint to prove it invariant
            continue
        if len(present) == 1:
            kept.append(r)  # the one current class: nothing to be invariant against
            continue
        mine = fps.get(cls, {}).get(r.task_id)
        if mine and all(fps.get(c, {}).get(r.task_id) == mine for c in present):
            kept.append(r)
        else:
            divergent += 1
    return PostureFilter(kept, POSTURE_ALL, divergent, unqualified)


def legacy_executor_lookup(session: Session) -> Callable[[str], str]:
    """``run_id → executor`` from each run's apparatus stamp (cached per request) — how a
    pre-2.3 row, which carries no posture of its own, is placed (ADR-0019 §10)."""
    cache: dict[str, str] = {}

    def of(run_id: str) -> str:
        if run_id not in cache:
            run = session.get(Run, run_id) if run_id else None
            executor = ""
            if run is not None:
                stamp = dict(run.apparatus_json or {}).get("executor") or {}
                executor = str(stamp.get("executor", "") if isinstance(stamp, Mapping) else stamp)
            cache[run_id] = executor
        return cache[run_id]

    return of


def filter_posture(
    session: Session, repo: str, rows: Iterable[GradeRow], posture: str, settings: object
) -> PostureFilter:
    """:func:`rows_for_posture` against the store: ``deployment`` (the default) is the
    deployment's own posture class; fingerprints and legacy executors come from the
    records."""
    wanted = (
        deployment_posture_class(settings, session.get(Repo, repo))
        if posture in ("", POSTURE_DEPLOYMENT)
        else posture
    )
    return rows_for_posture(
        rows,
        wanted,
        fingerprints=lambda classes: store_qualifications.latest_fingerprints(
            session, repo, classes
        ),
        legacy_executor_of=legacy_executor_lookup(session),
    )


#: ``?checks=`` beside an arm (``crb.core.checks.ARMS``): the repository's own arm, the
#: default. There is no pooled view (ADR-0024).
CHECKS_CURRENT = "current"
#: The ``checks`` query's vocabulary, as a pattern.
CHECKS_PATTERN = "^(" + "|".join((CHECKS_CURRENT, *ARMS)) + ")$"


def rows_for_arm(
    factory: sessionmaker[Session], repo: str, rows: Iterable[GradeRow], checks: str
) -> list[GradeRow]:
    """ADR-0024: a row graded with the format step or belt 6 on is never counted in a cell
    with one graded without. ``current`` (the default) reads the arm the repository's next
    run grades under — the arm its cells license delivery in; an arm word selects that one."""
    arm = current_checks_arm(factory, repo) if checks == CHECKS_CURRENT else checks
    return rows_for_checks(rows, arm)


def rows_for_mode(rows: Iterable[GradeRow], mode: str) -> list[GradeRow]:
    """Sighted and blind attempts are different measurements of the same task — the
    oracle is visible in one and held out in the other — and ``mode`` is not part of
    the cell key, so a map must never pool them: a blind budget ladder diluted every
    sighted cell on the live stack (2026-09-15). Default ``sighted``; ``blind`` for the
    blind map; ``all`` only when a reader asks for the pooled view explicitly."""
    rs = list(rows)
    if mode == "all":
        return rs
    return [r for r in rs if r.mode == mode]


def parse_by(by: str | None) -> tuple[str, ...]:
    """``"class,size,language"`` → the cell-key projection, in :data:`CELL_FIELDS` order."""
    tokens = [t.strip().lower() for t in (by or DEFAULT_BY).split(",") if t.strip()]
    fields: list[str] = []
    for t in tokens:
        if t not in BY_ALIASES:
            raise ApiError(
                422,
                "validation_error",
                f"unknown by field {t!r}",
                detail={"allowed": sorted(set(BY_ALIASES))},
            )
        f = BY_ALIASES[t]
        if f not in fields:
            fields.append(f)
    if not fields:
        raise ApiError(422, "validation_error", "by needs at least one field")
    return tuple(f for f in CELL_FIELDS if f in fields)


def signed_map(
    rows: Sequence[GradeRow],
    projection: Sequence[str],
    session: Session,
    repo: str,
    *,
    controls: ControlsVerdict | None = None,
    arm: str = DEFAULT_ARM,
    taxonomy: str = GLOBAL_CLASS_SET,
) -> tuple[CapabilityMap, int]:
    """The projection's map of ONE context arm and class-set version (``arm`` /
    ``taxonomy``; the rows are filtered again here, so a caller that passes several never
    pools them), routed on the repo's registered readings — evaluated over ALL the repo's rows,
    since a hierarchy reads its arms together — with the per-task oracle scores at the rows'
    apparatus and the active sign-offs overlaid; returns the number of sign-off records
    considered. ``controls`` is the verdict every cell is routed under (``None`` =
    unmeasured)."""
    records = load_signoff_records(session, repo)
    book = reading_book(session, repo, rows_in(session, repo))
    rs = rows_for_taxonomy_param(rows_for_arm_param(rows, arm), taxonomy)
    if arm == ARM_STANDARD:
        rs = rows_on_standard_arms(rs, projection, book)
    versions = sorted({r.apparatus_version for r in rs})
    apparatus = versions[0] if len(versions) == 1 else APPARATUS_VERSION
    cmap = build_capability_map(
        rs,
        projection=projection,
        policy=DEFAULT_POLICY,
        controls=controls,
        oracle_by_task=oracle_by_task(session, repo, apparatus=apparatus),
        readings=book,
    )
    return apply_signoffs_to_map(cmap, records, repo=repo), len(records)


def controls_out(verdict: ControlsVerdict) -> ControlsVerdictOut:
    """The verdict plus its ``state`` word under the default routing policy."""
    return ControlsVerdictOut(**verdict_dict(verdict, DEFAULT_POLICY))


def split_out(c: CapabilityCell) -> FailureSplitOut:
    """The cell's non-clean rows by ``failure_kind`` (lint counts come from the stats)."""
    return FailureSplitOut(
        builder_red=c.n_builder_red,
        budget=c.n_budget,
        protocol=c.n_protocol,
        harness=c.n_harness,
        outage=c.n_outage,
        disqualified=c.n_disqualified,
        lint=c.stats.n_lint if c.stats is not None else 0,
        lint_evaluated=c.stats.n_lint_evaluated if c.stats is not None else 0,
        api=c.stats.n_api if c.stats is not None else 0,
    )


def economics_out(e: Economics) -> EconomicsOut:
    """F35: the core's economics fold, re-typed (no arithmetic here)."""
    return EconomicsOut.model_validate(e.to_dict())


def cell_out(
    c: CapabilityCell,
    deliveries: Mapping[tuple[str, str], DeliveryCounts] | None = None,
    readings: Sequence[Reading] = (),
) -> CapabilityCellSplitOut:
    """A MEASURED cell as the API serves it: key, stats, decision, split, tier, apparatus —
    and, from the factory evidence chain, how many pull requests were delivered from the
    cell and how many merged (B-9 / F30; counts, never a rate)."""
    # only measured cells are serialised, and every measured cell carries its economics
    assert c.stats is not None and c.decision is not None and c.economics is not None
    s = c.stats
    n_delivered, n_merged = delivery_counts_matching(
        deliveries or {}, c.key.capability_class, c.key.size
    )
    key: dict[str, Any] = {**c.key.to_dict(), **v2_cell_fields(c, readings)}
    return CapabilityCellSplitOut(
        n_delivered=n_delivered,
        n_merged=n_merged,
        **key,
        label=c.label,
        n=s.n,
        clean=s.clean,
        disqualified=s.disqualified,
        errors=s.errors,
        rows=c.rows,
        rows_imported=c.rows_imported,
        repos=c.repos,
        point=round(s.point, 4),
        ci_low=round(s.ci.low, 4),
        ci_high=round(s.ci.high, 4),
        sigma=None if c.sigma is None else round(c.sigma, 4),
        false_q1=s.false_q1,
        cost_usd_mean=round(s.cost_usd_mean, 6),
        latency_s_mean=round(s.latency_s_mean, 3),
        cost_known=c.cost_known,
        latency_known=c.latency_known,
        # the strength the cell was ROUTED under: the repo's task-level mutation scores
        # (the sign-off's evidence), else the rows' own
        oracle_strength_mean=(
            None if c.decision.oracle_strength is None else round(c.decision.oracle_strength, 4)
        ),
        route=c.route,
        reason=c.decision.reason,
        reason_code=c.decision.reason_code,
        verification_tier=c.verification_tier or "automated-pass",
        apparatus_versions=list(s.apparatus_versions),
        posture_ids=list(s.posture_ids),
        belt_set=",".join(c.belt_sets),
        belt_sets=list(c.belt_sets),
        n_builder_red=s.n_builder_red,
        n_budget=s.n_budget,
        n_protocol=s.n_protocol,
        n_harness=s.n_harness,
        n_outage=s.n_outage,
        n_tasks=s.n_tasks,
        n_disqualified=s.n_disqualified,
        n_lint=s.n_lint,
        n_lint_evaluated=s.n_lint_evaluated,
        n_api=s.n_api,
        model_n=s.model_n,
        model_point=None if c.model_point is None else round(c.model_point, 4),
        model_ci_low=None if c.model_point is None else round(s.model_ci.low, 4),
        model_ci_high=None if c.model_point is None else round(s.model_ci.high, 4),
        failure_split=split_out(c),
        checks_arm=s.checks_arm,
        economics=economics_out(c.economics),
    )


def v2_cell_fields(c: CapabilityCell, readings: Sequence[Reading] = ()) -> dict[str, Any]:
    """routing.v2's fields of a measured cell: its arm, class-set version and apparatus, the
    distinct-change counts, what its reading says about the arm, every shortfall, every arm
    of the reading, and the cell's standard ("no proven standard" is ``standard: null``)."""
    assert c.stats is not None and c.decision is not None
    s, d = c.stats, c.decision
    v = c.verdict
    first = d.shortfalls[0] if d.shortfalls else None
    reading = c.reading
    spent = (
        budget_spent(readings or [reading.reading], reading.reading.budget_key)
        if reading is not None
        else 0.0
    )
    standard = reading.standard if reading is not None and reading.standard else None
    ceiling = reading is not None and reading.ceiling
    chain_top = reading.chain[-1] if reading is not None and reading.chain else None
    label = (
        f"standard {standard}"
        if standard
        else f"ceiling {chain_top}, forward-unvalidated"
        if ceiling and chain_top
        else "no proven standard"
    )
    return {
        "context_arm": s.context_arm,
        "taxonomy": s.taxonomy,
        "apparatus_version": s.apparatus_version,
        "n_tasks_eligible": s.n_tasks_eligible,
        "task_clean": s.task_clean,
        "task_ci_low": round(s.task_ci.low, 4),
        "task_ci_high": round(s.task_ci.high, 4),
        "n_unsealed": s.n_unsealed,
        "look_state": d.look_state,
        "reading_id": d.reading_id,
        "counted": d.counted,
        "counted_clean": d.counted_clean,
        "counted_ci_low": round(v.ci.low, 4) if v is not None else 0.0,
        "counted_ci_high": round(v.ci.high, 4) if v is not None else 1.0,
        "needed": d.needed,
        "next_look": d.next_look,
        "oracle_scored_tasks": d.oracle_scored_tasks,
        "oracle_share": round(d.oracle_share, 4),
        "shortfalls": [x.to_dict() for x in d.shortfalls],
        "reading": None if reading is None else reading.to_dict(),
        "provenance": {k: list(v) for k, v in (c.provenance or {}).items()},
        "standard": {
            "standard": standard or (chain_top if ceiling else None),
            "ceiling": bool(ceiling and not standard),
            "label": label,
            "next": first.next if first is not None else "",
            "next_count": first.count if first is not None else 0,
            "budget": reading.reading.budget if reading is not None else cell_error_budget(),
            "spent": round(spent, 6),
        },
    }


def _distinct(rows: Sequence[GradeRow], field: str) -> list[str]:
    """The distinct values of a cell field over ``rows`` (sizes in tier order)."""
    values = {getattr(r, field) for r in rows}
    if field == "size":
        return [s for s in SIZE_TIER_NAMES if s in values]
    return sorted(v for v in values if v)


def _coverage(
    session: Session, repo: str, rows: Sequence[GradeRow], controls: ControlsVerdict
) -> tuple[float | None, float | None, int | None]:
    """TAC over the cached change profile; ``None`` everywhere when no profile exists."""
    cached = cached_profile(get_repo_or_404(session, repo))
    if cached is None:
        return None, None, None
    profile = RepoChangeProfile.from_dict(dict(cached["profile"]))
    cs_map, _ = signed_map(rows, PROJECTION_CLASS_SIZE, session, repo, controls=controls)
    summary = trusted_autonomy_coverage(profile, rows, cells=cs_map, policy=DEFAULT_POLICY)
    return round(summary.coverage, 4), round(summary.earned_coverage, 4), profile.n_commits


@router.get(
    "/capability-map",
    response_model=CapabilityMapWithControlsOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Measured cells of one repo under the routing rule + controls verdict, sign-offs overlaid",
)
def capability_map(  # noqa: PLR0917 — FastAPI dependencies + query params
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
    by: str | None = Query(default=None, max_length=128),
    mode: str = Query(default="sighted", pattern="^(sighted|blind|all)$"),
    apparatus: str = Query(default="current", max_length=32),
    posture: str = Query(default=POSTURE_DEPLOYMENT, max_length=64),
    checks: str = Query(default=CHECKS_CURRENT, pattern=CHECKS_PATTERN),
    arm: str = Query(default=DEFAULT_ARM, max_length=128),
    taxonomy: str = Query(default=GLOBAL_CLASS_SET, max_length=64),
) -> CapabilityMapWithControlsOut:
    del viewer
    get_repo_or_404(db, repo)
    projection = parse_by(by)
    every = list(DbLedger(factory).rows(repo=repo))
    by_mode = rows_for_apparatus(rows_for_mode(every, mode), apparatus)
    stamped = rows_for_taxonomy_param(rows_for_arm_param(by_mode, arm), taxonomy)
    pf = filter_posture(db, repo, rows_for_arm(factory, repo, stamped, checks), posture, settings)
    rows = pf.rows
    controls = latest_controls_verdict(db, repo, apparatus=resolve_apparatus(apparatus))
    cmap, n_signoffs = signed_map(
        rows, projection, db, repo, controls=controls, arm=arm, taxonomy=taxonomy
    )
    readings = load_readings(db, repo)
    cells = [c for c in cmap.cells if c.measured]
    deliveries = FactoryHome(settings.home, repo).delivery_counts()
    by_route = {route: len(cs) for route, cs in cmap.by_route().items()}
    # total_cells = the grid the projection spans over values SEEN in the rows, so the UI
    # can say "12 of 20 measured" without inventing cells the repo never produces.
    grid = 1
    for f in projection:
        grid *= max(1, len(_distinct(rows, f)))
    tac, earned, commits = _coverage(db, repo, rows, controls)
    return CapabilityMapWithControlsOut(
        repo=repo,
        by=list(projection),
        classes=_distinct(rows, "capability_class"),
        sizes=_distinct(rows, "size"),
        languages=_distinct(rows, "language"),
        models=_distinct(rows, "model"),
        cells=[cell_out(c, deliveries, readings) for c in cells],
        summary=CapabilitySummary(
            trusted_autonomy_coverage=tac,
            earned_coverage=earned,
            profile_commits=commits,
            total_cells=grid if rows else 0,
            measured_cells=len(cells),
            deliver_cells=sum(1 for c in cells if c.route == ROUTE_DELIVER),
            cells_by_route=by_route,
            n_total=sum(c.n for c in cells),
            rows=cmap.rows,
            false_q1_total=cmap.false_q1_total,
            apparatus_versions=list(cmap.apparatus_versions),
            signoffs_applied=n_signoffs,
            posture_class=pf.posture_class,
            excluded_posture_divergent=pf.excluded_posture_divergent,
            unqualified_posture=pf.unqualified_posture,
        ),
        policy=RoutingPolicyWithControlsOut(**cmap.policy.to_dict()),
        controls=controls_out(controls),
        economics=economics_out(fold_economics(rows)),
        arm=arm,
        arms=[a for a in arms_present(by_mode) if a],
        taxonomy=taxonomy,
        taxonomies=sorted({r.taxonomy for r in by_mode if r.taxonomy}),
        apparatus=apparatus_block(every, apparatus),
    )


@router.get(
    "/routes",
    response_model=RoutesWithControlsResponse,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Route decisions per (full) cell with reasons, reason codes, the controls verdict and the policy in force",
)
def routes(  # noqa: PLR0917 — FastAPI dependencies + query params
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    repo: str = Query(min_length=1, max_length=64),
    by: str | None = Query(default=None, max_length=128),
    mode: str = Query(default="sighted", pattern="^(sighted|blind|all)$"),
    apparatus: str = Query(default="current", max_length=32),
    posture: str = Query(default=POSTURE_DEPLOYMENT, max_length=64),
    checks: str = Query(default=CHECKS_CURRENT, pattern=CHECKS_PATTERN),
    arm: str = Query(default=DEFAULT_ARM, max_length=128),
    taxonomy: str = Query(default=GLOBAL_CLASS_SET, max_length=64),
) -> RoutesWithControlsResponse:
    del viewer
    get_repo_or_404(db, repo)
    projection = parse_by(by) if by else PROJECTION_CELL
    by_mode = rows_for_apparatus(rows_for_mode(DbLedger(factory).rows(repo=repo), mode), apparatus)
    stamped = rows_for_taxonomy_param(rows_for_arm_param(by_mode, arm), taxonomy)
    rows = filter_posture(
        db, repo, rows_for_arm(factory, repo, stamped, checks), posture, settings
    ).rows
    controls = latest_controls_verdict(db, repo, apparatus=resolve_apparatus(apparatus))
    cmap, _ = signed_map(rows, projection, db, repo, controls=controls, arm=arm, taxonomy=taxonomy)
    decisions: list[RouteDecisionWithControlsOut] = []
    for c in cmap.cells:
        if c.decision is None or c.stats is None:
            continue
        d = c.decision.to_dict()
        d["controls"] = None if c.decision.controls is None else verdict_dict(c.decision.controls)
        decisions.append(
            RouteDecisionWithControlsOut(
                **d,
                label=c.label,
                verification_tier=c.verification_tier or "automated-pass",
                apparatus_versions=list(c.stats.apparatus_versions),
                # ci_high arrives in ``d``: the decision itself carries both ends of its
                # interval now, so passing it again here would be a duplicate keyword
                belt_sets=list(c.belt_sets),
                model_n=c.model_n,
                model_point=None if c.model_point is None else round(c.model_point, 4),
                model_ci_low=None if c.model_point is None else round(c.stats.model_ci.low, 4),
                model_ci_high=None if c.model_point is None else round(c.stats.model_ci.high, 4),
                failure_split=split_out(c),
                rows_imported=c.rows_imported,
            )
        )
    return RoutesWithControlsResponse(
        repo=repo,
        by=list(projection),
        policy=RoutingPolicyWithControlsOut(**cmap.policy.to_dict()),
        decisions=decisions,
        controls=controls_out(controls),
        arm=arm,
        arms=[a for a in arms_present(by_mode) if a],
        taxonomy=taxonomy,
    )


@router.get(
    "/failure-split",
    response_model=FailureSplitResponse,
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="The failure_kind split (and both rates) over a repo's rows, or one run's",
)
def failure_split_route(  # noqa: PLR0917 — FastAPI dependencies + query params
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
    run_id: str = Query(default="", max_length=32),
    checks: str = Query(default=CHECKS_CURRENT, pattern=CHECKS_PATTERN),
) -> FailureSplitResponse:
    """``clean · builder_red · budget · protocol · harness`` (= n) + ``disqualified``
    over the repo's rows, or the run's when ``run_id`` is given, with the all-rows
    point and the model point side by side. An unknown ``run_id`` answers an empty
    split (n = 0), never an invented one. The repo-wide split reads one ``checks`` arm —
    the repository's own by default (ADR-0024), so its clean rate never blends two
    instruments beside per-arm cells; a run's split is its own rows, graded on the one arm
    the run resolved, and ``checks`` does not filter it."""
    del viewer
    get_repo_or_404(db, repo)
    rows = list(DbLedger(factory).rows(repo=repo, run_id=run_id or None))
    if not run_id:
        rows = rows_for_arm(factory, repo, rows, checks)
    split = failure_split(rows)
    return FailureSplitResponse(repo=repo, run_id=run_id, **split.to_dict())


__all__ = [
    "BY_ALIASES",
    "DEFAULT_BY",
    "cell_out",
    "controls_out",
    "economics_out",
    "parse_by",
    "router",
    "rows_for_arm",
    "signed_map",
    "split_out",
]
