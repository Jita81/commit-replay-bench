"""The factory's per-repository state on disk — backlog, evidence, gap sign-offs, authored tests.

The forward-mode factory (:mod:`crb.factory`) keeps its records as append-only,
hash-chained JSONL files, like evidence packs: the API and the worker share
``CRB_HOME``, so both read and write the same directory, ``<home>/factory/<repo>/``:

    backlog.json            the ACTIVE frozen backlog (``Backlog.to_dict()``)
    backlog-<hash>.json     every backlog ever registered (history, never rewritten)
    evidence.jsonl          the factory evidence chain (``JsonlFactoryStore``)
    gaps.jsonl              structural-gap sign-offs (``JsonlGapSignoffLedger``)
    authored.json           operator-authored oracles per item ``{item_id: {path, content}}``

Nothing here decides anything: the loop, the grader and the reviewer do. This module
only places the records, and derives the task view (:func:`task_views`) a reader sees —
the latest readiness, RED proof, build, delivery (opened, or updated by a rework), verdict
and the pull request's outcome (merged / closed, read back from GitHub — B-9 / F30) per
item, plus the outcome's reason (why a governed stop stopped), straight from the evidence
events, never from a cached status. Every refusal the loop records (a route to a human
at readiness, ``red.refused``, ``delivery.refused``, a dependency block) is folded with
its reason so the page can say why, and the newest build's ids (task, pack, row) let a
reader open the evidence the build produced.

Two more things live here because both the API and the worker need them:

* **Evolutions** (F32): :meth:`FactoryHome.register_evolution` is the only way a frozen
  backlog changes — a NEW item chained onto the frozen hash (``Backlog.evolve``), a
  history copy, a ``backlog.evolved`` event, then the active pointer. The task view shows
  the superseded item as ``superseded`` (with ``superseded_by``) directly above its
  evolution, so the chain reads as it was registered.
* **The outcome sync** (B-9 / F30): :func:`sync_outcomes` reads every delivered pull
  request whose fate can still change — :func:`outcomes_pending`: no outcome yet, or
  ``delivery.closed`` (a person can reopen and merge it); ``delivery.merged`` is terminal
  — through a caller-supplied reader (the installation token's ``GET /pulls/{n}``) and
  records ``delivery.merged`` / ``delivery.closed`` — at most closed then merged per PR;
  a merged one is never read again. Both callers (the worker at the start of every
  factory run, ``POST /factory/{repo}/outcomes/sync``) ask :func:`outcomes_pending`
  before minting a token, so the "nothing to read" decision and the sync share ONE
  predicate; the capability map reads :meth:`FactoryHome.delivery_counts` for
  ``n_delivered`` / ``n_merged`` per cell.

Navigation
----------
What it is:   The factory's file-backed state for one repository under ``CRB_HOME``.
What it does: Registers and freezes a backlog (history kept), registers evolutions onto
              it, opens the evidence chain and the gap-sign-off ledger, stores
              operator-authored tests, derives the per-item task view (with each pull
              request's outcome and each item's supersession) from the evidence events,
              syncs delivered pull requests' outcomes, and counts deliveries per cell.
How:          Plain JSON/JSONL under ``<home>/factory/<repo>/``; the backlog is hashed by
              ``crb.factory.backlog`` before it is written; the task view folds the events
              newest-wins per kind per item, and the newest refusal per item since its
              last readiness pass (:class:`Refusal`); ``sync_outcomes`` is a pure fold
              over a reader callable so the API and the worker share one rule.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/factory/backlog.py (Backlog/BacklogItem, the hash, ``evolve``),
              src/crb/factory/evidence.py (the chain, its event kinds, the closed-then-merged
              outcome recorder), src/crb/factory/readiness.py (gap sign-offs),
              src/crb/factory/testfirst.py (AuthoredTest), src/crb/server/github_app.py
              (``PullRequest`` — what the sync's reader returns), src/crb/server/routes/factory.py
              (the API over this state), src/crb/server/routes/capability.py (reads
              ``delivery_counts`` for the map's cells), src/crb/server/worker.py (the
              ``factory`` run kind; runs the sync first)
Tested by:    tests/test_server_routes_factory.py, tests/test_factory_outcomes.py
Touch when:   a new factory record kind needs serving (add it to task_views), a refusal is
              recorded in a new shape (extend ``_refusal_of``), or the layout under
              CRB_HOME changes (update docs/OPERATOR.md and the worker together).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.redact import redact_and_cap
from crb.factory.backlog import Backlog, BacklogError, BacklogItem
from crb.factory.evidence import (
    EV_BUILD,
    EV_DELIVERY,
    EV_DELIVERY_CLOSED,
    EV_DELIVERY_MERGED,
    EV_DELIVERY_REFUSED,
    EV_DELIVERY_UPDATED,
    EV_GAP_SIGNOFF,
    EV_ITEM_OUTCOME,
    EV_READINESS,
    EV_RED_PROOF,
    EV_RED_REFUSED,
    EV_ROUTE,
    EV_VERDICT,
    FactoryEvent,
    FactoryEvidence,
    JsonlFactoryStore,
)
from crb.factory.readiness import SLOT_STRUCTURAL, SLOT_VALUE, JsonlGapSignoffLedger
from crb.factory.testfirst import AuthoredTest
from crb.server.github_app import PR_CLOSED, PR_MERGED, PR_OPEN, GitHubAppError, PullRequest

FACTORY_DIR = "factory"
#: The task-view status of an item a later evolution replaced (never an ``item.outcome``).
STATUS_SUPERSEDED_WORD = "superseded"

#: The route word the loop records when readiness sends an item to a person.
ROUTE_HUMAN_WORD = "human"
#: The outcome status the loop records for an item whose dependency was not accepted.
STATUS_BLOCKED_WORD = "blocked_on_dependency"


@dataclass(frozen=True)
class Refusal:
    """Why the loop stopped an item, as recorded on the chain: at which ``step``
    (``readiness`` / ``red`` / ``delivery`` / ``review`` / ``dependency``), the ``reason``
    sentence, and — for the route gate — the ``reason_code`` and the ``measured_route`` it
    read. ``review`` is the rule-3 stop (DL-045): a ``route.decided`` to ``human`` recorded
    AFTER a verdict (``after_verdict`` on the payload), so a built and delivered item is
    never read as refused at readiness."""

    step: str
    reason: str
    reason_code: str = ""
    measured_route: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "step": self.step,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "measured_route": self.measured_route,
        }


def _refusal_of(ev: FactoryEvent) -> Refusal | None:
    """The refusal an event records, or None when it is not one."""
    p = ev.payload
    if ev.kind == EV_ROUTE and str(p.get("route", "")) == ROUTE_HUMAN_WORD:
        step = "review" if p.get("after_verdict") else "readiness"
        return Refusal(step, str(p.get("reason", "")))
    if ev.kind == EV_RED_REFUSED:
        return Refusal("red", str(p.get("reason", "")))
    if ev.kind == EV_DELIVERY_REFUSED:
        return Refusal(
            "delivery",
            str(p.get("reason", "")),
            reason_code=str(p.get("reason_code", "")),
            measured_route=str(p.get("measured_route", "")),
        )
    if ev.kind == EV_ITEM_OUTCOME and str(p.get("status", "")) == STATUS_BLOCKED_WORD:
        blocked = ", ".join(str(x) for x in (p.get("blocked_on") or ()))
        return Refusal(
            "dependency", f"waiting on {blocked}" if blocked else "waiting on a dependency"
        )
    return None


@dataclass(frozen=True)
class DeliveryOutcome:
    """The newest delivered pull request's fate: ``state`` is ``open`` (delivered, no
    outcome recorded yet), ``merged`` or ``closed``; the rest is what the outcome event
    carries (empty while open). ``synced_at`` is when the outcome was recorded."""

    state: str
    pr_number: int
    pr_url: str
    merged_at: str = ""
    merged_by: str = ""
    merge_sha: str = ""
    closed_at: str = ""
    synced_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "merged_at": self.merged_at,
            "merged_by": self.merged_by,
            "merge_sha": self.merge_sha,
            "closed_at": self.closed_at,
            "synced_at": self.synced_at,
        }


def _outcome_of(delivery: FactoryEvent, outcome: FactoryEvent | None) -> DeliveryOutcome:
    """The task view's ``outcome`` for the item's newest delivery event and the outcome
    event recorded for that pull request (``None`` = still open as far as the record knows)."""
    number = int(delivery.payload.get("pr_number", 0) or 0)
    url = str(delivery.payload.get("pr_url", ""))
    if outcome is None:
        return DeliveryOutcome(PR_OPEN, number, url)
    p = outcome.payload
    return DeliveryOutcome(
        state=str(p.get("state", "")),
        pr_number=number,
        pr_url=url or str(p.get("pr_url", "")),
        merged_at=str(p.get("merged_at", "")),
        merged_by=str(p.get("merged_by", "")),
        merge_sha=str(p.get("merge_sha", "")),
        closed_at=str(p.get("closed_at", "")),
        synced_at=outcome.created,
    )


@dataclass(frozen=True)
class TaskView:
    """One backlog item as the API serves it (the UI's ``FactoryTask``)."""

    id: str
    title: str
    capability_class: str
    size: str
    kind: str
    status: str  # the latest item.outcome status, or "pending"
    #: Why a governed stop stopped — the item.outcome's ``error`` (``not_red``'s refusal,
    #: ``delivery_failed``'s error, ``oracle_needs_strengthening``'s finding and way
    #: forward); empty when accepted or not yet run.
    outcome_reason: str
    #: The unsigned STRUCTURAL slots — what blocks the build and what an approver can sign.
    dor_gaps: tuple[str, ...]
    route_hint: str
    red_proof: bool | None
    build_status: str
    pr_url: str | None
    review_verdict: str | None
    last_event: str
    #: The open VALUE slots — they route the item test-first and are never signed.
    value_gaps: tuple[str, ...] = ()
    #: The newest refusal since the item's last readiness pass (J-FAC-4); None = not refused.
    refusal: Refusal | None = None
    #: The outcome's ``error`` (a harness failure, a refused push), "" when none.
    error: str = ""
    #: The newest build's ids (F15): the ledger task (the oracle commit), its pack, its row.
    task_id: str = ""
    pack_hash: str = ""
    row_hash: str = ""
    row_id: str = ""
    #: B-9 / F30 — the newest delivered pull request's fate; None = nothing delivered.
    outcome: DeliveryOutcome | None = None
    #: F32 — the item this one replaced (an evolution), and the evolution that replaced
    #: this one (then ``status`` reads ``superseded``); "" when neither.
    supersedes: str = ""
    superseded_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "capability_class": self.capability_class,
            "size": self.size,
            "kind": self.kind,
            "status": self.status,
            "outcome_reason": self.outcome_reason,
            "dor_gaps": list(self.dor_gaps),
            "value_gaps": list(self.value_gaps),
            "route_hint": self.route_hint,
            "red_proof": self.red_proof,
            "build_status": self.build_status,
            "pr_url": self.pr_url,
            "review_verdict": self.review_verdict,
            "last_event": self.last_event,
            "refusal": self.refusal.to_dict() if self.refusal else None,
            "error": self.error,
            "task_id": self.task_id,
            "pack_hash": self.pack_hash,
            "row_hash": self.row_hash,
            "row_id": self.row_id,
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
        }


