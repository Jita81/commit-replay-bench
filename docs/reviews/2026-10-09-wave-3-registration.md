# Wave 3 — the registration, prepared and not run — 2026-10-09

**Status.** Prepared, not run. No reading is registered and no run is queued. The stack stays
down until Paul Glover restarts it (Q-14). Every step in part 5 is marked "not yet run".

**Authority.** Paul Glover's decision 7 of 2026-10-09, recorded as DL-371: Q-11 (ADR-0026's
values accepted), Q-14 (the restart and the money), Q-06 (each campaign is approved with a stated
maximum) and his answer on Wave 3's reviews (decision 5). The source is
`feedback/2026-10-09-project-room-decisions.md` in the private crb-handbook repository. This
record was written against `main` at `48c25abd`. The values Paul fixed on 2026-10-11, before
any data, are at the end of part 1 (DL-375 to DL-381, and his decision 9, DL-400 to DL-405), and
part 2 is amended to the campaign record the product now keeps (DL-374), which each reading names
(DL-382).

**Claims in this record.** Nothing here is measured on a graded row. A protocol value is the one
ADR-0026 item 13 fixes. A cost is item 13's projection, or arithmetic on it. The rate of dollars
to the pound is the operator's fixed conversion (DL-379), not a market rate. Each is tagged
where it stands.

## 1. The protocol

Wave 3 is the campaign ADR-0026 item 13 fixes, which PLAN's Wave 3 section restates. This part
copies it and adds nothing. The choices it leaves open follow the table.

| what | the value | where it is fixed |
|---|---|---|
| apparatus | 2.4; rows of another version are never pooled | ADR-0026 item 13; PLAN, Wave 3 |
| posture | sealed: the builder in the sealed container, the tests in the docker sandbox. `POST /readings` refuses a replayed arm on a posture class that is not `docker/<tree>/sealed` (`invalid_reading`) | items 2 and 13; `src/crb/server/routes/readings.py` |
| rung | `r1` only | items 2 and 13 |
| builder | `claude_code` with `claude-sonnet-5`, provider `anthropic` | item 13 |
| cells | cobra and click, `bug.fix`, XS and S, process step `replay`: cobra XS and cobra S (language `go`), click XS and click S (language `python`) | item 13; PLAN, Wave 3 |
| readings | one per cell, registered before its first attempt | items 2 and 13 |
| hierarchy | `S3` then `S1@<author>`, decided in that order; once `S3` reads `insufficient`, `S1` stops. A later arm reads `waiting` while the arm before it is still being read, and `stopped` once that arm reads insufficient or undecided; neither is read toward the verdict (FZ-2) | items 4 and 13 |
| rule | `look.v1`: `deliver` at 20 of the first 20, 29 of the first 30 or 38 of the first 40 clean; `insufficient` at the third miss | items 3 and 5; the first look at 20 fixed by DL-371 |
| error budget | 5% per cell, of which `look.v1` spends 2.10%. It is a budget of error, not of money: Wave 3's money is part 2 | item 5; DL-371; HB-14 |
| descriptive arms | `A0` and `A0+L` on the first 16 commits of each cell's seeded order; they spend no error budget and never certify | items 4 and 13 |
| the loop | `learning: off` on every `A0` run; `A0+L` runs with the repository's loop switch on | items 1 and 13 |
| budget profile | one profile for every arm but `A0+L` | item 13 |
| pool | chosen by a rule blind to every outcome and frozen with its sha256 at registration; a hand-picked list is refused `pool_not_blind` | item 2; DL-097 |
| order | the seeded order, below: one order per cell, shared by every arm | item 2 |
| what counts | a commit's attempt on an arm is the first attempt reserved for it on that arm after registration, and that attempt alone decides the commit; anything else is a miss and is never run again — but a reserved row built off the reading's checks arm (or graded unsealed in its posture class) reads `scope_fault`: its arm undecided, no hit, never a miss and never a re-run (RT2B-1, P-795). A reading run halts at its first outage or environment row: its in-flight commit is a miss (reserved.v1), and its unreserved commits stay pending and are run later (PW-7). Each arm's `duplicate_commits` shows the rows of a decided commit the reading did not read; it never changes a verdict (F87-2). The rule in full, amended before step 4, follows this table | item 2; P-792 |
| attempt rule | reserved.v1; max_reruns 0; no re-run, no leave | item 2; P-792 |
| run fields | repo, kind, mode, builder, model, provider, task_ids or limit, arm, test_author (S1), learning, budget_profile, reading_id, campaign_id, max_cost_usd, qualify_first; the stop knobs outage_stop and env_stop only at 1, the default for a reading run, which halts at its first outage or environment row (PW-7); pool, executor and timeout only at the values `POST /runs` stores when a body leaves them out; an `A0+L` run's task_ids are its enrolled commits it has not reserved, in the seeded order (all, or the first of them); anything else 422 reading_run_fields, refused again at claim | item 2; P-792; DL-386 |
| treatment | pinned by the campaign's first reservation on each repository (deployment) and each arm's first (arm); served as pinned_treatment on GET /readings; a later mismatch halts the run before any build | item 2; P-792 |
| qualification | each cell's pool is mined and qualified first, at no model cost | PLAN, Wave 3 |
| the loop pair | one test on 64 pooled pairs: a pair is each of the first 16 commits of its cell's pool, and a commit pending on either arm reads against the loop; an exact two-sided McNemar test at 0.05, read once, when both arms of every cell are complete (how Q-25 is read, below); it changes no default | item 13; DL-384; DL-386; DL-402 |

**What counts (item 2, amended before step 4, 2026-10-12; P-792, DL-385).** The operator chose
to fail closed: any cancel, kill, timeout or harness failure after the reservation is a miss,
and only a refusal before it leaves a commit pending. The row above reads, in full:

A commit's attempt on an arm is the first attempt reserved for it on that arm after
registration. The worker records the reservation (`reading.reserved`) under the events write
lock, after the run's spend check and before the builder or an `S1` test author is called. The
database refuses a second reservation of the same reading, arm and commit.

That attempt alone decides the commit. It is a hit only if all of the following hold for its
own row:

- the row was written by the run that reserved it, while that run still held its claim;
- it was graded after registration, in the reading's scope;
- it is clean on every belt and not disqualified;
- it is not lint-disabled, `harness`, `outage` or gold-red;
- it is on the reading's cell, and PASS on the held-out tests where the arm needs them;
- it carries the treatment pinned by the campaign's first reservation on this repository.

Anything else is a miss and is never run again. That covers a `harness`, `outage`,
lint-disabled, gold-red, off-cell or error row, and no row once the reserving run has ended or
been reclaimed. A cancel or a kill after the reservation costs the commit.

A reading run halts at its first outage or environment row (`outage_stop` and `env_stop` are
1 on a reading run, its default; any other value is refused 422 `reading_run_fields`, and again
at claim; PW-7). The commit in flight is a miss under reserved.v1. The run reserves nothing
more, so its unreserved commits stay pending and are run later. Under the general defaults (3
and 2) one usage-limit episode would have reserved three commits and missed all three, which
alone reads `look.v1` `insufficient` **[hypothesis — argued from the code and `look.v1`'s
third-miss rule; no live episode was measured]**.

An attempt refused before its reservation is not an attempt: the commit stays pending in its
place. A reading run whose resolved checks arm differs from the reading's frozen arm halts
`reading_checks_arm_mismatch` before it reserves, and the commit stays pending; a reserved row
built off the frozen arm all the same reads `scope_fault` (`scope` `checks_arm`): the arm is
undecided with no hit, the row is never a miss, and nothing is re-run (RT2B-1). Only runs whose
bodies carry the registered fields, with the registered values, may reserve. The pool and its
order are fixed at registration. No commit leaves the pool. A look reads the prefix of decided
commits and waits at the first pending one.

