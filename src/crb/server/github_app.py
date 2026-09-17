"""The GitHub App client — the enterprise connection, federated.

Navigation
----------
What it is:   ``GitHubApp`` — the product acting as the GitHub App an organisation installed:
              an app JWT (RS256, ten minutes), the app's installations, one installation's
              repositories, and short-lived **installation tokens** (one hour, minted on
              demand, cached until five minutes before expiry, never persisted).
What it does: Replaces personal access tokens with the pattern every comparable product uses
              (docs/reviews/2026-09-17-enterprise-front-end.md §3): an org admin installs the
              app on *selected* repositories; the product clones with an installation token
              whose scopes are the installation's (``Contents: read`` for measurement) and —
              only where the installation grants it — delivers with the same token
              (``Contents: write`` + ``Pull requests: write``). Tokens are never written to
              a row, an event, a log or a git config: they live in this process's cache and
              travel as a one-shot ``Authorization`` header.
How:          ``authlib.jose.jwt`` signs the app JWT with the private key from
              ``GitHubAppSettings``; ``httpx.Client`` (injectable — tests pass a
              ``MockTransport``) calls ``/app/installations``, ``/app/installations/{id}``,
              ``/app/installations/{id}/access_tokens`` and ``/installation/repositories``.
              Every failure is a ``GitHubAppError`` carrying the status and GitHub's message
              (redacted); the API maps it to 502 ``github_error``.
Layer:        server — docs/ARCHITECTURE.md#43-server
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/server/settings.py (``GitHubAppSettings``), src/crb/server/routes/github.py
              (the routes), src/crb/server/worker.py (clone with an installation token; the
              delivery credentials provider), src/crb/factory/delivery.py (``GitCredentials``
              carries the token to ``git push`` and the pulls API), docs/GITHUB-APP.md
Tested by:    tests/test_server_github_app.py
Touch when:   GitHub changes the app-auth flow; GHES needs a different path prefix (``api_url``
              already covers ``https://ghes.example/api/v3``).
Claims:       none — a transport.
"""

from __future__ import annotations

import datetime as _dt
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.jose import jwt

from crb.core.redact import redact
from crb.server.settings import GitHubAppSettings

#: GitHub caps an app JWT at ten minutes; nine keeps clock skew inside the window.
JWT_TTL_S = 9 * 60
#: A cached installation token is refreshed this long before GitHub's ``expires_at``.
TOKEN_REFRESH_MARGIN_S = 5 * 60
API_VERSION = "2022-11-28"


class GitHubAppError(RuntimeError):
    """GitHub refused or was unreachable: ``status`` (0 when unreachable) and a redacted message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(
            f"GitHub {status}: {message}" if status else f"GitHub unreachable: {message}"
        )
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Installation:
    """One installation of the app: the account it lives on and what it may see."""

    id: int
    account_login: str
    account_type: str
    repository_selection: str  # "all" | "selected"
    html_url: str
    suspended: bool
    #: Permission → level, as GitHub reports it (``contents: read`` …); what delivery needs.
    permissions: dict[str, str]

    @classmethod
    def from_api(cls, d: Mapping[str, Any]) -> Installation:
        acct = d.get("account") or {}
        return cls(
            id=int(d["id"]),
            account_login=str(acct.get("login", "")),
            account_type=str(acct.get("type", "")),
            repository_selection=str(d.get("repository_selection", "")),
            html_url=str(d.get("html_url", "")),
            suspended=bool(d.get("suspended_at")),
            permissions={str(k): str(v) for k, v in (d.get("permissions") or {}).items()},
        )

    @property
    def can_deliver(self) -> bool:
        """Delivery needs to push a branch and open a pull request."""
        return (
            self.permissions.get("contents") == "write"
            and self.permissions.get("pull_requests") == "write"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_login": self.account_login,
            "account_type": self.account_type,
            "repository_selection": self.repository_selection,
            "html_url": self.html_url,
            "suspended": self.suspended,
            "permissions": dict(self.permissions),
            "can_deliver": self.can_deliver,
        }


@dataclass(frozen=True)
class InstallationRepo:
    """One repository the installation may see — what the picker lists."""

    full_name: str
    name: str
    html_url: str
    clone_url: str
    default_branch: str
    private: bool
    language: str
    archived: bool

    @classmethod
    def from_api(cls, d: Mapping[str, Any]) -> InstallationRepo:
        return cls(
            full_name=str(d.get("full_name", "")),
            name=str(d.get("name", "")),
            html_url=str(d.get("html_url", "")),
            clone_url=str(d.get("clone_url", "")),
            default_branch=str(d.get("default_branch", "") or "main"),
            private=bool(d.get("private", False)),
            language=str(d.get("language") or ""),
            archived=bool(d.get("archived", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "name": self.name,
            "html_url": self.html_url,
            "clone_url": self.clone_url,
            "default_branch": self.default_branch,
            "private": self.private,
            "language": self.language,
            "archived": self.archived,
        }


@dataclass
class _CachedToken:
    token: str
    expires_at: float  # epoch seconds


def _parse_expiry(value: str) -> float:
    """GitHub's ``expires_at`` (``2026-09-17T12:00:00Z``) → epoch seconds; unparsable = now."""
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


