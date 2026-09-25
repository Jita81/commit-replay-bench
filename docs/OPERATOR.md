# Operator guide

*For the person who installs, configures and runs `crb` inside an organisation's tenant —
the tech lead's first afternoon, and the runbook after it.* It covers the day-2 work:
installing and checking the instrument, connecting and configuring a repository, running a
sweep, reading the capability map, signing a cell off, exporting and verifying the ledger,
what happens when the sandbox is unavailable, and the stop conditions. Installing the
product itself (image, Helm, Azure, backup, upgrade, go-live) is the
[Deployment guide](DEPLOYMENT.md); the GitHub connection is [GITHUB-APP](GITHUB-APP.md);
what a number may be claimed to mean is [EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md).
Every screen in the UI ends with an *About this screen* block and every element carries a
hint; this guide is the same material in one place, with the commands.

Read alongside: [README](../README.md) · [ARCHITECTURE](ARCHITECTURE.md) ·
[EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) · [ADR-0005 (sandbox)](adr/0005-fail-closed-docker-sandbox.md).

This guide is also bundled into the UI: open **Help** in the top bar (`/help`) for the
glossary and the guide index, or `/help/docs/OPERATOR` for this page, so an operator on a
deployment with no egress reads the same text the build was made from (DL-046). Every
screen ends with an *About this screen* block: its purpose, the next step for your role,
what the numbers mean, where the terms are defined and, once opened, every element on the
screen with its explanation. Hover over, focus or tap any number, pill, column heading,
button or field for what it shows and what its value means; Escape closes the explanation.

