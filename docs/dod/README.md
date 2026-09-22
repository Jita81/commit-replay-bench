# The definition of done — start here

"Done" used to be a feeling backed by a feature list. It is now a record. Every page, every
journey, every value stream and the product as a whole carry one artefact of the same shape
that says what done means there, what proves it, and how far it is from met.

Read [STANDARD.md](STANDARD.md) for the rules and [TEMPLATE.md](TEMPLATE.md) to write one.
This page is for a newcomer who has to read or change one.

## The four levels

| level | one per | file | id |
|---|---|---|---|
| page | route in `ui/src/App.tsx` | `pages/<route-slug>.md` | `dod.page.<route-slug>` |
| journey | one person's goal, walked as ordered pages | `journeys/<slug>.md` | `dod.journey.<slug>` |
| value stream | one flow of value through the product | `streams/<slug>.md` | `dod.stream.<slug>` |
| product | the whole | `product.md` | `dod.product` |

Each level names its parent and its children. A level is done only when its children are done
**and** its own criteria are met, so a partial page keeps its journey, its stream and the
product partial. That is the point: it stops a screen being called finished because it renders.

Every artefact answers the same ten questions — purpose, entry and exit, truth, actions,
explanation, evidence, roles, operations, accessibility, non-goals — plus the extra questions
its level adds (a journey adds steps, proof, time and cost, recovery; a stream adds trigger,
outcome, handoff, measure, automation; the product adds identity, go-live, claims, release,
posture, support, extensibility). A question that does not apply is `n/a` with the reason in
the gap column. It is never deleted.

Two rules carry the weight:

- A criterion is **observable**. A tester can mark it true or false on the running product
  without asking the author. "Handles errors well" is not a criterion. "A wrong password
  shows the error envelope and names what to do next" is.
- Evidence is a **typed reference that resolves** — a test, a vitest or Playwright title, a
  hint id, an API route, a code symbol, a doc anchor, a CI job, an ADR or a decision-log row
  (STANDARD.md §3). Prose is not evidence. When nothing proves a criterion, its evidence is
  `absent`, its state is `unmet`, and it carries a gap.

## How to read GAP-ANALYSIS.md

[GAP-ANALYSIS.md](GAP-ANALYSIS.md) is generated — do not edit it. Edit the artefacts and
re-run the checker.

It opens with one line: how many artefacts are done and how many criteria are met, n/a and
open. Then a table per level, so you can see which page, journey or stream is holding its
parent partial. Then **Open gaps, ranked**: one row per criterion that is `partial` or
`unmet`, ordered by level weight × category weight × (double for `unmet`). The first row is
the gap that unblocks the most "done", so the list is the order of work. The `gap` column is
either a `G-nnn` defined under `## Gaps` in that artefact, or an `F-`/`B-` row from the
backlog in `docs/reviews/2026-09-17-enterprise-front-end.md` §9; the last column is that
gap's one line — what is missing, the smallest change that closes it, and the owning layer.

The next feature is the top of that list, or it is not the next feature.

## How to change a criterion

In the same pull request as the change it describes:

1. Make the change and write its test, spec or hint.
2. Open the artefact and edit the criterion's `evidence` and `state`. If it is now met,
   replace `absent` with the reference that proves it and delete the gap id.
3. If a criterion is no longer the right question, rewrite the criterion — do not delete the
   category row.
4. If the change reveals something missing, add a gap under `## Gaps` and point a criterion at
   it. One line: what is missing · the smallest change that closes it · the owner layer.
5. Run the checker and commit what it writes.

```
python scripts/dod_check.py            # rewrite GAP-ANALYSIS.md and stamp every status:
python scripts/dod_check.py --check    # what CI runs: write nothing, fail on any defect
```

Never write `status:` by hand — the checker computes it. Never write `met` on prose: the
checker demotes a `met` whose references do not resolve, and `--check` reports it.

A new route needs a new page artefact; a new journey step needs a journey. The checker tells
you which file is missing.

## The CI gate

The `dod` job in `.github/workflows/ci.yml` runs `python scripts/dod_check.py --check`. It
fails when a route has no page artefact, a journey step belongs to no journey, a parent and
child disagree, a category row is missing, a criterion has a bad id, an unknown category or
state, `met` without a resolvable reference, `partial`/`unmet` without a defined gap, an
evidence reference that does not resolve, or a stale `GAP-ANALYSIS.md` or `status:` line.

So a pull request that adds a screen without its definition of done does not merge, and a
criterion cannot be marked met by assertion. The checker itself is tested by
`tests/test_dod_check.py`.
