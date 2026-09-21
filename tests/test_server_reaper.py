"""crb.server.reaper — an unconfirmed container kill is reaped, bounded, and never silent.

Navigation
----------
What it is:   The reaper's unit tests, against a scripted ``docker`` (no daemon).
What it does: Pins the contract: a container whose kill went unconfirmed is queued durably
              (the JSON file survives a new reaper over the same home), each pass asks
              ``docker inspect`` then ``docker rm -f`` and reports ``reaped`` once the daemon
              says the container is gone or not running, a daemon that never lets go is
              retried to ``max_attempts`` and then reported ``failed`` (dropped from the queue
              — the operator was told ``docker rm -f``), a corrupt state file is treated as
              empty with a warning, never a crash, and ``pending`` counts exactly what the
              health probe reports.
How:          A ``docker`` shell script whose ``inspect`` answers are scripted per call count;
              a reaper over a ``tmp_path`` state file.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/server/reaper.py (under test), src/crb/server/worker.py (the loop that
              drives it — tests/test_worker.py covers the events it emits)
Tested by:    tests/test_server_reaper.py
Touch when:   the reap sequence or the bound changes — update docs/API.md's cancel row and
              ADR-0012 with it.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from crb.server import reaper as rp


def _docker(dir_: Path, *, gone_after: int | None, rm_fails: bool = False) -> tuple[str, Path]:
    """A ``docker`` whose ``inspect`` says Running=true until ``gone_after`` inspect calls
    have been made (then "No such container"); ``None`` = never lets go. ``rm -f`` is
    logged, and fails when asked."""
    dir_.mkdir(parents=True, exist_ok=True)
    calls = dir_ / "calls"
    calls.write_text("")
    if gone_after is None:
        inspect = "echo true"
    else:
        inspect = (
            f'if [ "$(grep -c inspect "{calls}")" -le {gone_after} ]; then echo true; '
            'else echo "Error: No such container: $4" >&2; exit 1; fi'
        )
    rm = "exit 1" if rm_fails else ":"
    script = dir_ / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  inspect) echo inspect >> "{calls}"; {inspect} ;;\n'
        f'  rm) echo rm >> "{calls}"; {rm} ;;\n'
        "esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), calls


def test_add_persists_and_pending_counts(tmp_path: Path) -> None:
    path = tmp_path / "home" / "unconfirmed-containers.json"
    r = rp.ContainerReaper(path, docker="docker")
    assert r.pending() == [] and r.pending_count() == 0
    r.add("crb-build-a", run_id="run-1", task_id="t1")
    r.add("crb-build-b", run_id="run-1", task_id="t2")
    r.add("crb-build-a", run_id="run-1", task_id="t1")  # idempotent per container
    assert [e.container for e in r.pending()] == ["crb-build-a", "crb-build-b"]
    assert r.pending_count() == 2
    # durable: a new reaper over the same file (a restarted worker) sees the queue
    again = rp.ContainerReaper(path, docker="docker")
    assert [e.container for e in again.pending()] == ["crb-build-a", "crb-build-b"]
    saved = json.loads(path.read_text())
    assert saved["containers"][0] == {
        "container": "crb-build-a",
        "run_id": "run-1",
        "task_id": "t1",
        "attempts": 0,
        "added": saved["containers"][0]["added"],
        "last_error": "",
    }
    assert saved["containers"][0]["added"].endswith("+00:00")  # utc_now_iso


def test_reap_once_inspects_then_removes_and_reports_reaped(tmp_path: Path) -> None:
    """First pass: inspect says running → ``rm -f`` → inspect says gone → reaped; the
    entry leaves the queue."""
    docker, calls = _docker(tmp_path / "d", gone_after=1)
    r = rp.ContainerReaper(tmp_path / "state.json", docker=docker)
    r.add("crb-build-x", run_id="run-9", task_id="t9")
    results = r.reap_once()
    assert len(results) == 1
    (res,) = results
    assert res.reaped is True and res.entry.container == "crb-build-x"
    assert res.entry.run_id == "run-9" and res.entry.task_id == "t9"
    assert res.attempts == 1
    assert calls.read_text().split() == ["inspect", "rm", "inspect"]
    assert r.pending() == [] and r.reap_once() == []


def test_reap_once_on_an_already_gone_container_still_removes_and_reaps(tmp_path: Path) -> None:
    docker, calls = _docker(tmp_path / "d", gone_after=0)
    r = rp.ContainerReaper(tmp_path / "state.json", docker=docker)
    r.add("crb-build-y", run_id="run-1", task_id="t")
    (res,) = r.reap_once()
    assert res.reaped is True
    assert calls.read_text().split() == ["inspect", "rm"]  # rm -f is idempotent: no re-ask


def test_reap_gives_up_at_the_bound_with_a_failed_result(tmp_path: Path) -> None:
    """A daemon that never lets go: every pass increments ``attempts`` and keeps the entry
    (still pending — the probe stays degraded) until ``max_attempts``, when the reaper
    reports ``failed`` ONCE and drops the entry: the run's trace carries the failure and
    the operator was told the by-hand command."""
    docker, calls = _docker(tmp_path / "d", gone_after=None, rm_fails=True)
    r = rp.ContainerReaper(tmp_path / "state.json", docker=docker, max_attempts=3)
    r.add("crb-build-z", run_id="run-2", task_id="t2")
    assert r.reap_once() == [] and r.pending_count() == 1
    assert r.pending()[0].attempts == 1 and "rm -f" in r.pending()[0].last_error
    assert r.reap_once() == [] and r.pending()[0].attempts == 2
    (res,) = r.reap_once()
    assert res.reaped is False and res.attempts == 3
    assert "docker rm -f crb-build-z" in res.detail
    assert r.pending() == [] and r.reap_once() == []
    assert calls.read_text().split().count("rm") == 3


def test_corrupt_state_file_reads_as_empty_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json")
    r = rp.ContainerReaper(path, docker="docker")
    with caplog.at_level("WARNING", logger="crb.server.reaper"):
        assert r.pending() == []
    assert any("unreadable" in rec.message for rec in caplog.records)
    r.add("crb-build-q", run_id="r", task_id="t")  # a write repairs it
    assert r.pending_count() == 1


def test_docker_missing_counts_as_an_attempt_not_a_crash(tmp_path: Path) -> None:
    r = rp.ContainerReaper(
        tmp_path / "state.json", docker=str(tmp_path / "no" / "docker"), max_attempts=1
    )
    r.add("crb-build-m", run_id="r", task_id="t")
    (res,) = r.reap_once()
    assert res.reaped is False and res.attempts == 1
