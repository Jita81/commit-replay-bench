"""The governed loop, one backlog item end to end, every step evidenced.

    assess readiness ──operator work / a class a person tests / unsized──▶ routed_human
      │ THE ENTRY GATE (ADR-0026 item 8), before any spend, delivery on or off:
      │   the size rule (the estimate's cell and the next larger one) ──XL──▶ granularize
      │   no proven standard, or only an S3 ceiling ──▶ no_proven_standard
      │   missing what the standard arm needs ──▶ needs_context
      │   (an approver's calibration grant admits either as a calibration build)
      │   proven but unsigned, where a signed cell is required (ADR-0018's sign-off
      │   clause, on by default) ──▶ unsigned_cell
      │     (the ONLY clause ``deliver_override`` lifts — a second approver's, never the
      │     run's own actor's, never on a false-Q1 cell: a refused one is on the chain)
      │ an unsigned structural gap ──▶ not_ready
      │ delivery on, and no rung holds a licence at the item's size ──▶ not_licensed ($0)
      │ the capability map's route for the cell is read HERE, once, before any build
      ▼
    RED proof (authored test, or the test-first author rung) ──refused──▶ not_red
      ▼
    build ladder → grade (pack + ledger row, process_step=factory)
      ▼ not clean / disqualified ──▶ not_clean / disqualified
    review (independent identity, probes) → verdict RECORDED before any edit
      │ the required strength probe could not score the test (no waiver for its
      │ bytes) ──▶ oracle_not_scoreable (routed human; nothing pushed)
      ▼ accept_with_edit ──▶ rework: edit permitted → RED proof → build → grade
      │     │                 → a fresh verdict on the rebuilt change (nothing delivered)
      │     └─ a weak_oracle finding with no test author, or one that returns the
      │        same oracle ──▶ oracle_needs_strengthening (routed human; NO rebuild)
      ▼ reject / rework_exhausted / oracle_needs_strengthening ──▶ NO pull request
    a calibration build ──▶ calibration_build (NEVER a pull request)
    the delivered change's own cell (its measured size, the final rung's builder and
      │   model) must license it ──▶ size_exceeds_licence / cell_not_licensed
    deliver — ONLY an `accept` verdict reaches it (ADR-0021); OPT-IN, default OFF; fails
      │   closed on missing creds; gated on the route read at readiness (DL-038, DL-045),
      │   re-read on the measured cell when the change measures larger (GOV-2), which no
      │   override lifts (ADR-0026 item 8)
      ▼   ──▶ delivery_failed
    accepted

An item that already has an OPEN pull request from an earlier run (on the chain, no
merged/closed outcome) is carried to that pull request: an ``accept`` updates it (the lease
push, one pull request), any other final verdict CLOSES it with a comment naming the
verdict (:func:`crb.factory.delivery.close_pull_request`) — the product does not leave a
pull request open on a change its own review no longer stands behind.

Every arrow above appends to :class:`~crb.factory.evidence.FactoryEvidence`;
every stage emits :class:`~crb.observability.events.StepEvent` rows with
``stage="factory"``. Nothing here decides a verdict: the grader, the probes and
the reviewer do; the loop only sequences them and refuses to skip a step.

Navigation
----------
What it is:   The governed loop — one backlog item end to end, every step evidenced, no
              step skippable.
What it does: Sequences readiness and the entry gate (ADR-0026 item 8: an item is built only
              on its cell's proven context standard and with what that arm needs; an
              approver's calibration build never delivers; the override lifts only the
              sign-off clause, honoured only from a second approver and never on a false-Q1
              cell — GOV-1, GOV-4) — where the capability map's route for the item's cell is
              read once, before any build — → RED proof on the standard arm's oracle
              (authored or test-first rung) → build ladder, graded on the run's checks arm
              (GOV-3) → independent review (an unscoreable oracle with no approver's waiver
              for its bytes stops ``oracle_not_scoreable`` before any push) → rework (edit
              permitted only after a recorded verdict; bounded by ``max_rework``; a
              ``weak_oracle`` verdict never rebuilds against an unchanged oracle — DL-045
              rule 3) → optional delivery (default OFF, fails closed, gated on the delivered
              change's own licence and on that route — re-read on the measured cell when
              the change measures larger than its estimate, GOV-2 — and reached ONLY by an
              ``accept`` verdict — ADR-0021), turning every governed refusal into an
              ``ItemOutcome`` status rather than an exception; an open pull request an
              earlier run opened is updated on ``accept`` and closed, naming the verdict, on
              anything else; ``run_backlog`` requires a frozen, verifying backlog and records
              a blocked item explicitly when a dependency was not accepted. Emits a
              ``factory``-stage ``StepEvent`` per step.
How:          ``FactorySpec`` carries every collaborator; ``FactoryLoop.run_item`` walks the
              private ``_assess`` / ``_oracle`` / ``_prove`` / ``_build`` / ``_review`` /
              ``_deliver`` steps under a ``_Stop`` exception that maps to a status;
              ``_open_delivery`` reads the chain for the item's open pull request and
              ``_withdraw`` closes it.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0003-one-routing-rule.md (the route gate; amended 2026-09-19 and
              2026-09-27),
              docs/adr/0013-external-review-is-advisory-and-recorded.md (amended
              2026-09-21: a weak_oracle verdict never rebuilds against an unchanged oracle),
              docs/adr/0021-factory-review-before-delivery.md (review before delivery; only
              `accept` delivers; a later non-accept closes the open pull request),
              docs/adr/0018-a-signed-cell-licenses-delivery.md (the sign-off clause, default
              ON, and what an override may be claimed to mean),
              docs/adr/0026-the-context-standard.md (item 8: the clause stops before any
              spend; the override lifts it and nothing else)
Works with:   src/crb/factory/evidence.py (every arrow appends), src/crb/factory/readiness.py
              + src/crb/factory/testfirst.py + src/crb/factory/build.py +
              src/crb/factory/review.py + src/crb/factory/delivery.py (the steps, in order),
              src/crb/observability/events.py (``Emitter`` for the step events),
              src/crb/server/routes/factory.py (serves the chain and the task view)
Tested by:    tests/test_factory_loop.py
Touch when:   never for a new repository (delivery is switched on per run, not per repo);
              adding a status means ``STATUSES`` here, the UI's factory screen and
              docs/API.md#factory-phase-p6; adding a clause to the gate means a
              stop code here, the pre-run prediction in
              src/crb/server/routes/factory.py (``_cell_routes``) and the posture row, so
              what is predicted and what is enforced never disagree; changing the step order
              is a governance change — an ADR (ADR-0021 is the current order).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any, NoReturn

from crb.builders.base import Budget, Builder, Rung
from crb.builders.brief import (
    ACCEPTANCE_NONE,
    ARM_S1,
    ARM_S2,
    LABEL_ACCEPTANCE,
    arm_base,
    arm_carries_loop,
    context_arm_for,
)
from crb.core.checks import ResolvedChecks
from crb.core.deps import TaskDeps
from crb.core.evidence import utc_now_iso
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.ledger import JsonlLedger
from crb.core.posture import Posture
from crb.core.prevention import LearningSnapshot
from crb.core.redact import redact_and_cap, redact_and_cap_head
from crb.core.routing import REASON_FALSE_Q1, ROUTE_DO_NOT_SHIP
from crb.core.routing import ROUTE_DELIVER as ROUTE_DELIVER_WORD
from crb.core.runners.base import BaseRunner
from crb.core.spec import SIZE_TIER_NAMES, RepoConfig
from crb.factory.backlog import KIND_OPERATOR, Backlog, BacklogError, BacklogItem
from crb.factory.build import BuildResult, build_ladder
from crb.factory.delivery import (
    ClosePrFn,
    CommentPrFn,
    DeliveryError,
    DeliveryResult,
    GitCredentialsProvider,
    OpenPrFn,
    PushFn,
    close_pull_request,
    deliver,
)
from crb.factory.evidence import (
    EV_BACKLOG_FROZEN,
    EV_CALIBRATION_FUNDED,
    EV_DELIVERY,
    EV_DELIVERY_UPDATED,
    EV_PROBE_WAIVED,
    OUTCOME_CLOSED,
    FactoryEvent,
    FactoryEvidence,
    spent_grants,
)
from crb.factory.readiness import (
    ROUTE_HUMAN,
    ROUTE_TEST_FIRST,
    GapSignoff,
    JsonlGapSignoffLedger,
    Readiness,
    assess,
)
from crb.factory.review import (
    FINDING_PROBE_WAIVED,
    FINDING_WEAK_ORACLE,
    SEVERITY_BLOCKING,
    SEVERITY_MAJOR,
    MechanicalReviewer,
    Probe,
    ProbeWaiver,
    Reviewer,
    ReviewVerdict,
    permit_edit,
    review,
    unscoreable,
)
from crb.factory.standard import (
    NO_READINGS,
    STOP_CALIBRATION_BUILD,
    STOP_CELL_NOT_LICENSED,
    STOP_GRANULARIZE,
    STOP_NEEDS_CONTEXT,
    STOP_NO_PROVEN_STANDARD,
    STOP_NOT_LICENSED,
    STOP_SIZE_EXCEEDS_LICENCE,
    STOP_UNSIGNED_CELL,
    STOP_UNSIZED,
    Calibration,
    Entry,
    Readers,
    gate_for,
    licensing_rungs,
    own_cell_licence,
)
from crb.factory.testfirst import (
    AuthoredTest,
    NotRed,
    RedProof,
    TestAuthor,
    assert_distinct_identity,
    author_label,
    author_test,
    canonical_model,
    prove_red,
)
from crb.observability.events import Emitter, MemorySink, StepStatus

STAGE = "factory"
#: The row label a calibration build carries (ADR-0026 item 8).
LABEL_CALIBRATION = "calibration"

STATUS_NOT_READY = "not_ready"
STATUS_ROUTED_HUMAN = "routed_human"
STATUS_NO_ORACLE = "no_oracle"
STATUS_NOT_RED = "not_red"
STATUS_NOT_CLEAN = "not_clean"
STATUS_DISQUALIFIED = "disqualified"
STATUS_DELIVERY_FAILED = "delivery_failed"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_REWORK_EXHAUSTED = "rework_exhausted"
#: The reviewer asked for a stronger TEST (a ``weak_oracle`` finding) and no changed oracle
#: can be had — no test author, or the author returned the same bytes: a rebuild would only
#: let the builder find another way to pass the same test (B-1b finding 3, DL-045 rule 3).
STATUS_ORACLE_NEEDS_STRENGTHENING = "oracle_needs_strengthening"
#: The required strength probe could not score the authored test and no approver waived
#: it for those bytes (ADR-0025 item 12): no rework, no delivery — the way forward is a
#: superseding item with a scoreable test, or an approver's waiver for this test.
STATUS_ORACLE_NOT_SCOREABLE = "oracle_not_scoreable"
#: The entry gate's stops, before any spend (ADR-0026 item 8) — see crb.factory.standard.
STATUS_NO_PROVEN_STANDARD = STOP_NO_PROVEN_STANDARD
STATUS_NEEDS_CONTEXT = STOP_NEEDS_CONTEXT
STATUS_UNSIGNED_CELL = STOP_UNSIGNED_CELL
STATUS_GRANULARIZE = STOP_GRANULARIZE
STATUS_NOT_LICENSED = STOP_NOT_LICENSED
#: The licence of the delivered change (ADR-0025 item 12): after an accepting review, its
#: own measured cell did not license it — no pull request.
STATUS_SIZE_EXCEEDS_LICENCE = STOP_SIZE_EXCEEDS_LICENCE
STATUS_CELL_NOT_LICENSED = STOP_CELL_NOT_LICENSED
#: An approver's calibration build, accepted by its review: evented as one, stamped with its
#: arm, and never able to open a pull request.
STATUS_CALIBRATION_BUILD = STOP_CALIBRATION_BUILD
STATUS_BLOCKED = "blocked_on_dependency"
STATUS_ERROR = "error"
STATUSES: tuple[str, ...] = (
    STATUS_NOT_READY,
    STATUS_ROUTED_HUMAN,
    STATUS_NO_ORACLE,
    STATUS_NOT_RED,
    STATUS_NOT_CLEAN,
    STATUS_DISQUALIFIED,
    STATUS_DELIVERY_FAILED,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_REWORK_EXHAUSTED,
    STATUS_ORACLE_NEEDS_STRENGTHENING,
    STATUS_ORACLE_NOT_SCOREABLE,
    STATUS_NO_PROVEN_STANDARD,
    STATUS_NEEDS_CONTEXT,
    STATUS_UNSIGNED_CELL,
    STATUS_GRANULARIZE,
    STATUS_NOT_LICENSED,
    STATUS_SIZE_EXCEEDS_LICENCE,
    STATUS_CELL_NOT_LICENSED,
    STATUS_CALIBRATION_BUILD,
    STATUS_BLOCKED,
    STATUS_ERROR,
)
#: Entry-gate stop code → the item's status (``unsized`` goes to a person).
_ENTRY_STATUS: dict[str, str] = {
    STOP_UNSIZED: "routed_human",
    STOP_GRANULARIZE: STATUS_GRANULARIZE,
    STOP_NO_PROVEN_STANDARD: STATUS_NO_PROVEN_STANDARD,
    STOP_NEEDS_CONTEXT: STATUS_NEEDS_CONTEXT,
    STOP_UNSIGNED_CELL: STATUS_UNSIGNED_CELL,
    STOP_NOT_LICENSED: STATUS_NOT_LICENSED,
}
#: How much of a ``weak_oracle`` finding's detail the ``oracle_needs_strengthening`` reason
#: quotes — its head, so the reason's prefix and way forward fit ``ItemOutcome.error``.
_FINDING_HEAD_CHARS = 300

#: ``rework_test(item, verdict, previous) -> AuthoredTest | None`` — how a rework
#: obtains its (possibly strengthened) oracle. ``None`` keeps the previous test.
ReworkTestFn = Callable[[BacklogItem, ReviewVerdict, AuthoredTest], AuthoredTest | None]


@dataclass(frozen=True)
class FactorySpec:
    """Everything one factory run needs. Delivery is OPT-IN (``deliver=False``)."""

    config: RepoConfig
    runner: BaseRunner
    executor: Executor
    scratch: Path
    evidence_dir: Path
    evidence: FactoryEvidence
    ladder: tuple[Rung, ...]
    builder_for: Callable[[Rung], Builder]
    ledger: JsonlLedger | None = None
    budget: Budget = field(default_factory=Budget)
    reviewer: Reviewer = field(default_factory=MechanicalReviewer)
    probes: tuple[Probe, ...] | None = None
    test_author: TestAuthor | None = None
    gap_ledger: JsonlGapSignoffLedger | None = None
    deliver: bool = False
    creds: GitCredentialsProvider | None = None
    push_fn: PushFn | None = None
    open_pr_fn: OpenPrFn | None = None
    #: How a re-delivery (an item whose pull request an earlier run opened, accepted again)
    #: tells the pull request's reviewer why the branch moved; ``None`` = the branch is
    #: updated silently (the evidence chain still says).
    comment_pr_fn: CommentPrFn | None = None
    #: How an open pull request an earlier run opened is CLOSED when this run's review does
    #: not accept the item (ADR-0021); ``None`` = GitHub's pulls API
    #: (:func:`crb.factory.delivery.github_close_pr_fn`).
    close_pr_fn: ClosePrFn | None = None
    target_default_branch: str = "main"
    run_id: str = ""
    actor: str = ""
    timeout: int = 0
    max_rework: int = 1
    rework_test: ReworkTestFn | None = None
    #: The capability map's decision for the item's (class × size) cell — the ROUTE GATE on
    #: delivery: a pull request is opened only when it reads ``deliver``. ``None`` (no map
    #: available) withholds delivery like any other non-deliver route. Called ONCE per
    #: item, at readiness, before any build: the map that licenses a delivery is the map
    #: as it stood before this run's own rows landed (B-1b finding 2 → DL-045). It must answer
    #: from ONE pre-run reading of the map (the worker's is computed once, without this run's
    #: rows): when the built change measures larger than the item's estimate it is asked
    #: again, for the measured cell, and that answer is the route gate's (GOV-2).
    route_decision_for: Callable[[BacklogItem], Mapping[str, Any] | None] | None = None
    #: An approver's identity that lifts the SIGN-OFF clause (``unsigned_cell``) for THIS
    #: run, and nothing else (ADR-0026 item 8): never a missing standard, a ceiling, missing
    #: context, a calibration build, the route gate or the delivered change's own licence.
    #: Recorded on the evidence chain naming the approver. Empty = no override (the default).
    #: Never honoured when it names the run's own ``actor`` (GOV-4: ADR-0016's two-person
    #: rule — a second approver grants it, ``POST /runs/{id}/deliver-override``) or on a cell
    #: refused for false-Q1 (GOV-1: the honesty floor) — both refusals are on the chain.
    deliver_override_by: str = ""
    #: The same override read LIVE at each item's entry gate (the worker reads the run's
    #: row, so a second approver's grant made while the run works reaches the next item);
    #: ``None`` = the static ``deliver_override_by``.
    deliver_override_for: Callable[[], str] | None = None
    #: The run's ``checks`` switches (ADR-0024; the worker resolves ``params.checks`` over the
    #: repository's block, as for a replay): every build is graded on that arm — the arm the
    #: route gate read its licence on (GOV-3). ``None`` = the repository's own block.
    checks: ResolvedChecks | None = None
    #: The readers of the cells' proven standards (ADR-0026 item 8), bound ONCE per run to
    #: the pre-run map (the worker's: ``crb.server.factory_standard.bind_readers``). ``None``
    #: is ``crb.factory.standard.NO_READINGS`` — which fails closed: with no reading, no cell
    #: has a standard, and only a calibration build is built.
    readers: Readers | None = None
    #: ADR-0018's sign-off clause, as amended by ADR-0026 item 8. Default True: a proven
    #: standard with no active sign-off on its arm, class-set version and reading — in any
    #: cell the size rule reads — stops ``unsigned_cell`` BEFORE ANY SPEND. False
    #: (``CRB_FACTORY__REQUIRE_SIGNED_CELL=false``) removes this clause only, never the entry
    #: gate; the served posture says which is in force, so it is never a silent choice.
    require_signed_cell: bool = True
    #: The prevention loop's snapshot for this run (ADR-0020). A factory brief carries its
    #: overlay and lines when, and ONLY when, the item's standard arm carries ``+L``
    #: (ADR-0026 item 8): the loop switch never adds context the standard arm lacks.
    learning: LearningSnapshot | None = None
    keep_workspaces: bool = False
    #: The posture the run grades in and the dependency bindings its items build with
    #: (ADR-0019). ``None`` resolves the posture live per build and uses the null
    #: provider's bindings for the executor.
    posture: Posture | None = None
    deps: TaskDeps | None = None
    #: Keep every graded attempt's patch under ``<evidence_dir>/patches`` (crb.core.patches);
    #: ``False`` when the deployment keeps no code (``retention.patches`` off).
    keep_patches: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "ladder", tuple(self.ladder))
        if not self.ladder:
            raise ValueError("ladder must have at least one rung")
        if self.probes is not None:
            object.__setattr__(self, "probes", tuple(self.probes))
        if self.test_author is not None:
            # the author and every build rung differ by LABEL and by MODEL (C3): the refusal
            # names the rung by its place on the ladder, so the operator knows which to change
            lbl = author_label(self.test_author)
            for i, r in enumerate(self.ladder, start=1):
                assert_distinct_identity(lbl, r.label, role=f"build rung {i}")
        if self.max_rework < 0:
            raise ValueError("max_rework cannot be negative")
        if self.readers is None:
            object.__setattr__(self, "readers", NO_READINGS)

    @property
    def gate(self) -> Readers:
        """The bound readers (never ``None`` after construction)."""
        assert self.readers is not None
        return self.readers


@dataclass(frozen=True)
class ItemOutcome:
    """How one item ended: a ``STATUSES`` value plus everything that was observed on the
    way (readiness, proof, per-build summaries, delivery, every verdict)."""

    item_id: str
    status: str
    readiness: Readiness | None = None
    proof: RedProof | None = None
    builds: tuple[Mapping[str, Any], ...] = ()
    delivery: DeliveryResult | None = None
    verdicts: tuple[ReviewVerdict, ...] = ()
    reworks: int = 0
    error: str = ""
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        object.__setattr__(self, "builds", tuple(dict(b) for b in self.builds))
        object.__setattr__(self, "error", redact_and_cap(self.error, max_chars=2000))

    @property
    def accepted(self) -> bool:
        """The only status that counts as delivered work."""
        return self.status == STATUS_ACCEPTED

    @property
    def final_verdict(self) -> ReviewVerdict | None:
        """The last review verdict (after any rework), or ``None``."""
        return self.verdicts[-1] if self.verdicts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "status": self.status,
            "readiness": self.readiness.to_dict() if self.readiness else None,
            "proof": self.proof.to_dict() if self.proof else None,
            "builds": [dict(b) for b in self.builds],
            "delivery": self.delivery.to_dict() if self.delivery else None,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "reworks": self.reworks,
            "error": self.error,
            "duration_s": round(self.duration_s, 3),
        }


#: What the ``route.decided`` event keeps of the map's decision: enough for a reader (and
#: the pull-request body) to quote the pre-run map — the route, why, n, point, the
#: interval's floor, false-Q1, the policy and the apparatus the rows were graded under.
_ROUTE_SUMMARY_KEYS: tuple[str, ...] = (
    "route",
    "reason",
    "reason_code",
    "n",
    "point",
    "ci_low",
    "false_q1",
    "policy_version",
    "apparatus_versions",
    # ADR-0018: whether a human had attested the cell when the route was read — the sign-off
    # clause's reading, so the chain quotes the licence as well as the route
    "verification_tier",
)


def _route_summary(route: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The evidence-facing slice of a capability-map decision (``None`` stays ``None``)."""
    if route is None:
        return None
    return {k: route[k] for k in _ROUTE_SUMMARY_KEYS if k in route}


