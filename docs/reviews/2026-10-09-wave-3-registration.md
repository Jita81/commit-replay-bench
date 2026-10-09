# Wave 3 — the registration, prepared and not run — 2026-10-09

**Status.** Prepared, not run. No reading is registered and no run is queued. The stack stays
down until Paul Glover restarts it (Q-14). Every step in part 5 is marked "not yet run".

**Authority.** Paul Glover's decision 7 of 2026-10-09, recorded as DL-371: Q-11 (ADR-0026's
values accepted), Q-14 (the restart and the money), Q-06 (each campaign is approved with a stated
maximum) and his answer on Wave 3's reviews (decision 5). The source is
`feedback/2026-10-09-project-room-decisions.md` in the private crb-handbook repository. This
record was written against `main` at `48c25abd`.

**Claims in this record.** Nothing here is measured on a graded row. A protocol value is the one
ADR-0026 item 13 fixes. A cost is item 13's projection, or arithmetic on it. The rate of dollars
to the pound is an assumption. Each is tagged where it stands.

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
| the loop pair | descriptive: published with its interval beside the minimum detectable effect; it changes no default | item 13 |

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

## 2. Money

**The ceiling.** Paul Glover approved a hard ceiling of £80 for Wave 3, in two stages (decision
7, Q-14; DL-371). Stage 1 is up to £40. The rest is released only after Claude Code reports stage
1's spend and results. It is the first campaign approved with a stated maximum (Q-06). The £80
covers all of Wave 3: the readings, and the factory rerun and timed intake that PLAN's Wave 3
lists, which this record does not schedule **[aspiration — the ceiling decision 7 sets; nothing
is spent yet]**.

**The rate.** The ledger records dollars. This record converts at 1.35 dollars to the pound, the
fixed rate of the value baseline, which Q-14's own conversion uses too **[hypothesis — an
assumption, not a market rate: the product has no exchange-rate source, as
[the value baseline](2026-09-25-value-baseline.md) says under "What this does not say"]**.

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

**Who holds the ceiling.** The product does not enforce the £80 ceiling. It is held by Claude
Code stopping the campaign. These readings of the code on `main` at `48c25abd` make it so
(P-775, G-957):

- `POST /runs` takes a `max_cost_usd` per run, in dollars. Nothing sums a campaign's runs
  (`RunCreateRequest`, `src/crb/server/schemas.py`).
- That cap is a guard, not a guarantee. It admits an attempt while the run's spend plus a reserve
  stays within it, and the reserve is the dearest attempt so far, so nothing bounds a first
  attempt that has no cost cap of its own (`src/crb/server/spend_cap.py`; G-938). A run capped
  at $0.10 once spent $5.00 on its first attempt (P-261).
- An `S1` replay's test-author calls are not in its spend. Each is an `author.attempt` event
  with its `cost_usd` (`src/crb/factory/author.py`). The replay worker admits an attempt on the
  ledger rows alone (`Spend.of_rows`, `src/crb/server/worker.py`), and `GET /runs/{id}` serves
  `cost_usd` from the rows. A factory run adds its author's calls; a replay does not.

**The tally.** Claude Code keeps one running total for the campaign, in dollars:

- **spent** — for every run of the campaign, its `cost_usd` (`GET /runs/{id}`), plus, for an
  `S1` run, the `cost_usd` of each `author.attempt` event in its log (`GET /runs/{id}/events/log`,
  the MCP tool `crb_run_events`);
- **held** — for every run queued or running, its `max_cost_usd` less what it has spent, plus its
  headroom;
