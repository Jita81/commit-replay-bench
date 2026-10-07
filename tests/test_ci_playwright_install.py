"""The CI browser install — every network wait bounded and retried, so a stalled mirror costs
one attempt, never the job (P-751).

On PR #69 ``npx playwright install --with-deps chromium`` stalled inside ``apt-get update``
until GitHub cancelled ``walkthrough-story`` at its 40-minute timeout with no spec run: a
runner's network fault became a red required check. ``scripts/ci_playwright_install.sh``
bounds each attempt with ``timeout`` and retries it; these tests drive it against a fake
``playwright`` and pin that every job that drives a browser installs through it.

Navigation
----------
What it is:   Tests of the bounded Playwright install and of the CI steps that run it.
What it does: Runs the script against fake ``sudo``, ``timeout``, ``dpkg`` and ``playwright``
              executables: a stalled first system-package attempt is cut off at its bound and
              retried after ``dpkg --configure -a``, and the browser then installs; a phase
              that fails every attempt exits 1 naming P-751 and never reaches the next phase; a
              bad setting exits 2 before any install; apt's network timeouts and retries are
              written. Then reads ``ci.yml``: no step runs a bare ``playwright install``, and
              every job that drives a browser (``npx playwright test`` or
              ``scripts/walkthrough.sh``) installs through the script from ``ui/``.
How:          ``subprocess.run(["bash", script])`` from a temp ``ui`` directory, with a stub
              directory first on ``PATH``; the fake ``timeout`` enforces its bound with
              ``subprocess.run(timeout=…)`` and exits 124 like GNU timeout; each stub appends
              its argv to a calls file. ``ci.yml`` is read as text, job by job (the job-budget
              test's reader).
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/ci_playwright_install.sh (the script), .github/workflows/ci.yml (the jobs
              that run it), tests/test_ci_job_budget.py (the workflow reader it copies),
              docs/PREVENTION.md (P-751)
Tested by:    (this is a test file)
Touch when:   never for a new repository (it reads this repository's own CI); a job starts
              driving a browser; the script's phases, bounds or exit codes change.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_playwright_install.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"

_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")


def _jobs(text: str) -> dict[str, list[str]]:
    """``{job_id: its lines}`` for the workflow's ``jobs:`` block (tests/test_ci_job_budget.py's
    reader: no YAML dependency)."""
    lines = text.split("\n")
    out: dict[str, list[str]] = {}
    current = ""
    for line in lines[lines.index("jobs:") + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = _JOB_KEY.match(line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _steps(body: list[str]) -> list[str]:
    """Each step of a job as one text block (a step starts at ``      - ``)."""
    steps: list[list[str]] = []
    in_steps = False
    for line in body:
        if line.rstrip() == "    steps:":
            in_steps = True
        elif in_steps and line.startswith("      - "):
            steps.append([line])
        elif in_steps and steps:
            steps[-1].append(line)
    return ["\n".join(s) for s in steps]


#: GNU timeout's contract, enough of it for the script: ``timeout [--kill-after=N] SECONDS
#: CMD…`` runs CMD, and exits 124 when CMD outlives SECONDS.
_FAKE_TIMEOUT = """\
import os, subprocess, sys
args = sys.argv[1:]
while args[0].startswith("--"):
    args = args[1:]
seconds, cmd = float(args[0]), args[1:]
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write("timeout " + " ".join(sys.argv[1:]) + "\\n")
try:
    sys.exit(subprocess.run(cmd, timeout=seconds).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
"""

#: A fake ``playwright`` whose behaviour per phase comes from the environment:
#: ``FAKE_DEPS`` / ``FAKE_BROWSER`` is a comma list, one entry per call — ``ok``, ``fail`` or
#: ``hang`` (sleeps far past any bound the tests set); the last entry repeats.
_FAKE_PLAYWRIGHT = """\
import os, sys, time
phase = "deps" if sys.argv[1] == "install-deps" else "browser"
log = os.environ["FAKE_CALLS"]
with open(log, "a") as calls:
    calls.write("playwright " + " ".join(sys.argv[1:]) + "\\n")
n = sum(1 for line in open(log) if line.startswith("playwright " + sys.argv[1] + " "))
plan = os.environ["FAKE_" + phase.upper()].split(",")
what = plan[min(n, len(plan)) - 1]
if what == "hang":
    time.sleep(60)
sys.exit(0 if what == "ok" else 1)
"""


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A ``ui`` directory with a fake playwright, a stub ``bin`` and the calls file."""
    ui = tmp_path / "ui"
    (ui / "node_modules" / ".bin").mkdir(parents=True)
    calls = tmp_path / "calls.log"
    calls.touch()
    _executable(
        ui / "node_modules" / ".bin" / "playwright", f"#!{sys.executable}\n{_FAKE_PLAYWRIGHT}"
    )
    stubs = tmp_path / "bin"
    stubs.mkdir()
    # sudo and dpkg record themselves; sudo then runs its command as this user.
    _executable(stubs / "sudo", f'#!/bin/sh\necho "sudo $*" >> "{calls}"\nexec "$@"\n')
    _executable(stubs / "dpkg", f'#!/bin/sh\necho "dpkg $*" >> "{calls}"\n')
    _executable(stubs / "timeout", f"#!{sys.executable}\n{_FAKE_TIMEOUT}")
    return ui, stubs, calls


def _run(
    tmp_path: Path, *, deps: str, browser: str, **settings: str
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    ui, stubs, calls = _setup(tmp_path)
    apt_conf = tmp_path / "80-crb-ci-network"
    env = {
        **os.environ,
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CALLS": str(calls),
        "FAKE_DEPS": deps,
        "FAKE_BROWSER": browser,
        "CRB_APT_CONF": str(apt_conf),
        "CRB_PW_DEPS_SECONDS": "2",
        "CRB_PW_BROWSER_SECONDS": "2",
        **settings,
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT)], cwd=ui, env=env, capture_output=True, text=True, timeout=120
    )
    return proc, calls.read_text("utf-8").splitlines(), apt_conf


