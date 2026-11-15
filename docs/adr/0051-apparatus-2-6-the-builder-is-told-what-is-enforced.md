# ADR-0051 — Apparatus 2.6: the builder is told what is enforced and can run its tests

**Status:** Proposed (DL-419)
**Date:** 2026-11-14
**Apparatus impact:** bumps `APPARATUS_VERSION` to **2.6**. The builder's input changes: the
rules text, the refusal messages it reads mid-run, and an attempt refused before any model call
when the test tool does not start in the builder's own environment. Nothing that grades
moves: the belt set stays `v5`, the failure rule is unchanged (its golden hash at 2.6 equals
2.4's), the deny rules and every guard accept or refuse decision are unchanged, the mutation
scorer stays `mutation.v2`, and there is no migration and no schema change. Every posture id
moves with the stamp. Rows stamped 2.5 keep their meaning, are never re-graded and are never
pooled with 2.6 rows.

## Context

Two things the builder was handed did not match what the product enforces or provides.

**The rules disagreed with the enforcement.**

1. The recommended way to run the tests without the builder's own edits named
   `git checkout -- <paths>`, and claude_code's deny rules refuse `git checkout`. A builder that
   followed the advice issued a refused command, and a refused command counts as a violation.
2. The guard refuses a command it cannot parse (an unterminated quote, an unbalanced
   substitution, a here-document without a tag, a computed command name, `eval`), and that
   refusal is a violation. The rules never said so.
3. The rules said every violation disqualifies the run. Only test-file tampering does: a
   history, stash, network, install or unparseable command discards all the builder's source
   edits and fails the row with kind `protocol`. The stated outcome was wrong for every
   non-tamper violation.

**The builder could be handed a test command it could not run.** A Python repository whose lock
has no runtime dependency and pytest only in a development group resolves to no dependency
recipe, so a sealed builder gets no `/deps` site. The default builder image has no pytest. The
brief still handed the builder `python -m pytest …`, so every attempt paid for a builder that
could not run the command its brief gave it.

Rows graded before and after these fixes are different measurements, and nothing on a row
separates them. The reserved-reading treatment fingerprint hashes the builder image's tag, not
its image id (`crb.server.worker._container_projection`), so a rebuilt image under one tag does
not move it. The rules text is stamped on a row as the `ctx_rules` label, which is provenance:
shown and filterable, never a pooling key (`crb.core.context_arm.PROVENANCE_LABELS`, ADR-0026
item 1). Economics and the forecast separate rows only by apparatus, posture class, checks arm,
context arm and class-set version (`crb.core.economics`).

## Decision

1. `APPARATUS_VERSION` is `"2.6"` (`src/crb/core/version.py`). One bump covers both fixes,
   since both change what the builder is given and they ship together.
2. **The rules text.** `DEFAULT_RULES` (`src/crb/builders/base.py`), given to every builder,
   says that only tampering disqualifies; that a history, stash, network, install or
   unparseable command discards all source edits and fails the run; that a refused command still
   counts; and which unparseable forms are refused. claude_code's `system_rules` lists exactly
   the git subcommands its deny rules refuse, derived from `DENY_RULES` so the two cannot drift,
   and gives one stash-free line (`STASH_FREE_IDIOM`) to run the tests without the builder's
   edits. The advice to use `git checkout` is gone. `openai_agent` has no shell and gets no
   such line.
3. **The refusal messages.** The `git stash` refusal carries the same stash-free line. A
   could-not-parse refusal names its cause: unterminated quote, trailing backslash, unmatched
   backtick or unbalanced substitution.
4. **The preflight.** Before any model call (the `S1` author included), in blind and sighted
   modes, `build_fn_for`'s `attempt_of` (`src/crb/builders/adapter.py`) runs the runner's
   declared tool check in the builder's own environment: the builder image for a sealed builder,
   with the same mounts, `/deps` view and environment as the session, else the run's local
   executor or the host. The check is the handed command with only its argv replaced. A
   non-zero exit, a timeout, a cancellation, an environment error or a check that raised
   refuses the attempt as `runner tool missing: <tool> — …`, which the existing failure rule
   already classifies as a harness failure. An unavailable sandbox still stops the run.
5. **The Python builder image.** `deploy/Dockerfile.builder` gains a `crb-builder-python`
   variant, built on the Python sandbox image, and a `crb-builder-node` variant, each with its
   own tag. CI builds and smoke-tests each one as uid 65534 with no network. An operator
   selects a variant; the default `BASE_IMAGE` is unchanged.
6. **The discard record.** Before the adapter discards a builder's edits it captures the diff it
   drops (never the test overlay). The evidence pack keeps it as `notes.discarded_patch` with
   `notes.discarded_files`, the row carries the free-form label `discarded_files=<count>`, and
   the `builder.discard` event names the task. The capture is best-effort; a failure emits
   `builder.discard.error`.

**What does not change:** no verdict rule, no deny rule, no guard accept or refuse decision,
the failure rule and its golden (`tests/test_failure_rule_golden.py`), grading and belts, and
what counts inside n. A preflight refusal is a harness row, so it stays in the fail-closed n
and outside the model's n, as every `runner tool missing` row already does.

## Consequences

**Easier.** A builder that follows its rules issues no refused command [hypothesis: the rules
are derived from what the guard and the deny rules enforce, but no 2.6 run has measured it],
and a builder whose test tool does not start is not paid for. A 2.6 row is separated from a
2.5 row on the apparatus axis. A reader that pools versions still combines them: a read with
`apparatus=all`, and the flat cost and latency means under it (P-134, G-990). This change
does not alter those readers.

**Harder.**

- The apparatus is part of a posture's identity (`Posture.apparatus_version`,
  `src/crb/core/posture.py`), so every posture id moves. Every task is qualified again at 2.6
  before it is graded there: test runs only, no model spend. Oracle scores, negative controls
  and sign-offs are read at one apparatus, so they are redone before a cell delivers at 2.6.
