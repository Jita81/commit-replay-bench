---
id: dod.stream.manufacture-and-deliver
level: stream
name: Manufacture & deliver — ticket → backlog → readiness → run → PR on the customer repo → outcome
scope: manufacture-and-deliver
parent: dod.product
children: [dod.journey.intake-from-a-ticket, dod.journey.manufacture]
persons: [operator, approver, viewer, admin]
owner: factory
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Manufacture & deliver — ticket → backlog → readiness → run → PR on the customer repo → outcome

**Purpose.** Take a piece of work from the enterprise's own board and return it as a reviewed
pull request on their repository, built only in the cells the evidence licenses, with its
refusal or its merge recorded.

**Entry → exit.** A work item enters the chosen board column (Azure DevOps first, Jira second;
per repository, default off) → a branch `crb/<item>-<slug>` and a pull request on the
customer's repository against a non-default branch, whose body is the evidence summary, whose
verdict was recorded before any edit, and whose merge or closure lands back on the item's
chain and on the ticket.

**Non-goals.** It never writes to the customer's default branch and never merges: the pull
request is where the product's authority ends. It never creates tickets, never edits ticket
fields other than its own tag, comment and the state transition the mapping allows, and never
reads a column it was not pointed at.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| manufacture-and-deliver.purpose.1 | PURPOSE | The stream is named from its true start where a person meets it: Home's task 8 reads "Deliver your first change", Factory is a nav item, and a screen says that work enters from the enterprise's board rather than from a frozen backlog | `hint:about:/factory` · `hint:about:/home` | partial | G-548 |
| manufacture-and-deliver.entry-exit.2 | ENTRY-EXIT | The entry is a ticket the enterprise already wrote and the exit is a pull request on their repository, so no one writes the ticket twice | `route:POST /factory/{repo}/backlog` · `route:GET /factory/catalogue` | partial | G-900 |
| manufacture-and-deliver.truth.3 | TRUTH | Every number on an item is the chain's own and is shown before money is spent: the cell's route, reason code, n, point and lower bound are read once at readiness from rows that precede the run, and the item says so on the list | `test:tests/test_factory_loop.py::test_route_is_read_once_per_item_at_readiness_before_any_build` · `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"the route gate withholding delivery names the measured route and the reason code"` · `route:GET /factory/{repo}/tasks` | met | |
| manufacture-and-deliver.actions.4 | ACTIONS | Every action says what it did and what to do next: running the factory states the spend first, and an item the loop stopped reads as a sentence with its way forward rather than a status word | `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"an item stopped for a stronger oracle reads as a sentence with the way forward (DL-045 rule 3)"` · `route:POST /factory/{repo}/backlog/evolutions` · `dl:DL-045` | met | |
| manufacture-and-deliver.explanation.5 | EXPLANATION | A bundled guide explains the stream end to end, from where the work comes from to what happens to the pull request: forward mode is written, intake from a tracker is described nowhere because it does not exist | `doc:docs/ONBOARDING-A-REPO.md#step-8-forward-mode-when-a-cell-is-trusted` · `doc:docs/GITHUB-APP.md#5-what-happens-at-clone-and-at-delivery` | partial | G-903 |
| manufacture-and-deliver.evidence.6 | EVIDENCE | The whole stream is proven on a live stack: CI walks freeze → run → item chain with the fixture builder, and the one real delivery (two pull requests on `Jita81/cobra`) was measured on the local executor, which is a development reading, not evidence | `spec:ui/e2e/walkthrough/10-factory.spec.ts::"Run the factory with the fixture builder"` · `spec:ui/e2e/walkthrough/10-factory.spec.ts::"the item chain: one built (not clean, with its evidence), one refused at readine"` · `doc:docs/reviews/2026-09-19-b1b-first-factory-pull-request.md` · `ci:walkthrough` | partial | G-549 |
| manufacture-and-deliver.roles.7 | ROLES | The right person is the only person who can: delivery is opt-in per run, only an approver may override the route gate for one run and the override is stamped with their identity as an event, and the customer's own reviewer is the only one who merges | `test:tests/test_factory_loop.py::test_route_gate_override_by_an_approver_is_itself_on_the_record` · `dl:DL-038` · `adr:0003` | met | |
| manufacture-and-deliver.operations.8 | OPERATIONS | The platform team can watch and stop the stream: deliveries are metered by outcome (opened, withheld, failed), a run in flight is a banner with the run link and the current item, and an operator can cancel it | `test:tests/test_observability_metrics.py::test_record_event_meters_deliveries_by_outcome_and_nothing_else` · `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"an active factory run is a banner with the run link"` · `route:POST /runs/{id}/cancel` | met | |
| manufacture-and-deliver.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; the Factory and task pages carry the keyboard, focus and 375 px criteria on their own artefacts |
| manufacture-and-deliver.non-goals.10 | NON-GOALS | The limit of the product's authority is enforced, not promised: the default branch is refused before any credential is touched, the push is a branch-to-branch refspec, and nothing merges | `test:tests/test_factory_delivery.py::test_assert_not_default_branch_refuses` · `code:src/crb/factory/delivery.py::assert_not_default_branch` · `dl:DL-045` | met | |
| manufacture-and-deliver.trigger.11 | TRIGGER | A work item entering the enterprise's chosen board column is read by the product as a request to manufacture — a poll (or webhook) over an Azure DevOps WIQL or Jira JQL query, per repository, default off, with the connection held as a deployment secret — without anyone retyping the ticket | `absent` | unmet | G-901 |
| manufacture-and-deliver.outcome.12 | OUTCOME | The artefact of value is a pull request on the customer's repository whose body is the redacted evidence summary, and whose fate is read back and recorded once per pull request as `delivery.merged` or `delivery.closed` on the item's chain | `code:src/crb/factory/delivery.py::deliver` · `test:tests/test_factory_outcomes.py::test_sync_records_merged_and_closed_once_skips_open_and_reports_read_failures` · `route:POST /factory/{repo}/outcomes/sync` · `dl:DL-049` | met | |
| manufacture-and-deliver.handoff.13 | HANDOFF | Both ends of the stream join without a person carrying data: the readiness and routing answer for a ticket is posted back on that ticket as one comment with a tag, and the merge outcome lands on the item chain and the cell's counts — the second half is built, the first does not exist | `code:src/crb/server/factory_state.py::sync_outcomes` · `code:src/crb/factory/evidence.py::record_delivery_outcome` | partial | G-902 |
| manufacture-and-deliver.measure.14 | MEASURE | The product shows this stream's own numbers: lead time from the item arriving to the pull request opening and to its merge, and the cost of each certified change | `absent` | unmet | G-925 |
| manufacture-and-deliver.automation.15 | AUTOMATION | No step needs a person to do what the product could do: the backlog arrives from the tracker, a `test_author` rung in the served worker offers the RED test for an item that has none, and a stopped item's evolution is proposed rather than hand-registered | `absent` | unmet | G-904 |

