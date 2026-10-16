# Critical-friend review — exmap: is the idea right, and what are good answers?

**Date:** 2026-10-16 · **Scope:** exmap v1 as built (`a037820`) and the v2 requirement (`exmap/docs/REQUIREMENTS.md` at `3563969`, with `CRB-SEAM.md`), read against crb at the same commit · **Lens:** the operator's side; what is weak, what is unproven, what would change the verdict · **Inputs:** four lens notes (premise, measurability, practicality, alternatives) in the session scratchpad, plus §2. Produced by an AI subagent; treat it as claims to verify, not a sign-off.

**Tags.** [measured] gives n and source. [read] gives `path:line`, relative to the repository root; `demo/` is the scratchpad demo folder. [judgement] is reasoning. Nothing already in the repository was modified; this file is the only addition.

---

## 1. Verdict

The idea is worth pursuing, but not in the form v2 describes, and not yet. Keep stage 1, because an agreed, owned, signed set of examples captured before the code exists is the one input the factory's evidence says could matter: crb's only measured context lever is the test (+43.2 points, n = 37), and an example is a test in waiting. Drop the rest of v2's ambition for now. The autonomous stage 2, the reusable standards, the improvement loop and its budget all invest in unmeasured context and in a loop with no signal it can attribute while no cell is proven. crb's rule forbids showing a builder context its standard was not measured with [read: ADR-0026:548], but crb cannot tell a drafted slot line from a typed one; keeping drafted facts to calibration builds is exmap's own restraint [read: `exmap/docs/CRB-SEAM.md:267`, R8] (corrected: crb does not enforce this itself, so the advice to defer stands but exmap must hold that line). Re-aim the product as "agreed example rows that a named engineer turns into a failing test and sized XS or S tickets on the board, with crb's intake doing the fitness check". The single biggest risk is that exmap's value chain never reaches the layer that matters: a signed map from a real conversation may not carry what an engineer needs to write that test and size those items without going back to the business, and nothing checks it today, because the Definition of Done is a status gate that has already signed a contradiction [judgement, from §4].

Two uncomfortable conclusions. "Do less": most of v2's forty-one design requirements (R1 to R41 [read: `exmap/docs/CRB-SEAM.md`]) are deferrable. And exmap's factory value today is zero deliveries, whatever it supplies: no cell is proven, and every sized item that needs no split stops `no_proven_standard` before the gate checks what the ticket carries [read: `src/crb/factory/standard.py:456-471`; `exmap/docs/CRB-SEAM.md:160`], so nothing can deliver; unsized items, like the demo's, stop `unsized` first [read: `standard.py:425-432`; `demo/outputs/crb-backlog-item.json:14`].

---

## 2. What I looked at

| Evidence | Source |
|---|---|
| Four lens notes, in full | scratchpad `cf/{premise,measurable,practical,alternatives}.md` |
| The v2 requirement and seam | `exmap/docs/REQUIREMENTS.md`; `CRB-SEAM.md` §5, R8, R34, R35, "Later, not asked" |
| crb's standard, baseline, Wave 3 status | `docs/adr/0026-the-context-standard.md`; `docs/reviews/2026-09-25-value-baseline.md`; `docs/reviews/2026-10-09-wave-3-registration.md` |
| crb's gate code | `src/crb/factory/standard.py:425-476`; `readiness.py:4-8, 13-19` |
| The signed demo export | `demo/outputs/ticket.md`, `crb-backlog-item.json`; `demo/MANIFEST.md` |
| Classifier chatter probe, re-run today | `cf/probe/probe.mjs` against `exmap/dist/server/classifier/rules-v1.js` [measured: n = 30 utterances, deterministic, 1 run] |
| Gate default; what is unexercised | `exmap/src/core/dod.ts:12`; `exmap/docs/INTEGRATION-NOTES.md:566-568` |

Every line cited below was re-read for this review.

---

## 3. What is right about the idea (protect these)

