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
| manufacture-and-deliver.purpose.1 | PURPOSE | The stream is named from its true start where a person meets it: Home's task 8 reads "Deliver your first change" and Factory is a nav item, but no screen says that work enters from the enterprise's board — the product's story begins at a frozen backlog | `hint:about:/factory` · `hint:about:/home` | partial | G-340 |
| manufacture-and-deliver.entry-exit.2 | ENTRY-EXIT | The entry is a ticket the enterprise already wrote and the exit is a pull request on their repository: today the entry is an operator typing or pasting the item into the backlog route, so the ticket is written twice | `route:POST /factory/{repo}/backlog` · `route:GET /factory/catalogue` | partial | G-341 |
| manufacture-and-deliver.truth.3 | TRUTH | Every number on an item is the chain's own and is shown before money is spent: the cell's route, reason code, n, point and lower bound are read once at readiness from rows that precede the run, and the item says so on the list | `test:tests/test_factory_loop.py::test_route_is_read_once_per_item_at_readiness_before_any_build` · `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"the route gate withholding delivery names the measured route and the reason code"` · `route:GET /factory/{repo}/tasks` | met | |
| manufacture-and-deliver.actions.4 | ACTIONS | Every action says what it did and what to do next: running the factory states the spend first, and an item the loop stopped reads as a sentence with its way forward rather than a status word | `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"an item stopped for a stronger oracle reads as a sentence with the way forward (DL-045 rule 3)"` · `route:POST /factory/{repo}/backlog/evolutions` · `dl:DL-045` | met | |
| manufacture-and-deliver.explanation.5 | EXPLANATION | A bundled guide explains the stream end to end, from where the work comes from to what happens to the pull request: forward mode is written, intake from a tracker is described nowhere because it does not exist | `doc:docs/ONBOARDING-A-REPO.md#step-8-forward-mode-when-a-cell-is-trusted` · `doc:docs/GITHUB-APP.md#5-what-happens-at-clone-and-at-delivery` | partial | G-341 |
| manufacture-and-deliver.evidence.6 | EVIDENCE | The whole stream is proven on a live stack: CI walks freeze → run → item chain with the fixture builder, and the one real delivery (two pull requests on `Jita81/cobra`) was measured on the local executor, which is a development reading, not evidence | `spec:ui/e2e/walkthrough/10-factory.spec.ts::"Run the factory with the fixture builder"` · `spec:ui/e2e/walkthrough/10-factory.spec.ts::"the item chain: one built (not clean, with its evidence), one refused at readine"` · `doc:docs/reviews/2026-09-19-b1b-first-factory-pull-request.md` · `ci:walkthrough` | partial | G-342 |
| manufacture-and-deliver.roles.7 | ROLES | The right person is the only person who can: delivery is opt-in per run, only an approver may override the route gate for one run and the override is stamped with their identity as an event, and the customer's own reviewer is the only one who merges | `test:tests/test_factory_loop.py::test_route_gate_override_by_an_approver_is_itself_on_the_record` · `dl:DL-038` · `adr:0003` | met | |
| manufacture-and-deliver.operations.8 | OPERATIONS | The platform team can watch and stop the stream: deliveries are metered by outcome (opened, withheld, failed), a run in flight is a banner with the run link and the current item, and an operator can cancel it | `test:tests/test_observability_metrics.py::test_record_event_meters_deliveries_by_outcome_and_nothing_else` · `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"an active factory run is a banner with the run link"` · `route:POST /runs/{id}/cancel` | met | |
| manufacture-and-deliver.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; the Factory and task pages carry the keyboard, focus and 375 px criteria on their own artefacts |
| manufacture-and-deliver.non-goals.10 | NON-GOALS | The limit of the product's authority is enforced, not promised: the default branch is refused before any credential is touched, the push is a branch-to-branch refspec, and nothing merges | `test:tests/test_factory_delivery.py::test_assert_not_default_branch_refuses` · `code:src/crb/factory/delivery.py::assert_not_default_branch` · `dl:DL-045` | met | |
| manufacture-and-deliver.trigger.11 | TRIGGER | A work item entering the enterprise's chosen board column is read by the product as a request to manufacture — a poll (or webhook) over an Azure DevOps WIQL or Jira JQL query, per repository, default off, with the connection held as a deployment secret — without anyone retyping the ticket | `absent` | unmet | G-341 |
| manufacture-and-deliver.outcome.12 | OUTCOME | The artefact of value is a pull request on the customer's repository whose body is the redacted evidence summary, and whose fate is read back and recorded once per pull request as `delivery.merged` or `delivery.closed` on the item's chain | `code:src/crb/factory/delivery.py::deliver` · `test:tests/test_factory_outcomes.py::test_sync_records_merged_and_closed_once_skips_open_and_reports_read_failures` · `route:POST /factory/{repo}/outcomes/sync` · `dl:DL-049` | met | |
| manufacture-and-deliver.handoff.13 | HANDOFF | Both ends of the stream join without a person carrying data: the readiness and routing answer for a ticket is posted back on that ticket as one comment with a tag, and the merge outcome lands on the item chain and the cell's counts — the second half is built, the first does not exist | `code:src/crb/server/factory_state.py::sync_outcomes` · `code:src/crb/factory/evidence.py::record_delivery_outcome` | partial | G-341 |
| manufacture-and-deliver.measure.14 | MEASURE | The product shows this stream's own numbers: lead time from the item arriving to the pull request opening and to its merge, and the cost of each certified change | `absent` | unmet | G-343 |
| manufacture-and-deliver.automation.15 | AUTOMATION | No step needs a person to do what the product could do: today the backlog is typed by hand, every item needs an operator-authored RED test because no test-author rung is wired in the worker, and every stopped item needs a hand-registered evolution | `absent` | unmet | G-344 |

## Gaps
- **G-340** — the product's account of itself starts at a frozen backlog · name the stream on Home and on the Factory page from the ticket onwards, with the intake state (listening / not configured) on the same line · ui
- **G-341** — no work reaches the factory from a tracker: no Azure DevOps or Jira listener, nothing pulls ticket fields into a draft item, and nothing writes the readiness and routing answer back to the ticket · build the column listener behind one `TrackerClient` protocol (`src/crb/intake/{ado,jira}.py`), an `intake` settings block with a per-deployment secret, a worker poll, the readiness-comment renderer, a `/factory/{repo}/intake` view, tests with a fake tracker, and an ADR ("the ticket is the backlog item; the column is the consent gate") · server
- **G-342** — the only delivery against a real repository ran on the local executor and is stamped a development reading; the sealed (docker) rerun is not done · rerun the B-1b items under `CRB_BUILDER__EXECUTOR=docker` and record the result beside the first · factory
- **G-343** — no lead time and no cost per certified change: every factory event carries a timestamp but no duration is derived, and the customer's review minutes are not captured (F20 is blocked on B-9) · derive item-registered → PR-opened → merged from the events already stored and show it on the Factory page · server
- **G-344** — intake, oracle authoring and evolution are hand work: the worker wires no test author, so a value-gap item stops `no_oracle` and a weak-oracle verdict stops with a sentence · wire a test-author rung behind the same refusal that stops a rung authoring its own oracle, and offer the superseding item pre-filled from the stop · factory
