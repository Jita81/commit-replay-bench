"""The release workflow's tag rules, as testable functions: ``v<pyproject version>`` only,
on a commit ``main`` contains.

``release.yml`` runs this before building anything: on a tag push the tag must be exactly
``v`` + the version in ``pyproject.toml`` (a ``v2.0.0a1`` tag with ``version = "2.0.0a2"``
is refused with a ``::error::`` annotation) AND, with ``--require-on origin/main``, the
tagged commit must be reachable from ``main`` — a release is a tag on the merge commit
(docs/RELEASING.md §2), and before this rule a tag on an unmerged branch commit would have
built, pushed and keylessly signed an image nobody reviewed (CodeRabbit on PR #43,
2026-09-21 — CWE-16). On any other ref both rules are a no-op. Extracted from inline
workflow shell so the rule the tests pin is the rule the workflow runs (CodeRabbit on
PR #5, 2026-09-16 — the old test reconstructed the tag from the version and could not fail).

Navigation
----------
What it is:   The release tag ↔ package version check and the tag ↔ ``main`` provenance check
              (stdlib + ``git``; runs in CI's release ``build`` job and in the test suite).
What it does: ``check(ref_type, ref_name, version, commit=, ref=, cwd=)`` returns ``None`` when
              the ref is not a tag, or the tag is ``v<version>`` and (when ``ref`` is given)
              ``commit`` is reachable from ``ref``; else the error message.
              ``reachable_from(commit, ref, cwd=)`` is ``git merge-base --is-ancestor`` as a
              bool — an unknown ref is False (fail closed). ``main`` reads ``GITHUB_REF_TYPE``
              / ``GITHUB_REF_NAME`` / ``GITHUB_SHA`` (or ``--ref-type`` / ``--ref-name`` /
              ``--commit``) and the version from ``pyproject.toml``, prints them, and exits 1
              with a GitHub ``::error::`` line on a refusal.
How:          ``tomllib`` on ``pyproject.toml`` → string comparison after stripping the ``v``;
              ``subprocess`` → ``git merge-base --is-ancestor`` (exit 0 = reachable) for the
              provenance rule — the caller has fetched the ref first (the workflow's
              ``git fetch --no-tags origin main`` on a full-history checkout).
Layer:        tooling — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   .github/workflows/release.yml (the caller), pyproject.toml (the version),
              src/crb/core/version.py (the same number, pinned equal by
              tests/test_version_consistency.py), docs/RELEASING.md (the release procedure
              and the invariant, §2/§3)
Tested by:    tests/test_version_consistency.py (the version rule),
              tests/test_release_tag.py (the provenance rule, on a temporary git repository)
Touch when:   the tag convention changes (it must change here, in ``release.yml``'s ``on.push.tags``
              and in the cosign identity regexp together); the release contract changes what
              a tag must be reachable from (``--require-on`` in the workflow and RELEASING §2).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pyproject_version(root: Path = ROOT) -> str:
    """The ``[project].version`` in ``pyproject.toml``."""
    with (root / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def reachable_from(commit: str, ref: str, *, cwd: Path = ROOT) -> bool:
    """Whether ``commit`` is an ancestor of (or is) ``ref`` — ``git merge-base --is-ancestor``.
    ``commit`` is peeled (``^{commit}``) so an annotated tag object — what ``GITHUB_SHA``
    can name on a ``git tag -a`` push — is judged by the commit it points at. Exit 0 is
    reachable, 1 is not; any other exit (an unknown ref, not a repository, no ``git``) is
    also False, so a caller that requires provenance fails closed."""
    try:
        done = subprocess.run(
            ["git", "merge-base", "--is-ancestor", f"{commit}^{{commit}}", ref],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return done.returncode == 0


def check(
    ref_type: str,
    ref_name: str,
    version: str,
    *,
    commit: str = "",
    ref: str = "",
    cwd: Path = ROOT,
) -> str | None:
    """``None`` when acceptable; otherwise the reason. Only a tag is checked: it must be
    ``v<version>`` exactly (no ``V``, no missing ``v``, no suffix) and, when ``ref`` is
    given, ``commit`` (the tagged commit) must be reachable from ``ref`` — the release
    main-provenance invariant. The version rule is applied first."""
    if ref_type != "tag":
        return None
    if ref_name != f"v{version}":
        return f"tag {ref_name} does not match pyproject version {version} (expected v{version})"
    if ref and not reachable_from(commit or "HEAD", ref, cwd=cwd):
        return (
            f"tag {ref_name} points at {commit or 'HEAD'}, which is not reachable from {ref} — "
            "a release is a tag on a merged main commit (docs/RELEASING.md §2); "
            "nothing was built"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref-type", default=os.environ.get("GITHUB_REF_TYPE", ""))
    ap.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    ap.add_argument(
        "--commit",
        default=os.environ.get("GITHUB_SHA", ""),
        help="the tagged commit (GITHUB_SHA on a tag push; HEAD when empty)",
    )
    ap.add_argument(
        "--require-on",
        default="",
        metavar="REF",
        help="on a tag, refuse unless the tagged commit is reachable from REF (e.g. origin/main; "
        "fetch it first)",
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    version = pyproject_version(a.root)
    print(
        f"ref_type={a.ref_type or '-'} ref_name={a.ref_name or '-'} commit={a.commit or 'HEAD'} "
        f"pyproject={version} require_on={a.require_on or '-'}"
    )
    problem = check(a.ref_type, a.ref_name, version, commit=a.commit, ref=a.require_on, cwd=a.root)
    if problem:
        print(f"::error::{problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
