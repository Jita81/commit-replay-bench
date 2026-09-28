---
id: dod.journey.curate-the-library
level: journey
name: Curate the context library
scope: curate-the-library
parent: dod.stream.decide-and-license
children: [dod.page.library-repo]
persons: [operator, approver, viewer, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-27
---

# Curate the context library

**Purpose.** Two people put what they know about a repository into one vocabulary: a sponsor
proposes an entry — a component, a work type, a decision, a convention, a pattern or a
standard — and a different approver signs it, so the work type's page can show it as signed
context (ADR-0026 item 10; `help.ts` About copy for `/library/:repo`: "Each entry needs a
sponsor and a different approver, and nothing here reaches a builder until an arm has measured
it").

**Entry → exit.** Starts on the repository's page (*Context library*) for the sponsor, and on
Decisions for the approver, where an entry waiting for its second person reads "waits for a
second person to sign it" with a *Sign* link. Ends with an entry that reads *signed*, names
both people and the version they read, and is listed on its work type's page as signed context
with its effect `unmeasured`. A stale entry returns to Decisions as "went stale" until it is
signed again or retired.

**Non-goals.** The journey does not let one person both sponsor and sign (`same_person`, never
relaxed), treat a miner or a model as a person, edit an entry in place (a change is a new
version and needs a new signature), or put an entry into a builder's brief (only a measured
arm does, off by default — `product.truth.212`). It does not measure an entry's effect.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| curate-the-library.purpose.1 | PURPOSE | The library's About block and the operator guide say what an entry is, that two different people sign it, and that no entry reaches a builder until an arm has measured it | `hint:about:/library/:repo` · `doc:docs/OPERATOR.md#14-the-context-library` | met | |
| curate-the-library.entry-exit.2 | ENTRY-EXIT | The sponsor reaches the library from the repository's page; the approver reaches the entry from its Decisions row, whose Sign link opens the library's index; after signing, the entry is on its work type's page | `code:ui/src/screens/Repos/RepoDetail.tsx::"Context library"` · `code:ui/src/screens/Decisions/decisions.ts::libraryDecisions` · `spec:ui/e2e/walkthrough/14-library.spec.ts::"a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context"` | met | |
| curate-the-library.truth.3 | TRUTH | An entry is signed only by a person other than its sponsor, on the version that person read; a mined or model-drafted proposal is never signed until a person sponsors it; the record is append-only and hash-chained, and a tampered act is found | `test:tests/test_library.py::test_the_sponsor_can_never_sign_their_own_entry` · `test:tests/test_library.py::test_a_mined_proposal_needs_a_person_to_sponsor_it_before_another_signs` · `test:tests/test_library.py::test_a_signature_names_the_version_it_read_and_a_new_version_needs_a_new_one` · `test:tests/test_library.py::test_the_acts_are_hash_chained_and_a_tampered_act_is_found` · `test:tests/test_store_library.py::test_library_acts_are_append_only` | met | |
| curate-the-library.actions.4 | ACTIONS | Each act says what it did: a proposal names its sponsor and the second signature it waits for; a signature turns the entry *signed*; a revocation and a retirement are appended with their reason; a refusal names its rule in words | `vitest:ui/src/screens/Library/LibraryPage.test.tsx::"an operator proposes an entry and is told a different approver must sign it"` · `vitest:ui/src/screens/Library/LibraryPage.test.tsx::"a second approver signs, and a refusal is shown in the API’s words"` · `test:tests/test_server_routes_library.py::test_revocation_and_retirement_are_appended_with_their_reasons` | met | |
| curate-the-library.explanation.5 | EXPLANATION | Every element on the path — the library page and the Decisions library rows — resolves to the hint registry, and the Decisions kind tag names the three library kinds | `hint:ratchet:/library/:repo` · `hint:ratchet:/decisions` · `hint:id:pill.decisions.kind` | met | |
| curate-the-library.evidence.6 | EVIDENCE | One walkthrough proposes as a sponsor, is refused signing its own entry, signs as a second person from Decisions and reads the entry on the work type's page | `spec:ui/e2e/walkthrough/14-library.spec.ts::"a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context"` | met | |
| curate-the-library.roles.7 | ROLES | An operator proposes and sponsors; an approver signs, revokes and retires; the sponsor is refused signing at the API, in the page and on Decisions; every act is an event with its actor and its entry | `test:tests/test_server_routes_library.py::test_every_act_is_gated_by_role` · `test:tests/test_server_routes_library.py::test_an_operator_proposes_and_sponsors_and_a_second_person_signs` · `test:tests/test_server_routes_library.py::test_every_act_writes_its_event_naming_the_actor_and_the_entry` · `vitest:ui/src/screens/Decisions/decisions.test.ts::"an entry the viewer sponsored waits for another approver: never their Sign, never their re-signature"` · `adr:0026` · `dl:DL-129` | met | |
| curate-the-library.operations.8 | OPERATIONS | An entry read from a file goes stale without a person asking: the repository's head is read after every mine and the entries whose file changed are marked stale | `test:tests/test_worker.py::test_a_mine_reads_the_head_and_an_entry_whose_file_changed_goes_stale` · `test:tests/test_worker.py::test_a_file_gone_at_head_makes_its_entry_stale` · `code:src/crb/server/worker.py::"self._library_freshness(ctx, ref)"` | met | |
| curate-the-library.accessibility.9 | ACCESSIBILITY | Every page on the path renders for every persona at 375 and 1280 with axe clean, and the work type's page does not scroll sideways at 375 px | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/14-library.spec.ts::"a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context"` | met | |
| curate-the-library.non-goals.10 | NON-GOALS | The library page says nothing on it reaches a builder until an arm has measured it, and the guide says an entry is never edited in place | `hint:about:/library/:repo` · `doc:docs/OPERATOR.md#14-the-context-library` | met | |
| curate-the-library.steps.11 | STEPS | (1) The repository's page: *Context library* → the library with the first work type open. (2) Propose, as the sponsor → "You are its sponsor; a different approver must sign it". (3) Decisions, as the approver: "waits for a second person to sign it" → *Sign* opens the index. (4) Sign → the entry reads *signed*. (5) The work type's page → the entry is signed context with both names. Nothing the product knows is retyped | `code:ui/src/screens/Library/LibraryPage.tsx::LibraryPage` · `code:ui/src/screens/Decisions/decisions.ts::libraryDecisions` · `spec:ui/e2e/walkthrough/14-library.spec.ts::"a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context"` | met | |
| curate-the-library.proof.12 | PROOF | One spec walks the journey end to end as the two personas: the admin proposes from the repository's page and is refused signing; `walk-approver` follows Decisions to the entry and signs it; the work type's page shows it | `spec:ui/e2e/walkthrough/14-library.spec.ts::"a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context"` | met | |
| curate-the-library.time-cost.13 | TIME-COST | The guide states how long proposing and signing an entry takes, measured, and that it spends nothing. The nothing spent and a scripted pass are stated and measured; a person's time is not yet | `doc:docs/OPERATOR.md#14-the-context-library` · `spec:ui/e2e/walkthrough/14-library.spec.ts::"a sponsor proposes an entry and cannot sign it; a second person signs it and it is signed context"` · `measured:n = 1 scripted pass of propose, refused signature, second signature and the work type's page (1.4 s), method: 14-library.spec.ts timed by the spec on the tier-1 walkthrough stack on 2026-09-27, apparatus 2.3` | partial | G-737 |
| curate-the-library.recovery.14 | RECOVERY | Every stop names its way forward: the sponsor signing → a second person must sign; a stale version → read the entry again; a mined proposal with no sponsor → a person must sponsor it; a stale entry → sign it again or retire it | `code:src/crb/core/library.py::apply` · `code:ui/src/screens/Decisions/decisions.ts::libraryDecisions` · `test:tests/test_library.py::test_a_mined_proposal_needs_a_person_to_sponsor_it_before_another_signs` | met | |

## Gaps
- **G-737** — narrowed: OPERATOR §14 now states that proposing and signing spends nothing and a measured scripted pass (14-library, 1.4 s), but that pass reads nothing; how long a person takes to write, check and sign an entry has not been timed · time people doing the journey — proposing an entry with its provenance and signing it as a second person — on a fresh deployment, and state the figure with its n, method and apparatus in OPERATOR §14 · docs
