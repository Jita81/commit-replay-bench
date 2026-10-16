# Example Map Live: business requirement v2

Supersedes the business requirement in docs/DESIGN.md §1 where they differ; v1's interaction model and verification gate are kept.

**Status.** For the operator to confirm. Stage 1 is v1's business conversation, kept as it is. Stage 2, the factory decomposition, is new, and so is the improvement loop. The handover replaces v1's one-item export.

**Sources.** "Msg 1" and "Msg 2" are the operator's two messages after v1 shipped. "v1 brief" is the original requirement, restated in `docs/DESIGN.md` §1 and §2. crb citations are to crb at commit `a037820`. `ADR-nnnn` means `docs/adr/nnnn-*.md` at the repository root, and `:n-m` gives its lines. Other paths are relative to the repository root.

**Tags.** **[operator]** restates the operator's words. **[crb]** follows from crb's documented standard, with the ADR or file cited. **[inferred]** is this document's inference, listed again in §9.1. Where a requirement mixes sources, each tag names the part it covers.

---

## 0. The two decisions and the operator's answers

**The operator answered two decisions. Neither answer picks an option as posed. Both say how the work should be done.**

| Decision as posed | The operator's answer (Msg 2, verbatim) | Read here as |
|---|---|---|
| 1. How does the decomposition happen: a second engineers' refinement call on the same live engine, or generated from the verified map plus product knowledge, then verified by an engineer? | "On 1 I guess that depends on the product. I would expect this work to be attached to a product. The product might have multiple repos. Id expect to know from the work which repo and from the repo which technical information matters for the ask." | exmap derives the decomposition from the signed map and the product's repositories, so it differs by product (A2). Whether an engineer verifies each one is Q1. Whether a live call is ever wanted is Q2 |
| 2. Where does product knowledge come from: a connected crb deployment's API, reading the repositories directly, or both? | "I think for 2 we must follow our standard. We can attempt to produce the context we need for our task autonomously but where a single standard is used repeatedly we propose and have humans verify and improve based on continuous processing feedback or alternatively it's a standard that is put together per task in which case I would expect the standard and a history of ways it was used to be the artifact we are monitoring." | Both: the repositories themselves, and crb where a deployment is connected (A3). "Our standard" is the one this answer describes, with crb's mechanisms on top (A1) |

The operator went on: "Elements like this are essentially config for our process. It's by properly understanding the failures that we can correctly identify the cause and make the changes in the right place retesting to verify. All of course can be done autonomously and at pace within a [continuous] improvement budget." The bracketed word is this document's reading of the operator's text.

---

## 1. The value

**exmap's value is decomposition: it turns unstructured but guided context into structured context the factory can consume.** The live conversation is the input. A verified Example Map is a step on the way.

The operator (Msg 1):

> So the value of this is decomposition of unstructured but guided context into structured context that allows for factory consumption.
>
> There's an additional arc of value around ensuring that ticket matches what would be needed for context for the factory for the ask (which may require multiple factory components).
>
> I feel like we would need to understand sufficient technical details about the product but that should be split.

| Arc | What it means in crb's terms | v1 today |
|---|---|---|
| 1. Decomposition | A story, rules, examples and questions, then work items crb's backlog accepts | Delivered for the business half: a person-verified Example Map with provenance |
| 2. Fitness for the ask | Each item carries what crb asks a ticket for: a class, a size, the structural facts the class needs, and what the cell's standard needs (ADR-0026 item 8, :302-310) | Not delivered. One item of one class. Slot facts are typed at export, outside the sign-off. Size defaults to `unsized`, which crb sends to a person (`exmap/src/export/index.ts:64-66`; `src/crb/factory/standard.py:425-432`) |

**Sufficient technical detail, split out.** exmap needs enough technical detail about the product to make each ticket fit the ask. Msg 2 bounds it as the technical information that "matters for the ask". It lives in a separate stage (A5).

**What exmap controls.** crb admits a ticket "only when its cell has a proven standard and the ticket carries it" (ADR-0026 :302-303). exmap controls what the ticket carries, not the cell's standard. Today no cell has a proven standard (ADR-0026 :69-77), so every ticket stops or runs as a calibration build that cannot deliver (ADR-0026 :529-530).

---

## 2. The split

**There are two stages. Stage 1 is v1, kept, and a responsible person signs it. Stage 2 is new: exmap derives the factory items itself from the signed map and the product's repositories, and asks a person only what it cannot tell. Registering the items stays crb's act.**

| | Stage 1: business map (v1, kept) | Stage 2: factory decomposition (new) | Handover |
|---|---|---|---|
| Who does it | The person responsible for the business intent (v1 brief §0) | exmap, under verified standards (§4). People answer only its clarifications | exmap exports files. A named crb operator registers them |
| Input | The live, guided conversation | The signed stage 1 revision; the product, its repositories and each repository's technical-information profile; crb's answers where a deployment is connected | Stage 2's items |
| Output | One story with rules, examples and questions, each with provenance | Work items. Each has one repository, a class, a kind, a size, structural facts with their origin, dependencies, the rules and examples it carries, and a stamp of every standard version used (R17) | Files for the backlog path or the ticket path (§3) |
| Done when | The intent is agreed, the five Definition of Done checks pass and the map is signed | Every rule and example is carried (R15), every item passes exmap's checks (R22), and every crb answer and expected stop is shown (R25) | crb's entry gate decides |
| A person's check | The v1 sign-off (v1 brief §1 item 8) | The earlier verification of each reusable standard version used (R31). No per-task sign-off unless the operator wants one (Q1) | crb's register act (ADR-0020 §9, :444-447; ADR-0022 :102-104) |
| Made stale by | Any substantive change to the map | A new stage 1 revision; a change to any item or fact; a source it used moving (R18-R20) | crb's own rules (ADR-0017 :53-63) |

The flow:

1. Talk. The business map forms (stage 1, v1).
2. The responsible person signs it.
3. The work is attached to a product.
4. exmap reads the product's repositories and crb, proposes each item's repository, splits the work into items and answers the slot questions. It asks a person only when it cannot tell.
5. exmap checks each item and shows crb's answers and the stops crb is expected to apply.
6. exmap exports the handover. A named crb operator registers it.
7. crb's outcomes come back and feed the improvement loop (§5).

---

## 3. Product, repositories and the technical information that matters

**Work belongs to a product, and a product has one or more repositories. The work says which repository. Each repository's profile says which technical information matters for the ask. exmap reads that information from the repository itself and from crb. crb knows a great deal per repository, but it has no product and never decides which repository an ask touches.**

