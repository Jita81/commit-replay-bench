"""The governed loop, one backlog item end to end, every step evidenced.

    assess readiness ──refuse on unsigned structural gap──▶ not_ready
      │ route hint ──human──▶ routed_human
      ▼
    RED proof (authored test, or the test-first author rung) ──refused──▶ not_red
      ▼
    build ladder → grade (pack + ledger row, process_step=factory)
      ▼ not clean / disqualified ──▶ not_clean / disqualified
    deliver (OPT-IN, default OFF; fails closed on missing creds) ──▶ delivery_failed
      ▼
    review (independent identity, probes) → verdict RECORDED before any edit
      ▼ accept_with_edit ──▶ rework: edit permitted → RED proof → build → grade → fresh verdict
    accepted | rejected | rework_exhausted

Every arrow above appends to :class:`~crb.factory.evidence.FactoryEvidence`;
every stage emits :class:`~crb.observability.events.StepEvent` rows with
``stage="factory"``. Nothing here decides a verdict: the grader, the probes and
the reviewer do; the loop only sequences them and refuses to skip a step.

Navigation
----------
What it is:   The governed loop — one backlog item end to end, every step evidenced, no
              step skippable.
What it does: Sequences readiness → RED proof (authored or test-first rung) → build ladder
              → optional delivery (default OFF, fails closed) → independent review →
              rework (edit permitted only after a recorded verdict; bounded by
              ``max_rework``), turning every governed refusal into an ``ItemOutcome`` status
              rather than an exception; ``run_backlog`` requires a frozen, verifying
              backlog and records a blocked item explicitly when a dependency was not
              accepted. Emits a ``factory``-stage ``StepEvent`` per step.
How:          ``FactorySpec`` carries every collaborator; ``FactoryLoop.run_item`` walks the
              private ``_assess`` / ``_oracle`` / ``_prove`` / ``_build`` / ``_deliver`` /
              ``_review`` steps under a ``_Stop`` exception that maps to a status.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/factory/evidence.py (every arrow appends), src/crb/factory/readiness.py
              + src/crb/factory/testfirst.py + src/crb/factory/build.py +
              src/crb/factory/delivery.py + src/crb/factory/review.py (the steps, in order),
              src/crb/observability/events.py (``Emitter`` for the step events),
              src/crb/server/routes/factory.py (the HTTP surface — a 501 stub until P6)
Tested by:    tests/test_factory_loop.py
Touch when:   never for a new repository (delivery is switched on per run, not per repo);
              adding a status means ``STATUSES`` here, the UI's factory screen and
              docs/API.md#factory-phase-p6; changing the step order is a governance change
              — an ADR.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.builders.base import Budget, Builder, Rung
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.ledger import JsonlLedger
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig
from crb.factory.backlog import KIND_OPERATOR, Backlog, BacklogError, BacklogItem
from crb.factory.build import BuildResult, build_ladder
from crb.factory.delivery import (
    DeliveryError,
    DeliveryResult,
    GitCredentialsProvider,
    OpenPrFn,
    PushFn,
    deliver,
)
from crb.factory.evidence import EV_BACKLOG_FROZEN, FactoryEvent, FactoryEvidence
from crb.factory.readiness import (
    ROUTE_HUMAN,
    ROUTE_TEST_FIRST,
    GapSignoff,
    JsonlGapSignoffLedger,
    Readiness,
    assess,
)
from crb.factory.review import (
    MechanicalReviewer,
    Probe,
    Reviewer,
    ReviewVerdict,
    permit_edit,
    review,
)
from crb.factory.testfirst import (
    AuthoredTest,
    NotRed,
    RedProof,
    TestAuthor,
    assert_distinct_identity,
    author_label,
    author_test,
    prove_red,
)
from crb.observability.events import Emitter, MemorySink, StepStatus

STAGE = "factory"

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
    STATUS_BLOCKED,
    STATUS_ERROR,
)

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
    target_default_branch: str = "main"
    run_id: str = ""
    actor: str = ""
    timeout: int = 0
    max_rework: int = 1
    rework_test: ReworkTestFn | None = None
    route_decision_for: Callable[[BacklogItem], Mapping[str, Any] | None] | None = None
    keep_workspaces: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ladder", tuple(self.ladder))
        if not self.ladder:
            raise ValueError("ladder must have at least one rung")
        if self.probes is not None:
            object.__setattr__(self, "probes", tuple(self.probes))
        if self.test_author is not None:
            lbl = author_label(self.test_author)
            for r in self.ladder:
                assert_distinct_identity(lbl, r.label, role="builder")
        if self.max_rework < 0:
            raise ValueError("max_rework cannot be negative")


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

    def _assess(self, item: BacklogItem) -> Readiness:
        """Step 1: readiness; stops the item on an unsigned structural gap or a human route."""
        ev = self.spec.evidence
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
        if not r.ready:
            ev.record_route(
                item.id, ROUTE_HUMAN, r.reason, blocking=[g.slot for g in r.blocking_gaps]
            )
            self._emit("readiness.refused", item.id, status=StepStatus.SKIPPED, reason=r.reason)
            raise _Stop(STATUS_NOT_READY, readiness=r)
        ev.record_route(item.id, r.route_hint, r.reason)
        self._emit("route.decided", item.id, route=r.route_hint, reason=r.reason)
        if r.route_hint == ROUTE_HUMAN:
            raise _Stop(STATUS_ROUTED_HUMAN, readiness=r)
        return r

    def _oracle(
        self, item: BacklogItem, r: Readiness, authored: AuthoredTest | None
    ) -> AuthoredTest:
        """Step 2a: the oracle — the caller's authored test, else the test-author rung;
        stops with ``no_oracle`` when neither exists."""
        if authored is not None:
            return authored
        ta = self.spec.test_author
        if ta is None:
            self.spec.evidence.record_red_refused(
                item.id, "no authored test and no test author configured", route=r.route_hint
            )
            raise _Stop(STATUS_NO_ORACLE, readiness=r)
        self._emit("author.start", item.id, author=author_label(ta), route=r.route_hint)
        res = author_test(
            self.repo,
            item,
            ta,
            facts=r.facts,
            config=self.spec.config,
            scratch=self.spec.scratch,
            on_event=self._cb(item.id),
        )
        if r.route_hint != ROUTE_TEST_FIRST:
            self._emit("author.done", item.id, note="authored on the build route (no value gaps)")
        return res.authored

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
    ) -> list[BuildResult]:
        """Step 3: the build ladder; every attempt is recorded, the final one's tree kept."""
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

    def _deliver(self, item: BacklogItem, final: BuildResult) -> tuple[DeliveryResult | None, str]:
        """Step 4: delivery — skipped and RECORDED when opt-in is off; a failure stops the
        item (``delivery_failed``). Returns ``(result, pr_ref)``."""
        s = self.spec
        if not s.deliver:
            s.evidence.record_delivery_refused(
                item.id,
                "delivery is opt-in and OFF — built and graded locally only",
                pack_hash=final.pack_hash,
            )
            self._emit("delivery.skipped", item.id, status=StepStatus.SKIPPED, reason="opt-in off")
            return None, ""
        route = s.route_decision_for(item) if s.route_decision_for is not None else None
        try:
            d = deliver(
                self.repo,
                item,
                final,
                creds=s.creds,
                open_pr_fn=s.open_pr_fn,
                push_fn=s.push_fn,
                target_default_branch=s.target_default_branch,
                pack_link=str(final.pack_path),
                route_decision=route,
            )
        except DeliveryError as exc:
            s.evidence.record_delivery_refused(item.id, str(exc), pack_hash=final.pack_hash)
            self._emit("delivery.error", item.id, status=StepStatus.ERROR, error=str(exc))
            raise _Stop(STATUS_DELIVERY_FAILED, error=str(exc)) from exc
        s.evidence.record_delivery(d.to_dict())
        self._emit("delivery.opened", item.id, branch=d.branch, base=d.base, pr=d.pr_ref)
        return d, d.pr_ref

    def _review(
        self, item: BacklogItem, final: BuildResult, proof: RedProof, pr_ref: str
    ) -> ReviewVerdict:
        """Step 5: independent review; the verdict is on the ledger before this returns."""
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
        )
        self._emit("review.recorded", item.id, verdict=v.verdict, event=v.event_id)
        return v

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
        try:
            readiness = self._assess(item)
            oracle = self._oracle(item, readiness, authored)
            proof = self._prove(item, readiness, oracle)
            results = self._build(item, readiness, oracle, proof, trial_prefix="r")
            builds += [b.summary() for b in results]
            final = results[-1]
            keep.append(final)
            if final.disqualified:
                raise _Stop(STATUS_DISQUALIFIED)
            if not final.clean:
                raise _Stop(STATUS_NOT_CLEAN)
            delivery, pr_ref = self._deliver(item, final)
            verdict = self._review(item, final, proof, pr_ref)
            verdicts.append(verdict)
            while verdict.rework_required and reworks < s.max_rework:
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
                # the reviewed build is fully consumed (verdict on the record); release its
                # worktree so the rework can re-point the delivery branch
                final.close()
                edited = s.rework_test(item, verdict, oracle) if s.rework_test is not None else None
                oracle = edited or oracle
                proof = self._prove(item, readiness, oracle)
                results = self._build(item, readiness, oracle, proof, trial_prefix=f"w{reworks}r")
                builds += [b.summary() for b in results]
                final = results[-1]
                keep.append(final)
                if final.disqualified:
                    raise _Stop(STATUS_DISQUALIFIED)
                if not final.clean:
                    raise _Stop(STATUS_NOT_CLEAN)
                delivery, pr_ref = self._deliver(item, final)
                verdict = self._review(item, final, proof, pr_ref)
                verdicts.append(verdict)
            if verdict.accepted:
                status = STATUS_ACCEPTED
            elif verdict.rework_required:
                status = STATUS_REWORK_EXHAUSTED
            else:
                status = STATUS_REJECTED
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
        s.evidence.record_item_outcome(
            item.id,
            status=status,
            builds=len(builds),
            verdict=outcome.final_verdict.verdict if outcome.final_verdict else "",
            delivered=delivery is not None,
            reworks=reworks,
            error=error,
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
        blocked, never silently skipped."""
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
            unmet = [d for d in item.depends_on if d in outcomes and not outcomes[d].accepted]
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
    "STATUS_REJECTED",
    "STATUS_REWORK_EXHAUSTED",
    "STATUS_ROUTED_HUMAN",
    "FactoryLoop",
    "FactorySpec",
    "ItemOutcome",
    "ReworkTestFn",
]
