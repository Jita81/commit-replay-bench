"""GitHub App routes — install, list an installation's repositories, connect one.

Navigation
----------
What it is:   The HTTP surface of the enterprise connection: ``GET /github/app`` (is the app
              configured, where to install it, the installations on record), ``GET
              /github/setup`` (where GitHub sends the installer back — the installation is
              verified with the app's own credential, recorded, and the browser lands on
              the Connect screen), ``POST /github/installations/sync`` (refresh from GitHub),
              ``GET /github/installations/{id}/repositories`` (the picker, with a suggested
              config per repository) and ``POST /github/installations/{id}/connect``
              (register one of them as a crb repository, linked to the installation).
What it does: Makes "connect a repository" the org-level-install → repository-selection
              flow every comparable product uses (docs/GITHUB-APP.md), under the API's RBAC:
              a viewer may list, an operator may sync and connect. A connected repository is
              an ordinary ``Repo`` row whose ``config_json.github`` names the installation;
              the worker mints a token for that installation to clone (and, where the
              installation grants write, to deliver). No token is ever stored or returned.
How:          ``GitHubAppDep`` builds a :class:`GitHubApp` from settings (a 404
              ``github_app_not_configured`` when it is not); GitHub's refusals map to 502
              ``github_error``; the setup callback verifies ``installation_id`` via
              ``GET /app/installations/{id}`` before writing anything.
Layer:        server — docs/ARCHITECTURE.md#43-server
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/server/github_app.py (the client), src/crb/store/models.py
              (``GitHubInstallation``, ``Repo``), src/crb/server/routes/repos.py (the
              repository row and its ``repo.created`` event — reused here), src/crb/server/
              worker.py (clones with an installation token), ui/src/screens/Connect/
              GitHubConnectDialog.tsx (the picker), docs/API.md "GitHub App"
Tested by:    tests/test_server_github_app.py
Touch when:   the connect body grows a field (mirror it in the UI dialog); GHES needs a
              different discovery path.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from crb.server.auth import OperatorDep, ViewerDep
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.github_app import GitHubApp, GitHubAppError, Installation, suggest_config
from crb.server.routes.repos import _stored_config, _validated_config, repo_detail
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas import RepoDetail
from crb.server.settings import Settings
from crb.store.models import GitHubInstallation, Repo, _now

router = APIRouter(tags=["github"])
_ERR = {"model": ErrorEnvelope}
#: The key under ``config_json`` that links a repository to its installation.
GITHUB_KEY = "github"


def get_github_app(settings: SettingsDep) -> GitHubApp:
    """The configured app, or a 404 the UI renders as "an admin installs the GitHub App"."""
    if not settings.github.enabled:
        raise ApiError(
            404,
            "github_app_not_configured",
            "the GitHub App is not configured on this deployment (CRB_GITHUB__APP_ID and a private key — docs/GITHUB-APP.md)",
        )
    return GitHubApp(settings.github, httpx.Client(timeout=20.0))


GitHubAppDep = Annotated[GitHubApp, Depends(get_github_app)]


def _github_error(exc: GitHubAppError) -> ApiError:
    return ApiError(
        502,
        "github_error",
        f"GitHub refused: {exc.message}" if exc.status else exc.message,
        detail={"github_status": exc.status},
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InstallationOut(BaseModel):
    id: int
    account_login: str
    account_type: str
    repository_selection: str
    html_url: str
    suspended: bool
    permissions: dict[str, str]
    can_deliver: bool
    recorded_by: str = ""
    updated: str = ""


class GitHubAppOut(BaseModel):
    """``GET /github/app`` — configured or not, and what is on record."""

    configured: bool
    app_slug: str = ""
    install_url: str = ""
    api_url: str = ""
    installations: list[InstallationOut] = Field(default_factory=list)


class PickerRepoOut(BaseModel):
    full_name: str
    name: str
    html_url: str
    clone_url: str
    default_branch: str
    private: bool
    language: str
    archived: bool
    #: What the connect form pre-fills: product name, language, runner ("" = choose).
    suggested: dict[str, str]
    #: The crb repository already connected to this GitHub repository, if any.
    connected_as: str | None = None


class PickerPage(BaseModel):
    items: list[PickerRepoOut]
    total: int
    page: int
    per_page: int
    has_more: bool


class ConnectRequest(BaseModel):
    """``POST /github/installations/{id}/connect`` — one repository the installation may
    see, plus the fields the operator confirmed (the rest come from the suggestion)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(
        min_length=3, max_length=200, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=64)
    language: str | None = Field(default=None, max_length=32)
    runner: str | None = Field(default=None, max_length=16)
    src_prefix: str | None = Field(default=None, max_length=512)
    test_prefix: str | None = Field(default=None, max_length=512)
    ext: str | None = Field(default=None, max_length=32)
    test_mode: str | None = None
    test_suffix: str | None = Field(default=None, max_length=128)
    belt_scope: str | list[str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upsert(db: DbDep, inst: Installation, *, by: str) -> GitHubInstallation:
    row = db.get(GitHubInstallation, inst.id)
    if row is None:
        row = GitHubInstallation(installation_id=inst.id, recorded_by=by)
        db.add(row)
    row.account_login = inst.account_login
    row.account_type = inst.account_type
    row.repository_selection = inst.repository_selection
    row.html_url = inst.html_url
    row.permissions_json = dict(inst.permissions)
    row.suspended = inst.suspended
    row.updated = _now()
    return row


def _out(row: GitHubInstallation) -> InstallationOut:
    perms = {str(k): str(v) for k, v in dict(row.permissions_json or {}).items()}
    return InstallationOut(
        id=row.installation_id,
        account_login=row.account_login,
        account_type=row.account_type,
        repository_selection=row.repository_selection,
        html_url=row.html_url,
        suspended=row.suspended,
        permissions=perms,
        can_deliver=perms.get("contents") == "write" and perms.get("pull_requests") == "write",
        recorded_by=row.recorded_by,
        updated=row.updated,
    )


def _installation_or_404(db: DbDep, installation_id: int) -> GitHubInstallation:
    row = db.get(GitHubInstallation, installation_id)
    if row is None:
        raise ApiError(
            404,
            "not_found",
            f"installation {installation_id} is not on record — sync installations, or install the app",
        )
    return row


def _connected_names(db: DbDep) -> dict[str, str]:
    """``owner/name`` → crb repository name for every repository linked to GitHub."""
    out: dict[str, str] = {}
    for repo in db.execute(select(Repo)).scalars():
        link = dict(repo.config_json or {}).get(GITHUB_KEY) or {}
        full = str(link.get("full_name", ""))
        if full:
            out[full.lower()] = repo.name
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/github/app",
    response_model=GitHubAppOut,
    responses={401: _ERR},
    summary="Is the GitHub App configured, where to install it, the installations on record",
)
def get_app(viewer: ViewerDep, db: DbDep, settings: SettingsDep) -> GitHubAppOut:
    """Never 404s: an unconfigured app is a state the Connect screen renders."""
    del viewer
    g = settings.github
    rows = (
        db.execute(select(GitHubInstallation).order_by(GitHubInstallation.account_login))
        .scalars()
        .all()
    )
    return GitHubAppOut(
        configured=g.enabled,
        app_slug=g.app_slug,
        install_url=g.install_url if g.enabled else "",
        api_url=g.api_url if g.enabled else "",
        installations=[_out(r) for r in rows],
    )


