# ADR-0055 — Audited-bypass plan arm: a plan attested as drafted blind skips only the lookalike checks of the plan guard

**Status:** Proposed (DL-423)
**Date:** 2026-11-17
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. No existing set digest, row, arm,
brief, guard decision or reader result changes. The new source is opt-in; without an `audit`
field every plan set, brief and row is byte-identical to before, and the new stamps appear only
on rows of the new arm.
**Builds on:** ADR-0054 (the accepted-plan context arm), ADR-0050 (context sets) and ADR-0052
(stated requirements, whose drafter form the audit reuses). **Amends:** ADR-0054 items 1 and
4, for the `plan-audited` source only, and extends to that source every amendment ADR-0054
makes for the `plan` source: ADR-0050 items 3 and 4, ADR-0026 item 7 and ADR-0053 items 1
and 5 (see "Amended lines").

## Context

ADR-0054's `plan_guard` withholds a plan whole when its text resembles the change: it names a
held-out test or its path, copies eight tokens of the change's added lines in a row, repeats a
whole added line of code or states an asserted literal. Those checks read text, not history.
They cannot tell a plan that copied the answer from one that was drafted blind and happens to
read like it.

A blind drafter given a precise ticket often writes such a plan. A ticket that says "refuse
an empty name with `name required`" leads a careful drafter to a step that names the error
text, and a test that a team names after its behaviour leads the drafter to the same name. On
a guarded arm that plan is withheld, so the arm measures "plans that do not look like the
answer", not "plans written before the build". [hypothesis] The plans most likely to help are
the ones most likely to be withheld. Not measured: no run has compared delivered and withheld
plans. The test compares each group with its own matched `A0` controls, because the two groups
may differ in task difficulty. The measure is the difference, on an audited arm, between the
gain in clean rate over matched controls for rows stamped `ctx_plan_would_refuse` and the same
gain for delivered rows without the stamp, with its 95% interval. It is supported if the whole
interval is above zero, refuted if the whole interval is at or below zero, and inconclusive
otherwise. A small sample may give an inconclusive result.

Where the drafting itself was audited (a person or a model read the drafter's prompt, the
model it ran and its transcripts, and found no sight of the change), the text checks mostly
duplicate what the audit establishes, and they cost the measurement its strongest plans. They
are not wholly redundant: an audit of what the drafter was shown cannot show that the model
did not recall the change from its training. And the audit happens outside the product. The
product cannot replay it.

## Decision

1. **A separate source.** A new source, `plan-audited`, is registered beside `plan` in the
   source-to-kind table with kind `planned`, so every kind-based reader (the worker, the
   adapter, the parent-commit check) treats it as a plan. Its arm is
   `A0+library@ctx.plan-audited.<hex12>`. Nothing else changes about how `plan` is read.
