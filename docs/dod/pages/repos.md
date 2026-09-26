---
id: dod.page.repos
level: page
name: Repos
scope: /repos
parent: dod.journey.connect-a-repository
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Repos

**Purpose.** "Every repository this deployment knows, with its probe status and task counts.
The journey's Connection page is the same list with the walk beside it." (About block,
`help.ts`; eyebrow `Instrument · Repositories`.)

**Entry → exit.** No nav link or in-app link leads here: the route is reached by URL only
(the walkthroughs and the GitHub-App-less onboarding guide use it). Leave by clicking a row or
its name (`/repos/:name`), or by *Add repo*, which registers the repository and opens its
page (`/repos/:name`), not its walk.

**Non-goals.** Does not show where a repository is on the walk (Connection does); does not
probe, mine or measure; does not edit configuration (the repository's Configuration tab).

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| repos.purpose.1 | PURPOSE | The About block states the job in one sentence and says the Connection page is the same list with the walk beside it | `hint:about:/repos` · `vitest:ui/src/components/Help.test.tsx::"says, on each screen whose definition of done quotes it, the sentence that record quotes"` | met | |
| repos.entry-exit.2 | ENTRY-EXIT | The page is reachable from the product (a link on Connection or on the repository page), every row opens its repository, and Add repo lands on the new repository's page; the empty state tells a viewer to ask an operator | `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"Add repo via URL with a preset and runner options"` | partial | G-228 |
| repos.truth.3 | TRUTH | Each row's probe, tasks, gold-clean, hard and last-run cells show the same values `GET /repos` returns for that repository, the probe pill's accessible label names its state, and the list is not silently truncated beyond the default page | `route:GET /repos` · `hint:about:/repos` · `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"back on the repo page the probe pill is OK with the runner summary"` | partial | G-229 |
| repos.actions.4 | ACTIONS | Add repo: a preset fills language, runner, layout and belt scope; invalid runner-options JSON, a bad URL and an empty explicit belt list are refused client-side with the reason; a 422 renders the server envelope; on 201 the new repository's page opens | `vitest:ui/src/screens/Repos/RepoNewDialog.test.tsx::"a preset fills the layout, runner options and belt scope"` · `vitest:ui/src/screens/Repos/RepoNewDialog.test.tsx::"refuses invalid runner-options JSON and a non-object, then recovers"` · `vitest:ui/src/screens/Repos/RepoNewDialog.test.tsx::"renders the server error envelope on a 422"` · `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"Add repo via URL with a preset and runner options"` · `route:POST /repos` | met | |
| repos.explanation.5 | EXPLANATION | Every column header, pill and button carries a hint the ratchet enforces (floor 8; the open Add dialog floor 20); the probe column's hint opens on hover with the registry copy; the About block links Configure a repository and Register a repository | `hint:ratchet:/repos` · `hint:about:/repos` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"names one element on every instrument screen"` · `doc:docs/OPERATOR.md#2-configure-a-repository` | met | |
| repos.evidence.6 | EVIDENCE | The list screen has its own unit test (rows, probe pill states, empty state per role) beside the dialog's; tier-1 walkthroughs register through it and read the probe pill back; 11-screens walks it for four personas at 375 and 1280 and opens the Add dialog to prove a hint paints in the top layer | `vitest:ui/src/screens/Repos/ReposPage.test.tsx::"each row shows the served name, runner, probe state and counts"` · `vitest:ui/src/screens/Repos/ReposPage.test.tsx::"an operator is offered Add repo, and Add the first repo on an empty list"` · `vitest:ui/src/screens/Repos/ReposPage.test.tsx::"a viewer is offered neither button and is told to ask an operator"` · `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"back on the repo page the probe pill is OK with the runner summary"` · `spec:ui/e2e/walkthrough/repo-config.spec.ts::"register a repo with a bare config (no runner options, TARGET_ONLY belt)"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | met | |
| repos.roles.7 | ROLES | Only an operator sees Add repo and Add the first repo; a viewer's empty state reads "Ask an operator to add one."; the API answers 403 to a viewer on POST /repos and records repo.created | `vitest:ui/src/screens/Repos/ReposPage.test.tsx::"an operator is offered Add repo, and Add the first repo on an empty list"` · `vitest:ui/src/screens/Repos/ReposPage.test.tsx::"a viewer is offered neither button and is told to ask an operator"` · `test:tests/test_server_routes_repos.py::test_rbac` · `test:tests/test_server_routes_repos.py::test_create_validates_and_records_event` · `route:POST /repos` | met | |
| repos.operations.8 | OPERATIONS | The list is the operator guide's §2 entry point and the CLI's crb repo add is its equal; a stack whose store is down answers the page with an error state and retry, and /health says why | `doc:docs/OPERATOR.md#2-configure-a-repository` · `route:GET /health` · `route:GET /repos` | met | |
| repos.accessibility.9 | ACCESSIBILITY | axe WCAG 2.1 AA is clean on the list with a row present and at 375 and 1280 with a hint open; the Add dialog is modal, its hint paints in the top layer and one Escape closes the bubble, not the dialog | `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"Repos and Runs have no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | met | |
| repos.non-goals.10 | NON-GOALS | The About block says the walk lives on the Connection page, so this list is not asked to show stages | `hint:about:/repos` · `vitest:ui/src/components/Help.test.tsx::"says, on each screen whose definition of done quotes it, the sentence that record quotes"` | met | |

## Gaps
- **G-228** — nothing in the product links to /repos (no to="/repos" in ui/src); help.ts says "Add a repository here or from Connection" but only a typed URL reaches "here" · add a "All repositories" LinkButton on the Connection page header (or retire the route into Connection and redirect) · ui
- **G-229** — ReposPage reads useRepos (unpaged GET /repos, default page) while every journey screen reads useAllRepos (paged to 500): a deployment past the default page is truncated here without a count · switch ReposPage to useAllRepos and show "n of total" in the caption · ui
