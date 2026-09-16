# ADR-0009 — Text-level mutators for the non-Python languages

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** none (the strength number's *meaning* is unchanged: killed / graded;
the instrument that produced it is now named in the provenance stamp — `mutator_family`
and `operator_set_hash` — and the new `uncompilable` outcome is excluded, never counted)

## Context

Oracle adequacy is the semantic half of false-Q1 = 0: the belts prove a clean grade had a
GREEN oracle, and mutation scoring measures whether that green was worth anything (ADR-0001;
`crb.core.oracle.adequacy`). Until now the only mutator was the Python AST mutator, so every
Go, JavaScript, JVM and Rust task was **unscoreable** — on `spf13/cobra`, 25/25 tasks
unscoreable `[measured 2026-09-13; apparatus 2.0; method: a `crb` `oracle` run on the live
stack — the Python AST mutator over each task's changed lines produced zero mutants for every
Go file; n = 25 tasks]`. A capability map whose non-Python cells can never earn
`auto_ship` is not a routing brain for a polyglot enterprise estate; it is a Python tool
with four languages bolted on.

Constraints that shaped the answer:

- `crb.core` is standard-library only (ADR-0008). Python ships `ast`; it ships no parser
  for Go, JavaScript, Java, Kotlin or Rust, and tree-sitter is a compiled dependency in the
  verdict path.
- Per-cell strength must stay **comparable across languages within a language** — the
  same operator taxonomy, the same determinism (seed-free, byte-identical reruns, stable
  prefix under `max_mutants`), the same honesty properties (a RED baseline is unscoreable,
  a harness error is neither a kill nor an escape, the source is restored byte-exact).
- The AST mutator guarantees *every mutant compiles* by calling `compile()` before a
  candidate counts. A mutator that cannot see types cannot make that promise; a mutant the
  compiler rejects would be "killed" by the build failure and inflate strength dishonestly.

## Decision

1. **One text-level mutator for the C-family syntaxes** —
   `crb.core.oracle.mutators_text.TextLineMutator(language)` for `go`, `javascript`
   (+ TypeScript suffixes), `jvm` (Java, Kotlin) and `rust`. A small hand-written scanner
   per language (a comment/string state machine plus longest-match operators; no
   third-party dependency) produces opaque tokens for strings, chars, templates, regex
   literals and comments, so **no operator ever looks inside a literal or a comment**, and
   `<=` is one token, never `<` `=`.
2. **The same taxonomy.** Seven operators with the AST mutator's ranks for the five shared
   names: `cmp_flip`, `arith_flip`, `bool_flip`, `negate_cond`, `off_by_one`, plus
   `return_value` (the text analogue of `return_none`: `return true`↔`false`, a returned
   integer nudged, `return nil/null/None`-like and anything untyped skipped) and
   `delete_stmt` (one single-line statement blanked; never a line that opens or closes a
   block, a declaration clause, a label, a directive or a continuation). Each mutant is ONE
   change; candidates sort on `(line, col, operator-rank, description)`, are deduplicated by
   content, and ids are assigned before truncation — identical to the AST mutator.
3. **Confined to exactly the changed lines.** The AST mutator widens to the full span of
   every function the patch touched; the text mutator cannot see function spans and does
   not guess. This is recorded as a known difference between the families, not hidden.
4. **Structural well-formedness, then the toolchain.** Every text mutant is re-scanned
   (no unterminated literal or comment) and its brackets must still balance — the
   text-level analogue of `compile()`. Type errors are left to the toolchain: in
   `score_task`, a MUTANT run that the runner stamps as an *unattributed failure* (non-zero
   exit, no failing test id, `parse_error` set — the fail-closed contract in
   `BaseRunner.run`) is recorded as **`outcome = uncompilable`** and excluded from both the
   numerator and the denominator (`mutation.compile_failure`). A RED **baseline** with the
   same signature stays *unscoreable*: the two are never confused, because the baseline is
   checked before any mutant is written. A timeout is never a compile failure.
5. **The provenance stamp names the family.** `MutationProvenance` gains `mutator_family`
   (`ast` | `text`) and `operator_set_hash` now covers the text operator table, the
   substitution tables and the language profile (`describe()`), so the hash differs per
   language by construction. `mutator_for("go" | "javascript" | "jvm" | "rust")` returns the
   text mutator; `python` keeps the AST mutator; an unregistered language is still
   honestly unscoreable — never silently scored with the Python mutator.
6. **Registered in the scorer, not special-cased.** The shared `Mutant`/`Mutator` contract
   moves to the leaf module `crb.core.oracle.mutant` so the scorer can import the text
   mutator without an import cycle; `crb.core.oracle.mutation` re-exports it and its public
   API is unchanged.
