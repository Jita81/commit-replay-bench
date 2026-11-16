# ADR-0052 — Stated-requirement arms: pass rate when every required item is stated

**Status:** Proposed (DL-420)
**Date:** 2026-11-15
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. No existing row, arm, guard decision,
reader result or builder input changes. The new arm id is a pooling key of its own, every new
stamp is provenance, and a `req` pair is read within one apparatus.
**Amends:** ADR-0050 items 3 and 4, for the `req` and `req-placebo` sources only (see
"Amended lines" below).

## Context

Sign-off needs certain items: names, signatures, error texts, formats, rules and values. An
item that neither the request nor the product holds is a gap. A person closes it by stating
it. The question is: what is the pass rate when every required item is stated, per structure,
against the request as written?

Today the instrument cannot ask this [gap]:

- The leak guard (`novel_tokens`, `refuse_novel` in `crb.builders.brief`) withholds a whole
  entry that names any token the commit introduced. No source is exempt, and `ctx.oracle`
  skips only the time rule (ADR-0050 item 4). A feature commit introduces new names, so an
  entry stating them is withheld and the row runs with `ctx_delivered` = `0`.
- The pair reader links a control to one set digest only. A prose set and a checklist set over
  the same items cannot share a control.
- `turns` is not on the grade row, and the pair reader reads no cost.

Options weighed (see Alternatives):

- **A.** A guard-safe sub-population on the existing arms.
- **B.** Rewriting the ticket.
- **C.** Exempting `ctx.oracle` from the guard.
- **D.** A new declared source with its own disclosure guard.

D is chosen. It is a new arm whose guard differs from the novel-token guard, so it amends
ADR-0050 for that arm only. Every other source keeps the guard unchanged.

## Decision

1. **Source and arm.**
   - Two new sources, `req` and `req-placebo`, are added to the source-to-kind table
     `CTX_SOURCE_KIND` in `crb.core.context_arm`. Their kind is `stated`. Each source has
     exactly one kind; `tests/test_stated.py` pins this.
   - The name is `ctx.req.<digest[:12]>` and the arm is `A0+library@ctx.req.<hex>`.
   - `hindsight_arm` is true for the stated kind. That means the time-rule skip and the
     `ctx_ceiling` = `1` stamp follow the existing code.
   - `stated_arm` is the `req`-only predicate.
   - `CtxSet.hindsight` and the parser read the same table. There is no second definition.
   - `measurement_only` keys on the `ctx.` name. So every reader that drops ADR-0050 arms
     also drops these: routing, capability, the value scorecard, readings, the re-measure plan
     and its pricing, and the north star. `tests/test_req_measurement_only.py` pins this.
   - The arm id is a pooling key. `req` rows never pool with `A0`, `ctx.oracle*`, `ctx.mech*`
     or library rows.
2. **Stamps (`crb.core.ledger.ctx_label_violation`).**
   - A `req` entries row carries all of these: `ctx_stated` = `1`, `ctx_items` (the items
     digest), `ctx_structure`, `ctx_author_saw`, `ctx_prov` (counts per provenance plus
     `attested`) and `ctx_req_drafter`.
   - It may carry `ctx_req_refused`, the guard's reasons.
   - The author is `ctx_req_drafter`, never `ctx_drafter`, which keeps its mechanical meaning.
   - No other row carries any of these stamps: not a control row, not an oracle or mech row,
     not a plain row.
   - `ctx_turns` is the builder's turn count. It is an optional count on every context-set
     run's row, control included, and on no other row. A row whose builder never ran carries
     none, so it counts as missing rather than as zero.
   - `ctx_req_refused`, when present, is a sorted, comma-separated set of the guard's reasons
     below; any other value is refused at write and on read. It is not in `PROVENANCE_LABELS` and is
     not a pooling or blend key.
