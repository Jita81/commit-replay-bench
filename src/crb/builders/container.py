"""The builder in a sealed container (ADR-0012; plan P5).

Two things make a builder attempt *unable* — not merely *forbidden* — to recover
the gold commit or reach anything but the model endpoint:

1. :class:`SealedCheckout` — the checkout the builder edits is an **export** of
   the parent tree (``git archive <parent>`` → ``git init`` → one commit), never a
   ``git worktree`` of the main clone. A worktree shares the main clone's object
   store, which holds the commit under test; an export shares nothing. The commit's
   test files are overlaid on top exactly as the orchestrator overlays them on the
   real worktree, and :meth:`SealedCheckout.copy_back` moves the builder's result
   (changed, added and deleted files — never symlinks, never ``.git``) into the real
   worktree, where the unchanged grader runs the belts.
2. :class:`ContainerSession` — the builder process runs in a hardened container
   (``--read-only`` root, ``--cap-drop=ALL``, ``no-new-privileges``, non-root, pid /
   memory / cpu caps) whose **only network is an ``--internal`` bridge shared with
   one sidecar**: the CONNECT-only allowlisting proxy in
   :mod:`crb.builders.egress_proxy`. The builder has no DNS and no default route;
   the sidecar is dual-homed (internal + the operator's egress network) and tunnels
   only to the hosts on the allowlist. The model credential reaches the builder as
   ``--env NAME`` (resolved from the docker *client's* environment) — it is never on
   a command line and never written to disk inside the container.

Every failure to provide that isolation — no daemon, a missing image, a sidecar that
does not come up, a container that cannot launch — is
:class:`~crb.core.execution.SandboxUnavailable`: the run **stops** (ADR-0005). There
is no "build on the host if the container is unavailable" path.

The post-hoc guards (:class:`~crb.builders.base.GitArchaeologyGuard`, the CLI's deny
rules) stay on as belt-and-braces; with a sealed checkout they are no longer
load-bearing, so a guard false positive on honest shell can no longer be the only
thing between a builder and the answer.

Configuration comes from the worker's environment (``CRB_BUILDER__*``, mirrored by
``crb.server.settings.BuilderSettings``) — it is a deployment posture, never a run
parameter: a per-run downgrade to host execution would be a hole, not a feature.

Navigation
----------
What it is:   The sealed-container path: ``SealedCheckout`` (an export of the parent tree as
              its own repository), ``ContainerSession`` (the hardened builder container and
              its egress sidecar) and ``BuilderContainerSettings`` (the worker's posture).
What it does: Makes archaeology impossible rather than forbidden — the builder edits a tree
              whose object store does not contain the commit under test, inside a read-only,
              capability-dropped, non-root container whose only route is a CONNECT-only
              allowlisting proxy; copies regular files back (never symlinks, never ``.git``)
              for the unchanged grader. Every failure to provide that isolation is
              ``SandboxUnavailable`` — the run stops; there is no host fallback.
How:          ``SealedCheckout.create``: ``git archive <parent>`` → ``git init`` + one commit
              → overlay tests (a dangling oracle commit for byte-identity checks) → replicate
              harness fix-ups. ``ContainerSession.__enter__``: verify images → per-attempt
              ``--internal`` network → sidecar on the egress network → wait for ``READY``
              (``EgressSidecar``). ``run_args`` mounts the task's BUILDER dependency set —
              the parent's, never the gold's — read-only under ``/deps`` (ADR-0019).
              ``spawn``/``tools_executor`` hand the builder a container-bound transport;
              ``unconfirmed_kills`` names the containers this session spawned — the build
              streams AND the tool-loop executors' commands — whose enforced kill the
              daemon never confirmed (``DockerStream.kill_confirmed`` is False;
              ``DockerExecutor.unconfirmed_kills``) so the adapter can hand them to the
              worker's reaper instead of losing them.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/builders/sidecar.py (the internal network and the proxy container),
              src/crb/builders/egress_proxy.py (the sidecar's script, mounted read-only),
              src/crb/builders/adapter.py (the caller: ``sealed_build``),
              src/crb/core/execution.py (``DockerExecutor``/``DockerStream``/``DockerSettings``;
              the bounded kill confirmation ``unconfirmed_kills`` reads),
              src/crb/server/reaper.py (reaps what ``unconfirmed_kills`` names),
              src/crb/core/workspace.py (the source worktree and ``touched_files``),
              src/crb/builders/claude_code.py and src/crb/builders/openai_agent.py (receive
              ``overrides_for``), src/crb/core/deps.py (the builder binding it mounts)
Tested by:    tests/test_builders_container.py, tests/test_builders_container_docker.py
Touch when:   onboarding a repository whose tests need a toolchain cache — add it to
              ``CRB_BUILDER__*`` ``extra_ro_mounts`` / the builder image, never a mount of
              ``docker.sock``, ``/`` or ``$HOME`` (refused here); a new host the model
              endpoint needs goes in ``CRB_BUILDER__ALLOW_HOSTS`` (docs/DEPLOYMENT.md); a
              new sealable builder is added to ``SEALABLE_BUILDERS`` with an
              ``overrides_for`` branch.
Claims:       Sealing removes the archaeology vector; it does not make a clean grade
              mergeability (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import contextlib
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.builders import egress_proxy
from crb.builders.sidecar import (
    PROXY_ALIAS,
    PROXY_PORT,
    PROXY_SCRIPT_INSIDE,
    PROXY_START_TIMEOUT_S,
    EgressSidecar,
)
from crb.core.deps import ROLE_BUILDER, BundleMount, DepsBinding, TaskDeps
from crb.core.execution import (
    CancelFn,
    DockerExecutor,
    DockerSettings,
    DockerStream,
    SandboxUnavailable,
    UnconfirmedKill,
    bundle_mount_args,
)
from crb.core.git import GitError, GitRepo
from crb.core.workspace import HARNESS_SYMLINK, Workspace

#: Where the sealed checkout is mounted inside the builder container.
WORKDIR = "/work"
#: The sidecar's alias and port, the script's mount point and the READY wait live with the
#: sidecar (src/crb/builders/sidecar.py) and are re-exported here.
DEFAULT_ALLOW_HOSTS: tuple[str, ...] = ("api.anthropic.com",)

ENV_PREFIX = "CRB_BUILDER__"
EXECUTOR_HOST = "host"
EXECUTOR_DOCKER = "docker"

#: Environment variable NAMES whose values are passed to ``docker run`` as ``--env NAME``
#: (looked up from the client's environment) rather than ``--env NAME=value`` on argv.
_SECRET_ENV_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
#: Host-side variables that must NOT be forwarded into the container (they describe
#: the host, not the container) — the session sets container-appropriate ones.
_HOST_ONLY_ENV: frozenset[str] = frozenset({"PATH", "HOME", "TMPDIR", "TERM", "USER", "LOGNAME"})
#: What the docker CLIENT needs from the worker's environment to reach the daemon.
_CLIENT_ENV_PASSTHROUGH: tuple[str, ...] = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
_CLIENT_ENV_PREFIXES: tuple[str, ...] = ("DOCKER_",)

#: Builders whose attempt runs against a sealed checkout. ``fixture_gold`` (test-only)
#: replays the commit's own sources from the main clone and is left unsealed by design.
SEALABLE_BUILDERS: frozenset[str] = frozenset({"claude_code", "openai_agent", "editblock"})


def is_secret_env_name(name: str) -> bool:
    """Names that look like credentials are passed to docker by NAME only (never on argv)."""
    return bool(_SECRET_ENV_RE.search(name))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuilderContainerSettings:
    """The worker's builder-container posture (``CRB_BUILDER__*``).

    ``image`` is the builder image (``deploy/Dockerfile.builder``); ``proxy_image``
    is the sidecar's (defaults to ``image`` — it only needs ``python3``);
    ``allow_hosts`` the egress allowlist (``host`` or ``host:port``; empty ⇒ the
    builder runs with **no** network at all and no sidecar); ``egress_network`` the
    docker network the sidecar uses to reach the endpoint (``bridge`` by default).
    ``user`` defaults to the worker's own uid:gid so the bind-mounted checkout is
    writable without widening its permissions; root is refused.
    """

    image: str
    proxy_image: str = ""
    allow_hosts: tuple[str, ...] = DEFAULT_ALLOW_HOSTS
    egress_network: str = "bridge"
    memory: str = "4g"
    cpus: str = "2"
    pids_limit: int = 1024
    tmp_size: str = "1g"
    user: str = ""
    docker_binary: str = ""
    #: Extra read-only bind mounts ``{host_path: container_path}`` (toolchain caches).
    extra_ro_mounts: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.image.strip():
            raise SandboxUnavailable("builder executor 'docker' requires CRB_BUILDER__IMAGE")
        object.__setattr__(self, "image", self.image.strip())
        object.__setattr__(self, "proxy_image", (self.proxy_image or self.image).strip())
        hosts = tuple(h.strip() for h in self.allow_hosts if str(h).strip())
        try:
            egress_proxy.parse_allow(list(hosts))
        except ValueError as exc:
            raise SandboxUnavailable(f"builder egress allowlist invalid: {exc}") from exc
        object.__setattr__(self, "allow_hosts", hosts)
        user = self.user.strip() or f"{os.getuid()}:{os.getgid()}"
        uid = user.split(":", 1)[0].strip().lower()
        if uid in {"", "0", "root"}:
            raise SandboxUnavailable(
                f"refusing to run the builder container as root (user={user!r}); "
                "set CRB_BUILDER__USER to a non-root uid:gid"
            )
        object.__setattr__(self, "user", user)
        if self.pids_limit <= 0:
            raise SandboxUnavailable("builder pids_limit must be positive")
        for host in self.extra_ro_mounts:
            h = str(host)
            if h.endswith("docker.sock") or h in {"/", str(Path.home())}:
                raise SandboxUnavailable(f"refusing to mount {h!r} into the builder container")
        object.__setattr__(self, "extra_ro_mounts", dict(self.extra_ro_mounts))

    @property
    def networked(self) -> bool:
        """An empty allowlist means no sidecar and ``--network=none`` for the builder."""
        return bool(self.allow_hosts)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BuilderContainerSettings | None:
        """``None`` unless ``CRB_BUILDER__EXECUTOR=docker``; otherwise the settings, or
        :class:`SandboxUnavailable` when they are incomplete (fail closed, never host)."""
        e = os.environ if env is None else env
        kind = e.get(f"{ENV_PREFIX}EXECUTOR", "").strip().lower()
        if kind in {"", EXECUTOR_HOST, "local"}:
            return None
        if kind != EXECUTOR_DOCKER:
            raise SandboxUnavailable(
                f"{ENV_PREFIX}EXECUTOR={kind!r} is not one of {EXECUTOR_HOST!r}, {EXECUTOR_DOCKER!r}"
            )

        def get(name: str, default: str = "") -> str:
            return e.get(f"{ENV_PREFIX}{name}", default).strip()

        hosts_raw = get("ALLOW_HOSTS", ",".join(DEFAULT_ALLOW_HOSTS))
        hosts = tuple(h.strip() for h in hosts_raw.split(",") if h.strip())
        pids = get("PIDS_LIMIT")
        return cls(
            image=get("IMAGE"),
            proxy_image=get("PROXY_IMAGE"),
            allow_hosts=hosts,
            egress_network=get("EGRESS_NETWORK", "bridge") or "bridge",
            memory=get("MEMORY", "4g") or "4g",
            cpus=get("CPUS", "2") or "2",
            pids_limit=int(pids) if pids.isdigit() else 1024,
            tmp_size=get("TMP_SIZE", "1g") or "1g",
            user=get("USER"),
            docker_binary=get("DOCKER_BINARY"),
        )

    def describe(self) -> dict[str, Any]:
        """Apparatus-stamp shape (no secrets)."""
        return {
            "builder_executor": EXECUTOR_DOCKER,
            "image": self.image,
            "proxy_image": self.proxy_image,
            "allow_hosts": list(self.allow_hosts),
            "egress_network": self.egress_network if self.networked else "none",
            "user": self.user,
            "memory": self.memory,
            "cpus": self.cpus,
            "pids_limit": self.pids_limit,
        }


# ---------------------------------------------------------------------------
# Sealed checkout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One difference between the sealed checkout and its parent commit."""

    path: str
    kind: str  # added | modified | deleted


