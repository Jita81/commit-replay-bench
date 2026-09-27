"""The fetch container: dependencies are fetched OUTSIDE the test container (ADR-0019).

A fetch is one ``docker run`` of a digest-pinned toolchain image. Its only network is an
``--internal`` bridge whose only way out is the CONNECT-only allowlisting proxy
(:class:`~crb.builders.sidecar.EgressSidecar`) to the configured registry hosts — or none at
all for a ``file://`` mirror (the air-gapped mode) and for a step that installs or builds
what was fetched. It sees exactly two things: ``/in`` (the lockfiles read from git objects,
read-only) and ``/out`` (the stage the store will seal). It never sees a worktree, the
repository's source, a secret or ``CRB_HOME``, and nothing from a ``RepoConfig``, a run
request or a worktree reaches its argv, its environment or its allowlist — the plan's
argv and environment are the recipe's, fixed.

The wall clock is ``fetch_timeout_s``; a watchdog measures the stage while the fetch runs
and kills it past ``max_bundle_mb`` (``PROVISION_TOO_LARGE``); a non-zero exit is
``PROVISION_FETCH_FAILED`` naming every host the proxy denied.

Navigation
----------
What it is:   The dependency fetch — the hardened ``docker run`` argv and the runner that
              executes it behind the egress sidecar, with the size and time limits.
What it does: Builds the exact argv (internal network or none, read-only, no capabilities,
              the worker's non-root uid, ``/in`` read-only and ``/out``, the proxy URL, the
              recipe's fixed environment and nothing else); runs it with the sidecar for the
              registry hosts; kills an oversized or overdue fetch; names denied hosts; emits
              ``provision.fetch`` and ``provision.refused``.
How:          ``FetchPlan`` (recipe, image, argv, env, hosts, inputs, mirror) → ``fetch_argv``
              → ``run_fetch``: stage the inputs → start the sidecar (unless offline) →
              ``Popen`` → poll size and clock → ``docker kill`` on a breach → refusal or the
              filled stage.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/builders/sidecar.py (the internal network and the proxy),
              src/crb/provision/store.py (the stage it fills), src/crb/provision/go.py (a recipe
              that builds plans; src/crb/provision/python.py and src/crb/provision/node.py are
              the others), src/crb/core/deps.py (the refusals)
Tested by:    tests/test_provision_fetch.py, tests/test_provision_go.py
Touch when:   never for a new repository; a flag on the fetch's ``docker run`` is a security
              decision (docs/SECURITY.md §3.1.1 and ADR-0005's amendment change with it).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.builders.sidecar import EgressSidecar
from crb.core.deps import ProvisionRefused, is_secret_like, worker_user
from crb.core.execution import SandboxUnavailable
from crb.core.redact import redact_and_cap
from crb.provision.config import ProvisionConfig

#: Where a CA bundle for a TLS-intercepting mirror is mounted, and the variables that
#: point each toolchain at it.
CA_INSIDE = "/etc/crb/ca.pem"
_CA_ENV: tuple[str, ...] = ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "PIP_CERT")
MIRROR_INSIDE = "/mirror"

EventFn = Callable[[str, Mapping[str, Any]], None]

_POLL_S = 0.5


@dataclass(frozen=True)
class FetchPlan:
    """One container's work. ``argv`` and ``env`` are the recipe's, fixed; ``inputs`` are
    written under ``<stage>/in`` (the only thing from the repository, and it came from git
    objects); ``extra_ro`` mounts stage-relative directories read-only (an install step
    reading the wheels a fetch wrote); ``out_sub`` is the stage-relative ``/out``."""

    recipe: str
    lang: str
    key: str
    image: str
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    registry_hosts: tuple[str, ...] = ()
    inputs: Mapping[str, bytes] = field(default_factory=dict)
    mirror: Path | None = None
    offline: bool = False
    extra_ro: Mapping[str, str] = field(default_factory=dict)
    out_sub: str = "out"
    step: str = "fetch"

    def __post_init__(self) -> None:
        bad = sorted(k for k in self.env if is_secret_like(k))
        if bad:
            raise ValueError(f"a fetch never carries a secret-like variable: {bad}")

    @property
    def networked(self) -> bool:
        return not self.offline and self.mirror is None


@dataclass(frozen=True)
class FetchResult:
    stage: Path
    stdout: str
    stderr: str
    duration_s: float
    denied: tuple[str, ...] = ()


def fetch_argv(
    plan: FetchPlan,
    *,
    network: str,
    stage: Path,
    image: str,
    user: str,
    docker: str = "docker",
    name: str = "",
    ca_bundle: str = "",
    proxy_url: str = "",
) -> list[str]:
    """The fetch's exact ``docker run`` argv (tests assert on every token)."""
    uid = user.split(":", 1)[0].strip().lower()
    if uid in {"", "0", "root"}:
        raise SandboxUnavailable(f"refusing to run a dependency fetch as root (user={user!r})")
    stage = Path(stage)
    argv = [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name or f"crb-fetch-{uuid.uuid4().hex[:12]}",
        f"--network={network}",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        user,
        "--memory=2g",
        "--cpus=2",
        "--pids-limit=256",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=1g",
        "--mount",
        f"type=bind,src={stage / 'in'},dst=/in,readonly",
        "--mount",
        f"type=bind,src={stage / plan.out_sub},dst=/out",
    ]
    for src, inside in sorted(plan.extra_ro.items()):
        argv += ["--mount", f"type=bind,src={stage / src},dst={inside},readonly"]
    if plan.mirror is not None:
        argv += ["--mount", f"type=bind,src={plan.mirror},dst={MIRROR_INSIDE},readonly"]
    if ca_bundle:
        argv += ["--mount", f"type=bind,src={ca_bundle},dst={CA_INSIDE},readonly"]
        for var in _CA_ENV:
            argv += ["--env", f"{var}={CA_INSIDE}"]
    argv += ["--env", "HOME=/tmp"]
    if proxy_url:
        argv += ["--env", f"HTTPS_PROXY={proxy_url}"]
    for k, v in sorted(plan.env.items()):
        argv += ["--env", f"{k}={v}"]
    argv += [image, *plan.argv]
    return argv