| Link | The operator (Msg 2) | What crb has today | What exmap adds |
|---|---|---|---|
| Work to product | "I would expect this work to be attached to a product" | No product entity. None of the store's tables is one (`src/crb/store/models.py:116-625`). "One deployment per organisation" (`docs/ARCHITECTURE.md:60`) | A versioned product record (R3) |
| Product to repositories | "The product might have multiple repos" | Repositories keyed by name (`docs/API.md:87`). Whether a cell may pool several repositories "is not decided" (ADR-0026 :569-570) | The product's repository list (R2) |
| Work to repository | "Id expect to know from the work which repo" | Never decided by crb. The only tie is the column a repository's listener watches (`src/crb/server/intake.py:278-292`). No route classifies free text (`src/crb/intake/draft.py:315`) | A proposal per item that asks only when the evidence is ambiguous (R4) |
| Repository to the technical information that matters | "and from the repo which technical information matters for the ask" | Readable with the `viewer` role: config, change profile, posture, library entries, the capability map with each cell's standard and route, and the readiness catalogue (`docs/API.md:87-326`). The catalogue is global and "static per release" (`docs/API.md:322`). Readiness reads only the code catalogue, not signed work-type slots (`src/crb/factory/readiness.py:425-437`) | A technical-information profile per repository (R6), and reading the repository's files at a pinned commit, as crb's miners do (R5) |

**crb's gate verdict before registration.** On the ticket path, crb's intake runs readiness and the entry gate on every ticket it drafts, before any registration (`src/crb/server/intake.py:1352-1361`). It serves the stop on the intake row as `entry_stop`, `entry_reason` and `entry_needs` (`src/crb/server/intake.py:344-349`; `docs/API.md:333`). On the backlog path, the stop is served once the item is registered, as `entry` on `GET /factory/{repo}/tasks` (`docs/API.md:326`). No route previews an item that is on neither path. Q4 asks which route exmap should use.

**One item, one repository.** A crb item belongs to one repository's backlog, and `depends_on` must name an item in the same backlog (`src/crb/factory/backlog.py:205-218`). An ask that spans repositories becomes items in several backlogs, and crb cannot express the order between them.

**Access.** crb accepts a cookie session only. A tool without a browser uses a local crb account, as crb's MCP server does (`docs/API.md:13-22`; `docs/MCP.md:56-58`). The `viewer` role reads everything above. exmap's account holds `viewer` only (R26).

**Two uses of technical knowledge, kept apart.**

| Use | What it covers | Who sees it |
|---|---|---|
| To decompose | Choosing the repository, class, size, split and dependencies, and answering slot questions. Draws on the repository's files and on crb's config, change profile, library and capability map | exmap and the people it asks. It stays in the decomposition evidence |
| To carry on the ticket | Only what the item's cell standard needs. For `S1`: "the structural facts the test author reads, one `slot: text` line each". For `S2`: "a failing test a person wrote, attached to the ticket before any build" (`src/crb/factory/standard.py:128-132`) | The builder, which "gets that arm's context and nothing it was not measured with" (ADR-0026 :308). Library entries never reach a brief (`docs/API.md:227-230`) |

**Two handover paths.** v1 exports both a backlog item and a tracker ticket. crb treats them differently, so each requirement that touches crb says which path it holds on.

| | Backlog path (`crb-backlog-item.json`) | Ticket path (`ticket.md` in a watched column) |
|---|---|---|
| Who registers | A named crb operator, with `POST /factory/{repo}/backlog` or `/backlog/evolutions` (`docs/API.md:324-325`) | A named crb operator's Register act on the intake draft (ADR-0022). crb registers at once when approval is off or the author is on the allowlist (`docs/API.md:335`) |
| Repository | The route's `{repo}` | The column the repository's listener watches (ADR-0017 :42-43) |
| Item id | exmap's id | `<tracker>-<key>`; an edit is `<id>.r<revision>` (ADR-0017 :38-40, :53-57) |
| exmap's stamp (R17) | Labels | Tracker tags, which crb keeps in `labels.tags` (`src/crb/intake/draft.py:582-623`) |
| Order between items | `depends_on`, same repository only | None; exmap records it (R14) |
| An edit | An evolution with `supersedes` (R21) | crb's own evolution of the ticket |
| Organisation class set | Read in the global cell; the class-set labels are reserved to intake (`docs/API.md:279-284`) | crb reclassifies the item by the set's rule (`src/crb/server/class_set_state.py:221-251`) |
| Gate verdict | After registration (`GET /factory/{repo}/tasks`) | Before registration (the intake row) |
| Outcomes joined on | The item id | `labels.ticket` |

---

## 4. How context is produced, following the operator's standard

**exmap produces each task's context itself. When a reusable standard produced it, the person's check is the earlier verification of that standard's version, not a check on each item. A standard put together for one task is not approved before use: the standard and its history of use are what is monitored. exmap asks a person only when the evidence does not settle a question.**

### 4.1 The operator's standard (Msg 2)

| The operator's words | What exmap does | A person's part |
|---|---|---|
| "We can attempt to produce the context we need for our task autonomously" | Reads the product's repositories and crb, derives the items, answers the slot questions and records each fact's origin | None, except a clarification when the evidence is ambiguous |
| "where a single standard is used repeatedly we propose and have humans verify" | Proposes each reusable standard as a version: a repository's profile, the question wording, the decomposition recipe, the classifier prompt, the fitness checks | Verifies a version once, before it is used for a second task |
| "and improve based on continuous processing feedback" | The loop drafts the next version from failures and re-tests it (§5) | Verifies the new version |
| "a standard that is put together per task ... the standard and a history of ways it was used to be the artifact we are monitoring" | Keeps the per-task standard and an append-only history of its use. The loop monitors both, and a pattern that recurs becomes a proposed reusable standard | None before use |

### 4.2 crb mechanisms adopted on top

Each row is a design choice that rests on A1. The operator may veto any of them.

| Mechanism | crb source | Requirement | Cost if kept |
|---|---|---|---|
| Two different people verify a reusable standard: a sponsor and an approver | `docs/API.md:239, 269` (`same_person`, "never relaxed"); ADR-0026 item 10 | R31 | A second person per version |
| A model or a rule is never a person | ADR-0026 :414-418 | R29, R30 | None |
| Facts are labelled by origin; facts a model drafted are their own arm, `+facts@<drafter>` | ADR-0026 :106, :548 | R8 | While crb neither builds nor measures that arm, such items are fit only for a calibration build (Q7) |
| The builder sees only what its arm was measured with | ADR-0026 :308 | R9 | Repository facts beyond the class's slots stay off the ticket (Q8) |
| The loop never changes how work is judged | `docs/LEARNING-LOOP.md:354`; ADR-0020 §1 (:125-139) | R37 | Removing a check or lowering a floor needs a person |
| Failures are classified by a fixed rule with no model call | ADR-0020 §2 (:141-178), §10 (:477-478) | R35 | None |
| A keep and retire rule fixed in advance, against a frozen before window | ADR-0020 §6.3-§6.14 | R38 | None |
| Spend is checked before each paid call; an unpriced call is refused | ADR-0030 §3, §6 | R40 | None |
| Registration is a named crb operator's act | ADR-0020 §9 (:444-447); ADR-0022 :102-104 | R26-R28 | None: crb keeps it |

Not adopted: crb keeps its own loop's switch off by default "until the Phase B paired A/B shows a benefit" (ADR-0020 §4, :216-217). exmap's loop runs by default, as the operator asked, and a person can stop it (R39).

### 4.3 Limits crb puts on improving context

