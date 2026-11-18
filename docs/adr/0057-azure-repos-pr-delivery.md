# ADR-0057 — Azure Repos pull request delivery, attached to the Azure DevOps ticket

**Status:** Proposed (DL-425)
**Date:** 2026-11-18
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. No grade, belt, row or route changes.
The switch is off by default; with it off every request, header, event and stored row is the
same as before.
**Builds on:** ADR-0017 (the ticket is the backlog item; the Azure DevOps adapter and its link
verb), ADR-0021 (review before delivery; the pull request seams and the close on a later
non-accept) and ADR-0014 (the GitHub App, the other way a delivering run gets a token).

## Context

A team that keeps its work on an Azure DevOps board usually keeps its code in Azure Repos in
the same organisation. Today such a team can connect its board (ADR-0017) but a ticket that
passes the gap check cannot end in a pull request:

1. The pull request seams (`open_pr_fn`, `comment_pr_fn`, `close_pr_fn`) have one
   implementation, for GitHub.
2. Delivery, clone and fetch get a token only from the GitHub App, so a private Azure
   repository cannot even be fetched; the run ends `FetchRefused`.
3. `repository_of` reads `dev.azure.com/{org}/{project}/_git/{repo}` as `{org}/{project}`,
   so two repositories in one project look the same to the re-delivery checks
   (`assert_same_repository`, `repository_mismatch`).
4. The pull request targets `main` when the repository's link names no default branch;
   Azure repositories often use `master` or a branch of their own.
5. The Azure DevOps adapter attaches every link as a `Hyperlink`. Azure shows a pull request
   in a work item's Development section only when it is attached as an `ArtifactLink` whose
   URL is `vstfs:///Git/PullRequestId/{projectId}%2F{repoId}%2F{prId}`.
6. Azure DevOps caps a pull request description at 4000 characters; the product's pull
   request body can be longer.

## Decision

1. **A second implementation of the existing seams.** `crb.factory.delivery_azure` provides
   `azure_open_pr_fn`, `azure_comment_pr_fn` and `azure_close_pr_fn` with the same keyword
   signatures as the GitHub ones, over the Azure DevOps REST API at `api-version=7.1`, with
   the standard library only and an injectable `urlopen`. The loop is not changed.
2. **The tracker's token, only inside the board's organisation, only when switched on.**
   `CRB_FACTORY__AZURE_REPOS_DELIVERY` (default false) turns it on. A delivering run with no
   GitHub App link uses Azure Repos only when the switch is on, the tracker is Azure DevOps,
   and the remote (https `dev.azure.com/{org}/…/_git/{repo}` or `{org}.visualstudio.com/…`) is
   in the same organisation as the board's https address. The organisation is compared, not
   the host, because every organisation shares `dev.azure.com`. Any other remote gets no
   token. The token is read from the secret store at each push, clone and fetch and never
   kept; it travels only as `Authorization: Basic base64(":" + token)`, never in a URL, and
   every error text is redacted and has the token and its base64 forms removed.
   For git the header is scoped to the remote's own URL on push, clone and fetch, and push,
   clone and fetch follow no redirect for that URL
   (`http.<url>.followRedirects=false`, which an unscoped or host-wide setting cannot
   switch back on). The REST client follows no redirect either: a 3xx is a
   refusal with its status, so the header never reaches a host a redirect names.
3. **Opening is idempotent without a retry.** Azure answers 409 when an active pull request
   already joins the same source and target. The client then searches for active pull
   requests on that pair and adopts the one match; zero or more than one is a refusal. The
   request that opens a pull request is never sent twice.
4. **The repository key is `org/project/repo`.** `repository_of` returns the lower-cased
   `org/project/repo` for an Azure remote, so the re-delivery checks tell two repositories in
   one project apart. GitHub remotes give the same key as before.
5. **The target branch is the remote's default branch.** A fetch never refreshes the
   clone's `origin/HEAD`, so before each run the worker asks the remote which branch its
   `HEAD` names (`git ls-remote --symref`, with the same scoped header), fetches that branch
   and points `origin/HEAD` at it; the pull request targets `origin/HEAD`. When the remote
   names none, or `origin/HEAD` cannot be read, the run is refused before any build; the
   product does not guess `main`.
6. **A long description is cut, and says so.** Over 4000 characters it is cut at a line
   boundary, an open code fence is closed, and one line says the text was cut at Azure
   DevOps's limit and that the full summary is in the evidence pack. The recorded body hash
   is still the hash of the full body.
7. **The ticket gets Azure's own pull request link.** With the switch on, the Azure DevOps
   adapter's existing `link` verb, given a pull request on Azure Repos in the board's own
   organisation, reads the pull request for its artifact id and attaches one `ArtifactLink`
   named "Pull Request", unless the work item already has that link or a `Hyperlink` to the
   same address. With the switch off it reads no pull request. A pull request it cannot read,
   one in another organisation and every other URL get a `Hyperlink` as before. The six
   tracker verbs are unchanged.

## Consequences

- An Azure DevOps team can go from a ticket to a pull request on its own repository with one
  token, and the pull request shows on the ticket where Azure users look for it.
- The tracker token now needs the Code (Read & Write) scope as well as Work Items (Read &
  Write) when the switch is on. The operator opts in; docs/OPERATOR.md says which scopes.
- A new outbound flow, Azure Repos API, is listed in docs/SECURITY.md and docs/DEPLOYMENT.md
  and pinned by the egress test, off by default.
- An Azure pull request link costs three tracker requests the first time and two on a
  repeat [hypothesis]. Method: source inspection of the adapter's `link` verb. The first link
  reads the pull request, reads the work item's relations and adds the link; a repeat finds
  the link in the relations and adds none. tests/test_intake_adapters.py pins both sequences
  against a scripted tracker; no live organisation has been counted. The first-pass request
  bound for intake does not count it, as it counts no pull request link.
- Azure shows the first 4000 characters of a long description; the evidence pack holds the
  rest.
- Not in this change: the delivery preflight and the Factory screen (an Azure delivering run
  is started through the API or MCP only), outcome sync for Azure pull requests, SSH remotes,
  Azure DevOps Server, repositories in another organisation and a separate repository token.
  The REST shapes are written from the published API and pinned by hermetic fixtures; they are
  not yet checked against a live organisation.

## Alternatives considered

- **A separate token for Azure Repos.** Rejected for now: two secrets for one organisation,
  and the tracker token already has to be stored. Kept as a later option for teams that want
  to scope them apart.
- **A provider registry for pull request hosts.** Rejected: one more provider does not need
  one; the seams already make the host a choice at the call site.
- **A new tracker verb, `attach_pr`.** Rejected: it changes the six-verb contract, the fake
  tracker and the lease wrapper for a behaviour the existing `link` verb can carry.
- **Hyperlink only.** Rejected: Azure's Development section shows `ArtifactLink` entries only,
  so the pull request would not appear where a team looks for it.
- **Retry the opening request on a lost answer.** Rejected: a second request could open a
  second pull request; adopting the single active match on a 409 gives the same safety
  without it.
