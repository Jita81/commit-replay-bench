# ADR-0050 — Context-set arms: a governed paired measurement of supplied context

**Status:** Proposed (DL-418)
**Date:** 2026-11-14
**Apparatus impact:** none. APPARATUS_VERSION stays 2.5. The arm grammar is unchanged, every new
stamp is provenance (added to PROVENANCE_LABELS, never to the arm), and no existing row, arm or
reader result changes.
(Note, 2026-11-15: that was true when this change merged. ADR-0051 moves the stamp to 2.6, so a
context-set run is now stamped 2.6, and a context-set pair is read within one apparatus.)

## Context

The question "does supplying context to the builder change the outcome?" has not been asked as a
governed measurement. ADR-0026 records an upstream "signed facts" lever whose apparent gain was
answer leakage: facts written without the diff scored exactly the message-only arm. The
instrument already holds most of an honest answer:

- an arm grammar with a `+library@NAME` modifier (ADR-0026 item 1);
- a leak guard that refuses a brief line naming a token the commit introduced (item 7);
- a retrospective admission rule for library entries (item 10);
- an exact McNemar pair reader that fails closed on pending commits (NEW-1).

Four gaps stop a measurement today [gap]:

1. No replay caller passes library entries or `pool_began`, so no entry reaches a replay brief.
2. The leak guard computes its novel-token set only when a brief carries playbook lines.
3. Nothing separates context written with hindsight of the answer from context a production
   system could have had. Stamping hindsight text as mechanical would be a false stamp.
4. A time rule cannot admit a drafted entry: a draft made today post-dates every past commit.
   ADR-0026 says a provenance date is not a knowledge date.

A measurement must also separate "relevant text helped" from "more text helped", which needs a
placebo of equal length and irrelevant content, kept apart from the treatment.

## Decision

Add opt-in context-set arms. A run without `context_set` behaves exactly as before.

1. **Context set.** One JSON document, schema `crb.ctxset.v1`, with exactly one entry per
   task. Its digest is the sha256 of its canonical JSON. Its name is
   `ctx.<source>.<digest[:12]>`, where source is `oracle`, `oracle-placebo`, `mech` or
   `mech-placebo`. A set is immutable: a changed set is a new arm. It is stored by content
   address through an operator route, verified when stored and again when a run loads it
   (`crb.core.ctxset`). A run naming a set replays exactly the set's tasks.
2. **Arm ids (amends ADR-0026 item 1).** A library NAME starting with `ctx.` is reserved for
   context sets, must match `^ctx\.(oracle|oracle-placebo|mech|mech-placebo)\.[0-9a-f]{12}$`,
   and may only follow base `A0`, without `+facts` and `+L`. A malformed name in the reserved
   namespace (`ctx.` followed by anything else) is outside the arm grammar, so `parse_arm`
   refuses it rather than reading it as an ordinary library arm.
   `hindsight_arm` (name starts `ctx.oracle`) and `measurement_only` (any ctx name) are derived
   from the arm id alone (`crb.core.context_arm`).
3. **Leak guard (amends ADR-0026 item 7).** The novel-token set is computed whenever a brief
   carries playbook lines or a context-set entry, and every entry passes the same refusal as a
   playbook line. The guard is never relaxed. Its limit is recorded here: it removes only
   tokens absent from the whole parent tree, so an entry can still restate a fix in vocabulary
   the parent already has.
4. **Admission (amends ADR-0026 items 1 and 10).**
   - A hindsight set is exempt from the retrospective time rule only, never from the leak guard
     or the bare-fact refusal. The rule that test values are not entries is waived for
     hindsight sets only, which is why they are measurement-only.
   - A `ctx.mech` set is admitted by knowledge boundary under item 1's `+facts@<drafter>`
     condition: each entry is mechanical and records the task's parent commit as its
     `source_rev`, and the set names its pinned drafter. `admit_at_parent` in
     `crb.builders.brief` enforces it.
   - A placebo follows the rule of the set it is matched to.
   - A refused entry is counted and the row is still written under its arm (intention to
     treat).
