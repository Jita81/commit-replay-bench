"""``/factory/{repo}/*`` — the forward-mode factory's API: backlog, tasks, gap sign-offs, evidence.

The factory manufactures NEW work under the same governance as a replay (ADR-0001
belts, the append-only ledger, evidence packs, an independent review with the verdict
recorded before any edit — :mod:`crb.factory.loop`). This module serves its records:

* ``POST /factory/{repo}/backlog`` (operator) — register a backlog: the items are
  validated by the factory's own rules, frozen and hashed (:mod:`crb.factory.backlog`),
  written under ``CRB_HOME`` with the freeze recorded in the evidence chain; optional
  operator-authored oracles per item. Refused (409) while a ``factory`` run for the repo
  is queued or running — the hash a run verifies against must not move under it.
* ``GET /factory/{repo}/backlog`` — the active frozen backlog (404 when none), its
  evolutions, the delivery pre-flight (``delivery``: whether a run could open a pull
  request for this repository, by the same rule the worker's credentials follow —
  J-FAC-3) and the outcomes summary (``outcomes``: pull requests delivered / merged /
  closed / open — what Home's task 8 reads).
* ``POST /factory/{repo}/backlog/evolutions`` (operator) — register an evolution (F32): a
  NEW item chained onto the frozen hash, optionally superseding one; the frozen record
  never changes. Same authored-oracle handling and the same active-run refusal as
  registration.
* ``GET /factory/{repo}/tasks`` — every item's latest state, folded from the evidence,
  with every refusal's reason, the newest build's ids (J-FAC-4 / F15), the pull request's
  outcome (B-9 / F30), the item's place in its supersession chain (F32) and, for an item
  the loop stopped, ``way_forward`` — the evolutions route that supersedes it.
* ``POST /factory/{repo}/outcomes/sync`` (operator) — read each delivered pull request's
  state through the installation token and record ``delivery.merged`` /
  ``delivery.closed`` — at most closed then merged per PR (the worker does the same at
  the start of every factory run).
* ``POST /factory/{repo}/tasks/{id}/signoff-gap`` (approver) — sign one structural
  gap: appended to the hash-chained gap ledger and echoed into the evidence chain.
  Value slots cannot be signed (the DoR gate refuses them by design).
* ``GET /factory/{repo}/evidence`` — the chain, oldest first.
* ``GET /factory/{repo}/intake`` — the watched column as the last read saw it: the
  listener (default OFF), the deployment's tracker connection (no secret), the last
  poll's outcome and every ticket with its draft, its label and the feedback the
  ticket carries. No tracker is contacted by this route.
* ``PUT /factory/{repo}/intake`` (operator) — switch this repository's listener on or
  off: the consent gate for reading somebody's board, recorded with the actor.
* ``POST /factory/{repo}/intake/poll`` (operator) — read the column now, doing what the
  worker's timer would have done (ADR-0017).

Running the loop is a run kind: ``POST /runs {kind: "factory"}`` (see ``routes/runs.py``
and the worker); this module never builds anything.

Navigation
----------
What it is:   The API over the factory's per-repo state (``FactoryHome``).
What it does: Registers/freezes backlogs and their evolutions, serves the task view and
              the evidence chain, records approver gap sign-offs, syncs delivered pull
              requests' outcomes; every write is append-only and hashed.
How:          Thin FastAPI handlers → ``crb.server.factory_state.FactoryHome`` →
              ``crb.factory`` dataclasses; role gates from ``crb.server.auth``; the sync
              builds a request-scoped ``GitHubApp`` over the installation on record.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/factory_state.py (the state), src/crb/factory/backlog.py (item
              validation + hash), src/crb/factory/readiness.py (slots, sign), src/crb/server/worker.py
              (the ``factory`` run kind that consumes the backlog; ``_delivery_credentials`` is
              the rule ``_delivery_preflight`` mirrors), src/crb/server/routes/github.py (the
              installation record the pre-flight reads), src/crb/server/github_app.py
              (``pull_request`` — the outcome sync's reader), src/crb/server/intake.py
              (the listener these three routes serve and configure), docs/API.md (the
              contract), ui/src/screens/Factory/FactoryPage.tsx (the screen),
              ui/src/screens/Factory/IntakePage.tsx (the intake screen)
Tested by:    tests/test_server_routes_factory.py, tests/test_factory_outcomes.py,
              tests/test_server_routes_intake.py
Touch when:   a factory record gains a field the UI needs (extend TaskView + FactoryTask in
              ui/src/api/types.ts together); a new write path (keep it append-only, role-gated).
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from crb.core.capability import PROJECTION_CLASS_SIZE
from crb.core.redact import redact_and_cap_head
from crb.core.routing import ROUTE_DELIVER
from crb.core.spec import SIZE_TIER_NAMES
from crb.factory.backlog import KINDS, LEVELS, BacklogError, BacklogFrozen, BacklogItem
from crb.factory.evidence import verify_events
from crb.factory.readiness import CATALOGUE, SLOT_VALUE, sign, slots_for
from crb.factory.testfirst import AuthoredTest
from crb.intake.client import TrackerError
from crb.server.auth import ApproverDep, OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.factory_state import (
    FactoryHome,
    OutcomeSyncReport,
    outcomes_pending,
    sync_outcomes,
)
from crb.server.github_app import GitHubApp, GitHubAppError, permissions_allow_delivery
from crb.server.intake import CONFIG_KEY as INTAKE_CONFIG_KEY
from crb.server.intake import IntakeStore, ListenerState, build_tracker, poll_repository
from crb.server.routes.capability import rows_for_apparatus, rows_for_mode, signed_map
from crb.server.routes.oracle import latest_controls_verdict
from crb.server.routes.repos import get_repo_or_404
from crb.server.secrets import TRACKER_TOKEN_SECRET, SecretsDep
from crb.store.ledger import DbLedger
from crb.store.models import GitHubInstallation, Grade, Repo, Run

router = APIRouter(tags=["factory"])
_ERR = {"model": ErrorEnvelope}
ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running")


# --- schemas --------------------------------------------------------------------------


class BacklogItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    title: str = Field(min_length=1, max_length=200)
    kind: str = "code"
    description: str = Field(default="", max_length=8000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    capability_class: str = Field(default="(unclassified)", max_length=64)
    size_estimate: str = Field(default="S", max_length=4)
    structural_facts: list[str] = Field(default_factory=list, max_length=100)
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    level: str = "L1"
    labels: dict[str, str] = Field(default_factory=dict)


class AuthoredTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=400)
    content: str = Field(min_length=1, max_length=200_000)


class BacklogRegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BacklogItemIn] = Field(min_length=1, max_length=500)
    #: operator-authored oracles, keyed by item id (author recorded as ``operator:<id>``)
    authored: dict[str, AuthoredTestIn] = Field(default_factory=dict)


class EvolutionItemIn(BacklogItemIn):
    """An evolution: a backlog item plus the id it supersedes ("" = a pure amendment)."""

    supersedes: str = Field(default="", max_length=64)


class EvolutionRegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: EvolutionItemIn
    #: the evolution's operator-authored oracle (the superseded item's stays on record)
    authored: AuthoredTestIn | None = None


class BacklogItemOut(BaseModel):
    id: str
    title: str
    kind: str
    capability_class: str
    size: str
    level: str
    depends_on: list[str]
    structural_facts: list[str]
    has_authored_test: bool
    #: What and why, as the operator wrote it — served so a revised backlog can start
    #: from the active one (J-FAC-15).
    description: str = ""
    #: F32 — the item this evolution replaced, and the evolution that replaced this item.
    supersedes: str = ""
    superseded_by: str = ""


class DeliveryPreflightOut(BaseModel):
    """Whether a factory run could open a pull request for this repository — the worker's
    credentials rule (``Worker._delivery_credentials``) answered BEFORE any build is paid
    for: linked through the GitHub App, on the app's own host, the installation on record,
    not suspended, holding ``Contents: write`` and ``Pull requests: write``. ``reason`` is
    the sentence the page shows when it cannot; ``reason_code`` is one of ``ok``,
    ``not_linked``, ``app_not_configured``, ``host_mismatch``, ``installation_missing``,
    ``installation_suspended``, ``read_only``."""

    can_deliver: bool = False
    reason_code: str = "not_linked"
    reason: str = ""
    full_name: str = ""
    default_branch: str = ""
    installation_id: int | None = None
    account_login: str = ""


class OutcomesSummaryOut(BaseModel):
    """Pull requests the factory delivered on this repository and how they ended —
    COUNTS (a merge is a human act, never a rate). ``merged > 0`` is the fact Home's task 8
    reads as "the loop closed once". ``last_synced`` is the newest outcome's record time."""

    delivered: int = 0
    merged: int = 0
    closed: int = 0
    open: int = 0
    last_synced: str = ""