- What a builder sees improves only through measurement. crb never re-reads an `insufficient` arm, and a new class-set version is a new cell, "never a quiet way to buy another look" (ADR-0026 :246-248, :543-544).
- Improving exmap's questions leaves crb's arm unchanged only while the answers are a person's. The ticket a builder read is provenance (`ctx_ticket`, ADR-0026 :110-118), but facts a model drafted make a different arm (ADR-0026 :106). So exmap can improve its questions without waiting on crb. It cannot shortcut crb's measurement of what the builder sees.
- A set a person wrote is read prospectively only, "because a person signing today knows the history" (ADR-0026 :430-433).
- crb serves signals about its reusable standards: the decisions inbox's `entry_stale`, `signoff_stale` and `remeasure` (`docs/API.md:157`). Improving a standard from outcomes is not built. A library entry's effect reads `unmeasured`, no entry reaches a brief, and retirement by measurement is Wave 5 (`docs/API.md:227-241`; ADR-0026 :503-504). A class set changes only by proposing the next version (`src/crb/core/class_sets.py:18-19`). exmap does not rely on any of it.

---

## 5. Context elements are process config

**Every element that shapes context is config for the process. The loop traces a failure to the element that caused it, drafts a change to that element and re-tests it, autonomously, at pace and inside a budget. A person verifies the new version of a reusable standard before its next use. While no cell is proven, crb's entry gate never reaches `needs_context`, so the loop learns from exmap's own checks, crb's readiness answers, replays and the outcomes of calibration builds.**

crb's gate checks the cell's standard before it checks what the ticket carries. A sized item that needs no split stops `no_proven_standard` whenever its cell has no standard, and the `needs_context` clause is never reached (`src/crb/factory/standard.py:456-508`).

| Element | Makes context or judges it | Reusable or per task |
|---|---|---|
| The product record: its repositories, and each one's watched column for the ticket path | Makes | Reusable |
| Each repository's technical-information profile | Makes | Reusable |
| The question wording | Makes | Reusable |
| The decomposition recipe | Makes | Reusable |
| The assembly recipe that puts a per-task standard together | Makes | Reusable |
| A per-task standard | Makes | Per task |
| The classifier's prompt version (`exmap/src/classifier/constants.ts:16`) | Makes | Reusable |
| The classifier's confidence floor (`exmap/src/classifier/constants.ts:2`) | Judges | Reusable |
| The fitness checks (R22) | Judges | Reusable |
| The failure-classification rule (R35) | Judges | Reusable |
| The vendored catalogue copy | crb's: "a copy, never an edit" (`exmap/docs/DESIGN.md:1721`) | Used only without a deployment |

### 5.1 The signals, and where a change lands

| Signal | What it says about the context | Where the change lands |
|---|---|---|
| exmap's own check fails before handover (R22) | No size, no catalogued class, or a slot with no line | The question wording, the profile or the decomposition recipe |
| crb: `unsized` (`src/crb/factory/standard.py:425-432`) | exmap's size check let it through | The fitness check, by adding or tightening (R37) |
| crb: routed `human`, class not in the catalogue (`src/crb/factory/readiness.py:457-461`) | A wrong class, or a stale class list | The decomposition recipe; the catalogue source |
| crb: routed `human`, weak-oracle class or operator kind (`src/crb/factory/readiness.py:455-466`) | By design, a person must test | No exmap element. Report it |
| crb: `dor_gaps`, or `not_ready` (`src/crb/factory/loop.py:800-805`) | A slot was not asked or not answered, or crb read a different class (R24) | The question wording; the fitness check |
| crb: `value_gaps` | The value lives in the test | None. crb routes it to test-first authoring by design (`src/crb/factory/readiness.py:472-477`) |
| crb: `granularize` (`src/crb/factory/standard.py:433-443`) | The item is too large for crb's size rule | The decomposition recipe |
| crb: `needs_context`, reason `S1`, `needs` names slots | A structural slot is missing | The question wording for that class |
| crb: `needs_context`, reason `S1`, the need is a failing test by the standard's author (`is_test_need`, `src/crb/factory/standard.py:117-125`) | The run's test author is not the standard's | No exmap change. crb calls it "the operator's configuration, not the ticket's" (`src/crb/factory/standard.py:670-674`). Report it |
| crb: `needs_context`, reason `S2` | No person's failing test is attached | The stage 2 step that asks a person for the test (R7, R11) |
| crb: `no_proven_standard`, `unsigned_cell`, `not_licensed` (`src/crb/factory/standard.py:456-471, 521-536`; `src/crb/factory/loop.py:823-841`) | The cell's state, not the ticket | No exmap change. Report it |
| A calibration build's build, review or held-out acceptance result (`docs/API.md:326`) | Capability, unless a witness ties it to an element (R35) | None without a witness |
| Intent found wrong after sign-off | The business map | Reopen stage 1, which makes stage 2 stale |

### 5.2 Land the change, then re-test it

crb's practice, which exmap follows:

- Levels, strongest first: construction, a gate, mistake-proofing, then advice, "the fallback, never the first choice" (`docs/PREVENTION.md:42-45`).
- "The loop changes how a change is made, never how it is judged" (`docs/LEARNING-LOOP.md:354`).
- "Every ladder ends in a filed item" (ADR-0020 §5, :263-279).
- "The artefact is shown to fail: remove or break the prevention, run its test, see it fail, restore it" (`docs/dod/STANDARD.md:266-267`).
- The before window is frozen when a change is applied, "so later rows can never move it", and "Nothing retroactive" (ADR-0020 §6.5, §6.14).

exmap's replay provider and pure mappers ("same input → byte-identical output", `exmap/docs/DESIGN.md:1615`) let a failing case be replayed against changed config at once. A change that belongs to crb, such as a missing catalogue slot, a class or anything about grading, is prepared as a proposal for crb (R29).

### 5.3 Pace and budget

- **Pace.** A failure becomes a re-tested version in one replay run, without waiting for new items. The only wait is a person verifying a reusable version, which the operator asked for. The loop runs by default.
- **No model call to judge.** Classifying, attributing, choosing the element and measuring make no model call, as in crb's loop (ADR-0020 §10, :477-478). A model may draft a changed version. That drafting is the loop's paid work.
- **The budget.** crb has no continuous-improvement budget; a search of its docs and source found none. exmap must define one (Q5). crb's nearest budgets:

| Budget | What it caps | Status | Citation |
|---|---|---|---|
| Run spend cap `max_cost_usd` | What a run's attempts may cost together, checked with a reserve before every attempt | ADR Proposed; code and tests present | ADR-0030 §1-6 |
| Error budget per cell | Statistical risk across every reading of one cell | Accepted; in code | ADR-0026 §5 (:227-251) |
| Context budget | The lines crb's loop may add to a brief | Built, off | ADR-0020 §7 |
| Re-measurement spend | Runs the operator queues; it "asks again before it spends" | Built | `docs/LEARNING-LOOP.md:145-147, 214` |

crb's own loop is off on every repository, and no campaign has measured it (`docs/LEARNING-LOOP.md:460-466`; G-653). exmap does not depend on it.

### 5.4 Where a person acts, and why

