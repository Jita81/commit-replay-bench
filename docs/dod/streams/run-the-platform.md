---
id: dod.stream.run-the-platform
level: stream
name: Run the platform — deploy, go live, operate, recover
scope: run-the-platform
parent: dod.product
children: [dod.journey.orient, dod.journey.deploy-and-go-live, dod.journey.recover-an-account, dod.journey.operate]
persons: [admin, operator, approver, viewer]
owner: deploy
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Run the platform — deploy, go live, operate, recover

**Purpose.** Stand the instrument up inside the enterprise's own tenant and keep it honest and
watchable, so every other stream runs on a deployment whose state a person can read.

**Entry → exit.** An operator installs the image (`docs/DEPLOYMENT.md` §3) → a stack whose
`/health` probes are green, whose posture statement prints for a review board, whose runs can
be watched and cancelled, and whose accounts can be recovered without emptying the users table.

**Non-goals.** It measures nothing and spends nothing. It does not run the enterprise's
infrastructure: the egress test, backup rehearsal, PITR, key vault, image digest pinning,
alert rules, branch protection and the penetration test are operator acts the guides describe
and the product does not perform. It does not federate or manage more than one deployment.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| run-the-platform.purpose.1 | PURPOSE | A person signed in can read, in the product, that deploying, going live, operating and recovering are one named piece of work: Home's task list starts at "Connect GitHub", after the stack is already installed, and no screen names this stream | `absent` | unmet | G-580 |
| run-the-platform.entry-exit.2 | ENTRY-EXIT | A deployment that has just started states its own condition without anyone running a command: `GET /health` answers with the database, the append-only ledger and the worker, and the shell shows the instrument-health pill on the first screen after sign-in | `route:GET /health` · `spec:ui/e2e/walkthrough/01-login.spec.ts::"the stack answers /health with a database, an append-only ledger and a worker"` | met | |
| run-the-platform.truth.3 | TRUTH | The chain state and the false-Q1 total a reader sees come from a live verification of the ledger, not a stored summary, and the apparatus and policy versions under them are the ones this deployment reports | `route:GET /ledger/verify` · `route:GET /version` · `spec:ui/e2e/walkthrough/05-replay-fake.spec.ts::"the Ledger page: chain verifies, false-Q1 = 0, the rows are listed"` | met | |
| run-the-platform.actions.4 | ACTIONS | Every operator action in this stream reports its outcome: Cancel run stops the run after the attempt in flight, lands within 30 seconds, and the Runs list then reads it as cancelled — nothing already graded is lost | `route:POST /runs/{id}/cancel` · `spec:ui/e2e/walkthrough/06-cancel.spec.ts::"a running mine run is cancelled within 30 s of clicking Cancel run"` · `spec:ui/e2e/walkthrough/06-cancel.spec.ts::"the Runs list shows the run as cancelled"` | met | |
| run-the-platform.explanation.5 | EXPLANATION | Every section of the guide that governs this stream is reachable from the screen it governs: the go-live checklist and the Users section are bundled in the UI but linked from no screen and named in no `help.ts` entry | `doc:docs/DEPLOYMENT.md#8-go-live-checklist` · `doc:docs/OPERATOR.md#9-users` · `doc:docs/DEPLOYMENT.md#9-observability` | partial | G-581 |
| run-the-platform.evidence.6 | EVIDENCE | One walkthrough chain proves the stream end to end on a live stack — health, sign-in, a protected route, Settings, cancel, ledger verify — and the Deployment page's own rows and an account recovery are part of that chain | `spec:ui/e2e/walkthrough/01-login.spec.ts::"a protected route bounces to /login?next= and comes back after signing in"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"Settings shows builders configured yes/no, the sandbox mode and the ver"` · `ci:walkthrough` | partial | G-582 |
| run-the-platform.roles.7 | ROLES | Who may act is refused at the API, not only hidden in the UI: only an admin changes a role, a password or the active flag, the last active admin can never be demoted or deactivated, and every change is one audit event with actor and target | `test:tests/test_server_admin_users.py::test_last_admin_guard_and_second_admin` · `test:tests/test_server_admin_users.py::test_every_change_is_one_event_with_actor_and_target` · `route:PUT /users/{id}/active` | met | |
| run-the-platform.operations.8 | OPERATIONS | The platform team can see this stream's own state from outside the UI: `/health` reports the database, migrations, append-only triggers, ledger, worker heartbeat and sandbox; `/metrics` serves the series; `crb doctor` checks each host | `code:src/crb/server/routes/system.py::collect_health` · `code:src/crb/server/routes/system.py::probe_worker` · `route:GET /metrics` · `code:src/crb/cli/commands/service.py::cmd_doctor` | met | |
| run-the-platform.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; every page in it carries the keyboard, focus and axe criteria on its own artefact (07-settings-and-a11y, 11-screens) |
| run-the-platform.non-goals.10 | NON-GOALS | The acts this product does not perform — egress test, backup rehearsal, image digest pinning, alert rules, penetration test — are named on the Deployment page a reviewer reads, not only in the guides | `absent` | unmet | G-583 |
| run-the-platform.trigger.11 | TRIGGER | The product notices the state that starts this stream's work without being asked: a degraded sandbox raises a banner, the health pill changes, and a screen reads the go-live checklist against the deployment's own probes so an unfinished go-live is noticed | `route:GET /health` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"derives the eight tasks from the API and counts the completed ones"` | partial | G-584 |
| run-the-platform.outcome.12 | OUTCOME | The stream's artefact of value is a printable deployment posture statement at `/posture` — build and apparatus, identity and access, execution and egress, delivery, data and audit — built from `/version`, `/health`, `/github/app` and the ledger verification, with a next step on every row that is not the production posture | `hint:about:/posture` · `route:GET /version` · `vitest:ui/src/components/govuk.test.tsx::"every row that is not the production posture says what to do next, and the Delivery group reads from the API (J-FAC-10)"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` | met | |
| run-the-platform.handoff.13 | HANDOFF | The next stream starts from this one's output with nothing retyped: once the stack answers, Home's task 1 is the next action and every task's status is derived from the API, never kept on the client | `vitest:ui/src/screens/Home/HomePage.test.tsx::"derives the eight tasks from the API and counts the completed ones"` · `code:ui/src/screens/Home/HomePage.tsx::HomePage` | met | |
| run-the-platform.measure.14 | MEASURE | The product shows this stream's own numbers: time from install to first green `/health`, how many go-live lines are proven, and how long an account recovery took | `route:GET /flow?repo=` · `test:tests/test_server_routes_flow.py::test_every_figure_carries_an_n_and_a_label` · `vitest:ui/src/components/FlowPanel.test.tsx::"reads a measured lead time at human scale, with its n, its range and the apparatus"` · `test:tests/test_server_routes_flow.py::test_a_recovery_is_timed_from_the_reset_to_the_next_sign_in` · `test:tests/test_server_routes_flow.py::test_the_accounts_are_counted_and_two_figures_are_not_captured` | partial | G-558 |
| run-the-platform.automation.15 | AUTOMATION | No step here needs a person to do by hand what the product could do: a password reset, a deactivation and a reactivation are API and CLI only — Settings offers create and role change — so a locked-out user is recovered on the host | `absent` | unmet | F23 |

## Gaps
- **G-580** — the product never names this stream · give Home's task list a preceding "Set up the deployment" group (or a Deployment task list) whose rows are the go-live lines, so the work before task 1 is visible · ui
- **G-581** — `DEPLOYMENT §8` (go-live) and `OPERATOR §9` (users) are bundled but linked from no screen · add the two `readMore` entries to `help.ts` for `/posture` and `/settings` · ui
- **G-582** — no walkthrough asserts the Deployment page's rows (07 runs axe only) and none walks an account recovery · add a tier-1 spec that reads three posture rows and one that resets a password and signs in again · ui
- **G-583** — the operator-only acts are listed in DEPLOYMENT §8 and SECURITY §5, not on the screen a review board reads · add a "not done by this product" summary list to `/posture` naming each act and its guide anchor · ui
- **G-584** — nothing reads the go-live checklist against the deployment's own probes · serve a checklist view whose lines are the probes and settings the product already knows (image digest, `local_auth_enabled`, executor, bootstrap admin), each `proven` / `operator` / `not yet` · server
- **G-558** — the deployment's own flow has no start and no checklist reading: nothing stamps the install or the first green `/health`, and nothing reads the go-live checklist against the probes (the half G-584 names), so the platform stream shows account recoveries and states both halves as not captured · stamp both moments as system events at startup and serve the checklist from the deployment's own probes · deploy
