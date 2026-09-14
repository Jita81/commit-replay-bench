# Human review guide — the load-bearing core, in half a day

**For:** an engineer who did *not* build Commit Replay Bench, reviewing it before any external
demonstration. **Why:** the critical-friend review (`2026-09-13-critical-friend.md`, §6 and action #8)
found that none of the product's commits had been read by a human; the playbook we sell requires exactly
that. **Scope:** the ~4k lines that the honesty claim rests on — the grader, the ledger, the negative
controls, the builder guards, the store's append-only triggers and the evidence pack. Everything else
(UI, server routes, runners, miners) can be wrong without making a false pass *recordable*; these six
cannot.

Budget: ~1 h reading, ~2 h "try to break it", ~30 min sign-off. Every command below was run on
`reboot/v2 @ 655e732` on 2026-09-13/14 and its output is quoted; if yours differs, that is a finding.

---

## 0. Set-up (10 min)

```bash
git clone https://github.com/Jita81/commit-replay-bench && cd commit-replay-bench
git checkout reboot/v2 && git rev-parse --short HEAD          # record this in the sign-off
uv venv -q .venv --python 3.12
uv pip install -q -e '.[dev,server]' --python .venv/bin/python
.venv/bin/crb --version                                        # crb 2.0.0a0
export PATH="$PWD/.venv/bin:$PATH"; export REPO_ROOT="$PWD"
export CRB_HOME="$(mktemp -d)/crb-review"                      # a THROWAWAY home. Never point this at a live stack.
```

`CRB_HOME` is where `crb` keeps repos, tasks, the JSONL ledger and evidence packs
(`src/crb/cli/commands/__init__.py` documents the layout). The live stack on `127.0.0.1:8000` has its own
home; do not use it for these exercises.

---

## 1. What to read, in order (≈ 1 h)

Read each file top to bottom. The docstring states the invariant; your job is to confirm the code
actually holds it and to look for a path around it. The quoted lines are the contract.

| # | File | The invariant it must hold (quoted from the docstring) | What to look for |
|---|---|---|---|
| 1 | `src/crb/core/grade.py` (302 lines) | "**All four must hold** for the trial to be credited `clean`" … "Everything else fails closed" … "`GradeResult` enforces the invariant in `__post_init__`: it is impossible to construct a `clean=True` result with any belt not `True`. That is the poka-yoke the whole product rests on." | `GradeResult.__post_init__` (L109–117) is the only place `clean=True` can be minted. `derive_clean` (L141) must agree with it. In `grade()`, every early return goes through `done()` with `clean=False`; the one `clean=belts.all_true` (L288) must be the last statement. Belt 3 on a timed-out or unattributable belt run is `False`, not `None`. Check the `except Exception` at L300 records the error rather than swallowing it. |
| 2 | `src/crb/core/ledger.py` (445 lines) | "Two invariants are enforced at *write* time, not read time: **false-Q1 = 0** … **no pack ⇒ no Q1** — a clean row must carry a non-empty `evidence_pack_hash`." … "`verify_chain` walks a ledger and proves nothing was edited, reordered or removed." | `GradeRow.assert_invariants` (L152–166) runs in `__post_init__`, so a bad row cannot even exist in memory. `body()` (L187) hashes every field except `row_hash`; `chained()` sets `prev_hash` *before* hashing. `JsonlLedger.append` calls `assert_invariants` again (L320) then `fsync`. `false_q1_total` (L443) re-derives from belts, not the flag. Legacy rows: `recorded_belts()` (L146) applies the invariant to three belts when `belt_set="v3-legacy"` — confirm no code path lets a v4 row claim v3-legacy. |
| 3 | `src/crb/core/oracle/controls.py` (926 lines) | "prove the INSTRUMENT rejects what it must reject, with no model." Seven generators; `gold` MUST grade clean, `noop`/`stub` red, `test_tamper` disqualified, `regression` regressed; `hardcode_cheat`/`env_poison` are "MEASUREMENT controls … If one of them grades `clean` that is a **MEASURED ORACLE ESCAPE**". "A harness error on any control is a `VIOLATION`: the gate never passes on an error." | `observe()` (L129) fails closed. `EXPECTED` (L114) is the whole contract — read it as a table. `TamperGuard` (L153) re-hashes the oracle before every grade. The `env_poison` generator writes a **root `conftest.py`** (L683) — the review (§4.3) argues this must become a belt-1 disqualification, not an escape; workstream A1 is changing that. `_apply_control` raises `_NotConstructible` honestly rather than faking a row. `ControlsReport.passed` is `True` iff no VIOLATION — escapes do *not* fail the gate (deliberate; decide whether you agree). |
| 4 | `src/crb/builders/base.py` (913 lines) — the guards | "`TestFileGuard` and `GitArchaeologyGuard` are the shared input-mistake-proofing every adapter applies … refused *before* it happens (tool loops) or flagged after the fact (subprocess agents). The grader's belts remain the authority — these guards only stop honest mistakes early and turn dishonest ones into recorded protocol violations." | `TestFileGuard` (L516): absolute paths, `..`, symlink escape, `.git/`, protected test paths, anything `RepoConfig.is_test` says is a test. `GitArchaeologyGuard.check` (L786) — the allow-list is `GIT_ALLOWED`; `check_shell` (L821) splits on `&& || ; | &` and recurses into `$( )`, backticks and `( )`. Three false-positive classes were fixed on 2026-09-13 (`966a247`, `95a4f2e`, `d964318`); a guard that refuses honest shell inflates the harness-error rate, so read the corpus in `tests/test_builders_base.py` and think of a fourth. Confirm `BuildOutcome` carries no verdict. |
| 5 | `src/crb/store/db.py` + `src/crb/store/ledger.py` + `src/crb/store/models.py::APPEND_ONLY_TABLES` | "the ledger tables can be appended to and read, never rewritten" — SQLite `RAISE(ABORT)` / PostgreSQL trigger on `UPDATE` and `DELETE` for `("grades", "events", "signoffs", "evidence")`. `DbLedger.append` "runs in one transaction under a write lock … read the last `row_hash`, chain, validate the false-Q1 invariant, insert." | `install_append_only_triggers` (db.py L104) is called from both `init_db` and the Alembic initial migration (`migrations/versions/v0001_initial_schema.py` L246) — a migrated DB and a fresh DB get the same triggers. `assert_append_only` (ledger.py L153) is the `/health` probe: it *tries* an UPDATE and expects failure. `_lock` (L52): `BEGIN IMMEDIATE` on SQLite, advisory lock on PG — two concurrent appends cannot fork the chain. Note there is no trigger on `INSERT`: anyone with DB write access can append; the chain proves order and integrity, not authorship. |
| 6 | `src/crb/core/evidence.py` (164 lines) | "The per-task evidence pack. 'No pack ⇒ no Q1.' … the complete, redacted, self-describing record of one graded trial … Its canonical-JSON hash is what the ledger row carries; a ledger row without a pack hash cannot be written." "Packs … contain no secrets (everything passes through `crb.core.redact`) and, by default, no raw model output." | `EvidencePack.body()` (L133) is everything that is hashed; `verify_pack` recomputes it. `ApparatusStamp` — "Evidence expires with its apparatus" — check the version is stamped on every pack and row. Know what a pack does **not** hold: `diff_sha256` + counts, never the patch (ADR-0006) — a reviewer cannot re-examine what was accepted from the pack alone; the review's action #3 proposes bounded patch retention. |

Supporting reading if time allows: `docs/adr/0001-four-belts-and-false-q1-at-write.md`,
`0002-append-only-hash-chained-ledger.md`, `0006-zero-raw-retention-and-evidence-packs.md`,
`docs/EVIDENCE-AND-CLAIMS.md` §2 and §5 (the legacy-belt caveat you will need in exercise 7).

---

## 2. Try to break it (≈ 2 h)

Each exercise states the expected outcome. Record the actual outcome in the sign-off; a mismatch is a
finding whether it is better or worse than expected.

### Exercise 1 — construct a clean row with a failed belt

**Expected:** `FalseQ1Violation` from both the grader's result type and the ledger's row type, in
every variant.

```bash
python - <<'EOF'
from crb.core.grade import Belts, FalseQ1Violation, GradeResult
from crb.core.ledger import GradeRow
H = "x" * 64
attempts = {
  "GradeResult, belt 3 False": lambda: GradeResult(task_id="deadbeef", repo="demo", mode="sighted", clean=True,
      belts=Belts(tests_unmodified=True, target_green=True, no_new_failures=False, source_changed=True)),
  "GradeRow, belt 3 False":    lambda: GradeRow(repo="demo", task_id="deadbeef", clean=True, tests_unmodified=True,
      target_green=True, no_new_failures=False, source_changed=True, evidence_pack_hash=H),
  "GradeRow, belt 4 None":     lambda: GradeRow(repo="demo", task_id="deadbeef", clean=True, tests_unmodified=True,
      target_green=True, no_new_failures=True, source_changed=None, evidence_pack_hash=H),
  "GradeRow, no pack":         lambda: GradeRow(repo="demo", task_id="deadbeef", clean=True, tests_unmodified=True,
      target_green=True, no_new_failures=True, source_changed=True, evidence_pack_hash=""),
  "GradeRow, error set":       lambda: GradeRow(repo="demo", task_id="deadbeef", clean=True, tests_unmodified=True,
      target_green=True, no_new_failures=True, source_changed=True, evidence_pack_hash=H, error="timeout"),
  "GradeRow, disqualified":    lambda: GradeRow(repo="demo", task_id="deadbeef", clean=True, tests_unmodified=True,
      target_green=True, no_new_failures=True, source_changed=True, evidence_pack_hash=H, disqualified=True),
}
for name, make in attempts.items():
    try:
        make(); print(f"FLOOR BROKEN — {name} was constructed")
    except FalseQ1Violation as e:
        print(f"ok  {name}: {e}")
EOF
```

Observed 2026-09-13: all six raise, e.g. `ledger refuses clean row deadbeef: no evidence pack (no pack ⇒ no Q1)`.

Then try to get around it: `object.__setattr__(row, "clean", True)` on a non-clean row, then
`JsonlLedger(...).append(row)` — `append` calls `assert_invariants()` again and must raise. Try
`GradeRow.from_dict` with a hand-written dict. Try `belt_set="v3-legacy"` on a row with a `False` fourth
belt (allowed by design — the legacy set has three belts; confirm the first three are still checked).

### Exercise 2 — edit a ledger row in SQLite (trigger must abort)

Build a throwaway server DB and import the JSONL rows you will produce in exercise 3, then attack it with
the `sqlite3` CLI (bypassing every Python layer). Do exercise 3 first, or seed the DB after it.

```bash
cat > "$CRB_HOME/seed_db.py" <<'EOF'
import os
from crb.core.ledger import JsonlLedger
from crb.store import DbLedger, init_db, make_engine, make_session_factory
home = os.environ["CRB_HOME"]
engine = make_engine(f"sqlite:///{home}/crb.db"); init_db(engine)
ledger = DbLedger(make_session_factory(engine))
print("imported", ledger.import_rows(JsonlLedger(f"{home}/ledger.jsonl").rows()), "row(s); chain verifies", ledger.verify())
EOF
python "$CRB_HOME/seed_db.py"
sqlite3 "$CRB_HOME/crb.db" "select name from sqlite_master where type='trigger' order by name;"
sqlite3 "$CRB_HOME/crb.db" "update grades set clean=1 where seq=1;";  echo "exit=$?"
sqlite3 "$CRB_HOME/crb.db" "delete from grades where seq=1;";         echo "exit=$?"
sqlite3 "$CRB_HOME/crb.db" "select seq, clean, tests_unmodified, disqualified, substr(row_hash,1,12) from grades;"
```

**Expected:** eight triggers (`{grades,events,signoffs,evidence}_no_{update,delete}`); both statements
fail with `Error: stepping, grades is append-only (19)`, exit 19; the row is unchanged.
Observed 2026-09-13: exactly that.

Then try harder: `DROP TRIGGER grades_no_update;` succeeds for anyone with DDL rights on the file —
this is a property of SQLite, not a bug, but it means **the triggers protect against mistakes, not
against a privileged attacker; the hash chain (exercise 6) is what detects the latter.** Say so in your
findings if you think the docs under-state it. Also try `insert into grades …` with an invented
`row_hash` — it is accepted (no INSERT trigger) and exercise 6 must then fail.

### Exercise 3 — tamper a test file in a worktree and grade (must DQ)

Build a two-commit demo repository (plain git; no network), register it, mine it, prepare a trial
worktree at the target commit's parent, apply the correct source change **and** rewrite the target test
to pass trivially. The grader must disqualify on belt 1 regardless of the green.

```bash
export GIT_AUTHOR_NAME=reviewer GIT_AUTHOR_EMAIL=reviewer@example.invalid \
       GIT_COMMITTER_NAME=reviewer GIT_COMMITTER_EMAIL=reviewer@example.invalid
D="$CRB_HOME/demo-repo"; mkdir -p "$D/pkg" "$D/tests" && cd "$D" && git init -q -b main
: > pkg/__init__.py; echo "# demo" > README.md; git add -A; git commit -q -m init
printf 'def add(a, b):\n    return a + b\n' > pkg/calc.py
printf 'from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n' > tests/test_calc.py
git add -A; git commit -q -m "feat: add"
printf 'def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n' > pkg/calc.py
printf 'from pkg.calc import sub\n\n\ndef test_sub():\n    assert sub(5, 3) == 2\n' > tests/test_sub.py
git add -A; git commit -q -m "feat: sub"
SUB=$(git rev-parse HEAD); cd "$REPO_ROOT"

crb repo add demo --path "$D" --language py --src-prefix pkg/ --test-prefix tests/ \
    --belt-scope tests/ --probe tests/test_calc.py --runner-opt python="$REPO_ROOT/.venv/bin/python"
crb mine demo --target 2                                   # examined 2, found 2
crb prep demo "$SUB" --dest "$CRB_HOME/wt-tamper"          # parent + tests overlaid (sighted)
printf 'def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n' > "$CRB_HOME/wt-tamper/pkg/calc.py"
printf 'def test_sub():\n    assert True\n' > "$CRB_HOME/wt-tamper/tests/test_sub.py"     # the tamper
crb grade demo "$SUB" --worktree "$CRB_HOME/wt-tamper" --ledger; echo "exit=$?"
```

**Expected:** `DISQUALIFIED`, `tests_unmodified=False`, the other belts `None` (never evaluated — the
grader stops at belt 1), `dq_reason: target test file modified — disqualified`, exit 1, and a
**not-clean** row ledgered with an evidence pack. Observed 2026-09-13:

```
cc04e476d6 (demo) [sighted]: DISQUALIFIED
  belts: tests_unmodified=False, target_green=None, no_new_failures=None, source_changed=None
  dq_reason: target test file modified — disqualified
  ledgered: …/ledger.jsonl row=86d6513be452 pack=16abb8c14e23
exit=1
```

Variants worth five minutes each: tamper only whitespace / a trailing newline (belt 1 is byte-level —
must still DQ); `--mode blind` with the test rewritten before grading (belt 0 DQ: "builder modified
test files pre-overlay").

**Exercise 3b — regress a neighbour and silence its test (sighted).** Belt 1 protects the *target*
tests only; belt 3 compares failing sets. So break `add()`, then rewrite the neighbouring
`tests/test_calc.py` to `assert True`:

```bash
crb prep demo "$SUB" --dest "$CRB_HOME/wt-neighbour"
printf 'def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n' > "$CRB_HOME/wt-neighbour/pkg/calc.py"
printf 'def test_add():\n    assert True\n' > "$CRB_HOME/wt-neighbour/tests/test_calc.py"
crb grade demo "$SUB" --worktree "$CRB_HOME/wt-neighbour"; echo "exit=$?"
```

Observed 2026-09-14 on 655e732: **`CLEAN`, all four belts `True`, exit 0.** The standalone grader
credits a regression whose test was silenced. In the product's real build path this *is* caught — but
one layer up, not in the belts: `TestFileGuard.tampered()` (`builders/base.py` L608) flags "any other
touched test-classified file in either mode", the adapter then discards the source edits before
grading, and the row lands red with `protocol violation: tamper: …`
(`tests/test_builders_adapter.py::test_error_attempt_row_is_never_clean` pins this). Decide for
yourself whether a floor that depends on every caller going through the adapter is the floor the
docstring in `grade.py` promises ("the builder cannot move the goalposts"). Anything that grades a
worktree directly — `crb grade`, a future builder that bypasses `build_fn_for`, an operator re-grade —
gets the weaker belt. Record it as a finding; it belongs with A1's belt-1 widening (action #1).

### Exercise 4 — add a root `conftest.py` and grade (today: escapes; re-run after A1 merges)

This is review §4.3, the most important open hardening item. A `conftest.py` at the repo root runs at
pytest collection time; if it injects the missing function into the module under test, the target goes
green with **no implementation and no test edit**, and `conftest.py` itself satisfies belt 4 because it
is not under `tests/`.

```bash
crb prep demo "$SUB" --dest "$CRB_HOME/wt-poison"
printf 'import pkg.calc as _m\nexec("def sub(a, b):\\n    return a - b\\n", _m.__dict__)\n' > "$CRB_HOME/wt-poison/conftest.py"
crb grade demo "$SUB" --worktree "$CRB_HOME/wt-poison" --json | grep -E '"(clean|source_changed|changed_files|files|additions)"' -A1
```

**Today (655e732):** `"clean": true`, `"changed_files": ["conftest.py"]`, `"source_changed": true`.
Observed 2026-09-13: escapes exactly so. Note also that the evidence pack's `diff` reports
`"files": [], "additions": 0` for this clean grade — `Workspace.diff_stats` uses `git diff HEAD`, which
sees tracked changes only, while `touched_files` also lists untracked files. A clean row whose whole
change is a *new* file therefore carries a diff hash of an empty diff. That is a second, smaller finding
(evidence, not verdict); record it.

**After workstream A1 (action #1, belt 1 over test-infrastructure files) merges:** the same command must
return `disqualified` with a belt-1 reason naming `conftest.py`. Re-run and record the commit you re-ran
on. Also try `pytest.ini` / `pyproject.toml` `[tool.pytest.ini_options]` edits, a `sitecustomize.py`,
and — for the JS runners — `jest.config.js`.

### Exercise 5 — run guard-refused shell through `GitArchaeologyGuard.check_shell`

```bash
python - <<'EOF'
from crb.builders.base import GitArchaeologyGuard
g = GitArchaeologyGuard()
for c in [
  "git log --oneline -5", "git show HEAD~1:pkg/calc.py", "git stash", "git diff HEAD~1",
  "pip install requests", "curl https://github.com/x/y/pull/1", "cd pkg && git log -1 | head",
  # honest shell that MUST be allowed (each was a real false positive fixed on 2026-09-13):
  'grep -n "func (c \\*Command) Context\\|preRun(ctx" command.go', "echo $(pwd) && ls",
  "git status && git diff && git grep sub -- pkg",
]:
    r = g.check_shell(c); print("REFUSED" if r else "allowed", repr(c), r)
EOF
```

**Expected:** the first seven refused with an `archaeology:` or `network:` reason; the last three
allowed. Observed 2026-09-13: exactly that. Now spend fifteen minutes on (a) reaching history with a
spelling the guard does not see, and (b) honest shell it still refuses (heredocs, `awk` with
parentheses, …) — (b) inflates the harness-error share the review put at 45%.

Observed 2026-09-14 for (a): `git -C .. log`, `git --git-dir=../.git show HEAD~1`, `sh -c 'git log'`
and `GIT_DIR=/x git show HEAD~1` are all **refused** (wrappers, global options and env prefixes are
unwrapped). But all four of these are **allowed**:

```
python -c "import subprocess; subprocess.run(['git','log'])"
xargs git log                      # e.g.  echo | xargs git log
find . -name '*.py' -exec git log -1 -- {} \;
cat .git/HEAD                      # (shell guard; the file-read guard is a separate path)
```

`check()` inspects only the first word of each pipeline segment, so `git` as an *argument* of another
program is invisible. Per the module docstring the belts, not the guards, are the authority — a bypass
here cannot mint a false pass, but it lets a builder recover the real patch *unrecorded*, which
contaminates the measurement (a copied gold patch grades clean). Record as a finding for the guard
corpus (workstream A10, review §5 play 04).

### Exercise 6 — verify the hash chain with `crb ledger verify`, then break it

```bash
crb ledger verify                                          # the JSONL ledger under $CRB_HOME
cp "$CRB_HOME/ledger.jsonl" "$CRB_HOME/ledger-tampered.jsonl"
sed -i '' 's/"actor": ""/"actor": "mallory"/' "$CRB_HOME/ledger-tampered.jsonl"   # (GNU sed: drop the '')
crb ledger verify --path "$CRB_HOME/ledger-tampered.jsonl"; echo "exit=$?"
```

**Expected:** first run `N rows, chain OK, false-Q1 0, clean-without-pack 0, apparatus ['2.0']`;
second run `CHAIN BROKEN — row 1 (…) row_hash mismatch`, exit 1. Observed 2026-09-13: exactly that.
Also delete a middle line (prev_hash mismatch), swap two lines, and — the interesting one — re-hash a
tampered row yourself with `GradeRow.chained()` and re-chain every row after it: verification passes,
because the chain proves internal consistency, not that nobody rewrote the whole file. The mitigation is
an external anchor (the row hash quoted in a commit, a sign-off, or a copy the attacker cannot reach);
check whether the deployment you are reviewing has one (`docs/DEPLOYMENT.md`, `docs/DATA-RETENTION.md`).

For the DB ledger the same walk is `DbLedger.verify()`; `/health` calls `assert_append_only`.
Verify a pack too: `verify_pack(json.load(open("$CRB_HOME/evidence/<hash>.json")))` must be `True`.

### Exercise 7 — re-derive false-Q1 = 0 from the census JSONL

The census (1,071 rows, 24 public repos) is vendored under `data/census-2026-07-08/`; the CI gate
`tests/test_census_gate.py` re-derives it on every PR. Do it yourself with `sqlite3` alone. The review's
Appendix A SQL is written for a live server DB whose `grades` rows all carry four belts; **706 census rows
predate belt 4** (`belt_set = v3-legacy`, no `source_changed` key), so the belt-4 clause must be applied
only where the belt was recorded — the naive appendix SQL counts 682 phantom "violations".

```bash
(cd data/census-2026-07-08 && shasum -a 256 -c MANIFEST.sha256 | grep -vc ': OK$')   # 0 = every file intact
sqlite3 :memory: <<'SQL'
.separator "\x1f" "\n"
create table raw(line text);
.import data/census-2026-07-08/grades.jsonl raw
select 'rows', count(*) from raw;
select 'clean', count(*) from raw where json_extract(line,'$.clean')=1;
select 'four-belt rows', count(*) from raw where json_extract(line,'$.source_changed') is not null;
select 'false-Q1', count(*) from raw
 where json_extract(line,'$.clean')=1
   and (json_extract(line,'$.tests_unmodified') is not 1
     or json_extract(line,'$.target_green') is not 1
     or json_extract(line,'$.no_new_failures') is not 1
     or (json_extract(line,'$.source_changed') is not null and json_extract(line,'$.source_changed') is not 1));
SQL
```

**Expected:** `rows 1071`, `clean 962`, `four-belt rows 365`, `false-Q1 0`. Observed 2026-09-13: exactly that.

Against a live server DB (the review's appendix, made belt-set aware — use this form whenever the DB
holds imported census rows):

```sql
select count(*) from grades
 where clean=1 and (tests_unmodified is not 1 or target_green is not 1 or no_new_failures is not 1
                    or (belt_set='v4' and source_changed is not 1));
-- failure split (instrument vs model), per repo/mode:
select repo, mode, count(*), sum(clean), sum(error<>''), sum(error='' and clean=0)
  from grades where process_step='replay' group by 1,2;
```

Then the full import through the product's own path, which also proves the chain end to end:
`crb ledger import-census --grades data/census-2026-07-08/grades.jsonl --tasks-dir data/census-2026-07-08/tasks --configs data/census-2026-07-08/configs.json && crb ledger verify`.

### If you have another hour

- `pytest -q tests/test_grade.py tests/test_ledger.py tests/test_oracle_controls.py tests/test_builders_base.py tests/test_store_db.py tests/test_store_ledger.py tests/test_census_gate.py` — the six files' own suites plus the census gate. Read the tests as a second statement of the contract; a contract the tests do not pin is a finding.
- Read one *accepted* diff from a live run next to the maintainer's commit (review §3 shows how, `scratchpad/review/cobra/`). Mechanically clean is not mergeable; the product does not claim otherwise, but the map's word `deliver` does — see whether the UI you are shown makes that distinction visible.
- `crb.core.redact`: paste a fake `sk-…` key and an `https://user:pass@host` URL into a test tail and confirm neither reaches a pack.

---

## 3. Sign-off

Copy `docs/reviews/signoffs/TEMPLATE.md` to `docs/reviews/signoffs/<YYYY-MM-DD>-<reviewer>.md`, fill it
in, and commit it on a branch. A sign-off that lists no findings from §2 is unusual enough to say why.
The template (committed at `docs/reviews/signoffs/TEMPLATE.md`) requires: reviewer, date, the full commit
sha reviewed, environment, time spent; a yes/no per core file read; the exercise table (1–7, with 3b)
with expected vs observed and a match column; numbered findings, each with severity, `file:line`, the
reproduction, and whether it is a **false-pass path** (changes a verdict) or an evidence/observability
gap; a verdict (core holds / holds with conditions / do not demonstrate); and a "Not done" section.

Keep the sign-off honest about what was *not* done (exercises skipped, files skimmed). The product's
own rule applies to its reviewers: a claim without its method is a slogan.
