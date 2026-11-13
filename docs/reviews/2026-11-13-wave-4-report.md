# Wave 4 — the report — 2026-11-13

DRAFT — Paul's audit of ten is in (2026-11-13); not final until the TO FILL lines are closed.

**Status.** The Wave 4 primary read was run once, at 12:53Z on 2026-11-12, and filed its output.
The decision word is *Inconclusive*. The review draw was made once, on 2026-11-12. When the wave
record's last entry was written, no patch had yet been shown to the reviewer (WRN, "The review
draw is made"). The blind reviewer has since given a verdict on each of the 37 labels; the
delivery manager sealed them by 01:53Z on 2026-11-13 (the delivery manager's file times, not
filed in this repository). Paul's audit of ten came in by 09:04Z on 2026-11-13, so section 7 now
gives verdict counts by arm. Nothing
in this draft states one label's verdict or maps a blinded label to an arm **[hypothesis — read
from `wave-record-notes.md` (Part E, "Read run once") and `primary-read-output.txt` line 60, both
under `docs/reviews/2026-11-10-wave-4-registration/`; the rows they rest on are not in this
repository]**.

**Authority.** [The Wave 4 registration](2026-11-10-wave-4-registration.md) and its Amendments 2
to 4; Paul's written answers as the registration and the wave record quote them.

**Claims in this record.** Every figure is read from a named file. Short names used below:

- PRO = `docs/reviews/2026-11-10-wave-4-registration/primary-read-output.txt` (the filed read).
- RDO = `docs/reviews/2026-11-10-wave-4-registration/review-draw-output.txt` (the filed draw).
- WRN = `docs/reviews/2026-11-10-wave-4-registration/wave-record-notes.md` (the wave record).
- REG = `docs/reviews/2026-11-10-wave-4-registration.md` (the registration and its amendments).
- RRR = `docs/reviews/2026-11-10-wave-4-registration/r5-read-script-readings.txt`.
- ACR = the auditor's close re-check, `wave-4-close-recheck.md` (not in this repository).
- SC1 and SC2 = the served checks `served_check.out.json` and `served_check2.out.json` (not in
  this repository).
- ERR = the delivery manager's `error-classes.md`, 2026-11-13 00:28Z (not in this repository).

The rows behind every figure live in the product's ledger, which is not in this repository, so
each figure is tagged `[hypothesis]` with that reason (DL-088). The runs are at apparatus 2.5 (54
of 55 served runs; one blank, likely `98fe708c`) (SC1 item7; ACR anomalies), by `claude_code`
with `claude-sonnet-5` (SC1 item7). `clean` is a mechanical result, not proof that a patch is
right. Every cost figure is in product dollars, unconfirmed: no provider Console export is in hand.
**[hypothesis — SC1 and ACR; the served runs are not in this repository]**

## Summary for Paul

The result is **Inconclusive** **[hypothesis — PRO lines 43-60 and WRN, the signatures under
Part E; the rows are not in this repository]**.

- **Why the paired result does not decide it.** Over 12 batches and 60 commits, S1 minus A0 is
  d = -45.8333 points, with p = 4/4096 = 0.0009765625, below 0.05 (PRO lines 44-46). The method
  is the registered exact two-sided sign-flip test that flips whole batches: 12 batches give
  2^12 = 4,096 sign patterns, and p is the share that qualify (REG A6). The interval is
  -58.6725 to -32.9942 points (PRO line 47). It is the registered 95% interval for the mean
  per-commit difference, built from batches: the estimate plus and minus its standard error
  with each batch as one unit, times t = 2.2010, the 97.5% point of Student's t with 11 degrees
  of freedom (12 batches less one) (REG, the registered analysis, item 2, "The interval").
  Both seats read it this way.
  The primary p is below 0.05 with S1 behind. *Cleared* needs S1 ahead. *No 15-point effect*
  needs a p not below 0.05. Neither is reachable, so the word is *Inconclusive* for any count
  (WRN, signatures entry) **[hypothesis — PRO lines 44-47; the rows are not in this
  repository]**.
- **First ground: the blocks result.** The units found are 2 (click-1 to click-6 as one, cobra-1
  to cobra-6 as one). With 2 units, p = 2/4 = 0.5, not below 0.05 (PRO lines 49-55). Two units
  can never give a blocks p below 0.5; at least six units are needed before it can fall below
  0.05 (WRN, signatures entry, enumeration by the methodologist's seat). WRN says the next
  registration should say so. The decision line reads "Inconclusive (the blocks result falls on
  the other side of 0.05)" (PRO line 60) **[hypothesis — PRO lines 49-60; the rows are not in
  this repository]**.
- **Second ground: the left-out result** "cannot be calculated" (PRO lines 56-57). The output
  prints one ground, the blocks result. The seats name this as the second (WRN, signatures)
  **[hypothesis — PRO lines 56-57; the rows are not in this repository]**.
- **Both grounds rest on a faulty count.** The two units of the blocks result and the left-out
  result that cannot be calculated both come from the same faulty usable-test count (section 2).
  The decision word does not: the seats signed Inconclusive for any count (WRN, "Why 0 of 120",
  "What follows from it"; the deviation entry after the read) **[hypothesis — WRN; the events
  are not in this repository]**.

