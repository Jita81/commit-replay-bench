"""Prometheus metrics behind a no-op fallback.

``prometheus_client`` is an optional dependency (``[server]`` extra). When it is
absent every metric is a silent no-op so the CLI and core paths never need it.
Call-sites use the helper functions, never the raw objects, so the fallback and
the real registry share one API.

The one metric that matters most is ``crb_false_q1_total``: it is a gauge set
from the ledger and it must read 0. An alert on it is the operator's cheapest
guarantee that the honesty invariant still holds.

Two processes, two expositions
------------------------------
The registry is module-level, so a series lives in the PROCESS that records it. The
API records the HTTP series and the ledger gauges and serves them at ``/metrics``.
The worker records everything else — runs, tasks, belts, tokens, cost, latencies,
deliveries, token mints, queue depth — and serves its own exposition on
``CRB_METRICS_PORT`` (:func:`start_worker_exposition`, J-TEL-1). Before that port
existed the dashboards showed the API's registry only and every worker-side counter
read as absent. docs/DEPLOYMENT.md#9-observability names which process carries
which series.

Navigation
----------
What it is:   The Prometheus metric definitions and the recording helpers the worker and the
              server call, behind a no-op fallback when ``prometheus_client`` is not
              installed; the worker's own exposition server.
What it does: Counts runs, graded tasks by outcome, belt failures, builder tokens and cost
              (by repo), deliveries by outcome, GitHub installation-token mints (never the
              token); times grades and builds; gauges queue depth, ``crb_false_q1_total``
              (must stay 0) and the ledger row count; renders the exposition for the API's
              ``/metrics`` and starts the worker's on its port.
How:          Import-time try/except picks the real registry or ``_Noop``; every metric is
              a module-level object created through ``_counter``/``_gauge``/``_histogram``;
              call-sites use ``record_grade``/``record_build``/``record_event``/
              ``set_ledger_health``; ``fresh_registry`` rebinds every metric to a new
              registry for tests.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/server/worker.py (calls the recorders after each grade and build,
              meters events through ``record_event``, sets the queue gauge on check-in),
              src/crb/server/worker_main.py (``start_worker_exposition`` before the loop),
              src/crb/server/routes/system.py (``/metrics`` renders ``render()``),
              src/crb/server/http_metrics.py (the HTTP-level metrics on the same registry),
              src/crb/core/ledger.py (the source of the false-Q1 count the gauge reflects),
              deploy/helm/crb/values.yaml and deploy/docker-compose.yml (the two scrape
              targets), docs/DEPLOYMENT.md#9-observability (the metrics table)
Tested by:    tests/test_observability_metrics.py, tests/test_server_system.py
Touch when:   never for a new repository; a new metric is defined here with a helper, named
              ``crb_*``, and added to the table in docs/DEPLOYMENT.md#9-observability; never
              change what ``crb_false_q1_total`` means (docs/EVIDENCE-AND-CLAIMS.md).
Claims:       ``crb_builder_cost_usd_total`` sums metered cost only — unpriced models
              contribute zero, so it is a floor, not a bill (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

try:  # pragma: no cover — exercised only when the extra is installed
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        start_http_server,
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

_LOG = logging.getLogger(__name__)

#: ``factory``-stage event action → ``crb_deliveries_total`` outcome (J-TEL-13). The
#: vocabulary is the run's own event log (docs/API.md#event-vocabulary): ``delivery.opened``
#: = a branch was pushed and a pull request opened; ``delivery.withheld`` = the route gate
#: refused; ``delivery.error`` = the push or the PR call failed.
DELIVERY_OUTCOMES: Mapping[str, str] = {
    "delivery.opened": "opened",
    "delivery.withheld": "withheld",
    "delivery.error": "failed",
}


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

_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800)

if _AVAILABLE:  # pragma: no cover
    registry = CollectorRegistry()

    def _counter(name: str, doc: str, labels: list[str]) -> Any:
        return Counter(name, doc, labels, registry=registry)

    def _gauge(name: str, doc: str, labels: list[str]) -> Any:
        return Gauge(name, doc, labels, registry=registry)

    def _histogram(name: str, doc: str, labels: list[str]) -> Any:
        return Histogram(name, doc, labels, registry=registry, buckets=_BUCKETS)
else:

    def _counter(name: str, doc: str, labels: list[str]) -> Any:
        return _Noop()

    def _gauge(name: str, doc: str, labels: list[str]) -> Any:
        return _Noop()

    def _histogram(name: str, doc: str, labels: list[str]) -> Any:
        return _Noop()


#: ``(module attribute, kind, name, doc, labels)`` — the one table every metric is built
#: from, so :func:`fresh_registry` can rebuild them all against a new registry and the
#: documentation ratchet can compare names and labels against docs/DEPLOYMENT.md.
_SPECS: tuple[tuple[str, str, str, str, list[str]], ...] = (
    (
        "runs_total",
        "counter",
        "crb_runs_total",
        "Runs finished, by kind and terminal status.",
        ["kind", "status"],
    ),
    (
        "tasks_total",
        "counter",
        "crb_tasks_total",
        "Graded tasks, by repo and outcome (clean|not_clean|disqualified|error).",
        ["repo", "outcome"],
    ),
    (
        "belt_failures_total",
        "counter",
        "crb_belt_failures_total",
        "Belt failures, by belt name.",
        ["belt"],
    ),
    (
        "builder_tokens_total",
        "counter",
        "crb_builder_tokens_total",
        "Builder tokens, by repo, builder/model and direction (in|out).",
        ["repo", "builder", "model", "kind"],
    ),
    (
        "builder_cost_usd_total",
        "counter",
        "crb_builder_cost_usd_total",
        "Metered builder cost in USD, by repo and builder/model (a floor: unpriced models add 0).",
        ["repo", "builder", "model"],
    ),
    (
        "grade_latency_seconds",
        "histogram",
        "crb_grade_latency_seconds",
        "Wall-clock seconds to grade one trial.",
        ["runner"],
    ),
    (
        "build_latency_seconds",
        "histogram",
        "crb_build_latency_seconds",
        "Wall-clock seconds for one builder attempt.",
        ["builder"],
    ),
    (
        "sandbox_unavailable_total",
        "counter",
        "crb_sandbox_unavailable_total",
        "Times a run stopped because the sandbox failed closed.",
        [],
    ),
    (
        "deliveries_total",
        "counter",
        "crb_deliveries_total",
        "Factory deliveries, by repo and outcome (opened|withheld|failed).",
        ["repo", "outcome"],
    ),
    (
        "github_tokens_minted_total",
        "counter",
        "crb_github_tokens_minted_total",
        "GitHub App installation tokens minted by the worker, by installation id (never the token).",
        ["installation"],
    ),
    (
        "queue_depth",
        "gauge",
        "crb_queue_depth",
        "Queued runs, as the worker last saw them on check-in.",
        [],
    ),
    (
        "false_q1_total",
        "gauge",
        "crb_false_q1_total",
        "Clean ledger rows with a failed belt. MUST be 0.",
        [],
    ),
    ("ledger_rows", "gauge", "crb_ledger_rows", "Rows in the grade ledger.", []),
)

_FACTORIES = {"counter": _counter, "gauge": _gauge, "histogram": _histogram}


def _build_all() -> dict[str, Any]:
    return {attr: _FACTORIES[kind](name, doc, labels) for attr, kind, name, doc, labels in _SPECS}


_metrics = _build_all()
runs_total: Any = _metrics["runs_total"]
tasks_total: Any = _metrics["tasks_total"]
belt_failures_total: Any = _metrics["belt_failures_total"]
builder_tokens_total: Any = _metrics["builder_tokens_total"]
builder_cost_usd_total: Any = _metrics["builder_cost_usd_total"]
grade_latency_seconds: Any = _metrics["grade_latency_seconds"]
build_latency_seconds: Any = _metrics["build_latency_seconds"]
sandbox_unavailable_total: Any = _metrics["sandbox_unavailable_total"]
deliveries_total: Any = _metrics["deliveries_total"]
github_tokens_minted_total: Any = _metrics["github_tokens_minted_total"]
queue_depth: Any = _metrics["queue_depth"]
false_q1_total: Any = _metrics["false_q1_total"]
ledger_rows: Any = _metrics["ledger_rows"]


def specs() -> tuple[tuple[str, str, list[str]], ...]:
    """``(name, kind, labels)`` for every metric this module defines — what the
    documentation ratchet compares against docs/DEPLOYMENT.md."""
    return tuple((name, kind, list(labels)) for _a, kind, name, _d, labels in _SPECS)


_BINDING_ATTRS = ("registry", *(attr for attr, *_rest in _SPECS))


def fresh_registry() -> Any:
    """Rebind every metric to a NEW registry and return it (``None`` without the client).

    For tests: the module registry is process-wide and counters only go up, so a test
    that asserts a count needs its own. Every call-site reads the metrics through this
    module's attributes at call time, so rebinding here is enough. Pair it with
    :func:`snapshot_binding` / :func:`restore_binding`: the HTTP series
    (src/crb/server/http_metrics.py) are registered on the ORIGINAL registry at import,
    so a test that leaves the module rebound makes the API's ``/metrics`` lose them."""
    if not _AVAILABLE:  # pragma: no cover
        return None
    # the module attributes ARE the registry binding every call site reads, so a
    # rebinding here is the one honest way to give a test its own counters
    globals()["registry"] = CollectorRegistry()
    globals().update(_build_all())
    return globals()["registry"]


