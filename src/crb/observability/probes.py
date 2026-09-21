"""Health probes: is the instrument able to measure right now?

Each probe returns a :class:`ProbeResult` (ok / degraded / down + detail). The
aggregate is what ``/health`` and ``crb doctor`` render. A probe never raises: every
read runs under :func:`run_probe`, and a read that raises is ``down`` with ONE fixed
detail — ``<probe> could not be read — see the API log, request id …`` — while the
exception itself is logged under that request id. ``/health`` is unauthenticated, and a
driver's, Alembic's or the OS's message can carry a DSN, a host, a user, a path or SQL
(CWE-209): nothing an exception says is ever served.

Navigation
----------
What it is:   The health probes — toolchains on PATH, the docker daemon, configured builder
              credentials, any wrapped callable (a DB ping) — the ``run_probe`` guard every
              read runs under, and the ``aggregate`` that rolls them into one status.
What it does: Answers "can the instrument measure right now?" without ever raising: a
              missing ``git`` is ``down``, a missing optional toolchain ``degraded``, an
              unreachable daemon ``down`` (sandboxed runs would fail closed), no builder
              credential ``degraded``; ``skipped`` never lowers the aggregate; a read that
              raises is ``down`` with the fixed ``failure_detail`` and the exception logged
              (``request_id`` in the log record and in the sentence), never served.
How:          ``shutil.which`` / ``docker info`` / environment lookups → ``ProbeResult`` →
              ``aggregate`` takes the worst of ``ok < degraded < down``; ``run_probe`` is
              the one ``try``/``except`` (``log.exception`` + ``failure_detail``).
Layer:        observability — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/routes/system.py (``/health`` and ``/health/live`` — which
              probes run depends on ``CRB_ROLE``; its store probes run under ``run_probe``
              with the request's id), src/crb/cli/commands/service.py (``crb doctor`` adds
              the Claude Code login probe and the database ping; no request, so no id),
              src/crb/builders/container.py (``probe_builder_container``, the sealed-
              container counterpart), deploy/helm/crb/templates/api-service.yaml (the
              readiness/liveness endpoints these feed), docs/API.md#the-migrations-probe
              (the served shape of a failed read)
Tested by:    tests/test_server_system.py, tests/test_deploy_health_probes.py
Touch when:   onboarding a repository in a language whose toolchain is not in
              ``probe_toolchains``'s default list — add the binary name so ``/health`` says
              ``degraded`` before a sweep fails; a new credential source joins
              ``probe_builders`` (name only, never the value); a new probe's read goes
              under ``run_probe`` — never format an exception into a ``detail``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("crb.observability.probes")

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


def failure_detail(name: str, request_id: str = "") -> str:
    """The ONE ``detail`` a probe serves when its read raised: ``<name> could not be read —
    see the API log, request id <id>`` (``see the log`` when there is no request: the
    probes ``crb doctor`` shares — sandbox, worker — render this form; doctor's own
    ``migrations`` and ``database`` lines print the exception, since a local terminal has
    no unauthenticated reader). Fixed on purpose (CWE-209): the exception is in the log."""
    where = f"see the API log, request id {request_id}" if request_id else "see the log"
    return f"{name} could not be read — {where}"


def run_probe(name: str, read: Callable[[], ProbeResult], *, request_id: str = "") -> ProbeResult:
    """Run ``read`` — the guard EVERY probe's read goes under. A raise is ``down`` with
    :func:`failure_detail` and empty ``data``; the exception is logged at ERROR with its
    traceback and the request id (``request_id`` is also a field of the record, so the
    JSON log is searchable by the id the sentence names)."""
    try:
        return read()
    except Exception:
        log.exception(
            "%s probe failed (request_id=%s)",
            name,
            request_id or "-",
            extra={"probe": name, "request_id": request_id},
        )
        return ProbeResult(name, DOWN, failure_detail(name, request_id))


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


def probe_docker(timeout: int = 10, *, request_id: str = "") -> ProbeResult:
    """``docker info`` answers → ``ok`` with the server version; otherwise ``down`` (a
    CLI that cannot be run — a socket path, a permission — is a failed read, logged)."""

    def _read() -> ProbeResult:
        binary = shutil.which("docker")
        if not binary:
            return ProbeResult(
                "sandbox", DOWN, "docker binary not on PATH — sandboxed runs will fail closed"
            )
        r = subprocess.run(
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if r.returncode != 0:
            return ProbeResult(
                "sandbox", DOWN, "docker daemon not reachable — sandboxed runs will fail closed"
            )
        version = r.stdout.strip()
        return ProbeResult("sandbox", OK, f"docker {version}", {"version": version})

    return run_probe("sandbox", _read, request_id=request_id)


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


def probe_callable(name: str, fn: Callable[[], Any], *, request_id: str = "") -> ProbeResult:
    """Wrap an arbitrary check (e.g. a DB ping) so it never raises — ``ok`` with what it
    returned as ``data``, or :func:`run_probe`'s fixed ``down``."""

    def _read() -> ProbeResult:
        data = fn()
        return ProbeResult(
            name, OK, "ok", data if isinstance(data, dict) else {"result": str(data)}
        )

    return run_probe(name, _read, request_id=request_id)


def aggregate(results: Iterable[ProbeResult]) -> dict[str, Any]:
    """The worst status across probes (``skipped`` counts as neutral) plus every probe."""
    rs = list(results)
    worst = OK
    for r in rs:
        if r.status == DOWN:
            worst = DOWN
            break
        if r.status == DEGRADED or r.status not in (OK, SKIPPED):
            # an unknown status is never "ok": fail closed to degraded (CodeRabbit on PR #3)
            worst = DEGRADED
    return {"status": worst, "probes": [r.to_dict() for r in rs]}
