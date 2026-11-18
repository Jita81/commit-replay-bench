"""crb.factory.delivery_azure — Azure Repos pull requests through delivery's own seam (ADR-0057).

Navigation
----------
What it is:   The test suite of the Azure Repos delivery seam and of the Azure remote parser
              that keys a delivery's repository as ``org/project/repo``.
What it does: Pins which remotes parse (https ``dev.azure.com`` with or without a user part,
              ``{org}.visualstudio.com``) and which are refused; that ``repository_of`` keys an
              Azure remote by organisation, project and repository and is unchanged for GitHub;
              the open / comment / close requests and their bodies; that a 409 adopts the one
              active pull request with one POST and refuses none or two; the 4000-character
              description cap; that the token is in the header only, never in a URL, request
              body, error, ``repr`` or result row; and that a re-delivery or close through
              another repository of the same project is refused before the forge is called.
How:          A scripted ``urlopen`` records every request and answers from a list (an
              ``HTTPError`` for a refusal); the build comes from ``test_factory_build``'s
              harness; nothing reaches the network.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0057-azure-repos-pr-delivery.md (the seam under test)
Works with:   src/crb/factory/delivery_azure.py (under test), src/crb/factory/delivery.py
              (the parser, ``deliver`` and ``close_pull_request``), tests/test_factory_build.py
              (the harness), tests/test_factory_delivery.py (the GitHub cases these mirror)
Tested by:    tests/test_factory_delivery_azure.py
Touch when:   never for a new repository; the Azure REST shapes change (record the real
              answers here first), or the parser accepts another remote form.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from crb.factory import delivery as dv
from crb.factory import delivery_azure as az
from test_factory_build import Harness, harness, multiply_item
from test_factory_delivery import Seams, _clean_build

__all__ = ["harness"]

TOKEN = "azpat" + "q" * 47
B64 = base64.b64encode(f":{TOKEN}".encode()).decode("ascii")
REMOTE = "https://acme@dev.azure.com/acme/Payments/_git/ledger"
WEB = "https://dev.azure.com/acme/Payments/_git/ledger"
API = "https://dev.azure.com/acme/Payments/_apis/git/repositories/ledger"
SIBLING = "https://dev.azure.com/acme/Payments/_git/billing"


def _creds(remote: str = REMOTE) -> dv.GitCredentials:
    return dv.GitCredentials(remote=remote, token=TOKEN)


def _pr(number: int, *, source: str = "refs/heads/crb/i-1-x", web: str = WEB) -> dict[str, Any]:
    return {
        "pullRequestId": number,
        "sourceRefName": source,
        "targetRefName": "refs/heads/develop",
        "artifactId": f"vstfs:///Git/PullRequestId/p-1%2Fr-1%2F{number}",
        "repository": {"id": "r-1", "webUrl": web, "project": {"id": "p-1"}},
    }


@dataclass
class Forge:
    """A scripted ``urlopen``: records each request, answers ``(status, body)`` in order."""

    answers: list[tuple[int, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, req: Any, timeout: int = 0) -> Any:
        self.calls.append(
            {
                "method": req.get_method(),
                "url": req.full_url,
                "auth": req.get_header("Authorization"),
                "data": req.data,
            }
        )
        status, body = self.answers.pop(0)
        raw = (body if isinstance(body, str) else json.dumps(body)).encode()
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "refused", {}, io.BytesIO(raw))  # type: ignore[arg-type]
        return _Resp(raw)


class _Resp:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self) -> bytes:
        return self.raw


def _open(forge: Forge, **over: Any) -> tuple[str, int]:
    kw: dict[str, Any] = {
        "remote": REMOTE,
        "branch": "crb/i-1-x",
        "base": "develop",
        "title": "Add multiply",
        "body": "evidence",
        "credentials": _creds(),
        "urlopen": forge,
    }
    kw.update(over)
    return az.azure_open_pr_fn(**kw)


# --- the remote ----------------------------------------------------------------------


def test_parse_azure_remote_accepts_dev_azure_userinfo_and_visualstudio_forms() -> None:
    plain = dv.parse_azure_remote(WEB)
    assert plain == dv.AzureRepo("dev.azure.com", "acme", "Payments", "ledger")
    assert dv.parse_azure_remote(REMOTE) == plain
    assert plain.web_url == WEB and plain.api_base == API
    assert dv.parse_azure_remote(REMOTE).web_url == WEB  # the user part is dropped
    spaced = dv.parse_azure_remote("https://dev.azure.com/acme/My%20Project/_git/the%20repo")
    assert spaced is not None and (spaced.project, spaced.repo) == ("My Project", "the repo")
    assert spaced.web_url == "https://dev.azure.com/acme/My%20Project/_git/the%20repo"
    legacy = dv.parse_azure_remote("https://acme.visualstudio.com/Payments/_git/ledger")
    assert legacy == dv.AzureRepo("acme.visualstudio.com", "acme", "Payments", "ledger")
    assert legacy.api_base == (
        "https://acme.visualstudio.com/Payments/_apis/git/repositories/ledger"
    )
    assert dv.azure_organisation("https://dev.azure.com/ACME") == "acme"
    assert dv.azure_organisation("https://acme.visualstudio.com/") == "acme"
    assert az.parse_azure_pr_url(f"{WEB}/pullrequest/12") == (plain, 12)
    assert az.parse_azure_pr_url("https://github.com/acme/calc/pull/12") is None
    assert az.parse_azure_pr_url(f"{WEB}/pullrequest/0") is None


@pytest.mark.parametrize(
    "remote",
    [
        "git@ssh.dev.azure.com:v3/acme/Payments/ledger",
        "ssh://git@ssh.dev.azure.com/v3/acme/Payments/ledger",
        "http://dev.azure.com/acme/Payments/_git/ledger",
        "https://github.com/acme/calc.git",
        "https://dev.azure.com.evil.example/acme/Payments/_git/ledger",
        "https://evil.example/dev.azure.com/acme/Payments/_git/ledger",
        "https://dev.azure.com:8443/acme/Payments/_git/ledger",
        "https://dev.azure.com/acme/Payments/_git/ledger?path=/x",
        "https://dev.azure.com/acme/Payments/ledger",
        "https://dev.azure.com/acme/_git/ledger",
        "https://dev.azure.com/acme/Payments/_git/ledger/extra",
        "https://a.b.visualstudio.com/Payments/_git/ledger",
        # a decoded name that is no Azure DevOps name: a slash, a backslash, a control
        # character, or a dot segment (the API address and git's remote would disagree)
        "https://dev.azure.com/acme/a%2Fb/_git/c",
        "https://dev.azure.com/acme/a/_git/b%2Fc",
        "https://dev.azure.com/acme/a%5Cb/_git/c",
        "https://dev.azure.com/acme/a%0Ab/_git/c",
        "https://dev.azure.com/acme/../_git/ledger",
        "https://dev.azure.com/acme/%2E%2E/_git/ledger",
        "https://dev.azure.com/acme/Payments/_git/.",
        "https://dev.azure.com/../Payments/_git/ledger",
        "https://dev.azure.com/a%2Fb/Payments/_git/ledger",
        "",
    ],
)
def test_parse_azure_remote_refuses_ssh_http_and_foreign_hosts(remote: str) -> None:
    assert dv.parse_azure_remote(remote) is None
    assert dv.azure_repository(remote) == ""


def test_two_remotes_whose_decoded_names_join_alike_never_share_a_key() -> None:
    """``a%2Fb/_git/c`` and ``a/_git/b%2Fc`` both decoded to ``acme/a/b/c``: an operator
    could re-link a row from one to the other and the factory would then comment on, or
    abandon, the first repository's pull request number in the second."""
    first = "https://dev.azure.com/acme/a%2Fb/_git/c"
    second = "https://dev.azure.com/acme/a/_git/b%2Fc"
    assert dv.repository_of(first) != dv.repository_of(second)
    assert "acme/a/b/c" not in {dv.repository_of(first), dv.repository_of(second)}
    assert dv.azure_organisation("https://dev.azure.com/..") == ""


