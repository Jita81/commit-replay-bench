# Branch protection on `main` — the reading of 2026-09-27

The required status checks of this repository's `main` branch, read once from the
repository setting and kept here so the README's sentence about them can be re-derived
without access to the setting.

| File | What |
|---|---|
| `required_status_checks.json` | `strict` and `contexts` from `gh api repos/Jita81/commit-replay-bench/branches/main/protection/required_status_checks`, read 2026-09-27 (the reading of 2026-09-26 found the same contexts); only those two fields are kept. `_apparatus` is the product's apparatus version on `main` that day. |
| `MANIFEST.sha256` | The content hash of the file above. `shasum -a 256 -c MANIFEST.sha256` must pass. |

`tests/test_measured_claims.py` checks the manifest, re-derives the README's count of required
checks from this reading, and compares the reading with the jobs in
`.github/workflows/ci.yml` through `scripts/check_branch_protection.py`. A later reading is a
new directory; this one is never edited.
