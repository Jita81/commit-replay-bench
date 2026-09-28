---
id: dod.page.factory-acceptance
level: page
name: Held-out acceptance tests
scope: /factory/acceptance
parent: dod.journey.manufacture
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: done                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-28
---

# Held-out acceptance tests

**Purpose.** Let a second person write the held-out acceptance tests a calibration build's
first attempt is graded on, from the ticket alone and before the build, so that a cell whose
standard is only a ceiling can be tested forward — the one way ADR-0026 item 8 allows a
ceiling to become a standard.

**Entry → exit.** Arrives from a funded calibration build on the Factory screen (the item's
"Held-out acceptance tests" link) or by URL (`/factory/acceptance?repo=`); with no `?repo=`
the most recently updated repository is chosen. A person who may write the tests leaves with
them stored under their name, with the time and the digest; anyone else leaves knowing why they
may not. After the build, the ticket's row says whether its first attempt passed them.

**Non-goals.** It never shows the ticket's own failing test, a build, or the held-out tests
once they are saved. It does not fund a calibration build (an approver does that on the
Factory screen), run the factory, register a forward reading (`POST /readings/forward`, an
operator's act) or open a pull request: a calibration build never delivers.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| factory-acceptance.purpose.1 | PURPOSE | The About block and the page purpose say that a second person writes the tests a calibration build's first attempt is graded on, from the ticket alone, and that only a registered forward reading counting those results can turn a ceiling into a standard; the eyebrow reads "Journey · 4 of 4 · Factory · held-out tests" | `hint:about:/factory/acceptance` · `code:ui/src/screens/Factory/AcceptancePage.tsx::AcceptancePage` · `code:ui/src/components/Layout.tsx::"'/factory/acceptance', step: 3"` | met | |
| factory-acceptance.entry-exit.2 | ENTRY-EXIT | The page is reached by clicking the "Held-out acceptance tests" link on a funded calibration build on the Factory screen, not only by typing its path; it links back to the Factory screen; with nothing to write it says what makes a ticket appear | `vitest:ui/src/screens/Factory/FactoryPage.test.tsx::"a funded calibration build links to where a second person writes its held-out tests (ADR-0026 item 8)"` · `vitest:ui/src/App.reachability.test.ts::"is linked to from the app"` · `code:ui/src/screens/Factory/AcceptancePage.tsx::"No calibration build needs held-out tests"` · `hint:id:link.factory.acceptance` | met | |
| factory-acceptance.truth.3 | TRUTH | Each ticket is shown as it was written — description, acceptance criteria, kind and size — with who funded its calibration build and when, and never its own failing test; the API serves neither that test nor a build | `vitest:ui/src/screens/Factory/AcceptancePage.test.tsx::"shows the ticket as written and who funded its build, never its own failing test"` · `test:tests/test_server_acceptance.py::test_a_second_person_writes_held_out_tests_from_the_ticket_alone` · `route:GET /factory/{repo}/acceptance` | met | |
| factory-acceptance.actions.4 | ACTIONS | Saving sends exactly the file path and the tests typed and says the builder never sees them; a refusal is shown in the API's words beside the form; an empty press asks at the fields and sends nothing; a second save for the same build is refused | `vitest:ui/src/screens/Factory/AcceptancePage.test.tsx::"sends exactly the path and the tests typed, and says the builder never sees them"` · `vitest:ui/src/screens/Factory/AcceptancePage.test.tsx::"shows a refusal in the API’s words beside the form"` · `vitest:ui/src/screens/Factory/AcceptancePage.test.tsx::"an empty press asks at the fields and sends nothing"` · `route:POST /factory/{repo}/items/{item_id}/acceptance` | met | |
| factory-acceptance.roles.5 | ROLES | Only a person with the operator role or above who is not the ticket's author and not the approver who funded the build may write the tests (403 `acceptance_same_person` otherwise); anyone else is told why and shown no form; the factory does not use tests written by the person whose run builds the ticket | `test:tests/test_server_acceptance.py::test_the_tickets_author_and_the_funding_approver_may_not_write_them` · `vitest:ui/src/screens/Factory/AcceptancePage.test.tsx::"tells a person who may not write them why, and offers no form"` · `test:tests/test_factory_held_out.py::test_the_tests_are_not_used_when_written_by_the_author_the_sponsor_or_the_submitter` | met | |
| factory-acceptance.truth.6 | TRUTH | Tests can be written only while the build has not started and for a ticket never built before; a written or graded ticket shows who wrote its tests, when, their digest and paths, and the first attempt's result — never the tests themselves | `test:tests/test_server_acceptance.py::test_tests_are_refused_once_the_build_has_started_or_the_ticket_was_built` · `vitest:ui/src/screens/Factory/AcceptancePage.test.tsx::"a graded ticket shows who wrote its tests, their digest and the result — never the tests"` · `test:tests/test_server_acceptance.py::test_a_file_that_cannot_hold_a_held_out_test_is_refused` | met | |
| factory-acceptance.explanation.7 | EXPLANATION | Every element on the screen carries a hint from the registry and the ratchet enforces the route for a viewer and an operator with at least 12 hinted elements; hovering its status tag opens the registry's text | `hint:ratchet:/factory/acceptance` · `hint:about:/factory/acceptance` · `vitest:ui/src/help/hints-ratchet.test.tsx::"${pattern} as ${role}: every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"${route}: mouse-over on ${id} opens its bubble with the registry text; Escape closes it"` | met | |
| factory-acceptance.evidence.8 | EVIDENCE | A tier-1 spec walks it in the browser: a second person who neither wrote the ticket nor funded its build writes the tests, the run grades the first attempt on them and stamps it `S2` with `acceptance: held_out` inside its row, no pull request opens, and the page reads the ticket as graded; an end-to-end test walks the same path from a ceiling to the forward reading's state with its n, and to the promotion | `spec:ui/e2e/walkthrough/10-factory.spec.ts::"a second person writes I-1’s held-out acceptance tests from the ticket alone"` · `spec:ui/e2e/walkthrough/10-factory.spec.ts::"the item chain: one calibration build (not clean, with its evidence), one not built — no proven standard — with its gap and the way forward"` · `test:tests/test_forward_reading_e2e.py::test_a_calibration_build_on_a_ceiling_is_graded_on_held_out_tests_and_read_forward` | met | |
| factory-acceptance.accessibility.9 | ACCESSIBILITY | The route renders for every persona at 375 and 1280 with a hint bubble open and axe (WCAG 2.1 AA) clean, and does not scroll sideways at 375 | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| factory-acceptance.non-goals.10 | NON-GOALS | The page says nothing on it opens a pull request and who may not write the tests; the saved state says the builder never sees them | `code:ui/src/screens/Factory/AcceptancePage.tsx::"Nothing here opens a pull request."` · `hint:id:banner.acceptance.second_person` | met | |
| factory-acceptance.operations.11 | OPERATIONS | The held-out tests are stored as one event per calibration build on the hash-chained events table, written under its write lock and read back only when their digest and id re-hash; the routes and the actions the factory emits for them are rows of the API guide | `code:src/crb/server/acceptance.py::write_held_out` · `code:src/crb/server/acceptance.py::load_held_out` · `route:GET /factory/{repo}/acceptance` · `doc:docs/API.md#event-vocabulary` | met | |