- **headroom** — the dearest single attempt the campaign has seen, or $5.00 before the first
  (P-261); for an `S1` run, plus its commits still to run times the dearest author call seen, or
  $0.15 before the first (item 13's upper assumption).

A run is queued only when spent, held, its own cap and its own headroom together stay at or under
the stage's line: $54.00 in stage 1, and $108.00 for the campaign in all once stage 2 is
released. Each run's `max_cost_usd` is set to fit. The rule limits how many runs are in flight at
once; a worker runs one at a time (`Worker.run_forever`, `src/crb/server/worker.py`).

**Stage 1 ends** at the first of these:

- nothing more fits under $54.00 by the rule above;
- the protocol is complete: every reading is decided or its pool has ended, and every descriptive
  arm has run its fixed count;
- a stop: a cost the tally cannot know (an event or row with `cost_known: false`, or a run
  refused `spend_cap_unpriced` because a model it would call has no known price), a refused
  registration, a run whose spend passes its cap plus its headroom, or spend the tally cannot
  place against a run.

On a stop, Claude Code queues nothing more and cancels the runs that have not started. A running
run ends at its cap, which was set to fit.

**What Claude Code reports at the end of stage 1**, to Paul and as a dated record under
`docs/reviews/`:

- spend per cell and per arm, in dollars and in pounds at 1.35, the author calls shown apart, and
  the total against $54.00;
- for each reading arm: commits counted, clean and missed, and its state (`deliver`,
  `insufficient`, `look_pending` with the commits still needed, or `undecided`);
- for each descriptive arm: commits run and clean;
- what stage 2 would buy: the statement of part 4.

**Stage 2** starts only on Paul's written release, recorded in the decision log. Its line is
$108.00 for the campaign in all. Nothing is queued while the release is awaited.

**Assumptions.** The ceiling is held against the ledger's `cost_usd`, the cost the builder
reports, not against the provider's bill. Claude Code's own sessions (this one, the campaign's
and the reviewer's) are not counted against the £80 **[hypothesis — Paul to confirm]**.

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

**Paul's 10.** Paul reviews 10 of the clean blind patches himself, drawn once, when the
campaign's last run has ended **[aspiration — the draw decision 7 asks for; not yet made]**:

1. order the commits that have at least one clean blind patch by ascending
   `sha256("crb.wave3.review.v1|" + repo + "|" + commit sha)`, both repositories together;
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
  95% interval, and Cohen's κ with a bootstrap percentile interval (10,000 resamples from a fixed
  seed; resamples where κ is undefined are counted and reported);
- on the headline verdict, the secondary measure: the same two figures over the six verdicts.

At n = 10 both intervals are wide, and the report says so plainly: 9 agreements of 10 give a
Wilson 95% interval of 59.6% to 98.2% **[hypothesis — an illustration of the width at n = 10, not
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
reviewed patches judged mergeable, at n = E:

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
says the same of attempts and tasks]**.

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
Precision bought: the share judged mergeable to ±<h> points (Wilson 95%, n = <E>, p = <p>),
  ±<h at p = 0.5> points at worst. Paul's 10 give the agreement as in part 3.
Stage 2 asks for up to $<t> (£<t / 1.35>); the line becomes $108.00 for the campaign in all.
```

## 5. The steps after the restart

In order. Each is **not yet run**. Claude Code runs a step only on the stack Paul has restarted,
and stops and reports at the first step whose success condition fails.

| # | step | who and how | success condition | state |
|---|---|---|---|---|
| 0 | restart the stack on merged `main` | Paul, by handbook page 08's steps; the container runtime is colima, so step 7 there is `colima start` (HB-14) | `/health` reads ok and the worker is up | not yet run |
| 1 | confirm the instrument | Claude Code: `crb_version` (MCP) or `GET /version`; `GET /api/v1/repos` | apparatus `2.4`; the repositories `cobra` and `click` listed [hypothesis — the names the 2026-09-25 export used] | not yet run |
| 2 | fix the test author, choice (a) | Claude Code reads `raw.factory.test_author` from `GET /api/v1/settings` (admin); if it is empty or names `claude-sonnet-5`, Paul sets `CRB_FACTORY__TEST_AUTHOR` and restarts the worker | a `builder:model[:provider]` whose model is not `claude-sonnet-5`; its canonical model recorded here as `<author>` | not yet run |
| 3 | mine and qualify each repository, at no model cost | the Posture panel at `/repos/cobra` and `/repos/click` ("Qualify for this posture — no model spend"), or `crb_start_run` with `{"kind": "mine", "repo": "cobra"}` then `{"kind": "qualify", "repo": "cobra"}`, and the same for click | each run `succeeded` with a `cost_usd` of 0; `GET /api/v1/repos/<repo>/posture` shows `executor` `docker`, a `posture_class` of `docker/<tree>/sealed` and an empty `stale_reason`; each cell holds at least 20 qualified `bug.fix` commits, the first look, and each cell's count is noted here | not yet run |
| 4 | register the four readings | Claude Code, `POST /api/v1/readings` over HTTP with an operator session (`POST /api/v1/auth/login`, then `X-CSRF-Token` from the `crb_csrf` cookie, `__Host-crb_csrf` under TLS); no screen and no MCP tool registers a reading, and `crb reading register` writes only a local file. The body is below | `201` for each, with `reading_id`, the `pool` in seeded order, `pool_sha256` and `pool_rule`; `GET /api/v1/readings?repo=<repo>` lists each, its cell's budget spent at 2.10% of 5%. A refusal (`pool_seen`, `budget_spent`, `pool_not_blind`, `invalid_reading`) stops the campaign before any spend. The ids and pool sizes are added here in an amendment commit | not yet run |
| 5 | turn the loop on for `A0+L`, choice (b) | Paul or Claude Code: the switch on the Learn page, or `PUT /api/v1/learn/switch?repo=<repo>` with `{"auto_apply": "config", "reason": "Wave 3, the A0+L arm (ADR-0026 item 13; DL-371)"}`; the state before is recorded here | the Learn page reads `config` for cobra and for click | not yet run |
| 6 | queue the runs, cell by cell, under part 2's rule | Claude Code, `crb_start_run` (`POST /api/v1/runs`). **`S3`**: the cell's request from `crb_remeasure_plan` (`GET /api/v1/learn/remeasure?repo=<repo>`), plus `max_cost_usd` and `"budget_profile": "default"`. **`A0`**: `{"repo": "<repo>", "kind": "blind", "builder": "claude_code", "model": "claude-sonnet-5", "provider": "anthropic", "task_ids": [the first 16 of the reading's pool], "learning": "off", "budget_profile": "default", "max_cost_usd": <cap>}`. **`A0+L`**: the same with no `learning` and no `budget_profile`. **`S1`**: its request from the remeasure plan once `S3` delivers, plus `max_cost_usd` and `"budget_profile": "default"` | each run ends `succeeded`, or `failed` with `stopped_code: spend_cap`; its rows carry the arm queued, at rung `r1`, apparatus 2.4, in the sealed posture; `GET /api/v1/readings` counts the run's commits under that arm | not yet run |
| 7 | keep the tally | Claude Code, after each run: `cost_usd` from `GET /api/v1/runs/{id}`, and for `S1` the `author.attempt` costs from `crb_run_events` | spent and held stay at or under the stage's line; otherwise part 2's stop | not yet run |
| 8 | report stage 1 | Claude Code, when stage 1 ends (part 2) | Paul has the report and part 4's statement; the record is committed under `docs/reviews/` | not yet run |
| 9 | stage 2 | Paul releases it in writing; the release is recorded in the decision log; Claude Code resumes step 6 with the line at $108.00 | the release is recorded before any stage-2 run is queued | not yet run |
| 10 | restore the loop switch | Paul or Claude Code, after the last `A0+L` run | the switch reads the state recorded at step 5 | not yet run |
| 11 | the reviews | Paul creates the reviewer's account; Claude reviews in a fresh session (part 3); Claude Code draws Paul's 10; Paul files his | a review on every clean blind row a reading counts; Paul's 10 filed after Claude's; the agreement reported with its intervals | not yet run |

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
  "author_model": "<author>"
}
```

The other bodies change only `repo`, `size` and `language`: cobra S (`go`), click XS and click S
(`python`). `pool`, `since`, `taxonomy`, `posture_class` and `org_class` are left out, so the
pool is every qualified commit of the cell (choice (c)), the class set is the global vocabulary,
and the posture class is the deployment's own, which must be sealed.
