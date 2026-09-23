---
id: dod.page.oracle
level: page
name: Oracle (how much a green is worth)
scope: /oracle
parent: dod.journey.prove-the-instrument
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Oracle (how much a green is worth)

**Purpose.** How much a green is worth for this repository: the negative controls the grader
must catch, and the mutation strength of the tests on the changed lines. A weak oracle sends a
cell to a human whatever its pass rate (`help.ts` About copy for `/oracle`; eyebrow
`Instrument · Oracle`, `OraclePage.tsx:218`).

**Entry → exit.** Arrive by the Instrument nav entry `Oracle` (operator role only,
`Layout.tsx:120`), the Baseline door `Oracle and controls` (`ResultsPage.tsx:249`), the
repository's Next steps `Oracle adequacy` (`RepoDetail.tsx:204`) or the Learn strengthen
report (`LearnPage.tsx:306`), always with `?repo=`. Leave with: per task and per cell the
strength, band and the gate a green licenses; the negative-controls gate with the server's
verdict and the seven control rows. Exits as coded: a task id opens `/tasks/:repo/:taskId`
(`OraclePage.tsx:98,187`); no repo → `Choose a repo` with one link to `/connect` (`:223`); an
operator with nothing scored or no controls report gets `Run oracle` → `/runs?repo=&new=oracle`
(`:242`) and `Run controls` → `/runs?repo=&new=controls` (`:134`).

