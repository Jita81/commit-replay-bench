---
id: dod.page.classes
level: page
name: Classes of work (an organisation's class sets, a page per class, the labelling screen)
scope: /classes
parent: dod.journey.curate-the-library
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-28
---

# Classes of work

**Purpose.** An organisation's own classes of work, each a child of one global class, with one
rule that reads only what a ticket carries; a version routes nothing until people have labelled
a sample, its validity report passes and an approver other than its sponsor has signed it
(`help.ts` About copy; ADR-0026 item 9, DL-330).

**Entry → exit.** Arrives from a repository's context library (*Your organisation's classes of
work*). The person leaves having read a version — its classes, its validity report with every
measure's result, n and state, and how its commits were held out — and one class's page: what
the work is, the rule in words, example derivation commits, what a ticket in it must carry, the
signed context its builder would get (with a link to each repository's library page for it) and
what is proven per size; or having proposed a version (and so sponsored it), labelled derivation
commits, signed a version someone else proposed, or revoked one with a reason.

**Non-goals.** It does not let one person both propose and sign a version (`same_person`, never
relaxed). It does not show a labeller the rule's class, another person's label or any outcome.
It does not license a class on a commit that derived it, measure a class (only a registered
reading does, Wave 5), or change the global classes.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| classes.purpose.1 | PURPOSE | The About block states the page's job in one sentence and says that a version routes nothing until a sample is labelled, its validity report passes and a second person signs it; the operator guide says how | `hint:about:/classes` · `doc:docs/OPERATOR.md#15-your-organisations-classes` | met | |
| classes.entry-exit.2 | ENTRY-EXIT | A repository's context library links to the page, the page links back to Decisions, and each class's page links to the library page of its work type in each repository | `code:ui/src/screens/Library/LibraryPage.tsx::"Your organisation’s classes of work"` · `vitest:ui/src/screens/Classes/ClassesPage.test.tsx::"a version reads its report and routes nothing unsigned; a class page reads in plain words"` · `spec:ui/e2e/walkthrough/15-classes.spec.ts::"a sponsor proposes a class set, a person labels a sample, a second person signs, and it routes nothing until its report passes"` | met | |
| classes.truth.3 | TRUTH | A version says whether it routes, with the reason in words, wherever it is shown: routes nothing while unsigned, revoked or failing its validity report; the report shows each measure's result, what it was read over, its state and its threshold | `vitest:ui/src/screens/Classes/ClassesPage.test.tsx::"a version reads its report and routes nothing unsigned; a class page reads in plain words"` · `test:tests/test_server_routes_classes.py::test_the_sponsor_cannot_sign_and_a_second_person_can` · `test:tests/test_class_sets.py::test_a_version_routes_only_when_signed_by_a_second_person_and_its_report_passes` | met | |
| classes.truth.4 | TRUTH | A class's page says what the work is in the organisation's words, the rule in words, example commits from the derivation set only (each saying whether its ticket or its message was read), what a ticket must carry, the signed context scoped to it or its parent with sponsor, signer and effect, and per size the proven standard from the entry gate's own reading of the class's cell, or "No proven standard" and the next measurement | `test:tests/test_server_routes_classes.py::test_a_signed_version_whose_report_passes_routes_and_its_class_page_reads_in_plain_words` · `vitest:ui/src/screens/Classes/ClassesPage.test.tsx::"a version reads its report and routes nothing unsigned; a class page reads in plain words"` | met | |
| classes.truth.5 | TRUTH | The labelling screen shows a person only derivation commits — the message, the linked ticket as it stood or a note that the message stands in, and what changed — never the rule's class, another person's label or an outcome; a label of a confirmation commit is refused | `test:tests/test_server_routes_classes.py::test_the_labelling_screen_is_blind_and_takes_derivation_commits_only` · `vitest:ui/src/screens/Classes/ClassesPage.test.tsx::"the labelling screen shows the next commit, never the rule’s answer, and posts a person’s label"` | met | |
| classes.actions.6 | ACTIONS | Proposing tells the person they are the sponsor and that a different approver must sign; Save label records the person's label; Sign posts the digest the approver read; Revoke needs a reason, asked at the field; a refused act is shown in the API's words beside its control and takes focus | `spec:ui/e2e/walkthrough/15-classes.spec.ts::"a sponsor proposes a class set, a person labels a sample, a second person signs, and it routes nothing until its report passes"` · `vitest:ui/src/screens/Classes/ClassesPage.test.tsx::"the sponsor cannot sign; another approver signs the digest they read"` · `test:tests/test_server_routes_classes.py::test_a_rule_names_only_the_organisations_signed_components` | met | |
| classes.explanation.7 | EXPLANATION | Every tile, column, field, tag, row and button carries a registry hint and the ratchet enforces the route for the viewer, the operator and the approver with at least 40 hinted elements; one element answers on mouse-over | `hint:ratchet:/classes` · `hint:about:/classes` · `hint:id:stat.classes.count` | met | |
| classes.evidence.8 | EVIDENCE | The record, the report, the store, the routes and the hooks are unit-tested; the page is screen-tested; a walkthrough proposes as a sponsor, is refused signing, labels a sample as another person, reads the report's numbers, signs as a third and reads the class's page | `test:tests/test_class_sets.py::test_a_report_with_an_agreeing_sample_and_enough_confirmation_commits_passes` · `test:tests/test_store_class_sets.py::test_acts_are_checked_at_write_chained_and_verified` · `spec:ui/e2e/walkthrough/15-classes.spec.ts::"a sponsor proposes a class set, a person labels a sample, a second person signs, and it routes nothing until its report passes"` | met | |
| classes.roles.9 | ROLES | An operator proposes and labels, an approver signs and revokes (403 below the role on every route); the sponsor can never sign their own version — the page disables the button with the reason and the API refuses `same_person`; every act and refusal is an event naming the actor | `test:tests/test_server_routes_classes.py::test_every_route_is_role_gated` · `test:tests/test_server_routes_classes.py::test_the_sponsor_cannot_sign_and_a_second_person_can` · `test:tests/test_class_sets.py::test_a_version_is_signed_only_by_a_second_person_through_the_library_rule` | met | |
| classes.operations.10 | OPERATIONS | Every route behind the page is an API.md row; the class sets' chain can be verified over HTTP; a relabel writes the label table and never a graded row | `route:GET /classes` · `route:GET /classes/verify` · `route:POST /classes/{org}/versions/from-library` · `test:tests/test_server_routes_classes.py::test_a_sponsor_proposes_and_every_commit_is_relabelled_without_touching_a_row` · `test:tests/test_store_class_sets.py::test_a_tampered_act_breaks_the_chain` | met | |
| classes.operations.11 | OPERATIONS | A version waiting for its second person is a row on Decisions, as a library entry is | absent | unmet | G-762 |
| classes.accessibility.12 | ACCESSIBILITY | The route renders for every persona at 375 and 1280 with its About block, and at 375 px a class's page does not scroll sideways | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/15-classes.spec.ts::"a sponsor proposes a class set, a person labels a sample, a second person signs, and it routes nothing until its report passes"` | met | |
| classes.non-goals.13 | NON-GOALS | The page says that the labelling screen shows no rule's answer, no other person's label and no outcome, and that nothing routes until two people and the report agree | `code:ui/src/screens/Classes/ClassesPage.tsx::"never the rule’s answer, another person’s label or whether a build passed"` · `hint:about:/classes` | met | |
| classes.truth.14 | TRUTH | The capability map and the routing screen read an organisation's class cells on their own axis, as the class's page does | absent | unmet | G-763 |

## Gaps
- **G-762** — a class-set version waiting for its second person is not a Decisions row, so an approver learns of it only by opening Classes of work · add a `class_set_unsigned` decision kind that the Decisions inbox reads from `DbClassSets`, with a Sign link to `/classes?org=&v=`, and flip `classes.operations.11` · ui
- **G-763** — the capability map and `/routes` select a class-set version (`?taxonomy=`) but group its rows by the global parent, so two classes of one parent show as one cell there; only the class's page and the entry gate read the organisation class's own cell · project the map by the label table's organisation class when an organisation's version is selected, and flip `classes.truth.14` · server
