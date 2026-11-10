# Wave 3 — the stage-1 report — 2026-11-10

**Closed.** Paul closed Wave 3 on this report at 17:33Z, with no stage 2 (DL-416). Nothing is
released. Read once at the close, the loop pair does not clear, and Q-25's rule reads Stop, not the
default. Of the choices the read rests on, only one would flip it, and Paul kept that one as
registered; section 11 sets it out with the rest of the close. The FREEZE ends when this record
merges, by Paul's answers at 18:49Z and in the carve-out session (section 11). Sections 1 to 10
stand as written at stage 1's end; where the close makes a passage moot, the passage says so
**[hypothesis — Paul's answers in the lead session's transcript (17:33:07Z and 18:49:00Z) and in the
carve-out session (relayed at 18:46:01Z), and the stack's rows and readings on 2026-11-10 at about
17:40Z, apparatus 2.4; those records are not in this repository]**.

**Status at stage 1's end, before the close.** Stage 1 of the Wave 3 campaign `cmp_8e1f261023db8a26a40e0e84` has ended at its line
on Claude Code's reading of "fits", which part 2 does not contain. On that reading nothing more
fits under $54.00. No stop happened, and the protocol is not complete. Read literally, part 2
still admits at least one more small run, and no record says where a literal run would lead
(section 7) **[hypothesis — the campaign's tally on 2026-11-10 at about 10:55Z; those records are
not in this repository]**. The line is measured in Claude Code's own cost figure, which is 2.5
times Anthropic's bill, and Paul keeps that measure (section 1). Paul chooses between attesting the reading and having the
literal run made first. Only then can decision 9's fixed rule (Q-26, DL-400) release stage 2,
which Paul files (the start-up runbook's step 22). This record is the registration's part 5 step
8. Part 4's stage-2 statement is in the registration's part 6, in
[the stage-2 statement amendment](2026-10-09-wave-3-registration.md#the-stage-2-statement-amendment-2026-11-10).

**Authority.** Paul Glover's decision 7 of 2026-10-09 (DL-371) and decision 9 of 2026-10-11
(DL-400), as [the registration](2026-10-09-wave-3-registration.md) records them; the registration's
part 2 ("What Claude Code reports at the end of stage 1") and part 5 step 8; and the start-up
runbook (handbook page 13, v0.4.18) step 21, in the private crb-handbook repository.

**Claims in this record.** Every figure is read from the stack's own records: its ledger rows,
events, runs and readings. Those records are not in this repository, so each figure is tagged
`[hypothesis]` with that reason (DL-088). Step 12 publishes the rows. Each rate is a clean rate on
first attempts, at apparatus 2.4, in the sealed posture, by `claude_code` with `claude-sonnet-5`.
Sighted rows (`S3`) and blind rows (`A0`, `A0+L`) are never pooled. Every Wilson 95% interval here
is descriptive: fixed-n, and not adjusted for the sequential look. `clean` is a mechanical result:
the repository's held-out suite passed under the belts. It is not proof that the patch is correct.
Cobra's runs used the builder image `crb-builder-go:local` and click's `crb-builder:local`. This
record counts a disqualified row as a miss, as the readings do. At stage 1's end Paul had not
decided how the disqualifications suspected to be harness false positives are treated (section 10),
so each arm's upper bound with them counted clean is in section 3 as well. At the close Paul kept
them as misses, as registered (section 11) **[hypothesis — Paul's answers in the lead session's
transcript up to 17:33:07Z, and the carve-out session's question and Paul's "Yes", relayed to the
lead session at 18:46:01Z on 2026-11-10; neither transcript is in this repository]**.

## Summary for Paul

The stage at a glance **[hypothesis — read from the stack's `runs`, `grades` and `events` tables
and `GET /api/v1/readings` on 2026-11-10 between 10:50Z and 11:10Z, apparatus 2.4, n = 161 rows;
those records are not in this repository]**:

- **Closed (section 11).** You confirmed at 17:33Z that Wave 3 closes on this report, with no stage
  2, so nothing is released. Read once at the close on all 64 pairs, the loop does not clear: b = 8,
  c = 25, p = 0.0046. That is significant only because click S's 16 pending pairs are read against
  the loop; on the 48 observed pairs it still leans to `A0`, b = 8 against c = 10, p = 0.81. Q-25's
  rule reads **Stop**, not the default. Of the choices the read rests on, only one flips it:
  disqualified rows count as misses, as registered. With the scratch-path disqualifications counted
  clean, Change course would fire instead. You kept them as misses and left the verdict at Stop. The
  decision Wave 3 informs is yours (Q-19, DL-377); DL-415, in PR #108 and not yet on `main`, voids
  its 6 November date. You chose to end the FREEZE when this record merges, not at step 12's
  published rows. The loop switch is off again (step 10). The four bullets below on "fits", stage 2,
  part 4 and your step were written before the close and are moot **[hypothesis — section 11's
  sources: the stack's rows on 2026-11-10 at about 17:40Z, apparatus 2.4, and your answers up to
  18:49Z; those records are not in this repository]**.
- **Spend.** Stage 1 spent $52.708356 (£39.04) of the $54.00 line, author calls included, over
  12 runs and 161 rows. $1.29 (£0.96) is left. The dearest attempt so far cost $0.86, so by part
  2's rule the largest cap that still fits is $0.43, below one click S blind attempt ($0.555 on
  average over its 3). These are Claude Code's own cost figures, as registered. They price
  `claude-sonnet-5` at 2.5 times its list price: at list prices the same rows cost about $21.09
  (£15.62), which matches your console (section 1). You chose to keep the tally's dollars ("keep
  tally dollars", relayed by the carve-out session on 2026-11-10), so the line and the caps stay as
  registered and this record gives the bill beside them.
- **No stop.** No stop-list item fired. The image Ids matched at stage 1's start and at every
  check since. One worker ran at a time. It was replaced twice, each time between runs: at 02:44Z,
  when Paul restarted the stack onto `406722a6`, and at 08:42Z, for the switch to click's builder
  image on Paul's "A, go ahead with click". Nothing was reclaimed or abandoned. No row was
  disqualified for `nested_model_call`, and no reading's checks arm moved.
- **The readings.** None delivers. Cobra XS is `undecided`: its pool of 17 cannot reach the first
  look at 20, so its `S3` arm never ran. Cobra S, click XS and click S read `insufficient` at their
  third miss. Cobra S's three misses are all disqualifications on builder scratch paths, suspected
  harness false positives whose treatment Paul had not decided at stage 1's end (at the close Paul
  kept them as misses, section 11). Those rows were never graded; counted clean, the look would read
  20 of 20. `S1` stops in every cell. Each reading's next act is a new reading, which is Paul's
  call. Nothing is amended.
- **The descriptive arms.** Three cells have both arms complete at 16 commits each. Click S `A0`
  has run 3 of its 16 and `A0+L` none, so click S waits on a look. Four of cobra XS `A0+L`'s seven
  misses are refused `git -C` calls, and the scratch-path disqualifications fall in both cobra
  arms, so no `A0+L` effect, for or against, can be read. Paired commit by commit (interim, not
  tested), 18 of the 48 commits in the three complete cells were clean under one blind arm and
  not the other, 10 only under `A0` and 8 only under `A0+L`; each flip may be the loop's changes,
  the attempt's own variation or a suspected harness artefact, and one attempt per commit cannot
  tell which. Cobra's finish gate was learned from rows that include cobra XS `A0`'s own, a bias
  that, argued from the code and not measured, can only favour `A0+L` there (K7, part 2). On cobra S, of 16 commits, 6 were clean only when
  sighted and none only when blind (p = 0.031); that comparison was not registered and was chosen
  after the rows were seen, so it describes these rows, not the cell (section 3).
