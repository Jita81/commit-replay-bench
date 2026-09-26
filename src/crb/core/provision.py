"""Dependency inputs, read from git objects and never from a worktree (ADR-0019).

What a task's dependencies ARE is decided here, purely, before any container exists and
before any builder has touched a tree:

* :meth:`LockInputs.from_git` reads one commit's lockfiles with
  :meth:`~crb.core.git.GitRepo.show_blob` — the exact bytes in the object store. The API
  takes ``(repo, sha)`` and never a path on disk, so nothing a builder writes into a
  worktree can change what is fetched. ``.npmrc``, ``pip.conf`` and ``go.env`` are never
  read: a repository cannot configure the fetch.
* Every refusal is a :class:`~crb.core.deps.ProvisionRefused` with its code — a URL, VCS,
  path or foreign-registry source, an unpinned version, ``go.work``, a lock format this
  version does not provision, a package that must be built, a language that is not
  provisioned at all.
* :func:`bundle_key` addresses a sealed set by its recipe, the fetch image's ID and the
  lockfile blob hashes. Go has ONE key over the union of the parent's and the gold's
  blobs (one module cache holds both — the D4 finding) and a parent-only key for the
  builder; Python and Node have one key per lockfile set.
* :func:`select_role` is the closure: a trial's own manifests (read from the trial tree —
  selection is not fetching) must select the parent's or the gold's set, or it raises
  :class:`~crb.core.deps.ClosureViolation` naming what was outside.

Navigation
----------
What it is:   The pure half of dependency provisioning: lockfile readers over git objects, the
              refusal rules, the content-addressed bundle key and the closure selector.
What it does: Reads ``go.mod``/``go.sum`` (and a local replace target's ``go.mod``),
              pinned ``requirements*.txt`` (following ``-r``) or ``runner_opts.deps_lock``,
              and ``package.json`` + ``package-lock.json`` at a commit; refuses every source
              the ADR refuses; computes the bundle keys; says which set a trial selects.
How:          ``GitRepo.show_blob`` / ``tree_names`` → per-language parser → ``LockInputs``
              (files + parsed pins) → ``bundle_key`` over sorted blob hashes →
              ``ClosureSelector`` (``crb.core.deps``) → ``select_role`` on a trial tree.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/deps.py (the seam types and the refusal vocabulary),
              src/crb/core/git.py (``show_blob``: the object store is the only input),
              src/crb/provision/__init__.py (the providers that fetch what this reads),
              src/crb/core/runners/node_runners.py (``lock_key``: the same normalisation of a
              Node lockfile, for the host's eras), src/crb/core/spec.py (``RepoConfig.runner`` and ``runner_opts``)
Tested by:    tests/test_provision.py
Touch when:   a lock format becomes provisioned (a parser here, a recipe under
              src/crb/provision/, and a row in docs/DEPLOYMENT.md §3.4); never for a new
              repository — its lockfiles are read as committed.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from crb.core.deps import (
    ROLE_GOLD,
    ROLE_PARENT,
    SCHEME_GO,
    SCHEME_GO_VENDOR,
    SCHEME_NODE,
    SCHEME_NONE,
    SCHEME_PY,
    ClosureSelector,
    ClosureViolation,
    ProvisionRefused,
)

if TYPE_CHECKING:  # pragma: no cover
    from crb.core.git import GitRepo
    from crb.core.spec import RepoConfig

LANG_GO = "go"
LANG_PYTHON = "python"
LANG_NODE = "node"

#: Recipes (the first input of every bundle key: a recipe change is a new set). A recipe is
#: the binding scheme of the set it makes (``crb.core.deps.SCHEME_*``).
RECIPE_GO = SCHEME_GO
RECIPE_GO_VENDOR = SCHEME_GO_VENDOR
RECIPE_PY = SCHEME_PY
RECIPE_NODE = SCHEME_NODE
RECIPE_NONE = SCHEME_NONE

_RUNNER_LANG: Mapping[str, str] = {
    "go": LANG_GO,
    "pytest": LANG_PYTHON,
    "node": LANG_NODE,
    "vitest": LANG_NODE,
    "jest": LANG_NODE,
    "mocha": LANG_NODE,
}

#: Files a repository might use to configure a fetch. They are never read.
NEVER_READ: frozenset[str] = frozenset({".npmrc", "pip.conf", "go.env", ".pypirc", ".yarnrc"})

DEFAULT_NPM_REGISTRY_HOST = "registry.npmjs.org"


def lang_of(config: RepoConfig) -> str:
    """``go`` / ``python`` / ``node`` for a provisioned runner; JVM and Rust are refused
    with run scope (``PROVISION_UNSUPPORTED_LANGUAGE``)."""
    lang = _RUNNER_LANG.get(config.runner)
    if lang is None:
        raise ProvisionRefused(
            "PROVISION_UNSUPPORTED_LANGUAGE",
            f"runner {config.runner!r} ({config.language}) has no dependency recipe",
        )
    return lang


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class LockFile:
    """One input file: its repository-relative path and exact bytes."""

    path: str
    data: bytes

    @property
    def sha256(self) -> str:
        return sha256_hex(self.data)


class _Reader:
    """Reads blobs at one commit; refuses the configuration files a repository might
    use to steer a fetch. Every read goes through the object store."""

    def __init__(self, repo: GitRepo, sha: str) -> None:
        self.repo = repo
        self.sha = sha

    def blob(self, path: str) -> bytes | None:
        name = posixpath.basename(path)
        if name in NEVER_READ:  # pragma: no cover - guarded by construction, pinned by a test
            raise AssertionError(f"refusing to read repository configuration {path!r}")
        return self.repo.show_blob(self.sha, path)

    def names(self, directory: str = "") -> list[str]:
        return self.repo.tree_names(self.sha, directory)


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoMod:
    """The parts of a ``go.mod`` provisioning needs."""

    module: str = ""
    go: str = ""
    requires: tuple[tuple[str, str], ...] = ()
    #: (old path, old version or "", new path, new version or "")
    replaces: tuple[tuple[str, str, str, str], ...] = ()

    def local_replaces(self) -> tuple[str, ...]:
        """Replacement targets that are directories in the repository."""
        return tuple(new for _, _, new, nv in self.replaces if not nv and _is_local_path(new))

    def resolved_requires(self) -> tuple[str, ...]:
        """``module@version`` for every requirement after non-local replacements; a
        requirement replaced by a local directory is not a module fetch."""
        out: list[str] = []
        for path, version in self.requires:
            target = (path, version)
            for old, ov, new, nv in self.replaces:
                if old == path and (not ov or ov == version):
                    target = ("", "") if not nv and _is_local_path(new) else (new, nv)
                    break
            if target[0]:
                out.append(f"{target[0]}@{target[1]}")
        return tuple(sorted(set(out)))


def _is_local_path(p: str) -> bool:
    return p.startswith(("./", "../", "/")) or p in {".", ".."}


_GO_COMMENT = re.compile(r"//.*$")


def _unquote(tok: str) -> str:
    return tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in '"`' else tok


def parse_go_mod(text: str) -> GoMod:
    """A stdlib parser of ``module``, ``go``, ``require`` and ``replace`` (single lines and
    parenthesised blocks). Comments (``// indirect``) are dropped."""
    module = go = ""
    requires: list[tuple[str, str]] = []
    replaces: list[tuple[str, str, str, str]] = []
    block = ""
    for raw in text.splitlines():
        line = _GO_COMMENT.sub("", raw).strip()
        if not line:
            continue
        if block:
            if line == ")":
                block = ""
                continue
            _go_directive(block, line, requires, replaces)
            continue
        verb, _, rest = line.partition(" ")
        rest = rest.strip()
        if verb in {"require", "replace", "exclude", "retract", "tool", "godebug", "ignore"}:
            if rest == "(":
                block = verb
                continue
            _go_directive(verb, rest, requires, replaces)
        elif verb == "module":
            module = _unquote(rest)
        elif verb == "go":
            go = rest
    return GoMod(module, go, tuple(requires), tuple(replaces))


def _go_directive(
    verb: str,
    rest: str,
    requires: list[tuple[str, str]],
    replaces: list[tuple[str, str, str, str]],
) -> None:
    if verb == "require":
        parts = rest.split()
        if len(parts) >= 2:
            requires.append((_unquote(parts[0]), parts[1]))
    elif verb == "replace":
        left, arrow, right = rest.partition("=>")
        if not arrow:
            return
        lp, rp = left.split(), right.split()
        if not lp or not rp:
            return
        replaces.append(
            (
                _unquote(lp[0]),
                lp[1] if len(lp) > 1 else "",
                _unquote(rp[0]),
                rp[1] if len(rp) > 1 else "",
            )
        )


def go_version_tuple(v: str) -> tuple[int, ...]:
    """``"1.26.8"`` → ``(1, 26, 8)``; ``"1.22"`` → ``(1, 22, 0)``; junk → ``()``."""
    m = re.match(r"^(?:go)?(\d+)\.(\d+)(?:\.(\d+))?", v.strip())
    if not m:
        return ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _read_go(reader: _Reader) -> tuple[str, tuple[LockFile, ...], GoMod, dict[str, GoMod]]:
    if reader.blob("go.work") is not None:
        raise ProvisionRefused(
            "PROVISION_LOCK_UNSUPPORTED", "go.work at the repository root is not provisioned"
        )
    gomod_bytes = reader.blob("go.mod")
    if gomod_bytes is None:
        return RECIPE_NONE, (), GoMod(), {}
    gomod = parse_go_mod(gomod_bytes.decode("utf-8", "replace"))
    files = [LockFile("go.mod", gomod_bytes)]
    if reader.blob("vendor/modules.txt") is not None:
        return RECIPE_GO_VENDOR, tuple(files), gomod, {}
    locals_: dict[str, GoMod] = {}
    for target in gomod.local_replaces():
        rel = posixpath.normpath(target)
        if target.startswith("/") or rel == ".." or rel.startswith("../"):
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED",
                f"go.mod: replace => {target} points outside the repository",
            )
        sub = reader.blob(posixpath.join(rel, "go.mod"))
        if sub is None:
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED",
                f"go.mod: replace => {target} has no go.mod at this commit",
            )
        files.append(LockFile(posixpath.join(rel, "go.mod"), sub))
        locals_[rel] = parse_go_mod(sub.decode("utf-8", "replace"))
    fetched = set(gomod.resolved_requires())
    for sub_mod in locals_.values():
        fetched |= set(sub_mod.resolved_requires())
    if not fetched:
        return RECIPE_NONE, tuple(files), gomod, locals_
    gosum = reader.blob("go.sum")
    if gosum is None:
        raise ProvisionRefused(
            "PROVISION_NO_LOCK", "go.mod requires modules but go.sum is not committed"
        )
    files.append(LockFile("go.sum", gosum))
    return RECIPE_GO, tuple(files), gomod, locals_


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\[[^\]]*\])?\s*"
    r"==\s*(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_-]*)\s*(?P<marker>;.*)?$"
)
_RANGE = re.compile(r"(>=|<=|~=|!=|===|>|<|==\s*[^\s;]*\*)")
_PY_SOURCE_OPTS = (
    "-e",
    "--editable",
    "-i",
    "--index-url",
    "--extra-index-url",
    "-f",
    "--find-links",
    "--trusted-host",
    "--no-index",
)
_PY_ALT_LOCKS: tuple[str, ...] = ("uv.lock", "poetry.lock", "pylock.toml", "Pipfile.lock")


