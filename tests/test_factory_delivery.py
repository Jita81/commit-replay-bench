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
              refspecs, ``owner/repo`` from the remote, and that the delivery commit never sweeps
              unrelated files in.
How:          ``Seams`` record the push and the PR call instead of reaching a forge; the build
              comes from ``test_factory_build``'s harness.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/factory/delivery.py (under test), src/crb/factory/build.py
              (``BuildResult``), src/crb/core/git.py (the branch and push operations),
              tests/test_factory_build.py (the harness), docs/SECURITY.md (credentials, §3.3)
Tested by:    tests/test_factory_delivery.py
Touch when:   a forge other than GitHub is supported (a PR seam case; the default-branch refusal
              must still come first); the branch-naming rule changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from crb.core.git import GitRepo
from crb.factory import delivery as dv
from crb.factory.build import BuildResult
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
    """Recording stand-ins for the push and open-PR seams: nothing reaches a forge."""

    pushes: list[dict[str, Any]] = field(default_factory=list)
    prs: list[dict[str, Any]] = field(default_factory=list)

    def push(
        self, repo: GitRepo, *, branch: str, refspec: str, credentials: dv.GitCredentials
    ) -> None:
        """Record the branch, refspec and remote instead of pushing."""
        self.pushes.append({"branch": branch, "refspec": refspec, "remote": credentials.remote})

    def open_pr(self, **kw: Any) -> tuple[str, int]:
        """Record the PR request and answer with a fixed URL and number."""
        self.prs.append(dict(kw))
        return "https://github.invalid/acme/calc/pull/7", 7


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
            {"branch": res.branch, "refspec": f"{res.branch}:{res.branch}", "remote": REMOTE}
        ]
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
