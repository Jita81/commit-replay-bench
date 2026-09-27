"""The suite leaves no temporary tree it cannot delete (prevention register P-101).

Navigation
----------
What it is:   The guard against a test leaving a read-only directory under pytest's base
              temporary directory, which pytest then cannot remove.
What it does: Runs the sealing tests in a child pytest with its own base directory and
              proves ``shutil.rmtree`` removes what they leave; pins that
              ``restore_removable`` gives a sealed tree its owner's permissions back
              without following a symbolic link out of the tree, read from the mode bits so
              the test holds as uid 0 too; and refuses any test that expects the operating
              system to refuse on the mode bits anywhere but in the true branch of an
              ``if permissions_bind():`` (P-108, P-112).
How:          A child ``python -m pytest --basetemp`` under ``tmp_path``; a hand-made tree of
              ``0o555`` / ``0o000`` directories and a link to a read-only directory outside;
              a ``shutil.rmtree`` that ignores the mode bits stands in for uid 0; an ``ast``
              walk over every file under ``tests/`` for the ratchet, which follows each
              denial up to its own function looking for that branch.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/fixtures/tmptree.py (``restore_removable``, the helper under test),
              tests/conftest.py (the session finaliser that calls it),
              src/crb/provision/store.py (``seal`` makes the read-only sets the tests leave),
              docs/PREVENTION.md (rows P-101 and P-108)
Tested by:    tests/test_tmp_tree_hygiene.py
Touch when:   never for a new repository (it guards this suite's own tests); a new test
              makes a directory read-only under a temporary path, or expects a refusal the
              mode bits make.
"""

from __future__ import annotations

import ast
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.tmptree import permissions_bind, restore_removable

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


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


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
        assert _mode(d) == 0o555  # the seal, read from the mode bits whoever runs the suite
    locked.parent.chmod(0o000)
    assert _mode(locked.parent) == 0o000
    try:
        if permissions_bind():  # uid 0 with CAP_DAC_OVERRIDE removes it anyway (PR #61)
            assert _can_remove(tree) != ""  # the leak, reproduced
        restore_removable(tree)
        opened = [Path(p) for p, _dirs, _files in os.walk(tree)]
        assert {tree, sealed, sealed.parent, locked, locked.parent} <= set(opened)
        assert all(_mode(d) & stat.S_IRWXU == stat.S_IRWXU for d in opened), opened
        assert _can_remove(tree) == ""
        assert _mode(outside) == 0o555  # the link's target is not ours
    finally:
        outside.chmod(0o755)


def test_the_restore_test_holds_where_permissions_do_not_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #61 review: uid 0 with CAP_DAC_OVERRIDE removes a ``0o555`` / ``0o000`` tree, so a
    test that REQUIRES the removal to fail is wrong there although the clean-up works. Here
    ``shutil.rmtree`` behaves as it does for such a process (it ignores the mode bits)."""
    real_rmtree = shutil.rmtree

    def privileged_rmtree(path: str | os.PathLike[str], *args: object, **kw: object) -> None:
        restore_removable(Path(path))
        real_rmtree(path, *args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(shutil, "rmtree", privileged_rmtree)
    test_restore_removable_opens_a_sealed_tree_and_never_follows_a_link(tmp_path)


def _raises_bare_permission_error(node: ast.AST) -> bool:
    """``pytest.raises(PermissionError | OSError)`` with no ``match=``: an expectation the
    kernel refuses, not the product (a product refusal carries its message)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "raises"
        and bool(node.args)
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in {"PermissionError", "OSError"}
        and not any(k.arg == "match" for k in node.keywords)
    )


def _expects_removal_to_fail(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Call)
        and isinstance(node.left.func, ast.Name)
        and node.left.func.id == "_can_remove"
        and any(isinstance(op, ast.NotEq) for op in node.ops)
    )


