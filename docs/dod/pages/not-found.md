---
id: dod.page.not-found
level: page
name: This page does not exist
scope: *
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: done                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-27
updated: 2026-09-26
---

# This page does not exist

**Purpose.** "Nothing lives at this address" — the empty state under the title "This page does
not exist", inside the shell, showing the whole address that was asked for, why an address fails and what to do about it, and
one way back to Home.
It is the screen a lost person lands on, so it has to say where they are and what to do.

**Entry → exit.** Arrives on any authenticated URL the route table does not match — a mistyped
address, a stale bookmark, a link from an older version — while an unmatched URL with no session
bounces to `/login?next=` first, so nothing about the route space is shown before sign-in. Leaves
by "Back to Home" (`button.notfound.home`), the journey's start, or by any shell nav entry: the
nav, the health pill, the role chip and the stop-condition banner are all still on screen (on a phone the
nav, the pill and the chip are behind Menu, whose button shows a health that is not OK).

**Non-goals.** The page does not search for what the person meant, suggest a near match, report a
broken link, or offer the repositories list (which is not in the journey nav). It calls no API, so
it never distinguishes "no such route" from "a record that was deleted" — a missing run or task is
the API's 404 on its own page, not this one.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| not-found.purpose.1 | PURPOSE | The page says in plain words what happened before it says anything else: the eyebrow "Not found", the title "This page does not exist" and the empty state "Nothing lives at this address" | `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` | met | |
| not-found.entry-exit.2 | ENTRY-EXIT | The dead end has one named way out and the shell around it stays usable: "Back to Home" leads to the journey's start and the primary nav renders with it, so no unknown address strands a person | `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` · `hint:id:button.notfound.home` | met | |
| not-found.entry-exit.3 | ENTRY-EXIT | The page says what to do, not only where to go: it names the likely causes of the failure (a mistyped address, a link from an older version, a record that no longer exists) and the next move for each, so a person who did not arrive here by typing knows whether to report it | `vitest:ui/src/screens/NotFoundPage.test.tsx::"says why the address failed, what to do, and what the page will not do"` · `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` | met | |
| not-found.truth.4 | TRUTH | The address the page reports is the address that was asked for, query string and hash included, so it matches the link the person followed | `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the whole address asked for — the query string and the hash too"` | met | |
| not-found.actions.5 | ACTIONS | The page has one action and it names its destination: "Back to Home". Nothing here writes, spends or can fail, so there is no success or error state to state | `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` | met | |
| not-found.explanation.6 | EXPLANATION | Every element carries a hint and the ratchet holds `*` with a `SCREENS` entry and a `MIN_HINTS` floor, and the screen carries an About block like every other | `hint:id:button.notfound.home` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx has an entry of its own"` · `vitest:ui/src/components/Help.test.tsx::"the four shell screens carry an About block of their own"` · `hint:about:*` · `hint:ratchet:*` | met | |
| not-found.evidence.7 | EVIDENCE | The page's two facts — it shows the path, it leads back to Home — are unit-tested, the shell-intact behaviour is asserted end to end, and a CI job runs both suites | `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` · `ci:ui-unit` · `ci:ui-smoke` | met |  |
| not-found.evidence.8 | EVIDENCE | An unknown address is walked on the live stack and captured, like every other route | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met |  |
| not-found.roles.9 | ROLES | Every role sees the same page and no role sees it sooner: the route sits inside `RequireAuth`, so an unmatched URL with no session lands on `/login?next=` and the product tells an anonymous visitor nothing about which addresses exist | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/smoke.spec.ts::"a protected route redirects to /login with ?next="` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` | met | |
| not-found.operations.10 | OPERATIONS | A person who lands here still sees the platform's state: the page renders inside the shell, so the health pill, the version line and the stop-condition banner (the red "Delivery halted" row a false-Q1 ledger raises above every screen) are on screen — on a phone the pill is behind Menu, and a health that is not OK shows on the Menu button itself — and the page itself calls no API, so it cannot add a failure of its own | `code:ui/src/components/Layout.tsx::StopConditionBanner` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` · `route:GET /health` · `vitest:ui/src/components/Layout.test.tsx::"a health that is not OK stays signalled on the closed Menu button, where the folded pill cannot be seen"` | met | |
| not-found.accessibility.11 | ACCESSIBILITY | An axe (WCAG 2.1 AA) scan of an unknown address at 375 and 1280 reports no violation | `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met |  |
| not-found.non-goals.12 | NON-GOALS | The page states what it will not do — it does not search, guess a near match or report the link — so a person does not wait for it to recover for them | `vitest:ui/src/screens/NotFoundPage.test.tsx::"says why the address failed, what to do, and what the page will not do"` | met | |

## Gaps
