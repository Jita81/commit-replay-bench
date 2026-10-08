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
to pass its job-budget guard (the screens shards: 700 s, against 485 to 682 s for the rest).
Before the first attempt it writes apt network timeouts into ``/etc/apt/apt.conf.d`` (best
effort: a runner that refuses ``sudo -n`` gets a warning, not a failure), so most stalls end
inside apt itself. Every stopped or failed attempt is a ``::warning``; running out is an
``::error`` and exit 1.

Navigation
----------
What it is:   The bounded, retried Playwright browser install (stdlib only) every CI job that
              needs Chromium runs instead of calling ``playwright install`` itself.
What it does: Runs the install command (``npx playwright install --with-deps chromium``, or the
              one after ``--``) until it succeeds, an attempt stalls (no output for
              ``--idle-timeout`` s) or fails, retrying within ``--attempts`` and ``--budget``;
              exits 0 on success and 1 with an ``::error`` annotation when attempts or budget
              run out. It never leaves a stopped attempt's process group running.
How:          ``write_apt_timeouts`` (best effort, bounded) → for each attempt,
              ``run_attempt`` starts the command with ``start_new_session``, a reader thread
              timestamps every chunk of output, and the poll loop stops the group on idle or
              budget → ``cleanup`` → backoff. ``main(argv, *, run, cleanup, apt, sleep, clock,
              out)`` takes every effect as a parameter, so the tests drive it with real child
              processes and short timeouts.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the ``ui-smoke``, ``walkthrough-story`` and
              ``walkthrough-screens`` jobs run it), docs/PREVENTION.md (P-751 — the class it
              closes), scripts/ci_job_budget.py (the guard that measures the rest of the job)
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

#: The install every browser job needs: Chromium and the system libraries it links against.
DEFAULT_COMMAND = ("npx", "playwright", "install", "--with-deps", "chromium")
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
    """How one attempt ended: ``ok``, ``failed`` (with its exit code), ``stalled`` or
    ``out-of-budget``."""

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


def cleanup() -> None:
    """Kill a root apt-get a stopped attempt left behind (none is the usual case)."""
    _helper(CLEANUP_COMMAND)


def main(
    argv: Sequence[str] | None = None,
    *,
    run: Callable[..., Attempt] = run_attempt,
    cleanup: Callable[[], None] = cleanup,
    apt: Callable[[], bool] = write_apt_timeouts,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    out: TextIO | None = None,
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
    command = [c for c in args.command if c != "--"] or list(DEFAULT_COMMAND)
    if args.attempts < 1 or args.idle_timeout <= 0 or args.budget <= 0 or args.backoff < 0:
        parser.error("--attempts must be at least 1, the timeouts positive, --backoff not negative")

    if not args.no_apt_timeouts and not apt():
        print(
            "::warning title=browser install::could not write apt's network timeouts "
            f"({APT_CONF_PATH}); a stalled mirror is bounded only by the idle timeout",
            file=sink,
        )
    deadline = clock() + args.budget
    for k in range(1, args.attempts + 1):
        print(f"::group::browser install, attempt {k} of {args.attempts}", file=sink, flush=True)
        attempt = run(command, idle_timeout_s=args.idle_timeout, deadline=deadline, out=sink)
        print("::endgroup::", file=sink, flush=True)
        if attempt.outcome == "ok":
            print(
                f"browser install: attempt {k} of {args.attempts} {attempt.describe()}", file=sink
            )
            return 0
        print(
            f"::warning title=browser install::attempt {k} of {args.attempts} {attempt.describe()}",
            file=sink,
            flush=True,
        )
        cleanup()
        if k == args.attempts or clock() + args.backoff >= deadline:
            break
        sleep(args.backoff)
    print(
        f"::error title=browser install::no attempt succeeded within {args.attempts} attempts "
        f"and {args.budget:.0f} s (docs/PREVENTION.md P-751): the package mirror or the browser "
        "download is not answering; rerun the job",
        file=sink,
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