def test_repository_of_azure_remote_is_org_project_repo() -> None:
    assert dv.repository_of(WEB) == "acme/payments/ledger"
    assert dv.repository_of(REMOTE) == "acme/payments/ledger"
    assert dv.repository_of("https://acme.visualstudio.com/Payments/_git/Ledger") == (
        "acme/payments/ledger"
    )
    # two repositories of one project no longer share a key (it was "acme/payments")
    assert dv.repository_of(SIBLING) == "acme/payments/billing"


@pytest.mark.parametrize(
    ("remote", "today"),
    [  # repository_of's answers on main before the Azure parser existed
        ("https://github.com/acme/calc.git", "acme/calc"),
        ("https://github.com/Acme/Calc", "acme/calc"),
        ("git@github.com:acme/calc.git", "acme/calc"),
        ("ssh://git@github.com/acme/calc.git", "acme/calc"),
        ("https://ghe.example.com/team/svc.git", "team/svc"),
        ("https://x-access-token@github.com/acme/calc", "acme/calc"),
        ("acme/calc", "acme/calc"),
        ("https://github.com/only", ""),
        ("", ""),
    ],
)
def test_repository_of_github_remotes_unchanged(remote: str, today: str) -> None:
    assert dv.repository_of(remote) == today


# --- open, comment, close ------------------------------------------------------------


