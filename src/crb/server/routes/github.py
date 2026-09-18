"""GitHub App routes — install, list an installation's repositories, connect or link one.

Navigation
----------
What it is:   The HTTP surface of the enterprise connection: ``GET /github/app`` (is the app
              configured, where to install it, the installations on record), ``GET
              /github/setup`` (where GitHub sends the installer back — the installation is
              verified with the app's own credential, recorded, and the browser lands on
              the Connect screen), ``POST /github/installations/sync`` (refresh from GitHub),
              ``GET /github/installations/{id}/repositories`` (the picker, with a suggested
              config per repository), ``POST /github/installations/{id}/connect``
              (register one of them as a NEW crb repository, linked to the installation)
              and ``POST /repos/{name}/github-link`` (attach one of them to an EXISTING crb
              repository — it keeps its name and its evidence; its URL becomes the clone URL).
What it does: Makes "connect a repository" the org-level-install → repository-selection
              flow every comparable product uses (docs/GITHUB-APP.md), under the API's RBAC:
              a viewer may list, an operator may sync, connect and link. A connected repository
              is an ordinary ``Repo`` row whose ``config_json.github`` names the installation;
              the worker mints a token for that installation to clone (and, where the
              installation grants write, to deliver). No token is ever stored or returned.
              A link is a visible seam on the events table (``repo.github_linked`` with the
              URL before and after), never a silent edit.
How:          ``GitHubAppDep`` builds a :class:`GitHubApp` from settings (a 404
              ``github_app_not_configured`` when it is not); GitHub's refusals map to 502
              ``github_error``; the setup callback verifies ``installation_id`` via
              ``GET /app/installations/{id}`` before writing anything; connect and link
              share ``_visible_repository`` / ``_link_of`` and both let the unique index on
              ``repos.github_full_name`` decide a race (409, at autoflush or at commit).
Layer:        server — docs/ARCHITECTURE.md#43-server
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/server/github_app.py (the client), src/crb/store/models.py
              (``GitHubInstallation``, ``Repo``), src/crb/server/routes/repos.py (the
              repository row, ``get_repo_or_404`` / ``_config_of`` / ``PRESERVED_KEYS`` and
              its ``repo.created`` event — reused here), src/crb/server/worker.py (clones
              with an installation token; ``_github_host_ok`` is the CWE-201 rule a link
              relies on), ui/src/screens/Connect/GitHubConnectDialog.tsx (the picker and
              its two ways), docs/API.md "GitHub App", docs/GITHUB-APP.md
Tested by:    tests/test_server_github_app.py
Touch when:   the connect or link body grows a field (mirror it in the UI dialog); GHES
              needs a different discovery path.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crb.server.auth import (
    GITHUB_SETUP_COOKIE,
    OperatorDep,
    ViewerDep,
    clear_github_setup_cookie,
    issue_github_setup_state,
    new_github_setup_nonce,
    set_github_setup_cookie,
    verify_github_setup_state,
)
from crb.server.deps import ApiError, DbDep, ErrorEnvelope, SettingsDep
from crb.server.github_app import (
    GitHubApp,
    GitHubAppError,
    Installation,
    InstallationRepo,
    suggest_config,
)
from crb.server.routes.repos import (
    PRESERVED_KEYS,
    _config_of,
    _stored_config,
    _validated_config,
    get_repo_or_404,
    repo_detail,
)
from crb.server.routes.runs import append_system_event, system_trace_id
from crb.server.schemas import RepoDetail
from crb.server.settings import Settings
from crb.store.models import GitHubInstallation, Repo, _now

router = APIRouter(tags=["github"])
_ERR = {"model": ErrorEnvelope}
#: The key under ``config_json`` that links a repository to its installation.
GITHUB_KEY = "github"


def get_github_app(settings: SettingsDep) -> Iterator[GitHubApp]:
    """The configured app, or a 404 the UI renders as "an admin installs the GitHub App".
    A yielding dependency: the request's ``httpx.Client`` is closed when the request ends."""
    if not settings.github.enabled:
        raise ApiError(
            404,
            "github_app_not_configured",
            "the GitHub App is not configured on this deployment (CRB_GITHUB__APP_ID and a private key — docs/GITHUB-APP.md)",
        )
    client = httpx.Client(timeout=20.0)
    try:
        yield GitHubApp(settings.github, client)
    finally:
        client.close()


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


