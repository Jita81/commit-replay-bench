# ADR-0026 — The context standard: pre-registered context arms, a look rule with one error budget per cell, a leak guard, an entry gate, class sets held out by commit, and a library that reaches a brief only when measured

**Status:** Proposed (DL-086; the values marked **[operator]** are proposals the operator fixes
before stream R builds them; DL-087 records the library's scope)
**Date:** 2026-09-27
**Apparatus impact:** none of its own. It rides ADR-0025's bump to **2.4**: every row of 2.4 or
later stamps its context arm (`labels.context_arm`) and its class-set version
(`labels.taxonomy`), and routing.v2's rule is the look rule of item 3. ADR-0025 is amended here
before it is committed (item 6), so there is one bump, not two. No belt, belt set, size tier or
global class moves, and a clean row means at 2.4 what it meant at 2.3.

**Supersedes in part** ADR-0024 item 6 in two respects: rows with and without the loop's
changes no longer pool inside a checks arm, because the loop switch is part of the context arm
(item 1); and its export clause, which sends the `off` rows of every mode, now sends `S3` rows
only (item 12). ADR-0024's rejection of "put the finish gate on the arm" **stands**: the finish
gate, the playbook lines and the budget profile still pool inside an arm (item 1).
ADR-0025 as drafted (items 2, 8, 9, 10, 12 and 15: `min_tasks` 10 and the fixed bar become the
look rule; `not_licensed` becomes `no_proven_standard` and applies whether or not delivery is on;
a factory row may route for arm `S2` only; a sign-off stamps and lifts one arm, one class-set
version and one reading; item 12's sentence "`deliver_override` still overrides" is narrowed —
items 6 and 8). ADR-0003's amendment of 2026-09-16, decision 1 (an item in a cell that does not
route `deliver` is built, graded and reviewed, then withheld; an approver's `deliver_override`
lifts the route for one run) — item 8. ADR-0018 as drafted on `feat/w2-s`, decisions 1, 3 and 5
(an unsigned cell's item is built and withheld; the override lifts both clauses; a deployment may
make the route alone its bar) — item 8. The rule in `docs/adr/README.md` that any change to the
class taxonomy bumps the apparatus, and the *Touch when* of `src/crb/core/taxonomy.py` (now the
global vocabulary only — item 9). **Keeps** ADR-0007's export allowlist unchanged: item 12
narrows which rows leave and adds no field. **Relies on** ADR-0012, ADR-0019 and ADR-0023 (the
sealed posture), ADR-0015 and ADR-0016 (expiry and the two-person clause), ADR-0020 (the loop),
and ADR-0017 and ADR-0022 (intake).

## Context

The operator stated the product on 2026-09-26, in three statements. In short: it is a
context-engineering tuning tool and a governance layer that (1) derives an organisation's own
classification of work from its commits by replay; (2) for each class finds the least context —
the tests, and signed project knowledge around them — that gives a statistically proven
first-attempt pass rate; (3) lets a ticket into manufacturing only when it carries that context;
(4) surfaces what it learns as a curated context library (decisions, conventions, work types,
solution designs, standards) in one nomenclature that people verify and sign off, which then
shapes the builder's context; and (5) layers the organisation's standards on an ISO/IEC 25010
and 5055 baseline — improving iteratively until sure.

What exists answers little of that. The only context levels are sighted and blind, and mode
is a filter, not an axis: the cell key has no context field (`crb.core.ledger.CELL_FIELDS`) and
`docs/EVIDENCE-AND-CLAIMS.md` §3 lists the context condition as absent. The finish gate and the
playbook lines change the brief but pool inside a cell (`crb.core.checks`, ADR-0024 §6), and
`harness_command` and the rules text are not on the row (`BuildBrief.to_dict`). The class
vocabulary is a closed global constant whose *Touch when* reads "never for a new repository".
Intake classifies with a different keyword table and sizes by story points, defaulting to `S`.
A ready ticket in a cell that does not route `deliver` is still registered and built; only its
pull request is withheld. Nothing curates project knowledge, and nothing names ISO/IEC 25010.

The evidence says one thing clearly. On the 37 tasks attempted both ways at apparatus 2.2,
first attempts were clean 30 times with the commit's tests visible and 14 times without them:
13 clean both ways, 17 only with the tests, 1 only without, 6 neither — the tests add 43.2
points (paired Wald 95% 25.6 to 60.9; exact McNemar p = 0.00014) **[measured — n = 37 paired
tasks, the operator's export of 2026-09-25 read through `scripts/value_baseline.py`, first
observed r1 attempt per task and mode in file order; apparatus 2.2; host posture]**. Nothing
between those two contexts has been measured. Upstream, the +22.9-point "signed facts" lever was
leakage: facts written without the diff scored 33 of 48, exactly the message-only arm, while the
72.9% that crb's record calls "bare" is the checklist arm **[measured — n = 48 census tasks per
arm, one rep; method: the upstream T2 ledger (`grades.jsonl`, `informed_grades.json`,
`regrade_grades.json`) tallied 2026-09-26; apparatus n/a — the upstream Athena harness, not
crb]**.
That re-run also gave every task one class's four slots, and its informed control had 22 empty
sheets and the answer commit reachable in its worktree, so per-class structural facts written
without the diff are unmeasured, not falsified. No cell is proven: the largest cells (cobra and
click `bug.fix` XS and S) hold 9 to 11 distinct commits, koa's XS and S hold 6 each and cobra's M
holds 4, and every other cell 3 or fewer **[measured — n = 81 sighted first attempts at 2.2;
method: distinct tasks per repository, class and size under ADR-0025's first-attempt rule;
apparatus 2.2]**. All 618 rows were graded in the host posture, where the builder works in a git
worktree of the full clone and the target commit is still in the object store; the sealed
one-commit checkout exists but is used only when the builder runs in a container
(`crb.builders.adapter`, `container=`; `default_builder_executor` is `docker` in `prod` and
`host` in `dev`).

