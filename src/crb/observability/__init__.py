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
