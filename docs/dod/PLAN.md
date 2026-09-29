<!--
Navigation
----------
What it is:   The plan — the order of work in GAP-ANALYSIS.md batched into waves (Wave 0 to
              Wave 5, the acts only the operator can do, and what comes after Wave 4).
What it does: Says which gaps travel together, on which branch, and what "done" looks like when
              each wave lands; every wave item is a gap id the record defines, and
              scripts/dod_check.py refuses one that is not.
How:          One table per wave; its `gaps` column holds gap ids and nothing else (the checker
              reads it); the other columns say what ships and why. Ids a wave closes stay
              valid here because the generator lists them under "Gap ids retired" once the
              artefacts' git history shows they were gaps; every gap the order of work ranks
              must sit in some table here, and no heading quotes a rank (P-189).
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (Waves 2 to 5 build it; DL-086,
              DL-087); DL-063 records the rule the checker enforces on this file
Works with:   docs/dod/GAP-ANALYSIS.md (the order of work this batches), docs/dod/STANDARD.md
              (§6: the next feature is the top of the gap analysis), scripts/dod_check.py
              (refuses a wave item that is not a gap id), docs/PREVENTION.md (P-118, the class
              this rule closes), docs/reviews/2026-09-25-external-assessment.md (the source of
              the "trustworthy when" criteria Wave 2 closes)
Tested by:    tests/test_dod_check.py::test_a_plan_wave_item_must_be_a_gap_id_and_closing_it_keeps_the_plan_valid,
              ::test_a_gap_at_the_top_of_the_order_of_work_must_be_in_a_wave,
              ::test_every_open_gap_is_in_the_plan_not_only_the_top,
              ::test_a_plan_heading_never_quotes_a_rank,
              ::test_a_retired_id_must_have_been_a_gap_in_the_artefacts_history
Touch when:   a wave lands (say so and move to the next), a gap is opened that belongs in a
              wave, or the order of work changes which gap is first.
-->

# The plan — the north-star waves, each closing named gaps