class FactoryBacklogOut(BaseModel):
    repo: str
    hash: str
    frozen_at: str | None
    items: list[BacklogItemOut]
    #: J-FAC-3 — where a run would deliver, or why it cannot.
    delivery: DeliveryPreflightOut = DeliveryPreflightOut()
    #: F32 — every evolution in registration order (superseded ones included) and the
    #: chain hash over them ("" when none).
    evolutions: list[BacklogItemOut] = []
    evolutions_hash: str = ""
    #: B-9 / F30 — delivered pull requests by outcome.
    outcomes: OutcomesSummaryOut = OutcomesSummaryOut()


class DeliveryOutcomeOut(BaseModel):
    """The newest delivered pull request's fate (``factory_state.DeliveryOutcome``)."""

    state: str
    pr_number: int
    pr_url: str
    merged_at: str = ""
    merged_by: str = ""
    merge_sha: str = ""
    closed_at: str = ""
    synced_at: str = ""


class OutcomeSyncOut(BaseModel):
    """What one sync did (``factory_state.OutcomeSyncReport``) plus the outcomes summary
    after it."""

    checked: int
    merged: int
    closed: int
    open: int
    errors: list[str]
    outcomes: OutcomesSummaryOut


class CellRouteOut(BaseModel):
    """The capability map's decision for the item's (class × size) cell — the SAME signed
    map the delivery gate reads (sighted rows, current apparatus, the repo's latest
    controls verdict, sign-offs overlaid — DL-038), shown BEFORE a run spends anything.
    ``route`` is empty when nobody has measured the cell: delivery would be withheld."""

    route: str = ""
    reason_code: str = ""
    reason: str = ""
    n: int = 0
    #: The cell's measured clean rate with its 95 % Wilson interval and the apparatus its
    #: rows carry — the provenance behind the route (0 / empty when not measured).
    point: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    apparatus_versions: list[str] = []
    #: True only when the gate would let a clean build of this item open a pull request.
    deliverable: bool = False


class RefusalOut(BaseModel):
    """Why the loop stopped the item, from the chain (``factory_state.Refusal``)."""

    step: str
    reason: str
    reason_code: str = ""
    measured_route: str = ""


class EvolutionPrefillOut(BaseModel):
    """The superseding item, pre-filled — the body an operator POSTs to the way forward's
    ``route``, so the next step is a review of a draft rather than retyping what the
    product already knows (G-904).

    Every field but ``id`` and ``description`` is the stopped item's own. ``id`` is the
    next free ``<id>-v<n>`` (the register route refuses an id that exists). ``description``
    is the stopped item's description followed by what the stop asked for — for a
    ``oracle_needs_strengthening`` stop, the reviewer's own finding, verbatim, so the
    person strengthening the test can read what was too weak. Nothing here is a decision:
    the operator edits it and posts it, or does not.
    """

    id: str
    title: str
    kind: str
    description: str
    capability_class: str
    size_estimate: str
    structural_facts: list[str]
    acceptance_criteria: list[str]
    depends_on: list[str]
    level: str
    supersedes: str


