# Deployment guide

*For the platform team that installs crb inside an organisation's tenant.* Day-2 operation
(repositories, sweeps, sign-off, stop conditions) is the [Operator guide](OPERATOR.md); the
design behind these choices is [ARCHITECTURE §6](ARCHITECTURE.md#6-deployment-view) and
[ADR-0005 (fail-closed sandbox)](adr/0005-fail-closed-docker-sandbox.md).

Contents: [1 Shapes](#1-deployment-shapes) ·
[1.1 Single host without containers](#11-single-host-without-containers-evaluation) ·
[1.2 Two stacks on one machine](#12-two-stacks-on-one-machine) ·
[2 The image](#2-the-image-and-its-roles) ·
[2.2 Released image, signature, SBOM](#22-the-released-image-name-signature-sbom) ·
[3 Kubernetes (Helm)](#3-kubernetes-helm) · [4 Azure](#4-azure) ·
[5 Backup & restore](#5-backup-and-restore) ·
[5.1 SQLite](#51-backup-and-restore-sqlite) · [6 Upgrade](#6-upgrade) ·
[7 Air-gap](#7-air-gap-posture) · [8 Go-live checklist](#8-go-live-checklist) ·
[9 Observability](#9-observability) · [Releasing](RELEASING.md)

---

## 1. Deployment shapes

| Shape | When | Where documented |
|---|---|---|
| **Single host, no containers** | an evaluation on a laptop or one VM: `crb serve` + `crb worker` from a virtual environment, SQLite | §1.1 of this page |
| **Single host, Docker Compose** | pilots, one team, one VM in the tenant | [deploy/README.md](../deploy/README.md) |
| **Kubernetes, Helm** | shared platform, AKS/EKS/on-prem, managed PostgreSQL | §3 of this page; [deploy/helm/crb](../deploy/helm/crb/README.md) |

Both container shapes run the same image and the same four things: PostgreSQL, a one-shot **migrate** step,
the **api** (HTTP + UI) and the **worker** (queue consumer that mines, builds, grades and
appends to the ledger). Both enforce the same invariants: the append-only tables carry DB
triggers, every verdict is hash-chained, the sandbox fails closed, and the only permitted
egress is the model endpoint (worker), the OIDC issuer (api), the repository's git remote
(clone, fetch and factory delivery), the GitHub API (api and worker: the GitHub App's
installations and tokens, and a delivery's pull request), the image registry your images
come from, and two flows that are off by default: the tracker the intake watches
(`CRB_INTAKE__TRACKER`) and, with dependency provisioning on (`CRB_PROVISION__ENABLED=true`,
§3.4), the fetch sidecar to your package mirror or registry —
which receives only the package names and versions the task's lockfiles pin
([SECURITY.md](SECURITY.md) has the complete table, with what each flow sends) **[hypothesis — the design SECURITY.md's egress table and the chart's network policies record; a packet capture of a running deployment against that table would confirm it]**.

### 1.1 Single host without containers (evaluation)

The shape every walkthrough, the first factory run (B-1b) and the development stack use:
one directory, one SQLite file, two processes **[measured — n = 2 processes; method: the
commands in the block below, which the development stack runs, one serving the API and the
other the queue; apparatus n/a]**. It is for evaluation — the local executor
does not isolate test runs and SQLite is not the production store (§2.1) — but it holds
sign-offs and ledger rows like any other, so it deserves a fixed address.

```
~/crb-stack/                 # the stack root — a PERSISTENT path, never a temporary one
├── home/                    # CRB_HOME: evidence packs, events, factory evidence, transcripts, clones
│   └── secrets/             # the Claude Code login token (mode 0700; files 0600)
├── crb.db                   # the SQLite store (CRB_DATABASE_URL=sqlite:///~/crb-stack/crb.db)
└── env.sh / restart.sh      # the environment and the two commands, kept next to the data
```

```bash
export CRB_HOME=~/crb-stack/home CRB_ENV=dev CRB_DATABASE_URL="sqlite:///$HOME/crb-stack/crb.db"
crb migrate && crb doctor                       # every line ok or warn before the first run
crb serve --host 127.0.0.1 --port 8000 &        # API + UI
crb worker --home "$CRB_HOME" --executor local  # the queue consumer
```

**Never put `CRB_HOME`, the database or the secrets directory under `/tmp`, `/private/tmp`,
`/var/folders` or `$TMPDIR`** (DL-045). macOS treats those paths as temporary storage: the
OS's periodic clean-up removes untouched files there (see Apple's `periodic` / `daily`
documentation for `/tmp` on your macOS version), and it may empty them on reboot. A
deployment that lives there loses its builder token, its clones' `HEAD` and its restart
script with no error message. The product enforces the rule rather than relying on this
paragraph: `Settings` **refuses to start**
when `CRB_HOME` resolves under one of those roots and `CRB_ENV=prod` (the default), and
**warns** in `CRB_ENV=dev`; `crb doctor`'s `home` line says the same. `CRB_ALLOW_TEMP_HOME=true`
admits a temporary home for a throwaway evaluation only (the walkthrough harness runs
`dev`, so it is warned, never refused). Back this shape up with §5.1.

### 1.2 Two stacks on one machine

A second stack — a pilot beside the operator's own, a rehearsal beside a campaign — needs its
own everything, or the two will fight (pilot D5, 2026-09-27: the second worker could not bind
the metrics port the first one held **[measured — n = 1 bind failure, method: the pilot
worker's own log (`worker.log`, P-436), apparatus 2.3]**).

- **Its own root.** A different `CRB_HOME` and `CRB_DATABASE_URL`, both persistent (§1.1).
  A second stack never shares the first one's store: each worker would claim the other's runs.
- **Its own API port.** `crb serve --port <another>`; the UI is served from the same port.
- **Its own metrics port.** `CRB_METRICS_PORT=auto` lets the operating system pick a free one;
  the port it chose is in `/health` (`worker` probe, `data.workers[].metrics.port`) and in the
  worker's start-up log line. A fixed number works too, as long as it differs; `0` switches
  the listener off. If the port is taken the worker keeps running and `/health` names the
  conflict — no measurement is lost, only that worker's dashboard.
- **Its own login check.** Each stack verifies its builder login on its own (Settings → Claude
  Code login → Verify the login runs use); a login that works for one stack is not assumed to
  work for the other.

```bash
export CRB_HOME=~/crb-pilot/home CRB_ENV=dev CRB_DATABASE_URL="sqlite:///$HOME/crb-pilot/crb.db"
export CRB_METRICS_PORT=auto
crb migrate                                   # in the foreground: the store is at head first
crb serve --host 127.0.0.1 --port 8001 &      # only the API goes to the background
crb worker --home "$CRB_HOME" --executor local
```

## 2. The image and its roles

`deploy/Dockerfile` builds one image from the repository root: a `node` stage builds `ui/`
if present, a `python:3.12-slim` stage installs `crb[server,postgres]` non-editable into
`/app/.venv` as uid **10001** (`crb`), with `git` and the Docker **client** binary. Released
builds of it are published, signed and SBOM-attested to GHCR (§2.2); the same Dockerfile is
built and smoked by CI on every pull request. The entrypoint (`deploy/entrypoint.sh`)
selects the role:

| Role | Command | Notes |
|---|---|---|
| `serve` | `uvicorn --factory crb.server.app:create_app` | `--proxy-headers`, `--no-server-header`; serves `$CRB_UI_DIST` |
| `worker` | `python -m crb.server.worker_main` | needs a Docker daemon for sandboxes (opt-in) |
| `migrate [upgrade\|current\|check]` | `python -m crb.store.migrate` | `upgrade` = alembic head **+** append-only triggers, one transaction; `check` exits 1 when pending |

The container runs with a read-only root filesystem; writable paths are `/tmp`, `/home/crb`
(both tmpfs/emptyDir) and `$CRB_HOME` (`/srv/crb`: clones, worktrees, exports).

### 2.1 Environment reference

Settings are `CRB_`-prefixed; nested groups use `__`. Secret values are `SecretStr` in the
server and never appear in logs or `/settings`.

| Variable | Required | Meaning |
|---|---|---|
| `CRB_DATABASE_URL` | yes | `postgresql+psycopg://user:pw@host:5432/db?sslmode=require`; SQLite (`sqlite:///…`) is for development only |
| `CRB_SECRET_KEY` | yes (prod) | ≥ 32 chars; signs sessions. `CRB_ENV=prod` (default) refuses to start without it |
| `CRB_ENV` | | `prod` (default: Secure cookies, key required) or `dev` |
| `CRB_HOME` | | state dir; `/srv/crb` in the image. **Refused** in `prod` (warned in `dev`) when it resolves under `/tmp`, `/private/tmp`, `/var/folders` or `$TMPDIR` — §1.1 |
| `CRB_ALLOW_TEMP_HOME` | | `true` admits a temporary `CRB_HOME` in `prod` for a throwaway evaluation; the warning is still logged. Never on a server |
| `CRB_BIND_HOST` / `CRB_BIND_PORT` | | `0.0.0.0:8000` in the image |
| `CRB_PUBLIC_URL` | for *work arriving from a board* | the address people use to reach THIS deployment (`https://crb.example.com`; plain `http://` only on loopback). Set it on the **API and the worker**: the product writes links to its own pages on somebody else's ticket, and a relative path resolves against the tracker's host, so an intake listener cannot be switched on until it is set and a pass without it stops with `no_public_url` |
| `CRB_FORWARDED_ALLOW_IPS` / `CRB_TRUSTED_PROXIES` | | addresses whose `X-Forwarded-*` are believed (uvicorn / app). Set both to the proxy's CIDR; empty = believe nobody. Never `*` — a wildcard lets any client spoof its address and scheme (Helm ships empty; compose `127.0.0.1`) |
| `CRB_WEB_CONCURRENCY` | | uvicorn workers (default 1; 2 in compose/Helm) |
| `CRB_BOOTSTRAP_ADMIN__USERNAME` / `__PASSWORD` | first boot | seeds the first admin **only while `users` is empty** (≥ 12 chars) |
| `CRB_LOCAL_AUTH_ENABLED` | | set `false` once OIDC works |
| `CRB_OIDC__ISSUER`, `__CLIENT_ID`, `__CLIENT_SECRET`, `__REDIRECT_URL`, `__SCOPES`, `__ROLE_CLAIM`, `__ROLE_MAP`, `__ADMIN_GROUPS` | for SSO | see §4.1 for the Entra ID mapping |
| `CRB_OIDC__ROLE_FROM_CLAIMS` | | `first_login` (default): the claims set a role on the account's first sign-in and an admin's later change stands; `always`: the provider decides at every sign-in (removing someone from the admin group demotes them next time), each change recorded as `user.role_overridden`, but never a demotion of the last active admin — or of the last who can sign in (a local admin does not count once `CRB_LOCAL_AUTH_ENABLED=false`) — which keeps its role and records `user.role_override_refused` ([SECURITY §3.4](SECURITY.md#34-authentication-and-authorisation--crbserverauth)) |
| `CRB_GITHUB__APP_ID`, `__APP_SLUG`, `__PRIVATE_KEY` or `__PRIVATE_KEY_FILE`, `__API_URL`, `__WEB_URL` | for *Connect from GitHub* | the deployment's GitHub App (docs/GITHUB-APP.md); set on the **API and the worker**; the key from the secret store, never inline in a values file |
| `CRB_INTAKE__TRACKER`, `__URL`, `__PROJECT`, `__COLUMN`, `__AREA_PATH`, `__JQL`, `__EMAIL`, `__POINTS_FIELD`, `__ACCEPTANCE_FIELD`, `__POLL_S`, `__MAX_PER_POLL`, `__POLL_BUDGET_S`, `__OUTCOME_MAP`, `__REQUIRE_APPROVAL`, `__APPROVE_AUTHORS` | for *work arriving from a board* | the tracker this deployment takes work from (ADR-0017); set on the **API and the worker** so one environment configures both. `TRACKER` is `none` (the default — nothing is read anywhere), `ado` or `jira`; `URL` must be `https://`; `POLL_S` defaults to 300; `MAX_PER_POLL` (200) bounds one pass — a longer column is not read at all, it stops with `column_too_large` — and `POLL_BUDGET_S` (60) is how long one pass may take before it stops early and serves what it read; `OUTCOME_MAP` is JSON (`{"merged": "Done"}`) and is **empty by default**, so no ticket is ever moved. `REQUIRE_APPROVAL` is **`true` by default** (ADR-0022): a ready ticket waits on the Intake screen until an operator registers it; `APPROVE_AUTHORS` is a JSON list of tracker authors (the ticket's creator) whose tickets skip that act, **empty by default**. The credential is NOT an environment variable: an admin stores it at `PUT /settings/secrets/tracker-token`. Whether a given repository's listener is on is per repository, **default off**, and an operator's to switch |
| `CRB_SANDBOX__EXECUTOR` | api, worker | `docker` (default in `prod`, fail-closed) or `local` (development; the worker's default in `dev`). Read by the API (`/settings`, `/health`) and by the worker (`crb worker`; its short form `CRB_EXECUTOR` is read when this is absent). `local` in `prod` is **refused** unless `CRB_ALLOW_UNSEALED_PROD=1` is set with `CRB_ALLOW_UNSEALED_PROD_BY` and `CRB_ALLOW_UNSEALED_PROD_REASON` (below) |
| `CRB_BUILDER__EXECUTOR` | api, worker | where the builder runs: `docker` — the sealed container of ADR-0012 (an exported checkout that cannot contain the gold commit, one allowlisting egress sidecar) — or `host` (development). Empty means the env's default: `docker` in `prod`, `host` in `dev`. Compose and Helm pass one value to both the API and the worker (empty by default), so `/health` describes the builds the worker runs. `host` in `prod` is **refused** unless `CRB_ALLOW_UNSEALED_PROD=1` is set with `CRB_ALLOW_UNSEALED_PROD_BY` and `CRB_ALLOW_UNSEALED_PROD_REASON` (below). Factory builds are not covered: they always run on the host (below) |
| `CRB_BUILDER__IMAGE` | worker | the builder image (`deploy/Dockerfile.builder`), in the daemon's store. An explicit `CRB_BUILDER__EXECUTOR=docker` without it fails at start-up; the `prod` default without it fails each build closed (`sandbox unavailable`), never on the host |
| `CRB_ALLOW_UNSEALED_PROD` | api, worker | `1` lets `prod` start with the host builder or the local test executor — **for an evaluation you have decided not to count as evidence**. Without it both processes refuse to start and say which setting is unsealed. In `prod` it must name who set it and why (`CRB_ALLOW_UNSEALED_PROD_BY`, `CRB_ALLOW_UNSEALED_PROD_REASON`, below), or neither process starts. With it the API logs a warning, `/health` and `/settings` report `posture.unsealed_prod_override: true`, the Posture page says so to every viewer, and the worker stamps `unsealed_prod_override` into every run's apparatus and every evidence pack (ADR-0023). Without it a `prod` worker also refuses a run that asks for the local executor in its own parameters, and refuses every **factory** run: a factory build hands the builder a host worktree and no container, so it is never sealed (`posture.factory_builds: refused`). With it a factory run builds on the host and its apparatus carries the override (`run_kind: factory`) |
| `CRB_ALLOW_UNSEALED_PROD_BY` | api, worker | with `CRB_ALLOW_UNSEALED_PROD=1` in `prod`, **required**: the username of the admin who decided to run unsealed (a local username, the identity provider's subject or the account's email). At every start each process checks it names exactly one active admin — otherwise it refuses to start and writes nothing (the worker exits 2) — and writes one `posture.unsealed_override` event on the audit trail whose actor is that admin, with the reason, the process, the host and the posture it admits ([API.md § Event vocabulary](API.md#event-vocabulary); ADR-0023 as amended). The worker stamps the name beside the override (`unsealed_prod_override.acknowledged_by`) on every run that does not run sealed: every run of a worker whose defaults are unsealed, a run that asks for the local executor in its own parameters, and every factory run. Name a person with an admin account: a deployment whose only admin is the bootstrap account names that account |
| `CRB_ALLOW_UNSEALED_PROD_REASON` | api, worker | with `CRB_ALLOW_UNSEALED_PROD=1` in `prod`, **required**: why, in the admin's words — written into the same event |
| `CRB_METRICS_ENABLED` | api, worker | `true` (default). `false` → the api's `/metrics` answers 404 and the worker starts no exposition |
| `CRB_METRICS_HOST` | worker | the address the worker's exposition binds (default `127.0.0.1`, like `CRB_BIND_HOST`: the series name repositories, builders and installations, so a bare `crb worker` on a host offers them to nobody else). Compose and Helm set `0.0.0.0` inside the container, where only the compose network / the NetworkPolicy's scraper can reach the port (§9.1) |
| `CRB_METRICS_PORT` | worker | the worker's own Prometheus exposition port (default `9464`; `0` = off; `auto` = a free port the operating system picks, reported in `/health`'s `worker` probe and in the worker's log — for a second stack on one machine, §1.2) — the build / grade / cost / delivery series live here, not on the api (§9). A port the worker cannot bind never stops it: `/health` reads the worker `degraded` and names the port, the reason and the fix |
| `CRB_BUILDER__LOGIN_TTL_S` | api, worker | how long a builder login's last verification stands, in seconds (default `600`, 30–86400). A build run whose builder's login failed its verification within it is refused `builder_login_invalid` before it is queued, and a run already queued is failed by the worker at claim, before any build (set it the same for both); past it, the next submit verifies the login once first (one no-tool Haiku turn). The `builders` probe reads the same state and never verifies (docs/API.md, "Builders") |
| `CRB_LOG_FORMAT` / `CRB_LOG_LEVEL` | api, worker | `json` (default, one object per line) or `text`; `INFO` — every record is redacted before a handler sees it (§9) |
| `CRB_WORKER_HEARTBEAT_STALE_S` | api | seconds after which a *running* run's heartbeat is reported stale by `/health` (default 120). Worker liveness itself is judged against each worker's own `heartbeat_s` (§9) |
| `CRB_SANDBOX__IMAGE` | worker | default sandbox image when a repository config has none (a repository's own `sandbox_image` wins). The shipped reference images — `deploy/sandbox/Dockerfile.{python,node,go}`, built and smoked by CI — are what to push to your registry and name here (`deploy/sandbox/README.md`); the worker never pulls (`docker run --pull=never` **[measured — `tests/test_execution.py::test_docker_build_argv_has_every_hardening_flag` pins the flag on the argv; `tests/test_sandbox_images_docker.py::test_an_absent_image_fails_closed_without_a_pull` proves an absent image is `SandboxUnavailable` (exit 125, `No such image`) against a daemon, colima / Docker 29.5.2; apparatus 2.2]**), so the image must be in the daemon's store |
| `CRB_SANDBOX__TREE` | api, worker | `copy` (default): tests run in a throwaway tmpfs copy of the worktree, which is mounted read-only at `/src` (ADR-0019 §7); `readonly`: the worktree itself read-only at `/work` — a different posture, qualified separately. It applies whether or not the worker has a default image (`CRB_SANDBOX__WORK_SIZE` too), and any other value stops the worker at start-up |
| `CRB_SANDBOX__WORK_SIZE` | api, worker | size cap of the throwaway copy (default `1g`; a tmpfs, so it counts against the sandbox's memory). A tree that does not fit is `env_error: tree_copy_failed`, never a verdict |
| `CRB_PROVISION__ENABLED` | api, worker | dependency provisioning (ADR-0019, §3.4 below). `false` (default): under docker a repository that declares dependencies is refused `PROVISION_DISABLED` before any spend. `true`: each task's dependencies are fetched outside the test container, sealed and mounted read-only |
| `CRB_PROVISION__STORE` | worker | where sealed sets live (default `$CRB_HOME/deps`); must be a path the docker daemon can bind-mount (`crb doctor` proves it) |
| `CRB_PROVISION__GO_PROXY` / `__GO_SUMDB` | worker | the Go proxy (one URL, never `direct`; `file://<dir>` = an air-gapped mirror, fetched with no network) and the checksum database (`off` for a mirror) |
| `CRB_PROVISION__PYPI_INDEX` / `__PYPI_FILES_HOST` | worker | the Python simple index (`file://<dir>` = air-gapped) and the host its files come from |
| `CRB_PROVISION__NPM_REGISTRY` | worker | the npm registry (every lock entry's `resolved` host must be this one); `file://<dir>` = a pre-populated npm cache, air-gapped |
| `CRB_PROVISION__EXTRA_ALLOW_HOSTS` | worker | more `host[:port]` entries for the fetch's proxy (a CDN your mirror redirects to); parsed at start-up |
| `CRB_PROVISION__ALLOW_PUBLIC` | api, worker | `false` (default): with `CRB_ENV=prod` a public registry (proxy.golang.org, sum.golang.org, pypi.org, files.pythonhosted.org, registry.npmjs.org) is refused at start-up (`PROVISION_PUBLIC_REGISTRY`) |
| `CRB_PROVISION__GO_IMAGE` / `__PYTHON_IMAGE` / `__NODE_IMAGE` | worker | the fetch images; default the sandbox images' own bases, pinned by digest. In prod a reference without `@sha256:` is refused (`PROVISION_FETCH_IMAGE_UNPINNED`); pre-pull them (the worker never pulls) |
| `CRB_PROVISION__PROXY_IMAGE` / `__EGRESS_NETWORK` | worker | the image the fetch's allowlisting proxy sidecar runs on (needs `python3`; default the builder's proxy image) and the docker network it reaches the registry on (default `bridge`) |
| `CRB_PROVISION__MIRROR_CREDENTIAL_ENV` | worker | the NAME of a worker environment variable that holds your private mirror's credential as `user:password` (for example `CORP_MIRROR_AUTH`, set from your secret store) — never the credential itself, which is refused at start-up. Only a networked fetch to a registry that is not public carries it, written inside the fetch container to the file its toolchain reads (`.netrc` for pip and Go, `.npmrc` for npm); a test container and a builder never receive it ([SECURITY §3.1.1](SECURITY.md#311-dependency-provisioning--crbcoredeps-crbprovision-adr-0019)). A named variable that is not set stops the fetch with the variable's name |
| `CRB_PROVISION__CA_BUNDLE` | worker | a CA bundle for a TLS-intercepting mirror, mounted read-only into the fetch |
| `CRB_PROVISION__MAX_BUNDLE_MB` / `__MAX_TOTAL_GB` / `__FETCH_TIMEOUT_S` | worker | one set's size cap (`PROVISION_TOO_LARGE`, default 2048), the store's cap for `crb deps gc` (default 20) and a fetch's wall clock (default 900 s) |
| `CRB_FACTORY__REQUIRE_SIGNED_CELL` | api, worker | **true** (the default): the factory builds an item only when its cell's proven context standard carries an active sign-off — made on the standard's arm, class-set version and reading, on the current apparatus, posture class and checks arm (ADR-0018 as amended by ADR-0026 item 8) — in every cell the size rule reads. An item in an unsigned cell stops **before any spend** with status `unsigned_cell`: nothing is authored, built or reviewed. `false` removes this clause only, never the entry gate; the posture is served on `GET /settings` and the Posture page's **Delivery licence** row, and the Factory screen predicts each item under whichever is in force. Either way a second approver — never the person who queued the run — may lift this clause for one run (`POST /runs/{id}/deliver-override`), which is recorded under their name, never lifts the route and is never an attestation |
| `CRB_FACTORY__TEST_AUTHOR` | api, worker | the factory's test-author rung — `builder:model[:provider]`, the same spelling as a build rung, or empty / `none` (the default) for no author. With no author, an item nobody wrote a failing test for stops `no_oracle`; with one, that rung writes the test. **The author rung and the build rung are never the same rung**: a label that is also on a run's ladder is refused before anything is built. A run may override it (`POST /runs {test_author}`). The author calls the same OpenAI-compatible endpoint as the builders (`CRB_OPENAI_BASE_URL` below) and stamps its provider; an author rung naming a different provider is refused before any call (OPERATOR §10) |
| `CRB_RETENTION__TRANSCRIPTS_DAYS` | | 0 = keep no builder transcripts (default) |
| `CRB_OPENAI_BASE_URL`, `CRB_OPENAI_KEY_ENV` + the named key var | builder | the OpenAI-compatible endpoint (vLLM, llama-server, Cerebras, …) that **every** OpenAI-compatible builder calls — `editblock`, `openai_agent`, the intent labeller and the factory's test author — defaulting to Cerebras (`https://api.cerebras.ai/v1`, key in `CEREBRAS_API_KEY`) when unset. The provider a row is stamped with is the endpoint's own: `cerebras` for a host in the `cerebras.ai` domain, `azure` for an Azure endpoint in an Azure domain (`azure.com`, `azure-api.net`, `azure.us`, `azure.cn`), otherwise the URL's host and port (`gpu-box.internal:8080`) — and a host with no dot and no port is stamped `host:<name>`, so a service called `cerebras` is never stamped `cerebras`. A URL carrying a user name or key before the host, a query string or a fragment is refused by name, because the URL is stamped on every row — the key goes in the variable `CRB_OPENAI_KEY_ENV` names. A rung that names a different provider (`openai_agent:qwen@cerebras` while the URL is your server) is refused when the run is submitted (422 `builder_provider_mismatch`, nothing queued) and again before anything is built, so a self-hosted model's results never land in another provider's cell; name the host (`@gpu-box.internal:8080`) or leave the provider empty **[measured — n = 64 test cases in `tests/test_builders_endpoint.py`: 10 point a builder, the labeller or the test author at a fake OpenAI-compatible server on 127.0.0.1 and assert the request lands there and the row (or the authored test's record) carries its host; the other 54 check the settings, the provider rule and the refusals; each fix was reverted in turn and the tests failed; apparatus 2.3]**. Until 2026-09-25 (`product.truth.26` in docs/dod/product.md) the two builders ignored this variable and called Cerebras, and stamped `cerebras` on every row |
| `CRB_OPENAI_TIMEOUT_S` / `CRB_OPENAI_MAX_TOKENS` / `CRB_OPENAI_MAX_RETRIES` | builder | per-call timeout in seconds (default `120`, 1–3600), the completion's `max_tokens` (default `4000`, 1–200000; while it is unset the intent labeller keeps its own cap of `400`) and how many times a timed-out or 429/5xx call is retried (default `4`, 0–10). A value out of range or not a number stops the builder with an error that names the variable — never silently clamped. A self-hosted model is slower than a hosted one: at 15 tokens a second a 4,000-token reply needs about 270 s **[hypothesis — arithmetic from a stated generation rate, not measured on a model]**, so raise the timeout above that and set retries to `0` or `1`, because every retry regenerates the whole reply |
| `CRB_AZURE_ENDPOINT`, `CRB_AZURE_DEPLOYMENT`, `CRB_AZURE_API_VERSION`, `CRB_AZURE_KEY_ENV` + `AZURE_OPENAI_API_KEY` | builder | Azure OpenAI in-tenant (setting the endpoint selects Azure) |
| `ANTHROPIC_API_KEY` | builder | Claude Code builder in its production `api_key` auth mode (`claude -p --bare`) |
| `CRB_CLAUDE_CODE_AUTH` | builder | default auth mode for `claude_code` rungs when the run's `builder_config` does not set `auth`: `api_key` (default) or `cli` — **developer/evaluation only**: the worker's user's own `claude login` (subscription) is the credential, `--bare` is dropped and the target repository's `CLAUDE.md` is auto-discovered (see SECURITY.md) |
| `CRB_CLAUDE_CODE_MODEL` | api, builder | default model for a `claude_code` run created without one (`claude-sonnet-5` when unset; read by the API at run creation and by the adapter at instantiation) |
| `CRB_ALLOW_LOCAL_CLONE` | api, worker | `1` lets URL registrations use `file://` sources — **test and developer machines only**; never set it on a server |
| `DOCKER_HOST` | worker | set by Helm for the `dind`/`hostSocket` sandbox modes |

### 2.2 The released image: name, signature, SBOM

You should not build the image yourself. Every `v*` tag runs `.github/workflows/release.yml`,
which builds `deploy/Dockerfile` (UI bundle + the package installed non-editable), smokes
the result (non-root uid 10001, read-only root, `migrate upgrade` on SQLite, UI and tools
present), generates an SBOM, and only then pushes:

| | |
|---|---|
| Repository | `ghcr.io/jita81/commit-replay-bench` (private GHCR package; the same string is the Helm `image.repository` default and `CRB_IMAGE` in compose) |
| Tags | `<version>` — the git tag without its `v` (`v2.0.0a1` → `2.0.0a1`); `sha-<7-char sha>` — the same bytes by commit. No `latest`. |
| Platform | `linux/amd64`. Build locally (`docker buildx build --load -f deploy/Dockerfile .`) for arm64 evaluation machines. |
| Provenance | SLSA provenance (`mode=max`) and a BuildKit SBOM attestation in the image index (`docker buildx imagetools inspect <ref> --format '{{ json .Provenance }}'`). |
| SBOM | syft, SPDX 2.3 JSON, of the exact smoked image: attached as a cosign in-toto attestation (`--type spdxjson`) and uploaded as the `crb-image-sbom-<tag>` artifact of the release run (365-day retention). |
| Signature | cosign **keyless**: the GitHub Actions OIDC token of the release workflow → a short-lived Fulcio certificate → recorded in the Rekor transparency log. There is no signing key to rotate, leak or escrow. |
| Signing identity | `https://github.com/Jita81/commit-replay-bench/.github/workflows/release.yml@refs/tags/v…`, issuer `https://token.actions.githubusercontent.com`. Forks, branches and manual dispatches build the image but never push or sign. |

Verify — and pin the digest — before the image reaches a cluster or a host. The package
is private: `docker login ghcr.io` with a token carrying `read:packages` first (cosign
uses the same credentials to read the signature); for a cluster, `imagePullSecrets` in the
Helm values, or mirror into your own registry (below).

```bash
deploy/verify-image.sh 2.0.0a1 --sbom sbom.spdx.json          # cosign ≥ 2, jq
cosign triangulate --type digest ghcr.io/jita81/commit-replay-bench:2.0.0a1
#   → ghcr.io/jita81/commit-replay-bench@sha256:…  ← image.digest (Helm) / CRB_IMAGE (compose)
deploy/verify-image.sh 2.0.0a1 --digest sha256:…                # later: the tag still resolves to your pin
```

`deploy/verify-image.sh --print` shows the exact `cosign` invocations so a security reviewer
can read what is accepted: only a signature whose certificate identity matches the release
workflow **on a `v*` tag** of the canonical repository. Anything else fails verification.
The script, the workflow and the Helm values are held to the same repository, issuer and
identity by `tests/test_release_verify_image.py`.

Mirroring into your own registry (§4.3, §7): verify first, then
`cosign copy ghcr.io/jita81/commit-replay-bench:2.0.0a1 <acr>.azurecr.io/crb:2.0.0a1` —
it copies the image index **with** its signature and attestations and keeps the digest, so
`cosign verify` against the mirror's reference resolves the same Rekor entry. `docker pull`
+ `docker push` does neither (signatures are sibling OCI artifacts it does not carry, and a
re-push can change the index digest); `crane copy` keeps the digest but not the signature.
Admission control (Kyverno / Gatekeeper / Azure Policy) can enforce the same identity
regexp cluster-wide so an unsigned or mis-signed image cannot be scheduled.

Compose users: `CRB_IMAGE=ghcr.io/jita81/commit-replay-bench@sha256:…` in `deploy/.env`,
then `docker compose pull` and `up -d` without `--build`
([deploy/README.md §1.1](../deploy/README.md#11-use-the-released-image-instead-of-building)).

## 3. Kubernetes (Helm)

### 3.1 Install

```bash
kubectl create namespace crb
# 1. the Secret (or let External Secrets / Key Vault CSI create it — §4.2)
kubectl -n crb create secret generic crb-secrets \
  --from-literal=CRB_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=CRB_DATABASE_URL='postgresql+psycopg://crb:<pw>@<server>.postgres.database.azure.com:5432/crb?sslmode=require' \
  --from-literal=CRB_BOOTSTRAP_ADMIN__PASSWORD='<≥ 12 chars>' \
  --from-literal=CRB_OIDC__CLIENT_SECRET='<app registration secret>' \
  --from-literal=AZURE_OPENAI_API_KEY='<key>'
# 2. values
cat > crb-values.yaml <<'EOF'
image: { repository: <acr>.azurecr.io/crb, digest: "sha256:…" }
config:
  CRB_OIDC__ISSUER: https://login.microsoftonline.com/<tenant-id>/v2.0
  CRB_OIDC__CLIENT_ID: <app (client) id>
  CRB_OIDC__REDIRECT_URL: https://crb.example.internal/api/v1/auth/oidc/callback
  CRB_TRUSTED_PROXIES: 10.240.0.0/16          # ingress controller pod CIDR
  CRB_AZURE_ENDPOINT: https://<aoai>.openai.azure.com
  CRB_AZURE_DEPLOYMENT: gpt-4o
  # the deployment default for repositories that name no sandbox_image: one of the shipped
  # reference images (deploy/sandbox/README.md), pushed to your registry and pinned by digest;
  # a repository of another toolchain names its own (`crb repo add --sandbox-image …`)
  CRB_SANDBOX__IMAGE: <acr>.azurecr.io/crb-sandbox/python@sha256:<digest>
worker:
  sandbox: { mode: dind }
  nodeSelector: { crb.dev/pool: worker }
  tolerations: [{ key: crb.dev/worker, operator: Exists, effect: NoSchedule }]
# the default secretsStore claim (ReadWriteOnce) puts the api on the worker's node, so the api
# needs the same placement; the chart refuses a difference (§3.2)
api:
  nodeSelector: { crb.dev/pool: worker }
  tolerations: [{ key: crb.dev/worker, operator: Exists, effect: NoSchedule }]
networkPolicy:
  postgres: { cidrs: ["10.10.1.4/32"] }        # Flexible Server private endpoint
  modelEndpoint: { cidrs: ["10.10.2.4/32"] }   # Azure OpenAI private endpoint
  oidc: { cidrs: ["10.10.3.4/32"] }            # egress proxy / firewall for login.microsoftonline.com
  extraEgress:
    - to: [{ ipBlock: { cidr: 10.10.4.4/32 } }]   # ACR private endpoint (the dind sidecar's pre-pull of the sandbox images; the worker itself never pulls)
      ports: [{ protocol: TCP, port: 443 }]
ingress:
  enabled: true
  className: nginx
  host: crb.example.internal
  tls: { enabled: true, secretName: crb-tls }
EOF
# 3. install — the migrate Job runs first as a pre-install hook
helm upgrade --install crb deploy/helm/crb -n crb -f crb-values.yaml --wait
```

`helm --wait` returns only when the migrate Job succeeded and the api/worker pods are
ready. The chart renders **no** secret values: `existingSecret` is referenced by name, and a
secret-looking key placed under `config` fails the render.

### 3.2 What the chart hardens by default

`runAsNonRoot` 10001, `readOnlyRootFilesystem`, all capabilities dropped, `RuntimeDefault`
seccomp, no service-account token mount, default-deny NetworkPolicy for every crb pod with
explicit allowlists (DNS; ingress-controller → api; api/worker/migrate → PostgreSQL;
worker → model endpoint; api → OIDC), resource requests/limits on every container, a
`Recreate` strategy for the worker (it owns its RWO work volume), and a PVC with
`helm.sh/resource-policy: keep` so worktrees survive an uninstall. The stored credentials
(Settings → Claude Code login, the tracker token) live in `secretsStore`: one claim that the
API, which writes them and checks them when a run is submitted, and the worker, which reads
them at build time, both mount at `CRB_SECRETS_DIR` (`/srv/crb-secrets/store`). The default
ReadWriteOnce claim pins both pods to one node; name a ReadWriteMany claim of your own
(`secretsStore.existingClaim`, `secretsStore.accessMode: ReadWriteMany`) to lift the pin.
Because of the pin, the api must be able to run wherever the worker runs: with a
ReadWriteOnce claim the chart refuses to render unless `api.nodeSelector`,
`api.tolerations` and `api.affinity` are the same as `worker.nodeSelector`,
`worker.tolerations` and `worker.affinity`. Affinity counts as placement: a worker kept on
its pool by required node affinity (rather than a node selector) would otherwise follow an
api scheduled on a general node that its own rule forbids, and stay pending; pod affinity
and pod anti-affinity can forbid a node in the same way. The chart compares your values
before it adds its own pin. Matching values are not enough on their own: a required pod
anti-affinity that selects the api or the worker (a chart label such as
`app.kubernetes.io/component` or `crb.dev/secrets-store`, or one of your `podLabels`) forbids
the node the pin puts both pods on, whatever its topology key, so the chart refuses it too.
Make such a rule preferred, or use a ReadWriteMany claim. A worker on the dedicated, tainted pool of §4.4 therefore takes
the api with it (the example in §3.1), or the store moves to a ReadWriteMany claim on a file system that keeps POSIX
permissions (the store refuses a directory that its group can read).
The claim has no `keep` policy, so a stored credential does not outlive the release.
The kept patches, the evidence packs and the retained transcripts live in `evidenceStore`:
one claim that the worker, which writes them at grade time, and the API, which serves them
at `/grades/{row_hash}/patch` and `/grades/{row_hash}/transcript`, both mount at
`$CRB_HOME/evidence` and `$CRB_HOME/transcripts` (P-045). It follows the secrets store's
placement rule: a ReadWriteOnce claim pins both pods to one node, and only ReadWriteMany
claims for both stores lift the pin (`evidenceStore.existingClaim`,
`evidenceStore.accessMode: ReadWriteMany`). Unlike the secrets store it carries
`helm.sh/resource-policy: keep`: the kept patches are the product's retained output, so
delete the claim explicitly.
The chart also refuses an `api.podLabels`, `worker.podLabels`, `api.podAnnotations` or
`worker.podAnnotations` key that it sets itself (the pin's `crb.dev/secrets-store` label,
the selector labels, `checksum/config`): the pod would carry the key twice.

### 3.3 PostgreSQL

`postgresql.mode: external` (default) — `CRB_DATABASE_URL` in the Secret points at a
managed server; use `sslmode=require` (or `verify-full` with the CA) and a private endpoint.
`postgresql.mode: embedded` renders a single-replica StatefulSet (`postgres:16-alpine`, uid
70, read-only root) for **evaluation only** — no HA, no PITR, no managed backups.

**Do not let the application own the ledger.** On PostgreSQL the role that owns a table may
disable, drop or re-create its triggers, so a deployment whose API and worker connect as the
tables' owner holds append-only only against its own good behaviour (DL-081). Where your
platform allows a second role, split them:

- the **owner** runs `crb migrate` (the migration job) and owns every table and the
  `crb_append_only()` function;
- the **application** role — the one in the API's and the worker's `CRB_DATABASE_URL` — is
  granted `SELECT, INSERT` on the append-only tables, `SELECT, INSERT, UPDATE, DELETE` on
  the rest, only `SELECT` on `alembic_version` (only the owner migrates, so only the owner
  records the schema's version), and `USAGE, SELECT` on the sequences:

```sql
-- as the owner, after `crb migrate` has created the schema
CREATE ROLE crb_app LOGIN PASSWORD '<secret>';
GRANT CONNECT ON DATABASE crb TO crb_app;
GRANT USAGE ON SCHEMA public TO crb_app;
GRANT SELECT, INSERT ON grades, events, signoffs, evidence, reviews, task_qualifications,
  library_acts, class_set_acts, class_labels TO crb_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON repos, runs, tasks, users, invitations,
  decisions_due, workers, github_installations TO crb_app;
GRANT SELECT ON alembic_version TO crb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO crb_app;
-- tables and sequences the owner creates later (a release that adds a table)
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT ON TABLES TO crb_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO crb_app;
```

The default grants apply to what the owner creates, so run them as the owner. A table a
later release adds gets the narrower grant, `SELECT, INSERT`, so a new table is never
rewritable by the application before someone has decided it may be. When a release adds a
table the application must update or delete, its upgrade notes name it: grant `UPDATE,
DELETE` on that table as the owner before you restart the API and the worker, or those
writes are refused with `permission denied`.

(`SELECT tablename FROM pg_tables WHERE schemaname = 'public'` lists every table; the
append-only ones are `APPEND_ONLY_TABLES` in `src/crb/store/models.py`.) The API and the
worker then start with no DDL: `init_db` re-creates only a trigger that is not live, and a
store whose triggers are all live gets none. The application role cannot `TRUNCATE`,
disable, drop or redefine anything, nor issue the table DDL that rewrites or removes rows
with no trigger firing (`ALTER TABLE … ALTER COLUMN … TYPE … USING`, `DROP COLUMN`, `DROP
TABLE`) — on a single-role deployment the application IS the owner and can. A trigger that
is missing, disabled or re-created with any definition other than the installer's (a `WHEN`
that never holds) makes `/health`'s `append_only` probe `down` with its name in
`data.missing`. Where the application owns the tables (a single-role deployment, and SQLite)
the next start re-creates it. With the roles split, the application role cannot: its start
is refused (`permission denied`), so restore the trigger as the owner with `crb migrate`
(`CRB_DATABASE_URL=<owner URL> crb migrate`) before you restart the API and the worker. The
proofs are
`tests/test_store_db.py::test_an_application_role_that_does_not_own_the_tables_cannot_remove_the_protection`
and
`tests/test_store_db.py::test_a_trigger_missing_on_a_split_role_store_is_restored_by_the_owner_not_the_application`,
run on PostgreSQL in CI.

The chart and the compose file still give the migration job, the API and the worker one
`CRB_DATABASE_URL` [gap] G-709: run `crb migrate` as the owner yourself before each
install or upgrade (`CRB_DATABASE_URL=<owner URL> crb migrate`), and put the application
role's URL in the Secret. The chart's migration hook then finds the store at head, issues no
DDL and passes; an upgrade whose migration the owner has not run fails at that hook, before
any pod changes.

### 3.4 The worker's sandbox — choose deliberately

The worker creates one hardened container per test command (`--network=none --read-only
--cap-drop=ALL --user 65534`). It therefore needs *a* Docker daemon. Without one the
executor fails **closed**: runs are recorded `failed` (`sandbox unavailable: …`), nothing
executes on the node
([OPERATOR.md §7](OPERATOR.md#7-when-the-sandbox-is-unavailable)).

| `worker.sandbox.mode` | Mechanism | Blast radius | Use when |
|---|---|---|---|
| `none` (default) | — | none; every run fails closed (`failed`, `sandbox unavailable`) | until you have decided |
| `dind` | `docker:dind` sidecar in the worker pod, unix socket on a shared in-memory emptyDir, image store on an emptyDir | the **pod** — the sidecar is `privileged`, but it is the only privileged container and it never touches the node's runtime socket. Sandbox images are pulled by the sidecar (allow the registry in `extraEgress`) | the recommended cluster mode; put the worker on a dedicated node pool anyway |
| `hostSocket` | `hostPath` mount of the node's `/var/run/docker.sock` + `supplementalGroups` | the **node** — socket access is root-equivalent | only with a dedicated, tainted node pool, a PodSecurity exemption for that namespace, and a written risk acceptance |

In every mode the worker's own container stays non-root, read-only and capability-less,
and `DockerSettings` refuses to mount the socket, `/` or `$HOME` into a sandbox.

**Which image runs in the sandbox.** `deploy/sandbox/` ships three reference images —
python (pytest), node (`node --test`), go — each digest-pinned **[measured — every `FROM`
in the three Dockerfiles carries `@sha256:…`, n = 4 `FROM` lines, by inspection; apparatus
2.2]**, uid 65534 both as the image's own default user and as the user the executor runs
**[measured — `tests/test_sandbox_images_docker.py`: the image config's `User` is `65534:65534`
and `id -u` inside prints 65534 with and without the executor, 2 tests × 3 images; apparatus
2.2]**, read-only-root compatible, hadolint-clean, and proven from inside by CI on every pull
request (the `sandbox-images` job runs each language's fixture repository through the real
executor on the image it just built) **[measured — `tests/test_sandbox_images_docker.py`, 10 tests × 3 images, plus the sandbox and sealed-builder suites on the python image, run as CI's `sandbox-images` smoke step (`-m "not network"`, strict warm-up, any skip fails the step): 47 passed / 0 skipped on images built from this tree, colima / Docker 29.5.2, 2026-09-22; the job runs that step on every pull request — PR #44 run 35678358686 on the merged head 4a64fe3, 44 passed / 0 skipped, before this commit added the setuid and strict-warm-up tests; hadolint on each Dockerfile in the same job; apparatus 2.2]**. Build them, push them to your registry, pre-pull them into the
daemon the worker talks to (the `dind` sidecar's store in that mode), and name them: the
deployment default in `config.CRB_SANDBOX__IMAGE`, a repository's own in its
`sandbox_image`. Everything else — build, tag, push, select, extend for a toolchain,
dependencies, the re-pin cadence — is [deploy/sandbox/README.md](../deploy/sandbox/README.md).
A JVM reference image is deliberately not shipped: the Maven runner's docker branch cannot
resolve plugins offline yet (README §6).

**Dependencies are provisioned per task, outside the test container (ADR-0019).** A test
container never has a network, so a repository's dependencies cannot be installed in it —
and an image that bakes them in serves one commit's lockfile only. Before this, the docker
posture could not build a Go repository with a third-party module and graded every attempt
against the model **[hypothesis, recorded as measured — n = 3 or 4 rows of run `0c44ff24…`
(cobra), each `builder_red` with the target red; method: the run's grade rows as read on
2026-09-25, neither read in this repository; apparatus 2.2. The count is disputed: 3 rows
were observed when the run was cancelled, and stream D read 4 from the deployment's ledger
export, which is not committed — [gap] F42]**. With `CRB_PROVISION__ENABLED=true`:

- the lockfiles at the parent and at the gold are read from git objects; a fetch container
  (the pinned toolchain image, the worker's non-root uid, read-only, no capabilities) fetches
  them through the allowlisting proxy to your registry hosts only — or with no network at all
  from a `file://` mirror — and never sees the source, a secret or `CRB_HOME`;
- the result is sealed under `CRB_PROVISION__STORE` (on the work volume; the `dind` sidecar
  sees it at the same path) and mounted **read-only** into the test container, which keeps
  `--network=none`: Go's modules at `/deps/gomod` with `GOPROXY=off` (one cache for the
  parent's and the gold's modules), Python's wheels (from a pinned requirements file, a `uv.lock`, a `poetry.lock` or a PEP 751
  `pylock.toml`, each read into the same pinned, hashed set; DL-110) installed with no network at
  `/deps/site`, Node's `node_modules` from `npm ci --ignore-scripts` at `/work/node_modules`;
- every stop is a code with a fix, served as `{code, message, fix, doc}`:

| Code | Scope | What to do |
|---|---|---|
| `PROVISION_DISABLED` | run | switch provisioning on (`CRB_PROVISION__ENABLED`), or measure the repository in the local posture |
| `PROVISION_PUBLIC_REGISTRY` | run | point `CRB_PROVISION__GO_PROXY` / `__PYPI_INDEX` / `__NPM_REGISTRY` at your mirror, or set `CRB_PROVISION__ALLOW_PUBLIC=true` |
| `PROVISION_FETCH_IMAGE_UNPINNED` | run | pin `CRB_PROVISION__{GO,PYTHON,NODE}_IMAGE` by digest |
| `PROVISION_STORE_NOT_VISIBLE` | run | put `CRB_PROVISION__STORE` where the daemon can bind-mount it (under colima: your home; under `dind`: the work volume) |
| `PROVISION_UNSUPPORTED_LANGUAGE` | run | JVM and Rust: the local posture only in this version |
| `PROVISION_NO_LOCK`, `PROVISION_UNPINNED`, `PROVISION_SOURCE_REFUSED`, `PROVISION_BUILD_REQUIRED`, `PROVISION_LOCK_UNSUPPORTED`, `PROVISION_PRIVATE_MODULE`, `PROVISION_TOOLCHAIN_TOO_OLD`, `PROVISION_FETCH_FAILED`, `PROVISION_TOO_LARGE`, `PROVISION_UNSAFE_OUTPUT`, `PROVISION_TREE_SHADOWS_SET` | task | a fact about that commit's lockfiles or the registry; the message names the file, the line, the host or the setting |
| `BUNDLE_INTEGRITY` | run | a sealed set no longer matches its digest. The run stops before any builder is called, moves the set to `<store>/.quarantine/<lang>/<key>.<time>` with a record of why (a `provision.quarantined` event), and revokes every qualification that cites it (`provision.revoked`); the damaged bytes are never mounted again and stay for whoever investigates. Run again with qualify first on and the set is fetched and sealed afresh. Between runs, `crb deps verify --quarantine` does the same (G-966). Nothing is deleted by hand |

Switch it on in this order: mirror the registries inside the tenant (or allow the public
ones deliberately), pre-pull the three fetch images and the proxy image into the worker's
daemon (`deploy/sandbox/README.md` §1), allow the mirror's address in
`networkPolicy.packageMirror.cidrs` (Helm; the fetch's sidecar is the only thing that reaches
it), set `CRB_PROVISION__ENABLED=true`, and read the `provision` line of `crb doctor` on the
worker host and the `provision` probe of the worker's `/health`: `ok` names the store and the
registries; `fail` names the code and the fix. `/health` reuses that probe for 5 minutes
when it is `ok` and for 30 seconds when it is not, so a readiness poll never starts a
container each time; `crb doctor` always probes afresh. How long a first fetch takes per repository
is not measured yet **[hypothesis — about 1 to 3 minutes per cobra task with a cold Go
build cache, extrapolated from run `0c44ff24…`'s attempt latencies; the first live qualify
run replaces this with a measured figure]**.

Every check a pull-request workflow reports — each workflow under `.github/workflows` whose
`on:` names `pull_request`: today `ci.yml` and `commit-subjects.yml` — blocks a merge to
`main` only while its name is on the branch's required-status-checks list, which is a
repository setting, not a workflow file. The list names every job's check those workflows had
when it was last read — `sandbox-images` (which has no `continue-on-error` and fails on any
skipped smoke test exactly as `container` does), `sbom`, `fresh-clone` (every gate on a fresh
clone from `uv.lock` as root with no docker daemon, DL-101) and `commit-subjects` among them —
except the parts an aggregator stands for (below): the test, fresh-clone and walkthrough
shards, `fresh-clone-gates` and `walkthrough-story`. It is strict (a branch must be up to date)
**[measured 2026-10-07 — n = 18 required checks against the 18 gating check names the
pull-request workflows rendered then, method: `scripts/check_branch_protection.py` against
`GET /repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks`,
saved as `data/branch-protection-2026-10-07/`, apparatus 2.3; the reading of 2026-09-27 had
the same list less `fresh-clone` and `commit-subjects`, which an administrator added on
2026-10-07]**. A job added before the administrator can require it may wait in the saved
reading (`tests/fixtures/branch_protection_main.json`) under `awaiting_protection`, with the
step that remains and an open gap in docs/dod that names it; none waits there now, and the
daily comparison against the live setting never honours the key (DL-101, P-269).

`scripts/check_branch_protection.py` compares the two both ways. It finds the pull-request
workflows by reading each file's `on:`, never from a list kept by hand, so a new workflow's
job is held to the setting the day it lands. It fails on a required check that no job of a
pull-request workflow reports (every pull request would wait on it for ever), such a job that
no required check names (it could fail and the change still merge), a required check that is
a part of an aggregator, a setting that is not strict, and a job name of 100 characters or
more. The daily
`branch-protection` workflow (`.github/workflows/branch-protection.yml`) runs it against the
live setting. Reading the setting needs a token with Administration: read, which a workflow's
own `GITHUB_TOKEN` can never be given, so an administrator adds a fine-grained token with that
one permission on this repository as the secret `BRANCH_PROTECTION_TOKEN`. Until then the
workflow fails, by design (G-930).

When a pull request adds or renames a job, the administrator changes the list before it
merges (a renamed job leaves its old name required, so the pull request waits until then).
`PATCH` replaces the whole list, so read it first and send all of it back:

```bash
gh api repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks \
  --jq '{strict: .strict, contexts: .contexts}' > required.json
# edit required.json: add or rename the check name exactly as its workflow renders it
gh api -X PATCH repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks \
  --input required.json
python scripts/check_branch_protection.py --repo Jita81/commit-replay-bench   # must say "match"
```

Then save the new reading as `tests/fixtures/branch_protection_main.json`: the test that
compares the last reading with the pull-request workflows fails on every pull request until
the two agree. To re-create the list from nothing, send the whole set:

```bash
gh api -X PATCH repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks \
  --input - <<'JSON'
{"strict": true, "contexts": ["lint (ruff)", "types (mypy --strict)", "layers (import-linter)",
 "code-map (every file has a valid header; docs/CODE-MAP.md is current)",
 "test (py3.12)", "test (py3.13)", "test-postgres (store suite on PostgreSQL 16)",
 "security (gitleaks + pip-audit)", "container (docker build + smoke + helm lint)",
 "walkthrough (browser, live stack, tier 1)",
 "ui-unit (tsc -b + vitest, the hint ratchet included)",
 "ui-smoke (mocked browser: axe on /login, the index redirect, the 404)",
 "dod (every route, journey and stream has its definition of done; evidence resolves)",
 "claims (every quantified sentence on a covered page carries its tag)",
 "sandbox-images (build + hadolint + smoke each reference sandbox image)",
 "sbom (CycloneDX)",
 "fresh-clone (every gate from uv.lock, as root, no docker daemon)",
 "commit-subjects (Conventional Commits, imperative, at most 72 characters)"]}
JSON
```

`test (py3.12)`, `test (py3.13)`, `walkthrough (browser, live stack, tier 1)` and
`fresh-clone (every gate from uv.lock, as root, no docker daemon)` are aggregators — each a
job that `needs` its parts and runs `if: always()`: the work runs in parallel parts
(`test shard (py3.12, 1 of 9)` …, the walkthrough story and its screens shards, the
fresh-clone gates and its shards) and the aggregator passes only when every part passed (a
failed, cancelled or skipped part fails it), the suite's parts together ran every test
exactly once, and, for `test`, the union's coverage is at least 70 % (P-051, P-053) **[measured — n = 4 aggregators; method: `scripts/check_branch_protection.py`'s `aggregated_parts` over ci.yml, pinned by `tests/test_ci_job_budget.py` and `tests/test_check_branch_protection.py`; apparatus n/a, a property of the product's own code, not a graded row]**. Never add a part to the list — its name changes
whenever the job is split differently, and the aggregator's does not;
`scripts/check_branch_protection.py` refuses a part on the list.

A context must be the check-run name EXACTLY, and GitHub truncates a check-run name at 100
characters — a `name:` longer than that can never satisfy the context it is required under
(it blocked PR #48 until its long job names were shortened). Keep every job's `name:` in a
pull-request workflow under 100 characters.

## 4. Azure

### 4.1 Entra ID → `CRB_OIDC__*`

Create an **app registration** (single tenant), a **web** redirect URI
`https://<host>/api/v1/auth/oidc/callback` (the route `GET /auth/oidc/callback` under the API prefix — `docs/API.md`), and a client secret (or a federated credential). Then:

| Entra ID | crb setting |
|---|---|
| Directory (tenant) ID | `CRB_OIDC__ISSUER = https://login.microsoftonline.com/<tenant-id>/v2.0` |
| Application (client) ID | `CRB_OIDC__CLIENT_ID` |
| Client secret value | `CRB_OIDC__CLIENT_SECRET` (in the Secret) |
| Redirect URI | `CRB_OIDC__REDIRECT_URL` |
| App roles (`crb.viewer`, `crb.operator`, `crb.approver`, `crb.admin`) assigned to users/groups | `CRB_OIDC__ROLE_CLAIM=roles`, `CRB_OIDC__ROLE_MAP={"crb.viewer":"viewer",…}` |
| …or security groups (needs the *groups* optional claim) | `CRB_OIDC__ROLE_CLAIM=groups`, map group object IDs → roles; `CRB_OIDC__ADMIN_GROUPS=<group-id>` |

Token configuration: add the `email` optional claim. Scopes default to
`openid profile email`. Unmapped users get `viewer`; there is no self-service elevation.

### 4.2 Key Vault → environment

Never write secrets into values files or the compose `.env` by hand in production. Two
supported paths:

* **External Secrets Operator** with an `AzureKeyVault` `SecretStore` (workload identity)
  and an `ExternalSecret` that materialises `crb-secrets` with the keys in §3.1. Rotation
  = rotate in Key Vault; ESO refreshes the Secret; roll the pods
  (`kubectl -n crb rollout restart deploy/crb-api deploy/crb-worker`).
* **Key Vault CSI driver** with `secretProviderClass` + `secretObjects` syncing to a
  Kubernetes Secret of the same name (the chart consumes the synced Secret; it does not
  mount files).

Set `serviceAccount.annotations: {azure.workload.identity/client-id: <uami>}` and the
`azure.workload.identity/use: "true"` pod label via `api.podLabels` / `worker.podLabels`.

### 4.3 Private endpoints and egress

* **PostgreSQL**: Azure Database for PostgreSQL Flexible Server, *public access disabled*,
  private endpoint in the AKS VNet, `sslmode=require`; its NIC IP goes in
  `networkPolicy.postgres.cidrs` — the chart REFUSES to render an external-postgres
  release without it (under default deny every pod would lose its database silently).
  Enable PITR (7–35 days) — this is the ledger's backup. **[hypothesis — the range is
  Azure's published retention for point-in-time restore; this product has not checked it]**
* **Azure OpenAI**: private endpoint + `privatelink.openai.azure.com` DNS zone; public
  network access disabled; NIC IP in `networkPolicy.modelEndpoint.cidrs`. Content
  filtering/abuse monitoring settings are your data-protection decision — record it in the
  DPIA.
* **Container registry**: ACR with a private endpoint; push the crb image *and* the sandbox
  images there; AKS pulls via the private link. In `dind` mode the sidecar also pulls from
  ACR — allow it in `networkPolicy.extraEgress`.
* **Cluster egress**: route the node pool through Azure Firewall / NAT with a deny-by-default
  policy; the only application-level destinations are the three above plus
  `login.microsoftonline.com` (use the `AzureActiveDirectory` service tag). NetworkPolicy in
  the chart is the second layer, not the only one.
* **Ingress**: internal load balancer (`service.beta.kubernetes.io/azure-load-balancer-internal`
  on the ingress controller), TLS from your internal CA or cert-manager.

### 4.4 Node pool for the worker

A dedicated, tainted pool (`crb.dev/worker=true:NoSchedule`) with the ephemeral OS disk sized
for sandbox image layers (≥ 128 GB) and `dind` storage; no other workloads. Runs are CPU
bound (2 CPU / 2 GB per sandbox by default): size the pool for the concurrency you want.

## 5. Backup and restore

State: the database (everything that matters, including the append-only `grades` /
`events` / `signoffs` / `evidence` tables), the worker's work volume (`worker.workDir`;
reproducible from the repositories, convenient to keep), the evidence store
(`evidenceStore`: the kept patches and the retained transcripts the API serves, §3.2; back
it up with the database — a row whose patch is gone can no longer be re-read or reviewed)
and the secrets store (`secretsStore`: the stored Claude Code login and the tracker token,
§3.2).

* **Secrets store**: choose one of two, and write the choice down.
  * Back the claim up with a volume snapshot (or a copy of `/srv/crb-secrets/store`) held
    with the same protection as the Kubernetes Secret — it holds live credentials — and
    restore it before the api and the worker start.
  * Or do not back it up, and after a restore supply the credentials again before the
    worker starts: Settings → Claude Code login, and the tracker token. The api refuses a
    new run whose builder has no credential when it is submitted, but that is the only
    check. The worker claims a run that was queued or running when the backup was taken as
    soon as it starts, and without the credential that run's attempts fail.

* **Managed PostgreSQL**: PITR is the primary backup; take a logical `pg_dump -Fc` before
  every upgrade and monthly for off-platform retention.
* **Compose**: `pg_dump` + tar of `/srv/crb` — commands in
  [deploy/README.md §4](../deploy/README.md#4-backup-and-restore).
* **Verify every backup**: the store's row count and last `row_hash` before and after a
  restore must be the same, read from the database itself
  (`SELECT count(*), max(seq) FROM grades; SELECT row_hash FROM grades ORDER BY seq DESC LIMIT 1;`),
  and `GET /api/v1/ledger/verify` on the restored API must read `chain intact, false_q1=0`
  with that count. A restore that changes either is not a restore; treat it as an incident.
  `crb ledger verify` walks the core JSONL ledger at `$CRB_HOME/ledger.jsonl`, not the
  database — it cannot prove a database copy.

There is one restore order for each choice. In both, ledger verify and the health probes
come after the pods start.

Restore order when the secrets store is restored: database (on an *empty* target) → work
volume → evidence store → secrets store → `migrate` (no-op at head; it re-asserts the triggers) → start the
api and the worker → ledger verify → the `migrations` and `append_only` probes on
`/api/v1/health`.

Restore order when the credentials are supplied again: database (on an *empty* target) →
work volume → evidence store → `migrate` (no-op at head; it re-asserts the triggers) → start the api alone
(`worker.replicaCount: 0`) → supply the credentials again through Settings → start the
worker (`worker.replicaCount` back to its value) → ledger verify → the `migrations` and
`append_only` probes on `/api/v1/health`.

### 5.1 Backup and restore (SQLite)

The single-host shape (§1.1) keeps everything in `CRB_HOME` and one SQLite file, and it
holds real sign-offs and ledger rows — back it up like the production store. A copy taken
while the worker writes can be torn; `sqlite3 .backup` copies a consistent snapshot even
so, but stopping the worker first is the simplest guarantee.

The proof that a copy is a backup reads the copy: SQLite's own `integrity_check`, the
`grades` row count and the last `row_hash`, taken from the file with `sqlite3`. (`crb ledger
verify` walks the core JSONL ledger at `$CRB_HOME/ledger.jsonl`, ignores `CRB_DATABASE_URL`
and passes an empty or torn `crb.db` — do not use it here.) The same three-line query on
the live file, the copy and the restored file must give the same count and hash; a torn or
empty file fails it with a non-zero exit (`database disk image is malformed`, `no such
table: grades`).

```bash
# 1. quiesce — no run in flight (the API may keep serving reads)
kill "$(cat ~/crb-stack/worker.pid)"                 # THIS stack's worker: the pid its start script
                                                   # recorded, or `systemctl stop crb-worker` /
                                                   # `docker compose stop worker` — never a host-wide
                                                   # `pkill`, which stops every crb stack's workers
CHECK='PRAGMA integrity_check; SELECT count(*), max(seq) FROM grades;
       SELECT row_hash FROM grades ORDER BY seq DESC LIMIT 1;'
sqlite3 ~/crb-stack/crb.db "$CHECK"                # record: ok, the row count, the last row_hash

# 2. copy: the store with SQLite's own online-backup API, then the home directories
STAMP=$(date -u +%Y-%m-%dT%H%M%SZ); DEST=~/crb-backups/$STAMP
mkdir -p ~/crb-backups && mkdir "$DEST"            # no -p: a second run in the same second
                                                   # fails here instead of overwriting the first
sqlite3 ~/crb-stack/crb.db ".backup '$DEST/crb.db'"
tar -C ~/crb-stack -czf "$DEST/home.tgz" \
  $(cd ~/crb-stack && ls -d home/evidence home/events home/factory home/transcripts home/secrets 2>/dev/null)

# 3. prove the copy is a backup, not a torn file
sqlite3 "$DEST/crb.db" "$CHECK"                    # ok, the same row count, the same last row_hash
chmod -R go-rwx "$DEST"                            # it carries the login token
```

Restore, in this order, onto an **empty** `CRB_HOME`: stop the worker and the API →
`sqlite3 ~/crb-stack/crb.db ".restore '$DEST/crb.db'"` (or copy the file into place) →
`sqlite3 ~/crb-stack/crb.db "$CHECK"` must report `ok`, the count and the last `row_hash`
you recorded at step 1 → `tar -C ~/crb-stack -xzf "$DEST/home.tgz"` →
`chmod 0700 ~/crb-stack/home/secrets` → `crb migrate` (a no-op at head; it re-asserts the
append-only triggers) → `crb doctor` → start the API and the worker →
`GET /api/v1/health` green → `GET /api/v1/ledger/verify` (signed in) reads
`chain intact, false_q1=0` with the same row count. A restore that changes the count or the
hash, or breaks the chain, is not a restore; treat it as an incident (§5).

What the tar holds: `home/evidence` (the evidence packs the ledger cites), `home/events`,
`home/factory` (the factory evidence chain — each repository's frozen backlog,
`evidence.jsonl` and gap sign-offs),
`home/transcripts` (retained builder transcripts; the review screen serves them from the
path on the grade row, and after a restore without them every transcript link answers
"not retained") and `home/secrets` (the login token — leave it out only if you are prepared
to sign in again). Clones under `home/repos` and retained worktrees under `home/scratch`
are reproducible from the repositories and are left out.

## 6. Upgrade

```bash
pg_dump … > pre-upgrade.dump                                   # always
deploy/verify-image.sh <new version>                           # signature + SBOM attestation (§2.2)
cosign triangulate --type digest ghcr.io/jita81/commit-replay-bench:<new version>   # → sha256:<new>
helm upgrade crb deploy/helm/crb -n crb -f crb-values.yaml --set image.digest=sha256:<new> --wait
```

The `pre-upgrade` hook runs `migrate upgrade` **before** any pod is replaced; on PostgreSQL
the migration is one transaction, so a failure leaves the previous schema and the previous
pods untouched and the release fails cleanly. `helm rollback` restores the previous
manifests; it does **not** downgrade the schema — the initial revision's `downgrade`
refuses while the ledger holds rows by design. Schema changes are forward-only and additive
on append-only tables (migration rules are in each revision's docstring).

**If revision `0004` refuses** (`refusing to upgrade 0004: events holds N duplicated
(trace_id, seq) pair(s)`): a database written by a release before 2.0.0a1's batch-2 fixes
can hold an out-of-band system event (a cancel request) and a worker event on the same
`seq` — the collision `0004` exists to forbid. Rows in `events` are append-only, so the
upgrade will not renumber them for you; it lists the pairs. The remedy is an explicit,
recorded operator action on a backup-first copy: for each pair, move the LATER row (the
higher `id`) to `max(seq) + 1` of its trace — `events` carries no hash chain, so the
row's content and its `event_id` are untouched and only its position in the SSE resume
order moves to the trace's end. On SQLite:

```sql
BEGIN;
DROP TRIGGER events_no_update;
UPDATE events SET seq = (SELECT MAX(seq) FROM events e WHERE e.trace_id = events.trace_id) + 1 WHERE id = <later id>;
-- …one UPDATE per pair…
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
COMMIT;
```

On PostgreSQL the same statements with `DROP TRIGGER events_no_update ON events` /
`CREATE TRIGGER events_no_update BEFORE UPDATE ON events FOR EACH ROW EXECUTE FUNCTION
crb_append_only()`. Record the ids you moved in your change log; then re-run `migrate
upgrade`. (The dev stack that produced the NHS measurement needed exactly three such
moves on 2026-09-16 — three `run.cancel_requested` notes that had collided with the
worker's next event **[hypothesis — as recorded when that stack was upgraded; its rows are
not in this repository, so the count cannot be re-derived here]**.)

**Upgrading to revision `0009`** (`users.session_nonce`): additive; every account keeps
its sessions. On a deployment whose cookies are `Secure` (the default outside
`CRB_ENV=dev`) the cookies are renamed `__Host-crb_session` / `__Host-crb_csrf`, so
everybody signs in once more after the upgrade. From this release, signing out ends the
account's sessions on every device.

**Upgrading to revision `0013`** (the audit trail's hash chain, ADR-0029): the revision
chains every event already stored, then makes the database refuse any event that does not
carry the chain — the two chain columns have no default and must each hold a SHA-256 **[measured — n = 1 revision; method: `tests/test_store_migrate.py::test_0013_refuses_a_row_from_the_release_before_it_and_keeps_recording` on SQLite and PostgreSQL; apparatus n/a, a property of the product's own code, not a graded row]**. The
release before it does not write the chain, so while its API and worker pods still run
(the `pre-upgrade` hook migrates before any pod is replaced; compose's `run --rm migrate`
runs before `up -d`) every event they try to write is refused, one at a time: a sign-in
answers 500, a run's steps are dropped from its log. Nothing already chained is harmed and
the new release writes normally. To avoid that window, scale the API and the worker to 0
before the upgrade (`kubectl -n crb scale deploy --replicas=0 -l
'app.kubernetes.io/instance=crb,app.kubernetes.io/component in (api,worker)'`, or
`docker compose stop api worker`); `helm upgrade` then starts them on the new release. A
`helm rollback` across `0013` leaves the previous release refused on every event, since
the schema is not downgraded: do not roll back across it — restore the pre-upgrade dump
instead.

**Upgrading to revisions `0014` and `0015`** (`invitations`, `decisions_due`): additive.
On a split-role PostgreSQL store (§3.3) both tables arrive with the default grant alone,
`SELECT, INSERT`, but the application updates both: accepting or revoking an invitation,
and every pass over the decisions inbox (`GET /decisions` and the worker's idle refresh).
As the owner, before you restart the API and the worker, grant them the rest:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON invitations, decisions_due TO crb_app;
```

Without it the application's `UPDATE` and `DELETE` on both tables are refused with
`permission denied` **[measured — n = 2 tables; method:
`tests/test_store_db.py::test_the_upgrade_notes_grant_lets_the_application_rewrite_each_later_table`
on PostgreSQL, a store granted as §3.3 read before revision `0014` and upgraded to head,
refused before the grant above and allowed after it; apparatus n/a, a property of the
product's own code, not a graded row]**, so accepting or revoking an invitation and reading
the decisions inbox fail, and the worker logs `decisions refresh failed` (P-754). If your
grants were made before §3.3 had its two `ALTER DEFAULT PRIVILEGES` lines (before
2026-09-28), run those as the owner too, and grant `SELECT, INSERT` on `library_acts`
(`0016`). On SQLite, or where the application owns its tables, there is nothing to do.

**Upgrading to the chart with the evidence store** (`evidenceStore`, P-045): before it, the
worker kept its kept patches, evidence packs and transcripts on its own work claim, at
`$CRB_HOME/evidence` and `$CRB_HOME/transcripts`. The new chart mounts the evidence claim
over those two paths, which would hide what the worker kept **[measured — n = 2 paths; method: the chart's worker template, pinned by `tests/test_deploy_evidence_store.py`; apparatus n/a, a property of the product's own code, not a graded row]**. So when `worker.workDir.type`
is `pvc`, the worker pod runs an init container, `evidence-carry`, before the worker starts:
it copies both directories from the work claim into the evidence claim once, then leaves a
marker (`.carried-from-work`) so later starts copy nothing. Nothing is deleted from the work
claim; once `/grades/{row_hash}/patch` serves a patch written before the upgrade, you may
remove the old directories from it. With `workDir.type: emptyDir` the worker kept nothing
across restarts, and no carry runs (`tests/test_deploy_evidence_store.py`).

Compose: `docker compose run --rm migrate check` → `run --rm migrate` → `up -d`
([deploy/README.md §5](../deploy/README.md#5-upgrade)).

## 7. Air-gap posture

crb never bundles a model and never phones home: no telemetry, no update checks, no
run-time pulls by the worker itself. The complete outbound list is: worker → model endpoint;
api → OIDC issuer; api and worker → the repository's git remote (clone, fetch, factory
delivery); api and worker → the GitHub API (the GitHub App's installations and tokens, a
delivery's pull request); (intake on) → the tracker it watches; the container runtime (the `dind`
sidecar in the chart) → your image registry;
(provisioning on, §3.4) worker fetch sidecar → your package mirror, sent only the package
names and versions the lockfiles pin. Sandboxes run with `--network=none`; a `file://`
mirror makes the fetch network-less too. To operate fully inside the tenant:

1. point the builder at an in-tenant endpoint — Azure OpenAI with a private endpoint (§4.3)
   or a self-hosted OpenAI-compatible server (`CRB_OPENAI_BASE_URL=https://vllm.internal/v1`,
   with `CRB_OPENAI_TIMEOUT_S` raised to the model's generation time — §2.1). Every
   OpenAI-compatible builder and the labeller call that URL, and their rows carry its host
   as the provider;
2. mirror the images (crb, sandbox, the three dependency fetch images, `docker:dind`,
   `postgres`) into your registry, and the package registries your repositories use into a
   mirror (or a `file://` directory) that `CRB_PROVISION__*` points at;
3. enforce deny-by-default egress at the cluster/host boundary and keep the chart's
   NetworkPolicy allowlists to those CIDRs only;
4. verify from a worker pod that a public address is unreachable while
   `/api/v1/health` reports the builder reachable.

## 8. Go-live checklist

Each line below is one of two kinds, and the product shows every line's state on the
Deployment page (`/posture`, read from `GET /api/v1/golive`) so a review board reads the state,
not a ticked list:

- **product proves** — the product runs the check itself each time the page is read. The
  line is *proven* while the check passes and *unproven*, with what failed, while it does not.
  Nobody can attest a line of this kind: an attestation cannot stand in for a check the
  product runs (`409 proven_by_product`).
- **operator attests** — only you can do it, on your own infrastructure. The product cannot
  see it, so it reads *unproven* until an admin records it on Settings → Go-live attestations
  (`PUT /api/v1/settings/attestations/{line}`): what was done, the day it was done, and the
  admin's name. It then reads *attested*, with that record, until someone withdraws it. Each
  record is one `golive.attested` event; nothing is ever edited.

**Not here.** Going live does not connect a repository ([ONBOARDING Step 1](ONBOARDING-A-REPO.md#step-1--register-the-repository-developer-30-minutes)),
recover an account ([OPERATOR §9](OPERATOR.md#9-users)) or measure anything; those are other
journeys. The product performs none of the *operator attests* acts below: the egress test, the
backup rehearsal, the digest check, the alert rules and the penetration test are yours.

- [ ] **`image-digest`** · operator attests — The running image is a released digest:
      `deploy/verify-image.sh <version> --digest sha256:<pinned>` passes (§2.2) and the
      digest is what `image.digest` / `CRB_IMAGE` says.
- [ ] **`health-green`** · product proves — `GET /api/v1/health` on the API is green: `db` answers, `migrations` reads
      `database at <rev> = code head` — its contract is
      [API.md — The `migrations` probe](API.md#the-migrations-probe): `ok` at head with a schema that matches the models; `degraded` (still served) at head with a schema that differs (each difference named in `drift`) and for an unstamped `create_all` schema that matches the head, until `crb migrate` stamps it; `down` (the endpoint answers 503) when the store is behind, ahead, empty or an older unversioned schema (crb tables, no `alembic_version`, fingerprints of a revision behind the head) — revisions named where applicable, with the fix — or when it cannot be read — the fixed detail `migrations could not be read — see the API log, request id <id>`, `data: {}`, the exception in the API log under that id. A half-migrated database cannot pass this
      line. `append_only` proves every trigger live on every append-only table and an
      UPDATE and a DELETE refused, in the trigger's own words, on each table that holds a row
      (on an empty table no write is tried), `ledger` reads `false_q1=0`, `builders`
      configured with its login `verified` (press Verify under Settings → Claude Code
      login once; a present login alone reads `degraded`), `worker` heartbeats fresh (`sandbox` is `skipped` on the API pod — the
      worker owns it; prove it with `crb doctor` on the worker host). The line is proven
      only while every probe is `ok` or `skipped`.
- [ ] **`doctor`** · operator attests — `crb doctor` on the API host and on the worker host: every line `ok`, or `warn` for a
      reason you have written down; no `fail`. It covers what `/health` cannot see from
      inside a pod — the GitHub App's installations, the secrets directory mode, the
      `CRB_HOME` location and the help bundle ([OPERATOR.md §1.1](OPERATOR.md#11-check-the-installation-crb-doctor)).
- [ ] **`ledger-role`** · operator attests — On PostgreSQL, the API and the worker connect as a role that does not own the ledger
      tables (§3.3) — or the reason your platform cannot is written down.
- [ ] **`ledger-verified`** · product proves — `GET /api/v1/ledger/verify` reads `chain intact, false_q1=0` with `events.chain_ok:
      true` (the audit trail's own chain, ADR-0029).
- [ ] **`row-hash-recorded`** · operator attests — Both heads `GET /api/v1/ledger/verify` serves —
      `head_row_hash` (the grade ledger's last `row_hash`) and `events.head_row_hash` — are
      recorded out of band: in the change record for go-live, and after that from the
      `ledger heads at worker start` line every worker start writes to the log store (§9.4).
      To check a store later, a recorded head must still be the `row_hash` of a row in the
      same chain (`GET /api/v1/ledger/export` for grades; `crb ledger verify --store --json`
      on the API host prints both heads) and the chain must verify: a store cut at its end
      or replaced wholesale fails this, though its own walk reads intact.
- [ ] **`sign-in`** · product proves — OIDC login works with a role-mapped user; `CRB_LOCAL_AUTH_ENABLED=false`; the
      bootstrap admin password has been rotated (`PUT /users/{id}/password`, or
      `crb users set-password <admin>` on the API host) or the account deactivated
      (`PUT /users/{id}/active {"active": false}` / `crb users deactivate <admin>` —
      possible once another active admin exists, for example the first OIDC sign-in
      from an `CRB_OIDC__ADMIN_GROUPS` member). A bootstrap admin kept active with local
      sign-in off is not a second admin: nobody can sign in as it, so the last-admin rule
      does not count it and the only OIDC admin still cannot be demoted or deactivated;
      `CRB_BOOTSTRAP_ADMIN__*` unset
      ([OPERATOR.md §9](OPERATOR.md#9-users)). The product proves it from what it holds:
      an organisation account has signed in (the live proof that OIDC works), local
      sign-in is off, no bootstrap admin is configured, and every active local admin has
      had its password set since it was created.
- [ ] **`egress-denied`** · operator attests — Egress test from a worker pod fails to any public address.
- [ ] **`repo-probe`** · operator attests — `crb repo probe <repo>` is green inside the sandbox for every configured repository.
- [ ] **`repos-qualified`** · product proves — Provisioning points at your mirror and `crb repo qualify` is green for every
      repository: the `provision` line of `crb doctor` on the worker host is `ok` (store
      visible to the daemon, fetch images present, egress network present), and each
      repository with dependencies qualifies in the sealed posture before its first replay.
      The product proves it while every connected repository has a task qualified in the
      posture now in force — its latest docker posture, the one the gate grades in; a task
      qualified only in an older posture (before a new image, say) does not count — and the
      `provision` probe is not `down`.
- [ ] **`backups-pitr`** · operator attests — Backups: PITR enabled; a restore has been rehearsed and verified against the chain.
- [ ] **`false-q1-alert`** · operator attests — `false_q1 == 0` and `crb_false_q1_total == 0` on the dashboards, with an alert on any
      non-zero value ([OPERATOR.md §8](OPERATOR.md#8-stop-conditions)). The zero itself is
      proven by `ledger-verified`; the alert rule is yours.
- [ ] **`login-rate-limit`** · operator attests — The reverse proxy limits `POST /api/v1/auth/login` per client address (for example
      ingress-nginx `nginx.ingress.kubernetes.io/limit-rpm: "20"` on a path-scoped ingress,
      or `limit_req` on `/api/v1/auth/login`). This is required: the product's own limiter
      (five failures a minute per username and address, twenty per address **[measured —
      n = 2 limits; method: the defaults of the sign-in rate limiter in the server's
      authentication module, read at this commit; apparatus n/a]**) lives in the
      memory of one API process, so it does not see the other replicas or survive a restart
      ([SECURITY §3.4](SECURITY.md#34-authentication-and-authorisation--crbserverauth)).
- [ ] **`sealed-posture`** · product proves — Tests and the builder both run sealed in docker
      (`CRB_SANDBOX__EXECUTOR=docker`, `CRB_BUILDER__EXECUTOR=docker`; §3.4 and ADR-0023).
      The settings alone prove nothing, so the product needs all three: the `posture` of
      `GET /api/v1/health` reads `sealed: true` with `factory_builds: refused` (a factory
      build runs its builder on the host, so a deployment that allows them is not sealed);
      and the last run the worker stamped ran its tests in docker with no unsealed override.
      A production worker whose builder is not docker starts only under
      `CRB_ALLOW_UNSEALED_PROD` and then stamps that on every run, so the stamp's absence is
      the builder measured. Until a run has been stamped the line reads unproven.
- [ ] **`penetration-test`** · operator attests — A penetration test of this deployment has been done and its findings handled
      ([SECURITY §5](SECURITY.md#5-what-this-document-does-not-claim) says what the
      documentation does not claim in its place).

### 8.1 Record what only you can prove

On Settings, the Go-live attestations card lists the *operator attests* lines. For each act
you have done, write what was done and where its evidence is kept (for example "egress to
1.1.1.1 from worker-0 timed out; transcript in change ticket CHG-1042"), give the day it was
done, and choose *Record attestation*. The Deployment page then shows the line as attested,
with your name, that day and your words. *Withdraw* ends an attestation that no longer holds
(a new image, a restore that failed); the line reads unproven again and the withdrawal is
itself on record. Only an admin can record or withdraw. The day of an act is your own
calendar day: it can be the day after the server's UTC day (east of UTC your morning is
still yesterday in UTC) but no later; and it cannot be more than a day before the
withdrawal it follows (the evidence that was withdrawn cannot come back) or before the day
the product saw this deployment installed, when it saw that — each bound gives a day's
slack, because your calendar and the server's differ by up to a day. Only an admin reads local admins' login
names on the sign-in line; everyone else reads how many.

**Time and money.** Nothing on this checklist starts a run, so Step 0 buys no attempts: it
spends £0 of model money. The one model call on the way is *Verify* on a stored Claude Code
token, a single no-tool turn that an admin chooses to make, billed to that token's own
subscription. On the single-host evaluation shape the machine's part took 8.5 seconds, from
`crb migrate` on an empty database to the first `/health` that answered **[measured — n = 1
boot; method: `scripts/walkthrough.sh --trace off` prints the wall clock from `crb migrate` to
the first answering `/health` (the API and the worker started on SQLite, a fresh
`CRB_HOME`), on the operator's 16 GB Mac mini on 2026-09-27; apparatus 2.3]**. **[gap]** A
Compose or Helm install, with the operator's own decisions, has not been timed (G-321).

## 9. Observability

Three surfaces: **metrics** (Prometheus, two expositions), **health** (`/health`, eleven
probes), **events** (the run's audit trail, streamed as SSE and stored in the `events`
table) **[measured — n = 11 probes and 2 expositions; method: the probes the readiness
route runs, counted in its code and held there by `tests/test_health_probe_docs.py`, and one
exposition per process that records metrics; apparatus n/a]**. Logs are JSON and redacted. Nothing here leaves the tenant.

### 9.1 Metrics — which process carries which series

The Prometheus registry is process-wide, so a series lives in the process that records it.
The api records the HTTP series, the ledger gauges and the sign-off counter; **the worker
records everything else and serves its own exposition** on `CRB_METRICS_PORT` (default 9464; `auto` picks a free
port and reports it in `/health` — a second stack on one machine, §1.2). A deployment
that scrapes the api alone sees `crb_false_q1_total`, `crb_ledger_rows`,
`crb_signoffs_total` and the HTTP series — every cost, run, belt and delivery counter reads as absent. Scrape both:

| Shape | api | worker |
|---|---|---|
| compose | `http://api:8000/api/v1/metrics` (published on `127.0.0.1:8000`) | `http://worker:9464/metrics` — the container sets `CRB_METRICS_HOST=0.0.0.0` and the port is `expose`d on the compose network only, never published; `CRB_METRICS_PORT=0` switches it off |
| Helm | Service `crb-api`, port `http`, path `/api/v1/metrics`; `serviceMonitor.enabled` | headless Service `crb-worker`, port `metrics` (one target per worker pod; the pod sets `CRB_METRICS_HOST=0.0.0.0`); `serviceMonitor.worker.enabled`; `worker.metrics.port` (0 = off); the NetworkPolicy admits `networkPolicy.metricsIngress` peers to that port only |
| one process (`crb serve` + `crb worker` on a host) | `/api/v1/metrics` | `127.0.0.1:9464/metrics` — loopback by default; a Prometheus on another host needs `CRB_METRICS_HOST=<the interface it may reach>` (or `0.0.0.0` behind a host firewall) — the series name repositories, builders, per-repository cost and installation ids |

The table is checked against the code by `tests/test_observability_metrics.py`: a metric
the module defines that is not here, or is here under other labels, fails the suite. A
series whose process is `worker` is served by the worker only: the api's exposition leaves
it out, so an alert on its absence (the no-worker rule below) fires when no worker is
scraped, and that suite fails if the api serves one.

| name | type | labels | process | meaning |
|---|---|---|---|---|
| `crb_runs_total` | counter | `kind, status` | worker | runs finished, by kind and terminal status (`succeeded`, `failed`, `cancelled`) |
| `crb_tasks_total` | counter | `repo, outcome` | worker | graded trials by outcome: `clean`, `not_clean`, `disqualified`, `error` |
| `crb_belt_failures_total` | counter | `belt` | worker | a belt that read `false` (`null` — not evaluated — is not a failure) |
| `crb_builder_tokens_total` | counter | `repo, builder, model, kind` | worker | builder tokens by direction (`kind ∈ in, out`) — per repository, the charge-back number |
| `crb_builder_cost_usd_total` | counter | `repo, builder, model` | worker | metered builder cost in USD. A floor, not a bill: an unpriced model adds 0 |
| `crb_grade_latency_seconds` | histogram | `runner` | worker | wall-clock seconds to grade one trial |
| `crb_build_latency_seconds` | histogram | `builder` | worker | wall-clock seconds for one builder attempt |
| `crb_sandbox_unavailable_total` | counter | — | worker | runs that stopped because the sandbox failed closed (ADR-0005) |
| `crb_deliveries_total` | counter | `repo, outcome` | worker | factory deliveries: `opened` (branch pushed, PR opened), `withheld` (the route gate refused), `failed` (the push or the PR call errored). Metered from the run's own `delivery.*` events |
| `crb_signoffs_total` | counter | `outcome` | api | sign-off decisions the API committed: `created` (an attestation written), `refused` (the policy refused it — the 409 an approver sees), `revoked` (a revocation row appended). One count per `signoff.*` event, taken after the event is committed, so the counter and the audit trail agree; a refused revoke (already revoked, unknown id) writes no event and counts nothing |
| `crb_github_tokens_minted_total` | counter | `installation` | worker | GitHub App installation tokens actually minted (a cache hit does not count). The label is the installation id; the token is never a label, never logged |
| `crb_queue_depth` | gauge | — | worker | queued runs, as the worker last saw them on check-in (every `heartbeat_s`) |
| `crb_false_q1_total` | gauge | — | api (recounted on every scrape and every `/health`) and worker (after every run) | clean ledger rows with a failed belt. **Must be 0** — a stop condition ([OPERATOR §8](OPERATOR.md#8-stop-conditions)) |
| `crb_ledger_rows` | gauge | — | api, worker | rows in the grade ledger |
| `crb_http_requests_total` | counter | `method, route, status` | api | requests by route template (never a raw id) |
| `crb_http_request_duration_seconds` | histogram | `method, route` | api | request latency |

Histogram buckets: 1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800 seconds **[measured — n = 10
buckets; method: the bucket bounds every histogram is built with in the metrics module,
read at this commit; apparatus n/a]**.

### 9.2 Alert rules

These rules cover the operating posture; expressions assume both targets are scraped. The
chart ships them as a `PrometheusRule` (`prometheusRule.enabled`, off by default; its
`labels` are what your Prometheus's `ruleSelector` matches), with these expressions word for
word — `tests/test_deploy_alert_rules.py` fails when the chart and this table disagree — so
no deployment retypes them. The render refuses the rules while `worker.metrics.port` is 0:
three of them read series only the worker serves.

| Alert | Expression | Meaning and action |
|---|---|---|
| **False-Q1** | `max(crb_false_q1_total) > 0` | the honesty floor is breached — stop delivery, [OPERATOR §8](OPERATOR.md#8-stop-conditions). `/health` is also `down`. Critical, fires at once |
| **No worker** | `absent_over_time(crb_queue_depth[5m])` | no worker's exposition has been scraped for 5 minutes (`prometheusRule.noWorkerFor`; keep it several scrape intervals long), so queued runs will not start. A worker that is up but stopped checking in, or a running run whose heartbeat is stale, still serves the series: the `/health` probe `worker` names those (probe `/api/v1/health` with a blackbox exporter to alert on them too) |
| **Sandbox failing closed** | `increase(crb_sandbox_unavailable_total[15m]) > 0` | the docker daemon, image or mounts are wrong on the worker host ([OPERATOR §7](OPERATOR.md#7-when-the-sandbox-is-unavailable)); no test ran on the host as a fallback |
| **Deliveries failing** | `increase(crb_deliveries_total{outcome="failed"}[1h]) > 0` | the push or the pull-request call errored — the GitHub App's installation, permissions or the repository's default branch |

Useful, not alerts: `sum by (repo) (increase(crb_builder_cost_usd_total[24h]))` (spend per
repository, a floor), `sum by (repo, outcome) (increase(crb_deliveries_total[7d]))`,
`increase(crb_github_tokens_minted_total[1h])` (a mint rate far above the clone + deliver
rate is worth a look), `histogram_quantile(0.9, rate(crb_grade_latency_seconds_bucket[1h]))`.

### 9.3 Health

`GET /api/v1/health` (readiness, 503 on `down`) runs eleven probes — `db`, `migrations`
(the store's revision is the code's head; `down`, and so 503, when the store is behind, ahead,
empty or unreadable — [the contract](API.md#the-migrations-probe)), `append_only`, `ledger`,
`sandbox` (skipped for `CRB_ROLE=api`), `provision` (dependency provisioning, ADR-0019;
skipped for `CRB_ROLE=api` and while provisioning is off), `toolchains`, `builders` (a
present builder login is `verified`, `unverified` or `invalid` from its last recorded check —
never `ok` from presence alone, and a scrape never calls a model), `worker` (and each worker's
metrics listener), `intake` and `build` (the served commits agree) — each documented in
[API.md](API.md#health--metrics-no-auth-bind-to-an-internal-interface) **[measured — n = 11
probes; method: the probes the readiness route runs, counted in its code and held there by
`tests/test_health_probe_docs.py`; apparatus n/a]**.
`GET /api/v1/health/live` is the liveness probe: the process and its database, nothing else.

The `worker` probe reads the `workers` table: every worker upserts its row every
`heartbeat_s` (default 10 s) whether or not it holds a run, with the interval it promised,
so the probe judges a worker alive when it checked in within 3 × its own `heartbeat_s`. The
UI reads the same probe: the Deployment page lists the workers with their last check-in. The
`ledger` and `sandbox` probes raise a banner **[measured — n = 2, the two named; method: every
UI reader of a probe classified in `tests/test_health_probe_docs.py`'s `BANNERS`; apparatus
n/a, a property of the product's own code, not a graded row]**. The shell raises the red "Delivery halted" banner above every screen,
Home included, while the `ledger` probe reports a false-Q1 row; Home adds its own banner when
the `sandbox` probe says the sandbox cannot run. Any other probe that is not `ok` shows only as
the one-word pill in the header, so read `/health` itself when that pill is not `ok`.

### 9.4 Logs

Every worker start writes one `ledger heads at worker start` line with the grade ledger's and
the audit trail's head `row_hash` and row counts (as `grades_head`, `grades_rows`,
`events_head`, `events_rows` in the JSON form) — the copy of both heads the log store keeps
outside the database (§8). Both processes log one JSON object per line
(`CRB_LOG_FORMAT=json`, the default): `ts`,
`level`, `logger`, `msg`, any structured extras, and `exc` for a traceback. Every record —
message, `%`-arguments, extras and the traceback — passes the same redaction as evidence
packs before a handler sees it (`src/crb/core/redact.py`; the commitment is
[SECURITY.md](SECURITY.md)). Ship stderr with the collector you already run (Fluent Bit,
the Azure Monitor agent, `docker compose logs`); nothing else is written to disk except the
per-run JSONL event copy under `<CRB_HOME>/events/<run_id>.jsonl` and the worker's reaper
queue `<CRB_HOME>/unconfirmed-containers.json` — the names of builder containers whose
`docker kill` the daemon never confirmed, retried every poll until reaped or given up on
after 20 passes **[measured — n = 20 passes; method: the bound on reap passes, one per
worker poll, in the worker's reaper module, read at this commit; apparatus n/a]**
([API.md](API.md#runs), `POST /runs/{id}/cancel`); while it is non-empty the
`/health` worker probe reads `degraded`.

### 9.5 Events

Every step of a run is a `StepEvent` in the `events` table (append-only, ordered by `seq`
within a trace, and hash-chained over the whole table in id order — ADR-0029; `/ledger/verify`
walks the chain), streamed live as SSE from `GET /runs/{id}/events` and paged from
`GET /runs/{id}/events/log`. The complete vocabulary — stage, action, status, payload keys,
emitter, consumer — is [API.md § Event vocabulary](API.md#event-vocabulary), kept in step
with the code by `tests/test_event_vocabulary.py`. Retention: the table is append-only and
is never pruned by crb; size it with the ledger (a replay writes roughly 10–30 events per
task **[hypothesis — an estimate from the development stack's runs, not counted over a stated
number of tasks; a count of events per task over one sweep would confirm or replace it]**).
`GET /ledger/verify` — read each time a person opens the Ledger or the Posture page —
re-hashes only the events written since its last full walk, and walks the whole table again
at most five minutes after the last full walk, when anything it walked has changed, after a
break, or when an operator asks with `?full=true`; each answer says which walk it was
(`events.walk`) and when the last full walk ran (`events.full_walk_at`). A full walk still
slows as the table grows [hypothesis — two readings on SQLite over 100,000 events: 1.6 s and
2.7 s a walk; time `crb ledger verify --store`, which always walks in full, on your own
store to know yours] (ADR-0029, Consequences). The
JSONL copy under `<CRB_HOME>/events/` is the operator's local mirror and may be rotated
freely.

