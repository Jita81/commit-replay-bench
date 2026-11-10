# Wave 4 — the registration, prepared and not run — 2026-11-10

**Status.** Registered design. Nothing here has been run and nothing has been spent.
Decision R-1 is taken: option B, the combined test. No Wave 4 run is filed until the fixes of
part 4 are deployed. Paul's yes to the spends is recorded under Authority.

**Authority.** Paul's "yes to all four, go ahead" of 2026-11-10 (the Wave 3 closure; this design
with a money line of $60 for stage 1 and $35 for stage 2, in real dollars; apparatus 2.5 with a
short ADR; `gpt-oss-120b` on Cerebras as the test author), and his "Yes" of the same day to three
points: the freeze ends when #111 merges, Wave 4 stands under Wave 3's Stop verdict, and
disqualified rows count as misses **[hypothesis — Paul's words in the session of 2026-11-10, quoted by Claude Code]**.

On 2026-11-10 at about 22:10Z Claude Code asked Paul three things before an unattended night:
whether it may pull and restart the stack once after the fixes merge; how far the money may go
(the pilot only; the pilot, then click and cobra if every pilot gate passes, all under the one
line, stopping at the first failed gate or the money stop; or nothing); and whether CodeRabbit's
re-review is waived for heads whose only change since a reviewed head is the changelog merge with
`main`. Paul answered "restart yes, pilot plus both stages, waiver yes". That is the yes to the
pilot, to click and to cobra, each conditional on the gates of part 5 **[hypothesis — the question
and the answer in Claude Code's session of 2026-11-10; the transcript is not in this repository]**.

**Claims in this record.** Nothing here is measured on a Wave 4 row. Wave 3 figures are quoted from
its stage-1 report (#111). Pool counts were read from the served stack on 2026-11-10 at apparatus
2.4 and will change when every commit re-qualifies at 2.5. Costs are estimates. Power figures come
from a simulation of the registered test, not from data.

**Review.** Two independent reviewers checked the first draft, one on the statistics and one
against the product's code. This version takes in all fourteen of their findings **[hypothesis — the review ran in Claude Code's session on 2026-11-10; its output is not in this repository]**.
It was then revised for the five points of an outside review of the pull request (the source of
the pool counts, the simulation's method, the pilot's overlap with the wave, approval of a repeat
pilot, and a test that respects batches), and two more reviewers checked that revision **[hypothesis — CodeRabbit's review of #117 and a second review in Claude Code's session, both on 2026-11-10; neither output is in this repository]**.

## Decision R-1: option B, the combined test

**Decided 2026-11-10.** Asked to choose between A and B, Paul answered "I'm happy for you to make
the best decisions for our products future". Claude Code chose B on that authority: it is the
only option able to settle the effect the wave is built to find. The delegation covers the
design; it does not cover spending. Paul's separate yes to the spends is under Authority. The table and the
reasoning are kept below as the record of what was weighed.

The approved design assumed 40 qualified click commits in each of XS and S. The served stack
holds fewer. Read on 2026-11-10 from `GET /api/v1/repos/<repo>/tasks` on the served stack at
apparatus 2.4, `bug.fix` only **[hypothesis — counts read from the stack by Claude Code on 2026-11-10; the responses are not in this repository]**:

| Cell | Mined | Qualified now | Not qualified, by reason |
|---|---|---|---|
| click XS | 75 | 27 | gold tests not green 32; no wheel for a pinned package 12; lint could not run 3; new belt failure 1 |
| click S | 81 | 24 | gold tests not green 28; lint could not run 14; no wheel 14; new belt failure 1 |
| cobra XS | 23 | 16 | fetch failed 4; gold tests not green 3 |
| cobra S | 29 | 20 | fetch failed 7; gold tests not green 1; no record 1 |

Click therefore gives about 51 commits today, not 80. The pytest fix (part 4, fix 1) may rescue
some of the 60 "gold tests not green" click commits when everything re-qualifies at 2.5, but I
cannot know how many before that pass runs **[hypothesis — read from the stack on 2026-11-10 at apparatus 2.4]**.

| Option | Primary result read on | Commits (today's pools) | Attempts | Estimated cost | Smallest difference detected four times in five | Chance of detecting a true 15-point effect |
|---|---|---|---|---|---|---|
| **A. Staged, as approved** | click only; cobra is a later, separate check on your yes | about 51 | about 255, then about 180 | about $33, then about $23 | about 18 to 24 points | about 45% to 67% |
| **B. Combined (recommended)** | click and cobra together, all four cells, committed to before the first run | about 87 | about 435 | about $57 | about 14 to 18 points | about 74% to 91% |

Under B you agree to both repositories before any result is seen, so the two can be read as one
test. You still say yes at the cobra image switch, but only as an operations step: it may not
depend on what click showed. The money line becomes one line of $95 (the two approved lines
added). Under A the click result is too weak to settle a 15-point effect, and cobra can never be
added to it afterwards.

Either way the number of commits is cut to fit the money line before the first wave run (part 3),
so the wave cannot outgrow the line.

**How the two right-hand columns were found.** By simulation, not from data. Each commit got its
own chance of a clean build, drawn from a beta distribution with a mean of 0.3, 0.5, 0.6 or 0.7
and a within-commit correlation of 0, 0.25 or 0.5. `A0` made two independent attempts at that
chance and `S1` two at that chance plus the effect. Commits were independent of each other. The
test was the exact sign-flip test on per-commit differences, two-sided at 0.05. Each figure is
the share of 800 to 1,500 simulated waves that rejected, and the ranges span the settings above **[hypothesis — a simulation run in Claude Code's session on 2026-11-10; its script and output are not in this repository]**.

**Revised on 2026-11-10 after outside review; this replaces option B's row above.** Option A's
row rests on the old test and on pools that still hold the pilot's commits, so it overstates A;
it is kept as the record only. Three things changed. The pilot's six commits are struck from the
click lists before anything is counted (part 5), so today's pools give about 81 commits, about
405 attempts and about $53. Batches are five commits, not ten. The primary test flips whole
batches, not single commits (part 6), because all the commits of a batch share the same four runs **[hypothesis — counts read from the stack by Claude Code on 2026-11-10 and priced at 13 cents an attempt; the responses are not in this repository]**.

The simulation was repeated for that design, twice, by two scripts written independently. The four
cells held 24, 21, 16 and 20 commits in 18 batches. Each commit's chance came from a beta
distribution with a mean of 0.3, 0.5 or 0.7 and a within-commit correlation of 0, 0.25 or 0.5.
Each of a batch's four runs carried a shock shared by all its commits, drawn from a normal
distribution with a mean of 0 and a standard deviation of 0, 5 or 10 points. The effect and the
shock were added to the commit's chance and the sum was cut off at 0 and 1. Each setting ran
2,000 simulated waves (600 per step for the smallest difference); the first script's seed was
20261110 **[hypothesis — a simulation run in Claude Code's session on 2026-11-10; its script and output are not in this repository]**. Across the 27 settings and both scripts:

- the test rejected a true null in 2.5% to 4.6% of waves **[hypothesis — a simulation run in Claude Code's session on 2026-11-10; its script and output are not in this repository]**;
- it detected a 15-point effect in about 58% to 89% of waves **[hypothesis — a simulation run in Claude Code's session on 2026-11-10; its script and output are not in this repository]**;
- the smallest difference detected four times in five was 13 to 20 points **[hypothesis — a simulation run in Claude Code's session on 2026-11-10; its script and output are not in this repository]**.

The weakest setting is a mean of 0.7 with a correlation of 0.5: there the cut-off at 1 leaves less
than 15 points of real effect. The old test, flipping single commits, rejected a true null in up
to 8% of waves with batches of ten and about 6% with batches of five once runs carried a 10-point
shock; that is why it was replaced. Option B is still the only option with a fair chance of
detecting a 15-point effect, but that chance is lower than the first table said **[hypothesis — a simulation run in Claude Code's session on 2026-11-10; its script and output are not in this repository]**.

## 1. The question

**Does a blind builder that is given a test written independently beforehand do better than a
blind builder with the ticket alone?**

Wave 3 closed with the registered verdict Stop: the learning loop did not clear on 64 pairs (8
clean only with the loop, 25 only without, p = 0.0046). Wave 4 does not test the loop. It tests
the next lever the factory could really use, which the product already implements as arm `S1` **[hypothesis — quoted from the Wave 3 stage-1 report, #111; its rows are not in this record]**.

What is estimated is the effect of the `S1` arm **as the product implements it**, test author
failures included. It is not the effect of a perfect independent test.

## 2. Design

**Ordinary runs, not registered readings.** The product's readings allow one attempt per commit,
refuse a commit that already has a row, and treat `S1` as a certifying arm. Wave 4 needs two
attempts per commit on commits Wave 3 has already used. So no cell can read "deliver" from Wave 4
and no error budget is spent. In place of the product's seal, this document fixes the commit rule,
the run bodies, the row rule and the analysis before the first run, and the report lists every run
id. DL-373 keeps "the ordinary measurement runs that read no reading" **[aspiration — this registration's design; nothing is run yet]**.

Two costs of this choice, stated now:

- Every Wave 4 row marks its commit as seen. Wave 4 therefore uses up these commits for any later
  certifying reading on click and cobra at `bug.fix` XS and S.
- The product's maps show `S1` rows as a certifying arm whether or not a reading was registered.
  Routing and sign-off are not read for these cells at 2.5, and the report says so on its first
  page. Nothing in Wave 4 is a certificate.

**Arms, all on the same commits, learning off on both repositories:**

| Arm | What the builder gets | Attempts per commit |
|---|---|---|
| `A0` | the ticket only (blind) | 2 |
| `S1@gpt-oss-120b` | the ticket and one test file written from the ticket by the test author | 2 |
| `S3` | the held-out tests (sighted), as a reference | 1 |

**Fixed settings.** Apparatus 2.5. Builder `claude_code` with `claude-sonnet-5`, provider
`anthropic`, sealed posture, budget profile `default`. Class `bug.fix`, sizes XS and S.

**Run bodies.** A run carries one arm, so each batch of commits is filed as separate runs with
explicit `task_ids`. Every run names the Wave 4 campaign, a `max_cost_usd`, and the stop settings
`env_stop: 2` and `outage_stop: 3` (the product's defaults for ordinary runs, written out so they
cannot drift).

| Arm | Run body, beyond the fixed settings |
|---|---|
| `A0` | `kind: "blind"`, `task_ids`, `learning: "off"`, `retain: {transcripts: true}`, `builder_config: {keep_transcript: true}`, `budget: {max_turns: <the registered limit>}` |
| `S1` | the same, plus `arm: "S1"` and `test_author` set to the Cerebras `gpt-oss-120b` rung |
| `S3` | `kind: "replay"`, with the same learning, transcript and budget fields |

Transcripts need both transcript fields: either one alone keeps nothing, silently. `learning:
"off"` is sent on every run even though the repository switch is also off. The turn limit covers
the builder; the test author's own budget is separate and is left at the product default.

**The commit list is fixed by rule, then written down.**

1. After the fixes are deployed, every `bug.fix` XS and S commit on click and cobra re-qualifies at
   2.5 with a `qualify` run, at no model cost. The qualify run uses the same executor, image and
   sealed posture as the wave runs; otherwise its records would not apply to them.
2. Each cell's list is its qualified commits (the latest record per commit in that posture) in the
   product's seeded order: ascending `sha256("crb.reading.v1|" + repo + "|" + cell key + "|" +
   commit)`, ties by commit, as `crb.core.reading.seeded_order` computes it. The cell key is the
   seven fields process step, class, size, language, builder, model, provider — here `replay`,
   `bug.fix`, `XS` or `S`, the repository's language, `claude_code`, `claude-sonnet-5`,
   `anthropic` — joined as `canonical_cell_key` joins them **[aspiration — the rule the lists will be built by; no list exists yet]**.
3. The four **full** ordered lists, the exact key string of each, each pool's size and a sha256 of
   each list are appended to this document in an amendment commit **before the pilot**. The
   amendment marks the pilot's six commits (the last three of each click list) as struck; from
   then on "the list" means the list without them **[aspiration — this registration's design; nothing is run yet]**.
4. After the pilot, one per-cell cap `k` is set by the money rule of part 3 and each list is cut
   to its first `k` commits. `k`, the turn limit, the campaign id, every batch's seeded order and
   the power of the test on the cut lists (the same simulation, rerun) are appended in a second
   amendment **before the first wave run**. Nothing is added or removed after that.

All four steps are design **[aspiration — this registration's design; nothing is run yet]**.

**Run order.** Each cell's list is cut into batches of five in list order; a cell's last batch
may hold fewer, down to one commit. Within a repository the batches of the two sizes are filed
alternately, XS first, and when one size runs out the other carries on. A batch's number is its
place in that filing order within its repository, starting at 1. Each batch is four blind runs
filed one after another, never in parallel. A seeded coin per batch (the first hex digit of
`sha256("crb.wave4.order|" + repo + "|" + batch number)`, even or odd) picks the order
`A0, S1, S1, A0` or `S1, A0, A0, S1`. Each arm therefore sits equally early and late within every
batch, and neither steady drift in the model nor a long outage can line up with one arm by
design. A short outage can still hit the two middle runs of one batch, which belong to one arm;
the coin decides which arm that is. Rows still missing after the batch is filed again count as
misses and can move the primary result, so the report lists every such row with its batch and
arm. A
batch that is filed again keeps the order of its first filing. All blind batches of click run
first, then, after the image switch, all blind batches of cobra. `S3` runs are filed last and
only while the remaining line still covers every outstanding blind row at one and a half times
the running cost per attempt. The report prints the realised schedule with times **[aspiration — this registration's design; nothing is run yet]**.

**Row rule.** Fixed here so that no choice about rows can be made after results are seen **[aspiration — this registration's design; nothing is run yet]**.

- A commit's attempts under an arm are the rows from that arm's two runs in the commit's batch.
- If any of a batch's four runs halts, fails or returns fewer rows than it has commits, the whole
  batch is filed again once, all four runs, and the first filing's rows are set aside unread. The
  trigger is the run's status and row count, never its results.
- An `S1` build whose author produced no usable test is an ordinary miss. It is not a halted,
  failed or short run for the rule above: a run that is short only for that reason, read from
  the run's events and not from its results, is not filed again.
- After that, a row that is still missing counts as a miss. That covers a commit the product
  drops because it stopped qualifying, an outage, and a halted run.
- Pilot rows are never counted.

## 3. Money

| Item | Estimate | Line |
|---|---|---|
| Pilot | about $3 | inside the $95 line |
| A repeat pilot, only on Paul's yes | about $3 | inside the $95 line |
| Option A, stage 1 (click) — not chosen, kept as the record | about $33 | $60 |
| Option A, stage 2 (cobra) — not chosen, kept as the record | about $23 | $35 |
| Option B, whole wave | about $53 (about 81 commits once the pilot's six are struck) | $95 |

Estimates use Wave 3's real cost of about 13 cents an attempt. The test author's calls and a
higher turn limit will add to it; treat each estimate as plus or minus 50%. Costs are counted in
real dollars from the product's own price table once fix 4 is deployed **[hypothesis — Wave 3's cost per attempt as its stage-1 report (#111) gives it; the Wave 4 figure is an estimate]**.

**How the line is held.** A new campaign is registered in the product for Wave 4, holding no
readings, with its ceiling at the line (the product keeps ceilings in pounds at a recorded rate).
It must not be a Wave 3 campaign: a campaign that holds reserved readings on a repository refuses
every run that names no reading. Every run also carries its own `max_cost_usd`. A run the campaign
would refuse is not filed.

**The list is cut to fit the line.** `c` is the pilot's product cost per blind attempt: the mean
for `A0` and the mean for `S1`, author's calls included, averaged with equal weight, because the
wave runs the two arms equally. The wave may hold at most
`N = floor((line − pilot spend) / (5 × 1.5 × c))` commits. `k` is the largest whole number, at
most 40, for which the four cells cut to `k` hold no more than `N` commits together. Pilot spend
is the spend of every pilot run, a repeat included, and `c` comes from the pilot whose gates
passed. At 13 cents this leaves today's pools whole; at 20 cents it would cut the wave to 60
commits, and the power figures of R-1 would fall with it. The half again in the rule pays for
re-filed batches and for `S3` **[aspiration — this registration's design; nothing is run yet]**.

**If the money stops the wave anyway,** the primary is **not read**. Under option B that includes
the case where cobra cannot be run or finished for any reason: the result is reported as not
read, never as a click-only test. Each spend (pilot, click, cobra) starts only under Paul's yes recorded under Authority, and only
when every gate before it has passed.

## 4. Before any Wave 4 row

| # | What | State |
|---|---|---|
| 1 | Click's dependency set includes the `tests` group, so pytest is present for every build | Paul's stack step |
| 2 | The builder's own cache and temp files no longer disqualify a build | PR #113, reviewed, green |
| 3 | `git -C <worktree> <allowed command>` is accepted | PR #114, reviewed, green |
| 4 | Cost is computed from the product's price table, with the CLI's figure beside it | PR #115, outside review still owed |
| 5 | Apparatus 2.5 (ADR-0049, DL-417), so Wave 3 and Wave 4 rows can never be blended | PR #116 |
| 6 | The test author's key is on the stack | The stack's `env.sh` already names `CEREBRAS_API_KEY`; pilot gate checks that it works |
| 7 | Served checkout updated and the stack restarted | Claude Code, once, by Paul's yes of 22:10Z |
| 8 | Every commit re-qualified at 2.5; the full lists appended here | me, at no model cost, after 7 |
| 9 | The Wave 4 campaign registered | before the pilot, by Paul's yes of 22:10Z |

2.5 is not deployed while a 2.4 campaign is open, and not without fixes 2 to 4.

## 5. Pilot

Eighteen builds on click, about $3, transcripts kept. The pilot uses the last three commits of
each click cell's seeded order, six commits in all: two `A0` attempts on each (twelve builds) and
one `S1` attempt on each (six builds). Those six commits are struck from the click lists in the
first amendment, before `k`, the cost and the power are worked out, so no commit is in both the
pilot and the wave. Pilot rows are never counted **[aspiration — this registration's design; nothing is run yet]**.

The wave starts only if all of these hold **[aspiration — this registration's design; nothing is run yet]**:

- no more than 1 of 18 builds misses for a harness reason (part 7);
- the test author produces a usable test for at least 5 of 6 commits;
- no `S1` build is disqualified because of the authored test file itself: the test-files check
  must not fire on the file the harness wrote;
- if the author produces no usable test for a commit, that build still ends as a row or a
  recorded miss and its run's status is not halted or failed;
- one `S1` row's arm label reads `S1@gpt-oss-120b`, and a transcript file exists for a build of
  each arm;
- the product's cost for the pilot is within 10% of the provider consoles.

**The turn limit, by rule.** It stays at the product default unless at least 3 of the 18 pilot
builds, both arms counted together, end on the turn limit having run the tests within their last
five turns. In that case it is doubled, once, for every arm **[aspiration — this registration's design; nothing is run yet]**.

**If a gate fails.** Everything stops. No repeat pilot is filed and nothing more is spent until
Paul says yes to it, having seen which gate failed and what would change. If Paul does say yes, the
repeat pilot takes the next three commits from the tail of each click list, and those are struck
from the lists in a further amendment written before it runs. Its spend counts against the one
line. The `S1` arm is never tuned on commits the wave will count **[aspiration — this registration's design; nothing is run yet]**.

## 6. Analysis, fixed in advance

Every item below is a rule for rows that do not exist yet **[aspiration — this registration's design; nothing is run yet]**.

1. **Primary.** `A0` against `S1`. For each commit, the share of its two attempts that are clean
   under each arm, and the difference. Statistic: the sum of the per-commit differences. One exact
   two-sided sign-flip test at 0.05 over all four cells' commits, in which the unit that is
   flipped is the batch: each batch's summed difference keeps or changes its sign as a whole, and
   every one of the 2^(number of batches) sign patterns is counted. The p-value is the share of
   those patterns, the observed one included, whose summed difference is at least as far from
   zero as the observed sum. The commits of a batch share
   the same four runs, so they are not treated as independent; batches are. Smallest effect of
   interest: 15 points. This is the only p-value in the
   wave. It is read once, when every batch has been filed (and re-filed where the row rule says
   so). Until then no comparison between the arms is computed, on click or anywhere; rows are
   looked at only for the harness checks.
2. **The interval.** Beside the p-value, a 95% interval for the mean per-commit difference,
   built from batches and not from the sign-flip test, because inverting that test is exact only
   if the effect is the same on every commit. The estimate is the sum of all per-commit
   differences divided by the number of commits. Its standard error treats each batch as one
   unit: with `B` batches, `n_b` commits in batch `b`, batch sum `S_b`, estimate `d` and `N`
   commits, it is `sqrt(B/(B−1) × Σ(S_b − n_b×d)²) / N`. The interval is the estimate plus and
   minus that error times the 97.5% point of Student's t with `B − 1` degrees of freedom **[aspiration — this registration's design; nothing is run yet]**.
   In simulation on the registered batch layout this interval missed the true mean in 4.3% to
   6.9% of waves; the worst settings had a starting chance of 0.9, where the ceiling skews the
   differences **[hypothesis — a simulation run in Claude Code's session on 2026-11-11, 4,000 to 20,000 waves a setting, seed 20261111; its script and output are not in this repository]**.
3. **Author failures that run across batches.** The primary test treats batches as independent.
   A long failure of the test author breaks that: it turns `S1` rows into misses in several
   batches in a row. Those misses stay in the primary result, because an author that fails is
   part of what `S1` is. Beside it the report gives one sensitivity result, fixed here. A batch
   is *author-hit* if the author produced no usable test for more than half of its commits,
   read from the runs' events. Author-hit batches that follow one another in filing order
   within a repository form one block, which flips as a whole in the test and counts as one
   unit in the interval. The same test and interval are then recomputed twice: with those
   blocks, and with every author-hit batch left out. If either differs from the primary result
   on which side of 0.05 it falls, the wave is reported as *inconclusive*, whatever the primary
   p-value says **[aspiration — this registration's design; nothing is run yet]**.
4. **What each outcome may be called.** *Cleared*: p below 0.05 with `S1` ahead and the sensitivity result of item 3 on the same side. *No 15-point
   effect*: p not below 0.05 and the interval's upper end below 15 points. *Inconclusive*:
   anything else. Under option B the claim is about the average over the listed commits of both
   repositories together; nothing is claimed for either repository alone.
5. **Every row is a miss unless clean.** Disqualified rows, missing rows, outages, turn-limit
   endings and an author that produced no usable test all count as misses, under both arms. The
   product's own split is reported beside ours.
6. **Everything else is description, with no tests.** Per-cell and per-repository results;
   agreement between attempt 1 and attempt 2 within an arm; `S3` against each blind arm, with the
   blind rows that the test-files check alone disqualified listed beside it, because that check
   does not run on sighted rows; a table that leaves out harness-caused misses; a table that
   leaves out commits where the author produced no usable test; the author's usable-test rate. A
   secondary table never replaces the primary.
7. **Cause of every miss.** Classed as builder, harness or unclear with the checklist of part 7.
   The classing is not blind: an `S1` transcript shows the authored test. So the count that
   matters for the stop below is taken from row fields, and the transcript reading is reported
   beside it.
8. **Mergeability.** Ten clean patches per arm per repository, drawn where possible from commits
   clean under both arms, compared with the real commit by a reviewer who is not told the arm:
   merge as is, merge with small edits, or do not merge. Reported as counts. Paul checks five as an
   audit of the reviewer.
9. **Stops.** (a) The money line (part 3). (b) Four or more of the first 40 wave builds ending on
   an outage, a provider error, a container failure or a refused allowed command, counted from row
   fields. (c) Any change to the served code after the second amendment. After (b) or (c) every
   wave row so far is set aside, the fault is repaired, and the wave starts again only under a
   new amendment to this document, written before any further run.

**What the result will mean.** If `S1` clears, the independent test becomes the factory's default
blind arm and the next wave certifies cells with it. If the result is "no 15-point effect", the
blind route on these commits is not close to deliverable by this lever and the next step is a
different lever, not a larger sample. If it is inconclusive, it is reported as inconclusive and
Paul decides whether more commits are worth their cost.

## 7. Miss checklist, frozen here

A miss is **harness** when the transcript shows any of: a tool the builder needed was missing or
refused (test runner absent, an allowed command refused, sandbox or network error not caused by
the patch); the build ended on an outage, a provider error or a container failure; the row was
disqualified for a file the harness or its tooling wrote; the authored test for `S1` was absent or
could not be shown to fail at the parent.

A miss is **builder** when the tools worked and the patch failed the held-out tests, changed test
files, failed a belt, or the builder stopped or ran out of turns without a passing patch while
still able to run the tests.

Anything else is **unclear**, and is reported as such, never reassigned.

## 8. Kept out

The learning loop (it returns only after a design review and a cheap replay that shows an
effect); certifying readings; other classes and sizes; repeats inside registered readings;
Harness².

## 9. What needs Paul

| When | What |
|---|---|
| Before the pilot | Nothing more: R-1 is decided (B), and the restart and the three spends have Paul's yes of 2026-11-10 (Authority). |
| If a pilot gate fails | A yes or a no to a repeat pilot. Nothing is spent until then. |
| Before cobra | Cobra builds in the Go builder image, so its stage needs the image switch in `env.sh` and a second restart. Paul's yes covered one restart, so cobra waits for Paul's word on the second. |
| During the report | Check five sampled patches per repository. |
