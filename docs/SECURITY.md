# Security and threat model

_Audience: the security reviewer of an organisation self-hosting Commit Replay Bench (crb).
Every control below names the code that implements it. Statements about behaviour are
**[measured]** where a test in this repository proves them, **[design]** where they are
architectural commitments not yet covered by an end-to-end test._

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
│        └──▶ Builder attempt       [worktree; egress = model endpoint]│
│                                                                      │
│  Model endpoint (Azure OpenAI in-tenant / configured provider)  ◀────┘
└──────────────────────────────────────────────────────────────────────┘
```

Nothing crosses the tenant boundary except calls to the model endpoint the operator
configures. There is no telemetry, no update check, no licence phone-home.

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

**Residual risk:** in v2.0 the builder runs in a host worktree (not a container) with egress
to the model endpoint. The agentic adapters can execute repository build/test commands. A
malicious repository can therefore run code with the worker's privileges during a build
attempt. Mitigations now: run the worker as a dedicated low-privilege user on a dedicated
node with an egress policy allowing only the model endpoint (Helm chart ships a default-deny
`NetworkPolicy`); do not onboard repositories you would not run locally. Planned (phase P5):
the builder attempt inside the same hardened container with the model endpoint as the only
egress.

### 3.3 Credentials

- Provider keys are read from environment variables only (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `CEREBRAS_API_KEY`). They are never persisted to the
  database, never written to evidence packs or events, and `/settings` reports only
  *whether* each is configured (`crb.server.settings.Settings.redacted_dict`). [measured]
- Git delivery credentials (forward mode) come from an injected provider; the default
  `NullProvider` fails closed. [measured] `tests/test_factory_delivery.py`
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
| T4 | The builder recovers the real patch from git history | build | 3.2 archaeology guard + deny rules |
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
- The builder is not yet containerised (see 3.2 residual risk). [gap — phase P5]
- Container escape is out of scope for the application layer.

Report a vulnerability to the repository owner privately; do not open a public issue.
