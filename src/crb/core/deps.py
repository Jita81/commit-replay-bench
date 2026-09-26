"""The seam between qualification and dependency provisioning (ADR-0019).

A task's dependencies belong to the task. They are read from git objects at the parent
and at the gold, fetched OUTSIDE the test container, sealed into a content-addressed
store and mounted read-only into the test container, which keeps ``--network=none``.
On the host (the ``local`` executor) a task may instead use the host's own environment —
a module cache, a virtualenv, ``node_modules`` — which is what this product always used.
This module holds only the vocabulary both sides of that seam speak; it fetches
nothing and decides no verdict:

* :class:`DepsProvider` — ``mode``, ``resolve`` and ``verify``, implemented by
  :mod:`crb.provision` (``make_deps_provider``) and consumed by the qualifier, the grader
  and the worker; :class:`NullDepsProvider` is the provider a caller with no deployment
  settings uses (the host's environment under ``local``, nothing at all under ``docker``);
* :class:`TaskDeps` — the three bindings a task needs (the **parent's** for the
  qualification's RED and baseline, the **gold's** for the gold check and the blame
  witness, and the **builder's**, which is the parent's and never the gold's) and the
  :class:`ClosureSelector` that says which of them a trial's own manifests select;
* :class:`DepsBinding` — what one binding does to a test command: read-only
  :class:`BundleMount` s and the offline environment, for a container (``env``) and for
  the host (``local_env``);
* :class:`BundleMount` — a sealed set on disk. It can only name a path inside a
  registered store under a ``dep_<sha256>`` key, and the executor checks it again
  before it becomes a ``--mount`` (:func:`validate_mount`);
* :class:`ProvisionRefused` — the closed ``PROVISION_*`` / ``BUNDLE_INTEGRITY``
  vocabulary as a :class:`Refusal`: each code with its scope (``run`` stops the run,
  ``task`` skips the task), the fix that names the file, the host or the setting, and
  the guide anchor;
* :class:`ClosureViolation` — a trial whose manifests select something outside the
  task's closure (a disqualification under belt 1b, never a model failure).

Navigation
----------
What it is:   The dependency-provisioning seam: the provider protocol and the null provider,
              the task's three bindings and closure selector, the read-only bundle mount and
              the refusal vocabulary (ADR-0019).
What it does: Names what a sealed dependency set is and how a test command binds it; refuses
              a mount outside a registered store or without a ``dep_`` key; says which of
              the parent's or the gold's set a trial selects, or raises ``ClosureViolation``;
              gives every ``PROVISION_*`` stop its scope and its fix. It never fetches.
How:          Frozen dataclasses and a ``Protocol``; the closure selector reads the trial's
              ``go.mod`` / lockfiles through :mod:`crb.core.provision`'s pure parsers; store
              roots are registered by the store that owns them, and ``validate_mount``
              re-checks a mount's path, key and seal at use.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0005-fail-closed-docker-sandbox.md, docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/core/provision.py (the lockfile readers, keys and closure parsers the
              selector uses), src/crb/provision/__init__.py (``make_deps_provider``: the
              providers behind the protocol), src/crb/provision/store.py (the only maker of a
              real ``BundleMount``), src/crb/core/runners/base.py (``with_deps`` applies a
              binding to a command), src/crb/core/execution.py (renders and re-validates the
              mounts), src/crb/core/qualify.py (qualifies a task with the parent's and the
              gold's bindings), src/crb/core/grade.py (``GradeContext.deps`` and the closure
              check, belt 1b)
Tested by:    tests/test_deps_seam.py, tests/test_provision.py, tests/test_provision_store.py,
              tests/test_execution.py, tests/test_qualify.py
Touch when:   never for a new repository; a new ``PROVISION_*`` code is added to ``REFUSALS``
              with its scope and fix and to the table in docs/DEPLOYMENT.md#34-the-workers-sandbox--choose-deliberately
              and ADR-0019; a new language recipe adds its scheme here and in
              src/crb/core/provision.py.
"""

