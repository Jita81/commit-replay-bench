# The value baseline — working changes per pound, blind — 2026-09-25

**Question asked.** The operator, 2026-09-25: the product has gained features and lost the
value; it must produce working software, and its self-learning must get better the more data
goes through it. Before any change can be judged, how much working software does it produce
today for each pound, and is anything it learns stopping a bug from coming back?

**Claims in this record.** Every figure below is **[measured — n = 618 graded rows exported
from the operator's stack on 2026-09-25 (`GET /ledger/export`, pipe-separated projection) and
n = 10 review records from its review store, plus the three cobra verdicts of
[the critical-friend review](2026-09-13-critical-friend.md) §3; method: `scripts/value_baseline.py`
running `crb.core.value.value_report` over the files, every row's failure kind recomputed with
the product's own rule (`derive_failure_kind`); builder claude_code with claude-sonnet-5;
apparatus 2.2 in the headline table, apparatus 2.0–2.2 pooled in the second]**. The export
files are the operator's ledger and are not in this repository. The two headline figures are
products of two measured rates and are labelled as estimates wherever they appear.

## The baseline

**About 7% of blind attempts would produce a change a maintainer would merge, which is about
one working change for every £5 spent on blind attempts [measured — n = 94 valid blind
attempts under apparatus 2.2 × n = 13 reviewed clean patches; method: blind clean rate ×
reviewed clean → mergeable rate, the interval the product of the two Wilson bounds; apparatus
2.2].** The range is wide — from about £1.84 to about £17 per working change — because the
review sample is small. The figures under apparatus 2.2 are:

| measure | value | n / method / apparatus 2.2 |
|---|---|---|
| rows / valid observations | 518 / 259 | n = 518 rows; valid = not outage, harness, disqualified or a failed gold; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, all valid | 155 / 259 = 59.9% (Wilson 95% 53.8%-65.6%) | n = 259; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, sighted | 133 / 165 = 80.6% (Wilson 95% 73.9%-85.9%) | n = 165; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind | 22 / 94 = 23.4% (Wilson 95% 16.0%-32.9%) | n = 94; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind XS | 13 / 23 = 56.5% (Wilson 95% 36.8%-74.4%) | n = 23; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind S | 7 / 30 = 23.3% (Wilson 95% 11.8%-40.9%) | n = 30; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind M | 2 / 24 = 8.3% (Wilson 95% 2.3%-25.9%) | n = 24; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind L | 0 / 17 = 0.0% (Wilson 95% 0.0%-18.4%) | n = 17; method: the product's failure rule (`derive_failure_kind`) over the export |
| non-clean valid by kind | builder_red 43, budget 41, protocol 13, lint 7 | n = 104 non-clean valid rows; method: the product's failure rule (`derive_failure_kind`) over the export |
| spend on budget-stopped attempts | $25.86 of $94.25; 11 at the 900 s wall clock | n = 41 budget rows; cost as recorded on the row |
| escalation rungs r2 / r3, clean | 2 / 40 | n = 40 valid rows on rungs r2-r3; method: the product's failure rule (`derive_failure_kind`) over the export |
| process loss (budget + protocol + harness + outage) | 309 of 518 rows (59.7%); $37.88 of $94.25 (40.2%) = £28.06 | n = 518 rows; £ at 1.35 USD per GBP (fixed) |
| budget + protocol, share of valid failures | 51.9% | n = 104 non-clean valid rows; method: the product's failure rule (`derive_failure_kind`) over the export |
| reviewed clean patches judged mergeable | 4 / 13 = 30.8% (Wilson 95% 12.7%-57.6%) | n = 13 reviews (by verdict: api_change 2, defect 4, ok 4, style 3); 2 stored flag(s) corrected from the statement |
| proxy: clean patches lint-clean with no API break | 153 / 155 = 98.7% (Wilson 95% 95.4%-99.7%); 2 unknown (belt 5 not recorded) | n = 155 clean valid rows; method: the deterministic proxy, unknown counted as not working |
| **working rate, blind** (clean x precision) | 7.2% (2.0%-19.0%) | n = 94 blind valid x n = 13 review verdicts; method: product of two rates and of their Wilson bounds — an estimate |
| **working changes per pound, blind** | 0.2063 per £ (0.0581-0.5433); ≈ 6.77 working of 94 valid for £32.81 | n = 260 blind attempts (all spend counted); £ at 1.35 USD per GBP (fixed) |
| deliver decisions made prospectively, clean | 17 / 20 = 85.0% (Wilson 95% 64.0%-94.8%) | n = 274 rows routed from prior rows only (`routing.v1`, controls not evaluated) |
| bug classes closed (register: `crb.prevention.register.v1`) | 0 of 29 | n = 29 classes; the prevention loop's register at family level (an export carries no error text); a class closes only after an applied change the attempts prove, and none has been applied |