Contents: [1 Install](#1-install) · [1.1 Check the installation](#11-check-the-installation-crb-doctor) ·
[2 Configure a repository](#2-configure-a-repository) ·
[3 Run a sweep](#3-run-a-sweep) · [4 Read the capability map](#4-read-the-capability-map) ·
[5 Sign off](#5-sign-off) · [6 Export the ledger](#6-export-and-verify-the-ledger) ·
[7 When the sandbox is unavailable](#7-when-the-sandbox-is-unavailable) · [8 Stop conditions](#8-stop-conditions) ·
[9 Users](#9-users) · [10 The factory's test author](#10-the-factorys-test-author) ·
[11 Intake — work arriving from a board](#11-intake--work-arriving-from-a-board) ·
[12 The prevention loop](#12-the-prevention-loop)

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

Model credentials are read from the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`CEREBRAS_API_KEY`, the Azure pair) or, for the Claude Code login token, from the
owner-only secrets store (§3.0.1); they are never written to configuration files, evidence
packs or logs. `crb` redacts common secret shapes from every stored string as defence in
depth, but do not put live secrets in repositories under measurement.

The server, the worker and the UI are `crb serve` and `crb worker` (the `[server]` extra;
the UI is built into `ui/dist` or shipped in the image). Where they live — a laptop, one
VM, Compose or Kubernetes — and where their data must **not** live (a temporary directory)
is [DEPLOYMENT §1](DEPLOYMENT.md#1-deployment-shapes).

### 1.1 Check the installation (`crb doctor`)

```bash
crb doctor            # one line per check: ok / warn / fail (skip = does not apply), and the fix
crb doctor --live     # also one no-tool Haiku turn on the stored Claude Code token; never otherwise
crb doctor --json     # the same report in the /health vocabulary (ok / degraded / down / skipped)
```

Run it on the API host and on the worker host after installing, after changing any
`CRB_*` variable, and whenever a run sits `queued`. It exits 1 only on a `fail`. The lines:

| Line | What it checks | `fail` means |
|---|---|---|
| `toolchains` | `git`, `python3`, `go`, `node`, `mvn`, `cargo` on PATH | `git` missing (the others are `warn`) |
| `sandbox` | the Docker daemon answers | no daemon: sandboxed runs fail closed ([§7](#7-when-the-sandbox-is-unavailable)) |
| `builders` | which builder credentials / CLIs are configured (names, never values) | — (`warn` when none) |
| `claude_code` | where an `auth: cli` login would come from (env, secrets file `…xxxx`, keychain, none), the CLI's version; with `--live`, the real probe | the secrets file is group/world readable |
| `settings` | the server would start with this environment (`CRB_SECRET_KEY`, bootstrap password, `CRB_HOME`, …) | the first refusal, in the server's own words |
| `home` | `CRB_HOME` is a persistent path, and the secrets directory is mode `0700` and owned by the user running `crb` | a temporary `CRB_HOME` in `prod` (`warn` in `dev`); a group-readable secrets directory, or one another user owns (the store refuses both) |
| `github_app` | the app is configured, the key file is readable and parses, GitHub answers `/app/installations`, how many installations can deliver | half configured, an unreadable or malformed key, GitHub refusing (`skip` when not configured; `warn` with no installation yet) |
| `database` | the store answers and is initialised, every append-only trigger is present and they fire (an UPDATE on `grades` is refused) — the same reading as `/health` | not initialised, or triggers missing (`n/m present`) — `crb migrate` |
| `migrations` | the store's Alembic revision is the code's head — the same reading as `/health`, whose contract is [API.md — The `migrations` probe](API.md#the-migrations-probe): `ok` at head; `degraded` (still served) for an unstamped `create_all` schema that matches the head, until `crb migrate` stamps it; `down` (the endpoint answers 503) when the store is behind, ahead, empty or an older unversioned schema (crb tables, no `alembic_version`, fingerprints of a revision behind the head) — revisions named where applicable, with the fix — or when it cannot be read — the fixed detail `migrations could not be read — see the API log, request id <id>`, `data: {}`, the exception in the API log under that id (`crb doctor` runs in the operator's own terminal, so its `migrations` line shows the driver's error type and message — there is no unauthenticated reader to protect; only its `sandbox` and `worker` lines share `/health`'s fixed sentence) | the `down` states: behind, ahead, empty or an older unversioned schema, or cannot be read — `crb migrate` (or the log). `warn` only for an unstamped `create_all` schema that matches the head (complete; `crb migrate` stamps it) |
| `worker` | the workers' check-ins (the `workers` table), the queue depth and running runs' heartbeats, as `/health` reads them | `warn` when no worker has checked in yet, one stopped checking in (named, with its age), runs are queued and no worker is alive, or a running run's heartbeat is stale (an idle queue with a live worker is `ok`) |
| `ui` | the built UI the API serves and the help bundle in it (one non-empty chunk per guide) | `warn` without a build, or when `/help/docs/<guide>` would be empty |

`/health` on the running API answers the same questions from inside the process
([DEPLOYMENT §8](DEPLOYMENT.md#8-go-live-checklist)); `crb doctor` is for the host, before
and between runs.

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

### 2.0 Connecting and configuring a repository from the UI

**Connect** is the first screen of the journey. With the GitHub App configured
([GITHUB-APP](GITHUB-APP.md)), *Connect from GitHub* lists the repositories each
organisation's installation may see and registers the one you pick with a pre-filled name,
language and runner — no token is handed over; the worker mints the installation's own. A
repository you already measured can instead be *linked* to the picked GitHub repository — it
keeps its name and its evidence; only its URL moves ([GITHUB-APP §4](GITHUB-APP.md)).
Without the app, *Connect by URL* registers a public repository (or one the worker's git can
reach). Either way the repository then walks the six stages (probe → mine → oracle →
controls → first measurement) on `/connect/<name>`, each saying what it proves and what it
costs, and lands on **Results**.

A registered repository is edited on its page under **Configuration** (operators and
admins edit; viewers see the same form read-only). The form covers every field
`PUT /repos/{name}` accepts — language, runner, clone path / URL, layout (source prefix,
extensions, test mode with the matching test prefix or `|`-separated test suffixes), belt
scope (the three policies or an explicit list with one scope per row), probe scope,
sandbox image, layer, mining caps — and the **runner options** as a sub-form that offers
exactly the keys the selected runner reads (below), with a *Raw JSON* view that
round-trips for anything else. Inline validation refuses what the API would refuse, in
the API's words (`test_mode='suffix' requires test_suffix`, `String should have at most
32 characters`, …), and the runner-option checks refuse what the *runner* would choke on
at run time (a `pip` given as a string instead of a list, an empty `extra_args` row, a
non-integer `timeout`).

**Save** sends only the fields you changed (the pending line under the form lists them);
the server merges, re-validates the whole config and appends a `repo.updated` event whose
payload is the redacted field diff. The **Audit trail** card below the form lists those
events newest first — who changed which fields, with the from/to values as stored — so
"who widened the belt" is answered from the append-only events table. After a save the
toast offers **Run probe now**: the probe run is enqueued and followed inline until it
ends, green with the runner's own summary (`5 passed in 0.02s`) or red with the reason
(`probe not green: rc=1`, `setup failed: …`), linked to the run. A probe always runs the
*stored* configuration, so the button is disabled while the form has unsaved edits.

Runner options the form offers, runner by runner (nothing else is read; unknown keys are
kept untouched and listed as "not read by this runner"):

| Runner | Keys read (`crb.core.runners`) |
|---|---|
| every runner | `timeout` (s, one test command), `setup_timeout` (s, one setup step) |
| `pytest` | `python`, `pythonpath_suffix`, `pip` (list), `pip_fallback` (list), `uninstall` (list), `env` (map) |
| `node` | `node`, `npm`, `env` — `node --test` takes no extra arguments |
| `jest` / `vitest` | `npm`, `extra_args` (list), `env` |
| `mocha` | `npm`, `mocha_require`, `extra_args`, `env` |
| `go` | `go`, `cgo` (`0`/`1`), `gomodcache` (docker only) |
| `cargo` | `cargo`, `offline` (default true), `cargo_home` (docker only) |
| `maven` | `mvn`, `maven_flags` (list), `java_home`, `offline` (default true), `writable` (list), `maven_opts` (docker only) |

Three shapes we met onboarding NHS repositories, as worked examples — each is what the
form saves, shown as the stored `runner_opts` / layout it produces:

**A jest monorepo that must exclude a browser project and needs node 24.** The suite has
several jest projects; the browser-driven one has no place in a regression belt, and the
package's `engines` pins node ≥ 24 while the host default is older. Runner `jest`, source
prefix `packages/`, extensions `.js|.mjs|.ts|.tsx`. The tests are co-located with their
sources, so a test *prefix* cannot tell them apart: test mode **suffix** with
`.test.js|.test.mjs|.test.ts|.test.tsx`. Belt scope **AFFECTED_DIRS**. Runner options:
*Extra arguments* rows `--selectProjects` and `unit` (one row each — jest's variadic
option would otherwise swallow the test paths, which is why the runner puts `--` before
them), and an *Environment variables* row `PATH` = `/opt/homebrew/opt/node@24/bin:/usr/bin:/bin`
(applies to `npm ci` in setup as well as to every test command). Stored:

```json
{"extra_args": ["--selectProjects", "unit"],
 "env": {"PATH": "/opt/homebrew/opt/node@24/bin:/usr/bin:/bin"}}
```

**A jest + TypeScript component library whose commits touch snapshots.** Many commits
change only a `__snapshots__/*.snap`; the runner maps a snapshot to the test that owns
it, but only if the snapshot counts as a *test file* — so the suffixes must include
`.snap`. Test mode **suffix** with `.test.ts|.test.tsx|.snap`, extensions `.ts|.tsx`,
source prefix `src/`. The suite is small and fast, so belt scope **BARE** (the whole
suite on every task — the widest belt, the strongest green). Runner options: none beyond
`timeout` if the default 420 s is tight; `npm` only when the host's npm is not the one
that installed `node_modules`.

**A pytest package installed editable, with its own distribution removed.** A `src/`
layout whose tests import the package by name. Setup must install the test dependencies
*and* make sure the tests import the worktree's source, not a wheel built from the clone
at `HEAD` — the census invariant. Runner `pytest`, source prefix `src/`, test prefix
`tests/`, belt scope **AFFECTED_DIRS**, *PYTHONPATH suffix* `/src`, *pip install
arguments* rows `-e`, `.[test]` (one token per row; a single `"-e .[test]"` row is also
split on whitespace by the runner), *Uninstall after install* row `<distribution-name>`.
Stored:

```json
{"pythonpath_suffix": "/src",
 "pip": ["-e", ".[test]"],
 "uninstall": ["<distribution-name>"]}
```

Then **Save → Run probe now**: green means the belt can be trusted for that shape; red
names the step (a missing extra, a wrong PATH) before any task is mined.

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

**Sandbox images**: start from the shipped reference set —
[`deploy/sandbox/`](../deploy/sandbox/README.md): `crb-sandbox-python` (pytest),
`crb-sandbox-node` (`node --test`), `crb-sandbox-go`, each digest-pinned, running as user
`65534` with a read-only root and proven from inside by CI **[measured — `tests/test_sandbox_images_docker.py`, 10 tests × 3 images, plus the sandbox and sealed-builder suites on the python image, run as CI's `sandbox-images` smoke step (`-m "not network"`, strict warm-up, any skip fails the step): 47 passed / 0 skipped on images built from this tree, colima / Docker 29.5.2, 2026-09-22; the job runs that step on every pull request — PR #44 run 35678358686 on the merged head 4a64fe3, 44 passed / 0 skipped, before this commit added the setuid and strict-warm-up tests; hadolint on each Dockerfile in the same job; apparatus 2.2]** — and extend one per repository
(or per toolchain) with the repository's dependencies when its tests need more than the
runner. Under docker, setup does not run (`BaseRunner.sandbox_refusal`: setup is a host
phase and fails closed with `SETUP_SANDBOX_REFUSED` when the executor is `docker`), so the
image must already contain what setup would have installed — and nothing a host setup
installed is visible inside: the sandbox mounts only the trial worktree, read-only, at
`/work`, and a trial worktree's `node_modules` is a **symlink to the host clone's**
(`Workspace._post_create`), which dangles inside the container; a host venv, module cache
or `~/.m2` is likewise absent by construction — `DockerExecutor.build_argv` binds only the
worktree (read-only, at `/work`) and tmpfs where the runner declared it, nothing else from
the host **[measured — `tests/test_execution.py::test_docker_build_argv_has_every_hardening_flag`
and `::test_docker_build_argv_network_writable_paths_extra_mounts_and_cwd` pin the argv
token by token; apparatus 2.2]**. Bake the dependencies into a derived image
([`deploy/sandbox/README.md` §4](../deploy/sandbox/README.md) — `npm ci` of the lockfile
under `/opt/app` and `runner_opts.env: {NODE_PATH: /opt/app/node_modules}`; hash-pinned
test requirements for Python; `GOMODCACHE` for Go) **[measured — the symlink claim only: a `node_modules` symlink
to a host directory reads `No such file or directory` from inside `crb-sandbox-node`
under `DockerExecutor`, n = 1 probe, colima / Docker 29.5.2, 2026-09-22; apparatus
2.2]**; the derived-image recipe itself is the README's and is **[hypothesis]** until a
repository is measured on one. Name the image in the repository's `sandbox_image` (it wins) or the deployment's
`CRB_SANDBOX__IMAGE` (the default for repositories that name none); the worker never pulls,
so it must be in the daemon's store. A JVM reference image is not shipped — the Maven
runner cannot resolve plugins offline under docker yet (README §6), so under the compose /
Helm default (`CRB_SANDBOX__EXECUTOR=docker`) a JVM run fails closed rather than falling
back. The executor is chosen **per run, never per repository**: a run request's `executor`
field (`POST /runs`, one of the known executors) wins, else the worker's
`CRB_SANDBOX__EXECUTOR` / `--executor` applies to every run it handles; to measure a JVM
repository today, submit its runs with `executor: local` (or on a worker started `local`),
and the row's apparatus stamp carries the executor it ran under
**[measured — by inspection of `src/crb/server/worker.py`: `_executor` reads
`ctx.params.get("executor") or self.settings.executor` and `_stamp` writes
`executor: <its describe()>` into the run's `apparatus_json`; `tests/test_worker.py` pins that a
run's `apparatus_json` carries the runner and the executor it ran on; apparatus 2.2]**.

### 2.1a Packaging-metadata tests (`dist_info_stubs`)
The harness imports the repository's code from the worktree on `PYTHONPATH` and uninstalls
the repository's own distribution so a stale install can never shadow it. A test that
asserts the *package metadata* — `importlib.metadata.version("mesh-client") != "unknown"`
(NHSDigital/mesh-client `test_get_version`) — then fails for a reason that is neither the
builder's nor the oracle's. Declare the identity and the harness writes a METADATA-only
dist-info (no file records, so nothing is shadowed) after the uninstall:

```json
"runner_opts": {"uninstall": ["mesh-client"],
                "dist_info_stubs": [{"name": "Mesh-Client", "version": "0.0.0+crb"}]}
```

The stub is a recorded setup step (`crb dist-info-stub …`) and therefore part of the
apparatus record of every row measured under it.

### 2.1b Clean means working — the `checks` switchboard

A clean row says the repository's tests accept a patch. Three mechanisms make it also mean
the repository's reviewers would (ADR-0021). Each is **off** until you switch it on, for one
run or for the repository, and every row it touches records it.

| switch | what it does | what the row records |
|---|---|---|
| `format_step` | runs the repository's own formatter (`gofmt`, `ruff format`, `black`, `prettier`, `standard`, `cargo fmt`, or the one you declare) over the changed source files before grading, so the graded patch is the formatted one | `labels.format_step`: `ran=gofmt;changed=1`, or `skipped=<reason>` when the repository configures no formatter |
| `finish_gate` | puts the repository's own checks in the brief as a numbered checklist, re-runs them after the build, and gives the builder up to `finish_repair_turns` (default 1) bounded repair calls; `done` needs them to pass | `labels.finish_gate`: `before=fail:lint;repair=1;after=pass` |
| `api_stable` | belt 6: the public API of the code the builder changed must be unchanged unless the maintainers' commit changes it the same way (Go, Python, JavaScript/TypeScript) | `labels.api_stable` (`true`/`false`/`none`) and `labels.api_findings`; failure kind `api` |

Switch them on for a repository (the change lands on the repository's audit trail):

```bash
curl -X PUT "$CRB/api/v1/repos/cobra" -H 'content-type: application/json' -d '{
  "checks": {"format_step": true, "finish_gate": true, "api_stable": true,
             "commands": [{"name": "test", "argv": ["go", "test", "./..."], "blind_only": true}]}}'
```

or for one run: `POST /runs {…, "checks": {"finish_gate": true}}` (the run beats the
repository; the repository beats off). `commands` are the repository's extra checks — a type
checker, a vet, the test suite for blind attempts — run in the worktree with no network; one
that already fails on the untouched parent is recorded `pre_existing` and never holds an
attempt back. `go vet ./...` is added for you when `.golangci.yml` enables `govet` or the
Makefile or CI runs it. `formatter: {"command": [...], "exts": [...]}` declares a formatter
the detectors miss; `{"disabled": true}` switches the format step off for the repository.

To see what the product derives for a checkout against what its CI runs, and the gaps:

```bash
python scripts/audit_runner_commands.py /srv/repos/cobra --language go --runner go
```

### 2.2 Services the oracle needs

Some test suites are only an oracle when a **service** is running next to them —
NHSDigital/mesh-client's integration tests talk to the MESH sandbox on `localhost:8701`
over TLS, with certificates that must match the ones the commit's own tests carry. The
first measurement of that repository (`docs/reviews/2026-09-14-nhs-public-repos.md`) was
assembled by hand and therefore not reproducible from the configuration. `runner_opts.services`
is the first-class notion: the service, how to know it is up, what it must be given, what
the tests are told, and which *era* of it a commit needs.

**What happens.** `crb repo setup` (or the `setup` run kind) stages every variant's
fixtures under `<env_dir>/services/<service>/<variant>/` (running each `generate` once, in
the clone) and starts the latest variant; every docker command it ran is a recorded setup
step, and the `SetupResult` carries `services: [{name, variant, ref, image_digest,
healthy_at, adopted, container}]`. At grade time the runner makes sure the variant the
task's authored date selects is healthy — reusing the running one, replacing it when the
era changes — merges the service's `export` environment into the test command, and stamps
the same record onto every `TestRun` (`target_run.services` / `belt_run.services` in the
evidence). A service that cannot be started, built, staged or probed healthy is
`ServiceUnavailable` (a `SandboxUnavailable`): the run stops `failed` with the reason and the
service's last log lines; nothing is graded against a missing oracle, and nothing reads as
red *or* green because of it. **The builder gets the same service:** in a sighted build the
era's services are brought up before the builder starts and their `export` environment is part
of the test command the brief shows, so the builder runs the oracle the grader will run — it
never has to (and is never allowed to) start the service itself. Measured on mesh-client
(2026-09-15): without this, 2 of 4 sighted attempts were refused for reaching for `docker ps` /
`curl localhost:8701`.

**The shape.** One entry per service, exactly one of `image` | `compose` | `build`:

| key | meaning |
|---|---|
| `name` | lowercase `[a-z0-9_.-]`, unique; part of the container / compose project name |
| `image` | a runnable image (`docker run -d`) |
| `compose: {file, service, override}` | a service of the **repository's own** compose file; `override` is merged as a second compose file — where the build ref that still builds, extra environment, or anything the pinned file gets wrong today goes |
| `build: {context, ref}` | `docker build` of a directory in the clone, or of a git URL at `ref` |
| `command` | overrides the image's command (an image with no entrypoint of its own) |
| `ports` | `["<host>:<container>", …]` (compose: replaces the file's ports when given) |
| `env` | the container's environment |
| `export` | environment for the **test command**; `{host}`, `{port}` (first host port), `{fixtures}` (the staged directory), `{name}` are substituted |
| `health: {url \| cmd, timeout_s, interval_s, insecure_tls}` | required: a URL answering 2xx/3xx (`insecure_tls: true` accepts the service's self-signed certificate) or a command exiting 0, polled until `timeout_s` |
| `fixtures: [{src, dst, ro}]` | files the service must see: `src` is a path in the clone (after `generate`) **or `<ref>:<path>`** — the file as committed at `ref`, read with `git show`; `dst` is the absolute container path |
| `generate: [argv…]` | a repository command that produces fixtures (certificates…); runs **once per variant**, in the clone, before the fixtures are staged |
| `variants: [{name, era: {after, before}, fixtures, generate, env}]` | eras of the service, selected by the task's authored date (`after <= authored < before`, dates are midnight UTC); declare them oldest first; at most one variant without an era (the default), last |
| `logs_tail`, `keep`, `start_timeout_s` | log lines kept for the evidence (200); leave the service running when crb exits (`false`); wall clock for a start/build (1800 s) |

`CRB_SERVICES_DIR` (worker environment) moves the staging root off `CRB_HOME` for hosts whose container runtime cannot bind-mount it (colima and Docker Desktop share `$HOME`, not `/private/tmp`).

Top-level `fixtures` / `generate` are shared by every variant; without `variants` they
form the single default variant.

**Worked example — mesh-client.** The repository's `docker-compose.yml` builds the sandbox
from `mesh-sandbox.git#refs/tags/v1.0.27`, which no longer builds (Debian bullseye's
security archive is gone); `v1.0.110` does. Commits before 2025-08-01 committed the test
certificates; commit `5d0047a77c` (MESH-2092, Python 3.13) removed them and added
`scripts/create-test-certs-keys.sh`, which writes `tests/{ca,server,client}.*.pem`
(git-ignored). The sandbox must present the *era's* server certificate, and the tests read
the client certificate from `tests/` in every worktree:

```json
"runner_opts": {
  "post_create": [
    {"symlink": {"path": "tests/ca.cert.pem",     "target": "tests/ca.cert.pem"}},
    {"symlink": {"path": "tests/client.cert.pem", "target": "tests/client.cert.pem"}},
    {"symlink": {"path": "tests/client.key.pem",  "target": "tests/client.key.pem"}}
  ],
  "services": [
    {
      "name": "mesh_sandbox",
      "compose": {
        "file": "docker-compose.yml",
        "service": "mesh_sandbox",
        "override": {"services": {"mesh_sandbox": {"build": {
          "context": "https://github.com/NHSDigital/mesh-sandbox.git#refs/tags/v1.0.110"}}}}
      },
      "ports": ["8701:443"],
      "health": {"url": "https://localhost:8701/health", "insecure_tls": true,
                 "timeout_s": 180, "interval_s": 3},
      "fixtures": [
        {"src": "tests/mailboxes.jsonl", "dst": "/app/mesh_sandbox/store/data/mailboxes.jsonl"},
        {"src": "tests/workflows.jsonl", "dst": "/app/mesh_sandbox/store/data/workflows.jsonl"}
      ],
      "variants": [
        {
          "name": "committed-certs",
          "era": {"before": "2025-08-01"},
          "fixtures": [
            {"src": "5d0047a77c^:tests/server.cert.pem", "dst": "/tmp/server-cert.pem"},
            {"src": "5d0047a77c^:tests/server.key.pem",  "dst": "/tmp/server-cert.key"}
          ]
        },
        {
          "name": "generated-certs",
          "era": {"after": "2025-08-01"},
          "generate": ["bash", "scripts/create-test-certs-keys.sh"],
          "fixtures": [
            {"src": "tests/server.cert.pem", "dst": "/tmp/server-cert.pem"},
            {"src": "tests/server.key.pem",  "dst": "/tmp/server-cert.key"}
          ]
        }
      ]
    }
  ]
}
```

Reading it: the compose file's volumes (`./tests/server.cert.pem:/tmp/server-cert.pem:ro`
…) are replaced by the staged fixtures — compose merges volumes by container path — and its
`build.context` by the override's, so the sandbox builds from `v1.0.110` and presents, for a
task authored 2023-07-01, the certificate committed at the parent of `5d0047a77c`; for one
authored 2025-09-01, the one `create-test-certs-keys.sh` generated (once, in the clone —
which is also what the `post_create` symlinks point every worktree's client certificate at;
pre-boundary worktrees have their own committed copies and the symlink hook leaves an
existing file alone). The tests keep their hard-coded `https://localhost:8701`; no `export`
is needed. Switching eras restarts the one service (compose project
`crb-mesh-client-mesh_sandbox-<variant>`), so **concurrency is 1 per service**: two runs of
the same repository must not share a worker. To run two eras side by side give each variant
its own host port and export the URL instead.

**Where fixtures live, and why.** Under the runner's `env_dir` — `<home>/envs/<name>/services/`
(worker) or `<workdir>/envs/<name>/services/` (CLI) — never under `/private/tmp` or
`$TMPDIR`. On macOS the VM behind docker (colima, Docker Desktop) shares `/Users` but not
`/private/tmp` or `/private/var/folders`, so a bind mount from a temp path is silently
*empty* inside the container; the same applies to any host whose docker VM has a mount
table. Keep `CRB_HOME` on a path the VM mounts.

**Bit-rot policy.** When a pinned build no longer builds, the start fails **closed** and the
message names the exact key to set (`compose.override.services.<svc>.build.context`, or
`build.ref`) with the hint to try the latest release tag. crb never substitutes a version
silently: the version the oracle ran against is in every record, and changing it is your
configuration change.

**Adoption and cleanup.** Container / project names are deterministic
(`crb-<repo>-<service>-<variant>`), so a healthy instance another process left running is
adopted (`adopted: true` in the record) rather than restarted. What crb started it stops
when the process ends (`keep: true` leaves it up); `docker ps --filter label=crb.service`
lists anything left behind. Under the docker executor services refuse — the sandbox runs
tests with `--network=none`, so the tests could not reach `localhost` anyway; run such a
repository under the local executor or ship the service inside the sandbox image. The last
`logs_tail` lines of a service are kept, redacted and capped like test output, when it
stops or fails its health wait (see `DATA-RETENTION.md`).

## 3. Run a sweep

```bash
crb mine  myrepo --pool standard --target 25       # RED-check, baseline, gold-check; writes tasks
crb grade myrepo --builder editblock --mode sighted --budget-usd 5   # builders: editblock, openai_agent, claude_code
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
login is stale: run `claude login` as the worker's user and re-queue — or, better, supply a
long-lived token as described next.

#### 3.0.1 Supplying the Claude Code login token (`auth: cli`)

A keychain login (`claude login`) only works headlessly while its access token is fresh;
an expired one cannot be refreshed by a worker process (the CLI asks its parent to
refresh and gets nothing), so builds fail `401`. `claude setup-token` mints a long-lived
subscription token for exactly this case. The worker takes it from the first of these
sources — nothing is merged, and `api_key` mode never reads any of them:

| Order | Source | How to supply it | When to use it |
|---|---|---|---|
| 1 | `CLAUDE_CODE_OAUTH_TOKEN` in the **worker's** environment | your process manager / secret injection (compose `env_file`, a Kubernetes `Secret` env var) | a worker on a different host from the API, or a platform that already injects secrets |
| 2 | the **secrets file** on disk: `CRB_SECRETS_DIR` → `$CRB_HOME/secrets` → `./.crb/secrets`, file `claude_code_oauth_token` | **Settings → Claude Code login** in the UI (admin): **Sign in with your Claude account** — the API host runs `claude setup-token` for you, a new tab opens on Anthropic's sign-in page, you approve, paste the code the page shows, and the minted token is stored on the API host (it never passes through the browser); then **Verify**. Or run `claude setup-token` on any machine and paste the token, **Save**, **Verify**. Or mount the file yourself (`CRB_SECRETS_DIR=/mnt/secrets`, mode `0600`, a raw value, no metadata needed). The browser sign-in needs the `claude` CLI on the **API** host (`CRB_BUILDER__CLAUDE_BINARY` when it is not on PATH; the container image ships it) | the API and worker share `CRB_HOME` (the compose and Helm deployments do), or a Key Vault / CSI mount |
| 3 | nothing | `claude login` as the worker's user | a developer machine where the interactive login is fresh |

The file is written `0600` inside a `0700` directory owned by the API user, atomically;
the API never returns the value (`GET /settings/secrets` reports `present`, the last
four characters, who set it and when); an insecure mode (any group/other bit) is refused
on write and on read — the build fails closed with `model_error: … secrets file refused`
rather than use a credential another user could read. `docs/SECURITY.md` 3.3.1 has the
threat model. Wherever the worker runs, `claude` must be on its `PATH`.

**Check it:** `crb doctor` prints a `claude_code` line —
`auth: env | secrets file (…xxxx) | keychain | none`, the CLI version and the secrets
directory; `crb doctor --live` also runs the login probe (one no-tool Haiku turn:
`verify: ok (2.1s)` or `verify: invalid … authentication failed (HTTP 401)`). Run it on
the **worker** host with the worker's environment — that is the resolution a build sees.
The UI's **Verify** button runs the same probe on the **API** host with the stored token
(at most once every 10 s).

**Rotate it** (after a suspected exposure, when a person with access leaves, or on a
schedule — the token is long-lived):

1. On any machine: `claude setup-token` → copy the new value.
2. Settings → Claude Code login → paste → **Save** (the old file is replaced atomically)
   → **Verify** shows `ok`. Or replace the mounted file / the env var and restart the
   worker.
3. Revoke the old token: `claude auth logout` on the machine that minted it, or from the
   Anthropic console. Confirm with `crb doctor` (the fingerprint changed) and, if you
   kept the old value anywhere, `crb doctor --live` against it must now say `invalid`.
4. **Remove** it (Settings, or `DELETE /settings/secrets/claude-code-token`) when the
   evaluation is over — `auth: cli` is a developer/evaluation mode; production runs use
   `ANTHROPIC_API_KEY` on the worker and never read the file.

What you will see (the run's live log on `/runs/<id>`, and `crb` on the terminal):
`mine.candidate` → `mine.red` / `mine.skip` → `mine.gold` → `build.*` → `grade.belt` (five
per task with belt 5, `repo_lint_clean`; four on a repository without a lint plan) →
`ledger.append`. The full vocabulary — every action, its payload and who reads it — is
[API.md § Event vocabulary](API.md#event-vocabulary). Skips are normal: a commit whose
target is already green at the parent, or times out, is not a valid oracle and is
excluded, not counted. A queued run shows its place in the line ("Queued — 3 runs ahead of
it"); if the health check's `worker` probe is not `ok`, no worker will take it — see §7.

Every graded task produces an **evidence pack** (redacted; no raw diff, no transcript by
default), its **kept patch** (the builder's change, redacted, at most 1 MiB, under
`CRB_HOME/evidence/patches/` — `GET /grades/{row_hash}/patch` serves it with no retained
worktree; `CRB_RETENTION__PATCHES=false` keeps none) and a **ledger row** that carries the
pack's hash. A row cannot be `clean` without a pack.

#### 3.0.2 Spend: the calibrated budget and the measured escalation rule

Two switches decide what a build run pays for (`crb.core.spend`). Each is set per run on
`POST /runs` or per repository on `PUT /repos/{name}` as `spend: {…}`; the run wins, and
the run's apparatus says which applied and why (`extra.spend.sources`).

| switch | values | default | what it does |
|---|---|---|---|
| `escalation` | `measured` · `always` | `measured` | Before a failed attempt climbs to the next rung, look at that rung's earlier escalations in the cell (same builder and model; at least 10). If fewer than 1 in 10 of them came back clean, stop — the retry is not paid for. `always` climbs every rung, as before |
| `budget_profile` | `default` · `calibrated` | `default` | `calibrated` gives each attempt the caps the ledger's own clean completions in its cell used (p90 × 1.5; at least 8 of them), never less than the run's caps and never more than twice them. It changes what the builder is given, so it stays off until a paired comparison shows it helps |

Why: in the 2026-09-25 export, 40 escalated attempts (a same-model retry: a bare `r2` / `r3`
rung is the run's own builder and model at the same budget, on a fresh worktree with the same
brief) produced 2 clean patches for $20.70, against $1.35 per clean patch on a first blind
attempt; and 47 attempts stopped at their budget cost $28.87 for no output `[measured
2026-09-25; n = 322 valid of 618 rows, apparatus 2.0–2.2, builder claude_code /
claude-sonnet-5; method: the product's failure rule over the export,
scripts/spend_from_export.py]`. Every row a rule shaped says so: `labels.escalation` and
`labels.escalation_rule` on the row that stopped or climbed, `labels.budget_profile`,
`labels.budget_calibration` and `labels.budget_tier` on a calibrated attempt.

### 3.1 Oracle adequacy — mutation scoring

false-Q1 = 0 says a clean grade always had a GREEN oracle. It does not say the green was
worth anything: a suite that never exercises the branch a patch changed passes a wrong
patch too. An **oracle run** (`POST /runs {kind: "oracle"}`, or the run dialog) measures
that directly, with no model: at the GOLD state of each task it plants small deterministic
faults ("mutants") on the commit's changed lines and re-runs the task's target tests.

| Outcome | Meaning | Counted in `oracle_strength = killed / total`? |
|---|---|---|
| `killed` | the target tests went RED with the fault present (a timeout counts — the fault was observable) | numerator and denominator |
| `escaped` | the target tests stayed GREEN — a **proven blind spot**; its diff is in the report | denominator only |
| `uncompilable` | the toolchain rejected the mutant before any test could see it (a build failure with no test id attributed) | **no** — excluded from both |
| `error` | the harness itself failed on that mutant | **no** — excluded from both |

A task is **unscoreable** (`oracle_strength = null`, never averaged in) when its gold
state is RED on its own target tests, when no mutant can be generated on the changed
region, when no mutator exists for the language, or when no mutant reached a verdict.
The adequacy gate ([`crb.core.oracle.adequacy`](../src/crb/core/oracle/adequacy.py))
turns the number into a routing consequence: a CLEAN grade licenses auto-delivery only
when its oracle is `strong` (≥ 0.80 — the same constant as the routing rule's
`min_oracle_strength`); `adequate` (≥ 0.50), `weak` and `unscoreable` route to a human
even on green.

**Two mutator families, one taxonomy.** Every `oracle.score` event carries a
`provenance` stamp — `mutator`, `mutator_family` and `operator_set_hash` — naming the
instrument that produced the number:

| Language | Family | Instrument | What it sees |
|---|---|---|---|
| `python` | `ast` | `PythonAstMutator` — seven AST operators (`cmp_flip`, `arith_flip`, `bool_flip`, `negate_cond`, `off_by_one`, `return_none`, `swap_branches`) | the changed lines **and the full span of every function they touch**; every mutant is compile-checked before it counts |
| `go`, `javascript` (+TS), `jvm` (Java/Kotlin), `rust` | `text` | `TextLineMutator` — the same first five operators at the token level, plus `return_value` and `delete_stmt` ([ADR-0009](adr/0009-text-level-mutators.md)) | **exactly** the changed lines; strings, chars, templates, regexes and comments are never touched; it does not reason about types, so a mutant that fails to type-check is excluded as `uncompilable` by the toolchain, never counted as a kill |

Read the numbers accordingly: a strength is comparable **within one language and one
family** (the hash pins the operator table). Do not compare a Go cell's 0.6 with a Python
cell's 0.6 — the instruments differ, and the stamp says so. A high `uncompilable` count
on a cell is not a defect in the oracle; it means the language's compiler is doing part
of the oracle's job (a deleted declaration in Go or Java never reaches a test). For
JavaScript there is no compile step, so a deleted declaration is a *runtime* fault the
tests can observe — the same operator measures something slightly different there, which
is exactly why the family and language travel with the number.

Every mutant is generated deterministically (candidates sorted on line, column, operator
rank and description; two runs are byte-identical; `max_mutants` — default 20 — truncates
a stable prefix), the file under mutation is restored byte-exact after every mutant (and
verified by hash), and test files are never mutated. The blind-spot catalogue — every
escaped mutant with its diff — is the prevention artifact: each entry names a missing
assertion.

## 4. Read the capability map

`crb ledger stats` (CLI) and the Capability Map screen show, per cell
`(class × size × language × builder × model × provider)`:

| Column | Read it as |
|---|---|
| `n` | eligible graded trials — the claim's denominator; `disqualified` and `errors` shown beside it |
| `point` | clean / n |
| `ci_low – ci_high` | Wilson 95% interval — **the** number to quote |
| `false_q1` | must be **0**; anything else is a stop condition (§8) |
| `oracle_strength_mean` | hygiene-adjusted mutant kill-rate (§3.1) or **not measured** |
| `cost_usd_mean`, `latency_s_mean` | economics per trial |
| `apparatus_versions` | if more than one, the rows are from different instruments and are shown separately |
| `route` + reason | `deliver` / `calibrate` / `granularize` / `human` / `do_not_ship` — see [ADR-0003](adr/0003-one-routing-rule.md) |

Rules of reading: a cell at `n < 10` is `calibrate` whatever its point estimate; a
`deliver` route means "high-confidence candidate under the published bar", not "safe to
automate" — see [EVIDENCE-AND-CLAIMS §6](EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity).
Never quote a point without its interval and its `n`.

## 5. Sign off

An **approver** signs off a cell for a route in the Sign-off screen (or `POST /api/v1/signoffs`).
The server re-derives the cell's statistics and applies the routing rule:

- any false-Q1 row in the cell → **409 Conflict**, nothing written, event logged;
- requested route stricter than or equal to the rule's decision → **201**, an append-only
  `signoffs` row with actor and timestamp;
- requested route more permissive than the rule → **409** with the rule's reason;
- the approver is refused when they are the actor of the attested row (`Grade.actor`), the
  actor of the run that produced it (`Run.actor`), or the only person behind the cell's
  accepted evidence → **409** `same_actor` (`signoff-policy.v3`, the two-person rule): the
  account that queues the runs can never sign their result, whatever its role, and no
  `CRB_SIGNOFF__*` setting relaxes it — a deployment needs a second account (the approver)
  before any cell can be signed. The Sign-off page shows the refusal before the approver
  tries.

Sign-offs are revoked by a new row, never by deleting one. Every row records the kind of
account that signed or revoked (`verifier_kind`: `local` or `oidc`; `service` is reserved
and never minted).

## 6. Export and verify the ledger

```bash
crb ledger verify                          # walks the hash chain; exit 1 and the row number on any break
crb ledger export --repo myrepo -o myrepo.jsonl   # chain preserved; legacy rows keep belt_set=v3-legacy
```

For an audit: export, run `crb ledger verify` on the export, and record the last
`row_hash` out of band (for example in the audit report). Anyone with the file can re-run
the verification.

## 7. When the sandbox is unavailable

**Fail closed means the run STOPS.** If Docker is missing, the daemon is unreachable, the
image is not set, the configured user is root, a forbidden mount is requested, or
`docker run` fails to launch (exit 125 — the daemon's own launch-failure status, observed
for an absent image by `tests/test_sandbox_images_docker.py::test_an_absent_image_fails_closed_without_a_pull`
against colima / Docker 29.5.2), `crb` raises `SandboxUnavailable` and the run is
recorded `failed` with the error `sandbox unavailable: <cause>` (the job store's terminal
status — there is no `blocked` status). **No test is run on the host as a fallback**, and no
verdict is recorded for the affected tasks.

What to do:

1. `docker info` as the `crb` user — the daemon must answer.
2. `crb repo probe <repo>` — proves the image and the toolchain.
3. Check the run's status message; it names the cause (`docker binary not found`,
   `daemon not reachable`, `refusing to run untrusted tests as root`, `refusing to mount …`).
4. Fix the cause and **re-run** (a `failed` run is terminal; start a new one). Tasks that
   were never graded have no rows — nothing needs correcting in the ledger.

Where to look first: `GET /api/v1/health` — the `sandbox` probe (on the worker, or a
one-process deployment) says whether the daemon answers, and the `worker` probe says
whether any worker has checked in at all (a run that stays "Queued" with a healthy
sandbox is a worker that is not running — the probe names the last one seen and how long
ago). On the dashboards `crb_sandbox_unavailable_total` counts every run that stopped
this way; the alert rules and the metrics table are
[DEPLOYMENT.md §9](DEPLOYMENT.md#9-observability).

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

**Intake stop conditions** (ADR-0017). A listener stops with one of eight published reasons,
shown on `/factory/intake?repo=`, on the item's evidence chain as `intake.stopped` and in
`crb doctor`'s `intake` line. None of them loses work: the next poll retries, and nothing is
registered from a partial read.

| Reason | What happened | What you do |
|---|---|---|
| `not_configured` | no tracker is configured for this deployment (or `tracker: fake` without `CRB_ENABLE_FAKE_TRACKER=1`) | set the `CRB_INTAKE__*` block; a listener cannot be switched on until you have |
| `no_secret` | a tracker is configured but no credential is stored | an admin stores the tracker token (`PUT /settings/secrets/tracker-token`, or the Settings screen) |
| `unauthorised` | the tracker rejected the credential (401/403) | mint a new token with permission to read work items and add comments, and store it |
| `unreachable` | the tracker did not answer (timeout, 5xx, 429) | check the URL and that the deployment may reach it; the next poll retries on its own |
| `column_gone` | the watched column or state no longer exists on that board | point the listener at a column that does (`PUT /factory/{repo}/intake` with `column`) |
| `refused` | the tracker refused a write — usually a workflow transition it does not allow, or a permission the credential lacks; or a ticket whose key cannot become an item id, which costs that ticket and nothing else | nothing was changed on the ticket; fix the workflow or the permission, or clear `CRB_INTAKE__OUTCOME_MAP` |
| `column_too_large` | the column holds more tickets than one pass may read (`CRB_INTAKE__MAX_PER_POLL`), or the pass ran past `CRB_INTAKE__POLL_BUDGET_S` | narrow the area path or the JQL so the column holds the work that is genuinely ready, or raise the bound; a pass that ran out of time serves what it read and the rest are read next time |
| `no_public_url` | this deployment does not know its own address, so a link on a ticket would not open | set `CRB_PUBLIC_URL` to the address people use to reach the product, on the API and the worker |

Resume only after root cause, correction, a targeted regression run and re-qualification
of the affected cells.

## 9. Users

An admin manages accounts through the API (`/users`, [API.md](API.md#admin): create, role,
password, active; the Settings screen lists accounts and changes roles), and — when no
admin can sign in — with `crb users` on the API host. The host
verbs need no login: access to the host and the database is the credential. They read the
database `crb serve` reads (`--database-url` → `CRB_DATABASE_URL` → `$CRB_HOME/crb.db`),
so run them with the service's environment (the same `CRB_DATABASE_URL`; on a host, source
the unit's `EnvironmentFile` first; in the container, `kubectl exec` into the API pod). A
verb that resolves a database the server does not use — no file at the SQLite path, or no
`users` table — refuses, names the database it resolved, and creates nothing.

```
crb users list                       # username, role, active, issuer, last login
crb users create <name> --role admin # password from a prompt or CRB_USERS_PASSWORD_FILE
crb users set-password <name>        # its sessions end on their next request
crb users deactivate <name>          # refused for the last active admin (last_admin)
crb users activate <name>            # restores sessions issued before the deactivation
```

**Forgot the admin password?** On the API host: `crb users set-password admin` (the
bootstrap username, or whichever `crb users list` shows as an active admin), type the new
password at the prompt, sign in. **Locked out with no admin at all** (every admin
deactivated by mistake): `crb users activate <name>` or `crb users create <name> --role
admin`. There is no need to empty the `users` table again.

A password is never a command-line argument (shell history, `ps`): the verbs prompt, or
read the first line of the file `CRB_USERS_PASSWORD_FILE` names when there is no terminal
(a deployment script; delete the file afterwards). Passwords are ≥ 12 characters and are
stored as argon2id hashes only. An account that signs in through the organisation's
identity provider has no local password; disable it there.

Every change — by the API or the CLI — is one `system` event on the account's trace
(`user.created`, `user.role_set`, `user.password_set`, `user.activated`,
`user.deactivated`) with the actor (the admin's user id, or `cli:<os user>`) and the
target; never the password. Setting a password ends the account's sessions on their next
request (the cookie is bound to the credential it was issued under —
[SECURITY.md §3.4](SECURITY.md#34-authentication-and-authorisation--crbserverauth)).
Deactivating refuses every request while the account is inactive, but does not move that
credential: re-activating within the session lifetime (`CRB_SESSION_TTL`, 8 hours by
default) restores the sessions issued before. To contain a suspected compromise, deactivate
**and** set a new password; the password is what ends the sessions for good. The last
active admin can never be deactivated, by either door.

## 10. The factory's test author

Forward mode has no held-out test, so nothing can be built until one failing test exists. An
item whose oracle you pasted in when you registered the backlog has one. An item without one
stops `no_oracle` and waits for a person — unless this deployment configures a **test-author
rung**.

Set one variable, on the API *and* the worker:

```
CRB_FACTORY__TEST_AUTHOR=openai_agent:gpt-oss-120b:cerebras
```

The spelling is a rung — `builder:model[:provider]` — exactly as you would write a build
rung, and the builder half must be a registered builder name (`editblock`, `openai_agent`,
`claude_code`). Empty, or `none`, means no author: that is the default and it is the
behaviour the product shipped with. One run can override it without changing the
deployment:

```
POST /runs {"repo": "cobra", "kind": "factory", "test_author": "editblock:gpt-oss-120b"}
POST /runs {"repo": "cobra", "kind": "factory", "test_author": "none"}   # this run pays for no authoring
```

**The author rung and the build rung are never the same rung.** This is the same refusal
that has always stopped a rung building against a test it wrote itself: when the run's spec
is built, the author's label is compared with every rung on the ladder, and a match ends the
run with `SameIdentityError` **before anything is built or paid for**. If the run fails that
way, choose another rung — the message names the ladder. What the refusal deliberately does
not catch is the same model under a *different* registered builder name; the label space is
closed to the registry, so no label can be invented to dodge it, but model-level separation
is your choice of models, not something the product can enforce. [gap]

Nothing the author writes is taken on trust. The test is written in a throwaway worktree at
the base (a stray source edit cannot leak out of it), then the ordinary RED proof runs it at
the base and requires a failure with attributable test ids — green, a timeout or an
unattributable failure is refused. The proven bytes are staged as a throwaway commit and
belt 1 re-checks every test byte after the build. A reply the product cannot use (no file,
an empty file, a path the repository does not call a test) is put back to the model with the
reason, and after the attempts are spent the item simply has no oracle.

**What you see.** The run's apparatus stamp carries `test_author` (`""` = none), the trace
carries `factory/author.configured` before any authoring and one `author.attempt` per try
with the reason a reply could not be used. `GET /settings` (admin) serves the configured
rung under `raw.factory.test_author` (`none` when there is none); the Settings screen does
not show it yet. [gap] An item that still stops `no_oracle` with an author configured
means the author produced nothing usable — read `author.attempt`.

**When the review says the test is too weak.** The loop never rebuilds against an unchanged
test: the item stops `oracle_needs_strengthening` and the Factory screen offers the
replacement item already drafted from the item that stopped and from the reviewer's own
finding. Read the draft, strengthen the test, and register it — the frozen backlog does not
change, the draft is chained onto it.
## 11. Intake — work arriving from a board

A team's own board can be the front door of the factory: a ticket moved into one watched
column is the request to manufacture, and the ticket **is** the backlog item
(ADR-0017). Nothing about this is on by default, and it takes two separate decisions by
two different roles to switch on.

**1. An admin configures the connection, once per deployment.** Set the `CRB_INTAKE__*`
block on the API *and* the worker (DEPLOYMENT.md §2.1), then store the credential:

```
CRB_INTAKE__TRACKER=ado                       # none (default) | ado | jira
CRB_INTAKE__URL=https://dev.azure.com/contoso # https only; the site URL for Jira
CRB_INTAKE__PROJECT=Widgets
CRB_INTAKE__COLUMN="Ready for manufacture"    # the System.State / Jira status watched
CRB_INTAKE__AREA_PATH="Widgets\\Payments"      # Azure DevOps only, optional
CRB_INTAKE__POLL_S=300
CRB_INTAKE__MAX_PER_POLL=200                  # a longer column is not read at all (see below)
CRB_INTAKE__POLL_BUDGET_S=60                  # one pass may take this long, then it stops early
CRB_INTAKE__OUTCOME_MAP='{"merged": "Done"}'  # EMPTY by default: no ticket is ever moved
CRB_PUBLIC_URL=https://crb.example.com        # THIS deployment's address (required, see below)
```

`CRB_PUBLIC_URL` is not optional for intake. The product writes links to its own pages on
somebody else's ticket, and a relative path in an Azure DevOps or Jira comment resolves
against **their** host, so it would go nowhere. A listener cannot be switched on until it is
set (the switch is refused with `intake_no_public_url`), and a pass that somehow starts
without it stops with `no_public_url` before it writes anything.

**Bounds on one pass.** A first pass over a ticket it registers costs **eleven** Azure DevOps
requests, or **nine** Jira ones **[measured — n = 1 ready ticket × 2 adapters; method: every
request counted through an `httpx.MockTransport` for the verb sequence `poll_repository` makes on a
ticket it registers (the column, the ticket, the readiness comment, the label, the queued note, the
item link) — `tests/test_intake_write_bound.py::test_a_first_pass_on_one_ready_ticket_costs_eleven_azure_devops_requests`
and `::test_the_same_first_pass_costs_nine_jira_requests`, which also assert where each request
goes; apparatus 2.2. A count, so no interval]**. Azure DevOps is the dearer of the two because
three of its verbs read before they write. A pass runs in front of the worker's heartbeat and, for
*Re-read the column now*, inside an API request. So a column holding more than
`CRB_INTAKE__MAX_PER_POLL` tickets is **not read at all**: the pass stops
with `column_too_large` and says to narrow the area path or the JQL, because reading an
arbitrary 200 of somebody's board and saying nothing about the rest would be worse than
reading none of it. A pass still running after `CRB_INTAKE__POLL_BUDGET_S` stops early,
serves the tickets it read and records the same reason with how far it got; the rest are
read on the next pass.

The credential is deliberately **not** an environment variable. An admin stores it through
`PUT /settings/secrets/tracker-token` (or the Settings screen): an Azure DevOps personal
access token with *Work items: read & write*, or a Jira API token with the account email in
`CRB_INTAKE__EMAIL`. It is held owner-only on the API host and read back only as a
fingerprint, exactly like the GitHub App key.

**2. An operator switches the listener on, per repository.** `/factory/intake?repo=` →
*Switch the listener on*. Until they do, that repository's column is never read and no
ticket is ever written to — and the switch is stored with who threw it and when. It is one
click to switch off again.

**What the product then does, and what it will never do.** Every `poll_s` the worker reads
the column. For each ticket it has not already handled at its current revision it drafts a
backlog item, runs the readiness gate, and leaves **one** comment (idempotent by a hidden
marker) and **one** `crb:` label. When every question a good acceptance test needs is
answered, the item is registered through the same path the freeze form uses and the ticket
gets `crb:queued`, a note naming the item and a link to it. An edited ticket comes back as an
*evolution* — a new item superseding the old one; the frozen record is never rewritten. Over
a ticket's life it can receive four comments, each marked as its own (what is missing, the
queued note, the pull-request note, the note if the work stopped), one `crb:` label, a link
to the item and a link to the pull request, and — only where the outcome map is configured —
one state change. It edits no other field, never creates a ticket, and never reads a column it
was not pointed at. Switching the listener on or off is itself an event on the repository's
system trace (`intake.listener.switched`) naming the operator, so a later switch cannot
quietly overwrite who consented.

**Telemetry.** `/health` and `crb doctor` carry an `intake` line: the tracker, whether a
credential is stored, whether this deployment knows its own address, how many listeners are
on, and **the stop the last real read recorded** — so a deployment whose listeners are all
failing `unauthorised` reads `degraded`, not `ok`. It contacts no tracker: a readiness probe
that called somebody else's service would make this deployment's health depend on theirs, and
the reachability it reports is therefore the reachability the last poll measured. Every step is on the repository's own evidence chain
(`GET /factory/{repo}/evidence`) as `intake.polled`, `intake.read`,
`intake.feedback.posted`, `intake.registered`, `intake.queued`, `intake.delivered`,
`intake.transitioned` and `intake.stopped` (API.md, "Event vocabulary"). Stop conditions
are in §8.

**Cost.** Reading a column, drafting an item and posting the feedback call no model and
spend nothing. Only a factory run spends, and it is still started the same way (§3).

## 12. The prevention loop

The prevention loop (ADR-0020, the guide's
[§7](LEARNING-LOOP.md#7-prevention--a-bug-is-closed-by-a-change-that-stops-it-recurring))
turns each failure class a builder shows into a change to the process or the context, and
proves by the next attempts whether the change worked. It is **off** on every repository
until you throw its switch, and it spends nothing itself: it makes no model call.

**Read the register.** Open **Learn** and pick the repository: the first card lists every
class with how often it occurred on first attempts, the lever the loop would choose and at
what level, the change in force with its before → after, the status and what happens next.
`GET /learn/register?repo=` serves the same (any viewer), and `crb learn prevention --repo R`
builds it from JSONL files.

**Throw the switch** (operator; `PUT /learn/switch?repo=` or the card's switch control), with
a reason — it is recorded with your name:

* `context` lets the loop add checklist lines to the brief (at most seven, from closed
  templates) and file items for a person;
* `config` also lets it switch on the formatter step, the finish gate and the calibrated
  budget for the repository — as an overlay: a key your repository's configuration sets
  itself always wins;
* `off` suspends every change from the next run. Nothing is lost; switching back resumes them.

A run that must not see the loop's changes (the Phase B off arm) is queued with
`learning: "off"`.

**Let it work.** The worker takes a snapshot of the loop when a replay or blind run starts
(every row records the switch, the changes in force and the lines the builder read) and runs
one tick when the run ends. `POST /learn/tick?repo=` runs one now. A tick that fails is
logged and never fails the run.

**Undo a change** (operator): **Revert** on the class, with a reason, or
`POST /learn/changes/{change_id}/revert?repo=`. The change leaves the next run, and the loop
never applies that lever to that class again.

**Act on a filed item.** When the strongest fix is code or a grader decision, the loop files
an item; it appears in **Decisions** as "a prevention needs an owner". **Register** puts it on
the repository's factory backlog in one act (`POST /learn/items/{item_id}/register?repo=`):
the first item freezes a backlog, later ones evolve it; refused while a factory run holds the
backlog. An item for this product's own code is never put on your backlog: it is served for
the maintainers.

**Link a fix made elsewhere.** A merged pull request or a change to the environment that
should stop a class is linked with `POST /learn/links?repo=` (the classes, a reference and a
note). Its effect is measured from the link forward, never before.

**What the loop will never do:** write a grader key, a guard-corpus line, the failure rule or
a routing threshold; credit a class that went quiet with no change on record; call a class
closed while it still recurs, even as a refusal before spend, or while its failures have moved
to another class; put anything from a task's diff, tests or reviews into a brief; register an
item or write on a board without a named person; re-apply a lever a person reverted.

**If the chain does not verify**, every prevention route answers `409
prevention_chain_broken` and nothing is written: restore the `events` table from the database
backup (DEPLOYMENT §5). The chain lives in the database, never in `CRB_HOME`.

