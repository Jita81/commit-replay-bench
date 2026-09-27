"""The Python recipe, ``py.site.v1``: wheels from a pinned lock, installed with no network.

Two containers, both run by :func:`crb.provision.fetch.run_fetch`:

1. **fetch** — the pinned Python image, behind the allowlisting proxy (or with no network
   for a ``file://`` simple index): ``pip download --only-binary=:all: --no-deps
   [--require-hashes] --index-url <index> -r /in/lock.txt -d /out/wheels``. Wheels only:
   pip builds nothing and runs nothing a package ships. ``/in/lock.txt`` is written from
   the pins :mod:`crb.core.provision` parsed out of git objects — never the repository's
   own file, so an include, an option or an index line cannot reach pip.
   ``PIP_CONFIG_FILE=/dev/null``: no ``pip.conf`` is read.
2. **install** — the same image, ``--network=none``: ``pip install --no-index --find-links
   /wheels --only-binary=:all: --no-deps [--require-hashes] --target /out -r /in/lock.txt``.

Hashes are verified where the lock commits them (``--require-hashes``); where it does not,
every fetched wheel's sha256 is recorded in the manifest (``hashes: recorded``). A package
published only as a source distribution has no wheel to fetch:
``PROVISION_BUILD_REQUIRED``. The set is mounted read-only at ``/deps/site``; the pytest
runner puts it on ``PYTHONPATH`` after the tree.

Navigation
----------
What it is:   The Python dependency recipe — the fetch and install plans, the wheel manifest and
              the resolver the sealed provider calls for a ``pytest`` repository.
What it does: Fetches wheels only for exactly the pinned ``name==version`` lines (hash-checked
              when committed), installs them with no network into a site directory, seals one
              set per lockfile, and binds it read-only at ``/deps/site``.
How:          ``LockInputs.py_pins`` → ``lock_text`` → ``fetch_plan`` → ``run_fetch`` →
              ``install_plan`` (offline) → drop the wheels → seal → ``DepsBinding`` with the
              mount, ``PYTHONNOUSERSITE`` and ``PATH``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/__init__.py (``SealedProvider.per_lock`` calls ``resolve``),
              src/crb/provision/fetch.py (runs both plans), src/crb/core/provision.py (the pins),
              src/crb/core/runners/pytest_runner.py (applies the binding)
Tested by:    tests/test_provision_python.py
Touch when:   a Python repository's lock is refused — commit a pinned requirements lock or name
              one in ``runner_opts.deps_lock``; never to allow a source build.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.core.deps import DepsBinding, ProvisionRefused
from crb.core.provision import LANG_PYTHON, RECIPE_PY, LockInputs, describe_inputs
from crb.provision import RECIPES, SealedProvider
from crb.provision.config import ProvisionConfig
from crb.provision.fetch import MIRROR_INSIDE, FetchPlan
from crb.provision.store import Sealed, remove_tree

if TYPE_CHECKING:  # pragma: no cover
    from crb.core.deps import TaskDeps
    from crb.core.spec import RepoConfig

INSIDE = "/deps/site"
SUB = "site"
#: The sandbox image's own PATH (deploy/sandbox/Dockerfile.python's base), after the set's
#: console scripts.
IMAGE_PATH = "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"

_PIP_ENV = {
    "PIP_CONFIG_FILE": "/dev/null",
    "PIP_NO_INPUT": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_CACHE_DIR": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def lock_text(inputs: LockInputs) -> bytes:
    """The one lock pip reads, written from the parsed pins (never the repository's file)."""
    lines = []
    for p in inputs.py_pins:
        line = f"{p.name}=={p.version}"
        if p.marker:
            line += f" {p.marker}"
        line += "".join(f" --hash={h}" for h in p.hashes)
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def fetch_plan(inputs: LockInputs, *, key: str, config: ProvisionConfig, image: str) -> FetchPlan:
    mirror = config.mirror_for(LANG_PYTHON)
    index = f"file://{MIRROR_INSIDE}" if mirror is not None else config.pypi_index
    argv = [
        "python",
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--no-deps",
        *(["--require-hashes"] if inputs.require_hashes else []),
        "--index-url",
        index,
        "-r",
        "/in/lock.txt",
        "-d",
        "/out/wheels",
    ]
    return FetchPlan(
        recipe=RECIPE_PY,
        lang=LANG_PYTHON,
        key=key,
        image=image,
        argv=tuple(argv),
        env=dict(_PIP_ENV),
        registry_hosts=config.hosts_for(LANG_PYTHON),
        inputs={"lock.txt": lock_text(inputs)},
        mirror=mirror,
    )


def install_plan(inputs: LockInputs, *, key: str, image: str) -> FetchPlan:
    """The offline install of the fetched wheels into ``/out`` (the stage's ``out/site``)."""
    argv = [
        "python",
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        "/wheels",
        "--only-binary=:all:",
        "--no-deps",
        *(["--require-hashes"] if inputs.require_hashes else []),
        "--target",
        "/out",
        "-r",
        "/in/lock.txt",
    ]
    return FetchPlan(
        recipe=RECIPE_PY,
        lang=LANG_PYTHON,
        key=key,
        image=image,
        argv=tuple(argv),
        env=dict(_PIP_ENV),
        offline=True,
        extra_ro={"out/wheels": "/wheels"},
        out_sub=f"out/{SUB}",
        step="install",
    )


def _dist(dist_info: str) -> tuple[str, str]:
    """``(normalised name, version)`` of a ``<name>-<version>.dist-info`` directory (pip
    escapes a ``-`` in either part as ``_``, so the last ``-`` splits them)."""
    name, _, version = dist_info[: -len(".dist-info")].rpartition("-")
    return re.sub(r"[-_.]+", "-", name).lower(), version.replace("_", "-").lower()


def installed_manifest(inputs: LockInputs, site: Path) -> tuple[dict[str, list[str]], list[str]]:
    """``(packages, marker_skipped)`` for a set pip installed into ``site``.

    pip ignores a pin whose environment marker excludes the fetch image's Python (a
    pip-compile backport line, ``tomli==… ; python_version < "3.11"``), at fetch and at
    install. A pin with a marker is ``marker_skipped`` — never a package the set must hold,
    since the environment probe requires every package at its version — when that exact
    ``name==version`` is not installed and either the name is not installed at all or it
    is installed at the version of another pin of the same name (a universal lock pins
    ``numpy`` twice under opposite markers; pip keeps one). Otherwise it stays, so a
    version no pin names is still the probe's to report. A pin with NO marker stays in
    ``packages`` whether or not it is there: a set that lost it is the probe's to report,
    never this function's to hide (CodeRabbit on PR #56, and the check on its answer)."""
    present = {_dist(d.name) for d in Path(site).glob("*.dist-info") if d.is_dir()}
    names = {name for name, _ in present}
    pinned = {(p.norm, p.version.lower()) for p in inputs.py_pins}
    packages: dict[str, list[str]] = {}
    skipped: list[str] = []
    for p in inputs.py_pins:
        pin = p.norm + "==" + p.version
        installed = (p.norm, p.version.lower()) in present
        sibling_won = any(n == p.norm and (n, v) in pinned for n, v in present)
        if p.marker and not installed and (p.norm not in names or sibling_won):
            skipped.append(pin)
        else:
            packages[pin] = list(p.hashes)
    return packages, sorted(skipped)


def _wheel_hashes(wheels: Path) -> dict[str, str]:
    return {
        p.name: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(wheels.glob("*.whl"))
    }


def resolve(
    provider: SealedProvider, config: RepoConfig, pin: LockInputs, gin: LockInputs
) -> TaskDeps:
    cfg = provider.config
    image = cfg.python_image

    def build_for(inputs: LockInputs, key: str, image_id: str) -> Callable[[Path], dict[str, Any]]:
        def build(stage: Path) -> dict[str, Any]:
            plan = fetch_plan(inputs, key=key, config=cfg, image=image)
            try:
                res = provider.fetch(plan, stage)
            except ProvisionRefused as exc:
                if (
                    exc.code == "PROVISION_FETCH_FAILED"
                    and "No matching distribution" in exc.message
                ):
                    raise ProvisionRefused(
                        "PROVISION_BUILD_REQUIRED",
                        "no wheel for a pinned package (published as a source distribution "
                        f"only, or missing from the index): {exc.message[-300:]}",
                    ) from exc
                raise
            wheels = _wheel_hashes(stage / "out" / "wheels")
            provider.fetch(install_plan(inputs, key=key, image=image), stage)
            remove_tree(stage / "out" / "wheels")
            packages, marker_skipped = installed_manifest(inputs, stage / "out" / SUB)
            return {
                "recipe": RECIPE_PY,
                "inputs": [describe_inputs(inputs)],
                "fetch_image": image,
                "fetch_image_id": image_id,
                "registry_hosts": list(plan.registry_hosts),
                "mirror": str(plan.mirror or ""),
                "egress_denies": list(res.denied),
                "packages": packages,
                "marker_skipped": marker_skipped,
                "wheels": wheels,
                "hashes": "committed" if inputs.require_hashes else "recorded",
            }

        return build

    def bind(role: str, sealed: Sealed) -> DepsBinding:
        mount = provider.store.mount(sealed.key, LANG_PYTHON, SUB, INSIDE)
        return DepsBinding(
            role=role,
            lang=LANG_PYTHON,
            scheme=RECIPE_PY,
            key=sealed.key,
            digest=sealed.digest,
            mounts=(mount,),
            env={"PYTHONNOUSERSITE": "1", "PATH": f"{INSIDE}/bin:{IMAGE_PATH}"},
            local_env={"PYTHONNOUSERSITE": "1"},
            manifest=tuple(sorted(dict(sealed.manifest.get("packages") or {}))),
        )

    return provider.per_lock(
        lang=LANG_PYTHON,
        recipe=RECIPE_PY,
        image=image,
        pin=pin,
        gin=gin,
        build_for=build_for,
        bind=bind,
    )


RECIPES[LANG_PYTHON] = resolve

__all__ = [
    "INSIDE",
    "SUB",
    "fetch_plan",
    "install_plan",
    "installed_manifest",
    "lock_text",
    "resolve",
]
