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
  provisioned at all. A ``uv.lock`` is read into the same hashed pins a requirements
  lock gives, or refused; it is never provisioned loosely (G-951, G-962).
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
              pinned ``requirements*.txt`` (following ``-r``; a ``--hash`` that is not a
              whole sha256 refuses the lock, never dropped), a ``uv.lock`` (the project's
              dependencies and the ``runner_opts.deps_groups`` it names, closed, hashed and
              marked), a ``poetry.lock`` or PEP 751 ``pylock.toml`` (DL-110), or
              ``runner_opts.deps_lock`` (whose inner lists are alternatives: a commit reads
              the first it carries), and ``package.json`` + ``package-lock.json`` at a
              commit; refuses every source the ADR refuses; computes the bundle keys (a uv
              lock's groups included); says which set a trial selects.
How:          ``GitRepo.show_blob`` / ``tree_names`` → per-language parser (``parse_uv_lock``
              walks the lock's graph, joining markers per path; ``parse_structured_lock``
              reads a poetry or pylock lock) → ``LockInputs``
              (files + parsed pins) → ``bundle_key`` over sorted blob hashes →
              ``ClosureSelector`` (``crb.core.deps``) → ``select_role`` on a trial tree.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/deps.py (the seam types and the refusal vocabulary),
              src/crb/core/git.py (``show_blob``: the object store is the only input),
              src/crb/provision/__init__.py (the providers that fetch what this reads),
              src/crb/core/runners/node_runners.py (``lock_key``: the same normalisation of a
              Node lockfile, for the host's eras), src/crb/core/spec.py (``RepoConfig.runner`` and
              ``runner_opts``)
Tested by:    tests/test_provision.py
Touch when:   never for a new repository — its lockfiles are read as committed; a lock format
              becomes provisioned (a parser here, a recipe under src/crb/provision/, and a row in
              docs/DEPLOYMENT.md §3.4).
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
#: Python locks this version still refuses (poetry and pylock are read since DL-110, uv since
#: DL-101).
_PY_ALT_LOCKS: tuple[str, ...] = ("Pipfile.lock",)
#: The uv lock, read at the root when no requirements lock is there and none is declared.
UV_LOCK = "uv.lock"
#: The only package index a uv lock may name: the public one it was resolved against. The
#: fetch reads the deployment's own index (a mirror of it); the lock's hashes pin the bytes.
UV_PUBLIC_INDEX: frozenset[str] = frozenset({"https://pypi.org/simple", "https://pypi.org/simple/"})
#: A package reached by more marker paths than this is refused, not approximated.
_UV_MAX_PATHS = 32
_HASH = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")
#: A project name as PEP 508 spells it, and a version as a pin may write it: the whole
#: string, so a newline or an option can never ride inside one (``\Z``, not ``$``).
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+!_-]*\Z")
#: What an environment marker is written with: names, quoted values, comparisons and
#: parentheses. No newline, ``#``, ``;`` or backslash, and no word that starts with ``-``
#: (an option) — a marker is repository text that reaches the file pip reads.
_MARKER_CHARS = re.compile(r"[A-Za-z0-9_.'\"()<>=!~ ,*+@/:-]*\Z")
_OPTION_WORD = re.compile(r"(?:^|\s)-")

#: A node of a uv lock's graph: a package (by identity) and the extra it was reached for.
_UvNode = tuple[int, str]


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


def safe_marker(marker: str) -> bool:
    """True when ``marker`` (an environment marker, without its ``;``) cannot write a
    second line, a comment or an option into a requirements file."""
    return bool(_MARKER_CHARS.match(marker)) and not _OPTION_WORD.search(marker)


def pin_line_refusal(pin: PyPin) -> str:
    """Why ``pin`` cannot be written as one ``name==version [; marker] --hash=…`` line,
    or ``""``: each field is matched whole, never trusted because a reader produced it."""
    if not _NAME.match(pin.name):
        return f"the name {pin.name!r} is not a package name"
    if not _VERSION.match(pin.version):
        return f"{pin.name}: the version {pin.version!r} is not a version"
    if pin.marker and not (pin.marker.startswith(";") and safe_marker(pin.marker[1:])):
        return f"{pin.name}=={pin.version}: the marker {pin.marker!r} is not a marker"
    bad = [h for h in pin.hashes if not _HASH.match(h)]
    if bad:
        return f"{pin.name}=={pin.version}: {bad[0]!r} is not a sha256 hash"
    return ""


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