1. **It stands where crb's evidence locates the gap.** With the commit's tests, 30 of 37 first attempts were clean; without them, 14 of 37 [measured: n = 37 paired tasks; ADR-0026:55-60]. crb's answer for new work is `S2`, a person's failing test before any build [read: ADR-0026:315-321]. Agreed examples are that test's raw material [judgement].
2. **Examples state values**, and authored tests are expected to be weakest "where the oracle pins unstated values" [read: ADR-0026:559-561, crb's hypothesis]. This is the one credible way business context could raise pass rates [judgement].
3. **Two stages, two owners** (REQUIREMENTS §2): the business person owns the examples; "Engineers who know the product, or a verified standard" own stage 2 [read: REQUIREMENTS:24], including the API-shaped structural slots crb blocks on [read: `readiness.py:4-8, 13-16`].
4. **Honesty at the handover** (REQUIREMENTS §7): exmap reports crb's verdicts and never makes them.
5. **v1's honesty rules**: accepted questions never shown as answered; "self-asserted" said aloud; sign-off stale on any later change; export refused unless verified [read: `exmap/README.md:32-44, 219-223, 237-238`].
6. **Local-first capture, minimisation at export** [measured: far-end name occurs 0 times in 5 demo export files; `cf/practical.md` §1], and **ambiguity asks rather than guesses** [read: `exmap/README.md:187-190`].

---

## 4. What is weak or unproven, most serious first

**4.1 The value claim targets a context layer that measured zero, feeding a factory whose door is shut.** Claim: exmap "turns unstructured but guided context into structured context the factory can consume" [read: REQUIREMENTS:7], so it must raise outcomes to matter [judgement]. Basis: facts written without sight of the answer scored 33 of 48, the same as the message alone [measured: n = 48 per arm, upstream harness; ADR-0026:61-66]; per-class facts are "unmeasured, not falsified" [read: ADR-0026:67-69]; Wave 3 is "Prepared, not run" [read: `2026-10-09-wave-3-registration.md:3-4`]. Why it matters: v2's new effort all lands here. Settled by: Wave 3's `S1` against `S3` headroom, then a forward `S2` reading on a cell exmap feeds [read: ADR-0026:555-557].

**4.2 The thing with evidence behind it is parked.** Turning examples into a person's failing test is "Later, not asked" [read: `CRB-SEAM.md:422`]. So exmap's richest output lands as value slots, which crb routes rather than blocks on [read: `readiness.py:17-19`]. Settled by: the pilot in §7.

**4.3 Stage 1 has never met a real conversation.** Not verified: a real Teams call, Windows, macOS, the real Whisper path in a browser [read: `INTEGRATION-NOTES.md:566-568`]. The only end-to-end run is scripted with the offline classifier. Errors here compound into stage 2 [judgement]. Settled by: 8 real consented sessions with pre-registered measures (§7).

**4.4 The gate checks status, not meaning, and it signed a contradiction.** The signed rule reads as an amendment log ("Make that 24 hours for nurse appointments only. Keep two hours for GPs. Make the GP window three hours."), and a nurse example allows a two-hour cancellation against the 24-hour nurse rule [read: `demo/outputs/ticket.md:6,13`]. The brief asked for the complete requirement to be verified because "individually correct cards can contradict one another" [read: scratchpad `BRIEF.md:45`]. Voice confirmations count by default with no switch [read: `dod.ts:12`]. On the probe, chatter changed the map on 14 of 20 utterances; 5 of 6 one-word back-channels ("Yeah.", "Okay.", "Right.", "Good.", "Sure."; "Mm-hmm." changed nothing), and 6 of 20 chatter utterances, confirmed the last card [measured: n = 30, re-run 2026-10-16]; a voice confirmation is labelled in the check [read: `exmap/README.md:215`; `dod.ts:22-25`] but left out of the reviewer's confirmation preview [read: `demo/MANIFEST.md:64`]. "Human verified" licenses trust it has not earned. Settled by: a rule-against-example consistency check, voice confirmations off by default, a cold second reader on real maps.

**4.5 Information governance blocks NHS use before accuracy does.** The only "consent" in the code covers model download and Web Speech; the far end gets no notice; the verbatim transcript is kept indefinitely with no erasure route [read: `cf/practical.md` §1; grep of `exmap/README.md`, `docs/`, `src/` for GDPR, DPIA, retention: no hits]. crb's own retention rule is opt-in with a 30-day sweep [read: `docs/DATA-RETENTION.md:30`]. Settled by: a DPIA for the capture mode used, with an IG-safe mode (Me lane plus manual, or Teams transcript import) as default.

**4.6 The success criteria are partly unobservable or met by construction.** Criterion 1's acceptance cannot be seen while no item is built [read: `standard.py:456`]; its missing-context half can, through crb's readiness answers returned beside the stop (`dor_gaps`, `value_gaps`) and the intake comment's questions [read: `CRB-SEAM.md:359-360`; `src/crb/intake/feedback.py:423-425`] [judgement]. (Corrected: an earlier draft called criterion 1 wholly unobservable.) Criterion 2 is guaranteed by R15 [read: `CRB-SEAM.md:292`]; criterion 3's dominant stop is held against no element [read: `CRB-SEAM.md:362-363`]. None measures working software [judgement]. Settled by: adding "first-attempt clean on held-out tests for exmap-fed `S2` builds, with n" and "go-backs per signed map, by cause".

**4.7 Demand is unmeasured and the input does not match the map.** The factory has built 2 items [measured: n = 2; `2026-09-19-b1b-first-factory-pull-request.md:11-14`]; no real board has been read [read: `docs/dod/PLAN.md:200`, "a timed intake pass over a real board column" still to do], and no test or CI run contacts a real tracker [measured: n = 27 mocked requests; `2026-09-25-wave-report-since-2.0.0a1.md:162-164`]. Example Mapping yields feature stories, often M or L [judgement: unmeasured; Q8 and action 10 measure it]; crb's populated cells are `bug.fix` XS and S on libraries [measured: n = 81; ADR-0026:69-72]; blind L is 0 of 17 [measured; value-baseline:40]. Settled by: counting the target team's last 50 items by origin and cell (Q8).

**4.8 crb can falsify exmap's factory value but never attribute it.** The ticket is provenance, which "never splits a cell" [read: ADR-0026:110-118]; an exmap ticket and a hand-written one with a person's test pool in the same `S2` arm. Attribution needs about 62 tickets per arm for 0.70 to 0.90, 76 for 0.80 to 0.95, and 199 for 0.80 to 0.90 [judgement: arithmetic in `cf/measurable.md` §4]. Say so in the requirement.

**4.9 The person who runs exmap is not the person who signs.** Loopback only, one name for every click, reviewer name free text [read: `exmap/README.md:44, 63, 258`]; crb would call this "two-person rule not enforced at write" [read: `docs/EVIDENCE-AND-CLAIMS.md:299`]. Settled by: moving the signature to a system with real identities.

**4.10 Stage 2's fitness preview duplicates crb's intake comment**, which names every missing slot and the line that closes it before any spend [read: ADR-0017:65-72]. R19 to R28 wait until the ticket path proves insufficient [judgement].

---

## 5. Good answers to the four open questions

The lenses disagree on Q1 and Q4. I decide and say why.

**Q1. How stage 2 is produced.**
*Answer:* engineer-owned by default, done from the signed map on the board. Engineers may join the call where the product wants it. "Derived under a verified standard with no per-item check" is not offered until crb measures a `+facts@<drafter>` arm.
*Reasoning:* a person-typed fact is ticket content and rides any proven arm; a drafted fact is calibration-only [read: REQUIREMENTS:52; `CRB-SEAM.md:267`]. An engineer is needed anyway to write the `S2` test, so there is no autonomy to save. The practicality lens prefers "derived, one engineer check per handover" because engineers in the call worsen chatter and attribution; I answer that concern by letting the engineer work after the call. A click accepting a draft is a drafted fact with a person's name on it, the shape of the upstream leakage [judgement].
*Alternative:* derived with a per-item check, once the pilot shows engineers' slot answers are mechanical enough to template, or crb measures drafted facts with a lift.
*Commits the operator to:* engineer minutes per ask, recorded; no R6, R8 or R12 in the handover path.

**Q2. Whose standard.**
*Answer:* crb's, as crb embodies it, with crb's two-person rule and crb's accounts. exmap keeps no parallel standard and no identity of its own.
*Reasoning:* the three lenses that answer it agree (premise, practicality, alternatives; the measurability lens does not answer Q2). A lighter standard produces context crb will not admit and duplicates crb's machinery. Signing through crb or the board also settles 4.9 without a hosted service [judgement].
*Alternative:* a one-verifier exmap standard, only if exmap is used with no crb and no board behind it; then the badge reads "Signed off by <name> (self-asserted)".
*Commits the operator to:* a crb deployment or board approval in every real handover; R30 to R33 and R41 off the list.

**Q3. Calibration-only for drafted context.**
*Answer:* accept it. Do not propose that crb measures `+facts@<drafter>` now.
*Reasoning:* it is crb's rule [read: ADR-0026:548]. For conversation-sourced facts that arm would read prospectively only, because a person signing today knows the history [judgement: from ADR-0026:430-433 and the leak guard, 284-288; mechanically drafted context may certify retrospectively, 217-219], so at least 7 to 8 months to a first look on click and 5 to 9 years on koa and cobra [read: ADR-0026:444-446, crb's projection for twenty commits, the first of the looks at 20, 30 and 40 (:543)]. The only measurement, upstream and with a flawed control, shows no lift; per-class facts are unmeasured (4.1) [judgement]. The answer rests on that duration and the cheaper route below, not on a measured zero. It would spend a cell's error budget on exmap's weakest output. Propose instead the route crb has built and not run: a person's failing test from the agreed examples, read as `S2` [read: ADR-0026:555-557].
*Alternative:* propose the `+facts` reading once a cell exmap feeds has an `S1` standard and engineers' slot answers prove templatable.
*Commits the operator to:* no autonomous stage 2 in the handover path; the `S2` pilot in §7.