Recurrence of previously-seen bug classes per window of 50 attempts (n = 278 attempts, time-ordered, prior data only; apparatus 2.2):

| window | attempts | new classes | recurrences | recurrence rate (Wilson 95%) |
|---|---|---|---|---|
| 1 | 1-50 | 7 | 7 | 7 / 50 = 14.0% (Wilson 95% 7.0%-26.2%) |
| 2 | 51-100 | 2 | 15 | 15 / 50 = 30.0% (Wilson 95% 19.1%-43.8%) |
| 3 | 101-150 | 4 | 33 | 33 / 50 = 66.0% (Wilson 95% 52.1%-77.6%) |
| 4 | 151-200 | 12 | 6 | 6 / 50 = 12.0% (Wilson 95% 5.6%-23.8%) |
| 5 | 201-250 | 2 | 16 | 16 / 50 = 32.0% (Wilson 95% 20.8%-45.8%) |
| 6 | 251-278 (partial) | 2 | 14 | 14 / 28 = 50.0% (Wilson 95% 32.6%-67.4%) |

**The same figures pooled across apparatus 2.0, 2.1 and 2.2, as the brief for this wave read
them [measured — n = 618 rows; method: as above with `--apparatus all`; apparatus 2.0–2.2
pooled, which the product never does by default].**

| measure | value | n / method / apparatus 2.0, 2.1, 2.2 (pooled) |
|---|---|---|
| rows / valid observations | 618 / 318 | n = 618 rows; valid = not outage, harness, disqualified or a failed gold; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, all valid | 187 / 318 = 58.8% (Wilson 95% 53.3%-64.1%) | n = 318; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, sighted | 161 / 200 = 80.5% (Wilson 95% 74.5%-85.4%) | n = 200; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind | 26 / 118 = 22.0% (Wilson 95% 15.5%-30.3%) | n = 118; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind XS | 15 / 34 = 44.1% (Wilson 95% 28.9%-60.6%) | n = 34; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind S | 8 / 35 = 22.9% (Wilson 95% 12.1%-39.0%) | n = 35; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind M | 3 / 30 = 10.0% (Wilson 95% 3.5%-25.6%) | n = 30; method: the product's failure rule (`derive_failure_kind`) over the export |
| clean, blind L | 0 / 19 = 0.0% (Wilson 95% 0.0%-16.8%) | n = 19; method: the product's failure rule (`derive_failure_kind`) over the export |
| non-clean valid by kind | builder_red 50, budget 47, protocol 27, lint 7 | n = 131 non-clean valid rows; method: the product's failure rule (`derive_failure_kind`) over the export |
| spend on budget-stopped attempts | $28.87 of $120.21; 14 at the 900 s wall clock | n = 47 budget rows; cost as recorded on the row |
| escalation rungs r2 / r3, clean | 2 / 40 | n = 40 valid rows on rungs r2-r3; method: the product's failure rule (`derive_failure_kind`) over the export |
| process loss (budget + protocol + harness + outage) | 370 of 618 rows (59.9%); $50.38 of $120.21 (41.9%) = £37.32 | n = 618 rows; £ at 1.35 USD per GBP (fixed) |
| budget + protocol, share of valid failures | 56.5% | n = 131 non-clean valid rows; method: the product's failure rule (`derive_failure_kind`) over the export |
| reviewed clean patches judged mergeable | 4 / 13 = 30.8% (Wilson 95% 12.7%-57.6%) | n = 13 reviews (by verdict: api_change 2, defect 4, ok 4, style 3); 2 stored flag(s) corrected from the statement |
| proxy: clean patches lint-clean with no API break | 153 / 187 = 81.8% (Wilson 95% 75.7%-86.7%); 34 unknown (belt 5 not recorded) | n = 187 clean valid rows; method: the deterministic proxy, unknown counted as not working |
| **working rate, blind** (clean x precision) | 6.8% (2.0%-17.5%) | n = 118 blind valid x n = 13 review verdicts; method: product of two rates and of their Wilson bounds — an estimate |
| **working changes per pound, blind** | 0.1903 per £ (0.0552-0.4907); ≈ 8.0 working of 118 valid for £42.03 | n = 303 blind attempts (all spend counted); £ at 1.35 USD per GBP (fixed) |
| deliver decisions made prospectively, clean | 21 / 24 = 87.5% (Wilson 95% 69.0%-95.7%) | n = 348 rows routed from prior rows only (`routing.v1`, controls not evaluated) |
| bug classes closed (register: `crb.prevention.register.v1`) | 0 of 39 | n = 39 classes; the prevention loop's register at family level (an export carries no error text); a class closes only after an applied change the attempts prove, and none has been applied |

