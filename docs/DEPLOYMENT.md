# Deployment guide

*For the platform team that installs crb inside an organisation's tenant.* Day-2 operation
(repositories, sweeps, sign-off, stop conditions) is the [Operator guide](OPERATOR.md); the
design behind these choices is [ARCHITECTURE §6](ARCHITECTURE.md#6-deployment-view) and
[ADR-0005 (fail-closed sandbox)](adr/0005-fail-closed-docker-sandbox.md).

Contents: [1 Shapes](#1-deployment-shapes) · [2 The image](#2-the-image-and-its-roles) ·
[2.2 Released image, signature, SBOM](#22-the-released-image-name-signature-sbom) ·
[3 Kubernetes (Helm)](#3-kubernetes-helm) · [4 Azure](#4-azure) ·
[5 Backup & restore](#5-backup-and-restore) · [6 Upgrade](#6-upgrade) ·
[7 Air-gap](#7-air-gap-posture) · [8 Go-live checklist](#8-go-live-checklist)

---

## 1. Deployment shapes

| Shape | When | Where documented |
|---|---|---|
| **Single host, Docker Compose** | pilots, one team, one VM in the tenant | [deploy/README.md](../deploy/README.md) |
| **Kubernetes, Helm** | shared platform, AKS/EKS/on-prem, managed PostgreSQL | §3 of this page; [deploy/helm/crb](../deploy/helm/crb/README.md) |

Both run the same image and the same four things: PostgreSQL, a one-shot **migrate** step,
the **api** (HTTP + UI) and the **worker** (queue consumer that mines, builds, grades and
appends to the ledger). Both enforce the same invariants: the append-only tables carry DB
triggers, every verdict is hash-chained, the sandbox fails closed, and the only permitted
egress is the model endpoint (worker) and the OIDC issuer (api).

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
| `CRB_HOME` | | state dir; `/srv/crb` in the image |
| `CRB_BIND_HOST` / `CRB_BIND_PORT` | | `0.0.0.0:8000` in the image |
| `CRB_FORWARDED_ALLOW_IPS` / `CRB_TRUSTED_PROXIES` | | addresses whose `X-Forwarded-*` are believed (uvicorn / app). Set both to the proxy's CIDR; empty = believe nobody. Never `*` — a wildcard lets any client spoof its address and scheme (Helm ships empty; compose `127.0.0.1`) |
| `CRB_WEB_CONCURRENCY` | | uvicorn workers (default 1; 2 in compose/Helm) |
| `CRB_BOOTSTRAP_ADMIN__USERNAME` / `__PASSWORD` | first boot | seeds the first admin **only while `users` is empty** (≥ 12 chars) |
| `CRB_LOCAL_AUTH_ENABLED` | | set `false` once OIDC works |
| `CRB_OIDC__ISSUER`, `__CLIENT_ID`, `__CLIENT_SECRET`, `__REDIRECT_URL`, `__SCOPES`, `__ROLE_CLAIM`, `__ROLE_MAP`, `__ADMIN_GROUPS` | for SSO | see §4.1 for the Entra ID mapping |
| `CRB_SANDBOX__EXECUTOR` | | `docker` (default, fail-closed) or `local` (development) |
| `CRB_SANDBOX__IMAGE` | | default sandbox image when a repository config has none |
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
  CRB_OIDC__REDIRECT_URL: https://crb.example.internal/auth/callback
  CRB_TRUSTED_PROXIES: 10.240.0.0/16          # ingress controller pod CIDR
  CRB_AZURE_ENDPOINT: https://<aoai>.openai.azure.com
  CRB_AZURE_DEPLOYMENT: gpt-4o
  CRB_SANDBOX__IMAGE: <acr>.azurecr.io/crb-sandbox/python:2026-09
worker:
  sandbox: { mode: dind }
  nodeSelector: { crb.dev/pool: worker }
  tolerations: [{ key: crb.dev/worker, operator: Exists, effect: NoSchedule }]
networkPolicy:
  postgres: { cidrs: ["10.10.1.4/32"] }        # Flexible Server private endpoint
  modelEndpoint: { cidrs: ["10.10.2.4/32"] }   # Azure OpenAI private endpoint
  oidc: { cidrs: ["10.10.3.4/32"] }            # egress proxy / firewall for login.microsoftonline.com
  extraEgress:
    - to: [{ ipBlock: { cidr: 10.10.4.4/32 } }]   # ACR private endpoint (dind pulls sandbox images)
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
executor fails **closed**: runs become `blocked`, nothing executes on the node
([OPERATOR.md §7](OPERATOR.md#7-when-the-sandbox-is-unavailable)).

| `worker.sandbox.mode` | Mechanism | Blast radius | Use when |
|---|---|---|---|
| `none` (default) | — | none; runs are blocked | until you have decided |
| `dind` | `docker:dind` sidecar in the worker pod, unix socket on a shared in-memory emptyDir, image store on an emptyDir | the **pod** — the sidecar is `privileged`, but it is the only privileged container and it never touches the node's runtime socket. Sandbox images are pulled by the sidecar (allow the registry in `extraEgress`) | the recommended cluster mode; put the worker on a dedicated node pool anyway |
| `hostSocket` | `hostPath` mount of the node's `/var/run/docker.sock` + `supplementalGroups` | the **node** — socket access is root-equivalent | only with a dedicated, tainted node pool, a PodSecurity exemption for that namespace, and a written risk acceptance |

In every mode the worker's own container stays non-root, read-only and capability-less,
and `DockerSettings` refuses to mount the socket, `/` or `$HOME` into a sandbox.

## 4. Azure

### 4.1 Entra ID → `CRB_OIDC__*`

Create an **app registration** (single tenant), a **web** redirect URI
`https://<host>/auth/callback`, and a client secret (or a federated credential). Then:

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
* **Verify every backup**: `crb ledger verify` (or `GET /api/v1/ledger/verify`) before and
  after a restore must report the same row count and last `row_hash`. A restore that
  changes either is not a restore; treat it as an incident.

Restore order: database (on an *empty* target) → work volume → `migrate` (no-op at head; it
re-asserts the triggers) → api/worker → ledger verify → the append-only probe on
`/api/v1/health`.

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
- [ ] `GET /api/v1/health` is green: database reachable, migrations at head, append-only
      probe passes, sandbox reachable (worker), builder reachable.
- [ ] `crb ledger verify` succeeds; the last `row_hash` is recorded out of band.
- [ ] OIDC login works with a role-mapped user; `CRB_LOCAL_AUTH_ENABLED=false`; the
      bootstrap admin password has been rotated or the account disabled.
- [ ] Egress test from a worker pod fails to any public address.
- [ ] `crb repo probe <repo>` is green inside the sandbox for every configured repository.
- [ ] Backups: PITR enabled; a restore has been rehearsed and verified against the chain.
- [ ] `false_q1 == 0` and `crb_false_q1_total == 0` on the dashboards, with an alert on any
      non-zero value ([OPERATOR.md §8](OPERATOR.md#8-stop-conditions)).