@dataclass(frozen=True)
class DeliveredPr:
    """One pull request the factory delivered, and its recorded outcome event (if any)."""

    item_id: str
    pr_number: int
    pr_url: str
    outcome: FactoryEvent | None = None


@dataclass
class DeliveryCounts:
    """Counts for one cell: pull requests opened, merged, closed without merging."""

    n_delivered: int = 0
    n_merged: int = 0
    n_closed: int = 0


def delivery_counts_matching(
    counts: Mapping[tuple[str, str], DeliveryCounts], capability_class: str, size: str
) -> tuple[int, int]:
    """``(n_delivered, n_merged)`` summed over the cells a projected key covers: a key
    field that reads ``"*"`` (not projected) matches every value."""
    delivered = merged = 0
    for (cls, sz), c in counts.items():
        if capability_class in ("*", cls) and size in ("*", sz):
            delivered += c.n_delivered
            merged += c.n_merged
    return delivered, merged


@dataclass
class OutcomeSyncReport:
    """What one sync did: pull requests looked at, outcomes recorded by kind, the ones still
    open, and per-PR read failures (redacted, never raised — a sync is best-effort and
    the next one retries)."""

    checked: int = 0
    merged: int = 0
    closed: int = 0
    open: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "merged": self.merged,
            "closed": self.closed,
            "open": self.open,
            "errors": list(self.errors),
        }