Recurrence of previously-seen bug classes per window of 50 attempts (n = 352 attempts, time-ordered, prior data only; apparatus 2.0, 2.1, 2.2 (pooled)):

| window | attempts | new classes | recurrences | recurrence rate (Wilson 95%) |
|---|---|---|---|---|
| 1 | 1-50 | 13 | 16 | 16 / 50 = 32.0% (Wilson 95% 20.8%-45.8%) |
| 2 | 51-100 | 14 | 11 | 11 / 50 = 22.0% (Wilson 95% 12.8%-35.2%) |
| 3 | 101-150 | 1 | 4 | 4 / 50 = 8.0% (Wilson 95% 3.1%-18.8%) |
| 4 | 151-200 | 2 | 30 | 30 / 50 = 60.0% (Wilson 95% 46.2%-72.4%) |
| 5 | 201-250 | 3 | 21 | 21 / 50 = 42.0% (Wilson 95% 29.4%-55.8%) |
| 6 | 251-300 | 4 | 23 | 23 / 50 = 46.0% (Wilson 95% 33.0%-59.6%) |
| 7 | 301-350 | 2 | 16 | 16 / 50 = 32.0% (Wilson 95% 20.8%-45.8%) |
| 8 | 351-352 (partial) | 0 | 2 | 2 / 2 = 100.0% (Wilson 95% 34.2%-100.0%) |

**Where this differs from the brief's hand count [measured — n = 618 rows; method: the
product's rule against the brief's; apparatus 2.0–2.2 pooled].** The brief counted 322 valid
observations and 190 clean; the product's rule counts 318 and 187, because it also sets aside
the one disqualified row and the three rows on tasks whose own gold failed. The brief listed
the reviewers' reasons as style 4, behaviour 4 and public interface 2 — ten reasons for nine
patches; by each review's headline verdict it is style 3, defect 4 and public interface 2.

## Why the value leaks

1. **Clean is not working.** Nine of the thirteen clean patches a person read would not have
   been merged: three for style the repository's own tools reject, four for a behaviour defect
   or a feature not delivered, two for a public-interface change the task did not ask for
   [measured — n = 13 reviews; method: each review's headline verdict; apparatus 2.0–2.2].
   The deterministic proxy — clean, lint-clean, no interface break — called 153 of 155 clean
   patches working under apparatus 2.2 [measured — n = 155 clean valid rows; method: the
   proxy in `crb.core.value.proxy_working`; apparatus 2.2], so the proxy is optimistic until
   the formatter step and the interface belt (belt 6), built in this wave and off by default,
   are switched on. That is why the scorecard prefers any repository's reviews to the proxy.
2. **Process losses dominate the failures.** Budget stops and protocol refusals are 74 of the
   131 valid failures, and 14 budget-stopped attempts ran into the 900-second wall clock
   [measured — n = 131 valid non-clean rows and n = 47 budget rows; method: the product's
   failure rule; apparatus 2.0–2.2 pooled]. Budget-stopped attempts alone cost $28.87 of the
   $120.21 spent and returned nothing [measured — n = 47 budget rows; method: cost as recorded
   on each row; apparatus 2.0–2.2 pooled].
3. **Escalation rarely pays.** Two of forty valid attempts on the second and third rungs came
   out clean [measured — n = 40 rows on rungs r2 and r3; method: the product's failure rule;
   apparatus 2.2].
4. **The product throws away what it makes, and nothing learns yet.** The brief found none of
   the clean patches still retrievable **[measured by the brief from the store, not
   recomputable from the export — n = 190 clean rows; method: the retained-patch route;
   apparatus 2.0–2.2]**. From this wave on, every graded attempt keeps its patch. The
   learning curve does not fall: under apparatus 2.2 the share of attempts that repeat a
   class already seen was 14% in the first window of fifty attempts and 50% in the last,
   partial one [measured — n = 278 attempts; method: `learning_curve` with the prevention
   loop's register (`crb.prevention.register.v1`), each attempt's class judged against
   earlier attempts only; apparatus 2.2]. The register is now the one behind the curve, but
   no class is closed: the loop's switch is off by default and no change has been applied on
   the operator's stack, so nothing has yet been measured after a change **[gap — the Phase B
   paired campaign with the loop off and on; `docs/dod/streams/learn.md` G-537]**.

