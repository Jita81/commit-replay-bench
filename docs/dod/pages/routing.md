---
id: dod.page.routing
level: page
name: Routing
scope: /routing
parent: dod.journey.read-the-map-and-decide
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-22
---

# Routing

**Purpose.** Every route decision for one repository with its reason and the policy version
that produced it. The rule is published and the same for every cell; a deployment may tighten
it, never loosen it under the same name. (`help.ts` About copy; eyebrow `Instrument · Routes`.)

**Entry → exit.** Arrives from Baseline's "Every route with its reason" (`?repo=` carried), a
Capability cell's "routing", a Decisions row's "Read why", or the instrument nav "Routes"
(operator and above; lands on "Choose a repo"). Leaves with the policy in force (up to seven
thresholds and the rule sentence), the count of cells per route, and one decision per cell:
route, reason code with its sentence, n, point, model split, Wilson interval with provenance,
false-Q1, oracle strength and policy version. There is no outbound link from a decision row;
with nothing measured, Connect or (operator) Start a replay run.

**Non-goals.** The rule is not edited here and cannot be edited per repository: the page reads
the policy from the API. Route counts are cells, not attempts. Nothing is signed or run from
this page.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| routing.purpose.1 | PURPOSE | The About block states the page's job in one sentence and the eyebrow reads "Instrument · Routes"; the page's own purpose line matches it | `hint:about:/routing` · `code:ui/src/screens/Routing/RoutingPage.tsx::RoutingPage` | met | |
| routing.entry-exit.2 | ENTRY-EXIT | With no `?repo=` the empty state leads every role to Connect; with no decisions the replay link is offered only to an operator and every other role reads who starts the run | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"empty states: no repo sends every role to Connection"` | met | |
| routing.entry-exit.3 | ENTRY-EXIT | A decision row links to the cell's ledger rows and to its cell on the map, as the Capability detail does | `absent` | unmet | G-253 |
| routing.entry-exit.13 | ENTRY-EXIT | Arriving from the instrument nav with one repository connected lands on that repository's decisions, as Baseline, Factory and Sign-off do | `absent` | unmet | G-252 |
| routing.truth.4 | TRUTH | The policy card reads the thresholds and the rule sentence from the API (an amended deployment policy is shown as amended); every decision carries n, point, the Wilson interval, false-Q1, oracle strength, the reason code and the policy version; a false-Q1 row makes the read refuse with 409; the reason codes cover every clause of the rule | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"shows the amended rule, the verdict pill, a reason code per decision and the split"` · `test:tests/test_server_routes_capability.py::test_decisions_per_full_cell` · `test:tests/test_routing.py::test_route_decision_to_dict_carries_n_and_method` · `test:tests/test_routing.py::test_reason_codes_cover_every_clause_and_decision_refuses_unknown` · `test:tests/test_server_routes_capability.py::test_false_q1_row_refuses_the_map` · `route:GET /routes?repo=[&by=]` | met | |
| routing.truth.5 | TRUTH | The About block's numbers sentence states the thresholds the deployment is running, not a hard-coded default that can drift from a tightened policy | `hint:about:/routing` · `measured:n = 4 thresholds hard-coded in copy while the page reads them from the served policy, method: by inspection of ui/src/help/help.ts against RoutingPage.tsx, apparatus 2.2 — help.ts says "n ≥ 10, point ≥ 0.90, Wilson lower ≥ 0.80, oracle ≥ 0.80" while RoutingPage reads policy.min_n etc. from GET /routes` | partial | G-255 |
| routing.actions.6 | ACTIONS | A reason code opens its sentence inline as a button (not a hover title) and closes again; the only other act, "Start a replay run" in the empty state, navigates to the run form with the repository carried and is offered only to an operator | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"a reason code opens its sentence inline — a button, not a hover title (J-HEL-15)"` · `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"empty states: no repo sends every role to Connection"` · `hint:id:button.capability.start_replay` | met | |
| routing.explanation.7 | EXPLANATION | Every threshold row, the rule sentence, the route tiles and every table column carry a registry hint; the ratchet enforces the route at 20 hinted elements for every role whose branch renders (viewer and operator); the lower-bound threshold opens on hover with the registry copy | `hint:ratchet:/routing` · `hint:about:/routing` · `vitest:ui/src/help/hints-ratchet.test.tsx::"${pattern} as ${role}: every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"${route}: mouse-over on ${id} opens its bubble with the registry text"` · `hint:id:policy.routing.min_ci_low` | partial | G-254 |
| routing.evidence.8 | EVIDENCE | The policy card, the pills, the reason codes and the empty states are unit-tested; the one rule is tested clause by clause and at the route; a tier-1 walkthrough asserts a decision with its reason code on this page, and the axe sweep visits it | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"shows the amended rule, the verdict pill, a reason code per decision and the split"` · `test:tests/test_routing.py::test_calibrate_when_n_below_minimum` · `test:tests/test_routing.py::test_deliver_only_with_passed_majority_constructible_and_zero_escapes` · `test:tests/test_server_routes_capability.py::test_decisions_per_full_cell` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | partial | G-256 |
| routing.roles.9 | ROLES | The decisions are served to a signed-in viewer (API.md role column); the rule cannot be changed through any route; the replay link is offered only to an operator | `test:tests/test_server_routes_capability.py::test_viewer_reads` · `code:src/crb/server/routes/capability.py::routes` · `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"empty states: no repo sends every role to Connection"` · `adr:0003` | met | |
| routing.operations.10 | OPERATIONS | The read is documented in API.md with its policy thresholds; the guide names the rule, the controls gate and the stop conditions; the stop-condition banner sits above this page with a way forward | `route:GET /routes?repo=[&by=]` · `adr:0003` · `doc:docs/OPERATOR.md#4-read-the-capability-map` · `doc:docs/OPERATOR.md#8-stop-conditions` · `doc:docs/ONBOARDING-A-REPO.md#step-3--prove-the-instrument-on-this-repository-operator-0` · `hint:id:banner.shell.stop_condition` | met | |
| routing.accessibility.11 | ACCESSIBILITY | Renders for every role at 375 (top bar at most two rows) and 1280 with axe WCAG 2.1 AA clean while a hint bubble is open; the axe sweep also visits the page with real decisions on it; a keyboard-only pass reaches a reason-code button and opens it; the twelve-column table does not scroll the page sideways at 375; reduced motion is honoured | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `code:ui/src/index.css::"@media (prefers-reduced-motion: reduce)"` | partial | G-905 |
| routing.non-goals.12 | NON-GOALS | The About block says the rule is the same for every cell and may be tightened but never loosened under the same name, and that route counts are cells, not attempts | `hint:about:/routing` · `adr:0003` | met | |

