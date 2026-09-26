"""The egress sidecar: an ``--internal`` network whose only way out is the allowlisting proxy.

Extracted from :class:`crb.builders.container.ContainerSession` (ADR-0012) with no change in
behaviour, so the dependency fetch (ADR-0019) reuses the same wall: a container on the
internal network has no DNS and no default route; the sidecar is dual-homed — the
operator's egress network plus the internal one, where it answers as ``proxy`` — and runs
:mod:`crb.builders.egress_proxy`, CONNECT-only to the exact ``host[:port]`` allowlist.

Lifecycle: :meth:`EgressSidecar.start` creates the network, starts the sidecar (with the
proxy script copied beside the caller's scratch and mounted read-only), joins it to the
internal network and waits for its ``READY`` line — failing closed
(:class:`~crb.core.execution.SandboxUnavailable`) at every step. :meth:`close` keeps the
proxy's log tail (its ``allow`` / ``deny`` decisions, never tunnel contents), removes the
sidecar and the network, and never raises. :meth:`denied_hosts` reads the ``deny`` lines —
what a failed fetch names in its refusal.

Navigation
----------
What it is:   The egress sidecar — one ``--internal`` docker network plus the CONNECT-only
              allowlisting proxy container that is its only route out.
What it does: Starts the network and the proxy for an exact host allowlist, waits for
              ``READY``, fails closed on any step, keeps the decision log, tears everything
              down; shared by the sealed builder and the dependency fetch.
How:          ``docker network create --internal`` → ``docker run -d`` of the proxy on the
              egress network (hardened, read-only, script mounted read-only) → ``docker
              network connect --alias proxy`` → poll ``docker logs`` for ``READY`` → on close
              ``logs`` / ``rm -f`` / ``network rm``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/builders/egress_proxy.py (the program the sidecar runs),
              src/crb/builders/container.py (the sealed builder's session uses it),
              src/crb/provision/fetch.py (the dependency fetch uses it),
              src/crb/core/execution.py (``SandboxUnavailable``)
Tested by:    tests/test_builders_container.py, tests/test_builders_container_docker.py,
              tests/test_provision_fetch.py
Touch when:   never for a new repository; a new endpoint is an allowlist entry
              (``CRB_BUILDER__ALLOW_HOSTS`` / ``CRB_PROVISION__*``), never an edit here; any
              flag on the sidecar's ``docker run`` is a security decision (docs/SECURITY.md).
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from crb.builders import egress_proxy
from crb.core.execution import SandboxUnavailable

#: The sidecar's name on the internal network and the port it listens on.
PROXY_ALIAS = "proxy"
PROXY_PORT = 3128
#: Where the proxy script is mounted inside the sidecar.
PROXY_SCRIPT_INSIDE = "/opt/crb/egress_proxy.py"
#: Seconds to wait for the sidecar's ``READY`` line before failing closed.
PROXY_START_TIMEOUT_S = 30.0

#: ``docker <args…>`` with the client's minimal environment → the completed process.
DockerCall = Callable[..., "subprocess.CompletedProcess[str]"]

_DENY = re.compile(r"\bdeny\s+(\S+)")


class EgressSidecar:
    """One internal network and its proxy. ``docker`` runs one docker CLI call
    (``docker(*args, timeout=…)``); the caller owns the client environment."""

    def __init__(
        self,
        docker: DockerCall,
        *,
        network: str,
        proxy_name: str,
        allow_hosts: Sequence[str],
        egress_network: str,
        proxy_image: str,
        user: str,
        script: Path,
    ) -> None:
        hosts = [h for h in allow_hosts if str(h).strip()]
        try:
            egress_proxy.parse_allow(hosts)
        except ValueError as exc:
            raise SandboxUnavailable(f"egress allowlist invalid: {exc}") from exc
        self._docker = docker
        self.network = network
        self.proxy_name = proxy_name
        self.allow_hosts = tuple(hosts)
        self.egress_network = egress_network
        self.proxy_image = proxy_image
        self.user = user
        self.script = Path(script)
        self._network_created = False
        self._proxy_started = False
        self._script_written = False
        self.log = ""

    @property
    def url(self) -> str:
        """The proxy as a container on the internal network sees it."""
        return f"http://{PROXY_ALIAS}:{PROXY_PORT}"

    def _must(self, *args: str, what: str, timeout: int = 120) -> str:
        try:
            r = self._docker(*args, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxUnavailable(f"{what}: {type(exc).__name__}: {exc}") from exc
        if r.returncode != 0:
            raise SandboxUnavailable(f"{what}: {(r.stderr or r.stdout).strip()[:400]}")
        return str(r.stdout or "").strip()

    def start(self, *, what: str = "builder") -> None:
        """Create the internal network, start the sidecar on the egress network, join it
        to the internal one as ``proxy`` and wait for its ``READY`` line — fail closed at
        every step (the caller calls :meth:`close` on failure)."""
        self.script.write_bytes(Path(egress_proxy.__file__).read_bytes())
        self.script.chmod(0o444)
        self._script_written = True
        self._must(
            "network",
            "create",
            "--internal",
            "--driver",
            "bridge",
            self.network,
            what=f"{what} network create failed",
        )
        self._network_created = True
        # a failed `docker run -d` can still leave a created container behind: mark
        # it for removal BEFORE the attempt (rm -f on a missing name is harmless)
        self._proxy_started = True
        self._must(
            "run",
            "-d",
            "--name",
            self.proxy_name,
            f"--network={self.egress_network}",
            "--memory=256m",
            "--cpus=1",
            "--pids-limit=64",
            f"--user={self.user}",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=16m",
            "--mount",
            f"type=bind,src={self.script},dst={PROXY_SCRIPT_INSIDE},readonly",
            "--env",
            "PYTHONUNBUFFERED=1",
            self.proxy_image,
            "python3",
            PROXY_SCRIPT_INSIDE,
            "--listen",
            f"0.0.0.0:{PROXY_PORT}",  # inside the sidecar; reachable only on the internal network
            "--allow",
            ",".join(self.allow_hosts),
            what="egress proxy start failed",
        )
        self._must(
            "network",
            "connect",
            "--alias",
            PROXY_ALIAS,
            self.network,
            self.proxy_name,
            what=f"egress proxy could not join the {what} network",
        )
        deadline = time.monotonic() + PROXY_START_TIMEOUT_S
        while True:
            logs = self._docker("logs", self.proxy_name, timeout=30)
            text = (logs.stdout or "") + (logs.stderr or "")
            if "READY " in text:
                return
            state = self._docker(
                "inspect", "--format", "{{.State.Running}}", self.proxy_name, timeout=30
            )
            if state.stdout.strip() != "true" or time.monotonic() >= deadline:
                raise SandboxUnavailable(
                    "egress proxy unhealthy (no READY line): " + text.strip()[-400:]
                )
            time.sleep(0.2)

    def read_log(self) -> str:
        """The proxy's log so far (``allow`` / ``deny`` decisions); ``""`` if unreadable."""
        if not self._proxy_started:
            return self.log
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            logs = self._docker("logs", self.proxy_name, timeout=30)
            self.log = ((logs.stdout or "") + (logs.stderr or ""))[-4000:]
        return self.log

    def denied_hosts(self) -> list[str]:
        """``host:port`` for every ``deny`` line the proxy logged, in order, de-duplicated."""
        seen: dict[str, None] = {}
        for m in _DENY.finditer(self.read_log()):
            seen[m.group(1)] = None
        return list(seen)

    def close(self) -> None:
        """Tear down; never raises (the log tail is kept in :attr:`log`)."""
        if self._proxy_started:
            self.read_log()
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                self._docker("rm", "-f", self.proxy_name, timeout=60)
            self._proxy_started = False
        if self._network_created:
            for _ in range(3):
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    if self._docker("network", "rm", self.network, timeout=60).returncode == 0:
                        break
                time.sleep(1.0)
            self._network_created = False
        if self._script_written:
            self.script.unlink(missing_ok=True)
            self._script_written = False


__all__ = [
    "PROXY_ALIAS",
    "PROXY_PORT",
    "PROXY_SCRIPT_INSIDE",
    "PROXY_START_TIMEOUT_S",
    "DockerCall",
    "EgressSidecar",
]
