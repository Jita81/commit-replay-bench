"""The ``provision`` probe for ``crb doctor`` and the worker's ``/health`` (ADR-0019).

One line that says whether dependency provisioning can work on this host before a run
depends on it: **skipped** when provisioning is off (``CRB_PROVISION__ENABLED``); otherwise
**down** with the refusal's code and fix when production would refuse the configuration, the
docker daemon cannot see the store, a fetch image is not in the daemon's store (the worker
never pulls), or the egress network does not exist — and **ok** naming the store and the
registries when all four hold. It never fetches anything and never contacts a registry.

Navigation
----------
What it is:   The provisioning readiness probe shared by ``crb doctor`` and ``/health``.
What it does: Reads the worker-side configuration and answers skipped / ok / down with a
              sentence that names the fix; proves the daemon can see the store and that the
              fetch images and the egress network are present. Never fetches.
How:          ``ProvisionConfig`` → ``production_refusal`` → ``BundleStore.visible_to_daemon``
              → ``docker image inspect`` per fetch image → ``docker network inspect``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/config.py (what it checks), src/crb/provision/store.py
              (``visible_to_daemon``), src/crb/cli/commands/service.py (``crb doctor``'s line),
              src/crb/server/routes/system.py (the worker-side ``/health`` probe),
              src/crb/observability/probes.py (``ProbeResult``)
Tested by:    tests/test_cli_doctor.py, tests/test_server_system.py
Touch when:   a new precondition of provisioning becomes checkable from the host.
"""

from __future__ import annotations

import shutil
import subprocess

from crb.core.deps import ProvisionRefused
from crb.observability.probes import DOWN, OK, SKIPPED, ProbeResult
from crb.provision.config import ProvisionConfig
from crb.provision.store import BundleStore

NAME = "provision"


def _present(docker: str, *args: str) -> bool:
    try:
        r = subprocess.run([docker, *args], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def probe_provision(config: ProvisionConfig, *, docker: str = "") -> ProbeResult:
    """``skipped`` when off; ``down`` with the code and the fix when a precondition fails;
    ``ok`` otherwise. Never raises (``run_probe`` guards the unexpected)."""
    data: dict[str, object] = {"enabled": config.enabled}
    if not config.enabled:
        return ProbeResult(
            NAME,
            SKIPPED,
            "off (CRB_PROVISION__ENABLED): under docker a repository that declares "
            "dependencies is refused PROVISION_DISABLED before any spend",
            data,
        )
    refusal = config.production_refusal()
    if refusal is not None:
        return ProbeResult(NAME, DOWN, f"{refusal.code}: {refusal.message} — {refusal.fix}", data)
    docker = docker or config.docker_binary or shutil.which("docker") or ""
    if not docker:
        return ProbeResult(NAME, DOWN, "the docker binary is not on PATH", data)
    images = {"go": config.go_image, "python": config.python_image, "node": config.node_image}
    missing = [
        f"{lang}: {img}"
        for lang, img in images.items()
        if not _present(docker, "image", "inspect", img)
    ]
    data["fetch_images_missing"] = missing
    if missing:
        return ProbeResult(
            NAME,
            DOWN,
            "fetch image(s) not in the daemon's store (the worker never pulls; pre-pull them — "
            f"deploy/sandbox/README.md §2): {'; '.join(missing)}",
            data,
        )
    if config.proxy_image and not _present(docker, "image", "inspect", config.proxy_image):
        return ProbeResult(NAME, DOWN, f"proxy image {config.proxy_image} is not present", data)
    if not _present(docker, "network", "inspect", config.egress_network):
        return ProbeResult(
            NAME,
            DOWN,
            f"egress network {config.egress_network!r} does not exist "
            "(CRB_PROVISION__EGRESS_NETWORK)",
            data,
        )
    try:
        store = BundleStore(config.store)
        store.visible_to_daemon(docker, config.python_image)
    except ProvisionRefused as exc:
        return ProbeResult(NAME, DOWN, f"{exc.code}: {exc.message} — {exc.fix}", data)
    except OSError as exc:
        return ProbeResult(NAME, DOWN, f"the store {config.store} is not writable: {exc}", data)
    data["store"] = str(store.root)
    data["sets"] = len(store.sets())
    hosts = sorted({h for lang in ("go", "python", "node") for h in config.hosts_for(lang)})
    where = ", ".join(hosts) if hosts else "air-gapped mirrors"
    return ProbeResult(
        NAME, OK, f"on · store {store.root} visible to the daemon · fetches from {where}", data
    )


__all__ = ["NAME", "probe_provision"]
