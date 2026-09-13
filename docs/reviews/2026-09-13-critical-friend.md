# Critical-friend review — is the AI's code actually good, and is our governance of it honest?

**Date:** 2026-09-13 · **Scope:** Commit Replay Bench v2 (`reboot/v2` @ `95a4f2e`) run live against three public repositories (spf13/cobra, pallets/click, koajs/koa) with Claude Sonnet 5 via Claude Code, plus the *Automated Agile v2 Playbook* (Aug 2026) that describes the process. · **Lens:** an AI-governance community that has to decide what this evidence licenses.
**Reviewer:** Claude Opus 5, acting as critical friend at the operator's request. This review was itself produced by an AI; treat it as a structured set of claims to verify, not a sign-off.

---

## 1. Verdict in one paragraph

The *instrument* is honest: across every grade row written today, false-Q1 = 0 (no row credited clean with a failed belt), the ledger's hash chain verifies, and every failure — including the instrument's own — is recorded as not-clean with its reason. The *code the AI produced* is competent and green against the maintainers' own tests, but **not one of the three "clean" cobra patches I examined would have been merged as-is by a careful maintainer**: one fails the repository's own `gofmt` lint, one has two behavioural gaps I exposed with two 15-line tests written in five minutes, one silently changes the public API surface. The *data* is far too thin to license anything beyond "keep measuring": n = 3–9 per cell, no cell routes to `deliver`, and **13 of the 29 replay rows failed because of our harness, not the model**. The *governance document* (the playbook) still publishes a specification-value claim that the underlying research corrected a month before the playbook's date. The honest summary for a governance community is: the floor holds; the ceiling is unmeasured; human review of *what was accepted* — not just *that* it was accepted — is still mandatory; and our own process needs the same discipline we are selling.

---

## 2. What I actually looked at

| Evidence | Source |
|---|---|
| 29 replay grade rows (cobra 8, click 12, koa 8) + 4 review rows, Sonnet 5, sighted + blind | live stack ledger (`grades`, append-only, chain verified) |
| Oracle-strength runs: click 86 mutants, koa 31, cobra 49 | `runs.counts_json` |
| Negative-control runs: cobra 56 rows, koa 56, click 49 | run event streams |
| 4 AI patches re-built with kept worktrees, diffed against the maintainers' real commits, then `gofmt`/`go vet`/reviewer-written probe tests | `scratchpad/review/cobra/` |
| One evidence pack for a clean row, field by field | `evidence.body_json` |
| The playbook's seven plays and evidence table vs *The Quality Floor* essay v3.0 | uploaded `.docx`; `docs/book/the-quality-floor.essay.md` |
| The product: 32k LOC Python, 7.8k LOC UI, 1,482 tests, 9 ADRs, 74 commits in one day, 11 of them by an unattended agent identity | repo |

Everything below cites its n. Where I say "would not be merged" I mean I ran the check, not that I suspect it.

---

## 3. Is the code actually good? — four patches, read line by line

I re-ran the first three gold-clean cobra tasks with worktrees kept so a human could read the AI's diff next to the maintainer's. One was blocked by our own guard (§5.4); I fixed the guard and re-ran it, so four AI patches are on the table.

### 3.1 cobra #2241 — "Flow context to command in SetHelpFunc" (XS, bug fix)

| | Maintainer | Sonnet 5 |
|---|---|---|
| Fix | `if cmd.ctx == nil { cmd.ctx = c.ctx }` — fill only if unset | `cmd.SetContext(c.Context())` — unconditional overwrite |
| Grade | gold clean | **clean**, $0.20, 245 s, gofmt/vet clean |

**Finding.** Green, but semantically different: the AI's version clobbers a context the caller may already have set on the child. The maintainer's test cannot distinguish the two. A reviewer would ask "why overwrite?" — a one-line comment, but a real one. *Mechanically clean, semantically weaker.*

### 3.2 cobra #1559 — "Remove the default completion cmd if it is alone" (M, behaviour change)