def _is_permissions_bind(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "permissions_bind"
    )


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _guarded(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Walk up from ``node`` to its own scope: true when an ``if permissions_bind():`` on
    the way holds ``node`` in its TRUE branch. A call beside the denial, an ``else``, a
    ``not`` or an enclosing function's guard does not guard it."""
    current = node
    while (parent := parents.get(current)) is not None:
        if (
            isinstance(parent, ast.If)
            and current in parent.body
            and _is_permissions_bind(parent.test)
        ):
            return True
        if isinstance(parent, _SCOPES):
            return False
        current = parent
    return False


def _scope_of(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    current = parents.get(node)
    while current is not None and not isinstance(current, _SCOPES):
        current = parents.get(current)
    return current


def unguarded_denials(source: str) -> list[str]:
    """Functions that expect the operating system to refuse an operation on the mode bits
    anywhere but in the true branch of an ``if permissions_bind():`` — they fail under uid 0
    (P-108; the branch, not just a call somewhere in the function, since PR #61, P-112)."""
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        denials = [
            n
            for n in ast.walk(fn)
            if (_raises_bare_permission_error(n) or _expects_removal_to_fail(n))
            and _scope_of(n, parents) is fn
        ]
        if not all(_guarded(n, parents) for n in denials):
            found.append(f"{fn.name}:{fn.lineno}")
    return found


def test_the_ratchet_finds_a_denial_that_does_not_ask_whether_permissions_bind() -> None:
    bare = "def test_x(p):\n    with pytest.raises(PermissionError):\n        p.write_bytes(b'x')\n"
    removal = "def test_y(t):\n    assert _can_remove(t) != ''\n"
    guarded = (
        "def test_z(p):\n    if permissions_bind():\n"
        "        with pytest.raises(PermissionError):\n            p.write_bytes(b'x')\n"
    )
    product = (
        "def test_w():\n    with pytest.raises(PermissionError, match='refused'):\n        f()\n"
    )
    assert unguarded_denials(bare) == ["test_x:1"]
    assert unguarded_denials(removal) == ["test_y:1"]
    assert unguarded_denials(guarded) == []
    assert unguarded_denials(product) == []


def test_the_ratchet_finds_a_denial_outside_the_true_branch_of_the_guard() -> None:
    """A denial counts as guarded only in the true branch of an ``if permissions_bind():``
    in its own function: beside the call, in the ``else``, under ``not``, after the ``if``
    or inside a nested function it is unguarded (P-112)."""
    beside = (
        "def test_u(p):\n    permissions_bind()\n"
        "    with pytest.raises(PermissionError):\n        p.write_bytes(b'x')\n"
    )
    in_else = (
        "def test_v(t):\n    if permissions_bind():\n        pass\n"
        "    else:\n        assert _can_remove(t) != ''\n"
    )
    negated = (
        "def test_n(t):\n    if not permissions_bind():\n        assert _can_remove(t) != ''\n"
    )
    after = (
        "def test_a(t):\n    if permissions_bind():\n        pass\n"
        "    assert _can_remove(t) != ''\n"
    )
    nested = (
        "def test_q(t):\n    if permissions_bind():\n        def inner():\n"
        "            assert _can_remove(t) != ''\n"
    )
    deep = (
        "def test_d(t, ok):\n    if permissions_bind():\n        if ok:\n"
        "            assert _can_remove(t) != ''\n"
    )
    assert unguarded_denials(beside) == ["test_u:1"]
    assert unguarded_denials(in_else) == ["test_v:1"]
    assert unguarded_denials(negated) == ["test_n:1"]
    assert unguarded_denials(after) == ["test_a:1"]
    assert unguarded_denials(nested) == ["inner:3"]
    assert unguarded_denials(deep) == []


def test_no_test_expects_a_permission_denial_without_asking_whether_permissions_bind() -> None:
    """The suite is meant to give one answer as uid 0 (#51); a test that expects the mode
    bits to refuse something must ask first (P-108)."""
    found = [
        f"{path.relative_to(ROOT)}::{hit}"
        for path in sorted((ROOT / "tests").rglob("*.py"))
        for hit in unguarded_denials(path.read_text(encoding="utf-8"))
    ]
    assert found == [], (
        f"{found} expect the operating system to refuse on the mode bits, which uid 0 is not: "
        "check the mode bits directly, and expect the refusal only `if permissions_bind():` "
        "(tests/fixtures/tmptree.py)"
    )
