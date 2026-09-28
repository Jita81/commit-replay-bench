# Branch protection on `main` — the reading of 2026-09-27

The required status checks of this repository's `main` branch, read once from the
repository setting and kept here so the README's sentence about them can be re-derived
without access to the setting.

| File | What |
|---|---|
| `required_status_checks.json` | `strict` and `contexts` from `gh api repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks`, read 2026-09-27 (the reading of 2026-09-26 found the same contexts); only those two fields are kept. `_apparatus` is the product's apparatus version on `main` that day. |
| `workflow_jobs.json` | The check names the jobs of `.github/workflows/ci.yml` reported on `main` that day (commit `50b0945`, `main`'s head on 2026-09-27), read by `scripts/check_branch_protection.py`: the workflow the reading was compared with. Added on 2026-09-27 so the comparison no longer reads the working tree's `ci.yml`, which a later pull request may change before an admin can require the new job. |
| `MANIFEST.sha256` | The content hashes of the two files above. `shasum -a 256 -c MANIFEST.sha256` must pass. |

`tests/test_measured_claims.py` checks the manifest, re-derives the README's count of required
checks from this reading, compares the reading with the vendored workflow's jobs through
`scripts/check_branch_protection.py`, and checks that `workflow_jobs.json` is what `ci.yml` at
its commit gives. The live comparison of today's workflow with today's setting is the
operator's: `scripts/check_branch_protection.py`. A later reading is a new directory; the
reading in this one is never edited.
