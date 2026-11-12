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

## 2026-11-12 — the read script, recorded before it is committed

Written before the primary is read and before any result by arm exists.
**[hypothesis — the delivery manager's statement of when this section was written, 2026-11-12]**

### The methodologist's readings

- The readings on the read script are in `r5-read-script-readings.txt`, beside this file,
  sha256 `71b3c8b3064d91327b0d8c1ce93f5a4373730729acf5c52bddc51d29f963e539`. It is a signed
  record and is not edited after signing. Its line numbers for the script are those of the
  draft the methodologist read, not of the committed script.
  **[hypothesis — the delivery manager's statement of how the file is kept, 2026-11-12]**
- The six script changes the readings require (C1 to C6) are made in the committed script
  `scripts/wave4_primary_read.py`, each with a test on made-up records.
  **[measured — n = 6 changes, method: `pytest tests/test_wave4_primary_read.py` on the branch, apparatus 2.5; a property of the script, not a graded row]**
- The readings cite the read spec by open-point number. The spec the methodologist read is
  `r5-read-script-spec.txt`, beside this file, sha256
  `6b827a754b0b271dc5d2a30c64101aac605ba3a0c68e5622b610403056885c64`. It is copied unedited
  from the delivery manager's working folder, which is the path line 11 of the readings
  names. It is a spec, not the script: where the two differ, the script's opening text
  lists the departure.
  **[measured — n = 1 file, method: `shasum -a 256` by the delivery manager on 2026-11-12; apparatus n/a, a file hash, not a graded row]**
- The readings file carries no claim tags of its own. It is a signed record, so none is
  added. Its statements are the methodologist's readings of the registered text and of the
  draft script, signed 2026-11-12. Each one this record relies on is restated in this
  section under a tag.
  **[hypothesis — the delivery manager's statement of how the readings are to be taken, 2026-11-12]**

### What the poster kept, as the script reads it

- The script reads four files and fixes each by sha256: the plan `wave-batches.json`
  (`ae705b68e03e1ff58972d34cdb81f5e85095ca88449e23a99a9c5276702fb45a`), its copy from before
  `S3` was added, `wave-batches.before-s3.json`
  (`a3c592cd9e7a19210888b2f9bd6d3b8c6e05d6ce76169e996a71d36d7b2970fd`), `click-out.json`
  (`27b2747e044048c6766186a1689cc5749178c46a8dce3c78dacd6ed09a4c4170`) and `cobra-out.json`
  (`59d7eefc3361caa5f78fd18bc8b66f5e0e2cc5f36a1e49915ea79033b506e0e1`).
  **[measured — n = 4 files, method: `shasum -a 256` by the delivery manager on 2026-11-12; apparatus n/a, file hashes, not graded rows]**
- The place of a run in its batch is the `slot` number of its plan entry. The out key is
  the batch name, a slash, and that number. This is read from the poster's source text
  (`wave4_post.py`, sha256 `b30ca68ea35e7659b720011af690c6cc3713dfd8f6ce1777523f4651b850b105`,
  lines 102 to 150).
  **[measured — n = 1 rule, method: reading of the poster's source text by the delivery manager; apparatus n/a, a property of the poster, not a graded row]**
- In the out files the `run` value under each key is an object, not a run id. The ruling
  assumed an id. The object's key names are `id`, `status`, `progress`, `clean`, `errors`,
  `stopped_reason`, `stopped_code`, `cost_usd` and `error`. The script reads `run.id` and
  nothing else, under Point 1 of Amendment 4 ("the run id under each key and nothing else").
  It stops if any entry or any `run` object has a key name other than the recorded ones.
  The delivery manager read key names only, and no value.
  **[measured — n = 49 entries, method: a key-name listing of the two out files by the delivery manager on 2026-11-12, no value printed; files the poster wrote against the served stack at apparatus 2.5; file shapes, not graded rows]**

### Where the 48 standing run ids came from

- The script carries the 48 standing run ids as a fixed list. They were taken from the
  delivery manager's run ledger with no slot column (sha256
  `31ade1ad2417ec5ec75e0536f1bdefd7c47da72d46663e169f52d149f8706495`), which was built from
  the run ids the poster recorded in its out files. The sha256 of the list, one id a line
  in sorted order, is `b79c3cbedaf775238e0f74ddb506a7ebb86858d9b20845ca97a65dd6a7bedf3d`.
  The script checks that hash before it opens any file.
  **[measured — n = 48 ids, method: `shasum -a 256` of the id list by the delivery manager on 2026-11-12; apparatus n/a, a file hash, not a graded row]**
- So test T4 is not independent of the out files. It shows that the out files still agree
  with the ledger as issued. That each id is the right run rests on tests (a) and (b) on
  the run records and on campaign membership. The script prints this, and the wave report
  says it.
  **[hypothesis — the methodologist's reading, item 10 of the readings file, 2026-11-12]**

### Decisions of the delivery manager after the code check

- The script writes its whole output to a file named by `--output`, created new before
  the first request, and to the screen, line for line the same. It will not start if the
  file exists. The filed output is that file, unedited.
  **[aspiration — a rule for the one run of the read, which has not happened; fixed before any result by arm exists]**
- A row that is absent is a miss and does not stop the read (readings, items 1 and 4).
  If any is absent the script says that Amendment 3 recorded 240 rows, and lists each
  absent row with its run id, task, batch and arm after the decision word.
  **[hypothesis — the methodologist's reading, items 1 and 4 of the readings file, 2026-11-12]**
- A stop of the provider test writes the run ids and the two served times to the deviation
  file and prints counts only (Point 4 of Amendment 4 applies test (i)). Every other
  deviation file line that names a run also carries that run's two served times. A
  transport failure names only the run whose request failed.
  **[aspiration — a rule for the one run of the read, which has not happened; fixed before any result by arm exists]**
- The script departs from the read spec in five places, all recorded in its opening
  text: its name and its `--poster-dir` and `--output` arguments; an absent row is a miss;
  no figure for "clean without a usable test" is printed (R12 governs); the provider-stop
  deviation file keeps the two times; exit code 5 for a failed `--output` write.
  **[hypothesis — the delivery manager's decisions of 2026-11-12, made before any result by arm exists]**

### Deviation log entries, entered before the read

- 2026-11-12, the writer of the read spec. Read lines 9 to 18 of this file. Those lines
  hold eight run ids of click batches 1 and 2 and nine build error texts by short run id,
  five of which begin `authoring:`. The spec writer saw outcome-level text by run, namely
  authoring errors on named `S1` runs, before the read. Only `S1` builds have an author, so
  an authoring error names the run's arm. It was joined to nothing. No clean count was
  made. No constant, id or rule in the spec or the script was taken from it.
  **[hypothesis — a deviation of exposure recorded by the delivery manager from the spec writer's own statement, 2026-11-12]**
- 2026-11-12, the methodologist. Set out to read lines 31 to 117 of this file. After a
  break in the session the whole file was read back, lines 1 to 30 included. So the
  methodologist saw outcome-level text by run, namely authoring errors on named `S1` runs,
  before the read. This is the same text section 0 of the ruling already records for this
  seat, seen a second time. It was joined to nothing. No count was computed from it. No
  reading rests on it.
  **[hypothesis — a deviation of exposure recorded from the methodologist's own disclosure in the readings file, 2026-11-12]**

### What happens after a stop

- Exit 1 (not ready): no wave file was opened and no request was made. The cause is
  fixed and the script is started again. This is not a run of the read. Exit 2, 3 or 4:
  nobody runs the script again. The stop goes into the deviation log. Whether the primary
  is then read, and whether that run is a second read, is for Paul in writing.
  **[aspiration — the operator's rule for the one run of the read, from item 13 of the readings file; fixed before any result by arm exists]**
- Exit 5 (added after outside review of the pull request, before any result by arm
  exists): the `--output` file could not be written or closed after it was opened. Each
  line goes to the file before the screen, so the screen never shows a line the file does
  not hold. The script stops at once and prints one fixed line to the screen only. Exit 5
  is treated as exit 2, 3 or 4: nobody runs the script again, and the rest is for Paul in
  writing.
  **[aspiration — the operator's rule for the one run of the read, which has not happened; fixed before any result by arm exists]**
- Two more points are left to Paul in writing and are not in the script: a new test that
  every kept body carries every registered fixed setting, and failing a body that sends
  `arm: "A0"`. As registered, there is no such test, and test (e) accepts `arm: "A0"`.
  **[hypothesis — the methodologist's reading, items 6 and 8 of the readings file, 2026-11-12]**

## 2026-11-12 — Part E record: the script as merged, and the outcome decisions

Written before the primary is read and before any result by arm exists.
**[hypothesis — the delivery manager's statement of when this section was written, 2026-11-12]**

### The read script as merged (Part E item 1)

- The read script was merged to main at commit
  `ddf061a2cfdb1724dc7bccecc44196b9a1bec620` (pull request 132). At that commit
  `scripts/wave4_primary_read.py` has sha256
  `8b9bb6afe1a1d9982e3c6f25d3400939ea0b9badf4de8d9e7655464510727a25`. That is the same
  value the file had at the reviewed head of the pull request,
  `8a3d4fc45aa18d64ec365100163abfe37243da24`.
  **[measured — n = 2 commits, one file, method: `git show ddf061a2cfdb1724dc7bccecc44196b9a1bec620:scripts/wave4_primary_read.py | shasum -a 256` and `git show 8a3d4fc45aa18d64ec365100163abfe37243da24:scripts/wave4_primary_read.py | shasum -a 256`, each commit named by its full id, by the delivery manager on 2026-11-12; apparatus n/a, file hashes, not graded rows]**
- The registration file was not changed by that merge. At the same commit its sha256 is
  `6f6d9c9b71712c988e39a3962cc9522400d3bf98c5f887cf55e2822b8746c03e`, the same value it
  has at `dd52bc8456330cdd2187b3233685a3a0f96b2d76`, the commit that merged Amendment 4.
  **[measured — n = 2 commits, one file, method: `git show ddf061a2cfdb1724dc7bccecc44196b9a1bec620:docs/reviews/2026-11-10-wave-4-registration.md | shasum -a 256` and `git show dd52bc8456330cdd2187b3233685a3a0f96b2d76:docs/reviews/2026-11-10-wave-4-registration.md | shasum -a 256`, each commit named by its full id, by the delivery manager on 2026-11-12; apparatus n/a, file hashes, not graded rows]**
- The read is run from that commit of the script and from no other. If the script is
  changed before the read, the new commit and hash are recorded here first.
  **[aspiration — the operator's rule for the one run of the read, which has not happened]**

### The product owner's outcome decisions (Part E item 6)

- The document is `.context/crb-programme/first-tasks/1a-wave4-outcome-decisions.md` in
  the repository Jita81/AthenaClaude. It is committed at
  `366c799fe000207161c0909be802ea3a0e4b7269` on the branch `docs/crb-programme-records`,
  which is pushed. Its sha256 at that commit is
  `e8d9ac170cef0fd139a30843b6da73f3d55c4fa0fd86e33c3e7ec36f85581e80`.
  **[measured — n = 1 file, method: `git show HEAD:<path> | shasum -a 256` at that commit by the delivery manager on 2026-11-12, and the same value from the working file; apparatus n/a, a file hash, not a graded row]**
- That branch is not merged to that repository's main. Its pull request is still open and
  its checks are red on failures the branch did not cause. The commit and the hash fix the
  text all the same. If the document is changed before the read, the new commit and hash
  are recorded here first.
  **[hypothesis — the state of that pull request as the delivery manager read it on 2026-11-12; it is not in this repository]**
- The document is not copied into this repository. It is a product decision record of the
  programme and lives with the programme's records.
  **[hypothesis — the delivery manager's decision of 2026-11-12 on where the record lives]**
- The document's own pin names the registration as it stood at the head of pull request
  129, commit `32630d12`, sha256
  `dceff4ffe13116c36b76178900c55babeeaba9b03814ed359ed1438a69e02a30`, and says the pin is
  restated when that pull request merges. It has merged. The 809 lines of the registration
  at that head are the first 809 lines of the registration on main today, with no
  difference. Amendments 3 and 4 follow them and were added later. So every part 6 and
  Amendment 2 passage the document quotes stands on main as quoted.
  **[measured — n = 809 lines, method: `diff` of the file at `32630d12` against the first 809 lines of the file at `ddf061a2`, by the delivery manager on 2026-11-12, no difference printed; apparatus n/a, a text comparison, not a graded row]**
- The document was written before Amendments 3 and 4 and does not cite them. It is not
  edited to add them: its hash is fixed here. The wave report reads the outcome name from
  the registration as it stands on main, and takes from the document only what the product
  owner will do in each outcome.
  **[aspiration — the delivery manager's rule for the wave report, which is not yet written]**

### The served code (Part E item 4)

- The served checkout is at `7bb03d6c73c8c9e10cbc283049be2ce9740eb19e`, the commit noted
  at the second restart. It was read after the last blind run and after the cobra `S3`
  runs.
  **[measured — n = 1 checkout, method: `git rev-parse HEAD` in the served checkout by the delivery manager on 2026-11-12, read only; apparatus 2.5 is the apparatus that commit serves]**

### What is still open before the read

- Part E item 2, the cost gate. It is Paul's to close in writing, as the registration
  says. Nothing in this section closes it.
  **[hypothesis — Part E item 2 of the registration on main]**

## 2026-11-12 — Part E item 2 closed by Paul's word, before the read

- Paul wrote to the delivery manager on 2026-11-12, before 12:52Z, in these words: "read
  may go ahead on product dollars, unconfirmed". That is the second of the two things Part
  E item 2 names. The gate is deferred, not passed: no Console figure or export exists, and
  the product's figures are not confirmed against the provider's bill.
  **[hypothesis — Paul's message in the session of 2026-11-12; the transcript is not in this repository]**
- Every cost figure in the wave report carries the label "product dollars, unconfirmed", as
  item 2 requires.
  **[aspiration — a rule for the report, which is not yet written]**
- The script is run once, from a checkout of main at
  `07125be0ef710fd91af5a273ffaa1c002a21f5a3`, where `scripts/wave4_primary_read.py` has
  sha256 `8b9bb6afe1a1d9982e3c6f25d3400939ea0b9badf4de8d9e7655464510727a25`, the value
  recorded above for the merged script.
  **[measured — n = 1 file, method: `shasum -a 256 scripts/wave4_primary_read.py` in a checkout at `07125be0ef710fd91af5a273ffaa1c002a21f5a3` by the delivery manager on 2026-11-12; apparatus n/a, a file hash, not a graded row]**
- This entry was committed and pushed before the read script wrote its output. The commit
  that holds it, `ad5ac9e3a429ebe2eb5deab269f3ad4145e2226f`, has committer time 12:53:03Z.
  The delivery manager's checkout records its push at 12:53:05Z. The script's output file
  was last written at 12:53:13Z. These are times on one machine's clock. They show the
  order of the three events and nothing else.
  **[measured — n = 3 times, method: `git log --format=%cI` for the commit, `git reflog show origin/docs/wave-4-primary-read --date=iso-strict` for the push, and `stat` of the script's `--output` file for the write, by the delivery manager on 2026-11-12; apparatus n/a, clock times, not graded rows]**

## 2026-11-12 — The primary read: made once, filed unedited

- The read script was run once, at 12:53Z on 2026-11-12, by the delivery manager in a
  terminal tab, from a checkout whose only change against main
  `07125be0ef710fd91af5a273ffaa1c002a21f5a3` is the entry above. It printed its own sha256,
  `8b9bb6afe1a1d9982e3c6f25d3400939ea0b9badf4de8d9e7655464510727a25`, and ended with exit
  code 0 (the read was made). No deviation file was written.
  **[measured — n = 1 run of the script, method: `scripts/wave4_primary_read.py` with `--output`, its printed hash and exit code read from the terminal by the delivery manager on 2026-11-12, and a listing of the folder named by `--deviation-out` that shows no deviation file; apparatus n/a, a script run, not a graded row]**
- There was no earlier run and there is no second one. This is the delivery manager's
  statement. No record kept here can prove that a script was not run.
  **[hypothesis — the delivery manager's statement of 2026-11-12; the script keeps no count of its runs]**
- `primary-read-output.txt` is an artefact fixed by its hash. It carries no claim tags,
  because adding one would change the file and break the hash. The tagged record of what
  it says is the entry below, which gives n, method and apparatus. Any later document
  that quotes a figure from the output tags it there.
  **[hypothesis — a filing rule stated by the delivery manager for this one artefact]**
- Its output is filed beside this record as `primary-read-output.txt`, copied byte for byte
  from the file the script wrote. Its sha256 is
  `0ffe99026cfefb0ef04ab43529b1ffecdf982dee9a01984889a410020d06dd53` and it has 118 lines.
  Nothing in it is edited.
  **[measured — n = 1 file, method: `shasum -a 256` of the script's `--output` file and of the copy filed here, equal, by the delivery manager on 2026-11-12; apparatus n/a, a file hash, not a graded row]**
- What the output says, in its own figures. The order check passed. 240 of 240 rows were
  read and none was missing. The difference is `S1` minus `A0`. Over 12 batches and 60
  commits the summed difference is T = -55/2, which is d = -45.8333 points; p = 4/4096 =
  0.0009765625; the interval is -58.6725 to -32.9942 points. The blocks result, on 2 units,
  has p = 2/4 = 0.5. The left-out result cannot be calculated. Usable tests: 0 of 120. The
  decision word the script printed is **Inconclusive** ("the blocks result falls on the
  other side of 0.05").
  **[measured — n = 240 blind rows of 48 runs in 12 batches over 60 commits of click and cobra, method: the one run of `scripts/wave4_primary_read.py` filed as `primary-read-output.txt`, sign-flip test over batches; builder and models as registered in part 2; apparatus 2.5]**
- The output is not yet signed. The methodologist and the validity engineer sign it, or
  say why they do not, in the next entry. Until then no seat states a finding from it.
  **[aspiration — the two signatures are the next step and have not been given]**

## 2026-11-12 — Signatures on the primary read

Both seats read the filed copy in this repository and nothing else. Neither read the
poster's folder, the product or a row.

- **Methodologist: signs.** The seat signs the filed output (sha256
  `0ffe99026cfefb0ef04ab43529b1ffecdf982dee9a01984889a410020d06dd53`) as the primary read,
  with its decision word, Inconclusive. The seat re-did the arithmetic from the printed
  batch sums: T = -55/2, d = -45.8333 points, m = 4 of 4096, the interval -58.6725 to
  -32.9942, and the blocks result p = 2/4. Every figure agrees with the output.
  **[measured — n = 12 printed batch sums, method: recomputation of the sum, the sign-flip count over all 4096 patterns and the interval of part 6 item 2 from the filed output, by the methodologist's seat on 2026-11-12; apparatus n/a, arithmetic on a filed file]**
- **Validity engineer: signs.** The seat signs the same file, its decision word and its
  primary figures, after the same recomputation. Inconclusive is the only finding of the
  wave. The report may describe, and not state as a finding, that on the 60 listed commits
  of both repositories together the `S1` arm as the product served it had fewer clean rows
  than `A0`. The output says nothing about test-first as such.
  **[measured — n = 12 printed batch sums, method: recomputation from the filed output by the validity engineer's seat on 2026-11-12; apparatus n/a, arithmetic on a filed file]**
- **The decision word does not rest on the usable-test count.** Both seats say so. The
  primary p is below 0.05 with `S1` behind. Cleared needs `S1` ahead. No 15-point effect
  needs a p not below 0.05. Neither is reachable, so the word is Inconclusive for any
  count. The output prints one ground, the blocks result. The seats name a second: the
  left-out result cannot be calculated.
  **[hypothesis — the two seats' reading of A9 of the registration, signed 2026-11-12]**
- **Not signed by either seat: "usable tests: 0 of 120" as a measure of the test author.**
  The script counts a row whose `error` field is null or absent as failing test (d) of
  R12. The registered words are "does not begin with `authoring:`". If the product serves
  a null `error` for a row with no error, every such `S1` row was counted as without a
  usable test. The count, the 12 author-hit labels, the two-unit blocks result and the
  left-out result would then come from the counting rule and not from the author. R12 item
  5 names 0 of 120 as what a fault in the check would produce. The pilot read 5 of 6
  **[measured — n = 6 pilot `S1` commits of 18 pilot builds, method: each row's labels, stop reason and failure kind read from `GET /api/v1/grades/<row>`, as the gate table of Amendment 2 in `docs/reviews/2026-11-10-wave-4-registration.md` records, apparatus 2.5]**. No
  seat may call the figure the author's usable-test rate until the served shape of a
  row's `error` field and of the event's `task` key has been checked against the served
  code.
  **[hypothesis — both seats' statements of 2026-11-12; the served shape is not yet checked]**
- **Two misses, for the deviation log.** The spec's rule that a null `error` fails test
  (d) was never ruled on in the methodologist's signed readings. The consistency figure
  that would have shown the fault at once (clean `S1` rows counted without a usable test)
  was taken out by the delivery manager before the script was committed.
  **[hypothesis — the seats' account, 2026-11-12; the deviation log entry is not yet written]**
- **With two units the blocks p can never be below 0.5.** A blocks result needs at least
  six units before it can fall below 0.05. This is a property of the registered design.
  The next registration should say so.
  **[measured — n = 4 sign patterns, method: enumeration of the sign patterns of two units by the methodologist's seat on 2026-11-12; apparatus n/a, arithmetic]**
- **Reserved to Paul in writing.** Whether a corrected count of usable tests may be
  computed after filing and reported as description. The read is not run again without
  that word. Whether more commits are worth their cost is also Paul's, as part 6 says.
  **[hypothesis — the seats' reading of the read-once rule of the registration]**

## 2026-11-12 — Why the output says "usable tests: 0 of 120"

Paul asked for the cause. The entries below give it, each with its method. No agent read
a row, a run, an event or the poster's folder.

- **The 0 of 120 is a counting fault in the read script. It is not a measure of the test
  author.** The product's event emitter takes the `task` key out of an event's payload and
  stores it as the event's top-level `task_id` (`src/crb/observability/events.py` line 350).
  `GET /runs/{id}/events/log` serves `task_id` at the top level and the rest as `payload`
  (`src/crb/server/routes/runs.py` lines 298 to 302). The read script looks for the commit
  in `payload["task"]` (`scripts/wave4_primary_read.py`, `keep_event`), as R12 item 2 of the
  registration says. That key is never there, so test (b) of R12 fails for every attempt,
  whatever the author did. `keep_event` reads the task of each
  `builder.author_test.failed` event from the payload in the same way. In a run that holds
  such an event the missing key also makes test (c) fail for every attempt of that run
  (`usable_attempt`). A correction must mend both lookups.
  **[measured — n = 3 source passages, method: `git show 7bb03d6c73c8c9e10cbc283049be2ce9740eb19e:<path>` for the two product files and a read of the script as merged, by four agents and then the delivery manager on 2026-11-12; apparatus n/a, a reading of code, not a graded row]**
- **What follows from it.** The 12 "author-hit" labels, the blocks result on two units and
  the left-out result that cannot be calculated all come from that count. The decision
  word does not: the seats signed Inconclusive for any count.
  **[hypothesis — the delivery manager's reading of the script and of the signatures above]**
- **The null-`error` theory of the entry above is wrong.** The row's `error` field is a
  string that defaults to empty (`src/crb/core/ledger.py` line 865,
  `src/crb/server/schemas.py` line 1072), and an empty string passes test (d).
  **[measured — n = 2 source lines, method: `git show` at `7bb03d6c73c8c9e10cbc283049be2ce9740eb19e` by one agent on 2026-11-12; apparatus n/a, a reading of code]**
- **Why nothing caught it.** `docs/API.md` line 565 lists `task` among the payload keys of
  these events. The script's test fixtures copied that shape. The name check of R12 item 5
  looked at the key's name and not at where the product stores it. The provider check
  passed on the same log because `provider` stays in the payload.
  **[hypothesis — the agents' account of 2026-11-12, for the deviation log]**
- **The author's real usable-test rate is not known.** The provider line shows only that in
  each of the 24 `S1` runs at least one author call returned. Some authoring failures did
  happen (five texts in click batches 1 and 2, recorded above), and a row whose authoring
  fails skips the builder. How many of the 120 is not in the filed output.
  **[hypothesis — the agents' reading of the served code; no row was read]**
- **Still reserved to Paul.** A corrected count needs a second look at the product after
  filing: the `S1` rows whose `error` begins `authoring:`, or the script with the one-line
  mend. Neither is done without Paul's written word.
  **[hypothesis — the read-once rule of the registration, as the seats read it]**
- **When the read started.** The entry of Part E item 2 gives the time the output was last
  written, which is the end of the read. The session's transcript logs the terminal call
  that started the script at 12:53:13Z, after the push at 12:53:05Z.
  **[hypothesis — one timestamp in the delivery manager's session transcript, which is not in this repository]**

## 2026-11-12 — Deviation log entries, entered after the read

The entries of 2026-11-12 above name three misses "for the deviation log". They are entered
here. Each is a miss in how the read was prepared. None is a change to a filed result, and
none changes the decision word, which the seats signed for any count.

- 2026-11-12, the delivery manager. **The read script looked for an event's task where the
  product does not store it.** R12 item 2 of the registration and `docs/API.md` line 565
  name `task` as a payload key. The product stores it as the event's top-level `task_id`.
  The script reads the payload for both the start event and the failed event, so tests (b)
  and (c) of R12 could not pass for any attempt. The script's fixtures copied the
  documented shape, and the name check of R12 item 5 looked at the key's name only. No
  check against the served shape of an event was made before the read. The output's
  "usable tests: 0 of 120", its 12 author-hit labels, its two-unit blocks result and its
  left-out result all rest on this.
  **[hypothesis — a deviation of preparation, recorded by the delivery manager from the entry "Why the output says usable tests: 0 of 120" above; no row was read]**
- 2026-11-12, the delivery manager. **A consistency figure was taken out of the script
  before it was committed.** The figure counted clean `S1` rows that the script held to be
  without a usable test. On the filed output it would have been above zero wherever an `S1`
  row was clean, and that would have shown the fault at once. It was removed so that no
  figure outside R12 was printed. The removal was the delivery manager's decision and was
  not put to a seat.
  **[hypothesis — a deviation of preparation, recorded by the delivery manager from the seats' account in the signatures entry above]**
- 2026-11-12, the methodologist's seat and the delivery manager. **One rule of the read
  spec was never ruled on.** The spec said a null `error` fails test (d) of R12. The
  registered words are "does not begin with `authoring:`". The methodologist's signed
  readings do not cover the rule, and the delivery manager did not ask for a reading. The
  rule turned out not to bite, because the product serves an empty string and never a
  null. It is logged because a spec rule reached the script without a signed reading.
  **[hypothesis — a deviation of process, recorded by the delivery manager from the seats' statements of 2026-11-12 and the two source lines cited above]**
- **What the next registration takes from these.** A named event key is checked against
  the served shape of one real event before the read script is committed. A consistency
  figure may be removed only with a seat's signed word. Every rule of a read spec is
  listed against the signed reading that covers it.
  **[aspiration — the delivery manager's proposal for the next registration; nothing is registered yet]**
