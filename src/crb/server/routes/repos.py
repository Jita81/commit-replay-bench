"""``/repos`` — configured repositories, their config history, probe, change profile, tasks.

A repo row is ``RepoConfig.to_dict()`` plus its probe state. Every config change
is validated through :meth:`crb.core.spec.RepoConfig.from_dict` (an invalid config
cannot be stored) and recorded as a ``system/repo.updated`` event whose payload is
the REDACTED field diff — the audit trail for "who changed the belt scope" lives in
the append-only events table, not in a mutable column.

The change profile (:func:`crb.core.capability.profile_repo`) walks the clone's
git history; it is cached in ``config_json["profile"]`` with a timestamp and
recomputed on ``?refresh=true``. It is measurement INPUT (what the repo's work
looks like), never a verdict.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crb.core.capability import RepoChangeProfile, profile_repo
from crb.core.git import GitError, GitRepo
from crb.core.redact import redact
from crb.core.spec import SIZE_TIER_NAMES, RepoConfig, TaskSpec
from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SessionFactoryDep
from crb.server.routes.runs import (
    append_system_event,
    new_run,
    require_jobs,
    run_out,
    system_trace_id,
)
from crb.server.schemas import (
    TERMINAL_STATUSES,
    Page,
    PageDep,
    ProfileCell,
    RepoCreateRequest,
    RepoDetail,
    RepoLastRun,
    RepoProbe,
    RepoProfile,
    RepoSummary,
    RepoTaskCounts,
    RepoUpdateRequest,
    RunCreateRequest,
    RunOut,
    TaskSpecOut,
)
from crb.store.models import Repo, Run, Task

router = APIRouter(tags=["repos"])
_ERR = {"model": ErrorEnvelope}

PROFILE_KEY = "profile"
PROBE_STATES: frozenset[str] = frozenset({"ok", "degraded", "down"})


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------


def _validated_config(name: str, raw: Mapping[str, Any]) -> RepoConfig:
    """``RepoConfig.from_dict`` with ``ValueError`` → 422 in the envelope."""
    try:
        return RepoConfig.from_dict(name, raw)
    except (ValueError, KeyError, TypeError) as exc:
        raise ApiError(
            422,
            "validation_error",
            f"invalid repo config: {redact(str(exc))}",
            detail={"errors": [{"loc": ["body"], "msg": redact(str(exc)), "type": "value_error"}]},
        ) from exc


def _config_of(repo: Repo) -> RepoConfig:
    raw = {k: v for k, v in dict(repo.config_json or {}).items() if k != PROFILE_KEY}
    raw.setdefault("path", repo.clone_path)
    raw.setdefault("url", repo.url)
    return _validated_config(repo.name, raw)


def _stored_config(config: RepoConfig, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    d = config.to_dict()
    if extra:
        d.update(extra)
    return d


def config_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{field: {"from": …, "to": …}}`` over the keys that changed (profile cache excluded)."""
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(set(old) | set(new)):
        if key == PROFILE_KEY:
            continue
        if old.get(key) != new.get(key):
            out[key] = {"from": old.get(key), "to": new.get(key)}
    return out


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _task_counts(session: Session, name: str) -> RepoTaskCounts:
    rows = session.execute(
        select(Task.pool, Task.gold_clean, func.count(Task.task_id))
        .where(Task.repo == name)
        .group_by(Task.pool, Task.gold_clean)
    ).all()
    total = standard = hard = gold_ok = gold_bad = unchecked = 0
    for pool, gold, raw_n in rows:
        n = int(raw_n)
        total += n
        if pool == "hard":
            hard += n
        else:
            standard += n
        if gold is True:
            gold_ok += n
        elif gold is False:
            gold_bad += n
        else:
            unchecked += n
    return RepoTaskCounts(
        total=total,
        standard=standard,
        hard=hard,
        gold_clean=gold_ok,
        gold_failed=gold_bad,
        unchecked=unchecked,
    )


def _latest_run(session: Session, name: str, *, kind: str | None = None) -> Run | None:
    q = select(Run).where(Run.repo == name)
    if kind:
        q = q.where(Run.kind == kind)
    return session.execute(
        q.order_by(Run.created.desc(), Run.id.desc()).limit(1)
    ).scalar_one_or_none()


def _probe(repo: Repo, probe_run: Run | None) -> RepoProbe:
    if repo.probe_status in PROBE_STATES:
        status_ = repo.probe_status
    elif probe_run is None:
        status_ = "not_probed"
    elif probe_run.status in TERMINAL_STATUSES:
        status_ = "down" if probe_run.status != "succeeded" else "ok"
    else:
        status_ = probe_run.status
    checked = probe_run.finished if probe_run is not None and probe_run.finished else None
    return RepoProbe(
        status=status_,
        run_id=probe_run.id if probe_run is not None else None,
        checked=checked,
        detail=repo.probe_detail or (probe_run.error if probe_run is not None else ""),
    )