class WayForwardOut(BaseModel):
    """The next action the API serves for a stopped item: register an evolution that
    supersedes it (F32) — ``route`` is the path to POST to, ``supersedes`` the item id.

    ``what_to_change`` is one plain sentence naming what must be different about the
    superseding item for the loop to get further than this stop; ``prefill`` is that item
    already drafted (``null`` only when the item is not in the backlog the API can read).
    ``needs_authored_test`` says whether the POST should carry an ``authored`` oracle —
    true when the stop was about the test itself.
    """

    action: str = "register_evolution"
    route: str
    supersedes: str
    what_to_change: str = ""
    needs_authored_test: bool = False
    prefill: EvolutionPrefillOut | None = None


class FactoryTaskOut(BaseModel):
    id: str
    title: str
    capability_class: str
    size: str
    kind: str
    status: str
    #: Why a governed stop stopped (the item.outcome's ``error``); ``""`` otherwise.
    outcome_reason: str
    #: The unsigned STRUCTURAL slots: what blocks the build and what an approver can sign.
    dor_gaps: list[str]
    #: The open VALUE slots: they route the item test-first and are never signable.
    value_gaps: list[str] = []
    route_hint: str
    red_proof: bool | None
    build_status: str
    pr_url: str | None
    review_verdict: str | None
    last_event: str
    #: J-FAC-4 — the newest refusal since the item's last readiness pass; null = none.
    refusal: RefusalOut | None = None
    #: The outcome's error (a harness failure, a refused push); "" when none.
    error: str = ""
    #: F15 — the newest build's ledger task (the oracle commit), run, pack and row.
    task_id: str = ""
    run_id: str = ""
    pack_hash: str = ""
    row_hash: str = ""
    #: F28 — the cell's route before the run (absent fields = not measured).
    cell_route: CellRouteOut = CellRouteOut()
    #: B-9 / F30 — the newest delivered pull request's fate; null = nothing delivered.
    outcome: DeliveryOutcomeOut | None = None
    #: F32 — the supersession chain: what this item replaced / what replaced it.
    supersedes: str = ""
    superseded_by: str = ""
    #: The served link for a stopped item (a readiness / red / review refusal, a rejected
    #: or rework-exhausted verdict, no oracle): the evolutions route that supersedes it.
    #: null while the item is not stopped or already superseded.
    way_forward: WayForwardOut | None = None


#: The statuses whose way forward is a superseding evolution (the loop stopped the item
#: for a reason a revised item answers); a dependency block or a delivery refusal is not.
_STOPPED_STATUSES = frozenset(
    {
        "not_ready",
        "not_red",
        "no_oracle",
        "oracle_needs_strengthening",
        "rejected",
        "rework_exhausted",
    }
)
_STOPPED_STEPS = frozenset({"readiness", "red", "review"})

#: Per stopped status: the sentence naming what must be different about the superseding
#: item, and whether the POST should carry an oracle of its own. A stop about the TEST
#: needs a stronger test; a stop about the FACTS needs a fact.
_WHAT_TO_CHANGE: dict[str, tuple[str, bool]] = {
    "oracle_needs_strengthening": (
        "Strengthen the test so it fails for the reason the review gave, then register "
        "this item with the stronger test attached.",
        True,
    ),
    "no_oracle": (
        "Attach a test that fails on the repository as it stands today: nothing proved this "
        "item before the change, so there was nothing to build against.",
        True,
    ),
    "not_red": (
        "Attach a test that fails on the repository as it stands today — the one on record "
        "did not.",
        True,
    ),
    "not_ready": (
        "Add the structural fact the readiness gate asked for, as a `slot: text` line.",
        False,
    ),
    "rejected": ("Answer what the review rejected, then register the revised item.", False),
    "rework_exhausted": (
        "Answer what the review kept asking for, then register the revised item.",
        False,
    ),
}
_DEFAULT_WHAT_TO_CHANGE = (
    "Change what the stop asked for, then register the revised item.",
    False,
)
#: How far the stop's own reason is quoted into the pre-filled description. The HEAD is
#: kept: a stop's reason is read off its prefix (the finding, then the way forward).
_REASON_CHARS = 1000
#: ``BacklogItemIn.description``'s own limit — the draft must be a body the register route
#: accepts unedited, so the item's words plus the stop's reason are capped to it.
_DESCRIPTION_CHARS = 8000


def _next_item_id(base: str, taken: Iterable[str]) -> str:
    """``<base>-v2``, ``-v3`` … — the first that is free. The register route refuses an id
    that exists, so a pre-filled body must not arrive carrying one."""
    used = set(taken)
    stem = re.sub(r"-v\d+$", "", base)[:56] or "item"
    n = 2
    while f"{stem}-v{n}" in used:
        n += 1
    return f"{stem}-v{n}"


def _prefill(item: BacklogItem, *, taken: Iterable[str], reason: str) -> EvolutionPrefillOut:
    """The stopped item, drafted again as its successor, with the stop's own reason in the
    description — so the person reads what was wrong where they will fix it."""
    note = (
        f"\n\nWhy the last attempt stopped: {redact_and_cap_head(reason, max_chars=_REASON_CHARS)}"
    )
    return EvolutionPrefillOut(
        id=_next_item_id(item.id, taken),
        title=item.title,
        kind=item.kind,
        description=(item.description + note).strip()[:_DESCRIPTION_CHARS],
        capability_class=item.capability_class,
        size_estimate=item.size_estimate,
        structural_facts=list(item.structural_facts),
        acceptance_criteria=list(item.acceptance_criteria),
        depends_on=list(item.depends_on),
        level=item.level,
        supersedes=item.id,
    )


