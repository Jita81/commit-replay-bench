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
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.git import GitRepo
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


class Workspace:
    def __init__(self, repo: GitRepo, root: Path, *, sha: str, parent: str) -> None:
        self.repo = repo
        self.root = Path(root)
        self.sha = sha
        self.parent = parent

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
            p = self.root / str(spec["path"])
            if p.parent.is_dir() and not p.exists():
                p.write_text(str(spec.get("content", "")), encoding="utf-8")
        elif "symlink" in hook:
            spec = hook["symlink"]
            link = self.root / str(spec["path"])
            target = Path(str(spec["target"]))
            if not target.is_absolute():
                target = self.repo.path / target
            if not link.exists() and target.exists():
                with contextlib.suppress(OSError):
                    link.symlink_to(target)

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

    def touched_files(self) -> list[str]:
        """Working-tree files that differ from the parent (tracked + staged)."""
        tracked = self.repo.diff_names("HEAD", cwd=self.root)
        untracked = self.repo.run("ls-files", "--others", "--exclude-standard", cwd=self.root).lines
        return sorted(set(tracked) | set(untracked))

    def diff_stats(self, exclude: Iterable[str] = ()) -> DiffStats:
        """Stats + hash of the full working-tree diff vs the parent (tests excluded by caller)."""
        ex = set(exclude)
        text = self.repo.diff_text("HEAD", cwd=self.root)
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
