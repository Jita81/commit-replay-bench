"""Where commands run: on the host, or inside a hardened, network-less container.

The runners (:mod:`crb.core.runners`) build a :class:`Command` — argv, working
directory, environment, timeout, which paths need to be writable — and hand it to
an :class:`Executor`. The executor decides *where* it runs:

* :class:`LocalExecutor` — a plain subprocess on the host with a minimal, explicit
  environment (no inherited secrets) and process-group kill on timeout.
* :class:`DockerExecutor` — ``docker run`` with the full hardening set:
  ``--network=none``, read-only root and worktree, tmpfs scratch only where the
  runner declared it, ``--cap-drop=ALL``, ``no-new-privileges``, non-root user,
  cpu / memory / pid caps. It **fails closed**: no docker binary, no daemon, a
  root user, or a launch failure raise :class:`SandboxUnavailable` — we never
  degrade to running untrusted repository tests in-process.

Only a dep-install phase may ask for network (``Command.network=True``); the
DockerExecutor still applies every other cap to it.

Navigation
----------
What it is:   The executors — ``LocalExecutor`` (host subprocess) and ``DockerExecutor``
              (hardened, network-less container), the ``Command`` / ``ExecResult`` contract
              between them and the runners, and ``DockerStream`` for a long-lived container
              whose output is read as it runs.
What it does: Runs one command with a wall clock and a cancel token and reports exit code,
              output, timeout and cancellation honestly; strips the host environment down
              to an allowlist so a repository's tests never see the operator's secrets; and
              refuses — ``SandboxUnavailable`` — whenever the container cannot be provided
              exactly as hardened (no binary, no daemon, root user, forbidden mount, launch
              failure). It never falls back to the host.
How:          ``Command`` (argv, root, writable paths, network flag) → ``build_argv`` (the
              full ``docker run`` hardening set, asserted on by tests) → ``Popen`` with a
              drain thread polled against the deadline and the cancel token → ``docker
              kill <name>`` / process-group kill → ``ExecResult``; ``make_executor`` picks
              the kind from configuration and fails closed on ``docker`` without settings.
              An enforced docker kill — on ``DockerStream`` AND on the non-stream
              ``DockerExecutor.run`` path the belt / test runner uses — is
              confirmation-ATTEMPTED, bounded: after ``docker kill`` (its own subprocess
              timeout ``DOCKER_KILL_TIMEOUT_S``, 30 s) it polls ``docker inspect -f
              {{.State.Running}}`` for at most ``KILL_CONFIRM_S`` (10 s) in total — every
              inspect call is capped to the time remaining — accepting only the exact
              ``true`` / ``false`` ("no such container" is gone; anything else is unknown,
              never a stop), and neither ``lines()`` nor ``run()`` returns until that attempt
              ends. The attempt CAN end without confirming: a reader MUST read
              ``kill_confirmed`` (on the stream, on the ``ExecResult``) — ``True`` = the
              daemon reported the container not running; ``False`` = the bound was hit and
              the container may still be running (a warning names it; the executor records
              it in ``unconfirmed_kills`` and calls ``on_kill_unconfirmed`` so the worker
              records and reaps it — src/crb/server/reaper.py). The worst-case wait after a
              cancel is therefore the command's timeout + ``_CANCEL_POLL_S`` +
              ``DOCKER_KILL_TIMEOUT_S`` + ``KILL_CONFIRM_S``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/core/runners/base.py (builds the Command, parses the result),
              src/crb/builders/container.py (the sealed builder over ``DockerStream``; it
              reports the streams — and the tool-loop executors — whose kill went
              unconfirmed), src/crb/builders/adapter.py (hands each ``UnconfirmedKill`` to
              the worker),
              src/crb/server/reaper.py (reaps an unconfirmed container from the worker loop
              with ``container_stopped`` + ``docker rm -f``),
              src/crb/core/grade.py and src/crb/core/mine.py (let SandboxUnavailable
              propagate so a run stops), src/crb/server/worker.py (constructs the executor
              from settings and ends the run ``failed: sandbox unavailable``),
              src/crb/observability/probes.py (the health probe that reports the daemon)
Tested by:    tests/test_execution.py, tests/test_sandbox_docker.py,
              tests/test_builders_container.py, tests/test_builders_container_docker.py
Touch when:   never for a new repository (its image, memory and cpu limits are
              ``DockerSettings`` from the repo / deployment config; a toolchain that must
              write somewhere declares ``writable_paths`` in its runner); loosening any
              flag in ``build_argv`` is a security decision — docs/SECURITY.md#31-sandboxed-test-execution--crbcoreexecutiondockerexecutor
              and ADR-0005 must change with it.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

_LOG = logging.getLogger(__name__)

#: Environment variables passed through from the host to a local command. Everything
#: else (tokens, cloud creds, proxies) is dropped: repository test suites must never
#: see the operator's secrets.
_HOST_ENV_PASSTHROUGH: tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TZ",
    "TERM",
    "GOPATH",
    "GOCACHE",
    "GOMODCACHE",
    "GOFLAGS",
    "GOTOOLCHAIN",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "JAVA_HOME",
    "M2_HOME",
    "MAVEN_OPTS",
    "NODE_OPTIONS",
    "npm_config_cache",
)

DEFAULT_TIMEOUT_S = 900

#: ``cancel()`` → True means "stop now": the executor kills the running command and
#: returns ``rc=130, cancelled=True``. Polled every ``_CANCEL_POLL_S``.
CancelFn = Callable[[], bool]
_CANCEL_POLL_S = 1.0

#: The subprocess timeout on one ``docker kill <name>`` call — a hung daemon can hold the
#: client this long before the confirmation attempt even starts.
DOCKER_KILL_TIMEOUT_S: float = 30.0
#: The TOTAL bound on a kill's confirmation attempt (every inspect call gets only the time
#: left), and how often it asks. ``DockerStream`` / ``DockerExecutor`` carry them as class
#: attributes so a test can shorten the bound.
KILL_CONFIRM_S: float = 10.0
KILL_CONFIRM_STEP_S: float = 0.1


class SandboxUnavailable(RuntimeError):
    """Docker isolation was requested but cannot be provided safely. FAIL CLOSED."""


@dataclass(frozen=True)
class ExecResult:
    """What a command did. ``returncode`` is 124 on timeout and 130 on cancellation
    (the shell conventions) so a runner that only looks at the code still fails
    closed; ``timed_out`` / ``cancelled`` say which."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_s: float = 0.0
    cancelled: bool = False
    #: Docker only, after an enforced kill (``cancelled`` / ``timed_out``): ``True`` — the
    #: daemon reported the container not running; ``False`` — the confirmation bound was
    #: hit and ``container`` MAY STILL BE RUNNING (the executor has already reported it);
    #: ``None`` — no kill was issued (or not a container).
    kill_confirmed: bool | None = None
    container: str = ""

    @property
    def ok(self) -> bool:
        """Exit 0 AND neither enforced stop — a killed command is never ok."""
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    @property
    def combined(self) -> str:
        """stdout then stderr, for parsers and the redacted tail in evidence."""
        return self.stdout + ("\n" + self.stderr if self.stderr else "")