class GitHubApp:
    """The app: JWT, installations, repositories, installation tokens.

    ``client`` is any ``httpx.Client``; its ``base_url`` is ignored — every call names
    ``settings.api_url`` explicitly so a GHES deployment works unchanged.
    """

    def __init__(
        self,
        settings: GitHubAppSettings,
        client: httpx.Client | None = None,
        *,
        timeout_s: float = 20.0,
    ) -> None:
        if not settings.enabled:
            raise GitHubAppError(
                0, "the GitHub App is not configured (CRB_GITHUB__APP_ID and a private key)"
            )
        self.settings = settings
        self.client = client or httpx.Client(timeout=timeout_s)
        self._tokens: dict[int, _CachedToken] = {}

    # --- auth ------------------------------------------------------------------------
    def app_jwt(self, now: float | None = None) -> str:
        """A fresh RS256 JWT for the app (``iss`` = app id; ``iat`` one minute back for skew)."""
        t = int(now if now is not None else time.time())
        payload = {"iat": t - 60, "exp": t + JWT_TTL_S, "iss": self.settings.app_id}
        token = jwt.encode({"alg": "RS256"}, payload, self.settings.private_key_pem())
        return token.decode("ascii") if isinstance(token, bytes) else str(token)

    def _get(self, path: str, *, bearer: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._request("GET", path, bearer=bearer, params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        bearer: str,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self.settings.api_url}{path}"
        try:
            r = self.client.request(
                method,
                url,
                params=dict(params or {}),
                json=json,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {bearer}",
                    "X-GitHub-Api-Version": API_VERSION,
                },
            )
        except httpx.HTTPError as e:
            raise GitHubAppError(0, redact(str(e))[:300]) from e
        if r.status_code >= 400:
            try:
                msg = str(r.json().get("message", ""))
            except ValueError:
                msg = r.text[:300]
            raise GitHubAppError(r.status_code, redact(msg)[:300])
        return r.json() if r.content else {}

    def installation_token(self, installation_id: int, *, now: float | None = None) -> str:
        """A token for ``installation_id`` — minted on first use, cached until five minutes
        before it expires, never stored anywhere else."""
        t = now if now is not None else time.time()
        cached = self._tokens.get(installation_id)
        if cached and cached.expires_at - TOKEN_REFRESH_MARGIN_S > t:
            return cached.token
        data = self._request(
            "POST", f"/app/installations/{installation_id}/access_tokens", bearer=self.app_jwt(now)
        )
        token = str(data.get("token", ""))
        if not token:
            raise GitHubAppError(502, "installation token response carried no token")
        self._tokens[installation_id] = _CachedToken(
            token, _parse_expiry(str(data.get("expires_at", "")))
        )
        return token

    def forget_token(self, installation_id: int) -> None:
        self._tokens.pop(installation_id, None)

    # --- discovery -------------------------------------------------------------------
    def installations(self) -> list[Installation]:
        """Every installation of the app (paged)."""
        out: list[Installation] = []
        page = 1
        while True:
            data = self._get(
                "/app/installations", bearer=self.app_jwt(), params={"per_page": 100, "page": page}
            )
            items = data if isinstance(data, list) else []
            out.extend(Installation.from_api(d) for d in items)
            if len(items) < 100:
                return out
            page += 1

    def installation(self, installation_id: int) -> Installation:
        """One installation, verified with the app's own credential (the setup callback's
        ``installation_id`` is untrusted until this answers)."""
        return Installation.from_api(
            self._get(f"/app/installations/{installation_id}", bearer=self.app_jwt())
        )

    def repositories(
        self, installation_id: int, *, page: int = 1, per_page: int = 100
    ) -> tuple[list[InstallationRepo], int]:
        """The repositories the installation may see (one page) and GitHub's total count."""
        data = self._get(
            "/installation/repositories",
            bearer=self.installation_token(installation_id),
            params={"per_page": per_page, "page": page},
        )
        repos = [InstallationRepo.from_api(d) for d in data.get("repositories", [])]
        return repos, int(data.get("total_count", len(repos)))

    def repository(self, installation_id: int, full_name: str) -> InstallationRepo:
        """One repository by ``owner/name`` — 404 from GitHub when the installation cannot
        see it, which is the check the connect route relies on."""
        owner, _, name = full_name.partition("/")
        if not owner or not name:
            raise GitHubAppError(422, f"not an owner/name: {full_name!r}")
        return InstallationRepo.from_api(
            self._get(f"/repos/{owner}/{name}", bearer=self.installation_token(installation_id))
        )


#: GitHub's ``language`` → the product's ``Language``; anything else is left to the operator.
GITHUB_LANGUAGE: dict[str, str] = {
    "python": "python",
    "go": "go",
    "javascript": "javascript",
    "typescript": "javascript",
    "java": "jvm",
    "kotlin": "jvm",
    "scala": "jvm",
    "rust": "rust",
}
#: The default runner per language for a freshly connected repository (the probe verifies).
DEFAULT_RUNNER: dict[str, str] = {
    "python": "pytest",
    "go": "go",
    "javascript": "node",
    "jvm": "maven",
    "rust": "cargo",
}


def suggest_config(repo: InstallationRepo) -> dict[str, str]:
    """What the connect form pre-fills from what GitHub knows: a product name, the language
    and its default runner. Empty language = the operator chooses."""
    lang = GITHUB_LANGUAGE.get(repo.language.lower(), "")
    name = repo.full_name.lower().replace("/", "-")
    name = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in name)[:64]
    return {"name": name, "language": lang, "runner": DEFAULT_RUNNER.get(lang, "")}
