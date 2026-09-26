"""Delivery — a graded change ships as a BRANCH + PR in the customer's repo, never main.

The factory only ever *proposes*. A clean build the independent review ACCEPTED is
committed on a new branch ``crb/<item_id>-<slug>`` and a pull request is opened
against the customer's default branch; a human on the customer's side reviews and
merges. The factory NEVER pushes to, nor opens a PR against, ``main`` / ``master`` /
the configured default — :func:`assert_not_default_branch` is the hard invariant,
checked before credentials are resolved or the remote is touched, and its test is a
ratchet. Nor does it deliver a build the review did not accept: ``deliver`` takes the
verdict and refuses anything but ``accept`` before a credential is read (ADR-0021).

Credentials are BYOK behind :class:`GitCredentialsProvider`. The default is
:class:`NullProvider`, which raises :class:`NoGitCredentialsError` — with no
credentials wired, delivery **fails closed**, never a silent success-looking
no-op. Tokens never reach ``.git/config`` nor the argv: the default push seam passes
the token as a one-shot ``http.extraheader`` in the child's environment
(``GIT_CONFIG_COUNT``); the PR seam is GitHub's REST API over
:mod:`urllib` (stdlib). Both are injectable so tests are hermetic; an Azure
DevOps seam plugs in the same way.

The PR body is the evidence summary — belts, pack hash, apparatus, route
decision, RED proof — and a link to the pack. It carries no secrets: every
string passes through :mod:`crb.core.redact`.

A **re-delivery** (an item whose pull request an earlier run opened, accepted again)
updates that pull request instead of opening a second one: ``deliver`` is given
the earlier :class:`DeliveryResult` as ``previous``, the push leases against the
commit that delivery pushed (``--force-with-lease=<branch>:<sha>`` — a bare lease
has nothing to hold when the push goes to a URL, and git answers ``stale info``;
B-1b, 2026-09-19), the PR url and number are carried over, and a short comment
says why the branch moved. The comment is the OPTIONAL step and it runs AFTER the
push has moved the remote branch: when it fails (a rate limit, a 5xx, a timeout)
the result is still ``updated`` and carries the redacted failure as
``comment_error`` — the record must agree with the remote, never say "refused" of
a branch the pull request already carries.

A **close** (:func:`close_pull_request`) is the rework path for a delivered pull
request a later review did NOT accept (ADR-0021): a comment names the verdict and
why, then the pull request is closed — never merged, never deleted, a person may
reopen it.

Navigation
----------
What it is:   Delivery — a clean, reviewed and ACCEPTED build becomes a branch + pull
              request in the customer's repository, never a write to its default branch;
              and the close of a delivered pull request a later review did not accept.
What it does: Enforces the hard invariant first (``assert_not_default_branch``, before any
              credential is read), then the review (``verdict`` must be ``accept`` —
              ADR-0021), then resolves BYOK credentials (the default provider refuses —
              fail closed), commits the source diff plus the oracle on
              ``crb/<item>-<slug>`` (``[a-z0-9-]`` only), pushes with a one-shot auth header
              (never in ``.git/config``, never on the argv), and opens the PR whose body is
              the redacted evidence summary with everything a ticket author wrote inside one
              fence and whose title is escaped (C6b); ``close_pull_request`` comments the
              verdict and closes. Push, PR, comment and close are injectable seams.
How:          ``deliver`` = invariant → verdict → credentials → deliverability →
              ``commit_on_branch`` → ``push_fn`` → ``open_pr_fn`` → ``DeliveryResult``; with
              ``previous`` the push leases against ``previous.commit_sha``, no PR is opened
              and ``comment_pr_fn`` posts the note (``updated=True``; a failed note is
              ``comment_error`` on the result, never a refusal of the moved branch);
              ``close_pull_request`` = refuse ``accept`` → refuse a blank ``repo_id`` →
              credentials for that repository (the key a delivery resolves) →
              ``close_comment`` → ``close_pr_fn`` (GitHub: comment, then
              ``PATCH …/pulls/{n}``).
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md (the PR body is a
              summary, never raw output), docs/adr/0021-factory-review-before-delivery.md
              (only an accepted build is delivered; a later non-accept closes the PR)
Works with:   src/crb/factory/build.py (``BuildResult`` and its kept workspace),
              src/crb/core/git.py (``GitRepo.run`` for checkout / commit / push, and
              ``git_config_env`` for the header), src/crb/core/redact.py (every string in
              the PR body), src/crb/factory/loop.py (``_deliver`` — opt-in, default off,
              reached only by an accepted verdict; ``_withdraw`` closes),
              src/crb/factory/review.py (``VERDICT_ACCEPT``), src/crb/factory/evidence.py
              (``record_delivery`` / ``record_delivery_updated`` /
              ``record_delivery_refused`` / ``record_delivery_outcome``),
              docs/SECURITY.md#33-credentials
Tested by:    tests/test_factory_delivery.py, tests/test_factory_loop.py
Touch when:   onboarding a repository hosted somewhere other than GitHub — add an
              ``open_pr_fn`` + ``comment_pr_fn`` + ``close_pr_fn`` seam (Azure DevOps,
              GitLab) and a credentials provider; NEVER relax ``ALWAYS_PROTECTED_BRANCHES``,
              the verdict refusal or the invariant's order (their tests are ratchets —
              docs/CONTRIBUTING.md#the-never-weaken-a-gate-rule).
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
from crb.core.git import GitError, GitRepo, git_config_env
from crb.core.redact import redact
from crb.factory.backlog import BacklogItem
from crb.factory.build import FACTORY_IDENTITY, BuildResult
from crb.factory.review import VERDICT_ACCEPT

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
#: What a delivery branch may be made of after ``crb/`` (C6b): nothing a ticket author could
#: use to build an invalid or surprising ref (``..``, ``.lock``, ``@{``, capitals, ``_``).
DELIVERY_BRANCH_RE = re.compile(r"crb/[a-z0-9]+(?:-[a-z0-9]+)*")


def slugify(text: str, *, max_len: int = 40) -> str:
    """A branch-safe slug of a title (lower-case, hyphenated, capped)."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "change"


