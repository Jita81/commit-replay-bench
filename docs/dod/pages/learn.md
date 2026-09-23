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
updated: 2026-09-23
---

# Learn (what the ledger teaches)

**Purpose.** "What the ledger teaches, as three reports: refusals that should become guard
tests, weak oracles that should become test work, and evidence that has gone stale since the
apparatus changed. The product decides nothing; an operator decides here, beside the report, and
every decision is recorded with their name." (`help.ts` About copy for `/learn`; the header
purpose says the same and the eyebrow reads `Instrument · Learn`.)

**Entry → exit.** Arrive by the Instrument nav entry `Learn` (operator role only,
`Layout.tsx:121`) — no other screen links to the route. Pick a repository and leave with three
derivations of its ledger: refusal classes with the spend they cost and a verdict that reads
`unsure` until a named person has decided it; the cells withheld from deliver for a weak oracle, each shaped as a
test-writing item; and the cells whose rows predate the current apparatus with the rows and
spend still needed. An operator also leaves with any of three decisions made: `Decide` records a
refusal class's verdict into the guard corpus, `Register` puts a strengthening item on the
repository's backlog, and `Queue runs` sends a cell's re-measurement runs after showing the
estimate. Exits as coded: `Oracle` → `/oracle?repo=` from the strengthen report, `Factory` →
`/factory?repo=` after a registration, and `Runs` → `/runs?repo=` from the plan and after a
queue. With no repository chosen the body is the empty state `Pick a repository` and the only way
forward is the picker in the header.

