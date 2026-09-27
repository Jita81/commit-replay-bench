"""scripts/walkthrough.sh refuses to boot a stack whose ``crb`` is another checkout's.

Navigation
----------
What it is:   The regression test for P-060: the walkthrough driver served whatever tree the
              interpreter's ``crb`` import resolved to, so a worktree run against a shared,
              editable venv walked the OTHER checkout's server and reported its results as
              this branch's.
What it does: Builds a throwaway interpreter directory (a ``python`` wrapper and a ``crb``
              stub) and a fake ``crb`` package outside the repository, runs the script with
              ``PYTHONPATH`` pointing at the fake, and asserts it stops with exit code 2 and
              names both trees before it builds, clones or boots anything; and that this
              tree, put first on ``PYTHONPATH``, passes (``CRB_E2E_PREFLIGHT_ONLY=1``).
How:          ``subprocess.run`` of ``bash scripts/walkthrough.sh`` with a scrubbed
              environment (no ``CRB_HOME`` / ``CRB_DATABASE_URL``, so the earlier refusals do
              not fire first); the fake ``crb`` has no ``__init__.py``, like the real one.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/walkthrough.sh (the guard under test), .github/workflows/ci.yml (the
              ``walkthrough`` job runs the positive path on an editable install of this tree),
              docs/PREVENTION.md (P-060, the row this test closes),
              tests/test_walkthrough_axe_settles.py (the other test that holds the
              walkthrough's own behaviour)
Tested by:    tests/test_walkthrough_serves_this_tree.py
Touch when:   the walkthrough's preflight changes order, or it gains another way to choose
              the interpreter it serves with.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_a_crb_from_another_tree_is_refused_before_anything_boots(tmp_path: Path) -> None:
    fake = tmp_path / "other-checkout" / "src"
    (fake / "crb" / "server").mkdir(parents=True)
    # no crb/__init__.py: crb is a namespace package, as it is in src/ (P-011)
    (fake / "crb" / "server" / "__init__.py").write_text("", encoding="utf-8")
    (fake / "crb" / "server" / "app.py").write_text("", encoding="utf-8")
    bindir = tmp_path / "venv" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    crb = bindir / "crb"
    crb.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    python.chmod(0o755)
    crb.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in {"CRB_HOME", "CRB_DATABASE_URL"}} | {
        "CRB_PYTHON": str(python),
        "PYTHONPATH": str(fake),
        "TMPDIR": str(tmp_path),
    }
    r = subprocess.run(
        ["bash", str(ROOT / "scripts" / "walkthrough.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not from this checkout" in r.stderr
    assert str(fake.resolve() / "crb") in r.stderr
    # it stopped before it made its temporary stack
    assert not list(tmp_path.glob("crb-walkthrough.*"))


def test_this_checkout_passes_the_preflight() -> None:
    """The positive half: the interpreter this suite runs under, with this tree's ``src`` first
    on ``PYTHONPATH``, passes the check and the preflight names this tree's ``crb``."""
    bindir = Path(sys.executable).parent
    if not (bindir / "crb").exists():
        import pytest

        pytest.skip("the crb entry point is not installed beside this interpreter")
    env = {k: v for k, v in os.environ.items() if k not in {"CRB_HOME", "CRB_DATABASE_URL"}} | {
        "CRB_PYTHON": sys.executable,
        "PYTHONPATH": str(ROOT / "src"),
        "CRB_E2E_PREFLIGHT_ONLY": "1",
    }
    r = subprocess.run(
        ["bash", str(ROOT / "scripts" / "walkthrough.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"serving {(ROOT / 'src' / 'crb').resolve()}" in r.stdout
