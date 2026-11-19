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
   for the same item id, on the poll's path and the Register act's alike. A ticket whose
   words go back to content probed earlier is a new item; the poll registers it without
   the mark. A Register act cannot mark it after that: the act registers only a waiting
   draft later than the last registration, so it is refused `nothing_to_register`. To
   build those words, change the ticket's content: the change makes a new waiting draft,
   and a Register act on it starts a new probe.
3. **The worker's intake pass queues it.** After it tells the tickets, under the repository's
   intake lease, the pass looks for the oldest marked registration of that tracker with no
   `intake.manufacture.requested` or `intake.manufacture.skipped` for its
   `(tracker, key, content_revision)`, and queues at most one run per pass. The on-demand
   poll route never queues one.
4. **What it queues.** A `factory` run on `CRB_INTAKE__AUTO_MANUFACTURE_RUNG` with
   `deliver: true` and `max_rework` from `CRB_INTAKE__AUTO_MANUFACTURE_MAX_REWORK`. The run's
   cap is `CRB_INTAKE__AUTO_MANUFACTURE_MAX_COST_USD`, and each build attempt gets an equal
   share of it. The share is rounded down to a millionth of a dollar, so the build attempts
   together never pass the cap. The test author's calls are NOT capped: see "Consequences".
   `params.intake_item` names the item, and the worker builds that item only.
   `params.intake_auto` holds the key fields and who acted. The run meets the one submit gate
   `POST /runs` applies, and the factory params `POST /runs` pins. `POST /runs` cannot set
   either intake field.
5. **Once per content.** The run id is derived from `(repo, tracker, key, content_revision)`,
   so two passes that race insert one row and the second is refused by the store. The run and
   the system trace `intake.manufacture.queued` are written in one transaction. In it, in
   order: the pass still holds the intake lease; no run holds the key; no factory run on the
   repository is queued or running; the operator who acted is still an active operator;
   and, just before the insert, the pass is still in time and the chain shows no build or
   outcome for the item since its registration (the deadline is read again after that
   chain read). If any check fails, nothing is written and the consent stays pending; an
   approver found inactive there is recorded `approver_inactive` by the next pass. A run
   that already holds the key is named on the chain with the cap and rung it was stored
   with, and never queued again. A run held at claim (decision 8) does not hold the key:
   the next run of the key takes the next id, `attempt` 1, 2 and so on.
6. **Final skips.** `intake.manufacture.skipped` with a `reason`, never retried at that
   content: `item_superseded` (a later version is on the backlog), `has_dependencies`,
   `already_built` (a run graded or ended the item after the registration; the chain and the
   backlog are read again after the check for an active run, so a run that has just ended
   counts),
   `approver_inactive` (the operator who acted is no longer an active operator), `sealed`,
   `no_delivery_route` and `refused:<code>` (the submit gate's own code, or
   `validation_error` when the run request itself refuses the rung or cap).
7. **Waits.** A factory run already queued or running, a pass out of time, a lease lost
   (before an act or in the insert transaction) and an error reading the delivery route
   write nothing; the consent stays pending and the next pass tries again. The deadline is
   checked again after the delivery route is read, before a skip is written, and in the
   transaction that inserts the run, after the lease and the active-run check. The lease is
   renewed before each chain write, which narrows the window; the chain is not in the
   store's transaction, so it does not close it. Before it reads the runs of a key's
   earlier requests, the pass checks the deadline. It never reads them for a key a skip
   settled.
8. **The worker holds the run at its first claim.** Before any paid step, the worker reads
   the store and then the chain. It ends the automatic build failed at $0, with
   `system/run.refused` and code `intake_build_held`, when any other factory run on the
   repository is queued or running, in any order; when the chain shows a build or outcome
   for the item after its registration; or when the active runs or the chain cannot be
   read. Another automatic build holds it only when that build was queued earlier, so two
   never hold each other. The `intake.manufacture.requested` naming a held run no longer settles the
   key. The next pass reads the chain again: it records `already_built`, waits for the
   active run, or queues the next run of the key. A cancel accepted for the run wins over
   the hold: the worker ends it cancelled, and a run with an accepted cancel is never read
   as held, so its key stays settled. A cancel that cannot be read leaves the hold. A
   reclaimed run is never held: it may
   have spent before its worker stopped, so it goes on as the same run under its own cap.
   An operator's run is never held. This closes the window decision 5 leaves open on
   Postgres (see "Consequences"). The worker also refuses the item when it is no longer
   active or depends on other items, before it builds.
