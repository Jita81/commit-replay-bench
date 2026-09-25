---
id: dod.page.learn
level: page
name: Learn (what the ledger teaches)
scope: /learn
parent: dod.journey.learn-and-strengthen
children: []
persons: [viewer, operator, approver, admin]
owner: ui
status: partial                # WRITTEN BY THE CHECKER — never by hand
updated: 2026-09-25
---

# Learn (what the ledger teaches)

**Purpose.** "What the ledger teaches, and what the loop does about it: the prevention register
lists every bug class with the change that should remove it and whether it worked; three
reports list refusals that should become guard tests, weak oracles that should become test
work, and evidence that has gone stale since the apparatus changed. The three reports act on
nothing; the register acts only under an operator's switch." (`help.ts` About copy for
`/learn`; the header purpose says the same and the eyebrow reads `Instrument · Learn`.)

**Entry → exit.** Arrive by the Instrument nav entry `Learn` (operator role only,
`Layout.tsx:121`), or from a Decisions `prevention` row, which opens `/learn?repo=&class=` with
that class's details open. Pick a repository and leave with the prevention register — every
bug class with its lever and level, before → after with n and the bar, its status and what
happens next (an operator can throw the switch, revert a change or register a filed item from
here) — and three derivations of its ledger: refusal classes with the spend they cost and a
verdict that is always `unsure`; the cells withheld from deliver for a weak oracle, each shaped
as a test-writing item; and the cells whose rows predate the current apparatus with the rows
and spend still needed. Exits as coded: `Oracle` → `/oracle?repo=` from the strengthen report,
`Queue runs` → `/runs?repo=` from the re-measurement plan, and a class's evidence → `/ledger?repo=`.
With no repository chosen the body is the empty state `Pick a repository` and the only way
forward is the picker in the header.

