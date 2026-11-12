# Wave 4 — the registration, prepared and not run — 2026-11-10

**Status.** Registered design. Nothing here has been run and nothing has been spent.
Decision R-1 is taken: option B, the combined test. No Wave 4 run is filed until the fixes of
part 4 are deployed. Paul's yes to the spends is recorded under Authority.

**Amendment 1 (2026-11-11).** The fixes are deployed, both repositories are re-qualified at
apparatus 2.5 and the ordered lists are appended at the end of this page. Still nothing is
spent **[hypothesis — the detail and its evidence are in Amendment 1 below]**.

**Amendment 2 (2026-11-11).** The pilot is run, at a product cost of $3.05. Two of its six
gates did not hold as written; the turn limit is 50, `k` is 15 and the wave is 60 commits in 12
batches **[hypothesis — the detail and its evidence are in Amendment 2 below]**.

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

Transcripts need both transcript fields: either one alone keeps nothing, silently **[hypothesis — read from the code, not shown by a run: `src/crb/server/worker.py` gives the builder a transcript directory only when `retain.transcripts` or the older `keep_transcripts` field is set (the registered run bodies send only the first), and `src/crb/builders/claude_code.py` keeps the stream's events only when `keep_transcript` is set]**. `learning:
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
   The wave starts only if the cut lists hold at least one commit from each repository. If
   the pilot and the cap leave either repository with none, no wave run is started and the
   design is reported as infeasible, because the claim of part 6 is about both together **[aspiration — this registration's design; nothing is run yet]**.

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
   the same four runs, so they are not treated as independent; batches are. The hypothesis
   this test rejects is that the two arms are interchangeable within every batch, so that
   swapping their labels in a batch, which changes the sign of its summed difference, leaves
   its distribution as it was. The test is exact for that hypothesis and for no weaker one:
   it is not an exact test of a zero mean, because batch differences that are skewed around
   a zero mean can reject too often. A rejection therefore says that the arms differ; the
   direction and size are read from the estimate of item 2, and the report words it so. Smallest effect of
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
   This interval is approximate: no interval of this form has guaranteed coverage for every
   distribution of batch sums, and it is reported as a description, not as a second test **[aspiration — this registration's design; nothing is run yet]**.
   The simulation that checks it is in this repository. Its model: the registered layout of 18
   batches over 81 commits; each commit has a starting chance of a clean row of 0.3, 0.5, 0.7
   or 0.9, the same for all commits or spread by a beta distribution with intra-class
   correlation 0.25 or 0.5; `S1` adds 0, 15 or 30 points; each of a batch's four runs shifts
   all its commits by one normal draw with standard deviation 0, 0.05 or 0.10; two attempts an
   arm; the truth of each setting is the mean of a 200,000-commit sample **[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/interval_sim.py` and its output `interval_sim.out.txt` beside it, seed 20261111, 4,000 waves a setting; a simulation, not a measurement of the product]**.
   Over those 108 settings the interval missed the true mean in at most 7.3% of waves, and its
   upper end fell below the true mean in at most 6.3%; the worst settings had a starting
   chance of 0.9, where the ceiling skews the differences **[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/interval_sim.py` and its output `interval_sim.out.txt` beside it, seed 20261111, 4,000 waves a setting; a simulation, not a measurement of the product]**.
   Distributions built to break it do worse: when a whole batch differs by nothing with chance
   0.9 and by half a point otherwise, the interval missed in 19.4% of waves, because a wave in
   which every batch is zero gives an interval of no width **[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/interval_sim.py` and its output `interval_sim.out.txt` beside it, seed 20261111, 4,000 waves a setting; a simulation, not a measurement of the product]**.
   The one bound that holds for every distribution (Hoeffding's, on independent batch sums)
   is 66.5 points either side on this layout, too wide to say anything about a 15-point effect **[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/interval_sim.py` and its output `interval_sim.out.txt` beside it, seed 20261111, 4,000 waves a setting; a simulation, not a measurement of the product]**.
3. **Author failures that run across batches.** The primary test treats batches as independent.
   A long failure of the test author breaks that: it turns `S1` rows into misses in several
   batches in a row. Those misses stay in the primary result, because an author that fails is
   part of what `S1` is. Beside it the report gives one sensitivity result, fixed here. A batch
   is *author-hit* if the author produced no usable test in more than half of its expected
   `S1` attempts (two for each commit of the batch, each attempt counted on its own), read
   from the runs' events. An attempt with no row, or with no event showing a usable test,
   counts as one without a usable test. Author-hit batches that follow one another in filing order
   within a repository form one block, which flips as a whole in the test and counts as one
   unit in the interval. The same test and interval are then recomputed twice: with those
   blocks, and with every author-hit batch left out. The wave is reported as
   *inconclusive*, whatever the primary p-value says, if either recomputed result falls on the
   other side of 0.05 from the primary, or has a summed difference of the other sign, or
   cannot be calculated. It cannot be calculated when no batch is left, or when fewer than two
   units are left, so that the test has no more than two sign patterns and the interval no
   degrees of freedom **[aspiration — this registration's design; nothing is run yet]**.
4. **What each outcome may be called.** *Cleared*: p below 0.05 with `S1` ahead, and both sensitivity results of item 3 also below 0.05 with `S1` ahead. *No 15-point
   effect*: p not below 0.05, both sensitivity results of item 3 also not below 0.05, the
   upper end below 15 points of the primary interval and of both recomputed intervals of
   item 3, and at least six batches with a summed difference that is not zero, and a usable test from the author in at least nine in ten of the wave's
   expected `S1` attempts (two for each listed commit; an attempt with no row or no event
   showing a usable test counts as one without). *Inconclusive*: anything else **[aspiration — this registration's design; nothing is run yet]**.
   The recomputed intervals are held to the same 15 points because a run of author-hit
   batches can leave the primary interval just under it while the interval that treats them
   as one block reaches past it; that wave is inconclusive **[aspiration — this registration's design; nothing is run yet]**.
   The nine-in-ten condition covers author failures that item 3 does not see: a failure that
   takes two commits out of every batch makes no batch author-hit, yet it can hide an effect
   the author would show when it works. Such a wave is inconclusive, not a null **[aspiration — this registration's design; nothing is run yet]**.
   The six-batch guard is there because the interval is approximate (item 2): it refuses the
   call when too few batches moved for the spread between batches to mean anything. With the
   guard, the largest share of simulated waves in which the interval's upper end fell below the
   true mean was 5.1% over the 108 settings, at a true mean of about 10 points, and 0.0% to
   1.9% under the distributions built to break the interval **[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/interval_sim.py` and its output `interval_sim.out.txt` beside it, seed 20261111, 4,000 waves a setting; a simulation, not a measurement of the product]**.
   Those figures are for the guarded interval alone in the simulated models. They are not an
   error rate for the whole *No 15-point effect* rule, they do not establish one for other
   distributions of batch sums, and the guard does not give guaranteed coverage. No error
   rate is quoted for the call, and the report states this beside it **[aspiration — this registration's design; nothing is run yet]**. Under option B the claim is about the average over the listed commits of both
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
   new amendment to this document, written before any further run. That amendment
   recalculates the cut of part 3 with the campaign's whole spend so far (the pilot and every
   set-aside wave run) in place of the pilot spend, and restates the list and the power
   figures of R-1 for it. If the cut leaves either repository with no commit, the wave is not
   restarted **[aspiration — this registration's design; nothing is run yet]**.

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

## Amendment 1 — the four lists, before the pilot — 2026-11-11

This is the first amendment of part 2, step 3. It is appended before the pilot and before any
Wave 4 run is filed. No model money has been spent: both qualify runs cost $0
**[measured — n = 2 qualify runs, method: the cost field of each run record read from the served API, apparatus 2.5]**.

**Where the lists come from.** Each repository was re-qualified at apparatus 2.5 with one
`qualify` run on the served stack, in the sealed docker posture the wave runs use
**[measured — n = 212 click commits and n = 86 cobra commits, method: one `qualify` run per repository read back from its `qualify.task` events, apparatus 2.5]**.

| Repository | Qualify run | Posture | Qualified |
|---|---|---|---|
| click | `bc2f187d4e7b41b2a578025e8e6deca7` | `pst_376b10f54191926ee83a0b50` | 93 of 212 |
| cobra | `6b8f2378095e4ace9fc838b0f4ff160f` | `pst_a308788d88899137d5fae9c7` | 74 of 86 |

**How each list was built.** A cell's pool is the commits whose `qualify.task` event in that run
reads `qualified` and whose task row is `bug.fix`, of the cell's size, of the repository's
language and in the `standard` pool. The order is `crb.core.reading.seeded_order` over that pool
with the key string shown. The orders were computed twice, once in the browser from the served
API and once with the product's own function, and the two agree
**[measured — n = 4 lists, method: the browser result from the served API compared with `seeded_order` commit by commit, apparatus 2.5]**.
Each sha256 is over the list as
written below: one commit per line, each line ended by a newline.

**One thing not checked.** The product's pool rule also requires the qualified record's projected
class and size to match the task row. That projection is not served by the API, so these pools
were grouped by the task row alone. If the product's own pool for a cell differs from the list
here when the first run is filed, the difference is reported and nothing is run on that cell
until it is explained.

| Cell | Key string | Pool size | sha256 of the full list |
|---|---|---|---|
| click XS | `replay|bug.fix|XS|python|claude_code|claude-sonnet-5|anthropic` | 31 | `d91102a0de8e342c09b31c746670af156ee0861ca8b3b4577780acd166c2baf7` |
| click S | `replay|bug.fix|S|python|claude_code|claude-sonnet-5|anthropic` | 39 | `2b9426b2354440db523ad93fa85bcba04a8df66a75598a41399ee29ac3e2d36f` |
| cobra XS | `replay|bug.fix|XS|go|claude_code|claude-sonnet-5|anthropic` | 17 | `e0debbc332169853f04e18f2fd20c389cad3b15fcf364c74be79854803755386` |
| cobra S | `replay|bug.fix|S|go|claude_code|claude-sonnet-5|anthropic` | 27 | `056057184df2b721c7802325ce05efd7fe9585dcb4d903d62fc4b321e24dad68` |

**Struck for the pilot.** The last three commits of each click list are the pilot's six commits.
They are marked `struck` below. From here on "the list" for a click cell means the list without
them **[aspiration — the pilot is not yet run; this fixes which commits it will use]**.

| Cell | Size after striking | sha256 after striking |
|---|---|---|
| click XS | 28 | `d8e785c53fb769dbfb952220a657c1279b9b2c824fa73e2a6958aebc2f4fe254` |
| click S | 36 | `b383348c0292803bc8aba70b36831410ef40016b6bfe439bf4579103fedb3978` |

### click XS — `replay|bug.fix|XS|python|claude_code|claude-sonnet-5|anthropic`

```text
 1  b5464b7e065bdfd952b1532880941f1be07e4e2b
 2  0de3704747c1399d019f1d94caeefe20123b6ef0
 3  c326df95e9e3da0425360e030413f6a3ee25fdee
 4  3f91d2154ebc47651f0cd9798250a03821473521
 5  589ca314ae8d200ff55263a2c49c8ae6341866f3
 6  1b0e19f50595a07957bd96a600c37cd44b7e0cc3
 7  71f2bafa541e7f798834e74076786ff4281ac83e
 8  762c97eef7c1b3779678992f26a553a2a8c80793
 9  1a4d8c1bb1e8f8e214ede7223bd2c05dc2ce006a
10  f316d5cb3aa89b57c14aee54da6ac9062ac5bec4
11  32ae2acd3474a57d2450ea849545b2e1258bf76a
12  d340b0c1202284a1b9d0ca892549208527d586ce
13  4fd2fea0db423d242aedcae0a5f664efe0a93484
14  ac6a2acfdb4550c35ce69ce54db502ba96c96324
15  a3321c9ca14ddb951f04ac981f275b0de2f46208
16  f3a4363d1e8383df496adb31f2a6ed037f85380c
17  f58ca3e81424a35626c8a475eb59ab95589008ce
18  a2ac5839f29f61cf7f3f229c67b97d07988e479b
19  a6e0d2936891030f5092c9869c7391104f6721d9
20  f2ae679984c3dfaa0c7639686cd793f59eb4d9b8
21  6f85d26dcd50c1745e81040ed4f2b61f8bf293cf
22  61f8101f4e0d02cb902ef17853fa35ad88185265
23  701b313160be12752e49b3f7cea32402c0969a69
24  3a3e0350b6a2ea3e799440d48e779acabcf44de9
25  1f9cd54f686eb343cec714230ad825ce972739ab
26  bf1e8be90c46428f8bf8b45f295af80cfaf2e188
27  665736bc85a19a7a2357c071394b4a545617faa3
28  422e211018e9ef8ff9a840878464d35c4c6519ac
29  7ed114f89a5997736c372faa0fa3b12d2bba377a  struck (pilot)
30  1241abaed4e441582a21f4bf90c8482de02b92df  struck (pilot)
31  82f377c547e1867d073f02bb8f476214d07e245b  struck (pilot)
```

### click S — `replay|bug.fix|S|python|claude_code|claude-sonnet-5|anthropic`

```text
 1  91de59c6c8abc8251e7af551cd4546cc964288af
 2  7d05a59b9d46a415d85937630d1d812cf477f60a
 3  c653ec820093ed1dda41aae8d35bff7834b0344a
 4  becbde5cf416441627f779e8dd34e57738ee1c1f
 5  149683755e07b62de7480b3a60a714f0a8b6618f
 6  ecb99836a44367bad62960045d586e31e4a95766
 7  546f2851f414b07413777ebcae89b2c21a685252
 8  1b524bb30d0bd39528369c7029b9296e7663cf19
 9  380008389b32ca2b7de7c73f670a9eee1562004e
10  f25f697a439acc2b0d84aa8f5413330f4e2e75cf
11  2468b70997a6ec27ced4b4867954c90da3f92075
12  b36e3ede781b388ae8135af61e83269e211acdf1
13  6de212151893e4072ca21779b7b6f4cb82452f51
14  1c20dc6e724cd5625faaa17b715ba928d44c08bf
15  5fc3423ae54990cec5a8b41d2c7b489da41475b0
16  607316f9dea85ee81f8a215f5d5ae20f7f4fff71
17  a1235aacb1be55dc66ddcfefbf64dec44b6ab54d
18  8ee83ddbf5a7a4c2eac5308c9599c5ee67ee005e
19  1787497713fa389435ed732c9b26274c3cdc458d
20  fbdd434028fe07ecf35084c945b43b938dfd639f
21  70c673d37eb91ba42a129be9037caf3ebed62f3e
22  437e1e3295c7ec979fc1bf285bb402ca20d847e7
23  051725fa7e0c69effc9107066d8791c5b99242c3
24  bec59289d8cf9b9b4010642b2fee483e5f8eeefc
25  4271fe283dc9365563aebb369ada8d20eee015a8
26  d8763b93021c416549b5f8b4b5497234619410db
27  93ba0075f4881b858b61f89a753c7c10e330027e
28  029bbeda76aa824149f110408d56de7b402a87ed
29  c3535905c77a29afc84861b29d3ad366ce5451bd
30  aaf99a3ee6935f321f755bc7c5717a91d321cd39
31  93c6966eb3a575c2b600434d1cc9f4b3aee505ac
32  b7e5fd4cc7de70280eccd39f2bb956df617e5519
33  05f6fd0df4ecbd104eb7a229f9f185c2484dee69
34  18d29196c508b249ef1111f1f29c9133e0a8b097
35  88328fc8743d43566081d9f17acad5f5552f5a87
36  4e4c7a69b7953ccb8c14e92368ca65d9525f1d2b
37  fcd85032cff78aa536a6d2b455fb83bfcc02b228  struck (pilot)
38  812b8000f79c1fbb747a2de5114fc74515558857  struck (pilot)
39  047adef258fc25566163ffc3efd14effc0ef7352  struck (pilot)
```

### cobra XS — `replay|bug.fix|XS|go|claude_code|claude-sonnet-5|anthropic`

```text
 1  a73b9c391a9489d20f5ee1480e75d3b99fc8c7e2
 2  7ce08e227e8c9db9b243dfef1e792af31d19cdd0
 3  8822449c0fb9575f1d2453e80cd3e55ab8fc2844
 4  5155946348eed0f79a76f7743407c0c933e3b5f0
 5  8a63648dd905e5c96bee06e6851a894fc75aa058
 6  22b617914c8890ba20db7ceafcdc2ef4ca4817d3
 7  e392f3204db0445f1f4ad47448b04d8c8ad04c2a
 8  ed7b60e2987d2cd54d6a391379e33effdacdadf9
 9  7790bf97fd40e285913066cf65387ad281cd6c2e
10  6f84ef48750fe6355a267117837ba6ee3da254e7
11  b9ca5949e2f58373e8e4c3823c213401f7d9d0e3
12  fdee73b4a0d0be3e233b968ab038866b7cd99772
13  b4f979ae352828a0153281b590771ce9588d67f8
14  95f2f73ed97e57387762620175ccdc277a8597a0
15  a97f9fd47b290016526c8af2dac0531fea5cd773
16  746ef07158728502482cea9f880a6f4b21ef29a9
17  1995054b003053cc1e404bccfbf6d168e8731509
```

### cobra S — `replay|bug.fix|S|go|claude_code|claude-sonnet-5|anthropic`

```text
 1  b711e8760b73c6aa1b4aa1bef3a26da5926f175d
 2  2d94892a8bec681d65a129e0a94b2e0d87e52cb9
 3  02a0d2fbc9e61d26f8e5979749f6030964a55a3e
 4  df12a0a24975e4c9f278e62927ca08d000b9be71
 5  23a6174c7f9d0c64a48e634054bdf6886fb7fbba
 6  04318720db1743b8488c86b2f7dca6d9663cb2f2
 7  a15d0990180cf0d99905ad41201211f8ac3cab53
 8  890302a35f578311404a462b3cdd404f34db3720
 9  675ae5f5a98cc705a6d54f4c487ab81230604137
10  9054739e08187aab9294b7a773d54c92fabc23d3
11  212ea4078323771dc49b6f25a41d84efbaac3a4c
12  e0fefb2b76210bd9833a12d47b2a3cf83b9f47ab
13  c3573e220c93941b06812483ee96ceaf5fa5e5cc
14  5bef9d8d87ad1a1c73e74361bad9e38b3469a58e
15  45e521ea93e2270ef7333487f0a87e3887de2da9
16  9334a46bd6b3887f3561d705440038ec93b7f62e
17  50f385938e098a69ec93b3490ff68442ec3d6524
18  0da06874266c88228b8f14615396a1f6bfc90ed7
19  6607e6b8603f56adb027298ee6695e06ffb3a819
20  0745e5576205cd05fada5bb2e01500d97e1a04be
21  b6357260812dd09c49dc7d55042f0c795b419f6b
22  40d34bca1bffe2f5e84b18d7fd94d5b3c02275a6
23  10cf7be9972ee5b5994cf760ecba642309ac8685
24  f0508c8e7665e581c7880c232466fe77b7a8964b
25  6d00909120c77b54b0c9974a4e20ffc540901b98
26  a0a6ae020bb3899ff0276067863e50523f897370
27  df547f5fc6ee86071f73c36c16afd885bb4e3f28
```

## Amendment 2 — the pilot, the cut and the batch orders, before the first wave run — 2026-11-11

This is the second amendment of part 2, step 4. Its commit is pushed to the repository before
the first wave run is filed; the report will give that commit and the time of every run beside
it. Nothing below is a result of the wave: pilot rows are never counted (part 5)
**[aspiration — this amendment fixes the wave's settings; no wave run is filed yet]**.

### The pilot

Three runs on the six struck click commits, all in campaign `cmp_88cf9e875edba15371e6d3f7`, all
at the product's default limit of 25 turns, transcripts kept
**[measured — n = 3 pilot runs of 6 commits each, method: each run record and the campaign record read from the served API, apparatus 2.5]**.

| Run | Arm | Run id | Status | Rows | Product cost |
|---|---|---|---|---|---|
| 1 | `A0`, attempt 1 | `a7c9cb6621f44125b959af46bc811691` | succeeded | 6 | $0.781581 |
| 2 | `S1@gpt-oss-120b` | `09fa16a633a64d86a26e61fa9bc9a292` | succeeded | 6 | $1.647818, of which $0.006401 is the author's calls |
| 3 | `A0`, attempt 2 | `a101480af5454bfc84ff546fdca827ed` | succeeded | 6 | $0.618152 |

The campaign's spend after the pilot is $3.047552
**[measured — n = 1 campaign record, method: `spent_usd` read from `GET /api/v1/campaigns` on the served stack, apparatus 2.5]**.

### The gates of part 5, read one by one

| Gate | Reading | Holds |
|---|---|---|
| No more than 1 of 18 builds misses for a harness reason | 2 by the checklist of part 7 as written; 1 if the author's failure is left to its own gate (see below) | **no, as written** |
| The author produces a usable test for at least 5 of 6 commits | 5 of 6 | yes |
| No `S1` build disqualified because of the authored test file | 0 disqualified rows in run 2 | yes |
| A build with no usable test still ends as a row, and its run is not halted or failed | commit `047adef2` has a row with failure kind `authoring`; run 2 succeeded | yes |
| An `S1` row's label reads `S1@gpt-oss-120b`; a transcript exists for a build of each arm | all 6 rows of run 2 carry the label; 17 of 18 builds kept a transcript, the one without is the build that never started | yes |
| The product's cost is within 10% of the provider consoles | not shown (see below) | **no** |

All six readings are of pilot rows and events
**[measured — n = 18 pilot builds, method: each row's labels, stop reason and failure kind read from `GET /api/v1/grades/<row>`, and its kept transcript read where one exists, apparatus 2.5]**.

**The two harness-reason misses.** In run 3 the builder's `git stash list` on commit `82f377c5`
was refused by the command guard and the build ended there; that is "an allowed command
refused" in spirit, a read-only command the guard does not list. In run 2 the author's test for
commit `047adef2` passed at the parent, so it could not be shown to fail there and no build was
started. Part 7 classes that as a harness miss, and part 5 also gives the author its own gate
(5 of 6), which this one failure meets. Counted as part 7 is written the first gate reads 2 of
18 and fails by one. Claude Code first reported it to Paul as 1 of 18, which was wrong against
the text **[hypothesis — the reading and its correction were made in Claude Code's session of 2026-11-11; the transcript is not in this repository]**.

**The cost gate.** The product priced the pilot's builder rows at $3.041150 from its own price
table. The Claude Code CLI's own total for the same builds is about $7.60, 2.5 times as much:
the CLI prices `claude-sonnet-5` from its own list, which fix 4 (PR #115) set aside in favour
of the product's table. When Paul read the Anthropic console on 2026-11-11 it did not yet show
that day's spend, so neither figure is confirmed against it. The gate is therefore not shown to
hold **[hypothesis — the CLI totals are in the kept transcripts on the served stack and the console was read by Paul; neither is in this repository]**.

**Paul's decision on the failed gates.** Part 5 says the wave does not start while a gate fails. Paul, who owns
the money and the registration, was shown both failures on 2026-11-11 before any wave run and
decided each in their own words. On the cost gate: "Don't blockthings for spend innaccuracies,
its minimal cost just keep pushing". On the harness-reason gate, offered a repeat pilot of six
more click commits or a start without one: "proceed without a repeat pilot". So the wave starts
with both gates recorded as failed, not as passed and not redefined: the limit of one miss in 18
stands as written and was missed by one. The two misses are an authored test that was not red at
the parent and a refused `git stash list`; the wave's stop (b) still counts every refused
allowed command, and both arms meet the same guard. A reader who holds that the gate should
have stopped the wave should read every result below as coming from a wave that started on
the operator's waiver **[hypothesis — Paul's words are from the session of 2026-11-11, which is not in this repository]**.

**The turn limit, by rule.** Eight of the 17 builds that ran ended on the 25-turn limit. Four of
them had run the tests within their last five tool turns: commit `82f377c5` in run 1 and commit
`fcd85032` in runs 1, 2 and 3. That is at least 3 of 18, so the limit is doubled, once, for
every arm: **50 turns**
**[measured — n = 18 pilot builds, method: the stop reason of each row and the commands of the last five tool turns of each kept transcript, apparatus 2.5]**.

### The cut

By the rule of part 3, with the product's costs
**[measured — n = 12 `A0` attempts and n = 6 `S1` attempts, method: run costs from the campaign record divided by attempts, author's calls included, apparatus 2.5]**:

- mean cost of an `A0` attempt: ($0.781581 + $0.618152) / 12 = $0.116644;
- mean cost of an `S1` attempt: $1.647818 / 6 = $0.274636;
- `c` = their equal-weight average = $0.195640;
- `N` = floor((95 − 3.047552) / (5 × 1.5 × 0.195640)) = floor(62.67) = **62 commits**;
- the four lists after striking hold 28, 36, 17 and 27 commits; cut to 15 they hold 60, cut to
  16 they hold 64, so **`k` = 15** and the wave is **60 commits**, 30 in each repository.

Each cut list is the first 15 commits of its list in Amendment 1. The sha256 is over the cut
list, one commit per line, each line ended by a newline
**[measured — n = 4 cut lists, method: the first 15 lines of each Amendment 1 list hashed, apparatus 2.5]**.

| Cell | Commits | sha256 of the cut list |
|---|---|---|
| click XS | 1 to 15 | `4be598d74781c45123a2183cb7657f4256f371d712ecbd33c0be780a4493370f` |
| click S | 1 to 15 | `70c884819e4a78cca97ec1768e6a3b7892b5c06d0dd9d925a9c9f61230f60a3b` |
| cobra XS | 1 to 15 | `14f3ee8612cebe6889e1da9086b07a3f94c7a1ee8182db166703cfec2320f559` |
| cobra S | 1 to 15 | `08428d27117ddf7725772a262c12567147a3351a9ac9982c1db9b2fca3dc7fb3` |

Both repositories hold commits, so the wave may start (part 2, step 4). The pilot ran at 25
turns and the wave runs at 50, so a wave attempt may cost more than `c`; the rule fixes `c`
from the pilot and it is not adjusted. The campaign's ceiling and each run's own cap are what
hold the line **[aspiration — the wave's settings; no wave run is filed yet]**.

**Where `c` comes from.** Part 3 takes `c` from "the pilot whose gates passed". This pilot
failed two of its gates and there is no other pilot, so that condition of part 3 is not met.
`c` is taken from this pilot all the same, as a stated deviation that follows from Paul's
decision to proceed without a repeat pilot. `c` rests on the product's own cost, which the
failed cost gate says may understate what the provider bills: the CLI's own total for the same
builds was about 2.5 times the product's. So the cut is a cut in the product's dollars. The
money line, the campaign's ceiling and each run's `max_cost_usd` are all counted from the
product's price table (part 3), and the provider's bill for the wave may exceed $95 by as much
as the product understates it. The cut sets how many commits the wave holds; it does not change
how a row is graded or how the test is read, and if the money line stops the wave the primary
is not read (part 3) **[hypothesis — the CLI totals are in the kept transcripts on the served stack, not in this repository; the deviation follows Paul's words quoted above]**.

### The batches and their orders

Twelve batches of five commits, six in each repository, filed in this order. The coin is the
first hex digit of `sha256("crb.wave4.order|" + repo + "|" + batch number)`, with `repo` as the
run body names it (`click`, `cobra`): an even digit gives `A0, S1, S1, A0`, an odd digit gives
`S1, A0, A0, S1` **[hypothesis — the sha256 of each of the 12 strings, computed outside the product; anyone can recompute them from the rule above]**.

| Repository | Batch | Cell | List positions | First hex digit | Order of the four runs |
|---|---|---|---|---|---|
| click | 1 | XS | 1 to 5 | `0` | `A0, S1, S1, A0` |
| click | 2 | S | 1 to 5 | `c` | `A0, S1, S1, A0` |
| click | 3 | XS | 6 to 10 | `a` | `A0, S1, S1, A0` |
| click | 4 | S | 6 to 10 | `2` | `A0, S1, S1, A0` |
| click | 5 | XS | 11 to 15 | `e` | `A0, S1, S1, A0` |
| click | 6 | S | 11 to 15 | `7` | `S1, A0, A0, S1` |
| cobra | 1 | XS | 1 to 5 | `5` | `S1, A0, A0, S1` |
| cobra | 2 | S | 1 to 5 | `a` | `A0, S1, S1, A0` |
| cobra | 3 | XS | 6 to 10 | `6` | `A0, S1, S1, A0` |
| cobra | 4 | S | 6 to 10 | `b` | `S1, A0, A0, S1` |
| cobra | 5 | XS | 11 to 15 | `6` | `A0, S1, S1, A0` |
| cobra | 6 | S | 11 to 15 | `6` | `A0, S1, S1, A0` |

Every wave run carries the body of part 2 with `budget: {max_turns: 50}`, the campaign id
above, `env_stop: 2`, `outage_stop: 3` and `max_cost_usd: 6`. All six click batches run first.
Cobra follows after the image switch and the second restart, which Paul allowed on 2026-11-11
as an operations step, once the worker is idle; cobra's posture is read again after it, and if
it differs from `pst_a308788d88899137d5fae9c7` cobra re-qualifies at no model cost and the
difference is reported before any cobra run. `S3` runs are filed last, under the rule of
part 2 **[aspiration — the wave's settings; no wave run is filed yet]**.

### The power of the test on the cut lists

The simulation was rerun for 12 batches of five. Its model is the one R-1's revised simulation
describes: a starting chance with a mean of 0.3, 0.5 or 0.7 and a within-commit correlation of
0, 0.25 or 0.5, a shock for each of a batch's four runs with a standard deviation of 0, 5 or 10
points, and the exact two-sided test at 0.05 that flips whole batches over all 4,096 sign
patterns. Across the 27 settings
**[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/power_sim.py` and its output `power_sim.out.txt` beside it, seed 20261112, 2,000 waves a setting; a simulation, not a measurement of the product]**:

- the test rejected a true null in 2.5% to 3.9% of waves;
- with 15 points of added chance it rejected in 42% to 74% of waves;
- with 20 points added it rejected in 62% to 94% of waves, and with 25 points in 82% to 100%.

The added chance is what `S1` adds to a commit's chance before the chance is clipped to
[0, 1]; it labels the figures and is not the true effect. Wherever a chance plus its shock
reaches 0 or 1 (at every mean when the within-commit correlation is above 0, and at mean 0.7
with shocks), clipping makes the realised mean difference between the arms smaller than its
label: 9.4 to 15.0 points for 15
points added, 11.8 to 20.0 for 20 and 14.0 to 25.0 for 25, over the 27 settings
**[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/power_sim.py` and its output `power_sim.out.txt` beside it, seed 20261112, 2,000 waves a setting; a simulation, not a measurement of the product]**. Each share
above therefore belongs to a realised effect at or below its label; the script prints the
realised effect of every setting beside its shares.

A wave of 60 commits has less power than the one R-1 simulated: R-1 gave 58% to 89% at 15
points on about 81 commits in 18 batches, the pools as they stood before apparatus 2.5. A wave
of this size is more likely than not to detect 20 points added and may well miss 15. The
outcome rules of part 6 are unchanged, and a result that is
neither *Cleared* nor *No 15-point effect* is reported as inconclusive
**[hypothesis — `docs/reviews/2026-11-10-wave-4-registration/power_sim.py` and its output `power_sim.out.txt` beside it, seed 20261112, 2,000 waves a setting; a simulation, not a measurement of the product]**.

From here nothing is added to or removed from the lists, and any change to the served code
stops the wave (part 6, item 9).

**Note, 2026-11-11, after review, before any wave run.** After review of this amendment, and
before any wave run was filed, three things were reworded or added: the paragraph *Where `c`
comes from*, which says that part 3's condition for `c` is not met; the labels of the power
figures, which are the chance added before clipping, with the realised effect beside them; and
the `Touch when` line of `power_sim.py`. The script now also prints the realised effect,
computed from draws it already made; its rerun reproduces every rejection share of the first
output byte for byte. No number, list or order changed: the turn limit of 50, `c`, `N`, `k`,
the cut lists and their sha256s, the 12 batch orders, the seed and every rejection share are
as first put on record in commit `ca90419a`
**[hypothesis — `power_sim.out.txt` rerun and compared with its first recording; a simulation, not a measurement of the product]**.

## Amendment 3 — pre-unblinding rules: the read, the review draw, stop (b) and the next pool — 2026-11-12

This amendment is written before the primary is read. Nothing in it is a result. No comparison
between the arms has been computed by anyone, and none was used to write it. The methodologist
read no row, no clean count and no figure by arm, and did not combine the run ledger's slot
labels with Amendment 2's batch orders
**[hypothesis — the seat's own statement of what it read on 2026-11-12; the session is not in this repository]**.

**What this amendment does not change.** `N` (62), `k` (15), `c` ($0.1956404, which Amendment 2
prints rounded as $0.195640), the turn limit (50), the seed 20261112, the four lists, the cut,
the 12 batch orders, and every threshold and decision word of part 6. Part A restates part 6
and the row rule. Parts B, C and D fill gaps the registration left open.
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**How a choice is marked.** Where the registered text left a choice, the choice is made here,
once, and marked:

> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

The registered words are quoted beside each reading. Where two readings were possible and the
text does not settle it, the reading taken is the one that is harder on the product: more waves
called *inconclusive*, fewer called *cleared*, a less flattering sample. Each reading says
whether the text settled it or the harder reading was taken. Reading the decision rule is the
methodologist's to sign (topology rule 2). Nothing here waives or changes registered matter,
which only Paul can do (topology rule 1).
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

All money figures in this amendment are **product dollars, unconfirmed**: the product's own
price table, not compared with the provider's bill.

---

### Part A. The primary read

**A1. When it may be read.** Registered: "It is read once, when every batch has been filed (and
re-filed where the row rule says so)" (part 6 item 1). All 12 batches are filed: 48 standing
runs, each `succeeded` with 5 of 5 rows, and one earlier run of click batch 3 that failed with
no row. The money stop did not fire. The campaign record read on 2026-11-12 at about 03:40Z
shows $45.791476 spent of the $95 line and $49.208524 left (product dollars, unconfirmed). That
figure includes the pilot ($3.047552), the 49 wave runs ($42.575859) and the test author's
calls. So the primary is to be read, and not declared "not read", **once every condition of
part E holds**. Until then it is not read
**[hypothesis — figures from the delivery manager's read of the campaign record and from the run ledger given to the seats; neither is in this repository]**.

**A2. Which rows count.**

1. The 60 listed commits: the first 15 of each of the four lists (Amendment 2, "The cut").
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
2. For each commit and arm, "the rows from that arm's two runs in the commit's batch" (part 2,
   row rule). That is 4 rows a commit, 240 rows in all.
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
3. For click batch 3, the rows of the filing that stands (runs `8a258976`, `78b4d435`,
   `3f67a4d0`, `5fd4dc40`). The first filing (run `98fe708c`, failed, 0 rows) is "set aside
   unread" (part 2, row rule). It holds no row, so nothing is set aside in practice.
4. "Pilot rows are never counted" (part 2, row rule; part 5).
5. No `S3` row enters the primary. Part 6 item 1 reads "`A0` against `S1`".

**A3. What a row is worth.** A row is clean or it is a miss. "Disqualified rows, missing rows,
outages, turn-limit endings and an author that produced no usable test all count as misses,
under both arms" (part 6 item 5). Clean is read from the row's own field in the product ledger.
Nobody re-grades a row. A row that carries an error is a miss, not a gap. The 240 rows all
exist, so the primary runs on 240 rows, 60 commits and 12 batches. No row is dropped, replaced
or run again.
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**A4. Harness-class rows stay in.** A miss classed harness under part 7 is still a miss in the
primary, under both arms. The table "that leaves out harness-caused misses" is description, and
"A secondary table never replaces the primary" (part 6 item 6). No part 7 class is an input to
the primary script.
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**A5. The statistic.**

1. For commit *i*: `d_i` = (clean `S1` rows ÷ 2) − (clean `A0` rows ÷ 2).
2. For batch *b*: `S_b` = the sum of `d_i` over its five commits.
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
3. `T` = the sum of all 60 `d_i` ("Statistic: the sum of the per-commit differences", part 6
   item 1).

> **R1. Direction.** Registered: "the share of its two attempts that are clean under each arm,
> and the difference" (item 1); "p below 0.05 with `S1` ahead" (item 4). The difference is `S1`
> minus `A0`. "`S1` ahead" means the summed difference is above zero. A sum of exactly zero is
> not "ahead". **The text settles this**: item 4 names the direction, and the two-sided p-value
> is the same either way.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**A6. The test.** "One exact two-sided sign-flip test at 0.05 ... in which the unit that is
flipped is the batch" (item 1). There are 12 batches, so 2^12 = 4,096 sign patterns
(Amendment 2: "all 4,096 sign patterns"). The p-value is "the share of those patterns, the
observed one included, whose summed difference is at least as far from zero as the observed
sum".
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

- The script works in whole numbers (twice each difference), so ties are exact. "At least as
  far" means greater than or equal.
- Let `m` be the number of patterns that qualify. p = `m` ÷ 4,096. p is below 0.05 exactly
  when `m` is 204 or fewer (0.05 × 4,096 = 204.8). This is arithmetic, not a new threshold.
- "This is the only p-value in the wave" (item 1).

**A7. The interval** (item 2). The estimate is `d` = `T` ÷ 60. The standard error is
`sqrt(B/(B−1) × Σ(S_b − n_b×d)²) / N`. Here `B` = 12 batches, `n_b` = 5, and **`N` (commits)
= 60**. That `N` is item 2's letter for the number of commits in the formula. It is not the
cut rule's `N` = 62 of part 3, which is unchanged. The interval is `d` plus and minus the error
times the 97.5% point of Student's t with 11 degrees of freedom (2.2010). It is reported in
points (×100). It is "a description, not ... a second test". "Below 15 points" is compared
without rounding.
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**A8. The sensitivity results** (item 3), computed in the same run of the script.

1. Count, "from the runs' events", each expected `S1` attempt with no usable test, as R12
   below defines it. Expected
   attempts are "two for each commit of the batch": 10 a batch, 120 in the wave. "An attempt
   with no row, or with no event showing a usable test, counts as one without a usable test."
2. A batch is author-hit when that count is "more than half" of 10, which is 6 or more.
3. "Author-hit batches that follow one another in filing order within a repository form one
   block, which flips as a whole in the test and counts as one unit in the interval."
4. The test and the interval are "recomputed twice: with those blocks, and with every
   author-hit batch left out". With blocks, `B` is the number of units and `n_b` the commits in
   each unit. With batches left out, `B` and `N` (commits) count only what is kept.
5. A recomputed result "cannot be calculated when no batch is left, or when fewer than two
   units are left".
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

> **R2. No author-hit batch.** Registered: "The same test and interval are then recomputed
> twice: with those blocks, and with every author-hit batch left out." If no batch is
> author-hit, there is no block and nothing is left out, so both recomputed results are the
> primary itself. They are still printed. **The text settles this**: the rule changes units
> only for author-hit batches, and "cannot be calculated" is defined only by too few units.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

> **R12. "A usable test", and the event that shows it.** Registered: "read from the runs'
> events. An attempt with no row, or with no event showing a usable test, counts as one
> without a usable test" (part 6 item 3); "an author that produced no usable test" (item 5).
> The text does not say what makes a test usable, or name the event. Amendment 2 did read it
> once, at the pilot gate: "The author produces a usable test for at least 5 of 6 commits",
> result "5 of 6", where the sixth was "an authored test that was not red at the parent" (commit
> `047adef2`, a row "with failure kind `authoring`"). So a test that is present but not RED
> at the parent is **not usable**. Reading:
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
>
> 1. **Usable means** the author's test was written and shown RED at the parent, by a test
>    that it defines, so that the builder was started with it. A test that is absent, on a
>    path that is not allowed, not RED at the parent, timed out, or RED for no test it
>    defines, is not usable. So is an attempt where the author's provider refused the call or
>    the harness failed while proving RED. The cause does not matter to this count: "an
>    author that fails is part of what `S1` is" (item 3).
> 2. **What the script reads.** The stored events of each `S1` run, from the run's event log
>    (`GET /api/v1/runs/<id>/events/log`), and the `task` key of each event's payload. Two
>    actions matter: `builder.author_test.start` and `builder.author_test.failed`. The
>    product writes no event that says "usable" in so many words. It writes `start` when the
>    author step begins and `failed`, once, on every way that step can end without a usable
>    test.
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
> 3. **The count.** An expected `S1` attempt (one commit in one `S1` run) has a usable test
>    only if all four hold. (a) The attempt has a row. (b) The run's events hold a
>    `builder.author_test.start` for that commit's task. (c) The run's events hold no
>    `builder.author_test.failed` for that task. (d) The row's `error` field does not begin
>    with `authoring:`. If any one fails, or cannot be read, the attempt counts as one
>    without a usable test. Test (d) is a row field, not an event; it can only lower the
>    count. The script reads no clean field for this count.
> 4. **One count serves both rules**: the author-hit rule of item 3 (A8 items 1 and 2) and
>    the nine-in-ten rule of item 4 (A9 item 3). The script prints the count for each batch
>    and for the wave.
> 5. **A check on names, made on code and not on rows.** The two action names and the
>    `authoring:` prefix are those of the product's code and event table at `32630d12`. The
>    wave was served from `7bb03d6c`, which the seat may not read. Before the script of R5 is
>    committed, the delivery manager confirms from the served code that it writes these names.
>    If it does not, the read waits and this reading is corrected first, before any result by
>    arm exists. Without that check a changed name would count all 120 attempts as without a
>    usable test.
>
> **The text does not settle it, so the harder reading is taken**, and it is the one
> Amendment 2 already applied to the pilot. It is harder in two plain ways: it can only
> lower the count held against nine in ten, and it can only add author-hit batches, never
> remove one. The softer reading, any test file the author returned, would count a test that
> was never RED as usable.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
>
> The names in item 2 are from the code
> **[measured — n = 2 event actions and 1 error prefix, method: read in `src/crb/builders/adapter.py` and the event table of `docs/API.md` with read-only `git show` and `git grep`, commit `32630d12`, apparatus 2.5]**.

> **R3. A sum of exactly zero.** Registered: the wave is inconclusive "if either recomputed
> result ... has a summed difference of the other sign". The text does not say what a zero sum
> is. Two readings are possible. The softer one: zero is not "the other sign". The harder one:
> a recomputed sum counts as "of the other sign" whenever its sign differs from the primary's,
> with three signs, below zero, zero and above zero. So zero against a non-zero primary, or
> non-zero against a zero primary, makes the wave *inconclusive*. Two zeros are the same sign.
> **The text does not settle it, so the harder reading is taken.** It calls more waves
> inconclusive and none cleared that the softer reading would not. This reverses the softer
> reading in the seat's first draft; the change was made before any result existed.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**A9. The decision words** (items 3 and 4), applied in this order. No other word may be used.

1. ***Inconclusive*, by item 3**: "whatever the primary p-value says, if either recomputed
   result falls on the other side of 0.05 from the primary, or has a summed difference of the
   other sign, or cannot be calculated". "The other side" means one is below 0.05 and the other
   is not.
2. ***Cleared***: "p below 0.05 with `S1` ahead, and both sensitivity results of item 3 also
   below 0.05 with `S1` ahead".
3. ***No 15-point effect***: "p not below 0.05, both sensitivity results of item 3 also not
   below 0.05, the upper end below 15 points of the primary interval and of both recomputed
   intervals of item 3, and at least six batches with a summed difference that is not zero, and
   a usable test from the author in at least nine in ten of the wave's expected `S1` attempts".
   Nine in ten of 120 is 108 or more. The count is the one R12 defines.
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
4. ***Inconclusive***: "anything else".

> **R4. The six batches.** Registered: "at least six batches with a summed difference that is
> not zero". The six are counted once, among the 12 batches of the primary. **The text settles
> this**: item 3 uses "unit" for blocks and "batch" for batches, and item 4 says "batches" and
> gives one count. A harder reading, the same count in each recomputed result, would add a
> condition the text does not hold, so it is not taken.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

A rejection "says that the arms differ; the direction and size are read from the estimate of
item 2, and the report words it so" (item 1). "Nothing is claimed for either repository alone"
(item 4). "No error rate is quoted for the call" of *No 15-point effect* (item 4).

**A10. How the read is done.**

> **R5. Read once, by one script.** Registered: "It is read once" (item 1). The text does not
> say how. Reading:
> 1. One script computes A5 to A9. It is written and tested on made-up rows only. It is
>    committed, and its sha256 recorded, before it touches a Wave 4 row.
> 2. The script first checks, from the run bodies, that every run's arm is the arm Amendment 2's
>    order gives its place in its batch, and that the 48 run ids are the standing runs. If any
>    check fails it stops and prints no figure.
> 3. It is run once on the 240 rows. Its whole output is filed unedited with the 48 run ids.
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
> 4. The delivery manager runs it. The methodologist and the validity engineer each sign the
>    reading, and either can block (topology rule 4). Until both sign, the primary is open.
> 5. Until the output is filed, nobody computes a clean count by arm, by repository, by cell or
>    by batch: "no comparison between the arms is computed, on click or anywhere" (item 1).
>
> **The text does not settle the method; this is the reading that leaves the least room.** A
> second run, or a figure seen before the script is fixed, would be a second read.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

---

### Part B. The review sample and Paul's audit (part 6 item 8)

Registered, in full: "Ten clean patches per arm per repository, drawn where possible from
commits clean under both arms, compared with the real commit by a reviewer who is not told the
arm: merge as is, merge with small edits, or do not merge. Reported as counts. Paul checks five
as an audit of the reviewer" (part 6 item 8). And: "Check five sampled patches per repository"
(part 9, the table of what needs Paul). The registration gives no draw rule. The topology
document cites this as "part 6 item 7"; the committed number is item 8.
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**B1. When.** The rule is fixed now. The draw is run only after the primary is read and signed.
It needs the clean and arm fields, so it cannot run earlier.

**B2. The ten patches, for each repository `R` and each arm `A`.**
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

1. A patch is one clean row (commit, arm, attempt) from the rows of A2. Attempt 1 is the row
   from the first-filed of the arm's two runs in the batch. Attempt 2 is the other.
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
2. Order the 30 commits of `R` by ascending
   `sha256("crb.wave4.review|20261112|" + R + "|" + commit)`, ties by commit. `R` is `click`
   or `cobra`, as the run body names it. The commit is its full 40-character id.
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
3. Walk that order and take one patch a commit: the clean row of arm `A` with the lower attempt
   number. First take commits clean under both arms. If that gives fewer than ten, carry on
   with the other commits that have a clean row under `A`. If still fewer than ten, walk the
   order again and take second clean rows. If still fewer than ten, review all there are and
   report the shortfall as a count.
4. The drawn list and its sha256 are filed before the reviewer sees a patch. The reviewer is
   not told the arm.

> **R6. "Clean under both arms".** Registered: "drawn where possible from commits clean under
> both arms". A commit is clean under both arms when it has at least one clean row under `A0`
> and at least one under `S1`. The other reading is that all four rows are clean. **The text
> does not settle it, so the harder reading is taken.** "All four clean" would keep only the
> easiest commits, and their patches would flatter the merge counts.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

> **R7. The order of the draw.** Registered: "Ten clean patches per arm per repository". The
> text gives no order. Reading: B2 items 2 and 3. One commit order serves both arms, so the
> same commits are reviewed under both arms where possible. One patch a commit comes first, so
> ten patches are not ten views of three commits. The lower attempt is taken, so no one picks
> between two clean rows. **The text does not settle it; nothing in this order uses a result
> beyond the clean field the registered rule already requires.**
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**B3. Paul's audit.**

1. For each repository, order its reviewed patches (up to 20) by ascending
   `sha256("crb.wave4.audit|20261112|" + R + "|" + A + "|" + commit + "|" + attempt)`, ties by
   commit, then arm, then attempt. `A` is `A0` or `S1`. Attempt is `1` or `2`.
2. Paul checks the first five of each repository: ten patches in all.
   **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
3. He takes them in this sequence: click 1, cobra 1, click 2, cobra 2, and so on to click 5,
   cobra 5. If he checks fewer than ten, the ones checked are the first in that sequence, and
   the report states the shortfall against part 9.
4. The result is reported as counts of agreement with the reviewer, and nothing more.

> **R8. Five or ten.** Registered: "Paul checks five as an audit of the reviewer" (part 6
> item 8) and "Check five sampled patches per repository" (part 9). Read together, they mean
> **five per repository, ten in all**. I agree with the delivery manager's account of the two
> texts, for three reasons. Item 8's sentence sits inside a rule scoped "per arm per
> repository" and gives no scope of its own. Part 9 is the table of what Paul is asked, it
> states the scope outright, and Paul approved the registration with it. And ten is the harder
> reading: it is the larger audit of the reviewer. So **the text settles it when both parts
> are read together**, and the harder reading agrees. This commits no time of Paul's beyond
> what part 9 already asked. The alternative, five in all, would need Paul to waive part 9's
> words in writing; the sequence in B3 item 3 already fixes which patches those would be.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

> **R9. What Paul is told.** Registered: "a reviewer who is not told the arm". The text
> withholds the arm from the reviewer and is silent on Paul. Reading: Paul is not told the arm,
> or the reviewer's verdict, until he has given his own. **The text does not settle it, so the
> harder reading is taken.** An auditor who has seen the verdict tends to agree with it.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

> **R10. The number 20261112 in the hash strings.** Registered: seeded orders by sha256 (part 2,
> step 2 and "Run order"); "seed 20261112" for the power simulation (Amendment 2). The strings
> `crb.wave4.review|20261112|`, `crb.wave4.audit|20261112|` and `crb.d3.repo|20261112|` reuse
> that number as a fixed label. The seed itself, and the simulation that uses it, are not
> changed. Each hash is over the UTF-8 bytes of the string, printed as lower-case hex.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

---

### Part C. Decision D3: the selection rule for the next certifying reading's commit pool

This is a commitment made before unblinding. It changes nothing in the Wave 4 design.

Its source is decision D3 of the product meeting of 2026-11-11: "Before Wave 4 is unblinded,
commit the rule by which the commit pool for the next certifying reading will be chosen,
including the rule for choosing at least one repository the team has not tuned the harness on.
The pool itself is listed in that reading's registration, on commits no seat has read." D3 also
says adding a repository "needs Paul's answer to Question 4". The delivery manager, deciding as
managing director on Paul's instruction of 2026-11-11, answered Question 4: "Approved in
principle ... Registering it costs nothing. Any spend on it is a new budget line and goes to
Paul with a figure." If that answer is later held not to stand for Paul's, D3's own fallback
applies: the rule "draws from click and cobra only and the untuned repository is recorded as
outstanding"
**[hypothesis — quoted from the programme's meeting minutes and decisions page of 2026-11-11, which are not in this repository]**.

> **R11. The rule.** Registered: Wave 4 "uses up these commits for any later certifying reading
> on click and cobra at `bug.fix` XS and S" (part 2). D3 as quoted above. Reading:
>
> 1. **Eligible commit.** A commit is eligible only if it has no build row in the product
>    ledger at any apparatus version, under any arm, and it is on no list in Amendment 1. That
>    bars all 114 listed commits: the 60 of the wave, the six struck for the pilot and the 48
>    of the uncut tails.
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
> 2. **Untuned repository.** A repository is untuned when all of these hold: it is not
>    registered on the stack on 2026-11-12; it has no build row in the ledger; and no harness
>    fix, prompt, checklist, arm file, ADR or backlog item has been written with reference to
>    it. The pool of the next certifying reading holds at least one untuned repository.
> 3. **Where it comes from.** Only from the candidate list of C1 below. No name may be added
>    to that list. A name is dropped only by the mechanical checks of item 4.
> 4. **Which one.** The candidates are taken in the order of C2. The untuned repository is the
>    first name that passes every check: it can be cloned without credentials; its language is
>    Python or Go; its own test suite runs in the existing builder image; it is still untuned
>    under item 2; and its qualify run, at no model cost, leaves at least one eligible commit
>    in every cell that reading measures. The cells are fixed in that reading's registration
>    before the first candidate is qualified. Every candidate tried, and the check it failed,
>    is reported. If no candidate passes, the untuned repository is recorded as outstanding and
>    the reading certifies nothing about an untuned repository.
> 5. **Order and cut.** Within each cell the pool is its qualified, eligible commits in the
>    product's seeded order (part 2, step 2). The cut is by that registration's own money rule.
>    The full lists and their sha256s are appended to that registration before its first run.
> 6. **Nothing from Wave 4 picks a commit or a repository.** No Wave 4 result, cause code or
>    review verdict adds, drops or reorders one.
> 7. **Money.** Registering and qualifying cost nothing. Any model spend on the repository is
>    a new budget line and goes to Paul with a figure.
>
> **The registered text does not hold this rule; D3 asks for it.** Where there was a choice,
> the harder one was taken: the list is closed today, the order is by hash and not by any
> seat, and a failed candidate is reported and not quietly replaced.
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

**C1. The candidate list, written now.** Rule for the list: a public repository; Python or Go,
because those are the builder images that exist; with its own test suite; not click and not
cobra; and not registered on the stack. The repositories registered on the stack today are
click, cobra, koa, mesh-client, nhsuk-frontend and nhsuk-react-components. Two further tests
were applied by the seat. No repository of the `pallets` or `spf13` owners is listed, because
the team has worked on their code. And each name below was searched for in `docs`, `src` and
`tests` of this registration's commit (`32630d12`), ignoring case, in three ways.
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

1. Each `owner/name` as a fixed string. All 12 match no file.
2. Each owner as a whole word. Ten of the 12 match no file. The owner `jd` matches no file
   as a whole word. The owner `rs` matches 39 files as a whole word. Those hits are the Rust
   file ending `.rs` and the like, not the repository.
3. For those two, the repository's own name anywhere in a line. `zerolog` and `tenacity`
   match no file. Neither do `github.com/rs` and `github.com/jd`.

A plain substring search for the owner alone does not give zero, and the seat's first wording
was wrong to say it did: `rs` is inside 750 files and `jd` inside 15, as parts of other words.
So no listed repository is referred to there, by method 1 for all 12 and by methods 2 and 3
for the owners
**[measured — n = 12 names, method: read-only `git grep -i -l -F` on commit `32630d12`, paths `docs`, `src`, `tests`; `owner/name` 12 of 12 zero files; owner with `-w` 11 of 12 zero files and `rs` 39 files; `zerolog`, `tenacity`, `github.com/rs`, `github.com/jd` zero files; owner without `-w`: `rs` 750 files, `jd` 15 files, the other ten zero, apparatus 2.5]**.

The twelve names were written down before any hash was computed. Six are Python and six are Go.
The seat had no network. That each is public, in the stated language and has its own test suite
is the seat's own knowledge, not checked today; the checks of R11 item 4 test each one
mechanically at selection
**[hypothesis — the seat's general knowledge of these repositories; not checked against the network on 2026-11-12]**.

**C2. The order.** Ascending `sha256("crb.d3.repo|20261112|" + owner + "/" + name)`, ties by
`owner/name`. Computed with the Python standard library; anyone can recompute it from the rule
**[hypothesis — the sha256 of each of the 12 strings, computed outside the product]**.

| Place | Repository | Language | sha256 of `crb.d3.repo|20261112|owner/name` |
|---|---|---|---|
| 1 | `gorilla/mux` | Go | `0c423f70451c20084e6e23ee26d0c8527b9f001f4c14123754ed8b72ad6e8ffb` |
| 2 | `jpadilla/pyjwt` | Python | `1570d839d6ea6d427c7f5c078e6b3249ac81b9f84eb37fa6baf8ba925e44031b` |
| 3 | `rs/zerolog` | Go | `3e1c2a5b20c514db528e02fc2ebed837b4eec44aee82a53cca6c4e69476bff9c` |
| 4 | `hynek/structlog` | Python | `6346b19e791f1001532d1f08bd9f3cb528f59c8ee54a1166c83720a8ed28761f` |
| 5 | `pelletier/go-toml` | Go | `7abe50ab47eb78139eac8f23ed8f6a0c98b5685f1ac6587e99ee3292b13e48ed` |
| 6 | `jd/tenacity` | Python | `989617ce4221038db2cac58905579a57858b8edd4107b5f35cd011a91b0eb40b` |
| 7 | `sirupsen/logrus` | Go | `a54e5b77161adf1477892a2c5ffc6d86c84a70155e41cd2c4af36a25eccbd7a2` |
| 8 | `tox-dev/filelock` | Python | `c734df9a7bc739b2f6a2e7a8595cef45a91ed99d49cd1744c1f3871d02f32503` |
| 9 | `marshmallow-code/marshmallow` | Python | `d2891d30bde677997e838ff2eae00c949ea93d7d974a1608eedee3f170e8a290` |
| 10 | `hashicorp/go-version` | Go | `f0a645d21d930c47d6feb8753fd7031a4fc530475c240f3dd919627fab020901` |
| 11 | `urfave/cli` | Go | `f12d0a4f43b5daef7ceca7c8e9b05010f9a2f30095ed3430e26f4de874c8df5f` |
| 12 | `more-itertools/more-itertools` | Python | `f1a8dac473fde82a2240b750c840b6d1239b2c7aeba324906ab574eab694c402` |

The sha256 of the list as ordered above, one `owner/name` a line, each line ended by a newline,
is `b38fb8b6b8de3bf50ebc88b54e6dd54c1d9578bc2c5209c47fcc8350a612a1de`.

From this amendment's commit until that reading's registration is filed, no harness fix,
prompt, checklist or arm file is written with reference to a listed repository. If one is, that
repository is no longer untuned and is dropped under R11 item 4, and the report says so.

---

### Part D. Stop (b): the three counts and the methodologist's position

Registered: "(b) Four or more of the first 40 wave builds ending on an outage, a provider
error, a container failure or a refused allowed command, counted from row fields" (part 6
item 9). Amendment 2, written before the wave, said of the pilot's refused `git stash list`:
"that is 'an allowed command refused' in spirit, a read-only command the guard does not list",
and "the wave's stop (b) still counts every refused allowed command".
**[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**

**The facts.** The first 40 wave builds are click batches 1 and 2. Nine of them ended in an
error. Five were authored tests not red at the parent. Two were a refused `git stash`. One was
a refused `git log` and one a refused `git show`. None was an outage, a provider error or a
container failure. The count depends on the reading of "a refused allowed command"
**[hypothesis — row `error` fields read by the delivery manager from the served API on 2026-11-11; the responses are not in this repository]**:

| Reading | Count | Does the stop fire? |
|---|---|---|
| Strict: the guard forbids all three commands, so none is an allowed command | **0** | no |
| `git stash` only, as Amendment 2 treated the pilot's refused `git stash list` | **2** | no |
| Every refused read-only git command | **4** | **yes** |

**How it was decided.** The strict reading was applied by the delivery manager during the click
runs and first reported to Paul as 0, without the other two. The methodologist raised the
ambiguity from pooled figures. Paul was then shown all three counts and decided to continue
under the strict reading: "Happy to proceed with the [recommendations]". That decision was made
on 2026-11-11, before any cobra run, **after 110 pooled click rows existed**. No comparison by
arm had been made. So this reading was fixed after rows were seen, and it is recorded as a
deviation (annex, row D2)
**[hypothesis — Paul's words are from the session of 2026-11-11, which is not in this repository]**.

> **The methodologist's position.** I do not sign the strict count of 0 as the only reading the
> registered text supports. I sign the following.
>
> 1. **Two readings have support in the text.** "Allowed command" is the registration's own
>    term for a command on the guard's allow-list (part 4, fix 3). On that, 0 is right.
>    Amendment 2 then counted a refused `git stash list` as "an allowed command refused" in
>    spirit, and said in the same paragraph that stop (b) "still counts every refused allowed
>    command". On that, 2 is right. Amendment 2 was written before the wave; the strict reading
>    was fixed after rows existed. So where one count must be named, **the count I sign is 2,
>    not 0**. It is the harder of the two supported readings.
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
> 2. **Under both supported readings the stop did not fire.** Two is fewer than four. On that
>    ground I sign the reading "continue", and I do not block the read of the primary.
> 3. **The widest reading, 4, is not the registered one, but the text does not shut it out.**
>    It needs "in spirit" stretched from a command "the guard does not list" to `git log` and
>    `git show`, which the guard names and refuses on purpose ("no history/other revisions").
>    Amendment 2 did not go that far. I do not take it. I cannot say the words forbid it.
> 4. **What a reader should conclude.** The wave passed stop (b) at 0 or at 2. At 4 it would
>    have stopped, every row so far would have been set aside, and the wave would have started
>    again under a new amendment. A reader who holds the widest reading should treat every
>    Wave 4 result as coming from a wave that passed its stop (b) on the operator's decision,
>    made after 110 pooled rows were seen. The report prints all three counts and this
>    sentence on its first page, beside the pilot-gate waiver of Amendment 2.
> **[aspiration — a rule for the read, fixed before any result by arm exists; the read is not yet made]**
> 5. **It changes no row.** No row is added, dropped, re-read or re-classed by this statement.
>    The seat's earlier answer of 2026-11-11, which called the strict reading the count of
>    record, was an unsigned draft written without the committed text; this statement replaces
>    it. The next registration will write this stop as a closed list of row-field tests, so
>    that it has one reading.
>
> **[reading, signed by the methodologist 2026-11-12, before any result by arm exists]**

---

### Part E. Conditions that must hold before the primary is read

None of these needs a result by arm. If any one fails, the primary is not read until it is
put right or Paul rules in writing.

1. **This amendment is committed and hashed.** Its commit and the sha256 of the registration
   file with this amendment appended are recorded before the script of R5 touches a row. The
   script's own commit and sha256 are recorded with them.
2. **The cost gate. It is not met as written, and it is Paul's to rule on.** The gate is a
   team rule, not registered text: "Before cobra spend (a gate, not an option): cost
   metrologist reconciles click (needs Paul's Console figure/export) ... A block here yields
   'primary not read', never a click-only reading" (topology section 3 task 2). Three facts.
   **[hypothesis — read from the served stack and the session of 2026-11-12 by the seats; the rows and the transcript are not in this repository]**
   - It was not held in order. Cobra started at 23:28Z on 2026-11-11 without it. The
     reconciliation was done on 2026-11-12, over both stages.
   - It is not the reconciliation the gate asks for. The cost metrologist's verdict reads:
     "The ledger adds up, and the wave runs are well under the line. The reconciliation is
     one-way only, not three-way, and three gaps stay open." No Console figure or export
     exists. The metrologist did not say "passed", and neither does this amendment.
     **[hypothesis — read from the served stack and the session of 2026-11-12 by the seats; the rows and the transcript are not in this repository]**
   - The metrologist's block is about labelling only: the figures "may go into the report
     only when labelled 'product dollars, not confirmed against the provider'. No figure may
     be called provider-confirmed." It does not say the primary may be read.

   What is established, in product dollars, unconfirmed: the product's figures agree with
   themselves; stop (a) did not fire on them; the independent check reproduced them; and the
   $0.067900 gap seen before cobra is the test author's spend, which the campaign counts and
   a run's own cost does not.

   What is not established: that the product's figures match the provider's bill.

   Only Paul can close this. The delivery manager "cannot skip, defer or re-scope" a trigger;
   "only Paul can, in writing" (topology rule 7). The registration auditor rates the gate a
   fail against the team rule and names Paul as its owner. So **this condition is open. The
   primary is not read until Paul has done one of two things in writing**: given the Console
   figure or export, so that the metrologist can finish the reconciliation; or said that the
   gate is deferred and the primary may be read on product dollars, unconfirmed. The seat
   holds no such word from Paul for this gate. Paul's words on the pilot's cost gate, quoted
   in Amendment 2 ("Don't blockthings for spend innaccuracies, its minimal cost just keep
   pushing"), were given for that gate on 2026-11-11. The methodologist does not stretch them
   to this one. If Paul's word is given, it is quoted in the wave record with its date, and
   every cost figure in the report still carries the label "product dollars, unconfirmed".

   The skipped order is deviation D5 of the annex. That row uses the delivery manager's word
   "passed". This item, not that word, is the methodologist's position. No registered number
   moves either way: the primary counts clean rows, not dollars
   **[hypothesis — the cost metrologist's report, its independent check, the registration audit and the delivery manager's facts of 2026-11-12; none is in this repository]**.
3. **`S3` does not gate the primary.** Registered: "`S3` runs are filed last and only while the
   remaining line still covers every outstanding blind row at one and a half times the running
   cost per attempt" (part 2); `S3` is among "Everything else is description, with no tests"
   (part 6 item 6). No blind row is outstanding and $49.21 is left (product dollars,
   unconfirmed), so the condition for filing holds. The decision to file was taken before the
   read, so it cannot depend on the result. How `S3` rows are handled:
   - No `S3` row enters the primary, the interval, the sensitivity results or the decision word.
   - Nobody computes or looks at an `S3` clean count until the primary is filed and signed.
   - `S3` rows are reported in their own table, as description, with their run ids and filing
     times, as item 6 lays out: "`S3` against each blind arm, with the blind rows that the
     test-files check alone disqualified listed beside it".
   - The six cobra `S3` runs are being filed from 2026-11-12, same campaign, same caps. The six
     click `S3` runs wait for the next restart Paul grants. Until they exist the report says
     "click `S3`: not yet filed", and shows no `S3` figure for click.
   - If click `S3` is filed after any change to the served code or apparatus, its rows are
     shown apart and labelled with their apparatus. They are never blended with rows at 2.5.
4. **The served code did not change during the wave** (stop (c), part 6 item 9). The served
   commit is checked to be the same from the second amendment to the last blind run. The notes
   show `7bb03d6c`, unchanged, at the second restart.
5. **The filing order is checked by the script**, from run bodies, as R5 item 2 says. No seat
   does this by hand from a ledger.
6. **The product owner's outcome decisions are committed** and their hash recorded, as that
   document itself requires before the primary is read.
7. **No seat-facing ledger carries a slot label.** From now on any ledger given to a seat
   before the primary is signed is sorted by run id and has no slot column (annex, row D6).

One matter does not gate the read and is stated in the report: Amendment 1's "One thing not
checked" (the product's own pool against the listed pool). The wave's runs named their commits
by explicit `task_ids` from the listed pools. The report says whether the product's pools were
compared with the lists, and what was found.

---

### Annex. The deviation log

This is the delivery manager's deviation log of 2026-11-12, as given to the seats, unchanged
in substance. It is to be committed with the wave record. Rows are numbered as the delivery
manager numbered them. **Row D3 of this log is not decision D3 of the product meeting** (Part C).
Every cost is in product dollars, unconfirmed
**[hypothesis — the delivery manager's log of 2026-11-12; the events it records are not in this repository]**.

| # | When (UTC) | What | Registered text | Effect |
|---|---|---|---|---|
| D1 | 2026-11-11 | Both pilot gates failed and were waived by Paul | Part 5 | Recorded in Amendment 2 |
| D2 | 2026-11-11 | Stop (b) read under the strict reading on Paul's decision, after 110 pooled click rows existed; counts 0, 2, 4 recorded | Part 6 item 9 | Wave continued; a reader holding the widest reading treats the wave as passing stop (b) on the operator's decision |
| D3 | 2026-11-11 | Click-3/1 failed at gold control; batch 3 filed again once | Part 2 row rule | Within the rule |
| D4 | 2026-11-11 | Runs from click-3/1 onward filed by the `svc-claude` operator account; a poster crash and a login-verify timeout before batch 3, no run lost | none | None on rows |
| D5 | 2026-11-11 | Cost gate before cobra not held in order; done after both stages, passed | Topology section 3 task 2 | Order only |
| D6 | 2026-11-12 | Seat-facing ledger carried slot labels (arm derivable) | Wave rule | No seat combined them; fixed for later ledgers |
| D7 | 2026-11-12 | Cobra `S3` filed after the blind runs; click `S3` deferred to the next granted restart | Part 2 run order, Amendment 2 | `S3` is description only |
| D8 | 2026-11-12 | Costs are product dollars; the provider's bill is not yet compared | Part 3 | Labelled "product dollars, unconfirmed" everywhere |

Notes beside the log, from the same source. The failed first filing of click batch 3 (run
`98fe708c`) ended at its gold control before any build, with 0 rows and $0.00 (product dollars,
unconfirmed); its cause was not diagnosed and is on the backlog as "flaky click gold test".
The campaign record shows $45.791476 spent, of which $0.174468 is the test author's calls, and
$49.208524 left, over 52 runs (3 pilot, 49 wave), all in product dollars, unconfirmed, read
before any `S3` run. On row D2, Part D of this amendment gives the methodologist's own
position, which differs from the strict reading and changes no row.
**[hypothesis — read from the served stack and the session of 2026-11-12 by the seats; the rows and the transcript are not in this repository]**

Two notes by the delivery manager, added on 2026-11-12 before this amendment was committed and
before any result by arm exists. They change no reading.
**[hypothesis — read from the served stack and the session of 2026-11-12 by the seats; the rows and the transcript are not in this repository]**

1. Row D5's word "passed" is withdrawn. The reconciliation was one-way only and there is no
   Console figure. Part E item 2 states the position: the gate is open and is Paul's to rule on.
   **[hypothesis — read from the served stack and the session of 2026-11-12 by the seats; the rows and the transcript are not in this repository]**
2. The name check that R12 item 5 asks for was made. The served code writes the two event
   actions and the error prefix that R12 names
   **[measured — n = 2 event actions and 1 error prefix, method: read-only `git grep` for `author_test` and `authoring:` in `src/crb` and `docs/API.md` of the served checkout, commit `7bb03d6c`, apparatus 2.5]**.

---

### Signature

Seat: **methodologist**, crb programme.
Date: **2026-11-12**.
Signed before the primary is read, and before any result by arm exists.

Signed here: readings R1 to R12, the stop (b) statement of Part D, and the conditions of
Part E. Condition 2 of Part E is signed as open: it waits for Paul's written word. The
validity engineer's signature on the reading itself is separate and is given, or
withheld, after the script's output is filed (topology rule 4).

**Nothing in `N`, `k`, `c`, the turn limit, the seed, the lists, the orders or the thresholds
is changed by this amendment.** `N` is 62, `k` is 15, `c` is $0.1956404, the turn limit is 50,
the seed is 20261112, the four lists and the 12 batch orders are as Amendments 1 and 2 give
them, and every threshold and decision word of part 6 stands as registered.
**[hypothesis — read from the served stack and the session of 2026-11-12 by the seats; the rows and the transcript are not in this repository]**
