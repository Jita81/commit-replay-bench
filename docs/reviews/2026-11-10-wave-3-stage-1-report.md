# Wave 3 — the stage-1 report — 2026-11-10

**Status.** Stage 1 of the Wave 3 campaign `cmp_8e1f261023db8a26a40e0e84` has ended at its line.
Nothing more fits under $54.00, no stop happened, and the protocol is not complete. Click S still
waits on a look, so decision 9's fixed rule (Q-26, DL-400) releases stage 2. Paul files the release
(the start-up runbook's step 22). This record is the registration's part 5 step 8. Part 4's
stage-2 statement is in the registration's part 6, in
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
is descriptive: fixed-n, and not adjusted for the sequential look. A disqualified row counts as a
miss.

## Summary for Paul

The stage at a glance **[hypothesis — read from the stack's `runs`, `grades` and `events` tables
and `GET /api/v1/readings` on 2026-11-10 between 10:50Z and 11:10Z, apparatus 2.4, n = 161 rows;
those records are not in this repository]**:

- **Spend.** Stage 1 spent $52.708356 (£39.04) of the $54.00 line, author calls included, over
  12 runs and 161 rows. $1.29 (£0.96) is left. The dearest attempt so far cost $0.86, so the
  largest cap that still fits is $0.43, below one click S blind attempt.
- **No stop.** No stop-list item fired. The image Ids matched at every stage start. One worker ran
  at a time: it was replaced at 02:44Z and at 08:42Z, each time between runs, and nothing was
  reclaimed or abandoned. No row was disqualified
  `nested_model_call`, and no reading's checks arm moved.
- **The readings.** None delivers. Cobra XS is `undecided`: its pool of 17 cannot reach the
  first look at 20, so its `S3` arm never ran. Cobra S, click XS and click S read `insufficient`
  at their third miss. `S1` stops in every cell. Each reading's next act is a new reading, which
  is Paul's call. Nothing is amended.
- **The descriptive arms.** Three cells have both arms complete at 16 commits each. Click S `A0`
  has run 3 of its 16 and `A0+L` none, so click S waits on a look and DL-400 releases stage 2.
- **Stage 2.** It runs click S only: `A0`'s 13 pending commits, then `A0+L`'s 16. That is about
  $12 to $16 of the $55.29 the release leaves. No builder-image switch is needed, because click
  already runs on `crb-builder:local`.
- **Part 4.** The statement expects 66.4 clean blind patches for review, which gives the share
  judged mergeable to ±10.8 points, and ±11.7 at worst.
- **Your step.** Step 22, P-RELEASE-STAGE2, is yours: the three `wave3_post.py` commands in the
  runbook's step 22. I check the line reads $108.00 before any stage-2 run.

Section 10 lists the findings held for after the FREEZE.

## 1. Spend

Each run under the campaign, with its cost as the ledger records it, in dollars and in pounds at
1.35 (DL-379) **[hypothesis — read from the stack's `grades` table (rows 619 to 779) and the
smoke run's `author.attempt` event on 2026-11-10 at about 10:55Z, apparatus 2.4, n = 161 rows;
those records are not in this repository]**:

| run | cell | arm | rows | cost | in pounds |
|---|---|---|---|---|---|
| `0a7048da…` | cobra M (smoke) | `S1@gpt-oss-120b` | 1 | $0.000000 | £0.00 |
| `2dfb6a08…` | cobra M (smoke) | `A0`, no reading | 1 | $0.264145 | £0.20 |
| `27f45991…` | cobra XS | `A0` | 16 | $3.904366 | £2.89 |
| `f224053e…` | cobra XS | `A0+L` | 16 | $3.228201 | £2.39 |
| `5a395c04…` | cobra S | `S3` | 20 | $7.523129 | £5.57 |
| `715c67b5…` | cobra S | `A0` | 16 | $5.310428 | £3.93 |
| `f9a0e9e4…` | cobra S | `A0+L` | 16 | $6.685980 | £4.95 |
| `7d5d4bd7…` | click XS | `S3` | 20 | $5.370786 | £3.98 |
| `77139b64…` | click XS | `A0` | 16 | $5.608998 | £4.15 |
| `9e67c355…` | click XS | `A0+L` | 16 | $5.707909 | £4.23 |
| `ec9f81a4…` | click S | `S3` | 20 | $7.438403 | £5.51 |
| `73e160d8…` | click S | `A0` | 3 | $1.664313 | £1.23 |
| the test author's calls | — | — | — | $0.001697 | £0.00 |

| by cell | cost | in pounds |
|---|---|---|
| cobra XS | $7.132567 | £5.28 |
| cobra S | $19.519538 | £14.46 |
| click XS | $16.687693 | £12.36 |
| click S | $9.102716 | £6.74 |
| the two smoke runs | $0.264145 | £0.20 |
| the test author's calls | $0.001697 | £0.00 |
| **the campaign** | **$52.708356 of $54.00** | **£39.04 of £40.00** |

| by arm | cost | in pounds |
|---|---|---|
| `S3` (sighted) | $20.332318 | £15.06 |
| `A0` (blind) | $16.488106 | £12.21 |
| `A0+L` (blind) | $15.622090 | £11.57 |

The rows sum to $52.706659 and the one author call adds $0.001697, $52.708356 in all. That is the
sum the campaign's tally takes, over unrounded costs (`src/crb/core/campaign.py`): the tally
served when run `73e160d8…` was admitted, $51.044042, is the same sum over the rows before it.
Each figure in these tables is its own unrounded sum rounded once to six places, so a table's
parts can differ from its total in the last place. No run is live, so nothing is held, and the
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

| cell | reading | pool | look run | rows | clean | missed | state | decided at | Wilson 95% (sighted) |
|---|---|---|---|---|---|---|---|---|---|
| cobra XS | `rdg_e6bbe59930cd26e728a24364` | 17 | none | 0 | 0 | 0 | `undecided` | the pool cannot reach the look at 20 | — |
| cobra S | `rdg_2910bad1397a488cd6c05457` | 27 | `5a395c04…` | 20 | 17 | 3 | `insufficient` | the 20th commit (3 of 20 missed) | 0.850 [0.640, 0.948] |
| click XS | `rdg_1d932e9f635d6583f111d548` | 30 | `7d5d4bd7…` | 20 | 17 | 3 | `insufficient` | the 10th commit (3 of 10 missed) | 0.850 [0.640, 0.948] |
| click S | `rdg_471d0e7f4f51146392e8c788` | 38 | `ec9f81a4…` | 20 | 13 | 7 | `insufficient` | the 7th commit (3 of 7 missed) | 0.650 [0.433, 0.819] |

Click XS read 7 of its first 10 clean, 0.700 [0.397, 0.892], and click S 4 of its first 7, 0.571
[0.250, 0.842]. Each look run went on to 20 commits because the plan's request named 20 (part 2,
PW-4); the rows after the third miss are reserved under the reading and change nothing. Cobra S's
three misses are all disqualifications: one on a builder scratch file (`.tmp/out.json`) and two on
the in-repository Go build cache (`.gocache`, section 10) **[hypothesis — the rows' `dq_reason` and
the reading's text on 2026-11-10, apparatus 2.4, n = 20 rows; those records are not in this
repository]**.

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