What *Inconclusive* means: the registered rule for *Cleared* or *No 15-point effect* was not met,
so the wave makes neither claim. What it does not mean: it is not a finding that S1 is worse, nor
that test-first does not help. The report may describe that S1 as served had fewer clean rows than
A0 on these 60 commits. It says nothing about test-first as such (WRN, the validity engineer's
signature) **[hypothesis — PRO line 45; the rows are not in this repository]**.

**Stop (b) and the pilot-gate waiver** (REG Part D item 4 asks for these on the first page)
**[hypothesis — REG Amendment 2 and Part D, PRO lines 65-69; the rows are not in this
repository]**:

- Stop (b) under three readings: strict, 0; `git stash` only, 2, the count the methodologist
  signs; every refused read-only git command, 4, under which the stop would have fired (REG Part
  D; PRO lines 65-68).
- "A reader who holds the widest reading should treat every Wave 4 result as coming from a wave
  that passed its stop (b) on the operator's decision, made after 110 pooled rows were seen."
  (REG Part D item 4.)
- Both pilot gates failed and Paul waived them (REG Amendment 2; section 4). "A reader who holds
  that the gate should have stopped the wave should read every result below as coming from a wave
  that started on the operator's waiver." (REG Amendment 2.)

Also on this page **[hypothesis — PRO line 59, WRN "Why 0 of 120", ACR item 13; the rows and
the campaign record are not in this repository]**:

- "usable tests: 0 of 120" (PRO line 59) is a counting fault in the read script, not a measured
  rate. The corrected count is reserved to Paul and is not computed here. The test author's success
  rate is therefore unknown (section 2).
- Spend is $48.115522 of the one $95 line, product dollars, unconfirmed (section 5).
- Click `S3` is not yet filed: 0 of 6 runs (section 11).
- Section 12 lists the open decisions.

## 1. The primary result

The read ran once, at 12:53Z on 2026-11-12, from main `07125be0`, with exit 0 and no deviation
file (WRN, Part E). The read script's sha256 is `8b9bb6af…7a25` (PRO line 1). It read the campaign
`cmp_88cf9e875edba15371e6d3f7` (PRO line 2) **[hypothesis — PRO and WRN; the rows are not in this
repository]**. Its checks:

- Order check passed (PRO line 25).
- For all 49 runs the product's `s1` flag agreed with the body's `arm` (PRO line 26).
- Test author provider shown as cerebras on 24 of 24 standing S1 runs (PRO line 28). This shows
  only that in each of the 24 S1 runs at least one author call returned. The provider check
  passed on the same log because `provider` stays in the payload (WRN, "Why 0 of 120").
- Rows read 240 of 240, rows missing 0; first filing `98fe708c` set aside unread, 0 rows
  (PRO line 29).

Batch sums S (S1 minus A0), in filing order (PRO lines 31-42):

| Repository | Batch 1 | Batch 2 | Batch 3 | Batch 4 | Batch 5 | Batch 6 |
|---|---|---|---|---|---|---|
| click | -3.5 | -2.5 | -2.5 | 0 | -1.5 | -2.5 |
| cobra | -1.0 | -3.5 | -2.5 | -3.0 | -2.5 | -2.5 |

Every batch line reads "without usable test 10/10; author-hit yes" (PRO lines 31-42). Batches with
a non-zero sum: 11 of 12 (PRO line 58) **[hypothesis — PRO; the rows are not in this
repository]**.

| Result | Units B | Commits N | T | d (points) | p | Below 0.05 | Interval (points) | Upper end below 15 |
|---|---|---|---|---|---|---|---|---|
| Primary (PRO 43-48) | 12 | 60 | -55/2 | -45.8333 | 4/4096 = 0.0009765625 | yes | -58.6725 to -32.9942 (t 2.2010, df 11) | yes |
| Blocks (PRO 49-55) | 2 | 60 | -55/2 | -45.8333 | 2/4 = 0.5 | no | -98.7762 to 7.1096 (t 12.7063, df 1) | yes |
| Left-out (PRO 56-57) | — | — | — | — | cannot be calculated | — | — | — |

The read's own caveats, as filed (PRO lines 61-64): no error rate is quoted for the call; under
option B the claim covers both repositories together, never either alone; the interval is
approximate and is a description, not a second test. The t points below 11 degrees of freedom are
rounded up to 4 decimals, which can only widen an interval (RRR item 5). Served times were compared
as instants at the precision the record serves, with no tolerance (RRR item 7). `created` is
served to the microsecond (for example 18:05:19.131087+00:00) and `finished` to the whole second
(for example 04:09:02+00:00) (SC1 item9). A `finished` served to the whole second can fail (f) or
(g) against a `created` in the same second. That failure would be a stop under test (i), not a
reason to add a tolerance (RRR item 7). The fixed settings were compared only where a kept body
carried them; no test required every body to carry them all, and settings the product does not
serve back (env_stop, outage_stop, learning) were not compared (RRR item 6; PRO line 24)
**[hypothesis — PRO, RRR and SC1; the rows are not in this repository]**.

