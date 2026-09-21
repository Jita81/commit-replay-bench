# ADR-0013 — An external reviewer's verdict is recorded, advisory, and never an input to a verdict

**Status:** Proposed (operator decision DL-032 attached CodeRabbit; the factory integration
described here is not built) · **Amended 2026-09-21** (a `weak_oracle` verdict never
rebuilds against an unchanged oracle) — §"Amendment" below
**Date:** 2026-09-15
**Apparatus impact:** none. Nothing in this ADR touches a belt, the routing rule, the sign-off
policy or a ledger row. It adds a *review* source.

## Context

The operator attached **CodeRabbit** (an AI code-review service that comments on GitHub pull
requests) to the repository, to serve as third-party verification of three things: the
product's own code, its tests, and the output of the software factory.

The product already has a place for an outside opinion of a patch, and a rule about it:

- **`docs/EVIDENCE-AND-CLAIMS.md` §2** — a verdict comes from the repository's own tests under
  the belts; *no model reviews, approves or scores a change*. A model's opinion of a model's
  work is not evidence.
- **`crb.core.review`** — a *review row* (`crb.review.v1`): a human's post-hoc verdict on an
  accepted row, anchored to the evidence pack's diff hash, hash-chained, revocable by a newer
  row. It records who read what and what they concluded; it lifts nothing.
- **`crb.factory.review`** — the factory's independent reviewer (`Reviewer` protocol):
  probes run on the built worktree; the verdict is **recorded before any edit**; a rework is
  a new RED proof → build → grade → fresh verdict. The shipped implementation is
  `MechanicalReviewer` (probes, no model).

An AI reviewer fits the second and third of these exactly and the first not at all.

## Decision

1. **CodeRabbit reviews every pull request** into `main` (and, until 2026-09-16, `reboot/v2`), under
   `.coderabbit.yaml`, whose per-package instructions are written from this product's own
   invariants (stdlib-only core; false-Q1 at write; append-only stores; never weaken a test;
   the header standard; the claims policy). It is the reviewer that *did not build and did
   not grade*: its value is naming what the tests do not cover.
2. **Its verdict is advisory to the humans who merge.** It is never read by the grader, the
   routing rule, the capability map or the sign-off policy. A PR with CodeRabbit findings is
   addressed by a human — fixed, or answered with the reason and the evidence — and the
   thread is resolved by that human. Nothing automated merges on a CodeRabbit approval.
3. **For the factory's output**, the integration path (not built) is an
   `ExternalPrReviewer` implementing `crb.factory.review.Reviewer`: after `deliver()` opens
   the PR, it waits for the PR's review (CodeRabbit's, or a human's) and records it as a
   `ReviewVerdict` with `reviewer = "coderabbit"` (or the human's identity), the PR ref and
   the findings — **before any edit**, like every other verdict. `accept_with_edit` from an
   external reviewer follows the same rework path as the mechanical one. The verdict is a
   review row; it changes no grade and lifts no tier.
4. **What it may never do:** feed the belts, change a route, satisfy `require_attestation`
   (an approver attests to a diff *they* read), or be counted as `human-verified`. The tier
   ladder stays human-only.

## Consequences

- Kainos developers get an independent, always-on reviewer that knows the product's rules,
  on every change — and a record, in the PR, of what it flagged and how it was answered.
- The factory gains a second reviewer kind without changing its loop: the `Reviewer`
  protocol already isolates it, and verdict-before-edit already protects it.
- The claims policy is unchanged: "reviewed by CodeRabbit" is a process fact, not evidence of
  correctness. The reviews ledger will say `reviewer: coderabbit` where that is the truth.
- Cost: none to the ledger; CodeRabbit's own subscription on the operator's account.

## Amendment (2026-09-21) — a `weak_oracle` verdict never rebuilds against an unchanged oracle

**Context.** The first real factory run (B-1b, docs/reviews/2026-09-19-b1b-first-factory-pull-request.md,
finding 3; DL-045 rule 3) showed what decision 3's "same rework path" does when the
reviewer's finding is about the *test* rather than the change. The mechanical reviewer's
mutation probe found the oracle of `cobra-2154` weak against the delivered code (deleting
the `DisableFlagParsing` guard still passed) and returned `accept_with_edit` with a
`weak_oracle` finding. The deployment had no test-author rung, so the rework re-proved RED
with the *same* oracle and rebuilt — and the builder found another way to pass the same
test: a six-line change that dropped the guard, a regression nothing tested. The verdict
asked for a stronger test; the loop answered with a different patch.

**Decision.** A `weak_oracle` finding on an `accept_with_edit` verdict asks for a stronger
**oracle**, and the loop never rebuilds against an unchanged one on its account:

1. **No test author** (`FactorySpec.rework_test is None`): the item stops
   `oracle_needs_strengthening` *before* any edit is permitted. The chain records a
   `route.decided` event routing it `human` with the reason — the reviewer's finding and
   the way forward ("strengthen the test and register a superseding item"), plus
   `after_verdict`, `finding: weak_oracle`, the verdict's event id and the oracle's sha256 —
   the trace carries `rework.refused`, the `ItemOutcome` carries the reason, and the pull
   request keeps the one build the verdict was recorded against.
2. **A test author exists**: the rework is permitted to ask it (the edit is permitted, the
   rework starts), and the answer's sha256 is compared with the previous oracle's. The same
   bytes (or `None` = keep the previous test) is the same stop; only a **changed** oracle
   goes on to the RED proof and the build.
3. A rework asked for any other reason (a major finding that is not `weak_oracle`) keeps
   decision 3's path unchanged: the same oracle, a fresh RED proof, a build, the pull
   request updated, a fresh verdict, bounded by `max_rework`.

The rule holds for every `Reviewer` — the mechanical one and the external one this ADR
describes — because it reads the recorded verdict's findings, not the reviewer's identity.

**Consequences.** A weak oracle is now a stop with a named owner, not a wasted build: the
Factory screen says what happened and what to do; the superseding item carries the
strengthened test and the factory delivers the build that passes it. `tests/test_factory_loop.py`
pins the no-author stop (one build, one push, one pull request, one verdict, no edit), the
same-bytes stop, the other-reason rework, and the changed-oracle rework;
`tests/test_server_routes_factory.py` pins the task view's fold with its reason.

## Alternatives considered

- **Let CodeRabbit's approval gate merges automatically.** Rejected: it would make a model's
  opinion a verdict by another name (EVIDENCE-AND-CLAIMS §2) and remove the human from the
  one place the product insists on one.
- **Feed CodeRabbit's findings to the builder as a repair turn.** Rejected for the
  measurement: it would change what the builder is (a different arm, like the pre-flight —
  DL-030) and needs its own ADR if ever wanted; the pre-flight applies the repository's own
  deterministic gate, not an opinion.
- **Ignore it in the product and use it only on PRs.** That is decision 1–2 today; decision 3
  is the path when a client repository has it attached and the factory's PRs need a reviewer
  that is not the mechanical one.
