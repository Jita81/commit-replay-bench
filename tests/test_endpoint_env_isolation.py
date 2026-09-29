"""No test reads the developer's endpoint settings: the suite passes the same whatever
``CRB_OPENAI_*`` / ``CRB_AZURE_*`` the shell exports.

Navigation
----------
What it is:   The guard for P-277 — a subprocess run of the endpoint-sensitive test modules
              under a shell that points every OpenAI-compatible builder somewhere else.
What it does: Pins that ``tests/conftest.py``'s autouse ``_no_host_endpoint_env`` clears the
              endpoint variables before every test: with a self-hosted URL, an Azure
              endpoint and a reply length exported, the author, worker and builder suites
              still pass. Once the builders refused a rung naming a provider the endpoint is
              not (G-611), three tests that built a default author or builder began to fail
              on a developer's machine with ``CRB_OPENAI_BASE_URL`` set, and CI (which sets
              nothing) could not see it.
How:          ``subprocess.run`` of ``python -m pytest`` on each module in turn (one child per
              module, so each has its own time limit), with the parent's environment plus the
              hostile variables; the child's output is shown on failure, and a child that ran
              no tests (exit 5: the module skipped whole) fails by name rather than proving
              nothing.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/conftest.py (``_no_host_endpoint_env`` — the fixture under test),
              src/crb/builders/openai_client.py (``EndpointConfig.from_env`` — what the
              variables would change), tests/test_factory_author.py (builds a default
              author), tests/test_worker_test_author.py (the worker's default author),
              tests/test_builders_endpoint.py (reads the configured endpoint),
              tests/test_builders_openai_agent.py (builds a default agent builder),
              tests/test_builders_editblock.py (builds a default edit-block builder)
Tested by:    tests/test_endpoint_env_isolation.py
Touch when:   never for a new repository; a new ``CRB_OPENAI_*`` or ``CRB_AZURE_*`` variable is read
              (add it to the hostile set here and to the fixture); a new module builds a default
              OpenAI-compatible builder or author (add it to ``_MODULES``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent

#: A shell that points every OpenAI-compatible caller at an endpoint no test expects.
HOSTILE = {
    "CRB_OPENAI_BASE_URL": "http://gpu-box.internal:8080/v1",
    "CRB_OPENAI_KEY_ENV": "GPU_BOX_KEY",
    "CRB_OPENAI_MAX_TOKENS": "7",
    "CRB_OPENAI_TIMEOUT_S": "1",
    "CRB_OPENAI_MAX_RETRIES": "0",
    "CRB_AZURE_ENDPOINT": "https://tenant.openai.azure.com",
    "CRB_AZURE_DEPLOYMENT": "d1",
    "CRB_AZURE_API_VERSION": "2024-10-21",
    "CRB_AZURE_KEY_ENV": "TENANT_KEY",
}

_MODULES = (
    "test_factory_author.py",
    "test_worker_test_author.py",
    "test_builders_endpoint.py",
    "test_builders_openai_agent.py",
    "test_builders_editblock.py",
)


@pytest.mark.parametrize("module", _MODULES)
def test_the_suite_ignores_the_shells_endpoint_variables(module: str) -> None:
    env = {**os.environ, **HOSTILE}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:warnings",
            "-o",
            "addopts=",
            str(_TESTS / module),
        ],
        cwd=_TESTS.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    # exit 5 is "no tests ran": the module skipped whole (an importorskip on a package the
    # job did not install, P-707), which proves nothing about the endpoint variables
    assert proc.returncode != 5, f"{module} ran no tests — skipped whole:\n" + proc.stdout[-2000:]
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