## Gaps
- **G-905** — the keyboard-only pass now runs on every authenticated route **[measured — n = 24 routes × 4 personas at 1280; method: `ui/e2e/walkthrough/11-screens.spec.ts` calls `keyboardPass` on each route of its `routes()` list, tabbing from the first control inside `#main`; apparatus 2.2 — a count, not a rate, so no interval]** but it stops at the first hinted controls it meets, so **[gap]** no test yet proves a keyboard person can open a map cell, reach a reason-code button, open and close a term with `aria-expanded`, complete the sign-off form and its revoke confirmation, or freeze a backlog with focus moving into the dialog and back · add one per-screen keyboard step to the walkthrough for each of those five controls, asserting focus where the screen moves it · ui
- **G-252** — /routing (and /capability) call `useRepoParam()` without `defaultToLatest`, so the instrument nav lands on "Choose a repo" even when one repository exists · pass `{ defaultToLatest: true }` in RoutingPage and CapabilityPage · ui
- **G-253** — a decision row has no door: neither to the cell's ledger rows nor to its cell on the map, which the Capability detail has · add the same two LinkButtons per row (rows → `/ledger?repo=&capability_class=&size=`, cell → `/capability?repo=`) · ui
- **G-254** — the operator branch (the empty-state replay link) is outside the ratchet's roles for /routing (`['viewer']` only) · add `'operator'` to `INSTRUMENT_SCREENS['/routing'].roles` with an empty-decisions fixture · ui
- **G-255** — help.ts hard-codes the thresholds in prose while the page reads them from `GET /routes`, so the About copy can drift from a tightened deployment policy · make the numbers sentence say "the thresholds are the ones on the policy card" or render them from the same query · ui
- **G-256** — no walkthrough asserts a route decision on /routing (05 asserts "route calibrate" on /capability) and the 07 axe sweep does not visit /routing · add `/routing?repo=` to the 07 sweep and one 05 step asserting the calibrate decision's reason code and policy version · ui
