"""Test helpers for races: stage two writers at the same moment, deterministically.

Navigation
----------
What it is:   The test-only way to reproduce a check-then-act race without luck: a barrier
              after a named call, and a runner that starts every call at once.
What it does: ``pause_after`` wraps ``owner.name`` so each caller waits at a two-party barrier
              after the call returns — on code that does not serialise the write both callers
              meet there and the race is certain; on code that does, the second never arrives
              while the first holds the lock, the wait times out, the barrier breaks and every
              later wait passes at once. ``at_once`` runs callables on their own threads from
              one start signal and returns each result or the exception it raised.
How:          ``threading.Barrier`` (broken by a timeout, never re-armed) and
              ``threading.Event``; the test client re-raises a server error in the calling
              thread, so a 500 comes back as an exception in the result list.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/factory_state.py (``FactoryHome.registration`` — the lock the
              backlog races test), src/crb/store/events.py (``lock_event_writes`` — the lock
              the trace races test), tests/fixtures/server_seed.py (``make_env`` — the app
              whose requests these helpers race)
Tested by:    tests/test_server_routes_factory.py, tests/test_server_routes_learn.py,
              tests/test_server_routes_prevention.py
Touch when:   never for a new repository; a race needs a third party or a different pause.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

import pytest


def pause_after(
    monkeypatch: pytest.MonkeyPatch,
    owner: Any,
    name: str,
    gate: threading.Barrier | None = None,
    *,
    timeout: float = 2.0,
) -> None:
    """Wrap ``owner.name`` so each caller waits at ``gate`` (a fresh two-party barrier by
    default) after the call returns."""
    barrier = gate if gate is not None else threading.Barrier(2)
    real = getattr(owner, name)

    def paused(*args: Any, **kwargs: Any) -> Any:
        out = real(*args, **kwargs)
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=timeout)
        return out

    monkeypatch.setattr(owner, name, paused)


def at_once(*calls: Callable[[], Any]) -> list[Any]:
    """Run ``calls`` on their own threads at the same moment; each result, or the exception
    it raised."""
    out: list[Any] = [None] * len(calls)
    start = threading.Event()

    def run(i: int, call: Callable[[], Any]) -> None:
        start.wait()
        try:
            out[i] = call()
        except Exception as exc:  # a 500 surfaces here through the test client
            out[i] = exc

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    return out
