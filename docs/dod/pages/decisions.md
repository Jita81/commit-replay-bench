---
id: dod.page.decisions
level: page
name: Your decisions
scope: /decisions
parent: dod.journey.read-the-map-and-decide
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Your decisions

**Purpose.** Everything that is waiting on a person, across every repository. A cell the
policy would refuse anyway is never listed; it stays on the map with its reason. (`help.ts`
About copy; eyebrow `Journey · 3 of 4 · Decisions`.)

**Entry → exit.** Arrives from the nav step "Decisions" (with the count badge), Home's
Continue for a viewer, or "All decisions" on Baseline. Leaves by one row's act: Attest
(`/signoff?repo=&cell=`, the cell chosen), Sign a gap or Decide or Review (`/factory?repo=&item=`),
Read why (`/routing?repo=`), Investigate (`/ledger?repo=`), Revoke or re-sign a stale cell
(`/signoff?repo=&cell=`); with nothing waiting the page says so; with no repository it leads
to Connect.

**Non-goals.** No act is recorded here: the act is taken on the page the row links to. A cell
the policy would refuse is not listed. The inbox is rebuilt in the browser from the map,
sign-offs and factory tasks of every repository; there is no server-side inbox endpoint (F6).

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| decisions.purpose.1 | PURPOSE | The About block states the page's job in one sentence and the eyebrow reads "Journey · 3 of 4 · Decisions" | `hint:about:/decisions` · `vitest:ui/src/help/hints-ratchet.test.tsx::"a journey eyebrow carries nav.journey_position"` · `vitest:ui/src/components/Layout.test.tsx::"derives "Journey · n of 4 · Step" from the pathname, with an optional sub"` | met | |
| decisions.entry-exit.2 | ENTRY-EXIT | The nav badge carries the count; every row deep-links to the page that records the act with the repository and cell in the link; no repository leads to Connect; a connected but unmeasured repository reads "nothing measured yet"; nothing waiting is said, not hidden | `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"an approver sees the rows across repositories with the act and the deep link"` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"nothing waiting is said, not hidden"` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"a connected but unmeasured repository is "nothing measured yet", never "no repository connected""` · `vitest:ui/src/screens/Decisions/decisions.test.ts::"a deliver cell without an active sign-off is a sign-off due for the approver, deep-linked"` · `hint:id:nav.decisions_count` | met | |
| decisions.truth.3 | TRUTH | The kicker names the apparatus in force as a term; every row's evidence line shows the cell, n, the 95% Wilson interval and the reason code with its sentence; the count pill reads "counting…" until every repository's queries have settled; a stale row shows the apparatus it was signed under against the current one and its n, point and lower bound | `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"the kicker names the apparatus as a term"` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"an approver sees the rows across repositories with the act and the deep link"` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"a viewer reads a stale sign-off"` · `vitest:ui/src/screens/Decisions/decisions.test.ts::"human and do_not_ship cells are rows with their reason"` · `route:GET /version` | met | |
| decisions.truth.4 | TRUTH | A cell the policy would refuse is never a row; an active sign-off clears its row and a revoked one does not; factory unsigned gaps, rework verdicts and a withheld delivery each become a row | `vitest:ui/src/screens/Decisions/decisions.test.ts::"an active sign-off clears the row"` · `vitest:ui/src/screens/Decisions/decisions.test.ts::"factory items: unsigned gaps, rework verdicts and a withheld delivery each become a row"` · `code:ui/src/screens/Decisions/decisions.ts::decisionsFor` | met | |
| decisions.actions.5 | ACTIONS | Every row shows the act verb only to the role that can take it and "Read" plus "<role> acts" otherwise; a stale row offers "Revoke or re-sign" only to an approver | `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"a viewer sees the same rows with Read and the role that acts"` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"a viewer reads a stale sign-off"` | met | |
| decisions.actions.6 | ACTIONS | A failed repository query is shown with its status code and what to do next | `absent` | unmet | G-134 |
| decisions.explanation.7 | EXPLANATION | Every kicker, pill, tag, evidence line, act and stale row carries a registry hint and the ratchet enforces the route for every role whose branch renders (viewer, operator, approver) | `hint:ratchet:/decisions` · `hint:about:/decisions` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"every kicker, pill, tag, evidence line, act and stale row carries a hint"` | partial | G-132 |
| decisions.evidence.8 | EVIDENCE | The rows, the kicker, the stale section and the empty states are unit-tested; the route renders for every role at 375 and 1280 with axe clean once `data-ready` is true; a walkthrough follows Attest from a row to the sign-off form with the cell preselected | `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"an approver sees the rows across repositories with the act and the deep link"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` | partial | G-133 |
| decisions.roles.9 | ROLES | Every read behind the inbox is served to a signed-in viewer (API.md role column); the act is offered only to the role the row names and the sign-off itself is refused at the API to anyone but an approver | `route:GET /signoffs?repo=[&include_revoked=true]` · `route:GET /factory/{repo}/tasks` · `route:GET /repos` · `test:tests/test_server_routes_capability.py::test_viewer_reads` · `vitest:ui/src/screens/Decisions/DecisionsPage.test.tsx::"a viewer sees the same rows with Read and the role that acts"` | met | |
| decisions.operations.10 | OPERATIONS | The inbox is served by one endpoint the platform team can watch and cache, not rebuilt in every browser from three queries per repository on every screen | `code:ui/src/screens/Decisions/useDecisionCount.ts::useDecisions` · `measured:N repositories → 3N queries per visit, repeated by the nav badge on every screen (useDecisionCount.ts, Layout.tsx)` | unmet | F6 |
| decisions.operations.11 | OPERATIONS | The guide says what to do before anyone signs and why a sign-off expires; a false-Q1 row raises the stop-condition banner above this page with a way forward | `doc:docs/ONBOARDING-A-REPO.md#step-6-before-anyone-signs-anything` · `doc:docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp-evidence-expires` · `hint:id:banner.shell.stop_condition` · `doc:docs/OPERATOR.md#8-stop-conditions` | met | |
| decisions.accessibility.12 | ACCESSIBILITY | Renders for every role at 375 (top bar at most two rows) and 1280 with axe WCAG 2.1 AA clean while a hint bubble is open; a keyboard-only pass opens a hinted control's bubble on focus and hides it on Tab away; reduced motion is honoured | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `code:ui/src/index.css` | partial | G-905 |
| decisions.non-goals.13 | NON-GOALS | The About block's purpose line says a refused cell is never listed, and the approver's next step says the act is taken elsewhere ("Decline by doing nothing: an unsigned cell keeps its route") | `hint:about:/decisions` · `vitest:ui/src/components/Help.test.tsx::"says, on each screen whose definition of done quotes it, the sentence that record quotes"` | met | |

## Gaps
- **G-132** — the operator is not in the ratchet's role list for /decisions although the operator branch renders StartButton on item_human and rework rows · add `'operator'` to `ONRAMP_SCREENS['/decisions'].roles` with a factory-tasks fixture that yields those rows · ui
- **G-133** — no walkthrough follows a row: 07 runs axe and 11 renders; the Attest deep link with the cell preselected is asserted in jsdom only, and 08-signoff picks the cell from the dropdown · add one 08-signoff step that visits /decisions as the approver, clicks Attest and asserts `/signoff?repo=&cell=` with the cell already chosen · ui
- **G-134** — a failed repository query is rendered as `new Error(string)`, so the envelope's status and code are lost and the state does not say what to do · pass the `ApiError` through to ErrorState and keep its retry · ui
- **G-905** — the 11-screens keyboard pass tabs through `/results` only and the `scrollWidth` check exists for `/factory` only, so `/connect/:name/measure`, `/oracle`, `/capability`, `/decisions`, `/routing`, `/signoff` and `/factory` have no keyboard-only assertion and no "no horizontal scroll at 375" assertion · loop the tab pass and a `scrollWidth <= clientWidth` check over those routes in `11-screens.spec.ts` · ui
