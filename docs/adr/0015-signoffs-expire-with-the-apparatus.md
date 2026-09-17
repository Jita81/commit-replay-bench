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
   (`crb.signoff.v1`) or a cell with no rows is not judged here — the thin-cell and policy
   rules already refuse those.
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

## Alternatives considered

- **Bump the apparatus to 2.3 with this change** — rejected: it would stale every existing
  sign-off for a read-rule change, and would mislabel measurement rows whose grading did not
  change.
- **Delete or edit stale rows** — rejected by ADR-0002: the ledger is append-only.
- **Keep the tier and add a warning** — rejected: a warning beside a lifted tier is a licence
  to quote the tier without the warning.