@router.post(
    "/github/installations/sync",
    response_model=list[InstallationOut],
    responses={401: _ERR, 403: _ERR, 404: _ERR, 502: _ERR},
    summary="Refresh the installations on record from GitHub (operator)",
)
def sync_installations(
    operator: OperatorDep, db: DbDep, app: GitHubAppDep
) -> list[InstallationOut]:
    try:
        found = app.installations()
    except GitHubAppError as exc:
        raise _github_error(exc) from exc
    seen = {i.id for i in found}
    rows = [_upsert(db, i, by=operator.id) for i in found]
    # an installation GitHub no longer lists was uninstalled: keep the row, mark it
    for row in db.execute(select(GitHubInstallation)).scalars():
        if row.installation_id not in seen and not row.suspended:
            row.suspended = True
            row.updated = _now()
    db.commit()
    return [_out(r) for r in rows]


@router.get(
    "/github/setup",
    responses={401: _ERR, 403: _ERR, 404: _ERR, 502: _ERR},
    summary="Where GitHub sends the installer back (the app's Setup URL); records the installation and lands on Connect",
)
def setup_callback(
    operator: OperatorDep,
    db: DbDep,
    app: GitHubAppDep,
    installation_id: int = Query(ge=1),
    setup_action: str = Query(default="install", max_length=32),
) -> RedirectResponse:
    """``installation_id`` is untrusted until the app's own credential confirms it."""
    try:
        inst = app.installation(installation_id)
    except GitHubAppError as exc:
        raise _github_error(exc) from exc
    row = _upsert(db, inst, by=operator.id)
    append_system_event(
        db,
        trace_id=system_trace_id("github", str(inst.id)),
        action="github.installation.recorded",
        repo="",
        actor=operator.id,
        payload={
            "installation_id": inst.id,
            "account": inst.account_login,
            "selection": inst.repository_selection,
            "setup_action": setup_action,
            "can_deliver": inst.can_deliver,
        },
    )
    db.commit()
    return RedirectResponse(url=f"/connect?installation={row.installation_id}", status_code=303)


