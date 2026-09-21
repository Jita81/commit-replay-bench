# Deploying crb on a single host (Docker Compose)

The reference single-host deployment: PostgreSQL 16, a one-shot migration, the API (+ UI)
and one worker, all from one image built by `deploy/Dockerfile`. For Kubernetes see
[`helm/crb`](helm/crb/README.md); for the Azure/Entra/Key Vault specifics, air-gap posture
and the full upgrade/backup procedures see [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
Operating the product once it is up is [docs/OPERATOR.md](../docs/OPERATOR.md).

Contents: [1 Quickstart](#1-quickstart) · [1.1 Released image](#11-use-the-released-image-instead-of-building) · [2 TLS](#2-tls-in-front-of-the-api) ·
[3 Sandbox (docker socket)](#3-let-the-worker-sandbox-tests-docker-socket-opt-in) ·
[4 Backup & restore](#4-backup-and-restore) · [5 Upgrade](#5-upgrade) ·
[6 Air-gap](#6-air-gap-egress-only-to-the-model-endpoint) · [7 Azure OpenAI](#7-azure-openai-in-your-tenant) ·
[8 Troubleshooting](#8-troubleshooting) · [9 Builder in a sealed container](#9-builder-in-a-sealed-container-crb_builder__executordocker)

## 1. Quickstart

Requirements: a Linux host with Docker Engine ≥ 24 and the Compose plugin ≥ 2.20, 2 CPU /
4 GB for the API + database, plus whatever the sandboxes need (2 CPU / 2 GB per concurrent
task is the default `DockerSettings` cap).

```bash
git clone https://github.com/Jita81/commit-replay-bench.git && cd commit-replay-bench
cp deploy/.env.example deploy/.env && chmod 0600 deploy/.env
$EDITOR deploy/.env            # POSTGRES_PASSWORD, CRB_SECRET_KEY (openssl rand -hex 32),
                               # CRB_BOOTSTRAP_ADMIN__PASSWORD, the model endpoint
sudo install -d -o 10001 -g 10001 -m 0750 /srv/crb   # state dir; same path inside containers
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps        # db healthy, migrate exited 0, api + worker up
curl -fsS http://127.0.0.1:8000/api/v1/health         # database, migrations, append-only probe
```

The API listens on `127.0.0.1:8000` **only**. Log in with the bootstrap admin (honoured only
while the `users` table is empty), then configure OIDC and set
`CRB_LOCAL_AUTH_ENABLED=false`.

`--build` needs **BuildKit** (`deploy/Dockerfile` uses `--mount=type=cache` and the
`# syntax=` directive). Docker Engine ≥ 23 enables it by default; on a client without the
buildx plugin (some Homebrew / colima set-ups) `docker build` falls back to the legacy
builder and fails at the first `RUN --mount` — install `docker-buildx` and run
`docker buildx build --load -f deploy/Dockerfile -t crb:local .` instead. Most
installations should not build at all: use the released image (§1.1).

## 1.1 Use the released image instead of building

Every `v*` tag publishes one image, built by `.github/workflows/release.yml` from the same
`deploy/Dockerfile` that CI builds and smokes on every pull request:

| Reference | Meaning |
|---|---|
| `ghcr.io/jita81/commit-replay-bench:<version>` | the release, e.g. `2.0.0a1` (the git tag without its `v`) |
| `ghcr.io/jita81/commit-replay-bench:sha-<short>` | the same bytes, addressed by the 7-character commit sha |
| `ghcr.io/jita81/commit-replay-bench@sha256:…` | the digest — **pin this** in production (`CRB_IMAGE` below, `image.digest` in Helm) |

The image is `linux/amd64`, signed **keyless** with cosign (GitHub OIDC → Sigstore, recorded
in the Rekor transparency log) and carries two SBOMs: a BuildKit SBOM/provenance attestation
inside the image index, and a syft SPDX SBOM attached as an in-toto attestation (also
downloadable as the `crb-image-sbom-<tag>` artifact of the release run). No long-lived
signing key exists anywhere; the signing identity *is* the release workflow on a tag.

**Verify before you run it** — this is the step a regulated deployment must not skip. The
package is private, so log in first with a token that has `read:packages` (cosign reads
the signature from the same registry and uses the same Docker credentials):

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
# one command (cosign ≥ 2; jq for --sbom). --digest also asserts the tag → digest pin.
deploy/verify-image.sh 2.0.0a1 --sbom sbom.spdx.json
# …or the underlying commands, so you can see exactly what is accepted:
cosign verify ghcr.io/jita81/commit-replay-bench:2.0.0a1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/Jita81/commit-replay-bench/\.github/workflows/release\.yml@refs/tags/v'
cosign verify-attestation --type spdxjson ghcr.io/jita81/commit-replay-bench:2.0.0a1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/Jita81/commit-replay-bench/\.github/workflows/release\.yml@refs/tags/v' \
  | jq -r .payload | base64 -d | jq .predicate > sbom.spdx.json
cosign triangulate --type digest ghcr.io/jita81/commit-replay-bench:2.0.0a1   # the digest to pin
```

The identity regexp is the whole point: a signature from a fork, a branch, or a manual
dispatch of the workflow is **rejected**, not merely warned about. Then run compose with
the image instead of a local build:

```bash
cp deploy/.env.example deploy/.env && chmod 0600 deploy/.env && $EDITOR deploy/.env
echo 'CRB_IMAGE=ghcr.io/jita81/commit-replay-bench@sha256:<digest you verified>' >> deploy/.env
sudo install -d -o 10001 -g 10001 -m 0750 /srv/crb
docker compose -f deploy/docker-compose.yml pull        # pulls CRB_IMAGE (and postgres)
docker compose -f deploy/docker-compose.yml up -d       # no --build: the image is present, so nothing is built
docker compose -f deploy/docker-compose.yml ps
```

`CRB_IMAGE` defaults to `crb:local` (a local build); setting it to a GHCR reference in
`deploy/.env` makes every crb service (`migrate`, `api`, `worker`) run the verified bytes.
Air-gapped hosts: verify and `docker pull` on a connected machine, record
`docker image inspect ghcr.io/jita81/commit-replay-bench:2.0.0a1 --format '{{.Id}}'` (the
image ID survives `docker save | docker load`; the registry digest does not), load it on
the host, compare the ID, and set `CRB_IMAGE=ghcr.io/jita81/commit-replay-bench:2.0.0a1`
(the tag — a `@sha256:` reference would make compose try to pull). Upgrades are §5 with
`pull` in place of `build`.

What each service is:

| Service | Image | Role | Writable paths |
|---|---|---|---|
| `db` | `postgres:16.10-alpine3.22` (uid 70, read-only root) | the only stateful service | named volume `crb-pg` |
| `migrate` | crb (uid 10001) | `python -m crb.store.migrate upgrade`: Alembic → head **and** the append-only triggers; exits 0 | — |
| `api` | crb | `uvicorn --factory crb.server.app:create_app`; serves `ui/dist` | `/srv/crb` (bind), tmpfs `/tmp`, `/home/crb` |
| `worker` | crb | `python -m crb.server.worker_main`; mine → build → grade → ledger | `/srv/crb` (bind), tmpfs |

Every crb container runs with `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`,
a non-root uid, and CPU / memory / pid limits (`deploy.resources.limits`). Nothing except
`api` publishes a port.

## 2. TLS in front of the API

Terminate TLS on the same host and proxy to `127.0.0.1:8000`. Set `CRB_FORWARDED_ALLOW_IPS`
to the proxy's address (the default `127.0.0.1` is right for a proxy on the host). Caddy:

```caddyfile
crb.example.internal {
    tls /etc/ssl/crb.crt /etc/ssl/crb.key      # or your internal CA / ACME
    reverse_proxy 127.0.0.1:8000
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
    }
}
```

Session cookies are `Secure` whenever `CRB_ENV=prod` (the default), so plain-HTTP access
through the proxy will not log in — that is intended.

## 3. Let the worker sandbox tests (docker socket, opt-in)

By default the worker has **no** access to a Docker daemon. `CRB_SANDBOX__EXECUTOR=docker`
then fails **closed**: every run becomes `blocked`, no test runs on the host, no verdict is
written ([OPERATOR.md §7](../docs/OPERATOR.md#7-when-the-sandbox-is-unavailable)). To
enable sandboxing:

1. Read the security note in `docker-compose.yml` (`worker` → `volumes`). Access to the
   daemon socket is root-equivalent on the host. Put the worker on a host dedicated to crb,
   or in front of a socket proxy that exposes only the `containers`/`images`/`exec` endpoints.
2. `stat -c %g /var/run/docker.sock` → set `DOCKER_GID` in `deploy/.env`.
3. Uncomment the `- /var/run/docker.sock:/var/run/docker.sock` line and the `group_add`
   block in `docker-compose.yml`.
4. `docker compose -f deploy/docker-compose.yml up -d worker`, then `crb repo probe <repo>`
   (or the Repos screen) proves the sandbox image runs.

Why `/srv/crb` must be the **same path** on the host and in the container: the worker
creates a worktree under `$CRB_HOME` and asks the daemon to bind-mount it into the sandbox.
The daemon resolves that path on the **host**. A named volume or a different mount point
would make every sandbox start with an empty directory.

Sandbox images: [`deploy/sandbox/`](sandbox/README.md) ships the reference set —
`crb-sandbox-python` (pytest), `crb-sandbox-node` (`node --test`), `crb-sandbox-go` — each
digest-pinned, uid 65534, read-only-root compatible and proven from inside by CI on every
pull request. Build them from the repository root
(`docker build -f deploy/sandbox/Dockerfile.python -t crb-sandbox-python:local deploy/sandbox`,
likewise `node` and `go`), name the deployment default in `CRB_SANDBOX__IMAGE` and a
repository's own in its `sandbox_image` (the repository's wins), and extend one when a
repository's tests need more than the toolchain (its dependencies, `ruff` for belt 5 —
README §4). They must be present in the host daemon's image store: `docker pull` /
`docker load` them on the host; the worker never pulls from a registry (`docker run
--pull=never` — an absent image stops the run as `sandbox unavailable`).

## 4. Backup and restore

Two things hold state: the PostgreSQL volume (`crb-pg`: repos, runs, tasks, the append-only
`grades` / `events` / `signoffs` / `evidence` tables, users) and `/srv/crb` (clones,
worktrees, exports). The ledger's hash chain makes a backup **verifiable**: record the
last `row_hash` at backup time and compare after a restore.

```bash
C="docker compose -f deploy/docker-compose.yml"
# --- backup (online; pg_dump takes a consistent snapshot) ---
$C exec -T db pg_dump -U crb -d crb -Fc --no-owner > crb-$(date +%F).dump
sudo tar -C /srv -czf crb-state-$(date +%F).tgz crb
$C exec -T api python -m crb.cli.main ledger verify      # prints the row count; note the last row_hash
# --- restore (onto an EMPTY volume) ---
$C down
docker volume rm crb_crb-pg && docker volume create crb_crb-pg
$C up -d db && sleep 10
$C exec -T db pg_restore -U crb -d crb --no-owner --exit-on-error < crb-YYYY-MM-DD.dump
sudo tar -C /srv -xzf crb-state-YYYY-MM-DD.tgz
$C up -d
$C exec -T api python -m crb.cli.main ledger verify      # must succeed with the same count / last row_hash
```

`pg_restore` restores the triggers and the `crb_append_only()` function with the schema.
`migrate` runs again on `up` and is a no-op on a restored database at head (it re-asserts the
triggers regardless). Keep dumps under the same access control as the database: they
contain evidence packs (redacted, but organisational) and user records.

## 5. Upgrade

Migrations are forward-only in production and never rewrite an append-only table.

```bash
C="docker compose -f deploy/docker-compose.yml"
$C exec -T db pg_dump -U crb -d crb -Fc --no-owner > pre-upgrade-$(date +%F).dump   # always
git pull && $C build                     # or: set CRB_IMAGE=<registry>/crb:<tag> in .env and $C pull
$C run --rm migrate check                # exit 1 = migrations pending (expected before an upgrade)
$C run --rm migrate                      # alembic upgrade head + triggers, in one transaction
$C up -d                                 # api / worker roll onto the new image
curl -fsS http://127.0.0.1:8000/api/v1/health
```

A failed migration on PostgreSQL rolls back completely (single transaction); the previous
image keeps working against the untouched schema. Rolling back a *successful* migration is
not supported while the ledger holds rows — `downgrade` refuses by design; restore the
pre-upgrade dump instead.

## 6. Air-gap: egress only to the model endpoint

crb makes exactly two kinds of outbound connections: the **worker** to the configured model
endpoint (BYOK) and the **API** to the OIDC issuer (if enabled). Nothing phones home: no
telemetry, no update checks, no registry pulls at run time. Pin the posture on the host:

* the `crb` compose network is a plain bridge; add `internal: true` to it and attach a
  second, egress-capable network to `worker` (and `api` for OIDC) if you want the daemon to
  enforce isolation of `db` and `migrate`;
* on the host firewall, allow the Docker bridge to reach only the model endpoint and the
  issuer, e.g. with nftables:

  ```
  table inet crb-egress {
    set allow { type ipv4_addr; elements = { 10.20.0.7 } }        # private endpoint IP(s)
    chain forward { type filter hook forward priority 0;
      iifname "br-*" ip daddr @allow tcp dport 443 accept
      iifname "br-*" ip daddr 10.0.0.0/8 tcp dport 443 accept   # OIDC / internal CA if needed
      iifname "br-*" drop }
  }
  ```

* verify from inside: `docker compose exec worker python -c "import urllib.request;
  urllib.request.urlopen('https://example.com', timeout=5)"` must **fail**, while the model
  endpoint health probe on `/api/v1/health` reports the builder reachable.

Sandbox containers always run with `--network=none`; nothing a repository's tests do can
reach the network regardless of the host policy. With the builder in its own container
(§9) the *builder* also has no route out: only its egress sidecar talks to the endpoint,
so the host rule above is the second wall, not the only one.

## 7. Azure OpenAI in your tenant

The OpenAI-compatible builder selects Azure when `CRB_AZURE_ENDPOINT` is set. In
`deploy/.env`:

```
CRB_AZURE_ENDPOINT=https://<resource>.privatelink.openai.azure.com   # or the public FQDN + private DNS zone
CRB_AZURE_DEPLOYMENT=<deployment-name>                               # e.g. gpt-4o-2024-11-20
CRB_AZURE_API_VERSION=2024-10-21
CRB_AZURE_KEY_ENV=AZURE_OPENAI_API_KEY
AZURE_OPENAI_API_KEY=<from Key Vault; never commit>
```

Use a **private endpoint** on the Azure OpenAI resource, disable public network access, and
resolve `privatelink.openai.azure.com` through the VNet's private DNS zone; then the only
IP the firewall rule in §6 needs is the private endpoint's NIC address. Keys are read from
the environment at run time — pull them from Key Vault into `deploy/.env` with a managed
identity (`az keyvault secret show --vault-name … --name … --query value -o tsv`) as part
of your provisioning, and rotate by editing `.env` and `docker compose up -d worker`.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `migrate` exits non-zero: `refusing to guess … missing [...]` | The database has *some* crb tables but no `alembic_version` (a partial or foreign schema). Restore from backup or drop the schema; `migrate` never guesses. |
| `api` restarts with `CRB_SECRET_KEY is required when CRB_ENV=prod` | Set a ≥ 32-character key in `.env`. `CRB_ENV=dev` auto-generates one and turns `Secure` cookies off — never in production. |
| Runs are `blocked`, health shows the sandbox unavailable | The worker has no daemon socket (§3), the sandbox image is missing from the host daemon (`No such image` — the worker never pulls; `docker pull` / `docker load` it, [sandbox/README.md §2](sandbox/README.md)), or `docker info` fails as the socket's group. Nothing ran on the host; re-run after fixing. |
| Sandboxes start with an empty `/work` | `CRB_HOST_DIR` differs from `/srv/crb` or is a named volume; the paths must match (§3). |
| `/api/v1/health` reports `append_only: false` | The triggers are missing (someone ran DDL by hand). `docker compose run --rm migrate` re-installs them; then investigate — this is a stop condition ([OPERATOR.md §8](../docs/OPERATOR.md#8-stop-conditions)). |
| Login loops behind the proxy | `CRB_FORWARDED_ALLOW_IPS` does not include the proxy, so the app sees plain HTTP and refuses to set a `Secure` cookie. |

## 9. Builder in a sealed container (`CRB_BUILDER__EXECUTOR=docker`)

By default a builder attempt runs **on the worker host** in a `git worktree` of the main
clone — fine for development, but that worktree shares the clone's object store, which
contains the commit being replayed, and the agent runs with the worker's network. The
sealed-container mode ([ADR-0012](../docs/adr/0012-builder-in-a-sealed-container.md),
[SECURITY.md §3.2.1](../docs/SECURITY.md)) closes both by construction:

* the builder edits an **export** of the parent tree (`git archive` → `git init` → one
  commit): the gold commit is not in its object store, so no shell trick can reach it;
* the builder process runs in a **hardened container** (read-only root, `cap-drop=ALL`,
  non-root = the worker's uid, pid/memory/cpu caps) whose **only network is an internal
  bridge shared with one sidecar**: a CONNECT-only proxy that tunnels to the allowlisted
  host(s) and nothing else;
* the result is copied back (regular files only) into the real worktree and graded by the
  unchanged grader; anything that cannot be provisioned stops the run (`sandbox unavailable`).

### 9.1 Build the builder image

From the repository root, on top of the toolchain the repository under test needs (the
default base is the same `python:3.12` image the product uses; pass your Go / Node / JVM
sandbox image as `BASE_IMAGE` — it must be glibc-based and, if it has no `apt-get`,
already contain `git` and `ca-certificates`):

```bash
docker build -f deploy/Dockerfile.builder -t crb-builder:local .
docker build -f deploy/Dockerfile.builder -t crb-builder-go:local --build-arg BASE_IMAGE=<go sandbox image> .
docker run --rm crb-builder:local              # prints the pinned CLI version, as uid 65534
```

The image contains the Claude Code CLI as the npm package's **native binary** (pinned by
`CLAUDE_CODE_VERSION`, the version the adapter's argv is verified against) — no Node
runtime is added. Like sandbox images, it must be present in the host daemon's store
(`docker load` on an air-gapped host); the worker never pulls.

### 9.2 Configure the worker

```
CRB_BUILDER__EXECUTOR=docker
CRB_BUILDER__IMAGE=crb-builder:local              # required
CRB_BUILDER__PROXY_IMAGE=                          # sidecar image; default = IMAGE (needs python3 only)
CRB_BUILDER__ALLOW_HOSTS=api.anthropic.com         # host[:port], comma-separated; port defaults to 443
CRB_BUILDER__EGRESS_NETWORK=bridge                 # the docker network the SIDECAR reaches the endpoint from
CRB_BUILDER__MEMORY=4g  CRB_BUILDER__CPUS=2  CRB_BUILDER__PIDS_LIMIT=1024  CRB_BUILDER__TMP_SIZE=1g
CRB_BUILDER__USER=                                 # uid:gid; default = the worker's own; root refused
```

Add these to `deploy/.env` next to the sandbox settings; the worker needs the daemon
socket exactly as in §3. `/settings` (admin) shows the posture under `builder`, and the
API warns at start-up when `CRB_ENV=prod` and the executor is still `host`. For an
Azure OpenAI endpoint set `CRB_BUILDER__ALLOW_HOSTS=<resource>.privatelink.openai.azure.com`
(the sidecar resolves it through the host's DNS, so the private zone applies).

What one attempt does, exactly:

```
docker network create --internal --driver bridge crb-b-<task>-<id>
docker run -d --name crb-proxy-<task>-<id> --network=<EGRESS_NETWORK> --read-only --cap-drop=ALL \
  --security-opt no-new-privileges --user <uid:gid> --pids-limit=64 --memory=256m \
  --tmpfs /tmp --mount type=bind,src=<CRB_HOME>/…/crb-egress-<id>.py,dst=/opt/crb/egress_proxy.py,readonly \
  <PROXY_IMAGE> python3 /opt/crb/egress_proxy.py --listen 0.0.0.0:3128 --allow <ALLOW_HOSTS>
docker network connect --alias proxy crb-b-<task>-<id> crb-proxy-<task>-<id>     # wait for READY
docker run --rm --name crb-build-<task>-<id> --init --network=crb-b-<task>-<id> \
  --memory=4g --cpus=2 --pids-limit=1024 --user <uid:gid> --cap-drop=ALL \
  --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,size=1g \
  --mount type=bind,src=<sealed checkout>,dst=/work \
  --env ANTHROPIC_API_KEY --env CLAUDE_CODE_OAUTH_TOKEN         # names only; values from the client env \
  --env HTTPS_PROXY=http://proxy:3128 --env HOME=/tmp --env CI=1 … \
  --workdir /work --stop-timeout=<wall clock> <IMAGE> claude -p … --output-format stream-json …
docker rm -f crb-proxy-<task>-<id>; docker network rm crb-b-<task>-<id>
```

The sealed checkout lives next to the trial worktree under `$CRB_HOME` — which is why, as
for sandboxes, `$CRB_HOME` must be the **same path** on the host and in the worker
container (§3).

### 9.3 Prove it locally (colima / Docker Desktop)

```bash
colima start                                       # or Docker Desktop; `docker info` must answer
docker build -f deploy/Dockerfile.builder -t crb-builder:local .
.venv/bin/pytest -q tests/test_builders_container.py tests/test_builders_container_docker.py
```

The first file needs no daemon (the export's guarantees, copy-back, the `docker run`
argv, the proxy's policy in process). The second runs against the daemon with a
**scripted builder** standing in for `claude -p` — it edits the source and runs the target
tests *inside* the container, the result is graded clean on the host — and proves from
inside the container: read-only root, non-root uid, no host path visible, the credential
in the environment but never on argv, `example.com` refused by the sidecar (`403`) while
a mock endpoint on the allowlist is reachable and direct sockets fail; the
`network`-marked test finishes with a zero-spend TLS handshake to `api.anthropic.com`
through the tunnel. Nothing is left behind: the tests assert the sidecar, the network and
the sealed checkout are gone.

| Symptom | Cause / fix |
|---|---|
| run stops with `sandbox unavailable: docker image 'crb-builder:local' is not present` | Build or `docker load` the image on the worker's daemon (§9.1). |
| `sandbox unavailable: egress proxy unhealthy (no READY line)` | `PROXY_IMAGE` has no `python3`, or the sidecar cannot bind 3128 as the configured uid. `docker logs` of a `crb-proxy-*` container from a `retain` run shows why. |
| the builder reports `model_error: … 403` / cannot reach the endpoint | The endpoint's host is not on `CRB_BUILDER__ALLOW_HOSTS` (the sidecar's log line says `deny host:port`), or the sidecar's `EGRESS_NETWORK` has no route to it (§6 host firewall). |
| `refusing to run the builder container as root` | The worker runs as uid 0; set `CRB_BUILDER__USER` to a non-root `uid:gid` that can write `$CRB_HOME`. |
