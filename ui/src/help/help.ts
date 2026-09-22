/**
 * The screen help registry — what every screen is for, what each role does next, what its
 * numbers mean, its terms and where to read more.
 *
 * Navigation
 * ----------
 * What it is:   `HELP` (one `ScreenHelp` per route pattern) and `helpFor(pathname)`.
 * What it does: Holds the "About this screen" copy for every route in ui/src/App.tsx, in
 *               GOV.UK tone: a purpose, a next step per role (viewer is the fallback), what
 *               the numbers mean (n, interval, apparatus), the glossary ids on the screen and
 *               the guide sections to read. The About block in ui/src/components/Help.tsx
 *               reads it from the current route, so a screen needs no wiring. The help
 *               routes themselves have no entry.
 * How:          `helpFor` runs react-router's `matchPath` over `HELP` in declaration order and
 *               returns the first hit; patterns are the route table's own strings.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Help.tsx (`AboutThisScreen` renders an entry),
 *               ui/src/App.tsx (the route table every entry must cover — the test reads it),
 *               ui/src/help/glossary.ts (`terms[]` ids), ui/src/help/docs.ts (`readMore` anchors),
 *               ui/src/components/Layout.tsx (mounts the About block once)
 * Tested by:    ui/src/help/help.test.ts (the ratchet: every route, every anchor, every term,
 *               copy lint), ui/src/components/Help.test.tsx (rendered per route and role)
 * Touch when:   a screen is added (it needs an entry before the ratchet passes) or a
 *               screen's numbers change meaning (an apparatus or policy change with its ADR).
 */
import { matchPath } from 'react-router'
import type { Role } from '../api/types'
import type { DocAnchor } from './docs'
import type { TermId } from './glossary'

export interface ScreenHelp {
  /** A react-router pattern, matched with `matchPath` in declaration order. */
  route: string
  /** One or two sentences: what this screen is for. */
  purpose: string
  /** What to do next, by role; `viewer` is the fallback and always exists. */
  next: Partial<Record<Role, string>> & { viewer: string }
  /** What the numbers mean — n, interval, apparatus. Omitted only on a screen with no number. */
  numbers?: string
  /** Glossary ids surfaced under "Terms on this screen". */
  terms?: TermId[]
  /** Read more — bundled guide anchors, rendered as links to /help/docs/<name>#<slug>. */
  readMore: Array<{ to: DocAnchor; label: string }>
}

