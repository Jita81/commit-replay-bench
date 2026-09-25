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
| bug classes closed (register: `stub:failure-kind`) | 0 of 29 | n = 29 classes; the register is a stub until stream L is wired |

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
| bug classes closed (register: `stub:failure-kind`) | 0 of 39 | n = 39 classes; the register is a stub until stream L is wired |

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
   proxy in `crb.core.value.proxy_working`; apparatus 2.2], so until the formatter step and the
   interface belt exist the proxy is optimistic. That is why the scorecard prefers any
   repository's reviews to the proxy.
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
   apparatus 2.0–2.2]**. The learning curve does not fall: under apparatus 2.2 the share of
   attempts that repeat a class already seen was 16% in the first window of fifty attempts and
   54% in the last, partial one [measured — n = 278 attempts; method: `learning_curve`, each
   attempt's class judged against earlier attempts only; apparatus 2.2]. No class is closed
   because the register behind the curve is still the stub that applies nothing **[gap — the
   prevention loop's register is not wired; `docs/dod/product.md` G-650]**.

**What routing already gets right.** Of the rows the routing rule would have let in under
`deliver` at the time — each cell routed from the rows before it only — 17 of 20 came out
clean [measured — n = 20 prospective deliver decisions over n = 274 routed rows; method:
`prospective_routing`, numeric clauses only, negative controls not evaluated; apparatus 2.2].
Clean is not working, so this is an upper bound on the share that would merge **[hypothesis —
confirmed or refuted by reviewing the patches those rows produced, once they are kept]**.

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
```

On a running deployment the same report is `GET /value` (docs/API.md, Value), and Home shows
its north star. After the paired campaign with the loop off and on, this page gains a second
reading beside the first **[aspiration — `docs/dod/product.md` G-653]**.
