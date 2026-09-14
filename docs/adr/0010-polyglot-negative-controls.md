# ADR-0010 — Polyglot negative controls (Go and JavaScript)

**Status:** Accepted
**Date:** 2026-09-14
**Apparatus impact:** none to verdict semantics (`APPARATUS_VERSION` unchanged); the controls
instrument is re-stamped `controls_version = controls.v2` so a Go/JS gate result can never be
confused with one from v1, where four of the seven controls could not exist outside Python.

## Context

The negative-controls gate (`crb.core.oracle.controls`) proves the *instrument* rejects what
it must reject, with no model: seven deterministic submissions through the real replay path.
Three of them (`gold`, `noop`, `test_tamper`) are language-agnostic. The other four were
Python-AST transforms, so on every non-Python repository they read `not_constructible`. The
2026-09-13 critical-friend review (§4.2 reading 6, action #6) measured the consequence on the
live stack: spf13/cobra and koajs/koa each wrote 56 control rows with **32 `not_constructible`**
[measured], and the gate said "passed" with exactly the load-bearing controls untested:

- `regression` is the control that proves belt 3 (no new failures) is load-bearing rather than
  ornamental;
- `stub` proves belt 2 (target green) cannot be satisfied by an empty body;
- `hardcode_cheat` and `env_poison` are the *measurement* controls — they probe whether the
  oracle and the belts can tell an implementation from a lookup table or from state pollution.

Reproduced on the in-repo fixtures before this change: `tests/fixtures/langs/gorepo` and
`noderepo` both **4/7 `not_constructible`** (stub, regression, hardcode_cheat, env_poison)
[measured, `scratchpad/a3/before.py`, 2026-09-13].

Constraints, the same ones that shaped ADR-0009: `crb.core` is standard-library only
(ADR-0008), so there is no Go or JavaScript parser; every transform must be deterministic and
pure over text so it can be unit-tested without a repository; a cheat that cannot be built
must say so, never be faked, and never become a violation; and a control must go red **for
the right reason** — a stub that panics or fails to compile is "red", but it has not exercised
the belt it exists to test.

## Decision

1. **Two new pure transform modules, dispatched by language.** `controls_go.py` and
   `controls_js.py` implement `stub`, `regression`, `hardcode_cheat` and `env_poison` over the
   token stream of `mutators_text.tokenize` (Go / JavaScript profiles: literals, templates,
   regexes and comments are opaque; bracket matching is exact). `controls._apply_control`
   dispatches on `RepoConfig.language`: `python` keeps the AST transforms unchanged; `go` and
   `javascript` (including the TypeScript suffixes) use the new modules; `jvm` and `rust`
   read `not_constructible` with the reason *"no transform for <language> yet — constructible
   for python, go, javascript only"*. `gold`, `noop`, `test_tamper` are untouched.
2. **The toolchain checks every generated edit.** A Go stub / cheat / poison must compile
   *against the target test* (`go test -count=1 -run '^$' <target packages>` through the
   runner's own command, env and sandbox); a JavaScript one must parse (`node --check` for
   `.js/.mjs/.cjs`; the scanner's structural check for TypeScript/JSX, which node cannot
   parse). A failed check is `not_constructible` with the toolchain's tail as the reason —
   never a violation, never a row that graded red for a build error and claimed a belt.
3. **What each control is, per language** (the table is the contract; the row note repeats
   the vector so a reader can see what was done):

   | control | Go | JavaScript | expectation | honestly `not_constructible` when |
   |---|---|---|---|---|
   | `stub` | every function / method / `var f = func…` the gold changed keeps its signature; body → zero-value returns (`return 0, nil`, `return *new(T)` — the zero value of any `T`; `{}` for no results). Added functions appended as stubs with the gold signature; imports the hollowed bodies no longer use are blank-aliased (`_ "fmt"`); imports the appended signatures need are copied from the gold. **Never `panic`.** | every function-shaped unit the gold changed (`function f(){}`, `const f = () => {}`, class / object methods, `exports.f = function(){}`) keeps its signature; body → `return undefined;`. Added top-level units appended and exported the way the gold exports them (`export function` / `module.exports.f = f`). | `red` on an **assertion** (the runner attributes a failing test id, no parse error) | nothing function-shaped changed; source unscannable; the stub does not compile / parse (reason carries the toolchain tail) |
   | `regression` | gold overlaid + a NEW non-test file `negctrl_regression_poison.go` in an **adjacent package** whose `init()` panics. Adjacent = inside the belt scope, outside the target package(s), has `_test.go` files, and not import-reachable (transitively, via the in-module import graph) from the target. Go's target scope is the whole package, so a broken *function* in the same package is seen by belt 2, not belt 3 — the package is the unit belt 3 alone can see. | gold overlaid + `throw new Error("negctrl-regression-poison")` prepended to an **adjacent module**: one a test inside the belt scope imports and neither the target tests nor the module(s) under test import (relative specifiers resolved against the importing file). | `regressed` | `TARGET_ONLY` (and on Go `AFFECTED_DIRS`, whose belt is the target package) — the reason names the scope and says it can never construct this control; or no adjacent tested unit exists inside the belt. Runner-side, a poison that reaches the target (`red`) stays `not_constructible`, as for Python. |
   | `hardcode_cheat` | literal `(call, expectation)` pairs from the target test: `if got := f(1, 2); got != 3 {`, `if f(1) != 2 {`, `if 2 != f(1) {`, testify `assert/require.Equal|EqualValues|Exactly(t, want, f(…))` (either order, trailing message allowed), `.True/.False(t, f(…))`. Existing function: `if a == 1 && b == 2 { return 3 }` prepended, buggy body kept. Missing function: appended with the **gold** signature and only the guards + zero fallthrough. Single-result functions only. | `expect(f(1, 2)).toBe|toEqual|toStrictEqual(lit)`, `assert.equal|strictEqual|deepEqual|deepStrictEqual(f(…), lit)` (either order), ava/tape `t.is|deepEqual|equal|strictEqual(...)`. Scalar arguments only; the expectation may be an array/object literal of literals. Guard `if (a === 1 && b === 2) { return 3; }`; missing units appended with the gold signature and export wiring. | `caught_or_flagged` — `clean` is a **measured oracle escape** (the target tests cannot tell an implementation from a lookup) | no literal pair in the recognised shapes (table-driven Go tests and variable expectations are deliberately unparsed — narrowness is the point); facts name no function in the parent or the gold; the cheat does not compile / parse |
   | `env_poison` | Go has no collection-time hook. The one honest vector is a NEW non-test file `negctrl_env_poison.go` in the target package whose `init()` re-assigns every **package-level variable** the commit changed to its gold initialiser (`var Scale = func…`). The graded source file stays byte-identical to the parent. | an identity edit + the runner's own hook: **jest** `setupFiles` (`package.json#jest` / `jest.config.json` merged; else a new `jest.config.cjs`), **mocha** `require` (`package.json#mocha` / `.mocharc.json` merged; else a new `.mocharc.json`), **vitest** `test.setupFiles` in a new `vitest.config.mjs` + `vi.mock`. The hook loads a gold copy written *beside* the module (`src/x.negctrl_env_poison_gold.js`, so its relative imports resolve) and patches the real module's exports in place (CJS) or mocks the module id (ESM). | `caught_or_flagged` — the note names the belt that caught it (`caught by belt 1: …` / `belt 3` / `belt 2`) | Go: the commit changes only plain `func`s — there is no init-time way to replace a Go function, and the reason says so. JS: `node --test` (no configuration file; `NODE_OPTIONS` belongs to the harness); an existing JS/YAML-format runner config that cannot be merged textually (JSON configs are merged; nothing is rewritten by guesswork); the module does not exist at the parent (nothing to pollute). |

4. **An `env_poison` escape is no longer "not a grader bug".** The review (§4.3) overturned
   that reading: the oracle is the *test run*, and test infrastructure the runner loads is part
   of it. Workstream A1 is extending belt 1 to disqualify changes to such files. The module
   docstring, the escape note and the report now say: a clean `env_poison` row on Python or
   JavaScript is expected to be DQ'd by belt 1 and, if it still grades clean, **that is a
   belt-1 coverage gap to report** — never a weakness of the repository's tests. On Go the
   vector is a plain source file (`init()`), which no belt can or should reject; an escape
   there is recorded for the human reviewer of the accepted diff (review §7.1). The
   expectation stays `caught_or_flagged`, so the rows are consistent whether A1 has landed
   or not; the note says which belt did the work.
5. **What the gold diff touched is derived from git, never from a builder.** Both modules
   compare the parent file (worktree) with the commit's own version (`git show <sha>:<path>`)
   unit by unit; the runner never reads a builder's diff.

Enforced by: `crb.core.oracle.controls._apply_control` (dispatch, compile / syntax checks,
`NOT_CONSTRUCTIBLE_ERRORS`), `controls_go.{stub_changed_functions, select_adjacent_package,
regression_poison_file, extract_literal_asserts, build_hardcode_cheat, env_poison_file}`,
`controls_js.{stub_changed_functions, select_poison_target, belt_test_files, poison_module,
extract_literal_asserts, build_hardcode_cheat, env_poison_plan}`; proven end to end by
`tests/test_oracle_controls_go.py` and `tests/test_oracle_controls_js.py` on the real
toolchains (all four node runners).

## Consequences

- On the in-repo fixtures the constructible count goes from **4/7 → 6/7** on `gorepo` and
  `noderepo` (both feat commits *add* a unit, so `env_poison` has nothing to pollute — the
  same honest outcome as the Python `new`-file fixture) and **7/7** on the new
  `negctrl/gorepo_funcvar` (a changed `var Scale = func…`) and `negctrl/noderepo_fix` for
  jest / vitest / mocha (6/7 on `node --test`, which has no hook) [measured, 2026-09-14].
  Every verdict landed where the contract says: stub `red` with the failing test *attributed*
  (no build failure), regression `regressed`, hardcode `ESCAPE` exactly as on the Python
  fixture, `env_poison` built through the real hook with the graded file byte-identical.
- `"Controls: passed"` on a Go or JavaScript repository now means the load-bearing controls
  ran. On cobra with a `BARE` belt, `regression` will poison an adjacent package (`doc/`,
  `cobra/`) and `stub` will hollow the changed functions; `env_poison` will honestly read
  `not_constructible` on commits that change only plain functions — which is most of them —
  and that must be read as *"Go offers no such vector"*, not as a weak gate.
- A `regression` poison in Go is an `init()` panic, so `go test -json` reports a package-level
  `fail` with no test id; the Go runner records it as an *unattributed* belt failure and the
  grader still lands on `regressed` (belt 3 `False`). The row is correct but less legible than
  a named failing test; attributing package-level `fail` events (`<pkg>::<package>`) is the
  runner's change to make (`go_runner.parse`), not this module's.
- The Go stub blank-aliases imports the hollowed bodies orphaned and copies imports the
  appended signatures need; anything subtler (a type the gold also adds, a receiver type the
  parent lacks) reaches the compiler and comes back `not_constructible` with the error. That
  count is reported per row; it is the honest edge of a text-level transform.
- JavaScript `env_poison` on an ES-module repository graded under jest (babel-transformed
  exports are getter-only) may not take effect; the row then reads `caught by belt 2`, which
  is a weaker fact than a DQ. The vector is what it is; the fixture flavours prove it on CJS
  jest / mocha and ESM vitest. `node --test` has no hook at all — the reason says so.
- We must never: report a control that failed its compile / syntax check as anything but
  `not_constructible`; construct a Go `stub` with `panic`; let a `regression` poison sit
  inside the target scope and call the resulting `red` a belt-3 proof; read an `env_poison`
  escape as an oracle-weakness finding; or dispatch a language with no transform through the
  Python transforms.

## Alternatives considered

- **`go/ast` / a JS parser via the toolchain at generation time.** Rejected for the reasons in
  ADR-0009: more toolchain contracts in the generation path, unavailable under the docker
  executor at generation time, and the auditable reproduction story ("Python 3.12 + git")
  breaks. The compile / syntax check *after* generation is a one-shot toolchain call inside
  the same sandbox the tests already run in.
- **Go `stub` via `panic("stub")`.** Rejected: red for the wrong reason — a panic is not "an
  empty body the belt must reject", and it never reaches the assertion the control exists to
  exercise. Zero values via `*new(T)` compile for every type without the transform reasoning
  about types.
- **Go `regression` by breaking an exported function in the *same* package (the review's
  wording).** Rejected on measurement: the Go target scope is the whole package, so the break
  is seen by belt 2 and the row reads `red` → `not_constructible`, exactly the case the runner
  already special-cases. The adjacent *package* is the smallest unit belt 3 alone observes.
- **Go `regression` by hollowing an adjacent exported function instead of an `init()` panic.**
  Rejected: whether the adjacent package's tests observe the hollowed body cannot be known
  without running them, and an unobserved poison would grade `clean` and be recorded as a
  VIOLATION of the instrument — a false alarm. The `init()` panic is observable by
  construction (every test binary of the package fails before a test runs).
- **Go `env_poison` via `go.mod replace`.** Rejected: `replace` redirects *modules*, and the
  main module cannot be replaced; redirecting a dependency only helps when the target's
  behaviour comes from that dependency. Not a general vector, and the review's alternative
  (`init()` on package-level variables) is exactly what Go permits.
- **JavaScript `env_poison` via `NODE_OPTIONS=--require` in `.npmrc`.** Rejected: the runners
  invoke the tool binaries directly, not through `npm test`, so `.npmrc` never applies; and
  the executor owns the environment. The per-runner configuration file is the real vector.
- **Rewriting an existing `jest.config.js` / `.mocharc.yml` / `vite.config.ts`.** Rejected:
  merging JS or YAML textually is guesswork (a function config, an async config, a spread that
  breaks); JSON configs are merged, everything else is honestly `not_constructible` with the
  file named.
- **Counting `not_constructible` rows toward the gate.** Out of scope here; workstream A2
  withholds `deliver` while controls fail or are majority `not_constructible`, which is the
  routing-side half of this fix.