3. **The guard for `req` entries (`crb.builders.brief.req_guard`).** It is a pure function of
   the entry, its items and a harness-side gold view (`gold_view`: the novel set, a lookup of
   the parent tree, the source and test post-images, their added lines, and the test paths).
   It runs at compose time on every attempt and fails closed. With no gold view the reason is
   `req_no_gold`. A blob the commit or its parent holds that cannot be read gives no gold view;
   only a path one side lacks, a binary blob or a submodule pointer reads as empty, and
   `crb ctxset lint` stops with an error on such a blob. A withheld entry is counted (intention to
   treat) and its reasons are
   stamped. The reasons are:
   - `req_render`: the text is not the structure's rendering of the items.
   - `req_length`: more than 12 items, more than 240 characters in a statement, or more than
     1,600 characters in an entry.
   - `req_code_block`: a fence, or an indented line.
   - `req_disclose`: an item discloses something that is not one exact token of the change:
     not a novel token, not a code token of the source or test post-image, and not in the
     parent. A whole statement or a phrase wrapped round a token therefore declares nothing.
   - `req_undeclared_novel`: a statement names a novel token that its item does not declare.
     Matching is case- and whitespace-insensitive, which is stricter than `names_novel`. Only
     the text of a declared token, as a whole token, is masked out, so a declared token does
     not cover a novel token outside it or a longer token it is part of. The statement is
     also read with each declared token masked as a plain substring, and a novel token named
     on either reading counts, so masking never leaves fewer tokens named.
   - `req_provenance`: an item's declared provenance is not the most answer-side of the tokens
     it discloses or names. The ranking is nowhere < product < change_detail < tests_only, and
     a token in both the source and the tests counts as change_detail. A token is product only
     when the parent holds it in product code: a file that is not a test path, on a line that
     is not only a comment (`//`, `#`, `/*`, `*`, `--`). A token the parent holds only in a test
     file or a comment ranks by the post-images, and is product when neither holds it, so the
     label never ranks below the plain parent lookup. Every lookup, parent included, is
     whole-word and case-sensitive, so a token that appears only inside a longer
     word does not lower the provenance. The check is made twice, once on the tokens named
     on either reading and once on those named with the substring mask alone, and the item
     is refused when either disagrees.
   - `req_test_name`: an identifier or literal on a held-out test's definition or title line
     (pytest, unittest, Go `Test*` and `t.Run`, Rust `#[test]` and `mod tests`, JS
     `it`/`test`/`describe`, JUnit `@Test` and `@DisplayName`, parametrize ids) that neither
     the source post-image nor the parent holds. The names a test file defines (helpers,
     fixtures, constants, and every name an assignment in a Python test file (`.py`, `.pyi`)
     binds, such as `LIMIT = 10`, `A, B = 1, 2` or `self.LIMIT = 10`) count as test names
     too. The assignment rule reads only Python test files, so a Go `x := f()` defines nothing.
     In a JVM or .NET test file (`.java`, `.kt`, `.kts`, `.scala`, `.groovy`, `.cs`) every
     method or class name it declares counts, after any block comment, annotation or
     attribute on the same line, so the method on the line after `@Test` or `[Fact]` is one,
     as is a Kotlin backtick or Spock string name. Not read: fields and constants, a
     declaration split over lines, a return type in lower case other than a primitive, and
     annotation arguments nested more than one level.
   - `req_test_path`: a held-out test's path, file name or specific stem.
   - `req_test_span`: eight tokens in a row shared with the change's added test lines, read
     over the whole entry, so a run split across items is still found. The change's added
     source lines count too, except a signature item's header: from its start through the
     parenthesis that closes its parameter list and an optional return annotation. The entry's
     tokens are compared only where they belong to the change's own vocabulary, so prose words
     between copied code tokens do not break a run. A run still counts when copies of one
     single token of the change's own vocabulary are inserted inside it, as long as its eight
     tokens appear in order within sixteen. This is a bound: a run padded with two or more
     distinct tokens of the change's vocabulary, or spread wider than sixteen tokens, is not
     found.
   - `req_signature`: a signature item that carries a body: a brace, `;`, `=>` or `return`
     anywhere, or executable Python before its name or past its header (a call, `=`, `raise`,
     `yield`, `await`, `lambda`, a spaced arithmetic operator, or a statement opening the
     text). For this check a Go method's header (`func`, a receiver, one name, the parameter
     list and one result type or parenthesised result list) is read whole; the source-span
     rule still exempts only through the first closing parenthesis.

   The limits are fixed in `crb.core.stated`. Changing them needs a new ADR. A CLI lint
   (`crb ctxset lint FILE --clone DIR`) runs the same function against a local clone before a
   set is stored. That lint splits paths by the generic test-path heuristic; the run's guard
   stays authoritative. The lint and the miner, whose task paths the run's guard reads, list
   changed paths NUL-separated (`-z`), so a non-ASCII path is read as itself, not as git's
   display quoting.
