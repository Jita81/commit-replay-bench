"""A thin, argv-only git wrapper. No shell, no porcelain parsing beyond what we own.

Every call is ``git -C <path> ...`` with ``capture_output=True``. Nothing here
runs repository code; git is the only executable invoked. Worktree lifecycle
lives in :mod:`crb.core.workspace`.

Cloning (:func:`clone_repo`) is the one operation that reaches the network. It is
policy-checked (:func:`validate_clone_url`: ``https://`` and ssh only — ``file://``
and bare local paths are refused unless :data:`LOCAL_CLONE_ENV` is ``1``, a
test/dev-only switch), credential-safe (:func:`redact_url` strips userinfo from
every string that could reach a log, an event or an exception) and atomic (the
clone lands in a sibling temp directory and is renamed into place only once
``git clone`` exits 0, so a killed or timed-out clone never leaves a half-repo
that a later call would mistake for the real thing).

Navigation
----------
What it is:   The git wrapper — ``GitRepo`` (every query and worktree mutation the engine
              makes, as argv) and ``clone_repo`` (the one network operation, policy-checked
              and atomic).
What it does: Runs ``git -C <path> …`` with captured output and a wall clock; raises
              ``GitError`` (argv and stderr preserved) on ``check=True`` failures; reads
              history, changed files, churn, author dates and file contents from the
              object store; adds and removes worktrees. Refuses clone sources that are not
              ``https://`` / ssh (``file://`` only under the test-only switch) and never
              lets a credential reach a log or an exception.
How:          ``run`` → ``subprocess.run(["git", "-C", path, …])`` (no shell, timeout →
              ``GitError`` rc 124); ``clone_repo`` → ``validate_clone_url`` → clone into a
              sibling temp dir with ``GIT_TERMINAL_PROMPT=0`` → rename into place on exit 0;
              ``redact_url`` / ``redact_urls_in`` strip userinfo from every message.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/workspace.py (creates worktrees and reads the parent tree through
              it), src/crb/core/mine.py (log, changed files, churn, subject, author date),
              src/crb/core/capability.py (the change-profile walk), src/crb/server/worker.py
              (clones a URL-registered repository on its first run),
              src/crb/cli/commands/repo.py (``crb repo add --url``)
Tested by:    tests/test_git.py, tests/test_git_clone.py, tests/test_cli_repo_url.py,
              tests/test_worker_clone.py
Touch when:   never for a new repository (register a local clone with ``--path`` or a URL
              with ``--url`` — docs/OPERATOR.md#2-configure-a-repository); a new git query
              belongs here as argv, never as a shell string, and a clone-policy change
              (a new scheme) is a security decision recorded in docs/SECURITY.md.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

#: Set to ``1`` to let :func:`validate_clone_url` accept ``file://`` URLs. Test and
#: developer machines only: a local path is never a legitimate source for a
#: measured repository on a server.
LOCAL_CLONE_ENV = "CRB_ALLOW_LOCAL_CLONE"

#: Default wall clock for one ``git clone`` (full history of a large repo).
DEFAULT_CLONE_TIMEOUT_S = 30 * 60

_SCP_LIKE_RE = re.compile(r"^(?P<user>[A-Za-z0-9._-]+)@(?P<host>[A-Za-z0-9.-]+):(?P<path>[^/].*)$")
#: ``scheme://userinfo@`` anywhere in free text (git echoes URLs in its errors).
_USERINFO_IN_TEXT_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_SCHEMES_ALWAYS: frozenset[str] = frozenset({"https", "ssh"})
_SCHEMES_LOCAL: frozenset[str] = frozenset({"file"})


class CloneUrlError(ValueError):
    """A clone URL the policy refuses (scheme, shape, or a local source in production)."""


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
    """One git command's exit code and captured output."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def lines(self) -> list[str]:
        """Non-blank stdout lines (the shape of ``--name-only`` style output)."""
        return [ln for ln in self.stdout.split("\n") if ln.strip()]


