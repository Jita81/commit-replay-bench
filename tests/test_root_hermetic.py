"""The suite passes as root: no test relies on the kernel refusing root, or on the host's uid.

Navigation
----------
What it is:   Two ratchets over tests/ for the class that turned the ``fresh-clone`` job red
              before its first run (P-258): a test that holds as a developer and fails as
              uid 0, which is how that job runs the suite (``product.evidence.205``).
What it does: Fails when a test expects ``PermissionError`` (or ``OSError``) from a write,
              chmod, unlink or open inside ``pytest.raises`` without asking ``geteuid()``
              first — DAC does not stop root, so the write succeeds and the test fails — and
              when a test passes the host's own ``getuid()`` as a ``user=`` to code that
              refuses root. Each ratchet proves it still sees the shapes it names on a
              planted sample.
How:          ``ast`` over every ``tests/*.py``: the ``with pytest.raises(...)`` blocks and the
              ``user=`` keywords, per enclosing function.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/test_provision_store.py (the seal's write probe it found),
              tests/test_provision_fetch.py (the fetch user it found),
              tests/test_builders_container.py (the sibling ratchet for builder settings on
              the host's uid), .github/workflows/ci.yml (job ``fresh-clone``)
Tested by:    itself (the planted samples)
Touch when:   never for a new repository; a new filesystem call can be refused by mode bits, or a
              new keyword carries a uid into code that refuses root.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

#: Calls whose refusal by mode bits is DAC's, and so never happens to root.
_WRITES = frozenset(
    {
        "write_bytes",
        "write_text",
        "touch",
        "unlink",
        "mkdir",
        "rmdir",
        "rename",
        "replace",
        "chmod",
        "remove",
        "open",
        "rmtree",
        "symlink_to",
        "makedirs",
    }
)
_REFUSALS = frozenset({"PermissionError", "OSError"})


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _mentions(node: ast.AST, word: str) -> bool:
    return any(_name(n) == word for n in ast.walk(node))


def _expects_refusal(item: ast.withitem) -> bool:
    call = item.context_expr
    return (
        isinstance(call, ast.Call)
        and _name(call.func) == "raises"
        and bool(call.args)
        and any(_name(n) in _REFUSALS for n in ast.walk(call.args[0]))
    )


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def dac_refusals(source: str) -> list[str]:
    """Functions that expect the kernel to refuse a write and never ask whether they are
    root."""
    out: list[str] = []
    for fn in _functions(ast.parse(source)):
        if _mentions(fn, "geteuid") or _mentions(fn, "permissions_bind"):
            # root-aware: it decides what root may assert — ``permissions_bind()``
            # (tests/fixtures/tmptree.py) asks the kernel itself, the form feat/ns1's
            # tests/test_tmp_tree_hygiene.py requires for the same class (P-326)
            continue
        for w in (n for n in ast.walk(fn) if isinstance(n, ast.With | ast.AsyncWith)):
            if not any(_expects_refusal(i) for i in w.items):
                continue
            body = ast.Module(body=list(w.body), type_ignores=[])
            calls = [n for n in ast.walk(body) if isinstance(n, ast.Call)]
            if any(_name(c.func) in _WRITES for c in calls):
                out.append(fn.name)
                break
    return out


def host_uid_users(source: str) -> list[str]:
    """Functions that pass the host's own uid as ``user=``: as root that is ``0:…``, which
    the fetch and the sealed builder refuse."""
    out: list[str] = []
    for fn in _functions(ast.parse(source)):
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            if any(k.arg == "user" and _mentions(k.value, "getuid") for k in call.keywords):
                out.append(fn.name)
                break
    return out


def _scan(check: object) -> list[str]:
    assert callable(check)
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if ".cache" in path.parts:
            continue  # the per-session toolchain caches are not tests
        offenders += [f"{path.name}::{f}" for f in check(path.read_text())]
    return offenders


def test_no_test_relies_on_the_kernel_refusing_root_a_write() -> None:
    offenders = _scan(dac_refusals)
    assert not offenders, (
        "these tests expect a write to be refused by mode bits, which root is not: assert "
        "on the bits, and guard the write probe with os.geteuid() != 0 — " + ", ".join(offenders)
    )


def test_no_test_hands_the_hosts_uid_to_code_that_refuses_root() -> None:
    offenders = _scan(host_uid_users)
    assert not offenders, (
        "these tests pass user=<the host's uid>, which is 0 on the fresh-clone job: pass a "
        "fixed non-root uid:gid such as '10001:10001' — " + ", ".join(offenders)
    )


_PLANTED = """\
import os
import pytest


def test_seal_probe(tmp_path):
    p = tmp_path / "x"
    with pytest.raises(PermissionError):
        p.write_bytes(b"tampered")


def test_open_probe(tmp_path):
    with pytest.raises((PermissionError, FileNotFoundError)):
        open(tmp_path / "x", "w")


def test_root_aware(tmp_path):
    if os.geteuid() != 0:
        with pytest.raises(PermissionError):
            (tmp_path / "x").chmod(0o777)


def test_bound_by_permissions(tmp_path):
    if permissions_bind():
        with pytest.raises(PermissionError):
            (tmp_path / "x").write_bytes(b"tampered")


def test_policy_refusal():
    with pytest.raises(PermissionError, match="secrets"):
        load_secrets()


def test_fetch_user(tmp_path):
    fetch_argv(plan, user=f"{os.getuid()}:{os.getgid()}")


def test_fixed_user(tmp_path):
    fetch_argv(plan, user="10001:10001")
"""


def test_the_ratchets_see_the_shapes_they_name() -> None:
    """The pre-fix shapes of the two tests the root run found are caught; a root-aware
    probe (``geteuid`` or feat/ns1's ``permissions_bind``), a refusal the product raises
    itself and a fixed uid are not."""
    assert dac_refusals(_PLANTED) == ["test_seal_probe", "test_open_probe"]
    assert host_uid_users(_PLANTED) == ["test_fetch_user"]