The reservation's row decides its commit wherever it falls in the ledger: the reading never
reads row order. When a campaign admits a second run on a commit, the first admitted holds the
reservation and the second skips the commit (`commit_reserved`), so a row it wrote all the
same, even one written first, decides nothing. Each arm serves `duplicate_commits`: the rows of a decided
commit that the reading did not read (every row in the arm's scope, of an admitted run, but the
reservation's). It is a count for a person and never changes a verdict (F87-2).

**Why this is strictly more conservative** than the first-observed rule the row replaces
**[hypothesis — an argument from the code, not a measurement; method: the steps below,
reproduced over random worlds by
`tests/test_p792_reserved.py::test_p792_new_hits_subset_of_old`]**:

1. **Given that no other reading of the campaign enrols the commit on that arm** — true for
   Wave 3, which registers one reading per cell on four distinct cells, so no commit is in two
   pools — a campaign-admitted run must name the reading, and its arm and fields must match.
   So every built r1 attempt of an enrolled commit on an arm is reserved, and at most one
   exists. That reserved row R is exactly the old rule's "first observed attempt" for that
   commit.
2. Under the same condition, a new hit requires everything the old hit required, plus extra
   conditions: not gold-red, not harness or outage, on the pinned treatment, and ordered after
   registration. So, commit by commit, new-hit implies old-hit, whatever any old re-run would
   have returned.
3. The old rule only removes non-hits (leaves). So for every prefix length n, old hits in its
   first n non-left commits ≥ new hits in the first n enrolled commits. Likewise, new misses ≥
   old misses.
4. Therefore, under look.v1, a new deliver at 20/20, 29/30 or 38/40 implies an old deliver at
   the same look or earlier. A new insufficient can come only earlier.
5. Every hit is still an honest first attempt, so false-pass can only fall. Only power falls.

Without the condition, step 1 and step 2 fail: another `reserved.v1` reading of the same
campaign, cell and arm can reserve the same commit as well, the old rule reads that reading's
earlier miss as the first observed attempt, and this reading's reserved hit is a new hit with
no old one (`tests/test_p792_reserved.py::test_p792_conservative_needs_one_reading_per_commit_and_arm`).
The random worlds of `test_p792_new_hits_subset_of_old` add other readings' earlier rows only
within the condition: on another arm, or on the same arm in a run another campaign admitted.

The seeded order is ascending
`sha256("crb.reading.v1|" + repo + "|" + canonical cell key + "|" + commit sha)` (item 2). The
product computes it at registration and serves the pool in that order (`crb.core.reading`).

**Choices the protocol leaves open.** Each has a recommendation. Paul fixes each before step 4.

- **(a) The test author.** `S1@<author>` names the model of the deployment's test author,
  `CRB_FACTORY__TEST_AUTHOR` (`deployment_author_model`, `src/crb/server/routes/learn.py`). The
  worker refuses an author whose model is on the run's ladder, so it cannot be
  `claude-sonnet-5`. Recommended: the author the deployment names now, read at step 2. Item 13's
  projection assumes a test-author call costs $0.02 to $0.15 **[hypothesis — item 13's
  assumption, not measured]**.
- **(b) The loop switch's level for `A0+L`.** Item 1 says only "the loop switch on".
  Recommended: `config`, because item 13 exempts `A0+L` from the one budget profile, and only at
  `config` can the loop change a budget: its `budget_calibrated` lever writes
  `spend.budget_profile: calibrated` (`src/crb/core/prevention.py`) **[hypothesis — read from
  item 13's wording, which does not name a level]**. The switch's state is read first and
  restored after the last `A0+L` run.
- **(c) The pool rule.** Item 2 allows every qualified commit of the cell, or every one authored
  on or after a date the operator names. Recommended: every qualified commit, which is what an
  empty `since` gives, so no date has to be chosen.
- **(d) The one budget profile.** Recommended: `default`, named on every `S3`, `S1` and `A0`
  run. A run that names none follows the repository's profile, which the loop may change under
  (b).
- **(e) The run order.** Item 4 runs the arms in parallel and orders only the decision.
  Recommended: the product's remeasure plan (`GET /learn/remeasure`), which serves `S1`'s request
  only once `S3` delivers, so no money goes on an `S1` run that a miss of `S3` would stop. `A0`
  and `A0+L` are queued beside `S3` from the start. How far stage 1 can go is set by part 2.

One point is unchecked: whether a change the loop makes at `config` to the repository's `checks`
block moves `A0+L` rows off the reading's checks arm, so that the reading stops counting them
**[hypothesis — unchecked in the code]**. Step 6's success condition catches it, because the
reading must count each run's commits under the arm queued.

**Fixed before any data, 2026-10-11 (CRB Project room).** Paul Glover fixed these in the CRB
Project room on 2026-10-11, before any reading was registered, any run queued or any Wave 3
row written, so none was chosen knowing a result:

- **What the result decides (Q-25; DL-376).** In his words: "Continue if any cell delivers, or
  the loop's paired difference clears its registered smallest effect. Change course if no cell
  delivers but the loop or the test author moves the rate by more than noise. Stop if nothing
  moves and the sealed rate sits within noise of the lower bound of the rate taken where the
  answer was reachable. Whichever it is, the result is published with its rows in the
  repository." The registered smallest effect is one value, which every reading carries as
  `smallest_effect` (step 4; Q-28, DL-402). Q-25 reads the loop's pooled paired difference
  against it, and "a cell delivers" means a proven standard (Q-27, DL-401), as "How Q-25 is
  read", after this list, fixes.
- **When (Q-19; DL-377).** The decision is taken on Friday 6 November 2026, or when Wave 3
  reports, if that is sooner.
- **The open choices (Q-21; DL-378)**, each as recommended above:
  - (a) the test author is the one the deployment names now, `editblock:gpt-oss-120b` on
    Cerebras, checked at registration (step 2), and never the builder's own model;
  - (b) the loop runs at level `config` for the `A0+L` arm only, and the switch is put back
    after its last run (steps 5 and 10);
  - (c) the pool is every qualified commit of the cell;
  - (d) one budget profile, `default`, on every arm but `A0+L`;
  - (e) the product's remeasure plan sets the run order, so `S1` spends nothing until `S3`
    delivers.
- **The rate and what counts (DL-379).** 1.35 dollars to the pound: stage 1, £40, is $54.00,
  and the ceiling, £80, is $108.00 **[hypothesis — the operator's fixed conversion, not a
  market rate (DL-379)]**. The rate is stored on the campaign record (part 2). The
  ledger's `cost_usd` and the `S1` test author's calls count against the £80; Claude Code's own
  sessions do not. Stage 1's £40 is released (DL-381). Stage 2's £40 is released in advance, on
  a fixed rule (Q-26, DL-400, below), which replaces DL-381's "stage 2 is a new decision".
- **The freeze (Q-24; DL-375).** No new feature work until Wave 3 reports, except the pre-run
  pull request that made this record's checks the product's own.

**Decision 9, fixed before any data, 2026-10-11 (CRB Project room).** Paul Glover answered the
handbook's Q-26 to Q-30 yes, each as recommended, and R-13, before any reading was registered,
any run queued or any Wave 3 row written. The source is
`feedback/2026-10-11-project-room-decisions.md` in the private crb-handbook repository.

- **Stage 2 is released now, on a fixed rule (Q-26; DL-400).** Stage 2's £40 is released if
  stage 1 ends at its £40 line, because nothing more fits under $54.00 (part 2), with any cell
  still waiting on a look, whatever the readings say. A cell is waiting on a look while its
  reading is `look_pending`, or while its `A0` or `A0+L` arm has run fewer than its 16 commits,
  which holds back the loop pair's one look (below) **[hypothesis — the reading Claude Code took
  of "waiting on a look", flagged to Paul: it is the pre-run simulation's, which released stage 2 whenever
  stage 1 stopped at its line, and in which the descriptive arms were never complete in stage
  1]**. Claude Code files the release at step 9 and takes no further decision. No stage-1
  result can hold it back, the interim `A0` and `A0+L` tallies included. Nothing is released
  when stage 1 ends on a stop (part 2) or with the protocol complete. Under DL-381's "stage 2
  is a new decision", stage 1's result would have chosen whether to keep measuring.
- **A cell delivers when it holds a proven standard (Q-27; DL-401).** In Q-25, "a cell
  delivers" means that `S3` and `S1@<author>` both read `deliver` in that cell. `S3` reading
  `deliver` alone does not count. With four cells, the chance that some cell delivers by luck
  is 1.3–1.5% this way, against 7.5–8.1% for `S3` alone. A proven standard comes out in at most
  5.6% of simulated runs unless `S1` is nearly as clean as `S3`, so Change course or Stop is the
  likely outcome **[hypothesis — the pre-run simulation, at the host-posture priors]**.
- **How the loop's difference clears (Q-28; DL-402).** The rule is in "How Q-25 is read",
  below: the pooled test, and the pooled difference against one registered smallest effect.
- **The run order is kept (Q-29; DL-403).** Part 1's order and choice (e) stand; the readings
  are not queued ahead of the descriptive arms.
- **A reading that infrastructure decides (Q-30; DL-404).** Under the round-5 rule
  (`reserved.v1`), an outage, a harness fault, a cancel or a missing row after a commit is
  reserved counts as a miss and is never run again, and the verdict does not change. When at
  least one of the misses that make a reading `insufficient` is of that kind, so that the
  builder's patches alone did not decide it, the report labels the reading "insufficient —
  infrastructure".
  Q-25's Stop does not fire on that cell alone. Paul then decides whether to register the cell
  again on a fresh pool.
- **The builder's own account (R-13; DL-405).** The builder runs in `api_key` mode, on its own
  Anthropic API key, in a Workspace of its own whose spend limit sits at the ceiling. Paul sets
  it up and funds it. Part 5's "The builder's account" is the check before the reading runs.
  The `S1` test author runs on Cerebras (choice (a)).

**Decision 10, fixed before any data, 2026-10-12 (in chat with Claude Code).** Paul Glover
answered the handbook's Q-31, Q-32 and Q-34 yes, each as recommended, before any reading was
registered, any run queued or any Wave 3 row written: "Q-31 to Q-34 yes as you recommend, round
6 is the last". Q-33, the same answer, sets Claude Code's own token budget and is not part of
this record.

- **The formatter lever is out of Wave 3's +L treatment (Q-31; DL-410).** Before step 4,
  cobra's and click's repo config set `checks.format_step: false`. A reading pools one checks
  arm, frozen when it is registered (ADR-0024), so it cannot measure a lever that moves that
  arm. With the key set, a `format:*` rejection makes the loop fall back to `finish_gate`, which
  keeps the arm. Part 5's steps check it.
- **When no branch of Q-25 fires, Wave 3 concludes Change course (Q-32; DL-411).** The
  rule is in "How Q-25 is read", below.
- **What the readings register (Q-34; DL-412).** All four readings register
  `smallest_effect` 0.2, and each its own `hypothesis`, in one form that names the cell's
  repository and size (step 4's body, part 5). The reachable rate Q-25's Stop compares against
  is the value baseline's blind rate for the cell's size, taken in the host posture: 56.5% at
  XS (13 of 23 attempts) and 23.3% at S (7 of 30), part 4's prior **[hypothesis — a prior
  measured at apparatus 2.2 in the host posture, not at 2.4 in the sealed posture; method: the
  value baseline's headline table]**.
- **Round 6 is the last review round before the pre-run pull request merges (DL-413).**
  What it leaves is in this record's known gaps and the pull request's "What is not covered".

**How Q-25 is read (amended before step 4, 2026-10-11 and 2026-10-12; DL-384, decision 9's
DL-401 and DL-402, and decision 10's DL-411 and DL-412).** The Wave 3 pre-run red team
found that Q-25's Continue and Stop could be met or missed by a choice an analyst makes after
the data is in. These fix the statistics first, for 16 commits in each of four cells, so 64
pairs at most **[aspiration — the design ADR-0026 item 13 fixes; no pair is observed yet]**:

- **The loop pair.** One test, on the pairs of the four cells pooled. A pair is each of
  the first 16 commits of its cell's pool. A commit still pending on either arm is read
  against the loop, failing closed (NEW-1, round 5): pending on `A0` it reads clean there,
  pending on `A0+L` it reads a miss there, and `loop_pair` (`crb.core.reading`, read from
  the per-commit outcomes `GET /readings` serves) names it in `pending`, `complete` false. So no choice of which commits an arm runs, and no gap, can move b above
  c; and an `A0+L` run files its `task_ids` in the seeded order (step 6). With b the number of pairs clean under `A0+L` only and c the
  number clean under `A0` only, the test is an exact two-sided McNemar test at 0.05: p is
  twice the binomial probability of at most the smaller of b and c successes in b + c trials
  at one half, capped at 1, and 1 when b + c is 0.
- **What "clears" means (Q-28; DL-402, which replaces DL-384's per-cell bound).** The loop's
  difference is the pooled paired difference, (b − c) / n, with b, c and n counted over the
  pairs of the four cells pooled: the observed difference in clean share between `A0+L` and
  `A0`. The loop clears when the pooled test gives p < 0.05 with b above c and the pooled
  difference is at least the registered smallest effect. Continue's second clause holds when
  it clears. A difference in either direction is reported; only a positive one clears. Each
  cell's own paired difference is reported beside it, and is descriptive.
- **One smallest effect, which no code reads.** All four readings carry one `smallest_effect`, the
  registered smallest effect, 0.2, which Paul fixed on 2026-10-12 (Q-34; DL-412). The product stores
  `smallest_effect` in each reading and hashes it into the reading's id, but no code reads it.
  Claude Code computes the test and the comparison from the pairs when the loop pair is read, and
  the report shows the computation.
- **What the test can find.** The smallest difference it finds 80% of the time is 22–32 points
  after stage 1 (about 38 pairs) and 18–25 points after stage 2 (about 64 pairs). A loop effect
  smaller than about 20 points will usually be missed, so a loop that does not clear has not
  been shown to do nothing **[hypothesis — the pre-run power simulation, at the host-posture
  priors]**.
- **A cell delivers (Q-27; DL-401).** When `S3` and `S1@<author>` both read `deliver` in it, a
  proven standard. Continue's first clause holds when any cell does.
- **When it is read.** Once, when both arms of every cell are complete: each cell's `A0` and
  `A0+L` have run their 16 commits. If the campaign ends first, it is read once then, on the
  same 64 pairs with each pending commit read against the loop, and the record says how many
  were pending. Before that, an `A0` or
  `A0+L` tally is interim: the stage-1 report labels it "interim, not tested", and nothing
  rests on the difference, the stage-2 release included.
- **Noise.** Every Wilson interval this record serves or reports is descriptive (fixed-n, not
  adjusted for the sequential look): the Wilson 95% interval of clean over counted, taken as if the
  count had been fixed in advance. That includes the `ci_low` and `ci_high` that `GET
  /api/v1/readings` serves on each arm (`crb.core.reading`); `look.v1` decides a reading, never an
  interval. Q-25's "noise" is defined against that fixed-n rate. A rate moves by more than noise
  when it lies outside the fixed-n Wilson 95% interval of the rate it is compared with, in the same
  cell: the loop's `A0+L` rate against `A0`'s, the test author's `S1@<author>` rate against `A0`'s.
  For Stop the comparison is one-sided (Q-32; DL-411): the sealed rate, each cell's `A0` rate, has
  reached the rate taken where the answer was reachable when that rate's lower bound, the lower end
  of its fixed-n Wilson 95% interval, is at or below the upper end of the sealed rate's own, so a
  sealed rate above the reachable rate has reached it. The rate taken where the answer was reachable
  is the value baseline's blind rate for the cell's size, taken in the host posture where the target
  commit stays in the object store: 56.5% at XS (13 of 23) and 23.3% at S (7 of 30), part 4's tagged
  prior. Paul confirmed it on 2026-10-12 (Q-34; DL-412).
- **When no branch fires, and how the cells combine (Q-32; DL-411).** The branches are
  read in the order Continue, Change course, Stop. Continue and Change course hold if any cell
  meets them. Stop needs every completed cell to meet its test: nothing moves in it, and the
  sealed rate has reached the reachable rate, one-sided, as under "Noise". If `S1` never ran in
  a cell because `S3` did not deliver, its clause reads "did not move", and the record says
  `S1` was not run. When no branch fires, Wave 3 concludes Change course, and the record says
  which branch fired and whether it was the default.
- **In-sample switches.** The loop's config switches (`finish_gate`, `budget_calibrated`;
  `format_step` is held off, Q-31) may be learned from `A0`'s rows on the same commits the pair
  compares, so b can be inflated; the stage-1 report reads the loop pair with that caveat (K7, part
  2).
- **Order.** Within each cell, `A0` runs before `A0+L`: a cell's `A0+L` run is queued only
  after its `A0` run has ended, which narrows choice (e) and leaves `A0` queued beside `S3`
  from the start. Each run records the levers in force: its apparatus stamp's `extra.learning`
  (`auto_apply`, `changes`, `overlay`), which the stage-1 report lists per run. Under the
  fail-closed attempt rule the operator chose for item 2, which the "what counts" row now
  states (`reserved.v1`), no commit leaves, so none is replaced. If an amendment ever allows
  a replacement, it is queued in both arms.

## 2. Money

**The ceiling.** Paul Glover approved a hard ceiling of £80 for Wave 3, in two stages (decision
7, Q-14; DL-371). Stage 1 is up to £40. The rest is released only after Claude Code reports stage
1's spend and results. It is the first campaign approved with a stated maximum (Q-06). The £80
covers all of Wave 3: the readings, and the factory rerun and timed intake that PLAN's Wave 3
lists, which this record does not schedule **[aspiration — the ceiling decision 7 sets; nothing
is spent yet]**.

**The rate.** The ledger records dollars. This record converts at 1.35 dollars to the pound, the
fixed rate of the value baseline, which Q-14's own conversion uses too, and which Paul fixed for
Wave 3 on 2026-10-11 (DL-379) **[hypothesis — the operator's fixed conversion, not a market
rate: the product has no exchange-rate source, as [the value
baseline](2026-09-25-value-baseline.md) says under "What this does not say"]**. The campaign
record stores it, so the dollar lines below are the product's own.

| figure | pounds | dollars at 1.35 | source |
|---|---|---|---|
| stage 1 | £40.00 | $54.00 | Q-14 |
| stage 2, the rest | £40.00 | $54.00 | Q-14 |
| the ceiling | £80.00 | $108.00 | Q-14 |
| item 13's projected mean | £54.81 to £65.93 | $74 to $89 | ADR-0026 item 13 [hypothesis] |
| item 13's 90th percentile | £60.00 to £75.56 | $81 to $102 | ADR-0026 item 13 [hypothesis]; Q-14's "about £60 to £76" |

Stage 1's $54.00 is 61% to 73% of item 13's projected mean, so the protocol is unlikely to finish
within stage 1 **[hypothesis — $54.00 set against the projected mean of $74 to $89; method:
division]**.

**Who holds the ceiling: the campaign record.** The product holds it (DL-374, which replaces
the hand-held ceiling DL-371 described; G-957 is retired and P-775 closed). Wave 3 is one
campaign, registered once at step 4, before any reading, with an operator session:

```json
{
  "name": "wave-3",
  "ceiling_gbp": 80,
  "released_gbp": 40,
  "rate_usd_per_gbp": 1.35,
  "decision": "DL-379 and DL-381: Wave 3's £80 ceiling at 1.35, stage 1's £40 released"
}
```

- `POST /api/v1/campaigns` answers `201` with the record, its `campaign_id` (`cmp_[0-9a-f]{24}`;
  the ceiling, the release and the rate are hashed into it) and its tally: `ceiling_usd`
  $108.00 and `line_usd` $54.00. A second campaign of the same name is refused 409
  `campaign_exists`.
- Every Wave 3 run is filed under it: its `POST /runs` body carries `campaign_id` and a
  `max_cost_usd`, and an `S1` run its `task_ids` or a `limit`. Without the cap it is refused 422
  `campaign_cap_required`; an unbounded `S1` run, 422 `campaign_s1_unbounded`; an unknown
  campaign, 404 `campaign_unknown`.
- Every Wave 3 reading names the campaign: its registration body carries `campaign_id`, hashed
  into the reading's id, so it cannot be bound later or changed (DL-382). A run filed under
  the reading (`reading_id`) but not under that campaign is refused 409 `campaign_required`
  and nothing is queued, and the worker refuses at claim a run that no `campaign.admitted`
  event names. A run posted with the campaign's `campaign_id` but no `reading_id` is
  refused 409 `reading_required` when the campaign holds a reserved.v1 reading on that
  repository (`detail` `{campaign_id, reading_ids}`, nothing queued), so no run spends under
  the ceiling past the reading gates (`reading_unknown`, `reading_unsealed`,
  `reading_posture_mismatch`, `reading_run_fields`, the worker's claim checks; P-792 C19).
  Every Wave 3 body carries `reading_id` (step 6). A run of a pool commit posted with neither is not refused: it is queued outside
  the campaign and spends outside the ceiling under its own cap. A campaign's reading reads
  only rows of runs admitted under the campaign (`GET /api/v1/readings` serves
  `admitted_runs`, the campaign's count, the same for every reading of it); a row of any
  other run is invisible to it, whatever its failure kind, harness and outage included, so
  a commit is read by the attempt an admitted run reserved for it (part 1, "what counts"), and
  no run outside the campaign reserves one or makes it leave. A reading on the factory's cell names no campaign (422
  `campaign_unsupported_reading`); Wave 3 registers none.
- A run is admitted in the same transaction that queues it, and only while its cap and its
  headroom fit what is left under the line, by the tally below; otherwise it is refused 409
  `campaign_ceiling` and nothing is queued.
- A campaign with a run whose cost is not known is stopped, 409 `campaign_cost_unknown`, and so
  is one with a run that spent past its cap plus the headroom it was admitted with, 409
  `campaign_overrun`, and one with an attempt that spent and ended with no row, 409
  `unplaced_spend`: every new run is refused.
- The run's own cap is still a guard, not a guarantee: it admits an attempt while the run's
  spend plus the dearest attempt so far stays within it, so nothing bounds a first attempt that
  has no cost cap of its own (`src/crb/server/spend_cap.py`; G-938, still open). A run capped at
  $0.10 once spent $5.00 on its first attempt (P-261). The headroom below holds that overshoot.
- An `S1` replay's test-author calls are now in its spend (`Spend.with_authoring`), so its own
  cap reads them, and the campaign's tally does too (P-775).
- The free-stage chain files no run under a campaign, so it is not used: a run outside the
  campaign spends outside its ceiling, and no Wave 3 reading counts its rows. The Learn
  re-measurement queue (`POST /learn/remeasure/queue`) files none either, and the product
  refuses it for a reading that names a campaign, 409 `campaign_required` (DL-382).

**The tally.** The product keeps one running total for the campaign, in dollars, by this
rule, and `GET /api/v1/campaigns/{id}` serves it (`spent_usd`, with `authoring_usd` apart,
`held_usd`, `left_usd`, `stopped`, and the runs):

- **spent** — for every run of the campaign, its `cost_usd` (`GET /runs/{id}`), plus, for an
  `S1` run, the `cost_usd` of each `author.attempt` event in its log (`GET /runs/{id}/events/log`,
  the MCP tool `crb_run_events`);
- **held** — for every run queued or running, its `max_cost_usd` less what it has spent, plus the
  larger of the headroom it was admitted with and its headroom now;
- **headroom** — the dearest single attempt the campaign has seen, or $5.00 before the first
  (P-261); for an `S1` run, plus its commits still to run times the dearest author call seen, or
  $0.15 before the first (item 13's upper assumption).

A run is queued only when spent, held, its own cap and its own headroom together stay at or under
the stage's line: $54.00 in stage 1, and $108.00 for the campaign in all once stage 2 is
released. The product refuses any other run, 409 `campaign_ceiling`. Each run's `max_cost_usd`
is set to fit. The rule limits how many runs are in flight at once; a worker runs one at a time
(`Worker.run_forever`, `src/crb/server/worker.py`).

**Stage 1 ends** at the first of these:

- nothing more fits under $54.00 by the rule above;
- the protocol is complete: every reading is decided or its pool has ended, and every descriptive
  arm has run its fixed count;
- a stop: a cost the tally cannot know (an event or row with `cost_known: false`, or a run
  refused `spend_cap_unpriced` because a model it would call has no known price), a refused
  registration, a run whose spend passes its cap plus the headroom it was admitted with (never
  the headroom now, which its own overshooting attempt raises),
  a row of an admitted run graded unsealed in the reading's posture class, or a reserved row built
  off the reading's checks arm (each a `scope_fault`, P-795 and RT2B-1), which leaves its arm
  undecided with no hit — never a miss and never a re-run,
  or spend the tally cannot place against a run, `unplaced_spend`. An attempt with no row once
  its run has ended or been reclaimed is charged at its `build.done` cost, else at its
  reservation's hold, and the campaign stops (`crb.server.campaigns.unplaced_attempts`, F8);
  `GET /readings` serves the same attempts per arm as `settled_unrowed`. What the operator does
  then follows K4's rules below **[hypothesis — method: code reading of the tally; reproduced by
  `test_a_grade_that_raises_after_build_done_is_charged_and_stops_unplaced_spend` and
  `test_p792_tally_charges_unrowed_reservation`]**.

On a stop, Claude Code queues nothing more and cancels the runs that have not started; the
product refuses every new run of a stopped campaign whatever is queued. A running run ends at its
cap, which was set to fit.

**Not a stop: a model called from inside a build.** An attempt disqualified `nested_model_call`
is reported, and counts as a miss. The builder's container can reach one host, the model
endpoint, so a builder could call a second model whose spend its `cost_usd` never shows. The
product now refuses the claude CLI by name, and every tool input the builder emits passes a
tripwire: the endpoint `api.anthropic.com`, the path `/v1/messages`, the claude CLI run as a
command, an import of the anthropic SDK, or the name (never the value) of a model credential
variable. A hit is recorded as `network: nested_model_call: …` and the build is stopped there;
the row's kind is `protocol`, so the commit is read as missed and never re-run (F5, P-805, DL-391).
Round-1 red-teaming widened the guard: it now catches the CLI at any argument position (behind
`timeout`, inside an `os.system`/`subprocess.run` string, or written to a script and run) and
unwraps `env -S` and other command wrappers, a written script caught by the tripwire reading the
write (R1-F5-1, HON-R1-F5-1, R1-NEW-1). Round-2 red-teaming made it parse the wrappers' options
as the tools do (`env -`, `unshare`'s value options, `--prefix` abbreviations; R2-REG-1, R2-HON-1).
**Known gap:** the tripwire reads text. A call that is encoded or reached indirectly passes it,
and its spend would go unmetered: the tally holds the builder's reported cost only. Closing it
needs a proxy on the container's one allowed host that understands the API.

**What Claude Code reports at the end of stage 1**, to Paul and as a dated record under
`docs/reviews/`:

- spend per cell and per arm, in dollars and in pounds at 1.35, the author calls shown apart, and
  the total against $54.00;
- for each reading arm: commits counted, clean and missed, and its state (`deliver`,
  `insufficient`, `look_pending` with the commits still needed, or `undecided`);
- for each descriptive arm: commits run and clean, labelled "interim, not tested" (the loop
  pair is tested once, when both arms of every cell are complete; part 1), with the levers in
  force on each run;
- every attempt disqualified `nested_model_call`, by run and commit (each counted as a miss above);
- why stage 1 ended (part 2), which cells still wait on a look, and so whether
  Q-26's rule releases stage 2 (DL-400);
- what stage 2 would buy: the statement of part 4.

**Stage 2** is released in advance, on a fixed rule (Q-26, DL-400; part 1): when stage 1 ends
because nothing more fits under $54.00, with any cell still waiting on a look. Claude Code then
files `POST /api/v1/campaigns/{id}/release` with `{"released_gbp": 80,
"decision": "<the release's decision log id and words>"}`, the decision being DL-400's id and
words. The release raises the line and never passes the ceiling (409
`campaign_release_invalid`). Its line is $108.00 for the campaign in all. No decision is taken
after stage 1: the stage-1 report (step 8) shows why stage 1 ended and which cells still wait on
a look, and the release follows from those alone. It does not depend on any reading's state or
on the interim difference between `A0` and `A0+L`, and the loop pair is tested only as part 1
says.

**Assumptions.** The ceiling is held against the ledger's `cost_usd`, the cost the builder
reports, and the `S1` test author's calls, not against the provider's bill. Claude Code's own
sessions (this one, the campaign's and the reviewer's) are not counted against the £80. Both
were confirmed by Paul Glover on 2026-10-11 (DL-379).

### Known gaps (recorded before step 4)

The Wave 3 pre-run red team found these, and its triage records them as known gaps rather
than fixes (DL-384). Each is recorded here with why it is accepted and what the campaign does
about it:

- **K1, red-once.** RED runs once (`crb.core.qualify`), and the flaky set is never compared
  with `red.failing`. A flaky target can only add misses, or a clean that the gold control and
  witness would also see. Step 3 records an audit that `red.failing ⊆ baseline_failing − flaky`
  for each pool commit, and the step-3 amendment notes its result.
- **K2, author spend.** `DbEventSink` swallows write errors (`src/crb/store/events.py`), so an
  `author.attempt` cost can go missing. Each author call is at most $0.15 by item 13, and the
  headroom holds it **[hypothesis — item 13's assumption, not measured]**. The bias is toward
  under-counting.
- **K3, the author's price.** Step 2's success condition gains "and `<author>` has a known
  price". Otherwise the run is refused `spend_cap_unpriced`, which is already a stop.
- **K4, an orphaned container.** Only a hard worker death orphans a paid container: SIGTERM
  drains, and `keep_patch` never raises. Operator rules for the campaign: no `kill -9` during
  it, and a check for orphaned builder containers before resuming after a crash.
- **K5, cache writes.** `Pricing` (`src/crb/builders/budget.py`) has no cache-write rate, so
  cache creation is priced at the input rate: an under-count of about 3% **[hypothesis — the
  red team's estimate; method: Pricing in src/crb/builders/budget.py read against the
  published rates]**. It cannot flip a verdict, because the ceiling is held against `cost_usd`
  (DL-379).
- **K6, residuals.**
  - Once the builder is kept from calling a model inside its container (F5), a nested `claude`
    call by an obfuscated route would still go unmetered; an API-aware proxy to catch it is out
    of proportion.
  - Pre-2.4 history — the 2026-09-25 export, the Jita81/cobra pull requests — cannot be erased,
    but it cannot bias a pool that holds every qualified commit by rule (choice (c)) and is
    frozen.
  - The code half of Wilson and of treatment order is not fixed in code; the labels and the
    order in part 1 ("How Q-25 is read") cover it.
- **K7, what `reserved.v1` leaves open (P-792; DL-385).** Round 5's per-channel residuals,
  accepted because each costs power or information, never an honest first attempt:
  - **C6, information.** Side channels are closed as a lever, not as information: an
    attempt's outcome is still visible early (events, `docker ps`). After the reservation
    the operator can only abandon, which is a miss, and the pending prefix stays visible.
  - **C14, curation.** Unchanged: the pool and its order are fixed at registration and
    nothing leaves after it. Curation before registration is the review's job, and the pool
    is every qualified commit by rule (choice (c)).
  - **C18, the requalify stall.** A commit whose qualification is revoked after registration
    stays pending, and its reading stalls at that prefix until it is qualified again: a
    stall that cannot be skipped, so a cost in power and not a lever.
  - **C3, binary bytes.** A builder binary swapped at the same path keeps the treatment's
    digest. The bytes belong to the sealed posture, not to P-792.
  - **Forward and legacy readings.** A forward reading (`POST /readings/forward`) reads
    under `reserved.v1` only when its body asks for it, and a reading registered before this
    amendment keeps the first-observed rule; `GET /readings` serves each on the old rule
    with `attempt_rule` `first_observed.v0` and `p792` "open on this rule". Wave 3 registers
    neither.
  - **NEW-1, `A0`'s subset (round 5).** Only the loop arm `A0+L` is held to the seeded
    order. An `A0` run may still file a chosen subset of its first 16, and a descriptive
    tally counts the commits observed, so `A0`'s interim rate, the rate Q-25's noise clauses
    compare against, can rest on chosen commits. The loop pair cannot: every pair is read,
    and a pending one reads against the loop. Pinning `A0` too is a refusal at submit whose
    fixtures need a deterministic seeded order; it is left for after the freeze (Q-24), and
    the stage-1 report states each descriptive arm's counted commits beside its rate.
  - **The CLI's file readings.** `crb reading register` writes only `readings.jsonl` under
    the first-observed rule: no worker reads it, nothing reserves against it and
    `GET /readings` does not serve it, so nothing marks it as on the old rule. It writes the
    `--checks` arm it is given and compares it with neither the loop's overlay nor the
    repository's block, so it is never refused `reading_checks_overlay` (RT2B-2). Wave 3 never
    uses it; its readings are registered through `POST /readings`.
  - **The loop's config switches are learned in-sample.** The loop's playbook lines are held
    out by task and taught only by older commits (ADR-0026 item 7), but its config family —
    `finish_gate`, `budget_calibrated` (`format_step` is held off, Q-31) — has no held-out
    rule: the register reads every ledger row of the repository (`register_for`,
    `src/crb/server/prevention_state.py`), `A0`'s rows on the paired commits included, and a
    switch it throws applies to every later `A0+L` run. Since a cell's `A0` runs before its
    `A0+L` ("Order", part 1), a pair's `A0+L` attempt can be built with a switch learned from
    its own `A0` attempt. The bias can only favour b over c **[hypothesis — argued from the
    code, not measured]**. Time-ordering the switches or excluding the pool's rows from the
    register is a change to the loop, out of proportion under the freeze (Q-24); the loop
    pair is descriptive (ADR-0026 item 13), and the stage-1 report states this beside it and
    lists the config changes in force on each `A0+L` run (`extra.learning`, as "Order" asks).
  - **Power, the cost of failing closed.** An honest kill, outage, harness row or
    gold-control timeout after the reservation is a miss, and `look.v1` reads
    `insufficient` at the third miss, so an infrastructure fault rate f scales the chance of
    a deliver at 20 by about (1 − f)^20 **[hypothesis — arithmetic on look.v1; f is not
    measured]**. The claim checks refuse a dead login or a revoked credential before any
    reservation, a reading run halts at its first outage or environment row (`outage_stop` and
    `env_stop` 1, PW-7), so one episode costs at most the commit in flight, and `GET /readings` serves
    `settled_unrowed` per arm, so a fault-driven `insufficient` can be told apart.
  - **TOFU stalls.** The campaign's first reservation on a repository pins its treatment on
    first use: a rebuilt image, a `RepoConfig` edit, another executor or a changed worker
    environment afterwards halts every later reservation there
    (`reading_treatment_mismatch`, naming the half and the fields that differ) until it is
    restored or a new reading is registered. On `A0+L` the arm's pin holds the loop's switch
    level and a digest of a person's acts on the loop's chain — a veto-revert
    (`POST /learn/changes/{id}/revert`) and a link (`POST /learn/links`) — so a level edit, a
    veto or a link made between `A0+L` runs halts that arm the same way (C7); the loop's own
    applies and retires are the treatment and do not. Operator rule: from the first `A0+L`
    reservation on a repository until the campaign reports, no one edits the loop's level,
    vetoes a change or links a record on that repository.
  - **C19, information.** A reading counts only rows that carry its own reservation, so no
    reading counts another's rows, but one reading's rows stay visible beside another's:
    information without a lever.
  - **Lint off never delivers.** A reserved row graded with the lint belt switched off is a
    miss, so a reading whose repository's lint is off can never deliver; registration and
    submit refuse it first (`lint_disabled`, P-796). Conservative.
  - **F8's stop on row-less attempts.** An attempt with no row once its run has ended or
    been reclaimed is a miss for its reading and stops the whole campaign
    (`unplaced_spend`, part 2), an honest fault included: the campaign waits for the
    operator, who reads `settled_unrowed` and follows K4's rules.

## 3. The reviews

**The reviewer.** Claude (Claude Code, model `claude-opus-5-5`) reviews Wave 3's clean blind
patches. Paul Glover gave Claude the task (decision 7, his answer on Wave 3's reviews; DL-371).
Claude reviews in a fresh session, separate from the builder's and from the session that runs the
campaign, as that answer asks.

**What it reviews.** Every clean row of the blind arms — `A0`, `A0+L` and `S1@<author>` — that a
reading counts. `S3` is sighted and is not reviewed.

**A forged Go pass: what is closed and what is not.** The round-2 red team found that a non-test
Go source can make `go test -json` report the target tests passed when they never ran, and belt 2
graded that patch clean (F4-GO-TEST2JSON-SPOOF, high; P-804). Grading now disqualifies a touched
non-test file in a Go repository that starts printing the testing package's event lines, frames a
summary line with its `\x16` byte, or exits past its `os.Exit(0)` guard. It reads a `.go` source, a
`//go:embed` data file and a cgo or assembly source alike, with string escapes decoded
(REDFIX-REGRESS-HONESTY-R1-1). All five forgeries that graded clean are now disqualified, and no
commit in cobra's history trips the scan **[measured — n = 5 forgeries, and 889 non-test Go file
versions (42 distinct files) and 492 versions of 59 other files across cobra's 992 non-merge
commits; method: P-804's tests run with each fix reverted and restored, and the shipped scan over
every non-merge commit; apparatus n/a, the product's own grader]**. It reads text: a forgery that
assembles the text from pieces, or stores it encoded and decodes it at run time, still passes it.
So a clean cobra row still rests on this review as well as on the belts, and the review reads any
non-test change in a Go package that prints or exits, its embedded, cgo and assembly files
included.

**How a verdict is filed.** `POST /api/v1/reviews`, as an operator, with the row's
`grade_row_hash`, a statement, the findings, `mergeable`, and `patch_sha256` from
`GET /api/v1/grades/{row_hash}/patch`, so each verdict is anchored to the patch that was read. The
reviewer is the account that files it, so Claude files under an account of its own that Paul
creates, and each statement begins "Reviewer: Claude (Claude Code, claude-opus-5-5), tasked by
Paul Glover (DL-371)". The MCP server offers no tool that files a review: it calls filing one a
human act (`crb_reviews` only reads them).

**The scale.** The scale of the value baseline's 13 verdicts ([the value
baseline](2026-09-25-value-baseline.md), its headline table and "Clean is not working")
**[measured — n = 13 reviews; method: each review's headline verdict, as the value baseline
records it; apparatus 2.0–2.2]**. A review's headline verdict is `ok`, `defect`, `regression`,
`api_change`, `style` or `not_reviewed`, derived from its findings, most severe first
(`crb.core.review.derive_verdict`). `mergeable` is the separate answer to "would a maintainer
merge this as-is", and a regression is never mergeable. Who wrote those verdicts is being
corrected in PR #80, still open; this record cites only their scale.

**Paul's 10.** Paul reviews 10 of the clean blind patches himself. They are drawn once, after
the campaign's last run has ended and Claude has filed a verdict on every clean blind row a
reading counts **[aspiration — the draw decision 7 asks for; not yet made]**. The draw is salted
with a word Paul chooses and sends only then. It is recorded in the decision log with the draw.
Without that salt the 10 would be computable from the commits in advance, so the reviewer could
know which of its verdicts Paul will check:

1. order the commits that have at least one clean blind patch by ascending
   `sha256("crb.wave3.review.v1|" + salt + "|" + repo + "|" + commit sha)`, both repositories
   together;
2. walk them in that order and take one patch from each, from the first of `A0`, `A0+L` and
   `S1@<author>` that has one, until 10 are taken;
3. if fewer than 10 commits qualify, walk again for a second patch from each, in the same arm
   order; if there are fewer than 10 patches in all, take them all.

**Blinding and order.** Claude's session reads no review before it files its own, and Claude files
first. Paul then files his 10 without reading Claude's verdicts on them: he reads each patch from
`GET /api/v1/grades/{row_hash}/patch`, which serves the patch alone. The latest review of a row is
the standing one (`crb.core.review`), so Paul's verdict stands on those 10, and the headline is
partly a person's, as decision 7 asked. Both records stay in the hash-chained review store.

**The agreement.** On Paul's 10, Claude Code reports these **[aspiration — the measures decision
7 asks for; not yet computed]**:

- on `mergeable`, the primary measure: the share on which Paul and Claude agree, with its Wilson
  95% interval, descriptive (fixed-n, not adjusted for the sequential look), and Cohen's κ with a bootstrap percentile interval (10,000 resamples from a fixed
  seed; resamples where κ is undefined are counted and reported);
- on the headline verdict, the secondary measure: the same two figures over the six verdicts.

At n = 10 both intervals are wide, and the report says so plainly: 9 agreements of 10 give a
Wilson 95% interval of 59.6% to 98.2%, descriptive (fixed-n, not adjusted for the sequential
look) **[hypothesis — an illustration of the width at n = 10, not
a result; method: the Wilson score interval]**. The agreement is a first look at whether Claude's
verdicts can stand in for a person's, not a measure of it.

## 4. The stage-2 statement

Before stage 2, the registration states how many clean blind patches it expects to review and
what precision that buys (Q-14). Claude Code fills in this template from stage 1's results and
adds it to this record in an amendment commit.

**The expected number.** Summed over the cells c and the blind arms a:

```text
E = Σ_c Σ_{a ∈ {A0, A0+L, S1@<author>}}  N(c, a) × p̂(c, a)
```

N(c, a) is the number of commits arm a will have run in cell c by the campaign's end: the fixed
count for `A0` and `A0+L`; for `S1`, the commits its reading will read, up to 40, fewer if a look
decides or the pool ends, and none if `S3` does not deliver. p̂(c, a) is the arm's clean
first-attempt rate in stage 1. Where stage 1 has no rate for an arm, p̂ is the value baseline's
blind rate for the size: 56.5% at XS (13 of 23) and 23.3% at S (7 of 30) **[hypothesis — a prior
measured at apparatus 2.2 in the host posture, not at 2.4 in the sealed posture; method: the
value baseline's headline table]**.

**The precision it buys.** The half-width, in points, of the Wilson 95% interval on the share of
reviewed patches judged mergeable, at n = E, an interval that is descriptive (fixed-n, not
adjusted for the sequential look):

```text
h = z / (1 + z²/n) × √( p(1 − p)/n + z²/(4n²) ),   z = 1.96
```

Here p is the share judged mergeable in stage 1's reviews, else the value baseline's 4 of 13
(30.8%), and beside it p = 0.5, the widest **[hypothesis — a prior from the value baseline's
headline table, n = 13 reviews, apparatus 2.0–2.2]**. The table is arithmetic on the formula, not
a result.

| n reviewed | half-width at p = 0.308 | half-width at p = 0.5 |
|---|---|---|
| 10 | 24.9 points | 26.3 points |
| 20 | 18.8 points | 20.1 points |
| 30 | 15.7 points | 16.8 points |
| 40 | 13.8 points | 14.8 points |
| 51 | 12.3 points | 13.2 points |
| 60 | 11.4 points | 12.3 points |
| 80 | 9.9 points | 10.7 points |
| 100 | 8.9 points | 9.6 points |

The interval treats each patch as independent. `A0` and `A0+L` patches of one commit are paired,
so it is narrower than the commits alone support **[hypothesis — unmeasured; the value baseline
says the same of attempts and tasks]**. Like every Wilson interval this record serves or
reports, it is descriptive (fixed-n, not adjusted for the sequential look).

**A worked example.** From the descriptive arms alone, with no `S1` patch and the baseline's
rates: E = 2 arms × 2 cells × 16 commits × 0.565 at XS, plus the same × 0.233 at S, which is
about 51. The share judged mergeable would then be known to about ±12.3 points at p = 0.308, or
±13.2 at p = 0.5 **[hypothesis — an illustration; method: the formulas above with the value
baseline's priors; the real figures come from stage 1]**.

```text
Wave 3 — the stage-2 statement — <date>
Stage 1 spent $<s> (£<s / 1.35>) of $54.00, author calls included; see <stage-1 record>.
Clean blind patches expected for review by the campaign's end: E = <E>
  per cell and arm: <cell> <arm>: N = <N>, p̂ = <p̂> (<stage 1 | value baseline>)
Precision bought: the share judged mergeable to ±<h> points (Wilson 95%, n = <E>, p = <p>;
  descriptive: fixed-n, not adjusted for the sequential look), ±<h at p = 0.5> points at worst. Paul's 10 give the agreement as in part 3.
Stage 2 asks for up to $<t> (£<t / 1.35>); the line becomes $108.00 for the campaign in all.
```

## 5. The steps after the restart

In order. Each is **not yet run**. Claude Code runs a step only on the stack Paul has restarted,
and stops and reports at the first step whose success condition fails.

| # | step | who and how | success condition | state |
|---|---|---|---|---|
| 0 | restart the stack on merged `main` | Paul, by handbook page 08's steps; the container runtime is colima, so step 7 there is `colima start` (HB-14). The order and the sealed settings are DEPLOYMENT §1.1's: `source ~/crb-stack/env.sh` before `crb migrate`, the UI rebuilt before `crb doctor`, the worker on `--executor docker`; with both processes stopped across a migration (§6.1) | `crb doctor` has no `fail`; `/health` reads ok once the builder's login is verified, and the worker is up | not yet run |
| 1 | confirm the instrument | Claude Code: `crb_version` (MCP) or `GET /version`; `GET /api/v1/repos`; then the builder's-account check below (R-13) | apparatus `2.4`; the repositories `cobra` and `click` listed [hypothesis — the names the 2026-09-25 export used]; the check passes, and the login's source label and fingerprint are recorded here | not yet run |
| 2 | fix the test author, choice (a) | Claude Code reads `raw.factory.test_author` from `GET /api/v1/settings` (admin); if it is empty or names `claude-sonnet-5`, Paul sets `CRB_FACTORY__TEST_AUTHOR` and restarts the worker | a `builder:model[:provider]` whose model is not `claude-sonnet-5`; its canonical model recorded here as `<author>`, and `<author>` has a known price (else an `S1` run is refused `spend_cap_unpriced`, a stop; K3, part 2) | not yet run |
| 3 | mine and qualify each repository, at no model cost | the Posture panel at `/repos/cobra` and `/repos/click` ("Qualify for this posture — no model spend"), or `crb_start_run` with `{"kind": "mine", "repo": "cobra"}` then `{"kind": "qualify", "repo": "cobra"}`, and the same for click. The parameters are pinned, as values the step-3 amendment records: each mine and qualify body as sent (`pool`, `limit`, `max_candidates`, `ref`, and no `task_ids`), and the `since` and `taxonomy` step 4's bodies leave out (empty: every qualified commit, choice (c), and the global vocabulary); none changes after step 3. From then on: no label run, CLI label edit or 2.4 replay on cobra or click between step 3 and the end of step 11, but the runs step 6 files under the campaign | each run `succeeded` with a `cost_usd` of 0; `GET /api/v1/repos/<repo>/posture` shows `executor` `docker`, a `posture_class` of `docker/<tree>/sealed` and an empty `stale_reason`; each cell holds at least 20 qualified `bug.fix` commits, the first look, and each cell's count is noted here. The step-3 amendment records, for each cell, the qualified-set sha256 (its qualified commits in seeded order, hashed as `pool_sha256` is) and where each label came from (classifier or human), and the result of K1's audit (part 2) | not yet run |
| 4 | register the campaign, then the four readings | Claude Code, over HTTP with an operator session (`POST /api/v1/auth/login`, then `X-CSRF-Token` from the `crb_csrf` cookie, `__Host-crb_csrf` under TLS): first `POST /api/v1/campaigns` with part 2's body, then `POST /api/v1/readings` for each reading; no screen and no MCP tool registers a reading, and `crb reading register` writes only a local file. The body is below; it states the `hypothesis` and the `smallest_effect` and names the campaign (`campaign_id`), so the campaign comes first (DL-382). A reading registers only on a sealed deployment, the builder included: `CRB_SANDBOX__EXECUTOR` and `CRB_BUILDER__EXECUTOR` both `docker` (DL-373). Before the first registration, Claude Code records here, for cobra and for click, the loop's switch and the changes in force — `switch`, `overlay` and each entry's `change` from `GET /api/v1/learn/register?repo=<repo>` — the state step 10 restores; and checks that each repository's own `checks` block sets `format_step: false` (`GET /api/v1/repos/<repo>`, DL-410), setting it with `PUT /api/v1/repos/<repo>` and `{"checks": {"format_step": false}}` if it does not | `201` for the campaign, with `campaign_id`, `ceiling_usd` 108.00 and `line_usd` 54.00. `201` for each reading, with `reading_id`, the campaign's `campaign_id`, `attempt_rule` `reserved.v1`, `max_reruns` 0 and `budget_profile` `default` (part 1's attempt rule; a body naming another rule or re-run count is refused 422 `validation_error`), the `pool` in seeded order, `pool_sha256`, `pool_rule`, and the `pool_posture_id` and `pool_qualifications` the pool is pinned to (its commits' qualification records from step 3, never the miner's `gold_clean`; P-797); `GET /api/v1/readings?repo=<repo>` lists each with `pool_drift` `[]`, its cell's budget spent at 2.10% of 5%. Each reading's `checks_arm` reads `off`, the arm of the repository's own `checks` block; a reading on any other arm stops the campaign before any spend. A refusal (`campaign_unknown`, `lint_disabled`, `reading_checks_overlay`, `pool_seen` — under `reserved.v1`, any 2.4 replay row on a pool commit or its change, under any arm or test author, P-797 — `budget_spent`, `pool_not_blind`, `invalid_reading`), or a reading served with a `pool_drift` other than `[]` (`state` `undecided`: a pool commit relabelled out of its cell, or a pinned record missing or not qualified, P-797), stops the campaign before any spend; `lint_disabled` (`detail` `{repo, reason}`, nothing written) answers any registration while the repository's lint is switched off, and a `reserved.v1` reading hashes the repository's lint configuration as `lint_digest` (P-796). `reading_checks_overlay` (`detail` `{overlay_arm, repo_arm}`, nothing written) answers a registration while the loop's overlay moves the repository's checks arm off its own block's, so the precondition above did not hold: a reading frozen then would rest on a loop change (RT2B-2). On an unsealed deployment `invalid_reading` names what is unsealed in its `detail`: both executors, `{sandbox_executor, builder_executor}`, when the sandbox is on docker and the builder on the host; the posture class alone, `{posture_class}`, when the sandbox is not on docker, because that refusal comes first. A `409` `reading_exists` (`detail` `{reading_id}`, nothing written, nothing spent) answers a reading already registered, a retried request under any second or actor: it is a retry, not a stop; read the reading back with `GET /api/v1/readings?repo=<repo>`. The campaign id, the reading ids and the pool sizes are added here in an amendment commit | not yet run |
| 5 | turn the loop on for `A0+L`, choice (b) | Paul or Claude Code: the switch on the Learn page, or `PUT /api/v1/learn/switch?repo=<repo>` with `{"auto_apply": "config", "reason": "Wave 3, the A0+L arm (ADR-0026 item 13; DL-371)"}`; the state before is the one recorded at step 4 | the Learn page reads `config` for cobra and for click | not yet run |
| 6 | queue the runs, cell by cell, under part 2's rule | Claude Code, after the builder's-account check below passes at the start of each session, `crb_start_run` (`POST /api/v1/runs`), which posts the body unchanged; runs are queued with `POST /runs` only: `POST /api/v1/learn/remeasure/queue` files no run under a campaign, so the product refuses it for these readings (409 `campaign_required`). Every body carries `"reading_id": "<the cell's reading>"`, `"campaign_id": "<the campaign>"` and `"max_cost_usd": <cap>`; a body without `campaign_id` is refused 409 `campaign_required` when it carries `reading_id`, and is otherwise queued outside the campaign, and the reading never sees its rows, whatever their failure kind; a body with `campaign_id` but no `reading_id` is refused 409 `reading_required` when the campaign holds a reserved.v1 reading on that repository (`detail` `{campaign_id, reading_ids}`, nothing queued) — every body here carries `reading_id` (DL-382; P-792). **`S3`**: the cell's request from `crb_remeasure_plan` (`GET /api/v1/learn/remeasure?repo=<repo>`; nothing queued), plus those three and `"budget_profile": "default"`; a reading the plan lists with `checks_arm_moved` `{frozen, current}` has no request, because its run would halt `reading_checks_arm_mismatch`, so the repository's frozen checks arm is restored or the stage ends (RT2B-1). **`A0`**: `{"repo": "<repo>", "kind": "blind", "builder": "claude_code", "model": "claude-sonnet-5", "provider": "anthropic", "task_ids": [the first 16 of the reading's pool], "learning": "off", "budget_profile": "default", "reading_id": "<reading>", "campaign_id": "<campaign>", "max_cost_usd": <cap>}`. **`A0+L`**: the same with no `learning` and no `budget_profile`. `A0+L` files its `task_ids` in the seeded order: the commits of the `A0` body it has not reserved yet, first to last, or the first of them; a subset such as `A0`'s misses, another order or a commit outside the first 16 is refused 422 `reading_run_fields` (`detail.fields` `["task_ids"]`, nothing queued), and again at claim (NEW-1, round 5). **`S1`**: its request from the remeasure plan once `S3` delivers, with its `task_ids` or `limit`, plus those three and `"budget_profile": "default"`. Re-filing a run never re-rolls, because commits already reserved are skipped (`run.task_skipped commit_reserved`). No body names `outage_stop` or `env_stop` other than 1: a reading run halts at its first outage or environment row, its in-flight commit a miss (reserved.v1) and its unreserved commits pending, run later by a re-filed body; any other value is refused 422 `reading_run_fields`, and again at claim (PW-7). Before each run, item 5 of the builder's-account check below. Stop between tasks, never mid-attempt, because a cancel after a reservation costs the commit | each run is admitted (`201`) or refused before it is queued (`campaign_ceiling`, `campaign_cost_unknown`, `campaign_overrun`, `unplaced_spend` — the campaign is stopped, P-798 — `campaign_arm_in_flight` — a run of the same arm still live on one of its commits, F87-2 — `campaign_cap_required`, `campaign_s1_unbounded`, `campaign_required`, `campaign_unknown`, `reading_required`, `reading_unknown`, `reading_run_fields` — a field or value the reading does not register, P-792 — `reading_unsealed`, `reading_posture_mismatch`, `lint_disabled` — the repository's lint switched off, P-796 — `pool_drift` — the reading's pool moved since step 4, P-797); a queued run whose repository's lint is switched off, or whose reading's pool drifts or whose live posture is no longer the reading's `pool_posture_id`, after submit ends `failed` before anything is reserved (`system/run.refused`, `code: lint_disabled` or `pool_drift`), its commits still pending; a reading run whose resolved checks arm differs from the reading's frozen arm halts `reading_checks_arm_mismatch` before it reserves (`system/run.halted`, `detail` `{frozen, run}`), and the commit stays pending; an admitted run ends `succeeded`, or `failed` with `stopped_code: spend_cap`, or `failed` at its first outage row (`system/run.outage_stop`) or environment row (`system/run.environment_stop`) with one reserved commit missed and the rest pending (PW-7); its rows carry the arm queued, at rung `r1`, apparatus 2.4, in the sealed posture; each counted row carries `reservation` and `treatment` labels; `GET /api/v1/readings` counts the run's commits under that arm — only rows of runs the campaign admitted count, and `admitted_runs`, which every reading of the campaign serves, rises by one for each run the campaign admits — and `GET /api/v1/campaigns/{id}` lists the run; `pinned_treatment` is served after the first run on each repository | not yet run |
| 7 | read the tally | Claude Code, after each run: `GET /api/v1/campaigns/{id}` (`spent_usd`, `authoring_usd`, `held_usd`, `left_usd`, `stopped`); `GET /api/v1/runs/{id}` and `crb_run_events` only to place a figure against a run | `stopped` is `null` while the campaign runs, and spent and held stay at or under the stage's line; otherwise part 2's stop, which `stopped` serves as `{code, message, run_ids}` | not yet run |
| 8 | report stage 1 | Claude Code, when stage 1 ends (part 2) | Paul has the report and part 4's statement; the report says why stage 1 ended and whether Q-26's rule releases stage 2; the record is committed under `docs/reviews/` | not yet run |
| 9 | stage 2 | Claude Code, on decision 9's fixed rule (Q-26; DL-400): when stage 1 ended at its line with any cell still waiting on a look, it files `POST /api/v1/campaigns/{id}/release` (part 2), with no further decision; then the builder's-account check below, and step 6 resumes with the line at $108.00. When stage 1 ended on a stop or with the protocol complete, nothing is released | the release answers `200` with the campaign and is filed before any stage-2 run is queued; `GET /api/v1/campaigns/{id}` reads `line_usd` 108.00 | not yet run |
| 10 | restore the loop switch | Paul or Claude Code, after the last `A0+L` run | the switch reads the state recorded at step 4 | not yet run |
| 11 | the reviews | Paul creates the reviewer's account; Claude reviews in a fresh session (part 3); then Paul sends the salt and Claude Code draws his 10; Paul files his | a review on every clean blind row a reading counts; Paul's 10 filed after Claude's; the agreement reported with its intervals | not yet run |

**The builder's account (R-13; DL-405).** The builder runs on its own Anthropic API key, in a
Workspace of its own whose spend limit sits at the ceiling (the default Workspace takes no
custom limit). Paul sets it up and funds it. Claude Code runs this check at step 1, at the start
of each session of step 6, and before step 9 resumes step 6, and item 5 before each step-6 run,
and queues nothing until it passes. It reads no credential to do so: not `~/crb-stack/env.sh`, not the secrets directory,
not a keychain.

1. **The auth mode.** `GET /api/v1/builders/logins`, with the operator session: the
   `claude_code` item marked `default: true` reads `auth` `api_key` and `state` `verified`,
   within its `ttl_s`. The route serves a source label (`env`, `secrets_file` or `keychain`)
   and a fingerprint of at most 4 characters, never the token. Both are recorded at step 1, and
   a later check that reads another fingerprint is a stop. When the verification is older than
   `ttl_s`, `POST /api/v1/builders/claude_code/login/verify?auth=api_key` verifies it once: one
   no-tool Haiku turn, billed to the builder's Workspace and outside the campaign. In `api_key`
   mode the CLI runs with `--bare` and authenticates with the key alone, so a run cannot fall
   back to a subscription login (`src/crb/builders/claude_code.py`).
2. **The bodies.** No step-6 body carries a `builder_config`, so every run takes the
   deployment's default auth. A body that sets `builder_config.auth` is not filed.
3. **The account.** Before step 4, Paul confirms in the Anthropic Console that the key's
   Workspace is the builder's own, and names its spend limit, which is recorded here. The
   product cannot read the Workspace or its limit.
4. **Heavy work stays off it.** While a reading's run is queued or running, nothing else spends
   on the builder's key. No run outside the campaign calls `claude_code` on this stack. Claude
   Code's own sessions, workflows and subagents run on Paul's subscription login, never on the
   builder's key, which Claude Code never sets or reads. The `S1` test author runs on Cerebras
   (choice (a)), on an account of its own.
5. **Before each run (PW-7).** The builder's provider is not at its usage limit, and no other
   session spends the builder's account while a reading run is queued. The product serves no
   usage-limit state (a usage-limit refusal is not recorded on the login), so Claude Code reads
   the last reading run's end (`GET /api/v1/runs/{id}`): when it stopped
   `system/run.outage_stop`, nothing is filed until Paul confirms in the Anthropic Console that
   the Workspace is under its limit. And no session, workflow or subagent of Claude Code's is
   running on the builder's key (item 4). A run that halts all the same costs its in-flight
   commit (a miss); its unreserved commits stay pending and are filed again.

Its known gaps:

- **No product refusal.** The product does not refuse a reading's run in `cli` mode, so the
  check above is the only guard. In `cli` mode the builder would share Paul's subscription
  allowance with Claude Code's sessions; in the 2026-09-25 export, 240 of 518 rows were the
  builder's usage limit **[hypothesis — the pre-run red team's count over that export, n = 518
  rows]**.
- **Two processes.** `GET /builders/logins` reads the API process's default auth, and the
  worker resolves its own from its own environment. Both are started from the same `env.sh` at
  step 0, so they agree **[hypothesis — DEPLOYMENT §1.1's start order; the worker's auth mode is
  not served]**.
- **The limit can fire before the line.** The tally prices cache writes at the input rate,
  about 3% under (K5, part 2), and the login verifications are billed outside the campaign. A
  Workspace limit of exactly $108.00 could be reached while the tally reads about $105, and the
  builder's next call would then fail. Under the round-5 rule, the run's reserved commit would
  count as a miss, and the run would halt there (PW-7). So the limit should sit above the ceiling by that margin, at about $115, as a
  backstop that fires only past the product's own stop **[hypothesis — K5's 3% is the red
  team's estimate]**. This is raised with Paul.

The registration body for cobra XS:

```json
{
  "repo": "cobra",
  "cell": {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "XS",
    "language": "go",
    "builder": "claude_code",
    "model": "claude-sonnet-5",
    "provider": "anthropic"
  },
  "hierarchy": ["S3", "S1@<author>"],
  "rule": "look.v1",
  "attempt_rule": "reserved.v1",
  "max_reruns": 0,
  "budget_profile": "default",
  "descriptive": [["A0", 16], ["A0+L", 16]],
  "author_model": "<author>",
  "campaign_id": "<the campaign, registered first at step 4>",
  "hypothesis": "With the arm's treatment, the builder's blind patches on cobra XS commits pass the repository's own tests more often than A0's.",
  "smallest_effect": 0.2
}
```

`hypothesis` (1 to 2,000 characters) and `smallest_effect` are required and hashed into the
reading's id, so neither can be edited after registration. Paul fixed both on 2026-10-12 (Q-34;
DL-412): one `smallest_effect`, 0.2, on all four readings, and one `hypothesis` per cell, in the
form above with the cell's repository and size. That all four carry the same `smallest_effect` is
Q-28's rule (DL-402). It is the "registered smallest effect": the loop clears when the pooled test
gives p < 0.05 and the pooled paired difference is at least that large (part 1, "How Q-25 is read").
The product stores it, and no code reads it **[aspiration — ADR-0026 item 13's design: one reading
per cell, four in all; none is registered yet]**. `attempt_rule`, `max_reruns` and `budget_profile`
are part 1's attempt rule (P-792): they are what `POST /readings` registers when a body leaves them
out, a body naming another rule or re-run count is refused 422, and all three are hashed into the
id. `campaign_id` is hashed into the id as well: every run filed under the reading is filed under
that campaign or refused, and the reading counts only rows of runs the campaign admitted (DL-382).

The other bodies change only `repo`, `size`, `language` and the repository and size the `hypothesis`
names: cobra S (`go`), click XS and click S (`python`). `pool`, `since`, `taxonomy`, `posture_class`
and `org_class` are left out, so the pool is every qualified commit of the cell (choice (c)), the
class set is the global vocabulary, and the posture class is the deployment's own, which must be
sealed.
