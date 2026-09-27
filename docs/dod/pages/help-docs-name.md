---
id: dod.page.help-docs-name
level: page
name: Bundled guide
scope: /help/docs/:name
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: done                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-26
---

# Bundled guide

**Purpose.** The page header is the guide's own title and its one-line blurb — the same pair the
`/help` index offered — above the guide's full text; a decision record (`/help/docs/ADR-nnnn`)
is headed by its number and title. Every heading carries the id its slug gives,
which is how a screen's Read more lands on the section rather than the top.

**Entry → exit.** Arrives from every About block's Read more, every `<DocLink>` on a screen
(Measure, Factory, Deployment, Settings), the glossary's "Read more" and the guide index — with or
without a `#slug`, which the page scrolls to once the text is in. Leaves by "Back to glossary and
guides" to `/help`, or by any shell nav entry; an unknown name leaves by the empty state's link to
`/help`.

**Non-goals.** The page does not fetch a guide over the network, edit or comment on one, or search
across guides. It is a reader, not the source: the guide's text is `docs/<NAME>.md` in the
repository, and a decision record's `docs/adr/<nnnn>-….md`, copied in at build (DL-077) — the
page says so under its header.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| help-docs-name.purpose.1 | PURPOSE | The guide's header shows the same title and one-line blurb the `/help` index offered for that guide | `code:ui/src/help/docs.ts::DOC_TITLES` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` | met | |
| help-docs-name.entry-exit.2 | ENTRY-EXIT | A Read more anchor lands on the heading it names — every anchor in the screens' help and in the glossary is checked against the bundled guide and its real headings — and every state leads back: the guide has "Back to glossary and guides", the unknown-name state has a link to the index, and the shell nav is intact in both | `vitest:ui/src/help/help.test.ts::"every readMore anchor (screens and terms) names a bundled guide and a real heading"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `code:ui/src/components/govuk.tsx::BackLink` | met | |
| help-docs-name.truth.3 | TRUTH | The page renders no number of its own, and with the network blocked it still renders the guide's full text, matching the repository's `docs/<NAME>.md` | `vitest:ui/src/help/docs.test.ts::"loadDoc serves the file on disk and rejects an unknown name"` · `code:ui/src/help/docs.ts::DOC_NAMES` · `code:ui/src/help/docs.ts::isDocName` | met | |
| help-docs-name.truth.4 | TRUTH | The page never blames the wrong thing: a guide whose chunk fails to load renders the error envelope — "The guide could not be loaded", that the deployment holds it, and Retry — and never "No guide with that name", which is kept for a name the deployment does not hold; Retry loads it | `code:ui/src/screens/Help/DocPage.tsx::DocPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"a guide whose chunk fails to load says so with Retry"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `dl:DL-077` | met | |
| help-docs-name.actions.5 | ACTIONS | The page performs no action that writes or spends; while the chunk is loading it says "Loading the guide…" as a live status, and both stops (unknown name, failed load) end in an empty state that names what was asked for and offers one way on | `code:ui/src/screens/Help/DocPage.tsx::DocPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` | met | |
| help-docs-name.explanation.6 | EXPLANATION | Every element in the page body carries a hint — the Back link and the empty state's link included — and the ratchet holds the route with a `SCREENS` entry and a `MIN_HINTS` floor | `code:ui/src/components/govuk.tsx::BackLink` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx has an entry of its own"` · `vitest:ui/src/components/Help.test.tsx::"the four shell screens carry an About block of their own"` · `hint:about:/help/docs/:name` · `hint:ratchet:/help/docs/:name` · `hint:id:link.help.back` · `hint:id:link.help.index` | met |  |
| help-docs-name.evidence.7 | EVIDENCE | The render, the slug ids, the unknown name and the anchor contract are unit-tested, and a CI job runs that suite | `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `vitest:ui/src/help/docs.test.ts::"slugify follows the GitHub rule so the docs’ own anchors resolve"` · `ci:ui-unit` | met |  |
| help-docs-name.evidence.8 | EVIDENCE | Every one of the eight guides is opened on the live stack and renders its own first heading, the file's, under the page's one h1 — SECURITY and DEPLOYMENT, the two a reviewer is most likely to open, included — and so is a decision record, followed from `/help` | `spec:ui/e2e/walkthrough/13-orient.spec.ts::"all eight bundled guides and a decision record open on the served bundle"` · `ci:walkthrough` | met | |
| help-docs-name.roles.9 | ROLES | A session is required and no role is: the route sits inside `RequireAuth`, the page has no `can()` branch, and viewer, operator, approver and admin each read the same guide on the live stack | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| help-docs-name.operations.10 | OPERATIONS | Nothing on this page can fail against a network: the guide is a chunk of the image (the container job fails if the built UI is missing, and the UI build itself fails when the docs are not in its context — P-051) and no API is called, which is what lets a private, no-egress deployment serve its own documentation | `ci:container` · `test:tests/test_image_bundles_docs.py::test_the_image_context_keeps_every_doc_the_ui_bundles` · `vitest:ui/plugins/requireBundledDocs.test.ts::"fails the build naming the guide that is missing"` · `vitest:ui/plugins/requireBundledDocs.test.ts::"is in the plugins the UI build runs with"` · `doc:docs/DEPLOYMENT.md#7-air-gap-posture` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` | met | |
| help-docs-name.accessibility.11 | ACCESSIBILITY | The route is captured for viewer, operator, approver and admin at 375 and 1280 with axe (WCAG 2.1 AA) clean and a hint bubble open, the top bar is at most two rows at 375, the page does not scroll sideways at 375 (`scrollWidth <= innerWidth`) although the guides carry long unbroken tokens in inline code, and the guide is an `article` whose headings carry slug ids so a screen reader can move by heading, under the page's one h1 — the file's own `#` title is the article's h2, so a reader hears one page title (P-054) | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `code:ui/src/index.css::".prose-doc code"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"a guide and a decision record each carry exactly one h1"` · `vitest:ui/src/help/markdown.test.tsx::"under a page title every heading moves one level down"` | met | |
| help-docs-name.non-goals.12 | NON-GOALS | The page says where it stands what it is not: under the header, that this is a copy of the repository's guide (or decision record) built into the deployment, and that it is read-only — changed in the repository, not here | `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"a decision record renders at /help/docs/ADR-nnnn"` · `code:ui/src/screens/Help/DocPage.tsx::DocPage` | met | |

## Gaps
