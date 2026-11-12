# Wave 4 record notes (to be folded into the wave record; nothing here changes a registered number)

## 2026-11-11 23:0xZ — stop (b) reading, decided by Paul before any cobra run

Stop (b): four or more of the first 40 wave builds ending on an outage, a provider error, a
container failure or a refused allowed command, counted from row fields.
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

First 40 wave builds = click batches 1 and 2 (runs 7f3ee062, 3f17a9b8, c0147446, 688a8a4f,
5a6bd92c, b49c2e6a, a2373f88, c98ee5ba). Row `error` fields read from
`GET /api/v1/runs/<id>/tasks` on 2026-11-11 ~22:50Z. Nine builds ended in an error:
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

- 5 × "authoring: the authored test ... is not RED at the parent" (3f17a9b8 ×2, c0147446,
  b49c2e6a, a2373f88)
- 2 × "protocol violation: archaeology: 'git stash' is not allowed" (7f3ee062, b49c2e6a)
- 1 × "'git log' is not allowed (no history/other revisions)" (688a8a4f)
- 1 × "'git show' is not allowed (no history/other revisions)" (c98ee5ba)

No outage, provider error or container failure.

Count under each reading of "a refused allowed command":
- strict (the guard forbids all three commands by design, so none is an allowed command): 0
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- `git stash` only (Amendment 2 called the pilot's refused `git stash list` "an allowed
  command refused in spirit"): 2
- every refused read-only git command: 4 (the stop would have fired)

The team's methodologist raised the ambiguity on 2026-11-11 from pooled figures. Claude Code
had applied the strict reading during the click runs and had reported the count to Paul as 0
without stating the other readings. Paul was shown all three counts and Claude Code's
recommendation (strict reading, recorded with all three counts) and answered: "Happy to
proceed with the [recommendations]". The wave continues under the strict reading. This is a
reading decided after 110 pooled click builds were seen (no arm comparison was made); a
reader who holds the widest reading should treat the wave as one that passed its stop (b) on
the operator's decision.
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

## Refile rule — kept as registered

Paul offered to relax it; the product owner, methodologist and architect personas each
recommended keeping part 2's row rule unchanged for cobra. Applied mechanically on run status
and row count. Click: all runs filed so far ended `succeeded` with 5 of 5 rows; batch 3 was
refiled once (run 98fe708c failed its gold control before any build; no row was read).
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

## Other things the wave record must state
- runs from click-3/1 onward were filed by the `svc-claude` operator account;
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- a poster crash / login-verify timeout before batch 3 (no run lost);
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- both pilot gates failed and waived (Amendment 2).
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

## 2026-11-11 23:27:59Z — second stack restart (cobra builder image), granted once by Paul

- `~/crb-stack/env.sh` line 22 changed from `export CRB_BUILDER__IMAGE=crb-builder:local` to
  `export CRB_BUILDER__IMAGE=crb-builder-go:local` (image Id 77b43c312c7a, built 2026-10-11);
  backup beside it: `env.sh.bak-20261111T232545Z`. Lines 20 and 23 unchanged.
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- Preconditions met: every click batch filed (24 succeeded runs + 1 refiled gold-control failure,
  120 rows), no active run, worker idle.
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- `CRB_SKIP_UI_BUILD=1 ~/crb-stack/restart.sh` finished 2026-11-11T23:27:59Z: api pid 25906,
  worker pid 25907, apparatus 2.5, served commit 7bb03d6c (unchanged), database at 0018.
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- After restart: cobra posture id `pst_a308788d88899137d5fae9c7` (unchanged, not stale, class
  docker/copy/sealed, sandbox image crb-sandbox-go:main-8ab88ad, 74 of 86 qualified); no
  re-qualify needed. Each run checks its own gold control before any build.
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- Campaign before the first cobra run: spent $28.848331 of $95, left $66.151669.
  **[hypothesis — `spent_usd` and `left_usd` read from `GET /api/v1/campaigns/<id>` on the served stack through the signed-in browser, apparatus 2.5; the campaign record is not in this repository]**
- Cobra poster started ~23:30Z, same svc-claude account.
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

## 2026-11-12 — test (h) record: field names and values, read from the served code

Recorded by the delivery manager before the script of R5 is committed, as R5 item 2 test (h)
and Amendment 4 ask. Every line is read from the served code at `7bb03d6c`. None is read from
a run, a row, an event or a kept request.
**[hypothesis — the delivery manager's statement of what was read on 2026-11-12; the session is not in this repository]**

- The run record is `GET /api/v1/runs/{run_id}`, schema `RunOut`, built by `run_out`. The
  filing time is `created`. The end time is `finished`, null until the run ends. The status
  is `status`. The row count is `counts.rows`. The commits are `task_ids`. The kind is `kind`.
  **[measured — n = 6 fields, method: read-only `git show` of `src/crb/server/schemas.py` 601-643 and `src/crb/server/routes/runs.py` 547-597 at the served commit `7bb03d6c`, apparatus 2.5; a property of the product's code, not a graded row]**
- `RunOut` carries no `arm`, no `test_author` and no campaign field.
  **[measured — n = 1 schema, method: read-only `git show` of `src/crb/server/schemas.py` 601-643 at the served commit `7bb03d6c`, apparatus 2.5; a property of the product's code, not a graded row]**
- `test_author` is stored as sent, with outer whitespace removed, and only when `arm` is
  sent.
  **[measured — n = 1 code path, method: read-only `git show` of `src/crb/server/routes/runs.py` 772-776 at the served commit `7bb03d6c`, apparatus 2.5; a property of the product's code, not a graded row]**
- The value of Amendment 4 point 3, `editblock:gpt-oss-120b`, has no outer whitespace, so
  sent and stored are the same string. The code reads it as builder `editblock`, model
  `gpt-oss-120b`, and an empty provider.
  **[measured — n = 2 functions, method: read-only `git show` of `src/crb/builders/adapter.py` 457-479 and `src/crb/factory/author.py` 394-421 at the served commit `7bb03d6c`, apparatus 2.5; a property of the product's code, not a graded row]**
- The campaign record is `GET /api/v1/campaigns/{campaign_id}`. Each admitted run is listed
  with `runs[].run_id` and `runs[].s1`. `s1` is set at admission and is true when the request
  carried an `arm` field.
  **[measured — n = 2 fields, method: read-only `git show` of `src/crb/server/campaigns.py` 455-531 and `src/crb/server/routes/runs.py` 1246 and 1290 at the served commit `7bb03d6c`, apparatus 2.5; a property of the product's code, not a graded row]**
- The test author's event is `author.attempt`. Its `provider` field holds the provider of
  the endpoint that was called. The value for an endpoint in the `cerebras.ai` domain is
  `cerebras`. An author call that raises writes no such event.
  **[measured — n = 1 event and 1 value, method: read-only `git show` of `src/crb/factory/author.py` 326-348 and `src/crb/builders/openai_client.py` 530-544 at the served commit `7bb03d6c`, apparatus 2.5; a property of the product's code, not a graded row]**

## 2026-11-12 — two notes from the outside review of Amendment 4

- The ruling file `r5-arm-source-ruling-v2.txt` is a signed record, fixed by its sha256.
  It is not edited after signing, and it carries no claim tags of its own. The claims in
  it that this wave relies on are restated, with tags, in Amendment 4 and in the section
  above.
  **[hypothesis — the delivery manager's statement of how the file is kept, 2026-11-12]**
- Section 9 of that ruling says every failure of sections 3 to 8 is printed "with the run
  ids and times". Section 6.3 item 4 of the same ruling, and Point 4 of Amendment 4, say a
  failure of the provider test prints counts only and no run id. The script follows the
  narrower rule: a provider-test stop prints counts only. The script's tests on made-up
  rows assert that no run id reaches that output.
  **[aspiration — a rule for the read script, which is not yet written; fixed before any result by arm exists]**
