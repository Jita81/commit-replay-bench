# Architecture Decision Records

An ADR records one decision that shapes the product, the context that forced it, and the
consequences we accept. ADRs are **append-only**: a decision is superseded by a new ADR,
never edited into something else. A change to the meaning of a verdict (belt semantics,
size table, class taxonomy, routing rule) **must** bump `crb.core.version.APPARATUS_VERSION`
and be recorded here.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-four-belts-and-false-q1-at-write.md) | Four belts and false-Q1 = 0 enforced at write (amended 2026-09-13: belt 1 covers test infrastructure) | Accepted | 2026-09-13 |
| [0002](0002-append-only-hash-chained-ledger.md) | Append-only, hash-chained ledger | Accepted | 2026-09-13 |
| [0003](0003-one-routing-rule.md) | One routing rule (reconciles the published rule with the SPC rule) | Accepted | 2026-09-13 |
| [0004](0004-builder-registry-sighted-and-blind.md) | Builder registry; sighted and blind modes | Accepted | 2026-09-13 |
| [0005](0005-fail-closed-docker-sandbox.md) | Fail-closed Docker sandbox for every test run | Accepted | 2026-09-13 |
| [0006](0006-zero-raw-retention-and-evidence-packs.md) | Zero raw retention by default; evidence packs | Accepted | 2026-09-13 |
| [0007](0007-abstract-cell-export-only.md) | Cross-organisation learning: abstract cell export only | Accepted | 2026-09-13 |
| [0008](0008-stdlib-core-and-downward-layers.md) | Standard-library core and downward-only layers | Accepted | 2026-09-13 |
| [0009](0009-text-level-mutators.md) | Text-level mutators for the non-Python languages (`uncompilable` excluded; family stamped) | Accepted | 2026-09-13 |
| [0010](0010-polyglot-negative-controls.md) | Polyglot negative controls (Go + JavaScript text transforms; env_poison escape = belt-1 gap) | Accepted | 2026-09-14 |
| [0011](0011-repo-lint-belt.md) | Belt 5: the repository's own formatter/linter (`repo_lint_clean`; apparatus 2.2, belt set `v5`, failure kind `lint`; amends ADR-0001 and ADR-0002 rule 2) | Accepted | 2026-09-14 |
| [0012](0012-builder-in-a-sealed-container.md) | The builder runs in a sealed container: an exported checkout that cannot contain the gold commit, a hardened container, one allowlisting egress sidecar (`CRB_BUILDER__EXECUTOR=docker`; amends ADR-0005's scope) | Accepted | 2026-09-14 |
| [0013](0013-external-review-is-advisory-and-recorded.md) | An external reviewer's verdict (CodeRabbit on PRs; later a factory `Reviewer`) is recorded and advisory to humans — never an input to a verdict, a route or a sign-off | Proposed | 2026-09-15 |
| [0014](0014-github-app-is-the-connection.md) | The GitHub App is the connection: org-level install on selected repositories, installation tokens minted per use and never stored, write per installation; personal access tokens are not | Accepted | 2026-09-17 |
| [0015](0015-signoffs-expire-with-the-apparatus.md) | A sign-off expires with the apparatus: `covers_apparatus` at read, served `stale` / `active: false`, never edited; no apparatus bump (a read rule, not a moved instrument) | Accepted | 2026-09-17 |
| [0016](0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md) | The two-person rule (`same_actor`, `signoff-policy.v3`) is a write-time policy clause, not an apparatus move: the seam is `policy_version` / `schema` on every record; no apparatus bump (ADR-0015 §4 argument); pre-v3 records stay valid and identifiable (F53) | Accepted | 2026-09-21 |
| [0017](0017-the-ticket-is-the-backlog-item.md) | The ticket is the backlog item; the column is the consent gate: one watched column per repository (listener default OFF, operator-switched), six tracker verbs behind one protocol, an edit is an evolution and never an overwrite, and the gap feedback reaches the ticket before any spend; no apparatus impact (intake decides which items exist, never how one is graded) | Accepted | 2026-09-22 |
| [0023](0023-production-refuses-the-unsealed-posture.md) | Production refuses the unsealed posture (the host builder, the local test executor) unless `CRB_ALLOW_UNSEALED_PROD=1`; the override is shown on `/health`, `/settings` and the Posture page and stamped into every run's apparatus; the builder defaults to `docker` in prod; no apparatus bump (numbers 0018–0022 are held by parallel work and may land first) | Proposed | 2026-09-25 |

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
