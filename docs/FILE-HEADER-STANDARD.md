# File header standard — every source file explains itself and links to its neighbours

**Why.** This product is handed to developers and governance reviewers who did not write it.
Every file carries, at its top, what it is, what it does, how it does it, where it sits in the
architecture, which files it works with, which tests prove it, and when a developer onboarding
a client repository would need to touch it. The headers are the source of truth for the
generated contents page [`docs/CODE-MAP.md`](CODE-MAP.md) (`scripts/code_map.py`), and CI
(`code-map` job) fails when a file lacks the block or a link in it points at a file that does
not exist. The README is the front door; CODE-MAP is the contents page; the headers are the
pages.

## The block

Python: inside the module docstring (the first statement of the file). TypeScript / TSX: in a
leading `/** … */` comment before the first import. Tests: the same block, where "What it
does" says what property the file pins. The block is the LAST part of the docstring/comment so
existing prose (design notes, invariants, worked examples) stays above it untouched.

```
Navigation
----------
What it is:   one sentence — the thing this file is (a grader, a route module, a fixture …)
What it does: two or three sentences — the behaviour, the inputs and outputs, the invariant
              it enforces; what it refuses to do
How:          two or three sentences — the mechanism, in the order it runs
Layer:        core | builders | store | server | observability | factory | cli | ui | tests | deploy
              — docs/ARCHITECTURE.md#<anchor of the section that describes this layer>
ADRs:         docs/adr/<file>.md, … (or "none")
Works with:   src/crb/…/x.py (why), src/crb/…/y.py (why) — the files a reader opens next
Tested by:    tests/test_x.py, … (or "untested — <reason>", never blank)
Touch when:   the situations in which a developer edits THIS file — onboarding a repo, adding
              a runner/belt/builder/screen, changing a threshold; and what must change with it
              (an ADR, EVIDENCE-AND-CLAIMS, a migration, the API doc, the UI type)
Claims:       (optional) what this file's output licenses and what it does not — cite
              docs/EVIDENCE-AND-CLAIMS.md sections
```

Rules:
- Keys exactly as above, in that order; `Claims` optional, the rest required.
- Every path is repository-relative (`src/crb/core/grade.py`, `docs/adr/0001-….md`,
  `ui/src/screens/Runs/RunDetailPage.tsx`) and must exist; `scripts/code_map.py --check`
  refuses a dangling link. A path may carry an `#anchor` for Markdown targets.
- `Works with` names files, never packages, and says WHY in parentheses — that is the
  hyperlink graph a reader walks. Three to eight entries; the most-read neighbour first.
- `Touch when` is written for the developer onboarding a client repository first, the
  contributor second. If nothing in the file ever changes for a new repository, say so:
  "never for a new repository; …".
- Prose above the block: keep it. Do not restate the block. Do not pad. A reader should be able
  to read the summary line, the block, and know whether to open the file.
- Wrap at 100 columns. British English. No marketing.

## Python example (tail of the module docstring)

```python
"""THE belt grader. false-Q1 = 0 by construction.

… existing prose …

Navigation
----------
What it is:   The grader — the one function (`grade`) that turns a trial worktree into a
              `GradeResult` under the belts.
What it does: Evaluates belts 1–5 mechanically against the parent tree and the overlaid
              oracle; credits `clean` only when every evaluated belt holds; records harness
              errors, tampering and malformed oracles as non-passes or disqualifications.
How:          Integrity check of the git view → tamper scan (test files, test infrastructure,
              other tests) → target run → belt-scope run → diff stats → belt 5 plan → result.
Layer:        core — docs/ARCHITECTURE.md#31-crbcore-the-engine
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/workspace.py (the trial tree and its integrity), src/crb/core/lint.py
              (belt 5), src/crb/core/ledger.py (the row a result becomes), src/crb/core/runners/base.py
              (the test runs)
Tested by:    tests/test_grade.py, tests/test_oracle_controls.py, tests/test_runners_node.py
Touch when:   never for a new repository (configure the runner and belt scope instead —
              docs/OPERATOR.md#repository-configuration); adding a belt or changing what
              "clean" means needs an ADR and an apparatus bump (docs/EVIDENCE-AND-CLAIMS.md#4).
Claims:       A clean grade is a mechanical observation, not mergeability
              (docs/EVIDENCE-AND-CLAIMS.md#7-what-may-be-claimed).
"""
```

## TypeScript example (leading comment)

```ts
/**
 * Run detail — one run's status, counts, live event stream and per-task table.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /runs/:id.
 * What it does: … 
 * How:          …
 * Layer:        ui — docs/ARCHITECTURE.md#36-ui-the-observability-front-end
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (the queries), ui/src/api/types.ts (Run, RunTaskRow), …
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx, ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   a field is added to GET /runs/{id} (docs/API.md) — update ui/src/api/types.ts first
 */
```
