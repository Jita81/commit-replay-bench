# ADR-0013 — An external reviewer's verdict is recorded, advisory, and never an input to a verdict

**Status:** Proposed (operator decision DL-032 attached CodeRabbit; the factory integration
described here is not built)
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