**Q4. The improvement budget.**
*Answer:* defer the loop. Until a cell exmap feeds reaches `needs_context`, the paid budget is zero. When the loop starts, count it in people's verification minutes per story, set per product by the product's owner, with model spend as a secondary cap.
*Reasoning:* the loop has no attributable signal: cell-state stops are held against no element [read: `CRB-SEAM.md:362-363`] and `needs_context` is never reached [read: `CRB-SEAM.md:160`]. crb's loop has not yet applied a change: 0 of 29 classes closed [measured: n = 29 classes; value-baseline:51]; recurrence per 50-attempt window ranged 12% to 66%, ending at 50% on a partial window of 28 [measured: n = 278 attempts; value-baseline:57-62]; the switch is off and nothing has been measured after a change [read: value-baseline:155-157]. That is no evidence a loop cannot learn, so deferral rests on the two seam points alone (corrected: an earlier draft cited crb's curve as a loop failing to learn). The lenses split three ways (a minutes cap now; zero paid spend; deferral). Deferral wins: a budget for a loop with no attributable signal is spend without a reading. The minutes unit is kept because verification time is the scarce input; crb's own 13 patch reviews were all a model's, none a person's [measured: n = 13; value-baseline:123-124].
*Alternative:* an unpaid loop (classification and replay of exmap's own checks), switch off by default.
*Commits the operator to:* R34 to R40 off the list; rising review time per card treated as a failure signal when the loop starts.

---

## 6. Questions the requirement should ask

**Q5. Lawful basis, notice, retention and erasure.** Who is the controller? What do participants see before the Call lane runs? What is the retention window, and how is one person's utterance erased without breaking the chain (hash a commitment in the chain, keep the text in a deletable side store)? A gate on the Call lane, not a README line [judgement].

**Q6. Who runs exmap, who signs, and what does "Human verified" license?** Name what a signer attests to and what they do not; carry "signed by facilitator, not PO" to the ticket (4.9).

**Q7. Is live capture needed?** A Teams transcript carries real identities, Teams' consent banner and the organisation's retention policy, and exmap already replays a conversation file [read: `exmap/docs/DESIGN.md:1307`]. Live against transcript is untested; the operator's preference is the only basis [read: scratchpad `BRIEF.md:8`].

**Q8. What share of the team's work starts as a conversation and lands in a cell crb could certify?** Bugs and chores arrive as tickets and should go through crb's intake directly. If conversation-first asks are rare, exmap is a facilitation aid, not a factory front end [judgement].

---

## 7. Recommended next step

**Riskiest assumption exmap owns:** a signed map from a real conversation carries what an engineer needs to produce sized, one-class, one-repository items and one failing test per example without going back to the business. A proven cell is a bigger risk, but it is crb's to buy down (Wave 3, about $74 to $89 [read: ADR-0026:494-501, crb's projection]); exmap reads that result rather than waiting on it.