- **"Fits" — your choice (moot since the close).** Part 2 does not say what "fits" means. I read a run as fitting only
  when its cap holds one attempt at the arm's expected cost, so on my reading nothing more fits.
  Read literally, a run capped at up to $0.43 on click S `A0`'s next commit still fits. You choose:
  (a) attest my reading in a decision-log row, as DL-400 recorded a reading I took, and stage 1
  ends now; or (b) have me make the literal run, or runs, under C-STAGE1-RUNS first. I recommend
  (b): it is part 2's rule as written, and its rows are real click S `A0` rows. Its risk: the
  worker does not bound a run's first attempt, and one dearer than $1.29 would overrun the
  campaign. That is a stop, and DL-400 would then release nothing. No attempt of the 161 cost more
  than $0.86. Section 7 has the detail.
- **Stage 2 (moot since the close: it does not run).** It runs click S only: `A0`'s 13 pending commits (fewer if you choose (b)), then
  `A0+L`'s 16. That is about $10 to $16 of the $55.29 the release leaves, and up to about $25 if
  every attempt cost as much as the dearest so far. Each run's cap limits it but does not bound
  it: a run's first attempt is unbounded, and a later one dearer than any before it can pass the
  cap (section 9). No builder-image
  switch is needed, because click already runs on `crb-builder:local`. That image has no pytest,
  and click's dependency sets give the builder pytest for only 10 of the 29 builds (section 10).
- **Part 4 (moot since the close: the statement is recorded but not acted on).** The statement expects 66.4 clean blind patches for review if click S `A0`'s 2 of 3
  holds, or 60.8 if its 13 pending commits run at the value baseline's rate, and I give the two
  equal weight. Stage 1 has already observed 54. Stage 2 adds about 12 (or 6.8), which narrows the
  share judged mergeable from ±12.0 points to ±10.8 (or ±11.3). No cell can deliver in stage 2.
  These are path (a)'s figures: if you choose (b), I fill the statement and this report again from
  the rows at stage 1's end before step 22.
- **Your step (moot since the close: step 22 is not filed).** First the "fits" choice above. Then step 22, P-RELEASE-STAGE2, is yours: the
  three `wave3_post.py` commands in the runbook's step 22, whose decision is now DL-400's id and
  its words verbatim. If (b) ends on a stop, nothing is released. I check the line reads $108.00
  before any stage-2 run.

Section 10 lists the findings held for after the FREEZE.

## 1. Spend

Each run under the campaign, with its cost as the ledger records it, in dollars and in pounds at
1.35 (DL-379) **[hypothesis — read from the stack's `grades` table (rows 619 to 779) and the
smoke run's `author.attempt` event on 2026-11-10 at about 10:55Z, apparatus 2.4, n = 161 rows;
those records are not in this repository]**:

| run | cell | arm | rows | cost | in pounds |
|---|---|---|---|---|---|
| `0a7048da…` | cobra M (smoke) | `S1@gpt-oss-120b` | 1 | $0.000000 | £0.00 |
| `2dfb6a08…` | cobra M (smoke) | `A0`, no reading | 1 | $0.264146 | £0.20 |
| `27f45991…` | cobra XS | `A0` | 16 | $3.904366 | £2.89 |
| `f224053e…` | cobra XS | `A0+L` | 16 | $3.228201 | £2.39 |
| `5a395c04…` | cobra S | `S3` | 20 | $7.523129 | £5.57 |
| `715c67b5…` | cobra S | `A0` | 16 | $5.310428 | £3.93 |
| `f9a0e9e4…` | cobra S | `A0+L` | 16 | $6.685981 | £4.95 |
| `7d5d4bd7…` | click XS | `S3` | 20 | $5.370786 | £3.98 |
| `77139b64…` | click XS | `A0` | 16 | $5.608998 | £4.15 |
| `9e67c355…` | click XS | `A0+L` | 16 | $5.707909 | £4.23 |
| `ec9f81a4…` | click S | `S3` | 20 | $7.438403 | £5.51 |
| `73e160d8…` | click S | `A0` | 3 | $1.664314 | £1.23 |
| the test author's calls | — | — | — | $0.001697 | £0.00 |

| by cell | cost | in pounds |
|---|---|---|
| cobra XS | $7.132567 | £5.28 |
| cobra S | $19.519538 | £14.46 |
| click XS | $16.687693 | £12.36 |
| click S | $9.102717 | £6.74 |
| the two smoke runs | $0.264146 | £0.20 |
| the test author's calls | $0.001697 | £0.00 |
| **the campaign** | **$52.708356 of $54.00** | **£39.04 of £40.00** |

| by arm | cost | in pounds |
|---|---|---|
| `S3` (sighted) | $20.332318 | £15.06 |
| `A0` (blind) | $16.488106 | £12.21 |
| `A0+L` (blind) | $15.622091 | £11.57 |

The rows sum to $52.706659 and the one author call adds $0.001697, $52.708356 in all. That is the
sum the campaign's tally takes, over unrounded costs (`src/crb/core/campaign.py`): the tally
served when run `73e160d8…` was admitted, $51.044042, is the same sum over the rows before it.
Each figure in these tables is the exact sum of its rows' recorded costs, which are recorded to
eight places, rounded once, half up, to six places. The tally adds the same costs in binary floating
point, and to six places that gives the same $52.708356 and $51.044042. A table's printed parts can
differ from its total by a few units in the last place. No run is live, so nothing is held, and the
campaign was not stopped for an unplaced attempt when it admitted that run **[hypothesis — the
row sums from the `grades` table, and the author call and the tally from the `campaign.admitted`
payload of 2026-11-10 at 10:45:39Z; those records are not in this repository]**. Each run's cap
and its admission are in the stack's
`campaign.admitted` events. The builder's own sessions, the reviewer's and Claude Code's are not
counted (DL-379).

**What the bill says.** Every cost above is Claude Code's own figure for its session
(`total_cost_usd`), which crb records unchanged. It is not Anthropic's bill, and it is 2.5 times
the bill. Each of the 160 rows with a cost records its own tokens priced at $5 per million input
tokens and $25 per million output, with cache reads at a tenth of the input price and cache writes
at 1.25 times it, to within 0.03%. `claude-sonnet-5`'s list prices are $2 and $10. Paul's console
export for the builder's API key, saved on 2026-11-10 at 12:06, shows for 9 November between 97%
and 99% of crb's tokens for that day, priced at the list prices: $2.13, where crb's rows record
$5.22. The export's 10 November figures stop at about 09:00Z. At the list prices the 161 rows cost
about $21.09 (£15.62); Paul's console showed $21.13 for the month to date. The tally, the line,
every cap and headroom, and the "fits" arithmetic in this record are all in Claude Code's figure,
as registered, and Paul keeps them so: "keep tally dollars" (relayed by the carve-out session,
2026-11-10). The error only ever overstates, so it cannot overspend; it buys 2.5 times fewer
attempts than the money would (section 10) **[hypothesis — the rows' recorded costs and tokens
from the `grades` and `evidence` tables, and Paul's two console exports (cost and tokens, 2026-10-12
to 2026-11-10); those records are not in this repository]**.

## 2. The reading arms

The `S3` arm of each reading, read on the run its look was filed as **[hypothesis — read from
`GET /api/v1/readings`, the remeasure plan (`GET /api/v1/learn/remeasure`) and the stack's
`grades` table after each look run, 2026-11-10, apparatus 2.4; those records are not in this
repository]**:

| cell | reading | pool | look run | builder image | rows | clean | missed | state | decided at | Wilson 95% (sighted) |
|---|---|---|---|---|---|---|---|---|---|---|
| cobra XS | `rdg_e6bbe59930cd26e728a24364` | 17 | none | none | 0 | 0 | 0 | `undecided` | the pool cannot reach the look at 20 | — |
| cobra S | `rdg_2910bad1397a488cd6c05457` | 27 | `5a395c04…` | `crb-builder-go:local` | 20 | 17 | 3 | `insufficient` | the 20th commit (3 of 20 missed) | 0.850 [0.640, 0.948] |
| click XS | `rdg_1d932e9f635d6583f111d548` | 30 | `7d5d4bd7…` | `crb-builder:local` | 20 | 17 | 3 | `insufficient` | the 10th commit (3 of 10 missed) | 0.850 [0.640, 0.948] |
| click S | `rdg_471d0e7f4f51146392e8c788` | 38 | `ec9f81a4…` | `crb-builder:local` | 20 | 13 | 7 | `insufficient` | the 7th commit (3 of 7 missed) | 0.650 [0.433, 0.819] |