| | Maintainer | Sonnet 5 |
|---|---|---|
| Approach | Add the command, then `c.Find(args)` to see whether it is being invoked; remove it if not | Inspect raw `args[0]` before creating the command |
| Grade | gold clean | **clean**, $0.63, 185 s, 840k input tokens |

**Findings (all verified by running them):**
1. `gofmt -l` flags `completions.go` — the AI's doc-comment indentation is not gofmt-canonical. cobra's `.golangci.yml` enables `gofmt`. **The repository's own CI would have rejected this patch before any human saw it.**
2. `prog --verbose completion bash` on a single-command CLI → `unknown command "completion"` with the AI's patch; a bash script with the maintainer's. The AI checked `args[0]` literally; cobra's `Find` strips flags first. **User-visible regression the held-out test does not cover.**
3. A root whose only other subcommand is a user-supplied `help` gets the completion command added by the AI's patch and not by the maintainer's. Edge case, but the maintainer explicitly reasoned about it and the AI did not.

On the plus side the AI *updated the doc comment* the maintainer left stale, and avoided the add-then-remove churn. It is a plausible first draft from a mid-level engineer. **It is not a mergeable patch, and the oracle said it was.**

### 3.3 cobra — "The default ShellCompDirective can be customized" (S, feature)

| | Maintainer | Sonnet 5 |
|---|---|---|
| Field | `DefaultShellCompDirective *ShellCompDirective` (exported) | `defaultShellCompDirective` (unexported) + setter + helper |
| Grade | gold clean | **clean**, $0.31, 72 s, gofmt/vet clean |

**Finding.** `CompletionOptions{DefaultShellCompDirective: &d}` — the struct-literal form every other field in that struct supports — does not compile against the AI's version (verified with `go vet`). The PR's own test only used the setter, so both pass. The AI's code is arguably *better* encapsulated and better documented than the gold; it is also *inconsistent with the surrounding API*, which is exactly the kind of thing a maintainer, not a test, catches. *Public-API divergence invisible to the oracle.*

### 3.4 cobra #2241 first attempt — blocked by us

First run: not clean, $0.16, 41 s, `error: archaeology: could not parse the command safely (unbalanced substitution)`. The AI had run `grep -n "func (c \*Command) Context\|preRun(ctx" command.go`. Our guard read the `(` inside a quoted grep pattern as an unbalanced sub-shell and killed the build. Fixed in `95a4f2e` (guard now honours shell quoting; regression test added). This is the **third guard false-positive class found today** (after `$(pwd)` / `$(find …)` and the missing environment prefix).

### 3.5 What this means

Three for three "clean" patches carry a reviewer-visible defect or divergence — and these are XS–M changes in a well-tested, idiomatic Go library with the strongest oracle we measured (0.94). "Clean" here means precisely what ADR-0001 says it means: *the four mechanical predicates held*. It does not mean mergeable, idiomatic, API-consistent, or lint-clean. The playbook says this in words (§05 "mechanical vs semantic"). The capability map, the sign-off screen and the word "deliver" in the routing rule do not say it loudly enough.

---

## 4. What the data honestly tells us

### 4.1 The numbers, with n

| repo | mode | n | clean | red (model) | error (harness/protocol) | mean $ | mean s |
|---|---|---|---|---|---|---|---|
| cobra | sighted | 5 | 4 | 1 | 0 | 0.24 | 62 |
| cobra | blind | 3 | 2 | 1 | 0 | 0.39 | 122 |
| click | sighted (run 1) | 5 | 0 | 0 | 5 | 0.43 | 271 |
| click | sighted (run 2, env fixed) | 4* | 4 | 0 | 1 | — | — |
| click | blind (run 1) | 3 | 0 | 0 | 3 | 0.38 | 123 |
| koa | sighted | 5 | 3 | 0 | 2 | 0.17 | 67 |
| koa | blind | 3 | 1 | 0 | 2 | 0.35 | 116 |
| **all** | | **29** | **14** | **2** | **13** | | |

