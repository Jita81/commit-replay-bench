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

There is no telemetry, no update check, no licence phone-home, and the opt-in federated
export (ADR-0007) is a file the operator produces, never a call the product makes. With the
builder in its container (ADR-0012) the model endpoint is reachable from exactly one
process — the egress sidecar — and only for the hosts on the allowlist.

## 3. Controls

### 3.1 Sandboxed test execution — `crb.core.execution.DockerExecutor`

| Control | Implementation | Status |
|---|---|---|
| No network | `--network=none` on every test run; only an explicit dependency-install phase may request `--network=bridge`, and it still carries every other cap | [measured] `tests/test_execution.py` asserts the argv flag-by-flag |
| Immutable root + worktree | `--read-only`, worktree bind-mounted `readonly`; writable scratch only at declared paths (`target/`, `.pytest_scratch`) and tmpfs `/tmp` with `nosuid,nodev` | [measured] |
| Least privilege | `--cap-drop=ALL`, `--security-opt no-new-privileges`, non-root `--user=65534:65534` (root refused at construction) | [measured] |
| Resource caps | `--memory`, `--cpus`, `--pids-limit`, `--stop-timeout`; wall-clock timeout returns `rc=124` and is graded as a failure, never a pass | [measured] |
| Fail closed | No docker binary, unreachable daemon, root user, docker-socket or `$HOME` mount request, or a launch failure (exit 125) raise `SandboxUnavailable`; the **run stops** and is recorded `failed`. The product never degrades to in-process execution when the sandbox was requested | [measured] `tests/test_execution.py`, `tests/test_sandbox_docker.py` (skipped without a daemon) |
| Host environment isolation | `LocalExecutor` (development only) passes through an explicit allowlist of variables (`PATH`, toolchain caches); operator secrets are proven absent inside the child | [measured] `test_execution.py::…env…` |

**Residual risk:** container escape via the kernel. Mitigation is the standard one — keep the
container runtime patched; run the worker on a dedicated node; consider gVisor/Kata for
hostile repositories. This is documented, not implemented.

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

**Residual risk (host mode, `CRB_BUILDER__EXECUTOR=host`, the default for development and
evaluation):** the builder runs in a host worktree that shares the main clone's object
store (the gold commit is reachable, and only the guards stand in the way) with the
worker's privileges and egress. Run the worker as a dedicated low-privilege user on a
dedicated node with an egress policy allowing only the model endpoint (Helm ships a
default-deny `NetworkPolicy`); do not onboard repositories you would not run locally; and
use container mode for any measurement that will be relied on. The API logs a warning
when `CRB_ENV=prod` and the builder executor is `host`.

### 3.3 Credentials

- Provider keys are read from environment variables only (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `CEREBRAS_API_KEY`). They are never persisted to the
  database, never written to evidence packs or events, and `/settings` reports only
  *whether* each is configured (`crb.server.settings.Settings.redacted_dict`). [measured]
- Git delivery credentials (forward mode) come from an injected provider; the default
  `NullProvider` fails closed. [measured] `tests/test_factory_delivery.py`
- Repositories connected through the **GitHub App** (ADR-0014) are cloned — and, where the
  installation grants write, delivered to — with **installation tokens** the worker mints per
  use: scoped to the installation (one hour by GitHub's contract), cached in memory until
  five minutes before the expiry GitHub returned, passed to git through `GIT_CONFIG_COUNT` as
  a one-shot `Authorization` header — never argv, never `.git/config`, never a row, event,
  log or API response. [measured] `tests/test_server_github_app.py` (fake GitHub transport,
  apparatus 2.2). The token is sent only to the app's own GitHub host — a repository whose
  URL is edited to another host loses its link and gets no token [measured] the same file;
  delivery credentials exist only while the installation grants `contents: write` **and**
  `pull_requests: write`, read from GitHub at the time [measured]; the setup callback records
  an installation only with a signed, session-bound `state` this deployment minted (CWE-352),
  otherwise the operator records it through the CSRF-protected sync [measured]. The app's private
  key comes from the environment or a mounted file; `/settings` reports only
  `private_key_configured`. [measured] `tests/test_server_github_app.py`
- Every string that leaves a sandbox — test output tails, diffs, transcripts, log lines,
  event payloads — passes through `crb.core.redact` (bearer/basic headers, well-known key
  prefixes, JWTs, `key=value` secrets, URL userinfo, private-key blocks). [measured]
  `tests/test_redact.py`
- Session cookies are signed (`itsdangerous`), `HttpOnly`, `SameSite=Lax`, `Secure` outside
  `CRB_ENV=dev`; the secret key is mandatory in production. CSRF is double-submit
  (`crb_csrf` cookie + `X-CSRF-Token` header) on every unsafe method. [measured]
  `tests/test_server_auth.py`

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
  admin only. [measured] `tests/test_server_claude_login.py` (a fake CLI replays the real
  transcript, including a refused code and a token-shaped run in an error line).

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
  group map; users upserted by `(issuer, subject)`. [design — exercised with an injected fake
  provider in tests; not yet run against a live IdP]
- Local accounts (argon2id, constant-time compare, per-user+IP rate limit) exist for
  bootstrap and air-gapped installs; disable with `CRB_LOCAL_AUTH_ENABLED=false` once OIDC
  works. [measured]
- Roles are an ascending ladder `viewer < operator < approver < admin`; every mutating route
  names its minimum role; `/health` and `/metrics` are unauthenticated and must be bound to
  an internal interface. [measured] RBAC matrix in `tests/test_server_app.py`

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
| T8 | An insider edits a past verdict | ledger | 3.5 triggers + hash chain + `/health` proof |
| T9 | A false pass is recorded because a runner could not attribute a failure | grade | fail-closed parse rule (`unattributed failure` ⇒ belt 3 false), harness errors ⇒ not clean |
| T10 | A green with no real change is credited (build-cache ghost) | grade | belt 4 `source_changed` |
| T11 | Session hijack / CSRF / privilege escalation | API | 3.3 cookies, CSRF, 3.4 RBAC |
| T12 | Cross-organisation data leakage via the federated export | export | allowlist of abstract fields only, k-anonymity, opt-in; consumption not implemented (`crb.core.federated`) |
| T13 | A weak oracle lets a semantically wrong patch pass | grade | not a mechanical false-Q1; measured and gated by oracle strength (`crb.core.oracle`), routed to `human` below 0.8 |

## 5. What this document does not claim

- No penetration test has been performed on v2.0. [gap]
- The OIDC flow has not been exercised against a live identity provider. [gap]
- Container mode for the builder (3.2.1) is proven with a scripted builder and a mock
  endpoint plus a zero-spend TLS probe to the real endpoint; a full `claude -p` build
  through the sidecar with a live credential has not yet been run in CI (it needs a
  credential and spend). Host mode remains the default until an operator sets
  `CRB_BUILDER__EXECUTOR=docker`. [gap — measured on the fake-model path only]
- Container escape is out of scope for the application layer.

Report a vulnerability to the repository owner privately; do not open a public issue.