@dataclass(frozen=True)
class PyPin:
    """One ``name==version`` line (with its committed hashes, if any)."""

    name: str
    version: str
    hashes: tuple[str, ...] = ()
    marker: str = ""
    source: str = ""  # "file:line"

    @property
    def norm(self) -> str:
        return re.sub(r"[-_.]+", "-", self.name).lower()


def _logical_lines(text: str) -> Iterable[tuple[int, str]]:
    buf, start = "", 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not buf:
            start = n
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        yield start, buf
        buf = ""
    if buf:
        yield start, buf


def _strip_comment(line: str) -> str:
    # pip: a comment starts at "#" at line start or after whitespace (a URL fragment is not one)
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()


def parse_requirements(
    reader: _Reader, path: str, *, seen: set[str] | None = None
) -> tuple[list[LockFile], list[PyPin]]:
    """Read ``path`` and its ``-r`` includes through git objects. Only ``name==version``
    (with optional ``--hash`` options and markers) is accepted."""
    seen = set() if seen is None else seen
    norm = posixpath.normpath(path)
    if norm in seen:
        return [], []
    seen.add(norm)
    if norm.startswith("../") or norm.startswith("/"):
        raise ProvisionRefused(
            "PROVISION_SOURCE_REFUSED", f"{path}: an include outside the repository"
        )
    data = reader.blob(norm)
    if data is None:
        raise ProvisionRefused("PROVISION_NO_LOCK", f"{norm} is not committed at this commit")
    files = [LockFile(norm, data)]
    pins: list[PyPin] = []
    base = posixpath.dirname(norm)
    for lineno, logical in _logical_lines(data.decode("utf-8", "replace")):
        line = _strip_comment(logical)
        if not line:
            continue
        where = f"{norm}:{lineno}"
        m_inc = re.match(r"^(?:-r|--requirement)(?:\s*=\s*|\s+|(?=\S))(\S+)$", line)
        if m_inc:
            sub_files, sub_pins = parse_requirements(
                reader, posixpath.join(base, m_inc.group(1)), seen=seen
            )
            files += sub_files
            pins += sub_pins
            continue
        if line.startswith("-"):
            opt = line.split()[0].split("=")[0]
            if opt in _PY_SOURCE_OPTS:
                raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{where}: {opt} is refused")
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED", f"{where}: the option {opt} is not supported"
            )
        hashes = tuple(re.findall(r"--hash[=\s]+(sha256:[0-9a-fA-F]{64})", line))
        spec = re.split(r"\s--hash", line, maxsplit=1)[0].strip()
        if (
            "://" in spec
            or " @ " in spec
            or spec.startswith((".", "/"))
            or spec.endswith((".whl", ".tar.gz", ".zip"))
        ):
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED", f"{where}: {spec!r} is a URL, VCS or path source"
            )
        m = _PIN.match(spec)
        if not m or _RANGE.search(spec.split(";")[0]):
            raise ProvisionRefused("PROVISION_UNPINNED", f"{where}: {spec!r} is not name==version")
        pins.append(
            PyPin(m.group("name"), m.group("version"), hashes, (m.group("marker") or ""), where)
        )
    return files, pins


