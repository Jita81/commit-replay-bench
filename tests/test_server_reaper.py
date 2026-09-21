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
              empty with a warning, never a crash, ``pending`` counts exactly what the
              health probe reports, and a pass under ``budget_s`` ends within the budget
              against a daemon that answers slowly (each call capped to the remainder, the
              entry it ran out on counting one attempt with the reason, the rest untouched).
How:          A ``docker`` shell script whose ``inspect`` answers are scripted per call count
              (optionally sleeping first); a reaper over a ``tmp_path`` state file.
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
import time
from pathlib import Path

import pytest

from crb.server import reaper as rp


def _docker(
    dir_: Path, *, gone_after: int | None, rm_fails: bool = False, delay_s: float = 0.0
) -> tuple[str, Path]:
    """A ``docker`` whose ``inspect`` says Running=true until ``gone_after`` inspect calls
    have been made (then "No such container"); ``None`` = never lets go. ``rm -f`` is
    logged, and fails when asked. ``delay_s`` makes every call sleep first (a slow daemon)."""
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
        "#!/bin/sh\n" + (f"sleep {delay_s:g}\n" if delay_s else "") + 'case "$1" in\n'
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


def test_reap_pass_ends_within_its_time_budget(tmp_path: Path) -> None:
    """Three entries against a daemon that takes 2 s per answer, under a 0.5 s budget: the
    pass ends inside the budget (the first inspect is capped to the remainder), the entry
    it ran out on carries ``pass budget exhausted`` as one attempt, the entries it never
    reached are untouched — and an unbudgeted pass (``budget_s=None``) still asks every
    question. Nothing is ever reported ``reaped`` on a question the daemon did not answer."""
    docker, calls = _docker(tmp_path / "slow", gone_after=None, delay_s=2.0)
    r = rp.ContainerReaper(tmp_path / "state.json", docker=docker, max_attempts=20)
    for i in range(3):
        r.add(f"crb-build-slow-{i}", run_id=f"run-{i}", task_id=f"t{i}")
    t0 = time.monotonic()
    assert r.reap_once(budget_s=0.5) == []
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed  # not 3 entries × (2 s + 2 s + 2 s)
    first, second, third = r.pending()
    assert first.attempts == 1 and rp.BUDGET_EXHAUSTED in first.last_error
    assert (second.attempts, third.attempts) == (0, 0) and not second.last_error
    assert calls.read_text().split() == []  # the capped inspect was cut before it answered
    # a zero budget reaches no entry at all: the queue is exactly as it was
    assert r.reap_once(budget_s=0.0) == []
    assert [e.attempts for e in r.pending()] == [1, 0, 0]


def test_reap_pass_budget_caps_each_call_to_the_remainder(tmp_path: Path) -> None:
    """A daemon fast enough to answer inside the budget is not cut short: with 0.2 s per
    answer and a 1 s budget the first entry gets its full inspect / rm / inspect (three
    calls, 0.6 s), the second is cut where the remainder runs out, the third (which the
    remainder cannot reach: 0.6 s + at least one 0.2 s answer + a capped call) is
    untouched, and the next pass (a fresh budget) continues from the first."""
    docker, calls = _docker(tmp_path / "ok", gone_after=None, rm_fails=True, delay_s=0.2)
    r = rp.ContainerReaper(tmp_path / "state.json", docker=docker, max_attempts=20)
    r.add("crb-build-a", run_id="ra", task_id="ta")
    r.add("crb-build-b", run_id="rb", task_id="tb")
    r.add("crb-build-c", run_id="rc", task_id="tc")
    t0 = time.monotonic()
    assert r.reap_once(budget_s=1.0) == []
    assert time.monotonic() - t0 < 2.0
    log = calls.read_text().split()
    assert log[:3] == ["inspect", "rm", "inspect"]  # entry a in full
    a, _b, c = r.pending()
    assert a.attempts == 1 and "still running" in a.last_error
    assert c.attempts == 0 and not c.last_error  # never reached this pass
    assert r.reap_once(budget_s=1.0) == []  # the next pass carries on from a
    assert r.pending()[0].attempts == 2
