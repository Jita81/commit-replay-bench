# Human review guide — the load-bearing core, in half a day

**For:** an engineer who did *not* build Commit Replay Bench, reviewing it before any external
demonstration. **Why:** the critical-friend review (`2026-09-13-critical-friend.md`, §6 and action #8)
found that none of the product's commits had been read by a human; the playbook we sell requires exactly
that. **Scope:** the ~6k lines that the honesty claim rests on — the grader and the worktree it grades,
the ledger, the negative controls, the builder guards, the store's append-only triggers, the evidence
pack, and (since the first independent pass) the test-infrastructure table, belt 5, the sealed
checkout, the review anchor and the sign-off gate. Everything else (UI, server routes, runners, miners)
can be wrong without making a false pass *recordable*; these cannot.

Budget: ~1.5 h reading, ~2.5 h "try to break it", ~30 min sign-off. This guide was first written
against `reboot/v2 @ 655e732` (2026-09-13/14) and **re-baselined after the independent AI pass**
(`signoffs/2026-09-14-fable-ai-pass.md`, 9 findings on `842875b`) closed its findings: every line
number below is from the re-baselined tree, every "Observed" line names the commit it was observed on,
and every exercise whose expected outcome CHANGED says what it used to be. If yours differs, that is a
finding.

---

## 0. Set-up (10 min)

```bash
git clone https://github.com/Jita81/commit-replay-bench && cd commit-replay-bench
git checkout reboot/v2 && git rev-parse --short HEAD          # record this in the sign-off
uv venv -q .venv --python 3.12
uv pip install -q -e '.[dev,server]' --python .venv/bin/python
.venv/bin/crb --version                                        # crb 2.0.0a1
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
| 1 | `src/crb/core/grade.py` (516 lines) | "**Every belt that was evaluated must hold** for the trial to be credited `clean`" … "Everything else fails closed" … "`GradeResult` enforces the invariant in `__post_init__`: it is impossible to construct a `clean=True` result with any belt not `True`. That is the poka-yoke the whole product rests on." | `GradeResult.__post_init__` (L160) is the only place `clean=True` can be minted. `derive_clean` (L193) must agree with it. In `grade()`, every early return goes through `done()` with `clean=False`; the one `clean = belts.all_true and not lint_error` (L500) must be the last statement. The pre-flight `ws.enforce_integrity()` (L302) runs before anything else and DQs (`worktree integrity: …`). Belt 1b (`infra_tampered`, L210) and 1c run before any test. Belt 3 on a timed-out or unattributable belt run is `False`, not `None`. Belt 5 folds in at the end: `None` is *not evaluated*, never a pass. Check the `except Exception` at L514 records the error rather than swallowing it. |
| 2 | `src/crb/core/workspace.py` (755 lines) | "The grader's view is independent of the builder's git" — `touched_files` "enumerates from the **filesystem against the parent tree** … the index, `HEAD`, `info/exclude` and `core.excludesFile` are never consulted"; `enforce_integrity` "is the grader's pre-flight: `HEAD` must still be the parent, the worktree must still belong to the harness's clone, no index entry may carry a skip-worktree or assume-unchanged bit, and the shared `info/exclude` must hold only what the harness recorded at create time". | `touched_files` (L512): `parent_tree` (L495, `ls-tree -r <parent>` from the object store) vs a fresh blob hash of every file — find a git state the builder can write that changes the answer. `_not_ignored_by_parent` (L620): the only honoured ignore rules are patterns present in a `.gitignore` tracked at the parent; `info/exclude` sources (`.git/…`) and absolute `core.excludesFile` sources are never honoured. `enforce_integrity` (L322) and `restore_exclude` (L294): the exclude file of a *linked worktree is the main clone's* — one builder's line hides a path for every worktree; membership is by line so a concurrent trial's harness line is not tamper. `diff_stats` diffs against `parent` by sha, never `HEAD`. Known residual: a checkout that differs from its blob (`eol=crlf`, LFS) reads as touched (fail-closed). |
| 3 | `src/crb/core/test_infra.py` (721 lines) | "The oracle is the test **run**, not the test **files**" … every rule "carries the *reason* it is oracle-relevant; a rule without a reason is a bug" … "Fail closed" (unparsable / oversize / DOCTYPE ⇒ changed) … "Lint configuration is test infrastructure too (ADR-0011 amendment)". | `INFRA_RULES` (L154) is the whole belt-1b contract — read it as a table, per language, and think of a file the runner reads that is not in it. `matching_rule` (L457): whole-file rules win over section-aware ones. `infra_sections_changed` (L663): the section parsers for `pyproject.toml` (`[tool.pytest]`, `pytest11`, **`[tool.ruff]`**), `setup.cfg`/`tox.ini` (`[tool:pytest]`, `[pytest]`, **`[flake8]`**), `package.json` (runner keys, `scripts.test`, **`eslintConfig`/`prettier`/`scripts.lint`**), `go.mod`, `pom.xml`, `Cargo.toml` (**`[lints]`**). `.editorconfig` is JS-only (prettier reads it) — decide whether you agree. Documented residuals: files a config *references*, `src/pytest.py` shadowing under a `pythonpath_suffix`. |
| 4 | `src/crb/core/ledger.py` (996 lines) | "Two invariants are enforced at *write* time, not read time: **false-Q1 = 0** … **no pack ⇒ no Q1**" … "**`belt_set` must agree with the apparatus**" … "`verify_chain` walks a ledger and proves nothing was edited, reordered or removed." | `GradeRow.assert_invariants` (L411) runs in `__post_init__`, so a bad row cannot even exist in memory — at write and on read alike. `assert_belt_set_matches_apparatus` (L444) + `expected_belt_sets` (L118): `v3-legacy` (and a `1.0-census` `v4`) only for `imported:` census rows, `2.0`–`2.1` ⇒ `v4`, `2.2+` ⇒ `v5`; a `v3-legacy` row has `source_changed=None`. `body()` (L530) hashes every field except `row_hash` and any belt the row's set does not record (so pre-belt-5 ledgers still verify); `chained()` sets `prev_hash` *before* hashing. `JsonlLedger.append` calls `assert_invariants` again (L718) then `fsync`. `false_q1_total` (L994) re-derives from the recorded belts, not the flag. `derive_failure_kind` is the ONE rule naming why a row is not clean. |
| 5 | `src/crb/core/oracle/controls.py` (1371 lines) | "prove the INSTRUMENT rejects what it must reject, with no model." Seven generators; `gold` MUST grade clean, `noop`/`stub` red, `test_tamper` disqualified, `regression` regressed; `hardcode_cheat` is a "MEASUREMENT control … If it grades `clean` that is a **MEASURED ORACLE ESCAPE**"; `env_poison` is expected *caught by belt 1* (a clean row there is a grader gap). "A harness error on any control is a `VIOLATION`: the gate never passes on an error." | `observe()` (L153) fails closed. `EXPECTED` (L138) is the whole contract — read it as a table. `TamperGuard` (L177) re-hashes the oracle before every grade. The `env_poison` generator (L497) writes a **root `conftest.py`** — belt 1b now disqualifies it (exercise 4). Controls grade with `evaluate_lint=False` (ADR-0011): belt 5 must not decide a control. `_apply_control` raises `_NotConstructible` honestly rather than faking a row. `ControlsReport.passed` (L577) is `True` iff no VIOLATION — escapes do *not* fail `passed`; the router and the sign-off gate DO gate on escapes (a CI reader of `passed` alone is misled — decide whether you agree). |
| 6 | `src/crb/core/lint.py` (999 lines) — belt 5 | "the repository's OWN formatter/linter accepts the files the builder changed … That definition is the repository's, never ours: belt 5 runs the linter the repository configures, or nothing." "The honest asymmetry (`None` ≠ pass ≠ fail)". | `_read_exit` (L339) is the ONE place an exit code is interpreted: findings ⇒ `False`, timeout ⇒ `False`, not-runnable / crash ⇒ harness error, never a pass. `run_plan` (L393) stops at the first rejection and hands only changed, existing, extension-matched files to a `paths="changed"` tool. Detection per language (`go_plan` L611, `python_plan` L662, `js_plan`, `jvm_plan`, `rust_plan`, and `tsc` where the repo's CI runs it, L715ff) reads the repository's config — which belt 1b now protects (file 3): confirm every file `python_ruff_evidence` / `js_plan` reads is in `INFRA_RULES`. Every default is a check-only invocation (a linter that *fixes* the worktree would be a verdict on the wrong bytes). |
| 7 | `src/crb/builders/base.py` (2240 lines) — the guards | "`TestFileGuard` and `GitArchaeologyGuard` are the shared input-mistake-proofing every adapter applies … refused *before* it happens (tool loops) or flagged after the fact (subprocess agents). The grader's belts remain the authority — these guards only stop honest mistakes early and turn dishonest ones into recorded protocol violations." | `TestFileGuard` (L529): absolute paths, `..`, symlink escape, `.git/` **as written or resolved** (`resolved_rel`, L587), protected test paths, anything `RepoConfig.is_test` says is a test — for the path and for what it resolves to. `GitArchaeologyGuard.check` (L1603) / `check_shell` (L1607): segments on `&& || ; | &` *and newlines*; `$( )`, backticks and `( )` hoisted (`_hoist_substitutions`, L1077 — quoted punctuation becomes a sentinel, so `grep '('` is text); redirection targets inspected (`_redirect_target`, L1397) and `tee/cp/mv/install/ln/dd of=` targets (`_write_target_arg`, L1406), symlinks followed when a cwd is known; inline code scanned (`_scan_code`, L1462). Read the two corpora (`tests/fixtures/shell_corpus*.txt`, ~450 lines each) and think of a line for each. Known gaps, documented in the class docstring: string concatenation inside inline code (`'gi'+'t'`), variable verbs, script files (`bash x.sh`, `make`, `python x.py`) — the sealed container (file 9) is that belt. Confirm `BuildOutcome` (L395) carries no verdict. |
| 8 | `src/crb/store/db.py` + `src/crb/store/ledger.py` + `src/crb/store/models.py::APPEND_ONLY_TABLES` | "the ledger tables can be appended to and read, never rewritten" — SQLite `RAISE(ABORT)` / PostgreSQL trigger on `UPDATE` and `DELETE` for `("grades", "events", "signoffs", "evidence", "reviews")`. `DbLedger.append` "runs in one transaction under a write lock … read the last `row_hash`, chain, validate the false-Q1 invariant, insert." | `install_append_only_triggers` (db.py L104) is called from both `init_db` and the Alembic migrations — a migrated DB and a fresh DB get the same **ten** triggers. `assert_append_only` (ledger.py L288) is the `/health` probe: it *tries* an UPDATE and expects failure. `_lock` (L70): `BEGIN IMMEDIATE` on SQLite, advisory lock on PG — two concurrent appends cannot fork the chain. `DbReviewLedger.append` (L202): the reviewed row is resolved by `grade_row_hash` and the pack by **the row's** hash (file 10). Note there is no trigger on `INSERT`: anyone with DB write access can append; the chain proves order and integrity, not authorship. |
| 9 | `src/crb/builders/container.py` (976 lines) — the sealed posture | `SealedCheckout` (L294): "the commit under test is not there (`git cat-file -e <sha>` fails)" … no alternates, no pointer at the main clone; `copy_back` (L533) "Regular files only: a symlink …, a `.git` component or a path that resolves outside `ws.root` is refused and reported, never followed." | `create` (L335): the answer is *not in the container* — `rev-list --count HEAD` is 1, the gold commit and the gold blob are unreachable. `diff_against_parent` (L515) uses `touched_files` on the sealed workspace, so the same tree-based rule applies inside. `copy_back` transfers bytes, never links; a tampered test IS copied so belt 1 on the host sees it. This posture is **opt-in** (`CRB_BUILDER__EXECUTOR=docker`, `deploy/README.md` §9); every host-posture row was measured without it. `tests/test_builders_container_docker.py -m docker` needs a daemon. |
| 10 | `src/crb/core/review.py` (656 lines) | "A reviewer attests to *bytes*, not to a description of them" … "**Whose pack.** The pack is the REVIEWED ROW's — resolved from the row named by `grade_row_hash`, never from the record's own `evidence_pack_hash` field." | `check_review_anchor` (L356) is the ONE rule both ledgers apply: the record's pack field must equal the row's, a caller's pack must be self-certifying (`pack_is_authentic`, L349: its `pack_hash` recomputes), a verdict is never chained without the pack, then `check_patch_anchor` (L322). `JsonlReviewLedger.append` (L414) *requires* the pack for a verdict. `derive_verdict` is the ONE rule for the headline; a `regression` finding refuses `mergeable=True`. Findings and statements pass through `redact`. |
| 11 | `src/crb/core/signoff.py` (969 lines) | The sign-off gate: a human attests to a *cell*; refusals `false_q1` and `attestation` are non-overridable; `oracle_unmeasured` (L155, policy v2) "no task of the cell has a mutation score" is a refusal in the same family as `controls_unmeasured` and is **non-relaxable**. | `evaluate_signoff` (L623) is the gate; `SignoffPolicy` (L255) says which refusals an operator may relax (`CRB_SIGNOFF__…`) and `relaxed=True` is stamped when one is. `stamp_evidence` (L566) pins what was true at sign-off (route, controls, oracle strength) into the hashed record. `JsonlSignoffLedger` chains like the others. Try to sign a cell with nothing measured (exercise 6c). |
| 12 | `src/crb/core/evidence.py` (164 lines) | "The per-task evidence pack. 'No pack ⇒ no Q1.' … the complete, redacted, self-describing record of one graded trial … Its canonical-JSON hash is what the ledger row carries; a ledger row without a pack hash cannot be written." "Packs … contain no secrets (everything passes through `crb.core.redact`) and, by default, no raw model output." | `EvidencePack.body()` (L133) is everything that is hashed; `verify_pack` (L161) recomputes it — and is what makes a pack *self-certifying* for the review anchor. `ApparatusStamp` — "Evidence expires with its apparatus" — check the version is stamped on every pack and row. A pack holds `diff_sha256` + counts, never the patch (ADR-0006); a retained worktree is *served* against that hash (`server/routes/grades.py::retained_patch_text` reassembles the diff exactly as `Workspace.diff_stats` hashed it — the drift test in `tests/test_server_routes_reviews.py` pins the two). |

Supporting reading if time allows: `docs/adr/0001-four-belts-and-false-q1-at-write.md`,
`0002-append-only-hash-chained-ledger.md`, `0006-zero-raw-retention-and-evidence-packs.md`,
`0011-repo-lint-belt.md` (belt 5 and both amendments), `docs/EVIDENCE-AND-CLAIMS.md` §2 and §5 (the
legacy-belt caveat you will need in exercise 7), and the previous sign-offs under `signoffs/`.

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
`GradeRow.from_dict` with a hand-written dict. Try `belt_set="v3-legacy"` with `source_changed=False`
on an otherwise-default (measured, apparatus `2.2`) row — the AI pass (finding 4) **constructed and
appended** exactly that on `842875b`; it must now raise `LedgerIntegrityError: … belt_set='v3-legacy'
is not what apparatus '2.2' (provenance 'measured') records — expected v5`. The legacy set is reachable
only with `provenance="imported:…"` and `apparatus_version="1.0-census"`, and then the first three belts
are still checked and `source_changed` must be `None`. Also try a `v5` row stamped `2.1` and a `v4` row
stamped `2.2` (both refused), and confirm the census import in exercise 7 still loads.

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

**Expected:** **ten** triggers (`{grades,events,signoffs,evidence,reviews}_no_{update,delete}` — the
guide said eight before the `reviews` table existed); both statements fail with `Error: stepping,
grades is append-only (19)`, exit 19; the row is unchanged. Observed 2026-09-13 (eight) and 2026-09-14
on `842875b` (ten): exactly that.

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
grader stops at belt 1; belt 5 `None` is *not evaluated* here too), `dq_reason: target test file
modified — disqualified`, exit 1, and a **not-clean** row ledgered with an evidence pack. Observed
2026-09-14 on the re-baselined tree:

```
7b3c9c77e3 (demo) [sighted]: DISQUALIFIED
  belts: tests_unmodified=False, target_green=None, no_new_failures=None, source_changed=None, repo_lint_clean=None
  dq_reason: target test file modified — disqualified
  ledgered: …/ledger.jsonl row=140a75541717 pack=11bbe4514586
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

**Expected:** `DISQUALIFIED`, `dq_reason: non-target test files modified: ['tests/test_calc.py']`,
exit 1 — belt 1c, in the grader itself. Observed 2026-09-14 on `842875b`: exactly that. (On `655e732`
this graded **`CLEAN`**: belt 1 protected the *target* tests only and the regression's silenced test
was caught one layer up, in `TestFileGuard.tampered()` via the adapter — a floor that depended on
every caller going through the adapter. It is in the belts now; the docstring's "the builder cannot
move the goalposts" holds for `crb grade`, a re-grade and any builder alike.)

### Exercise 4 — add a root `conftest.py` and grade (must DQ on belt 1b)

This was review §4.3, the most important hardening item of the first review. A `conftest.py` at the
repo root runs at pytest collection time; if it injects the missing function into the module under
test, the target goes green with **no implementation and no test edit**, and `conftest.py` itself
satisfies belt 4 because it is not under `tests/`.

```bash
crb prep demo "$SUB" --dest "$CRB_HOME/wt-poison"
printf 'import pkg.calc as _m\nexec("def sub(a, b):\\n    return a - b\\n", _m.__dict__)\n' > "$CRB_HOME/wt-poison/conftest.py"
crb grade demo "$SUB" --worktree "$CRB_HOME/wt-poison" --json | grep -E '"(clean|disqualified|dq_reason|tamper_files|tests_unmodified)"' -A1
```

**Expected:** `"disqualified": true`, `"dq_reason": "test infrastructure modified: ['conftest.py']"`,
`"tests_unmodified": false`, `"tamper_files": ["conftest.py"]` (and `"diff": null` — nothing ran;
without the `| grep` the exit code is 1). Observed 2026-09-14 on `842875b` and on the re-baselined
tree: exactly that. (On `655e732` it graded **`"clean": true`**; the evidence pack's
`diff` also reported `"files": [], "additions": 0` because `diff_stats` saw tracked changes only —
both fixed: `diff_stats` diffs untracked files against `/dev/null` and hashes the full text.)
Also try `pytest.ini`, `pyproject.toml` `[tool.pytest.ini_options]`, `sitecustomize.py`, a `.pth`
file, `pkg/conftest.py`, and a `conftest.py` hidden by a builder-written `.gitignore` — all DQ; an
honest `pyproject.toml` edit under `[project]` only must still grade `CLEAN` (section-aware). For the
JS/Go/JVM/Rust tables use `crb.core.test_infra.is_test_infra` / `infra_sections_changed` directly.

**Exercise 4b — hide the poison from git itself (must DQ: `worktree integrity`).** The AI pass
(finding 1) found three ways to make git *not report* the file, each graded `clean` on the host
posture. Each carries an identity edit to `pkg/calc.py` so belt 4 holds on its own:

```bash
# (a) info/exclude — the exclude file of a linked worktree is the MAIN CLONE's
crb prep demo "$SUB" --dest "$CRB_HOME/wt-a"; cd "$CRB_HOME/wt-a"
printf 'import pkg.calc as _m\nexec("def sub(a, b):\\n    return a - b\\n", _m.__dict__)\n' > conftest.py
printf '# touched\n' >> pkg/calc.py
echo conftest.py >> "$(git rev-parse --path-format=absolute --git-path info/exclude)"; cd "$REPO_ROOT"
crb grade demo "$SUB" --worktree "$CRB_HOME/wt-a"; echo "exit=$?"
# (b) a commit inside the worktree (HEAD moves)
crb prep demo "$SUB" --dest "$CRB_HOME/wt-b"; cd "$CRB_HOME/wt-b"
printf 'import pkg.calc as _m\nexec("def sub(a, b):\\n    return a - b\\n", _m.__dict__)\n' > conftest.py
printf '# touched\n' >> pkg/calc.py; git add -f conftest.py; git commit -q -m x; cd "$REPO_ROOT"
crb grade demo "$SUB" --worktree "$CRB_HOME/wt-b"; echo "exit=$?"
# (c) a tracked infra file flagged skip-worktree — needs a repo whose parent TRACKS conftest.py;
#     build one as in exercise 3 with `: > conftest.py` in the init commit, then in its worktree:
#     poison conftest.py; git update-index --skip-worktree conftest.py   (or --assume-unchanged)
```

**Expected through `crb grade`** (observed 2026-09-14 on the re-baselined tree): (a) `DISQUALIFIED`,
`dq_reason: test infrastructure modified: ['conftest.py']`, exit 1 — belt 1b from the tree walk, which
never reads the exclude file; (b) `crb: error: --worktree HEAD … is not the task's parent …`, exit 2 —
the CLI's own HEAD pin refuses before grading (a harness error, not a row); (c) `DISQUALIFIED`,
`dq_reason: worktree integrity: skip-worktree / assume-unchanged set on: conftest.py`, exit 1.

**Expected through `grade()` / `run_task`** (the product's run path, which on `842875b` had no HEAD
check at all): all three `DISQUALIFIED` with a `worktree integrity: …` reason — (a) `info/exclude
carried 1 line(s) the harness did not write (removed): ['conftest.py']`, and the line is GONE from the
main clone's exclude file afterwards (it hid the path for every other worktree of the repo); (b) `HEAD
… is not the parent …`; (c) as above. `tests/test_grade.py` and `tests/test_run.py` pin each.

In every case `Workspace.touched_files()` lists `conftest.py` regardless — the tree walk, not the
pre-flight, is what holds the belt (`tests/test_workspace.py`). One residual to record: through
`crb grade` the `Workspace` is *bound* to a worktree `crb prep` created in another process, so there is
no create-time baseline and the builder's exclude line is NOT removed (`grep conftest "$(git -C
"$CRB_HOME/wt-a" rev-parse --path-format=absolute --git-path info/exclude)"` still finds it); the
verdict is right, the shared file stays dirty until `crb prep` persists the baseline. Then try to find
a fourth: something the builder can write inside the worktree that changes what
`Workspace.touched_files()` returns.

**Exercise 4c — rewrite the linter's configuration (must DQ on belt 1b).** With a repo whose parent
carries `pyproject.toml` `[tool.ruff.lint] select = ["E", "F"]` (register it as in exercise 3 and set
`--runner-opt python=` to an interpreter with `ruff` beside it), an unused import grades
`repo_lint_clean=False` (`failure_kind: lint`). The AI pass (finding 2) then wrote `select = []` into
`pyproject.toml`, and separately a nested `pkg/ruff.toml` with `[lint]\nselect = []`, and got `CLEAN`
with `repo_lint_clean=True`. **Expected now:** `DISQUALIFIED`, `dq_reason: test infrastructure
modified: ['pyproject.toml']` / `['pkg/ruff.toml']`; an honest `[project]` version bump in the same
file still grades `CLEAN` with `repo_lint_clean=True` (`tests/test_lint.py::
test_builder_cannot_rewrite_the_linters_configuration` pins all four). `# noqa` in the source is the
repository's own mechanism and still passes — decide whether you agree (ADR-0011 amendment).

### Exercise 5 — run guard-refused shell through `GitArchaeologyGuard.check_shell`

```bash
python - <<'EOF'
from crb.builders.base import GitArchaeologyGuard
g = GitArchaeologyGuard()
for c in [
  "git log --oneline -5", "git show HEAD~1:pkg/calc.py", "git stash", "git diff HEAD~1",
  "pip install requests", "curl https://github.com/x/y/pull/1", "cd pkg && git log -1 | head",
  # the four bypasses the first pass found (all REFUSED since A8) and the redirection the AI pass
  # found (REFUSED since finding 6a):
  "python -c \"import subprocess; subprocess.run(['git','log'])\"", "echo | xargs git log",
  "find . -name '*.py' -exec git log -1 -- {} \\;", "cat .git/HEAD",
  "echo conftest.py >> .git/info/exclude",
  # honest shell that MUST be allowed (each was a real false positive, fixed 2026-09-13/14):
  'grep -n "func (c \\*Command) Context\\|preRun(ctx" command.go', "echo $(pwd) && ls",
  "git status && git diff && git grep sub -- pkg", "echo \"a (b\" | grep '('",
]:
    r = g.check_shell(c); print("REFUSED" if r else "allowed", repr(c), r)
EOF
```

**Expected:** the first twelve refused with an `archaeology:` or `network:` reason; the last four
allowed. Observed 2026-09-14 on the re-baselined tree: exactly that. (History: on `655e732` the
`python -c`, `xargs`, `find -exec` and `cat .git/HEAD` forms were **allowed** — `check()` read only the
first word of each segment; A8 closed them with the inline-code scan and wrapper unwrapping. On
`842875b` `>> .git/info/exclude` was **allowed** — redirection targets were skipped — and `grep '('`
was **refused** as a "stray sub-shell token"; both fixed by the AI pass's findings 6a/7. Run the whole
corpus: `pytest -q tests/test_builders_guard_corpus.py -s` prints the counts.)

Now spend fifteen minutes on (a) reaching history or `.git` with a spelling the guard does not see,
and (b) honest shell it still refuses — (b) inflates the harness-error share. The **live gaps**, named
in the `GitArchaeologyGuard` docstring so you do not rediscover them: inside inline code, string
concatenation and variable verbs (`s.run(['gi'+'t','log'])`, `v='log'; s.run(['git', v])`,
`os.system('g''it log')`, `'git'+' show HEAD~1'` with `shell=True`, `pathlib.Path('.'+'git')`, the
perl/node equivalents); script files (`bash ./x.sh`, `make`, `python x.py`); and, without a cwd,
`git diff <unknown-word>`. Per the module docstring the belts, not the guards, are the authority — a
bypass here cannot mint a false pass (finding 1's fixes hold whatever the builder ran), but it lets a
builder recover the real patch *unrecorded*, which contaminates the measurement (a copied gold patch
grades clean). The sealed container (`CRB_BUILDER__EXECUTOR=docker`, file 9) is the belt for that: the
answer is not in the container. Record any new spelling as a finding for the corpus, with the line.

### Exercise 6 — verify the hash chain with `crb ledger verify`, then break it

```bash
crb ledger verify                                          # the JSONL ledger under $CRB_HOME
cp "$CRB_HOME/ledger.jsonl" "$CRB_HOME/ledger-tampered.jsonl"
sed -i '' 's/"actor": ""/"actor": "mallory"/' "$CRB_HOME/ledger-tampered.jsonl"   # (GNU sed: drop the '')
crb ledger verify --path "$CRB_HOME/ledger-tampered.jsonl"; echo "exit=$?"
```

**Expected:** first run `N rows, chain OK, false-Q1 0, clean-without-pack 0, apparatus ['2.2']`;
second run `CHAIN BROKEN — row 1 (…) row_hash mismatch`, exit 1. Observed 2026-09-14 on `842875b`:
exactly that. Also delete a middle line (prev_hash mismatch), swap two lines, and — the interesting
one — re-hash a tampered row yourself with `GradeRow.chained()` and re-chain every row after it:
verification passes, because the chain proves internal consistency, not that nobody rewrote the whole
file. (But note what the *row type* still refuses on read: a re-hashed row that is clean with a failed
belt, or that claims a belt set its apparatus could not have recorded, raises when the ledger is
loaded.) The mitigation for a consistent rewrite is an external anchor (the row hash quoted in a
commit, a sign-off, or a copy the attacker cannot reach); `docs/DEPLOYMENT.md` records it as a go-live
checklist line, not a mechanism — the AI pass (finding 9) says so; decide whether that is enough for
the deployment you are reviewing.

For the DB ledger the same walk is `DbLedger.verify()`; `/health` calls `assert_append_only`.
Verify a pack too: `verify_pack(json.load(open("$CRB_HOME/evidence/<hash>.json")))` must be `True`.

**Exercise 6b — anchor a review to the wrong row's pack (must be refused in both ledgers).** Two clean
rows A and B with different diffs in a throwaway store; a `ReviewRecord` with `grade_row_hash=A`,
`evidence_pack_hash=<B's pack>`, `patch_sha256_reviewed=<B's diff hash>`. On `842875b`
`DbReviewLedger.append(record)` **accepted** it (the pack was looked up by the record's own field) and
`JsonlReviewLedger.append(record)` without a pack checked nothing (finding 5). **Expected now:** the
DB ledger refuses `pack_hash_mismatch` (the pack is resolved through row A); the JSONL ledger refuses
`pack_required` without a pack and `pack_hash_mismatch` when handed B's pack together with row A; a
pack whose `pack_hash` does not recompute is refused as not the row's
(`tests/test_store_reviews.py::test_append_anchors_to_the_reviewed_rows_pack_never_the_records`,
`tests/test_review.py::test_jsonl_ledger_requires_the_reviewed_rows_pack_for_a_verdict`). The API
(`POST /reviews`) always resolved the pack from the row; the store-level contract now matches it.

**Exercise 6c — sign off a cell whose oracle was never measured (must be refused).** Twenty clean
rows with `oracle_strength=None`, controls passed 7/7: on `842875b` the router said `deliver` and
`evaluate_signoff` refused nothing (finding 3). **Expected now:** refusal `oracle_unmeasured` (policy
v2, `core/signoff.py`), in the same family as `controls_unmeasured` and **not relaxable** by
`CRB_SIGNOFF__*`; `false_q1` and `attestation` remain non-overridable. `tests/test_signoff.py` pins
the decider's rule.

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

- `pytest -q tests/test_grade.py tests/test_workspace.py tests/test_run.py tests/test_test_infra.py tests/test_lint.py tests/test_ledger.py tests/test_oracle_controls.py tests/test_builders_base.py tests/test_builders_guard_corpus.py tests/test_builders_container.py tests/test_review.py tests/test_store_reviews.py tests/test_signoff.py tests/test_store_db.py tests/test_store_ledger.py tests/test_census_gate.py` — the reading list's own suites plus the census gate (add `-m docker` for the sealed-container suite when a daemon is reachable). Read the tests as a second statement of the contract; a contract the tests do not pin is a finding.
- Read one *accepted* diff from a live run next to the maintainer's commit (review §3 shows how, `scratchpad/review/cobra/`). Mechanically clean is not mergeable; the product does not claim otherwise, but the map's word `deliver` does — see whether the UI you are shown makes that distinction visible.
- `crb.core.redact`: paste a fake `sk-…` key, a `ghp_…` token, an `AKIA…` key and an `https://user:pass@host` URL into a test tail and confirm none reaches a pack. Known by design: the URL's *username* survives (`https://alice:[REDACTED]@…`); the DPIA text should say so.
- Which posture are you signing? Every row measured on the host executor was measured without the sealed container. The AI pass's verdict was "do not demonstrate *on the host-executor posture*" while finding 1 stood; the fixes are in the grader now, but a demonstration should still say which executor produced its rows.

---

## 3. Sign-off

Copy `docs/reviews/signoffs/TEMPLATE.md` to `docs/reviews/signoffs/<YYYY-MM-DD>-<reviewer>.md`, fill it
in, and commit it on a branch. A sign-off that lists no findings from §2 is unusual enough to say why.
The template (committed at `docs/reviews/signoffs/TEMPLATE.md`) requires: reviewer, date, the full commit
sha reviewed, environment (name the executor: host or sealed), time spent; a yes/no per core file read
(the twelve of §1); the exercise table (1–7, with 3b, 4b, 4c, 6b, 6c) with expected vs observed and a
match column; numbered findings, each with severity, `file:line`, the reproduction, and whether it is a
**false-pass path** (changes a verdict) or an evidence/observability gap; a verdict (core holds / holds
with conditions / do not demonstrate); and a "Not done" section. Keep every reproduction you find as a
regression test in the same change that fixes it — that is how the previous passes' findings were
closed, and how a reviewer after you knows they stayed closed.

Keep the sign-off honest about what was *not* done (exercises skipped, files skimmed). The product's
own rule applies to its reviewers: a claim without its method is a slogan.
