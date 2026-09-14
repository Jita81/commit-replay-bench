"""Disposable worktrees: the commit's PARENT, with tests (and, for gold, sources) overlaid.

A :class:`Workspace` is the unit every builder and grader operates on. It is
always created fresh from the main clone, never reused across trials, and
removed after grading. Its ``HEAD`` is the parent commit, so ``git diff HEAD``
inside it is exactly "what changed since the parent" — belt 4's source-changed
check and the evidence pack's diff stats both read from that.

Test-file integrity is checked by **content hash against the commit's own
version** (``git show <sha>:<path>``), not by ``git diff`` heuristics, so a
builder cannot satisfy belt 1 by any means other than leaving the oracle
byte-identical.

:meth:`Workspace.touched_files` is "what the builder changed", with three
invariants the belts rely on:

* **Every kind of change is listed** — modified, deleted and staged tracked files
  (renames are reported as a deletion plus an addition, never collapsed into the
  new name) and untracked additions at any depth.
* **Git-ignored paths stay out** (``node_modules``, virtualenvs, build output)
  *unless the ignore rule that hides them is the builder's own*: a rule added to
  a ``.gitignore`` since the parent, or a ``.gitignore`` the builder created,
  cannot hide a file from the grader.
* **What the harness itself wrote at create time is not a builder change** while
  it is byte-identical to what was written (``post_create`` hooks, the
  ``node_modules`` symlink). Overlaid test files are the caller's to exclude.
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

    def _exclude_from_git(self, pattern: str) -> None:
        """Ignore a harness fixup in THIS worktree only (``info/exclude``).

        A repo's ``.gitignore`` commonly says ``node_modules/`` — the trailing slash
        matches a directory, not the symlink the harness plants — so the link showed
        up as an untracked touched file and ``discard_source_edits`` deleted it,
        after which every grade failed with ``FileNotFoundError: 'jest'``
        (NHSDigital/nhsuk-react-components, 2026-09-13). The exclude file is
        per-worktree, never committed, never seen by the builder as a change.
        """
        rel = self.repo.run("rev-parse", "--git-path", "info/exclude", cwd=self.root).stdout
        path = Path(rel.strip())
        if not path.is_absolute():
            path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{pattern}\n")

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

    def touched_files(self) -> list[str]:
        """Files the BUILDER changed relative to the parent (see the module docstring).

        ``git diff --name-only --no-renames HEAD`` (modified + deleted + staged; a
        rename is its deletion and its addition) ∪ ``git ls-files --others
        --exclude-standard`` (untracked, not ignored) ∪ ignored files hidden only by
        a builder-authored ignore rule, minus harness-written files still unchanged.
        """
        tracked = self.repo.run(
            "diff", "--name-only", "--no-renames", "HEAD", cwd=self.root, check=True
        ).lines
        untracked = self.repo.run("ls-files", "--others", "--exclude-standard", cwd=self.root).lines
        touched = set(tracked) | set(untracked)
        touched |= self._hidden_by_builder_ignore_rules(touched)
        return sorted(f for f in touched if not self.harness_unchanged(f))

    def _hidden_by_builder_ignore_rules(self, touched: set[str]) -> set[str]:
        """Ignored, untracked paths whose ignore rule the builder wrote.

        Only consulted when a ``.gitignore`` is itself touched (modified or new).
        Every ignored path is attributed with ``git check-ignore -v``; a rule from an
        untouched ignore file, or one whose pattern line already existed in the
        parent's version of that file, is honoured. Anything else is un-hidden —
        directories are expanded to the files beneath them.
        """
        sources = {f for f in touched if f == ".gitignore" or f.endswith("/.gitignore")}
        if not sources:
            return set()
        ignored = self.repo.run(
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--directory",
            cwd=self.root,
        ).stdout.split("\0")
        ignored = [p for p in ignored if p]
        if not ignored:
            return set()
        attributed = self._check_ignore(ignored)
        parent_lines: dict[str, set[str]] = {}
        out: set[str] = set()
        # -z output: <source> NUL <linenum> NUL <pattern> NUL <pathname> NUL, repeated
        for i in range(0, len(attributed) - 3, 4):
            source, _lineno, pattern, path = attributed[i : i + 4]
            if source not in sources:
                continue  # a rule from an ignore file the builder did not touch
            if source not in parent_lines:
                before = self.parent_text(source) or ""
                parent_lines[source] = {ln.strip() for ln in before.splitlines()}
            if pattern.strip() in parent_lines[source]:
                continue  # the rule pre-dates the builder
            if path.endswith("/"):
                base = self.root / path
                for dirpath, _dirs, names in os.walk(base, followlinks=False):
                    out.update(self.relpath(Path(dirpath) / n) for n in names)
            else:
                out.add(path)
        return out

    def _check_ignore(self, paths: Sequence[str]) -> list[str]:
        """``git check-ignore -z -v --stdin`` over ``paths``: the NUL-separated fields.

        ``-z`` (unambiguous for any path byte) is only accepted with ``--stdin``, and
        the argv-only :class:`GitRepo` wrapper has no stdin — so this is the one git
        call the workspace makes itself, with the wrapper's binary and timeout.
        """
        argv = [self.repo.git_binary, "-C", str(self.root), "check-ignore", "-z", "-v", "--stdin"]
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

        Untracked NEW files are part of the change: ``git diff HEAD`` alone ignores
        them, so a patch that only adds a file carried an empty diff hash (human-review-
        guide exercise 4, 2026-09-14). They are diffed against ``/dev/null`` via
        ``--no-index`` and appended, in path order, so the hash is deterministic.
        """
        ex = set(exclude)
        text = self.repo.diff_text("HEAD", cwd=self.root)
        tracked = set(self.repo.diff_names("HEAD", cwd=self.root))
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
