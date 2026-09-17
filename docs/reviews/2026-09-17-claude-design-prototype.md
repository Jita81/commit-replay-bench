# The Claude Design prototype against the journey shell — assessment (2026-09-17)

<!--
Navigation
----------
What it is:   The operator's Claude Design prototype ("crb Front End", twelve NHS/GOV.UK-
              patterned screens built from the enterprise front-end brief) read against the
              front end as it stood after PR #30, with a verdict per screen: what the
              prototype does better, what ours does better, and what the prototype claims
              that the product does not yet do.
What it does: Records the design decision (DL-042: adopt the NHS design system and the
              prototype's screen grammar; keep our data binding, RBAC and API-derived
              state), what PR #32 implemented, and what stays on the backlog with its
              F-number in docs/reviews/2026-09-17-enterprise-front-end.md §9.
How:          The prototype was read from the design project (`crb Front End.dc.html`,
              `support.js`, `github.md`); its copy and numbers are illustrative and were not
              treated as measurements.
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   docs/DECISION-LOG.md (DL-042), docs/reviews/2026-09-17-enterprise-front-end.md
              (the backlog it updates), ui/src/components/govuk.tsx (the patterns),
              ui/src/screens/Home/HomePage.tsx, ui/src/screens/Connect/MeasurePage.tsx,
              ui/src/screens/Results/MapTable.tsx, ui/src/screens/Decisions/DecisionsPage.tsx,
              ui/src/screens/Posture/PosturePage.tsx, src/crb/core/signoff.py (the staleness
              rule the prototype exposed)
Tested by:    not applicable — a review record
Touch when:   a backlog row below lands.
-->

## Verdict

The prototype is the better *language*; ours is the better *machine*. The prototype speaks
the NHS/GOV.UK service grammar a public-sector reader already knows — task list, summary
list, "Important" banner, warning callout, inset text, confirmation with a reference,
solid route tags — and it puts governance facts where the eye already is. Ours derives
every status from the API, enforces roles, tests the contract, and never fabricates a
number. The right product is the prototype's grammar on our data: that is what PR #32
built (DL-042).

The prototype also exposed **two product gaps** by drawing them as if they existed:

1. **A sign-off made on an earlier apparatus still lifted the cell.** EVIDENCE-AND-CLAIMS
   §4 says evidence expires when the apparatus changes; `apply_signoffs` checked false-Q1
   at read but not the apparatus. Fixed in PR #32: a record stamped at 2.1 is *stale* at
   2.2 — kept on the record, served with `stale: true`, lifting nothing, listed in the
   Decisions inbox as "Signed cells now stale" to re-sign or revoke.
2. **Separation of duties is not enforced at write.** The prototype's home page says
   "Sign-off is refused at write if the same person does both". It is not: an operator who
   queued the run may hold the approver role and sign. The UI now states the policy
   honestly ("keeping operator and approver on two people is the deployment's policy")
   rather than claim enforcement; enforcement is backlog **F7b** below.

## Screen by screen

