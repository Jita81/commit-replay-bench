# Census evidence — exposure expansion, 2026-07-08

The raw, immutable evidence behind the numbers in `docs/EVIDENCE-AND-CLAIMS.md`,
copied verbatim from the census workspace (`~/.expansion-bench/state/`) on
2026-09-13. Nothing here is code from the measured repositories: only commit
shas, file paths, verdicts, belt values, and per-repo runner configuration for
24 public open-source repositories.

| File | What |
|---|---|
| `grades.jsonl` | 1,071 graded trials (append-only). 706 rows predate belt 4 (`source_changed`) and are imported as `belt_set=v3-legacy`; 365 carry all four belts. |
| `banked_grades.jsonl` | 232 rows from the earlier paired-factorial campaigns (three-belt grader). |
| `tasks/<repo>_tasks.json` | The mined tasks per repo: target/test/src files, pool, size, authored date, baseline failing set, gold verdict. |
| `configs.json` | The 24 repo configurations (language, runner, layout, belt scope). |
| `class_labels.json`, `operation_labels.json` | Census change-class / operation labels (LLM-assigned upstream; kept as labels, never as the deterministic class). |
| `capability_cells.json` | The upstream per-cell rollup, for reconciliation only. |
| `MANIFEST.sha256` | Content hashes of every file above. `shasum -a 256 -c MANIFEST.sha256` must pass. |

Apparatus: `1.0-census` (the untracked `bench.py` grader). Import with
`crb ledger import-census --grades data/census-2026-07-08/grades.jsonl --tasks-dir data/census-2026-07-08/tasks --configs data/census-2026-07-08/configs.json`.
The CI gate `tests/test_census_gate.py` re-derives every row and asserts false-Q1 = 0.