\*click run 2 wrote 5 rows: 4 clean, 1 guard false positive (`$(pwd)` — old guard build on the live worker). Total spend $9.56; 79 builder-minutes. Every row: `capability_class = bug.fix`. False-Q1 violations: **0** (checked directly against the belts, not the flag).

### 4.2 Six honest readings

1. **The floor held.** Zero clean rows with a failed belt, across 29 live rows, 4 review rows, 161 negative-control rows and every gate. This is the one number the whole design defends and it is intact.
2. **The instrument, not the model, produced most of the failures.** 13 of 15 non-clean rows are harness or protocol errors: an unprovisioned environment that led the model to `pip install` (8 rows), guard false positives on ordinary shell (`$(find …)`, `$(pwd)`, quoted parentheses — 4 rows), and `git stash` (1 row, arguably a legitimate protocol refusal). Only **2 rows** are the model failing the task. The ledger records this honestly (fail-closed, reason in `error`), but a naive "clean rate" of 48% would badly misdescribe the model, and an honest "≈ 88% when the harness works" would badly overclaim from n = 16.
3. **Nothing routes to `deliver`, and nothing should.** The rule needs n ≥ 10 ∧ point ≥ 0.90 ∧ Wilson-low ≥ 0.80 ∧ false-Q1 = 0 ∧ oracle ≥ 0.8. The largest cell has n = 7. At n = 5 with 4 clean the Wilson lower bound is 0.38. The product correctly says `calibrate` everywhere. Anyone reading today's map as capability evidence is reading noise.
4. **The class axis is degenerate on these repos.** The classifier is path-based; a code file outside recognised `routes/`, `models/`, `migrations/` … patterns falls through to `bug.fix`. cobra #1559 is a behaviour change and the ShellCompDirective task is a feature; both are labelled `bug.fix`. The cell key's "class" therefore carries no information on library repos. This is not what the essay measured (the census used labelled classes) and it must be fixed before any per-class claim is made from this product.
5. **Oracle strength is a lower bound on weakness, not a certificate of coverage.** cobra's 0.94 comes from text-level mutators that produce many uncompilable mutants (14 of 21 in the M cell were excluded). The #1559 task sits in a cell scored 0.95 and its test missed two behaviours a reviewer found in minutes. Mutation score measures whether the tests notice *crude* breakage; it says nothing about flag handling, API shape or style.
6. **The negative-control gate is thin outside Python.** On cobra and koa only 3 of 7 controls are constructible (gold, noop, test_tamper); the load-bearing ones — regression, stub, hardcode-cheat, env-poison — are Python-AST-only and read `not_constructible`. "Controls: passed" on a Go or JS repo currently means "the three easy ones passed". On click, where all 7 run, the gate **failed** (regression 7/7 violations because the suite is too large to run in full and the belt scope is TARGET_ONLY, so belt 3 is blind) — and the replay runs proceeded anyway and produced clean rows the capability map shows without that caveat.

### 4.3 A finding I disagree with the product's own docs about

On click, the `env_poison` control **escaped 3 of 7 times**: an identity edit to the source plus a new root `conftest.py` that execs the gold module at collection time graded *clean*. The product's docstring calls this a "measured oracle escape — a finding, never a violation — not a grader bug". I think that is the wrong call. Belt 1 protects the *test files*; the oracle is the *test run*, and for pytest that run includes `conftest.py`, `pytest.ini`, `pyproject.toml [tool.pytest]`, `sitecustomize.py`, `.pth` files and `PYTHONPATH` (for JS: `jest.config.*`, `vitest.config.*`, `.mocharc`, `package.json#jest`). A builder that adds any of those has modified the oracle and should be disqualified under belt 1, not scored as "the repo's tests are weak". Until that is closed, a motivated (or merely confused) agent can earn a clean grade by poisoning collection. **This is the most important hardening item in this review.**