from __future__ import annotations

import os
import re
import stat
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from crb.core.git import GitRepo
    from crb.core.spec import RepoConfig

SCOPE_RUN = "run"
SCOPE_TASK = "task"

#: Where every refusal's fix is explained at length.
REFUSAL_DOC = "docs/DEPLOYMENT.md#34-the-workers-sandbox--choose-deliberately"

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
PROVISION_UNSAFE_OUTPUT = "PROVISION_UNSAFE_OUTPUT"
#: Task scope: a fact about one commit's TREE — it holds its own dependency tree where the
#: host would read it before the sealed set (a committed ``node_modules``).
PROVISION_TREE_SHADOWS_SET = "PROVISION_TREE_SHADOWS_SET"
#: A sealed set no longer matches its digest (run scope).
BUNDLE_INTEGRITY = "BUNDLE_INTEGRITY"

#: The closed vocabulary: code → (scope, what to do). A code outside it is a
#: programming error (``KeyError``), never a new silent stop.
REFUSALS: Mapping[str, tuple[str, str]] = {
    PROVISION_DISABLED: (
        SCOPE_RUN,
        "switch dependency provisioning on (CRB_PROVISION__ENABLED=true, DEPLOYMENT §3.4), "
        "or measure this repository in the local posture",
    ),
    PROVISION_PUBLIC_REGISTRY: (
        SCOPE_RUN,
        "point CRB_PROVISION__GO_PROXY, CRB_PROVISION__PYPI_INDEX and "
        "CRB_PROVISION__NPM_REGISTRY at your organisation's mirror, or allow the public "
        "registries explicitly with CRB_PROVISION__ALLOW_PUBLIC=true",
    ),
    PROVISION_FETCH_IMAGE_UNPINNED: (
        SCOPE_RUN,
        "pin CRB_PROVISION__GO_IMAGE, CRB_PROVISION__PYTHON_IMAGE and "
        "CRB_PROVISION__NODE_IMAGE by digest (name:tag@sha256:…)",
    ),
    PROVISION_STORE_NOT_VISIBLE: (
        SCOPE_RUN,
        "put CRB_PROVISION__STORE on a path the docker daemon can bind-mount (under colima "
        "or Docker Desktop: a directory under your home; under dind: the shared work volume)",
    ),
    PROVISION_UNSUPPORTED_LANGUAGE: (
        SCOPE_RUN,
        "JVM and Rust repositories are measured in the local posture only in this version "
        "(ADR-0019); set CRB_SANDBOX__EXECUTOR=local for them, on a stamp that says so",
    ),
    PROVISION_NO_LOCK: (
        SCOPE_TASK,
        "commit a pinned lockfile at this commit (go.sum; requirements.txt with name==version "
        "lines, or runner_opts.deps_lock; package-lock.json)",
    ),
    PROVISION_UNPINNED: (
        SCOPE_TASK,
        "pin every dependency exactly in the named file (name==version for pip; an "
        "integrity field on every package-lock.json entry)",
    ),
    PROVISION_SOURCE_REFUSED: (
        SCOPE_TASK,
        "the named line fetches from a URL, a VCS, a path or a foreign registry; publish the "
        "package to your mirror and pin it by version",
    ),
    PROVISION_BUILD_REQUIRED: (
        SCOPE_TASK,
        "the named package must be built or run an install script; for Node name it in "
        "runner_opts.deps_build_scripts, for Python publish a wheel to your mirror",
    ),
    PROVISION_LOCK_UNSUPPORTED: (
        SCOPE_TASK,
        "this lockfile format is not provisioned in this version (go.work, yarn, pnpm, "
        "poetry, uv, pylock, npm lockfileVersion 1); commit a supported lock or use the "
        "local posture",
    ),
    PROVISION_PRIVATE_MODULE: (
        SCOPE_TASK,
        "the named module is private (runner_opts.goprivate) and the public proxy cannot "
        "serve it; point CRB_PROVISION__GO_PROXY at a mirror that holds it",
    ),
    PROVISION_TOOLCHAIN_TOO_OLD: (
        SCOPE_TASK,
        "the go directive is newer than the fetch image's toolchain; re-pin "
        "CRB_PROVISION__GO_IMAGE (and the sandbox image) to a newer Go",
    ),
    PROVISION_FETCH_FAILED: (
        SCOPE_TASK,
        "read the fetch's tail: a denied host goes on CRB_PROVISION__EXTRA_ALLOW_HOSTS, a "
        "missing version goes on your mirror",
    ),
    PROVISION_TOO_LARGE: (
        SCOPE_TASK,
        "the dependency set exceeded CRB_PROVISION__MAX_BUNDLE_MB; raise it if the set is "
        "genuinely that large",
    ),
    PROVISION_UNSAFE_OUTPUT: (
        SCOPE_TASK,
        "a package's install or rebuild step wrote a link that leaves its dependency set; "
        "the set was discarded, not sealed: find the package named and leave it out of "
        "runner_opts.deps_build_scripts, or pin a version that does not do this",
    ),
    PROVISION_TREE_SHADOWS_SET: (
        SCOPE_TASK,
        "this commit's tree holds its own node_modules directory, which Node and npm read "
        "before the sealed set on the host; measure this repository with the docker "
        "executor (the set is mounted over it) or in the local posture",
    ),
    BUNDLE_INTEGRITY: (
        SCOPE_RUN,
        "a sealed dependency set no longer matches its digest: `crb deps verify` names it; "
        "delete that set's directory from the store and the next run fetches and seals it "
        "again",
    ),
}

