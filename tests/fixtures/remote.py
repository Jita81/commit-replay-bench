"""A local "remote" for clone tests: a bare repository fed from a fixture clone.

``clone_repo`` refuses ``file://`` by policy, so every test that clones from one of
these sets ``CRB_ALLOW_LOCAL_CLONE=1`` (or passes ``allow_local=True``) — the same
switch a developer machine would use, never a test-only code path in the product.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str) -> str:
    p = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed rc={p.returncode}: {p.stderr}")
    return p.stdout.strip()


def bare_remote(src: Path, dest: Path, *, tag: str = "") -> str:
    """``git init --bare dest`` + push every branch of ``src`` (and ``tag`` when given).

    Returns the ``file://`` URL of the bare repository.
    """
    _git("init", "--bare", "--quiet", "--initial-branch=main", str(dest))
    if tag:
        _git("-C", str(src), "tag", tag)
    _git("-C", str(src), "push", "--quiet", "--all", str(dest))
    if tag:
        _git("-C", str(src), "push", "--quiet", str(dest), f"refs/tags/{tag}")
    return dest.resolve().as_uri()


__all__ = ["bare_remote"]