class LinkRequest(BaseModel):
    """``POST /repos/{name}/github-link`` — the installation and one repository it may see,
    to attach to a crb repository that already exists (its name, and so its ledger rows,
    stay)."""

    model_config = ConfigDict(extra="forbid")

    installation_id: int = Field(ge=1)
    full_name: str = Field(
        min_length=3, max_length=200, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
    )


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


def _visible_repository(app: GitHubApp, installation_id: int, full_name: str) -> InstallationRepo:
    """The repository as the installation sees it — GitHub's 404 becomes the API's words
    (select it in the app's repository access); an archived one is a 422. Shared by connect
    and link so both refuse the same repositories the same way."""
    try:
        gh = app.repository(installation_id, full_name)
    except GitHubAppError as exc:
        if exc.status == 404:
            raise ApiError(
                404,
                "not_found",
                f"{full_name} is not visible to installation {installation_id} — select it in the app's repository access",
            ) from exc
        raise _github_error(exc) from exc
    if gh.archived:
        raise ApiError(422, "validation_error", f"{gh.full_name} is archived")
    return gh


def _link_of(inst: GitHubInstallation, gh: InstallationRepo) -> dict[str, Any]:
    """What ``config_json.github`` holds: the installation the worker mints a token for and
    the repository facts the UI shows. Never a token."""
    return {
        "installation_id": inst.installation_id,
        "full_name": gh.full_name,
        "default_branch": gh.default_branch,
        "html_url": gh.html_url,
        "private": gh.private,
    }