2. **The attestation.** A `plan-audited` set is a `crb.ctxset.v3` document with one more
   top-level field, `audit`, required on that source and refused on every other
   (`ctxset_plan_audit`). It holds exactly five keys: `audited_by` (`human:<id>` or
   `model:<id>@<sha256>`), `audited` (a sorted, unique subset of `model`, `prompt` and
   `transcripts` that always holds `transcripts`), `record_sha256` (the full sha256 of the
   audit record, which is kept outside the product), `method` (one trimmed line of at most
   300 characters, with no line break of any kind and no code fence, of backticks or
   `~~~`) and `covers` (every entry's task id, sorted, and no other). Any other shape is
   refused `ctxset_plan_audit` before the set is stored.
3. **Inside the digest.** The audit is part of the hashed body, so a set's name moves when any
   audit field moves, and an audited set never shares a name with a guarded set of the same
   plans. A set without `audit` hashes exactly as before.
4. **Two kinds of reason.** The guard's reasons are split into two fixed tuples that together
   hold every plan reason, with none in both. Structural reasons say what the plan is:
   `plan_render`, `plan_length`, `plan_code_block` and `plan_no_gold`. Lookalike reasons say
   what its text resembles: `plan_test_name`, `plan_test_path`, `plan_test_span`,
   `plan_gold_span`, `plan_gold_line` and `plan_asserted_literal`.
5. **The bypass.** On a `ctx.plan-audited*` arm, compose runs the full `plan_guard`. A
   structural reason still withholds the plan whole, as on a guarded arm, and only the
   structural reasons are stamped `ctx_plan_refused`. Lookalike reasons alone do not withhold
   it: the plan is delivered, and the reasons are stamped. The bypass fails closed: only a
   reason named in the lookalike tuple is skipped, so a reason in neither tuple withholds the
   plan, and the split is checked when the module loads. Every other part of the blind brief
   is unchanged: the brief's own test files, target tests and test command stay withheld. The
   delivered plan itself may still name a held-out test, its path, its lines or an asserted
   literal: a row whose `ctx_plan_would_refuse` holds `plan_test_name`, `plan_test_path`,
   `plan_test_span` or `plan_asserted_literal` carries such text to the builder.
6. **Stamps.** Every row of the arm carries `ctx_plan_guard` = `audited_bypass`,
   `ctx_plan_audit` (the record's sha256) and `ctx_plan_auditor` (who attested). A delivered
   plan the full guard would have withheld also carries `ctx_plan_would_refuse`: its lookalike
   reasons, sorted. A clean plan carries no `ctx_plan_would_refuse`. No other row carries any
   of these four stamps. The audit's `method` is never stamped.
7. **The ledger checks them.** A `ctx.plan-audited*` row without the guard, audit or auditor
   stamp, with a guard value other than `audited_bypass`, a short audit digest or a malformed
   auditor is refused, a trailing line break included. So is a `ctx_plan_would_refuse` that
   is empty, unsorted, repeated, names a structural reason, or sits on a row that delivered no
   plan (beside `ctx_plan_refused`, or with `ctx_delivered` below 1), and a `ctx_plan_refused`
   that names a lookalike reason. Any of
   the four stamps on a guarded plan row, another kind's row, a control row or a row with no
   context set is refused.
8. **Never pooled.** The audited arm is measurement-only, like every plan arm. `ctx_compare`
   refuses to pair an audited arm with a guarded one either way round (`ctx_pair_blend`); an audited
   set pairs only with its own `A0` control.
9. **Readable, off by default.** No run uses the source unless an operator stores an audited
   set and names its arm. `crb ctxset lint` withholds an audited set's plans on structural
   reasons only and lists the lookalike ones as "audited bypass of …" (`would_refuse` in
   `--json`); `crb ctxset show` prints the line `audited    yes (record <hex12>)`.
   `GET /ctxsets/{name}` carries `audited` and `audit_record_sha256`, never the method;
   `POST /ctxsets` takes the `audit` field.

### Amended lines

For the `plan-audited` source only:

- **ADR-0054 item 1**, "`crb.ctxset.v3` holds the `plan` source and only it". It holds the
  `plan-audited` source too, with its `audit` field (item 2 here).
- **ADR-0054's own amendments** to ADR-0050 items 3 and 4, ADR-0026 item 7 and ADR-0053 items
  1 and 5, which name the `plan` source, apply to `plan-audited` as well: its plan
  entries meet `plan_guard` instead of `refuse_novel`, are admitted by the parent-commit check
  without the mechanical stamp, may name a token the commit introduced and may carry gaps.
- **ADR-0054 item 4**, "`plan_guard` withholds a plan whole" on any of its reasons. On an
  audited arm it withholds a plan whole on a structural reason only; a lookalike reason is
  stamped on the row (`ctx_plan_would_refuse`) and the plan is delivered.

The `plan` source and its guard are unchanged. This is a new arm with its own attestation and
stamps, not a relaxed gate.

## Consequences

- A team's blind-drafted plans can be measured whole, the precise ones included, against the
  same builder without them, with n and Wilson intervals, by exact test.
- The attestation is unverified by the product. crb checks its shape and records its digest
  and author; it does not read the audit record, replay the drafting or check the auditor
  against any account [gap]. `ctx_plan_auditor` reads "the operator says this auditor
  attested blind drafting", not a verified audit.
- An attested set is trusted. A false attestation leaks the answer to the builder on exactly
  the plans the guard would have caught, and the rows still look valid. The stamps bound the
  damage: every such row names the lookalike reasons it skipped and the record that vouched
  for it, so a reader can count, split or drop them.
- Rows of the audited arm are never comparable with `ctx.plan` rows. They answer a different
  question (all blind plans, against plans that do not look like the answer), so they never
  pool or pair. No reader splits audited rows by `ctx_plan_would_refuse` yet [gap].
- A plan with a code block cannot reach the guard on either arm: a fenced line breaks the
  plan's shape first and is refused `plan_render`. `plan_code_block` is structural and kept,
  so a future renderer that allows a block cannot open it to the bypass.
- No page shows `audited`, `audit_record_sha256` or the audited stamps yet [gap].
- An audit of the drafter's prompt and transcripts cannot detect a model recalling a public
  commit it was trained on. On a public repository an audited plan that trips a lookalike
  reason may still carry the answer [gap]; a reader should treat rows whose
  `ctx_plan_would_refuse` holds `plan_asserted_literal`, `plan_test_span` or `plan_gold_line`
  as suspect.
- The text limits that still apply to a delivered plan are weak bounds: up to 8000 characters
  over 80 trimmed lines, so a falsely attested plan can carry held-out assertion lines word
  for word, losing only their indentation.

## Alternatives considered

- **A run flag that switches the guard off.** Rejected: the flag would live on the run, not the
  set, so the same set's name would mean two things, and nothing would record why the guard
  was off. The attestation lives in the set and its digest.
- **Relax the text checks for every plan.** Rejected: it would re-open ADR-0054's leak on
  every plan set, attested or not, and change the meaning of existing rows.
- **Let the audit bypass `plan_code_block` too.** Rejected: a code block is what a plan is,
  not what it resembles; an audit of the drafting says nothing about whether the text hands
  over code.
- **Bump the apparatus to 2.7.** Rejected: no existing row, digest or verdict changes meaning.
  The new rows are told apart by their arm and stamps, and never pool with any other.
