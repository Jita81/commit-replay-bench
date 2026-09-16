"""The release workflow's tag rule, as one testable function: ``v<pyproject version>`` only.

``release.yml`` runs this before building anything: on a tag push the tag must be exactly
``v`` + the version in ``pyproject.toml`` (a ``v2.0.0a1`` tag with ``version = "2.0.0a2"``
is refused with a ``::error::`` annotation); on any other ref it is a no-op. Extracted from
inline workflow shell so the rule the tests pin is the rule the workflow runs (CodeRabbit on
PR #5, 2026-09-16 — the old test reconstructed the tag from the version and could not fail).

Navigation
----------
What it is:   The release tag ↔ package version check (stdlib only; runs in CI's release
              ``build`` job and in the test suite).
What it does: ``check(ref_type, ref_name, version)`` returns ``None`` when the ref is not a tag
              or the tag is ``v<version>``, else the error message; ``main`` reads
              ``GITHUB_REF_TYPE`` / ``GITHUB_REF_NAME`` (or ``--ref-type`` / ``--ref-name``) and
              the version from ``pyproject.toml``, prints the pair, and exits 1 with a GitHub
              ``::error::`` line on a mismatch.
How:          ``tomllib`` on ``pyproject.toml`` → string comparison after stripping the ``v``.
Layer:        tooling — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   .github/workflows/release.yml (the caller), pyproject.toml (the version),
              src/crb/core/version.py (the same number, pinned equal by
              tests/test_version_consistency.py), docs/OPERATOR.md (the release procedure)
Tested by:    tests/test_version_consistency.py
Touch when:   the tag convention changes (it must change here, in ``release.yml``'s ``on.push.tags``
              and in the cosign identity regexp together).
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pyproject_version(root: Path = ROOT) -> str:
    """The ``[project].version`` in ``pyproject.toml``."""
    with (root / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def check(ref_type: str, ref_name: str, version: str) -> str | None:
    """``None`` when acceptable; otherwise the reason. Only a tag is checked, and a tag is
    acceptable only as ``v<version>`` exactly (no ``V``, no missing ``v``, no suffix)."""
    if ref_type != "tag":
        return None
    if ref_name != f"v{version}":
        return f"tag {ref_name} does not match pyproject version {version} (expected v{version})"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref-type", default=os.environ.get("GITHUB_REF_TYPE", ""))
    ap.add_argument("--ref-name", default=os.environ.get("GITHUB_REF_NAME", ""))
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    version = pyproject_version(a.root)
    print(f"ref_type={a.ref_type or '-'} ref_name={a.ref_name or '-'} pyproject={version}")
    problem = check(a.ref_type, a.ref_name, version)
    if problem:
        print(f"::error::{problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
