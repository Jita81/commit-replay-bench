"""Disposable worktrees: the commit's PARENT, with tests (and, for gold, sources) overlaid.

A :class:`Workspace` is the unit every builder and grader operates on. It is
always created fresh from the main clone, never reused across trials, and
removed after grading. Its ``HEAD`` is the parent commit; every "what changed"
question is answered against :attr:`Workspace.parent` — the commit the harness
recorded — never against whatever ``HEAD`` happens to be at grade time.

Test-file integrity is checked by **content hash against the commit's own
version** (``git show <sha>:<path>``), not by ``git diff`` heuristics, so a
builder cannot satisfy belt 1 by any means other than leaving the oracle
byte-identical.

The grader's view is independent of the builder's git
-------------------------------------------------------
A worktree shares its git directory with the main clone, and the builder runs
inside it with git on its PATH. Anything git *reports* — ``git diff``, ``git
status``, ``ls-files --others --exclude-standard`` — is computed from state the
builder can write: the index (``update-index --skip-worktree`` /
``--assume-unchanged`` / ``--cacheinfo`` with a forged stat), ``HEAD`` (a ``git
commit`` inside the worktree), the shared ``info/exclude`` (which for a linked
worktree is the *main clone's* — one builder's line hides a path for every other
worktree of that repository), ``core.excludesFile``. The independent AI review
pass (2026-09-14, finding 1) graded three such worktrees ``clean``. So:

* :meth:`Workspace.touched_files` enumerates from the **filesystem against the
  parent tree** (``git ls-tree -r <parent>`` object ids vs a fresh hash of every
  file) — the index, ``HEAD``, ``info/exclude`` and ``core.excludesFile`` are never
  consulted. The only ignore rules honoured for an untracked path are patterns
  that exist, line for line, in a ``.gitignore`` **tracked at the parent
  commit**; a rule the builder wrote (a new ``.gitignore``, a new line in one)
  hides nothing.
* :meth:`Workspace.enforce_integrity` is the grader's pre-flight: ``HEAD`` must
  still be the parent, the worktree must still belong to the harness's clone, no
  index entry may carry a skip-worktree or assume-unchanged bit, and the shared
  ``info/exclude`` must hold only what the harness recorded at create time — any
  other line is removed (the file is rewritten) and reported as tamper. A
  violation is a disqualification, never a verdict.

:meth:`Workspace.touched_files` keeps the three invariants the belts rely on:

* **Every kind of change is listed** — modified, deleted and type-changed tracked
  files (a rename is its deletion plus its addition, never collapsed into the new
  name) and untracked additions at any depth, symlinks included.
* **Repository-ignored paths stay out** (``node_modules``, virtualenvs, build
  output) *only by the parent's own rules*: a rule the builder added cannot hide a
  file from the grader.
* **What the harness itself wrote at create time is not a builder change** while
  it is byte-identical to what was written (``post_create`` hooks, the
  ``node_modules`` symlink). Overlaid test files are the caller's to exclude.

Known residual: a file whose checkout differs from its blob (``eol=crlf`` /
``filter=lfs`` attributes) reads as touched — fail-closed, and the same rule
belt 1a's raw hash compare already applies to the oracle files.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.git import GitError, GitRepo
from crb.core.spec import Language, RepoConfig


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: Git object-id length → the hash git uses for that repository's object format.
_OID_ALGORITHMS: dict[int, str] = {40: "sha1", 64: "sha256"}

#: Git tree-entry modes for a regular file (the executable bit is not a content change).
_FILE_MODES: frozenset[str] = frozenset({"100644", "100755"})
_SYMLINK_MODE = "120000"
_GITLINK_MODE = "160000"

#: The worktree-relative name the exclude file is reported under in tamper evidence.
EXCLUDE_TAMPER_PATH = ".git/info/exclude"

#: ``git ls-files -v`` tags that mean "git has been told not to look at this file".
#: ``S`` is skip-worktree; a lowercase tag is assume-unchanged. Either hides an edit
#: from every porcelain view the builder can point the harness at.
_INDEX_BIT_TAGS: frozenset[str] = frozenset({"S"})


def git_blob_oid(data: bytes, *, algorithm: str = "sha1") -> str:
    """The object id git would give ``data`` as a blob (``blob <len>\\0<data>``)."""
    h = hashlib.new(algorithm, usedforsecurity=False)
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def _file_blob_oid(path: Path, algorithm: str) -> str | None:
    """Blob oid of a regular file, read in chunks; ``None`` if it cannot be read."""
    h = hashlib.new(algorithm, usedforsecurity=False)
    try:
        size = path.stat().st_size
        h.update(b"blob %d\0" % size)
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


@dataclass(frozen=True)
class TreeEntry:
    """One entry of the parent tree (``git ls-tree -r``): mode, object id, size."""

    mode: str
    oid: str
    size: int | None


@dataclass(frozen=True)
class IntegrityViolation:
    """One way the worktree's git view was found not to be the harness's.

    ``kind`` is one of ``head_moved`` (``HEAD`` is not the parent), ``foreign_gitdir``
    (the worktree no longer belongs to the harness's clone), ``index_bits``
    (skip-worktree / assume-unchanged entries), ``exclude_edited`` (lines in the
    shared ``info/exclude`` the harness did not write — now removed). ``files``
    are the paths to report as tamper evidence.
    """

    kind: str
    detail: str
    files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "files": list(self.files)}


@dataclass(frozen=True)
class DiffStats:
    files: tuple[str, ...]
    additions: int
    deletions: int
    diff_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": list(self.files),
            "additions": self.additions,
            "deletions": self.deletions,
            "diff_sha256": self.diff_sha256,
        }


#: Marker in :attr:`Workspace.harness_files` for a symlink the harness created.
HARNESS_SYMLINK = "symlink"


class Workspace:
    def __init__(self, repo: GitRepo, root: Path, *, sha: str, parent: str) -> None:
        self.repo = repo
        self.root = Path(root)
        self.sha = sha
        self.parent = parent
        #: rel path → sha256 of what the harness wrote (or :data:`HARNESS_SYMLINK`)
        #: during ``_post_create``. Such a file is not a builder change while unchanged.
        self.harness_files: dict[str, str] = {}
        #: The lines of ``info/exclude`` when this worktree was created — the file is
        #: the main clone's, shared with the operator and every other worktree — plus
        #: the patterns the harness itself appended (:attr:`exclude_patterns`). Together
        #: they are the only content the file may hold at grade time. ``None`` when the
        #: workspace was bound to an existing worktree (the CLI's ``crb grade``): the
        #: file is then left alone — and never read by the grader either.
        self.exclude_baseline: list[str] | None = None
        #: Patterns :meth:`_exclude_from_git` wrote for this worktree.
        self.exclude_patterns: list[str] = []

    # --- lifecycle ---------------------------------------------------------------
    @classmethod
    def create(
        cls,
        repo: GitRepo,
        sha: str,
        dest: Path,
        *,
        config: RepoConfig | None = None,
        post_create: bool = True,
    ) -> Workspace:
        """Create a worktree at ``sha``'s parent under ``dest`` (removed if present)."""
        dest = Path(dest)
        if dest.exists():
            repo.worktree_remove(dest)
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        parent = repo.parent(sha)
        repo.worktree_add(dest, parent)
        ws = cls(repo, dest, sha=sha, parent=parent)
        ws.exclude_baseline = ws._exclude_lines()
        if post_create and config is not None:
            ws._post_create(config)
        return ws

    @classmethod
    def at_ref(
        cls,
        repo: GitRepo,
        ref: str,
        dest: Path,
        *,
        config: RepoConfig | None = None,
        post_create: bool = True,
    ) -> Workspace:
        """A worktree checked out AT ``ref`` itself (forward mode: no commit parent).

        ``sha == parent == ref`` so belt 4's "changed since HEAD" and the diff
        helpers behave exactly as they do for a replay worktree.
        """
        dest = Path(dest)
        if dest.exists():
            repo.worktree_remove(dest)
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        head = repo.rev_parse(ref)
        repo.worktree_add(dest, head)
        ws = cls(repo, dest, sha=head, parent=head)
        ws.exclude_baseline = ws._exclude_lines()
        if post_create and config is not None:
            ws._post_create(config)
        return ws

    def remove(self) -> None:
        self.repo.worktree_remove(self.root)
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.remove()

    def _post_create(self, config: RepoConfig) -> None:
        """Per-language fixups a raw worktree needs before its tests can run."""
        if config.language is Language.JAVASCRIPT:
            link = self.root / "node_modules"
            main_nm = self.repo.path / "node_modules"
            if not link.exists() and main_nm.is_dir():
                with contextlib.suppress(OSError):
                    link.symlink_to(main_nm)
                    self._exclude_from_git("/node_modules")
                    self.harness_files["node_modules"] = HARNESS_SYMLINK
        for hook in config.runner_opts.get("post_create", []) or []:
            self._apply_hook(hook)

    def _exclude_path(self) -> Path:
        """The ``info/exclude`` git consults for this worktree. For a linked worktree
        that is the **main clone's** file (``info/`` lives in the common git dir)."""
        rel = self.repo.run("rev-parse", "--git-path", "info/exclude", cwd=self.root).stdout
        path = Path(rel.strip())
        if not path.is_absolute():
            path = self.root / path
        return path

    def _exclude_lines(self) -> list[str]:
        try:
            return self._exclude_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

    def _exclude_from_git(self, pattern: str) -> None:
        """Ignore a harness fixup from git's porcelain views (``info/exclude``) and
        RECORD it: the grader restores the file to exactly the recorded content.

        A repo's ``.gitignore`` commonly says ``node_modules/`` — the trailing slash
        matches a directory, not the symlink the harness plants — so the link showed
        up as an untracked touched file and ``discard_source_edits`` deleted it,
        after which every grade failed with ``FileNotFoundError: 'jest'``
        (NHSDigital/nhsuk-react-components, 2026-09-13). The exclude file is never
        committed and (since 2026-09-14) never read by :meth:`touched_files`; the
        harness symlink stays out of the builder's changes through
        :attr:`harness_files`. The exclude line keeps the builder's own ``git status``
        quiet about it.
        """
        path = self._exclude_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{pattern}\n")
        self.exclude_patterns.append(pattern)

    def restore_exclude(self) -> list[str]:
        """Rewrite ``info/exclude`` to the content the harness recorded; return the
        foreign lines that were removed (the builder's — ``[]`` when none).

        Membership is by stripped line, not by byte position: a concurrent trial of
        the same repository appends the same harness pattern to the shared file, and
        that is not tamper. A line the harness never wrote and that was not there at
        create time can only have come from the builder (or from an operator editing
        the main clone mid-trial, which is the same thing to the grader). A workspace
        without a baseline (bound, not created) leaves the file alone.
        """
        if self.exclude_baseline is None:
            return []
        allowed = {ln.strip() for ln in self.exclude_baseline} | {
            p.strip() for p in self.exclude_patterns
        }
        allowed.add("")
        current = self._exclude_lines()
        foreign = [ln for ln in current if ln.strip() not in allowed]
        if not foreign:
            return []
        path = self._exclude_path()
        kept = [ln for ln in current if ln.strip() in allowed]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{ln}\n" for ln in kept), encoding="utf-8")
        return foreign

    # --- integrity -----------------------------------------------------------------
    def enforce_integrity(self) -> list[IntegrityViolation]:
        """The grader's pre-flight (see the module docstring). Returns every
        violation found — an empty list means the worktree's git view is still the
        harness's. Restores the shared ``info/exclude`` as a side effect. Never raises
        for a builder-caused state: a ``.git`` the harness cannot read is reported as
        ``foreign_gitdir``, not thrown."""
        out: list[IntegrityViolation] = []
        try:
            head = self._head()
        except GitError as exc:
            return [
                IntegrityViolation(
                    "foreign_gitdir", f"cannot resolve the worktree's HEAD: {exc}", (".git",)
                )
            ]
        if head != self.parent:
            out.append(
                IntegrityViolation(
                    "head_moved",
                    f"HEAD {head[:10]} is not the parent {self.parent[:10]}",
                    (".git/HEAD",),
                )
            )
        if not self._belongs_to_clone():
            out.append(
                IntegrityViolation(
                    "foreign_gitdir",
                    "the worktree's git directory is not the harness clone's",
                    (".git",),
                )
            )
        flagged = self._index_bit_paths()
        if flagged:
            out.append(
                IntegrityViolation(
                    "index_bits",
                    "skip-worktree / assume-unchanged set on: "
                    + ", ".join(flagged[:5])
                    + (" …" if len(flagged) > 5 else ""),
                    tuple(flagged),
                )
            )
        foreign = self.restore_exclude()
        if foreign:
            out.append(
                IntegrityViolation(
                    "exclude_edited",
                    f"info/exclude carried {len(foreign)} line(s) the harness did not write "
                    f"(removed): {foreign[:3]}",
                    (EXCLUDE_TAMPER_PATH,),
                )
            )
        return out

    def _head(self) -> str:
        return self.repo.run(
            "rev-parse", "--verify", "HEAD^{commit}", cwd=self.root, check=True
        ).stdout.strip()

    def _belongs_to_clone(self) -> bool:
        """The worktree's common git dir IS the harness clone's (the ``.git`` pointer
        has not been redirected at another repository)."""
        try:
            here = self.repo.run(
                "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=self.root, check=True
            ).stdout.strip()
            clone = self.repo.run(
                "rev-parse", "--path-format=absolute", "--git-common-dir", check=True
            ).stdout.strip()
        except GitError:
            return False
        try:
            return Path(here).resolve() == Path(clone).resolve()
        except OSError:
            return False

    def _index_bit_paths(self) -> list[str]:
        """Index entries git has been told not to look at (``ls-files -v``: ``S`` =
        skip-worktree, lowercase = assume-unchanged), sorted."""
        try:
            out = self.repo.run("ls-files", "-v", "-z", cwd=self.root, check=True).stdout
        except GitError:
            return []
        flagged: list[str] = []
        for rec in out.split("\0"):
            if len(rec) < 3 or rec[1] != " ":
                continue
            tag, path = rec[0], rec[2:]
            if tag in _INDEX_BIT_TAGS or tag.islower():
                flagged.append(path)
        return sorted(flagged)

    def _apply_hook(self, hook: Mapping[str, Any]) -> None:
        if "write_if_missing" in hook:
            spec = hook["write_if_missing"]
            rel = str(spec["path"])
            p = self.root / rel
            if p.parent.is_dir() and not p.exists():
                content = str(spec.get("content", "")).encode("utf-8")
                p.write_bytes(content)
                self.harness_files[rel] = sha256_bytes(content)
        elif "symlink" in hook:
            spec = hook["symlink"]
            rel = str(spec["path"])
            link = self.root / rel
            target = Path(str(spec["target"]))
            if not target.is_absolute():
                target = self.repo.path / target
            if not link.exists() and target.exists():
                with contextlib.suppress(OSError):
                    link.symlink_to(target)
                    self.harness_files[rel] = HARNESS_SYMLINK

    def harness_unchanged(self, rel: str) -> bool:
        """``rel`` was written by the harness at create time and is still exactly that."""
        recorded = self.harness_files.get(rel)
        if recorded is None:
            return False
        if recorded == HARNESS_SYMLINK:
            return (self.root / rel).is_symlink()
        return self.file_hash(rel) == recorded

    # --- overlays ----------------------------------------------------------------
    def overlay_tests(self, test_files: Sequence[str]) -> None:
        """Bring the commit's TEST files into the parent worktree (target goes RED)."""
        self.repo.checkout_paths(self.sha, list(test_files), cwd=self.root)

    def overlay_sources(self, src_files: Sequence[str]) -> None:
        """Bring the commit's SOURCE files in (the gold / human patch)."""
        self.repo.checkout_paths(self.sha, list(src_files), cwd=self.root)

    def restore_from_parent(self, paths: Sequence[str]) -> None:
        self.repo.checkout_paths(self.parent, list(paths), cwd=self.root)

    # --- integrity ---------------------------------------------------------------
    def file_hash(self, rel: str) -> str | None:
        p = self.root / rel
        try:
            return sha256_bytes(p.read_bytes())
        except OSError:
            return None

    def commit_file_hash(self, rel: str) -> str | None:
        content = self.repo.show_file(self.sha, rel)
        return None if content is None else sha256_bytes(content.encode("utf-8"))

    def tests_byte_identical(self, test_files: Iterable[str]) -> tuple[bool, list[str]]:
        """Belt 1: every test file's content equals the commit's own version.

        Uses ``git diff <sha> -- <paths>`` (byte-level, honours .gitattributes
        the same way the commit did) AND a raw hash compare as belt-and-braces.
        Returns ``(ok, offending_paths)``.
        """
        files = list(test_files)
        offending: list[str] = []
        diff = self.repo.diff_paths_against(self.sha, files, cwd=self.root)
        if diff.strip():
            for f in files:
                if f"a/{f}" in diff or f"b/{f}" in diff:
                    offending.append(f)
        for f in files:
            if f in offending:
                continue
            here = self.file_hash(f)
            theirs = self.commit_file_hash(f)
            if here is None or theirs is None or here != theirs:
                offending.append(f)
        return (not offending, offending)

    def parent_text(self, rel: str) -> str | None:
        """``rel``'s content at the parent commit, or ``None`` if it did not exist."""
        return self.repo.show_file(self.parent, rel)

    def parent_tree(self) -> dict[str, TreeEntry]:
        """Every path in the parent commit's tree (``git ls-tree -r -l``), keyed by
        repo-relative POSIX path. Read from the object store — nothing in the worktree
        can change it."""
        out = self.repo.run("ls-tree", "-r", "-l", "-z", self.parent, cwd=self.root, check=True)
        entries: dict[str, TreeEntry] = {}
        for rec in out.stdout.split("\0"):
            if not rec:
                continue
            meta, _tab, path = rec.partition("\t")
            parts = meta.split()
            if len(parts) != 4 or not path:
                raise GitError(["ls-tree", "-r", "-l", self.parent], 0, f"unparsable entry {rec!r}")
            mode, _type, oid, size = parts
            entries[path] = TreeEntry(mode, oid, int(size) if size.isdigit() else None)
        return entries

    def touched_files(self) -> list[str]:
        """Files the BUILDER changed relative to the parent (see the module docstring).

        Computed from the filesystem against :meth:`parent_tree`, never from git's
        index-, ``HEAD``- or exclude-dependent views:

        * a tracked path whose bytes (or symlink target, or entry type) differ from
          the parent's blob, or that is gone, is touched;
        * every other path present in the tree is touched unless an ignore rule that
          exists in a ``.gitignore`` tracked at the parent hides it (attributed with
          ``git check-ignore -v --no-index``; ``info/exclude``, ``core.excludesFile``
          and any rule the builder wrote are not honoured);
        * minus harness-written files still exactly as written.

        A rename is its deletion plus its addition. Directories wholly ignored by the
        parent's rules (``node_modules/``, ``.venv/``) are pruned without descending,
        as git does; a directory the parent tracks anything under is always walked.
        Nested ``.git`` entries are never entered or reported.
        """
        tracked = self.parent_tree()
        algorithm = (
            _OID_ALGORITHMS.get(len(next(iter(tracked.values())).oid), "sha1")
            if tracked
            else "sha1"
        )
        tracked_dirs: set[str] = set()
        for rel in tracked:
            d = rel
            while "/" in d:
                d = d.rsplit("/", 1)[0]
                tracked_dirs.add(d)
        touched: set[str] = set()
        seen: set[str] = set()
        candidates: list[str] = []
        level: list[str] = [""]
        while level:
            subdirs: list[str] = []
            for dir_rel in level:
                try:
                    with os.scandir(self.root / dir_rel if dir_rel else self.root) as it:
                        entries = sorted(it, key=lambda e: e.name)
                except OSError:
                    continue
                for e in entries:
                    if e.name == ".git":
                        continue
                    rel = f"{dir_rel}/{e.name}" if dir_rel else e.name
                    try:
                        is_link = e.is_symlink()
                        is_dir = not is_link and e.is_dir(follow_symlinks=False)
                    except OSError:
                        touched.add(rel)  # unreadable: fail closed
                        continue
                    if is_dir:
                        entry = tracked.get(rel)
                        if entry is not None and entry.mode == _GITLINK_MODE:
                            seen.add(rel)  # a submodule: not this tree's concern
                            continue
                        if entry is not None:
                            touched.add(rel)  # a file became a directory
                            seen.add(rel)
                        subdirs.append(rel)
                        continue
                    entry = tracked.get(rel)
                    if entry is None:
                        candidates.append(rel)
                        continue
                    seen.add(rel)
                    if not self._entry_unchanged(rel, entry, is_link=is_link, algorithm=algorithm):
                        touched.add(rel)
            level = self._next_level(subdirs, tracked_dirs, tracked)
        touched.update(rel for rel in tracked if rel not in seen)  # deleted
        touched.update(self._not_ignored_by_parent(candidates, tracked))
        return sorted(f for f in touched if not self.harness_unchanged(f))

    def _next_level(
        self, dirs: Sequence[str], tracked_dirs: set[str], tracked: Mapping[str, TreeEntry]
    ) -> list[str]:
        """The directories to walk next: every partially-tracked one, plus the wholly
        untracked ones the parent's own ignore rules do not hide."""
        descend = [d for d in dirs if d in tracked_dirs]
        wholly_untracked = [d for d in dirs if d not in tracked_dirs]
        if wholly_untracked:
            descend += self._not_ignored_by_parent(wholly_untracked, tracked)
        return sorted(descend)

    def _entry_unchanged(
        self, rel: str, entry: TreeEntry, *, is_link: bool, algorithm: str
    ) -> bool:
        p = self.root / rel
        if entry.mode == _SYMLINK_MODE:
            if not is_link:
                return False
            try:
                target = os.readlink(p)
            except OSError:
                return False
            return git_blob_oid(os.fsencode(target), algorithm=algorithm) == entry.oid
        if entry.mode not in _FILE_MODES or is_link:
            return False  # a symlink (or an unknown mode) where the parent had a file
        if entry.size is not None:
            try:
                if p.stat().st_size != entry.size:
                    return False
            except OSError:
                return False
        return _file_blob_oid(p, algorithm) == entry.oid

    def _not_ignored_by_parent(
        self, paths: Sequence[str], tracked: Mapping[str, TreeEntry]
    ) -> list[str]:
        """``paths`` minus those hidden by an ignore rule the PARENT commit carries.

        Every path is attributed with ``git check-ignore -v -n --no-index``. A match
        is honoured only when its source is a repo-relative ``.gitignore`` that exists
        in the parent tree AND the matching pattern is, stripped, one of that file's
        lines at the parent. ``info/exclude`` (``.git/…``), ``core.excludesFile`` (an
        absolute path) and any builder-written rule therefore hide nothing.
        """
        if not paths:
            return []
        attributed = self._check_ignore(paths)
        parent_lines: dict[str, set[str] | None] = {}
        out: list[str] = []
        # -z -n output: <source> NUL <linenum> NUL <pattern> NUL <pathname> NUL, repeated;
        # a non-matching path carries empty source/linenum/pattern fields
        for i in range(0, len(attributed) - 3, 4):
            source, _lineno, pattern, path = attributed[i : i + 4]
            if not source or not pattern:
                out.append(path)
                continue
            if not self._is_parent_gitignore(source, tracked):
                out.append(path)
                continue
            if source not in parent_lines:
                before = self.parent_text(source)
                parent_lines[source] = (
                    None if before is None else {ln.strip() for ln in before.splitlines()}
                )
            lines = parent_lines[source]
            if lines is None or pattern.strip() not in lines:
                out.append(path)  # the rule is the builder's
        return out

    @staticmethod
    def _is_parent_gitignore(source: str, tracked: Mapping[str, TreeEntry]) -> bool:
        s = source.replace("\\", "/")
        while s.startswith("./"):
            s = s[2:]
        if s.startswith("/") or s.startswith("../") or "/../" in s or ".git/" in s:
            return False
        if s.rsplit("/", 1)[-1] != ".gitignore":
            return False
        entry = tracked.get(s)
        return entry is not None and entry.mode in _FILE_MODES

    def _check_ignore(self, paths: Sequence[str]) -> list[str]:
        """``git check-ignore -z -v -n --no-index --stdin`` over ``paths``: the
        NUL-separated fields, four per path (``-n`` reports non-matches too, with
        empty source/line/pattern).

        ``-z`` (unambiguous for any path byte) is only accepted with ``--stdin``, and
        the argv-only :class:`GitRepo` wrapper has no stdin — so this is the one git
        call the workspace makes itself, with the wrapper's binary and timeout.
        ``--no-index`` keeps the (builder-writable) index out of the answer.
        """
        argv = [
            self.repo.git_binary,
            "-C",
            str(self.root),
            "check-ignore",
            "-z",
            "-v",
            "-n",
            "--no-index",
            "--stdin",
        ]
        try:
            p = subprocess.run(  # argv-only, our own git binary, no shell
                argv,
                input="\0".join(paths) + "\0",
                capture_output=True,
                text=True,
                timeout=self.repo.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(argv, 124, f"timed out after {self.repo.timeout}s") from e
        if p.returncode not in (0, 1):  # 1 = no path ignored; anything else is an error
            raise GitError(argv, p.returncode, p.stderr or "")
        fields = (p.stdout or "").split("\0")
        if fields and fields[-1] == "":
            fields.pop()  # the record terminator, not a fifth field
        return fields

    def diff_stats(self, exclude: Iterable[str] = ()) -> DiffStats:
        """Stats + hash of the full working-tree diff vs the parent (tests excluded by caller).

        Untracked NEW files are part of the change: ``git diff <parent>`` alone ignores
        them, so a patch that only adds a file carried an empty diff hash (human-review-
        guide exercise 4, 2026-09-14). They are diffed against ``/dev/null`` via
        ``--no-index`` and appended, in path order, so the hash is deterministic.

        The diff is taken against :attr:`parent` by sha, never ``HEAD`` (a builder can
        move ``HEAD``); the grader runs :meth:`enforce_integrity` first so the index
        carries no bit that would make ``git diff`` skip a file.
        """
        ex = set(exclude)
        text = self.repo.diff_text(self.parent, cwd=self.root)
        tracked = set(self.repo.diff_names(self.parent, cwd=self.root))
        for rel in self.touched_files():  # hash covers the FULL diff; ``exclude`` only
            if rel in tracked or self.harness_unchanged(rel):  # filters files/counts below
                continue
            p = self.root / rel
            if not p.is_file() or p.is_symlink():
                continue
            r = self.repo.run("diff", "--no-index", "--", "/dev/null", rel, cwd=self.root)
            # --no-index exits 1 when the files differ (always, against /dev/null)
            if r.stdout:
                text += ("" if text.endswith("\n") or not text else "\n") + r.stdout
        adds = dels = 0
        files: list[str] = []
        current: str | None = None
        for line in text.splitlines():
            if line.startswith("+++ b/"):
                current = line[6:]
                if current not in ex:
                    files.append(current)
            elif current in ex:
                continue
            elif line.startswith("+") and not line.startswith("+++"):
                adds += 1
            elif line.startswith("-") and not line.startswith("---"):
                dels += 1
        return DiffStats(tuple(files), adds, dels, sha256_bytes(text.encode("utf-8")))

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8", errors="replace")

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    def relpath(self, p: Path) -> str:
        return os.path.relpath(p, self.root)
