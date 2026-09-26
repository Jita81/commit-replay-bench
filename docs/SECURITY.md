# Security and threat model

_Audience: the security reviewer of an organisation self-hosting Commit Replay Bench (crb).
Every control below names the code that implements it. Statements about behaviour carry
the repository's claim tags (docs/EVIDENCE-AND-CLAIMS.md §1): **[measured]** where a test
in this repository proves them — for a security control the "n, method, apparatus" of a
measured claim is the named test, what it exercises, and the release it runs in;
**[hypothesis]** where the control is implemented but not yet covered by an end-to-end
test; **[aspiration]** where it is designed for and not yet built. (Earlier editions wrote
**[design]** for the second and third of these; read it as **[hypothesis]** where the code
exists and **[aspiration]** where it does not.)_

## 1. What the system does, in security terms

crb runs **untrusted code twice** per graded trial:

1. **Repository test suites** — the customer's own repositories, at historical commits, in
   the language's native test runner. These are arbitrary programs.
2. **AI builders** — an agent that reads and edits a throwaway worktree and, for the agentic
   adapters, runs commands inside it.

It also stores verdict evidence that must be **tamper-evident** for audit, and it holds
model-provider credentials that must never reach either of the untrusted contexts above.

The security objective is therefore threefold: **contain** untrusted execution, **protect**
credentials and the host, and **prove** that stored evidence has not been altered.

## 2. Trust boundaries

```
┌────────────────────────── customer tenant ──────────────────────────┐
│  Operator / Approver / Viewer  ──(OIDC, cookie session, RBAC)──▶ API │
│                                                                      │
│  API (crb.server) ──▶ Postgres/SQLite (append-only ledger tables)    │
│        │                                                             │
│  Worker (crb.server.worker) ──▶ throwaway git worktrees             │
│        ├──▶ Sandboxed test runs   [docker: no network, read-only]    │
│        └──▶ Builder attempt       [CRB_BUILDER__EXECUTOR=docker:     │
│              sealed export of the parent tree (no gold commit in its │
│              object store) in a hardened container on an --internal  │
│              network ──▶ egress sidecar (CONNECT-only allowlist) ──┐ │
│              host mode (dev/eval): worktree; egress = worker's]    │ │
│                                                                    │ │
│  Model endpoint (Azure OpenAI in-tenant / configured provider)  ◀──┘─┘
└──────────────────────────────────────────────────────────────────────┘
```

**What crosses the tenant boundary — the complete list.** Nothing leaves the deployment
except these three flows, each to an endpoint the operator configures, and each carrying
only what is named here:

| Flow | Endpoint | What is sent | What is never sent |
|---|---|---|---|
| Builder / labeller / reviewer calls | the model endpoint (`CRB_OPENAI_BASE_URL` / Azure / Anthropic) | the task brief, the source files the builder reads in its worktree, tool results, the diff it writes | the held-out tests, the ledger, credentials, other repositories |
| Repository clone and fetch | the repository's git remote (`repos.url`) | the git protocol; the push token only on an `https://` / `ssh` remote and only for factory delivery (§3.4 / `crb.factory.delivery`) | anything not in the git protocol |
| Sign-in | the OIDC issuer (`CRB_OIDC__ISSUER`, https-only) | the authorisation code flow (PKCE), the ID-token validation against the issuer's JWKS | the session cookie, any repository content |
| Intake — the watched column (ADR-0017; **off by default**, and off entirely unless `CRB_INTAKE__TRACKER` names one) | the tracker (`CRB_INTAKE__URL`, https-only): Azure DevOps `/_apis/wit/*` or Jira `/rest/api/3/*` | a WIQL or JQL query naming the configured project, column and area path; a read of the work items it returns; and, per ticket, up to four comments each marked as its own (what is missing, queued, the pull request, the stop), ONE `crb:` label, a link to the backlog item and a link to the pull request, and — only where `CRB_INTAKE__OUTCOME_MAP` configures it — ONE state transition **[measured — n = 1 ticket driven through a poll, a delivery, a stop and a configured transition: four distinct markers, two links, one label, one state change, and the same notes posted again add none; method: the real service over the shared fake board, `tests/test_intake_write_bound.py::test_the_whole_life_of_a_ticket_is_four_comments_two_links_one_label_one_transition`, with the renderer and verb count in `tests/test_intake_feedback.py::test_the_comment_counts_what_it_writes_rather_than_promising_it_writes_little`; release 2.0.0a1, apparatus 2.2]**. One pass reads at most `CRB_INTAKE__MAX_PER_POLL` tickets (200), and once `CRB_INTAKE__POLL_BUDGET_S` (60 s) has gone it starts no further tracker call: it serves what it read and says it stopped. That is a bound on how many calls are made, not a stopwatch on the pass — the call already running is not cancelled, so a pass takes the budget plus the verb in progress, not the budget exactly. A column therefore cannot become an unbounded egress **[measured — n = 2 bounds; method: a column of 5 against a bound of 4 reads not one ticket and stops `column_too_large`, and a pass whose budget goes serves what it read and records the stop, whether it goes between tickets or inside the last one (`tests/test_intake_service.py::test_a_column_bigger_than_one_pass_may_read_stops_rather_than_walking_it`, `::test_a_pass_that_runs_out_of_time_serves_what_it_has_and_says_so`, `::test_a_budget_that_runs_out_inside_a_ticket_starts_no_further_tracker_call`, `::test_a_budget_that_runs_out_inside_the_last_ticket_stops_the_pass_not_only_the_row`, `::test_the_default_bounds_are_the_settings_defaults`); release 2.0.0a1, apparatus 2.2]** | the source code, the diff, the ledger, an evidence pack, any other repository's content, any field of the ticket other than its own comment, its `crb:` label and the mapped state; the model endpoint's credentials |

The intake flow is the only one that WRITES to a third-party system, and what it may write
is bounded by the size of the protocol it has (`crb.intake.client.TrackerClient`: six verbs,
no more) rather than by a rule somebody has to remember **[measured — n = 6 verbs and 4
renderers counted against the sentence the ticket itself carries; method:
`tests/test_intake_feedback.py::test_the_comment_counts_what_it_writes_rather_than_promising_it_writes_little`
enumerates `TrackerClient`'s public functions and `crb.intake.feedback`'s `render_*`
functions, so a seventh verb or a fifth note fails the test; release 2.0.0a1, apparatus 2.2]**.
Its credential lives in the product's own secret store (`tracker_token`, owner-only, read back
as a fingerprint), never in a URL, a log, an event or an error message — which is not a promise
but a test **[measured — n = 2 passes (one that reads the board, one that cannot reach it, where
the detail is built) × 5 records searched for the stored value: the log at DEBUG level, the
served intake view, the state file, the evidence chain and the settings body; method:
`tests/test_server_routes_intake.py::test_the_tracker_token_is_in_no_log_no_event_no_state_file_and_no_error`;
release 2.0.0a1, apparatus 2.2]**.

Since 2026-09-25 (assessment C6, ADR-0022) the intake boundary also holds four more rules.
The credential is sent only to the tracker's own origin: a request URL whose scheme, host or
port differ from the configured one is refused before the header is attached **[measured —
n = 4 foreign URLs refused and never sent (another host, another scheme, another port, a
lookalike host), the same origin served absolute and relative; method:
`tests/test_intake_adapters.py::test_an_absolute_url_on_another_origin_is_refused_and_never_sent_the_credential`,
an `httpx.MockTransport` that records every request; release 2.0.0a1, apparatus 2.2]**. What a
ticket says reaches a customer's pull request only inside one fenced code block, the title
is escaped to one inert line and the branch is `[a-z0-9-]` **[measured — n = 1 hostile title
and 2 hostile criteria (a code span, emphasis, an HTML comment, a mention, a link, a fence and
a heading, an image tag) and 5 item ids; method:
`tests/test_factory_delivery.py::test_ticket_text_in_the_pr_body_is_fenced_and_cannot_become_markup`,
`::test_the_pull_request_title_escapes_the_ticket_titles_markdown`,
`::test_the_delivery_branch_is_lowercase_letters_digits_and_hyphens` (with
`git check-ref-format`); release 2.0.0a1, apparatus 2.2]**. A ready ticket is registered only
by an operator's evented Register act unless its author is on an explicit allowlist, and one
pass per repository runs at a time under a lease row **[measured — n = 5 cases: a ready ticket
waits, the act registers the draft read, a moved revision is refused, an allowlisted author
bypasses and others wait, two overlapping passes register once; method:
`tests/test_intake_service.py` (the C6 section) and `tests/test_server_routes_intake.py` (the
same at the API); release 2.0.0a1, apparatus 2.2]**.

