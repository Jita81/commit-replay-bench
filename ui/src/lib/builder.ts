/**
 * The builder a screen runs with, chosen from what the deployment has configured.
 *
 * Navigation
 * ----------
 * What it is:   `builderChoice(health)` — the one rule for picking a builder from `/health`.
 * What it does: Reads the `builders` probe (presence only, never a value): an Anthropic key →
 *               Claude Code in production auth; only a Claude Code CLI login → Claude Code
 *               with `{auth: "cli"}`, the operator's own login, which the label says is a
 *               development and evaluation posture; NO credentialed builder but the test-only
 *               `fixture_gold` registered (the hermetic walkthrough and CI stacks) → the
 *               fixture, labelled a test-only instrument check that is never a builder
 *               measurement, at its known price of $0 per attempt; nothing usable → `null`, so
 *               the screen can disable its button and say an admin adds a provider key in
 *               Settings. A credentialed builder always outranks the fixture: an instrument
 *               check must never price or measure on the money page while a real builder is
 *               available. Measure and Factory share it so the two never disagree on what
 *               the deployment can run.
 * How:          A pure function over the `Health` value the `useHealth` hook returns.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
 * Works with:   ui/src/screens/Connect/MeasurePage.tsx (posts the choice with the replay and
 *               prices the estimate from `cost_per_attempt_usd` when it is known),
 *               ui/src/screens/Factory/FactoryPage.tsx (posts it with the factory run),
 *               ui/src/api/types.ts (`Health`), ui/src/api/hooks.ts (`useHealth`),
 *               src/crb/observability/probes.py (`probe_builders` — the `fixture_gold` flag
 *               follows the registry's own switch and its production belt)
 * Tested by:    ui/src/lib/builder.test.ts, ui/src/screens/Connect/MeasurePage.test.tsx
 * Touch when:   a builder or auth mode is added to the deployment's builders probe.
 */
import type { Health } from '../api/types'

export interface BuilderChoice {
  builder: string
  model: string
  /** Sent with the run when non-empty (`{auth: "cli"}`). */
  builder_config: Record<string, unknown>
  /** What the "Before you start" row says. */
  label: string
  /** True for a provider key; false for the operator's own CLI login (development and evaluation only) and for the fixture. */
  production: boolean
  /**
   * The builder's KNOWN price per attempt in USD, when the deployment knows it before any
   * attempt is made — only the test-only fixture, which spends nothing (`cost_known: true`,
   * `$0`). `null` for a real builder: its cost is measured, never assumed, so the estimate
   * reads the repository's measured mean or the documented planning range instead.
   */
  cost_per_attempt_usd: number | null
}

/** The `fixture_gold` label: says what it is and what it is not, on the money page and the run. */
export const FIXTURE_LABEL = 'fixture_gold · gold · test-only instrument check — replays the commit’s own source, never a builder measurement'

/** The builder to run with, from the `builders` health probe; `null` when the deployment has none usable. */
export function builderChoice(health: Health | undefined): BuilderChoice | null {
  const keys = health?.probes.find((p) => p.name === 'builders')?.data
  if (!keys) return null
  if (keys.anthropic) return { builder: 'claude_code', model: 'claude-sonnet-5', builder_config: {}, label: 'Claude Code · claude-sonnet-5 · API key (production)', production: true, cost_per_attempt_usd: null }
  if (keys.claude_code_cli) {
    return { builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, label: 'Claude Code · claude-sonnet-5 · the operator’s own CLI login (development and evaluation only)', production: false, cost_per_attempt_usd: null }
  }
  // only when no real builder is credentialed: the instrument check, at its known $0
  if (keys.fixture_gold) return { builder: 'fixture_gold', model: 'gold', builder_config: {}, label: FIXTURE_LABEL, production: false, cost_per_attempt_usd: 0 }
  return null
}
