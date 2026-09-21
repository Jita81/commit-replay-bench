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

A **re-delivery** (a rework after ``accept_with_edit``) updates the pull request
the first delivery opened instead of opening a second one: ``deliver`` is given
the earlier :class:`DeliveryResult` as ``previous``, the push leases against the
commit that delivery pushed (``--force-with-lease=<branch>:<sha>`` — a bare lease
has nothing to hold when the push goes to a URL, and git answers ``stale info``;
B-1b, 2026-09-19), the PR url and number are carried over, and a short comment
names the rework so the human reviewer sees why the branch moved.

Navigation
----------
What it is:   Delivery — a clean build becomes a branch + pull request in the customer's
              repository, never a write to its default branch.
What it does: Enforces the hard invariant first (``assert_not_default_branch``, before any
              credential is read), then resolves BYOK credentials (the default provider
              refuses — fail closed), commits the source diff plus the oracle on
              ``crb/<item>-<slug>``, pushes with a one-shot auth header (the token never
              touches ``.git/config``), and opens the PR whose body is the redacted evidence
              summary. Push and PR are injectable seams.
How:          ``deliver`` = invariant → credentials → deliverability → ``commit_on_branch``
              → ``push_fn`` → ``open_pr_fn`` → ``DeliveryResult``; with ``previous`` the
              push leases against ``previous.commit_sha``, no PR is opened and
              ``comment_pr_fn`` posts the rework note (``updated=True``).
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md (the PR body is a
              summary, never raw output)
Works with:   src/crb/factory/build.py (``BuildResult`` and its kept workspace),
              src/crb/core/git.py (``GitRepo.run`` for checkout / commit / push),
              src/crb/core/redact.py (every string in the PR body), src/crb/factory/loop.py
              (``_deliver`` — opt-in, default off; hands the rework its ``previous``),
              src/crb/factory/evidence.py (``record_delivery`` / ``record_delivery_updated`` /
              ``record_delivery_refused``), docs/SECURITY.md#33-credentials
Tested by:    tests/test_factory_delivery.py, tests/test_factory_loop.py
Touch when:   onboarding a repository hosted somewhere other than GitHub — add an
              ``open_pr_fn`` + ``comment_pr_fn`` seam (Azure DevOps, GitLab) and a
              credentials provider; NEVER
              relax ``ALWAYS_PROTECTED_BRANCHES`` or the invariant's order (its test is a
              ratchet — docs/CONTRIBUTING.md#the-never-weaken-a-gate-rule).
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


def remote_carries_token_safely(remote: str) -> bool:
    """True when ``remote`` is a transport that does not expose a push token in clear
    text: ``https://``, ``ssh://`` or the scp-like ``git@host:owner/repo`` form. Everything
    else (``http://``, ``git://``, ``ftp://``, a bare local path) is refused."""
    r = remote.strip()
    lower = r.lower()
    if lower.startswith(("https://", "ssh://")):
        return True
    # scp-like: user@host:path — no scheme, exactly one "@" before the first ":"
    head, sep, _rest = r.partition(":")
    return bool(sep) and "@" in head and "/" not in head and not lower.startswith("//")


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
        if not remote_carries_token_safely(self.remote):
            # Fail closed at construction: a `http://` or `git://` remote would send the
            # Basic header in clear text (CodeRabbit on PR #4, 2026-09-15).
            raise ValueError(
                "credentials need an https:// or ssh (git@ / ssh://) remote — "
                f"refusing to send a token over {self.remote.split(':', 1)[0]!r}"
            )

    def basic_auth_header(self) -> str:
        """The one-shot ``Authorization`` header value the push seam passes to git."""
        raw = f"{self.username}:{self.token}".encode()
        return "Authorization: Basic " + base64.b64encode(raw).decode("ascii")

    def to_dict(self) -> dict[str, Any]:
        """Loggable form: the token is always ``[REDACTED]``."""
        return {"remote": self.remote, "username": self.username, "token": "[REDACTED]"}


@runtime_checkable
class GitCredentialsProvider(Protocol):
    """BYOK seam: how delivery obtains a push token for ``repo``."""

    def resolve(self, repo: str) -> GitCredentials: ...


class NullProvider:
    """The default: no credentials. ``resolve`` always raises — fail closed."""

    def resolve(self, repo: str) -> GitCredentials:
        raise NoGitCredentialsError(
            f"no git credentials configured for {repo!r} — delivery refused (fail closed)"
        )


