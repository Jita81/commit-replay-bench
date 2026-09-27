# The learning loop — what loops mechanically, what the product derives, what a human still does

*Answering the operator's question of 2026-09-14: "Is the self-learning loop working?"*

The honest answer was: **half of it**. The *measurement* half loops mechanically. The
*learning* half — a failure becoming a prevention artefact, a weak oracle becoming
test-strengthening work, an apparatus change triggering re-measurement — happened only
through people and agents reading the ledger. `crb.core.learn` (this document's subject)
makes the learning half product behaviour: three deterministic derivations from the ledger
as it is, each stopping exactly where a decision needs a name attached.

Contents: [1 What loops today](#1-what-loops-mechanically-today) ·
[2 What this module adds](#2-what-crbcorelearn-adds) · [3 What still needs a human, and why](#3-what-still-needs-a-human-and-why-that-is-deliberate) ·
[4 Using it](#4-using-it) · [5 Properties the tests pin](#5-properties-the-tests-pin) · [6 Not yet](#6-what-this-is-not-yet) ·
[7 Prevention](#7-prevention--a-bug-is-closed-by-a-change-that-stops-it-recurring)

---

## 1. What loops mechanically today

```
run ──▶ grade ──▶ ledger ──▶ capability map ──▶ route ──▶ (sign-off) ──▶ factory
 ▲        four belts   append-only,    per cell:       ONE rule       human        forward
 │        false-Q1=0   hash-chained    n, Wilson CI,   (ADR-0003)     attests      mode
 │        at write     (ADR-0002)      failure split,
 │                                     apparatus stamp
 └──────────────────── the operator queues the next run ───────────────────────────┘
```

Every arrow above is code, and every number carries its `n`, its interval and the
apparatus that produced it (`docs/EVIDENCE-AND-CLAIMS.md`). What the loop did **not** do
before this module — and what the critical-friend review of 2026-09-13 named — is *learn
from its own failures*:

| Review finding | Where the learning lived |
|---|---|
| §4.2 reading 2 / §5 play 04 — 13 of 15 non-clean rows were the instrument's doing; three guard false-positive classes were each "fixed reactively" after a build was lost; "read a sample of refusals weekly" | A person read the rows, wrote the corpus line by hand (A10's `tests/fixtures/shell_corpus*.txt`), and fixed the guard. On 2026-09-14 an NHS row (`.git` inside a quoted grep argument) went the same way: fixed by hand in `90bf171`, corpus line added by hand. |
| §4.2 reading 5 / §5 play 03 — strength ≥ 0.8 did not prevent a patch with two behavioural gaps; "a test engineer reviews the target tests once" | Nothing produced the work item. The routing rule withheld `deliver` (`oracle_weak`, `controls_escapes`, `controls_thin`) and stopped there. |
| §6 "evidence expires with the apparatus" / §8 action 10 — "run each repo to n ≥ 10 per cell with the fixed harness before quoting any rate" | The apparatus stamp made stale rows *visible* (`apparatus_versions` on every cell) but nobody computed what re-measurement would cost or which runs to queue. |

## 2. What `crb.core.learn` adds

Three pure functions over `GradeRow`s (stdlib only, ADR-0008), each with a CLI verb
(`crb learn …`), an optional read-only API route (`GET /learn/{refusals,strengthen,remeasure}`,
viewer role), and a byte-identity guarantee: same rows → same report.

### 2.1 Refusal triage — `triage_refusals(rows)` → `crb learn refusals`

Every row whose `failure_kind` is `protocol` carries the guard's own words in
`error` / `labels.builder_error`:

```
protocol violation: archaeology: '.git' is off limits (.git) (attempted: find . -iname "*conftest*" … | grep -v ".git"); network: 'curl' is not allowed (no network access) (attempted: curl -sk https://localhost:8701/health)
```

The triage parses each violation (reason prefix `archaeology:` / `network:` / `tamper:`, the
guard's sentence, the attempted command — tolerating the recorder's 120-character cap and
the ledger's field caps), normalises the command to its **shape** (paths → `<path>`, shas →
`<sha>`, quoted strings → `"<str>"`, numbers → `<n>`, URLs → `<url>`; flags, verbs, pipes,
redirections and `$(…)` substitutions kept, because they are what a guard decides on),
groups by (prefix, reason, shape), and reports per group: `n`, `$` and minutes lost, the
repos / tasks / row hashes, up to three raw examples, and a **candidate corpus line** in
exactly the format `tests/test_builders_guard_corpus.py` loads — one for the honest corpus
and one (`<command><TAB><prefix>:`) for the refused corpus.

The NHS row above becomes two groups:

| prefix | reason | shape | n | candidate |
|---|---|---|---|---|
| archaeology | `'.git' is off limits (.git)` | `find . -iname "<str>" -o -iname "<str>" \| grep -v "<str>"` | 1 | honest → `shell_corpus.txt` |
| network | `'curl' is not allowed (no network access)` | `curl -sk <url>` | 1 | refuse → `shell_corpus_refused.txt` |

**Every group's verdict is `unsure`.** The report cannot say `honest`; the dataclass refuses
to be constructed with any other verdict. A human writes a decisions file and runs
`crb learn refusals --apply decisions.json`; `apply_triage` validates every decision before
writing anything, then appends the accepted lines under a provenance comment:

```
# learned 2026-09-14 from nhs-api/3f9a1c2b7e row 699216b2ec56 (honest→paul) — .git inside a quoted argument
find . -iname "*conftest*" -o -iname "*helpers*" | grep -v ".git"
```

From that moment the guard corpus test fails on the false positive **before** the next
build is lost — which is the prevention artefact the review asked for, produced by the
product, accepted by a person.

### 2.2 Oracle-weak cells → work — `strengthening_backlog(map, scores)` → `crb learn strengthen`

For every cell the routing rule holds back because of the oracle (`reason_code` ∈
`oracle_weak`, `controls_escapes`, `controls_thin`), one item per weak scored task
(strength below `RoutingPolicy.min_oracle_strength`, unscoreable, or with escaped mutants),
in the factory's frozen-backlog item shape (`crb.factory.backlog.BacklogItem`):

```json
{
  "id": "strengthen-4b2f7c9e1d0a3b58",
  "title": "strengthen the target tests for click Fix pager on Windows",
  "kind": "code",
  "capability_class": "test.add",
  "description": "mutants that escaped: src/click/core.py:40 remove the elif; src/click/core.py:44 0 → 1. Cell bug.fix|S routes human (oracle_weak): oracle strength 0.33 for task click/aaaaaaaaaa vs threshold 0.80. …",
  "structural_facts": [
    "subject_under_test: src/click/core.py",
    "behaviour_asserted: the target tests fail on each escaped mutant: src/click/core.py:40 remove the elif; …"
  ],
  "labels": {"cell": "bug.fix|S", "reason_code": "oracle_weak", "oracle_strength": "0.33", "threshold": "0.80", "escaped": "2", "slots": "structural", "task_id": "…"}
}
```

Two deliberate choices. The class is `test.add`, whose catalogue slots are all
**structural** (`subject_under_test`, `behaviour_asserted`) and both are filled from facts
the ledger and the oracle run already hold — never a value from the answer — so the
Definition-of-Ready gate (`crb.factory.readiness.assess`) says `build` without a human
supplying anything (the review's play-01 finding: structure helps, values leak). And the
escaped mutants are listed *when the oracle run recorded them* (`CommitOracleScore.outcomes`
or the report's `escaped_mutants`); otherwise the item carries the count and says so. A held
cell with no per-task score gets one cell-level item, so a flag is never dropped silently.

Item ids are `sha(cell, repo, task)` — a re-run produces the same backlog; `--since <apparatus>`
keeps only cells and scores stamped at or after that version. `--out backlog.json` writes an
**unfrozen** `Backlog`; freezing it is the human's act (§3).

### 2.3 Apparatus change → re-measurement plan — `remeasure_plan(rows, current)` → `crb learn remeasure`

Per full cell (the unit a run targets): the rows stamped with an apparatus older than the
current one, how many eligible current-apparatus rows exist, `n_needed = min_n − n_current`
(from `routing.DEFAULT_POLICY`), the estimated cost (that cell's own mean row cost × n
needed, with `cost_known` false when no row recorded one) and minutes, and the exact
`POST /runs` bodies (`crb.server.schemas.RunCreateRequest`) an operator can queue:

```json
{"repo": "cobra", "kind": "replay", "mode": "sighted", "builder": "claude_code",
 "model": "claude-sonnet-5", "provider": "anthropic",
 "task_ids": ["1995054b00…", "…"], "limit": 7}
```

`task_ids` re-measures the *same* tasks the stale rows were graded on; when they are fewer
than the rule needs, a second request asks for the remainder by `limit` and says so. The
plan queues nothing — `crb learn remeasure` prints JSON; the operator posts it.

## 3. What still needs a human, and why that is deliberate

| Step | Who | Why the product must not do it |
|---|---|---|
| Accepting a corpus line (`honest` / `refuse`) | a named person, in a decisions file | A loop that appended its own refusals to its own guard corpus would launder a false positive into policy the moment it happened: the guard refused `curl -sk https://localhost:8701/health` **correctly** (a builder probing the sandbox) and `find … \| grep -v ".git"` **wrongly**, and nothing in the row distinguishes them. The review's play-04 asks for "a sample of refusals read by a person weekly"; `apply_triage` is that reading, with provenance. The report never carries a verdict other than `unsure`, by construction. |
| Pulling a strengthening item into a sprint (freezing the backlog) | the repo's test owner | The item says *which* mutants escaped; only a person can say whether the target tests should encode that behaviour or whether the mutant is equivalent (review §4.2.5: text-level mutators produce uncompilable and equivalent mutants). A product that froze and built its own strengthening items would spend a builder editing the oracle — the one thing belt 1 exists to prevent — on nobody's authority. |
| Queuing the re-measurement | the operator | Money and credits. The plan is honest about cost (`cost_known`) precisely so that the person who pays can decide; enterprise-grade autonomy still gates spend. |

None of these is a gap the product will later close. They are the three places the review
put a human on purpose (§7 items 4–6), and this module's job is to hand each of them a
finished, reproducible artefact instead of a ledger to read.

## 4. Using it

```bash
crb learn refusals                              # the triage, text
crb learn refusals --json --out refusals.json   # the same, machine-readable
# … a human writes decisions.json:
#   {"decided_by": "paul", "decisions": [
#      {"group_id": "…", "verdict": "honest", "note": ".git inside a quoted argument"},
#      {"group_id": "…", "verdict": "refuse", "note": "probing the sandbox on localhost"},
#      {"group_id": "…", "verdict": "unsure"}]}
crb learn refusals --apply decisions.json --corpus-dir tests/fixtures
pytest tests/test_builders_guard_corpus.py -q   # the new line binds (or fails: fix the guard)

crb learn strengthen --oracle oracle-report.json --repo click --out strengthen.json
crb learn strengthen --since 2.1 --by class_size --json

crb learn remeasure                             # against the running APPARATUS_VERSION
crb learn remeasure --apparatus 2.2 --json      # what a bump would cost before making it
```

All three read the ledger the way `crb route` does: `--path <ledger.jsonl>` or
`<workdir>/ledger.jsonl` (`--workdir` / `$CRB_HOME`). `--policy-json` overrides the routing
policy the derivations key on. The API mirrors the reports for the UI:
`GET /api/v1/learn/refusals?repo=…`, `/learn/strengthen?repo=…`, `/learn/remeasure?repo=…`
(viewer role; the store's rows, the latest oracle scores and controls verdict). The
refusals report serves its instrument-caused share as a rate with its context — `share:
{rows_total, rows_protocol, share, ci_low, ci_high}` (Wilson 95 %) and `by_apparatus:
[{apparatus_version, …the same}]` — so a UI never blends the share across apparatus
versions or shows it without an interval; `protocol_share` stays for the CLI's one-line
summary.

## 5. Properties the tests pin (`tests/test_learn.py`, `tests/test_cli_learn.py`)

* **The exact strings from tonight's rows parse**: `pip install`, `$(pwd)` (cut at the
  recorder's cap and flagged `truncated`), quoted parentheses in a grep pattern, `git stash`,
  `npx jest`, `npx prettier`, `uv run`, the NHS two-violation row, a reviewer's free-text
  violation with no command.
* **Determinism**: same rows in any order → byte-identical JSON for all three reports; item
  ids independent of the `registered` stamp; the CLI writes identical files twice.
* **Never auto-accept**: every group is `unsure`; a `RefusalGroup` with another verdict
  cannot be constructed; `apply_triage` needs `decided_by`, validates every decision before
  writing, refuses a truncated candidate without a human-supplied full command, refuses to
  file a `tamper:` as a shell-corpus refusal (that is belt 1's), and is idempotent.
* **The items pass the factory's gate**: every strengthening item round-trips through
  `BacklogItem.from_dict` and `readiness.assess` as `ready` / `build` with no value gaps, and
  the `--out` file loads and freezes as a `Backlog` whose hash verifies.
* **The run requests are valid**: every body validates as `RunCreateRequest`.

## 6. What this is not (yet)

* It does not fix the guard. A `honest` decision makes the guard corpus test fail on the
  false positive; the fix is still a code change (`crb.builders.base`), reviewed as one.
* It does not label refusals *instrument* vs *builder* on its own — that is what the human
  verdict is. Once decisions accumulate, the share of `honest` decisions per reason is the
  guard's measured false-positive rate; reporting it over time is a follow-up.
* Strengthening items are proposals for the **target tests of an existing task**; they do
  not propose new oracle coverage for classes that have no tasks.
* The re-measurement plan estimates cost from the cell's own history; a cell whose rows
  recorded no cost says `cost_known: false` rather than guessing.

## 7. Prevention — a bug is closed by a change that stops it recurring

*The operator, 2026-09-25: "We should be learning from a bug and then going back to update
our process or context to remove it moving forward."* The three reports above stop where a
person decides. The prevention loop (`crb.core.prevention`, ADR-0020) goes one step further
for the failures a builder makes: it names each failure class, gives it the strongest change
the class admits, and keeps, retires or escalates that change by what the next attempts show.
It acts only under a switch an operator throws.

### 7.1 The one rule

The loop changes how a change is made, never how it is judged. It may switch on three process
mechanisms and add checklist lines to the brief, and nothing else:

| lever | what it does | level |
|---|---|---|
| `checks.format_step` | the repository's own formatter runs over the changed files before grading | construction |
| `checks.finish_gate` | the builder gets the repository's own checks as a checklist, and `done` needs them to pass | gate |
| `spend.budget_profile: calibrated` | the caps come from the cell's clean completions | mistake-proofing |
| a playbook line | one operating fact, from a closed template | advisory |

It never writes a belt or its switch (`checks.api_stable` included), the lint plan, a runner,
the guards or their corpus, the oracle, a routing threshold or the failure rule —
`check_writable` refuses each by name — and it never switches anything off. A fix that needs
one of those keys, or needs code, becomes a *filed item* for a person. All three mechanisms
ship (streams W and K); none is on by default, so a repository runs under one only when an
operator sets it or the loop applies it with the switch at `config`. The loop applies the
calibrated budget only where K's rule can set it — a cell with at least 8 clean completions —
and otherwise passes it over as "cannot calibrate" and files the budget hand-off instead.

### 7.2 The switch

One switch per repository, `learning.auto_apply`, thrown only by an operator with a reason
(`PUT /learn/switch`); the record names the person.

| setting | what the loop may do |
|---|---|
| `off` (the default) | compute and show the register and its recommendations; nothing reaches a builder, nothing is written |
| `context` | apply playbook lines, and file items |
| `config` | also throw the three process switches |

The team's own configuration always wins: a key the repository sets itself, or a run sets,
outranks the loop's overlay, and the register shows the loop's change as `overridden`. A run
can opt out (`POST /runs` with `learning: "off"`) but never opt in. Switching to `off`
suspends every change from the next run; switching back resumes them.

### 7.3 What a class is

A class is a signature computed from the row the same way every time
(`crb.prevention.sig.v1`): `protocol:network:go mod` (the guard and the refused command's
first words, never its arguments), `budget:max_turns`, `harness:runner-tool-missing:jest`,
`format:gofmt`, `lint:ruff:e501` (the rule id from the linter's own output, never its
message), `api:changed`, `builder_red:target_red`, `review:style`, `factory:pr_closed`. A
provider refusal (`outage`) observed nothing, so it is never a class.

### 7.4 Reading the register

The Learn page's first card, `GET /learn/register` and `crb learn prevention` show the same
register:

| column | what it says |
|---|---|
| Class | the signature and its family |
| Seen | first attempts that showed the class, over the comparable first attempts of its stratum (the repository and the mode where it occurs most), with tasks and dollars |
| Lever | the strongest change the class admits that the loop may apply, and its level; every lever it passed over is listed with the reason |
| Applied | when the change in force was applied, and on whose behalf |
| Before → after | recurrence in the frozen before window and on the exposed first attempts since, each with its n, and the bar |
| Status | `open`, `applied`, `closed`, `retired` or `escalated`, with qualifiers such as `watch` (too few yet), `dormant` (quiet with no change — never credited), `capability` (judged by value, never closed), `suspended` (the switch forbids it now) |
| Next | one sentence: how many more attempts a decision needs, or what a person must do |

### 7.5 The three numbers

* **Decisive n** — `ceil(ln 0.025 ÷ ln(1 − p0))`, clamped to 10–200, where `p0` is the
  class's rate in the before window (its stratum's last 100 comparable first attempts,
  frozen when the change is applied). It is the smallest n at which zero recurrences is
  significant. For 9 refusals in 30 first attempts, `p0` is 0.30 and n is 11. The formatter
  step, whose effect the row itself records, needs 3.
* **The keep test** — at exactly two looks, the first n and the first 2n exposed first
  attempts (those whose own labels name the change): keep when `P(X ≤ k | n, p0) ≤ 0.025`;
  at the second look, retire when it did not keep. At the tenth exposed attempt and at each
  look, retire at once when `P(X ≥ k | n, p0) ≤ 0.01` or the exposed clean rate's Wilson-95
  upper bound falls below the before clean rate. A retired line escalates to a switch, a
  retired switch to the filed item.
* **The closed window** — a kept change closes its class after `max(20, n)` exposed first
  attempts with no recurrence (a refusal before spend counts), provided the stratum's
  non-clean rate is no more than 5 points above the before window; otherwise the class reads
  `displaced` and names what it now fails as. Any later recurrence reopens it.

Only first attempts count: a retry exists only after a failure, and stream K's escalation rule
decides how many there are. Harness and disqualified rows stay in n, so moving a failure into
another kind can never shrink the denominator.

### 7.6 Where the register stands today

Nothing has been applied, so nothing is closed. Over the operator's export of 2026-09-25, at
the export's family-level resolution, the register for the three Phase B repositories reads
as below [measured — n = the comparable first attempts of each class's stratum, shown as
k of n; method: `scripts/prevention_from_export.py` over the 618-row export, the product's
failure rule, first attempts only, outage rows excluded; apparatus 2.2]. The levers are what
the loop would choose with the mechanisms this build ships and the switch at `config`; the
switch is off on every repository, so none is applied yet.

| repository | class | first attempts | decisive n | what the loop would do |
|---|---|---|---|---|
| cobra | `protocol:network`, blind | 3 of 19 | 22 | file the refused-call item; apply the finish gate (mistake-proofing) |
| cobra | `builder_red:target_red`, blind | 6 of 19 | 10 | the finish gate, judged by value in the paired campaign: a capability class, held by routing |
| cobra | `harness:no-credential`, sighted | 9 of 80 | 31 | file the credential link (stream D's submit-time refusal, measured from its link) |
| cobra | `budget`, sighted | 4 of 80 | — | dormant: quiet in the last 20 sighted first attempts, never credited |
| click | `budget`, sighted | 7 of 43 | 21 | file the budget hand-off; the calibrated budget is passed over — the sighted L cell has 7 clean completions, one short of 8 |
| click | `lint`, sighted | 2 of 39 | 71 | apply the finish gate (gate) |
| click | `builder_red:target_red`, blind | 3 of 11 | 12 | a capability class, held by routing |
| koa | `builder_red:target_red`, blind | 4 of 10 | 10 | a capability class, held by routing |
| koa | `budget`, sighted | 3 of 29 | 34 | file the budget hand-off; apply the calibrated budget (mistake-proofing) |

The largest blind class by first attempts is the red target on cobra and koa and the network
refusal on click; counted over every rung, click's is the budget stop [measured — n = 22, 17
and 13 blind first attempts; method: the same script; apparatus 2.0–2.2].

### 7.7 What the loop will never do

* write a grader key, a guard-corpus line, the failure rule or a routing threshold;
* credit a class that went quiet with no change on record;
* count a class closed while it recurs as a refusal before spend, or while its failures have
  moved to another class;
* put free text, a model's words, or anything from a task's gold diff, target tests or
  review notes into a brief — lines come from closed templates, reach a task only when two
  other tasks taught them, and are dropped at injection if a slot shares a word with the
  task's test or source file names;
* register an item on a backlog, or write on a board, without a named person;
* re-apply a lever a person reverted.

