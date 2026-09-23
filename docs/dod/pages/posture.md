---
id: dod.page.posture
level: page
name: About this deployment (Deployment posture)
scope: /posture
parent: dod.journey.deploy-and-go-live
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# About this deployment (Deployment posture)

**Purpose.** A printable statement of how this deployment is built, secured and audited, for an architecture or security review. Each row is read from the running system or names its source (help.ts `/posture`).

**Entry → exit.** The person arrives from the nav link "Deployment" (`nav.posture`; a review page, not a journey step — the eyebrow is empty), from Home's sandbox banner ("See the deployment's health") or from Home task 7 when they are not an admin. They read five summary lists (build and apparatus, identity and access, execution and egress, delivery, data and audit — 21 rows). Every row whose value is not the production posture ends with the next step: a guide link for everyone and a "Settings" link for an admin. They leave with the statement (the About block says: print it, or send the URL) and, for an admin, the one-click path to Settings.

**Non-goals.** The page changes nothing: it has no form and no button. It never shows a secret value, only whether one is configured. It is not the go-live checklist (DEPLOYMENT §8) and does not tick it. It does not count as a journey step.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| posture.purpose.1 | PURPOSE | The About block states the page's job in one sentence and gives the admin's next step (configure OpenID Connect, set a sealed executor) | `hint:about:/posture` · `vitest:ui/src/components/Help.test.tsx::"says, on each screen whose definition of done quotes it, the sentence that record quotes"` | met | |
| posture.entry-exit.2 | ENTRY-EXIT | The page is reached from the nav "Deployment" link and from Home; every row that is not the production posture ends with a next-step sentence, a guide link and, for an admin, a "Settings" link | `hint:id:nav.posture` · `hint:id:banner.home.sandbox` · `hint:id:link.posture.settings` · `vitest:ui/src/components/govuk.test.tsx::"every row that is not the production posture says what to do next, and the Delivery group reads from the API (J-FAC-10)"` | met | |
| posture.truth.3 | TRUTH | Every live figure is read from the API at view time: version, apparatus and policy from `GET /version`; "k of n installations can deliver" from `GET /github/app`; ledger rows, chain state and false-Q1 total from `GET /ledger/verify`; toolchains, worker and append-only from `GET /health`; a value the API returns only to an admin reads "shown to admins" for everyone else | `route:GET /version` · `route:GET /github/app` · `route:GET /ledger/verify` · `route:GET /health` · `code:src/crb/server/routes/ledger.py::verify_ledger` · `vitest:ui/src/components/govuk.test.tsx::"renders the four groups from the API and never a secret"` | met | |
| posture.truth.4 | TRUTH | Every row names its source or is read from the API: the ten literal rows (belt set v5, signoff-policy.v3, Apache-2.0, roles, separation of duties, secrets, writes, override, credentials, raw retention, export) say which setting, policy file or code they come from; and a failed `GET /version` shows a sentence, never "…" for ever | `absent` | unmet | G-212 |
| posture.actions.5 | ACTIONS | The kicker says "printable" and the page prints as one statement: a Print control or a print stylesheet exists, and the nav chrome is out of the print | `absent` | unmet | G-213 |
| posture.explanation.6 | EXPLANATION | Every element carries a resolved hint (the ratchet holds `/posture` at 22 hinted elements as viewer and admin), the apparatus row's hover opens its bubble, and the About block is mounted | `hint:ratchet:/posture` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"opens its bubble with the registry text"` · `hint:about:/posture` | met | |
| posture.evidence.7 | EVIDENCE | Unit tests render the page as viewer and as admin from mocked API responses; a tier-1 walkthrough loads the route on the live stack and asserts its rows, and the rendering is captured at 375 and 1280 for every role | `vitest:ui/src/components/govuk.test.tsx::"renders the four groups from the API and never a secret"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | partial | G-214 |
| posture.roles.8 | ROLES | The route is read-only and open to every signed-in role; `GET /settings` is issued only for an admin and is refused for anyone else at the API; the page never shows an admin-only value to a lower role; no audit event is needed because nothing is written | `route:GET /settings` · `test:tests/test_server_system.py::test_settings_requires_admin_and_redacts` · `vitest:ui/src/components/govuk.test.tsx::"renders the four groups from the API and never a secret"` | met | |
| posture.operations.9 | OPERATIONS | The worker, toolchains, append-only and ledger probes are the health check's own sentences; a worker that has stopped checking in, a broken chain, a non-docker executor and an unregistered GitHub App each end with a way forward that links the operator guide | `route:GET /health` · `code:src/crb/server/routes/system.py::probe_worker` · `doc:docs/DEPLOYMENT.md#9-observability` · `doc:docs/OPERATOR.md#6-export-and-verify-the-ledger` · `doc:docs/DEPLOYMENT.md#34-the-workers-sandbox--choose-deliberately` · `doc:docs/GITHUB-APP.md#2-register-the-app-once-per-deployment` | met | |
| posture.accessibility.10 | ACCESSIBILITY | axe (WCAG 2.1 AA) passes on the loaded route at 1280, and at 375 and 1280 for viewer, operator, approver and admin with a hint bubble open (opened by tap at 375, closed by Escape); the top bar wraps to at most two rows at 375; reduced motion is honoured by the stylesheet | `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"the journey screens — Home, Connection, Measure, Results, Decisions, Factory, Deployment — have no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | met | |
| posture.non-goals.11 | NON-GOALS | The page says what it does not do: the inset text says secret values are never shown; the About block says the page changes nothing and is not the go-live checklist | `hint:about:/posture` | partial | G-215 |

## Gaps
- **G-212** — Ten rows are string literals in `PosturePage.tsx` presented as deployment facts with no source, and a failed `GET /version` leaves "…" for ever · read policy and belt-set names from `GET /version`, give each remaining literal a "(from …)" source or move it to `GET /settings`, and render the health-style "could not be read" sentence when `/version` fails · server
- **G-213** — The kicker says "printable" but no `@media print` rule and no Print control exist in `ui/src` · add a print stylesheet that hides the shell and a "Print this page" button on the kicker line · ui
- **G-214** — The walkthrough asserts only two of the 21 rows (the version line and the ledger line) and the unit test title says "four groups" while the page renders five · assert one row per group in `07-settings-and-a11y.spec.ts` and rename the unit test to match the page · ui
- **G-215** — The About block does not say the page changes nothing and is not the go-live checklist · add one sentence to the `/posture` entry in `help.ts` · ui
