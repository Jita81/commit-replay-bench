# Example Map Live: business requirement v2

**Status.** For the operator to confirm; six open questions are in §10. It supersedes the business requirement in `docs/DESIGN.md` §1 where they differ. v1's interaction model and verification gate are kept. Design detail, including every crb endpoint, label, stop code and citation, is in `docs/CRB-SEAM.md`. Sources: the v1 brief, and the operator's two messages after v1 shipped ("Msg 1", "Msg 2").

## 1. The value

**exmap turns unstructured but guided context into structured context the factory can consume.** In the operator's words: "the value of this is decomposition of unstructured but guided context into structured context that allows for factory consumption" (Msg 1).

A second arc of value is "ensuring that ticket matches what would be needed for context for the factory for the ask (which may require multiple factory components)" (Msg 1). A verified Example Map is therefore a step, not the finish line. Done means the factory receives work it can accept, carrying the context it needs, for everything that was agreed.

**The bottleneck is review time, so review happens inside the conversation.** The operator: "The idea of live transcript is so that we can talk about it and have it appear and change on the screen in front of them. Remember that our bottleneck is review time. Here we are bringing the review within the conversation and therefore making it as close to the decision making as possible and the lowest effort possible with the best UX possible." Live capture is therefore the product, not a convenience: a transcript reviewed after the meeting is the after-the-fact review exmap exists to remove. This sets three conditions on the experience:

- what people see changes within seconds of what they say, worded as the agreed rule rather than as a log of corrections;
- confirming a card is the cheapest act on screen, and deliberate: a listening cue such as "yeah" is never taken as a decision;
- whatever the Definition of Done needs is settled during the conversation, so little or no review is left for afterwards.

**Review is calibrated, not minimised.** The operator: "I would challenge the point on wanting to reduce human review minutes. I don't think that's quite right. We want to calibrate human review time vs success rates of their requirements in a self learning loop that allows us to identify common requirement gaps and feed that back to the review process with suggestions of discussion topics and even elements of the story itself." The aim is not the fewest review minutes; it is review spent where it changes how requirements fare.

**What is calibrated is the full cost of the change.** The operator: "it's not just the review time. We should be tracking participants and who they are so that we can understand the full cost of the change. That's what we are really calibrating. We want the right resource used to deliver the [outcome] we need and that's something I think we can measure from the value we get from the context." The bracketed word is a reading of the operator's text. The cost side is everyone's time on the change, by who they are and what role they played, plus what it cost downstream. The value side is how the requirement fared (Q5).

We will know it works when:

- the factory accepts exmap's work items without a person going back to ask for missing context;
- every agreed rule and example can be traced to the work items that carry it;
- stops of the same cause become rarer as the improvement loop runs.
- the full cost of each change is known, from who took part, in what role and for how long, through to its downstream cost; and for each kind of ask the loop shows which mix of people and effort delivers the outcome needed at the least cost.

## 2. The two stages

**The business requirement and the technical decomposition are separate stages, with different owners and different sign-offs.** The operator: "we would need to understand sufficient technical details about the product but that should be split" (Msg 1).

| | Stage 1: the business map | Stage 2: the factory decomposition |
|---|---|---|
| What | v1 as built: story, rules, examples and open questions from the conversation | The signed map turned into factory work items |
| Owner | The responsible business person | Engineers who know the product, or a verified standard (§3) |
| Done when | v1's Definition of Done passes and the map is signed | Every item meets §4 and the handover is honest (§7) |

Stage 2's handover replaces v1's single-item export. A change to the signed map makes stage 2 stale until it is redone.

## 3. Product, repositories and technical information

**Work belongs to a product, and the product decides what technical knowledge applies.** The operator: "I would expect this work to be attached to a product. The product might have multiple repos. Id expect to know from the work which repo and from the repo which technical information matters for the ask" (Msg 2).

1. Every piece of work is attached to a product. Stage 2 cannot start without one.
2. A product names its repositories.
3. Each work item states its repository. Where the evidence does not settle it, exmap asks; it never guesses.
4. For each repository, what technical information matters for a given kind of ask is itself a standard (§5), not a guess made fresh each time.
5. How stage 2 is produced is set per product: live, with engineers in the room on the same conversational engine, or derived from the product's knowledge under a verified standard. The operator: "On 1 I guess that depends on the product" (Msg 2). Both routes must be supported; Q1 asks which is the default.

crb has no product today; it knows repositories. exmap therefore keeps the product record until crb has one.

## 4. What each work item must be

**Each item is one unit the factory accepts, carrying what the factory asks of that kind of work.**

1. An ask that needs several factory components becomes several items, in order, each in one repository and one kind of work.
2. Each item carries everything the factory's entry gate asks for its kind of work, including a size.
3. Every agreed rule and example is carried by at least one item, and every item names the rules and examples it carries.
4. An open question accepted as outstanding stays open on every item it concerns. It is never shown as answered.
5. Every fact names where it came from: a named person, exmap's drafting, or a source such as a repository file at a commit.
6. Any change to the signed map, to an item, or to a source an item relied on makes the handover stale.

**One tension needs a decision.** The factory may show a builder only context its standard was measured with. Facts exmap drafts or derives have not been measured, so such items may only feed the factory's calibration builds until the factory measures that kind of context. That limits the value of autonomous decomposition. Q3 asks how to resolve it.

## 5. The standard

