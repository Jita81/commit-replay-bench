---
id: dod.stream.learn
level: stream
name: Learn — outcomes, evolutions, oracle strengthening, cells → routing
scope: learn
parent: dod.product
children: [dod.journey.learn-and-strengthen]
persons: [operator, viewer, approver, admin]
owner: server
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Learn — outcomes, evolutions, oracle strengthening, cells → routing

**Purpose.** Turn what the instrument got wrong into work: a guard that stops refusing honest
commands, a test that stops letting wrong answers through, and a re-measurement that makes
stale cells current again.

**Entry → exit.** Rows accumulate — protocol refusals, cells held by a weak oracle or escaped
mutants, an apparatus bump, weak-oracle verdicts, merged and closed pull requests → three
reproducible artefacts a person accepts or refuses: a candidate guard-corpus line with its
provenance, a strengthening backlog whose items already pass the factory's readiness gate, and
an exact re-measurement plan with its cost.

**Non-goals.** The product proposes and never accepts: it does not edit the guard corpus, does
not freeze its own strengthening items, does not queue the re-measurement it priced, and never
writes a test on nobody's authority. Cross-organisation abstract learning is designed and
parked until a second organisation asks.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| stream-learn.purpose.1 | PURPOSE | The stream is named where a person meets it: Learn is a nav item and the page names its three reports in plain phrases, defining their words inline | `hint:about:/learn` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"names the three reports in plain phrases"` · `code:ui/src/screens/Learn/LearnPage.tsx::LearnPage` | met | |
| stream-learn.entry-exit.2 | ENTRY-EXIT | A person arrives from the nav and leaves with the artefact and the next action they can take here, on the page that showed it rather than as a command on the host | `hint:about:/learn` · `doc:docs/LEARNING-LOOP.md#4-using-it` | partial | G-532 |
| stream-learn.truth.3 | TRUTH | Every derivation is pure and reproducible — the same rows give byte-identical output — and no verdict is invented: every refusal group is `unsure` until a named person decides | `test:tests/test_learn.py::test_deterministic_and_order_independent` · `test:tests/test_learn.py::test_never_auto_accepts` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` | met | |
| stream-learn.actions.4 | ACTIONS | Every action the stream offers reports its outcome on the screen that offered it: accepting a corpus line, freezing a strengthening item and queueing a re-measurement each have a control beside the report and a success state that names what was written | `absent` | unmet | G-532 |
| stream-learn.explanation.5 | EXPLANATION | A bundled guide explains the stream end to end — what loops mechanically, what the product derives, what a person still does and why that is deliberate | `doc:docs/LEARNING-LOOP.md#1-what-loops-mechanically-today` · `doc:docs/LEARNING-LOOP.md#2-what-crbcorelearn-adds` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` | met | |
| stream-learn.evidence.6 | EVIDENCE | The stream is proven end to end, not only in parts: unit and route tests pin the three derivations and the CLI round trip, and one walkthrough walks a refusal from a run through the report to an accepted corpus line on a live stack | `test:tests/test_learn.py::test_items_pass_the_factory_dor_gate_as_build` · `test:tests/test_server_routes_learn.py::test_strengthen_uses_the_controls_verdict_and_the_oracle_scores` · `test:tests/test_cli_learn.py::test_refusals_apply_refuses_unnamed_or_unknown` | partial | G-533 |
| stream-learn.roles.7 | ROLES | Who may act is enforced at both layers, and who decided is recorded: the three reads need `viewer` at the API, the Learn nav entry is operator-gated in the UI, and applying a triage refuses a decisions file that names no person | `test:tests/test_server_routes_learn.py::test_rbac` · `code:ui/src/components/Layout.tsx::INSTRUMENT` · `test:tests/test_cli_learn.py::test_refusals_apply_refuses_unnamed_or_unknown` · `code:src/crb/core/learn.py::apply_triage` | met | |
| stream-learn.operations.8 | OPERATIONS | The platform team can find and watch this stream from outside the UI: `docs/API.md` lists the three `/learn` routes with their shapes and role, `/metrics` serves a counter per report, and OPERATOR says when to read each one | `absent` | unmet | G-534 |
| stream-learn.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; the Learn page carries the keyboard, focus and axe criteria on its own artefact |
| stream-learn.non-goals.10 | NON-GOALS | What the product will not do is written where the reader meets it: it proposes and never accepts, and the guide says why an editor of its own oracle is what belt 1 exists to prevent | `doc:docs/LEARNING-LOOP.md#6-what-this-is-not-yet` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` · `dl:DL-044` | met | |
| stream-learn.trigger.11 | TRIGGER | The product notices what should start this stream and raises it to a person: the reports are recomputed at read, so they are current whenever opened, and a held cell, a recurring refusal shape after an accepted prevention and a stale apparatus each become a Decisions row | `code:src/crb/core/learn.py::strengthening_backlog` · `code:src/crb/core/learn.py::triage_refusals` | partial | G-535 |
| stream-learn.outcome.12 | OUTCOME | The artefacts of value are three and each is complete enough to act on: a candidate corpus line with redacted provenance, a strengthening backlog whose items pass the factory's readiness gate as `build`, and a re-measurement plan with exact run bodies and a cost marked known or not | `code:src/crb/core/learn.py::triage_refusals` · `code:src/crb/core/learn.py::remeasure_plan` · `test:tests/test_learn.py::test_items_pass_the_factory_dor_gate_as_build` | met | |
| stream-learn.handoff.13 | HANDOFF | The next stream starts from this one's output without retyping: the strengthening backlog is registered and the re-measurement plan queued from the report itself, and a route consumes merge outcomes and human review verdicts | `absent` | unmet | G-532 |
| stream-learn.measure.14 | MEASURE | The product shows this stream's own numbers: the guard's false-positive rate over time, how often a defect class recurs after a prevention was accepted, and the time from a finding to its re-measurement | `absent` | unmet | G-536 |
| stream-learn.automation.15 | AUTOMATION | No step needs a person to do what the product could do: the three decisions stay human by design, and each handoff around them is a button beside the report rather than a command on the host | `absent` | unmet | G-532 |

## Gaps
- **G-532** — the Learn page is read-only: `refusals --apply` is CLI only, the strengthening backlog must be pasted into `POST /factory/{repo}/backlog`, and the re-measurement bodies must be posted by hand · add the three write paths behind the same named-person decision the CLI already requires (accept a line, register the items, queue the plan) · server
- **G-533** — no walkthrough proves the stream on a live stack: the Learn page is only rendered by 11-screens · add a tier-1 spec that makes a refusal, reads the group on the page and accepts a line · ui
- **G-534** — the `/learn` endpoints are in no guide and no series: `docs/API.md` lists none of them and nothing meters the reports · add the rows to `docs/API.md` and a counter per report · docs
- **G-535** — nothing raises the stream's own findings to a person: a held cell, a recurring refusal shape after a prevention (F33) and a stale apparatus appear only when someone opens Learn, and merge outcomes and review verdicts feed no clause of the routing rule · make each a Decisions row and state whether outcomes may ever route · server
- **G-536** — no measure of whether learning worked: the guard's false-positive rate over time, defect-class recurrence and finding → prevention → re-measurement time are all underived · derive them from the refusal groups and corpus provenance already stored and show them on the Learn page · server
