"""A thin, argv-only git wrapper. No shell, no porcelain parsing beyond what we own.

Every call is ``git -C <path> ...`` with ``capture_output=True``. Nothing here
runs repository code; git is the only executable invoked. Worktree lifecycle
lives in :mod:`crb.core.workspace`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """A git command failed. ``argv`` and ``stderr`` are preserved for the ledger."""

    def __init__(self, argv: list[str], returncode: int, stderr: str) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"git {' '.join(argv[:3])}… failed rc={returncode}: {stderr.strip()[:400]}"
        )


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.stdout.split("\n") if ln.strip()]


class GitRepo:
    """Handle on a local clone (or a worktree of one)."""

    def __init__(self, path: str | Path, *, git_binary: str = "git", timeout: int = 300) -> None:
        self.path = Path(path)
        self.git_binary = git_binary
        self.timeout = timeout

    # --- plumbing ----------------------------------------------------------------
    def run(self, *args: str, check: bool = False, cwd: str | Path | None = None) -> GitResult:
        argv = [self.git_binary, "-C", str(cwd or self.path), *args]
        try:
            p = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(argv, 124, f"timed out after {self.timeout}s") from e
        res = GitResult(p.returncode, p.stdout or "", p.stderr or "")
        if check and not res.ok:
            raise GitError(argv, res.returncode, res.stderr)
        return res

    # --- queries -----------------------------------------------------------------
    def rev_parse(self, ref: str = "HEAD") -> str:
        return self.run("rev-parse", "--verify", ref + "^{commit}", check=True).stdout.strip()

    def is_repo(self) -> bool:
        return self.run("rev-parse", "--is-inside-work-tree").ok

    def log_shas(self, n: int, *, ref: str = "HEAD", no_merges: bool = True) -> list[str]:
        args = ["log", "--format=%H", "-n", str(n)]
        if no_merges:
            args.append("--no-merges")
        args.append(ref)
        return self.run(*args, check=True).stdout.split()

    def changed_files(self, sha: str) -> list[str]:
        """Files touched by ``sha`` (relative to its first parent)."""
        return self.run("show", "--name-only", "--pretty=format:", sha, check=True).lines

    def numstat_churn(self, base: str, head: str, paths: list[str]) -> int:
        """Added + deleted lines between ``base`` and ``head`` restricted to ``paths``."""
        if not paths:
            return 0
        out = self.run("diff", "--numstat", base, head, "--", *paths, check=True).stdout
        churn = 0
        for line in out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            a, d = parts[0], parts[1]
            churn += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
        return churn

    def author_date(self, sha: str) -> str:
        return self.run("show", "-s", "--format=%aI", sha, check=True).stdout.strip()

    def subject(self, sha: str) -> str:
        return self.run("show", "-s", "--format=%s", sha, check=True).stdout.strip()

    def message(self, sha: str) -> str:
        return self.run("show", "-s", "--format=%B", sha, check=True).stdout.strip()

    def parent(self, sha: str) -> str:
        return self.rev_parse(f"{sha}~1")

    def diff_names(self, ref: str, *, cwd: str | Path | None = None) -> list[str]:
        """``git diff --name-only <ref>`` in the worktree (working tree vs ``ref``)."""
        return self.run("diff", "--name-only", ref, cwd=cwd, check=True).lines

    def diff_paths_against(
        self, ref: str, paths: list[str], *, cwd: str | Path | None = None
    ) -> str:
        """Textual diff of the working tree ``paths`` against their state at ``ref``."""
        if not paths:
            return ""
        return self.run("diff", ref, "--", *paths, cwd=cwd, check=True).stdout

    def diff_stat(self, ref: str, *, cwd: str | Path | None = None) -> str:
        return self.run("diff", "--stat", ref, cwd=cwd, check=True).stdout

    def diff_text(self, ref: str, *, cwd: str | Path | None = None) -> str:
        return self.run("diff", ref, cwd=cwd, check=True).stdout

    def show_file(self, sha: str, path: str) -> str | None:
        r = self.run("show", f"{sha}:{path}")
        return r.stdout if r.ok else None

    # --- mutations (worktree-scoped) --------------------------------------------
    def checkout_paths(self, sha: str, paths: list[str], *, cwd: str | Path) -> None:
        """Overlay ``paths`` from ``sha`` into the worktree at ``cwd``."""
        if not paths:
            return
        self.run("checkout", sha, "--", *paths, cwd=cwd, check=True)

    def worktree_add(self, dest: Path, ref: str) -> None:
        self.run("worktree", "add", "-f", "--detach", str(dest), ref, check=True)

    def worktree_remove(self, dest: Path) -> None:
        self.run("worktree", "remove", "--force", str(dest))
        self.run("worktree", "prune")
