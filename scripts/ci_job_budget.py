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

Navigation
----------
What it is:   The job-budget guard (stdlib only), run as the last step of the long CI jobs.
What it does: Reads the job's start stamp (``CRB_JOB_STARTED_AT``, epoch seconds, written by
              the job's first step), computes the elapsed share of ``--timeout-minutes``,
              writes one line (or, past the threshold, an alarm block) to
              ``$GITHUB_STEP_SUMMARY``, prints a GitHub annotation past the threshold, and
              exits 1 in ``fail`` mode past it, 2 when the stamp is missing.
How:          ``assess(elapsed_s, timeout_minutes, threshold)`` → ``Budget``;
              ``summary(budget, job, mode)`` → Markdown; ``main(argv, environ, now)`` wires
              them with no global state, so the tests drive it with a fake clock.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the ``test-shard``, ``test``, ``walkthrough-story``
              and ``walkthrough-screens`` jobs start the clock and run this last),
              docs/PREVENTION.md (P-051 and P-053 — the class it closes), scripts/walkthrough.sh
              (the job the class first bit), scripts/ci_test_shards.py (the suite's split)
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
#: The share of the timeout past which a job is over budget.
DEFAULT_THRESHOLD = 0.8
MODES = ("fail", "warn")


@dataclass(frozen=True)
class Budget:
    elapsed_s: float
    timeout_minutes: int
    threshold: float

    @property
    def share(self) -> float:
        return self.elapsed_s / (self.timeout_minutes * 60)

    @property
    def over(self) -> bool:
        return self.share >= self.threshold


def assess(elapsed_s: float, timeout_minutes: int, threshold: float = DEFAULT_THRESHOLD) -> Budget:
    """The job's elapsed time against its timeout. Raises ``ValueError`` on a budget that
    cannot be read: a non-positive timeout, a threshold outside (0, 1], a negative elapsed."""
    if timeout_minutes <= 0:
        raise ValueError(f"timeout-minutes must be positive, got {timeout_minutes}")
    if not 0 < threshold <= 1:
        raise ValueError(f"threshold must be in (0, 1], got {threshold}")
    if elapsed_s < 0:
        raise ValueError(f"the start stamp is in the future ({elapsed_s:.0f} s elapsed)")
    return Budget(elapsed_s, timeout_minutes, threshold)


def summary(budget: Budget, job: str, mode: str) -> str:
    """The job-summary Markdown: one line under budget, an alarm block over it."""
    head = (
        f"{budget.elapsed_s / 60:.1f} of {budget.timeout_minutes} min "
        f"({budget.share:.0%} of timeout-minutes; the limit is {budget.threshold:.0%})"
    )
    if not budget.over:
        return f"**Job budget — `{job}`:** {head}.\n"
    consequence = (
        "This job FAILS on it"
        if mode == "fail"
        else "This job still passes (warn mode), but it will not for long"
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
    clock = time.time() if now is None else now
    try:
        budget = assess(clock - started, args.timeout_minutes, args.threshold)
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