export const HELP: ScreenHelp[] = [
  {
    route: '/home',
    purpose: 'This is where the deployment is on the way from an empty install to a change delivered under evidence. The task list is the operators’ progress; every role can read it.',
    next: {
      viewer: 'Follow Continue to the baseline for the most recent repository, or open Decisions to see what is waiting on a person. You cannot start a task from here.',
      operator: 'Work the tasks in order. Tasks 1 to 4 cost nothing; tasks 5 and 8 spend model budget and say so before they start.',
      approver: 'Nothing here needs you until task 7 is done and a cell reaches your Decisions. Read the baseline meanwhile.',
      admin: 'Task 1 (the GitHub App) and task 7 (an approver account) are yours; both are in Settings.',
    },
    numbers: '“n of 8 tasks” counts tasks marked Completed. It is progress, not a quality figure; the quality figures live on the Baseline with their n and interval.',
    terms: ['cell', 'apparatus', 'signoff', 'oracle_strength'],
    readMore: [
      { to: 'ONBOARDING-A-REPO', label: 'Using Commit Replay Bench on a repository, step by step' },
      { to: 'GITHUB-APP#1-why-an-app-not-a-token', label: 'Why the GitHub App, not a token' },
    ],
  },
  {
    route: '/connect',
    purpose: 'Connect a repository so the instrument can learn how its code tests itself. Nothing is written to the repository at this stage and no model is called.',
    next: {
      viewer: 'Open a repository to see where it is on the walk. Only an operator can connect one.',
      operator: 'Connect from GitHub if the App is installed, otherwise connect by URL, then open the repository and run the six stages in order.',
      admin: 'If Connect from GitHub is greyed out, register the App once in Settings; organisations then install it on the repositories it may see.',
    },
    numbers: 'Tasks is the number of commits mined into replayable tasks; gold-clean is how many of them pass their own test at the recorded commit inside the sandbox. A repository with 0 gold-clean tasks cannot be measured.',
    terms: ['gold_clean', 'sighted', 'oracle_strength', 'negative_controls'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-1--register-the-repository-developer-30-minutes', label: 'Register a repository' },
      { to: 'GITHUB-APP#4-connect-a-repository', label: 'Connect through the GitHub App' },
      { to: 'OPERATOR#20-connecting-and-configuring-a-repository-from-the-ui', label: 'Configure a repository from the UI' },
    ],
  },
  {
    route: '/connect/:name/measure',
    purpose: 'Choose how many attempts to buy and what to keep, then start the first sighted measurement. This is the step that spends money, and it says how much before you confirm.',
    next: {
      viewer: 'Only an operator can start a measurement.',
      operator: 'Pick a number of attempts, decide whether to keep worktrees for failed attempts, then confirm. You can cancel the run from Runs while it is in flight and you pay only for attempts made.',
    },
    numbers: 'The estimate is a planning band, not a measurement: with no measured mean for this repository it uses the per-attempt range from earlier repositories and carries no apparatus. Once this repository has measured attempts the estimate uses their mean (n shown) with ±20 % around it.',
    terms: ['sighted', 'apparatus', 'evidence_pack', 'cell'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-4--measure-operator-the-money-step', label: 'Measure: the money step' },
      { to: 'DATA-RETENTION#2-retention-defaults-zero-raw-retention', label: 'What is kept, and for how long' },
    ],
  },
  {
    route: '/connect/:name',
    purpose: 'The six stages that take one repository from registered to measured. Each stage says what it proves and whether it spends money; the first five involve no model.',
    next: {
      viewer: 'Read each stage’s status and detail line. The Baseline button opens the baseline once any stage has produced rows; a stage that reads Done, with a finding names what deliver is waiting on.',
      operator: 'Press Run on the next stage that reads Not started. A Failed stage says so; open run gives the log and the error, fix the cause, then Retry. Measure… is the only stage that spends.',
    },
    numbers: 'Stage detail lines carry counts (tasks mined, controls constructed, mutants killed). They are counts, not rates: the rates, with n and a Wilson interval, appear on the Baseline.',
    terms: ['negative_controls', 'oracle_strength', 'sighted', 'wilson', 'apparatus', 'belt', 'cell'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-3--prove-the-instrument-on-this-repository-operator-0', label: 'Prove the instrument for £0' },
      { to: 'OPERATOR#7-when-the-sandbox-is-unavailable', label: 'When the sandbox is unavailable' },
    ],
  },
  {
    route: '/results',
    purpose: 'What the evidence says about one repository, in the order it matters: is the instrument trustworthy here, what may the builder be trusted to do, and what is waiting on a person. This is the baseline the factory runs on.',
    next: {
      viewer: 'Read the three gates first. If any is amber the numbers below are provisional. Then read the route tiles and the map; open a cell for its full evidence.',
      operator: 'If a gate is amber, go back to the walk and run what is missing. If a cell reads calibrate, more attempts move it; if it reads human, more attempts will not.',
      approver: 'A cell that routes deliver and is not yet signed appears under Waiting on a person; Attest takes you to the sign-off form.',
    },
    numbers: 'Every rate carries n (attempts), a 95 % Wilson interval and the apparatus version that produced it. The interval is the claim, not the point. Economics tiles are means only: the API does not yet serve an interval for cost or latency.',
    terms: ['cell', 'wilson', 'apparatus', 'false_q1', 'oracle_strength', 'negative_controls', 'deliver', 'calibrate', 'human', 'granularize', 'belt'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-5--read-the-map-everyone', label: 'Read the map' },
      { to: 'EVIDENCE-AND-CLAIMS#3-every-number-carries-its-method', label: 'Every number carries its method' },
      { to: 'EVIDENCE-AND-CLAIMS#7-what-must-never-be-said', label: 'What must never be said' },
    ],
  },
  {
    route: '/decisions',
    purpose: 'Everything that is waiting on a person, across every repository. A cell the policy would refuse anyway is never listed; it stays on the map with its reason.',
    next: {
      viewer: 'Read why each row is here; the evidence line names the cell, n, interval and reason code.',
      operator: 'Rows marked “approver acts” are not yours — a Sign a gap row needs an approver. Decide and Review rows on factory items are yours; Read opens the rest.',
      approver: 'Attest opens the sign-off form with the cell chosen; Sign a gap opens the item on the Factory. Decline by doing nothing: an unsigned cell keeps its route.',
    },
    numbers: 'n on a row is the attempts in that cell; the bracket is its 95 % Wilson interval; the code after it is the routing reason. A stale row was signed under an earlier apparatus and licenses nothing until re-signed.',
    terms: ['cell', 'wilson', 'reason_code', 'signoff', 'stale', 'apparatus', 'false_q1'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-6--before-anyone-signs-anything', label: 'Before anyone signs anything' },
      { to: 'EVIDENCE-AND-CLAIMS#4-the-apparatus-stamp--evidence-expires', label: 'Why a sign-off expires' },
    ],
  },
  {
    route: '/signoff',
    purpose: 'Record that a named approver reviewed a cell’s evidence and read one accepted change. The server refuses a sign-off that does not meet the published policy; a refusal is the gate working, not an error.',
    next: {
      viewer: 'Only an approver can sign. The attestations table shows every sign-off and revocation for this repository.',
      approver: 'Choose the cell, choose the accepted row you read, read the diff shown, tick the affirmation, write what you read and why it is acceptable, then Sign off. The green panel gives you a reference.',
    },
    numbers: 'Each gate row shows the observed value against the policy threshold (n, point, Wilson lower bound, oracle strength, controls constructed and escaped). The policy version and apparatus are stamped on the record and served back verbatim.',
    terms: ['signoff', 'cell', 'wilson', 'false_q1', 'oracle_strength', 'negative_controls', 'deliver', 'controls_escape', 'apparatus', 'belt'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-7--sign-off-approver', label: 'Sign off' },
      { to: 'EVIDENCE-AND-CLAIMS#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2', label: 'What a signed cell may be claimed to mean' },
      { to: 'OPERATOR#5-sign-off', label: 'Sign-off in the operator guide' },
    ],
  },
  {
    route: '/factory',
    purpose: 'Deliver new work under the same rules as replay: a frozen backlog, a failing test proved before any build, a build inside the sandbox, and a branch and pull request only where the map routes deliver. Every step is on the evidence chain.',
    next: {
      viewer: 'Read each item’s chain: readiness, RED proof, build, delivery, review, outcome. A PR link opens the pull request in the repository.',
      operator: 'Freeze a backlog, then Run the factory. The count beside the checkbox says how many items sit in a deliver cell today; the rest are built and withheld.',
      approver: 'Items blocked on a structural gap wait for your signature. Overriding the route gate is recorded on the chain under your name.',
    },
    numbers: '“k of m items sit in a cell that routes deliver” is read from the map at this moment; it changes as measurement changes. Build and review statuses are the server’s words, shown verbatim.',
    terms: ['red_proof', 'route_gate', 'cell', 'deliver', 'evidence_pack', 'apparatus', 'belt', 'wilson'],
    readMore: [
      { to: 'ONBOARDING-A-REPO#step-8--forward-mode-when-a-cell-is-trusted', label: 'Forward mode' },
      { to: 'GITHUB-APP#5-what-happens-at-clone-and-at-delivery', label: 'What happens at delivery' },
    ],
  },
  {
    route: '/posture',
    purpose: 'A printable statement of how this deployment is built, secured and audited, for an architecture or security review. Each row is read from the running system or names its source.',
    next: {
      viewer: 'Print it, or send the URL. “Shown to admins” marks a value the API only returns to an admin.',
      admin: 'If Sign-in reads Local accounts only, configure OpenID Connect; if Test executor is not docker, nothing measured is evidence.',
    },
    numbers: 'Ledger rows, chain state and false-Q1 total come from the live verification; the belt set and policy names are the versions in force.',
    terms: ['apparatus', 'belt', 'false_q1', 'cell'],
    readMore: [
      { to: 'SECURITY#2-trust-boundaries', label: 'Trust boundaries' },
      { to: 'DATA-RETENTION#2-retention-defaults-zero-raw-retention', label: 'Retention defaults' },
      { to: 'DEPLOYMENT', label: 'Deploying Commit Replay Bench' },
    ],
  },
  {
    route: '/runs/:id',
    purpose: 'One run: its progress, live log, per-task rows and their evidence packs. Cancel stops after the attempt in flight; nothing already graded is lost.',
    next: {
      viewer: 'Read the rows and open a pack; the pack hash is the row’s permanent reference.',
      operator: 'Watch the log; open a row’s pack to see every belt and the diff; cancel if the spend is wrong.',
    },
    numbers: 'A row is clean only when every evaluated belt holds; the “why not clean” split is red, budget, protocol and harness. Instrument rows (protocol, harness) count against the builder until the instrument is fixed.',
    terms: ['belt', 'clean', 'evidence_pack', 'false_q1', 'wilson', 'apparatus', 'oracle_strength', 'cell'],
    readMore: [
      { to: 'EVIDENCE-AND-CLAIMS#2-clean-semantic-q1-and-false-q1', label: 'Clean and false-Q1' },
      { to: 'DATA-RETENTION#2-retention-defaults-zero-raw-retention', label: 'What an evidence pack keeps' },
    ],
  },
  {
    route: '/runs',
    purpose: 'Every run the worker has executed or queued: mine, replay, blind, oracle, controls and factory. A run’s rows are what the ledger and the map are made of.',
    next: {
      viewer: 'Open a run to read its progress and the evidence pack of any row.',
      operator: 'Press Start a run, or open one to watch its live log and cancel it. The kind’s hint says what it produces and whether it spends.',
    },
    numbers: 'Progress counts are tasks attempted of tasks planned. Cost is builder-reported and summed; it is not an estimate.',
    terms: ['sighted', 'blind', 'negative_controls', 'oracle_strength', 'evidence_pack', 'apparatus'],
    readMore: [
      { to: 'OPERATOR#3-run-a-sweep', label: 'Run a sweep' },
      { to: 'OPERATOR#8-stop-conditions', label: 'Stop conditions' },
    ],
  },
  {
    route: '/capability',
    purpose: 'The full map for one repository: one cell per class and size (and, projected, language or model) with its rate, interval, false-Q1 count, cost, latency, oracle strength and the route the evidence licenses.',
    next: {
      viewer: 'Read a cell’s route and interval; an empty cell says not measured, never zero.',
      operator: 'Open a cell for every number with its method and links to its rows and its route decision. Export CSV gives the rows behind the map.',
    },
    numbers: 'point = clean / n; the bracket is the 95 % Wilson interval; fQ1 is the false-Q1 count and must be 0; “or” is the mean oracle strength; the glyph is the verification tier. Cells with more than one apparatus version are flagged mixed, never averaged.',
    terms: ['cell', 'wilson', 'false_q1', 'oracle_strength', 'apparatus', 'deliver', 'calibrate', 'human', 'granularize', 'reason_code', 'belt'],
    readMore: [
      { to: 'OPERATOR#4-read-the-capability-map', label: 'Read the capability map' },
      { to: 'EVIDENCE-AND-CLAIMS#6-permitted-claim-shapes-by-maturity', label: 'What a cell’s route licenses' },
    ],
  },
  {
    route: '/routing',
    purpose: 'Every route decision for one repository with its reason and the policy version that produced it. The rule is published and the same for every cell; a deployment may tighten it, never loosen it under the same name.',
    next: {
      viewer: 'Read the reason code beside each cell; the policy card shows the thresholds in force.',
      operator: 'A calibrate reason names what is missing (n, point, lower bound, controls). A human reason will not change with more attempts: strengthen the tests or run the controls.',
    },
    numbers: 'Route counts are cells, not attempts. Thresholds are the policy’s: n ≥ 10, point ≥ 0.90, Wilson lower ≥ 0.80, oracle ≥ 0.80, controls passed with 0 escapes and a majority constructed.',
    terms: ['cell', 'route_gate', 'reason_code', 'deliver', 'calibrate', 'human', 'granularize', 'wilson', 'oracle_strength', 'controls_escape', 'belt'],
    readMore: [
      { to: 'EVIDENCE-AND-CLAIMS#6-permitted-claim-shapes-by-maturity', label: 'What a route licenses' },
      { to: 'ONBOARDING-A-REPO#step-3--prove-the-instrument-on-this-repository-operator-0', label: 'The controls gate' },
    ],
  },
  {
    route: '/oracle',
    purpose: 'How much a green is worth for this repository: the negative controls the grader must catch, and the mutation strength of the tests on the changed lines. A weak oracle sends a cell to a human whatever its pass rate.',
    next: {
      viewer: 'The gate rows name what held and what did not; escapes are findings about the tests, not failures of the grader.',
      operator: 'If the controls gate is not open, run the controls. If a task is weak, the strengthen report on Learn turns it into test work.',
    },
    numbers: 'Strength = mutants killed / mutants planted on the changed lines, per task, with a 95 % Wilson interval; unscoreable tasks are counted and never averaged. Bands: strong ≥ 0.80, adequate, weak.',
    terms: ['oracle_strength', 'negative_controls', 'controls_escape', 'wilson', 'human', 'cell', 'apparatus'],
    readMore: [
      { to: 'OPERATOR#31-oracle-adequacy--mutation-scoring', label: 'Oracle adequacy: mutation scoring' },
      { to: 'ONBOARDING-A-REPO#step-2--make-the-oracle-reproducible-developer-the-real-work', label: 'Make the oracle reproducible' },
    ],
  },
  {
    route: '/learn',
    purpose: 'What the ledger teaches, as three reports: refusals that should become guard tests, weak oracles that should become test work, and evidence that has gone stale since the apparatus changed. Nothing here acts; a person does.',
    next: {
      viewer: 'Read the reports; every row carries the rows and spend behind it.',
      operator: 'Copy a candidate corpus line into a decision file, freeze a strengthening item on the Factory, or queue the re-measurement runs the plan lists.',
    },
    numbers: 'Refusal share is protocol rows / all rows with a 95 % Wilson interval, per apparatus version. Re-measurement spend multiplies each cell’s own mean row cost by the rows still needed; a dash means no cost is known.',
    terms: ['apparatus', 'stale', 'oracle_strength', 'wilson', 'cell'],
    readMore: [
      { to: 'LEARNING-LOOP', label: 'The learning loop' },
      { to: 'LEARNING-LOOP#3-what-still-needs-a-human-and-why-that-is-deliberate', label: 'What still needs a human' },
    ],
  },
  {
    route: '/ledger',
    purpose: 'Every graded trial, append-only and hash-chained. Verify proves nothing was edited, reordered or removed; the false-Q1 total is the number everything else defends.',
    next: {
      viewer: 'Filter by repository, mode or clean; open a task or a pack. Export gives the rows as JSONL or CSV; the abstract export contains cells only, no code and no identifiers.',
      operator: 'A broken chain or a false-Q1 above 0 halts delivery; investigate the named row before anything else.',
    },
    numbers: 'Rows is the whole ledger across repositories; Matching rows is the current filter. false-Q1 is enforced when a row is written and re-derived when it is read.',
    terms: ['false_q1', 'clean', 'belt', 'evidence_pack', 'sighted', 'blind', 'cell', 'apparatus', 'oracle_strength'],
    readMore: [
      { to: 'EVIDENCE-AND-CLAIMS#6c-the-evidence-ladder--the-chain-proves-integrity-not-truth', label: 'What the chain proves' },
      { to: 'OPERATOR#6-export-and-verify-the-ledger', label: 'Export and verify' },
      { to: 'DATA-RETENTION#5-cross-organisation-sharing', label: 'What the abstract export shares' },
    ],
  },
  {
    route: '/repos/:name',
    purpose: 'The repository as an instrument: its toolchain probe, mined tasks, change profile and the configuration that governs how its commits are replayed.',
    next: {
      viewer: 'Read the probe result and the task list; a task opens its spec and every graded trial against it.',
      operator: 'Edit the configuration when the walk’s probe or mine stage fails; the runner, test prefixes and services are what the belts depend on.',
    },
    numbers: 'The change profile counts commits by class and size; it weights the coverage figure on the map. Gold-clean is tasks whose own test passes at the recorded commit.',
    terms: ['gold_clean', 'belt', 'cell', 'oracle_strength', 'wilson', 'apparatus'],
    readMore: [
      { to: 'OPERATOR#2-configure-a-repository', label: 'Configure a repository' },
      { to: 'OPERATOR#22-services-the-oracle-needs', label: 'Services the oracle needs' },
    ],
  },
  {
    route: '/repos',
    purpose: 'Every repository this deployment knows, with its probe status and task counts. The journey’s Connection page is the same list with the walk beside it.',
    next: {
      viewer: 'Open a repository to read its probe result, tasks and configuration.',
      operator: 'Add a repository here or from Connection; open one to edit the configuration the belts depend on.',
    },
    numbers: 'Task counts are commits mined into tasks; gold-clean is how many pass their own test at the recorded commit.',
    terms: ['gold_clean', 'belt'],
    readMore: [
      { to: 'OPERATOR#2-configure-a-repository', label: 'Configure a repository' },
      { to: 'ONBOARDING-A-REPO#step-1--register-the-repository-developer-30-minutes', label: 'Register a repository' },
    ],
  },
  {
    route: '/tasks/:repo/:taskId',
    purpose: 'One replayable commit: its specification (the failing test, the source files, the belt scope) and every graded trial against it.',
    next: {
      viewer: 'Open a trial’s pack to see the diff and each belt’s result.',
    },
    numbers: 'Trials are single attempts; the cell’s rate is on the map, not here.',
    terms: ['belt', 'evidence_pack', 'clean', 'gold_clean', 'cell', 'apparatus'],
    readMore: [{ to: 'EVIDENCE-AND-CLAIMS#2-clean-semantic-q1-and-false-q1', label: 'The belts and clean' }],
  },
  {
    route: '/settings',
    purpose: 'The instrument’s health, the builder sign-in, the GitHub App and, for admins, the non-secret configuration and user accounts. Secrets are never returned by the API and never shown here.',
    next: {
      viewer: 'Read the health probes; ask an admin for anything else.',
      admin: 'Register the GitHub App, store the builder token, create an approver account. A probe that is not ok explains itself in its detail line.',
    },
    numbers: 'The version line is what every claim cites: crb (the package), apparatus (the instrument) and policy (the routing rule).',
    terms: ['apparatus', 'negative_controls'],
    readMore: [
      { to: 'GITHUB-APP#2-register-the-app-once-per-deployment', label: 'Register the GitHub App' },
      { to: 'SECURITY#33-credentials', label: 'How credentials are held' },
      { to: 'OPERATOR#7-when-the-sandbox-is-unavailable', label: 'When the sandbox is unavailable' },
    ],
  },
]

/** The first entry whose pattern matches `pathname`, or `undefined` (the help pages, the 404). */
export function helpFor(pathname: string): ScreenHelp | undefined {
  return HELP.find((h) => matchPath({ path: h.route, end: true }, pathname) !== null)
}