| Step | Who | Why | Source |
|---|---|---|---|
| Sign the business map | The responsible person | "The human owns the meaning" | v1 brief §0; `exmap/docs/DESIGN.md` §1 |
| Answer a clarification | A person who knows | exmap "must ask rather than guess" | v1 brief §0 |
| Verify a reusable standard's version | A person; crb's rule adds a second (§4.2) | "we propose and have humans verify" | Msg 2; ADR-0026 item 10 |
| Sponsor a proposal to crb's library | A named person, in their own crb session | "a miner or a model is never a person" | ADR-0026 :414-418 |
| Register an item on a crb backlog | A named crb operator | "Nothing is registered by itself, because a frozen backlog is what a factory run spends against" | ADR-0020 §9 (:444-447) |
| Spend crb's money: fund a calibration build, queue runs | An approver; an operator | "enterprise-grade autonomy still gates spend". Queueing re-measurement is one of three steps of which crb says "None of these is a gap the product will later close" | `docs/LEARNING-LOOP.md:214-217`; `src/crb/factory/standard.py:509-518` |
| Remove a check or lower a floor | A named person | The loop never changes how work is judged | `docs/LEARNING-LOOP.md:354` |
| Stop the loop; revert a change | Any named person | The loop never re-applies a change a person reverted | ADR-0020 Consequences (:491-492) |

Everything else is exmap's own work, as the operator said: "All of course can be done autonomously".

---

## 6. Requirements

Each requirement has a source tag and an acceptance criterion a tester can check. A "named person" is an authenticated, stable account id (R41).

### 6.1 Product and repositories

**R1.** Work is attached to a product. Stage 2 cannot start on work with no product, because the product is where its repositories come from. **[operator]** Msg 2.
*Accept:* starting stage 2 on a session with no product is refused, and the refusal names the missing product. Every handed-over item names its product.

**R2.** A product lists one or more repositories by name, each with the place exmap reads it from (a local clone or a remote address). **[operator]** the list (Msg 2). **[crb]** a repository is keyed by its name (`src/crb/store/models.py:117`). **[inferred, A3]** the read location.
*Accept:* a product with two repositories can be saved and read back. With a deployment connected, a repository that `GET /repos` does not list is saved and labelled "not known to crb". With none connected, each is labelled "unverified against crb". Stage 2 runs in both cases.

**R3.** exmap holds the product record as versioned config. Each version names its proposer, and earlier versions stay readable. **[inferred, A4]**
*Accept:* each change to the product record creates a new version with a proposer. Each item names the product version it was decomposed under.

**R4.** For each item, exmap proposes the repository from the work, the product's repositories and their profiles. It asks a person only when the evidence does not settle it, and never guesses. **[operator]** Msg 2, "Id expect to know from the work which repo"; v1 brief §0, it "must ask rather than guess".
*Accept:* every item's repository has a proposal record citing its evidence. A scripted ask that fits one repository creates the item with no person's act. A scripted ask that fits two repositories equally yields a clarification listing both, and no item is created until it is answered.

**R5.** exmap reads product knowledge from the repositories themselves, at a pinned commit, and from a connected crb deployment where one exists. Every fact names its source: a file at a commit, or a crb read with its endpoint and time. Stage 2 works on repository contents when no deployment is connected. **[operator]** Msg 2, "from the repo which technical information matters for the ask". **[crb]** a miner reads "one kind of source at one pinned commit" and proposes from it, because "A person should not have to type what a repository already says" (`src/crb/core/miners.py:1-8`). **[inferred, A3, A9]** using both sources, and the network calls they need.
*Accept:* with no deployment connected, stage 2 produces items from a repository's files at a named commit. Each fact in the decomposition evidence cites a file and commit, or a crb endpoint and time, and is marked as from the repository or from crb.

**R6.** Each repository has a versioned technical-information profile: which technical information matters for each kind of ask, and what exmap asks beyond crb's slots to decompose it. It is exmap config. exmap proposes it from the repository, and it is used for a second task only once verified (R31). It drives the questions exmap asks and the facts it selects. It holds questions and selection rules, not facts. **[operator]** Msg 2, "from the repo which technical information matters for the ask" and "Elements like this are essentially config". **[crb]** facts about a repository belong in crb's library (ADR-0026 item 10), so exmap keeps no signed store of them.
*Accept:* for a scripted ask, the questions exmap asks and the facts it selects are exactly those the profile version names. Each profile entry is a question or a selection rule that names a source; an entry that states a fact is refused. Each item cites its profile version.

### 6.2 What each ticket asks and carries

**R7.** For each item, exmap asks at least what crb asks the ticket for: the structural slots of the item's class, and, where the cell's standard is `S2`, a failing test written by a named person. crb's catalogue is the floor, and the profile adds what exmap needs to decompose. The catalogue is read from the connected deployment, and from the vendored copy only when none is connected. **[crb]** ADR-0026 item 8 (:302-310); `src/crb/factory/standard.py:128-132`; `docs/API.md:322`.
*Accept:* with a deployment connected, the slot questions for a class equal that class's slots in `GET /factory/catalogue`, and the profile's questions are marked as exmap's. Each item names its catalogue source. Items made from the vendored copy are labelled with its source commit.

**R8.** Every structural fact records its origin: typed by a named person, drafted by exmap's model (with its provider and prompt version), or derived from a source (a file at a commit, or a crb read). A fact a person did not write is handed over with its origin label, never as a plain person's fact. While crb neither builds nor measures an arm for such facts, an item that carries any is shown "carries drafted facts: fit only for a calibration build". **[crb]** facts a pinned model drafted are their own arm, `+facts@<drafter>` (ADR-0026 :106), and crb must never "Give a builder context its standard was not measured with" (ADR-0026 :548). crb's factory stamps a build `S1` or `S2` only (`src/crb/factory/loop.py:931-937`), so it does not yet record this arm (§9.3).
*Accept:* each fact in a handover has an origin. An item with a model-drafted or derived fact shows the calibration-only line in the fitness report. Changing a fact's origin changes the stage 2 revision.

**R9.** Repository knowledge beyond the class's slots stays in the decomposition evidence. It is not put on the ticket as context for the builder. **[crb]** the builder "gets that arm's context and nothing it was not measured with" (ADR-0026 :308); library entries never reach a brief (`docs/API.md:227-230`). **[inferred, A8]** that this keeps off the ticket repository facts the operator may consider relevant.
*Accept:* an exported ticket's acceptance criteria hold only the agreed examples' criteria and slot lines of the item's class. No library statement, repository config or file content appears. The decomposition evidence lists every source used.

**R10.** Each item has one repository, one class from crb's catalogue, one kind and one size. Its structural facts are `slot: text` lines that name slots of its own class only. **[crb]** the `BacklogItem` shape (v1 brief §3); a line naming another class's slot fills nothing (`src/crb/factory/readiness.py:449`; `src/crb/intake/draft.py:13-17`).
*Accept:* each exported item validates against crb's `BacklogItem` rules. Entering a fact that names another class's slot is refused, and the refusal names the class the slot belongs to.

**R11.** A test handed over as an item's `S2` test was written by a named person. exmap records its author and never hands over a test its model drafted. **[crb]** both backlog routes stamp an attached test `operator:<id>`, which makes the build `S2` (`src/crb/server/routes/factory.py:1003-1006, 1042-1048`; `src/crb/factory/testfirst.py:232-235`; `src/crb/factory/loop.py:931-937`).
*Accept:* adding a test to a handover with no named author, or with exmap's model as its author, is refused.

