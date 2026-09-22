/**
 * The hint registry — one plain-English sentence or two per element a reader meets, keyed by
 * a stable id.
 *
 * Navigation
 * ----------
 * What it is:   `HINTS` (id → sentence), the `HintId` union, `hintText(id)`, `SHARED_IDS` and
 *               `MIN_HINTS`.
 * What it does: Holds the copy every `<Hint id>` bubble shows and the About block's "Elements
 *               on this screen" lists, so the two can never drift. Ids are stable and dotted:
 *               `<kind>.<screen>.<thing>` for a screen-specific element, `<kind>.<thing>` for
 *               the shared vocabulary a shared component derives itself (route.*, belt.*,
 *               kind.*, controls.*, provenance.*, probe.*, run.*, tier.*, oracle.*, review.*,
 *               nav.*). Copy rules: GOV.UK tone; what the element IS and what its value MEANS;
 *               a number names what it counts, over what n, with what interval or apparatus;
 *               no links (those live in Term and About); jargon only where the route's About
 *               carries the term. A hint never restates the number the element shows.
 * How:          A `const` object `satisfies Record<string, string>`; `HintId` is derived from
 *               its keys so a typo is a compile error and `hintText` can never return
 *               `undefined`. `MIN_HINTS` is the per-route floor the ratchet enforces.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Hint.tsx (renders an entry as a tooltip),
 *               ui/src/components/Help.tsx (the About block lists every entry on the screen),
 *               ui/src/help/help.ts (the About copy whose `terms[]` the lint checks against),
 *               ui/src/help/glossary.ts (the terms a hint may use), ui/src/components/Layout.tsx
 *               (the shell's nav.* and pill.shell.* ids), ui/src/lib/verdict.ts (the display
 *               tables whose states the shared ids describe)
 * Tested by:    ui/src/help/hints.test.ts (length, full stop, no links, copy lint),
 *               ui/src/help/hints-ratchet.test.tsx (every element on every enforced route
 *               carries one of these ids), ui/src/help/hints-hover.instrument.test.tsx (one
 *               element per instrument screen opens its text on mouse-over)
 * Touch when:   an element is added to a screen (add its id here first; the ratchet fails
 *               until the screen renders it); copy changes meaning only with the apparatus or
 *               policy change that made it wrong.
 */

