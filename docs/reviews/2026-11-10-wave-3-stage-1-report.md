# Wave 3 — the stage-1 report — 2026-11-10

**Status.** Stage 1 of the Wave 3 campaign `cmp_8e1f261023db8a26a40e0e84` has ended at its line
on Claude Code's reading of "fits", which part 2 does not contain. On that reading nothing more
fits under $54.00. No stop happened, and the protocol is not complete. Read literally, part 2
still admits at least one more small run, and no record says where a literal run would lead
(section 7) **[hypothesis — the campaign's tally on 2026-11-10 at about 10:55Z; those records are
not in this repository]**. Paul chooses between attesting the reading and having the literal run
made first. Only then can decision 9's fixed rule (Q-26, DL-400) release stage 2,
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
record counts a disqualified row as a miss, as the readings do. Paul has not decided how the
disqualifications suspected to be harness false positives are treated (section 10), so each arm's
upper bound with them counted clean is in section 3 as well.

## Summary for Paul

The stage at a glance **[hypothesis — read from the stack's `runs`, `grades` and `events` tables
and `GET /api/v1/readings` on 2026-11-10 between 10:50Z and 11:10Z, apparatus 2.4, n = 161 rows;
those records are not in this repository]**:

- **Spend.** Stage 1 spent $52.708356 (£39.04) of the $54.00 line, author calls included, over
  12 runs and 161 rows. $1.29 (£0.96) is left. The dearest attempt so far cost $0.86, so by part
  2's rule the largest cap that still fits is $0.43, below one click S blind attempt ($0.555 on
  average over its 3).
- **No stop.** No stop-list item fired. The image Ids matched at stage 1's start and at every
  check since. One worker ran at a time. It was replaced twice, each time between runs: at 02:44Z,
  when Paul restarted the stack onto `406722a6`, and at 08:42Z, for the switch to click's builder
  image on Paul's "A, go ahead with click". Nothing was reclaimed or abandoned. No row was
  disqualified for `nested_model_call`, and no reading's checks arm moved.
- **The readings.** None delivers. Cobra XS is `undecided`: its pool of 17 cannot reach the
  first look at 20, so its `S3` arm never ran. Cobra S, click XS and click S read `insufficient`
  at their third miss. Cobra S's three misses are all disqualifications on builder scratch paths,
  suspected harness false positives whose treatment Paul has not decided. Those rows were never
  graded; counted clean, the look would read 20 of 20. `S1` stops in every cell. Each reading's
  next act is a new reading, which is Paul's call. Nothing is amended.
- **The descriptive arms.** Three cells have both arms complete at 16 commits each. Click S `A0`
  has run 3 of its 16 and `A0+L` none, so click S waits on a look. Four of cobra XS `A0+L`'s seven
  misses are refused `git -C` calls, and the scratch-path disqualifications fall in both cobra
  arms, so no `A0+L` effect, for or against, can be read.
- **"Fits" — your choice.** Part 2 does not say what "fits" means. I read a run as fitting only
  when its cap holds one attempt at the arm's expected cost, so on my reading nothing more fits.
  Read literally, a run capped at up to $0.43 on click S `A0`'s next commit still fits. You choose:
  (a) attest my reading in a decision-log row, as DL-400 recorded a reading I took, and stage 1
  ends now; or (b) have me make the literal run, or runs, under C-STAGE1-RUNS first. I recommend
  (b): it is part 2's rule as written, and its rows are real click S `A0` rows. Its risk: the
  worker does not bound a run's first attempt, and one dearer than $1.29 would overrun the
  campaign. That is a stop, and DL-400 would then release nothing. No attempt of the 161 cost more
  than $0.86. Section 7 has the detail.
- **Stage 2.** It runs click S only: `A0`'s 13 pending commits (fewer if you choose (b)), then
  `A0+L`'s 16. That is about $10 to $16 of the $55.29 the release leaves, and up to about $25 if
  every attempt cost as much as the dearest so far; each run's cap bounds it. No builder-image
  switch is needed, because click already runs on `crb-builder:local`, but whether the builder
  there can run click's tests is not confirmed (section 10).
- **Part 4.** The statement expects 66.4 clean blind patches for review if click S `A0`'s 2 of 3
  holds, or 59.5 at the value baseline's rate, and I give the two equal weight. Stage 1 has already
  observed 54. Stage 2 adds about 12 (or 5.5), which narrows the share judged mergeable from ±12.0
  points to ±10.8 (or ±11.4). No cell can deliver in stage 2.