Independent verification of the first design of this decision found it measured the wrong
thing in the places each item below answers: it pooled on digests that the loop changes
mid-campaign (item 1); it spent a fresh error rate on every arm (items 4 and 5); it let classes
be carved on outcomes and licensed on the same commits (item 9); it unified class across replay
and intake but not size (items 8 and 9); it let the commit's own tests — written with the change
— certify a standard (item 4); and it priced library measurements as replays when its own leak
rule makes them prospective (item 10).

## Decision

1. **A context arm is a pre-registered id; its parts are provenance, never a pooling key.**
   `crb.core.context_arm` names every arm with one grammar: a base, then optional modifiers in
   this order — `+facts@<drafter>`, `+library@<version>`, `+L`. The `S1` base names its test
   author's canonical model, `S1@<author>` (ADR-0021's `canonical_model`, so a provider label
   never makes one model two authors), because an authored test is only as good as its author:
   two author models are two arms, and `cell_stats` refuses to pool them. Where this record
   writes `S1` alone, it means `S1@<author>` for the author the reading pins.

   | base | the builder is given | retrospective (replay) | prospective (factory) |
   |---|---|---|---|
   | `A0` | the ticket only: the commit message, or the linked ticket as it stood at the parent's date | yes — descriptive only | no |
   | `S1@<author>` | the ticket and a failing test the named test author wrote in the sealed parent checkout | yes — certifies (item 4) | yes |
   | `S2` | the ticket and a failing test a person attached before any build | no | yes — certifies (item 8) |
   | `S3` | the ticket and the commit's own tests | yes — a ceiling, never certifies | no |

   | modifier | means | allowed retrospectively only when |
   |---|---|---|
   | `+facts@<drafter>` | structural facts drafted by a pinned model from the ticket and the parent tree | drafted in the sealed parent checkout, no person's edit or selection |
   | `+library@<version>` | a frozen set of library entries (item 10) | every entry mined mechanically at a commit at or before the reading's pool began, no person's edit or selection |
   | `+L` | the repository's loop switch on (ADR-0020) — a **policy**, not a snapshot | always (the loop learns only from other, older commits — item 7) |

   The composer that builds the brief (stream F, one for replay and the factory) stamps
   `labels.context_arm` from what the brief actually carried. Everything else about the brief is
   stamped as **provenance**: `ctx_ticket` (`message` or `ticket@<date>`), `ctx_brief` (sha256 of
   the composed parts), `ctx_harness` (sha256 of `harness_command`), `ctx_rules` (sha256 of
   `DEFAULT_RULES`), `ctx_author` (the test author's provider stamp; its canonical model is in
   the arm), `ctx_library` (digest of
   the injected entry ids and versions), `ctx_refused` (context lines the leak guard refused),
   and the existing `learn_playbook`, `learn_lines`, `checks`, `finish_gate` and
   `budget_profile`. A provenance stamp is shown and filterable; it never splits a cell.
   `crb.core.ledger.cell_stats` raises `ContextArmsPooled` for rows of two arms, as it raises
   `ChecksArmsPooled` (ADR-0024) and `ApparatusPooled` (ADR-0025). A reading (item 2) pins one
   test-author model by naming `S1@<author>` in its hierarchy, so the map, `/routes` and
   `/value` show each author's rows as their own arm and never pool them.

   *Why this answers ADR-0024's objection.* ADR-0024 rejected "put the finish gate on the arm"
   because splitting on it "would reset a repository's cells whenever the loop applies its
   most-used process lever". An arm id names a policy fixed before the first attempt — `+L`
   means "the loop is on", whatever it then does — so the loop adding a line or throwing a
   switch mid-campaign changes a provenance stamp, never the arm. Inside one arm the finish gate,
   the playbook lines and the budget profile still pool, as ADR-0024 decided. What changes is
   that rows with the loop on and off are two arms and never pool, and that an authored-test row
   and a real-test row — both `sighted` today — are two arms.

2. **A reading is registered before its first attempt, and only rows graded after it count.**
   `crb.core.reading` records, as a hash-chained event before any attempt: the repository, the
   cell key, the apparatus, the class-set version, the posture class and checks arm, the
   **hierarchy** (arm ids, richest first — item 4), any descriptive arms and their fixed counts,
   the rule (item 3) and the share of the cell's error budget it spends (item 5) — the
   hierarchy's `S1@<author>` arms name the test author's model — and the **frozen pool**: the
   list of qualified commits and its sha256. The pool is chosen by a rule blind to every
   outcome — every qualified commit of the cell, or every one authored at or after a date the
   operator names — and the rule is recorded with it; a hand-picked list is refused
   `pool_not_blind`, because a list chosen after grading could hold only the commits that
   passed (DL-097). The **seeded order** is normative: commits are
   read in ascending
   `sha256("crb.reading.v1|" + repo + "|" + canonical cell key + "|" + commit sha)`, one order
   per cell shared by every arm, so the arms are paired and no run incident can reorder a look.
   A registration is refused `pool_seen` if any pool commit already has a graded row under an arm
   of its hierarchy at that apparatus, and `budget_spent` if the cell's budget cannot cover it.
   Within a reading a commit counts once, by its first observed attempt (ADR-0025 item 2) among
   rows this deployment graded after registration (an imported row is history and never counts,
   DL-097), on the reading's checks arm, at rung `r1`: for a replayed arm, **in the sealed posture**
   (the builder in the sealed container and the tests in the docker sandbox — ADR-0012,
   ADR-0019, ADR-0023); for `S2`, on factory rows whose held-out acceptance tests stayed outside
   the builder's tree until grading (item 8).
   A commit with no observed attempt is `pending` and the look waits; a harness row is re-run
   before its look is read. A commit the instrument cannot grade (it fails qualification, or
   stays `harness` after the re-runs the reading allows) leaves the pool with its reason
   recorded before any outcome of it is seen, and the next commit in the seeded order takes its
   place — so, unlike ADR-0025 item 2, an instrument failure is never counted as a miss that
   could end a reading.

