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
[4 Using it](#4-using-it) · [5 Properties the tests pin](#5-properties-the-tests-pin) · [6 Not yet](#6-what-this-is-not-yet)

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