#: The ``reason_code`` of a delivery withheld because the change measured larger than the
#: cell the route was read on, and the measured cell does not route ``deliver`` (GOV-2).
REASON_SIZE_EXCEEDS_LICENCE = "size_exceeds_licence"
#: Why an approver's override was NOT honoured, as the refusal records it (``override_refused``).
OVERRIDE_REFUSED_FALSE_Q1 = "false_q1"
OVERRIDE_REFUSED_SAME_ACTOR = "same_actor"
_OVERRIDE_REFUSED_WHY: dict[str, str] = {
    OVERRIDE_REFUSED_FALSE_Q1: (
        "false-Q1 = 0 is the honesty floor: no override lifts anything on a cell with a "
        "false-Q1 row (the override by {by} was refused)"
    ),
    OVERRIDE_REFUSED_SAME_ACTOR: (
        "the override was named by this run's own actor {by}; a second approver grants it "
        "(ADR-0016's two-person rule), so it was refused"
    ),
}


def _tier(size: str) -> int:
    """A size tier's rank (``XS`` = 0); an unknown word ranks below every tier."""
    return SIZE_TIER_NAMES.index(size) if size in SIZE_TIER_NAMES else -1


def _override_refusal(route: Mapping[str, Any] | None, override_by: str, *, actor: str) -> str:
    """Why an override naming ``override_by`` cannot lift the sign-off clause for this cell
    (``""`` = it may): the honesty floor (a ``do_not_ship`` cell, a ``false_q1`` reason or
    any false-Q1 row in the cell — GOV-1), or an override named by the run's own actor
    (GOV-4)."""
    if not override_by:
        return ""
    r = route or {}
    try:
        fq1 = int(r.get("false_q1") or 0)
    except (TypeError, ValueError):
        fq1 = 1  # an unreadable count is not a clean one
    if r.get("route") == ROUTE_DO_NOT_SHIP or r.get("reason_code") == REASON_FALSE_Q1 or fq1 > 0:
        return OVERRIDE_REFUSED_FALSE_Q1
    if actor and override_by == actor:
        return OVERRIDE_REFUSED_SAME_ACTOR
    return ""