def _dir_bytes(root: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for n in filenames:
            with contextlib.suppress(OSError):
                total += (Path(dirpath) / n).lstat().st_size
    return total


def _client_env() -> dict[str, str]:
    """The docker CLIENT's environment: what it needs to find the daemon, nothing else."""
    keep = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
    return {k: v for k, v in os.environ.items() if k in keep or k.startswith("DOCKER_")}


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def run_fetch(
    plan: FetchPlan,
    stage: Path,
    *,
    config: ProvisionConfig,
    docker: str = "",
    user: str = "",
    on_event: EventFn | None = None,
) -> FetchResult:
    """Run ``plan`` into ``stage`` (``<stage>/in`` written from ``plan.inputs`` first).

    Raises :class:`~crb.core.deps.ProvisionRefused` (``PROVISION_TOO_LARGE``,
    ``PROVISION_FETCH_FAILED``) or :class:`~crb.core.execution.SandboxUnavailable` (no
    daemon, the image absent — a deployment fault). The caller seals or discards."""
    docker = docker or config.docker_binary or shutil.which("docker") or ""
    if not docker:
        raise SandboxUnavailable("dependency fetch needs the docker binary on PATH")
    user = user or worker_user()
    stage = Path(stage)
    for rel, data in plan.inputs.items():
        p = stage / "in" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (stage / plan.out_sub).mkdir(parents=True, exist_ok=True)
    fid = uuid.uuid4().hex[:12]
    name = f"crb-fetch-{fid}"

    def call(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [docker, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_client_env(),
        )

    sidecar: EgressSidecar | None = None
    network = "none"
    proxy_url = ""
    _emit(
        on_event,
        "provision.fetch",
        lang=plan.lang,
        key=plan.key,
        recipe=plan.recipe,
        step=plan.step,
        image=plan.image,
        hosts=list(plan.registry_hosts),
        mode="proxy" if plan.networked else ("mirror" if plan.mirror else "offline"),
    )
    try:
        if plan.networked:
            if not plan.registry_hosts:
                raise ProvisionRefused("PROVISION_FETCH_FAILED", "no registry host to fetch from")
            if not config.proxy_image:
                raise SandboxUnavailable(
                    "dependency fetch needs CRB_PROVISION__PROXY_IMAGE (an image with python3)"
                )
            sidecar = EgressSidecar(
                call,
                network=f"crb-f-{fid}",
                proxy_name=f"crb-fproxy-{fid}",
                allow_hosts=plan.registry_hosts,
                egress_network=config.egress_network,
                proxy_image=config.proxy_image,
                user=user,
                script=stage / "egress_proxy.py",
            )
            sidecar.start(what="fetch")
            network = sidecar.network
            proxy_url = sidecar.url
        argv = fetch_argv(
            plan,
            network=network,
            stage=stage,
            image=plan.image,
            user=user,
            docker=docker,
            name=name,
            ca_bundle=config.ca_bundle,
            proxy_url=proxy_url,
        )
        return _execute(
            plan,
            argv,
            stage=stage,
            name=name,
            docker=docker,
            config=config,
            sidecar=sidecar,
            on_event=on_event,
        )
    finally:
        if sidecar is not None:
            sidecar.close()


def _execute(
    plan: FetchPlan,
    argv: list[str],
    *,
    stage: Path,
    name: str,
    docker: str,
    config: ProvisionConfig,
    sidecar: EgressSidecar | None,
    on_event: EventFn | None,
) -> FetchResult:
    started = time.monotonic()
    cap = config.max_bundle_mb * (1 << 20)
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=_client_env(),
    )
    box: dict[str, str] = {}

    def drain() -> None:
        o, e = proc.communicate()
        box["out"], box["err"] = o or "", e or ""

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    breach = ""
    deadline = started + config.fetch_timeout_s
    while t.is_alive():
        t.join(_POLL_S)
        if not t.is_alive():
            break
        if _dir_bytes(stage / plan.out_sub) > cap:
            breach = "too_large"
        elif time.monotonic() >= deadline:
            breach = "timeout"
        else:
            continue
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([docker, "kill", name], capture_output=True, timeout=30, check=False)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(OSError):
                proc.kill()
        t.join()
        break
    out, err = box.get("out", ""), box.get("err", "")
    duration = time.monotonic() - started
    denied = tuple(sidecar.denied_hosts()) if sidecar is not None else ()
    tail = redact_and_cap((out + "\n" + err).strip(), max_chars=1200)

    def refuse(code: str, message: str) -> ProvisionRefused:
        _emit(
            on_event, "provision.refused", lang=plan.lang, key=plan.key, code=code, message=message
        )
        return ProvisionRefused(code, message)

    if breach == "too_large":
        raise refuse(
            "PROVISION_TOO_LARGE",
            f"{plan.step} for {plan.key} exceeded {config.max_bundle_mb} MB and was killed",
        )
    if breach == "timeout":
        raise refuse(
            "PROVISION_FETCH_FAILED",
            f"{plan.step} for {plan.key} timed out after {config.fetch_timeout_s}s",
        )
    if proc.returncode == 125:
        raise SandboxUnavailable(f"docker could not launch the {plan.step} container: {err[-400:]}")
    if proc.returncode != 0:
        named = f"; the proxy denied {', '.join(denied)}" if denied else ""
        raise refuse(
            "PROVISION_FETCH_FAILED",
            f"{plan.step} for {plan.key} exited {proc.returncode}{named}: {tail[-600:]}",
        )
    return FetchResult(stage, out, err, duration, denied)


__all__ = ["CA_INSIDE", "MIRROR_INSIDE", "FetchPlan", "FetchResult", "fetch_argv", "run_fetch"]
