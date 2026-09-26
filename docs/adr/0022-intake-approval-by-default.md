# ADR-0022 — An operator approves a ticket before it is registered; one pass per repository

**Status:** Proposed (DL-059)
**Date:** 2026-09-25
**Apparatus impact:** none — intake decides *which* items exist, never how one is graded
(ADR-0017's reasoning holds): no belt, cell, route, threshold or sign-off clause moves, and
`APPARATUS_VERSION` and every policy version are unchanged. **Supersedes in part:**
[ADR-0017](0017-the-ticket-is-the-backlog-item.md), "The column is the consent gate" —
moving a ticket into the watched column is now the *request* to manufacture, not the
consent; the consent is an operator's Register act (or a named author on an explicit
allowlist).

## Context

The external assessment of 2026-09-25 (item C6) found five things at the intake boundary.

1. **No human step.** A ticket whose structural slots were filled was registered on the
   frozen backlog and queued for the factory with no person in between. Anyone who could
   edit a ticket in the watched column could put work into the factory, and what they wrote
   became the backlog item, the pull-request title and the pull-request body.
2. **Ticket text as markup.** The ticket's title was the pull request's `##` heading and its
   acceptance criteria were emitted verbatim as list items, so a ticket author could write a
   heading, a checked box, a mention that pages a team or a link into a customer's pull
   request. The delivery branch kept the item id's capitals, dots and underscores.
3. **No lease.** Nothing stopped the worker's timed poll and an operator's "Re-read" from
   reading one column at once.
4. **429 was a stop.** A rate-limited tracker stopped the pass on its first 429.
5. **The credential could leave.** `TrackerHttp.request` used any absolute URL it was given
   as-is, so a caller handing it one on another host would have sent the tracker token there.

[measured, n = 5 reproductions on origin/main `8ab88ad`, method: the fake tracker and an
`httpx.MockTransport` against the unmodified service (scratch script, recorded in the pull
request), apparatus 2.2] A ready ticket was registered by the first poll (`registered: 1`);
two overlapping passes both ran (two `intake.polled` events, four comment writes for one
ticket); a 429 answered `unreachable` after one call with no wait; a request to
`https://evil.invalid/x` was sent with `Authorization: Basic …`; the PR body carried the
title as a heading and the criteria as live markdown, and `crb/A..B-…` was a branch git
refuses.

## Decision

1. **Approval by default.** `CRB_INTAKE__REQUIRE_APPROVAL` (`IntakeSettings.require_approval`)
   is `true` by default. A ready ticket is labelled as before and lands as a **draft**:
   `intake.awaiting_approval` on the chain carries the draft item, the ticket's revision,
   its content digest and its author, and the Intake screen shows it waiting with a
   **Register this ticket** act (operator). `crb.server.intake.poll_repository`'s own
   default is the same (`ApprovalPolicy()`), so a caller that forgets to pass a policy still
   gates. The act — `POST /factory/{repo}/intake/{key}/register {revision}`,
   `crb.server.intake.register_approved` — registers exactly the waiting draft, as the
   operator read it: a ticket whose content has changed since that revision is refused
   (409 `revision_moved`), as is a key with nothing waiting (409 `nothing_to_register`) or a
   repository a factory run holds (409 `factory_run_active`). The act writes on the ticket,
   so it is refused while the repository's listener is off (422 `intake_listener_off`, the
   same refusal the poll has: the switch stays the consent to write on that board). It is
   evented twice: `intake.registered` on the item's chain with
   `approved_by: operator:<account id>` — the stable, unique account id, never the display
   name an account can change or share — and `approved_by_name` beside it for a human
   reader, and `intake.approved` on the repository's system trace.
2. **An explicit allowlist may bypass it.** `CRB_INTAKE__APPROVE_AUTHORS` (a JSON list,
   empty by default) names tracker authors — the ticket's creator: Azure DevOps
   `System.CreatedBy` sign-in name, Jira `creator` email, or its account id when the email
   is hidden — whose ready tickets register without the act; the registration records
   `approved_by: allowlist:<author>`. `require_approval: false` registers every ready ticket
   unattended and records `approved_by: unattended`. The allowlist trusts the ticket's
   **creator**; it does not see who edited the ticket since. A deployment that needs
   per-edit trust leaves the allowlist empty.
3. **Ticket text is data.** `crb.factory.delivery.pr_body` shows the title and the acceptance
   criteria only inside one fenced block whose fence is longer than any backtick run inside
   it; the pull-request title escapes every markdown punctuation mark onto one line
   (`escape_markdown_line`); the commit subject is one line; the delivery branch is
   `crb/<slug of the item id>-<slug of the title>`, `[a-z0-9-]` only
   (`delivery_branch_name`, `DELIVERY_BRANCH_RE`). A pull request an earlier run opened
   under the old name keeps its branch when it is updated.
4. **One pass per repository.** Every pass — the worker's timed poll, the on-demand poll route
   and the Register act — takes `crb.server.intake.intake_lease(factory, repo)`: a
   `lease:intake:<repo>` row in the existing `workers` table (no new table, no migration),
   taken by insert (atomic on SQLite and PostgreSQL), expired after twice the poll budget
   plus a minute, released only by its holder. A pass that finds it held reads and writes
   nothing (`busy`; the route answers 409 `intake_busy`). The health probe does not count a
   lease row as a worker (`crb.store.models.LEASE_ROW_PREFIX`).
5. **A rate limit is waited out, briefly; the credential never leaves the tracker's origin.**
   `crb.intake.http.TrackerHttp` retries a 429 up to `MAX_RETRIES` (2) times, waiting for
   `Retry-After` (seconds or an HTTP date) but never more than `MAX_RETRY_WAIT_S` (10 s) per
   try, doubling from one second when there is no header; then it is `unreachable` with the
   reason. A request URL whose scheme, host or port differ from `base_url`'s is refused
   (`refused`) before the credential is attached.

## Consequences

- Money cannot move on a ticket nobody at the operator's end has read, unless the
  deployment names that ticket's author. The intake journey gains one act; a team that
  trusts its board names its authors or switches approval off, on the record.
- A customer's pull request shows what the ticket asked for, verbatim, as inert text.
- Two passes can no longer race; a crashed pass blocks its repository for at most its lease's
  time to live.
- The walkthrough (`ui/e2e/walkthrough/12-intake.spec.ts`) presses Register after the edit.
- We must never register a ready ticket without an approval record (`approved_by` on every
  `intake.registered` written from now on), never render ticket text outside the fence, and
  never send the tracker credential to another origin.

## Alternatives considered

- **Keep the column as the consent.** Rejected: the column is writable by everyone who can
  edit the board, which is not the same population as the people who may spend money and
  write on a customer's repository.
- **Approve per repository instead of per ticket.** Rejected: that is the listener switch
  again; the finding is about what an individual ticket says.
- **Strip markdown from ticket text instead of fencing it.** Rejected: it changes what the
  person wrote; a fence shows it exactly and makes it inert.
- **A new `leases` table.** Rejected for now: it needs a migration on every deployment; the
  `workers` table is mutable state with a primary key, which is all a lease needs.
