"""Azure Repos pull requests — the second implementation of delivery's PR seam (ADR-0057).

The factory delivers to a repository hosted on Azure Repos the same way it delivers to
GitHub: the push is git's own (:func:`crb.factory.delivery.git_push_fn`, a one-shot header in
the child's environment, with redirects off — :func:`azure_push_fn`), and the pull request is
opened, commented on and closed through three functions with the same keyword-only
signatures as the GitHub ones. ``deliver`` and
``close_pull_request`` do not know which forge they talk to.

Azure DevOps's Git REST API (``api-version=7.1``) is reached with stdlib :mod:`urllib`, and
the ``urlopen`` it uses is injectable so every test is hermetic. The personal access token
travels only in an ``Authorization: Basic`` header (empty user name, the token as password):
never in a URL, never in a request body, and never in an error — every error text passes
through :func:`crb.core.redact.redact` and then has the token and its base64 forms replaced,
because the redactor has no shape for an Azure DevOps token.

A second POST for the same source and target branch is refused by Azure with 409 (an active
pull request already exists). The open then looks the active one up and adopts it only when
exactly one matches; it never posts again. Azure caps a description at 4000 characters, so a
longer evidence summary is cut at a line boundary, an open fence is closed, and one line says
the full summary is in the evidence pack (:func:`cap_description`).

Navigation
----------
What it is:   The Azure Repos client for factory delivery: open, comment on and abandon a
              pull request, with the same signatures as the GitHub seam.
What it does: Parses the remote (:func:`crb.factory.delivery.parse_azure_remote`; anything
              but an https Azure DevOps Services remote is refused), POSTs the pull request
              with ``refs/heads/`` source and target refs and a description capped at 4000
              characters, adopts the one active pull request on a 409, posts a comment as a
              new thread, and closes by commenting then PATCHing ``status: abandoned``.
How:          ``_call`` builds one ``urllib.request.Request`` with a Basic header and JSON
              body, opens it through the injected ``urlopen`` and scrubs any refusal;
              ``azure_open_pr_fn`` / ``azure_comment_pr_fn`` / ``azure_close_pr_fn`` are the
              seams; ``cap_description`` walks the fences line by line.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0057-azure-repos-pr-delivery.md (this seam, the tracker token, the
              same-organisation rule), docs/adr/0021-factory-review-before-delivery.md (only an
              accepted build is delivered; a later non-accept closes the pull request)
Works with:   src/crb/factory/delivery.py (the seam signatures, ``GitCredentials`` and the
              remote parser), src/crb/core/redact.py (every error text),
              src/crb/server/worker.py (wires these seams when the switch is on),
              src/crb/intake/ado.py (attaches the pull request to the ticket)
Tested by:    tests/test_factory_delivery_azure.py
Touch when:   onboarding a repository on Azure DevOps Server, over SSH or in another
              organisation (each refused today — ADR-0057 gaps); Azure changes the pull request
              REST shapes; NEVER put the token in a URL or let an error carry it.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from crb.core.git import GitRepo
from crb.core.redact import redact
from crb.factory.delivery import (
    AzureRepo,
    DeliveryError,
    GitCredentials,
    git_push_fn,
    parse_azure_remote,
)

#: The Azure DevOps REST version every call names.
API_VERSION = "7.1"
#: Azure DevOps's limit on a pull request description, in characters.
DESCRIPTION_LIMIT = 4000
#: The line a cut description ends with.
CUT_NOTE = (
    "_This description was cut at Azure DevOps's 4000-character limit; the full summary is in "
    "the evidence pack._"
)
#: How much of a refusal's body an error keeps.
_ERROR_BODY = 500

#: ``urlopen(request, timeout=…)`` — :func:`urllib.request.urlopen` unless a test injects one.
UrlOpen = Callable[..., Any]


class AzureReposError(DeliveryError):
    """Azure Repos refused a call; ``status`` is the HTTP code (0 when unreachable)."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _target(remote: str) -> AzureRepo:
    repo = parse_azure_remote(remote)
    if repo is None:
        raise DeliveryError(
            "not an https Azure Repos remote (dev.azure.com/{org}/{project}/_git/{repo} or "
            "{org}.visualstudio.com/{project}/_git/{repo}): refused"
        )
    return repo


def parse_azure_pr_url(url: str) -> tuple[AzureRepo, int] | None:
    """``(repository, number)`` of an Azure Repos pull request address
    (``…/{project}/_git/{repo}/pullrequest/{n}``), or ``None`` for any other address."""
    head, sep, tail = url.strip().rstrip("/").rpartition("/pullrequest/")
    if not sep or not (tail.isascii() and tail.isdigit()) or int(tail) <= 0:
        return None
    repo = parse_azure_remote(head)
    return (repo, int(tail)) if repo is not None else None


