# Factory fit: a public-mandate feedback prototype (bounded experiment, 2026-10-03)

**Question.** The factory-fit assessment for a pseudonymous public-feedback system
(identity, gap map, question planner, multi-channel airlock) made predictions about how the
factory would handle the prototype's backlog. This experiment tests the cheapest of them
cheaply, so the open questions are the ones that need money, people or a sandbox.

**Bounded by design:** five items, one attempt each, no retries; a builder budget of
12 tool calls per item; no model API keys in the session, so the factory's own
`claude_code` builder and `RungTestAuthor` were **not** used — see *Method* for what stood in
for them.

## Method

| Step | What ran | Real crb code? |
|---|---|---|
| Readiness | `crb.factory.readiness.assess` over the 14 items in [`backlog.json`](backlog.json) → [`readiness.json`](readiness.json) | yes |
| Repository | a fresh repo (`prototype/`): pyproject, ruff, pytest, typed stubs raising `NotImplementedError` (item A1, done by hand) | — |
| Oracle | one test file per item (B1, B2, B9, B10, B11), written by the test author (this session's model) with the spec in each docstring; **RED proof**: 60 of 60 failing with attributable ids at the base | no (same rule as `crb.factory.testfirst.prove_red`) |
| Gold check | a reference implementation turned all 60 green; it was then removed from the repository so that no builder could read it | no |
| Build | five subagents on a **different model** from the test author (the identity rule of `assert_distinct_identity`), each in its own git worktree, sighted (tests visible), told not to touch `tests/` | no |
| Grade | [`grade.py`](grade.py): the five belts (`tests_unmodified` by SHA-256, `target_green`, `no_new_failures`, `source_changed`, `repo_lint_clean`), on the host (no docker in the session) | belts re-implemented |
| Oracle strength | `crb.core.oracle.mutation.generate_mutants` over every line of each built module; each mutant run against its target test file | mutant generator yes, scorer no |

## Results

**[measured — n = 5 tasks, 1 attempt each, sighted, host posture, belts as in `grade.py`;
not crb apparatus 2.3, so never pooled with the ledger]**

| Item | Class / size | Clean | Lines | Mutants killed | Strength | ADR-0003 rule 5 |
|---|---|---|---|---|---|---|
| B1 `derive_pseudonym` | bug.fix XS | ✅ | +12 | 6/6 | 1.00 | — |
| B2 recovery phrase | bug.fix S | ✅ | +29 | 19/24 | **0.79** | `human` (< 0.80) |
| B9 coverage state machine | bug.fix S | ✅ | +21 | 21/21 | 1.00 | — |
| B10 gap analyser | bug.fix S | ✅ | +17 | 3/6 | **0.50** | `human` (< 0.80) |
| B11 question planner | bug.fix S | ✅ | +10 | 11/12 | 0.92 | — |

- **Clean 5/5** (Wilson 95% interval 0.57–1.00). Every builder finished in 4–5 tool calls and
  10–15 s. The builders' own reports were not counted as results; the belts were.
- **Two of five oracles were too weak**, and these were tests written with care, by the
  model that had just written the spec. B10 had no case where a `vague` slot and an
  `uncovered` slot tie on priority, so the rank table could be shifted without any test
  failing. Of its three surviving mutants, one is equivalent (it keeps the order); the other
  two are real gaps. B2 never tested the four-word boundary. Under the published rule, both
  cells would route to `human` until their oracles are strengthened.
- **Leak control on B1:** a variant that kept a module-level `pseudonym → secret` table (a
  table that links pseudonym to identity, the exact failure the architecture exists to
  prevent) **passed 7/7**. A green suite says nothing about unlinkability.

### Readiness gate (real crb code)

| Item | Route hint | Why |
|---|---|---|
| B1, B2, B4–B11 | `test_first_authoring` | structural slots filled, value slots open |
| B3 blind-signature verify | `human` | the `expected_behaviour` slot was deliberately left empty, and the gate blocked it |
| X1 conversation engine as `feature.add` | `human` | class is not in the catalogue |
| X2 question-bank content as `docs.update` | `human` | class has a weak oracle |
| X3 "the whole prototype", `bug.fix` **XL** | `test_first_authoring` | **readiness passes it** (see finding 3) |

## Predictions against results

| Prediction (from the assessment) | Result |
|---|---|
| Small, pure, well-specified items build clean at a high rate | **Supported:** 5/5. The interval is still wide (0.57–1.00) |
| Writing them up in the `bug.fix` shape works for the readiness gate | **Confirmed** for all 10 written that way |
| `feature.add` and weak-oracle content route to a human | **Confirmed** |
| The belts cannot show the anonymity property | **Confirmed** by the leak control |
| Oracle strength is a real risk even with careful test-first authoring | **Stronger than predicted:** 2 of 5 below the 0.80 bar |
| A new repository delivers nothing without an approver override | **Confirmed from the code** (`FactorySpec.route_decision_for`: no map ⇒ delivery withheld); not run end to end |
| "Planner is medium-high" (B11) | **Not supported as a difference.** It was the smallest and cleanest; my difficulty ranking was noise at this size |

## Findings

1. **The harness is where the misses come from, as the critical-friend review found for crb
   itself.** Grading this experiment's builds failed twice for reasons that were the
   experiment's own fault, not the builders'. First, the skeleton had no `.gitignore`, so
   bytecode files counted as edits and belt 1 failed on all four builds graded by then.
   Second, the mutation loop rewrote source within the same second, Python served a stale
   `.pyc`, and a correct build graded red. crb's scorer already guards this (`_next_tick`);
   the stand-in didn't. Both were fixed and every item was re-graded. The first numbers would
   have read 0/5.
2. **A second automated check is needed, not more care.** Even with the oracle and the spec
   written by the same careful author, 2 of 5 fell below the bar. Run `crb oracle` mutation
   scoring on every authored test before the build, not after.
3. **On a cold-start repository nothing stops an XL item from being built.** Granularizing XL
   happens only in `crb.core.routing.route`, `crb.factory` never checks size, and with no map
   the route is never evaluated. X3 ("the whole prototype") is ready and would be attempted:
   spend, not risk, since delivery is still withheld. **Closed on this branch (2026-10-04):**
   readiness now routes an item estimated at a size in the routing policy's
   `granularize_sizes` to `human` before any build (`crb.factory.readiness.GRANULARIZE_SIZES`,
   the policy's own tuple, not a copy).
4. **`feature.add` is the prototype's natural class and the catalogue doesn't hold it.** Writing
   new modules up as `bug.fix` worked here, but it bends the class meaning behind every cell.

## What this does not establish

The factory's real loop and builders, the sealed sandbox, PR delivery, items of size M or
larger, frontend items, the blind mode, and any LLM-quality, crypto or neutrality property.
With n = 5 the build rate is a direction, not a licence.

## Cost

Five builder subagents, about 46k tokens each (most of it the agent's fixed context), 4–5
tool calls each; the oracle, gold and grading cost no model calls.

## Files

`backlog.json` (the 14 items) · `readiness.json` (the gate's answers) · `grade.py` (belts and
mutation) · `grades.jsonl` (the graded rows) · `prototype/` (skeleton, the five oracles, the
five builds as graded; `pytest` → 60 passed).
