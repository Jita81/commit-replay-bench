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
the latest readiness, RED proof, build, delivery (opened, or updated by a rework) and
verdict per item, straight from the evidence events, never from a cached status.

Navigation
----------
What it is:   The factory's file-backed state for one repository under ``CRB_HOME``.
What it does: Registers and freezes a backlog (history kept), opens the evidence chain and
              the gap-sign-off ledger, stores operator-authored tests, and derives the
              per-item task view from the evidence events for the API.
How:          Plain JSON/JSONL under ``<home>/factory/<repo>/``; the backlog is hashed by
              ``crb.factory.backlog`` before it is written; the task view folds the events
              newest-wins per kind per item.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/factory/backlog.py (Backlog/BacklogItem, the hash), src/crb/factory/evidence.py
              (the chain and its event kinds), src/crb/factory/readiness.py (gap sign-offs),
              src/crb/factory/testfirst.py (AuthoredTest), src/crb/server/routes/factory.py
              (the API over this state), src/crb/server/worker.py (the ``factory`` run kind)
Tested by:    tests/test_server_routes_factory.py
Touch when:   a new factory record kind needs serving (add it to task_views), or the layout
              under CRB_HOME changes (update docs/OPERATOR.md and the worker together).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.factory.backlog import Backlog, BacklogError, BacklogItem
from crb.factory.evidence import (
    EV_BUILD,
    EV_DELIVERY,
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
from crb.factory.readiness import JsonlGapSignoffLedger
from crb.factory.testfirst import AuthoredTest

FACTORY_DIR = "factory"


@dataclass(frozen=True)
class TaskView:
    """One backlog item as the API serves it (the UI's ``FactoryTask``)."""

    id: str
    title: str
    capability_class: str
    size: str
    kind: str
    status: str  # the latest item.outcome status, or "pending"
    dor_gaps: tuple[str, ...]
    route_hint: str
    red_proof: bool | None
    build_status: str
    pr_url: str | None
    review_verdict: str | None
    last_event: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "capability_class": self.capability_class,
            "size": self.size,
            "kind": self.kind,
            "status": self.status,
            "dor_gaps": list(self.dor_gaps),
            "route_hint": self.route_hint,
            "red_proof": self.red_proof,
            "build_status": self.build_status,
            "pr_url": self.pr_url,
            "review_verdict": self.review_verdict,
            "last_event": self.last_event,
        }


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
        tmp = self.backlog_path.with_suffix(".json.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self.backlog_path)  # atomic on POSIX: readers see old or new, never half
        return backlog

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

    def save_authored(self, tests: Mapping[str, AuthoredTest]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        body = {
            k: {"path": t.path, "content": t.content, "author": t.author} for k, t in tests.items()
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
        for ev in self.events():
            if ev.item_id:
                latest.setdefault(ev.item_id, {})[ev.kind] = ev  # newest wins per kind
                last_kind[ev.item_id] = ev.kind
        views: list[TaskView] = []
        for item in backlog.ordered():
            by = latest.get(item.id, {})
            readiness = by.get(EV_READINESS)
            gaps = tuple(
                str(g.get("slot", g) if isinstance(g, Mapping) else g)
                for g in (readiness.payload.get("gaps", ()) if readiness else ())
            )
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
            # a rework's re-delivery (`delivery.updated`) carries the SAME pull request the
            # first delivery opened — it always follows an `opened` for the item, and its
            # pr_url is the one to show (DL-045)
            delivery = by.get(EV_DELIVERY_UPDATED) or by.get(EV_DELIVERY)
            pr = str(delivery.payload.get("pr_url", "")) if delivery else ""
            if not pr and by.get(EV_DELIVERY_REFUSED) is not None:
                pr = ""
            verdict = by.get(EV_VERDICT)
            outcome = by.get(EV_ITEM_OUTCOME)
            views.append(
                TaskView(
                    id=item.id,
                    title=item.title,
                    capability_class=item.capability_class,
                    size=item.size_estimate,
                    kind=item.kind,
                    status=str(outcome.payload.get("status", "pending")) if outcome else "pending",
                    dor_gaps=gaps,
                    route_hint=str(route.payload.get("route", "")) if route else "",
                    red_proof=red,
                    build_status=build_status,
                    pr_url=pr or None,
                    review_verdict=str(verdict.payload.get("verdict", "")) if verdict else None,
                    last_event=last_kind.get(item.id, ""),
                )
            )
        return views

    def gap_signoffs(self) -> list[dict[str, Any]]:
        return [
            {**dict(e.payload), "item_id": e.item_id}
            for e in self.events()
            if e.kind == EV_GAP_SIGNOFF
        ]


__all__ = ["FACTORY_DIR", "BacklogError", "FactoryHome", "TaskView"]