#: code → (the fix sentence, the guide anchor): the shape the qualifier's code views read.
REFUSAL_TEXT: Mapping[str, tuple[str, str]] = {
    code: (fix, REFUSAL_DOC) for code, (_scope, fix) in REFUSALS.items()
}

#: The codes whose scope is the whole run (a deployment setting or a damaged store).
RUN_SCOPE_CODES: frozenset[str] = frozenset(
    code for code, (scope, _fix) in REFUSALS.items() if scope == SCOPE_RUN
)


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
        """The ``{code, message, fix, doc, scope}`` shape the API serves."""
        return {
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
            "doc": self.doc,
            "scope": self.scope,
        }


def refusal(code: str, message: str, *, fix: str = "") -> Refusal:
    """A :class:`Refusal` with the code's own scope, fix and guide anchor. A code outside
    :data:`REFUSALS` is a programming error (``KeyError``)."""
    scope, default_fix = REFUSALS[code]
    return Refusal(code, message, fix=fix or default_fix, doc=REFUSAL_DOC, scope=scope)


class ProvisionRefused(RuntimeError):
    """A provisioning stop from the closed vocabulary. Raised as
    ``ProvisionRefused(code, message)`` (or with a ready :class:`Refusal`); ``refusal``
    carries it, and ``code`` / ``scope`` / ``message`` / ``fix`` / ``doc`` read it.
    ``scope == "run"`` stops the run; ``"task"`` skips the task."""

    def __init__(self, code: str | Refusal, message: str = "", *, fix: str = "") -> None:
        r = code if isinstance(code, Refusal) else refusal(code, message, fix=fix)
        self.refusal = r
        self.code = r.code
        self.scope = r.scope
        self.message = r.message
        self.fix = r.fix
        self.doc = r.doc
        super().__init__(f"{r.code}: {r.message}")

    def to_dict(self) -> dict[str, str]:
        """The ``{code, message, fix, doc, scope}`` shape the API serves."""
        return self.refusal.to_dict()


