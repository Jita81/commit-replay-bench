"""``/readings`` — register a reading before its first attempt, and read every reading back.

ADR-0026 items 2 to 5: a cell is licensed only by a **reading** registered before its first
attempt — the cell, the hierarchy of context arms richest first, any descriptive arms, the look
rule, the share of the cell's error budget it spends, the test author's model and the frozen
pool of qualified commits with its SHA-256 — frozen by RULE (every qualified commit of the cell,
or every one authored since a date), never by a hand-picked list (DL-097). ``POST /readings``
(operator; CSRF-bound like every cookie-authenticated write) writes one ``reading.registered``
event under the events store's write lock, so two registrations can never both spend the last of
a cell's budget; it is refused ``409 reading_exists`` when the reading is already registered (a
retried request, under any second or actor, names it in ``detail.reading_id`` and writes nothing
— P-793), ``409 lint_disabled`` while the repository's lint is switched off (P-796), ``409
pool_seen`` when a pool commit already has a graded row under an arm of the hierarchy at this
apparatus (a reserved.v1 reading: any replay row at apparatus 2.4 or later, under any arm or
test author — P-797), ``422 pool_not_blind`` when the caller names a pool the rule does not
give, ``409 budget_spent`` when the budget cannot cover the rule, and ``422 invalid_reading``
for a shape the ADR forbids, and ``404 campaign_unknown`` when it names a ``campaign_id`` no
verified campaign has — a reading names its campaign at birth, a run filed under it is then
filed under that campaign, and it counts only runs the campaign admitted (DL-382). ``GET
/readings`` serves every reading of a repository evaluated over its rows — each arm's look
state, the attempt rule it reads under and, for a reserved.v1 reading, the treatment its
attempts are pinned to, the commits each arm has reserved (P-792), how many of those settled
with no row (``settled_unrowed``, F8) and how its pool moved since registration
(``pool_drift``; a drifted reading reads ``undecided`` — P-797) — and each
cell's budget spent. A reserved.v1 pool is read from qualification records, never from the
task's mined ``gold_clean``: the cell's commits whose record in force in the latest posture of
the reading's posture class is ``qualified``, pinned by record id (P-797). ``standard_for`` is
the seam the factory's entry gate reads (ADR-0026 item 8). ``POST /readings/forward`` (operator)
registers the forward reading of a ceiling (DL-334): ``S2`` on the factory's cell, counted on
calibration builds graded on a second person's held-out tests, the one reading that can promote
the ceiling; ``load_readings`` enrols its pool. A reading on the factory's cell — the forward
reading among them — may name no campaign (DL-382): its runs are factory runs, which no submit
gate requires to be filed under a campaign (a factory run names a ``reading_id`` only under a
reserved.v1 forward reading, ``attempt_rule``, which reserves each ticket's first build, P-792
C8); both routes refuse its ``campaign_id`` ``422 campaign_unsupported_reading``.
A replay or blind reading may name one, because a run filed under it by ``reading_id`` is held
to the campaign (409 ``campaign_required``) and any row counts only when the campaign admitted
its run.

Navigation
----------
What it is:   The readings route module and the store readers the capability map, the sign-off
              write path and the factory share (``load_readings``, ``reading_book``,
              ``standard_for``).
What it does: Registers a reading (operator): freezes the pool by rule from the repository's
              qualified tasks (``pool_by_rule``; a list the rule does not give is refused;
              a reserved.v1 pool from the qualification records in force in the latest
              posture of its class, pinned as ``pool_posture_id`` and ``pool_qualifications``
              — ``_qualified_reserved``, P-797) —
              under an organisation's class set, only the confirmation commits its rule puts in
              the reading's ``org_class``, on that class's parent's cell, and only while the set
              routes (ADR-0026 item 9),
              refuses an unsealed posture for a replayed arm, a campaign that does not
              verify (``campaign_unknown``, DL-382) and any campaign on a reading of the
              factory's cell, the forward reading included (``campaign_unsupported_reading``),
              reads the rows and the readings already registered under the lock, refuses a
              reading already registered (``reading_exists``, P-793) and any registration
              while the repository's lint is off (``lint_disabled``, P-796), and writes the
              event (a reserved.v1 reading only when asked: ``attempt_rule``, P-792, hashing
              the repository's ``lint_digest`` — on ``POST /readings/forward`` too, whose
              factory runs then reserve each ticket's first build, C8); lists readings
              with every arm's state and the budget per cell, each with its attempt rule (a
              legacy one ``first_observed.v0``, ``p792: "open on this rule"``), its treatment
              pins, its reserved commits per arm, how many of them settled with no row
              (``settled_unrowed``) and its pool drift (``served_reading``, P-792, P-797: a
              drifted reading reads ``undecided``);
              answers a cell's proven standard on one checks arm and posture class (or
              ``None``).
How:          ``append_event_checked`` (lock → ``_qualified`` or ``_qualified_reserved`` →
              ``crb.core.reading.register`` → insert) →
              ``load_readings`` (verified events; a record that does not re-hash is skipped and
              counted) → ``ReadingBook.evaluate`` over ``DbLedger`` rows → ``served_reading``
              (``treatment_pins``, ``pool_drift``) → ``standard_of``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 2 to 5 and 8's seam),
              docs/adr/0025-routing-v2.md
Works with:   src/crb/core/reading.py (the rules a registration and a reading follow),
              src/crb/store/events.py and src/crb/store/qualifications.py
              (``append_event_checked``: the locked event write; ``latest_posture_of_class``
              and ``qualified_specs``: a reserved.v1 pool),
              src/crb/server/campaigns.py (``campaign_of``: the campaign a reading names;
              ``unplaced_attempts``: the reservations served as ``settled_unrowed``),
              src/crb/server/routes/capability.py (routes every cell on its reading),
              src/crb/server/routes/signoffs.py (the sign-off write path reads the same book),
              src/crb/server/reading_book.py (``load_readings``, re-exported here: the run
              submit gate and the worker read it below this module; ``treatment_pins``, the
              pins the worker halts a moved treatment by and ``GET /readings`` serves;
              ``repo_lint``, the lint a registration refuses or hashes; ``pool_drift``, the
              drift a reserved.v1 reading is served ``undecided`` on),
              src/crb/server/posture_view.py (the deployment's posture class),
              docs/API.md#capability-routing-forecast-sign-off (the two routes documented)
Tested by:    tests/test_server_readings.py, tests/test_forward_reading_e2e.py,
              tests/test_p792_reserved.py (the attempt rule, the pins and the reserved counts,
              the forward reading's opt-in),
              tests/test_p792_pool.py (the pool pinned to its qualification records)
Touch when:   never for a new repository; the reading's shape or the registration's refusals change
              (an ADR amending ADR-0026 first); never for a new repository.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.campaign import REFUSAL_UNKNOWN
from crb.core.capability import ReadingBook
from crb.core.class_sets import CONFIRMATION, is_org_class_set, refuse_reading_pool
from crb.core.context_arm import parse_arm
from crb.core.evidence import utc_now_iso
from crb.core.ledger import (
    CELL_FIELDS,
    LABEL_CHANGE_ID,
    PROCESS_FACTORY,
    GradeRow,
    is_sealed_class,
)
from crb.core.lint import LINT_DISABLED_BY_CONFIG
from crb.core.reading import (
    ATTEMPT_RULE_LEGACY,
    ATTEMPT_RULE_RESERVED,
    DEFAULT_MAX_RERUNS,
    OUTCOME_UNDECIDED,
    READING_EVENT_ACTION,
    REFUSAL_CAMPAIGN_UNSUPPORTED,
    REFUSAL_INVALID,
    REFUSAL_LINT_DISABLED,
    REFUSAL_NOT_A_CEILING,
    REFUSAL_POOL_NOT_BLIND,
    RULE_LOOK_V1,
    Reading,
    ReadingOutcome,
    ReadingRefused,
    Standard,
    budget_spent,
    campaign_unsupported,
    cell_error_budget,
    enrolled,
    evaluate,
    first_per_id,
    lint_config_digest,
    lint_refusal,
    pool_by_rule,
    refuse_unless_blind,
    register,
    register_forward,
    standard_of,
)
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.core.version import APPARATUS_VERSION
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.campaigns import campaign_of, unplaced_attempts
from crb.server.class_set_state import report_for, verdict_for
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep, SettingsDep
from crb.server.posture_view import deployment_posture_class
from crb.server.prevention_state import current_checks_arm
from crb.server.reading_book import load_readings, pool_drift, repo_lint, treatment_pins
from crb.server.routes.repos import get_repo_or_404
from crb.store import qualifications as store_q
from crb.store.class_sets import DbClassSets
from crb.store.events import append_event_checked
from crb.store.ledger import DbLedger
from crb.store.models import Event, Repo, Task

router = APIRouter(tags=["capability"])
_ERR = {"model": ErrorEnvelope}

#: The trace every repository's readings are written under (one per repository).
TRACE_PREFIX = "readings:"


def _trace(repo: str) -> str:
    return TRACE_PREFIX + repo


#: What a reading tests, written before its first attempt (Wave 3 pre-run, Q-24): stripped,
#: and never blank — a reading registered without its question is refused 422.
Hypothesis = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
#: The smallest effect that would matter, a share of attempts in (0, 1].
SmallestEffect = Annotated[float, Field(gt=0, le=1)]
#: The campaign every run of the reading spends under (DL-382): named at registration, never
#: bound later. ``None`` for a reading under no campaign.
CampaignId = Annotated[str | None, Field(pattern=r"^cmp_[0-9a-f]{24}$")]


def _refuse_unknown_campaign(session: Session, campaign_id: str | None) -> None:
    """404 ``campaign_unknown`` — the code ``POST /runs`` answers — when a registration names
    a campaign no verified record has: read inside the registration's lock, so nothing is
    written for a reading whose runs could never be admitted (DL-382)."""
    if campaign_id is not None and campaign_of(session, campaign_id) is None:
        raise ApiError(
            404,
            REFUSAL_UNKNOWN,
            f"no verified campaign {campaign_id!r}",
            detail={"campaign_id": campaign_id},
        )


def reading_book(session: Session, repo: str, rows: Iterable[GradeRow]) -> ReadingBook:
    """Every reading of ``repo`` evaluated over ``rows`` (all arms, ledger order)."""
    return ReadingBook.evaluate(load_readings(session, repo), rows)


def standard_for(
    factory: sessionmaker[Session],
    repo: str,
    cell: Mapping[str, str],
    *,
    checks_arm: str,
    posture_class: str,
    apparatus: str = APPARATUS_VERSION,
    taxonomy: str = GLOBAL_CLASS_SET,
) -> Standard | None:
    """The cell's proven context standard at ``apparatus`` and ``taxonomy`` on ONE checks arm
    and posture class — the arm a ticket's build must carry, the reading that proved it, and
    whether it is only a ceiling (``S3`` alone: calibration builds only) — or ``None``: no
    proven standard. The factory's entry gate reads this (ADR-0026 item 8), naming the
    repository's own checks arm (``current_checks_arm``) and the deployment's posture class
    (``deployment_posture_class``): both are required, so a licence never crosses an arm or a
    posture (P-319)."""
    with factory() as s:
        readings = load_readings(s, repo)
    rows = list(DbLedger(factory).rows(repo=repo))
    return standard_of(
        readings,
        rows,
        repo=repo,
        cell=dict(cell),
        apparatus=apparatus,
        taxonomy=taxonomy,
        checks_arm=checks_arm,
        posture_class=posture_class,
    )


#: ``?arm=standard``: each cell read on its own proven standard arm.
ARM_STANDARD = "standard"
#: The arm a cell with no proven standard is shown on: ``S3``, the arm every sighted replay
#: row of 2.4 carries (the commit's own tests) — a ceiling, so it never delivers.
DISPLAY_ARM = "S3"


def rows_on_standard_arms(
    rows: Sequence[GradeRow], projection: Sequence[str], book: ReadingBook
) -> list[GradeRow]:
    """Each projected cell's rows on ONE arm — :meth:`ReadingBook.standard_rows`."""
    return book.standard_rows(rows, projection, display_arm=DISPLAY_ARM)


