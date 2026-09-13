# Operator guide (skeleton)

*For the person who installs, configures and runs `crb` inside an organisation's tenant.*
This is a skeleton for phases P1–P2; the full runbook (deployment, DPIA support, air-gap
guidance, incident procedures) lands in P7. Where a command or screen is not yet built, it
is marked with the phase that delivers it.

Read alongside: [README](../README.md) · [ARCHITECTURE](ARCHITECTURE.md) ·
[EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) · [ADR-0005 (sandbox)](adr/0005-fail-closed-docker-sandbox.md).

Contents: [1 Install](#1-install) · [2 Configure a repository](#2-configure-a-repository) ·
[3 Run a sweep](#3-run-a-sweep) · [4 Read the capability map](#4-read-the-capability-map) ·
[5 Sign off](#5-sign-off-p4) · [6 Export the ledger](#6-export-and-verify-the-ledger) ·
[7 When the sandbox is unavailable](#7-when-the-sandbox-is-unavailable) · [8 Stop conditions](#8-stop-conditions)

---

## 1. Install

Requirements: Python ≥ 3.12, `git`, a Docker daemon reachable by the user running `crb`
(for the sandboxed executor — the default), and network access **only** to the model
endpoint you configure.

```bash
uv venv .venv --python 3.12
uv pip install -e '.[dev]' --python .venv/bin/python        # CLI + core
# builder extras as needed: '.[openai]' (Azure OpenAI / Cerebras / local), '.[claude]'
```

Model credentials are read from the environment (or the vault integration in P4); they are
never written to configuration files, evidence packs or logs. `crb` redacts common secret
shapes from every stored string as defence in depth, but do not put live secrets in
repositories under measurement.

Server, worker and UI (`crb serve`, `crb worker`) land in P4–P5.

## 2. Configure a repository

A repository is described by a `RepoConfig` (see `crb.core.spec`): language, runner,
source/test layout, regression belt scope, a known-green probe scope, runner options, the
sandbox image, and mining limits.

```bash
crb repo add myrepo \
  --path /srv/repos/myrepo \
  --language python --runner pytest \
  --src-prefix src/ --test-prefix tests/ \
  --belt-scope AFFECTED_DIRS \
  --probe tests/test_smoke.py \
  --sandbox-image ghcr.io/example/myrepo-toolchain:2026-09
crb repo setup myrepo        # the ONLY network phase: install the test dependencies
crb repo probe myrepo        # runs setup itself first if the environment is not ready
```

Or let crb clone a public/upstream repository for you (full history, `--no-tags`, into
`<workdir>/repos/<name>`; `https://` and `ssh://` sources only — a local path is registered
with `--path`, never cloned):

```bash
crb repo add httpx --url https://github.com/encode/httpx.git \
  --language python --src-prefix httpx/ --test-prefix tests/ --probe tests/models/test_queryparams.py
```

The same happens in the UI ("Add a repository" → Git URL) and the API (`POST /repos` with
`url` and no `clone_path`): the worker clones on the repository's first run and records
`repo.clone.start` / `repo.clone.done` on that run's trace. Presets in the dialog
(python-src-layout, python-flat, go, node-test, vitest, jest, mocha, maven, cargo) fill the
layout, belt scope and runner options for well-known shapes; the probe scope is always yours.
`CRB_ALLOW_LOCAL_CLONE=1` additionally permits `file://` sources on a test or developer
machine — never on a server.

`crb repo probe` runs the probe scope and must be green before mining; it proves the
toolchain and the dependencies are in place. Belt scope options:

| `belt_scope` | Regression belt runs… |
|---|---|
| `TARGET_ONLY` | only the target tests (weakest; use for very large suites while calibrating) |
| `AFFECTED_DIRS` | every test in the target tests' directories |
| `BARE` | the runner's default discovery (whole suite) |
| explicit list | the named runner scopes |

The census `configs.json` shape is accepted unchanged by `RepoConfig.from_dict`.

### 2.1 Environment setup — the only network phase

Everything `crb` measures runs **offline**: mining, grading, oracle scoring and the
negative controls all execute with the network denied (in the sandbox) or with the
toolchain told to resolve from its local cache. The one exception is **setup**, which
installs the repository's test dependencies once, up front, and records every command it
ran. Nothing else ever asks for the network; if a run needs something setup did not
install, it fails — it does not fetch.

`crb repo setup <name>` (CLI) and the `setup` run kind (`POST /runs {"kind": "setup"}` —
server) call the same runner method. Per language:

| Runner | What setup runs (in the clone) | Where the environment lives | "Ready" means |
|---|---|---|---|
| `pytest` | `uv venv` (or `python -m venv`), then `pip install` of `runner_opts.pip` (falling back to `pip_fallback`), then `pip uninstall` of `runner_opts.uninstall` | `<env>/venv` under `<workdir>/envs/<name>` (CLI) or `<home>/envs/<name>` (worker) | the configured interpreter imports `pytest` |
| `node` / `jest` / `vitest` / `mocha` | `npm ci` when `package-lock.json` is committed, else `npm install` (both `--no-audit --no-fund`) | `node_modules` **in the clone** (every worktree symlinks it) | `node_modules/.bin` exists, or `package.json` declares no dependencies |
| `go` | `go mod download` | the host module cache (`$GOMODCACHE`) | `go list ./...` resolves with `GOPROXY=off` |
| `maven` | `mvn -q -B <maven_flags> test -DskipTests` (compiler, resources, surefire and dependencies in one warm-up) | the local repository (`~/.m2`) | the same goal succeeds offline (`-o`) |
| `cargo` | `cargo fetch` | the registry cache (`$CARGO_HOME`) | `cargo metadata --offline` resolves the graph |

Python runner options (`--runner-opt KEY=VALUE` on `repo add`, or the census keys):

* `pip` — the pip arguments of the primary install, as a list (`["django", "pytest", "-r",
  "requirements/test.txt"]`; a single string is split on whitespace). Without it, setup
  does an editable install of the repository with its test extra — `[test]`, `[tests]`,
  `[dev]` or `[testing]`, whichever `pyproject.toml` actually declares (installers exit 0 on
  an unknown extra, so nothing is guessed) — falling back to a plain `-e .`, then installs
  `pytest`.
* `pip_fallback` — a second pip argument list, tried only when the primary fails (the
  typical shape: the same packages without a pinned requirements file).
* `uninstall` — distributions to remove after the install: the repository's **own**
  package. The tests must import the worktree's source through `PYTHONPATH`, never a
  wheel built from the clone at `HEAD`; this is the census invariant and setup enforces
  it.
* `python` — an interpreter you manage yourself. When set, setup never installs into it:
  it only verifies that it imports `pytest` (and refuses otherwise). Unset it to let setup
  build the venv.
* `setup_timeout` — per-step wall clock in seconds (default 1800; `--timeout` overrides).

What you get back is a `SetupResult`: `ok`, one record per step (`argv`, `rc`, a redacted
output tail, duration), a `note` naming the step that stopped the phase, and the total
time. `ok` means *ready now* — every decisive step exited 0 **and** the runner's own
readiness probe passed. A primary `pip` list that fails and a `pip_fallback` that succeeds
is `ok` (both steps are kept in the record). The worker stores the result in the run's
`counts_json` and streams `setup.step` events; the CLI prints it (`--json` for the full
record). A failed setup ends the run `failed` with the last step's tail; `repos.probe_status`
is untouched by setup itself.

**Probe runs setup automatically.** When `crb repo probe` (or a `probe` run) finds the
environment not ready it emits `setup.auto`, runs setup, and only then runs the probe
scope; a setup failure fails the probe (`probe_status = failed`, detail = the setup note
and tail). Under the docker executor the readiness question does not apply: the sandbox
image *is* the environment (see below) and setup refuses to run there.

**Offline / air-gapped tenants.** Setup is the only phase that needs a registry, so it is
the one to point at your mirror — or to make unnecessary by pre-seeding the caches. The
executor passes the toolchains a fixed allow-list of variables only (`PATH`, `HOME`, and
the Go / Cargo / Java / Maven / npm cache locations — see `crb.core.execution`); every
other variable, `PIP_INDEX_URL` and `GOPROXY` included, is dropped by design. Configure
mirrors in the tools' own files under the worker's `HOME`, never in `runner_opts`:

* Python — `~/.config/uv/uv.toml` (`index-url`, or `offline = true` with a warm
  `~/.cache/uv`) and `~/.config/pip/pip.conf` for the `python -m venv` path, or a
  wheelhouse named in `runner_opts.pip` (`["--no-index", "--find-links", "/srv/wheels", …]`);
* Node — `registry=` in `~/.npmrc` (add `offline=true` with a warm `~/.npm/_cacache`);
* Go — `go env -w GOPROXY=https://proxy.example GOSUMDB=off` (persisted under
  `~/.config/go/env`), or a pre-populated `GOMODCACHE` — with one, `environment_ready` is
  already true and no setup is needed;
* Maven — a `<mirror>` in `~/.m2/settings.xml`, or a copied local repository;
* Cargo — a `[source]` replacement in `~/.cargo/config.toml` (vendored or a mirror), or a
  warm `$CARGO_HOME`.

Registry credentials likewise live in those files; every step tail is passed through
`crb.core.redact` before it is stored, but keep secrets out of the repository itself.

**Sandbox images** are yours to build: one image per repository (or per toolchain) with
the language runtime, the test runner and the repository's dependencies pre-installed,
runnable as user `65534` with a read-only root. Under docker, setup does not run — the
image must already contain what setup would have installed (the `node_modules` a host
setup installed in the clone is visible to the container through the read-only worktree
mount; a host venv, module cache or `~/.m2` is not). P7 ships reference images.

## 3. Run a sweep

```bash
crb mine  myrepo --pool standard --target 25       # RED-check, baseline, gold-check; writes tasks
crb grade myrepo --builder editblock --mode sighted --budget-usd 5   # P2: editblock; P3: openai_agent, claude_code
crb ledger stats --repo myrepo
```

**Claude Code on a developer machine.** The `claude_code` builder's production mode needs
`ANTHROPIC_API_KEY` on the worker (`claude -p --bare`). For a local evaluation on your own
subscription, start a run with builder config `{"auth": "cli"}` (the run dialog's "Use my
Claude Code login (dev)" toggle) or set `CRB_CLAUDE_CODE_AUTH=cli` on the worker: the CLI
uses the worker user's own `claude login`, no key is forwarded, and the apparatus records
the mode. Read the SECURITY.md row first — the target repository's `CLAUDE.md` is
auto-discovered in this mode. The default model is `claude-sonnet-5` (the census's measured
path; `claude-opus-5` is selectable per run; `CRB_CLAUDE_CODE_MODEL` moves the default).
If a build errors with `authentication failed (HTTP 401) — run claude login`, the stored
login is stale: run `claude login` as the worker's user and re-queue.

What you will see (events; UI live progress in P5): `mine.candidate` → `mine.red` /
`mine.skip` → `mine.gold` → `build.*` → `grade.belt` (four per task) → `ledger.append`.
Skips are normal: a commit whose target is already green at the parent, or times out, is
not a valid oracle and is excluded, not counted.

Every graded task produces an **evidence pack** (redacted; no raw diff, no transcript by
default) and a **ledger row** that carries the pack's hash. A row cannot be `clean` without
a pack.

## 4. Read the capability map

`crb ledger stats` (CLI) and the Capability Map screen (P5) show, per cell
`(class × size × language × builder × model × provider)`:

| Column | Read it as |
|---|---|
| `n` | eligible graded trials — the claim's denominator; `disqualified` and `errors` shown beside it |
| `point` | clean / n |
| `ci_low – ci_high` | Wilson 95% interval — **the** number to quote |
| `false_q1` | must be **0**; anything else is a stop condition (§8) |
| `oracle_strength_mean` | hygiene-adjusted mutant kill-rate (P2) or **not measured** |
| `cost_usd_mean`, `latency_s_mean` | economics per trial |
| `apparatus_versions` | if more than one, the rows are from different instruments and are shown separately |
| `route` + reason | `deliver` / `calibrate` / `granularize` / `human` / `do_not_ship` — see [ADR-0003](adr/0003-one-routing-rule.md) |

Rules of reading: a cell at `n < 10` is `calibrate` whatever its point estimate; a
`deliver` route means "high-confidence candidate under the published bar", not "safe to
automate" — see [EVIDENCE-AND-CLAIMS §6](EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity).
Never quote a point without its interval and its `n`.

## 5. Sign off (P4)

An **approver** signs off a cell for a route in the Sign-off screen (or `POST /api/v1/signoffs`).
The server re-derives the cell's statistics and applies the routing rule:

- any false-Q1 row in the cell → **409 Conflict**, nothing written, event logged;
- requested route stricter than or equal to the rule's decision → **201**, an append-only
  `signoffs` row with actor and timestamp;
- requested route more permissive than the rule → **409** with the rule's reason.

Sign-offs are revoked by a new row, never by deleting one.

## 6. Export and verify the ledger

```bash
crb ledger verify                          # walks the hash chain; exit 1 and the row number on any break
crb ledger export --repo myrepo -o myrepo.jsonl   # P2; chain preserved; legacy rows keep belt_set=v3-legacy
```

For an audit: export, run `crb ledger verify` on the export, and record the last
`row_hash` out of band (for example in the audit report). Anyone with the file can re-run
the verification.

## 7. When the sandbox is unavailable

**Fail closed means the run STOPS.** If Docker is missing, the daemon is unreachable, the
image is not set, the configured user is root, a forbidden mount is requested, or
`docker run` fails to launch (exit 125), `crb` raises `SandboxUnavailable` and the run's
status becomes `blocked`. **No test is run on the host as a fallback**, and no verdict is
recorded for the affected tasks.

What to do:

1. `docker info` as the `crb` user — the daemon must answer.
2. `crb repo probe <repo>` — proves the image and the toolchain.
3. Check the run's status message; it names the cause (`docker binary not found`,
   `daemon not reachable`, `refusing to run untrusted tests as root`, `refusing to mount …`).
4. Fix the cause and **re-run**; the worker (P4) resumes blocked runs. Tasks that were
   never graded have no rows — nothing needs correcting in the ledger.

Do **not** switch the executor to `local` for a repository you do not fully trust; the
local executor exists for development and fixture repositories and is visible on every
verdict's apparatus stamp.

## 8. Stop conditions

Stop delivery and investigate before any further sign-off if you observe any of:

- `false_q1 > 0` anywhere (`crb_false_q1_total` metric non-zero);
- `crb ledger verify` fails;
- a secret in an evidence pack, log or export;
- a sandbox escape or unexpected network egress from a test container;
- a builder repeatedly disqualified for test tampering (shows as a rising `disqualified` count).

Resume only after root cause, correction, a targeted regression run and re-qualification
of the affected cells.
