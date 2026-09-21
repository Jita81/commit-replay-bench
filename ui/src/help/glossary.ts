/**
 * The glossary — the 22 terms every screen uses, defined once in plain English.
 *
 * Navigation
 * ----------
 * What it is:   `TERMS`, the registry of term id → term, a short definition and a guide anchor.
 * What it does: Gives every screen one place to define the product's own vocabulary (cell,
 *               apparatus, belt, the four routes, false-Q1, the oracle and its controls, the
 *               factory's RED proof and route gate, sign-off and staleness). A term that is a
 *               number names its n, interval and apparatus in its definition. The
 *               definitions are the product's published rule (docs/EVIDENCE-AND-CLAIMS.md,
 *               docs/adr/0003-one-routing-rule.md), so a screen never re-explains them.
 * How:          A typed `Record<TermId, Term>`; `TERM_IDS` fixes the order the glossary page
 *               lists them in. `<Term id>` and the About block read it; `/help` renders it.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md (the routes), docs/adr/0001-four-belts-and-false-q1-at-write.md
 *               (belts and false-Q1), docs/adr/0010-polyglot-negative-controls.md (controls),
 *               docs/adr/0015-signoffs-expire-with-the-apparatus.md (stale)
 * Works with:   ui/src/components/Help.tsx (`Term` and the About block render these),
 *               ui/src/help/help.ts (each screen names the terms it shows),
 *               ui/src/screens/Help/HelpPage.tsx (the glossary page),
 *               ui/src/help/docs.ts (`DocAnchor` for `readMore`),
 *               docs/EVIDENCE-AND-CLAIMS.md (the source of the definitions)
 * Tested by:    ui/src/help/glossary.test.ts, ui/src/help/help.test.ts (every anchor resolves)
 * Touch when:   a term is added to a screen — add it here first; a threshold in the routing
 *               rule changes (update `deliver` and `oracle_strength` with the ADR).
 */
import type { DocAnchor } from './docs'

export type TermId =
  | 'cell'
  | 'apparatus'
  | 'belt'
  | 'clean'
  | 'gold_clean'
  | 'wilson'
  | 'sighted'
  | 'blind'
  | 'deliver'
  | 'calibrate'
  | 'human'
  | 'granularize'
  | 'false_q1'
  | 'oracle_strength'
  | 'negative_controls'
  | 'controls_escape'
  | 'red_proof'
  | 'route_gate'
  | 'reason_code'
  | 'signoff'
  | 'stale'
  | 'evidence_pack'

export interface Term {
  /** The term as the screens print it. */
  term: string
  /** One or two plain-English sentences; a number names its n, interval and apparatus. */
  short: string
  /** The guide section that says more. */
  readMore?: DocAnchor
}

/** The glossary order: the unit and the instrument first, then the routes, then the gates. */
export const TERM_IDS: readonly TermId[] = [
  'cell', 'apparatus', 'belt', 'clean', 'gold_clean', 'wilson', 'sighted', 'blind', 'deliver', 'calibrate', 'human',
  'granularize', 'false_q1', 'oracle_strength', 'negative_controls', 'controls_escape', 'red_proof', 'route_gate',
  'reason_code', 'signoff', 'stale', 'evidence_pack',
]

