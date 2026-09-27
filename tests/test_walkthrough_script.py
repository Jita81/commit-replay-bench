"""The walkthrough serves the checkout it was run from — never another tree's code.

``scripts/walkthrough.sh`` starts ``crb serve`` and ``crb worker`` from an interpreter it is
given. With a shared virtual environment whose editable install points at another checkout,
``import crb`` resolved to THAT checkout, so a walkthrough run from a worktree tested another
tree's code and passed or failed on it (docs/PREVENTION.md P-061; reproduced on 2026-09-26: two
specs failed on the shared checkout's pre-ADR-0022 intake and passed 68 of 68 on the
branch's own code). The script now puts its own ``src`` first on ``PYTHONPATH`` and refuses
to start when any ``crb`` module the stack loads comes from elsewhere.

Navigation
----------
What it is:   The tests for walkthrough.sh's preflight: which checkout the stack imports.
What it does: Runs the real script with ``CRB_E2E_PREFLIGHT_ONLY=1`` (it stops before creating
              anything) and asserts it accepts this checkout; runs a copy of the script in a
              tree whose ``src`` does not carry the server and asserts it refuses, naming the
              module it would have served from elsewhere.
How:          ``subprocess.run(["bash", script])`` with ``CRB_PYTHON`` set to this interpreter
              and ``CRB_HOME``/``CRB_DATABASE_URL`` removed from the environment.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/walkthrough.sh (under test), docs/PREVENTION.md (P-061),
              .github/workflows/ci.yml (the walkthrough job that runs the whole script)
Tested by:    (this is a test file)
Touch when:   the walkthrough starts another process that imports crb (add it to the guard's
              module list).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "walkthrough.sh"


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CRB_HOME", "CRB_DATABASE_URL")}
    env.pop("PYTHONPATH", None)
    env["CRB_PYTHON"] = sys.executable
    env["CRB_E2E_PREFLIGHT_ONLY"] = "1"
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, timeout=120, check=False
    )


def test_the_walkthrough_imports_crb_from_its_own_checkout() -> None:
    done = _run(SCRIPT)
    assert done.returncode == 0, done.stderr
    assert f"crb imports from {ROOT / 'src'}" in done.stderr


def test_the_walkthrough_refuses_to_serve_another_checkouts_code(tmp_path: Path) -> None:
    """A tree whose own ``src`` lacks the server: ``crb.cli.main`` can only come from another
    checkout (this interpreter's install), and the script must say so and stop."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "crb").mkdir(parents=True)
    (tmp_path / "ui").mkdir()
    copy = tmp_path / "scripts" / "walkthrough.sh"
    shutil.copy2(SCRIPT, copy)
    done = _run(copy)
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert "walkthrough: the stack would serve crb from outside" in done.stderr
    assert "crb.cli.main" in done.stderr
