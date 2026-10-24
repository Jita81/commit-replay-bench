#!/usr/bin/env python3
"""The job-budget guard — a CI job says so when it has crept past 80 % of its own timeout.

A job's ``timeout-minutes`` is a budget, not a quality gate, and a job that grows a little with
every wave reaches it without anyone deciding it should: the day it does, GitHub cancels it and
every pull request waits on a required check no run can finish. The tier-1 walkthrough did
exactly that on PR #57 (cancelled at its 40-minute budget twice, every spec so far passing),
and the py3.13 test job ran 58 of its 60 minutes on the same pull request. This guard turns the
creep into a signal while there is still room to act on it — split the job, never raise the
timeout again (docs/PREVENTION.md P-051).

    # the job's first step starts the clock
    echo "CRB_JOB_STARTED_AT=$(date +%s)" >> "$GITHUB_ENV"
    # its last step (if: always()) reads it
    python3 scripts/ci_job_budget.py --timeout-minutes 40 --mode fail

It always writes the job's elapsed time and its share of the timeout to the job summary. Past
the threshold (``--threshold``, default 0.8) it adds an unmissable block to the summary and an
annotation: ``--mode fail`` exits 1 (every job that runs it: the suite's shards and their
``test`` aggregators since the split, P-053, and the walkthrough jobs); ``--mode warn`` exits 0
with a ``::warning`` — kept for a job being brought under budget, never left there
(tests/test_ci_job_budget.py fails the build while any job only warns). A
missing or unreadable start stamp (``nan`` and ``inf`` included) exits 2 in either mode: a
guard that cannot measure must not read as a pass.

A job that installs a browser has one more question to answer: would it still pass had the
install been as slow as its ``--budget`` allows? ``scripts/ci_install_browser.py`` leaves the
install's time and budget in the job's environment (``CRB_INSTALL_SECONDS``,
``CRB_INSTALL_BUDGET``), and the guard counts the job as over its limit when the elapsed time,
with this run's install replaced by its whole budget, reaches the threshold. Without it the
rest of a job grew into the install's room unseen: by 2026-10-23 the rest of a screens shard
took up to 1178 s of its 1200 s limit while its install was allowed 700 s, and shards failed on
whichever pull request met a slow package mirror (P-813). With it, the pull request that grows
the job is the one that fails, on every run. One of the two variables without the other, or
either unreadable, exits 2 like a missing stamp.

Navigation
----------
What it is:   The job-budget guard (stdlib only), run as the last step of the long CI jobs.
What it does: Reads the job's start stamp (``CRB_JOB_STARTED_AT``, epoch seconds, written by
              the job's first step), computes the elapsed share of ``--timeout-minutes``,
              and, where the job installed a browser, the share it would have used had the
              install taken its whole budget; writes one line (or, past the threshold, an
              alarm block) to ``$GITHUB_STEP_SUMMARY``, prints a GitHub annotation past the
              threshold, and exits 1 in ``fail`` mode past it, 2 when the stamp or the
              install's record is unreadable.
How:          ``assess(elapsed_s, timeout_minutes, threshold)`` → ``Budget``;
              ``summary(budget, job, mode)`` → Markdown; ``main(argv, environ, now)`` wires
              them with no global state, so the tests drive it with a fake clock.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the ``test-shard``, ``test``, ``walkthrough-story``
              and ``walkthrough-screens`` jobs start the clock and run this last),
              docs/PREVENTION.md (P-051 and P-053 — the class it closes; P-813, the install's
              room), scripts/ci_install_browser.py (writes the install's record),
              scripts/walkthrough.sh (the job the class first bit), scripts/ci_test_shards.py
              (the suite's split)
Tested by:    tests/test_ci_job_budget.py
Touch when:   never for a new repository (it measures this repository's own CI jobs); a CI
              job is added whose runtime grows with the product (start its clock and run this
              with its own ``timeout-minutes``); the threshold policy changes.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

#: The environment variable the job's first step writes (epoch seconds).
START_VAR = "CRB_JOB_STARTED_AT"
#: What scripts/ci_install_browser.py leaves for the guard: the install's seconds and its budget.
INSTALL_SECONDS_VAR = "CRB_INSTALL_SECONDS"
INSTALL_BUDGET_VAR = "CRB_INSTALL_BUDGET"
#: The share of the timeout past which a job is over budget.
DEFAULT_THRESHOLD = 0.8
MODES = ("fail", "warn")


@dataclass(frozen=True)
class Install:
    """The job's browser install: how long it took and how long its ``--budget`` allowed."""

    seconds: float
    budget_s: float


@dataclass(frozen=True)
class Budget:
    elapsed_s: float
    timeout_minutes: int
    threshold: float
    install: Install | None = None

    @property
    def share(self) -> float:
        return self.elapsed_s / (self.timeout_minutes * 60)

    @property
    def worst_s(self) -> float:
        """The elapsed time had the install taken its whole budget (never less than elapsed)."""
        if self.install is None:
            return self.elapsed_s
        return max(self.elapsed_s, self.elapsed_s - self.install.seconds + self.install.budget_s)

    @property
    def worst_share(self) -> float:
        return self.worst_s / (self.timeout_minutes * 60)

    @property
    def no_room(self) -> bool:
        """Under the threshold now, but not with the slowest install the budget allows."""
        return not self.share >= self.threshold and self.worst_share >= self.threshold

    @property
    def over(self) -> bool:
        return self.share >= self.threshold or self.no_room