3. **The look rule.** An arm of a reading is read only at 20, 30 and 40 distinct commits in the
   seeded order. It reads `deliver` at 20 of the first 20, 29 of the first 30 or 38 of the first
   40 clean; `insufficient` at its third miss (38 of 40 is then out of reach); `undecided` if the
   pool ends before a look decides; otherwise `look_pending` with the commits still needed. The
   Wilson 95% lower bound at each deliver point is 0.839, 0.833 and 0.835. What the rule does
   **[measured — n = 40 draws per path, exact enumeration, no sampling, so no interval; method:
   an exact dynamic programme over 40 Bernoulli draws with the stop at the third miss,
   reproduced independently by the method verifier; apparatus n/a]**:

   | true first-attempt rate | P(deliver) | expected commits consumed |
   |---|---|---|
   | 0.38 | 0.0% | 4.8 |
   | 0.70 | 0.1% | 10.0 |
   | 0.80 | **2.1%** | 14.7 |
   | 0.85 | 8.4% | 18.7 |
   | 0.90 | 28.7% | 23.8 |
   | 0.926 | 48.9% | 26.0 |
   | 0.95 | 72.3% | 26.7 |
   | 0.97 | 90.2% | 25.4 |

   routing.v2's fixed bar, re-read as rows accrue, would certify a cell whose true rate is 0.80
   2.8% of the time read once at 16 commits, 5.0% read at 16, 24, 32 and 40, and 6.3% read after
   every commit from 10 to 40 **[measured — n = 40 draws per path, exact enumeration, no
   sampling; method: the same dynamic programme applied to routing.v2's fixed bar at each
   reading schedule; apparatus n/a]**. The look rule replaces ADR-0025's `min_tasks` 10
   and its fixed point and Wilson bars (item 6). The first look at 20 is the operator's decision
   **[operator]**.

4. **The standard is found by a fixed-sequence hierarchy, richest arm first.** A reading's
   hierarchy is read in its registered order and stops at the **first arm that does not
   deliver**; the cell's standard is the leanest arm in that unbroken chain. The false-deliver
   rate of the whole chain is the rule's rate for one arm — 2.1% at a true rate of 0.80 —
   because a leaner arm is decided only after every richer arm delivered, so the first arm whose
   true rate is at or below 0.80 must itself deliver for any error to occur. Phase 1's hierarchy
   is `S3` then `S1`. The arms run in parallel on the same commits; only the decision is ordered.
   Once `S3` reads `insufficient`, `S1` stops too: no leaner arm can become the standard.
   - **`S3` never certifies.** The commit's own tests were written with the change and can
     encode its values and names; a standard found on `S3` alone reads **`ceiling,
     forward-unvalidated`** and admits tickets only as calibration builds (item 8) until the
     cell's `S2` reading delivers.
   - **Only the `S1` family certifies retrospectively**: `S1` alone, or with context produced
     mechanically before the pool began (`+facts@<drafter>`, `+library@<version>` under item 1's
     conditions). Its test is answer-blind by construction: the author sees the ticket and the
     parent's example tests, ranked by title overlap over the parent's tracked files, never the
     diff, the commit's tests or later history.
   - **`S2` certifies prospectively only**, from calibration builds graded on held-out acceptance
     tests (item 8).
   - **`A0` and `A0+L` never certify.** They run a fixed number of commits for the north star
     and the loop's paired reading (item 13), and spend no budget.

5. **One error budget per cell, across every arm and every phase.** A cell — repository ×
   cell key × apparatus × class-set version — has one budget, **5% [operator; 2.5% is the
   stricter choice]**. Every reading registered on the cell spends its rule's P(deliver | 0.80),
   computed exactly in code by the item 3 programme; a registration that would overspend is
   refused `budget_spent`, and the cell then reads "no proven standard at this apparatus and
   class-set version" for any arm not already decided. Descriptive arms spend nothing. The rules a
   reading may register are pre-registered here:

   | rule | looks (deliver at) | P(deliver) at 0.80 | at 0.90 | at 0.95 | at 0.97 |
   |---|---|---|---|---|---|
   | `look.v1` | 20/20, 29/30, 38/40 | 2.10% | 28.7% | 72.3% | 90.2% |
   | `look.v1-strict` | 20/20, 30/30, 39/40 | 1.22% | 15.4% | 49.4% | 72.7% |
   | `look.v1-late` | 30/30, 39/40 | 0.22% | 9.2% | 41.8% | 67.5% |

   **[measured — n = 40 draws per path, exact enumeration, no sampling; method: the item 3
   programme applied to each rule; apparatus n/a]**. With the 5% budget a cell can take Phase 1
   (`look.v1`, 2.10%), one later reading under `look.v1` (2.10%) and one under `look.v1-late`
   (0.22%): 4.42% in all. With 2.5% it can take Phase 1 and one `look.v1-late` reading. Each
   cell's spend is served on the map beside its readings. A new apparatus or class-set version is
   a new cell with a new budget; both are recorded decisions (an ADR, a signed version), so a
   bump is visible, never a quiet way to buy another look. Across cells nothing is corrected: four
   cells each sitting at 0.80 give about an 8% chance that at least one is wrongly certified
   under Phase 1 alone **[hypothesis — four independent cells each at a true rate of 0.80;
   method: 1 − (1 − 0.0210)^4, exact]**.

