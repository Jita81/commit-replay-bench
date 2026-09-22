"""crb.server.github_app + routes/github — the enterprise connection, against a fake GitHub.

Navigation
----------
What it is:   Tests for the GitHub App client and its routes: the app JWT is RS256 over
              the app id with a ten-minute life; installation tokens are minted with the
              JWT, cached, and refreshed near expiry; installations and repositories are
              read with the right credential; a pull request's state is read with the
              installation token and reads as merged / closed / open (B-9 / F30);
              GitHub's refusals become ``GitHubAppError``.
              The routes: unconfigured = 404 ``github_app_not_configured`` (and ``GET
              /github/app`` says ``configured: false`` rather than 404); the setup callback
              verifies the installation with the app's credential before recording it;
              sync marks vanished installations suspended; the picker lists with a
              suggested config and marks already-connected repositories; connect registers
              a linked repository (409 on a second connect, 404 when the installation
              cannot see it, 422 when GitHub reports no language and none is given); a
              config update keeps the link; link attaches an installation's repository to
              an EXISTING row (the name and config stay, the URL moves, the
              ``repo.github_linked`` event carries both URLs; 404 / 422 / 409 as connect,
              re-link records the previous ``full_name``, a race is the index's 409); the
              worker clones with the token in the environment — never argv — and its
              delivery provider mints the token for a linked row's own remote.
What it does: Pins that no token is ever persisted or returned (no row, no event payload,
              no API response carries it) — the property ADR-0014 rests on.
How:          ``httpx.MockTransport`` plays GitHub; a throwaway RSA key signs the JWT and
              the test verifies it with the public half; the routes get the client through
              ``app.dependency_overrides[get_github_app]``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/server/github_app.py, src/crb/server/routes/github.py,
              src/crb/server/worker.py (``_github_auth_header``, ``_delivery_credentials``),
              src/crb/core/git.py (``clone_repo(auth_header=)``)
Tested by:    tests/test_server_github_app.py
Touch when:   a route or a field is added; GitHub's payload shapes change.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from authlib.jose import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from crb.server.app import API_PREFIX
from crb.server.auth import issue_github_setup_state
from crb.server.github_app import (
    DELIVERY_PERMISSIONS,
    PR_CLOSED,
    PR_MERGED,
    PR_OPEN,
    GitHubApp,
    GitHubAppError,
    permissions_allow_delivery,
    suggest_config,
)
from crb.server.routes.github import get_github_app
from crb.server.settings import GitHubAppSettings
from crb.store.models import Event, GitHubInstallation, Repo
from fixtures.server_seed import envelope, login, make_env

pytestmark = pytest.mark.timeout(120)


@pytest.fixture(scope="module")
def keypair() -> tuple[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def settings_for(pem: str, **over: Any) -> GitHubAppSettings:
    return GitHubAppSettings(app_id="4242", app_slug="crb-bench", private_key=pem, **over)


INSTALLATION = {
    "id": 77,
    "account": {"login": "acme", "type": "Organization"},
    "repository_selection": "selected",
    "html_url": "https://github.com/organizations/acme/settings/installations/77",
    "permissions": {"contents": "read", "metadata": "read"},
}
INSTALLATION_RW = {
    **INSTALLATION,
    "id": 78,
    "permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"},
}
REPOS = {
    "total_count": 2,
    "repositories": [
        {
            "full_name": "acme/Calc",
            "name": "Calc",
            "html_url": "https://github.com/acme/Calc",
            "clone_url": "https://github.com/acme/Calc.git",
            "default_branch": "main",
            "private": True,
            "language": "Python",
            "archived": False,
        },
        {
            "full_name": "acme/site",
            "name": "site",
            "html_url": "https://github.com/acme/site",
            "clone_url": "https://github.com/acme/site.git",
            "default_branch": "trunk",
            "private": False,
            "language": None,
            "archived": False,
        },
    ],
}


def pull_request_api(
    number: int, state: str, *, full_name: str = "acme/Calc", merged_by: str = "paul"
) -> dict[str, Any]:
    """GitHub's ``GET /repos/{owner}/{name}/pulls/{number}`` shape for one of the three
    fates the sync reads: ``open``, ``merged`` (closed + merged) or ``closed`` (without
    merging). An OPEN pull request carries a ``merge_commit_sha`` too — GitHub's test
    merge — which must never read as a merge."""
    url = f"https://github.com/{full_name}/pull/{number}"
    base: dict[str, Any] = {
        "number": number,
        "html_url": url,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "merge_commit_sha": "f" * 40,
        "merged_by": None,
        "closed_at": None,
        "head": {"sha": "a" * 40, "ref": f"crb/I-{number}"},
        "base": {"ref": "main"},
    }
    if state == PR_MERGED:
        base.update(
            state="closed",
            merged=True,
            merged_at="2026-09-19T17:02:11Z",
            merge_commit_sha="e0fefb2" + "0" * 33,
            merged_by={"login": merged_by, "type": "User"},
            closed_at="2026-09-19T17:02:11Z",
        )
    elif state == PR_CLOSED:
        base.update(state="closed", merge_commit_sha=None, closed_at="2026-09-20T09:00:00Z")
    return base


class FakeGitHub:
    """A minimal GitHub: records every request; serves installations, tokens, repos, and
    pull requests (``pulls[(full_name_lower, number)]`` — absent = 404)."""

    def __init__(self, public_key: Any) -> None:
        self.public_key = public_key
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.tokens_minted = 0
        self.installations: list[dict[str, Any]] = [INSTALLATION, INSTALLATION_RW]
        self.pulls: dict[tuple[str, int], dict[str, Any]] = {
            ("acme/calc", 7): pull_request_api(7, PR_OPEN),
            ("acme/calc", 8): pull_request_api(8, PR_MERGED),
            ("acme/calc", 9): pull_request_api(9, PR_CLOSED),
        }
        self.moved: set[str] = set()  # lower-cased ``owner/name`` that answer 301
        #: lower-cased ``owner/name`` whose 301 carries a NON-object JSON body (a gateway's
        #: answer, not GitHub's ``{"message"}`` shape)
        self.moved_odd_body: set[str] = set()
        # lower-cased ``owner/name`` → the ``owner/name`` GitHub answers 200 with instead
        # (a redirect the transport followed, or a transfer answered under the new owner)
        self.answered_as: dict[str, str] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _bearer(self, req: httpx.Request) -> str:
        return req.headers.get("Authorization", "").removeprefix("Bearer ")

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path, dict(req.headers)))
        path = req.url.path
        bearer = self._bearer(req)
        if path == "/app/installations":
            claims = jwt.decode(bearer, self.public_key)  # an app JWT, or this raises
            assert claims["iss"] == "4242"
            return httpx.Response(200, json=self.installations)
        if path.startswith("/app/installations/") and path.endswith("/access_tokens"):
            jwt.decode(bearer, self.public_key)
            self.tokens_minted += 1
            iid = path.split("/")[3]
            return httpx.Response(
                201,
                json={
                    "token": f"ghs_token_{iid}_{self.tokens_minted}",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
        if path.startswith("/app/installations/"):
            jwt.decode(bearer, self.public_key)
            iid = int(path.split("/")[3])
            for i in self.installations:
                if i["id"] == iid:
                    return httpx.Response(200, json=i)
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/installation/repositories":
            assert bearer.startswith("ghs_token_"), "repositories need an installation token"
            return httpx.Response(200, json=REPOS)
        if path.startswith("/repos/") and "/pulls/" in path:
            assert bearer.startswith("ghs_token_"), "a pull request needs an installation token"
            full, _, num = path.removeprefix("/repos/").partition("/pulls/")
            pr = self.pulls.get((full.lower(), int(num)))
            if pr is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=pr)
        if path.startswith("/repos/"):
            assert bearer.startswith("ghs_token_")
            full = path.removeprefix("/repos/")
            if full.lower() in self.moved_odd_body:
                # a gateway in front of GitHub answering the redirect with a JSON array
                return httpx.Response(301, json=["moved", f"/repositories/{full}"])
            if full.lower() in self.moved:
                # a renamed or transferred repository: GitHub answers 301 (the client never
                # follows it) with a body that is not a repository
                return httpx.Response(
                    301,
                    json={"message": "Moved Permanently", "url": f"/repositories/{full}"},
                    headers={"Location": f"https://api.github.invalid/repositories/{full}"},
                )
            full = self.answered_as.get(full.lower(), full)
            for r in REPOS["repositories"]:
                if r["full_name"].lower() == full.lower():
                    return httpx.Response(200, json=r)
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(500, json={"message": f"unexpected {path}"})


# --- the client ------------------------------------------------------------------------


def test_app_jwt_is_rs256_over_the_app_id_with_a_short_life(keypair: tuple[str, Any]) -> None:
    pem, public = keypair
    app = GitHubApp(
        settings_for(pem),
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    token = app.app_jwt(now=1_000_000)
    claims = jwt.decode(token, public)
    assert (
        claims["iss"] == "4242"
        and claims["iat"] == 1_000_000 - 60
        and claims["exp"] == 1_000_000 + 540
    )
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "==").decode())
    assert header["alg"] == "RS256"


def test_unconfigured_settings_refuse_to_build_a_client() -> None:
    assert not GitHubAppSettings().enabled
    with pytest.raises(GitHubAppError, match="not configured"):
        GitHubApp(GitHubAppSettings())
    with pytest.raises(ValueError, match="https://"):
        GitHubAppSettings(api_url="http://ghes.example/api/v3")


def test_installation_tokens_are_minted_with_the_jwt_cached_and_refreshed_near_expiry(
    keypair: tuple[str, Any],
) -> None:
    pem, public = keypair
    gh = FakeGitHub(public)
    app = GitHubApp(settings_for(pem), httpx.Client(transport=gh.transport()))
    t1 = app.installation_token(77, now=1_000_000)
    t2 = app.installation_token(77, now=1_000_100)
    assert t1 == t2 == "ghs_token_77_1" and gh.tokens_minted == 1
    # a different installation is a different token; an expiring one is re-minted
    assert app.installation_token(78) == "ghs_token_78_2"
    app._tokens[77].expires_at = time.time() + 60  # inside the five-minute margin
    assert app.installation_token(77) == "ghs_token_77_3"
    # the token never travels anywhere but the Authorization header of the next call
    repos, total = app.repositories(77)
    assert total == 2 and [r.full_name for r in repos] == ["acme/Calc", "acme/site"]
    last = gh.calls[-1]
    assert (
        last[1] == "/installation/repositories"
        and last[2]["authorization"] == "Bearer ghs_token_77_3"
    )
    inst = app.installation(78)
    assert inst.can_deliver and not app.installation(77).can_deliver
    assert [i.id for i in app.installations()] == [77, 78]


def test_one_delivery_permission_predicate() -> None:
    """``Installation.can_deliver``, the factory pre-flight and the installations route
    all read ``permissions_allow_delivery``: both write scopes, exactly; a missing scope,
    a read level, an empty or absent mapping, and a stored row's non-string level all say no."""
    assert DELIVERY_PERMISSIONS == {"contents": "write", "pull_requests": "write"}
    assert permissions_allow_delivery({"contents": "write", "pull_requests": "write"})
    assert permissions_allow_delivery(
        {"contents": "write", "pull_requests": "write", "metadata": "read"}
    )
    assert not permissions_allow_delivery({"contents": "write"})
    assert not permissions_allow_delivery({"contents": "read", "pull_requests": "write"})
    assert not permissions_allow_delivery({"contents": "write", "pull_requests": "read"})
    assert not permissions_allow_delivery({})
    assert not permissions_allow_delivery(None)
    assert not permissions_allow_delivery({"contents": None, "pull_requests": "write"})
    # the dataclass property is the same predicate
    from crb.server.github_app import Installation

    inst = Installation.from_api({"id": 1, "permissions": {"contents": "write"}})
    assert inst.can_deliver is permissions_allow_delivery(inst.permissions) is False


