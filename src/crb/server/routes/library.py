"""``/library`` — a repository's context library: propose, sponsor, sign, and each work type's page.

The library holds what people know about a repository that a test cannot say (ADR-0026
item 10): components, work types, decisions, conventions, patterns and standards, each
with the id ``<kind>/<slug>``, a statement of at most 400 characters and its provenance.
Every entry needs **two different people**: the sponsor who puts it forward — the person
who proposes it here, or who adopts a miner's or a model's proposal — and the approver who
signs it. The approver can never be the sponsor (409 ``library_refused`` with
``detail.code = same_person``), and a miner or a model is never a person.

Every write is appended to the hash-chained ``library_acts`` table through
:class:`~crb.store.library.DbLibraryLedger` — which checks the act against the entry's
state inside the write lock — and is a ``system/library.*`` event naming the actor and the
entry. A refused act writes nothing but a ``library.refused`` event.

**Nothing here reaches a builder's brief.** The index and the page say so
(``reaches_briefs: false``): an entry reaches a brief only inside a measured context arm
(ADR-0026 items 1 and 10), which no build of this release runs.

Navigation
----------
What it is:   The ``/library`` route module: the index (``GET /library/{repo}``), the page per
              work type, the five acts over HTTP (propose, sponsor, sign, revoke, retire), the
              freshness reading that makes an entry stale, the miners (``GET …/miners``,
              ``POST …/mine``) and the chain's verification.
What it does: Gates each act by role — an operator proposes and sponsors, an approver signs,
              revokes and retires — and hands it to the core's rule; resolves a rows
              provenance in the grade ledger (422 for an unknown row; at signing, who produced
              the rows, for the two-person rule); serves each entry with its sponsor's and
              approver's names, its evidence for a standard (``check`` only for a pair the
              quality table counts and the repository runs, else ``advisory``) and its effect
              (``unmeasured``); builds the work-type page from
              the library, the mined tasks, the readiness catalogue, the repository's
              switched-on checks, the proven standard per size (stream R's reader, a seam) and
              the ISO/IEC 25010 table (stream C's ``crb.core.quality_model``, a seam); runs
              the miners over the clone at a pinned commit and appends their proposals under
              ``mined:<name>@<version>``, unsigned and unsponsored (G-677).
How:          ``DbLibraryLedger.append(new_act(…))`` → ``append_system_event`` → commit; reads
              fold ``DbLibraryLedger.states``; ``work_type_page`` assembles the page.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10),
              docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
Works with:   src/crb/core/library.py (the record, the rule, the page as data),
              src/crb/store/library.py (the ledger), src/crb/server/schemas_library.py (the
              request and response bodies), src/crb/factory/readiness.py (``slots_for`` — what
              a ticket must carry today), src/crb/core/checks.py and src/crb/core/lint.py (the
              switched-on checks), ui/src/screens/Library/LibraryPage.tsx (the page that
              calls them),
              src/crb/store/models.py (``Grade``, ``Run`` — who produced a cited row),
              src/crb/core/miners.py (the miners and the run ``POST …/mine`` appends)
Tested by:    tests/test_server_routes_library.py, tests/test_server_routes_library_mine.py,
              tests/test_worker_clone.py (the clone-path rule at ``mine_source``)
Touch when:   never for a new repository; a new act is added in src/crb/core/library.py first,
              then here with its event row in docs/API.md#event-vocabulary and its route row in
              docs/API.md#library (the contract these routes serve).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.checks import RepoChecks
from crb.core.git import GitError, GitRepo
from crb.core.ledger import LedgerIntegrityError
from crb.core.library import (
    ACT_PROPOSE,
    ACT_RETIRE,
    ACT_REVOKE,
    ACT_SIGN,
    ACT_SPONSOR,
    ISO_25010_CHARACTERISTICS,
    KINDS,
    PROVENANCE_PERSON,
    PROVENANCE_ROWS,
    RETIRED_BY_PERSON,
    STATEMENT_MAX,
    EntryState,
    EvidencePairs,
    LibraryEntry,
    LibraryRefused,
    Provenance,
    StandardReader,
    entry_id_of,
    evidence_of,
    evidence_pairs,
    quality_rows,
    standard_for,
    work_type_page,
    work_types_of,
)
from crb.core.lint import plan_from_config
from crb.core.miners import (
    OUTCOME_PROPOSED,
    OUTCOME_UNCHANGED,
    GradedRow,
    MinedTask,
    MineSource,
    Outcome,
    describe_miners,
    miner_names,
    run_miners,
    source_from_git,
)
from crb.core.redact import redact
from crb.core.spec import RepoConfig
from crb.factory.readiness import slots_for
from crb.observability.events import StepStatus
from crb.server.auth import ApproverDep, OperatorDep, ViewerDep
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    Principal,
    SessionFactoryDep,
    SettingsDep,
)
from crb.server.routes.repos import clone_root, confined_clone_path, get_repo_or_404
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas_library import (
    EntryOut,
    EntryProposeRequest,
    FreshnessOut,
    FreshnessRequest,
    LibraryIndexOut,
    LibraryVerifyOut,
    MineOut,
    MineOutcomeOut,
    MineRequest,
    MinerOut,
    MinersOut,
    ReasonRequest,
    VersionRequest,
    WorkTypeOut,
    WorkTypePageOut,
)
from crb.store.library import DbLibraryLedger, new_act
from crb.store.models import Grade, Run, Task, User

router = APIRouter(tags=["library"])
_ERR = {"model": ErrorEnvelope}

CODE_REFUSED = "library_refused"

#: The checks every graded attempt runs, whatever the repository configures.
ALWAYS_ON: tuple[str, ...] = ("target_green", "no_new_failures")
#: A person's review verdicts: available wherever a person reviews an accepted row.
REVIEW_CHECKS: tuple[str, ...] = ("defect", "regression", "style", "api_change")

#: SEAM (stream R): the page's reader of each size's proven standard. Bound here to the
#: core's ``standard_for``, which answers ``None`` until R's registered readings land; the
#: integration binds R's reader in its place (tests replace it to show a proven cell).
STANDARD_READER: list[StandardReader] = [standard_for]


QUALITY_MODULE = "crb.core.quality_model"


def quality_model() -> Sequence[Any] | None:
    """SEAM (stream C): ``crb.core.quality_model.QUALITY_MODEL`` — the ISO/IEC 25010:2023
    characteristic-to-check table — or ``None`` on a build without it, when the page says
    the table is not served rather than supplying one of its own."""
    try:
        module = importlib.import_module(QUALITY_MODULE)
    except ModuleNotFoundError as exc:
        # only the table's own absence is "not served"; a table that fails to import one of
        # its dependencies is a broken build, never an empty section
        if exc.name != QUALITY_MODULE:
            raise
        return None
    model = getattr(module, "QUALITY_MODEL", None)
    return tuple(model) if model is not None else None


def _trace(repo: str) -> str:
    return system_trace_id("library", repo)


def _names(db: Session, ids: Iterable[str]) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.subject).where(User.id.in_(wanted)))
    out: dict[str, str] = {}
    for uid, display, subject in rows:
        name = display or subject.removeprefix("local:")
        out[str(uid)] = str(name)
    return out


def _config(repo_row: Any) -> RepoConfig | None:
    try:
        return RepoConfig.from_dict(repo_row.name, dict(repo_row.config_json or {}))
    except (ValueError, KeyError, TypeError):
        return None


def switched_on_checks(config: RepoConfig | None) -> list[str]:
    """The checks this repository runs: belts 2 and 3 always; belt 5 where it configures a
    linter; the format step and belt 6 where switched on; its finish-gate commands by
    name; and a person's review verdicts."""
    on = list(ALWAYS_ON)
    if config is not None:
        try:
            if plan_from_config(config.lint) is not None:
                on.append("repo_lint_clean")
        except ValueError:
            pass
        checks = RepoChecks.from_config(config.checks)
        if checks.format_step:
            on.append("format_step")
        if checks.api_stable:
            on.append("api_stable")
        on.extend(c.name for c in checks.commands)
    on.extend(REVIEW_CHECKS)
    return on