class StaticProvider:
    """Credentials handed in by the caller (tests, a one-off run)."""

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
    """Strip ``refs/heads/`` and surrounding slashes so aliases of a branch compare equal."""
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
    """A branch-safe slug of a title (lower-case, hyphenated, capped)."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "change"


def delivery_branch_name(item: BacklogItem) -> str:
    """``crb/<item id>-<title slug>`` — the branch a delivery opens."""
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
    """The PR description: the evidence summary a reviewer needs, every string redacted."""
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


def rework_comment(
    item: BacklogItem,
    build: BuildResult,
    *,
    previous: DeliveryResult,
    commit_sha: str,
    rework_n: int,
    after_verdict: str,
    pack_link: str = "",
) -> str:
    """The comment a re-delivery posts on the pull request it updates: why the branch
    moved (the rework number and the verdict it answers), from which commit to which, and
    the new build's evidence. Every string redacted."""
    belts = build.grade.belts.to_dict()
    lines = [
        f"### Rework {rework_n} — after `{after_verdict or 'review'}`",
        "",
        f"The factory rebuilt `{item.id}` after the review verdict "
        f"`{after_verdict or 'review'}` and moved `{previous.branch}` from "
        f"`{previous.commit_sha[:12]}` to `{commit_sha[:12]}` (force-with-lease against the "
        "previous commit; the pull request is the same).",
        "",
        f"- evidence pack: `{build.pack_hash}`" + (f" — {pack_link}" if pack_link else ""),
        f"- commit: `{commit_sha}` (previous `{previous.commit_sha}`)",
        f"- grade: **{'clean' if build.clean else 'not clean'}**",
        "- belts: " + ", ".join(f"{k}={v}" for k, v in belts.items()),
        f"- oracle: `{build.oracle.test_path}` sha256 `{build.oracle.test_sha256}`",
        f"- builder: `{build.rung}` trial `{build.trial}`",
        f"- ledger row: `{build.row.row_hash if build.row else '(not ledgered)'}`",
    ]
    return redact("\n".join(lines))


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------

#: ``push_fn(repo, *, branch, refspec, credentials, expected=None)`` — ``expected`` is the
#: commit the remote branch must still point at (a re-delivery); ``None`` is a first push.
PushFn = Callable[..., None]
#: ``open_pr_fn(*, remote, branch, base, title, body, credentials) -> (url, number)``
OpenPrFn = Callable[..., tuple[str, int]]
#: ``comment_pr_fn(*, remote, pr_number, body, credentials) -> None``
CommentPrFn = Callable[..., None]


def force_with_lease_arg(branch: str, expected: str | None) -> str:
    """The lease git is asked to hold. With ``expected`` the remote ``branch`` must still
    point at that commit (``--force-with-lease=<branch>:<sha>``) — the only form that works
    when the push goes to a URL, where no remote-tracking ref exists to lease against.
    Without it the bare lease is what makes a FIRST push refuse a branch that already
    exists on the remote (git: ``stale info``)."""
    if expected is None:
        return "--force-with-lease"
    sha = expected.strip()
    if not sha:
        raise DeliveryError("a re-delivery needs the commit the previous delivery pushed")
    return f"--force-with-lease={branch}:{sha}"


def git_push_fn(
    repo: GitRepo,
    *,
    branch: str,
    refspec: str,
    credentials: GitCredentials,
    expected: str | None = None,
) -> None:
    """Push ``refspec`` (``branch:branch``, never ``HEAD``) with a one-shot auth
    header. The token is never written to ``.git/config``. ``expected`` (a re-delivery)
    is the commit the remote branch must still point at — see :func:`force_with_lease_arg`."""
    src, _, dst = refspec.partition(":")
    if src != branch or dst != branch:
        raise DefaultBranchProtectionError(f"refspec {refspec!r} must be {branch}:{branch}")
    res = repo.run(
        "-c",
        f"http.{credentials.remote}.extraheader={credentials.basic_auth_header()}",
        "push",
        force_with_lease_arg(branch, expected),
        credentials.remote,
        refspec,
    )
    if not res.ok:
        raise DeliveryError(
            f"git push of {branch!r} failed rc={res.returncode}: {redact(res.stderr)[:400]}"
        )


def owner_repo_from_remote(remote: str) -> tuple[str, str]:
    """``(owner, name)`` from an https or ``git@`` remote URL (``.git`` stripped)."""
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


def _github_post(
    url: str, payload: Mapping[str, Any], credentials: GitCredentials, *, what: str, timeout: int
) -> dict[str, Any]:
    """One authenticated POST to the GitHub REST API (stdlib urllib); the decoded JSON
    body, or a :class:`DeliveryError` naming ``what`` and the (redacted) refusal."""
    req = urllib.request.Request(  # noqa: S310 — https API URL built from a parsed remote
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
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
            f"GitHub {what} API returned {e.code}: {redact(e.read().decode('utf-8', 'replace'))[:500]}"
        ) from e
    except urllib.error.URLError as e:
        raise DeliveryError(f"GitHub {what} API unreachable: {e.reason}") from e
    return dict(data) if isinstance(data, Mapping) else {}


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
    data = _github_post(
        f"{api_base}/repos/{owner}/{name}/pulls",
        {"title": title, "head": branch, "base": base, "body": body, "maintainer_can_modify": True},
        credentials,
        what="pulls",
        timeout=timeout,
    )
    pr_url = str(data.get("html_url") or data.get("url") or "")
    number = data.get("number")
    if not pr_url or not isinstance(number, int):
        raise DeliveryError("GitHub pulls response missing html_url/number")
    return pr_url, number