def test_open_pr_posts_refs_and_returns_web_url() -> None:
    forge = Forge([(201, _pr(12))])
    assert _open(forge) == (f"{WEB}/pullrequest/12", 12)
    (call,) = forge.calls
    assert call["method"] == "POST"
    assert call["url"] == f"{API}/pullrequests?api-version=7.1"
    assert json.loads(call["data"]) == {
        "sourceRefName": "refs/heads/crb/i-1-x",
        "targetRefName": "refs/heads/develop",
        "title": "Add multiply",
        "description": "evidence",
    }
    # a webUrl naming another repository is not believed: the address comes from the remote
    other = Forge([(201, _pr(13, web="https://dev.azure.com/evil/x/_git/y"))])
    assert _open(other) == (f"{WEB}/pullrequest/13", 13)


def test_open_pr_sends_token_in_header_only() -> None:
    forge = Forge([(201, _pr(12))])
    _open(forge)
    (call,) = forge.calls
    assert call["auth"] == f"Basic {B64}"
    for secret in (TOKEN, B64, "acme@"):
        assert secret not in call["url"]
    assert TOKEN not in call["data"].decode() and B64 not in call["data"].decode()


def test_open_pr_409_adopts_the_single_active_pr_with_one_post() -> None:
    exists = {"message": "TF401179: An active pull request for the source and target exists."}
    forge = Forge([(409, exists), (200, {"value": [_pr(9)], "count": 1})])
    assert _open(forge) == (f"{WEB}/pullrequest/9", 9)
    assert [c["method"] for c in forge.calls] == ["POST", "GET"]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(forge.calls[1]["url"]).query)
    assert query == {
        "searchCriteria.sourceRefName": ["refs/heads/crb/i-1-x"],
        "searchCriteria.targetRefName": ["refs/heads/develop"],
        "searchCriteria.status": ["active"],
        "api-version": ["7.1"],
    }


@pytest.mark.parametrize(
    "rows",
    [[], [_pr(9), _pr(10)], [_pr(9, source="refs/heads/crb/other")]],
    ids=["none", "two", "another-branch"],
)
def test_open_pr_409_with_zero_or_two_matches_is_refused(rows: list[dict[str, Any]]) -> None:
    forge = Forge([(409, {"message": "TF401179"}), (200, {"value": rows})])
    with pytest.raises(dv.DeliveryError, match="none adopted"):
        _open(forge)
    assert [c["method"] for c in forge.calls] == ["POST", "GET"]


