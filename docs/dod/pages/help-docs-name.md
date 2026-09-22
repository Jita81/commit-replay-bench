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

**Purpose.** One of the eight bundled guides, read inside the product: "the repository is private
and deployments may have no egress", so the guide is a lazy chunk built into the image and every
heading carries the id its slug gives, which is how a screen's Read more lands on the section
(`DocPage.tsx:7-13`). The header shows the guide's own title and one-line blurb from the registry
(`docs.ts`, `DOC_TITLES`).

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
| help-docs-name.purpose.1 | PURPOSE | The header names the guide being read and says in one line what it covers, both taken from the registry rather than the file, so the title a person sees matches the one the index offered | `code:ui/src/help/docs.ts::DOC_TITLES` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` | met | |
| help-docs-name.entry-exit.2 | ENTRY-EXIT | A Read more anchor lands on the heading it names — every anchor in the screens' help and in the glossary is checked against the bundled guide and its real headings — and every state leads back: the guide has "Back to glossary and guides", the unknown-name state has a link to the index, and the shell nav is intact in both | `vitest:ui/src/help/help.test.ts::"every readMore anchor (screens and terms) names a bundled guide and a real heading"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `code:ui/src/components/govuk.tsx::BackLink` | met | |
| help-docs-name.truth.3 | TRUTH | The page renders no number of its own and the text it shows is the repository's own guide file, loaded from the build's bundle rather than a copy pasted into the UI | `vitest:ui/src/help/docs.test.ts::"loadDoc serves the file on disk and rejects an unknown name"` · `code:ui/src/help/docs.ts::DOC_NAMES` · `code:ui/src/help/docs.ts::isDocName` | met | |
| help-docs-name.truth.4 | TRUTH | The page never blames the wrong thing: a guide whose chunk fails to load renders "No guide with that name" with the name in the reason — the same screen as a name that does not exist — so a person is told their link is wrong when the deployment's asset failed | `code:ui/src/screens/Help/DocPage.tsx::DocPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` | unmet | G-113 |
| help-docs-name.actions.5 | ACTIONS | The page performs no action that writes or spends; while the chunk is loading it says "Loading the guide…" as a live status, and both stops (unknown name, failed load) end in an empty state that names what was asked for and offers one way on | `code:ui/src/screens/Help/DocPage.tsx::DocPage` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` | met | |
| help-docs-name.explanation.6 | EXPLANATION | Every element carries a hint and the ratchet enforces the route — today the page body has no hinted element at all (the Back link is a plain link and the empty state's link carries no hint), the route has no `SCREENS` entry or `MIN_HINTS` floor because the ratchet skips every path starting with `/help`, and the About block is absent by design, so this is the one screen where the shell's promise that every element explains itself does not reach the content | `code:ui/src/components/govuk.tsx::BackLink` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx except /login and * has an entry"` · `vitest:ui/src/components/Help.test.tsx::"renders nothing on a route with no entry"` | unmet | G-100 |
| help-docs-name.evidence.7 | EVIDENCE | The render, the slug ids, the unknown name and the anchor contract are unit-tested — but no CI job runs the unit suite, so all of it is local-only evidence | `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"an unknown name renders the empty state with a link to /help"` · `vitest:ui/src/help/docs.test.ts::"slugify follows the GitHub rule so the docs’ own anchors resolve"` | partial | G-101 |
| help-docs-name.evidence.8 | EVIDENCE | Every one of the eight guides is opened on the live stack and renders its text: the walkthrough visits `OPERATOR` only, so the other seven guides — including SECURITY and DEPLOYMENT, the two a reviewer is most likely to open — are proven by a unit test against a jsdom renderer and never against the served bundle | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `ci:walkthrough` | unmet | G-114 |
| help-docs-name.roles.9 | ROLES | A session is required and no role is: the route sits inside `RequireAuth`, the page has no `can()` branch, and viewer, operator, approver and admin each read the same guide on the live stack | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| help-docs-name.operations.10 | OPERATIONS | Nothing on this page can fail against a network: the guide is a chunk of the image (the container job fails if the built UI is missing) and no API is called, which is what lets a private, no-egress deployment serve its own documentation | `ci:container` · `doc:docs/DEPLOYMENT.md#7-air-gap-posture` · `vitest:ui/src/help/docs.test.ts::"bundles exactly the eight guides and no ADR"` | met | |
| help-docs-name.accessibility.11 | ACCESSIBILITY | The route is captured for viewer, operator, approver and admin at 375 and 1280 with axe (WCAG 2.1 AA) clean and a hint bubble open, the top bar is at most two rows at 375, and the guide is an `article` whose headings carry slug ids so a screen reader can move by heading | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `vitest:ui/src/screens/Help/HelpPage.test.tsx::"renders a bundled guide with slug ids and a way back"` | met | |
| help-docs-name.non-goals.12 | NON-GOALS | The page says where it stands what it is not: that this is a bundled copy of the repository's guide, that it is read-only, and that the ADRs are not here | `absent` | unmet | G-115 |

## Gaps
- **G-100** — `/login`, `/help`, `/help/docs/:name` and `*` have no `SCREENS` entry and no `MIN_HINTS` floor: the ratchet skips them by name (`hints-ratchet.test.tsx:184`), so a new unhinted element on any of them never fails a test, against the operator's ask that every element explains itself · add a `SCREENS` entry with a fixture and a floor for each (login 4, help 2, guide 1, 404 1) and delete the skip · ui.
- **G-101** — no CI job runs the vitest suite or the mocked smoke spec (`ci.yml` has no `npm test` and no `npm run e2e` step): the unit tests, the only axe run on `/login` and the only end-to-end 404 are local-only evidence · add a `ui-unit` job (`npm test`) and a `ui-smoke` job (`npm run e2e`) to `.github/workflows/ci.yml` · deploy.
- **G-113** — a chunk that fails to load is reported as "No guide with that name" (`DocPage.tsx`, `failed` and `!known` share one branch), blaming the person's link for the deployment's failure, with no retry · split the two states: keep the empty state for an unknown name, and render an `ErrorState` with Retry when `loadDoc` rejects · ui.
- **G-114** — only `OPERATOR` is opened on the live stack (`11-screens.spec.ts` routes list); the other seven guides are proven by a unit test alone · add the remaining seven names to the walkthrough's route list, or one spec that opens each guide and asserts its first heading · tests.
- **G-115** — the page states none of its non-goals: nothing says the text is a build-time copy of the repository's guide, that it cannot be edited here, or that the ADRs are not bundled · add one line under the header ("A copy of the repository's guide, built into this deployment. Read-only.") · ui.