The 48 standing run ids came from the delivery manager's slot-free run ledger, built from the
poster's out files. Their list sha256 is `b79c3cbe…edf3d`. Test T4 is a consistency test against
that ledger, not an independent one; independence rests on tests (a), (b) and campaign membership
(PRO line 27; RRR item 10) **[hypothesis — PRO and RRR; the rows are not in this repository]**.

Amendment 2 says the report will give Amendment 2's commit "and the time of every run beside it"
(REG Amendment 2, opening paragraph). The commits are in section 9, item 10. TO FILL by the
delivery manager: the filing time of every wave run beside Amendment 2's commit, from the served
run records (Amendment 2 preamble).
**[hypothesis — REG Amendment 2; the run records are not in this repository]**

Per-arm description tables that Part 6 item 6 asks for (per-cell results, `S3` against the blind
arms, attempt agreement): TO FILL by the delivery manager: the by-arm description tables of
REG Part 6 item 6, from served rows after Paul's audit is in.

## 2. "usable tests: 0 of 120" is a counting fault

The read printed "usable tests: 0 of 120 (nine in ten = 108)" (PRO line 59). That figure is not a
measurement. The script's `keep_event` reads the task from `payload["task"]`. The product moves the
task to a top-level `task_id` (events.py line 350) and serves it there (runs.py lines 298-302). So
test (b) of R12 fails on every attempt, and test (c) fails on every attempt of any run that holds
a `builder.author_test.failed` event. The theory that a null error field caused it is wrong: the
field is an empty string (ledger.py line 865, schemas.py line 1072). The wrong key came from
docs/API.md line 565 as it stood at commit `7bb03d6c` (the `builder.author_test` row, which
listed `task` as a payload key; the row has since been corrected and now names `task_id` on the
envelope) (WRN, "Why 0 of 120") **[hypothesis — WRN; the events are not in this
repository]**.

- The decision word does not rest on the usable count. The seats did not sign 0 of 120 (WRN,
  signatures).
- The corrected count is reserved to Paul. It is not computed here (WRN; ACR item 4).
- The test author's success rate is therefore unknown.
- "without usable test 10/10" and "author-hit yes" on every batch line (PRO lines 31-42) come from
  the same lookup and carry the same fault.
- The two units of the blocks result and the left-out result that cannot be calculated both come
  from the same faulty count. The decision word does not: the seats signed Inconclusive for any
  count (WRN, "What follows from it"; the deviation entry after the read).

## 3. Stop (b)

Stop (b) was read on the first 40 builds, click batches 1 and 2, at 2026-11-11 23:0xZ. Those
builds held nine errors: 5 authoring not-RED, 2 `git stash`, 1 `git log`, 1 `git show`. There was
no outage, provider or container error (WRN, stop (b) note). The served check shows 9 errors in
the first 40 rows: 5 not-RED, 2 stash, 2 log or show (SC1 item5; ACR item 5) **[hypothesis —
WRN, SC1 and ACR; the rows are not in this repository]**.

Amendment 2, written before the wave, said of the pilot's refused `git stash list`: "that is 'an
allowed command refused' in spirit", and "the wave's stop (b) still counts every refused allowed
command" (REG Part D, quoting Amendment 2).

The three readings, as Amendment 3 Part D records them (REG Part D; PRO lines 65-68):

| Reading | Count | Does the stop fire? |
|---|---|---|
| Strict | 0 | no |
| `git stash` only (the count the methodologist signs) | 2 | no |
| Every refused read-only git command | 4 | yes |

The strict reading was applied by the delivery manager during the click runs and "first reported
to Paul as 0, without the other two" (REG Part D). The methodologist raised the ambiguity. Paul
was then shown all three counts and answered "Happy to proceed with the [recommendations]" (REG
Part D; WRN). The methodologist does not sign the strict count of 0 as the only reading the text
supports; the count the seat signs is 2 (REG Part D, the methodologist's position).
**[hypothesis — REG Part D and WRN; the rows are not in this repository]**

The strict reading was decided after 110 pooled click builds were seen. A reader who holds the
widest reading should treat every Wave 4 result as coming from a wave that passed its stop (b) on
the operator's decision (PRO line 69; WRN) **[hypothesis — REG, PRO and WRN; the rows are not in
this repository]**.

## 4. The pilot-gate waiver and the cost-gate word

Amendment 2 records the pilot: $3.047552, product dollars, unconfirmed. The harness gate failed (2
of 18 fails) and the cost gate failed. Claude Code first reported the harness gate to Paul as 1 of
18, "which was wrong against the text" (REG Amendment 2). On the cost gate Paul wrote "Don't
blockthings for spend innaccuracies, its minimal cost just keep pushing" (spelling as filed). On
the harness-reason gate Paul wrote "proceed without a repeat pilot" (REG Amendment 2). So the wave
started with both gates recorded as failed, not as passed and not redefined. "A reader who holds
that the gate should have stopped the wave should read every result below as coming from a wave
that started on the operator's waiver." (REG Amendment 2) **[hypothesis — REG; the pilot rows are
not in this repository]**. Amendment 2 then fixed the turn limit at 50, N at 62, k at 15 and the
wave at 60 commits (REG, Amendment 2).