def budget_by_cell(readings: Sequence[Reading]) -> list[dict[str, Any]]:
    """What each cell (repository × cell key × apparatus × class-set version) has spent —
    each ``reading_id`` once (``first_per_id``, P-793)."""
    readings = first_per_id(readings)
    seen: dict[tuple[str, str, str, str], Reading] = {}
    for r in readings:
        seen.setdefault(r.budget_key, r)
    out: list[dict[str, Any]] = []
    for key, first in seen.items():
        spent = budget_spent(readings, key)
        out.append(
            {
                "cell": dict(first.cell),
                "apparatus": first.apparatus,
                "taxonomy": first.taxonomy,
                "budget": first.budget,
                "spent": round(spent, 6),
                "remaining": round(max(first.budget - spent, 0.0), 6),
                "readings": sum(1 for r in readings if r.budget_key == key),
            }
        )
    return out


class ReadingIn(BaseModel):
    """A registration: the full cell, the hierarchy (richest first) and the pool RULE — every
    qualified task of the cell's class, size and language, or every one authored at or after
    ``since`` (DL-097). ``pool``, when given, must be that rule's own pool: a hand-picked list
    is refused ``pool_not_blind``. Under ``reserved.v1`` a task is qualified when its record in
    force in the latest posture of the reading's posture class is ``qualified`` (P-797)."""

    repo: str = Field(min_length=1, max_length=64)
    cell: dict[str, str]
    hierarchy: list[str] = Field(min_length=1, max_length=8)
    pool: list[str] = Field(default_factory=list, max_length=2000)
    since: str = Field(default="", max_length=40)
    rule: str = RULE_LOOK_V1
    descriptive: list[tuple[str, int]] = Field(default_factory=list, max_length=4)
    author_model: str = Field(default="", max_length=128)
    taxonomy: str = Field(default=GLOBAL_CLASS_SET, max_length=96)
    posture_class: str = Field(default="", max_length=64)
    #: Under an organisation's class set (``taxonomy`` other than the global vocabulary): the
    #: organisation's class this reading reads — its pool is the confirmation commits the
    #: version's rule puts in that class (ADR-0026 item 9). Empty for the global vocabulary.
    org_class: str = Field(default="", max_length=64)
    #: What the reading tests and the smallest effect that would matter (Wave 3 pre-run,
    #: Q-24): both required and both inside the reading's hash (P-787).
    hypothesis: Hypothesis
    smallest_effect: SmallestEffect
    #: The campaign every run of this reading spends under (DL-382): it must exist and verify
    #: (404 ``campaign_unknown``); hashed into the reading's id when given.
    campaign_id: CampaignId = None
    #: How a commit is read (P-792), opt-in: ``""`` the legacy first-observed rule, or
    #: ``reserved.v1`` — only the attempt a run reserves for a commit before its build decides
    #: it, so a cancel, kill or harness failure after the reservation is that commit's miss.
    #: ``max_reruns`` defaults to 2 under the legacy rule and 0 under reserved.v1 (the only
    #: value it accepts); ``budget_profile`` is the profile every run of a reserved.v1 reading
    #: spends on, ignored under the legacy rule. Both hashed only with the rule.
    attempt_rule: Literal["", "reserved.v1"] = ""
    max_reruns: int | None = Field(default=None, ge=0)
    budget_profile: str = Field(default="default", max_length=64)