export const HINTS = {

  // ── Shared vocabulary (derived by shared components)
  'route.deliver':
    'This cell clears every bar of the published routing rule, so the factory may open a branch and a pull request for this class of change under human review. It never means a change is safe to merge.',
  'route.calibrate':
    'Not enough evidence yet, or the rate is under the bar. More attempts, or running the negative controls, can change this route.',
  'route.granularize':
    'Changes of this size are split into smaller ones before they are attempted, so this cell is never measured as it stands.',
  'route.human':
    'A green cannot be trusted here whatever the pass rate: the tests are too weak, the controls gate failed, or a deliberate cheat graded clean. More attempts will not change it; stronger tests will.',
  'route.do_not_ship':
    'A row in this cell was credited clean although its belts contradict it (false-Q1). Nothing measured in the cell is evidence until the ledger is audited.',
  'route.not_yet_measured':
    'No graded attempt exists for this cell. It says nothing, not zero: a rate appears once a replay puts rows here.',
  'belt.tests_unmodified':
    'Belt 1: the builder did not change any test file. A tick means the tests that grade the attempt are the repository’s own; a cross disqualifies the row.',
  'belt.target_green':
    'Belt 2: the test the commit added or fixed passes after the change. A cross means the attempt did not do the job it was set.',
  'belt.no_new_failures':
    'Belt 3: the regression scope configured for the repository has no new failing tests after the change. A cross means the change broke something that was green before.',
  'belt.source_changed':
    'Belt 4: at least one source file changed. A cross means the attempt produced no change to the code, so a green target test proves nothing.',
  'belt.repo_lint_clean':
    'Belt 5: the repository’s own formatter or linter accepts the changed files. A dash means the repository has no linter configured, so the belt was not evaluated and does not count against the row.',
  'kind.builder_red':
    'Attempts where the builder finished and the belts failed it: the target test stayed red, a regression appeared, or no source changed. These count against the builder.',
  'kind.lint':
    'Attempts where the code worked (belts 1 to 4 held) but the repository’s own formatter or linter rejected the changed files (belt 5).',
  'kind.budget':
    'Attempts the builder cut short by hitting its own cap on wall clock, turns, tool calls, tokens or cost before it finished. They count in n.',
  'kind.protocol':
    'Attempts a guard refused (tamper, archaeology or network). This is an instrument decision, not a builder failure, and it counts against autonomy until the guard is fixed or the refusal is accepted.',
  'kind.harness':
    'Attempts that failed in the executor, sandbox, parser, setup or model API. The instrument failed, not the model; they count against autonomy until the instrument is fixed.',
  'kind.outage':
    'Calls the model provider refused (a usage limit, a 429 or a dead credential). Nothing was observed, so these sit outside n.',
  'kind.disqualified':
    'Attempts disqualified for tampering with a test or a malformed oracle. They are excluded and sit outside n, counted neither clean nor failed.',
  'stat.shared.model_rate':
    'The builder’s pass rate on fair, finished attempts only: clean divided by clean plus red, with its n and, where the server gave one, its 95 % Wilson interval. It is diagnostic and sits beside the all-rows rate; it never routes.',
  'controls.passed':
    'The negative controls run for this repository caught every deliberate cheat, at least half the controls could be constructed and nothing escaped. Every cell on the map was routed under this verdict.',
  'controls.failed':
    'The grader passed a deliberate cheat it must refuse (a violation). This is an instrument defect: every cell routes to a human until the grader is fixed and the controls re-run.',
  'controls.escaped':
    'A deliberate cheat graded clean because the repository’s own tests could not tell. It is a finding about the tests, and on its own withholds deliver until the tests are hardened.',
  'controls.thin':
    'Fewer than half the control rows could be constructed for this repository, so the report is too thin to license deliver. Cells route calibrate until more controls can be built.',
  'controls.unmeasured':
    'The negative controls have never run for this repository. Nothing on the map can route deliver until they pass.',
  'provenance.measured':
    'These rows were measured by this deployment under one apparatus version, shown beside the pill with the belt set. Measured rows are the only rows that route.',
  'provenance.imported':
    'These rows were imported (for example from a census) rather than measured here. They are kept for reference and carry the apparatus they were imported under.',
  'provenance.mixed':
    'More than one apparatus version or belt set stands behind this figure. Evidence from different apparatus is never averaged, so read it as a flag, not a rate.',
  'chart.ci_bar':
    'The band is the 95 % Wilson interval for this rate, the mark is its point, and the dotted ticks are the policy’s bars for the point and the lower bound. The numbers beside it are the claim; the bar is a glance aid.',
  'run.status':
    'Queued means nothing has started or been spent; Running means a worker holds it; Succeeded, Failed and Cancelled are final. A cancelled run keeps every row already graded.',
  'probe.status':
    'OK means the check passed; Degraded means it works with a caveat named in its detail; Down means it failed; Skipped means this process role does not run it and never lowers the aggregate.',
  'tier.verification':
    'How far this cell’s evidence has been checked by a person: human-verified or A/B-confirmed (green), automated pass (asserted, not yet earned), or untrusted. A sign-off lifts the tier; it never changes the route.',
  'oracle.band':
    'Strong, adequate, weak or unscoreable, from the share of planted faults the tests on the changed lines caught, against the policy’s floors. Weak sends a green to a human; unscoreable means no fault could be planted.',
  'oracle.gate':
    'What a clean grade licenses at this strength: clears the bar (a branch and pull request under review), review-gated (a person reviews before anything opens), or needs a human (the tests are too weak for a green to mean anything).',
  'review.verdict':
    'The standing human review of this row: OK, or the worst finding recorded (regression, defect, API change, style). Not reviewed means someone looked and could not review. A review is advisory to a person; it never changes a route.',
  'nav.journey_position':
    'Where this screen sits on the four-step journey: connect a repository, earn its baseline, decide what waits on a person, run the factory. The number is a position, not progress.',

  // ── Shell — every screen (components/Layout.tsx)
  'pill.shell.health':
    'The overall health of the instrument from its probes: sandbox, worker, ledger, toolchains. Anything but OK is explained probe by probe on Settings and Deployment.',
  'pill.shell.role':
    'The role your session holds. A viewer reads everything and changes nothing; an operator starts runs; an approver signs cells; an admin manages accounts and the GitHub App.',
  'nav.help':
    'The glossary of every term on these screens and the bundled guides.',
  'button.shell.theme':
    'Switch between light, dark and your system’s theme. It changes nothing but how the screens look.',
  'button.shell.sign_out':
    'End your session on this browser. Runs in flight carry on without you.',
  'nav.home':
    'Where this deployment is on the way from an empty install to a change delivered under evidence: the eight tasks and the next one to press.',
  'nav.connect':
    'Step 1: connect a repository and walk it through the six stages that make it measurable.',
  'nav.baseline':
    'Step 2: what the evidence says about one repository — the gates, the routes, the map and what waits on a person.',
  'nav.decisions':
    'Step 3: everything waiting on a person across every repository. The number is how many decisions are ready now.',
  'nav.decisions_count':
    'How many decisions are waiting on a person right now, across every repository. It counts sign-offs due, gaps to sign and factory items to decide; it is not a quality figure.',
  'nav.factory':
    'Step 4: deliver new work under the baseline — a frozen backlog, a RED proof, a build under the belts and a pull request only where the map routes deliver.',
  'nav.posture':
    'A printable statement of how this deployment is built, secured and audited, for an architecture or security review.',
  'nav.runs':
    'Every run the worker has executed or queued, with its progress and cost; where an operator starts one.',
  'nav.capability':
    'The full capability map: one cell per class and size with its rate, interval, false-Q1 count, cost, latency, oracle strength and route.',
  'nav.routing':
    'Every route decision with its reason code and the policy version that produced it.',
  'nav.oracle':
    'How much a green is worth here: the negative controls and the mutation strength of the tests on the changed lines.',
  'nav.learn':
    'What the ledger teaches: refusals to turn into guard tests, weak oracles to turn into test work, stale evidence to re-measure.',
  'nav.ledger':
    'Every graded trial, append-only and hash-chained, with the verification that nothing was edited.',
  'nav.settings':
    'The instrument’s health, the builder sign-in, the GitHub App and, for admins, accounts and non-secret configuration.',
  'banner.shell.stop_condition':
    'A row on the ledger was credited clean although its belts contradict it. Delivery is halted everywhere until it is investigated; no setting can hide this banner.',
  'nav.version_line':
    'The three versions every claim cites: crb (the software), apparatus (the instrument that graded the rows) and policy (the routing rule). A sign-off made under an older apparatus is stale.',
  'nav.footer_help':
    'The glossary and guides, in words, on every screen.',
  'nav.footer_glossary':
    'Every term the screens use, in plain English, with each number’s n, interval and apparatus.',

  // ── /login (screens/Login/LoginPage.tsx)
  'field.login.username':
    'The username of a local account an admin created on this deployment.',
  'field.login.password':
    'The account’s password. It is checked by the API and never stored by this page.',
  'button.login.submit':
    'Sign in with the local account above. Your role decides what you can change once inside.',
  'button.login.oidc':
    'Sign in with your organisation account through OpenID Connect. Your role is assigned by the deployment’s mapping, not chosen here.',

  // ── /home (screens/Home/HomePage.tsx)
  'stat.home.kicker':
    'The repository the tasks below are about (the most recently updated one, unless the link named another) and whether it is in trial, measuring or measured.',
  'banner.home.sandbox':
    'The sandbox probe is not OK on this host, so anything measured now is a development reading and not evidence. Deployment shows the probe and what to fix.',
  'stat.home.completed':
    'How many of the eight tasks are marked Completed. It is progress through the set-up, not a quality figure; the quality figures live on the Baseline with their n and interval.',
  'task.home.connect_github':
    'Whether the GitHub App is registered and installed. Optional when a repository is connected by URL; Completed lets the factory clone private repositories and open pull requests.',
  'task.home.choose_repo':
    'Whether at least one repository is connected. Everything after this task is about the repository named in the kicker.',
  'task.home.confirm_shape':
    'Whether the toolchain probe has proved the instrument can run this repository’s tests. Failed means the probe found the toolchain missing; open the repository to read why.',
  'task.home.prove_instrument':
    'Whether the oracle strength is scored and the negative controls passed. These cost nothing and every number later stands under them.',
  'task.home.measure':
    'Whether a first sighted measurement has run. This is the task that spends model budget; it says how much before it starts.',
  'task.home.read_baseline':
    'Incomplete once the map has rows; Completed once someone has acted on the baseline (any active sign-off on this repository).',
  'task.home.invite_approver':
    'Whether an account with the approver role exists. Only an admin can add one; the operator who queues runs should not be the approver who signs them.',
  'task.home.deliver':
    'Where the factory is: blocked before any measurement, waiting for a backlog, frozen and ready to run, in progress item k of n, or Completed once an item has a pull request or was accepted.',
  'button.home.continue':
    'Go to the first task you can act on now. Nothing spends money until a run you can see and cancel is queued.',

  // ── /connect (screens/Connect/ConnectPage.tsx · ConnectPage)
  'button.connect.github':
    'Pick a repository from an organisation that installed the GitHub App. No token to hand over; the App mints a short-lived credential per use. Greyed out until an admin registers the App.',
  'button.connect.url':
    'Register a repository by its git URL or an existing clone path on the server. The worker clones it on the first run; nothing is written to the repository.',
  'col.connect.repository':
    'The name the ledger keys this repository by. Open it to see the six stages of its walk.',
  'col.connect.language':
    'The language and test runner the repository is configured with; the probe checks that the runner works here.',
  'col.connect.tasks':
    'Commits mined into replayable tasks, then how many of them are gold-clean (their own change passes its test in the sandbox). Only gold-clean tasks are replayed.',
  'col.connect.next_stage':
    'The walk’s state for this repository: which stage comes next, or that every stage is done.',
  'col.connect.last_run':
    'The kind and status of the most recent run for this repository.',
  'pill.connect.stage_summary':
    'The next stage this repository needs, or Done when the walk is complete. Failed names a stage to retry; Done, with a finding means deliver is withheld until the finding is read.',
  'button.connect.row_action':
    'Continue opens the walk at its next stage; Baseline opens what the evidence says once every stage holds rows.',
  'button.connect.empty_connect':
    'Start the walk for a first repository: register, probe, mine, oracle, controls, then a first measurement.',

  // ── Connect from GitHub dialog (screens/Connect/GitHubConnectDialog.tsx)
  'field.github.installation':
    'The organisation or account that installed the GitHub App. Only repositories that installation can see are listed.',
  'button.github.sync':
    'Ask GitHub which installations exist now and record them here. Use it after installing the App or changing its permissions.',
  'field.github.search':
    'Filter the list by owner/name. The list is one page of the installation’s repositories at a time.',
  'pill.github.repo_flags':
    'Private means the App must hold read access to clone it; archived repositories can be measured but not delivered to; a tick means it is already connected here.',
  'button.github.page':
    'Move through the installation’s repositories one page at a time.',
  'field.github.mode':
    'Create a new repository record from the GitHub repository, or link the GitHub repository to a record that already exists here.',
  'field.github.existing':
    'The record to link. Only repositories with no GitHub link yet are listed.',
  'field.github.name':
    'The lowercase name the ledger keys this repository by. It cannot be changed once rows exist.',
  'field.github.language':
    'The language the instrument treats the repository as. GitHub’s guess is filled in; choose one when it reports none.',
  'field.github.runner':
    'The runner that executes the repository’s tests inside the sandbox. The probe verifies it before anything is measured.',
  'button.github.connect':
    'Record the repository and open its walk. Nothing is cloned yet and nothing is written to GitHub.',
  'button.github.use_url':
    'Register by git URL instead, when the App is not configured or the repository is not under an installation.',
  'link.github.install':
    'Opens GitHub to install the App on another organisation or account. Come back and press Sync installations once it is installed.',

  // ── /connect/:name (screens/Connect/ConnectPage.tsx · ConnectRepoPage)
  'button.walk.configuration':
    'Open the repository’s configuration: language, runner, test layout, belt scope, probe scope and mining caps. Edit it when the probe or mine stage fails.',
  'button.walk.baseline':
    'Open what the evidence says about this repository. It fills in once any stage has produced rows; before the walk is done its numbers are provisional.',
  'stage.walk.register':
    'The repository record exists with its URL or clone path and language. Nothing has been cloned or run.',
  'stage.walk.probe':
    'The configured known-green test scope was run inside the sandbox to prove the runner works here. Costs nothing. Failed means the toolchain or the probe scope is wrong; read the detail line.',
  'stage.walk.mine':
    'History was walked for commits whose test fails before the change and passes with it. The detail line counts tasks found; only gold-clean tasks can be replayed. Costs nothing.',
  'stage.walk.oracle':
    'Faults were planted on each task’s changed lines to see whether its tests notice. Costs nothing. A weak oracle sends a cell to a human whatever its pass rate.',
  'stage.walk.controls':
    'Seven deliberate cheats were graded to prove the grader refuses what it must. Costs nothing. Passed licenses deliver; an escape or a thin set withholds it.',
  'stage.walk.measure':
    'A sighted replay: the builder attempts each gold-clean task and every attempt is graded under the belts. This is the stage that spends model budget; the estimate is shown before you confirm.',
  'pill.walk.stage_status':
    'Not started, In progress, Done, Failed or Waiting for an earlier stage. Done, with a finding means the stage holds evidence that carries a finding (a controls escape or a thin set): read it before spending. Queued means nothing has started or been spent.',
  'pill.walk.spends':
    'This stage calls a model and costs money. Every other stage is free.',
  'button.walk.run_stage':
    'Queue this stage’s run. Run and Retry cost nothing; Measure… opens the estimate for the one stage that spends. A queued run can be cancelled from Runs.',
  'stat.walk.stage_detail':
    'What the stage found, as counts (tasks mined, mutants killed, controls constructed) or the probe’s first line. Counts, not rates: the rates with n and interval are on the Baseline.',
  'link.walk.open_run':
    'The run that produced this stage’s result: its log, its error if any, and every row it graded.',
  'stat.walk.inflight_progress':
    'The attempt or task in hand out of the total this run planned. Rows land on the baseline as each one is graded.',
  'stat.walk.inflight_spend':
    'Builder-reported dollars spent by this run so far, summed over finished attempts. It is a measurement, not an estimate.',
  'link.walk.inflight_open':
    'Watch the live log and per-task rows of this run.',
  'button.walk.cancel':
    'Stop after the attempt in flight. Attempts already made are still charged and their rows are kept.',

  // ── /connect/:name/measure (screens/Connect/MeasurePage.tsx)
  'link.measure.back':
    'Return to the six stages for this repository without starting anything.',
  'nav.measure.kicker':
    'This is task 5 of the eight on Home, and the only step before the factory that spends model budget.',
  'banner.measure.inflight':
    'A measurement is already queued or running for this repository, with its attempts made and spend so far. Start another only when it has finished or been cancelled.',
  'field.measure.attempts':
    'How many attempts to buy, one per gold-clean task up to this number. 10 shows the shape but cannot route (n must reach 10 in a cell); 30 is the first useful picture; 60 gives tighter intervals for a longer wait.',
  'stat.measure.gold_cap':
    'The run makes one attempt per gold-clean task, so it cannot make more attempts than the repository has gold-clean tasks.',
  'field.measure.retain_worktrees':
    'Keep the working copy of each failed attempt so a person can read what the builder did. Off by default; kept until you delete it and in scope for your retention policy.',
  'field.measure.retain_transcripts':
    'Keep the builder’s conversation for each attempt. Off by default; it can contain code from your repository, so it is in scope for your retention policy.',
  'stat.measure.estimate':
    'A planning band for this run: the number of attempts times a per-attempt cost. With no measured mean for this repository it uses the range earlier repositories showed and carries no apparatus; once this repository has measured attempts it uses their mean (n shown) with ±20 % around it. It is not a measured interval.',
  'summary.measure.builder':
    'The builder and model this deployment will use for every attempt, chosen from the credentials the admin configured. Every knob opens the full run form.',
  'link.measure.every_knob':
    'Open the full run form on Runs to set the builder, model, ladder, budget caps and executor yourself.',
  'summary.measure.budget_cap':
    'There is no cap on the run’s total spend yet. Each attempt is capped on turns, tool calls and wall clock, and you can cancel at any point.',
  'summary.measure.retention':
    'What this run will keep beyond grades and hashes, from the two boxes above.',
  'summary.measure.posture':
    'Whether the sandbox that runs the tests is sealed (docker) so the rows count as evidence, or a local executor whose rows are a development reading only.',
  'button.measure.start':
    'Queue the measurement now. It spends model budget up to the estimate shown; you can cancel from Runs and pay only for attempts made.',

  // ── /results — Baseline (screens/Results/ResultsPage.tsx + MapTable.tsx)
  'field.shared.repo_picker':
    'The repository every number on this screen is about. A cell says nothing about a repository it was not measured on. The choice is kept in the address so the page can be shared.',
  'banner.results.replay_running':
    'A replay is still grading attempts for this repository, so every number below moves as each row lands. Open the run to watch it.',
  'stat.results.controls':
    'The verdict of the latest negative-controls run for this repository: passed, escaped, thin, failed or not run, over n control rows, stamped with the apparatus and controls version that produced it. Only passed licenses deliver anywhere on the map.',
  'stat.results.oracle_strength':
    'The mean of every scored task’s mutation kill-rate (faults caught over faults planted on the changed lines), over n tasks, under the apparatus shown. It is a mean of per-task scores, so it carries no interval; below the policy bar a cell routes to a human.',
  'stat.results.false_q1':
    'The number of rows credited clean whose own recorded belts contradict them, across every measured cell (n = attempts on the map). It must read 0: one such row halts delivery and is refused when written.',
  'button.results.full_map':
    'The same cells with every number and its method, projections by language and model, and a CSV export of the rows behind them.',
  'stat.results.route_deliver':
    'How many measured cells route deliver, with n the attempts inside them, out of every measured cell on the map. The factory may open pull requests only for these.',
  'stat.results.route_calibrate':
    'How many measured cells route calibrate: not enough evidence yet or under the bar. More attempts can move them.',
  'stat.results.route_granularize':
    'How many cells route granularize: changes of that size are split before they are attempted.',
  'stat.results.route_human':
    'How many measured cells route to a human: a green cannot be trusted there. More attempts will not move them; stronger tests will.',
  'col.map.class':
    'The class of change, from the commit taxonomy (for example bug.fix or backend.route.add). Each row is one class across five size tiers.',
  'col.map.size':
    'The size tier of the change as the apparatus measures it (a complexity band, not a line count). Every tier is shown so an unmeasured one is visible.',
  'map.cell.route':
    'The route the published rule gives this cell from its own evidence. Deliver licenses pull requests; calibrate needs more evidence; human needs stronger tests; do not ship means false-Q1.',
  'map.cell.n':
    'The number of graded attempts in this cell, and the number of distinct commits behind them. n below 10 cannot route deliver; few tasks behind many attempts means the rate leans on a handful of commits.',
  'map.cell.point':
    'The share of attempts graded clean in this cell. A dash means the interval is too wide (over 60 points) for the point to mean anything yet.',
  'map.cell.interval':
    'The 95 % Wilson interval for the rate above, from n. The interval is the claim; the point is only its centre.',
  'map.cell.apparatus':
    'The apparatus version that graded these rows. Rows from different versions are never averaged; a sign-off under an older version is stale.',
  'map.cell.signoff':
    'Signed with a date means an approver attested this cell under the current apparatus; sign-off due means it routes deliver and no one has signed; sign-off stale means it was signed under an older apparatus; otherwise the reason code that decided the route.',
  'map.cell.not_measured':
    'No sighted attempt exists for this class and size. It says nothing, not zero.',
  'map.cell.granularize':
    'This size is split into smaller changes before it is attempted, so it is never measured as it stands.',
  'banner.results.licence':
    'The one sentence the largest signed cell permits you to say, with every qualifier: repository, apparatus, belt set, controls gate, n, class and size, rate with interval, who signed and when. Every figure is the signed snapshot, not the cell as it reads now.',
  'stat.results.cost_per_attempt':
    'The mean builder-reported dollars per attempt over every cell with a known cost, weighted by n, on the current apparatus. A mean only: the API serves no interval for cost yet.',
  'stat.results.cost_per_clean':
    'The same mean divided by the clean rate: what one clean attempt cost on average, over n clean attempts. No interval.',
  'stat.results.latency':
    'The mean wall-clock time of one attempt over every cell with a known latency, weighted by n. A mean only, no interval.',
  'stat.results.clean_rate':
    'Clean attempts over all attempts across every measured cell (n shown). It is a whole-repository summary and is never a routing input: routes are decided cell by cell.',
  'banner.results.no_throughput':
    'The ledger records neither human hours nor merge outcomes, so cost per accepted change cannot be shown honestly. Cost per clean attempt is what is measured.',
  'button.results.routing':
    'Every cell’s route decision with its reason code and the policy thresholds in force.',
  'button.results.oracle':
    'The per-task mutation scores and the negative-controls rows behind the two gate tiles above.',
  'button.results.ledger':
    'The graded rows themselves, filtered to this repository, with the chain verification.',
  'pill.results.decision_kind':
    'Why this item waits: a sign-off due, a cell that must not ship, a factory item blocked or to review. The button beside it names who acts.',
  'button.results.decision_act':
    'Take the decision if your role can, or read it if not. The role that acts is named under the button.',
  'button.results.all_decisions':
    'Every decision waiting on a person, across every repository.',
  'stat.results.waiting_count':
    'How many decisions are waiting on a person for this repository alone: sign-offs due, gaps to sign and factory items to decide.',

  // ── /decisions (screens/Decisions/DecisionsPage.tsx)
  'stat.decisions.apparatus':
    'The apparatus version every decision below is read under. A sign-off made under an earlier version is listed as stale.',
  'stat.decisions.count':
    'How many decisions are ready for a person now, and across how many repositories. A cell the policy would refuse anyway is never counted; it stays on the map with its reason.',
  'stat.decisions.repo_count':
    'How many of the decisions above belong to this repository; each is listed under it.',
  'pill.decisions.kind':
    'The kind of decision: must not ship (false-Q1), sign-off due, a structural gap to sign, a factory item routed to a person, a review to read, or delivery withheld by the route.',
  'stat.decisions.evidence':
    'The cell’s attempts (n), its clean rate with its 95 % Wilson interval, and the reason code that decided its route, under the apparatus in the kicker.',
  'button.decisions.act':
    'Take this decision. It opens the sign-off form with the cell chosen, the factory item, or the ledger row, depending on the kind.',
  'button.decisions.read':
    'Read the decision without acting. The role that can act is named under the button.',
  'tile.decisions.stale':
    'A cell signed under an earlier apparatus. It is kept as history and licenses nothing until an approver re-signs it under the current apparatus or revokes it.',
  'button.decisions.resign':
    'Open the sign-off form on this cell to revoke the stale attestation or sign it again under the current apparatus.',

  // ── /signoff (screens/Signoff/SignoffPage.tsx)
  'details.signoff.why_refused':
    'The six clauses the server checks before it records a sign-off. Two of them (false-Q1 and the attestation) cannot be relaxed by any deployment setting.',
  'gate.signoff.banner':
    'Every clause of the sign-off policy with its observed value against the threshold, evaluated before you try. Open only when every row holds; a refusal after pressing Sign off is the gate working.',
  'gate.signoff.measured':
    'The cell has graded attempts under the current apparatus (n shown). An unmeasured cell cannot be signed.',
  'gate.signoff.false_q1':
    'No row in the cell is credited clean against its own belts. This clause cannot be relaxed.',
  'gate.signoff.thin_cell':
    'The cell has at least the policy’s minimum attempts, with its point and Wilson lower bound shown. A thin cell is refused however good its rate.',
  'gate.signoff.controls':
    'The latest controls run passed, with no more escapes than the policy allows and at least the required share constructible; the run and its date are named. Never run is a refusal.',
  'gate.signoff.oracle':
    'The cell’s tasks have a measured mutation strength at or above the bar. Unmeasured is a refusal that cannot be overridden: run an oracle run first.',
  'gate.signoff.route':
    'The published rule routes this cell deliver. A sign-off never changes a route, so a cell routed elsewhere cannot be signed.',
  'gate.signoff.attestation':
    'You have named one accepted row and affirmed you read its diff. This clause cannot be relaxed: the attestation is hash-chained with the sign-off.',
  'gate.signoff.second_person':
    'The two-person rule: the server refuses your sign-off if you queued the run that produced the attested row, or if you are the only person behind the cell. No setting can relax it; the refusal code is same_actor.',
  'button.signoff.sign':
    'Record the attestation. The server re-checks every clause at write and refuses if any fails; a refusal records nothing.',
  'tile.signoff.refusal':
    'A clause the server would refuse on right now: its code, what it means, the observed value against the threshold, and whether any deployment setting could relax it.',
  'pill.signoff.non_overridable':
    'This clause cannot be relaxed by any deployment setting.',
  'stat.signoff.point':
    'The share of the cell’s eligible attempts graded clean (clean of n), with its 95 % Wilson interval, apparatus and belt set. This is the snapshot the record will carry.',
  'stat.signoff.ci_low':
    'The lower bound of the 95 % Wilson interval: the figure the routing rule reads against its bar. It rises with n at the same rate.',
  'stat.signoff.false_q1':
    'Rows in this cell credited clean against a failed belt. Must be 0; a later false-Q1 row invalidates the sign-off at read.',
  'stat.signoff.oracle':
    'The mean mutation kill-rate of the tasks in this cell, over the tasks scored of those in the cell. Unmeasured is a refusal, never a pass.',
  'tile.signoff.controls':
    'The controls verdict every cell is routed under, with how many controls were constructed, how many escaped, and the run and date it came from.',
  'tile.signoff.route':
    'The cell’s route with its reason code and sentence. A sign-off lifts the verification tier and never the route.',
  'tile.signoff.failure_split':
    'The interval bar, the model rate on fair attempts, and the split of what was not clean (red, budget, protocol, harness, DQ).',
  'field.signoff.cell_read':
    'Choose a measured cell to read its gate and evidence. Nothing changes on the server because you read it.',
  'banner.signoff.not_meaning':
    'A sign-off does not change the route, point or interval, vouches for no other class, size or repository, and stops counting if a false-Q1 row appears or the apparatus changes.',
  'field.signoff.cell':
    'The measured cell you are attesting, shown with its route, n and rate. Only cells with attempts on the current apparatus are listed.',
  'tile.signoff.cell_summary':
    'The chosen cell’s route, the reason the rule gave, and the apparatus and belt set its rows carry.',
  'field.signoff.accepted_row':
    'The clean (accepted) rows in this cell. Name the one whose diff you read; its hash is chained into the sign-off.',
  'field.signoff.read_affirmation':
    'Your affirmation that you read the diff of the row named above. The attestation names that row and is hash-chained with the sign-off.',
  'tile.signoff.read_diff':
    'The diff you are about to affirm you read, verified against the pack’s hash when the deployment retained it; otherwise the pack’s file list and links to the task and the run.',
  'button.signoff.task':
    'Open the task: its specification and every graded trial against it.',
  'button.signoff.run':
    'Open the run that produced this row: its log and every other row it graded.',
  'field.signoff.statement':
    'What you read in that diff and why it is acceptable. Recorded verbatim, append-only and redacted of secret-shaped content.',
  'field.signoff.note':
    'Optional: what else you reviewed (packs, refusals, the oracle). Recorded verbatim.',
  'banner.signoff.recorded':
    'The sign-off is on the ledger. The reference is the first characters of its row hash; the summary under it is what was recorded, served back verbatim.',
  'col.signoff.cell':
    'The class and size (and language or model where projected) the attestation covers.',
  'col.signoff.status':
    'Active counts now; stale was signed under an older apparatus; invalidated means a false-Q1 row appeared since; superseded means a later attestation covers the same scope; revoked was withdrawn by an approver.',
  'pill.signoff.status':
    'Active counts now; stale lifts nothing until re-signed; invalidated means the cell now has a false-Q1 row; superseded means a later attestation covers the same scope; revoked was withdrawn, with who and when.',
  'col.signoff.approver':
    'The named person who signed, with the kind of account they signed from. The server refused this record at write if that person had produced the evidence themselves.',
  'pill.signoff.verifier_kind':
    'The kind of account that signed: local (a password account on this deployment), oidc (your identity provider), or service (a delegated signature, which never reads as a person). Records written before this was stamped say so.',
  'col.signoff.signed':
    'When the attestation was recorded on the ledger. Newest first by default.',
  'col.signoff.evidence':
    'The snapshot the approver attested: n, point, Wilson lower, false-Q1, oracle strength and apparatus. Rows added since do not change it.',
  'col.signoff.policy':
    'The sign-off policy version in force, the route and reason code, and the controls verdict with its run, at the moment of signing. Pre-policy record means it was signed before a policy snapshot was recorded.',
  'col.signoff.attestation':
    'The accepted row the approver affirmed reading, by its hash and subject, with the statement they recorded under it. The statement is the governance record.',
  'col.signoff.note':
    'The approver’s optional note on what else they reviewed, recorded verbatim.',
  'button.signoff.revoke':
    'Withdraw this attestation. It appends a revocation row naming you and your reason; the attestation stays on the record marked revoked, and the cell returns to sign-off due.',
  'field.signoff.revoke_reason':
    'Recorded verbatim on the revocation row, append-only. An auditor reads it next to the attestation it withdraws.',
  'button.signoff.revoke_confirm':
    'Record the revocation now. The factory stops opening pull requests for this cell.',

  // ── /factory (screens/Factory/FactoryPage.tsx)
  'button.factory.freeze':
    'Write the items to work: they are validated, hashed and recorded as the first event of the evidence chain. Refused while a factory run is active.',
  'pill.factory.frozen':
    'Frozen means the backlog’s hash is on the chain and a run can work it; the date is when it was frozen. Not frozen means it has not been recorded yet.',
  'stat.factory.hash':
    'The first characters of the backlog’s hash, the first event of the evidence chain. A revised backlog gets a new hash; the old chain stays.',
  'stat.factory.items_count':
    'How many items the frozen backlog holds.',
  'banner.factory.active_run':
    'The run working this backlog: the item in hand out of the total, what the chain last recorded for it, the spend so far and when it started.',
  'button.factory.open_run':
    'Watch the live log and per-item rows of the run working this backlog.',
  'button.factory.cancel':
    'Stop the loop after the item in hand. Items already built are still charged and stay on the chain.',
  'stat.factory.last_run':
    'What the newest finished factory run did: how many of its items were accepted, and the other outcomes by count, with when it finished.',
  'link.factory.last_run':
    'Open the newest finished factory run: its log, its per-item rows and what it cost.',
  'summary.factory.builder':
    'The builder and model the run will use: the deployment’s configured default, or one you name under Use a different builder.',
  'summary.factory.items':
    'How many items will be worked (those with no unsigned structural gap), and how many of them sit today in a cell the map routes deliver. Readiness is assessed again at the run.',
  'stat.factory.estimate':
    'A planning band: items to work times a per-item cost. With no measured mean for this repository it uses the range earlier repositories showed and carries no apparatus; otherwise this repository’s measured mean (n shown) ±20 %. Not a measured interval.',
  'summary.factory.delivery':
    'Whether a clean build in a deliver cell will open a branch and pull request in the linked repository, and against which branch. Not linked means no pull request can be opened; the reason is under it.',
  'summary.factory.budget_cap':
    'There is no cap on the run’s total spend yet. The builder’s ladder caps turns, tool calls and wall clock per attempt.',
  'field.factory.deliver':
    'When on, a clean build in a cell that routes deliver opens a branch and pull request under review; never a merge. When off, every item is built and graded locally only.',
  'stat.factory.deliverable':
    'How many items sit right now in a cell the map routes deliver. It is read from the map at this moment and changes as measurement changes; the rest are built and withheld.',
  'field.factory.override':
    'Let this run open pull requests for items whose cell does not route deliver. The override is recorded on the evidence chain under your name. Approver only.',
  'details.factory.own_builder':
    'Name a registered builder and model for this run instead of the deployment’s default. Blank keeps the builder above.',
  'field.factory.own_builder':
    'The name of a builder registered on the server, as the run form’s Builder field takes it.',
  'field.factory.own_model':
    'Optional model id for that builder; blank uses the builder’s default.',
  'button.factory.run':
    'Queue the factory run now. It spends model budget up to the estimate shown; you can cancel and pay only for items built.',
  'button.factory.started_run':
    'The factory run you just queued; open it to watch the loop work the backlog.',
  'item.factory.id':
    'The backlog item’s id as written in the frozen backlog.',
  'item.factory.cell':
    'The class and size the item was declared as, which is the cell the route gate reads, and its kind (code, test, docs).',
  'factory.cell_route.deliverable':
    'The item’s cell routes deliver on the signed map right now, so a clean build may open a pull request. The n, rate with interval and apparatus follow.',
  'factory.cell_route.withheld':
    'The item’s cell routes something other than deliver (the reason code follows), so a clean build is withheld: built, graded and reviewed, no pull request.',
  'factory.cell_route.unmeasured':
    'Nobody has measured this class and size on this repository, so delivery would be withheld.',
  'item.factory.cell_prov':
    'The cell’s attempts (n), clean rate with its 95 % Wilson interval, and the apparatus that graded them, as the route gate read them.',
  'item.factory.status':
    'Where the item ended: not started, accepted, waiting on a signature, goes to a person, no test to prove, RED proof refused, build not clean, rejected by review, delivery failed or rework exhausted.',
  'button.factory.item_run':
    'The factory run that worked this item; its log and rows are there.',
  'button.factory.evidence':
    'Open the evidence pack of the item’s build: the belts, the diff hash, the builder and the review.',
  'link.factory.pr':
    'The pull request the factory opened in the repository, for review under the repository’s own rules.',
  'banner.factory.refusal':
    'Why the loop stopped on this item, from the chain, and the two ways forward: add the fact and register an evolution that supersedes the item, or open the change by hand and mark it done next time.',
  'banner.factory.what_to_change':
    'One sentence naming what must be different about the replacement item for the loop to get past this stop: a stronger failing test, or a fact the readiness gate asked for.',
  'item.factory.prefill':
    'The replacement item, drafted from the one that stopped and from the reason it stopped. Nothing is registered until an operator posts it; the frozen backlog does not change, the draft is chained onto it.',
  'button.factory.freeze_revised':
    'Open the freeze form prefilled from the active backlog: change what this item needs and keep the rest. This is the heavier path, a new backlog with a new hash; an evolution keeps the frozen hash.',
  'pill.factory.step_current':
    'The step the item is at out of six, and its state. All six steps are behind the disclosure below.',
  'step.factory.readiness':
    'Whether every structural fact the class needs is present and signed, and the route the item’s cell has. An unsigned structural gap refuses the item before any spend; a value gap routes test-first and is never signed.',
  'step.factory.red':
    'Whether the authored test fails on the current code before any build. No RED, no build: a test that already passes proves nothing.',
  'step.factory.build':
    'Whether the builder’s change graded clean under every belt inside the sandbox. The status is the server’s word, shown verbatim.',
  'step.factory.delivery':
    'Whether a branch and pull request were opened. Withheld names why: delivery was off for the run, or the route gate (the cell does not route deliver). Failed means the push was refused.',
  'step.factory.review':
    'The verdict of the independent review of the built change. It is advisory to a person; it never changes a route.',
  'step.factory.outcome':
    'The item’s final status on the chain, and the error if one stopped it.',
  'pill.factory.step_state':
    'Done, here (the step in hand), not yet, failed or skipped. Skipped is a deliberate withhold, not an error.',
  'field.factory.gap':
    'Which unsigned structural gap you are signing, shown as the question the class asks.',
  'field.factory.gap_answer':
    'The structural fact, written so a reviewer could check it (for example an endpoint or a file path). It is recorded on the chain under your name.',
  'button.factory.sign_gap':
    'Record the fact as signed by you. The item can then be worked by the next run.',
  'button.factory.freeze_mode':
    'Switch between the form, which asks each class’s questions, and pasting a prepared JSON backlog.',
  'button.factory.freeze_submit':
    'Validate, hash and record these items as the first event of the chain. Refused with 409 while a factory run is active.',
  'field.factory.backlog_json':
    'A prepared backlog in the API’s shape: items with id, title, class, size and structural facts, and optional authored tests.',
  'field.factory.item_id':
    'A short id unique in this backlog (letters, digits, dots, underscores, hyphens). Other items refer to it in Depends on.',
  'field.factory.item_title':
    'One line saying what the change is, as the pull request title would.',
  'field.factory.item_class':
    'The class of change from the taxonomy. It decides which structural questions are asked and which cell the route gate reads.',
  'field.factory.item_size':
    'The size tier you estimate (a complexity band, not lines). With the class it names the cell the route gate reads.',
  'field.factory.item_kind':
    'What the item produces: code, a test, or documentation.',
  'field.factory.item_level':
    'The readiness level the item is held to.',
  'field.factory.item_description':
    'What and why, as the issue would say it. Never a diff: the factory writes the change.',
  'field.factory.item_fact':
    'A fact a good test for this class needs. A structural fact left empty is the gap the run stops on until an approver signs it; a value fact routes test-first and never blocks.',
  'field.factory.item_depends':
    'Ids of items that must be accepted before this one is worked, comma-separated.',
  'button.factory.item_remove':
    'Drop this item from the backlog being frozen. Ids of removed items are not reused.',
  'button.factory.item_add':
    'Add a further item with the next free id.',

  // ── /posture — Deployment (screens/Posture/PosturePage.tsx)
  'summary.posture.version':
    'The version of the crb software this deployment is running.',
  'summary.posture.apparatus':
    'The instrument version that grades rows (grader, belt set, size table and routing rule together). Rows from different versions are never blended.',
  'summary.posture.policies':
    'The routing policy and the sign-off policy versions the server applies. A deployment may tighten a policy, never loosen it under the same name.',
  'summary.posture.licence':
    'The software licence of Commit Replay Bench.',
  'summary.posture.sign_in':
    'How people sign in: local accounts only, or your organisation’s OpenID Connect as well.',
  'summary.posture.roles':
    'The four roles and what each may do: read, start runs, sign cells, administer.',
  'summary.posture.separation':
    'The two-person rule and how it is enforced: the server refuses a sign-off whose approver produced the evidence, so an operator who queued the runs cannot also sign them.',
  'summary.posture.source_control':
    'Whether the GitHub App is registered, how many installations it has, and that its tokens are minted per use and never stored.',
  'summary.posture.executor':
    'Whether tests run in a sealed docker sandbox (rows count as evidence) or locally (a development reading, not evidence).',
  'summary.posture.builder':
    'Where the builder runs and what network it may reach. Shown to admins.',
  'summary.posture.toolchains':
    'The toolchains the worker host can run, from the health probe.',
  'summary.posture.worker':
    'Whether a worker is checking in, how many runs are queued, and when it last answered. Queued runs wait until one does.',
  'summary.posture.secrets':
    'Where credentials are read from and the guarantee that they are never persisted or returned by the API.',
  'summary.posture.writes':
    'What the factory writes to a repository: a branch named by the item and one pull request against the default branch, never the default branch itself.',
  'summary.posture.permissions':
    'The GitHub App permissions delivery needs (Contents: write, Pull requests: write) and how many installations hold them. Installations without them measure only.',
  'summary.posture.route_gate':
    'A pull request opens only for a cell the map routes deliver under the named policy.',
  'summary.posture.override':
    'An approver may override the gate for one run; the override is an event on the chain naming them and the route it overrode.',
  'summary.posture.credentials':
    'Installation tokens are minted per push and never stored.',
  'summary.posture.retention':
    'Nothing raw is kept by default; worktrees and transcripts are opt-in per run.',
  'summary.posture.ledger':
    'The live chain verification: rows, whether every hash links, and the false-Q1 total. A broken chain is a finding, never repaired in place.',
  'summary.posture.append_only':
    'Whether the database refuses updates and deletes on the ledger, from the health probe.',
  'summary.posture.export':
    'How evidence leaves the system: JSONL export and evidence packs by hash.',
  'link.posture.settings':
    'Where an admin changes this value; the row above says what it should be.',

  // ── /repos (screens/Repos/ReposPage.tsx)
  'button.repos.add':
    'Register a repository by URL or clone path with its language, runner and test layout. The walk on Connection does the same with the stages beside it.',
  'col.repos.name':
    'The name the ledger keys the repository by.',
  'col.repos.language':
    'The language and test runner configured for the repository.',
  'col.repos.probe':
    'Whether the instrument can run the repository’s tests in the sandbox, from the last toolchain probe. Nothing can be measured until it is OK.',
  'col.repos.tasks':
    'Commits mined into replayable tasks: each fails its test before the change and passes after.',
  'col.repos.gold':
    'Tasks whose own historical change passes its test in the sandbox. Only these are replayed and counted in n.',
  'col.repos.hard':
    'Tasks the miner placed in the hard pool by churn; a run can be limited to one pool.',
  'col.repos.last_run':
    'The kind and status of the most recent run, and when it finished.',

  // ── Add a repository dialog (screens/Repos/RepoNewDialog.tsx)
  'field.repo_new.name':
    'The lowercase name the ledger keys this repository by. It cannot change once rows exist.',
  'field.repo_new.preset':
    'Fills the layout fields for a well-known project shape; every field stays editable.',
  'field.repo_new.language':
    'Selects the source and test heuristics and which runners can run the repository.',
  'field.repo_new.runner':
    'The tool that executes the tests inside the sandbox. The probe verifies it.',
  'field.repo_new.source':
    'Whether the worker clones a git URL on the first run or uses an existing clone on the server host.',
  'field.repo_new.location':
    'The URL the worker clones (https or ssh only) or the path of an existing clone on the server host.',
  'field.repo_new.src_prefix':
    'A file is source if its path starts here; empty means anything outside the test prefix. Belt 4 reads this.',
  'field.repo_new.test_prefix':
    'A file is a test if its path starts here. Belt 1 reads this; Go and Rust use their own conventions.',
  'field.repo_new.ext':
    'The file extensions that count as code; default by language.',
  'field.repo_new.belt_scope':
    'The regression scope belt 3 runs after the target tests: the target only, the affected directories, or the runner’s bare discovery. The wider the scope, the more a green means.',
  'field.repo_new.belt_list':
    'Comma-separated runner scopes for belt 3, in the form the runner addresses.',
  'field.repo_new.probe':
    'A known-green test scope the probe runs to prove the toolchain. Repository-specific; never filled by a preset.',
  'field.repo_new.sandbox_image':
    'The container image with the toolchain and dependencies. The docker executor fails closed without one.',
  'button.repo_new.submit':
    'Record the repository. Nothing is cloned or run until the first run.',

  // ── /repos/:name (screens/Repos/RepoDetail.tsx + RepoConfigTab.tsx + RepoConfigForm.tsx + RunnerOptsEditor.tsx)
  'tab.repo.overview':
    'Task counts, the toolchain probe and the next steps.',
  'tab.repo.profile':
    'How the repository’s commits distribute over class and size: a census of the examined history, which weights the coverage figure on the map.',
  'tab.repo.tasks':
    'Every mined task with its class, size, pool, gold status and RED check.',
  'tab.repo.config':
    'The configuration that governs how commits are replayed: toolchain, layout, belt scope, probe, sandbox image, mining caps and runner options, with its audit trail.',
  'stat.repo.tasks':
    'Commits mined into tasks: each was RED-checked (its test fails at the parent commit). n is the same count.',
  'stat.repo.gold':
    'The share of mined tasks whose own change passes its test in the sandbox, with its 95 % Wilson interval over the mined tasks, and the clean, failed and unchecked counts. Only gold-clean tasks are replayed.',
  'stat.repo.hard':
    'Tasks in the hard pool, with the standard count beside it. A run can be limited to one pool.',
  'button.repo.probe_now':
    'Queue a toolchain probe: the configured known-green scope runs in the sandbox. Costs nothing; it uses the stored configuration.',
  'pill.repo.probe':
    'The result of the last probe with its detail line, when it ran and the run it came from. Degraded works with a caveat; Down means nothing can be measured yet.',
  'link.repo.probe_run':
    'The run that made this probe reading; its log shows the command the toolchain ran and what it printed.',
  'button.repo.start_run':
    'Open the full run form for this repository: kind, builder, model, ladder, budget and executor.',
  'button.repo.next_steps':
    'The screens that read this repository: its walk, the factory, the capability map, the oracle and its runs.',
  'col.profile.class':
    'The class of change, one row per class found in the examined history.',
  'col.profile.size':
    'The size tier. A 0 is a measured zero of the census, not an unmeasured cell.',
  'col.profile.total':
    'Commits in this class across every size.',
  'col.profile.share':
    'This class’s share of every classified commit. An exact fraction of the census, so it carries no interval.',
  'chart.profile.cell':
    'How many of the classified commits fall in this class and size. The shading scales with the count; 0 means none, measured.',
  'col.tasks.task':
    'The commit the task replays, shortened; open it for the spec and every trial.',
  'col.tasks.subject':
    'The commit’s subject line, as the author wrote it.',
  'col.tasks.class':
    'The class the miner or a labelling model gave the commit.',
  'col.tasks.size':
    'The size tier the apparatus measured for the change.',
  'col.tasks.pool':
    'Standard or hard, by churn; a run can be limited to one pool.',
  'col.tasks.churn':
    'Source lines the commit changed; the miner uses it to place the task in a pool.',
  'col.tasks.gold':
    'Whether the commit’s own change passes its test in the sandbox: clean, failed (with why), or unchecked. Only clean tasks are replayed.',
  'pill.tasks.gold':
    'Clean means the real change passes its test in the sandbox; failed names why (the task is excluded from n); unchecked means the mine run did not verify it.',
  'col.tasks.red':
    'Whether the test was seen failing at the parent commit, so the task has a real failing test.',
  'col.tasks.authored':
    'When the commit was authored in the repository’s history.',
  'button.repo_config.reset':
    'Discard your unsaved edits and show the stored configuration again.',
  'button.repo_config.probe':
    'Probe with the stored configuration. Save first: unsaved edits are not what the probe runs.',
  'button.repo_config.save':
    'Store the configuration. The change is recorded as an audit event with the redacted field diff.',
  'tile.repo_config.audit':
    'Every configuration event for this repository (registered, updated, GitHub-linked), append-only, each with who did it and the redacted field diff.',
  'pill.repo_config.changed':
    'A field this event changed; the diff under it shows the old and new value.',
  'details.repo_config.diff':
    'Opens the old and new value of each field this event changed, as recorded at write with secrets redacted.',
  'pill.repo_config.probe_result':
    'The probe run a save offered: queued or running until the worker finishes, then green (the known-green scope passed under the stored configuration) or failed with the runner’s own last line.',
  'tile.repo_config.stored':
    'The configuration exactly as the API returns it.',
  'field.repo_config.language':
    'Selects the source and test heuristics and which runners can run the repository.',
  'field.repo_config.runner':
    'The tool that executes the tests inside the sandbox; the probe verifies it.',
  'field.repo_config.clone_path':
    'Where the clone lives on the server host; empty until the worker’s first run clones the URL.',
  'field.repo_config.url':
    'What the worker clones when there is no clone yet (https or ssh only). Informational once a clone path exists.',
  'field.repo_config.src_prefix':
    'A file is source if its path starts here and has one of the extensions; empty means anything outside the test prefix. Belt 4 reads this.',
  'field.repo_config.ext':
    'The extensions that count as code, separated by a bar; empty means the language default.',
  'field.repo_config.test_mode':
    'How a test file is recognised: by a path prefix, or by a filename suffix wherever it lives (co-located tests). Belt 1 reads this.',
  'field.repo_config.test_suffix':
    'Filename endings that mark a test, separated by a bar; include .snap so snapshot-only commits keep their oracle.',
  'field.repo_config.test_prefix':
    'A file is a test if its path starts here.',
  'field.repo_config.belt_policy':
    'The regression scope belt 3 runs after the target tests: the target only, the affected directories, a bare discovery, or a list you give. The wider the scope, the more a green means.',
  'field.repo_config.belt_list':
    'One runner scope per row, in the form the runner addresses (a directory, a package pattern, a class glob).',
  'field.repo_config.probe':
    'A known-green scope the probe runs to prove the toolchain; empty means the runner’s bare discovery.',
  'field.repo_config.sandbox_image':
    'The container image with toolchain and dependencies. The docker executor fails closed without one.',
  'field.repo_config.layer':
    'A free label for grouping repositories in reports; no runner reads it.',
  'field.repo_config.mining':
    'How far a mine run walks history and how many tasks it keeps per pool. Empty means the miner’s default.',
  'field.repo_config.runner_view':
    'Edit the runner options field by field, or as the whole JSON object.',
  'field.repo_config.runner_opt':
    'An option passed to the test runner inside the sandbox (timeouts, binaries, environment, flags). The description under each names its default.',
  'field.repo_config.runner_json':
    'The whole runner_opts object as stored. Edits apply as you type once the JSON parses.',
  'button.repo_config.runner_remove':
    'Drop this option so the runner uses its default.',
  'button.repo_config.list_edit':
    'Add a row to the list, or remove this one.',

  // ── /runs (screens/Runs/RunsPage.tsx)
  'field.runs.kind_filter':
    'Show only runs of one kind: mine, replay, blind, oracle, controls, label, probe or factory.',
  'field.runs.status_filter':
    'Show only runs in one state: queued, running, succeeded, failed or cancelled.',
  'button.runs.start':
    'Open the full run form: kind, builder, model, ladder, budget caps, executor. Replay, blind and factory runs spend model budget.',
  'col.runs.id':
    'The run’s id, shortened. Open it for its log, tiles and rows.',
  'col.runs.repo':
    'The repository the run worked; every row it graded belongs to it.',
  'col.runs.kind':
    'What the run did, and for a replay or blind run its grading mode.',
  'col.runs.status':
    'Queued, running, succeeded, failed or cancelled; a cancel that was requested but not yet honoured is noted.',
  'col.runs.progress':
    'Tasks attempted of tasks planned, as a bar and a count.',
  'chart.runs.progress':
    'Tasks attempted out of tasks planned for this run, as a share. Red when the run failed, green when it succeeded.',
  'col.runs.clean':
    'Tasks graded clean out of tasks graded in this run. A count, not a rate: the rate with its interval is on the run page.',
  'col.runs.dq_err':
    'Tasks disqualified (a test tampered or a malformed oracle) and tasks that hit a harness or sandbox error. Neither counts as clean.',
  'col.runs.builder':
    'The builder and model the run used, when it used one.',
  'col.runs.cost':
    'Builder-reported dollars, summed over the run’s attempts. A measurement, not an estimate.',
  'col.runs.created':
    'When the run was queued. Newest first by default.',

  // ── Start a run dialog (screens/Runs/RunNewDialog.tsx)
  'field.run_new.repo':
    'The repository the run works; every row it grades belongs to it.',
  'field.run_new.kind':
    'What the run does. Mine, oracle, controls, label and probe cost nothing; replay and blind call a builder and spend. The line under it says what each produces.',
  'field.run_new.mode':
    'Derived from the kind: replay is sighted (the builder sees the failing test), blind is blind (it sees only a description). The two are never one rate.',
  'field.run_new.builder':
    'A builder registered on the server; the line under it names which have credentials configured.',
  'field.run_new.model':
    'The model id the builder runs; blank uses the builder’s default. Every rate is reported with its model.',
  'field.run_new.provider':
    'The inference provider, when the builder supports more than one. Stamped on every row.',
  'field.run_new.ladder':
    'Comma-separated rung labels; each rung is one attempt, and the next runs only if the previous was not clean. Object rungs below are appended in order.',
  'field.run_new.cli_login':
    'Run the builder on the operator’s own subscription login instead of an API key. Developer and evaluation use only; the repository’s CLAUDE.md is auto-discovered in this mode.',
  'field.run_new.budget':
    'The cap per attempt on turns, tool calls, tokens, cost and wall clock. Blank is the builder’s default (shown); 0 tokens or $0 means no cap. Every row is stamped with the tier it ran under.',
  'button.run_new.add_rung':
    'Append a rung of this builder and model with its own caps. Blank caps inherit the run budget.',
  'button.run_new.sweep':
    'Replace the ladder with three rungs of this builder and model at 25, 50 and 100 tool calls: the same model at an escalating budget.',
  'button.run_new.clear_rungs':
    'Remove every object rung from the ladder; the label list above stays.',
  'field.run_new.rung':
    'This rung’s builder, model, provider and per-attempt caps. The tier shown beside the rung number is what its rows will be stamped with.',
  'button.run_new.remove_rung':
    'Drop this rung from the ladder; the rungs after it move up.',
  'field.run_new.builder_config':
    'Constructor overrides applied to every rung and stamped into the run’s apparatus. Model, provider and credential keys are refused here: identity comes from the ladder, secrets from the worker’s environment.',
  'field.run_new.limit':
    'The most tasks to attempt; blank means every eligible task.',
  'field.run_new.pool':
    'Limit the run to the standard or the hard pool of tasks.',
  'field.run_new.executor':
    'Where tests run: the server default, docker (sealed; rows count as evidence) or local (a development reading). Docker fails closed when unavailable.',
  'field.run_new.timeout':
    'The cap on one test run inside the sandbox. A timeout is a failure, never a pass.',
  'button.run_new.queue':
    'Put the run on the queue for the next worker. A replay, blind or factory run spends model budget; you can cancel it from its page.',

  // ── /runs/:id (screens/Runs/RunDetailPage.tsx + LiveLog.tsx + EvidenceDrawer.tsx + ReviewPanel.tsx)
  'pill.run.status':
    'Queued means nothing has started or been spent; Running means a worker holds it; Succeeded, Failed and Cancelled are final and keep every graded row.',
  'pill.run.cancel_requested':
    'Someone asked the run to stop; the worker ends it after the attempt in flight.',
  'stat.run.identity':
    'The mode, builder, model, provider and ladder this run graded under. A rate quoted without these is not a claim.',
  'link.run.repo':
    'The repository this run worked; opens its overview, tasks and configuration.',
  'button.run.cancel':
    'Stop after the attempt in flight. Attempts already made are still charged and their rows are kept.',
  'chart.run.progress':
    'Tasks attempted out of tasks planned, as a share.',
  'stat.run.queue':
    'Where this run sits in the queue and how many are ahead of it. Nothing is spent while queued.',
  'stat.run.now':
    'When the run started, what it has spent, and how long is left estimated from the finished tasks’ latencies (so it firms up as tasks finish).',
  'stat.run.stage':
    'The stage the last event puts the current task in (setup, build, grade, ledger).',
  'stat.run.heartbeat':
    'When the worker last checked in against how long it may stay silent. Amber means it may have stopped; queued runs wait until one answers.',
  'stat.run.clean':
    'The share of graded tasks clean on any rung of the ladder, over n graded tasks, with its 95 % Wilson interval and the apparatus that graded them.',
  'stat.run.first_pass':
    'The share of graded tasks clean on the first rung alone, over the same n, with its interval. The gap to Clean (any rung) is what the later rungs bought.',
  'stat.run.disqualified':
    'Tasks disqualified for tampering with a test or a malformed oracle. Excluded from n, counted neither way.',
  'stat.run.errors':
    'Tasks that hit a harness or sandbox error. The instrument failed closed; they are not counted clean.',
  'stat.run.rows':
    'Rows this run appended to the ledger: one per attempt, so a ladder with several rungs writes several rows per task.',
  'stat.run.rows_live':
    'How many ledger rows the not-clean breakdown below is read from so far; updating means the run is still writing rows and the figures will move.',
  'stat.run.event_count':
    'How many step events the live log has received on this stream, malformed frames excluded.',
  'stat.run.cost':
    'Builder-reported dollars, summed over the run’s attempts. A measurement, not an estimate.',
  'stat.run.detail_counter':
    'This run kind’s own counter, served verbatim (for a mine run: candidates examined, tasks found, skipped). n is the candidates examined.',
  'stat.run.split_point':
    'Clean rows over every eligible row of the run, with its 95 % Wilson interval. This is the rate that routes.',
  'stat.run.split_model':
    'Clean over clean plus red: the builder’s rate where it got a fair, finished attempt, with its interval. Diagnostic, never a gate.',
  'stat.run.split_instrument':
    'Rows the harness or a guard failed, not the model. They count against autonomy until the instrument is fixed.',
  'stat.run.split_budget':
    'Attempts cut short by their own cap on wall clock, turns, tool calls, tokens or cost.',
  'stat.run.split_cost_known':
    'Rows whose dollar figure is a measurement (a true $0 counts) out of all rows; the rest carry no price and are left out of cost means.',
  'pill.run.split':
    'Every row of the run by what happened to it: clean, red, lint, budget, protocol, harness, outage, DQ. n is clean plus red plus budget plus protocol plus harness; DQ and outage sit outside n.',
  'pill.run.stream':
    'Whether the live event stream is connected, reconnecting, or done. Reconnects and dropped events are counted beside it.',
  'field.run.log_explain':
    'Show one plain sentence under each event saying what it means.',
  'field.run.log_follow':
    'Keep the newest event in view as they arrive.',
  'pill.run.event_status':
    'The event’s outcome: ok, error, invalid, skipped or in progress.',
  'link.run.event_task':
    'The task this event belongs to; click to filter the per-task table to it.',
  'col.run_tasks.task':
    'The task attempted, shortened. Click the row to open the evidence pack of its last trial.',
  'col.run_tasks.cell':
    'The class and size tier the task falls in: the cell its row counts toward on the map.',
  'col.run_tasks.trials':
    'How many rungs of the ladder were attempted for this task.',
  'col.run_tasks.outcome':
    'Clean (every recorded belt held), not clean, disqualified (excluded from n) or error (the instrument failed).',
  'pill.run_tasks.outcome':
    'Clean means every recorded belt held on some rung; DQ is excluded from the denominator; error means the harness, not the builder, failed.',
  'col.run_tasks.belts':
    'Each belt’s result on the last rung: tick held, cross failed, dash not recorded or not evaluated.',
  'col.run_tasks.cost_latency':
    'Builder-reported dollars and wall-clock seconds for the task’s attempts.',
  'col.run_tasks.evidence':
    'The evidence pack of each rung, by hash. The hash is the row’s permanent reference.',
  'link.run_tasks.pack':
    'Open this rung’s evidence pack: the spec, every belt’s result, the diff hash, the builder and the review.',
  'pill.evidence.grade':
    'The pack’s grade: clean (every belt held), disqualified (with why), or not clean.',
  'pill.evidence.verified':
    'Whether the pack’s hash matches its canonical body. A mismatch means the evidence is untrusted.',
  'stat.evidence.hash':
    'The pack’s hash, shortened; the full hash is the row’s permanent reference.',
  'tile.evidence.spec':
    'The task as the builder received it: its files, target tests, belt scope, how many tests were failing at the parent, and its gold status.',
  'tile.evidence.belts':
    'Each belt’s result with the test runs behind belts 2 and 3 (and the lint run for belt 5), tampered files and new failures named.',
  'tile.evidence.diff':
    'The files the builder changed, lines added and removed, and the diff’s hash; the bytes themselves are on the Patch tab when retained.',
  'tile.evidence.builder':
    'The builder, model and provider, attempts and turns, tokens in and out, cost, latency, and whether a transcript was kept.',
  'tile.evidence.apparatus':
    'The instrument version, belt set and executor that graded this pack.',
  'tile.evidence.json':
    'The whole pack as stored, for an auditor.',
  'tab.evidence':
    'Pack is the graded record; Patch is the retained diff verified against the pack; Transcript is the builder’s conversation when kept; Review is where a person records what they read.',
  'pill.evidence.patch_verified':
    'Whether the served patch hashes to the diff hash in the pack. A mismatch means the bytes shown are not what was graded.',
  'pill.evidence.patch_flags':
    'Redacted means secret-shaped content was removed before serving; truncated means the patch was capped at 1 MiB.',
  'pill.evidence.test_run':
    'How this test run ended: green (every test in the scope passed), red with the runner’s return code, timed out, or a parse error when the runner’s output could not be read. Open it for the failing ids and the redacted output tail.',
  'pill.evidence.lint_run':
    'What the repository’s own formatter or linter said about the changed files (belt 5): accepted, rejected, could not run, or not evaluated when none is configured.',
  'tile.evidence.patch_excluded':
    'This file is in the served patch but not in the pack’s diff file list, for example the overlaid oracle test; it is shown but not counted in the additions and deletions.',
  'button.review.finding':
    'Mark a finding you saw in the diff: regression, defect, API change or style. The worst finding becomes the verdict.',
  'pill.review.draft_verdict':
    'The verdict your findings will record, derived from the worst one; OK when none.',
  'field.review.finding':
    'What you saw, in one sentence, and where.',
  'field.review.mergeable':
    'Would a maintainer merge this as it stands? Recorded with the review; it never changes a route.',
  'field.review.statement':
    'What you concluded and why. This is the governance record, append-only.',
  'field.review.not_reviewed':
    'Record that you looked but could not review this row: no findings, no anchor hash.',
  'tile.review.anchor':
    'The hash of the patch you loaded against the pack’s diff hash. A review is anchored only when they match, so it records what you actually read.',
  'button.review.record':
    'Append the review to the ledger, hash-chained and anchored to the patch you loaded.',
  'pill.review.mergeable':
    'Whether that reviewer would merge the change as it stood.',

  // ── /tasks/:repo/:taskId (screens/Runs/TaskDetailPage.tsx)
  'tile.task.id':
    'The commit the task replays, or for a factory item the hash of the authored test the factory wrote as its RED proof.',
  'tile.task.authored':
    'When the commit was authored in the repository’s history.',
  'tile.task.target_tests':
    'The tests the change must make pass: belt 2.',
  'tile.task.belt_scope':
    'The regression scope belt 3 runs after the target tests; BARE means the runner’s own discovery.',
  'tile.task.files':
    'The files the commit touched, split into tests (which the builder must not change) and source (which it must).',
  'tile.task.red_gold':
    'Whether the test was seen failing at the parent, and whether the real change passes it in the sandbox. A task that is not gold-clean is excluded from n.',
  'tile.task.full_spec':
    'The task specification exactly as stored.',
  'col.task.created':
    'When the row was graded and appended to the ledger.',
  'col.task.run':
    'The run that produced the row; open it for the log and the other rows.',
  'col.task.trial':
    'The grading mode (sighted or blind) and the rung of the ladder.',
  'col.task.builder':
    'The builder and model that made the attempt.',
  'col.task.clean':
    'Clean (every evaluated belt held), DQ (excluded from n) or not clean, with the error when the instrument failed.',
  'pill.task.clean':
    'Clean means every evaluated belt held; DQ names why the row is excluded; no means a belt failed or the instrument errored.',
  'col.task.belts':
    'Each belt’s result: tick held, cross failed, dash not recorded or not evaluated.',
  'col.task.cost_latency':
    'Builder-reported dollars and wall-clock seconds for the attempt.',
  'col.task.provenance':
    'The apparatus version and belt set that graded the row, and whether it was measured here or imported.',
  'col.task.review':
    'The standing human review of the row, if any; click it to read the review. Not reviewed means no one has.',
  'col.task.evidence':
    'The evidence pack by hash; open it for every belt and the diff.',

  // ── /capability — Map grid (screens/Capability/CapabilityPage.tsx)
  'button.capability.export':
    'Download the ledger rows behind this map for this repository as CSV.',
  'stat.capability.coverage':
    'The share of this repository’s change volume (its change profile, weighted by commit count) whose cell routes deliver. A coverage of the profile, not a sampled rate, so it carries no interval; each cell’s rate carries its own.',
  'stat.capability.measured_cells':
    'Cells with at least one graded attempt out of every class and size on the grid, under the apparatus shown.',
  'stat.capability.false_q1':
    'Rows credited clean against a failed belt, across the map. Must be 0; any other value halts delivery and marks every number here untrusted.',
  'stat.capability.controls':
    'The controls verdict with how many controls were constructible out of the total, and the gate the policy applies: passed, at least half constructible and no escapes for deliver.',
  'banner.capability.false_q1':
    'A cell contains a clean row whose belts did not all hold. Treat every number on this page as untrusted until the ledger is audited.',
  'field.capability.by_language':
    'Split each class and size cell by the language of the task. Several cells may then stack in one slot.',
  'field.capability.language':
    'Show only cells of one language; all keeps every language stacked in its slot.',
  'field.capability.by_model':
    'Split each cell by the model that made the attempts. A rate is always about one model.',
  'field.capability.model':
    'Show only cells measured with one model.',
  'col.capability.class':
    'The class of change; every class of the taxonomy is shown so a 0-count class is visible.',
  'col.capability.size':
    'The size tier as the apparatus measures it.',
  'map.cell.tile':
    'One cell: its route, n, point with its interval and clean count, the interval bar against the policy ticks, the model rate and split, then false-Q1, mean cost, mean latency, oracle strength and the verification tier glyph. Open it for every number with its method.',
  'map.cell.fq1':
    'The false-Q1 count for this cell. Must be 0.',
  'map.cell.cost':
    'Mean builder-reported dollars per attempt in this cell.',
  'map.cell.latency':
    'Mean wall-clock time per attempt in this cell.',
  'map.cell.oracle':
    'Mean oracle strength of the tasks in this cell (faults caught over faults planted). Below the policy bar the cell routes to a human.',
  'map.cell.tier':
    'The verification tier: tick for human-verified or A/B-confirmed, half-disc for an automated pass, cross for untrusted.',
  'map.cell.grid_not_measured':
    'No graded attempt for this class and size (n = 0). It says nothing, not zero.',
  'tile.capability.legend':
    'What each number on a tile is, in order, with the terms one click away.',
  'tile.capability.detail_head':
    'The open cell’s route, verification tier, and the apparatus and belt set its rows carry.',
  'tile.capability.reason':
    'The reason code and sentence the routing rule gave this cell.',
  'tile.capability.split':
    'The rows that were not clean, by what happened: red, lint, budget, protocol, harness, DQ. n is clean plus red plus budget plus protocol plus harness; DQ sits outside n.',
  'stat.capability.point':
    'Clean attempts over every eligible attempt in this cell, with its 95 % Wilson interval. This is the rate that routes.',
  'stat.capability.n_tasks':
    'How many different commits stand behind the n attempts. Fewer than five means the rate leans on a handful of commits, which the interval does not show.',
  'stat.capability.model_point':
    'Clean over clean plus red: the builder’s rate on fair, finished attempts, with its interval. Diagnostic, not a gate.',
  'stat.capability.cell_false_q1':
    'Rows in this cell credited clean against a failed belt. Must be 0.',
  'stat.capability.cost':
    'Mean builder-reported dollars per attempt in this cell over n. A mean, no interval.',
  'stat.capability.latency':
    'Mean wall-clock time of the build per attempt over n. A mean, no interval.',
  'stat.capability.oracle':
    'Mean mutation kill-rate of the tasks’ tests in this cell. Below the policy bar the cell routes to a human.',
  'banner.capability.ci_drift':
    'The interval recomputed in the browser differs from the server’s; the server’s is shown and the drift is flagged, not hidden.',
  'button.capability.rows':
    'The ledger filtered to this cell’s rows.',
  'button.capability.routing':
    'The routes table for this repository, with every reason code and the policy thresholds.',
  'button.capability.close':
    'Close the open cell and return to the grid alone.',
  'button.capability.start_replay':
    'Open the run form on a sighted replay for this repository; each graded trial is one observation in its cell.',

  // ── /routing — Routes (screens/Routing/RoutingPage.tsx)
  'policy.routing.min_n':
    'The fewest attempts a cell needs before it can route deliver.',
  'policy.routing.min_point':
    'The lowest clean rate a cell may have and still route deliver.',
  'policy.routing.min_ci_low':
    'The lowest the 95 % Wilson lower bound may be for deliver. It rises toward the point as n grows.',
  'policy.routing.min_oracle':
    'The lowest mean mutation strength a cell’s tasks may have for deliver, when measured.',
  'policy.routing.granularize':
    'The size tiers that are split before they are attempted.',
  'policy.routing.min_controls_share':
    'The share of control rows that must be constructible for the controls report to count.',
  'policy.routing.max_escapes':
    'How many controls may escape before deliver is withheld. Zero in the published policy.',
  'tile.routing.rule':
    'The one rule in words: every clause a cell must clear for deliver and which failures send it to do not ship, granularize, human or calibrate.',
  'stat.routing.route_count':
    'How many cells route this way, out of every measured cell (n). Counts of cells, not attempts.',
  'col.routing.cell':
    'The class and size (and language, builder, model or provider where projected) the decision is for.',
  'col.routing.route':
    'The route the published rule gave the cell from its own evidence.',
  'col.routing.code':
    'The reason code naming the first clause of the rule that decided the route. Click a code for its sentence.',
  'col.routing.n':
    'Graded attempts in the cell; the rule needs at least its minimum n for deliver.',
  'col.routing.point':
    'The share of attempts graded clean: the all-rows rate that routes.',
  'col.routing.model_split':
    'The builder’s rate on fair attempts and the split of what was not clean, beside the routing rate, never instead of it.',
  'col.routing.ci_low':
    'The lower bound of the 95 % Wilson interval: the figure the rule compares to its bar.',
  'col.routing.interval':
    'The interval as a bar with the policy ticks, from the server’s own bounds.',
  'col.routing.false_q1':
    'Rows credited clean against a failed belt. Any value above 0 routes do not ship.',
  'col.routing.oracle':
    'The cell’s mean mutation strength, or a dash when unmeasured.',
  'col.routing.reason':
    'The rule’s sentence for this decision, verbatim.',
  'col.routing.policy':
    'The policy version that produced the decision.',

  // ── /oracle (screens/Oracle/OraclePage.tsx)
  'stat.oracle.mean':
    'The mean of every scored task’s kill-rate (faults caught over faults planted), over n scored tasks, under the policy and apparatus shown. Each task carries its own interval below; a mean of rates has none.',
  'stat.oracle.strong':
    'Tasks whose strength is at or above the deliver floor, out of every task. A green on these clears the oracle bar.',
  'stat.oracle.adequate':
    'Tasks between the adequate floor and the deliver floor. A green on these clears the bar; every change still goes to review.',
  'stat.oracle.weak':
    'Tasks below the adequate floor. A green on these is low confidence and routes to a human.',
  'stat.oracle.unscoreable':
    'Tasks where no fault could be planted, so they carry no strength. Counted, never averaged, and never clear the bar.',
  'col.oracle_cell.cell':
    'The class and size tier the scores are aggregated to.',
  'col.oracle_cell.n':
    'Scored tasks in the cell; unscoreable tasks are not counted here.',
  'col.oracle_cell.strength':
    'The mean kill-rate of the cell’s scored tasks.',
  'col.oracle_cell.band':
    'Strong, adequate, weak or unscoreable, against the policy’s floors.',
  'col.oracle_cell.gate':
    'What a green licenses at that strength: clears the bar, review-gated, or needs a human.',
  'col.oracle_task.task':
    'The task scored; open it for its spec and trials.',
  'col.oracle_task.strength':
    'Faults caught over faults planted for this task, with its 95 % Wilson interval computed from those counts.',
  'col.oracle_task.mutants':
    'Faults the tests noticed over faults planted on the changed lines: the n behind the strength.',
  'gate.oracle.controls':
    'The latest negative-controls report as a gate: the server’s verdict, whether any violation occurred, that a report exists, and the escapes as findings.',
  'gate.oracle.verdict':
    'The server’s reduction of the report: passed, escaped, thin, failed or unmeasured, with constructible, share and escapes. This is what every cell was routed under.',
  'gate.oracle.violations':
    'A violation is the grader passing a cheat it must refuse: an instrument defect. The count is over every control row.',
  'gate.oracle.present':
    'How many tasks and control rows the report covers.',
  'gate.oracle.escapes':
    'Escapes (a cheat the tests could not tell from a fix), controls not constructible, and controls skipped. Findings about the tests, not failures of the grader.',
  'button.oracle.run_controls':
    'Queue the negative-control matrix for this repository. Costs nothing.',
  'button.oracle.run_oracle':
    'Queue an oracle run to plant faults on each task’s changed lines and score its tests. Costs nothing.',
  'col.controls.task':
    'The task the control was built on; open it for its spec and trials.',
  'col.controls.control':
    'Which deliberate cheat: gold (the real change), noop, test-tamper, stub, regression, hardcode-cheat or env-poison.',
  'col.controls.expected':
    'What the grader must say for this cheat, and what it said.',
  'col.controls.verdict':
    'ok means the grader answered as it must; VIOLATION means it passed a cheat (an instrument defect); ESCAPE means the tests could not tell (a finding about the tests); not constructible or skip means the control could not be built.',
  'pill.controls.verdict':
    'ok: the grader refused what it must. VIOLATION: it passed a cheat, an instrument defect. ESCAPE: the repository’s tests could not tell, a finding about the tests.',
  'col.controls.note_duration':
    'The grader’s note for the row and how long the control took.',

  // ── /learn (screens/Learn/LearnPage.tsx)
  'stat.learn.refusal_share':
    'Rows a builder guard refused as a share of every row, per apparatus version, with its 95 % Wilson interval. Amber above 5 %: read every class until it is below.',
  'stat.learn.refusal_classes':
    'How many distinct (guard, reason, command shape) groups the refused rows fall into, over n refused rows.',
  'stat.learn.refusal_cost':
    'Builder-reported dollars and minutes spent on attempts that ended in a refusal.',
  'col.learn_refusals.n':
    'Refused rows in this class, across every run of the repository.',
  'col.learn_refusals.guard':
    'Which guard refused: network, archaeology or tamper.',
  'pill.learn.guard':
    'The guard family that refused the command: network (an outbound call), archaeology (reading history it must not), or tamper.',
  'col.learn_refusals.reason_shape':
    'The guard’s reason and the shape of the command it refused, with arguments generalised.',
  'col.learn_refusals.cost':
    'Dollars spent on the attempts in this class before they were refused.',
  'col.learn_refusals.verdict':
    'Always unsure here: a person decides whether the refusal was honest or should be allowed, and writes the line into the guard corpus.',
  'pill.learn.verdict':
    'The product never decides: a person writes honest or refuse for this class with the command-line tool.',
  'stat.learn.oracle_held':
    'Cells withheld from deliver because their oracle is under the bar or their controls escaped or were thin, under the routing policy and threshold shown. More attempts will not move these; stronger tests will.',
  'stat.learn.items':
    'Test-writing items proposed in the frozen-backlog shape, one per held cell, ready to freeze on the Factory.',
  'stat.learn.no_scores':
    'Held cells whose tasks have no mutation score yet, so the escaped mutants cannot be listed. Run an oracle run to fill them.',
  'col.learn_strengthen.item':
    'The proposed test-writing item and its title.',
  'col.learn_strengthen.cell':
    'The class and size the item would strengthen.',
  'col.learn_strengthen.reason':
    'The reason code that withheld the cell: a weak oracle, an escaped control or thin controls.',
  'pill.learn.held_reason':
    'The routing reason that withheld deliver from this cell.',
  'col.learn_strengthen.strength':
    'The cell’s oracle strength against the policy threshold.',
  'col.learn_strengthen.escaped':
    'How many negative controls escaped in this cell (a cheat the tests could not tell).',
  'stat.learn.stale_rows':
    'Rows older than the current apparatus out of every row for this repository. Stale evidence is kept as history and licenses nothing.',
  'stat.learn.needed':
    'Attempts still needed on the current apparatus to bring every stale cell back to the rule’s minimum n, over the cells that are stale.',
  'stat.learn.remeasure_cost':
    'Each stale cell’s own mean row cost times the rows it still needs, summed over the cells with a known cost. A dash means no cost is known.',
  'col.learn_remeasure.cell':
    'The class and size whose rows predate the current apparatus.',
  'col.learn_remeasure.counts':
    'Rows on older apparatus versions (named), rows on the current one, and how many more the rule needs.',
  'col.learn_remeasure.cost':
    'The cell’s mean row cost times the rows needed; a question mark when no cost is known.',
  'col.learn_remeasure.runs':
    'How many run requests the plan lists to close the gap.',
  'link.learn.oracle':
    'The oracle page for this repository, where an oracle run is queued and scores are read.',
  'link.learn.runs':
    'The runs page for this repository, where the plan’s runs are queued.',

  // ── /ledger (screens/Ledger/LedgerPage.tsx)
  'button.ledger.export_jsonl':
    'Download the rows (filtered to the repository if one is chosen) as JSON lines, the form the chain verifies.',
  'button.ledger.export_csv':
    'Download the same rows as CSV for a spreadsheet.',
  'button.ledger.export_abstract':
    'Download cells only: no code, no identifiers. This is what a federated deployment may share.',
  'gate.ledger.banner':
    'The live proof that the ledger is intact: every row’s hash links to the previous one, and no row is credited clean against its belts.',
  'gate.ledger.chain':
    'Every row’s prev_hash and row_hash match across the whole ledger. A broken chain names the row; it is a finding, never repaired in place.',
  'gate.ledger.false_q1':
    'No row anywhere is credited clean against a failed belt. Enforced when a row is written and re-derived when read.',
  'stat.ledger.rows':
    'Every row on the ledger across every repository.',
  'stat.ledger.false_q1':
    'Rows credited clean against a failed belt, across the whole ledger. Must be 0; it is the number everything else defends.',
  'stat.ledger.matching':
    'Rows matching the current filters, out of the whole ledger; the table shows one page of them.',
  'field.ledger.clean':
    'Show only clean rows, or only rows that were not clean.',
  'field.ledger.mode':
    'Show only sighted rows (the builder saw the failing test) or only blind rows. The two are never one rate.',
  'field.ledger.size':
    'Show only rows of one size tier; all keeps every tier.',
  'field.ledger.class':
    'Show only rows of one class of change; press Enter or leave the field to apply.',
  'field.ledger.model':
    'Show only rows made with one model; press Enter or leave the field to apply.',
  'col.ledger.created':
    'When the row was appended to the ledger. Newest first by default.',
  'col.ledger.repo':
    'The repository the row was graded on; the picker above filters to one.',
  'col.ledger.task':
    'The task attempted, shortened; open it for its spec and every trial.',
  'col.ledger.cell':
    'The class and size the row counts toward on the map.',
  'col.ledger.builder':
    'The builder and model that made the attempt.',
  'col.ledger.mode':
    'Sighted or blind, and the rung of the ladder.',
  'col.ledger.clean':
    'Clean (every evaluated belt held), DQ (excluded from n, with why) or not clean; error when the instrument failed.',
  'pill.ledger.clean':
    'Clean means every evaluated belt held; DQ names why the row is excluded; no means a belt failed; error means the instrument failed.',
  'col.ledger.belts':
    'Each belt’s result as a glyph: tick held, cross failed, dash not recorded or not evaluated. A belt the row’s apparatus never had is not shown.',
  'col.ledger.cost_latency_oracle':
    'Builder-reported dollars, wall-clock seconds, and the task’s oracle strength when scored.',
  'col.ledger.provenance':
    'The apparatus version and belt set that graded the row, and whether it was measured here or imported.',
  'col.ledger.hash':
    'The row’s hash, shortened; the full hash is its permanent reference and the link in the chain.',
  'stat.ledger.page':
    'Which rows of the matching set are shown.',
  'button.ledger.page':
    'Move through the matching rows one page at a time.',

  // ── /settings (screens/Settings/SettingsPage.tsx + GitHubAppCard.tsx + ClaudeCodeLoginCard.tsx)
  'pill.settings.health':
    'The worst status among the probes below; a skipped probe never lowers it.',
  'stat.settings.version':
    'crb (the software), apparatus (the instrument that grades rows) and policy (the routing rule): the three versions every claim cites.',
  'pill.settings.probe':
    'One health check with its status and a detail line saying what it found; a probe that is not OK explains itself here.',
  'tile.settings.claude_login':
    'The builder sign-in for the claude_code builder in cli mode: whether a token is stored (only its last four characters are ever shown) and whether it works.',
  'pill.settings.token':
    'Whether a builder token is stored on this deployment, identified by its last four characters only.',
  'pill.settings.verify':
    'Whether the stored token was accepted when tried: ok, rejected, the CLI missing on the host, or a timeout.',
  'button.settings.claude_signin':
    'Start the sign-in flow: you get a code to paste from Anthropic; the token is stored on the server and never shown again.',
  'field.settings.claude_code':
    'The one-time code the sign-in page gave you.',
  'field.settings.token':
    'Paste a token to store. Never shown again after saving; only its last four characters are reported.',
  'button.settings.token_save':
    'Store the token on the server for the worker to use.',
  'button.settings.verify_login':
    'Try the stored token once, through the builder’s own environment, and report whether it was accepted; allowed once every 10 seconds.',
  'button.settings.remove_token':
    'Delete the stored token from the server; builders in cli mode stop working until a new one is stored.',
  'pill.settings.signin_state':
    'Where the sign-in flow is: waiting for the code, exchanging it, done or failed.',
  'pill.settings.github_configured':
    'Whether the App id and private key are set on the API and the worker. Without them repositories connect by URL only.',
  'button.settings.github_sync':
    'Ask GitHub which organisations installed the App and with what permissions, and record them here.',
  'pill.settings.installation':
    'Can deliver means the installation holds Contents: write and Pull requests: write; read-only means it can measure but not open pull requests; uninstalled means GitHub reports it suspended.',
  'tile.settings.sandbox_mode':
    'The test executor the worker uses: docker (sealed; rows count as evidence) or local (a development reading).',
  'tile.settings.ledger_backend':
    'Where the ledger is stored (the database the append-only chain lives in).',
  'tile.settings.apparatus_policy':
    'The instrument version and the routing policy version in force.',
  'tile.settings.oidc':
    'Whether organisation sign-in through OpenID Connect is enabled.',
  'pill.settings.builder':
    'A builder provider and whether its credential is configured on the worker. Configured or not is all the API reports; the secret itself is never returned.',
  'tile.settings.retention':
    'The retention settings in force: what raw artefacts are kept and for how long. Zero raw retention by default.',
  'col.settings.users':
    'The account’s sign-in name, display name, email, where it is issued (local or the OpenID provider) and when it was created.',
  'col.settings.role':
    'The account’s role. Changing it here takes effect on the person’s next request.',
  'field.settings.user_role':
    'Set this account’s role: viewer, operator, approver or admin. Keep operator and approver on different people.',
  'field.settings.new_username':
    'The sign-in name for a new local account.',
  'field.settings.new_display':
    'The name shown in the header and on attestations.',
  'field.settings.new_email':
    'The account’s email, used to identify the person on records.',
  'field.settings.new_role':
    'The role the new account starts with. An approver is what task 7 on Home asks for.',
  'field.settings.new_password':
    'A first password for the local account. It is never echoed back.',
  'button.settings.create_user':
    'Create the local account with the role chosen.',

  // ── /help, /help/docs/:name, 404
  'link.help.read_more':
    'The guide section that says more about this term.',
  'link.help.guide':
    'Open this bundled guide; its sections are what the Read more links point at.',
  'button.notfound.home':
    'Return to Home, the start of the journey, with the navigation intact.',
} as const satisfies Record<string, string>

