"""The Node recipe, ``node.modules.v1``: ``node_modules`` from a trusted ``package-lock.json``.

Fetch: the pinned Node image, behind the allowlisting proxy, runs ``npm ci --ignore-scripts``
over ``package.json`` and the lockfile only — ``.npmrc`` is never read
(``npm_config_userconfig=/dev/null``, the global config an absent file), no install
script runs, and every tarball is checked against the lock's ``integrity`` by npm itself.
:mod:`crb.core.provision` has already refused a ``resolved`` host that is not the configured
registry, a ``file:`` / ``git`` / ``link`` entry, an entry without ``integrity`` and an
install script the repository did not name in ``runner_opts.deps_build_scripts``. Those it
named are rebuilt in a second container with ``--network=none``: ``npm rebuild <pkgs>``.

The air-gapped mode is a pre-populated npm cache (``CRB_PROVISION__NPM_REGISTRY=file://<cache>``),
mounted read-only and copied to ``/tmp`` for ``npm ci --offline``.

At test time ``<set>/app/node_modules`` is mounted read-only at ``/work/node_modules`` with
``NODE_PATH`` and ``PATH`` pointing at it; no dependency era is installed.

Navigation
----------
What it is:   The Node dependency recipe — fetch and rebuild plans and the resolver the sealed
              provider calls for a ``node`` / ``vitest`` / ``jest`` / ``mocha`` repository.
What it does: Installs exactly the committed lock with scripts off (npm checks every
              ``integrity``), rebuilds only the packages the repository named, with no network,
              seals one set per lockfile and binds it read-only at ``/work/node_modules``.
How:          ``LockInputs`` (package.json + lock from git objects) → ``fetch_plan`` →
              ``run_fetch`` → ``rebuild_plan`` (offline, when named) → seal → ``DepsBinding``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/__init__.py (``SealedProvider.per_lock`` calls ``resolve``),
              src/crb/provision/fetch.py (runs both plans), src/crb/core/provision.py (the
              lock's refusals), src/crb/core/runners/node_runners.py (applies the binding)
Tested by:    tests/test_provision_node.py
Touch when:   a Node repository needs an install script — name the package in
              ``runner_opts.deps_build_scripts``; never to let a fetch run scripts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.core.deps import DepsBinding
from crb.core.provision import LANG_NODE, RECIPE_NODE, LockInputs, describe_inputs
from crb.provision import RECIPES, SealedProvider
from crb.provision.config import ProvisionConfig
from crb.provision.fetch import MIRROR_INSIDE, FetchPlan
from crb.provision.store import Sealed

if TYPE_CHECKING:  # pragma: no cover
    from crb.core.deps import TaskDeps
    from crb.core.spec import RepoConfig

INSIDE = "/work/node_modules"
SUB = "app/node_modules"
#: The sandbox image's own PATH (deploy/sandbox/Dockerfile.node's base), after the set's bins.
IMAGE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

_NPM_ENV = {
    "npm_config_userconfig": "/dev/null",
    # an absent file: npm refuses one path loaded as both user and global config
    "npm_config_globalconfig": "/tmp/.crb-no-globalrc",
    "npm_config_cache": "/tmp/npm",
    "npm_config_update_notifier": "false",
    "npm_config_fund": "false",
    "npm_config_audit": "false",
    "NODE_ENV": "development",
}


def fetch_plan(inputs: LockInputs, *, key: str, config: ProvisionConfig, image: str) -> FetchPlan:
    mirror = config.mirror_for(LANG_NODE)
    files = {f.path: f.data for f in inputs.files}
    names = " ".join(sorted(files))
    offline = ""
    if mirror is not None:
        offline = f"cp -R {MIRROR_INSIDE}/. /tmp/npm && "
    script = (
        f"mkdir -p /out/app && cd /in && cp {names} /out/app/ && {offline}"
        "npm ci --ignore-scripts --no-audit --no-fund "
        f"{'--offline ' if mirror is not None else ''}--prefix /out/app"
    )
    env = dict(_NPM_ENV)
    env["npm_config_registry"] = (
        "https://registry.npmjs.org/" if mirror is not None else config.npm_registry
    )
    return FetchPlan(
        recipe=RECIPE_NODE,
        lang=LANG_NODE,
        key=key,
        image=image,
        argv=("sh", "-c", script),
        env=env,
        registry_hosts=config.hosts_for(LANG_NODE),
        inputs=files,
        mirror=mirror,
    )


def rebuild_plan(inputs: LockInputs, *, key: str, image: str) -> FetchPlan | None:
    """``npm rebuild <named>`` with no network, or ``None`` when nothing was named."""
    named = sorted({p.name for p in inputs.node_pkgs if p.install_script})
    if not named:
        return None
    return FetchPlan(
        recipe=RECIPE_NODE,
        lang=LANG_NODE,
        key=key,
        image=image,
        argv=("sh", "-c", "cd /out/app && npm rebuild " + " ".join(named)),
        env=dict(_NPM_ENV),
        offline=True,
        step="rebuild",
    )


def resolve(
    provider: SealedProvider, config: RepoConfig, pin: LockInputs, gin: LockInputs
) -> TaskDeps:
    cfg = provider.config
    image = cfg.node_image

    def build_for(inputs: LockInputs, key: str, image_id: str) -> Callable[[Path], dict[str, Any]]:
        def build(stage: Path) -> dict[str, Any]:
            plan = fetch_plan(inputs, key=key, config=cfg, image=image)
            res = provider.fetch(plan, stage)
            rebuild = rebuild_plan(inputs, key=key, image=image)
            if rebuild is not None:
                provider.fetch(rebuild, stage)
            return {
                "recipe": RECIPE_NODE,
                "inputs": [describe_inputs(inputs)],
                "fetch_image": image,
                "fetch_image_id": image_id,
                "registry_hosts": list(plan.registry_hosts),
                "mirror": str(plan.mirror or ""),
                "egress_denies": list(res.denied),
                "packages": {f"{p.name}@{p.version}": p.integrity for p in inputs.node_pkgs},
                "rebuilt": sorted({p.name for p in inputs.node_pkgs if p.install_script}),
                "hashes": "committed",
            }

        return build

    def bind(role: str, sealed: Sealed) -> DepsBinding:
        mount = provider.store.mount(sealed.key, LANG_NODE, SUB, INSIDE)
        host = sealed.path / SUB
        return DepsBinding(
            role=role,
            lang=LANG_NODE,
            scheme=RECIPE_NODE,
            key=sealed.key,
            digest=sealed.digest,
            mounts=(mount,),
            env={"NODE_PATH": INSIDE, "PATH": f"{INSIDE}/.bin:{IMAGE_PATH}"},
            local_env={"NODE_PATH": str(host)},
            manifest=tuple(sorted(dict(sealed.manifest.get("packages") or {}))),
        )

    return provider.per_lock(
        lang=LANG_NODE,
        recipe=RECIPE_NODE,
        image=image,
        pin=pin,
        gin=gin,
        build_for=build_for,
        bind=bind,
    )


RECIPES[LANG_NODE] = resolve

__all__ = ["INSIDE", "SUB", "fetch_plan", "rebuild_plan", "resolve"]
