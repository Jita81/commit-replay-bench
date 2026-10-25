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
runner puts it on ``PYTHONPATH`` after the tree. A repository's ``runner_opts.dist_info_stubs``
are written into the site after the install (METADATA only, as the host's setup writes
them) and are in the set's key; a malformed entry is ``PROVISION_STUB_INVALID``.

The lint recipe, ``py.lint.v1`` (:func:`lint_sets`, under docker only): belt 5's ruff at the
version each commit pins (:func:`crb.core.lint.sealed_ruff_version`, read from git objects),
fetched and installed by the same two plans (``ruff==V``, the committed ``uv.lock`` hashes
when they name that version), checked to hold exactly ``ruff-V.dist-info`` and ``bin/ruff``,
sealed under a key over the image and the pin, and mounted read-only at ``/deps/lint`` for
the lint steps alone — never on ``PYTHONPATH`` (ADR-0011 amendment d).

Navigation
----------
What it is:   The Python dependency recipe — the fetch and install plans, the wheel manifest and
              the resolver the sealed provider calls for a ``pytest`` repository.
What it does: Fetches wheels only for exactly the pinned ``name==version`` lines (hash-checked
              when committed), installs them with no network into a site directory, seals one
              set per lockfile, and binds it read-only at ``/deps/site``; seals the ruff each
              commit pins as a lint set at ``/deps/lint``.
How:          ``LockInputs.py_pins`` → ``lock_text`` → ``fetch_plan`` → ``run_fetch`` →
              ``install_plan`` (offline) → drop the wheels → seal → ``DepsBinding`` with the
              mount, ``PYTHONNOUSERSITE`` and ``PATH``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/provision/__init__.py (``SealedProvider.per_lock`` calls ``resolve``;
              ``SealedProvider.resolve`` calls ``lint_sets`` through ``LINT_RECIPES``),
              src/crb/provision/fetch.py (runs both plans), src/crb/core/provision.py (the pins),
              src/crb/core/runners/pytest_runner.py (applies the binding)
Tested by:    tests/test_provision_python.py, tests/test_lint_sealed_ruff.py
Touch when:   a Python repository's lock is refused — commit a pinned requirements lock or name
              one in ``runner_opts.deps_lock``; never to allow a source build.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.core.deps import (
    PROVISION_STUB_INVALID,
    SCOPE_RUN,
    DepsBinding,
    LintSet,
    ProvisionRefused,
)
from crb.core.lint import python_lint_evidence, sealed_ruff_version
from crb.core.provision import (
    LANG_PYTHON,
    RECIPE_PY,
    UV_LOCK,
    LockInputs,
    PyPin,
    bundle_key,
    describe_inputs,
    pin_line_refusal,
    uv_locked,
)
from crb.core.runners.pytest_runner import dist_info_stubs, write_dist_info
from crb.provision import LINT_RECIPES, RECIPES, SealedProvider
from crb.provision.config import ProvisionConfig
from crb.provision.fetch import MIRROR_INSIDE, FetchPlan
from crb.provision.store import Sealed, remove_tree

if TYPE_CHECKING:  # pragma: no cover
    from crb.core.deps import TaskDeps
    from crb.core.git import GitRepo
    from crb.core.spec import RepoConfig

INSIDE = "/deps/site"
SUB = "site"
#: The lint recipe: one tool wheel (the commit's pinned ruff), fetched and installed as the
#: site recipe installs a lock, sealed apart and mounted read-only at ``LINT_INSIDE``.
RECIPE_LINT = "py.lint.v1"
LINT_INSIDE = "/deps/lint"
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
    """The one lock pip reads, written from the parsed pins (never the repository's file).

    Fail closed: every pin is matched field by field before it is written
    (``pin_line_refusal``), whatever reader produced it, so a name, version, marker or hash
    that would carry a second line, a comment or an option into ``/in/lock.txt`` is refused
    ``PROVISION_SOURCE_REFUSED`` rather than written."""
    lines = []
    for p in inputs.py_pins:
        why = pin_line_refusal(p)
        if why:
            raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{p.source or 'a pin'}: {why}")
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