**The experiment: a paper-handover pilot, about 6 weeks [judgement: `cf/alternatives.md` §4.2], people's time only.**
- *Before it (1 to 2 weeks [judgement: `cf/alternatives.md` §4.1]):* `requireHumanConfirm: true` by default; structured example rows with a contradiction check that fails the gate; the IG-safe capture mode (Me lane plus manual, or transcript import) or a participant notice; size and class required at handover.
- *Setup:* one product team, one repository the operator controls, 8 real consented asks that start as conversations. Per ask: a stage 1 session and signature; then an engineer who was not in the session turns the map into board tickets, sized, one class each, slots filled, with one failing test per example. crb's intake comments on the tickets where a listener can be switched on.
- *Recorded:* every go-back, by cause (missing example, contradiction, ambiguity, technical fact the business could not know); engineer minutes from map to ready tickets; item count and sizes; live map against transcript-imported map where both exist; a cold second reader's contradiction count.
- *Success:* at most 1 of 8 maps causes a go-back for a missing or contradictory rule or example; median engineer time below a pre-stated estimate for refining a comparable ask the usual way; a cold reader finds no contradiction in at least 7 of 8.
- *Kill:* 3 or more such go-backs (catches a 40% true rate 69% of the time, spares a 10% rate 96% of the time [judgement: exact binomial, `cf/alternatives.md` §4.2]); engineer time not below the estimate; fewer than 8 suitable asks in 6 weeks; or IG refuses every capture mode. On a kill, drop the factory claim and judge exmap as a workshop tool, or take the ticket-template path with no separate tool.
- *Then, if it passes and Wave 3 shows `S1` well short of `S3`:* the 10-ticket descriptive `S2` pilot on calibration builds, stop at the third miss, no reading registered [read: `cf/measurable.md` §4 Tier 1]. The pilot's engineer-written tests are those failing tests.

