"""The served-commit stamp: a server running code the checkout no longer holds, or a UI bundle
built from another commit, reads ``stale`` — never fresh.

Navigation
----------
What it is:   The test suite for src/crb/observability/build_stamp.py and the two build
              recipes that feed it (the vite plugin and the image's build argument).
What it does: Pins that three agreeing commits are not stale; that a server started from one
              commit while the checkout holds another is stale with "restart" in the sentence;
              that a bundle built from another commit is stale with "rebuild"; that a served
              bundle with no stamp is stale; that no bundle is not; that unknown commits are
              never compared (``skipped``, not ``ok``); that the probe is ``degraded`` for
              ``/health`` and ``down`` for ``crb doctor``; that the checkout and behind-count
              readings come from a real git repository; that ``CRB_SOURCE_COMMIT`` wins and
              the process commit is captured once; and that ``ui/vite.config.ts`` writes the
              stamp file this module reads and the Dockerfile carries the commit into both
              stages.
How:          Real throwaway git repositories under ``tmp_path``; a dist directory with and
              without ``build-stamp.json``; the recipes are read as text.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/observability/build_stamp.py (under test), ui/vite.config.ts (the stamp
              writer), deploy/Dockerfile (the image's commit), tests/test_server_system.py
              (the ``/health`` half), tests/test_cli_doctor.py (the doctor half),
              docs/PREVENTION.md (P-002)
Tested by:    (this is a test file)
Touch when:   the stamp's file name or fields change (the plugin, the module and this file
              change together).
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from crb.observability import build_stamp as bs
from crb.observability.probes import DEGRADED, DOWN, OK, SKIPPED

ROOT = Path(__file__).resolve().parent.parent
A = "a" * 40
B = "b" * 40


def _dist(tmp_path: Path, commit: str | None) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    if commit is not None:
        (dist / bs.BUILD_STAMP_FILE).write_text(
            json.dumps({"commit": commit, "built_at": "2026-09-25T00:00:00Z"}), encoding="utf-8"
        )
    return dist


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "f").write_text("1", encoding="utf-8")
    _git(repo, "add", "f")
    _git(repo, "commit", "-q", "-m", "one")
    return repo


def test_agreeing_commits_are_not_stale(tmp_path: Path) -> None:
    r = bs.served_report(server=A, checkout=A, dist=_dist(tmp_path, A))
    assert r == {
        "server_commit": A,
        "checkout_commit": A,
        "ui_commit": A,
        "ui_stamp": bs.UI_STAMPED,
        "stale": False,
        "reasons": [],
    }
    p = bs.probe_build(tmp_path / "dist", server=A, checkout=A)
    assert p.status == OK and p.detail == f"serving {A[:12]} · UI built from the same commit"


def test_a_server_started_before_a_pull_is_stale_and_says_restart() -> None:
    r = bs.served_report(server=A, checkout=B, dist=None)
    assert r["stale"] is True
    assert r["reasons"] == [
        f"the server was started from {A[:12]} but the checkout now holds {B[:12]} — restart "
        "the server (and the worker) to run it"
    ]


def test_a_bundle_built_from_another_commit_is_stale_and_says_rebuild(tmp_path: Path) -> None:
    r = bs.served_report(server=A, checkout=A, dist=_dist(tmp_path, B))
    assert r["stale"] is True and r["ui_commit"] == B
    assert (
        "the UI bundle was built from bbbbbbbbbbbb but the server runs aaaaaaaaaaaa"
        in r["reasons"][0]
    )
    assert "npm --prefix ui run build" in r["reasons"][0]


def test_a_served_bundle_with_no_stamp_is_stale_and_no_bundle_is_not(tmp_path: Path) -> None:
    r = bs.served_report(server=A, checkout=A, dist=_dist(tmp_path, None))
    assert r["stale"] is True and r["ui_stamp"] == bs.UI_UNSTAMPED
    assert "carries no readable build-stamp.json" in r["reasons"][0]
    assert bs.served_report(server=A, checkout=A, dist=None)["stale"] is False
    # an unreadable stamp is not a stamp
    (tmp_path / "dist" / bs.BUILD_STAMP_FILE).write_text("{not json", encoding="utf-8")
    assert bs.ui_stamp(tmp_path / "dist") == ("", bs.UI_UNREADABLE)
    assert bs.served_report(server=A, checkout=A, dist=tmp_path / "dist")["stale"] is True


def test_unknown_commits_are_never_compared_and_never_read_as_fresh(tmp_path: Path) -> None:
    p = bs.probe_build(_dist(tmp_path, B), server="", checkout="")
    assert p.status == SKIPPED and bs.SOURCE_COMMIT_ENV in p.detail
    assert p.data["stale"] is False  # nothing to compare is not a mismatch...
    assert p.status != OK  # ...and it is not reported as fresh either


def test_the_probe_is_degraded_for_health_and_down_for_doctor() -> None:
    health = bs.probe_build(None, server=A, checkout=B)
    doctor = bs.probe_build(None, server=A, checkout=B, stale_status=DOWN)
    assert health.status == DEGRADED and doctor.status == DOWN
    assert health.detail.startswith("STALE: the server was started from")
    assert health.name == doctor.name == "build"


def test_checkout_and_behind_come_from_the_real_repository(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    assert bs.checkout_commit(repo) == head
    assert bs.commits_behind(repo) is None  # no origin/main ref: not guessed
    (repo / "f").write_text("2", encoding="utf-8")
    _git(repo, "commit", "-qam", "two")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "three")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "reset", "-q", "--hard", head)
    assert bs.commits_behind(repo) == 2
    assert bs.checkout_commit(tmp_path / "not-a-repo") == ""


def test_the_default_source_root_is_this_checkout() -> None:
    """P-011: the first draft located the checkout from ``crb.__file__`` — ``None``, because
    ``crb`` is a namespace package — and every ``/health`` raised. The defaults must find
    THIS repository and its real HEAD."""
    assert bs.source_root() == ROOT and (ROOT / "pyproject.toml").is_file()
    assert bs.checkout_commit() == _git(ROOT, "rev-parse", "HEAD")


def test_nothing_in_src_reads_the_namespace_package_file() -> None:
    """The class behind P-011, not only the instance: ``crb`` has no ``__init__.py``, so
    ``crb.__file__`` is ``None`` everywhere — locate files from the module's own
    ``__file__`` instead."""
    assert not (ROOT / "src" / "crb" / "__init__.py").exists()  # still a namespace package
    offenders = [
        f"{p.relative_to(ROOT)}:{node.lineno}"
        for p in (ROOT / "src").rglob("*.py")
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if reads_namespace_file(node)
    ]
    assert offenders == []


def reads_namespace_file(node: ast.AST) -> bool:
    """``crb.__file__`` or ``getattr(crb, "__file__"…)`` — both read the namespace
    package's ``None``."""
    if isinstance(node, ast.Attribute):
        return (
            node.attr == "__file__"
            and isinstance(node.value, ast.Name)
            and (node.value.id == "crb")
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = node.args
        return (
            node.func.id == "getattr"
            and len(args) >= 2
            and isinstance(args[0], ast.Name)
            and args[0].id == "crb"
            and isinstance(args[1], ast.Constant)
            and args[1].value == "__file__"
        )
    return False


def test_the_namespace_guard_catches_the_attribute_and_the_getattr_form() -> None:
    def hits(src: str) -> int:
        return sum(reads_namespace_file(n) for n in ast.walk(ast.parse(src)))

    assert hits("import crb\nx = crb.__file__\n") == 1
    assert hits("import crb\nx = getattr(crb, '__file__', None)\n") == 1
    assert hits("import crb.core.version as v\nx = v.__file__\n") == 0
    assert hits("x = getattr(obj, '__file__')\n") == 0


def test_the_source_commit_variable_wins_and_the_process_commit_is_captured_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bs.process_commit.cache_clear()
    try:
        monkeypatch.setenv(bs.SOURCE_COMMIT_ENV, A)
        assert bs.process_commit() == A
        monkeypatch.setenv(bs.SOURCE_COMMIT_ENV, B)
        assert bs.process_commit() == A  # captured at the first call, not re-read
    finally:
        bs.process_commit.cache_clear()


def test_the_vite_build_writes_the_stamp_this_module_reads() -> None:
    """The contract between the two halves: remove the plugin and the bundle is unstamped."""
    cfg = (ROOT / "ui" / "vite.config.ts").read_text(encoding="utf-8")
    assert "function buildStamp(" in cfg and "buildStamp()" in cfg.split("plugins:", 1)[1]
    assert f"fileName: '{bs.BUILD_STAMP_FILE}'" in cfg
    assert f"process.env.{bs.SOURCE_COMMIT_ENV}" in cfg and "'rev-parse', 'HEAD'" in cfg


def test_the_image_carries_the_commit_into_the_ui_build_and_the_runtime() -> None:
    """An image has no .git: the commit must arrive as a build argument in BOTH stages."""
    text = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    ui_stage = text.split("AS ui-builder", 1)[1].split("\nFROM ", 1)[0]
    runtime = text.split("AS runtime", 1)[1]
    assert f"ARG {bs.SOURCE_COMMIT_ENV}" in ui_stage
    assert f"ARG {bs.SOURCE_COMMIT_ENV}" in runtime
    assert f"{bs.SOURCE_COMMIT_ENV}=${{{bs.SOURCE_COMMIT_ENV}}}" in runtime
