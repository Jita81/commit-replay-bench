"""Dependency provisioning behind the ``crb.core.deps`` seam (ADR-0019).

:func:`make_deps_provider` picks the provider for the deployment's posture:

* **provisioning off, local executor** → :class:`HostEnvProvider`: the host's own setup, as
  before; nothing is bound (``mode`` answers ``host-env``).
* **provisioning off, docker executor** → :class:`DisabledProvider`: the lockfiles are read
  from git objects; a repository that declares dependencies is refused
  ``PROVISION_DISABLED`` (run scope) before any spend, with the fix; one that declares none
  is sealed and empty.
* **provisioning on** → :class:`SealedProvider`: lockfiles → key → a store hit
  (``provision.reuse``) or a fetch and a seal (``provision.fetch`` / ``provision.seal``) →
  a :class:`~crb.core.deps.TaskDeps` with the parent's, the gold's and the builder's
  bindings and the closure selector. In production a public registry without
  ``allow_public`` and a fetch image without a digest are refused at construction.

Every provider speaks :class:`~crb.core.deps.DepsProvider`: ``mode(config, executor)``
(the dependency part of the posture class), ``resolve`` (from git objects, never a
worktree) and ``verify`` (every sealed set a task cites, re-hashed).

Navigation
----------
What it is:   The dependency providers — host-env, disabled and sealed — and the factory that
              picks one for the deployment's posture.
What it does: Resolves a task's dependencies from its parent's and gold's lockfiles (git
              objects only), reusing a sealed set or fetching and sealing one, and binds each
              role's set; refuses with the ``PROVISION_*`` code when it cannot, before any
              builder exists; verifies a sealed set on demand.
How:          ``LockInputs.from_git`` (parent, gold) → per language: ``bundle_key`` /
              ``go_keys`` → ``BundleStore.get`` or ``run_fetch`` + ``seal`` → ``store.mount`` →
              ``DepsBinding`` per role → ``TaskDeps`` with the ``ClosureSelector``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md, docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/core/deps.py (the protocol and types it implements),
              src/crb/core/provision.py (lockfiles and keys), src/crb/provision/store.py (sealed
              sets), src/crb/provision/fetch.py (the fetch container), src/crb/provision/go.py,
              src/crb/provision/python.py and src/crb/provision/node.py (the recipes),
              src/crb/provision/config.py (``CRB_PROVISION__*``)
Tested by:    tests/test_provision_go.py, tests/test_provision_python.py, tests/test_provision_node.py,
              tests/test_posture_e2e_docker.py
Touch when:   never for a new repository; a new language recipe registers here and in
              src/crb/core/provision.py.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.core.deps import (
    DEPS_MODE_HOST_ENV,
    DEPS_MODE_SEALED,
    ROLE_BUILDER,
    ROLE_GOLD,
    ROLE_PARENT,
    DepsBinding,
    EventFn,
    ProvisionRefused,
    TaskDeps,
    host_env_deps,
    no_deps,
)
from crb.core.execution import SandboxUnavailable
from crb.core.provision import (
    LANG_GO,
    RECIPE_GO,
    RECIPE_GO_VENDOR,
    LockInputs,
    bundle_key,
    closure_selector,
    describe_inputs,
    go_keys,
    lang_of,
)
from crb.provision import go as go_recipe
from crb.provision.config import ProvisionConfig
from crb.provision.fetch import run_fetch
from crb.provision.store import BundleStore, Sealed

if TYPE_CHECKING:  # pragma: no cover
    from crb.core.git import GitRepo
    from crb.core.spec import RepoConfig

#: ``(provider, repo config, parent inputs, gold inputs) → TaskDeps`` — a language recipe.
RecipeFn = Callable[["SealedProvider", "RepoConfig", LockInputs, LockInputs], TaskDeps]

MODE_SEALED = DEPS_MODE_SEALED
MODE_HOST = DEPS_MODE_HOST_ENV

#: Language → recipe resolver, for the languages that are not Go (registered by their
#: modules on import: src/crb/provision/python.py, src/crb/provision/node.py).
RECIPES: dict[str, RecipeFn] = {}


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def _inputs(
    repo: GitRepo, config: RepoConfig, gold: str, parent: str, npm_host: str
) -> tuple[str, LockInputs, LockInputs]:
    lang = lang_of(config)
    parent = parent or repo.parent(gold)
    pin = LockInputs.from_git(repo, parent, config, npm_registry_host=npm_host)
    gin = LockInputs.from_git(repo, gold, config, npm_registry_host=npm_host)
    return lang, pin, gin


class HostEnvProvider:
    """The local posture with provisioning off: the host's own setup; nothing bound."""

    deps_mode = MODE_HOST
    enabled = False

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        return self.deps_mode

    def resolve(
        self,
        repo: GitRepo,
        config: RepoConfig,
        *,
        gold: str,
        parent: str = "",
        executor_name: str = "",
        on_event: EventFn | None = None,
    ) -> TaskDeps:
        return host_env_deps(str(config.language))

    def verify(self, deps: TaskDeps) -> None:
        return None