## Gaps
- **G-548** — the product's account of itself starts at a frozen backlog · name the stream on Home and on the Factory page from the ticket onwards, with the intake state (listening / not configured) on the same line · ui
- **G-900** — no tracker connection exists, so no column can be watched · add an `intake` settings block (`tracker: ado|jira`, organisation or site URL, project, watched column or state, area path or JQL, `intake_poll_s`, `enabled` default OFF per repository) to `src/crb/server/settings.py` and a tracker secret in the product's own store, read back as a fingerprint like the GitHub App key · server
- **G-901** — nothing polls the watched column, so a ticket never reaches the product · read each switched-on repository's column every `intake_poll_s` in `Worker.run_forever`'s idle loop through the `TrackerClient`, keyed by (tracker, key, revision) on the chain, queueing a registration refused with `409 factory_run_active` and recording every stop as an `intake.*` event the health probe and the screen serve · server
- **G-902** — no gap feedback leaves the product, so the ticket never learns what is missing · render `open_questions()` plus the pre-run `cell_route` (route, n, Wilson interval, false-Q1, apparatus) into one idempotent marked comment on the ticket, set `crb:needs-info` / `crb:ready` / `crb:not-deliverable`, record `intake.feedback.posted` and serve the same text on the intake row · factory
- **G-903** — neither the decision nor the operation is recorded anywhere a reader can find · add an ADR ("the ticket is the backlog item; the column is the consent gate") with its DECISION-LOG row, API.md rows for the intake route and the `intake.*` vocabulary, an OPERATOR section (settings, secret, `/health` and `crb doctor` probes, telemetry, stop conditions), a SECURITY §2 egress row and a guide section stating the non-goals and the measured minutes and £ per ticket · docs
- **G-904** — the served worker configures no `test_author` rung (`Worker._run_factory` builds `FactorySpec` without one), so every item without an operator-authored test stops `no_oracle` · configure a test-author rung in the served worker, or refuse at intake with `crb:needs-info` naming the acceptance test as the missing slot before any spend · factory
- **G-549** — the only delivery against a real repository ran on the local executor and is stamped a development reading; the sealed (docker) rerun is not done · rerun the B-1b items under `CRB_BUILDER__EXECUTOR=docker` and record the result beside the first · factory
- **G-925** — the product folds no lead time and no spend out of the events it already stores, so backlog → merge and cost per human-verified change cannot be shown (backlog F20; the merge outcome is already recorded by `sync_outcomes`, and B-9's open half is the reviewer-minutes capture) · derive the durations and the spend per stream from the runs and events already stored, capture reviewer minutes on `POST /reviews`, and serve a Flow view with one endpoint per stream · server
