# Core review sign-off

Copy to `docs/reviews/signoffs/<YYYY-MM-DD>-<reviewer>.md`. Procedure: `docs/reviews/human-review-guide.md`.

- **Reviewer:** <name, role, organisation — must not have authored the reviewed code>
- **Date:** <YYYY-MM-DD>
- **Commit reviewed:** <full sha> on <branch>   (`git rev-parse HEAD`)
- **Environment:** <OS, Python, `crb --version`, executor local|docker — the posture the rows were measured on>
- **Time spent:** <h reading / h exercises>

## Files read (all twelve required — the guide's §1 table)

| File | Read in full | Notes |
|---|---|---|
| src/crb/core/grade.py | yes/no | |
| src/crb/core/workspace.py (touched_files, enforce_integrity) | yes/no | |
| src/crb/core/test_infra.py (belt 1b table, lint config) | yes/no | |
| src/crb/core/ledger.py | yes/no | |
| src/crb/core/oracle/controls.py | yes/no | |
| src/crb/core/lint.py (belt 5) | yes/no | |
| src/crb/builders/base.py (guards) | yes/no | |
| src/crb/store/db.py, store/ledger.py (triggers, chain, review anchor) | yes/no | |
| src/crb/builders/container.py (sealed checkout, copy_back) | yes/no | |
| src/crb/core/review.py (the review anchor) | yes/no | |
| src/crb/core/signoff.py (the sign-off gate) | yes/no | |
| src/crb/core/evidence.py | yes/no | |

## Exercises

| # | Exercise | Expected | Observed | Match |
|---|---|---|---|---|
| 1 | Clean row with failed belt → FalseQ1Violation; measured row claiming v3-legacy → LedgerIntegrityError | raises (6/6 variants); raises | | |
| 2 | UPDATE/DELETE a ledger row in SQLite | ten triggers; trigger aborts, row intact | | |
| 3 | Tampered target test → grade | DISQUALIFIED, belt 1 False, exit 1 | | |
| 3b | Regress neighbour + silence its test (sighted) | DISQUALIFIED, `non-target test files modified` (belt 1c) | | |
| 4 | Root conftest.py → grade | DISQUALIFIED, `test infrastructure modified: ['conftest.py']` | | |
| 4b | Poison hidden from git: info/exclude / commit / skip-worktree | DISQUALIFIED, `worktree integrity: …` (or belt 1b on a bound worktree); exclude line removed | | |
| 4c | Linter config rewritten (`[tool.ruff.lint] select = []`, `pkg/ruff.toml`) | DISQUALIFIED, belt 1b; honest `[project]` edit CLEAN | | |
| 5 | Guard corpus through check_shell | 12 refused / 4 allowed; corpus counts; own attempts: | | |
| 6 | crb ledger verify; tampered copy | OK; CHAIN BROKEN | | |
| 6b | Review anchored to another row's pack | refused in both ledgers (`pack_hash_mismatch` / `pack_required`) | | |
| 6c | Sign-off with the oracle unmeasured | refused `oracle_unmeasured`, non-relaxable | | |
| 7 | Census false-Q1 re-derivation | 1071 / 962 / 365 / 0 | | |

## Findings

<numbered; each with severity (blocks demo / fix before pilot / note), file:line, how reproduced,
and whether it is a false-pass path (changes a verdict) or an evidence/observability gap>

## Verdict

- [ ] **Core holds** — no path found to record a false pass; findings are evidence/observability only.
- [ ] **Core holds with conditions** — list the conditions and who owns them.
- [ ] **Do not demonstrate** — a false-pass path exists: <finding #>.

## Not done

<exercises skipped, files skimmed rather than read, variants not attempted>

Signed: <name>  ·  <date>
