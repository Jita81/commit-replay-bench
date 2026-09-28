"""The import contracts hold on the tree under test — never on another checkout of ``crb``.

``crb`` is a namespace package. A worktree run with ``PYTHONPATH=<worktree>/src`` against a
virtual environment whose editable install points at another checkout sees ``crb`` in BOTH
places, and ``lint-imports`` then read the other checkout's copy of a module both trees carry:
a forbidden import planted in this worktree's ``crb/factory/review.py`` passed as KEPT
(P-381). This suite runs the contracts itself, in a subprocess whose ``sys.path`` holds this
checkout's ``src`` as the only source of ``crb``, so the full suite fails when a contract
breaks here, whatever the environment's editable install points at.

Navigation
----------
What it is:   A gate over ``pyproject.toml``'s import-linter contracts, run on this checkout.
What it does: Proves the filtered interpreter resolves ``crb`` to this checkout alone, then runs
              ``lint-imports`` there and requires every contract kept, the library's
              "library entries never reach a brief" among them.
How:          ``subprocess`` with ``-c``: drop every ``sys.path`` entry that holds a ``crb``
              package other than ``<root>/src``, then call importlinter's CLI entry point.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md,
              docs/adr/0026-the-context-standard.md (item 10)
Works with:   pyproject.toml (``[tool.importlinter]`` — the contracts it runs),
              docs/PREVENTION.md (P-381, the class it stops), scripts/walkthrough.sh (the same
              refusal of a foreign ``crb`` for the served stack)
Tested by:    this file
Touch when:   never for a new repository; a contract is added or renamed in pyproject.toml.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

_PRELUDE = f"""
import os, sys
src = {str(SRC)!r}
sys.path = [p for p in sys.path if not os.path.isdir(os.path.join(p or '.', 'crb'))]
sys.path.insert(0, src)
"""


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _PRELUDE + code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_the_filtered_interpreter_sees_this_checkout_alone() -> None:
    r = _run("import crb; print(list(crb.__path__))")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == repr([str(SRC / "crb")])


def test_every_import_contract_is_kept_on_the_tree_under_test() -> None:
    pytest.importorskip("importlinter")
    r = _run(
        "from importlinter.cli import lint_imports_command\n"
        "sys.argv = ['lint-imports']\n"
        "raise SystemExit(lint_imports_command())\n"
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-4000:]
    assert "library entries never reach a brief KEPT" in out
    assert " 0 broken" in out