class DisabledProvider:
    """The sealed posture with provisioning off: a repository that declares dependencies is
    refused ``PROVISION_DISABLED`` (run scope) before any spend."""

    deps_mode = MODE_SEALED
    enabled = False

    def __init__(self, config: ProvisionConfig | None = None) -> None:
        self.config = config or ProvisionConfig()

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        return self.deps_mode

    def resolve(
        self,
        repo: GitRepo,
        config: RepoConfig,
        *,
        gold: str,
        parent: str = "",
        executor_name: str = "",
        on_event: EventFn | None = None,
    ) -> TaskDeps:
        lang, pin, gin = _inputs(repo, config, gold, parent, self.config.npm_registry_host())
        declared = [i for i in (pin, gin) if i.declares_dependencies]
        if declared:
            what = ", ".join(declared[0].pins[:3]) or declared[0].recipe
            raise ProvisionRefused(
                "PROVISION_DISABLED",
                f"{config.name} declares {lang} dependencies ({what}) and dependency "
                "provisioning is off",
            )
        return no_deps(self.deps_mode, lang)

    def verify(self, deps: TaskDeps) -> None:
        return None


class SealedProvider:
    """Provisioning on: fetch outside the test container, seal, bind read-only."""

    deps_mode = MODE_SEALED
    enabled = True

    def __init__(
        self,
        config: ProvisionConfig,
        *,
        store: BundleStore | None = None,
        docker: str = "",
        on_event: EventFn | None = None,
    ) -> None:
        self.config = config
        self.store = store or BundleStore(config.store)
        self.docker = docker or config.docker_binary or shutil.which("docker") or "docker"
        self.on_event = on_event
        self._image_ids: dict[str, str] = {}
        self._lock = threading.Lock()
        self._call = threading.local()  # the event sink of the resolve on this thread

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        return self.deps_mode

    def _events(self) -> EventFn | None:
        """This call's event sink (``resolve(on_event=…)``), else the provider's."""
        return getattr(self._call, "on_event", None) or self.on_event

    # --- plumbing ------------------------------------------------------------------
    def image_id(self, image: str) -> str:
        """``docker image inspect --format {{.Id}}`` — the fetch image's bytes, never its tag."""
        hit = self._image_ids.get(image)
        if hit:
            return hit
        try:
            r = subprocess.run(
                [self.docker, "image", "inspect", "--format", "{{.Id}}", image],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxUnavailable(f"fetch image probe failed for {image!r}: {exc}") from exc
        if r.returncode != 0 or not r.stdout.strip():
            raise SandboxUnavailable(
                f"fetch image {image!r} is not present in the daemon's store (the worker never "
                "pulls; pre-pull it — deploy/sandbox/README.md §2)"
            )
        self._image_ids[image] = r.stdout.strip()
        return self._image_ids[image]

    def verify(self, deps: TaskDeps) -> None:
        """Re-hash every sealed set ``deps`` cites (``BUNDLE_INTEGRITY`` on a mismatch)."""
        for key in deps.keys:
            self.store.verify(key)

    def seal_or_reuse(self, lang: str, key: str, build: Callable[[Path], dict[str, Any]]) -> Sealed:
        """A store hit, or ``build(stage)`` (which fetches into the stage and returns the
        manifest fields) and a seal. One fetch at a time in this process."""
        on_event = self._events()
        with self._lock:
            hit = self.store.get(lang, key)
            if hit is not None:
                _emit(on_event, "provision.reuse", lang=lang, key=key, digest=hit.digest)
                return hit
            stage = self.store.stage()
            try:
                fields = build(stage)
            except BaseException:
                self.store.discard(stage)
                raise
            sealed = self.store.seal(stage, {"lang": lang, "key": key, **fields})
            _emit(
                on_event,
                "provision.seal",
                lang=lang,
                key=key,
                digest=sealed.digest,
                bytes=sealed.bytes,
            )
            return sealed

    def fetch(self, plan: Any, stage: Path) -> Any:
        """``run_fetch`` with this provider's configuration, docker and event sink."""
        return run_fetch(
            plan, stage, config=self.config, docker=self.docker, on_event=self._events()
        )

    # --- resolve ------------------------------------------------------------------------
    def resolve(
        self,
        repo: GitRepo,
        config: RepoConfig,
        *,
        gold: str,
        parent: str = "",
        executor_name: str = "",
        on_event: EventFn | None = None,
    ) -> TaskDeps:
        previous = getattr(self._call, "on_event", None)
        self._call.on_event = on_event
        try:
            return self._resolve(repo, config, gold=gold, parent=parent)
        finally:
            self._call.on_event = previous

    def _resolve(self, repo: GitRepo, config: RepoConfig, *, gold: str, parent: str) -> TaskDeps:
        lang, pin, gin = _inputs(repo, config, gold, parent, self.config.npm_registry_host())
        if not (pin.declares_dependencies or gin.declares_dependencies):
            return no_deps(self.deps_mode, lang)
        if lang == LANG_GO:
            return self._resolve_go(config, pin, gin)
        recipe = RECIPES.get(lang)
        if recipe is None:  # pragma: no cover - the recipes register on import below
            raise ProvisionRefused("PROVISION_UNSUPPORTED_LANGUAGE", f"no recipe for {lang}")
        return recipe(self, config, pin, gin)

    def _resolve_go(self, config: RepoConfig, pin: LockInputs, gin: LockInputs) -> TaskDeps:
        if RECIPE_GO_VENDOR in {pin.recipe, gin.recipe}:
            vb = {
                r: DepsBinding(
                    role=r,
                    lang=LANG_GO,
                    scheme=RECIPE_GO_VENDOR,
                    env=dict(go_recipe.VENDOR_ENV),
                    local_env=dict(go_recipe.VENDOR_ENV),
                )
                for r in (ROLE_PARENT, ROLE_GOLD, ROLE_BUILDER)
            }
            return TaskDeps(
                self.deps_mode, LANG_GO, vb[ROLE_PARENT], vb[ROLE_GOLD], vb[ROLE_BUILDER]
            )
        image = self.config.go_image
        image_id = self.image_id(image)
        union_key, parent_key = go_keys(pin, gin, image_id)
        opts = dict(config.runner_opts)

        def fetcher(sets: list[LockInputs], key: str) -> Callable[[Path], dict[str, Any]]:
            def build(stage: Path) -> dict[str, Any]:
                plan = go_recipe.plan(sets, key=key, config=self.config, opts=opts, image=image)
                res = self.fetch(plan, stage)
                return {
                    "recipe": plan.recipe,
                    "inputs": [describe_inputs(s) for s in sets],
                    "fetch_image": image,
                    "fetch_image_id": image_id,
                    "registry_hosts": list(plan.registry_hosts),
                    "mirror": str(plan.mirror or ""),
                    "egress_denies": list(res.denied),
                    "modules": go_recipe.manifest_modules(res.stdout),
                    "hashes": "committed",
                }

            return build

        union = self.seal_or_reuse(LANG_GO, union_key, fetcher([pin, gin], union_key))
        parent_set = (
            union
            if parent_key == union_key
            else self.seal_or_reuse(LANG_GO, parent_key, fetcher([pin], parent_key))
        )

        def bind(role: str, sealed: Sealed) -> DepsBinding:
            mount = self.store.mount(sealed.key, LANG_GO, go_recipe.SUB, go_recipe.INSIDE)
            modules = dict(sealed.manifest.get("modules") or {})
            return DepsBinding(
                role=role,
                lang=LANG_GO,
                scheme=RECIPE_GO,
                key=sealed.key,
                digest=sealed.digest,
                mounts=(mount,),
                env=go_recipe.binding_env(),
                local_env=go_recipe.local_env(sealed.path / go_recipe.SUB),
                manifest=tuple(sorted(modules)),
            )

        gold_b = bind(ROLE_GOLD, union)
        return TaskDeps(
            self.deps_mode,
            LANG_GO,
            parent=bind(ROLE_PARENT, union),
            gold=gold_b,
            builder=bind(ROLE_BUILDER, parent_set),
            selector=closure_selector(LANG_GO, modules=gold_b.manifest),
        )

    def per_lock(
        self,
        *,
        lang: str,
        recipe: str,
        image: str,
        pin: LockInputs,
        gin: LockInputs,
        build_for: Callable[[LockInputs, str, str], Callable[[Path], dict[str, Any]]],
        bind: Callable[[str, Sealed], DepsBinding],
    ) -> TaskDeps:
        """One sealed set per lockfile (Python, Node): the parent's and the gold's — one key
        when the lock did not change; the builder gets the parent's."""
        image_id = self.image_id(image)
        sealed: dict[str, Sealed] = {}
        for role, inputs in ((ROLE_PARENT, pin), (ROLE_GOLD, gin)):
            key = bundle_key(recipe, image_id, inputs.blobs)
            sealed[role] = self.seal_or_reuse(lang, key, build_for(inputs, key, image_id))
        return TaskDeps(
            self.deps_mode,
            lang,
            parent=bind(ROLE_PARENT, sealed[ROLE_PARENT]),
            gold=bind(ROLE_GOLD, sealed[ROLE_GOLD]),
            builder=bind(ROLE_BUILDER, sealed[ROLE_PARENT]),
            selector=closure_selector(lang, parent=pin, gold=gin),
        )


DepsProviderImpl = HostEnvProvider | DisabledProvider | SealedProvider


def make_deps_provider(
    config: ProvisionConfig,
    *,
    executor_kind: str = "docker",
    on_event: EventFn | None = None,
    docker: str = "",
    probe_image: str = "",
) -> DepsProviderImpl:
    """The provider for this posture (see the module docstring). ``probe_image`` (a present
    image, e.g. the sandbox image) proves the daemon can see the store; a store it cannot
    see is ``PROVISION_STORE_NOT_VISIBLE``. Production refusals raise here, before any run."""
    kind = (executor_kind or "local").strip().lower()
    if not config.enabled:
        return HostEnvProvider() if kind in {"local", "host", ""} else DisabledProvider(config)
    refusal = config.production_refusal()
    if refusal is not None:
        raise refusal
    provider = SealedProvider(config, docker=docker, on_event=on_event)
    if probe_image and kind == "docker":
        provider.store.visible_to_daemon(provider.docker, probe_image)
    return provider


# The language recipes register themselves in RECIPES on import (they import this module).
from crb.provision import node as _node  # noqa: E402, F401
from crb.provision import python as _python  # noqa: E402, F401

__all__ = [
    "MODE_HOST",
    "MODE_SEALED",
    "RECIPES",
    "DepsProviderImpl",
    "DisabledProvider",
    "HostEnvProvider",
    "SealedProvider",
    "make_deps_provider",
]