Click XS read 7 of its first 10 clean, 0.700 [0.397, 0.892], and click S 4 of its first 7, 0.571
[0.250, 0.842]. Each look run went on to 20 commits because the plan's request named 20 (part 2,
PW-4); the rows after the third miss are reserved under the reading and change nothing. Cobra S's
three misses are all disqualifications: one on a builder scratch file (`.tmp/out.json`) and two on
the in-repository Go build cache (`.gocache`). All three are suspected harness false positives
(section 10). At stage 1's end Paul had not decided how they are treated; at the close Paul kept
them as misses (section 11). Those rows were never graded, so whether they were clean is not known;
counted clean, the look reads 20 of 20, 1.000 [0.839, 1.000], an upper bound. Click's two looks
depend on whether the builder can run click's tests, which is not confirmed (section 10)
**[hypothesis — the rows' `dq_reason` and the reading's text on 2026-11-10, apparatus 2.4, n = 20
rows; those records are not in this repository]**.

- **No reading delivers**, so no result carries the label "look.v1 deliver; oracle and controls
  not yet measured".
- **`S1` reads `stopped` in every cell**, because each `S3` read `insufficient` or `undecided`
  (part 1, FZ-2).
- **Each `next_act` is `new_reading`.** That is Paul's call, and no reading was amended ("Option
  D: not yet", and for cobra, "if a cobra cell is short, report it the same way and don't amend").
- **Cobra XS's `S3` never ran.** Its pool held 17 qualified commits at step 3, 3 short of the
  first look, and the plan served it as `cannot_clear`. Running it could only read `insufficient`
  or stay `undecided`, and `S1` could not follow either way.

## 3. The descriptive arms — interim, not tested

Each `A0` and `A0+L` arm enrols the first 16 commits of its reading's pool in seeded order. These
figures are **interim, not tested**: the loop pair is tested once, when both arms of every cell
are complete or, if the campaign ends first, then, with each pending commit read against the loop
(part 1) **[hypothesis — read from the stack's `grades` table and
`GET /api/v1/readings` on 2026-11-10, apparatus 2.4, blind, n = 16 per arm except click S; those
records are not in this repository]**. Since the close, that one test has been made, on all 64
pairs (section 11); the figures here stay descriptive.

| cell | arm | run | builder image | observed | clean | red | refused call | budget | lint | DQ scratch path | DQ test files | Wilson 95% (blind) | scratch DQs counted clean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cobra XS | `A0` | `27f45991…` | `crb-builder-go:local` | 16 of 16 | 11 | 2 | 0 | 0 | 0 | 3 | 0 | 0.688 [0.444, 0.858] | 14 of 16, 0.875 [0.640, 0.965] |
| cobra XS | `A0+L` | `f224053e…` | `crb-builder-go:local` | 16 of 16 | 9 | 2 | 4 | 0 | 0 | 1 | 0 | 0.563 [0.332, 0.769] | 10 of 16, 0.625 [0.386, 0.815] |
| cobra S | `A0` | `715c67b5…` | `crb-builder-go:local` | 16 of 16 | 8 | 4 | 1 | 0 | 0 | 2 | 1 | 0.500 [0.280, 0.720] | 10 of 16, 0.625 [0.386, 0.815] |
| cobra S | `A0+L` | `f9a0e9e4…` | `crb-builder-go:local` | 16 of 16 | 6 | 3 | 3 | 0 | 0 | 3 | 1 | 0.375 [0.185, 0.614] | 9 of 16, 0.563 [0.332, 0.769] |
| click XS | `A0` | `77139b64…` | `crb-builder:local` | 16 of 16 | 8 | 2 | 1 | 4 | 1 | 0 | 0 | 0.500 [0.280, 0.720] | no scratch DQ |
| click XS | `A0+L` | `9e67c355…` | `crb-builder:local` | 16 of 16 | 10 | 1 | 1 | 4 | 0 | 0 | 0 | 0.625 [0.386, 0.815] | no scratch DQ |
| click S | `A0` | `73e160d8…` | `crb-builder:local` | 3 of 16 | 2 | 0 | 0 | 1 | 0 | 0 | 0 | 0.667 [0.208, 0.939] | no scratch DQ |
| click S | `A0+L` | none yet | — | 0 of 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — |

Every miss falls in one column. Red means the held-out suite failed. A refused call is a tool call
the sandbox refused, which ends the attempt (failure kind `protocol`). Budget means the attempt
ran out of turns or tokens, and lint that the lint gate failed. The disqualification columns
split the rows the tamper check disqualified: on builder scratch paths, suspected harness false
positives, or on test files. The last column counts the scratch-path disqualifications clean. It
is an upper bound, not a rate: those rows were never graded.

Cobra's `A0+L` arms sit below their `A0` arms, but mostly on misses suspected to be harness
artefacts: five refused `git -C` calls fall in `A0+L` (section 10), and the scratch-path
disqualifications fall in both arms. In each complete cell the two arms' intervals overlap, with
those rows counted as misses or as clean, so no `A0+L` effect, for or against, is claimed. Click S
`A0`'s one miss, row 779, was a budget miss: the attempt reached its turn limit (`max_turns`) at
$0.863184, the dearest attempt of the stage, before the lint gate ran. It counts in the 2 of 3
**[hypothesis — read from the rows' `failure_kind`, `stop_reason` and `dq_reason` in the stack's
`grades` table on 2026-11-10, apparatus 2.4, n = 16 per arm except click S; the rows are not in
this repository]**.

**Paired by commit.** Each complete cell's `A0` and `A0+L` arms ran the same 16 commits in the
same order, and each `S3` look's first 16 commits are its `A0` arm's 16 (click S `A0`'s 3 are its
look's first 3). So the arms can be compared commit by commit: each pair shares the commit, its
era and, on click, its dependency set, and differs by the arm: the loop's changes for `A0` and
`A0+L`; for `S3` against a blind arm, whether the tests are seen and the blind-only checks that
go with it **[hypothesis — each run's
`task_id`s and their order in the stack's `grades` table, 2026-11-10; those records are not in
this repository]**. A disqualified row counts as not clean. The last column counts the
scratch-path disqualifications clean instead. For the `S3` rows, the p value is the exact
two-sided sign test on the commits clean under one arm only. The `A0` and `A0+L` pairs are the
loop pair, which part 1 tests once, so they carry no p value here:

| cell | first arm | second arm | commits | clean in both | only the first | only the second | in neither | p | scratch DQs counted clean: only the first, only the second |
|---|---|---|---|---|---|---|---|---|---|
| cobra XS | `A0` | `A0+L` | 16 | 7 | 4 | 2 | 3 | not tested (part 1) | 4, 0 |
| cobra S | `A0` | `A0+L` | 16 | 4 | 4 | 2 | 6 | not tested (part 1) | 2, 1 |
| click XS | `A0` | `A0+L` | 16 | 6 | 2 | 4 | 4 | not tested (part 1) | no scratch DQ |
| the three | `A0` | `A0+L` | 48 | 17 | 10 | 8 | 13 | not tested (part 1) | 8, 5 |
| cobra S | `S3` | `A0` | 16 | 8 | 6 | 0 | 2 | 0.031 | 6, 0 |
| cobra S | `S3` | `A0+L` | 16 | 6 | 8 | 0 | 2 | 0.0078 | 7, 0 |
| click XS | `S3` | `A0` | 16 | 6 | 7 | 2 | 1 | 0.18 | no scratch DQ |
| click XS | `S3` | `A0+L` | 16 | 8 | 5 | 2 | 1 | 0.45 | no scratch DQ |
| click S | `S3` | `A0` | 3 | 1 | 1 | 1 | 0 | 1.00 | no scratch DQ |

Click XS's look took its third miss at its 10th commit, so its `S3` rows 11 to 16 do not bear on
the reading; they are paired here only as rows **[hypothesis — the order and `clean` flags of
`7d5d4bd7…`'s rows in the stack's `grades` table, 2026-11-10; those records are not in this
repository]**.

What the pairs show **[hypothesis — the rows of the ten runs above in the stack's `grades` table
(`task_id`, `clean`, `disqualified`, `dq_reason`), read on 2026-11-10, apparatus 2.4; and the
carve-out session's count from the served run-task lists, which agrees; those records are not
in this repository]**:

- **The loop pair.** In the three complete cells, 18 of the 48 commits were clean under one blind
  arm and not the other: 10 only under `A0`, 8 only under `A0+L`. Each flip may be the loop's
  changes, the attempt's own variation or a suspected harness artefact (the refused `git -C`
  calls and the scratch-path disqualifications, section 10), and with one attempt per commit they
  cannot be told apart. The net is 2 commits of 48 toward `A0`: cobra 8 to 4 toward `A0`, click XS
  4 to 2 toward `A0+L`. With the scratch-path disqualifications counted clean, 13 commits flip, 8
  and 5. All of it is interim, not tested; the loop pair's one test, made at the close, is in
  section 11.
