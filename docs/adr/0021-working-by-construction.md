# ADR-0021 — "Clean" means working, by construction: the format step, the finish gate, belt 6 `api_stable`, and one switchboard

**Status:** Accepted (operator decision DL-054; built in the value wave, stream W)
**Date:** 2026-09-25
**Apparatus impact:** none while every mechanism is OFF (the default). Each is opt-in per run
or per repository and recorded on every row it touches, so rows with and without it never
pool silently. Making any of them a default is an apparatus change (bump
`APPARATUS_VERSION`) and needs the paired A/B this ADR asks for. Adds the failure kind `api`
(ranked between `budget` and `lint`) and amends ADR-0011's detectors (see *Runner-command
audit*).

## Context

A clean row says the repository's held-out tests accept the patch (belts 1–4) and, where the
repository configures one, that its own formatter and linter do (belt 5, ADR-0011). It does
not say a reviewer would merge it. Of the clean patches a person has reviewed, most would not
have been merged: 4 of 13 were mergeable; the rest failed on style or lint (4), on behaviour
or a feature not delivered (4), and on a public-API break or divergence (2) **[measured — n =
13 reviewed clean patches (the 10 review records in the operator's store on 2026-09-25 and
the 3 cobra patches in `docs/reviews/2026-09-13-critical-friend.md`), method: human review
records, apparatus 2.2]**. Two of those classes are mechanical: a formatter finding and an API
change are both decidable without a model.

The prior evidence this design respects: a distilled checklist beat an essay; verify-repair
inside the attempt was the strongest process lever in the programme that preceded this
product; context enrichment of the brief was falsified and a specification lever turned out
to be leakage — so anything added to what a builder sees carries operating facts only and
never text derived from the gold or the target tests; and a new behaviour that changes what a
builder sees is opt-in until a paired A/B shows a benefit **[hypothesis — each carried from
that programme, none yet measured under apparatus 2.2]**.

## Decision

1. **The format step** (`crb.core.formatting`). After an admissible build and before the
   grade, the repository's OWN formatter rewrites the changed non-test files, so the graded
   patch is the formatted one. The formatters are the belt-5 plan's formatter steps (`gofmt`,
   `ruff format`, `black`, `prettier`, `standard`, `cargo fmt`), black when the repository
   configures it, or the one it declares (`checks.formatter`). Never a formatter the
   repository does not use: none configured → skipped with a named reason
   (`no_formatter_configured`, `formatter_not_installed:<name>`, `disabled`,
   `no_changed_source_files`, `attempt_not_admissible`). The row's `format_step` label says
   what ran and how many files it changed; the pack's notes list the files.
2. **The finish gate** (`crb.core.finish_gate`). The brief carries the repository's own
   checks as a numbered checklist (the belt-5 plan, commands the repository evidences —
   `go vet ./...` where `.golangci.yml` enables `govet` — the declared `checks.commands`,
   and for a blind attempt the harness command without a scope); after the build the harness
   re-runs them and, when one fails that passed at the parent, gives the builder up to
   `finish_repair_turns` (default 1, at most 3) bounded repair calls with the failing output.
   `done` is accepted only when the gate passes. A command already red at the parent is
   `pre_existing` and never gates; a command that cannot run is an error and never gates;
   the belts, not the gate, decide `clean`. A blind checklist that would name a held-out test
   path or target scope is refused before any builder call (`finish gate refused: …`, a
   harness row, $0). The row's `finish_gate` label reads `before=fail:lint;repair=1;after=pass`.
3. **Belt 6 `api_stable`** (`crb.core.api_surface`). For every public unit the patch changed
   (a Go package, a Python module, a JS/TS module) the public surface — symbol → normalised
   signature — is read at the parent, in the trial and at the gold. Every trial change (added,
   removed, changed) must be one the gold made the same way; any other is a finding and the
   belt fails. Go by a declaration scanner cross-checked against `go/ast` in the tests; Python
   by `ast`; JS/TS by a declaration scanner recording parameter SHAPES (Go and JS parameter
   names are not API; Python's are). Non-public units (`internal/`, `package main`,
   `_private` modules, tool configs) and unparsable ones are skipped with a note; no unit
   evaluated → `None`, never a pass. The belt is recorded as the hashed row label
   `api_stable` (`true` / `false` / `none`) with `api_findings` (`kind:unit:symbol;…`), not a
   column: rows written without it hash byte-for-byte as before, and the ledger refuses a
   clean row whose label records `false` (a false-Q1 by the one route the columns cannot
   see). `GradeResult` refuses to be built clean with belt 6 `False`.
