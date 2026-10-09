"""Blocked egress is reported, metered and named (G-400).

OPERATOR §8 names "a sandbox escape or unexpected network egress from a test container" as
a stop condition, and nothing surfaced the one signal the product has for it: the egress
sidecar's ``deny`` lines. A sealed build's :class:`ContainerSession` now reads them on close
and reports them once as ``builder.egress_denied {hosts, n}``; the worker's ``record_event``
meters them into ``crb_egress_denied_total{repo}``, which DEPLOYMENT §9.2 alerts on.

Navigation
----------
What it is:   The suite for the egress-denied report from a container session to the metric.
What it does: A sidecar whose proxy log carries ``deny evil.example:443`` makes the session
              emit ``builder.egress_denied`` with that host on the raw callback, exactly once
              across two closes; the event, bridged the way the worker bridges a builder
              callback (``build`` stage), increments ``crb_egress_denied_total{repo}`` by the
              number of hosts; an allow-only log emits nothing and counts nothing; the metric
              is a worker series.
How:          A real ``EgressSidecar`` over a fake ``docker`` that answers ``logs`` with a
              canned tail; a session over an executor stub; ``Emitter`` + ``MemorySink`` for
              the bridge; the metrics module rebound to a fresh registry.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/builders/container.py (``ContainerSession.report_egress`` / ``close``),
              src/crb/builders/sidecar.py (``denied_hosts``), src/crb/observability/metrics.py
              (``record_event``, ``EGRESS_DENIED_ACTION``, ``WORKER_SERIES``),
              src/crb/builders/adapter.py (passes the raw ``on_event`` into the session),
              docs/API.md#event-vocabulary (the action's row), docs/DEPLOYMENT.md#92-alert-rules
              (the alert that reads the counter)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the sidecar's log line format changes (the ``deny``
              regex in sidecar.py), or the action or the metric is renamed — change API.md and
              DEPLOYMENT §9.1 with it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from crb.builders.container import BuilderContainerSettings, ContainerSession
from crb.builders.sidecar import EgressSidecar
from crb.observability import metrics
from crb.observability.events import Emitter, MemorySink

pytestmark = pytest.mark.skipif(not metrics.available(), reason="prometheus_client not installed")


@pytest.fixture
def registry() -> Iterator[Any]:
    saved = metrics.snapshot_binding()
    try:
        yield metrics.fresh_registry()
    finally:
        metrics.restore_binding(saved)


def _sidecar(tail: str, tmp_path: Path) -> EgressSidecar:
    """A started-looking sidecar whose ``docker logs`` answers ``tail``."""

    def docker(*args: str, timeout: int = 0) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "logs":
            return subprocess.CompletedProcess(list(args), 0, stdout=tail, stderr="")
        return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")

    sc = EgressSidecar(
        docker,
        network="crb-b-test",
        proxy_name="crb-proxy-test",
        allow_hosts=["api.anthropic.com:443"],
        egress_network="bridge",
        proxy_image="crb-builder:test",
        user="10001:10001",
        script=tmp_path / "egress.py",
    )
    sc._proxy_started = True  # the log is read from the container until close
    return sc


def _session(
    tmp_path: Path, tail: str, events: list[tuple[str, dict[str, Any]]]
) -> ContainerSession:
    checkout: Any = SimpleNamespace(root=tmp_path / "sealed", link_targets={})
    session = ContainerSession(
        BuilderContainerSettings(image="crb-builder:test", user="10001:10001"),
        checkout,
        executor=SimpleNamespace(docker="docker", cancel_fn=None),  # type: ignore[arg-type]
        label="egress",
        on_event=lambda action, payload: events.append((action, dict(payload))),
    )
    session.sidecar = _sidecar(tail, tmp_path)
    return session


def test_a_denied_host_in_the_sidecar_log_is_reported_once_and_counted(
    registry: Any, tmp_path: Path
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    tail = "allow api.anthropic.com:443\ndeny evil.example:443\ndeny evil.example:443\n"
    session = _session(tmp_path, tail, events)
    session.close()
    session.close()  # idempotent: the second close reports nothing
    assert events == [("builder.egress_denied", {"hosts": ["evil.example:443"], "n": 1})]
    assert session.denied_hosts == ["evil.example:443"]  # still readable after close

    # the worker bridges a builder callback onto its emitter under the ``build`` stage and
    # meters every event through ``record_event`` (src/crb/server/worker.py)
    em = Emitter(MemorySink(), trace_id="t" * 32, actor="worker", repo="demo")
    for action, payload in events:
        em.on_event("build")(action, payload)
    for ev in em.sink._events:  # type: ignore[attr-defined]
        metrics.record_event(ev)
    assert registry.get_sample_value("crb_egress_denied_total", {"repo": "demo"}) == 1.0
    assert "crb_egress_denied_total" in metrics.WORKER_SERIES
    assert metrics.EGRESS_DENIED_ACTION == "builder.egress_denied"


def test_an_allow_only_log_reports_nothing_and_counts_nothing(
    registry: Any, tmp_path: Path
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    session = _session(tmp_path, "allow api.anthropic.com:443\n", events)
    session.close()
    assert events == [] and session.denied_hosts == []
    assert registry.get_sample_value("crb_egress_denied_total", {"repo": "demo"}) is None


def test_two_hosts_count_two_and_a_wrong_stage_counts_nothing(registry: Any) -> None:
    em = Emitter(MemorySink(), trace_id="t" * 32, actor="worker", repo="demo")
    em.emit("build", "builder.egress_denied", hosts=["a.example:443", "b.example:443"], n=2)
    em.emit("factory", "builder.egress_denied", hosts=["c.example:443"], n=1)  # not a build
    for ev in em.sink._events:  # type: ignore[attr-defined]
        metrics.record_event(ev)
    assert registry.get_sample_value("crb_egress_denied_total", {"repo": "demo"}) == 2.0


def test_a_deny_line_older_than_the_kept_tail_is_still_reported(
    registry: Any, tmp_path: Path
) -> None:
    """P-641: ``proxy_log`` keeps the last 4000 characters for display, and a long agentic
    build writes one ``allow`` line per CONNECT — a ``deny`` two hundred connections ago is
    outside that tail. The denied hosts are read from the WHOLE proxy log at close, once;
    the tail stays what the run page shows."""
    events: list[tuple[str, dict[str, Any]]] = []
    whole = "deny evil.example:443\n" + "allow api.anthropic.com:443\n" * 300
    assert len(whole) > 4000 and "deny" not in whole[-4000:]
    session = _session(tmp_path, whole, events)
    session.close()
    assert events == [("builder.egress_denied", {"hosts": ["evil.example:443"], "n": 1})]
    assert session.denied_hosts == ["evil.example:443"]
    assert len(session.proxy_log) == 4000 and "deny" not in session.proxy_log


def test_a_denied_method_is_not_a_denied_host(registry: Any, tmp_path: Path) -> None:
    """The proxy also logs ``deny method=GET`` for a non-CONNECT request; only a
    ``host:port`` target is a denied host — the method line is neither evented nor counted."""
    events: list[tuple[str, dict[str, Any]]] = []
    session = _session(tmp_path, "deny method=GET\nallow api.anthropic.com:443\n", events)
    session.close()
    assert events == [] and session.denied_hosts == []
    session = _session(tmp_path, "deny method=GET\ndeny evil.example:443\n", events)
    session.close()
    assert events == [("builder.egress_denied", {"hosts": ["evil.example:443"], "n": 1})]


def test_an_unnetworked_session_has_no_sidecar_and_reports_nothing(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    checkout: Any = SimpleNamespace(root=tmp_path / "sealed", link_targets={})
    session = ContainerSession(
        BuilderContainerSettings(image="crb-builder:test", user="10001:10001", allow_hosts=()),
        checkout,
        executor=SimpleNamespace(docker="docker", cancel_fn=None),  # type: ignore[arg-type]
        on_event=lambda action, payload: events.append((action, dict(payload))),
    )
    assert session.sidecar is None and session.denied_hosts == []
    session.close()
    assert events == []