def _fences_balanced(text: str) -> bool:
    return az._open_fence(text.split("\n")) == ""


@pytest.mark.parametrize("fence", ["```", "````"])
def test_long_description_capped_at_4000_with_fence_closed_and_note(fence: str) -> None:
    body = "\n".join(["## Evidence", f"{fence}text", *(["x" * 79] * 80), fence, "tail"])
    assert len(body) > 4000
    out = az.cap_description(body)
    assert len(out) <= 4000
    assert out.endswith(az.CUT_NOTE) and "4000" in az.CUT_NOTE and "evidence pack" in az.CUT_NOTE
    head = out[: -len(az.CUT_NOTE)].rstrip("\n")
    assert head.endswith(f"\n{fence}")  # the open block is closed
    assert body.startswith(head[: -len(fence) - 1] + "\n")  # cut at a line boundary
    assert _fences_balanced(out)
    forge = Forge([(201, _pr(12))])
    _open(forge, body=body)
    assert json.loads(forge.calls[0]["data"])["description"] == out


def test_short_description_unchanged() -> None:
    assert az.cap_description("evidence") == "evidence"
    exact = "y" * 4000
    assert az.cap_description(exact) == exact
    assert az.cap_description("z" * 5000) == az.CUT_NOTE  # one line too long for the limit


def test_comment_posts_a_thread() -> None:
    forge = Forge([(200, {"id": 1})])
    az.azure_comment_pr_fn(
        remote=REMOTE, pr_number=12, body="note", credentials=_creds(), urlopen=forge
    )
    (call,) = forge.calls
    assert call["method"] == "POST"
    assert call["url"] == f"{API}/pullrequests/12/threads?api-version=7.1"
    assert json.loads(call["data"]) == {
        "comments": [{"parentCommentId": 0, "content": "note", "commentType": 1}],
        "status": 1,
    }
    for bad in (0, -1):
        with pytest.raises(dv.DeliveryError):
            az.azure_comment_pr_fn(
                remote=REMOTE, pr_number=bad, body="n", credentials=_creds(), urlopen=forge
            )
    assert len(forge.calls) == 1


def test_close_comments_then_abandons() -> None:
    forge = Forge([(200, {"id": 1}), (200, {"pullRequestId": 12, "status": "abandoned"})])
    az.azure_close_pr_fn(
        remote=REMOTE, pr_number=12, body="rejected", credentials=_creds(), urlopen=forge
    )
    assert [(c["method"], c["url"]) for c in forge.calls] == [
        ("POST", f"{API}/pullrequests/12/threads?api-version=7.1"),
        ("PATCH", f"{API}/pullrequests/12?api-version=7.1"),
    ]
    assert json.loads(forge.calls[1]["data"]) == {"status": "abandoned"}


# --- the token -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "answers",
    [
        [(400, f"bad request for {TOKEN} with Basic {B64}")],
        [(409, {"message": "TF401179"}), (500, {"message": f"server echoed {TOKEN} / {B64}"})],
        [(401, "x" * 2000 + TOKEN)],
    ],
    ids=["400", "409-then-search-fails", "long-body"],
)
def test_error_text_never_carries_the_token(answers: list[tuple[int, Any]]) -> None:
    with pytest.raises(dv.DeliveryError) as caught:
        _open(Forge(list(answers)))
    text = str(caught.value)
    assert TOKEN not in text and B64 not in text
    assert "Azure Repos" in text and len(text) < 600
    assert caught.value.__cause__ is None  # no chained HTTPError carries the body


