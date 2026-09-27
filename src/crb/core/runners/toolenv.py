"""The declared test environment: on the host, the tests see only the tools a runner names.

On the host executor a test command used to inherit the worker's ``PATH``. Whatever
happened to be installed there could then change a verdict: in the 2026-09-27 dress
rehearsal, Homebrew ``shellcheck`` on the ``PATH`` made cobra's ``TestBashCompletions``
fail at old commits, and 41 of 85 gold patches read red (pilot finding D2). The sealed
image carries no ``shellcheck``, so the same task qualified in one posture and not in the
other for a reason no record named.

This module makes the host's test environment a declaration, not an inheritance:

* a runner lists the tools its tests may run (:meth:`BaseRunner.declared_tools`: for Go,
  ``go``, ``gofmt``, ``git`` and the POSIX basics the sealed image also carries);
* :func:`declare_environment` resolves each one once, links exactly those into a private,
  content-addressed ``bin`` directory, and builds the WHOLE environment from it: ``PATH`` is
  that directory and nothing else, and only the names in :data:`HOST_PASSTHROUGH` (plus the
  runner's own) come from the worker's environment;
* the result carries its identity: every tool with its resolved path, version line and
  SHA-256, and one digest over them. Another tool on the host's ``PATH`` changes nothing;
  a changed declared tool changes the digest, so the posture changes and every task is
  qualified again (ADR-0048).

Navigation
----------
What it is:   The declared test environment for the host executor — the tool farm, the
              explicit environment and its identity (``DeclaredEnvironment``).
What it does: Resolves a runner's declared tools against the worker's ``PATH`` (or an explicit
              path), links them into ``<tmp>/crb-toolenv-<uid>/<key>/bin``, and returns the
              complete environment a host test command runs in, with a digest that moves when
              a declared tool's bytes or version move and never when an undeclared tool
              appears. It never reads a secret and never inherits ``PATH``.
How:          ``ToolSpec`` list → ``shutil.which`` / the explicit path → realpath, size and
              mtime keyed cache of the SHA-256 and the version line → canonical JSON → SHA-256
              digest → the farm, built in a sibling temp directory and renamed into place.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0048-the-host-posture-declares-its-environment.md,
              docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/runners/base.py (``declare`` applies it to every host test command),
              src/crb/core/runners/go_runner.py (the Go declaration), src/crb/core/execution.py
              (``Command.declared_env``: the host executor then inherits nothing),
              src/crb/core/posture.py (``Posture.environment`` carries the digest),
              deploy/sandbox/Dockerfile.go (the sealed image the Go list mirrors)
Tested by:    tests/test_runners_toolenv.py
Touch when:   never for a new repository — a repository whose tests run another host tool
              declares it in ``runner_opts.tools`` (docs/OPERATOR.md); adding a tool every
              repository of a language needs goes in that runner's ``declared_tools`` and
              changes the digest (every host posture of that language qualifies again).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.execution import LOCAL_FIXED_ENV

#: The POSIX basics a test may run by name. The sealed images are Debian slim, which carry
#: these (coreutils, bash, sed, grep, gawk/mawk, findutils, diffutils, tar, gzip, which);
#: the host's list mirrors them so a test sees the same tool NAMES in both postures.
POSIX_BASICS: tuple[str, ...] = (
    "sh",
    "bash",
    "env",
    "cat",
    "cp",
    "mv",
    "rm",
    "mkdir",
    "rmdir",
    "ln",
    "ls",
    "chmod",
    "touch",
    "date",
    "dirname",
    "basename",
    "echo",
    "printf",
    "test",
    "true",
    "false",
    "sed",
    "grep",
    "awk",
    "tr",
    "head",
    "tail",
    "sort",
    "uniq",
    "wc",
    "cut",
    "find",
    "xargs",
    "tee",
    "uname",
    "mktemp",
    "diff",
    "cmp",
    "tar",
    "gzip",
    "sleep",
    "id",
    "pwd",
    "readlink",
    "expr",
    "which",
)

#: The names a host test command may take from the worker's environment (every runner).
#: Their VALUES enter the digest only when they can change an outcome by value
#: (:data:`VALUE_SIGNIFICANT`); a path-valued name counts by presence.
HOST_PASSTHROUGH: tuple[str, ...] = ("HOME", "LANG", "LC_ALL", "TZ", "TMPDIR")

#: Passthrough names whose value can change a test's outcome (a locale, a time zone).
VALUE_SIGNIFICANT: frozenset[str] = frozenset({"LANG", "LC_ALL", "TZ"})

#: Wall clock for one tool's version probe.
VERSION_PROBE_TIMEOUT_S = 30

#: The prefix of :attr:`DeclaredEnvironment.identity` (what ``Posture.environment`` holds).
IDENTITY_PREFIX = "declared:sha256:"


@dataclass(frozen=True)
class ToolSpec:
    """One tool a runner's tests may run by name. ``path`` pins it (``runner_opts``);
    otherwise it is found on the worker's ``PATH``. ``version_args`` prints its version
    (``("version",)`` for ``go``); empty means the bytes' hash alone names it."""

    name: str
    path: str | None = None
    version_args: tuple[str, ...] = ()
    #: False: part of the identity but not linked into the farm — a virtualenv's
    #: interpreter, which must be run from its own ``bin`` (a link elsewhere loses the venv).
    link: bool = True


