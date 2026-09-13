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
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

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


class SandboxUnavailable(RuntimeError):
    """Docker isolation was requested but cannot be provided safely. FAIL CLOSED."""


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def combined(self) -> str:
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
    name: str

    def run(self, cmd: Command) -> ExecResult: ...

    def tool(self, name: str, host_override: str | None = None) -> str:
        """Resolve a toolchain binary name for this execution environment."""
        ...

    def describe(self) -> dict[str, Any]:
        """Apparatus-stamp description (no secrets)."""
        ...


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------


class LocalExecutor:
    """Run on the host. Minimal explicit environment; process-group kill on timeout."""

    name = "local"

    def __init__(self, *, base_env: Mapping[str, str] | None = None) -> None:
        self._base_env = dict(base_env) if base_env is not None else self._host_base_env()

    @staticmethod
    def _host_base_env() -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in _HOST_ENV_PASSTHROUGH}
        env.setdefault("LANG", "C.UTF-8")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["CI"] = "1"
        env["NO_COLOR"] = "1"
        return env

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or shutil.which(name) or name

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    def run(self, cmd: Command) -> ExecResult:
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
        try:
            out, err = proc.communicate(timeout=cmd.timeout)
            rc = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
            out, err = proc.communicate()
            rc, timed_out = 124, True
        return ExecResult(rc, out or "", err or "", timed_out, time.monotonic() - started)

    @staticmethod
    def _kill_group(proc: subprocess.Popen[str]) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


# ---------------------------------------------------------------------------
# Docker (hardened, fail-closed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DockerSettings:
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
    ) -> None:
        self.settings = settings
        self._runner: Runner = runner or subprocess.run
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

    def describe(self) -> dict[str, Any]:
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
        argv += ["--mount", f"type=bind,src={cmd.root},dst={s.workdir},readonly"]
        # Writable paths are bind-mounted rw from the (disposable) worktree so the
        # runner can parse reports the toolchain writes there (surefire XML, …).
        # They are created world-writable because the container runs as `user`.
        for rel in cmd.writable_paths:
            host_dir = cmd.root / rel
            host_dir.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                host_dir.chmod(0o777)
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

    def run(self, cmd: Command) -> ExecResult:
        argv = self.build_argv(cmd)
        started = time.monotonic()
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


def make_executor(kind: str, *, docker: DockerSettings | None = None) -> Executor:
    """``kind`` ∈ {"local", "docker"}. Docker without settings fails closed."""
    k = (kind or "local").strip().lower()
    if k in {"", "local", "none", "host"}:
        return LocalExecutor()
    if k == "docker":
        if docker is None:
            raise SandboxUnavailable("executor 'docker' requires DockerSettings (image)")
        return DockerExecutor(docker)
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
    "ExecResult",
    "Executor",
    "LocalExecutor",
    "SandboxUnavailable",
    "make_executor",
    "sequence_env",
)
