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
              runs as ``CRB_ROLE=api``, that the worker deployment runs as ``CRB_ROLE=worker``,
              and (with ``helm`` on PATH) that the chart renders those probes and lints
              ``--strict``. A liveness check on the deep endpoint restarted a healthy API for a
              docker socket the serve container is not meant to have (A11).
How:          Reads ``deploy/Dockerfile`` and the chart templates as text; ``helm template`` /
              ``helm lint`` when available.
Layer:        tests — docs/ARCHITECTURE.md#6-deployment-view
ADRs:         none
Works with:   deploy/Dockerfile (the HEALTHCHECK), deploy/helm/crb/templates/api-deployment.yaml
              and deploy/helm/crb/templates/worker-deployment.yaml (the probes and roles),
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
    render = subprocess.run(
        ["helm", "template", "crb", str(CHART)],
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
