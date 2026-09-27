# ADR-0018 — A signed cell licenses delivery: the gate reads the sign-off as well as the route

**Status:** Accepted (DL-120; wave 4, stream S; closes G-517). Decisions 1, 3 and 5
**as drafted** on 2026-09-23 are superseded in part by [ADR-0026](0026-the-context-standard.md)
item 8 before this ADR merged; the decisions below are the amended text, and each superseded
draft is quoted under [What ADR-0026 supersedes](#what-adr-0026-supersedes).
**Date:** 2026-09-23 (amended 2026-09-27, DL-120)
**Apparatus impact:** none. This changes *which tickets the factory may build and deliver*, not
what a grade means: no belt, no grader, no routing threshold, no ledger column and no sign-off
clause moves, so `crb.core.version.APPARATUS_VERSION` stays where it is and `signoff-policy.v3`
/ `crb.signoff.v4` stay as they are (the ADR-0016 §3 argument applies unchanged). The visible
seam is the stop code `unsigned_cell` on the item's evidence chain and the posture line that
says which setting is in force.

## Context

`FactoryLoop._deliver` gated delivery on one thing: the capability map's route for the item's
(class × size) cell, read once at readiness (DL-038, DL-045). `route == deliver` opened a branch
and a pull request; anything else withheld it. The route is a **measurement** — n, the Wilson
lower bound, false-Q1, the controls verdict, the oracle's strength — and nothing in it is a
person.

Three things in this product already said something different:

1. `docs/ONBOARDING-A-REPO.md` puts **step 7 (sign off)** before **step 8 (forward mode)**, and
   step 8 is where a pull request is first opened.
2. `docs/dod/streams/decide-and-license.md` criterion `handoff.13` states the handoff in its own
   words: "a cell's sign-off licenses the delivery — the factory's gate reads the sign-off as
   well as the route, so a cell routing `deliver` with no human sign-off does not open a pull
   request". The criterion was `partial`: the second half was not true of the code.
3. `docs/EVIDENCE-AND-CLAIMS.md` §6a says what a signed cell may be claimed to mean, and the
   product's own sentence for the factory is that it "delivers changes only in cells the
   baseline licenses".

The code licensed on the measurement alone. So a cell that measures well could license a pull
request in a customer's repository with **no human attestation anywhere** — and that is what
B-1b actually ran (`project_crb_b1b`: PRs #1 and #2 on `Jita81/cobra` were delivered from an
unsigned `deliver` route). [measured — n = 2 delivered pull requests, apparatus 2.2; the runs are
on the factory evidence chain, not a rate]

The question this ADR answers: **is an active sign-off a precondition of delivery, and if so with
what default and what override?**

## Decision

1. **A signed cell is a precondition of entry, and it is the default.**
   `FactorySpec.require_signed_cell` defaults to `True` (`CRB_FACTORY__REQUIRE_SIGNED_CELL`,
   default true). A ticket whose cell has a **proven standard that is not a ceiling** but no
   active sign-off on it **stops before any spend** with the stop code `unsigned_cell`: no
   oracle is authored, nothing is built, graded or reviewed, and no pull request can follow.
   The stop is recorded on the item's evidence chain (a `route.decided` event carrying
   `reason_code: unsigned_cell` and the tier it read) and emitted as the `entry.refused` step
   event, and the item's status is `unsigned_cell`. It applies whether or not delivery is
   switched on for the run, as ADR-0026 item 8's entry gate does.
   - *Signed* means an active attestation (not revoked, scoped to this repository) that
     covers the cell **on the current apparatus** (ADR-0015), **in the posture class the
     cell is read in** (ADR-0019 §8, `crb.signoff.v4`) and **on the repository's own
     `checks` arm** (ADR-0024) — exactly the overlay
     `crb.core.signoff.apply_signoffs` already applies, withheld the moment the cell's own
     `false_q1` stops being 0. When routing.v2 lands (ADR-0026 item 6) the same overlay is
     also scoped to the standard's **context arm, class-set version and reading**; that
     reader is stream R's, and ADR-0026's entry gate reads `Standard.signed` from it.
   - *A proven standard that is not a ceiling* is ADR-0026's `standard_for(repo, cell)`.
     Until that reader lands, the code's stand-in is the one proof it has: the cell's route,
     read once at readiness, says `deliver`. A cell that does not route `deliver` is left to
     the route clause (and, after the integration, to `no_proven_standard`); this clause
     never builds what the entry gate would stop.