export const TERMS: Record<TermId, Term> = {
  cell: {
    term: 'cell',
    short: 'One class of change at one size (for example bugfix × S), measured on one repository; the unit every rate, route and sign-off attaches to. Its n is the attempts in it, never a share of the repository.',
    readMore: 'EVIDENCE-AND-CLAIMS#3-every-number-carries-its-method',
  },
  apparatus: {
    term: 'apparatus',
    short: 'The version of the instrument that produced a row: grader, belt set, size table and routing rule together (apparatus 2.2 today). Evidence from one apparatus is never blended with another, and a sign-off made under an earlier one is stale.',
    readMore: 'EVIDENCE-AND-CLAIMS#4-the-apparatus-stamp--evidence-expires',
  },
  belt: {
    term: 'belt',
    short: 'One mechanical check on a trial: tests unmodified, the target test green, no new failures, source changed, and (belt 5) the repository’s own linter clean. A row is clean only when every evaluated belt holds.',
    readMore: 'EVIDENCE-AND-CLAIMS#2-clean-semantic-q1-and-false-q1',
  },
  clean: {
    term: 'clean',
    short: 'A trial whose evaluated belts all hold, that was not disqualified, and that has an evidence pack. Clean means the change satisfied the repository’s own tests, not that it is correct.',
    readMore: 'EVIDENCE-AND-CLAIMS#2-clean-semantic-q1-and-false-q1',
  },
  gold_clean: {
    term: 'gold-clean',
    short: 'A mined task whose own historical change passes its test inside the sandbox. A task that is not gold-clean is excluded from n.',
    readMore: 'ONBOARDING-A-REPO#step-2--make-the-oracle-reproducible-developer-the-real-work',
  },
  wilson: {
    term: 'Wilson interval',
    short: 'The 95 % range a measured rate could plausibly be, given n. Small n gives a wide interval; the interval is the claim, not the point.',
    readMore: 'EVIDENCE-AND-CLAIMS#3-every-number-carries-its-method',
  },
  sighted: {
    term: 'sighted',
    short: 'A replay where the builder sees the failing test it must make pass. A sighted rate is not a blind rate.',
    readMore: 'OPERATOR#3-run-a-sweep',
  },
  blind: {
    term: 'blind',
    short: 'A replay where the builder is given the commit’s description but not its test. It is the harder mode and is reported as its own cell.',
    readMore: 'OPERATOR#3-run-a-sweep',
  },
  deliver: {
    term: 'deliver',
    short: 'The route that lets the factory open a branch and pull request for this class of change: n ≥ 10, point ≥ 0.90, Wilson lower ≥ 0.80, false-Q1 = 0, oracle ≥ 0.80 and the controls gate passed. It never means a change is safe to merge.',
    readMore: 'EVIDENCE-AND-CLAIMS#7-what-must-never-be-said',
  },
  calibrate: {
    term: 'calibrate',
    short: 'Not enough evidence yet, or the rate is under the bar. More attempts, or running the controls, can change it.',
    readMore: 'OPERATOR#4-read-the-capability-map',
  },
  human: {
    term: 'human',
    short: 'A green cannot be trusted here whatever the rate: the tests are too weak to notice a wrong patch, the controls gate failed, or a deliberate cheat graded clean. More attempts will not change it; stronger tests will.',
    readMore: 'OPERATOR#31-oracle-adequacy--mutation-scoring',
  },
  granularize: {
    term: 'granularize',
    short: 'Extra-large changes are split into smaller ones before they are attempted.',
    readMore: 'OPERATOR#4-read-the-capability-map',
  },
  false_q1: {
    term: 'false-Q1',
    short: 'A row credited clean that its own recorded belts contradict. It is refused when written and re-counted when read; the total must be 0, and any other value halts delivery.',
    readMore: 'EVIDENCE-AND-CLAIMS#2-clean-semantic-q1-and-false-q1',
  },
  oracle_strength: {
    term: 'oracle strength',
    short: 'How often the repository’s tests on the changed lines catch a planted fault: mutants killed / mutants planted, per task, with its n and interval. Below 0.80 a cell routes to a human.',
    readMore: 'OPERATOR#31-oracle-adequacy--mutation-scoring',
  },
  negative_controls: {
    term: 'negative controls',
    short: 'Seven deliberate cheats (no change, a stub, a tampered test, a regression, a hard-coded answer, a poisoned environment, plus the real change as the positive control) the grader must catch before any pass rate means anything. The report reads passed when no cheat produced a violation; an escape (a cheat graded clean) or a thin set (fewer than half constructible) is counted separately and on its own withholds deliver.',
    readMore: 'ONBOARDING-A-REPO#step-3--prove-the-instrument-on-this-repository-operator-0',
  },
  controls_escape: {
    term: 'controls escape',
    short: 'A deliberate cheat that graded clean. It is a finding about the tests, recorded and counted; one escape withholds deliver until the tests are hardened and the controls re-run.',
    readMore: 'ONBOARDING-A-REPO#step-3--prove-the-instrument-on-this-repository-operator-0',
  },
  red_proof: {
    term: 'RED proof',
    short: 'Before the factory builds an item it must show the new test failing on the current code. No RED, no build.',
    readMore: 'ONBOARDING-A-REPO#step-8--forward-mode-when-a-cell-is-trusted',
  },
  route_gate: {
    term: 'route gate',
    short: 'The check, before a build is paid for and again before a pull request is opened, that the item’s cell routes deliver. An approver may override it; the override is recorded on the chain under their name.',
    readMore: 'ONBOARDING-A-REPO#step-8--forward-mode-when-a-cell-is-trusted',
  },
  reason_code: {
    term: 'reason code',
    short: 'The short code beside a route (for example n_below_min) naming the first clause of the rule that decided it.',
    readMore: 'OPERATOR#4-read-the-capability-map',
  },
  signoff: {
    term: 'sign-off',
    short: 'A named approver’s record that they reviewed a cell’s evidence and read one accepted change. It lifts the cell’s verification tier; it never changes its route, point or interval, and it expires when the apparatus changes.',
    readMore: 'EVIDENCE-AND-CLAIMS#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2',
  },
  stale: {
    term: 'stale',
    short: 'Evidence or a sign-off produced under an earlier apparatus. It is kept as history and licenses nothing until re-measured or re-signed.',
    readMore: 'EVIDENCE-AND-CLAIMS#4-the-apparatus-stamp--evidence-expires',
  },
  evidence_pack: {
    term: 'evidence pack',
    short: 'The hashed record of one trial: the spec, every belt’s result, the diff’s hash, the builder and the apparatus. Its hash is the row’s permanent reference.',
    readMore: 'DATA-RETENTION#2-retention-defaults-zero-raw-retention',
  },
}