6. **routing.v2 carries the context arm, the class-set version and the look rule, in the one bump
   to 2.4 (amending ADR-0025 before it is committed).**
   - Item 1 (one apparatus per reading) extends to one context arm and one class-set version:
     `?arm=` and `?taxonomy=` select; `all` is refused with 422, as `?apparatus=all` is.
   - Item 2's first-attempt rule stands inside a reading, with item 2 of this ADR's pool rule for
     instrument failures, and its "a factory row is never a routing first attempt" holds for
     every factory row **except** an `S2` row (item 8). The sealed-posture clause ADR-0025 adds
     applies to replayed arms; an `S2` reading's posture clause is item 8's held-out rule.
   - Item 8's table: rows 5 (`tasks_below_min`), 10 (`point_below_bar`) and 11
     (`ci_low_below_bar`) are replaced, in the same positions, by `reading_unregistered` and
     `look_pending` (`calibrate`, next act `register`, or `replay`, `qualify` or `mine` with the
     commits still needed), and by `insufficient` (`human`, next act a richer arm in a new reading
     within the budget, `split`, or a person), `undecided` (`calibrate`, next act `mine`) and
     `ceiling` (`calibrate`, next act calibration builds toward `S2`). `route()` returns
     `deliver` only for the arm that is the cell's standard and not a ceiling. `tasks_to_bar`
     becomes the commits still needed to the next look.
   - Item 9: a sign-off may be written only for the cell's standard arm, when its reading reads
     `deliver`; `thin_tasks` becomes `look_pending`. The `crb.signoff.v5` record also stamps,
     under its `row_hash`, the `context_arm`, the `taxonomy` and the reading's id, and
     `apply_signoffs` lifts only a cell read on that same arm, class-set version and reading —
     as ADR-0024 made the overlay lift only a cell read on the checks arm it was signed on. A
     sign-off read against another arm, version or reading lifts nothing and is listed stale.
   - Item 10: `RoutingPolicy.describe()` renders the look rule, the hierarchy and the budget.
   - Item 12: `not_licensed` becomes `no_proven_standard` and applies whether or not delivery is
     switched on (item 8); `size_exceeds_licence` and `cell_not_licensed` stand. Its sentence
     "`deliver_override` still overrides" becomes: `deliver_override` lifts only the sign-off
     clause of a proven standard, never `no_proven_standard`, `size_exceeds_licence` or
     `cell_not_licensed` (item 8).
   - Item 15: the smallest cell that can deliver is 20 distinct commits in a registered reading,
     all clean on their first observed attempt in the sealed posture.

7. **The leak guard: no context arm carries the answer.** A replay brief is built only from what
   existed at the commit's parent: its message, or its linked ticket as it stood at the parent's
   date (`ctx_ticket` says which; where no ticket is linked the message is a proxy that may name
   the fix, so `A0` is optimistic against a real ticket **[hypothesis — unmeasured]**); the
   parent tree; learned lines taught by at least two other commits, all older than this one by
   commit date (`playbook.held_out` plus time order); and, for a retrospective arm, only facts or
   library entries produced under item 1's conditions. The test author works in a sealed
   one-commit checkout of the parent (`crb.builders.container.SealedCheckout`) in every posture;
   it never sees the diff, the commit's tests or later history, and the `S1` builder never sees
   the real tests, which are removed before grading. Brief composition refuses any context line
   that names an identifier or literal the commit introduced — present in the gold post-image,
   absent from the parent tree — and counts each refusal on the row (`ctx_refused`); the builder
   never sees the diff that powers the check. A test plants such a line and sees it refused.
   Only replayed rows graded in the sealed posture count toward a standard (item 2): in the host
   posture the worktree holds the target commit and the only guards are `DEFAULT_RULES` and the
   builder's deny rules, so the leak is closed only in the sealed posture.