def github_comment_pr_fn(
    *,
    remote: str,
    pr_number: int,
    body: str,
    credentials: GitCredentials,
    api_base: str = "https://api.github.com",
    timeout: int = 30,
) -> None:
    """Post ``body`` as a comment on pull request ``pr_number`` (GitHub's issues comments
    API — a pull request is an issue for comments; the installation token that opened the
    PR may comment on it)."""
    owner, name = owner_repo_from_remote(remote)
    if pr_number <= 0:
        raise DeliveryError(f"cannot comment on pull request number {pr_number!r}")
    _github_post(
        f"{api_base}/repos/{owner}/{name}/issues/{pr_number}/comments",
        {"body": body},
        credentials,
        what="comments",
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# deliver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryResult:
    """What a delivery produced: the branch, its commit, the PR (url + number) and the
    hash of the body that was posted (the PR description; for a re-delivery, the rework
    comment). ``updated`` marks a re-delivery: the branch moved from
    ``previous_commit_sha`` to ``commit_sha`` on the pull request the first delivery opened."""

    item_id: str
    branch: str
    base: str
    commit_sha: str
    pr_url: str
    pr_number: int
    pack_hash: str
    body_sha256: str
    created: str = field(default_factory=utc_now_iso)
    previous_commit_sha: str = ""
    updated: bool = False

    @property
    def pr_ref(self) -> str:
        """The reference the review records: the PR URL, or branch@sha when no PR opened."""
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
            "previous_commit_sha": self.previous_commit_sha,
            "updated": self.updated,
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
    comment_pr_fn: CommentPrFn | None = None,
    target_default_branch: str,
    pack_link: str = "",
    route_decision: Mapping[str, Any] | None = None,
    title: str = "",
    repo_id: str = "",
    previous: DeliveryResult | None = None,
    rework_n: int = 0,
    after_verdict: str = "",
) -> DeliveryResult:
    """Deliver a CLEAN build as a new branch + PR. Order of refusals is deliberate:
    invariant first (before any credential is read), then credentials (fail
    closed), then deliverability, then git, then the remote.

    With ``previous`` (the item's earlier delivery) this is a RE-delivery: the branch and
    base must be the previous ones, the push leases against ``previous.commit_sha``, no
    second pull request is opened (url and number are carried over) and, when a
    ``comment_pr_fn`` is given, a comment naming the rework (``rework_n``, the
    ``after_verdict`` it answers, the new pack hash and commit) is posted on it."""
    branch = assert_not_default_branch(delivery_branch_name(item), target_default_branch)
    base = _norm_branch(target_default_branch)
    if not base:
        raise DeliveryError("target_default_branch is required (it is the PR base)")
    if previous is not None:
        if previous.item_id != item.id:
            raise DeliveryError(
                f"previous delivery is for item {previous.item_id!r}, not {item.id!r}"
            )
        if previous.branch != branch or previous.base != base:
            raise DeliveryError(
                f"re-delivery must update {previous.branch!r} -> {previous.base!r}; "
                f"this build would deliver {branch!r} -> {base!r}"
            )
        if not previous.commit_sha.strip():
            raise DeliveryError("previous delivery carries no commit to lease against")
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

    pr_title = title or f"{item.title} [{item.id}]"
    sha = commit_on_branch(
        build,
        branch,
        message=f"{item.title}\n\ncrb factory item: {item.id}\nevidence pack: {build.pack_hash}\n"
        f"oracle: {build.oracle.test_path} sha256 {build.oracle.test_sha256}",
    )
    # belt-and-braces: the refspec is branch:branch — never HEAD, never the base.
    assert_not_default_branch(branch, base)
    if previous is not None:
        # the rework re-points the SAME branch: lease against the commit the first delivery
        # pushed (a bare lease has no remote-tracking ref to hold when pushing to a URL),
        # keep the pull request, and tell its reviewer why the branch moved
        push(
            repo,
            branch=branch,
            refspec=f"{branch}:{branch}",
            credentials=credentials,
            expected=previous.commit_sha,
        )
        note = rework_comment(
            item,
            build,
            previous=previous,
            commit_sha=sha,
            rework_n=rework_n,
            after_verdict=after_verdict,
            pack_link=pack_link,
        )
        posted = ""
        if comment_pr_fn is not None and previous.pr_number > 0:
            comment_pr_fn(
                remote=credentials.remote,
                pr_number=previous.pr_number,
                body=note,
                credentials=credentials,
            )
            posted = sha256_text(note)
        return DeliveryResult(
            item_id=item.id,
            branch=branch,
            base=base,
            commit_sha=sha,
            pr_url=previous.pr_url,
            pr_number=previous.pr_number,
            pack_hash=build.pack_hash,
            body_sha256=posted,
            previous_commit_sha=previous.commit_sha,
            updated=True,
        )
    body = pr_body(item, build, pack_link=pack_link, route_decision=route_decision)
    push(repo, branch=branch, refspec=f"{branch}:{branch}", credentials=credentials, expected=None)
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
    "CommentPrFn",
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
    "force_with_lease_arg",
    "git_push_fn",
    "github_comment_pr_fn",
    "github_open_pr_fn",
    "owner_repo_from_remote",
    "pr_body",
    "rework_comment",
    "slugify",
]