**Context is produced and governed by the organisation's standard.** The operator: "we must follow our standard" (Msg 2). Restated as requirements:

1. exmap attempts to produce the context a task needs autonomously.
2. Where a single standard is used repeatedly, exmap proposes it, people verify it before it is reused, and it improves from continuous processing feedback.
3. Where a standard is put together for one task, the standard and the history of the ways it was used are the artefact that is monitored.
4. Every such element is process configuration: versioned, with a named proposer, and changed only through §6.

This document reads "our standard" as the organisation's standard as crb already embodies it. Where crb already holds a reusable standard, such as kinds of work and their questions per repository, exmap reads it and proposes changes to it rather than keeping a parallel copy. exmap's own configuration is then limited to its own process: question wording, decomposition recipes, classifier prompts and its checks. Q2 asks the operator to confirm this reading.

## 6. The improvement loop and its budget

**Failures are traced to their cause, fixed where the cause is, and re-tested before the fix is kept.** The operator: "It's by properly understanding the failures that we can correctly identify the cause and make the changes in the right place retesting to verify. All of course can be done autonomously and at pace within a [continuous] improvement budget" (Msg 2). The bracketed word is a reading of the operator's text.

1. Each failure, such as a factory stop, a missing-context stop, a person's correction or a failed build, is traced to the element that caused it.
2. The change lands on that element, in the place that owns it. A change to something the factory owns is proposed to the factory.
3. A change is kept only when re-testing shows the failure gone and nothing new broken.
4. The loop runs autonomously and at pace, within a declared improvement budget. A named person can stop it or revert any change.

The same loop learns from requirements themselves:

5. For each kind of ask, the loop relates the review spent on a requirement to how that requirement fared, and reports that calibration with its sample size.
6. It finds the requirement gaps that recur, and feeds them back into the live session as suggested discussion topics and as proposed elements of the story, such as rules, examples and questions.
7. A suggestion is always a proposal. It appears as a proposed topic or card, becomes part of the map only through a deliberate confirmation, and the loop records which suggestions were taken and how those requirements then fared.
8. The catalogue of recurring gaps is itself a standard (§5): proposed by the loop, verified by people, improved from feedback, with its history of use kept.
9. Each session records who took part, in what role, and for how long, and every participant knows it is recorded. Who said what stays what people assigned; exmap does not infer a person's contribution.
10. The full cost of a change joins the people cost of its conversations with its downstream cost: engineers' time, the factory's spend and any rework, through the links from rules and examples to work items (§4).
11. For each kind of ask, the loop relates the mix of roles and the effort spent to how requirements fared, and suggests who to involve as well as what to discuss.

## 7. Honesty at the handover

**exmap reports the factory's verdicts; it never makes them.**

1. Before handover, exmap checks what it can and says which checks are its own.
2. Every factory answer is shown as the factory gave it. No stop is hidden, and none is computed by exmap.
3. exmap never registers work in the factory. A named factory operator does.
4. What the factory lacks is proposed to it, never worked around inside exmap.

## 8. Where people act

| Act | Who |
|---|---|
| Sign the business map | The responsible business person |
| Answer a clarification | Whoever was in the conversation |
| Check a derived decomposition, where the product asks for it | An engineer on the product (Q1) |
| Verify a reusable standard before it is reused | A named person (Q2 settles whether two are needed) |
| Register work, fund calibration builds, queue factory runs | The factory's own operators and approvers |
| Stop the improvement loop or revert a change | A named person |

## 9. Non-goals

v1's non-goals stand. In addition, exmap does not:

- decide anything the factory's gate decides;
- write to the factory;
- edit the factory's catalogue, classes, thresholds or rules;
- run the factory's own learning loop.

## 10. Assumptions and open questions

**Assumptions, to confirm or correct:**

1. "That should be split" means a separate stage in exmap. The other reading is a separate requirement for product knowledge.
2. "Multiple factory components" means several work items, across kinds of work and repositories.
3. A standard counts as "used repeatedly" from its second task, so it is verified before that second use.
4. When the improvement budget is spent, the loop stops paid work only; its unpaid work goes on.
5. Stage 2 may make network calls to the product's repositories and to a connected crb deployment. v1 makes none beyond the speech model download and the classifier.
6. exmap keeps the product record until crb has a product.

**Open questions for the operator:**

**Q1.** For a given product, is stage 2 produced live with engineers, derived and checked by a person per item, or derived under a verified standard with no per-item check, and which is the default?

**Q2.** Does "our standard" mean crb's context standard as crb embodies it, with crb's two-person verification and crb's accounts, or a lighter standard exmap keeps itself with one named verifier, as v1's sign-off does?

**Q3.** Context exmap drafts or derives reaches a builder only once the factory has measured that kind of context. Do you accept that such items feed calibration builds only until then, and should exmap propose that measurement to crb?

**Q4.** What is the improvement budget: what it is counted in (model spend, people's verification time, factory runs), how large it is, who sets it, and whether it is per product or overall?

**Q5.** What counts as a requirement's success: decisions taken on screen not reopened later, engineers not going back to the business, the factory building its items clean at the first attempt, no later defect traced to a missing rule or example, or a combination; and how long should the loop wait for the slow signals?

**Q6.** Is the calibration of roles, or of named people; where do the cost rates come from; and who may see the results? Measuring named individuals' contribution to outcomes is employee monitoring, with its own governance, and may change how people take part.
