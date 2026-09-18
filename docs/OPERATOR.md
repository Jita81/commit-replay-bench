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

### 1a. On a Mac, without a toolchain

To look at the product rather than operate it, build the double-clickable application
([ADR-0016](adr/0016-a-double-clickable-macos-app.md)). It carries its own CPython, the
`[server]` extra and the built interface, so nothing above is required on the machine that
runs it — only `git`, and only for the steps that touch a repository.

```bash
macos/build_app.sh          # needs uv and npm at BUILD time, neither at run time
open dist/crb.app
```

It opens your browser on `http://127.0.0.1:<port>/` and prints a generated `admin` password,
also written to `~/Library/Application Support/crb/first-run-credentials.txt` (mode 0600).
That directory is the whole of its state: the SQLite database, the session signing key and
the server log. Delete it to start again.

An application you build on the machine that runs it carries no `com.apple.quarantine`
attribute, so it opens on a double-click. A copy **downloaded** from anywhere is quarantined
and stays refused until it is signed with a Developer ID and notarised —
`.github/workflows/macos-app.yml` does that automatically once the Apple secrets exist.

> **What a desktop run may not be used for.** A Mac with no Docker daemon runs
> `CRB_SANDBOX__EXECUTOR=local`: test runs are **not isolated**, which is the posture
> [§7](#7-when-the-sandbox-is-unavailable) describes. The application relaxes that one
> setting so it can start at all, reports it in the first-run output and in
> `/api/v1/health`, and changes no belt, threshold, routing rule or sign-off clause. Numbers
> produced this way are a development reading. Measure on a sealed executor before anything
> is read as evidence.

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
language and runner — no token is handed over; the worker mints the installation's own.
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

**Sandbox images** are yours to build: one image per repository (or per toolchain) with
the language runtime, the test runner and the repository's dependencies pre-installed,
runnable as user `65534` with a read-only root. Under docker, setup does not run — the
image must already contain what setup would have installed (the `node_modules` a host
setup installed in the clone is visible to the container through the read-only worktree
mount; a host venv, module cache or `~/.m2` is not). P7 ships reference images.

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
directory; `crb doctor --verify` also runs the login probe (one no-tool Haiku turn:
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
   kept the old value anywhere, `crb doctor --verify` against it must now say `invalid`.
4. **Remove** it (Settings, or `DELETE /settings/secrets/claude-code-token`) when the
   evaluation is over — `auth: cli` is a developer/evaluation mode; production runs use
   `ANTHROPIC_API_KEY` on the worker and never read the file.

What you will see (events; UI live progress in P5): `mine.candidate` → `mine.red` /
`mine.skip` → `mine.gold` → `build.*` → `grade.belt` (four per task) → `ledger.append`.
Skips are normal: a commit whose target is already green at the parent, or times out, is
not a valid oracle and is excluded, not counted.

Every graded task produces an **evidence pack** (redacted; no raw diff, no transcript by
default) and a **ledger row** that carries the pack's hash. A row cannot be `clean` without
a pack.

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
