# Wave 3 — the registration, prepared and not run — 2026-10-09

**Status.** Prepared, not run. No reading is registered and no run is queued. The stack stays
down until Paul Glover restarts it (Q-14). Every step in part 5 is marked "not yet run".

**Authority.** Paul Glover's decision 7 of 2026-10-09, recorded as DL-371: Q-11 (ADR-0026's
values accepted), Q-14 (the restart and the money), Q-06 (each campaign is approved with a stated
maximum) and his answer on Wave 3's reviews (decision 5). The source is
`feedback/2026-10-09-project-room-decisions.md` in the private crb-handbook repository. This
record was written against `main` at `48c25abd`. The values Paul fixed on 2026-10-11, before
any data, are at the end of part 1 (DL-375 to DL-381), and part 2 is amended to the campaign
record the product now keeps (DL-374), which each reading names (DL-382).

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
| hierarchy | `S3` then `S1@<author>`, decided in that order; once `S3` reads `insufficient`, `S1` stops | items 4 and 13 |
| rule | `look.v1`: `deliver` at 20 of the first 20, 29 of the first 30 or 38 of the first 40 clean; `insufficient` at the third miss | items 3 and 5; the first look at 20 fixed by DL-371 |
| error budget | 5% per cell, of which `look.v1` spends 2.10%. It is a budget of error, not of money: Wave 3's money is part 2 | item 5; DL-371; HB-14 |
| descriptive arms | `A0` and `A0+L` on the first 16 commits of each cell's seeded order; they spend no error budget and never certify | items 4 and 13 |
| the loop | `learning: off` on every `A0` run; `A0+L` runs with the repository's loop switch on | items 1 and 13 |
| budget profile | one profile for every arm but `A0+L` | item 13 |
| pool | chosen by a rule blind to every outcome and frozen with its sha256 at registration; a hand-picked list is refused `pool_not_blind` | item 2; DL-097 |
| order | the seeded order, below: one order per cell, shared by every arm | item 2 |
| what counts | a commit's first observed attempt graded after registration, on the reading's checks arm; a `harness` row is run again; a commit the instrument cannot grade leaves the pool, and the next in order takes its place | item 2 |
| qualification | each cell's pool is mined and qualified first, at no model cost | PLAN, Wave 3 |
| the loop pair | one test on 64 pooled pairs: a pair is a commit observed in both `A0` and `A0+L`, among the first 16 of its cell's pool; an exact two-sided McNemar test at 0.05, read once, when both arms of every cell are complete (how Q-25 is read, below); it changes no default | item 13; DL-384 |

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
  repository." The registered smallest effect is each reading's `smallest_effect` (step 4).
  Q-25 reads each cell's loop difference against that cell's reading's `smallest_effect`, as
  "How Q-25 is read", after this list, fixes.
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
  sessions do not. Stage 1's £40 is released; stage 2 is a new decision (DL-381).
- **The freeze (Q-24; DL-375).** No new feature work until Wave 3 reports, except the pre-run
  pull request that made this record's checks the product's own.

**How Q-25 is read (amended before step 4, 2026-10-11; DL-384).** The Wave 3 pre-run red team
found that Q-25's Continue and Stop could be met or missed by a choice an analyst makes after
the data is in. These fix the statistics first, for 16 commits in each of four cells, so 64
pairs at most **[aspiration — the design ADR-0026 item 13 fixes; no pair is observed yet]**:

- **The loop pair.** One test, on the pairs of the four cells pooled. A pair is a commit
  observed in both `A0` and `A0+L`, among the first 16 of its cell's pool; a commit observed in
  one arm only is not a pair. With b the number of pairs clean under `A0+L` only and c the
  number clean under `A0` only, the test is an exact two-sided McNemar test at 0.05: p is
  twice the binomial probability of at most the smaller of b and c successes in b + c trials
  at one half, capped at 1, and 1 when b + c is 0.