_HASH_OPTION = re.compile(r"--hash(?:=|\s+)(\S+)")


def _whole_hashes(tail: str, where: str) -> tuple[str, ...]:
    """The ``--hash`` options after a pin, each a whole ``sha256:<64 hex>``. Anything else
    in the tail — a hash of another kind or length, a ``--hash`` with no value, another
    option — refuses the lock (PROVISION_SOURCE_REFUSED): a hash is never skipped, so the
    pin written bare, nor cut to 64 characters (DL-101; docs/PREVENTION.md P-271)."""
    hashes: list[str] = []
    rest = tail.strip()
    while rest:
        m = _HASH_OPTION.match(rest)
        if not m or not _HASH.match(m.group(1)):
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED",
                f"{where}: {rest.split()[0] if not m else m.group(1)!r} after the pin is not "
                "a whole --hash=sha256:<64 hex>",
            )
        hashes.append(m.group(1))
        rest = rest[m.end() :].strip()
    return tuple(hashes)


def parse_requirements(
    reader: _Reader, path: str, *, seen: set[str] | None = None
) -> tuple[list[LockFile], list[PyPin]]:
    """Read ``path`` and its ``-r`` includes through git objects. Only ``name==version``
    (with optional markers, and ``--hash`` options each a whole sha256) is accepted."""
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
        first_hash = re.search(r"\s--hash", line)
        cut = first_hash.start() if first_hash else len(line)
        spec, hashes = line[:cut].strip(), _whole_hashes(line[cut:], where)
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
        pin = PyPin(m.group("name"), m.group("version"), hashes, (m.group("marker") or ""), where)
        why = pin_line_refusal(pin)
        if why:
            raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{where}: {why}")
        pins.append(pin)
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


def _declared_locks(config: RepoConfig) -> list[str | tuple[str, ...]] | None:
    """``runner_opts.deps_lock`` as entries: a path every commit must carry, or a tuple of
    alternatives of which a commit reads the first it carries. ``None`` when nothing is
    declared; a malformed declaration is refused, never guessed at."""
    raw = config.runner_opts.get("deps_lock")
    if raw is None:
        return None
    entries = [raw] if isinstance(raw, str) else raw
    out: list[str | tuple[str, ...]] = []
    if isinstance(entries, list) and entries:
        for entry in entries:
            if isinstance(entry, str) and entry.strip():
                out.append(entry)
            elif (
                isinstance(entry, list)
                and entry
                and all(isinstance(e, str) and e.strip() for e in entry)
            ):
                out.append(tuple(entry))
            else:
                out = []
                break
    if not out:
        raise ProvisionRefused(
            "PROVISION_NO_LOCK",
            "runner_opts.deps_lock must name a lock path, or a list whose entries are paths or "
            f"lists of alternative paths; got {raw!r}",
        )
    return out


def _choose(reader: _Reader, entry: str | tuple[str, ...]) -> str:
    """The path one declared entry reads at this commit: the path itself, or the first of
    its alternatives the commit carries (none carried is ``PROVISION_NO_LOCK``)."""
    if isinstance(entry, str):
        return entry
    for alt in entry:
        if reader.blob(posixpath.normpath(alt)) is not None:
            return alt
    raise ProvisionRefused(
        "PROVISION_NO_LOCK",
        f"none of the declared alternatives ({', '.join(entry)}) is committed at this commit",
    )


def _deps_groups(config: RepoConfig) -> tuple[str, ...]:
    """``runner_opts.deps_groups``: the dependency groups or extras a uv lock is read for,
    besides the project's own dependencies."""
    raw = config.runner_opts.get("deps_groups") or ()
    groups = (raw,) if isinstance(raw, str) else tuple(raw)
    if not all(isinstance(g, str) and g for g in groups):
        raise ProvisionRefused(
            "PROVISION_NO_LOCK", f"runner_opts.deps_groups must name groups; got {raw!r}"
        )
    return tuple(sorted(set(groups)))


# ---------------------------------------------------------------------------
# Python — poetry and PEP 751 pylock locks: read into the same pinned, hashed ``PyPin`` set a
# requirements lock gives, so one recipe fetches them (DL-110). A ``uv.lock`` is read by
# :func:`parse_uv_lock`, which walks its graph for the named groups (DL-101).
# ---------------------------------------------------------------------------

