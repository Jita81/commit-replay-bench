---
id: dod.page.help
level: page
name: Glossary and guides
scope: /help
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Glossary and guides

**Purpose.** "Every term the screens use, in plain English, with the number's n, interval and
apparatus where the term is a number." — the lede under the title (`HelpPage.tsx:61`). It is the
one place a person can look up a word they met on a screen without leaving the product.

**Entry → exit.** Arrives from the "?" in the top bar (`nav.help`), the footer's Help and Glossary
links (`nav.footer_help`), every `<Term>` a screen renders, every About block's Read more, and the
guide page's Back link. Leaves by a term's "Read more" (`link.help.read_more`) or a guide title
(`link.help.guide`), both to `/help/docs/<name>#<slug>`, landing on the section itself; the shell
nav stays on screen, so any journey step is one click away.

**Non-goals.** The page reads no API, holds no state and shows no figure of its own: the numbers
with their n and interval live on the screens that measure them. It is not the architecture
decision record — the Decisions section says so on the page: the ADRs are in the repository under
`docs/adr` and are listed here by title only. It does not search, filter or accept a correction.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| help.purpose.1 | PURPOSE | The lede under the title states the page's job in one sentence — every term the screens use, in plain English, with the number's n, interval and apparatus where the term is a number | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |
| help.entry-exit.2 | ENTRY-EXIT | Every entry to the page lands on the thing that was asked for — a term link scrolls to its own entry by `location.hash`, a Read more opens the guide at its heading — and every row leads somewhere: the 22 terms, the 8 guides and the 16 ADR rows are links, so a reviewer following a decision a screen cites (ADR-0015 on the sign-off, ADR-0016 on the two-person rule) can read it from the product | `vitest:ui/src/help/help.test.ts::"every readMore anchor (screens and terms) names a bundled guide and a real heading"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` · `adr:0015` · `adr:0016` | partial | G-156 |
| help.truth.3 | TRUTH | The page publishes no number of its own; every term that names a number carries its threshold, n and apparatus in the definition (the four routing rules and the two rates), and the guide list is the eight the build actually bundles, so the index cannot offer a guide the deployment does not hold | `vitest:ui/src/help/glossary.test.ts::"the four routes and the two rates carry their thresholds"` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` · `code:ui/src/help/docs.ts::DOC_NAMES` | met | |
| help.truth.4 | TRUTH | The Decisions list matches the decision records the repository holds: 16 rows are hand-typed in `HelpPage.tsx` (`ADRS`) and no test compares them with `docs/adr`, so an ADR added, renamed or superseded leaves the page stating a decision list that is not the product's | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `adr:0016` | unmet | G-157 |
| help.actions.5 | ACTIONS | The page performs no action that writes, spends or changes state: its only controls are links whose visible text names where they go (the term's "Read more", the guide's own title), so nothing can succeed or fail silently | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |
| help.explanation.6 | EXPLANATION | Every element on the page carries a hint that opens on hover, focus and tap, and the ratchet holds the route with a `SCREENS` entry and a `MIN_HINTS` floor, so a new unhinted element fails a test | `hint:id:link.help.read_more` · `hint:id:link.help.guide` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx except /login and * has an entry"` · `vitest:ui/src/components/Help.test.tsx::"renders nothing on a route with no entry"` · `hint:ratchet:/help` | met |  |
| help.evidence.7 | EVIDENCE | The page's render, the guide registry and the glossary's copy rules are unit-tested, a CI job runs that suite, and the route is visited on the live stack for four personas at 375 and 1280 | `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` · `vitest:ui/src/help/glossary.test.ts::"every short definition is at most two sentences, has no exclamation mark and names its term"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `ci:walkthrough` · `ci:ui-unit` | met |  |
| help.roles.8 | ROLES | A session is required and no role is: the route sits inside `RequireAuth`, the page has no `can()` branch, and viewer, operator, approver and admin are each walked through it on the live stack and see the same glossary, the same guides and the same decisions | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| help.operations.9 | OPERATIONS | The platform team has nothing to run for this page and nothing that can fail at run time: it calls no API, and the guides it indexes are bundled into the image at build (asserted by the container job, which fails if `ui/dist` is missing), so a deployment with no egress still serves the help — the air-gap posture the deployment guide states | `ci:container` · `doc:docs/DEPLOYMENT.md#7-air-gap-posture` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` | met | |
| help.accessibility.10 | ACCESSIBILITY | The route is captured for viewer, operator, approver and admin at 375 and 1280 with axe (WCAG 2.1 AA) clean on the live stack with a hint bubble open, the top bar is at most two rows at 375, the terms are a definition list with an id per term, and the three sections are named headings | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |
| help.non-goals.11 | NON-GOALS | The page states on itself what it does not hold: the Decisions section says the architecture decision records are in the repository under `docs/adr` and are listed here by title so a screen can name one | `code:ui/src/screens/Help/HelpPage.tsx::HelpPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders the glossary, the guides and the decisions for a viewer"` | met | |

## Gaps
- **G-156** — the 16 ADR rows are plain text (`HelpPage.tsx`, "not bundled, so listed, not linked"), so a reviewer following an ADR a screen cites cannot read it in the product · add the ADR markdown to the bundled glob and route `/help/adr/:id` through the existing renderer, or link each row to the repository file · ui
- **G-157** — the ADR list is hand-typed in `HelpPage.tsx` and no test compares it with `docs/adr/*.md`, so the page can state a decision list the repository does not hold · add a vitest that reads the ADR directory and asserts number and title against `ADRS` (the same shape as the docs registry test) · ui
