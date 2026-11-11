#!/usr/bin/env python3
"""The bounded browser install — a stalled package mirror costs one attempt, not the whole job.

``npx playwright install --with-deps chromium`` runs ``apt-get`` as root to fetch the browser's
system libraries, and nothing bounds it. On 7 Oct 2026 the runners' Azure Ubuntu mirror stopped
answering: apt fell back to ``archive.ubuntu.com``, printed its last ``InRelease`` line and then
waited, silently, until each job's own ``timeout-minutes`` cancelled it — six browser jobs on
pull requests #58, #66 and #69, 20 to 40 minutes each, every one a required check
(docs/PREVENTION.md P-751). This wrapper turns the hang into a short, named failure and a retry:

    # in ui/, after npm ci
    python3 ../scripts/ci_install_browser.py

Each attempt runs the install in its own process group. An attempt that prints nothing for
``--idle-timeout`` seconds is stopped: TERM to the group, then KILL, then a bounded
``sudo -n pkill -x apt-get`` so a root apt left behind cannot hold the package lock against the
next attempt. A slow mirror is not a dead one. apt prints one ``Get:`` line as each package
starts and nothing while it downloads, so on 7 Oct 2026, with the mirror serving 15 to 70 kB/s
(run 37683365608, jobs 113004810354 and 113004810596), healthy attempts sat silent for up to
237 s mid-package; the default 300 s outlasts that, and a dead socket ends sooner, inside apt
(the timeouts below give up after 90 s). Stopping a slow attempt costs a reconnect, not its
progress: apt keeps the packages it has fetched and resumes a partial one, so on job
113004810354 the third attempt finished in 40 s a 7.5 MB package the first two had spent 258 s
on, and job 113004810596's 686 s install passed on its third attempt. So attempts repeat, up to
``--attempts``, while the overall ``--budget`` lasts, and the budget, not the attempt count,
decides how slow a mirror a job survives: each job passes at most half its own
``timeout-minutes``, and less where the rest of the job would leave a longer install no room
to pass its job-budget guard. It leaves its time and its budget in ``$GITHUB_ENV``
(``CRB_INSTALL_SECONDS``, ``CRB_INSTALL_BUDGET``), and that guard fails a job whose rest has
grown into the budget's room, on every run rather than on the day a mirror is slow (P-813).
Before the first attempt it writes apt network timeouts into ``/etc/apt/apt.conf.d`` (best
effort: a runner that refuses ``sudo -n`` gets a warning, not a failure), so most stalls end
inside apt itself. Every stopped or failed attempt is a ``::warning``; running out is an
``::error`` and exit 1. The error names a mirror only when an attempt was stopped for silence:
an install that exits non-zero every time says so instead, since a rerun meets the same error
(run 39905786776, 2026-10-23: Playwright refused Ubuntu 26.04 on all five attempts, and the error
blamed the mirror), and a last attempt still printing when the budget ran out is called slow,
not silent.

The system libraries are fetched only when the browser needs them. On 11 Nov 2026 the runners
could not resolve any Ubuntu mirror: apt waited 20 s on each package at each of three mirrors,
kept printing, and the first attempt spent a whole 450 s budget on nine font packages while
every library Chromium links against was already on the image; all nine browser jobs of run
43042027976 failed that way, and three of run 43042354459 (P-816). So the default install now
downloads the browser alone (``npx playwright install chromium``, which never calls apt), then
starts it once (``browser_starts``). A browser that starts is the whole install and apt is
never run; one that does not sends the next attempt down the ``--with-deps`` path above, with
its timeouts and retries. A command given after ``--`` is run as written, with no probe.

Navigation
----------
What it is:   The bounded, retried Playwright browser install (stdlib only) every CI job that
              needs Chromium runs instead of calling ``playwright install`` itself.
What it does: Runs the install (the browser alone, then ``--with-deps`` only if the browser does
              not start; or the command after ``--``) until it succeeds, an attempt stalls (no
              output for
              ``--idle-timeout`` s) or fails, retrying within ``--attempts`` and ``--budget``;
              exits 0 on success and 1 with an ``::error`` annotation when attempts or budget
              run out, and either way records its time and budget for the job's budget guard.
              It never leaves a stopped attempt's process group running.
How:          For each attempt, ``run_attempt`` starts the command with ``start_new_session``,
              a reader thread timestamps every chunk of output, and the poll loop stops the
              group on idle or budget → ``cleanup`` → backoff. A browser-only attempt that
              succeeds is followed by ``browser_starts``; ``write_apt_timeouts`` (best effort,
              bounded) runs before the first attempt that can call apt. ``main(argv, *, run,
              cleanup, apt, sleep, clock, out, record, probe)`` takes every effect as a
              parameter, so the tests drive it with real child processes and short timeouts.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the ``ui-smoke``, ``walkthrough-story`` and
              ``walkthrough-screens`` jobs run it), docs/PREVENTION.md (P-751 — the class it
              closes; P-813, its room; P-816, apt only when needed),
              scripts/ci_job_budget.py (the guard that measures the rest of the job and reads
              this one's record)
Tested by:    tests/test_ci_install_browser.py
Touch when:   never for a new repository (it installs this repository's own CI browser); a CI
              job starts needing a Playwright browser (call this, never ``playwright install``);
              a healthy install is seen to go quiet for longer than the idle timeout.
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

#: What the install leaves for the job's budget guard (scripts/ci_job_budget.py reads them).
SECONDS_VAR = "CRB_INSTALL_SECONDS"
BUDGET_VAR = "CRB_INSTALL_BUDGET"

#: The install that needs apt: Chromium and the system libraries it links against. It runs only
#: after the browser alone was installed and did not start (P-816).
DEFAULT_COMMAND = ("npx", "playwright", "install", "--with-deps", "chromium")
#: The install tried first: the browser download alone, which never calls apt.
BROWSER_ONLY_COMMAND = ("npx", "playwright", "install", "chromium")
#: Starts the installed Chromium once, headless, as the tests will: exit 0 means every system
#: library it links against is already on the image.
PROBE_COMMAND = (
    "node",
    "-e",
    "require('@playwright/test').chromium.launch().then(b => b.close())"
    ".catch(e => { console.error(String(e)); process.exit(1); });",
)
#: apt's own network bounds, written before the first attempt so a dead mirror times out in apt.
#: A dead socket gives up after three tries of 30 s, about 90 s, well inside the idle timeout;
#: a slow download is never cut short by them, since its bytes keep arriving while apt is silent.
APT_CONF_PATH = "/etc/apt/apt.conf.d/99crb-ci-network-timeouts"
APT_CONF = 'Acquire::http::Timeout "30";\nAcquire::https::Timeout "30";\nAcquire::Retries "2";\n'
#: What is left after a stopped attempt that can still hold the package lock: a root apt-get.
CLEANUP_COMMAND = ("sudo", "-n", "pkill", "-KILL", "-x", "apt-get")
#: How long a stopped group gets between TERM and KILL, and any helper command in all.
GRACE_S = 10.0
HELPER_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class Attempt:
    """How one attempt ended: ``ok``, ``failed`` (with its exit code), ``stalled``,
    ``out-of-budget`` or ``unusable`` (the browser alone installed, and did not start)."""

    outcome: str
    returncode: int | None
    seconds: float

    def describe(self) -> str:
        if self.outcome == "failed":
            return f"exited {self.returncode} after {self.seconds:.0f} s"
        if self.outcome == "stalled":
            return (
                f"printed nothing for the idle timeout and was stopped after {self.seconds:.0f} s"
            )
        if self.outcome == "out-of-budget":
            return f"was stopped when the install budget ran out, after {self.seconds:.0f} s"
        if self.outcome == "unusable":
            return (
                f"downloaded Chromium in {self.seconds:.0f} s, but it does not start on this "
                "image without its system libraries"
            )
        return f"succeeded in {self.seconds:.0f} s"


def _stop_group(proc: subprocess.Popen[bytes], grace_s: float) -> None:
    """TERM the attempt's whole process group, then KILL it if it has not gone in ``grace_s``."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sig)
        try:
            proc.wait(timeout=grace_s)
            return
        except subprocess.TimeoutExpired:
            continue