@dataclass(frozen=True)
class CopyBack:
    """What :meth:`SealedCheckout.copy_back` did. ``refused`` lists paths that were
    NOT transferred and why — a symlink, a ``.git`` component, a path that escapes."""

    copied: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """The ``builder.copy_back`` event payload."""
        return {
            "copied": list(self.copied),
            "deleted": list(self.deleted),
            "unchanged": list(self.unchanged),
            "refused": list(self.refused),
        }


_GIT_IDENTITY: tuple[str, ...] = (
    "-c",
    "user.name=crb sealed checkout",
    "-c",
    "user.email=crb@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.autocrlf=false",
)


def _git_env() -> dict[str, str]:
    """A git environment that reads NO host configuration (no global filters, no
    signing, no templates) — the sealed repository must be reproducible and inert."""
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TMPDIR")}
    env.setdefault("LANG", "C.UTF-8")
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["HOME"] = tempfile.gettempdir()
    return env


def _git(git: str, cwd: Path, *args: str, timeout: int = 300) -> bytes:
    """``git -C cwd <identity> args`` with the inert environment; raises :class:`GitError`.
    Returns raw stdout (blobs are bytes)."""
    argv = [git, "-C", str(cwd), *_GIT_IDENTITY, *args]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False, env=_git_env())
    except subprocess.TimeoutExpired as e:
        raise GitError(argv, 124, f"timed out after {timeout}s") from e
    if p.returncode != 0:
        raise GitError(argv, p.returncode, p.stderr.decode("utf-8", "replace"))
    return p.stdout