9. **Start-up refuses** the switch on without `CRB_INTAKE__GAP_PROBE`, without
   `CRB_INTAKE__REQUIRE_APPROVAL`, with an empty rung, or with a cap whose per-attempt share
   is above the per-run budget limit. Whenever a rung is set, with the switch on or off,
   start-up also builds the run request each pass queues (`manufacture_request`, the same
   function, with a stand-in repository name) and refuses the rung when that request
   refuses it. That covers each part's length and the one-label ladder: at most 128
   characters, of letters, digits and `._:/@-`. A pass that still meets a request it
   refuses records `refused:validation_error` once and does not retry.
10. **A switch-off does not withdraw a queued run.** Switching the listener or the setting
    off stops new runs. A run already queued stays queued; cancel it like any other run.

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
- The cap does not bound the test author. When the item has no person's test, the run uses
  the deployment's test author (`CRB_FACTORY__TEST_AUTHOR`). Its calls are counted in the
  run's spend, but they have no cap per call, and on the run's first authoring pass nothing
  is reserved for them. That pass (two calls by default) can take the spend past the cap,
  and the item's build attempts still run after it. The check after the loop
  (`cap.passed`) then ends the run failed, after the money was spent. A real bound needs a
  cap per author call; this change does not add one.
- The active-run check in the insert transaction is not serialised with `POST /runs`,
  which inserts with no lock. On SQLite the lease write serialises every writer, so no
  run commits unseen. On Postgres at READ COMMITTED, an operator's run can commit after
  that check and before the insert. Both runs are then queued. The worker's hold at the
  first claim (decision 8) closes this on any database. The claim reads after the
  automatic build committed, so a run the insert missed is seen then: queued or running,
  and the build is held; or ended, and its build or outcome for the item is already on
  the chain, and the build is held; or ended without building the item, and the build
  is right to go on. No lock is added to `POST /runs`.
- What stays open. An operator's run submitted after the automatic build's claim check
  can build the item again; that is the operator's own choice to queue a second build.
  A run that is reclaimed after it spent is not held, so it can build beside a run that
  started while it was stopped; reclaim does not change which runs may spend. Each hold
  is one failed $0 run, and a stuck active run makes each pass wait, not hold again; a
  run left `running` by a dead worker is reclaimed first. Active runs or a chain that
  cannot be read at claim hold the build each time a run is queued, at $0, until they
  read. Any error in that read holds, a programming error included.
- A store error in a claim check before the hold (the cancel read, or a refusal check)
  ends the automatic build failed with an ordinary error, at $0. That settles its consent;
  the operator changes the ticket's content, polls it to record a new waiting draft, and
  then registers it again. The new content has a new `content_revision`, which no build
  has settled. An edit that leaves the content the same keeps the settled
  `content_revision` and starts no automatic build. A build held and then cancelled has a
  `system/run.refused` event with `intake_build_held` before its `cancelled` finish, so
  count holds from run outcomes, not from those events.
- An operator's run that wrote a paid grade for the item and then failed or stopped
  before its chain record (`build.graded`), without being reclaimed, leaves no build on
  the chain. A chain write that raises after the grade committed is enough; no dead worker
  is needed. The automatic build then reads the item as unbuilt and can build it once
  more, under its own cap. The window is the time between the grade's commit and the
  chain write in one attempt. Closing it needs the grades read beside the chain; this change does
  not add that.
- Each pass reads one run row per earlier request of a key that no skip settled, until it
  finds a run not held. The chain only grows, so a long history makes that read longer. A
  pass that runs out of time writes nothing and waits; it never spends. One bounded query
  per pass would remove this cost; this change does not add one.
- Holds cost the automatic build some turns. An operator's run queued after the
  automatic build, but before a worker claims it, also holds it. The consent is not
  lost: the next pass records `already_built` or queues the build again.
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