@dataclass(frozen=True)
class UnconfirmedKill:
    """A container whose ``docker kill`` was issued but never confirmed within
    ``bound_s`` seconds — it may still be running. Produced by :class:`DockerStream`
    (read through ``ContainerSession.unconfirmed_kills``) and by
    :meth:`DockerExecutor.run`'s cancel path (``DockerExecutor.unconfirmed_kills`` and
    its ``on_kill_unconfirmed`` callback); consumed by the worker's reaper."""

    container: str
    bound_s: float


#: ``on_kill_unconfirmed(kill)`` — how a :class:`DockerExecutor` reports a container its
#: cancel / wall-clock kill could not confirm stopped. The callback must not raise; the
#: executor swallows (and logs) anything it does.
KillUnconfirmedFn = Callable[[UnconfirmedKill], None]


@dataclass(frozen=True)
class Command:
    """A command to run inside a worktree.

    ``root`` is the worktree on the host; ``cwd_rel`` is where to run relative to it.
    ``writable_paths`` are root-relative paths the command needs to write (build
    caches, ``target/``…); a sandboxed executor mounts tmpfs there and nothing else.
    """

    argv: tuple[str, ...]
    root: Path
    cwd_rel: str = "."
    env: Mapping[str, str] = field(default_factory=dict)
    timeout: int = DEFAULT_TIMEOUT_S
    writable_paths: tuple[str, ...] = ()
    network: bool = False

    def __post_init__(self) -> None:
        if not self.argv:
            raise ValueError("argv must not be empty")
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))
        object.__setattr__(self, "root", Path(self.root).resolve())
        object.__setattr__(self, "env", dict(self.env))
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


