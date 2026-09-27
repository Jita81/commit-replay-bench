---
id: dod.page.help
level: page
name: Glossary and guides
scope: /help
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: done                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-26
---

# Glossary and guides

**Purpose.** "Every term the screens use, in plain English, with the number's n, interval and
apparatus where the term is a number." — the lede under the title (`HelpPage.tsx:61`). It is the
one place a person can look up a word they met on a screen without leaving the product.

**Entry → exit.** Arrives from the "?" in the top bar (`nav.help`), the footer's Help and Glossary
links (`nav.footer_help`), every `<Term>` a screen renders, every About block's Read more, and the
guide page's Back link. Leaves by a term's "Read more" (`link.help.read_more`), a guide title
(`link.help.guide`), both to `/help/docs/<name>#<slug>`, landing on the section itself, or a
decision record (`link.help.adr`, to `/help/docs/ADR-nnnn`); the shell
nav stays on screen, so any journey step is one click away.

**Non-goals.** The page reads no API, holds no state and shows no figure of its own: the numbers
with their n and interval live on the screens that measure them. It holds no decision record of
its own — the Decisions section says so on the page: the ADRs live in the repository under
`docs/adr`, and each opens here as a read-only copy built into the deployment (DL-073). It does
not search, filter or accept a correction.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| help.purpose.1 | PURPOSE | The lede under the title states the page's job in one sentence — every term the screens use, in plain English, with the number's n, interval and apparatus where the term is a number | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |
| help.entry-exit.2 | ENTRY-EXIT | Every entry to the page lands on the thing that was asked for — a term link scrolls to its own entry by `location.hash`, a Read more opens the guide at its heading — and every row leads somewhere: every term, every guide and every decision record is a link, so a reviewer following a decision a screen cites (ADR-0015 on the sign-off, ADR-0016 on the two-person rule) can read it from the product | `vitest:ui/src/help/help.test.ts::"every readMore anchor (screens and terms) names a bundled guide and a real heading"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"every decision record is a link that opens it here"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"a decision record renders at /help/docs/ADR-nnnn"` · `spec:ui/e2e/walkthrough/13-orient.spec.ts::"all eight bundled guides and a decision record open on the served bundle"` · `adr:0015` · `adr:0016` · `dl:DL-073` | met | |
| help.truth.3 | TRUTH | The page publishes no number of its own; every term that names a number carries its threshold, n and apparatus in the definition (the four routing rules and the two rates), and the guide list is the eight the build actually bundles, so the index cannot offer a guide the deployment does not hold | `vitest:ui/src/help/glossary.test.ts::"the four routes and the two rates carry their thresholds"` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` · `code:ui/src/help/docs.ts::DOC_NAMES` | met | |
| help.truth.4 | TRUTH | The Decisions list matches the decision records the repository holds: the rows are `ADR_TITLES`, and a test reads every record in `docs/adr` and fails when one is added, renamed, retitled or removed without its row, or a row names no record | `vitest:ui/src/help/adrs.test.ts::"lists exactly the decision records in docs/adr, by number and title"` · `vitest:ui/src/help/adrs.test.ts::"loads every listed record as the file on disk"` · `code:ui/src/help/adrs.ts::ADR_TITLES` · `adr:0016` | met | |
| help.actions.5 | ACTIONS | The page performs no action that writes, spends or changes state: its only controls are links whose visible text names where they go (the term's "Read more", the guide's own title), so nothing can succeed or fail silently | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |
| help.explanation.6 | EXPLANATION | Every element on the page carries a hint that opens on hover, focus and tap, and the ratchet holds the route with a `SCREENS` entry and a `MIN_HINTS` floor, so a new unhinted element fails a test | `hint:id:link.help.read_more` · `hint:id:link.help.guide` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx has an entry of its own"` · `vitest:ui/src/components/Help.test.tsx::"the four shell screens carry an About block of their own"` · `hint:about:/help` · `hint:id:link.help.adr` · `hint:ratchet:/help` | met |  |
| help.evidence.7 | EVIDENCE | The page's render, the guide registry and the glossary's copy rules are unit-tested, a CI job runs that suite, and the route is visited on the live stack for four personas at 375 and 1280 | `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` · `vitest:ui/src/help/glossary.test.ts::"every short definition is at most two sentences, has no exclamation mark and names its term"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `ci:walkthrough` · `ci:ui-unit` | met |  |
| help.roles.8 | ROLES | A session is required and no role is: the route sits inside `RequireAuth`, the page has no `can()` branch, and viewer, operator, approver and admin are each walked through it on the live stack and see the same glossary, the same guides and the same decisions | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| help.operations.9 | OPERATIONS | The platform team has nothing to run for this page and nothing that can fail at run time: it calls no API, and the guides and decision records it indexes are bundled into the image at build (the container job fails if `ui/dist` is missing, and the UI build itself fails when the docs are not in its context — P-106), so a deployment with no egress still serves the help — the air-gap posture the deployment guide states | `ci:container` · `test:tests/test_image_bundles_docs.py::test_the_image_context_keeps_every_doc_the_ui_bundles` · `vitest:ui/plugins/requireBundledDocs.test.ts::"fails the build naming the guide that is missing"` · `vitest:ui/plugins/requireBundledDocs.test.ts::"is in the plugins the UI build runs with"` · `doc:docs/DEPLOYMENT.md#7-air-gap-posture` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` | met | |
| help.accessibility.10 | ACCESSIBILITY | The route is captured for viewer, operator, approver and admin at 375 and 1280 with axe (WCAG 2.1 AA) clean on the live stack with a hint bubble open, the top bar is at most two rows at 375, the terms are a definition list with an id per term, and the three sections are named headings | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |
| help.non-goals.11 | NON-GOALS | The page states on itself what it does not hold: the Decisions section says the architecture decision records live in the repository under `docs/adr` and open here as read-only copies built into the deployment, so the page holds no record of its own | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |

## Gaps
