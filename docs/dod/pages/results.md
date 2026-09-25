---
id: dod.page.results
level: page
name: Baseline
scope: /results
parent: dod.journey.read-the-map-and-decide
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Baseline

**Purpose.** What the evidence says about one repository, in the order it matters: is the
instrument trustworthy here, what may the builder be trusted to do, and what is waiting on a
person. This is the baseline the factory runs on. (`help.ts` About copy; eyebrow
`Journey · 2 of 4 · Baseline`.)

**Entry → exit.** Arrives from the nav step "Baseline", the Connect walk's "Baseline" button,
Home's "Read the baseline" task or a viewer's Continue; with no `?repo=` the most recently
updated repository is chosen. Leaves with the three gate readings, the route per cell with its
n, interval and apparatus, the licence sentence, and one of the doors: Open the full map
(`/capability?repo=`), Every route with its reason (`/routing?repo=`), Oracle and controls
(`/oracle?repo=`), The ledger (`/ledger?repo=`), All decisions (`/decisions`), a decision's act
(`/signoff`, `/ledger`, `/routing`, `/factory`) or Open the run (`/runs/:id`).

**Non-goals.** No repository-wide rate and no "the AI can do X%". No throughput or
cost-per-accepted-change headline: the ledger records neither human hours nor merge outcomes,
and the page says so. No act is taken here; every act is a link to the page that records it.
No economics tile reads an unknown cost or latency as zero, and none pools apparatus versions.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| results.purpose.1 | PURPOSE | The About block states the page's job in one sentence and the eyebrow reads "Journey · 2 of 4 · Baseline" | `hint:about:/results` · `vitest:ui/src/help/hints-ratchet.test.tsx::"a journey eyebrow carries nav.journey_position"` · `vitest:ui/src/components/Help.test.tsx::"renders the Baseline entry for a viewer: the four parts, the terms, the links"` | met | |
| results.entry-exit.2 | ENTRY-EXIT | With no `?repo=` the latest repository is chosen; with no repository the empty state leads to Connect; the five doors and every decision row carry the repository in their link | `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"with no ?repo= the most recently updated repository is chosen for you (replace, not push)"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"with no repository at all the empty state stays and leads to Connect"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"renders the instrument gates, the routes with n, what deliver means, and what waits on a person"` | met | |
| results.truth.3 | TRUTH | The three gate tiles (negative controls, oracle strength, false-Q1) each show n and the apparatus from the report; a 404 reads "not run" or "not scored", never an alert; the oracle bar is the policy's, not a constant | `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"every instrument tile carries n, an interval or an honest "95% CI —" with the reason, and the apparatus from the data"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"a controls or oracle 404 is "not run" / "not scored", never an alert"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"the bar in the oracle tile follows the policy in force, not a constant"` · `route:GET /oracle/{repo}/controls` · `route:GET /oracle/{repo}` | met | |
| results.truth.4 | TRUTH | Every map cell shows its route, n (and n_tasks), point, 95% Wilson interval and apparatus version; an unmeasured cell reads "not measured", never 0; the licence sentence quotes the stamped sign-off snapshot and says when the cell has moved on; a false-Q1 row makes the map read refuse with 409 | `vitest:ui/src/screens/Results/MapTable.test.tsx::"renders the sign-off state on the cell and the honest empty cells"` · `vitest:ui/src/screens/Results/MapTable.test.tsx::"the licence sentence quotes the STAMPED snapshot with every qualifier, says when the cell has moved on, and is null with no signed cell"` · `code:ui/src/screens/Results/MapTable.tsx::licenseSentence` · `test:tests/test_server_routes_capability.py::test_false_q1_row_refuses_the_map` · `code:src/crb/server/routes/capability.py::capability_map` | met | |
| results.truth.5 | TRUTH | The four economics tiles carry n and an interval with the apparatus that produced them: cost per attempt, cost per clean attempt and latency read the server's fold over the rows (n = attempts, or clean attempts, with a known value; a Student-t or delta-method t 95% interval with its method; the apparatus), an unknown is a dash with its reason, never zero; the clean rate carries a Wilson interval | `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"the economics tiles carry the known count as n, the served interval and the apparatus; an unknown is a dash with its reason (F35)"` · `test:tests/test_server_routes_capability.py::test_economics_per_cell_and_for_the_map` · `test:tests/test_economics.py::test_all_unknown_serves_no_value_and_says_why` · `hint:id:stat.results.cost_per_attempt` · `hint:id:stat.results.cost_per_clean` · `hint:id:stat.results.latency` · `hint:id:stat.results.clean_rate` | met | |
| results.actions.6 | ACTIONS | Every act on the page is a link that names its verb for the role that can take it and reads "Read" plus "<role> acts" otherwise; "sign-off due" is plain text for a reader who cannot sign; a replay in flight is announced above the numbers with attempt k of n, $ spent and a link to the run | `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"a viewer is never offered an act they cannot take: Read and who acts, and "sign-off due" as plain text"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"a replay in flight is announced above the numbers with its progress and the run link"` · `vitest:ui/src/screens/Results/MapTable.test.tsx::"a reader who cannot sign sees "sign-off due" as plain text, never as an action"` | met | |
| results.actions.7 | ACTIONS | The "Waiting on a person" card says how many rows it is not showing when it cuts the list | `absent` | unmet | G-237 |
| results.explanation.8 | EXPLANATION | Every tile, map header, cell line, pill and door carries a registry hint; the ratchet enforces the route for the viewer and the approver at 30 hinted elements or more; the About block lists the terms and links to the guide | `hint:ratchet:/results` · `hint:about:/results` · `vitest:ui/src/help/hints-ratchet.test.tsx::"${pattern} as ${role}: every element carries a resolved hint"` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"every tile, map header and cell, pill and door carries a hint"` | met | |
| results.evidence.9 | EVIDENCE | The gates, the route tiles, the map, the licence sentence and the decisions panel are unit-tested; the route renders for every role at 375 and 1280 with axe clean; a walkthrough asserts at least one gate value, one route tile with its n and one door on the live stack | `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"renders the instrument gates, the routes with n, what deliver means, and what waits on a person"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` | partial | G-238 |
| results.roles.10 | ROLES | Every read behind the page is served to a signed-in viewer (API.md role column); the UI offers an act only to the role that can take it and the sign-off link only to an approver | `route:GET /signoffs?repo=[&include_revoked=true]` · `route:GET /factory/{repo}/tasks` · `route:GET /repos/{name}` · `test:tests/test_server_routes_capability.py::test_viewer_reads` · `vitest:ui/src/screens/Results/ResultsPage.test.tsx::"a viewer is never offered an act they cannot take: Read and who acts, and "sign-off due" as plain text"` | met | |
| results.operations.11 | OPERATIONS | The reads are documented in API.md; the guide says how to read the map and what a stop condition is; a false-Q1 row raises the stop-condition banner above this page with "Investigate in the ledger", and the alert rule fires on `crb_false_q1_total` | `route:GET /routes?repo=[&by=]` · `doc:docs/OPERATOR.md#4-read-the-capability-map` · `doc:docs/OPERATOR.md#8-stop-conditions` · `doc:docs/DEPLOYMENT.md#92-alert-rules` · `hint:id:banner.shell.stop_condition` · `code:ui/src/components/Layout.tsx::StopConditionBanner` | met | |
| results.entry-exit.12 | ENTRY-EXIT | When a gate reads amber or "not run" the page offers one click back to the walk step that produces it | `absent` | unmet | G-236 |
| results.accessibility.13 | ACCESSIBILITY | Renders for every role at 375 (top bar at most two rows) and 1280 with axe WCAG 2.1 AA clean while a hint bubble is open; Tab through the first twenty stops opens a hinted control's bubble on focus and hides it on Tab away; the map's numbers stay out of the tab order and the route tag in it; reduced motion is honoured | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `vitest:ui/src/screens/Results/MapTable.test.tsx::"every column header and every line of a cell carries a hint"` · `code:ui/src/index.css::"@media (prefers-reduced-motion: reduce)"` | met | |
| results.non-goals.14 | NON-GOALS | The page says on its face what it does not show: the "No throughput headline" callout names the missing human hours and merge outcomes; the deliver paragraph says deliver never means safe to merge | `hint:id:banner.results.no_throughput` · `hint:about:/results` · `doc:docs/ONBOARDING-A-REPO.md#what-you-may-claim-afterwards-and-what-you-may-not` | met | |

