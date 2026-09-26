# ADR-0020 — A bug is closed by prevention: every failure class gets the strongest change it admits, and is closed only when the attempts that saw the change stop showing it

**Status:** Accepted (operator decision DL-053; built in the value wave, stream L). It follows the
operator's instruction of 2026-09-25 and was chosen by judging a panel of independent designs.
Amended at the value merge after an adversarial review (§5, §6.6, §6.9–6.11, §6.14 below;
docs/PREVENTION.md P-019 to P-023).
**Date:** 2026-09-25
**Apparatus impact:** none — deliberately. The loop changes what a builder is *given*: a process
switch, or a checklist line in the brief. It never changes what a grade *means*. No belt, grader,
failure rule, routing threshold or cell key moves, so `crb.core.version.APPARATUS_VERSION` stays
`2.2`. This follows the reasoning of ADR-0016: an input the row records is not a moved instrument.

The loop's own seams are:

- its rule versions, stamped on every record it writes: `crb.prevention.sig.v1` (what a class is)
  and `crb.prevention.rule.v1` (when a change is kept, retired or closed);
- the hashed `learn*` labels on every row.

The class rule sits on top of the product's failure rule (`derive_failure_kind`), and that rule
stays behind the apparatus version. The class rule is part of every comparability key, so a change
to it breaks comparability as openly as an apparatus bump would. It does not, however, mark every
sign-off stale (ADR-0015 §4).

A prevention the loop files that *would* change the failure rule needs its own ADR and an apparatus
bump. An example is a refused command that no longer voids the attempt. The loop can only file such
an item.

## Context

The operator, 2026-09-25: *"We should be learning from a bug and then going back to update our
process or context to remove it moving forward."* Learning here is not a statistic that tightens as
`n` grows. For every failure class the product sees, it means a change to the process or the
context, and proof that the class stopped.

### What exists, and what it does not do

- **Three reports, no action.** `crb.core.learn` derives three reports: refusal triage, the
  strengthening backlog and the re-measurement plan. Each stops where a person decides
  (`docs/LEARNING-LOOP.md` §3), and none changes the next attempt.
- **The harness command is already in the blind brief.** Since 2026-09-14 (`b6e438a`),
  `adapter.build` sets `BuildBrief.harness_command` on every attempt, so the blind brief names the
  scope-free test command. Telling a blind builder how to run the tests is a lever already pulled.
- **Preflight exists, per run.** `adapter.Preflight` runs belt 5's fixers and one repair turn. It is
  off by default. Stream W's formatter step and finish gate make the same idea switchable per
  repository.
- **Verdicts and outcomes are recorded.** The review store keeps human verdicts
  (`crb.core.review.latest_reviews`). The factory's evidence chain records closed pull requests and
  refused deliveries (`crb.factory.evidence`).
- **The write-back was never merged.** The parked `feat/w2-l` write-back registers learn items onto
  a frozen backlog, with the signed-in session as the decider.
- **System events are not tamper-evident.** The `events` table's triggers make system events
  append-only, but they are only *sequenced*: `append_system_event` writes no hash chain. A record
  that must be tamper-evident cannot rely on the event alone.
- **One refused command voids the whole attempt.** The Claude Code builder records a refused shell
  command as a protocol violation even when its own deny rule stopped the command
  (`crb.builders.claude_code`). So one refused `go mod tidy` voids everything the builder did.

### What the ledger shows

All figures come from the operator's export of 2026-09-25.

- **Most failures are process losses.** Budget stops and protocol refusals are 74 of the 132
  non-clean valid rows [measured — n = 618 exported rows, 322 valid once outage and harness rows are
  excluded; method: the product's failure rule (`derive_failure_kind`, fed the export's error
  classes) over the export; apparatus 2.0–2.2].