def assess(
    elapsed_s: float,
    timeout_minutes: int,
    threshold: float = DEFAULT_THRESHOLD,
    install: Install | None = None,
) -> Budget:
    """The job's elapsed time against its timeout. Raises ``ValueError`` on a budget that
    cannot be read: a non-positive timeout, a threshold outside (0, 1], a negative elapsed, an
    install that took negative time or had no budget."""
    if timeout_minutes <= 0:
        raise ValueError(f"timeout-minutes must be positive, got {timeout_minutes}")
    if not 0 < threshold <= 1:
        raise ValueError(f"threshold must be in (0, 1], got {threshold}")
    if elapsed_s < 0:
        raise ValueError(f"the start stamp is in the future ({elapsed_s:.0f} s elapsed)")
    if install is not None and (install.seconds < 0 or install.budget_s <= 0):
        raise ValueError(
            f"the browser install's record is not a time and a budget ({install.seconds:.0f} s "
            f"of {install.budget_s:.0f} s)"
        )
    return Budget(elapsed_s, timeout_minutes, threshold, install)


def summary(budget: Budget, job: str, mode: str) -> str:
    """The job-summary Markdown: one line under budget, an alarm block over it."""
    head = (
        f"{budget.elapsed_s / 60:.1f} of {budget.timeout_minutes} min "
        f"({budget.share:.0%} of timeout-minutes; the limit is {budget.threshold:.0%})"
    )
    room = ""
    if budget.install is not None:
        room = (
            f"; with the slowest browser install its budget allows ({budget.install.budget_s:.0f} s;"
            f" this run's took {budget.install.seconds:.0f} s) it would be "
            f"{budget.worst_s / 60:.1f} min ({budget.worst_share:.0%})"
        )
    if not budget.over:
        return f"**Job budget — `{job}`:** {head}{room}.\n"
    consequence = (
        "This job FAILS on it"
        if mode == "fail"
        else "This job still passes (warn mode), but it will not for long"
    )
    if budget.no_room:
        return (
            f"## NO ROOM FOR THE INSTALL — `{job}`: {head}{room}\n\n"
            f"> **{consequence}.** The rest of the job has grown into the time its browser "
            "install is allowed, so a slow package mirror would fail it on a pull request that "
            "changed nothing. Split the job, or lower the install's `--budget` with the "
            "measurement that justifies it — never raise `timeout-minutes` (docs/PREVENTION.md "
            "P-051, P-813).\n"
        )
    return (
        f"## OVER BUDGET — `{job}`: {head}\n\n"
        f"> **{consequence}.** A job that creeps to its timeout is cancelled, and a cancelled "
        "required check blocks every merge. Split the job into parts that run in parallel — "
        "never raise `timeout-minutes` again (docs/PREVENTION.md P-051).\n"
    )


def annotation(budget: Budget, job: str, mode: str) -> str:
    """The workflow command GitHub turns into an annotation on the run (over budget only)."""
    level = "error" if mode == "fail" else "warning"
    if budget.no_room and budget.install is not None:
        return (
            f"::{level} title=job budget::{job} used {budget.share:.0%} of its "
            f"{budget.timeout_minutes}-minute timeout, but {budget.worst_share:.0%} with the "
            f"{budget.install.budget_s:.0f} s its browser install is allowed (limit "
            f"{budget.threshold:.0%}): split it or lower the install's budget "
            "(docs/PREVENTION.md P-813)"
        )
    return (
        f"::{level} title=job budget::{job} used {budget.share:.0%} of its "
        f"{budget.timeout_minutes}-minute timeout (limit {budget.threshold:.0%}): split it "
        "rather than raising the timeout (docs/PREVENTION.md P-051)"
    )


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--timeout-minutes",
        type=int,
        required=True,
        help="the job's own timeout-minutes (tests/test_ci_job_budget.py holds them equal)",
    )
    ap.add_argument("--mode", choices=MODES, required=True, help="fail: exit 1 over budget")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    return ap.parse_args(list(argv))


def main(
    argv: Sequence[str],
    environ: Mapping[str, str] | None = None,
    now: float | None = None,
) -> int:
    args = _parse(argv)
    env = os.environ if environ is None else environ
    job = env.get("GITHUB_JOB", "this job")
    raw = env.get(START_VAR, "").strip()
    try:
        started = float(raw)
    except ValueError:
        started = math.nan
    if not math.isfinite(started):  # float() accepts "nan" and "inf": neither is a time
        print(
            f"::error title=job budget::{START_VAR} is not set to epoch seconds ({raw!r}): the "
            "job's first step must start the clock — the budget cannot be measured",
        )
        return 2
    install_raw = (env.get(INSTALL_SECONDS_VAR), env.get(INSTALL_BUDGET_VAR))
    install = None
    if install_raw != (None, None):
        try:
            install = Install(float(install_raw[0] or ""), float(install_raw[1] or ""))
        except ValueError:
            install = Install(math.nan, math.nan)
        if not (math.isfinite(install.seconds) and math.isfinite(install.budget_s)):
            print(
                f"::error title=job budget::{INSTALL_SECONDS_VAR}={install_raw[0]!r} and "
                f"{INSTALL_BUDGET_VAR}={install_raw[1]!r} are not both seconds: the browser "
                "install's record is unreadable — the job's room for it cannot be measured",
            )
            return 2
    clock = time.time() if now is None else now
    try:
        budget = assess(clock - started, args.timeout_minutes, args.threshold, install)
    except ValueError as exc:
        print(f"::error title=job budget::{exc}")
        return 2
    text = summary(budget, job, args.mode)
    summary_path = env.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write(text)
    print(text, end="")
    if budget.over:
        print(annotation(budget, job, args.mode))
        return 1 if args.mode == "fail" else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
