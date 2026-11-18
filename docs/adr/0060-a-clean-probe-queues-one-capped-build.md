# ADR-0060 — A clean probe queues one capped build

**Status:** Proposed (DL-428)
**Date:** 2026-11-18
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. The run it queues is an ordinary
factory run, graded and recorded as any other, so no grade, belt, cell, route, threshold or
sign-off clause changes. With `CRB_INTAKE__AUTO_MANUFACTURE` off (the default) every event,
chain byte, tracker call and run parameter is pinned unchanged.
**Amends:** ADR-0017 ("The ticket is the backlog item"), ADR-0022 (decision 1, the Register
act), ADR-0057 ("Not in this change") and ADR-0059 ("Not in this change"). Each place carries
an inline "(Amended by ADR-0060: …)" mark. See "Amended text".

## Context

ADR-0059 put one trial build between an operator's Register act and the registration. When
that build reports no guess, the ticket is registered under the operator's approval with no
second act. It then waits on the frozen backlog until someone starts a factory run through
the API, the CLI or MCP. That second step adds a wait and a hand-off, and it asks the person
to decide twice about one ticket at one content.

A build spends the operator's money and opens a pull request on a customer's repository. So a
build that starts without a second act has to rest on a consent that was given for it, at the
moment it was given, and has to be capped, deduplicated and recorded.

## Decision

**One capped, delivering factory run per consented, clean registration.** A deployment
switch, `CRB_INTAKE__AUTO_MANUFACTURE`, off by default, adds one step after registration:

1. **Consent is recorded at the act.** Only an operator's Register act consents
   (`approved_by` starts `operator:`), and only while the switch is on at that act. The act
   that queues a gap probe writes `manufacture: auto` on `intake.gap_probe.requested`. A
   registration written under that request, or by a later act on a clean probe, carries
   `manufacture: auto` and `content_revision` on `intake.registered`. An allowlisted author
   or an unattended column never consents. An act made while the switch was off never
   becomes consent when the switch is turned on later.
2. **Only a clean probe of that item.** The mark is written only when the probe ended done
   with no question, the build-time stop (`not_built`) is empty, and the probe was requested
   for the same item id. A ticket whose words go back to content probed earlier is a new
   item; it is registered without the mark and needs a new act.
3. **The worker's intake pass queues it.** After it tells the tickets, under the repository's
   intake lease, the pass looks for the oldest marked registration of that tracker with no
   `intake.manufacture.requested` or `intake.manufacture.skipped` for its
   `(tracker, key, content_revision)`, and queues at most one run per pass. The on-demand
   poll route never queues one.
4. **What it queues.** A `factory` run on `CRB_INTAKE__AUTO_MANUFACTURE_RUNG` with
   `deliver: true` and `max_rework` from `CRB_INTAKE__AUTO_MANUFACTURE_MAX_REWORK`. The run's
   whole cap is `CRB_INTAKE__AUTO_MANUFACTURE_MAX_COST_USD`, and each attempt gets an equal
   share of it. `params.intake_item` names the item, and the worker builds that item only.
   `params.intake_auto` holds the key fields and who acted. The run meets the one submit gate
   `POST /runs` applies, and the factory params `POST /runs` pins. `POST /runs` cannot set
   either intake field.
5. **Once per content.** The run id is derived from `(repo, tracker, key, content_revision)`,
   so two passes that race insert one row and the second is refused by the store. The run and
   the system trace `intake.manufacture.queued` are written in one transaction. A run that
   already holds the key is named on the chain and never queued again.
6. **Final skips.** `intake.manufacture.skipped` with a `reason`, never retried at that
   content: `item_superseded` (a later version is on the backlog), `has_dependencies`,
   `already_built` (a run graded or ended the item after the registration),
   `approver_inactive` (the operator who acted is no longer an active operator), `sealed`,
   `no_delivery_route` and `refused:<code>` (the submit gate's own code).
7. **Waits.** A factory run already queued or running, a pass out of time, a lease lost and an
   error reading the delivery route write nothing; the next pass tries again.
8. **The worker refuses the item** when it is no longer active or depends on other items,
   before it builds.
9. **Start-up refuses** the switch on without `CRB_INTAKE__GAP_PROBE`, without
   `CRB_INTAKE__REQUIRE_APPROVAL`, with an empty rung, and with a cap whose per-attempt share
   is above the per-run budget limit.

### Amended text

- **ADR-0017, "The ticket is the backlog item"**: registered through exactly the path the API
  uses, and, where `CRB_INTAKE__AUTO_MANUFACTURE` is on and an operator's act consented, built
  once by one capped factory run.
- **ADR-0022, decision 1**: the Register act registers exactly the waiting draft. Where
  `CRB_INTAKE__AUTO_MANUFACTURE` is on, the same act also consents to one capped build of
  that content after a clean probe.
- **ADR-0057, "Not in this change"**: an Azure delivering run is started through the API or
  MCP, or by intake's automatic build.
- **ADR-0059, "Not in this change"**: manufacturing straight after a clean probe is now
  ADR-0060, behind its own switch.

## Consequences

- A ticket an operator approves can become a pull request with no second act, under a cap the
  operator set, and each new content needs a new act.
- The chain names the run only after the next sweep with the listener and the switch both on.
  Until then the run's `params.intake_auto` and the system trace are the record.
- The test author has no cap of its own per call. The run's spend check after the loop
  (`cap.passed`) catches an overrun, but only after it was spent.
- Proven against fakes only [gap]. No live tracker or paid build was run for this change;
  closing it needs one operator-run reading on a sandbox repository.
- Not in this change: a ticket comment that says a build was queued or skipped, showing the
  automatic run on the intake screen, and consent from an allowlisted author.

## Alternatives considered

- **Decide consent at registration.** Simpler, but an act made while the switch was off would
  become consent when the switch is turned on later.
- **Queue the run inside the poll that registers.** The poll's tracker writes and the run would
  share one failure path; a separate sweep can name a run the chain missed.
- **Key the dedupe on the item id.** Content that goes back to an earlier state gets a new item
  id, so it would build again with no new act.
- **Let the run build the whole backlog.** It would build items no person consented to.