def test_github_refusals_become_errors_with_status_and_redacted_message(
    keypair: tuple[str, Any],
) -> None:
    pem, public = keypair
    gh = FakeGitHub(public)
    app = GitHubApp(settings_for(pem), httpx.Client(transport=gh.transport()))
    with pytest.raises(GitHubAppError, match="GitHub 404: Not Found") as e:
        app.installation(99)
    assert e.value.status == 404
    with pytest.raises(GitHubAppError, match="GitHub 404"):
        app.repository(77, "acme/nope")
    with pytest.raises(GitHubAppError, match="not an owner/name"):
        app.repository(77, "nope")
    down = GitHubApp(
        settings_for(pem),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: (_ for _ in ()).throw(httpx.ConnectError("boom"))
            )
        ),
    )
    with pytest.raises(GitHubAppError, match="unreachable") as e2:
        down.installations()
    assert e2.value.status == 0
    # a 2xx with no body, or one that is not JSON, is GitHub's fault and a 502 — never a
    # false "no installations" and never a KeyError from an empty installation
    for body in (b"", b"<html>maintenance</html>"):
        odd = GitHubApp(
            settings_for(pem),
            httpx.Client(
                transport=httpx.MockTransport(lambda r, b=body: httpx.Response(200, content=b))
            ),
        )
        with pytest.raises(GitHubAppError, match=r"empty response|malformed response") as e3:
            odd.installations()
        assert e3.value.status == 502
        with pytest.raises(GitHubAppError, match=r"empty response|malformed response"):
            odd.installation(77)


