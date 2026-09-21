"""The deploy artefacts point liveness at ``/health/live`` and readiness at ``/health``.

Liveness = "the process is up and its database answers" (one probe, never the
sandbox); readiness = the deep probe. A liveness check on the deep endpoint restarts
a healthy API for a docker socket the serve container is not meant to have (A11).
The API pod runs as ``CRB_ROLE=api`` so the deep probe reports the sandbox
``skipped``; the worker pod as ``CRB_ROLE=worker``.

Navigation
----------
What it is:   The deploy artefacts' probe test suite — liveness at ``/health/live``, readiness
              at ``/health``, roles per pod.
What it does: Pins that the Dockerfile's ``HEALTHCHECK`` is the liveness endpoint, that the Helm
              API deployment probes liveness on ``/health/live`` and readiness on ``/health`` and
              runs as ``CRB_ROLE=api``, that the worker deployment runs as ``CRB_ROLE=worker``
              and exposes its own metrics port in compose and the chart (J-TEL-1), and (with
              ``helm`` on PATH) that the chart renders those probes and lints ``--strict``. A liveness check on the deep endpoint restarted a healthy API for a
              docker socket the serve container is not meant to have (A11).
How:          Reads ``deploy/Dockerfile`` and the chart templates as text; ``helm template`` /
              ``helm lint`` when available.
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/Dockerfile (the HEALTHCHECK), deploy/helm/crb/templates/api-deployment.yaml
              and deploy/helm/crb/templates/worker-deployment.yaml (the probes and roles),
              deploy/helm/crb/templates/worker-service.yaml and deploy/docker-compose.yml (the
              worker's metrics port),
              src/crb/server/routes/system.py (the endpoints), tests/test_server_system.py (the
              endpoints' own suite), docs/DEPLOYMENT.md (the image and its roles, §2)
Tested by:    tests/test_deploy_health_probes.py
Touch when:   a probe endpoint or a pod role is added (the template and this suite together);
              never point liveness at the deep probe.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "deploy" / "Dockerfile"
CHART = ROOT / "deploy" / "helm" / "crb"
API_DEPLOYMENT = CHART / "templates" / "api-deployment.yaml"
WORKER_DEPLOYMENT = CHART / "templates" / "worker-deployment.yaml"

LIVE = "/api/v1/health/live"
DEEP = "/api/v1/health"


def _probe_path(template: str, probe: str) -> str:
    m = re.search(rf"{probe}:\s*\n\s*httpGet:\s*\n\s*path:\s*(\S+)", template)
    assert m, f"{probe} not found"
    return m.group(1)


def test_dockerfile_healthcheck_is_the_liveness_endpoint() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    m = re.search(r"^HEALTHCHECK[^\n]*\\\n\s*CMD\s*(\[.*\])\s*$", text, re.M)
    assert m, "HEALTHCHECK not found"
    cmd = m.group(1)
    assert LIVE in cmd
    assert f"{DEEP}'" not in cmd and f'{DEEP}"' not in cmd  # never the deep probe


def test_helm_api_probes_liveness_live_readiness_deep_and_role_api() -> None:
    text = API_DEPLOYMENT.read_text(encoding="utf-8")
    assert _probe_path(text, "livenessProbe") == LIVE
    assert _probe_path(text, "startupProbe") == LIVE
    assert _probe_path(text, "readinessProbe") == DEEP
    assert re.search(r"name:\s*CRB_ROLE\s*\n\s*value:\s*\"api\"", text)


def test_helm_worker_runs_as_role_worker() -> None:
    text = WORKER_DEPLOYMENT.read_text(encoding="utf-8")
    assert re.search(r"name:\s*CRB_ROLE\s*\n\s*value:\s*\"worker\"", text)


def test_worker_exposes_its_own_metrics_port_in_every_shipped_shape() -> None:
    """J-TEL-1: the build / grade / cost series are recorded in the worker process, so a
    scrape of the api alone shows none of them. Compose exposes the worker's port on the
    internal network; the chart sets ``CRB_METRICS_PORT``, names a container port, fronts
    it with a headless Service and (opt-in) a ServiceMonitor for ``component: worker``."""
    compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    worker = compose.split("\n  worker:\n", 1)[1]
    assert "CRB_METRICS_PORT: ${CRB_METRICS_PORT:-9464}" in worker
    # the worker binds loopback by default; the container opts into every interface so the
    # compose network (and nothing beyond it) can reach the port
    assert "CRB_METRICS_HOST: 0.0.0.0" in worker
    assert re.search(r"\n    expose:\n      - \"\$\{CRB_METRICS_PORT:-9464\}\"", worker)
    assert "ports:" not in worker.split("healthcheck:")[0]  # internal only, never published
    deployment = WORKER_DEPLOYMENT.read_text(encoding="utf-8")
    assert re.search(r"name:\s*CRB_METRICS_HOST\s*\n\s*value:\s*\"0.0.0.0\"", deployment)
    assert re.search(
        r"name:\s*CRB_METRICS_PORT\s*\n\s*value:\s*\{\{ .Values.worker.metrics.port", deployment
    )
    assert (
        "name: metrics" in deployment
        and "containerPort: {{ int .Values.worker.metrics.port }}" in deployment
    )
    service = (CHART / "templates" / "worker-service.yaml").read_text(encoding="utf-8")
    assert "clusterIP: None" in service and "kind: ServiceMonitor" in service
    assert "app.kubernetes.io/component: worker" in service
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert re.search(r"\n  metrics:\n    port: 9464\n", values)
    assert re.search(r"serviceMonitor:\n(?:.*\n)*?  worker:\n    enabled: false", values)


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not on PATH")
def test_helm_renders_the_probes_and_lints_strict() -> None:
    lint = subprocess.run(
        ["helm", "lint", "--strict", str(CHART)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
    # the default (external postgres) needs its CIDR under the default-deny policy;
    # without one the chart refuses to render rather than deny every pod its database
    bare = subprocess.run(
        ["helm", "template", "crb", str(CHART)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert bare.returncode != 0 and "postgres.cidrs is empty" in bare.stderr
    render = subprocess.run(
        [
            "helm",
            "template",
            "crb",
            str(CHART),
            "--set",
            "networkPolicy.postgres.cidrs={10.0.0.0/8}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert render.returncode == 0, render.stderr
    api = render.stdout.split("kind: Deployment")[1:]
    api_doc = next(d for d in api if "app.kubernetes.io/component: api" in d)
    assert _probe_path(api_doc, "livenessProbe") == LIVE
    assert _probe_path(api_doc, "readinessProbe") == DEEP
    assert re.search(r"name:\s*CRB_ROLE\s*\n\s*value:\s*\"api\"", api_doc)
    # J-TEL-1: the worker pod carries the metrics port and a headless Service fronts it
    worker_doc = next(d for d in api if "app.kubernetes.io/component: worker" in d)
    assert re.search(r"name:\s*CRB_METRICS_PORT\s*\n\s*value:\s*\"9464\"", worker_doc)
    assert "containerPort: 9464" in worker_doc
    services = render.stdout.split("kind: Service\n")[1:]
    assert any("clusterIP: None" in d and "component: worker" in d for d in services)
    # port 0 switches every worker-metrics object off
    off = subprocess.run(
        [
            "helm",
            "template",
            "crb",
            str(CHART),
            "--set",
            "networkPolicy.postgres.cidrs={10.0.0.0/8}",
            "--set",
            "worker.metrics.port=0",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert off.returncode == 0, off.stderr
    assert "crb-worker-metrics-ingress" not in off.stdout and "name: metrics" not in off.stdout