The cost gate before cobra spend was not held in order. Cobra started at 23:28Z on 2026-11-11
without it. The reconciliation was done on 2026-11-12, over both stages, and was one-way only, not
three-way (REG Part E item 2; annex row D5). The annex word "passed" for D5 was withdrawn (REG
Amendment 3 annex, note 1) **[hypothesis — REG Part E and the Amendment 3 annex; the spend rows
are not in this repository]**.

The cost gate before the read was closed by Paul before 12:52Z on 2026-11-12 with the words "read
may go ahead on product dollars, unconfirmed" (WRN, Part E). It is deferred, not passed
**[hypothesis — WRN Part E; no provider Console export is in hand]**.

## 5. Spend against the $95 line

All figures are product dollars, unconfirmed **[hypothesis — SC1 "campaign"; ACR item 13; REG
Amendment 3; WRN second restart; the campaign record is not in this repository]**.

| Figure | Amount | Source |
|---|---|---|
| The line | $95 (product dollars, unconfirmed) | SC1 campaign; REG |
| Spent, final | $48.115522 (product dollars, unconfirmed) | SC1 campaign; ACR item 13 |
| Left | $46.884478 (product dollars, unconfirmed) | SC1 campaign |
| Of which authoring | $0.174468 (product dollars, unconfirmed) | SC1 campaign |
| Run rows, wave (49 runs) | $42.575859 (product dollars, unconfirmed) | SC1 campaign |
| Run rows, `S3` (6 runs) | $2.324046 (product dollars, unconfirmed) | SC1 campaign |
| Run rows, pilot (3 runs) | $3.04115 (product dollars, unconfirmed) | SC1 campaign |
| Run rows, sum (58 runs) | $47.941055 (product dollars, unconfirmed) | SC1 campaign |
| Spent less `S3` (= F1) | $45.791476 (product dollars, unconfirmed) | ACR item 13; REG Amendment 3 A1 |
| Spent before the first cobra run | $28.848331 (product dollars, unconfirmed) | WRN second restart |
| Unexplained residue | $0.006403 (product dollars, unconfirmed) | ACR item 13 |

"Final" spend covers cobra `S3` only. Click `S3` is not filed, so it is not in the figure (ACR
item 13).

The residue of $0.006403, product dollars, unconfirmed, is not explained. The auditor's likely
cause is the pilot S1 author's $0.006401, product dollars, unconfirmed: the pilot run costs,
$3.04115 (product dollars, unconfirmed), are $0.006402 (product dollars, unconfirmed) short of the
$3.047552 (product dollars, unconfirmed) that Amendment 2 records (ACR item 13). This is not shown.
The run-row authoring sum reads $0.174469, product dollars, unconfirmed, against $0.174468 in the
campaign figure, a one-millionth rounding (SC1; ACR anomalies). Amendment 3 also records a
$0.067900, product dollars, unconfirmed, gap in author spend (REG Amendment 3) **[hypothesis —
ACR, SC1 and REG; the campaign record is not in this repository]**.

How far the product's prices can be trusted is open. For the pilot builds, the product priced the
builder rows at $3.041150 (product dollars, unconfirmed). The Claude Code CLI's own total for the
same builds was about $7.60 (the CLI's own price list; like the product dollars, unconfirmed), 2.5
times as much. Fix 4 (PR #115) set the CLI's price list aside in favour of the product's table
(REG Amendment 2, "The cost gate"). Which figure the provider's bill matches is not known. No wave
figure is worked out here at CLI prices.
**[hypothesis — REG Amendment 2; no provider bill is in hand]**

The provider Console exports are not in hand. Checking product figures against them is reserved
to Paul (ACR item 12).

## 6. Error classes

The delivery manager classed the 55 error rows without arm (ERR). None is marked clean, so each
counts as a miss (SC1 item6; ACR item 6). There were 45 author-gate refusals and 10 protocol stops
(ERR) **[hypothesis — ERR and SC1; the rows are not in this repository]**.

| Class | click | cobra | Total |
|---|---|---|---|
| A1 held-out path | 0 | 2 | 2 |
| A2 passes at parent | 15 | 8 | 23 |
| A3 failed without attributable test ids | 0 | 15 | 15 |
| A4 no test it defines fails | 0 | 5 | 5 |
| P1 `git stash` | 5 | 1 | 6 |
| P2 `git log` / `git show` | 3 | 1 | 4 |
| Total | 23 | 32 | 55 |

Source: ERR. The click and cobra totals match SC1 item6. For cobra, ERR's split (30 author-gate,
2 protocol) matches the product's own `failure_kind` labels (authoring 30, protocol 2) (SC1
item6).

