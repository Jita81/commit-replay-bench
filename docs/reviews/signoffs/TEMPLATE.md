# Core review sign-off

Copy to `docs/reviews/signoffs/<YYYY-MM-DD>-<reviewer>.md`. Procedure: `docs/reviews/human-review-guide.md`.

- **Reviewer:** <name, role, organisation — must not have authored the reviewed code>
- **Date:** <YYYY-MM-DD>
- **Commit reviewed:** <full sha> on <branch>   (`git rev-parse HEAD`)
- **Environment:** <OS, Python, `crb --version`, executor local|docker>
- **Time spent:** <h reading / h exercises>

## Files read (all six required)

| File | Read in full | Notes |
|---|---|---|
| src/crb/core/grade.py | yes/no | |
| src/crb/core/ledger.py | yes/no | |
| src/crb/core/oracle/controls.py | yes/no | |
| src/crb/builders/base.py (guards) | yes/no | |
| src/crb/store/db.py, store/ledger.py (triggers, chain) | yes/no | |
| src/crb/core/evidence.py | yes/no | |

## Exercises

| # | Exercise | Expected | Observed | Match |
|---|---|---|---|---|
| 1 | Clean row with failed belt → FalseQ1Violation | raises (6/6 variants) | | |
| 2 | UPDATE/DELETE a ledger row in SQLite | trigger aborts, row intact | | |
| 3 | Tampered target test → grade | DISQUALIFIED, belt 1 False, exit 1 | | |
| 3b | Regress neighbour + silence its test (sighted) | 655e732: CLEAN via `crb grade` (red only via the adapter path) | | |
| 4 | Root conftest.py → grade | 655e732: clean (escape); post-A1: disqualified | | |
| 5 | Guard corpus through check_shell | 7 refused / 3 allowed; own attempts: | | |
| 6 | crb ledger verify; tampered copy | OK; CHAIN BROKEN | | |
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