**What routing already gets right.** Of the rows the routing rule would have let in under
`deliver` at the time — each cell routed from the rows before it only — 17 of 20 came out
clean [measured — n = 20 prospective deliver decisions over n = 274 routed rows; method:
`prospective_routing`, numeric clauses only, negative controls not evaluated; apparatus 2.2].
Clean is not working, so this is an upper bound on the share that would merge **[hypothesis —
confirmed or refuted by reviewing the patches those rows produced, once they are kept]**.

## Today's prevention register — cobra, click and koa

**What the loop would do today, class by class [measured — n = 618 exported rows, of which the
loop reads each repository's first attempts (cobra 107, click 70, koa 47); method:
`scripts/prevention_from_export.py` running `crb.core.prevention.build_register` with the
mechanisms this build ships (`finish_gate`, `format_step`, `budget_calibrated`) and stream K's
calibration check, every row's kind from the product's failure rule; apparatus 2.0–2.2, each
class's stratum the latest comparable key, apparatus 2.2].** The export carries no error text,
stop reason or lint pack, so every class is read at family level (`protocol:network:-`,
`budget:unrecorded`, `lint:*`). The switch is off on every repository, so every class is
`open`: *suspended* means the loop would act if an operator switched it on, *watch* that there
are too few occurrences yet, *dormant* that the class has gone quiet with no change on record
(never credited to the loop), and *capability* that the class is judged by value in the paired
campaign and is never closed by recurrence.

**cobra** — 107 first attempts (22 blind, 85 sighted); the largest blind class is `builder_red:target_red` (7 first attempts) [measured — n = 107 first attempts; method: the register over the export; apparatus 2.0–2.2].

| class | first attempts (blind / sighted) | stratum | tasks | spend | actionable | lever the loop would apply | would file | status |
|---|---|---|---|---|---|---|---|---|
| `builder_red:target_red` | 12 (7 / 5) | 6 of 19 blind (apparatus 2.2) | 8 | $6.20 | yes | `finish_gate` (gate) | — | open (capability, suspended) |
| `harness:no-credential` | 9 (0 / 9) | 9 of 80 sighted (apparatus 2.2) | 9 | $0.00 | yes | none the loop may apply | `item:credential-link` | open |
| `budget:unrecorded` | 5 (1 / 4) | 4 of 80 sighted (apparatus 2.2) | 3 | $4.91 | no | `budget_calibrated` (mistake-proofing) | `item:budget-handoff` | open (dormant) |
| `protocol:network:-` | 3 (3 / 0) | 3 of 19 blind (apparatus 2.2) | 3 | $4.40 | yes | `finish_gate` (mistake-proofing) | `item:refused-call` | open (suspended) |
| `lint:*` | 1 (0 / 1) | 1 of 63 sighted (apparatus 2.2) | 1 | $0.46 | no | `finish_gate` (gate) | — | open (watch) |
| `harness:other` | 0 (0 / 0) | 0 of 19 blind (apparatus 2.2) | 1 | $0.44 | no | none the loop may apply | — | open (watch) |

**click** — 70 first attempts (17 blind, 53 sighted); the largest blind class is `protocol:network:-` (5 first attempts) [measured — n = 70 first attempts; method: the register over the export; apparatus 2.0–2.2].

| class | first attempts (blind / sighted) | stratum | tasks | spend | actionable | lever the loop would apply | would file | status |
|---|---|---|---|---|---|---|---|---|
| `budget:unrecorded` | 10 (3 / 7) | 7 of 43 sighted (apparatus 2.2) | 5 | $13.07 | yes | none the loop may apply | `item:budget-handoff` | open |
| `protocol:network:-` | 6 (5 / 1) | 1 of 11 blind (apparatus 2.2) | 3 | $2.06 | no | `finish_gate` (mistake-proofing) | `item:refused-call` | open (watch) |
| `harness:env-network:pip` | 5 (1 / 4) | 0 of 43 sighted (apparatus 2.2) | 4 | $2.67 | no | none the loop may apply | `item:env-provision` | open (watch) |
| `builder_red:target_red` | 4 (4 / 0) | 3 of 11 blind (apparatus 2.2) | 2 | $2.47 | yes | `finish_gate` (gate) | — | open (capability, suspended) |
| `lint:*` | 2 (0 / 2) | 2 of 39 sighted (apparatus 2.2) | 2 | $0.32 | yes | `finish_gate` (gate) | — | open (suspended) |
| `harness:other` | 1 (0 / 1) | 0 of 43 sighted (apparatus 2.2) | 1 | $0.31 | no | none the loop may apply | — | open (watch) |
| `protocol:archaeology:-` | 0 (0 / 0) | 0 of 11 blind (apparatus 2.2) | 1 | $1.52 | no | `finish_gate` (mistake-proofing) | `item:refused-call` | open (watch) |

**koa** — 47 first attempts (13 blind, 34 sighted); the largest blind class is `builder_red:target_red` (4 first attempts) [measured — n = 47 first attempts; method: the register over the export; apparatus 2.0–2.2].

| class | first attempts (blind / sighted) | stratum | tasks | spend | actionable | lever the loop would apply | would file | status |
|---|---|---|---|---|---|---|---|---|
| `builder_red:target_red` | 4 (4 / 0) | 4 of 10 blind (apparatus 2.2) | 4 | $3.90 | yes | `finish_gate` (gate) | — | open (capability, suspended) |
| `protocol:archaeology:-` | 4 (2 / 2) | 1 of 10 blind (apparatus 2.2) | 3 | $1.07 | no | `finish_gate` (mistake-proofing) | `item:refused-call` | open (watch) |
| `budget:unrecorded` | 3 (0 / 3) | 3 of 29 sighted (apparatus 2.2) | 4 | $1.53 | yes | `budget_calibrated` (mistake-proofing) | `item:budget-handoff` | open (suspended) |
| `builder_red:regression` | 1 (0 / 1) | 1 of 29 sighted (apparatus 2.2) | 1 | $0.13 | no | `finish_gate` (gate) | — | open (watch) |
| `protocol:network:-` | 1 (1 / 0) | 0 of 10 blind (apparatus 2.2) | 1 | $0.23 | no | `finish_gate` (mistake-proofing) | `item:refused-call` | open (watch) |

**What this says.** Every protocol refusal and every red target test would be answered with
stream W's finish gate, a process lever; no class needs a playbook line [measured — n = 224
first attempts in cobra, click and koa; method: the register over the export; apparatus 2.2
strata]. Budget stops would get stream K's calibrated budget in koa, but not in click: the
loop checks click's budget class against the sighted L cell, where the export holds only 7
clean completions, one below the 8 the calibration needs, so the loop would file the
budget-handoff item instead of applying a budget it cannot set from data [measured — n = 43
sighted first attempts in click; method: the register over the export with K's calibration
check, minimum `crb.core.spend.CALIBRATION_MIN_CLEAN`; apparatus 2.2]. The nine cobra rows
refused for a missing credential are now stopped at submit (`docs/PREVENTION.md` P-003), so
the loop would file a link to that fix rather than make a change of its own [measured — n = 9
of 80 sighted first attempts in cobra; method: the register over the export; apparatus 2.2].
Whether any of these changes lowers its class's recurrence is not known until the paired
campaign runs **[gap — `docs/dod/streams/learn.md` G-537]**.