2. **The clause reads the reading already taken, and adds no second look.** The tier comes from
   the same cell decision the loop read ONCE at readiness (DL-045): the worker's
   `_route_lookup` builds it from `signed_map`, which overlays the repo's sign-off records
   through `crb.core.signoff.apply_signoffs`. So "signed" here means exactly what the
   Capability page means by it, and a stale sign-off licenses nothing.
3. **The override lifts the sign-off clause and nothing else, for one named run, and is
   evented.** A run queued with `deliver_override` (approver role only; `POST /runs` stamps
   the approver's identity into `params.deliver_override_by`) admits an item that would stop
   `unsigned_cell` — and only that. It writes a `route.decided` evidence event naming the
   clause (`clause: unsigned_cell`), the approver and the tier it read, and a
   `delivery.override` step event. It never lifts `no_proven_standard`, a ceiling,
   `needs_context`, a calibration build, `size_exceeds_licence` or `cell_not_licensed`
   (ADR-0026 item 8), and it no longer lifts the route clause: a cell that does not route
   `deliver` opens no pull request under any override (ADR-0026 supersedes ADR-0003's
   amendment of 2026-09-16, decision 1, in this respect).
4. **What an override may be claimed to mean is bounded, and the product says so.** An override
   is one named person licensing **one run** to build and deliver in a cell nobody has signed.
   It does not lift the cell's verification tier, it is not an attestation, it names no
   attested row, and no two-person claim may be made about it: the approver who overrides is
   the operator who queued the run (`POST /runs` stamps one identity for both). The pull
   request body says which licence it was opened under — `licence: **signed cell**
   (human-verified)` or `licence: **unsigned cell** — opened under a named override` — so the
   reader who merges it is never told a second person had attested when none had. The second
   person for an overridden delivery is the human who merges the pull request; the factory
   never touches the default branch (ADR-0014, the delivery contract).
5. **A deployment may remove the sign-off clause, never the entry gate, and that posture is
   visible.** `CRB_FACTORY__REQUIRE_SIGNED_CELL=false` removes this clause only: the proven
   standard alone is then the bar, and every other stop of ADR-0026 item 8 still applies. It
   is not a hidden knob: `GET /settings` reports `require_signed_cell`, the Posture page's
   **Delivery licence** row states which posture is in force, and the Factory screen's
   per-item prediction (`cell_route.deliverable`) is computed under the setting, so an
   operator sees before spending anything whether an item would be built and delivered.

## What ADR-0026 supersedes

ADR-0026 item 8 (Proposed, 2026-09-27) re-read this ADR before it merged. Three decisions as
drafted on 2026-09-23 do not stand:

- **Decision 1 as drafted — build and withhold.** "The gate refuses an item whose cell carries
  no earned verification tier … Nothing is pushed and no pull request is opened; the item is
  still built, graded and reviewed." Superseded: an unsigned cell stops the ticket **before any
  spend**. Building a change that can never be delivered spent the operator's money on work
  nobody could use.
- **Decision 3 as drafted — the override lifts both clauses.** "`deliver_override` … overrides
  the delivery gate — both clauses." Superseded: the override lifts only a missing sign-off on
  a proven standard that is not a ceiling. The route clause is no longer overridable.
- **Decision 5 as drafted — the route alone.** "`CRB_FACTORY__REQUIRE_SIGNED_CELL=false`
  returns the pre-decision behaviour … the measurement is its licence." Superseded in meaning:
  the setting removes the sign-off clause only, and "the route alone" now means **the proven
  standard alone**; it never removes the entry gate.

Decisions 2 and 4 stand as drafted.

## Consequences

- **What becomes harder, on purpose.** After an apparatus bump every sign-off is stale
  (ADR-0015), so with the default a deployment mid-apparatus-move builds nothing in its
  proven cells until they are re-signed. That is the cost, it is stated here, and it is the
  same rule the Capability page already applies to trust: evidence expires when the instrument
  moves. A deployment that cannot wait has two stated ways through — an approver's named
  per-run override of the sign-off clause, or the setting — and both are on the record.
- **What becomes cheaper.** A ticket in an unsigned cell costs nothing: it stops before the
  test author, the builder or the reviewer is called (ADR-0026 item 8), where the draft built
  it at the operator's cost and then withheld the one thing the build was for.
- **What becomes easier.** The onboarding order is now the code's order: step 7 before step 8.
  A reader of a delivered pull request can tell, from the body alone, whether a human had
  attested the cell it came from. `handoff.13` is true in its amended words: a cell that
  routes `deliver` with no human sign-off is not built, so it opens no pull request.
- **What we must never do.** Silently lift the clause: there is no per-item, per-repository or
  per-cell relaxation, no unnamed override, and the override never writes a sign-off record
  and never lifts another stop. And never re-read the map to satisfy this clause — a build's
  own clean row must not be what makes its cell look signed (DL-045); the readiness reading is
  the only reading.
- **What the integration wires.** ADR-0026's entry gate (stream F, `decide_entry`) carries the
  sign-off clause in its own words; this ADR fixes its default (`require_signed_cell=True`),
  what *signed* reads (the overlay above, bound into `Standard.signed` by stream R's
  `standard_for`) and the override's reach. The stand-in on this code (the route read at
  readiness) is replaced by `standard_for` when those land.
