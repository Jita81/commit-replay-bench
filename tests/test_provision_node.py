"""Node: ``node_modules`` from a trusted lockfile, scripts off, sealed per lockfile (D5).

Without a daemon: the fetch plan is ``npm ci --ignore-scripts`` over ``package.json`` and the
lock only, with no user or global npmrc; a rebuild is planned only for a package the
repository named, and runs with no network. With a daemon: an npm cache pre-populated from
fixture tarballs (``npm cache add`` inside the pinned Node image, no network) serves an
air-gapped ``npm ci --offline`` into two sealed sets (the parent's lock and the gold's), and
the shipped Node sandbox image runs each tree's tests with ``--network=none`` against the set
its own lock selects.

Navigation
----------
What it is:   The suite for the Node recipe (``crb.provision.node``) and the Node runners' binding.
What it does: Pins the plans' argv and environment; proves against a daemon that the parent's
              and the gold's lockfiles each seal their own ``node_modules``, that each tree
              selects its own set and passes offline under ``node --test``, and that the
              runner's ``npm ls --all --offline`` probe reads the set whole.
How:          ``pkgmirror.build_npm_tarballs`` → ``npm cache add`` in a network-less container →
              ``noderepo_deps.build`` → ``SealedProvider.resolve`` (file:// cache) →
              ``NodeTestRunner`` bound to the selected set on the shipped ``crb-sandbox-node`` image.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/node.py (under test), src/crb/core/runners/node_runners.py (the
              binding), tests/fixtures/pkgmirror.py (the tarballs), tests/fixtures/langs/noderepo_deps.py
              (the repository)
Tested by:    tests/test_provision_node.py
Touch when:   the Node recipe's plans or binding change.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.execution import DockerExecutor, DockerSettings
from crb.core.git import GitRepo
from crb.core.provision import LockInputs
from crb.core.runners import get_runner
from crb.core.workspace import Workspace
from crb.provision import SealedProvider
from crb.provision import node as node_recipe
from crb.provision.config import DEFAULT_NODE_IMAGE, ProvisionConfig
from crb.provision.store import remove_tree

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

noderepo_deps = langs.fixture_module("noderepo_deps")
pkgmirror = importlib.import_module("fixtures.pkgmirror")


def test_npm_fetch_is_ci_with_scripts_off_over_the_lock_only(tmp_path: Path) -> None:
    root, feat = noderepo_deps.build(tmp_path)
    repo = GitRepo(root)
    inputs = LockInputs.from_git(repo, feat, noderepo_deps.config())
    plan = node_recipe.fetch_plan(
        inputs, key="dep_" + "0" * 64, config=ProvisionConfig(), image="node@sha256:x"
    )
    assert set(plan.inputs) == {"package.json", "package-lock.json"}
    script = plan.argv[2]
    assert "npm ci --ignore-scripts --no-audit --no-fund --prefix /out/app" in script
    assert ".npmrc" not in script and "--offline" not in script
    assert plan.env["npm_config_userconfig"] == "/dev/null"
    assert plan.env["npm_config_globalconfig"] == "/tmp/.crb-no-globalrc"
    assert plan.env["npm_config_registry"] == "https://registry.npmjs.org"
    assert plan.registry_hosts == ("registry.npmjs.org",)
    assert node_recipe.rebuild_plan(inputs, key="k", image="i") is None
    mirror = node_recipe.fetch_plan(
        inputs,
        key="dep_" + "0" * 64,
        config=ProvisionConfig(npm_registry="file:///srv/npm"),
        image="i",
    )
    assert "--offline" in mirror.argv[2] and mirror.registry_hosts == () and not mirror.networked


# ---------------------------------------------------------------------------


@pytest.fixture
def scratch() -> Iterator[Path]:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.require_docker_image(DEFAULT_NODE_IMAGE, "the pinned node fetch image")
    root = langs.CACHE_DIR / "provision" / f"node-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    remove_tree(root)


def _npm_cache(scratch: Path) -> Path:
    """An npm cache holding both fixture tarballs, filled inside the pinned Node image with
    no network (the air-gapped mirror shape)."""
    tarballs = scratch / "tarballs"
    pkgmirror.build_npm_tarballs(tarballs)
    cache = scratch / "npm-cache"
    cache.mkdir()
    adds = " && ".join(
        f"npm cache add /tarballs/{pkgmirror.tarball_name(v)} --cache /cache"
        for v in pkgmirror.VERSIONS
    )
    r = subprocess.run(
        [
            shutil.which("docker") or "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            "HOME=/tmp",
            "--mount",
            f"type=bind,src={tarballs},dst=/tarballs,readonly",
            "--mount",
            f"type=bind,src={cache},dst=/cache",
            DEFAULT_NODE_IMAGE,
            "sh",
            "-c",
            adds,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return cache


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.sandbox_images
def test_node_parent_and_gold_each_get_their_sealed_modules_and_pass_offline(scratch: Path) -> None:
    image = langs.ensure_shipped_sandbox_image("node")
    cache = _npm_cache(scratch)
    root, feat = noderepo_deps.build(scratch / "repo")
    repo = GitRepo(root)
    cfg = noderepo_deps.config()
    provider = SealedProvider(
        ProvisionConfig(
            enabled=True, env="dev", store=scratch / "deps", npm_registry=f"file://{cache}"
        )
    )
    deps = provider.resolve(repo, cfg, gold=feat)
    assert deps.parent.key != deps.gold.key and deps.builder.key == deps.parent.key
    assert deps.parent.manifest == ("cfxdep@1.0.0",) and deps.gold.manifest == ("cfxdep@1.1.0",)
    gold_set = provider.store.verify(deps.gold.key)
    assert (gold_set.path / "app" / "node_modules" / "cfxdep" / "index.js").is_file()

    executor = DockerExecutor(DockerSettings(image=image))
    runner = get_runner(cfg)
    cand = langs.feat_candidate(repo, cfg, feat)
    for role in ("parent", "gold"):
        if role == "gold":
            ws = langs.trial_worktree(
                repo,
                cand,
                scratch / "t-gold",
                cfg,
                sources=("package.json", "package-lock.json", noderepo_deps.SRC_BYE),
            )
            scope: tuple[str, ...] = (noderepo_deps.TEST_BYE,)
        else:
            ws = Workspace.create(repo, feat, scratch / "t-parent", config=cfg)
            scope = ("__tests__/core.test.js",)
        try:
            binding = deps.binding_for(ws.root)
            assert binding.role == role
            with runner.deps_bound(binding):
                probe = runner.probe_environment(executor, ws.root)
                assert probe is not None and probe.ok, probe.combined if probe else ""
                run = runner.run(executor, ws.root, scope)
            assert run.green, (role, run.tail)
        finally:
            ws.remove()
