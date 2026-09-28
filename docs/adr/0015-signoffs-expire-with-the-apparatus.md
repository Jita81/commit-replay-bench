# ADR-0015 — A sign-off expires with the apparatus: stale at read, never edited

**Status:** Accepted (operator decision DL-042; built in PR #32)
**Date:** 2026-09-17
**Apparatus impact:** none — deliberately. This changes how a sign-off is *read*, not what a
grade means: no belt, no grader, no routing threshold and no ledger row changes, so the
apparatus stays 2.2 and `signoff-policy.v2`'s write-time clauses are untouched. What changes
is one read-time rule in `apply_signoffs` and two served fields.

## Context

`docs/EVIDENCE-AND-CLAIMS.md` §4 has always said that evidence expires when the apparatus
changes: every ledger row carries its apparatus version, and a cell shows mixed versions
rather than blending them. A sign-off is a human attestation over a cell's evidence, stamped
with the apparatus the cell had at signing (`SignoffRecord.apparatus_version`, hash-covered).
Until this decision the stamp was recorded and displayed but **not applied at read**: a cell
signed under apparatus 2.1 kept its `human-verified` tier after the instrument moved to 2.2,
so a reader could quote a licence sentence about rows the signer never saw. The Claude Design
prototype (DL-042) drew this expiry as if it already existed; reading it against the code
showed it did not.

## Decision

1. **A sign-off covers a cell only while the cell's rows are inside its stamp.**
   `SignoffRecord.covers_apparatus(cell)` is true when every apparatus version among the
   cell's rows is in the record's stamped set. `apply_signoffs` lifts a tier only for records
   that both match the cell's scope and cover its apparatus. A record with no stamp
   (`crb.signoff.v1`, or a stored row whose cell carries none) cannot show that it covers
   the rows read now, so it covers nothing and is stale on every apparatus (amended
   2026-09-27, below). A cell with no rows is not judged here — the thin-cell rule refuses it.
2. **Stale is a state, not a deletion.** The row stays on the ledger, still verifies in the
   hash chain, and is served with `stale: true`, `apparatus_current: "<deployment's>"` and
   `active: false`. Nothing is edited (ADR-0002); the approver re-signs against the new rows
   or revokes with a reason. The Decisions inbox lists stale records under *Signed cells now
   stale*; the capability map cell reads *sign-off stale*.
3. **Two readings, one rule.** `GET /signoffs` judges `stale` against the deployment's
   current apparatus (the reading every screen uses). A pooled `/capability-map?apparatus=all`
   applies the stricter per-cell coverage rule to the rows it actually pooled and may decline
   to apply a record the list still shows as active; that is the rule doing its job on a
   reading the operator asked for, and API.md says so.
4. **No apparatus bump, no policy bump.** The house rule ("a change to the sign-off policy
   needs an ADR and an apparatus-version bump") exists so that measured evidence cannot be
   re-read under a moved instrument without a visible seam. This decision adds no clause to
   what a sign-off may attest at write and moves no instrument; it makes an existing seam
   (§4) bite at read. Bumping the apparatus here would itself make every current sign-off
   stale — the opposite of the intent. The ADR is the visible record instead.

## Consequences

- A deployment that bumps its apparatus sees every signed cell return to the Decisions inbox
  as stale until re-signed. That is the cost of the claim being true.
- The licence sentence on the capability map quotes the stamped snapshot (`n`, point, the
  interval, false-Q1, apparatus) *as signed*, and says so; current cell statistics are shown
  separately.
- Tested by `tests/test_signoff.py` (the coverage rule, apparatus 2.1 vs 2.2) and
  `tests/test_server_routes_signoffs.py` (a v1 or earlier-apparatus record served
  `stale: true`, `active: false`, `apparatus_current`); UI: `MapTable.test.tsx`,
  `DecisionsPage.test.tsx`.

## Amendment (2026-09-27) — a record with no stamp lifts nothing

**Context.** §1 as first written let a record with no apparatus stamp lift a cell on every
apparatus, on the ground that "the thin-cell and policy rules already refuse those". Those
rules run when the sign-off is written, not when the overlay reads it, so a record whose
evidence was graded by an older instrument went on licensing a cell forever — the
opposite of "evidence expires with the apparatus" (governance review 2026-09-27, GOV-6;
DL-083).

**Decision.** `SignoffRecord.covers_apparatus` is false for a record with an empty stamp
whenever the cell has rows, so `apply_signoffs` lifts nothing on it. `GET /signoffs` serves
such a record `stale: true`, `active: false`, with `stale_reason: "no_apparatus_stamp"`
(the other reasons are `apparatus_moved`, `checks_arm_moved` and `posture_moved`, first
match wins), and the Decisions inbox lists it under *Signed cells now stale* with that
reason, so an approver re-signs it on the current rows or revokes it. No apparatus bump:
the instrument has not moved; the read rule now matches §2's promise.

**Consequences.** A deployment carrying `crb.signoff.v1` records sees those cells return to
the inbox. Tested by `tests/test_signoff.py::test_a_sign_off_with_no_apparatus_stamp_lifts_nothing`
and `tests/test_server_routes_signoffs.py::TestListAndRevoke::test_a_row_with_no_apparatus_stamp_is_served_stale_and_asks_for_a_re_sign`.

## Alternatives considered

- **Bump the apparatus to 2.3 with this change** — rejected: it would stale every existing
  sign-off for a read-rule change, and would mislabel measurement rows whose grading did not
  change.
- **Delete or edit stale rows** — rejected by ADR-0002: the ledger is append-only.
- **Keep the tier and add a warning** — rejected: a warning beside a lifted tier is a licence
  to quote the tier without the warning.
