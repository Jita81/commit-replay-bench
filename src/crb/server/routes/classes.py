"""``/classes`` — an organisation's own classes of work: propose, label, report, sign, read.

The global classes are one vocabulary for everyone; an organisation's work is not. Here a
sponsor proposes the organisation's class set as a version (``<org>/classes@vN``), each class a
child of one global class, with a rule that reads only what a ticket carries (ADR-0026 item 9).
Before any class was proposed, every commit was already in a **derivation** or a
**confirmation** set by a seeded hash; a person labels derivation commits blind (to the rule,
to other labellers and to every outcome); the **validity report** compares the rule with those
labels and counts what else the ADR asks; and an **approver who is not the sponsor** signs it.
A version routes nothing until it is signed and its report passes. Each class has a page that
says what the work is, with example commits, what a ticket in it must carry, the context its
builder would get and what is proven for each size.

Every write is appended to the hash-chained ``class_set_acts`` table or to the label table
(``class_labels``) and is a ``system/class_set.*`` event naming the actor. A refused act
writes nothing but a ``class_set.refused`` event.

Navigation
----------
What it is:   The ``/classes`` route module: the index, a version with its report and split,
              the page per class, the labelling queue and a person's label, and the acts
              (propose, propose from the library, sign, revoke).
What it does: Gates each act by role — an operator proposes and labels, an approver signs and
              revokes — and hands it to the core's rule; checks a rule's components against
              the organisation's component names (the signed component entries of the
              version's repositories) and a cited work-type entry against the library; relabels
              every commit by the new version's rule into the label table; refuses a person's
              label of a confirmation commit; serves the labelling queue with no rule label, no
              other person's label and no outcome.
How:          ``DbClassSets.append(new_act(…))`` → ``append_system_event`` → commit; reads fold
              ``DbClassSets.versions``; the report and the verdict come from
              ``crb.server.class_set_state``; a class's proven standard per size from the
              factory gate's own readers (``crb.server.factory_standard.readers_in``).
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9),
              docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
Works with:   src/crb/core/class_sets.py (the rule), src/crb/server/class_set_state.py (the
              report, the verdict, the relabel), src/crb/store/class_sets.py (the acts and
              labels), src/crb/store/library.py (the component names and work-type entries),
              src/crb/server/schemas_classes.py (the request bodies),
              ui/src/screens/Classes/ClassesPage.tsx (the screen that calls them)
Tested by:    tests/test_server_routes_classes.py
Touch when:   onboarding a client repository never needs it — a repository joins a class set
              when a version names it; a new act is added in src/crb/core/class_sets.py first,
              then here with its event row in docs/API.md#event-vocabulary and its route row in
              docs/API.md#classes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from crb.core.class_sets import (
    ACT_PROPOSE,
    ACT_REVOKE,
    ACT_SIGN,
    CONFIRMATION,
    COVERAGE_MIN,
    DERIVATION,
    DERIVATION_SHARE,
    KAPPA_MIN,
    MEASURABLE_MIN,
    OVERRIDE_RATE_MAX,
    PER_CLASS_MIN,
    REFUSAL_CONFIRMATION_LABEL,
    REFUSAL_EXAMPLE_LABEL,
    REFUSAL_REPO_TAKEN,
    REFUSAL_SPONSOR_LABEL,
    SAMPLE_MIN,
    SPLIT_SEED,
    STATUS_REVOKED,
    Case,
    ClassRule,
    ClassSetRefused,
    ClassSetVersion,
    OrgClass,
    VersionState,
    classify,
    example_keys,
    examples_of,
    global_parents,
    routes,
)
from crb.core.ledger import LedgerIntegrityError
from crb.core.library import (
    KIND_COMPONENT,
    KIND_WORK_TYPE,
    EntryState,
    LibraryRefused,
    entry_id_of,
    signed_context,
)
from crb.core.redact import redact
from crb.core.taxonomy import CLASS_DEFINITIONS, UNCLASSIFIED
from crb.factory.readiness import slots_for
from crb.factory.standard import CellRef, standard_signed
from crb.observability.events import StepStatus
from crb.server import factory_standard
from crb.server.auth import ApproverDep, OperatorDep, ViewerDep
from crb.server.class_set_state import cases_for, relabel, report_for
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    Principal,
    SessionFactoryDep,
    SettingsDep,
)
from crb.server.posture_view import deployment_posture_class
from crb.server.prevention_state import checks_arm_in
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas_classes import (
    ClassIn,
    DigestIn,
    FromLibraryIn,
    LabelIn,
    ProposeIn,
    ReasonIn,
    RuleIn,
)
from crb.store.class_sets import SOURCE_PERSON, DbClassSets, new_act
from crb.store.library import DbLibraryLedger
from crb.store.models import Repo, Task, User

router = APIRouter(tags=["classes"])
_ERR = {"model": ErrorEnvelope}

CODE_REFUSED = "class_set_refused"
SIZES: tuple[str, ...] = ("XS", "S", "M", "L", "XL")
FIRST_LOOK = 20


def _trace(org: str) -> str:
    return system_trace_id("classes", org)


def _names(db: Session, ids: Iterable[str]) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.subject).where(User.id.in_(wanted)))
    return {str(u): str(d or s.removeprefix("local:")) for u, d, s in rows}


def _store(factory: Any) -> DbClassSets:
    return DbClassSets(factory)


def _versions(factory: Any, org: str | None = None) -> dict[str, VersionState]:
    try:
        return _store(factory).versions(org)
    except LedgerIntegrityError as exc:
        raise ApiError(
            409, "class_set_integrity", f"the class sets' acts no longer fold: {exc}"
        ) from exc


def _state(factory: Any, org: str, n: int) -> VersionState:
    vid = f"{org}/classes@v{n}"
    state = _versions(factory, org).get(vid)
    if state is None:
        raise ApiError(404, "not_found", f"no class set {vid!r}")
    return state


def _refused(
    db: Session, exc: LibraryRefused, *, org: str, actor: str, act: str, vid: str
) -> ApiError:
    append_system_event(
        db,
        trace_id=_trace(org),
        action="class_set.refused",
        actor=actor,
        status=StepStatus.INVALID,
        error=str(exc),
        payload={"act": act, "version_id": vid, "code": exc.code},
    )
    db.commit()
    return ApiError(409, CODE_REFUSED, str(exc), detail={"code": exc.code, "version_id": vid})


def _invalid(msg: str, *loc: str) -> ApiError:
    words = redact(msg)
    return ApiError(
        422,
        "validation_error",
        words,
        detail={"errors": [{"loc": ["body", *loc], "msg": words, "type": "value_error"}]},
    )


def _summary(db: Session, state: VersionState, verdict: Mapping[str, Any]) -> dict[str, Any]:
    names = _names(db, [state.sponsor, state.approver])
    return {
        **state.to_dict(),
        "org": state.version.org,
        "n": state.version.n,
        "sponsor_name": names.get(state.sponsor, ""),
        "approver_name": names.get(state.approver, ""),
        "route": dict(verdict),
    }


def _verdict(db: Session, state: VersionState) -> tuple[dict[str, Any], dict[str, Any]]:
    report = report_for(db, state)
    return routes(state, report).to_dict(), report.to_dict()


def thresholds() -> dict[str, Any]:
    """The validity report's thresholds as served (ADR-0026 item 9, the operator's values)."""
    return {
        "coverage_min": COVERAGE_MIN,
        "kappa_min": KAPPA_MIN,
        "sample_min": SAMPLE_MIN,
        "per_class_min": PER_CLASS_MIN,
        "measurable_min": MEASURABLE_MIN,
        "override_rate_max": OVERRIDE_RATE_MAX,
        "derivation_share": DERIVATION_SHARE,
        "split_seed": SPLIT_SEED,
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get(
    "/classes",
    responses={401: _ERR, 409: _ERR},
    summary="Every organisation's class sets, each version with its status and whether it routes",
)
def classes_index(_viewer: ViewerDep, db: DbDep, factory: SessionFactoryDep) -> dict[str, Any]:
    states = _versions(factory)
    orgs: dict[str, list[dict[str, Any]]] = {}
    for s in sorted(states.values(), key=lambda x: (x.version.org, -x.version.n)):
        verdict, report = _verdict(db, s)
        orgs.setdefault(s.version.org, []).append(
            {**_summary(db, s, verdict), "passes": report["passes"]}
        )
    return {
        "orgs": [{"org": o, "versions": v} for o, v in orgs.items()],
        "repos": sorted(db.execute(select(Repo.name)).scalars()),
        "thresholds": thresholds(),
        # the parents a class may name, with what each means — the proposal form lists them
        "global_classes": [
            {"slug": k, "definition": CLASS_DEFINITIONS[k]} for k in global_parents()
        ],
    }


def _split_counts(version: ClassSetVersion, cases: Sequence[Any]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, int]] = {r: {DERIVATION: 0, CONFIRMATION: 0} for r in version.repos}
    for c in cases:
        out.setdefault(c.repo, {DERIVATION: 0, CONFIRMATION: 0})[c.split] += 1
    return [{"repo": r, **v} for r, v in out.items()]


def _class_counts(version: ClassSetVersion, cases: Sequence[Any]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = {
        c.slug: {DERIVATION: 0, CONFIRMATION: 0} for c in version.classes
    }
    counts[UNCLASSIFIED] = {DERIVATION: 0, CONFIRMATION: 0}
    for case in cases:
        counts[classify(version, case.fields).slug][case.split] += 1
    return [{"class": k, **v} for k, v in counts.items()]


@router.get(
    "/classes/{org}/v/{n}",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="One class-set version: its classes and rules, the split, the validity report, the verdict",
)
def version_detail(
    org: str, n: int, viewer: ViewerDep, db: DbDep, factory: SessionFactoryDep
) -> dict[str, Any]:
    state = _state(factory, org, n)
    verdict, report = _verdict(db, state)
    cases = cases_for(db, state.version)
    report = _withhold_agreement(report, factory, state, cases, viewer.id)
    return {
        **_summary(db, state, verdict),
        "report": report,
        "split": _split_counts(state.version, cases),
        "class_counts": _class_counts(state.version, cases),
        "thresholds": thresholds(),
    }


def _offered(version: ClassSetVersion, cases: Sequence[Case]) -> list[Case]:
    """The derivation commits a person may label: every one but the classes' example commits,
    which a class's page shows as the rule's answer (P-686)."""
    shown = example_keys(cases)
    return [c for c in cases if c.split == DERIVATION and (c.repo, c.task_id) not in shown]


def _my_labels(factory: Any, version_id: str, who: str) -> dict[tuple[str, str], str]:
    return {
        (r.repo, r.task_id): r.capability_class
        for r in _store(factory).labels(version_id, source=SOURCE_PERSON)
        if r.labeller == who
    }


def _withhold_agreement(
    report: dict[str, Any], factory: Any, state: VersionState, cases: Sequence[Case], who: str
) -> dict[str, Any]:
    """The report as ``who`` may read it: while they have labelled some but not all of the
    version's sample, the agreement's κ is withheld from them — seen after each label, it would
    tell them whether their label matched the rule's (P-686)."""
    offered = {(c.repo, c.task_id) for c in _offered(state.version, cases)}
    mine = len(set(_my_labels(factory, state.version_id, who)) & offered)
    if not 0 < mine < len(offered):
        return report
    measures = [
        m
        if m["name"] != "agreement"
        else {
            **m,
            "value": None,
            "state": "withheld",
            "detail": {},
            "words": (
                f"Withheld from you while you label this version's sample: you have labelled "
                f"{mine} of {len(offered)} commits. It shows when you have labelled them all, "
                "so each label stays your own reading."
            ),
        }
        for m in report["measures"]
    ]
    return {**report, "measures": measures}


