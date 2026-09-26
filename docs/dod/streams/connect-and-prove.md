---
id: dod.stream.connect-and-prove
level: stream
name: Connect & prove — repository → probe → oracle reproducible → controls
scope: connect-and-prove
parent: dod.product
children: [dod.journey.connect-a-repository, dod.journey.prove-the-instrument]
persons: [operator, admin, viewer, approver]
owner: server
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Connect & prove — repository → probe → oracle reproducible → controls

**Purpose.** Turn one of the enterprise's repositories into an instrument that can be trusted
to judge a build: the toolchain runs, the corpus reproduces, the repository's own tests are
strong enough to catch a wrong answer, and the bench proves it catches itself cheating.

**Entry → exit.** A developer registers a repository through the GitHub App or by URL →
a repository whose probe is green, whose mined tasks are gold-clean, whose tasks carry
task-level oracle strengths, and whose negative-controls report reads `passed` with 0 escapes
— the precondition under which anything measured afterwards is evidence.

**Non-goals.** Nothing here measures a builder or spends money (steps 1–4 of the guide are
£0). It does not fix the repository's own test suite, propose configuration edits, or connect
anything but GitHub — GitLab and Azure DevOps connectors are named and not built (DL-041, F21).

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| connect-and-prove.purpose.1 | PURPOSE | The stream is named where a person meets it: Home's tasks 1–4 read "Connect GitHub", "Choose a repository", "Confirm its shape" and "Prove the instrument (£0)", and the Connection walk names the stage the repository has reached and the next action | `hint:about:/home` · `hint:about:/connect` · `code:ui/src/screens/Connect/connection.ts::stagesFor` | met | |
| connect-and-prove.entry-exit.2 | ENTRY-EXIT | A person arriving with nothing is told where to start, and a repository already part-way through resumes at the stage it is at rather than at the beginning: a fresh repository is waiting on the probe with the later stages blocked | `vitest:ui/src/screens/Connect/connection.test.ts::"a fresh repository is registered and waiting on the probe"` · `hint:about:/connect` | met | |
| connect-and-prove.truth.3 | TRUTH | Every count in the stream is the run's own and a failure reads as a failure: probe green/failing/duration, mine found/examined/target, oracle strength per task, controls k of N with escapes — and a failed controls report is failed, not done, and blocks the measurement | `vitest:ui/src/screens/Connect/connection.test.ts::"a failed controls report is failed (not done) and blocks the measurement"` · `route:GET /oracle/{repo}/controls` · `test:tests/test_oracle_controls.py::test_hardcode_cheat_slipping_through_is_a_measured_escape` | met | |
| connect-and-prove.actions.4 | ACTIONS | Every action in the stream reports what it did on the screen that started it: "Probe now" opens the run's live log, and the repository page then shows the probe pill as OK with the runner summary | `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"Probe now"` · `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"back on the repo page the probe pill is OK with the runner summary"` · `route:POST /repos/{name}/probe` | met | |
| connect-and-prove.explanation.5 | EXPLANATION | A bundled guide explains the stream end to end — register, describe the shape, make the oracle reproducible, prove the instrument — in the order the screens ask for it | `doc:docs/ONBOARDING-A-REPO.md#step-1--register-the-repository-developer-30-minutes` · `doc:docs/ONBOARDING-A-REPO.md#step-2--make-the-oracle-reproducible-developer-the-real-work` · `doc:docs/ONBOARDING-A-REPO.md#step-3--prove-the-instrument-on-this-repository-operator-0` · `doc:docs/OPERATOR.md#20-connecting-and-configuring-a-repository-from-the-ui` | met | |
| connect-and-prove.evidence.6 | EVIDENCE | One walkthrough chain proves the whole stream on a live stack in CI: register and probe, mine, score the oracle, run the negative controls | `spec:ui/e2e/walkthrough/02-repo-onboard.spec.ts::"back on the repo page the probe pill is OK with the runner summary"` · `spec:ui/e2e/walkthrough/03-mine.spec.ts::"the repo Tasks tab lists"` · `spec:ui/e2e/walkthrough/04-oracle-and-controls.spec.ts::"an oracle run scores every mined task"` · `spec:ui/e2e/walkthrough/04-oracle-and-controls.spec.ts::"a controls run renders the seven negative controls"` · `ci:walkthrough` | met | |
| connect-and-prove.roles.7 | ROLES | Only an operator may register a repository or change its shape; a viewer reads the configuration, cannot edit it, and is told so rather than shown a control that fails | `spec:ui/e2e/walkthrough/repo-config.spec.ts::"a viewer reads the configuration but cannot edit it"` · `route:POST /repos` | met | |
| connect-and-prove.operations.8 | OPERATIONS | The platform team can see this stream's runs from outside the UI: every stage emits its events and the run counters, and `crb_runs_total` and `crb_sandbox_unavailable_total` meter them per kind and status | `test:tests/test_observability_metrics.py::test_worker_runs_total_and_sandbox_unavailable_after_harness_runs` · `route:GET /metrics` · `code:src/crb/server/worker.py::_run_probe` | met | |
| connect-and-prove.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; the Connection, repository and Oracle pages carry the keyboard, focus and axe criteria on their own artefacts |
| connect-and-prove.non-goals.10 | NON-GOALS | That this stream costs nothing is stated where the person decides to run it — the guide's step 3 and Home's task 4 both say £0, so no one waits for an approval that is not needed | `doc:docs/ONBOARDING-A-REPO.md#step-3--prove-the-instrument-on-this-repository-operator-0` · `hint:about:/home` | met | |
| connect-and-prove.trigger.11 | TRIGGER | What starts the stream is recorded by the product, not remembered by a person: registering a repository through an installation or by URL writes the repository row and its events with the actor who did it | `route:POST /repos` · `route:POST /github/installations/{id}/connect` · `test:tests/test_server_routes_repos.py::test_create_validates_and_records_event` · `test:tests/test_server_github_app.py::test_picker_lists_with_suggestions_and_connect_registers_a_linked_repo` | met | |
| connect-and-prove.outcome.12 | OUTCOME | The artefact of value is a proven instrument, served and readable: task-level oracle strengths and a negative-controls report with its verdict, escapes and constructible k of N, which every later route decision reads | `route:GET /oracle/{repo}` · `route:GET /oracle/{repo}/controls` · `code:src/crb/server/worker.py::_run_controls` · `code:src/crb/server/routes/oracle.py::latest_controls_verdict` | met | |
| connect-and-prove.handoff.13 | HANDOFF | The next stream starts from this one's output with nothing retyped: mined counts, an oracle report, a passed controls report and measured rows complete their stages, the Measure step unblocks itself, and the map routes under the same controls verdict | `vitest:ui/src/screens/Connect/connection.test.ts::"mined counts, an oracle report, a passed controls report and measured rows complete their stages"` · `code:src/crb/server/routes/oracle.py::latest_controls_verdict` | met | |
| connect-and-prove.measure.14 | MEASURE | The product shows this stream's own numbers: elapsed time from registration to a passed controls report, and the developer hours the guide calls "the real work" | `route:GET /flow?repo=` · `test:tests/test_server_routes_flow.py::test_every_figure_carries_an_n_and_a_label` · `vitest:ui/src/components/FlowPanel.test.tsx::"reads a measured lead time at human scale, with its n, its range and the apparatus"` · `test:tests/test_server_routes_flow.py::test_registration_to_the_first_passed_report_is_measured` | partial | G-556 |
| connect-and-prove.automation.15 | AUTOMATION | No step needs a person to do what the product could do: the six stages are sequenced from one act, and a repository whose gold target is not green is offered the `runner_opts` change the mine notes imply rather than leaving a developer to write it | `absent` | unmet | G-500 |

## Gaps
- **G-500** — nothing sequences the six stages and nothing proposes a reproducibility fix · queue the next £0 stage automatically when the previous one succeeds (opt-in per repository), and turn each `gold_note` into a named candidate config change the developer accepts or rejects · server
- **G-556** — the developer hours the guide calls "the real work" (making a repository's oracle reproducible) happen outside the product and nothing times them, so the connect stream shows its elapsed lead time and states that half as not captured · record the start and end of step 2 against the repository (an operator marks it, or the mine runs' span stands in) and serve it beside the elapsed time · server