#: ``read_pr(pr_number) -> PullRequest`` — how the sync reads one pull request's state.
ReadPrFn = Callable[[int], PullRequest]


def outcomes_pending(home: FactoryHome) -> list[DeliveredPr]:
    """Deliveries whose fate can still change: no outcome yet, or ``delivery.closed`` — a
    person can reopen a closed pull request and merge it. ``delivery.merged`` is terminal
    (the ledger refuses anything after a merge), so a merged delivery is never read again.
    The ONE place this rule lives: :func:`sync_outcomes` iterates it, and both callers
    ask it before minting an installation token (an empty answer mints nothing)."""
    return [
        d for d in home.deliveries() if d.outcome is None or d.outcome.kind != EV_DELIVERY_MERGED
    ]


def sync_outcomes(home: FactoryHome, read_pr: ReadPrFn, *, actor: str) -> OutcomeSyncReport:
    """Read every delivered pull request whose fate can still change
    (:func:`outcomes_pending`: no outcome on the chain yet, or ``delivery.closed`` — a
    person can reopen and merge it) and record ``delivery.merged`` / ``delivery.closed``
    for the ones that ended: at most closed then merged per PR (the evidence ledger refuses
    a repeat of the same state and anything after a merge). A merged PR is never read
    again; a PR still open records nothing; a read that fails is an entry in ``errors``
    and the PR is retried by the next sync."""
    report = OutcomeSyncReport()
    ev = home.evidence(actor=actor)
    for d in outcomes_pending(home):
        report.checked += 1
        try:
            pr = read_pr(d.pr_number)
        except GitHubAppError as exc:
            report.errors.append(
                f"PR #{d.pr_number} ({d.item_id}): {redact_and_cap(str(exc), max_chars=300)}"
            )
            continue
        if pr.outcome == PR_OPEN:
            report.open += 1
            continue
        _, recorded = ev.record_delivery_outcome(
            d.item_id,
            state=pr.outcome,
            pr_number=d.pr_number,
            pr_url=d.pr_url or pr.html_url,
            merged_at=pr.merged_at,
            merged_by=pr.merged_by,
            merge_sha=pr.merge_commit_sha,
            closed_at=pr.closed_at,
        )
        if recorded and pr.outcome == PR_MERGED:
            report.merged += 1
        elif recorded and pr.outcome == PR_CLOSED:
            report.closed += 1
    return report