- **What "clears" means.** A cell's loop difference is its paired difference, (b − c) / n
  with b, c and n counted over that cell's own pairs, and its lower 95% bound is the lower end
  of Newcombe's hybrid score interval for a paired difference (Newcombe 1998, method 10), so
  no interval is chosen after the data. The loop clears
  in a cell when the pooled test gives p < 0.05 with b above c, and that cell's lower bound is
  at least that cell's reading's `smallest_effect`; Continue's second clause holds when it
  clears in any cell.
  A difference in either direction is reported; only a positive one clears.
  Whether the four readings carry one value is open (step 4).
- **When it is read.** Once, when both arms of every cell are complete: each cell's `A0` and
  `A0+L` have run their 16 commits. If the campaign ends first, it is read once then, on the
  pairs observed, and the record says how many short of 64 it fell. Before that, an `A0` or
  `A0+L` tally is interim: the stage-1 report labels it "interim, not tested", and nothing
  rests on the difference, the stage-2 release included.
- **Noise.** Every Wilson interval this record serves or reports is descriptive (fixed-n, not
  adjusted for the sequential look): the Wilson 95% interval of clean over counted, taken as
  if the count had been fixed in advance. That includes the `ci_low` and `ci_high` that
  `GET /api/v1/readings` serves on each arm (`crb.core.reading`); `look.v1` decides a reading,
  never an interval. Q-25's "noise" is defined against that fixed-n rate. A rate moves by more
  than noise when it lies outside the fixed-n Wilson 95% interval of the rate it is compared
  with, in the same cell: the loop's `A0+L` rate against `A0`'s, the test author's
  `S1@<author>` rate against `A0`'s. The sealed rate, each cell's `A0` rate, sits within noise
  of the lower bound of the rate taken where the answer was reachable when that bound, the
  lower end of that rate's fixed-n Wilson 95% interval, lies inside the sealed rate's own.
  Which rate that is stays as Paul's words name it; this record recommends the value
  baseline's blind rate for the cell's size, taken in the host posture where the target commit
  stays in the object store (part 4's prior), and Paul confirms it before step 4.
- **Order.** Within each cell, `A0` runs before `A0+L`: a cell's `A0+L` run is queued only
  after its `A0` run has ended, which narrows choice (e) and leaves `A0` queued beside `S3`
  from the start. Each run records the levers in force: its apparatus stamp's `extra.learning`
  (`auto_apply`, `changes`, `overlay`), which the stage-1 report lists per run. Under the
  fail-closed attempt rule the operator chose for item 2, which a later amendment writes into
  the "what counts" row, no commit leaves, so none is replaced. Until then, and if an
  amendment ever allows a replacement, it is queued in both arms.

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
  admitted under the campaign and spends under the ceiling, but skips every reading gate
  (`reading_unknown`, `reading_unsealed`, `reading_posture_mismatch`, the worker's claim
  checks), and its rows count only when graded in the reading's scope: its cell, the sealed
  posture class, rung `r1`, after registration. Every Wave 3 body carries `reading_id`
  (step 6). A run of a pool commit posted with neither is not refused: it is queued outside
  the campaign and spends outside the ceiling under its own cap. A campaign's reading reads
  only rows of runs admitted under the campaign (`GET /api/v1/readings` serves
  `admitted_runs`, the campaign's count, the same for every reading of it); a row of any
  other run is invisible to it, whatever its failure kind, harness and outage included, so
  a commit is read by its first admitted attempt and no run outside the campaign makes it
  leave. A reading on the factory's cell names no campaign (422
  `campaign_unsupported_reading`); Wave 3 registers none.
- A run is admitted in the same transaction that queues it, and only while its cap and its
  headroom fit what is left under the line, by the tally below; otherwise it is refused 409
  `campaign_ceiling` and nothing is queued.
- A campaign with a run whose cost is not known is stopped, 409 `campaign_cost_unknown`, and so
  is one with a run that spent past its cap plus the headroom it was admitted with, 409
  `campaign_overrun`: every new run is refused.
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
  a row of an admitted run graded unsealed in the reading's posture class (`scope_fault`), which leaves its arm undecided,
  or spend the tally cannot place against a run.

On a stop, Claude Code queues nothing more and cancels the runs that have not started; the
product refuses every new run of a stopped campaign whatever is queued. A running run ends at its
cap, which was set to fit.

**What Claude Code reports at the end of stage 1**, to Paul and as a dated record under
`docs/reviews/`:

- spend per cell and per arm, in dollars and in pounds at 1.35, the author calls shown apart, and
  the total against $54.00;
- for each reading arm: commits counted, clean and missed, and its state (`deliver`,
  `insufficient`, `look_pending` with the commits still needed, or `undecided`);
- for each descriptive arm: commits run and clean, labelled "interim, not tested" (the loop
  pair is tested once, when both arms of every cell are complete; part 1), with the levers in
  force on each run;
- what stage 2 would buy: the statement of part 4.

**Stage 2** starts only on Paul's written release, recorded in the decision log: a new decision
(DL-381). It is then filed as `POST /api/v1/campaigns/{id}/release` with `{"released_gbp": 80,
"decision": "<the release's decision log id and words>"}`, which raises the line and never
passes the ceiling (409 `campaign_release_invalid`). Its line is $108.00 for the campaign in
all. Nothing is queued while the release is awaited. The release does not depend on the
interim difference between `A0` and `A0+L`: the stage-2 statement (part 4) and stage 1's spend
are what it reads, and the loop pair is tested only as part 1 says.

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

## 3. The reviews

**The reviewer.** Claude (Claude Code, model `claude-opus-5-5`) reviews Wave 3's clean blind
patches. Paul Glover gave Claude the task (decision 7, his answer on Wave 3's reviews; DL-371).
Claude reviews in a fresh session, separate from the builder's and from the session that runs the
campaign, as that answer asks.

**What it reviews.** Every clean row of the blind arms — `A0`, `A0+L` and `S1@<author>` — that a
reading counts. `S3` is sighted and is not reviewed.

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
| 1 | confirm the instrument | Claude Code: `crb_version` (MCP) or `GET /version`; `GET /api/v1/repos` | apparatus `2.4`; the repositories `cobra` and `click` listed [hypothesis — the names the 2026-09-25 export used] | not yet run |
| 2 | fix the test author, choice (a) | Claude Code reads `raw.factory.test_author` from `GET /api/v1/settings` (admin); if it is empty or names `claude-sonnet-5`, Paul sets `CRB_FACTORY__TEST_AUTHOR` and restarts the worker | a `builder:model[:provider]` whose model is not `claude-sonnet-5`; its canonical model recorded here as `<author>`, and `<author>` has a known price (else an `S1` run is refused `spend_cap_unpriced`, a stop; K3, part 2) | not yet run |
| 3 | mine and qualify each repository, at no model cost | the Posture panel at `/repos/cobra` and `/repos/click` ("Qualify for this posture — no model spend"), or `crb_start_run` with `{"kind": "mine", "repo": "cobra"}` then `{"kind": "qualify", "repo": "cobra"}`, and the same for click. The parameters are pinned, as values the step-3 amendment records: each mine and qualify body as sent (`pool`, `limit`, `max_candidates`, `ref`, and no `task_ids`), and the `since` and `taxonomy` step 4's bodies leave out (empty: every qualified commit, choice (c), and the global vocabulary); none changes after step 3. From then on: no label run, CLI label edit or 2.4 replay on cobra or click between step 3 and the end of step 11, but the runs step 6 files under the campaign | each run `succeeded` with a `cost_usd` of 0; `GET /api/v1/repos/<repo>/posture` shows `executor` `docker`, a `posture_class` of `docker/<tree>/sealed` and an empty `stale_reason`; each cell holds at least 20 qualified `bug.fix` commits, the first look, and each cell's count is noted here. The step-3 amendment records, for each cell, the qualified-set sha256 (its qualified commits in seeded order, hashed as `pool_sha256` is) and where each label came from (classifier or human), and the result of K1's audit (part 2) | not yet run |
| 4 | register the campaign, then the four readings | Claude Code, over HTTP with an operator session (`POST /api/v1/auth/login`, then `X-CSRF-Token` from the `crb_csrf` cookie, `__Host-crb_csrf` under TLS): first `POST /api/v1/campaigns` with part 2's body, then `POST /api/v1/readings` for each reading; no screen and no MCP tool registers a reading, and `crb reading register` writes only a local file. The body is below; it states the `hypothesis` and the `smallest_effect` and names the campaign (`campaign_id`), so the campaign comes first (DL-382). A reading registers only on a sealed deployment, the builder included: `CRB_SANDBOX__EXECUTOR` and `CRB_BUILDER__EXECUTOR` both `docker` (DL-373) | `201` for the campaign, with `campaign_id`, `ceiling_usd` 108.00 and `line_usd` 54.00. `201` for each reading, with `reading_id`, the campaign's `campaign_id`, the `pool` in seeded order, `pool_sha256` and `pool_rule`; `GET /api/v1/readings?repo=<repo>` lists each, its cell's budget spent at 2.10% of 5%. A refusal (`campaign_unknown`, `lint_disabled`, `pool_seen`, `budget_spent`, `pool_not_blind`, `invalid_reading`) stops the campaign before any spend; `lint_disabled` (`detail` `{repo, reason}`, nothing written) answers any registration while the repository's lint is switched off, and a `reserved.v1` reading hashes the repository's lint configuration as `lint_digest` (P-796). On an unsealed deployment `invalid_reading` names what is unsealed in its `detail`: both executors, `{sandbox_executor, builder_executor}`, when the sandbox is on docker and the builder on the host; the posture class alone, `{posture_class}`, when the sandbox is not on docker, because that refusal comes first. A `409` `reading_exists` (`detail` `{reading_id}`, nothing written, nothing spent) answers a reading already registered, a retried request under any second or actor: it is a retry, not a stop; read the reading back with `GET /api/v1/readings?repo=<repo>`. The campaign id, the reading ids and the pool sizes are added here in an amendment commit | not yet run |
| 5 | turn the loop on for `A0+L`, choice (b) | Paul or Claude Code: the switch on the Learn page, or `PUT /api/v1/learn/switch?repo=<repo>` with `{"auto_apply": "config", "reason": "Wave 3, the A0+L arm (ADR-0026 item 13; DL-371)"}`; the state before is recorded here | the Learn page reads `config` for cobra and for click | not yet run |
| 6 | queue the runs, cell by cell, under part 2's rule | Claude Code, `crb_start_run` (`POST /api/v1/runs`), which posts the body unchanged; runs are queued with `POST /runs` only: `POST /api/v1/learn/remeasure/queue` files no run under a campaign, so the product refuses it for these readings (409 `campaign_required`). Every body carries `"reading_id": "<the cell's reading>"`, `"campaign_id": "<the campaign>"` and `"max_cost_usd": <cap>`; a body without `campaign_id` is refused 409 `campaign_required` when it carries `reading_id`, and is otherwise queued outside the campaign, and the reading never sees its rows, whatever their failure kind; a body with `campaign_id` but no `reading_id` is admitted and spends under the ceiling but skips every reading gate, and its rows count only when graded in the reading's scope — every body here carries `reading_id` (DL-382). **`S3`**: the cell's request from `crb_remeasure_plan` (`GET /api/v1/learn/remeasure?repo=<repo>`; nothing queued), plus those three and `"budget_profile": "default"`. **`A0`**: `{"repo": "<repo>", "kind": "blind", "builder": "claude_code", "model": "claude-sonnet-5", "provider": "anthropic", "task_ids": [the first 16 of the reading's pool], "learning": "off", "budget_profile": "default", "reading_id": "<reading>", "campaign_id": "<campaign>", "max_cost_usd": <cap>}`. **`A0+L`**: the same with no `learning` and no `budget_profile`. **`S1`**: its request from the remeasure plan once `S3` delivers, with its `task_ids` or `limit`, plus those three and `"budget_profile": "default"` | each run is admitted (`201`) or refused before it is queued (`campaign_ceiling`, `campaign_cost_unknown`, `campaign_overrun`, `campaign_cap_required`, `campaign_s1_unbounded`, `campaign_required`, `campaign_unknown`, `reading_unknown`, `reading_unsealed`, `reading_posture_mismatch`, `lint_disabled` — the repository's lint switched off, P-796); a queued run whose repository's lint is switched off after submit ends `failed` at claim before anything is reserved (`system/run.refused`, `code: lint_disabled`), its commits still pending; an admitted run ends `succeeded`, or `failed` with `stopped_code: spend_cap`; its rows carry the arm queued, at rung `r1`, apparatus 2.4, in the sealed posture; `GET /api/v1/readings` counts the run's commits under that arm — only rows of runs the campaign admitted count, and `admitted_runs`, which every reading of the campaign serves, rises by one for each run the campaign admits — and `GET /api/v1/campaigns/{id}` lists the run | not yet run |
| 7 | read the tally | Claude Code, after each run: `GET /api/v1/campaigns/{id}` (`spent_usd`, `authoring_usd`, `held_usd`, `left_usd`, `stopped`); `GET /api/v1/runs/{id}` and `crb_run_events` only to place a figure against a run | `stopped` is `null` while the campaign runs, and spent and held stay at or under the stage's line; otherwise part 2's stop, which `stopped` serves as `{code, message, run_ids}` | not yet run |
| 8 | report stage 1 | Claude Code, when stage 1 ends (part 2) | Paul has the report and part 4's statement; the record is committed under `docs/reviews/` | not yet run |
| 9 | stage 2 | Paul releases it in writing, a new decision; the release is recorded in the decision log and filed as `POST /api/v1/campaigns/{id}/release` (part 2); Claude Code resumes step 6 with the line at $108.00 | the release answers `200` with the campaign and is recorded before any stage-2 run is queued; `GET /api/v1/campaigns/{id}` reads `line_usd` 108.00 | not yet run |
| 10 | restore the loop switch | Paul or Claude Code, after the last `A0+L` run | the switch reads the state recorded at step 5 | not yet run |
| 11 | the reviews | Paul creates the reviewer's account; Claude reviews in a fresh session (part 3); then Paul sends the salt and Claude Code draws his 10; Paul files his | a review on every clean blind row a reading counts; Paul's 10 filed after Claude's; the agreement reported with its intervals | not yet run |

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
  "descriptive": [["A0", 16], ["A0+L", 16]],
  "author_model": "<author>",
  "campaign_id": "<the campaign, registered first at step 4>",
  "hypothesis": "<what the cell's reading tests, in the operator's words>",
  "smallest_effect": "<a share of attempts in (0, 1], fixed by Paul before step 4>"
}
```

`hypothesis` (1 to 2,000 characters) and `smallest_effect` are required and hashed into the
reading's id, so neither can be edited after registration. Both are open: Paul fixes them
before step 4, and this record proposes no number for the smallest effect. It is the
"registered smallest effect": Q-25 reads each cell's loop difference against that cell's
reading's `smallest_effect`, and the loop clears in a cell when the pooled test gives p < 0.05
and the lower end of that cell's paired difference's 95% interval is at least that large
(part 1, "How Q-25 is read") **[aspiration — ADR-0026 item 13's design: one reading per cell,
four in all; none is registered yet]**.
Open for Paul before step 4: whether the four readings carry one smallest_effect.
`campaign_id` is hashed into the id as well: every run filed under the reading is filed under
that campaign or refused, and the reading counts only rows of runs the campaign admitted
(DL-382).

The other bodies change only `repo`, `size` and `language`: cobra S (`go`), click XS and click S
(`python`). `pool`, `since`, `taxonomy`, `posture_class` and `org_class` are left out, so the
pool is every qualified commit of the cell (choice (c)), the class set is the global vocabulary,
and the posture class is the deployment's own, which must be sealed.
