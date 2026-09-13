# Decision log

One line per decision taken by the owner/operator. Append-only; newest at the bottom.
Design decisions with rationale live in the [ADRs](adr/README.md); this log records *that*
a choice was made, by whom, and when. Format: `DL-NNN · YYYY-MM-DD · who · decision · consequence / link`.

| Id | Date | Who | Decision | Consequence / link |
|---|---|---|---|---|
| DL-001 | 2026-09-13 | Operator | **Scope = benchmark + forward-mode loop.** The carve-out is the commit-replay instrument, the ledger, routing, and (P6) a factory that manufactures new work under the same governance — *not* Athena's discovery / inception pipeline. | Plan §"Product shape"; README "What it is not". |
| DL-002 | 2026-09-13 | Operator | **Repo = reboot `Jita81/commit-replay-bench`** (private). The June 2026 v1 contents are superseded; the old head is tagged `v1.0.0-legacy`; work lands on `reboot/v2` via branch + PR, never by force-replacing history. | CHANGELOG 2.0.0a0; README status. |
| DL-003 | 2026-09-13 | Operator | **Deployment = self-hosted in the customer's tenant, BYOK.** Single-organisation, multi-repo; no SaaS billing or workspace plumbing; OIDC (Entra ID) + local admin bootstrap. | ARCHITECTURE §2; ADR-0007 (nothing leaves but abstract cells, opt-in). |
| DL-004 | 2026-09-13 | Operator → architect | **Builders left to the architect.** Decision taken: a pluggable registry with `claude_code` (agentic), `openai_agent` (Azure OpenAI / Cerebras / local) and `editblock` as first-class adapters; Copilot later behind the same interface; sighted and blind modes. | ADR-0004. |
| DL-005 | 2026-09-13 | Architect | **One routing rule.** The published rule (`n ≥ 10 ∧ point ≥ 0.90 ∧ Wilson-low ≥ 0.80 ∧ false_q1 = 0 ∧ oracle ≥ 0.80 when measured`) gates; the upstream SPC rule (`σ ≤ 0.10, n ≥ 20`) becomes advisory. | ADR-0003; `crb.core.routing` (`routing.v1`). |
| DL-006 | 2026-09-13 | Architect | **false-Q1 = 0 enforced at write**, not read; a clean row must carry an evidence-pack hash ("no pack ⇒ no Q1"). Four belts; legacy three-belt census rows reported separately. | ADR-0001; ADR-0002; EVIDENCE-AND-CLAIMS §5. |
| DL-007 | 2026-09-13 | Architect | **Sandbox is Docker, fail-closed**; a run stops rather than degrades to host execution. Builder runs in a throwaway host worktree in P3; containerised builder with egress allowlist in P5. | ADR-0005; OPERATOR §7. |
| DL-008 | 2026-09-13 | Architect | **Zero raw retention by default**: diffs as hash + stats, test output redacted and capped, transcripts opt-in with a retention window. | ADR-0006. |
| DL-009 | 2026-09-13 | Architect | **`crb.core` is stdlib-only; layers depend downward only; enforced by import-linter in CI.** Not-yet-existing layers are parenthesised (optional) until their package lands. | ADR-0008; CONTRIBUTING. |
| DL-010 | 2026-09-13 | Operator (pending) | **Licence to be confirmed.** `LICENSE` is MIT inherited from v1; the v2 product licence has not been decided. | README "Licence"; ARCHITECTURE §9.2. |
| DL-011 | 2026-09-13 | Coordinator | **import-linter config fix on `reboot/v2`**: `include_external_packages = true`; not-yet-existing layers parenthesised (optional); `crb.observability` made mandatory the moment its package landed. | CHANGELOG *Unreleased*; CONTRIBUTING "Optional-layer convention". |