def test_pull_request_state_is_read_with_the_installation_token(
    keypair: tuple[str, Any],
) -> None:
    """B-9 / F30: the three fates a delivered pull request can have, as GitHub reports them,
    read with the installation's token (never the app JWT) and folded into one word."""
    pem, public = keypair
    gh = FakeGitHub(public)
    app = GitHubApp(settings_for(pem), httpx.Client(transport=gh.transport()))
    open_ = app.pull_request(78, "acme/Calc", 7)
    assert (open_.outcome, open_.state, open_.merged, open_.number) == (PR_OPEN, "open", False, 7)
    assert open_.merge_commit_sha == "" and open_.merged_by == "" and open_.merged_at == ""
    assert open_.head_sha == "a" * 40 and open_.html_url.endswith("/pull/7")
    merged = app.pull_request(78, "acme/Calc", 8)
    assert (merged.outcome, merged.merged_by, merged.merged_at) == (
        PR_MERGED,
        "paul",
        "2026-09-19T17:02:11Z",
    )
    assert merged.merge_commit_sha.startswith("e0fefb2") and merged.closed_at
    closed = app.pull_request(78, "acme/Calc", 9)
    assert (closed.outcome, closed.merged, closed.merge_commit_sha) == (PR_CLOSED, False, "")
    assert closed.closed_at == "2026-09-20T09:00:00Z" and closed.merged_by == ""
    # one token mint for the three reads; every read went under it, with the api version
    assert gh.tokens_minted == 1
    reads = [c for c in gh.calls if "/pulls/" in c[1]]
    assert [c[1] for c in reads] == [
        "/repos/acme/Calc/pulls/7",
        "/repos/acme/Calc/pulls/8",
        "/repos/acme/Calc/pulls/9",
    ]
    assert all(c[2]["authorization"].startswith("Bearer ghs_token_78_") for c in reads)
    # refusals: a PR GitHub does not have, a malformed name, a number that is not one
    with pytest.raises(GitHubAppError, match="GitHub 404") as e:
        app.pull_request(78, "acme/Calc", 404)
    assert e.value.status == 404
    with pytest.raises(GitHubAppError, match="not an owner/name"):
        app.pull_request(78, "../rate_limit", 7)
    with pytest.raises(GitHubAppError, match="not a pull request number"):
        app.pull_request(78, "acme/Calc", 0)
    assert not [c for c in gh.calls if c[1].endswith("/pulls/0")]


def test_suggest_config_maps_github_language_to_ours() -> None:
    from crb.server.github_app import InstallationRepo

    py = InstallationRepo.from_api(REPOS["repositories"][0])
    assert suggest_config(py) == {"name": "acme-calc", "language": "python", "runner": "pytest"}
    unknown = InstallationRepo.from_api(REPOS["repositories"][1])
    assert suggest_config(unknown) == {"name": "acme-site", "language": "", "runner": ""}
    ts = InstallationRepo.from_api(
        {**REPOS["repositories"][0], "language": "TypeScript", "full_name": "Acme/Web App"}
    )
    assert suggest_config(ts) == {
        "name": "acme-web-app",
        "language": "javascript",
        "runner": "node",
    }


# --- the routes --------------------------------------------------------------------------


def _wire(env: Any, pem: str, public: Any) -> FakeGitHub:
    """Configure the app on the env's settings (what ``GET /github/app`` reads) and route
    every GitHub call to the fake through the dependency."""
    gh = FakeGitHub(public)
    env.settings.github = settings_for(pem)
    app = GitHubApp(env.settings.github, httpx.Client(transport=gh.transport()))
    env.client.app.dependency_overrides[get_github_app] = lambda: app
    return gh