| cell | arm | run | enrolled | observed | clean | disqualified | Wilson 95% (blind) |
|---|---|---|---|---|---|---|---|
| cobra XS | `A0` | `27f45991…` | 16 | 16 | 11 | 3 | 0.688 [0.444, 0.858] |
| cobra XS | `A0+L` | `f224053e…` | 16 | 16 | 9 | 1 | 0.562 [0.332, 0.769] |
| cobra S | `A0` | `715c67b5…` | 16 | 16 | 8 | 3 | 0.500 [0.280, 0.720] |
| cobra S | `A0+L` | `f9a0e9e4…` | 16 | 16 | 6 | 4 | 0.375 [0.185, 0.614] |
| click XS | `A0` | `77139b64…` | 16 | 16 | 8 | 0 | 0.500 [0.280, 0.720] |
| click XS | `A0+L` | `9e67c355…` | 16 | 16 | 10 | 0 | 0.625 [0.386, 0.815] |
| click S | `A0` | `73e160d8…` | 16 | 3 | 2 | 0 | 0.667 [0.208, 0.939] |
| click S | `A0+L` | none yet | 16 | 0 | 0 | 0 | — |

In each complete cell the two arms' intervals overlap, so no difference between `A0` and `A0+L`
is claimed **[hypothesis — read from the table above, n = 16 per arm, apparatus 2.4; the rows are
not in this repository]**.

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

