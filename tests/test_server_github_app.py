"""crb.server.github_app + routes/github — the enterprise connection, against a fake GitHub.

Navigation
----------
What it is:   Tests for the GitHub App client and its routes: the app JWT is RS256 over
              the app id with a ten-minute life; installation tokens are minted with the
              JWT, cached, and refreshed near expiry; installations and repositories are
              read with the right credential; GitHub's refusals become ``GitHubAppError``.
              The routes: unconfigured = 404 ``github_app_not_configured`` (and ``GET
              /github/app`` says ``configured: false`` rather than 404); the setup callback
              verifies the installation with the app's credential before recording it;
              sync marks vanished installations suspended; the picker lists with a
              suggested config and marks already-connected repositories; connect registers
              a linked repository (409 on a second connect, 404 when the installation
              cannot see it, 422 when GitHub reports no language and none is given); a
              config update keeps the link; the worker clones with the token in the
              environment — never argv — and its delivery provider mints the token.
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
from crb.server.github_app import GitHubApp, GitHubAppError, suggest_config
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


class FakeGitHub:
    """A minimal GitHub: records every request; serves installations, tokens, repos."""

    def __init__(self, public_key: Any) -> None:
        self.public_key = public_key
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.tokens_minted = 0
        self.installations: list[dict[str, Any]] = [INSTALLATION, INSTALLATION_RW]

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
        if path.startswith("/repos/"):
            assert bearer.startswith("ghs_token_")
            full = path.removeprefix("/repos/")
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