def test_unconfigured_app_is_a_state_not_an_error(tmp_path: Path) -> None:
    with make_env(tmp_path) as env:
        r = env.get("/github/app")
        assert r.status_code == 200 and r.json() == {
            "configured": False,
            "app_slug": "",
            "install_url": "",
            "api_url": "",
            "installations": [],
        }
        r = env.post("/github/installations/sync")
        assert r.status_code == 404 and envelope(r)["code"] == "github_app_not_configured"
        r = env.get("/github/installations/77/repositories")
        assert r.status_code == 404 and envelope(r)["code"] == "github_app_not_configured"


def _state_for(env: Any, user_id: str, nonce: str = "n") -> str:
    """A state signed by the deployment for another principal (a replayed link)."""
    return issue_github_setup_state(env.settings, user_id, nonce)


def test_setup_callback_verifies_records_and_lands_on_connect(
    tmp_path: Path, keypair: tuple[str, Any]
) -> None:
    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        gh = _wire(env, pem, public)
        # an id GitHub does not know is refused before anything is written
        r = env.client.get(
            f"{API_PREFIX}/github/setup?installation_id=99&setup_action=install",
            follow_redirects=False,
        )
        assert r.status_code == 502 and envelope(r)["code"] == "github_error"
        # a callback that carries no state this deployment signed for THIS operator writes
        # nothing (CWE-352): it lands on Connect flagged unverified, where the CSRF-protected
        # sync records the installation with the same app-credential check
        for bad in ("", "&state=not-a-state", f"&state={_state_for(env, 'someone-else')}"):
            r = env.client.get(
                f"{API_PREFIX}/github/setup?installation_id=77&setup_action=install{bad}",
                follow_redirects=False,
            )
            assert r.status_code == 303, r.text
            assert r.headers["location"] == "/connect?installation=77&unverified=1"
        with env.factory() as s:
            assert s.get(GitHubInstallation, 77) is None
        # the install link the operator is given carries the state; GitHub passes it back.
        # The same response binds the link to THIS browser with a nonce cookie (httponly)
        r = env.get("/github/app")
        link = r.json()["install_url"]
        assert link.startswith("https://github.com/apps/crb-bench/installations/new?state=")
        state = link.split("state=", 1)[1]
        assert "crb_github_setup" in r.cookies and "HttpOnly" in r.headers["set-cookie"]
        # the right state in the wrong browser (no cookie, or another link's cookie) writes nothing
        cookie = env.client.cookies.get("crb_github_setup")
        for wrong in (None, "another-links-nonce"):
            env.client.cookies.delete("crb_github_setup")
            if wrong:
                env.client.cookies.set("crb_github_setup", wrong)
            r = env.client.get(
                f"{API_PREFIX}/github/setup?installation_id=77&setup_action=install&state={state}",
                follow_redirects=False,
            )
            assert r.headers["location"] == "/connect?installation=77&unverified=1"
        env.client.cookies.set("crb_github_setup", cookie)
        r = env.client.get(
            f"{API_PREFIX}/github/setup?installation_id=77&setup_action=install&state={state}",
            follow_redirects=False,
        )
        assert r.status_code == 303 and r.headers["location"] == "/connect?installation=77"
        # …and the write consumed the nonce: the response expires the cookie (a browser
        # drops it on Max-Age=0; the test jar, which held a hand-set copy, is told the same)
        assert (
            'crb_github_setup=""' in r.headers["set-cookie"]
            and "Max-Age=0" in r.headers["set-cookie"]
        )
        env.client.cookies.delete("crb_github_setup")
        r = env.client.get(
            f"{API_PREFIX}/github/setup?installation_id=77&setup_action=install&state={state}",
            follow_redirects=False,
        )
        assert r.headers["location"] == "/connect?installation=77&unverified=1"
        with env.factory() as s:
            row = s.get(GitHubInstallation, 77)
            assert (
                row is not None
                and row.account_login == "acme"
                and row.repository_selection == "selected"
            )
            assert (
                row.permissions_json == {"contents": "read", "metadata": "read"}
                and not row.suspended
            )
            ev = (
                s.execute(select(Event).where(Event.action == "github.installation.recorded"))
                .scalars()
                .one()
            )
            assert (
                ev.payload_json["installation_id"] == 77 and ev.payload_json["can_deliver"] is False
            )
            assert "ghs_" not in json.dumps(ev.payload_json)
        # the app view now lists it; a viewer may read it
        login(env.client, "viewer")
        body = env.get("/github/app").json()
        # a viewer's link is plain: a viewer cannot complete the callback, so no state is minted
        assert (
            body["configured"]
            and body["install_url"] == "https://github.com/apps/crb-bench/installations/new"
        )
        assert [i["id"] for i in body["installations"]] == [77] and body["installations"][0][
            "can_deliver"
        ] is False
        assert "ghs_" not in json.dumps(body) and gh.tokens_minted == 0


def test_sync_records_every_installation_and_suspends_vanished_ones(
    tmp_path: Path, keypair: tuple[str, Any]
) -> None:
    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        gh = _wire(env, pem, public)
        r = env.post("/github/installations/sync")
        assert r.status_code == 200 and [i["id"] for i in r.json()] == [77, 78]
        assert r.json()[1]["can_deliver"] is True
        gh.installations = [INSTALLATION_RW]  # 77 was uninstalled
        r = env.post("/github/installations/sync")
        assert [i["id"] for i in r.json()] == [78]
        with env.factory() as s:
            assert s.get(GitHubInstallation, 77).suspended is True
        login(env.client, "viewer")
        assert env.post("/github/installations/sync").status_code == 403


