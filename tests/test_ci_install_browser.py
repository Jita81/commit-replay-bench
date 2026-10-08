"""The bounded browser install, and the CI jobs that must use it — a dead mirror costs an attempt.

On 7 Oct 2026 ``npx playwright install --with-deps chromium`` hung silently in apt on six
required browser jobs, on pull requests #58, #66 and #69, until each job's own timeout cancelled
it 20 to 40 minutes later (docs/PREVENTION.md P-749). ``scripts/ci_install_browser.py`` stops
an attempt that goes quiet, kills its whole process group and retries within a budget; these
tests drive it with real child processes and sub-second timeouts, and hold every CI job to
calling it. Later that evening the mirror slowed to 15 to 70 kB/s instead, and healthy attempts
sat silent for up to 237 s mid-package, so the defaults are pinned against that measurement too.

Navigation
----------
What it is:   Tests of the bounded, retried browser install and of the CI configuration that
              runs it.
What it does: Pins that a quick install succeeds on attempt 1; that a silent attempt is stopped
              at the idle timeout and retried, and the next one can succeed; that a failing
              exit is retried and running out is an ``::error`` and exit 1; that the overall
              budget, not a per-attempt cap, ends a long run; that a stopped attempt's whole
              process group, grandchild included, is gone; that a progress bar redrawn with
              ``\\r`` counts as output; that a refused apt-config write is only a warning. For
              the configuration: no workflow line runs ``playwright install`` itself, the
              ``ui-smoke``, ``walkthrough-story`` and ``walkthrough-screens`` jobs call the
              wrapper, each passing a ``--budget`` of at most half its ``timeout-minutes``;
              the default idle timeout outlasts the slow mirror's measured silences, and the
              attempts outlast every job's budget, so the budget, not the count, binds.
How:          Calls ``main``/``run_attempt`` with ``sys.executable -c`` commands, a recording
              cleanup and a no-op apt writer; reads ``ci.yml`` as text, job by job.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/ci_install_browser.py (the wrapper), .github/workflows/ci.yml (the jobs),
              docs/PREVENTION.md (P-749), tests/test_ci_job_budget.py (the job parser this
              mirrors)
Tested by:    (this is a test file)
Touch when:   never for a new repository (it reads this repository's own CI); a CI job starts
              installing a Playwright browser (add it to ``INSTALLING``); the wrapper's
              defaults change; a healthy install is measured silent for longer than
              ``SLOW_MIRROR_SILENCE_S``.
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
#: Every job that needs a Playwright browser, and so must install it through the wrapper.
INSTALLING = ("ui-smoke", "walkthrough-story", "walkthrough-screens")
#: The longest silence of a healthy attempt on the slow mirror of 7 Oct 2026 (15 to 70 kB/s; run
#: 37683365608, jobs 113004810354 and 113004810596): apt prints nothing while a package downloads.
SLOW_MIRROR_SILENCE_S = 237
PY = sys.executable


def _mod() -> ModuleType:
    if "ci_install_browser" in sys.modules:
        return sys.modules["ci_install_browser"]
    spec = importlib.util.spec_from_file_location(
        "ci_install_browser", ROOT / "scripts" / "ci_install_browser.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_install_browser"] = mod
    spec.loader.exec_module(mod)
    return mod


def _main(
    argv: list[str], cleanups: list[int] | None = None, apt_ok: bool | None = None
) -> tuple[int, str]:
    """Run ``main`` with no sleeping; skip the apt write unless ``apt_ok`` says how it ends."""
    out = io.StringIO()
    rec = cleanups if cleanups is not None else []
    rc = _mod().main(
        ["--no-apt-timeouts", *argv] if apt_ok is None else argv,
        cleanup=lambda: rec.append(1),
        apt=lambda: bool(apt_ok),
        sleep=lambda _s: None,
        out=out,
    )
    return rc, out.getvalue()


def _py(code: str) -> list[str]:
    return ["--", PY, "-c", code]


# --- the wrapper ----------------------------------------------------------------------------


def test_a_quick_install_succeeds_on_the_first_attempt() -> None:
    cleanups: list[int] = []
    rc, out = _main(["--idle-timeout", "5", *_py("print('installed chromium')")], cleanups)
    assert rc == 0
    assert "installed chromium" in out
    assert "attempt 1 of 5 succeeded" in out
    assert "::warning" not in out and "::error" not in out
    assert cleanups == []


def test_a_silent_attempt_is_stopped_and_retried_and_the_retry_can_succeed(tmp_path: Path) -> None:
    marker = tmp_path / "first-done"
    # Attempt 1 prints, then goes silent (a stalled mirror); attempt 2 finishes at once.
    code = (
        "import pathlib,sys,time\n"
        f"m=pathlib.Path({str(marker)!r})\n"
        "if m.exists():\n    print('ok'); sys.exit(0)\n"
        "m.write_text('1'); print('Get:1 InRelease', flush=True); time.sleep(60)\n"
    )
    cleanups: list[int] = []
    started = time.monotonic()
    rc, out = _main(["--idle-timeout", "0.5", "--budget", "30", *_py(code)], cleanups)
    assert rc == 0
    assert time.monotonic() - started < 20, (
        "the stalled attempt was not stopped at the idle timeout"
    )
    assert "attempt 1 of 5 printed nothing for the idle timeout" in out
    assert "attempt 2 of 5 succeeded" in out
    assert cleanups == [1], "a stopped attempt must be followed by the apt cleanup"


def test_a_failing_install_is_retried_and_running_out_is_an_error() -> None:
    cleanups: list[int] = []
    rc, out = _main(
        ["--attempts", "2", *_py("import sys; print('E: apt'); sys.exit(100)")], cleanups
    )
    assert rc == 1
    assert out.count("::warning title=browser install::") == 2
    assert "exited 100" in out
    assert "::error title=browser install::no attempt succeeded within 2 attempts" in out
    assert "P-749" in out
    assert cleanups == [1, 1]


def test_the_budget_ends_a_run_that_keeps_printing_past_it() -> None:
    # Prints every 0.1 s, so the idle timeout never trips; only the budget can end it.
    code = "import time\nwhile True:\n    print('.', flush=True); time.sleep(0.1)\n"
    started = time.monotonic()
    rc, out = _main(["--idle-timeout", "5", "--budget", "1", *_py(code)])
    assert rc == 1
    assert time.monotonic() - started < 15
    assert "was stopped when the install budget ran out" in out
    assert "attempt 2" not in out, "no attempt may start once the budget is spent"


def test_a_stopped_attempt_leaves_no_process_of_its_group_behind(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"
    # The child starts a grandchild that would outlive it, then both go silent.
    code = (
        "import subprocess,sys,time,pathlib\n"
        "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pidfile)!r}).write_text(str(g.pid))\n"
        "print('started', flush=True); time.sleep(60)\n"
    )
    m = _mod()
    out = io.StringIO()
    attempt = m.run_attempt(
        [PY, "-c", code],
        idle_timeout_s=0.5,
        deadline=time.monotonic() + 30,
        out=out,
        grace_s=2.0,
    )
    assert attempt.outcome == "stalled"
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the grandchild outlived the stopped attempt")


def test_a_progress_bar_redrawn_in_place_counts_as_output() -> None:
    # No newline for 1.5 s, but a redraw every 0.1 s: not a stall at a 0.5 s idle timeout.
    code = (
        "import sys,time\n"
        "for i in range(15):\n"
        "    sys.stdout.write('\\r|' + '#'*i); sys.stdout.flush(); time.sleep(0.1)\n"
        "print(' 100%')\n"
    )
    rc, out = _main(["--idle-timeout", "0.5", *_py(code)])
    assert rc == 0, out
    assert "attempt 1 of 5 succeeded" in out


def test_a_refused_apt_config_write_is_only_a_warning() -> None:
    rc, out = _main(_py("print('ok')"), apt_ok=False)
    assert rc == 0
    assert "::warning title=browser install::could not write apt's network timeouts" in out


def test_the_default_command_is_the_playwright_install_with_system_deps() -> None:
    assert _mod().DEFAULT_COMMAND == ("npx", "playwright", "install", "--with-deps", "chromium")


def test_the_apt_timeouts_keep_apt_silent_for_less_than_the_idle_timeout() -> None:
    m = _mod()
    timeout_m = re.search(r'Acquire::https::Timeout "(\d+)"', m.APT_CONF)
    retries_m = re.search(r'Acquire::Retries "(\d+)"', m.APT_CONF)
    assert timeout_m is not None and retries_m is not None
    timeout, retries = int(timeout_m.group(1)), int(retries_m.group(1))
    default_idle = _defaults()["idle_timeout"]
    assert timeout * (retries + 1) < default_idle


def _defaults() -> dict[str, float]:
    """The wrapper's argparse defaults (idle timeout, budget, attempts), read by running ``main``
    with an empty command line and an attempt that succeeds at once."""
    seen: dict[str, float] = {}

    def run(_cmd: object, *, idle_timeout_s: float, deadline: float, out: object) -> object:
        seen["idle_timeout"] = idle_timeout_s
        seen["budget"] = deadline - now
        return _mod().Attempt("ok", 0, 0.0)

    now = 1000.0
    out = io.StringIO()
    _mod().main([], run=run, apt=lambda: True, cleanup=lambda: None, clock=lambda: now, out=out)
    attempts = re.search(r"attempt 1 of (\d+)", out.getvalue())
    assert attempts is not None
    seen["attempts"] = float(attempts.group(1))
    return seen


def test_the_default_idle_timeout_outlasts_a_slow_mirrors_silence() -> None:
    # A healthy attempt on a slow mirror is silent while each package downloads; stopping it
    # there costs a reconnect for nothing. The margin is for a mirror a little slower still.
    assert _defaults()["idle_timeout"] > SLOW_MIRROR_SILENCE_S


# --- the CI configuration -------------------------------------------------------------------

_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")


def _jobs(text: str) -> dict[str, list[str]]:
    """``{job_id: its lines}`` for the workflow's ``jobs:`` block."""
    lines = text.split("\n")
    start = lines.index("jobs:")
    out: dict[str, list[str]] = {}
    current = ""
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = _JOB_KEY.match(line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _direct_installs(text: str) -> list[str]:
    """Lines that run ``playwright install`` themselves (comments aside)."""
    return [
        ln.strip()
        for ln in text.split("\n")
        if re.search(r"playwright\s+install", ln) and not ln.lstrip().startswith("#")
    ]


def test_no_workflow_runs_playwright_install_itself() -> None:
    for wf in sorted(WORKFLOWS.glob("*.y*ml")):
        assert _direct_installs(wf.read_text("utf-8")) == [], (
            f"{wf.name} runs playwright install directly; call scripts/ci_install_browser.py "
            "(docs/PREVENTION.md P-749)"
        )


def test_the_ban_refuses_a_planted_direct_install() -> None:
    planted = (
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        "          npx playwright install --with-deps chromium\n"
    )
    assert _direct_installs(planted) == ["npx playwright install --with-deps chromium"]
    assert _direct_installs("      # npx playwright install is banned here\n") == []


def _budgets(job: str, text: str | None = None) -> tuple[list[float], int]:
    """The ``--budget`` each of ``job``'s wrapper calls passes, and the job's ``timeout-minutes``."""
    body = _jobs(CI.read_text("utf-8") if text is None else text)[job]
    calls = [ln for ln in body if "ci_install_browser.py" in ln and not ln.lstrip().startswith("#")]
    assert calls, f"{job} must install its browser through scripts/ci_install_browser.py"
    budgets = []
    for ln in calls:
        m = re.search(r"--budget[ =](\d+(?:\.\d+)?)", ln)
        assert m is not None, f"{job} must pass its own --budget: {ln.strip()}"
        budgets.append(float(m.group(1)))
    timeout = next(
        int(m.group(1)) for ln in body if (m := re.match(r"^    timeout-minutes:\s*(\d+)", ln))
    )
    return budgets, timeout


@pytest.mark.parametrize("job", INSTALLING)
def test_each_browser_job_installs_through_the_wrapper_within_half_its_timeout(job: str) -> None:
    budgets, timeout = _budgets(job)
    for budget in budgets:
        assert budget <= timeout * 60 / 2, (
            f"{job}'s install budget of {budget:.0f} s is more than half its {timeout}-minute timeout"
        )


@pytest.mark.parametrize("job", INSTALLING)
def test_the_attempts_outlast_each_jobs_budget(job: str) -> None:
    # Attempts stopped at the idle timeout must not run out before the budget does: on a slow
    # mirror each retry resumes where the last one stopped, so the budget is what should bind.
    d = _defaults()
    for budget in _budgets(job)[0]:
        assert d["attempts"] * d["idle_timeout"] >= budget, (
            f"{d['attempts']:.0f} attempts of {d['idle_timeout']:.0f} s run out before "
            f"{job}'s {budget:.0f} s budget"
        )


def test_the_budget_check_refuses_a_call_with_no_budget() -> None:
    # A call that falls back to the default budget would escape the half-timeout check.
    planted = (
        "jobs:\n  x:\n    timeout-minutes: 20\n    steps:\n      - run: |\n"
        "          python3 ../scripts/ci_install_browser.py\n"
    )
    with pytest.raises(AssertionError, match="must pass its own --budget"):
        _budgets("x", planted)
    assert _budgets("x", planted.replace(".py\n", ".py --budget 600\n")) == ([600.0], 20)