#: A PEP 751 lock's file name: ``pylock.toml`` or ``pylock.<name>.toml``.
_PYLOCK = re.compile(r"pylock(?:\.[A-Za-z0-9_-]+)?\.toml")


def _structured_lock(name: str) -> str:
    """``poetry`` / ``pylock`` for a structured lock's file name, else ``""`` (a ``uv.lock``
    is :func:`parse_uv_lock`'s)."""
    base = posixpath.basename(name)
    if base == "poetry.lock":
        return "poetry"
    if _PYLOCK.fullmatch(base):
        return "pylock"
    return ""


def _sha256s(values: Iterable[object]) -> tuple[str, ...]:
    """The ``sha256:<hex>`` hashes among ``values`` (anything else is left out, never guessed)."""
    out: list[str] = []
    for v in values:
        text = str(v or "").strip()
        m = re.fullmatch(r"sha256[:=]([0-9a-fA-F]{64})", text)
        if m and f"sha256:{m.group(1).lower()}" not in out:
            out.append(f"sha256:{m.group(1).lower()}")
    return tuple(out)


def _or_markers(markers: Iterable[str]) -> str:
    """``(a) or (b)`` over distinct non-empty markers; ``""`` when there are none."""
    uniq = list(dict.fromkeys(m.strip() for m in markers if m and m.strip()))
    if not uniq:
        return ""
    return uniq[0] if len(uniq) == 1 else " or ".join(f"({m})" for m in uniq)


def _and_markers(*markers: str) -> str:
    parts = [m.strip() for m in markers if m and m.strip()]
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return " and ".join(f"({m})" for m in parts)


def _edge_markers(edges: Iterable[tuple[str, str]], names: Iterable[str]) -> dict[str, str]:
    """name → the marker under which some package needs it: the OR of its incoming edges'
    markers, or ``""`` when any edge needs it unconditionally (or nothing names it)."""
    incoming: dict[str, list[str]] = {}
    for target, marker in edges:
        incoming.setdefault(re.sub(r"[-_.]+", "-", target).lower(), []).append(marker)
    out: dict[str, str] = {}
    for name in names:
        ms = incoming.get(re.sub(r"[-_.]+", "-", name).lower(), [])
        out[name] = "" if not ms or any(not m for m in ms) else _or_markers(ms)
    return out


def _pin(name: str, version: object, hashes: tuple[str, ...], marker: str, where: str) -> PyPin:
    v = str(version or "").strip()
    if not name or not v or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+!_-]*", v):
        raise ProvisionRefused("PROVISION_UNPINNED", f"{where}: {name or '?'} has no exact version")
    return PyPin(name, v, hashes, f"; {marker}" if marker else "", where)


def _poetry_pins(doc: Mapping[str, Any], path: str) -> list[PyPin]:
    """``poetry.lock``: every package, hashed from its ``files``; a ``legacy`` source (a
    private index) is fetched from the configured index like any other, a git, URL, file or
    directory source is refused."""
    packages = [p for p in doc.get("package") or [] if isinstance(p, Mapping)]
    edges: list[tuple[str, str]] = []
    for pkg in packages:
        for dep, spec in dict(pkg.get("dependencies") or {}).items():
            specs = spec if isinstance(spec, list) else [spec]
            for one in specs:
                marker = str(one.get("markers") or "") if isinstance(one, Mapping) else ""
                edges.append((str(dep), marker))
    reach = _edge_markers(edges, [str(p.get("name") or "") for p in packages])
    pins: list[PyPin] = []
    for i, pkg in enumerate(packages):
        name = str(pkg.get("name") or "")
        where = f"{path}:package[{i}] {name}"
        source = dict(pkg.get("source") or {})
        kind = str(source.get("type") or "")
        if kind and kind != "legacy":
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED", f"{where}: a {kind} source is refused"
            )
        own = pkg.get("markers")
        if isinstance(own, Mapping):
            own = _or_markers(str(v) for v in own.values())
        marker = str(own or "") or reach[name]
        hashes = _sha256s(f.get("hash") for f in pkg.get("files") or [] if isinstance(f, Mapping))
        pins.append(_pin(name, pkg.get("version"), hashes, marker, where))
    return pins


