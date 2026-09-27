# ADR-0018 — A signed cell licenses delivery: the gate reads the sign-off as well as the route

**Status:** Accepted (wave 2, stream S; closes G-517)
**Date:** 2026-09-23
**Apparatus impact:** none. This changes *when the factory may open a pull request*, not what a
grade means: no belt, no grader, no routing threshold, no ledger column and no sign-off clause
moves, so `crb.core.version.APPARATUS_VERSION` stays `2.2` and `signoff-policy.v3` /
`crb.signoff.v3` stay as they are (the ADR-0016 §3 argument applies unchanged). The visible seam
is the refusal code `unsigned_cell` on the item's evidence chain and the posture line that says
which setting is in force.

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

1. **A signed cell is a precondition of delivery, and it is the default.**
   `FactorySpec.require_signed_cell` defaults to `True`. In `FactoryLoop._deliver`, after the
   route clause, the gate refuses an item whose cell carries no earned verification tier
   (`crb.core.capability.EARNED_TIERS` — `human-verified` or `ab-confirmed`) with refusal code
   `unsigned_cell`, records `delivery.refused` on the evidence chain and emits its own
   `delivery.unsigned` step event. Nothing is pushed and no pull request is opened; the item is
   still built, graded and reviewed, exactly as a route refusal leaves it.
2. **The clause reads the reading already taken, and adds no second look.** The tier comes from
   the same cell decision the loop read ONCE at readiness (DL-045): the worker's
   `_route_lookup` builds it from `signed_map`, which overlays the repo's sign-off records
   through `crb.core.signoff.apply_signoffs`. That overlay already enforces every property this
   gate needs — the attestation is active (not revoked), scoped to this repository, made on the
   cell's own apparatus (ADR-0015), and withheld the moment the cell's own `false_q1` stops
   being 0. So "signed" here means exactly what the Capability page means by it, and a stale
   sign-off licenses nothing.
3. **The override is the one that already exists, is named, and is recorded per clause.** A run
   queued with `deliver_override` (approver role only; `POST /runs` stamps the approver's
   identity into `params.deliver_override_by`) overrides the delivery gate — both clauses.
   Each overridden clause writes its own `route.decided` evidence event naming the clause, the
   approver and what was overridden, and its own `delivery.override` step event.
4. **What an override may be claimed to mean is bounded, and the product says so.** An override
   is one named person licensing **one run** to open a pull request. It does not lift the cell's
   verification tier, it is not an attestation, it names no attested row, and no two-person claim
   may be made about it: the approver who overrides is the operator who queued the run (`POST
   /runs` stamps one identity for both). The pull request body says which licence it was opened
   under — `licence: **signed cell** (human-verified)` or `licence: **unsigned cell** — opened
   under a named override` — so the reader who merges it is never told a second person had
   attested when none had. The second person for an overridden delivery is the human who merges
   the pull request; the factory never touches the default branch (ADR-0014, the delivery
   contract).
5. **A deployment may set the route alone as its bar, and that posture is visible.**
   `CRB_FACTORY__REQUIRE_SIGNED_CELL=false` returns the pre-decision behaviour for a deployment
   that decides the measurement is its licence. It is not a hidden knob: `GET /settings` reports
   `require_signed_cell`, the Posture page's **Delivery licence** row states which of the two
   postures is in force, and the Factory screen's per-item prediction (`cell_route.deliverable`)
   is computed under the setting, so an operator sees before spending anything whether a clean
   build of that item would be delivered or withheld.

## Consequences

- **What becomes harder, on purpose.** After an apparatus bump every sign-off is stale
  (ADR-0015), so with the default a deployment mid-apparatus-move delivers nothing until the
  cells it delivers from are re-signed. That is the cost, it is stated here, and it is the same
  rule the Capability page already applies to trust: evidence expires when the instrument moves.
  A deployment that cannot wait has two stated ways through — an approver's named per-run
  override, or the setting — and both are on the record.
- **What becomes easier.** The onboarding order is now the code's order: step 7 before step 8.
  A reader of a delivered pull request can tell, from the body alone, whether a human had
  attested the cell it came from. `handoff.13` is true in the words it was written in.
- **What we must never do.** Silently lift the clause: there is no per-item, per-repository or
  per-cell relaxation, no unnamed override, and the override never writes a sign-off record.
  And never re-read the map to satisfy this clause — a build's own clean row must not be what
  makes its cell look signed (DL-045); the readiness reading is the only reading.
- Tested by `tests/test_factory_loop.py` (`TestSignedCellGate`: withheld on an unsigned cell with
  the refusal code and event, delivered on a signed one, both settings, the named override on
  the record, `automated-pass` is not a licence), `tests/test_worker.py` (the served lookup
  carries the tier) and `tests/test_server_routes_factory.py` (the pre-run prediction honours the
  clause). [measured — n = 8 tests, apparatus 2.2; pass/fail, not a rate]

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
  option and it was tempting; it was rejected because the override already exists for the route
  clause with an approver's name on it, and an unoverridable clause would make the first
  delivery of a newly measured repository impossible to perform without first signing a cell
  whose evidence the approver may legitimately still be reading. The override's meaning is
  bounded in Decision 4 instead, and it is recorded.
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