def _py_declares(reader: _Reader) -> bool:
    if any(reader.blob(f) is not None for f in ("setup.py", "setup.cfg")):
        return True
    raw = reader.blob("pyproject.toml")
    if raw is None:
        return False
    try:
        data = tomllib.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return False
    project = data.get("project")
    if not isinstance(project, dict):
        return False
    return bool(project.get("dependencies")) or bool(project.get("optional-dependencies"))


def _read_python(
    reader: _Reader, config: RepoConfig
) -> tuple[str, tuple[LockFile, ...], tuple[PyPin, ...]]:
    declared = config.runner_opts.get("deps_lock")
    if isinstance(declared, str):
        declared = [declared]
    names = reader.names()
    paths = (
        [str(p) for p in declared]
        if declared
        else sorted(n for n in names if re.fullmatch(r"requirements[\w.-]*\.txt", n))
    )
    if not paths:
        alt = [n for n in _PY_ALT_LOCKS if n in names]
        if alt:
            raise ProvisionRefused(
                "PROVISION_LOCK_UNSUPPORTED",
                f"{alt[0]} is not provisioned in this version; commit a pinned requirements "
                "lock (or name one in runner_opts.deps_lock)",
            )
        if _py_declares(reader):
            raise ProvisionRefused(
                "PROVISION_NO_LOCK",
                "the project declares dependencies but no requirements lock is committed",
            )
        return RECIPE_NONE, (), ()
    files: list[LockFile] = []
    pins: list[PyPin] = []
    seen: set[str] = set()
    for p in paths:
        f, pn = parse_requirements(reader, p, seen=seen)
        files += f
        pins += pn
    if not pins:
        return RECIPE_NONE, tuple(files), ()
    return RECIPE_PY, tuple(files), tuple(pins)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodePkg:
    """One ``packages`` entry of a ``package-lock.json`` (v2+)."""

    path: str
    name: str
    version: str
    integrity: str
    install_script: bool = False