def _pylock_pins(doc: Mapping[str, Any], path: str) -> list[PyPin]:
    """A PEP 751 ``pylock.toml``: every package from an index, hashed from its wheels and
    sdist; a ``vcs``, ``directory`` or ``archive`` package is refused."""
    version = str(doc.get("lock-version") or "")
    if not version.startswith("1."):
        raise ProvisionRefused(
            "PROVISION_LOCK_UNSUPPORTED", f"{path}: lock-version {version or '?'} is not 1.x"
        )
    pins: list[PyPin] = []
    for i, pkg in enumerate(p for p in doc.get("packages") or [] if isinstance(p, Mapping)):
        name = str(pkg.get("name") or "")
        where = f"{path}:packages[{i}] {name}"
        other = [k for k in ("vcs", "directory", "archive") if k in pkg]
        if other:
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED", f"{where}: a {other[0]} source is refused"
            )
        files = [pkg.get("sdist") or {}, *(pkg.get("wheels") or [])]
        hashes = _sha256s(
            f"sha256:{dict(f.get('hashes') or {}).get('sha256', '')}"
            for f in files
            if isinstance(f, Mapping)
        )
        pins.append(_pin(name, pkg.get("version"), hashes, str(pkg.get("marker") or ""), where))
    return pins


def parse_structured_lock(reader: _Reader, path: str) -> tuple[list[LockFile], list[PyPin]]:
    """Read one poetry or pylock lock at ``path`` through git objects."""
    norm = posixpath.normpath(path)
    data = reader.blob(norm)
    if data is None:
        raise ProvisionRefused("PROVISION_NO_LOCK", f"{norm} is not committed at this commit")
    try:
        doc = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProvisionRefused(
            "PROVISION_LOCK_UNSUPPORTED", f"{norm} is not a readable TOML lock: {exc}"
        ) from exc
    kind = _structured_lock(norm)
    reader_fn = {"poetry": _poetry_pins, "pylock": _pylock_pins}[kind]
    return [LockFile(norm, data)], reader_fn(doc, norm)


def _read_python(
    reader: _Reader, config: RepoConfig
) -> tuple[str, tuple[LockFile, ...], tuple[PyPin, ...], tuple[str, ...]]:
    declared = _declared_locks(config)
    names = reader.names()
    if declared:
        paths = [_choose(reader, entry) for entry in declared]
    else:
        paths = sorted(n for n in names if re.fullmatch(r"requirements[\w.-]*\.txt", n))
    if not paths:
        structured = [n for n in (UV_LOCK, "poetry.lock") if n in names] + sorted(
            n for n in names if _PYLOCK.fullmatch(n)
        )
        if structured:
            paths = structured[:1]
    if not paths:
        alt = [n for n in _PY_ALT_LOCKS if n in names]
        if alt:
            raise ProvisionRefused(
                "PROVISION_LOCK_UNSUPPORTED",
                f"{alt[0]} is not provisioned in this version; commit a pinned requirements "
                "lock, a uv.lock, poetry.lock or pylock.toml (or name one in runner_opts.deps_lock)",
            )
        if _py_declares(reader):
            raise ProvisionRefused(
                "PROVISION_NO_LOCK",
                "the project declares dependencies but no requirements lock is committed",
            )
        return RECIPE_NONE, (), (), ()
    files: list[LockFile] = []
    pins: list[PyPin] = []
    seen: set[str] = set()
    selection: tuple[str, ...] = ()
    for p in paths:
        if posixpath.basename(p) == UV_LOCK:
            selection = _deps_groups(config)
            f, pn = parse_uv_lock(reader, p, selection)
        elif _structured_lock(p):
            f, pn = parse_structured_lock(reader, p)
        else:
            f, pn = parse_requirements(reader, p, seen=seen)
        files += f
        pins += pn
    if not pins:
        return RECIPE_NONE, tuple(files), (), selection
    return RECIPE_PY, tuple(files), tuple(pins), selection