- Tested by `tests/test_factory_loop.py` (`TestSignedCellClause`: an unsigned `deliver` cell
  stops before any spend with its own status and event, whether or not delivery is on; a
  signed one is built and delivered; `automated-pass` and an absent tier are not a licence;
  the setting removes only this clause; the named override lifts only this clause and is on
  the record; it never lifts the route), `tests/test_worker.py` (the served lookup carries the
  tier) and `tests/test_server_routes_factory.py` (the pre-run prediction honours the clause).

## Alternatives considered

- **Leave the route as the only gate and correct the documents instead** (delete the handoff
  criterion's second half, move onboarding step 7 after step 8). Rejected: it would make the
  product's own sentence — "a signed cell is what licenses delivery" — false in the one place it
  matters, and it would leave the deployment with no way to require a human before a pull request
  reaches a customer's repository. The cost of rejecting it is the one named above: delivery
  stops when sign-offs go stale.
- **Gate on the sign-off, default OFF (opt-in).** Rejected: the safe posture would be the one
  nobody selected, which is how the `/automation-map` default executor came to fabricate
  (landmark 2026-07-04). A gate whose default is off is a gate the first real run does not have.
- **Require the sign-off with no override at all.** Rejected, narrowly. It is the strictest
  option and it was tempting; it was rejected because an unoverridable clause would make the
  first delivery of a newly measured repository impossible to perform without first signing a
  cell whose evidence the approver may legitimately still be reading. The override is instead
  narrowed to this clause alone (ADR-0026 item 8), its meaning is bounded in Decision 4, and
  it is recorded.
- **Make the override refuse the approver who queued the run (`same_actor` for delivery).**
  Rejected as written, because `POST /runs` stamps one identity as both the run's actor and the
  override's approver, so the clause would refuse every override that can be requested today —
  a gate that reads as a two-person rule but is really "no override". The honest form is
  Decision 4: the override is one person, the product says it is one person, and the merge is
  where the second person is.
- **Write a sign-off record on an override** (so the cell shows as signed afterwards).
  Rejected by ADR-0002 and ADR-0016: an attestation names an accepted row a human read and is
  refused at write by `signoff-policy.v3`. Minting one from a delivery decision would fabricate
  the very record the two-person rule protects.