- **Your step.** First the "fits" choice above. Then step 22, P-RELEASE-STAGE2, is yours: the
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
(section 10), and Paul has not decided how they are treated. Those rows were never graded, so
whether they were clean is not known; counted clean, the look reads 20 of 20, 1.000 [0.839, 1.000],
an upper bound. Click's two looks depend on whether the builder can run click's tests, which is
not confirmed (section 10) **[hypothesis — the rows' `dq_reason` and the reading's text on
2026-11-10, apparatus 2.4, n = 20 rows; those records are not in this repository]**.

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
are complete (part 1) **[hypothesis — read from the stack's `grades` table and
`GET /api/v1/readings` on 2026-11-10, apparatus 2.4, blind, n = 16 per arm except click S; those
records are not in this repository]**.

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
`A0+L` rows: click XS's now and click S's in stage 2. The two sighted changes answer different
signatures, `which` and `pip download`, with the same lever, the finish gate, and in the sighted
stratum, not the blind one the `A0+L` arms run in **[hypothesis — read from the
`learn.prevention.recorded` events of each change in the stack's `events` table on 2026-11-10;
those records are not in this repository]**.

The calibrated budget profile is in force for click's blind stratum. Click S `A0+L`'s body names
no `budget_profile`, so it will pin `calibrated` at its first reservation, while every `A0` body
names `default`. That is part 1's `A0+L` arm as registered: the loop's changes in force when the
arm runs.

**The loop's switch and the factory rows.** The switch was turned to `config` for cobra at
2026-11-09 23:19:53Z and for click at 23:20:21Z, each with an empty overlay and the reason "Wave
3, the `A0+L` arm (ADR-0026 item 13; DL-371)". Step 10 restores it to the state step 4 recorded:
`auto_apply` off, never switched. The factory rows did not move during stage 1: cobra holds 3 and
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
2's first end). Paul has yet to choose whether that reading stands (below). It did not end on a
stop or with the protocol complete.

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

**When DL-400 releases stage 2.** Once stage 1 has ended at its line, by either path, with a cell
still waiting on a look and no stop, DL-400 releases stage 2. Paul files it at the runbook's step
22, `POST /api/v1/campaigns/{id}/release` with `{"released_gbp": 80, "decision": …}`, the decision
being DL-400's id and its words verbatim. If the literal path ends on a stop, nothing is released.
The amendment records why Paul, not Claude Code, files it.

## 8. What stage 2 buys