def counted_evidence(config: RepoConfig | None) -> EvidencePairs:
    """The ``(characteristic, check)`` pairs the product's quality table counts and this
    repository switches on — empty while the table is not on the build."""
    return evidence_pairs(quality_rows(quality_model(), switched_on_checks(config)))


def _entry_out(s: EntryState, names: dict[str, str], counted: EvidencePairs) -> EntryOut:
    d = s.to_dict()
    return EntryOut(
        **d,
        sponsor_name=names.get(s.sponsor, ""),
        approver_name=names.get(s.approver, ""),
        evidence=evidence_of(s.entry, counted),
    )


def row_producers(db: Session, repo: str, rows: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(actors, missing)`` of graded rows ``rows`` of ``repo``: the actor of each row and
    of the run that produced it, and the row hashes the grade ledger does not hold."""
    if not rows:
        return [], []
    found = db.execute(
        select(Grade.row_hash, Grade.actor, Grade.run_id).where(
            Grade.repo == repo, Grade.row_hash.in_(set(rows))
        )
    ).all()
    missing = sorted(set(rows) - {h for h, _a, _r in found})
    run_ids = {r for _h, _a, r in found if r}
    run_actors = (
        db.execute(select(Run.actor).where(Run.id.in_(run_ids))).scalars().all() if run_ids else []
    )
    actors = sorted({a for _h, a, _r in found if a} | {a for a in run_actors if a})
    return actors, missing


def _states(factory: Any, repo: str) -> dict[str, EntryState]:
    try:
        return DbLibraryLedger(factory).states(repo)
    except LedgerIntegrityError as exc:
        raise ApiError(
            409, "library_integrity", f"the library's acts no longer fold: {exc}"
        ) from exc


def _tasks(db: Session, repo: str) -> list[dict[str, str]]:
    rows = db.execute(
        select(Task.task_id, Task.capability_class, Task.size, Task.subject)
        .where(Task.repo == repo)
        .order_by(Task.authored.desc(), Task.task_id)
    )
    return [{"task_id": t, "capability_class": c, "size": z, "subject": s} for t, c, z, s in rows]


def _refused(
    db: Session, exc: LibraryRefused, *, repo: str, actor: str, act: str, entry_id: str
) -> ApiError:
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.refused",
        repo=repo,
        actor=actor,
        status=StepStatus.INVALID,
        error=str(exc),
        payload={"act": act, "entry_id": entry_id, "code": exc.code},
    )
    db.commit()
    return ApiError(409, CODE_REFUSED, str(exc), detail={"code": exc.code, "entry_id": entry_id})


def _current(factory: Any, repo: str, kind: str, slug: str) -> EntryState:
    eid = entry_id_of(kind, slug)
    state = _states(factory, repo).get(eid)
    if state is None:
        raise ApiError(404, "not_found", f"no entry {eid!r} in {repo}'s library")
    return state


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get(
    "/library/verify",
    response_model=LibraryVerifyOut,
    responses={401: _ERR},
    summary="Walk the library's hash chain from genesis (never raises)",
)
def verify_library(_viewer: ViewerDep, factory: SessionFactoryDep) -> LibraryVerifyOut:
    """Recompute every act's hash from the stored columns; a break is reported, not hidden."""
    ledger = DbLibraryLedger(factory)
    try:
        return LibraryVerifyOut(ok=True, acts=ledger.verify())
    except LedgerIntegrityError as exc:
        return LibraryVerifyOut(ok=False, acts=len(ledger.acts()), error=str(exc))


@router.get(
    "/library/{repo}",
    response_model=LibraryIndexOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="The repository's library: every entry with its status, and its work types",
)
def library_index(
    repo: str, _viewer: ViewerDep, db: DbDep, factory: SessionFactoryDep
) -> LibraryIndexOut:
    row = get_repo_or_404(db, repo)
    states = _states(factory, repo)
    counted = counted_evidence(_config(row))
    names = _names(db, [x for s in states.values() for x in (s.sponsor, s.approver)])
    order = {k: i for i, k in enumerate(KINDS)}
    entries = sorted(states.values(), key=lambda s: (order[s.entry.kind], s.entry.slug))
    return LibraryIndexOut(
        repo=repo,
        entries=[_entry_out(s, names, counted) for s in entries],
        work_types=[WorkTypeOut(**w) for w in work_types_of(states, _tasks(db, repo))],
        kinds=list(KINDS),
        characteristics=list(ISO_25010_CHARACTERISTICS),
        statement_max=STATEMENT_MAX,
    )


@router.get(
    "/library/{repo}/work-types/{slug}",
    response_model=WorkTypePageOut,
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="The page for one work type: what it is, what a ticket carries, what is proven",
)
def work_type(
    repo: str, slug: str, _viewer: ViewerDep, db: DbDep, factory: SessionFactoryDep
) -> WorkTypePageOut:
    row = get_repo_or_404(db, repo)
    states = _states(factory, repo)
    runnable = switched_on_checks(_config(row))
    wt = states.get(entry_id_of("work-type", slug))
    parent = wt.entry.parent_class if wt is not None and wt.usable else slug
    catalogue = [
        {"name": s.name, "question": s.question, "kind": s.kind} for s in slots_for(parent)
    ]
    try:
        page = work_type_page(
            repo,
            slug,
            states,
            tasks=_tasks(db, repo),
            catalogue=catalogue,
            runnable_checks=runnable,
            quality=quality_rows(quality_model(), runnable),
            reader=STANDARD_READER[0],
        )
    except KeyError as exc:
        raise ApiError(
            404,
            "not_found",
            f"no work type {slug!r} in {repo}: not a global class or a signed entry",
        ) from exc
    names = _names(db, [x for c in page["context"] for x in (c["sponsor"], c["approver"])])
    for c in page["context"]:
        c["sponsor_name"] = names.get(c["sponsor"], "")
        c["approver_name"] = names.get(c["approver"], "")
    return WorkTypePageOut(**page)


# ---------------------------------------------------------------------------
# Acts
# ---------------------------------------------------------------------------


def _entry_from(repo: str, body: EntryProposeRequest, proposer: Principal) -> LibraryEntry:
    prov = body.provenance
    try:
        provenance = Provenance(
            kind=prov.kind,
            path=prov.path,
            commit=prov.commit.lower(),
            digest=prov.digest.lower(),
            rows=tuple(r.lower() for r in prov.rows),
            person=proposer.id if prov.kind == PROVENANCE_PERSON else "",
        )
        return LibraryEntry(
            repo=repo,
            kind=body.kind,
            slug=body.slug,
            title=body.title,
            statement=body.statement,
            provenance=provenance,
            proposed_by=proposer.id,
            components=tuple(body.components),
            work_types=tuple(body.work_types),
            characteristic=body.characteristic,
            check=body.check,
            parent_class=body.parent_class,
            examples=tuple(x.lower() for x in body.examples),
            slots=tuple(body.slots),
        )
    except ValueError as exc:
        raise ApiError(
            422,
            "validation_error",
            redact(str(exc)),
            detail={"errors": [{"loc": ["body"], "msg": redact(str(exc)), "type": "value_error"}]},
        ) from exc


@router.post(
    "/library/{repo}/entries",
    response_model=EntryOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Propose an entry (operator); the proposer is its sponsor",
)
def propose_entry(
    repo: str,
    *,
    body: EntryProposeRequest,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> EntryOut:
    row = get_repo_or_404(db, repo)
    entry = _entry_from(repo, body, operator)
    _actors, missing = row_producers(db, repo, entry.provenance.rows)
    if missing:
        n = len(missing)
        msg = (
            f"a rows provenance names graded rows of this repository: {n} graded "
            f"row{'s' if n != 1 else ''} not found in {repo}'s ledger"
        )
        raise ApiError(
            422,
            "validation_error",
            msg,
            detail={"errors": [{"loc": ["body", "provenance", "rows"], "msg": msg,
                                "type": "value_error"}]},
        )  # fmt: skip
    act = new_act(
        repo,
        entry.entry_id,
        entry.version,
        ACT_PROPOSE,
        operator.id,
        body={"entry": entry.content()},
    )
    try:
        chained, state = DbLibraryLedger(factory).append(act)
    except LibraryRefused as exc:
        raise _refused(
            db, exc, repo=repo, actor=operator.id, act=ACT_PROPOSE, entry_id=entry.entry_id
        ) from exc
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.proposed",
        repo=repo,
        actor=operator.id,
        payload={"entry_id": entry.entry_id, "version": entry.version, "act_id": chained.act_id},
    )
    db.commit()
    return _entry_out(state, _names(db, [state.sponsor]), counted_evidence(_config(row)))


def _act(
    db: Session,
    factory: Any,
    *,
    repo: str,
    kind: str,
    slug: str,
    act: str,
    who: Principal,
    version: str,
    body: dict[str, Any],
) -> tuple[Any, EntryState]:
    get_repo_or_404(db, repo)
    if kind not in KINDS:
        raise ApiError(404, "not_found", f"no kind {kind!r}: one of {', '.join(KINDS)}")
    current = _current(factory, repo, kind, slug)
    try:
        return DbLibraryLedger(factory).append(
            new_act(
                repo, current.entry_id, version or current.entry.version, act, who.id, body=body
            )
        )
    except LibraryRefused as exc:
        raise _refused(
            db, exc, repo=repo, actor=who.id, act=act, entry_id=current.entry_id
        ) from exc


def _out(db: Session, repo: str, state: EntryState) -> EntryOut:
    row = get_repo_or_404(db, repo)
    return _entry_out(
        state, _names(db, [state.sponsor, state.approver]), counted_evidence(_config(row))
    )


@router.post(
    "/library/{repo}/entries/{kind}/{slug}/sponsor",
    response_model=EntryOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Adopt a miner's or a model's proposal as its sponsor (operator)",
)
def sponsor_entry(
    repo: str,
    kind: str,
    slug: str,
    *,
    body: VersionRequest,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> EntryOut:
    chained, state = _act(
        db,
        factory,
        repo=repo,
        kind=kind,
        slug=slug,
        act=ACT_SPONSOR,
        who=operator,
        version=body.version,
        body={},
    )
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.sponsored",
        repo=repo,
        actor=operator.id,
        payload={"entry_id": state.entry_id, "version": body.version, "act_id": chained.act_id},
    )
    db.commit()
    return _out(db, repo, state)


@router.post(
    "/library/{repo}/entries/{kind}/{slug}/sign",
    response_model=EntryOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Sign an entry (approver, never its sponsor); 409 library_refused same_person",
)
def sign_entry(
    repo: str,
    kind: str,
    slug: str,
    *,
    body: VersionRequest,
    approver: ApproverDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> EntryOut:
    get_repo_or_404(db, repo)
    sign_body: dict[str, Any] = {}
    if kind in KINDS:
        prov = _current(factory, repo, kind, slug).entry.provenance
        if prov.kind == PROVENANCE_ROWS:
            # ground 1 of the two-person rule: who produced the rows the entry was learned from
            actors, missing = row_producers(db, repo, prov.rows)
            sign_body = {"row_actors": actors, "rows_missing": missing}
    chained, state = _act(
        db,
        factory,
        repo=repo,
        kind=kind,
        slug=slug,
        act=ACT_SIGN,
        who=approver,
        version=body.version,
        body=sign_body,
    )
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.signed",
        repo=repo,
        actor=approver.id,
        payload={
            "entry_id": state.entry_id,
            "version": body.version,
            "sponsor": state.sponsor,
            "act_id": chained.act_id,
        },
    )
    db.commit()
    return _out(db, repo, state)


@router.post(
    "/library/{repo}/entries/{kind}/{slug}/revoke",
    response_model=EntryOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Revoke an entry (approver; appended, never an edit)",
)
def revoke_entry(
    repo: str,
    kind: str,
    slug: str,
    *,
    body: ReasonRequest,
    approver: ApproverDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> EntryOut:
    reason = redact(body.reason.strip())
    chained, state = _act(
        db,
        factory,
        repo=repo,
        kind=kind,
        slug=slug,
        act=ACT_REVOKE,
        who=approver,
        version="",
        body={"reason": reason},
    )
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.revoked",
        repo=repo,
        actor=approver.id,
        payload={"entry_id": state.entry_id, "reason": reason, "act_id": chained.act_id},
    )
    db.commit()
    return _out(db, repo, state)


@router.post(
    "/library/{repo}/entries/{kind}/{slug}/retire",
    response_model=EntryOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Retire an entry (approver; a retirement by measurement is the arm reader's)",
)
def retire_entry(
    repo: str,
    kind: str,
    slug: str,
    *,
    body: ReasonRequest,
    approver: ApproverDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> EntryOut:
    reason = redact(body.reason.strip())
    chained, state = _act(
        db,
        factory,
        repo=repo,
        kind=kind,
        slug=slug,
        act=ACT_RETIRE,
        who=approver,
        version="",
        body={"reason": reason, "by": RETIRED_BY_PERSON},
    )
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.retired",
        repo=repo,
        actor=approver.id,
        payload={
            "entry_id": state.entry_id,
            "by": RETIRED_BY_PERSON,
            "reason": reason,
            "act_id": chained.act_id,
        },
    )
    db.commit()
    return _out(db, repo, state)


@router.post(
    "/library/{repo}/freshness",
    response_model=FreshnessOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Read the repository's head: an entry whose source file changed reads stale",
)
def freshness(
    repo: str,
    *,
    body: FreshnessRequest,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> FreshnessOut:
    get_repo_or_404(db, repo)
    head = body.head_commit.strip().lower()
    digests = {p: (d.strip().lower() or None) for p, d in body.digests.items()}
    _states(factory, repo)  # a library whose acts no longer fold answers 409, never a guess
    stale: list[str] = []
    for chained, state in DbLibraryLedger(factory).mark_stale(repo, head, digests, operator.id):
        stale.append(state.entry_id)
        append_system_event(
            db,
            trace_id=_trace(repo),
            action="library.stale",
            repo=repo,
            actor=operator.id,
            payload={
                "entry_id": state.entry_id,
                "path": state.entry.provenance.path,
                "head_commit": head,
                "act_id": chained.act_id,
            },
        )
    db.commit()
    return FreshnessOut(repo=repo, head_commit=head, stale=stale)


# ---------------------------------------------------------------------------
# The miners: proposals from the repository's own files (G-677)
# ---------------------------------------------------------------------------


@router.get(
    "/library/{repo}/miners",
    response_model=MinersOut,
    responses={401: _ERR, 404: _ERR},
    summary="The miners a run applies, in order, with what each reads and proposes",
)
def list_miners(repo: str, _viewer: ViewerDep, db: DbDep) -> MinersOut:
    get_repo_or_404(db, repo)
    return MinersOut(repo=repo, miners=[MinerOut(**m) for m in describe_miners()])


def _mined_tasks(db: Session, repo: str) -> list[MinedTask]:
    rows = db.execute(
        select(Task.task_id, Task.capability_class, Task.size, Task.spec_json)
        .where(Task.repo == repo)
        .order_by(Task.authored.desc(), Task.task_id)
    )
    return [
        MinedTask(
            task_id=t,
            capability_class=c,
            size=z,
            src_files=tuple(str(p) for p in (spec or {}).get("src_files") or ()),
            test_files=tuple(str(p) for p in (spec or {}).get("test_files") or ()),
        )
        for t, c, z, spec in rows
    ]


def _graded_rows(db: Session, repo: str) -> list[GradedRow]:
    rows = db.execute(select(Grade.row_hash, Grade.task_id, Grade.clean).where(Grade.repo == repo))
    return [GradedRow(row_hash=h, task_id=t, clean=bool(c)) for h, t, c in rows if h]


def mine_source(db: Session, repo_row: Any, ref: str, *, home: Any) -> MineSource:
    """The repository at ``ref`` (empty = the clone's ``HEAD``), pinned to the full sha it
    names now, with its mined tasks and graded rows. The clone-path rule is applied again at
    use (:func:`~crb.server.routes.repos.confined_clone_path`) and git opens the checked
    path; nothing is checked out — the tree and the blobs are read from the object store."""
    config = _config(repo_row)
    path = (config.path if config is not None else "") or repo_row.clone_path
    if not path:
        raise ApiError(
            409, "no_clone_path", f"repo {repo_row.name!r} has no clone to mine",
            detail={"repo": repo_row.name},
        )  # fmt: skip
    opened = confined_clone_path(path, home)
    if opened is None:
        raise ApiError(
            422, "clone_path_escapes",
            "clone_path is under the repositories directory but resolves outside it",
            detail={"clone_root": str(clone_root(home))},
        )  # fmt: skip
    git = GitRepo(opened, timeout=60)
    try:
        if not opened.is_dir() or not git.is_repo():
            raise ApiError(
                409, "clone_unavailable",
                f"the clone of {repo_row.name!r} is not a git repository on this host",
                detail={"repo": repo_row.name},
            )  # fmt: skip
        return source_from_git(
            git,
            repo_row.name,
            ref or "HEAD",
            tasks=_mined_tasks(db, repo_row.name),
            graded=_graded_rows(db, repo_row.name),
        )
    except GitError as exc:
        raise ApiError(
            422,
            "unknown_commit",
            f"{ref or 'HEAD'} names no commit of the clone of {repo_row.name!r}: fetch it "
            "first, or name a sha, branch or tag the clone holds",
            detail={"commit": ref},
        ) from exc


@router.post(
    "/library/{repo}/mine",
    response_model=MineOut,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Propose entries from the repository's files at a pinned commit (operator)",
)
def mine_library(
    repo: str,
    *,
    body: MineRequest,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> MineOut:
    """Run the registered miners (or the ones named) over the repository at one pinned
    commit and append each proposal as a ``propose`` act under its miner
    (``mined:<name>@<version>``) — never signed, never sponsored: a person adopts it and a
    different person signs it. The same sha proposes nothing new. The run is one
    ``library.mined`` event naming the operator, the commit and the counts, and each
    proposal a ``library.proposed`` event naming its miner."""
    row = get_repo_or_404(db, repo)
    names = list(dict.fromkeys(body.miners))
    unknown = [n for n in names if n not in miner_names()]
    if unknown:
        msg = f"no miner registered as {', '.join(unknown)}; one of {', '.join(miner_names())}"
        raise ApiError(
            422, "validation_error", msg,
            detail={"errors": [{"loc": ["body", "miners"], "msg": msg, "type": "value_error"}]},
        )  # fmt: skip
    source = mine_source(db, row, body.commit.strip(), home=settings.home)
    run = run_miners(source, names=names or None, states=_states(factory, repo))
    ledger = DbLibraryLedger(factory)
    outcomes = list(run.outcomes)
    written: list[tuple[Any, EntryState, Any]] = []
    # every act first, then the events: an event added to ``db`` before the next locked
    # append would hold SQLite's write lock against it
    for p in run.proposals:
        e = p.entry
        act = new_act(repo, e.entry_id, e.version, ACT_PROPOSE, e.proposed_by,
                      body={"entry": e.content()})  # fmt: skip
        try:
            chained, state = ledger.append(act)
        except LibraryRefused as exc:
            # another writer proposed this version between the read and the write
            outcomes = [
                Outcome(o.miner, o.subject, OUTCOME_UNCHANGED, str(exc), o.version)
                if o.subject == e.entry_id and o.outcome == OUTCOME_PROPOSED
                else o
                for o in outcomes
            ]
            continue
        written.append((chained, state, p))
    proposed = [state for _c, state, _p in written]
    for chained, state, p in written:
        append_system_event(
            db,
            trace_id=_trace(repo),
            action="library.proposed",
            repo=repo,
            actor=state.entry.proposed_by,
            payload={
                "entry_id": state.entry_id,
                "version": state.entry.version,
                "act_id": chained.act_id,
                "commit": run.commit,
                "miner": p.miner,
                "drafted_by": p.drafted_by,
                "run_by": operator.id,
            },
        )
    counts = {k: sum(1 for o in outcomes if o.outcome == k) for k in run.counts()}
    append_system_event(
        db,
        trace_id=_trace(repo),
        action="library.mined",
        repo=repo,
        actor=operator.id,
        payload={
            "commit": run.commit,
            "miners": list(run.miners),
            "counts": counts,
            "proposed": [s.entry_id for s in proposed],
            "files_read": len(run.files_read),
        },
    )
    db.commit()
    counted = counted_evidence(_config(row))
    return MineOut(
        repo=repo,
        commit=run.commit,
        miners=list(run.miners),
        counts=counts,
        proposed=[_entry_out(s, {}, counted) for s in proposed],
        outcomes=[MineOutcomeOut(**o.to_dict()) for o in outcomes],
        files_read=len(run.files_read),
    )