class ClosureViolation(ValueError):
    """A trial's manifests select something outside the task's dependency closure (belt
    1b in a provisioned posture): the trial is disqualified, never charged. ``outside``
    names every module/lockfile that stepped outside; ``detail`` is the sentence (given
    as a string, it is the sentence itself)."""

    def __init__(self, outside: Sequence[str] | str, detail: str = "") -> None:
        if isinstance(outside, str):
            self.outside: tuple[str, ...] = ()
            self.detail = outside
        else:
            self.outside = tuple(outside)
            self.detail = f"outside the task's sealed set: {', '.join(self.outside) or detail}"
        super().__init__(f"dependency closure: {self.detail}")


# ---------------------------------------------------------------------------
# Bundle mounts
# ---------------------------------------------------------------------------

#: The only shape a sealed set's directory name may have.
KEY_RE = re.compile(r"^dep_[0-9a-f]{64}$")

#: Where a bundle may appear inside a test container.
MOUNT_TARGETS: tuple[str, ...] = ("/deps/", "/work/node_modules")

_ROOTS_LOCK = threading.Lock()
_STORE_ROOTS: set[Path] = set()


def register_store_root(root: Path) -> Path:
    """Record ``root`` as a bundle store in this process (the store calls this). Only a
    path under a registered root can become a :class:`BundleMount`."""
    resolved = Path(root).resolve()
    with _ROOTS_LOCK:
        _STORE_ROOTS.add(resolved)
    return resolved


def store_roots() -> frozenset[Path]:
    """Every registered store root (resolved)."""
    with _ROOTS_LOCK:
        return frozenset(_STORE_ROOTS)


@dataclass(frozen=True)
class BundleMount:
    """A sealed set mounted read-only: ``host_path`` (``<store>/<lang>/<key>/<sub>``) at
    ``container_path``. Constructed by :meth:`crb.provision.store.BundleStore.mount`
    only; construction validates, and :func:`validate_mount` validates again at use."""

    host_path: Path
    container_path: str
    key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "host_path", Path(self.host_path))
        problem = mount_problem(self, check_seal=False)
        if problem:
            raise ValueError(f"refusing bundle mount: {problem}")

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "container_path": self.container_path}


def mount_problem(mount: BundleMount, *, check_seal: bool = True) -> str:
    """Why ``mount`` may not be mounted, or ``""``. A mount must name a ``dep_<sha256>``
    key, sit inside that key's directory under a registered store root, target
    ``/deps/…`` or ``/work/node_modules``, and — at use (``check_seal``) — exist as a
    directory nobody can write."""
    key = str(getattr(mount, "key", ""))
    if not KEY_RE.fullmatch(key):
        return f"{key!r} is not a dep_<sha256> key"
    target = str(getattr(mount, "container_path", ""))
    if not target.startswith(MOUNT_TARGETS) or ".." in target.split("/"):
        return f"container path {target!r} is not under /deps/ or /work/node_modules"
    try:
        host = Path(mount.host_path).resolve()
    except OSError as exc:  # pragma: no cover - an unresolvable path
        return f"host path unresolvable: {exc}"
    roots = store_roots()
    owner = next((r for r in roots if r == host or r in host.parents), None)
    if owner is None:
        return f"{host} is not inside a registered bundle store"
    rel = host.relative_to(owner).parts
    if len(rel) < 2 or rel[1] != key:
        return f"{host} is not inside the directory of key {key}"
    if check_seal:
        try:
            st = host.stat()
        except OSError:
            return f"{host} does not exist"
        if not stat.S_ISDIR(st.st_mode):
            return f"{host} is not a directory"
        if st.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            return f"{host} is writable: the set is not sealed"
    return ""


def validate_mount(mount: BundleMount) -> None:
    """Raise ``ValueError`` unless ``mount`` passes :func:`mount_problem` with the seal."""
    problem = mount_problem(mount, check_seal=True)
    if problem:
        raise ValueError(f"refusing bundle mount: {problem}")


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------

ROLE_PARENT = "parent"
ROLE_GOLD = "gold"
ROLE_BUILDER = "builder"

