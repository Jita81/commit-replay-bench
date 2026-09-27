<!--
Navigation
----------
What it is:   The plan — the order of work in GAP-ANALYSIS.md batched into waves (Wave 0 to
              Wave 4, the acts only the operator can do, and what comes after Wave 4).
What it does: Says which gaps travel together, on which branch, and what "done" looks like when
              each wave lands; every wave item is a gap id the record defines, and
              scripts/dod_check.py refuses one that is not.
How:          One table per wave; its `gaps` column holds gap ids and nothing else (the checker
              reads it); the other columns say what ships and why. Ids a wave closes stay
              valid here because the generator lists them under "Gap ids retired" once the
              artefacts' git history shows they were gaps; every gap the order of work ranks
              must sit in some table here, and no heading quotes a rank (P-122).
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none (DL-063 records the rule the checker enforces on this file)
Works with:   docs/dod/GAP-ANALYSIS.md (the order of work this batches), docs/dod/STANDARD.md
              (§6: the next feature is the top of the gap analysis), scripts/dod_check.py
              (refuses a wave item that is not a gap id), docs/PREVENTION.md (P-051, the class
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
false as soon as the order moves (P-122). The check reads ids, not meaning, so a reviewer
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
or the list after Wave 4 below, and the checker now refuses a ranked gap in no table (P-122).
Waves 2 to 4 have not started.

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

D1, the checker, closes in the same change the register rows that name it (P-051, "the record
drifts from the order of work", and P-060, "the generated file vouches for itself"), so it
carries no gap id: `dod_check.py` refuses a gap line no criterion cites, a wave item here that
is not a gap id, and a gap among the first 25 of the order of work that no wave names; and it
keeps a closed gap nameable only while the history vouches for it (DL-063, DL-064).

Outside the waves, and not DoD work: carrying the four commits that exist only on the
integration tree (`770adbb`, `79f4597`, `27f2171`, `8d15f12`) to `main` in one pull request
after #57 lands. Their criterion is on the record already: `sign-off-a-cell.truth.22`, met
(a sign-off lifts only a cell read in the posture class its evidence was graded in).

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

**Done when:** on the merged branch, `GAP-ANALYSIS.md` no longer lists G-532, G-912, F23, F35,
G-905, G-911, G-919 or F26, and G-925 is replaced by narrower gaps for what nothing records;
the tier-1 walkthrough passes with specs in which an admin resets a colleague's password and
the colleague signs in again, and an operator accepts a refusal line on `/learn` and reads what
it did.

## Wave 2 — trustworthy when (autonomous)

Four of the external assessment's five conditions, spend under control, and the approver task
that now leads the autonomous work. On this branch the order of work puts G-477 (Home's task 7
reads Completed with only the bootstrap admin) first among the gaps nobody but us can close,
so it moves here from Wave 4 (STANDARD §6); it restarts from the parked `feat/w2-s`, whose
readiness rule it is, and the rest of that stream stays in Wave 4. H, I and C can
start beside Wave 1; R branches from Wave 1's merge, because it shares `capability.py` with E
and `learn.py` with L; F owns `worker.py` for the wave. A3 (G-973) and A6 (G-974) ride the one
apparatus bump to 2.4 with `routing.v2`.

| stream | gaps | what ships |
|---|---|---|
| R · `routing.v2` | G-661, G-540, G-973, G-974 | one ADR; apparatus 2.4; a distinct-task minimum; `calibrate` on an unmeasured oracle; the sealed-posture clause; `lint_status` and `mutation.v2` in the same bump; the map and `/value` split by learn label |
| F · factory | G-662, G-538, G-707, G-975 | the required, scoreable strength probe and the `oracle_not_scoreable` stop; factory builds get the loop's overlay and labels; the worker re-checks the builder credential when it claims a run; a pull request opens only when the delivered change's own cell routes `deliver` |
| I · audit | G-663, F51, G-601, G-924, G-972, G-760 | an audit event naming who set the unsealed override; the `events` table hash-chained and verified; the head `row_hash` served and logged at worker start; `crb_signoffs_total`; the append-only probe on every table; the migration job's own owner URL in the chart and compose, so the API and the worker connect as a role that does not own the ledger |
| H · gates and spend | G-664, G-602, F5b, G-705, G-706, G-970, G-971, G-987 | `uv.lock`, CI installing from it, and a fresh-clone job as root with no docker daemon; a `PrometheusRule` template; a per-run spend cap (the assessment's C8 re-scoped to it); the reaper test on a fake clock; the Helm API and worker share the evidence directories; the docker-wait sites and their ratchet; the executor and mining edge cases; one retrying helper for every system event's trace seq |
| E2 · economics in one scope | G-990, G-991, G-989 | a cell's flat cost and latency means, the Pareto frontier, the best config and the forecast's price read one apparatus version and one posture class or are withheld; `GET /value` filters by posture class and refuses to pool two; a help-copy ratchet ties "not yet served" sentences to the API's fields (opened by Wave 1's stream E) |
| S0 · the approver task · from `feat/w2-s` | G-477 | Home task 7 reads the real two-person readiness: Completed only when an approver other than the operator who would queue exists, never on the bootstrap admin alone |
| C · claims | G-929, G-660, G-994, G-996, G-995, G-998 | the claims allowlist widened page by page, `docs/dod/**` included; the rows locator and the re-derivation test, ready for Wave 3's rows; the README routing bar generated and checked; a scheduled mutation pass that proves the evidence of a met criterion or a closed prevention row can fail, and a check that a criterion flipped to met kept its words; one owner per shared defect class in a wave, so parallel streams stop fixing one class several ways; a `[measured]` tag whose method names a source the repository does not carry is refused |

The builder-endpoint work parked on `feat/w3-x` joins this wave when its criteria reach the
record; until then it is not a wave item.

**Done when:** truth.202, truth.203, posture.204, roles.7, evidence.205, go-live.15, go-live.20
and claims.21 read `met`, and so do `home.truth.13` and `sign-off-a-cell.truth.3` (G-477); `APPARATUS_VERSION` reads 2.4; the fresh-clone job passes every gate
as root without a docker daemon, installing from `uv.lock`; tests show a cell of many attempts
on too few tasks routing `calibrate`, a build that cannot be scored stopping before any push,
and a production start under the override writing an event that names who set it.

## Wave 3 — the measurement (needs the operator)

One campaign, graded at apparatus 2.4, in the sealed posture (sandbox and builder both in
docker), after Wave 2 — rows of two apparatus versions are never pooled, so a campaign graded
at 2.3 would be bought twice.

| arm | gaps | what it produces |
|---|---|---|
| sealed replay: cobra `bug.fix` XS and S, at least 10 distinct tasks per cell, one attempt each | G-660, F42, G-571 | README's `[measured]` section on vendored rows; rows stamped `executor: docker`; the probe green in the sandbox image |
| paired blind: the same tasks with the loop off and on | G-653, G-537, G-572, G-590 | the north star before and after, each with its interval; each class's recurrence in round 2 against round 1; each switch's effect per pound |
| reviews on kept patches | G-539 | review classes measured on anchored reviews |
| a factory rerun under docker on a scratch repository | G-549, G-365, G-142, G-367 | a delivered pull request under the sealed posture; minutes and £ per item |
| a timed intake pass over a real board column | G-928, G-383 | minutes and £ per ticket; the per-attempt £ the map serves |

**Done when:** the baseline review publishes the north star with the loop off and on, each with
n, its interval in pounds and apparatus 2.4 (value.109 met); README's measured section cites
vendored rows whose checksum manifest and re-derivation test pass in CI (claims.201 met);
posture.23 and go-live.18 read met.

## Wave 4 — the second person and the go-live truth (autonomous)

| stream · base | gaps | what ships |
|---|---|---|
| S · the second person · `feat/w2-s` | G-517, G-518, G-516, G-476, G-478, G-479, G-480, G-481, G-284, G-285, G-286 | a signed cell licenses delivery by default (ADR-0018); an approver is invited with a one-time link (task 7's readiness rule lands first, in Wave 2's S0); a decision carries its age; the sign-off gate shows the evidence's posture |
| P · posture and go-live · new | G-317, G-316, G-318, G-319, G-580, G-581, G-583, G-584, G-582, G-212, G-213, G-214, G-215, G-320, G-321, G-950, G-951, G-966 | `/posture` lists each go-live line as proven, attested or unproven; each posture row names its source and the page prints; the go-live walkthrough; mirror credentials; the remaining lock formats sealed; a damaged sealed set quarantined |
| T · truth on the instrument screens · new | G-102, G-124, G-126, G-108, G-143, G-184, G-180, G-204, G-229, G-255, G-952, G-992, G-993 | honest failure states and role gates on Capability, Connect, Measure, Factory, Ledger, Oracle, Repos and Routing; `ledger.exported` events; a gold witness beside each caught control; the walkthrough presses Sign off, Revoke sign-off, Freeze and Run by Tab and Enter |

**Done when:** an invited approver can accept, sign in and sign a cell on the walkthrough stack;
the factory refuses an unsigned cell by default; `/posture` shows each go-live line's state; the
only open product criteria are go-live.16 (F43), release.22 (G-604), extensibility.25 (F21) and
identity.11 (G-600).

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

## After Wave 4, in gap order

| theme | gaps |
|---|---|
| each stream's own numbers and automation | G-535, G-500, G-536, G-556, G-565, G-534, G-564, G-548 |
| honest actions and failure states | G-397, G-976, G-101, G-117, G-127, G-128, G-132, G-134, G-181, G-182, G-205, G-206, G-237, G-254, G-294, G-368, G-400, G-920, F32, F6 |
| doors and wayfinding | G-907, G-977, G-236, G-444, G-253, G-260, G-293, G-366, G-228, G-396, G-979 |
| proof through each journey's own doors | G-428, G-300, G-380, G-399, G-446, G-109, G-119, G-125, G-133, G-238, G-256, G-268, G-183 |
| time, cost and non-goals in words | G-302, G-401, G-430, G-447, G-978, G-908, G-382, G-402, G-429, G-140, G-185, G-207, G-262, G-263, G-269 |
| the product | F43, G-604, F21, G-600 |

## What each wave must do to its own artefacts

1. Flip the criteria it closes to `met` with evidence that resolves — in the same pull request.
2. Add a criterion for anything it builds that no criterion covered (and say so in the PR).
3. Regenerate `GAP-ANALYSIS.md` (`python scripts/dod_check.py`) and commit it.
4. Never delete a gap without either closing it or recording why it is `n/a`.
