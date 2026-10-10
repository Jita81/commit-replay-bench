# ADR-0018 — A signed cell licenses delivery: the gate reads the sign-off as well as the route

**Status:** Accepted (DL-106; wave 4, stream S; closes G-517). Every decision **as drafted**
on 2026-09-23 is superseded in part by [ADR-0026](0026-the-context-standard.md) item 8 or by
the Wave 4 integration (GOV-4) before this ADR merged; the decisions below are the amended
text, and each superseded draft is quoted under
[What ADR-0026 supersedes](#what-adr-0026-supersedes). Decision 1's clause is read at the
delivered change's own cell too, since the Wave 4 attack (DL-119).
**Date:** 2026-09-23 (amended 2026-09-27, DL-106; 2026-09-28, DL-119; 2026-10-10, G-738)
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
   The stop is recorded on the item's evidence chain (an `entry.refused` event and a
   `route.decided` event carrying `reason_code: unsigned_cell`, the entry decision with the
   cells the size rule read and the standard it applied) and emitted as the `entry.refused`
   step event, and the item's status is `unsigned_cell`. It applies whether or not delivery is
   switched on for the run, as ADR-0026 item 8's entry gate does.
   - **The clause is read again at the delivered change's own cell** (DL-119, P-391). The
     entry gate reads the cells the size rule names from the ticket's **estimate** — the
     estimate cell and, until the points-to-churn agreement passes, the next larger one. A
     change that measures larger than both lands in a cell the entry gate never read. So,
     after the build and the route gate, with the clause on, the delivered cell's own
     standard (`own_cell_licence`'s `Licence.standard`: class, measured size, the building
     rung's builder, model and provider, and the arm the build carried) must carry an active
     sign-off too, or a second approver's override must lift it under the same bounds as at
     entry (decision 3); otherwise the item stops `unsigned_cell` at delivery, with both sizes
     and the licence on a `delivery.refused` event, and no pull request opens.
   - *Signed* means an active attestation (not revoked, not superseded, scoped to this
     repository, on an intact sign-off chain) that covers the cell **on the current
     apparatus** (ADR-0015), **in the posture class the cell is read in** (ADR-0019 §8,
     `crb.signoff.v4`), **on the repository's own `checks` arm** (ADR-0024) and on the
     standard's **context arm, class-set version and reading** (ADR-0026 item 6), made by an
     approver whose account is **active now** (ADR-0016's amendment of 2026-09-28, DL-120: a
     leaver's sign-off lifts nothing). The one reader is
     `crb.server.factory_standard.signed_by` over `load_signoff_records`.
   - *A proven standard that is not a ceiling* is ADR-0026's `standard_for(repo, cell)`.
     Since the Wave 4 integration (DL-106) the clause is the entry gate's own `unsigned_cell`
     stop (`crb.factory.standard.decide_entry`) over the store-bound readers
     (`crb.server.factory_standard`), so *signed* is `Standard.signed`: a sign-off made on the
     standard's arm, class-set version and reading. A cell with no proven standard, or only
     an `S3` ceiling, stops `no_proven_standard` instead; this clause never builds what the
     entry gate would stop.
2. **The clause reads one binding, taken before any build, and adds no second look.** *Signed*
   is `Standard.signed`, from the `standard_for` reader the worker binds ONCE per run before
   any build (`crb.server.factory_standard.bind_readers`, over the pre-run store — DL-045,
   DL-106): the entry gate, the delivered cell's re-read (decision 1), the factory screen's
   prediction and the ticket feedback all ask that reader, with the same
   `require_signed_cell`. A build's own row never makes its cell look signed, and a stale
   sign-off licenses nothing. The capability map's verification tier (`apply_signoffs`) is a
   different reader with a different matching rule; it is not what this clause reads. Since
   G-738 every other reader of *signed* asks this clause's own predicate,
   `crb.factory.standard.cell_signed`, over the same binding
   (`crb.server.factory_standard.deployment_readers`): the decisions inbox's "sign-off due"
   and the map, which serves it as each cell's `signed` beside the tier (P-411). The map
   serves `null` for a cell that pools classes or sizes, which the gate never reads, and on
   an organisation's class-set view, whose cells are keyed by the global parent (G-763).
3. **The override lifts the sign-off clause and nothing else, for one named run, and is
   evented.** It is granted on a queued or running factory run that delivers, by a **second
   approver**, with `POST /runs/{id}/deliver-override` (GOV-4): the route stamps the
   approver's id into `params.deliver_override_by` and appends a `system/run.deliver_override`
   event naming them on the run's trace, in one transaction. `POST /runs` refuses
   `deliver_override` at enqueue (409 `same_actor`), and the worker honours a grant only
   while that approver's account is active and holds the approver role (P-229). At the entry
   gate it admits an item that would stop `unsigned_cell` — and only that — and writes a
   `route.decided` evidence event whose reason reads "sign-off clause lifted by <approver> for
   this run", carrying `override_by` and the standard it lifted, plus a `delivery.override`
   step event. At the delivered cell (decision 1) the same approver lifts the same clause, and
   the delivery event's `licence` names them (`override_by`). A refused override is recorded
   as `override_refused` with the reason. It never lifts `no_proven_standard`, a ceiling,
   `needs_context`, a calibration build, `size_exceeds_licence` or `cell_not_licensed`
   (ADR-0026 item 8), and it never lifts the route gate: a cell that does not route `deliver`
   opens no pull request under any override (ADR-0026 supersedes ADR-0003's amendment of
   2026-09-16, decision 1, in this respect).
4. **What an override may be claimed to mean is bounded, and the product says so.** An override
   is one named **second approver** — never the run's own actor, never on a cell with a
   false-Q1 row in any cell the size rule reads or in the delivered cell (the honesty floor,
   GOV-1) — licensing **one run** to build and deliver in a cell nobody has signed. It does
   not lift the cell's verification tier, it is not an attestation and it names no attested
   row. The pull request body says which licence it was opened under, read from the
   **delivered** change's own cell, never the estimate's (DL-119, P-391):
   `licence: **signed cell** — the cell's proven standard (<arm>) carries an active sign-off`,
   `licence: **unsigned cell** — opened under a per-run override of the sign-off clause by
   approver <id>, not a human attestation of the cell`, or `licence: **unsigned cell** — this
   deployment does not require a signed cell` — so the reader who merges it is never told a
   person had attested the cell when none had. The factory never touches the default branch
   (ADR-0014, the delivery contract).
5. **A deployment may remove the sign-off clause, never the entry gate, and that posture is
   visible.** `CRB_FACTORY__REQUIRE_SIGNED_CELL=false` removes this clause only: the proven
   standard alone is then the bar, and every other stop of ADR-0026 item 8 still applies. It
   is not a hidden knob: `GET /settings` reports `require_signed_cell`, the Posture page's
   **Delivery licence** row states which posture is in force, and the Factory screen's
   per-item prediction (`cell_route.deliverable`) is computed under the setting, so an
   operator sees before spending anything whether an item would be built and delivered.

## What ADR-0026 supersedes

ADR-0026 item 8 (Proposed, 2026-09-27) re-read this ADR before it merged, and the Wave 4
integration (GOV-4, 2026-09-28) moved the override to a second approver. No decision as drafted
on 2026-09-23 stands whole:

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

- **Decision 2 as drafted — the map's tier.** "The tier comes from the same cell decision the
  loop read ONCE at readiness (DL-045): the worker's `_route_lookup` builds it from
  `signed_map` … So "signed" here means exactly what the Capability page means by it."
  Superseded (DL-106): *signed* is `Standard.signed` from the `standard_for` reader bound once
  before any build — a sign-off on the standard's arm, class-set version and reading. The
  map's tier is another reader. The decisions inbox asks this clause itself over the same
  binding, and the map serves the clause's reading beside the tier as `signed` (G-738); the
  Capability page still shows only the tier (G-303).
- **Decision 3 as drafted — the override queued with the run.** "A run queued with
  `deliver_override` (approver role only; `POST /runs` stamps the approver's identity into
  `params.deliver_override_by`) … It writes a `route.decided` evidence event naming the clause
  (`clause: unsigned_cell`), the approver and the tier it read." Superseded (GOV-4): `POST
  /runs` refuses `deliver_override` with 409 `same_actor`; a second approver grants it with
  `POST /runs/{id}/deliver-override`; the evidence event carries `override_by` and the
  standard, not a clause field or a tier.
- **Decision 4 as drafted — one person.** "No two-person claim may be made about it: the
  approver who overrides is the operator who queued the run (`POST /runs` stamps one identity
  for both)." Superseded (GOV-4): the override is a second approver's, never the run's actor;
  and the licence line is the delivered cell's (DL-119).

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
  `standard_for`) and the override's reach. At the Wave 4 integration (2026-09-28) the
  route stand-in was removed: the clause is `decide_entry`'s, the factory screen and the
  ticket feedback read the same `standard_for` and the same `require_signed_cell`, and the
  override is a second approver's act on the run's page (`POST /runs/{id}/deliver-override`,
  GOV-4) — never the run's own actor, never on a false-Q1 cell — which supersedes decision
  4's "the approver who overrides is the operator who queued the run". The pull request
  names the licence as the entry gate decided it: a signed standard, a named second
  approver's override, or a deployment that does not require a signed cell.
- Tested by `tests/test_factory_loop.py` (`TestSignedCellClause`: an unsigned `deliver` cell
  stops before any spend with its own status and event, whether or not delivery is on; a
  signed standard is built and delivered; the setting removes only this clause; the named
  override lifts only this clause and is on the record; it never lifts the route;
  `test_the_sign_off_override_is_never_the_runs_own_actor`,
  `test_no_override_lifts_anything_on_a_false_q1_cell` and
  `test_the_override_is_refused_when_any_cell_the_size_rule_reads_carries_false_q1`: the
  override's bounds; `test_a_change_larger_than_its_estimate_is_delivered_only_into_a_signed_cell`
  and `test_the_licence_line_is_the_delivered_cells_not_the_estimates`: decision 1's
  delivered-cell read and decision 4's licence line), `tests/test_worker.py` (the production
  path stops an unsigned cell unless configured off; an override is honoured only from an
  active second approver), `tests/test_server_routes_factory.py` (409 `same_actor` at
  enqueue and at the grant; the
  pre-run prediction honours the clause), `tests/test_intake_worker.py` and
  `tests/test_server_routes_intake.py` (the served ticket feedback names the clause) and
  `tests/test_governed_delivery_e2e.py` (a leaver's sign-off licenses nothing).

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
  Rejected as drafted, because `POST /runs` then stamped one identity as both the run's actor
  and the override's approver, so the clause would have refused every override that could be
  requested — a gate that read as a two-person rule but was really "no override". **Adopted
  at the Wave 4 integration (GOV-4)**, once the grant became its own act: `POST /runs` refuses
  `deliver_override` at enqueue, a second approver grants it with
  `POST /runs/{id}/deliver-override`, and the API, the worker and the loop each refuse an
  override named by the run's own actor.
- **Write a sign-off record on an override** (so the cell shows as signed afterwards).
  Rejected by ADR-0002 and ADR-0016: an attestation names an accepted row a human read and is
  refused at write by `signoff-policy.v3`. Minting one from a delivery decision would fabricate
  the very record the two-person rule protects.
