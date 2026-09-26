"""The suite leaves no temporary tree it cannot delete (prevention register P-101).

Navigation
----------
What it is:   The guard against a test leaving a read-only directory under pytest's base
              temporary directory, which pytest then cannot remove.
What it does: Runs the sealing tests in a child pytest with its own base directory and
              proves ``shutil.rmtree`` removes what they leave; pins that
              ``restore_removable`` gives a sealed tree its owner's permissions back
              without following a symbolic link out of the tree.
How:          A child ``python -m pytest --basetemp`` under ``tmp_path``; a hand-made tree of
              ``0o555`` / ``0o000`` directories and a link to a read-only directory outside.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/fixtures/tmptree.py (``restore_removable``, the helper under test),
              tests/conftest.py (the session finaliser that calls it),
              src/crb/provision/store.py (``seal`` makes the read-only sets the tests leave),
              docs/PREVENTION.md (row P-101)
Tested by:    tests/test_tmp_tree_hygiene.py
Touch when:   a new test makes a directory read-only under a temporary path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from fixtures.tmptree import restore_removable

ROOT = Path(__file__).resolve().parents[1]

#: Tests that leave sealed (read-only) dependency sets under their ``tmp_path``. Before the
#: session finaliser, pytest renamed each run's base directory to ``garbage-<uuid>`` and left
#: it: about 0.4 GB per full-suite run on a developer machine.
SEALING_TESTS = (
    "tests/test_cli_deps.py::test_ls_verify_and_gc",
    "tests/test_provision_store.py::test_a_changed_byte_is_bundle_integrity",
    "tests/test_execution.py::test_a_bundle_mount_outside_the_store_is_refused",
    "tests/test_builders_container.py::test_builder_cell_mounts_the_parent_set_never_the_gold",
)


def _can_remove(path: Path) -> str:
    """``""`` when ``shutil.rmtree`` removes ``path``, else the error it raised."""
    try:
        shutil.rmtree(path)
    except OSError as e:
        return f"{type(e).__name__}: {e}"
    return ""


def test_the_sealing_tests_leave_a_tree_shutil_can_remove(tmp_path: Path) -> None:
    base = tmp_path / "child-basetemp"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:warnings",
            "-o",
            "addopts=",
            f"--basetemp={base}",
            *SEALING_TESTS,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    try:
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
        assert base.is_dir()
        assert _can_remove(base) == ""
    finally:
        restore_removable(tmp_path)  # never let this test leak what it is testing for


def test_restore_removable_opens_a_sealed_tree_and_never_follows_a_link(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("x", encoding="utf-8")
    outside.chmod(0o555)
    tree = tmp_path / "tree"
    sealed = tree / "dep_x" / "gomod"
    sealed.mkdir(parents=True)
    (sealed / "f").write_text("x", encoding="utf-8")
    (sealed / "f").chmod(0o444)
    (tree / "dep_x" / "link").symlink_to(outside)
    locked = tree / "locked" / "sub"
    locked.mkdir(parents=True)
    for d in (sealed, sealed.parent, locked):
        d.chmod(0o555)
    locked.parent.chmod(0o000)
    try:
        assert _can_remove(tree) != ""  # the leak, reproduced
        restore_removable(tree)
        assert _can_remove(tree) == ""
        assert (outside.stat().st_mode & 0o777) == 0o555  # the link's target is not ours
    finally:
        outside.chmod(0o755)
