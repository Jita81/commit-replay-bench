"""No test reads the developer's endpoint settings: the suite passes the same whatever
``CRB_OPENAI_*`` / ``CRB_AZURE_*`` the shell exports.

Navigation
----------
What it is:   The guard for P-969 — a subprocess run of the endpoint-sensitive test modules
              under a shell that points every OpenAI-compatible builder somewhere else.
What it does: Pins that ``tests/conftest.py``'s autouse ``_no_host_endpoint_env`` clears the
              endpoint variables before every test: with a self-hosted URL, an Azure
              endpoint and a reply length exported, the author, worker and builder suites
              still pass. Once the builders refused a rung naming a provider the endpoint is
              not (G-611), three tests that built a default author or builder began to fail
              on a developer's machine with ``CRB_OPENAI_BASE_URL`` set, and CI (which sets
              nothing) could not see it.
How:          ``subprocess.run`` of ``python -m pytest`` on the modules, with the parent's
              environment plus the hostile variables; the child's output is shown on failure.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/conftest.py (``_no_host_endpoint_env`` — the fixture under test),
              src/crb/builders/openai_client.py (``EndpointConfig.from_env`` — what the
              variables would change), tests/test_factory_author.py and
              tests/test_worker_test_author.py (the modules that read the default endpoint)
Tested by:    tests/test_endpoint_env_isolation.py
Touch when:   a new ``CRB_OPENAI_*`` or ``CRB_AZURE_*`` variable is read (add it to the
              hostile set here and to the fixture); a new module builds a default
              OpenAI-compatible builder or author (add it to ``_MODULES``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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

_MODULES = ("test_factory_author.py", "test_worker_test_author.py")


def test_the_suite_ignores_the_shells_endpoint_variables() -> None:
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
            *(str(_TESTS / m) for m in _MODULES),
        ],
        cwd=_TESTS.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
