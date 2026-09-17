# Persona walkthrough on the live stack — 2026-09-17

**Question asked:** from every perspective the enterprise front-end brief named, does each
person get the right experience, and does it work?

**Method.** One live deployment (`crb 2.0.0a1`, apparatus 2.2, `feat/nhs-design-journey`,
local executor — a *development* posture, so nothing measured here is evidence). Four local
accounts were created for the walk: `vera-viewer` (viewer), `oli-operator` (operator),
`ada-approver` (approver) and the bootstrap admin. Every screen was driven in a real
browser, then swept with axe (WCAG 2.1 AA) as three of the four personas and checked at a
375 px viewport. The MCP server was driven over stdio as the viewer. One real replay run was
started by the operator through the Measure page (cobra, 10 sighted attempts,
`claude_code / claude-sonnet-5`, `auth: cli`) so the walk crossed a run in flight and a run
completing. One real sign-off was made and then revoked so the dev ledger records it as a
test.

The defects found were fixed in the same branch as they were found; the table says what
each person saw before and after. Every behavioural fix (1–12) carries a test; the two
layout-only fixes (13, 14 — a wrapping title and a wrapping hash) do not.

## Verdict per persona

| Persona | Journey | Worked before? | After |
|---|---|---|---|
| **Operator** (tech lead trying it in an afternoon) | Home → Connection walk → Measure → run in flight → Results | **No** — Measure posted no builder (422); the walk said *Done* while the replay ran | Yes. Builder derived from the health probe; *In progress* while running; estimate ≈$2.84, actual $2.57 |
| **Approver** (signs a cell) | Decisions → Sign-off with `?cell=` → read the diff → affirm → sign → confirmation → map shows *signed* → Decisions drops the row → revoke | **Partly** — the form asked "I have read this accepted diff" without showing any diff; the signer was named by user id; revoke was one click, no reason, and the row vanished | Yes. The retained patch is on the form; names resolved at read; revoke confirms with a required reason recorded on the ledger; history stays listed |
| **Viewer / sponsor / auditor** | Home → Results → Decisions → Deployment → Ledger → Settings | **Partly** — Home was an operator's to-do list ("Get started", "Measure — spends money"); read-only otherwise held (0 buttons, 0 inputs on Settings; no secret anywhere) | Yes. "Where this deployment is", the operators' progress, *Continue* to the map |
| **Admin / AppSec / ARB** | Settings (users, secrets, GitHub App) → Deployment posture | **Partly** — Users table's Username column was blank (API `subject`, UI `username`); posture said *Sign-in: shown to admins* to everyone else | Yes. `username` served; `/version.oidc_enabled` feeds the posture row and the login page |
| **Developer** | Factory: freeze a backlog → item chain; Runs → evidence pack of a failed row | **Partly** — a never-built item read *failed* and an unassessed one *done* (API `not_built` vs UI `not_started`); the evidence drawer was already exact (belt 5: "gofmt rejected 2 changed file(s)") | Yes |
| **Platform engineer** | Connect from GitHub with no app configured | Yes — clear "not configured" state with the admin's instruction and a URL fallback; the footer carried a disabled *Connect* and a duplicate link | Yes, footer trimmed |
| **MCP consumer** (an assistant reading the deployment) | `crb mcp` over stdio as the viewer: `crb_whoami`, `crb_repos`, `crb_capability_map`, `crb_signoffs`, `crb_ledger_verify`, `crb_refusals`; then `crb_start_run` | Yes — 38 tools; every read answered from the ledger; `crb_start_run` refused with the 403 envelope (`role 'operator' required`) | — |
| **Everyone, on a phone** | Home, Results, Sign-off, Decisions, Deployment at 375 px | Yes — no horizontal overflow on any screen; the nav wraps to three rows | — |
| **Everyone, with assistive tech** | axe WCAG 2.1 AA on nine journey screens × three personas | **No** — two serious findings: the *See the health check* link in the Important banner had no non-colour distinction; the red pill ink on its soft fill was 4.4:1 | 27/27 clean. Links in prose underline; the red soft fill is lightened to 4.7:1 |
| **Sign-in** | `/login` | **No** — offered *Sign in with organisation account* when no provider was configured (it would 404) | Button only when `/version` says `oidc_enabled` |

## What the instrument did while we watched