def _way_forward(
    repo: str,
    view: Mapping[str, Any],
    *,
    item: BacklogItem | None = None,
    taken: Iterable[str] = (),
) -> WayForwardOut | None:
    """The evolutions route as the next action, for an item the loop stopped and no
    evolution has replaced yet; ``None`` otherwise.

    When the item itself can be read (``item``), the superseding item is served
    pre-filled from it and from the stop's own reason (G-904): on an
    ``oracle_needs_strengthening`` verdict that reason is the reviewer's weak-oracle
    finding, so the draft says what was too weak about the test it must strengthen.
    """
    if view.get("superseded_by"):
        return None
    refusal = dict(view.get("refusal") or {})
    status = str(view.get("status") or "")
    stopped = status in _STOPPED_STATUSES or refusal.get("step") in _STOPPED_STEPS
    if not stopped:
        return None
    what, needs_test = _WHAT_TO_CHANGE.get(status, _DEFAULT_WHAT_TO_CHANGE)
    reason = str(view.get("outcome_reason") or refusal.get("reason") or "")
    return WayForwardOut(
        route=f"/factory/{repo}/backlog/evolutions",
        supersedes=str(view.get("id", "")),
        what_to_change=what,
        needs_authored_test=needs_test,
        prefill=_prefill(item, taken=taken, reason=reason) if item is not None else None,
    )


class CatalogueSlotOut(BaseModel):
    name: str
    question: str
    #: ``structural`` blocks the build until signed; ``value`` only routes (readiness.py).
    kind: str


class CatalogueClassOut(BaseModel):
    capability_class: str
    slots: list[CatalogueSlotOut]


class FactoryCatalogueOut(BaseModel):
    """What a backlog item may be made of: the change classes the readiness gate knows and
    the facts each needs (F24 — the freeze form asks these questions instead of taking raw
    JSON), the size tiers and the item kinds / levels the backlog accepts."""

    classes: list[CatalogueClassOut]
    sizes: list[str]
    kinds: list[str]
    levels: list[str]


class GapSignoffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=4000)


class GapSignoffOut(BaseModel):
    item_id: str
    slot: str
    kind: str
    verifier: str
    signed_at: str
    row_hash: str


class FactoryEventOut(BaseModel):
    seq: int
    kind: str
    item_id: str
    actor: str
    created: str
    payload: dict[str, Any]
    row_hash: str


class FactoryEvidenceOut(BaseModel):
    repo: str
    total: int
    verified: bool
    items: list[FactoryEventOut]


# --- helpers ---------------------------------------------------------------------------


def _home(settings: Any, repo: str) -> FactoryHome:
    return FactoryHome(settings.home, repo)


def _github_client() -> httpx.Client:
    """The request-scoped HTTP client the outcome sync talks to GitHub with (tests replace
    it with a ``MockTransport`` client)."""
    return httpx.Client(timeout=20.0)


def _active_factory_run(db: Any, repo: str) -> Run | None:
    q = (
        select(Run)
        .where(Run.repo == repo, Run.kind == "factory", Run.status.in_(ACTIVE_STATUSES))
        .limit(1)
    )
    run: Run | None = db.execute(q).scalars().first()
    return run


def _delivery_preflight(db: Any, settings: Any, repo: Repo) -> DeliveryPreflightOut:
    """The worker's ``_delivery_credentials`` rule, answered from the record (no call to
    GitHub: the worker re-reads the permissions live at delivery, so a pass here is
    "nothing on record stops it", never a promise)."""
    link = dict(dict(repo.config_json or {}).get("github") or {})
    try:
        installation_id = int(link.get("installation_id") or 0) or None
    except (TypeError, ValueError):
        installation_id = None
    out = DeliveryPreflightOut(
        full_name=str(link.get("full_name") or ""),
        default_branch=str(link.get("default_branch") or ""),
        installation_id=installation_id,
    )
    admin_next = "then Sync installations in Settings."
    if installation_id is None:
        out.reason_code = "not_linked"
        out.reason = (
            "Delivery is not possible for this repository: it is connected by URL, not "
            "through the GitHub App. Connect it through the GitHub App with Contents: write "
            f"and Pull requests: write, {admin_next}"
        )
        return out
    if not settings.github.enabled:
        out.reason_code = "app_not_configured"
        out.reason = (
            "Delivery is not possible: the GitHub App is not configured on this deployment, "
            "so no installation token can be minted. An admin registers the app for this "
            "deployment (the GitHub App guide), then syncs installations in Settings."
        )
        return out
    try:
        host = urlsplit(str(repo.url or "")).hostname or ""
        app_host = urlsplit(str(settings.github.web_url)).hostname or ""
    except ValueError:
        host, app_host = "", ""
    if not host or host != app_host:
        out.reason_code = "host_mismatch"
        out.reason = (
            f"Delivery is not possible: the repository URL is not on {app_host or 'the GitHub host the app is registered with'}, "
            "so the installation token is never sent to it. Set the URL back to the linked "
            "GitHub repository in the repository's config."
        )
        return out
    inst = db.get(GitHubInstallation, installation_id)
    if inst is None:
        out.reason_code = "installation_missing"
        out.reason = (
            f"Delivery is not possible: installation {installation_id} is not on record. "
            f"Sync installations in Settings; if it stays missing, reinstall the app on "
            f"{out.full_name.split('/')[0] or 'the organisation'} and connect the repository again."
        )
        return out
    out.account_login = inst.account_login
    if inst.suspended:
        out.reason_code = "installation_suspended"
        out.reason = (
            f"Delivery is not possible: the {inst.account_login} installation is suspended "
            "or was removed. Restore it in GitHub, then Sync installations in Settings."
        )
        return out
    perms = dict(inst.permissions_json or {})
    if not permissions_allow_delivery(perms):
        held = ", ".join(f"{k}: {v}" for k, v in sorted(perms.items())) or "none"
        out.reason_code = "read_only"
        out.reason = (
            f"Delivery is not possible: the {inst.account_login} installation is read-only "
            f"({held}). Grant Contents: write and Pull requests: write on the installation in "
            f"GitHub, {admin_next}"
        )
        return out
    out.can_deliver = True
    out.reason_code = "ok"
    return out


