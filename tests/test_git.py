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
Touch when:   onboarding a client repository never needs it; a git operation is added to the
              wrapper (one case here; the wrapper stays argv-only, never a shell).
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
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


def test_changed_and_diff_names_read_a_non_ascii_path_raw(tmp_path: Path) -> None:
    """A non-ASCII path comes back as the path itself, never git's display quoting."""
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "fixture"),
        ("config", "core.quotePath", "true"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    (root / "café.py").write_text("x = 1\n", encoding="utf-8")
    (root / "plain.py").write_text("y = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "one"], check=True)
    repo = GitRepo(root)
    assert sorted(repo.changed_files("HEAD")) == ["café.py", "plain.py"]
    (root / "café.py").write_text("x = 2\n", encoding="utf-8")
    assert repo.diff_names("HEAD") == ["café.py"]


def _fixture_repo(root: Path) -> None:
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "fixture@example.invalid"),
        ("config", "user.name", "fixture"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True)


def _git(root: Path, *args: str, stdin: bytes | None = None) -> str:
    return (
        subprocess.run(
            ["git", "-C", str(root), *args], input=stdin, capture_output=True, check=True
        )
        .stdout.decode("ascii")
        .strip()
    )


def test_changed_and_diff_names_keep_a_carriage_return_in_a_path(tmp_path: Path) -> None:
    """Outside review: a ``\\r`` in a tracked name is read as itself, never translated to
    a newline by text-mode decoding."""
    root = tmp_path / "repo"
    _fixture_repo(root)
    name = "odd\rname.py"
    (root / name).write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "one"], check=True)
    repo = GitRepo(root)
    assert repo.changed_files("HEAD") == [name]
    (root / name).write_text("x = 2\n", encoding="utf-8")
    assert repo.diff_names("HEAD") == [name]


def test_changed_and_diff_names_read_a_non_utf8_path_reversibly(tmp_path: Path) -> None:
    """Outside review: a tracked name holding a byte that is not UTF-8 neither raises nor is
    mangled; it is decoded as :func:`os.fsdecode` names the file. The tree is built with git
    plumbing, so no filesystem support for such a name is needed (APFS refuses one)."""
    root = tmp_path / "repo"
    _fixture_repo(root)
    raw_name = b"bad\xffname.py"
    blob = _git(root, "hash-object", "-w", "--stdin", stdin=b"x = 1\n")
    _git(
        root,
        "update-index",
        "-z",
        "--index-info",
        stdin=b"100644 " + blob.encode() + b"\t" + raw_name + b"\0",
    )
    tree = _git(root, "write-tree")
    commit = _git(root, "commit-tree", tree, "-m", "one")
    _git(root, "update-ref", "HEAD", commit)
    repo = GitRepo(root)
    name = raw_name.decode("utf-8", "surrogateescape")
    assert repo.changed_files("HEAD") == [name]
    assert os.fsencode(name) == raw_name
    # the index holds the path, the working tree does not: a deletion against HEAD
    assert repo.diff_names("HEAD") == [name]


_FS_PROBE = """
import os, sys
from crb.core.git import GitRepo
if sys.getfilesystemencoding().lower().replace("-", "") == "utf8":
    print("utf8")
    raise SystemExit(0)
raw = bytes.fromhex(sys.argv[2])
repo = GitRepo(sys.argv[1])
for names in (repo.changed_files("HEAD"), repo.diff_names("HEAD")):
    assert names == [os.fsdecode(raw)], names
    assert os.fsencode(names[0]) == raw, names
print("ok")
"""


def test_z_paths_follow_a_non_utf8_filesystem_encoding(tmp_path: Path) -> None:
    """Outside review: under a filesystem encoding that is not UTF-8 a tracked ``café.py``
    is named as :func:`os.fsdecode` names it, so it equals the directory listing's name and
    goes back to git as the same bytes. Run in a child interpreter under the C locale; where
    the platform fixes the filesystem encoding to UTF-8 (macOS) the case cannot arise."""
    root = tmp_path / "repo"
    _fixture_repo(root)
    raw_name = "café.py".encode()
    blob = _git(root, "hash-object", "-w", "--stdin", stdin=b"x = 1\n")
    _git(
        root,
        "update-index",
        "-z",
        "--index-info",
        stdin=b"100644 " + blob.encode() + b"\t" + raw_name + b"\0",
    )
    commit = _git(root, "commit-tree", _git(root, "write-tree"), "-m", "one")
    _git(root, "update-ref", "HEAD", commit)
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    done = subprocess.run(
        [sys.executable, "-c", _FS_PROBE, str(root), raw_name.hex()],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    if done.stdout.strip() == "utf8":
        pytest.skip("this platform fixes the filesystem encoding to UTF-8")
    assert done.stdout.strip() == "ok"


def test_a_non_utf8_path_on_disk_matches_the_filesystem_walk(tmp_path: Path) -> None:
    """Where the filesystem accepts a non-UTF-8 name, ``diff_names`` names it exactly as
    a directory listing does (the comparison the workspace makes)."""
    root = tmp_path / "repo"
    _fixture_repo(root)
    try:
        with open(os.fsencode(root) + b"/bad\xffname.py", "wb") as fh:
            fh.write(b"x = 1\n")
    except OSError as err:
        pytest.skip(f"the filesystem refuses a non-UTF-8 file name: {err}")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "one"], check=True)
    repo = GitRepo(root)
    listed = [p for p in os.listdir(root) if p != ".git"]
    assert repo.changed_files("HEAD") == listed
    (root / listed[0]).write_bytes(b"x = 2\n")
    assert repo.diff_names("HEAD") == listed


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