**The open A3 question.** The author gate sits at adapter.py lines 1110-1140. Go tests may not
compile at the parent commit, so a cobra A3 refusal may be the instrument's miss, not the author's.
It is not settled. Settling it needs the stored parent output, and that look is not yet done (ERR)
**[hypothesis — ERR; the stored output is not in this repository]**. Only S1 builds have an author
(WRN, the deviation entries before the read), so author-gate refusals occur only on S1 builds.
Until the A3 question is settled, it could bear on how the cobra rows are read. No size is claimed
for that here.

ERR says the split by arm "goes in the wave report from the key file" (ERR, Limits). This report
follows ERR on the source. TO FILL after Paul's audit, from the key file: the error classes split
by arm.

## 7. The review

The draw, as filed **[hypothesis — RDO, WRN and REG; the patches are not in this repository]**:

- The draw was made once, on 2026-11-12 (WRN, "Draw made"). RDO prints no time. The delivery
  manager's copies of the three draw files carry the file time 23:37Z; no filed source holds it.
- The draw script was merged in PR #136 at `9ccc6ee9`, run once, exit 0. Its output sha256 is
  `91a15562…`, 53 lines (WRN, "Draw made").
- Click: 17 drawn of 20, shortfall 3. Cobra: 20 drawn of 20. 37 labels in all (RDO lines 52-53).
- Clean rows that carry an error, wave-wide: 0 (RDO line 51).
- Review list sha256 `6fa535d0…`, key file sha256 `c79a0815…`, audit file sha256 `9990eb80…`
  (RDO lines 47-49).
- When WRN's last entry was written, no patch had been shown to the reviewer (WRN, "Draw made").
  Since then the reviewer has given 37 verdicts, one per label, sealed by the delivery manager
  by 01:53Z on 2026-11-13 (file times; not filed in this repository). They stayed sealed until
  Paul's audit was in.
