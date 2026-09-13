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
from dataclasses import dataclass, field
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
    OK = "ok"
    ERROR = "error"
    INVALID = "invalid"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"


def new_trace_id() -> str:
    return uuid.uuid4().hex


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="milliseconds")


def _redact_value(v: Any) -> Any:
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, Mapping):
        return {str(k): _redact_value(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_redact_value(x) for x in v]
    return v


@dataclass(frozen=True)
class StepEvent:
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
        kw = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        if "status" in kw:
            kw["status"] = StepStatus(kw["status"])
        return cls(**kw)


class EventSink(Protocol):
    def emit(self, event: StepEvent) -> None: ...


class MemorySink:
    """Keeps events in memory (tests, CLI progress, SSE fan-out buffers)."""

    def __init__(self, max_events: int = 100_000) -> None:
        self._events: list[StepEvent] = []
        self._max = max_events
        self._lock = threading.Lock()

    def emit(self, event: StepEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]

    @property
    def events(self) -> list[StepEvent]:
        with self._lock:
            return list(self._events)

    def by_trace(self, trace_id: str) -> list[StepEvent]:
        return [e for e in self.events if e.trace_id == trace_id]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class JsonlSink:
    """Append-only JSONL file, one event per line, fsync'd."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def emit(self, event: StepEvent) -> None:
        line = json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    def read(self) -> Iterator[StepEvent]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield StepEvent.from_dict(json.loads(line))


class MultiSink:
    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = list(sinks)

    def add(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    def emit(self, event: StepEvent) -> None:
        for s in self._sinks:
            with contextlib.suppress(Exception):  # a broken sink must never break a run
                s.emit(event)


class CallbackSink:
    """Adapts any ``fn(event)`` — e.g. an SSE broadcaster — into a sink."""

    def __init__(self, fn: Callable[[StepEvent], None]) -> None:
        self._fn = fn

    def emit(self, event: StepEvent) -> None:
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

    def _next_seq(self) -> int:
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
            seq=self._next_seq(),
        )
        self.sink.emit(ev)
        return ev

    def error(self, stage: str, action: str, exc: BaseException, **payload: Any) -> StepEvent:
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