def snapshot_binding() -> dict[str, Any]:
    """The current registry and metric objects, to hand back to :func:`restore_binding`."""
    return {name: globals()[name] for name in _BINDING_ATTRS}


def restore_binding(snapshot: Mapping[str, Any]) -> None:
    """Put a :func:`snapshot_binding` back (a test's fresh registry must not outlive it)."""
    globals().update(dict(snapshot))


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
    *,
    repo: str,
    builder: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    latency_s: float,
) -> None:
    """One builder attempt: tokens by direction, metered cost (both by repo — the number
    a platform team charges back), and its latency."""
    builder_tokens_total.labels(repo, builder, model, "in").inc(tokens_in)
    builder_tokens_total.labels(repo, builder, model, "out").inc(tokens_out)
    builder_cost_usd_total.labels(repo, builder, model).inc(cost_usd)
    build_latency_seconds.labels(builder).observe(latency_s)


def record_event(event: Any) -> None:
    """Meter what an event says (a ``CallbackSink`` on the worker's emitter): a
    ``factory``-stage ``delivery.*`` action counts one delivery by outcome. Any other
    event is ignored. Never raises (a sink must never break a run)."""
    try:
        outcome = DELIVERY_OUTCOMES.get(str(getattr(event, "action", "")))
        if outcome is not None and getattr(event, "stage", "") == "factory":
            deliveries_total.labels(str(getattr(event, "repo", "") or ""), outcome).inc()
    except Exception:  # pragma: no cover — defensive: metering must not affect a run
        _LOG.exception("metrics: record_event failed")


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


