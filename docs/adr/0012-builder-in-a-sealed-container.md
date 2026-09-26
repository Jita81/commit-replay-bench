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
7. **Cancel and the wall clock end in `docker kill`, and an unconfirmed kill is visible and
   reaped — never a silent terminal `cancelled`.** `DockerExecutor.stream()` /
   `DockerStream` (core, additive) stream the container's stdout to the unchanged
   stream-json parser and kill the *container* (then the client) on the run's cancel token
   or the budget's wall clock — killing the client alone would leave the container running.
   `docker kill` returns when the signal is sent, not when the daemon stops listing the
   container, so `DockerStream.kill()` makes a **bounded confirmation attempt**
   (2026-09-21): it polls `docker inspect -f {{.State.Running}}` for at most
   `KILL_CONFIRM_S` = 10 s in total after the kill (`KILL_CONFIRM_STEP_S` = 100 ms steps;
   every inspect call is given only the time left, so a slow daemon cannot stretch the
   wait; only the exact strings `true` / `false` are read — an empty or otherwise malformed
   exit-0 answer is unknown, never a stop; a removed `--rm` container is gone) and
   `lines()` waits for that attempt to end. The attempt can end without confirming, and a
   reader must read `kill_confirmed`. **The non-stream path holds the same contract**
   (2026-09-21): `DockerExecutor.run()` under the run's cancel token — the belt / oracle
   test run of the grade stage, and the `openai_agent` model's commands through
   `ContainerSession.tools_executor()` — ends a cancel or the wall clock in `docker kill`,
   then the client's process group, then the same bounded confirmation; the result carries
   `ExecResult.kill_confirmed` and `container`, and an unconfirmed kill is recorded on
   `DockerExecutor.unconfirmed_kills` and handed to the executor's `on_kill_unconfirmed`
   before `run()` returns. **The reaper contract** (2026-09-21) governs the unconfirmed
   case on every path: the run still ends `cancelled` / timed out — it did stop building —
   but the kill is reported to the worker (a sealed attempt's, build stream or tool-loop
   executor alike, via `ContainerSession.unconfirmed_kills` →
   `build_fn_for(on_kill_unconfirmed=…)`; the grade stage's via
   `make_executor(on_kill_unconfirmed=…)`) and the
   worker (1) writes a system `run.kill_unconfirmed` event (status error; `container`,
   `run_id`, `bound_s`, `task_id`) on the run's trace and appends "container `<name>` may
   still be running — it will be reaped by the worker; `docker rm -f <name>` reaps it by
   hand" to the run's error, a sealed attempt's evidence pack carrying
   `notes.kill_confirmed: false` and `notes.container`; (2) queues the name durably in
   `<CRB_HOME>/unconfirmed-containers.json` (`crb.server.reaper`) and, on every poll of its
   loop, makes one pass — `docker inspect`, `docker rm -f`, `inspect` — under a **time
   budget** of `heartbeat_s / 2` (`Worker.reap_budget_s`; every docker call is capped to
   the time left in the pass, the entry the budget runs out on counts one attempt with the
   reason `pass budget exhausted`, and the entries the pass never reached wait for the next
   poll), so a daemon that answers nothing can hold the idle loop for at most the budget
   and the check-in that follows is never later than the worker's own liveness bound
   (`3 × heartbeat_s`); the pass writes `run.kill_reaped` when the daemon reports the
   container gone or not running, or after 20 passes `run.kill_reap_failed` (status error,
   with the by-hand command) and drops it; the check-in row carries the pending count
   (`workers.unconfirmed_containers`, revision 0008) so the `/health` worker probe reports
   `unconfirmed_containers` and reads `degraded` until the queue is empty; (3) the run
   page's Progress card says "a container may still be running (being reaped by the
   worker)" from `run.kill_unconfirmed` until `run.kill_reaped` lands (or names the by-hand
   command after `run.kill_reap_failed`) — the UI's SSE ring buffer pins the
   `system/run.kill_*` events so a busy run cannot evict them before the line is read.
   **The bound on the wait after a cancel** (both paths; constants in
   `src/crb/core/execution.py`): the command's own timeout + `_CANCEL_POLL_S` (1 s, the
   token poll) + `DOCKER_KILL_TIMEOUT_S` (30 s, the subprocess timeout on the `docker kill`
   call itself — a hung daemon can hold the client that long) + `KILL_CONFIRM_S` (10 s,
   the confirmation attempt) — i.e. timeout + 41 s in the worst case, and timeout + ≈1 s
   against a daemon that answers.

   Evidence, by apparatus:
   - [measured] **Scripted-docker unit tests** (no daemon; `tests/test_execution.py`, n = 21
     cases; method: `DockerStream`, the cancellable `DockerExecutor.run` path and the helpers
     against a `docker` shell script whose `inspect` answers are scripted): the kill is
     confirmed by polling (`true, true, false`
     → three inspects, `kill_confirmed` True before `lines()` returns); the bound is held and
     warned (`always-true` → False, 1.3 s ≤ elapsed < 5 s); a removed container is gone
     (`No such container` → True after one inspect); a natural exit asks nothing; the strict
     parse (8 parametrised answers — only exact `true` / `false` read, `""`, `True`,
     `FALSE`, `false extra`, `<no value>`, `null` are unknown; a non-zero exit without
     "no such" is unknown); the budget across inspect calls (an inspect that sleeps 5 s under
     a 0.5 s bound ends in 0.5–2 s, never 5.5 s; each call's budget is the time remaining,
     strictly decreasing). The non-stream path (5 cases): a cancel mid-command is confirmed
     (`true` then `false` → two inspects, rc 130, `kill_confirmed` True, the container named,
     nothing reported, done well inside the wall clock); an `always-true` daemon ends the
     attempt at the bound with `kill_confirmed` False, the kill on `unconfirmed_kills` and
     handed to `on_kill_unconfirmed` before `run()` returns, a callback that raises logged
     and never the result; the wall clock against a removed container is confirmed after
     one inspect (rc 124); a natural exit asks nothing; `make_executor` hands the report to
     the docker executor only. The worker side (`tests/test_worker.py`, n = 6 cases; method:
     the worker over SQLite with a session double that reports one unconfirmed kill, and an
     executor double that reports one from the grade stage): the event, the run's error
     note, `notes.kill_confirmed: false` in the pack, the durable queue and the check-in
     count; the grade stage's kill filed under the task being graded with the same note and
     queue entry; the reap pass writing `run.kill_reaped`; giving up at the bound with
     `run.kill_reap_failed`; the polling loop reaping without a run claimed; and the pass
     budget — a daemon sleeping 3 s per answer with two entries queued: the pass ends in
     under `heartbeat_s` (budget `heartbeat_s / 2`), the first entry carries one attempt with
     `pass budget exhausted`, the second is untouched, and the check-in row sampled every
     200 ms while the loop runs is never older than `3 × heartbeat_s`. The reaper alone
     (`tests/test_server_reaper.py`, n = 8 cases, two on the budget: three entries against a
     2 s-per-answer daemon under 0.5 s end in under 1 s with no answer counted as a stop; a
     0.2 s daemon under 1 s gets its first entry's three calls in full and the third entry
     is never reached until the next pass). The session's report
     (`tests/test_builders_container.py`, n = 2 cases: the streams' and the tool-loop
     executors' kills). The probe (`tests/test_server_system.py`, n = 1 case). The UI ring
     (`ui/src/screens/Runs/RunDetailPage.test.tsx`, n = 1 case: a `run.kill_unconfirmed`
     survives 18 later events in a 3-event ring and the container line still reads
     "being reaped"; `run.kill_reaped` clears it).
   - [measured] **Colima integration runs** (`tests/test_builders_container_docker.py`,
     `test_cancel_kills_the_container` and `test_wall_clock_kills_the_container`, unchanged;
     n = 4 runs × 2 tests = 8 passes, 0 failures, and `docker ps -a --filter name=crb-build`
     empty afterwards; method: a real `sleep 60` container in the builder image, cancelled
     via the token and killed by a 3 s wall clock, `lines()` returning within 30 s and
     `docker ps` not listing the container; apparatus: docker server 29.5.2 (client 29.6.1)
     via colima 0.10.3, macOS 26.6.2 arm64, Python 3.12.13, commit f538cfe). These runs
     exercise the confirmed path only — the daemon confirmed every kill; the unconfirmed
     path is provable only against a scripted daemon (above).
   - [measured] **Colima integration runs, the non-stream path** (`tests/test_sandbox_docker.py`,
     `test_cancel_kills_the_container_and_the_daemon_confirms_it` and
     `test_wall_clock_kills_the_container_and_the_daemon_confirms_it`; n = 3 runs × 2 tests
     = 6 passes, 0 failures, the two docker suites 18/18 on each run in 21–24 s, and
     `docker ps -aq --filter name=crb-` empty afterwards; method: `DockerExecutor.run` on a
     real `sleep 60` in `crb-test-py:local`, the cancel token flipped at 2 s and a 3 s wall
     clock, `run()` returning within 30 s with `kill_confirmed` True, the container named on
     the result and not listed, nothing handed to `on_kill_unconfirmed`; apparatus: docker
     server 29.5.2 (client 29.6.1) via colima, macOS 26.6.2 arm64, Python 3.12, commit
     36de2d3, from a worktree under `$HOME` with `PYTHONPATH` pinned to it). Confirmed path
     only, as above.
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

## Amendment 2026-09-25 — ADR-0019: the sealed builder may read the parent's dependency set, never the gold's

Dependencies are provisioned per task (ADR-0019): the parent's and the gold's lockfiles are
read from git objects, fetched outside every test container and sealed read-only. Two things
follow for this ADR:

- **The egress sidecar is shared.** `crb.builders.sidecar.EgressSidecar` is the
  `--internal` network and CONNECT-only proxy this ADR introduced, extracted from
  `ContainerSession` with no change in behaviour; the dependency fetch runs behind the same
  program with the registry hosts as its allowlist. The builder's allowlist does not change:
  model endpoints only. A package registry is never on it.
- **The builder may be given the parent's set, never the gold's.** A builder that runs the
  repository's tests before it answers needs the dependencies the parent tree declares. When
  a task's dependencies are bound, the builder container mounts `TaskDeps.builder` — the
  parent-only set — read-only with the same offline environment as a test container. The
  gold's set is never mounted where a builder can read it: its module list is part of the
  answer (SECURITY T21). A trial whose own manifests step outside the task's closure is
  disqualified at grading, never graded against a set it was not given.
