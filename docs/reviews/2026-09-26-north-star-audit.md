<!--
Navigation
----------
What it is:   Section 6 of the north-star synthesis of 26 September 2026 — the stale or
              contradictory artefacts it found on the integration tree — vendored verbatim so
              the records that cite it resolve inside the repository.
What it does: Lists the 24 artefacts the synthesis found stale or contradictory on
              `origin/integration/next` at `81536f3`, each with what was wrong and the
              correction it asked for; Wave 0 of docs/dod/PLAN.md made those corrections.
How:          The synthesis was written for the operator and the agents of the north-star
              waves and kept outside the repository; its sources paragraph and its §6 are
              copied below byte for byte after this header and the note under it. Nothing in
              them is edited: where the tree has moved on, the definition of done says so.
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0013-external-review-is-advisory-and-recorded.md (a review is advisory
              and recorded)
Works with:   docs/PREVENTION.md (P-051 counts these rows), docs/DECISION-LOG.md (DL-063, the
              Wave 0 correction, and DL-071, which answers item 17), docs/dod/PLAN.md (Wave 0,
              the corrections), docs/reviews/2026-09-25-external-assessment.md (item 6 asked
              for it to be vendored the same way)
Tested by:    not applicable — a review record; scripts/claims_check.py reads it for an
              Actions table (it has none)
Touch when:   never to change its words; a finding it records is closed in the artefact that
              names it, with the evidence there.
-->

# The north-star synthesis of 26 September 2026 — §6, stale or contradictory artefacts

> **What this is.** Section 6 of the north-star synthesis the operator's agents wrote on
> 26 September 2026 to rank the open work, vendored verbatim with the paragraph that names
> its sources. The rest of the synthesis (what done is, the order of work, the waves) is
> carried by `docs/dod/GAP-ANALYSIS.md` and `docs/dod/PLAN.md`. `docs/PREVENTION.md` P-051
> counts the rows below, and `docs/DECISION-LOG.md` DL-071 answers item 17.

**Sources.** The integration tree, `origin/integration/next` at `81536f3`: `main` at #52 with the five open
pull requests #53 to #57 merged onto it. And `origin/main` at `64cdf46`. On both trees
`scripts/dod_check.py --check` passes ("gap analysis current"). Every count here comes from the checker's
own output, unless it is marked as a projection.

## 6. Stale or contradictory artefacts to correct first

Correct these in Wave 0, before anything is built on the order of work.