- **No change has ever been credited.** No change the product made has been recorded against a
  failure class, so none can be credited. On click, network refusals fell from 5 of 16 attempts
  under apparatus 2.0 to 1 of 66 under 2.2, once the harness command reached the blind brief.
  Nothing recorded that change [measured — n = 16 and 66 attempts, outage rows excluded; method: the
  product's failure rule over the export; apparatus 2.0 and 2.2]. The class is quiet, not closed,
  and no rule can tell the two apart.
- **Advice did not stop the same class elsewhere.** On 2026-09-15, cobra had 7 blind network
  refusals over 3 tasks, costing $4.40, with the harness command already in the brief [measured — n
  = 38 blind cobra attempts, outage rows excluded; method: the product's failure rule over the
  export; apparatus 2.2].
- **The samples are small.** The repositories the Phase B campaign will replay have few attempts per
  mode. Cobra, click and koa have 19, 11 and 10 blind first attempts under apparatus 2.2 [measured —
  n = 40 blind first attempts (rung `r1`, outage rows excluded); method: the export counted by
  repository; apparatus 2.2]. A rule must say how many attempts it needs before it decides, and must
  not decide early.
- **No reviews for these repositories.** The review store holds no record for cobra, click or koa.
  Its 10 records are for the three NHS repositories [measured — n = 10 review records; method: the
  store's export of 2026-09-25; apparatus 2.2]. The three cobra findings of the critical-friend
  review cannot enter the store, because their patches were not kept.

### Prior evidence

The design respects the following results. They were measured in the Athena programme and have not
been re-measured on this apparatus, so here they are a [hypothesis]:

- enriching the brief with code context was falsified (0 flips and 2 regressions in a paired A/B);
- a "specification lever" turned out to be leakage;
- a distilled checklist beat an essay;
- in-attempt verify-repair was the strongest lever.

So the loop writes operating facts only, as a checklist, and reaches for a process lever before any
text.

### The designs judged

The panel judged these designs:

- *construction first*: every class gets the strongest lever it admits, and climbs automatically;
- *evidence first*: a class closes only on prospective, comparable, held-out evidence;
- *operator first*: one rule a platform team can hold the loop to, one switch, and every change
  reversible by a named person.

This decision takes the third as its spine, the first's lever discipline and the second's
measurement.

## Decision

### 1. The one rule: the loop changes how a change is made, never how it is judged

The loop may switch on only the process mechanisms in this table, and may add checklist lines to the
brief (at most seven). Nothing else.

| lever | what it does | level | built by |
|---|---|---|---|
| `format_step` | runs the repository's own formatter over the changed source files before grading | construction | stream W |
| `finish_gate` | gives the builder the repository's own check commands as a checklist; `done` needs them to pass (in-attempt verify-repair) | gate | stream W |
| `budget_calibrated` | sets caps from the ledger's clean completions in the cell (`spend.budget_profile: calibrated`) | mistake-proofing | stream K |
| a playbook line | states one operating fact from a closed template | advisory | this decision |

The loop may never write anything that grades the builder. That rules out:

- a belt or its switch, including belt 6's `checks.api_stable`;
- the lint plan (`lint`, `lint.disabled`);
- a runner or its options;
- the guards or the guard corpus;
- the oracle, mining and pools;
- routing thresholds, the failure rule and the class rule.

`crb.core.prevention.check_writable` refuses every key outside the table, by name, and the tests
offer it the forbidden ones. A change that needs one of those keys arrives as a filed item for a
person (§5, §9). The loop never switches anything *off*: when it retires one of its own changes, it
removes that change's entry.

This rule is what stops the loop closing a class by going blind.

### 2. What a class is

A class signature has the form `family:sub[:detail]`. It is lower-case ASCII, at most 96 characters
long, and computed on read by `crb.core.prevention.signatures` from hashed row fields only, under
the rule version `crb.prevention.sig.v1`. The families are:

- **`protocol:<guard>:<head>`** — the guard family comes from `learn.parse_violations` (`network`,
  `archaeology`, `tamper` or `other`). The command head comes from `learn.normalise_command`: the
  first one or two word tokens after environment assignments, `cd … &&`, `sudo` and `timeout <n>`.
  Examples are `pip install`, `go mod tidy` and `git log`. Paths, strings, numbers and flags never
  reach it.
- **`budget:<stop_reason>`** — one of `max_turns`, `max_tool_calls`, `max_tokens`, `max_cost_usd` or
  `wall_clock`, or `unrecorded` for rows written before the label existed.
- **`harness:<cause>[:<tool>]`** — found by one ordered table over the row's error. The causes are
  `no-credential`, `runner-tool-missing:<tool>` (including stream D's pre-check, `runner tool
  missing:`), `env-network:<tool>`, `linter-unrunnable:<tool>`, `sandbox`, `timeout` and `other`.
- **`format:<tool>` or `lint:<tool>:<rule>`** — `format:<tool>` when belt 5 failed and every
  rejecting step is a formatter (`gofmt`, `ruff-format`, `prettier`, `spotless` or `cargo-fmt`).
  Otherwise `lint:<tool>:<rule>`, with rule ids parsed from the evidence pack's step tails, never
  from the messages. The rule is `*` when none parses.
- **`api:<added|removed|changed>`** — the kind only, from belt 6's findings (stream W). Never the
  unit or the symbol.
- **`builder_red:<sub>`** — the first of `tests_modified`, `no_source_change`, `regression` and
  `target_red` that the belts show.
- **`disqualified:<reason code>`**.
- **`review:<regression|defect|api_change|style>`** — from the standing review of a row. That is
  `latest_reviews`, which reads stream K's appended corrections as the standing verdict. A review
  with `mergeable=false` and no finding is `review:not_mergeable`.
- **`factory:<pr_closed|red_refused|delivery_refused>`** — from the factory's evidence chain.

An `outage` row observed nothing, so it is never a class.

A row may carry several signatures. It counts once per class, and its first signature is its primary
one.

Changing any rule in this list bumps `crb.prevention.sig.v1`, and a golden fixture fails if the
version is not bumped. Every decision taken under the old version then reads `rules changed —
re-baseline`.

### 3. The register is computed; the prevention chain is the only state

`crb.core.prevention.build_register(rows, reviews, factory_events, records, *, repo, mechanisms)` is
a pure function. The same input gives byte-identical output. It has no argument that can exclude a
row, a task or a class.

For each repository and class it serves:

- when the class was first and last seen;
- occurrences, and occurrences on first attempts;
- tasks, runs and spend;
- the evidence row hashes (the first 50, and the total);
- counts by mode and by apparatus;
- the recommended lever, with the levers it passed over and why;
- the change in force and its measurement;
- the status, and one plain sentence saying what happens next.

The loop's own acts are the only stored state. They are `PreventionRecord`s of seven kinds:
`switched`, `applied`, `decided`, `reverted`, `proposed`, `registered` and `linked`. Each record is:

- hash-chained (`prev_hash` → `row_hash`, the ledger's own discipline);
- attributable (`actor`, and `on_behalf_of` the person who threw the switch);
- stamped with the rule versions and the apparatus.

The server stores each record as one `learn.prevention.recorded` system event on the repository's
`learn:<repo>` trace:

- the `events` table's triggers make it append-only;
- the chain in the payload makes it tamper-evident;
- the database backup already covers it.

There is no new table and no migration. `JsonlPreventionStore` is the standard-library twin, used by
`crb learn prevention` on the command line.

### 4. One switch per repository, and the team's own configuration wins

`learning.auto_apply` is `off`, `context` or `config`. It is `off` by default until the Phase B
paired A/B shows a benefit.

Each throw of the switch is a `switched` record, written by `PUT /learn/switch?repo=`. Only an
operator may throw it, and a reason is required. The decider is the signed-in session, never a field
of the body. This keeps ADR-0017's lesson — every throw names a person — without a mutable field on
the repository row.

- **`off`** — the register and the recommendations are computed and shown, but nothing from the loop
  reaches a builder, and the loop writes nothing.
- **`context`** — the loop may apply playbook lines, and may propose items (a proposal changes
  nothing a builder sees, §5).
- **`config`** — the loop may also apply the switches in §1.

What the loop applies is an **overlay**, folded from the chain. The repository's own configuration
is never written.

The order of precedence is:

1. a run parameter;
2. the repository's own configuration;
3. the loop's overlay;
4. the default.

So a team that sets a key itself always wins, and the register shows the loop's change as
`overridden`.

Switching to `off` suspends every change from the next run. Nothing is lost, and switching back
resumes them.

A run may opt out (`POST /runs` with `learning: "off"`) but can never opt in. That is how the Phase
B campaign runs its off arm on the same repository.

### 5. Which lever: the strongest the class admits, construction first

`crb.core.prevention.choose_lever` walks the catalogue from strongest to weakest: construction,
gate, mistake-proofing, advisory. It skips a lever when:

- this build does not ship its mechanism;
- the mechanism is already on for the repository;
- the switch does not allow it;
- the team has set its key;
- the loop has retired it for this class under this apparatus;
- a person reverted it for this class.

It then applies four principles.

- **Dual track.** If the strongest lever the class admits is code, the loop proposes it at once,
  because a proposal changes nothing a builder sees. It then applies the best lever it is allowed to
  apply, as the interim.
- **Advisory last.** A playbook line is used only when no process lever is admissible or allowed.
  There is no template for `budget`, `builder_red:target_red`, `review:defect`, `review:regression`
  or `factory` classes. "Be quicker" and "be more careful" are the essay that measured worse than a
  checklist.
- **Deterministic first.** A lever whose effect the row itself records, such as the formatter step,
  may be applied from the first occurrence. Every other lever waits until the class is actionable
  (§6).
- **One at a time.** At most one change is under measurement for a class. One change may serve
  several classes, as the finish gate does, and each class is measured on its own.
- **Every ladder ends in a filed item.** A class that no specific code item admits — `lint`,
  `format`, `builder_red:no_source_change`, `disqualified`, `harness:other` and the like — gets the
  catalogue's last lever, `item:prevent-class` (a person builds the prevention the catalogue lacks),
  when nothing the loop may apply is left. Capability and factory classes are exempt: they are
  routed and strengthened, not prevented.

Filed items carry their evidence, the class, the lever, its level and the expected effect. From
today's data they include:

- a command the builder's deny rule already refused becomes a recorded refused call, not a voided
  attempt. This is construction, but it changes the failure rule, so it needs its own ADR and an
  apparatus bump;
- a provisioned sandbox answers `go mod tidy` and `pip install` without the network (construction);
- a builder near its budget runs the finish checks and stops with its best patch (construction);
- switch belt 6 on for a repository. That is a grader key, so it is a person's decision.

The brief also listed runner commands, the escalation rung and a qualification pre-check as
configuration levers. The loop throws none of them:

- a command string belongs to the repository's configuration, and stream W's finish gate carries it;
  a loop that composed one could compose a refused or scoped one;
- stream K makes its measured escalation rule the default for every repository;
- stream D's pre-check is always on.

They appear in the register as the mechanisms that contain a class. Containment never closes a
class.

### 6. Apply, measure, decide — `crb.prevention.rule.v1`

1. **The unit is a first attempt.** A first attempt is the rung-`r1` row of one run, task and mode,
   when the provider did not refuse the call. A retry exists only after a failure, and stream K's
   escalation rule now decides how many retries there are, so counting retries would let the loop
   credit its own lever for K's change. Harness and disqualified rows stay in `n`, so moving a
   failure from one kind to another can never shrink the denominator.
2. **Observable.** A class is counted only where its detector ran:
   - belt 5 for `lint` and `format`;
   - belt 6 for `api`;
   - a review for `review`;
   - an outcome for `factory`;
   - every attempt for the rest.

   Switching a detector on is never read as the class appearing.
3. **Actionable.** A class is actionable when it has at least 2 first-attempt occurrences on at
   least 2 tasks, in one comparable stratum with at least 10 first attempts. Below that, the class
   is `open · watch`.
4. **Stratum and comparability** are frozen when a change is applied.
   - The stratum is the repository and the mode with more occurrences; a tie goes to blind.
   - The comparability key is the apparatus major.minor, the builder family (the name before any
     `+`), the model and the signature-rule version.

   Rows outside the key are counted and shown, never pooled.
5. **Before.** The before window is the stratum's last 100 comparable first attempts before the
   change, or all of them if there are fewer. It is frozen in the `applied` record as `k0`, `n0` and
   a digest of their row hashes, so later rows can never move it. `p0 = k0 / n0`.
6. **Exposed.** Exposed attempts are the stratum's first attempts after the change whose own labels
   name it: `learn_changes`, or `learn_lines` for a line. A switch's row must also carry its
   mechanism's own label saying it ran (`budget_profile=calibrated`, `checks` with `fmt=1` or
   `gate=1`): a run whose own parameter overrode the switch — including a plain top-level
   `budget_profile` on `POST /runs` — was never exposed, and the snapshot does not name the change
   on its rows. A row that does not name the change is shown as unexposed and never counted. Rows
   from runs that opted out are shown beside it as the concurrent comparison. They are for reading,
   not for deciding — except as §6.10 says.
7. **Decisive n** is `ceil(ln 0.025 / ln(1 − p0))`, clamped to 10–200. It is the smallest `n` at
   which zero recurrences are significant at the level each look uses. The formatter step, whose
   effect the row records, needs 3.
8. **Two looks only.** The rule looks at exactly the first `decisive n` exposed attempts, and then
   at the first `2 × decisive n`.
   - **Keep** when the one-sided exact binomial `P(X ≤ k1 | n1, p0) ≤ 0.025`.
   - **Retire** at the second look when not kept.
   - **Harm: retire at once.** At the tenth exposed attempt or at either look, retire when `P(X ≥ k1
     | n1, p0) ≤ 0.01`, or when the Wilson-95 upper bound of the exposed clean rate is below the
     before clean rate.
9. **Retire, then escalate.** The loop appends `reverted`, with actor `loop` and the measurement as
   the reason. It never applies that lever to that class again under that apparatus. It then moves
   the class to its next admissible lever: from a line to a switch, or from a switch to the filed
   item. Escalation only climbs: once a switch has been retired for a class, no playbook line is
   applied to it — the class waits on the filed item (`escalated`). With no lever left, the class is
   `retired` and routing holds it.
10. **Closed.** A class is closed when all three of these hold:
    - its change was kept;
    - no occurrence has appeared in the last `max(20, decisive n)` exposed attempts, counting
      refusals before spend;
    - the stratum's non-clean rate is no more than 5 percentage points above the before window's
      **non-target** failure rate — its non-clean rate less the class's own share. Comparing with
      the whole non-clean rate would let the same attempts fail as another class at the same rate
      and still close the class.

    A class whose attempts now fail as another class stays `applied · displaced` and names its
    successor. It is never counted closed. Nor is a class kept or closed while it still recurs, at
    or above `p0`, on at least 10 comparable first attempts of tasks the change never reached (runs
    opted out, or a team override): running the loop only where the class does not live cannot close
    it. An honest A/B runs the same tasks in both arms, so its control arm never blocks.
11. **Reopened.** Any later exposed occurrence returns a closed class to `applied · reopened`. The
    loop names the row and proposes the next stronger lever.
12. **Inconclusive.** No verdict is given when the comparability key moves inside the window, or
    when the outage share of the stratum's rows more than doubles. A line is withdrawn, because
    context is not free. A switch stays, marked `unproven`.
13. **Capability classes are not decided by this rule.** These are `builder_red:target_red`,
    `review:defect` and `review:regression`. The finish gate that addresses them is judged by stream
    S's working changes per pound in the Phase B A/B. Routing holds them, and the loop never calls
    them closed.
14. **Nothing retroactive.** A class that went quiet with no change on record is `open · dormant`
    and is never credited — and the loop never applies a lever to it, not even a deterministic one
    that may otherwise act from the first occurrence. A code change made outside the loop is
    measured only when a person links it (`POST /learn/links`). Its exposure starts at the link
    record, never before.

Every `decided` record carries the counts, the bar, both p-values and the digest of the exposed rows
it read. `crb.core.prevention.verify_decisions` re-derives each decision from the ledger and refuses
a filtered ledger.

The served status is one of stream S's five: `open`, `applied`, `closed`, `retired` or `escalated`.
Qualifiers sit beside it: `watch`, `dormant`, `capability`, `contained`, `overridden`, `suspended`,
`displaced`, `reopened` and `unproven`. `escalated` means the class waits on a stronger lever the
loop cannot apply: a filed item, or a switch it is not allowed to throw.

### 7. No leakage, by construction

- **Narrow inputs.** `crb.core.playbook.compile_playbook(signals, facts)` accepts only:
  - class facts: the signature, the template id, the slot values, and the ids of the tasks and rows
    that taught it;
  - repository facts: the check commands stream W holds, and tool names.

  It cannot take a row, a pack, a diff, a review or an error text. A test pins that `playbook.py`
  imports nothing that holds one.
- **Closed templates.** Lines come only from a closed table of templates: a network refusal, a
  history refusal, format before finishing, a lint rule, keep the public API, and finish with a
  source change.
- **Checked slots.** Each slot is checked against a closed vocabulary, or the line is not written.
  Command heads come from a fixed allowlist, rule ids are checked by grammar, and commands come only
  from configuration.
- **Checked commands.** Every command a line recommends must be in the honest guard corpus, and the
  builder's own shell guard checks it again at injection.
- **Held out by task.** A line reaches a replay of task T only when at least two *other* tasks
  taught it.
- **A leak gate at injection.** The adapter drops any line that contains a token of four or more
  characters from T's target tests, test files or source files, and records the drop
  (`learn_dropped`).
- **A hard cap.** At most seven lines, 160 characters each and 1,000 in all, one per class. They are
  rendered as the checklist "Operating notes for this repository", after the harness line. They are
  recorded in the brief's `to_dict`, so the evidence pack says what the builder read.
- **Canary tests.** Tests plant canaries in the gold diff, the target tests, review statements, row
  errors and linter messages, and assert that none reaches a line or a brief.

### 8. What every row records

These are hashed labels, so the chain commits to what the builder was given:

- `learn` — the effective switch, after any opt-out;
- `learn_changes` — the ids of the changes in force, sorted; at most 8, otherwise the digest of the
  set;
- `learn_overlay` — the digest of the overlay;
- `learn_playbook` — the digest of the lines injected;
- `learn_lines` and `learn_dropped` — the ids of the lines injected and dropped.

Stream W's and stream K's labels (`format_step`, `finish_gate`, `budget_profile`, `escalation_rule`)
sit beside them.

A row without these labels was written before the loop and reads `learn: off`, which is true. So old
and new rows never mix silently.

The capability map does not split a cell by these labels, just as it does not for K's budget
profile. The labels make the split recoverable, and the Phase B analysis reads it split.

### 9. Filed items

A proposed item is a `proposed` record. It becomes a row in the Decisions inbox — "a prevention
needs an owner" — and shows on its Learn row.

Nothing is registered by itself, because a frozen backlog is what a factory run spends against
(`docs/LEARNING-LOOP.md` §3).

- **One operator act registers an item.** `POST /learn/items/{item_id}/register?repo=` registers a
  repository's item onto its factory backlog. It uses the register-or-evolve path that the freeze
  route and the intake listener already use:
  - the first item freezes a backlog, and later ones evolve it;
  - ids are `prevent-<sha12>`, with `-v<n>` supersession;
  - the call is refused with 409 while a run holds the backlog.

  An environment fix is registered as kind `infra`. A grader-key decision is registered as kind
  `operator`.
- **Product items stay off customer backlogs.** An item for this product's own code never goes on a
  customer's backlog. It is served for the maintainers, and an operator may link the issue that
  carries it.
- **No tickets.** The loop writes no ticket on any board. ADR-0017's six tracker verbs stay the
  limit.

### 10. Where it lives

- `src/crb/core/prevention.py` and `src/crb/core/playbook.py`, both standard library only
  (ADR-0008).
- `src/crb/server/prevention_state.py`: the events store, the per-run snapshot and the tick.
- `src/crb/server/routes/prevention.py`, which serves:
  - `GET /learn/register`
  - `PUT /learn/switch`
  - `POST /learn/tick`
  - `POST /learn/changes/{change_id}/revert`
  - `POST /learn/items/{item_id}/register`
  - `POST /learn/links`
- One card on the existing Learn page, and one derivation in the Decisions inbox. There is no new
  screen.

The worker takes a snapshot when a run starts and runs one tick when it ends. A tick that fails
never fails the run. The loop makes no model call.

## Consequences

### Easier

- **Every class has a record.** Every bug class has a row with its evidence, the lever chosen and
  why, and what would close it, whether or not the switch is on.
- **Learning becomes countable.** Stream S's recurrence curve reads this register. "The loop is
  learning" becomes a count of classes closed, and the share closed by process rather than by
  context.
- **Phase B needs nothing new.** The switch, the per-run opt-out and the labels give the campaign
  both arms.
- **A platform team stays in control.** It can hold the loop to one sentence (§1), stop it with one
  switch, and undo any change by name, with a reason.

### Harder

- **Small numbers.** At today's rates the bars are:
  - 22 blind first attempts for cobra's network refusals;
  - 12 for click's blind budget stops;
  - 78 for click's sighted lint rejections.

  [hypothesis — decisive n computed from the export's first-attempt rates under apparatus 2.2; the
  rates will move.] Many rows will read "needs N more" for a round or two. The page must say so,
  rather than imply progress.
- **Confounding.** Stream W's switches, stream K's budget profile and the loop's lines may land
  together. One change per class, and the list of changes in force, make this visible. Only the
  paired A/B removes it.
- **Detail depends on the store.** The export has no stop reason, error text or lint pack. A
  register built from it resolves budget, protocol and lint classes to family level only. The live
  store resolves them fully.
- **The review side is starved** until stream K keeps every patch. No cobra, click or koa review can
  anchor today.
- **Capability classes never close.** `builder_red` is the largest blind class on cobra and koa,
  with 15 and 13 blind rows [measured — n = 38 and 20 blind attempts; method: the product's failure
  rule over the export; apparatus 2.2]. Its only process lever is judged by value, not by
  recurrence.

### What we must never do

- Write a grader key, a guard-corpus line, the failure rule or a routing threshold.
- Credit a class that went quiet with no change on record.
- Count a class closed while it recurs as a refusal before spend, or while its failures have moved
  to another class.
- Put free text, a model's words, or anything from a task's gold diff, target tests or review notes
  into a brief.
- Register an item on a backlog, or write on a board, without a named person.
- Re-apply a lever that a person reverted.

### What the register would do today

The register over the operator's export is generated, not retyped here:
`scripts/prevention_from_export.py --md` prints the tables that [the value
baseline](../reviews/2026-09-25-value-baseline.md#todays-prevention-register--cobra-click-and-koa)
carries, class by class, with the lever and the filed item the loop would choose. An earlier draft
of this section kept its own hand-made table; it drifted from the generated one within the day
(docs/PREVENTION.md P-015), so the page is now the one place that quotes the register, and a test
holds every other page to that.

## Alternatives considered

- **Construction first, as proposed.** Its lever discipline is §5. It lost on three counts, each
  with a cost:
  - it kept its state on the system trace and called it hash-chained, which it is not (§3 adds the
    chain in the payload);
  - it registered filed items onto the customer's factory backlog by itself, spending against a
    backlog nobody froze (§9 keeps a person);
  - it wrote the repository's configuration directly, so a revert could put back a stale value over
    a person's later edit, and switching off could not suspend anything (§4 uses an overlay).
- **Evidence first, as proposed.** Its frozen before window, exposure by label, comparability key,
  bounded looks and inconclusive rule are §6. It lost on cost to the operator and to the signal:
  - its holdout withholds a possibly useful line from one attempt in four, where a stratum holds
    only 10 to 20;
  - paired sign tests, sequential checkpoints at z = 2.24 and more statuses than a platform team can
    read make it hard to use;
  - its new table needed a migration.
- **Operator first, as proposed.** Taken as the spine, with two corrections:
  - its "link a past fix" example measured rows under apparatus 2.0 against rows under 2.2, crossing
    the boundary its own rule forbids. §6.14 makes every link prospective;
  - it checked "keep" on every tick, which inflates false keeps. §6.8 allows two looks.
- **A dedicated table and migration for the chain.** It costs a migration head shared with two
  workflows in flight, and buys nothing that the `events` table with a payload chain does not.
- **A JSONL chain under `CRB_HOME`, like the factory's evidence.** The production shapes back up the
  database and treat the home volume as reproducible (`docs/DEPLOYMENT.md` §5). The record of what
  the loop did would be lost with the volume.
- **Bumping the apparatus when the class rule changes.** It would mark every sign-off stale and
  mislabel rows whose grading did not change (ADR-0015 §4, ADR-0016 §3). The signature-rule version
  in the comparability key breaks comparability just as openly.
- **Measuring every rung.** Retries follow a failure, and K's escalation rule now decides how many
  there are. A class's rate would fall because escalation stopped, and the loop would credit itself.
- **Letting the loop write runner commands, escalation or the pre-check.** A composed command can be
  refused or can scope the oracle. Escalation is K's default and the pre-check is D's, so a loop
  switch on either would only fight them.
- **A model to write lines or to read reviews.** It is non-deterministic, a path for leakage, an
  essay by default, and a paid call on every tick.
- **Closing on pass rate, or on stream S's curve alone.** A pass rate mixes classes, and a curve
  describes without a bar. Closure needs a before window, a bar and exposed attempts.
- **Crediting fixes after the fact, such as click's network refusals.** Back-dated credit across an
  apparatus boundary is the unfalsifiable claim that `docs/EVIDENCE-AND-CLAIMS.md` forbids.
- **Letting the loop accept guard-corpus lines.** It would launder a false positive into policy
  (`docs/LEARNING-LOOP.md` §3). The triage stays with a person.
