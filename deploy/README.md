# Deploying crb on a single host (Docker Compose)

The reference single-host deployment: PostgreSQL 16, a one-shot migration, the API (+ UI)
and one worker, all from one image built by `deploy/Dockerfile`. For Kubernetes see
[`helm/crb`](helm/crb/README.md); for the Azure/Entra/Key Vault specifics, air-gap posture
and the full upgrade/backup procedures see [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
Operating the product once it is up is [docs/OPERATOR.md](../docs/OPERATOR.md).

Contents: [1 Quickstart](#1-quickstart) · [2 TLS](#2-tls-in-front-of-the-api) ·
[3 Sandbox (docker socket)](#3-let-the-worker-sandbox-tests-docker-socket-opt-in) ·
[4 Backup & restore](#4-backup-and-restore) · [5 Upgrade](#5-upgrade) ·
[6 Air-gap](#6-air-gap-egress-only-to-the-model-endpoint) · [7 Azure OpenAI](#7-azure-openai-in-your-tenant) ·
[8 Troubleshooting](#8-troubleshooting)

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

Sandbox images are yours to build (one per repository or toolchain, runnable as uid 65534
with a read-only root — [OPERATOR.md §2](../docs/OPERATOR.md#2-configure-a-repository)).
They must be present in the host daemon's image store: `docker pull`/`docker load` them on
the host; the worker never pulls from a registry.

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
reach the network regardless of the host policy.

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
| Runs are `blocked`, health shows the sandbox unavailable | The worker has no daemon socket (§3), the sandbox image is missing from the host daemon, or `docker info` fails as the socket's group. Nothing ran on the host; re-run after fixing. |
| Sandboxes start with an empty `/work` | `CRB_HOST_DIR` differs from `/srv/crb` or is a named volume; the paths must match (§3). |
| `/api/v1/health` reports `append_only: false` | The triggers are missing (someone ran DDL by hand). `docker compose run --rm migrate` re-installs them; then investigate — this is a stop condition ([OPERATOR.md §8](../docs/OPERATOR.md#8-stop-conditions)). |
| Login loops behind the proxy | `CRB_FORWARDED_ALLOW_IPS` does not include the proxy, so the app sees plain HTTP and refuses to set a `Secure` cookie. |
