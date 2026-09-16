# Reproducing the census-ledger invariants

*For a reviewer with a fresh clone and thirty minutes.* This walks you through re-deriving
every claim `crb` makes **about the census ledger itself** — the 1,071 verdicts vendored in
`data/census-2026-07-08/` — using only the checked-in data and the current code. Every
command below was run as written; the output blocks are pasted, not typed.

**What this reproduces:** that the vendored files are the ones we say they are (hash
manifest); that every census verdict imports into the v2 ledger without the ledger inventing
anything; that the hash chain verifies; that **false-Q1 (mechanical) = 0** — no row is
credited `clean` while a belt it recorded says otherwise; and what the routing rule and the
capability map say about those rows under apparatus `1.0-census`.

**What this does NOT reproduce:** the builder runs. The 1,071 verdicts are 863 distinct
(repository, task) pairs — `[measured]` from `grades.jsonl`; 22 of the 24 configured public
repositories have verdicts — run through Claude Code (Sonnet) in July 2026, on Claude Code
credits, with the untracked `bench.py` grader (apparatus `1.0-census`). Nothing here re-runs
a model, re-executes a repository's tests, or re-grades a patch. You are checking the
**ledger's internal consistency** and the **grader's re-derivation** from the recorded
belts — not the belts' truth. §7 says exactly what that licenses.

