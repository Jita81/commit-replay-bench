# ADR-0016 — The two-person rule is a policy clause, not an apparatus move

**Status:** Accepted (architect decision DL-047; built in PR #45)
**Date:** 2026-09-21
**Apparatus impact:** none — deliberately. `same_actor` changes what a sign-off may *attest at
write*, not what a grade means: no belt, no grader, no routing threshold and no ledger row
changes, so `crb.core.version.APPARATUS_VERSION` stays `2.2`. The visible seam is the sign-off
record's own version pair — `policy_version` (`signoff-policy.v2` → `signoff-policy.v3`) and
`schema` (`crb.signoff.v2` → `crb.signoff.v3`) — both hash-covered and served on every read.

## Context

The house rule for `src/crb/core/**` (`.coderabbit.yaml`; `docs/CONTRIBUTING.md` "How to add
an ADR", step 4; `docs/EVIDENCE-AND-CLAIMS.md` §4) says a change to the sign-off policy needs
an ADR and an apparatus-version bump. The rule exists so that measured evidence can never be
re-read under a moved instrument without a visible seam: a grade row stamped `2.1` must never
blend with one stamped `2.2`, and a sign-off stamped under one apparatus must not license a
cell whose rows were graded under another (ADR-0015).

DL-047 (F7b) added the fourth non-overridable clause to `crb.core.signoff.SignoffPolicy`:
`same_actor` — the approver is refused when they are the actor of the attested row
(`Grade.actor`), the actor of the run that produced it (`Run.actor`), or the only person
behind the cell's accepted evidence. With it the policy version moved to `signoff-policy.v3`
(`require_independent_verifier`, stamped, non-relaxable) and the record schema to
`crb.signoff.v3` (`verifier_kind`, F34). The question this ADR answers is whether that change
is an *apparatus* move — and it is not, for the reason ADR-0015 §4 already gave for the
read-time expiry rule.

## Decision

1. **`same_actor` is a write-time policy clause; the apparatus does not move.** The clause
   is evaluated by `crb.core.signoff.same_actor_refusal` inside `evaluate_signoff` /
   `check_signable` on the actors the write boundary resolves
   (`crb.server.routes.signoffs.cell_actors`, `Grade.actor`, `Run.actor`). It reads no belt,
   changes no grader, moves no routing threshold and adds no ledger column
   (`verifier_kind` lives in the record's `cell_json` snapshot, as the attestation does). A
   grade row graded before and after this decision means exactly the same thing, so
   `APPARATUS_VERSION` stays `2.2`.
2. **The seam is `policy_version` and `schema`, not the apparatus stamp.** Every sign-off
   record stamps `policy_version` (`signoff-policy.v1` / `v2` / `v3`) and `schema`
   (`crb.signoff.v1` / `v2` / `v3`) under `row_hash`, and `GET /signoffs` serves both on
   every read (`docs/API.md`). An auditor reads from the record itself whether the two-person
   rule was in force when a cell was signed: `policy_version: signoff-policy.v3` and
   `policy_thresholds.require_independent_verifier: true` say it was; `v2` or `v1` say it
   was not. That is the module's own rule — "a new clause bumps the policy version so an audit
   reads from the record whether the rule was in force" (`crb.core.signoff` module docstring)
   — and it is the same mechanism that already distinguishes a `v1` record (no
   `require_oracle_measured`) from a `v2` one.
3. **Bumping the apparatus would be wrong, not merely unnecessary.** ADR-0015 §4: bumping
   `APPARATUS_VERSION` makes every current sign-off `stale` at read and mislabels every
   measurement row whose grading did not change. Doing that for a clause that constrains
   *who may sign* would stale every signed cell in every deployment for a change that did not
   touch a single grade — the opposite of a visible seam, because the seam would then say
   "the instrument moved" when it did not.
4. **Pre-v3 records stay valid and are identifiable, not re-judged.** A record signed under
   `signoff-policy.v2` (or `v1`) keeps its stamp, still verifies in the hash chain (the v2
   body's field tuple is frozen — `tests/test_signoff.py::test_v2_record_still_verifies_and_reads_as_v2_with_no_verifier_kind`),
   and lifts its cell exactly as before. Nothing is edited (ADR-0002). What such a record
   does *not* say is that a second person signed it; a reader quoting it must quote it as
   signed under its own policy version (EVIDENCE-AND-CLAIMS §6a).

## Consequences

- A deployment that upgrades sees no sign-off go stale; every record it holds keeps its
  stamped meaning. The cost of that is the one named in (4): an active pre-v3 sign-off may
  have been signed by the person who produced its evidence, and today the record only lets
  an auditor *tell* that, not lists it. Backlog **F53** (docs/reviews/2026-09-17-enterprise-front-end.md
  §9): re-judge active pre-v3 sign-offs under `same_actor` at read and list them in the
  Decisions inbox as "signed before the two-person rule" (n and m served) — a read rule in
  the spirit of ADR-0015, no apparatus bump, no edit to the row.
- The house rule is read as it was written for: "a change to the sign-off policy needs an
  ADR" holds (this is that ADR); "and an apparatus bump" applies when the change moves what a
  grade means. A future clause that *re-weights evidence* (a threshold on a belt, a different
  clean rule, a routing change) still bumps the apparatus; a clause on who may attest, or on
  what the attestation must name, bumps `signoff-policy` and `crb.signoff` instead.
- Tested by `tests/test_signoff.py` (`same_actor` on each ground, the clause last and not
  liftable by a relaxed policy, a v3 record round-trips under `crb.signoff.v3`, a v2 record
  keeps its hash and reads as `v2`) and `tests/test_server_routes_signoffs.py::TestTwoPersonRule`
  (the API refuses at write and in the preview; a second approver signs; the served record
  carries `policy_version: signoff-policy.v3`). `tests/test_version_consistency.py` pins the
  apparatus at `2.2`. [measured — n = 14 + 4 tests, apparatus 2.2; pass/fail, not a rate;
  the counts are stated in SECURITY.md §3.4]

## Alternatives considered

- **Bump the apparatus to 2.3 with this change** — rejected by the ADR-0015 §4 argument: it
  would stale every existing sign-off and mislabel measurement rows whose grading did not
  change, for a clause that constrains the signer, not the grade.
- **Re-judge pre-v3 records at write time (revoke or edit them)** — rejected by ADR-0002:
  the ledger is append-only; a record's meaning is what it stamped. The read-time listing is
  F53.
- **Bump only the record schema (`crb.signoff.v3`) and leave `policy_version` at `v2`** —
  rejected: `policy_thresholds` would then carry `require_independent_verifier` under a
  version that never defined it, and an auditor could not tell from `policy_version` alone
  whether the rule was in force. The module's rule is one clause, one policy version.