| change | repository | what | stratum | applied at | after run |
|---|---|---|---|---|---|
| `b383c935cf96a6d3` | cobra | `checks.finish_gate=true` | blind | 2026-11-09 23:44:13Z | `27f45991…` (cobra XS `A0`) |
| `5f1bdc05682e7967` | cobra | context line T-ARCH, "Repository history is off limits…" | blind | 2026-11-10 00:13:53Z | `f224053e…` (cobra XS `A0+L`) |
| `de907765ff95e6b2` | click | `checks.finish_gate=true` | blind | 09:18:05Z | `7d5d4bd7…` (click XS `S3`) |
| `678532656dbf3811` | click | `spend.budget_profile=calibrated` | blind | 10:06:05Z | `9e67c355…` (click XS `A0+L`) |
| `380316afbba349ff` | click | `checks.finish_gate=true` | sighted | 10:32:27Z | `ec9f81a4…` (click S `S3`) |
| `2bf857ee6301258d` | click | `checks.finish_gate=true` | sighted | 10:32:27Z | `ec9f81a4…` (click S `S3`) |

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

Stage 1 ended because nothing more fits under $54.00 (part 2's first end). It did not end on a
stop or with the protocol complete.

**The last run.** After click S's `S3` look the campaign had spent $51.044042, with $2.955958 left
and a headroom of $0.797871, so a cap of up to $2.158087 fitted. Click S `A0` was queued at
10:45:39Z as `73e160d8…`, with a cap of $2.15 and the reading's first 16 commits. The worker
reserves, before each attempt, the dearest attempt the run has made. After three attempts that was
$0.86, which would have passed the cap, so the run halted at 10:50:30Z, `failed` with
`stopped_code` `spend_cap` and 13 commits still pending. A halt at the cap is not a stop: the run
spent $1.664313, under its cap and far under its cap plus the headroom it was admitted with
**[hypothesis — read from the run, its `run.spend_cap` event and the `campaign.admitted` payload
on 2026-11-10 at about 10:51Z, apparatus 2.4, n = 3 rows; those records are not in this
repository]**.

**Nothing more fits.** The campaign has spent $52.708356 and $1.291644 is left. Row 779's
$0.863184 is now the dearest attempt the campaign has seen, so it is the headroom of any new
run, and the largest cap that fits is $0.428460. Click S `A0`'s three attempts averaged $0.555,
and its dearest cost $0.86 **[hypothesis — arithmetic on the figures above; those rows are not in
this repository]**.

**How "fits" was read.** Part 2 admits a run when spent, held, its cap and its headroom stay at or
under the line, and sets each cap "to fit". This record reads a run as fitting only when its cap
holds at least one attempt at the arm's expected cost, so that the headroom stays a reserve for an
attempt that overshoots, not the money for a planned one. Read literally, a run capped at $0.43
would still be admitted, and it would run one attempt, because the worker reserves nothing before
a run's first. That one attempt would leave too little for any further run, and click S would
still wait on a look (`A0` at 4 of 16). So the two readings differ only in which stage one commit's
row belongs to, and DL-400 releases stage 2 under both **[hypothesis — code reading of `admit` in
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

**So DL-400 releases stage 2.** Stage 1 ended at its line with a cell still waiting on a look, and
neither a stop nor a complete protocol holds the release back. Paul files it at the runbook's step
22, `POST /api/v1/campaigns/{id}/release` with `{"released_gbp": 80, "decision": …}`, DL-400's id
and words. The amendment records why Paul, not Claude Code, files it.

## 8. What stage 2 buys

Part 4's statement, filled from stage 1, is in the registration's part 6:
[the stage-2 statement amendment](2026-10-09-wave-3-registration.md#the-stage-2-statement-amendment-2026-11-10).
It expects 66.4 clean blind patches for review by the campaign's end, which gives the share judged
mergeable to ±10.8 points at p = 0.308 and ±11.7 points at p = 0.5 **[hypothesis — part 4's
formulas on stage 1's rates and the value baseline's priors; the rows are not in this
repository]**. Stage 2 asks for up to $54.00 (£40.00). The line becomes $108.00 for the campaign in
all.

## 9. What stage 2 runs

Only click S's descriptive arms are left. Stage 2 runs them in this order, each capped to fit
under $108.00 **[hypothesis — read from `GET /api/v1/readings` on 2026-11-10 at about 10:55Z, and
an estimate from click S's own stage-1 rows, $0.40 per row over 23 rows or $0.55 per row over the 3
blind ones, apparatus 2.4; those rows are not in this repository]**:

- **click S `A0`**: its 13 pending commits, `becbde5c…` to `607316f9…` in seeded order, with
  `learning` off and `budget_profile` default;
- **click S `A0+L`**: the same 16 commits as `A0`, with no `learning` and no `budget_profile` key,
  once `A0` has finished;
- about 29 attempts in all, roughly $12 to $16 of the $55.29 left after the release.

**No image switch.** Click's runs are pinned to `crb-builder:local`, and the stack already runs that
image, so stage 2 needs no `env.sh` edit and no restart. Cobra's stage-1 cells are complete and
stage 2 runs no cobra cell. This answers the question the click builder-image amendment left for
this report: the separate image phases it describes are not needed **[hypothesis — read from the
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

- **The Go build cache disqualifies clean work.** Eleven cobra rows were disqualified for
  modified test infrastructure ("test infrastructure modified", the tamper check's `test_infra`
  kind) on the builder's in-repository Go cache (`.gocache`, `.gotmp/cache`). It is likely a
  harness false positive. Two of them fell in cobra S's look. Those two rows were never graded, so
  whether they would have been clean is not known.
- **The archaeology guard refuses the worktree's own root.** `git -C /work …` is refused because
  the guard resolves `/work` to the host path. It caused four of cobra XS `A0+L`'s misses and one
  of cobra S `A0+L`'s.
- **The time-order rule kept T-ARCH from cobra S.** The line was taught by a commit dated
  2026-04-24, and 15 of cobra S's 16 commits are older, so `A0+L` on cobra S measured roughly
  `A0` plus the finish gate. The rule works as designed.
- **Click's builder cannot see its dependencies.** The builder container mounts `/deps/site`
  read-only, but nothing puts it on `PYTHONPATH`, and `crb-builder:local` has no `pytest` or `uv`.
  The builder then tries network installs, which the seal refuses. That explains five click
  misses (`pip download`, `uv run`).
- **The loop learns from sighted runs and old evidence.** Click's first change, `de907765…`, was
  applied at the end of a sighted `S3` run on evidence keyed `2.2|claude_code|claude-sonnet-5`.
  Two more were applied at the end of click S's `S3` run.
- **The plan's `S3` estimates run about two times low.** Cobra S's look cost $7.52 against
  $3.66, and click S's $7.44 against $3.42. Both stayed under their caps.
- **"Fits" needs one meaning.** Section 7's reading should be written into part 2's rule, or the
  rule should fix the cap as a number of attempts.
- **The submit gate's login check can time out.** Cobra S `A0`'s first submit at 03:31Z was refused
  422 `builder_login_invalid` after a 60-second verification timeout. Nothing was queued or spent,
  and the resubmit at 03:41:39Z verified.
- **The tally's `authoring_usd`** should be checked against the one author call ($0.001697) when
  the stage-2 runs are read.
