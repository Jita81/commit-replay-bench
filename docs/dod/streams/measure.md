---
id: dod.stream.measure
level: stream
name: Measure — mine / replay / blind → ledger → capability map & routing
scope: measure
parent: dod.product
children: [dod.journey.measure, dod.journey.read-the-map-and-decide]
persons: [operator, viewer, approver, admin]
owner: server
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Measure — mine / replay / blind → ledger → capability map & routing

**Purpose.** Spend a known amount of money to find out what an AI builder can actually do on
this repository, graded by the repository's own tests, and turn the rows into one map that
says where delivery is licensed and where it is not.

**Entry → exit.** The controls pass and an operator queues the first sighted replay → a
capability map whose every cell carries n, a Wilson interval, false-Q1, the oracle strength,
cost and latency means, the apparatus stamp, the failure split and the ONE rule's route with
its reason code.

**Non-goals.** A measurement is not a licence: the map lifts no verification tier by itself
and blind rows never license delivery. It says nothing outside the corpus's domain — the rates
are over source-and-test-coupled commits inside the pool caps, not architecture, migrations,
UX or source-only change.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| measure.purpose.1 | PURPOSE | The stream is named where a person meets it: Home's task 5 reads "Measure — spends money" and task 6 "Read the baseline", and the Baseline page is the artefact those tasks lead to | `hint:about:/home` · `hint:about:/results` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"derives the eight tasks from the API and counts the completed ones"` | met | |
| measure.entry-exit.2 | ENTRY-EXIT | The person arrives from the proven repository and leaves with a cell they can read: the Capability page shows the measured cell carrying n, a Wilson interval and its route | `spec:ui/e2e/walkthrough/05-replay-fake.spec.ts::"the Capability page: the measured cell carries n, a Wilson interval and rout"` · `hint:about:/results` | met | |
| measure.truth.3 | TRUTH | Every rate the stream renders carries n, the interval, the apparatus and the method, and false-Q1 is refused at write rather than reported afterwards | `doc:docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method` · `test:tests/test_ledger.py::test_ledger_refuses_a_false_q1_row_before_writing` · `test:tests/test_store_ledger.py::test_append_refuses_a_false_q1_row_even_if_constructed_sideways` · `spec:ui/e2e/walkthrough/05-replay-fake.spec.ts::"the Ledger page: chain verifies, false-Q1 = 0, the rows are listed"` · `adr:0001` | met | |
| measure.actions.4 | ACTIONS | Every action states its cost before it runs and its outcome after: a run declares its budget and spend, and a replay that failed with no rows offers Retry with the run to open, never a blind second spend | `vitest:ui/src/screens/Connect/connection.test.ts::"a failed replay with no rows is failed with the run to open, and offers Retry not a blind spend"` · `route:POST /runs` · `spec:ui/e2e/walkthrough/09-budget-sweep.spec.ts::"clean on rung 1"` | met | |
| measure.explanation.5 | EXPLANATION | A bundled guide explains the stream end to end — queue a sweep, grade under the belts, read the map, read the route — in the words the screens use | `doc:docs/ONBOARDING-A-REPO.md#step-4-measure-operator-the-money-step` · `doc:docs/ONBOARDING-A-REPO.md#step-5-read-the-map-everyone` · `doc:docs/OPERATOR.md#3-run-a-sweep` · `doc:docs/OPERATOR.md#4-read-the-capability-map` | met | |
| measure.evidence.6 | EVIDENCE | One walkthrough chain proves the whole stream on a live stack in CI: start a replay, read the rows and their belts, verify the ledger, read the cell with its interval and route, and be refused a sign-off on a thin cell | `spec:ui/e2e/walkthrough/05-replay-fake.spec.ts::"the Ledger page: chain verifies, false-Q1 = 0, the rows are listed"` · `spec:ui/e2e/walkthrough/05-replay-fake.spec.ts::"the Capability page: the measured cell carries n, a Wilson interval and rout"` · `ci:walkthrough` | met | |
| measure.roles.7 | ROLES | Queueing a run and spending money is an operator's act; a viewer reads the same map and ledger, and the abstract export is not offered to them | `vitest:ui/src/screens/Ledger/LedgerPage.test.tsx::"a viewer has no abstract export and no note"` · `route:POST /runs` | met | |
| measure.operations.8 | OPERATIONS | The platform team can see the stream's stop conditions where they happen: `/health`'s ledger probe counts false-Q1 rows, the metrics carry the belt failures and spend, and the shell's "Delivery halted" banner is proven to render when the probe is non-zero | `route:GET /metrics` · `code:src/crb/server/routes/system.py::probe_ledger` · `doc:docs/OPERATOR.md#8-stop-conditions` | partial | G-564 |
| measure.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; the Measure, Runs, Results and Capability pages carry the keyboard, focus and axe criteria on their own artefacts |
| measure.non-goals.10 | NON-GOALS | What the measurement cannot say is written where a reader meets the number: the corpus's domain of validity and the forbidden claim shapes are stated in the bundled evidence policy | `doc:docs/EVIDENCE-AND-CLAIMS.md#6b-domain-of-validity-what-the-corpus-can-and-cannot-say` · `doc:docs/EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said` | met | |
| measure.trigger.11 | TRIGGER | The product marks the stream ready itself rather than waiting to be told: when the controls pass and the mined tasks exist, the Measure stage becomes actionable and Home's task 5 unblocks with the repository already chosen | `vitest:ui/src/screens/Connect/connection.test.ts::"mined counts, an oracle report, a passed controls report and measured rows complete their stages"` · `code:ui/src/screens/Connect/connection.ts::stagesFor` | met | |
| measure.outcome.12 | OUTCOME | The artefact of value is the capability map: per cell n, n_tasks, point, Wilson interval, false-Q1, oracle strength, cost and latency means, apparatus versions, the failure split and the ONE rule's route with a reason code | `code:src/crb/core/capability.py::build_capability_map` · `code:src/crb/core/routing.py::route` · `route:GET /routes?repo=[&by=]` · `adr:0003` | met | |
| measure.handoff.13 | HANDOFF | The next streams start from this one's output with nothing retyped: the Decisions inbox derives its rows from the map, and the factory's route gate reads the same map once per item, excluding the run's own rows | `code:ui/src/screens/Decisions/decisions.ts::decisionsFor` · `code:src/crb/server/worker.py::_route_lookup` · `test:tests/test_factory_loop.py::test_route_is_read_once_per_item_at_readiness_before_any_build` | met | |
| measure.measure.14 | MEASURE | The product shows this stream's own numbers: elapsed time and money spent from the first row to a cell at n ≥ 10, and the cumulative spend per repository | `absent` | unmet | G-925 |
| measure.automation.15 | AUTOMATION | No step needs a person to do what the product could do: a cell one row short of the bar is not topped up — an operator reads n, works out how many attempts remain and queues another run by hand | `absent` | unmet | G-565 |

## Gaps
- **G-564** — the "Delivery halted" stop-condition banner is rendered by no test: no walkthrough produces a false-Q1 row and no unit test asserts the banner · assert it in a unit test with a stubbed health probe reporting `false_q1 > 0` · ui
- **G-565** — nothing offers to finish a thin cell: `remeasure_plan` computes `n_needed` and the cost only after an apparatus bump, never for a cell short of `min_n` · serve "n_needed and its cost" on every under-bar cell with the run body pre-filled · server
- **G-925** — the product folds no lead time and no spend out of the events it already stores, so backlog → merge and cost per human-verified change cannot be shown (backlog F20; the merge outcome is already recorded by `sync_outcomes`, and B-9's open half is the reviewer-minutes capture) · derive the durations and the spend per stream from the runs and events already stored, capture reviewer minutes on `POST /reviews`, and serve a Flow view with one endpoint per stream · server
