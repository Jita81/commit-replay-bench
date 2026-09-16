"""A local "remote" for clone tests: a bare repository fed from a fixture clone.

``clone_repo`` refuses ``file://`` by policy, so every test that clones from one of
these sets ``CRB_ALLOW_LOCAL_CLONE=1`` (or passes ``allow_local=True``) — the same
switch a developer machine would use, never a test-only code path in the product.

Navigation
----------
What it is:   A local "remote" for the clone tests: a bare repository fed from a fixture clone.
What it does: Returns the ``file://`` URL of a bare repository holding every branch (and an
              optional tag) of a fixture, so ``clone_repo`` and the URL-registration paths can be
              exercised without a network. Every consumer sets ``CRB_ALLOW_LOCAL_CLONE=1`` — the
              product's own developer switch, never a test-only code path.
How:          ``git init --bare`` then ``git push --all`` (and the tag) from the source clone.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/git.py (``clone_repo`` and the URL policy under test),
              tests/test_git_clone.py, tests/test_cli_repo_url.py and tests/test_worker_clone.py
              (the consumers), tests/fixtures/pyrepo.py (the usual source)
Tested by:    tests/test_git_clone.py, tests/test_cli_repo_url.py, tests/test_worker_clone.py
Touch when:   the clone policy gains a case a bare ``file://`` remote cannot stand in for (a
              credentialled HTTPS remote needs a real server, not this).
"""

from __future__ import annotations

from pathlib import Path

from fixtures.langs import git


def bare_remote(src: Path, dest: Path, *, tag: str = "") -> str:
    """``git init --bare dest`` + push every branch of ``src`` (and ``tag`` when given).

    Every command runs through the hermetic ``fixtures.langs.git`` helper (fixed identity,
    no user/system config, 120 s timeout) so developer git configuration cannot change the
    repository's shape or push behaviour, and a stalled push cannot block the session
    (CodeRabbit on PR #5, 2026-09-16). Returns the ``file://`` URL of the bare repository.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(dest.parent, "init", "--bare", "--quiet", "--initial-branch=main", str(dest))
    if tag:
        git(src, "tag", tag)
    git(src, "push", "--quiet", "--all", str(dest))
    if tag:
        git(src, "push", "--quiet", str(dest), f"refs/tags/{tag}")
    return dest.resolve().as_uri()


__all__ = ["bare_remote"]