class Executor(Protocol):
    """The contract a runner programs against. ``name`` appears on every apparatus
    stamp, so which executor graded a row is always visible."""

    name: str

    def run(self, cmd: Command) -> ExecResult: ...

    def tool(self, name: str, host_override: str | None = None) -> str:
        """Resolve a toolchain binary name for this execution environment."""
        ...

    def describe(self) -> dict[str, Any]:
        """Apparatus-stamp description (no secrets)."""
        ...


#: The ``subprocess.run``-shaped callable the DockerExecutor uses for its probes and
#: non-cancellable runs — injectable so tests assert on argv without a daemon.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------


class LocalExecutor:
    """Run on the host. Minimal explicit environment; process-group kill on timeout."""

    name = "local"

    def __init__(
        self, *, base_env: Mapping[str, str] | None = None, cancel: CancelFn | None = None
    ) -> None:
        self._base_env = dict(base_env) if base_env is not None else self._host_base_env()
        self._cancel = cancel

    @staticmethod
    def _host_base_env() -> dict[str, str]:
        """The allowlisted slice of the host environment plus the flags that make test
        output parseable (``CI``, ``NO_COLOR``) and keep the worktree clean of
        bytecode."""
        env = {k: v for k, v in os.environ.items() if k in _HOST_ENV_PASSTHROUGH}
        env.setdefault("LANG", "C.UTF-8")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["CI"] = "1"
        env["NO_COLOR"] = "1"
        return env

    def tool(self, name: str, host_override: str | None = None) -> str:
        """A configured override, else the binary on PATH, else the bare name."""
        return host_override or shutil.which(name) or name

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    @property
    def cancel_fn(self) -> CancelFn | None:
        """The run's cancel token, so a builder's own processes can follow it."""
        return self._cancel

    def run(self, cmd: Command) -> ExecResult:
        """Run ``cmd`` on the host under its wall clock and the cancel token. Never
        raises for what the command did; a timeout or cancellation kills the whole
        process group (``start_new_session``) so no test child outlives the run."""
        env = dict(self._base_env)
        env.update(cmd.env)
        cwd = cmd.root / cmd.cwd_rel
        started = time.monotonic()
        proc = subprocess.Popen(
            list(cmd.argv),
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,  # a test that waits for input must fail, never hang
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = cancelled = False
        deadline = started + cmd.timeout
        # Read pipes on a helper thread so a chatty child never blocks on a full pipe
        # while we poll for the deadline and the cancel token.
        box: dict[str, str] = {}

        def _drain() -> None:
            o, e = proc.communicate()
            box["out"], box["err"] = o or "", e or ""

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
        while t.is_alive():
            t.join(_CANCEL_POLL_S)
            if not t.is_alive():
                break
            if self._cancel is not None and self._cancel():
                cancelled = True
                self._kill_group(proc)
                t.join()
                break
            if time.monotonic() >= deadline:
                timed_out = True
                self._kill_group(proc)
                t.join()
                break
        rc = 130 if cancelled else 124 if timed_out else int(proc.returncode or 0)
        return ExecResult(
            rc,
            box.get("out", ""),
            box.get("err", ""),
            timed_out,
            time.monotonic() - started,
            cancelled,
        )

    @staticmethod
    def _kill_group(proc: subprocess.Popen[str]) -> None:
        """SIGKILL the session the command leads (its children included); fall back to
        the process alone if the group is already gone or not ours."""
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


# ---------------------------------------------------------------------------
# Docker (hardened, fail-closed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DockerSettings:
    """The sandbox's shape. Construction itself fails closed: no image, a root user or
    a forbidden mount is :class:`SandboxUnavailable` before any container exists."""

    image: str
    memory: str = "2g"
    cpus: str = "2"
    pids_limit: int = 512
    user: str = "65534:65534"
    workdir: str = "/work"
    tmp_size: str = "512m"
    #: Extra read-only bind mounts ``{host_path: container_path}`` — e.g. a shared
    #: ``node_modules`` or a Go module cache. Never a docker socket, never $HOME.
    extra_ro_mounts: Mapping[str, str] = field(default_factory=dict)
    docker_binary: str = ""

    def __post_init__(self) -> None:
        if not self.image:
            raise SandboxUnavailable("docker sandbox requested without an image")
        uid = self.user.split(":", 1)[0].strip().lower()
        if uid in {"", "0", "root"}:
            raise SandboxUnavailable(
                f"refusing to run untrusted tests as root (user={self.user!r}); use e.g. 65534:65534"
            )
        for host in self.extra_ro_mounts:
            h = str(host)
            if h.endswith("docker.sock") or h in {"/", str(Path.home())}:
                raise SandboxUnavailable(f"refusing to mount {h!r} into the sandbox")
        object.__setattr__(self, "extra_ro_mounts", dict(self.extra_ro_mounts))


class DockerExecutor:
    """Run inside a hardened container. See module docstring for the invariant set.

    An enforced kill on :meth:`run` (the cancel token or the wall clock) is
    confirmation-attempted like a :class:`DockerStream`'s: bounded by
    :attr:`KILL_CONFIRM_S`, the answer on the result's ``kill_confirmed``. A kill that
    goes unconfirmed is appended to :attr:`unconfirmed_kills` and handed to
    ``on_kill_unconfirmed`` — the same report a sealed session makes for its streams —
    so no path ends as a silent terminal ``cancelled`` with a running container.
    """

    name = "docker"

    #: The confirmation bound and step (module defaults; class attributes so a test can
    #: shorten them).
    KILL_CONFIRM_S: float = KILL_CONFIRM_S
    KILL_CONFIRM_STEP_S: float = KILL_CONFIRM_STEP_S

    def __init__(
        self,
        settings: DockerSettings,
        *,
        runner: Runner | None = None,
        verify_daemon: bool = True,
        cancel: CancelFn | None = None,
        on_kill_unconfirmed: KillUnconfirmedFn | None = None,
    ) -> None:
        self.settings = settings
        self._runner: Runner = runner or subprocess.run
        self._cancel = cancel
        self._on_kill_unconfirmed = on_kill_unconfirmed
        #: Every container this executor's :meth:`run` killed WITHOUT confirmation, in
        #: order — what a session reads after an attempt (``unconfirmed_kills``).
        self.unconfirmed_kills: list[UnconfirmedKill] = []
        resolved = settings.docker_binary or shutil.which("docker")
        if not resolved:
            raise SandboxUnavailable(
                "docker sandbox requested but the 'docker' binary was not found on PATH; "
                "refusing to run untrusted repository tests in-process"
            )
        self.docker = resolved
        if verify_daemon:
            self._verify_daemon()

    def _verify_daemon(self) -> None:
        """One ``docker info`` at construction: a dead daemon is found before the first
        task, not by the first task."""
        try:
            r = self._runner(
                [self.docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            raise SandboxUnavailable(f"docker daemon probe failed: {e}") from e
        if r.returncode != 0:
            raise SandboxUnavailable(
                f"docker daemon not reachable: {(r.stderr or r.stdout).strip()[:400]}"
            )

    def tool(self, name: str, host_override: str | None = None) -> str:
        # Inside the image the toolchain is on PATH; host overrides never apply.
        return name

    @property
    def cancel_fn(self) -> CancelFn | None:
        """The run's cancel token, so a builder's containers can follow it."""
        return self._cancel

    def describe(self) -> dict[str, Any]:
        """The apparatus-stamp view of the sandbox (image and limits; no host paths)."""
        s = self.settings
        return {
            "executor": self.name,
            "image": s.image,
            "user": s.user,
            "memory": s.memory,
            "cpus": s.cpus,
            "pids_limit": s.pids_limit,
            "network": "none",
        }

    def build_argv(self, cmd: Command) -> list[str]:
        """The hardened ``docker run`` argv. Tests assert on this directly."""
        s = self.settings
        argv: list[str] = [
            self.docker,
            "run",
            "--rm",
            "--network=bridge" if cmd.network else "--network=none",
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
        ]
        # the worktree is read-only inside: the builder edits it BEFORE grading, the
        # tests only read it; a test that writes into the tree fails, never mutates it
        argv += ["--mount", f"type=bind,src={cmd.root},dst={s.workdir},readonly"]
        # Writable paths are bind-mounted rw from the (disposable) worktree so the
        # runner can parse reports the toolchain writes there (surefire XML, …). The
        # container runs as `user` (nobody by default), which owns nothing on the host,
        # so the directory must be group/other-writable for it — but never world-listable
        # or executable beyond that: 0o733 lets the container's uid create files inside
        # without handing every host user a readable tree (CodeRabbit on PR #3, CWE-276;
        # the worktree itself is disposable and lives under the worker's scratch).
        for rel in cmd.writable_paths:
            host_dir = cmd.root / rel
            host_dir.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                host_dir.chmod(0o733)
            inside = f"{s.workdir}/{rel}".rstrip("/")
            argv += ["--mount", f"type=bind,src={host_dir},dst={inside}"]
        for host, inside in s.extra_ro_mounts.items():
            argv += ["--mount", f"type=bind,src={host},dst={inside},readonly"]
        for k, v in cmd.env.items():
            argv += ["--env", f"{k}={v}"]
        argv += ["--env", "HOME=/tmp", "--env", "CI=1", "--env", "NO_COLOR=1"]
        cwd_inside = s.workdir if cmd.cwd_rel in {".", ""} else f"{s.workdir}/{cmd.cwd_rel}"
        argv += ["--workdir", cwd_inside, f"--stop-timeout={max(1, int(cmd.timeout))}", s.image]
        argv += list(cmd.argv)
        return argv

    def _run_cancellable(self, argv: list[str], cmd: Command, started: float) -> ExecResult:
        """``docker run`` under the cancel token. The container gets a name so the
        deadline and the token can ``docker kill`` IT — killing the client process
        alone would leave the container running (the same rule as :class:`DockerStream`).
        After the kill: the client's process group (a hung daemon must not orphan the
        ``docker run`` client), then the bounded confirmation attempt
        (:func:`wait_container_stopped`, :attr:`KILL_CONFIRM_S`); an unconfirmed kill is
        reported through :meth:`_report_unconfirmed` before the result is returned."""
        name = f"crb-{uuid.uuid4().hex[:12]}"
        argv = [*argv[:3], "--name", name, *argv[3:]]  # docker run --rm --name …
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        box: dict[str, str] = {}

        def _drain() -> None:
            o, e = proc.communicate()
            box["out"], box["err"] = o or "", e or ""

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
        timed_out = cancelled = False
        kill_confirmed: bool | None = None
        deadline = started + cmd.timeout
        while t.is_alive():
            t.join(_CANCEL_POLL_S)
            if not t.is_alive():
                break
            if self._cancel is not None and self._cancel():
                cancelled = True
            elif time.monotonic() >= deadline:
                timed_out = True
            else:
                continue
            kill_confirmed = self._kill(name, proc)
            t.join()
            break
        if proc.returncode == 125 and not (cancelled or timed_out):
            raise SandboxUnavailable(
                f"docker failed to launch the container (exit 125): {box.get('err', '')[:400]}"
            )
        rc = 130 if cancelled else 124 if timed_out else int(proc.returncode or 0)
        return ExecResult(
            rc,
            box.get("out", ""),
            box.get("err", ""),
            timed_out,
            time.monotonic() - started,
            cancelled,
            kill_confirmed=kill_confirmed,
            container=name,
        )

    def _kill(self, name: str, proc: subprocess.Popen[str]) -> bool:
        """``docker kill <name>`` (bounded by :data:`DOCKER_KILL_TIMEOUT_S`), then the
        client's process group, then the bounded confirmation attempt. Returns whether
        the daemon confirmed the container stopped; an unconfirmed kill has already been
        recorded and reported when this returns ``False``."""
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                [self.docker, "kill", name],
                capture_output=True,
                check=False,
                timeout=DOCKER_KILL_TIMEOUT_S,
            )
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(OSError):
                proc.kill()
        confirmed = wait_container_stopped(
            self.docker, name, timeout_s=self.KILL_CONFIRM_S, step_s=self.KILL_CONFIRM_STEP_S
        )
        if not confirmed:
            self._report_unconfirmed(
                UnconfirmedKill(container=name, bound_s=float(self.KILL_CONFIRM_S))
            )
        return confirmed

    def _report_unconfirmed(self, kill: UnconfirmedKill) -> None:
        """Record ``kill`` on :attr:`unconfirmed_kills` and hand it to
        ``on_kill_unconfirmed``; a callback that raises is logged, never re-raised into
        the command's result."""
        self.unconfirmed_kills.append(kill)
        if self._on_kill_unconfirmed is None:
            return
        try:
            self._on_kill_unconfirmed(kill)
        except Exception:
            _LOG.exception("on_kill_unconfirmed failed for container %s", kill.container)

    def require_image(self, image: str) -> None:
        """Fail closed unless ``image`` is present in the daemon's image store.

        The worker never pulls: an absent image is a deployment fault, so it is a
        :class:`SandboxUnavailable` (the run stops) rather than an exit-125 surprise
        half-way through a build attempt.
        """
        if not image:
            raise SandboxUnavailable("docker image name is empty")
        try:
            r = self._runner(
                [self.docker, "image", "inspect", "--format", "{{.Id}}", image],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            raise SandboxUnavailable(f"docker image probe failed for {image!r}: {e}") from e
        if r.returncode != 0:
            raise SandboxUnavailable(
                f"docker image {image!r} is not present in the daemon's store (the worker never "
                f"pulls): {(r.stderr or r.stdout).strip()[:300]}"
            )

    def stream(
        self,
        run_args: Sequence[str],
        *,
        argv: Sequence[str],
        client_env: Mapping[str, str],
        timeout_s: int,
        name: str = "",
    ) -> DockerStream:
        """Start a long-lived ``docker run`` and stream its stdout line by line.

        ``run_args`` are the ``docker run`` options (after ``--rm``; the caller owns
        the hardening set), ``argv`` the command inside the container. ``client_env``
        is the environment of the *docker client* process — ``--env NAME`` (no value)
        options in ``run_args`` are resolved from it, which is how a secret reaches
        the container without ever appearing on a command line. Deadline and the
        executor's cancel token both end in ``docker kill <name>`` (killing the client
        alone would leave the container running). A launch failure (exit 125 before
        any output) is a :class:`SandboxUnavailable` — fail closed.
        """
        cname = name or f"crb-{uuid.uuid4().hex[:12]}"
        full = [self.docker, "run", "--rm", "--name", cname, *run_args, *argv]
        return DockerStream(
            full,
            docker=self.docker,
            name=cname,
            env=client_env,
            timeout_s=timeout_s,
            cancel=self._cancel,
        )

    def run(self, cmd: Command) -> ExecResult:
        """Run ``cmd`` in the sandbox. A timeout is a result (124); a failure of docker
        itself to launch (exit 125, a missing binary) is :class:`SandboxUnavailable`."""
        argv = self.build_argv(cmd)
        started = time.monotonic()
        # The real daemon always takes the polled path — with or without a cancel token —
        # because it is the one that kills the CONTAINER on the wall clock and confirms
        # it: subprocess.run's own timeout kills only the ``docker run`` client and would
        # leave the container running (the CLI's executors carry no cancel token). An
        # injected runner (tests) cannot be polled, so it keeps the plain timeout path.
        if self._runner is subprocess.run:
            return self._run_cancellable(argv, cmd, started)
        try:
            r = self._runner(argv, capture_output=True, text=True, timeout=cmd.timeout, check=False)
        except subprocess.TimeoutExpired:
            return ExecResult(
                124, "", "TIMEOUT — container exceeded wall clock", True, time.monotonic() - started
            )
        except FileNotFoundError as e:
            raise SandboxUnavailable(f"docker binary unusable at run time: {e}") from e
        if r.returncode == 125:
            # docker-level launch failure is a sandbox/config error, never a RED result
            raise SandboxUnavailable(
                f"docker failed to launch the container (exit 125): {(r.stderr or r.stdout).strip()[:400]}"
            )
        return ExecResult(
            r.returncode, r.stdout or "", r.stderr or "", False, time.monotonic() - started
        )


#: The most one ``docker inspect`` may take; :func:`wait_container_stopped` caps each
#: call further to the time left in its own budget.
INSPECT_TIMEOUT_S: float = 10.0


def container_stopped(
    docker: str, name: str, *, timeout_s: float = INSPECT_TIMEOUT_S
) -> bool | None:
    """One ``docker inspect -f {{.State.Running}}`` question, answered STRICTLY.

    ``True`` when the daemon says exactly ``false`` (not running) or the container is
    gone ("no such container" — ``--rm`` reaps asynchronously); ``False`` when it says
    exactly ``true``; ``None`` when the daemon could not be asked within ``timeout_s``,
    failed for another reason, or — exit 0 with anything but those two strings (empty,
    ``<no value>``, a case variant, trailing text) — said something this function does
    not understand. An unparseable answer is never a stop: the caller keeps asking to
    its bound.
    """
    try:
        r = subprocess.run(
            [docker, "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            check=False,
            timeout=max(timeout_s, 0.001),
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 0:
        answer = (r.stdout or "").strip()
        if answer == "false":
            return True
        if answer == "true":
            return False
        return None
    if "no such" in (r.stderr or "").lower():
        return True
    return None


def wait_container_stopped(
    docker: str,
    name: str,
    *,
    timeout_s: float = KILL_CONFIRM_S,
    step_s: float = KILL_CONFIRM_STEP_S,
) -> bool:
    """Poll :func:`container_stopped` until the daemon reports the container not
    running, bounded by ``timeout_s`` IN TOTAL: every inspect call is given only the
    time remaining, so a slow daemon can never stretch the wait past the bound.
    ``docker kill`` returns when the signal is delivered, not when ``docker ps`` stops
    listing the container — a reader that needs "cancelled means not running" waits
    here. ``True`` = confirmed; ``False`` = the bound was hit (logged as a warning —
    the container may still be running and the caller must say so)."""
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if container_stopped(docker, name, timeout_s=min(INSPECT_TIMEOUT_S, remaining)) is True:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(step_s, remaining))
    _LOG.warning(
        "container %s not confirmed stopped within %.1fs after docker kill", name, timeout_s
    )
    return False


class DockerStream:
    """A running ``docker run`` whose stdout is consumed line by line.

    Invariants:

    * **The container dies with the deadline or the cancel token** — via ``docker kill
      <name>``, then the client process group. A `docker run` client killed on its own
      leaves the container running; that is the failure this class exists to prevent.
    * **An enforced kill is confirmation-attempted, bounded, before the stream ends**:
      ``docker kill`` returns when the signal is sent, not when the daemon stops listing
      the container, so :meth:`kill` polls ``docker inspect -f {{.State.Running}}`` for
      at most :attr:`KILL_CONFIRM_S` in total (each call capped to the time left) and
      :meth:`lines` waits for that attempt to end. The attempt can end WITHOUT
      confirming: after a cancel or the wall clock a caller MUST read
      :attr:`kill_confirmed` — ``True`` means the daemon reported the container not
      running; ``False`` means the bound was hit, a warning named the container, and it
      may still be running (the worker records and reaps it).
    * **stderr never deadlocks stdout**: it goes to a temporary file, of which the last
      4000 characters are kept as :attr:`stderr_tail` (the caller redacts).
    * **Exit 125 with no output is a launch failure** (bad option, missing image,
      unusable network) and raises :class:`SandboxUnavailable` when the lines are
      consumed — never a silent empty stream.
    * ``timed_out`` / ``cancelled`` are set before the kill, so a reader that sees the
      stream end can tell an honest exit from an enforced one.
    """

    #: The TOTAL bound on :meth:`kill`'s confirmation attempt (every inspect call gets
    #: only the time left), and how often it asks. Class attributes so a test can
    #: shorten the bound (module defaults :data:`KILL_CONFIRM_S` / :data:`KILL_CONFIRM_STEP_S`).
    KILL_CONFIRM_S: float = KILL_CONFIRM_S
    KILL_CONFIRM_STEP_S: float = KILL_CONFIRM_STEP_S

    def __init__(
        self,
        full_argv: Sequence[str],
        *,
        docker: str,
        name: str,
        env: Mapping[str, str],
        timeout_s: int,
        cancel: CancelFn | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.name = name
        self._docker = docker
        self._cancel = cancel
        self._timed_out = False
        self._cancelled = False
        self._kill_confirmed: bool | None = None
        self._kill_lock = threading.Lock()
        self._stderr = ""
        self._stderr_file = tempfile.TemporaryFile(  # noqa: SIM115 — closed in lines()
            mode="w+", encoding="utf-8", errors="replace"
        )
        self._proc = subprocess.Popen(
            list(full_argv),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=self._stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        self._watchdog = threading.Timer(timeout_s, self._on_deadline)
        self._watchdog.daemon = True
        self._watchdog.start()
        self._stop_poll = threading.Event()
        self._poller: threading.Thread | None = None
        if cancel is not None:
            self._poller = threading.Thread(target=self._poll_cancel, daemon=True)
            self._poller.start()

    # --- lifecycle ---------------------------------------------------------------
    def lines(self) -> Iterator[str]:
        """Yield stdout line by line until the container exits or is killed; then reap
        the client, keep the stderr tail, and raise for a launch failure. Consume it
        fully (or stop early — the ``finally`` still cleans up)."""
        assert self._proc.stdout is not None
        saw_output = False
        try:
            for line in self._proc.stdout:
                saw_output = True
                yield line.rstrip("\n")
        finally:
            self._watchdog.cancel()
            self._stop_poll.set()
            try:  # reap the client whether it exited, was killed, or the reader stopped early
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.kill()
                self._proc.wait()
            if self._enforced:  # the promise: after an enforced kill, the container is down
                self._confirm_stopped()
            try:
                self._stderr_file.seek(0)
                self._stderr = self._stderr_file.read()[-4000:]
            except (OSError, ValueError):
                self._stderr = ""
            finally:
                self._stderr_file.close()
        if self._proc.returncode == 125 and not saw_output and not self._enforced:
            raise SandboxUnavailable(
                f"docker failed to launch the container (exit 125): {self._stderr[-400:]}"
            )

    @property
    def _enforced(self) -> bool:
        """Did WE end it (deadline or cancel)? A 125 after an enforced kill is not a
        launch failure."""
        return self._timed_out or self._cancelled

    def _poll_cancel(self) -> None:
        while not self._stop_poll.wait(_CANCEL_POLL_S):
            if self._cancel is not None and self._cancel():
                self._cancelled = True
                self.kill()
                return

    def _on_deadline(self) -> None:
        self._timed_out = True
        self.kill()

    def kill(self) -> None:
        """``docker kill <name>`` first (the container is the process that matters),
        then the client's process group, then wait — bounded by :attr:`KILL_CONFIRM_S`
        — for the daemon to report the container not running, recording the answer in
        :attr:`kill_confirmed` (``False`` when the bound was hit: not confirmed).
        Idempotent; never raises. Serialised with :meth:`lines`'s reap, so the stream
        does not end before the attempt does."""
        with self._kill_lock:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    [self._docker, "kill", self.name],
                    capture_output=True,
                    check=False,
                    timeout=DOCKER_KILL_TIMEOUT_S,
                )
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                with contextlib.suppress(OSError):
                    self._proc.kill()
            self._kill_confirmed = self._wait_stopped()

    def _confirm_stopped(self) -> None:
        """Block until any in-flight :meth:`kill` has finished its confirmation (it
        holds ``_kill_lock`` for its whole body), and confirm ourselves if none was
        recorded — the deadline or cancel flag was set but the reader reached EOF
        before :meth:`kill` ran, e.g. the container exited on its own at that moment."""
        with self._kill_lock:
            if self._kill_confirmed is None:
                self._kill_confirmed = self._wait_stopped()

    def _wait_stopped(self) -> bool:
        return wait_container_stopped(
            self._docker,
            self.name,
            timeout_s=self.KILL_CONFIRM_S,
            step_s=self.KILL_CONFIRM_STEP_S,
        )

    # --- state ---------------------------------------------------------------------
    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def kill_confirmed(self) -> bool | None:
        """``None`` — no kill was issued; ``True`` — after the kill the daemon reported
        the container not running (or gone); ``False`` — the confirmation bound
        (:attr:`KILL_CONFIRM_S`) was hit, a warning named the container, and it MAY
        STILL BE RUNNING: the reader must say so (the worker records the event and
        queues the reaper) rather than report a clean stop."""
        return self._kill_confirmed

    @property
    def stderr_tail(self) -> str:
        return self._stderr


def make_executor(
    kind: str,
    *,
    docker: DockerSettings | None = None,
    cancel: CancelFn | None = None,
    on_kill_unconfirmed: KillUnconfirmedFn | None = None,
) -> Executor:
    """``kind`` ∈ {"local", "docker"}. Docker without settings fails closed.
    ``on_kill_unconfirmed`` reaches the docker executor only (a local kill needs no
    daemon to confirm it)."""
    k = (kind or "local").strip().lower()
    if k in {"", "local", "none", "host"}:
        return LocalExecutor(cancel=cancel)
    if k == "docker":
        if docker is None:
            raise SandboxUnavailable("executor 'docker' requires DockerSettings (image)")
        return DockerExecutor(docker, cancel=cancel, on_kill_unconfirmed=on_kill_unconfirmed)
    raise ValueError(f"unknown executor kind {kind!r}")


def sequence_env(*layers: Mapping[str, str] | None) -> dict[str, str]:
    """Merge env layers left→right, skipping None."""
    out: dict[str, str] = {}
    for layer in layers:
        if layer:
            out.update(layer)
    return out


__all__: Sequence[str] = (
    "DOCKER_KILL_TIMEOUT_S",
    "KILL_CONFIRM_S",
    "KILL_CONFIRM_STEP_S",
    "Command",
    "DockerExecutor",
    "DockerSettings",
    "DockerStream",
    "ExecResult",
    "Executor",
    "KillUnconfirmedFn",
    "LocalExecutor",
    "SandboxUnavailable",
    "UnconfirmedKill",
    "container_stopped",
    "make_executor",
    "sequence_env",
    "wait_container_stopped",
)
