"""The posture seam: a task's dependencies as bindings, and the provider that resolves them.

A test run needs its dependencies somewhere the toolchain can read them. On the host
(the ``local`` executor) that is the host's own environment — a module cache, a
virtualenv, ``node_modules`` — which is what this product has always used. Inside the
sealed sandbox (``--network=none``, ADR-0005) nothing is there unless it was provisioned
first, outside the test container, from the task's own lockfiles (ADR-0019 §6).

This module is the interface both sides of that decision code to:

* a :class:`DepsBinding` is one dependency set as a test command sees it — the read-only
  mounts it needs and the environment that points the toolchain at them (``env`` inside
  the sandbox, ``local_env`` on the host);
* a :class:`TaskDeps` holds the three bindings a task has — the parent's (for the
  qualification's RED and baseline), the gold's (for the gold check and the blame
  witness) and the builder's (what a sealed builder may read: the parent's, never the
  gold's) — and the closure selector (:meth:`TaskDeps.for_tree`) that picks the binding a
  trial's own manifests select, or refuses with :class:`ClosureViolation`;
* a :class:`DepsProvider` resolves a task's :class:`TaskDeps` from git objects before
  any builder exists, and refuses with :class:`ProvisionRefused` (a :class:`Refusal`:
  code, message, fix, guide anchor, scope) when it cannot.

:class:`NullDepsProvider` is what a deployment has until provisioning is switched on: the
host's environment under ``local``, and nothing at all under ``docker`` — which is the
honest statement of the sealed posture as shipped (the qualification then refuses a task
whose parent cannot load its dependencies offline, ``QUAL_ENV_UNLOADABLE``, instead of a
replay blaming the model for it).

Navigation
----------
What it is:   The dependency seam of ADR-0019 — bindings, the task's three bindings and its
              closure selector, the refusal vocabulary and the provider protocol, plus the
              null provider every deployment starts with.
What it does: Gives the qualifier, the grader and the worker one shape for "the
              dependencies this test run may read", so the posture that grades a trial is the
              posture its qualification measured; never fetches anything itself.
How:          Frozen dataclasses and a ``Protocol``; ``NullDepsProvider.mode`` answers
              ``host-env`` for ``local`` and ``sealed`` for ``docker``; ``TaskDeps.to_dict`` /
              ``from_dict`` round-trip everything but the selector (a function, not data).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/runners/base.py (``run_for(deps=…)`` applies a binding to the test
              command), src/crb/core/execution.py (``Command.ro_mounts`` carries the mounts),
              src/crb/core/grade.py (the grader the bindings reach through the runner),
              src/crb/provision/__init__.py (``make_deps_provider`` — the one place
              a deployment's provider is chosen), src/crb/server/worker.py (resolves a task's
              dependencies before it qualifies or builds)
Tested by:    tests/test_deps_seam.py
Touch when:   a new dependency scheme lands (a constant here, the binding in the provider);
              a refusal code is added (the constant, ``REFUSAL_TEXT`` and ADR-0019's table
              together).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # the protocol names them; the core never imports them at run time
    from crb.core.git import GitRepo
    from crb.core.spec import RepoConfig

#: The binding schemes. ``none`` — nothing mounted, nothing set (the sealed posture with
#: provisioning off); ``host-env`` — the host's own environment (the ``local`` executor).
DEPS_NONE = "none"
DEPS_HOST_ENV = "host-env"
SCHEME_GO = "go.modcache.v1"
SCHEME_GO_VENDOR = "go.vendor.v1"
SCHEME_PY = "py.site.v1"
SCHEME_NODE = "node.modules.v1"

#: How a posture gets its dependencies — one of the three parts of ``posture_class``.
DEPS_MODE_SEALED = "sealed"
DEPS_MODE_HOST_ENV = "host-env"
DEPS_MODES: tuple[str, ...] = (DEPS_MODE_SEALED, DEPS_MODE_HOST_ENV)

#: The scope of a refusal: ``run`` stops the run; ``task`` skips that task.
SCOPE_RUN = "run"
SCOPE_TASK = "task"

#: The provisioning refusal codes (ADR-0019 §9). Run scope: a deployment setting.
PROVISION_DISABLED = "PROVISION_DISABLED"
PROVISION_PUBLIC_REGISTRY = "PROVISION_PUBLIC_REGISTRY"
PROVISION_FETCH_IMAGE_UNPINNED = "PROVISION_FETCH_IMAGE_UNPINNED"
PROVISION_STORE_NOT_VISIBLE = "PROVISION_STORE_NOT_VISIBLE"
PROVISION_UNSUPPORTED_LANGUAGE = "PROVISION_UNSUPPORTED_LANGUAGE"
#: Task scope: a fact about one commit's lockfiles or about the registry.
PROVISION_NO_LOCK = "PROVISION_NO_LOCK"
PROVISION_UNPINNED = "PROVISION_UNPINNED"
PROVISION_SOURCE_REFUSED = "PROVISION_SOURCE_REFUSED"
PROVISION_BUILD_REQUIRED = "PROVISION_BUILD_REQUIRED"
PROVISION_LOCK_UNSUPPORTED = "PROVISION_LOCK_UNSUPPORTED"
PROVISION_PRIVATE_MODULE = "PROVISION_PRIVATE_MODULE"
PROVISION_TOOLCHAIN_TOO_OLD = "PROVISION_TOOLCHAIN_TOO_OLD"
PROVISION_FETCH_FAILED = "PROVISION_FETCH_FAILED"
PROVISION_TOO_LARGE = "PROVISION_TOO_LARGE"
#: A sealed set no longer matches its digest (run scope).
BUNDLE_INTEGRITY = "BUNDLE_INTEGRITY"

_DEPLOY_DOC = "docs/DEPLOYMENT.md#34-the-workers-sandbox--choose-deliberately"

#: code → (the fix sentence, the guide anchor). Every refusal a person meets says what to do.
REFUSAL_TEXT: dict[str, tuple[str, str]] = {
    PROVISION_DISABLED: (
        "switch dependency provisioning on (CRB_PROVISION__ENABLED=true) and qualify again",
        _DEPLOY_DOC,
    ),
    PROVISION_PUBLIC_REGISTRY: (
        "point provisioning at the organisation's mirror, or allow the public registry "
        "explicitly in the provisioning settings",
        _DEPLOY_DOC,
    ),
    PROVISION_FETCH_IMAGE_UNPINNED: (
        "pin the fetch image by digest (image@sha256:…) in the provisioning settings",
        _DEPLOY_DOC,
    ),
    PROVISION_STORE_NOT_VISIBLE: (
        "put the dependency store on a path the docker daemon can mount and run crb doctor",
        _DEPLOY_DOC,
    ),
    PROVISION_UNSUPPORTED_LANGUAGE: (
        "measure this repository in the local posture; its language has no sealed provisioning yet",
        _DEPLOY_DOC,
    ),
    PROVISION_NO_LOCK: (
        "commit a lockfile the provisioner reads (go.sum, package-lock.json or a pinned "
        "requirements file) or measure in the local posture",
        _DEPLOY_DOC,
    ),
    PROVISION_UNPINNED: ("pin every dependency to one version in the lockfile named", _DEPLOY_DOC),
    PROVISION_SOURCE_REFUSED: (
        "replace the URL, VCS or path dependency named with a registry version",
        _DEPLOY_DOC,
    ),
    PROVISION_BUILD_REQUIRED: (
        "use a wheel or a prebuilt package for the dependency named, or measure in the "
        "local posture",
        _DEPLOY_DOC,
    ),
    PROVISION_LOCK_UNSUPPORTED: (
        "use a lockfile format the provisioner reads, or measure in the local posture",
        _DEPLOY_DOC,
    ),
    PROVISION_PRIVATE_MODULE: (
        "mirror the private module named in the organisation's registry",
        _DEPLOY_DOC,
    ),
    PROVISION_TOOLCHAIN_TOO_OLD: (
        "raise the toolchain version of the fetch image to what the lockfile needs",
        _DEPLOY_DOC,
    ),
    PROVISION_FETCH_FAILED: (
        "check the registry host named is on the provisioning allowlist and reachable, "
        "then qualify again",
        _DEPLOY_DOC,
    ),
    PROVISION_TOO_LARGE: (
        "raise the provisioning size limit, or measure this repository in the local posture",
        _DEPLOY_DOC,
    ),
    BUNDLE_INTEGRITY: (
        "run crb deps verify; every qualification that cites the damaged set is revoked "
        "and must be qualified again",
        _DEPLOY_DOC,
    ),
}

#: The codes whose scope is the whole run (a deployment setting or a damaged store).
RUN_SCOPE_CODES: frozenset[str] = frozenset(
    {
        PROVISION_DISABLED,
        PROVISION_PUBLIC_REGISTRY,
        PROVISION_FETCH_IMAGE_UNPINNED,
        PROVISION_STORE_NOT_VISIBLE,
        PROVISION_UNSUPPORTED_LANGUAGE,
        BUNDLE_INTEGRITY,
    }
)


@dataclass(frozen=True)
class BundleMount:
    """One sealed dependency set, bound read-only into a test container at ``inside``."""

    host: Path
    inside: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", Path(self.host))
        if not self.inside.startswith("/"):
            raise ValueError(f"a bundle mount's inside path must be absolute, got {self.inside!r}")

    def to_dict(self) -> dict[str, str]:
        return {"host": str(self.host), "inside": self.inside}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> BundleMount:
        return cls(Path(str(d["host"])), str(d["inside"]))


@dataclass(frozen=True)
class DepsBinding:
    """One dependency set as a test command sees it.

    ``key`` names the set in the store (empty for ``none`` / ``host-env``), ``digest`` is
    its sealed digest; ``mounts`` are bound read-only; ``env`` is set inside the sandbox
    and ``local_env`` on the host — the runner applies the one that fits its executor.
    """

    scheme: str
    key: str = ""
    digest: str = ""
    mounts: tuple[BundleMount, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    local_env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mounts", tuple(self.mounts))
        object.__setattr__(self, "env", dict(self.env))
        object.__setattr__(self, "local_env", dict(self.local_env))

    def env_for(self, executor_name: str) -> dict[str, str]:
        """The environment a command on ``executor_name`` gets from this binding."""
        return dict(self.env) if executor_name == "docker" else dict(self.local_env)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "key": self.key,
            "digest": self.digest,
            "mounts": [m.to_dict() for m in self.mounts],
            "env": dict(self.env),
            "local_env": dict(self.local_env),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> DepsBinding:
        return cls(
            scheme=str(d.get("scheme", DEPS_NONE)),
            key=str(d.get("key", "")),
            digest=str(d.get("digest", "")),
            mounts=tuple(BundleMount.from_dict(m) for m in d.get("mounts") or ()),
            env=dict(d.get("env") or {}),
            local_env=dict(d.get("local_env") or {}),
        )


#: Nothing mounted, nothing set: the sealed posture with provisioning off.
NO_DEPS = DepsBinding(DEPS_NONE)
#: The host's own environment: the ``local`` executor, as this product always ran.
HOST_ENV_DEPS = DepsBinding(DEPS_HOST_ENV)


class ClosureViolation(Exception):
    """A trial's own manifests select dependencies outside the task's closure (belt 1b in
    a provisioned posture): the trial is disqualified, never charged."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