## What this does not say

- The headline is an estimate: a product of two rates measured on different samples. Most of
  the reviewed patches were sighted and most blind attempts were not reviewed **[hypothesis —
  that a sighted patch is as mergeable as a blind one; a review sample of blind patches
  confirms or refutes it]**.
- The reviews in the export name the task, not the graded row, so under apparatus 2.2 they
  are counted without checking which apparatus graded the patch they read.
- The export carries no stop reason and no `source_changed` belt, so the reader infers both
  **[gap — the store's rows carry them; a JSONL export read through `GradeRow` needs no
  inference]**: a budget stop at or beyond 900 seconds is named the wall clock, and a
  lint-only failure is read from belts 1 to 3 and belt 5.
- Pounds are dollars at a fixed 1.35 dollars to the pound, not a market rate **[gap — the
  product has no exchange-rate source; the rate is a parameter of `GET /value` and of the
  script]**. The ledger records dollars and every figure above can be read in them.

## How to regenerate it

```
PYTHONPATH=src python scripts/value_baseline.py \
  --ledger ledger-2026-09-25.psv --reviews reviews-2026-09-25.psv --apparatus 2.2
PYTHONPATH=src python scripts/value_baseline.py \
  --ledger ledger-2026-09-25.psv --reviews reviews-2026-09-25.psv --apparatus all
PYTHONPATH=src python scripts/prevention_from_export.py ledger-2026-09-25.psv \
  --repos cobra,click,koa
```

On a running deployment the same report is `GET /value` (docs/API.md, Value), and Home shows
its north star. After the paired campaign with the loop off and on, this page gains a second
reading beside the first **[aspiration — `docs/dod/product.md` G-653]**.