| # | Artefact | What is wrong | Correction |
|---|---|---|---|
| 1 | `product.md` evidence.6 · G-930; README status paragraph (lines 31 to 41); PLAN.md Wave 1 row E | Branch protection already requires 16 checks, including `dod`, `claims`, `ui-unit`, `ui-smoke`, `sandbox-images` and `sbom` (read through the protection API on 26 September). README still says ten, and names apparatus 2.2 while the tree is at 2.3 | flip evidence.6 to `met`; correct README and PLAN.md |
| 2 | `product.md` truth.203 · G-662 | says "land PR #55", but C1 and C3 are on the tree (ADR-0021, DL-059, the delivery and loop tests) | `partial`; the line reduced to C2 |
| 3 | `product.md` posture.204 · G-663 | says "land PR #53", but the refusal is on the tree (ADR-0023, `unsealed_prod_refusal`, `test_settings_posture.py`) | `partial`; the line reduced to the audit event |
| 4 | `product.md` evidence.205 · G-664 | says "land PR #51", but #51 is on `main` (the pins, hermeticity, a daily run) | `partial`; the line reduced to the lock file and the fresh-clone job |
| 5 | `product.md` truth.202 · G-661 | "posture labels arrive with PR #56" (merged); "lets deliver through when … controls … unmeasured" is false on the served path | cut to the distinct-task minimum, the unmeasured oracle, the sealed clause and `routing.v1` |
| 6 | `product.md` criteria 201 to 205 | cite "external assessment 2026-09-25 §F", which is not in `docs/reviews` | vendor it as `docs/reviews/2026-09-25-external-assessment.md` |
| 7 | `product.md` G-605 | a gap line no criterion cites, so it never reaches the gap analysis; it overlaps G-929 | cite it from claims.21, or fold it into G-929 |
| 8 | `product.md` purpose and G-600 | the purpose joins README's first sentence to a paraphrase; "the long-form account" is not in the repository, so no test can compare the three sentences | name the account (`docs/SUMMARY.md`, or the book vendored) |
| 9 | F42 and F43 in the gap analysis | both render as "[aspiration] Shippable-state gaps · XS–L", because they sit inside the F36 to F47 range row; F42 part 2 overlaps G-660 and neither says so | give each its own backlog row with its words |
| 10 | `docs/PREVENTION.md` P-008 · G-703 | pending, though #56's qualification is on the tree with tests that fail if the class recurs (product.posture.28 and .29) | close it, citing those tests |
| 11 | `docs/PREVENTION.md` | the docker-wait flake class (#49, #53; half-fixed by #59) has no row, and neither do the assessment's B5 and A5(c) defects | register them |
| 12 | `docs/dod/PLAN.md` | contradicts STANDARD §6: G-653 (rank 1) and G-660 to G-664 are in no wave; Wave 0 still says "#46 in CI"; Wave 3 R names G-920 but describes G-914; Wave 3 U2 names B-9, which no criterion cites (the work is G-368); its Wave 2 items rank below its Wave 3 items (G-925, in Wave 3, is rank 3) | rewrite to section 5 |
| 13 | The integration tree | `770adbb` changes sign-off records and refusals and names no criterion; it and three more commits are in no pull request | carry them to `main` with a criterion (Wave 0, stream K) |
| 14 | Orphan gap lines | G-931 (intake), G-940 and G-941 (measure journey), G-942 (prove), G-943 (results), G-944 (repos-name) are defined but cited by no criterion; G-905 is defined in 6 files where no criterion cites it | delete them, and make the checker refuse an orphan |
| 15 | One change under several ids | section 3.3; STANDARD §2 says one id, one identical line | one id per change, in the G-900 band |
| 16 | `streams/learn.md` roles.7 against `pages/learn.md` and `journeys/learn-and-strengthen.md` (G-914), and `/oracle` (G-919) | the stream calls the operator-only nav entry correct; the page and journey call it a defect | decide once. The API already lets a viewer read both pages, so `viewer` is the consistent choice; then change roles.7's evidence |
| 17 | Non-goals that contradict gaps | `pages/learn.md`: "the three reports never write" against G-532; `pages/factory.md` and G-140: "never imported from a ticket system" against `factory-intake` (done; ADR-0022); `pages/login.md`: no About block against G-926; `decisions.md`, `factory.md`, `connect-name-measure.md` and `settings.md` list as non-goals the F6, F5b and F23 work the gap analysis asks for | a non-goal exists "so the gap analysis never asks for it" (STANDARD §2), so each pair contradicts itself. Recommended call: keep the gap where a stream or journey names it, and rewrite the non-goal; "not yet" is a gap, not a non-goal |
| 18 | `pages/results.md` non-goals.14 (met) | rests on "the ledger records neither human hours nor merge outcomes"; merge outcomes are recorded (`sync_outcomes`, `delivery.merged`, `delivery.closed`) | correct the copy and the criterion |
| 19 | Criteria written as the defect, not the done condition | run-the-platform purpose.1, explanation.5, automation.15; decide-and-license automation.15; measure automation.15. Marking them `met` would read backwards | rewrite each as the observable done state |
| 20 | Gap lines overtaken by merged work | G-548 (Factory now links intake, which shows listening or not configured); G-500 (#56's qualification fix sentences and `qualify_first`; connect-and-prove never mentions qualification); G-480 (`crb.signoff.v4` carries the posture class; only the gate row is missing); G-431 and G-352 (ADR-0019's `qualify` run kind and button are not mentioned) | cut each line to what remains |
| 21 | Backlog row F23 | still says "no route sets it, so a leaver keeps a working login"; the API and host halves shipped in #42 | say what remains: the Settings screen |
| 22 | Operating guides against the code | G-403 asks DEPLOYMENT §9.3 for "eight probes", but `/health` serves the ten probes API.md lists plus `provision`, which API.md omits; DEPLOYMENT §9.3 says seven and claims Home raises a banner for the worker probe (only the sandbox probe does, G-397); G-141 and G-364 propose an "OPERATOR §10" that is now the test author's section | correct the guides and both gap lines |
| 23 | Home task 7 | deploy-and-go-live treats "task 7 Completed" as its exit; sign-off-a-cell truth.3 (G-477) says that reading is untrue with only the bootstrap admin; `pages/home.md` has no criterion for it | add the TRUTH criterion to `home.md` under G-477 |
| 24 | Small drift | `pages/posture.md` says 22 rows, G-214 says 21, and a unit test says four groups for five; G-465 names spec `12-…`, already taken by `12-intake.spec.ts`; `Layout.tsx` line numbers in G-914, G-919 and four entry and exit paragraphs; `updated:` dates of 22 September on artefacts #56 and #57 changed; streams cite none of ADR-0019, 0021, 0022 or 0023, and ADR-0019 calls ADR-0018 "pending in wave 2" (it is on `feat/w2-s`) | correct in the same pull request |