- Paul's audit of ten is in. "Paul checks five" in Part 6 item 8 is read as ten (REG, R8).
  Paul's audit file uses a second salted order; only the longest unbroken checked run counts (WRN).
  Paul gave all ten verdicts on the audit page between 09:01Z and 09:04Z on 2026-11-13 (the
  page's own save times), without the arm or the reviewer's verdict shown. The delivery manager
  recorded them at 09:04Z and only then compared them. Shortfall: 0 of 10.

The figures below were counted by the delivery manager on 2026-11-13 from the key file, the 37
sealed verdict files and Paul's ten verdicts. Method: join on the blinded label, then count.
None of the three sources is filed in this repository **[hypothesis — the key file, the reviewer's
verdict files and Paul's verdicts are held by the delivery manager, not in this repository]**.

Reviewer verdicts by arm, clean drawn patches only (37):

| Repository | Arm | Drawn | Merge as is | Merge with small edits | Do not merge |
|---|---|---|---|---|---|
| click | A0 | 10 | 1 | 9 | 0 |
| click | S1 | 7 | 0 | 7 | 0 |
| cobra | A0 | 10 | 9 | 1 | 0 |
| cobra | S1 | 10 | 6 | 3 | 1 |
| both | A0 | 20 | 10 | 10 | 0 |
| both | S1 | 17 | 6 | 10 | 1 |

These rows describe the patches that passed the tests and were drawn. They are not a comparison
of the arms: an arm with fewer clean rows puts fewer, and differently chosen, patches in the draw.

B2 item 3 counts and step counts, by repository and arm (key file; RDO line 50):

| Repository | Arm | Step 1 | Step 2 | Step 3 | Drawn of 10 | Shortfall |
|---|---|---|---|---|---|---|
| click | A0 | 5 | 5 | 0 | 10 | 0 |
| click | S1 | 5 | 0 | 2 | 7 | 3 |
| cobra | A0 | 10 | 0 | 0 | 10 | 0 |
| cobra | S1 | 10 | 0 | 0 | 10 | 0 |

Clean rows that carry an error: 0 in each of the four rows.

Paul's audit agreement with the reviewer: 8 of 10 the same verdict, 2 of 10 different. B3 allows
the count of agreement and nothing more, so no further split is given here.

Beside the agreement row: R9 holds in what Paul and the reviewer are told, and not against a
reader who works the public B3 hash (WRN, review draw rules; see below).

**The click shortfall.** Click has 3 fewer clean patches to draw than its 20 slots (RDO line 52).
The draw takes only clean rows, so the review has 37 labels, not 40 **[hypothesis — RDO; the
rows are not in this repository]**.

**The residual B3-hash leak.** The reviewer's labels come from a salted sha256 whose salt sits
only in the key file (WRN, reading 1). The leak comes from B3's audit hash, which is public and
takes the arm as input. On made-up tables, with no wave data, guessing each audited patch's arm
from its smaller audit hash was right for 3170 of 4000 audited patches, in 400 made-up tables,
against 2000 by chance. Separately, ranking labels by their commit's smallest audit hash found
Paul's patches at a precision of 0.478, against 0.250 by chance, over 400 made-up tables with no
wave data. That is a guess at which patches Paul checks, not at an arm. R9 holds in what Paul and
the reviewer are told, not against a reader who works the public hash. The next registration
should salt the audit order (WRN, review draw rules) **[hypothesis — WRN; the draw trials are not
in this repository]**.

**Repeated commits.** The same commit appears under more than one label. In click, `ecb99836` and
`6de21215` appear 3 times each, and `b36e3ede`, `ac6a2acf` and `becbde5c` 2 times each. In cobra,
each of the 10 commits appears 2 times (RDO lines 10-46). No source I read says whether any two
drawn patches are identical in content. TO FILL by the delivery manager: whether any drawn patch
pairs are byte-identical **[hypothesis — RDO; the patches are not in this repository]**.

## 8. Deviations

**The deviation log (REG Amendment 3 annex), row by row, with its Effect column** **[hypothesis
— REG annex; the events it records are not in this repository]**:

1. **D1** (2026-11-11). Both pilot gates failed and were waived by Paul. Registered text: Part 5.
   Effect: recorded in Amendment 2.
2. **D2** (2026-11-11). Stop (b) read under the strict reading on Paul's decision, after 110
   pooled click rows existed; counts 0, 2, 4 recorded. Registered text: Part 6 item 9. Effect:
   wave continued; a reader holding the widest reading treats the wave as passing stop (b) on the
   operator's decision.
3. **D3** (2026-11-11). Click-3/1 (`98fe708c`) failed at gold control, with 0 rows and $0.00
   (product dollars, unconfirmed); the cause was not diagnosed. Batch 3 was filed again once.
   Registered text: Part 2 row rule. Effect: within the rule (REG annex and the notes beside it).
4. **D4** (2026-11-11). Runs from click-3/1 onward were filed by the `svc-claude` operator
   account. A poster crash and a login-verify timeout came before batch 3, with no run lost.
   Registered text: none. Effect: none on rows.
5. **D5** (2026-11-11). Cost gate before cobra not held in order; done after both stages.
   Registered text: topology section 3 task 2. Effect: order only. The row's word "passed" was
   withdrawn (annex, note 1; section 4).
6. **D6** (2026-11-12). Seat-facing ledger carried slot labels, so the arm could be worked out.
   Registered text: wave rule. Effect: no seat combined them; fixed for later ledgers (REG Part E
   item 7).
7. **D7** (2026-11-12). Cobra `S3` filed after the blind runs; click `S3` deferred to the next
   granted restart. Registered text: Part 2 run order, Amendment 2. Effect: `S3` is description
   only.
8. **D8** (2026-11-12). Costs are product dollars; the provider's bill is not yet compared.
   Registered text: Part 3. Effect: labelled "product dollars, unconfirmed" everywhere.

**Entries in the wave record, before the read** **[hypothesis — WRN and RRR; the records they
cite are not in this repository]**:

9. **Blinding slip, the spec writer.** On 2026-11-12, before the read, the spec writer read a
   passage of the wave record that holds run-level error texts. This was outcome-level text by
   run that names the arm. It was joined to nothing (WRN; RRR item 12).
10. **Blinding slip, the methodologist.** After a session break the whole of WRN came back into
    the methodologist's context. That is the same text the ruling's section 0 already records for
    this seat, seen a second time. Nothing was computed from it (WRN; RRR, the signature block).

**Entries in the wave record, after the read** (WRN, "Deviation log entries, entered after the
read"):

11. **The task-key lookup.** The read script looked for an event's task where the product does
    not store it. This produced 0 of 120 (section 2).
12. **The consistency figure.** A figure that counted clean S1 rows the script held to be without
    a usable test was taken out before the script was committed. On the filed output "it would
    have been above zero wherever an `S1` row was clean, and that would have shown the fault at
    once". "The removal was the delivery manager's decision and was not put to a seat." (WRN.)
13. **The null-error spec rule** was never ruled on. It turned out not to bite (WRN).
14. **What the next registration takes from these** (WRN). A named event key is checked against
    the served shape of one real event before the read script is committed. A consistency figure
    may be removed only with a seat's signed word. Every rule of a read spec is listed against
    the signed reading that covers it.

Entries 11 to 14 **[hypothesis — WRN, the entries after the read; the events are not in this
repository]**.

The read script's other departures from the spec are recorded in its opening text (WRN, "Decisions
of the delivery manager after the code check").

**Entry in the wave record, before the draw:**

15. **Paul's audit file** uses a second salted order, not the B3 sequence (WRN, review draw
    rules).

**Other matters the sources say the report must state** **[hypothesis — ACR and REG; the records
they cite are not in this repository]**:

16. **D1 to D8 were committed together, late.** They went in at 2026-11-12T04:03:45Z, 5 to 10
    hours after the events, not as rule 8 requires (ACR item 10).
17. **Amendment 4 spelling.** Spelling A (`editblock:gpt-oss-120b`) was used. The delivery manager
    saw the value before the documents were searched. Spelling B would have failed all 24 S1 runs
    (REG Amendment 4).
18. **A git fetch.** Auditor A ran a `git fetch`, against the rules (ACR anomalies).
19. **A second deviation log** exists in the AthenaClaude repository on a local branch. Whether
    that branch has been pushed was not checked (ACR item 10).

A second stack restart, granted once by Paul, changed the cobra builder image. The served commit
and the apparatus were unchanged (WRN). It is not a row of the deviation log.

## 9. The auditor's findings

The auditor re-checked 14 items (ACR). Items 1 and 2 were "partly shown" in ACR and are now shown
from served data on 2026-11-13 (SC2) **[hypothesis — ACR, SC1 and SC2; the served data is not in
this repository]**. ACR was written before SC2 and does not cover it. No auditor has re-run SC2.
The delivery manager ran SC2 at 05:55Z on 2026-11-13, signed in to the served product as
`svc-claude`, with read-only requests. That is the checked party checking itself. ACR's
step 6 for item 1, created times against
posted times to within seconds, is not in SC2.

| # | Item | Verdict | What decides it |
|---|---|---|---|
| 1 | Arm order of the 12 batches | Shown from served data on 2026-11-13 | SC2: 12 of 12 batches match the Amendment 2 order by served filing time; filed in table order |
| 2 | The refile keeps its arm; batch 3 keeps its order | Shown from served data on 2026-11-13 | SC2: click batch 3 set-aside and standing ids check |
| 3 | Arm labels and pairing | Shown | SC1 item3: 120 rows S1, 120 rows A0, 120 pairs of 2 rows |
| 4 | Usable-test count | Not done | Reserved to Paul |
| 5 | Nine errors of the first 40 | Partly shown | Matches Part D, but by text matching; log and show are lumped |
| 6 | Every error row is a miss | Shown | 55 error rows, 0 clean |
| 7 | Settings of the 49 runs | Partly shown | Campaign id, env_stop, outage_stop, learning, author rest on the plan file |
| 8 | `S3` bodies and rows | Partly shown | Cobra: 6 runs, 30 rows, sighted, after the wave; click not filed |
| 9 | No overlap | Shown | 55 runs, 0 overlaps, 18:05:19Z to 04:09:02Z |
| 10 | Git history | Partly shown | Served commit not shown by git; log not kept as rule 8 asks |
| 11 | Simulations and pool counts | Partly shown | Simulations byte-identical; pool counts not re-runnable |
| 12 | Console against product | Not done | Needs Paul's Console exports |
| 13 | Campaign record | Partly shown | Agrees with F1; residue unexplained |
| 14 | Pool against registered lists | Not shown | Neither script reads the pool |

Further findings, item by item (ACR, SC1, SC2) **[hypothesis — ACR, SC1, SC2 and PRO; the
records are not in this repository]**.

- **Item 1, place.** SC2 now ranks place by the product's filing time. In the local check script
  that ACR reviewed, the arm label was read from the out file. Amendment 4 point 1 allows only the
  run id from an out file.
- **Item 7.** The campaign-id check is weak. ACR says the author provider is not checked; PRO line
  28 shows cerebras on 24 of 24. That line shows only that in each of the 24 S1 runs at least one
  author call returned (WRN, "Why 0 of 120"). One run has a blank apparatus (SC1 item7: 2.5 on
  54, blank on 1), likely `98fe708c`.
- **Item 10, Amendment 2.** It was first pushed as `ca90419a` by 2026-11-11T17:04:04Z, final
  `32630d12` by 17:25:30Z. That is on the PR branch about 40 minutes before the first filing at
  18:05:19Z. It reached main at 2026-11-12T05:13:13Z, about 11 hours after the first filing.
  Auditor B recommends keeping or tagging the branch that holds both commits, since the squash
  merge left them off main.
- **Item 10, code on main.** Three source changes landed on main during the wave.
- **Item 10, the signature.** It is plain text in a commit at 04:03:45Z, after the stop decision
  and after `S3` was posted.
- **Item 11.** The interval simulation models an 18 by 81 layout, not 12 by 5. The re-run used a
  different Python, with byte-identical output. Simulated attempt costs: A0 $0.116644, S1
  $0.274636, product dollars, unconfirmed; N = 62, k = 15.
- **Weaknesses of the audit check scripts (local and served), as ACR lists them.** These are
  weaknesses of the checks, not of the primary read script.
  - The served side never derives place or order from the product's filing order (SC2 now does).
  - The local script reads arm, posting time, "ended cleanly" and cost from the out file, where
    Amendment 4 point 1 allows only the run id. It prints none of the five "Taken on trust" lines
    and no file fingerprints.
  - Times are compared as text. The check would miss an overlap of under a second. The cut-off
    between pilot and wave runs is a fixed text time, `2026-11-11T18:05:00`, chosen after the
    first run was seen.
  - The served campaign check only tests that the id is not empty.
  - Missing values pass as fine. A run with no `counts` record reads as "no stop", so the 55
    "(none)" stop codes do not prove that env_stop and outage_stop did not fire. A missing S1 flag
    reads as A0.
  - Error kinds are read by text matching.
  - The body checks test the plan file, not what was posted.
  - Smaller points: the label check is a subset test; the registered short run ids are never
    asserted; every served value comes through one signed-in session.
  - Both sides of the checks were run and saved by the delivery manager, and the auditors could
    not re-run either.
- **Anomalies:** the actor split is 9 and 46 (SC1 item7; D4 says the switch was from click-3/1
  onward); one blank run; the residue; the one-millionth rounding ($0.174469 against $0.174468 and
  $48.115523 against $48.115522, product dollars, unconfirmed); two cobra rows of kind "other"; 7
  minutes between the last posting and the last finish; the signature after posting; code changed
  on main; the local script takes runs without sorting; Auditor A's `git fetch`.
- **The two "other" cobra rows.** ACR guessed they are the two rows the product labels
  "protocol". ERR classes all 55 rows with none left over. Its cobra split is 30 author-gate and 2
  protocol (P1 1, P2 1), as the product's `failure_kind` labels are (SC1 item6: authoring 30,
  protocol 2). SC1's text matching put 1 cobra row under `git stash` and 1 under `git log` or
  `git show` already. So the counts fit the two "other" rows being ERR's two A1 rows (held-out
  path), not the protocol rows. Rows were not matched one to one.