### 6.3 Decomposition

**R12.** exmap derives the decomposition from the signed business map, the product's repositories and each repository's profile. It asks a person only where it cannot tell. **[operator]** Msg 2, the answer to decision 1 and "We can attempt to produce the context we need for our task autonomously"; v1 brief §0, "the AI handles the mechanics of structuring it". **[inferred, A2]** reading the answer to decision 1 this way.
*Accept:* a scripted signed map and a product with verified profiles yield items with no person's act. A scripted ambiguity yields one clarification and no item until it is answered.

**R13.** An ask whose rules need work of several capability classes becomes several items, one class each. **[operator]** Msg 1, "which may require multiple factory components". **[crb]** a `BacklogItem` has one class. **[inferred, A6]** that "multiple factory components" means several items.
*Accept:* a scripted ask that needs a new backend route and a new frontend component yields an item of class `backend.route.add` and one of class `frontend.component.add`. In one repository, the component item's `depends_on` names the route item. In two, the link is recorded as in R14.

**R14.** `depends_on` names only items in the same repository's backlog. exmap records any other order itself, labelled "not enforced by crb". On the ticket path, exmap records every order this way. **[crb]** `src/crb/factory/backlog.py:205-218`; crb's intake never sets `depends_on` (`src/crb/intake/draft.py:582-623`).
*Accept:* an item in repository A that must follow one in repository B has no `depends_on` entry for it, and the handover lists the link under "order across repositories, not enforced by crb". A ticket-path handover lists every order there.

### 6.4 Coverage, traceability and the stamp

**R15.** Every item cites the rules and examples it carries. Every rule and example in the signed map is carried by at least one item. **[operator]** the citing, v1 brief §0, "traceable provenance". **[inferred, A7]** full coverage.
*Accept:* the coverage report lists each rule and example with the items that carry it. An item that cites no rule, or a rule or example that no item carries, blocks handover and is named.

**R16.** An open question accepted at stage 1 is carried, still marked open, to every item it concerns. **[operator]** v1 brief §0: "the system must not pretend the question has been answered".
*Accept:* an accepted question about a rule appears, marked open, in the body of each item that cites that rule. No exported field shows it as answered.

**R17.** Every item carries a stamp: the stage 1 and stage 2 revisions; the product and profile versions; the id and version of each standard used, or of its per-task standard; the account ids of the people who signed stage 1 and verified each standard; and, for each crb answer it relied on, the apparatus version, policy version, posture class, checks arm, taxonomy, context arm and reading id. On the ticket path the stamp travels as tracker tags. **[operator]** Msg 2, "the standard and a history of ways it was used". **[crb]** a sign-off is keyed on arm, class-set version and reading (ADR-0026 :322-324); "A result quoted without its stamp is an anecdote" (`docs/EVIDENCE-AND-CLAIMS.md:144-151`); crb serves these values (`docs/API.md:53, 94, 156`) and keeps a ticket's tags in `labels.tags` (`src/crb/intake/draft.py:582-623`).
*Accept:* each exported item carries these values, and each value resolves to a record in exmap's ledger. A ticket-path export carries them as tags.

### 6.5 What makes stage 2 stale

**R18.** A substantive change to the signed business map makes stage 2's output stale. A stale output cannot be handed over. Stale is a state, not a deletion. **[operator]** v1 brief §0: "Any subsequent substantive change invalidates that sign-off". **[crb]** "Stale is a state, not a deletion" (ADR-0015 §2).
*Accept:* after stage 2 passes its checks, amending a rule in stage 1 marks stage 2 stale with the reason "business revision moved". Handover is refused until stage 2 is derived again from the new revision. The stale output stays readable and the chain still verifies.

**R19.** Technical facts are inside the stage 2 revision. Any change to an item or a fact makes a new stage 2 revision, which must pass the checks again before handover. **[operator]** v1 brief §0, the same rule. This closes v1's gap, where export facts sit outside the revision and the signing reviewer may change them after signing (`exmap/src/core/apply.ts:721-738`; `exmap/docs/INTEGRATION-NOTES.md:575-584`).
*Accept:* changing a slot fact after the checks pass creates a new revision. Handing over the earlier revision is refused, and the new one is handed over only after its checks pass.

**R20.** When a source stage 2 used moves, exmap flags the affected items for re-check. The sources are: a repository file a fact cites, at a newer commit; a class's slots in crb's catalogue; the class set covering a repository; a cited library entry going stale; any crb value in R17's stamp; and a cell sign-off going stale or being revoked. **[crb]** library freshness (ADR-0026 :419-420); a new class-set version is a new cell (ADR-0026 :246-248); sign-offs go stale when the apparatus, arm, posture class or checks arm moves (ADR-0015 §1-2; `docs/API.md:164`).
*Accept:* after stage 2 passes, a change to a class's slots in the deployment's catalogue, or a new apparatus version at `GET /version`, flags every affected item "source changed" at the next read.

**R21.** An item handed over and then changed is issued again as an evolution of the earlier item. On the backlog path, exmap gives it a new id with `supersedes` set. On the ticket path, the same ticket is exported with the changed content, and crb makes the evolution. **[crb]** "An edit is an evolution" (ADR-0017 :53-63); `docs/API.md:325`.
*Accept:* re-exporting after a change gives each earlier backlog-path item a new id with `supersedes` set to the earlier id. A ticket-path re-export keeps the ticket key, and exmap records crb's `<id>.r<revision>` when it reads the outcome back.

### 6.6 Fitness, before handover

**R22.** Before handover, exmap checks each item on what needs no crb rule: a size is set, the class is in the served catalogue, and each structural slot of the class has a line. A missing one blocks handover and names the crb stop the item would meet. An item of kind `operator` is shown "routes to a person". An open value slot does not block, and is shown "routes to test-first authoring". **[crb]** `src/crb/factory/standard.py:425-432`; `src/crb/factory/readiness.py:11-19, 455-461, 472-477`.
*Accept:* each of the three blocking cases, set up alone, blocks handover and names its stop. An item whose only gap is a value slot can be handed over and shows its route.