**Defer:** the thin stage 2 slice (product and repository config, several sized items, coverage, staleness, named `S2` author with crb identity) until the pilot reads. **Do not build yet:** R6, R8, R12; R19 to R28; R30 to R41; per-OS live-audio work; any Teams bot.

---

## 8. Actions

| # | Action | Owner | Why |
|---|---|---|---|
| 1 | Restate §1's value as "agreed example rows that become a named person's failing test on items small enough to route"; promote "Later, not asked" to the core | operator | The test is the only measured lever (4.1, 4.2) |
| 2 | Replace the three success criteria with working-software and go-back measures, each with n | operator | Current ones are partly unobservable or met by construction (4.6) |
| 3 | `requireHumanConfirm` true by default; show voice-confirmed cards in the review preview | exmap | 5 of 6 one-word back-channels confirmed the last card, and the preview leaves voice confirmations out (4.4) |
| 4 | Example rows with a rule-parameter contradiction check that fails the gate; amendments rewrite the rule rather than append | exmap | The demo signed a contradiction and an amendment log (4.4) |
| 5 | Make size and class required at handover | exmap | Size is optional at export and defaults to unsized [read: `exmap/src/web/components/ExportDrawer.tsx:20, 49, 106`; `exmap/src/export/index.ts:65`], and the demo's was unsized, crb's first stop [read: `crb-backlog-item.json:14`; `standard.py:425-432`]; who set it is already recorded [read: `demo/outputs/ticket.md:22`] |
| 6 | Teams `.vtt` and pasted-transcript importer; participant notice; documented IG-safe mode | exmap | Enables real sessions and answers the notice gap (4.5, Q7) |
| 7 | Badge shows signer, "self-asserted" and unanswered-question count | exmap | "Human verified" claims more than the gate checks (4.4, Q6) |
| 8 | Run the 8-ask pilot with pre-registered criteria; time everything | operator | Tests the riskiest exmap-owned assumption at no crb cost (§7) |
| 9 | Commission a DPIA; set a transcript retention window and an erasure route | operator | Blocks NHS use before accuracy does (4.5, Q5) |
| 10 | Count the last 50 items by origin and crb cell | operator | Demand and fit are unmeasured (4.7, Q8) |
| 11 | Make the ticket path the default handover; let crb's intake comment do the fitness check | exmap | No code, replaces R19 to R28 (4.10) |
| 12 | Run Wave 3; publish `S1` against `S3` per cell | crb | The only source of ceilings and of `S2` headroom (4.1) |
| 13 | Run the timed intake pass over one real board column, on the pilot's tickets | crb | crb's pending milestone [read: `docs/dod/PLAN.md:200`]; shows whether its comment closes the engineer's gaps |
| 14 | Freeze R6, R8, R12, R19 to R28, R30 to R41 until actions 8 and 12 read; state in §10 that crb can falsify exmap's factory value but never attribute it | operator | Unadmitted context, a loop with no signal, and provenance that never splits a cell (4.1, 4.8, Q3, Q4) |

---

## 9. Operator's response (2026-10-16) and what it changes

**The operator corrected the premise.** Live transcription exists so the map appears and changes on screen in front of the people deciding. The bottleneck is review time, and exmap brings the review inside the conversation, as close to the decision as possible, at the lowest effort and with the best experience. This review measured exmap mainly by factory pass rates and treated its gates as a burden; it should have treated human review minutes as the target. What changes [judgement throughout]:

1. **Q7 is answered: live capture is the product.** A Teams transcript import is after-the-fact review, the cost exmap removes. It stays only as a fallback where information governance forbids live capture (action 6). The governance work in 4.5 and Q5 still has to happen, as a participant notice and consent inside the live flow.
2. **exmap has value before any crb cell is proven.** Less review time on agreed requirements is worth having on its own. The "zero deliveries today" point in §1 limits the factory arc, not the product.
3. **v1 does not yet deliver the premise.** In the demo, sign-off needed a long run of clicks in the Review drawer after the conversation ended (accepting four questions, marking cards reviewed, accepting three acts). That is the after-the-fact review. The next build should move those acts into the flow of talk.
4. **The confirmation flaw in 4.4 becomes the central design problem.** Voice confirmation is what makes in-conversation review cheap, and it is also what turned "yeah" into a decision 5 times in 6. The fix is a confirmation that is cheap and deliberate, not voice confirmation switched off.
5. **Latency and wording become critical, and both are unmeasured.** The on-screen rule must read as the agreed rule within seconds. The offline classifier is instant but appends corrections verbatim; the Claude classifier's latency was only estimated in the design, at 20 to 45 seconds per utterance [read: `exmap/docs/DESIGN.md` §17]. Measure both on real speech before anything else.
6. **Q1 shifts towards live.** The same argument applies to stage 2: where engineers can attend, a live technical session on the same engine brings technical review into the conversation too. Derived-then-checked becomes the fallback, not the default.
7. **The pilot measures review time and how requirements fare.** Record the human minutes from the start of the conversation to a signed map, and on to ready tickets; how many on-screen decisions are reopened later; and engineer go-backs. Together these are the first calibration data for the loop below.

Q2, Q3 and Q4 stand. Counting the improvement budget in people's review minutes now matches the operator's bottleneck exactly.

**A second correction: review is calibrated, not minimised.** The operator challenged the aim of reducing review minutes. The aim is to calibrate human review time against how the requirements it produces fare, in a self-learning loop that finds common requirement gaps and feeds them back to the review as suggested discussion topics and proposed story elements. This is the right objective: minimising minutes would reward rubber-stamping. It mirrors crb, which looks for the least context that gives a proven pass rate per class of work; exmap would look for the review that gives a proven requirement success rate per kind of ask [judgement]. What it needs:

- **A definition of requirement success** (REQUIREMENTS Q5). Fast signals are decisions reopened and engineer go-backs; slow signals are first-attempt factory results and later defects traced to a missing rule or example. The slow ones are the strongest and arrive weeks or months later.
- **Traceability end to end.** A defect can be traced to a requirement gap only through the rule and example links to work items that stage 2 already requires (REQUIREMENTS §4.3).
- **Volume per kind of ask.** Calibration is only as good as its sample; report every rate with its n, as crb does.
- **Suggestions that stay proposals.** A suggested discussion topic is low risk. A suggested rule or example is higher risk: the group may accept a drafted requirement because it is on screen, which is the rubber-stamping the calibration is meant to catch. Record which suggestions were accepted and compare how those requirements fare.
- **A gap catalogue governed as a standard.** It is the business-level counterpart of crb's readiness slots: crb's slot questions are written by hand; exmap would learn its own per kind of ask, proposed by the loop and verified by people.

**A third correction: the full cost of the change is what is calibrated.** The operator wants participants tracked, who they are and their roles, so the full cost of a change is known, and the right people are used to deliver the outcome needed, measured against the value the context delivers. This is a cost-effectiveness question per kind of ask, and it is the right frame for "the right resource" [judgement]. What it needs:

- **Identity beyond lane labels.** v1 knows only the speaker label a person gives each capture lane, and does no diarisation [read: `exmap/README.md` audio section]. Attendance, role and time present can be recorded reliably; who contributed what cannot without per-person capture or diarisation, so cost should rest on attendance first.
- **Governance for people data.** Relating named people to the success of their requirements is employee monitoring under UK GDPR, needing a lawful basis, transparency and a DPIA, and it may change how people take part. Calibrating by role and cost band answers "the right resource" without ranking individuals (REQUIREMENTS Q6).
- **Downstream cost from crb.** crb already derives each stream's durations and its spend from recorded moments and graded rows' `cost_usd` [read: `docs/API.md`, Flow section]. The full cost joins that with the people cost of the conversation, through the rule-and-example links to work items.
- **Stratification.** The complexity of an ask drives both who attends and how it fares, so every comparison must be within a kind and size of ask, with its n, or it will credit senior people for hard asks going badly and junior people for easy ones going well.