## 10. Taken on trust

These were not shown, and the result rests on them **[hypothesis — ACR items 5, 7, 10, 11, 14 and
the summary; WRN; PRO lines 18-23; the records are not in this repository]**:

1. **The served commit.** The product served `7bb03d6c73c8…` (WRN, Part E). Git cannot show what a
   running product served (ACR item 10).
2. **The upstream pool counts.** 93 of 212 and 74 of 86 are not in committed code and could not be
   re-run (ACR item 11).
3. **The signature.** It is plain text in a commit, not a cryptographic signature (ACR item 10).
4. **The pool against the registered lists at first filing.** Not shown: neither script reads the
   product's pool (ACR item 14). REG Part E asks that this be stated.
5. **The read's own five trust lines** (PRO lines 18-23): that the poster sent each plan body
   unchanged and in place; that the four input files are as they were at filing (hashes first
   recorded after the wave); whether any tie was made by inference; that `refile.py` filed batch 3
   from the same plan entries; and that one poster text ran for every batch, though D4 records a
   crash before batch 3.
6. **Settings on the plan file alone.** The campaign id, env_stop, outage_stop, learning off and
   the test author rest on the delivery manager's private plan file. The product's run record does
   not carry these fields (ACR summary point 3; item 7).
7. **One run each of the read and the draw.** That each was run only once is the delivery
   manager's statement. "No record kept here can prove that a script was not run." (WRN, the
   primary read entry; the draw entry.)