class ReadingsOut(BaseModel):
    """``GET /readings``: every reading of ``repo`` evaluated over its rows (each arm's look
    state), with the attempt rule it reads under (``attempt_rule``; a legacy reading also
    ``p792: "open on this rule"``), its treatment pins (``pinned_treatment``) and its reserved
    commits per arm (``reserved``) and its pool drift (``pool_drift``, P-797; a drifted
    reading reads ``undecided``) — :func:`served_reading` — and each cell's budget spent."""

    repo: str
    readings: list[dict[str, Any]]
    budgets: list[dict[str, Any]]
    budget: float


def _qualified(session: Session, repo: str, cell: Mapping[str, str]) -> dict[str, Task]:
    """The repository's qualified tasks (gold checked clean) in the cell's class, size and
    language — what a pool may hold."""
    q = select(Task).where(
        Task.repo == repo,
        Task.capability_class == cell.get("capability_class", ""),
        Task.size == cell.get("size", ""),
        Task.gold_clean.is_(True),
    )
    lang = cell.get("language", "")
    return {
        t.task_id: t
        for t in session.execute(q).scalars()
        if not lang or not t.language or t.language == lang
    }


def _qualified_reserved(
    session: Session, repo: str, cell: Mapping[str, str], posture_class: str
) -> tuple[dict[str, Task], str, dict[str, str]]:
    """A reserved.v1 reading's qualified tasks (P-797): the cell's commits whose record in
    force in the latest posture recorded for ``posture_class`` is ``qualified`` — its projected
    spec and its task row both of the cell's class and size, of its language when both name
    one — with that posture and each commit's record id (``pool_posture_id``,
    ``pool_qualifications``). The mined ``gold_clean`` admits nothing: a commit no record
    qualified, or one whose record in force is unqualified or revoked, is not in the pool."""
    posture_id = store_q.latest_posture_of_class(session, repo, posture_class)
    if not posture_id:
        return {}, "", {}
    klass, size = cell.get("capability_class", ""), cell.get("size", "")
    lang = cell.get("language", "")
    specs = [
        spec
        for spec in store_q.qualified_specs(session, repo, posture_id)
        if spec.capability_class == klass
        and spec.size == size
        and (not lang or not spec.language or spec.language == lang)
    ]
    if not specs:
        return {}, posture_id, {}
    rows = session.execute(
        select(Task).where(Task.repo == repo, Task.task_id.in_([sp.task_id for sp in specs]))
    ).scalars()
    tasks = {t.task_id: t for t in rows if t.capability_class == klass and t.size == size}
    pins = {sp.task_id: sp.qualification_ref for sp in specs if sp.task_id in tasks}
    return tasks, posture_id, pins


