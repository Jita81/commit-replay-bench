"""The Go recipe, ``go.modcache.v1``: the parent's and the gold's modules in one sealed cache.

One fetch container runs ``cd /in/<set> && go mod download -json`` for the parent's and
the gold's ``go.mod`` / ``go.sum`` (and any local replace target's ``go.mod``), writing one
module cache: the gold commit's ``go.sum`` differs from its parent's (the D4 finding), and
both must build offline from the same set. Every artifact is checked against the committed
``go.sum`` and the checksum database; ``go mod download -json`` reports each module's
``ziphash``, which the manifest records.

The environment is fixed: ``GOPROXY`` is the configured proxy (never ``,direct``),
``GOVCS=*:off`` so no VCS is ever run, ``GOTOOLCHAIN=local`` so no toolchain is downloaded,
``GOENV=off`` / ``GOWORK=off`` so nothing from a repository configures the fetch,
``GOFLAGS=-mod=readonly``. A private module (``runner_opts.goprivate``) with only a public
proxy configured is refused before any request (``PROVISION_PRIVATE_MODULE``); a ``go``
directive newer than the fetch image's toolchain is ``PROVISION_TOOLCHAIN_TOO_OLD``.

At test time the set is mounted read-only at ``/deps/gomod`` with ``GOPROXY=off
GOSUMDB=off`` (:func:`binding_env`).

Navigation
----------
What it is:   The Go dependency recipe — the fetch plan, its refusals, the manifest reader and
              the offline test-time environment.
What it does: Plans one fetch for the parent's and the gold's module sets into one cache;
              refuses a private module without a private proxy and a too-new ``go`` directive
              before any request; reads ``go mod download -json`` into ``module@version`` →
              ``ziphash``; gives the offline environment a sealed cache is mounted with.
How:          ``LockInputs`` (from git objects) → ``plan`` (inputs under ``/in/parent`` and
              ``/in/gold``, the fixed env) → ``run_fetch`` → ``manifest_modules`` →
              ``binding_env`` / ``local_env``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/provision/fetch.py (runs the plan), src/crb/provision/__init__.py (the
              provider that seals and binds), src/crb/core/provision.py (``LockInputs``,
              ``go_keys``), src/crb/core/runners/go_runner.py (applies the binding)
Tested by:    tests/test_provision_go.py, tests/test_runners_go.py
Touch when:   a Go repository needs a private module (point ``CRB_PROVISION__GO_PROXY`` at a
              mirror that holds it; ``runner_opts.goprivate`` names it); never to add
              ``direct`` or a VCS.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from crb.core.deps import ProvisionRefused
from crb.core.provision import RECIPE_GO, LockInputs, go_version_tuple
from crb.provision.config import PUBLIC_HOSTS, ProvisionConfig
from crb.provision.fetch import MIRROR_INSIDE, FetchPlan

#: Where the cache is mounted in a test container.
INSIDE = "/deps/gomod"
SUB = "gomod"


def toolchain_of(image: str) -> tuple[int, ...]:
    """The Go version a ``golang:<version>-…`` image reference names (``()`` if none)."""
    m = re.search(r"golang:(\d+\.\d+(?:\.\d+)?)", image)
    return go_version_tuple(m.group(1)) if m else ()


def _goprivate(opts: Mapping[str, Any]) -> tuple[str, ...]:
    raw = opts.get("goprivate") or ""
    items = raw if isinstance(raw, list | tuple) else str(raw).split(",")
    return tuple(str(p).strip() for p in items if str(p).strip())


def _matches(pattern: str, module: str) -> bool:
    """Go's GOPRIVATE rule: the glob matches a prefix of the path, element by element."""
    parts = module.split("/")
    n = len(pattern.split("/"))
    return len(parts) >= n and fnmatch.fnmatchcase("/".join(parts[:n]), pattern)


