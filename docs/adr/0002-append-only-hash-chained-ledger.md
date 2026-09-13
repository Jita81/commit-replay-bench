# ADR-0002 — Append-only, hash-chained ledger

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** none (storage, not verdict semantics)

## Context

An NHS deployment must be able to show an auditor that no verdict was altered, removed or
reordered after the fact (the validation standard's G0.4 "ledger immutability": attempted
mutations — deleting failures, altering grades, post-hoc rerouting, editing costs, removing
disqualifications — must all be detectable and attributable). Upstream, the benchmark
ledger was JSONL "append-only by convention", with a CWD-dependent path and three disjoint
stores, and its false-Q1 check ran at read time. Convention is not evidence.

## Decision

1. The unit of record is `crb.core.ledger.GradeRow`: one graded trial reduced to what
   statistics and audit need (belts, `clean`, DQ/error, cell fields, cost/latency, oracle
   strength, `evidence_pack_hash`, `apparatus_version`, `belt_set`, `provenance`, `actor`,
   `created`). Schema id `crb.grade.v2`.
2. Every row is **chained**: `prev_hash` is the previous row's `row_hash`; `row_hash` is the
   SHA-256 of the row's canonical JSON body (`GradeRow.compute_hash` over `body()`, which is
   every field except `row_hash`, with `labels` copied). The first row's `prev_hash` is
   `GENESIS_HASH` (64 zeros).
3. `JsonlLedger.append` is the only write path in the reference implementation: it calls
   `assert_invariants()` (ADR-0001), computes the chain from the file's last line, writes
   one line, `flush()`es and `fsync()`s. There is no update or delete API.
4. `verify_chain(rows)` walks a ledger and raises `LedgerIntegrityError` on the first
   `prev_hash` or `row_hash` mismatch, returning the row count otherwise. `crb ledger verify`
   exposes it; `/health` runs it (P4).
5. The database store (P4) holds the same rows with the same chain; `grades`, `events` and
   `signoffs` tables have DB triggers that forbid `UPDATE` and `DELETE`. Revocation of a
   sign-off is a **new row** referencing the revoked one.
6. JSONL is the portable interchange: the store imports the census `grades.jsonl` (1,071
   rows, stamped `provenance="imported:…"`, `belt_set="v3-legacy"` where belt 4 is absent)
   and exports any subset with its chain intact.
7. Statistics are computed only from ledger rows (`cell_stats`, `all_cell_stats`), and
   `cell_stats.false_q1` re-derives `clean == all recorded belts True` at read time.

## Consequences

- Any edit to a stored row is detectable by anyone with the file and `crb ledger verify`;
  the chain, not a database permission, is the evidence.
- Corrections are appended, never applied in place: a mis-graded trial gets a new row
  (with `provenance` explaining why) and the old row stays visible.
- The ledger grows monotonically; export/rotation must preserve the chain (export whole
  prefixes, record the last `row_hash` at the cut).
- Rows must be written in a single serialised order per ledger file; concurrent writers
  use the database store, whose sequence is the transaction order.
- Importing legacy rows keeps their original apparatus visible; they are never silently
  upgraded to `v4`.

## Alternatives considered

- **Database permissions only (no chain).** Rejected: a DBA or a backup restore can alter
  rows without a trace; an auditor cannot verify from an export.
- **Signed rows (per-row signatures with a key).** Deferred: signing adds key management
  that an air-gapped deployment may not want; the chain plus an operator-held final hash
  (published out of band) gives tamper-evidence now. Signing can be layered later without
  changing the row schema.
- **Mutable rows with an audit table.** Rejected: two sources of truth; the audit table is
  itself mutable.
- **Merkle tree instead of a linear chain.** Deferred: a linear chain matches the
  append-only write pattern and the JSONL format; inclusion proofs are not a current
  requirement.