4. **The failure kind `api`**, in the ONE rule (`derive_failure_kind`): after `budget`,
   before `lint` — belts 1–4 held and belt 6 failed. `api` outranks `lint` because a formatter
   removes a lint finding mechanically, while an API break changes what callers compile
   against. `FailureSplit` / `CellStats` / the capability map count it (`api`, `n_api`) and it
   is a model-attributed kind (inside `model_n`).
5. **One switchboard: `RepoConfig.checks`** (`crb.core.checks`). `{format_step, finish_gate,
   api_stable, finish_repair_turns, formatter, commands}`, every switch OFF by default,
   validated at config time (an unknown key or a wrong type is refused, never a silent
   default), written through `PUT /repos/{name}` (the diff is the `repo.updated` event on the
   repository's audit trail) and overridden for one run by `params.checks` (run > repository >
   OFF). Every row of a run with a switch on, or of a repository with a non-default block,
   carries `labels.checks` = `fmt=1:repo;gate=0:default;api=1:run;cfg=<12-hex version>`; the
   apparatus stamp carries `extra.checks`. **This is the surface the prevention loop
   (ADR-0020) writes** to switch a mechanism on for a repository whose failure class recurs.

## Runner-command audit (amends ADR-0011's detectors)

`scripts/audit_runner_commands.py` compared what the runners derive with what the six live
repositories' own CI runs (`docs/reviews/2026-09-25-runner-commands-audit.md`). The gaps
fixed here, each pinned by `tests/test_runner_audit.py`:

- a frozen pre-commit `rev` (a sha with `# frozen: v0.15.9`, pallets/click) yielded no ruff
  pin, and a sha starting with a digit would have yielded `==<sha>`;
- a host ruff that does not satisfy the repository's pin now REFUSES its step (a harness
  error naming the pin — `LintTool.refuse`) instead of reading every patch as `lint`
  (mesh-client under `ruff ^0.2.0`, reviewed 2026-09-14);
- black's check mode joins belt 5 where the repository configures black (mesh-client's CI runs
  `make black-check`), on the host only;
- eslint and stylelint inherit the lint script's `--max-warnings` (both NHS repositories run
  `--max-warnings 0`, so a warning fails their CI); stylelint joins the plan where configured
  (nhsuk-frontend `lint:css`); prettier judges the stylesheets, JSON, Markdown and YAML it
  formats (`prettier --check .` in CI);
- the new inputs are test infrastructure (belt 1b): stylelint configuration, `[tool.black]`,
  and the `lint:js` / `lint:css` / `lint:types` / `lint:prettier` scripts.

These change which tools belt 5 runs for those repositories; `lint_run.detected` records the
difference on every pack (`eslint(max-warnings=0)+prettier+stylelint+tsc:lint:types`,
`ruff@0.16.7!pin>=0.2.0,<0.3.0`), as the `tsc` amendment to ADR-0011 did.

## Consequences

- A repository can be switched to "clean means working" without a code change, and the switch
  is on the audit trail and on every row.
- Rows remain comparable: nothing changes for a run with every switch OFF and a repository with
  no `checks` block.
- The finish gate costs up to `finish_repair_turns` extra builder calls per attempt, capped at
  the pre-flight repair's budget (10 turns, 15 tool calls, 300 s); both calls are one attempt's
  spend on the row.
- Belt 6 reads declarations, not types; a change to an imported type's definition in an
  unchanged package is not seen. It is a floor on API drift, not a certificate of design.
- **Not yet measured**: whether any of the three raises working changes per pound. The paired
  blind campaign (Phase B: the same tasks with the switches OFF and ON) decides; until then each
  stays OFF by default **[gap — no paired rows exist yet]**.

## Alternatives considered

- *Belt 6 as a ledger column.* Needs a store migration, a new belt set and an apparatus bump
  before a single measurement exists; the hashed label records the same fact with no change
  to rows written without it, and the ledger's invariant closes the false-Q1 route.
- *Ask the model to format and to check the API in the brief.* Advisory text is the weakest
  prevention; the harness can do both deterministically.
- *Rename the builder per switch (as the pre-flight does, `<name>+preflight`).* Fragments the
  cells the router reads every time the prevention loop switches something on; the row label
  records the arm instead, and a reader splits by it.