def plan(
    sets: Iterable[LockInputs],
    *,
    key: str,
    config: ProvisionConfig,
    opts: Mapping[str, Any],
    image: str = "",
) -> FetchPlan:
    """The fetch plan for ``sets`` (the parent's and the gold's, de-duplicated) into ``key``."""
    image = image or config.go_image
    sets = list(sets)
    tc = toolchain_of(image)
    for s in sets:
        want = go_version_tuple(s.go_mod.go if s.go_mod else "")
        if tc and want and want > tc:
            raise ProvisionRefused(
                "PROVISION_TOOLCHAIN_TOO_OLD",
                f"go.mod at {s.sha[:12]} says go {s.go_mod.go if s.go_mod else ''}; the fetch "
                f"image has go {'.'.join(map(str, tc))}",
            )
    private = _goprivate(opts)
    mirror = config.mirror_for("go")
    public_proxy = mirror is None and any(
        h.split(":")[0] in PUBLIC_HOSTS for h in config.hosts_for("go")[:1]
    )
    if private and public_proxy:
        for s in sets:
            hit = sorted(p for p in s.pins if any(_matches(g, p.split("@", 1)[0]) for g in private))
            if hit:
                raise ProvisionRefused(
                    "PROVISION_PRIVATE_MODULE",
                    f"{hit[0]} is private (runner_opts.goprivate) and the configured proxy "
                    f"{config.go_proxy} is public",
                )
    inputs: dict[str, bytes] = {}
    names: list[str] = []
    seen: dict[tuple[str, ...], str] = {}
    for s in sets:
        ident = s.blobs
        if ident in seen:
            continue
        name = f"s{len(names)}"
        seen[ident] = name
        names.append(name)
        for f in s.files:
            inputs[f"{name}/{f.path}"] = f.data
    script = " && ".join(f"cd /in/{n} && go mod download -json" for n in names)
    env = {
        "GOPROXY": f"file://{MIRROR_INSIDE}" if mirror is not None else config.go_proxy,
        "GOSUMDB": "off" if mirror is not None else (config.go_sumdb or "off"),
        "GOVCS": "*:off",
        "GOFLAGS": "-mod=readonly",
        "GOTOOLCHAIN": "local",
        "GOENV": "off",
        "GOWORK": "off",
        "CGO_ENABLED": "0",
        "GOMODCACHE": f"/out/{SUB}",
        "GOCACHE": "/tmp/gocache",
        "GOPATH": "/tmp/go",
    }
    if private:
        env["GONOSUMDB"] = ",".join(private)
    return FetchPlan(
        recipe=RECIPE_GO,
        lang="go",
        key=key,
        image=image,
        argv=("sh", "-c", script),
        env=env,
        registry_hosts=config.hosts_for("go"),
        inputs=inputs,
        mirror=mirror,
    )


def manifest_modules(stdout: str) -> dict[str, str]:
    """``module@version`` → ``ziphash`` (``Sum``) from ``go mod download -json`` output (a
    stream of JSON objects). An object with an ``Error`` is a failed fetch."""
    out: dict[str, str] = {}
    dec = json.JSONDecoder()
    i, n = 0, len(stdout)
    while i < n:
        while i < n and stdout[i].isspace():
            i += 1
        if i >= n:
            break
        obj, i = dec.raw_decode(stdout, i)
        if not isinstance(obj, dict):
            continue
        if obj.get("Error"):
            raise ProvisionRefused("PROVISION_FETCH_FAILED", str(obj["Error"])[:400])
        path, version = obj.get("Path"), obj.get("Version")
        if path and version:
            out[f"{path}@{version}"] = str(obj.get("Sum") or "")
    return out


#: The offline test-time environment (a container: the cache at /deps/gomod).
TEST_ENV: Mapping[str, str] = {
    "GOPROXY": "off",
    "GOSUMDB": "off",
    "GOVCS": "*:off",
    "GOWORK": "off",
    "GOENV": "off",
    "GOTOOLCHAIN": "local",
    "GOFLAGS": "-count=1 -mod=mod",
}


def binding_env() -> dict[str, str]:
    """For a test container: the mounted cache, offline."""
    return {**TEST_ENV, "GOMODCACHE": INSIDE, "GOCACHE": "/tmp/gocache"}


def local_env(path: Path) -> dict[str, str]:
    """For a host command: the sealed cache at its store path, offline."""
    return {**TEST_ENV, "GOMODCACHE": str(path)}


#: A vendored tree: no fetch, the vendor directory is the set.
VENDOR_ENV: Mapping[str, str] = {**TEST_ENV, "GOFLAGS": "-count=1 -mod=vendor"}


__all__ = [
    "INSIDE",
    "SUB",
    "TEST_ENV",
    "VENDOR_ENV",
    "binding_env",
    "local_env",
    "manifest_modules",
    "plan",
    "toolchain_of",
]