def parse_uv_lock(
    reader: _Reader, path: str, groups: Sequence[str] = ()
) -> tuple[list[LockFile], list[PyPin]]:
    """Read a ``uv.lock`` through git objects into the pinned, hashed set a requirements
    lock gives: the project's own dependencies and the named ``groups`` (dependency groups
    or extras), closed over every package's dependencies and the extras an edge asks for.

    Each pin carries every wheel's hash, and the marker that reaches it: the conjunction
    of the markers on one path from the project, joined by ``or`` over the paths, and none
    when any path is unconditional — pip evaluates it on the fetch image. Refused, never
    loosened: a source other than the public index (``PROVISION_SOURCE_REFUSED``); a
    package every environment needs that has no wheel (``PROVISION_BUILD_REQUIRED``); a
    lock version, a workspace or an edge this reader cannot resolve to one package
    (``PROVISION_LOCK_UNSUPPORTED``); a group the lock does not carry (``PROVISION_NO_LOCK``).
    The project itself is the tree under test and is never fetched."""
    norm = posixpath.normpath(path)
    if norm.startswith("../") or norm.startswith("/"):
        raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{path}: a lock outside the repository")
    data = reader.blob(norm)
    if data is None:
        raise ProvisionRefused("PROVISION_NO_LOCK", f"{norm} is not committed at this commit")

    def unsupported(why: str) -> ProvisionRefused:
        return ProvisionRefused("PROVISION_LOCK_UNSUPPORTED", f"{norm}: {why}")

    try:
        lock = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise unsupported(f"not a TOML lock ({exc})") from exc
    if lock.get("version") != 1:
        raise unsupported(f"lock version {lock.get('version')!r} is not provisioned (only 1)")
    packages = [p for p in lock.get("package", []) if isinstance(p, dict)]
    roots = [p for p in packages if _uv_is_project(p)]
    if len(roots) != 1:
        raise unsupported(
            "a uv workspace is not provisioned"
            if roots
            else "names no project (no package whose source is the lock's own directory)"
        )
    root = roots[0]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for p in packages:
        by_name.setdefault(_norm_name(str(p.get("name", ""))), []).append(p)

    def resolve(edge: Mapping[str, Any]) -> dict[str, Any]:
        name = _norm_name(str(edge.get("name", "")))
        cands = by_name.get(name, [])
        if "version" in edge:
            cands = [c for c in cands if c.get("version") == edge["version"]]
        if len(cands) > 1 and "source" in edge:
            cands = [c for c in cands if c.get("source") == edge["source"]]
        if len(cands) != 1:
            raise unsupported(f"the dependency {name} resolves to {len(cands)} packages")
        return cands[0]

    def edges(pkg: Mapping[str, Any], extra: str) -> list[Mapping[str, Any]]:
        table = (
            pkg.get("dependencies", [])
            if not extra
            else pkg.get("optional-dependencies", {}).get(extra, [])
        )
        return [e for e in table if isinstance(e, dict)]

    start: list[Mapping[str, Any]] = edges(root, "")
    dev = root.get("dev-dependencies", {})
    optional = root.get("optional-dependencies", {})
    for g in groups:
        if g in dev:
            start += [e for e in dev[g] if isinstance(e, dict)]
        elif g in optional:
            start += edges(root, g)
        else:
            raise ProvisionRefused(
                "PROVISION_NO_LOCK", f"{norm} carries no dependency group or extra named {g!r}"
            )

    # the marker paths reaching each (package, extra) node: a set of conjunctions, the empty
    # conjunction meaning "always"; a superset of a held path adds nothing (absorption)
    paths: dict[_UvNode, set[frozenset[str]]] = {}
    ident: dict[int, dict[str, Any]] = {}
    work: list[tuple[_UvNode, frozenset[str]]] = []

    def reach(edge: Mapping[str, Any], via: frozenset[str]) -> None:
        pkg = resolve(edge)
        extras = [str(x) for x in edge.get("extra", []) or []]
        if _uv_is_project(pkg):
            # the tree under test is never fetched, but an extra of its own that an edge
            # names (``{ name = "proj", extra = ["testing"] }``) is followed like any other
            missing = [x for x in extras if x not in optional]
            if missing:
                raise ProvisionRefused(
                    "PROVISION_NO_LOCK",
                    f"{norm}: the project declares no extra named {missing[0]!r}",
                )
            if not extras:
                return
        marker = str(edge.get("marker", "")).strip()
        if marker and not safe_marker(marker):
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED",
                f"{norm}: the marker {marker!r} on {edge.get('name')!r} is not a marker",
            )
        clause = via | {marker} if marker else via
        for extra in extras if _uv_is_project(pkg) else ("", *extras):
            node = (id(pkg), extra)
            ident[id(pkg)] = pkg
            held = paths.setdefault(node, set())
            if any(h <= clause for h in held):
                continue
            held -= {h for h in held if clause <= h}
            held.add(clause)
            if len(held) > _UV_MAX_PATHS:
                raise unsupported(f"{pkg.get('name')} is reached by too many marker paths")
            work.append((node, clause))

    for e in start:
        reach(e, frozenset())
    while work:
        (pid, extra), clause = work.pop()
        if clause not in paths.get((pid, extra), set()):
            continue  # absorbed by a shorter path since it was queued
        for e in edges(ident[pid], extra):
            reach(e, clause)

    pins: list[PyPin] = []
    for pid, pkg in ident.items():
        if _uv_is_project(pkg):
            continue  # reached only for its own extras
        clauses = paths.get((pid, ""), set())
        name = str(pkg.get("name", ""))
        version = str(pkg.get("version", ""))
        if not version:
            raise ProvisionRefused("PROVISION_UNPINNED", f"{norm}: {name!r} has no version")
        if not _NAME.match(name) or not _VERSION.match(version):
            raise ProvisionRefused(
                "PROVISION_SOURCE_REFUSED",
                f"{norm}: {name!r}=={version!r} is not a package name and version",
            )
        _uv_check_source(norm, name, pkg.get("source"))
        marker = _uv_marker(clauses)
        hashes = tuple(
            str(w.get("hash", "")) for w in pkg.get("wheels", []) or [] if isinstance(w, dict)
        )
        if not hashes:
            if not marker:
                raise ProvisionRefused(
                    "PROVISION_BUILD_REQUIRED", f"{norm}: {name}=={version} publishes no wheel"
                )
            sdist = pkg.get("sdist")
            hashes = (str(sdist.get("hash", "")),) if isinstance(sdist, dict) else ()
        if not hashes or not all(_HASH.match(h) for h in hashes):
            raise ProvisionRefused(
                "PROVISION_UNPINNED", f"{norm}: {name}=={version} carries no sha256 hash"
            )
        pins.append(PyPin(name, version, hashes, marker, f"{norm}:{name}"))
    pins.sort(key=lambda p: (p.norm, p.version))
    return [LockFile(norm, data)], pins


