"""crb.core.git — the argv-only git wrapper, exercised on the fixture repo.

Navigation
----------
What it is:   The argv-only git wrapper's test suite on the fixture repository.
What it does: Pins ``GitResult``, ``rev_parse`` / ``parent`` (and their errors on a bad ref or a
              root commit), ``log_shas``, ``changed_files``, ``numstat`` churn, author / date /
              subject / message, ``show_file``, the worktree lifecycle (add, checkout paths,
              diff, remove), ``check=False`` results and a timeout as ``GitError`` rc 124.
How:          Every call goes through a real ``git`` subprocess on ``pyrepo``; nothing is mocked.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/git.py (under test), tests/fixtures/pyrepo.py (the history),
              tests/test_git_clone.py (the clone half of the same module)
Tested by:    tests/test_git.py
Touch when:   a git operation is added to the wrapper (one case here; the wrapper stays argv-only,
              never a shell).
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from crb.core.git import GitError, GitRepo, GitResult
from fixtures import pyrepo as pr


def test_git_result_properties() -> None:
    r = GitResult(0, "a\n\n b \n", "")
    assert r.ok
    assert r.lines == ["a", " b "]
    assert not GitResult(1, "", "err").ok


def test_rev_parse_and_parent(pyrepo: pr.PyRepo) -> None:
    repo = pyrepo.repo
    assert repo.rev_parse() == pyrepo.docs_sha
    assert repo.rev_parse("HEAD~1") == pyrepo.feat_sha
    assert repo.parent(pyrepo.feat_sha) == pyrepo.initial_sha
    assert repo.parent(pyrepo.docs_sha) == pyrepo.feat_sha
    assert re.fullmatch(r"[0-9a-f]{40}", pyrepo.feat_sha)


def test_rev_parse_bad_ref_raises_git_error(pyrepo: pr.PyRepo) -> None:
    with pytest.raises(GitError) as ei:
        pyrepo.repo.rev_parse("no-such-ref")
    err = ei.value
    assert err.returncode != 0
    assert err.argv[0] == "git"
    assert "rev-parse" in err.argv
    assert "failed rc=" in str(err)


def test_parent_of_root_commit_raises(pyrepo: pr.PyRepo) -> None:
    with pytest.raises(GitError):
        pyrepo.repo.parent(pyrepo.initial_sha)


def test_is_repo(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    assert pyrepo.repo.is_repo()
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not GitRepo(plain).is_repo()


def test_log_shas(pyrepo: pr.PyRepo) -> None:
    repo = pyrepo.repo
    assert repo.log_shas(10) == [pyrepo.docs_sha, pyrepo.feat_sha, pyrepo.initial_sha]
    assert repo.log_shas(1) == [pyrepo.docs_sha]
    assert repo.log_shas(5, ref=pyrepo.feat_sha) == [pyrepo.feat_sha, pyrepo.initial_sha]
    assert repo.log_shas(5, no_merges=False)[0] == pyrepo.docs_sha


def test_changed_files(pyrepo: pr.PyRepo) -> None:
    repo = pyrepo.repo
    assert repo.changed_files(pyrepo.feat_sha) == [pr.SRC, pr.TEST_SUBTRACT]
    assert repo.changed_files(pyrepo.docs_sha) == [pr.README]
    assert set(repo.changed_files(pyrepo.initial_sha)) == {"pytest.ini", pr.SRC, pr.TEST_CALC}


def test_numstat_churn(pyrepo: pr.PyRepo) -> None:
    repo = pyrepo.repo
    assert (
        repo.numstat_churn(f"{pyrepo.feat_sha}~1", pyrepo.feat_sha, [pr.SRC]) == pr.FEAT_SRC_CHURN
    )
    assert repo.numstat_churn(pyrepo.initial_sha, pyrepo.feat_sha, []) == 0
    # restricted to paths: the test file alone
    n_test = repo.numstat_churn(pyrepo.initial_sha, pyrepo.feat_sha, [pr.TEST_SUBTRACT])
    assert n_test == len(pr.TEST_SUBTRACT_SRC.splitlines())
    # unrelated path → 0
    assert repo.numstat_churn(pyrepo.initial_sha, pyrepo.feat_sha, ["nope.py"]) == 0


def test_author_date_subject_message(pyrepo: pr.PyRepo) -> None:
    repo = pyrepo.repo
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", repo.author_date(pyrepo.feat_sha)
    )
    assert repo.subject(pyrepo.feat_sha) == "feat: add subtract"
    assert repo.subject(pyrepo.docs_sha) == "docs: describe the calculator"
    # a UTC author date is spelled ``+00:00`` whatever git renders (2.53 prints ``Z``):
    # the date is stored, hashed and compared for era selection
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-09-15T13:10:00Z"}
    subprocess.run(
        [
            "git",
            "-C",
            str(pyrepo.path),
            *pr.GIT_IDENTITY,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "chore: utc",
        ],
        check=True,
        env=env,
    )
    assert repo.author_date(repo.rev_parse("HEAD")) == "2026-09-15T13:10:00+00:00"
    assert repo.message(pyrepo.feat_sha).startswith("feat: add subtract")


def test_show_file(pyrepo: pr.PyRepo) -> None:
    repo = pyrepo.repo
    assert repo.show_file(pyrepo.feat_sha, pr.SRC) == pr.SRC_FEAT
    assert repo.show_file(pyrepo.initial_sha, pr.SRC) == pr.SRC_INITIAL
    assert repo.show_file(pyrepo.initial_sha, pr.TEST_SUBTRACT) is None
    assert repo.show_file(pyrepo.feat_sha, "missing.py") is None


def test_worktree_add_checkout_paths_diff_and_remove(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    repo = pyrepo.repo
    dest = tmp_path / "wt"
    repo.worktree_add(dest, pyrepo.initial_sha)
    assert (dest / pr.SRC).read_text() == pr.SRC_INITIAL
    assert not (dest / pr.TEST_SUBTRACT).exists()
    assert GitRepo(dest).rev_parse() == pyrepo.initial_sha
    listing = repo.run("worktree", "list", check=True).stdout
    assert str(dest.resolve()) in listing or str(dest) in listing

    # overlay the commit's files into the worktree
    repo.checkout_paths(pyrepo.feat_sha, [pr.TEST_SUBTRACT], cwd=dest)
    assert (dest / pr.TEST_SUBTRACT).read_text() == pr.TEST_SUBTRACT_SRC
    repo.checkout_paths(pyrepo.feat_sha, [], cwd=dest)  # no-op

    assert repo.diff_names("HEAD", cwd=dest) == [pr.TEST_SUBTRACT]
    assert repo.diff_paths_against(pyrepo.feat_sha, [pr.TEST_SUBTRACT], cwd=dest) == ""
    assert repo.diff_paths_against(pyrepo.feat_sha, [], cwd=dest) == ""
    assert pr.SRC in repo.diff_paths_against(pyrepo.feat_sha, [pr.SRC], cwd=dest)
    assert pr.TEST_SUBTRACT in repo.diff_stat("HEAD", cwd=dest)
    text = repo.diff_text("HEAD", cwd=dest)
    assert "+++ b/tests/test_subtract.py" in text

    repo.worktree_remove(dest)
    assert not dest.exists()
    assert str(dest) not in repo.run("worktree", "list", check=True).stdout
    # removing again is tolerated (no check=True on remove)
    repo.worktree_remove(dest)


def test_run_check_false_returns_result(pyrepo: pr.PyRepo) -> None:
    r = pyrepo.repo.run("rev-parse", "--verify", "nope^{commit}")
    assert not r.ok
    assert r.stderr


def test_run_timeout_raises_git_error_124(tmp_path: Path) -> None:
    fake = tmp_path / "slowgit"
    fake.write_text("#!/bin/sh\nsleep 5\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    repo = GitRepo(tmp_path, git_binary=str(fake), timeout=1)
    with pytest.raises(GitError) as ei:
        repo.run("status")
    assert ei.value.returncode == 124
    assert "timed out" in ei.value.stderr


def test_git_repo_path_is_pathlike(pyrepo: pr.PyRepo) -> None:
    repo = GitRepo(str(pyrepo.path))
    assert isinstance(repo.path, Path)
    assert os.fspath(repo.path) == str(pyrepo.path)