def _node_name(key: str) -> str:
    return key.rsplit("node_modules/", 1)[-1]


def _read_node(
    reader: _Reader, config: RepoConfig, registry_host: str
) -> tuple[str, tuple[LockFile, ...], tuple[NodePkg, ...]]:
    pkg_bytes = reader.blob("package.json")
    if pkg_bytes is None:
        return RECIPE_NONE, (), ()
    try:
        pkg = json.loads(pkg_bytes.decode("utf-8", "replace"))
    except ValueError as exc:
        raise ProvisionRefused("PROVISION_NO_LOCK", f"package.json is not JSON: {exc}") from exc
    declares = isinstance(pkg, dict) and any(
        isinstance(pkg.get(k), dict) and pkg[k]
        for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
    )
    lock_name = next(
        (n for n in ("package-lock.json", "npm-shrinkwrap.json") if reader.blob(n) is not None),
        "",
    )
    if not lock_name:
        other = next((n for n in ("yarn.lock", "pnpm-lock.yaml") if reader.blob(n)), "")
        if other:
            raise ProvisionRefused(
                "PROVISION_LOCK_UNSUPPORTED", f"{other} is not provisioned in this version"
            )
        if declares:
            raise ProvisionRefused(
                "PROVISION_NO_LOCK",
                "package.json declares dependencies but no lockfile is committed",
            )
        return RECIPE_NONE, (LockFile("package.json", pkg_bytes),), ()
    lock_bytes = reader.blob(lock_name) or b""
    try:
        lock = json.loads(lock_bytes.decode("utf-8", "replace"))
    except ValueError as exc:
        raise ProvisionRefused("PROVISION_UNPINNED", f"{lock_name} is not JSON: {exc}") from exc
    version = int(lock.get("lockfileVersion") or 1) if isinstance(lock, dict) else 1
    packages = lock.get("packages") if isinstance(lock, dict) else None
    if version < 2 or not isinstance(packages, dict):
        raise ProvisionRefused(
            "PROVISION_LOCK_UNSUPPORTED",
            f"{lock_name} is lockfileVersion {version}; version 2 or later is required",
        )
    allowed_scripts = {str(p) for p in (config.runner_opts.get("deps_build_scripts") or [])}
    out: list[NodePkg] = []
    for key, entry in sorted(packages.items()):
        if not key or not isinstance(entry, dict):
            continue
        where = f"{lock_name}: {key}"
        if entry.get("link"):
            raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{where} is a link entry")
        if entry.get("inBundle"):
            continue  # shipped inside its parent's tarball, covered by the parent's integrity
        resolved = str(entry.get("resolved") or "")
        if resolved.startswith(("file:", "git", "link:")) or (
            resolved and not resolved.startswith("https://")
        ):
            raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{where} resolves to {resolved!r}")
        host = (urlsplit(resolved).hostname or "") if resolved else ""
        if resolved and host != registry_host:
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED",
                f"{where} resolves from {host!r}, not the configured registry {registry_host!r}",
            )
        integrity = str(entry.get("integrity") or "")
        if not integrity:
            raise ProvisionRefused("PROVISION_UNPINNED", f"{where} has no integrity field")
        name = str(entry.get("name") or _node_name(key))
        if entry.get("hasInstallScript") and name not in allowed_scripts:
            raise ProvisionRefused(
                "PROVISION_BUILD_REQUIRED",
                f"{where} runs an install script; name {name!r} in "
                "runner_opts.deps_build_scripts to rebuild it without a network",
            )
        out.append(
            NodePkg(
                key,
                name,
                str(entry.get("version") or ""),
                integrity,
                bool(entry.get("hasInstallScript")),
            )
        )
    files = (LockFile("package.json", pkg_bytes), LockFile(lock_name, lock_bytes))
    if not out:
        return RECIPE_NONE, files, ()
    return RECIPE_NODE, files, tuple(out)