- **The loop's switch on cobra was learned in-sample (K7, part 2).** Cobra's finish gate
  (`b383c935…`) was applied at 23:44:13Z on 2026-11-09, as cobra XS `A0` finished. Its evidence, 2
  target-red first attempts of 18 blind ones at apparatus 2.4, matches the 18 blind 2.4 cobra rows
  then in the ledger: the smoke commit's 2 rows and cobra XS `A0`'s 16, the last of them written at
  23:44:13Z. The gate was in force on both cobra `A0+L` runs. On cobra XS, then, each commit's
  `A0+L` attempt ran under a switch learned from rows that include its own `A0` attempt, a bias
  that, argued from the code and not measured, can only favour b (clean only under `A0+L`) over c
  (clean only under `A0`) (part 2). On cobra S the switch was learned from the smoke commit's 2
  rows and cobra XS `A0`'s 16, none of them on a cobra S commit. Click XS's switch (`de907765…`) was
  keyed on apparatus 2.2 rows from before the campaign, not on click XS `A0`'s rows. The table of
  levers below lists the config changes in force on each `A0+L` run.
- **Sighted against blind.** On cobra S, 6 commits were clean only when sighted and none only
  when blind (p = 0.031), and still 6 and none with the scratch-path disqualifications counted
  clean. Against `A0+L` it is 8 and none (p = 0.0078), or 7 and none (p = 0.016) with them counted
  clean. One of the 6, commit `e0fefb2b`, is clean sighted (row 664) and disqualified blind (row
  684) for test files modified before the overlay, a check only blind rows run; row 700 plays the
  same part against `A0+L`. On click XS it is 7 and 2 (p = 0.18). This pairs sighted and blind
  rows commit by commit; it does not pool them.
