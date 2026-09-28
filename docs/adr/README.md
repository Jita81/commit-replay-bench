# Architecture Decision Records

An ADR records one decision that shapes the product, the context that forced it, and the
consequences we accept. ADRs are **append-only**: a decision is superseded by a new ADR,
never edited into something else. A change to the meaning of a verdict (belt semantics,
size table, the global class vocabulary, routing rule) — an organisation's class-set version is a
stamp and a read axis instead (ADR-0026) — **must** bump `crb.core.version.APPARATUS_VERSION`
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
| [0019](0019-qualification-is-posture-relative.md) | Qualification is posture-relative: a task is proven in the posture that grades it (`task_qualifications`, the `qualify` run kind, $0), its dependencies are provisioned per task outside the test container (`crb.core.deps`, `crb.provision`), and the model is blamed only with a witness from that posture (`MisattributionViolation`); apparatus 2.3; amends ADR-0005 and ADR-0012 | Accepted | 2026-09-25 |
| [0020](0020-a-bug-is-closed-by-prevention.md) | A bug is closed by prevention: one per-repository switch (default off), the strongest lever a class admits, measured on the first attempts that saw it and kept, retired or escalated by `crb.prevention.rule.v1`; the loop changes how a change is made, never how it is judged; no apparatus impact | Accepted | 2026-09-25 |
| [0021](0021-factory-review-before-delivery.md) | The factory reviews before it delivers: only an `accept` verdict reaches delivery (`deliver()` refuses any other), a rework re-delivers nothing, and an earlier run's open pull request is closed with a comment naming the verdict when a later review does not accept the item; supersedes in part ADR-0003's 2026-09-16 and 2026-09-19 amendments; no apparatus impact | Proposed | 2026-09-25 |
| [0022](0022-intake-approval-by-default.md) | An operator approves a ticket before it is registered (`CRB_INTAKE__REQUIRE_APPROVAL=true` by default; the evented Register act binds to the revision read; an explicit author allowlist may bypass it); ticket text is fenced in the PR body and the branch is `[a-z0-9-]`; one pass per repository under a lease row; 429 honours `Retry-After` within a cap; the tracker credential never leaves its origin; supersedes in part ADR-0017; no apparatus impact | Proposed | 2026-09-25 |
| [0023](0023-production-refuses-the-unsealed-posture.md) | Production refuses the unsealed posture (the host builder, the local test executor) unless `CRB_ALLOW_UNSEALED_PROD=1` (amended 2026-09-27: in prod the override names the admin who set it and why, `CRB_ALLOW_UNSEALED_PROD_BY` / `_REASON`, checked at every start and written as a `posture.unsealed_override` audit event; the name is stamped beside the override); the override is shown on `/health`, `/settings` and the Posture page and stamped into every run's apparatus; the builder defaults to `docker` in prod; factory builds are not sealed, so prod refuses factory runs unless the override is set; no apparatus bump (numbers 0018–0022 are held by parallel work and may land first) | Proposed | 2026-09-25 |
| [0024](0024-working-by-construction.md) | "Clean" means working, by construction: the repository's own formatter before grading, the finish gate (the repository's checks as the brief's checklist, verified, bounded repair), belt 6 `api_stable` (failure kind `api`, recorded as a hashed row label), and ONE per-repository switchboard `RepoConfig.checks` the prevention loop writes — every mechanism OFF by default and recorded on the row; the format step and belt 6 make a row's checks ARM, a hashed stamp and a read filter that never pools two arms in a cell (no apparatus bump); amends ADR-0011's detectors after the runner-command audit | Accepted | 2026-09-25 |
| [0026](0026-the-context-standard.md) | The context standard: a pre-registered context arm (`labels.context_arm`) and class-set version (`labels.taxonomy`) on every 2.4 row, never pooled; registered readings in a seeded commit order read by the look rule (20/20, 29/30, 38/40) along a hierarchy that stops at the first arm that does not deliver, one error budget per cell; the leak guard; the entry gate and calibration builds; class sets held out by commit; the library measured before it reaches a brief; ISO/IEC 25010 named, never claimed; amends ADR-0025 before it is committed; supersedes in part ADR-0024 item 6 (loop on and off no longer pool; the export sends `S3` rows only), ADR-0003's 2026-09-16 amendment (build and withhold) and ADR-0018 as drafted (the override narrowed to a missing sign-off); no apparatus impact of its own (it rides 2.4) | Proposed | 2026-09-27 |
| [0028](0028-the-moments-flow-needs-are-recorded.md) | The moments the flow reading needs and could not derive are recorded once, as system events, when the product observes them: a cell first routing `deliver` (after every finished run, per apparatus × posture class × checks arm; cells already at deliver when recording began are counted, never timed), the install (observed only on a database that held nothing, otherwise unknown and never dated) and the first green `/health`; observability only, never a verdict (numbers 0025–0027 are held by parallel work) | Proposed | 2026-09-26 |
| [0029](0029-the-audit-trail-is-hash-chained.md) | The audit trail is hash-chained: every `events` row carries `prev_hash` / `row_hash` (`crb.core.event_chain`), set in its writer's own flush under the events lock so no writer can skip or choose them, with a unique `prev_hash` so the chain cannot fork; revision 0013 chains the existing rows; `/ledger/verify` and `crb ledger verify --store` walk it and serve both chains' heads, which every worker start also logs, to be recorded outside the store; the append-only probe proves every table in the trigger's own words; the HMAC tail anchor is deferred; no apparatus impact (numbers 0029–0040 are held by parallel work) | Proposed | 2026-09-27 |

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