# ---------------------------------------------------------------------------
# The inputs of one commit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LockInputs:
    """One commit's dependency inputs, read from git objects.

    ``recipe`` is ``none`` when the commit declares nothing to fetch. ``files`` are the
    exact blobs (hashed into the key); ``pins`` what they pin (``module@version``,
    ``name==version``, ``name@version``)."""

    lang: str
    sha: str
    recipe: str
    files: tuple[LockFile, ...] = ()
    pins: tuple[str, ...] = ()
    go_mod: GoMod | None = None
    local_mods: Mapping[str, GoMod] = field(default_factory=dict)
    py_pins: tuple[PyPin, ...] = ()
    node_pkgs: tuple[NodePkg, ...] = ()

    @classmethod
    def from_git(
        cls,
        repo: GitRepo,
        sha: str,
        config: RepoConfig,
        *,
        npm_registry_host: str = DEFAULT_NPM_REGISTRY_HOST,
    ) -> LockInputs:
        """Read ``sha``'s lockfiles from ``repo``'s object store (never a worktree)."""
        lang = lang_of(config)
        reader = _Reader(repo, sha)
        if lang == LANG_GO:
            recipe, files, gomod, locals_ = _read_go(reader)
            pins = set(gomod.resolved_requires())
            for m in locals_.values():
                pins |= set(m.resolved_requires())
            return cls(lang, sha, recipe, files, tuple(sorted(pins)), gomod, dict(locals_))
        if lang == LANG_PYTHON:
            recipe, files, py = _read_python(reader, config)
            return cls(
                lang,
                sha,
                recipe,
                files,
                tuple(sorted(f"{p.norm}=={p.version}" for p in py)),
                py_pins=py,
            )
        recipe, files, node = _read_node(reader, config, npm_registry_host)
        return cls(
            lang,
            sha,
            recipe,
            files,
            tuple(sorted(f"{p.name}@{p.version}" for p in node)),
            node_pkgs=node,
        )

    @property
    def declares_dependencies(self) -> bool:
        """Something must be fetched (a vendored Go tree needs nothing fetched but is
        still a dependency scheme)."""
        return self.recipe != RECIPE_NONE

    @property
    def blobs(self) -> tuple[str, ...]:
        return tuple(sorted(f.sha256 for f in self.files))

    @property
    def lock_key(self) -> str:
        """The identity of this commit's lock set, computed as :func:`tree_lock_key` would
        compute it from the same files on disk."""
        return files_lock_key(self.lang, {f.path: f.data for f in self.files})

    @property
    def lock_paths(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.files)

    @property
    def require_hashes(self) -> bool:
        """Python: every pin carries a committed hash (``--require-hashes``)."""
        return bool(self.py_pins) and all(p.hashes for p in self.py_pins)