#: ``selector(root) -> DepsBinding`` — which binding a trial's manifests select.
Selector = Callable[[Path], DepsBinding]


@dataclass(frozen=True)
class TaskDeps:
    """A task's three bindings and its closure selector.

    ``parent`` serves the qualification's RED and baseline; ``gold`` the gold check and
    the blame witness; ``builder`` is what a sealed builder may read — the parent's set,
    never the gold's (ADR-0019, amending ADR-0012). ``selector`` is not data: it does not
    round-trip, and a :class:`TaskDeps` read back from a record selects ``gold``.
    """

    scheme: str
    parent: DepsBinding
    gold: DepsBinding
    builder: DepsBinding
    selector: Selector | None = field(default=None, compare=False)

    def for_tree(self, root: Path) -> DepsBinding:
        """The binding a trial at ``root`` is graded with; raises :class:`ClosureViolation`
        when its manifests select anything outside the task's closure. With no selector
        (the null provider, a record read back) the gold's binding serves every trial."""
        if self.selector is None:
            return self.gold
        return self.selector(Path(root))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "parent": self.parent.to_dict(),
            "gold": self.gold.to_dict(),
            "builder": self.builder.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TaskDeps:
        return cls(
            scheme=str(d.get("scheme", DEPS_NONE)),
            parent=DepsBinding.from_dict(d.get("parent") or {}),
            gold=DepsBinding.from_dict(d.get("gold") or {}),
            builder=DepsBinding.from_dict(d.get("builder") or {}),
        )

    @classmethod
    def uniform(cls, binding: DepsBinding) -> TaskDeps:
        """One binding serving all three roles (the null provider's shape)."""
        return cls(binding.scheme, binding, binding, binding)