**Non-goals.** The page never queues a run itself (the Runs dialog does), never derives the
controls gate in the browser (the server's `verdict` is rendered as served), never strengthens
a test (Learn names the work; a person does it), never compares a strength across languages or
mutator families (OPERATOR §3.1), and never says "auto-ship".

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| oracle.purpose.1 | PURPOSE | The header purpose and the About block say in one sentence what a green is worth and that a weak oracle routes to a human; no tile or pill says "auto-ship" | `hint:about:/oracle` · `vitest:ui/src/screens/Oracle/OraclePage.test.tsx::"says what a green is worth in plain words and never"` | met | |
| oracle.entry-exit.2 | ENTRY-EXIT | With no repository chosen the page shows one link to `/connect`; with a repository every task id is a link to its task page; the Baseline door and the repository's Next steps reach the page with `?repo=` set | `vitest:ui/src/screens/Oracle/OraclePage.test.tsx::"no repo sends every role to Connection"` · `vitest:ui/src/screens/Repos/RepoDetail.test.tsx::"Next steps reach the Connection walk and the Factory for this repository"` · `hint:id:button.results.oracle` · `hint:id:nav.oracle` | partial | G-919 |
| oracle.truth.3 | TRUTH | Each per-task strength reads killed / mutants (its n) with a 95 % Wilson interval computed from those served counts; the Mean strength tile names n = scored tasks, the policy version and the apparatus and says a mean of rates has no interval; the Strong and Adequate floors are the served policy's, and the policy cannot drift from the routing rule | `spec:ui/e2e/walkthrough/04-oracle-and-controls.spec.ts::"an oracle run scores every mined task"` · `test:tests/test_oracle_adequacy.py::test_policy_derived_from_routing_cannot_drift` · `test:tests/test_server_routes_oracle.py::test_shape_bands_gates` | partial | G-204 |
| oracle.truth.4 | TRUTH | The negative-controls gate is OPEN only when the server's verdict is `passed`; a report with escapes or a thin set reads CLOSED with the counts (violations over rows, escapes, not constructible, skipped); a 404 reads `No controls report yet`, never as passed | `spec:ui/e2e/walkthrough/04-oracle-and-controls.spec.ts::"a controls run renders the seven negative controls with their verdicts"` · `vitest:ui/src/screens/Oracle/OraclePage.test.tsx::"a viewer reads who runs the oracle and the controls"` · `test:tests/test_server_routes_oracle.py::test_not_measured_404` · `test:tests/test_oracle_controls.py::test_report_passes_with_escapes_reported_prominently` | met | |
| oracle.actions.5 | ACTIONS | `Run oracle` and `Run controls` are offered to an operator only and open the Runs start dialog with the repository set and the kind preselected; a viewer reads who runs them; a failed controls read shows an error card with Retry | `vitest:ui/src/screens/Oracle/OraclePage.test.tsx::"a viewer reads who runs the oracle and the controls"` · `vitest:ui/src/screens/Runs/RunsPage.test.tsx::"?new= opens the start dialog for an operator, never for a viewer (J-FAC-12)"` · `hint:id:button.oracle.run_oracle` · `hint:id:button.oracle.run_controls` | partial | G-205 |
| oracle.explanation.6 | EXPLANATION | Every tile, column header, pill, gate row and button carries a registry hint (at least 22 on the route), the ratchet enforces the route, `stat.oracle.mean` opens on hover, the band, gate, controls and escape words open their definitions inline, and the About block links the two guides | `hint:ratchet:/oracle` · `hint:about:/oracle` · `hint:id:stat.oracle.mean` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"opens its bubble with the registry text"` | partial | G-206 |
| oracle.evidence.7 | EVIDENCE | The route has unit tests per role, is walked by a tier-1 spec that runs a real oracle run and a real controls run and reads the tables, and is rendered for every persona at 375 and 1280 | `vitest:ui/src/screens/Oracle/OraclePage.test.tsx::"says what a green is worth in plain words and never"` · `spec:ui/e2e/walkthrough/04-oracle-and-controls.spec.ts::"an oracle run scores every mined task"` · `spec:ui/e2e/walkthrough/04-oracle-and-controls.spec.ts::"a controls run renders the seven negative controls with their verdicts"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | met | |
| oracle.roles.8 | ROLES | Reading the page and both reports needs `viewer` at the API and the UI; the two run links render only for `operator` and the run they queue is `POST /runs` (operator) with the actor recorded on the run; anonymous reads are 401 | `route:GET /oracle/{repo}` · `route:GET /oracle/{repo}/controls` · `route:POST /runs` · `vitest:ui/src/screens/Oracle/OraclePage.test.tsx::"a viewer reads who runs the oracle and the controls"` · `test:tests/test_server_routes_oracle.py::test_anonymous_401` · `test:tests/test_server_routes_oracle.py::test_admin_reads_too` | met | |
| oracle.operations.9 | OPERATIONS | The two routes are in API.md; OPERATOR §3.1 explains the score, the bands and the two mutator families; oracle and controls runs are counted by kind in `crb_runs_total`; the stop condition (controls not `passed` with 0 escapes) has its way forward in the guide | `doc:docs/API.md#oracle-adequacy` · `doc:docs/OPERATOR.md#31-oracle-adequacy--mutation-scoring` · `doc:docs/DEPLOYMENT.md#91-metrics--which-process-carries-which-series` · `doc:docs/ONBOARDING-A-REPO.md#step-3--prove-the-instrument-on-this-repository-operator-0` | partial | G-920 |
| oracle.accessibility.10 | ACCESSIBILITY | The route is axe-clean (WCAG 2.1 AA) with a controls report rendered, and at 375 and 1280 for every persona with a hint bubble open; a term opens and closes from the keyboard with `aria-expanded`; the bubble has no fade under reduced motion | `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"Capability, Ledger and Sign-off have no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` · `vitest:ui/src/components/Help.test.tsx::"is a button that toggles an inline definition with aria-expanded / aria-controls"` · `vitest:ui/src/components/Hint.test.tsx::"prefers-reduced-motion: the bubble gets no fade (inline, so no cascade can restore it)"` | partial | G-905 |
| oracle.non-goals.11 | NON-GOALS | The About block or the guide it links states that the page queues nothing, that the gate is the server's verdict, and that a strength is comparable only within one language and mutator family | `hint:about:/oracle` · `doc:docs/OPERATOR.md#31-oracle-adequacy--mutation-scoring` | partial | G-207 |

## Gaps
- **G-919** — A viewer (the governance reader ONBOARDING step 3 sends here) has no nav entry to `/oracle`: the Instrument entry is operator-only (`Layout.tsx:120`) although the API and the page are viewer-readable · set the entry's role to `viewer` as `/ledger` already is, and pin it in `Layout.test.tsx` · ui
- **G-204** — No test pins the per-task Wilson interval or that the Strong / Adequate tile floors follow the served policy; the About copy hard-codes `strong ≥ 0.80` (`help.ts:247`) while the page reads `policy.autoship_floor` · add an `OraclePage.test.tsx` case with a non-default policy asserting the floor text and the `[low, high]` for 9 / 10, and make the About sentence say "the policy's deliver floor" · ui
- **G-205** — The operator half of the run links is unproven: `RunsPage.test.tsx` asserts only that a viewer gets no dialog, nothing pins that `?new=oracle` preselects the kind `oracle` and the repository, and the controls `ErrorState` Retry is never rendered on this route · add a `RunsPage.test.tsx` case as operator asserting the dialog's kind and repo fields, and an `OraclePage.test.tsx` case with a 500 on controls asserting Retry refetches · ui
- **G-206** — The hint ratchet runs `/oracle` as `viewer` only (`hints-ratchet.instrument.tsx:471`), so the operator branch (`Run oracle`, `Run controls`) is outside the "every element is hinted" check · add `operator` to the entry's `roles` · ui
- **G-920** — No health probe, `crb doctor` check or metric series carries the controls verdict or the oracle band per repository; only `crb_runs_total{kind}` counts the runs · a `crb_controls_verdict{repo,state}` gauge set by the worker on `controls.report`, with a DEPLOYMENT §9.1 row and the metrics ratchet test · server
- **G-905** — the keyboard-only pass now runs on every authenticated route **[measured — n = 24 routes × 4 personas at 1280; method: `ui/e2e/walkthrough/11-screens.spec.ts` calls `keyboardPass` on each route of its `routes()` list, tabbing from the first control inside `#main`; apparatus 2.2 — a count, not a rate, so no interval]** but it stops at the first hinted controls it meets, so **[gap]** no test yet proves a keyboard person can open a map cell, reach a reason-code button, open and close a term with `aria-expanded`, complete the sign-off form and its revoke confirmation, or freeze a backlog with focus moving into the dialog and back · add one per-screen keyboard step to the walkthrough for each of those five controls, asserting focus where the screen moves it · ui
- **G-207** — The About block has no non-goal sentence: it does not say the page queues nothing, that the gate is the server's verdict, or that strengths compare within one language and family only · add one sentence to the `/oracle` entry's `numbers` in `help.ts` · ui
