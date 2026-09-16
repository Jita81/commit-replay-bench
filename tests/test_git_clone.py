"""crb.core.git cloning: URL policy, credential redaction, and ``clone_repo`` against a
local bare remote (full history, ``--no-tags``, idempotent, atomic, fail-closed).

Navigation
----------
What it is:   The clone policy's test suite: URL validation, credential redaction and
              ``clone_repo`` against a local bare remote.
What it does: Pins that only HTTPS and SSH URLs are accepted (``file://`` only under the
              ``CRB_ALLOW_LOCAL_CLONE`` developer switch), that refusals and errors never echo an
              embedded credential, that ``redact_url`` / ``redact_urls_in`` scrub free text, and
              that a clone takes the full history without tags, is idempotent, refuses a
              non-empty non-repository destination, and cleans up on failure or timeout (rc 124).
How:          ``bare_remote`` from ``fixtures.remote`` serves ``pyrepo``; a URL to a closed port
              proves the fail-fast error path without a network.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/git.py (under test), tests/fixtures/remote.py (the bare remote),
              tests/test_cli_repo_url.py and tests/test_worker_clone.py (the same policy at the
              CLI and worker), docs/SECURITY.md (the credential rules)
Tested by:    tests/test_git_clone.py
Touch when:   a URL scheme or host policy is added (a case in the accepted and refused tables);
              the clone options change (``--no-tags``, depth).
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from crb.core.git import (
    LOCAL_CLONE_ENV,
    CloneUrlError,
    GitError,
    GitRepo,
    clone_repo,
    local_clone_allowed,
    redact_url,
    redact_urls_in,
    validate_clone_url,
)
from fixtures import pyrepo as pr
from fixtures.remote import bare_remote

# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/org/repo.git",
        "https://github.com/org/repo",
        "HTTPS://example.org/x/y",
        "ssh://git@github.com/org/repo.git",
        "ssh://git@github.com:2222/org/repo.git",
        "git@github.com:org/repo.git",
        "deploy-1@git.internal.nhs.uk:team/service",
    ],
)
def test_https_and_ssh_are_accepted(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    assert validate_clone_url(f"  {url}  ") == url


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("http://github.com/org/repo.git", "scheme 'http'"),
        ("git://github.com/org/repo.git", "scheme 'git'"),
        ("ftp://host/x", "scheme 'ftp'"),
        ("file:///srv/repos/x", "scheme 'file'"),
        ("/srv/repos/x", "not a git URL"),
        ("./x", "not a git URL"),
        ("~/x", "not a git URL"),
        ("C:\\repos\\x", "not a git URL"),
        ("https://github.com", "no repository path"),
        ("https://github.com/", "no repository path"),
        ("https:///org/repo", "no host"),
        ("https://github.com/org/re po", "whitespace"),
    ],
)
def test_refused_urls(url: str, why: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    with pytest.raises(CloneUrlError, match=why):
        validate_clone_url(url)


def test_file_urls_only_under_the_dev_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    assert not local_clone_allowed()
    with pytest.raises(CloneUrlError, match=LOCAL_CLONE_ENV):
        validate_clone_url("file:///tmp/x.git")
    assert validate_clone_url("file:///tmp/x.git", allow_local=True) == "file:///tmp/x.git"
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    assert local_clone_allowed()
    assert validate_clone_url("file:///tmp/x.git") == "file:///tmp/x.git"
    with pytest.raises(CloneUrlError, match="no path"):
        validate_clone_url("file://")
    # the switch never widens the policy beyond file://
    with pytest.raises(CloneUrlError, match="not a git URL"):
        validate_clone_url("/tmp/x.git")
    monkeypatch.setenv(LOCAL_CLONE_ENV, "yes")  # only the literal "1" counts
    assert not local_clone_allowed()


def test_refusal_messages_never_echo_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    with pytest.raises(CloneUrlError) as ei:
        validate_clone_url("https://alice:s3cretT0ken@example.org/")
    assert "s3cretT0ken" not in str(ei.value) and "alice" not in str(ei.value)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "safe"),
    [
        ("https://alice:s3cret@example.org/org/repo.git", "https://example.org/org/repo.git"),
        ("https://ghp_abcdef0123456789@github.com/o/r", "https://github.com/o/r"),
        ("https://example.org/org/repo.git?x=1#f", "https://example.org/org/repo.git?x=1#f"),
        ("ssh://git@github.com/org/repo.git", "ssh://git@github.com/org/repo.git"),
        ("ssh://git:pw@github.com:22/org/repo.git", "ssh://git@github.com:22/org/repo.git"),
        ("git@github.com:org/repo.git", "git@github.com:org/repo.git"),
        ("file:///srv/x.git", "file:///srv/x.git"),
        ("", ""),
        ("not a url at all", "[unparsable url]"),
    ],
)
def test_redact_url(url: str, safe: str) -> None:
    assert redact_url(url) == safe


def test_redact_urls_in_free_text() -> None:
    text = (
        "fatal: unable to access 'https://bob:t0k3n@example.org/o/r.git/': refused\n"
        "also ssh://deploy:pw@host/x and plain https://example.org/ok"
    )
    out = redact_urls_in(text)
    assert "t0k3n" not in out and "pw@" not in out and "bob" not in out
    assert "https://example.org/o/r.git/" in out and "https://example.org/ok" in out


# ---------------------------------------------------------------------------
# clone_repo
# ---------------------------------------------------------------------------


@pytest.fixture
def remote(pyrepo: pr.PyRepo, tmp_path: Path) -> str:
    return bare_remote(pyrepo.path, tmp_path / "remote.git", tag="v1")


def test_clone_full_history_no_tags(pyrepo: pr.PyRepo, remote: str, tmp_path: Path) -> None:
    dest = tmp_path / "clones" / "pyrepo"
    head = clone_repo(remote, dest, allow_local=True)
    assert head == pyrepo.docs_sha
    got = GitRepo(dest)
    assert got.is_repo() and got.rev_parse() == pyrepo.docs_sha
    # full history: every commit is present and mining-style queries work
    assert got.log_shas(10) == [pyrepo.docs_sha, pyrepo.feat_sha, pyrepo.initial_sha]
    assert got.changed_files(pyrepo.feat_sha) == [pr.SRC, pr.TEST_SUBTRACT]
    assert not got.run("rev-parse", "--is-shallow-repository", check=True).stdout.startswith("true")
    # --no-tags: the remote's tag was not fetched
    assert got.run("tag", "--list", check=True).stdout.strip() == ""
    # no temp directory left beside the clone
    assert sorted(p.name for p in dest.parent.iterdir()) == ["pyrepo"]


def test_clone_is_idempotent(pyrepo: pr.PyRepo, remote: str, tmp_path: Path) -> None:
    dest = tmp_path / "pyrepo"
    first = clone_repo(remote, dest, allow_local=True)
    marker = dest / "local-marker.txt"
    marker.write_text("kept", encoding="utf-8")
    second = clone_repo(remote, dest, allow_local=True)
    assert first == second == pyrepo.docs_sha
    assert marker.read_text(encoding="utf-8") == "kept"  # reused, never re-cloned


def test_clone_respects_the_policy_switch(
    remote: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    with pytest.raises(CloneUrlError, match="refused"):
        clone_repo(remote, tmp_path / "x")
    assert not (tmp_path / "x").exists()
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    assert len(clone_repo(remote, tmp_path / "x")) == 40


def test_clone_refuses_a_non_empty_non_repo_destination(remote: str, tmp_path: Path) -> None:
    dest = tmp_path / "busy"
    dest.mkdir()
    (dest / "file").write_text("x", encoding="utf-8")
    with pytest.raises(GitError, match="not a git repository"):
        clone_repo(remote, dest, allow_local=True)
    assert (dest / "file").exists()
    # an EMPTY directory is fine (created by an operator ahead of time)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert len(clone_repo(remote, empty, allow_local=True)) == 40


def test_clone_failure_is_git_error_with_redacted_argv(tmp_path: Path) -> None:
    missing = (tmp_path / "nope.git").resolve().as_uri()
    with pytest.raises(GitError) as ei:
        clone_repo(missing, tmp_path / "dest", allow_local=True)
    assert ei.value.returncode != 0 and "clone" in ei.value.argv
    assert not (tmp_path / "dest").exists()
    assert not any(p.name.startswith("dest.tmp-") for p in tmp_path.iterdir())


def test_clone_error_never_carries_credentials(tmp_path: Path) -> None:
    """A URL with an embedded token that fails fast (nothing listens on port 1): the
    exception, its argv and the stderr it carries are all redacted."""
    url = "https://alice:s3cretT0ken@127.0.0.1:1/org/repo.git"
    with pytest.raises(GitError) as ei:
        clone_repo(url, tmp_path / "dest", timeout=60)
    err = ei.value
    for secret in ("s3cretT0ken", "alice"):  # the token AND the username stay out of every field
        assert secret not in str(err) and secret not in err.stderr, secret
        assert all(secret not in a for a in err.argv), secret
    assert "https://127.0.0.1:1/org/repo.git" in err.argv


def test_clone_timeout_is_a_git_error_124_and_cleans_up(tmp_path: Path) -> None:
    fake = tmp_path / "slowgit"
    fake.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    with pytest.raises(GitError) as ei:
        clone_repo(
            "https://example.org/org/repo.git",
            tmp_path / "dest",
            timeout=1,
            git_binary=str(fake),
        )
    assert ei.value.returncode == 124 and "timed out" in ei.value.stderr
    assert not (tmp_path / "dest").exists()
    assert not any(p.name.startswith("dest.tmp-") for p in tmp_path.iterdir())