def test_token_absent_from_every_request_body() -> None:
    forge = Forge(
        [
            (409, {"message": "TF401179"}),
            (200, {"value": [_pr(9)]}),
            (200, {"id": 1}),
            (200, {"id": 2}),
            (200, {"pullRequestId": 9}),
        ]
    )
    _open(forge)
    kw = {"remote": REMOTE, "pr_number": 9, "credentials": _creds(), "urlopen": forge}
    az.azure_comment_pr_fn(body="moved", **kw)
    az.azure_close_pr_fn(body="closed", **kw)
    assert len(forge.calls) == 5
    for call in forge.calls:
        sent = (call["data"] or b"").decode() + call["url"]
        assert TOKEN not in sent and B64 not in sent


def test_token_absent_from_repr_and_result_row(harness: Harness) -> None:
    forge = Forge([(201, _pr(12))])
    seams = Seams()
    build = _clean_build(harness)
    try:
        res = dv.deliver(
            harness.repo.repo,
            multiply_item(),
            build,
            creds=dv.StaticProvider(_creds()),
            push_fn=seams.push,
            open_pr_fn=lambda **kw: az.azure_open_pr_fn(urlopen=forge, **kw),
            target_default_branch="develop",
            verdict="accept",
        )
    finally:
        build.close()
    assert (res.pr_url, res.pr_number) == (f"{WEB}/pullrequest/12", 12)
    assert res.repository == "acme/payments/ledger"
    for text in (repr(_creds()), repr(res), json.dumps(res.to_dict()), str(_creds().to_dict())):
        assert TOKEN not in text and B64 not in text


def test_recorded_body_hash_is_the_full_body_not_the_cut_description(harness: Harness) -> None:
    """ADR-0057: Azure DevOps keeps 4000 characters of a description, so the seam cuts it;
    the ledger's ``body_sha256`` is still the hash of the whole evidence summary built."""
    forge = Forge([(201, _pr(12))])
    seams = Seams()
    build = _clean_build(harness)
    licence = "licence detail " * 400  # the body passes Azure's 4000-character limit
    try:
        full = dv.pr_body(multiply_item(), build, licence_line=licence)
        res = dv.deliver(
            harness.repo.repo,
            multiply_item(),
            build,
            creds=dv.StaticProvider(_creds()),
            push_fn=seams.push,
            open_pr_fn=lambda **kw: az.azure_open_pr_fn(urlopen=forge, **kw),
            target_default_branch="develop",
            verdict="accept",
            licence_line=licence,
        )
    finally:
        build.close()
    sent = json.loads(forge.calls[0]["data"])["description"]
    assert len(full) > az.DESCRIPTION_LIMIT >= len(sent) and sent != full
    assert res.body_sha256 == dv.sha256_text(full) != dv.sha256_text(sent)


# --- a recorded pull request is only reused in its own repository ----------------------


def _earlier(**over: Any) -> dv.DeliveryResult:
    """An earlier run's delivery of ``I-1`` to ``acme/Payments/ledger``, pull request 5."""
    fields: dict[str, Any] = {
        "item_id": "I-1",
        "branch": "crb/i-1-add-multiply-to-calc",
        "base": "main",
        "commit_sha": "c" * 40,
        "pr_url": f"{WEB}/pullrequest/5",
        "pr_number": 5,
        "pack_hash": "p" * 64,
        "body_sha256": "",
        "repository": dv.repository_of(REMOTE),
    }
    fields.update(over)
    return dv.DeliveryResult(**fields)


def test_redelivery_into_another_repo_of_the_same_project_is_refused(harness: Harness) -> None:
    """Under the old ``owner/name`` key both repositories were ``acme/payments``: pull
    request 5 of ``ledger`` would have been pushed to and commented on in ``billing``."""
    seams = Seams()
    build = _clean_build(harness)
    try:
        with pytest.raises(dv.DeliveryError, match=r"acme/payments/ledger.*acme/payments/billing"):
            dv.deliver(
                harness.repo.repo,
                multiply_item(),
                build,
                creds=dv.StaticProvider(_creds(SIBLING)),
                push_fn=seams.push,
                open_pr_fn=seams.open_pr,
                comment_pr_fn=seams.comment_pr,
                target_default_branch="main",
                previous=_earlier(),
                verdict="accept",
            )
    finally:
        build.close()
    assert seams.pushes == [] and seams.prs == [] and seams.comments == []


