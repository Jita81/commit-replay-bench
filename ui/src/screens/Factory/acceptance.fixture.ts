/**
 * The held-out acceptance-test screen's fixture: open, graded and built-not-graded assignments.
 *
 * Navigation
 * ----------
 * What it is:   `ACCEPTANCE`, the `GET /factory/alpha/acceptance` body the screen's tests and the
 *               hint ratchet render.
 * What it does: Holds a populated state — an open assignment the signed-in operator may answer,
 *               a graded one with its record, its writer's name and a result a forward reading
 *               counts, and one built without held-out tests — so every element a reader meets
 *               is rendered and checked for its hint.
 * How:          A plain object in the `AcceptanceAssignments` shape.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 8)
 * Works with:   ui/src/screens/Factory/AcceptancePage.tsx (the screen), ui/src/api/types.ts (the
 *               shape), ui/src/help/hints-ratchet.instrument.tsx (the ratchet's entry)
 * Tested by:    ui/src/screens/Factory/AcceptancePage.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   never for a new repository; the assignment's shape changes.
 */
import type { AcceptanceAssignments } from '../../api/types'

/** Whole 32-character user ids, as the store keeps them: the page shows names, never cut ids. */
export const APPROVER_ID = '3f9a1c2b'.repeat(4)
export const WRITER_ID = '7d0e44a1'.repeat(4)

export const ACCEPTANCE: AcceptanceAssignments = {
  repo: 'alpha',
  assignments: [
    {
      item_id: 'I-1',
      title: 'Add multiply to calc',
      description: 'calc needs a multiply(a, b) function.',
      acceptance_criteria: ['multiply(3, 4) == 12'],
      capability_class: 'bug.fix',
      size: 'XS',
      grant: 'g1',
      funded_by: APPROVER_ID,
      funded_by_name: 'Ada Approver',
      funded_at: '2026-09-28T10:00:00+00:00',
      status: 'open',
      can_write: true,
      why_not: '',
      record: null,
      author_name: '',
      result: '',
      forward_reading: 'rdg_forward',
      counted_by: '',
      suggested_path: 'tests/test_i_1_held_out.py',
    },
    {
      item_id: 'I-2',
      title: 'Divide in calc',
      description: 'calc needs divide(a, b).',
      acceptance_criteria: [],
      capability_class: 'bug.fix',
      size: 'XS',
      grant: 'g2',
      funded_by: APPROVER_ID,
      funded_by_name: 'Ada Approver',
      funded_at: '2026-09-27T10:00:00+00:00',
      status: 'graded',
      can_write: false,
      why_not: 'the build’s first attempt has been graded on the held-out tests',
      record: {
        record_id: 'hot_1',
        item_id: 'I-2',
        grant: 'g2',
        author: `operator:${WRITER_ID}`,
        written_at: '2026-09-27T11:00:00+00:00',
        sha256: 'a'.repeat(64),
        paths: ['tests/test_divide_held_out.py'],
      },
      author_name: 'Bea Second',
      result: 'pass',
      forward_reading: 'rdg_forward',
      counted_by: 'rdg_forward',
      suggested_path: 'tests/test_i_2_held_out.py',
    },
    {
      item_id: 'I-3',
      title: 'Power in calc',
      description: 'calc needs power(a, b).',
      acceptance_criteria: ['power(2, 3) == 8'],
      capability_class: 'bug.fix',
      size: 'XS',
      grant: 'g3',
      funded_by: APPROVER_ID,
      funded_by_name: 'Ada Approver',
      funded_at: '2026-09-26T10:00:00+00:00',
      status: 'not_graded',
      can_write: false,
      why_not: 'the build started before any held-out tests were written, so its first attempt was graded on the ticket’s own test only',
      record: null,
      author_name: '',
      result: '',
      forward_reading: 'rdg_forward',
      counted_by: '',
      suggested_path: 'tests/test_i_3_held_out.py',
    },
  ],
}