**Non-goals.** The three reports never write: they append no line to the guard corpus, freeze
no backlog item, queue no run and spend nothing. The register card writes only what an
operator does with its controls, each a record naming the person; it never writes a grader key
and never computes a verdict in the browser (every decision is the server's, re-derived from
the ledger). No report judges a refusal (every verdict is `unsure` by construction), derives a
route in the browser, or blends a rate across apparatus versions.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| learn.purpose.1 | PURPOSE | The header purpose and the About block name the prevention register and the three reports and say that the reports act on nothing and the register acts only under an operator's switch; the card eyebrows read `Prevention`, `Refusals`, `Weak oracles` and `Stale evidence`, never a play number | `hint:about:/learn` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"names the three reports in plain phrases and defines their words inline (J-HEL-17)"` | met | |
| learn.entry-exit.2 | ENTRY-EXIT | With a repository chosen the strengthen report links to `/oracle?repo=` and the re-measurement plan to `/runs?repo=`, both carrying the repository; with none chosen the body says which repository is missing and offers one action to choose it | `hint:id:link.learn.oracle` · `hint:id:link.learn.runs` · `code:ui/src/screens/Learn/LearnPage.tsx::LearnPage` | partial | G-172 |
| learn.truth.3 | TRUTH | The Instrument-caused rows tile reads protocol rows ÷ all rows with that n, a Wilson 95 % interval and the apparatus version the rows carry; with more than one apparatus version on record it shows each version's own rate and counts, and no blended rate is the headline | `test:tests/test_learn.py::test_counts_cost_and_the_denominator` · `test:tests/test_learn.py::test_rows_to_clear_bar_is_the_wilson_minimum_not_min_n` · `code:ui/src/screens/Learn/LearnPage.tsx::RefusalsSection` | partial | G-173 |
| learn.truth.4 | TRUTH | Every verdict in the refusal table reads `unsure`, its pill says a human writes honest or refuse through `crb learn refusals --apply`, and the intro sentence says a person judges each class | `test:tests/test_learn.py::test_never_auto_accepts` · `hint:id:pill.learn.verdict` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"names the three reports in plain phrases and defines their words inline (J-HEL-17)"` | met | |
| learn.truth.5 | TRUTH | Every other figure names where it comes from: `Refusal classes` is grouped by (guard, reason, command shape) over n protocol rows; `Oracle-held cells` names the policy and the oracle threshold; `Rows still needed` names the rule n ≥ min_n per cell; `Estimated spend` multiplies each cell's own mean row cost by the rows needed and reads a dash when no cell's cost is known, with the known-cost cell count as its n | `test:tests/test_learn.py::test_groups_by_reason_and_shape` · `test:tests/test_learn.py::test_unknown_cost_is_honest` · `test:tests/test_learn.py::test_cells_n_needed_cost_and_requests` · `test:tests/test_learn.py::test_policy_min_n` | met | |
| learn.actions.6 | ACTIONS | The three reports perform no write for any role; the register card's switch, revert and register controls render only for an operator, and a viewer sees every change and no control | `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"names the three reports in plain phrases and defines their words inline (J-HEL-17)"` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a viewer sees the switch and every change but no control"` · `code:ui/src/screens/Learn/PreventionSection.tsx::PreventionSection` | met | |
| learn.actions.7 | ACTIONS | While a report is deriving it says which report; a report that fails to load shows the server's reason with a Retry that refetches that report alone and leaves the other two rendered | `absent` | unmet | G-174 |
| learn.actions.8 | ACTIONS | The three hand-offs the About block tells the operator to make — copy a candidate corpus line, freeze a strengthening item on the Factory, queue the re-measurement runs the plan lists — are each one control on the report that computed them | `absent` | unmet | G-912 |
| learn.explanation.9 | EXPLANATION | Every tile, column header, pill, link and nav entry on the route carries a registry hint (at least 26), the ratchet enforces the route, `stat.learn.refusal_share` opens its bubble on hover and closes on Escape, and `apparatus`, `stale`, `cell`, `oracle strength` and `negative controls` open their definitions inline | `hint:ratchet:/learn` · `hint:about:/learn` · `hint:id:stat.learn.refusal_share` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"opens its bubble with the registry text"` | met | |
| learn.evidence.10 | EVIDENCE | Each derivation the page renders is pinned server-side: the refusal grouping and its denominator, the strengthening items against the served controls verdict and oracle scores, and the re-measurement plan's counts, cost and `POST /runs` bodies | `test:tests/test_learn.py::test_groups_by_reason_and_shape` · `test:tests/test_server_routes_learn.py::test_refusals_empty_then_one` · `test:tests/test_server_routes_learn.py::test_strengthen_uses_the_controls_verdict_and_the_oracle_scores` · `test:tests/test_learn.py::test_requests_are_valid_post_runs_bodies` | met | |
| learn.evidence.11 | EVIDENCE | A tier-1 spec renders the three reports on a running stack from real ledger rows and reads a row of each table; the route is captured for every persona at 375 and 1280 | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | partial | G-913 |
| learn.roles.12 | ROLES | Each of the three reads needs `viewer` at the API; an anonymous read is 401 and an unknown repository 404, so neither ever renders as an empty report | `test:tests/test_server_routes_learn.py::test_rbac` · `test:tests/test_server_routes_learn.py::test_unknown_repo_404` · `code:src/crb/server/routes/learn.py::learn_refusals` · `code:src/crb/server/routes/learn.py::learn_strengthen` | met | |
| learn.entry-exit.13 | ENTRY-EXIT | Every role the API admits can reach the page in the UI: the route is viewer-readable and the ratchet renders it as a viewer, so a viewer has a nav entry to it | `absent` | unmet | G-914 |
| learn.operations.14 | OPERATIONS | The three routes are listed in `docs/API.md` with their shapes and their role, and the operator guide has a section for the learning loop that says when to read the page and what to do with each report | `absent` | unmet | G-915 |
| learn.operations.15 | OPERATIONS | The guide the page links is bundled in the product and says what each report means, what the CLI twin is, and why each report stops at a person | `doc:docs/LEARNING-LOOP.md#4-using-it` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` · `hint:about:/learn` | met | |
| learn.accessibility.16 | ACCESSIBILITY | The route is axe-clean (WCAG 2.1 AA) with the three reports rendered, and renders for every persona at 375 and 1280 with the top bar no more than two rows and a hint bubble open | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | partial | G-916 |
| learn.explanation.18 | EXPLANATION | No element on the page explains itself only through a browser tooltip | `code:ui/src/screens/Learn/LearnPage.tsx::StrengthenSection` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a strengthening item shows its description as text, not as a hover-only title (G-287)"` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every title= sits in a file the allowlist names, within its count"` | met |  |
| learn.non-goals.17 | NON-GOALS | The page states what it will not do where the reader meets it: the About block says the three reports act on nothing and the register acts only under an operator's switch, each report's intro names the person who decides, and the guide says why that is deliberate and what the loop will never do | `hint:about:/learn` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` · `doc:docs/LEARNING-LOOP.md#77-what-the-loop-will-never-do` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"names the three reports in plain phrases and defines their words inline (J-HEL-17)"` | met | |
| learn.truth.19 | TRUTH | The register card shows each class with its first-attempt occurrences (k of n), the lever and its level, before → after with both n and the bar sentence, and the status with its qualifiers | `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"the register card shows each class with its lever, level, before → after and status"` · `test:tests/test_server_routes_prevention.py::test_register_is_viewer_readable_and_404s_an_unknown_repo` | met | |
| learn.actions.20 | ACTIONS | Each operator act on the register card — switch, revert, register an item — says what it wrote in a status line naming who and which record, and a refused act shows the server's reason | `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"an operator reverts a change with a reason"` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"the switch needs a reason and names who threw it"` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a filed item registers in one act"` · `test:tests/test_server_routes_prevention.py::test_the_switch_is_operator_only_needs_a_reason_and_names_the_session` | met | |
| learn.explanation.21 | EXPLANATION | Every element of the register card carries a registry hint, and the ratchet renders `/learn` with the register populated, as a viewer and as an operator | `hint:ratchet:/learn` · `hint:id:switch.learn.auto_apply` · `hint:id:col.learn_register.before_after` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every element carries a resolved hint"` | met | |
| learn.evidence.22 | EVIDENCE | A tier-1 walkthrough renders the register card on a running stack from real rows and reads one class | `absent` | unmet | G-175 |
| learn.accessibility.23 | ACCESSIBILITY | The register card is axe-clean (WCAG 2.1 AA) at 375 and 1280 with its table and a class expanded | `absent` | unmet | G-176 |
| learn.entry-exit.24 | ENTRY-EXIT | A Decisions `prevention` row links to `/learn?repo=&class=`, and the Learn page opens with that class shown | `vitest:ui/src/screens/Decisions/decisions.test.ts::"a prevention with no owner is a decision"` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a viewer sees the switch and every change but no control"` | met | |