def test_close_of_a_pr_recorded_in_another_azure_repo_is_refused() -> None:
    forge = Forge([])
    with pytest.raises(dv.DeliveryError, match=r"acme/payments/ledger.*acme/payments/billing"):
        dv.close_pull_request(
            _earlier(),
            verdict="reject",
            reason="x",
            creds=dv.StaticProvider(_creds(SIBLING)),
            close_pr_fn=lambda **kw: az.azure_close_pr_fn(urlopen=forge, **kw),
            repo_id="/repos/billing",
        )
    assert forge.calls == []


def test_a_redirect_is_refused_and_the_token_never_reaches_the_second_host() -> None:
    """The default opener follows no 3xx: urllib would otherwise copy the Authorization
    header to the host the redirect names."""
    import http.server
    import threading

    seen: list[tuple[str, str | None]] = []

    def serve(location: str | None) -> http.server.HTTPServer:
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                seen.append((self.server.name, self.headers.get("Authorization")))  # type: ignore[attr-defined]
                if location:
                    self.send_response(302)
                    self.send_header("Location", location)
                else:
                    self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a: object) -> None:
                return None

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    other = serve(None)
    other.name = "other"  # type: ignore[attr-defined]
    first = serve(f"http://127.0.0.1:{other.server_port}/elsewhere")
    first.name = "first"  # type: ignore[attr-defined]
    try:
        with pytest.raises(az.AzureReposError) as err:
            az._call(
                f"http://127.0.0.1:{first.server_port}/x",
                _creds(),
                what="probe",
                timeout=5,
                urlopen=None,
            )
    finally:
        first.shutdown()
        other.shutdown()
    assert err.value.status == 302
    assert [name for name, _ in seen] == ["first"]
    assert TOKEN not in str(err.value)


@pytest.mark.parametrize("body", ["null", "[]", '"text"', "", "  "])
def test_a_non_object_answer_is_refused_not_read_as_empty(body: str) -> None:
    """Nothing, ``null`` or ``[]`` is no confirmation: the comment is refused, so a caller never
    records one Azure did not answer for."""
    with pytest.raises(az.AzureReposError, match="no JSON object"):
        az.azure_comment_pr_fn(
            remote=REMOTE,
            pr_number=12,
            body="n",
            credentials=_creds(),
            urlopen=Forge([(200, body)]),
        )


def test_azure_push_turns_redirects_off_for_the_remote() -> None:
    """The push carries the tracker token, so git is told not to follow a redirect for that
    remote, as on clone and fetch; GitHub's push keeps git's default."""
    calls: list[dict[str, str]] = []

    class _Repo:
        def run(self, *args: str, env: dict[str, str]) -> Any:
            calls.append(env)
            return SimpleNamespace(ok=True, returncode=0, stderr="")

    creds = _creds(WEB)
    az.azure_push_fn(_Repo(), branch="crb/x", refspec="crb/x:crb/x", credentials=creds)  # type: ignore[arg-type]
    dv.git_push_fn(_Repo(), branch="crb/x", refspec="crb/x:crb/x", credentials=creds)  # type: ignore[arg-type]
    pairs = [
        {
            v: env[k.replace("KEY", "VALUE")]
            for k, v in env.items()
            if k.startswith("GIT_CONFIG_KEY_")
        }
        for env in calls
    ]
    assert pairs[0][f"http.{WEB}.followRedirects"] == "false"
    assert f"http.{WEB}.followRedirects" not in pairs[1]
    assert TOKEN not in repr(pairs[0].keys())