8. **The entry gate: a ticket enters manufacturing only when its cell has a proven standard and
   the ticket carries it.** Readiness reads the cell's standard from the current signed map
   (`standard_for(repo, cell)` on the repository's checks arm and the deployment's posture
   class — a reading speaks only for a cell read on the checks arm and posture class it counted
   its rows on, DL-097) and asks the ticket for exactly what that arm needs — for `S1`,
   the structural slots the test author reads; for `S2`, a failing test a person attached — and
   the builder gets that arm's context and nothing it was not measured with (a person's test
   attached to a ticket in an `S1` cell is kept as a held-out acceptance test, never shown to the
   builder). The repository's loop switch never adds context the standard arm lacks: a factory
   brief carries the loop's overlay and lines when, and only when, its standard arm carries `+L`
   — so a loop-off standard such as `S1` is built loop-off in a repository whose loop is on. A
   ticket whose cell has no proven standard, or that lacks what the standard needs,
   stops before any spend with the missing context named (`no_proven_standard`,
   `needs_context`), **whether or not delivery is switched on**. An approver may fund a ticket
   stopped for either reason only as a **calibration build**: evented as one, stamped with its
   arm, and never able to open a pull request. A calibration build on a ticket that carries a
   person's failing test, graded also on held-out acceptance tests a second person wrote
   without seeing that test or
   the build (kept outside the builder's tree until grading), yields an `S2` row; a registered
   `S2` reading that delivers is the **forward reading** that alone promotes an `S3` ceiling.
   - **The sign-off clause and `deliver_override`.** Where ADR-0018's clause is in force, a
     ticket whose cell has a proven standard that is not a ceiling, but no active sign-off on
     that arm, class-set version and reading (item 6), stops before any spend `unsigned_cell`
     instead of being built and withheld. `deliver_override` survives only there: an approver
     may license one run's items in such a cell by name, as ADR-0018 decisions 3 and 4 bound
     it. It never lifts `no_proven_standard`, a ceiling, `needs_context`, a calibration build,
     `size_exceeds_licence` or `cell_not_licensed`. `require_signed_cell=false` removes the
     sign-off clause only, never this gate. This supersedes in part ADR-0003's amendment of
     2026-09-16 (decision 1: build and withhold, and the override of the route) and ADR-0018 as
     drafted (decision 1's build and withhold; decision 3's override of both clauses; decision
     5's "the route alone", which now means the proven standard alone). Wave 4's stream S
     re-reads ADR-0018 against this item before it merges.
   - **Size.** A ticket's size comes from story points only once the organisation's
     points-to-churn agreement has passed (item 9's validity report). Until then readiness reads
     the cell the points name and the next larger size's cell and applies the more demanding of
     the two — a cell with no proven standard is the most demanding, so either one lacking a
     standard stops the ticket **[operator: or refuse every pointed ticket `size_unknown` until
     the agreement passes]**. An `L` ticket reads the L and XL cells; XL routes `granularize`,
     so until the agreement passes every ticket pointed L stops, routed `granularize`, with the
     reason named. A ticket with no points is `unsized` and routes `human` (ADR-0025
     item 12). After the build, ADR-0025's `size_exceeds_licence` check stands.

9. **Class sets: one rule at replay and intake, held out by commit, versioned, never pooled.**
   - **The stamp.** Every row of 2.4 or later stamps `labels.taxonomy`: `global/classes@v1` for
     the global vocabulary, `<org>/classes@vN` for an organisation's set. A label table maps
     (task, version) to class, so a relabel never rewrites a stored row. The map, `/routes`,
     sign-offs and the delivery gate read one version; `cell_stats` raises `ClassSetsPooled` for
     two. `capability_class` in the cell key stays the global parent, so the federated key does
     not move.
   - **One rule.** A version's rule reads only what a ticket carries — its text, work-item type,
     component or area, labels and points, and the organisation's component names from the
     library. At intake it reads the ticket; at replay it reads the commit's linked ticket as it
     stood at the parent's date, or else the message, marked as a proxy. Changed paths, line
     counts and churn leave the rule; they stay diagnostics and ADR-0025's post-build size check.
   - **Held out by commit.** Before any class of a new version is proposed, each repository's
     replayable commits are split by `sha256("crb.split.v1|" + repo + "|" + commit)` into a
     **derivation set** and a **confirmation set** — one third and two thirds **[operator]** —
     and the split is recorded. Proposing, merging, splitting and the separation test (which does
     read replay outcomes) use derivation commits only. A version **licenses only on
     confirmation commits**, through a reading registered after it was signed; a commit that
     derived or separated a class never licenses it. A confirmation commit must also be ungraded
     under the arms of that reading's hierarchy at that apparatus, whatever class-set version
     graded it: item 2's `pool_seen` refuses it otherwise. So on a repository already measured
     at an apparatus (Wave 3 grades cobra's and click's commits under `S3` and `S1` at 2.4), a
     new class set licenses only at the next apparatus or on commits made since that
     measurement.
   - **The validity report** runs before a version may route (its costs are $0 except model
     relabelling), with thresholds **[operator]**: coverage — at least 90% of replayable commits
     fall in a named class; agreement — Cohen's κ at least 0.6 against a person-labelled sample of
     at least 50 derivation commits, at least 5 per class; stability — a model rule repeats its
     own labels at least 90% of the time; ticket consistency — where at least 20 commits link a
     ticket, the rule gives the same class from the ticket and from the message at least 80% of
     the time; **size agreement** — on at least 20 linked tickets that carry points, the tier the
     points name equals the churn tier of the merged change at least 80% of the time and names a
     smaller tier at most 10% of the time; measurability — at least 20 confirmation commits in
     each class × size cell the version routes.
   - **Two people.** A version routes nothing until its report passes and an approver other than
     its sponsor has signed it (item 10's rule). A using team proposes version N+1 as work-type
     entries; the class set becomes a DL-044 registry seam instead of a code edit. A person's
     `crb:class=` override on a ticket stays and is counted; a high override rate fails the rule.
   - **The new *Touch when* of `src/crb/core/taxonomy.py`:** "never for a new repository or
     organisation — an organisation's classes are a class-set version (ADR-0026 item 9), stamped
     `labels.taxonomy` and read on their own axis; adding, removing or redefining a GLOBAL class
     still changes the instrument: bump `src/crb/core/version.py`, add the definition
     (`tests/test_classify.py` enforces one per member) and record it in `docs/adr/README.md`."
     The index's rule that "a change to the class taxonomy must bump `APPARATUS_VERSION`" is
     narrowed to the global vocabulary in the same way.

10. **The context library: six kinds, one nomenclature, two people, measured before it reaches a
    brief** (scope: DL-087).
    - **Kinds and ids.** Every entry is a `component`, `work-type`, `decision`, `convention`,
      `pattern` or `standard`, with the id `<kind>/<slug>`. A work type is an organisation class:
      its definition, global parent, rule, example commits and test standard (the failing test a
      ticket must lead to and its structural slots; the readiness catalogue is version 1 of these
      slots). A standard names the ISO/IEC 25010 characteristic it refines, optionally an
      ISO/IEC 5055 measure, and the repository's check that evidences it; without a check it is
      advisory and counts as no evidence. Values that belong in a test, code and secrets are not
      entries.
    - **The record**: id, kind, title, a statement of at most 400 characters, scope (components
      and work types), provenance (a file at a commit, the graded rows it was learned from, or
      the person who wrote it), `proposed_by` (a person, `mined:<miner version>` or
      `drafted:<model>`), status (`proposed` → `signed` → `stale`, `retired` or `revoked`), a
      version hash, the characteristic and check for a standard or convention, and its measured
      effect or `unmeasured`.
    - **One two-person rule.** Every entry, and every class-set version, needs two different
      people: a **sponsor** who puts it forward — for a mined or model-drafted proposal, the
      person who first adopts it for signing — and an **approver** who signs it. The approver can
      never be the sponsor, and a miner or a model is never a person. The ledger is append-only
      and hash-chained, on the pattern of `crb.core.signoff` (`same_actor_refusal`, ADR-0016);
      revocation and retirement are appended; an entry mined from a file at a commit reads
      `stale` when that file changes at the repository's head and returns to Decisions.
    - **Proposed, never invented.** A registry of miners proposes entries at no model cost from
      a pinned commit: ADRs as decisions, CODEOWNERS and the directory layout as components, lint
      and formatter configurations as conventions with their check, the test layout and example
      tests as a work type's test standard, the change profile as work-type candidates with
      counts. A model may draft a statement and is recorded as its drafter. `CLAUDE.md`,
      `AGENTS.md` and `CONTRIBUTING` are read as data for a proposal and never reach a brief raw.
    - **Measured before it reaches a brief.** An entry set reaches a builder only inside an arm
      whose effect was measured: the set is frozen as `+library@<version>`, registered as an arm
      and read against the same arm without it under the look rule, inside the cell's budget. A
      set produced under item 1's mechanical conditions may be read retrospectively; a set a
      person wrote, edited or selected is read **prospectively only**, on commits after its
      signature, because a person signing today knows the history — a provenance date is not a
      knowledge date. A set is kept, or retired by the look rule or the prevention loop's harm
      clause (ADR-0020); single entries are attributed by leave-one-out only after their set is
      kept. The per-repository switch that lets kept entries into briefs is off by default.
      Showing, signing, classifying and readiness use an entry as soon as it is signed; briefs
      use it only after measurement. A library arm is usable as a standard only while every entry
      of its frozen set is signed and fresh.
    - **What a prospective reading costs in time.** A cell gains new commits at its own rate:
      cobra's `bug.fix` XS and S cells about 0.2 a month, koa's about 0.3, click's about 2.6 to
      2.9 **[measured — n = 9, 11, 6, 6, 10 and 11 commits; method: public commit dates of the
      2026-09-25 export's tasks read through the GitHub API on 2026-09-27, over the months from
      each repository's oldest mined commit to the mining date, 2026-09-13; one window, not a
      forecast; apparatus 2.0–2.2 for the task list]**. Twenty prospective commits would take
      about 7 to 8 months on click and 5 to 9 years on koa and cobra **[hypothesis — projection
      at those rates]**. Each reading states its expected duration beside its cost.

11. **The quality baseline is named, never claimed.** `crb.core.quality_model` holds one table
    from each ISO/IEC 25010:2023 characteristic to the product's checks that evidence part of it
    (by name, with when each runs), and the guide carries it:

    | characteristic | evidenced by | note |
    |---|---|---|
    | Functional suitability — correctness | belt 2 `target_green`, belt 3 `no_new_failures`; review verdicts `defect`, `regression` | completeness only as far as the tests assert; mutation strength says how far to trust it |
    | Maintainability — analysability, modifiability | belt 5 `repo_lint_clean` where the repository configures a linter; the format step; belt 6 `api_stable` (modifiability) where switched on; review verdicts `style`, `api_change` | by the repository's own rules, not ISO/IEC 5055's |
    | Compatibility — interoperability | not evidenced; named only as belt 6's argued secondary | not counted |
    | Reliability, Security, Performance efficiency, Interaction capability, Flexibility, Safety | not evidenced | F31 proposes the repository's own security scanner as a review probe |

    So the belts evidence parts of **two** of the nine characteristics **[measured — n = 9
    characteristics of ISO/IEC 25010:2023; method: each read against the belt, review-verdict and
    check definitions in the table above; apparatus n/a]**; belt 3 is regression correctness
    and counts under functional suitability only. Belts 1 and 4, the negative controls and
    mutation strength evidence the instrument's integrity, not a product quality.
    None of ISO/IEC 5055's measures is computed; one may enter only as the repository's own
    analyser run as a gate (ADR-0011), never as prose. The claims gate refuses any sentence in
    README, the guides or the pull-request body template that says code conforms to an ISO
    standard. An organisation's standard entry with a runnable check becomes a finish-gate or
    belt command on its repository; without one it is shown and signed but counts as no evidence.

12. **The abstract export carries `S3` rows at `global/classes@v1` only.** ADR-0007's allowlist
    does not move: the abstract cell has no field that could keep two arms or two class sets
    apart. Today's export sends every row of the checks arm `off` and pools sighted and blind
    rows, because mode is not in the cell key (`crb.core.federated.export_abstract` reads
    `rows_for_checks(rows, ARM_OFF)` with no mode filter). From 2.4 it sends only `S3` rows,
    stamped at 2.4, under the global parent class: blind rows and unstamped rows from before
    2.4 no longer leave. That narrows which rows leave and adds no field, so ADR-0007's ratchet
    is not engaged. Organisation class names and library entries are tenant data and never
    leave. Exporting another arm needs the ratchet ADR-0007
    names: a test change and an ADR.

13. **What each wave builds, and the first campaign.** Wave 2 builds items 1 to 8, item 9's
    stamp, and items 11 and 12: stream T writes this record first; R builds items 1 to 6, item
    9's stamp and item 12 on stream G's branch; F builds the composer, the `S1` arm and items 7
    and 8; C builds item 11. Wave 3 is one pre-registered campaign at 2.4 in the sealed posture,
    rung `r1` only, claude_code with claude-sonnet-5: cobra and click `bug.fix` XS and S; one
    reading per cell with hierarchy `S3` then `S1` under `look.v1`; `A0` and `A0+L` on the first
    16 commits of each cell's seeded order, with `learning: off` on the `A0` runs and one budget
    profile for every arm but `A0+L`.
    The loop's pair is **descriptive**: at 64 pairs an exact two-sided McNemar test at 0.05 has 80%
    power only for a net loop effect of about 13.5, 18 or 21.5 points when 15%, 25% or 35% of
    pairs are discordant **[hypothesis — power at the planned 64 pairs; method: exact
    enumeration of the binomial on discordant pairs, no sampling]**; the reading is published
    with its interval beside that minimum and changes no default. Its total cost has a mean
    of about $74 to $89 and a 90th percentile of about $81 to
    $102 **[hypothesis — projection; method: 20,000 simulated campaigns, each cell's `S3` rate
    drawn from a Beta posterior on its own sighted first attempts, `S1` at 0.5, 0.7, 0.85 or
    `S3`'s rate, the look rule's stopping over a pool of 40 commits in every cell (cobra's cells
    may hold only 25 to 35, which lowers the cost), per-attempt prices resampled
    from n = 161 priced sighted and n = 53 priced blind `r1` XS/S attempts of the 2026-09-25
    export (apparatus 2.0–2.2, host posture), harness re-runs at 10 of 177, a test-author call of
    $0.02 to $0.15 assumed, $2 to $5 for the factory rerun and timed intake]**. Wave 4 builds the
    library record, the miners, the per-work-type page, the forward reading's held-out tests and
    the class-set machinery. Wave 5 is the operator's: prospective library and `S2` readings, and
    an organisation's first class set, at the durations item 10 states.

## Consequences

**What becomes easier.**
- A cell says which context makes its changes pass, or that none is proven yet, and what to
  measure next — on one screen, per arm, with n, the interval and the look state.
- "Sure" has a stated error: at most the cell's budget, whatever is tried on it and in whatever
  phase, because every reading is registered before its first attempt and spends from one budget.
- Replay measures what manufacture sends: one composer builds both briefs, and `S1` replays the
  factory's own path against the repository's real held-out tests.
- A ticket that cannot pass is stopped before it costs anything, with the context it lacks named
  on the ticket.
- An organisation can shape its own classes and project knowledge without editing code, and every
  version and entry carries two names and its provenance.

**What becomes harder.**
- Most cells will read "no proven standard" at first. On today's rates the commit's own tests
  deliver in about half of cobra's XS readings (46% to 53%), about a fifth to a quarter of its S
  readings (21% to 26%) and fewer than one in ten of click's **[hypothesis — projection; method:
  the item 3 programme integrated over a Beta posterior on each cell's sighted first attempts —
  cobra XS 9 of 9, cobra S 10 of 11, click XS 8 of 10, click S 9 of 11 — at a pool of 40
  commits, and for cobra also at 30, where its history may end; apparatus 2.2, host
  posture]**, and `S1` can only do as well or worse. Context alone will not clear most cells
  at this builder; process, decomposition and the model are levers too **[hypothesis — inference]**.
- The gate can stop the factory: until a campaign certifies a cell, every ticket in it stops or
  runs as a calibration build that cannot deliver.
- Pools are bounded by history and by rate. cobra's whole history may hold only about 25 to 35
  qualifying commits per XS or S cell **[hypothesis — projection at the measured rate back to
  the repository's creation in 2013]**, so its later looks may never be reached; prospective
  readings on slow repositories take years (item 10).
- A new class-set version licenses only on its confirmation share of each cell's commits (two
  thirds, proposed — item 9), and each arm × builder × model needs 20 to 40 commits of its own:
  arms must stay few and pre-registered.
- Every reading needs a registration act, and the budget refuses a reading it cannot cover.

**What we must never do.**
- Pool two context arms, two class-set versions, two apparatus versions, two modes, two checks
  arms or two posture classes in one cell.
- Read a look anywhere but at 20, 30 and 40 commits of a registered reading, in its seeded order;
  count a row graded before the reading was registered; or re-read an `insufficient` arm.
- Spend more than the cell's budget, or read an arm outside a registered hierarchy.
- Let `S3` certify, let `A0` or `A0+L` license, or let a person-written context license on
  commits that person could already see.
- Give a builder context its standard was not measured with, or open a pull request from a
  calibration build; or let `deliver_override` lift a missing standard.
- License a class-set version on a commit that derived or separated it.
- Let an entry reach a brief unmeasured, unsigned, stale, retired or revoked; let one person
  sponsor and sign; or call code ISO-conformant.

**What is still open [gap].**
- No forward reading exists yet: the held-out acceptance tests of item 8 need a second person
  (Wave 4), and on slow repositories an `S2` reading takes years.
- `S1@<author>` measures one test author; another author model is another arm (item 1),
  never pooled, and needs its own commits. Authored tests are weakest where the oracle pins
  unstated values, so `S1` may lose most exactly there **[hypothesis — from the upstream
  per-class result on exact-value classes]**.
- Messages written after the code, and tests written with it, keep `A0` and `S3` optimistic
  against real tickets **[hypothesis — unmeasured]**; the linked-ticket reader of item 9 is Wave
  4's.
- The derivation/confirmation split protects the licence, not the proposer's eye: a person can
  still see confirmation outcomes from earlier readings. The two-person rule and the ticket-time
  rule limit what that person can carve; nothing removes it.
- Whether a cell may pool several repositories of one organisation is not decided; repository is
  the strongest confounder in every reading so far.

## Alternatives considered

- **Pool on digests: stamp the playbook and library digests, the finish-gate checklist,
  `harness_command` and the rules version into the arm** (the first design). Rejected: the
  loop's playbook digest changes whenever it adds a line, so an `A0+L` campaign could never be
  read as one cell — ADR-0024's objection exactly. They are provenance (item 1).
- **Freeze the loop's overlay at the campaign's start.** Rejected for `A0+L`: it measures a
  snapshot, not the loop, and value.109 asks what the loop does. A reading may still register a
  frozen overlay as its own arm.
- **Keep routing.v2's fixed bar** (16 all clean, 25 with one miss, 33 with two). Rejected: read as
  commits accrue it certifies a 0.80 cell 5.0% to 6.3% of the time (item 3) **[measured — n = 40
  draws per path, exact enumeration, no sampling; method: item 3's programme; apparatus n/a]**; a
  bar read whenever
  rows exist rewards stopping when the numbers look good, the reason ADR-0025 rejected the
  per-task mean.
- **A fresh error rate for each arm and each phase** (the first design's Phase 2). Rejected: each
  arm tested at 2.1% after an earlier arm failed adds up to 2.1% more **[measured — n = 40 draws
  per path, exact enumeration, no sampling; method: item 3's programme; apparatus n/a]**; the
  hierarchy and the budget keep one error per cell.
- **Split the budget equally across every arm that might become the standard (Bonferroni).**
  Rejected for Phase 1: a fixed sequence spends one arm's error on the whole chain, where an
  equal split would test each arm at half of it; the price is that `S1` can deliver only after
  `S3` has. Kept across phases, where no natural order exists: that is the budget.
- **Let `S3` certify.** Rejected: its tests were written with the change; the upstream `+22.9`
  was context written with sight of the answer.
- **License a class set on rows graded after its signature, with outcomes used only to merge
  classes** (the first design). Rejected: the separation test reads outcomes, so the set was
  carved on them, and re-replaying the same commits after signing repeats their outcomes. Held
  out by commit instead.
- **Read the look in ledger order.** Rejected: harness rows are re-run and appended later, so the
  commits in a look would depend on run incidents. The seeded order is fixed at registration.
- **Default an unpointed ticket to `S`, or trust points unchecked.** Rejected: points and churn
  are different units writing the same size labels; nothing has measured their agreement.
- **Single-person sign-off for a mined entry.** Rejected: the product would then sign its own
  proposals through one person, while cells already need two (ADR-0016).
- **Measure person-written library entries on replay.** Rejected: a person writing today has
  hindsight of later history.
- **Amend ADR-0007 to export `context_arm`.** Deferred, not rejected: federation is parked until
  a second organisation asks (DL-044); the arm vocabulary carries no tenant data, so it is the
  first field to add then.
- **A second bump (2.5) for the arm and the class-set stamp.** Rejected: at a bump every cell
  starts not measured, so Wave 3 would be bought twice.
- **Measure single entries directly.** Rejected: one entry's effect is below what 20 to 40
  commits can resolve **[hypothesis — power]**; sets first, leave-one-out after.
- **Keep the gate at delivery ("build and withhold").** Rejected: it spends money on work that
  cannot be delivered and reads to the ticket's author as a promise.

## Operator values

The values marked **[operator]** above are proposals until the operator fixes them. Each is one
row here. A criterion or gap line of the definition of done that states one carries
`ADR-0026 [operator]` and follows the operator's choice; `scripts/dod_check.py` refuses one that
does not, refuses a marker this table does not register, and refuses the marker once this ADR
is accepted (docs/PREVENTION.md P-229).

| item | the proposal | the words a criterion states it in |
|---|---|---|
| 3 | the first look at 20 | `of the first 20` |
| 5 | one error budget per cell of 5% (2.5% is the stricter choice) | `budget of 5%` |
| 8 | until the points-to-churn agreement passes, the more demanding of the named size's cell and the next larger one (or refuse every pointed ticket `size_unknown`) | `the more demanding` |
| 9 | a derivation set of one third and a confirmation set of two thirds | `one third` · `two thirds` |
| 9 | the validity report's thresholds | `twenty confirmation` · `20 confirmation` · `at least 90%` · `κ at least` |