- **What the p values are.** Part 1 registers none of the `S3` comparisons, and tests the loop
  pair only once, when both arms of every cell are complete or the campaign ends; that test had
  not been run at stage 1's end, and was run once at the close (section 11). The `S3` comparisons were chosen after the rows were seen, among eight distinct
  pairings (the table's "three" row sums three others), each read two ways, with the scratch-path
  disqualifications as misses and as clean, and none is corrected for that. Corrected for the
  eight, none is below 0.05 / 8, about 0.0063. Corrected for the five `S3` pairings alone, only
  cobra S's `S3` against `A0+L` is below 0.01, and only with those disqualifications as misses
  (0.0078; 0.016 with them clean); corrected for the ten `S3` readings (0.005), none is. They
  describe these rows, not the cells.

**The levers in force on each run.** Every row of every run carries `budget_tier` 25/25/900, the
default profile **[hypothesis — read from each row's labels in the stack's `grades` table on
2026-11-10, apparatus 2.4, n = 161 rows; those records are not in this repository]**:

| arm | `learn` | `budget_profile` | `checks` label | `learn_changes` | `learn_overlay` |
|---|---|---|---|---|---|
| `A0` (all four runs) | `off` | `default` | none | none | none |
| `A0+L`, cobra XS (`f224053e…`) | `config` | not named; default in force | `fmt=0:default;gate=1:repo;api=0:default;cfg=427c0aee0619` | `b383c935cf96a6d3` | `02d21a10b19dc326` |
| `A0+L`, cobra S (`f9a0e9e4…`) | `config` | not named; default in force | the same | `b383c935cf96a6d3` | `02d21a10b19dc326` |
| `A0+L`, click XS (`9e67c355…`) | `config` | not named; default in force | the same | `de907765ff95e6b2` | `02d21a10b19dc326` |

Every `A0+L` row reads `fmt=0` and `api=0`, and no reading's `checks_arm` moved, so RT2B-1's check
holds. Both `learn_changes` values are the same lever, `checks.finish_gate=true`; the gate itself
is not part of the checks arm. The finish gate read `before=pass` on 12 rows of each cobra run and
on 15 of click XS's, and `skipped=attempt_not_admissible` on the rest. On cobra S, the context line
T-ARCH (`2cb848523eef`, change `5f1bdc05…`) was in force but reached one brief: 15 rows carry it
as `learn_dropped`, and only row 700 (`e0fefb2b`) as `learn_lines`, with `learn_playbook`
`bbb263c587201ce2` **[hypothesis — the same labels, n = 48 `A0+L` rows, apparatus 2.4; those
records are not in this repository]**.

**The loop's changes during stage 1.** Each was applied by the loop's tick at the end of a
reading run, between that run's `run.done` and `run.finished`, so none is a stop (RT2B-3). None was
made after `73e160d8…` **[hypothesis — read from the stack's `events` table on 2026-11-10 at about
10:55Z; those records are not in this repository]**:

| change | repository | what | signature it answers | evidence keyed at | stratum | applied at | after run |
|---|---|---|---|---|---|---|---|
| `b383c935cf96a6d3` | cobra | `checks.finish_gate=true` | `builder_red:target_red`, 2 of 18 | 2.4 | blind | 2026-11-09 23:44:13Z | `27f45991…` (cobra XS `A0`) |
| `5f1bdc05682e7967` | cobra | context line T-ARCH, "Repository history is off limits…" | `protocol:archaeology:rm`, 3 of 34 | 2.4 | blind | 2026-11-10 00:13:53Z | `f224053e…` (cobra XS `A0+L`) |
| `de907765ff95e6b2` | click | `checks.finish_gate=true` | `builder_red:target_red`, 3 of 11 | 2.2 | blind | 2026-11-10 09:18:05Z | `7d5d4bd7…` (click XS `S3`) |
| `678532656dbf3811` | click | `spend.budget_profile=calibrated` | `budget:max_turns`, 8 of 32 | 2.4 | blind | 2026-11-10 10:06:05Z | `9e67c355…` (click XS `A0+L`) |
| `380316afbba349ff` | click | `checks.finish_gate=true` | `protocol:network:which`, 2 of 40 | 2.4 | sighted | 2026-11-10 10:32:27Z | `ec9f81a4…` (click S `S3`) |
| `2bf857ee6301258d` | click | `checks.finish_gate=true` | `protocol:network:pip download`, 2 of 40 | 2.4 | sighted | 2026-11-10 10:32:27Z | `ec9f81a4…` (click S `S3`) |

Each "signature it answers" cell gives the signature and its count in the first attempts the
change's evidence held, and "evidence keyed at" the apparatus version that evidence was keyed at,
as each change's `learn.prevention.recorded` event records them. Click's first change,
`de907765…`, rests on 11 blind attempts keyed at apparatus 2.2, and it is in force in apparatus 2.4
`A0+L` rows: click XS's, and click S's in stage 2, which the close cancelled (section 11). The two sighted changes answer different
signatures, `which` and `pip download`, with the same lever, the finish gate, and in the sighted
stratum, not the blind one the `A0+L` arms run in **[hypothesis — read from the
`learn.prevention.recorded` events of each change in the stack's `events` table on 2026-11-10;
those records are not in this repository]**.

The calibrated budget profile is in force for click's blind stratum. Click S `A0+L`'s body names
no `budget_profile`, so it would have pinned `calibrated` at its first reservation, while every
`A0` body names `default`. That is part 1's `A0+L` arm as registered: the loop's changes in force
when the arm runs. Since the close, the arm does not run (section 11).

**The loop's switch and the factory rows.** The switch was turned to `config` for cobra at
2026-11-09 23:19:53Z and for click at 23:20:21Z, each with an empty overlay and the reason "Wave
3, the `A0+L` arm (ADR-0026 item 13; DL-371)". Step 10 restores it to the state step 4 recorded:
`auto_apply` off, never switched. Step 10 ran at the close, at 17:37Z, and the switch now has
records, so it is off but no longer "never switched" (section 11). The factory rows did not move during stage 1: cobra holds 3 and
click 0, as before the switch, so no factory run touched either repository (RT2B-3)
**[hypothesis — read from `GET /api/v1/learn/register` and `GET /api/v1/grades?process_step=factory`
for each repository before each `A0+L` run and on 2026-11-10 at about 10:55Z; those records are
not in this repository]**.

## 4. Commits decided by infrastructure

None. No `A0` or `A0+L` commit was decided with reason `harness`, `outage` or `unobserved`, in any
cell **[hypothesis — read from `GET /api/v1/readings` (each arm's reserved commits and their
`reason`) and the `grades` table on 2026-11-10, apparatus 2.4, n = 99 descriptive rows; those
records are not in this repository]**.

The nine blind budget misses, four in each click XS arm and click S `A0`'s row 779 (`max_turns`),
are the builder's misses, not infrastructure's: the attempt ran and used its budget, and each
counts against its arm **[hypothesis — the rows' `failure_kind` and `stop_reason` in the stack's
`grades` table on 2026-11-10, apparatus 2.4, n = 9 rows; those records are not in this
repository]**.

## 5. Reclaimed, abandoned or lost runs

None during the campaign. The stack holds three `system/run.reclaimed` events, all dated
2026-09-13 to 2026-09-15, before the campaign; it holds no `run.abandoned` or `run.claim_lost`
event **[hypothesis — read from the stack's `events` table on 2026-11-10 at about 10:55Z; those
records are not in this repository]**.

## 6. `nested_model_call`

None. No row of the campaign was disqualified `nested_model_call` **[hypothesis — read from the
`dq_reason` of rows 619 to 779 in the stack's `grades` table on 2026-11-10, apparatus 2.4,
n = 161 rows; those records are not in this repository]**.

## 7. Why stage 1 ended

Stage 1 ended, on Claude Code's reading of "fits", because nothing more fits under $54.00 (part
2's first end). Paul had yet to choose whether that reading stands (below). It did not end on a
stop or with the protocol complete. Paul then closed Wave 3 on this report (section 11), so no run
was made on either reading and the choice below is moot.

**The last run.** After click S's `S3` look the campaign had spent $51.044042, with $2.955958 left
and a headroom of $0.797871, so a cap of up to $2.158087 fitted. Click S `A0` was queued at
10:45:39Z as `73e160d8…`, with a cap of $2.15 and the reading's first 16 commits. The worker
reserves, before each attempt, the dearest attempt the run has made. After three attempts that was
$0.86, which would have passed the cap, so the run halted at 10:50:30Z, `failed` with
`stopped_code` `spend_cap` and 13 commits still pending. A halt at the cap is not a stop: the run
spent $1.664314, under its cap and far under its cap plus the headroom it was admitted with
**[hypothesis — read from the run, its `run.spend_cap` event and the `campaign.admitted` payload
on 2026-11-10 at about 10:51Z, apparatus 2.4, n = 3 rows; those records are not in this
repository]**.

**What is left.** The campaign has spent $52.708356 and $1.291644 is left. Row 779's
$0.863184 is now the dearest attempt the campaign has seen, so it is the headroom of any new
run, and the largest cap that fits is $0.428460. Click S `A0`'s three attempts averaged $0.555,
and its dearest cost $0.86 **[hypothesis — arithmetic on the figures above; those rows are not in
this repository]**.

**How "fits" was read, and Paul's choice.** Part 2 admits a run when spent, held, its cap and its
headroom stay at or under the line, and sets each cap "to fit". It does not say what a run must be
able to do to fit. Claude Code read a run as fitting only when its cap holds at least one attempt
at the arm's expected cost, so that the headroom stays a reserve for an attempt that overshoots,
not the money for a planned one. That reading is Claude Code's, not part 2's. Read literally, a
run on click S `A0`'s next pending commit, `becbde5c…`, capped at up to $0.428460, fits and would
be admitted. The worker reserves nothing before a run's first attempt, so that attempt is
unbounded (G-938) **[hypothesis — the figures above, and code reading of `SpendCap.check` in
`src/crb/server/spend_cap.py` at the served `406722a6`; the stack's records are not in this
repository]**. The two readings are not equivalent, and no record says which of three outcomes a
literal run would have:

- if the attempt costs under $0.428460, another run with a small cap may still fit, and the literal
  path goes on;
- if it costs between $0.428460 and $1.291644, nothing more fits and stage 1 ends at its line, with
  click S still waiting on a look (`A0` at 4 of 16);
- if it costs more than $1.291644, the run's cap plus its headroom, the campaign overruns. That is
  a stop (`campaign_overrun`), and DL-400 then releases nothing.

No attempt of the stage's 161 cost more than $0.863184. A literal run's rows are real click S `A0`
rows and count toward its 16. So Paul chooses between two paths:

- **(a)** attest Claude Code's reading in a decision-log row, in Paul's words, as DL-400 recorded
  the reading Claude Code took of "waits on a look"; stage 1 then ends now;
- **(b)** have Claude Code make the literal run, or runs, first, under C-STAGE1-RUNS and Paul's
  "A, go ahead with click" of 08:42Z.

Claude Code recommends (b). It is part 2's rule as written, its rows are rows the protocol wants,
and part 2 says "No decision is taken after stage 1". Its risk is the stop above. No run is queued
and nothing is released until Paul chooses **[hypothesis — code reading of `admit` in
`src/crb/server/worker.py` and `SpendCap.check` in `src/crb/server/spend_cap.py` at the served
`406722a6`, with the figures above; the stack's records are not in this repository]**.

**A call I corrected.** At 10:40Z I first recorded stage 1 as ended, judging fit by a full run of
16 commits. That was wrong under part 2's rule, which sets each cap to fit. I corrected it at
10:45Z, before any release, and queued the capped run above. Paul was told of both
**[hypothesis — the lead session's notices to Paul at 10:40Z and 10:45Z, and the run's admission
at 10:45:39Z; the session's transcript and the stack's records are not in this repository]**.

**Which cells wait on a look.** A cell waits while its reading is `look_pending`, or while its `A0`
or `A0+L` arm has run fewer than its 16 commits (DL-400). No reading is `look_pending`. Cobra XS,
cobra S and click XS have run both arms in full. Click S has run 3 of `A0`'s 16 and none of
`A0+L`'s **[hypothesis — read from `GET /api/v1/readings` and the remeasure plan on 2026-11-10 at
about 10:55Z, apparatus 2.4; those records are not in this repository]**.

**When DL-400 releases stage 2 (moot since the close; section 11).** Once stage 1 has ended at its line, by either path, with a cell
still waiting on a look and no stop, DL-400 releases stage 2. Paul files it at the runbook's step
22, `POST /api/v1/campaigns/{id}/release` with `{"released_gbp": 80, "decision": …}`, the decision
being DL-400's id and its words verbatim. If the literal path ends on a stop, nothing is released.
The amendment records why Paul, not Claude Code, files it. On path (b), Claude Code first fills
part 4's statement and this report again from the rows at stage 1's end, since the literal runs
change its spend and click S `A0`'s rate **[hypothesis — DL-400 in `docs/DECISION-LOG.md`, part 5
steps 8 and 9 and the stage-2 statement amendment in the registration, and step 22 of the start-up
runbook (handbook page 13, v0.4.18); the runbook is in the private handbook, not in this
repository]**.

