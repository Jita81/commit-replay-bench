---
id: dod.stream.decide-and-license
level: stream
name: Decide & license — decisions inbox → sign-off → licence sentence
scope: decide-and-license
parent: dod.product
children: [dod.journey.sign-off-a-cell]
persons: [approver, operator, viewer, admin]
owner: server
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Decide & license — decisions inbox → sign-off → licence sentence

**Purpose.** Put every point where a human act is due in one place, and turn a measured cell
into a sentence a named second person is willing to put their name to.

**Entry → exit.** A cell routes `deliver` with no active sign-off (or a cell is held for a
human, or a factory item has an unsigned structural gap) → a hash-chained sign-off record
whose every field is the licence sentence, or a refusal listing every failing clause, recorded
as an event.

**Non-goals.** A sign-off does not change the route and does not promise anything about the
next change: it lifts the verification tier of a cell that the evidence already licensed. The
product does not decide; it refuses, and it never creates the second person for you.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| decide-and-license.purpose.1 | PURPOSE | The stream is named where a person meets it: Decisions is a nav item for every role, its rows say what act is due and on whom, and Home's task 7 reads "Invite an approver" | `hint:about:/decisions` · `vitest:ui/src/screens/Decisions/decisions.test.ts::"a deliver cell without an active sign-off is a sign-off due for the approver, deep-linked"` · `hint:about:/home` | met | |
| decide-and-license.entry-exit.2 | ENTRY-EXIT | The approver arrives on a row deep-linked to the cell and leaves with either a licence sentence or a refusal naming every clause that failed — never a blank form and never a silent failure | `hint:about:/signoff` · `route:GET /signoffs/policy` · `spec:ui/e2e/walkthrough/08-signoff.spec.ts::"thin cell is REFUSED before the approver tries: every clause"` | met | |
| decide-and-license.truth.3 | TRUTH | The record stamps the whole decision the approver saw, under the hash: n, point, the Wilson lower bound, false-Q1, the measured oracle strength, the controls verdict with k of N and escapes, the route and its reason code, the policy version and thresholds, the attested row and the signing account's kind | `code:src/crb/core/signoff.py::evaluate_signoff` · `test:tests/test_signoff.py::test_record_roundtrip_and_hash_v3` · `doc:docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2` | met | |
| decide-and-license.actions.4 | ACTIONS | Every act in the stream says what it did and what it did not: a refusal is recorded as an event and writes nothing, a revocation is a new row carrying its reason, and the preview shows the refusals before the approver tries | `route:POST /signoffs` · `route:POST /signoffs/{id}/revoke` · `test:tests/test_server_routes_signoffs.py::test_revoke_appends_and_hides` · `test:tests/test_server_routes_signoffs.py::test_revoke_needs_a_reason_at_the_api_not_just_in_the_ui` · `test:tests/test_server_routes_signoffs.py::test_preview_of_the_seeded_deliver_cell_lists_the_refusals` · `dl:DL-043` | met | |
| decide-and-license.explanation.5 | EXPLANATION | A bundled guide explains the stream end to end — what to do before anyone signs, how to sign, and exactly what a signed cell may be claimed to mean | `doc:docs/ONBOARDING-A-REPO.md#step-6-before-anyone-signs-anything` · `doc:docs/ONBOARDING-A-REPO.md#step-7-sign-off-approver` · `doc:docs/OPERATOR.md#5-sign-off` · `doc:docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2` | met | |
| decide-and-license.evidence.6 | EVIDENCE | One walkthrough chain proves the whole stream on a live stack in CI: a thin cell refused with every clause, a policy-satisfying cell seeded, the operator who queued the runs refused by the two-person rule, and a second person signing with an attestation | `spec:ui/e2e/walkthrough/08-signoff.spec.ts::"the admin who queued the runs is refused by the two-person rule (same_actor)"` · `spec:ui/e2e/walkthrough/08-signoff.spec.ts::"a second person (the approver) signs the deliver cell with an attestation"` · `spec:ui/e2e/walkthrough/09-review.spec.ts::"a Defect review is recorded against the row, anchored to the loaded patch"` · `ci:walkthrough` | met | |
| decide-and-license.roles.7 | ROLES | The right person is the only person who can: signing needs the approver role, and the two-person rule refuses an approver who produced the evidence they would sign — at write and in the preview, with no knob that relaxes it | `code:src/crb/core/signoff.py::same_actor_refusal` · `adr:0016` · `dl:DL-047` | met | |
| decide-and-license.operations.8 | OPERATIONS | The platform team can see what is waiting and for how long: the nav badge counts what is due, every write and refusal is an event, and the moment a decision became due is recorded, so the wait and the backlog age can be read | `code:src/crb/core/signoff.py::apply_signoffs` · `route:GET /signoffs/{id}` | partial | G-516 |
| decide-and-license.accessibility.9 | ACCESSIBILITY | A stream-level artefact (a summary, a status board) is keyboard-reachable and WCAG 2.1 AA clean at 375 and 1280 px | `absent` | n/a | the stream renders no artefact of its own; the Decisions and Sign-off pages carry the keyboard, focus and axe criteria on their own artefacts |
| decide-and-license.non-goals.10 | NON-GOALS | What a signed cell does not mean is written where the reader meets it: the licence sentence lifts the verification tier and never the route, and the bundled policy states the limit in the same words | `doc:docs/EVIDENCE-AND-CLAIMS.md#6a-what-a-signed-cell-may-be-claimed-to-mean-signoff-policyv2` · `adr:0015` | met | |
| decide-and-license.trigger.11 | TRIGGER | The product notices the trigger without a person hunting for it: a cell that routes `deliver` with no active sign-off, a cell held for a human and an unsigned structural gap each become a row, and the shell's badge counts them on every screen | `vitest:ui/src/screens/Decisions/decisions.test.ts::"a deliver cell without an active sign-off is a sign-off due for the approver, deep-linked"` · `vitest:ui/src/screens/Decisions/decisions.test.ts::"factory items: unsigned gaps, rework verdicts and a withheld delivery each become a row"` | met | |
| decide-and-license.outcome.12 | OUTCOME | The artefact of value is a hash-chained sign-off record whose fields are the licence sentence, overlaid at read so that a later false-Q1 row invalidates it and an apparatus bump makes it stale | `code:src/crb/core/signoff.py::evaluate_signoff` · `code:src/crb/core/signoff.py::apply_signoffs` · `adr:0015` | met | |
| decide-and-license.handoff.13 | HANDOFF | The next stream starts from this one's output: a signed structural gap stops blocking readiness without being retyped, and a cell's sign-off licenses the delivery — the factory's gate reads the sign-off as well as the route, so a cell routing `deliver` with no human sign-off does not open a pull request | `test:tests/test_factory_readiness.py::test_signoff_fills_structural_gap_and_is_ledgered` · `test:tests/test_factory_loop.py::test_route_gate_withholds_delivery_when_the_cell_does_not_route_deliver` | partial | G-517 |
| decide-and-license.measure.14 | MEASURE | The product shows this stream's own numbers: time from a cell routing `deliver` to a signature, and the reviewer minutes each decision cost | `absent` | unmet | G-925 |
| decide-and-license.automation.15 | AUTOMATION | No step needs a person to do what the product could do: a deployment with one account can sign nothing, and the product tells the admin to invite an approver but cannot create, invite or notify that second person | `absent` | unmet | G-518 |

## Gaps
- **G-516** — the inbox is derived at read from three APIs: no persistence, no "due since", no assignment, no SLA and no notification, so a decision exists only while someone has the page open · record the moment a row first becomes due and serve its age with the row · server
- **G-517** — the delivery gate is the route, not the sign-off: `loop` reads `route == deliver` only, so an unsigned cell can license a pull request · decide the question in an ADR and, if signing is to be a precondition, add the clause to the gate with a stated default · factory
- **G-925** — the product folds no lead time and no spend out of the events it already stores, so backlog → merge and cost per human-verified change cannot be shown (backlog F20; the merge outcome is already recorded by `sync_outcomes`, and B-9's open half is the reviewer-minutes capture) · derive the durations and the spend per stream from the runs and events already stored, capture reviewer minutes on `POST /reviews`, and serve a Flow view with one endpoint per stream · server
- **G-518** — inviting the second person is a manual out-of-band act: Settings creates a local account but nothing invites, emails or tracks that the approver ever signed in · add an invitation with a one-time link and show the deployment's two-person readiness on Home's task 7 · server
