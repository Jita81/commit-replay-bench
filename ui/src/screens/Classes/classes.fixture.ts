/**
 * Fixtures for the classes screen — one organisation, a proposed version with its report, a
 * class's page and the labelling queue.
 *
 * Navigation
 * ----------
 * What it is:   `INDEX` (`GET /classes`: acme's v1, proposed by Ada, not signed, routing nothing),
 *               `VERSION` (`GET /classes/acme/v/1`: two classes, the report with a failing
 *               agreement, the split), `CLASS_PAGE` (`GET /classes/acme/v/1/classes/parser-fix`)
 *               and `QUEUE` (`GET /classes/acme/v/1/label-queue`: two derivation commits, one
 *               labelled by the reader).
 * What it does: Gives the screen test and the hint ratchet one populated state to render, in the
 *               shapes docs/API.md#classes names.
 * How:          Plain objects typed by ui/src/api/types.ts.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 9)
 * Works with:   ui/src/screens/Classes/ClassesPage.test.tsx (renders it),
 *               ui/src/help/hints-ratchet.instrument.tsx (hints the route with it),
 *               ui/src/api/types.ts (the shapes it is typed by)
 * Tested by:    ui/src/screens/Classes/ClassesPage.test.tsx
 * Touch when:   never for a new repository; a field of `/classes` changes (types.ts first).
 */
import type { ClassLabelQueue, ClassPage, ClassSetIndex, ClassSetVersionDetail, ClassSetVersionSummary } from '../../api/types'

export const ADA = 'a'.repeat(32)
export const BEN = 'b'.repeat(32)

const THRESHOLDS = {
  coverage_min: 0.9,
  kappa_min: 0.6,
  sample_min: 50,
  per_class_min: 5,
  measurable_min: 20,
  override_rate_max: 0.2,
  derivation_share: 1 / 3,
  split_seed: 'crb.split.v1',
}

export const SUMMARY: ClassSetVersionSummary = {
  version_id: 'acme/classes@v1',
  org: 'acme',
  n: 1,
  digest: 'd'.repeat(64),
  version: {
    org: 'acme',
    n: 1,
    classes: [
      { slug: 'parser-fix', title: 'A fix to the parser', definition: 'A change that corrects how the parser reads its input.', parent: 'bug.fix', rule: { words: ['parser', 'parse'], work_item_types: [], components: [], labels: [] }, entry_id: '', entry_repo: '' },
      { slug: 'cli-fix', title: 'A fix to the command line', definition: 'A change that corrects the command line’s flags.', parent: 'bug.fix', rule: { words: ['cli', 'flag'], work_item_types: [], components: [], labels: [] }, entry_id: '', entry_repo: '' },
    ],
    repos: ['alpha'],
    proposed_by: ADA,
    derivation_share: 1 / 3,
    split_seed: 'crb.split.v1',
    based_on: '',
  },
  status: 'proposed',
  sponsor: ADA,
  sponsor_name: 'Ada',
  proposed_at: '2026-09-28T10:00:00+00:00',
  approver: '',
  approver_name: '',
  signed_at: '',
  revoked: null,
  route: { routes: false, code: 'class_set_unsigned', words: 'No approver other than its sponsor has signed it, so it routes nothing.' },
  passes: false,
}

export const INDEX: ClassSetIndex = {
  orgs: [{ org: 'acme', versions: [SUMMARY] }],
  repos: ['alpha'],
  thresholds: THRESHOLDS,
  global_classes: [
    { slug: 'bug.fix', definition: 'Fixes a defect in existing behaviour.' },
    { slug: 'feature.add', definition: 'Adds a new capability.' },
  ],
}