---

## 5. The playbook, play by play — what exists, what the data says, where the human goes

| Play | What the product does today | What the data says | Gap / required human check |
|---|---|---|---|
| **01 Context architecture** | Benchmark mode: none (the commit message + repo). Factory mode: frozen, hashed backlog. | Essay v3.0: implementation-blind facts ≈ +0 over the bare message; checklist ≈ +4; the +23 was the author having seen the answer. Structural/API-shaped facts help; exact values do not. | The playbook's evidence table still says "signed facts + checklist raised 33/48 → 46/48 — precise facts outperform generic context". **That claim was corrected on 2026-07-09; the playbook is dated August 2026.** Reframe context packs as *accountability and shape*, not reproduction lift. Human: a context owner signs *shape* facts; nobody signs values they derived from the answer. |
| **02 Classification & DoR** | Path-based class; size = source churn tier; oracle strength per cell; factory DoR = structural gaps only. | Class axis degenerate on library repos (all `bug.fix`). Size is churn, a proxy for blast radius, not risk. Novelty and residual risk: not measured anywhere. | Class must be intent-derived (LLM-labelled with a human-audited sample, or maintainer labels) before per-class routing is trusted. Human: classification audit on a sample every run; risk classing (clinical / financial / safety) stays human. |
| **03 Executable spec & oracle** | Held-out tests are the oracle; mutation strength (AST for Python, text-level for Go/JS/JVM/Rust); adequacy gate ≥ 0.8 for `deliver`. | Strength ≥ 0.8 did not prevent a patch with two behavioural gaps from grading clean. Text mutators discard most of their mutants on Go. | Treat strength as a *floor on test quality*, not a licence. Human: for any class that is to be auto-delivered, a test engineer reviews the target tests once — do they encode the behaviour a maintainer would insist on (flags, defaults, API shape)? |
| **04 Controlled generation** | Guards (no test edits, no history, no network, no installs), budgets, model identity recorded; sighted/blind modes. | Guards caused 12 of 29 rows to fail; three false-positive classes fixed today. Transcript not retained (`transcript_ref = ''`). | Guards need their own regression corpus of *honest* shell (we now have one growing in `tests/`). Refusals must be labelled *instrument* vs *builder* so refusal-rate is meaningful. Human: read a sample of refusals weekly; a rising refusal rate is a product bug until proven otherwise. |
| **05 Independent grading** | Four belts, false-Q1 = 0 at write, DQ on tamper/malformed oracle, fail-closed on harness error. | Held perfectly. But: belt 1 scope too narrow (§4.3); belt 3 blind under TARGET_ONLY (click); controls thin outside Python (§4.2.6); 3/3 clean patches semantically divergent (§3). | **Human review of the accepted diff is not optional at this maturity.** The pack holds `diff_sha256` + stats, not the patch — a human cannot re-examine what was accepted. Add bounded, redacted patch retention (opt-in for benchmark; mandatory for forward mode where the PR *is* the artefact). |
| **06 Routing, refusal, escalation** | One published rule; `calibrate` everywhere today; sign-off screen. | Correctly refuses to route anything. W3-C found sign-off accepts thin cells. The controls-gate verdict does not withhold `deliver`. | Wire controls-gate failure and `not_constructible`-majority into the route as `human`. Sign-off must show n, CI, oracle, controls verdict and *the reviewer's own sample findings* before an approver can sign. Human: the approver role must be a person who has read at least one accepted diff in that cell. |
| **07 Evidence ledger** | Append-only + hash chain (DB triggers + JSONL), chain verified; abstract-cell export only. | Verified. Packs are predicate evidence, not code evidence. | Add "what was accepted" to the pack (retained patch, or a pointer to the PR). Add a *review* row type so a human's post-hoc verdict on an accepted change is itself ledgered against the row — today human findings have nowhere to live. |

---

## 6. Governance of our own process — the uncomfortable part

