# Architecture Decision Records

An ADR records one decision that shapes the product, the context that forced it, and the
consequences we accept. ADRs are **append-only**: a decision is superseded by a new ADR,
never edited into something else. A change to the meaning of a verdict (belt semantics,
size table, class taxonomy, routing rule) **must** bump `crb.core.version.APPARATUS_VERSION`
and be recorded here.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-four-belts-and-false-q1-at-write.md) | Four belts and false-Q1 = 0 enforced at write | Accepted | 2026-09-13 |
| [0002](0002-append-only-hash-chained-ledger.md) | Append-only, hash-chained ledger | Accepted | 2026-09-13 |
| [0003](0003-one-routing-rule.md) | One routing rule (reconciles the published rule with the SPC rule) | Accepted | 2026-09-13 |
| [0004](0004-builder-registry-sighted-and-blind.md) | Builder registry; sighted and blind modes | Accepted | 2026-09-13 |
| [0005](0005-fail-closed-docker-sandbox.md) | Fail-closed Docker sandbox for every test run | Accepted | 2026-09-13 |
| [0006](0006-zero-raw-retention-and-evidence-packs.md) | Zero raw retention by default; evidence packs | Accepted | 2026-09-13 |
| [0007](0007-abstract-cell-export-only.md) | Cross-organisation learning: abstract cell export only | Accepted | 2026-09-13 |
| [0008](0008-stdlib-core-and-downward-layers.md) | Standard-library core and downward-only layers | Accepted | 2026-09-13 |
| [0009](0009-text-level-mutators.md) | Text-level mutators for the non-Python languages (`uncompilable` excluded; family stamped) | Accepted | 2026-09-13 |

## Format

```markdown
# ADR-NNNN — <title>

**Status:** Proposed | Accepted | Superseded by ADR-MMMM
**Date:** YYYY-MM-DD
**Apparatus impact:** none | bumps APPARATUS_VERSION to X.Y

## Context
What forces this decision: the problem, the constraints, the evidence (tagged
[measured] / [hypothesis] / [aspiration] per docs/EVIDENCE-AND-CLAIMS.md).

## Decision
What we do, stated so that it can be checked against the code. Name the module,
class or function that enforces it.

## Consequences
What becomes easier, what becomes harder, what we now must never do.

## Alternatives considered
Each rejected option and the reason it lost.
```

Numbering is sequential and never reused. File name: `NNNN-kebab-case-title.md`.
To add an ADR, see [CONTRIBUTING → How to add an ADR](../CONTRIBUTING.md#how-to-add-an-adr).
