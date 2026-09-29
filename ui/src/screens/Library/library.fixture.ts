/**
 * Fixtures for the context library screen — one populated index and one work type's page.
 *
 * Navigation
 * ----------
 * What it is:   `LIBRARY` (a `GET /library/alpha` body: a signed convention, an unsigned
 *               proposal, a mined proposal nobody sponsored yet, a stale entry and a signed
 *               standard) and `WORK_TYPE` (a `GET /library/alpha/work-types/bug.fix` body with
 *               slots, signed context, a proven XS standard and the quality table).
 * What it does: Gives the screen test, the hint ratchet and the Decisions test one populated
 *               state to render, in the shapes docs/API.md#library names.
 * How:          Plain objects typed by ui/src/api/types.ts.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 10)
 * Works with:   ui/src/screens/Library/LibraryPage.test.tsx (renders it),
 *               ui/src/help/hints-ratchet.instrument.tsx (hints the route with it),
 *               ui/src/screens/Decisions/decisions.test.ts (the library's inbox rows)
 * Tested by:    ui/src/screens/Library/LibraryPage.test.tsx
 * Touch when:   never for a new repository; a field of `/library` changes (types.ts first).
 */
import type { LibraryEntry, LibraryIndex, LibraryRecord, WorkTypePage } from '../../api/types'

export const ADA = 'a'.repeat(32)
export const BEN = 'b'.repeat(32)

function record(over: Partial<LibraryRecord>): LibraryRecord {
  return {
    repo: 'alpha',
    kind: 'convention',
    slug: 'errors-wrap',
    title: 'Wrap errors with context',
    statement: 'Every returned error is wrapped with fmt.Errorf and %w, naming the operation.',
    provenance: { kind: 'person', path: '', commit: '', digest: '', rows: [], person: ADA },
    proposed_by: ADA,
    components: [],
    work_types: ['bug.fix'],
    characteristic: '',
    check: '',
    parent_class: '',
    examples: [],
    slots: [],
    ...over,
  }
}

function entry(over: Partial<LibraryEntry> & { entry: LibraryRecord }): LibraryEntry {
  return {
    entry_id: `${over.entry.kind}/${over.entry.slug}`,
    version: 'f'.repeat(64),
    status: 'proposed',
    proposed_at: '2026-09-27T10:00:00+00:00',
    sponsor: ADA,
    sponsor_name: 'Ada',
    sponsored_at: '2026-09-27T10:00:00+00:00',
    approver: '',
    approver_name: '',
    signed_at: '',
    stale: null,
    retired: null,
    revoked: null,
    effect: 'unmeasured',
    evidence: 'advisory',
    acts: 1,
    ...over,
  }
}

export const SIGNED = entry({ entry: record({}), status: 'signed', approver: BEN, approver_name: 'Ben', signed_at: '2026-09-27T11:00:00+00:00', acts: 2 })
export const PROPOSED = entry({ entry: record({ slug: 'context-first', title: 'Pass context first' }), version: 'e'.repeat(64) })
export const MINED = entry({
  entry: record({ kind: 'decision', slug: 'adr-0001', title: 'Use cobra for commands', provenance: { kind: 'file', path: 'docs/adr/0001.md', commit: '1'.repeat(40), digest: 'd'.repeat(64), rows: [], person: '' }, proposed_by: 'mined:adr@1' }),
  sponsor: '',
  sponsor_name: '',
  sponsored_at: '',
  evidence: '',
})
export const STALE = entry({
  entry: record({ slug: 'lint', title: 'Lint with golangci', provenance: { kind: 'file', path: '.golangci.yml', commit: '1'.repeat(40), digest: 'd'.repeat(64), rows: [], person: '' }, proposed_by: 'mined:lint@1', check: 'golangci-lint' }),
  status: 'stale',
  approver: BEN,
  approver_name: 'Ben',
  stale: { head_commit: '2'.repeat(40), path: '.golangci.yml', digest: 'e'.repeat(64), at: '2026-09-27T12:00:00+00:00' },
})
export const STANDARD = entry({
  entry: record({ kind: 'standard', slug: 'vet', title: 'Vet every package', characteristic: 'Maintainability', check: 'go-vet' }),
  status: 'signed',
  approver: BEN,
  approver_name: 'Ben',
  signed_at: '2026-09-27T11:00:00+00:00',
  evidence: 'check',
})