The operator's run (`6fb61af9…`; cobra, replay, sighted, `claude_code / claude-sonnet-5`
with `auth: cli`, apparatus 2.2) finished during the walk: 10 tasks, 9 clean, 1 not clean
(the lint belt — gofmt), 0 disqualified, 0 harness errors, $2.57 builder-reported
**[measured — the run's ledger rows, read on `/runs/{id}`]**. Between the start and the end
of the walk `bug.fix × S` on cobra crossed the bar — 23 of 24 clean, 95.8 % (95 % Wilson
[79.8 %, 99.3 %]), route *calibrate* (`ci_low_below_bar`: the lower bound sat under the
80 % bar) → 24 of 25 clean, 96.0 % (95 % Wilson [80.5 %, 99.3 %]), route *deliver* under
`routing.v1` **[measured — `/capability-map?repo=cobra`, current apparatus 2.2, sighted
rows, `claude_code / claude-sonnet-5`; the intervals are the API's `wilson_interval`]**;
the Decisions inbox picked it up
without anyone reloading anything, and showed the viewer *approver acts* next to it. The
badge is honest by role: the approver saw 1 waiting before the sign-off and the viewer saw 3
after the revoke (two cobra cells due, one click cell routed to a human).

## Defects fixed in this walk

| # | Severity | Persona | Defect | Fix | Test |
|---|---|---|---|---|---|
| 1 | High | operator | Measure page `POST /runs` → 422 "kind 'replay' needs a builder" | `builderChoice()` from the health builders probe (`anthropic` → production; `claude_code_cli` → `auth: cli`, labelled development-only; none → button disabled) | `MeasurePage.test.tsx` |
| 2 | High | operator | Connection walk said *Done* for mine/measure while a run was active | running outranks done (`connection.ts`) | `connection.test.ts` |
| 3 | High | approver | Sign-off form asked for the affirmation with no diff to read | `ReadTheDiff` under the picked row: the evidence pack, the retained patch, links to the task and the run; honest fallback when the patch was not retained | `SignoffPage.test.tsx` |
| 4 | Medium | approver, auditor, viewer | Signer shown as a user id (confirmation, attestations table, Decisions, **the licence sentence**) | API resolves `approver_name` / `revoked_by_name` at read; the ledger keeps the id; `approverName()` in the UI | `test_server_routes_signoffs.py`, UI tests |
| 5 | Medium | approver, auditor | Revoke was one click, no confirmation, no reason; revoked rows disappeared ("No attestations yet") | Confirmation panel with a required reason sent as the revocation `note`; `include_revoked=true` on the sign-off page | `SignoffPage.test.tsx` |
| 6 | Medium | viewer | Home was an operator's task list for everyone | Role-aware: *Where this deployment is*, "the operators have completed n of 7", *Continue* to the map | `HomePage.test.tsx` |
| 7 | Medium | operator | Home called a measurement in flight *Incomplete* and the map *Cannot start yet* with 60 rows on it; task 7 sent non-admins to `/settings` | *In progress* linking to the walk; map from the first row; task 7 → `/posture` unless admin | `HomePage.test.tsx` |
| 8 | Medium | anyone signing in | Organisation sign-in button shown with no provider | `/version.oidc_enabled`; button conditional; posture row reads it for every role | `test_server_app.py`, `smoke.spec.ts` |
| 9 | Medium | admin | Users table Username column blank | `/users` serves `username` (subject without `local:`) | `test_server_app.py` |
| 10 | Medium | developer | Factory item never built → *failed*; never assessed → *done* | `stepsFor` recognises `not_built` and an empty route hint | `FactoryPage.test.tsx` |
| 11 | Serious (WCAG) | everyone | Link in the Important banner distinguishable by colour only; red pill ink 4.4:1 | prose links underline; `--fail-soft` #FDF5F4 (4.7:1) | live axe sweep; walkthrough spec 07 extended |
| 12 | Low | platform | GitHub dialog footer: disabled *Connect* + duplicate URL link when not configured | footer is *Cancel* only | Connect tests |
| 13 | Low | developer | Factory step titles truncated at card width | titles wrap | — |
| 14 | Low | approver | Row hash overflowed the confirmation column | `break-all` | — |

## Findings not fixed here (backlog)

| ID | Item | Persona | Why | Effort |
|---|---|---|---|---|
| **F23** | **User lifecycle**: deactivate a user, reset a local password, show `active` / `last_login` in the Users table. The model has `active`; the API has no route to set it, so a leaver keeps a working login until an admin edits the database | admin / AppSec | JML is the first question an NHS IG review asks | S |
| **F24** | Factory backlog freeze is a raw-JSON textarea (the prefilled example is content, not a placeholder — typing appends). A form (id, title, class, size, facts) with the JSON as an "advanced" tab | developer | the first factory action should not need the API doc open | M |
| **F25** | `GET /settings/secrets` returns `set_by` and the token fingerprint to viewers (presence-only by design; the metadata is more than presence) | AppSec | low; narrow the viewer projection to `present: bool` | S |
| **F26** | Phone header: the three nav rows take half the first screen; a collapsible menu under 640 px | everyone on a phone | usable now, not pleasant | S |
| **F7b** (existing) | Separation of duties at write — the operator who queued the run can also be the approver who signs it; the posture page says so honestly | approver, ARB | already on the backlog; this walk confirms it is the biggest governance gap left | M |

## What is honest about the dev ledger after this walk

- One test sign-off (`sgn_9e5e373eb4`, `bug.fix × XS` on cobra) was recorded and then revoked
  with the reason *evidence re-examined* — both rows are on the chain; the attestation
  statement itself begins "TEST ATTESTATION (persona walkthrough 2026-09-17, will be
  revoked)".
- One test backlog (`T-1 walkthrough test item`, hash `1644eba4…`) is frozen on cobra; the
  factory was not run on it.
- Ledger after the walk: 602 rows, chain intact, false-Q1 0, 0 clean rows without a pack
  **[measured — `/ledger/verify`, apparatus 2.2; exact counts, no interval]**.
- The two WCAG figures (4.4:1 before, 4.7:1 after) are contrast ratios computed from the
  tokens, not sampled rates: no `n`, no interval.

## How to repeat it

```bash
# API + UI gates
.venv/bin/ruff check src tests && .venv/bin/mypy src && .venv/bin/python scripts/code_map.py --check
.venv/bin/python -m pytest tests/test_server_routes_signoffs.py tests/test_server_app.py -q
cd ui && npm run typecheck && npx vitest run
# the live walkthrough (boots its own stack) — spec 07 now sweeps the journey screens with axe
cd ui && npm run walkthrough
```
