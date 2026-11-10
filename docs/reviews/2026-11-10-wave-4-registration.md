# Wave 4 — the registration, prepared and not run — 2026-11-10

**Status.** Draft for Paul Glover to read. Nothing here has been run and nothing has been spent.
Decision R-1 is taken: option B, the combined test. No Wave 4 run is filed until the fixes of
part 4 are deployed and Paul has said yes to each spend.

**Authority.** Paul's "yes to all four, go ahead" of 2026-11-10 (the Wave 3 closure; this design
with a money line of $60 for stage 1 and $35 for stage 2, in real dollars; apparatus 2.5 with a
short ADR; `gpt-oss-120b` on Cerebras as the test author), and his "Yes" of the same day to three
points: the freeze ends when #111 merges, Wave 4 stands under Wave 3's Stop verdict, and
disqualified rows count as misses **[hypothesis — Paul's words in the session of 2026-11-10, quoted by Claude Code]**.

**Claims in this record.** Nothing here is measured on a Wave 4 row. Wave 3 figures are quoted from
its stage-1 report (#111). Pool counts were read from the served stack on 2026-11-10 at apparatus
2.4 and will change when every commit re-qualifies at 2.5. Costs are estimates. Power figures come
from a simulation of the registered test, not from data.

**Review.** Two independent reviewers checked the first draft, one on the statistics and one
against the product's code. This version takes in all fourteen of their findings **[hypothesis — the review ran in Claude Code's session on 2026-11-10; its output is not in this repository]**.

## Decision R-1: option B, the combined test

**Decided 2026-11-10.** Asked to choose between A and B, Paul answered "I'm happy for you to make
the best decisions for our products future". Claude Code chose B on that authority: it is the
only option able to settle the effect the wave is built to find. The delegation covers the
design; it does not cover spending, and each spend still waits for Paul's yes. The table and the
reasoning are kept below as the record of what was weighed.

The approved design assumed 40 qualified click commits in each of XS and S. The served stack
holds fewer. Read on 2026-11-10 from `GET /api/v1/repos/<repo>/tasks`, `bug.fix` only:

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
   each list are appended to this document in an amendment commit **before the pilot**.
4. After the pilot, one per-cell cap `k` is set by the money rule of part 3 and each list is cut
   to its first `k` commits. `k`, the turn limit and the campaign id are appended in a second
   amendment **before the first wave run**. Nothing is added or removed after that.

All four steps are design **[aspiration — this registration's design; nothing is run yet]**.

**Run order.** Commits are taken in batches of ten, in list order, XS and S alternating. Each batch
is four blind runs filed one after another, never in parallel. A seeded coin per batch (the first
hex digit of `sha256("crb.wave4.order|" + repo + "|" + batch number)`, even or odd) picks the
order `A0, S1, S1, A0` or `S1, A0, A0, S1`. Each arm therefore sits equally early and late within
every batch, and neither drift in the model nor a service outage can line up with one arm by
design. All blind batches of click run first, then, after the image switch, all blind batches of
cobra. `S3` runs are filed last and only while the remaining line still covers every outstanding
blind row at one and a half times the running cost per attempt. The report prints the realised
schedule with times **[aspiration — this registration's design; nothing is run yet]**.

**Row rule.** Fixed here so that no choice about rows can be made after results are seen **[aspiration — this registration's design; nothing is run yet]**.

- A commit's attempts under an arm are the rows from that arm's two runs in the commit's batch.
- If any of a batch's four runs halts, fails or returns fewer rows than it has commits, the whole
  batch is filed again once, all four runs, and the first filing's rows are set aside unread. The
  trigger is the run's status and row count, never its results.
- After that, a row that is still missing counts as a miss. That covers a commit the product
  drops because it stopped qualifying, an outage, and a halted run.
- Pilot rows are never counted.

## 3. Money

| Item | Estimate | Line |
|---|---|---|
| Pilot | about $3 | inside the stage-1 line |
| Option A, stage 1 (click) | about $33 | $60 |
| Option A, stage 2 (cobra) | about $23 | $35 |
| Option B, whole wave | about $57 | $95 |

Estimates use Wave 3's real cost of about 13 cents an attempt. The test author's calls and a
higher turn limit will add to it; treat each estimate as plus or minus 50%. Costs are counted in
real dollars from the product's own price table once fix 4 is deployed **[hypothesis — Wave 3's cost per attempt as its stage-1 report (#111) gives it; the Wave 4 figure is an estimate]**.

**How the line is held.** A new campaign is registered in the product for Wave 4, holding no
readings, with its ceiling at the line (the product keeps ceilings in pounds at a recorded rate).
It must not be a Wave 3 campaign: a campaign that holds reserved readings on a repository refuses
every run that names no reading. Every run also carries its own `max_cost_usd`. A run the campaign
would refuse is not filed.

**The list is cut to fit the line.** With `c` the pilot's mean product cost per blind attempt,
both arms pooled and the author's calls included, the wave may hold at most
`N = floor((line − pilot spend) / (5 × 1.5 × c))` commits. `k` is the largest whole number, at
most 40, for which the four cells (two under option A) cut to `k` hold no more than `N` commits
together. At 13 cents this leaves today's pools whole; at 20 cents it would cut option B to about
61 commits, and the power figures of R-1 would fall with it. The half again in the rule pays for
re-filed batches and for `S3` **[aspiration — this registration's design; nothing is run yet]**.

**If the money stops the wave anyway,** the primary is **not read**. Under option B that includes
the case where cobra cannot be run or finished for any reason: the result is reported as not
read, never as a click-only test. Each new spend (pilot, click, cobra) starts only on Paul's yes.

## 4. Before any Wave 4 row

| # | What | State |
|---|---|---|
| 1 | Click's dependency set includes the `tests` group, so pytest is present for every build | Paul's stack step |
| 2 | The builder's own cache and temp files no longer disqualify a build | PR #113, reviewed, green |
| 3 | `git -C <worktree> <allowed command>` is accepted | PR #114, reviewed, green |
| 4 | Cost is computed from the product's price table, with the CLI's figure beside it | PR #115, green, outside review still owed |
| 5 | Apparatus 2.5 (ADR-0049), so Wave 3 and Wave 4 rows can never be blended | branch ready; opens after #111 merges |
| 6 | The test author's key is on the stack | Paul, with the `addkey` helper |
| 7 | Served checkout updated and the stack restarted | Paul |
| 8 | Every commit re-qualified at 2.5; the full lists appended here | me, at no model cost, after 7 |
| 9 | The Wave 4 campaign registered | on Paul's yes to the pilot |

2.5 is not deployed while a 2.4 campaign is open, and not without fixes 2 to 4.

## 5. Pilot

Eighteen builds on click, about $3: twelve `A0` and six `S1`, transcripts kept. The pilot uses
the last commits of each click cell's seeded order (six XS and six S for `A0`; the last three of
each for `S1`). Pilot rows are never counted **[aspiration — this registration's design; nothing is run yet]**.

The wave starts only if all of these hold **[aspiration — this registration's design; nothing is run yet]**:

- no more than 1 of 18 builds misses for a harness reason (part 7);
- the test author produces a usable test for at least 5 of 6 commits;
- no `S1` build is disqualified because of the authored test file itself: the test-files check
  must not fire on the file the harness wrote;
- one `S1` row's arm label reads `S1@gpt-oss-120b`, and a transcript file exists for a build of
  each arm;
- the product's cost for the pilot is within 10% of the provider consoles.

**The turn limit, by rule.** It stays at the product default unless at least 3 of the 18 pilot
builds, both arms counted together, end on the turn limit having run the tests within their last
five turns. In that case it is doubled, once, for every arm **[aspiration — this registration's design; nothing is run yet]**.

**If a gate fails.** Whatever is changed in the harness or the author's set-up, the pilot commits
already used are struck from the lists before anything is run again, and the repeat pilot takes
the next commits from the tail. The `S1` arm is never tuned on commits the wave will count.

## 6. Analysis, fixed in advance

Every item below is a rule for rows that do not exist yet **[aspiration — this registration's design; nothing is run yet]**.

1. **Primary.** `A0` against `S1`. For each commit, the share of its two attempts that are clean
   under each arm, and the difference. Statistic: the sum of the per-commit differences. One exact
   two-sided sign-flip test at 0.05, over click's commits (option A) or over all four cells'
   commits (option B). Smallest effect of interest: 15 points. This is the only p-value in the
   wave. It is read once, when every batch has been filed (and re-filed where the row rule says
   so). Until then no comparison between the arms is computed, on click or anywhere; rows are
   looked at only for the harness checks.
2. **The interval.** Beside the p-value, a 95% interval for the mean per-commit difference, found
   by inverting the same sign-flip test.
3. **What each outcome may be called.** *Cleared*: p below 0.05 with `S1` ahead. *No 15-point
   effect*: p not below 0.05 and the interval's upper end below 15 points. *Inconclusive*:
   anything else. Under option B the claim is about the average over the listed commits of both
   repositories together; nothing is claimed for either repository alone.
4. **Every row is a miss unless clean.** Disqualified rows, missing rows, outages, turn-limit
   endings and an author that produced no usable test all count as misses, under both arms. The
   product's own split is reported beside ours.
5. **Everything else is description, with no tests.** Per-cell and per-repository results;
   agreement between attempt 1 and attempt 2 within an arm; `S3` against each blind arm, with the
   blind rows that the test-files check alone disqualified listed beside it, because that check
   does not run on sighted rows; a table that leaves out harness-caused misses; a table that
   leaves out commits where the author produced no usable test; the author's usable-test rate. A
   secondary table never replaces the primary.
6. **Cause of every miss.** Classed as builder, harness or unclear with the checklist of part 7.
   The classing is not blind: an `S1` transcript shows the authored test. So the count that
   matters for the stop below is taken from row fields, and the transcript reading is reported
   beside it.
7. **Mergeability.** Ten clean patches per arm per repository, drawn where possible from commits
   clean under both arms, compared with the real commit by a reviewer who is not told the arm:
   merge as is, merge with small edits, or do not merge. Reported as counts. Paul checks five as an
   audit of the reviewer.
8. **Stops.** (a) The money line (part 3). (b) Four or more of the first 40 wave builds ending on
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
| Now | Nothing: R-1 is decided (B). |
| After #111 merges | Nothing: I merge the fix PRs under the usual rule and open the 2.5 PR. |
| Before the pilot | The Cerebras key with `addkey`; yes to click's `tests` dependency group; pull and restart the stack. I will give the exact commands then. |
| Before each spend | Yes to the pilot (which also registers the campaign), yes to click, yes to cobra (with its image switch). |
| During the report | Check five sampled patches per repository. |
