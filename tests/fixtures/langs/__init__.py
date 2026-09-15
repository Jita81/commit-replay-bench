"""Per-language fixture repositories for the runner integration tests.

Every builder module in this package exposes the same two functions::

    build(tmp_path, ...) -> (repo_path, feat_sha)
    config(...)          -> RepoConfig

and every repository has the same two-commit shape — the invariant the runner
tests rely on:

* commit 1 ``chore: initial calc`` — one source unit + one passing test (GREEN);
* commit 2 ``feat: add sub``      — a NEW function AND a NEW test file for it.

Therefore: parent + the feat commit's test overlaid = RED (the test names a
symbol that does not exist yet, so it fails to load/compile/run), and parent +
feat tests + feat sources (the "gold") = GREEN with no new failures.

Where a language's target scope is wider than one file (Go: the package), the
initial commit also carries a *second* unit so the regression belt can be shown
failing independently of the target (see :mod:`gorepo`).

Git here is deliberately hermetic: no global/system config, fixed identity, no
signing — so the shas depend only on content and the timestamps we set.

Navigation
----------
What it is:   The per-language fixture package: hermetic git helpers and the shared two-commit
              repository shape every runner integration test relies on.
What it does: Fixes the invariant — commit 1 is one unit plus one GREEN test, commit 2 adds a
              NEW unit and its NEW test — so that parent + feat tests = RED and parent + feat
              tests + feat sources = GREEN with no new failures, in every language. Git runs with
              no global/system config, a fixed identity and fixed dates.
How:          ``two_commit_repo(root, initial, feat)`` writes the files, commits twice and returns
              ``(root, feat_sha)``; each language module builds its files and calls it.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/langs/gorepo.py, tests/fixtures/langs/noderepo.py,
              tests/fixtures/langs/jvmrepo.py, tests/fixtures/langs/rustrepo.py and
              tests/fixtures/langs/pyrepo_min.py (the builders), tests/conftest_langs.py (the
              instrument steps that consume the shape)
Tested by:    tests/test_runners_go.py, tests/test_runners_node.py, tests/test_runners_jvm.py,
              tests/test_runners_cargo.py, tests/test_sandbox_docker.py
Touch when:   adding a runner for a new language — add ``<lang>repo.py`` beside this file
              exposing ``build`` and ``config`` with the same two-commit shape; never change the
              subjects or dates (shas are content-addressed and tests compare them).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

INITIAL_SUBJECT = "chore: initial calc"
FEAT_SUBJECT = "feat: add sub"

_GIT_ENV: Mapping[str, str] = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "crb fixture",
    "GIT_AUTHOR_EMAIL": "fixture@crb.invalid",
    "GIT_COMMITTER_NAME": "crb fixture",
    "GIT_COMMITTER_EMAIL": "fixture@crb.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


def git(path: Path, *args: str) -> str:
    """Run one git command in ``path`` with the hermetic environment; return stdout."""
    env = {**os.environ, **_GIT_ENV}
    p = subprocess.run(
        ["git", "-C", str(path), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed rc={p.returncode}: {p.stderr[:400]}")
    return p.stdout


def write_files(root: Path, files: Mapping[str, str]) -> None:
    """Write ``{relative_path: content}`` under ``root`` (parents created)."""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def init_repo(root: Path) -> None:
    """``git init`` on branch ``main`` under the hermetic environment."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")


def commit_all(root: Path, subject: str) -> str:
    """Stage everything and commit; return the full sha."""
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", subject)
    return git(root, "rev-parse", "HEAD").strip()


def two_commit_repo(
    root: Path,
    initial: Mapping[str, str],
    feat: Mapping[str, str],
) -> tuple[Path, str]:
    """The shared shape: ``initial`` files → commit 1; ``feat`` files → commit 2."""
    init_repo(root)
    write_files(root, initial)
    commit_all(root, INITIAL_SUBJECT)
    write_files(root, feat)
    feat_sha = commit_all(root, FEAT_SUBJECT)
    return root, feat_sha


__all__ = [
    "FEAT_SUBJECT",
    "INITIAL_SUBJECT",
    "commit_all",
    "git",
    "init_repo",
    "two_commit_repo",
    "write_files",
]