def _licence_line(entry: Entry) -> str:
    """What licensed this item at the entry gate, for the pull request's reader (ADR-0018):
    a signed cell, an approver's per-run override of the sign-off clause — one person, one
    run, never a human attestation of the cell — or a deployment that does not require a
    signed cell. Never "signed" unless the standard itself carries an active sign-off."""
    if entry.override_by:
        return (
            f"**unsigned cell** — opened under a per-run override of the sign-off clause by "
            f"approver `{entry.override_by}`, not a human attestation of the cell"
        )
    if entry.standard is not None and entry.standard.signed:
        return (
            f"**signed cell** — the cell's proven standard (`{entry.standard.arm}`) carries an "
            "active sign-off"
        )
    return (
        "**unsigned cell** — this deployment does not require a signed cell "
        "(`CRB_FACTORY__REQUIRE_SIGNED_CELL=false`)"
    )


def _waiver_notes(verdict: ReviewVerdict) -> tuple[str, ...]:
    """Every waiver the accepted verdict went through, as the pull request states it."""
    return tuple(
        f.detail for p in verdict.probes for f in p.findings if f.kind == FINDING_PROBE_WAIVED
    )


class _Stop(Exception):
    """Internal: end the item with a status (never escapes ``run_item``)."""

    def __init__(self, status: str, **fields: Any) -> None:
        super().__init__(status)
        self.status = status
        self.fields = fields


