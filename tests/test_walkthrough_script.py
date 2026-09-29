"""The walkthrough serves the checkout it was run from — never another tree's code — and
tier 1 is hermetic by construction: the stack it boots can never credential a real builder.

``scripts/walkthrough.sh`` starts ``crb serve`` and ``crb worker`` from an interpreter it is
given. With a shared virtual environment whose editable install points at another checkout,
``import crb`` resolved to THAT checkout, so a walkthrough run from a worktree tested another
tree's code and passed or failed on it (docs/PREVENTION.md P-128; reproduced on 2026-09-26: two
specs failed on the shared checkout's pre-ADR-0022 intake and passed 68 of 68 on the
branch's own code). The script now puts its own ``src`` first on ``PYTHONPATH`` and refuses
to start when any ``crb`` module the stack loads comes from elsewhere.

Navigation
----------
What it is:   The tests for walkthrough.sh's preflight: which checkout the stack imports, and
              that tier 1 hides the operator's ``claude`` from the stack's PATH (P-663).
What it does: Runs the real script with ``CRB_E2E_PREFLIGHT_ONLY=1`` (it stops before creating
              anything) and asserts it accepts this checkout; runs a copy of the script in a
              tree whose ``src`` does not carry the server and asserts it refuses, naming the
              module it would have served from elsewhere; with a fake ``claude`` on PATH,
              asserts the preflight says tier 1 will hide it and that tier 2
              (``CRB_E2E_BUILDER`` set) says nothing; and sources the script's own
              ``hide_cli_from_path`` to assert the PATH it prints resolves no ``claude`` while
              every other executable of the same directory still resolves.
How:          ``subprocess.run(["bash", script])`` with ``CRB_PYTHON`` set to this interpreter
              and ``CRB_HOME``/``CRB_DATABASE_URL`` removed from the environment; the function
              cut from the script's text and run under ``bash -c``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/walkthrough.sh (under test), docs/PREVENTION.md (P-128, P-663),
              src/crb/observability/probes.py (``probe_builders`` reads ``shutil.which``),
              ui/e2e/walkthrough/05-replay-fake.spec.ts (the tier-1 refusal this keeps green),
              .github/workflows/ci.yml (the walkthrough job that runs the whole script)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the walkthrough starts another process that imports crb
              (add it to the guard's module list); the builders probe reads a new CLI from PATH
              (hide it the same way).
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "walkthrough.sh"


def _run(script: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CRB_HOME", "CRB_DATABASE_URL", "CRB_E2E_BUILDER")
    }
    env.pop("PYTHONPATH", None)
    env["CRB_PYTHON"] = sys.executable
    env["CRB_E2E_PREFLIGHT_ONLY"] = "1"
    env.update(extra)
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, timeout=120, check=False
    )


def _fake_bin(tmp_path: Path, *names: str) -> Path:
    """A directory of executables named ``names`` (a stand-in for the operator's bin)."""
    d = tmp_path / "fakebin"
    d.mkdir()
    for name in names:
        f = d / name
        f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return d


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


def test_tier_1_preflight_says_it_will_hide_the_operators_claude(tmp_path: Path) -> None:
    """P-663: a ``claude`` on PATH made /health credential a CLI login, the money page offer a
    real builder and 05 refuse the red button. Tier 1 now hides it, and says so before it
    creates anything; tier 2 (``CRB_E2E_BUILDER`` set) keeps the operator's PATH and is silent."""
    fake = _fake_bin(tmp_path, "claude")
    path = f"{fake}{os.pathsep}{os.environ.get('PATH', '')}"
    tier1 = _run(SCRIPT, PATH=path)
    assert tier1.returncode == 0, tier1.stderr
    assert f"tier 1 is hermetic — the stack's PATH will hide {fake / 'claude'}" in tier1.stderr
    tier2 = _run(SCRIPT, PATH=path, CRB_E2E_BUILDER="claude_code")
    assert tier2.returncode == 0, tier2.stderr
    assert "will hide" not in tier2.stderr


def test_hide_cli_from_path_removes_claude_and_keeps_every_other_executable(
    tmp_path: Path,
) -> None:
    """The script's own function, cut from its text: the PATH it prints resolves no ``claude``,
    while ``git`` from the same directory (and the directories that held no ``claude``) still
    resolve — so the stack loses the CLI login and nothing else."""
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"^hide_cli_from_path\(\) \{.*?^\}$", text, re.S | re.M)
    assert m, "walkthrough.sh no longer defines hide_cli_from_path"
    fake = _fake_bin(tmp_path, "claude", "git", "node")
    other = tmp_path / "other"
    other.mkdir()
    tool = other / "tool"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    shim = tmp_path / "shim"
    probe = (
        m.group(0)
        + f'\nnew="$(hide_cli_from_path claude {shim})"\n'
        + 'echo "PATH=$new"\n'
        + 'PATH="$new" command -v claude || echo "claude: NONE"\n'
        + 'for t in git node tool; do PATH="$new" command -v "$t" || echo "$t: NONE"; done\n'
    )
    bash = shutil.which("bash")
    assert bash, "bash is required to run the walkthrough"
    done = subprocess.run(
        [bash, "-c", probe],
        # mkdir and ln come from the system directories, as on any machine the script runs on
        env={
            "PATH": os.pathsep.join([str(fake), str(other), "/usr/bin", "/bin"]),
            "HOME": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert "claude: NONE" in lines, done.stdout
    for t in ("git", "node", "tool"):
        assert f"{t}: NONE" not in lines, done.stdout
    # the directory that held claude is replaced by a shim of symlinks; the other is kept as is
    new_path = next(line for line in lines if line.startswith("PATH=")).removeprefix("PATH=")
    assert str(fake) not in new_path.split(os.pathsep)
    assert str(other) in new_path.split(os.pathsep)
    assert (shim / str(fake).replace("/", "_") / "git").is_symlink()
    assert not (shim / str(fake).replace("/", "_") / "claude").exists()
