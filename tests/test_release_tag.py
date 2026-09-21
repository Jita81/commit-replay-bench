"""The release main-provenance invariant: a ``v*`` tag is released only when its commit
is reachable from ``main``.

RELEASING §2 says a release is a tag on the merge commit; before this rule the workflow
checked only the tag's version and the repository, so a tag on an unmerged branch commit
would build, push to GHCR and keylessly sign an image nobody reviewed (CodeRabbit on PR #43,
2026-09-21 — CWE-16). ``scripts/check_release_tag.py`` now carries the check as a function,
``reachable_from``, and the workflow's first step fetches ``main`` and runs the script with
``--require-on origin/main`` — so the rule the suite pins is the rule the pipeline runs.
Proven here on a temporary git repository: a tagged commit on ``main`` is accepted, a tagged
commit on a branch that ``main`` does not contain is refused with the ``::error::``
annotation, and the workflow file calls the rule before building.

Navigation
----------
What it is:   The release main-provenance test suite — ``reachable_from`` and the
              ``--require-on`` refusal, on a throwaway git repository.
What it does: Pins that ``reachable_from`` answers True for a commit on the ref and False for
              one off it (or an unknown ref), that ``main`` with ``--require-on`` exits 1 with a
              ``::error::`` line naming the tag, the commit and the ref for an unmerged commit
              and 0 for a merged one, that a branch push never runs the check, and that
              ``release.yml`` fetches ``main`` with full history and runs the script with
              ``--require-on origin/main`` before ``uv build``.
How:          ``git init`` in ``tmp_path`` (identity via ``-c``; never the developer's config),
              two commits on ``main`` and one on a side branch; the script's functions are
              called in-process; the workflow is read as text.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/check_release_tag.py (under test), .github/workflows/release.yml (the
              caller), docs/RELEASING.md (§2/§3 — the invariant and the tag-protection
              recommendation), tests/test_version_consistency.py (the version half of the
              same script)
Tested by:    tests/test_release_tag.py
Touch when:   the release contract changes what a tag must be reachable from (the script's
              ``--require-on`` default, the workflow step and RELEASING §2 together).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

_SPEC = importlib.util.spec_from_file_location(
    "check_release_tag", ROOT / "scripts" / "check_release_tag.py"
)
assert _SPEC and _SPEC.loader
crt = sys.modules.get("check_release_tag") or importlib.util.module_from_spec(_SPEC)
if "check_release_tag" not in sys.modules:
    sys.modules["check_release_tag"] = crt
    _SPEC.loader.exec_module(crt)

_GIT_ID = ("-c", "user.name=crb-test", "-c", "user.email=crb-test@example.invalid")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *_GIT_ID, *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> dict[str, str | Path]:
    """A repository whose ``main`` holds two commits and whose ``side`` branch holds one
    commit ``main`` does not contain; ``pyproject.toml`` names version ``1.2.3`` on both."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
    _git(r, "add", "pyproject.toml")
    _git(r, "commit", "-q", "-m", "one")
    (r / "a.txt").write_text("a\n")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-q", "-m", "two")
    merged = _git(r, "rev-parse", "HEAD")
    _git(r, "switch", "-q", "-c", "side")
    (r / "b.txt").write_text("b\n")
    _git(r, "add", "b.txt")
    _git(r, "commit", "-q", "-m", "three (unmerged)")
    unmerged = _git(r, "rev-parse", "HEAD")
    _git(r, "tag", "-a", "v1.2.3", "-m", "an annotated tag on the unmerged commit")
    tag_object = _git(r, "rev-parse", "v1.2.3")  # the tag object, not the commit
    _git(r, "switch", "-q", "main")
    return {"path": r, "merged": merged, "unmerged": unmerged, "tag_object": tag_object}


def test_reachable_from_answers_for_a_merged_and_an_unmerged_commit(
    repo: dict[str, str | Path],
) -> None:
    r = Path(repo["path"])
    assert crt.reachable_from(str(repo["merged"]), "main", cwd=r) is True
    assert crt.reachable_from(str(repo["unmerged"]), "main", cwd=r) is False
    # the branch's own commit is reachable from itself; main's commits are its ancestors
    assert crt.reachable_from(str(repo["merged"]), "side", cwd=r) is True
    # an unknown ref is "not reachable", never a crash: the workflow fails closed
    assert crt.reachable_from(str(repo["merged"]), "no-such-ref", cwd=r) is False
    # an annotated tag OBJECT (what GITHUB_SHA can name on a `git tag -a` push) is peeled
    # to its commit — still judged, still refused
    assert repo["tag_object"] != repo["unmerged"]
    assert crt.reachable_from(str(repo["tag_object"]), "main", cwd=r) is False
    assert crt.reachable_from(str(repo["tag_object"]), "side", cwd=r) is True


def test_the_check_refuses_a_tag_whose_commit_is_not_on_the_ref(
    repo: dict[str, str | Path],
) -> None:
    v = "1.2.3"
    assert (
        crt.check("tag", f"v{v}", v, commit=str(repo["merged"]), ref="main", cwd=Path(repo["path"]))
        is None
    )
    problem = crt.check(
        "tag", f"v{v}", v, commit=str(repo["unmerged"]), ref="main", cwd=Path(repo["path"])
    )
    assert problem is not None
    assert f"tag v{v}" in problem and str(repo["unmerged"]) in problem
    assert "not reachable from main" in problem
    # without a ref to require, only the version rule applies (the pre-existing behaviour)
    assert crt.check("tag", f"v{v}", v, commit=str(repo["unmerged"])) is None
    # a branch push never runs either rule
    assert crt.check("branch", "side", v, commit=str(repo["unmerged"]), ref="main") is None


def test_main_with_require_on_exits_one_with_an_error_annotation(
    repo: dict[str, str | Path], capsys: pytest.CaptureFixture[str]
) -> None:
    r = Path(repo["path"])
    base = ["--root", str(r), "--ref-type", "tag", "--ref-name", "v1.2.3", "--require-on", "main"]
    assert crt.main([*base, "--commit", str(repo["merged"])]) == 0
    assert "::error::" not in capsys.readouterr().out
    assert crt.main([*base, "--commit", str(repo["unmerged"])]) == 1
    out = capsys.readouterr().out
    assert re.search(r"^::error::tag v1\.2\.3 .*not reachable from main", out, re.M), out
    # the version rule still runs first, so a wrong tag is refused for that reason
    assert crt.main([*base[:-4], "--ref-name", "v9.9.9", "--commit", str(repo["merged"])]) == 1
    assert "does not match pyproject version" in capsys.readouterr().out


def test_release_workflow_runs_the_main_provenance_check_before_building() -> None:
    """The ``build`` job fetches ``main`` with full history and runs the script with
    ``--require-on origin/main`` before ``uv build`` — the step RELEASING §3 names."""
    text = RELEASE.read_text(encoding="utf-8")
    build = text.split("\n  image:", 1)[0]
    assert "fetch-depth: 0" in build
    fetch = build.index("git fetch --no-tags origin main")
    check = build.index("scripts/check_release_tag.py --require-on origin/main")
    uv_build = build.index("run: uv build")
    assert fetch < check < uv_build
