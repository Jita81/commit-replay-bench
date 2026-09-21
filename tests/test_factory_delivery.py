"""crb.factory.delivery — branch + PR only, NEVER the default branch; creds fail closed.

Navigation
----------
What it is:   The factory delivery step's test suite — branch + PR only, NEVER the default
              branch; credentials fail closed.
What it does: Pins that the default branch is refused (before any credential is touched), that
              the delivery branch name is never a protected name, that a null credential provider
              fails closed, that credentials never leak (env provider), that delivery commits the
              source and the oracle on a new branch and opens the PR through stdlib ``urllib``,
              that a build that is not clean is refused, that the push seam rejects non-branch
              refspecs, ``owner/repo`` from the remote, that the delivery commit never sweeps
              unrelated files in, and — B-1b finding 1 — that a re-delivery leases against the
              commit the first delivery pushed, opens no second pull request and posts the
              rework comment (a comment that fails after the push is ``comment_error`` on an
              ``updated`` result, never a refusal), with the lease semantics proven against a
              REAL bare repository.
How:          ``Seams`` record the push, the PR and the comment calls instead of reaching a
              forge; the build comes from ``test_factory_build``'s harness; ``_ToBare`` runs
              ``git_push_fn``'s exact argv with the https remote swapped for a local bare repo.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/factory/delivery.py (under test), src/crb/factory/build.py
              (``BuildResult``), src/crb/core/git.py (the branch and push operations),
              tests/test_factory_build.py (the harness), docs/SECURITY.md (credentials, §3.3)
Tested by:    tests/test_factory_delivery.py
Touch when:   a forge other than GitHub is supported (a PR + comment seam case; the
              default-branch refusal must still come first); the branch-naming rule changes;
              the lease rule changes (the bare-repo test is what proves it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from crb.core.evidence import sha256_text
from crb.core.git import GitRepo, GitResult
from crb.factory import delivery as dv
from crb.factory.build import FACTORY_IDENTITY, BuildResult
from fixtures import pyrepo as pr
from test_factory_build import (
    SRC,
    TEST_MULTIPLY,
    FakeBuilder,
    Harness,
    authored_multiply,
    harness,
    multiply_item,
    noop,
)

__all__ = ["harness"]

TOKEN = "ghp_" + "a" * 36
REMOTE = "https://github.com/acme/calc.git"


def _creds() -> dv.GitCredentials:
    return dv.GitCredentials(remote=REMOTE, token=TOKEN)


@dataclass
class Seams:
    """Recording stand-ins for the push, open-PR and comment seams: nothing reaches a forge."""

    pushes: list[dict[str, Any]] = field(default_factory=list)
    prs: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)

    def push(
        self,
        repo: GitRepo,
        *,
        branch: str,
        refspec: str,
        credentials: dv.GitCredentials,
        expected: str | None = None,
    ) -> None:
        """Record the branch, refspec, remote and lease instead of pushing."""
        self.pushes.append(
            {
                "branch": branch,
                "refspec": refspec,
                "remote": credentials.remote,
                "expected": expected,
            }
        )

    def open_pr(self, **kw: Any) -> tuple[str, int]:
        """Record the PR request and answer with a fixed URL and number."""
        self.prs.append(dict(kw))
        return "https://github.invalid/acme/calc/pull/7", 7

    def comment_pr(self, **kw: Any) -> None:
        """Record the comment request."""
        self.comments.append(dict(kw))


def _clean_build(harness: Harness) -> BuildResult:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    return harness.build(item, authored, proof, FakeBuilder())


# --- the invariant (ratchet) --------------------------------------------------------


@pytest.mark.parametrize(
    ("branch", "default"),
    [
        ("main", "develop"),
        ("master", "develop"),
        ("MAIN", "develop"),
        ("develop", "develop"),
        ("refs/heads/develop", "develop"),
        ("refs/heads/refs/heads/main", ""),
        ("/main/", ""),
        ("", "develop"),
        ("   ", "develop"),
        ("trunk", "refs/heads/trunk"),
    ],
)
def test_assert_not_default_branch_refuses(branch: str, default: str) -> None:
    with pytest.raises(dv.DefaultBranchProtectionError):
        dv.assert_not_default_branch(branch, default)


def test_assert_not_default_branch_allows_new_branches() -> None:
    assert dv.assert_not_default_branch("crb/I-1-x", "main") == "crb/I-1-x"
    assert dv.assert_not_default_branch("refs/heads/crb/I-1-x", "develop") == "crb/I-1-x"
    assert frozenset({"main", "master"}) == dv.ALWAYS_PROTECTED_BRANCHES  # the ratchet


def test_delivery_branch_name_is_never_a_protected_name() -> None:
    for title in ("main", "master", "Main branch", "develop"):
        b = dv.delivery_branch_name(multiply_item(title=title))
        assert b.startswith("crb/I-1-")
        assert dv.assert_not_default_branch(b, "develop") == b


def test_deliver_refuses_default_before_touching_creds(harness: Harness) -> None:
    build = _clean_build(harness)
    try:
        item = multiply_item()
        target = dv.delivery_branch_name(item)  # make the computed branch the "default"

        class Boom:
            def resolve(self, repo: str) -> dv.GitCredentials:
                raise AssertionError("credentials must not be resolved before the invariant")

        with pytest.raises(dv.DefaultBranchProtectionError):
            dv.deliver(harness.repo.repo, item, build, creds=Boom(), target_default_branch=target)
    finally:
        build.close()


# --- credentials -------------------------------------------------------------------------


def test_null_provider_fails_closed(harness: Harness) -> None:
    build = _clean_build(harness)
    seams = Seams()
    try:
        with pytest.raises(dv.NoGitCredentialsError):
            dv.deliver(
                harness.repo.repo,
                multiply_item(),
                build,
                push_fn=seams.push,
                open_pr_fn=seams.open_pr,
                target_default_branch="main",
            )
        with pytest.raises(dv.NoGitCredentialsError):
            dv.deliver(
                harness.repo.repo,
                multiply_item(),
                build,
                creds=dv.NullProvider(),
                push_fn=seams.push,
                open_pr_fn=seams.open_pr,
                target_default_branch="main",
            )
        assert not seams.pushes and not seams.prs
    finally:
        build.close()


def test_credentials_never_leak_and_env_provider() -> None:
    c = _creds()
    assert TOKEN not in repr(c) and TOKEN not in json.dumps(c.to_dict())
    assert c.basic_auth_header().startswith("Authorization: Basic ")
    with pytest.raises(ValueError):
        dv.GitCredentials(remote="", token=TOKEN)
    with pytest.raises(ValueError):
        dv.GitCredentials(remote=REMOTE, token=" ")
    # a clear-text transport is refused at construction, before any push can leak the
    # token (CodeRabbit on PR #4, 2026-09-15); ssh forms are fine
    for bad in (
        "http://github.com/acme/calc.git",
        "git://github.com/acme/calc.git",
        "/srv/calc.git",
    ):
        with pytest.raises(ValueError, match="https:// or ssh"):
            dv.GitCredentials(remote=bad, token=TOKEN)
    for ok in ("git@github.com:acme/calc.git", "ssh://git@github.com/acme/calc.git"):
        assert dv.GitCredentials(remote=ok, token=TOKEN).remote == ok
    env = dv.EnvProvider(environ={"CRB_GIT_TOKEN": TOKEN, "CRB_GIT_REMOTE": REMOTE})
    assert env.resolve("x").remote == REMOTE
    with pytest.raises(dv.NoGitCredentialsError):
        dv.EnvProvider(environ={}).resolve("x")
    assert dv.StaticProvider(c).resolve("any") is c


# --- the happy path (hermetic seams) --------------------------------------------------------


def test_deliver_commits_source_and_oracle_on_new_branch_and_opens_pr(harness: Harness) -> None:
    item = multiply_item()
    build = _clean_build(harness)
    seams = Seams()
    try:
        res = dv.deliver(
            harness.repo.repo,
            item,
            build,
            creds=dv.StaticProvider(_creds()),
            push_fn=seams.push,
            open_pr_fn=seams.open_pr,
            target_default_branch="main",
            pack_link="packs/x.json",
            route_decision={"route": "calibrate", "reason": "n=0", "policy_version": "routing.v1"},
        )
        repo = harness.repo.repo
        assert res.branch == "crb/I-1-add-multiply-to-calc" and res.base == "main"
        assert res.pr_url.endswith("/pull/7") and res.pr_number == 7 and res.pr_ref == res.pr_url
        assert res.pack_hash == build.pack_hash
        # the branch exists in the repo, parented at HEAD, with exactly source + oracle
        assert repo.rev_parse(res.branch) == res.commit_sha
        assert repo.parent(res.commit_sha) == harness.head
        assert sorted(repo.changed_files(res.commit_sha)) == sorted([SRC, TEST_MULTIPLY])
        assert repo.show_file(res.commit_sha, TEST_MULTIPLY) == authored_multiply().content
        # main did not move
        assert repo.rev_parse("main") == harness.head
        # the seams saw a branch:branch refspec and a PR head != base
        assert seams.pushes == [
            {
                "branch": res.branch,
                "refspec": f"{res.branch}:{res.branch}",
                "remote": REMOTE,
                "expected": None,  # a first push: the bare lease
            }
        ]
        assert not res.updated and res.previous_commit_sha == "" and not seams.comments
        pr_call = seams.prs[0]
        assert pr_call["branch"] == res.branch and pr_call["base"] == "main"
        assert pr_call["remote"] == REMOTE and pr_call["credentials"].token == TOKEN
        body = pr_call["body"]
        assert build.pack_hash in body and "tests_unmodified=True" in body
        assert "packs/x.json" in body and "calibrate" in body and "routing.v1" in body
        assert build.oracle.test_sha256 in body and TOKEN not in body
        assert "never the default branch" in body
    finally:
        build.close()


def test_deliver_refuses_a_build_that_is_not_clean(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    proof = harness.prove(item, authored)
    build = harness.build(item, authored, proof, FakeBuilder(edit=noop))
    seams = Seams()
    try:
        with pytest.raises(dv.DeliveryRefused, match="not clean"):
            dv.deliver(
                harness.repo.repo,
                item,
                build,
                creds=dv.StaticProvider(_creds()),
                push_fn=seams.push,
                open_pr_fn=seams.open_pr,
                target_default_branch="main",
            )
        assert not seams.pushes
    finally:
        build.close()


def test_push_seam_rejects_non_branch_refspecs(harness: Harness) -> None:
    with pytest.raises(dv.DefaultBranchProtectionError):
        dv.git_push_fn(harness.repo.repo, branch="crb/x", refspec="HEAD:main", credentials=_creds())
    with pytest.raises(dv.DefaultBranchProtectionError):
        dv.git_push_fn(
            harness.repo.repo, branch="crb/x", refspec="crb/x:main", credentials=_creds()
        )


def test_owner_repo_from_remote() -> None:
    assert dv.owner_repo_from_remote("https://github.com/acme/calc.git") == ("acme", "calc")
    assert dv.owner_repo_from_remote("git@github.com:acme/calc.git") == ("acme", "calc")
    with pytest.raises(dv.DeliveryError):
        dv.owner_repo_from_remote("https://github.com/only")


def test_github_open_pr_uses_stdlib_urllib(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    seen: dict[str, Any] = {}

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"html_url": "https://github.com/acme/calc/pull/3", "number": 3}
            ).encode()

    def fake_urlopen(req: Any, timeout: int = 0) -> _Resp:
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["data"] = json.loads(req.data)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    url, n = dv.github_open_pr_fn(
        remote=REMOTE, branch="crb/x", base="main", title="t", body="b", credentials=_creds()
    )
    assert (url, n) == ("https://github.com/acme/calc/pull/3", 3)
    assert seen["url"] == "https://api.github.com/repos/acme/calc/pulls"
    assert seen["data"]["head"] == "crb/x" and seen["data"]["base"] == "main"
    assert seen["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_readme_untouched_by_delivery(harness: Harness) -> None:
    """The delivery commit never sweeps unrelated files in."""
    build = _clean_build(harness)
    try:
        assert build.workspace is not None
        (build.workspace.root / pr.README).write_text("stray edit\n", encoding="utf-8")
        seams = Seams()
        res = dv.deliver(
            harness.repo.repo,
            multiply_item(),
            build,
            creds=dv.StaticProvider(_creds()),
            push_fn=seams.push,
            open_pr_fn=seams.open_pr,
            target_default_branch="main",
        )
        assert pr.README not in harness.repo.repo.changed_files(res.commit_sha)
    finally:
        build.close()


# --- re-delivery: the rework updates the pull request (B-1b finding 1, DL-045) ---------------


class _Argv(GitRepo):
    """A ``GitRepo`` that records the argv ``git_push_fn`` builds and runs nothing."""

    def __init__(self) -> None:
        super().__init__("/nonexistent")
        self.argv: list[list[str]] = []

    def run(self, *args: str, check: bool = False, cwd: str | Path | None = None) -> GitResult:
        self.argv.append(list(args))
        return GitResult(0, "", "")


def test_git_push_fn_builds_the_exact_lease_argv() -> None:
    """Without ``expected`` the bare lease (what makes a FIRST push refuse a branch that
    already exists); with it ``--force-with-lease=<branch>:<sha>`` — the only lease git can
    hold when the push goes to a URL, where no remote-tracking ref exists."""
    creds = _creds()
    header = f"http.{REMOTE}.extraheader={creds.basic_auth_header()}"
    repo = _Argv()
    dv.git_push_fn(repo, branch="crb/x", refspec="crb/x:crb/x", credentials=creds)
    assert repo.argv == [["-c", header, "push", "--force-with-lease", REMOTE, "crb/x:crb/x"]]
    repo = _Argv()
    dv.git_push_fn(
        repo, branch="crb/x", refspec="crb/x:crb/x", credentials=creds, expected="a" * 40
    )
    assert repo.argv == [
        ["-c", header, "push", f"--force-with-lease=crb/x:{'a' * 40}", REMOTE, "crb/x:crb/x"]
    ]
    assert dv.force_with_lease_arg("crb/x", None) == "--force-with-lease"
    with pytest.raises(dv.DeliveryError, match="needs the commit"):
        dv.force_with_lease_arg("crb/x", "  ")
    assert TOKEN not in json.dumps(repo.argv).replace(creds.basic_auth_header(), "")


class _ToBare(GitRepo):
    """Runs ``git_push_fn``'s exact argv against a REAL local bare repository: only the
    remote argument is swapped (``REMOTE`` → the bare path); the one-shot auth header for
    the https remote stays on the command line and is simply not consulted for a path."""

    def __init__(self, path: Path, bare: Path) -> None:
        super().__init__(path)
        self.bare = bare
        self.argv: list[list[str]] = []

    def run(self, *args: str, check: bool = False, cwd: str | Path | None = None) -> GitResult:
        self.argv.append(list(args))
        swapped = tuple(str(self.bare) if a == REMOTE else a for a in args)
        return super().run(*swapped, check=check, cwd=cwd)


def test_lease_semantics_against_a_real_bare_repository(harness: Harness, tmp_path: Path) -> None:
    """The finding itself, reproduced and then fixed under real git: (1) a first push with
    the bare lease creates the branch; (2) a second push with the bare lease is REJECTED
    (``stale info`` — there is no remote-tracking ref to lease against when pushing to a
    URL: what B-1b hit); (3) the same push leasing against the commit the first push made
    succeeds; (4) a push leasing against a WRONG commit is rejected and the remote branch
    does not move. ``GitCredentials`` refuses a ``file://`` remote by design, so the https
    credentials stay and only the destination argument is swapped for the bare path."""
    bare = tmp_path / "remote.git"
    GitRepo(tmp_path).run("init", "--bare", "-q", str(bare), cwd=tmp_path, check=True)
    remote = GitRepo(bare)
    repo = _ToBare(harness.repo.path, bare)
    creds = _creds()
    branch, refspec = "crb/I-1-lease", "crb/I-1-lease:crb/I-1-lease"

    def commit_on_branch(parent: str, msg: str) -> str:
        """A new commit on ``branch`` (same tree) without touching any checkout."""
        tree = repo.run("rev-parse", f"{parent}^{{tree}}", check=True).stdout.strip()
        sha = repo.run(
            *FACTORY_IDENTITY, "commit-tree", tree, "-p", parent, "-m", msg, check=True
        ).stdout.strip()
        repo.run("update-ref", f"refs/heads/{branch}", sha, check=True)
        return sha

    first = commit_on_branch(harness.head, "first delivery")
    # (1) the first push: bare lease, the branch does not exist on the remote → created
    dv.git_push_fn(repo, branch=branch, refspec=refspec, credentials=creds)
    assert remote.rev_parse(branch) == first
    assert repo.argv[-1][2:4] == ["push", "--force-with-lease"]
    # (2) the rework's commit — pushed the way B-1b pushed it: rejected, `stale info`
    second = commit_on_branch(first, "rework 1")
    with pytest.raises(dv.DeliveryError, match=r"stale info|rejected"):
        dv.git_push_fn(repo, branch=branch, refspec=refspec, credentials=creds)
    assert remote.rev_parse(branch) == first  # the remote did not move
    # (4) a WRONG expected commit: rejected by git, the remote does not move
    with pytest.raises(dv.DeliveryError, match=r"stale info|rejected"):
        dv.git_push_fn(
            repo, branch=branch, refspec=refspec, credentials=creds, expected=harness.head
        )
    assert remote.rev_parse(branch) == first
    # (3) the fix: lease against the commit the first delivery pushed → the branch moves
    dv.git_push_fn(repo, branch=branch, refspec=refspec, credentials=creds, expected=first)
    assert remote.rev_parse(branch) == second
    assert repo.argv[-1][2:4] == ["push", f"--force-with-lease={branch}:{first}"]
    # main never moved on either side
    assert repo.rev_parse("main") == harness.head
    assert not remote.run("rev-parse", "--verify", "refs/heads/main").ok
    assert TOKEN not in json.dumps(repo.argv).replace(creds.basic_auth_header(), "")


def test_redelivery_leases_on_the_previous_commit_updates_the_pr_and_comments(
    harness: Harness,
) -> None:
    item = multiply_item()
    seams = Seams()
    kw: dict[str, Any] = {
        "creds": dv.StaticProvider(_creds()),
        "push_fn": seams.push,
        "open_pr_fn": seams.open_pr,
        "comment_pr_fn": seams.comment_pr,
        "target_default_branch": "main",
        "pack_link": "packs/x.json",
    }
    first_build = _clean_build(harness)
    try:
        first = dv.deliver(harness.repo.repo, item, first_build, **kw)
    finally:
        first_build.close()  # the loop releases the reviewed build before a rework
    rework = _clean_build(harness)
    try:
        second = dv.deliver(
            harness.repo.repo,
            item,
            rework,
            previous=first,
            rework_n=1,
            after_verdict="accept_with_edit",
            **kw,
        )
        repo = harness.repo.repo
        # the same branch, re-pointed; the push leased against the FIRST commit
        assert second.branch == first.branch and second.base == first.base
        assert second.commit_sha != first.commit_sha
        assert repo.rev_parse(second.branch) == second.commit_sha
        assert [p["expected"] for p in seams.pushes] == [None, first.commit_sha]
        # no second pull request: url and number carried over, the result says `updated`
        assert len(seams.prs) == 1
        assert (second.pr_url, second.pr_number) == (first.pr_url, first.pr_number)
        assert second.updated and second.previous_commit_sha == first.commit_sha
        assert not first.updated
        assert second.pack_hash == rework.pack_hash
        # the reviewer is told why the branch moved
        (c,) = seams.comments
        assert c["pr_number"] == 7 and c["remote"] == REMOTE and c["credentials"].token == TOKEN
        body = c["body"]
        assert body.startswith("### Rework 1 — after `accept_with_edit`")
        assert first.commit_sha in body and second.commit_sha in body
        assert rework.pack_hash in body and "packs/x.json" in body and TOKEN not in body
        assert second.body_sha256 == sha256_text(body)
        d = second.to_dict()
        assert d["updated"] is True and d["previous_commit_sha"] == first.commit_sha
        assert repo.rev_parse("main") == harness.head
    finally:
        rework.close()


def test_redelivery_without_a_comment_seam_updates_the_branch_silently(
    harness: Harness,
) -> None:
    item = multiply_item()
    seams = Seams()
    kw: dict[str, Any] = {
        "creds": dv.StaticProvider(_creds()),
        "push_fn": seams.push,
        "open_pr_fn": seams.open_pr,
        "target_default_branch": "main",
    }
    b1 = _clean_build(harness)
    try:
        first = dv.deliver(harness.repo.repo, item, b1, **kw)
    finally:
        b1.close()
    b2 = _clean_build(harness)
    try:
        second = dv.deliver(harness.repo.repo, item, b2, previous=first, rework_n=1, **kw)
        assert second.updated and second.body_sha256 == "" and not seams.comments
        assert len(seams.prs) == 1 and seams.pushes[-1]["expected"] == first.commit_sha
    finally:
        b2.close()


@pytest.mark.parametrize(
    "failure",
    [
        dv.DeliveryError(f"GitHub comments API returned 403: token {TOKEN} may not comment"),
        TimeoutError("timed out"),
        ValueError("Expecting value: line 1 column 1 (char 0)"),
    ],
    ids=["api-refusal", "timeout", "non-json-body"],
)
def test_redelivery_whose_comment_fails_keeps_the_moved_branch_on_the_record(
    harness: Harness, failure: Exception
) -> None:
    """The comment is the OPTIONAL step and it runs AFTER the push has moved the remote
    branch: its failure must not undo the record of the delivery that succeeded (the chain
    would say `refused` while the pull request carries the rework). The result is still
    `updated`, carries the redacted failure as ``comment_error``, and hashes no body."""
    item = multiply_item()
    seams = Seams()

    def failing_comment(**kw: Any) -> None:
        seams.comments.append(dict(kw))
        raise failure

    kw: dict[str, Any] = {
        "creds": dv.StaticProvider(_creds()),
        "push_fn": seams.push,
        "open_pr_fn": seams.open_pr,
        "comment_pr_fn": failing_comment,
        "target_default_branch": "main",
    }
    b1 = _clean_build(harness)
    try:
        first = dv.deliver(harness.repo.repo, item, b1, **kw)
    finally:
        b1.close()
    assert first.comment_error == "" and first.to_dict()["comment_error"] == ""
    b2 = _clean_build(harness)
    try:
        second = dv.deliver(
            harness.repo.repo, item, b2, previous=first, rework_n=1, after_verdict="x", **kw
        )
        # the push happened (leased against the first commit) and the result says so
        assert seams.pushes[-1]["expected"] == first.commit_sha and len(seams.prs) == 1
        assert second.updated and second.commit_sha != first.commit_sha
        assert harness.repo.repo.rev_parse(second.branch) == second.commit_sha
        assert (second.pr_url, second.pr_number) == (first.pr_url, first.pr_number)
        # the comment was attempted once, failed, and the failure is on the result — redacted
        assert len(seams.comments) == 1
        assert second.body_sha256 == ""
        assert second.comment_error.startswith(type(failure).__name__ + ": ")
        assert TOKEN not in second.comment_error
        assert second.to_dict()["comment_error"] == second.comment_error
    finally:
        b2.close()


def test_redelivery_refuses_a_different_branch_base_or_item(harness: Harness) -> None:
    """A rework can only update the delivery it follows: another branch, another base or
    another item's delivery is refused before anything is pushed."""
    item = multiply_item()
    seams = Seams()
    kw: dict[str, Any] = {
        "creds": dv.StaticProvider(_creds()),
        "push_fn": seams.push,
        "open_pr_fn": seams.open_pr,
        "comment_pr_fn": seams.comment_pr,
    }
    b1 = _clean_build(harness)
    try:
        first = dv.deliver(harness.repo.repo, item, b1, target_default_branch="main", **kw)
    finally:
        b1.close()
    b2 = _clean_build(harness)
    try:
        before = len(seams.pushes)
        with pytest.raises(dv.DeliveryError, match="re-delivery must update"):
            dv.deliver(
                harness.repo.repo,
                item,
                b2,
                previous=replace(first, branch="crb/I-1-something-else"),
                target_default_branch="main",
                **kw,
            )
        with pytest.raises(dv.DeliveryError, match="re-delivery must update"):
            dv.deliver(
                harness.repo.repo, item, b2, previous=first, target_default_branch="develop", **kw
            )
        with pytest.raises(dv.DeliveryError, match="for item"):
            dv.deliver(
                harness.repo.repo,
                item,
                b2,
                previous=replace(first, item_id="I-9"),
                target_default_branch="main",
                **kw,
            )
        with pytest.raises(dv.DeliveryError, match="no commit to lease"):
            dv.deliver(
                harness.repo.repo,
                item,
                b2,
                previous=replace(first, commit_sha=""),
                target_default_branch="main",
                **kw,
            )
        assert len(seams.pushes) == before and len(seams.prs) == 1 and not seams.comments
    finally:
        b2.close()


def test_github_comment_pr_uses_stdlib_urllib(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    seen: dict[str, Any] = {}

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"id": 1}).encode()

    def fake_urlopen(req: Any, timeout: int = 0) -> _Resp:
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["headers"] = dict(req.header_items())
        seen["data"] = json.loads(req.data)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    dv.github_comment_pr_fn(
        remote=REMOTE, pr_number=7, body="why the branch moved", credentials=_creds()
    )
    assert seen["url"] == "https://api.github.com/repos/acme/calc/issues/7/comments"
    assert seen["method"] == "POST" and seen["data"] == {"body": "why the branch moved"}
    assert seen["headers"]["Authorization"] == f"Bearer {TOKEN}"
    with pytest.raises(dv.DeliveryError, match="cannot comment"):
        dv.github_comment_pr_fn(remote=REMOTE, pr_number=0, body="x", credentials=_creds())
