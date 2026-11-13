# Wave 5, step 0: the A3 repeat — recorded as not done

Made 2026-11-13 17:19Z by the delivery manager, under section 4.2 step 0 and section 4.5 of
`docs/reviews/2026-11-13-wave-5-registration.md`. No model was called and nothing was spent.

## Result

**Not done.** The authored test of the selected row was not kept, so the rule of step 0
applies: "if the authored test was not kept, no new one is authored and the repeat is recorded
as not done." The author gate stays as it is on main. Nothing here changes a registered number.

## The row, by the fixed rule

- Source: the served task rows of the Wave 4 cobra runs, read through the product's own API
  (`GET /api/v1/runs/<id>/tasks`), sign-in `svc-claude`, 2026-11-13 17:10Z to 17:19Z.
- Rows whose `error` contains "failed without attributable test ids": 15, in 9 runs, all on
  the S1 arm **[measured — n = 15 rows in the 31 cobra runs of 2026-11-11 to
  2026-11-12, method: substring match on the served `error` field, apparatus 2.5]**.
- `attempt` is the arm's attempt number: the first or the second S1 slot of the batch, in
  the batch's registered order. Section 6.4 of the registration defines an arm's slots in a
  batch as its attempts.
- Key: sha256("crb.w5.a3|" + task_id + "|" + attempt), hex, smallest first, ties by task id.

| sha256 (first 16 hex) | task id (first 12) | attempt | run (first 8) |
|---|---|---|---|
| `030962d23fa86784` | `b9ca5949e2f5` | 1 | `5757bed0` |
| `3c1d880f0d5a3674` | `890302a35f57` | 2 | `d768fea1` |
| `4e0eb8da430f8a63` | `b9ca5949e2f5` | 2 | `b93cb250` |
| `528e96dd03baad7e` | `ed7b60e2987d` | 1 | `220e17cd` |
| `83b7f2f2c70d7171` | `02a0d2fbc9e6` | 1 | `76df3cb7` |
| `83f35bd06cb39802` | `45e521ea93e2` | 2 | `31377ac9` |
| `8ea7939289c2e25a` | `a15d0990180c` | 2 | `d768fea1` |
| `a53db05ac4390269` | `890302a35f57` | 1 | `011c4214` |
| `a5b6177db87893e6` | `a97f9fd47b29` | 2 | `b93cb250` |
| `bd5414f959ae52ae` | `04318720db17` | 2 | `d768fea1` |
| `c2895f9b50ee58a2` | `9054739e0818` | 2 | `d768fea1` |
| `cd67d2349686c345` | `45e521ea93e2` | 1 | `52f8630b` |
| `e128b63517925190` | `e392f3204db0` | 1 | `220e17cd` |
| `e63593808346a8e0` | `23a6174c7f9d` | 2 | `df6fba6c` |
| `ebdadc4ee098d1ec` | `23a6174c7f9d` | 1 | `76df3cb7` |

**The selected row** is the first line:

- task `b9ca5949e2f58373e8e4c3823c213401f7d9d0e3`, S1 attempt 1, run `5757bed0`;
- grade row id `cd730218f396479ab6489b6efd3c506f`, ledger sequence 1003, created
  2026-11-12T02:07:36Z;
- row hash `14813940ad51f88f6553682fe603817789f4f8b4cce152177928c0f0a91fd4d4`;
- served error: "authoring: the authored test 'help_test.go' is not RED at the parent: it
  failed without attributable test ids".

A second reading of `attempt` (the slot number, 1 to 4) would select task `a97f9fd47b29` in
run `b93cb250`. It is recorded here so a reader can see the choice of reading did not decide
the result: that row's authored test was not kept either.

## Why the authored test was not kept

- `GET /api/v1/grades/<row hash>/transcript` for the selected row answers 404, reason "the
  builder transcript was not retained (retain.transcripts was off)", although the run asked
  for transcripts (`retain_transcripts: true`).
- The same answer came back for all 15 rows
  **[measured — n = 15 rows, method: one `transcript` read per row, apparatus 2.5]**.
- The cause is in the code, not in a setting. On an author-gate refusal the adapter removes
  the authored file from the worktree and returns an attempt with no transcript reference
  (`src/crb/builders/adapter.py`, `author_s1` and its `fail` helper, lines 1014 to 1140 in
  the served checkout `7bb03d6c`). The refusal event carries the task id and the first 200
  characters of the error only. The parent run's output is not stored.
- The row's kept patch is the held-out test's diff (`command_test.go`), not the author's file.

## What follows

- **The gate is not changed** (section 4.5). S1 runs in Wave 5 as it is on main.
- **The open question stays open.** Whether these 15 refusals are Go compile failures at the
  parent (an instrument miss) or real author misses cannot be settled from Wave 4's records
  **[hypothesis — the compile-failure reading is the delivery manager's, from
  `error-classes.md` of 2026-11-13; no parent output exists to test it]**.
- **A gap in the product, for the backlog.** A refused authored test and the parent's output
  are evidence, and the product drops both. Keeping them (retention only, no change to what
  the gate decides) would let the next wave's own rows answer the question. This is proposed
  as a separate pull request; it is not part of this registration and is not assumed by it.

## Presses made in the product

One sign-in as `svc-claude` on the local stack. Reads only after that; no run was started.