7. **Every written version is newer than wall-clock.** Bringing compiled toolchains under
   the scorer exposed a latent honesty bug [measured, on the Maven fixture]: the scorer
   stamped each mutant/restore with a *distinct* mtime (`base + k`, which defeats the
   `.pyc` equality check) but one that could be **older** than the `.class` files Maven
   compiled during the baseline run, so Maven's stale-source check — and cargo's
   fingerprints, both mtime-*ordered* — sometimes skipped recompilation and graded the
   previous version's code. `_next_tick` now stamps every version strictly after both the
   previous version and `time.time()`, so it is newer than any artefact that exists when
   it is written; pinned by a regression test. Go keys its build cache on content and node
   has none, so they were never exposed.

## Consequences

- Go, JavaScript/TypeScript, Java/Kotlin and Rust tasks are now scoreable; their cells can
  earn `strong` / `adequate` / `weak` bands and, through the adequacy gate, `auto_ship`.
  Verified end to end on the four fixture toolchains: the obvious mutants (`a - b` → `a + b`,
  the negated condition) are killed by the feat commit's own test, the untested branch
  escapes, and a deleted declaration is rejected by `go`/`javac`/`rustc` and excluded.
- **Strength numbers are comparable only within a language and a family.** A Go cell's
  0.60 and a Python cell's 0.60 were produced by different instruments with different
  reach; the stamp (`mutator_family`, `operator_set_hash`, `language`) travels with every
  number and every report, and readers must not pool across it.
- The text mutator **never reasons about types**: a `+`→`-` on strings, a `*`→`/` on a
  pointer type, an integer nudge in an array size, a deleted `let`/`:=`/`int d = …` all
  reach the toolchain and come back `uncompilable`. That count is reported per task and per
  cell; it is not oracle weakness and not an error — it is the compiler doing part of the
  oracle's job. A high count is expected in Go and Java, near zero in JavaScript.
- JavaScript has no compile step, so `delete_stmt` on a declaration is a *runtime* fault
  the tests can observe (a kill or an escape), where in Go it is `uncompilable`. The same
  operator measures a slightly different thing per language — one more reason the numbers
  do not pool.
- Known limitation, recorded not hidden: under `node --test` an import-time `SyntaxError`
  is attributed by the JUnit reporter to the test FILE as a failing test case, so it would
  read as a kill rather than `uncompilable`. The text mutator's structural check (re-scan +
  bracket balance) is what prevents a syntax-broken mutant from being emitted in the first
  place; making the node runner classify a file-level load failure as an unattributed
  failure would close the residual gap and is the runner's change to make.
- Rust tail expressions (no `return` keyword) are invisible to `return_value`; `if let` is
  never negated; a Go pointer/deref `*` after an identifier is read as binary and comes back
  `uncompilable`. Generic brackets (`List<String>`, `Vec<i32>`) are distinguished from
  comparisons by spacing — the spaced form only is mutated — a heuristic, but a
  deterministic one, and a wrong guess is caught by the toolchain, never counted.
- We must never: count an `uncompilable` mutant in either direction; average an
  unscoreable task into a cell; compare or pool strengths across families; or let a
  mutator touch a test file (the scorer refuses outright).

## Alternatives considered

- **tree-sitter (or per-language parsers) in `crb.core`.** Rejected: a compiled
  third-party dependency in the verdict path, forbidden by ADR-0008; the grammars change
  under us; and the auditable reproduction story ("Python 3.12 + git") breaks.
- **Shell out to each language's own parser (`go/ast`, `javac -Xprint`, `rustc -Zast-json`).**
  Rejected: four more toolchain contracts to maintain in the *generation* path, unavailable
  under the docker executor at generation time, and non-deterministic across toolchain
  versions in ways a text scanner is not.
- **Count a toolchain-rejected mutant as killed ("CI would be red").** Rejected: it credits
  the oracle for a fault it never observed and inflates strength exactly where the text
  mutator is weakest; the honest reading is "not graded", and the count is surfaced so a
  reader can see how much of the attack surface the compiler absorbed.
- **Count it as escaped.** Rejected for the mirror reason: it punishes a suite for a fault
  that could never ship.
- **Only the token-substitution operators, no `delete_stmt` / `return_value`.** Rejected:
  it would drop the two operators that most often find "the branch nobody exercises", and
  the taxonomy would no longer cover the AST mutator's return-value and control-flow
  classes.
- **Widen the text mutator to changed functions by brace-matching.** Rejected for now:
  brace-matching without a grammar mis-scopes lambdas, closures and nested types; the
  narrower, exact confinement is the honest one and is recorded as a family difference.
