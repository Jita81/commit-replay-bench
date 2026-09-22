---
id: dod.page.help-docs-name
level: page
name: Bundled guide
scope: /help/docs/:name
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Bundled guide

**Purpose.** The page header is the guide's own title and its one-line blurb — the same pair the
`/help` index offered — above the guide's full text. Every heading carries the id its slug gives,
which is how a screen's Read more lands on the section rather than the top.

**Entry → exit.** Arrives from every About block's Read more, every `<DocLink>` on a screen
(Measure, Factory, Deployment, Settings), the glossary's "Read more" and the guide index — with or
without a `#slug`, which the page scrolls to once the text is in. Leaves by "Back to glossary and
guides" to `/help`, or by any shell nav entry; an unknown name leaves by the empty state's link to
`/help`.

**Non-goals.** The page does not fetch a guide over the network, edit or comment on one, search
across guides, or render the ADRs (they are not bundled). It is a reader, not the source: the
guide's text is `docs/<NAME>.md` in the repository, copied in at build.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| help-docs-name.purpose.1 | PURPOSE | The guide's header shows the same title and one-line blurb the `/help` index offered for that guide | `code:ui/src/help/docs.ts::DOC_TITLES` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` | met | |
| help-docs-name.entry-exit.2 | ENTRY-EXIT | A Read more anchor lands on the heading it names — every anchor in the screens' help and in the glossary is checked against the bundled guide and its real headings — and every state leads back: the guide has "Back to glossary and guides", the unknown-name state has a link to the index, and the shell nav is intact in both | `vitest:ui/src/help/help.test.ts::"every readMore anchor (screens and terms) names a bundled guide and a real heading"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `code:ui/src/components/govuk.tsx::BackLink` | met | |
| help-docs-name.truth.3 | TRUTH | The page renders no number of its own, and with the network blocked it still renders the guide's full text, matching the repository's `docs/<NAME>.md` | `vitest:ui/src/help/docs.test.ts::"loadDoc serves the file on disk and rejects an unknown name"` · `code:ui/src/help/docs.ts::DOC_NAMES` · `code:ui/src/help/docs.ts::isDocName` | met | |
| help-docs-name.truth.4 | TRUTH | The page never blames the wrong thing: a guide whose chunk fails to load renders "No guide with that name" with the name in the reason — the same screen as a name that does not exist — so a person is told their link is wrong when the deployment's asset failed | `code:ui/src/screens/Help/DocPage.tsx::DocPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` | unmet | G-148 |
| help-docs-name.actions.5 | ACTIONS | The page performs no action that writes or spends; while the chunk is loading it says "Loading the guide…" as a live status, and both stops (unknown name, failed load) end in an empty state that names what was asked for and offers one way on | `code:ui/src/screens/Help/DocPage.tsx::DocPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` | met | |
| help-docs-name.explanation.6 | EXPLANATION | Every element in the page body carries a hint — the Back link and the empty state's link included — and the ratchet holds the route with a `SCREENS` entry and a `MIN_HINTS` floor | `code:ui/src/components/govuk.tsx::BackLink` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx except /login and * has an entry"` · `vitest:ui/src/components/Help.test.tsx::"renders nothing on a route with no entry"` · `hint:ratchet:/help/docs/:name` · `hint:id:link.help.back` · `hint:id:link.help.index` | met |  |
| help-docs-name.evidence.7 | EVIDENCE | The render, the slug ids, the unknown name and the anchor contract are unit-tested, and a CI job runs that suite | `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `vitest:ui/src/help/docs.test.ts::"slugify follows the GitHub rule so the docs’ own anchors resolve"` · `ci:ui-unit` | met |  |
| help-docs-name.evidence.8 | EVIDENCE | Every one of the eight guides is opened on the live stack and renders its text: the walkthrough visits `OPERATOR` only, so the other seven guides — including SECURITY and DEPLOYMENT, the two a reviewer is most likely to open — are proven by a unit test against a jsdom renderer and never against the served bundle | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `ci:walkthrough` | unmet | G-149 |
| help-docs-name.roles.9 | ROLES | A session is required and no role is: the route sits inside `RequireAuth`, the page has no `can()` branch, and viewer, operator, approver and admin each read the same guide on the live stack | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| help-docs-name.operations.10 | OPERATIONS | Nothing on this page can fail against a network: the guide is a chunk of the image (the container job fails if the built UI is missing) and no API is called, which is what lets a private, no-egress deployment serve its own documentation | `ci:container` · `doc:docs/DEPLOYMENT.md#7-air-gap-posture` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` | met | |
| help-docs-name.accessibility.11 | ACCESSIBILITY | The route is captured for viewer, operator, approver and admin at 375 and 1280 with axe (WCAG 2.1 AA) clean and a hint bubble open, the top bar is at most two rows at 375, the page does not scroll sideways at 375 (`scrollWidth <= innerWidth`) although the guides carry long unbroken tokens in inline code, and the guide is an `article` whose headings carry slug ids so a screen reader can move by heading | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `code:ui/src/index.css::".prose-doc code"` | met | |
| help-docs-name.non-goals.12 | NON-GOALS | The page says where it stands what it is not: that this is a bundled copy of the repository's guide, that it is read-only, and that the ADRs are not here | `absent` | unmet | G-150 |

## Gaps
- **G-148** — a chunk that fails to load is reported as "No guide with that name" (`DocPage.tsx`, `failed` and `!known` share one branch), blaming the person's link for the deployment's failure, with no retry · split the two states: keep the empty state for an unknown name, and render an `ErrorState` with Retry when `loadDoc` rejects · ui
- **G-149** — only `OPERATOR` is opened on the live stack (`11-screens.spec.ts` routes list); the other seven guides are proven by a unit test alone · add the remaining seven names to the walkthrough's route list, or one spec that opens each guide and asserts its first heading · ui
- **G-150** — the page states none of its non-goals: nothing says the text is a build-time copy of the repository's guide, that it cannot be edited here, or that the ADRs are not bundled · add one line under the header ("A copy of the repository's guide, built into this deployment. Read-only.") · ui