def _basic(token: str) -> str:
    return base64.b64encode(f":{token}".encode()).decode("ascii")


def _scrub(text: str, credentials: GitCredentials) -> str:
    """``text`` with no trace of the token: redacted, then the token and every base64 form a
    header could carry replaced, then cut to :data:`_ERROR_BODY` characters."""
    out = redact(text)
    token = credentials.token
    for secret in (
        token,
        _basic(token),
        base64.b64encode(f"{credentials.username}:{token}".encode()).decode("ascii"),
    ):
        out = out.replace(secret, "[REDACTED]")
    return out[:_ERROR_BODY]


def _url(base: str, path: str, **query: str) -> str:
    params = urllib.parse.urlencode({**query, "api-version": API_VERSION})
    return f"{base}{path}?{params}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect: urllib would copy the ``Authorization`` header to whatever
    host a 3xx names, and turn a redirected POST into a GET."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


#: The default opener: a 3xx is an :class:`AzureReposError` with its status, never followed.
_OPENER = urllib.request.build_opener(_NoRedirect())


def _call(
    url: str,
    credentials: GitCredentials,
    *,
    what: str,
    timeout: int,
    urlopen: UrlOpen | None,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One authenticated call to the Azure DevOps Git REST API; the decoded JSON object, or
    an :class:`AzureReposError` naming ``what`` and the scrubbed refusal."""
    req = urllib.request.Request(  # noqa: S310 — https URL built from a parsed Azure remote
        url,
        data=None if payload is None else json.dumps(dict(payload)).encode("utf-8"),
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {_basic(credentials.token)}",
            "Content-Type": "application/json",
        },
    )
    opener = urlopen or _OPENER.open
    try:
        with opener(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body = _scrub(e.read().decode("utf-8", "replace"), credentials)
        raise AzureReposError(
            f"Azure Repos {what} API returned {e.code}: {body}", status=e.code
        ) from None
    except urllib.error.URLError as e:
        reason = _scrub(str(e.reason), credentials)
        raise AzureReposError(f"Azure Repos {what} API unreachable: {reason}") from None
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        raise AzureReposError(f"Azure Repos {what} API answered with no JSON object") from None
    if not isinstance(data, Mapping):
        # ``null`` or ``[]`` is not an answer to a call that returns an object: refused, so a
        # caller never records a comment or a close Azure did not confirm
        raise AzureReposError(f"Azure Repos {what} API answered with no JSON object")
    return dict(data)


def cap_description(body: str, limit: int = DESCRIPTION_LIMIT) -> str:
    """``body`` unchanged when it fits Azure's limit; otherwise cut at the last line boundary
    that leaves room, an open fence closed, and :data:`CUT_NOTE` as the last line — never
    more than ``limit`` characters."""
    if len(body) <= limit:
        return body
    budget = limit - len(CUT_NOTE) - 2
    kept: list[str] = []
    used = 0
    for line in body.split("\n"):
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    while True:
        fence = _open_fence(kept)
        closing = f"\n{fence}" if fence else ""
        if used + len(closing) <= budget or not kept:
            break
        used -= len(kept.pop()) + 1
    head = "\n".join(kept)
    return f"{head}{closing}\n\n{CUT_NOTE}" if head else CUT_NOTE


def _open_fence(lines: list[str]) -> str:
    """The fence of a code block ``lines`` leave open (CommonMark: closed by a line of the same
    character at least as long, and nothing else), or ``""``."""
    fence = ""
    for line in lines:
        s = line.strip()
        run = len(s) - len(s.lstrip("`"))
        if not fence:
            if run >= 3:
                fence = "`" * run
        elif run >= len(fence) and s == "`" * run:
            fence = ""
    return fence


def _ref(branch: str) -> str:
    b = branch.strip()
    return b if b.startswith("refs/heads/") else f"refs/heads/{b}"


def _pr_address(repo: AzureRepo, data: Mapping[str, Any]) -> tuple[str, int]:
    """The pull request's web address and number. Azure's ``repository.webUrl`` is used only
    when it names the same repository as the remote; otherwise the address is built from it."""
    number = data.get("pullRequestId")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise DeliveryError("Azure Repos pull request response has no pullRequestId")
    web = str((data.get("repository") or {}).get("webUrl") or "")
    said = parse_azure_remote(web)
    base = said.web_url if said is not None and said.key == repo.key else repo.web_url
    return f"{base}/pullrequest/{number}", number


#: ``azure_open_pr_fn(*, remote, branch, base, title, body, credentials)`` — opens the pull
#: request (or adopts the one active pull request on the same branches).
def azure_open_pr_fn(
    *,
    remote: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    credentials: GitCredentials,
    timeout: int = 30,
    urlopen: UrlOpen | None = None,
) -> tuple[str, int]:
    """Open ``branch -> base`` on the Azure Repos repository ``remote`` names. On 409 the one
    active pull request with the same source and target is adopted; none or more than one is a
    :class:`DeliveryError`. The POST is never sent twice."""
    repo = _target(remote)
    source, target = _ref(branch), _ref(base)
    try:
        data = _call(
            _url(repo.api_base, "/pullrequests"),
            credentials,
            what="pull requests",
            timeout=timeout,
            urlopen=urlopen,
            method="POST",
            payload={
                "sourceRefName": source,
                "targetRefName": target,
                "title": title,
                "description": cap_description(body),
            },
        )
    except AzureReposError as e:
        if e.status != 409:
            raise
        data = _adopt_active(repo, source, target, credentials, timeout=timeout, urlopen=urlopen)
    return _pr_address(repo, data)


def _adopt_active(
    repo: AzureRepo,
    source: str,
    target: str,
    credentials: GitCredentials,
    *,
    timeout: int,
    urlopen: UrlOpen | None,
) -> dict[str, Any]:
    found = _call(
        _url(
            repo.api_base,
            "/pullrequests",
            **{
                "searchCriteria.sourceRefName": source,
                "searchCriteria.targetRefName": target,
                "searchCriteria.status": "active",
            },
        ),
        credentials,
        what="pull requests",
        timeout=timeout,
        urlopen=urlopen,
    )
    rows = [
        dict(r)
        for r in (found.get("value") or [])
        if isinstance(r, Mapping)
        and r.get("sourceRefName") == source
        and r.get("targetRefName") == target
    ]
    if len(rows) != 1:
        raise DeliveryError(
            f"Azure Repos refused the pull request (409) and {len(rows)} active pull requests "
            f"match {source} -> {target}: none adopted"
        )
    return rows[0]


#: ``push_fn(repo, *, branch, refspec, credentials, expected=None)`` for Azure Repos.
def azure_push_fn(
    repo: GitRepo,
    *,
    branch: str,
    refspec: str,
    credentials: GitCredentials,
    expected: str | None = None,
) -> None:
    """:func:`crb.factory.delivery.git_push_fn` with redirects off for the remote: the
    tracker's long-lived token goes to no host a redirect names, as on clone and fetch."""
    git_push_fn(
        repo,
        branch=branch,
        refspec=refspec,
        credentials=credentials,
        expected=expected,
        follow_redirects=False,
    )


#: ``azure_comment_pr_fn(*, remote, pr_number, body, credentials)`` — posts a comment as a
#: new thread on the pull request.
def azure_comment_pr_fn(
    *,
    remote: str,
    pr_number: int,
    body: str,
    credentials: GitCredentials,
    timeout: int = 30,
    urlopen: UrlOpen | None = None,
) -> None:
    """Post ``body`` on pull request ``pr_number`` as a new active comment thread."""
    repo = _target(remote)
    if pr_number <= 0:
        raise DeliveryError(f"cannot comment on pull request number {pr_number!r}")
    _call(
        _url(repo.api_base, f"/pullrequests/{pr_number}/threads"),
        credentials,
        what="threads",
        timeout=timeout,
        urlopen=urlopen,
        method="POST",
        payload={
            "comments": [{"parentCommentId": 0, "content": body, "commentType": 1}],
            "status": 1,
        },
    )


#: ``azure_close_pr_fn(*, remote, pr_number, body, credentials)`` — comments, then abandons
#: the pull request (never completes it, never deletes the branch).
def azure_close_pr_fn(
    *,
    remote: str,
    pr_number: int,
    body: str,
    credentials: GitCredentials,
    timeout: int = 30,
    urlopen: UrlOpen | None = None,
) -> None:
    """Comment ``body`` on pull request ``pr_number``, then set it ``abandoned`` (Azure's
    close; a person may reactivate it). The comment goes first so a reader sees why."""
    repo = _target(remote)
    if pr_number <= 0:
        raise DeliveryError(f"cannot close pull request number {pr_number!r}")
    azure_comment_pr_fn(
        remote=remote,
        pr_number=pr_number,
        body=body,
        credentials=credentials,
        timeout=timeout,
        urlopen=urlopen,
    )
    _call(
        _url(repo.api_base, f"/pullrequests/{pr_number}"),
        credentials,
        what="pull requests",
        timeout=timeout,
        urlopen=urlopen,
        method="PATCH",
        payload={"status": "abandoned"},
    )


__all__ = [
    "API_VERSION",
    "CUT_NOTE",
    "DESCRIPTION_LIMIT",
    "AzureReposError",
    "azure_close_pr_fn",
    "azure_comment_pr_fn",
    "azure_open_pr_fn",
    "azure_push_fn",
    "cap_description",
    "parse_azure_pr_url",
]
