"""The metrics module on a FRESH registry: every recorder, the worker-side counters after
a real harness run, the delivery and token-mint meters, the queue gauge, the worker's
exposition switch, and the no-op path when the client is absent.

The module registry is process-wide and counters only go up, so every test here takes
``metrics.fresh_registry()`` and reads samples back with ``get_sample_value``.

Navigation
----------
What it is:   The observability metrics suite (J-TEL-13 / J-TEL-14).
What it does: Pins ``record_grade`` (outcome mapping; a belt ``False`` is a failure, ``None`` is
              not), ``record_build`` (tokens by direction and cost carry the ``repo`` label),
              ``record_event`` (``delivery.*`` on the factory stage → ``crb_deliveries_total``
              by outcome, nothing else counted), ``crb_runs_total`` per terminal status and
              ``crb_sandbox_unavailable_total`` after worker harness runs, the metered GitHub
              App counting REAL mints only (never a token in a label), ``crb_queue_depth`` on
              check-in, ``start_worker_exposition`` honouring enabled/port, the ``_Noop``
              fallback, and that every metric in the module is in docs/DEPLOYMENT.md's table
              with the same labels (the documentation ratchet).
How:          ``metrics.fresh_registry()`` per test; the worker ``Harness`` from
              tests/test_worker.py for the end-to-end counters; ``GitHubApp.installation_token``
              monkeypatched to a scripted token sequence.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/observability/metrics.py (under test), src/crb/server/worker.py (the
              recorders' call sites, ``_MeteredGitHubApp``, ``checkin``), tests/test_worker.py
              (``Harness`` / ``FakeBuilder``), docs/DEPLOYMENT.md#9-observability (the table
              the ratchet reads), tests/test_server_system.py (the API-side series)
Tested by:    tests/test_observability_metrics.py
Touch when:   a metric is added or relabelled (add its row to docs/DEPLOYMENT.md and a case
              here); never for a new repository.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.core.execution import SandboxUnavailable
from crb.observability import metrics
from crb.observability.events import Emitter, MemorySink, StepStatus
from crb.server import worker as worker_mod
from crb.server.github_app import GitHubApp
from crb.server.settings import GitHubAppSettings
from crb.store.jobs import STATUS_FAILED, STATUS_SUCCEEDED
from fixtures import pyrepo as pr
from test_worker import FakeBuilder, Harness

pytestmark = pytest.mark.skipif(not metrics.available(), reason="prometheus_client not installed")

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def registry() -> Iterator[Any]:
    """A fresh registry every metric is rebound to (the module one is process-wide), put
    back afterwards so the API's HTTP series — registered on the original at import — are
    still what ``/metrics`` renders for the suites that run after this one."""
    saved = metrics.snapshot_binding()
    try:
        yield metrics.fresh_registry()
    finally:
        metrics.restore_binding(saved)


def sample(registry: Any, name: str, **labels: str) -> float | None:
    v = registry.get_sample_value(name, labels or None)
    return None if v is None else float(v)


# --- recorders --------------------------------------------------------------------------


def test_record_grade_maps_outcomes_and_counts_only_false_belts(registry: Any) -> None:
    base = {"repo": "demo", "runner": "pytest", "duration_s": 2.5}
    metrics.record_grade(
        clean=True, disqualified=False, error="", belts={"target_green": True}, **base
    )
    metrics.record_grade(
        clean=False,
        disqualified=False,
        error="",
        belts={"target_green": False, "no_new_failures": None, "tests_unmodified": True},
        **base,
    )
    metrics.record_grade(
        clean=False, disqualified=True, error="", belts={"tests_unmodified": False}, **base
    )
    # an error wins over every other outcome, and its belts still count when they are False
    metrics.record_grade(
        clean=True, disqualified=True, error="boom", belts={"source_changed": False}, **base
    )
    t = "crb_tasks_total"
    assert sample(registry, t, repo="demo", outcome="clean") == 1
    assert sample(registry, t, repo="demo", outcome="not_clean") == 1
    assert sample(registry, t, repo="demo", outcome="disqualified") == 1
    assert sample(registry, t, repo="demo", outcome="error") == 1
    b = "crb_belt_failures_total"
    assert sample(registry, b, belt="target_green") == 1
    assert sample(registry, b, belt="tests_unmodified") == 1
    assert sample(registry, b, belt="source_changed") == 1
    assert sample(registry, b, belt="no_new_failures") is None  # None = not evaluated
    assert sample(registry, "crb_grade_latency_seconds_count", runner="pytest") == 4
    assert sample(registry, "crb_grade_latency_seconds_sum", runner="pytest") == pytest.approx(10.0)


def test_record_build_carries_the_repo_label_on_tokens_and_cost(registry: Any) -> None:
    metrics.record_build(
        repo="demo",
        builder="fake",
        model="m",
        tokens_in=120,
        tokens_out=30,
        cost_usd=0.012,
        latency_s=4.0,
    )
    metrics.record_build(
        repo="other",
        builder="fake",
        model="m",
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.0,  # an unpriced model contributes 0: the total is a floor, not a bill
        latency_s=1.0,
    )
    tok = "crb_builder_tokens_total"
    assert sample(registry, tok, repo="demo", builder="fake", model="m", kind="in") == 120
    assert sample(registry, tok, repo="demo", builder="fake", model="m", kind="out") == 30
    cost = "crb_builder_cost_usd_total"
    assert sample(registry, cost, repo="demo", builder="fake", model="m") == pytest.approx(0.012)
    assert sample(registry, cost, repo="other", builder="fake", model="m") == 0.0
    assert sample(registry, "crb_build_latency_seconds_count", builder="fake") == 2


def test_record_event_meters_deliveries_by_outcome_and_nothing_else(registry: Any) -> None:
    em = Emitter(MemorySink(), trace_id="t" * 32, actor="op", repo="demo")
    em.emit("factory", "delivery.opened", task_id="i1", branch="crb/i1", pr="…/pull/7")
    em.emit("factory", "delivery.withheld", task_id="i2", status=StepStatus.SKIPPED)
    em.emit("factory", "delivery.error", task_id="i3", status=StepStatus.ERROR, error="push")
    em.emit("factory", "delivery.skipped", task_id="i4", status=StepStatus.SKIPPED)  # opt-in off
    em.emit("factory", "delivery.override", task_id="i5", override_by="appr")
    em.emit("system", "delivery.opened", task_id="i6")  # wrong stage: not a delivery
    for ev in em.sink._events:  # type: ignore[attr-defined]
        metrics.record_event(ev)
    d = "crb_deliveries_total"
    assert sample(registry, d, repo="demo", outcome="opened") == 1
    assert sample(registry, d, repo="demo", outcome="withheld") == 1
    assert sample(registry, d, repo="demo", outcome="failed") == 1
    assert {o for (o,) in [(k,) for k in ("skipped", "override")]} and all(
        sample(registry, d, repo="demo", outcome=o) is None for o in ("skipped", "override")
    )
    assert metrics.DELIVERY_OUTCOMES == {
        "delivery.opened": "opened",
        "delivery.withheld": "withheld",
        "delivery.error": "failed",
    }
    metrics.record_event(object())  # not an event at all: ignored, never raises


# --- the worker's counters end to end --------------------------------------------------


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)  # as test_worker does
    FakeBuilder.briefs = []
    FakeBuilder.hook = None
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


def test_worker_runs_total_and_sandbox_unavailable_after_harness_runs(
    registry: Any, h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = h.enqueue("replay")
    assert h.run_one().status == STATUS_SUCCEEDED
    assert sample(registry, "crb_runs_total", kind="replay", status="succeeded") == 1
    # the grade and build recorders fired from the run ledger, with the repo label
    assert sample(registry, "crb_tasks_total", repo=pr.REPO_NAME, outcome="clean") == 1
    assert (
        sample(
            registry,
            "crb_builder_tokens_total",
            repo=pr.REPO_NAME,
            builder="fake",
            model="m",
            kind="in",
        )
        is not None
    )
    assert sample(registry, "crb_deliveries_total", repo=pr.REPO_NAME, outcome="opened") is None
    assert run.id  # the run exists

    def refuse(kind: str, *, docker: Any = None, **_kw: Any) -> Any:
        raise SandboxUnavailable("docker daemon not reachable")

    monkeypatch.setattr(worker_mod, "make_executor", refuse)
    h.enqueue("replay", params_json={"executor": "docker", "image": "crb/py:1"})
    assert h.run_one().status == STATUS_FAILED
    assert sample(registry, "crb_sandbox_unavailable_total") == 1
    assert sample(registry, "crb_runs_total", kind="replay", status="failed") == 1
    assert FakeBuilder.briefs  # the first run built; the second never reached a builder


def test_checkin_sets_the_queue_depth_gauge(registry: Any, h: Harness) -> None:
    h.enqueue("replay")
    h.enqueue("mine")
    h.worker.checkin()
    assert sample(registry, "crb_queue_depth") == 2
    assert h.run_one().status == STATUS_SUCCEEDED  # execute() checks in on its way out
    assert sample(registry, "crb_queue_depth") == 1


def test_metered_github_app_counts_real_mints_only_and_never_the_token(
    registry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    app = worker_mod._MeteredGitHubApp(GitHubAppSettings(app_id="4242", private_key=pem))
    script = iter(
        [
            "ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "ghs_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        ]
    )
    monkeypatch.setattr(
        GitHubApp, "installation_token", lambda self, iid, *, now=None: next(script)
    )
    assert app.installation_token(77) == "ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert app.installation_token(77) == "ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # cache hit
    assert app.installation_token(77) == "ghs_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"  # a refresh
    assert sample(registry, "crb_github_tokens_minted_total", installation="77") == 2
    exposition = metrics.render().decode()
    assert "ghs_" not in exposition and 'installation="77"' in exposition


# --- the worker's exposition and the no-op path -----------------------------------------


def test_start_worker_exposition_honours_the_switches(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="crb.observability.metrics")
    assert metrics.start_worker_exposition(9464, enabled=False) is False
    assert metrics.start_worker_exposition(0, enabled=True) is False
    assert "exposition off" in caplog.text


def test_start_worker_exposition_serves_the_registry_on_a_free_port(registry: Any) -> None:
    import socket
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    metrics.queue_depth.set(3)
    assert metrics.start_worker_exposition(port, addr="127.0.0.1") is True
    deadline = time.monotonic() + 5
    body = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=1) as r:
                body = r.read().decode()
            break
        except OSError:
            time.sleep(0.05)
    assert "crb_queue_depth 3.0" in body
    assert threading.active_count() >= 1


def test_noop_when_the_client_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "_AVAILABLE", False)  # monkeypatch puts both back
    monkeypatch.setattr(metrics, "registry", None)
    noop = metrics._Noop()
    noop.labels("a", "b").inc(3)
    noop.set(1)
    noop.observe(2.0)
    assert metrics.render() == b"" and metrics.available() is False
    assert metrics.start_worker_exposition(9464) is False


# --- the documentation ratchet ----------------------------------------------------------


def test_every_metric_is_documented_with_its_labels() -> None:
    """docs/DEPLOYMENT.md §9 is what a platform team wires alerts from; a metric or a label
    that is not there (or is there under the wrong labels) is a dashboard that reads absent."""
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    rows = {
        m.group(1): (m.group(2).strip(), m.group(3).strip())
        for m in re.finditer(r"^\| `(crb_[a-z0-9_]+)` \| (\w+) \| `?([^|]*?)`? \|", text, re.M)
    }
    for name, kind, labels in metrics.specs():
        assert name in rows, f"{name} is not in docs/DEPLOYMENT.md §9"
        doc_kind, doc_labels = rows[name]
        assert doc_kind == kind, (name, doc_kind, kind)
        documented = [x.strip() for x in doc_labels.split(",") if x.strip() and x.strip() != "—"]
        assert documented == labels, (name, documented, labels)
    # the API's HTTP series are documented too
    assert "crb_http_requests_total" in rows and "crb_http_request_duration_seconds" in rows