def bundle_key(recipe: str, fetch_image_id: str, blobs: Iterable[str]) -> str:
    """``dep_`` + sha256 over the recipe, the fetch image's ID and the sorted blob hashes."""
    h = hashlib.sha256()
    h.update(recipe.encode())
    h.update(b"\0")
    h.update(fetch_image_id.encode())
    h.update(b"\0")
    for b in sorted(blobs):
        h.update(b.encode() + b"\n")
    return "dep_" + h.hexdigest()


def go_keys(parent: LockInputs, gold: LockInputs, fetch_image_id: str) -> tuple[str, str]:
    """``(union key, parent-only key)``: one module cache for the parent's and the gold's
    modules together (the gold commit's go.sum differs from its parent's — D4), and the
    builder's parent-only set (the same key when the lockfiles did not change)."""
    union = bundle_key(RECIPE_GO, fetch_image_id, {*parent.blobs, *gold.blobs})
    parent_only = bundle_key(RECIPE_GO, fetch_image_id, parent.blobs)
    return union, parent_only


#: The files a Node lock key is taken from, first present wins — the same names on the
#: git side (:func:`files_lock_key`) and on the trial's tree (:func:`tree_lock_key`).
_NODE_LOCK_NAMES: tuple[str, ...] = ("package-lock.json", "npm-shrinkwrap.json", "package.json")


def files_lock_key(lang: str, files: Mapping[str, bytes]) -> str:
    """The lock identity of a set of files (path → bytes). Node reuses
    :func:`crb.core.runners.node_runners.lock_key`'s normalisation (the first lockfile's
    sha256, 16 hex); Python hashes every lock file with its path."""
    if lang == LANG_NODE:
        for name in _NODE_LOCK_NAMES:
            if name in files:
                return sha256_hex(files[name])[:16]
        return ""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode() + b"\0" + sha256_hex(files[path]).encode() + b"\n")
    return h.hexdigest()[:16]


def tree_lock_key(lang: str, root: Path, paths: Sequence[str]) -> str:
    """:func:`files_lock_key` over ``paths`` as they stand in the trial tree ``root``. Node
    keys on the first lockfile present, read through :func:`_trial_manifest`: a lockfile
    that is a link, or that leaves the tree, is a :class:`ClosureViolation` and is never
    read (the same rule as Go's ``go.mod``)."""
    if lang == LANG_NODE:
        for name in _NODE_LOCK_NAMES:
            f = _trial_manifest(Path(root), name)
            if f is not None:
                return files_lock_key(lang, {name: f.read_bytes()})
        return ""
    files: dict[str, bytes] = {}
    for p in paths:
        f = _inside(Path(root), p)  # a link out of the tree reads as absent
        if f is not None:
            files[p] = f.read_bytes()
    return files_lock_key(lang, files)


