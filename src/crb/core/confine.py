"""Confined writes: a repository-relative path written inside its root, never through a link.

A worktree is untrusted input: the repository it was checked out from can commit a
directory, or a file, as a symbolic link to anywhere on the host. A path the product
joins onto the worktree and then writes with ``mkdir`` / ``write_text`` follows such a
link, so the product's OWN write lands outside the worktree — and whatever runs next reads
the file from there (governance review 2026-09-27, GOV-5: an authored oracle written
through ``tests/ext -> /elsewhere``). This module is the one way the product writes a
repository-relative path it did not create: every component is opened relative to its
parent's file descriptor with ``O_NOFOLLOW``, so a link is refused rather than followed,
whether it was there before the call or swapped in during it.

Navigation
----------
What it is:   The confined writer — ``write_text_confined`` / ``write_bytes_confined`` and
              the ``PathEscape`` refusal they raise.
What it does: Refuses an absolute path, a ``..`` component, a component or final entry that
              is a symbolic link, and a component that is not a directory, each with the
              reason named; creates missing directories and writes the file through
              descriptors opened ``O_NOFOLLOW`` relative to their parent, then checks the
              resolved path lies inside the resolved root.
How:          ``_components`` validates the relative path lexically; ``_open_parent`` walks
              it from the root descriptor (``os.stat(..., dir_fd=, follow_symlinks=False)``
              for the named reason, ``os.open(..., O_NOFOLLOW | O_DIRECTORY, dir_fd=)`` as the
              race guard); the leaf is opened ``O_CREAT | O_TRUNC | O_NOFOLLOW``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md (the worktree is untrusted input)
Works with:   src/crb/factory/testfirst.py (``write_authored``: the RED proof and the oracle
              commit write the authored test through it), src/crb/factory/review.py
              (``replay_edits`` writes the builder's edits into the review tree through it),
              src/crb/factory/build.py (``stage_oracle_commit`` stages the oracle through
              ``write_authored``)
Tested by:    tests/test_factory_testfirst.py
Touch when:   never for a new repository — a client repository that commits links is refused
              here, not configured around; the product writes another repository-relative
              path it did not create (route it through here, never ``Path.write_text``); a
              platform without ``dir_fd`` support is added (it must refuse, not fall back).
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path, PurePosixPath

#: ``O_NOFOLLOW`` / ``O_DIRECTORY`` exist on every POSIX platform the product runs on; a
#: platform without them has no confined write, and ``_flag`` refuses rather than guess.
_NOFOLLOW = "O_NOFOLLOW"
_DIRECTORY = "O_DIRECTORY"


class PathEscape(ValueError):
    """A repository-relative write that could land outside its root, refused with why."""


def _flag(name: str) -> int:
    value = getattr(os, name, None)
    if value is None:  # pragma: no cover — every supported platform defines both
        raise PathEscape(f"this platform has no {name}: a confined write is not possible")
    return int(value)


def _components(rel: str) -> tuple[str, ...]:
    """The path's components, refusing an empty, absolute or ``..``-bearing path."""
    text = str(rel or "")
    if not text.strip() or "\x00" in text:
        raise PathEscape(f"{rel!r} is not a repository-relative path")
    pure = PurePosixPath(text.replace("\\", "/"))
    if pure.is_absolute():
        raise PathEscape(f"{rel!r} is absolute, not repository-relative")
    parts = tuple(p for p in pure.parts if p not in ("", "."))
    if not parts or ".." in parts:
        raise PathEscape(f"{rel!r} leaves the repository ('..')")
    return parts


def _kind(name: str, dir_fd: int) -> int | None:
    """The mode of ``name`` under ``dir_fd`` without following a link; ``None`` if absent."""
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return None


def _open_dir(name: str, dir_fd: int, shown: str) -> int:
    """Open (creating when absent) the directory ``name`` under ``dir_fd``, never a link."""
    mode = _kind(name, dir_fd)
    if mode is None:
        # created meanwhile? the O_NOFOLLOW open below judges what it is
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, 0o777, dir_fd=dir_fd)
        mode = _kind(name, dir_fd)
    if mode is not None and stat.S_ISLNK(mode):
        raise PathEscape(f"{shown!r} is a symbolic link — a write through it could leave the root")
    if mode is not None and not stat.S_ISDIR(mode):
        raise PathEscape(f"{shown!r} is not a directory")
    try:
        return os.open(name, os.O_RDONLY | _flag(_DIRECTORY) | _flag(_NOFOLLOW), dir_fd=dir_fd)
    except OSError as exc:  # swapped for a link or a file between the stat and the open
        raise PathEscape(f"{shown!r} changed under the write ({exc.strerror})") from exc


def write_bytes_confined(root: Path, rel: str, data: bytes) -> Path:
    """Write ``data`` to ``root/rel`` (parents created) without following any link; returns
    the written path. Raises :class:`PathEscape` for a path that could land outside ``root``."""
    parts = _components(rel)
    root_fd = os.open(root, os.O_RDONLY | _flag(_DIRECTORY))
    fds = [root_fd]
    try:
        for i, name in enumerate(parts[:-1]):
            fds.append(_open_dir(name, fds[-1], "/".join(parts[: i + 1])))
        leaf = parts[-1]
        mode = _kind(leaf, fds[-1])
        if mode is not None and stat.S_ISLNK(mode):
            raise PathEscape(
                f"{rel!r} is a symbolic link — a write through it could leave the root"
            )
        if mode is not None and not stat.S_ISREG(mode):
            raise PathEscape(f"{rel!r} exists and is not a regular file")
        try:
            fd = os.open(
                leaf,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _flag(_NOFOLLOW),
                0o666,
                dir_fd=fds[-1],
            )
        except OSError as exc:
            raise PathEscape(f"{rel!r} changed under the write ({exc.strerror})") from exc
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    finally:
        for fd in reversed(fds):
            os.close(fd)
    out = Path(root).joinpath(*parts)
    if not out.resolve().is_relative_to(Path(root).resolve()):  # belt and braces
        raise PathEscape(f"{rel!r} resolved outside the root")
    return out


def write_text_confined(root: Path, rel: str, text: str, *, encoding: str = "utf-8") -> Path:
    """:func:`write_bytes_confined` for text."""
    return write_bytes_confined(root, rel, text.encode(encoding))


__all__ = ["PathEscape", "write_bytes_confined", "write_text_confined"]