export const VERSION: ClassSetVersionDetail = {
  ...SUMMARY,
  report: {
    version_id: 'acme/classes@v1',
    passes: false,
    size_from_points: false,
    measures: [
      { name: 'coverage', value: 0.95, threshold: 'at least 90% of replayable commits in a named class', n: 208, state: 'pass', words: '198 of 208 replayable commits fall in a named class (95.2%).', detail: {} },
      { name: 'agreement', value: 0.41, threshold: 'κ at least 0.6 over at least 50 derivation commits, at least 5 per class', n: 12, state: 'fail', words: 'κ = 0.41 between the rule and a person over 12 labels of 12 derivation commits; the sample needs 38 more commits.', detail: {} },
      { name: 'stability', value: 1, threshold: 'the rule repeats its own labels at least 90% of the time', n: 208, state: 'pass', words: 'Applied twice, the rule gave the same class to 208 of 208 commits (it is a fixed rule, not a model).', detail: {} },
      { name: 'ticket_consistency', value: null, threshold: 'where at least 20 commits link a ticket', n: 0, state: 'not_applicable', words: '0 commits link a ticket; the check applies from 20.', detail: {} },
      { name: 'size_agreement', value: null, threshold: 'on at least 20 pointed tickets', n: 0, state: 'fail', words: '0 linked tickets carry points.', detail: {} },
      { name: 'measurability', value: 2, threshold: 'at least 20 confirmation commits in each class and size cell it routes', n: 120, state: 'pass', words: '2 class and size cells hold 20 or more qualified confirmation commits.', detail: {} },
      { name: 'override_rate', value: 0, threshold: 'at most 20% of classified tickets carry a crb:class= override', n: 198, state: 'pass', words: '0 of 198 classified tickets named their class with crb:class= (0.0%).', detail: {} },
    ],
    routable_cells: [
      { class: 'parser-fix', size: 'S' },
      { class: 'cli-fix', size: 'S' },
    ],
    commits: 208,
    derivation: 70,
    confirmation: 138,
  },
  split: [{ repo: 'alpha', derivation: 70, confirmation: 138 }],
  class_counts: [
    { class: 'parser-fix', derivation: 30, confirmation: 60 },
    { class: 'cli-fix', derivation: 30, confirmation: 60 },
    { class: '(unclassified)', derivation: 10, confirmation: 18 },
  ],
  thresholds: THRESHOLDS,
}

export const CLASS_PAGE: ClassPage = {
  org: 'acme',
  version_id: 'acme/classes@v1',
  status: 'proposed',
  route: SUMMARY.route,
  slug: 'parser-fix',
  title: 'A fix to the parser',
  definition: 'A change that corrects how the parser reads its input.',
  parent: 'bug.fix',
  parent_definition: 'Fixes a defect in existing behaviour.',
  rule: { words: ['parser', 'parse'], work_item_types: [], components: [], labels: [] },
  // the server writes straight apostrophes; the page sets them as ’ (typeset in ClassesPage)
  rule_words: "A ticket is in this class when the ticket's text says “parser” or “parse”.",
  entry_id: '',
  entry_repo: '',
  examples: [{ repo: 'alpha', sha: 'c'.repeat(40), subject: 'fix: the parser drops a token (1)', size: 'S', proxy: true }],
  ticket_slots: [{ name: 'reproduction', question: 'How is the bug reproduced (the input / sequence that fails)?', kind: 'structural' }],
  signed_slots: [],
  context: [{ repo: 'alpha', entry_id: 'convention/errors-wrap', title: 'Wrap errors', statement: 'Every returned error names the operation.', sponsor: ADA, sponsor_name: 'Ada', approver: BEN, approver_name: 'Ben', signed_at: '2026-09-27T10:00:00+00:00', effect: 'unmeasured' }],
  library: [{ repo: 'alpha', work_type: 'bug.fix' }],
  sizes: [
    { repo: 'alpha', size: 'XS', confirmation: 0, standard: null, next: 'Wait for the class set to route; 0 qualified confirmation commits so far.' },
    { repo: 'alpha', size: 'S', confirmation: 60, standard: null, next: 'Wait for the class set to route; 60 qualified confirmation commits so far.' },
  ],
}

export const QUEUE: ClassLabelQueue = {
  version_id: 'acme/classes@v1',
  classes: [
    { slug: 'parser-fix', title: 'A fix to the parser', definition: 'A change that corrects how the parser reads its input.' },
    { slug: 'cli-fix', title: 'A fix to the command line', definition: 'A change that corrects the command line’s flags.' },
  ],
  items: [
    { repo: 'alpha', task_id: 'e'.repeat(40), message: 'fix: the cli flag --x4 is ignored', ticket: null, diff: { source_files: 1, test_files: 2, churn: 12 }, my_label: '' },
    { repo: 'alpha', task_id: 'f'.repeat(40), message: 'fix: the parser drops a token (3)', ticket: null, diff: { source_files: 1, test_files: 1, churn: 12 }, my_label: 'parser-fix' },
  ],
  labelled_by_me: 1,
  sample_min: 50,
  per_class_min: 5,
  sponsor: false,
}

export const CLASSES_API: Record<string, unknown> = {
  'GET /classes': INDEX,
  'GET /classes/acme/v/1': VERSION,
  'GET /classes/acme/v/1/classes/parser-fix': CLASS_PAGE,
  'GET /classes/acme/v/1/label-queue': QUEUE,
}
