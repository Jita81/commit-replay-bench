/**
 * A populated prevention register — the one fixture the Learn page's tests and the hint ratchet
 * render, so both see the same elements (ADR-0020).
 *
 * Navigation
 * ----------
 * What it is:   `REGISTER`: a `GET /learn/register` body for repository `alpha` with the
 *               switch thrown, one class applied (a playbook line with its measurement, a
 *               filed item and a product item), one class escalated and one open under watch.
 * What it does: Gives every column, tile, pill, field and button of the register card a state
 *               to render, so the ratchet sees every hinted element and the page tests can read
 *               n, the bar, the status and the qualifiers.
 * How:          A plain object typed as `PreventionRegister` (ui/src/api/types.ts), numbers from
 *               the ladder scenario of tests/test_prevention_rule.py.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
 * Works with:   ui/src/screens/Learn/LearnPage.test.tsx (the page tests),
 *               ui/src/help/hints-ratchet.instrument.tsx (the ratchet's /learn fixture),
 *               ui/src/api/types.ts (the shape), src/crb/core/prevention.py (the served shape)
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   the register's served shape changes (keep this a populated, valid body).
 */
import type { PreventionEntry, PreventionRegister } from '../../api/types'

const KEY = '2.2|claude_code|claude-sonnet-5|crb.prevention.sig.v1'

const APPLIED: PreventionEntry = {
  repo: 'alpha',
  signature: 'protocol:network:go mod',
  family: 'protocol',
  sub: 'network',
  detail: 'go mod',
  first_seen: '2026-10-01T00:00:00+00:00',
  first_ref: 'a'.repeat(64),
  last_seen: '2026-10-01T02:00:00+00:00',
  occurrences: 12,
  first_attempts: 12,
  blocked: 0,
  tasks: 8,
  runs: 3,
  cost_usd: 1.2,
  refs: ['a'.repeat(64), 'b'.repeat(64)],
  refs_total: 12,
  by_mode: { blind: 12 },
  by_apparatus: { '2.2': 12 },
  not_comparable: 0,
  stratum: { mode: 'blind', key: KEY, n: 41, k: 12, tasks: 8 },
  actionable: true,
  why_not: '',
  capability: false,
  recommendation: {
    lever_id: 'line:T-NET',
    level: 'advisory',
    family: 'context',
    why: 'the strongest admissible lever (advisory)',
    allowed: true,
    passed_over: [
      { lever_id: 'item:refused-call', level: 'construction', why_not: 'a filed item: code a person builds' },
      { lever_id: 'finish_gate', level: 'mistake-proofing', why_not: 'this build does not ship it yet' },
    ],
    propose: [],
  },
  change: {
    change_id: 'c0ffee0c0ffee0c0',
    lever_id: 'line:T-NET',
    family: 'context',
    level: 'advisory',
    targets: ['protocol:network:go mod'],
    stratum_mode: 'blind',
    key: KEY,
    what: { line_id: 'a379a201505e', template_id: 'T-NET', text: 'No network: `go mod` is refused and ends the attempt. Dependencies are installed; check your work with the test command above.' },
    applied_at: '2026-10-01T01:40:00+00:00',
    applied_by: 'loop',
    on_behalf_of: 'op-1',
    before: { 'protocol:network:go mod': { k0: 9, n0: 30, decisive_n: 11 } },
    state: 'in_force',
    record_hash: 'd'.repeat(64),
  },
  proposals: [
    {
      item_id: 'prevent-e2e3c3b7b3e8',
      targets: ['protocol:network:go mod'],
      lever_id: 'item:offline-deps',
      level: 'construction',
      scope: 'infra',
      kind: 'infra',
      title: 'Provision the sandbox so dependency commands resolve without the network',
      description: 'protocol:network:go mod recurred on 9 first attempt(s) over 6 task(s) in alpha ($0.90).',
      expected_effect: 'the installer answers offline, so the refusal has nothing to refuse',
      evidence_refs: ['a'.repeat(64)],
      evidence_total: 9,
      proposed_at: '2026-10-01T01:40:00+00:00',
      record_hash: 'e'.repeat(64),
      registered: null,
    },
    {
      item_id: 'prevent-0a1b2c3d4e5f',
      targets: ['protocol:network:go mod'],
      lever_id: 'item:refused-call',
      level: 'construction',
      scope: 'product',
      kind: 'product',
      title: 'Record a command the builder’s own deny rule refused as a refused call, not a voided attempt',
      description: 'protocol:network:go mod recurred on 9 first attempt(s) over 6 task(s) in alpha ($0.90).',
      expected_effect: 'one refused command no longer voids everything the builder did',
      evidence_refs: ['a'.repeat(64)],
      evidence_total: 9,
      proposed_at: '2026-10-01T01:40:00+00:00',
      record_hash: 'f'.repeat(64),
      registered: null,
    },
  ],
  measurement: {
    signature: 'protocol:network:go mod',
    stratum_mode: 'blind',
    key: KEY,
    before: { k: 9, n: 30, p0: 0.3, digest: '1219175bb56176e4', clean_rate: 0.5667 },
    exposed: { k: 3, n: 11, clean_k: 8, clean_ci_low: 0.43, clean_ci_high: 0.9 },
    unexposed_n: 0,
    concurrent: { k: 0, n: 0 },
    not_comparable: 0,
    decisive_n: 11,
    looks: [11, 22],
    closing_window: 20,
    closing_zero_run: 2,
    bar: 'keep if P(X ≤ k | n = 11, p0 = 0.300) ≤ 0.025 — at most 0 recurrence(s) in the first 11; a second look at 22',
    deterministic: false,
  },
  status: 'applied',
  qualifiers: [],
  lever_kind: 'context',
  next: 'Needs 11 more exposed first attempt(s) before look 2.',
  history: [
    { kind: 'proposed', record_id: 'r1', row_hash: 'e'.repeat(64), created: '2026-10-01T01:40:00+00:00', actor: 'loop', on_behalf_of: 'op-1', summary: 'item:offline-deps' },
    { kind: 'applied', record_id: 'r2', row_hash: 'd'.repeat(64), created: '2026-10-01T01:40:00+00:00', actor: 'loop', on_behalf_of: 'op-1', summary: 'line:T-NET' },
  ],
}

