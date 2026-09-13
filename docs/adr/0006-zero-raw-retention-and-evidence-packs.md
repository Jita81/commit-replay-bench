# ADR-0006 — Zero raw retention by default; evidence packs

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** none; `EVIDENCE_SCHEMA = "crb.evidence.v1"`

## Context

Two requirements pull against each other. An auditor must be able to reconstruct every
production decision from evidence (validation standard C8 / G0; "no pack ⇒ no Q1"). A
data-protection impact assessment in an NHS organisation wants the product to hold as
little of the customer's source code, and as little model output, as possible — and none
of it by accident. Upstream, replay sweeps already held the invariant that raw diffs are
not stored; transcripts were sometimes retained inline.

## Decision

1. **The evidence pack is the unit of audit.** `crb.core.evidence.EvidencePack` holds:
   the `TaskSpec`; the `GradeResult` (belts, DQ/error, `new_failures`, `tamper_files`,
   `changed_files`, **redacted and capped** target/belt run tails, `DiffStats`); the
   `ApparatusStamp`; the `BuilderRef`; run/trial/actor/created; free-form `notes`.
   `pack_hash` is the SHA-256 of the canonical JSON of `body()`; `verify_pack()` recomputes
   it. The ledger row carries `evidence_pack_hash`; a `clean` row without one cannot be
   written (ADR-0001).
2. **Diffs are stored as hash + statistics**, never as text:
   `Workspace.diff_stats()` → `DiffStats(files, additions, deletions, diff_sha256)`. The
   diff hash lets an auditor confirm a reproduced patch is the one that was graded without
   the product retaining the patch.
3. **Test output is redacted and capped** before it reaches a pack: `grade()` passes every
   `TestRun.tail` through `crb.core.redact.redact_and_cap` (default cap 8,000 characters,
   keeping the tail); `error` strings are capped at 2,000. The redaction patterns cover
   bearer/basic auth headers, well-known key prefixes (`sk-`, `gh*_`, `xox*-`, `AKIA`,
   `AIza`), JWTs, `*secret|token|password|api_key*=value` pairs, credentials in URLs, and
   private-key blocks.
4. **Builder transcripts are opt-in.** `BuilderRef.transcript_ref` is a pointer to raw model
   output stored elsewhere under a retention window — never inline in a pack or a row.
   Default: not stored. When enabled, the store (P4) records the window and purges on
   expiry; the pack keeps only the reference.
5. **The executor strips the environment** (ADR-0005) so secrets are unlikely to appear in
   output at all; redaction is defence in depth and runs on every stored string, including
   JSON logs (`crb.observability.logging`).
6. **Legacy imports** keep the same policy: the census import stores belts, sizes, classes
   and the fields the rows had; it does not import diffs or transcripts.

## Consequences

- An auditor gets everything needed to reconstruct *why* a verdict was reached — task,
  belts, what failed, how big the change was, who built it with what, under which
  apparatus — without the product becoming a second copy of the customer's code.
- A pack cannot be used to *re-run* the patch; reproduction requires the builder to be run
  again (and the diff hash then confirms identity). That is a deliberate trade.
- The cap can truncate a very long failure tail; the *head* of the output is lost and the
  tail kept, because test runners print the summary last.
- Redaction is pattern-based and conservative; it cannot recognise every secret shape. The
  operator guide instructs that repositories under measurement must not hold live secrets
  in test fixtures, and the executor denies the environment regardless.
- Enabling transcript retention is an operator decision with a recorded window; the
  Settings screen (P5) shows it, and the DPIA support document (P7) describes it.

## Alternatives considered

- **Store full diffs for convenience.** Rejected: the product would retain the customer's
  source changes; the hash + stats meet the audit need.
- **Store transcripts by default with a long window.** Rejected: model output can contain
  code, secrets echoed from the repository, and personal data; opt-in with a window is the
  DPIA-friendly default.
- **No cap on test output.** Rejected: unbounded packs; a runaway test could write
  gigabytes into the evidence store.
- **Redact at display time only.** Rejected: the stored artefact is what leaks in a backup
  or an export.