4. **Items and structure (`crb.core.stated`, schema `crb.ctxset.v2`).**
   - A v2 entry holds items, never text. Each item is
     `{item_id, kind, statement, provenance, discloses}`.
   - The text the builder reads is rendered by code with the set's fixed renderer, `prose` or
     `checklist`. Both renderers state every statement verbatim, in `item_id` order, under one
     header.
   - The item hash covers task, id, kind, statement, provenance and the sorted discloses. The
     items digest is the sha256 of the sorted item hashes. Text and structure are outside it,
     so two structures over the same items share one items digest and carry the same
     information.
   - The parser refuses an item whose statement does not contain each token it discloses
     (`ctxset_items_undelivered`), and an entry over the limits (`ctxset_items_length`).
   - The set names `drafter` (`human:<id>` or `model:<id>@<prompt sha256>`) and `saw` (a subset
     of `diff`, `tests`, `ticket`).
   - v1 parsing is unchanged, so every stored v1 digest is unchanged.
5. **Pairing (`crb.core.ctx_compare.ctx_pair`).**
   - A control run of stated set P links to a stated treatment C when both are stored, are
     stated, and have equal items digest, repo and task list. Otherwise the pair is refused as
     `ctx_pair_items_mismatch` (or `ctx_pair_unlinked` when P is not stored).
   - Two structures over the same items digest share one control: a control run of either set
     links to the other set's entries run.
   - A non-stated treatment against a stated control is refused.
   - An entries run of P against an entries run of C is the **head-to-head** structure
     contrast.
   - The oracle and mech linkage rules are unchanged.
   - The `/ctxsets/compare` route loads every set the rows name.
6. **Reading.**
   - A `req` comparison leads with its own banner, `STATED_BANNER`, in place of the ceiling
     banner. The next line holds the provenance counts.
   - Provenance strata, split by whether any item is `tests_only`, are always part of the
     result, and the text rendering prints both strata (`tests_only`, `no_tests_only`), an
     empty one as `n 0`.
   - Every pair also carries a descriptive cost block: per side, the median and total of
     `cost_usd`, `tokens_in`, `tokens_out` and `ctx_turns` over first attempts (`cost_usd`
     over known costs only), the count of first attempts with no known cost (`cost_usd_missing`,
     never read as
     zero), and the paired per-task cost difference (median, inclusive IQR) with its n and the
     count of tasks unpriced on either side (`n_missing`).
   - Every pair carries both sides' time windows, and a `drift` flag when the sides ran more
     than seven days apart.
   - The structure question is read only from a head-to-head pair. Subtracting two lifts over
     one control is not a test. With more than two structures, a Holm adjustment across the
     head-to-head comparisons is required before any one is reported. Only two structures
     exist today.
7. **Off by default.** A run without `context_set` is unchanged. A `req` run has the same
   conditions as every context-set run (ADR-0050 item 10).

### Amended lines

This ADR amends ADR-0050, **for the `req` and `req-placebo` sources only**, in two places:

- **Item 3**, the sentences "every entry passes the same refusal as a playbook line. The guard
  is never relaxed." For a `req` entry that carries items, the refusal is `req_guard`, not
  `refuse_novel`.
- **Item 4**, the first bullet, "A hindsight set is exempt from the retrospective time rule
  only, never from the leak guard or the bare-fact refusal." A `req` set is exempt from the
  time rule and from `refuse_novel` for its item entries. It is not exempt from `req_guard` or
  from the bare-fact refusal.

For every other source (`oracle`, `oracle-placebo`, `mech`, `mech-placebo`), and for every
fact, learned line and item-less entry on a `req` arm, `refuse_novel` applies exactly as
before. `tests/test_brief_req_guard.py::test_refuse_novel_still_applies_to_every_non_req_line`
pins this.

This is a new arm with a declared-disclosure guard. It is not "no gate relaxed": a `req` entry
may name a token the commit introduced when an item declares it, with checked provenance.

## Consequences

**Easier.**

- The pass rate given items written with sight of the change can be measured against the
  request as written, with n, Wilson intervals and an exact test, on the same commits.
- Prose and checklist over the same items share one control, and the structure question has
  a head-to-head pair of its own.
- Every context-set pair carries its cost and its time windows.

**Harder.**

- Items are written with hindsight. The result is a reference for that writer's items, not
  what a requester would state. The claim wording is "given items written with sight of the
  tests". It is never a builder capability, and never "context lifts capability".
- The guard does not stop a full paraphrase of the fix in words. A task whose items are all
  `tests_only` is close to handing over the tests in words, hence the required strata.
- The novel set ignores short identifiers and single digits, and makes every candidate novel
  on a very large commit. Such tasks lean toward refusal. Report the n of withheld tasks next
  to any result. A token counts as held by the parent exactly when the per-token lookup finds
  it, even when the parent holds it only inside a longer candidate ("Service" inside "Service
  Unavailable"); the batched read repeats until it agrees, and keeps the rest novel past its
  pass limit.
- Each structure needs its own `req-placebo`, length-matched to it, before any claim that
  "the items helped" rather than "more text helped".

**Must never.**

- Relax `refuse_novel` for any source other than `req` and `req-placebo`.
- Let a `req` row certify, license, route, pool or enter the value scorecard.
- Reuse `ctx_drafter` for a stated set's author.
- Accept author-supplied text for a `req` entry. The text is always rendered from the items.
- Report a structure difference from two lifts over one control.
- Word a `req` result as a builder capability, or as context free of the answer.

**Open.**

- A push-back gate, which returns a request with known gaps [aspiration]. Nothing supports it
  yet. It needs a `req` lift over control on at least two repositories, a detector computed
  before the change that predicts which tasks gain, and that detector's false-positive rate.
  The provenance counts are its training signal. It is not designed here.
- Whether the guard limits (8 tokens, 12 items, 240 and 1,600 characters) are right
  [hypothesis]. They are proposals, not measured.

## Alternatives considered

- **A. A guard-safe sub-population on `ctx.oracle`.** It selects exactly the tasks without a
  naming gap, so it cannot answer the question for new names. It is kept only as a separately
  labelled oracle stratum, never reported together with `req` results.
- **B. Requirements written into the ticket.** The ticket is not guarded. `ctx_ticket` is
  provenance, so the rows would pool with plain `A0`, and the request as written could no
  longer be told apart from the request plus items.
- **C. Exempting `ctx.oracle` from the guard, or swapping the guard on every arm.** It relaxes
  an existing gate. ADR-0050 forbids it.
- **Free-text entries checked for verbatim statements.** Rejected for code rendering: two
  structures could still carry different content under one items digest.
- **An apparatus bump to 2.7.** Rejected: no existing row, arm, guard decision or reader result
  changes, and the arm id already separates the rows. A bump moves every posture id.