## Gaps
- **G-172** — The no-repository body is a bare `Pick a repository` with no action (`LearnPage.tsx:398`), unlike Capability, Routing and Oracle, which link to `/connect` · give the `EmptyState` the same `Connection` action and assert it in `LearnPage.test.tsx` · ui
- **G-173** — No test pins what the refusal tiles render: neither the single-apparatus Wilson interval and n, nor the multi-version branch that must not show a blended headline rate (`LearnPage.tsx:243-252`); only the server's derivation is pinned · add a `LearnPage.test.tsx` case with a one-version and a two-version `by_apparatus` fixture asserting the value, n, interval and apparatus line of `stat.learn.refusal_share` · ui
- **G-174** — The per-report loading line (`Deriving …`) and the `ErrorState` Retry (`LearnPage.tsx:222,289,340`) are never rendered in a test, so nothing proves a failed report leaves the other two readable or that Retry refetches · add a `LearnPage.test.tsx` case with a 500 on `/learn/strengthen` only, asserting the other two cards still render and that Retry refetches that query · ui
- **G-912** — The About block tells the operator to "copy a candidate corpus line into a decision file, freeze a strengthening item on the Factory, or queue the re-measurement runs the plan lists" (`help.ts:259`) and the page offers none of the three: the refusal row's `candidate_honest` / `candidate_refused` lines are computed and never shown or copyable, the strengthening items are served in the frozen-backlog shape with no link to the freeze form, and the plan's `POST /runs` bodies are counted but not queueable · add a copy control per refusal row, a `Freeze on the Factory` link that carries the item to `/factory`'s freeze form, and a `Queue` control on the plan that opens the Runs dialog prefilled from `requests` · ui
- **G-913** — No spec renders any of the three reports on a running stack: `11-screens.spec.ts:130` visits `/learn` with no `?repo=`, so only the empty state is ever walked, and the single unit test uses all-empty fixtures · give the walkthrough a `/learn?repo=<primary>` visit that asserts one row of each table and the refusal tile's n and interval · ui
- **G-914** — The Instrument nav entry for `/learn` is `role: 'operator'` (`Layout.tsx:121`) although the three routes are viewer-gated and the hint ratchet renders the page as a viewer (`hints-ratchet.instrument.tsx:473-479`), so a governance reader with API access has no path to it · set the entry's role to `viewer`, as `/ledger` already is, and pin it in `Layout.test.tsx` · ui
- **G-915** — `docs/API.md` lists no `/learn` route and `docs/OPERATOR.md` never mentions the learning loop, so the platform team running the product has no runbook entry for the page or its three reads · add the three rows to API.md §routes with their shapes and `viewer` role, and an OPERATOR section that says when to read each report and what to do with it · docs
- **G-916** — `/learn` is in no axe sweep: `07-settings-and-a11y.spec.ts` covers the journey screens, Capability, Ledger, Sign-off and Oracle, and the only visit to `/learn` renders the empty state · add `/learn?repo=<primary>` to the instrument axe test after the three tables are visible · ui
- **G-175** — no walkthrough renders the register card on a running stack · add a `/learn?repo=<primary>` visit after a tick that asserts one register row · ui
- **G-176** — the register card is in no axe sweep · add `/learn?repo=<primary>` with the register rendered to the instrument axe test at 375 and 1280 · ui