There is no telemetry, no update check, no licence phone-home, and the opt-in federated
export (ADR-0007) is a file the operator produces, never a call the product makes. With the
builder in its container (ADR-0012) the model endpoint is reachable from exactly one
process — the egress sidecar — and only for the hosts on the allowlist.

## 3. Controls

### 3.1 Sandboxed test execution — `crb.core.execution.DockerExecutor`

| Control | Implementation | Status |
|---|---|---|
| No network | `--network=none` on every test run, with no exception: `Command.network=True` is **refused** under docker (`SandboxUnavailable`: "dependencies are provisioned per task, never installed in the sandbox") — a repository's dependencies arrive as read-only sealed sets fetched outside the test container (3.1.1, ADR-0019) | [measured] `tests/test_execution.py` asserts the argv flag-by-flag and `test_network_true_is_refused_under_docker` pins the refusal for both tree modes |
| Immutable root + worktree; tests in a throwaway copy | `--read-only`; the worktree bind-mounted `readonly` at `/src` and every command run in a **throwaway copy** of it — a tmpfs at `/work` capped at `work_size`, owned by the container's uid (mode 0700), `exec,nosuid,nodev`, copied by GNU `tar` and gone with the container (ADR-0019 §7; the `readonly` tree keeps the worktree itself read-only at `/work`, a separate posture). A test that writes its own tree (cobra's `TestDeadcodeElimination`) behaves as on the host and nothing it writes reaches the host; a copy that fails is `env_error: tree_copy_failed`, never a verdict. The tree reaches the container whole whatever its host modes: the container's user owns nothing on the host, so before a container starts `grant_sandbox_read` adds read (and search, on a directory) for the owner and for others on every path the worker owns — what a git checkout under the default umask already has; never a write bit, never git's execute bit, never through a link (the command's own writable paths are left at `0733`). A path it cannot make readable fails the copy closed, and GNU tar's "removed before we read it" is fatal although tar exits 1 for it, so no path is ever silently left out of the copy (PR #56). Writable scratch only at declared paths (`target/`, `.pytest_scratch`) and tmpfs `/tmp` with `noexec,nosuid,nodev` stated on the argv. **The one exception:** `exec` in place of `noexec` for a command whose toolchain runs the binaries it builds there — the Go runner declares `Command.exec_tmp` so `go test` can exec its test binaries; `nosuid,nodev` and every other flag hold, and the tmpfs dies with the container. The exception is **per toolchain** (a runner declares it in its `command()`), never per repository: no `RepoConfig` key, `runner_opts` or run request can set it | [measured] `tests/test_execution.py::test_copy_tree_argv_mounts_the_worktree_read_only_at_src_and_a_sized_exec_tmpfs_at_work` and `::test_readonly_tree_keeps_todays_argv` pin both tree shapes token by token; `tests/test_sandbox_docker.py::test_a_path_host_modes_hide_from_the_sandbox_uid_still_reaches_the_tests` (both trees), `::test_a_command_after_a_runner_wrote_its_scratch_still_copies_the_tree` and `::test_the_copy_fails_closed_on_a_path_it_cannot_read_never_drops_it` plant a mode-000 directory, a mode-600 file and a mode-000 file and read them from inside the container, and `tests/test_execution.py::test_docker_run_lets_the_sandbox_uid_read_the_tree_never_write_never_through_a_link` pins the exact modes the grant leaves **[measured — n = 4 docker tests + 2 unit cases, colima (Docker 29.5.2), 2026-09-26, apparatus 2.3; the Linux ownership case (a runner uid that is not the sandbox's) was reproduced once in a container before and after the grant, and CI's `sandbox-images` job is its standing check]**; `tests/test_sandbox_images_docker.py::test_a_test_can_write_its_tree_and_nothing_reaches_the_host` proves from inside each shipped image that `/src` refuses a write, `/work` accepts one and the host tree stays byte-identical (n = 3 images, colima, Docker 29.5.2, 2026-09-25, apparatus 2.2). `tests/test_execution.py` also asserts both tmpfs shapes token by token (`noexec` present / `exec` absent for an ordinary command, the reverse for `exec_tmp`) and that nothing else in the argv differs; `tests/test_sandbox_images_docker.py::test_tmp_is_noexec_unless_the_runner_declares_exec_tmp` reads `/proc/mounts` inside each shipped image and tries to run a script written under `/tmp` (`noexec` + `Permission denied` for the python and node runners' commands; `exec` + it runs only for the Go runner's, which is the only runner whose `command()` declares `exec_tmp`) — 3/3 images built from this tree (colima, Docker 29.5.2, 2026-09-22) and in CI's `sandbox-images` job on every pull request (PR #44 run 35678358686 on the merged head 4a64fe3); the read-only root, read-only worktree, writable `/tmp` and no-setuid proofs: 10 tests × 3 images, same suite; apparatus 2.2 |
| Sealed dependency sets, read-only | A binding's `ro_mounts` are rendered `--mount …,readonly` only after `validate_mount` re-checks each one: inside a registered bundle store, under its `dep_<sha256>` key directory, nothing in it writable. A forged or unsealed mount is `SandboxUnavailable` | [measured] `tests/test_execution.py::test_a_bundle_mount_outside_the_store_is_refused`, `tests/test_provision_store.py::test_a_mount_outside_the_store_or_without_a_key_name_is_refused` |
| Least privilege | `--cap-drop=ALL`, `--security-opt no-new-privileges`, non-root `--user=65534:65534` (root refused at construction) | [measured] |
| Resource caps | `--memory`, `--cpus`, `--pids-limit`, `--stop-timeout`; wall-clock timeout returns `rc=124` and is graded as a failure, never a pass | [measured] |
| Fail closed | No docker binary, unreachable daemon, root user, docker-socket or `$HOME` mount request, or a launch failure (exit 125) raise `SandboxUnavailable`; the **run stops** and is recorded `failed`. The product never degrades to in-process execution when the sandbox was requested. `--pull=never`: an image absent from the daemon's store is a launch failure, never a registry pull at run time | [measured] `tests/test_execution.py`, `tests/test_sandbox_docker.py` (skipped without a daemon), `tests/test_sandbox_images_docker.py` (an absent image is `SandboxUnavailable` against a real daemon, the match pinned to the daemon's no-pull wording `No such image` — dropping `--pull=never` reads `pull access denied` and fails the test; 3/3 images locally, 2026-09-22, and CI's `sandbox-images` job on every pull request) |
| Host environment isolation | `LocalExecutor` (development only) passes through an explicit allowlist of variables (`PATH`, toolchain caches); operator secrets are proven absent inside the child | [measured] `test_execution.py::…env…` |

**Residual risk:** container escape via the kernel. Mitigation is the standard one — keep the
container runtime patched; run the worker on a dedicated node; consider gVisor/Kata for
hostile repositories. This is documented, not implemented.

**The images.** `deploy/sandbox/Dockerfile.{python,node,go}` are the reference sandbox
images: each `FROM` pinned by the multi-arch index digest, the toolchain and the test runner
only (pytest hash-pinned; Go copied onto a slim base without gcc or git), `USER 65534:65534`,
OCI labels, hadolint-clean **[measured — `tests/test_sandbox_images_docker.py` reads `USER`
and the six labels from each image's config; hadolint in CI]**. CI's `sandbox-images` job
builds each on every pull request and proves the controls above from inside it through the
real runner of that language **[measured — 10 tests × 3 images before ADR-0019: uid 65534 by default and
under the executor, `/usr` + `/work` read-only from inside (now `/src`, with `/work` the throwaway copy), `/tmp` writable and `noexec`
except for the Go runner's command, no setuid/setgid file in the image, a network probe
fails through the runner, an absent image is `SandboxUnavailable` without a pull, qualify +
grade clean; 47 passed / 0 skipped with the sandbox and sealed-builder suites on the python
image, on images built from this tree, colima / Docker 29.5.2, 2026-09-22 — the same step CI
runs on every pull request (PR #44 run 35678358686 on the merged head 4a64fe3, 44 passed /
0 skipped before this commit's three added tests); apparatus 2.2]**. The worker reads the same `CRB_SANDBOX__EXECUTOR`
/ `CRB_SANDBOX__IMAGE` the API reports — until 2026-09-21 it read only its short forms, so a
compose / Helm worker ran `local` while `/settings` said `docker` — and a repository's own
`sandbox_image` wins over the deployment default **[measured — `tests/test_worker.py`
`test_settings_from_args_env_fallbacks`, `test_docker_settings_resolution`]**. Selection,
extension and the re-pin cadence: `deploy/sandbox/README.md`.

#### 3.1.1 Dependency provisioning — `crb.core.deps`, `crb.provision` (ADR-0019)

A task's dependencies are fetched **outside** the test container, sealed and mounted
read-only. Provisioning is **off** until an operator switches it on
(`CRB_PROVISION__ENABLED`); while it is off, a repository that declares dependencies is
refused `PROVISION_DISABLED` under docker before any spend.

| Control | Implementation | Status |
|---|---|---|
| Inputs from git objects only | The lockfiles at the parent and at the gold are read with `git cat-file blob <sha>:<path>`; no fetch path accepts a worktree, so nothing a builder writes can change what is fetched. `.npmrc`, `pip.conf`, `go.env` and `.pypirc` are never read; Python's lock is rewritten from the parsed pins, so no include, option or index line of the repository reaches pip | [measured] `tests/test_provision.py::test_lock_inputs_are_read_from_git_objects_not_the_worktree`, `::test_repository_config_files_are_never_read`, `tests/test_provision_python.py::test_pip_fetch_is_wheels_only_from_the_parsed_pins` |
| Refused before any container starts | A URL, VCS, path or foreign-registry source, an unpinned version, `go.work`, yarn / pnpm / poetry / uv / pylock locks, npm lockfileVersion 1, an install script the repository did not name, JVM and Rust — each a `PROVISION_*` code with its fix | [measured] `tests/test_provision.py` (one test per refusal) |
| The fetch container | Digest-pinned toolchain image (with CA certificates); the worker's non-root uid (root refused); `--read-only`, `--cap-drop=ALL`, `no-new-privileges`, memory / cpu / pid caps, `noexec` `/tmp`; it sees `/in` (the lockfiles, read-only) and `/out` only — never a worktree, the source, a secret or `CRB_HOME`; its environment is the recipe's fixed allowlist and a secret-looking name is refused at construction | [measured] `tests/test_provision_fetch.py::test_fetch_argv_is_internal_network_proxy_only_no_worktree_no_secret` pins every token; `::test_fetch_user_is_the_worker_and_never_root` |
| Egress | The fetch's only network is an `--internal` bridge whose only way out is the CONNECT-only allowlisting proxy (`crb.builders.sidecar`, the same program as the builder's) to the configured registry hosts; a `file://` mirror runs with **no network and no sidecar**. `GOPROXY` is never `direct`, `GOVCS=*:off`, `GOTOOLCHAIN=local`; a denied host is named in the refusal | [measured] `tests/test_provision_fetch.py::test_an_airgapped_mirror_runs_with_no_network_and_no_sidecar`, `::test_a_denied_host_is_named_in_the_refusal` (a real daemon; the proxy refuses before any connection), `tests/test_provision_go.py::test_go_fetch_never_uses_direct_or_a_vcs` |
| No repository code runs with a network | `go mod download`; `npm ci --ignore-scripts`; `pip download --only-binary=:all:`. A Python install and a named Node install script run in a **second** container with `--network=none` | [measured] `tests/test_provision_python.py`, `tests/test_provision_node.py` (the plans, and a daemon run of each) |
| Integrity | Go checks every module against the committed `go.sum` (and the checksum database unless the mirror is air-gapped); npm checks every tarball against the lock's `integrity`; pip enforces `--require-hashes` when the lock carries hashes and the manifest records the fetched hash when it does not | [measured] the daemon tests of each recipe fetch against committed hashes (`tests/test_provision_go.py::test_go_fetch_puts_parent_and_gold_in_one_cache`) |
| The store | Content-addressed (recipe, fetch image ID, lockfile blob hashes); built in a 0700 stage; sealed with a sha256 output digest in `bundle.json`, every write bit removed, renamed atomically; the only constructor of a mount; `crb deps verify` re-proves the digest (`BUNDLE_INTEGRITY`, run scope) | [measured] `tests/test_provision_store.py` |
| The host never follows what a container wrote | A named install or rebuild step runs package code with `/out` writable. Before the seal, a symlink that leaves the set (absolute, or escaping read as written or once resolved) or anything but a regular file at `bundle.json` is `PROVISION_UNSAFE_OUTPUT` (task scope) and the stage is discarded; the manifest is written as a new file with `O_EXCL \| O_NOFOLLOW`; removal never changes permissions through a link; a link to a directory inside a set is part of its digest, so `crb deps verify` sees it swapped | [measured] `tests/test_provision_fetch.py::test_links_a_fetch_plants_in_out_never_lead_the_host_out_of_the_stage` (a real daemon: the links planted from inside the container, the host file and directory unchanged), `tests/test_provision_store.py::test_a_link_planted_in_the_output_is_refused_and_never_followed`, `::test_removal_never_chmods_through_a_link`, `::test_a_directory_link_inside_the_set_is_in_the_digest` |
| Limits | A watchdog kills a fetch past `CRB_PROVISION__MAX_BUNDLE_MB` (`PROVISION_TOO_LARGE`); the wall clock is `CRB_PROVISION__FETCH_TIMEOUT_S`; `crb deps gc` never removes a cited key, nor a stage a live fetch in any process still holds (each stage is leased with an exclusive `flock` the kernel drops with a crashed process; a lease counts only once it is locked and still the file at its path, and `gc` unlinks a lease only while it holds its lock) | [measured] `tests/test_provision_fetch.py::test_an_oversized_fetch_is_killed_and_refused`; `tests/test_provision_store.py::test_gc_never_removes_a_stage_a_fetch_is_still_filling`, `::test_a_gc_between_the_lease_and_its_lock_never_orphans_a_live_stage`, `::test_gc_removes_a_lease_only_while_it_holds_that_lease_itself` |
| Production | A public registry is refused unless `CRB_PROVISION__ALLOW_PUBLIC`; a fetch image without `@sha256:` is refused — both at start-up | [measured] `tests/test_settings_provision.py` |

### 3.2 Builder containment — `crb.builders.base`

| Control | Implementation | Status |
|---|---|---|
| Test files are immutable to the builder | `TestFileGuard` refuses writes to the target tests (sighted) or to any test-looking path (blind); belt 1 re-hashes the oracle against the real commit at grade time, so a bypass is **disqualified**, never credited | [measured] `tests/test_builders_base.py`, `tests/test_grade.py` |
| No path traversal / `.git` writes | `TestFileGuard` normalises and confines every write to the worktree root | [measured] |
| No git archaeology | `GitArchaeologyGuard` denies `git log/show/reflog/diff <sha>/checkout <sha>/stash/bisect` in agentic tool loops; the Claude Code adapter additionally passes `--disallowedTools` deny rules and records any violation seen in the transcript fail-closed | [measured] |
| Bounded loops | `Budget` caps turns, tool calls, tokens, cost and wall clock; a loop with no bound is a constructor error | [measured] |
| Minimal credentials | The Claude Code adapter runs `claude -p --bare` (auth mode `api_key`, the default): authentication is strictly `ANTHROPIC_API_KEY` from the worker's environment, never the operator's keychain or OAuth profile; the target repository's `CLAUDE.md`/hooks are not loaded (prompt-injection vector); `--no-session-persistence` keeps transcripts off disk | [measured] argv asserted in `tests/test_builders_claude_code.py`; verified against CLI 2.1.132 |
| `cli` auth mode is developer/evaluation only | `builder_config: {"auth": "cli"}` (or `CRB_CLAUDE_CODE_AUTH=cli`) drops `--bare` and uses the worker user's own `claude login` — the operator's identity and subscription spend. Still enforced: the tool set, `--permission-mode dontAsk`, the `--disallowedTools` deny rules, `--disable-slash-commands`, `--no-session-persistence`, `--setting-sources user` (the target repository's `.claude/settings.json` / `settings.local.json` hooks and permission rules are NOT loaded), a minimal child environment (`PATH HOME LANG LC_ALL TMPDIR TERM TZ` + `USER`/`LOGNAME`/`CLAUDE_CONFIG_DIR`, no API key), and every post-hoc guard. **Not isolated:** the target repository's `CLAUDE.md` files ARE auto-discovered (only `--bare` skips them — `--setting-sources` governs settings, not memory files), the operator's `~/.claude/CLAUDE.md` and user-level settings/hooks load, the keychain is read. Never use it on a server; the mode is recorded in the run's apparatus so a ledger row from it is identifiable | [measured] argv/env asserted in `tests/test_builders_claude_code.py`; live 1-turn probe on CLI 2.1.132 (W3-B report) |
| Clone sources are policy-checked | A URL-only repository is cloned by the worker only from `https://` / `ssh://` / `user@host:path`; `http://`, `git://`, local paths and `file://` are refused at registration (422) and at clone time (`file://` only under `CRB_ALLOW_LOCAL_CLONE=1`, a test/dev switch); `GIT_TERMINAL_PROMPT=0` so a missing credential fails instead of hanging; userinfo is stripped from every event, error and argv; the clone is atomic (temp dir + rename) so a killed clone never leaves a half-repository that a later run would trust | [measured] `tests/test_git_clone.py`, `tests/test_worker_clone.py`, `tests/test_server_routes_w3b.py` |
| `builder_config` cannot carry identity or secrets | `POST /runs` refuses `model` / `provider` / `name` (the rung is the recorded identity; an override would make the ledger row lie) and credential-shaped keys (`*api_key*`, `*token*`, `*secret*`, `*password*` …): provider keys come from the worker's environment, never from a persisted, served request body | [measured] `tests/test_server_routes_w3b.py` |
| The builder's self-report is untrusted | `BuildOutcome.summary` is labelled `trusted: False`; only the grader decides | [design, enforced by construction] |

#### 3.2.1 The builder in a sealed container — `crb.builders.container` (ADR-0012)

Enabled by `CRB_BUILDER__EXECUTOR=docker` on the **worker** (a deployment posture, never a
run parameter — there is no per-run way back to host execution). `/settings` shows the
posture under `builder`; `probe_builder_container()` is the `crb doctor` hook.

| Control | Implementation | Status |
|---|---|---|
| **Gold-commit exfiltration closed by construction** | The builder edits a `SealedCheckout`: `git archive <parent>` → fresh `git init` (inert config: no host config, hooks, signing or templates) → one commit. One tree object is serialised and nothing else, so the object store holds the parent tree and the overlaid tests only; `git cat-file -e <gold>` fails, and so does it for the gold blob of the answer file. `export-ignore`/`export-subst` are undone from the parent's own blobs so the tree is exact. The archaeology guard and the CLI deny rules stay on, as belt-and-braces | [measured] `tests/test_builders_container.py` (one reachable commit; gold commit and blob absent; own `.git` directory, no alternates, no remote; tree byte-equal to the parent) |
| Result reaches the grader; nothing else does | `copy_back` transfers modified / added / deleted **regular files** into the real worktree; a symlink on either side, a `.git` component, a directory, or a path resolving outside the worktree is refused and reported; byte-identical files untouched; a tampered test IS transferred so belt 1 sees it. Grading is the unchanged host-side grader in its own sandbox | [measured] |
| Hardened builder container | `deploy/Dockerfile.builder` (toolchain base + git + the pinned Claude Code native binary). `docker run --init --read-only --cap-drop=ALL --security-opt no-new-privileges --pids-limit --memory --cpus --tmpfs /tmp --user <worker uid:gid>` (root refused); the sealed checkout is the only rw mount (`/work`); `--stop-timeout` = the wall clock. Argv asserted flag by flag | [measured] `builder_run_args` tests; `tests/test_builders_container_docker.py` proves read-only root, non-root uid, no host path visible, the builder's own test run inside |
| **Egress allowlist** | Per attempt: an `--internal` bridge (no gateway, no external DNS) shared by the builder and ONE sidecar running `crb/builders/egress_proxy.py` — standard-library, **CONNECT-only** (plain HTTP → `405`), exact host match + port (`api.anthropic.com:443` by default; `host[:port]` entries; no wildcards) → else `403` and a `deny host:port` log line; the sidecar alone is dual-homed onto the operator's egress network. `HTTPS_PROXY=http://proxy:3128` in the builder. Empty allowlist ⇒ `--network=none`, no sidecar. Bypassing the proxy is impossible by topology, not by rule | [measured] in-process proxy policy tests; docker test: mock endpoint reachable through the proxy, `example.com` `403`, direct sockets fail (no route / no DNS); network-marked test: TLS end to end to the real endpoint, zero spend |
| **Token exposure surface** | Secret-named variables (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*`) are passed as `--env NAME` and resolved from the docker **client's** environment — never on a `docker run` argv (not in `ps`, not in the daemon's event log), never written to a file inside the container (`HOME=/tmp` is a tmpfs that dies with it, `--no-session-persistence` still applies). The surface is: the worker process, the docker client process for the attempt's duration, the daemon, and the container's own environment. Source order unchanged (§3.3.1) | [measured] argv tests assert the value is absent; the docker test reads `key=present` from inside and re-asserts the argv |
| Fail closed | No daemon / builder image or sidecar image absent from the store / sidecar without `READY` in 30 s / network create fails / launch failure / spawn outside the sealed checkout ⇒ `SandboxUnavailable`; the run **stops** (`stopped_reason: sandbox unavailable: …`), no attempt runs on the host, no verdict is written. Sidecar and network are removed even on a failed start | [measured] host tests with a fake session; docker tests with a missing image and a python-less sidecar image |
| Cancel / wall clock | `DockerStream` (core) kills the **container** (`docker kill <name>`) on the run's cancel token or the budget's wall clock, then the client | [measured] docker tests: `cancelled` / `timed_out`, container gone |
| Per builder | `claude_code`: the CLI itself runs in the container through the unchanged spawn contract; `openai_agent`: trusted loop stays host-side, the model's commands run in the builder image with `--network=none` over the sealed checkout; `editblock`: sealed checkout only; `fixture_gold` (test-only): unsealed by design | [measured] |

**Residual risk (container mode):** container escape via the kernel (as §3.1); the
`--internal` bridge still has the host's bridge interface on its subnet — a daemon bound to
TCP, or any service listening on all host interfaces, would be reachable from the builder
(keep the daemon on its socket; bind host services to specific interfaces). The sidecar's
allowlist is exact-host, so a compromised builder can still talk to the model endpoint —
that is the intended channel, and spend is bounded by the budget.

**Residual risk (host mode, `CRB_BUILDER__EXECUTOR=host`, the default for development
only — `CRB_ENV=dev`):** the builder runs in a host worktree that shares the main clone's object
store (the gold commit is reachable, and only the guards stand in the way) with the
worker's privileges and egress. Run the worker as a dedicated low-privilege user on a
dedicated node with an egress policy allowing only the model endpoint (Helm ships a
default-deny `NetworkPolicy`); do not onboard repositories you would not run locally; and
use container mode for any measurement that will be relied on. With `CRB_ENV=prod` the
API and the worker refuse to start in host mode unless `CRB_ALLOW_UNSEALED_PROD=1`, and a run
made under that override carries it in its apparatus (§5, ADR-0023).

### 3.3 Credentials

- Provider keys are read from environment variables only (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `CEREBRAS_API_KEY`). They are never persisted to the
  database, never written to evidence packs or events, and `/settings` reports only
  *whether* each is configured (`crb.server.settings.Settings.redacted_dict`). [measured]
- Git delivery credentials (forward mode) come from an injected provider; the default
  `NullProvider` fails closed. [measured] `tests/test_factory_delivery.py`
- The delivery **push** carries its one-shot `Authorization` header in the child's
  environment (`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n`,
  `crb.core.git.git_config_env`), never on the argv; until 2026-09-25 it was a
  `-c http.<remote>.extraheader=…` argument, readable in `/proc` and `ps` (assessment D1). A
  `GitError` redacts every `extraheader` value and every credential shape from the argv and
  stderr it keeps, whoever built the command line. [measured, n = 3 cases: the push argv
  carries no header and the environment does, a `GitError` built from a header-bearing argv
  carries no token, a push that times out raises a `GitError` with no token —
  `tests/test_factory_delivery.py::test_the_push_token_travels_in_the_environment_never_on_the_argv`,
  `::test_a_git_error_never_carries_an_auth_header_or_a_token`,
  `::test_a_push_that_times_out_raises_a_git_error_without_the_token`; recording git doubles
  and a hanging git binary, apparatus 2.2]
- Repositories connected through the **GitHub App** (ADR-0014) are cloned — and, where the
  installation grants write, delivered to — with **installation tokens** the worker mints per
  use: scoped to the installation (one hour by GitHub's contract), cached in memory until
  five minutes before the expiry GitHub returned, passed to git through `GIT_CONFIG_COUNT` as
  a one-shot `Authorization` header — never argv, never `.git/config`, never a row, event,
  log or API response. [measured, n = 3 cases: mint on first use, re-use inside the hour,
  re-mint inside the five-minute margin — `tests/test_server_github_app.py::test_installation_tokens_are_minted_with_the_jwt_cached_and_refreshed_near_expiry`;
  n = 1 clone: the header reaches git through `GIT_CONFIG_*` and is absent from argv —
  `::test_worker_clones_with_the_installation_token_in_the_environment_never_argv`; fake
  GitHub transport, apparatus 2.2]. The token is sent only to the app's own GitHub host — a
  repository whose URL is edited to another host loses its link [measured, n = 1 URL change,
  `::test_picker_lists_with_suggestions_and_connect_registers_a_linked_repo`, apparatus 2.2]
  and gets no token [measured, n = 3 URLs: the app's host → header, another host → none,
  plain http → none — `::test_worker_clones_…`, apparatus 2.2]. Delivery credentials exist
  only while the installation grants `contents: write` **and** `pull_requests: write`, read
  from GitHub at the time [measured, n = 2 installations: 77 read-only → none, 78 read-write
  → a provider, plus 1 off-host remote → none — `::test_worker_clones_…`, apparatus 2.2].
  The setup callback records an installation only with a signed `state` bound to the
  operator and to the browser that fetched the install link (a nonce in an httponly cookie,
  consumed by the write — CWE-352); otherwise the operator records it through the
  CSRF-protected sync [measured, n = 7 callbacks: no state, a forged state, another
  principal's state, the right state without the cookie, with another link's cookie, the
  genuine one (written), and a replay after the write — six land unverified with nothing
  written, one writes — `::test_setup_callback_verifies_records_and_lands_on_connect`,
  apparatus 2.2]. The app's private
  key comes from the environment or a mounted file; `/settings` reports only
  `private_key_configured`. [measured] `tests/test_server_github_app.py`
- Every string that leaves a sandbox — test output tails, diffs, transcripts, log lines,
  event payloads — passes through `crb.core.redact` (bearer/basic headers, well-known key
  prefixes, JWTs, `key=value` secrets, URL userinfo, private-key blocks). [measured]
  `tests/test_redact.py`
- Session cookies are signed (`itsdangerous`), `HttpOnly`, `SameSite=Lax`, `Secure` outside
  `CRB_ENV=dev`; the secret key is mandatory in production. Whenever cookies are `Secure`
  they are named `__Host-crb_session` / `__Host-crb_csrf`: the browser accepts such a
  cookie only from a secure response with `Path=/` and no `Domain`, so a sibling host
  cannot plant or shadow one (a plain-named cookie is ignored). CSRF is **bound to the
  session**: every unsafe method must carry `X-CSRF-Token` equal to
  `HMAC(secret, user id, credential version)`, which the middleware recomputes from the
  signed session cookie — a cookie/header pair chosen by whoever can set cookies is
  refused, and the token ends with its session. The middleware and the authentication
  check read the session cookie through one function over the same lenient parser, so a
  malformed neighbour cookie (a space, JSON, a consent banner's date) cannot hide the
  session from the CSRF check while the request still authenticates. [measured]
  `tests/test_server_auth.py::TestCsrfBoundToSession`,
  `tests/test_server_auth.py::TestCsrfSeesTheSameCookiesAsAuth`
- **Sessions end on a password change, on logout, on "sign out everywhere" and on
  deactivation.** The cookie carries the credential version it was issued under (a
  fingerprint of the account's argon2 hash and its `session_nonce`); setting a password
  re-salts the hash, and logout (`POST /auth/logout`) or an admin's sign-out-everywhere
  (`POST /users/{id}/sessions/revoke`, which works for an OIDC account too) rotates the
  nonce, so every session of that account — on every device, since the nonce is per
  account — answers `401 session_revoked` on its next request; no server-side session
  table to keep or leak. A copied cookie therefore dies with the logout, not at
  `session_ttl`. [measured] `tests/test_server_auth.py::TestSessionRevocation`
  A deactivated account is refused on its very next request and for as long as it
  is inactive; the active flag is not part of the version, so re-activating within
  `session_ttl` restores the sessions issued before — containing a compromised account
  means deactivating **and** signing it out everywhere (or setting a new password). A self-service change
  (`PUT /users/me/password`) requires the current password — a borrowed session cannot
  change it — and re-issues the cookie only to the browser that made the change. The
  break-glass path (`crb users set-password | deactivate` on the host, where database
  access is the credential) goes through the same primitives and writes the same
  `user.*` events with actor `cli:<os user>`; a password never enters an event, a log
  line, stdout or argv (prompt or `CRB_USERS_PASSWORD_FILE`). The last active admin can
  never be deactivated (`409 last_admin`), by either door. [measured]
  `tests/test_server_admin_users.py`, `tests/test_cli_users.py`

#### 3.3.1 Secrets at rest — `crb.core.secrets_file`, `crb.server.secrets`

The one credential the product will hold for the operator is the Claude Code login
token (`claude setup-token`) that a `claude_code` build in `auth: cli` mode forwards to
the CLI as `CLAUDE_CODE_OAUTH_TOKEN`. It exists so the token never has to transit a chat,
a ticket or a shell history again (review 2026-09-13, action #9).

- **Minted on the API host, from the browser.** *Settings → Sign in with your Claude
  account* starts a login session: a detached helper (`crb.server.claude_login_driver`)
  runs `claude setup-token` in a pseudo-terminal on the API host, the browser opens
  Anthropic's sign-in URL in a new tab, the person approves and pastes the code
  Anthropic shows, the helper types it into the CLI and stores the minted token through
  the same owner-only store as the manual path. The browser sees the URL, the session
  state and, at the end, four characters; the pasted code is written once (mode 0600)
  and deleted the moment the helper has typed it; the token is never in a response, an
  event, a log line or the session directory (the helper scrubs token shapes from
  everything it reports). One session per deployment at a time; ten-minute expiry;
  admin only. The CLI runs with an allowlisted environment — `PATH`, `HOME`, `TERM=dumb`,
  `NO_COLOR`, a no-op `BROWSER`, the host's proxy and certificate-authority variables
  (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` in either case, `NODE_EXTRA_CA_CERTS`,
  `SSL_CERT_FILE`, `SSL_CERT_DIR`, so the sign-in works behind a proxy) and a
  `CLAUDE_CONFIG_DIR` created for that sign-in and removed after it — so the secret key, the database URL and the OIDC client secret the
  API process holds never reach it, and it neither reads nor writes the host account's own
  Claude configuration. [measured] `tests/test_server_claude_login.py` (a fake CLI replays
  the real transcript, including a refused code and a token-shaped run in an error line;
  another dumps the environment it was given).

- **Where.** One file per secret under `CRB_SECRETS_DIR` → `$CRB_HOME/secrets` →
  `./.crb/secrets`: `claude_code_oauth_token` (the raw value) and
  `claude_code_oauth_token.meta.json` (`set_at`, `set_by` — never the value). Directory
  `0700`, files `0600`, owned by the API process user. Writes are atomic (`O_EXCL` temp
  file in the same directory, fsync, rename) so a reader sees an old or a new value,
  never a torn one. [measured] `tests/test_server_secrets.py`
- **Owner-only or nothing.** The store refuses to *write* into a directory that has any
  group/other permission bit or a different owner, and refuses to *read* a value file
  with any group/other bit; it never widens or narrows permissions itself — an insecure
  mode is a finding (`crb doctor` reports it `down`, a `cli` build fails closed with
  `model_error: … secrets file refused`, the API answers `409 secrets_insecure`). [measured]
- **Never in the database, never in evidence, never in a log, never in a response.** The
  value enters through `PUT /settings/secrets/claude-code-token` (admin, CSRF) and leaves
  only as an environment variable of the child `claude` process. Every API response —
  the `PUT` included — is a status: `present`, a `fingerprint` of at most the **last four
  characters**, `set_at`, `set_by`. Log lines carry the secret's *name* and that
  fingerprint. `repr()` of the store never includes a value; the redacting log filter and
  `crb.core.redact` (`sk-…` prefixes) are defence in depth behind that. [measured]
  `tests/test_server_routes_admin_secrets.py`, `tests/test_builders_claude_code.py`
- **What is logged.** `secret set` / `secret removed` with `secret`, `fingerprint`,
  `set_by`; `secret unreadable` with the permission reason. The verify probe's stderr
  tail is redacted and capped before it is returned.
- **Verify is metered.** `POST …/verify` runs one no-tool Haiku turn through the
  builder's exact environment and is limited to one call per 10 s per deployment
  (`429 rate_limited` + `Retry-After`), so the button cannot be used to burn quota. It
  stops at the CLI's first `401` retry event (≈2 s) rather than letting the CLI retry
  for ~90 s. [measured]
- **Role split.** Statuses are readable by any signed-in role (they are non-secret by
  construction and an operator needs them to know whether an `auth: cli` run can
  authenticate); the on-host directory path is reported to admins only; store, remove
  and verify are admin-only. [measured]
- **Operator-provided mounts.** `CRB_SECRETS_DIR` may point at a directory the platform
  fills (a Secrets Store CSI / Key Vault mount): a raw value file with no `.meta.json` is
  read like any other; the same owner-only file-mode rule applies, so mount it with a
  `0600`/`0400` file mode for the crb user.
- **Threat: API-host compromise = token compromise.** The token is a long-lived
  subscription credential; anyone who can read the API process's files (or the
  process memory during a verify) can use it. Mitigation is rotation, not encryption at
  rest (a key on the same host adds nothing): run `claude setup-token` again, paste the
  new value (the old file is replaced atomically), and revoke the old token from the
  Anthropic account (`claude auth logout` / the console). Rotation is a two-minute
  procedure in `docs/OPERATOR.md`.
- **Scope.** `auth: cli` is a developer/evaluation mode (see 3.2 and the builder's
  docstring); production runs use `ANTHROPIC_API_KEY` in the worker environment and never
  read the secrets file.

### 3.4 Authentication and authorisation — `crb.server.auth`

- OIDC (Entra ID or any provider): authorisation-code flow with PKCE and a signed state
  cookie; ID-token validation against the provider's JWKS; role from a configurable claim /
  group map; users upserted by `(issuer, subject)`. The claims set an account's role on its
  **first** sign-in only; after that the role is the admin's to change and a sign-in does
  not revert it. `CRB_OIDC__ROLE_FROM_CLAIMS=always` makes the provider the source of truth
  instead (a removal from the admin group then demotes at the next sign-in) and records
  every change it makes as `user.role_overridden` with the role before and after.
  [design — exercised with an injected fake provider in tests; not yet run against a live
  IdP]
- Local accounts (argon2id, constant-time compare) exist for bootstrap and air-gapped
  installs; disable with `CRB_LOCAL_AUTH_ENABLED=false` once OIDC works. Failed sign-ins are
  limited in the API process: five a minute per username and address, and twenty a minute
  per address whatever the usernames (a spray across accounts). The limiter is in memory and
  per process, so **production must also limit `POST /api/v1/auth/login` per client address
  at the reverse proxy**, which sees every replica ([DEPLOYMENT §8](DEPLOYMENT.md#8-go-live-checklist)).
  [measured] `tests/test_server_auth.py::TestLoginRateLimitPerIp`
- Where a registered repository may live: a `clone_path` must resolve inside
  `$CRB_HOME/repos`, where the worker clones. A path elsewhere on the host is an admin's
  decision and is recorded (`repo.clone_path.outside_home`); anyone else — including a model
  through the MCP write tools, which ride the same route — gets `403
  clone_path_outside_home`; a path under that directory that resolves outside it (a symbolic
  link) is refused for every role. The same check runs again where the path is used — the
  worker before it reads a clone, and the profile walk — because a path that did not exist
  at registration can gain a link later (for example from another repository's clone).
  The worker's own clone destination (`$CRB_HOME/repos/<name>`) has a stricter rule, checked
  before any git process starts: it must be exactly that directory, or nothing yet, and never
  a symbolic link — whether the link leads outside the directory or to another repository's
  clone inside it. git is then pointed at the resolved path that was checked;
  `clone_repo` refuses a destination that is a symbolic link; and a structural test holds
  every place that opens a stored clone to the one use-time function
  (`confined_clone_path`), with a second test that fails when a function in `crb.server`
  calls `GitRepo(…)` or `clone_repo(…)`, or starts any process (through `subprocess`, `os`,
  `asyncio` or `pty`), and is not on one of that test's lists, and a third that refuses an
  import of a process starter the second test could not see. These scans resolve an
  imported alias (`from crb.core.git import GitRepo as G`), and each is run on a
  throwaway module that uses every import form, so renaming an import does not hide a call.
  When one name is bound by two imports in a module (a module-level one and one inside a
  function), a scan that looks for git or the link rule counts the call if either import
  makes it one, and the use-site test counts a path as confined only if both are the
  confiner; this can give a false alarm, which renaming the import clears, but never a
  miss. A name bound some other way — an assignment such as `G = GitRepo` — is not
  resolved.
  **[measured — n = 36 tests, all passing on this change (PR #52); method: pytest on the
  node ids below, which include a link at the destination in five shapes (outside the
  directory, to another clone inside it, to an empty directory, dangling, and chained). The
  tests that pin a fix were written before it: 8 of the 9 clone-path tests added first
  failed on `main` at 8ab88ad (the ninth is the control that must pass), and 8 of the 10 destination-shape tests failed on 7d5a619 (the
  other 2, the outside shape, already passed there), and the 3 import-form tests failed on
  ca17168, before the names were resolved, and the 5 colliding-import tests failed on
  e0a6fce, before every import of a name was kept; apparatus 2.2. A count of tests, not a
  rate, so no interval]** `tests/test_server_routes_repos.py::TestClonePathConfinement`,
  `tests/test_worker_clone.py::test_a_clone_path_that_escapes_the_root_at_use_time_fails_the_run`,
  `tests/test_worker_clone.py::test_a_link_at_the_clone_destination_is_refused_before_any_git_command`,
  `tests/test_worker_clone.py::test_every_link_at_the_clone_destination_is_refused_before_any_git_command`,
  `tests/test_worker_clone.py::test_the_destination_rule_is_identity_not_containment`,
  `tests/test_worker_clone.py::test_git_opens_only_the_confined_path_at_every_use_site`,
  `tests/test_worker_clone.py::test_the_use_site_list_is_every_place_the_server_opens_git`,
  `tests/test_worker_clone.py::test_the_server_names_process_starters_only_through_their_module`,
  `tests/test_worker_clone.py::test_the_git_opener_discovery_sees_every_import_form`,
  `tests/test_worker_clone.py::test_the_use_site_ratchet_sees_aliased_openers_and_confiners`,
  `tests/test_worker_clone.py::test_the_link_rule_scan_sees_an_aliased_import`,
  `tests/test_worker_clone.py::test_the_git_opener_discovery_sees_every_binding_of_a_colliding_alias`,
  `tests/test_worker_clone.py::test_the_link_rule_scan_sees_every_binding_of_a_colliding_alias`,
  `tests/test_worker_clone.py::test_the_use_site_ratchet_confines_only_when_every_binding_is_a_confiner`,
  `tests/test_worker_clone.py::test_the_use_site_ratchet_reports_an_opener_called_without_its_path`,
  `tests/test_git_clone.py::test_clone_refuses_a_destination_that_is_a_symbolic_link`,
  `tests/test_mcp_server.py::test_register_repo_tool_is_confined_to_the_repos_root`
- Account lifecycle: an admin sets a password or the active flag (`PUT /users/{id}/password`,
  `PUT /users/{id}/active`); a person changes their own with the current password
  (`PUT /users/me/password`); on the host, `crb users` does the same without a login
  (break-glass — database access is the credential). One implementation behind both
  (`set_password`, `set_user_active`): ≥ 12 characters, argon2id, OIDC accounts refused
  (`not_local`), the last active admin never deactivated (`last_admin`), every change an
  audit event with actor and target, sessions ended by the change (§3.3). [measured]
  `tests/test_server_admin_users.py`, `tests/test_cli_users.py`
- Roles are an ascending ladder `viewer < operator < approver < admin`; every mutating route
  names its minimum role; `/health` and `/metrics` are unauthenticated and must be bound to
  an internal interface. [measured] RBAC matrix in `tests/test_server_app.py`
- **Two-person rule, enforced at write** (`signoff-policy.v3`, F7b, DL-047, ADR-0016):
  `409 signoff_refused` / `same_actor` — the approver is refused when they are the actor of
  the attested row (`Grade.actor`), the actor of the run that produced it (`Run.actor`), or
  the only person behind the cell's accepted evidence — the person who produced the evidence
  can never be the person who signs it. Non-person actors (the worker, `cli:<os user>`,
  `service:…`, the census importer, the empty actor) never count as a second person. The
  clause has no `CRB_SIGNOFF__*` knob and cannot be relaxed (`require_independent_verifier`
  may only be `true`; anything else is `503 signoff_policy_invalid`), the preview shows it
  to the would-be approver before they try, and the record stamps
  `require_independent_verifier: true` so an audit reads that the rule was in force. The
  rule bites exactly when a person is behind the evidence: where a person actor matches
  the approver, or the approver is the only person behind the cell's accepted rows, the
  sign-off is refused — so a deployment in which one account both queues runs and approves
  cannot sign those cells at all, and a separate operator and approver account is the
  precondition for signing evidence people produced. Evidence with no person actor at all
  (the worker's scheduled runs, `cli:` and `service:` actors, the census importer) is not
  judged by this clause (`same_actor_refusal` is silent when no person actor resolves)
  and is guarded by the other clauses only. [measured — n = 15 tests under apparatus 2.2: 7 in
  `tests/test_server_routes_signoffs.py::TestTwoPersonRule` drive `POST /signoffs`,
  `GET /signoffs/preview` and `cell_actors` against a seeded ledger (refused on the attested
  row's run actor; refused on the row's own `Grade.actor` alone, the run unnamed; `cell_actors`
  gathers both halves over accepted rows only; refused as the only person behind the cell; a
  second approver signs the same cell; the seeded operator/approver split signs; the preview
  names the refusal first — the three route tests added after an adversarial mutation pass
  each kill a mutant the first six let live), and 8 in `tests/test_signoff.py` exercise
  `same_actor_refusal` /
  `is_person_actor` in the core (each of the three grounds, non-person actors never
  count, the clause is last and not lifted by a relaxed policy, the ledger write boundary
  refuses, the silent case when no actors were resolved); pass/fail, not a rate]
- **Who signed is on the record** (F34): every sign-off carries `verifier_kind` — `local`
  or `oidc`, stamped from the signing account's issuer under the hash; `service` is reserved
  for a delegated, non-person signature and no write path of this API mints it, so a
  delegated signature can never read as a person's. Rows written before the field carry
  `""`, never a guessed kind. A blank `users.issuer` (no product path writes one) is
  **503 `account_issuer_missing`** on the write, the preview and a revocation — nothing
  written, the account named — never a guessed kind and never a 500. [measured — n = 5
  tests under apparatus 2.2: 3 in
  `tests/test_signoff.py` (a `crb.signoff.v3` record round-trips and hashes with the kind;
  a v2 record with no kind still verifies and serves `""`, and flipping a stored kind to
  `service` breaks its hash; `verifier_kind_for_issuer` maps the local issuer → `local`
  and any other → `oidc`, refusing an empty issuer) and 2 in
  `tests/test_server_routes_signoffs.py::TestVerifierKind` (an identity-provider session
  signs and the served record reads `oidc`; a blanked issuer is 503 on all three routes with
  the signoffs table unchanged); the seed's `local` stamp is also asserted on every write
  and preview in that file; pass/fail, not a rate]

### 3.5 Evidence integrity — `crb.core.ledger`, `crb.store`

- Grade rows, events and sign-offs are **append-only**: database triggers refuse `UPDATE`
  and `DELETE` (SQLite `RAISE(ABORT)`, PostgreSQL trigger function); `/health` proves the
  triggers are live on every call (`assert_append_only`). [measured] `tests/test_store_*.py`
- Every grade row carries `prev_hash` and `row_hash` (SHA-256 over canonical JSON); the chain
  verifies end to end (`crb ledger verify`, `GET /ledger/verify`); an exported JSONL verifies
  standalone without the database. [measured] 1,071-row census: chain verifies; a single
  flipped field is detected (`tests/test_ledger.py`, `tests/test_census_gate.py`)
- The false-Q1 invariant is enforced **at write** in two independent places
  (`GradeResult.__post_init__`, `GradeRow.assert_invariants`) and re-checked at read
  (`/health` SQL count, routing `do_not_ship`). A clean row cannot exist without an
  evidence-pack hash. [measured]
- Evidence packs are content-addressed (`pack_hash`) and re-verified on read. [measured]

### 3.6 Data minimisation — see `docs/DATA-RETENTION.md`

Zero raw retention by default: diffs are stored as hash + line counts, test output is
redacted and capped, builder transcripts are kept only when explicitly enabled and then
subject to a retention window.

### 3.7 Supply chain

- Python dependencies are pinned in `uv.lock`; CI runs `pip-audit --strict` and emits a
  CycloneDX SBOM; `gitleaks` scans every push; Dependabot is enabled for pip and Actions.
- The core engine has **zero** third-party dependencies (enforced by `import-linter`), so the
  grading path's supply-chain surface is the Python standard library and `git`.
- Container images are pinned by tag; the runtime image runs as a non-root user.

## 4. Threats considered

| # | Threat | Where it lands | Control(s) |
|---|---|---|---|
| T1 | A repository's tests exfiltrate data or attack the network | test run | 3.1 no network, read-only, caps |
| T2 | A repository's tests escape the container | test run | 3.1 least privilege + residual risk note |
| T3 | The builder edits or weakens the oracle to go green | build | 3.2 guard + belt 1 disqualification |
| T4 | The builder recovers the real patch from git history | build | 3.2.1 sealed checkout — the commit is **not in the object store** (closed by construction); 3.2 archaeology guard + deny rules remain as belt-and-braces |
| T4a | The builder reaches the upstream repository, a registry, a search engine or a paste of the real diff | build | 3.2.1 egress allowlist: only the model endpoint's host, only through the sidecar, only `CONNECT`; no DNS and no route from the builder itself |
| T4b | A repository's build/test commands, run by the builder, attack the worker host or network | build | 3.2.1 read-only root, `cap-drop=ALL`, non-root, pid/mem/cpu caps, `--internal` network; the sealed checkout is the only writable mount |
| T4c | The model credential leaks via `ps`, the daemon's event log, or a file the builder can read | build | 3.2.1 `--env NAME` from the client's environment (never on argv); tmpfs `HOME`; nothing written by the worker into the container |
| T5 | Prompt injection from repository content steers the builder | build | `--bare` (no repo `CLAUDE.md`/hooks); builder output untrusted; grader decides |
| T6 | A builder loop runs unbounded / burns budget | build | 3.2 budgets |
| T7 | Model credentials leak into a worktree, a pack or a log | everywhere | 3.3 env-only, redaction, never persisted |
| T7a | The stored Claude Code login token is read by another user on the API host, or torn/half-written | secrets file | 3.3.1 owner-only `0700`/`0600`, refuse-on-insecure-mode (write and read), atomic rename; `crb doctor` reports the mode |
| T7b | The stored token leaks through the API, the UI, a log or an evidence pack | API / UI / logs | 3.3.1 status-only responses (≤4-char fingerprint), password field never echoed and cleared on save, log lines carry name + fingerprint, verify output redacted |
| T7c | The verify button is used to burn subscription quota | API | 3.3.1 one probe per 10 s per deployment, one no-tool Haiku turn, admin-only |
| T7d | API-host compromise | secrets file | token compromise: rotate (`claude setup-token`, paste, revoke the old one) — see 3.3.1 |
| T7e | The `claude setup-token` CLI reads the API's own secrets from its environment | API host | 3.3.1 allowlisted environment and a throwaway `CLAUDE_CONFIG_DIR` |
| T8 | An insider edits a past verdict | ledger | 3.5 triggers + hash chain + `/health` proof |
| T9 | A false pass is recorded because a runner could not attribute a failure | grade | fail-closed parse rule (`unattributed failure` ⇒ belt 3 false), harness errors ⇒ not clean |
| T10 | A green with no real change is credited (build-cache ghost) | grade | belt 4 `source_changed` |
| T11 | Session hijack / CSRF / privilege escalation | API | 3.3 `__Host-` cookies, session-bound CSRF, revocable sessions (logout, sign out everywhere), 3.4 RBAC, first-login OIDC roles |
| T11a | Online password guessing, one account or sprayed across many | API | 3.4 per-(username, address) and per-address limits in the process; the proxy's limiter in production |
| T11b | An operator, or a model through the MCP tools, points the deployment at an arbitrary host directory | API host | 3.4 `clone_path` confined to `$CRB_HOME/repos`; elsewhere admin-only and recorded; symbolic-link escapes refused |
| T12 | Cross-organisation data leakage via the federated export | export | allowlist of abstract fields only, k-anonymity, opt-in; consumption not implemented (`crb.core.federated`) |
| T13 | A weak oracle lets a semantically wrong patch pass | grade | not a mechanical false-Q1; measured and gated by oracle strength (`crb.core.oracle`), routed to `human` below 0.8 |
| T14 | A dependency fetch runs untrusted code with a network (an install script, a source build) | provision | 3.1.1: wheels only, `npm ci --ignore-scripts`, `go mod download`; anything that must build runs in a second container with `--network=none`; a Python source distribution is refused |
| T15 | A builder steers a fetch, or a repository injects fetch configuration (`.npmrc`, `pip.conf`, `go.env`, an index line) | provision | 3.1.1: inputs from git objects at the parent and the gold only, never a worktree; configuration files never read; Python's lock rewritten from the parsed pins; the argv, environment and allowlist are the recipe's, never a `RepoConfig`'s or a run request's |
| T16 | Exfiltration or metadata disclosure through module paths or a fetch's requests | provision | 3.1.1: the fetch sees the lockfiles only (no source, no secret, no `CRB_HOME`); the proxy admits the configured registry hosts only; production points at the tenant's mirror; a private module behind a public proxy is refused before any request (`PROVISION_PRIVATE_MODULE`); at grade time the closure selector reads nothing outside the builder's tree — a linked manifest or a local `replace` that leaves the tree is a closure violation, so no file outside it is read or quoted (`tests/test_provision.py::test_a_trial_never_makes_the_selector_read_outside_its_tree`) |
| T17 | A substituted artifact (a registry or mirror serves different bytes) | provision | 3.1.1 integrity: `go.sum` + the checksum database, npm `integrity`, pip hashes where committed (recorded where not — the residual) |
| T18 | Tampering with or poisoning the store | provision / test run | 3.1.1: sealed read-only with a digest; `validate_mount` at every use; `crb deps verify` → `BUNDLE_INTEGRITY` stops the run; the key includes the fetch image's ID |
| T19 | The fetch's proxy is used as a relay to another host | provision | the proxy is CONNECT-only to an exact host:port allowlist (`crb.builders.egress_proxy`); denials are logged and named in the refusal |
| T20 | Resource exhaustion by a fetch or by the store | provision | memory / cpu / pid caps on the fetch; `MAX_BUNDLE_MB` watchdog; fetch wall clock; `MAX_TOTAL_GB` and `crb deps gc`; the throwaway tree capped at `work_size` |
| T21 | Answer leakage through the builder's dependency set (the gold's module list is part of the answer) | build | 3.1.1 / ADR-0012 amendment: a sealed builder may be given the **parent's** set, never the gold's; the trial is graded with the set its own manifests select, and one outside the closure is disqualified |

## 5. What this document does not claim

- No penetration test has been performed on v2.0. [gap]
- The OIDC flow has not been exercised against a live identity provider. [gap]
- Container mode for the builder (3.2.1) is proven with a scripted builder and a mock
  endpoint plus a zero-spend TLS probe to the real endpoint; a full `claude -p` build
  through the sidecar with a live credential has not yet been run in CI (it needs a
  credential and spend). [gap — measured on the fake-model path only]
- **Production refuses the unsealed posture** (ADR-0023). With `CRB_ENV=prod` the builder
  defaults to its sealed container (`CRB_BUILDER__EXECUTOR=docker`), and the API and the
  worker both refuse to start with `CRB_BUILDER__EXECUTOR=host` or
  `CRB_SANDBOX__EXECUTOR=local` unless `CRB_ALLOW_UNSEALED_PROD=1` is set. That override is
  the operator's statement that what the deployment measures is a development reading: it is
  shown on `/health`, `/settings` and the Posture page, and stamped into every run's
  apparatus and every evidence pack as `unsealed_prod_override`, so a row produced under it
  can always be told apart. `CRB_ENV=dev` keeps the host defaults. The refusal proves a
  setting, not a measurement: no row has yet been produced on the sealed posture (below).
  [measured — `tests/test_settings_posture.py` and `tests/test_worker.py` pin the refusal,
  the override and the stamp; apparatus 2.2]
- **Factory builds are not sealed** (ADR-0023 §5). The builder executor setting governs
  replay builds; a factory run hands its builder a host worktree and no container. A `prod`
  worker therefore refuses every factory run unless `CRB_ALLOW_UNSEALED_PROD=1`, and with it
  stamps the run's apparatus (`run_kind: factory`); `/health` reports this as
  `posture.factory_builds`. [measured — `tests/test_worker.py`,
  `tests/test_settings_posture.py::TestFactoryBuilds`] Sealing factory builds is not done.
  [gap — factory builds run on the host]
- **One builder posture for both processes.** Compose and Helm hand the API (which serves
  `/health`) and the worker (which runs the builds) the same `CRB_BUILDER__EXECUTOR`.
  [measured — `tests/test_settings_posture.py::TestHelmOneBuilderPosture` renders the chart]
- **Worktree names carry nothing of the commit** (DL-055). Trial, mining, control and oracle
  worktrees are named by a random token, and the mapping to the task is on the run's events,
  so `pwd`, `basename`, the `.git` pointer and the prompt no longer hand the builder a prefix
  of the held-out sha. On the host posture the builder can still read anything the worker
  user can read, including the main clone's history, which is why production refuses it.
  [measured — `tests/test_run.py`, `tests/test_builders_guard_corpus.py` scan with the
  fixture's real sha; apparatus 2.2]
- Reference sandbox images ship and are proven in CI (3.1) **[measured — n = 42 tests passed,
  0 skipped, across `tests/test_sandbox_images_docker.py` (3 images) and
  `tests/test_sandbox_docker.py`; method: a local run on colima, Docker 29.5.2, 2026-09-25;
  apparatus 2.2]**. Every *verdict* to date is on the host executor posture. The first replay
  in the docker posture (run `0c44ff24…`, cobra) graded its rows `builder_red` because the
  sealed container could not load cobra's modules — an instrument failure charged to the
  model **[measured — n = 3 or 4 rows, each `builder_red` with the target red; method: the
  run's grade rows as read on 2026-09-25; apparatus 2.2. The count is disputed: 3 rows were
  observed when the run was cancelled (the session's findings note), and stream D read 4 from
  the deployment's ledger export, which is not committed — [gap] F42, settled only by the
  stack's ledger]**. Dependency
  provisioning and the throwaway tree (3.1, 3.1.1) now let the sealed posture run a Go, a
  Python and a Node fixture with dependencies offline **[measured — n = 3 fixture
  repositories, one per language, each parent and gold tree passing offline in the shipped
  image against its sealed set; method: `tests/test_provision_{go,python,node}.py` against a
  real daemon on colima, 2026-09-25; apparatus 2.2]**. The apparatus 2.3 read rule of ADR-0019
  is in force: a docker row stamped before 2.3, such as each row of run `0c44ff24…`, is left
  out of every rate and counted `unqualified_posture` **[measured — the DoD criterion
  results.truth.17, `tests/test_server_routes_capability.py::test_pre_2_3_docker_rows_are_excluded_and_counted`;
  apparatus 2.3]**. No real repository has yet been qualified in the sealed posture on a live
  stack **[gap — F42]**.
- Container escape is out of scope for the application layer.

Report a vulnerability to the repository owner privately; do not open a public issue.
