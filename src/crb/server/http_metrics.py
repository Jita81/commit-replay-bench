"""HTTP request metrics, registered on the shared observability registry.

``crb.observability.metrics`` owns the registry (and the no-op fallback when
``prometheus_client`` is absent). This module only ADDS the two HTTP series so a
single ``/metrics`` scrape carries engine and server metrics together:

* ``crb_http_requests_total{method,route,status}`` — counter
* ``crb_http_request_duration_seconds{method,route}`` — histogram

``route`` is the matched route template (``/api/v1/users/{user_id}``), never the
raw path, so cardinality stays bounded and ids never reach the metrics endpoint.
"""

from __future__ import annotations

from typing import Any

from crb.observability import metrics as _m

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

if _m.available() and _m.registry is not None:  # pragma: no cover — extra installed
    from prometheus_client import Counter, Histogram

    http_requests_total: Any = Counter(
        "crb_http_requests_total",
        "HTTP requests, by method, matched route template and status code.",
        ["method", "route", "status"],
        registry=_m.registry,
    )
    http_request_duration_seconds: Any = Histogram(
        "crb_http_request_duration_seconds",
        "HTTP request wall-clock seconds, by method and matched route template.",
        ["method", "route"],
        registry=_m.registry,
        buckets=_BUCKETS,
    )
else:  # pragma: no cover
    http_requests_total = _m._Noop()
    http_request_duration_seconds = _m._Noop()


def observe(method: str, route: str, status: int, duration_s: float) -> None:
    http_requests_total.labels(method, route, str(status)).inc()
    http_request_duration_seconds.labels(method, route).observe(duration_s)


__all__ = ["http_request_duration_seconds", "http_requests_total", "observe"]