def _norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _uv_is_project(pkg: Mapping[str, Any]) -> bool:
    src = pkg.get("source")
    return isinstance(src, dict) and any(src.get(k) == "." for k in ("editable", "virtual"))


def _uv_check_source(lock: str, name: str, src: object) -> None:
    kind, where = next(iter(src.items())) if isinstance(src, dict) and src else ("", "")
    if kind == "registry" and where in UV_PUBLIC_INDEX:
        return
    what = f"the index {where}" if kind == "registry" else f"a {kind or 'missing'} source"
    raise ProvisionRefused("PROVISION_SOURCE_REFUSED", f"{lock}: {name} comes from {what}")


def _uv_marker(clauses: set[frozenset[str]]) -> str:
    """``""`` when any path is unconditional, else ``"; <marker>"``: one marker as written,
    a conjunction's parts parenthesised, several paths joined by ``or``."""
    if not clauses or frozenset() in clauses:
        return ""

    def conj(c: frozenset[str]) -> str:
        parts = sorted(c)
        return parts[0] if len(parts) == 1 else " and ".join(f"({m})" for m in parts)

    terms = sorted(conj(c) for c in clauses)
    return "; " + (terms[0] if len(terms) == 1 else " or ".join(f"({t})" for t in terms))


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
    #: The groups a uv lock was read for (``runner_opts.deps_groups``): the same file read for
    #: another selection pins another set, so the selection is part of the bundle key.
    selection: tuple[str, ...] = ()

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
            recipe, files, py, selection = _read_python(reader, config)
            return cls(
                lang,
                sha,
                recipe,
                files,
                tuple(sorted(f"{p.norm}=={p.version}" for p in py)),
                py_pins=py,
                selection=selection,
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
        """What a bundle key covers: every input file's hash, and the uv groups read."""
        chosen = (f"groups:{','.join(self.selection)}",) if self.selection else ()
        return tuple(sorted(f.sha256 for f in self.files)) + chosen

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
    "parse_structured_lock",
    "parse_uv_lock",
    "pin_line_refusal",
    "select_role",
    "tree_lock_key",
]