def _safe_rel(rel: str) -> str:
    """A repo-relative path that stays inside the tree and never names ``.git``,
    or ``""`` when it must be refused."""
    if not rel or rel.startswith("/") or "\\" in rel:
        return ""
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or ".." in parts or ".git" in parts:
        return ""
    return "/".join(parts)


class SealedCheckout:
    """A standalone git repository holding exactly the parent tree — and nothing else.

    Guarantees (each has a test in ``tests/test_builders_container.py``):

    * the object store contains one commit (``rev-list --count HEAD == 1``) plus, in
      sighted mode, one *dangling* commit of the overlaid tests that only exists so
      :meth:`~crb.core.workspace.Workspace.tests_byte_identical` has a reference —
      the commit under test is not there (``git cat-file -e <sha>`` fails);
    * ``.git`` is a directory owned by this checkout, not a ``gitdir:`` file pointing
      at the main clone, and there are no alternates;
    * the working tree equals the parent tree byte for byte — ``export-ignore`` /
      ``export-subst`` attributes, which ``git archive`` would honour, are undone by
      reading those paths back from the parent's own blobs;
    * the overlaid test files are byte-identical to the real worktree's, and harness
      fix-ups (``node_modules`` symlink, ``write_if_missing`` hooks) are replicated so
      the builder's tests run the way the grader's will.
    """

    def __init__(
        self,
        root: Path,
        source: Workspace,
        *,
        commit: str,
        oracle_commit: str,
        skipped_links: Sequence[str] = (),
    ) -> None:
        self.root = Path(root)
        self.source = source
        self.repo = GitRepo(self.root, git_binary=source.repo.git_binary)
        self.commit = commit
        self.oracle_commit = oracle_commit
        #: tar members refused at extraction (links escaping the tree); informational
        self.skipped_links = tuple(skipped_links)
        #: host paths a harness symlink points at (mounted read-only into the container)
        self.link_targets: dict[str, str] = {}
        self._ws: Workspace | None = None

    # --- creation ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        ws: Workspace,
        dest: Path,
        *,
        test_files: Sequence[str] = (),
        carry_files: Sequence[str] = (),
    ) -> SealedCheckout:
        """Export ``ws.parent`` into ``dest`` as its own repository; overlay ``test_files``
        (their content is taken from ``ws`` — the orchestrator already overlaid the
        commit's version there) and replicate the harness fix-ups.

        ``carry_files`` are the REAL worktree's current versions of source files a prior
        attempt already changed (the pre-flight's repair call): they are committed into the
        sealed base, so the repair builder starts from the first attempt's edits and
        :meth:`diff_against_parent` reports only what the repair changed (CodeRabbit finding
        on PR #3, 2026-09-15 — without this a sealed repair started from the bare parent
        and silently discarded the first attempt)."""
        dest = Path(dest)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir()
        git = ws.repo.git_binary
        skipped = cls._export_tree(ws, dest)
        cls._backfill_attribute_paths(ws, dest)
        with tempfile.TemporaryDirectory(prefix="crb-git-template-") as empty:
            _git(git, dest, "init", "-q", f"--template={empty}")
        _git(git, dest, "add", "-A", "-f")
        _git(git, dest, "commit", "-q", "--allow-empty", "-m", "sealed parent tree")
        carried = [t for t in (_safe_rel(t) for t in carry_files) if t]
        if carried:
            for rel in carried:
                if (ws.root / rel).is_file():
                    cls._copy_file(ws.root / rel, dest / rel)
                else:
                    (dest / rel).unlink(missing_ok=True)  # the prior attempt deleted it
            _git(git, dest, "add", "-A", "-f", "--", *carried)
            _git(git, dest, "commit", "-q", "--allow-empty", "-m", "prior attempt's edits")
        c1 = _git(git, dest, "rev-parse", "HEAD").decode().strip()
        oracle = c1
        tests = [t for t in (_safe_rel(t) for t in test_files) if t]
        if tests:
            for rel in tests:
                cls._copy_file(ws.root / rel, dest / rel)
            _git(git, dest, "add", "-f", "--", *tests)
            tree = _git(git, dest, "write-tree").decode().strip()
            oracle = (
                _git(git, dest, "commit-tree", tree, "-p", c1, "-m", "overlaid tests")
                .decode()
                .strip()
            )
            # the index keeps the tests staged (as `git checkout <sha> -- paths` leaves
            # them in the real worktree); HEAD stays at the parent tree
        sealed = cls(dest, ws, commit=c1, oracle_commit=oracle, skipped_links=skipped)
        sealed._replicate_harness()
        return sealed

    @staticmethod
    def _export_tree(ws: Workspace, dest: Path) -> list[str]:
        """``git archive <parent>`` → ``dest``. One tree object is serialised: no
        history, no refs, no other objects can come along. Links that would point
        outside ``dest`` are refused by the ``data`` filter and reported."""
        skipped: list[str] = []
        with tempfile.NamedTemporaryFile(prefix="crb-sealed-", suffix=".tar", delete=False) as fh:
            tar_path = Path(fh.name)
        try:
            _git(
                ws.repo.git_binary,
                ws.root,
                "archive",
                "--format=tar",
                "-o",
                str(tar_path),
                ws.parent,
                timeout=ws.repo.timeout,
            )
            with tarfile.open(tar_path) as tar:
                for member in tar.getmembers():
                    if member.name in ("pax_global_header",) or not _safe_rel(member.name):
                        continue
                    try:
                        tar.extract(member, path=dest, filter="data")
                    except tarfile.FilterError:
                        skipped.append(member.name)
        finally:
            tar_path.unlink(missing_ok=True)
        return skipped

    @staticmethod
    def _backfill_attribute_paths(ws: Workspace, dest: Path) -> None:
        """Paths ``git archive`` omitted (``export-ignore`` — on the file or on any
        directory above it) or rewrote (``export-subst``) are restored from the
        parent's own blobs, so the sealed tree is the parent tree — not the parent's
        *release* tree. Omissions are found by comparing the extracted tree with
        ``ls-tree``; substitutions by asking ``check-attr``."""
        git = ws.repo.git_binary
        listing = _git(git, ws.root, "ls-tree", "-r", "-z", ws.parent)
        entries: dict[str, str] = {}  # path → mode
        for rec in listing.split(b"\0"):
            if not rec:
                continue
            meta, _, path = rec.partition(b"\t")
            mode, kind, _sha = meta.decode("utf-8", "replace").split(" ", 2)
            if kind == "blob":
                entries[path.decode("utf-8", "surrogateescape")] = mode
        if not entries:
            return
        affected: set[str] = {
            rel for rel in entries if not ((dest / rel).is_symlink() or (dest / rel).exists())
        }
        argv = [git, "-C", str(ws.root), "check-attr", "-z", "--stdin", "export-subst"]
        p = subprocess.run(
            argv,
            input="\0".join(entries) + "\0",
            capture_output=True,
            text=True,
            timeout=ws.repo.timeout,
            check=False,
            env=_git_env(),
        )
        if p.returncode != 0:
            raise GitError(argv, p.returncode, p.stderr or "")
        fields = p.stdout.split("\0")
        for i in range(0, len(fields) - 2, 3):
            attr_path, _attr, value = fields[i : i + 3]
            if value not in ("unspecified", "unset"):
                affected.add(attr_path)
        for rel in sorted(affected):
            safe = _safe_rel(rel)
            if not safe:
                continue
            mode = entries[rel]
            blob = _git(git, ws.root, "cat-file", "blob", f"{ws.parent}:{rel}")
            target = dest / safe
            if target.is_symlink() or target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                link = blob.decode("utf-8", "surrogateescape")
                # relative and inside the tree, as the tar ``data`` filter demands
                if _safe_rel(posixpath.normpath(posixpath.join(posixpath.dirname(safe), link))):
                    with contextlib.suppress(OSError):
                        target.symlink_to(link)
                continue
            target.write_bytes(blob)
            if mode == "100755":
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    @staticmethod
    def _copy_file(src: Path, dst: Path) -> None:
        """Byte copy of a regular file (mode bits kept); a symlink source is an error."""
        if src.is_symlink():
            raise SandboxUnavailable(f"refusing to copy a symlink into the sealed checkout: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink():
            dst.unlink()
        shutil.copyfile(src, dst)
        shutil.copymode(src, dst)

    def _replicate_harness(self) -> None:
        """Harness fix-ups from the source worktree: content files are copied, symlinks
        recreated with the same absolute target (and that target recorded for a
        read-only mount into the container) and excluded from git as they are there."""
        excludes: list[str] = []
        for rel, recorded in self.source.harness_files.items():
            safe = _safe_rel(rel)
            if not safe:
                continue
            src = self.source.root / safe
            dst = self.root / safe
            if recorded == HARNESS_SYMLINK:
                if not src.is_symlink():
                    continue
                target = os.readlink(src)
                if not os.path.isabs(target):
                    target = os.path.normpath(os.path.join(os.path.dirname(src), target))
                if dst.exists() or dst.is_symlink():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    dst.symlink_to(target)
                    self.link_targets[safe] = target
                    excludes.append(f"/{safe}")
            elif src.is_file() and not dst.exists():
                self._copy_file(src, dst)
        if excludes:
            exclude = self.root / ".git" / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as fh:
                fh.write("".join(f"{e}\n" for e in excludes))

    # --- the builder's view ------------------------------------------------------
    def workspace(self) -> Workspace:
        """The :class:`Workspace` a builder operates on: ``HEAD`` is the parent tree
        (``sha == oracle_commit`` so belt-1 style checks compare against the overlaid
        tests, ``parent == commit`` so "what changed" is against the parent)."""
        if self._ws is None:
            ws = Workspace(self.repo, self.root, sha=self.oracle_commit, parent=self.commit)
            ws.harness_files = dict(self.source.harness_files)
            self._ws = ws
        return self._ws

    def diff_against_parent(self) -> list[Change]:
        """Every path that differs from the parent tree (the overlaid tests included —
        :meth:`copy_back` skips what is byte-identical to the real worktree)."""
        ws = self.workspace()
        tracked = set(
            ws.repo.run(
                "ls-tree", "-r", "-z", "--name-only", "HEAD", cwd=ws.root, check=True
            ).stdout.split("\0")
        )
        out: list[Change] = []
        for rel in ws.touched_files():
            p = self.root / rel
            if p.is_symlink() or p.exists():
                out.append(Change(rel, "modified" if rel in tracked else "added"))
            else:
                out.append(Change(rel, "deleted"))
        return out

    def copy_back(self, ws: Workspace) -> CopyBack:
        """Transfer the builder's result into the real worktree ``ws`` for grading.

        Regular files only: a symlink in the sealed checkout, a symlink (or directory)
        at the destination, a ``.git`` component or a path that resolves outside
        ``ws.root`` is refused and reported, never followed. Byte-identical files
        (the overlaid tests, untouched harness files) are left alone. A tampered test
        IS copied — belt 1 on the host must see it.
        """
        root = ws.root.resolve()
        copied: list[str] = []
        deleted: list[str] = []
        unchanged: list[str] = []
        refused: list[str] = []
        for change in self.diff_against_parent():
            rel = _safe_rel(change.path)
            if not rel:
                refused.append(f"{change.path}: unsafe path")
                continue
            src = self.root / rel
            dst = ws.root / rel
            try:
                inside = root == dst.parent.resolve() or root in dst.parent.resolve().parents
            except OSError:
                inside = False
            if not inside:
                refused.append(f"{rel}: resolves outside the worktree")
                continue
            if dst.is_symlink():
                refused.append(f"{rel}: destination is a symlink")
                continue
            if change.kind == "deleted":
                if dst.is_dir():
                    refused.append(f"{rel}: destination is a directory")
                elif dst.exists():
                    dst.unlink()
                    deleted.append(rel)
                else:
                    unchanged.append(rel)
                continue
            if src.is_symlink():
                refused.append(f"{rel}: symlink (not transferred)")
                continue
            if not src.is_file():
                refused.append(f"{rel}: not a regular file")
                continue
            if dst.is_dir():
                refused.append(f"{rel}: destination is a directory")
                continue
            data = src.read_bytes()
            if dst.is_file() and dst.read_bytes() == data and _mode(dst) == _mode(src):
                unchanged.append(rel)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            shutil.copymode(src, dst)
            copied.append(rel)
        return CopyBack(tuple(copied), tuple(deleted), tuple(unchanged), tuple(refused))

    def remove(self) -> None:
        """Delete the checkout (best effort; a leftover is disk, not a leak of anything)."""
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> SealedCheckout:
        return self

    def __exit__(self, *exc: object) -> None:
        self.remove()


def _mode(p: Path) -> int:
    """The execute bits of a file — the only mode ``copy_back`` preserves."""
    return stat.S_IMODE(p.stat().st_mode) & 0o111


# ---------------------------------------------------------------------------
# The container session (per build attempt)
# ---------------------------------------------------------------------------


def builder_deps_view(binding: DepsBinding) -> tuple[list[BundleMount], dict[str, str]]:
    """The builder's view of a sealed set: every mount moved under ``/deps/`` (the sealed
    checkout owns ``/work``, so ``/work/node_modules`` becomes ``/deps/node_modules``) and
    the binding's offline environment re-pointed to match. Refuses any binding that is not
    the task's BUILDER set — the parent's; the gold's is never shown to a builder (its module
    list is part of the answer: ADR-0012 amendment, ADR-0019)."""
    if binding.role != ROLE_BUILDER:
        raise SandboxUnavailable(
            f"a builder may be given the parent's dependency set only, not the {binding.role!r} set"
        )
    mounts: list[BundleMount] = []
    env = dict(binding.env)
    for m in binding.mounts:
        inside = m.container_path
        if inside.startswith(WORKDIR + "/"):
            moved = "/deps/" + inside[len(WORKDIR) + 1 :]
            env = {k: v.replace(inside, moved) for k, v in env.items()}
            inside = moved
        mounts.append(BundleMount(host_path=m.host_path, container_path=inside, key=m.key))
    return mounts, env


def builder_run_args(
    settings: BuilderContainerSettings,
    *,
    checkout: Path,
    env: Mapping[str, str],
    timeout_s: int,
    network: str,
    extra_ro_mounts: Mapping[str, str] | None = None,
    deps: DepsBinding | None = None,
) -> list[str]:
    """The ``docker run`` options for the builder container (tests assert on these).

    ``network`` is the internal network's name, or ``"none"``. Secret-named variables
    are passed as ``--env NAME`` so their values never appear on a command line. ``deps``
    — the task's BUILDER binding, the parent's sealed set — is mounted read-only with its
    offline environment (:func:`builder_deps_view`); the egress allowlist is untouched.
    """
    s = settings
    deps_mounts: list[BundleMount] = []
    if deps is not None and deps.sealed:
        deps_mounts, deps_env = builder_deps_view(deps)
        env = {**deps_env, **env}
    args: list[str] = [
        "--init",
        f"--network={network}",
        f"--memory={s.memory}",
        f"--cpus={s.cpus}",
        f"--pids-limit={s.pids_limit}",
        f"--user={s.user}",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,nosuid,nodev,size={s.tmp_size}",
        "--mount",
        f"type=bind,src={checkout},dst={WORKDIR}",
    ]
    mounts = dict(s.extra_ro_mounts)
    mounts.update(extra_ro_mounts or {})
    for host, inside in mounts.items():
        args += ["--mount", f"type=bind,src={host},dst={inside},readonly"]
    args += bundle_mount_args(deps_mounts)
    for k, v in sorted(env.items()):
        args += ["--env", k if is_secret_env_name(k) else f"{k}={v}"]
    args += ["--workdir", WORKDIR, f"--stop-timeout={max(1, int(timeout_s))}", s.image]
    return args


def container_env(env: Mapping[str, str], *, proxy_url: str) -> dict[str, str]:
    """The builder's environment as seen inside the container: the caller's variables
    minus the host-only ones, ``HOME=/tmp``, and the proxy variables when networked."""
    out = {k: v for k, v in env.items() if k not in _HOST_ONLY_ENV}
    out["HOME"] = "/tmp"
    out["TMPDIR"] = "/tmp"
    out.setdefault("LANG", "C.UTF-8")
    out["CI"] = "1"
    out["NO_COLOR"] = "1"
    if proxy_url:
        out["HTTPS_PROXY"] = proxy_url
        out["HTTP_PROXY"] = proxy_url
        out["https_proxy"] = proxy_url
        out["http_proxy"] = proxy_url
        out["NO_PROXY"] = ""
    return out


def client_env(secrets: Mapping[str, str]) -> dict[str, str]:
    """The docker CLIENT's environment: what it needs to find the daemon, plus the
    secret values ``--env NAME`` resolves. Nothing else from the worker leaks."""
    out = {k: v for k, v in os.environ.items() if k in _CLIENT_ENV_PASSTHROUGH}
    out.update({k: v for k, v in os.environ.items() if k.startswith(_CLIENT_ENV_PREFIXES)})
    out.update(secrets)
    return out


class ContainerSession:
    """One build attempt's containers, created on enter and torn down on exit.

    Enter: verify the images, create the per-attempt ``--internal`` network, start the
    sidecar on the egress network, join it to the internal network as ``proxy``, wait
    for its ``READY`` line. Exit: remove the sidecar and the network. Any step that
    fails is :class:`SandboxUnavailable`; nothing is ever half-provisioned silently.
    """

    def __init__(
        self,
        settings: BuilderContainerSettings,
        checkout: SealedCheckout,
        *,
        cancel: CancelFn | None = None,
        executor: DockerExecutor | None = None,
        label: str = "",
        deps: TaskDeps | None = None,
    ) -> None:
        self.settings = settings
        self.checkout = checkout
        #: the task's dependencies (ADR-0019); the builder is only ever given ``deps.builder``
        self.deps = deps
        self.cancel = cancel
        self.executor = executor or DockerExecutor(
            DockerSettings(
                image=settings.image,
                memory=settings.memory,
                cpus=settings.cpus,
                pids_limit=settings.pids_limit,
                user=settings.user,
                tmp_size=settings.tmp_size,
                extra_ro_mounts=settings.extra_ro_mounts,
                docker_binary=settings.docker_binary,
            ),
            cancel=cancel,
        )
        self.id = f"{(label or 'b').strip('-')[:24]}-{uuid.uuid4().hex[:8]}"
        self.network = f"crb-b-{self.id}" if settings.networked else "none"
        self.proxy_name = f"crb-proxy-{self.id}"
        self.build_name = f"crb-build-{self.id}"
        self.sidecar: EgressSidecar | None = None
        #: Every stream :meth:`spawn` returned, for :meth:`unconfirmed_kills`.
        self.streams: list[DockerStream] = []
        #: Every executor :meth:`tools_executor` handed out (the ``openai_agent`` tool
        #: loop's commands run through it), for :meth:`unconfirmed_kills`.
        self.tools_executors: list[DockerExecutor] = []

    # --- docker plumbing ---------------------------------------------------------
    def _docker(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        """One docker CLI call with the client's minimal environment (no secrets)."""
        return subprocess.run(
            [self.executor.docker, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=client_env({}),
        )

    def _must(self, *args: str, what: str, timeout: int = 120) -> str:
        """``_docker`` that fails closed: any error is ``SandboxUnavailable(what: …)``."""
        try:
            r = self._docker(*args, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxUnavailable(f"{what}: {type(exc).__name__}: {exc}") from exc
        if r.returncode != 0:
            raise SandboxUnavailable(f"{what}: {(r.stderr or r.stdout).strip()[:400]}")
        return r.stdout.strip()

    @property
    def proxy_url(self) -> str:
        """The sidecar as the builder sees it on the internal network (``""`` unnetworked)."""
        return f"http://{PROXY_ALIAS}:{PROXY_PORT}" if self.settings.networked else ""

    @property
    def ro_mounts(self) -> dict[str, str]:
        """Harness symlink targets (e.g. the main clone's ``node_modules``) mounted at
        their own path so the replicated links resolve inside the container."""
        return {t: t for t in sorted(set(self.checkout.link_targets.values()))}

    # --- lifecycle ---------------------------------------------------------------
    def __enter__(self) -> ContainerSession:
        s = self.settings
        self.executor.require_image(s.image)
        if not s.networked:
            return self
        self.executor.require_image(s.proxy_image)
        try:
            self._start_proxy()
        except BaseException:
            self.close()
            raise
        return self

    def _start_proxy(self) -> None:
        """Start the egress sidecar (src/crb/builders/sidecar.py): the internal network, the
        proxy on the egress network joined to it as ``proxy``, its ``READY`` line — fail
        closed at every step."""
        s = self.settings
        self.sidecar = EgressSidecar(
            self._docker,
            network=self.network,
            proxy_name=self.proxy_name,
            allow_hosts=s.allow_hosts,
            egress_network=s.egress_network,
            proxy_image=s.proxy_image,
            user=s.user,
            script=self.checkout.root.parent / f"crb-egress-{self.id}.py",
        )
        self.sidecar.start(what="builder")

    @property
    def proxy_log(self) -> str:
        """The sidecar's log tail (its allow / deny decisions), kept after close."""
        return self.sidecar.log if self.sidecar is not None else ""

    def close(self) -> None:
        """Tear down; never raises (the proxy's log tail stays readable as ``proxy_log``)."""
        if self.sidecar is not None:
            self.sidecar.close()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- what the builders get -----------------------------------------------------
    def run_args(self, env: Mapping[str, str], *, timeout_s: int) -> list[str]:
        """The ``docker run`` options for this session's builder container."""
        return builder_run_args(
            self.settings,
            checkout=self.checkout.root,
            env=env,
            timeout_s=timeout_s,
            network=self.network,
            extra_ro_mounts=self.ro_mounts,
            deps=self.deps.builder if self.deps is not None else None,
        )

    def spawn(
        self, argv: list[str], env: Mapping[str, str], cwd: Path, timeout_s: int
    ) -> DockerStream:
        """The ``SpawnFn`` for :class:`~crb.builders.claude_code.ClaudeCodeBuilder`:
        the same argv, run inside the container over the sealed checkout, its stdout
        streamed back unchanged. Host paths in argv (the prompt names the checkout)
        are rewritten to :data:`WORKDIR`."""
        if Path(cwd).resolve() != self.checkout.root.resolve():
            raise SandboxUnavailable(
                f"builder asked to run in {cwd}, but only the sealed checkout is mounted"
            )
        inside = container_env(env, proxy_url=self.proxy_url)
        secrets = {k: v for k, v in inside.items() if is_secret_env_name(k)}
        host = str(cwd)
        rewritten = [a.replace(host, WORKDIR) for a in argv]
        stream = self.executor.stream(
            self.run_args(inside, timeout_s=timeout_s),
            argv=rewritten,
            client_env=client_env(secrets),
            timeout_s=timeout_s,
            name=self.build_name,
        )
        self.streams.append(stream)
        return stream

    def unconfirmed_kills(self) -> list[UnconfirmedKill]:
        """The containers this session spawned whose enforced kill (cancel or the wall
        clock) the daemon did NOT confirm within the confirmation bound: the build
        streams with ``kill_confirmed is False`` (``DockerStream.KILL_CONFIRM_S``) and
        every kill the tool-loop executors recorded (``DockerExecutor.unconfirmed_kills``,
        the ``openai_agent`` model's commands). Each may still be running: the caller
        must record it and hand it to the reaper (src/crb/server/reaper.py); an empty
        list means every kill this session issued was confirmed, or none was issued."""
        kills = [
            UnconfirmedKill(container=s.name, bound_s=float(s.KILL_CONFIRM_S))
            for s in self.streams
            if s.kill_confirmed is False
        ]
        for ex in self.tools_executors:
            kills.extend(ex.unconfirmed_kills)
        return kills

    def tools_executor(self) -> DockerExecutor:
        """For the in-process tool loop (``openai_agent``): its commands run in the
        builder image over the sealed checkout with ``--network=none`` — the loop
        itself (trusted worker code) talks to the model; the model's commands do not.
        The executor is remembered so :meth:`unconfirmed_kills` reports a command
        container its kill could not confirm, exactly as it reports a build stream."""
        ex = DockerExecutor(
            DockerSettings(
                image=self.settings.image,
                memory=self.settings.memory,
                cpus=self.settings.cpus,
                pids_limit=self.settings.pids_limit,
                user=self.settings.user,
                tmp_size=self.settings.tmp_size,
                extra_ro_mounts={**self.settings.extra_ro_mounts, **self.ro_mounts},
                docker_binary=self.settings.docker_binary,
            ),
            cancel=self.cancel,
            verify_daemon=False,
        )
        self.tools_executors.append(ex)
        return ex

    def overrides_for(self, builder: str) -> dict[str, Any]:
        """Constructor overrides that point a builder at this session."""
        if builder == "claude_code":
            return {"spawn": self.spawn, "claude_binary": "claude", "workdir_alias": WORKDIR}
        if builder == "openai_agent":
            return {"executor": self.tools_executor()}
        return {}


SessionFactory = Callable[..., ContainerSession]


# ---------------------------------------------------------------------------
# Doctor probe (``crb doctor`` hook — reported to the CLI owner, not wired here)
# ---------------------------------------------------------------------------


def probe_builder_container(
    settings: BuilderContainerSettings | None = None,
) -> tuple[str, str]:
    """``("up" | "down" | "off", detail)`` for ``crb doctor``: the daemon answers, the
    builder image and the proxy image are present. ``off`` when the worker's posture
    is host execution. Never raises."""
    try:
        s = settings if settings is not None else BuilderContainerSettings.from_env()
    except SandboxUnavailable as exc:
        return "down", str(exc)
    if s is None:
        return "off", "CRB_BUILDER__EXECUTOR is not 'docker': builders run on the host"
    try:
        ex = DockerExecutor(
            DockerSettings(image=s.image, user=s.user, docker_binary=s.docker_binary)
        )
        ex.require_image(s.image)
        if s.networked:
            ex.require_image(s.proxy_image)
    except SandboxUnavailable as exc:
        return "down", str(exc)
    hosts = ", ".join(s.allow_hosts) if s.networked else "no network"
    return "up", f"image {s.image}; proxy {s.proxy_image}; egress → {hosts}"


__all__ = [
    "DEFAULT_ALLOW_HOSTS",
    "ENV_PREFIX",
    "EXECUTOR_DOCKER",
    "EXECUTOR_HOST",
    "PROXY_ALIAS",
    "PROXY_PORT",
    "PROXY_SCRIPT_INSIDE",
    "PROXY_START_TIMEOUT_S",
    "SEALABLE_BUILDERS",
    "WORKDIR",
    "BuilderContainerSettings",
    "Change",
    "ContainerSession",
    "CopyBack",
    "SealedCheckout",
    "SessionFactory",
    "UnconfirmedKill",
    "builder_deps_view",
    "builder_run_args",
    "client_env",
    "container_env",
    "is_secret_env_name",
    "probe_builder_container",
]