def repo_summary(session: Session, repo: Repo) -> RepoSummary:
    last = _latest_run(session, repo.name)
    return RepoSummary(
        name=repo.name,
        language=repo.language,
        runner=repo.runner,
        url=repo.url,
        clone_path=repo.clone_path,
        probe=_probe(repo, _latest_run(session, repo.name, kind="probe")),
        task_counts=_task_counts(session, repo.name),
        last_run=(
            RepoLastRun(
                id=last.id, kind=last.kind, status=last.status, finished=last.finished or None
            )
            if last is not None
            else None
        ),
        created=repo.created,
        updated=repo.updated,
    )


def repo_detail(session: Session, repo: Repo) -> RepoDetail:
    summary = repo_summary(session, repo)
    cached = dict(repo.config_json or {}).get(PROFILE_KEY) or {}
    return RepoDetail(
        **summary.model_dump(),
        config=_config_of(repo).to_dict(),
        profile_computed_at=str(cached.get("computed_at")) if cached else None,
    )


def get_repo_or_404(session: Session, name: str) -> Repo:
    repo = session.get(Repo, name)
    if repo is None:
        raise ApiError(404, "not_found", f"no repo {name!r}")
    return repo


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/repos", response_model=Page[RepoSummary], responses={401: _ERR})
def list_repos(viewer: ViewerDep, db: DbDep, page: PageDep) -> Page[RepoSummary]:
    del viewer
    total = int(db.execute(select(func.count(Repo.name))).scalar_one())
    repos = list(
        db.execute(select(Repo).order_by(Repo.name).limit(page.limit).offset(page.offset)).scalars()
    )
    return Page[RepoSummary](
        items=[repo_summary(db, r) for r in repos],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/repos",
    response_model=RepoDetail,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 409: _ERR, 422: _ERR},
    summary="Register a repository (config validated; recorded as a system event)",
)
def create_repo(body: RepoCreateRequest, operator: OperatorDep, db: DbDep) -> RepoDetail:
    if db.get(Repo, body.name) is not None:
        raise ApiError(409, "already_exists", f"repo {body.name!r} already exists")
    config = _validated_config(body.name, body.config_updates())
    repo = Repo(
        name=config.name,
        language=config.language.value,
        runner=config.runner,
        clone_path=config.path,
        url=config.url,
        config_json=_stored_config(config),
        probe_status="unknown",
    )
    db.add(repo)
    append_system_event(
        db,
        trace_id=system_trace_id("repo", config.name),
        action="repo.created",
        repo=config.name,
        actor=operator.id,
        payload={"config": config.to_dict()},
    )
    db.commit()
    return repo_detail(db, repo)


@router.get("/repos/{name}", response_model=RepoDetail, responses={401: _ERR, 404: _ERR})
def get_repo(name: str, viewer: ViewerDep, db: DbDep) -> RepoDetail:
    del viewer
    return repo_detail(db, get_repo_or_404(db, name))


@router.put(
    "/repos/{name}",
    response_model=RepoDetail,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Update the config (partial); the redacted diff is appended to the events table",
)
def update_repo(name: str, body: RepoUpdateRequest, operator: OperatorDep, db: DbDep) -> RepoDetail:
    repo = get_repo_or_404(db, name)
    old = _config_of(repo).to_dict()
    merged = {**old, **body.config_updates()}
    config = _validated_config(name, merged)
    new = config.to_dict()
    diff = config_diff(old, new)
    cached = dict(repo.config_json or {}).get(PROFILE_KEY)
    repo.language = config.language.value
    repo.runner = config.runner
    repo.clone_path = config.path
    repo.url = config.url
    repo.config_json = _stored_config(config, {PROFILE_KEY: cached} if cached else None)
    repo.updated = _now()
    append_system_event(
        db,
        trace_id=system_trace_id("repo", name),
        action="repo.updated",
        repo=name,
        actor=operator.id,
        payload={"diff": diff, "fields": sorted(diff)},
    )
    db.commit()
    return repo_detail(db, repo)


@router.post(
    "/repos/{name}/probe",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 503: _ERR},
    summary="Enqueue a probe run (proves the toolchain on the configured known-green scope)",
)
def probe_repo(name: str, operator: OperatorDep, db: DbDep, factory: SessionFactoryDep) -> RunOut:
    repo = get_repo_or_404(db, name)
    config = _config_of(repo)
    req = RunCreateRequest(repo=name, kind="probe")
    run = new_run(req, actor=operator.id)
    run.params_json = {**run.params_json, "probe": config.probe, "runner": config.runner}
    stored = require_jobs().enqueue(factory, run)
    fresh = db.get(Run, stored.id)
    return run_out(db, fresh if fresh is not None else stored)


