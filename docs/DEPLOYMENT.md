# Deployment guide

*For the platform team that installs crb inside an organisation's tenant.* Day-2 operation
(repositories, sweeps, sign-off, stop conditions) is the [Operator guide](OPERATOR.md); the
design behind these choices is [ARCHITECTURE §6](ARCHITECTURE.md#6-deployment-view) and
[ADR-0005 (fail-closed sandbox)](adr/0005-fail-closed-docker-sandbox.md).

Contents: [1 Shapes](#1-deployment-shapes) ·
[1.1 Single host without containers](#11-single-host-without-containers-evaluation) ·
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

The two container shapes run the same image and the same four things: PostgreSQL, a one-shot **migrate** step,
the **api** (HTTP + UI) and the **worker** (queue consumer that mines, builds, grades and
appends to the ledger). Both enforce the same invariants: the append-only tables carry DB
triggers, every verdict is hash-chained, the sandbox fails closed, and the only permitted
egress is the model endpoint (worker) and the OIDC issuer (api).

### 1.1 Single host without containers (evaluation)

The shape every walkthrough, the first factory run (B-1b) and the development stack use:
one directory, one SQLite file, two processes. It is for evaluation — the local executor
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
| `CRB_FORWARDED_ALLOW_IPS` / `CRB_TRUSTED_PROXIES` | | addresses whose `X-Forwarded-*` are believed (uvicorn / app). Set both to the proxy's CIDR; empty = believe nobody. Never `*` — a wildcard lets any client spoof its address and scheme (Helm ships empty; compose `127.0.0.1`) |
| `CRB_WEB_CONCURRENCY` | | uvicorn workers (default 1; 2 in compose/Helm) |
| `CRB_BOOTSTRAP_ADMIN__USERNAME` / `__PASSWORD` | first boot | seeds the first admin **only while `users` is empty** (≥ 12 chars) |
| `CRB_LOCAL_AUTH_ENABLED` | | set `false` once OIDC works |
| `CRB_OIDC__ISSUER`, `__CLIENT_ID`, `__CLIENT_SECRET`, `__REDIRECT_URL`, `__SCOPES`, `__ROLE_CLAIM`, `__ROLE_MAP`, `__ADMIN_GROUPS` | for SSO | see §4.1 for the Entra ID mapping |
| `CRB_GITHUB__APP_ID`, `__APP_SLUG`, `__PRIVATE_KEY` or `__PRIVATE_KEY_FILE`, `__API_URL`, `__WEB_URL` | for *Connect from GitHub* | the deployment's GitHub App (docs/GITHUB-APP.md); set on the **API and the worker**; the key from the secret store, never inline in a values file |
| `CRB_SANDBOX__EXECUTOR` | api, worker | `docker` (default, fail-closed) or `local` (development). Read by the API (`/settings`, `/health`) and by the worker (`crb worker`; its short form `CRB_EXECUTOR` is read when this is absent) |
| `CRB_METRICS_ENABLED` | api, worker | `true` (default). `false` → the api's `/metrics` answers 404 and the worker starts no exposition |
| `CRB_METRICS_HOST` | worker | the address the worker's exposition binds (default `127.0.0.1`, like `CRB_BIND_HOST`: the series name repositories, builders and installations, so a bare `crb worker` on a host offers them to nobody else). Compose and Helm set `0.0.0.0` inside the container, where only the compose network / the NetworkPolicy's scraper can reach the port (§9.1) |
| `CRB_METRICS_PORT` | worker | the worker's own Prometheus exposition port (default `9464`; `0` = off) — the build / grade / cost / delivery series live here, not on the api (§9) |
| `CRB_LOG_FORMAT` / `CRB_LOG_LEVEL` | api, worker | `json` (default, one object per line) or `text`; `INFO` — every record is redacted before a handler sees it (§9) |
| `CRB_WORKER_HEARTBEAT_STALE_S` | api | seconds after which a *running* run's heartbeat is reported stale by `/health` (default 120). Worker liveness itself is judged against each worker's own `heartbeat_s` (§9) |
| `CRB_SANDBOX__IMAGE` | worker | default sandbox image when a repository config has none (a repository's own `sandbox_image` wins). The shipped reference images — `deploy/sandbox/Dockerfile.{python,node,go}`, built and smoked by CI — are what to push to your registry and name here (`deploy/sandbox/README.md`); the worker never pulls (`docker run --pull=never` **[measured — `tests/test_execution.py::test_docker_build_argv_has_every_hardening_flag` pins the flag on the argv; `tests/test_sandbox_images_docker.py::test_an_absent_image_fails_closed_without_a_pull` proves an absent image is `SandboxUnavailable` (exit 125, `No such image`) against a daemon, colima / Docker 29.5.2; apparatus 2.2]**), so the image must be in the daemon's store |
| `CRB_FACTORY__TEST_AUTHOR` | api, worker | the factory's test-author rung — `builder:model[:provider]`, the same spelling as a build rung, or empty / `none` (the default) for no author. With no author, an item nobody wrote a failing test for stops `no_oracle`; with one, that rung writes the test. **The author rung and the build rung are never the same rung**: a label that is also on a run's ladder is refused before anything is built. A run may override it (`POST /runs {test_author}`) |
| `CRB_RETENTION__TRANSCRIPTS_DAYS` | | 0 = keep no builder transcripts (default) |
| `CRB_OPENAI_BASE_URL`, `CRB_OPENAI_KEY_ENV` + the named key var | builder | OpenAI-compatible endpoint (vLLM, Cerebras, …) |
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
`helm.sh/resource-policy: keep` so worktrees survive an uninstall.

### 3.3 PostgreSQL

`postgresql.mode: external` (default) — `CRB_DATABASE_URL` in the Secret points at a
managed server; use `sslmode=require` (or `verify-full` with the CA) and a private endpoint.
`postgresql.mode: embedded` renders a single-replica StatefulSet (`postgres:16-alpine`, uid
70, read-only root) for **evaluation only** — no HA, no PITR, no managed backups.

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
`sandbox_image`. Everything else — build, tag, push, select, extend for a repository's
dependencies, the re-pin cadence — is [deploy/sandbox/README.md](../deploy/sandbox/README.md).
A JVM reference image is deliberately not shipped: the Maven runner's docker branch cannot
resolve plugins offline yet (README §6).

The `sandbox-images` job is meant to block a merge to `main` exactly as `container` does —
it has no `continue-on-error` and fails on any skipped smoke test — but a job blocks only
when its context is in the branch's required status checks, which is a repository setting,
not a workflow file **[measured — `GET /repos/Jita81/commit-replay-bench/branches/main/protection`,
2026-09-22: the context is absent; a red `sandbox-images` would not block a merge]**. The
repository administrator adds it once:

```bash
gh api -X PATCH repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks \
  --input - <<'JSON'
{"strict": true, "contexts": ["lint (ruff)", "types (mypy --strict)", "layers (import-linter)",
 "code-map (every file has a valid header; docs/CODE-MAP.md is current)",
 "test (py3.12)", "test (py3.13)", "test-postgres (store suite on PostgreSQL 16)",
 "security (gitleaks + pip-audit)", "container (docker build + smoke + helm lint)",
 "walkthrough (browser, live stack, tier 1)",
 "sandbox-images (build + hadolint + smoke each reference sandbox image)"]}
JSON
```

(the list is the current set plus the new context — `PATCH` replaces it, so send all of
them; `GET …/protection` first to confirm the set has not moved). Until then the job's
verdict is visible on every pull request but advisory.

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
  Enable PITR (7–35 days) — this is the ledger's backup.
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
`events` / `signoffs` / `evidence` tables) and the worker's work volume (reproducible from
the repositories; convenient to keep).

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

Restore order: database (on an *empty* target) → work volume → `migrate` (no-op at head; it
re-asserts the triggers) → api/worker → ledger verify → the `migrations` and `append_only`
probes on `/api/v1/health`.

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
worker's next event.)

Compose: `docker compose run --rm migrate check` → `run --rm migrate` → `up -d`
([deploy/README.md §5](../deploy/README.md#5-upgrade)).

## 7. Air-gap posture

crb never bundles a model and never phones home: no telemetry, no update checks, no
run-time pulls by the worker itself. The complete outbound list is: worker → model endpoint;
api → OIDC issuer; (`dind` only) sidecar → your registry. Sandboxes run with
`--network=none`. To operate fully inside the tenant:

1. point the builder at an in-tenant endpoint — Azure OpenAI with a private endpoint (§4.3)
   or a self-hosted OpenAI-compatible server (`CRB_OPENAI_BASE_URL=https://vllm.internal/v1`);
2. mirror the images (crb, sandbox, `docker:dind`, `postgres`) into your registry;
3. enforce deny-by-default egress at the cluster/host boundary and keep the chart's
   NetworkPolicy allowlists to those CIDRs only;
4. verify from a worker pod that a public address is unreachable while
   `/api/v1/health` reports the builder reachable.

## 8. Go-live checklist

- [ ] The running image is a released digest: `deploy/verify-image.sh <version> --digest
      sha256:<pinned>` passes (§2.2) and the digest is what `image.digest` / `CRB_IMAGE` says.
- [ ] `GET /api/v1/health` on the API is green: `db` answers, `migrations` reads
      `database at <rev> = code head` — its contract is
      [API.md — The `migrations` probe](API.md#the-migrations-probe): `ok` at head; `degraded` (still served) for an unstamped `create_all` schema that matches the head, until `crb migrate` stamps it; `down` (the endpoint answers 503) when the store is behind, ahead, empty or an older unversioned schema (crb tables, no `alembic_version`, fingerprints of a revision behind the head) — revisions named where applicable, with the fix — or when it cannot be read — the fixed detail `migrations could not be read — see the API log, request id <id>`, `data: {}`, the exception in the API log under that id. A half-migrated database cannot pass this
      line. `append_only` proves an
      UPDATE refused, `ledger` reads `false_q1=0`, `builders`
      configured, `worker` heartbeats fresh (`sandbox` is `skipped` on the API pod — the
      worker owns it; prove it with `crb doctor` on the worker host).
- [ ] `crb doctor` on the API host and on the worker host: every line `ok`, or `warn` for a
      reason you have written down; no `fail`. It covers what `/health` cannot see from
      inside a pod — the GitHub App's installations, the secrets directory mode, the
      `CRB_HOME` location and the help bundle ([OPERATOR.md §1.1](OPERATOR.md#11-check-the-installation-crb-doctor)).
- [ ] `GET /api/v1/ledger/verify` reads `chain intact, false_q1=0`; the last `row_hash`
      (`SELECT row_hash FROM grades ORDER BY seq DESC LIMIT 1`) is recorded out of band.
- [ ] OIDC login works with a role-mapped user; `CRB_LOCAL_AUTH_ENABLED=false`; the
      bootstrap admin password has been rotated (`PUT /users/{id}/password`, or
      `crb users set-password <admin>` on the API host) or the account deactivated
      (`PUT /users/{id}/active {"active": false}` / `crb users deactivate <admin>` —
      possible once another active admin exists, for example the first OIDC sign-in
      from an `CRB_OIDC__ADMIN_GROUPS` member); `CRB_BOOTSTRAP_ADMIN__*` unset
      ([OPERATOR.md §9](OPERATOR.md#9-users)).
- [ ] Egress test from a worker pod fails to any public address.
- [ ] `crb repo probe <repo>` is green inside the sandbox for every configured repository.
- [ ] Backups: PITR enabled; a restore has been rehearsed and verified against the chain.
- [ ] `false_q1 == 0` and `crb_false_q1_total == 0` on the dashboards, with an alert on any
      non-zero value ([OPERATOR.md §8](OPERATOR.md#8-stop-conditions)).

## 9. Observability

Three surfaces: **metrics** (Prometheus, two expositions), **health** (`/health`, seven
probes), **events** (the run's audit trail, streamed as SSE and stored in the `events`
table). Logs are JSON and redacted. Nothing here leaves the tenant.

### 9.1 Metrics — which process carries which series

The Prometheus registry is process-wide, so a series lives in the process that records it.
The api records the HTTP series and the ledger gauges; **the worker records everything
else and serves its own exposition** on `CRB_METRICS_PORT` (default 9464). A deployment
that scrapes the api alone sees `crb_false_q1_total`, `crb_ledger_rows` and the HTTP
series — every cost, run, belt and delivery counter reads as absent. Scrape both:

| Shape | api | worker |
|---|---|---|
| compose | `http://api:8000/api/v1/metrics` (published on `127.0.0.1:8000`) | `http://worker:9464/metrics` — the container sets `CRB_METRICS_HOST=0.0.0.0` and the port is `expose`d on the compose network only, never published; `CRB_METRICS_PORT=0` switches it off |
| Helm | Service `crb-api`, port `http`, path `/api/v1/metrics`; `serviceMonitor.enabled` | headless Service `crb-worker`, port `metrics` (one target per worker pod; the pod sets `CRB_METRICS_HOST=0.0.0.0`); `serviceMonitor.worker.enabled`; `worker.metrics.port` (0 = off); the NetworkPolicy admits `networkPolicy.metricsIngress` peers to that port only |
| one process (`crb serve` + `crb worker` on a host) | `/api/v1/metrics` | `127.0.0.1:9464/metrics` — loopback by default; a Prometheus on another host needs `CRB_METRICS_HOST=<the interface it may reach>` (or `0.0.0.0` behind a host firewall) — the series name repositories, builders, per-repository cost and installation ids |

The table is checked against the code by `tests/test_observability_metrics.py`: a metric
the module defines that is not here, or is here under other labels, fails the suite.

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
| `crb_github_tokens_minted_total` | counter | `installation` | worker | GitHub App installation tokens actually minted (a cache hit does not count). The label is the installation id; the token is never a label, never logged |
| `crb_queue_depth` | gauge | — | worker | queued runs, as the worker last saw them on check-in (every `heartbeat_s`) |
| `crb_false_q1_total` | gauge | — | api (recounted on every scrape and every `/health`) and worker (after every run) | clean ledger rows with a failed belt. **Must be 0** — a stop condition ([OPERATOR §8](OPERATOR.md#8-stop-conditions)) |
| `crb_ledger_rows` | gauge | — | api, worker | rows in the grade ledger |
| `crb_http_requests_total` | counter | `method, route, status` | api | requests by route template (never a raw id) |
| `crb_http_request_duration_seconds` | histogram | `method, route` | api | request latency |

Histogram buckets: 1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800 seconds.

### 9.2 Alert rules

Four rules cover the operating posture. Expressions assume both targets are scraped.

| Alert | Expression | Meaning and action |
|---|---|---|
| **False-Q1** | `max(crb_false_q1_total) > 0` | the honesty floor is breached — stop delivery, [OPERATOR §8](OPERATOR.md#8-stop-conditions). `/health` is also `down` |
| **No worker** | `/health` probe `worker` is not `ok` (`crb_http_*` cannot see it; probe `/api/v1/health` with a blackbox exporter, or alert on `crb_queue_depth > 0` with no fresh worker scrape for 3 × `heartbeat_s`) | queued runs will not start: no worker has checked in, one stopped checking in (the probe names it and its age), or a running run's heartbeat is stale |
| **Sandbox failing closed** | `increase(crb_sandbox_unavailable_total[15m]) > 0` | the docker daemon, image or mounts are wrong on the worker host ([OPERATOR §7](OPERATOR.md#7-when-the-sandbox-is-unavailable)); no test ran on the host as a fallback |
| **Deliveries failing** | `increase(crb_deliveries_total{outcome="failed"}[1h]) > 0` | the push or the pull-request call errored — the GitHub App's installation, permissions or the repository's default branch |

Useful, not alerts: `sum by (repo) (increase(crb_builder_cost_usd_total[24h]))` (spend per
repository, a floor), `sum by (repo, outcome) (increase(crb_deliveries_total[7d]))`,
`increase(crb_github_tokens_minted_total[1h])` (a mint rate far above the clone + deliver
rate is worth a look), `histogram_quantile(0.9, rate(crb_grade_latency_seconds_bucket[1h]))`.

### 9.3 Health

`GET /api/v1/health` (readiness, 503 on `down`) runs seven probes — `db`, `append_only`,
`ledger`, `sandbox` (skipped for `CRB_ROLE=api`), `toolchains`, `builders`, `worker` —
documented in [API.md](API.md#health--metrics-no-auth-bind-to-an-internal-interface).
`GET /api/v1/health/live` is the liveness probe: the process and its database, nothing else.

The `worker` probe reads the `workers` table: every worker upserts its row every
`heartbeat_s` (default 10 s) whether or not it holds a run, with the interval it promised,
so the probe judges a worker alive when it checked in within 3 × its own `heartbeat_s`. The
UI reads the same probe: the Home screen shows a banner when it is not `ok` and the
Deployment page lists the workers with their last check-in.

### 9.4 Logs

Both processes log one JSON object per line (`CRB_LOG_FORMAT=json`, the default): `ts`,
`level`, `logger`, `msg`, any structured extras, and `exc` for a traceback. Every record —
message, `%`-arguments, extras and the traceback — passes the same redaction as evidence
packs before a handler sees it (`src/crb/core/redact.py`; the commitment is
[SECURITY.md](SECURITY.md)). Ship stderr with the collector you already run (Fluent Bit,
the Azure Monitor agent, `docker compose logs`); nothing else is written to disk except the
per-run JSONL event copy under `<CRB_HOME>/events/<run_id>.jsonl` and the worker's reaper
queue `<CRB_HOME>/unconfirmed-containers.json` — the names of builder containers whose
`docker kill` the daemon never confirmed, retried every poll until reaped or given up on
after 20 passes ([API.md](API.md#runs), `POST /runs/{id}/cancel`); while it is non-empty the
`/health` worker probe reads `degraded`.

### 9.5 Events

Every step of a run is a `StepEvent` in the `events` table (append-only, hash-ordered by
`seq`), streamed live as SSE from `GET /runs/{id}/events` and paged from
`GET /runs/{id}/events/log`. The complete vocabulary — stage, action, status, payload keys,
emitter, consumer — is [API.md § Event vocabulary](API.md#event-vocabulary), kept in step
with the code by `tests/test_event_vocabulary.py`. Retention: the table is append-only and
is never pruned by crb; size it with the ledger (a replay writes roughly 10–30 events per
task). The JSONL copy under `<CRB_HOME>/events/` is the operator's local mirror and may be
rotated freely.

