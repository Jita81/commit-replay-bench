# ADR-0005 — Fail-closed Docker sandbox for every test run

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** the executor description is part of the `ApparatusStamp` (`executor` field)

## Context

Grading means running a third party's test suite, with a machine-generated patch applied,
on infrastructure inside an NHS tenant. Repository tests are untrusted code: they can read
the environment, open sockets, fork, fill disks, or (with a malicious patch) attempt to
tamper with the grader `[threat model — a design premise, not a measurement]`. The
validation standard's G5.3 requires containment for network, filesystem/process escape,
resource exhaustion, cross-task access and credential theft, and names any sandbox escape a
launch blocker `[compliance requirement — what the decision below must meet; the controls
that meet it are tagged in docs/SECURITY.md §3.1]`. Upstream `sandbox_harness.py` had the
hardening set but was pytest-specific and could be bypassed by configuration `[observed by
inspection of AthenaClaude `origin/main`, 2026-09-13]`.

## Decision

1. Every runner builds a `Command` (argv, root, cwd, env, timeout, `writable_paths`,
   `network`) and hands it to an `Executor`; the runner never calls `subprocess` itself.
2. `crb.core.execution.DockerExecutor.build_argv` produces the hardened `docker run` argv,
   which tests assert on directly:

   ```
   docker run --rm
     --pull=never                        (an image absent from the daemon's store is exit 125 → SandboxUnavailable; never a registry pull)
     --network=none                      (--network=bridge only when Command.network=True — the dep-install phase)
     --memory=<2g> --cpus=<2> --pids-limit=<512>
     --user=65534:65534
     --cap-drop=ALL --security-opt no-new-privileges
     --read-only
     --tmpfs /tmp:rw,noexec,nosuid,nodev,size=<512m>   (rw,exec,nosuid,nodev,… only when Command.exec_tmp — see amendment 2026-09-21)
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

## Amendment 2026-09-21 — the tmpfs is `exec` for a toolchain that declares it; never a pull

Docker mounts a `--tmpfs` with `noexec` unless `exec` is named, so `/tmp` — the only
scratch every sandbox has — could not run a binary. `go test` compiles each package's test
binary into its temp directory and execs it: under the sandbox that is `/tmp`, and the Go
runner had never been run against a daemon (`fork/exec /tmp/go-build…/calc.test: permission
denied`, found by the first reference-image smoke, `tests/test_sandbox_images_docker.py`).

Decision: `Command.exec_tmp` (default `False`) — a runner declares that its toolchain runs
what it builds under `/tmp`; the executor then mounts `/tmp:rw,exec,nosuid,nodev,size=…`.
The Go runner declares it, in its own `command()`; the declaration is **per toolchain, never
per repository** — no `RepoConfig` key, `runner_opts` entry or run request reaches it, so a
hostile repository cannot ask for an exec-mountable scratch. Every other command mounts
`/tmp:rw,noexec,nosuid,nodev,size=…`
— `noexec` now stated on the argv rather than inherited from the runtime's default, so the
control does not depend on which daemon is behind the socket. `nosuid` and `nodev` hold in
both shapes, as do every other flag; a test process is arbitrary code under every one of
these executors already, so `noexec` on scratch is defence-in-depth against nothing the
image's own interpreter could not do — but it stays wherever it costs nothing. The
documented control (SECURITY.md §3.1) was always `nosuid,nodev`; the argv now says exactly
what it does **[measured — `tests/test_execution.py` asserts both tmpfs shapes token by
token (n = 2 tests); `tests/test_sandbox_images_docker.py` reads `/proc/mounts` inside each
shipped image and tries to run a script written under `/tmp` — `noexec` and `Permission
denied` for an ordinary command on every image, `exec` and the script runs only for the
command the Go runner declares (`test_tmp_is_noexec_unless_the_runner_declares_exec_tmp`,
3/3 images built from this tree, colima / Docker 29.5.2, 2026-09-22, and in CI's
`sandbox-images` job on every pull request — PR #44 run 35678358686 on the merged head
4a64fe3) — and proves `go test` runs and `/usr` stays read-only from inside the shipped Go
image (10 tests × 3 images, same suite); apparatus 2.2]**. The builder container (ADR-0012, `crb.builders.container`) has the same
implicit `noexec` on its tmpfs and will need the same declaration before a Go builder image
can run its own tests inside the cell — a follow-up, not changed here.

Also added: `--pull=never`. The documentation always said the worker never pulls; `docker
run` pulls a missing image by default. An absent image is now a launch failure (exit 125,
`No such image`) → `SandboxUnavailable` **[measured — `test_an_absent_image_fails_closed_without_a_pull`
against a real daemon, same suite]**.

The reference images this argv runs are `deploy/sandbox/Dockerfile.{python,node,go}`
(`deploy/sandbox/README.md`), built and proven from inside by CI on every pull request
**[measured — the `sandbox-images` smoke step (`-m "not network"`, strict warm-up, any skip
fails it): 47 passed / 0 skipped on images built from this tree (30 image tests + the sandbox
and sealed-builder suites on the python image), colima / Docker 29.5.2, 2026-09-22; in CI,
PR #44 run 35678358686 on the merged head 4a64fe3, 44 passed / 0 skipped before this
commit's three added tests; apparatus 2.2]**.

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

## Amendment 2026-09-25 — ADR-0019: a throwaway tree, read-only dependency sets and no network for any command

The first replay in the docker posture (F42 part 2, run `0c44ff24…`, cobra) graded every
attempt `builder_red` because the sealed container held none of the repository's modules,
and a test that writes into its own package directory (`TestDeadcodeElimination`) failed on
the read-only worktree while it passes on the host **[measured — n = 3 or 4 rows, each
`builder_red` with the target red (disputed: 3 observed when the run was cancelled, 4 in
stream D's reading of the deployment's ledger export, which is not committed — [gap] F42);
method: the run's grade rows as read on 2026-09-25, and each defect reproduced by hand
against a fresh clone inside the shipped Go image with `--network none`; apparatus 2.2]**. ADR-0019 decides the fix; this
ADR's argv changes three ways:

1. **Tests run in a throwaway copy of the tree.** The worktree is bind-mounted read-only at
   `/src`; every command runs in a copy of it on a tmpfs at `/work` — capped at
   `DockerSettings.work_size`, owned by the container's uid (mode 0700), `exec,nosuid,nodev`
   (the tree was always executable to its own tests), made by GNU `tar` under `/bin/sh` and
   gone with the container. Declared writable paths are still bound from the worktree and
   excluded from the copy; the builder's own fixer (`writable_paths=(".",)`) keeps the old
   shape. A copy that fails exits 97 with a marker and is `env_error: tree_copy_failed` on
   the result — red, never attributed, never a verdict. `tree: readonly` keeps the old argv
   token for token, as a separate posture. **[measured — `tests/test_execution.py` pins both
   shapes; `tests/test_sandbox_images_docker.py` proves from inside each shipped image that
   `/src` refuses a write, `/work` accepts one and the host tree is byte-identical, and that
   the D5 test reads the same on the host and in the copy; n = 3 images, colima, Docker
   29.5.2, 2026-09-25; apparatus 2.2]**
2. **Dependency sets are mounted read-only.** `Command.ro_mounts` carries sealed sets from
   the bundle store (`crb.provision.store`); the executor re-validates each one — inside a
   registered store, under its `dep_<sha256>` key, nothing writable — before it becomes a
   `--mount …,readonly`, and refuses (`SandboxUnavailable`) otherwise.
3. **No command gets a network.** `Command.network=True` is refused under docker. The
   dependency-install phase this ADR once allowed a network for is gone from the sandbox:
   dependencies are fetched outside it, by a fetch container behind the same allowlisting
   proxy the sealed builder uses (ADR-0012), and sealed (docs/SECURITY.md §3.1.1).

`--network=none` on every test container is unchanged, and is now without exception.
