"""``/repos`` — configured repositories, their config history, probe, change profile, tasks.

A repo row is ``RepoConfig.to_dict()`` plus its probe state. Every config change
is validated through :meth:`crb.core.spec.RepoConfig.from_dict` (an invalid config
cannot be stored) and recorded as a ``system/repo.updated`` event whose payload is
the REDACTED field diff — the audit trail for "who changed the belt scope" lives in
the append-only events table, not in a mutable column. ``GET /repos/{name}/events``
serves that trail (the repo's system trace: ``repo.created`` then every
``repo.updated``), newest first, so the UI's Configuration tab can show who changed
what without reading the database.

The change profile (:func:`crb.core.capability.profile_repo`) walks the clone's
git history; it is cached in ``config_json["profile"]`` with a timestamp and
recomputed on ``?refresh=true``. It is measurement INPUT (what the repo's work
looks like), never a verdict.

Navigation
----------
What it is:   The ``/repos`` route module — register, read, update, probe and profile a
              repository; list its tasks and its configuration audit trail.
What it does: Validates every config through ``RepoConfig.from_dict`` (an invalid config is
              never stored), records each change as a ``system/repo.updated`` event
              carrying the redacted field diff, enqueues a probe run, computes and caches
              the change profile (measurement INPUT, never a verdict), and pages mined
              tasks; confines a registered ``clone_path`` to ``<home>/repos``
              (``confine_clone_path`` — elsewhere is admin-only and recorded, a symbolic-link
              escape is refused; ``confined_clone_path`` re-applies the link rule where the
              path is used — the profile walk here and the worker's ``_load_repo`` — and
              hands back the resolved path git then opens). Also the
              home of ``get_repo_or_404`` and ``cached_profile`` that other route modules
              import.
How:          ``_validated_config`` → ``Repo`` row + ``append_system_event`` on the repo's
              system trace; ``compute_profile`` walks the clone with ``profile_repo`` and
              stores the result under ``config_json["profile"]``.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/core/spec.py (``RepoConfig`` — the shape stored in ``config_json``),
              src/crb/core/capability.py (``profile_repo`` / ``RepoChangeProfile``),
              src/crb/server/routes/runs.py (``new_run`` / ``append_system_event`` /
              ``system_trace_id``), src/crb/server/schemas.py (``RepoCreateRequest`` and the
              ``Repo*`` shapes — ``RepoSummary.github_full_name`` is read off the row here),
              src/crb/store/models.py (``Repo``, ``Task``), src/crb/server/routes/github.py
              (connect and link reuse ``get_repo_or_404`` / ``_config_of`` /
              ``_stored_config`` / ``PRESERVED_KEYS`` and write the ``github`` key this
              module preserves), src/crb/server/worker.py (``confined_clone_path`` at use),
              docs/OPERATOR.md#20-configuring-a-repository-from-the-ui,
              ui/src/screens/Repos
Tested by:    tests/test_server_routes_repos.py, tests/test_server_routes_w3b.py,
              tests/test_mcp_server.py (the MCP write tools ride these routes),
              tests/test_worker_clone.py (the rule at use, in the worker)
Touch when:   THIS is the route a new repository goes through — but adding one is
              configuration (docs/OPERATOR.md#2-configure-a-repository), not code; edit
              this file only when ``RepoConfig`` gains a field (the request schema, the UI
              form and docs/API.md#repos change with it).
"""

from __future__ import annotations

import datetime as _dt
import os
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
from crb.server.auth import OperatorDep, ViewerDep, require_role_now
from crb.server.deps import (
    ApiError,
    DbDep,
    ErrorEnvelope,
    Principal,
    SessionFactoryDep,
    SettingsDep,
)
from crb.server.routes.runs import (
    append_system_event,
    event_to_dict,
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
    StepEventOut,
    TaskSpecOut,
)
from crb.server.settings import ROLE_RANK
from crb.store.models import Event, Repo, Run, Task

router = APIRouter(tags=["repos"])
_ERR = {"model": ErrorEnvelope}

PROFILE_KEY = "profile"
#: ``config_json`` keys that are NOT repository config and survive every config update:
#: the cached change profile, the GitHub App link (src/crb/server/routes/github.py) and the
#: intake listener's switch (src/crb/server/intake.py) — editing a repository's test command
#: must never silently switch its listener off.
PRESERVED_KEYS: tuple[str, ...] = (PROFILE_KEY, "github", "intake")
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
    """The row's ``RepoConfig`` (the cached profile is not part of the config)."""
    raw = {k: v for k, v in dict(repo.config_json or {}).items() if k not in PRESERVED_KEYS}
    raw.setdefault("path", repo.clone_path)
    raw.setdefault("url", repo.url)
    return _validated_config(repo.name, raw)