## 8. What stage 2 buys

Stage 2 does not run: Paul closed Wave 3 on this report (section 11). Sections 8 and 9 stand as
written before the close.

Part 4's statement, filled from stage 1, is in the registration's part 6:
[the stage-2 statement amendment](2026-10-09-wave-3-registration.md#the-stage-2-statement-amendment-2026-11-10).
It expects 66.4 clean blind patches for review by the campaign's end if click S `A0`'s 2 of 3
holds, as part 4's rule makes it, or 60.8 if click S `A0`'s 13 pending commits run at the value
baseline's 0.233, its 2 clean of 3 kept as observed. These are path (a)'s figures; on path (b)
they are filled again from the rows at stage 1's end (section 7). This
record gives the two equal weight, because 2 of 3 rests on three rows, one of them a budget miss.
That gives the share judged mergeable to ±10.8 points at p = 0.308 (±11.3 on 60.8), and ±11.7 at
p = 0.5 (±12.2) **[hypothesis — part 4's formulas on stage 1's rates and the value baseline's
priors; the rows are not in this repository]**. Stage 2 asks for up to $54.00 (£40.00). The line
becomes $108.00 for the campaign in all.

**What stage 2 adds.** Stage 1 has already observed 54 clean blind patches. Stage 2 adds about
12.4 of the 66.4, or 6.8 of the 60.8 (its 29 attempts at 7 of 30), so it narrows the share's
interval by about 1.1 points, or 0.7: from ±12.0 to ±10.8 (or ±11.3) at p = 0.308, and from ±12.9
to ±11.7 (or ±12.2) at worst
**[hypothesis — part 4's formulas at 54 patches and at E; the rows are not in this
repository]**.

**What stage 2 cannot conclude.**
- No cell can deliver. Stage 2 runs no reading arm, and every reading's next act is a new reading.
- Stage 2 completes the last cell, so the loop pair is then tested once (part 1). That test pools
  64 pairs, and the smallest difference it finds 80% of the time is about 18 to 25 points, so a
  loop effect smaller than about 20 points will usually be missed. In the three complete cells,
  18 of 48 commits were clean under one blind arm and not the other (section 3), and with one
  attempt per commit no single flip can be put down to the loop **[hypothesis — part 1's pre-run power simulation, and the
  paired rows in section 3; no stage-2 row exists yet]**.
- Click S `A0+L` will pin the calibrated budget profile while `A0` runs the default, so any
  difference between them mixes the loop's checks with a budget change **[hypothesis — the config
  change `678532656dbf3811` (`spend.budget_profile=calibrated`) in the stack's `events` table on
  2026-11-10, the run bodies in section 9, and code reading of the arm's pin at its first
  reservation (`treatment_pins` in `src/crb/server/reading_book.py` at the served `406722a6`); the
  stack's records are not in this repository]**.
- Click's builder has pytest for only 10 of stage 2's 29 builds, as for 25 of stage 1's 75, so
  every click arm measures a builder that, for most commits, has no pytest to run click's tests
  with (section 10) **[hypothesis — the commits' parents in the stack's click clone and the
  dependency sets' `bundle.json` files, 2026-11-10; those records are not in this repository]**.

## 9. What stage 2 runs

Only click S's descriptive arms are left. Stage 2 runs them in this order, each capped to fit
under $108.00 **[hypothesis — read from `GET /api/v1/readings` on 2026-11-10 at about 10:55Z, and
an estimate from click's blind stage-1 rows, $0.354 per row over click XS's 32 or $0.555 per row
over click S's 3, apparatus 2.4; those rows are not in this repository]**:

- **click S `A0`**: its 13 pending commits (fewer if Paul chooses the literal path),
  `becbde5c…` to `607316f9…` in seeded order, with `learning` off and `budget_profile` default;
- **click S `A0+L`**: the same 16 commits as `A0`, with no `learning` and no `budget_profile` key,
  once `A0` has finished;
- about 29 attempts in all, roughly $10 to $16 of the $55.29 left after the release, and up to
  about $25 if every attempt cost as much as the dearest so far, $0.863184.

Each run's cap limits what it can spend, whatever the estimate, but it is a guard, not a
guarantee. The worker reserves nothing before a run's first attempt (G-938, section 7), and before
each later attempt it reserves only the dearest attempt the run has made, so one dearer attempt can
carry a run past its cap **[hypothesis — code reading of `SpendCap.check` in
`src/crb/server/spend_cap.py` at the served `406722a6`]**. The plan's own estimates are no guide
here: they cover `S3` only, they came to about half of what stage 1's runs cost (section 10), and
they read 0.0 for `A0` and `A0+L`. The calibrated budget profile that click S `A0+L` will pin has
no measured cost yet **[hypothesis — the remeasure plan as the stack served it on 2026-11-10 at
about 10:55Z, the runs' spend in section 1, and the rows of section 3, none of them on the
calibrated profile; those records are not in this repository]**.

**No image switch.** Click's runs are pinned to `crb-builder:local`, and the stack already runs that
image, so stage 2 needs no `env.sh` edit and no restart. Cobra's runs used `crb-builder-go:local`;
cobra's stage-1 cells are complete and stage 2 runs no cobra cell. This answers the question the
click builder-image amendment left for this report: the separate image phases it describes are not
needed. It also means all of stage 2 runs on an image without pytest, where click's dependency sets give
the builder pytest for only 10 of its 29 builds (section 10) **[hypothesis — read from the
`reading.reserved` events' builder image for click (`crb-builder:local`) and the output of the local
image-Id check (`check_image_ids.sh`) of 2026-11-10 at 10:54:52Z, which read `crb-builder:local` as
`116f523d…`; neither record is in this repository]**.

**Before the first stage-2 run.** I check that `GET /api/v1/campaigns/{id}` reads `line_usd`
108.00, run the builder's-account check (items 1 to 5) again, and check the five image Ids,
`crb-sandbox-go:main-8ab88ad` among them as `0e796b7e…`. A failed check stops the stage and Paul is
told.

## 10. Findings held for after the FREEZE

None of these is a stop, and the FREEZE blocks a fix to each during the campaign. Each is for the
post-campaign report (since the close, see section 11's "What stays open")
**[hypothesis — read from the rows, events and builder images named in each
item on 2026-11-09 and 2026-11-10, apparatus 2.4; those records are not in this repository]**:

- **Builder scratch paths may disqualify clean work.** Twelve cobra rows were disqualified for
  modified test infrastructure ("test infrastructure modified", the tamper check's `test_infra`
  kind) on the builder's scratch paths: eleven on the in-repository Go build cache (`.gocache`,
  `.gotmp/cache`) and one on `.tmp/out.json`. Nine fell in the descriptive arms and three in cobra
  S's look. They are suspected harness false positives, but they were never graded, so whether they
  would have been clean is not known. At stage 1's end Paul had not decided how they are treated; at
  the close Paul kept them as misses for Wave 3's read (section 11). Two more rows, 684 and 700,
  both on commit `e0fefb2b`, were disqualified for modified test files; this record does not class
  them with the scratch-path rows.
- **The archaeology guard may refuse the worktree's own root.** Five refused calls were
  `git -C /work …`: rows 641, 642, 647 and 652 in cobra XS `A0+L`, and 703 in cobra S `A0+L`. The
  suspected mechanism is that the guard resolves `/work` to the host path; it is not confirmed.
- **The time-order rule kept T-ARCH from cobra S.** The line was taught by a commit dated
  2026-04-24, and 15 of cobra S's 16 commits are older, so `A0+L` on cobra S measured roughly
  `A0` plus the finish gate. The rule works as designed.
- **Click's builder had pytest for only 25 of its 75 builds.** The test command in the builder's
  brief puts the sealed dependency set `/deps/site` on `PYTHONPATH`, as designed. Click's set holds
  pytest only when the commit's parent pins its tests in `requirements/tests.txt`: 25 builds. For
  37, the set is built from `uv.lock`, which takes no dependency group because click's settings
  name none, so it holds no pytest. For 13, the parent has no runtime dependencies and no set is
  mounted. `crb-builder:local` itself has no pytest and no `uv`. The grader is unaffected: its
  sandbox installs pytest. Six builds had their edits discarded under the command rules before
  grading:
  - five for network installs: rows 710, 711, 774 and 776 reached for pytest through `pip` or
    `uv`, and 742 ran `pip download --help`;
  - one, 726, for `git log`.

  Only 710 and 776 reached the network (pypi.org, refused). Retention is off by default and a
  reading run cannot turn it on, so no transcript was kept, and whether any builder ran click's
  tests cannot be read from the records. Sighted rows with pytest were clean in 13 of 13 [0.772,
  1.000], the rest in 17 of 27 [0.442, 0.785]. Those commits differ in era, so the gap is not
  shown to be the cause. Stage 2's click S builds would have run the same way (moot since the
  close): 10 of its 29 have pytest. Giving
  click's sets pytest means changing click's settings and rebuilding its sets in mid-campaign,
  which the FREEZE holds back; that is Paul's call **[hypothesis — the five click runs' `grades`
  rows and their `ctx_harness` labels, the `builder.discard` and `builder.egress_denied` events,
  the parents of the commits in the stack's click clone, the dependency sets' `bundle.json` files,
  and a check of `crb-builder:local` (`116f523d…`) in a throwaway container with no network on
  2026-11-10; those records are not in this repository]**.
- **The loop learns from sighted runs and old evidence.** Click's first change, `de907765…`, was
  applied at the end of a sighted `S3` run and rests on 11 blind attempts keyed
  `2.2|claude_code|claude-sonnet-5`, yet it is in force in apparatus 2.4 `A0+L` rows. Cobra's
  changes rest on evidence keyed 2.4. Two more click changes, in the sighted stratum, were applied
  at the end of click S's `S3` run; they answer different signatures with the same lever.
- **The plan's estimates run about two times low and cover `S3` only.** Cobra S's look cost $7.52
  against $3.66 (2.06 times), click S's $7.44 against $3.42 (2.17 times) and click XS's $5.37
  against $2.70 (1.99 times). All stayed under their caps. The plan's estimates for `A0` and
  `A0+L` read 0.0.
- **"Fits" needs one meaning.** For this campaign it was Paul's choice (section 7), which the
  close made moot (section 11). Part 2 should
  define it, and the worker should bound a run's first attempt, which it now leaves unbounded
  (G-938).
- **The submit gate's login check can time out.** Cobra S `A0`'s first submit at 03:31Z was refused
  422 `builder_login_invalid` after a 60-second verification timeout. Nothing was queued or spent,
  and the resubmit at 03:41:39Z verified.
- **The tally's `authoring_usd`** should be checked against the one author call ($0.001697) when
  the rows are published (step 12); stage 2 does not run.
- **Claude Code's cost figure is 2.5 times the bill.** The builder's CLI prices `claude-sonnet-5`
  at $5 and $25 per million tokens, not $2 and $10, and the tally takes its figure unchanged
  (section 1). A campaign line therefore buys 2.5 times fewer attempts than its money. The cause
  is not confirmed. One possibility is the builder image's CLI, version 2.1.132 against the host's
  2.1.292, not knowing Sonnet 5's prices **[hypothesis — `claude --version` in a throwaway
  `crb-builder:local` container and on the host, 2026-11-10; neither output is in this
  repository]**. Pricing the
  recorded tokens from a table, or updating the builder's CLI, changes the tally, which the FREEZE
  blocks, and Paul has kept the tally's dollars for this campaign.

