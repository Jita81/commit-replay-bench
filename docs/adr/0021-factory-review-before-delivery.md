# ADR-0021 — The factory reviews before it delivers; only an accepted build opens a pull request

**Status:** Proposed (DL-059)
**Date:** 2026-09-25
**Apparatus impact:** none — this orders the factory's steps and decides which verdict may
reach delivery. It changes no belt, no grade, no cell, no route, no threshold and no
sign-off clause; `APPARATUS_VERSION`, `routing.POLICY_VERSION` and the sign-off policy
version are unchanged. **Supersedes in part:** [ADR-0003](0003-one-routing-rule.md)'s
amendment of 2026-09-16 (the sentence "the build is still graded and reviewed" read as
review *after* the route gate's delivery step) and its amendment of 2026-09-19, decision 2
("the item goes on to review the branch the pull request now carries" — a rework no
longer re-delivers inside a run).

## Context

The external assessment of 2026-09-25 (item C1) found that `FactoryLoop.run_item` ran
`_deliver` before `_review`. With delivery switched on, a clean build became a public pull
request on the customer's repository **before** the independent review — the RED
reproduction, the belt re-run and the mutation-strength probe — had run. When the review
then found the test weak (a `weak_oracle` finding, DL-045 rule 3), the item stopped
`oracle_needs_strengthening`, but the pull request stayed open with the weak build in it:
`src/crb/factory/delivery.py` had no way to close one. A reviewer on the customer's side saw
a change the product's own review had not accepted, with nothing on it to say so.

[measured, n = 7 factory-loop cases on origin/main `8ab88ad`, method: hermetic loop tests
with fake builders and recording push/PR seams (`tests/test_factory_loop.py`, the C1
section), apparatus 2.2] With a probe whose only finding is a major `weak_oracle`, the item
ended `oracle_needs_strengthening` with a pull request opened and a delivery branch
committed; a rejected build and a rework-exhausted build were delivered; a rework opened a
pull request on the build the review asked to change and then updated it.

## Decision

1. **Review comes before delivery.** The loop's order is assess → oracle → RED proof →
   build → review → (rework → review)\* → deliver. `FactoryLoop.run_item` reviews the final
   build with no pull-request reference (none exists yet) and calls `_deliver` only when the
   final verdict is `accept`. A rework rebuilds and is reviewed again; nothing leaves the
   factory until a build is accepted, so a rework no longer "re-delivers" inside a run.
2. **The delivery boundary refuses anything but `accept`.** `crb.factory.delivery.deliver`
   takes the review's `verdict` as a required argument and raises `DeliveryRefused` for any
   value but `accept`, after the default-branch invariant and before a credential is read or
   a branch committed. `FactoryLoop._deliver` refuses as well when the verdict is not
   `accept` or is for a different evidence pack. A future caller cannot deliver an
   unreviewed build by forgetting the order.
3. **A pull request the product no longer stands behind is closed.** An item that already
   has an open pull request from an earlier run (the newest `delivery.opened` /
   `delivery.updated` on its chain, with no `delivery.merged` / `delivery.closed` outcome)
   is carried to that pull request: an `accept` updates it (the lease push and comment of
   ADR-0003's 2026-09-19 amendment, unchanged), and any other final verdict — `reject`,
   `rework_exhausted`, or the `oracle_needs_strengthening` stop — **closes** it through
   `crb.factory.delivery.close_pull_request`: a comment naming the verdict, the major
   findings and why, then `PATCH /repos/{owner}/{repo}/pulls/{n}` with `state: closed`
   (`github_close_pr_fn`; the worker passes the deployment's GitHub API base). The chain
   records `delivery.closed` with `closed_by: factory`, `verdict` and `reason`; a failure to
   close is a `delivery.close_failed` warning on the trace and the outcome sync still reads
   the pull request's fate. Nothing is merged or deleted; a person may reopen it. With
   delivery off the loop touches no remote, so it neither updates nor closes.
4. **The Factory screen reads in the same order.** `stepsFor` returns readiness → RED proof
   → build → review → delivery → outcome; a build the review did not accept reads "No pull
   request — the review did not accept this build (…), so nothing was pushed", and a clean
   build awaiting its review reads "after the review accepts the build". The step hints are
   kept and say the same.

## Consequences

- A pull request on a customer's repository always carries a build the product's own review
  accepted, with the verdict on the evidence chain before the push. The review's `pr_ref` is
  empty; the pull request is found from the item's `delivery.opened` event.
- A rework costs one build and no pushes; the customer sees one pull request, on the
  accepted rebuild, instead of a first pull request that is then force-updated.
- An open pull request from an earlier run can now be closed by the factory. This is a write
  on the customer's repository; it happens only with delivery on, with the same
  installation credentials that opened the pull request, and it is on the chain.
- `deliver()` gained a required `verdict` argument: every caller must say which verdict
  licenses the delivery.
- We must never again deliver before the review, nor deliver on a verdict other than
  `accept`. The tests in `tests/test_factory_loop.py` (C1 section) and, in
  `tests/test_factory_delivery.py`,
  `test_deliver_refuses_any_verdict_but_accept_before_touching_creds` are ratchets.

## Alternatives considered

- **Keep the order and close the pull request on a weak verdict.** Rejected: the weak build is
  still public for the length of the review, and a customer's CI, notifications and
  reviewers act on it in that window.
- **Open the pull request as a draft before the review, and mark it ready after.** Rejected:
  a draft is still a public branch carrying an unreviewed change, drafts are not available
  on every plan or forge, and it adds a second state to keep in step with the chain.
- **Leave an earlier run's open pull request alone when a later review does not accept the
  item.** Rejected: the product would be leaving open a change its latest evidence does not
  support, and the customer has no way to know that from the pull request.