| Prototype screen | Better in the prototype | Better in ours | Done in #32 | Backlog |
|---|---|---|---|---|
| A1 Get started | Seven tasks with statuses, "completed n of 7", the cost sentence ("tasks 1 to 4 cost nothing"), "Why two people", the degraded sandbox as an *Important* banner | Statuses derived from the API (`stagesFor`), never kept; task 7 knows whether an approver exists | **Home** (`/home`), all of it, on real state | — |
| A2 Connect GitHub | Permissions with *why* per scope; "what is not requested" (write is a later, approver-confirmed step); "what leaves the tenant"; "why not a PAT" | The picker works (installations, search, suggested config, connected-as); the app really mints tokens | — | **F9** connection review page with the explanatory panels |
| A3 Choose a repository | Filter panel; language / tests / last commit / status columns; "No approver" as a status | Reads GitHub live; marks connected repositories; refuses a second connect | — | **F3** shape detection from the tree (test framework, last commit) |
| A4 Confirm its shape | A *summary list* per config key with a **risk sentence** ("wrong prefix: the belts cannot tell a fix from a test edit"); belt-scope explanation | The full config form with runner-specific options and validation | — | **F3b** review page with risk copy before the probe |
| A5 Prove the instrument | The three £0 steps as one task, "nothing is evidence until the third passes", the green "Controls passed · 0 escapes" panel | The six-stage walk already sequences them and watches the runs | partly (the Home task and copy) | **F4** group the three stages visually with the green panel |
| A6 Measure | Attempt radios with meaning; retention with the policy statement; "Before you start" (cost range, cap, retention, posture); red button naming the spend | The full run form for every knob | **Measure** (`/connect/:name/measure`), the estimate from the repository's own measured cost | — |
| A7 Capability map | "Is this evidence?" strip; the class × size **table** with route tags and per-cell **signed / due / stale**; "what this licenses you to say"; economics; "no throughput headline" | The strip and the decisions panel existed; the grid with drill-down remains under *Map grid* | **MapTable** + licence sentence + economics + callout on Results | — |
| B7 Decision inbox | Same kinds (lifted from our `decisions.ts`); **stale signed cells** section; the nav badge; role-filtered verbs | Cross-repository; the derivation is tested | stale section, badge, NHS grammar | — |
| Sign-off check-your-answers | Every clause as observed vs threshold with "no deployment knob"; the accepted-row picker; **"what your signature does not mean"**; the button names the cell and route | The clauses are the server's real refusal set; the preview is live | the callout; the confirmation | **F7** clause table as a summary list with the "no knob" marker |
| Sign-off confirmation | The green panel with a reference, the summary, "what happens next" | — | **ConfirmationPanel** after a recorded sign-off | — |
| B6 Rollup by team | Ownership from GitHub teams / CODEOWNERS; approver group per team; sums of signed cells, never averages | (nothing — teams do not exist in the product) | — | **F11 / F12** |
| B9 Factory process | Eight stages (adds freeze, route gate, PR opened, bounded rework); a per-item **timeline** from the evidence chain | Six steps per item with the acts in place (sign a gap, freeze, run) | — | **F15** eight stages + timeline from `/factory/{repo}/evidence` |
| B1 Deployment posture | Four summary lists for a review board, printable | — | **Posture** (`/posture`) from `/version`, `/health`, `/settings`, `/ledger/verify` | **F18** SIEM row when audit export exists |
| Stop-condition banner | Full-width red, "no policy setting can override this" | — | on every screen from the ledger health probe | — |

## What the prototype claims that is not so (not implemented as drawn)

- "Separation of duties — enforced at write" → not enforced; **F7b**.
- "Pull requests: read — to read review verdicts and merge outcomes" → merge outcomes are
  not recorded (B-9); the permission table in docs/GITHUB-APP.md is the truth.
- "Budget cap £25 — the run stops itself" → caps are per attempt on the ladder (turns, tool
  calls, wall clock, tokens, cost); a per-run spend cap is **F5b**.
- "Posture: sealed (docker) — countable as evidence; host posture refused for evidence
  runs" → host posture is a stated caveat today, not a refusal; making the sealed posture a
  sign-off clause is B-1's campaign plus a policy change.
- "belts v4" → v5 since apparatus 2.2. Currency: the prototype uses £; the ledger records
  USD; the UI shows `$` with the ledger's numbers.

## Backlog changes (docs/reviews/2026-09-17-enterprise-front-end.md §9)

Added: **F3b** shape review with risk copy (S); **F5b** per-run spend cap (M, API); **F7b**
separation of duties at write — refuse a sign-off whose approver is the actor of every
accepted row it names, or of the run that produced them (M, core + API); **F16 is now in
progress** — the NHS palette, Arial and the GOV.UK patterns landed; the explore screens
still use the old component set and migrate screen by screen.
