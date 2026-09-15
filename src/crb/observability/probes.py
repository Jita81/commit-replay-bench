"""Health probes: is the instrument able to measure right now?

Each probe returns a :class:`ProbeResult` (ok / degraded / down + detail). The
aggregate is what ``/health`` and ``crb doctor`` render. A probe never raises.

Navigation
----------
What it is:   The health probes — toolchains on PATH, the docker daemon, configured builder
              credentials, any wrapped callable (a DB ping) — and the ``aggregate`` that
              rolls them into one status.
What it does: Answers "can the instrument measure right now?" without ever raising: a
              missing ``git`` is ``down``, a missing optional toolchain ``degraded``, an
              unreachable daemon ``down`` (sandboxed runs would fail closed), no builder
              credential ``degraded``; ``skipped`` never lowers the aggregate.
How:          ``shutil.which`` / ``docker info`` / environment lookups → ``ProbeResult`` →
              ``aggregate`` takes the worst of ``ok < degraded < down``.
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/routes/system.py (``/health`` and ``/health/live`` — which
              probes run depends on ``CRB_ROLE``), src/crb/cli/commands/service.py (``crb
              doctor`` adds the Claude Code login probe and the database ping),
              src/crb/builders/container.py (``probe_builder_container``, the sealed-
              container counterpart), deploy/helm/crb/templates/api-service.yaml (the
              readiness/liveness endpoints these feed)
Tested by:    tests/test_server_system.py, tests/test_deploy_health_probes.py
Touch when:   onboarding a repository in a language whose toolchain is not in
              ``probe_toolchains``'s default list — add the binary name so ``/health`` says
              ``degraded`` before a sweep fails; a new credential source joins
              ``probe_builders`` (name only, never the value).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

OK = "ok"
DEGRADED = "degraded"
DOWN = "down"
#: A probe deliberately not run for this process role (e.g. the sandbox probe on an api
#: container without a docker socket); never lowers the aggregate.
SKIPPED = "skipped"


@dataclass(frozen=True)
class ProbeResult:
    """One probe's answer: ``status`` ∈ ok | degraded | down | skipped, a human ``detail``
    and machine ``data`` (never a secret value — presence flags only)."""

    name: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The ``/health`` JSON shape for one probe."""
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "data": dict(self.data),
        }


def probe_toolchains(
    names: Iterable[str] = ("git", "python3", "go", "node", "mvn", "cargo"),
) -> ProbeResult:
    """Which language toolchains are on PATH; ``git`` missing is ``down``, others ``degraded``."""
    found = {n: bool(shutil.which(n)) for n in names}
    missing = [n for n, ok in found.items() if not ok]
    status = DOWN if not found.get("git") else (DEGRADED if missing else OK)
    return ProbeResult(
        "toolchains", status, "missing: " + ", ".join(missing) if missing else "all present", found
    )


def probe_docker(timeout: int = 10) -> ProbeResult:
    """``docker info`` answers → ``ok`` with the server version; otherwise ``down``."""
    binary = shutil.which("docker")
    if not binary:
        return ProbeResult(
            "sandbox", DOWN, "docker binary not on PATH — sandboxed runs will fail closed"
        )
    try:
        r = subprocess.run(
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return ProbeResult("sandbox", DOWN, f"docker probe failed: {e}")
    if r.returncode != 0:
        return ProbeResult(
            "sandbox", DOWN, "docker daemon not reachable — sandboxed runs will fail closed"
        )
    return ProbeResult("sandbox", OK, f"docker {r.stdout.strip()}", {"version": r.stdout.strip()})


def probe_builders(env: dict[str, str] | None = None) -> ProbeResult:
    """Which builder credentials / CLIs are configured (presence only, never values)."""
    e = env if env is not None else dict(os.environ)
    keys = {
        "anthropic": bool(e.get("ANTHROPIC_API_KEY")),
        "openai": bool(e.get("OPENAI_API_KEY")),
        "azure_openai": bool(e.get("AZURE_OPENAI_API_KEY") and e.get("AZURE_OPENAI_ENDPOINT")),
        "cerebras": bool(e.get("CEREBRAS_API_KEY")),
        "claude_code_cli": bool(shutil.which("claude")),
    }
    configured = [k for k, v in keys.items() if v]
    status = OK if configured else DEGRADED
    return ProbeResult("builders", status, "configured: " + (", ".join(configured) or "none"), keys)


def probe_callable(name: str, fn: Callable[[], Any]) -> ProbeResult:
    """Wrap an arbitrary check (e.g. a DB ping) so it never raises."""
    try:
        data = fn()
    except Exception as exc:
        return ProbeResult(name, DOWN, f"{type(exc).__name__}: {exc}")
    return ProbeResult(name, OK, "ok", data if isinstance(data, dict) else {"result": str(data)})


def aggregate(results: Iterable[ProbeResult]) -> dict[str, Any]:
    """The worst status across probes (``skipped`` counts as neutral) plus every probe."""
    rs = list(results)
    worst = OK
    for r in rs:
        if r.status == DOWN:
            worst = DOWN
            break
        if r.status == DEGRADED:
            worst = DEGRADED
    return {"status": worst, "probes": [r.to_dict() for r in rs]}
