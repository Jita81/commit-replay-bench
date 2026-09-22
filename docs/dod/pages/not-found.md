---
id: dod.page.not-found
level: page
name: This page does not exist
scope: *
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# This page does not exist

**Purpose.** "Nothing lives at this address" — the empty state under the title "This page does
not exist", inside the shell, showing the address that was asked for and one way back to Home.
It is the screen a lost person lands on, so it has to say where they are and what to do.

**Entry → exit.** Arrives on any authenticated URL the route table does not match — a mistyped
address, a stale bookmark, a link from an older version — while an unmatched URL with no session
bounces to `/login?next=` first, so nothing about the route space is shown before sign-in. Leaves
by "Back to Home" (`button.notfound.home`), the journey's start, or by any shell nav entry: the
nav, the health pill, the role chip and the stop-condition banner are all still on screen.

**Non-goals.** The page does not search for what the person meant, suggest a near match, report a
broken link, or offer the repositories list (which is not in the journey nav). It calls no API, so
it never distinguishes "no such route" from "a record that was deleted" — a missing run or task is
the API's 404 on its own page, not this one.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| not-found.purpose.1 | PURPOSE | The page says in plain words what happened before it says anything else: the eyebrow "Not found", the title "This page does not exist" and the empty state "Nothing lives at this address" | `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` | met | |
| not-found.entry-exit.2 | ENTRY-EXIT | The dead end has one named way out and the shell around it stays usable: "Back to Home" leads to the journey's start and the primary nav renders with it, so no unknown address strands a person | `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` · `hint:id:button.notfound.home` | met | |
| not-found.entry-exit.3 | ENTRY-EXIT | The page says what to do, not only where to go: it names the likely causes of the failure (a mistyped address, a link from an older version, a record that no longer exists) and the next move for each, so a person who did not arrive here by typing knows whether to report it | `absent` | unmet | G-196 |
| not-found.truth.4 | TRUTH | The address the page reports is the address that was asked for, query string and hash included, so it matches the link the person followed | `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` | partial | G-197 |
| not-found.actions.5 | ACTIONS | The page has one action and it names its destination: "Back to Home". Nothing here writes, spends or can fail, so there is no success or error state to state | `code:ui/src/screens/NotFoundPage.tsx::NotFoundPage` · `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` | met | |
| not-found.explanation.6 | EXPLANATION | Every element carries a hint and the ratchet holds `*` with a `SCREENS` entry and a `MIN_HINTS` floor, and the screen carries an About block like every other | `hint:id:button.notfound.home` · `vitest:ui/src/help/help.test.ts::"every route in App.tsx except /login and * has an entry"` · `vitest:ui/src/components/Help.test.tsx::"renders nothing on a route with no entry"` | partial | G-909 |
| not-found.evidence.7 | EVIDENCE | The page's two facts — it shows the path, it leads back to Home — are unit-tested, the shell-intact behaviour is asserted end to end, and a CI job runs both suites | `vitest:ui/src/screens/NotFoundPage.test.tsx::"shows the path and leads back to Home"` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` | partial | G-910 |
| not-found.evidence.8 | EVIDENCE | An unknown address is walked on the live stack and captured, like every other route | `absent` | unmet | G-918 |
| not-found.roles.9 | ROLES | Every role sees the same page and no role sees it sooner: the route sits inside `RequireAuth`, so an unmatched URL with no session lands on `/login?next=` and the product tells an anonymous visitor nothing about which addresses exist | `code:ui/src/lib/auth.tsx::RequireAuth` · `code:ui/src/App.tsx::App` · `spec:ui/e2e/smoke.spec.ts::"a protected route redirects to /login with ?next="` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` | met | |
| not-found.operations.10 | OPERATIONS | A person who lands here still sees the platform's state: the page renders inside the shell, so the health pill, the version line and the stop-condition banner (the red "Delivery halted" row a false-Q1 ledger raises above every screen) are on screen, and the page itself calls no API, so it cannot add a failure of its own | `code:ui/src/components/Layout.tsx::StopConditionBanner` · `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` · `route:GET /health` | met | |
| not-found.accessibility.11 | ACCESSIBILITY | An axe (WCAG 2.1 AA) scan of an unknown address at 375 and 1280 reports no violation | `spec:ui/e2e/smoke.spec.ts::"unknown routes render the 404 inside the shell"` | unmet | G-918 |
| not-found.non-goals.12 | NON-GOALS | The page states what it will not do — it does not search, guess a near match or report the link — so a person does not wait for it to recover for them | `absent` | unmet | G-196 |

## Gaps
- **G-909** — `/login`, `/help`, `/help/docs/:name` and `*` have no `SCREENS` entry and no `MIN_HINTS` floor: the ratchet skips them by name (`hints-ratchet.test.tsx:184`), so a new unhinted element on any of them never fails a test, against the operator's ask that every element explains itself · add a `SCREENS` entry with a fixture and a floor for each (login 4, help 2, guide 1, 404 1) and delete the skip · ui
- **G-910** — `ci.yml` has no UI job: `tsc -b`, vitest, the hint ratchet and the mocked smoke spec run only as local gates before a release, so a hint-registry or type regression passes branch protection and the only axe run on `/login` and the only end-to-end 404 are local-only evidence; README's "eleven jobs" also counts the two-way Python test matrix as two jobs · add a `ui` job to `ci.yml` running `npm ci`, `tsc -b`, `npm test` and the mocked smoke spec, and correct the README count · deploy
- **G-196** — the 404 says where to go but not why the address failed nor what it will not do: no cause, no "check the address", no "a run or task may have been deleted", no statement that it does not search or report the link · add two sentences to the empty state's reason and one non-goal line · ui
- **G-197** — the reason shows `location.pathname` only, dropping the query string and hash, so the address reported is not the address requested · render `pathname + search + hash` · ui
- **G-918** — no axe run and no live-stack visit for an unknown address: the mocked smoke test runs no scan and the walkthrough's route list has no unmatched path · add `*` (an unknown path, About block absent) to the walkthrough's route list so it is captured and axe-swept per persona at both widths · ui
