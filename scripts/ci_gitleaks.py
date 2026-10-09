#!/usr/bin/env python3
"""The secrets scan — every commit a pull request adds, and the whole history on main.

``gitleaks/gitleaks-action@v3`` chose the commits to scan on a pull request from one page of
``GET /pulls/{n}/commits`` (its ``ScanPullRequest``: no ``per_page``, so 30 commits) and scanned
``--no-merges --first-parent <first>^..<last>`` of that page. On pull request #74 the security job
of run 37854206126 at ``0b788b13`` scanned ``87f8b4db^..2cf9df77``: 15 of the 558 non-merge
commits the pull request adds, and not its head (docs/PREVENTION.md P-773). A secret committed
after the thirtieth commit of a long pull request never met the gate. This wrapper names the range
from the event itself instead:

    # in the security job, after the pinned, checksum-verified gitleaks install
    python3 scripts/ci_gitleaks.py

On ``pull_request`` it scans ``<base sha>..<head sha>``: every commit the head reaches that the base
does not, the head included. On a push to a protected branch, the daily schedule and a manual
run it scans everything the checked-out commit reaches (``HEAD``) — about four seconds for the
whole repository — so a finding anywhere in main's history fails main, not the next pull request.
An event with no range here is refused: a new trigger must say what it scans.

``git log -p`` prints no patch for a merge commit, so text a conflict resolution adds appears in
no scanned commit of the pull request; the squash commit it becomes on main carries it, and main's
push scan reads that.

Navigation
----------
What it is:   The security job's gitleaks invocation (stdlib only): the scan range for the event,
              then ``gitleaks git`` over it with the repository's ``.gitleaks.toml``.
What it does: Maps ``EVENT_NAME`` (with ``BASE_SHA``/``HEAD_SHA`` on a pull request) to a
              ``--log-opts`` range, prints how many commits the range holds, runs
              ``$GITLEAKS git --redact`` and exits with its code: 0 clean, 2 leaks found (an
              ``::error``), anything else a failed scan (an ``::error``). An event with no range,
              or a pull request with no base or head commit, exits 1 before scanning.
How:          ``log_opts`` → ``command`` → ``main(argv, *, env, run, out)``, which takes the
              process runner as a parameter, so the tests drive it with a recording runner and
              read the ranges against real git repositories.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the ``security`` job installs the pinned scanner and runs
              this), .gitleaks.toml (the rules and allowlists), docs/PREVENTION.md (P-773)
Tested by:    tests/test_ci_gitleaks.py
Touch when:   never for a new repository (it scans this repository's own history); ci.yml gains a
              trigger (give it a range here); the scanner's command line changes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO

#: Events that scan one pull request's own commits: what its head reaches and its base does not.
PULL_REQUEST_EVENTS = frozenset({"pull_request"})
#: Events that scan everything the checked-out commit reaches.
FULL_HISTORY_EVENTS = frozenset({"push", "schedule", "workflow_dispatch"})
#: gitleaks' exit code when it finds a leak (``--exit-code``), kept apart from a failed scan's 1.
EXIT_LEAKS = 2

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def log_opts(event: str, base_sha: str, head_sha: str) -> str:
    """The ``git log`` range gitleaks scans for ``event``."""
    if event in PULL_REQUEST_EVENTS:
        if not base_sha or not head_sha:
            raise ValueError(
                f"{event}: the pull request's base and head commits are both required "
                "(BASE_SHA and HEAD_SHA)"
            )
        return f"{base_sha}..{head_sha}"
    if event in FULL_HISTORY_EVENTS:
        return "HEAD"
    raise ValueError(f"no scan range is defined for the {event!r} event; add one to this script")


def command(gitleaks: str, range_: str) -> list[str]:
    """The scan: redacted, verbose findings, the repository's config, one ``git log`` range."""
    return [
        gitleaks,
        "git",
        "--redact",
        "--verbose",
        "--no-banner",
        "--config",
        ".gitleaks.toml",
        "--exit-code",
        str(EXIT_LEAKS),
        f"--log-opts={range_}",
        ".",
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] = os.environ,
    run: Runner = subprocess.run,
    out: TextIO = sys.stdout,
) -> int:
    del argv  # configured by the environment the workflow step sets
    event = env.get("EVENT_NAME", "")
    try:
        range_ = log_opts(event, env.get("BASE_SHA", ""), env.get("HEAD_SHA", ""))
    except ValueError as exc:
        print(f"::error::{exc}", file=out)
        return 1
    counted = run(
        ["git", "rev-list", "--count", range_], capture_output=True, text=True, check=False
    )
    if counted.returncode != 0:
        print(f"::error::cannot read the commits in {range_}: {counted.stderr.strip()}", file=out)
        return 1
    print(f"{event}: scanning {counted.stdout.strip()} commits ({range_})", file=out, flush=True)
    rc = run(command(env.get("GITLEAKS", "gitleaks"), range_), check=False).returncode
    if rc == EXIT_LEAKS:
        print(f"::error::gitleaks found secrets in {range_}; see the findings above", file=out)
    elif rc != 0:
        print(f"::error::gitleaks did not complete (exit {rc})", file=out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