class FactoryLoop:
    """The orchestrator: ``run_item`` for one item, ``run_backlog`` for a frozen backlog,
    ``checkpoint`` for a horizon transition. Holds no state beyond its spec."""

    def __init__(self, spec: FactorySpec, repo: GitRepo, *, emitter: Emitter | None = None) -> None:
        self.spec = spec
        self.repo = repo
        #: The ONE key a delivery and a close resolve git credentials with (PR #55 review:
        #: a close once asked for the item id, a delivery for the repository).
        self.credentials_key = str(repo.path)
        self.emitter = emitter or Emitter(MemorySink(), actor=spec.actor, repo=spec.config.name)

    # --- events ---------------------------------------------------------------
    def _emit(
        self, action: str, item_id: str, *, status: StepStatus = StepStatus.OK, **payload: Any
    ) -> None:
        """One ``factory``-stage StepEvent (the item id is the step id)."""
        self.emitter.emit(STAGE, action, status=status, task_id=item_id, **payload)

    def _cb(self, item_id: str) -> Callable[[str, Mapping[str, Any]], None]:
        """The ``on_event`` callback handed to the core / builders for this item."""
        return self.emitter.on_event(STAGE, task_id=item_id)

    # --- steps -----------------------------------------------------------------
    def _signoffs(self, item: BacklogItem) -> list[GapSignoff]:
        """The item's gap sign-offs from the configured ledger (none when there is none)."""
        gl = self.spec.gap_ledger
        return gl.for_item(item.id) if gl is not None else []

    def _map_route(self, item: BacklogItem) -> dict[str, Any] | None:
        """The capability map's decision for the item's cell — read ONCE per item, here at
        readiness and before any build, so the gate and the pull-request body quote the map
        as it stood before this run (a clean build's own row must not nudge the cell that
        licenses its delivery — B-1b finding 2, DL-045). ``None`` = nobody measured it."""
        f = self.spec.route_decision_for
        if f is None:
            return None
        d = f(item)
        return None if d is None else dict(d)

    def _override_by(self) -> str:
        """Who lifts the sign-off clause for this run, read now: the live seam when the spec
        has one (a second approver's grant made while the run works), else the static
        value. ``""`` = nobody."""
        f = self.spec.deliver_override_for
        return str((f() if f is not None else self.spec.deliver_override_by) or "").strip()

    def _calibration(self, item: BacklogItem) -> Calibration | None:
        """The item's unspent calibration grant: the newest ``calibration.funded`` that no
        run has claimed (one grant funds ONE run — :func:`spent_grants`). Reading it is not
        taking it: :meth:`_assess` claims it on the chain before any spend (P-298)."""
        grant: Calibration | None = None
        events = self.spec.evidence.events_for(item.id)
        for ev in events:
            if ev.kind == EV_CALIBRATION_FUNDED:
                grant = Calibration(
                    approver=str(ev.payload.get("approver", "")),
                    reason=str(ev.payload.get("reason", "")),
                    event_id=ev.event_id,
                )
        return None if grant is None or grant.event_id in spent_grants(events) else grant

    def _stop_entry(self, item: BacklogItem, r: Readiness, entry: Entry) -> NoReturn:
        """Record the entry gate's stop — before any spend — and end the item."""
        ev = self.spec.evidence
        ev.record_entry_refused(
            item.id,
            entry.code,
            entry.reason,
            reason_code=entry.reason_code,
            needs=list(entry.needs),
            entry=entry.to_dict(),
        )
        ev.record_route(
            item.id, ROUTE_HUMAN, entry.reason, reason_code=entry.code, needs=list(entry.needs)
        )
        self._emit(
            "entry.refused",
            item.id,
            status=StepStatus.SKIPPED,
            code=entry.code,
            reason=entry.reason,
            needs=list(entry.needs),
        )
        raise _Stop(_ENTRY_STATUS[entry.code], readiness=r, error=entry.reason)

    def _assess(
        self, item: BacklogItem, authored: AuthoredTest | None = None
    ) -> tuple[Readiness, dict[str, Any] | None, Entry]:
        """Step 1: readiness and the ENTRY GATE (ADR-0026 item 8), before any spend.

        Operator work and a class a person must test (uncatalogued, weak oracle) go to a
        person; then the gate: the size rule, the cell's proven standard, what that arm
        needs, the sign-off clause (the one clause ``deliver_override`` lifts); an
        approver's calibration grant admits an item stopped for a missing standard or
        missing context, as a calibration build. A structural gap still blocks any build
        (``not_ready``). With delivery on, some rung must hold a licence at the item's size
        (``not_licensed``). Returns the readiness, the cell's route (:meth:`_map_route`) and
        the entry decision."""
        s = self.spec
        ev = s.evidence
        r = assess(item, self._signoffs(item))
        ev.record_readiness(r.to_dict())
        self._emit(
            "readiness.assessed",
            item.id,
            status=StepStatus.OK if r.ready else StepStatus.SKIPPED,
            ready=r.ready,
            route_hint=r.route_hint,
            gaps=[g.to_dict() for g in r.gaps],
        )
        if item.kind == KIND_OPERATOR:
            # never the factory's to build: it goes to the operator action queue, gaps and all
            ev.record_route(item.id, ROUTE_HUMAN, r.reason, open_gaps=[g.slot for g in r.gaps])
            self._emit("route.decided", item.id, route=ROUTE_HUMAN, reason=r.reason)
            raise _Stop(STATUS_ROUTED_HUMAN, readiness=r)
        if r.route_hint == ROUTE_HUMAN and r.ready:
            # a class a person must test (uncatalogued, or green proves only the build)
            ev.record_route(item.id, ROUTE_HUMAN, r.reason)
            self._emit("route.decided", item.id, route=ROUTE_HUMAN, reason=r.reason)
            raise _Stop(STATUS_ROUTED_HUMAN, readiness=r)
        g = s.gate
        # the override names a second approver, and never lifts anything on a false-Q1 cell:
        # a refused one is recorded, and the gate decides as if nobody had named it
        override_by = self._override_by()
        refused = _override_refusal(
            self._map_route(item) if override_by else None, override_by, actor=s.actor
        )
        if refused:
            ev.record_route(
                item.id,
                r.route_hint,
                f"override refused — {_OVERRIDE_REFUSED_WHY[refused].format(by=override_by)}",
                override_refused=refused,
                override_by=override_by,
            )
            self._emit(
                "delivery.override_refused",
                item.id,
                status=StepStatus.SKIPPED,
                override_refused=refused,
                override_by=override_by,
            )
            override_by = ""

        def decide(calibration: Calibration | None) -> Entry:
            return gate_for(
                item,
                r,
                g,
                person_test=authored is not None and authored.operator_authored,
                calibration=calibration,
                require_signed_cell=s.require_signed_cell,
                override_by=override_by,
                author=self._s1_author(authored),
            )

        entry = decide(self._calibration(item))
        if not entry.enters:
            self._stop_entry(item, r, entry)
        if entry.override_by:
            # the approver's override lifted the sign-off clause — and only that — by name
            ev.record_route(
                item.id,
                r.route_hint,
                f"sign-off clause lifted by {entry.override_by} for this run",
                override_by=entry.override_by,
                standard=entry.standard.to_dict() if entry.standard else None,
            )
            self._emit("delivery.override", item.id, override_by=entry.override_by)
        if not r.ready:
            ev.record_route(
                item.id, ROUTE_HUMAN, r.reason, blocking=[gap.slot for gap in r.blocking_gaps]
            )
            self._emit("readiness.refused", item.id, status=StepStatus.SKIPPED, reason=r.reason)
            raise _Stop(STATUS_NOT_READY, readiness=r)
        if entry.calibration is not None and (
            ev.claim_calibration(item.id, entry.calibration.event_id, run_id=s.run_id) is None
        ):
            # another run claimed the grant between our read and now: this run is answered
            # as if it had never been funded — the gate's own stop, before any spend (P-298)
            self._stop_entry(item, r, decide(None))
        route = self._map_route(item)
        cell = _route_summary(route)
        ev.record_route(
            item.id,
            r.route_hint,
            r.reason,
            cell_route=cell,
            standard=entry.standard.to_dict() if entry.standard else None,
            calibration=entry.calibration is not None,
        )
        self._emit("route.decided", item.id, route=r.route_hint, reason=r.reason, cell_route=cell)
        if s.deliver and entry.calibration is None:
            rungs = [(rung.builder, rung.model) for rung in s.ladder]
            if not licensing_rungs(
                item.capability_class,
                item.size_estimate,
                rungs,
                arm=entry.arm,
                standard_for=g.standard_for,
            ):
                self._stop_entry(
                    item,
                    r,
                    Entry(
                        STOP_NOT_LICENSED,
                        f"delivery is on and no rung of this run's ladder "
                        f"({', '.join(f'{b}:{m}' for b, m in rungs)}) holds a licence for "
                        f"{entry.arm} in the {item.capability_class} {item.size_estimate} "
                        "cell for its own builder and model: not built",
                        reason_code=STOP_NOT_LICENSED,
                        standard=entry.standard,
                        cells=entry.cells,
                    ),
                )
        if entry.calibration is not None:
            ev.record_route(
                item.id,
                r.route_hint,
                entry.reason,
                reason_code=STOP_CALIBRATION_BUILD,
                calibration_by=entry.calibration.approver,
                calibration_event=entry.calibration.event_id,
            )
            self._emit(
                "calibration.started",
                item.id,
                approver=entry.calibration.approver,
                answers=entry.reason_code,
            )
        return r, route, entry

    def _s1_author(self, authored: AuthoredTest | None) -> str | None:
        """The canonical model that would write this item's ``S1`` test — a caller's own
        (non-person) test's author, else the run's test author — or ``None`` when there is
        none (the oracle step then stops ``no_oracle``). The entry gate compares it with an
        ``S1@<author>`` standard, before any spend (ADR-0026 items 1 and 8)."""
        if authored is not None and not authored.operator_authored:
            model = authored.author.split(":", 1)[-1]
            return canonical_model(model) or model
        ta = self.spec.test_author
        if ta is None:
            return None
        return canonical_model(ta.model) or ta.model

    @staticmethod
    def _arm_base(entry: Entry, authored: AuthoredTest | None) -> str:
        """The base of the arm this build is composed from: the cell's standard arm; for a
        calibration build, ``S2`` when a person attached a failing test, else ``S1``."""
        if entry.calibration is None and entry.standard is not None and entry.standard.licenses:
            return entry.standard.base
        return ARM_S2 if authored is not None and authored.operator_authored else ARM_S1

    def _oracle(
        self,
        item: BacklogItem,
        r: Readiness,
        authored: AuthoredTest | None,
        entry: Entry | None = None,
    ) -> tuple[AuthoredTest, str]:
        """Step 2a: the oracle the standard arm is measured with, and the arm's id
        (ADR-0026 items 1 and 8) — the builder gets exactly that arm's context:

        * ``S2`` — the failing test a person attached;
        * ``S1@<author>`` — the configured test author's test; a person's test attached to
          an item in an ``S1`` cell is HELD OUT (recorded, never shown to the builder).

        Stops with ``no_oracle`` when the arm's oracle cannot be had."""
        entry = entry or Entry()
        s = self.spec
        plus_l = entry.calibration is None and entry.standard is not None and entry.standard.plus_l
        base = self._arm_base(entry, authored)
        if base == ARM_S2 and authored is not None:
            return authored, context_arm_for(base=ARM_S2, plus_l=plus_l)
        if authored is not None and authored.operator_authored:
            s.evidence.record_route(
                item.id,
                r.route_hint,
                "a person's test on an S1 cell is kept as a held-out acceptance test: the "
                "builder never sees it",
                held_out_test=authored.path,
                held_out_sha256=authored.sha256,
            )
            self._emit("author.held_out", item.id, path=authored.path, sha256=authored.sha256)
        elif authored is not None:
            # a test handed in by another author (a caller's own oracle) is the arm's oracle
            ta_model = authored.author.split(":", 1)[-1]
            return authored, context_arm_for(
                base=ARM_S1, author=canonical_model(ta_model) or ta_model, plus_l=plus_l
            )
        ta = s.test_author
        if ta is None:
            s.evidence.record_red_refused(
                item.id, "no authored test and no test author configured", route=r.route_hint
            )
            raise _Stop(STATUS_NO_ORACLE, readiness=r)
        self._emit("author.start", item.id, author=author_label(ta), route=r.route_hint)
        res = author_test(
            self.repo,
            item,
            ta,
            facts=r.facts,
            config=s.config,
            scratch=s.scratch,
            on_event=self._cb(item.id),
        )
        if r.route_hint != ROUTE_TEST_FIRST:
            self._emit("author.done", item.id, note="authored on the build route (no value gaps)")
        arm = context_arm_for(
            base=ARM_S1, author=canonical_model(ta.model) or ta.model, plus_l=plus_l
        )
        return res.authored, arm

    def _prove(self, item: BacklogItem, r: Readiness, authored: AuthoredTest) -> RedProof:
        """Step 2b: the RED proof; a refusal is recorded and stops the item (``not_red``)."""
        s = self.spec
        try:
            proof = prove_red(
                self.repo,
                item,
                authored,
                config=s.config,
                runner=s.runner,
                executor=s.executor,
                scratch=s.scratch,
                timeout=s.timeout,
                on_event=self._cb(item.id),
            )
        except NotRed as exc:
            s.evidence.record_red_refused(
                item.id, str(exc), path=authored.path, author=authored.author
            )
            raise _Stop(STATUS_NOT_RED, readiness=r, error=str(exc)) from exc
        s.evidence.record_red_proof(proof.to_dict())
        return proof

    def _build(
        self,
        item: BacklogItem,
        r: Readiness,
        authored: AuthoredTest,
        proof: RedProof,
        *,
        trial_prefix: str,
        labels: Mapping[str, str] | None = None,
        arm: str = "",
    ) -> list[BuildResult]:
        """Step 3: the build ladder; every attempt is recorded, the final one's tree kept.
        ``labels`` go on every row: the context arm the brief carried, a calibration
        build's stamp (ADR-0026 items 1 and 8)."""
        s = self.spec
        results = build_ladder(
            self.repo,
            item,
            authored,
            proof,
            rungs=s.ladder,
            builder_for=s.builder_for,
            budget=s.budget,
            config=s.config,
            runner=s.runner,
            executor=s.executor,
            scratch=s.scratch,
            evidence_dir=s.evidence_dir,
            ledger=s.ledger,
            run_id=s.run_id,
            actor=s.actor,
            facts=r.fact_lines(),
            timeout=s.timeout,
            trial_prefix=trial_prefix,
            on_event=self._cb(item.id),
            posture=s.posture,
            deps=s.deps,
            keep_patches=s.keep_patches,
            checks=s.checks,
            labels=labels,
            arm=arm,
            # ADR-0026 item 8: the loop's overlay and lines only on a +L arm
            learning=s.learning if arm_carries_loop(arm) else None,
            author_stamp=self._author_stamp(proof),
        )
        for res in results:
            s.evidence.record_build(
                item.id,
                pack_hash=res.pack_hash,
                row_id=res.row.row_id if res.row else "",
                row_hash=res.row.row_hash if res.row else "",
                clean=res.clean,
                belts=res.grade.belts.to_dict(),
                rung=res.rung,
                trial=res.trial,
                oracle_commit=res.oracle.sha,
                test_sha256=res.oracle.test_sha256,
                disqualified=res.disqualified,
                error=res.error or res.grade.error,
            )
        return results

    def _deliver(
        self,
        item: BacklogItem,
        final: BuildResult,
        route: Mapping[str, Any] | None,
        *,
        verdict: ReviewVerdict,
        previous: DeliveryResult | None = None,
        rework_n: int = 0,
        after_verdict: str = "",
        arm: str = "",
        licence_line: str = "",
    ) -> tuple[DeliveryResult | None, str]:
        """The LAST step: delivery of a build the review ACCEPTED (ADR-0021) — skipped and
        RECORDED when opt-in is off; a failure stops the item (``delivery_failed``).
        ``verdict`` is the review of ``final``: anything but ``accept`` is refused here and
        again by :func:`crb.factory.delivery.deliver`, so no caller can deliver an
        unreviewed or unaccepted build. ``route`` is the cell's decision read at readiness.
        ``previous`` is the item's OPEN pull request from an earlier run: the same pull
        request is updated, never a second one opened; its comment failing (after the push
        has moved the branch) is recorded on the ``delivery.updated`` event as
        ``comment_error`` and emitted as a ``delivery.comment_failed`` warning. ``arm`` is
        the context arm the build carried: the change's own cell must license THAT arm.
        Returns ``(result, pr_ref)``."""
        s = self.spec
        if not verdict.accepted or verdict.pack_hash != final.pack_hash:
            raise DeliveryError(
                f"delivery refused: the review of build {final.pack_hash[:12]} is "
                f"{verdict.verdict!r} on pack {verdict.pack_hash[:12]} — only an accepted, "
                "reviewed build is delivered (ADR-0021)"
            )
        if not s.deliver:
            s.evidence.record_delivery_refused(
                item.id,
                "delivery is opt-in and OFF — built and graded locally only",
                pack_hash=final.pack_hash,
            )
            self._emit("delivery.skipped", item.id, status=StepStatus.SKIPPED, reason="opt-in off")
            return None, ""
        # THE LICENCE OF THE DELIVERED CHANGE (ADR-0025 item 12, C4): the change's OWN cell —
        # its class, the size tier of the churn actually built, the final rung's builder and
        # model, and the arm the build carried — must license delivery in the map read
        # before the run. Both sizes and both cells go on the evidence; nothing (no
        # override) lifts this.
        built_by = final.pack.builder
        rung_builder, _, rung_model = final.rung.partition(":")
        lic = own_cell_licence(
            capability_class=item.capability_class,
            estimate=item.size_estimate,
            measured=final.task.size,
            builder=built_by.name if built_by is not None else rung_builder,
            model=built_by.model if built_by is not None else rung_model,
            arm=arm,
            standard_for=s.gate.standard_for,
        )
        if not lic.licensed:
            s.evidence.record_delivery_refused(
                item.id,
                lic.reason,
                pack_hash=final.pack_hash,
                reason_code=lic.code,
                estimate=lic.estimate,
                measured=lic.measured,
                estimated_cell=f"{item.capability_class}|{item.size_estimate}",
                licence=lic.to_dict(),
            )
            self._emit(
                "delivery.unlicensed",
                item.id,
                status=StepStatus.SKIPPED,
                reason=lic.reason,
                code=lic.code,
                estimate=lic.estimate,
                measured=lic.measured,
            )
            raise _Stop(
                STATUS_SIZE_EXCEEDS_LICENCE
                if lic.code == STOP_SIZE_EXCEEDS_LICENCE
                else STATUS_CELL_NOT_LICENSED,
                error=lic.reason,
            )
        # both sizes and both cells ride on the delivery event itself
        licence = {
            "estimate": lic.estimate,
            "measured": lic.measured,
            "estimated_cell": f"{item.capability_class}|{item.size_estimate}",
            "licence": lic.to_dict(),
        }
        # THE ROUTE GATE (external review 2026-09-16, point 36 → DL-038): the capability
        # map decides what the factory may deliver. A clean build in a cell that does not
        # route `deliver` — or in a cell nobody has measured — opens no pull request; the
        # withholding and the measured route are on the evidence chain. The route was read
        # ONCE, at readiness, before this build's row landed (DL-045) — never re-read here,
        # unless the change measures larger than the item's estimate: the route gate covers
        # the size DELIVERED (GOV-2), so the measured cell's route — from the same pre-run
        # map — is the one read. No override lifts it (ADR-0026 item 8:
        # ``deliver_override`` lifts the sign-off clause only, at the entry gate).
        declared, delivered = item.size_estimate, final.task.size
        resized = _tier(delivered) > _tier(declared)
        if resized:
            route = self._map_route(dc_replace(item, size_estimate=delivered))
        sizes = {"size_estimate": declared, "size_measured": delivered} if resized else {}
        measured = str(route.get("route", "")) if route else ""
        if measured != ROUTE_DELIVER_WORD:
            why = (
                "no capability-map route for the item's cell — nothing measured licenses delivery"
                if route is None
                else f"the cell routes {measured} ({route.get('reason_code') or route.get('reason', '')})"
            )
            reason_code = str((route or {}).get("reason_code", ""))
            if resized:
                why = (
                    f"the change measures {delivered} ({final.task.src_churn} changed lines) "
                    f"where the item was estimated {declared}, and the ({item.capability_class}, "
                    f"{delivered}) cell licenses no delivery: {why}"
                )
                reason_code = REASON_SIZE_EXCEEDS_LICENCE
            s.evidence.record_delivery_refused(
                item.id,
                f"route gate: {why}",
                pack_hash=final.pack_hash,
                measured_route=measured,
                reason_code=reason_code,
                policy_version=str((route or {}).get("policy_version", "")),
                **sizes,
            )
            self._emit(
                "delivery.withheld",
                item.id,
                status=StepStatus.SKIPPED,
                reason=why,
                measured_route=measured,
            )
            return None, ""
        try:
            d = deliver(
                self.repo,
                item,
                final,
                creds=s.creds,
                open_pr_fn=s.open_pr_fn,
                push_fn=s.push_fn,
                comment_pr_fn=s.comment_pr_fn,
                target_default_branch=s.target_default_branch,
                pack_link=str(final.pack_path),
                route_decision=route,
                previous=previous,
                rework_n=rework_n,
                after_verdict=after_verdict,
                verdict=verdict.verdict,
                repo_id=self.credentials_key,
                waivers=_waiver_notes(verdict),
                licence_line=licence_line,
            )
        except DeliveryError as exc:
            s.evidence.record_delivery_refused(
                item.id, str(exc), pack_hash=final.pack_hash, rework=rework_n
            )
            self._emit("delivery.error", item.id, status=StepStatus.ERROR, error=str(exc))
            raise _Stop(STATUS_DELIVERY_FAILED, error=str(exc)) from exc
        if d.updated:
            s.evidence.record_delivery_updated(
                {**d.to_dict(), **licence}, rework=rework_n, after_verdict=after_verdict
            )
            self._emit(
                "delivery.updated",
                item.id,
                branch=d.branch,
                base=d.base,
                pr=d.pr_ref,
                previous_commit_sha=d.previous_commit_sha,
                commit_sha=d.commit_sha,
                rework=rework_n,
            )
            if d.comment_error:
                # the branch and the pull request carry the rework; only the note to the
                # reviewer is missing — a warning on the trace, never a delivery failure
                self._emit(
                    "delivery.comment_failed",
                    item.id,
                    status=StepStatus.ERROR,
                    error=d.comment_error,
                    pr=d.pr_ref,
                    rework=rework_n,
                )
            return d, d.pr_ref
        s.evidence.record_delivery({**d.to_dict(), **licence})
        self._emit("delivery.opened", item.id, branch=d.branch, base=d.base, pr=d.pr_ref)
        return d, d.pr_ref

    def _author_stamp(self, proof: RedProof) -> str:
        """``ctx_author`` — the test author's provider stamp, when the test author wrote the
        oracle (an ``S1`` arm); "" for a person's test."""
        ta = self.spec.test_author
        if ta is None or proof.author != author_label(ta):
            return ""
        return str(getattr(ta, "provider", "") or ta.name)

    def _probe_waiver(self, item: BacklogItem, test_sha256: str) -> ProbeWaiver | None:
        """The newest approver's waiver of the strength probe on the item's chain that is
        bound to exactly ``test_sha256`` (ADR-0025 item 12); ``None`` when there is none —
        a waiver for other bytes is not a waiver."""
        found: ProbeWaiver | None = None
        for ev in self.spec.evidence.events_for(item.id, EV_PROBE_WAIVED):
            w = ProbeWaiver(
                approver=str(ev.payload.get("approver", "")),
                reason=str(ev.payload.get("reason", "")),
                test_sha256=str(ev.payload.get("test_sha256", "")),
                event_id=ev.event_id,
            )
            if w.applies_to(test_sha256):
                found = w
        return found

    def _require_scoreable(
        self,
        item: BacklogItem,
        verdict: ReviewVerdict,
        oracle: AuthoredTest,
        *,
        open_pr: DeliveryResult | None = None,
    ) -> None:
        """Stop the item ``oracle_not_scoreable`` when the required strength probe could
        not score its test and nobody waived it for these bytes (ADR-0025 item 12): the
        verdict is already on the record; nothing is reworked or pushed, an open pull
        request an earlier run opened is closed, and the reason carries the way forward."""
        probe = unscoreable(verdict)
        if probe is None:
            return
        why = redact_and_cap_head(probe.detail, max_chars=_FINDING_HEAD_CHARS)
        reason = (
            f"the strength probe could not score the authored test ({why}): register a "
            "superseding item whose test exercises the changed lines, or ask an approver "
            f"to waive the probe for this test's exact bytes (sha256 {oracle.sha256[:12]})"
        )
        self.spec.evidence.record_route(
            item.id,
            ROUTE_HUMAN,
            reason,
            reason_code=STATUS_ORACLE_NOT_SCOREABLE,
            after_verdict=verdict.verdict,
            verdict_event=verdict.event_id,
            oracle_sha256=oracle.sha256,
        )
        self._emit("route.decided", item.id, route=ROUTE_HUMAN, reason=reason)
        self._withdraw(item, open_pr, verdict, reason)
        raise _Stop(STATUS_ORACLE_NOT_SCOREABLE, error=reason)

    def _review(
        self, item: BacklogItem, final: BuildResult, proof: RedProof, pr_ref: str = ""
    ) -> ReviewVerdict:
        """Step 4: independent review of the built change BEFORE anything leaves the
        factory (ADR-0021) — ``pr_ref`` is empty, no pull request exists yet; the verdict
        is on the ledger before this returns. An approver's strength-probe waiver for the
        build's own oracle bytes is handed to the review (ADR-0025 item 12)."""
        s = self.spec
        v = review(
            final,
            pr_ref,
            reviewer=s.reviewer,
            item=item,
            proof=proof,
            repo=self.repo,
            config=s.config,
            runner=s.runner,
            executor=s.executor,
            scratch=s.scratch,
            evidence=s.evidence,
            probes=s.probes,
            timeout=s.timeout,
            on_event=self._cb(item.id),
            waiver=self._probe_waiver(item, final.oracle.test_sha256),
        )
        self._emit("review.recorded", item.id, verdict=v.verdict, event=v.event_id)
        return v

    # --- a pull request an earlier run opened (ADR-0021) -----------------------------
    def _open_delivery(self, item: BacklogItem) -> DeliveryResult | None:
        """The item's newest delivery on the chain whose pull request has no recorded
        outcome (``delivery.merged`` / ``delivery.closed``) — the pull request an earlier
        run opened and nobody has merged or closed. Read only when delivery is on: with it
        off this run touches no remote. ``None`` when there is none."""
        s = self.spec
        if not s.deliver:
            return None
        latest: FactoryEvent | None = None
        for ev in s.evidence.events_for(item.id):
            if ev.kind in (EV_DELIVERY, EV_DELIVERY_UPDATED):
                latest = ev
        if latest is None:
            return None
        p = latest.payload
        number = int(p.get("pr_number", 0) or 0)
        if number <= 0 or s.evidence.outcome_for(item.id, number) is not None:
            return None
        return DeliveryResult(
            item_id=item.id,
            branch=str(p.get("branch", "")),
            base=str(p.get("base", "")),
            commit_sha=str(p.get("commit_sha", "")),
            pr_url=str(p.get("pr_url", "")),
            pr_number=number,
            pack_hash=str(p.get("pack_hash", "")),
            body_sha256=str(p.get("body_sha256", "")),
            created=str(p.get("created", "")),
            # the repository the pull request is in: the re-delivery and the close refuse
            # any other (PR #55 review — a re-linked row once closed a stranger's PR)
            repository=str(p.get("repository", "")),
        )

    def _withdraw(
        self, item: BacklogItem, open_pr: DeliveryResult | None, verdict: ReviewVerdict, why: str
    ) -> None:
        """Close the item's open pull request because this run's review did not accept the
        item (ADR-0021): a comment names the verdict and why, then the pull request is
        closed; the chain records ``delivery.closed`` with ``closed_by: factory`` and the
        verdict. A failure to close is a ``delivery.close_failed`` warning on the trace —
        the pull request stays open and the outcome sync still reads its fate — never a
        change to the item's status."""
        if open_pr is None:
            return
        s = self.spec
        kinds = sorted(
            {f.kind for f in verdict.findings if f.severity in (SEVERITY_MAJOR, SEVERITY_BLOCKING)}
        )
        why = f"{'finding(s) ' + ', '.join(kinds) + ' — ' if kinds else ''}{why}"
        try:
            close_pull_request(
                open_pr,
                verdict=verdict.verdict,
                reason=why,
                creds=s.creds,
                close_pr_fn=s.close_pr_fn,
                repo_id=self.credentials_key,
            )
        except Exception as exc:  # a refused, unreachable or garbled close: never a status
            self._emit(
                "delivery.close_failed",
                item.id,
                status=StepStatus.ERROR,
                error=redact_and_cap_head(f"{type(exc).__name__}: {exc}", max_chars=400),
                pr=open_pr.pr_ref,
                verdict=verdict.verdict,
            )
            return
        s.evidence.record_delivery_outcome(
            item.id,
            state=OUTCOME_CLOSED,
            pr_number=open_pr.pr_number,
            pr_url=open_pr.pr_url,
            closed_at=utc_now_iso(),
            closed_by="factory",
            verdict=verdict.verdict,
            reason=why,
        )
        self._emit(
            "delivery.closed",
            item.id,
            pr=open_pr.pr_ref,
            verdict=verdict.verdict,
            closed_by="factory",
        )

    # --- the oracle rule on rework (DL-045 rule 3) --------------------------------
    @staticmethod
    def _weak_oracle_finding(verdict: ReviewVerdict) -> str | None:
        """The detail of the verdict's ``weak_oracle`` finding, or ``None`` when the rework
        was asked for another reason (that rework keeps the ordinary path)."""
        for f in verdict.findings:
            if f.kind == FINDING_WEAK_ORACLE:
                return f.detail
        return None

    def _refuse_rework(
        self,
        item: BacklogItem,
        verdict: ReviewVerdict,
        oracle: AuthoredTest,
        why: str,
        *,
        open_pr: DeliveryResult | None = None,
    ) -> NoReturn:
        """Stop the item ``oracle_needs_strengthening``: the reviewer asked for a stronger
        test and none can be had here. Routed human on the chain (the finding and the way
        forward in the reason), ``rework.refused`` on the trace — NO build, NO delivery,
        and an open pull request an earlier run opened is closed (ADR-0021)."""
        # the finding's detail may run to the 2000 chars a ReviewFinding allows, and
        # ItemOutcome.error is tail-capped at 2000: composed from the detail's HEAD, the
        # reason keeps its prefix (the reader's key) and the way forward on the outcome
        # exactly as the chain and the trace carry it
        finding = redact_and_cap_head(
            self._weak_oracle_finding(verdict) or "", max_chars=_FINDING_HEAD_CHARS
        )
        reason = (
            f"the reviewer found the oracle weak ({finding}) and {why}: "
            "strengthen the test and register a superseding item"
        )
        self.spec.evidence.record_route(
            item.id,
            ROUTE_HUMAN,
            reason,
            after_verdict=verdict.verdict,
            finding=FINDING_WEAK_ORACLE,
            verdict_event=verdict.event_id,
            oracle_sha256=oracle.sha256,
        )
        self._emit("route.decided", item.id, route=ROUTE_HUMAN, reason=reason)
        self._emit("rework.refused", item.id, status=StepStatus.SKIPPED, reason=reason)
        self._withdraw(item, open_pr, verdict, reason)
        raise _Stop(STATUS_ORACLE_NEEDS_STRENGTHENING, error=reason)

    # --- one item ----------------------------------------------------------------
    def run_item(self, item: BacklogItem, *, authored: AuthoredTest | None = None) -> ItemOutcome:
        """Run one item end to end. Never raises for a governed refusal (the outcome
        says why); raises :class:`SandboxUnavailable` so a run can stop."""
        started = time.monotonic()
        s = self.spec
        self._emit(
            "item.start", item.id, kind=item.kind, level=item.level, cls=item.capability_class
        )
        readiness: Readiness | None = None
        proof: RedProof | None = None
        builds: list[Mapping[str, Any]] = []
        verdicts: list[ReviewVerdict] = []
        delivery: DeliveryResult | None = None
        reworks = 0
        keep: list[BuildResult] = []
        entry = Entry()
        try:
            readiness, route, entry = self._assess(item, authored)
            calibrating = entry.calibration is not None
            # the item's pull request from an earlier run, read before this run appends
            # anything: an accept updates it, any other final verdict closes it (ADR-0021).
            # A calibration build never touches a remote.
            open_pr = None if calibrating else self._open_delivery(item)
            oracle, arm = self._oracle(item, readiness, authored, entry)
            # the arm is composed into the brief and stamped by the composer; the loop adds
            # only what the build cannot know — that it is an approver's calibration build,
            # and, on an S2 row, that no second person's held-out acceptance tests graded
            # it (ADR-0026 item 8; product.truth.215 builds them): such a row is never a
            # routing first attempt (``crb.builders.brief.counts_as_s2_first_attempt``)
            labels = {LABEL_CALIBRATION: "true"} if calibrating else {}
            if arm_base(arm) == ARM_S2:
                labels[LABEL_ACCEPTANCE] = ACCEPTANCE_NONE
            proof = self._prove(item, readiness, oracle)
            results = self._build(
                item, readiness, oracle, proof, trial_prefix="r", labels=labels, arm=arm
            )
            builds += [b.summary() for b in results]
            final = results[-1]
            keep.append(final)
            if final.disqualified:
                raise _Stop(STATUS_DISQUALIFIED)
            if not final.clean:
                raise _Stop(STATUS_NOT_CLEAN)
            # ADR-0021: the review comes BEFORE anything leaves the factory — no pull
            # request exists while the build is under review
            verdict = self._review(item, final, proof)
            verdicts.append(verdict)
            self._require_scoreable(item, verdict, oracle, open_pr=open_pr)
            while verdict.rework_required and reworks < s.max_rework:
                # DL-045 rule 3: a `weak_oracle` finding asks for a stronger TEST; rebuilding
                # against the same one only lets the builder find another way to pass it
                # (B-1b finding 3). With no test author there is nobody here to strengthen
                # it — the item stops before any edit is permitted.
                wants_stronger_test = self._weak_oracle_finding(verdict) is not None
                if wants_stronger_test and s.rework_test is None:
                    self._refuse_rework(
                        item,
                        verdict,
                        oracle,
                        "this deployment has no test author",
                        open_pr=open_pr,
                    )
                reworks += 1
                # the human/agent edit is PERMITTED only now — the verdict is on the record
                permit_edit(
                    s.evidence,
                    item.id,
                    pack_hash=final.pack_hash,
                    editor=s.actor or "factory",
                    note=f"rework {reworks} after {verdict.verdict}",
                )
                self._emit("rework.start", item.id, n=reworks, after=verdict.verdict)
                # the reviewed build is fully consumed (verdict on the record) and was never
                # delivered; release its worktree before the rebuild
                final.close()
                edited = s.rework_test(item, verdict, oracle) if s.rework_test is not None else None
                if wants_stronger_test and (edited is None or edited.sha256 == oracle.sha256):
                    # the author answered with the same bytes: still the same oracle
                    self._refuse_rework(
                        item,
                        verdict,
                        oracle,
                        "the test author returned the same oracle",
                        open_pr=open_pr,
                    )
                oracle = edited or oracle
                proof = self._prove(item, readiness, oracle)
                results = self._build(
                    item,
                    readiness,
                    oracle,
                    proof,
                    trial_prefix=f"w{reworks}r",
                    labels=labels,
                    arm=arm,
                )
                builds += [b.summary() for b in results]
                final = results[-1]
                keep.append(final)
                if final.disqualified:
                    raise _Stop(STATUS_DISQUALIFIED)
                if not final.clean:
                    raise _Stop(STATUS_NOT_CLEAN)
                verdict = self._review(item, final, proof)
                verdicts.append(verdict)
                self._require_scoreable(item, verdict, oracle, open_pr=open_pr)
            if verdict.accepted and calibrating:
                # ADR-0026 item 8: a calibration build never opens a pull request, whatever
                # its review and its cell's route say — it is a measurement, not a delivery
                assert entry.calibration is not None
                why = (
                    f"a calibration build (funded by {entry.calibration.approver}) never opens "
                    "a pull request: its row is a measurement of the arm"
                )
                s.evidence.record_delivery_refused(
                    item.id,
                    why,
                    pack_hash=final.pack_hash,
                    reason_code=STOP_CALIBRATION_BUILD,
                    calibration_by=entry.calibration.approver,
                    context_arm=arm,
                )
                self._emit(
                    "calibration.built",
                    item.id,
                    status=StepStatus.SKIPPED,
                    reason=why,
                    approver=entry.calibration.approver,
                )
                status = STATUS_CALIBRATION_BUILD
            elif verdict.accepted:
                # the ONLY path to a pull request: the final, accepted, reviewed build
                delivery, _ = self._deliver(
                    item,
                    final,
                    route,
                    verdict=verdict,
                    previous=open_pr,
                    rework_n=reworks,
                    after_verdict=verdicts[-2].verdict if len(verdicts) > 1 else "",
                    arm=arm,
                    licence_line=_licence_line(entry),
                )
                status = STATUS_ACCEPTED
            else:
                status = STATUS_REWORK_EXHAUSTED if verdict.rework_required else STATUS_REJECTED
                self._withdraw(
                    item,
                    open_pr,
                    verdict,
                    f"the review of this run's rebuild ended {status}: {verdict.summary}",
                )
            error = ""
        except _Stop as stop:
            status = stop.status
            readiness = stop.fields.get("readiness", readiness)
            error = str(stop.fields.get("error", ""))
        except SandboxUnavailable:
            raise
        except Exception as exc:  # any other harness failure is a recorded non-pass
            status = STATUS_ERROR
            error = f"{type(exc).__name__}: {exc}"
            self._emit("item.error", item.id, status=StepStatus.ERROR, error=error)
        finally:
            if not s.keep_workspaces:
                for b in keep:
                    b.close()
        outcome = ItemOutcome(
            item_id=item.id,
            status=status,
            readiness=readiness,
            proof=proof,
            builds=tuple(builds),
            delivery=delivery,
            verdicts=tuple(verdicts),
            reworks=reworks,
            error=error,
            duration_s=time.monotonic() - started,
        )
        spent = (
            {"calibration_event": entry.calibration.event_id}
            if entry.calibration is not None and builds
            else {}
        )
        s.evidence.record_item_outcome(
            item.id,
            status=status,
            builds=len(builds),
            verdict=outcome.final_verdict.verdict if outcome.final_verdict else "",
            delivered=delivery is not None,
            reworks=reworks,
            error=error,
            **spent,
        )
        self._emit(
            "item.done",
            item.id,
            status=StepStatus.OK if outcome.accepted else StepStatus.SKIPPED,
            outcome=status,
            duration_ms=int(outcome.duration_s * 1000),
        )
        return outcome

    # --- a whole backlog ---------------------------------------------------------
    def run_backlog(
        self,
        backlog: Backlog,
        *,
        authored: Mapping[str, AuthoredTest] | None = None,
        expected_hash: str = "",
        stop: Callable[[], bool] | None = None,
    ) -> list[ItemOutcome]:
        """All-comers: every active item is attempted or explicitly routed, in
        dependency order. The backlog must be frozen and verify; the freeze is
        recorded once. An item whose dependency was not accepted is recorded as
        blocked, never silently skipped — the dependency resolved through the
        backlog's supersession chain, so its latest evolution is what must have been
        accepted."""
        if not backlog.frozen or not backlog.verify(expected_hash):
            raise BacklogError("backlog must be frozen and verify against its hash before a run")
        ev = self.spec.evidence
        if not any(
            e.kind == EV_BACKLOG_FROZEN and e.payload.get("backlog_hash") == backlog.backlog_hash
            for e in ev.events()
        ):
            ev.record_freeze(
                backlog_hash=backlog.backlog_hash,
                item_ids=[i.id for i in backlog.items],
                frozen_at=backlog.frozen_at,
            )
        tests = dict(authored or {})
        outcomes: dict[str, ItemOutcome] = {}
        for item in backlog.ordered():
            if stop is not None and stop():
                break
            # a dependency names the id as registered; what was worked may be the latest
            # evolution of it (``Backlog.resolve``) — the block check follows the same
            # supersession chain ``ordered()`` sorted by, so a failed evolution of a
            # dependency blocks the dependant under the evolution's id
            deps = [backlog.resolve(d) for d in item.depends_on]
            unmet = [d for d in deps if d in outcomes and not outcomes[d].accepted]
            if unmet:
                ev.record_item_outcome(item.id, status=STATUS_BLOCKED, blocked_on=unmet)
                self._emit("item.blocked", item.id, status=StepStatus.SKIPPED, blocked_on=unmet)
                outcomes[item.id] = ItemOutcome(
                    item.id, STATUS_BLOCKED, error=f"blocked on {unmet}"
                )
                continue
            outcomes[item.id] = self.run_item(item, authored=tests.get(item.id))
        return list(outcomes.values())

    def checkpoint(
        self,
        level: str,
        *,
        observations: int,
        issues_minted: Sequence[str],
        signed_off_by: str,
        note: str = "",
    ) -> FactoryEvent:
        """Ledger a horizon transition (L1 → L2 → L3) with its verification mode."""
        ev = self.spec.evidence.record_checkpoint(
            level=level,
            observations=observations,
            issues_minted=issues_minted,
            signed_off_by=signed_off_by,
            note=note,
        )
        self._emit("horizon.checkpoint", "", level=level, observations=observations)
        return ev


__all__ = [
    "STAGE",
    "STATUSES",
    "STATUS_ACCEPTED",
    "STATUS_BLOCKED",
    "STATUS_DELIVERY_FAILED",
    "STATUS_DISQUALIFIED",
    "STATUS_ERROR",
    "STATUS_NOT_CLEAN",
    "STATUS_NOT_READY",
    "STATUS_NOT_RED",
    "STATUS_NO_ORACLE",
    "STATUS_ORACLE_NEEDS_STRENGTHENING",
    "STATUS_ORACLE_NOT_SCOREABLE",
    "STATUS_REJECTED",
    "STATUS_REWORK_EXHAUSTED",
    "STATUS_ROUTED_HUMAN",
    "STATUS_UNSIGNED_CELL",
    "FactoryLoop",
    "FactorySpec",
    "ItemOutcome",
    "ReworkTestFn",
]