class GitRepo:
    """Handle on a local clone (or a worktree of one). ``cwd`` on a method points a
    call at a worktree of this clone; the object store queried is the same."""

    def __init__(self, path: str | Path, *, git_binary: str = "git", timeout: int = 300) -> None:
        self.path = Path(path)
        self.git_binary = git_binary
        self.timeout = timeout

    # --- plumbing ----------------------------------------------------------------
    def run(self, *args: str, check: bool = False, cwd: str | Path | None = None) -> GitResult:
        """``git -C <cwd or path> <args>``. A timeout is a ``GitError`` (rc 124) always;
        a non-zero exit is one only with ``check=True``."""
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
        """The full sha ``ref`` names (``^{commit}``: a tag is peeled, a blob refused)."""
        return self.run("rev-parse", "--verify", ref + "^{commit}", check=True).stdout.strip()

    def is_repo(self) -> bool:
        """Is ``path`` inside a git working tree?"""
        return self.run("rev-parse", "--is-inside-work-tree").ok

    def log_shas(self, n: int, *, ref: str = "HEAD", no_merges: bool = True) -> list[str]:
        """The newest ``n`` commit shas from ``ref`` (merges skipped by default: a
        merge's diff against its first parent is the whole branch, not a change)."""
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
        """The author date as strict ISO 8601 with a numeric offset, always.

        git ≥ 2.5x renders a UTC ``%aI`` as ``…Z`` (older git: ``…+00:00``). The date is
        stored on every task, hashed into evidence and compared for era selection, so
        one spelling is kept whatever git the host runs (CI, 2026-09-15)."""
        raw = self.run("show", "-s", "--format=%aI", sha, check=True).stdout.strip()
        return raw[:-1] + "+00:00" if raw.endswith("Z") else raw

    def subject(self, sha: str) -> str:
        """The commit's subject line."""
        return self.run("show", "-s", "--format=%s", sha, check=True).stdout.strip()

    def message(self, sha: str) -> str:
        """The full commit message (what the intent labeller is shown — never the diff)."""
        return self.run("show", "-s", "--format=%B", sha, check=True).stdout.strip()

    def parent(self, sha: str) -> str:
        """The first parent's sha — the commit every trial is replayed from."""
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
        """``git diff --stat <ref>`` of the working tree."""
        return self.run("diff", "--stat", ref, cwd=cwd, check=True).stdout

    def diff_text(self, ref: str, *, cwd: str | Path | None = None) -> str:
        """The full unified diff of the working tree against ``ref`` (tracked files
        only — the workspace adds untracked additions itself)."""
        return self.run("diff", ref, cwd=cwd, check=True).stdout

    def show_file(self, sha: str, path: str) -> str | None:
        """``path``'s content at ``sha`` from the object store, or ``None`` if the
        commit has no such file."""
        r = self.run("show", f"{sha}:{path}")
        return r.stdout if r.ok else None

    def show_blob(self, sha: str, path: str) -> bytes | None:
        """``path``'s exact BYTES at ``sha`` (no newline translation), or ``None`` when the
        commit has no such blob. Dependency inputs are hashed from these bytes, so a key
        computed from the object store equals one computed from the same file on disk."""
        argv = [self.git_binary, "-C", str(self.path), "cat-file", "blob", f"{sha}:{path}"]
        try:
            p = subprocess.run(argv, capture_output=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as e:
            raise GitError(argv, 124, f"timed out after {self.timeout}s") from e
        return p.stdout if p.returncode == 0 else None

    def tree_names(self, sha: str, directory: str = "") -> list[str]:
        """The entry names directly under ``directory`` (the root when empty) at ``sha``."""
        spec = f"{sha}:{directory}" if directory else sha
        r = self.run("ls-tree", "--name-only", spec)
        return r.lines if r.ok else []

    # --- mutations (worktree-scoped) --------------------------------------------
    def checkout_paths(self, sha: str, paths: list[str], *, cwd: str | Path) -> None:
        """Overlay ``paths`` from ``sha`` into the worktree at ``cwd``."""
        if not paths:
            return
        self.run("checkout", sha, "--", *paths, cwd=cwd, check=True)

    def worktree_add(self, dest: Path, ref: str) -> None:
        """A detached worktree at ``ref`` (``-f``: reuse a registration a crashed run
        left behind)."""
        self.run("worktree", "add", "-f", "--detach", str(dest), ref, check=True)

    def worktree_remove(self, dest: Path) -> None:
        """Remove the worktree and prune its registration; best effort (not checked)."""
        self.run("worktree", "remove", "--force", str(dest))
        self.run("worktree", "prune")


# ---------------------------------------------------------------------------
# Cloning
# ---------------------------------------------------------------------------


def local_clone_allowed() -> bool:
    """``CRB_ALLOW_LOCAL_CLONE=1`` (test/dev only) permits ``file://`` sources."""
    return os.environ.get(LOCAL_CLONE_ENV, "").strip() == "1"


def redact_url(url: str) -> str:
    """The URL with any credential removed — safe for logs, events and exceptions.

    ``https://user:token@host/p`` and ``https://token@host/p`` both become
    ``https://host/p`` (a token may sit in the user slot); ``ssh://git@host/p``
    keeps its non-secret username but loses any password; the scp-like
    ``git@host:p`` form is returned unchanged. Anything unparsable is returned as
    ``[unparsable url]`` rather than echoed.
    """
    s = url.strip()
    if "://" not in s:
        return s if not s or _SCP_LIKE_RE.match(s) else "[unparsable url]"
    try:
        parts = urlsplit(s)
    except ValueError:
        return "[unparsable url]"
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, hostport = netloc.rpartition("@")
        if parts.scheme.lower() in {"http", "https"}:
            netloc = hostport
        else:
            user = userinfo.partition(":")[0]
            netloc = f"{user}@{hostport}" if user else hostport
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redact_urls_in(text: str) -> str:
    """Strip ``scheme://userinfo@`` from every URL embedded in free text (git stderr)."""
    return _USERINFO_IN_TEXT_RE.sub(r"\1", text)


def validate_clone_url(url: str, *, allow_local: bool | None = None) -> str:
    """Return ``url`` stripped if it is an acceptable clone source, else raise.

    Accepted: ``https://host/path``, ``ssh://[user@]host[:port]/path`` and the
    scp-like ``user@host:path``. Refused: every other scheme (``http``, ``git``,
    ``ftp`` …), bare local paths (``/srv/x``, ``./x``, ``~/x``) and ``file://`` —
    the last is accepted only when ``allow_local`` is true (default: the
    :data:`LOCAL_CLONE_ENV` switch). Error messages never echo userinfo.
    """
    s = (url or "").strip()
    if not s:
        raise CloneUrlError("clone url is empty")
    if any(ch.isspace() for ch in s):
        raise CloneUrlError("clone url must not contain whitespace")
    if "://" not in s:
        if _SCP_LIKE_RE.match(s):
            return s
        raise CloneUrlError(
            f"clone url {redact_url(s)!r} is not a git URL (https://…, ssh://… or user@host:path); "
            "a local path is registered with clone_path, never cloned"
        )
    try:
        parts = urlsplit(s)
    except ValueError as exc:
        raise CloneUrlError("clone url is not parsable") from exc
    scheme = parts.scheme.lower()
    local_ok = local_clone_allowed() if allow_local is None else allow_local
    if scheme in _SCHEMES_LOCAL:
        if not local_ok:
            raise CloneUrlError(
                f"clone url scheme {scheme!r} is refused (set {LOCAL_CLONE_ENV}=1 on a test or "
                "developer machine only)"
            )
        if not parts.path:
            raise CloneUrlError("file:// clone url has no path")
        return s
    if scheme not in _SCHEMES_ALWAYS:
        raise CloneUrlError(
            f"clone url scheme {scheme!r} is refused; use https:// or ssh:// (or user@host:path)"
        )
    if not parts.hostname:
        raise CloneUrlError(f"clone url {redact_url(s)!r} has no host")
    if not parts.path or parts.path == "/":
        raise CloneUrlError(f"clone url {redact_url(s)!r} has no repository path")
    return s


def clone_repo(
    url: str,
    dest: str | Path,
    *,
    timeout: int = DEFAULT_CLONE_TIMEOUT_S,
    git_binary: str = "git",
    allow_local: bool | None = None,
    auth_header: str | None = None,
) -> str:
    """Clone ``url`` (full history, ``--no-tags``) into ``dest``; return the HEAD sha.

    ``auth_header`` (``"Authorization: Basic …"`` — a GitHub App installation token, see
    src/crb/server/github_app.py) is handed to git through the ``GIT_CONFIG_COUNT``
    environment mechanism as ``http.extraheader``: it never appears in argv, in
    ``.git/config`` or in any error this function raises.

    Invariants:

    * **Idempotent.** An existing git repository at ``dest`` is reused as-is (its
      HEAD is returned, nothing is fetched); a non-empty non-repository ``dest``
      is an error, never overwritten.
    * **Atomic.** git clones into ``<dest>.tmp-<pid>-<ns>`` beside ``dest`` and the
      directory is renamed into place only after a zero exit; a failure or a
      timeout removes the temp directory. Two concurrent callers race on the
      rename and the loser adopts the winner's clone.
    * **Credential-safe.** ``GIT_TERMINAL_PROMPT=0`` so a missing credential fails
      instead of hanging; the URL is redacted in every raised message and in
      ``GitError.argv``.
    * **Fail closed.** A non-zero exit or a timeout is a :class:`GitError`; the
      policy check is a :class:`CloneUrlError` before any process is spawned.
    """
    src = validate_clone_url(url, allow_local=allow_local)
    target = Path(dest)
    safe = redact_url(src)
    if target.exists():
        existing = GitRepo(target, git_binary=git_binary)
        if existing.is_repo():
            return existing.rev_parse()
        if any(target.iterdir()):
            raise GitError(
                [git_binary, "clone", "--quiet", "--no-tags", safe, str(target)],
                1,
                f"destination {target} exists and is not a git repository",
            )
        target.rmdir()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f"{target.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    argv = [git_binary, "clone", "--quiet", "--no-tags", src, str(tmp)]
    # the real argv (may carry a token) runs; the redacted one is what any error shows
    safe_argv = [git_binary, "clone", "--quiet", "--no-tags", safe, str(tmp)]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    if auth_header:
        # one-shot credential for this process only (git ≥ 2.31): not argv, not on disk
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraheader",
                "GIT_CONFIG_VALUE_0": auth_header,
            }
        )
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False, env=env
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GitError(safe_argv, 124, f"clone timed out after {timeout}s") from exc
    if p.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        stderr = redact_urls_in((p.stderr or "").replace(src, safe))
        raise GitError(safe_argv, p.returncode, stderr)
    try:
        os.rename(tmp, target)
    except OSError:
        # lost the race (or dest appeared meanwhile): adopt what is there if it is a repo
        shutil.rmtree(tmp, ignore_errors=True)
        if not GitRepo(target, git_binary=git_binary).is_repo():
            raise
    return GitRepo(target, git_binary=git_binary).rev_parse()
