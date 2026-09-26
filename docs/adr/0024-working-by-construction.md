# ADR-0024 — "Clean" means working, by construction: the format step, the finish gate, belt 6 `api_stable`, and one switchboard

**Status:** Accepted (operator decision DL-054; built in the value wave, stream W)
**Date:** 2026-09-25
**Apparatus impact:** none — no `APPARATUS_VERSION` bump and no new belt set; the checks
are a hashed stamp and a read filter, as ADR-0019 makes posture (§6). The format step and
belt 6 DO change what a clean row means when a repository or a run switches them on, and a
row graded with either on was, before this amendment, counted in the same cell as one graded
without **[measured — n = 1 reproduction: five rows with no `checks` stamp and three stamped
`api=1` with belt 6 recorded `true`, one cell key; `cell_stats` read n = 8 and the capability
map served one `bug.fix` cell of 8; method: `crb.core.ledger.cell_stats` and
`crb.core.capability.build_capability_map` on feat/value at `e2fc00b`, 2026-09-26;
apparatus 2.2]**. So every row carries its arm (§6), no reader reduces a cell across two arms
(`cell_stats` refuses), and every reader picks one. A bump would not have kept the two apart:
the switches are per repository and per run, so rows of both arms would share any version.
It would also have split the default rows — which mean exactly what they meant under 2.2 —
from their own history. The finish gate is not on the arm: the belts, not the gate, decide
clean, so it pools like the budget profile and the playbook lines, recorded on the row.
Making any switch a default IS an apparatus change and needs the paired A/B this ADR asks
for. This ADR adds the failure kind `api` (ranked between `budget` and `lint`) and amends
ADR-0011's detectors (see *Runner-command audit*). It lands after PR #56 (ADR-0019, which
takes apparatus 2.3) and names no version of its own.

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
6. **The arm: a stamp and a read filter, never a pool.** A row's arm (`off`, `fmt`, `api` or
   `fmt,api`; `GradeRow.checks_arm`) is read from its hashed `checks` stamp and from belt 6's
   own label, so a row written before the switchboard is `off` and no row is re-derived. A
   run's arm is `ResolvedChecks.arm`, the same word. `crb.core.ledger.rows_for_checks` keeps
   one arm; there is no pooled view. `cell_stats` refuses rows of two arms
   (`ChecksArmsPooled`), so no reader can reduce a mixed cell, and `all_cell_stats` returns
   one cell per key and arm. The served readers use the arm the repository's next run grades
   under, the same resolution the worker applies (`crb.server.prevention_state.
   current_checks_arm`). That covers the capability map and `/routes` (where `?checks=<arm>`
   selects another arm), the delivery gate and the Factory page's cell routes, the Learn
   plans, the forecast and the review cells. The worker's calibrated budget and escalation
   yield read the run's own arm. The CLI (`crb route`, `crb learn strengthen|remeasure`)
   takes `--checks` (default `off`), and `crb ledger stats` prints one cell per key and arm.
   The scorecard keys its cells and its prospective routing by arm. The abstract export
   carries `off` rows only: a switched-on arm is a local experiment until an A/B makes it
   the default, and an abstract cell has no field that could keep two arms apart.

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
  no `checks` block, and a row graded with the format step or belt 6 on is only ever counted
  with rows of its own arm (§6).
- Switching the format step or belt 6 on for a repository starts its cells afresh. By a
  person or by the prevention loop (`learning.auto_apply: config`), the map, the routes and
  the delivery gate then read the new arm, which has no rows yet, so its cells calibrate
  until it is measured. The old arm's rows stay readable with `?checks=off`. A cell never
  licenses a delivery on rows graded by an instrument the repository no longer uses.
  Switching the finish gate changes no cell.
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
- *Rename the builder per switch (as the pre-flight does, `<name>+preflight`).* The builder is
  a cell-key field, so the full cells would split, but every projection that drops it (the
  class × size map the delivery gate reads) would still pool the arms. The arm is a read
  filter instead, applied before any projection (§6).
- *Bump `APPARATUS_VERSION` (to 2.4, after ADR-0019's 2.3) and the belt set.* Rows of both
  arms would carry the same version, because the switches are per repository and per run, so
  the bump alone keeps nothing apart. It would also retire every default row's history for a
  meaning that did not change. The version moves when a switch becomes a default.
- *Put the finish gate on the arm.* It changes what the builder does before it says done, never
  a belt, so a gate-on clean row means what a gate-off one means. Splitting on it would reset a
  repository's cells whenever the loop applies its most-used process lever.