def delivery_branch_name(item: BacklogItem) -> str:
    """``crb/<item id>-<title slug>``, both halves reduced to ``[a-z0-9-]`` — the branch a
    delivery opens. An item id may carry capitals, ``.`` and ``_`` (a ticket's key and
    revision become one: ``fake-4711.r2``), which git refuses in some shapes (``A..B``) and
    which a ticket author controls; neither reaches a ref (assessment 2026-09-25, C6b)."""
    branch = f"{DELIVERY_BRANCH_PREFIX}{slugify(item.id, max_len=64)}-{slugify(item.title)}"
    if not DELIVERY_BRANCH_RE.fullmatch(branch):  # the shape is the contract; never guessed
        raise DeliveryError(f"could not build a safe delivery branch for {item.id!r}")
    return branch


def legacy_delivery_branch_name(item: BacklogItem) -> str:
    """The branch name deliveries used before C6b (``crb/<raw id>-<slug>``) — accepted ONLY
    to update a pull request an earlier run opened under it."""
    return f"{DELIVERY_BRANCH_PREFIX}{item.id}-{slugify(item.title)}"


#: CommonMark's backslash-escapable characters (every ASCII punctuation mark).
_MD_PUNCT_RE = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~^&\"'@=:;/?%$,])")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def escape_markdown_line(text: str, *, max_len: int = 200) -> str:
    """``text`` as ONE line of inert markdown: control characters and newlines collapse to
    a space and every ASCII punctuation mark is backslash-escaped, so a ticket's title
    cannot open a code span, emphasis, a link, an HTML tag or a mention (C6b)."""
    one_line = " ".join(_CONTROL_RE.sub(" ", text).split())[:max_len]
    return _MD_PUNCT_RE.sub(r"\\\1", one_line)


