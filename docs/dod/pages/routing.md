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
updated: 2026-09-26
---

# Routing

**Purpose.** Every route decision for one repository with its reason and the policy version
that produced it. The rule is published and the same for every cell; a deployment may tighten
it, never loosen it under the same name. (`help.ts` About copy; eyebrow `Instrument · Routes`.)

**Entry → exit.** Arrives from Baseline's "Every route with its reason" (`?repo=` carried), a
Capability cell's "routing", a Decisions row's "Read why", or the instrument nav "Routes"
(every role; lands on "Choose a repo"). Leaves with the policy in force (up to seven
thresholds and the rule sentence), the count of cells per route, and one decision per cell:
route, reason code with its sentence, n, point, model split, Wilson interval with provenance,
false-Q1, oracle strength and policy version. There is no outbound link from a decision row;
with nothing measured, Connect or (operator) Start a replay run **[aspiration — this artefact's specification; its criteria state what is met]**.

**Non-goals.** The rule is not edited here and cannot be edited per repository: the page reads
the policy from the API. Route counts are cells, not attempts. Nothing is signed or run from
this page.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| routing.purpose.1 | PURPOSE | The About block states the page's job in one sentence and the eyebrow reads "Instrument · Routes"; the page's own purpose line matches it | `hint:about:/routing` · `code:ui/src/screens/Routing/RoutingPage.tsx::RoutingPage` | met | |
| routing.entry-exit.2 | ENTRY-EXIT | With no `?repo=` the empty state leads every role to Connect; with no decisions the replay link is offered only to an operator and every other role reads who starts the run | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"empty states: no repo sends every role to Connection"` | met | |
| routing.entry-exit.3 | ENTRY-EXIT | A decision row links to the cell's ledger rows and to its cell on the map, as the Capability detail does | `absent` | unmet | G-253 |
| routing.entry-exit.13 | ENTRY-EXIT | Arriving from the instrument nav with one repository connected lands on that repository's decisions, as Baseline, Factory and Sign-off do | `absent` | unmet | G-977 |
| routing.truth.4 | TRUTH | The policy card reads the thresholds and the rule sentence from the API (an amended deployment policy is shown as amended); every decision carries n, point, the Wilson interval, false-Q1, oracle strength, the reason code and the policy version; a false-Q1 row makes the read refuse with 409; the reason codes cover every clause of the rule | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"shows the amended rule, the verdict pill, a reason code per decision and the split"` · `test:tests/test_server_routes_capability.py::test_decisions_per_full_cell` · `test:tests/test_routing.py::test_route_decision_to_dict_carries_the_reading_and_the_counts` · `test:tests/test_routing.py::test_reason_codes_cover_every_clause_and_decision_refuses_unknown` · `test:tests/test_server_routes_capability.py::test_false_q1_row_refuses_the_map` · `route:GET /routes?repo=[&by=]` | met | |
| routing.truth.5 | TRUTH | The About block's numbers sentence names which thresholds apply and points at the Policy in force card, which reads them from the served policy; it repeats no threshold value, in symbols, in words or as the rule's own numbers, that could drift from a tightened policy | `hint:about:/routing` · `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"shows the amended rule, the verdict pill, a reason code per decision and the split"` · `vitest:ui/src/help/help.test.ts::"no About block states a policy threshold as a number: the served policy may be tightened, and the copy would drift (G-255, G-204)"` · `vitest:ui/src/help/help.test.ts::"the threshold matcher finds a threshold however it is written, and passes a number that is not one"` | met | |
| routing.actions.6 | ACTIONS | A reason code opens its sentence inline as a button (not a hover title) and closes again; the only other act, "Start a replay run" in the empty state, navigates to the run form with the repository carried and is offered only to an operator | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"a reason code opens its sentence inline — a button, not a hover title (J-HEL-15)"` · `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"empty states: no repo sends every role to Connection"` · `hint:id:button.capability.start_replay` | met | |
| routing.explanation.7 | EXPLANATION | Every threshold row, the rule sentence, the route tiles and every table column carry a registry hint; the ratchet enforces the route at 20 hinted elements for every role whose branch renders (viewer and operator); the look-rule threshold opens on hover with the registry copy | `hint:ratchet:/routing` · `hint:about:/routing` · `vitest:ui/src/help/hints-ratchet.test.tsx::"${pattern} as ${role}: every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"${route}: mouse-over on ${id} opens its bubble with the registry text"` · `hint:id:policy.routing.looks` | partial | G-254 |
| routing.evidence.8 | EVIDENCE | The policy card, the pills, the reason codes and the empty states are unit-tested; the one rule is tested clause by clause and at the route; a tier-1 walkthrough asserts a decision with its reason code on this page, and the axe sweep visits it | `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"shows the amended rule, the verdict pill, a reason code per decision and the split"` · `test:tests/test_routing.py::test_a_pending_look_routes_calibrate_and_names_the_commits_still_needed` · `test:tests/test_routing.py::test_deliver_only_when_every_clause_holds` · `test:tests/test_server_routes_capability.py::test_decisions_per_full_cell` · `spec:ui/e2e/walkthrough/06c-map-doors.spec.ts::"the map read through its doors: Baseline → All decisions → Open the full map → Every route with its reason"` · `spec:ui/e2e/walkthrough/07-settings-and-a11y.spec.ts::"Routes with decisions has no WCAG 2.1 AA violations"` · `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` | met | |
| routing.roles.9 | ROLES | The decisions are served to a signed-in viewer (API.md role column); the rule cannot be changed through any route; the replay link is offered only to an operator | `test:tests/test_server_routes_capability.py::test_viewer_reads` · `code:src/crb/server/routes/capability.py::routes` · `vitest:ui/src/screens/Routing/RoutingPage.test.tsx::"empty states: no repo sends every role to Connection"` · `adr:0003` | met | |
| routing.operations.10 | OPERATIONS | The read is documented in API.md with its policy thresholds; the guide names the rule, the controls gate and the stop conditions; the stop-condition banner sits above this page with a way forward | `route:GET /routes?repo=[&by=]` · `adr:0003` · `doc:docs/OPERATOR.md#4-read-the-capability-map` · `doc:docs/OPERATOR.md#8-stop-conditions` · `doc:docs/ONBOARDING-A-REPO.md#step-3--prove-the-instrument-on-this-repository-operator-0` · `hint:id:banner.shell.stop_condition` | met | |
| routing.accessibility.11 | ACCESSIBILITY | Renders for every role at 375 (top bar at most two rows) and 1280 with axe WCAG 2.1 AA clean while a hint bubble is open; the axe sweep also visits the page with real decisions on it; a keyboard-only pass reaches a reason-code button and opens it; the twelve-column table does not scroll the page sideways at 375; reduced motion is honoured | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"${persona} @ ${vp.width}: every route renders, is captured, and carries About this screen"` · `code:ui/src/index.css::"@media (prefers-reduced-motion: reduce)"` · `spec:ui/e2e/walkthrough/11b-keyboard.spec.ts::"keyboard: a reason-code button on Routes is reached by Tab and opens and closes with aria-expanded (/routing)"` | met | |
| routing.truth.14 | TRUTH | A decision says whose evidence it rests on: every decision on `/routes` and every cell on `/capability-map` carries `rows_imported` beside `rows`, 0 on the default `apparatus=current` reading the delivery gate uses (it counts rows measured here only), and a route read under an explicit apparatus or `all` over imported rows is documented as a reader's view that licenses nothing | `test:tests/test_evidence_import_governance.py::test_a_readers_view_names_the_imported_rows_behind_every_cell_and_route` · `route:GET /routes?repo=[&by=]` · `dl:DL-079` | met | |
| routing.non-goals.12 | NON-GOALS | The About block says the rule is the same for every cell and may be tightened but never loosened under the same name, and that route counts are cells, not attempts | `hint:about:/routing` · `adr:0003` | met | |

## Gaps
- **G-977** — `/capability` and `/routing` call `useRepoParam()` without `defaultToLatest`, so entering either from the instrument nav asks the person to choose the repository even when one is connected, while Baseline, Factory and Sign-off default to the latest · pass `{ defaultToLatest: true }` in CapabilityPage and RoutingPage · ui
- **G-253** — a decision row has no door: neither to the cell's ledger rows nor to its cell on the map, which the Capability detail has · add the same two LinkButtons per row (rows → `/ledger?repo=&capability_class=&size=`, cell → `/capability?repo=`) · ui
- **G-254** — the operator branch (the empty-state replay link) is outside the ratchet's roles for /routing (`['viewer']` only) · add `'operator'` to `INSTRUMENT_SCREENS['/routing'].roles` with an empty-decisions fixture · ui
