"""crb.observability — what an operator can SEE while the instrument runs.

* :mod:`crb.observability.events`  — the ``StepEvent`` envelope (one shape for
  every stage: mine → prep → build → grade → ledger → oracle → factory), sinks
  (memory, JSONL, fan-out) and an ``Emitter`` that adapts the core's plain
  ``on_event(action, payload)`` callbacks into structured, redacted events.
* :mod:`crb.observability.metrics` — Prometheus counters/histograms behind a
  no-op fallback so the core never needs ``prometheus_client``.
* :mod:`crb.observability.logging` — JSON logging with redaction.
* :mod:`crb.observability.probes`  — health probes (sandbox, toolchains, builders).

Nothing here decides a verdict. It only reports what happened, with its method.

Navigation
----------
What it is:   The public surface of the observability package — the event envelope, its
              sinks and the ``Emitter``.
What it does: Re-exports the event types the server, worker, store and factory import; the
              metrics, logging and probe modules are imported by their own names.
How:          Plain re-exports; ``__all__`` is the contract.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/observability/events.py (everything exported here),
              src/crb/store/events.py (the DB sink built on these types),
              src/crb/server/worker.py (the main producer of events)
Tested by:    tests/test_store_events.py, tests/test_worker.py
Touch when:   never for a new repository; a new sink or event field lands in
              src/crb/observability/events.py and is exported here in the same change.
"""

from crb.observability.events import (
    Emitter,
    EventSink,
    JsonlSink,
    MemorySink,
    MultiSink,
    StepEvent,
    StepStatus,
    new_trace_id,
)

__all__ = [
    "Emitter",
    "EventSink",
    "JsonlSink",
    "MemorySink",
    "MultiSink",
    "StepEvent",
    "StepStatus",
    "new_trace_id",
]