Contents: [0 Prerequisites](#0-prerequisites) · [1 Manifest](#1-verify-the-manifest) ·
[2 Import](#2-import-the-census-into-a-temporary-crb_home) · [3 Chain](#3-verify-the-hash-chain) ·
[4 False-Q1](#4-re-derive-false-q1--0) · [5 Cells](#5-cells-routing-and-the-capability-map) ·
[6 Expected numbers](#6-the-expected-numbers-and-what-ci-asserts) · [7 What you may claim](#7-what-you-may-claim-after-running-this) ·
[8 Tamper checks](#8-optional-tamper-checks) · [9 Known limits](#9-known-limits-and-findings)

---

## 0. Prerequisites

* A fresh clone of `Jita81/commit-replay-bench` at `reboot/v2` (or the tag you are reviewing).
* Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/). No Docker, no model, no network after
  the install.
* `CRB_HOME` and `CRB_DATABASE_URL` **unset** in your shell. Everything below writes into a
  throwaway directory; nothing touches a running stack.

```bash
env | grep -E '^CRB_' && echo "unset these first" || echo "clean environment"
uv venv -q .venv --python 3.12 && uv pip install -q -e '.[dev]' --python .venv/bin/python
export CRB_HOME="$(mktemp -d)/home"      # a temporary workdir; delete it afterwards
D=data/census-2026-07-08
```

`crb.core` is standard-library only, so the import, the chain and the statistics run with
no third-party package in the loop; the `dev` extra is only pytest and the linters for §6.

## 1. Verify the manifest

`MANIFEST.sha256` lists every vendored file. If this fails, stop: you are not looking at the
evidence the documentation describes.

```bash
( cd "$D" && shasum -a 256 -c MANIFEST.sha256 )
```

Output tail (31 files; `grep -c ': OK'` → `31`, exit code `0`):

```
./tasks/pytest_tasks.json: OK
./tasks/sqlalchemy_tasks.json: OK
./tasks/starlette_tasks.json: OK
./tasks/werkzeug_tasks.json: OK
./tasks/zap_tasks.json: OK
```

## 2. Import the census into a temporary `CRB_HOME`

The verb is `crb ledger import-census`. It reads the 24 repo configurations, the 25 task
files and `grades.jsonl`, and appends one `GradeRow` per verdict to `$CRB_HOME/ledger.jsonl`
together with an *imported* evidence pack per row (the raw census line, hashed) so that "no
pack ⇒ no Q1" holds even for history. A belt the census did not record stays `None`; it is
never defaulted — that is the entire point of the `v3-legacy` belt set.

```bash
.venv/bin/crb ledger import-census --grades "$D/grades.jsonl" --tasks-dir "$D/tasks" --configs "$D/configs.json"
```

```
census import -> /…/home/ledger.jsonl
  configs 24, tasks 2097, grades read 1071: imported 1071, already present 0, skipped 0
  belt sets {'v3-legacy': 706, 'v4': 365}; modes {'sighted': 927, 'blind': 144}; packs written 1071
  ledger rows 1071, chain verified 1071, false-Q1 0
```

The import is deterministic (fixed import timestamp, content-derived ids), so running it
again changes nothing — every row is recognised by its evidence-pack hash:

```
  configs 0, tasks 0, grades read 1071: imported 0, already present 1071, skipped 0
  belt sets {}; modes {}; packs written 0
  ledger rows 1071, chain verified 1071, false-Q1 0
```

`skipped 0` matters: a verdict whose task record is missing would be skipped with a
`legacy.skip` event rather than imported with guessed class/size. None was.

**`banked_grades.jsonl` is deliberately not imported.** Its 232 rows come from the earlier
paired-factorial campaigns and record *fewer* belts than the census grader: 121 rows carry
only `target_green`, 108 carry `target_green` + `tests_unmodified`, 3 carry none; belt 3
(`no_new_failures`) exists only as a `new_failures` list whose emptiness may mean "none
found" or "not run". Feeding the file to the importer stops at its first clean row:

```
crb: error: FalseQ1Violation: ledger refuses clean row fbb02d9be7 (drf): belts={'tests_unmodified': True, 'target_green': True, 'no_new_failures': None}
```

That refusal is the write-time invariant doing its job (a clean row must have every belt it
claims recorded as `True`); deriving belt 3 from an empty list would be inventing evidence.
The file is vendored and hashed for provenance only, and **no number in this repository is
derived from it**. See §9 for the one wrinkle this leaves.

## 3. Verify the hash chain

```bash
.venv/bin/crb ledger verify            # add --json for the machine-readable form
```

```
/…/home/ledger.jsonl: 1071 rows, chain OK, false-Q1 0, clean-without-pack 0, apparatus ['1.0-census']
```

With `--json` (whitespace condensed here; the tool pretty-prints one key per line):

```json
{
  "apparatus_versions": ["1.0-census"],
  "belt_sets": {"v3-legacy": 706, "v4": 365},
  "chain_ok": true,
  "clean_without_pack": 0,
  "false_q1": 0,
  "ledger": "/…/home/ledger.jsonl",
  "ok": true,
  "rows": 1071
}
```

`verify` walks `prev_hash → row_hash` from the genesis hash to the last row **and**
re-counts false-Q1 from the belts (not from the `clean` flag). Exit code `0` only when the
chain holds, `false_q1 == 0` and no clean row lacks a pack. On a running stack the same
check is `GET /api/v1/ledger/verify`, and `/api/v1/health` reports the `ledger` probe as
`down` (HTTP 503) the moment either count is non-zero.

## 4. Re-derive false-Q1 = 0

### 4.1 The CLI form

`false_q1_total` in `crb.core.ledger` is what §3 already printed: for every row with
`clean == True`, every belt **that row recorded** must be `True`. Three belts for
`v3-legacy` rows, four for `v4`. The same function feeds `crb ledger stats`, `crb route`,
the capability map, the sign-off ledger (which returns 409 on a non-zero count) and the
health probe.

### 4.2 The SQL form (the critical-friend review's Appendix A, applied to the census)

The review's appendix gives a query "against the belts, not the flag" for a **2.0** stack
where every row carries four belts:

```sql
select count(*) from grades
 where clean = 1
   and (tests_unmodified is not 1 or target_green is not 1
        or no_new_failures is not 1 or source_changed is not 1);
```

Run verbatim on the census it returns **682, not 0** — and understanding why is the
legacy-belt caveat in one number. To run it you need the rows in a table; this loads the
exported ledger into a throwaway SQLite file with the standard library only:

```bash
.venv/bin/crb ledger export --out "$CRB_HOME/census-export.jsonl"
.venv/bin/python - <<'EOF'
import json, os, sqlite3
home = os.environ["CRB_HOME"]
cols = ("row_id","repo","task_id","clean","tests_unmodified","target_green","no_new_failures",
        "source_changed","belt_set","mode","process_step","error","disqualified",
        "apparatus_version","capability_class","size","language")
db = sqlite3.connect(f"{home}/census.db")
db.execute("create table grades (%s)" % ", ".join(cols))
for line in open(f"{home}/census-export.jsonl"):
    if line.strip():
        d = json.loads(line)
        db.execute("insert into grades values (%s)" % ",".join("?" * len(cols)), [d.get(c) for c in cols])
db.commit(); print("loaded", db.execute("select count(*) from grades").fetchone()[0], "rows")
EOF
```

Then, with `sqlite3 "$CRB_HOME/census.db"` (or `python3 -c 'import sqlite3, …'` if the
`sqlite3` binary is not installed — the module is in the standard library):

| Query | Result |
|---|---|
| (a) the appendix query verbatim (four belts) | **682** |
| (a′) the same, restricted to `belt_set = 'v4'` (rows that recorded belt 4) | **0** |
| (b) the product's predicate: `… or (belt_set <> 'v3-legacy' and source_changed is not 1)` | **0** |

```
sqlite> select belt_set, count(*) rows, sum(clean) clean, sum(source_changed is null) belt4_unrecorded, sum(source_changed=0) belt4_false from grades group by 1;
belt_set   rows  clean  belt4_unrecorded  belt4_false
---------  ----  -----  ----------------  -----------
v3-legacy  706   682    706
v4         365   280    0                 41
```

682 is exactly the number of clean three-belt rows. Their `source_changed` is `NULL` —
*never measured* — and in SQL `NULL is not 1` is true, so the four-belt query counts
"unrecorded" as "failed". Query (b) is `FALSE_Q1_PREDICATE` in `crb.server.routes.signoffs`
and the `ledger` health probe: it applies belt 4 only to rows whose belt set recorded it.
Query (a′) is the same statement from the other side: among the 365 rows that *did* record
belt 4, no clean row has it false (41 non-clean rows do — belt 4 was doing work).

So the sentence the census licenses is precisely EVIDENCE-AND-CLAIMS §2(a): **"0 recorded
`clean` rows violate their recorded acceptance predicates."** It says nothing about belt 4
on the 706 legacy rows, which is unmeasured for them — not passed, not failed.

The appendix's second query, the failure split, on the census:

```
sqlite> select belt_set, mode, count(*) n, sum(clean) clean, sum(error<>'') error, sum(error='' and clean=0) red, sum(disqualified) dq from grades where process_step='replay' group by 1,2;
belt_set   mode     n    clean  error  red  dq
---------  -------  ---  -----  -----  ---  --
v3-legacy  sighted  706  682    12     12   1
v4         blind    144  114    0      30   0
v4         sighted  221  166    0      55   7
```

`error` rows are harness failures recorded as not-clean with their reason (the census kept
them: EVIDENCE-AND-CLAIMS §8, principle 3); `red` is the model failing the task; `dq` rows
are disqualified and excluded from the eligible `n` below.

## 5. Cells, routing and the capability map

### 5.1 Statistics by apparatus, belt set and mode

```bash
.venv/bin/crb ledger stats --by apparatus,belt_set,mode
```

```
apparatus_version  belt_set   mode     n    clean  point  ci_low  ci_high  dq  err  fq1  belts      apparatus
-----------------  ---------  -------  ---  -----  -----  ------  -------  --  ---  ---  ---------  ----------
1.0-census         v3-legacy  sighted  705  682    0.967  0.952   0.978    1   12   0    v3-legacy  1.0-census
1.0-census         v4         blind    144  114    0.792  0.718   0.850    0   0    0    v4         1.0-census
1.0-census         v4         sighted  214  166    0.776  0.715   0.826    7   0    0    v4         1.0-census

1071 rows in /…/home/ledger.jsonl; false-Q1 total 0; point = clean/n over eligible trials; CI = Wilson 95%
```

`n` is eligible trials (not disqualified, `gold_clean` not `False`), which is why the
legacy row shows 705 of 706 and the v4 sighted row 214 of 221. The three rows reconcile to
the CI gate's totals: clean 682 + 114 + 166 = **962**; dq 1 + 7 = **8**; errors **12**.

The `belts` and `apparatus` columns are there so a reader sees instrument mixing. Here the
apparatus is uniform (`1.0-census`) and the belt sets are split by grouping; a grouping that
omits `belt_set` shows `v3-legacy+v4` in the `belts` column of every mixed cell. The product
never blends this into one number silently. For example, the (`bug.fix`, `XS`) cell of §5.3
split by mode:

```
$ .venv/bin/crb ledger stats --by class,size,mode | grep -E '^bug.fix +XS'
bug.fix            XS    blind    60   51     0.850  0.739   0.919    0   0    0    v4            1.0-census
bug.fix            XS    sighted  336  323    0.961  0.935   0.977    3   3    0    v3-legacy+v4  1.0-census
```

### 5.2 The routing rule

```bash
.venv/bin/crb route         # the one published rule, routing.v1 (ADR-0003)
```

Output tail (the full table is 33 cells keyed by class × size × language × builder × model):

```
bug.fix            XS    python      claude-code-workflow  sonnet  172  0.977  0.942   0    deliver      n=172 point=0.977 ci_low=0.942 false_q1=0
bug.fix            XS    rust        claude-code-workflow  sonnet  18   0.889  0.672   0    calibrate    point 0.889 < 0.90
test.add           S     go          claude-code-workflow  sonnet  1    1.000  0.207   0    calibrate    n=1 < 10
test.add           S     python      claude-code-workflow  sonnet  2    1.000  0.342   0    calibrate    n=2 < 10

33 cell(s) from 1071 rows; policy routing.v1 (n≥10, point≥0.9, Wilson-low≥0.8, oracle≥0.8 when measured); summary {'calibrate': 20, 'deliver': 8, 'granularize': 5}
```

Read `deliver` as EVIDENCE-AND-CLAIMS §6 defines it: *"high-confidence candidate under the
published bar"* for a sighted, retrospective corpus under apparatus `1.0-census` — not
"autonomous delivery is safe", and not a statement about apparatus `2.0`, whose ledger
starts empty.

### 5.3 The capability map (apparatus `1.0-census`)

There is no `crb capability` verb: the map is `crb.core.capability.build_capability_map`,
served by `GET /api/v1/capability-map?repo=<name>&by=class,size` on a stack and used
directly by the CI gate. The same call from the CLI environment, under the gate's
projection:

```bash
.venv/bin/python - <<'EOF'
import os
from pathlib import Path
from crb.core.ledger import JsonlLedger
from crb.core.capability import PROJECTION_CLASS_SIZE, build_capability_map, render_markdown
rows = list(JsonlLedger(Path(os.environ["CRB_HOME"]) / "ledger.jsonl").rows())
print(render_markdown(build_capability_map(rows, projection=PROJECTION_CLASS_SIZE)))
EOF
```

> **The legacy-belt caveat, stated as EVIDENCE-AND-CLAIMS §5 states it:** *"The census ledger
> that seeds this product (`grades.jsonl`, **1,071 rows**) was produced by the upstream
> apparatus. **706 of the 1,071 rows were graded under three belts before belt 4
> (`source_changed`) existed; 365 carry all four.** `[measured]` from the file itself: the
> `source_changed` key is present on 365 rows and absent on 706."* — and: *"**No claim blends
> apparatus versions.** 'Under apparatus 1.0-census, cell X was …' and 'under apparatus 2.0,
> cell X is …' are two statements."*

```
# Capability map — capability_class x size

rows=1071 · false-Q1=0 · policy=routing.v1 · apparatus=1.0-census

| capability_class | size | n | clean | point | 95% CI | sigma | false-Q1 | tier | route | why |
|---|---|---|---|---|---|---|---|---|---|---|
| `backend.route.add` | `L` | 1 | 1 | 100.0% | [0.21, 1.00] | 0.00 | 0 | automated-pass | **calibrate** | n=1 < 10 |
| `backend.route.add` | `M` | 6 | 4 | 66.7% | [0.30, 0.90] | 0.52 | 0 | automated-pass | **calibrate** | n=6 < 10 |
| `backend.route.add` | `S` | 4 | 4 | 100.0% | [0.51, 1.00] | 0.00 | 0 | automated-pass | **calibrate** | n=4 < 10 |
| `backend.route.add` | `XS` | 4 | 4 | 100.0% | [0.51, 1.00] | 0.00 | 0 | automated-pass | **calibrate** | n=4 < 10 |
| `bug.fix` | `L` | 55 | 45 | 81.8% | [0.70, 0.90] | 0.39 | 0 | automated-pass | **calibrate** | point 0.818 < 0.90 |
| `bug.fix` | `M` | 186 | 154 | 82.8% | [0.77, 0.88] | 0.38 | 0 | automated-pass | **calibrate** | point 0.828 < 0.90 |
| `bug.fix` | `S` | 391 | 363 | 92.8% | [0.90, 0.95] | 0.26 | 0 | automated-pass | **deliver** | n=391 point=0.928 ci_low=0.898 false_q1=0 |
| `bug.fix` | `XL` | 17 | 10 | 58.8% | [0.36, 0.78] | 0.51 | 0 | automated-pass | **granularize** | size XL is split before attempting |
| `bug.fix` | `XS` | 396 | 374 | 94.4% | [0.92, 0.96] | 0.23 | 0 | automated-pass | **deliver** | n=396 point=0.944 ci_low=0.917 false_q1=0 |
| `test.add` | `S` | 3 | 3 | 100.0% | [0.44, 1.00] | 0.00 | 0 | automated-pass | **calibrate** | n=3 < 10 |
```

Two things to read off this table before quoting it. First, every cell in it mixes
`v3-legacy` and `v4` rows AND sighted and blind rows (only §5.1's grouping separates
them), so each is a statement about three belts on most of its rows and about two
different measurements of the same task. The two `deliver` cells, split the way a claim
must be quoted (mode × belt set; Wilson 95%; `crb ledger stats --by
class,size,mode,belt_set`; DQ rows excluded):

| cell | mode | belt set | n | clean | rate | Wilson 95% |
|---|---|---|---|---|---|---|
| `bug.fix` XS | sighted | `v3-legacy` | 281 | 274 | 97.5% | [0.95, 0.99] |
| `bug.fix` XS | sighted | `v4` | 55 | 49 | 89.1% | [0.78, 0.95] |
| `bug.fix` XS | blind | `v4` | 60 | 51 | 85.0% | [0.74, 0.92] |
| `bug.fix` S | sighted | `v3-legacy` | 277 | 265 | 95.7% | [0.93, 0.98] |
| `bug.fix` S | sighted | `v4` | 51 | 45 | 88.2% | [0.77, 0.94] |
| `bug.fix` S | blind | `v4` | 63 | 53 | 84.1% | [0.73, 0.91] |

The blended 94.4% / 92.8% in the table above is what the map computed under `mode=all`;
it is not a rate to quote — the four-belt sighted rate is ~89% and the blind rate ~85%,
each with an interval that does not include the blended number. Second, the `capability_class` axis here is `crb`'s
deterministic, path-derived class — not the LLM-assigned labels in `class_labels.json`,
which are kept as labels only — and the critical-friend review (§4.2, point 4) found that
axis degenerate on library repositories: `bug.fix` absorbs behaviour changes and features.
The `tier` column is `automated-pass` throughout: no cell has a human-verified or A/B
confirmed sign-off, because none has been done.

## 6. The expected numbers, and what CI asserts

`tests/test_census_gate.py` runs on every pull request and asserts **exactly** these
values; if you get anything else, the data or the importer changed, and either is a stop
condition (the test's docstring: do not "fix the test").

| Quantity | Expected | Where it is asserted |
|---|---|---|
| Manifest | every listed file present, sha256 matches | `test_manifest_matches_files` |
| Rows imported = raw lines = ledger rows | **1,071** | `test_every_row_imports_and_false_q1_is_zero` |
| `false_q1_total` | **0** | same |
| `ledger.verify()` (chain length) | **1,071** | same |
| `belt_set == v3-legacy` | **706** | `test_known_counts_hold` |
| `belt_set == v4` | **365** | same |
| `clean` | **962** | same |
| `disqualified` | **8** | same |
| `error` non-empty | **12** | same |
| `mode == blind` | **144** | same |
| every row has an `evidence_pack_hash` | true | same |
| every row `apparatus_version == "1.0-census"` | true | same |
| every row `provenance` starts with `imported:` | true | same |
| any cell routed `deliver` (class × size) has `n ≥ 10` and `false_q1 == 0` | true | `test_no_cell_delivers_below_min_n` |

```bash
.venv/bin/pytest -q tests/test_census_gate.py
```

```
....                                                                     [100%]
4 passed in 0.33s
```

Numbers that appear above but are **not** in the gate — 927 sighted rows, the 682 / 114 /
166 clean split, the 33 routing cells, 8 `deliver` cells — are derived from the same rows by
the commands shown; they are reproducible, not asserted.

## 7. What you may claim after running this

> Mirrors §9 of `docs/reviews/2026-09-13-critical-friend.md` ("what the evidence *does*
> license") and the claim shapes in `docs/EVIDENCE-AND-CLAIMS.md` §6–7. Tags as in §1 there.
>
> **You may say**
> - "The vendored census ledger (`data/census-2026-07-08`, 1,071 rows, sha256-manifested)
>   imports into `crb` 2.0 with 0 skipped rows, the hash chain verifies, and **0 rows are
>   credited clean while any belt they recorded is not `True`** (false-Q1, mechanical = 0)."
>   **[measured]** — re-derivable by anyone from §1–§4.
> - "This holds over three belts for 706 rows and four belts for 365; belt 4 is unmeasured,
>   not passed, for the 706." **[measured]**
> - "Under apparatus `1.0-census`, builder `claude-code-workflow` (Sonnet), the
>   retrospective commit-replay corpus graded by each repository's own held-out tests
>   shows, for the class × size cell (`bug.fix`, `XS`), sighted four-belt rows 49/55 clean
>   (89.1%, Wilson 95% [0.78, 0.95]), blind four-belt rows 51/60 (85.0%, [0.74, 0.92]),
>   sighted three-belt legacy rows 274/281 (97.5%, [0.95, 0.99]), false-Q1 = 0 in each" —
>   and likewise for any other cell in §5, *split by mode and belt set, with its n,
>   interval, builder and apparatus attached*; never the blended 374/396 (94.4%), which
>   pools two measurements of the same task and two belt sets. **[measured, retrospective]**
> - "A forged verdict in this ledger is refused at read, and any edit breaks the chain at
>   the edited row" (§8). **[measured]**
>
> **You may not say**
> - anything about apparatus **2.0** from these rows — the current instrument's ledger is
>   not this file, and a number that blends `1.0-census` and `2.0` is barred by policy;
> - that any `deliver` cell here means autonomous delivery is safe, or that a per-class
>   capability exists — the class axis is path-derived and degenerate on library repos
>   (review §4.2), and "deliver" is a candidate label under a published bar (§6 of the
>   claims policy), unvalidated prospectively and unaudited semantically;
> - that a green suite proved semantic correctness, that the public commits were
>   contamination-free, or that the builder runs themselves were reproduced — they were
>   not run here;
> - any rate without its `n`, interval, mode, builder/model and apparatus version.

## 8. Optional: tamper checks

Do these on **copies**; the exit codes are the product's behaviour, not a demonstration.

Flip one non-clean row to `clean: true` (a forged Q1) — the row is refused at read, before
the chain is even walked, because its recorded belt 3 is `False`:

```
$ .venv/bin/crb ledger verify --path "$CRB_HOME/tampered.jsonl"
crb: error: FalseQ1Violation: ledger refuses clean row e1aee4b872 (fastify): belts={'tests_unmodified': True, 'target_green': True, 'no_new_failures': False}
exit 2
```

Edit a field that is *not* a verdict (here `latency_s` on line 503) — the invariant is
satisfied but the row's hash no longer matches, and everything after it is untrusted:

```
$ .venv/bin/crb ledger verify --path "$CRB_HOME/chainbreak.jsonl"
/…/home/chainbreak.jsonl: CHAIN BROKEN — row 503 (e1aee4b872) row_hash mismatch
exit 1
```

## 9. Known limits and findings

* **The builder runs are not reproduced.** 863 distinct tasks on 22 repositories, Claude
  Code credits, July 2026; the `bench.py` grader is untracked. Only the ledger's consistency
  and the grader's re-derivation
  from recorded belts are checked. A reviewer who wants belt truth re-established must run
  the tasks again under apparatus 2.0 — a different, and separately reported, ledger.
* **`banked_grades.jsonl` is provenance only** (§2). Its belt coverage is too thin for the
  ledger to accept a clean row honestly, so it contributes no number anywhere.
* **A refused import is not atomic.** `crb ledger import-census` appends row by row; when the
  banked file was fed in by mistake, two non-clean rows had been appended before the first
  clean row was refused. Point `--path` at a fresh file when experimenting, or re-verify
  afterwards; in the intended use (one import of `grades.jsonl` into an empty workdir) the
  question does not arise.
* **The class axis** of every cell above is path-derived and coarse on these repositories
  (review §4.2). Treat per-class rows as *cells with that label*, not as capability by
  change type, until the intent-derived class (Wave A workstream A4) has re-labelled them.
* **Cleanup:** `rm -rf "${CRB_HOME%/home}"` removes the temporary directory. Nothing was
  written anywhere else.

Related: [EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) · [ADR-0001](adr/0001-four-belts-and-false-q1-at-write.md) ·
[ADR-0002](adr/0002-append-only-hash-chained-ledger.md) · [ADR-0003](adr/0003-one-routing-rule.md) ·
[data/census-2026-07-08/README.md](../data/census-2026-07-08/README.md) ·
[2026-09-13 critical-friend review](reviews/2026-09-13-critical-friend.md)