def _stored_config(config: RepoConfig, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What goes into ``config_json``: the config dict plus any cache entry to keep."""
    d = config.to_dict()
    if extra:
        d.update(extra)
    return d


def config_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{field: {"from": …, "to": …}}`` over the keys that changed (profile cache excluded)."""
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(set(old) | set(new)):
        if key in PRESERVED_KEYS:
            continue
        if old.get(key) != new.get(key):
            out[key] = {"from": old.get(key), "to": new.get(key)}
    return out


# ---------------------------------------------------------------------------
# Where a clone may live (D2)
# ---------------------------------------------------------------------------

#: The directory under ``home`` a registered ``clone_path`` must resolve inside — the one the
#: worker clones into (src/crb/server/worker.py ``_load_repo``).
CLONE_ROOT = "repos"


def clone_root(home: str | Path) -> Path:
    """``<home>/repos``, absolute and with every symlink resolved."""
    return Path(os.path.abspath(Path(home) / CLONE_ROOT)).resolve()


def clone_path_escapes(path: str | Path, home: str | Path) -> bool:
    """Whether ``path`` is WRITTEN under :func:`clone_root` but RESOLVES outside it — a
    symbolic link on the way out. Checked where a clone path is written
    (:func:`confine_clone_path`) AND where it is used (the profile walk here, the worker's
    ``_load_repo``): a path that did not exist at registration can gain a link later, for
    example from another repository's clone, so a check at write time alone is not enough."""
    raw = Path(path)
    written_root = Path(os.path.abspath(Path(home) / CLONE_ROOT))
    root = clone_root(home)
    written = Path(os.path.normpath(raw))
    resolved = raw.resolve()
    looks_inside = any(written.is_relative_to(r) and written != r for r in (written_root, root))
    return looks_inside and not (resolved.is_relative_to(root) and resolved != root)


def confined_clone_path(
    path: str | Path, home: str | Path, *, inside_root: bool = False
) -> Path | None:
    """The clone-path rule where a stored path is USED — the one way the worker and the
    profile walk turn a clone path into the path git opens. ``path`` is resolved once and
    ``None`` returned (refused) when it is written under :func:`clone_root` but resolves
    outside it (:func:`clone_path_escapes`). With ``inside_root`` (the worker's own clone
    destination, a directory it creates and then persists as the clone) the rule is
    IDENTITY, not containment: the resolved path must be exactly ``<root>/<the written
    name>``, so any symbolic link at or below the root on the way — to somewhere outside,
    to another repository's clone inside, dangling, or chained — is refused (PR #52
    review: a link to a clone inside the root passed a containment check and was adopted).
    Otherwise the RESOLVED path is returned, and the caller opens THAT, so the path git
    works in is the path that was checked, not whatever the written path names by the time
    git reads it. tests/test_worker_clone.py holds every use site to this function."""
    if clone_path_escapes(path, home):
        return None
    resolved = Path(path).resolve()
    if inside_root:
        root = clone_root(home)
        written = Path(os.path.normpath(Path(os.path.abspath(path))))
        bases = (Path(os.path.abspath(Path(home) / CLONE_ROOT)), root)
        names = [written.relative_to(b) for b in bases if written.is_relative_to(b)]
        if not names or names[0] == Path(".") or resolved != root / names[0]:
            return None
    return resolved


def _escapes_error(root: Path) -> ApiError:
    return ApiError(
        422,
        "clone_path_escapes",
        "clone_path is under the repositories directory but resolves outside it "
        "(a symbolic link); register the real location instead",
        detail={"field": "clone_path", "clone_root": str(root)},
    )


def confine_clone_path(path: str, home: str | Path, principal: Principal) -> Path | None:
    """The clone-path rule every registration and every move of a clone goes through.

    A ``clone_path`` names a directory on the API host that every later run reads, builds
    in and profiles, so it resolves inside :func:`clone_root`. Returns ``None`` for such a
    path. A path outside the root is an admin's decision: for an admin the resolved path is
    returned (the caller records ``repo.clone_path.outside_home``), anyone else gets 403
    ``clone_path_outside_home`` — through the API and the MCP write tools alike, which ride
    this route. A path WRITTEN under the root that RESOLVES outside it (a symlink escape) is
    refused for every role with 422 ``clone_path_escapes``: nobody may register one place
    and read another. A relative path is refused (422 ``clone_path_not_absolute``): its
    meaning would depend on which process's working directory read it.
    """
    raw = Path(path)
    if not raw.is_absolute():
        raise ApiError(
            422,
            "clone_path_not_absolute",
            "clone_path must be an absolute path on the server",
            detail={"field": "clone_path"},
        )
    root = clone_root(home)
    if clone_path_escapes(raw, home):
        raise _escapes_error(root)
    resolved = raw.resolve()
    if resolved.is_relative_to(root) and resolved != root:
        return None
    if ROLE_RANK.get(principal.role, -1) < ROLE_RANK["admin"]:
        raise ApiError(
            403,
            "clone_path_outside_home",
            f"clone_path must be inside {root}; only an admin may register a clone elsewhere",
            detail={"field": "clone_path", "clone_root": str(root), "required": "admin"},
        )
    return resolved


def _record_outside_home(
    db: Session, *, name: str, actor: str, path: str, resolved: Path, home: str | Path
) -> None:
    """The audit event for an admin-registered clone outside the root, in the caller's
    transaction."""
    append_system_event(
        db,
        trace_id=system_trace_id("repo", name),
        action="repo.clone_path.outside_home",
        repo=name,
        actor=actor,
        payload={"path": path, "resolved": str(resolved), "clone_root": str(clone_root(home))},
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _task_counts(session: Session, name: str) -> RepoTaskCounts:
    """Task totals by pool and gold status, in one grouped query."""
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
    """The repo's newest run (optionally of one kind), or ``None``."""
    q = select(Run).where(Run.repo == name)
    if kind:
        q = q.where(Run.kind == kind)
    return session.execute(
        q.order_by(Run.created.desc(), Run.id.desc()).limit(1)
    ).scalar_one_or_none()


def _probe(repo: Repo, probe_run: Run | None) -> RepoProbe:
    """The probe state: the worker's recorded verdict wins; else derived from the latest
    probe run's status; ``not_probed`` when there has never been one."""
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
    """The list-row view: identity, probe, task counts, last run."""
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
        github_full_name=repo.github_full_name,
    )


def repo_detail(session: Session, repo: Repo) -> RepoDetail:
    """The summary plus the validated config and when the profile was last computed."""
    summary = repo_summary(session, repo)
    cached = dict(repo.config_json or {}).get(PROFILE_KEY) or {}
    return RepoDetail(
        **summary.model_dump(),
        config=_config_of(repo).to_dict(),
        profile_computed_at=str(cached.get("computed_at")) if cached else None,
    )


def get_repo_or_404(session: Session, name: str) -> Repo:
    """The repo row, or 404 — the guard every repo-scoped route starts with."""
    repo = session.get(Repo, name)
    if repo is None:
        raise ApiError(404, "not_found", f"no repo {name!r}")
    return repo


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/repos", response_model=Page[RepoSummary], responses={401: _ERR})
def list_repos(viewer: ViewerDep, db: DbDep, page: PageDep) -> Page[RepoSummary]:
    """Every configured repository, by name."""
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
def create_repo(
    body: RepoCreateRequest, operator: OperatorDep, db: DbDep, settings: SettingsDep
) -> RepoDetail:
    """Register a repository; the full config is the ``repo.created`` event's payload. A
    ``clone_path`` goes through :func:`confine_clone_path` first."""
    if db.get(Repo, body.name) is not None:
        raise ApiError(409, "already_exists", f"repo {body.name!r} already exists")
    config = _validated_config(body.name, body.config_updates())
    outside = confine_clone_path(config.path, settings.home, operator) if config.path else None
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
    if outside is not None:
        _record_outside_home(
            db,
            name=config.name,
            actor=operator.id,
            path=config.path,
            resolved=outside,
            home=settings.home,
        )
    db.commit()
    return repo_detail(db, repo)


@router.get("/repos/{name}", response_model=RepoDetail, responses={401: _ERR, 404: _ERR})
def get_repo(name: str, viewer: ViewerDep, db: DbDep) -> RepoDetail:
    """One repository with its config."""
    del viewer
    return repo_detail(db, get_repo_or_404(db, name))


@router.put(
    "/repos/{name}",
    response_model=RepoDetail,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR},
    summary="Update the config (partial); the redacted diff is appended to the events table",
)
def update_repo(
    name: str, body: RepoUpdateRequest, operator: OperatorDep, db: DbDep, settings: SettingsDep
) -> RepoDetail:
    """Partial update: merge, re-validate, store, and append the field diff as an event.
    The cached profile survives a config change (it is history, not config). A MOVED
    ``clone_path`` goes through :func:`confine_clone_path`; an unchanged one (a clone an
    admin registered outside the root) does not block an edit of anything else."""
    repo = get_repo_or_404(db, name)
    old = _config_of(repo).to_dict()
    merged = {**old, **body.config_updates()}
    config = _validated_config(name, merged)
    moved = bool(config.path) and config.path != old.get("path")
    outside = confine_clone_path(config.path, settings.home, operator) if moved else None
    new = config.to_dict()
    diff = config_diff(old, new)
    kept = {k: v for k, v in dict(repo.config_json or {}).items() if k in PRESERVED_KEYS and v}
    # the GitHub link belongs to the URL it was made for: a changed URL drops it, or the
    # worker would mint the installation's token and hand it to whatever host the new URL
    # names (CWE-201). The operator re-connects from the picker to link again.
    unlinked = "github" in kept and config.url != (repo.url or "")
    if unlinked:
        kept.pop("github", None)
        repo.github_full_name = None
    repo.language = config.language.value
    repo.runner = config.runner
    repo.clone_path = config.path
    repo.url = config.url
    repo.config_json = _stored_config(config, kept or None)
    repo.updated = _now()
    append_system_event(
        db,
        trace_id=system_trace_id("repo", name),
        action="repo.updated",
        repo=name,
        actor=operator.id,
        payload={"diff": diff, "fields": sorted(diff), "github_unlinked": unlinked},
    )
    if outside is not None:
        _record_outside_home(
            db, name=name, actor=operator.id, path=config.path, resolved=outside, home=settings.home
        )
    db.commit()
    return repo_detail(db, repo)