@dataclass(frozen=True)
class ResolvedTool:
    """A declared tool as found: ``path`` is ``""`` when the host has none (recorded absent,
    never silently dropped — an absent tool is part of the identity too)."""

    name: str
    path: str = ""
    version: str = ""
    sha256: str = ""
    link: bool = True

    @property
    def present(self) -> bool:
        return bool(self.path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "version": self.version,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class DeclaredEnvironment:
    """The complete environment a host test command runs in, and its identity."""

    tools: tuple[ResolvedTool, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    bin_dir: str = ""
    digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "env", dict(self.env))

    @property
    def identity(self) -> str:
        """``declared:sha256:<hex>`` — the posture's ``environment`` field."""
        return IDENTITY_PREFIX + self.digest

    def summary(self) -> str:
        """One line naming every tool: ``name=version@sha12`` (``name=absent``), sorted."""
        parts = []
        for t in sorted(self.tools, key=lambda t: t.name):
            if not t.present:
                parts.append(f"{t.name}=absent")
            else:
                parts.append(f"{t.name}={t.version or '-'}@{t.sha256[:12]}")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """The record a qualification and an evidence pack keep (no values of path names)."""
        return {
            "declared": True,
            "digest": self.digest,
            "tools": [t.to_dict() for t in sorted(self.tools, key=lambda t: t.name)],
            "env_names": sorted(self.env),
        }


# ---------------------------------------------------------------------------
# Resolution (cached: hashing a toolchain binary once per process is enough)
# ---------------------------------------------------------------------------

_CACHE: dict[tuple[str, int, int, tuple[str, ...]], tuple[str, str]] = {}
_CACHE_LOCK = threading.Lock()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_line(path: str, args: Sequence[str]) -> str:
    """The first non-empty output line of ``<path> <args>``; ``""`` when it cannot run."""
    if not args:
        return ""
    try:
        res = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=VERSION_PROBE_TIMEOUT_S,
            env={"PATH": os.path.dirname(path), "HOME": os.environ.get("HOME", "/tmp")},
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (res.stdout or res.stderr or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def resolve_tool(spec: ToolSpec, search_path: str | None = None) -> ResolvedTool:
    """``spec`` found on ``search_path`` (default: the worker's ``PATH``) or at its pinned
    path, with its version line and SHA-256; absent when there is no executable file."""
    found = spec.path if spec.path else shutil.which(spec.name, path=search_path)
    if not found:
        return ResolvedTool(spec.name, link=spec.link)
    real = os.path.realpath(found)
    try:
        st = os.stat(real)
    except OSError:
        return ResolvedTool(spec.name, link=spec.link)
    if not os.path.isfile(real) or not os.access(real, os.X_OK):
        return ResolvedTool(spec.name, link=spec.link)
    key = (real, st.st_size, st.st_mtime_ns, tuple(spec.version_args))
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is None:
        try:
            digest = _sha256_file(real)
        except OSError:
            return ResolvedTool(spec.name, link=spec.link)
        cached = (digest, _version_line(found, spec.version_args))
        with _CACHE_LOCK:
            _CACHE[key] = cached
    return ResolvedTool(spec.name, str(found), cached[1], cached[0], spec.link)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def environment_digest(
    tools: Iterable[ResolvedTool], values: Mapping[str, str], names: Iterable[str]
) -> str:
    """SHA-256 over what can change a test's outcome: each tool's name, version and bytes
    (never its path — two paths to the same bytes are one environment), the values of the
    value-significant names and the set of names present."""
    return hashlib.sha256(
        _canonical(
            {
                "tools": sorted(
                    ([t.name, t.version, t.sha256] for t in tools), key=lambda row: row[0]
                ),
                "values": dict(sorted(values.items())),
                "names": sorted(set(names)),
            }
        ).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# The farm: exactly the declared tools, linked into one directory
# ---------------------------------------------------------------------------


def farm_root() -> Path:
    """Where the farms live: ``$CRB_TOOLENV_DIR`` or ``<tmp>/crb-toolenv-<uid>``."""
    override = os.environ.get("CRB_TOOLENV_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return Path(tempfile.gettempdir()) / f"crb-toolenv-{uid}"


def _farm_ok(bin_dir: Path, tools: Sequence[ResolvedTool]) -> bool:
    present = {t.name: t.path for t in tools if t.present and t.link}
    try:
        entries = {p.name: os.readlink(p) for p in bin_dir.iterdir()}
    except OSError:
        return False
    return entries == present


def ensure_farm(tools: Sequence[ResolvedTool], *, root: Path | None = None) -> Path:
    """The ``bin`` directory holding a link to each present tool and nothing else, keyed by
    the tools' names, paths and hashes. Built beside its final place and renamed in, so two
    workers never see a half-built farm; a farm whose links no longer match is rebuilt."""
    present = sorted((t for t in tools if t.present and t.link), key=lambda t: t.name)
    key = hashlib.sha256(
        _canonical([[t.name, t.path, t.sha256] for t in present]).encode("utf-8")
    ).hexdigest()[:24]
    base = Path(root) if root is not None else farm_root()
    final = base / key
    bin_dir = final / "bin"
    if _farm_ok(bin_dir, present):
        return bin_dir
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key}-", dir=base))
    try:
        (staging / "bin").mkdir()
        for t in present:
            os.symlink(t.path, staging / "bin" / t.name)
        if final.exists():
            # a stale or damaged farm under the same key: set it aside, then take its place
            stale = Path(tempfile.mkdtemp(prefix=f".{key}-stale-", dir=base))
            os.replace(final, stale / "old")
            shutil.rmtree(stale, ignore_errors=True)
        try:
            os.replace(staging, final)
        except OSError:
            # another worker renamed its (identical) farm in first
            if not _farm_ok(bin_dir, present):
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return bin_dir


def declare_environment(
    specs: Sequence[ToolSpec],
    *,
    passthrough: Sequence[str] = (),
    host_env: Mapping[str, str] | None = None,
    extra_path: Sequence[str] = (),
    root: Path | None = None,
) -> DeclaredEnvironment:
    """The declared environment for ``specs``: the farm as the whole ``PATH`` (then
    ``extra_path``, directories the runner owns such as a virtualenv's ``bin``), the
    fixed flags every host command carries, and the host's values of
    :data:`HOST_PASSTHROUGH` plus ``passthrough`` — nothing else from the worker."""
    source = dict(os.environ if host_env is None else host_env)
    search = source.get("PATH", os.defpath)
    seen: dict[str, ToolSpec] = {}
    for s in specs:
        seen.setdefault(s.name, s)
    tools = tuple(resolve_tool(s, search) for s in seen.values())
    names = tuple(dict.fromkeys((*HOST_PASSTHROUGH, *passthrough)))
    env: dict[str, str] = {k: source[k] for k in names if k in source}
    env.setdefault("LANG", "C.UTF-8")
    env.update(LOCAL_FIXED_ENV)
    values = {k: v for k, v in env.items() if k in VALUE_SIGNIFICANT or k in LOCAL_FIXED_ENV}
    digest = environment_digest(tools, values, env)
    bin_dir = ensure_farm(tools, root=root)
    env["PATH"] = os.pathsep.join([str(bin_dir), *extra_path])
    return DeclaredEnvironment(tools, env, str(bin_dir), digest)


__all__ = [
    "HOST_PASSTHROUGH",
    "IDENTITY_PREFIX",
    "POSIX_BASICS",
    "VALUE_SIGNIFICANT",
    "DeclaredEnvironment",
    "ResolvedTool",
    "ToolSpec",
    "declare_environment",
    "ensure_farm",
    "environment_digest",
    "farm_root",
    "resolve_tool",
]
