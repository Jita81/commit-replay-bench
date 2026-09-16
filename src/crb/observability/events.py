"""The ``StepEvent`` envelope and its sinks.

One event shape for every stage, so a viewer can answer "what ran, on what,
with what result, how long, how much" without joins:

    trace_id   — the run
    step_id    — the task (or sub-step) within the run
    stage      — mine | prep | build | grade | ledger | oracle | factory | system
    action     — a dotted verb the stage emits (``grade.belt``, ``build.turn`` …)
    status     — ok | error | invalid | skipped | in_progress

Events are append-only and redacted at construction. The :class:`Emitter`
binds a trace and produces the plain ``on_event(action, payload)`` callbacks
the core accepts, so ``crb.core`` stays dependency-free while every belt,
every builder turn and every ledger append lands in the stream.

Navigation
----------
What it is:   The ``StepEvent`` envelope, the sink protocol with its four implementations
              (memory, JSONL, fan-out, callback) and the trace-bound ``Emitter``.
What it does: Gives every stage one redacted, append-only event shape; ``Emitter.on_event``
              adapts the core's ``on_event(action, payload)`` callbacks (which know nothing
              of traces or sinks) into sequenced events, inferring the status from the
              action's suffix; ``MultiSink`` guarantees a broken sink never breaks a run.
How:          ``StepEvent.__post_init__`` validates the stage and redacts every string in the
              payload → ``Emitter.emit`` stamps trace, actor, repo and a monotonic ``seq`` →
              ``sink.emit``; ``timed`` brackets a block with ``.start``/``.done``/``.error``.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/redact.py (applied at construction, so no sink can leak a
              secret), src/crb/store/events.py (the DB sink and the SSE source),
              src/crb/server/worker.py (binds an ``Emitter`` per run and hands its
              ``on_event`` to the core), src/crb/core/grade.py and src/crb/core/mine.py (the
              action names they emit), src/crb/server/schemas.py (the API shape of an event)
Tested by:    tests/test_store_events.py, tests/test_worker.py
Touch when:   never for a new repository; a new stage is an entry in ``STAGES`` plus its
              mention in docs/ARCHITECTURE.md; a new field goes in ``to_dict``/``from_dict``,
              the store model and the API schema together (a DB migration).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from crb.core.redact import redact

STAGES: tuple[str, ...] = (
    "mine",
    "prep",
    "build",
    "grade",
    "ledger",
    "oracle",
    "factory",
    "system",
)


class StepStatus(StrEnum):
    """The outcome of one step. ``skipped`` covers a deliberate non-run (a DQ, a control
    skip) — it is not an error and not a pass."""

    OK = "ok"
    ERROR = "error"
    INVALID = "invalid"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"


def new_trace_id() -> str:
    """A fresh run id (32 hex chars)."""
    return uuid.uuid4().hex


def _utc_now() -> str:
    """ISO-8601 UTC to the millisecond (the timestamp every event carries)."""
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


def _redact_value(v: Any) -> Any:
    """Redact every string anywhere inside a payload (mappings and sequences recursed)."""
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, Mapping):
        return {str(k): _redact_value(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_redact_value(x) for x in v]
    return v


@dataclass(frozen=True)
class StepEvent:
    """One thing that happened. Redacted at construction; ``seq`` orders events within a
    trace; ``event_id`` makes each one addressable across sinks."""

    trace_id: str
    stage: str
    action: str
    status: StepStatus = StepStatus.OK
    step_id: str = ""
    parent_step_id: str = ""
    actor: str = ""
    repo: str = ""
    task_id: str = ""
    input_ref: str = ""
    output_ref: str = ""
    error_code: str = ""
    error_message: str = ""
    duration_ms: int | None = None
    cost_usd: float | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now)
    seq: int = 0
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"stage {self.stage!r} not in {STAGES}")
        object.__setattr__(self, "payload", _redact_value(dict(self.payload)))
        object.__setattr__(self, "error_message", redact(self.error_message))

    def to_dict(self) -> dict[str, Any]:
        """The wire shape (JSONL line, DB row, SSE frame) — flat, sorted by the sinks."""
        return {
            "event_id": self.event_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "parent_step_id": self.parent_step_id,
            "stage": self.stage,
            "action": self.action,
            "status": self.status.value,
            "actor": self.actor,
            "repo": self.repo,
            "task_id": self.task_id,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> StepEvent:
        """Inverse of :meth:`to_dict`; unknown keys are ignored so old lines still load."""
        kw = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        if "status" in kw:
            kw["status"] = StepStatus(kw["status"])
        return cls(**kw)


class EventSink(Protocol):
    """Anything that accepts events. Implementations must not raise into the producer."""

    def emit(self, event: StepEvent) -> None: ...


class MemorySink:
    """Keeps events in memory (tests, CLI progress, SSE fan-out buffers)."""

    def __init__(self, max_events: int = 100_000) -> None:
        self._events: list[StepEvent] = []
        self._max = max_events
        self._lock = threading.Lock()

    def emit(self, event: StepEvent) -> None:
        """Append; the oldest events are dropped beyond ``max_events`` (a ring, not a leak)."""
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]

    @property
    def events(self) -> list[StepEvent]:
        """A snapshot copy (safe to iterate while producers keep emitting)."""
        with self._lock:
            return list(self._events)

    def by_trace(self, trace_id: str) -> list[StepEvent]:
        """The events of one run, in emission order."""
        return [e for e in self.events if e.trace_id == trace_id]

    def clear(self) -> None:
        """Drop everything (tests)."""
        with self._lock:
            self._events.clear()


class JsonlSink:
    """Append-only JSONL file, one event per line, fsync'd."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def emit(self, event: StepEvent) -> None:
        """Append one line and fsync — a crash mid-run loses at most the event in flight."""
        line = json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    def read(self) -> Iterator[StepEvent]:
        """Every event in the file, in order (an absent file yields nothing)."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield StepEvent.from_dict(json.loads(line))


class MultiSink:
    """Fan-out to several sinks; one sink's failure is suppressed so the others still see
    the event and the run never notices."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = list(sinks)

    def add(self, sink: EventSink) -> None:
        """Attach another sink (e.g. an SSE broadcaster once a client connects)."""
        self._sinks.append(sink)

    def emit(self, event: StepEvent) -> None:
        """Deliver to every sink in order."""
        for s in self._sinks:
            with contextlib.suppress(Exception):  # a broken sink must never break a run
                s.emit(event)