| results.truth.15 | TRUTH | The About block's numbers sentence describes the economics tiles as served: n is the attempts with a known value, each carries an interval and the apparatus, and an unknown is a dash, never zero | `hint:about:/results` · `measured:n = 1 sentence out of date, method: by inspection of the Baseline entry's numbers sentence in ui/src/help/help.ts, which still says economics are means only, apparatus 2.2` | unmet | G-239 |

## Gaps
- **G-236** — an amber or "not run" gate has no one-click way back to the walk: help.ts tells the operator to "go back to the walk" but "Back to the walk" renders only when nothing is measured · render the LinkButton to `/connect/:name` in the gates card whenever a gate is not green · ui
- **G-237** — the "Waiting on a person" card cuts to six rows and does not say so; the eyebrow count is the full length · add "and n more" beside "All decisions" when the list is cut · ui
- **G-239** — the Baseline About block's numbers sentence (`ui/src/help/help.ts`) still says "Economics tiles are means only: the API does not yet serve an interval for cost or latency", which is false since F35 serves a known n, a t interval and the apparatus · replace it with "Cost and latency carry the attempts with a known value as n, a Student-t 95 % interval and the apparatus; an unknown is a dash, never zero" when wave 2's `help.ts` merges (wave 3a may not edit that file) · ui
- **G-238** — no walkthrough asserts a number or a door on /results: 07 runs axe and 11 renders · add one 05-replay-fake step that reads the three gates, the calibrate tile's n and follows "Open the full map" with the repository carried · ui