def _backlog_out(home: FactoryHome, delivery: DeliveryPreflightOut) -> FactoryBacklogOut | None:
    backlog = home.load_backlog()
    if backlog is None:
        return None
    authored = home.authored()
    superseded_by = backlog.superseded_by()

    def item_out(i: BacklogItem) -> BacklogItemOut:
        return BacklogItemOut(
            id=i.id,
            title=i.title,
            kind=i.kind,
            capability_class=i.capability_class,
            size=i.size_estimate,
            level=i.level,
            depends_on=list(i.depends_on),
            structural_facts=list(i.structural_facts),
            has_authored_test=i.id in authored,
            description=i.description,
            supersedes=i.supersedes,
            superseded_by=superseded_by.get(i.id, ""),
        )

    return FactoryBacklogOut(
        repo=home.repo,
        hash=backlog.backlog_hash,
        frozen_at=backlog.frozen_at or None,
        delivery=delivery,
        items=[item_out(i) for i in backlog.ordered()],
        evolutions=[item_out(e) for e in backlog.evolutions],
        evolutions_hash=backlog.evolutions_hash,
        outcomes=OutcomesSummaryOut(**home.outcomes_summary()),
    )


def _refuse_if_run_active(db: Any, repo: str) -> None:
    active = _active_factory_run(db, repo)
    if active is not None:
        raise ApiError(
            409,
            "factory_run_active",
            f"a factory run ({active.id}) is {active.status} on {repo!r}: the backlog it "
            "verifies against cannot change under it — cancel it or wait",
        )


def _item_from(it: BacklogItemIn, *, supersedes: str = "") -> BacklogItem:
    if it.kind not in KINDS:
        raise ApiError(422, "validation_error", f"item {it.id!r}: kind must be one of {KINDS}")
    if it.level not in LEVELS:
        raise ApiError(422, "validation_error", f"item {it.id!r}: level must be one of {LEVELS}")
    try:
        return BacklogItem(
            id=it.id,
            title=it.title,
            kind=it.kind,
            description=it.description,
            acceptance_criteria=tuple(it.acceptance_criteria),
            capability_class=it.capability_class,
            size_estimate=it.size_estimate,
            structural_facts=tuple(it.structural_facts),
            depends_on=tuple(it.depends_on),
            level=it.level,
            labels=dict(it.labels),
            supersedes=supersedes,
        )
    except (BacklogError, ValueError) as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc


# --- routes ----------------------------------------------------------------------------


@router.get(
    "/factory/catalogue",
    response_model=FactoryCatalogueOut,
    responses={401: _ERR},
    summary="The change classes, their structural-fact slots, the sizes, kinds and levels a backlog item may use",
)
def factory_catalogue(viewer: ViewerDep) -> FactoryCatalogueOut:
    del viewer
    return FactoryCatalogueOut(
        classes=[
            CatalogueClassOut(
                capability_class=cls,
                slots=[
                    CatalogueSlotOut(name=sl.name, question=sl.question, kind=sl.kind)
                    for sl in slots
                ],
            )
            for cls, slots in CATALOGUE.items()
        ],
        sizes=list(SIZE_TIER_NAMES),
        kinds=list(KINDS),
        levels=list(LEVELS),
    )