## 11. The close

**Paul's decision.** At 14:06:15Z Claude Code asked Paul: "Do you confirm closing Wave 3 on the
stage-1 report, with no stage 2? Yes, or no and keep stage 2 as planned." Paul answered "Yes" at
17:33:07Z. DL-416 records it **[hypothesis — the question and the answer in the lead session's
transcript, 2026-11-10; it is not in this repository]**. These follow from it, and the last from Paul's later answers:

- **No stage 2.** Step 22's release (P-RELEASE-STAGE2) is not filed, nothing is released, and
  the campaign's line stays at $54.00. For this campaign, DL-416 sets aside DL-400's fixed
  release, which no stage-1 result could have held back.
- **"Fits" is moot.** Section 7's choice is moot: no further run is made on either reading.
  Stage 1 ended at its line on Claude Code's reading of "fits" (section 7), with no stop; Paul's
  close then set aside the release that reading would have triggered.
- **The statement is not acted on.** Part 6's stage-2 statement amendment stays as written: the
  statement was recorded there, and nothing is released on it. The closure amendment beside it
  records this.
- **The loop pair is read now.** Claude Code reads the close as the campaign ending before its
  descriptive arms were complete (part 1; a choice listed below), so part 1's loop pair is read
  now, once (below).
- **The FREEZE ends when this record merges.** The FREEZE (Q-24, DL-375) holds until Wave 3 reports,
  and Q-25 publishes the result with its rows (step 12, still open). Wave 3 could be read as
  reporting either when this record is on `main` or when step 12's rows are published, and Claude
  Code asked Paul which. Paul answered "Yes it does" at 18:49:00Z to "Does the FREEZE end when #111
  merges, or at step 12, when the rows are published?" In the carve-out session Paul had answered
  "Yes" to "End the freeze at #111's merge, not at the published rows…". Step 12 still publishes the
  rows, but the FREEZE does not wait for it **[hypothesis — Claude Code's question and Paul's answer
  at 18:49:00Z in the lead session's transcript, and Paul's "Yes" to the carve-out session's item on
  the FREEZE, relayed at 18:46:01Z, 2026-11-10; neither is in this repository]**.

**The loop pair at the close.** Part 1: "If the campaign ends first, it is read once then, on the
same 64 pairs with each pending commit read against the loop, and the record says how many were
pending." A pending `A0` commit is read as clean and a pending `A0+L` commit as a miss
**[hypothesis — read from the stack's `grades` table (rows 619 to 779) and
`GET /api/v1/readings` for both repositories on 2026-11-10 at about 17:40Z, apparatus 2.4,
blind, n = 64 pairs, 48 of them observed; the test is part 1's exact two-sided McNemar test
(`crb.core.reading.mcnemar_p`); those records are not in this repository]**:

| cell | pairs | clean in both | only `A0+L` (b) | only `A0` (c) | in neither | pending pairs |
|---|---|---|---|---|---|---|
| cobra XS | 16 | 7 | 2 | 4 | 3 | 0 |
| cobra S | 16 | 4 | 2 | 4 | 6 | 0 |
| click XS | 16 | 6 | 4 | 2 | 4 | 0 |
| click S | 16 | 0 | 0 | 15 | 1 | 16 |
| pooled | 64 | 17 | 8 | 25 | 14 | 16 |

- **What was pending.** 16 of the 64 pairs were pending, all in click S. That is 29 commit-arms:
  `A0`'s 13 and `A0+L`'s 16. In click S, the 15 under c are `A0`'s 2 observed clean commits and
  its 13 pending ones. The pair in neither is row 779's commit, a budget miss under `A0`.
- **The pooled result.** b = 8 and c = 25, so (b − c) / n = −0.266, p = 0.0046. The loop does not
  clear, because only a positive difference clears (Q-28, DL-402).
- **Why it is significant.** The pending commits make the lean significant; they do not create
  it. 15 of the 25 under c are click S's, where `A0+L` never ran. On the 48 observed pairs it still
  leans to `A0`, b = 8 and c = 10, p = 0.81. This record does not read the loop as harmful.