def _playwright_calls(calls: list[str]) -> list[str]:
    return [c.removeprefix("playwright ") for c in calls if c.startswith("playwright ")]


# --- the script ------------------------------------------------------------------------------


def test_a_stalled_system_package_attempt_is_cut_off_and_retried_then_the_browser_installs(
    tmp_path: Path,
) -> None:
    proc, calls, apt_conf = _run(tmp_path, deps="hang,ok", browser="ok")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _playwright_calls(calls) == [
        "install-deps chromium",
        "install-deps chromium",
        "install chromium",
    ]
    assert "hit its time bound (exit 124)" in proc.stdout
    # The retry first finishes whatever the killed attempt left half-configured.
    deps_at = [i for i, c in enumerate(calls) if c == "playwright install-deps chromium"]
    assert deps_at[0] < calls.index("dpkg --configure -a") < deps_at[1]
    # Every install ran under its bound; the system packages ran as root, the browser did not.
    bounded = [c for c in calls if c.startswith("timeout ")]
    assert bounded == [
        "timeout --kill-after=15 2 ./node_modules/.bin/playwright install-deps chromium",
        "timeout --kill-after=15 2 ./node_modules/.bin/playwright install-deps chromium",
        "timeout --kill-after=15 2 ./node_modules/.bin/playwright install chromium",
    ]
    as_root = [c for c in calls if c.startswith("sudo env ")]
    assert len(as_root) == 2
    assert all("playwright install-deps chromium" in c for c in as_root)
    assert apt_conf.read_text("utf-8").splitlines() == [
        'Acquire::Retries "3";',
        'Acquire::http::Timeout "30";',
        'Acquire::https::Timeout "30";',
        'DPkg::Lock::Timeout "60";',
    ]


def test_a_failed_browser_download_is_retried(tmp_path: Path) -> None:
    proc, calls, _ = _run(tmp_path, deps="ok", browser="fail,hang,ok")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _playwright_calls(calls).count("install chromium") == 3
    assert "browser installed on attempt 3 of 3" in proc.stdout
    assert "dpkg --configure -a" not in calls  # only a system-package retry repairs dpkg


def test_a_phase_that_fails_every_attempt_fails_the_step_and_names_the_class(
    tmp_path: Path,
) -> None:
    proc, calls, _ = _run(tmp_path, deps="fail", browser="ok", CRB_PW_ATTEMPTS="2")
    assert proc.returncode == 1
    assert _playwright_calls(calls) == ["install-deps chromium"] * 2
    assert "::error::ci_playwright_install: deps failed on all 2 attempts" in proc.stdout
    assert "P-751" in proc.stdout


def test_a_bad_setting_is_refused_before_anything_is_installed(tmp_path: Path) -> None:
    for setting in ({"CRB_PW_ATTEMPTS": "0"}, {"CRB_PW_DEPS_SECONDS": "ten"}):
        where = tmp_path / next(iter(setting))
        proc, calls, apt_conf = _run(where, deps="ok", browser="ok", **setting)
        assert proc.returncode == 2, setting
        assert calls == [] and not apt_conf.exists(), setting


def test_run_outside_ui_it_refuses_rather_than_installing_nothing(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 2
    assert "run it from ui/ after npm ci" in proc.stderr


# --- the CI configuration ----------------------------------------------------------------------


def _code(step: str) -> str:
    """A step's text without its comment lines (a comment may name what it forbids)."""
    return "\n".join(ln for ln in step.split("\n") if not ln.lstrip().startswith("#"))


def test_no_ci_step_runs_a_bare_playwright_install() -> None:
    for job, body in _jobs(CI.read_text("utf-8")).items():
        for step in _steps(body):
            assert not re.search(r"playwright\s+install", _code(step)), (
                f"{job}: a bare `playwright install` has no bound on its network waits — run "
                "scripts/ci_playwright_install.sh from ui/ instead (P-751)"
            )


def test_every_job_that_drives_a_browser_installs_through_the_script() -> None:
    jobs = _jobs(CI.read_text("utf-8"))
    browser_jobs = [
        job
        for job, body in jobs.items()
        if any(
            re.search(r"npx playwright test|scripts/walkthrough\.sh", _code(s))
            for s in _steps(body)
        )
    ]
    assert {"ui-smoke", "walkthrough-story", "walkthrough-screens"} <= set(browser_jobs)
    for job in browser_jobs:
        installs = [s for s in _steps(jobs[job]) if "ci_playwright_install.sh" in _code(s)]
        assert len(installs) == 1, f"{job}: drives a browser but never runs the bounded install"
        assert re.search(r"^\s+working-directory: ui\s*$", installs[0], re.M), (
            f"{job}: the install must run from ui/, where @playwright/test is installed"
        )
        assert "bash ../scripts/ci_playwright_install.sh" in installs[0]