@router.get(
    "/github/installations/{installation_id}/repositories",
    response_model=PickerPage,
    responses={401: _ERR, 404: _ERR, 502: _ERR},
    summary="The repositories an installation may see, with a suggested config each (the picker)",
)
def list_repositories(  # noqa: PLR0917 — FastAPI dependencies + query params
    installation_id: int,
    viewer: ViewerDep,
    db: DbDep,
    app: GitHubAppDep,
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1, le=1000),
    per_page: int = Query(default=50, ge=1, le=100),
) -> PickerPage:
    del viewer
    _installation_or_404(db, installation_id)
    try:
        repos, total = app.repositories(installation_id, page=page, per_page=per_page)
    except GitHubAppError as exc:
        raise _github_error(exc) from exc
    connected = _connected_names(db)
    needle = q.strip().lower()
    items = [
        PickerRepoOut(
            **r.to_dict(),
            suggested=suggest_config(r),
            connected_as=connected.get(r.full_name.lower()),
        )
        for r in repos
        if not needle or needle in r.full_name.lower()
    ]
    return PickerPage(
        items=items, total=total, page=page, per_page=per_page, has_more=page * per_page < total
    )


@router.post(
    "/github/installations/{installation_id}/connect",
    response_model=RepoDetail,
    status_code=201,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 502: _ERR},
    summary="Register one of the installation's repositories as a crb repository, linked to the installation (operator)",
)
def connect_repository(
    installation_id: int, body: ConnectRequest, operator: OperatorDep, db: DbDep, app: GitHubAppDep
) -> RepoDetail:
    """The repository must be visible to the installation (GitHub answers 404 otherwise);
    the row's ``url`` is the https clone URL and ``config_json.github`` names the
    installation the worker mints a token for."""
    inst = _installation_or_404(db, installation_id)
    try:
        gh = app.repository(installation_id, body.full_name)
    except GitHubAppError as exc:
        if exc.status == 404:
            raise ApiError(
                404,
                "not_found",
                f"{body.full_name} is not visible to installation {installation_id} — select it in the app's repository access",
            ) from exc
        raise _github_error(exc) from exc
    if gh.archived:
        raise ApiError(422, "validation_error", f"{gh.full_name} is archived")
    already = _connected_names(db).get(gh.full_name.lower())
    if already:
        raise ApiError(
            409,
            "already_exists",
            f"{gh.full_name} is already connected as {already!r}",
            detail={"repo": already},
        )
    suggestion = suggest_config(gh)
    name = (body.name or suggestion["name"]).strip().lower()
    if db.get(Repo, name) is not None:
        raise ApiError(409, "already_exists", f"repo {name!r} already exists")
    language = (body.language or suggestion["language"]).strip()
    if not language:
        raise ApiError(
            422,
            "validation_error",
            f"GitHub reports no language for {gh.full_name} — choose one",
            detail={"suggested": suggestion},
        )
    raw: dict[str, Any] = {
        "language": language,
        "url": gh.clone_url,
        "runner": body.runner or suggestion["runner"],
    }
    for key in ("src_prefix", "test_prefix", "ext", "test_mode", "test_suffix", "belt_scope"):
        value = getattr(body, key)
        if value is not None:
            raw[key] = value
    try:
        config = _validated_config(name, raw)
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    link = {
        "installation_id": inst.installation_id,
        "full_name": gh.full_name,
        "default_branch": gh.default_branch,
        "html_url": gh.html_url,
        "private": gh.private,
    }
    repo = Repo(
        name=config.name,
        language=config.language.value,
        runner=config.runner,
        clone_path="",
        url=config.url,
        config_json=_stored_config(config, {GITHUB_KEY: link}),
        probe_status="unknown",
    )
    db.add(repo)
    append_system_event(
        db,
        trace_id=system_trace_id("repo", config.name),
        action="repo.created",
        repo=config.name,
        actor=operator.id,
        payload={"config": config.to_dict(), "github": link},
    )
    db.commit()
    return repo_detail(db, repo)


def installation_for_repo(settings: Settings, config_json: dict[str, Any]) -> int | None:
    """The installation a repository is linked to (``config_json.github.installation_id``),
    when the app is configured — what the worker asks before minting a token."""
    if not settings.github.enabled:
        return None
    link = dict(config_json or {}).get(GITHUB_KEY) or {}
    try:
        return int(link.get("installation_id") or 0) or None
    except (TypeError, ValueError):
        return None