def closure_selector(
    lang: str,
    *,
    modules: Iterable[str] = (),
    parent: LockInputs | None = None,
    gold: LockInputs | None = None,
) -> ClosureSelector:
    """The selector a task's :class:`~crb.core.deps.TaskDeps` carries: Go by the sealed
    manifest's ``module@version`` set; Python/Node by the parent's and the gold's lock
    keys."""
    if lang == LANG_GO:
        return ClosureSelector(lang, modules=frozenset(modules))
    keys: dict[str, str] = {}
    paths: dict[str, tuple[str, ...]] = {}
    for role, inputs in ((ROLE_PARENT, parent), (ROLE_GOLD, gold)):
        if inputs is not None:
            keys[role] = inputs.lock_key
            paths[role] = inputs.lock_paths
    return ClosureSelector(lang, lock_keys=keys, lock_paths=paths)


def _inside(root: Path, rel: str) -> Path | None:
    """``root / rel`` when it is a regular file that is not a link and resolves inside
    ``root``; else ``None``. The trial tree is the builder's: nothing it names is read
    from outside it."""
    p = root / rel
    if p.is_symlink() or not p.is_file():
        return None
    base = root.resolve()
    real = p.resolve()
    return p if base in real.parents else None


def _trial_manifest(root: Path, rel: str) -> Path | None:
    """The trial's ``rel`` to read, ``None`` when it is absent, or
    :class:`ClosureViolation` when it is a link or leaves the tree."""
    p = root / rel
    if not p.is_symlink() and not p.exists():
        return None
    ok = _inside(root, rel)
    if ok is None:
        raise ClosureViolation(f"{rel} is a link or is not a file inside the trial's tree")
    return ok


def select_role(selector: ClosureSelector, root: Path) -> str:
    """``"parent"`` or ``"gold"`` for the trial at ``root``, or :class:`ClosureViolation`.
    A manifest that is a link, or a local ``replace`` that leaves the tree, is a
    violation: the fetch side refuses the same (:func:`_read_go`), and a builder's tree
    must never make the grader read — and quote — a file outside it."""
    root = Path(root)
    if selector.lang == LANG_GO:
        gomod_path = _trial_manifest(root, "go.mod")
        if gomod_path is None:
            return ROLE_GOLD
        gomod = parse_go_mod(gomod_path.read_text(encoding="utf-8", errors="replace"))
        wanted = set(gomod.resolved_requires())
        for target in gomod.local_replaces():
            rel = posixpath.normpath(target)
            if target.startswith("/") or rel == ".." or rel.startswith("../"):
                raise ClosureViolation(f"go.mod: replace => {target} points outside the tree")
            sub = _trial_manifest(root, posixpath.join(rel, "go.mod"))
            if sub is not None:
                wanted |= set(parse_go_mod(sub.read_text("utf-8", "replace")).resolved_requires())
        outside = sorted(wanted - set(selector.modules))
        if outside:
            raise ClosureViolation(outside)
        return ROLE_GOLD
    for role in (ROLE_PARENT, ROLE_GOLD):
        key = selector.lock_keys.get(role)
        if key and tree_lock_key(selector.lang, root, selector.lock_paths.get(role, ())) == key:
            return role
    raise ClosureViolation(
        [f"lock set {tree_lock_key(selector.lang, root, _all_paths(selector)) or '(none)'}"],
        "the trial's lockfiles match neither the parent's nor the gold's",
    )


def _all_paths(selector: ClosureSelector) -> tuple[str, ...]:
    out: dict[str, None] = {}
    for paths in selector.lock_paths.values():
        for p in paths:
            out[p] = None
    return tuple(out)


def describe_inputs(inputs: LockInputs) -> dict[str, Any]:
    """The manifest's ``inputs`` entry for one commit."""
    return {
        "sha": inputs.sha,
        "recipe": inputs.recipe,
        "files": {f.path: f.sha256 for f in inputs.files},
    }


__all__ = [
    "DEFAULT_NPM_REGISTRY_HOST",
    "LANG_GO",
    "LANG_NODE",
    "LANG_PYTHON",
    "NEVER_READ",
    "RECIPE_GO",
    "RECIPE_GO_VENDOR",
    "RECIPE_NODE",
    "RECIPE_NONE",
    "RECIPE_PY",
    "GoMod",
    "LockFile",
    "LockInputs",
    "NodePkg",
    "PyPin",
    "bundle_key",
    "closure_selector",
    "describe_inputs",
    "files_lock_key",
    "go_keys",
    "go_version_tuple",
    "lang_of",
    "parse_go_mod",
    "parse_requirements",
    "select_role",
    "tree_lock_key",
]