@router.get(
    "/factory/{repo}/backlog",
    response_model=FactoryBacklogOut,
    responses={401: _ERR, 404: _ERR},
    summary="The repo's active frozen backlog (hash, freeze time, items in dependency order)",
)
def get_backlog(
    repo: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> FactoryBacklogOut:
    del viewer
    row = get_repo_or_404(db, repo)
    out = _backlog_out(_home(settings, repo), _delivery_preflight(db, settings, row))
    if out is None:
        raise ApiError(404, "not_found", f"no backlog registered for {repo!r}")
    return out


@router.post(
    "/factory/{repo}/backlog",
    response_model=FactoryBacklogOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register and FREEZE a backlog (validated, hashed, recorded); optional authored oracles",
)
def register_backlog(
    repo: str, body: BacklogRegisterIn, operator: OperatorDep, db: DbDep, settings: SettingsDep
) -> FactoryBacklogOut:
    row = get_repo_or_404(db, repo)
    _refuse_if_run_active(db, repo)
    items = [_item_from(it) for it in body.items]
    unknown = sorted(set(body.authored) - {it.id for it in body.items})
    if unknown:
        raise ApiError(422, "validation_error", f"authored tests for unknown items: {unknown}")
    home = _home(settings, repo)
    try:
        authored = {
            item_id: AuthoredTest(path=t.path, content=t.content, author=f"operator:{operator.id}")
            for item_id, t in body.authored.items()
        }
        backlog = home.register_backlog(items, actor=operator.id)
    except (BacklogError, ValueError) as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    home.save_authored(authored)
    out = _backlog_out(home, _delivery_preflight(db, settings, row))
    assert out is not None and out.hash == backlog.backlog_hash
    return out


@router.post(
    "/factory/{repo}/backlog/evolutions",
    response_model=FactoryBacklogOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register an EVOLUTION onto the frozen backlog: a new item, optionally superseding one (the frozen record never changes)",
)
def register_evolution(
    repo: str, body: EvolutionRegisterIn, operator: OperatorDep, db: DbDep, settings: SettingsDep
) -> FactoryBacklogOut:
    """F32: the only way a frozen backlog changes. The new item is chained onto the frozen
    hash (``Backlog.evolve``), recorded as ``backlog.evolved``, and its authored oracle
    (if any) is stored beside the others; the superseded item stays in the record and
    the task view shows it as superseded. **409 ``factory_run_active``** while a run is
    queued or running; **409 ``item_exists``** / **409 ``already_superseded``** for a
    frozen-record violation; 422 for a malformed item or an unknown ``supersedes``."""
    row = get_repo_or_404(db, repo)
    _refuse_if_run_active(db, repo)
    home = _home(settings, repo)
    if home.load_backlog() is None:
        raise ApiError(404, "not_found", f"no backlog registered for {repo!r}")
    item = _item_from(body.item, supersedes=body.item.supersedes)
    try:
        # the oracle is validated BEFORE the evolution is written (the same order as
        # register_backlog): a repo-escaping path or blank content is a 422 and the chain
        # gains nothing — never an evolution persisted without its oracle and a 500
        authored = (
            {
                item.id: AuthoredTest(
                    path=body.authored.path,
                    content=body.authored.content,
                    author=f"operator:{operator.id}",
                )
            }
            if body.authored is not None
            else {}
        )
        evolved = home.register_evolution(item, actor=operator.id)
    except BacklogFrozen as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    except (BacklogError, ValueError) as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    if authored:
        home.save_authored(authored, merge=True)
    out = _backlog_out(home, _delivery_preflight(db, settings, row))
    assert out is not None and out.evolutions_hash == evolved.evolutions_hash
    return out


@router.post(
    "/factory/{repo}/outcomes/sync",
    response_model=OutcomeSyncOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 502: _ERR},
    summary="Read each delivered pull request's state from GitHub and record delivery.merged / delivery.closed (at most closed then merged per PR)",
)
def sync_delivery_outcomes(
    repo: str, operator: OperatorDep, db: DbDep, settings: SettingsDep
) -> OutcomeSyncOut:
    """B-9 / F30: the merge outcome back as evidence. Reads through the installation token
    of the repository's link (**409 ``outcome_sync_unavailable``** with the pre-flight's
    reason when the repository is not linked, the app is not configured, the URL is off
    the app's host, or the installation is missing / suspended); a token that cannot be
    minted is **502 ``github_error``**; a single pull request that cannot be read is an
    entry in ``errors`` and is retried by the next sync. Records nothing for a pull
    request still open; a closed one is read again (a person can reopen and merge it —
    ``merged`` after ``closed`` is recorded once); a merged one is never read again."""
    row = get_repo_or_404(db, repo)
    home = _home(settings, repo)
    if home.load_backlog() is None:
        raise ApiError(404, "not_found", f"no backlog registered for {repo!r}")
    pre = _delivery_preflight(db, settings, row)
    if pre.reason_code not in ("ok", "read_only") or pre.installation_id is None:
        raise ApiError(
            409,
            "outcome_sync_unavailable",
            f"the outcome of a delivered pull request can only be read through the GitHub "
            f"App installation the repository is linked to. {pre.reason}",
        )
    installation_id, full_name = pre.installation_id, pre.full_name
    if not outcomes_pending(home):
        # nothing whose fate can still change (every delivery merged, or none delivered):
        # no token is minted for an empty sync — a closed one IS pending (see the helper)
        report = OutcomeSyncReport()
    else:
        client = _github_client()
        try:
            app = GitHubApp(settings.github, client)
            try:
                app.installation_token(installation_id)  # a dead credential is ONE 502
            except GitHubAppError as exc:
                raise ApiError(
                    502,
                    "github_error",
                    f"GitHub refused: {exc.message}" if exc.status else exc.message,
                    detail={"github_status": exc.status},
                ) from exc
            report = sync_outcomes(
                home,
                lambda n: app.pull_request(installation_id, full_name, n),
                actor=operator.id,
            )
        finally:
            client.close()
    return OutcomeSyncOut(
        **report.to_dict(), outcomes=OutcomesSummaryOut(**home.outcomes_summary())
    )


@router.get(
    "/factory/{repo}/tasks",
    response_model=list[FactoryTaskOut],
    responses={401: _ERR, 404: _ERR},
    summary="Every backlog item's latest state — DoR gaps, route, RED proof, build, PR, verdict — from the evidence",
)
def list_tasks(
    repo: str, viewer: ViewerDep, db: DbDep, factory: SessionFactoryDep, settings: SettingsDep
) -> list[FactoryTaskOut]:
    del viewer
    get_repo_or_404(db, repo)
    home = _home(settings, repo)
    views = home.task_views()
    routes = _cell_routes(db, factory, repo) if views else {}
    # G-904 — the stopped item's own record, so its way forward can carry the superseding
    # item already drafted; ``taken`` keeps that draft's id off one the register route
    # would refuse. A repository whose backlog has gone serves the way forward without it.
    backlog = home.load_backlog() if views else None
    items = {i.id: i for i in (*backlog.items, *backlog.evolutions)} if backlog is not None else {}
    # F15 — the run that produced the newest build, from the ledger row the build event
    # names (the chain carries the row, the row carries the run)
    row_ids = [v.row_id for v in views if v.row_id]
    run_by_row: dict[str, str] = {}
    if row_ids:
        for row_id, run_id in db.execute(
            select(Grade.row_id, Grade.run_id).where(Grade.row_id.in_(row_ids))
        ).all():
            run_by_row[str(row_id)] = str(run_id or "")
    out: list[FactoryTaskOut] = []
    for v in views:
        d = v.to_dict()
        d.pop("row_id")
        out.append(
            FactoryTaskOut(
                **d,
                run_id=run_by_row.get(v.row_id, ""),
                cell_route=routes.get(f"{v.capability_class}|{v.size}", CellRouteOut()),
                way_forward=_way_forward(repo, d, item=items.get(v.id), taken=items.keys()),
            )
        )
    return out


def _cell_routes(db: DbDep, factory: SessionFactoryDep, repo: str) -> dict[str, CellRouteOut]:
    """``class|size`` → the map's decision, from exactly the reading the worker's delivery
    gate uses (:meth:`crb.server.worker.Worker._route_lookup`): sighted rows on the current
    apparatus, the repo's latest controls verdict, sign-offs overlaid."""
    rows = rows_for_apparatus(
        rows_for_mode(DbLedger(factory).rows(repo=repo), "sighted"), "current"
    )
    cmap, _ = signed_map(
        rows, PROJECTION_CLASS_SIZE, db, repo, controls=latest_controls_verdict(db, repo)
    )
    out: dict[str, CellRouteOut] = {}
    for c in cmap.cells:
        if c.decision is None:
            continue
        d = c.decision
        st = c.stats
        out[f"{c.key.capability_class}|{c.key.size}"] = CellRouteOut(
            route=d.route,
            reason_code=d.reason_code,
            reason=d.reason,
            n=st.n if st is not None else 0,
            point=st.point if st is not None else 0.0,
            ci_low=st.ci.low if st is not None else 0.0,
            ci_high=st.ci.high if st is not None else 0.0,
            apparatus_versions=list(st.apparatus_versions) if st is not None else [],
            deliverable=d.route == ROUTE_DELIVER,
        )
    return out