def _profile_out(name: str, cached: Mapping[str, Any]) -> RepoProfile:
    profile = RepoChangeProfile.from_dict(dict(cached.get("profile") or {}))
    d = profile.to_dict()
    classes = sorted({c["capability_class"] for c in d["cells"]})
    sizes = [s for s in SIZE_TIER_NAMES if s in {c["size"] for c in d["cells"]}]
    return RepoProfile(
        repo=name,
        ref=d["ref"],
        n_commits=d["n_commits"],
        examined=d["examined"],
        skipped=d["skipped"],
        classes=classes,
        sizes=sizes,
        cells=[ProfileCell(**c) for c in d["cells"]],
        class_totals=d["class_totals"],
        size_totals=d["size_totals"],
        computed_at=str(cached.get("computed_at", "")),
    )


def compute_profile(repo: Repo, config: RepoConfig, *, log_n: int = 0) -> dict[str, Any]:
    """Walk the clone and return the cache entry ``{"computed_at", "profile"}``."""
    path = config.path or repo.clone_path
    if not path:
        raise ApiError(
            409,
            "no_clone_path",
            f"repo {repo.name!r} has no clone_path to profile",
            detail={"repo": repo.name},
        )
    git = GitRepo(Path(path))
    if not Path(path).is_dir() or not git.is_repo():
        raise ApiError(
            409,
            "clone_unavailable",
            f"clone_path for {repo.name!r} is not a git repository on this host",
            detail={"repo": repo.name},
        )
    try:
        profile = profile_repo(git, config, log_n=log_n)
    except GitError as exc:
        raise ApiError(
            409,
            "profile_failed",
            f"git failed while profiling {repo.name!r}: {redact(str(exc))}",
            detail={"repo": repo.name},
        ) from exc
    return {"computed_at": _now(), "profile": profile.to_dict()}


def cached_profile(repo: Repo) -> dict[str, Any] | None:
    """The stored profile cache entry, or ``None`` when the repo was never profiled."""
    cached = dict(repo.config_json or {}).get(PROFILE_KEY)
    return dict(cached) if isinstance(cached, Mapping) and cached.get("profile") else None


@router.get(
    "/repos/{name}/profile",
    response_model=RepoProfile,
    responses={401: _ERR, 404: _ERR, 409: _ERR},
    summary="Change profile (class x size histogram of recent history); cached; ?refresh=true recomputes",
)
def get_profile(
    name: str,
    viewer: ViewerDep,
    db: DbDep,
    refresh: bool = Query(default=False),
    log_n: int = Query(default=0, ge=0, le=100_000),
) -> RepoProfile:
    del viewer
    repo = get_repo_or_404(db, name)
    cached = cached_profile(repo)
    if cached is None or refresh:
        cached = compute_profile(repo, _config_of(repo), log_n=log_n)
        repo.config_json = {**dict(repo.config_json or {}), PROFILE_KEY: cached}
        db.commit()
    return _profile_out(name, cached)


@router.get(
    "/repos/{name}/tasks",
    response_model=Page[TaskSpecOut],
    responses={401: _ERR, 404: _ERR},
    summary="Mined TaskSpecs (pool, size, class, gold status)",
)
def list_tasks(
    name: str,
    viewer: ViewerDep,
    db: DbDep,
    page: PageDep,
    *,
    pool: str | None = Query(default=None, max_length=16),
    size: str | None = Query(default=None, max_length=4),
    capability_class: str | None = Query(default=None, max_length=64),
    gold_clean: bool | None = Query(default=None),
) -> Page[TaskSpecOut]:
    del viewer
    get_repo_or_404(db, name)
    q = select(Task).where(Task.repo == name)
    c = select(func.count(Task.task_id)).where(Task.repo == name)
    if pool:
        q, c = q.where(Task.pool == pool), c.where(Task.pool == pool)
    if size:
        q, c = q.where(Task.size == size), c.where(Task.size == size)
    if capability_class:
        q = q.where(Task.capability_class == capability_class)
        c = c.where(Task.capability_class == capability_class)
    if gold_clean is not None:
        q, c = q.where(Task.gold_clean.is_(gold_clean)), c.where(Task.gold_clean.is_(gold_clean))
    total = int(db.execute(c).scalar_one())
    tasks = list(
        db.execute(
            q.order_by(Task.authored.desc(), Task.task_id).limit(page.limit).offset(page.offset)
        ).scalars()
    )
    return Page[TaskSpecOut](
        items=[TaskSpecOut(**TaskSpec.from_dict(t.spec_json).to_dict()) for t in tasks],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


__all__ = [
    "PROFILE_KEY",
    "cached_profile",
    "compute_profile",
    "config_diff",
    "get_repo_or_404",
    "repo_detail",
    "repo_summary",
    "router",
]