def test_picker_lists_with_suggestions_and_connect_registers_a_linked_repo(
    tmp_path: Path, keypair: tuple[str, Any]
) -> None:
    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        gh = _wire(env, pem, public)
        assert env.post("/github/installations/sync").status_code == 200
        # unknown installation → 404 before GitHub is asked
        assert env.get("/github/installations/5/repositories").status_code == 404
        page = env.get("/github/installations/77/repositories").json()
        assert page["total"] == 2 and not page["has_more"]
        calc, site = page["items"]
        assert (
            calc["suggested"] == {"name": "acme-calc", "language": "python", "runner": "pytest"}
            and calc["connected_as"] is None
        )
        assert site["suggested"]["language"] == ""
        assert (
            env.get("/github/installations/77/repositories?q=calc").json()["items"][0]["full_name"]
            == "acme/Calc"
        )
        # connect with the suggestion (name, language, runner all defaulted)
        r = env.post("/github/installations/77/connect", json={"full_name": "acme/Calc"})
        assert r.status_code == 201, r.text
        detail = r.json()
        assert (
            detail["name"] == "acme-calc"
            and detail["language"] == "python"
            and detail["runner"] == "pytest"
        )
        assert detail["url"] == "https://github.com/acme/Calc.git" and detail["clone_path"] == ""
        with env.factory() as s:
            row = s.get(Repo, "acme-calc")
            assert row is not None
            assert row.config_json["github"] == {
                "installation_id": 77,
                "full_name": "acme/Calc",
                "default_branch": "main",
                "html_url": "https://github.com/acme/Calc",
                "private": True,
            }
            assert "ghs_" not in json.dumps(row.config_json)
        # the picker now marks it
        page = env.get("/github/installations/77/repositories").json()
        assert page["items"][0]["connected_as"] == "acme-calc"
        # a second connect of the same repository is a 409 naming it
        r = env.post(
            "/github/installations/77/connect", json={"full_name": "acme/Calc", "name": "again"}
        )
        assert r.status_code == 409 and envelope(r)["detail"]["repo"] == "acme-calc"
        # a repository the installation cannot see is a 404 in the API's words
        r = env.post("/github/installations/77/connect", json={"full_name": "acme/nope"})
        assert r.status_code == 404 and "not visible to installation 77" in envelope(r)["message"]
        # no language from GitHub and none given → 422 with the suggestion; given → fine
        r = env.post("/github/installations/77/connect", json={"full_name": "acme/site"})
        assert r.status_code == 422 and envelope(r)["detail"]["suggested"]["name"] == "acme-site"
        r = env.post(
            "/github/installations/77/connect",
            json={
                "full_name": "acme/site",
                "language": "javascript",
                "runner": "vitest",
                "src_prefix": "src/",
                "test_prefix": "test/",
            },
        )
        assert r.status_code == 201 and r.json()["config"]["test_prefix"] == "test/"
        # a config update keeps the link (PRESERVED_KEYS) and the constrained identity
        r = env.put("/repos/acme-calc", json={"src_prefix": "calc/"})
        assert r.status_code == 200, r.text
        with env.factory() as s:
            row = s.get(Repo, "acme-calc")
            assert row.config_json["github"]["installation_id"] == 77
            assert row.github_full_name == "acme/calc"
        # a URL change drops the link: the worker would otherwise mint the installation's
        # token and hand it to whatever host the new URL names (CWE-201)
        r = env.put("/repos/acme-calc", json={"url": "https://code.example.org/acme/calc.git"})
        assert r.status_code == 200, r.text
        assert "github" not in r.json()["config"]
        with env.factory() as s:
            row = s.get(Repo, "acme-calc")
            assert "github" not in row.config_json and row.github_full_name is None
            ev = s.execute(select(Event).where(Event.action == "repo.updated")).scalars().all()
            assert [e.payload_json["github_unlinked"] for e in ev] == [False, True]
        # …and the same GitHub repository can be connected again afterwards (no ghost row)
        r = env.post(
            "/github/installations/77/connect",
            json={"full_name": "acme/Calc", "name": "acme-calc-2"},
        )
        assert r.status_code == 201, r.text
        # a viewer may list but not connect
        login(env.client, "viewer")
        assert env.get("/github/installations/77/repositories").status_code == 200
        assert (
            env.post(
                "/github/installations/77/connect", json={"full_name": "acme/Calc"}
            ).status_code
            == 403
        )
        assert gh.tokens_minted >= 1


# --- link an existing repository -----------------------------------------------------------


def _seed_repo(
    env: Any, name: str = "cobra", url: str = "https://github.com/spf13/cobra.git"
) -> None:
    r = env.post("/repos", json={"name": name, "language": "go", "runner": "go", "url": url})
    assert r.status_code == 201, r.text