We are proposing a governed production line to a regulated customer. The product was built in one day by parallel AI agents under an AI orchestrator, with the operator steering and no independent human reading of the 32k lines. Applying the playbook's own standard to us:

| Playbook expectation | What we did | Honest grade |
|---|---|---|
| Independent evidence, not self-assessment | 1,482 tests, ruff/mypy/import-linter/negative-control gates, live runs on real repos. | **Good** — the gates are real and they caught real defects today (5 runner defects, a Maven false-green, three guard classes, token accounting). |
| Human review of every accepted change | None of the 74 commits was reviewed by a human before landing on `reboot/v2`. The reviewer of the agents' work was another AI (me). | **Fail by our own standard.** Mitigation before any customer sees it: a human review of the *core* (grade, ledger, controls, guards — ~4k lines) at minimum. |
| Fail-closed guards; process defects treated as such | An agent's walkthrough script `rm -rf`'d the live stack (DB, env files, secrets). Nothing in the product was harmed; the incident was caught by the operator noticing, and the fix was a paragraph in the agents' brief. | **Weak.** By the operator's own prevention hierarchy, advisory context is the weakest tier. The structural fix (agents get a throwaway `CRB_HOME`, refuse to run if one is set) now exists in `scripts/walkthrough.sh` — but it is a script convention, not a sandbox. |
| Secrets never in evidence or logs | The OAuth token was pasted into the chat by the operator and placed in a mode-600 file; it never entered the ledger, packs or git. It did transit the conversation transcript. | **Rotate it.** Then build the UI path the operator asked for so a token never transits a chat again. |
| Claims carry scope and caveats | ADRs, EVIDENCE-AND-CLAIMS, [measured]/[hypothesis] tags. The essay corrected its own headline finding. | **Good** — except the playbook (§5, play 01) has not caught up with the correction. |
| Evidence expires with the apparatus | Apparatus stamp on every row; census rows tagged `v3-legacy`, never blended. | **Good.** |
| Nothing auto-delivers on thin evidence | Nothing does. | **Good.** |

The pattern: the *mechanical* governance is strong and honest; the *human* governance — review of accepted code, independent reading of the instrument, incident prevention — is where we are asking the customer to do what we have not yet done ourselves.

---

## 7. Where human checks are non-negotiable (as of this evidence)

1. **Reading the accepted diff** for every change in any cell that is not yet `deliver` — which today is every cell. Not sampling: every one. (Three of three had findings.)
2. **Lint/CI of the target repo** as a fifth belt, mechanically — `gofmt`, `golangci-lint`, `ruff`, `eslint`, `tsc` — because "clean" currently means the tests, not the repo's own definition of acceptable. Cheap, deterministic, and would have caught §3.2 finding 1.
3. **Classification audit** on a sample per repo until the class axis is intent-derived.
4. **Oracle review by a test engineer** for any class proposed for `deliver`: not the mutation score — the tests themselves.
5. **Refusal triage**: every harness/protocol error read by a person until the instrument-caused share is < 5% of rows (today 45%).
6. **Sign-off** only by a named person who has read at least one accepted diff in that cell, with the controls-gate verdict on the screen.
7. **Risk classing** (clinical, financial, safety, PII) stays human in perpetuity — the product has no notion of it, and should not pretend to.

---

## 8. Actions, in priority order

