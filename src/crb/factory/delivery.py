"""Delivery — a graded change ships as a BRANCH + PR in the customer's repo, never main.

The factory only ever *proposes*. A clean build is committed on a new branch
``crb/<item_id>-<slug>`` and a pull request is opened against the customer's
default branch; a human on the customer's side reviews and merges. The factory
NEVER pushes to, nor opens a PR against, ``main`` / ``master`` / the configured
default — :func:`assert_not_default_branch` is the hard invariant, checked
before credentials are resolved or the remote is touched, and its test is a
ratchet.

Credentials are BYOK behind :class:`GitCredentialsProvider`. The default is
:class:`NullProvider`, which raises :class:`NoGitCredentialsError` — with no
credentials wired, delivery **fails closed**, never a silent success-looking
no-op. Tokens never reach ``.git/config``: the default push seam passes the
token as a one-shot ``http.extraheader``; the PR seam is GitHub's REST API over
:mod:`urllib` (stdlib). Both are injectable so tests are hermetic; an Azure
DevOps seam plugs in the same way.

The PR body is the evidence summary — belts, pack hash, apparatus, route
decision, RED proof — and a link to the pack. It carries no secrets: every
string passes through :mod:`crb.core.redact`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from crb.core.evidence import sha256_text, utc_now_iso
from crb.core.git import GitError, GitRepo
from crb.core.redact import redact
from crb.factory.backlog import BacklogItem
from crb.factory.build import FACTORY_IDENTITY, BuildResult

DELIVERY_BRANCH_PREFIX = "crb/"

#: Never a valid push destination or PR head, whatever the configured default.
ALWAYS_PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "master"})


class DeliveryError(RuntimeError):
    """A delivery could not be performed safely."""


class DefaultBranchProtectionError(DeliveryError):
    """A delivery would write to / target the default or a protected branch. HARD
    INVARIANT — the ratchet test asserts it can never be relaxed."""


class NoGitCredentialsError(DeliveryError):
    """No BYOK credentials are configured. Delivery fails closed."""


class DeliveryRefused(DeliveryError):
    """The build is not deliverable (not clean, disqualified, no workspace)."""


# ---------------------------------------------------------------------------
# Credentials (BYOK)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitCredentials:
    """A push token for one remote. ``token`` is excluded from ``repr`` and from
    every dict this module emits."""

    remote: str
    token: str = field(repr=False)
    username: str = "x-access-token"

    def __post_init__(self) -> None:
        if not self.remote.strip():
            raise ValueError("credentials need a remote URL")
        if not self.token.strip():
            raise ValueError("credentials need a non-empty token")

    def basic_auth_header(self) -> str:
        raw = f"{self.username}:{self.token}".encode()
        return "Authorization: Basic " + base64.b64encode(raw).decode("ascii")

    def to_dict(self) -> dict[str, Any]:
        return {"remote": self.remote, "username": self.username, "token": "[REDACTED]"}


@runtime_checkable
class GitCredentialsProvider(Protocol):
    def resolve(self, repo: str) -> GitCredentials: ...


class NullProvider:
    """The default: no credentials. ``resolve`` always raises — fail closed."""

    def resolve(self, repo: str) -> GitCredentials:
        raise NoGitCredentialsError(
            f"no git credentials configured for {repo!r} — delivery refused (fail closed)"
        )


class StaticProvider:
    def __init__(self, credentials: GitCredentials) -> None:
        self._creds = credentials

    def resolve(self, repo: str) -> GitCredentials:
        return self._creds


class EnvProvider:
    """Read the token and remote from the environment (``CRB_GIT_TOKEN`` /
    ``CRB_GIT_REMOTE``). Missing either → :class:`NoGitCredentialsError`."""

    def __init__(
        self,
        *,
        token_var: str = "CRB_GIT_TOKEN",  # noqa: S107 — an env VAR NAME, not a secret
        remote_var: str = "CRB_GIT_REMOTE",
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.token_var = token_var
        self.remote_var = remote_var
        self._environ = environ

    def resolve(self, repo: str) -> GitCredentials:
        env = self._environ if self._environ is not None else os.environ
        token = env.get(self.token_var, "").strip()
        remote = env.get(self.remote_var, "").strip()
        if not token or not remote:
            raise NoGitCredentialsError(
                f"{self.token_var} / {self.remote_var} not set — delivery refused (fail closed)"
            )
        return GitCredentials(remote=remote, token=token)


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def _norm_branch(name: str) -> str:
    n = (name or "").strip()
    while n.startswith("refs/heads/"):
        n = n[len("refs/heads/") :]
    return n.strip("/")


def assert_not_default_branch(branch_name: str, target_default_branch: str) -> str:
    """Return the normalised branch when it is safe; raise
    :class:`DefaultBranchProtectionError` when it is empty or resolves
    (case-insensitively, ref-normalised) to the default or a protected branch."""
    branch = _norm_branch(branch_name)
    if not branch:
        raise DefaultBranchProtectionError("delivery branch name is empty — refusing to deliver")
    protected = {b.lower() for b in ALWAYS_PROTECTED_BRANCHES}
    default = _norm_branch(target_default_branch)
    if default:
        protected.add(default.lower())
    if branch.lower() in protected:
        raise DefaultBranchProtectionError(
            f"refusing to deliver to the default/protected branch {branch!r} "
            f"(protected: {sorted(protected)}); delivery only ever opens a NEW branch + PR"
        )
    return branch


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "change"


def delivery_branch_name(item: BacklogItem) -> str:
    return f"{DELIVERY_BRANCH_PREFIX}{item.id}-{slugify(item.title)}"


# ---------------------------------------------------------------------------
# PR body = evidence summary
# ---------------------------------------------------------------------------


def pr_body(
    item: BacklogItem,
    build: BuildResult,
    *,
    pack_link: str = "",
    route_decision: Mapping[str, Any] | None = None,
) -> str:
    belts = build.grade.belts.to_dict()
    proof = build.pack.notes.get("red_proof", {})
    lines = [
        f"## {item.title}",
        "",
        f"Automated proposal from crb factory for backlog item `{item.id}` "
        f"({item.kind}, {item.level}, class `{item.capability_class}`).",
        "",
        "This targets a NEW branch, never the default branch. A human reviews and merges.",
        "",
        "### Evidence",
        "",
        f"- evidence pack: `{build.pack_hash}`" + (f" — {pack_link}" if pack_link else ""),
        f"- grade: **{'clean' if build.clean else 'not clean'}**",
        "- belts: " + ", ".join(f"{k}={v}" for k, v in belts.items()),
        f"- oracle: `{build.oracle.test_path}` sha256 `{build.oracle.test_sha256}` "
        f"(RED at base `{proof.get('base_sha', '')[:12]}`, "
        f"{len(proof.get('failing_ids', []))} failing id(s))",
        f"- oracle commit: `{build.oracle.sha}` on `{build.oracle.branch}`",
        f"- builder: `{build.rung}` trial `{build.trial}`",
        f"- apparatus: `{build.pack.apparatus.apparatus_version}` runner `{build.pack.apparatus.runner}` "
        f"executor `{build.pack.apparatus.executor.get('executor', '')}`",
        f"- ledger row: `{build.row.row_hash if build.row else '(not ledgered)'}`",
    ]
    if route_decision:
        lines.append(
            f"- route: **{route_decision.get('route', '')}** — {route_decision.get('reason', '')} "
            f"(policy `{route_decision.get('policy_version', '')}`)"
        )
    if item.acceptance_criteria:
        lines += ["", "### Acceptance criteria", ""] + [f"- {c}" for c in item.acceptance_criteria]
    lines += ["", f"changed files: {', '.join(f'`{f}`' for f in build.changed_files) or '(none)'}"]
    return redact("\n".join(lines))


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------

#: ``push_fn(repo, *, branch, refspec, credentials)``
PushFn = Callable[..., None]
#: ``open_pr_fn(*, remote, branch, base, title, body, credentials) -> (url, number)``
OpenPrFn = Callable[..., tuple[str, int]]


def git_push_fn(repo: GitRepo, *, branch: str, refspec: str, credentials: GitCredentials) -> None:
    """Push ``refspec`` (``branch:branch``, never ``HEAD``) with a one-shot auth
    header. The token is never written to ``.git/config``."""
    src, _, dst = refspec.partition(":")
    if src != branch or dst != branch:
        raise DefaultBranchProtectionError(f"refspec {refspec!r} must be {branch}:{branch}")
    res = repo.run(
        "-c",
        f"http.{credentials.remote}.extraheader={credentials.basic_auth_header()}",
        "push",
        "--force-with-lease",
        credentials.remote,
        refspec,
    )
    if not res.ok:
        raise DeliveryError(
            f"git push of {branch!r} failed rc={res.returncode}: {redact(res.stderr)[:400]}"
        )


def owner_repo_from_remote(remote: str) -> tuple[str, str]:
    r = remote.strip()
    path = (
        r.split(":", 1)[1] if r.startswith("git@") and ":" in r else urllib.parse.urlparse(r).path
    )
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise DeliveryError(f"cannot parse owner/repo from remote {remote!r}")
    return parts[0], parts[1]


def github_open_pr_fn(
    *,
    remote: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    credentials: GitCredentials,
    api_base: str = "https://api.github.com",
    timeout: int = 30,
) -> tuple[str, int]:
    """Open ``branch -> base`` via the GitHub pulls API (stdlib urllib)."""
    owner, name = owner_repo_from_remote(remote)
    url = f"{api_base}/repos/{owner}/{name}/pulls"
    payload = json.dumps(
        {"title": title, "head": branch, "base": base, "body": body, "maintainer_can_modify": True}
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — https API URL built from a parsed remote
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {credentials.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise DeliveryError(
            f"GitHub pulls API returned {e.code}: {redact(e.read().decode('utf-8', 'replace'))[:500]}"
        ) from e
    except urllib.error.URLError as e:
        raise DeliveryError(f"GitHub pulls API unreachable: {e.reason}") from e
    pr_url = str(data.get("html_url") or data.get("url") or "")
    number = data.get("number")
    if not pr_url or not isinstance(number, int):
        raise DeliveryError("GitHub pulls response missing html_url/number")
    return pr_url, number


# ---------------------------------------------------------------------------
# deliver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryResult:
    item_id: str
    branch: str
    base: str
    commit_sha: str
    pr_url: str
    pr_number: int
    pack_hash: str
    body_sha256: str
    created: str = field(default_factory=utc_now_iso)

    @property
    def pr_ref(self) -> str:
        return self.pr_url or f"{self.branch}@{self.commit_sha[:12]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "branch": self.branch,
            "base": self.base,
            "commit_sha": self.commit_sha,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "pack_hash": self.pack_hash,
            "body_sha256": self.body_sha256,
            "created": self.created,
        }


def commit_on_branch(build: BuildResult, branch: str, *, message: str) -> str:
    """Move the build worktree onto ``branch`` and commit the source diff + the
    authored test. Returns the commit sha. The branch is the factory's own; a
    rework re-points it."""
    ws = build.workspace
    if ws is None:
        raise DeliveryRefused("build workspace was closed — nothing to deliver")
    repo = ws.repo
    files = [*build.changed_files, build.oracle.test_path]
    try:
        repo.run("checkout", "-q", "-B", branch, cwd=ws.root, check=True)
        repo.run("add", "--", *files, cwd=ws.root, check=True)
        repo.run(
            *FACTORY_IDENTITY, "commit", "-q", "--no-verify", "-m", message, cwd=ws.root, check=True
        )
        return repo.run(
            "rev-parse", "--verify", "HEAD^{commit}", cwd=ws.root, check=True
        ).stdout.strip()
    except GitError as e:
        raise DeliveryError(
            f"could not commit delivery branch {branch!r}: {redact(e.stderr)[:400]}"
        ) from e


def deliver(
    repo: GitRepo,
    item: BacklogItem,
    build: BuildResult,
    *,
    creds: GitCredentialsProvider | None = None,
    open_pr_fn: OpenPrFn | None = None,
    push_fn: PushFn | None = None,
    target_default_branch: str,
    pack_link: str = "",
    route_decision: Mapping[str, Any] | None = None,
    title: str = "",
    repo_id: str = "",
) -> DeliveryResult:
    """Deliver a CLEAN build as a new branch + PR. Order of refusals is deliberate:
    invariant first (before any credential is read), then credentials (fail
    closed), then deliverability, then git, then the remote."""
    branch = assert_not_default_branch(delivery_branch_name(item), target_default_branch)
    base = _norm_branch(target_default_branch)
    if not base:
        raise DeliveryError("target_default_branch is required (it is the PR base)")
    provider = creds if creds is not None else NullProvider()
    credentials = provider.resolve(repo_id or str(repo.path))
    if not build.clean:
        raise DeliveryRefused(
            f"build for {item.id} is not clean (belts={build.grade.belts.to_dict()}) — not deliverable"
        )
    if build.disqualified:
        raise DeliveryRefused(f"build for {item.id} was disqualified: {build.grade.dq_reason}")
    push = push_fn if push_fn is not None else git_push_fn
    open_pr = open_pr_fn if open_pr_fn is not None else github_open_pr_fn

    body = pr_body(item, build, pack_link=pack_link, route_decision=route_decision)
    pr_title = title or f"{item.title} [{item.id}]"
    sha = commit_on_branch(
        build,
        branch,
        message=f"{item.title}\n\ncrb factory item: {item.id}\nevidence pack: {build.pack_hash}\n"
        f"oracle: {build.oracle.test_path} sha256 {build.oracle.test_sha256}",
    )
    # belt-and-braces: the refspec is branch:branch — never HEAD, never the base.
    assert_not_default_branch(branch, base)
    push(repo, branch=branch, refspec=f"{branch}:{branch}", credentials=credentials)
    pr_url, pr_number = open_pr(
        remote=credentials.remote,
        branch=branch,
        base=base,
        title=pr_title,
        body=body,
        credentials=credentials,
    )
    return DeliveryResult(
        item_id=item.id,
        branch=branch,
        base=base,
        commit_sha=sha,
        pr_url=pr_url,
        pr_number=pr_number,
        pack_hash=build.pack_hash,
        body_sha256=sha256_text(body),
    )


__all__ = [
    "ALWAYS_PROTECTED_BRANCHES",
    "DELIVERY_BRANCH_PREFIX",
    "DefaultBranchProtectionError",
    "DeliveryError",
    "DeliveryRefused",
    "DeliveryResult",
    "EnvProvider",
    "GitCredentials",
    "GitCredentialsProvider",
    "NoGitCredentialsError",
    "NullProvider",
    "OpenPrFn",
    "PushFn",
    "StaticProvider",
    "assert_not_default_branch",
    "commit_on_branch",
    "deliver",
    "delivery_branch_name",
    "git_push_fn",
    "github_open_pr_fn",
    "owner_repo_from_remote",
    "pr_body",
    "slugify",
]
