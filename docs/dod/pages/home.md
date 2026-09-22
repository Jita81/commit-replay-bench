---
id: dod.page.home
level: page
name: Home — Get started / Where this deployment is
scope: /home
parent: dod.journey.orient
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Home — Get started / Where this deployment is

**Purpose.** "This is where the deployment is on the way from an empty install to a change
delivered under evidence. The task list is the operators' progress; every role can read it."
(`help.ts`, the About block for `/home`). Eyebrow: `Journey · start`.

**Entry → exit.** Arrives from the index redirect, the brand link and the Home nav entry on every
screen, a direct sign-in (`LoginPage` default `next`), and the 404's "Back to Home". Leaves by one
of the eight task links (Connect GitHub → `/connect`, Choose a repository → `/connect`, Confirm its
shape → `/repos/:name`, Prove the instrument → `/connect/:name`, Measure → `/connect/:name/measure`,
Read the baseline → `/results?repo=`, Invite an approver → `/settings` for an admin or `/posture` for
anyone else, Deliver → `/factory?repo=`), by Continue (the first task the operator can act on now;
a viewer's Continue goes to the baseline or Decisions), or by the sandbox banner's link to `/posture`.

**Non-goals.** The page starts no run, writes nothing and keeps no status locally: every tag is
derived from the API on each visit. It is not a quality figure ("n of 8" is progress); the numbers
with n and interval live on the Baseline. A viewer cannot start a task from here.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| home.purpose.1 | PURPOSE | The About block's first sentence says what the page is for and the eyebrow reads `Journey · start`, so a person can say where they are | `hint:about:/home` · `vitest:ui/src/components/Layout.test.tsx::"derives "Journey · n of 4 · Step" from the pathname, with an optional sub"` | met | |
| home.entry-exit.2 | ENTRY-EXIT | A direct sign-in lands here; Continue names the task it opens ("Continue to task n: <name>") and lands on it; every task row is a link to its page; a non-admin's Invite an approver goes to `/posture`, never to a page that refuses them | `spec:ui/e2e/walkthrough/01-login.spec.ts::"a wrong password shows the error envelope"` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"a stale sign-off (the apparatus moved on) completes nothing: task 6 stays Incomplete and Continue lands on it"` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"an active sign-off completes "Read the baseline""` | met | |
| home.truth.3 | TRUTH | "You have completed n of 8 tasks" counts tasks tagged Completed and the About block says it is progress, not quality; every tag is derived from the API — the App and its installations, the repositories, the probe, oracle and controls stages, the map's `n_total`, a sign-off the API flags active and not stale, the users list, the frozen backlog and the active factory run ("item k of n" from `progress`) — and a failed read of any of them shows an error envelope, never a false "no repository yet" or "Cannot start yet" | `vitest:ui/src/screens/Home/HomePage.test.tsx::"derives the eight tasks from the API and counts the completed ones"` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"reads the factory task from the API facts, delivered first"` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"an App that is configured with no installation on record is "Incomplete", never "Completed" because a repository exists"` · `hint:about:/home` | partial | G-164 |
| home.truth.4 | TRUTH | Task 6 "Read the baseline" reads Completed once the baseline has been read, as its name says, not only once a cell has been signed off | `absent` | unmet | G-165 |
| home.actions.5 | ACTIONS | Both actions are navigations that name their destination: Continue opens the named task (an operator) or the baseline for the named repository, else Decisions (a viewer, an approver); the task links open the named page; nothing here writes or spends | `vitest:ui/src/screens/Home/HomePage.test.tsx::"a viewer reads the same list as a progress report, a measurement in flight is "In progress", and the map opens from the first row"` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"with nothing connected every task after the first is not started"` | met | |
| home.explanation.6 | EXPLANATION | Every element — the kicker, the sandbox banner's lead line, each task's status tag, the "n of 8" summary and Continue — carries a hint, the ratchet enforces the route for viewer, operator and admin with a floor of 10 hinted elements, and the About block gives a next step per role, what the number means, four terms and two guide links | `hint:ratchet:/home` · `hint:about:/home` · `vitest:ui/src/help/hints-ratchet.test.tsx::"${pattern} as ${role}: every element carries a resolved hint"` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"every task tag, the kicker, the summary, the banner and Continue carry a hint"` | met | |
| home.evidence.7 | EVIDENCE | The eight task statuses, the viewer's reading, the factory item count and the hints are unit-tested and the unit suite runs in CI; the route is axe-swept at 1280 and captured for four personas at 375 and 1280 with the About block and a hint open | `vitest:ui/src/screens/Home/HomePage.test.tsx::"derives the eight tasks from the API and counts the completed ones"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `ci:ui-unit` | met |  |
| home.evidence.8 | EVIDENCE | A walkthrough asserts a task's tag against the live stack's state — Choose a repository reads Completed after the repository is onboarded, Measure reads Completed after the replay — so the derivation is proven on real data, not only on mocks | `absent` | unmet | G-166 |
| home.roles.9 | ROLES | The API gates the one role-bound read (`GET /users` is admin-only and the page requests it only as an admin — a viewer's task 7 falls back to their own role); the UI shows an operator "Get started" and everyone else "Where this deployment is" with a lede that says they change nothing; Invite an approver links to Settings only for an admin and others read "Only an admin can add users"; an approver sees the reading the About block describes for them | `test:tests/test_server_auth.py::test_viewer_cannot_manage_users` · `doc:docs/API.md#admin` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"a viewer reads the same list as a progress report, a measurement in flight is "In progress", and the map opens from the first row"` · `hint:about:/home` | partial | G-911 |
| home.operations.10 | OPERATIONS | When the sandbox probe is not `ok` the page shows an "Important" banner naming the probe's status, says anything measured now is a development reading, and links to the deployment's health; a false-Q1 row on the ledger renders the red "Delivery halted" banner above this and every screen with a link to the ledger; the guide the About block links names step 0's health check | `route:GET /health` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"every task tag, the kicker, the summary, the banner and Continue carry a hint"` · `code:ui/src/components/Layout.tsx::StopConditionBanner` · `doc:docs/ONBOARDING-A-REPO.md#step-0-deploy-the-stack-operator-once` · `doc:docs/OPERATOR.md#7-when-the-sandbox-is-unavailable` | met | |
| home.accessibility.11 | ACCESSIBILITY | The task list is a named list, axe (WCAG 2.1 AA) is clean at 1280 on live data and at 375 and 1280 with a hint open for every persona, the top bar is at most two rows at 375, and the page has no horizontal scroll at 375 | `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | partial | F26 |
| home.non-goals.12 | NON-GOALS | The page states its non-goals where the person stands: the inset text says nothing spends money without a queued run they can see and cancel, the About block says "n of 8" is progress not quality and tells a viewer "You cannot start a task from here" | `hint:about:/home` · `vitest:ui/src/screens/Home/HomePage.test.tsx::"a viewer reads the same list as a progress report, a measurement in flight is "In progress", and the map opens from the first row"` | met | |

## Gaps
- **G-164** — a failed `GET /repos`, `/health`, `/capability-map`, `/signoffs` or `/users` renders as "no repository yet", "Cannot start yet" or "Not known yet" with no error envelope: `HomePage.tsx` imports no `ErrorState` and has no `isError` branch for those reads (only the GitHub App read shows "Unavailable") · render an `ErrorState` with Retry when any of those queries is in error and tag the tasks that depend on it "Unavailable" · ui
- **G-165** — task 6 "Read the baseline" completes only on a sign-off the API flags active and not stale (`HomePage.tsx`, `baselineActed`), so a baseline that was read and not signed can never complete and the tag contradicts the task's name; no API field backs the status · either rename the task "Sign off a cell" or complete it on a server-recorded fact (the first `GET /capability-map` read by a person, or a review record) · server
- **G-166** — no walkthrough asserts a task tag against the live stack: `07` visits `/home` for axe and `11` for the capture and About block, so the derivation of Completed / Incomplete / Cannot start yet is proven on mocks only · after `02-repo-onboard` assert task 2 reads Completed, after `05-replay-fake` assert task 5 reads Completed and task 6 Incomplete · ui
- **G-911** — an approver sees the operator's view — the title "Get started" and "Continue to task n" — because `can('operator')` is true for an approver (`ROLE_ORDER` in `types.ts`), while the About block tells the approver "Nothing here needs you until task 7 is done"; the page and its help disagree for one role and no test covers the approver · decide the approver's reading (the progress report, per the About copy), gate the operator view on that decision and add the approver case to `HomePage.test.tsx` · ui
- F26 — collapsible navigation under 640 px: the three nav rows take half a phone's first screen (backlog, `docs/reviews/2026-09-17-enterprise-front-end.md` §9).