- A reserved reading registered at 2.5 pinned its pool to a 2.5 posture; a run filed under it
  is refused `pool_drift` (P-797). Close every 2.5 campaign on a stack before deploying 2.6.
- A sealed Python builder on the default image is now refused before the model is called,
  where it used to be paid for and fail. Select `crb-builder-python` for such a repository.

**Must never.** Blend 2.5 and 2.6 rows in a rate, a reading or a claim. This holds for the
context-set arms of ADR-0050 too, which landed at 2.5: a context-set run graded at 2.6 is paired
only with a control graded at 2.6, and the paired reader already refuses a blend of apparatus.

**New on 2.6 rows.** The discard record: the kept discarded patch, the `discarded_files` count
label and the task id on the `builder.discard` event. A 2.5 row carries none of them, and its
absence there says nothing about whether edits were discarded. A row with the label chains with
rows without it, and the ledger verifies
(`tests/test_builders_adapter.py::test_a_row_with_the_discard_label_chains_with_rows_without_it`).

## Left open, unchanged by this ADR

- Whether a command the tool refused, and that therefore never ran, counts as a violation. It
  counts today, and the rules now say so; the docstring of claude_code's `_inspect_tool_use`
  records it as an open policy decision and a test pins the current behaviour.
- Whether a read-only stash form (`git stash list`, `git stash show`) triggers the full discard.
- How a protocol discard counts in a reading.
- Whether a parse failure gets its own failure kind rather than `protocol`.

## Known gaps

- The treatment fingerprint hashes the builder image's tag, not its image id, so a rebuilt image
  under one tag is not separated (G-113).
- Nothing selects the builder image from the runner's language; the default `BASE_IMAGE` has no
  pytest, so a sealed Python builder on it is refused until an operator selects the Python
  variant, and no CI job builds the default-base variant (G-114).
- The rules cross-check compares the advised commands with an emulation of claude_code's
  deny-rule matching, not with the CLI itself, so a change in how the CLI matches a deny rule
  is not caught (G-115).
- The discarded-patch capture is best-effort: when it fails, the record has only the
  `builder.discard.error` event, not the patch.

## Alternatives considered

- **No bump.** Rows graded under the old rules and the new ones would pool, and nothing on a row
  separates them; that blend is what the apparatus stamp exists to prevent.
- **Two separate bumps, one per fix.** Both fixes change the builder's input and ship together;
  a 2.6 that held only one of them would never be deployed alone, and every posture would be
  re-qualified twice for no separation anyone could read.
- **Change the dependency-group default, so the Python builder's `/deps` site carries pytest.**
  That changes which dependency set the grader binds, a grading change, where this decision
  changes only what the builder is handed.
