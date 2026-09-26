# crb Helm chart

Minimal, hardened chart for Commit Replay Bench: `api` Deployment + Service (+ optional
Ingress/TLS, PDB, ServiceMonitor), `worker` Deployment with a PVC work directory and three
sandbox modes, a `migrate` Job as a `pre-install,pre-upgrade` hook, a ConfigMap for plain
settings, default-deny NetworkPolicies with CIDR allowlists, and an **evaluation-only**
embedded PostgreSQL. No subcharts: it lints, templates and installs offline.

The worked deployment (Azure: Entra ID, Key Vault, private endpoints, egress) is in
[docs/DEPLOYMENT.md §3–4](../../../docs/DEPLOYMENT.md).

```bash
kubectl create namespace crb
kubectl -n crb create secret generic crb-secrets \
  --from-literal=CRB_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=CRB_DATABASE_URL='postgresql+psycopg://crb:<pw>@<host>:5432/crb?sslmode=require' \
  --from-literal=CRB_BOOTSTRAP_ADMIN__PASSWORD='<≥12 chars>' \
  --from-literal=AZURE_OPENAI_API_KEY='<from Key Vault>'
helm lint deploy/helm/crb --strict
helm upgrade --install crb deploy/helm/crb -n crb -f my-values.yaml
```

Key values (see `values.yaml` for all, every default is the secure choice):

| Value | Meaning |
|---|---|
| `image.repository` / `image.tag` / `image.digest` | pin by digest in production |
| `existingSecret` | Secret holding `CRB_SECRET_KEY`, `CRB_DATABASE_URL`, optional client secrets / API keys. The chart never renders secret values and refuses secret-looking keys under `config` |
| `config.*` | plain `CRB_*` environment (OIDC issuer/client id, model endpoint, sandbox executor/image) |
| `postgresql.mode` | `external` (managed server; URL in the Secret) or `embedded` (evaluation only) |
| `worker.sandbox.mode` | `none` (fail-closed; runs `failed`, `sandbox unavailable`), `dind` (privileged sidecar, pod-scoped), `hostSocket` (node's docker.sock — dedicated node pool only) |
| `worker.workDir` | PVC (default, resumable) or emptyDir |
| `secretsStore` | the one claim the API and the worker both mount at `CRB_SECRETS_DIR` (the stored Claude Code login and tracker token): the chart makes a ReadWriteOnce claim and pins both pods to one node, or name your own ReadWriteMany claim (`existingClaim`, `accessMode: ReadWriteMany`) to lift the pin. With the pin, `api.nodeSelector` / `api.tolerations` must equal the worker's (the render refuses a difference); back the claim up or supply the credentials again after a restore (docs/DEPLOYMENT.md §5) |
| `networkPolicy.*` | `apiIngress` peers, `postgres.cidrs`, `modelEndpoint.cidrs` (worker), `oidc.cidrs` (api), `extraEgress` |
| `ingress.*` | host, class, TLS secret |
| `podSecurityContext` / `containerSecurityContext` | non-root 10001, read-only root, no capabilities, RuntimeDefault seccomp |

Verify a render before installing:

```bash
helm template crb deploy/helm/crb -f my-values.yaml | kubeconform -strict -kubernetes-version 1.30.0 -ignore-missing-schemas
```