class CallbackSink:
    """Adapts any ``fn(event)`` — e.g. an SSE broadcaster — into a sink."""

    def __init__(self, fn: Callable[[StepEvent], None]) -> None:
        self._fn = fn

    def emit(self, event: StepEvent) -> None:
        """Call the function; wrap in a ``MultiSink`` if it may raise."""
        self._fn(event)


OnEvent = Callable[[str, Mapping[str, Any]], None]


class Emitter:
    """A trace-bound event producer. Thread-safe monotonic ``seq``."""

    def __init__(
        self, sink: EventSink, *, trace_id: str = "", actor: str = "", repo: str = ""
    ) -> None:
        self.sink = sink
        self.trace_id = trace_id or new_trace_id()
        self.actor = actor
        self.repo = repo
        self._seq = 0
        self._lock = threading.Lock()
        # serialises seq allocation + sink delivery (RLock: a sink may emit through the
        # same emitter from within the same call)
        self._emit_lock = threading.RLock()

    def _next_seq(self) -> int:
        """The next sequence number — the only per-trace ordering a reader may rely on
        (timestamps can collide within a millisecond)."""
        with self._lock:
            self._seq += 1
            return self._seq

    def emit(
        self,
        stage: str,
        action: str,
        *,
        status: StepStatus = StepStatus.OK,
        step_id: str = "",
        task_id: str = "",
        parent_step_id: str = "",
        duration_ms: int | None = None,
        cost_usd: float | None = None,
        error: str = "",
        error_code: str = "",
        input_ref: str = "",
        output_ref: str = "",
        **payload: Any,
    ) -> StepEvent:
        """Build one event under this trace and hand it to the sink; ``step_id`` defaults
        to ``task_id`` so per-task events group without the caller thinking about it."""
        ev = StepEvent(
            trace_id=self.trace_id,
            stage=stage,
            action=action,
            status=status,
            step_id=step_id or task_id,
            parent_step_id=parent_step_id,
            actor=self.actor,
            repo=self.repo,
            task_id=task_id,
            input_ref=input_ref,
            output_ref=output_ref,
            error_code=error_code,
            error_message=error,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            payload=payload,
            seq=0,
        )
        # allocate the sequence number AND deliver under one lock: with the lock released
        # between the two, thread A could take seq 1, thread B take and deliver seq 2, then
        # A deliver seq 1 — a JSONL sink or an SSE stream would see them out of order and a
        # resume-by-seq reader would skip one (CodeRabbit on PR #3, 2026-09-15)
        with self._emit_lock:
            ev = replace(ev, seq=self._next_seq())
            self.sink.emit(ev)
        return ev

    def error(self, stage: str, action: str, exc: BaseException, **payload: Any) -> StepEvent:
        """An ``error`` event from an exception (type as the code, message redacted)."""
        return self.emit(
            stage,
            action,
            status=StepStatus.ERROR,
            error=f"{type(exc).__name__}: {exc}",
            error_code=type(exc).__name__,
            **payload,
        )

    def on_event(self, stage: str, *, task_id: str = "") -> OnEvent:
        """A callback with the core's ``on_event(action, payload)`` signature."""

        def _cb(action: str, payload: Mapping[str, Any]) -> None:
            p = dict(payload)
            # The core names the task as ``task`` (grade, controls) or ``sha`` (mine); either
            # becomes the event's task_id, else the one bound when the callback was made.
            tid = str(p.pop("task", "") or p.pop("sha", "") or task_id)
            status = StepStatus.OK
            if action.endswith(".error"):
                status = StepStatus.ERROR
            elif (
                action.endswith(".skip")
                or action.endswith(".tamper")
                or action.endswith(".malformed_oracle")
            ):
                status = StepStatus.SKIPPED
            self.emit(stage, action, status=status, task_id=tid, error=str(p.pop("error", "")), **p)

        return _cb

    @contextlib.contextmanager
    def timed(
        self, stage: str, action: str, *, task_id: str = "", **payload: Any
    ) -> Iterator[None]:
        """Emit ``<action>.start`` then ``<action>.done`` (or ``.error``) with duration."""
        self.emit(
            stage, action + ".start", status=StepStatus.IN_PROGRESS, task_id=task_id, **payload
        )
        t0 = time.monotonic()
        try:
            yield
        except BaseException as exc:
            self.emit(
                stage,
                action + ".error",
                status=StepStatus.ERROR,
                task_id=task_id,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error=f"{type(exc).__name__}: {exc}",
                error_code=type(exc).__name__,
                **payload,
            )
            raise
        self.emit(
            stage,
            action + ".done",
            task_id=task_id,
            duration_ms=int((time.monotonic() - t0) * 1000),
            **payload,
        )