| # | Action | Kind | Owner |
|---|---|---|---|
| 1 | Extend belt 1 to *test-infrastructure* files (conftest / pytest config / sitecustomize / .pth / jest+vitest+mocha config / package.json test sections): any change → DQ. Re-run click controls; `env_poison` escapes must go to 0. | product, poka-yoke | crb core |
| 2 | Add a **repo-lint belt** (run the repo's own formatter/linter on changed files; failure → not clean). Record as belt 5 with its own apparatus version bump. | product | crb core |
| 3 | Retain the accepted patch (bounded, redacted) in the evidence pack — opt-in for benchmark, mandatory in forward mode. Add a `review` row type for human post-hoc verdicts. | product, ADR-0006 amendment | crb store |
| 4 | Label every non-clean row `failure_kind ∈ {builder_red, protocol, harness}` and show the split everywhere a rate is shown. Capability map withholds `deliver` while controls fail or are majority `not_constructible`. | product | crb core + UI |
| 5 | Intent-derived change class (labelled, with a human-audited sample per repo); keep the path class as a separate field. | product | crb core |
| 6 | Port the four Python-only negative controls to Go/JS (regression via adjacent-package edit; stub via body replacement; hardcode via literal parsing; env-poison via `init()` / `setupFiles`). | product | crb oracle |
| 7 | Correct the playbook's evidence table: replace the 33→46/48 row with the v3.0 finding (blind-authored facts 68.8% ≈ bare 72.9%; informed 91.7% = leakage; checklist ≈ +4; structural facts help, values do not). | governance doc | operator |
| 8 | Human review of `crb.core.{grade,ledger,oracle.controls}` and `crb.builders.base` by an engineer who did not build them, before any external demonstration. | process | operator / Kainos |
| 9 | Rotate the Claude Code OAuth token; build the UI/`crb doctor` path for supplying it. | security | operator |
| 10 | Run each repo to n ≥ 10 per cell with the fixed harness before quoting any rate; quote Wilson intervals only. | measurement | operator (credits) |

---

## 9. What the evidence *does* license today

- Saying: "We have an instrument that grades AI code changes against a repository's own held-out tests, fails closed, cannot record a false pass, and proves it on 161 negative-control rows and every live row so far." **[measured]**
- Saying: "On three public libraries, Sonnet 5 reproduced 14 of 16 changes the harness let it attempt, at $0.17–0.43 and 1–4 minutes each." **[measured, n = 16, single run, no CI]**
- Saying: "Mechanically clean is not mergeable: in a 3-patch sample, 3 had reviewer-visible defects or divergences." **[measured, n = 3]**
- **Not** saying: any per-class capability, any `deliver` routing, any semantic-correctness rate, anything about NHS code (the three NHS repos are validated but not yet run).

---

### Appendix A — commands a governance reviewer can re-run

```bash
# false-Q1 against the belts, not the flag
sqlite3 $CRB_HOME/crb.db "select count(*) from grades where clean=1 and (tests_unmodified is not 1 or target_green is not 1 or no_new_failures is not 1 or source_changed is not 1);"
# failure split
sqlite3 $CRB_HOME/crb.db "select repo, mode, count(*), sum(clean), sum(error<>''), sum(error='' and clean=0) from grades where process_step='replay' group by 1,2;"
# hash chain
crb ledger verify
```

### Appendix B — the reviewer probes for cobra #1559 (both fail on the AI patch, both pass on the maintainer's)

```go
func TestReviewCompletionAfterFlagNoSubcommands(t *testing.T) {
	rootCmd := &Command{Use: "root", Args: NoArgs, Run: emptyRun}
	rootCmd.PersistentFlags().Bool("verbose", false, "")
	output, err := executeCommand(rootCmd, "--verbose", "completion", "bash")
	if err != nil { t.Fatalf("expected completion script, got error: %v", err) }
	if !strings.Contains(output, "bash completion") { t.Fatalf("no script: %.200s", output) }
}

func TestReviewOnlyHelpSubcommand(t *testing.T) {
	rootCmd := &Command{Use: "root", Args: ArbitraryArgs, Run: emptyRun}
	rootCmd.AddCommand(&Command{Use: "help", Run: emptyRun})
	if _, err := executeCommand(rootCmd, "foo"); err != nil { t.Fatalf("root should accept args: %v", err) }
	if c, _, _ := rootCmd.Find([]string{"completion"}); c.Name() == "completion" {
		t.Fatalf("completion command was added although help is the only other subcommand")
	}
}
```