8. **No arm comparison at stop (b).** "No arm comparison was made" when stop (b) was read is a
   claim about how people behaved. The evidence cannot show it (ACR item 5).
9. **Stop (c).** That the served code stayed `7bb03d6c` rests on a checkout read after the last
   blind run (WRN, Part E item 4). Three source changes landed on main during the wave, one of
   them before the second restart (ACR item 10).

## 11. `S3`

Cobra `S3` is filed: 6 runs, 30 sighted rows, one per commit, all after the wave (SC1 item8; ACR
item 8). "click `S3`: not yet filed" (0 of 6 runs) (REG Amendment 3 Part E; ACR item 8).
Restarting it, or dropping it in writing, is Paul's choice **[hypothesis — SC1, ACR and REG; the
rows are not in this repository]**. The `S3` against the blind arms table is TO FILL by the
delivery manager: `S3` against the blind arms (REG Part 6 item 6).

## 12. Decisions for Paul

Each line says what the choice would buy. No choice is pressed **[hypothesis — WRN signatures,
ACR and ERR; the rows are not in this repository]**.

- **More commits, or not.** More units could make the blocks result decidable. Not running more
  keeps the spend where it is and the word at *Inconclusive*. The two units come from the faulty
  count (section 2), so "two units" may not hold once the count is mended.
- **The corrected usable-test recount.** It would give the test author's real success rate, and
  the batch lines' "without usable test" figures. It could change the units of the blocks result
  and the left-out result. It does not change the decision word: the seats signed Inconclusive for
  any count (WRN).
- **Click `S3`: restart or drop.** A restart would complete `S3` on both repositories, at a cost
  in product dollars, unconfirmed, still to be read. Paul's written word that click `S3` is
  dropped would also close ACR item 8.
- **The provider Console exports.** They would confirm or correct every product-dollar figure,
  including the residue and the gap against the CLI's total (section 5).
- **Two order-check tests.** A new test that every kept body carries every registered fixed
  setting (RRR item 6), and failing a body that sends `arm: "A0"` (WRN; RRR item 8). As
  registered there is no such test, and test (e) accepts `arm: "A0"`. Each is a new registered
  test, so only Paul can add it.
- **The A3 look.** Reading the stored parent output of the 15 cobra A3 rows would settle whether
  those refusals are the instrument's miss or the author's (ERR). It is not yet done. The
  delivery manager's reading: it changes no registered number and adds no test, so it needs no
  new word from Paul; it will be reported as a look made after the read.

## The close

Paul's audit of ten is in. This draft closes when the TO FILL lines are filled from their named
sources, and the decisions above are recorded. Auditor B's recommendation stands open: keep or tag
the branch that holds `ca90419a` and `32630d12` (ACR item 10). Until then it is a DRAFT.