def write_stubs(site: Path, stubs: tuple[tuple[str, str], ...]) -> list[str]:
    """Write each ``(name, version)`` stub into ``site`` after pip's install, as
    ``name==version``. They are never ``packages``: the environment probe requires those, and
    a stub is metadata, not a pin. A name the set already holds a distribution of is left
    alone — that distribution answers ``importlib.metadata`` already, and two would leave
    which one answers to the order the directory is read in."""
    held = {_dist(d.name)[0] for d in site.glob("*.dist-info") if d.is_dir()}
    written = []
    for name, version in stubs:
        norm = re.sub(r"[-_.]+", "-", name).lower()
        if norm in held:
            continue
        write_dist_info(site, name, version)
        held.add(norm)
        written.append(f"{name}=={version}")
    return written


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
    try:
        stubs = dist_info_stubs(config.runner_opts)
    except ValueError as exc:
        raise ProvisionRefused(PROVISION_STUB_INVALID, str(exc)) from exc

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
            written = write_stubs(stage / "out" / SUB, stubs)
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
                **({"dist_info_stubs": written} if stubs else {}),
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
        extra=tuple(f"dist-info-stub:{n}=={v}" for n, v in stubs),
    )


class _CommitFiles:
    """One commit's tree as :class:`crb.core.lint.ConfigFiles`, read from the object store
    (never a worktree): belt 5's own detectors name the ruff a lint set must hold."""

    def __init__(self, repo: GitRepo, sha: str) -> None:
        self._repo = repo
        self._sha = sha

    def is_file(self, path: str) -> bool:
        return self._repo.show_blob(self._sha, path) is not None

    def text(self, path: str, limit: int = 1_000_000) -> str:
        data = self._repo.show_blob(self._sha, path)
        if data is None or len(data) > limit:
            return ""
        return data.decode("utf-8", errors="replace")

    def files_under(self, directory: str) -> list[str]:
        d = directory.rstrip("/")
        r = self._repo.run("ls-tree", f"{self._sha}:{d}" if d else self._sha)
        if not r.ok:
            return []
        prefix = f"{d}/" if d else ""
        out: list[str] = []
        for line in r.lines:  # "<mode> <type> <oid>\t<name>": blobs only, as on disk
            meta, _, name = line.partition("\t")
            if name and meta.split()[1:2] == ["blob"]:
                out.append(f"{prefix}{name}")
        return sorted(out)


def _ruff_pin(files: _CommitFiles, sha: str) -> tuple[PyPin | None, str]:
    """``(pin, "")`` — the ruff the commit pins, with the hashes ``uv.lock`` commits for
    that exact version — ``(None, reason)`` when it pins none, ``(None, "")`` when it
    configures no ruff at all."""
    found = python_lint_evidence(files)
    if "ruff" not in found and "ruff-format" not in found:
        return None, ""
    version, why = sealed_ruff_version(files)
    if not version:
        return None, f"{sha[:12]}: {why}"
    locked = uv_locked(files.text(UV_LOCK), "ruff")
    if locked is not None and locked.version == version:
        return PyPin("ruff", version, locked.hashes, "", f"{sha[:12]}:{UV_LOCK}"), ""
    return PyPin("ruff", version, (), "", f"{sha[:12]}:ruff=={version}"), ""