def test_link_attaches_an_installation_repository_to_an_existing_row(
    tmp_path: Path, keypair: tuple[str, Any]
) -> None:
    """A repository measured before the app existed (or whose history now lives on a fork)
    keeps its name — and with it its ledger rows; the link changes its URL and writes the
    same link dict connect does, and the events table carries the seam an auditor reads."""
    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        _wire(env, pem, public)
        assert env.post("/github/installations/sync").status_code == 200
        _seed_repo(env)
        r = env.post(
            "/repos/cobra/github-link", json={"installation_id": 77, "full_name": "acme/Calc"}
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        # the name, language, runner and layout are untouched; only the URL moved
        assert detail["name"] == "cobra" and detail["language"] == "go" and detail["runner"] == "go"
        assert detail["url"] == "https://github.com/acme/Calc.git"
        assert detail["config"]["url"] == "https://github.com/acme/Calc.git"
        assert detail["github_full_name"] == "acme/calc"
        with env.factory() as s:
            row = s.get(Repo, "cobra")
            assert row.url == "https://github.com/acme/Calc.git"
            assert row.github_full_name == "acme/calc"
            assert row.config_json["github"] == {
                "installation_id": 77,
                "full_name": "acme/Calc",
                "default_branch": "main",
                "html_url": "https://github.com/acme/Calc",
                "private": True,
            }
            assert row.config_json["language"] == "go" and row.config_json["runner"] == "go"
            assert "ghs_" not in json.dumps(row.config_json)
            ev = (
                s.execute(select(Event).where(Event.action == "repo.github_linked")).scalars().one()
            )
            assert ev.repo == "cobra" and ev.payload_json == {
                "github": row.config_json["github"],
                "url_before": "https://github.com/spf13/cobra.git",
                "url_after": "https://github.com/acme/Calc.git",
                "previous_full_name": None,
                # the ``repo.updated`` shape too, so the Configuration tab's audit trail
                # renders "Changed: url" with the before/after diff
                "fields": ["url"],
                "diff": {
                    "url": {
                        "from": "https://github.com/spf13/cobra.git",
                        "to": "https://github.com/acme/Calc.git",
                    }
                },
            }
            assert "ghs_" not in json.dumps(ev.payload_json)
        # the repo's own event trail shows the seam, newest first
        trail = env.get("/repos/cobra/events").json()["items"]
        assert trail[0]["action"] == "repo.github_linked"
        # the picker now marks the GitHub repository as connected under the OLD name
        page = env.get("/github/installations/77/repositories").json()
        assert page["items"][0]["connected_as"] == "cobra"
        # the list row says which repositories carry a link (what the UI's select filters on)
        rows = {r["name"]: r["github_full_name"] for r in env.get("/repos").json()["items"]}
        assert rows["cobra"] == "acme/calc" and rows["alpha"] is None  # alpha: seeded by URL
        # after the link the worker resolves delivery credentials for the row's own remote
        from crb.server import worker as w

        gh_worker = FakeGitHub(public)
        settings = w.WorkerSettings(home=tmp_path / "home", github=settings_for(pem))
        worker = w.Worker.__new__(w.Worker)
        worker.settings = settings
        worker._github_app_client = GitHubApp(
            settings.github, httpx.Client(transport=gh_worker.transport())
        )
        with env.factory() as s:
            row = s.get(Repo, "cobra")
            cfg, remote = dict(row.config_json), str(row.url)
        # installation 77 is read-only: measurement clones, delivery fails closed
        assert worker._github_auth_header(cfg, remote) is not None
        assert worker._delivery_credentials(cfg, remote) is None
        # re-linked to the writable installation, the same remote gets a delivery provider
        r = env.post(
            "/repos/cobra/github-link", json={"installation_id": 78, "full_name": "acme/Calc"}
        )
        assert r.status_code == 200, r.text
        with env.factory() as s:
            row = s.get(Repo, "cobra")
            cfg, remote = dict(row.config_json), str(row.url)
        provider = worker._delivery_credentials(cfg, remote)
        assert provider is not None
        creds = provider.resolve("cobra")
        assert creds.remote == remote and creds.token.startswith("ghs_token_78_")
        assert "ghs_" not in repr(creds)


def test_link_refusals_and_the_relink_seam(tmp_path: Path, keypair: tuple[str, Any]) -> None:
    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        _wire(env, pem, public)
        assert env.post("/github/installations/sync").status_code == 200
        _seed_repo(env)
        _seed_repo(env, "other", "https://example.org/other.git")
        body = {"installation_id": 77, "full_name": "acme/Calc"}
        # unknown repository
        r = env.post("/repos/nope/github-link", json=body)
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"
        # an installation not on record, before GitHub is asked
        r = env.post("/repos/cobra/github-link", json={**body, "installation_id": 5})
        assert r.status_code == 404 and "not on record" in envelope(r)["message"]
        # a repository the installation cannot see — connect's words
        r = env.post("/repos/cobra/github-link", json={**body, "full_name": "acme/nope"})
        assert r.status_code == 404 and "not visible to installation 77" in envelope(r)["message"]
        # an archived repository
        REPOS["repositories"].append(
            {
                "full_name": "acme/old",
                "name": "old",
                "html_url": "https://github.com/acme/old",
                "clone_url": "https://github.com/acme/old.git",
                "default_branch": "main",
                "private": False,
                "language": "Go",
                "archived": True,
            }
        )
        try:
            r = env.post("/repos/cobra/github-link", json={**body, "full_name": "acme/old"})
            assert r.status_code == 422 and "archived" in envelope(r)["message"]
        finally:
            REPOS["repositories"].pop()
        # a malformed body never reaches GitHub
        r = env.post("/repos/cobra/github-link", json={**body, "full_name": "nope"})
        assert r.status_code == 422
        r = env.post("/repos/cobra/github-link", json={**body, "extra": 1})
        assert r.status_code == 422
        # nothing was written by any refusal
        with env.factory() as s:
            row = s.get(Repo, "cobra")
            assert "github" not in row.config_json and row.github_full_name is None
            assert row.url == "https://github.com/spf13/cobra.git"
            linked = select(Event).where(Event.action == "repo.github_linked")
            assert s.execute(linked).first() is None
        # linked once …
        assert env.post("/repos/cobra/github-link", json=body).status_code == 200
        # … the same GitHub repository cannot be linked to a DIFFERENT row (409 naming it)
        r = env.post("/repos/other/github-link", json=body)
        assert r.status_code == 409 and envelope(r)["detail"]["repo"] == "cobra"
        assert envelope(r)["code"] == "already_exists"
        # nor connected as a new row
        r = env.post("/github/installations/77/connect", json={"full_name": "acme/Calc"})
        assert r.status_code == 409 and envelope(r)["detail"]["repo"] == "cobra"
        # linking the same row to the same repository again is idempotent (200, same link)
        r = env.post("/repos/cobra/github-link", json=body)
        assert r.status_code == 200 and r.json()["github_full_name"] == "acme/calc"
        # re-linking the row to ANOTHER repository replaces the link and records the previous
        r = env.post(
            "/repos/cobra/github-link", json={"installation_id": 77, "full_name": "acme/site"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["url"] == "https://github.com/acme/site.git"
        with env.factory() as s:
            row = s.get(Repo, "cobra")
            assert row.github_full_name == "acme/site"
            assert row.config_json["github"]["full_name"] == "acme/site"
            events = s.execute(linked.order_by(Event.seq)).scalars().all()
            assert [e.payload_json["previous_full_name"] for e in events] == [
                None,
                "acme/Calc",
                "acme/Calc",
            ]
            assert events[-1].payload_json["url_before"] == "https://github.com/acme/Calc.git"
            assert events[-1].payload_json["url_after"] == "https://github.com/acme/site.git"
        # acme/Calc is free again: the other row may take it now
        assert env.post("/repos/other/github-link", json=body).status_code == 200
        # a viewer may not link
        login(env.client, "viewer")
        assert env.post("/repos/cobra/github-link", json=body).status_code == 403


def test_link_refuses_an_answer_that_is_not_the_repository_asked_for(
    tmp_path: Path, keypair: tuple[str, Any]
) -> None:
    """GitHub's answer must BE the repository asked for, or nothing is written. A renamed or
    transferred repository answers 301 (a body that is not a repository): 502 naming it,
    not a 200 that commits ``url=""`` over a measured row. A dot segment that passes a
    loose pattern would be collapsed by the URL layer (``/repos/../rate_limit`` →
    ``GET /rate_limit`` under the installation's bearer): refused before any GitHub call. A
    200 under a different ``full_name`` (a followed redirect) is a 422 naming the new one.
    The guards sit on the path connect shares, so connect is cured the same way."""
    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        gh = _wire(env, pem, public)
        assert env.post("/github/installations/sync").status_code == 200
        _seed_repo(env)
        untouched = {"url": "https://github.com/spf13/cobra.git", "github_full_name": None}

        def row_is_untouched() -> None:
            with env.factory() as s:
                row = s.get(Repo, "cobra")
                assert row.url == untouched["url"]
                assert row.github_full_name is None and "github" not in row.config_json
                linked = select(Event).where(Event.action == "repo.github_linked")
                assert s.execute(linked).first() is None

        # a renamed repository: GitHub's 301 is a refusal, in GitHub's words
        gh.moved.add("acme/renamed")
        r = env.post(
            "/repos/cobra/github-link", json={"installation_id": 77, "full_name": "acme/renamed"}
        )
        assert r.status_code == 502, r.text
        assert envelope(r)["code"] == "github_error"
        assert "Moved Permanently" in envelope(r)["message"]
        assert envelope(r)["detail"]["github_status"] == 301
        row_is_untouched()
        # connect shares the guard
        r = env.post("/github/installations/77/connect", json={"full_name": "acme/renamed"})
        assert r.status_code == 502 and envelope(r)["detail"]["github_status"] == 301
        # a 3xx whose JSON body is not an object (a gateway's array) is still the 502, in
        # the status line's words — never a 500 from reading ``.get`` on a list
        gh.moved_odd_body.add("acme/gateway")
        r = env.post(
            "/repos/cobra/github-link", json={"installation_id": 77, "full_name": "acme/gateway"}
        )
        assert r.status_code == 502, r.text
        assert envelope(r)["detail"]["github_status"] == 301
        assert '"moved"' in envelope(r)["message"]  # the body's text, since it had no message
        row_is_untouched()
        # a dot segment never reaches GitHub — the pattern refuses it (422) and the client
        # would refuse it too; no request outside ``/repos/`` was made under the bearer
        before = len(gh.calls)
        for bad in ("../rate_limit", "acme/..", "./meta", "acme/.", "-acme/x", "acme-/x"):
            r = env.post("/repos/cobra/github-link", json={"installation_id": 77, "full_name": bad})
            assert r.status_code == 422, (bad, r.text)
            r = env.post("/github/installations/77/connect", json={"full_name": bad})
            assert r.status_code == 422, (bad, r.text)
        assert gh.calls[before:] == []
        assert all(
            path.startswith(("/app/", "/repos/", "/installation/")) for _, path, _ in gh.calls
        )
        row_is_untouched()
        # the client itself refuses a dot segment even without the pattern in front of it
        app = GitHubApp(settings_for(pem), httpx.Client(transport=gh.transport()))
        for bad in ("../rate_limit", "acme/..", "a/b/c"):
            with pytest.raises(GitHubAppError) as ei:
                app.repository(77, bad)
            assert ei.value.status == 422
        assert not any(path == "/rate_limit" for _, path, _ in gh.calls)
        # a 200 that names a DIFFERENT repository (a redirect the transport followed, or a
        # transfer answered under the new owner) is the operator's stale input: 422 naming it
        REPOS["repositories"].append(
            {
                "full_name": "newowner/Calc",
                "name": "Calc",
                "html_url": "https://github.com/newowner/Calc",
                "clone_url": "https://github.com/newowner/Calc.git",
                "default_branch": "main",
                "private": False,
                "language": "Go",
                "archived": False,
            }
        )
        gh.answered_as["acme/moved"] = "newowner/Calc"
        try:
            r = env.post(
                "/repos/cobra/github-link", json={"installation_id": 77, "full_name": "acme/moved"}
            )
            assert r.status_code == 422, r.text
            assert envelope(r)["code"] == "validation_error"
            assert "newowner/Calc" in envelope(r)["message"]
            assert envelope(r)["detail"]["full_name"] == "newowner/Calc"
            row_is_untouched()
            # an answer with no clone URL at all is GitHub's fault
            REPOS["repositories"][-1]["clone_url"] = ""
            r = env.post(
                "/repos/cobra/github-link",
                json={"installation_id": 77, "full_name": "newowner/Calc"},
            )
            assert r.status_code == 502 and envelope(r)["code"] == "github_error"
            row_is_untouched()
        finally:
            REPOS["repositories"].pop()


def test_link_race_is_decided_by_the_unique_index(
    tmp_path: Path, keypair: tuple[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two operators link the same GitHub repository to two rows at once: the scan passes
    for both, the unique index on ``repos.github_full_name`` refuses the second commit, and
    the route answers 409 rather than 500 — with nothing half-written."""
    from crb.server.routes import github as gh_routes

    pem, public = keypair
    with make_env(tmp_path, role="operator") as env:
        _wire(env, pem, public)
        assert env.post("/github/installations/sync").status_code == 200
        _seed_repo(env)
        _seed_repo(env, "other", "https://example.org/other.git")
        # the scan sees nothing (the other request has not committed yet) …
        monkeypatch.setattr(gh_routes, "_connected_names", lambda db: {})
        body = {"installation_id": 77, "full_name": "acme/Calc"}
        assert env.post("/repos/cobra/github-link", json=body).status_code == 200
        # … so the index decides
        r = env.post("/repos/other/github-link", json=body)
        assert r.status_code == 409 and envelope(r)["code"] == "already_exists"
        with env.factory() as s:
            other = s.get(Repo, "other")
            assert other.github_full_name is None and "github" not in other.config_json
            assert other.url == "https://example.org/other.git"
            linked = select(Event).where(Event.action == "repo.github_linked")
            assert s.execute(linked).scalars().one().repo == "cobra"


# --- the worker ----------------------------------------------------------------------------


def test_worker_clones_with_the_installation_token_in_the_environment_never_argv(
    tmp_path: Path, keypair: tuple[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.core import git as core_git
    from crb.server import worker as w

    pem, public = keypair
    gh = FakeGitHub(public)
    settings = w.WorkerSettings(home=tmp_path / "home", github=settings_for(pem))
    worker = w.Worker.__new__(w.Worker)
    worker.settings = settings
    worker._github_app_client = GitHubApp(settings.github, httpx.Client(transport=gh.transport()))
    header = worker._github_auth_header({"github": {"installation_id": 77}})
    assert header is not None and header.startswith("Authorization: Basic ")
    assert "ghs_token_77_1" not in header  # base64 of x-access-token:<token>, never the raw token
    assert (
        worker._github_auth_header({"github": {}}) is None
        and worker._github_auth_header({}) is None
    )
    # the token goes only to the app's own host: a URL edited to point elsewhere gets none
    assert (
        worker._github_auth_header(
            {"github": {"installation_id": 77}}, "https://github.com/acme/Calc.git"
        )
        is not None
    )
    assert (
        worker._github_auth_header(
            {"github": {"installation_id": 77}}, "https://evil.example/acme/Calc.git"
        )
        is None
    )
    assert (
        worker._github_auth_header(
            {"github": {"installation_id": 77}}, "http://github.com/acme/Calc.git"
        )
        is None
    )
    # an unconfigured app never mints
    unconfigured = w.Worker.__new__(w.Worker)
    unconfigured.settings = w.WorkerSettings(home=tmp_path / "h2")
    unconfigured._github_app_client = None
    assert unconfigured._github_auth_header({"github": {"installation_id": 77}}) is None

    # clone_repo hands the header to git through GIT_CONFIG_*, not argv
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kw: Any) -> Any:
        seen["argv"] = list(argv)
        seen["env"] = dict(kw["env"])
        (Path(argv[-1])).mkdir(parents=True)
        (Path(argv[-1]) / ".git").mkdir()
        return type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(core_git.subprocess, "run", fake_run)
    monkeypatch.setattr(core_git.GitRepo, "is_repo", lambda self: True)
    monkeypatch.setattr(core_git.GitRepo, "rev_parse", lambda self, *a, **k: "abc123")
    core_git.clone_repo("https://github.com/acme/Calc.git", tmp_path / "dest", auth_header=header)
    assert header not in " ".join(seen["argv"]) and "ghs_" not in " ".join(seen["argv"])
    assert (
        seen["env"]["GIT_CONFIG_COUNT"] == "1"
        and seen["env"]["GIT_CONFIG_KEY_0"] == "http.extraheader"
    )
    assert seen["env"]["GIT_CONFIG_VALUE_0"] == header

    # the delivery provider mints the installation's token for the remote
    provider = worker._delivery_credentials(
        {"github": {"installation_id": 78}}, "https://github.com/acme/Calc.git"
    )
    assert provider is not None
    creds = provider.resolve("acme-calc")
    assert creds.remote == "https://github.com/acme/Calc.git" and creds.token.startswith(
        "ghs_token_78_"
    )
    assert "ghs_" not in repr(creds) and worker._delivery_credentials({}, "https://x") is None
    # a read-only installation (77: contents read) gets no delivery credentials at all — the
    # loop fails closed before a branch could be pushed; nor does any remote off the app's host
    assert (
        worker._delivery_credentials(
            {"github": {"installation_id": 77}}, "https://github.com/acme/Calc.git"
        )
        is None
    )
    assert (
        worker._delivery_credentials(
            {"github": {"installation_id": 78}}, "https://evil.example/acme/Calc.git"
        )
        is None
    )
