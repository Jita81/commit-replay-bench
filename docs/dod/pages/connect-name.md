---
id: dod.page.connect-name
level: page
name: The walk — six stages for one repository
scope: /connect/:name
parent: dod.journey.connect-a-repository
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# The walk — six stages for one repository

**Purpose.** "The six stages that take one repository from registered to measured. Each stage
says what it proves and whether it spends money; the first five involve no model." (About
block, `help.ts`; eyebrow `Journey · 1 of 4 · Connection`.)

**Entry → exit.** Arrive from a row on Connection (name link or *Continue*), from Home tasks 4
and 5, from the repository page's *Connection walk* button, from the Measure page's back link,
or from the Baseline's *Back to the walk*. The header sentence names the next stage and why it
matters. Leave by pressing *Run* on the next stage (probe, mine, oracle, controls), *Measure…*
on the sixth, *open run* / *Open the run* (`/runs/:id`), *Configuration* (`/repos/:name`) or
*Baseline* (`/results?repo=`), which fills in once every stage is done. For this journey the
person leaves with stages 1 (registered) and 2 (probed) reading Done and stage 3 as the next
Run.

**Non-goals.** Does not edit configuration (Configuration); does not show the run log (the run
page); does not show rates (the Baseline); does not itself spend — the sixth stage opens the
run form and says so first.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| connect-name.purpose.1 | PURPOSE | The About block states the job in one sentence; the header sentence reads "Next: <stage>. <why>" until every stage is done, then says the baseline holds the evidence | `hint:about:/connect/:name` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"the per-repository walk: six stages, statuses from the API, the operator runs the next one"` | met | |
| connect-name.entry-exit.2 | ENTRY-EXIT | Every stage with a run links to it; Configuration and Baseline are one click in the header; a failed or cancelled measurement never reads as Not started; an unknown repository name shows a Not found state that says what to do | `code:ui/src/screens/Connect/connection.ts::stagesFor` · `vitest:ui/src/screens/Connect/connection.test.ts::"a failed replay with no rows is failed with the run to open, and offers Retry not a blind spend"` · `vitest:ui/src/screens/Repos/RepoDetail.test.tsx::"Next steps reach the Connection walk and the Factory for this repository"` | partial | G-116 |
| connect-name.truth.3 | TRUTH | Stage detail lines are counts (tasks mined, controls constructed, mutants killed), never rates, and the About block says the rates live on the Baseline; a queued run shows the server's queue_position; a running measurement shows "Attempt k of n" from the run's own progress and "$x spent so far" from its cost_usd | `hint:about:/connect/:name` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a queued run reads Queued with the server’s queue_position (the worker’s own order), never a client recount (J-TEL-6)"` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a running measurement shows attempts, spend, started and a Cancel that confirms before posting (J-ONR-5)"` · `vitest:ui/src/screens/Connect/connection.test.ts::"mined counts, an oracle report, a passed controls report and measured rows complete their stages"` | met | |
| connect-name.truth.4 | TRUTH | A controls report that passed with an escape or a thin set reads "Done, with a finding" and names what deliver is waiting on; a failed report is Failed and blocks the measurement | `vitest:ui/src/screens/Connect/connection.test.ts::"a failed controls report is failed (not done) and blocks the measurement"` · `vitest:ui/src/screens/Connect/connection.test.ts::"the walk goes on, the finding is named, deliver is withheld"` | met | |
| connect-name.actions.5 | ACTIONS | Run on the probe stage posts the probe and on mine/oracle/controls posts a run; the button is disabled while a request is pending; an API refusal renders as a compact error under the list; when the watched run ends every input is refetched so the stage turns Done | `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"the per-repository walk: six stages, statuses from the API, the operator runs the next one"` · `route:POST /repos/{name}/probe` · `route:POST /runs` | met | |
| connect-name.actions.6 | ACTIONS | Cancel the run asks for confirmation that names the cost (attempts already made are still charged), then posts the cancel and reads "Cancel requested — the worker stops between attempts"; the confirmation is the app's own dialog, not window.confirm, so it is hinted and axe-checked | `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a running measurement shows attempts, spend, started and a Cancel that confirms before posting (J-ONR-5)"` · `route:POST /runs/{id}/cancel` | partial | G-117 |
| connect-name.actions.7 | ACTIONS | Measure… on the sixth stage opens the designed Measure page (cost band, keep-worktrees choice, confirm), the same surface Home task 5 opens, not the technical run form | `hint:about:/connect/:name/measure` | partial | G-118 |
| connect-name.explanation.8 | EXPLANATION | Every stage title, status pill, detail line, in-flight line and action carries a hint the ratchet enforces (floor 14); the About block links the £0 proving step and the sandbox-unavailable guide | `hint:ratchet:/connect/:name` · `hint:about:/connect/:name` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"every stage title, status pill, detail line and action on the walk carries a hint"` · `doc:docs/OPERATOR.md#7-when-the-sandbox-is-unavailable` | met | |
| connect-name.evidence.9 | EVIDENCE | The stage derivation is unit-tested (17 cases) and the screen for viewer and operator; 11-screens walks the route for four personas at 375 and 1280; a tier-1 walkthrough presses Run on this page and watches the stage turn Done | `vitest:ui/src/screens/Connect/connection.test.ts::"a fresh repository is registered and waiting on the probe"` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a viewer sees the walk but no action"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | partial | G-119 |
| connect-name.roles.10 | ROLES | A viewer sees every stage but no Run, Retry, Measure… or Cancel — a sentence says an operator runs it and, on the sixth stage, that it spends; the API answers 403 to a viewer on the probe and on run creation; the run row carries the actor | `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a viewer sees the walk but no action"` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a viewer on the measure stage is told it spends, in a sentence"` · `test:tests/test_server_routes_repos.py::test_rbac` · `route:POST /repos/{name}/probe` | met | |
| connect-name.operations.11 | OPERATIONS | A probe with no job queue answers 503 queue_unavailable and the compact error names it; a run that sits queued is explained by crb doctor's worker line and OPERATOR §7; probe.done events and crb_runs_total{kind} name the stage in telemetry | `route:POST /repos/{name}/probe` · `test:tests/test_server_routes_repos.py::test_404_and_queue_unavailable` · `doc:docs/OPERATOR.md#7-when-the-sandbox-is-unavailable` · `doc:docs/OPERATOR.md#11-check-the-installation-crb-doctor` · `doc:docs/DEPLOYMENT.md#91-metrics--which-process-carries-which-series` | met | |
| connect-name.accessibility.12 | ACCESSIBILITY | axe WCAG 2.1 AA is clean at 375 and 1280 with a hint open; the in-flight line that changes every poll is a polite live region and the link and Cancel sit outside it; the stages are an ordered list with an accessible name | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `vitest:ui/src/screens/Connect/ConnectPage.test.tsx::"a running measurement shows attempts, spend, started and a Cancel that confirms before posting (J-ONR-5)"` | met | |
| connect-name.non-goals.13 | NON-GOALS | The About block states that the first five stages involve no model, that Measure… is the only stage that spends, and that the rates with n and a Wilson interval appear on the Baseline rather than here | `hint:about:/connect/:name` · `vitest:ui/src/components/Help.test.tsx::"says, on each screen whose definition of done quotes it, the sentence that record quotes"` | met | |

## Gaps
- **G-116** — an unknown repository name renders a generic ErrorState ("Not found", retry) with no link back to Connection · give the 404 branch a way forward: "No repository called <name> — open Connection" linking /connect (ConnectPage.tsx ConnectRepoPage) · ui
- **G-117** — Cancel the run uses window.confirm (ConnectPage.tsx cancelRun), which carries no hint, cannot be reached by 11-screens' dialogHints and is invisible to axe · replace it with the app Dialog (the same confirm-an-action shape the Measure page uses) and add it to INSTRUMENT_VARIANTS · ui
- **G-118** — the sixth stage's Measure… opens RunNewDialog (ConnectPage.tsx act) while Home task 5 and MeasurePage.tsx say /connect/:name/measure is "the walk's sixth stage as a page": two entry surfaces with different copy and defaults for the money step · make Measure… a LinkButton to /connect/:name/measure and drop RunNewDialog from the walk · ui
- **G-119** — no walkthrough presses a stage button on this page; every real run in e2e starts from /repos or /runs (02-repo-onboard, 03-mine, 04-oracle-and-controls) · add a tier-1 case that opens /connect/:name, presses Run on the probe stage, and asserts the stage reads Done after waitForRun · ui