`GAP-ANALYSIS.md` is the order of work; this file is the batching: which gaps travel together,
on which branch, and what "done" looks like when the wave lands. It follows the north-star
synthesis of 26 September 2026, which ranked the open work on the integration tree
(`origin/integration/next` at `81536f3`: `main` with pull requests #52 to #57 merged onto it).

**The rule.** Nothing enters a wave that is not a gap id the record defines. If something must
be built that no artefact names, the artefact is wrong: add the criterion and its gap first,
then plan it. `scripts/dod_check.py` holds this file to the rule: every cell of a table's
`gaps` column is a list of gap ids and nothing else, and each is a gap an artefact or the
prevention register defines, a backlog row a criterion cites, or one the order of work has
retired (closed or merged). An id is retired only when the artefacts' git history, or the base
branch's committed gap analysis, shows it was a gap, so editing the generated file cannot
admit one. A wave that closes a gap never breaks this plan; a typo does. Every gap the order
of work ranks must also sit in some table here — a wave, or the list after the waves — and no
heading quotes a rank: the order of work is `GAP-ANALYSIS.md`, and a rank copied here reads
false as soon as the order moves (P-189). The check reads ids, not meaning, so a reviewer
still reads each row against the lines its ids carry.

**How every wave works.** One pull request per stream, merged onto one branch, attacked by
adversarial verifiers, then merged to `main` by the operator. Each pull request flips the
criteria it closes to `met` with evidence that resolves and would fail if the behaviour
regressed, narrows a gap it only half closes, and regenerates `GAP-ANALYSIS.md`. Streams own
their files; the shared registries (`hints.ts`, `help.ts`, `types.ts`, `API.md`,
`CHANGELOG.md`, `CODE-MAP.md`, `docs/dod/**`) are additive and resolved once, at the merge.

**Integrated.** Wave 0 (`feat/ns1-d`) and Wave 1 (`feat/ns1-m`, `feat/ns1-l`, `feat/ns1-u`,
`feat/ns1-e`, `feat/ns1-a1` and `feat/ns1-a2`) are merged onto one branch, `feat/ns1`, cut
from the integration tree, with every stream's ids renumbered to follow the base in merge
order. It awaits the operator's merge. The gaps the streams opened are placed in Wave 2, Wave 4
or the list after Wave 4 below, and the checker now refuses a ranked gap in no table (P-189).
Wave 2's streams (T, then C, I, H, X, F, and R on G) are integrated on
`feat/ns2`, cut from `feat/ns1` at `1240f6bf` and brought to its later head, `46f87156` (the
PR #63 review fixes), by a merge on 28 September; Wave 2's own prevention rows moved up by
eight, after `feat/ns1`'s `P-227` to `P-234` (P-334), their other ids renumbered after
`feat/ns1`'s in merge order and their seams wired (the entry gate reads the registered readings through one
binding, `crb.server.factory_standard`); it awaits the operator's merge after `feat/ns1`. Wave
4's streams (T4, P, S, then L with M) are integrated on `feat/ns4`, cut from `feat/ns2` and
brought to its later head, `8ba71fda`, by a merge on 28 September, with their ids renumbered after
Wave 2's (DL-106 to DL-120, P-350 to P-403, ADR-0031, Alembic revisions 0014 to 0016) and their
seams wired; what it closed and what it left are under Wave 4 below. It awaits the operator's
merge after `feat/ns2`. Wave 3 and Wave 5 need the operator and have not started.

Some ids the base carried are retired on this branch because they were **merged or narrowed,
not closed**: the criteria that cited them are still open under the id that replaced them.
Merged: G-100, G-252 and G-445 into G-977; G-116 and G-220 into G-979; G-118 into G-907;
G-141 and G-364 into G-978; G-261, G-381 and G-398 into G-976. Narrowed: G-905 into G-992
(`factory.accessibility.18`) and G-993 (`signoff.accessibility.14`), its other three
criteria met; G-925 into G-556 (`connect-and-prove.measure.14`) and G-584
(`run-the-platform.measure.14`), its other three criteria met.

## Wave 0 — correct the record (autonomous; integrated on `feat/ns1`)

| stream | gaps | what ships |
|---|---|---|
| D0 · the artefacts | G-930, G-661, G-662, G-663, G-664, G-703, G-403, G-480, G-500, G-548, G-907, G-976, G-977, G-978, G-979 | `product.evidence.6` kept `partial` on G-930, cut to what remains: `scripts/check_branch_protection.py` compares the required-check list with ci.yml's jobs, and a daily workflow runs it once the operator provisions its token; criteria 202 to 205 `partial`, citing what landed, each gap line cut to what remains; P-008 closed with #56's tests; the external assessment vendored as `docs/reviews/2026-09-25-external-assessment.md`; F42 and F43 given their own backlog rows and F5b re-scoped against the assessment's C8; the orphan gap lines (G-931, G-940 to G-944, the stray copies of G-905) deleted and G-605 folded into G-929; each duplicated change that no other stream owns carried by one id; the non-goals that contradicted a gap rewritten; the Results throughput copy, README's status paragraph and the `/health` probe list in the guides corrected; this plan rewritten |
| D0 · registered, not yet closed | G-970, G-971, G-972 | the docker-wait flake class, the five executor and mining defects (the assessment's B5) and the append-only probe (A5(c)) registered in `docs/PREVENTION.md`, each pending with its gap |
| D0 · the integration's own links | G-997 | the changelog entries of this integration link GitHub's create-a-pull-request form (`pull/new/feat/ns1`), which never becomes the pull request's page; they are replaced with `pull/<n>` when the operator opens it, and the changelog test then refuses a create-form link |
| D0 · the criteria Wave 2 needs | G-973, G-974, G-975 | the criteria the assessment's A3 (`lint_status`), A6 (`mutation.v2`) and C4 (the delivered change's own cell) need before Wave 2 may build them, added `unmet` |

D1, the checker, closes in the same change the register rows that name it (P-118, "the record
drifts from the order of work", and P-127, "the generated file vouches for itself"), so it
carries no gap id: `dod_check.py` refuses a gap line no criterion cites, a wave item here that
is not a gap id, and a gap among the first 25 of the order of work that no wave names; and it
keeps a closed gap nameable only while the history vouches for it (DL-063, DL-064).

Outside the waves, and not DoD work: carrying the four commits that exist only on the
integration tree (`770adbb`, `79f4597`, `27f2171`, `8d15f12`) to `main` in one pull request
after #57 lands. Their criterion is on the record already: `sign-off-a-cell.truth.22`, met
(a sign-off lifts only a cell read in the posture class its evidence was graded in) **[hypothesis — true when the plan was written; not re-checked since]**.

**Done when:** `dod_check.py --check` passes with its new refusals; `GAP-ANALYSIS.md` shows
`product.evidence.6` partial on G-930 alone (the operator's token), criteria 202 to 205
partial, P-008 closed and no orphan gap line; every wave item here is a gap id.

## Wave 1 — finish what was built (autonomous; integrated on `feat/ns1`)

The gaps the north-star synthesis ranked 3 to 20 on `81536f3`, plus the smaller gaps on the
same screens that finish an artefact.
Five of these streams restart work parked on 25 September (`feat/w2-m`, `feat/w2-l`,
`feat/w2-u`, `feat/w3-e`, `feat/w3-a`).

| stream · branch | gaps | what ships |
|---|---|---|
| M · flow · `feat/ns1-m` | G-925 | `GET /flow`; each stream's screen shows its lead time, spend and counts with n; what nothing records yet (developer hours, reviewer minutes, the install-to-green reading) becomes narrower gaps of its own |
| L · Learn · `feat/ns1-l` | G-532, G-912, G-172, G-173, G-174, G-175, G-176, G-913, G-533, G-916, G-348, G-349, G-350, G-351, G-352, G-431, G-432 | the three write paths behind the named-person decision; Decide, Register and Queue beside each report; hand-offs into `/factory` and `/runs` filled in; links into Learn from the screens that reveal the need; a Learn walkthrough with axe |
| U · accounts · `feat/ns1-u` | F23, G-460, G-461, G-462, G-922, G-463, G-464, G-465, G-466, G-467, G-923, G-276, G-277, G-188, G-412, G-189, G-927, G-190, G-191 | Settings › Users with history; change my password; `/login` says who can reset a password; a sign-in failure returns to `/login` with its reason; a 429 names the wait; `user.login` events; a recovery walkthrough, timed |
| E · economics · `feat/ns1-e` | F35 | known-n counts and a t interval per cell; tiles show n, the interval and the apparatus; an unknown value is a dash |
| A1 · keyboard, phone and nav · `feat/ns1-a1` | G-905, F26, G-192, G-196, G-197, G-292, G-914, G-919, G-448, G-301 | the five keyboard steps; the phone menu under 640 px; `/login` swept before sign-in; nav entries at `viewer`; the `/repos` journey eyebrow |
| A2 · wayfinding and help · `feat/ns1-a2` | G-926, G-911, G-164, G-165, G-166, G-148, G-149, G-150, G-156, G-157, G-413, G-414 | the shell screens' About blocks; the approver's Home; Home shows its failed reads; the help pages' gaps; the orient walkthrough, timed |
| B · evidence and import (the security and governance review, EI-2, EI-3, EI-6) · `fix/audit-b` | G-755, G-756, G-757, G-758, G-759 | imported rows stamped inside their hash and audited, never counted by a sign-off or the route that licenses delivery; no attestation of an imported or pack-less row; the worker never appends a clean row without its kept pack; the sign-off and review chains verified by `/ledger/verify`, `GET /signoffs/verify` and `/health` |
| A · the security review's auth findings · `fix/audit-a` | G-750, G-751, G-752, G-753, G-754 | the operator's internal security and governance review (2026-09-27): the login limiter reserves an attempt before it checks the password, so a burst cannot outrun it (AUTH-1); the identity provider's claims never demote the last active admin (AUTH-2); deactivation ends an account's sessions for good (AUTH-3); every credential change and every sign-out is an event naming who made it (EI-8); the re-check's two residuals — the last-admin count takes only admins who can sign in, and a finished Claude sign-in is recorded with its own time though nobody reads it back (G-754) |

**Done when:** on the merged branch, `GAP-ANALYSIS.md` no longer lists G-532, G-912, F23, F35,
G-905, G-911, G-919 or F26, and G-925 is replaced by narrower gaps for what nothing records;
the tier-1 walkthrough passes with specs in which an admin resets a colleague's password and
the colleague signs in again, and an operator accepts a refusal line on `/learn` and reads what
it did.

## Wave 2 — trustworthy when, and the context standard (autonomous; integrated on `feat/ns2`)

The external assessment's conditions for trust, all but the measured README section, which is
Wave 3's; spend under control; and the operator's thesis of 26 September 2026 made buildable
(ADR-0026): a context arm and a class-set version on every row, registered readings under the
look rule, the leak guard and the entry gate. **T, the thesis record, lands first** and is docs
only: ADR-0026, DL-086 and DL-087, the criteria and gaps the thesis needs, the corrected
specification-lever record and this plan. It closes no gap, so it has no row. Every other stream
branches from T's head. R builds on G's branch, because it owns the one apparatus bump that G's
`lint_status`, `failure_kind` and `mutation.v2` ride; F owns `worker.py`, the factory and the
brief composer for the wave.

On this branch the order of work puts G-477 (Home's task 7 reads Completed with only the
bootstrap admin) first among the gaps nobody but us can close **[measured — n = 1 gap; method: `GAP-ANALYSIS.md`'s order of work as `scripts/dod_check.py` generated it on `feat/ns1`; apparatus n/a, a property of the product's own code, not a graded row]**, so it moves here from Wave 4
(STANDARD §6); it restarts from the parked `feat/w2-s`, whose readiness rule it is, and the rest
of that stream stays in Wave 4.

| stream | gaps | what ships |
|---|---|---|
| C · claims | G-929, G-660, G-674, G-994, G-996, G-995, G-998 | the claims allowlist widened page by page, `docs/dod/**` included; the rows locator and the re-derivation test, ready for Wave 3's rows; the ISO/IEC 25010 characteristic-to-check table and the rule that refuses a conformity claim; **not built on `feat/ns2`, carried forward:** a scheduled mutation pass that proves the evidence of a met criterion or a closed prevention row can fail, and a check that a criterion flipped to met kept its words; one owner per shared defect class in a wave, so parallel streams stop fixing one class several ways; a `[measured]` tag whose method names a source the repository does not carry is refused |
| I · audit | G-663, F51, G-601, G-924, G-972, G-709 | an audit event naming who set the unsealed override; the `events` table hash-chained and verified; the head `row_hash` served and logged at worker start; `crb_signoffs_total`; the append-only probe on every table; **not built on `feat/ns2`, carried forward (G-709):** the migration job's own owner URL in the chart and compose, so the API and the worker connect as a role that does not own the ledger |
| G · the grade says why | G-973, G-974, G-971, G-953, G-954, G-955 | `lint_status`; `failure_kind` stamped at write; `mutation.v2`; the executor and mining edge cases; a distinct commit counted as a distinct change (one task per patch-id, a revert paired with its original); the files the tests wrote kept in the pack |
| R · routing.v2 and the context arms | G-661, G-932, G-678 | ADR-0025 committed as ADR-0026 amends it; apparatus 2.4; registered readings with a frozen pool and a seeded order; the look rule, the hierarchy and the per-cell budget; the context arm and class-set version on every row, never pooled; the map, `/routes`, `/value`, sign-offs and the delivery gate read one arm and one version; the cell's standard served |
| F · the factory's licence and entry | G-662, G-975, G-707, G-934, G-671, G-933 | the required, scoreable strength probe; the delivered change's own cell; the credential re-check at claim; one brief composer for replay and the factory, and the replay `S1` arm; the leak guard; readiness reads the cell's standard, stops `no_proven_standard` or `needs_context` before any spend, runs calibration builds that never deliver, and applies the size rule |
| H · gates and spend | G-664, G-602, F5b, G-705, G-706, G-970 | `uv.lock` and a fresh-clone job as root with no docker daemon; a `PrometheusRule` template; a per-run spend cap; the reaper test on a fake clock; shared evidence directories; the docker-wait sites and their ratchet |
| E2 · economics in one scope | G-990, G-991, G-989 | **not built on `feat/ns2`, carried forward:** a cell's flat cost and latency means, the Pareto frontier, the best config and the forecast's price read one apparatus version and one posture class or are withheld; `GET /value` filters by posture class and refuses to pool two; a help-copy ratchet ties "not yet served" sentences to the API's fields (opened by Wave 1's stream E) |
| S0 · the approver task · from `feat/w2-s` | G-477 | **not built on `feat/ns2`, carried forward:** Home task 7 reads the real two-person readiness: Completed only when an approver other than the operator who would queue exists, never on the bootstrap admin alone |
| X · a configured builder endpoint | G-611 | every OpenAI-compatible builder and the labeller call the endpoint `CRB_OPENAI_BASE_URL` names, stamp its provider and use its timeout, reply length and retry count (`product.truth.26`, brought in from the parked `feat/w3-x`); the factory's test author stamps the provider of the endpoint it calls and refuses a rung naming another (`product.truth.27`) |

**Status on `feat/ns2`.** Built and verified: T, G, R, F, H, I (but G-709), X and C's claims
work (but G-994, G-996, G-995 and G-998). Not built, and carried forward to the list after Wave 4: E2
(G-989, G-990, G-991 — `measure.truth.30` and `truth.31` stay unmet), S0 (G-477 —
`home.truth.13` and `sign-off-a-cell.truth.3` stay unmet), C's check that a criterion kept its
words (G-994), its scheduled mutation pass (G-996), one owner per shared defect class (G-995)
and its refusal of a `[measured]` source the repository does not carry (G-998), and I's
migration-owner URL (G-709). `product.evidence.205` stays `partial` on G-664 until the
`fresh-clone` job has run green on the pull request's CI. G-660 is Wave 3's, by design.

**Done when:** truth.202, truth.203, posture.204, roles.7, evidence.205, go-live.15, go-live.20,
claims.21, value.111, truth.206, truth.207, truth.214, truth.216 and claims.210 read `met`, as
do the learn stream's automation.25 and measure.27, intake's recovery.23 and manufacture's
non-goals.12, and so do `home.truth.13` and `sign-off-a-cell.truth.3` (G-477), and product
truth.26 and truth.27; `APPARATUS_VERSION` reads 2.4; tests show a cell of many attempts on too
few commits routing `calibrate`, rows of more than one context arm or class-set version refused a
pooled reading, a planted leaking context line refused, a ticket in a cell with no proven
standard stopped before any spend with delivery off, a calibration build that never opens a pull
request, the code's look rule reproducing ADR-0026's operating characteristics, a build that
cannot be scored stopping before any push, and a production start under the override writing an
event that names who set it; the fresh-clone job passes every gate as root without a docker
daemon, installing from `uv.lock`.

## Wave 3 — the measurement (needs the operator)

One pre-registered campaign, graded at apparatus 2.4 in the sealed posture (sandbox and builder
both in docker), after Wave 2 — rows of different apparatus versions are never pooled, so a
campaign graded earlier would be bought twice. ADR-0026 item 13 is its protocol: cobra and click
`bug.fix` XS and S; one registered reading per cell, `S3` then `S1` under the look rule; `A0`
and `A0+L` on the first commits of each cell's seeded order; rung r1 only. Each cell's pool is
mined and qualified first, at no model cost.

| piece | gaps | what it produces |
|---|---|---|
| the readings: `S3` then `S1` per cell, the look rule, the sealed posture, rung r1, apparatus 2.4 | G-653, G-660, F42, G-571 | each cell's standard, ceiling or "no proven standard", every arm with its n and interval; README's measured section on vendored `S3` rows; rows stamped `executor: docker`; the probe green in the sandbox image |
| the loop pair: `A0` and `A0+L` on the same commits | G-653, G-537, G-572, G-590 | the north star with the loop off and on, as a descriptive paired reading beside the campaign's minimum detectable effect; each class's recurrence with the loop on against off |
| reviews on kept patches | G-539 | review classes measured on anchored reviews |
| the factory under docker: calibration builds on cobra; a tier-2 walkthrough on a scratch repository | G-549, G-365, G-142, G-367 | on cobra, the B-1b items rerun as sealed calibration builds — minutes and £ per item and no pull request, because no cobra cell has a proven standard until its `S1` reading delivers; on a scratch repository linked through the App, the tier-2 walkthrough seeded with a registered fixture reading whose `S3` and `S1` arms both deliver, ending in a pull request under the sealed posture — minutes and £ per delivered item |
| a timed intake pass over a real board column | G-928, G-383 | minutes and £ per ticket; the per-attempt £ the map serves |

**Done when:** the baseline review publishes, per arm, the first-attempt clean rate and working
changes per pound with n, interval and apparatus 2.4, the loop's paired reading with its
interval beside the minimum detectable effect, and each cell's standard or "no proven standard"
(value.109 met); README's measured section cites vendored rows whose checksum manifest and
re-derivation test pass in CI (claims.201 met); posture.23 and go-live.18 read met.

## Wave 4 — the second person and the go-live truth (autonomous; integrated on `feat/ns4`)

| stream · base | gaps | what ships |
|---|---|---|
| S · the second person · `feat/w2-s` | G-517, G-518, G-516, G-476, G-478, G-479, G-480, G-481, G-284, G-285, G-286 | a signed cell licenses delivery by default (ADR-0018, re-read against ADR-0026 item 8 before it merges: an unsigned cell stops a ticket before any spend, and `deliver_override` lifts only the sign-off clause of a proven standard); an approver is invited with a one-time link (task 7's readiness rule lands first, in Wave 2's S0); a decision carries its age; the sign-off gate shows the evidence's posture |
| P · posture and go-live · new | G-317, G-316, G-318, G-319, G-580, G-581, G-583, G-584, G-582, G-212, G-213, G-214, G-215, G-320, G-321, G-950, G-951, G-966 | `/posture` lists each go-live line as proven, attested or unproven; each posture row names its source and the page prints; the go-live walkthrough; mirror credentials; the remaining lock formats sealed; a damaged sealed set quarantined |
| V · truth on the instrument screens · new | G-102, G-124, G-126, G-108, G-143, G-184, G-180, G-204, G-229, G-255, G-952, G-992, G-993 | honest failure states and role gates on Capability, Connect, Measure, Factory, Ledger, Oracle, Repos and Routing; `ledger.exported` events; a gold witness beside each caught control; the walkthrough presses Sign off, Revoke sign-off, Freeze and Run by Tab and Enter |
| LIB · the context library · new, after S | G-673, G-677, G-675, G-676, G-735, G-737 | the entry record and its two-person sign-off ledger; the miner registry and its miners over a pinned commit; entry sets registered as arms and kept or retired by the look rule and the harm clause, the brief switch off by default; `/library/:repo` with one page per work type |
| CLS · the organisation's classes · new, after S | G-672 | class-set versions per organisation with the global classes as parents; the derivation and confirmation split by commit; one rule over ticket-time fields at replay and at intake, with the linked-ticket reader; the validity report with its size-agreement clause; the two-person sign-off; the class set as a DL-044 seam |
| FWD · the forward reading · new, after S | G-679 | held-out acceptance tests a second person writes for a calibration build; the `acceptance: held_out` stamp on its `S2` row; the registered `S2` reading that alone promotes an `S3` ceiling. Built on `feat/ns4b-fwd` (DL-334, DL-335, P-690 to P-696), then attacked and fixed: G-679 closed and `product.truth.215` met; `/factory/acceptance` is its page, and a ceiling's forward reading is registered on the work type's library page |
| CL · claims on the decision records · new | G-945, G-946 | `docs/adr/*.md` and `CHANGELOG.md` read by the claims gate, each page tagged or corrected in its own change, so every public page the repository carries is gated; each count of a list in the code on a gated page bound to a test that re-derives it, or removed (claims.218) |

**Status on `feat/ns4`.** Built and verified, then attacked and fixed (DL-119, DL-120, P-391 to
P-403): S (all but G-478, and G-477 carried from Wave 2 closed), P (all but G-321), V as stream T4
(all but G-143, G-992 and G-993) and LIB as streams L and M (G-673, G-676, G-677 and G-736 closed;
G-735 and G-737 open). Not built, and carried to the list after Wave 4: LIB's entry sets as arms
(G-675, so `product.truth.212` stays unmet) and CL (G-945, G-946). CLS and FWD were then built as
Wave 4b, on `feat/ns4b-cls` and `feat/ns4b-fwd`: CLS (DL-330 to DL-333, P-680 to P-689) closed
G-672, `product.truth.208` partial on G-761 (the linked-ticket reader, a replay pool keyed by the
rule's class alone, and the factory's own-cell licence), `product.extensibility.220` met, and the
class page's own gaps G-762, G-763 and G-764 (merge, split and the separation test) open; FWD
(DL-334, DL-335, P-690 to P-696) closed G-679 and `product.truth.215` reads met — see its row
above. The seams the integration moved
to later work are there too: the Decisions inbox reading the entry gate's own sign-off (G-738),
the read-then-insert ratchet (G-720), the failed-read ratchet's per-read rule and its list
(G-732), and the controls still disabled while their request runs (G-739).

**Done when:** an invited approver can accept, sign in and sign a cell on the walkthrough stack;
the factory refuses an unsigned cell by default; `/posture` shows each go-live line's state;
roles.209, extensibility.213, truth.212, explanation.211, truth.208 and truth.215 read met; the
only open product criteria are go-live.16 (F43), release.22 (G-604), extensibility.25 (F21) and
identity.11 (G-600). **Not met on `feat/ns4`:** truth.208, truth.212 and truth.215 are unmet
(CLS, LIB's arms and FWD were not built), and the walkthrough stack cannot show a person signing a
cell (G-956); roles.209, extensibility.213 and explanation.211 read met. On `feat/ns4b` (Wave
4b) `product.truth.208` reads partial (G-761) and `product.truth.215` reads met.

## Wave 5 — the library and the organisation's classes, measured (needs the operator)

Every reading here is registered before its first attempt and spends from its cell's budget
(ADR-0026 items 5 and 10). Prospective readings run at each cell's own commit rate, so they are
planned in months or years, not in runs.

| act | what it needs | when |
|---|---|---|
| an organisation's first class set: derive on the derivation commits, validate, sign, register readings on the confirmation commits | a person-labelled sample; a second person; a budget per cell | after Wave 4's CLS |
| library entry sets as arms: mechanical sets on replay, signed sets on new commits | a budget per cell; the per-repository brief switch, off until a set is kept | after Wave 4's LIB; on slow repositories this takes years |
| forward `S2` readings in cells whose standard is a ceiling | tickets that carry a person's failing test; held-out acceptance tests from a second person | after Wave 4's FWD |

## Acts only the operator can do

These are not wave items; each unblocks the work named beside it.

| act | unblocks | when |
|---|---|---|
| let the train land (#53 to #57) | everything | now |
| decide on #58 (dev auto-login) | nothing in the definition of done | after the train |
| merge the pull request that carries the integration-only commits | `sign-off-a-cell.truth.22` on `main` | right after #57 |
| merge each wave | each wave | as each is verified |
| restart the stack on merged code; docker; a budget | Wave 3 | after Wave 2 |
| a second person: a reviewer and an approver | G-539; a real sign-off; go-live.16's rotated admin | Waves 3 and 4 |
| sign in through a live identity provider | F43 (go-live.16) | Wave 4 or later |
| cut 2.0.0b1: the tag, the chart as an OCI artifact, a `v*` tag-protection ruleset | G-604 (release.22) | after Wave 4 |
| a penetration test | F46, named in G-317's line | before go-live |
| add a fine-grained token with Administration: read as the secret `BRANCH_PROTECTION_TOKEN` | G-930 (`product.evidence.6`): the daily `branch-protection` workflow goes green | any time |
| accept ADR-0026 and fix its [operator] values: the per-cell budget, the first look, the size rule, the class-set split and thresholds | Wave 2's R and F, built on the proposals | now: Wave 2 is built on them |
| once ADR-0026 is accepted, drop the `[operator]` markers on the values it fixed | the record reads as decided | after the acceptance |
| merge `feat/ns1`, then open the pull request for `feat/ns2` and replace the `pull/new/feat/ns2` links in CHANGELOG with `pull/<n>` | Wave 2 on `main`; G-997's twin for Wave 2 | after `feat/ns1` merges |
| run CI on the `feat/ns2` pull request, so the `fresh-clone` job and the other new jobs have their first runs | G-664 (`product.evidence.205`) | when the pull request opens |
| add `fresh-clone` to `main`'s required checks | G-930's list; a skipped job no longer passes a merge | after its first green run |
| upgrade across revision 0013 as DEPLOYMENT says: scale the API and the worker to 0, run the migration, never `helm rollback` across 0013 | the hash-chained audit trail on a running stack | at the first deploy of Wave 2 |
| rebuild the shared development environment from `uv.lock` with CI's extras | G-766 | now |
| register and fund the Wave 3 readings | Wave 3 | after Wave 2 |
| a person-labelled sample and a second person for class sets and library entries | Wave 5 | after Wave 4 |

## After Wave 4, in gap order

| theme | gaps |
|---|---|
| each stream's own numbers and automation | G-535, G-500, G-536, G-556, G-565, G-534, G-564, G-548 |
| honest actions and failure states | G-397, G-976, G-101, G-117, G-127, G-128, G-132, G-134, G-181, G-182, G-205, G-206, G-237, G-254, G-294, G-368, G-400, G-920, F32, F6 |
| doors and wayfinding | G-907, G-977, G-236, G-444, G-253, G-260, G-293, G-366, G-228, G-396, G-979 |
| proof through each journey's own doors | G-428, G-300, G-380, G-399, G-446, G-109, G-119, G-125, G-133, G-238, G-256, G-268, G-183 |
| time, cost and non-goals in words | G-302, G-401, G-430, G-447, G-978, G-908, G-382, G-402, G-429, G-140, G-185, G-207, G-262, G-263, G-269 |
| what Wave 2 left open: the walkthrough's sealed reading, a spend cap that is a ceiling, the approver task, economics in one scope, the migration job's owner URL, the fresh-clone job's first CI run, and C's evidence checks | G-956, G-963, G-477, G-990, G-991, G-989, G-709, G-664, G-994, G-996, G-995, G-998 |
| what the Wave 2 review found in our own process: the gate environment, the plan's record, accepted ADRs and a stale base | G-766, G-767, G-768, G-769 |
| what Wave 4 left open: the Decisions inbox's sign-off reader, the read-then-insert ratchet, the failed-read ratchet, controls disabled while pending, and the streams not built (LIB's arms, CL; CLS and FWD are built as Wave 4b) | G-738, G-720, G-732, G-739, G-675, G-945, G-946 |
| what stream CLS left open: the linked-ticket reader, a replay pool keyed by the rule's class alone and the factory's own-cell licence for an organisation's class, class sets on Decisions, the map's organisation cells, and the merge, split and separation-test tools | G-761, G-762, G-763, G-764 |
| the product | F43, G-604, F21, G-600 |

## What each wave must do to its own artefacts

1. Flip the criteria it closes to `met` with evidence that resolves — in the same pull request.
2. Add a criterion for anything it builds that no criterion covered (and say so in the PR).
3. Regenerate `GAP-ANALYSIS.md` (`python scripts/dod_check.py`) and commit it.
4. Never delete a gap without either closing it or recording why it is `n/a`.