def _change_of(task: Task) -> str:
    labels = dict((task.spec_json or {}).get("labels") or {})
    return str(labels.get(LABEL_CHANGE_ID, "") or "")


def _refuse_lint_disabled(s: Session, repo: str) -> dict[str, Any]:
    """The repository's lint, read under the events lock — or 409 ``lint_disabled`` while the
    operator has switched it off, before anything is read or written (P-796,
    :func:`crb.core.reading.lint_refusal`): a row graded with belt 5 off never counts as one
    graded with it on, so a switch thrown after outcomes are seen could reshape what the
    reading counts."""
    lint = repo_lint(s, repo)
    reason = lint_refusal(repo, lint)
    if reason:
        raise ReadingRefused(
            reason,
            code=REFUSAL_LINT_DISABLED,
            detail={"repo": repo, "reason": LINT_DISABLED_BY_CONFIG},
        )
    return lint


def _refuse(exc: ReadingRefused) -> ApiError:
    shape = (REFUSAL_INVALID, REFUSAL_POOL_NOT_BLIND, REFUSAL_CAMPAIGN_UNSUPPORTED)
    code = 422 if exc.code in shape else 409
    if exc.code == REFUSAL_NOT_A_CEILING:
        code = 409
    return ApiError(code, exc.code, str(exc), detail=dict(exc.detail))


