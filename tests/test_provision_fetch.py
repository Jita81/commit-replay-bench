"""The fetch container: outside the test container, through the allowlisting proxy only (D3).

The argv tests are pure and pin every token. The daemon tests run a real fetch container:
an air-gapped mirror with ``--network=none`` and no sidecar, an oversized fetch killed by
the watchdog, and a fetch whose proxy denies a host — named in the refusal. None of them
needs the internet: the proxy refuses the denied host before any connection is made.

Navigation
----------
What it is:   The suite for ``crb.provision.fetch`` (and the extracted ``EgressSidecar`` it runs
              behind).
What it does: Pins that the fetch argv has only the internal network or none, is read-only with
              no capabilities, runs as the worker and never root, mounts ``/in`` read-only and
              ``/out`` and nothing else (no worktree, no ``/src``, no ``CRB_HOME``, no
              secret-named variable); that an air-gapped mirror needs no network and no
              sidecar; that an oversized fetch is killed and refused ``PROVISION_TOO_LARGE``;
              and that a denied host is named in ``PROVISION_FETCH_FAILED``.
How:          ``fetch_argv`` on a fixed plan; ``run_fetch`` against the pinned python image with a
              stage under ``tests/.cache`` (bind-mountable under colima).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/fetch.py (under test), src/crb/builders/sidecar.py (the proxy),
              src/crb/provision/store.py (the stage), tests/conftest_langs.py (the daemon probe)
Tested by:    tests/test_provision_fetch.py
Touch when:   a flag on the fetch's ``docker run`` changes (a security decision: SECURITY §3.1.1).
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.deps import ProvisionRefused
from crb.core.execution import SandboxUnavailable
from crb.provision import fetch as fetch_mod
from crb.provision.config import DEFAULT_PYTHON_IMAGE, ProvisionConfig
from crb.provision.fetch import FetchPlan, fetch_argv, run_fetch
from crb.provision.store import BundleStore

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

KEY = "dep_" + "c" * 64


def _plan(**kw: object) -> FetchPlan:
    base: dict[str, object] = {
        "recipe": "go.modcache.v1",
        "lang": "go",
        "key": KEY,
        "image": "golang:1.26.8-bookworm@sha256:" + "a" * 64,
        "argv": ("sh", "-c", "cd /in/gold && go mod download -json"),
        "env": {"GOPROXY": "https://proxy.golang.org", "GOVCS": "*:off"},
        "registry_hosts": ("proxy.golang.org", "sum.golang.org"),
        "inputs": {"gold/go.mod": b"module x\n"},
    }
    base.update(kw)
    return FetchPlan(**base)  # type: ignore[arg-type]


def test_fetch_argv_is_internal_network_proxy_only_no_worktree_no_secret(tmp_path: Path) -> None:
    stage = tmp_path / "deps" / ".staging" / "s1"
    argv = fetch_argv(
        _plan(),
        network="crb-f-1",
        stage=stage,
        image="golang:1.26.8-bookworm@sha256:" + "a" * 64,
        user="501:20",
        name="crb-fetch-1",
        proxy_url="http://proxy:3128",
    )
    assert argv == [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        "crb-fetch-1",
        "--network=crb-f-1",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "501:20",
        "--memory=2g",
        "--cpus=2",
        "--pids-limit=256",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=1g",
        "--mount",
        f"type=bind,src={stage / 'in'},dst=/in,readonly",
        "--mount",
        f"type=bind,src={stage / 'out'},dst=/out",
        "--env",
        "HOME=/tmp",
        "--env",
        "HTTPS_PROXY=http://proxy:3128",
        "--env",
        "GOPROXY=https://proxy.golang.org",
        "--env",
        "GOVCS=*:off",
        "golang:1.26.8-bookworm@sha256:" + "a" * 64,
        "sh",
        "-c",
        "cd /in/gold && go mod download -json",
    ]
    joined = " ".join(argv)
    for forbidden in ("/work", "/src", "CRB_HOME", "docker.sock", "--privileged", "bridge"):
        assert forbidden not in joined, forbidden
    envs = [argv[i + 1].split("=", 1)[0] for i, a in enumerate(argv) if a == "--env"]
    assert envs == ["HOME", "HTTPS_PROXY", "GOPROXY", "GOVCS"]
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert [m.split("dst=")[1] for m in mounts] == ["/in,readonly", "/out"]
    # a recipe can never carry a secret-looking variable into a fetch
    with pytest.raises(ValueError, match="secret-like"):
        _plan(env={"NPM_TOKEN": "x"})
    with pytest.raises(ValueError, match="secret-like"):
        _plan(env={"GOAUTH": "x"})


def test_fetch_user_is_the_worker_and_never_root(tmp_path: Path) -> None:
    for root in ("0:0", "root", "0"):
        with pytest.raises(SandboxUnavailable, match="root"):
            fetch_argv(_plan(), network="none", stage=tmp_path, image="i@sha256:x", user=root)
    argv = fetch_argv(
        _plan(), network="none", stage=tmp_path, image="i", user=f"{os.getuid()}:{os.getgid()}"
    )
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "HTTPS_PROXY" not in " ".join(argv)  # no proxy without the sidecar


# ---------------------------------------------------------------------------
# Against a daemon
# ---------------------------------------------------------------------------


@pytest.fixture
def scratch() -> Iterator[Path]:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.require_docker_image(DEFAULT_PYTHON_IMAGE, "the pinned python fetch image")
    root = langs.CACHE_DIR / "provision" / f"fetch-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    from crb.provision.store import remove_tree

    remove_tree(root)


def _py_plan(script: str, **kw: object) -> FetchPlan:
    return _plan(
        recipe="test.v1",
        lang="python",
        image=DEFAULT_PYTHON_IMAGE,
        argv=("python", "-c", script),
        env={},
        **kw,
    )


@pytest.mark.docker
@pytest.mark.sandbox_images
def test_an_airgapped_mirror_runs_with_no_network_and_no_sidecar(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mirror = scratch / "mirror"
    mirror.mkdir()
    (mirror / "pkg.txt").write_text("from the mirror\n", encoding="utf-8")

    def no_sidecar(*a: object, **k: object) -> None:
        raise AssertionError("an air-gapped fetch must not start a sidecar")

    monkeypatch.setattr(fetch_mod, "EgressSidecar", no_sidecar)
    store = BundleStore(scratch / "deps")
    stage = store.stage()
    script = (
        "import socket, shutil\n"
        "try:\n socket.create_connection(('1.1.1.1', 53), timeout=3); net = 'up'\n"
        "except OSError:\n net = 'none'\n"
        "open('/out/net.txt', 'w').write(net)\n"
        "shutil.copy('/mirror/pkg.txt', '/out/pkg.txt')\n"
        "open('/out/in.txt', 'w').write(open('/in/gold/go.mod').read())\n"
    )
    plan = _py_plan(script, mirror=mirror, registry_hosts=())
    res = run_fetch(plan, stage, config=ProvisionConfig(enabled=True, env="dev"))
    assert (stage / "out" / "net.txt").read_text() == "none"
    assert (stage / "out" / "pkg.txt").read_text() == "from the mirror\n"
    assert (stage / "out" / "in.txt").read_text() == "module x\n"
    assert res.denied == ()
    # the mirror and /in are read-only inside
    stage2 = store.stage()
    bad = _py_plan("open('/mirror/x', 'w')", mirror=mirror, registry_hosts=())
    with pytest.raises(ProvisionRefused) as ei:
        run_fetch(bad, stage2, config=ProvisionConfig(enabled=True, env="dev"))
    assert ei.value.code == "PROVISION_FETCH_FAILED" and "Read-only" in ei.value.message


@pytest.mark.docker
@pytest.mark.sandbox_images
def test_an_oversized_fetch_is_killed_and_refused(scratch: Path) -> None:
    store = BundleStore(scratch / "deps")
    stage = store.stage()
    script = (
        "import time\n"
        "f = open('/out/big.bin', 'wb')\n"
        "for _ in range(600):\n f.write(b'x' * (1 << 20)); f.flush(); time.sleep(0.05)\n"
    )
    events: list[tuple[str, dict]] = []
    cfg = ProvisionConfig(enabled=True, env="dev", max_bundle_mb=2, fetch_timeout_s=120)
    with pytest.raises(ProvisionRefused) as ei:
        run_fetch(
            _py_plan(script, offline=True),
            stage,
            config=cfg,
            on_event=lambda a, p: events.append((a, dict(p))),
        )
    assert ei.value.code == "PROVISION_TOO_LARGE" and "2 MB" in ei.value.message
    assert (stage / "out" / "big.bin").stat().st_size < 64 * (1 << 20), "the watchdog was late"
    assert [a for a, _ in events] == ["provision.fetch", "provision.refused"]
    assert events[1][1]["code"] == "PROVISION_TOO_LARGE"


@pytest.mark.docker
@pytest.mark.sandbox_images
def test_a_denied_host_is_named_in_the_refusal(scratch: Path) -> None:
    store = BundleStore(scratch / "deps")
    stage = store.stage()
    script = (
        "import os, urllib.request\n"
        "urllib.request.urlopen('https://denied.invalid/simple/', timeout=10)\n"
    )
    cfg = ProvisionConfig(
        enabled=True, env="dev", proxy_image=DEFAULT_PYTHON_IMAGE, fetch_timeout_s=120
    )
    plan = _py_plan(script, registry_hosts=("registry.allowed.invalid",))
    with pytest.raises(ProvisionRefused) as ei:
        run_fetch(plan, stage, config=cfg)
    assert ei.value.code == "PROVISION_FETCH_FAILED"
    assert "the proxy denied denied.invalid:443" in ei.value.message
    # the sidecar and its network are gone
    docker = shutil.which("docker") or "docker"
    import subprocess

    left = subprocess.run(
        [docker, "ps", "-a", "-q", "--filter", "name=crb-fproxy-"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert left == ""
