# The GitHub App — connecting an enterprise's repositories

<!--
Navigation
----------
What it is:   The operator guide for the GitHub App: registering it once per deployment,
              installing it per organisation on selected repositories, what each permission
              is for, and how the product uses the installation to clone (measurement) and,
              only where granted, to deliver (a branch and a pull request).
What it does: Makes "connect a repository" the flow every comparable product uses — an
              org-level install with repository selection and short-lived tokens the product
              mints itself — so nobody hands the deployment a personal access token.
How:          `CRB_GITHUB__*` on the API and the worker; `GET /github/setup` as the app's
              Setup URL; the Connect screen's "Connect from GitHub"; `config_json.github` on
              a connected repository names the installation.
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/server/github_app.py, src/crb/server/routes/github.py,
              src/crb/server/worker.py (clone + delivery), docs/SECURITY.md (§2 egress, §3
              secrets), docs/DEPLOYMENT.md (the environment table), docs/API.md "GitHub App",
              docs/reviews/2026-09-17-enterprise-front-end.md §3 (why this pattern)
Tested by:    tests/test_server_github_app.py, ui/src/screens/Connect/GitHubConnectDialog.test.tsx
Touch when:   a permission is added (say what for); GitHub Enterprise Server needs a note.
-->

## 1. Why an app, not a token

A personal access token belongs to a person, outlives their role, and grants whatever that
person can see. A **GitHub App** belongs to the deployment: an organisation admin installs it
on *selected* repositories, GitHub records exactly which, and the product mints
**installation tokens** — scoped to that installation — on demand. The one-hour token
lifetime is GitHub's documented contract for installation tokens, not something this product
measures; what the product does with the token is **[measured]**: minted per use with the
app JWT, cached in memory until five minutes before the `expires_at` GitHub returned, never
persisted, passed to git as a one-shot header and never on argv
(`tests/test_server_github_app.py::test_installation_tokens_are_minted_with_the_jwt_cached_and_refreshed_near_expiry`
and `::test_worker_clones_with_the_installation_token_in_the_environment_never_argv` — a
fake GitHub transport, 10 cases in the file, apparatus 2.2; the fake returns `expires_at`
one hour out, a second call inside that hour re-uses the token, and a token inside the
five-minute margin is re-minted). Nothing is handed over; nothing
long-lived is stored. That the named vendors connect this way is **[hypothesis]** drawn from
their public documentation (the research brief, §3), not measured here.

The product needs very little:

| Permission | Level | For |
|---|---|---|
| **Metadata** | read | list the installation's repositories (the picker) |
| **Contents** | read | clone the repository to mine and grade — **all measurement needs only this** |
| Contents | write | *factory delivery only*: push the `crb/<item>` branch |
| Pull requests | write | *factory delivery only*: open the pull request |

