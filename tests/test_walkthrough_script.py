"""The browser walkthrough's stack runs the checkout under test, never a shared venv's other
checkout (P-052).

Navigation
----------
What it is:   A behavioural test of ``scripts/walkthrough.sh``'s preamble: it runs the script
              with a stand-in interpreter and asserts where the stack's code comes from.
What it does: Runs the script with ``CRB_PYTHON`` pointing at a fake interpreter that reports
              ``crb.server.app`` imported from somewhere other than this checkout's ``src``
              and requires the script to refuse (exit 2, naming both paths) before it builds,
              boots or writes anything; then runs it with an interpreter that honours
              ``PYTHONPATH`` and requires the script to have put ``<checkout>/src`` first.
              Found 2026-09-26: two walkthrough runs on ``feat/ns1-a1`` failed 03b with a
              422 because the shared venv's editable install served another checkout's
              server, which had no ``qualify`` run kind; the same mix can let a run pass on
              code that is not under test.
How:          A temporary bin directory holds the fake ``python`` and ``crb`` and a
              ``dirname``; ``PATH`` is that directory and ``/bin`` only, so a script without
              the check stops at "git is required" instead — and the message check fails.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/walkthrough.sh (the check under test), docs/PREVENTION.md (row P-052),
              ui/e2e/walkthrough/README.md (how the walkthrough is run)
Tested by:    tests/test_walkthrough_script.py
Touch when:   the walkthrough's interpreter checks move or change their wording.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "walkthrough.sh"


def _fake_bin(tmp_path: Path, app_file: str) -> Path:
    """A bin dir whose ``python`` answers the script's import probes and nothing else."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "pythonpath.txt"
    python = bindir / "python"
    python.write_text(
        "#!/bin/sh\n"
        f'printf "%s" "$PYTHONPATH" > "{log}"\n'
        'case "$2" in\n'
        '  "import crb.server.app") exit 0 ;;\n'
        f'  *"print(m.__file__)"*) echo "{app_file}"; exit 0 ;;\n'
        "esac\n"
        "exit 1\n",
        encoding="utf-8",
    )
    crb = bindir / "crb"
    crb.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    for f in (python, crb):
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    dirname = shutil.which("dirname")
    assert dirname, "the test needs dirname"
    (bindir / "dirname").symlink_to(dirname)
    return bindir


def _run(bindir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"CRB_HOME", "CRB_DATABASE_URL", "PYTHONPATH"}
    }
    env["PATH"] = f"{bindir}:/bin"
    env["CRB_PYTHON"] = str(bindir / "python")
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30, check=False
    )


def test_the_walkthrough_refuses_an_interpreter_that_imports_another_checkout(
    tmp_path: Path,
) -> None:
    bindir = _fake_bin(tmp_path, "/elsewhere/commit-replay-bench/src/crb/server/app.py")
    done = _run(bindir)
    assert done.returncode == 2, done.stderr
    assert "not from this checkout" in done.stderr, done.stderr
    assert "/elsewhere/commit-replay-bench/src/crb/server/app.py" in done.stderr
    assert f"{ROOT}/src" in done.stderr
    assert not list(tmp_path.glob("crb-walkthrough.*")), "it must refuse before making a temp dir"


def test_the_walkthrough_puts_this_checkouts_src_first_on_pythonpath(tmp_path: Path) -> None:
    bindir = _fake_bin(tmp_path, f"{ROOT}/src/crb/server/app.py")
    done = _run(bindir)
    # past the check, the script stops at the next prerequisite (git is not on this PATH)
    assert "not from this checkout" not in done.stderr, done.stderr
    assert "git is required" in done.stderr, done.stderr
    seen = (tmp_path / "pythonpath.txt").read_text(encoding="utf-8")
    assert seen.split(":")[0] == f"{ROOT}/src", seen
