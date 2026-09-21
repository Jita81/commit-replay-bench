# ADR-0012 — The builder runs in a sealed container: an exported checkout, an allowlisted egress

**Status:** Accepted
**Date:** 2026-09-14
**Apparatus impact:** none (belts, size table, class taxonomy and routing are unchanged; the
builder's execution posture is recorded on the run's event stream — `builder.sealed` — and
in the builder's `describe()` as `container_workdir`). Amends ADR-0005 (which covered test
runs only) and the "Builder runs on the host in v1 of P3" residual risk in ADR-0004 /
`docs/ARCHITECTURE.md` §7.

## Context

Until now a builder attempt ran **on the host**, in a `git worktree` of the main clone, with
the operator's egress. Two facts made that a measurement risk rather than a mere hygiene
issue:

1. **The worktree shares the main clone's object store, which contains the commit under
   test.** Nothing but the `GitArchaeologyGuard` (a shell parser) and the CLI's deny rules
   stood between the builder and `git show <gold>`. The reviews of 2026-09-13/14 recorded
   four guard *false-positive* classes in 24 h on honest shell (quoted parentheses, a
   `.git`-mentioning grep filter, a quote inside `$( … )`, `npx` of a local binary), on top
   of 45 removed by the corpus. Shell parsing is a long tail in both directions: every
   false positive we fix on honest shell is a reminder that a false *negative* on
   dishonest shell — `python -c "subprocess.run(['git','show',…])"` was one — recovers the
   answer. A guard can only be belt-and-braces; it cannot be the wall.
2. **The agentic adapters execute repository build/test commands** with the worker's
   privileges and network. A hostile repository (or a prompt-injected agent) could reach
   anything the worker can.

The validation standard's containment requirement (G5.3) and ADR-0005 already say what a
sandbox must look like; ADR-0005 applied it to test runs and named the builder as P5.

## Decision

Behind `CRB_BUILDER__EXECUTOR=docker` (`crb.builders.container`, wired through
`crb.builders.adapter.build_fn_for(container=…)`; the worker passes
`container_settings_from_env()`):