Install with read-only permissions first. Grant the two write permissions only to the
installations whose repositories the factory may deliver to — the Connect screen and the
Settings card say "can deliver" / "read-only" per installation, and the route gate
(ADR-0003, amendment 2026-09-16) still decides *whether* a given change may be delivered.
The product never pushes to a default branch (ADR-0006's delivery rule is unchanged).

## 2. Register the app (once per deployment)

In the organisation that owns the deployment (or a personal account for a trial):
*Settings → Developer settings → GitHub Apps → New GitHub App*.

| Field | Value |
|---|---|
| Name | anything (`crb-bench-<org>`); the **slug** GitHub derives is `CRB_GITHUB__APP_SLUG` |
| Homepage URL | the deployment's UI |
| **Setup URL** | `https://<deployment>/api/v1/github/setup` — tick *Redirect on update* |
| Webhook | *inactive* (not needed; installations are synced on demand) |
| Repository permissions | Metadata: read, Contents: read (+ Contents: write, Pull requests: write if the factory will deliver) |
| Where can this app be installed? | *Only on this account* for a single-org deployment; *Any account* for a multi-org one |

Then **Generate a private key** (a `.pem` download) and note the **App ID**.

Configure the API **and** the worker with the same values (one environment configures both):

```
CRB_GITHUB__APP_ID=123456
CRB_GITHUB__APP_SLUG=crb-bench-acme
CRB_GITHUB__PRIVATE_KEY_FILE=/run/secrets/github-app.pem      # or CRB_GITHUB__PRIVATE_KEY=<PEM text>
# GitHub Enterprise Server only:
# CRB_GITHUB__API_URL=https://ghes.example/api/v3
# CRB_GITHUB__WEB_URL=https://ghes.example
```

Put the key in the secret store the deployment already uses (Key Vault → mounted file, or a
Kubernetes secret; docs/DEPLOYMENT.md §2.4). `GET /settings` reports `private_key_configured`
— never the key. `GET /github/app` says `configured: true` when both values are present.

## 3. Install it (once per organisation)

Settings → GitHub App shows **Install on an organisation ↗** (`https://github.com/apps/<slug>/installations/new`).
The org admin chooses **Only select repositories** and picks them. GitHub then sends the
admin to the Setup URL; the API verifies the installation with the app's own credential
(`GET /app/installations/{id}`), records it (`github_installations`, plus a
`github.installation.recorded` event), and lands the browser on **Connect** with the picker
open on that installation. The installer needs the **operator** role in crb (the callback is
a signed-in route); an org admin who is not a crb operator can still install — an operator
then presses **Sync installations**.

Adding repositories later: the org admin edits the installation's repository access in GitHub;
the picker reads live from GitHub, so they appear on the next open.

## 4. Connect a repository

*Connect → Connect from GitHub*: choose the installation, find the repository, pick it. The
form pre-fills the crb name (`owner-repo`), the language GitHub reports and that language's
default runner (`python → pytest`, `go → go`, `javascript → node`, `jvm → maven`,
`rust → cargo`); confirm or change them. Source and test layout (`src_prefix`,
`test_prefix`, belt scope) can be set here or afterwards under Configuration — the probe
stage verifies the runner either way.

What the API records: an ordinary repository row whose `url` is the https clone URL and whose
`config_json.github` is `{installation_id, full_name, default_branch, html_url, private}`.
A config update keeps that link. The row carries no token.

### Linking a repository you already measured

A repository connected by URL before the app existed — or one whose history now lives on a
fork the app can see (`cobra`, measured on `spf13/cobra`, delivered on `Jita81/cobra`) —
keeps its name, and with it its ledger rows, its capability map and its sign-offs. Pick the
GitHub repository as above, then choose **Link to an existing repository** and select the
crb repository (only repositories with no GitHub link are offered). The API
(`POST /repos/{name}/github-link`) changes the row's `url` to the clone URL and writes the
same `config_json.github` link; language, runner, layout and belt scope are left as measured
(edit them under Configuration if the fork differs), and an existing clone is kept. The act
is recorded as a `repo.github_linked` event carrying the URL before and after, so the seam
is visible on the repository's events rather than a silent edit; linking the row to another
repository later replaces the link and records the previous `full_name`. A GitHub repository
already linked to a different crb repository is refused (409) — one repository, one row.

## 5. What happens at clone and at delivery

- **Clone** (any run): the worker sees `config_json.github.installation_id`, mints an
  installation token (cached until five minutes before its one-hour expiry), and clones with
  it as a one-shot `Authorization` header passed through git's `GIT_CONFIG_COUNT`
  environment mechanism — never on the command line, never in `.git/config`, never in an
  event or a log (`repo.clone.start` carries `github_app: true` and the redacted URL only).
- **Delivery** (a factory run with `deliver: true`, after the route gate): the same
  installation's token pushes the `crb/<item>` branch and opens the pull request against the
  repository's default branch. If the installation is read-only, delivery fails closed —
  recorded as `delivery_failed`, no branch, no PR — and the Settings card says why.

## 6. Federated use

- **One app, many organisations.** Register the app once; each organisation installs it on
  its own selection. `GET /github/app` lists every installation; the picker is per
  installation, so a platform team can connect repositories for several orgs from one
  deployment while each org's admin controls what the app may see.
- **Least privilege by default.** Read-only installations measure; write is granted per
  installation, and only after the map has earned a `deliver` route somewhere.
- **Revocation is GitHub's.** Uninstall the app or remove a repository from the selection
  and the next token mint fails; **Sync installations** marks the installation
  *uninstalled* on record. No token to rotate on the crb side.
- **Audit.** Installations recorded, repositories connected, and every clone and delivery
  are events on the trace; the GitHub side has its own audit log of the app's actions.

## 7. Trial without the app

A trial that cannot register an app yet uses *Connect by URL* (a public repository, or a
private one the worker's own git credentials can reach). Everything after registration is
identical; the app can be added later and existing repositories keep working.