def run_attempt(
    command: Sequence[str],
    *,
    idle_timeout_s: float,
    deadline: float,
    out: TextIO,
    clock: Callable[[], float] = time.monotonic,
    grace_s: float = GRACE_S,
) -> Attempt:
    """Run ``command`` once, echoing its output; stop it after ``idle_timeout_s`` of silence or
    at ``deadline``."""
    started = clock()
    proc = subprocess.Popen(
        list(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True
    )
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    last_output = [started]
    decode = codecs.getincrementaldecoder("utf-8")("replace").decode

    def pump() -> None:
        # Raw chunks, not lines: a progress bar redrawn with ``\r`` is output too.
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                return
            if not chunk:
                return
            last_output[0] = clock()
            out.write(decode(chunk))
            out.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    outcome = ""
    while proc.poll() is None:
        now = clock()
        if now - last_output[0] > idle_timeout_s:
            outcome = "stalled"
        elif now >= deadline:
            outcome = "out-of-budget"
        if outcome:
            _stop_group(proc, grace_s)
            break
        time.sleep(0.1)
    reader.join(timeout=grace_s)
    if not reader.is_alive():
        proc.stdout.close()
    seconds = clock() - started
    if outcome:
        return Attempt(outcome, proc.returncode, seconds)
    return Attempt("ok" if proc.returncode == 0 else "failed", proc.returncode, seconds)


def _helper(command: Sequence[str], stdin: str | None = None) -> bool:
    """Run a bounded helper command; True when it ran and exited 0."""
    try:
        done = subprocess.run(
            list(command),
            input=stdin,
            text=True,
            capture_output=True,
            timeout=HELPER_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def write_apt_timeouts() -> bool:
    """Write apt's network timeouts as root, without prompting; False when the runner refuses."""
    return _helper(("sudo", "-n", "tee", APT_CONF_PATH), stdin=APT_CONF)


def browser_starts(out: TextIO | None = None) -> bool:
    """Start the installed Chromium once and close it; True when it ran. What a failed start
    printed is echoed, so the log says which library is missing."""
    sink = out if out is not None else sys.stdout
    try:
        done = subprocess.run(
            list(PROBE_COMMAND),
            text=True,
            capture_output=True,
            timeout=HELPER_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"browser start probe did not finish: {exc}", file=sink, flush=True)
        return False
    if done.returncode != 0:
        print((done.stdout + done.stderr).strip(), file=sink, flush=True)
    return done.returncode == 0


def cleanup() -> None:
    """Kill a root apt-get a stopped attempt left behind (none is the usual case)."""
    _helper(CLEANUP_COMMAND)


def record_install(seconds: float, budget: float) -> None:
    """Leave the install's time and budget in ``$GITHUB_ENV`` for the job's later steps, so the
    budget guard can ask whether the job has room for the slowest install the budget allows
    (P-813). Outside Actions there is no ``$GITHUB_ENV`` and nothing is written. Neither number
    is rounded to whole seconds: rounded, ``--budget 0.4`` would read as 0, which the guard
    refuses, and an install of 430.6 s would read as 431, which puts the guard's projection
    0.4 s short of the truth and can pass a job that sits on its threshold."""
    path = os.environ.get("GITHUB_ENV", "")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{SECONDS_VAR}={seconds}\n{BUDGET_VAR}={budget:g}\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    run: Callable[..., Attempt] = run_attempt,
    cleanup: Callable[[], None] = cleanup,
    apt: Callable[[], bool] = write_apt_timeouts,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    out: TextIO | None = None,
    record: Callable[[float, float], None] = record_install,
    probe: Callable[[], bool] = browser_starts,
) -> int:
    sink = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--idle-timeout", type=float, default=300.0, help="seconds of silence")
    parser.add_argument("--budget", type=float, default=600.0, help="seconds, all attempts")
    parser.add_argument("--backoff", type=float, default=10.0, help="seconds between attempts")
    parser.add_argument("--no-apt-timeouts", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    custom = [c for c in args.command if c != "--"]
    if args.attempts < 1 or args.idle_timeout <= 0 or args.budget <= 0 or args.backoff < 0:
        parser.error("--attempts must be at least 1, the timeouts positive, --backoff not negative")

    started = clock()
    deadline = started + args.budget
    tried: list[Attempt] = []
    # The default install tries the browser alone first and calls apt only if it does not
    # start (P-816); a command given after ``--`` is run as written.
    browser_only = not custom
    apt_bounded = args.no_apt_timeouts
    for k in range(1, args.attempts + 1):
        if not browser_only and not apt_bounded:
            apt_bounded = True
            if not apt():
                print(
                    "::warning title=browser install::could not write apt's network timeouts "
                    f"({APT_CONF_PATH}); a stalled mirror is bounded only by the idle timeout",
                    file=sink,
                )
        command = custom or list(BROWSER_ONLY_COMMAND if browser_only else DEFAULT_COMMAND)
        print(f"::group::browser install, attempt {k} of {args.attempts}", file=sink, flush=True)
        attempt = run(command, idle_timeout_s=args.idle_timeout, deadline=deadline, out=sink)
        if attempt.outcome == "ok" and browser_only and not probe():
            # Downloaded, but a system library is missing: the next attempt installs them.
            attempt = Attempt("unusable", attempt.returncode, attempt.seconds)
            browser_only = False
        tried.append(attempt)
        print("::endgroup::", file=sink, flush=True)
        if attempt.outcome == "ok":
            print(
                f"browser install: attempt {k} of {args.attempts} {attempt.describe()}", file=sink
            )
            record(clock() - started, args.budget)
            return 0
        print(
            f"::warning title=browser install::attempt {k} of {args.attempts} {attempt.describe()}",
            file=sink,
            flush=True,
        )
        if attempt.outcome == "unusable":
            # Nothing was stopped and no mirror was asked: no apt to clean up, no backoff.
            if k == args.attempts or clock() >= deadline:
                break
            continue
        cleanup()
        if k == args.attempts or clock() + args.backoff >= deadline:
            break
        sleep(args.backoff)
    # An "unusable" attempt asked no mirror and stopped nothing, so it says nothing about the
    # network: the cause is read from the attempts that ran an install to its end.
    installs = [a for a in tried if a.outcome != "unusable"]
    if (
        installs
        and tried[-1].outcome != "unusable"
        and all(a.outcome == "failed" for a in installs)
    ):
        cause = (
            f"the install exited non-zero every time (the last with exit {tried[-1].returncode}), "
            "so read its output above before rerunning: a rerun meets the same error unless the "
            "network caused it"
        )
    elif tried[-1].outcome == "unusable":
        cause = (
            "Chromium was downloaded but does not start, and no attempt or budget was left to "
            "install its system libraries; read the probe's output above"
        )
    elif tried[-1].outcome == "out-of-budget":
        cause = (
            "the budget ran out while the last attempt was still printing, so the download is "
            "slow rather than silent; rerun the job"
        )
    else:
        cause = "the package mirror or the browser download is not answering; rerun the job"
    print(
        f"::error title=browser install::no attempt succeeded within {args.attempts} attempts "
        f"and {args.budget:.0f} s (docs/PREVENTION.md P-751): {cause}",
        file=sink,
        flush=True,
    )
    record(clock() - started, args.budget)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
