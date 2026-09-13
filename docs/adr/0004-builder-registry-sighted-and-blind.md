# ADR-0004 — Builder registry; sighted and blind modes

**Status:** Accepted
**Date:** 2026-09-13
**Apparatus impact:** none for the grader; `mode` is recorded on every `GradeResult`, `GradeRow` and `BuilderRef`

## Context

The census builder upstream was Claude Code *workflow JavaScript*; no Python builder adapter
existed. Portable pieces existed for an OpenAI-compatible tool loop
(`manufacture/agentic_generate.py`, `scripts/model_repro_bench/gptoss_agent.py`) and a
single-shot SEARCH/REPLACE edit-block generator (v1 `generate.py`,
`commit_replay.parse_edit_blocks`). `[measured]` upstream: the agentic process (tools, run
tests, iterate to green) with a capable model was the dominant lever on hard commits
(replicated across three experiments), while a weak model gained nothing from the same
process — so the product must be able to run several builders under one contract and
compare them on the same ledger.

The design customer runs in its own tenant: Azure OpenAI in-tenant, a local model, or
Claude Code must be first-class, and the builder's view of the task must be controlled so
that no builder can see a test it could weaken.

## Decision

1. **A `Builder` protocol and a registry** in `crb.builders` (P3). A builder receives a
   `Workspace` (a fresh parent worktree), the `TaskSpec` fields it is allowed to see for the
   mode, and a budget (turns, tokens, cost, wall-clock); it returns a `BuilderRef`
   (`crb.core.evidence.BuilderRef`: name, model, provider, mode, attempts, turns, tokens,
   cost, latency, opt-in `transcript_ref`, budget, note). Adapters:
   - `claude_code` — Claude Agent SDK / `claude -p`, with the census prompt rules (no test
     edits, no git archaeology, no network, tool budget);
   - `openai_agent` — OpenAI-compatible tool-calling loop (Azure OpenAI, Cerebras, local);
   - `editblock` — single-shot SEARCH/REPLACE for cheap models.
   Copilot and others can be added behind the same interface.
2. **Two modes**, recorded as `GradeResult.mode ∈ {"sighted", "blind"}`
   (`crb.core.grade.MODES`):
   - `sighted` — the target tests are overlaid **before** the build; the builder knows what
     must pass. Belt 1 proves it left them byte-identical.
   - `blind` — the builder sees the parent checkout and the task description only; the
     held-out tests are overlaid **at grade time** (`grade()` calls `ws.overlay_tests`).
     Belt 0: any test file touched before the overlay disqualifies the trial.
3. **In neither mode** does the builder receive the belt scope, the baseline failing set,
   the runner's command, or the grader. It may run whatever tests it finds in the worktree;
   the regression belt is computed by the grader from the task, not from the builder's
   report.
4. **Tamper guard**: the grader re-hashes the target tests against the commit's own version
   (`Workspace.tests_byte_identical`) on every grade; a builder's self-report is never
   consulted.
5. **Budgets and an escalation ladder** are builder-agnostic and recorded on the
   `BuilderRef.budget` mapping; exhausting a budget is a recorded failure, never an
   unbounded retry. A cost meter accumulates tokens and USD per attempt; the ledger row
   carries `attempts`, `tokens_in/out`, `cost_usd`, `latency_s`.
6. **Builder isolation**: v1 of P3 runs the builder in a throwaway worktree on the host;
   `[aspiration]` P5 moves it into a container whose egress is restricted to the configured
   model endpoint. Until then the operator guide states the limitation.

## Consequences

- Any builder can be measured on the same ledger and routed by the same rule; the cell key
  carries `builder`, `model`, `provider`, so results never blend across them.
- Sighted and blind results are different populations (`mode` is on every row); a sighted
  rate must never be quoted as a blind capability (see EVIDENCE-AND-CLAIMS).
- A builder that edits a test to pass is disqualified, not failed — so a systematically
  cheating builder shows up as a high DQ count, which the UI displays beside `n`.
- Adapters carry their SDKs as optional extras (`[claude]`, `[openai]`); the core stays
  stdlib-only (ADR-0008).
- Live builder smoke tests need credentials and are marked `live` (skipped in CI).

## Alternatives considered

- **One builder (Claude Code only).** Rejected: the customer's tenant may not permit it,
  and the product's value is comparing builders on measured evidence.
- **Give the builder the belt scope so it can self-check regressions.** Rejected: the belt
  is the instrument; a builder that knows the instrument can special-case it.
- **Blind mode by hiding tests via `.gitignore` or file permissions.** Rejected: fragile;
  overlaying at grade time plus belt 0 is exact.
- **Let the builder report its own pass/fail.** Rejected on principle — the grader, not the
  builder, decides. A self-report is correlated judgement, not independent evidence
  ([EVIDENCE-AND-CLAIMS §8](../EVIDENCE-AND-CLAIMS.md#8-validation-principles-we-inherit)).