export type HintId = keyof typeof HINTS

/**
 * The ids shared components derive themselves (`VerdictPill`, `BeltPills`, `ControlsPill`…): the
 * orphan check in hints-ratchet.test.tsx ("every registered id is referenced") exempts them,
 * with `tab.repo.*` (derived by RepoDetail), from needing a literal `'<id>'` in a source file.
 */
export const SHARED_IDS: readonly HintId[] = [
  'route.deliver',
  'route.calibrate',
  'route.granularize',
  'route.human',
  'route.do_not_ship',
  'route.not_yet_measured',
  'belt.tests_unmodified',
  'belt.target_green',
  'belt.no_new_failures',
  'belt.source_changed',
  'belt.repo_lint_clean',
  'kind.builder_red',
  'kind.lint',
  'kind.budget',
  'kind.protocol',
  'kind.harness',
  'kind.outage',
  'kind.disqualified',
  'stat.shared.model_rate',
  'controls.passed',
  'controls.failed',
  'controls.escaped',
  'controls.thin',
  'controls.unmeasured',
  'provenance.measured',
  'provenance.imported',
  'provenance.mixed',
  'chart.ci_bar',
  'run.status',
  'probe.status',
  'tier.verification',
  'oracle.band',
  'oracle.gate',
  'review.verdict',
  'nav.journey_position',
]

/**
 * The minimum number of hinted elements each route must render under the standard fixtures
 * (from hints-inventory.md, minus dialogs and role-gated forms); the ratchet fails below it so a
 * screen that silently lost its data cannot pass vacuously.
 */
export const MIN_HINTS: Record<string, number> = {
  '/home': 10,
  '/connect': 8,
  '/connect/:name': 14,
  '/connect/:name/measure': 10,
  '/results': 30,
  '/decisions': 6,
  '/signoff': 30,
  '/factory': 28,
  '/posture': 22,
  '/repos': 8,
  // the Overview tab (the state a reader lands on); the Change profile, Tasks and Configuration tabs are held by the ratchet's variants
  '/repos/:name': 14,
  '/runs': 13,
  '/runs/:id': 24,
  '/tasks/:repo/:taskId': 16,
  '/capability': 28,
  '/routing': 20,
  '/oracle': 22,
  '/learn': 26,
  '/ledger': 26,
  // a viewer's Settings (health, the login card read-only, the GitHub App); the admin's configuration and users are held by the ratchet's variants
  '/settings': 11,
}

/** The text for an id; the union type makes a typo a compile error, so this can never be undefined. */
export function hintText(id: HintId): string {
  return HINTS[id]
}