@router.post(
    "/readings",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register a reading before its first attempt (operator): cell, hierarchy, rule, frozen pool",
)
def register_reading(
    body: ReadingIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    repo_row: Repo = get_repo_or_404(db, body.repo)
    unknown = sorted(set(body.cell) - set(CELL_FIELDS))
    if unknown:
        raise ApiError(422, REFUSAL_INVALID, f"unknown cell field(s) {unknown}")
    posture = body.posture_class or deployment_posture_class(settings, repo_row)
    try:
        replayed = [a for a in body.hierarchy if parse_arm(a).base != "S2"]
    except ValueError as exc:
        raise ApiError(422, REFUSAL_INVALID, str(exc)) from exc
    if replayed and not is_sealed_class(posture):
        raise ApiError(
            422,
            REFUSAL_INVALID,
            f"a replayed arm counts only rows graded in the sealed posture; this reading would "
            f"read {posture!r} (ADR-0026 item 2) — register it on a docker/<tree>/sealed class",
            detail={"posture_class": posture},
        )
    deployment = settings.posture()
    if replayed and not deployment["sealed"]:
        # the posture class is the sandbox's alone: a host builder under a docker sandbox
        # still names a sealed class, so the deployment itself must be sealed (P-789)
        raise ApiError(
            422,
            REFUSAL_INVALID,
            "a replayed reading needs a sealed deployment: the sandbox and the builder must "
            "both run on docker",
            detail={
                "sandbox_executor": deployment["sandbox_executor"],
                "builder_executor": deployment["builder_executor"],
            },
        )
    checks = current_checks_arm(factory, body.repo)
    try:
        budget = cell_error_budget()
    except ValueError as exc:
        raise ApiError(422, REFUSAL_INVALID, str(exc)) from exc

    org = is_org_class_set(body.taxonomy)
    if org != bool(body.org_class):
        raise ApiError(
            422,
            REFUSAL_INVALID,
            "an organisation's class set is read one class at a time: name org_class with an "
            "organisation's taxonomy, and neither with the global vocabulary",
        )

    def build(s: Session) -> dict[str, Any]:
        lint = _refuse_lint_disabled(s, body.repo)
        _refuse_unknown_campaign(s, body.campaign_id)
        pool_posture_id, pins = "", dict[str, str]()
        if body.attempt_rule == ATTEMPT_RULE_RESERVED:
            qualified, pool_posture_id, pins = _qualified_reserved(s, body.repo, body.cell, posture)
        else:
            qualified = _qualified(s, body.repo, body.cell)
        if org:
            # the class the version's rule gave each commit (the label table), and only its
            # confirmation commits: a commit that derived the class never licenses it
            state, _verdict = verdict_for(s, body.taxonomy)
            klass = state.version.class_of(body.org_class) if state is not None else None
            parent = klass.parent if klass is not None else ""
            if parent and body.cell.get("capability_class", "") != parent:
                # the organisation's class splits its parent's cell and no other: a reading on
                # another global class's cell would be an orphan cell no gate reads (P-682)
                raise ReadingRefused(
                    f"{body.org_class} is a child of {parent}: a reading of it sits on a "
                    f"{parent} cell, never on {body.cell.get('capability_class', '')!r}",
                    code=REFUSAL_INVALID,
                )
            labelled = DbClassSets(factory).rule_labels(body.taxonomy, body.repo)
            qualified = {
                c: t
                for c, t in qualified.items()
                if labelled.get((body.repo, c)) == body.org_class
                and state is not None
                and state.version.split(body.repo, c) == CONFIRMATION
            }
            report = report_for(s, state) if state is not None and state.signed else None
            refuse_reading_pool(
                state,
                report,
                repo=body.repo,
                org_class=body.org_class,
                pool=list(qualified),
                now=utc_now_iso(),
            )
        pool, pool_rule = pool_by_rule(
            {c: str(t.authored or "") for c, t in qualified.items()}, since=body.since
        )
        refuse_unless_blind(list(dict.fromkeys(body.pool)), pool, pool_rule)
        if not pool:
            why = (
                "a reserved.v1 pool freezes only commits whose qualification record in force "
                f"in the latest {posture} posture is qualified (P-797)"
                if body.attempt_rule == ATTEMPT_RULE_RESERVED
                else "a pool freezes qualified commits only"
            )
            raise ReadingRefused(
                f"no qualified task of this cell's class, size and language under {pool_rule}"
                f" — {why}",
                code=REFUSAL_INVALID,
                detail={"pool_posture_id": pool_posture_id} if pool_posture_id else {},
            )
        reading = register(
            repo=body.repo,
            cell=body.cell,
            hierarchy=body.hierarchy,
            pool=pool,
            apparatus=APPARATUS_VERSION,
            taxonomy=body.taxonomy,
            posture_class=posture,
            checks_arm=checks,
            actor=operator.id,
            existing=load_readings(s, body.repo),
            rows=DbLedger(factory).rows(repo=body.repo),
            rule=body.rule,
            descriptive=[(a, int(n)) for a, n in body.descriptive],
            author_model=body.author_model,
            changes={c: _change_of(qualified[c]) for c in pool},
            budget=budget,
            pool_rule=pool_rule,
            org_class=body.org_class,
            hypothesis=body.hypothesis,
            smallest_effect=body.smallest_effect,
            campaign_id=body.campaign_id or "",
            attempt_rule=body.attempt_rule,
            max_reruns=(
                body.max_reruns
                if body.max_reruns is not None
                else (0 if body.attempt_rule else DEFAULT_MAX_RERUNS)
            ),
            budget_profile=body.budget_profile if body.attempt_rule else "",
            lint_digest=lint_config_digest(lint),
            pool_posture_id=pool_posture_id,
            pool_qualifications={c: pins[c] for c in pool if c in pins},
        )
        return reading.to_dict()

    try:
        ev = append_event_checked(
            factory,
            trace_id=_trace(body.repo),
            stage="system",
            action=READING_EVENT_ACTION,
            build=build,
            actor=operator.id,
            repo=body.repo,
        )
    except ReadingRefused as exc:
        raise _refuse(exc) from exc
    return dict(ev.payload)


class ForwardIn(BaseModel):
    """A forward reading (ADR-0026 items 4, 5 and 8; DL-334): the reading whose ``S3``
    ceiling it may promote, and the factory builder, model and provider its calibration
    builds run on. The pool is not named: it is every calibration build of the cell whose
    held-out tests are written after this registration."""

    repo: str = Field(min_length=1, max_length=64)
    promotes: str = Field(min_length=1, max_length=64)
    builder: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="", max_length=64)
    rule: str = RULE_LOOK_V1
    hypothesis: Hypothesis
    smallest_effect: SmallestEffect
    #: Refused when given (422 ``campaign_unsupported_reading``, DL-382): kept on the model so
    #: a body that names a campaign is refused by name, never registered without it.
    campaign_id: CampaignId = None
    #: How a ticket is read (P-792 C8), opt-in as on ``ReadingIn``: ``""`` the legacy rule
    #: (its first ``r1`` factory row after registration), or ``reserved.v1`` — a factory run
    #: filed under the reading (``reading_id``) reserves the ticket's first build before it
    #: starts, and only that attempt decides it, so a failure after the reservation is a
    #: miss. ``max_reruns`` defaults to 2 under the legacy rule and 0 under reserved.v1 (the
    #: only value it accepts); ``budget_profile`` is ignored under the legacy rule. Both are
    #: hashed only with the rule, so a forward reading registered without one keeps its id.
    attempt_rule: Literal["", "reserved.v1"] = ""
    max_reruns: int | None = Field(default=None, ge=0)
    budget_profile: str = Field(default="default", max_length=64)