export const LIBRARY: LibraryIndex = {
  repo: 'alpha',
  entries: [MINED, SIGNED, PROPOSED, STALE, STANDARD],
  work_types: [
    { slug: 'bug.fix', title: 'bug.fix', parent_class: 'bug.fix', status: 'global', tasks: 12 },
    { slug: 'docs.update', title: 'docs.update', parent_class: 'docs.update', status: 'global', tasks: 2 },
  ],
  kinds: ['component', 'work-type', 'decision', 'convention', 'pattern', 'standard'],
  characteristics: ['Functional suitability', 'Performance efficiency', 'Compatibility', 'Interaction capability', 'Reliability', 'Security', 'Maintainability', 'Flexibility', 'Safety'],
  statement_max: 400,
  reaches_briefs: false,
}

function context(e: LibraryEntry) {
  return {
    entry_id: e.entry_id,
    kind: e.entry.kind,
    title: e.entry.title,
    statement: e.entry.statement,
    sponsor: e.sponsor,
    sponsor_name: e.sponsor_name,
    approver: e.approver,
    approver_name: e.approver_name,
    signed_at: e.signed_at,
    provenance: e.entry.provenance,
    provenance_label: 'written by a person',
    proposed_by: e.entry.proposed_by,
    effect: 'unmeasured',
    characteristic: e.entry.characteristic,
    check: e.entry.check,
    evidence: e.evidence,
  }
}

export const WORK_TYPE: WorkTypePage = {
  repo: 'alpha',
  slug: 'bug.fix',
  title: 'bug.fix',
  definition: 'Repairs a defect: the code did not do what it was documented or expected to do.',
  definition_source: 'global',
  parent_class: 'bug.fix',
  examples: [{ sha: 'c'.repeat(40), subject: 'fix: divide by zero', size: 'XS' }],
  ticket_slots: [
    { name: 'expected_behavior', question: 'What should happen instead?', kind: 'structural' },
    { name: 'example_values', question: 'A failing input and its expected output.', kind: 'value' },
  ],
  signed_slots: [],
  context: [context(SIGNED), context(STANDARD)],
  sizes: [
    { size: 'XS', tasks: 20, standard: { arm: 'S1@gpt-oss-120b', n: 20, clean: 20, ci_low: 0.839, ci_high: 1, apparatus: '2.4', state: 'deliver', ceiling: false, reading_id: 'r1' }, next: '' },
    { size: 'S', tasks: 6, standard: null, next: 'Register a reading of this cell (S3, then S1, under the look rule). A first look needs 20 distinct commits; 6 commits of this kind and size mined so far.' },
    { size: 'M', tasks: 0, standard: null, next: 'Register a reading of this cell (S3, then S1, under the look rule). A first look needs 20 distinct commits; 0 commits of this kind and size mined so far.' },
    // ADR-0026 items 4 and 8 — a ceiling (S3 alone) with its forward reading, one ticket read
    {
      size: 'L',
      tasks: 22,
      standard: {
        arm: 'S3',
        n: 20,
        clean: 20,
        ci_low: 0.839,
        ci_high: 1,
        apparatus: '2.4',
        state: 'deliver',
        ceiling: true,
        reading_id: 'r3',
        // n differs from the passes, so a screen that swapped them would be caught
        forward: { reading_id: 'rf', rule: 'look.v1', registered_at: '2026-09-28T10:00:00+00:00', state: 'look_pending', counted: 3, clean: 2, enrolled: 4, next_look: 20, needed: 17 },
      },
      next: 'Measured only against each commit’s own tests, so a ticket here is built only as a calibration build, which never opens a pull request.',
    },
    // a ceiling with no forward reading yet: an operator registers one on this page
    {
      size: 'XL',
      tasks: 21,
      standard: { arm: 'S3', n: 20, clean: 20, ci_low: 0.839, ci_high: 1, apparatus: '2.4', state: 'deliver', ceiling: true, reading_id: 'r5', forward: null },
      next: 'Measured only against each commit’s own tests, so a ticket here is built only as a calibration build, which never opens a pull request.',
    },
  ],
  quality: {
    served: true,
    rows: [
      { characteristic: 'Functional suitability', checks: [{ check: 'target_green', label: 'belt 2 `target_green`', sub: 'functional correctness', runs: 'at every grade', on: true }], evidenced: true, note: '' },
      { characteristic: 'Security', checks: [], evidenced: false, note: 'not evidenced' },
    ],
    switched_on: ['target_green', 'no_new_failures'],
    standards: [context(STANDARD)],
  },
  reaches_briefs: false,
}

/** The `mockApi` table for a populated library screen. */
export const LIBRARY_API = { 'GET /library/alpha': LIBRARY, 'GET /library/alpha/work-types/bug.fix': WORK_TYPE }
