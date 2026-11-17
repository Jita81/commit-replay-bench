# ADR-0054 — Accepted-plan context arm: pass rate when the builder is given a plan accepted before the build

**Status:** Proposed (DL-422)
**Date:** 2026-11-17
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. No existing set digest, row, arm,
brief, guard decision or reader result changes. The new schema and source are opt-in, and the
new stamps appear only on rows of the new arm.
**Builds on:** ADR-0050 (context sets), ADR-0026 (the leak guard and the library's rules) and
ADR-0053 (open requirement gaps). **Amends:** ADR-0050 items 3 and 4 and ADR-0026 item 7, for
the `plan` source only, and ADR-0053 items 1 and 5 (see "Amended lines").

## Context

The context-set arms so far ask what a builder does with facts: a hindsight set written from
the answer (`oracle`), a set drafted mechanically at the parent (`mech`) and a set of stated
requirements (`req`). In practice a team often writes a plan before anyone builds: which files
change, in what order, which decisions are already made and what the tests should cover. A
person who asked for the change then accepts it or not.

Nothing measures whether such a plan helps. A plan cannot ride an existing arm:

- it is not a hindsight brief, because it was written without sight of the change;
- it is not mechanical, because a person or a model wrote it;
- it is not a set of stated items, because its job is to name steps and files, and it may
  name what the build will add (a new function, a new error text). `refuse_novel` would
  refuse every such line, and `req_guard`'s declared-disclosure items do not fit a plan.

A plan also carries a leak risk of its own. A plan drafted with sight of the change or its
tests would hand the builder the answer under another name.

## Decision

1. **The record.** A new schema, `crb.ctxset.v3`, holds the `plan` source and only it. There
   is no `plan-placebo` yet. The set names its `drafter` (`human:<id>` or
   `model:<id>@<sha256>`), what the drafter `saw` (a sorted subset of `ticket` and `tree`
   that always includes `ticket`) and who `accepted_by` the plans (`human:<id>` or `none`).
   Each entry carries the task's parent commit as `source_rev` and a structured `plan` of
   five sections of one-line strings: `summary`, `files`, `steps`, `decisions` and `tests`.
   `summary` and `steps` are never empty. Entries may carry ADR-0053 `gaps`.
2. **Rendered by code.** The text the builder reads is rendered from the plan by
   `crb.core.plan.render`: one fixed header, then each section as plain bullets (steps
   numbered), with no indentation. The header and headings ("Implementation plan for this
   change:", "Decisions:") claim nothing the set may not hold: whether the plan was accepted
   and what its drafter saw are row stamps, never words the builder reads, so every plan set's
   builder reads the same frame. A stored `text` must equal that rendering
   (`ctxset_plan_render`) and sits outside the digest, so the digest pins the plan, not its
   layout. Fixed limits hold per entry: 8000 characters, 80 lines, 600 characters a line, 40
   files and 24 decisions (`ctxset_plan_length`). They are new limits for a new schema; the
   stated-set limits of ADR-0052 are unchanged.
3. **Refused at store time.** `ctxset_plan_saw` (the drafter saw anything but the ticket and
   the parent tree, or not the ticket), `ctxset_plan_accepted`, `ctxset_plan_shape` (a line
   with a fence or a newline, an empty `summary` or `steps`), `ctxset_plan_render` and
   `ctxset_plan_length`. A v1 or v2 body that names the `plan` source is refused as before.
4. **The guard: withheld whole.** At compose time, harness-side, each plan meets
   `plan_guard` against the gold view. It is withheld WHOLE, never trimmed, when:
   - its text is not its rendering (`plan_render`) or it breaks a limit (`plan_length`);
   - its own lines hold a code block, a held-out test's name or a held-out test's path or
     stem (`plan_code_block`, `plan_test_name`, `plan_test_path`: the checks `req_guard`
     makes, now one shared function, pinned equal to the old inline checks). They read the
     plan's lines, never the renderer's header and headings, whose words a held-out test may
     share;
   - its lines, read together, share an eight-token run with the change's added test lines
     (`plan_test_span`) or added source lines (`plan_gold_span`);
   - its lines, read together, hold a whole added source or test line of code, or that
     line's body past one leading word, whitespace and case aside: at least 10 characters
     with a bracket, `=`, `<` or `>`, which neither the request nor the parent holds
     (`plan_gold_line`). A one-line fix has fewer than eight tokens, so the span rules alone
     cannot see its copy;
   - its lines, read together, repeat four words in a row of a string literal an added test
     may assert, which neither the request nor the parent holds (`plan_asserted_literal`);
   - there is no gold view (`plan_no_gold`: it fails closed).
   A withheld plan is counted as refused, and its reasons are stamped on the row.
5. **Novel tokens are counted, not refused.** A plan written before the build may name what
   the build will add. The number of such tokens a delivered plan names is stamped as
   `ctx_plan_novel`, so a reader can split rows on it. Every fact and learned line on the same
   brief still meets `refuse_novel`.
6. **Admitted at the parent.** A plan entry is not mechanical. It is admitted only when its
   `source_rev` is the task's parent commit (`admit_at_parent` with
   `require_mechanical=False`), and the worker refuses a set whose entry was drafted
   elsewhere at claim, before anything is built.
7. **Its own block in the brief.** A kept plan reaches the brief's own plan block, after the
   known facts and before any repair note, never `spec_facts`. Several kept plans are joined
   by a blank line. A brief with no plan is byte-for-byte what it was.
8. **Stamps.** A plan row carries `ctx_plan_drafter`, `ctx_plan_saw` and `ctx_plan_accepted`,
   plus `ctx_plan_refused` (sorted guard reasons) when a plan was withheld and
   `ctx_plan_novel` when one was kept. It carries no `ctx_drafter` and no `ctx_ceiling`. The
   ledger refuses a plan row that lacks a stamp or whose stamps disagree with these rules, and
   refuses a plan stamp on any other row. `ctx_plan_novel` counts over the plan's own lines.
   `drafter`, `saw` and `accepted_by` are what the operator who stored the set says, as with
   a stated set's `drafter`: the server checks their form, not that the named person drafted
   or accepted the plan.
9. **Measurement-only, never pooled.** The arm `A0+library@ctx.plan.<hex12>` is
   measurement-only like every context-set arm. It pairs with its own plain `A0` control. The
   paired reader refuses to pair it with an entries run of another kind (`ctx_pair_blend`),
   and it is not a ceiling. `crb ctxset lint` runs `plan_guard` offline.
10. **Off by default.** A run without a `plan` set is unchanged. Golden pins hold the briefs
    and digests of the existing arms.

### Amended lines

For the `plan` source only:

- **ADR-0050 item 3**, "every entry passes the same refusal as a playbook line". A plan entry
  meets `plan_guard`, not `refuse_novel`.
- **ADR-0050 item 4**, the `ctx.mech` bullet. A plan set is admitted by the same parent-commit
  check, without the mechanical stamp.
- **ADR-0026 item 7**, "Brief composition refuses any context line that names an identifier or
  literal the commit introduced". A delivered plan may name such a token; it is counted on the
  row (`ctx_plan_novel`) instead. Every other context line is refused as before.

- **ADR-0053 items 1 and 5.** A v3 entry may carry `gaps` and its set meets the same gate;
  a plan row may carry `ctx_open_gaps` on the same terms as a stated row.

This is a new arm with a guard of its own, not a relaxed gate. No source but `plan` changes.

## Consequences

- A team's own planning step can be measured on real commits: the pass rate with an accepted
  plan against the same builder without one, with n and Wilson intervals, by exact test.
- A plan that names its held-out tests, copies eight tokens of the change in a row, or copies
  a whole added line of code never reaches the builder; the row says why. A plan that
  paraphrases a short change in fewer than eight tokens, without a whole line of it, is not
  caught: the guard finds copies, not ideas.
- A plan that names what the build will add is delivered. The count is on the row; no reader
  splits on it yet [gap].
- There is no placebo for a plan yet, so a lift cannot yet be told apart from the effect of
  any extra text of that length [gap].
- Whether a plan was really written before the change is the drafter's claim. The record names
  the drafter, what they saw and who accepted, and the parent check holds, but the timing
  itself is attested, not proven. So are `drafter`, `saw` and `accepted_by`: they are the
  storing operator's claims, not checked against any account, so `ctx_plan_accepted` reads
  "the operator says this person accepted it", not a verified acceptance.
- `GET /ctxsets/{name}` and the UI's API types carry `planned` and `accepted_by`. No page
  shows them or the plan stamps yet [gap].

## Alternatives considered

- **Run plans as stated items under `req_guard`.** Rejected: items declare each disclosed
  token with provenance; a plan's steps and files do not fit that shape, and the stated limits
  would have to grow, which ADR-0052 forbids.
- **Trim a guarded plan line by line.** Rejected: a partial plan is a different plan from the
  one accepted. Withholding it whole keeps the arm meaning "the accepted plan, or nothing".
- **Refuse every novel token, as `refuse_novel` does.** Rejected: it would refuse most real
  plans and measure nothing. Counting keeps the rows honest and splittable.
- **Free-text plans.** Rejected: free text cannot be checked for shape or limits, and its
  layout would enter the digest. A plan rendered by code from sections removes both.
- **Let the plan's drafter see the change.** Rejected: that is a hindsight brief, which
  ADR-0050 already measures as a ceiling.