@router.get(
    "/repos/{name}/events",
    response_model=Page[StepEventOut],
    responses={401: _ERR, 404: _ERR},
    summary="Config audit trail: the repo's system events (repo.created, repo.updated diffs), newest first",
)
def list_repo_events(name: str, viewer: ViewerDep, db: DbDep, page: PageDep) -> Page[StepEventOut]:
    """The repo's own system trace (``sha256("repo:<name>")[:32]``) as stored.

    Payloads are the redacted diffs :func:`update_repo` appended — served verbatim,
    never recomputed, so what an auditor reads is what was written at the time.
    """
    del viewer
    get_repo_or_404(db, name)
    trace = system_trace_id("repo", name)
    total = int(
        db.execute(select(func.count(Event.id)).where(Event.trace_id == trace)).scalar_one()
    )
    items = list(
        db.execute(
            select(Event)
            .where(Event.trace_id == trace)
            .order_by(Event.seq.desc(), Event.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        ).scalars()
    )
    return Page[StepEventOut](
        items=[StepEventOut(**event_to_dict(m)) for m in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/repos/{name}/probe",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 503: _ERR},
    summary="Enqueue a probe run (proves the toolchain on the configured known-green scope)",
)
def probe_repo(name: str, operator: OperatorDep, db: DbDep, factory: SessionFactoryDep) -> RunOut:
    """Enqueue a ``probe`` run carrying the config's probe scope and runner."""
    repo = get_repo_or_404(db, name)
    config = _config_of(repo)
    req = RunCreateRequest(repo=name, kind="probe")
    run = new_run(req, actor=operator.id)
    run.params_json = {**run.params_json, "probe": config.probe, "runner": config.runner}
    stored = require_jobs().enqueue(factory, run)
    fresh = db.get(Run, stored.id)
    return run_out(db, fresh if fresh is not None else stored)


def _profile_out(name: str, cached: Mapping[str, Any]) -> RepoProfile:
    """The cache entry as the API serves it (classes sorted, sizes in tier order)."""
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


def compute_profile(
    repo: Repo, config: RepoConfig, *, home: str | Path, log_n: int = 0
) -> dict[str, Any]:
    """Walk the clone and return the cache entry ``{"computed_at", "profile"}``. The
    clone-path rule is applied again here, at use: a path that gained a symbolic link off
    the repositories directory since it was registered is refused, never walked."""
    path = config.path or repo.clone_path
    if not path:
        raise ApiError(
            409,
            "no_clone_path",
            f"repo {repo.name!r} has no clone_path to profile",
            detail={"repo": repo.name},
        )
    opened = confined_clone_path(path, home)
    if opened is None:
        raise _escapes_error(clone_root(home))
    git = GitRepo(opened)
    if not opened.is_dir() or not git.is_repo():
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
    responses={401: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
    summary="Change profile (class x size histogram of recent history); cached; ?refresh=true recomputes",
)
def get_profile(
    name: str,
    viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    *,
    refresh: bool = Query(default=False),
    log_n: int = Query(default=0, ge=0, le=100_000),
) -> RepoProfile:
    # Reading the cached histogram is a viewer action; forcing a recompute is a git walk
    # plus a write to the config row, so ``?refresh=true`` needs operator (CodeRabbit on
    # PR #4, 2026-09-15 — a viewer could otherwise hammer the walk).
    if refresh:
        require_role_now(viewer, "operator")
    repo = get_repo_or_404(db, name)
    cached = cached_profile(repo)
    # Computed on demand (a git walk) and cached in the config row; only ?refresh redoes it.
    if cached is None or refresh:
        cached = compute_profile(repo, _config_of(repo), home=settings.home, log_n=log_n)
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