def fenced(lines: list[str], *, info: str = "text") -> list[str]:
    """``lines`` inside ONE fenced code block whose fence is longer than any run of
    backticks in them (CommonMark: only a fence of the same character, at least as long,
    closes it), so nothing inside can end the block and become markup (C6b)."""
    body = "\n".join(
        _CONTROL_RE.sub(lambda m: "\n" if "\n" in m.group() else " ", ln) for ln in lines
    )
    longest = max((len(r) for r in re.findall(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}{info}", *body.split("\n"), fence]


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
    """The PR description: the evidence summary a reviewer needs, every string redacted.

    Everything a ticket author wrote — the title and the acceptance criteria — is DATA,
    not markup: it appears only inside one fenced block (:func:`fenced`), so it cannot add
    a heading, a checkbox, a link, a mention or an HTML comment to the customer's pull
    request (assessment 2026-09-25, C6b)."""
    belts = build.grade.belts.to_dict()
    proof = build.pack.notes.get("red_proof", {})
    ticket_lines = [f"title: {item.title}"]
    if item.acceptance_criteria:
        ticket_lines += ["acceptance criteria:"] + [f"- {c}" for c in item.acceptance_criteria]
    lines = [
        f"## crb factory: backlog item `{slugify(item.id, max_len=64)}`",
        "",
        f"Automated proposal from crb factory for backlog item `{slugify(item.id, max_len=64)}` "
        f"({item.kind}, {item.level}, class `{item.capability_class}`).",
        "",
        "This targets a NEW branch, never the default branch. A human reviews and merges.",
        "",
        "### What was asked (from the backlog item, shown as written)",
        "",
        *fenced(ticket_lines),
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
    why = (
        f"after the review verdict `{after_verdict}` asked for a rework and the rebuilt "
        "change was accepted"
        if after_verdict
        else "in a later run whose review accepted the rebuilt change"
    )
    lines = [
        f"### Rework {rework_n} — after `{after_verdict}`"
        if after_verdict
        else "### Rebuilt by a later factory run — accepted by review",
        "",
        f"The factory rebuilt `{item.id}` {why}, and moved `{previous.branch}` from "
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
#: ``close_pr_fn(*, remote, pr_number, body, credentials) -> None`` — post ``body`` on the
#: pull request, then close it (ADR-0021: the rework path for a delivered PR later found weak).
ClosePrFn = Callable[..., None]


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
    header. The token is never written to ``.git/config`` and never put on the argv: the
    header travels in the child's environment as ``GIT_CONFIG_COUNT`` /
    ``GIT_CONFIG_KEY_n`` / ``GIT_CONFIG_VALUE_n`` (:func:`crb.core.git.git_config_env` — an
    argv is readable by every user on the host through ``/proc`` and ``ps``; D1,
    docs/SECURITY.md §3.3). ``expected`` (a re-delivery) is the commit the remote branch
    must still point at — see :func:`force_with_lease_arg`."""
    src, _, dst = refspec.partition(":")
    if src != branch or dst != branch:
        raise DefaultBranchProtectionError(f"refspec {refspec!r} must be {branch}:{branch}")
    res = repo.run(
        "push",
        force_with_lease_arg(branch, expected),
        credentials.remote,
        refspec,
        env=git_config_env(
            {f"http.{credentials.remote}.extraheader": credentials.basic_auth_header()}
        ),
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


def repository_of(remote: str) -> str:
    """``owner/name`` of a remote URL (or of an ``owner/name`` string), lower-cased because
    GitHub's names are case-insensitive; ``""`` when it cannot be parsed."""
    try:
        owner, name = owner_repo_from_remote(remote)
    except DeliveryError:
        return ""
    return f"{owner}/{name}".lower()


#: GitHub's address of a pull request: ``https://<host>/<owner>/<name>/pull/<n>``.
_PR_URL_RE = re.compile(r"^https://[^/\s]+/([^/\s]+)/([^/\s]+)/pull/\d+/?$")


def recorded_repository(repository: str, pr_url: str) -> str:
    """The repository a recorded pull request is in, as ``owner/name``: the ``repository``
    its delivery recorded; for a delivery recorded before that field existed, the
    repository in GitHub's address of the pull request; otherwise ``""``, which
    :func:`repository_mismatch` never takes to match anything."""
    if repository.strip():
        return repository.strip().lower()
    m = _PR_URL_RE.match(pr_url.strip())
    return f"{m[1]}/{m[2]}".lower() if m else ""


def delivered_repository(previous: DeliveryResult) -> str:
    """:func:`recorded_repository` of an earlier delivery."""
    return recorded_repository(previous.repository, previous.pr_url)


def repository_mismatch(*, repository: str, pr_url: str, remote: str, where: str) -> str:
    """Why a recorded pull request (``where`` names it) must not be touched through
    ``remote``, or ``""`` when it is in that repository (PR #55 review).

    A pull request number means nothing without its repository, and an operator may
    re-link a row to another one (``POST /repos/{name}/github-link``): the same number
    there is somebody else's pull request. Every path that reuses a recorded pull
    request asks this first — the re-delivery's push and comment and the close
    (:func:`assert_same_repository`), and the outcome sync. An unknown repository on
    either side is a reason, never assumed to match."""
    was, now = recorded_repository(repository, pr_url), repository_of(remote)
    if not was or not now:
        return (
            f"cannot tell which repository {where} is in (delivered to {was or 'unknown'}, "
            f"linked now to {now or 'unknown'}): it is not touched"
        )
    if was != now:
        return (
            f"{where} is in {was}, and this repository is now linked to {now}: the factory "
            "never touches a pull request in another repository — close or merge it there "
            "by hand"
        )
    return ""


def assert_same_repository(previous: DeliveryResult, remote: str) -> None:
    """Refuse (:class:`DeliveryError`) to touch an earlier delivery's pull request through
    ``remote`` unless the pull request is in that repository (:func:`repository_mismatch`)."""
    why = repository_mismatch(
        repository=previous.repository,
        pr_url=previous.pr_url,
        remote=remote,
        where=f"pull request #{previous.pr_number} of {previous.item_id!r}",
    )
    if why:
        raise DeliveryError(why)


def _github_post(
    url: str,
    payload: Mapping[str, Any],
    credentials: GitCredentials,
    *,
    what: str,
    timeout: int,
    method: str = "POST",
) -> dict[str, Any]:
    """One authenticated call (``POST`` by default, ``PATCH`` to close) to the GitHub REST
    API (stdlib urllib); the decoded JSON body, or a :class:`DeliveryError` naming
    ``what`` and the (redacted) refusal."""
    req = urllib.request.Request(  # noqa: S310 — https API URL built from a parsed remote
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        method=method,
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


def github_close_pr_fn(
    *,
    remote: str,
    pr_number: int,
    body: str,
    credentials: GitCredentials,
    api_base: str = "https://api.github.com",
    timeout: int = 30,
) -> None:
    """Comment ``body`` on pull request ``pr_number``, then close it (``PATCH
    /repos/{owner}/{repo}/pulls/{n}`` with ``state: closed``). The comment goes first so a
    reader of the closed pull request sees why; a failure of either is a
    :class:`DeliveryError`."""
    owner, name = owner_repo_from_remote(remote)
    if pr_number <= 0:
        raise DeliveryError(f"cannot close pull request number {pr_number!r}")
    github_comment_pr_fn(
        remote=remote,
        pr_number=pr_number,
        body=body,
        credentials=credentials,
        api_base=api_base,
        timeout=timeout,
    )
    _github_post(
        f"{api_base}/repos/{owner}/{name}/pulls/{pr_number}",
        {"state": "closed"},
        credentials,
        what="pulls",
        timeout=timeout,
        method="PATCH",
    )


# ---------------------------------------------------------------------------
# deliver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryResult:
    """What a delivery produced: the branch, its commit, the PR (url + number) and the
    hash of the body that was posted (the PR description; for a re-delivery, the rework
    comment). ``updated`` marks a re-delivery: the branch moved from
    ``previous_commit_sha`` to ``commit_sha`` on the pull request the first delivery opened.
    ``comment_error`` (a re-delivery) is the redacted failure of the rework comment — the
    branch HAD moved, so the delivery stands and the reviewer was not told why; empty when
    the comment posted (``body_sha256`` is its hash) or none was asked for."""

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
    comment_error: str = ""
    #: ``owner/name`` of the repository the pull request is in (:func:`repository_of` of the
    #: remote it was delivered through) — the number means nothing without it (PR #55 review).
    repository: str = ""

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
            "comment_error": self.comment_error,
            "repository": self.repository,
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
    verdict: str,
) -> DeliveryResult:
    """Deliver a CLEAN, REVIEWED and ACCEPTED build as a new branch + PR. Order of
    refusals is deliberate: invariant first (before any credential is read), then the
    review (``verdict`` must be ``accept`` — ADR-0021: a pull request never opens on an
    unreviewed or unaccepted build, whoever calls this), then credentials (fail closed),
    then deliverability, then git, then the remote.

    With ``previous`` (the item's earlier delivery) this is a RE-delivery: the branch and
    base must be the previous ones, the push leases against ``previous.commit_sha``, no
    second pull request is opened (url and number are carried over) and, when a
    ``comment_pr_fn`` is given, a comment naming the rework (``rework_n``, the
    ``after_verdict`` it answers, the new pack hash and commit) is posted on it. The
    comment runs after the push has moved the remote branch, so its failure is NOT a
    delivery failure: the result is returned ``updated`` with ``comment_error`` set."""
    wanted = delivery_branch_name(item)
    if previous is not None and previous.branch == legacy_delivery_branch_name(item):
        # a pull request an earlier run opened before C6b keeps its branch
        wanted = previous.branch
    branch = assert_not_default_branch(wanted, target_default_branch)
    base = _norm_branch(target_default_branch)
    if not base:
        raise DeliveryError("target_default_branch is required (it is the PR base)")
    if verdict != VERDICT_ACCEPT:
        raise DeliveryRefused(
            f"build for {item.id} was not accepted by the review (verdict {verdict!r}) — "
            "only an accepted, reviewed build is delivered (ADR-0021)"
        )
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
    if previous is not None:
        assert_same_repository(previous, credentials.remote)
    if not build.clean:
        raise DeliveryRefused(
            f"build for {item.id} is not clean (belts={build.grade.belts.to_dict()}) — not deliverable"
        )
    if build.disqualified:
        raise DeliveryRefused(f"build for {item.id} was disqualified: {build.grade.dq_reason}")
    push = push_fn if push_fn is not None else git_push_fn
    open_pr = open_pr_fn if open_pr_fn is not None else github_open_pr_fn

    # the title a ticket author wrote is escaped into ONE inert line (C6b): GitHub renders
    # a pull request's title as inline markdown
    pr_title = title or f"{escape_markdown_line(item.title)} [{item.id}]"
    subject = " ".join(_CONTROL_RE.sub(" ", item.title).split())[:72] or item.id
    sha = commit_on_branch(
        build,
        branch,
        message=f"{subject}\n\ncrb factory item: {item.id}\nevidence pack: {build.pack_hash}\n"
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
        comment_error = ""
        if comment_pr_fn is not None and previous.pr_number > 0:
            try:
                comment_pr_fn(
                    remote=credentials.remote,
                    pr_number=previous.pr_number,
                    body=note,
                    credentials=credentials,
                )
            except Exception as exc:
                # the push above already moved the remote branch: a failed comment (an API
                # refusal, a timeout, an undecodable reply) must not turn a delivery that
                # happened into a refusal on the record. It is carried on the result; the
                # loop warns and reviews the branch the pull request now carries.
                comment_error = redact(f"{type(exc).__name__}: {exc}")[:400]
            else:
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
            comment_error=comment_error,
            repository=repository_of(credentials.remote),
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
        repository=repository_of(credentials.remote),
    )


def close_comment(previous: DeliveryResult, *, verdict: str, reason: str) -> str:
    """The comment a close posts: which verdict, why, and that nothing was merged. Every
    string redacted."""
    lines = [
        f"### Closed by the crb factory — review verdict `{verdict}`",
        "",
        f"A later factory run reviewed a rebuild of item `{previous.item_id}` and did not "
        f"accept it (verdict `{verdict}`). The product no longer stands behind the change on "
        f"`{previous.branch}`, so this pull request is closed rather than left open for "
        "someone to merge.",
        "",
        f"- why: {reason}",
        f"- last delivered commit: `{previous.commit_sha}` (evidence pack `{previous.pack_hash}`)",
        "",
        "Nothing was merged. The item's evidence chain records the close; a person may "
        "reopen this pull request.",
    ]
    return redact("\n".join(lines))


def close_pull_request(
    previous: DeliveryResult,
    *,
    verdict: str,
    reason: str,
    creds: GitCredentialsProvider | None,
    close_pr_fn: ClosePrFn | None = None,
    repo_id: str,
) -> str:
    """Close a pull request the factory opened, because a later review of the item did
    NOT accept it (ADR-0021) — the rework path for a delivered pull request later found
    weak. Refuses ``verdict == accept`` (an accepted build is delivered, never closed), a
    delivery with no pull request, and a blank ``repo_id``; credentials fail closed like a
    delivery's. ``repo_id`` is REQUIRED and is the key a delivery of the same repository
    resolves its credentials with (the loop passes the one it holds) — never the item id,
    which a provider keyed on the repository would resolve wrongly (PR #55 review). A pull
    request in another repository than those credentials name is refused before the
    forge is called (:func:`assert_same_repository`). Returns the comment posted (the
    caller records it)."""
    if verdict == VERDICT_ACCEPT:
        raise DeliveryError("an accepted build is delivered, never closed")
    if previous.pr_number <= 0:
        raise DeliveryError(f"delivery of {previous.item_id!r} has no pull request to close")
    if not repo_id.strip():
        raise DeliveryError(
            f"close of {previous.item_id!r} names no repository to resolve credentials for"
        )
    provider = creds if creds is not None else NullProvider()
    credentials = provider.resolve(repo_id)
    assert_same_repository(previous, credentials.remote)
    body = close_comment(previous, verdict=verdict, reason=reason)
    close = close_pr_fn if close_pr_fn is not None else github_close_pr_fn
    close(
        remote=credentials.remote,
        pr_number=previous.pr_number,
        body=body,
        credentials=credentials,
    )
    return body


__all__ = [
    "ALWAYS_PROTECTED_BRANCHES",
    "DELIVERY_BRANCH_PREFIX",
    "DELIVERY_BRANCH_RE",
    "ClosePrFn",
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
    "assert_same_repository",
    "close_comment",
    "close_pull_request",
    "commit_on_branch",
    "deliver",
    "delivered_repository",
    "delivery_branch_name",
    "escape_markdown_line",
    "fenced",
    "force_with_lease_arg",
    "git_push_fn",
    "github_close_pr_fn",
    "github_comment_pr_fn",
    "github_open_pr_fn",
    "legacy_delivery_branch_name",
    "owner_repo_from_remote",
    "pr_body",
    "recorded_repository",
    "repository_mismatch",
    "repository_of",
    "rework_comment",
    "slugify",
]
