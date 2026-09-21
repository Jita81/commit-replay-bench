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
              A ``DockerStream`` kill is CONFIRMED: after ``docker kill`` it polls ``docker
              inspect -f {{.State.Running}}`` (≤ 10 s, 100 ms steps; "no such container"
              is gone) and ``lines()`` does not return until that poll ends, so a reader
              that sees the stream end after cancel or the wall clock can rely on the
              container not running (``kill_confirmed``; a warning when the bound is hit).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/core/runners/base.py (builds the Command, parses the result),
              src/crb/builders/container.py (the sealed builder over ``DockerStream``),
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

    @property
    def ok(self) -> bool:
        """Exit 0 AND neither enforced stop — a killed command is never ok."""
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    @property
    def combined(self) -> str:
        """stdout then stderr, for parsers and the redacted tail in evidence."""
        return self.stdout + ("\n" + self.stderr if self.stderr else "")


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
    """Run inside a hardened container. See module docstring for the invariant set."""

    name = "docker"

    def __init__(
        self,
        settings: DockerSettings,
        *,
        runner: Runner | None = None,
        verify_daemon: bool = True,
        cancel: CancelFn | None = None,
    ) -> None:
        self.settings = settings
        self._runner: Runner = runner or subprocess.run
        self._cancel = cancel
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
        alone would leave the container running (the same rule as :class:`DockerStream`)."""
        name = f"crb-{uuid.uuid4().hex[:12]}"
        argv = [*argv[:3], "--name", name, *argv[3:]]  # docker run --rm --name …
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        box: dict[str, str] = {}

        def _drain() -> None:
            o, e = proc.communicate()
            box["out"], box["err"] = o or "", e or ""

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
        timed_out = cancelled = False
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
            subprocess.run(
                [self.docker, "kill", name], capture_output=True, check=False, timeout=30
            )
            t.join(30)
            break
        if proc.returncode == 125 and not cancelled:
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
        )

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
        # the cancellable path drives Popen itself; an injected runner (tests) cannot
        # be polled, so it takes the plain timeout path
        if self._cancel is not None and self._runner is subprocess.run:
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


def _container_stopped(docker: str, name: str) -> bool | None:
    """One ``docker inspect`` question: ``True`` when the container is not running
    (stopped, or already removed — ``--rm`` reaps asynchronously), ``False`` while
    it still runs, ``None`` when the daemon could not be asked."""
    try:
        r = subprocess.run(
            [docker, "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            check=False,
            timeout=10,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 0:
        return (r.stdout or "").strip().lower() != "true"
    if "no such" in (r.stderr or "").lower():
        return True
    return None


def wait_container_stopped(
    docker: str, name: str, *, timeout_s: float = 10.0, step_s: float = 0.1
) -> bool:
    """Poll :func:`_container_stopped` until the daemon reports the container not
    running, bounded by ``timeout_s``. ``docker kill`` returns when the signal is
    delivered, not when ``docker ps`` stops listing the container — a reader that
    needs "cancelled means not running" waits here. ``True`` = confirmed; ``False``
    = the bound was hit (logged as a warning — the container may still be running)."""
    deadline = time.monotonic() + timeout_s
    while True:
        if _container_stopped(docker, name) is True:
            return True
        if time.monotonic() >= deadline:
            _LOG.warning(
                "container %s not confirmed stopped within %.1fs after docker kill", name, timeout_s
            )
            return False
        time.sleep(step_s)


class DockerStream:
    """A running ``docker run`` whose stdout is consumed line by line.

    Invariants:

    * **The container dies with the deadline or the cancel token** — via ``docker kill
      <name>``, then the client process group. A `docker run` client killed on its own
      leaves the container running; that is the failure this class exists to prevent.
    * **An enforced kill is confirmed before the stream ends**: ``docker kill`` returns
      when the signal is sent, not when the daemon stops listing the container, so
      :meth:`kill` polls ``docker inspect -f {{.State.Running}}`` (bounded — see
      :attr:`KILL_CONFIRM_S`) and :meth:`lines` waits for that poll. When it returns
      after a cancel or the wall clock, the container is not running, or
      :attr:`kill_confirmed` is ``False`` and a warning was logged.
    * **stderr never deadlocks stdout**: it goes to a temporary file, of which the last
      4000 characters are kept as :attr:`stderr_tail` (the caller redacts).
    * **Exit 125 with no output is a launch failure** (bad option, missing image,
      unusable network) and raises :class:`SandboxUnavailable` when the lines are
      consumed — never a silent empty stream.
    * ``timed_out`` / ``cancelled`` are set before the kill, so a reader that sees the
      stream end can tell an honest exit from an enforced one.
    """

    #: How long :meth:`kill` waits for the daemon to report the container stopped,
    #: and how often it asks. Class attributes so a test can shorten the bound.
    KILL_CONFIRM_S: float = 10.0
    KILL_CONFIRM_STEP_S: float = 0.1

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
        then the client's process group, then wait — bounded — until the daemon
        reports the container not running (:attr:`kill_confirmed`). Idempotent;
        never raises. Serialised with :meth:`lines`'s reap, so the stream does not
        end before the confirmation does."""
        with self._kill_lock:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    [self._docker, "kill", self.name], capture_output=True, check=False, timeout=30
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
        (:attr:`KILL_CONFIRM_S`) was hit and a warning was logged."""
        return self._kill_confirmed

    @property
    def stderr_tail(self) -> str:
        return self._stderr


def make_executor(
    kind: str, *, docker: DockerSettings | None = None, cancel: CancelFn | None = None
) -> Executor:
    """``kind`` ∈ {"local", "docker"}. Docker without settings fails closed."""
    k = (kind or "local").strip().lower()
    if k in {"", "local", "none", "host"}:
        return LocalExecutor(cancel=cancel)
    if k == "docker":
        if docker is None:
            raise SandboxUnavailable("executor 'docker' requires DockerSettings (image)")
        return DockerExecutor(docker, cancel=cancel)
    raise ValueError(f"unknown executor kind {kind!r}")


def sequence_env(*layers: Mapping[str, str] | None) -> dict[str, str]:
    """Merge env layers left→right, skipping None."""
    out: dict[str, str] = {}
    for layer in layers:
        if layer:
            out.update(layer)
    return out


__all__: Sequence[str] = (
    "Command",
    "DockerExecutor",
    "DockerSettings",
    "DockerStream",
    "ExecResult",
    "Executor",
    "LocalExecutor",
    "SandboxUnavailable",
    "make_executor",
    "sequence_env",
)
