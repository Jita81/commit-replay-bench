# ADR-0014 — The GitHub App is the connection; a personal access token is not

**Status:** Accepted (operator decision DL-041; built in PR #31)
**Date:** 2026-09-17
**Apparatus impact:** none. Nothing here touches a belt, the routing rule, the sign-off policy
or a ledger row. It changes how a repository's bytes reach the worker and how a delivery's
branch reaches GitHub.

## Context

Until now a repository was registered by URL or clone path and cloned with whatever git on the
worker could reach; factory delivery read a long-lived token from `CRB_GIT_TOKEN`. That is
how a trial works and it is not how an enterprise with thousands of developers across many
teams connects anything. The research brief (`docs/reviews/2026-09-17-enterprise-front-end.md`
§3) found the same shape in every comparable product — GitHub's own Copilot and code-security
enablement, SonarQube, Snyk, Cortex, Compass, LinearB, Swarmia, Renovate: a **GitHub App
installed at organisation level on selected repositories**, minting **short-lived
installation tokens**, never a personal access token; org-level install → team-level
enablement → repository opt-in; ownership from the catalogue the enterprise already has.

The product's needs are small and separable: measurement needs `Metadata: read` and
`Contents: read`; delivery — a branch and a pull request, never the default branch
(ADR-0006) — needs `Contents: write` and `Pull requests: write`.

## Decision

1. **The deployment is a GitHub App.** One registration per deployment (`CRB_GITHUB__APP_ID`,
   a private key from the secret store, optionally a GHES `api_url`/`web_url`). Organisations
   install it on the repositories it may see; the product records each installation
   (`github_installations`) after verifying it with the app's own credential.
2. **Tokens are minted, never stored.** The worker mints an installation token when it clones
   or delivers, caches it in memory until five minutes before the expiry GitHub returned (one
   hour by GitHub's contract), and hands it to git as a one-shot `Authorization` header through
   `GIT_CONFIG_COUNT` — never argv, never `.git/config`, never a row, an event or a log. No API
   response carries a token. **[measured]** `tests/test_server_github_app.py` (fake GitHub
   transport, apparatus 2.2): the mint, the cache, the refresh at five minutes to expiry, the
   header in the environment and not in argv, and the absence of `ghs_` from every response
   and event payload the tests read.
3. **A connected repository is an ordinary repository.** `POST /github/installations/{id}/connect`
   registers a `Repo` row whose `url` is the https clone URL and whose `config_json.github`
   names the installation; every later run is unchanged. The link survives config updates.
4. **Write is per installation and explicit.** An installation without write permissions
   measures only; delivery fails closed on it. Granting write is the organisation admin's act
   in GitHub, visible on record as `can_deliver`; whether a given change may be delivered
   remains the route gate's decision (ADR-0003 amendment 2026-09-16) and, above it, an
   approver's.
5. **Connect by URL stays** for trials and for repositories outside GitHub; nothing about it
   changed.

## Consequences

- Nobody hands the deployment a credential that belongs to a person; revocation is GitHub's
  (uninstall, or narrow the selection) and takes effect at the next mint.
- Federation is native: one deployment, many organisations, each controlling its own
  selection; a platform team connects from one screen.
- The worker needs the same `CRB_GITHUB__*` as the API (one environment configures both);
  `docs/DEPLOYMENT.md` lists them.
- Not in this ADR: GitLab and Azure DevOps connectors (the same shape, different apps —
  backlog F21); enterprise-level (multi-org) installs on GitHub Enterprise Cloud; webhooks
  (installations are synced on demand, which is enough without a public endpoint).

## Alternatives considered

- **Personal access tokens per repository.** Rejected: a person's credential, long-lived,
  over-scoped, and the thing every security review asks about first.
- **Deploy keys.** Rejected: per-repository SSH keys to manage, no pull-request API, no
  repository selection an org admin controls in one place.
- **OAuth App (user-to-server).** Rejected: acts as a user, so audit attributes the clone and
  the PR to a person rather than to the deployment; token life is the user's session.
