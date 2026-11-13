"""Served-shape event fixtures, built by the real emitter, never by hand.

A test of a read script gets its events here. The event is made by ``Emitter.on_event`` (the
path the core, the builders and the oracle use) and returned in the shape
``GET /runs/{id}/events/log`` serves, so a fixture cannot describe a layout the product does
not produce. A hand-built ``{"action": ..., "payload": {"task": ...}}`` is what failed in
Wave 4.

Navigation
----------
What it is:   The one maker of served-shape StepEvent dicts for tests.
What it does: ``served_event(action, stage, **payload)`` emits through the real emitter's
              ``on_event`` callback and returns ``StepEvent.to_dict()``;
              ``served_run(spec)`` makes a run's event list with ascending ``seq``.
How:          ``Emitter`` over a ``MemorySink``; tests/test_read_preflight.py pins that the
              dict has exactly the served envelope keys plus ``payload``.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/observability/events.py (the emitter), src/crb/server/routes/runs.py
              (``EVENT_KEYS``, the served shape), tests/test_read_preflight.py (its check)
Tested by:    tests/test_read_preflight.py
Touch when:   never for a new repository; the served event shape changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from crb.observability.events import Emitter, MemorySink


def served_event(action: str, stage: str = "build", seq: int = 1, **payload: Any) -> dict[str, Any]:
    """One event as the server serves it, made by ``Emitter.on_event(stage)``."""
    sink = MemorySink()
    Emitter(sink, trace_id="t" * 32).on_event(stage)(action, payload)
    [ev] = sink.events
    d = ev.to_dict()
    d["seq"] = seq
    return d


def served_run(spec: Iterable[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """``(stage, action, callback payload)`` triples in emission order."""
    return [
        served_event(action, stage, seq=i, **payload)
        for i, (stage, action, payload) in enumerate(spec, start=1)
    ]