1. **The clone the builder sees cannot contain the answer — by construction.**
   `SealedCheckout.create(ws)` exports the task's parent tree with `git archive <parent>`
   into a fresh directory, `git init`s it with an inert configuration (no host config, no
   hooks, no signing, no templates) and commits that tree once. `git archive` serialises one
   tree object and nothing else — no history, no refs, no other objects can come along; an
   export shares nothing with the main clone's object store. Paths that `archive` would
   omit (`export-ignore`, on a file or a directory) or rewrite (`export-subst`) are restored
   from the parent's own blobs, so the sealed tree *is* the parent tree, not its release
   tarball. The commit's test files are then overlaid on top exactly as the orchestrator
   overlays them on the real worktree (a dangling, ref-less "oracle" commit of those files
   exists only so the workspace's byte-identity check has a reference); harness fix-ups
   (`node_modules` symlink, `write_if_missing` hooks) are replicated and excluded as they
   are there. The gold commit is unreachable: `git cat-file -e <gold>` fails, and so does
   it for the gold *blob* of the answer file. [measured] `tests/test_builders_container.py`
2. **Grading is unchanged and happens on the host.** After the attempt,
   `SealedCheckout.copy_back(ws)` moves the builder's result into the real worktree:
   modified, added and deleted **regular files only** — a symlink on either side, a
   `.git` component or a path that resolves outside the worktree is refused and reported,
   never followed; byte-identical files are untouched; a tampered test *is* copied so belt
   1 on the host sees it. The four belts (five with ADR-0011) then run exactly as before,
   in the grader's own sandbox (ADR-0005). [measured]
3. **The builder process runs in a hardened container** (`deploy/Dockerfile.builder`: the
   repository's toolchain image + git + the pinned Claude Code CLI as a native binary):
   `--read-only` root, `--cap-drop=ALL`, `no-new-privileges`, `--init`, pid / memory / cpu
   caps, tmpfs `/tmp` as `HOME`, the sealed checkout bind-mounted **rw** at `/work` and
   nothing else writable; `--user` is the **worker's own uid:gid** (root refused) so the
   checkout needs no permission widening and everything the builder writes is the
   worker's to read and delete. The exact argv is `builder_run_args()`, asserted flag by
   flag. [measured]
4. **The only network is one sidecar.** Per attempt the worker creates an `--internal`
   bridge network (no gateway, no route out, no external DNS), starts a sidecar from
   `CRB_BUILDER__PROXY_IMAGE` on the operator's egress network running
   `crb/builders/egress_proxy.py` (standard-library, CONNECT-only, exact-host allowlist —
   `api.anthropic.com` by default, `host[:port]` entries otherwise; plain HTTP through the
   proxy is `405`, an unlisted host or port is `403` and logged as `deny host:port`), joins
   it to the internal network as `proxy`, waits for its `READY` line, and runs the builder
   with `HTTPS_PROXY=http://proxy:3128`. The builder cannot resolve or reach anything but
   the sidecar; the sidecar connects only to the allowlist. An empty allowlist means
   `--network=none` and no sidecar. [measured] `tests/test_builders_container_docker.py`
   (mock endpoint reachable through the proxy, `example.com` refused, direct sockets fail;
   a network-marked test proves TLS end to end to the real endpoint with zero spend)
5. **The credential never touches a command line or a file inside the container.**
   Secret-named variables (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*`)
   are passed as `--env NAME` and resolved from the **docker client's** environment; every
   other variable is `--env NAME=value`. The token source order of ADR-0004 / SECURITY §3.3.1
   (environment → owner-only secrets file) is unchanged. [measured]
6. **Fail closed, every step.** No daemon, a builder or sidecar image missing from the
   daemon's store, a sidecar that does not print `READY` within 30 s, a network that cannot
   be created, a container that cannot launch (exit 125 with no output), a `spawn` for any
   directory other than the sealed checkout — each is `SandboxUnavailable`; the orchestrator
   stops the run (`stopped_reason = sandbox unavailable: …`) and no attempt and no verdict of
   either kind is recorded. There is no "build on the host if the container is unavailable"
   path, and no per-run parameter can select host execution: the posture is the worker's
   environment. [measured]
7. **Cancel and the wall clock end in `docker kill`.** `DockerExecutor.stream()` /
   `DockerStream` (core, additive) stream the container's stdout to the unchanged
   stream-json parser and kill the *container* (then the client) on the run's cancel token
   or the budget's wall clock — killing the client alone would leave the container running.
   `docker kill` returns when the signal is sent, not when the daemon stops listing the
   container, so the kill is **confirmed** (2026-09-21): `DockerStream.kill()` polls
   `docker inspect -f {{.State.Running}}` (≤ 10 s, 100 ms steps; a removed `--rm`
   container is gone) and `lines()` waits for that poll, recording `kill_confirmed` and
   warning when the bound is hit — "cancelled" means the container is not running.
   [measured]
8. **The post-hoc guards stay on as belt-and-braces**, not as the wall: the shell guard,
   the CLI deny rules and the tamper check still run (container paths are translated to
   the host copy so path verification keeps working); a violation is still recorded
   fail-closed. They can no longer be the only thing between a builder and the answer.
9. **Per builder.** `claude_code`: the CLI process itself runs in the container (its own
   test runs included) through the same `SpawnFn` contract as before. `openai_agent`: the
   tool loop is trusted worker code and stays host-side, talking to the model as it always
   has; the *model's* commands (`run_command`, `run_target_tests`) execute in the builder
   image over the sealed checkout with `--network=none`, and its file tools act on the
   sealed checkout. `editblock`: sealed checkout only (it runs nothing). `fixture_gold`
   (test-only) replays the commit's own sources from the main clone and is left unsealed by
   design.

## Consequences

- A deployment that sets `CRB_BUILDER__EXECUTOR=docker` needs the builder image in the
  host daemon's store (`deploy/README.md` §9) and, as for the sandbox, the same `$CRB_HOME`
  path on the host and in the worker container (the daemon resolves bind-mount sources on
  the host). Toolchains the builder needs must be **inside the image** — it has no network
  to install them, which is also the protocol.
- Every attempt pays for a network create, a sidecar start and an export of the parent
  tree (seconds; the export is a tar extraction). Worktree and sealed checkout are both
  disposable and both removed after grading unless `retain.worktrees` is set.
- A repository whose tests need an operator-provisioned service (Wave C15) needs that
  service reachable from the builder image too; the allowlist is per host, not per
  builder, so a service hostname can be allowlisted alongside the endpoint.
- `crb doctor` should report the posture: `probe_builder_container()` returns
  `up | down | off` with the images and the allowlist; wiring it into
  `cli/commands/service.py` is a one-line addition for that file's owner.
- `crb.builders.egress_proxy` is a standalone standard-library file (it runs where crb is
  not installed) and is unit-tested in process; it is copied next to the sealed checkout
  per attempt and mounted read-only, so the sidecar always runs the worker's version.

## Alternatives considered

- **Keep the worktree, harden the guard.** Rejected: a parser cannot make history
  *unreachable*; the false-positive classes were the symptom of asking it to.
- **`git clone --depth 1 file://<worktree>`.** Works (the transport sends only objects
  reachable from HEAD at depth 1) but depends on transport semantics and leaves a
  `shallow` marker and a remote to scrub; `git archive` is a single tree object by
  definition and needs no scrubbing.
- **Share the sidecar's network namespace (`--network=container:<proxy>`).** Rejected: the
  builder would share the sidecar's egress route and could bypass the proxy entirely.
- **A host-side proxy.** Rejected: an `--internal` network has no route to the host on
  colima / Docker Desktop, and a host listener is one more thing on the worker host.
- **tinyproxy / squid in a package.** Considered; a 200-line CONNECT-only proxy we can read
  in full, unit-test in process and ship inside our own image was preferred over a
  configurable general-purpose proxy whose default is to proxy everything.
- **Run the builder as `nobody` and `chmod 777` the checkout** (the sandbox's convention).
  Rejected for the builder: it must write everywhere in the checkout; the worker's own uid
  keeps ownership sane on every platform without widening permissions.
- **gVisor / Kata for the builder.** Deferred, as in ADR-0005: the `Executor` seam allows it.
