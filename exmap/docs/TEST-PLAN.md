# Example Map Live — Test plan

Every unit and e2e test, by module. Section numbers refer to `DESIGN.md`. Gates: `npm run check` (typecheck + `vitest run` + build) and `npm run e2e` (build + Playwright, `workers: 1`); both must pass before any commit. Unit tests never touch the network; the e2e never depends on the Hugging Face Hub.

Conventions: one `it` per numbered case; a case that names several assertions is one test with several `expect`s; "scenario" = `tests/unit/core/fixtures.ts#scenario()` (§5.10); "fixture" = `src/web/public/replay/conversation.v1.json` (§14); `testCtx()` = counter ids + a fixed clock stepping 1 s.

## 1. Core (`tests/unit/core/`, node project)

### `types.test-d.ts` (compile-time, run by `tsc --noEmit` in `npm run check`)
0. `EventBody` keeps every payload's fields (`{ type: "proposal.made", proposal, effects, id, seq, at, session_id, batch_id, prev_hash }` compiles); `chainEvent(prev, { type: "proposal.applied", … }, sha)` compiles and is assignable to `ExmapEvent`; `CardRecord` for an example keeps `rule_id`; `z.infer<typeof ProposalSchema>` and `ClassifierProposal` are mutually assignable; `REFUSAL` is `{ readonly [K in RefusalCode]: K }`.

### `canonical.test.ts`, `chain.test.ts`
1. `canonicalJson` sorts nested keys, drops `undefined`, emits no whitespace — `{b:1,a:{d:undefined,c:[2,{z:1,y:2}]}}` → `{"a":{"c":[2,{"y":2,"z":1}]},"b":1}`.
2. `canonicalJson` refuses `NaN`/`Infinity`/bigint/functions with `CanonicalError`.
3. The sha256 adapter matches the vectors `""` and `"abc"` (§5); the same file runs against the server (`node:crypto`) and browser (`@noble/hashes`) adapters.
4. The genesis event has `prev_hash ""`, `seq 1`, `hash === sha256(canonicalJson(body sans hash))`, `batch_id === id`.
5. `verifyChain` accepts the 60-event scenario: `ok`, `count === 60`, `head === last.hash`.
6. `verifyChain` detects payload tampering — one card's text changed inside event 7's effects → `HASH_MISMATCH` at seq 7.
7. `verifyChain` detects a removed event — delete event 5 → `PREV_HASH_MISMATCH`/`SEQ_MISMATCH` at seq 6; never repaired.
8. `verifyChain` detects reordering — swap events 3 and 4 → failure at seq 3.
9. `verifyChain` detects a foreign session's event spliced in → `SESSION_MISMATCH`.
10. `replay` refuses a revision stamp the reducer does not reproduce — alter `revision.hash` on the last revision-creating event and recompute its hash → chain ok, `REVISION_MISMATCH` at its seq; variant: alter an earlier one and re-chain every later event → same.

### `revision.test.ts`
11. The revision is `GENESIS_REVISION_HASH` for an empty map (`8e97e07b…9675`).
12. The revision does not change with timestamps, utterances, classifications or export options — same commands with a different clock plus extra `utterance.record` / `classification.record` / `export.options_set` → identical hash.
13. The revision changes when a rule's text changes and reverts to the earlier hash after undo.
14. The revision ignores confirmation, `needs_review`, acceptance and supersedes links.
15. The revision excludes rejected, superseded and proposed cards — after remove/replace the hash equals a map that never had them.