@dataclass(frozen=True)
class Refusal:
    """Why a provider will not provision: a closed ``code``, a sentence, what to do, the
    guide anchor, and whether it stops the run (``run``) or skips the task (``task``)."""

    code: str
    message: str
    fix: str = ""
    doc: str = ""
    scope: str = SCOPE_TASK

    def __post_init__(self) -> None:
        if self.scope not in (SCOPE_RUN, SCOPE_TASK):
            raise ValueError(f"refusal scope must be {SCOPE_RUN!r} or {SCOPE_TASK!r}")
        fix, doc = REFUSAL_TEXT.get(self.code, ("", ""))
        if not self.fix:
            object.__setattr__(self, "fix", fix)
        if not self.doc:
            object.__setattr__(self, "doc", doc)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
            "doc": self.doc,
            "scope": self.scope,
        }


def refusal(code: str, message: str) -> Refusal:
    """A :class:`Refusal` with the code's own scope, fix and guide anchor."""
    return Refusal(code, message, scope=SCOPE_RUN if code in RUN_SCOPE_CODES else SCOPE_TASK)


class ProvisionRefused(Exception):
    """The provider will not provision; ``refusal`` says why and what to do."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(f"{refusal.code}: {refusal.message}")
        self.refusal = refusal


class DepsProvider(Protocol):
    """How a task's dependencies are resolved (ADR-0019 §6). The qualifier, the grader and
    the worker consume it; ``crb.provision`` implements it."""

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        """``sealed`` or ``host-env`` — the dependency part of the posture class."""
        ...

    def resolve(
        self,
        repo: GitRepo,
        config: RepoConfig,
        *,
        parent: str,
        gold: str,
        executor_name: str,
        on_event: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> TaskDeps:
        """The task's bindings under ``executor_name``, from git objects only (never a
        worktree); raises :class:`ProvisionRefused`."""
        ...

    def verify(self, deps: TaskDeps) -> None:
        """Re-check the sealed sets ``deps`` cites; raises :class:`ProvisionRefused`
        (``BUNDLE_INTEGRITY``) when one no longer matches its digest."""
        ...


class NullDepsProvider:
    """Provisioning off: the host's environment locally, nothing at all in the sandbox."""

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        return DEPS_MODE_SEALED if executor_name == "docker" else DEPS_MODE_HOST_ENV

    def resolve(
        self,
        repo: GitRepo,
        config: RepoConfig,
        *,
        parent: str,
        gold: str,
        executor_name: str,
        on_event: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> TaskDeps:
        return self.for_executor(executor_name)

    def for_executor(self, executor_name: str) -> TaskDeps:
        """The bindings this provider gives every task under ``executor_name``."""
        return TaskDeps.uniform(NO_DEPS if executor_name == "docker" else HOST_ENV_DEPS)

    def verify(self, deps: TaskDeps) -> None:
        return None


__all__ = [
    "BUNDLE_INTEGRITY",
    "DEPS_HOST_ENV",
    "DEPS_MODES",
    "DEPS_MODE_HOST_ENV",
    "DEPS_MODE_SEALED",
    "DEPS_NONE",
    "HOST_ENV_DEPS",
    "NO_DEPS",
    "REFUSAL_TEXT",
    "RUN_SCOPE_CODES",
    "SCHEME_GO",
    "SCHEME_GO_VENDOR",
    "SCHEME_NODE",
    "SCHEME_PY",
    "SCOPE_RUN",
    "SCOPE_TASK",
    "BundleMount",
    "ClosureViolation",
    "DepsBinding",
    "DepsProvider",
    "NullDepsProvider",
    "ProvisionRefused",
    "Refusal",
    "TaskDeps",
    "refusal",
]