#: The worker's exposition binds loopback by default, like the API's ``CRB_BIND_HOST``: the
#: series carry repository names, builder / model names, per-repository cost and GitHub
#: installation ids, so a bare ``crb worker`` on a host (or a laptop) must not offer them to
#: every interface. A container sets ``CRB_METRICS_HOST=0.0.0.0`` (compose, Helm): there the
#: scraper is another pod / service, the port is never published beyond the compose network,
#: and the NetworkPolicy admits only the scraper (docs/DEPLOYMENT.md#9).
LOOPBACK = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 — opted into per container, never the default


def start_worker_exposition(port: int, *, enabled: bool = True, addr: str = LOOPBACK) -> bool:
    """Serve this process's registry on ``addr:port`` (J-TEL-1) — the worker's ``/metrics``,
    where the build / grade / cost series live. ``addr`` defaults to loopback
    (``CRB_METRICS_HOST``). ``True`` when a server was started; ``False`` when metrics are
    disabled, ``port`` is 0, or the client is absent (each is logged once so an operator
    scraping nothing knows why). A port that cannot be bound is logged and the worker
    still runs: a missing dashboard must not stop measurement."""
    if not enabled or int(port) <= 0:
        _LOG.info("worker metrics exposition off (enabled=%s port=%s)", enabled, port)
        return False
    if not _AVAILABLE or registry is None:  # pragma: no cover
        _LOG.warning("worker metrics exposition off: prometheus_client is not installed")
        return False
    try:
        start_http_server(int(port), addr=addr, registry=registry)  # pragma: no cover
    except OSError as exc:  # pragma: no cover — bind failure
        _LOG.error("worker metrics exposition could not bind port %s: %s", port, exc)
        return False
    _LOG.info("worker metrics exposition on %s:%s/metrics", addr, port)  # pragma: no cover
    return True  # pragma: no cover