### `reduce.test.ts`, `replay.test.ts`
16. `reduce` never mutates its input (deep-frozen state; every event type).
17. `reduce` is total for every event type — one standalone event of each of the 13 types naming unknown ids reduces without throwing, sets `head`, applies effects, pushes revisions, leaves unknown proposals/clarifications/signoffs untouched (§5.3 totality rule).
18. History is appended only on version bumps — confirm (no bump) vs update (bump); a replace by existing card bumps neither card's version.
19. `replay` of the scenario equals folding `reduce`; `reduce.ts` imports neither `chain.ts` nor `revision.ts` (asserted on the module's import list).
20. No reduced state ever contains a `proposed` card; a create's `proposal.made` does carry a `proposed` effect.

### `apply.cards.test.ts`
21. `card.create` story → `proposed` in `proposal.made`, `applied` in `proposal.applied`; `version 1`; `created === changed`; `restored_by === null`.
22. A second live story is refused `STORY_ALREADY_EXISTS`; no events; `nextId` not called.
23. An example with a non-live or non-rule link is refused — `CARD_NOT_LIVE` for a removed rule; `LINK_KIND_MISMATCH` for a question id.
24. `card.update` bumps version, resets confirmed → applied, clears confirmation, keeps history, sets `restored_by` null.
25. `card.update` with identical content → `NO_CHANGE`; a disallowed patch key → `PATCH_FIELD_NOT_ALLOWED`; an empty patch → `PATCH_EMPTY`.
26. A rule update flags linked live examples `needs_review` and leaves unlinked ones alone; confirming the rule does not clear them; confirming the example does.
27. `card.remove` → rejected/removed, keeps history and provenance; removing a rule flags its examples `rule_removed` and leaves the dangling `rule_id`.
28. `card.replace` by text supersedes the old card, links `supersedes`/`superseded_by`, re-links examples (`rule_replaced`) and questions.
29. `card.replace` by `replacement_card_id` keeps the replacement's id, provenance, confirmation and version; the old card `superseded_by` it; examples re-linked; a replacement of a different kind → `KIND_MISMATCH`; the target itself → `REPLACEMENT_INVALID`; a replacement that already supersedes → `REPLACEMENT_INVALID`; a non-live replacement → `CARD_NOT_LIVE`.
30. `definition.refine` upserts by term and is a content change (flags examples of a rule); a second identical refine → `NO_CHANGE`; empty term → `INVALID_DEFINITION`.

### `apply.review.test.ts`
31. `confirm` sets `confirmed` with `confirmation.version` and `confirmation.by`; marks the producing proposal confirmed; an already-confirmed unflagged card → `NOTHING_TO_CONFIRM`; a mixed list confirms only the changed ones; `by` of a human proposal is `{ provider: "human", actor: "Ana", confidence: 1 }` and of a voice confirm copies the AI stamp.
32. `confirms_proposal_ids` is filtered by affected cards — replace a rule with two examples: confirming only the replacement card does not confirm the replace proposal; confirming the two examples afterwards does.
33. `confirm` by `proposal_ids` reviews an act — an AI `card.remove`: `confirm { card_ids: [], proposal_ids: [p] }` → `proposal.confirmed` with `confirms_proposal_ids: [p]`, no effects, status `confirmed`, `unreviewedActs` empty; naming a `card.create` → `PROPOSAL_NOT_CONFIRMABLE`; a `clarifying` one → `PROPOSAL_NOT_CONFIRMABLE`; both lists empty → `EMPTY_TARGET`; an already confirmed act only → `NOTHING_TO_CONFIRM`.
34. `interpretation.reject` of a create → card rejected/interpretation_rejected; of an update → previous content, status, confirmation and `changed` restored at version+1 with `restored_by` = the rejecting proposal; event `proposal.rejected` with a new revision; of a replace (either form) → the old card live again and the replacement's `supersedes` null.
35. `interpretation.reject` refuses a confirmed, pending or already-rejected proposal (`PROPOSAL_NOT_REJECTABLE`) and a confirm proposal (`PROPOSAL_KIND_NOT_REJECTABLE`); rejecting an `undo` succeeds and restores the pre-undo hash; rejecting an `interpretation.reject` re-applies the rejected update.
36. `interpretation.reject` refuses when a later proposal touched an affected card (`REJECT_NOT_LATEST`); a rule update whose flagged example was confirmed in between is rejectable and the example keeps its confirmation with `needs_review` restored to null.
37. Shape and intent refusals — mismatched intent → `INTENT_OPERATION_MISMATCH`; duplicate proposal id → `DUPLICATE_ID`; unknown utterance id → `UTTERANCE_UNKNOWN`; an extra key on a proposal, a missing `is_local` on an utterance, an unknown command kind → `BAD_SHAPE` naming the path; `confidence: 0.333` → `INVALID_CONFIDENCE` (never rounded); `score: 1.5` → `INVALID_CONFIDENCE`.
38. The status machine is closed — property test over the scenario: every observed transition ∈ {proposed→applied (within one batch), applied→confirmed, confirmed→applied, applied→rejected, confirmed→rejected, applied→superseded, confirmed→superseded, rejected→applied, rejected→confirmed, superseded→applied, superseded→confirmed}; `rejected`/`superseded` are left only through `proposal.rejected` or `undo.applied`.
39. `restored_by` and `changed` — after a reject that restores an earlier version, `changed.proposal_id` is the original author and `restored_by.proposal_id` the reject; a following `card.update` clears `restored_by`.

### `apply.batch.test.ts`
40. `proposal.propose` with two proposals is one batch — a reject prefix + a remove → `[made₁, rejected, made₂, applied]`, all with `batch_id === made₁.id`; two revisions with that `batch_id`; `undoTarget(state, 1)` is the revision before both.
41. A batch is all or nothing — proposal 2 refused (`CARD_NOT_LIVE`) → no events, `nextId` not called, `detail` starts `proposal 2 of 2`; proposal 2 is validated against the state after proposal 1 (create then update of the created card succeeds in one batch).
42. `signoff.invalidated` is appended once per batch, after the first revision-creating event.

### `clarification.test.ts`
43. `needs_clarification` yields `proposal.made` + `clarification.asked`, no card, no revision; shape refusals: both `template` and `pending_operation` → `CLARIFICATION_SHAPE`; candidates with a `pending_operation` → `CLARIFICATION_SHAPE`; a `card.create` template of kind rule → `CLARIFICATION_SHAPE`; a `pending_operation` naming a non-live card → `CARD_NOT_LIVE` at ask time; empty `question` → `CLARIFICATION_QUESTION_REQUIRED`.
44. Answering with a candidate applies the resolved operation in the same batch — `[clarification.answered, proposal.made, proposal.applied]`; the resolved proposal keeps the asking stamp (`provider: "rules.v1"`, `fallback_from` preserved) with `actor: "Ana"`, `confidence 1`, `resolves_clarification_id`; the clarification is `answered` with `resolved_by_proposal_id`; `nextId("prop")` called exactly once, after validation (a refused candidate calls it zero times).
45. Answering `yes` applies the pending operation — a confirm_intent removal → the same event shape, the card rejected/removed, `actor` set so `unreviewedActs` is empty; `yes` without `pending_operation` → `CLARIFICATION_NO_OPERATION`; `yes` after the target was removed → `CARD_NOT_LIVE` and nothing appended.
46. An amendment template resolves per card — `{ patch: { text: "…" }, amendment: { from: "two hours", to: "24 hours", scope: null, append: "Make that 24 hours." } }` with a card containing "two hours" → substituted; with a card that does not → `card.text + " Amendment: Make that 24 hours."`; `from: null, to: ""` → the append path.
47. Answering with text keeps it open; a later proposal citing the clarification resolves it; a second citing proposal → `CLARIFICATION_NOT_AWAITING_PROPOSAL`.
48. A text answer with no resolver can still be answered by candidate, yes or dismiss; two text answers in a row → `text_answers.length === 2`, still open; dismiss → check 3 passes.
49. Dismiss closes it and marks the asking proposal dismissed; answering a dismissed or resolved one → `CLARIFICATION_NOT_ANSWERABLE`; candidate without template → `CLARIFICATION_NO_TEMPLATE`; a proposal citing a dismissed clarification → `CLARIFICATION_NOT_AWAITING_PROPOSAL`; empty `actor` → `ACTOR_REQUIRED`; empty dismiss reason → `REASON_REQUIRED`.
50. A reject template resolves to the card's authoring proposal — candidate answer on an `interpretation.reject` template → `operation.proposal_id === cards[card].changed.proposal_id`.

### `classification.test.ts`
51. `classification.record` appends `utterance.classified` and the counts follow — intent `none` → `counts.classified` +1, `actionable` unchanged; with `proposal_ids` citing the utterance → `actionable` +1; `fallback_from: "claude"` → `fallbacks` +1; `error` with `proposal_ids: []` → `classifier_errors` +1; `error` with proposal ids → `CLASSIFICATION_PROPOSAL_MISMATCH`; a proposal id not citing the utterance → `CLASSIFICATION_PROPOSAL_MISMATCH`; never substantive, never invalidates.
52. `heard_intent` — `{ intent: "none", heard_intent: "confirm" }` is stored and read back by `select.classificationsOf`; `{ intent: "add", heard_intent: "confirm" }` → `BAD_SHAPE`.

### `apply.undo.test.ts`
53. `undo(null)` restores the previous step; the new revision hash equals the target's; statuses match the target snapshot; restored cards keep their old `changed` and carry `restored_by` = the undo proposal.
54. Cards created after the target become rejected/undone; a card removed since is live again; a card superseded since is live again (superseded→applied).
55. Undo of the undo redoes — the hash returns to the pre-undo value; `currentRevision.cause === "undo.applied"` before the redo.
56. `undoTarget` counts batches, not revisions — after a two-revision batch `undoTarget(state, 1)` is before both; `undoTarget(state, 2)` skips the batch before that; more steps than batches → null and `undo { null }` → `UNDO_NO_EARLIER_REVISION`.
57. Undo refusals — fresh map → `UNDO_NO_EARLIER_REVISION`; seq ≥ current → `UNDO_TARGET_IS_CURRENT` / `UNDO_TARGET_OUT_OF_RANGE`; a target with the current hash → `NO_CHANGE`.

### `dod.test.ts`, `signoff.test.ts`
58. `dodReport` names failing ids — an unconfirmed rule, a flagged example, a dangling example link, an unanswered question, an open clarification, an unreviewed AI removal each fail exactly their check with the id in `details`; a voice-confirmed rule's detail reads `confirmed by voice (rules.v1, 0.5, …)` and with `{ requireHumanConfirm: true }` that rule fails check 1.
59. An AI removal, undo or reject blocks check 3 until confirmed by proposal id or rejected; a human removal (`actor` set) does not; a removal resolved from a clarification by a person does not.
60. An AI-recorded answer does not resolve a question until the card is confirmed.
61. Accepting a question resolves check 4 and the details say "accepted outstanding", never "answered"; accepting an answered or accepted question → `QUESTION_ALREADY_RESOLVED`; empty reason → `REASON_REQUIRED`.
62. Sign-off is refused with the failing checks — `SIGNOFF_DOD_FAILED` carries `checks`; no events.
63. `statusLabel` never returns "rejected" — every rejected card in the scenario labels as `removed` / `interpretation rejected` / `undone`.
64. Sign-off requires the exact sentence and a reviewer name — `SIGNOFF_CONFIRMATION_TEXT_MISMATCH` / `SIGNOFF_REVIEWER_REQUIRED`.
65. Sign-off with a stale revision hash → `SIGNOFF_STALE_REVISION`.
66. Sign-off records reviewer, revision stamp, evidence head and the five checks; `isHumanVerified` becomes true.
67. A later content change emits `signoff.invalidated` in the same batch and `isHumanVerified` becomes false — for update, remove, replace (both forms), refine, reject and undo.
68. A new utterance, a classification, a `proposal.made` alone, a confirm, a question acceptance or an export-options change does not invalidate.
69. A `needs_clarification` proposal after sign-off does not invalidate but makes `isHumanVerified` false; dismissing it makes it true again without a new sign-off; the same for an AI removal applied-then-rejected (false until the reject act is reviewed).
70. Re-sign-off after invalidation succeeds; the old sign-off stays `invalidated` with `by_event_id`; a second sign-off on the same revision → `SIGNOFF_ALREADY_ACTIVE`.

### `apply.export-options.test.ts`, `select.test.ts`
71. `export.options_set` appends one event with `seq` 1 then 2, `at` from the clock, `by` from the input; `select.exportOptions(state)` is the last; `state.export_options` holds both; not substantive, never invalidates; `kind: "ops"` → `INVALID_ENUM`; a slot `"1bad"` → `BAD_SHAPE`; empty fact text → `EMPTY_TEXT`; 41 facts → `BAD_SHAPE`; empty `by` → `ACTOR_REQUIRED`; empty `capability_class` → `EMPTY_TEXT`.
72. `select.lastAppliedProposal` — default returns the latest `applied` AI proposal and skips human ones; `{ statuses: ["applied", "confirmed"] }` returns a confirmed one; `select.isRejectable` is false for a confirmed proposal, a confirm proposal, a human proposal and a proposal whose card was updated since, true otherwise; `select.counts` fields equal hand-counted values over the scenario.
73. `apply` is atomic — every refusal returns no events, leaves the returned state identical and calls `nextId` zero times; every success returns `state` deep-equal to `replay(prior + new).state`.

## 2. Classifier (`tests/unit/classifier/`, node project, no network)

`helpers.ts`: `card(id, kind, text, { seq, last_utterance_id, last_speaker, links, answer, proposal_id, status })`, `utt(id, text, { speaker, lane })`, `input({ … })` with defaults (`recent: []`, `cards: [story]`, refs null), `expectOp(p, op)`, `mintIds()`.

### `normalize.test.ts`, `referents.test.ts`
1. `twenty-four hours` → `24 hours` with span `twenty-four hours`; `don't` → `do not`; `that's` → `that is`; `walk-in` → `walk in` with `originalSpan` `walk-in`; sentence split on `.` `?` `;` `:`.
2. `stripDiscourse`: `Right, so is …` → `is …`; `Right.` kept; `Yes, …` kept; `Got it.` dropped; at most three markers removed.
3. `contentTokens` / `tokenMatch`: `cancellation` ~ `cancel`; `GPs` ~ `gp`; `appointments` ~ `appointment`.
4. `parseReferent`: `that example` → kind example; `the GP one` → named "gp"; `the example about dentists` → example, named "dentists"; `that limit` → paraphrase "limit"; `the GP window` → paraphrase "gp window"; `make that 24 hours` → bare; `change it to` → bare; `use this example instead` → null (P2 excluded); `it is refused` → null; `the 24 hour rule` → rule, named "24 hour".
5. `maskReferents`: `delete that example, it duplicates the gp one` → `delete <ref>, it duplicates <ref>`.
6. `resolveReferent` degenerate cases: empty pool → none; one card → resolved "the only"; a paraphrase miss on a single card → resolved; a named miss on a single card → ambiguous with one candidate → `askTarget` → confirm_intent.

### `rules-v1.test.ts` (one `it` per row; contexts name cards `R1`, `E1`, `Q1` with speaker and touching utterance)
| # | input (text; context) | expect |
|---|---|---|
| 1 | `Right, let's start with how cancellation works today.` | none, heard_intent null, confidence 0, operations [] |
| 2 | `A patient should be able to cancel online, but not within two hours of their appointment.` | add rule 1.0, text verbatim |
| 3 | `Patients must confirm by email.` | add rule 1.0 (A2 + A3 without article) |
| 4 | `We also need an error case.` | add example (A1 + noun `case`) 0.5 |
| 5 | `We need a rule for weekends.` | add rule (noun `rule`) 0.5 |
| 6 | `For example, if a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused.` | add example 1.0, text without `For example, ` |
| 7 | `Given a nurse appointment at 10am, when the patient cancels at 8am, then it is allowed.` | add example 1.0, text verbatim |
| 8 | `Say a patient has two appointments on the same day.` | add example 1.0 |
| 9 | `What about appointments already in progress?`; last_proposal add rule R1 in window | add question 1.0, about_card_id R1 |
| 10 | `Do we know if nurses can cancel?` | add question 1.0 |
| 11 | `Is the limit the same for nurses?` | add question 0.5 (A5 only) |
| 12 | `I'm not sure, let's leave that open.` | none |
| 13 | `Change that limit to 24 hours.`; one rule R1 "…not within two hours…" | amend 1.0, `card.update { R1, patch: { text: …24 hours… }, amendment { from "two hours", to "24 hours", scope null } }` |
| 14 | `Actually, make that 24 hours for nurse appointments. Keep two hours for GPs.`; R1, last_proposal targets it | amend 1.0, scope `nurse appointments`, `patch.text_append` form |
| 15 | `Change that limit to 24 hours.`; R1(u3,Sam), R2(u4,Priya) in window; speaker Sam | choose_target, candidates `[R2, R1]`, pending `[card.update { "$choice", patch: { text_append } }]` |
| 16 | same; two rules, neither recent | choose_target with both |
| 17 | `Change it to 48 hours.`; no rules, one example | none, heard_intent amend, rationale `There is no rule to change.` |
| 18 | `Delete that example.`; E1(u3,Sam), E2(u4,Priya); speaker Sam; both in window | remove 0.5, choose_target `[E2, E1]` |
| 19 | same, speaker Priya | resolved E2 ("the example you just gave") |
| 20 | `Delete that example. It's not what I meant.`; one recent example | remove 0.5, resolved, reason `It's not what I meant.` |
| 21 | `We don't need that rule.`; one rule | remove 0.5 (D2) |
| 22 | `Delete the example about nurses.`; examples about nurse / GP | remove, resolved by named topic |
| 23 | `Delete the example about dentists.`; same | choose_target, why `no example about 'dentists'` |
| 24 | `Delete the example about dentists.`; one example E1 | confirm_intent `Did you mean to remove <E1 label>? (no example about 'dentists')` |
| 25 | `Delete that, it duplicates the GP one.`; E_gp3(u25,Priya), E_gp2(u24,Sam), last_proposal add E_gp3; speaker Priya | remove 1.0, target E_gp3, reason `it duplicates the GP one` |
| 26 | `Use this example instead.`; last_proposal add example E3 in window, older E1 | replace 1.0, `card.replace { card_id: E1, replacement: null, replacement_card_id: E3 }` |
| 27 | `Use this example instead of the old nurse one.`; E3 last, E_nurse, E_gp older | replace, target E_nurse by named topic |
| 28 | `Instead, if a GP cancels at 9am for a 10am slot it is refused.`; one example E1 in window | replace 0.5 with `replacement: { text: "If a GP cancels at 9am for a 10am slot it is refused." }`, target E1 |
| 29 | `Use this instead.`; no last_proposal | none, heard_intent replace, rationale mentions "no new content" |
| 30 | `By appointment I mean a booked slot, not a walk-in.` | clarify 1.0, `definition.refine { story, "appointment", "a booked slot, not a walk-in" }` |
| 31 | `When we say cut-off we mean the two-hour window.` | clarify, term `cut-off`, definition `the two-hour window` |
| 32 | `To clarify, nurses are clinicians too.` | clarify vs add → 0.25; no C2 capture → none, heard_intent clarify, rationale `…say 'By X I mean Y'` |
| 33 | `No, that's not what I said.`; last_rejectable P in window | reject 1.0, `interpretation.reject { P }` |
| 34 | same; last_rejectable null | none, heard_intent reject |
| 35 | same; P outside the window; index story + R1(Pa), E1(Pb), E2(Pc) | choose_target `Which interpretation is wrong?`, candidates `[E2, E1, R1]`, pending `[interpretation.reject { "$choice" }]` |
| 36 | same as 35 with only R1 (Pa) | confirm_intent `Did you mean to reject the interpretation that produced <R1 label>?` |
| 37 | `No, delete the nurse example.`; P in window, nurse example | remove, operations `[interpretation.reject { P }, card.remove { E_nurse }]`, 0.5 |
| 38 | `Yes, that's exactly right.`; last_proposal P (card.create, applied, [R1]) | confirm 1.0, `confirm { card_ids: [R1] }` |
| 39 | `Yes.`; last_proposal P (card.create) | confirm 0.5 |
| 40 | `Yes.`; last_proposal P (card.remove, applied) | confirm 0.5, `confirm { card_ids: [] }`, rationale `Confirmed the removal.`; same with an `undo` / `interpretation.reject` last proposal |
| 41 | `Yes.`; last_proposal P status confirmed | none, heard_intent confirm, rationale `already confirmed`; with a `confirm`-kind last proposal → none, `A confirmation cannot be confirmed.` |
| 42 | `Yes, but make it 24 hours.`; P (applied, card.create) targets R1 in window | amend with leading `confirm { [R1] }` then `card.update { R1 … }` |
| 43 | `Okay.`; no last_proposal | none, heard_intent confirm, `Nothing to confirm yet.` |
| 44 | `Go back to the previous version.` | undo 1.0, steps 1 |
| 45 | `Undo that.` | undo 0.5, steps 1 |
| 46 | `Undo the last two changes.` | undo 1.0, steps 2 |
| 47 | `Should we delete that example?`; one example E1 | remove 0.5 → damped 0.25 → confirm_intent `Did you mean to remove <E1 label>?` |
| 48 | `Yes, but not within two hours.`; P (card.create, [R1], in window) | prefix confirm `[R1]` + add rule 0.5, text `Not within two hours.` |
| 49 | `Actually, 24 hours.`; R1 with `two hours`, last_proposal targets it | amend 0.5 (M3), `from "two hours"`, `patch.text` replaced |
| 50 | `And a GP appointment at 10am cancelled at 9am is refused.`; last_proposal add example in window | add example 0.5 via A6 |
| 51 | same, last_proposal add rule | add rule via A6 |
| 52 | same, no last_proposal | none |
| 53 | `Change that limit to 24 hours.`; R1 (not in window), last_proposal = add question Q1 (in window) | amend 1.0 targeting R1 — the question is never updated |
| 54 | `The answer is yes, walk-ins count.`; one unanswered Q1 in window | amend 0.5 (M4), `card.update { Q1, patch: { answer: "yes, walk-ins count" }, amendment: null }` |
| 55 | `We need another example.` | add example 1.0 |
| 56 | `Delete the rule instead.`; one rule | remove 0.5 (trailing `instead` does not score replace) |
| 57 | determinism: classify the full fixture twice → deep-equal proposals; identical `JSON.stringify` |
| 58 | every proposal from rows 1–56 passes `ProposalSchema.parse` and `assertProposalInvariants` |

### `clarification.test.ts`
| # | pending | utterance | expect |
|---|---|---|---|
| 1 | choose_target [E2, E1], pending `[card.remove { $choice }]` | `The second one.` | resolves chosen [E1], ops `[card.remove { E1 }]`, confidence 1, source [u, asking], classifier = pending.classifier |
| 2 | same | `Number 2.` / `2` | as 1 |
| 3 | same | `The GP one.` | chosen by label |
| 4 | same | `The GP one, please.` | as 3 (filler removed) |
| 5 | same (both texts contain `appointment`) | `The appointment one.` | tie → not an answer → none, `resolves: null` |
| 6 | same | `The latest one.` | chosen [E2] |
| 7 | same | `Neither.` | none, heard_intent remove, `resolves.dismissed === true`, ops [] |
| 8 | same; one rule | `Neither, I meant the rule.` | dismissed; remainder has no verb → none, dismissed true |
| 9 | same; rule R1 | `No, delete the rule instead.` | dismissed with remainder → remove, ops `[card.remove { R1 }]` (no reject prefix) |
| 10 | same | `No.` | dismissed, remainder null |
| 11 | same | `No, that's not what I said.` | dismissed, remainder null |
| 12 | same | `A patient must give a reason.` | not an answer → add rule, `resolves: null` |
| 13 | same | `Yes.` | reask: none, heard_intent remove, needs_clarification false, resolves null |
| 14 | confirm_intent (pending `[card.remove { E1 }]`) | `Yes.` | ops `[card.remove { E1 }]`, resolves chosen [] dismissed false |
| 15 | confirm_intent | `No.` | dismissed, ops [] |
| 16 | confirm_intent; rule R1 | `No, make it 48 hours.` | dismissed with remainder → amend on R1 |
| 17 | choose_target [E2, E1] | `Both.` | chosen [E2, E1] → two `card.remove` ops |
| 18 | choose_target [E2, E1, E3] | `Both.` | not an answer → none |
| 19 | choose_target for `interpretation.reject { $choice }`; E1.proposal_id = Pb | `The first one.` | ops `[interpretation.reject { Pb }]` |
| 20 | same; the chosen card has `proposal_id: null` | `The second one.` | none, heard_intent reject, resolves set, rationale `…made by a person…` |

### `claude-provider.test.ts` (fake `ModelClient`; `fakeCreate(result | error)` records params)
| # | fake | expect |
|---|---|---|
| 1 | valid add proposal JSON, `stop_reason: "end_turn"`, `model: "claude-opus-5-5"` | provenance `{ provider: "claude", model: "claude-opus-5-5", prompt_version: SYSTEM_PROMPT_VERSION, fallback_from: null, error: null }`; params: `model`, `max_tokens === 4096`, `system[0].cache_control.type === "ephemeral"`, `system[0].text === FROZEN_SYSTEM`, `output_config.effort === "medium"`, `output_config.format.type === "json_schema"`, one user message; options `timeout === 20000`, `maxRetries === 1`; no `thinking`, `tool_choice`, `temperature` |
| 2a | `stop_reason: "refusal"`, `stop_details: { category: "general_harms" }`, `content: []` | rules.v1 fallback `error: "refusal:general_harms"`, rationale ends with the fallback note; `onError` once |
| 2b | `stop_reason: "refusal"`, `content: [{ text: "I can't" }]` | `error: "refusal:unknown"` — not `parse` |
| 3 | `content: [{ text: "not json" }]`, `end_turn` | fallback `parse` |
| 4 | throws `AuthenticationError` | fallback `auth`, `onError { code: "auth" }` |
| 5 | throws `RateLimitError` on calls 1 and 2, succeeds on 3, throws on 4 | `onError` called for 1, not 2, again on 4 → exactly 2 calls |
| 6 | throws `APIConnectionTimeoutError` | `timeout` (not `connection`) |
| 7 | throws `APIConnectionError` | `connection` |
| 8 | `stop_reason: "max_tokens"`, truncated JSON | `stop:max_tokens` — not `parse` |
| 9 | valid shape but `card.remove.card_id: "card_9999"`; 3 examples in the index | provider claude, choose_target over the 3 examples most recent first, `$choice` pending, `error: null` |
| 10 | same with 1 example | confirm_intent bound to it |
| 11 | same with none | none, heard_intent remove, provider claude |
| 12 | `intent: "remove"` with a `card.create` op | fallback `invalid:intent_op_mismatch` |
| 13 | `intent: "amend"`, `operations: []`, no clarification | fallback `invalid:intent_op_mismatch` |
| 14 | `confidence: 0.2`, amend op | confirm_intent wrap, question starts `Did you mean to` |
| 15 | `confidence: 1.7` | clamped to 1 |
| 16 | `resolves.proposal_id` ≠ pending id, ops depend on the choice | resolves dropped; reask proposal |
| 17 | `target_card_ids: []` with ops naming `card_0007` | recomputed to `["card_0007"]` |
| 18 | `card.rule_id: "card_404"` | link null, rationale gains `(link dropped: unknown card)` |
| 19 | `interpretation.reject { proposal_id: "prop_nope" }`; last_rejectable P | op dropped → confirm_intent `Did you mean to reject the last interpretation?` with `interpretation.reject { P }` |
| 20 | `renderUserMessage` snapshot for the §14 state after u05 | contains `## CARD INDEX`, each card id, `## LAST REJECTABLE`, `## PENDING CLARIFICATION` with numbered candidates, `## NEW UTTERANCE` last; a manual-lane utterance renders `(typed)`; no ISO timestamp, no session id |
| 21 | `FROZEN_SYSTEM` | SHA-256 equals the pinned constant; `/20\d\d-\d\d/` absent; names every intent and operation kind; contains "confirm {card_ids: []}" |
| 22 | `selectProvider` matrix | `{}`→rules.v1; `{ANTHROPIC_API_KEY:"x"}`→claude; `{ANTHROPIC_AUTH_TOKEN:"x"}`→claude; `{EXMAP_CLASSIFIER:"rules.v1", ANTHROPIC_API_KEY:"x"}`→rules.v1; `{EXMAP_CLASSIFIER:"claude"}`→claude; `{EXMAP_CLASSIFIER:"gpt"}`→throws `E_CLASSIFIER_UNKNOWN_PROVIDER` |
| 23 | aborted signal; fake throws `APIUserAbortError` | `aborted`, `onError` not called |
| 24 | fake throws `new Error("Could not resolve authentication method…")` | `auth`, `onError { code: "auth" }` |
| 25 | JSON with `intent: "modify"` | `parse` |
| 26 | rules.v1 fallback whose rationale is 200 chars | returned rationale ≤ 200 chars ending with the note; invariants hold |
| 27 | `confirm { card_ids: [] }` with `last_proposal` a removal | kept as an act review; with a `card.create` last proposal → none, heard_intent confirm |

### `conversation.test.ts`
The fixture end to end: `createRulesClassifier()`, `buildClassifierInput` + `toCoreCommands` (`src/server/classifier-bridge.ts`) and core `apply` with `testCtx()`; a `MapState` is threaded through; `ui` steps run as core commands (`question.accept`; `confirm { card_ids: [], proposal_ids: [p] }` for `accept_acts`; human `confirm` lists as `review/checks` builds them; `signoff.record`; `export.options_set`). Binds `$symbols`; asserts per utterance intent, `heard_intent`, confidence (±0.005), operation kinds/targets/patches, clarification kind + candidate order, `resolves`, every proposal validates, and `refused[]` is empty. Also: after u15 `$p14` is `confirmed` with `by.provider === "rules.v1"`; after u30 `isHumanVerified === true`; after u31 the batch contains `signoff.invalidated` and `isHumanVerified === false`; after the second sign-off `true`; the final live index is exactly the §14 set; `select.counts` after u31 matches hand counts (31 utterances, 31 classified).

## 3. Audio (`tests/unit/audio/`, node project; `tests/unit/web/audio/`, web project)

`helpers.ts`: `silence(n)`, `tone(n, amplitude, hz)`, `noise(n, rms)` → `Float32Array[]` of 320 samples; `feed(segmenter, frames, t0)`.

### `vad.test.ts`
1. `frameRms` of zeros = 0; of a full-scale sine ≈ 0.707; `rmsToDb(0)` ≈ −180.
2. Seeding: ten frames at −50 dB → floor −64; ten at −75 → −70; ten at −20 (speech from frame 0) → −64 and frame 11 at −20 is speech.
3. The floor drops quickly (20 % per quieter frame) and rises slowly (0.5 %).
4. The floor does not rise during speech frames.
5. Onset needs `floor + 9`; `floor + 7` is silence from `silence` but speech from `inSpeech`.
6. Nothing below −55 dBFS is speech even with a very low floor.
7. The floor is clamped to [−70, −25].
8. Re-seed: steady −45 dB noise from frame 0 → speech from frame 1; after 3 s the floor ≈ −45 and the next frame is not speech; speech at −20 with every 10th frame at −40 → floor −40 and the −20 frames still speech.

### `segmenter.test.ts`
9. 1 s silence, 1 s −20 dB speech, 1 s silence → one segment: `startedAt 800`, `onsetAt 1000`, `speechMs 1000`, kept to `lastSpeechAt + 20 + 200`, `pcm.length = (endedAt − startedAt) × 16`, `seq 1`, `cappedAt15s false`.
10. The pre-roll holds exactly the 10 frames before the onset frame, byte-for-byte, then the onset frame.
11. Onset at frame 3 → `startedAt = onsetAt − 60`.
12. A 150 ms blip → `null`, back in `silence`; a 300 ms "Yes." → a segment with `speechMs 300`.
13. A 500 ms gap inside speech does not close; 600 ms does.
14. 1 s silence then 20 s continuous speech → segment 1 ends at exactly 15 000 ms from `startedAt` with `cappedAt15s`; segment 2 starts at the next frame; the concatenated `pcm`s equal the input.
15. Start mid-speech: continuous −20 dB from frame 0 → one segment with `onsetAt 0`.
16. `segmenterFlush` in speech emits; in silence returns null; < 200 ms speech returns null.
17. `speaker` is stamped at close time; a change before the close frame is reflected, after it is not; `null` is stamped as `null`.
18. `peakRmsDb` equals the loudest frame's dB.

### `hallucination.test.ts`
19. `"Thank you."` with `{ 700, -50 }` → dropped; `{ 700, -20 }` → kept; `{ 1500, -50 }` → kept.
20. `"Okay."` at `{ 500, -20 }` and `{ 500, -50 }` → kept; `"Yes."`, `"Bye."`, `"you"` → kept at any energy.
21. `""`, `"..."`, `"."`, `"[BLANK_AUDIO]"`, `"(music)"`, `"♪"` → dropped regardless of energy.
22. `"you you you you you you"` → dropped; `"go go go go go go now"` → kept unchanged.
23. A real sentence at any energy → kept, text unchanged.
24. Normalisation: `"Thank you!!"`, `" thank  you "`, `"THANK YOU."` all match the table.

### `replay.test.ts`
25. `parseReplayFixture` accepts the shipped `conversation.v1.json` (with `story`, `speakers`, `ui`, `label`, `expect`); rejects missing `version`, non-array `utterances`, a bad `lane`, decreasing `atMs`, empty `text`, a duplicate `label`, any other unknown key — each `REPLAY_FIXTURE_INVALID` naming the index and field.
26. Instant mode emits all utterances in order synchronously; `play()` resolves; `state === 'done'`.
27. `play('instant', { until: 'u05' })` emits u01–u05 and leaves `paused`, `index 5`; `step()` emits u06 only; `resume()` emits the rest; `until: 2` emits three; an unknown label rejects `REPLAY_FIXTURE_INVALID`.
28. `skip('u06')` after `until: 'u05'` advances `index` to 6 without emitting; `play` then continues from u07.
29. Timed mode at ×2 with fake timers: an utterance at 4000 ms emits at 2000 ms; pause at 1000 ms and resume 5 s later emits at 7000 ms.
30. With the clock at 90 000 ms and a fixture starting at `atMs 500`, the utterance at 4500 gets `tStartMs 94 000`, `tEndMs = tStartMs + durationMs` (or the word estimate); `speaker` falls back to `speakers.get(lane)`; `provider 'replay'`, `isLocal true`, `confidence null`.
31. `transcribe()` rejects `NOT_SEGMENT_PROVIDER`.

### `captureLane.test.ts` (fake `MediaDevicesLike`, fake `AudioGraph`)
32. `start()` → `requesting` then `live` with an audio track; `getUserMedia` was called synchronously; the video track's `stop()` called; `trackLabel` set; `ensureContext` awaited after the stream resolved; `addModule` ran once across two lanes.
33. A stream with no audio track → `error NO_AUDIO_TRACK`; every track stopped; guidance `no_audio_track`.
34. Each DOMException name maps to its code with `domName` preserved; an unknown name → `UNKNOWN`.
35. `OverconstrainedError` with a saved deviceId → one retry without it → `live`; a second failure → `DEVICE_UNAVAILABLE` and the saved id cleared.
36. Audio track `ended` while live → `stopped` with `ended_by_browser` (display) / `device_lost` (device); detached; `segmenterFlush` ran.
37. `mute`/`unmute` toggle `signal`; 10 s of frames under −60 dB → `silent`; a loud frame → `signal`.
38. `start()` while `requesting`/`live` rejects `LaneStateError`; `stop()` while `requesting` stops the later stream and never attaches it; `stop()` in idle/stopped/error is a no-op; `attach` throwing → `WORKLET_LOAD_FAILED` with all tracks stopped; `setSource` while live throws.
39. `getDisplayMedia` undefined → `UNSUPPORTED` without calling anything.

### `queues.test.ts`
40. `TranscriptionQueue`: FIFO across lanes; one in flight; backlog counts; a provider error pauses, the restart hook is called once, the segment is retried once then set aside in `failed`; `retryFailed` re-enqueues; `TRANSCRIBE_TIMEOUT` follows the same path; `provider(lane)` null for `me` and Whisper for `remote` → `me` segments return `false` and are never transcribed; a push-mode provider behaves as `null`.
41. Lane stop does not drain the queue: three waiting, both lanes stopped → all three transcribed and posted; the provider's `stop()` not called until `dispose()`.
42. `PostQueue` with an in-memory sink: order preserved; up to three in flight, never four; `transient` retried with the backoff sequence until `ok`; a timeout followed by `{ ok: true, duplicate: true }` is a success with `eventId` and no `lastError`; `lastError` on the third consecutive transient failure; `refused` not retried, lands in `refused[]` and `lastError` with the server's reason.
43. `HttpUtteranceSink` with a fake `fetch`: default `timeoutMs === 15000`; `201` → ok with `eventId`; `409 { reason: 'DUPLICATE_ID', event }` → ok, duplicate, `eventId = event.id`; `409 { reason: 'LEDGER_BROKEN' }`, `404 SESSION_NOT_FOUND`, `400 BAD_REQUEST`, `403`, `422 EMPTY_TEXT` → `refused`; `408`, `429`, `503`, a thrown `TypeError`, an `AbortError` (`message: 'timeout'`), a 2xx non-JSON body → `transient`.
44. `buildUtterance`: `utt_` + UUID; integers; `t_end_ms ≥ t_start_ms`; negatives clamped to 0; `confidence` rounded to 2 dp and clamped; empty text throws `EMPTY_TEXT`; the output satisfies core's `utterance.record` (apply with `testCtx()` → `ok`, and the ledgered utterance carries `is_local` and `confidence` unchanged).

### `guidance.test.ts`, `webSpeech.test.ts`, `speakers.test.ts`, `resample.test.ts`, `localWhisper.test.ts`
45. Every `(os, lane, reason, source)` combination returns a non-empty `title` and `steps`.
46. Snapshot of the Windows / macOS / Linux `no_audio_track` text (the contract the README follows by hand).
47. `detectOs()` from Windows 11 Chrome, macOS Chrome, Ubuntu Chrome UA strings, and `userAgentData.platform` when present.
48. Web Speech: interim results call `onInterim` and are never emitted; a final emits with `tStartMs` from the first interim of that index; `confidence` 0 → null; after an `onend` restart a new interim at index 0 gets a fresh `tStartMs`.
49. Web Speech: `onend` restarts while started; `network` surfaces `WEB_SPEECH_NETWORK` once and backs off; `not-allowed` stops with `WEB_SPEECH_DENIED`; `start()` rejects `WEB_SPEECH_DENIED` "consent not given" without the flag.
50. `SpeakerStore`: `get('remote')` null until `set`; `set('remote', '  Bob ')` → `'Bob'` added to `remoteKnown` once; `set('remote', '')` → null; `get('manual')` mirrors `me`; `userName` seeds `me`, null leaves it null; `remoteKnown` caps at 20.
51. `resampleTo16k`: 48 000 → 16 000 gives length/3 (±1) and a 1 kHz tone keeps its RMS within 1 dB.
52. `LocalWhisperProvider` with a fake `Worker`: `start()` resolves on `ready` with `device`/`threads`; rejects `MODEL_LOAD_FAILED` on a load error and on an unhandled error while loading; `transcribe()` resolves on its `result`; rejects `TRANSCRIBE_FAILED` on an error with its `jobId` or `null`; rejects `TRANSCRIBE_TIMEOUT` after the deadline; `stop()` waits for the in-flight job; `stop({ force: true })` terminates at once.

### `tests/unit/web/audio/` (jsdom)
53. `CaptureControls.test.tsx`: both lanes render idle; meters named "Call level" / "Microphone level" with `aria-valuemin/max`; the provider select is disabled while a lane is live; the backlog diagnostics line is prefixed "this page:".
54. `ConsentNotice.test.tsx`: Continue / Cancel call the controller; `role="dialog"`, focus on Continue, Escape cancels.

## 4. Server (`tests/unit/server/`, node project)

Setup: `buildApp({ home: mkdtemp, port: 4317, classifier: fake, webDist: null, ortDir: null, now: fixedClock, nextId: counterIds })`, `app.inject` with `Host: 127.0.0.1:4317`. `helpers.ts`: `fakeClassifier(script)`, `postUtterance(app, id, text, { wait = true, lane, speaker })`, `createSession(app, { story })`, `readLedger(home, id)`, `awaitClassified(app, id, utteranceId)`.

1. `health.test.ts` — `GET /api/health` → `{ app: "exmap" }`; `GET /api/config` with `ANTHROPIC_API_KEY = "x"` → `provider "claude"`, `reason` names the variable, `model === CLAUDE_MODEL`, the serialised body does not contain `"x"` as a credential; `EXMAP_CLASSIFIER=rules.v1` with a key → `rules.v1`, reason `EXMAP_CLASSIFIER=rules.v1`; `last_error` set after a fallback classification and cleared after a non-fallback claude classification.
2. `host-guard.test.ts` — `Host: evil.example` → 403 `FORBIDDEN_HOST`; `127.0.0.1:4317`, `localhost:4317`, `[::1]:4317` pass; `127.0.0.1:5173` → 403 without `dev`, 200 with; port 0 accepts the bound port; WS upgrade with `Origin: http://evil.example` → close 4003; `http://localhost:5173` accepted only with `dev`.
3. `sessions.test.ts` — create (201; `meta.json` has `schema`, `created_at`; `events.jsonl` exists and is empty); with `story` and `actor` → two events and the story `applied`; `story` without `actor` → 400 `ACTOR_REQUIRED`; list newest first with `counts` matching `select.counts`; `GET /api/sessions/bad` → 400; unknown id → 404; `events?after=1` → seq > 1; `state` omits snapshots; `GET /api/sessions/:id` returns `export_options: null` then the current value after a PUT.
4. `utterances.test.ts` — without `wait`: 201 arrives before the fake classifier resolves (deferred promise) and the body is exactly `{ ok, event }`; with `wait=1`: `event.seq === 1`, `classification.proposals[0].events` of types `[proposal.made, proposal.applied]`, an `utterance.classified` follows naming the proposal; a duplicate id → 409 `DUPLICATE_ID` with the original `{ id, seq, hash }` and no second classification; `text: "  "` → 422 `EMPTY_TEXT`; `lane: "phone"`, a missing `is_local`, an extra key → 422 `BAD_REQUEST` with `issues`; `t_end_ms < t_start_ms` → 422 `INVALID_TIMING`; `is_local`/`confidence` present on the stored event; `intent: "none", heard_intent: "confirm"` → one `utterance.classified { intent: "none", heard_intent: "confirm" }` and nothing else; a thrown `ClassifierError` → 201 then `utterance.classified { error, proposal_ids: [] }`; two concurrent posts with the first resolving after the second → proposals in utterance order and both utterances before both proposals; a proposal targeting a card removed meanwhile → `refused[0].reason === "CARD_NOT_LIVE"`, still 201; fallback provenance (`fallback_from`, `error`, `prompt_version`) preserved on the proposal and the classified event; the stale-answer race (open clarification, voice answer in flight, click `dismiss`) → the classifier is called again with `pending_clarification: null`, no `CLARIFICATION_NOT_ANSWERABLE` is ledgered, the second result applied; `close()` during an in-flight classify → `signal` aborted and queued jobs never run.
5. `bridge.test.ts` — table over §8.7: every classifier op → the expected core op with `intent === intentOf(kind)` (story create with a live story → `card.update` under `amend`; a `confirm` prefix under a remove utterance; a reject prefix under amend); all proposals of one result in one `proposal.propose`; `replacement_card_id` → one `card.replace`; `text_append` → `patch.text` = current + " " + append; `confirm { card_ids: [] }` after a removal `last_proposal` → `confirm { proposal_ids: [that id] }`, after a create `last_proposal` → `refused NOTHING_TO_CONFIRM`; `undo { steps: 2 }` → `select.undoTarget(state, 2)`; undo right after an undo → a `pending_operation` clarification "redo it?", with "redo" in the text → a plain undo; choose_target → `template` without target, `candidates` with `score: null`, a `card.update` template carrying `amendment { from, to, scope, append }`; confirm_intent → `pending_operation`, `template: null`, `candidates: []`; `resolves { dismissed: false }` → `clarification.answer { kind: "text" }` then `resolves_clarification_id` on exactly the first proposal; `resolves { dismissed: true }` with a remainder → `dismiss` then the remainder with `resolves_clarification_id: null`; a `resolves` whose utterance is already in `text_answers` → no second text answer; `actor` on resolving proposals is the speaker label or `"(Call, no speaker label)"`; `prompt_version` carried; `buildClassifierInput` passes `lane: "manual"` and `speaker: null` through, builds `cards[].answer`/`proposal_id`/`last_speaker`, `last_proposal` includes a confirmed one and skips human proposals, `last_rejectable` uses `select.isRejectable`, `pending_clarification` is the most recent open one, maps a confirm_intent back from `pending_operation`, and skips a pure-question clarification.
6. `acts.test.ts` — accept of a content proposal → `proposal.confirmed` naming the card with `actor "Ana"`; accept of a removal → 200 with `confirms_proposal_ids === [pid]`, no effects, `unreviewedActs` empty; accept of a `confirm` proposal → 409 `PROPOSAL_NOT_CONFIRMABLE`; reject → `proposal.rejected` + new revision; missing actor → 400; unknown pid → 404; candidate → `[clarification.answered, proposal.made, proposal.applied]` with the asking provider and `actor "Ana"`; `yes` on a `pending_operation` clarification → the same shape; `yes` on a template clarification → 409 `CLARIFICATION_NO_OPERATION`; text → 201 at once with a `manual` utterance (`speaker === actor`, `is_local: true`) and `clarification.answered { kind: "text" }` (still `open`), then with `wait=1` the classifier sees `pending_clarification` and the `resolves` proposal resolves it with one text answer; a text whose classification is `none` → `resolved: false`, still open, a later candidate click succeeds; dismiss → `dismissed`; cards create/confirm/remove/update (empty patch → 422 `PATCH_EMPTY`); accept-outstanding without reason → 400 `REASON_REQUIRED`, with reason → `question.accepted_outstanding` and `answer` still null; `undo` → `undo.applied` with the target's hash; `review/checks` for `story_rules_confirmed` → one `proposal.confirmed` with exactly the sent `card_ids`; a wrong-kind id → 422 `KIND_MISMATCH`; an empty list → 409 `NOTHING_TO_CONFIRM`; `changes_resolved` → 400 `CHECK_NOT_MARKABLE`; a repeated identical mark → 409 `NOTHING_TO_CONFIRM`; sign-off without `actor` is accepted.
7. `signoff.test.ts` — unreviewed map → 422 with five checks and `pass === false`; after full review (including Accept on every AI act) → 200 and `human_verified: true`; wrong statement → 400; stale `revision_hash` → 409; a later `cards/:id/update` → the batch contains `signoff.invalidated`; re-sign-off → 200 and the earlier one reads `invalidated` in `/state`; a clarification asked after sign-off → `human_verified: false` without invalidation, true again after Dismiss.
8. `persistence.test.ts` — every line of `events.jsonl` equals `canonicalJson(event)` and the file ends with `\n`; byte length equals the sum of its lines; `fs.fsyncSync` called once per batch; restart: a second `buildApp` on the same home serves the same `head` and `counts`; tamper (flip one character in event 3's text) → `GET /api/sessions/:id` 409 `LEDGER_BROKEN { row: 3, seq: 3, code: "HASH_MISMATCH" }` and the list shows `broken` with counts from events 1–2; remove line 2 → `PREV_HASH_MISMATCH`/`SEQ_MISMATCH` at row 2; truncate the last line mid-JSON → `LEDGER_PARSE_ERROR` at the last row with a prefix summary; a broken session refuses `POST …/utterances` and writes nothing; write failure (`writeSync` stubbed to half-write then `ENOSPC`) → 500 `LEDGER_WRITE_FAILED`, file length equals the pre-write length (`ftruncateSync` observed), `head` unchanged, next act 409 `LEDGER_BROKEN`, a WS client got 4009, a fresh open loads the same `head`; `export.options_set` events round-trip through restart; `server.lock`: two `startServer`s on one home → `HomeLockedError` with the first's URL; a dead-pid lock is taken over; a live pid without `port` → `HomeLockedError { url: null }`; `close()` removes it.
9. `stream.test.ts` (`app.listen({ port: 0 })`, `ws` client) — `hello` first; `after=2` delivers seq 3..n then live events; an act during catch-up is delivered exactly once in order; `proposal.*` and `utterance.classified` arrive after the 201; unknown session → `error` frame then 4004; `Origin` check.
10. `export-routes.test.ts` — unverified → 422 `NOT_HUMAN_VERIFIED` with `checks` and `signoff.status === "none"`; active sign-off + open clarification → `active_but_dod_failed`; `?draft=true` → 200, `Content-Disposition` `DRAFT-crb-backlog-item.json`, title prefixed, `labels.exmap_draft === "true"`; verified → all five files 200 with the right content types; `export/backlog-item.json` → 400 `EXPORT_FILE_UNKNOWN`.
11. `export-options.test.ts` — `PUT` → 200 with `events[0].type === "export.options_set"` and `export_options.seq === 1`; a second PUT → `seq 2`; `capability_class: "nope"` → 400 `CLASS_UNKNOWN`; `"unclassified"` accepted; a slot `"1bad"` → 422 `BAD_SHAPE`; missing `actor` → 400; `GET /api/sessions/:id` returns the latest; `evidence.json` carries `export_options_history` with both.
12. `settings.test.ts` — default `""`; `PUT` persists (file content) and survives restart; an 81-char name → 400.

## 5. Export (`tests/unit/export/`, node project; fixtures from the core scenario plus a verified variant)

1. `context.test.ts` — refusal shape for an unverified map (`signoff.status` `none` / `invalidated` with `invalidated_by_event_id` / `active_but_dod_failed`); draft on a verified map still watermarks; defaults when there are no export options (`seq: 0`).
2. `backlog-item.test.ts` — id from the story "A patient can cancel an appointment online, but not within two hours." → `a-patient-can-cancel-an-appointment-online-but-n-<hash8>` (the 48-char cap, no trailing `-`), draft → `…-draft-<hash8>`, both match crb's regex and ≤ 64; a punctuation-only story → `exmap-<hash8>`; title truncation at a word boundary; description contains `Rules:` and `Definitions:`; AC lines: a parseable example → `Given …, when …, then …`, an `if … then` example parses, free text → `Example: …`, facts follow examples; `structural_facts` verbatim; labels; `registered === now`; determinism.
3. `ticket.test.ts` — `body` is a string with `\n`; tags include `crb:class=` and `crb:kind=`; points table (`XS→1 … XL→21, unsized→null`); `author/url/state` empty; `ticket.md` contains `## Open questions explicitly accepted as outstanding` iff a question is accepted and never "answered" in that section; draft banner iff draft; `## Unresolved questions` only on drafts; the verification paragraph names reviewer, revision and head.
4. `feature.test.ts` — `Feature:` = title; one `Rule:` per live rule in order; scenarios under their rule; unattached examples under the comment; G/W/T steps or a single `* ` step; questions as comments with "accepted outstanding" wording; definitions as comments; multi-line indentation; `@exmap-draft` only on drafts; no tabs; ends with one `\n`.
5. `evidence.test.ts` — `sha256(canonicalJson(canonical_state)) === requirement_revision.hash`; verified → `signoff.status "active"` and revision equality; draft after invalidation → `verified false`, `signoff.status "invalidated"`, `watermark` set; `export_options` and history carried verbatim from state.
6. `catalogue.test.ts` — the JSON has `_source`, `_source_commit` (40 hex), `_copied` (YYYY-MM-DD), 14 classes; every slot has `name`, `question`, `kind ∈ {structural, value}`; `slotsFor("bug.fix")` → `reproduction`, `expected_behaviour` structural and `exact_value` value; `isCatalogueClass("unclassified") === false`; the file is byte-identical to the scratchpad generator's output at vendoring time (a checked-in hash).

## 6. Web (`tests/unit/web/`, jsdom + testing-library)

1. `hash.test.ts` — the `@noble/hashes` adapter matches the two vectors.
2. `sessionStore.test.ts` — fake WebSocket: `hello` then events → the state reduces; a seq gap → `resync()` with `after = head.seq`; a duplicate seq ignored; `seq === head + 1` with a wrong `prev_hash` → `chainError PREV_HASH_MISMATCH`, no reconnect, no further reduction; a tampered hash → `chainError` and no further reduction; the reconnect backoff sequence; an `export.options_set` event reduces into `export_options`.
3. `Board.test.tsx` — four columns with the kind backgrounds; cards show text, a status chip from `statusLabel` (a removed card reads "removed", never "rejected"), version; the history toggle hides non-live by default and shows them struck through; the needs_review chip text; provenance shows `restored_by` and `confirmation.by`; keyboard: `ArrowDown` moves to the next card, `ArrowRight` to the next column, `Enter` opens the menu and `Escape` returns focus.
4. `ProposalTray.test.tsx` — items show the rationale and a numeric confidence; Accept calls `api.acceptProposal`; Accept present on a removal and Reject reads "Restore"; an unreviewed act 15 utterances old is still listed; an open clarification 15 utterances old is still listed; a template clarification renders one button per candidate, a "Will: remove …" line and the text field; a `pending_operation` clarification renders `clarification-yes-*` and no candidates; a pure question renders only text + Dismiss; text answers are listed under the question.
5. `ReviewDrawer.test.tsx` — five checks with pass/fail text; `dod-mark-*` only on checks 1, 2, 4; the mark sends exactly the previewed `card_ids`; check 3 renders `dod-act-accept-*` per unreviewed act and a link per open clarification; the invalidation notice when the last sign-off is invalidated; the "signed off but not currently verified" line; `review-catching-up` and a disabled submit when `pendingWork() > 0`, enabled after `signoff-anyway`; submit disabled until both fields are filled; 422 renders `signoff-errors`.
6. `ExportDrawer.test.tsx` — slot questions change with the class; structural/value chips; a free fact with a foreign slot shows the prose warning; download links carry `?draft=true` when toggled and use `crb-backlog-item.json`; gate text for unverified; the options-history disclosure from state.
7. `SettingsDialog.test.tsx` — an empty name blocks acts (an act button opens settings); classifier status renders provider/model/reason from a mocked `/api/config`; a grep-style assertion over `src/web/**` finds no `claude-` literal; no input of type password or named "key"; `SessionPicker` has `settings-open`.
8. `replayDriver.test.ts` — with a fake controller: `playUntil("u05")` calls `playReplay("instant", { until: "u05" })` then awaits idle; `skip("u06")` calls `skipReplay`; `playAll()` plays the rest; `position` follows the controller's replay index.

## 7. Launcher (`tests/unit/launcher/launcher.test.ts`, node project)

1. `nodeVersionOk("22.11.0") === false`, `"22.12.0"` true, `"23.1.0"` true; `installNeeded({ nodeModulesExists, stamp, lockHash })` table; `buildStale(...)` table over the five conditions; `locateNpm({ execPath, env, exists })` table (`npm_execpath` wins; the Windows layout; the `../lib/node_modules` layout; PATH last); `browserCommand(platform, env, url)` → `["open", url]` / `["cmd.exe", ["/c", "start", "", url]]` / `["xdg-open", url]` / `null` without a display; `probePort` against a stub returning `{ app: "exmap" }` → `"exmap"`, HTML → `"other"`, a closed port → `"free"`; `scripts/install-stamp.mjs` writes `sha256(package-lock.json)`.

## 8. End to end (`tests/e2e/`, Playwright 1.56.1, `workers: 1`, the fixtures of §13)

1. `journey.spec.ts` — the §13.1 journey (brief §0 steps 1–5 and §5): steps 1–14 as written there, one test; plus the typed variant (three sentences through `ManualInput`: an add, an amend, a resolving "Delete that example."; lane "Typed", provider "Typed", `is_local: true`).
2. `replay.spec.ts` — open `?session=<id>&replay=demo&speed=instant&autostart=1&testhooks=1`; wait for `replay-status` `31 / 31` then `postQueueIdle()`; transcript rows = 31; `column-rule` has ≥ 1 card; the header's utterance count equals the rows; the number of `utterance.classified` events (`GET /events`) equals 31; a second test opens `?replay=demo&speed=instant&autostart=1&testhooks=1` without `session=` after `setName("Sam")` and asserts a session was created with a story card.
3. `audio.spec.ts` — a `beforeAll` creates a session through the API; every test opens the session screen with `testhooks=1`:
   - E1 replay, instant: `replay-status` `31 / 31` → idle → exactly 31 transcript rows, each with provider "Replay" and its fixture speaker; the session counter equals 31; the first row's `mm:ss` is session-relative.
   - E1a replay breakpoints: `playReplay('instant', { until: 'u05' })` via the hook → idle → the u05 clarification with two candidates; `replay-step` → u06 answers it; the rest via `replay-play`.
   - E2 manual: "We also need an error case." in lane Call with speaker "Alice" → a row with lane "Call", speaker "Alice", provider "Typed"; the textarea clears; Shift+Enter does not submit; an empty speaker field → "— (no speaker label)".
   - E3 mic lane state machine (fake device + WAV): "Capture only", `lane-me-start` → `data-state=live` within 5 s; `level-me` `aria-valuenow > 0` within 5 s; `segmentsClosed().me ≥ 1` within 20 s; "Live — no sound heard" within 25 s `[VERIFY %noloop]`; the provider select disabled while live; `lane-me-stop` → `stopped`.
   - E4 remote lane headless: `lane-remote-start` → `data-state=error` with an allowed `data-error-code`; `guidance-panel` with `data-os=linux` and the Linux title; Escape closes it.
   - E5 speaker label: "Bob" committed with Enter stamps subsequent manual Call utterances; uncommitted "Al" does not.
   - E6 provider honesty and consent: choosing Web Speech opens `webspeech-notice` with no `rec.start()`; Cancel reverts; Continue → `lane-me-provider-badge` "Web Speech (not local)" (or the disabled reason when headless Chromium has no recogniser).
   - E7 model download inert without consent: tiny.en, Whisper, `lane-me-start` → `model-notice` visible and no request to `huggingface.co`; `model-notice-cancel` → "Capture only (download declined)", lane still live, still no Hub request.
   - E8 accessibility: axe on the session screen with CaptureControls mounted and with `model-notice` open → no serious/critical violations.
4. `axe.spec.ts` — after `playUntil("u13")` (and a separate state replayed to u05 for a clarification): axe on the session screen, then with `review-drawer`, `export-drawer` and the settings dialog open; `violations.filter(serious | critical)` is `[]` each time; the full list is attached to the report.
5. `launcher.spec.ts` (serial, `request` only) — `spawn(node, ["bin/exmap.mjs", "--no-open", "--port", "0", "--home", tmp])` → the listening line; `GET /api/health` → `{ app: "exmap" }`; a second launcher with `--port <thatPort> --home <tmp2>` exits 0 printing "already running"; `SIGTERM` the first → exit 0 within 5 s and `server.lock` gone; the launcher's stdout contains neither "npm install" nor "building" (the stamps match: idempotency).
