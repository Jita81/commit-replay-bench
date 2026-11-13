# Wave 5 registration, version 3 (revised after the two checks of 2026-11-13)

**Status.** DRAFT — not signed. Signed by the step-1 commit that merges this file.

Commit Replay Bench (crb). Pre-registration of Wave 5. Written by the statistician and
methodologist seat on 2026-11-13. This text replaces version 2 in full. It is not a diff.
This revision of version 3 closes the R11 check (findings R-F1 to R-F11) and the forking-path
check (FP-H1 to FP-H7, FP-M1 to FP-M7, FP-L1 to FP-L5); the closing table maps each to a section.
It also closes the review of the integrated text (findings RV1 to RV24, in the review's order),
and the second review of the integrated text (findings RR1 to RR24, in that review's order),
both mapped in the same table.

Tags used on every figure, as in Wave 4:

- **[measured — n, method]**: a number read from rows, files or a script, with its method.
- **[hypothesis — basis]**: a number assumed or carried from elsewhere, with its basis.
- **[aspiration — basis]**: a number we aim for, not one we have.

All dollar figures are product dollars, unconfirmed against the provider.

Two sets of decisions by the managing director (MD) are written in. The morning set, D-a to
D-g, was applied in version 2. The afternoon set, called M1 to M9 here, is applied in this
version; where M1 to M9 and D-a to D-g differ, M1 to M9 win. Every point decided by the MD is
marked "decided by the MD 2026-11-13". Where this seat had to choose, the text says so. Where
two check findings conflicted, this seat took the option that leaves fewer human choices once
outcomes are visible, and says so at the place
**[hypothesis — how this text was made; the rulings' messages are not in this repository]**.

**Rulings of 2026-11-13 (09:45Z, the delivery manager deciding as MD).** The last open points
of this version are decided and written in at their places: Q17 (no amendment acts after the
first counted run, in either direction; section 10), Q18 (class `bug.fix`, sizes XS and S;
section 5.2), Q19 (the wave closes 30 days after the first counted run; section 6.2), Q20 (the
$129 line under the operator's standing authority of 2026-11-13; section 0), the item-5
confirmations (the onboarding rule of 5.4, the SPDX allow-list, the L2 full-size bar and the
order of checks; section 5.2), the qualify record as a fact of the code (section 4.1), the A3
rule (section 4.5) and the blind reviewer as an agent session (section 11.2)
**[hypothesis — the MD's rulings file of 2026-11-13 is not in this repository; each ruling is
written in at the place named]**. W0 and W0_CAL are
signed in the freeze record, not now (section 9.3). Section 12 lists every decision.

**Source of the Wave 4 registration.** Every line number quoted here is from
`docs/reviews/2026-11-10-wave-4-registration.md` as on main at `0af1d920`, 1,892 lines, sha256
`6f6d9c9b71712c988e39a3962cc9522400d3bf98c5f887cf55e2822b8746c03e`; the file was last changed
by #131. Decision D3 is at lines 1232-1241, R11 at 1244-1277, C1 at 1279-1305, C2 at 1307-1327,
the untuned guard at 1329-1331, and the commit-list rule (part 2, steps 1 to 3) at lines 167-180
**[measured — n = 1 file, method: sha256 of the file on main and each quoted line number
re-read against the quoted text, apparatus n/a]**.

---

## 0. Status, authority and money

- **Wave 5 is "the next certifying reading"** in the sense of decision D3 (line 1233) and of
  R11 item 2 (line 1255). R11 and D3 therefore bind it in full.
- This registration is a draft until it is committed and its sha256 is recorded. It binds from
  that moment. Nothing in section 4.2 starts before then.
- **The operator is Paul.** Every "operator" in this text is Paul, the person R11 item 7 names,
  as in the Wave 4 registration, which calls Paul's waiver "the operator's waiver" (line 689)
  **[hypothesis — basis: Wave 4 registration line 689 on main `0af1d920`; that the operator
  of the rulings of 2026-11-13 is Paul is this seat's reading, for the delivery manager to
  confirm]**.
- Spend so far on the campaign is $69.98 of a $200 line, so $130.02 is left. The Cerebras
  balance is $44.78
  **[hypothesis — operator's message of 2026-11-13, not in this repository; product dollars,
  unconfirmed; not reconciled with the provider]**. The freeze record quotes the spend figure
  in force at the freeze, with its date and source, beside the authority (step 8a).
- **R11 item 7 (lines 1271-1272): "Any model spend on the repository is a new budget line and
  goes to Paul with a figure."** Wave 5's model spend is a budget line of **$129**. $129 is the
  n = 10 high case of section 7.3, rounded up **[measured — n = 128 commit-arms, method:
  128 × $0.400963 × 2.5 = $128.31, appendix A part 2, apparatus n/a; product dollars,
  unconfirmed]**.
- **The $129 line is committed under the operator's standing authority of 2026-11-13**
  (decided by the MD 2026-11-13, Q20): "take any cost / reset or other action you think is
  necessary to prove the product works, is useful and adds value". The figure was reported to
  the operator on 2026-11-13. No lift is needed: $129 is inside the $130.02 left of the $200
  line. Product dollars, unconfirmed
  **[hypothesis — the operator's words and the report of the figure are quoted from the MD's
  rulings of 2026-11-13; neither message is in this repository]**.
  Read with the bullet above, "reported to the operator" means the $129 figure went to Paul,
  which is what R11 item 7 asks **[hypothesis — this seat's reading of Q20 and R11 item 7;
  confirmed by the delivery manager on 2026-11-13]**.
  The freeze record quotes that authority word for word, names where the quoted message is
  kept, and gives the date the figure was reported to Paul; the report states the line at the
  result. No model money is spent before that quotation is in the record.
- **D3's fallback acts only before the freeze.** If the Question 4 answer (lines 1236-1239) is
  held not to stand, D3's fallback (lines 1239-1241) applies and Wave 5 is recorded as not run
  on any C1 or L2 name, but only if the MD or Paul invokes it in writing, filed before step 10.
  After the freeze such a holding is printed beside the word and does not act (section 10)
  **[aspiration — this registration's design; nothing is run yet]**.
- The only by-arm fact from Wave 4's primary read used in the design is: S1 minus A0 =
  -45.8333 points, exact sign-flip p = 4/4096 over 12 batches (60 commits), 95% t interval
  -58.6725 to -32.9942
  **[hypothesis — the Wave 4 report draft (open PR #141), not on main; n = 12 batches, exact
  sign-flip and t(0.975, 11) = 2.2010; not
  recomputed by either check, because the rows are outside their scope]**.
- One further Wave 4 fact is used, only to fix the claim words of section 1.3: in Paul's audit
  of the blind reviewer, Paul agreed with the reviewer on 8 of 10 patches; both differences were
  S1 click patches that passed the held-out tests and that Paul would not merge
  **[hypothesis — n = 10 audited patches, Paul's B3 audit as reported in MD ruling M9 of
  2026-11-13; the audit is not in this repository]**.
  No Wave 4 result picks, drops or orders a repository or a commit (R11 item 6, line 1269).

## 1. The question, and what a word may claim

### 1.1 The question

On these n repositories, is the builder with a self-authored test (S1, as served, including
its harness) better than, worse than, or within 15 points of the same builder with no authored
test (A0), in the share of attempts that pass the repository's held-out tests?
**[hypothesis — the question H2 asks; nothing is run yet]**

"Clean" below is the row's served `clean` field, which records exactly that: the attempt's
patch passed the repository's held-out tests under the belts. It means nothing more, and it is
never overridden (section 3.1).

### 1.2 Scope rules (decided by the MD 2026-11-13)

1. **The word speaks only of "these n repositories"**, at the commits run.
2. **The population reading is labelled approximate.** Read as a statement about repositories
   in general, the t interval is printed beside the word and labelled "approximate: treats the
   n repositories as a random sample, which they are not". That population reading never
   changes the word. The same 90% interval still decides Within 15 (section 3.3), as a
   registered rule on these n repositories, not as a population claim.
3. **"S1 as served, including its harness".** The S1 arm is the whole served path: the
   Cerebras test author, its prompts, its timeouts, the provider and the builder. A Worse on
   S1 is a statement about that path, not about test-first building as an idea.
4. **Words for the instrument.** The calibration of section 4.1 lets us say the read script
   "reads a known gap correctly on served rows". A wave that ends in Better, Worse or Within 15
   "returned a decision-grade call". "Useful" is kept for a call that would change a default.

### 1.3 Claim words (decided by the MD 2026-11-13, ruling M9)

- Every claim of this wave says "passes the repository's held-out tests". It never says
  "mergeable", "correct", "safe to merge" or "ready". The reason is the Wave 4 audit fact of
  section 0: two test-passing S1 patches out of 10 audited were ones Paul would not merge.
- The blind review and Paul's audit (section 11.2) are a registered secondary. They are
  reported as counts and never change the word.

### 1.4 When the wave can end Undecided

Undecided has two causes, and the text names both:

1. **A small true effect.** At a true effect near 0, Within 15 is reached with probability
   0.549 at n = 10 and 0.027 at n = 6 (τ_e = 0.10)
   **[measured — n = 1,000 simulated waves a cell, method: discrete simulation in appendix A part 4,
   re-run with python3 -I and compared byte for byte, apparatus n/a]**.
2. **Too few repositories.** At n = 6 a Better or Worse needs all six D_r non-zero and of one
   sign, because the smallest reachable p is 2/2^6 = 0.03125 and the next is 4/64 = 0.0625.
   One zero or one dissenter gives Undecided whatever the effect. Within 15 also needs at
   least 6 non-zero repositories. At a true effect of 0 and n = 6, the wave is Undecided with
   probability 0.967, and in 0.771 of waves that is with fewer than 6 non-zero repositories
   **[measured — n = 1,000 simulated waves a cell, method: exact enumeration and discrete
   simulation in appendix A parts 3 and 4, re-run with python3 -I, apparatus n/a]**. So an Undecided
   can come from too few
   repositories, not only from a small effect, and the report says which applies (n' < 6 or
   not).

The registered design (section 7) reaches a correct Worse with probability at least 0.8 at
n ≥ 7 only under the normal model of a Wave-4-sized effect; see section 7.4 for the exact
statements.

## 2. Arms and contrast (decided by the MD 2026-11-13, ruling M1)

- **A0**: the builder (claude-sonnet-5, the registered default) with no authored test.
- **S1**: the same builder, given a test written first by the Cerebras author, as served.

There is one contrast:

| Contrast | Difference per repository | Positive means |
|---|---|---|
| H2 | D_r = S1 − A0 | S1 passes the held-out tests more often than A0 |

J = 1. There is no weak-model arm, no W rule and no H1 in the confirmatory design. The $0
calibrations of sections 4.1 and 4.3 are kept.

## 3. Unit, statistic, test and words

### 3.1 Unit and difference

- **The unit is the repository.** Commits and attempts are nested inside it.
- For repository r, m_r is the number of counted commits (section 6.1): 6 in a full
  repository, from 2 to 6 in a C1 repository with fewer qualified commits (section 5.3), and
  from 1 to 6 for R11's untuned repository if a replacement empties a cell (section 5.7).
- For repository r and arm X, the clean rate is clean rows divided by registered rows, where
  registered rows = m_r × 2 attempts **[aspiration — this registration's design; nothing is run
  yet]**.
- **A row is clean if and only if its served `clean` field is true.** Nothing overrides it. A
  row with a harness fault has no passing verdict, so its `clean` field is not true and it
  counts as a failure for the arm that produced it (section 8.3). Fault types are description
  only, named by the served `error_code` values (section 11.1).
- A registered attempt with no row counts as not clean. This covers an attempt filed with no
  row and an attempt still unfiled at the wave's close (section 6.2).
- D_r = 100 × (clean rate of S1 − clean rate of A0), in points.
- D = the unweighted mean of D_r over the counted repositories. **Every counted repository has
  weight 1, whatever its m_r.** This is the unit rule that covers unequal counts; known-answer
  set K7 tests it.

### 3.2 The test

- Exact two-sided sign-flip test over all 2^n sign patterns of the D_r. The p-value is the
  share of patterns whose |mean| is at least the observed |D|.
- A repository with D_r = 0 flips to itself, so it does not change p. The effective n for the
  test is the number of non-zero repositories, n'. The smallest reachable p is 2/2^n'
  **[measured — appendix A part 3, exact enumeration]**.
- Smallest reachable p: n' = 5 → 0.0625; 6 → 0.03125; 7 → 0.015625; 8 → 0.0078125;
  10 → 0.0019531 **[measured — appendix A part 3, p_min = 2/2^n]**.
- So at alpha 0.05 the floor for Better or Worse is 6 non-zero repositories **[aspiration — this
  registration's design; nothing is run yet]**.

### 3.3 Words

The word is the first that applies, in this order (a partition)
**[aspiration — this registration's design; nothing is run yet]**:

1. **Invalid**: a check of section 9 other than P3 failed, or fewer than 6 whole repositories
   were counted (section 8).
2. **Better**: p < 0.05 and D > 0.
3. **Worse**: p < 0.05 and D < 0.
4. **Within 15**: all three hold: the 90% t interval for D lies inside −15 to +15 points; at
   least 6 non-zero repositories; a usable test in at least 0.9 of S1 attempts filed (P3).
5. **Undecided**: none of the above.

### 3.4 The arithmetic, registered exactly (fixing RR16)

`expect_w5.py` and the read script both implement these rules, so neither can pick its own
**[aspiration — this registration's design; nothing is run yet]**:

- **Exact rationals for the test.** Each D_r is held as the exact fraction
  100 × (cS / R − cA / R), where cS and cA are the integer clean counts and R the registered
  rows an arm: m_r × 2 in counted mode, m_r × 1 in calibration mode (Python
  `fractions.Fraction`; in calibration mode S1 and A0 read `gold` and `empty`). The test sums the
  D_r of each sign
  pattern exactly; a pattern counts when the absolute value of its sum is at least the absolute
  value of the observed sum, compared exactly. p = (patterns counted) / 2^k as an exact
  fraction, and "p < 0.05" is the exact comparison p < 1/20. No tolerance is used.
- **The t interval.** D is the mean of all k D_r, zeros included. s is the sample standard
  deviation of all k D_r, with divisor k − 1. The half-width is t(0.95, k − 1) × s / √k, with
  the quantile of `w5v3_calc.py`, computed in floating point from the exact D_r.
- **Within 15 is strict**: −15 < D − half-width and D + half-width < 15, as `w5v3_calc.py`
  computes it. An interval that touches ±15 does not fit.
- **The output bytes.** UTF-8, LF line endings, one `key: value` line per field in this order:
  `mode`, `k`, `n_nonzero`, `D` (signed, 4 decimals), `p` (exact fraction `a/b`, then 7
  decimals), `half_width_90` (4 decimals), `usable_share` (counted mode only, 4 decimals),
  `word`; then one line per repository in run order, `repo|m_r|clean_A0|clean_S1|D_r`. Floats
  are printed with Python's `format(x, ".4f")` (`.7f` for p); `-0.0000` is printed `0.0000`.

### 3.5 When the primary read happens (fixing RR21)

The primary read runs once, at the earlier of two moments, and not before
**[aspiration — this registration's design; nothing is run yet]**:

1. every registered attempt in the run set has a run id and its run has reached a finished
   status, and the driver has fetched its events; or
2. the close (section 6.2).

No count, clean rate or word of the counted runs is computed before then, by any seat. A
computation before then is recorded and printed beside the word.

## 4. The $0 checks and the order of steps before the first counted run

### 4.1 Gold against empty (decided by the MD 2026-11-13, M1, M4)

- **One record per commit, inside qualify.** The qualify run of step 3 grades each commit
  twice under the belts: at its parent, which is the empty patch, and with the gold patch. Both
  verdicts are fields of its record. That record is R11's "qualified" fact and is also the only
  gold-and-empty record: there is no separate Controls run, no re-run, and the first record is
  final.
- **The record holds both verdicts: a fact of the code.** In `src/crb/core/qualify.py` on main
  at `0af1d920`, the `Qualification` record (line 212) holds `red` (line 226: the kind of RED
  and the failing test ids at the parent, which is the empty-patch verdict) and `gold` (line
  229: `clean`, `lint` and `target_passed`), and `fingerprint_of` (line 189) hashes both
  **[measured — n = 1 file, method: code read of `src/crb/core/qualify.py` on main `0af1d920`
  by the MD and this seat, apparatus 2.5]**. **The served record is checked at step 3**, not at
  the pilot (fixing RR10): a mechanical field-presence test on every served qualify record of
  step 3, before step 4. Each record must carry the fields `state`, `red.kind` and
  `gold.clean`. If any record lacks one, step 3 fails for every name and the wave is recorded
  as not run, with no model money spent **[aspiration — this registration's design; nothing is
  run yet]**.
- **How the two arms are read from the record** (fixing RR24). The record has no `clean` field
  for the empty patch, so the mapping is registered. In `qualify.py` on main `0af1d920` the RED
  kinds are `tests_failed` (the parent's failing test ids are parsed) and `build_failed`
  **[measured — n = 1 file, method: code read of `src/crb/core/qualify.py` on main `0af1d920`
  by this seat, apparatus 2.5]**. The mapping is:
  - **empty** clean = false when `red.kind` is `tests_failed` or `build_failed`, and true
    otherwise;
  - **gold** clean = the record's `gold.clean`;
  - **qualified** = the record's `state` is `qualified`.
  So "finds the `clean` field" below means the gold arm's `gold.clean` and the empty arm's
  `red.kind` under this mapping.
- **The calibration never changes a pool, a list or n.** A commit is qualified when its
  record shows the empty patch not clean and the gold patch clean; nothing else is applied.
- **Why this option** (FP-H5 against R-F2): R-F2 asked for a separate Controls run whose
  disagreements are repaired before the freeze; FP-H5 asked for one gold-and-empty grading
  inside qualify with the first record final. A separate run creates a second record of the
  same fact, and every disagreement then needs a person to decide what was wrong and when it is
  repaired. One final record leaves no such choice, and it cannot remove a commit after n is
  declared. So FP-H5's option is taken, and it also meets R-F2's demand that the Controls never
  change a pool, a list or n.
- **The calibration push.** At step 6 the stored qualify records of every commit on a counted
  list (section 6.1) are pushed through the read script in calibration mode (section 4.4),
  with arms `gold` and `empty`, so each repository's m_r is the same as in counted mode. Expected:
  D_r = +100 in every repository, D = +100, p = 2/2^n, n' = n, 90%
  half-width 0, word Better (n ≥ 6) **[hypothesis — follows from the definition of qualified;
  checked by sha256 of the output at step 6]**.
- **What it shows, plainly.** Because qualified commits have this gap by definition, the push
  does not test the oracle. It shows that the read script finds the `clean` field and the
  verdict fields on real served records and does the arithmetic of section 3. That is why a
  zero clean count may be waived (section 9.3) while a zero usable-test count may not.

### 4.2 The order of steps (decided by the MD 2026-11-13, M4; steps renumbered in this revision)

Each step is done, and its output filed with its sha256, before the next. Every step output is
filed in `docs/reviews/2026-11-13-wave-5-registration/` under the step's number. Steps 0 to 10
cost no model money except the pilot in step 9. All registered attempts, pilot and counted, are
submitted by one driver script (section 6.2), whose sha256 is filed at step 8 and in the freeze
record **[aspiration — this registration's design; nothing is run yet]**.

0. **Before step 1: the A3 repeat** (section 4.5; fixing RR3 and RR19). The delivery manager
   does it, or records that it was not done; either way the record is filed before step 1.
   - **The row, by a fixed rule.** Among the Wave 4 cobra S1 rows whose error contains
     "failed without attributable test ids", the one with the smallest
     sha256("crb.w5.a3|" + task_id + "|" + attempt), as hex, ties by task id. No person picks
     it.
   - **The command.** The authored test kept in that row's served transcript is written into
     the commit's parent tree, and `go test ./...` is run once in the cobra builder image, with
     its exit code, stdout and stderr kept. No model is called, so it is $0 in product dollars;
     if the authored test was not kept, no new one is authored and the repeat is recorded as
     not done.
   - **What counts as proof.** The output proves a compile failure at the parent only if it
     contains the string `[build failed]`. Anything else, or a repeat not done, leaves the gate
     as it is on main.
   - **Filed.** The row id, the authored test, the output and their sha256s.
   **[aspiration — this registration's design; nothing is run yet]**
1. The registration is committed and its sha256 recorded, with the main commit id of that
   merge (the **step-1 commit**). Q18 (the cell class) and Q19 (the close) were decided by the
   MD on 2026-11-13, before this step (section 12).
2. **Configuration first.** For all 23 names, the onboarding configuration is derived by the
   rule of section 5.4, filed with its sha256, and never changed after. The HEAD commit of each
   name used for check 3 is recorded here **[aspiration — this registration's design; nothing is run
   yet]**.
3. **Qualify all 23 names at $0**, once each, in the same executor, image and sealed posture
   as the counted runs, with the step-2 configuration (section 5.2). The step-3 record holds:
   the apparatus version and the other fields the service serves at `/version`; the **deployed
   commit** (section 6.4); the builder image digest of each language and the qualify posture
   id; and the result of the field-presence test of section 4.1. Checks 1 to 8 of section 5.2,
   check 4 included, are all evaluated in this step, and the report of every candidate tried
   and the first check it failed in the registered order is filed here (section 5.6; R11 item
   4, lines 1263-1264), with the class and size labels the product gave every commit
   **[aspiration — this registration's design; nothing is run yet]**.
4. **Declare n, the run set and the run order** (sections 5.3 and 6.2). The run set is closed
   here: no name is added or replaced after this step. If n < 6, stop: nothing is spent and
   the wave is recorded as not run.
5. **Pin the preflight, then compute the lists.** `scripts/read_preflight.py` is pinned as the
   file on main once PR #142 has merged under the normal merge rule (section 9.2); its sha256
   and the main commit id are filed, and a byte copy is filed in the wave-5 folder. Until #142
   is merged, step 5 and every later step wait, and no money is spent. Then the commit lists
   are computed by the seeded order (section 6.1): each cell's **pool list** (its full ordered
   pool, commit ids only), its exact key string, its pool size, its **counted list** and its
   **pilot commit**, each with its sha256. Generate, with a separate script `expect_w5.py` that
   does not import the read script, the byte-exact expected output of the calibration push
   (4.1) and of K1 to K7 (4.3), and file each with its sha256.
6. **Calibrations.** Snapshot the step-3 qualify records of every commit on a counted list to
   a file and file its sha256. Run the read script in calibration mode on that file and on K1
   to K7. Each output's sha256 must equal its filed expected sha256.
7. **Event-key positive control, live dry run and probes** (section 9.2, P5), all at $0, on
   the pinned preflight: snapshot Wave 4's already-served events to a file and file its sha256;
   run the planted script, the unplanted read script, the driver's preflight and every
   conforming probe on it, each with its pass rule of section 9.2.
8. **Budget, campaign and append.** (a) The $129 line is recorded with its authority: Paul's
   standing authority of 2026-11-13, quoted word for word with where the message is kept, and
   the date the figure was reported to Paul (R11 item 7; section 0; Q20). The spend so far of
   the $200 line, quoted from Paul with its date, is recorded beside it, and the **remaining
   line must be at least $129**; if it is not, the wave stops and is recorded as not run. The
   campaign of section 6.2 is registered and its id filed. (b) Re-check every commit on a
   counted list and every pilot commit for a build row and for a recorded read (sections 5.7
   and 6.1) and apply the replacement rule; if any counted list changed, step 6 is re-run on
   the new lists. (c) The pool lists, counted lists, pilot commits, key strings, pool sizes and
   per-list sha256s are **appended to this registration in an amendment commit**, as R11 item 5
   (line 1268) and Wave 4 part 2 step 3 require; the amendment marks the pilot commits as
   struck.
9. **The pilot** (section 6.3), with its pass rule, then the read script's dry run on the
   struck pilot rows. The dry run prints plumbing counts only (section 6.3).
10. **The freeze.** Re-check build rows and recorded reads once more (section 5.7); any
    replacement is appended in a second amendment commit. The remaining line is checked again
    against $129, as at step 8a. **Then steps 6 and 7 are re-run on the exact files whose
    sha256s go into the freeze record**, and every output must pass again; a failure here may
    be repaired and steps 6 and 7 re-run again, before the freeze record is filed. Then the
    freeze record is filed:
    - sha256 of the read script, of the pinned `scripts/read_preflight.py`, of the planted
      script, of each probe, of the driver script, of each configuration, of each list, of each
      expected output, of the qualify-record snapshot and the Wave 4 events snapshot;
    - the outputs of the final step-6 and step-7 runs, with their sha256s;
    - the run bodies of section 6.4, the campaign id and the per-run cost cap;
    - the step-1 commit, the deployed commit and the served `/version` fields of step 3, and
      the diff of the pinned preflight against PR #142's head `7122682`;
    - the amendment commit id(s); the frozen W0 and W0_CAL constants (section 9.3) as signed;
    - the money line ($129) with its authority, the spend figure in force and their dates
      (step 8a);
    - as a diff, any change to the read script or the driver after the pilot.

    Then the first counted run may start
    **[aspiration — this registration's design; nothing is run yet]**.

Before step 10, a failed $0 check of steps 6 or 7, or a failed pilot (section 6.3), may be
repaired and the step re-run, because no counted outcome exists; every repair and re-run is
recorded, and a repair to the read script or the driver after the pilot is filed as a diff in
the freeze record. Qualify (step 3) is never re-run, and the run set (step 4) never changes.
Pilot rows are struck and never counted.
**After step 10 nothing in the freeze record changes.** At read time the calibration push and
K1 to K7 are re-run by re-pushing the stored files with the frozen script (no new Controls or
qualify run), and P5 is re-run on the stored snapshot. A failure of any of them then, or of
P6, makes H2 Invalid, finally, with no repair after outcomes are visible.

### 4.3 Synthetic known-answer sets

The read script is fed these sets in known-answer mode (section 4.4) and its output must match
the filed expected output byte for byte, compared by sha256
**[measured — appendix A part 6, exact enumeration and t quantiles, script w5v3_calc.py]**.

| Set | Input | D | p | n' | 90% half-width | Word |
|---|---|---|---|---|---|---|
| K1 | 8 D_r at −50 | −50.0000 | 2/256 = 0.0078125 | 8 | 0.0000 | Worse |
| K2 | 8 D_r, ±10 alternating | 0.0000 | 1.0000000 | 8 | 7.1608 | Within 15 |
| K3 | 6 D_r: one 0, five −40 | −33.3333 | 4/64 = 0.0625 | 5 | 13.4337 | Undecided |
| K4 | 7 D_r at +30 | +30.0000 | 2/128 = 0.015625 | 7 | 0.0000 | Better |
| K5 | 10 D_r: nine −20, one +10 | −17.0000 | 4/1024 = 0.0039062 | 10 | 5.4993 | Worse |
| K6 | K2's D_r, usable share 0.85 | 0.0000 | 1.0000000 | 8 | 7.1608 | Undecided |
| K7 | rows, unequal m_r (below) | −36.1111 | 2/64 = 0.03125 | 6 | 5.5974 | Worse |

- K3 is Undecided because p = 0.0625 is not below 0.05 and n' = 5 is below 6.
- K6 tests P3: the interval fits and n' = 8, but the usable-test share is below 0.9. P3 bars
  Within 15 only, so the word is Undecided, not Invalid (section 3.3 item 1).
- K7 is given as rows, not D_r, to test the unit rule. Repository 1 has m_r = 2 (4 rows an
  arm): A0 3 clean, S1 1 clean, D_r = −50. Repositories 2 to 6 have m_r = 6 (12 rows an arm):
  A0 9 clean, S1 5 clean, D_r = −33.3333 each. D = (−50 + 5 × −33.3333) / 6 = −36.1111
  **[measured — n = 6 repositories of set K7, method: the known-answer script of appendix A
  re-run with python3 -I, apparatus n/a]**.

### 4.4 The read script's three entry points and row models (fixing FP-H7)

- **Counted mode** (the primary read). Rows are the counted build rows; registered rows per
  arm = m_r × 2; events are fetched and checked by the preflight; every count goes through
  `nonzero` with the frozen W0 (section 9.3).
- **Calibration mode** (4.1). Input is the stored qualify-record file of the counted lists.
  Arms are `gold` and `empty`, read by the mapping of 4.1; there is one row per commit per
  arm, so registered rows per arm = m_r × 1. No events
  are fetched, and the S1-only counts (author events, usable tests, P3) are not computed, so
  `nonzero` is never called on them. Counts that are computed go through `nonzero` with the
  frozen constant W0_CAL (section 9.3), so the `empty` arm's zero clean count is waived by a
  constant, not by a person.
- **Known-answer mode** (4.3). Input is a file of D_r values (K1 to K6, with K6's usable share)
  or rows (K7). It computes the statistic and the word only.
- In every mode the output is plain text whose exact bytes are fixed by `expect_w5.py`; the
  check is a sha256 comparison and needs no reading by a person.

### 4.5 The A3 rule: the author gate's refusals (decided by the MD 2026-11-13)

A3 is the author gate's refusal "failed without attributable test ids" (the authored test is
not shown RED at the parent; `src/crb/builders/adapter.py` line 1139 on main `0af1d920`). In
Wave 4 it refused 15 cobra S1 rows
**[hypothesis — the count is quoted from the MD's rulings of 2026-11-13; this seat did not
recount the Wave 4 rows]**.

- S1 runs exactly as it is on main at the step-1 commit, as deployed at the deployed commit
  recorded at step 3 (section 6.4), which serves the same code.
- The gate is changed before step 1 only if a $0 repeat of one Wave 4 A3 row, keeping the
  parent's output, proves a compile failure at the parent, and the fix merges under the normal
  merge rule before step 1. The row, the command, the proof string (`[build failed]`) and the
  filing are fixed in step 0 of section 4.2. A repeat not done before step 1 is recorded as not
  done, and the gate stays as on main.
- After step 1 the gate is not changed.
- An author-gate refusal counts as not clean for S1 (section 3.1; ruling M8).

## 5. Repositories (decided by the MD 2026-11-13, rulings M2, M3, M6)

### 5.1 What R11 requires of C1 names

R11 requires **at least one** untuned repository, not every passing C1 name:

- Item 2, line 1255: "The pool of the next certifying reading holds at least one untuned
  repository."
- Item 4, lines 1258-1259: "The untuned repository is the first name that passes every
  check", the candidates being "taken in the order of C2".
- Item 3, lines 1256-1257: it comes only from C1, and "a name is dropped only by the
  mechanical checks of item 4".

Both checks confirmed this reading. So, under ruling M2: passing C1 names are used in C2 order
first, then passing L2 names in L2 order, until 10 are reached. If 11 or 12 C1 names pass, the
first 10 in C2 order are used **[aspiration — this registration's design; nothing is run yet]**.
That keeps R11's untuned repository (the first C1 passer) in
every case, so **there is no deviation from R11**. The line stays at $129 and no lift is needed.

**R11's untuned repository** in this text means the first C1 name in C2 order that passes
every check of section 5.2 at step 3. It is fixed at step 4 and never passes to another name.

### 5.2 Qualify, all at $0

All 23 names (12 C1, 11 L2) are qualified once each before any model run, at the apparatus
version written in the step-3 record, with the step-2 configuration, in the same executor, image
and sealed posture as the counted runs **[aspiration — this registration's design; nothing is run
yet]**. The cells are fixed in this registration, as R11 item 4
(lines 1262-1263) requires before the first candidate is qualified: process step `replay`,
class `bug.fix`, size `XS` and size `S`, the repository's language, builder `claude_code`, model
`claude-sonnet-5`, provider `anthropic`, joined as `canonical_cell_key` joins them. Class and
size are the labels the product's classifier gives each commit at that apparatus version; the
labels are filed with the lists. The class is `bug.fix`, sizes XS and S, as in Wave 4
(decided by the MD 2026-11-13, Q18).

A commit is **eligible** under R11 item 1 (lines 1247-1250): no build row in the ledger at any
apparatus version, under any arm, and on no list in Amendment 1. It is **qualified** when its
one qualify record shows the empty patch (the parent) not clean and the gold patch clean under
the belts (section 4.1). The pool uses "the latest record per commit in that posture" (Wave 4
part 2 step 2, line 171); since qualify runs once and is never re-run, that is the only record.

**Why one qualify run, first record final** (R-F3 against FP-H5 and FP-M4): R-F3 allowed a
re-qualify after a filed instrument repair covering all 23 names alike; FP-H5 and FP-M4 asked
for one run with the first record final. A repair is still a person's decision taken after
qualify outcomes are visible, and it can change which names and commits enter the pool. One
run leaves no such decision. If qualify itself is broken, fewer than 6 names pass and the wave
is recorded as not run; a new registration would be needed. Fewer human choices, so taken
**[aspiration — this registration's design; nothing is run yet]**.

**The checks, in their registered order** (R11 item 4, lines 1259-1262; fixing R-F11; the
order confirmed by the MD 2026-11-13). The report gives the first check a name failed in this
order **[aspiration — this registration's design; nothing is run yet]**:

1. **Clone**: `git clone` of the public URL without credentials exits 0.
2. **Language**: the GitHub API's primary language is Python or Go.
3. **Suite runs**: the product's repository probe (`POST /repos/{name}/probe`, $0), run once
   at the recorded HEAD by the deployed service in the existing builder image of the name's
   language with the step-2 configuration, returns a probe run whose served status ends
   `succeeded` (the repository then serves probe status `ok`). The image
   digest and the qualify posture id are written in the step-3 record. One attempt; no second
   try **[hypothesis — that the probe runs the registered test command in the builder image is
   read from the product's API, not yet exercised on these names]**.
4. **Untuned** (R11 item 2): not registered on the stack on 2026-11-12; no build row in the
   ledger; and no harness fix, prompt, checklist, arm file, ADR or backlog item written with
   reference to it, found mechanically at step 3 on the main commit recorded in the step-3
   record (fixing RR6 and RR18). The search is C1's (Wave 4 lines 1287-1296): read-only
   `git grep -i -l` over the paths `docs`, `src` and `tests`, **excluding exactly** these
   paths, which name the names because they register this wave and the last one:
   `docs/reviews/2026-11-10-wave-4-registration.md` and its folder,
   `docs/reviews/2026-11-13-wave-4-report.md`, and
   `docs/reviews/2026-11-13-wave-5-registration.md` (with its amendments) and its folder
   (where every step output, configuration and report of this wave is filed). The forms are:
   - m1: `owner/name` as a fixed string (`-F`);
   - m2: the owner as a whole word (`-w -F`);
   - m3: only when m2 finds a file, the name as a whole word (`-w -F`), and
     `github.com/<owner>` as a fixed string.

   **A name fails check 4 when m1 finds a file, or when m2 finds a file and either m3 form
   finds a file.** No hit is judged by a person. On main `0af1d920` with these exclusions, m1
   finds no file for any of the 23 names; m2 finds files only for `rs` (39) and `google` (4);
   and m3 finds no file for either, so no name fails today
   **[measured — n = 23 names, method: read-only `git grep` of the four forms on main
   `0af1d920` with the exclusions above, run by this seat on 2026-11-13, apparatus 2.5]**.
   The step-2 configuration is the registered input this registration requires and is not
   such an item.
5. **Eligible commits a cell**: its qualify run leaves at least one qualified eligible commit
   in each of the two cells.

For L2 names only, three checks follow, in this order:

6. **Licence**: the GitHub API's `license.spdx_id` is one of MIT, BSD-2-Clause, BSD-3-Clause,
   Apache-2.0, ISC or MPL-2.0. Any other value, NOASSERTION included, fails the name.
7. **Archive**: the GitHub API's `archived` field is false.
8. **Full size**: at least 3 qualified eligible commits in each cell, where for a Go L2 name a
   commit counts only if it compiles at its parent (version 2's Q6, kept for L2 only). "Compiles
   at its parent" is read from the same step-3 qualify record, with no extra command: the
   commit's `red.kind` is `tests_failed` (the parent built and its tests failed), not
   `build_failed` (the parent did not build). A Go L2 commit whose `red.kind` is `build_failed`
   also leaves that name's pool, so the pool, the bar and the counted list agree
   **[aspiration — this registration's design; nothing is run yet]**.

**C1 names: R11's bar, exactly.** A C1 name passes when it passes checks 1 to 5. No other check
is applied to a C1 name: no licence or archive check and no compile-at-parent filter. Those facts
are printed for C1 names as description only.

**L2 names: C1's list rules plus a full-size bar.** L2 names already meet C1's list rules
(public; Python or Go; own test suite; not click or cobra; no `pallets` or `spf13` owner) by how
L2 was built. An L2 name passes when it passes checks 1 to 8.

**Why the licence rule is a fixed allow-list** (fixing FP-M6): reading a licence file and
deciding whether it "permits the use" is a judgement. A fixed list of SPDX ids read from one API
field is not. Its cost is known now: the two L2 names whose API licence is NOASSERTION,
mahmoud/boltons and pypa/packaging, fail check 6, so at most 9 L2 names can pass. This was this
seat's choice, made before any qualify run and blind to arm, and the MD confirmed it on
2026-11-13 **[hypothesis — the licences as the API reported them to the version 2 seat; check 6
reads the field again at step 3]**.

Why two bars: R11 binds the C1 names, and the rulings say a C1 name's bar is R11's exactly.
L2 is this wave's own list, so it takes the full design of 3 commits a cell (the L2 full-size
bar, confirmed by the MD 2026-11-13). Both bars are
fixed now, before any name is qualified and before any arm result exists, and neither leaves
any choice to a person. **[aspiration — no measured pass rate exists; 6 of 23 needed]**

### 5.3 n, floor, fill order, and a C1 name with fewer than 3 commits in a cell

- n = min(number of names that pass, 10), declared in writing with the names at step 4,
  before any model run (decided by the MD 2026-11-13, M1 and M2).
- Fill order: passing C1 names in C2 order, then passing L2 names in L2 order.
- **Floor 6.** Fewer than 6 passes means nothing is spent and the wave is recorded as not run
  **[aspiration — this registration's design; nothing is run yet]**.
- **Outstanding.** If no C1 name passes, or if R11's untuned repository is not among the
  repositories counted at the read for any reason, the report says, in R11's words (lines
  1264-1265), that "the untuned repository is recorded as outstanding and the reading certifies
  nothing about an untuned repository". The word on H2 is still computed on the counted
  repositories.
- **A C1 name with at least 1 but fewer than 3 qualified eligible commits in a cell runs with
  what it has**: every one of its commits in that cell, up to 3, is counted, so m_r is between
  2 and 6. Its D_r is computed on its own registered rows and it has weight 1 in D, as every
  repository does (section 3.1).

  Why this option: the other options are to drop the name (which breaks R11 item 3 when it is
  the first passer), to top it up from another cell or repository (which changes R11's cells),
  or to treat the first passer differently from later C1 passers (a second rule that a person
  would have to apply). Running with what it has is the one option that never drops the name
  R11 requires, uses a single rule for every C1 name, and needs no judgement. Its cost is
  small: one thin repository (m_r = 2) among n = 7 moves the chance of a correct Worse at a
  Wave-4-sized effect from 0.987 to 0.967, and the chance of Within 15 at a null effect from
  0.114 to 0.056 **[measured — n = 1,000 simulated waves a cell, method: discrete simulation in
  appendix A part 5, re-run with python3 -I and compared byte for byte, apparatus n/a]**.

### 5.4 Onboarding configuration, and what makes a name "tuned" (ruling M6)

- **The only configuration allowed** for a repository is what is needed to run its own test
  suite in the existing builder image, and it is produced by one written rule, the same for
  every name, at step 2, before qualify. No person writes it by hand:
  - **Go**: install step `go mod download`; test command `go test ./...`; no environment
    variables.
  - **Python**: install step `pip install -e .`; then, if the package metadata declares an
    optional-dependency group named exactly `test`, `tests`, `testing` or `dev` (the first
    present in that order), `pip install -e ".[group]"`; then, if one of
    `requirements-test.txt`, `test-requirements.txt`, `requirements/test.txt` or
    `requirements-dev.txt` exists at HEAD (the first present in that order), `pip install -r`
    on it; then `pip install pytest`. Test command `python -m pytest -q`. No environment
    variables.
  The rule's output is expressed in the product's repository registration fields
  **[hypothesis — the product takes an install step and a test command per repository]**.
- **Why a fixed rule** (R-F3, FP-H6): a configuration written per repository after looking
  at it is a choice a person makes, and a configuration changed after qualify makes the qualify
  records stale. A rule applied once before qualify removes both. A suite that does not run
  under the rule's configuration fails check 3; there is no second attempt. This was this
  seat's choice within ruling M6, which allows only test-running configuration, fixed and
  hashed, and the MD confirmed the rule on 2026-11-13.
- Each configuration's sha256 is filed at step 2 and in the freeze record. It is never changed.
- **Tuned.** A name is tuned under R11 item 2 when any harness fix, prompt, checklist, arm
  file, ADR or backlog item has been written with reference to it, as found by the search of
  check 4. At step 3 such an item makes the name fail check 4. After step 3 the search is run
  again at the read, on the main commit of that moment with the same exclusions and forms, over
  the run-set names: a hit makes H2 Invalid (P9). No repository is dropped or replaced for this
  **[aspiration — this registration's design; nothing is run yet]**.

### 5.5 Lists (unchanged from version 2, re-checked)

- **C1** is Wave 4's twelve names in C2 order. List sha256
  `b38fb8b6b8de3bf50ebc88b54e6dd54c1d9578bc2c5209c47fcc8350a612a1de`, which matches the Wave
  4 registration, line 1327 **[measured — n = 12 names, method: sha256 recomputed by this seat
  and by both checks, appendix A part 1, apparatus n/a]**.
- **L2** is built from the scout's ranked table only, minus spf13/pflag and minus any C1 name,
  ordered by ascending sha256("crb.w5.repo|20261113|" + owner/name). Its sha256, one
  owner/name a line, newline-ended, is
  `c62cf5f1f39b336e9842b43beb9794cf848051bb84078ba1331213bfa84e8145`
  **[measured — n = 11 names, method: sha256 recomputed from the list, appendix A part 1,
  apparatus n/a]**.
- Leaving out the scout's "measured and rejected" names was this seat's choice, made before
  any result and blind to arm. It is recorded as such (checker finding F-L).

| Place | Repository | Language | Licence (GitHub API) | Passes check 6? |
|---|---|---|---|---|
| 1 | labstack/echo | Go | MIT | yes |
| 2 | mahmoud/boltons | Python | NOASSERTION | no |
| 3 | BurntSushi/toml | Go | MIT | yes |
| 4 | python-poetry/tomlkit | Python | MIT | yes |
| 5 | astanin/python-tabulate | Python | MIT | yes |
| 6 | arrow-py/arrow | Python | Apache-2.0 | yes |
| 7 | andialbrecht/sqlparse | Python | BSD-3-Clause | yes |
| 8 | pypa/packaging | Python | NOASSERTION | no |
| 9 | tox-dev/platformdirs | Python | MIT | yes |
| 10 | go-chi/chi | Go | MIT | yes |
| 11 | google/go-cmp | Go | BSD-3-Clause | yes |

The per-name hashes are in part 1 of `w5_calc.out.txt` (version 2's script, filed beside this
page) and were recomputed unchanged (appendix A part 1 here). Licences are as the GitHub REST
API reported them to the version 2 seat **[hypothesis — n = 11 names, one GitHub REST GET per
repository by the version 2 seat; the responses are not in this repository]**; check 6 reads
the field again at step 3, and the step-3 value is the one that counts.

### 5.6 Reports filed at qualify (ruling M6, R11 items 4 and 5)

- Every one of the 23 names tried, with the first check it failed in the order of section 5.2,
  or "passed", and for each passing name its count of qualified eligible commits in each cell
  **[aspiration — this registration's design; nothing is run yet]**.
- The apparatus version, and the class and size label of every commit qualify looked at.
- For each run-set repository: the full ordered list of each cell's pool (commit ids only),
  the exact cell key string, the pool size, and the sha256 of each list (step 5), appended to
  this registration at step 8.

### 5.7 Commits no seat has read (D3, line 1235; fixing R-F6 and R-F8)

- D3 requires the pool to be "on commits no seat has read". The filed lists carry commit ids
  only. No seat opens a pooled commit's diff or message before the primary is read. The
  configuration rule of 5.4 needs no commit to be read, so no reading is planned; any reading
  is recorded, with the commit id, the seat and the time **[aspiration — this registration's design;
  nothing is run yet]**.
- **Before the freeze** (steps 8b and 10): a commit on a counted list (section 6.1) that has
  been read, or that now has a build row (R11 item 1), is replaced by the next commit in that
  cell's pool list that is eligible, not on a counted list, not read, and not the cell's
  registered pilot commit or a re-pilot commit (section 6.3). The pilot commits are never the
  replacement, at any step. If no such commit exists, the cell is shorter by one
  **[aspiration — this registration's design; nothing is run yet]**.
- **A cell that would be empty.** For any repository other than R11's untuned repository, the
  repository leaves the run set before the freeze, is reported, and nothing replaces it; if n
  falls below 6, the wave stops and is recorded as not run. **R11's untuned repository never
  leaves the run set under this section** (fixing RR22): R11 item 3 lets a name be dropped
  only by the checks of item 4, so its cell runs shorter, down to 0 commits, and its m_r is
  the count left (1 to 6). If both of its cells would be empty, the wave stops before the
  freeze and is recorded as not run, with no counted model money spent
  **[aspiration — this registration's design; nothing is run yet]**.
- **After the freeze**: a recorded read of a counted commit's diff or message before the
  primary is read makes H2 Invalid (P9).
- Both replacement triggers are R11 item 1 or D3 checks, so they stay within R11.

## 6. Commits, run order and pilot

### 6.1 Commits per repository (ruling M3, fixing F-A and R-F3)

- **Two lists a cell, one word each** (fixing RR7). The **pool list** is the cell's whole pool
  in seeded order. The **counted list** is the commits of the cell that are run and counted:
  the first 3 of the pool list (fewer when the pool holds fewer), after any replacement of
  section 5.7. The **pilot commit** of a cell that has one is the 4th of the pool list
  (section 6.3); it is fixed at step 5 and never joins a counted list. "Listed" is not used
  alone **[aspiration — this registration's design; nothing is run yet]**.
- Within each cell the pool is the qualified eligible commits, by their one qualify record in
  the counted runs' posture, in **the product's seeded order**: ascending
  sha256("crb.reading.v1|" + repo + "|" + cell key + "|" + commit), ties by commit, as
  `crb.core.reading.seeded_order` computes it (Wave 4 part 2 step 2, lines 171-176; R11 item 5,
  lines 1266-1267). Version 2's `crb.w5.commit` hash is withdrawn.
- **The cut** (R11 item 5: "The cut is by that registration's own money rule"). The cut is
  c = 3 commits per cell for every n ≤ 10, because the n = 10 high case, $128.31, is at most the
  $129 line (method: section 7.3 table). The money rule acts only at repository boundaries
  (section 8.2) and never shortens a cell. A C1 cell whose pool holds fewer than 3 is counted
  whole (section 5.3). m_r = XS count + S count **[aspiration — this registration's design; nothing
  is run yet]**.
- 2 attempts per commit per arm, as in Wave 4 **[aspiration — this registration's design; nothing is
  run yet]**.

### 6.2 Run order and filing

- **R11's untuned repository runs first.** The other run-set repositories follow in ascending
  sha256("crb.w5.run|20261113|" + owner/name). Putting it first is mechanical, arm-blind and
  fixed at step 4; it makes the money stop least likely to reach it.
- Within a repository: an XS batch, then an S batch.
- Within a batch, arm order is a mirror, A0, S1, S1, A0 or S1, A0, A0, S1, chosen by the first
  bit of sha256("crb.w5.order|" + owner/name + "|" + batch); 0 picks the first order.
- **One driver.** Every registered attempt is submitted by the driver script, in the order
  above, and the driver logs each submission and its response. No attempt is submitted by
  hand. After a crash the driver resumes at the first registered attempt with no run id; it
  never skips one.
- **One run at a time.** The driver submits one run, waits until its served status is
  terminal (`succeeded`, `failed` or `cancelled`), fetches its events, recomputes spend so far
  (section 8.2), and only then submits the next. No two runs of the wave are in flight at once
  **[aspiration — this registration's design; nothing is run yet]**.
- **Refused or started, from the service** (fixing RR9). An attempt is started (filed) when
  the service returns a run id; it is never submitted again. When a submission returns no run
  id (a refusal, a timeout or a lost response), the driver first reads the campaign
  (`GET /campaigns/{id}`, which lists every run filed under it). A run listed there with the
  same repository, arm and `task_ids` and not yet in the driver's log is adopted as that
  attempt's run, and logged. Only if there is none is the attempt submitted again, unchanged.
  An attempt is submitted at most 5 times, at least 15 minutes apart; after the 5th with no run
  id it counts as filed with no row, so not clean for its arm. Neither outcome is judged by a
  person **[aspiration — this registration's design; nothing is run yet]**.
- **Spend over the campaign, not the log.** Spend so far is summed over every run the campaign
  lists, so a run the driver never logged is still counted (section 8.2).
- **The driver obeys the preflight too** (fixing RR20). The driver imports `read_preflight`,
  declares its own `EVENT_EXPECTATIONS` (`cost_usd` included), calls `read_preflight.check` on
  each run's fetched events before summing them, reads every served field it uses through
  `read_preflight.value`, and passes its counts through `read_preflight.nonzero`, so it meets
  the same AST rule as the read script. It must pass the preflight (exit 0) at step 7 and at
  step 10, on its pinned sha256. A driver that reads `cost_usd` any other way fails P5.
- **The close.** The wave closes 30 days after the first counted run (decided by the MD
  2026-11-13, Q19).
  A registered attempt still with no run id at the close counts as filed with no row, so not
  clean for its arm. It never removes its repository from the count **[aspiration — this
  registration's design; nothing is run yet]**.
- So the only way a repository leaves the count after the freeze is a money stop inside it
  (section 8.2).

### 6.3 Pilot (plumbing only)

- The pilot commit of a cell is the 4th commit of the pool list of the XS cell of the first two
  Python and the first two Go run-set repositories, in run order, that have at least 4
  qualified eligible XS commits; it is fixed at step 5. If fewer than two repositories of a
  language qualify for it, the pilot is smaller; it is never a commit on a counted list
  **[aspiration — this registration's design; nothing is run yet]**.
- **How it runs.** Each pilot commit is its own batch, in the mirror arm order of section 6.2
  for that repository and batch name `pilot`, with the run bodies of section 6.4: at most 4
  commits × 4 runs, 16 runs of one commit each, 2 attempts an arm, so at most 8 commit-arms as
  costed in section 7.2 **[aspiration — this registration's design; nothing is run yet]**.
- **The pass rule** (fixing RR10 and RR20). The pilot passes when all of these hold, read
  mechanically from the driver's log and the fetched events:
  1. the driver's preflight and the read script's preflight both exit 0 on the pilot events;
  2. rows landed equal attempts submitted, for every pilot run;
  3. the summed `cost_usd` of the pilot runs is above 0;
  4. every S1 pilot run has at least one author event (section 9.1, P3's events) and at least
     one of its events carries a `cost_usd` above 0.

  A pilot that fails any of them may be repaired before step 10 (the read script, the driver,
  or the deployment at the same deployed commit), with every repair filed, and re-piloted once:
  the re-pilot uses, in each pilot repository, the next commit of the XS pool list after its
  pilot commit that is not on a counted list. A second failure stops the wave before the
  freeze, recorded as not run **[aspiration — this registration's design; nothing is run
  yet]**.
- Pilot rows are struck and never counted. The dry run prints only plumbing counts: rows landed,
  events fetched, events keyed, the preflight's exit code, and the summed `cost_usd`. It never
  prints clean, usable tests or any other outcome by arm, and no seat looks at those by arm
  before the primary is read; a look is recorded.
- The pilot is part of this reading. Its build rows do not make a run-set repository tuned,
  because R11 item 4 tests "untuned" at qualify, and the counted runs make build rows too.

### 6.4 Run bodies and the deployed commit (fixing RR5 and RR19)

**Fixed settings**, as Wave 4 part 2: apparatus as served at step 3; builder `claude_code` with
`claude-sonnet-5`, provider `anthropic`; sealed posture; budget profile `default`; class
`bug.fix`, sizes XS and S. **One slot of a batch's arm order is one run over that batch's
counted commits** (its `task_ids`), one attempt per commit; so the 2 slots an arm in a batch
are the 2 attempts per commit per arm of section 6.1
**[aspiration — this registration's design; nothing is run yet]**.

| Arm | Run body, sent by the driver |
|---|---|
| `A0` | `repo`, `kind: "blind"`, `task_ids` (the batch's counted list), `learning: "off"`, `retain: {transcripts: true}`, `builder_config: {keep_transcript: true}`, `budget: {max_turns: 50}`, `campaign_id`, `env_stop: 2`, `outage_stop: 3`, `max_cost_usd: 6` |
| `S1` | the same, plus `arm: "S1"` and `test_author: "editblock:gpt-oss-120b"` |

- **The turn limit is 50**, the value Wave 4 ran its counted batches at (Wave 4 registration
  line 759), fixed now with no pilot rule, so the rate of section 7.2 applies to the same
  setting. `max_cost_usd: 6`, `env_stop: 2` and `outage_stop: 3` are Wave 4's values (line
  760). The test author's own budget and timeouts are the product's defaults at the deployed
  commit, sent by no field, as in Wave 4 part 2
  **[hypothesis — the settings are read from the Wave 4 registration on main `0af1d920`; that
  they give the cost basis of 7.2 assumes Wave 4's report draft ran at them]**.
- **The campaign.** At step 8a the driver registers one campaign for the wave
  (`POST /campaigns`), with its ceiling in pounds equal to $129 at the USD-per-GBP rate it
  records, the whole ceiling released, and the decision named as this registration's Q20. Its
  id goes into every run body and the freeze record. The campaign's 409 `campaign_ceiling` is
  a second guard under the money stop of section 8.2, not a replacement for it.
- **Frozen.** The bodies, with the campaign id, are written out in full in the freeze record;
  the driver sends exactly them, and its sha256 binds that.
- **The deployed commit.** `/version` serves the package, apparatus, policy and belt-set
  versions but no commit **[measured — n = 1 route, method: code read of `/version` in
  `src/crb/server/routes/system.py` on main `0af1d920`, apparatus 2.5]**. So at step 3 the
  operator records the main commit the service is deployed from, and it must serve the same
  code as the step-1 commit: `git diff --name-only <step-1> <deployed> -- src deploy
  pyproject.toml uv.lock` is empty. The driver records `/version` before each run. No deploy
  from another commit is made between step 3 and the read; a restart from the same commit is
  allowed and recorded. P8 checks both
  **[aspiration — this registration's design; nothing is run yet]**.

## 7. Design, cost and power (decided by the MD 2026-11-13, ruling M1)

### 7.1 The design

**D3: arms A0 and S1; 6 commits per repository (3 XS, 3 S), 2 attempts each; n = number of
passing names, at most 10; floor 6; nothing is spent below the floor. Line $129.**
**[aspiration — this registration's design; nothing is run yet]**

### 7.2 Cost basis

- Rate per commit-arm (2 attempts) = $48.115522 / 120 = $0.400963, all in
  **[hypothesis — the Wave 4 report draft (open PR #141), not on main, section 5; n = 120
  commit-arms; product dollars, unconfirmed]**.
- High case = central × 2.5 **[hypothesis — version 1's margin, kept unchanged]**.
- Commit-arms = n × 6 commits × 2 arms + 8 pilot. A thin C1 repository costs less; the table
  is the full-size maximum **[aspiration — this registration's design; nothing is run yet]**.
- Author (Cerebras) cost per S1 attempt = $0.174468 / 126 = $0.001385; at n = 10 there are
  (60 + 4) × 2 = 128 S1 attempts, $0.18 central and $0.44 high, against a $44.78 balance, so
  Cerebras does not bind **[hypothesis — the Wave 4 report draft (open PR #141), not on main; n =
  126 S1 attempts; arithmetic on its
  figures; product dollars, unconfirmed]**.
- Time per commit-arm-attempt slot = 2.464 minutes
  **[hypothesis — the Wave 4 report draft (open PR #141), not on main; 49 runs × 5 commits in 10.06
  h]**.

### 7.3 Cost by n

Lift is defined once: the line (high case rounded up to the next dollar) minus $130.02, or $0
when that is negative.

| n | Commit-arms | Central | High | Line (high, rounded up) | Lift over $130.02 |
|---|---|---|---|---|---|
| 6 | 80 | $32.08 | $80.19 | $81 | $0 |
| 7 | 92 | $36.89 | $92.22 | $93 | $0 |
| 8 | 104 | $41.70 | $104.25 | $105 | $0 |
| 9 | 116 | $46.51 | $116.28 | $117 | $0 |
| 10 | 128 | $51.32 | $128.31 | $129 | $0 |
| 11 | 140 | $56.13 | $140.34 | $141 | $10.98 |
| 12 | 152 | $60.95 | $152.37 | $153 | $22.98 |

**[measured — n = 7 values of n, method: appendix A part 2, commit-arms × $0.400963, × 2.5,
rounded up; recomputed independently by the forking-path check; apparatus n/a; product dollars,
unconfirmed]**

- n = 11 and n = 12 cannot occur: R11 requires one untuned repository, not every C1 passer
  (section 5.1), so the cap of 10 holds. The two rows are shown only because ruling M2 asked for
  them.
- At n = 10 the high case is $128.31, $1.71 inside $130.02 and $0.69 inside the $129 line.
  Time at n = 10: 10.5 h; at n = 6: 6.6 h **[measured — appendix A part 2]**.

### 7.4 Power (ruling M7, fixing F-F and F-G)

At Wave 4's consistency, 11 of 12 batches had the sign of the mean, so q = 11/12
**[hypothesis — the Wave 4 report draft (open PR #141), not on main; n = 12 batches]**. Power for a
correct Better or Worse at
alpha 0.05, by two methods **[aspiration — this registration's design; nothing is run yet]**:

- **Method A**: exact sign test with equal magnitudes (each repository has the right sign
  with probability q; binomial, exact).
- **Method B**: exact sign-flip test with each repository's difference drawn from
  Normal(z, 1), z = Φ⁻¹(11/12) = 1.3830; 4,000 simulated waves a cell, seed 20261123.

| n | A: power | A: needs | B: power (s.e.) |
|---|---|---|---|
| 6 | 0.593 | 6 of 6 | 0.595 (0.008) |
| 7 | 0.544 | 7 of 7 | 0.826 (0.006) |
| 8 | 0.499 | 8 of 8 | 0.900 (0.005) |
| 9 | 0.831 | 8 of 9 | 0.941 (0.004) |
| 10 | 0.800 | 9 of 10 | 0.973 (0.003) |
| 11 | 0.768 | 10 of 11 | 0.985 (0.002) |
| 12 | 0.928 | 10 of 12 | 0.991 (0.001) |

**[measured — n = 4,000 simulated waves a cell, method: appendix A part 3, A exact, B
simulation, apparatus n/a. The forking-path check recomputed both
with its own script and seeds: method A identical; method B 0.590, 0.837, 0.902, 0.940, 0.968,
0.985, 0.992, within 2 s.e.]**

Plain statements:

- Power is not monotone in n under method A, because the exact p-value moves in steps:
  at n = 7 and 8 one dissenter already gives p ≥ 0.05 (0.125 and 0.0703).
- Under method B, power is at least 0.8 from n = 7. Under method A it is not 0.8 until n = 9.
  Which is nearer the truth depends on how much the repository differences vary in size; a
  dissenter with a small difference is allowed under B and not under A.
- At n = 6, the floor, power is 0.59 by both methods. An Undecided at n = 6 is likely to come
  from too few repositories, not from a small effect (section 1.4).
- At q = 11/12, power depends on n and not on m. m = 6 is chosen (ruling M1) because more
  commits per repository make a zero D_r less likely and raise the chance of Within 15 when
  the effect is small; it is not claimed to be the cheapest design with power 0.8. A design
  with m = 4 would be cheaper (checker finding F-F) and is not taken.

The discrete simulation of the registered read (m = 6, the model of part 6 of
`w5_calc.out.txt`, 1,000 waves a cell) gives, for a true shift of −46 points and τ_e = 0.10,
P(correct Worse) =
0.863 at n = 6, 0.985 at n = 7 and 1.000 at n = 10; for −25 points, 0.392, 0.630 and 0.931;
with τ_e = 0.20 at −46 points, 0.693, 0.930 and 0.996. At a true effect of 0, any decisive
word (a false one) occurs with probability about 0.05 or below in every cell (largest observed
0.048; Monte Carlo s.e. about 0.007, so a cell's true rate may be slightly above 0.05). Because
the model clips rates to [0, 1], its "effect 0" is about −0.8 points, not exactly 0
**[measured — n = 1,000 simulated waves a cell, method: discrete simulation in appendix A part 4,
s.e. = √(0.05 × 0.95 / 1,000), apparatus n/a]**.

### 7.5 Alternatives costed and not taken (ruling M1)

| Design | Arms, m | Commit-arms (n = 10) | Central | High | Line | Lift over $130.02 |
|---|---|---|---|---|---|---|
| D1 | A0, S1; m = 10 | 200 + 8 = 208 | $83.40 | $208.50 | $209 | $78.98 |
| D2 | A0, S1, W; m = 10 | 300 + 40 = 340 | $136.33 | $340.82 | $341 | $210.98 |

At n = 7: D1 148 commit-arms, $59.34 central, $148.36 high, line $149, lift $18.98; D2 250
commit-arms (the W pilot is fixed at 10 commits × 4 arms = 40, whatever n), $100.24 central,
$250.60 high, line $251, lift $120.98. D2 at n = 10 would file 220 S1 attempts
((100 + 10) × 2), author cost $0.305 central. Version 2's D2 figures at n = 7 (238, $95.43,
$238.57, $108.98) and its 226 S1 attempts were wrong and are replaced (checker finding F-K)
**[measured — n = 2 designs at n = 7 and n = 10, method: appendix A part 2, commit-arms ×
$0.400963, × 2.5, apparatus n/a; product dollars, unconfirmed]**. Neither design is run in Wave 5.

## 8. Money and stops (decided by the MD 2026-11-13, rulings M7 and M8)

### 8.1 The line

- **The line is $129**, committed under the operator's standing authority of 2026-11-13 with
  the figure reported to the operator (R11 item 7; section 0; Q20), and recorded in the freeze
  record (step 10). It is never lifted after the freeze, and in
  particular never after a money stop in order to reach the floor.
- **The $129 is held for this wave** (fixing RR12). At step 8a and again at step 10 the spend
  so far of the $200 line, quoted from Paul with its date, is recorded, and what remains of the
  line must be at least $129; if it is not, the wave stops and is recorded as not run. The
  wave's campaign ceiling (section 6.4) holds the $129 in the product
  **[aspiration — this registration's design; nothing is run yet]**.

### 8.2 Money stop

- **Spend so far** (fixing FP-M5 and RR9) is the sum of the served `cost_usd` field over every
  event of every run the wave's campaign lists (`GET /campaigns/{id}`), pilot and counted,
  builder and author steps alike, whether or not the run is in the driver's log. The driver
  computes it before each repository starts and after each run reaches a terminal status
  (section 6.2), reading `cost_usd` through `read_preflight.value`. `cost_usd` is declared in
  the `EVENT_EXPECTATIONS` of both the driver and the read script, so a missing key raises,
  and the summed spend of the pilot goes through `nonzero` with no waiver and must pass the
  pilot rule of section 6.3, so a spend that silently reads as zero stops the wave
  **[hypothesis — `cost_usd` is in `ENVELOPE_KEYS` of `scripts/read_preflight.py` as at the
  head of PR #142 (`7122682`), not yet on main; that it covers both builder and author cost is
  checked by the pilot dry run's printed sum]**.
- **Repository boundary.** Before a repository starts, if spend so far plus the high cost of
  one full repository ($12.03 = 12 commit-arms × $0.400963 × 2.5) would pass $129, the wave
  stops there. At the high case for every repository, all 10 repositories fit (pilot $8.02 +
  10 × $12.03 = $128.31); before the 10th, spend is $116.28 and the margin is
  $129 − ($116.28 + $12.03) = $0.69, which also covers the $0.44 high author cost if the rate
  does not already include it **[measured — n = 10 repositories, method: appendix A part 2,
  arithmetic on the cost basis of 7.2, apparatus n/a; product dollars, unconfirmed]**.
- If $129 is passed inside a repository, filing stops at once. That repository is not
  counted; its rows are kept and reported as description.
- **k whole repositories.** After a money stop, k is the number of complete repositories. The
  read happens if k ≥ 6. A stop that leaves fewer than 6 whole repositories makes H2 Invalid
  **[aspiration — this registration's design; nothing is run yet]**.
  At k = 6 the power of section 7.4 at n = 6 applies and is printed beside the word. If R11's
  untuned repository is not among the k, the outstanding sentence of section 5.3 is printed.

### 8.3 Harness faults: no stop; faulty rows count as failures (ruling M8)

**Choice: the harness-fault stop is removed. A row with a harness fault counts as a failure
for the arm that produced it,** through its served `clean` field (section 3.1). There is no
threshold, no drop and no replacement.

Why this and not the signed "more than 2 faulty rows of 24" stop:

1. A mechanical fault rule can avoid using the arm label, but it cannot avoid the arm's
   effect. A sandbox error or a missing verdict can be caused by what the arm did (for
   example, an authored test that hangs the sandbox). Dropping a repository on such rows
   would remove exactly the repositories where one arm's served path breaks, and the "S1 as
   served, including its harness" scope of section 1.2 says those breaks belong to the arm. So
   a rule that is blind to the arm label is still not free of the arm, and the ruling's
   condition cannot be met without a forking path.
2. A drop would make the run set depend on outcomes seen during the wave, and a replacement
   would add a second choice (which repository next, and whether money allows). Ruling M8's
   "with and without" double report would add a second number beside the word.
3. Counting such rows as failures needs no list of fault codes that could silently match
   nothing, which is the failure mode of Wave 4's event-key bug. It reads one served field.

The cost of this choice is noise from faults that are truly external (a provider outage). The
mirrored arm order of section 6.2 runs both arms of a batch next to each other in time, so an
outage tends to hit both. Every fault is printed by `error_code` and arm in description
(section 11.1), so a reader can see it. A builder provider error is treated like any other
fault (closing the second half of checker finding F-H).

## 9. Checks before and at the read

### 9.1 The checks

Each failure except P3 makes H2 Invalid; there is only one contrast. P3 bars Within 15 only and
leaves Better, Worse and Undecided.

| # | Check | Denominator | Pass condition | When |
|---|---|---|---|---|
| P1 | Freeze record filed (step 10 of 4.2) | – | filed before the first counted run | before |
| P2 | Row completeness | registered attempts in the k counted repositories (Σ m_r × 2 per arm) | no registered attempt has more than one run id; every counted run id is in the driver's log, either submitted by the driver or adopted from the campaign listing (6.2); the campaign lists no run that the log lacks; an attempt with no row counts as not clean | at read |
| P3 | Usable-test share | S1 attempts filed in the counted repositories; filed with no row counts as no usable test | at least 0.9 have a usable test. **Usable** (fixing RR23; Wave 4 R12 item 3, `usable_attempt`): (a) the attempt has a row; (b) its run's events hold a `builder.author_test.start` event whose envelope `task_id` equals the commit; (c) none holds a `builder.author_test.failed` event whose envelope `task_id` equals the commit or cannot be read; (d) the row's `error` is a string that does not start with `authoring: `. Both actions and the key are declared in `EVENT_EXPECTATIONS` | at read; bars Within 15 only |
| P4 | Calibrations: gold against empty (4.1), K1 to K7 (4.3) | every commit on a counted list (6.1); seven sets | output sha256 equals the filed expected sha256 | step 6, and at read by re-pushing the stored files |
| P5 | Event-key positive control, live dry run, conforming probes | – | 9.2 | step 7, and at read on the stored snapshot |
| P6 | Event-key check on every event | every event fetched for the counted rows | every expected key resolves; none skipped | at read |
| P7 | Zero counts | every count passed through `read_preflight.nonzero` | 9.3 | at read |
| P8 | Apparatus version and deployed commit | every counted row; every `/version` record the driver kept (6.4) | every row reports the apparatus version of the step-3 record; every kept `/version` record equals the step-3 one in every served field; the deployed commit is the step-3 one and no deploy from another commit happened (6.4) | at read |
| P9 | Reads and writes | the record of 5.4 and 5.7; the check-4 search of 5.2 | no recorded read of a counted commit's diff or message, and no R11 item 2 item written with reference to a run-set repository, from step 3 to the primary read; the check-4 search, re-run at the read on main, fails no run-set name | at read |

### 9.2 P5: the event-key check, its positive control, and the AST rule (M4, M7)

The event-key check (EKC) is `scripts/read_preflight.py`. **That script is not on main yet:
it is in open PR #142** (head `7122682` when this text was written). **The file used is the
file on main after #142 merges** under the normal merge rule, pinned at step 5 of 4.2 with its
sha256 and that main commit id, and a byte copy is filed in the wave-5 folder (fixing RR2 and
RR14). Until #142 merges, step 5 and every later step wait and no money is spent; no version
from a branch is used. The read script, the driver and every probe import that pinned file. It
exits with `read_preflight.EXIT_CODE`, which is 6, on
any failure, before any figure is computed
**[hypothesis — `EXIT_CODE = 6` read from `scripts/read_preflight.py` at the head of PR #142
(`7122682`); the file may change before it merges, and the freeze record pins the version
used]**.

- **The read script must import `read_preflight`, declare a module-level
  `EVENT_EXPECTATIONS`, call `read_preflight.check(...)` on the events it fetched before any
  figure, and pass every count through `read_preflight.nonzero(...)`.** The preflight itself
  fails a script that does not.
- **The Wave 4 events snapshot.** At step 7 Wave 4's already-served events are fetched once
  (a GET, $0) and written to a file; its sha256 is filed. Every later P5 run uses the file, so
  P5 at read time does not depend on the service still serving Wave 4's events.
- **Positive control** (fixing RR15). The planted script is the Wave 5 read script with
  Wave 4's event-key lookup planted in it (the `payload["task"]` lookup; the served event
  carries a top-level `task_id`). It differs from the unplanted read script in exactly one
  line, line N; N and both sha256s are filed. It passes only if, on the snapshot, (a) it exits
  with exactly code 6, (b) at least one line of its stderr, leading spaces removed, starts
  with `line N:` (the preflight CLI prints each finding indented by two spaces), and (c) the
  unplanted read script exits 0. **Any other result, a crash or an import error alike, fails
  P5.**
- **Live dry run.** The unplanted Wave 5 read script's preflight is run on the snapshot and
  must exit 0, passing `check` on every event. Any other exit fails P5. This shows, before any
  Wave 5 model money, that the declared keys match what the service serves.
- **Conforming bypass probes** (fixing FP-L2). The 18 bypass probes of 2026-11-13 were also
  failed for not importing `read_preflight`, and most also hit the planted `task` mismatch, so
  their exit 6 did not isolate each ban. At step 7 the probes are written from scratch on the
  pinned file: one passing script (imports `read_preflight`, declares `EVENT_EXPECTATIONS`,
  calls `check` and `nonzero`, reads a served key through `value`), and one probe for each
  banned or tracked form named in the AST rule below, each differing from the passing script
  in exactly one line, line N, filed with N. A probe passes only if it exits 6 and at least one
  stderr line, leading spaces removed, starts with `line N:`; the passing script must exit 0. The
  driver (6.2) is also
  run through the preflight and must exit 0. All sha256s are frozen.
- **The AST rule, as now implemented.** The preflight parses the read script and fails, exit
  6, on any read of an event dictionary that can turn a missing key into a value. It follows
  the event dictionary through aliases (including a module alias and an attribute such as
  `.payload`), function parameters and helper functions, tuple-unpacking targets, `for`
  targets, `match` patterns, comprehensions, lambdas and walrus assignments. It bans `.get`
  with or without a default, `dict.get(...)` called unbound, `getattr(..., "get")`,
  `operator.itemgetter`, and `except KeyError` around an event lookup. It fails a payload
  lookup of a key the emitter serves at the envelope, any key or action compared but not
  declared in `EVENT_EXPECTATIONS` (which catches an `or` default on a subscript and a
  misspelt action), and a missing `check` or `nonzero` call. A missing key must raise, and
  reads go through `read_preflight.value`.
  **[hypothesis — 22 probe files were run through the preflight CLI of the event-key-check
  branch (PR #142) on 2026-11-13: 18 bypass probes, 3 false-positive probes and Wave 4's read
  script; all 22 reported "preflight FAILED, no figure computed"; the three false-positive
  probes were failed only for the missing `check`/`nonzero` calls, not for their lookups.
  Weaker than it reads: 17 of the 18 bypass probes were also failed for the missing import;
  the conforming probes above close that gap. The probe files and logs are not in this
  repository; the conforming probes are filed with their sha256s at step 7]**.
- The sha256 of `scripts/read_preflight.py` used is the one pinned at step 5 and repeated in
  the freeze record. The rule above describes the implementation at PR #142's head `7122682`
  as probed. If the pinned file differs from it, the freeze record files the diff, and every
  P5 probe is run on the pinned file at step 7 and again at step 10 (fixing RR13); the 22
  probes of 2026-11-13 are not evidence for a file they were not run on.

### 9.3 P7: zero counts and the frozen waiver constants W0 and W0_CAL (ruling M5, fixing F-D)

`read_preflight.nonzero` stops on a count of zero over a non-empty population unless a signed
`Waiver(count, reason, signed_by, signed_at)` for that exact label is passed as `waiver`; a
waiver passed to a count that is not zero also stops it **[hypothesis — read from
`scripts/read_preflight.py` at PR #142's head `7122682`; the pinned file governs]**. In Wave 5
**no person writes a waiver at read time.** The read script holds a module constant
`W0 = {exact nonzero label: Waiver(label, reason, signed_by, signed_at)}`, and in calibration
mode `W0_CAL` likewise (fixing RR8). The script passes `W0[label]` only when the label is a key
of the constant and the count is zero, and passes nothing otherwise. It calls `nonzero` only
with a label that is in a module constant `LABELS`, the exact list expanded below; any other
label exits 6 before a figure prints. `nonzero`'s `out` writes to stderr. Both constants are
generated at step 5 by expanding the label
patterns below over the run-set names and the arms, signed by the methodologist and the MD in
the freeze record (not before it; MD ruling of 2026-11-13), and hashed there as part of the
read script. Nothing is added after the
registration is committed. **A zero on a label that is not a key exits 6, so H2 is Invalid,
mechanically.** Zeros seen in the pilot dry run do not extend W0.

**W0, labels that may be zero** (`<repo>` is each run-set owner/name; `<arm>` is A0 or S1):

| Label pattern | `reason` of the Waiver |
|---|---|
| `clean rows|<repo>|<arm>`, `clean rows|all|<arm>` | an arm can fail every attempt; P4 shows the field is read |
| `author refusals|S1`, `author timeouts|S1`, `author provider errors|S1` | the author may never refuse, time out or error |
| `builder failures given a usable test|S1` | S1 may pass on every usable test |
| `fault rows|<arm>` | no harness fault may occur |
| `no row|<arm>` | every registered attempt may have a row |
| `repositories D_r = 0`, `repositories D_r != 0` | either set may be empty |
| `batches nonzero summed difference` | every batch may sum to 0 |
| `review verdict|<verdict>|<arm>`, `audit agree`, `audit disagree` | a verdict or agreement class may not occur |
| `S1 attempts with an author event|<repo>`, `usable tests|<repo>` | an author can fail every attempt in one repository; the all-k count is not waivable |

Fault counts by `error_code` are counted only over the codes that occur, so they are never
zero and need no entry.

**W0_CAL** (calibration mode): `clean rows|<repo>|empty` and `clean rows|all|empty`, reason
"the empty patch is not clean on any qualified commit, by definition".

**Never waivable** (no entry in either constant, so a zero makes H2 Invalid). These are
counted only over all k counted repositories, never per repository, with these exact labels:
`registered attempts|all`, `filed attempts|all|<arm>`, `rows fetched|all|<arm>`,
`events fetched|all`, `events|<action>` for each action declared in `EVENT_EXPECTATIONS`,
`S1 attempts with an author event|all`, `usable tests|all`, `pilot cost_usd|all` and
`counted repositories`. The per-repository forms `S1 attempts with an author event|<repo>` and
`usable tests|<repo>` are counted too, and they are keys of W0 with the text "an author can
fail every attempt in one repository; the all-k count is not waivable". A zero usable-test count is
not waivable because that was Wave 4's failure: the read printed
"usable tests: 0 of 120" from a key mismatch.

## 10. Forking paths (decided by the MD 2026-11-13; Q17 confirmed)

- **The MD's rule stands: after the first counted run no amendment raises the word**, or
  changes the statistic, the unit, the unit rule, the sign of D, the order of words, J or
  alpha.
- **No amendment lowers the word either** (fixing FP-H2; confirmed by the MD 2026-11-13, Q17).
  After the first counted run the word moves only through the mechanical checks of sections 8
  and 9. Any amendment filed after the first counted run, lowering or raising, is printed
  beside the word and does not act.
- No check that fails after the freeze is repaired (section 4.2). The money line is not
  lifted after the freeze (section 8.1). The run set closes at step 4 (section 5.4). After the
  freeze the only way a repository leaves the count is a money stop inside it (sections 6.2 and
  8.2), which is mechanical.
- D is signed S1 − A0, and the sign is printed beside every number.

## 11. Secondaries and description (none changes the word)

### 11.1 Description

1. **The S1 decomposition.** S1 attempts filed are split into author refusals, author
   timeouts, author provider errors, builder failures given a usable test, harness faults,
   and clean. Counts and shares over "S1 attempts filed", for the k repositories.
2. **Harness faults by served `error_code` and arm**, for both arms, and the count of rows with
   `clean` true and a non-null `error_code` (counted as clean, as served).
3. **The t interval.** D with its 90% t interval, labelled "approximate" **[aspiration — this
   registration's design; nothing is run yet]**.
4. **Per-repository table**: m_r, registered rows, clean rows per arm, D_r; C1 or L2; whether it
   is R11's untuned repository; for C1 names, licence, archive state and the Go
   compile-at-parent flag of each commit.
5. **Rows from a repository not counted** after a money stop, with run ids.
6. **Every recorded read of a pooled commit and every replacement made under section 5.7.**

### 11.2 Registered secondaries

1. **By batch.** The exact sign-flip over the 2 × k batches (one XS, one S per repository).
   It prints after the primary with the sentence "the secondary does not change the word."
2. **Blind review and Paul's audit (ruling M9)**, with the Wave 4 B2 and B3 rules (Wave 4
   registration lines 1136-1198) adapted to Wave 5:
   - When: drawn only after the primary is read and signed.
   - Per repository R and arm A, up to 3 clean patches. Order R's counted commits by
     ascending sha256("crb.w5.review|20261113|" + R + "|" + commit), ties by commit. Walk it,
     one patch a commit, the clean row with the lower attempt number: first commits clean
     under both arms (at least one clean row under each, Wave 4 reading R6), then other
     commits with a clean row under A, then second clean rows in the same two passes; stop
     at 3. A shortfall is reported as a count
     **[aspiration — this registration's design; nothing is run yet]**.
   - The drawn list and its sha256 are filed before the reviewer sees a patch. The reviewer
     is not told the arm and gives one of: merge as is, merge with small edits, do not merge.
   - Paul's audit: order each repository's reviewed patches by ascending
     sha256("crb.w5.audit|20261113|" + R + "|" + A + "|" + commit + "|" + attempt), ties by
     commit, then arm, then attempt. Paul checks the first of each repository in run order,
     then the second of each, until 10 are taken or none are left. He is not told the arm or
     the reviewer's verdict until he has given his own (Wave 4 reading R9).
   - Reported: verdict counts by arm, and agreement counts between Paul and the reviewer.
     Printed with the sentence "the review does not change the word." Even a "merge as is"
     count supports only "passes the repository's held-out tests" for the primary claim.
   - Cost: the reviewer is a blinded agent session, as in Wave 4, and is not charged to the
     $129 line (decided by the MD 2026-11-13). If it would need product dollars, that goes to
     Paul with a figure first.

## 12. Decisions

| # | Decision | Value | Status |
|---|---|---|---|
| Q1 | Contrasts | H2 only; J = 1; no W, no H1 | decided by the MD 2026-11-13 (M1) |
| Q2 | Sign of D | D_r = S1 − A0 | decided by the MD 2026-11-13 |
| Q3 | Calibrations | gold vs empty from the qualify record; K1 to K7; sha256 compare | decided by the MD 2026-11-13 (M1, M4); mechanics this seat's |
| Q4 | What R11 requires | at least one untuned repository, the first C1 passer | read from R11 lines 1255, 1258-1259 (M2); confirmed by both checks |
| Q5 | Lists and fill | C1 in C2 order, then L2; cap 10; no deviation | decided by the MD 2026-11-13 (M2) |
| Q6 | Qualify bar | C1: R11 item 4 exactly; L2: + licence allow-list, archive, ≥ 3 a cell, Go compile | M3; L2 bar and check order this seat's |
| Q7 | Thin C1 name | runs with what it has; weight 1; m_r 2 to 6 | M3; option chosen by this seat |
| Q8 | Commit order | product's seeded order, `crb.reading.v1`; one qualify record | decided by the MD 2026-11-13 (M3) |
| Q9 | Design | D3: A0, S1; m = 6; n ≤ 10; floor 6; line $129 | decided by the MD 2026-11-13 (M1) |
| Q10 | Pre-run order and freeze | section 4.2, steps 0 to 10 | decided by the MD 2026-11-13 (M4); order this seat's |
| Q11 | Zero counts | frozen W0 and W0_CAL constants, signed at the freeze | decided by the MD 2026-11-13 (M5) |
| Q12 | Onboarding config | one written rule, before qualify; hashed; never changed | decided by the MD 2026-11-13 (M6); rule this seat's |
| Q13 | Money | line frozen; boundary stop; k ≥ 6 else Invalid | decided by the MD 2026-11-13 (M7) |
| Q14 | Harness faults | no stop; faulty rows are failures for their arm | M8; option chosen by this seat |
| Q15 | Claim words | "passes the repository's held-out tests"; never "mergeable" | decided by the MD 2026-11-13 (M9) |
| Q16 | Review secondary | B2/B3-style draw and audit; does not change the word | decided by the MD 2026-11-13 (M9) |
| Q17 | Amendments after first counted run | none acts after the first counted run, in either direction | decided by the MD 2026-11-13 (the rule and this seat's narrowing, confirmed) |
| Q18 | Cell class | `bug.fix`, sizes XS and S, as Wave 4 | decided by the MD 2026-11-13 |
| Q19 | Wave close | 30 days after the first counted run | decided by the MD 2026-11-13 |
| Q20 | Budget route for $129 | operator's standing authority of 2026-11-13; figure reported to the operator that day; no lift ($129 inside $130.02) | decided by the MD 2026-11-13 |
| Q21 | Item-5 confirmations | onboarding rule (5.4); SPDX allow-list; L2 full-size bar; order of checks (5.2) | confirmed by the MD 2026-11-13 |
| Q22 | Qualify record | holds both verdicts: a cited fact of the code (4.1); the pilot checks it on a served record | checked by code read on main `0af1d920`, 2026-11-13 |
| Q23 | A3 author-gate refusals | S1 as on main at step 1; gate changed before step 1 only on the $0 repeat proof; not after (4.5) | decided by the MD 2026-11-13 |
| Q24 | W0 and W0_CAL signing | in the freeze record, not now (9.3) | decided by the MD 2026-11-13 |
| Q25 | Blind reviewer | an agent session, not charged to the line (11.2) | decided by the MD 2026-11-13 |
| Q26 | Who "the operator" is | Paul, in every use (0) | confirmed by the delivery manager, 2026-11-13 |
| Q27 | Preflight version | the file on main after PR #142 merges; pinned at step 5; steps 5+ wait until then (4.2, 9.2) | confirmed by the delivery manager, 2026-11-13 |
| Q28 | Run bodies | Wave 4's counted settings: turn limit 50, $6 cap a run, env_stop 2, outage_stop 3; S1 author `editblock:gpt-oss-120b` (6.4) | confirmed by the delivery manager, 2026-11-13 |
| Q29 | Refused or unknown submissions | adopt from the campaign listing; at most 5 submissions, 15 minutes apart; then filed with no row (6.2) | confirmed by the delivery manager, 2026-11-13 |
| Q30 | Campaign | one campaign, ceiling $129 at the recorded rate, registered at step 8a; spend over the campaign (6.2, 6.4, 8.2) | confirmed by the delivery manager, 2026-11-13 |
| Q31 | A3 repeat | row by the fixed sha256 rule; `go test ./...` in the builder image; proof is `[build failed]`; else not done (4.2 step 0) | confirmed by the delivery manager, 2026-11-13 |
| Q32 | Arithmetic | exact rationals; exact p; sd divisor k − 1; strict Within 15; byte format (3.4) | confirmed by the delivery manager, 2026-11-13 |
| Q33 | Check 8 | compile at parent is `red.kind` = `tests_failed`; a Go L2 `build_failed` commit leaves the pool (5.2) | confirmed by the delivery manager, 2026-11-13 |
| Q34 | Untuned repository before the freeze | never leaves the run set; runs shorter, m_r 1 to 6; both cells empty means not run (5.7) | confirmed by the delivery manager, 2026-11-13 |
| Q35 | Check 4 | three-form git grep at step 3, exclusions named; re-run at the read (5.2, P9) | confirmed by the delivery manager, 2026-11-13 |
| Q36 | Pilot | own batches in mirror order; pass rule; one re-pilot, then not run (6.3) | confirmed by the delivery manager, 2026-11-13 |
| Q37 | Deployed commit | recorded at step 3; no src or deploy diff from the step-1 commit; no deploy from another commit (6.4, P8) | confirmed by the delivery manager, 2026-11-13 |
| Q38 | Remaining line | at least $129 left at steps 8a and 10, else not run (8.1) | confirmed by the delivery manager, 2026-11-13 |
| Q39 | Read trigger | once, at the earlier of all attempts finished and fetched, or the close (3.5) | confirmed by the delivery manager, 2026-11-13 |
| Q40 | Probes | product probe for check 3; P5 probes rewritten with the `line N:` rule; the driver through the preflight (5.2, 9.2) | confirmed by the delivery manager, 2026-11-13 |
| Q41 | Usable test and labels | Wave 4 `usable_attempt`; exact `LABELS`; never-waivable counts over all k (P3, 9.3) | confirmed by the delivery manager, 2026-11-13 |

## Appendix A. Script output, quoted

The scripts and their outputs are filed beside this page, in
`docs/reviews/2026-11-13-wave-5-registration/`. Each script uses the standard library only and
is run with `python3 -I <script> > <output>` from that folder; a re-run on 2026-11-13 (Python
3.14.7) gave output byte-identical to the filed output for all four scripts
**[measured — n = 4 scripts, method: re-run with `python3 -I` and compared byte for byte with
`cmp`, apparatus n/a]**.

| Script | sha256 of the script | Output | sha256 of the output |
|---|---|---|---|
| `w5v3_calc.py` | `842d57c32ca304a363c0646dc39cb880bb274d9232009ae95bd49cec3468f4ae` | `w5v3_calc.out.txt` | `c9ec2a027aa54512376f47e9e1e26d59a8b4ab5b2c0cd4f4ffbe5634a325a5c4` |
| `recheck.py` | `1494ec338540ec0359daa92f820496f9da59249640cb08379a73d4a1b781c1c9` | `recheck.out.txt` | `14a451f189feff8a4cde0ac9cb445ebbc520356ba7540405c6dccdbde1bb31e5` |
| `w5_calc.py` | `b9e80ef4ab1d42cf38e137a56e1b5af8765daa84c945edfcdad54913e5698132` | `w5_calc.out.txt` | `ca053315d5600520e5c2b65391891ca64489c5a3241d49ae3262b225467f5352` |
| `regcheck.py` | `0eacc88160f4676113c9239481df98a2da7541aa6a44d2dbbfd98cc33d767c40` | `regcheck.out.txt` | `75e40784d0f852d826085f862f03f5944300dce01bee4469f099e1b6ca0b4031` |

`w5v3_calc.py` makes every figure of this appendix. `recheck.py` is the forking-path check's
independent recomputation (seeds 777 and 4242), which matched every figure within Monte Carlo
error. `w5_calc.py` is version 2's script and `regcheck.py` version 2's checker's
recomputation of it; they are filed for the figures carried from version 2 (below).

Notes: in part 4, the last column is "any decisive word" when delta is 0, which is the false
call rate at a null effect; for a negative delta it is a decisive word of the wrong sign. The
known-answer sets in part 6 are written in points. In part 2, "lift over 130.02" is the line
minus $130.02, as in section 7.3; the bracketed "high minus 130.02" is shown for reference only.
In part 5, P(Worse) counts every Worse word, so at delta 0 it is the false-Worse rate (0.009
in both rows); it was printed as 0.000 by construction before review. Each part's first line
is its claim tag, printed by the script, with its method and its sample size or seed.

```
======== 1. C1 in C2 order and L2, recomputed
[hypothesis — design input: sha256 over the 12 C1 and 11 L2 names; exact arithmetic on stated inputs, no sample; not a measurement of the product]
sha256(C1 in C2 order) = b38fb8b6b8de3bf50ebc88b54e6dd54c1d9578bc2c5209c47fcc8350a612a1de match: True
L2 order unchanged: True
sha256(L2 in hash order) = c62cf5f1f39b336e9842b43beb9794cf848051bb84078ba1331213bfa84e8145 match: True
seeded-order key example (R11 item 5, Wave 4 part 2 step 2): crb.reading.v1|<repo>|<cell key>|<commit>

======== 2. Costs, product dollars, unconfirmed
[hypothesis — cost and time projection from Wave 4's rate over 120 commit-arms and its 49 runs; unconfirmed]
rate per commit-arm (2 attempts) = 48.115522/120 = 0.400963; left = 130.02
high per full repository = 6 commits x 2 arms x 0.400963 x 2.5 = 12.0289
pilot high = 8 x 0.400963 x 2.5 = 8.0193
 n | commit-arms | central  | high     | line(ceil high) | lift over 130.02
 6 |          80 |    32.08 |    80.19 |              81 | 0.00  (high minus 130.02 = -49.83)
 7 |          92 |    36.89 |    92.22 |              93 | 0.00  (high minus 130.02 = -37.80)
 8 |         104 |    41.70 |   104.25 |             105 | 0.00  (high minus 130.02 = -25.77)
 9 |         116 |    46.51 |   116.28 |             117 | 0.00  (high minus 130.02 = -13.74)
10 |         128 |    51.32 |   128.31 |             129 | 0.00  (high minus 130.02 = -1.71)
11 |         140 |    56.13 |   140.34 |             141 | 10.98  (high minus 130.02 = +10.32)
12 |         152 |    60.95 |   152.37 |             153 | 22.98  (high minus 130.02 = +22.35)
thinnest R11 repository (1 XS + 1 S): 2 commits x 2 arms = 4 commit-arms, central 1.60, high 4.01
repository-boundary stop with line 129: start repository j only if spend + 12.0289 <= 129
  after pilot +  0 repos at high: spend    8.02; next starts: True
  after pilot +  1 repos at high: spend   20.05; next starts: True
  after pilot +  2 repos at high: spend   32.08; next starts: True
  after pilot +  3 repos at high: spend   44.11; next starts: True
  after pilot +  4 repos at high: spend   56.13; next starts: True
  after pilot +  5 repos at high: spend   68.16; next starts: True
  after pilot +  6 repos at high: spend   80.19; next starts: True
  after pilot +  7 repos at high: spend   92.22; next starts: True
  after pilot +  8 repos at high: spend  104.25; next starts: True
  after pilot +  9 repos at high: spend  116.28; next starts: True
  after pilot + 10 repos at high: spend  128.31; next starts: False
time D3 n=6: 80 commit-arms x 2 x 2.464 min = 6.6 h
time D3 n=10: 128 commit-arms x 2 x 2.464 min = 10.5 h
D1 n=10 m=10 (A0,S1): 208 commit-arms, central 83.40, high 208.50, line 209, lift 78.98
D1 n=7  m=10 (A0,S1): 148 commit-arms, central 59.34, high 148.36, line 149, lift 18.98
D2 n=10 m=10 (A0,S1,W; pilot 10 commits x 4 arms): 340 commit-arms, central 136.33, high 340.82, line 341, lift 210.98
D2 n=7  m=10 (A0,S1,W; pilot 10 commits x 4 arms): 250 commit-arms, central 100.24, high 250.60, line 251, lift 120.98
D2 S1 attempts n=10: (100 + 10) x 2 = 220 ; author central = 0.305

======== 3. Power at q = 11/12, n = 6..12, alpha 0.05 (J = 1)
[hypothesis — method A exact binomial; method B 4,000 simulated waves a cell, seed 20261123; simulation under stated assumptions, not a measurement of the product]
method A: exact sign test, equal magnitudes (binomial); method B: exact sign-flip,
unit difference ~ Normal(z,1), z = Phi^-1(11/12) = 1.3830, 4000 waves a cell, seed 20261123
n= 6: A 0.593 (needs >= 6 of 6 same sign) | B 0.595 (MC s.e. 0.008) | p_min 2/2^n = 0.031250
n= 7: A 0.544 (needs >= 7 of 7 same sign) | B 0.826 (MC s.e. 0.006) | p_min 2/2^n = 0.015625
n= 8: A 0.499 (needs >= 8 of 8 same sign) | B 0.900 (MC s.e. 0.005) | p_min 2/2^n = 0.007812
n= 9: A 0.831 (needs >= 8 of 9 same sign) | B 0.941 (MC s.e. 0.004) | p_min 2/2^n = 0.003906
n=10: A 0.800 (needs >= 9 of 10 same sign) | B 0.973 (MC s.e. 0.003) | p_min 2/2^n = 0.001953
n=11: A 0.768 (needs >= 10 of 11 same sign) | B 0.985 (MC s.e. 0.002) | p_min 2/2^n = 0.000977
n=12: A 0.928 (needs >= 10 of 12 same sign) | B 0.991 (MC s.e. 0.001) | p_min 2/2^n = 0.000488

======== 4. Discrete simulation of the D3 read, n = 6..12 (model as v2 appendix A part 6)
[hypothesis — 1,000 simulated waves a cell, seed 20261133; simulation under stated assumptions, not a measurement of the product]
A0 repo mean ~ N(0.7,0.15) clipped; commit chance Beta, ICC 0.25; S1 shift per repo
~ N(delta, tau_e); 2 attempts/arm; m = 6; 1,000 waves a cell; seed 20261133
cols: P(correct Better/Worse) | P(Within 15) | P(Undecided) | P(Undecided and n' < 6) | P(wrong-sign decisive)
tau_e=0.10 delta=+0.00 n= 6: 0.000 | 0.027 | 0.967 | 0.771 | 0.006
tau_e=0.10 delta=+0.00 n= 7: 0.000 | 0.135 | 0.853 | 0.450 | 0.012
tau_e=0.10 delta=+0.00 n= 8: 0.000 | 0.290 | 0.684 | 0.220 | 0.026
tau_e=0.10 delta=+0.00 n= 9: 0.000 | 0.441 | 0.537 | 0.088 | 0.022
tau_e=0.10 delta=+0.00 n=10: 0.000 | 0.549 | 0.416 | 0.032 | 0.035
tau_e=0.10 delta=+0.00 n=11: 0.000 | 0.636 | 0.316 | 0.018 | 0.048
tau_e=0.10 delta=+0.00 n=12: 0.000 | 0.728 | 0.243 | 0.006 | 0.029
tau_e=0.10 delta=-0.25 n= 6: 0.392 | 0.000 | 0.608 | 0.388 | 0.000
tau_e=0.10 delta=-0.25 n= 7: 0.630 | 0.002 | 0.368 | 0.122 | 0.000
tau_e=0.10 delta=-0.25 n= 8: 0.808 | 0.000 | 0.192 | 0.023 | 0.000
tau_e=0.10 delta=-0.25 n= 9: 0.852 | 0.000 | 0.148 | 0.004 | 0.000
tau_e=0.10 delta=-0.25 n=10: 0.931 | 0.002 | 0.067 | 0.001 | 0.000
tau_e=0.10 delta=-0.25 n=11: 0.944 | 0.002 | 0.054 | 0.000 | 0.000
tau_e=0.10 delta=-0.25 n=12: 0.972 | 0.001 | 0.027 | 0.000 | 0.000
tau_e=0.10 delta=-0.46 n= 6: 0.863 | 0.000 | 0.137 | 0.098 | 0.000
tau_e=0.10 delta=-0.46 n= 7: 0.985 | 0.000 | 0.015 | 0.007 | 0.000
tau_e=0.10 delta=-0.46 n= 8: 0.997 | 0.000 | 0.003 | 0.000 | 0.000
tau_e=0.10 delta=-0.46 n= 9: 1.000 | 0.000 | 0.000 | 0.000 | 0.000
tau_e=0.10 delta=-0.46 n=10: 1.000 | 0.000 | 0.000 | 0.000 | 0.000
tau_e=0.10 delta=-0.46 n=11: 1.000 | 0.000 | 0.000 | 0.000 | 0.000
tau_e=0.10 delta=-0.46 n=12: 1.000 | 0.000 | 0.000 | 0.000 | 0.000
tau_e=0.20 delta=+0.00 n= 6: 0.000 | 0.009 | 0.984 | 0.679 | 0.007
tau_e=0.20 delta=+0.00 n= 7: 0.000 | 0.062 | 0.916 | 0.329 | 0.022
tau_e=0.20 delta=+0.00 n= 8: 0.000 | 0.103 | 0.875 | 0.145 | 0.022
tau_e=0.20 delta=+0.00 n= 9: 0.000 | 0.227 | 0.746 | 0.058 | 0.027
tau_e=0.20 delta=+0.00 n=10: 0.000 | 0.268 | 0.692 | 0.015 | 0.040
tau_e=0.20 delta=+0.00 n=11: 0.000 | 0.329 | 0.630 | 0.007 | 0.041
tau_e=0.20 delta=+0.00 n=12: 0.000 | 0.401 | 0.553 | 0.003 | 0.046
tau_e=0.20 delta=-0.25 n= 6: 0.227 | 0.000 | 0.773 | 0.456 | 0.000
tau_e=0.20 delta=-0.25 n= 7: 0.423 | 0.001 | 0.576 | 0.135 | 0.000
tau_e=0.20 delta=-0.25 n= 8: 0.550 | 0.002 | 0.448 | 0.032 | 0.000
tau_e=0.20 delta=-0.25 n= 9: 0.668 | 0.008 | 0.324 | 0.003 | 0.000
tau_e=0.20 delta=-0.25 n=10: 0.763 | 0.003 | 0.234 | 0.001 | 0.000
tau_e=0.20 delta=-0.25 n=11: 0.796 | 0.003 | 0.201 | 0.000 | 0.000
tau_e=0.20 delta=-0.25 n=12: 0.855 | 0.001 | 0.144 | 0.000 | 0.000
tau_e=0.20 delta=-0.46 n= 6: 0.693 | 0.000 | 0.307 | 0.180 | 0.000
tau_e=0.20 delta=-0.46 n= 7: 0.930 | 0.000 | 0.070 | 0.013 | 0.000
tau_e=0.20 delta=-0.46 n= 8: 0.974 | 0.000 | 0.026 | 0.002 | 0.000
tau_e=0.20 delta=-0.46 n= 9: 0.994 | 0.000 | 0.006 | 0.000 | 0.000
tau_e=0.20 delta=-0.46 n=10: 0.996 | 0.000 | 0.004 | 0.000 | 0.000
tau_e=0.20 delta=-0.46 n=11: 0.999 | 0.000 | 0.001 | 0.000 | 0.000
tau_e=0.20 delta=-0.46 n=12: 0.999 | 0.000 | 0.001 | 0.000 | 0.000

======== 5. One thin R11 repository (m_r = 2: one XS, one S) among n = 7, tau_e 0.10
[hypothesis — 1,000 simulated waves a cell, seed 20261143; simulation under stated assumptions, not a measurement of the product]
P(Worse) counts every Worse word, so at delta 0 it is the false-Worse rate
delta=+0.00 thin repos=0: P(Worse)=0.009 P(Within 15)=0.114
delta=+0.00 thin repos=1: P(Worse)=0.009 P(Within 15)=0.056
delta=-0.46 thin repos=0: P(Worse)=0.987 P(Within 15)=0.000
delta=-0.46 thin repos=1: P(Worse)=0.967 P(Within 15)=0.000

======== 6. Known-answer sets K1..K7 through the registered word rule (J = 1)
[hypothesis — seven synthetic sets, exact sign-flip and t; exact arithmetic on stated inputs, no sample; not a measurement of the product]
K1 eight repos all -50: D=-50.0000 p=0.0078125 (2/256) nonzero=8 90% half-width=0.0000 -> Worse
K2 eight repos +-10 alternating: D=+0.0000 p=1.0000000 (256/256) nonzero=8 90% half-width=7.1608 -> Within 15
K3 six repos, one 0, five -40: D=-33.3333 p=0.0625000 (4/64) nonzero=5 90% half-width=13.4337 -> Undecided
K4 seven repos all +30: D=+30.0000 p=0.0156250 (2/128) nonzero=7 90% half-width=0.0000 -> Better
K5 ten repos, nine -20 one +10: D=-17.0000 p=0.0039062 (4/1024) nonzero=10 90% half-width=5.4993 -> Worse
K6 = K2 with usable-test share 0.85 (P3 fails): D=+0.0000 p=1.0000000 (256/256) nonzero=8 90% half-width=7.1608 -> Undecided
K7 r1: m_r=2, registered rows/arm=4, A0 clean=3, S1 clean=1, D_r=-50.0000
K7 r2: m_r=6, registered rows/arm=12, A0 clean=9, S1 clean=5, D_r=-33.3333
K7 r3: m_r=6, registered rows/arm=12, A0 clean=9, S1 clean=5, D_r=-33.3333
K7 r4: m_r=6, registered rows/arm=12, A0 clean=9, S1 clean=5, D_r=-33.3333
K7 r5: m_r=6, registered rows/arm=12, A0 clean=9, S1 clean=5, D_r=-33.3333
K7 r6: m_r=6, registered rows/arm=12, A0 clean=9, S1 clean=5, D_r=-33.3333
K7 six repos, unequal counts: D=-36.1111 p=0.0312500 (2/64) nonzero=6 90% half-width=5.5974 -> Worse
check t(0.95,5) = 2.015  t(0.95,7) = 1.8946  t(0.95,9) = 1.8331
```

Two figures in part 5 differ from part 4 for the same cell (P(Within 15) at δ 0, n 7: 0.114
against 0.135; P(Worse) at −46: 0.987 against 0.985). They come from separate random streams
of 1,000 waves; the gap is within Monte Carlo error (s.e. about 0.011 and 0.004)
**[measured — n = 1,000 simulated waves a cell, method: discrete simulation in appendix A parts 4
and 5, re-run with python3 -I and compared byte for byte, apparatus n/a]**.

Figures carried unchanged from version 2 (script `w5_calc.py` and its output
`w5_calc.out.txt`, filed beside this page, independently matched by the checker's
`regcheck.py`, output `regcheck.out.txt`): the per-name C1 and L2 hashes (part 1), the t
quantiles (part 3), and the q(m) normal-model table (part 5). Version 2's part 7 (W pilot
rule) and its D2 figures at n = 7 are withdrawn. On review, `w5_calc.py` part 6 now counts
Within 15 at every effect (it had counted it only at effect 0) and prints the seed it uses,
20261114; none of part 6's figures is quoted on this page **[measured — n = 1 file, method:
code read of `w5_calc.py` and a re-run with `python3 -I`, compared byte for byte twice,
apparatus n/a]**.

## Closing table: findings and rulings to sections

| Item | What it asked | Closed in |
|---|---|---|
| F-A | Commit order must be the product's seeded order (R11 item 5) | 6.1 |
| F-B | C1 bar exactly R11's; a C1 name with 1 to 3 commits a cell is not dropped | 5.2, 5.3, 3.1, 4.3 K7 |
| F-C | Calibrations and P5 before the first counted run; no repair after | 4.1, 4.2, 4.4, 9.1, 10 |
| F-D | Zero counts: signatures only before; new zero makes Invalid | 9.3 (frozen W0) |
| F-E | Lists and sha256s before the first run; every candidate reported; "tuned" defined | 4.2 steps 3, 5, 8; 5.4; 5.6 |
| F-F | "Cheapest" claim corrected; n is min(passes, 10), not 7 | 7.4, 7.1 |
| F-G | Power at the floor; Undecided also from too few repositories | 1.4, 7.4, 8.2 |
| F-H | No line lift after a money stop; builder provider errors classified | 8.1, 8.2, 8.3 |
| F-I | AST rule narrow | 9.2 |
| F-J | Dangling "closing note"; conflict mislabelled as with R11 | 5.1 |
| F-K | D2 arithmetic at n = 7; S1 attempts; W pilot model | 7.5; W rule withdrawn (2) |
| F-L | L2 membership choice; boltons licence; K sets miss P3 | 5.5, 5.2 check 6, 4.3 |
| R-F1 | Untuned repository can leave the count silently | 5.1, 5.3 (outstanding), 6.2 (runs first), 8.2, 5.4 (no replacement) |
| R-F2 | Controls must not change a pool or n | 4.1 (one qualify record; conflict with FP-H5 resolved there) |
| R-F3 | Seeded-order clause in full; same posture; no re-qualify path | 4.2 steps 2-3, 5.2, 5.4, 6.1 |
| R-F4 | R11 item 7: new budget line to Paul with a figure | 0, 4.2 step 8a, 8.1, Q20 |
| R-F5 | Lists appended to the registration, not only filed | 4.2 step 8c, 5.6 |
| R-F6 | "On commits no seat has read" | 5.7, P9 |
| R-F7 | Cell class not closed | 5.2, Q18 (decided by the MD 2026-11-13) |
| R-F8 | Eligibility re-checked before the freeze | 5.7, 4.2 steps 8b and 10 |
| R-F9 | Cut stated as a rule | 6.1 |
| R-F10 | Wave 5 is "the next certifying reading" | 0 |
| R-F11 | Fixed order of checks | 5.2, 5.6 |
| FP-H1 | P3 had two words | 3.3 item 1, 9.1 |
| FP-H2 | Discretionary lowering amendment | 10, Q17 |
| FP-H3 | why_zero written at read time | 9.3 (frozen W0, W0_CAL) |
| FP-H4 | Repositories leave through operator choices | 6.2 (driver, no-row at close, run id rule), P2 |
| FP-H5 | Gold-against-empty had no defined fate | 4.1, 5.2 |
| FP-H6 | Pilot by arm visible while things can change | 4.2, 5.4, 6.3 |
| FP-H7 | "Exactly the expected output" was a judgement | 4.2 steps 5-6, 4.4, P4 |
| FP-M1 | Positive-control exits; dependence on live service | 9.2, P5 |
| FP-M2 | A row could read two ways | 3.1, 8.3, 11.1 |
| FP-M3 | Untuned repository last in run order | 6.2 |
| FP-M4 | Re-qualify; apparatus version; classifier | 5.2, 5.6, P8 |
| FP-M5 | "Spend so far" source | 8.2 |
| FP-M6 | "Suite runs" and licence were judgements | 5.2 checks 3 and 6, 5.4 |
| FP-M7 | Q18, Q19 still flagged | 12 (both decided by the MD 2026-11-13) |
| FP-L1 | "Lift" meant two things | 7.3, appendix A note |
| FP-L2 | Probe evidence weaker than it read | 9.2 (conforming probes) |
| FP-L3 | "At most 0.048" is Monte Carlo | 7.4 |
| FP-L4 | Lists appended | 4.2 step 8c |
| FP-L5 | Wave 4 figures not independently checked | 0 (tag says so) |
| M1 | D3 chosen; D1, D2 costed only; no weak-model arm; $0 calibrations kept | 2, 4.1, 4.3, 7.1, 7.5 |
| M2 | Honour R11 exactly; say what it requires of C1 names | 5.1, 5.3, 7.3 |
| M3 | Seeded order; R11's bar; thin C1 names without a forking path | 5.2, 5.3, 6.1 |
| M4 | $0 checks and positive control before the first run; freeze; live dry run | 4.2, 9.1, 9.2 |
| M5 | Waiver list fixed before the first run; unlisted zero makes Invalid | 9.3 |
| M6 | Lists and sha256s; candidate report; onboarding rule | 4.2, 5.4, 5.6 |
| M7 | Power n = 6..12 with method; Undecided causes; no lift after a stop; F-I to F-L | 1.4, 7.4, 8.1, 8.2, 9.2, 5.1, 7.5, 5.5 |
| M8 | Harness-fault stop: mechanical and arm-blind, or removed | 8.3 (removed; faulty rows are failures for their arm) |
| M9 | Claim words "passes the held-out tests"; blind review and audit as a secondary | 0, 1.1, 1.3, 11.2 |
| Rulings 09:45Z | Q17 to Q20, item 5, qualify record, item 6 (W0, W0_CAL), A3, blind reviewer | head, 0, 4.1, 4.2, 4.5, 5.2, 5.4, 6.2, 8.1, 9.3, 10, 11.2, 12 |
| RR1 | Spend figure tagged measured; "goes to Paul with a figure" | 0 (retagged; freeze quotes the figure, step 8a) |
| RR2 | Pinning rule for the preflight not asked for | 4.2 step 5, 9.2 (Q27) |
| RR3 | A3 repeat not a step; no row rule or runner | 4.2 step 0, 4.5 (Q31) |
| RR4 | Spend so far tagged as measured | 0 |
| RR5 | Arms not defined as run bodies | 6.4 (Q28) |
| RR6 | Check 4 search method and exclusions | 5.2 check 4, 5.4 (Q35) |
| RR7 | "Listed" meant two things | 6.1, 5.7, 4.1, P4 |
| RR8 | Never-waivable counts and labels not exact | 9.3 (Q41) |
| RR9 | Refused submissions resubmitted without limit | 6.2, 8.2 (Q29) |
| RR10 | Served qualify-record fields checked too late | 4.1, 4.2 step 3, 6.3 |
| RR11 | Q4 fallback names no person | 0 |
| RR12 | "The operator" and the $129 not held | 0, 8.1, 4.2 steps 8a and 10 (Q26, Q38) |
| RR13 | Read-script repair without re-running steps 6 and 7 | 4.2 step 10, 9.2 |
| RR14 | Preflight only in an open PR | 4.2 step 5, 9.2 (Q27) |
| RR15 | Positive control passes on any exit 6 | 9.2 (`line N:` rule) |
| RR16 | Arithmetic not fully specified | 3.4 (Q32) |
| RR17 | t interval "never changes the word" and decides Within 15 | 1.2 |
| RR18 | Checks 3, 4 and 8 not mechanical | 5.2 checks 3, 4 and 8, 4.2 step 3 (Q33, Q35, Q40) |
| RR19 | Deployed code not pinned | 6.4, 4.2 steps 0 and 3, P8 (Q37) |
| RR20 | Driver not bound to the preflight | 6.2, 6.3, 8.2, 9.2 |
| RR21 | No read trigger | 3.5 (Q39) |
| RR22 | Untuned repository could leave before the freeze | 5.7, 3.1 (Q34) |
| RR23 | Usable test names no field | P3 in 9.1, 9.3 (Q41) |
| RR24 | Empty arm's clean derived without a rule | 4.1 |