Part 4's statement, filled from stage 1, is in the registration's part 6:
[the stage-2 statement amendment](2026-10-09-wave-3-registration.md#the-stage-2-statement-amendment-2026-11-10).
It expects 66.4 clean blind patches for review by the campaign's end if click S `A0`'s 2 of 3
holds, as part 4's rule makes it, or 59.5 if click S `A0` runs at the value baseline's 0.233. This
record gives the two equal weight, because 2 of 3 rests on three rows, one of them a budget miss.
That gives the share judged mergeable to ±10.8 points at p = 0.308 (±11.4 on 59.5), and ±11.7 at
p = 0.5 (±12.3) **[hypothesis — part 4's formulas on stage 1's rates and the value baseline's
priors; the rows are not in this repository]**. Stage 2 asks for up to $54.00 (£40.00). The line
becomes $108.00 for the campaign in all.

**What stage 2 adds.** Stage 1 has already observed 54 clean blind patches. Stage 2 adds about
12.4 of the 66.4, or 5.5 of the 59.5, so it narrows the share's interval by about 1.1 points, or
0.5: from ±12.0 to ±10.8 (or ±11.4) at p = 0.308, and from ±12.9 to ±11.7 (or ±12.3) at worst
**[hypothesis — part 4's formulas at 54 patches and at E; the rows are not in this
repository]**.

**What stage 2 cannot conclude.**
- No cell can deliver. Stage 2 runs no reading arm, and every reading's next act is a new reading.
- Stage 2 completes the last cell, so the loop pair is then tested once (part 1). At 16 commits an
  arm's Wilson interval is about ±0.22 at p = 0.5, so that test can show only a large difference
  **[hypothesis — part 4's Wilson formula at n = 16; no stage-2 row exists yet]**.
- Click S `A0+L` will pin the calibrated budget profile while `A0` runs the default, so any
  difference between them mixes the loop's checks with a budget change.
- Every click row depends on whether the builder can run click's tests, which is not confirmed
  (section 10).

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

Each run's cap bounds what it can spend, whatever the estimate. The plan's own estimates are no
guide here: they cover `S3` only, they came to about half of what stage 1's runs cost (section 10), and they
read 0.0 for `A0` and `A0+L`. The calibrated budget profile that click S `A0+L` will pin has no
measured cost yet.

**No image switch.** Click's runs are pinned to `crb-builder:local`, and the stack already runs that
image, so stage 2 needs no `env.sh` edit and no restart. Cobra's runs used `crb-builder-go:local`;
cobra's stage-1 cells are complete and stage 2 runs no cobra cell. This answers the question the
click builder-image amendment left for this report: the separate image phases it describes are not
needed. It also means all of stage 2 runs on the image whose test-running is not confirmed
(section 10) **[hypothesis — read from the
`reading.reserved` events' builder image for click (`crb-builder:local`) and the output of the local
image-Id check (`check_image_ids.sh`) of 2026-11-10 at 10:54:52Z, which read `crb-builder:local` as
`116f523d…`; neither record is in this repository]**.

**Before the first stage-2 run.** I check that `GET /api/v1/campaigns/{id}` reads `line_usd`
108.00, run the builder's-account check (items 1 to 5) again, and check the five image Ids,
`crb-sandbox-go:main-8ab88ad` among them as `0e796b7e…`. A failed check stops the stage and Paul is
told.

## 10. Findings held for after the FREEZE

None of these is a stop, and the FREEZE blocks a fix to each during the campaign. Each is for the
post-campaign report **[hypothesis — read from the rows, events and builder images named in each
item on 2026-11-09 and 2026-11-10, apparatus 2.4; those records are not in this repository]**:

- **Builder scratch paths may disqualify clean work.** Twelve cobra rows were disqualified for
  modified test infrastructure ("test infrastructure modified", the tamper check's `test_infra`
  kind) on the builder's scratch paths: eleven on the in-repository Go build cache (`.gocache`,
  `.gotmp/cache`) and one on `.tmp/out.json`. Nine fell in the descriptive arms and three in cobra
  S's look. They are suspected harness false positives, but they were never graded, so whether
  they would have been clean is not known, and Paul has not decided how they are treated. Two
  more rows, 684 and 700, both on commit `e0fefb2b`, were disqualified for modified test files;
  this record does not class them with the scratch-path rows.
- **The archaeology guard may refuse the worktree's own root.** Five refused calls were
  `git -C /work …`: rows 641, 642, 647 and 652 in cobra XS `A0+L`, and 703 in cobra S `A0+L`. The
  suspected mechanism is that the guard resolves `/work` to the host path; it is not confirmed.
- **The time-order rule kept T-ARCH from cobra S.** The line was taught by a commit dated
  2026-04-24, and 15 of cobra S's 16 commits are older, so `A0+L` on cobra S measured roughly
  `A0` plus the finish gate. The rule works as designed.
- **Click's builder may not see its dependencies.** The builder container mounts `/deps/site`
  read-only, but nothing seen puts it on `PYTHONPATH`, and `crb-builder:local` has no `pytest` or
  `uv`. The builder then tries network installs, which the seal refuses. That fits five click
  misses: rows 710, 742 and 776 (`pip download`) and 711 and 774 (`uv run`). Whether the builder
  can run click's tests is not confirmed; if it cannot, every click row measured a builder working
  without them.
- **The loop learns from sighted runs and old evidence.** Click's first change, `de907765…`, was
  applied at the end of a sighted `S3` run and rests on 11 blind attempts keyed
  `2.2|claude_code|claude-sonnet-5`, yet it is in force in apparatus 2.4 `A0+L` rows. Cobra's
  changes rest on evidence keyed 2.4. Two more click changes, in the sighted stratum, were applied
  at the end of click S's `S3` run; they answer different signatures with the same lever.
- **The plan's estimates run about two times low and cover `S3` only.** Cobra S's look cost $7.52
  against $3.66 (2.06 times), click S's $7.44 against $3.42 (2.17 times) and click XS's $5.37
  against $2.70 (1.99 times). All stayed under their caps. The plan's estimates for `A0` and
  `A0+L` read 0.0.
- **"Fits" needs one meaning.** For this campaign it is Paul's choice (section 7). Part 2 should
  define it, and the worker should bound a run's first attempt, which it now leaves unbounded
  (G-938).
- **The submit gate's login check can time out.** Cobra S `A0`'s first submit at 03:31Z was refused
  422 `builder_login_invalid` after a 60-second verification timeout. Nothing was queued or spent,
  and the resubmit at 03:41:39Z verified.
- **The tally's `authoring_usd`** should be checked against the one author call ($0.001697) when
  the stage-2 runs are read.