@router.post(
    "/readings/forward",
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Register the forward (S2) reading of a ceiling before its first calibration build (operator)",
)
def register_forward_reading(
    body: ForwardIn,
    operator: OperatorDep,
    db: DbDep,
    factory: SessionFactoryDep,
) -> dict[str, Any]:
    """The one reading that can promote an ``S3`` ceiling to a standard: ``S2`` on the
    factory's cell, counted only on calibration builds graded on a second person's held-out
    acceptance tests. Refused **409** ``not_a_ceiling`` when the named reading does not read
    ``ceiling`` now, **409** ``reading_exists`` when the same forward reading is already
    registered (a retry writes nothing — P-793), **409** ``lint_disabled`` while the
    repository's lint is switched off (P-796), **409** ``budget_spent`` when the ceiling's
    cell budget cannot cover the rule, **404** for a reading the repository does not have, **422**
    ``campaign_unsupported_reading`` for any ``campaign_id`` — before anything is read or
    written: its calibration builds are factory runs, which no submit gate requires to be
    filed under a campaign (DL-382, :func:`crb.core.reading.campaign_unsupported`), and
    **422** ``invalid_reading`` (``detail: {max_reruns, budget_profile}``, nothing written)
    for a reserved.v1 body asking for re-runs or naming no budget profile. With
    ``attempt_rule: reserved.v1`` a factory run names the reading and reserves each ticket's
    first build (P-792 C8); without it nothing ties a factory run to the reading."""
    if body.campaign_id is not None:
        raise ApiError(
            422,
            REFUSAL_CAMPAIGN_UNSUPPORTED,
            campaign_unsupported(PROCESS_FACTORY),
            detail={"campaign_id": body.campaign_id, "process_step": PROCESS_FACTORY},
        )
    get_repo_or_404(db, body.repo)
    rows = list(DbLedger(factory).rows(repo=body.repo))

    def build(s: Session) -> dict[str, Any]:
        lint = _refuse_lint_disabled(s, body.repo)
        readings = load_readings(s, body.repo)
        named = next((r for r in readings if r.reading_id == body.promotes), None)
        if named is None:
            raise ApiError(404, "not_found", f"no reading {body.promotes!r} on {body.repo!r}")
        reading = register_forward(
            ceiling=evaluate(named, rows),
            builder=body.builder,
            model=body.model,
            provider=body.provider,
            actor=operator.id,
            existing=readings,
            rule=body.rule,
            budget=cell_error_budget(),
            hypothesis=body.hypothesis,
            smallest_effect=body.smallest_effect,
            lint_digest=lint_config_digest(lint),
            attempt_rule=body.attempt_rule,
            max_reruns=(
                body.max_reruns
                if body.max_reruns is not None
                else (0 if body.attempt_rule else DEFAULT_MAX_RERUNS)
            ),
            budget_profile=body.budget_profile if body.attempt_rule else "",
        )
        return reading.to_dict()

    try:
        ev = append_event_checked(
            factory,
            trace_id=_trace(body.repo),
            stage="system",
            action=READING_EVENT_ACTION,
            build=build,
            actor=operator.id,
            repo=body.repo,
        )
    except ReadingRefused as exc:
        raise _refuse(exc) from exc
    except ValueError as exc:
        raise ApiError(422, REFUSAL_INVALID, str(exc)) from exc
    return dict(ev.payload)