#: The binding schemes. ``none`` — nothing mounted, nothing set (the task declares no
#: dependencies, or the sealed posture with nothing provisioned); ``host-env`` — the host's
#: own environment (the ``local`` executor with provisioning off).
SCHEME_NONE = "none"
SCHEME_HOST = "host-env"
SCHEME_GO = "go.modcache.v1"
SCHEME_GO_VENDOR = "go.vendor.v1"
SCHEME_PY = "py.site.v1"
SCHEME_NODE = "node.modules.v1"
#: The names the qualifier and its tests use for the two unsealed schemes.
DEPS_NONE = SCHEME_NONE
DEPS_HOST_ENV = SCHEME_HOST

#: How a posture gets its dependencies — one of the three parts of ``posture_class``.
DEPS_MODE_SEALED = "sealed"
DEPS_MODE_HOST_ENV = "host-env"
DEPS_MODES: tuple[str, ...] = (DEPS_MODE_SEALED, DEPS_MODE_HOST_ENV)


@dataclass(frozen=True)
class DepsBinding:
    """What one dependency set does to a test command.

    ``env`` is for a container (paths under ``/deps`` or ``/work``); ``local_env`` for a
    host command (the store's own paths). ``mounts`` become ``Command.ro_mounts`` and are
    rendered by the docker executor only. ``manifest`` lists what the set holds
    (``module@version``, ``name==version``) — the closure a trial must stay inside.
    """

    role: str = ""
    lang: str = ""
    scheme: str = SCHEME_NONE
    key: str = ""
    digest: str = ""
    mounts: tuple[BundleMount, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    local_env: Mapping[str, str] = field(default_factory=dict)
    manifest: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mounts", tuple(self.mounts))
        object.__setattr__(self, "env", dict(self.env))
        object.__setattr__(self, "local_env", dict(self.local_env))
        object.__setattr__(self, "manifest", tuple(self.manifest))

    @property
    def sealed(self) -> bool:
        """A provisioned set (not "no dependencies", not the host's own setup)."""
        return self.scheme not in {SCHEME_NONE, SCHEME_HOST}

    def env_for(self, executor_name: str) -> dict[str, str]:
        """The variables for a command run by ``executor_name``."""
        return dict(self.env if executor_name == "docker" else self.local_env)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "lang": self.lang,
            "scheme": self.scheme,
            "key": self.key,
            "digest": self.digest,
            "mounts": [m.to_dict() for m in self.mounts],
        }


def empty_binding(role: str, lang: str = "", scheme: str = SCHEME_NONE) -> DepsBinding:
    """A binding that changes nothing (no dependencies, or the host's own setup)."""
    return DepsBinding(role=role, lang=lang, scheme=scheme)


#: Nothing mounted, nothing set: the sealed posture with nothing provisioned.
NO_DEPS = DepsBinding(scheme=SCHEME_NONE)
#: The host's own environment: the ``local`` executor, as this product always ran.
HOST_ENV_DEPS = DepsBinding(scheme=SCHEME_HOST)


class Selector(Protocol):
    """Which of the task's sets a trial tree selects: ``"parent"`` or ``"gold"``, or
    :class:`ClosureViolation`."""

    def select(self, root: Path) -> str: ...


@dataclass(frozen=True)
class ClosureSelector:
    """Which sealed set a trial's own manifests select.

    Go: the trial's ``go.mod`` requires must all be in ``modules`` (the sealed
    manifest's ``module@version`` set) → the one cache that holds the parent's and the
    gold's modules together. Python / Node: the trial's lock key must be the parent's or
    the gold's (``lock_keys``: role → key, computed over ``lock_paths`` for that role).
    Anything else is :class:`ClosureViolation`.
    """

    lang: str
    modules: frozenset[str] = frozenset()
    lock_keys: Mapping[str, str] = field(default_factory=dict)
    lock_paths: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def select(self, root: Path) -> str:
        """``"parent"`` or ``"gold"`` for the trial tree at ``root``; raises otherwise."""
        from crb.core import provision  # noqa: PLC0415 — provision imports this module

        return provision.select_role(self, Path(root))