**R23.** Every other verdict comes from crb: the size rule and `granularize`, the cell's standard, whether it is signed, the route, weak-oracle classes, the organisation class rule and the entry stop. exmap shows crb's answer where one is served: before registration on the ticket path (the intake row's `entry_*`), and after registration on either path (`GET /factory/{repo}/tasks`). Where none is served yet, it shows "not yet checked by crb". It never computes these itself, and never shows an item as able to enter manufacturing unless crb says so. **[crb]** `gate_for` is "the ONE call the loop's pre-build check and the intake's ticket feedback both make" (`src/crb/factory/standard.py:670-674`); `src/crb/server/intake.py:344-349, 1352-1361`; `docs/API.md:326, 333`; weak-oracle classes are a code constant crb does not serve (`src/crb/factory/readiness.py:96-100`; `docs/API.md:322`).
*Accept:* a review of exmap's source finds no implementation of crb's size rule, entry gate or class rule. On a deployment with no proven standard, an item previewed through crb shows `no_proven_standard` with crb's reason text. When crb refuses a read, for example with `409 false_q1_refused`, exmap shows the refusal, not a guess.

**R24.** exmap reads which class-set version covers each repository (`GET /classes`, `repos`). For a repository that a routing version covers, the item goes on the ticket path with no `crb:class=` tag, unless a named person chose to override. On the backlog path it is labelled "read in the global cell". exmap never writes the labels crb reserves for its intake: `labels.taxonomy`, `org_class` and `class_by`. **[crb]** the gate reads an organisation's cells only through those labels (`src/crb/factory/standard.py:444-449, 686-687`), which only intake may write (`docs/API.md:279-284`); intake reclassifies by the set's rule (`src/crb/server/class_set_state.py:221-251`); "a high override rate fails the rule" (ADR-0026 :388-389).
*Accept:* for a repository covered by a routing version, a ticket-path export carries no `crb:class=` tag, and a backlog-path export of the same item is labelled "read in the global cell". No export carries the reserved labels.

**R25.** The fitness report holds one line per check per item. Each line says whether exmap checked it or crb answered it, and each crb answer carries its stamp and time. A stop that comes from the cell is shown, never hidden, and does not block handover. **[crb]** the per-item evidence chain (ADR-0018 :53-56). **[operator]** v1 brief §0: a person may knowingly accept an open issue, but the system "must not pretend".
*Accept:* the evidence of a handover holds one line per check per item, each marked as exmap's or crb's. An item with a cell-state stop is handed over with the stop shown.

### 6.7 Handover and the crb boundary

**R26.** Handover is the exported files. exmap never registers an item or writes anything to crb, and its crb account, if it has one, holds `viewer` only. **[crb]** crb's own loop never will "register an item on a backlog, or write on a board, without a named person" (`docs/LEARNING-LOOP.md:495`); ADR-0020 §9 (:444-447); a decision "cannot be filed under somebody else's name" (`docs/LEARNING-LOOP.md:204-205`). **[operator]** v1 brief §2 left pushing into crb's API as a later step, and neither message reopened it.
*Accept:* no exmap code path calls a crb route other than `GET`. exmap reads its account's role from `GET /health` and refuses to use an account above `viewer`.

**R27.** A repository's handover says how to register it without displacing what is already there. When the repository has no active backlog (`GET /factory/{repo}/backlog` returns 404), the handover is one backlog file. Otherwise it is one evolution body per item, in dependency order. With no deployment connected, both forms are exported with this rule stated. **[crb]** registering a backlog freezes the items "as the repo's ACTIVE backlog" and moves the previous one to history (`src/crb/server/factory_state.py:535-555`); an evolution is "The only way a frozen backlog changes" (`docs/API.md:325`); "the first item freezes a backlog, and later ones evolve it" (ADR-0020 :450).
*Accept:* for a repository with an active backlog, the handover holds evolution bodies only, in dependency order, with a note that registering a backlog file would replace the active backlog. Registering them leaves every item that was already active still active, and `evolutions_hash` extends.

**R28.** Each repository's handover names its path, backlog or ticket, and carries the stamp, order and links as §3's table says. For the ticket path, the product record maps each repository to the column its listener watches. **[crb]** ADR-0017 :38-43, :53-57; `src/crb/intake/draft.py:582-623`.
*Accept:* a ticket-path export carries the stamp as tags and names the repository's watched column. Outcomes read back for it are joined on `labels.ticket`.

**R29.** What crb lacks is prepared as a proposal for crb, never made locally. A fact or slot for crb's library is prepared for a named person to submit from their own crb session, and that person becomes its sponsor. A slot missing from a global class goes to crb's maintainers as an item for crb's own code: a change to `CATALOGUE`. A work-type entry is proposed only for an organisation's own class. exmap never edits its catalogue copy. **[crb]** the caller of `POST /library/{repo}/entries` "is the proposer and so the sponsor", and a mined or drafted proposal needs a person to adopt it (`docs/API.md:237-238`); a work type's slug is "never a global class's" (`docs/API.md:237`); a new slot extends `CATALOGUE` in code (`src/crb/factory/readiness.py:55-59`); "Product items stay off customer backlogs" (ADR-0020 :456-458); "a copy, never an edit" (`exmap/docs/DESIGN.md:1721`). Readiness does not yet read signed work-type slots (`src/crb/factory/readiness.py:425-437`), so a signed one changes nothing at the gate until crb wires it.
*Accept:* the test pinning the copy's hash still passes. A "missing slot" finding produces a proposal record addressed to crb, and exmap makes no crb write.

### 6.8 Standards and their history

**R30.** Every context element exmap uses is versioned, and each version names its proposer: a person, or exmap's model or rule with its version. A model or a rule is never recorded as the verifier. **[operator]** Msg 2, "we propose and have humans verify". **[crb]** "a miner or a model is never a person" (ADR-0026 :414-418).
*Accept:* each version record has a proposer. A version exmap proposed cannot be marked verified without a named person's act.

**R31.** A reusable standard's version is used for a second task only once a person has verified it. Until then it is a per-task standard (R32). Items produced under a verified version need no further person's check on that account. **[operator]** the verification, Msg 2, "where a single standard is used repeatedly we propose and have humans verify". **[crb]** the two people, a sponsor and an approver who is not the sponsor (`docs/API.md:239, 269`), adopted on top (§4.2).
*Accept:* applying an unverified version to a second task is refused. A verify act by the account that sponsored the version is refused. Items under a verified version are handed over with no per-item person's act.

**R32.** A per-task standard is kept as a versioned record. Each use is appended to a hash-chained history: the item, the version, and crb's outcome for that item. **[operator]** Msg 2, "the standard and a history of ways it was used". **[crb]** append-only, hash-chained ledger discipline (v1 brief §3).
*Accept:* the history of a per-task standard lists every item that used it. Verifying the chain detects a removed or edited entry.

**R33.** The loop monitors the per-task standards and their histories. A failure traced to a per-task standard is attributed to the assembly recipe version that put it together. An assembly or a failure that recurs across tasks produces a proposed reusable standard, verified under R31. **[operator]** Msg 2, "the artifact we are monitoring" and "improve based on continuous processing feedback".
*Accept:* a scripted run of tasks whose per-task standards share one assembly yields one proposed reusable standard that cites each task. A failure on a per-task standard is recorded against the assembly recipe version.

### 6.9 The improvement loop and its budget

**R34.** The loop learns from these signals, read back for every handed-over item across sessions: exmap's own checks (R22); replays of exmap's stages against changed config; crb's readiness answers (`dor_gaps`, `value_gaps`, `route_hint`) and entry stop; the build, review and held-out acceptance results of funded calibration builds; and intent found wrong after sign-off. Each is recorded against the standard versions and the stage 2 revision that produced the item. While no cell is proven, crb's gate never reaches `needs_context`, and the loop's report says so. **[operator]** Msg 2, "continuous processing feedback". **[crb]** `docs/API.md:326`; `src/crb/factory/standard.py:456-508`.
*Accept:* after crb reports a handed-over item with stop `no_proven_standard` and a `value_gaps` entry, the history of that item's standard version shows the stop as "cell state" and the gap as "routes to test-first authoring" at exmap's next read.

**R35.** Before any change, each failure is classified to its cause and to the stage or element responsible (§5.1), by a rule that gives the same answer for the same record and makes no model call. A failure is held against a context element only with a witness: crb's answer names a gap that element should have filled, or a replay with only that element changed removes the cause. A cell-state stop, a weak-oracle or operator-kind route, or a build or review failure without a witness is held against no exmap element. **[operator]** Msg 2, "properly understanding the failures". **[crb]** ADR-0020 §2 (:141-178), §6.13 (:372-375), §10 (:477-478); blame needs a witness (`docs/EVIDENCE-AND-CLAIMS.md:112`).
*Accept:* classifying the same outcome twice gives the same cause, with no model configured. A `no_proven_standard` stop is recorded as "cell state" and held against no element. A build failure with no witness is recorded as "capability".

**R36.** The change lands on the element the classification names, at the strongest level that element allows: first a check that refuses the gap before handover, then a better question or profile entry, and written advice last. A change to how crb judges work is filed to crb (R29), never made by exmap. **[operator]** the element, Msg 2, "make the changes in the right place". **[crb]** the levels and the filing (`docs/PREVENTION.md:42-45`; ADR-0020 §1, §5).
*Accept:* each change record names the failure class, the element changed and the level. exmap has no write path to crb.

**R37.** The judging elements are the fitness checks, the failure-classification rule and the classifier's confidence floor. The loop may add a check or raise the floor, and puts that version forward like any other. It never removes a check or lowers the floor: only a named person does. A change to the classification rule bumps its version. **[crb]** "The loop changes how a change is made, never how it is judged" (`docs/LEARNING-LOOP.md:354`; ADR-0020 §1, :125-139); `check_writable` "refuses every key outside the table, by name" (`src/crb/core/prevention.py:1043-1058`); a rule change without a bump fails a golden fixture (ADR-0020 §2, :176-178).
*Accept:* a loop-proposed version that removes a check or lowers the floor is refused by name. A classification-rule change without a version bump fails a golden fixture.

**R38.** A change is kept on its replay re-test: the failing case fails under the old version and passes under the new one, and the replay corpus shows no new failure. Its effect on later items is then observed against a before window frozen when it was kept. The rule for retiring it on harm, and the minimum counts that rule needs, are fixed when it is kept. crb's bar is the default: a class is actionable at 2 or more occurrences on 2 or more tasks in a stratum of at least 10 (ADR-0020 §6.3), and a change is retired at once on harm (ADR-0020 §6.8). Below the counts, the reading is labelled descriptive. Nothing earlier is credited to the change. **[operator]** Msg 2, "retesting to verify". **[crb]** `docs/dod/STANDARD.md:266-267`; ADR-0020 §6.5, §6.14; a descriptive reading "changes no default" (ADR-0026 :489-493).
*Accept:* each kept change has a replay case that fails when the change is removed. Each change record holds its frozen window and its retire rule. A window with fewer rows than its minimum reads "descriptive".

**R39.** The loop runs at pace. A failure becomes a re-tested version in one replay run, without waiting for new items. The loop runs by default inside the budget. A named person can stop it at any time, with a reason, and can revert any change by name. The loop never puts forward again a change a person reverted for the same failure class. Every act records its actor and, for a person, their account id. **[operator]** Msg 2, "autonomously and at pace". **[crb]** every act is a hash-chained record with its actor (ADR-0020 §3, :197-209); the loop never re-applies a lever a person reverted (ADR-0020 :491-492; `docs/LEARNING-LOOP.md:496`).
*Accept:* a scripted failure yields a re-tested version in one replay run with no new item. On a fresh install the loop is running. After a stop it does nothing until a named person restarts it. After a revert, the same change for the same failure class is not put forward again.

**R40.** All improvement spend comes from a declared continuous-improvement budget. Before each paid call, the loop checks what it has spent, plus a reserve for that call, against the budget. It refuses a call whose price it cannot know. When the budget is spent, the loop makes no paid call, and its unpaid work goes on. It never spends crb's budgets: funding a calibration build and queueing runs stay crb's approver and operator acts. **[operator]** Msg 2, "within a [continuous] improvement budget". **[crb]** the reserve and the refusal (ADR-0030 §3, §6, "A cap that cannot see a cost cannot be kept"); crb's spend (`docs/LEARNING-LOOP.md:214`; `src/crb/factory/standard.py:509-518`). **[inferred, A10]** what happens when the budget is spent.
*Accept:* with the budget at zero, the loop makes no paid call and still classifies failures. A paid call with no known price is refused. No exmap call funds a calibration build or queues a crb run.

**R41.** A named person is an authenticated, stable account id. A typed name does not count. R11, R24, R30, R31, R37 and R39 are blocked until Q6 is answered. **[crb]** crb records a decider as "the stable, unique account id, never the display name an account can change or share" (ADR-0022 :55-58), and the decider is the signed-in session (`docs/LEARNING-LOOP.md:204-205`). v1's reviewer name is self-asserted and labelled so (`exmap/docs/DESIGN.md` §1.3).
*Accept:* an act that needs a named person is refused when no authenticated account is signed in. Two acts that must be by different people are refused when they carry the same account id.

---

## 7. What v1 provides and keeps

**v1 built and gated the business half. Its mechanisms carry into stage 2. The export, the place of the facts and the network calls change.**

| Mechanism | What v1 does | In v2 |
|---|---|---|
| Live capture, one command, local-first | Two browser capture lanes, local speech-to-text, one launch command, loopback only (v1 brief §1 items 3-6) | Kept, except that stage 2 may read remote repositories and a crb deployment over the network, which v1's list of network calls does not allow (v1 brief §1 item 4; A9) |
| Proposals, never state changes | The classifier proposes, and asks when the target is ambiguous, "never a guess" (`exmap/docs/DESIGN.md:60, 778`) | Kept. Stage 2 asks with candidates that are not cards, such as repositories and classes. Today a candidate must be a live card (`exmap/docs/DESIGN.md:778`) |
| Hash-chained ledger | Canonical JSON, `prev_hash` and `hash`; verification never repairs (`exmap/src/core/chain.ts:1-57`) | Kept. Stage 2 events extend the closed event union (`exmap/src/core/types.ts:218-235`). Hashes are not guaranteed byte-compatible with crb's (`exmap/docs/DESIGN.md:726`) |
| Definition of Done gate | Five fixed checks over the card kinds (`exmap/src/core/dod.ts:232-249`) | Kept for stage 1. Stage 2 has its own checks (R15, R16, R22) |
| Sign-off made stale by change | Keyed to the revision hash (`exmap/src/core/apply.ts:46-66`) | Kept. The stage 2 revision also hashes items and facts (R19) |
| Provenance stamp | Provider, prompt version, fallback, error, actor (`exmap/src/core/types.ts:100-110`) | Kept. It gives the attribution the loop needs (R30, R35) |
| Export gate and pure mappers | Refused unless verified; drafts watermarked; same input, same bytes (`exmap/src/export/index.ts:85-94`; `exmap/docs/DESIGN.md:1615`) | Kept. The mappers emit several items for each path (R13, R27, R28) |

| v1 behaviour | v2 | Requirements |
|---|---|---|
| One story, one item, one class | Several items across repositories and classes | R13, R14 |
| Slot facts typed at export, outside the revision | Facts sit inside the stage 2 revision, each with its origin | R8, R19 |
| Class defaults to `unclassified`, size to `unsized` | Either one blocks handover | R22 |
| A static, vendored catalogue | Read from the deployment; the copy is a labelled fallback | R7 |
| `depends_on: []`, `supersedes: ""` | Set when they apply | R14, R21 |
| Reads nothing from crb or the repositories | Reads both, and reads each handed-over item's outcome | R5, R34 |
| No product or repository | A product with repositories and their profiles | R1-R6 |

---

## 8. Non-goals

- Deciding anything crb's gate decides: the size rule, standards, sign-offs, licences, routes or the class rule (R23).
- Registering items, writing anything to crb, funding calibration builds or queueing runs (R26, R40).
- Pushing into a crb deployment's API. It stays v1's documented next step.
- Editing crb's catalogue, class vocabulary, grader keys, routing thresholds or class sets (R29, R36).
- Adding a product entity to crb (Q3).
- Choosing a tracker column or switching a crb listener. The product record only names the column a listener already watches.
- Running or relying on crb's prevention loop.
- The v1 non-goals that still stand: speaker diarisation, a Teams bot or Graph integration, multi-user collaboration over the network, a database, cloud sync and server-side speech-to-text. The histories in R32 and R34 are append-only files, as in v1.

**Later, not asked.** Turning agreed examples into crb tests. If it is ever wanted, an agreed example can become only the `S2` failing test a named person writes (R11), never a held-out acceptance test. The people who agreed it are the ticket's authors, and crb cannot see them as such: it counts as authors only the test author and whoever registered the item (`src/crb/factory/evidence.py:412-424`; `src/crb/core/acceptance.py:4-9`). R17's stamp names them for crb's people.

---

## 9. Assumptions to confirm, open questions, and what only crb can change

### 9.1 Assumptions to confirm

| Id | Assumption | Rests on | Requirements |
|---|---|---|---|
| A1 | **[inferred]** "Our standard" is the standard the operator described in Msg 2: produce context autonomously; people verify a reusable standard, which improves from feedback; a per-task standard is monitored through its history. crb's mechanisms in §4.2 are adopted on top of it as design choices, each open to veto | "I think for 2 we must follow our standard" and the sentences after it | Every [crb] requirement |
| A2 | **[inferred]** "I guess that depends on the product", read with the rest of that answer, means the decomposition is derived from each product's knowledge, so it differs by product. It does not mean a per-product choice between a live call and generation | "On 1 I guess that depends on the product ... from the repo which technical information matters for the ask" | R12 |
| A3 | **[inferred]** Product knowledge comes from both sources: the repositories, read at a pinned commit as crb's miners read them, and a connected crb deployment where one exists | "we must follow our standard"; "from the repo which technical information matters" | R2, R5 |
| A4 | **[inferred]** exmap holds the product record as versioned config, because crb has no product entity | "I would expect this work to be attached to a product" | R3 |
| A5 | **[inferred]** "that should be split" means a separate stage in exmap, not a separate document or a separate section of the ticket | Msg 1 | §2 |
| A6 | **[inferred]** "which may require multiple factory components" means an ask may become several items of different classes. The other reading is one ticket carrying the context several factory components read, such as the test author, the builder and the reviewer; R7 covers that reading in any case | Msg 1 | R13 |
| A7 | **[inferred]** Every agreed rule and example must be carried by some item, because a ticket that drops one does not match the ask | Msg 1, "ensuring that ticket matches ... the ask" | R15 |
| A8 | **[inferred]** crb's rule that the builder sees only what its standard was measured with applies to repository facts exmap finds relevant, so they stay off the ticket | ADR-0026 :308, set against Msg 2 | R9 |
| A9 | **[inferred]** Stage 2 may call a crb deployment and read remote repositories over the network. This relaxes v1's rule that the only network calls are the speech model download and the classifier (v1 brief §1 item 4) | A3 | R2, R5, R20, R23, R34 |
| A10 | **[inferred]** When the improvement budget is spent, the loop stops paid calls only, and its unpaid work goes on | "within a [continuous] improvement budget" | R40 |

### 9.2 Open questions for the operator

1. **Should an engineer sign each decomposition?** This document has no such sign-off: the person's check is the verification of each reusable standard version (R31). A per-task sign-off would sit against "All of course can be done autonomously" and v1's "the AI handles the mechanics of structuring it".
2. **Is a live engineers' refinement call ever wanted, and for which products?** This document derives every decomposition (A2).
3. **Where does the product live?** In exmap, as versioned config (A4), or should crb add a product above repositories? crb has none. A review proposed only a `team` attribute on repositories (`docs/reviews/2026-09-17-enterprise-front-end.md:123`).
4. **How does exmap get crb's gate verdict before handover?** (a) crb adds a dry run for an unregistered item; (b) a named operator registers the items and exmap reads `GET /factory/{repo}/tasks`; (c) exmap's own checks only (R22), with crb's verdict after registration; (d) the ticket path: the ticket goes into the watched column and exmap reads the intake row's `entry_*`. With (d), crb comments on the ticket, and registers it at once when approval is off or the author is on the allowlist (`docs/API.md:335`).
5. **What is the continuous-improvement budget?** What it is counted in (model calls, people's verification time, crb runs), how large it is, who sets it, and whether it applies per product or overall. crb has none to reuse.
6. **How are people identified?** v1 runs for one user on loopback, with a self-asserted reviewer name. Named acts and the two-person rule need identities that cannot be borrowed (R41). Should people sign in through the crb deployment's accounts, which is one more network call, or should exmap add its own?
7. **Facts exmap drafts.** crb treats facts a model drafted as their own arm, `+facts@<drafter>`, which it neither builds nor measures today. Do you accept that items carrying them are fit only for a calibration build until crb measures that arm (R8)? The alternative is a person restating each fact in their own words, which is a per-item step.
8. **Relevant repository facts on the ticket.** crb lets the builder see only what its cell standard was measured with, so repository facts you consider relevant cannot ride on the ticket until crb measures an arm that includes them (A8, R9). Accept this, or should exmap propose such an arm to crb?
9. **crb's own acts.** You said "All of course can be done autonomously". This document still leaves to crb's named people the acts crb owns: registering items, funding calibration builds, queueing runs and sponsoring library entries (§5.4). Confirm that these stay with crb.

### 9.3 Changes only crb can make

| Change | Why exmap needs it | Today |
|---|---|---|
| A dry run of the entry gate for an item on neither path | Q4, option (a) | No such route (`src/crb/server/routes/factory.py:1157, 1352`) |
| A route for an outside `drafted:` library proposal with no sponsor | R29 without a person submitting | None; the caller is the sponsor (`docs/API.md:237-238`) |
| Stamping `+facts@<drafter>` on a build whose facts a model drafted | R8, Q7 | The factory stamps `S1` or `S2` only (`src/crb/factory/loop.py:931-937`) |
| Readiness reading signed work-type slots | R29's proposals reaching the gate | Readiness reads only the code catalogue (`src/crb/factory/readiness.py:425-437`) |
