# Branch protection on `main` — the reading of 2026-10-07

The required status checks of this repository's `main` branch, read once from the
repository setting and kept here so the README's sentence about them can be re-derived
without access to the setting. On 2026-10-07 an administrator added two contexts to the
16 of the 2026-09-27 reading (`data/branch-protection-2026-09-27/`): `fresh-clone (…)`,
the `ci.yml` aggregator that had waited under `awaiting_protection` (DL-101), and
`commit-subjects (…)`, the one job of `.github/workflows/commit-subjects.yml`, a
pull-request workflow of its own that the comparison read only from this reading on.

| File | What |
|---|---|
| `required_status_checks.json` | `strict` and `contexts` from `gh api repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks`, read 2026-10-07; only those two fields are kept. `_apparatus` is the product's apparatus version on `main` that day. |
| `workflow_jobs.json` | The check names that must be required, read by `scripts/check_branch_protection.py` (`pull_request_contexts`) from every workflow under `.github/workflows` whose `on:` names `pull_request` at commit `8fa2d73` (`main`'s head on 2026-10-07): `jobs` maps each to the file that reports it, `parts` maps each part of an aggregator, never required, to the aggregator's job key. This is the set the reading was compared with. |
| `MANIFEST.sha256` | The content hashes of the two files above. `shasum -a 256 -c MANIFEST.sha256` must pass. |

`tests/test_measured_claims.py` checks the manifest, re-derives the README's count of required
checks from this reading, compares the reading with the vendored jobs and parts through
`scripts/check_branch_protection.py`, and checks that `workflow_jobs.json` is what the
workflows at its commit give. The live comparison of today's workflows with today's setting
is the operator's: `scripts/check_branch_protection.py`. A later reading is a new directory;
the reading in this one is never edited.