@dataclass(frozen=True)
class TaskDeps:
    """A task's dependencies: the parent's, the gold's and the builder's bindings and the
    closure selector. ``mode`` is the provider's (``sealed`` / ``host-env``)."""

    mode: str
    lang: str
    parent: DepsBinding
    gold: DepsBinding
    builder: DepsBinding
    selector: Selector | None = field(default=None, compare=False)
    refusal: ProvisionRefused | None = field(default=None, compare=False)

    @classmethod
    def uniform(cls, binding: DepsBinding, *, mode: str = "", lang: str = "") -> TaskDeps:
        """One binding serving all three roles (the null provider's shape). ``mode``
        defaults to ``host-env`` for the host's binding and ``sealed`` otherwise."""
        m = mode or (DEPS_MODE_HOST_ENV if binding.scheme == SCHEME_HOST else DEPS_MODE_SEALED)
        return cls(m, lang or binding.lang, binding, binding, binding)

    @property
    def scheme(self) -> str:
        """The scheme of the set a trial is graded with by default (the gold's)."""
        return self.gold.scheme

    @property
    def keys(self) -> tuple[str, ...]:
        """Every distinct sealed key the task cites (what a qualification records)."""
        seen: dict[str, None] = {}
        for b in (self.parent, self.gold, self.builder):
            if b.key:
                seen[b.key] = None
        return tuple(seen)

    @property
    def digests(self) -> dict[str, str]:
        """key → output digest, for every sealed set the task cites."""
        return {b.key: b.digest for b in (self.parent, self.gold, self.builder) if b.key}

    def binding_for(self, root: Path) -> DepsBinding:
        """The binding a trial at ``root`` is graded with — the set its own manifests
        select. ``ClosureViolation`` when they select something outside the closure. With
        no selector (nothing provisioned) the gold's binding serves every trial."""
        if self.selector is None:
            return self.gold
        role = self.selector.select(Path(root))
        return self.parent if role == ROLE_PARENT else self.gold

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "lang": self.lang,
            "keys": list(self.keys),
            "digests": self.digests,
            "parent": self.parent.to_dict(),
            "gold": self.gold.to_dict(),
            "builder": self.builder.to_dict(),
        }


#: ``on_event(action, payload)`` — how a provider reports reuse, fetch, seal and refusal.
EventFn = Callable[[str, Mapping[str, Any]], None]


class DepsProvider(Protocol):
    """What the qualifier, the grader and the worker ask of provisioning (ADR-0019 §6).

    ``mode`` is the dependency part of the posture class. ``resolve`` reads the lockfiles
    at ``parent`` and ``gold`` from ``repo``'s object store (never a worktree) and returns
    the task's :class:`TaskDeps`, fetching and sealing on a store miss; it raises
    :class:`ProvisionRefused` with the code. ``verify`` re-hashes every sealed set a
    task cites (``BUNDLE_INTEGRITY`` on a mismatch)."""

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        """``sealed`` or ``host-env`` — the dependency part of the posture class."""
        ...

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
        """The task's bindings, from git objects only; raises :class:`ProvisionRefused`."""
        ...

    def verify(self, deps: TaskDeps) -> None:
        """Re-check the sealed sets ``deps`` cites; raises :class:`ProvisionRefused`
        (``BUNDLE_INTEGRITY``) when one no longer matches its digest."""
        ...