**Non-goals.** The page never decides. It offers an operator the three decisions the reports
hand off to, and each one is that person's act, recorded with their name: the page itself judges
no refusal (every served verdict is `unsure` by construction), composes no body (a request names
an id and the server re-derives the line, the item and the run from the ledger), spends nothing
without confirming the estimate first, and offers a viewer none of the three. It never derives a
route in the browser (the held reason and the threshold are the served routing policy's), and
never blends a rate across apparatus versions.

## Definition of done

| id | category | criterion | evidence | state | gap |
|---|---|---|---|---|---|
| learn.purpose.1 | PURPOSE | The header purpose and the About block name the three reports in one sentence and say that the product decides nothing — the decisions are a named operator's; the three card eyebrows read `Refusals`, `Weak oracles` and `Stale evidence`, never a play number | `hint:about:/learn` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"names the three reports in plain phrases and defines their words inline (J-HEL-17)"` | met | |
| learn.entry-exit.2 | ENTRY-EXIT | With a repository chosen the strengthen report links to `/oracle?repo=` and the re-measurement plan to `/runs?repo=`, both carrying the repository; with none chosen the body says which repository is missing and offers one action to choose it | `hint:id:link.learn.oracle` · `hint:id:link.learn.runs` · `code:ui/src/screens/Learn/LearnPage.tsx::LearnPage` | partial | G-172 |
| learn.truth.3 | TRUTH | The Instrument-caused rows tile reads protocol rows ÷ all rows with that n, a Wilson 95 % interval and the apparatus version the rows carry; with more than one apparatus version on record it shows each version's own rate and counts, and no blended rate is the headline | `test:tests/test_learn.py::test_counts_cost_and_the_denominator` · `test:tests/test_learn.py::test_rows_to_clear_bar_is_the_wilson_minimum_not_min_n` · `code:ui/src/screens/Learn/LearnPage.tsx::RefusalsSection` | partial | G-173 |
| learn.truth.4 | TRUTH | A verdict nobody has made reads `unsure`, and its pill says the product never decides; a verdict that HAS been made reads `honest` or `refuse` with the name of the person who made it, served from the decision record rather than derived in the browser; the intro sentence says a person judges each class | `test:tests/test_learn.py::test_never_auto_accepts` · `hint:id:pill.learn.verdict` · `hint:id:pill.learn.decided` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a class already decided reads its verdict and who decided it, and is not offered the form again"` | met | |
| learn.truth.5 | TRUTH | Every other figure names where it comes from: `Refusal classes` is grouped by (guard, reason, command shape) over n protocol rows; `Oracle-held cells` names the policy and the oracle threshold; `Rows still needed` names the rule n ≥ min_n per cell; `Estimated spend` multiplies each cell's own mean row cost by the rows needed and reads a dash when no cell's cost is known, with the known-cost cell count as its n | `test:tests/test_learn.py::test_groups_by_reason_and_shape` · `test:tests/test_learn.py::test_unknown_cost_is_honest` · `test:tests/test_learn.py::test_cells_n_needed_cost_and_requests` · `test:tests/test_learn.py::test_policy_min_n` | met | |
| learn.actions.6 | ACTIONS | The page's writes are the three decisions and nothing else, each offered to an operator only: a viewer is shown no `Decide`, `Register` or `Queue runs` control, and the request a decision sends names an id and carries no `decided_by` | `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"offers a viewer none of the three decisions (they are operator acts at the API too)"` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a refusal verdict is a form, and its success state names the verdict, the decider and the file (G-532)"` · `code:ui/src/screens/Learn/LearnPage.tsx::LearnPage` | met | |
| learn.actions.7 | ACTIONS | While a report is deriving it says which report; a report that fails to load shows the server's reason with a Retry that refetches that report alone and leaves the other two rendered | `absent` | unmet | G-174 |
| learn.actions.8 | ACTIONS | The three hand-offs the About block tells the operator to make — decide a refusal class, register a strengthening item, queue the re-measurement runs the plan lists — are each one control on the report that computed them, and the one that spends money confirms the plan's own estimate before anything is sent | `hint:id:col.learn_refusals.decide` · `hint:id:col.learn_strengthen.register` · `hint:id:col.learn_remeasure.queue` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"queueing a re-measurement confirms the plan’s own estimate before anything is sent (G-532)"` · `code:ui/src/screens/Learn/LearnPage.tsx::QueueDialog` | met | |
| learn.explanation.9 | EXPLANATION | Every tile, column header, pill, link, action control, form field and nav entry on the route carries a registry hint (at least 26), the ratchet enforces the route for a viewer AND an operator and in both open dialogs, `stat.learn.refusal_share` opens its bubble on hover and closes on Escape, and `apparatus`, `stale`, `cell`, `oracle strength` and `negative controls` open their definitions inline | `hint:ratchet:/learn` · `hint:about:/learn` · `hint:id:stat.learn.refusal_share` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every element carries a resolved hint"` · `vitest:ui/src/help/hints-hover.instrument.test.tsx::"opens its bubble with the registry text"` | met | |
| learn.evidence.10 | EVIDENCE | Each derivation the page renders is pinned server-side: the refusal grouping and its denominator, the strengthening items against the served controls verdict and oracle scores, and the re-measurement plan's counts, cost and `POST /runs` bodies | `test:tests/test_learn.py::test_groups_by_reason_and_shape` · `test:tests/test_server_routes_learn.py::test_refusals_empty_then_one` · `test:tests/test_server_routes_learn.py::test_strengthen_uses_the_controls_verdict_and_the_oracle_scores` · `test:tests/test_learn.py::test_requests_are_valid_post_runs_bodies` | met | |
| learn.evidence.11 | EVIDENCE | A tier-1 spec renders the three reports on a running stack from real ledger rows and reads a row of each table; the route is captured for every persona at 375 and 1280 | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | partial | G-913 |
| learn.roles.12 | ROLES | Each of the three reads needs `viewer` at the API; an anonymous read is 401 and an unknown repository 404, so neither ever renders as an empty report | `test:tests/test_server_routes_learn.py::test_rbac` · `test:tests/test_server_routes_learn.py::test_unknown_repo_404` · `code:src/crb/server/routes/learn.py::learn_refusals` · `code:src/crb/server/routes/learn.py::learn_strengthen` | met | |
| learn.entry-exit.13 | ENTRY-EXIT | Every role the API admits can reach the page in the UI: the route is viewer-readable and the ratchet renders it as a viewer, so a viewer has a nav entry to it | `absent` | unmet | G-914 |
| learn.operations.14 | OPERATIONS | The three routes are listed in `docs/API.md` with their shapes and their role, and the operator guide has a section for the learning loop that says when to read the page and what to do with each report | `absent` | unmet | G-915 |
| learn.operations.15 | OPERATIONS | The guide the page links is bundled in the product and says what each report means, what the CLI twin is, and why each report stops at a person | `doc:docs/LEARNING-LOOP.md#4-using-it` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` · `hint:about:/learn` | met | |
| learn.accessibility.16 | ACCESSIBILITY | The route is axe-clean (WCAG 2.1 AA) with the three reports rendered, and renders for every persona at 375 and 1280 with the top bar no more than two rows and a hint bubble open | `spec:ui/e2e/walkthrough/11-screens.spec.ts::"every route renders, is captured, and carries About this screen"` | partial | G-916 |
| learn.explanation.18 | EXPLANATION | No element on the page explains itself only through a browser tooltip | `code:ui/src/screens/Learn/LearnPage.tsx::StrengthenSection` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"a strengthening item shows its description as text, not as a hover-only title (G-287)"` · `vitest:ui/src/help/hints-ratchet.test.tsx::"every title= sits in a file the allowlist names, within its count"` | met |  |
| learn.non-goals.17 | NON-GOALS | The page itself states that it decides nothing — the About block's last sentence and each report's intro name the person who decides, and a viewer's copy says the decision is an operator's — and the guide it links says why that is deliberate | `hint:about:/learn` · `doc:docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate` · `vitest:ui/src/screens/Learn/LearnPage.test.tsx::"offers a viewer none of the three decisions (they are operator acts at the API too)"` | met | |

## Gaps
- **G-172** — The no-repository body is a bare `Pick a repository` with no action (`LearnPage.tsx:398`), unlike Capability, Routing and Oracle, which link to `/connect` · give the `EmptyState` the same `Connection` action and assert it in `LearnPage.test.tsx` · ui
- **G-173** — No test pins what the refusal tiles render: neither the single-apparatus Wilson interval and n, nor the multi-version branch that must not show a blended headline rate (`LearnPage.tsx:243-252`); only the server's derivation is pinned · add a `LearnPage.test.tsx` case with a one-version and a two-version `by_apparatus` fixture asserting the value, n, interval and apparatus line of `stat.learn.refusal_share` · ui
- **G-174** — The per-report loading line (`Deriving …`) and the `ErrorState` Retry (`LearnPage.tsx:222,289,340`) are never rendered in a test, so nothing proves a failed report leaves the other two readable or that Retry refetches · add a `LearnPage.test.tsx` case with a 500 on `/learn/strengthen` only, asserting the other two cards still render and that Retry refetches that query · ui
- **G-913** — No spec renders any of the three reports on a running stack: `11-screens.spec.ts:130` visits `/learn` with no `?repo=`, so only the empty state is ever walked, and the single unit test uses all-empty fixtures · give the walkthrough a `/learn?repo=<primary>` visit that asserts one row of each table and the refusal tile's n and interval · ui
- **G-914** — The Instrument nav entry for `/learn` is `role: 'operator'` (`Layout.tsx:121`) although the three routes are viewer-gated and the hint ratchet renders the page as a viewer (`hints-ratchet.instrument.tsx:473-479`), so a governance reader with API access has no path to it · set the entry's role to `viewer`, as `/ledger` already is, and pin it in `Layout.test.tsx` · ui
- **G-915** — `docs/OPERATOR.md` never mentions the learning loop, so the platform team running the product has no runbook entry for the page or its reports (`docs/API.md` §Learn lists every route with its shape and role since the write paths landed) · add an OPERATOR section that says when to read each report and what to do with it · docs
- **G-916** — `/learn` is in no axe sweep: `07-settings-and-a11y.spec.ts` covers the journey screens, Capability, Ledger, Sign-off and Oracle, and the only visit to `/learn` renders the empty state · add `/learn?repo=<primary>` to the instrument axe test after the three tables are visible · ui
