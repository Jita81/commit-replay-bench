# Evidence and claims policy

*What `crb` may say about a number, and what it must never say.* Condensed from the
production-validation standard (gates G0–G8), the evidence-campaign gates ("evidence
expires") and the claim–evidence contract. This policy binds the product's UI, its exports,
this repository's documentation, and anyone quoting a `crb` figure.

**The rule in one line: a number without its method is a slogan.** Every figure carries
its numerator, its denominator `n`, its Wilson 95% interval, the apparatus version that
produced it, and the mode (sighted / blind) and builder it applies to.

Contents: [1 Claim tags](#1-claim-tags) · [2 CLEAN, semantic Q1, false-Q1](#2-clean-semantic-q1-and-false-q1) ·
[3 Every number carries its method](#3-every-number-carries-its-method) ·
[4 The apparatus stamp — evidence expires](#4-the-apparatus-stamp--evidence-expires) ·
[5 The legacy-belt caveat](#5-the-legacy-belt-caveat-on-the-census-ledger) ·
[6 Permitted claim shapes](#6-permitted-claim-shapes-by-maturity) ·
[7 What must never be said](#7-what-must-never-be-said) · [8 Principles](#8-validation-principles-we-inherit)

---

## 1. Claim tags

Every claim in this repository — README, ADRs, architecture, UI copy — carries one tag:

| Tag | Meaning | What it must cite |
|---|---|---|
| `[measured]` | Backed by ledger rows that can be re-derived. | `n`, the method (which belts, which mode, which builder/model), the Wilson interval, the apparatus version, and where the rows are. |
| `[hypothesis]` | Directionally supported; not confirmed by a pre-registered or replicated measurement. | The evidence so far and what would confirm or falsify it. |
| `[aspiration]` | Designed for; not demonstrated. | The design (ADR, plan phase). |

A claim moves from `[hypothesis]` to `[measured]` only by a pre-registered measurement whose
interval excludes a trivial effect and that has been replicated or independently re-run;
one sample, however clean, promotes to "replication pending", never to settled. A claim
never moves the other way silently: when its apparatus changes it becomes **stale** (§4)
and is re-tagged.

## 2. CLEAN, semantic Q1, and false-Q1

`crb` uses the validation standard's vocabulary and does not blur it.

| Term | Definition | Who decides |
|---|---|---|
| **CLEAN** | All four mechanical belts hold (`tests_unmodified`, `target_green`, `no_new_failures`, `source_changed`), the trial is not disqualified, no harness error, and an evidence pack exists. | The grader, mechanically (`crb.core.grade`). |
| **Semantic Q1** | CLEAN **plus**: the oracle is adequate for the change (strength ≥ 0.80 when measured), no prohibited test manipulation, security gates pass, provenance complete, no critical unresolved ambiguity, the route permits it, and the change is within the validated envelope. | The routing rule plus, for production use, an independent audit. |
| **False-Q1 (mechanical)** | A row credited `clean` that its own recorded belts contradict. **Must be 0**; cannot be constructed (`FalseQ1Violation`) or written (`GradeRow.assert_invariants`). | Enforced in code; re-checked at read time (`cell_stats.false_q1`, `false_q1_total`). |
| **False-Q1 (audited, semantic)** | A Q1 accepted for delivery in which an independent assessment later finds a defect that should have blocked acceptance. | Independent human or hidden-evidence audit. |

### Severity ladder for audited false-Q1

| Class | Meaning |
|---|---|
| **FQ1-S1** | Security / safety / data corruption / catastrophic. |
| **FQ1-S2** | Material user-visible or business defect. |
| **FQ1-S3** | Limited functional defect. |
| **FQ1-S4** | Minor quality issue. |

**Vocabulary rule.** "False-Q1 = 0" may be used **only** for one of two precisely stated
things: (a) *mechanical*: "0 recorded `clean` rows violate their recorded acceptance
predicates" — which `crb` enforces and can prove from any export; or (b) *audited
semantic*: "0 S1/S2 defects across N independently audited Q1 acceptances (CI reported)".
The two are never conflated. A green suite is evidence that the change satisfies the
suite; it is not proof of semantic correctness.

## 3. Every number carries its method

The product shows, for every cell and every aggregate:

| Field | Source | Why |
|---|---|---|
| `n` | `CellStats.n` — eligible trials (not disqualified; `gold_clean` is not `False`). | The denominator is the claim. Disqualified and gold-failed tasks are shown beside `n`, not hidden in it. |
| `clean`, `point` | `clean / n`. | The numerator and the proportion. |
| `ci_low`, `ci_high` | Wilson score interval, z = 1.96 (`crb.core.stats.wilson_interval`). | Small `n` shows as a wide interval; `n ≤ 0` shows `[0, 1]`. |
| `false_q1` | Read-time re-derivation. | Must display 0; anything else is a stop condition. |
| `disqualified`, `errors` | Counts. | A harness bug shows here, never as a higher pass rate. |
| `cost_usd_mean`, `latency_s_mean` | Means over trials that recorded them. | Economics travel with quality. |
| `oracle_strength_mean` or "not measured" | Hygiene-adjusted mutant kill-rate (P2). | A verdict from a weak oracle certifies less. |
| `apparatus_versions` | The set of `apparatus_version` values in the cell. | Mixed versions are visible, not blended (§4). |
| `mode`, `builder`, `model`, `provider` | Cell key. | A sighted rate is not a blind rate; builder A's rate is not builder B's. |

Aggregates across cells are shown only with their component cells reachable; an aggregate
without a breakdown is not published. Where observations cluster by repository, the
breakdown by repository is shown and the headline must survive removing the strongest
repository.

**Attempt budgets.** Every experiment reports attempt-1, ≤2, ≤3 and full-budget success
separately. "Task solve rate under budget" is never labelled first-pass accuracy. Failed
attempts, timeouts and infrastructure failures stay in the denominators and the cost.

## 4. The apparatus stamp — evidence expires

Every grade row and every evidence pack carries an `ApparatusStamp`
(`crb.core.evidence.ApparatusStamp`):

```
apparatus_version:  2.0                 # grader semantics, belt set, size table, taxonomy, routing rule
crb_version:        2.0.0a0
grader:             crb.core.grade
runner:             pytest | go | node | vitest | jest | mocha | maven | cargo (+ options)
executor:           {executor: docker, image, user, memory, cpus, pids_limit, network: none}
corpus_sha:         <hash of the task set, when sealed>
policy_version:     routing.v1
```

**Evidence expires when the conditions that produced it change.** When any stamped
component changes — apparatus version, grader semantics, runner behaviour, executor,
corpus, routing policy, or the builder's model id — prior evidence downstream of that
component becomes **stale**: citable as history, dead as a basis for routing until
re-measured. A result quoted without its stamp is an anecdote.

`APPARATUS_VERSION` bumps only with an ADR. Model changes are recorded on the cell key
(`model`, `provider`), so a new model id is a new cell; no capability is inherited.

## 5. The legacy-belt caveat on the census ledger

The census ledger that seeds this product (`grades.jsonl`, **1,071 rows**) was produced by
the upstream apparatus. **706 of the 1,071 rows were graded under three belts before belt 4
(`source_changed`) existed; 365 carry all four.** `[measured]` from the file itself: the
`source_changed` key is present on 365 rows and absent on 706.

The product handles this as follows and it is not configurable:

- Legacy rows are imported with `belt_set = "v3-legacy"`, `apparatus_version = "1.0-census"`
  and `provenance = "imported:…"`. The false-Q1 invariant is applied to the **three belts
  they recorded** (`GradeRow.recorded_belts`); a clean legacy row with any of those three
  belts not `True` is refused at import.
- Cells report legacy and v4 rows **separately**; `apparatus_versions` on a cell makes any
  mixture visible, and the UI does not combine them into one point estimate.
- **No claim blends apparatus versions.** "Under apparatus 1.0-census, cell X was …" and
  "under apparatus 2.0, cell X is …" are two statements.
- The plan's P1 gate re-derives all 1,071 rows: `clean == all recorded belts True` and no
  clean row has a false belt. That gate proves the *mechanical* false-Q1 = 0 statement
  about the seed data; it says nothing about the fourth belt on the 706 rows, which is
  simply unmeasured for them.

## 6. Permitted claim shapes, by maturity

| Stage passed | Permitted claim shape |
|---|---|
| Retrospective sighted replay (the census; `crb` P1–P3) | "Under apparatus V, builder B (model M) reproduced X% (n, Wilson CI) of the measured **retrospective commit-replay** corpus for cell C, graded by the repository's own held-out tests; false-Q1 (mechanical) = 0." |
| Blind replay (`mode = blind`) | "X% task success (n, CI) on a held-out evaluation where the decisive historical tests were **hidden during implementation**." |
| Oracle adequacy measured (P2) | "…of which cells with oracle strength ≥ 0.80 (hygiene-adjusted mutant kill-rate) are routed `deliver`; cells below are routed `human`." |
| Pre-registered prospective validation | "Under a pre-registered frozen policy, `crb` routed future work into populations with measured prospective outcomes of X, Y, Z." |
| Independent semantic Q1 audit | "Across N independently audited Q1 acceptances, X contained material semantic defects (CI reported, by severity)." |
| Production shadow mode | "On live work, the factory reduced measured human finishing/review effort by X% at Y quality." |
| Controlled autonomous delivery | "Within the explicitly validated capability envelope, the factory autonomously delivered N production changes with X observed material false-Q1 outcomes." |

A `deliver` route from the routing rule means **"high-confidence candidate under the
published bar"**; until prospective and audited evidence exists it does not mean
"autonomous delivery is safe". `calibrate` and `human` routes are product successes
(refusals), reported with the same rigour as passes.

### 6a. What a signed cell may be claimed to mean (`signoff-policy.v1`)

A human sign-off lifts a cell's **verification tier** (`automated-pass` →
`human-verified` / `ab-confirmed`); it never lifts its route, its point or its interval.
Since `signoff-policy.v1` (DL-014) a sign-off is a *policy decision refused at write*
(`crb.core.signoff`), so a signed cell licenses exactly this claim shape:

> "Under apparatus V, cell C of repo R (n, point, Wilson lower — all ≥ the published
> bar: n ≥ 10, point ≥ 0.90, lower ≥ 0.80, false-Q1 = 0, route `deliver`) was signed off
> by a named approver on date D under `signoff-policy.v1`, with the repository's
> negative-controls gate **passed, k of N constructible, 0 escapes** (controls run X), and
> the approver's attestation that they read accepted row H (task T)."

Every word of that sentence is a field of the record (`policy_version`,
`policy_thresholds`, `route_reason_code`, `controls_*`, `attestation`), hash-chained with
the sign-off and served back verbatim by `GET /signoffs/{id}`. What it does **not** mean:

- that the cell is safe for autonomous delivery (§6 still applies: `deliver` is a
  high-confidence candidate under the published bar, not a safety claim);
- that every accepted change in the cell was read — the attestation names **one** row;
  a per-change human verdict is the `review` row type (Wave B13), not the sign-off;
- that the cell stays signed: a later false-Q1 row invalidates the attestation at read
  (`active: false`), an apparatus bump makes its snapshot stale (§4), and a revocation
  is one append away.

A deployment may relax the numeric thresholds and the route / controls switches within
the published bounds (`docs/API.md`, `/signoffs/policy`); a record then says so
(`policy_thresholds` differs from the defaults, `relaxed: true` on the policy) and any
quote of it must name the relaxed bar. Two clauses have no knob and never will: a
false-Q1 cell cannot be signed, and a sign-off without an attestation cannot be made.
A record signed before the policy (`schema: crb.signoff.v1`) carries no policy snapshot
and may only be quoted as "signed before `signoff-policy.v1`".

## 7. What must never be said

- **"Delivers unseen software correctly 97.5% of the time."** — or any rate from a sighted,
  retrospective corpus presented as blind or prospective capability. The permitted form is
  in §6, row 1, and it names the apparatus, the corpus, the cell and `n`.
- That a green repository test suite proves complete semantic correctness.
- That retrospective public commits are contamination-free.
- That success after any number of attempts equals first-pass accuracy.
- That a 100% result from a small sample predicts 100% future reliability (the Wilson
  interval is the claim, not the point).
- That performance on a handful of repositories proves universal reliability; that
  performance on ≤ 3-file changes extends to arbitrary scale.
- That a classification label produced by heuristics or a model is ground truth.
- That a model-generated test is trustworthy because another model approved it.
- That passing the historical test proves equivalence to the historical patch.
- That an aggregate success rate makes every cell inside it safe for automated delivery.
- Any rate without `n`, interval, mode, builder/model and apparatus version.
- Anything that blends `1.0-census` and `2.0` apparatus rows into one number.

## 8. Validation principles we inherit

1. **Freeze before measure** — release, prompts, routing policy, classifier, model ids,
   budgets, thresholds, exclusion rules. A change creates a new experimental version.
2. **Register exclusions before outcomes** — post-outcome exclusions are barred from
   headline metrics.
3. **Preserve every failure** — failed attempts, timeouts, infrastructure failures,
   invalid patches, tampering attempts, budget exhaustion, escalations.
4. **Independent evidence beats correlated judgement** — no production claim rests solely
   on model-generates → model-reviews → model-approves; the repository's own tests, run
   mechanically, are the independent mechanism.
5. **Report uncertainty** — numerator, denominator, CI, source, route, attempt budget;
   clustered analysis where observations cluster by repository.
6. **Prefer explicit escalation to unsupported confidence** — no infrastructure failure
   may silently become Q1; the run stops (`SandboxUnavailable`) or the row records an
   error.
7. **The system must be capable of becoming less autonomous** — a later row can demote a
   cell; a stop condition (any false-Q1, sandbox escape, ledger chain break, secret in an
   artefact) halts delivery until root cause, correction and re-qualification.

Related: [ADR-0001](adr/0001-four-belts-and-false-q1-at-write.md) ·
[ADR-0003](adr/0003-one-routing-rule.md) · [ARCHITECTURE §7.4](ARCHITECTURE.md#74-versioning) ·
[OPERATOR](OPERATOR.md).
