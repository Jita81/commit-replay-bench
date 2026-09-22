---
id: dod.page.connect
level: page
name: Connect a repository
scope: /connect
parent: dod.journey.connect-a-repository
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Connect a repository

**Purpose.** "Connect a repository so the instrument can learn how its code tests itself.
Nothing is written to the repository at this stage and no model is called." (About block,
`help.ts`; eyebrow `Journey · 1 of 4 · Connection`.)

**Entry → exit.** Arrive from the journey nav (Connection), from Home tasks 1, 2 and 5, from
the empty state of every downstream screen (Baseline, Decisions, Factory, Sign-off, Map grid,
Routes, Oracle), or from the GitHub App's setup callback (`/connect?installation=<id>`, which
opens the picker). Leave with a repository row: creating one from either dialog opens its walk
(`/connect/:name`); an existing row's name links to its walk and its door reads *Continue*
(walk) or *Baseline* (`/results?repo=`) once every stage is done.

**Non-goals.** Does not edit a repository's configuration (Configuration on `/repos/:name`);
does not run a stage (the walk); does not register the GitHub App (Settings); does not write
to the repository or call a model.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| connect.purpose.1 | PURPOSE | The About block states the job in one sentence and the eyebrow reads "Journey · 1 of 4 · Connection", derived from JOURNEY_STEPS | `hint:about:/connect` · `code:ui/src/components/Layout.tsx::journeyEyebrow` · `vitest:ui/src/help/hints-ratchet.test.tsx::"a journey eyebrow carries nav.journey_position"` | met | |
| connect.entry-exit.2 | ENTRY-EXIT | A repository created from either dialog lands on its walk; every row's name links to its walk and its door reads Continue or Baseline; the setup callback's ?installation= opens the picker; the empty state names the six stages and offers Connect | `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"lists connected repositories with their next stage"` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"door is named Baseline, the same as the nav, and opens the baseline"` · `vitest:ui/src/screens/Connect/GitHubConnectDialog.test.tsx::"the Connect screen opens the picker on ?installation= (the setup callback lands there)"` | met | |
| connect.truth.3 | TRUTH | The Tasks cell shows the mined total and the gold-clean count as counts from GET /repos (no rate, no interval); the Next stage pill is derived from the same three reads the walk uses; the About block's numbers line says what each count is | `route:GET /repos` · `hint:about:/connect` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"lists connected repositories with their next stage"` · `code:ui/src/screens/Connect/connection.ts::stagesFor` | met | |
| connect.truth.4 | TRUTH | A per-row read of the oracle, controls or map that fails for a reason other than 404 is shown on that row as an error with retry, never as a stage state | `absent` | unmet | G-124 |
| connect.actions.5 | ACTIONS | Connect from GitHub lists the installation's repositories, pre-fills name, language and runner, and Connect creates the row and opens its walk; a refused attempt shows the server envelope in the dialog and clears when the mode changes; an unconfigured app is a state that offers Connect by URL | `vitest:ui/src/screens/Connect/GitHubConnectDialog.test.tsx::"lists the installation and its repositories, pre-fills the pick, and connects"` · `vitest:ui/src/screens/Connect/GitHubConnectDialog.test.tsx::"link mode says it is loading, describes its hint to the select, and a refused attempt's alert clears when the mode is switched"` · `vitest:ui/src/screens/Connect/GitHubConnectDialog.test.tsx::"an unconfigured app is a state with the URL fallback"` · `route:POST /github/installations/{id}/connect` | met | |
| connect.actions.6 | ACTIONS | Connect by URL refuses http://, local paths and invalid runner-options JSON client-side with the reason, renders the 422 envelope from the server, and on 201 opens the walk | `vitest:ui/src/screens/Repos/RepoNewDialog.test.tsx::"rejects a local path or http:// as a git URL but accepts it as a clone path"` · `vitest:ui/src/screens/Repos/RepoNewDialog.test.tsx::"refuses invalid runner-options JSON and a non-object, then recovers"` · `vitest:ui/src/screens/Repos/RepoNewDialog.test.tsx::"renders the server error envelope on a 422"` · `route:POST /repos` | met | |
| connect.actions.7 | ACTIONS | Link to an existing repository moves only the row's URL and records repo.github_linked; Sync installations records an installation GitHub sent back unverified, after the deployment verifies it, and the banner on the dialog says so | `vitest:ui/src/screens/Connect/GitHubConnectDialog.test.tsx::"link mode lists the repositories without a GitHub link, posts the link and selects the repository"` · `test:tests/test_server_github_app.py::test_link_attaches_an_installation_repository_to_an_existing_row` · `test:tests/test_server_github_app.py::test_sync_records_every_installation_and_suspends_vanished_ones` · `route:POST /github/installations/sync` | partial | G-128 |
| connect.explanation.8 | EXPLANATION | Every column header, pill and button carries a hint the ratchet enforces (floor 8 per role); the About block links Register a repository, Connect through the GitHub App and Configure a repository from the UI | `hint:ratchet:/connect` · `hint:about:/connect` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"every column header, pill and button on the list carries a hint"` · `doc:docs/GITHUB-APP.md#4-connect-a-repository` | met | |
| connect.evidence.9 | EVIDENCE | The list, its doors and both dialogs are unit-tested; the route is walked by 11-screens for four personas at 375 and 1280; a tier-1 walkthrough presses Connect by URL on this page and lands on the walk | `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"lists connected repositories with their next stage"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` | partial | G-125 |
| connect.roles.10 | ROLES | Only an operator sees Connect from GitHub, Connect by URL and the empty state's Connect; the API answers 403 to a viewer on POST /repos and the GitHub connect, and records repo.created with the actor | `test:tests/test_server_routes_repos.py::test_rbac` · `test:tests/test_server_routes_repos.py::test_create_validates_and_records_event` · `route:POST /repos` | partial | G-126 |
| connect.operations.11 | OPERATIONS | GET /github/app answers configured:false as a state, never a 404; crb doctor's github_app line names a half-configured app; the operator and GitHub App guides describe this screen step by step | `route:GET /github/app` · `test:tests/test_server_github_app.py::test_unconfigured_app_is_a_state_not_an_error` · `doc:docs/OPERATOR.md#11-check-the-installation-crb-doctor` · `doc:docs/OPERATOR.md#20-connecting-and-configuring-a-repository-from-the-ui` · `doc:docs/GITHUB-APP.md#3-install-it-once-per-organisation` | met | |
| connect.accessibility.12 | ACCESSIBILITY | axe WCAG 2.1 AA is clean at 375 and 1280 with a hint bubble open, the top bar is at most two rows at 375, the table scrolls inside a labelled region, and every column including the door column has an accessible header | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` | partial | G-127 |
| connect.non-goals.13 | NON-GOALS | The About block states that nothing is written to the repository at this stage, that no model is called, and that a repository with 0 gold-clean tasks cannot be measured | `hint:about:/connect` · `vitest:ui/src/components/Help.test.tsx::"says, on each screen whose definition of done quotes it, the sentence that record quotes"` | met | |

## Gaps
- **G-124** — a per-row 5xx on GET /oracle/{name}, /oracle/{name}/controls or /capability-map is passed to stagesFor as undefined and the row shows no error (ConnectPage.tsx RepoRow) · render a compact ErrorState in the Next stage cell when any of the three reads is isError and not 404 · ui
- **G-125** — no walkthrough presses Connect by URL or Connect from GitHub on /connect; tier-1 onboarding registers through /repos "Add repo" (02-repo-onboard.spec.ts) · add one tier-1 case to 02-repo-onboard.spec.ts that opens /connect, presses Connect by URL and asserts the landing on /connect/:name (the GitHub path stays offline, tier 2) · ui
- **G-126** — no unit test asserts that a viewer on /connect sees neither connect button nor the empty state's Connect · add a viewer case to ConnectPage.test.tsx asserting no button named /Connect/ is rendered · ui
- **G-127** — the door column's header is an empty th (ConnectPage.tsx), so a screen-reader user gets no name for the Baseline/Continue column · give the th visually hidden text ("Next") under a col.connect hint id · ui
- **G-128** — the "installation not on record" banner and the Sync installations act are not unit-tested in the dialog (GitHubConnectDialog.test.tsx has no case for data-testid installation-unrecorded) · add a case landing on ?installation=&unverified=1 that asserts the banner and that Sync posts /github/installations/sync and selects the installation · ui
