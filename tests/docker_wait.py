"""The one way a test reads whether docker still lists something: a bounded, fail-closed wait.

``docker run --rm`` removes a container in the daemon AFTER the kill or the exit returns,
and a session's teardown removes its sidecar and network the same way, so a test that
asserts ``docker ps -a`` is empty the instant a kill, an ``rm`` or a cancel returns races
the daemon and fails CI for no fault in the code (docs/PREVENTION.md P-119: PRs #49 and
#53). #59 gave the two kill tests of tests/test_sandbox_docker.py a bounded wait and #60
fixed that wait's last query; this module is that wait, once, for every such site, and
``tests/test_docker_wait.py`` refuses a docker state read anywhere else in the tests.

Navigation
----------
What it is:   The shared test helper that waits, within a bound, for ``docker ps`` or
              ``docker network ls`` to list nothing under a name filter.
What it does: Polls the listing, each query bounded by the time left; answers ``True`` once
              a SUCCESSFUL query lists nothing and ``False`` when the name is still listed
              at the deadline (a leak the caller refuses). A failed query fails the test,
              and so does a daemon that never answered; a query that times out after the
              daemon has already listed the name reads as still listed (#60's semantics).
How:          ``subprocess.run([docker, *listing, "--filter", f"name={name}"],
              timeout=<time left>)`` in a loop with a 0.2 s step → ``True`` / ``False`` /
              ``pytest.fail``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   tests/test_sandbox_docker.py (the kill and leak probes that wait through it),
              tests/test_builders_container_docker.py (the session teardown's container and
              network checks), tests/test_provision_fetch.py (the fetch container after a
              kill), tests/test_docker_wait.py (its tests and the ratchet), docs/PREVENTION.md
              (P-119, the class it closes)
Tested by:    tests/test_docker_wait.py
Touch when:   a test needs to know whether docker still lists a container or a network:
              call :func:`gone` or :func:`network_gone`, never ``docker ps`` directly.
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest

#: How long a removed container or network may take to leave docker's listing. A name
#: still listed after this is a leak.
GONE_WITHIN_S = 15.0
#: The pause between two queries.
STEP_S = 0.2


def _docker() -> str:
    return shutil.which("docker") or "docker"


def lists_nothing(listing: list[str], name: str, *, within_s: float = GONE_WITHIN_S) -> bool:
    """``True`` once a SUCCESSFUL ``docker <listing> --filter name=<name>`` prints nothing;
    ``False`` if ``name`` is still listed at ``within_s`` seconds. Every query is bounded by
    the time left. A failed query fails the test, and so does a daemon that never answered:
    empty output from it is not proof of removal. A query that times out after the daemon
    has already listed the name reads as still listed — it ran to the deadline, which is
    where a name that stays behind always ends."""
    deadline = time.monotonic() + within_s
    seen_listed = False
    argv = [_docker(), *listing, "--filter", f"name={name}"]
    what = " ".join(listing)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            q = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=remaining)
        except subprocess.TimeoutExpired:
            if seen_listed:
                return False
            pytest.fail(f"docker {what} did not answer within {within_s:g}s while checking {name}")
        if q.returncode != 0:
            pytest.fail(
                f"docker {what} failed (rc={q.returncode}) checking {name}: {q.stderr.strip()}"
            )
        if q.stdout.strip() == "":
            return True
        seen_listed = True
        time.sleep(min(STEP_S, max(0.0, deadline - time.monotonic())))


def gone(name: str, *, within_s: float = GONE_WITHIN_S, running_only: bool = False) -> bool:
    """No container whose name matches ``name`` is listed (``docker ps -aq``; with
    ``running_only``, none is RUNNING — ``docker ps -q``)."""
    listing = ["ps", "-q"] if running_only else ["ps", "-aq"]
    return lists_nothing(listing, name, within_s=within_s)


def network_gone(name: str, *, within_s: float = GONE_WITHIN_S) -> bool:
    """No network whose name matches ``name`` is listed (``docker network ls -q``)."""
    return lists_nothing(["network", "ls", "-q"], name, within_s=within_s)