def _library_states(factory: Any, repo: str) -> dict[str, EntryState]:
    try:
        return DbLibraryLedger(factory).states(repo)
    except LedgerIntegrityError:
        return {}


@router.get(
    "/classes/{org}/v/{n}/classes/{slug}",
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="The page for one class: what the work is, examples, what a ticket carries, what is proven",
)
def class_page(
    org: str,
    n: int,
    slug: str,
    *,
    _viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    state = _state(factory, org, n)
    version = state.version
    klass = version.class_of(slug)
    if klass is None:
        raise ApiError(404, "not_found", f"{version.version_id} has no class {slug!r}")
    verdict, _report = _verdict(db, state)
    cases = cases_for(db, version)
    subjects = {
        (t.repo, t.task_id): t.subject
        for t in db.execute(select(Task).where(Task.repo.in_(version.repos))).scalars()
    }
    mine = [c for c in cases if classify(version, c.fields).slug == slug]
    # example commits are derivation commits, set aside from the labelled sample (P-686); a
    # confirmation commit is kept for the licence
    examples = [
        {"repo": c.repo, "sha": c.task_id, "subject": subjects.get((c.repo, c.task_id), ""),
         "size": c.size, "proxy": c.fields.proxy}
        for c in examples_of(version, cases)[slug]
    ]  # fmt: skip
    signed_slots: list[str] = []
    context: list[dict[str, Any]] = []
    for repo in version.repos:
        states = _library_states(factory, repo)
        if klass.entry_id and klass.entry_repo == repo:
            wt = states.get(klass.entry_id)
            if wt is not None and wt.usable:
                signed_slots = list(wt.entry.slots)
        for s in signed_context(states.values()):
            e = s.entry
            if e.kind == KIND_WORK_TYPE or not ({slug, klass.parent} & set(e.work_types)):
                continue
            context.append(
                {"repo": repo, "entry_id": s.entry_id, "title": e.title, "statement": e.statement,
                 "sponsor": s.sponsor, "approver": s.approver, "signed_at": s.signed_at,
                 "effect": s.effect}
            )  # fmt: skip
    names = _names(db, [x for c in context for x in (c["sponsor"], c["approver"])])
    for c in context:
        c["sponsor_name"], c["approver_name"] = (
            names.get(c["sponsor"], ""),
            names.get(c["approver"], ""),
        )
    library = [
        {"repo": r, "work_type": klass.entry_id.split("/", 1)[1]
         if klass.entry_id and klass.entry_repo == r else klass.parent}
        for r in version.repos
    ]  # fmt: skip
    sizes: list[dict[str, Any]] = []
    for repo in version.repos:
        repo_row = db.get(Repo, repo)
        if repo_row is None:
            continue
        readers = factory_standard.readers_in(
            db,
            repo,
            checks_arm=checks_arm_in(db, repo),
            posture_class=deployment_posture_class(settings, repo_row),
        )
        for size in SIZES:
            # only commits a reading of the class can pool: those mined under its parent (P-682)
            confirming = sum(
                1 for c in mine if c.repo == repo and c.size == size and c.split == CONFIRMATION
                and c.qualified and c.mined_class == klass.parent
            )  # fmt: skip
            std = readers.standard_for(
                CellRef(klass.parent, size, taxonomy=version.version_id, org_class=slug)
            )
            sizes.append(
                {
                    "repo": repo,
                    "size": size,
                    "confirmation": confirming,
                    "standard": (
                        {
                            "arm": std.arm,
                            "reading_id": std.reading_id,
                            "signed": standard_signed(std),
                            "ceiling": not std.licenses,
                        }
                        if std is not None
                        else None
                    ),
                    "next": "" if std is not None else _next_measurement(verdict, confirming),
                }
            )
    return {
        "org": org,
        "version_id": version.version_id,
        "status": state.status,
        "route": verdict,
        "slug": klass.slug,
        "title": klass.title,
        "definition": klass.definition,
        "parent": klass.parent,
        "parent_definition": CLASS_DEFINITIONS.get(klass.parent, ""),
        "rule": klass.rule.to_dict(),
        "rule_words": rule_in_words(klass.rule),
        "entry_id": klass.entry_id,
        "entry_repo": klass.entry_repo,
        "examples": examples,
        "ticket_slots": [
            {"name": s.name, "question": s.question, "kind": s.kind}
            for s in slots_for(klass.parent)
        ],
        "signed_slots": signed_slots,
        "context": context,
        "library": library,
        "sizes": sizes,
    }


def rule_in_words(rule: ClassRule) -> str:
    """The rule as a person reads it."""
    parts: list[str] = []
    if rule.words:
        parts.append("the ticket's text says " + " or ".join(f"“{w}”" for w in rule.words))
    if rule.work_item_types:
        parts.append("it is a " + " or ".join(rule.work_item_types))
    if rule.components:
        parts.append("it concerns the component " + " or ".join(rule.components))
    if rule.labels:
        parts.append("it carries the label " + " or ".join(rule.labels))
    return "A ticket is in this class when " + ", and ".join(parts) + "."


def _next_measurement(verdict: Mapping[str, Any], confirming: int) -> str:
    """The next step for one size, said once per row; why the set does not route is said once
    above the table (the page's route line), never repeated on every row."""
    have = f"{confirming} qualified confirmation commit{'s' if confirming != 1 else ''} so far"
    if not verdict.get("routes"):
        return f"Wait for the class set to route; {have}."
    return (
        f"Register a reading of this class (S3, then S1) on its confirmation commits; a first "
        f"look needs {FIRST_LOOK}, and it has {have.removesuffix(' so far')}."
    )


# ---------------------------------------------------------------------------
# The labelling screen
# ---------------------------------------------------------------------------


@router.get(
    "/classes/{org}/v/{n}/label-queue",
    responses={401: _ERR, 403: _ERR, 404: _ERR},
    summary="Derivation commits to label (operator), blind to the rule, other labellers and outcomes",
)
def label_queue(
    org: str,
    n: int,
    *,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    state = _state(factory, org, n)
    version = state.version
    sponsor = operator.id == state.sponsor
    mine = _my_labels(factory, version.version_id, operator.id)
    tasks = {
        (t.repo, t.task_id): t
        for t in db.execute(select(Task).where(Task.repo.in_(version.repos))).scalars()
    }
    items: list[dict[str, Any]] = []
    # the sponsor is offered nothing: the rule is their own words, so their labels would
    # measure its author against it (P-684); nor is any class's example commit (P-686)
    for c in [] if sponsor else _offered(version, cases_for(db, version)):
        if repo and c.repo != repo:
            continue
        t = tasks[(c.repo, c.task_id)]
        spec = dict(t.spec_json or {})
        items.append(
            {
                "repo": c.repo,
                "task_id": c.task_id,
                "message": c.message.text,
                "ticket": c.ticket.to_dict() if c.ticket is not None else None,
                "diff": {
                    "source_files": len(spec.get("src_files") or ()),
                    "test_files": len(spec.get("test_files") or ()),
                    "churn": int(spec.get("src_churn") or 0),
                },
                "my_label": mine.get((c.repo, c.task_id), ""),
            }
        )
    items.sort(key=lambda x: (x["my_label"] != "", x["repo"], x["task_id"]))
    return {
        "version_id": version.version_id,
        "classes": [
            {"slug": k.slug, "title": k.title, "definition": k.definition} for k in version.classes
        ],
        "items": items,
        "labelled_by_me": sum(1 for x in items if x["my_label"]),
        "sample_min": SAMPLE_MIN,
        "per_class_min": PER_CLASS_MIN,
        "sponsor": sponsor,
    }


@router.post(
    "/classes/{org}/v/{n}/labels",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="A person's label of one derivation commit (operator); a confirmation commit is 409",
)
def add_label(
    org: str,
    n: int,
    *,
    body: LabelIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> dict[str, Any]:
    state = _state(factory, org, n)
    version = state.version
    if body.repo not in version.repos:
        raise _invalid(f"{version.version_id} does not cover {body.repo}", "repo")
    task = db.get(Task, (body.repo, body.task_id))
    if task is None:
        raise ApiError(404, "not_found", f"no commit {body.task_id!r} in {body.repo}")
    klass = body.capability_class
    if klass != UNCLASSIFIED and version.class_of(klass) is None:
        raise _invalid(f"{version.version_id} has no class {klass!r}", "class")
    refusal: ClassSetRefused | None = None
    if operator.id == state.sponsor:
        refusal = ClassSetRefused(
            "you sponsored this class set: its rule is your own words, so your labels would "
            "check the rule against its author — another person labels its sample (P-684)",
            code=REFUSAL_SPONSOR_LABEL,
        )
    elif version.split(body.repo, body.task_id) != DERIVATION:
        refusal = ClassSetRefused(
            "this commit is in the confirmation set: a person labels derivation commits only, "
            "so the commits a class set is licensed on are never the ones it was checked on "
            "(ADR-0026 item 9)",
            code=REFUSAL_CONFIRMATION_LABEL,
        )
    elif (body.repo, body.task_id) in example_keys(cases_for(db, version)):
        refusal = ClassSetRefused(
            "this commit is one of a class's example commits, shown on its page as the rule's "
            "answer, so it is never labelled (P-686)",
            code=REFUSAL_EXAMPLE_LABEL,
        )
    if refusal is not None:
        raise _refused(db, refusal, org=org, actor=operator.id, act="label", vid=version.version_id)
    _store(factory).add_labels(
        version.version_id, [(body.repo, body.task_id, klass)], source=SOURCE_PERSON,
        labeller=operator.id,
    )  # fmt: skip
    append_system_event(
        db,
        trace_id=_trace(org),
        action="class_set.labelled",
        repo=body.repo,
        actor=operator.id,
        task_id=body.task_id,
        payload={"version_id": version.version_id, "class": klass},
    )
    db.commit()
    return {"version_id": version.version_id, "repo": body.repo, "task_id": body.task_id,
            "class": klass, "labeller": operator.id}  # fmt: skip


# ---------------------------------------------------------------------------
# Acts
# ---------------------------------------------------------------------------


def _rule(r: RuleIn) -> ClassRule:
    return ClassRule(
        words=tuple(r.words),
        work_item_types=tuple(r.work_item_types),
        components=tuple(r.components),
        labels=tuple(r.labels),
    )


def component_names(factory: Any, repos: Iterable[str]) -> set[str]:
    """The organisation's component names: the slugs of the signed component entries of the
    version's repositories' libraries (ADR-0026 items 9 and 10)."""
    out: set[str] = set()
    for repo in repos:
        for s in _library_states(factory, repo).values():
            if s.entry.kind == KIND_COMPONENT and s.usable:
                out.add(s.entry.slug)
    return out


def _class_from(factory: Any, c: ClassIn, i: int) -> OrgClass:
    slug, title, definition, parent = c.slug, c.title, c.definition, c.parent
    entry_id = entry_repo = ""
    if c.entry_repo or c.entry_slug:
        entry_id = entry_id_of(KIND_WORK_TYPE, c.entry_slug)
        wt = _library_states(factory, c.entry_repo).get(entry_id)
        if wt is None or not wt.usable:
            raise _invalid(
                f"{c.entry_repo} has no signed work-type entry {c.entry_slug!r}: a class taken "
                "from the library is a signed work type",
                "classes", str(i), "entry_slug",
            )  # fmt: skip
        entry_repo = c.entry_repo
        slug = slug or wt.entry.slug
        title = title or wt.entry.title
        definition = definition or wt.entry.statement
        parent = parent or wt.entry.parent_class
    try:
        return OrgClass(
            slug=slug,
            title=title,
            definition=definition,
            parent=parent,
            rule=_rule(c.rule),
            entry_id=entry_id,
            entry_repo=entry_repo,
        )
    except ValueError as exc:
        # name the class the refusal is about, so a person proposing many knows which line
        words = str(exc).removeprefix(f"{slug}: ")
        raise _invalid(f"Class {i + 1} ({slug or 'no slug'}): {words}", "classes", str(i)) from exc


def _propose(
    db: Session,
    factory: Any,
    org: str,
    repos: list[str],
    classes: list[OrgClass],
    *,
    who: Principal,
) -> dict[str, Any]:
    for repo in repos:
        if db.get(Repo, repo) is None:
            raise _invalid(f"no repository {repo!r}", "repos")
    known = component_names(factory, repos)
    for i, k in enumerate(classes):
        unknown = sorted(set(k.rule.components) - known)
        if unknown:
            raise _invalid(
                f"{k.slug} names {', '.join(unknown)}, which is not a signed component of "
                f"{', '.join(repos)}: a rule names the organisation's components from the library",
                "classes", str(i), "rule", "components",
            )  # fmt: skip
    current = _versions(factory, org)
    top = max((s.version.n for s in current.values()), default=0)
    # one organisation's class sets per repository: two would each claim its tickets, and the
    # intake would pick one by the order of their names (P-685)
    for other in _versions(factory).values():
        taken = sorted(set(other.version.repos) & set(repos))
        if other.version.org != org and other.status != STATUS_REVOKED and taken:
            exc = ClassSetRefused(
                f"{', '.join(taken)} already has {other.version_id}, {other.version.org}'s: a "
                "repository's commits and tickets are described by one organisation's classes. "
                "Revoke that version first, or propose under its organisation",
                code=REFUSAL_REPO_TAKEN,
            )
            raise _refused(
                db, exc, org=org, actor=who.id, act=ACT_PROPOSE, vid=f"{org}/classes@v{top + 1}"
            )
    try:
        version = ClassSetVersion(
            org=org,
            n=top + 1,
            classes=tuple(classes),
            repos=tuple(repos),
            proposed_by=who.id,
            based_on=f"{org}/classes@v{top}" if top else "",
        )
    except ValueError as exc:
        raise _invalid(str(exc)) from exc
    act = new_act(
        org, version.version_id, version.digest, ACT_PROPOSE, who.id,
        body={"version": version.content()},
    )  # fmt: skip
    try:
        chained, state = _store(factory).append(act)
    except LibraryRefused as exc:
        raise _refused(
            db, exc, org=org, actor=who.id, act=ACT_PROPOSE, vid=version.version_id
        ) from exc
    labelled = relabel(db, state, actor=who.id)
    append_system_event(
        db,
        trace_id=_trace(org),
        action="class_set.proposed",
        actor=who.id,
        payload={"version_id": version.version_id, "digest": version.digest,
                 "act_id": chained.act_id, "classes": len(classes), "repos": list(repos)},
    )  # fmt: skip
    append_system_event(
        db,
        trace_id=_trace(org),
        action="class_set.relabelled",
        actor=who.id,
        payload={"version_id": version.version_id, "labels": labelled},
    )
    db.commit()
    verdict, _ = _verdict(db, state)
    return _summary(db, state, verdict)


@router.post(
    "/classes/{org}/versions",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Propose the organisation's next class set (operator); the proposer is its sponsor",
)
def propose_version(
    org: str, *, body: ProposeIn, operator: OperatorDep, db: DbDep, factory: SessionFactoryDep
) -> dict[str, Any]:
    classes = [_class_from(factory, c, i) for i, c in enumerate(body.classes)]
    return _propose(db, factory, org, list(dict.fromkeys(body.repos)), classes, who=operator)


@router.post(
    "/classes/{org}/versions/from-library",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Propose version N+1 from the library's signed work-type entries (operator; DL-044 seam)",
)
def propose_from_library(
    org: str, *, body: FromLibraryIn, operator: OperatorDep, db: DbDep, factory: SessionFactoryDep
) -> dict[str, Any]:
    """The DL-044 registry seam: a using team adds a class by signing a work-type entry in the
    library; version N+1 keeps the latest version's classes and adds every signed work-type
    entry of ``repos`` not yet a class, with the rule ``rules`` names for it."""
    current = _versions(factory, org)
    latest = max(current.values(), key=lambda s: s.version.n, default=None)
    classes: list[OrgClass] = list(latest.version.classes) if latest is not None else []
    have = {c.slug for c in classes}
    repos = list(dict.fromkeys([*(latest.version.repos if latest else ()), *body.repos]))
    added = 0
    for repo in body.repos:
        for s in sorted(_library_states(factory, repo).values(), key=lambda x: x.entry.slug):
            e = s.entry
            if e.kind != KIND_WORK_TYPE or not s.usable or e.slug in have:
                continue
            rule = body.rules.get(e.slug)
            if rule is None:
                raise _invalid(
                    f"the signed work type {e.slug} of {repo} needs its rule: name it in rules",
                    "rules", e.slug,
                )  # fmt: skip
            classes.append(
                _class_from(
                    factory,
                    ClassIn(rule=rule, entry_repo=repo, entry_slug=e.slug),
                    len(classes),
                )
            )
            have.add(e.slug)
            added += 1
    if not added:
        raise _invalid(
            "no signed work-type entry of these repositories is new: sign one in the library "
            "first, then propose the next version from it",
            "repos",
        )
    return _propose(db, factory, org, repos, classes, who=operator)


@router.post(
    "/classes/{org}/v/{n}/sign",
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Sign a class set (approver, never its sponsor); 409 class_set_refused same_person",
)
def sign_version(
    org: str,
    n: int,
    *,
    body: DigestIn,
    approver: ApproverDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> dict[str, Any]:
    state = _state(factory, org, n)
    act = new_act(org, state.version_id, body.digest, ACT_SIGN, approver.id)
    try:
        chained, after = _store(factory).append(act)
    except LibraryRefused as exc:
        raise _refused(
            db, exc, org=org, actor=approver.id, act=ACT_SIGN, vid=state.version_id
        ) from exc
    append_system_event(
        db,
        trace_id=_trace(org),
        action="class_set.signed",
        actor=approver.id,
        payload={"version_id": state.version_id, "digest": body.digest,
                 "sponsor": after.sponsor, "act_id": chained.act_id},
    )  # fmt: skip
    db.commit()
    verdict, _ = _verdict(db, after)
    return _summary(db, after, verdict)


@router.post(
    "/classes/{org}/v/{n}/revoke",
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Revoke a class set with a reason (approver); it then routes nothing",
)
def revoke_version(
    org: str,
    n: int,
    *,
    body: ReasonIn,
    approver: ApproverDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> dict[str, Any]:
    state = _state(factory, org, n)
    act = new_act(
        org, state.version_id, state.version.digest, ACT_REVOKE, approver.id,
        body={"reason": body.reason},
    )  # fmt: skip
    try:
        chained, after = _store(factory).append(act)
    except LibraryRefused as exc:
        raise _refused(
            db, exc, org=org, actor=approver.id, act=ACT_REVOKE, vid=state.version_id
        ) from exc
    append_system_event(
        db,
        trace_id=_trace(org),
        action="class_set.revoked",
        actor=approver.id,
        payload={"version_id": state.version_id, "act_id": chained.act_id},
    )
    db.commit()
    verdict, _ = _verdict(db, after)
    return _summary(db, after, verdict)


@router.get(
    "/classes/verify",
    responses={401: _ERR},
    summary="Walk the class sets' hash chain from genesis (never raises)",
)
def verify_classes(_viewer: ViewerDep, factory: SessionFactoryDep) -> dict[str, Any]:
    store = _store(factory)
    try:
        return {"ok": True, "acts": store.verify(), "error": ""}
    except LedgerIntegrityError as exc:
        return {"ok": False, "acts": len(store.acts()), "error": str(exc)}


__all__ = ["component_names", "router", "rule_in_words", "thresholds"]