- **Infrastructure.** No pair was decided by infrastructure. Every reserved commit has its row,
  and no reason served is `harness`, `outage` or `unobserved` (section 4). The read without such
  pairs is the same read.
- **Each cell's own difference.** These are descriptive: cobra XS −0.125, cobra S −0.125 and
  click XS +0.125, each p = 0.69; click S −0.938 (b = 0, c = 15, p < 0.001), with all 16 of its
  pairs pending.
- **K7.** In-sample switches can inflate b (K7, part 2). b does not clear here, so the caveat
  changes nothing.
- **Power.** Part 1's simulation gave the loop test 80% power only for a difference of 18 to 25
  points, with every pair observed (DL-412).

**Q-25's branch, as the registered rule reads it.** The branches are read in the order Continue,
Change course, Stop (Q-32, DL-411) **[hypothesis — the rates and intervals of section 3,
recomputed with `crb.core.stats.wilson_interval`. The reachable rate is part 4's prior, XS 13 of
23 [0.368, 0.744] and S 7 of 30 [0.118, 0.409], measured at apparatus 2.2 in the host posture.
The stack's records are not in this repository]**:

- **Continue does not fire.** No cell delivers: no `S3` reading reads `deliver`, `S1` never ran,
  and so no cell has a proven standard (Q-27). The loop does not clear (above).
- **Change course does not fire.** `S1` was not run in any cell, so the test author's clause
  reads "did not move". Click S's `A0+L` counted no commit, so it has no rate to move. In each
  complete cell, `A0+L`'s rate lies inside `A0`'s fixed-n Wilson interval:
  - cobra XS 0.563, inside [0.444, 0.858];
  - cobra S 0.375, inside [0.280, 0.720];
  - click XS 0.625, inside [0.280, 0.720].
- **Stop fires.** Three cells are complete: cobra XS, cobra S and click XS. Click S's arms ran 3
  and 0 of 16, and it would meet the reach clause too if it were counted (0.118 ≤ 0.939). In each
  complete cell nothing moves, and the reachable rate's lower bound is at or below `A0`'s upper
  bound:
  - cobra XS: 0.368 ≤ 0.858 (XS);
  - click XS: 0.368 ≤ 0.720 (XS);
  - cobra S: 0.118 ≤ 0.720 (S).

Wave 3's branch on the registered rule is therefore **Stop**, and it is not the default.

**What the read rests on.** Two separate checks, run from the lead session, recomputed the pair and the branch from the
stack's database and the registration. Each matched Claude Code's read with no discrepancy, and
each tried to refute it **[hypothesis — the checks' outputs in the lead session's transcript, and
the stack's rows and readings on 2026-11-10 at about 17:40Z, apparatus 2.4; those records are not
in this repository]**. These are the choices the read rests on:

- **Disqualified rows count as misses**, as the registered rule and the readings count them. This is
  the only one of these choices that flips the branch. The scratch-path disqualifications could
  instead be counted clean, as an upper bound, since those rows were never graded. Cobra XS `A0`
  would then read 14 of 16 [0.640, 0.965], and `A0+L` 10 of 16, 0.625, which lies just outside, so
  Change course would fire. Asked after this read, Paul kept the registered rule: the carve-out
  session asked "Count disqualified rows as misses, as registered, and leave Wave 3's verdict
  alone", and Paul answered "Yes". So the branch rests on the rule fixed before the data, not on a
  treatment chosen knowing that it flips the branch **[hypothesis — the carve-out session's question
  and Paul's "Yes", relayed to the lead session at 18:46:01Z on 2026-11-10; at 18:49:00Z Paul said
  to take that session's commands as Paul's own; neither transcript is in this repository]**.
- **A completed cell** is one whose two blind arms ran their 16 commits, the registration's own
  sense ("When it is read"). Stop also fires on any narrower set of these cells that is not
  empty.
- **"Moves" is two-sided**, as "lies outside" reads, so a drop counts.
- **DL-404's label is not earned.** Q-30's "insufficient — infrastructure" label (DL-404) applies
  when a miss that makes a reading insufficient is served as an outage, a harness fault, a cancel
  or a missing row. None is. Cobra S's three `S3` misses are served `disqualified`. Click XS's
  three are served as two protocol misses (rows 710 and 711, whose edits were discarded when the
  builder reached for the pytest its image lacks, section 10) and one budget miss (row 714). If
  Paul classed cobra S's disqualifications and click XS's two discarded builds as harness faults,
  both readings would carry the label, and Stop would rest on cobra XS alone. Either way the
  branch stays Stop, which Paul's answer above leaves alone.
- **Paul's close counts as the campaign ending first** (part 1).
- **The reachable rate is a prior** from apparatus 2.2 in the host posture, which Paul confirmed
  (DL-412). Stop's reach clause hardly depends on it: the prior's lower bound would have to
  exceed 0.720 (cobra S, click XS) or 0.858 (cobra XS) for the clause to fail, and it is 0.118 at
  S and 0.368 at XS. Read the other way, at S an `A0` of 0 of 16 still meets it; at XS, only an
  `A0` of 2 of 16 or fewer would not.

**What Stop says, and whose decision follows.** Q-25 names the branch, and the decision Wave 3
informs is Paul's. Q-19 (DL-377) set it "on Friday 6 November 2026, or when Wave 3 reports, if
that is sooner". The 6 November date passed before Wave 3's first row, written on 2026-11-09.
DL-415 (PR #108, not yet on `main`) voids the date, so Wave 3's report is the only trigger left.

Stop is the rule's read of these rows: the sealed rate had already reached the reachable rate,
the loop did not move it, and the test author never ran (`S1`'s clause reads "did not move" by
default). It is not a finding that the loop or the test author cannot help
**[hypothesis — part 1's pre-run power simulation and section 10's findings; the stack's records
are not in this repository]**:
- the loop test had 80% power only for a difference of 18 to 25 points, even with every pair
  observed;
- the test author never ran;
- stage 1's measurement faults count as misses in both arms (section 10).

Earlier, the carve-out session relayed Paul's plan to close on this report, fix the measurement and
design a new wave, and called that plan "Change course". That label describes Paul's plan, and it
came before this read was made. It is not Q-25's branch. Asked after the read, Paul left Wave 3's
verdict at Stop (above) **[hypothesis — the carve-out session's messages to the lead session on
2026-11-10, before the close at 17:33:07Z, and its question and Paul's "Yes", relayed at 18:46:01Z;
neither transcript is in this repository]**. DL-416 records the label and Paul's answer.

**Step 10, the loop switch.** It was restored on 2026-11-10 to `auto_apply` off with an empty
overlay, with the reason "Wave 3 closed on the stage-1 report (DL-416); step 10 restores the
switch to step 4's state, off":
- for cobra, record `beaccf3a5089716e` at 17:37:10Z;
- for click, record `c7bfbeda017d3891` at 17:37:29Z.

The state differs from step 4's in one respect: the switch now has records, where step 4 read
"never switched". The applied changes stay on each repository's chain, and they lie dormant while
the switch is off:
- cobra `b383c935…` and `5f1bdc05…`;
- click `67853265…`, `de907765…`, `380316af…` and `2bf857ee…`.

The factory rows did not move: cobra holds 3 and click 0 **[hypothesis — read from
`GET /api/v1/learn/register?repo=<repo>` and `GET /api/v1/grades?process_step=factory` for each
repository after the restore, 2026-11-10 at about 17:38Z; those records are not in this
repository]**.

**What stays open.**
- **Step 11**, the reviews of stage 1's clean blind rows, has not run. It needs the reviewer's
  account, which Paul creates, Claude's reviews in a fresh session and Paul's own 10 (part 3). The
  close does not decide it.
- **Step 12**, the published rows, has not run. Q-25 requires it whichever branch fires.
- **The decision Wave 3 informs** is Paul's (Q-19, DL-377; DL-415).
- **Section 10's findings** were held by the FREEZE. Once it ends at this record's merge, they
  become work for the carve-out session's fix pull requests and input to whatever Paul decides next.
