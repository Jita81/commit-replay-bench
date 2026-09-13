# ADR-0007 — Cross-organisation learning: abstract cell export only

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** none

## Context

Each deployment measures only its own repositories, so a new deployment starts with an
empty capability map and every cell routed `calibrate`. It would be useful for a new
organisation to inherit priors — "in other deployments, `bug.fix × S × python` with this
builder and model was at `deliver`" — without any organisation's code, task ids or
repository names leaving its tenant. Upstream `tuning/federated.py` sketched the boundary
(an allowlist and k-anonymity) but nothing consumed it. `[aspiration]`: the claim
`federated_cross_tenant_learning` in the upstream claim contract has `n=0`; this ADR
designs the boundary, it does not demonstrate the benefit.

## Decision

1. **The cell is the abstraction boundary.** `crb.core.ledger.CellKey` is defined as
   `(process_step, capability_class, size, language, builder, model, provider)` and by
   construction carries **no task id, no repo, no free text**.
2. The only object that may leave a deployment is a **cell statistic**:
   `CellStats.to_dict()` → the cell key fields plus `n`, `clean`, `disqualified`, `errors`,
   `false_q1`, `point`, `ci_low`, `ci_high`, `cost_usd_mean`, `latency_s_mean`,
   `oracle_strength_mean`, `apparatus_versions`. Nothing else — no rows, no packs, no
   labels, no timestamps finer than the export date.
3. `crb.core.federated` (P2) implements the export with:
   - an **allowlist ratchet** — the exported field set is an explicit tuple in code; adding
     a field requires a test change and an ADR; removing one is always allowed;
   - **k-anonymity** — a cell is exported only if `n ≥ k` (deployment-configurable, default
     to be set in P2 and recorded here) so that a single task cannot be inferred;
   - the **apparatus versions** present in the cell, so a consumer never mixes apparatus.
4. Export is **opt-in, per deployment, per export** — an operator action with an audit
   event; there is no background upload. Import of a shared meta-ledger is likewise an
   explicit action, and imported priors are **displayed as priors** ("other deployments,
   n=…"), never merged into the local ledger and **never consumed automatically by
   `route()`**: the routing rule reads only local rows.
5. Repository names and `labels` are stripped even from projections (`group_by_cell`
   key projections may roll up by fewer fields but never add non-cell fields).

## Consequences

- A tenant's code, commit messages, file paths, task ids and repository names cannot leave
  by this path; an auditor can verify that from the allowlist tuple and its test.
- Cold-start priors are informational only; the local ledger must earn every `deliver`
  route itself. This is slower and deliberate.
- Small deployments export little or nothing (k-anonymity), which is the intended trade.
- The shared meta-ledger format is a list of `CellStats` dicts with an export stamp; the
  consuming side must handle mixed apparatus versions by keeping them separate.

## Alternatives considered

- **Share evidence packs.** Rejected: packs contain file paths, subjects and redacted test
  output — customer data.
- **Share rows with hashed repo/task ids.** Rejected: hashed identifiers still allow
  linkage across exports and leak the existence and cadence of work.
- **Automatic federated routing (use shared priors in `route()`).** Rejected: a route is a
  local trust decision on local evidence; a prior from elsewhere is not evidence about
  this organisation's repositories or builders.
- **No cross-organisation learning at all.** Rejected only in the sense that the boundary
  is worth designing now; the export stays off until an operator turns it on.
