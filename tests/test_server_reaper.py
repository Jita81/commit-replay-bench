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
How:          A ``docker`` shell script whose ``inspect`` answers are scripted per call count,
              and for the time budget a fake daemon on a fake clock (``_FakeDaemon``: no
              spawn, no real time, P-014); a reaper over a ``tmp_path`` state file.
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
import subprocess
import time
from pathlib import Path

import pytest

from crb.server import reaper as rp


def _docker(dir_: Path, *, gone_after: int | None, rm_fails: bool = False) -> tuple[str, Path]:
    """A ``docker`` whose ``inspect`` says Running=true until ``gone_after`` inspect calls
    have been made (then "No such container"); ``None`` = never lets go. ``rm -f`` is
    logged, and fails when asked. A slow daemon is :class:`_FakeDaemon`, on a fake
    clock: a real script that sleeps would time the machine, not the budget (P-014)."""
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
        '#!/bin/sh\ncase "$1" in\n'
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


class _FakeDaemon:
    """A docker daemon on a fake clock: every question takes ``answer_s`` of fake time, or
    — when that is longer than the call's timeout — runs to the timeout and is not answered
    (``inspect`` reads unknown, ``rm -f`` raises ``TimeoutExpired``). Nothing is spawned and
    no real time passes, so the budget arithmetic is tested without timing the machine
    (docs/PREVENTION.md P-014)."""

    def __init__(self, *, answer_s: float, running: bool = True, rm_fails: bool = False) -> None:
        self.now = 1000.0
        self.answer_s = answer_s
        self.running = running
        self.rm_fails = rm_fails
        self.calls: list[tuple[str, float]] = []

    def clock(self) -> float:
        return self.now

    def _spend(self, what: str, timeout: float) -> bool:
        """Advance the clock by the answer or the timeout; ``True`` when it answered."""
        self.calls.append((what, timeout))
        if self.answer_s > timeout:
            self.now += timeout
            return False
        self.now += self.answer_s
        return True

    def stopped(self, docker: str, name: str, *, timeout_s: float) -> bool | None:
        if not self._spend("inspect", timeout_s):
            return None
        return not self.running

    def runner(self, argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        timeout = float(kw["timeout"])  # type: ignore[arg-type]
        if not self._spend(argv[1], timeout):
            raise subprocess.TimeoutExpired(argv, timeout)
        rc = 1 if self.rm_fails else 0
        return subprocess.CompletedProcess(argv, rc, "", "refused" if rc else "")

    def reaper(self, path: Path, **kw: object) -> rp.ContainerReaper:
        return rp.ContainerReaper(
            path,
            docker="docker",
            runner=self.runner,
            clock=self.clock,
            stopped=self.stopped,
            **kw,  # type: ignore[arg-type]
        )


def test_reap_pass_ends_within_its_time_budget(tmp_path: Path) -> None:
    """Three entries against a daemon that takes 2 s per answer, under a 0.5 s budget: the
    pass ends inside the budget (the first inspect is capped to the remainder), the entry
    it ran out on carries ``pass budget exhausted`` as one attempt, the entries it never
    reached are untouched. Nothing is ever reported ``reaped`` on a question the daemon did
    not answer. The daemon and the clock are fakes: no real time is measured."""
    daemon = _FakeDaemon(answer_s=2.0)
    r = daemon.reaper(tmp_path / "state.json", max_attempts=20)
    for i in range(3):
        r.add(f"crb-build-slow-{i}", run_id=f"run-{i}", task_id=f"t{i}")
    start = daemon.now
    assert r.reap_once(budget_s=0.5) == []
    assert daemon.now - start == pytest.approx(0.5)  # not 3 entries x (2 s + 2 s + 2 s)
    assert daemon.calls == [("inspect", pytest.approx(0.5))]  # capped to the remainder
    first, second, third = r.pending()
    assert first.attempts == 1 and rp.BUDGET_EXHAUSTED in first.last_error
    assert (second.attempts, third.attempts) == (0, 0) and not second.last_error
    # a zero budget reaches no entry at all: the queue is exactly as it was
    assert r.reap_once(budget_s=0.0) == []
    assert [e.attempts for e in r.pending()] == [1, 0, 0]
    assert len(daemon.calls) == 1


def test_an_unbudgeted_pass_asks_every_question_whatever_the_daemon_takes(
    tmp_path: Path,
) -> None:
    """``budget_s=None`` caps each call at its own timeout only: a slow daemon is asked
    inspect, rm -f and inspect again for every entry."""
    daemon = _FakeDaemon(answer_s=2.0, rm_fails=True)
    r = daemon.reaper(tmp_path / "state.json", max_attempts=20)
    r.add("crb-build-a", run_id="ra", task_id="ta")
    r.add("crb-build-b", run_id="rb", task_id="tb")
    assert r.reap_once() == []
    assert [w for w, _ in daemon.calls] == ["inspect", "rm", "inspect"] * 2
    assert [t for _, t in daemon.calls] == [
        rp.INSPECT_TIMEOUT_S,
        rp.RM_TIMEOUT_S,
        rp.INSPECT_TIMEOUT_S,
    ] * 2
    assert all("still running" in e.last_error for e in r.pending())


def test_reap_pass_budget_caps_each_call_to_the_remainder(tmp_path: Path) -> None:
    """A daemon fast enough to answer inside the budget is not cut short: with 0.2 s per
    answer and a 1 s budget the first entry gets its full inspect / rm / inspect (three
    calls, 0.6 s), the second is cut where the remainder runs out (its inspect, 0.2 s, then
    an rm capped to the 0.2 s left and no second inspect), the third is untouched, and the
    next pass (a fresh budget) continues from the first. The clock is a fake one the daemon
    advances, so the arithmetic holds on any machine (P-014)."""
    daemon = _FakeDaemon(answer_s=0.2, rm_fails=True)
    r = daemon.reaper(tmp_path / "state.json", max_attempts=20)
    r.add("crb-build-a", run_id="ra", task_id="ta")
    r.add("crb-build-b", run_id="rb", task_id="tb")
    r.add("crb-build-c", run_id="rc", task_id="tc")
    start = daemon.now
    assert r.reap_once(budget_s=1.0) == []
    assert daemon.now - start == pytest.approx(1.0)
    assert [w for w, _ in daemon.calls] == ["inspect", "rm", "inspect", "inspect", "rm"]
    assert daemon.calls[-1][1] == pytest.approx(0.2)  # the last call got only the remainder
    a, b, c = r.pending()
    assert a.attempts == 1 and "still running" in a.last_error
    assert b.attempts == 1 and rp.BUDGET_EXHAUSTED in b.last_error
    assert c.attempts == 0 and not c.last_error  # never reached this pass
    assert r.reap_once(budget_s=1.0) == []  # the next pass carries on from a
    assert r.pending()[0].attempts == 2


def test_the_reaper_reads_the_real_clock_and_the_strict_inspect_by_default(
    tmp_path: Path,
) -> None:
    """The injection points default to what production uses: the monotonic clock and
    ``container_stopped``'s strict question."""
    r = rp.ContainerReaper(tmp_path / "state.json")
    assert r._clock is time.monotonic
    assert r._stopped is rp.container_stopped