def _lint_set(provider: SealedProvider, pin: PyPin, sha: str) -> LintSet:
    """Seal (or reuse) the set holding exactly ``pin``'s ruff and mount it read-only. The
    label is the set manifest's ``version`` — read from the installed wheel's own
    ``dist-info`` at seal time, never from the request. A set whose manifest does not name
    the pinned ruff is never labelled: a stored one is quarantined and sealed afresh, and a
    fresh one is ``BUNDLE_INTEGRITY`` (``seal_or_reuse``'s ``accept``)."""
    cfg = provider.config
    image = cfg.python_image
    image_id = provider.image_id(image)
    inputs = LockInputs(LANG_PYTHON, sha, RECIPE_PY, pins=(f"ruff=={pin.version}",), py_pins=(pin,))
    key = bundle_key(RECIPE_LINT, image_id, (f"ruff=={pin.version}", *pin.hashes))

    def build(stage: Path) -> dict[str, Any]:
        plan = fetch_plan(inputs, key=key, config=cfg, image=image)
        res = provider.fetch(plan, stage)
        wheels = _wheel_hashes(stage / "out" / "wheels")
        provider.fetch(install_plan(inputs, key=key, image=image), stage)
        remove_tree(stage / "out" / "wheels")
        site = stage / "out" / SUB
        held = sorted(
            v for n, v in (_dist(d.name) for d in site.glob("*.dist-info")) if n == "ruff"
        )
        if held != [pin.version.lower()] or not (site / "bin" / "ruff").is_file():
            raise ProvisionRefused(
                "PROVISION_FETCH_FAILED",
                f"the ruff=={pin.version} wheel installed {held or 'no ruff'} "
                f"({'with' if (site / 'bin' / 'ruff').is_file() else 'without'} bin/ruff)",
            )
        return {
            "recipe": RECIPE_LINT,
            "inputs": [{"sha": sha, "pin": f"ruff=={pin.version}", "source": pin.source}],
            "tool": "ruff",
            "version": held[0],
            "fetch_image": image,
            "fetch_image_id": image_id,
            "registry_hosts": list(plan.registry_hosts),
            "mirror": str(plan.mirror or ""),
            "egress_denies": list(res.denied),
            "packages": {f"ruff=={pin.version}": list(pin.hashes)},
            "wheels": wheels,
            "hashes": "committed" if inputs.require_hashes else "recorded",
        }

    def accept(manifest: Mapping[str, Any]) -> str:
        tool = str(manifest.get("tool") or "")
        version = str(manifest.get("version") or "")
        if tool == "ruff" and version == pin.version.lower():
            return ""
        return (
            f"lint set {key} holds {tool or 'no tool'}=={version or '?'}, not ruff=={pin.version}"
        )

    sealed = provider.seal_or_reuse(LANG_PYTHON, key, build, accept)
    mount = provider.store.mount(key, LANG_PYTHON, SUB, LINT_INSIDE)
    return LintSet("ruff", str(sealed.manifest["version"]), key, sealed.digest, mount)


def lint_sets(
    provider: SealedProvider, repo: GitRepo, shas: tuple[str, ...]
) -> tuple[tuple[LintSet, ...], str]:
    """``(sets, note)`` — one sealed ruff set per distinct version the commits ``shas`` pin
    (the parent's and the gold's), for belt 5 under docker: the sandbox image carries no
    linter. ``note`` says why a commit has none (it pins no exact ruff; a fetch was
    refused). A task-scope refusal (the wheel would not fetch or install) is a note, not an
    exception: the lint step is then refused with it — a harness error, not a verdict. Every
    run-scope refusal (``BUNDLE_INTEGRITY`` among them) and ``SandboxUnavailable``
    propagate: they refuse the run, as the site set's do, and are never a note."""
    wanted: dict[str, tuple[PyPin, str]] = {}  # version → (pin, the commit it came from)
    notes: list[str] = []
    for sha in dict.fromkeys(shas):
        pin, why = _ruff_pin(_CommitFiles(repo, sha), sha)
        if why:
            notes.append(why)
        held = wanted.get(pin.version) if pin is not None else None
        if pin is not None and (held is None or (pin.hashes and not held[0].hashes)):
            wanted[pin.version] = (pin, sha)  # committed hashes win over recorded ones
    sets: list[LintSet] = []
    for version, (pin, sha) in sorted(wanted.items()):
        try:
            sets.append(_lint_set(provider, pin, sha))
        except ProvisionRefused as exc:
            if exc.scope == SCOPE_RUN:
                raise  # a damaged store or a refused posture refuses the run, never a note
            notes.append(f"ruff=={version}: {exc.code}: {exc.message}")
    return tuple(sets), "; ".join(notes)


RECIPES[LANG_PYTHON] = resolve
LINT_RECIPES[LANG_PYTHON] = lint_sets

__all__ = [
    "INSIDE",
    "LINT_INSIDE",
    "RECIPE_LINT",
    "SUB",
    "fetch_plan",
    "install_plan",
    "installed_manifest",
    "lint_sets",
    "lock_text",
    "resolve",
    "write_stubs",
]