class NullDepsProvider:
    """No provisioning and no lockfile reading: the host's environment under ``local``,
    nothing at all under ``docker`` (a task whose parent then cannot load its
    dependencies offline is refused ``QUAL_ENV_UNLOADABLE`` at qualification). What a
    caller with no deployment settings uses; a deployment's provider comes from
    :func:`crb.provision.make_deps_provider`."""

    def mode(self, config: RepoConfig, executor_name: str) -> str:
        return DEPS_MODE_SEALED if executor_name == "docker" else DEPS_MODE_HOST_ENV

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
        return self.for_executor(executor_name)

    def for_executor(self, executor_name: str) -> TaskDeps:
        """The bindings this provider gives every task under ``executor_name``."""
        return TaskDeps.uniform(NO_DEPS if executor_name == "docker" else HOST_ENV_DEPS)

    def verify(self, deps: TaskDeps) -> None:
        return None


def host_env_deps(lang: str = "") -> TaskDeps:
    """The local posture with provisioning off: the host's own setup, nothing bound."""
    b = {r: empty_binding(r, lang, SCHEME_HOST) for r in (ROLE_PARENT, ROLE_GOLD, ROLE_BUILDER)}
    return TaskDeps(DEPS_MODE_HOST_ENV, lang, b[ROLE_PARENT], b[ROLE_GOLD], b[ROLE_BUILDER])


def no_deps(mode: str, lang: str = "") -> TaskDeps:
    """A task that declares no dependencies: sealed and empty."""
    b = {r: empty_binding(r, lang) for r in (ROLE_PARENT, ROLE_GOLD, ROLE_BUILDER)}
    return TaskDeps(mode, lang, b[ROLE_PARENT], b[ROLE_GOLD], b[ROLE_BUILDER])


def is_secret_like(name: str) -> bool:
    """Variable names that look like credentials (never passed into a fetch)."""
    return bool(re.search(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", name, re.IGNORECASE))


def worker_user() -> str:
    """The worker's own ``uid:gid`` (a fetch writes files the worker can seal)."""
    return f"{os.getuid()}:{os.getgid()}"


__all__ = [
    "BUNDLE_INTEGRITY",
    "DEPS_HOST_ENV",
    "DEPS_MODES",
    "DEPS_MODE_HOST_ENV",
    "DEPS_MODE_SEALED",
    "DEPS_NONE",
    "HOST_ENV_DEPS",
    "KEY_RE",
    "NO_DEPS",
    "PROVISION_BUILD_REQUIRED",
    "PROVISION_DISABLED",
    "PROVISION_FETCH_FAILED",
    "PROVISION_FETCH_IMAGE_UNPINNED",
    "PROVISION_LOCK_UNSUPPORTED",
    "PROVISION_NO_LOCK",
    "PROVISION_PRIVATE_MODULE",
    "PROVISION_PUBLIC_REGISTRY",
    "PROVISION_SOURCE_REFUSED",
    "PROVISION_STORE_NOT_VISIBLE",
    "PROVISION_TOOLCHAIN_TOO_OLD",
    "PROVISION_TOO_LARGE",
    "PROVISION_TREE_SHADOWS_SET",
    "PROVISION_UNPINNED",
    "PROVISION_UNSAFE_OUTPUT",
    "PROVISION_UNSUPPORTED_LANGUAGE",
    "REFUSALS",
    "REFUSAL_DOC",
    "REFUSAL_TEXT",
    "ROLE_BUILDER",
    "ROLE_GOLD",
    "ROLE_PARENT",
    "RUN_SCOPE_CODES",
    "SCHEME_GO",
    "SCHEME_GO_VENDOR",
    "SCHEME_HOST",
    "SCHEME_NODE",
    "SCHEME_NONE",
    "SCHEME_PY",
    "SCOPE_RUN",
    "SCOPE_TASK",
    "BundleMount",
    "ClosureSelector",
    "ClosureViolation",
    "DepsBinding",
    "DepsProvider",
    "EventFn",
    "NullDepsProvider",
    "ProvisionRefused",
    "Refusal",
    "Selector",
    "TaskDeps",
    "empty_binding",
    "host_env_deps",
    "is_secret_like",
    "mount_problem",
    "no_deps",
    "refusal",
    "register_store_root",
    "store_roots",
    "validate_mount",
    "worker_user",
]