def _connected_names(db: DbDep) -> dict[str, str]:
    """``owner/name`` (lower-cased) → crb repository name for every repository linked to
    GitHub — read from the constrained column (revision 0006), the same fact the unique
    index enforces at commit."""
    rows = db.execute(
        select(Repo.github_full_name, Repo.name).where(Repo.github_full_name.is_not(None))
    ).all()
    return {str(full): str(name) for full, name in rows}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/github/app",
    response_model=GitHubAppOut,
    responses={401: _ERR},
    summary="Is the GitHub App configured, where to install it, the installations on record",
)
def get_app(
    viewer: ViewerDep, db: DbDep, settings: SettingsDep, response: Response
) -> GitHubAppOut:
    """Never 404s: an unconfigured app is a state the Connect screen renders. The install
    link carries a signed ``state`` bound to this principal AND to this browser (a nonce
    the response also sets as an httponly cookie; thirty minutes) so the setup callback can
    tell an install this person started, here, from a link someone else made them open or
    a stale tab in another session — an operator's link writes; a viewer's is plain (a
    viewer cannot complete it)."""
    g = settings.github
    rows = (
        db.execute(select(GitHubInstallation).order_by(GitHubInstallation.account_login))
        .scalars()
        .all()
    )
    install_url = g.install_url if g.enabled else ""
    if install_url and viewer.role in ("operator", "approver", "admin"):
        nonce = new_github_setup_nonce()
        set_github_setup_cookie(response, settings, nonce)
        install_url = f"{install_url}?state={issue_github_setup_state(settings, viewer.id, nonce)}"
    return GitHubAppOut(
        configured=g.enabled,
        app_slug=g.app_slug,
        install_url=install_url,
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
def setup_callback(  # noqa: PLR0917 — FastAPI dependencies + query params
    request: Request,
    operator: OperatorDep,
    db: DbDep,
    app: GitHubAppDep,
    settings: SettingsDep,
    installation_id: int = Query(ge=1),
    setup_action: str = Query(default="install", max_length=32),
    state: str = Query(default="", max_length=512),
) -> RedirectResponse:
    """``installation_id`` is untrusted until the app's own credential confirms it; the
    write is made only when ``state`` proves this operator started the install, in this
    browser, from a link this deployment minted — the state's nonce must match the
    ``crb_github_setup`` cookie, which is consumed by the write (CWE-352). Without that
    proof nothing is recorded: the callback lands on Connect with ``unverified=1`` and the
    operator records the installation with the CSRF-protected sync, which verifies it the
    same way."""
    try:
        inst = app.installation(installation_id)
    except GitHubAppError as exc:
        raise _github_error(exc) from exc
    nonce = request.cookies.get(GITHUB_SETUP_COOKIE)
    if not verify_github_setup_state(settings, state, operator.id, nonce):
        return RedirectResponse(
            url=f"/connect?installation={inst.id}&unverified=1", status_code=303
        )
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
    out = RedirectResponse(url=f"/connect?installation={row.installation_id}", status_code=303)
    clear_github_setup_cookie(out, settings)  # one state, one write
    return out


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
    gh = _visible_repository(app, installation_id, body.full_name)
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
    link = _link_of(inst, gh)
    repo = Repo(
        name=config.name,
        language=config.language.value,
        runner=config.runner,
        clone_path="",
        url=config.url,
        config_json=_stored_config(config, {GITHUB_KEY: link}),
        github_full_name=gh.full_name.lower(),
        probe_status="unknown",
    )
    db.add(repo)
    try:
        # the event's seq query autoflushes the row: the index may refuse here or at commit
        append_system_event(
            db,
            trace_id=system_trace_id("repo", config.name),
            action="repo.created",
            repo=config.name,
            actor=operator.id,
            payload={"config": config.to_dict(), "github": link},
        )
        db.commit()
    except IntegrityError as exc:
        # two operators connected the same repository at once: the unique index on
        # ``repos.github_full_name`` (or the name's primary key) decided, not the scan above
        db.rollback()
        raise ApiError(
            409,
            "already_exists",
            f"{gh.full_name} was connected by another request at the same time (or the name {name!r} is taken)",
        ) from exc
    return repo_detail(db, repo)


@router.post(
    "/repos/{name}/github-link",
    response_model=RepoDetail,
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR, 502: _ERR},
    summary="Link an EXISTING crb repository to one of an installation's repositories (operator)",
)
def link_repository(
    name: str, body: LinkRequest, operator: OperatorDep, db: DbDep, app: GitHubAppDep
) -> RepoDetail:
    """The row keeps its name — and with it every ledger row, map and sign-off made under
    it: this is the path for a repository measured before the app existed, or whose history
    now lives on a fork (``cobra`` → ``Jita81/cobra``). What changes: ``url`` becomes the
    https clone URL, ``github_full_name`` the constrained identity, ``config_json.github``
    the same link connect writes. Language, runner, layout and belt scope are NOT touched —
    the measured config stands; the operator edits it separately if the fork differs — and
    an existing clone is kept (same history). Re-linking the row to another repository
    replaces the link (the operator's explicit act) and the event records the previous
    ``full_name``. The link is a visible seam on the events table
    (``repo.github_linked`` with ``url_before`` / ``url_after``), never a silent edit.

    CWE-201 holds as for connect: the worker sends an installation token only to an https
    remote on the app's own host (``Worker._github_host_ok``), whatever the link says, and
    a later ``PUT /repos/{name}`` that changes the URL drops the link."""
    repo = get_repo_or_404(db, name)
    inst = _installation_or_404(db, body.installation_id)
    gh = _visible_repository(app, body.installation_id, body.full_name)
    already = _connected_names(db).get(gh.full_name.lower())
    if already and already != repo.name:
        raise ApiError(
            409,
            "already_exists",
            f"{gh.full_name} is already connected as {already!r}",
            detail={"repo": already},
        )
    link = _link_of(inst, gh)
    previous = dict(dict(repo.config_json or {}).get(GITHUB_KEY) or {})
    url_before = str(repo.url or "")
    # the config re-validates with the new URL (the policy check every stored config passes);
    # the cached profile is history and survives, the old link is replaced
    config = _validated_config(name, {**_config_of(repo).to_dict(), "url": gh.clone_url})
    kept = {k: v for k, v in dict(repo.config_json or {}).items() if k in PRESERVED_KEYS and v}
    kept[GITHUB_KEY] = link
    repo.url = config.url
    repo.config_json = _stored_config(config, kept)
    repo.github_full_name = gh.full_name.lower()
    repo.updated = _now()
    try:
        # the event's seq query autoflushes the row: the index may refuse here or at commit
        append_system_event(
            db,
            trace_id=system_trace_id("repo", name),
            action="repo.github_linked",
            repo=name,
            actor=operator.id,
            payload={
                "github": link,
                "url_before": url_before,
                "url_after": config.url,
                "previous_full_name": previous.get("full_name") or None,
            },
        )
        db.commit()
    except IntegrityError as exc:
        # two operators linked the same repository to two rows at once: the unique index
        # on ``repos.github_full_name`` decided, not the scan above
        db.rollback()
        raise ApiError(
            409,
            "already_exists",
            f"{gh.full_name} was connected by another request at the same time",
        ) from exc
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