5. **Provenance stamps.** A ctx row carries `ctx_set`, `ctx_source`, `ctx_gap`,
   `ctx_gap_rule`, `ctx_delivered` and `ctx_chars`, plus `ctx_drafter` on a mechanical arm and
   `ctx_ceiling` = `1` on a hindsight arm. A control row keeps plain `A0` and carries
   `ctx_set`, `ctx_source` = `control`, `ctx_gap` and `ctx_gap_rule`. The stamps are set before
   any step that can fail, so error rows carry them. The ledger refuses a row that lacks them or
   whose digest disagrees with its arm (`GradeRow.assert_own_classification`).
6. **Gap label.** Rule `anchor.v1`: `ctx_gap` is `1` when the ticket names no identifier found
   in the parent tree. It reads the ticket and the parent tree only, is computed once per task
   before the run, and is descriptive: never a pooling, routing or primary-test key.
7. **Placebo.** Its own set and its own arm, over the same tasks, within max(16, 2%) characters
   of the treatment per task, sharing no identifier token with the treatment entry beyond a
   fixed stopword list, naming its treatment by digest. It is never pooled with the treatment.
8. **Paired comparison (`crb.core.ctx_compare`).** First attempts of two named runs, paired by
   task: discordant counts, the exact two-sided McNemar p, per-arm k/n with Wilson intervals,
   delivered and refused entries, delivered characters, a dose-imbalance flag and per-gap
   counts. A task pending on either side is read clean under the control and a miss under the
   treatment, and is named. The reader refuses any blend of apparatus, posture class, builder
   executor, checks arm, builder, model, taxonomy or gap rule, and any unsealed row.
9. **Never certifies (new rule).** No reading accepts a measurement-only arm. The value
   scorecard, capability, routing and re-measure readers drop its rows, and an explicit arm
   selector refuses it. The re-measure plan never prices a top-up from its rows, a run's
   escalation yield and calibrated caps never read them, and the north star drops review
   verdicts joined to them. Its spend is measurement spend and stays outside the north star. A
   hindsight result is shown as a reference for one hindsight brief that may restate the
   answer, never as a builder capability.
10. **Runs.** A context-set run is kind `blind`, learning off, needs a sealed deployment, and
    is refused in a reserved reading; the reserved parameter whitelist is unchanged.

## Consequences

**Easier.**

- A context source can be tried against a matched placebo on the same commits, with n,
  intervals and an exact test.
- A mechanical source and a hindsight brief share one mechanism. The hindsight result is a
  reference for that one brief on those commits, not a bound on what any source could add: a
  hindsight brief can omit useful information, and another source can beat it.

**Harder.**

- Context-set runs and plain `A0` runs on one repository under one campaign share the `A0`
  campaign key and run one at a time. This is intended.
- Every commit a context-set run replays counts as seen for later reserved readings.
- A heavily refused set reads as diluted, not absent.
- A mechanical set's drafting is attested by its record until crb drafts sets itself.

**Must never.**

- Relax the leak guard, the bare-fact refusal, or the admission rule for a non-hindsight set.
- Mark hindsight text as mechanical.
- Pool a placebo with its treatment.
- Let a measurement-only arm certify, license, route or enter the value scorecard.
- Word a ceiling as a builder capability or as context free of the answer.
- Change an existing row or the meaning of an existing arm.

**Open.**

- Whether a mechanical source that beats its placebo should become a candidate context standard
  for a cell [hypothesis]. That needs its own reading design and ADR.
- Whether `anchor.v1` tracks real missing context [hypothesis].

## Alternatives considered

- **A new arm base or modifier for context.** Rejected: it changes the grammar every reader
  parses; the library modifier already carries a name.
- **Composing context briefs with the retrospective rule off.** Rejected: it also drops the
  bare-fact refusal and admits hindsight text unlabelled.
- **Stamping hindsight entries mechanical with an early produced-at.** Rejected: a false stamp.
- **Admitting mechanical entries by wall-clock time.** Rejected: a draft always post-dates the
  commit; the knowledge boundary is the parent commit.
- **Exempting hindsight lines from the leak guard.** Rejected: it would add tokens the commit
  introduced to a ceiling that can already restate the fix.
- **An apparatus bump to 2.6.** Rejected: no existing row or reader result changes.
- **Running context sets inside a reserved reading.** Rejected: it widens the reserved
  whitelist; the first measurement does not certify.
- **Adding a refusal clause to the routing rule.** Rejected: a routing-rule change is an
  apparatus question; every caller refuses the arm before routing instead.