const WATCH: PreventionEntry = {
  ...APPLIED,
  signature: 'budget:max_turns',
  family: 'budget',
  sub: 'max_turns',
  detail: '',
  occurrences: 1,
  first_attempts: 1,
  tasks: 1,
  cost_usd: 0.4,
  refs: ['c'.repeat(64)],
  refs_total: 1,
  stratum: { mode: 'blind', key: KEY, n: 41, k: 1, tasks: 1 },
  actionable: false,
  why_not: '1 of 2 occurrences on 1 of 2 tasks in 41 of 10 comparable blind first attempts',
  recommendation: { lever_id: '', level: '', family: '', why: 'only a filed item admits this class', allowed: false, passed_over: [], propose: [] },
  change: null,
  proposals: [],
  measurement: null,
  status: 'open',
  qualifiers: ['watch'],
  lever_kind: '',
  next: 'Watching: 1 of 2 occurrences on 1 of 2 tasks in 41 of 10 comparable blind first attempts.',
  history: [],
}

const ESCALATED: PreventionEntry = {
  ...WATCH,
  signature: 'harness:runner-tool-missing:jest',
  family: 'harness',
  sub: 'runner-tool-missing',
  detail: 'jest',
  occurrences: 3,
  first_attempts: 3,
  blocked: 3,
  tasks: 3,
  cost_usd: 0,
  stratum: { mode: 'blind', key: KEY, n: 41, k: 3, tasks: 3 },
  actionable: true,
  why_not: '',
  status: 'escalated',
  qualifiers: ['contained'],
  proposals: [{ ...APPLIED.proposals[0]!, item_id: 'prevent-111122223333', lever_id: 'item:env-provision', title: 'Provision the missing tool in the repository’s sandbox image', targets: ['harness:runner-tool-missing:jest'] }],
  next: 'Waiting on a person: register the filed item "Provision the missing tool in the repository’s sandbox image", or link a fix.',
}

export const REGISTER: PreventionRegister = {
  schema: 'crb.prevention.register.v1',
  repo: 'alpha',
  rules: { signature: 'crb.prevention.sig.v1', decision: 'crb.prevention.rule.v1', apparatus: '2.2' },
  apparatus: '2.2',
  switch: { auto_apply: 'context', switched_by: 'op-1', switched_at: '2026-10-01T00:40:00+00:00', reason: 'try the lines on alpha', record_id: 'sw1' },
  attempts: { first_attempts: 41, blind: 41, sighted: 0, rows: 41, outage: 0 },
  counts: { open: 1, applied: 1, closed: 0, retired: 0, escalated: 1 },
  share_closed: 0,
  share_closed_by_process: null,
  overlay: {},
  playbook: {
    lines: [{ line_id: 'a379a201505e', template_id: 'T-NET', signature: 'protocol:network:go mod', text: 'No network: `go mod` is refused and ends the attempt. Dependencies are installed; check your work with the test command above.' }],
    chars: 125,
    max_lines: 7,
    max_chars: 1000,
    sha256: '9f86d081884c7d65',
  },
  entries: [APPLIED, ESCALATED, WATCH],
  proposals: [...APPLIED.proposals, ...ESCALATED.proposals],
  links: [],
  chain: { records: 6, head: 'd'.repeat(64), verified: true },
  decisions_verified: [],
}
