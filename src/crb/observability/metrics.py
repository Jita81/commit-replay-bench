"""Prometheus metrics behind a no-op fallback.

``prometheus_client`` is an optional dependency (``[server]`` extra). When it is
absent every metric is a silent no-op so the CLI and core paths never need it.
Call-sites use the helper functions, never the raw objects, so the fallback and
the real registry share one API.

The one metric that matters most is ``crb_false_q1_total``: it is a gauge set
from the ledger and it must read 0. An alert on it is the operator's cheapest
guarantee that the honesty invariant still holds.

Navigation
----------
What it is:   The Prometheus metric definitions and the three recording helpers the worker
              and the server call, behind a no-op fallback when ``prometheus_client`` is
              not installed.
What it does: Counts runs, graded tasks by outcome, belt failures, builder tokens and cost;
              times grades and builds; exposes ``crb_false_q1_total`` (must stay 0) and the
              ledger row count as gauges; renders the exposition for ``/metrics``.
How:          Import-time try/except picks the real registry or ``_Noop``; every metric is
              a module-level object created through ``_counter``/``_gauge``/``_histogram``;
              call-sites use ``record_grade``/``record_build``/``set_ledger_health``.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/server/worker.py (calls the recorders after each grade and build),
              src/crb/server/routes/system.py (``/metrics`` renders ``render()``),
              src/crb/server/http_metrics.py (the HTTP-level metrics on the same registry),
              src/crb/core/ledger.py (the source of the false-Q1 count the gauge reflects),
              deploy/helm/crb/values.yaml (the optional Prometheus scrape of ``/metrics``)
Tested by:    tests/test_server_system.py
Touch when:   never for a new repository; a new metric is defined here with a helper, named
              ``crb_*``, and documented in docs/ARCHITECTURE.md; never change what
              ``crb_false_q1_total`` means (docs/EVIDENCE-AND-CLAIMS.md).
Claims:       ``crb_builder_cost_usd_total`` sums metered cost only — unpriced models
              contribute zero, so it is a floor, not a bill (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover — exercised only when the extra is installed
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


class _Noop:
    """Stands in for every metric when the client is absent; accepts any call, does nothing."""

    def labels(self, *_: Any, **__: Any) -> _Noop:
        return self

    def inc(self, *_: Any, **__: Any) -> None:
        pass

    def set(self, *_: Any, **__: Any) -> None:
        pass

    def observe(self, *_: Any, **__: Any) -> None:
        pass


registry: Any = None

if _AVAILABLE:  # pragma: no cover
    registry = CollectorRegistry()

    def _counter(name: str, doc: str, labels: list[str]) -> Any:
        return Counter(name, doc, labels, registry=registry)

    def _gauge(name: str, doc: str, labels: list[str]) -> Any:
        return Gauge(name, doc, labels, registry=registry)

    def _histogram(name: str, doc: str, labels: list[str]) -> Any:
        return Histogram(
            name,
            doc,
            labels,
            registry=registry,
            buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800),
        )
else:

    def _counter(name: str, doc: str, labels: list[str]) -> Any:
        return _Noop()

    def _gauge(name: str, doc: str, labels: list[str]) -> Any:
        return _Noop()

    def _histogram(name: str, doc: str, labels: list[str]) -> Any:
        return _Noop()


runs_total = _counter(
    "crb_runs_total", "Runs started, by kind and terminal status.", ["kind", "status"]
)
tasks_total = _counter(
    "crb_tasks_total",
    "Graded tasks, by repo and outcome (clean|not_clean|disqualified|error).",
    ["repo", "outcome"],
)
belt_failures_total = _counter("crb_belt_failures_total", "Belt failures, by belt name.", ["belt"])
builder_tokens_total = _counter(
    "crb_builder_tokens_total",
    "Builder tokens, by builder/model and direction.",
    ["builder", "model", "kind"],
)
builder_cost_usd_total = _counter(
    "crb_builder_cost_usd_total", "Estimated builder cost in USD.", ["builder", "model"]
)
grade_latency_seconds = _histogram(
    "crb_grade_latency_seconds", "Wall-clock seconds to grade one trial.", ["runner"]
)
build_latency_seconds = _histogram(
    "crb_build_latency_seconds", "Wall-clock seconds for one builder attempt.", ["builder"]
)
sandbox_unavailable_total = _counter(
    "crb_sandbox_unavailable_total", "Times a run stopped because the sandbox failed closed.", []
)
false_q1_total = _gauge(
    "crb_false_q1_total", "Clean ledger rows with a failed belt. MUST be 0.", []
)
ledger_rows = _gauge("crb_ledger_rows", "Rows in the grade ledger.", [])


def record_grade(
    *,
    repo: str,
    runner: str,
    clean: bool,
    disqualified: bool,
    error: str,
    belts: dict[str, Any],
    duration_s: float,
) -> None:
    """One graded trial: outcome counter, a failure counter per belt that is ``False``
    (``None`` — not evaluated — is not a failure), and the grade latency."""
    outcome = (
        "error" if error else "disqualified" if disqualified else "clean" if clean else "not_clean"
    )
    tasks_total.labels(repo, outcome).inc()
    for belt, value in belts.items():
        if value is False:
            belt_failures_total.labels(belt).inc()
    grade_latency_seconds.labels(runner).observe(duration_s)


def record_build(
    *, builder: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float, latency_s: float
) -> None:
    """One builder attempt: tokens by direction, metered cost, and its latency."""
    builder_tokens_total.labels(builder, model, "in").inc(tokens_in)
    builder_tokens_total.labels(builder, model, "out").inc(tokens_out)
    builder_cost_usd_total.labels(builder, model).inc(cost_usd)
    build_latency_seconds.labels(builder).observe(latency_s)


def set_ledger_health(*, rows: int, false_q1: int) -> None:
    """Refresh the two ledger gauges from a verification pass (``false_q1`` must be 0)."""
    ledger_rows.set(rows)
    false_q1_total.set(false_q1)


def render() -> bytes:
    """Prometheus text exposition (empty when the client is not installed)."""
    if not _AVAILABLE or registry is None:  # pragma: no cover
        return b""
    return bytes(generate_latest(registry))  # pragma: no cover


def available() -> bool:
    """``True`` iff ``prometheus_client`` is installed (``/metrics`` is real, not empty)."""
    return _AVAILABLE