class FactoryHome:
    """``<home>/factory/<repo>/`` — see the module docstring."""

    def __init__(self, home: str | Path, repo: str) -> None:
        self.repo = repo
        self.dir = Path(home) / FACTORY_DIR / repo

    # --- backlog -------------------------------------------------------------------
    @property
    def backlog_path(self) -> Path:
        return self.dir / "backlog.json"

    def load_backlog(self) -> Backlog | None:
        if not self.backlog_path.exists():
            return None
        return Backlog.from_dict(json.loads(self.backlog_path.read_text(encoding="utf-8")))

    def register_backlog(self, items: list[BacklogItem], *, actor: str) -> Backlog:
        """Freeze ``items`` as the repo's ACTIVE backlog and record the freeze in the
        evidence chain. The previous active backlog stays in the history files. Raises
        :class:`BacklogError` when the items do not validate (the loop's own rules)."""
        backlog = Backlog(items=tuple(items), repo=self.repo).freeze()
        self.dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(backlog.to_dict(), sort_keys=True, ensure_ascii=False, indent=1)
        # Order matters: history file, then the freeze EVENT, and only then the active
        # pointer. A failure in the evidence append leaves the previous active backlog
        # intact and one unreferenced history file behind — never an active backlog the
        # chain does not cover (CodeRabbit on PR #4, 2026-09-15).
        (self.dir / f"backlog-{backlog.backlog_hash[:16]}.json").write_text(body, encoding="utf-8")
        self.evidence(actor=actor).record_freeze(
            backlog_hash=backlog.backlog_hash,
            item_ids=[i.id for i in backlog.items],
            frozen_at=backlog.frozen_at,
        )
        self._write_active(body)
        return backlog

    def register_evolution(self, item: BacklogItem, *, actor: str) -> Backlog:
        """Register an evolution onto the ACTIVE frozen backlog (F32): a NEW item, optionally
        superseding one (``item.supersedes``), through :meth:`Backlog.evolve` — the frozen
        record is untouched, the evolutions chain hash is extended. Same order as a freeze:
        history copy, the ``backlog.evolved`` event, then the active pointer. Raises
        :class:`BacklogError` (``BacklogFrozen`` for an id that exists or an item already
        superseded) and ``LookupError`` when no backlog is registered."""
        backlog = self.load_backlog()
        if backlog is None:
            raise LookupError(f"no backlog registered for {self.repo!r}")
        evolved = backlog.evolve(item)
        body = json.dumps(evolved.to_dict(), sort_keys=True, ensure_ascii=False, indent=1)
        (self.dir / f"backlog-{evolved.evolutions_hash[:16]}.json").write_text(
            body, encoding="utf-8"
        )
        self.evidence(actor=actor).record_evolution(
            item_id=item.id,
            supersedes=item.supersedes,
            backlog_hash=evolved.backlog_hash,
            evolutions_hash=evolved.evolutions_hash,
        )
        self._write_active(body)
        return evolved

    def _write_active(self, body: str) -> None:
        tmp = self.backlog_path.with_suffix(".json.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self.backlog_path)  # atomic on POSIX: readers see old or new, never half

    # --- evidence / sign-offs / authored tests ----------------------------------------
    def evidence(self, *, actor: str = "") -> FactoryEvidence:
        self.dir.mkdir(parents=True, exist_ok=True)
        return FactoryEvidence(
            JsonlFactoryStore(self.dir / "evidence.jsonl"), actor=actor, repo=self.repo
        )

    def gap_ledger(self) -> JsonlGapSignoffLedger:
        self.dir.mkdir(parents=True, exist_ok=True)
        return JsonlGapSignoffLedger(self.dir / "gaps.jsonl")

    @property
    def authored_path(self) -> Path:
        return self.dir / "authored.json"

    def authored(self) -> dict[str, AuthoredTest]:
        if not self.authored_path.exists():
            return {}
        raw = json.loads(self.authored_path.read_text(encoding="utf-8"))
        return {
            k: AuthoredTest(path=str(v["path"]), content=str(v["content"]), author=str(v["author"]))
            for k, v in raw.items()
        }

    def save_authored(self, tests: Mapping[str, AuthoredTest], *, merge: bool = False) -> None:
        """Store operator-authored oracles per item; ``merge=True`` keeps the ones already
        stored for other items (an evolution adds its oracle beside the frozen items')."""
        self.dir.mkdir(parents=True, exist_ok=True)
        kept = self.authored() if merge else {}
        body = {
            k: {"path": t.path, "content": t.content, "author": t.author}
            for k, t in {**kept, **dict(tests)}.items()
        }
        self.authored_path.write_text(
            json.dumps(body, sort_keys=True, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # --- the task view ---------------------------------------------------------------
    def events(self) -> list[FactoryEvent]:
        if not (self.dir / "evidence.jsonl").exists():
            return []
        return self.evidence().events()

    def task_views(self) -> list[TaskView]:
        """The latest state of every active backlog item, folded from the evidence."""
        backlog = self.load_backlog()
        if backlog is None:
            return []
        latest: dict[str, dict[str, FactoryEvent]] = {}
        last_kind: dict[str, str] = {}  # the kind of each item's newest event
        refusals: dict[str, Refusal] = {}  # newest refusal since the item's last readiness
        # the newest delivery event of EITHER kind, in chain order: a rework's re-delivery
        # (`delivery.updated`) carries the SAME pull request the first delivery opened
        # (DL-045), but a later run may open a FRESH one (the branch deleted after the
        # first PR closed) — so recency decides, never a preference between the kinds
        latest_delivery: dict[str, FactoryEvent] = {}
        # (item, pr_number) → its outcome event (merged / closed); at most one per PR
        outcomes: dict[tuple[str, int], FactoryEvent] = {}
        for ev in self.events():
            if ev.item_id:
                latest.setdefault(ev.item_id, {})[ev.kind] = ev  # newest wins per kind
                last_kind[ev.item_id] = ev.kind
                if ev.kind == EV_READINESS:
                    # a new pass over the item: the last pass's refusal no longer stands
                    refusals.pop(ev.item_id, None)
                refusal = _refusal_of(ev)
                if refusal is not None:
                    refusals[ev.item_id] = refusal
                if ev.kind in (EV_DELIVERY, EV_DELIVERY_UPDATED):
                    latest_delivery[ev.item_id] = ev
                if ev.kind in (EV_DELIVERY_MERGED, EV_DELIVERY_CLOSED):
                    outcomes[(ev.item_id, int(ev.payload.get("pr_number", 0) or 0))] = ev
        superseded_by = backlog.superseded_by()
        views: list[TaskView] = []
        # the active items in dependency order, each evolution preceded by what it replaced
        # (oldest first) so the chain reads as it was registered (F32)
        ordered: list[BacklogItem] = []
        for active in backlog.ordered():
            ordered.extend(i for i in backlog.lineage(active.id) if i not in ordered)
        for item in ordered:
            by = latest.get(item.id, {})
            readiness = by.get(EV_READINESS)
            # structural gaps block the build and are what an approver signs; value gaps only
            # route (test-first) and are never signable — serve them apart so the page never
            # offers one for signing (readiness.Gap: ``kind``; a record without it is structural)
            structural: list[str] = []
            values: list[str] = []
            for g in readiness.payload.get("gaps", ()) if readiness else ():
                if isinstance(g, Mapping):
                    slot = str(g.get("slot", ""))
                    (
                        values if str(g.get("kind", SLOT_STRUCTURAL)) == SLOT_VALUE else structural
                    ).append(slot)
                else:
                    structural.append(str(g))
            route = by.get(EV_ROUTE)
            proof = by.get(EV_RED_PROOF)
            refused = by.get(EV_RED_REFUSED)
            red: bool | None = True if proof else (False if refused else None)
            build = by.get(EV_BUILD)
            build_status = "not_built"
            if build is not None:
                build_status = (
                    "clean"
                    if build.payload.get("clean")
                    else ("disqualified" if build.payload.get("disqualified") else "not_clean")
                )
            delivery = latest_delivery.get(item.id)
            pr = str(delivery.payload.get("pr_url", "")) if delivery else ""
            if not pr and by.get(EV_DELIVERY_REFUSED) is not None:
                pr = ""
            pr_outcome: DeliveryOutcome | None = None
            if delivery is not None:
                number = int(delivery.payload.get("pr_number", 0) or 0)
                pr_outcome = _outcome_of(delivery, outcomes.get((item.id, number)))
            verdict = by.get(EV_VERDICT)
            outcome = by.get(EV_ITEM_OUTCOME)
            replaced_by = superseded_by.get(item.id, "")
            status = str(outcome.payload.get("status", "pending")) if outcome else "pending"
            views.append(
                TaskView(
                    id=item.id,
                    title=item.title,
                    capability_class=item.capability_class,
                    size=item.size_estimate,
                    kind=item.kind,
                    status=STATUS_SUPERSEDED_WORD if replaced_by else status,
                    outcome_reason=str(outcome.payload.get("error", "")) if outcome else "",
                    dor_gaps=tuple(structural),
                    value_gaps=tuple(values),
                    route_hint=str(route.payload.get("route", "")) if route else "",
                    red_proof=red,
                    build_status=build_status,
                    pr_url=pr or None,
                    review_verdict=str(verdict.payload.get("verdict", "")) if verdict else None,
                    last_event=last_kind.get(item.id, ""),
                    refusal=refusals.get(item.id),
                    error=str(outcome.payload.get("error", "") or "") if outcome else "",
                    task_id=str(build.payload.get("oracle_commit", "")) if build else "",
                    pack_hash=str(build.payload.get("pack_hash", "")) if build else "",
                    row_hash=str(build.payload.get("row_hash", "")) if build else "",
                    row_id=str(build.payload.get("row_id", "")) if build else "",
                    outcome=pr_outcome,
                    supersedes=item.supersedes,
                    superseded_by=replaced_by,
                )
            )
        return views

    # --- delivered pull requests and their outcomes (B-9 / F30) --------------------------
    def deliveries(self) -> list[DeliveredPr]:
        """Every pull request the factory delivered (one per distinct ``(item, pr_number)``,
        from ``delivery.opened`` / ``delivery.updated``), with the outcome event recorded
        for it when there is one — in chain order of first delivery."""
        seen: dict[tuple[str, int], DeliveredPr] = {}
        outcomes: dict[tuple[str, int], FactoryEvent] = {}
        for ev in self.events():
            number = int(ev.payload.get("pr_number", 0) or 0)
            if ev.kind in (EV_DELIVERY, EV_DELIVERY_UPDATED) and number > 0:
                seen.setdefault(
                    (ev.item_id, number),
                    DeliveredPr(ev.item_id, number, str(ev.payload.get("pr_url", ""))),
                )
            elif ev.kind in (EV_DELIVERY_MERGED, EV_DELIVERY_CLOSED):
                outcomes[(ev.item_id, number)] = ev
        return [
            DeliveredPr(d.item_id, d.pr_number, d.pr_url, outcome=outcomes.get(key))
            for key, d in seen.items()
        ]

    def delivery_counts(self) -> dict[tuple[str, str], DeliveryCounts]:
        """Per ``(capability_class, size)`` of the delivering item: how many pull requests
        the factory opened there and how many of them merged / closed — COUNTS for the
        capability map's cells (no rate, no interval: a merge is a human act, not a
        measurement of the builder). Items of a re-registered backlog that the active
        record no longer names are counted under their last known cell when the chain
        still carries them; otherwise they are skipped."""
        backlog = self.load_backlog()
        cell_of: dict[str, tuple[str, str]] = {}
        if backlog is not None:
            for it in backlog.all_items():
                cell_of[it.id] = (it.capability_class, it.size_estimate)
        out: dict[tuple[str, str], DeliveryCounts] = {}
        for d in self.deliveries():
            cell = cell_of.get(d.item_id)
            if cell is None:
                continue
            c = out.setdefault(cell, DeliveryCounts())
            c.n_delivered += 1
            if d.outcome is not None and d.outcome.kind == EV_DELIVERY_MERGED:
                c.n_merged += 1
            elif d.outcome is not None:
                c.n_closed += 1
        return out

    def outcomes_summary(self) -> dict[str, Any]:
        """``{delivered, merged, closed, open, last_synced}`` over every delivered pull
        request — the fact Home's task 8 reads (a merged delivery = the loop closed once)."""
        ds = self.deliveries()
        merged = [d for d in ds if d.outcome is not None and d.outcome.kind == EV_DELIVERY_MERGED]
        closed = [d for d in ds if d.outcome is not None and d.outcome.kind == EV_DELIVERY_CLOSED]
        synced = [d.outcome.created for d in ds if d.outcome is not None]
        return {
            "delivered": len(ds),
            "merged": len(merged),
            "closed": len(closed),
            "open": len(ds) - len(merged) - len(closed),
            "last_synced": max(synced) if synced else "",
        }

    def gap_signoffs(self) -> list[dict[str, Any]]:
        return [
            {**dict(e.payload), "item_id": e.item_id}
            for e in self.events()
            if e.kind == EV_GAP_SIGNOFF
        ]


__all__ = [
    "FACTORY_DIR",
    "STATUS_SUPERSEDED_WORD",
    "BacklogError",
    "DeliveredPr",
    "DeliveryCounts",
    "DeliveryOutcome",
    "FactoryHome",
    "OutcomeSyncReport",
    "ReadPrFn",
    "Refusal",
    "TaskView",
    "delivery_counts_matching",
    "outcomes_pending",
    "sync_outcomes",
]
