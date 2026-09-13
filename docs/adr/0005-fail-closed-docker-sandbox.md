# ADR-0005 — Fail-closed Docker sandbox for every test run

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** the executor description is part of the `ApparatusStamp` (`executor` field)

## Context

Grading means running a third party's test suite, with a machine-generated patch applied,
on infrastructure inside an NHS tenant. Repository tests are untrusted code: they can read
the environment, open sockets, fork, fill disks, or (with a malicious patch) attempt to
tamper with the grader. The validation standard's G5.3 requires containment for network,
filesystem/process escape, resource exhaustion, cross-task access and credential theft, and
names any sandbox escape a launch blocker. Upstream `sandbox_harness.py` had the hardening
set but was pytest-specific and could be bypassed by configuration.

## Decision

1. Every runner builds a `Command` (argv, root, cwd, env, timeout, `writable_paths`,
   `network`) and hands it to an `Executor`; the runner never calls `subprocess` itself.
2. `crb.core.execution.DockerExecutor.build_argv` produces the hardened `docker run` argv,
   which tests assert on directly:

   ```
   docker run --rm
     --network=none                      (--network=bridge only when Command.network=True — the dep-install phase)
     --memory=<2g> --cpus=<2> --pids-limit=<512>
     --user=65534:65534
     --cap-drop=ALL --security-opt no-new-privileges
     --read-only
     --tmpfs /tmp:rw,nosuid,nodev,size=<512m>
     --mount type=bind,src=<worktree>,dst=/work,readonly
     [--mount type=bind,src=<worktree>/<writable_path>,dst=/work/<writable_path>]   per declared writable path
     [--mount type=bind,src=<host>,dst=<inside>,readonly]                            per extra_ro_mount
     --env K=V …  --env HOME=/tmp --env CI=1 --env NO_COLOR=1
     --workdir /work[/<cwd_rel>] --stop-timeout=<timeout> <image> <argv…>
   ```
3. **Fail closed.** `SandboxUnavailable` is raised — and the run **stops** — when:
   - no `docker` binary is on PATH (`DockerExecutor.__init__`);
   - the daemon probe (`docker info`) fails or is unreachable;
   - `DockerSettings.image` is empty;
   - `DockerSettings.user` resolves to root (`""`, `"0"`, `"root"`);
   - an `extra_ro_mounts` host path ends with `docker.sock` or is `/` or `$HOME`;
   - `docker run` exits 125 (launch failure) or the binary vanishes at run time.
   `grade()` deliberately re-raises `SandboxUnavailable` while turning every other
   exception into a recorded non-pass: an infrastructure fault must never become a verdict
   in either direction.
4. **Timeouts are failures**: a container that exceeds the wall clock returns
   `ExecResult(returncode=124, timed_out=True)`; `TestRun.green` is then `False`.
5. `make_executor("docker")` without `DockerSettings` raises `SandboxUnavailable`; there is
   no "docker if available, else local" mode.
6. `LocalExecutor` exists for development and for trusted fixture repositories only. It
   still strips the operator's environment to `_HOST_ENV_PASSTHROUGH` (PATH, HOME, locale,
   toolchain cache variables) and kills the whole process group on timeout. The operator
   guide and the apparatus stamp make the executor visible on every verdict.
7. `Executor.describe()` (no secrets) is embedded in the `ApparatusStamp`, so an auditor
   can see which isolation a verdict was produced under.

## Consequences

- A deployment without a working Docker daemon cannot grade; the failure mode is a
  stopped run with `SandboxUnavailable` in the run status, not a degraded result.
- Toolchains must be **inside the image** (`DockerExecutor.tool()` ignores host overrides);
  operators supply a per-repository `sandbox_image` and `crb repo probe` proves it.
- Writable paths must be declared by the runner (build caches, `target/`, surefire
  reports); anything undeclared is read-only, which surfaces as a test failure attributed
  to the trial, not the instrument. Runners are expected to declare what their toolchain
  needs.
- The container runs as `nobody`; declared writable directories are `chmod 777` on the
  disposable worktree so that works. Worktrees are never reused across trials.
- Dependency installation with network is a separate phase (`Command.network=True`) that
  still runs with every other cap; P1/P2 add a pinned index date to it.

## Alternatives considered

- **Run tests in-process / on the host by default.** Rejected: untrusted code with the
  operator's environment, and no containment claim can be made.
- **Fall back to local execution when Docker is missing.** Rejected: a silent downgrade of
  the apparatus; the stamp would say "docker" while the run said "local".
- **gVisor / Firecracker / Kata.** Deferred: stronger isolation, but not uniformly
  available on customer platforms. The `Executor` protocol allows adding one without
  touching runners or the grader.
- **Allow the docker socket as a mount for DinD builds.** Rejected explicitly in
  `DockerSettings.__post_init__`.