@router.get(
    "/readings",
    response_model=ReadingsOut,
    responses={401: _ERR, 404: _ERR},
    summary="Every registered reading of a repo with each arm's look state, and each cell's budget spent",
)
def list_readings(
    viewer: ViewerDep,
    db: DbDep,
    factory: SessionFactoryDep,
    repo: str = Query(min_length=1, max_length=64),
) -> ReadingsOut:
    del viewer
    get_repo_or_404(db, repo)
    readings = load_readings(db, repo)
    book = ReadingBook.evaluate(readings, DbLedger(factory).rows(repo=repo))
    return ReadingsOut(
        repo=repo,
        readings=[served_reading(db, o) for o in book.outcomes],
        budgets=budget_by_cell(readings),
        budget=cell_error_budget(),
    )


#: What ``GET /readings`` says of a legacy reading's P-792 channels: the reserved.v1 rule
#: closes them, and the legacy rule (``first_observed.v0``), whose id never moves, does not.
P792_OPEN = "open on this rule"


def _pin(ev: Event, half: str) -> dict[str, Any]:
    """One half of a treatment pin as its reservation stored it: the body, its digest
    (``deployment_fp`` / ``arm_fp``) and the event that pinned it."""
    payload = dict(ev.payload_json or {})
    body = dict((payload.get("treatment_body") or {}).get(half) or {})
    return {"body": body, "digest": str(payload.get(f"{half}_fp") or ""), "event_id": ev.event_id}