@router.post(
    "/factory/{repo}/tasks/{item_id}/signoff-gap",
    response_model=GapSignoffOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Sign one STRUCTURAL gap of an item (appended to the gap ledger and the evidence chain)",
)
def signoff_gap(  # noqa: PLR0917 — FastAPI dependencies + path/body
    repo: str,
    item_id: str,
    body: GapSignoffIn,
    approver: ApproverDep,
    db: DbDep,
    settings: SettingsDep,
) -> GapSignoffOut:
    get_repo_or_404(db, repo)
    home = _home(settings, repo)
    backlog = home.load_backlog()
    if backlog is None:
        raise ApiError(404, "not_found", f"no backlog registered for {repo!r}")
    item = next((i for i in (*backlog.items, *backlog.evolutions) if i.id == item_id), None)
    if item is None:
        raise ApiError(404, "not_found", f"no item {item_id!r} in the backlog of {repo!r}")
    slots = {s.name: s for s in slots_for(item.capability_class)}
    slot = slots.get(body.slot)
    if slot is None:
        raise ApiError(
            422,
            "validation_error",
            f"{body.slot!r} is not a slot of class {item.capability_class!r} "
            f"(known: {sorted(slots)})",
        )
    if slot.kind == SLOT_VALUE:
        raise ApiError(
            422,
            "value_slot_unsignable",
            f"{body.slot!r} is a VALUE slot: a value nobody derived from the answer cannot be "
            "signed into readiness (docs/EVIDENCE-AND-CLAIMS.md)",
        )
    record = sign(home.gap_ledger(), item, body.slot, body.answer, verifier=approver.id)
    home.evidence(actor=approver.id).record_gap_signoff(
        {
            "item_id": record.item_id,
            "slot": record.slot,
            "kind": record.kind,
            "verifier": record.verifier,
            "signed_at": record.signed_at,
            "row_hash": record.row_hash,
        }
    )
    return GapSignoffOut(
        item_id=record.item_id,
        slot=record.slot,
        kind=record.kind,
        verifier=record.verifier,
        signed_at=record.signed_at,
        row_hash=record.row_hash,
    )