def served_reading(session: Session, outcome: ReadingOutcome) -> dict[str, Any]:
    """One reading as ``GET /readings`` serves it: the evaluated outcome
    (``ReadingOutcome.to_dict``) with the attempt rule it reads under (``attempt_rule``:
    ``reserved.v1``, else ``first_observed.v0`` with ``p792: "open on this rule"``) and, for a
    reserved.v1 reading (P-792 channels C3, C5 and C17), the treatment its attempts are pinned
    to — ``pinned_treatment``: ``{deployment: {body, digest, event_id} | null, arms: {arm:
    {body, digest, event_id}}}`` from the campaign's first reservation on the repository and
    each arm's first (:func:`~crb.server.reading_book.treatment_pins`, the rule the worker
    halts a moved treatment by), ``null`` before any — ``reserved``, the commits each arm
    has reserved of those it enrols, ``settled_unrowed``, how many of those reservations are
    unplaced attempts — settled with no row, so the tally charges them and the campaign stops
    on ``unplaced_spend`` (:func:`~crb.server.campaigns.unplaced_attempts`, F8) — and
    ``pool_drift``, how its pool moved since registration
    (:func:`~crb.server.reading_book.pool_drift`, P-797): a drifted reading reads
    ``undecided`` with no standard, whatever its rows say, until the pool is restored. A legacy
    reading has none of them (``null``)."""
    reading = outcome.reading
    out = outcome.to_dict()
    if not reading.reserved:
        out.update(
            attempt_rule=ATTEMPT_RULE_LEGACY,
            p792=P792_OPEN,
            pinned_treatment=None,
            reserved=None,
            settled_unrowed=None,
            pool_drift=None,
        )
        return out
    deployment, arms = treatment_pins(session, reading)
    pinned = {a: _pin(ev, "arm") for a, ev in arms.items() if a in reading.arms}
    reservations = reading.reservations or {}
    unplaced = {
        a.reservation_event_id
        for a in unplaced_attempts(session, {res.run_id for res in reservations.values()})
        if a.reservation_event_id
    }
    out.update(
        attempt_rule=reading.attempt_rule,
        pinned_treatment=(
            {
                "deployment": _pin(deployment, "deployment") if deployment is not None else None,
                "arms": pinned,
            }
            if deployment is not None or pinned
            else None
        ),
        reserved={
            arm: sum(1 for c in enrolled(reading, arm) if (arm, c) in reservations)
            for arm in reading.arms
        },
        settled_unrowed={
            arm: sum(
                1
                for c in enrolled(reading, arm)
                if (arm, c) in reservations and reservations[(arm, c)].event_id in unplaced
            )
            for arm in reading.arms
        },
    )
    drift = pool_drift(session, reading)
    out["pool_drift"] = drift
    if drift:
        out.update(state=OUTCOME_UNDECIDED, standard=None, ceiling=False)
    return out


__all__ = [
    "ARM_STANDARD",
    "DISPLAY_ARM",
    "budget_by_cell",
    "load_readings",
    "reading_book",
    "router",
    "rows_on_standard_arms",
    "served_reading",
    "standard_for",
]