@router.get(
    "/factory/{repo}/evidence",
    response_model=FactoryEvidenceOut,
    responses={401: _ERR, 404: _ERR},
    summary="The factory evidence chain, oldest first (hash-verified on read)",
)
def get_evidence(  # noqa: PLR0917 — FastAPI dependencies + query params
    repo: str,
    viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    item_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> FactoryEvidenceOut:
    del viewer
    get_repo_or_404(db, repo)
    home = _home(settings, repo)
    events = home.events()
    verified = True
    try:
        # verify the chain we already materialised — one read of evidence.jsonl, not two
        verify_events(events)
    except Exception:  # a broken chain is reported, never hidden
        verified = False
    if item_id:
        events = [e for e in events if e.item_id == item_id]
    page = events[offset : offset + limit]
    return FactoryEvidenceOut(
        repo=repo,
        total=len(events),
        verified=verified,
        items=[
            FactoryEventOut(
                seq=i + offset,
                kind=e.kind,
                item_id=e.item_id,
                actor=e.actor,
                created=e.created,
                payload=dict(e.payload),
                row_hash=e.row_hash,
            )
            for i, e in enumerate(page)
        ],
    )


# --- intake: the enterprise's own board ---------------------------------------------------


class IntakeListenerOut(BaseModel):
    """One repository's listener, as the screen shows it. ``enabled`` is false until an
    operator switches it on, and the switch names who threw it."""

    enabled: bool = False
    column: str = ""
    switched_by: str = ""
    switched_at: str = ""
    since: str = ""


class IntakeConnectionOut(BaseModel):
    """The deployment-wide connection, with no secret in it. ``credential_set`` is the
    presence of the stored ``tracker_token``, never its value."""

    tracker: str = "none"
    url: str = ""
    project: str = ""
    column: str = ""
    poll_s: int = 0
    outcome_map: dict[str, str] = Field(default_factory=dict)
    configured: bool = False
    credential_set: bool = False
    credential_fingerprint: str = ""


class IntakeRowOut(BaseModel):
    """One ticket in the watched column, exactly as the last read saw it."""

    model_config = ConfigDict(extra="ignore")

    key: str
    title: str = ""
    url: str = ""
    revision: str = ""
    label: str = ""
    state: str = ""
    item_id: str = ""
    item_url: str = ""
    feedback: str = ""
    open_questions: list[dict[str, str]] = Field(default_factory=list)
    capability_class: str = ""
    confidence: float = 0.0
    size: str = ""
    registered: bool = False
    is_evolution: bool = False
    supersedes: str = ""
    cell_route: CellRouteOut | None = None
    read_at: str = ""
    stopped: str = ""
    stopped_advice: str = ""


class IntakePollOut(BaseModel):
    """What the last poll did, and why it stopped if it did."""

    model_config = ConfigDict(extra="ignore")

    repo: str = ""
    column: str = ""
    seen: int = 0
    read: int = 0
    skipped: int = 0
    commented: int = 0
    registered: int = 0
    queued: int = 0
    stopped: str = ""
    detail: str = ""
    advice: str = ""
    at: str = ""


class IntakeOut(BaseModel):
    """``GET /factory/{repo}/intake``: the listener, the connection, the last poll and the
    column's tickets with their draft, their label and the feedback the ticket carries."""

    repo: str
    listener: IntakeListenerOut
    connection: IntakeConnectionOut
    last_poll: IntakePollOut | None = None
    rows: list[IntakeRowOut] = Field(default_factory=list)


class IntakePollIn(BaseModel):
    """``POST /factory/{repo}/intake/poll``. ``force`` re-reads every ticket in the column
    even when its revision has already been handled — what "Post the feedback again" does
    for a person who deleted the comment or wants today's numbers on the ticket. It is
    still safe to repeat: the comment and the label are idempotent on the tracker."""

    force: bool = False


class IntakeListenerIn(BaseModel):
    """``PUT /factory/{repo}/intake``: switch the listener and, optionally, override the
    column this repository watches."""

    enabled: bool
    column: str = Field(default="", max_length=200)


def _intake_connection(settings: Any, secrets: Any) -> IntakeConnectionOut:
    cfg = settings.intake
    status = secrets.status(TRACKER_TOKEN_SECRET)
    return IntakeConnectionOut(
        tracker=cfg.tracker,
        url=cfg.url,
        project=cfg.project,
        column=cfg.column,
        poll_s=cfg.poll_s,
        outcome_map=dict(cfg.outcome_map),
        configured=cfg.enabled,
        credential_set=bool(status.present),
        credential_fingerprint=str(getattr(status, "fingerprint", "") or ""),
    )


def _intake_out(repo: str, settings: Any, secrets: Any, row: Repo) -> IntakeOut:
    listener = ListenerState.from_config(row.config_json)
    store = IntakeStore(settings.home, repo)
    last = store.last_poll()
    return IntakeOut(
        repo=repo,
        listener=IntakeListenerOut(**listener.to_dict()),
        connection=_intake_connection(settings, secrets),
        last_poll=IntakePollOut(**last) if last else None,
        rows=[IntakeRowOut(**r.to_dict()) for r in store.rows()],
    )


@router.get(
    "/factory/{repo}/intake",
    response_model=IntakeOut,
    responses={401: _ERR, 404: _ERR},
    summary="The watched column as the last read saw it: the listener, the connection, every ticket with its draft, label and feedback",
)
def get_intake(
    repo: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep, secrets: SecretsDep
) -> IntakeOut:
    """Reads only what a poll already wrote: no tracker is contacted by this route, so a
    screen never waits on somebody else's service. ``listener.enabled`` is ``false`` until
    an operator switches it on — that is the default for every repository (ADR-0017)."""
    del viewer
    row = get_repo_or_404(db, repo)
    return _intake_out(repo, settings, secrets, row)


@router.put(
    "/factory/{repo}/intake",
    response_model=IntakeOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Switch this repository's intake listener on or off (operator); optionally override the watched column",
)
def put_intake(  # noqa: PLR0917 — FastAPI dependencies + path/body
    repo: str,
    body: IntakeListenerIn,
    operator: OperatorDep,
    db: DbDep,
    settings: SettingsDep,
    secrets: SecretsDep,
) -> IntakeOut:
    """The consent gate. Switching a listener on is what allows this product to read
    somebody's board and write on their tickets, so it is operator-only and the switch is
    stored with the actor and the time. Switching a listener on when no tracker is
    configured is refused (422) rather than accepted and silently idle."""
    row = get_repo_or_404(db, repo)
    if body.enabled and not settings.intake.enabled:
        raise ApiError(
            422,
            "intake_not_configured",
            "no tracker is configured for this deployment: an admin sets CRB_INTAKE__* and "
            "stores the tracker token before a listener can be switched on",
        )
    state = ListenerState(
        enabled=body.enabled,
        column=body.column.strip(),
        switched_by=operator.display_name or operator.id,
        switched_at=_dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat(),
        since=ListenerState.from_config(row.config_json).since,
    )
    row.config_json = {**dict(row.config_json or {}), INTAKE_CONFIG_KEY: state.to_dict()}
    db.commit()
    return _intake_out(repo, settings, secrets, row)


@router.post(
    "/factory/{repo}/intake/poll",
    response_model=IntakeOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 502: _ERR},
    summary="Read the watched column now (operator): comment, label and register whatever it has earned",
)
def poll_intake(  # noqa: PLR0917 — FastAPI dependencies + body
    repo: str,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    secrets: SecretsDep,
    body: IntakePollIn | None = None,
) -> IntakeOut:
    """The same poll the worker makes on its own timer, on demand. Refused (422) when the
    listener is off — the switch is the consent, and a route that polled anyway would make
    it meaningless. A tracker that cannot be reached is 502 ``tracker_error`` carrying the
    published stop reason, and nothing is registered from a partial read."""
    row = get_repo_or_404(db, repo)
    listener = ListenerState.from_config(row.config_json)
    if not listener.enabled:
        raise ApiError(
            422,
            "intake_listener_off",
            f"the intake listener for {repo!r} is off: switch it on before reading the column",
        )
    try:
        tracker = build_tracker(
            settings.intake,
            secrets.get(TRACKER_TOKEN_SECRET) or "",
            home=settings.home,
        )
    except TrackerError as exc:
        raise ApiError(502, "tracker_error", f"{exc.detail or exc.reason} — {exc.advice}") from exc
    routes = _cell_routes(db, factory, repo)
    home = _home(settings, repo)
    report = poll_repository(
        repo,
        tracker=tracker,
        listener=listener,
        column=listener.column or settings.intake.column,
        home=home,
        route_for=lambda item: (
            routes[f"{item.capability_class}|{item.size_estimate}"].model_dump()
            if f"{item.capability_class}|{item.size_estimate}" in routes
            else None
        ),
        item_url=lambda item_id: f"/factory?repo={repo}&item={item_id}",
        run_active=lambda: _active_factory_run(db, repo) is not None,
        actor=operator.id,
        force=bool(body.force) if body else False,
    )
    IntakeStore(settings.home, repo).write(report)
    return _intake_out(repo, settings, secrets, row)
