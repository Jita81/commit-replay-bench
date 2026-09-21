/**
 * The builder a screen runs with, chosen from what the deployment has configured.
 *
 * Navigation
 * ----------
 * What it is:   `builderChoice(health)` — the one rule for picking a builder from `/health`.
 * What it does: Reads the `builders` probe (presence only, never a value): an Anthropic key →
 *               Claude Code in production auth; only a Claude Code CLI login → Claude Code
 *               with `{auth: "cli"}`, the operator's own login, which the label says is a
 *               development and evaluation posture; nothing usable → `null`, so the screen can
 *               disable its button and say an admin adds a provider key in Settings. Measure
 *               and Factory share it so the two never disagree on what the deployment can run.
 * How:          A pure function over the `Health` value the `useHealth` hook returns.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
 * Works with:   ui/src/screens/Connect/MeasurePage.tsx (posts the choice with the replay),
 *               ui/src/screens/Factory/FactoryPage.tsx (posts it with the factory run),
 *               ui/src/api/types.ts (`Health`), ui/src/api/hooks.ts (`useHealth`)
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
  /** True for a provider key; false for the operator's own CLI login (development and evaluation only). */
  production: boolean
}

/** The builder to run with, from the `builders` health probe; `null` when the deployment has none usable. */
export function builderChoice(health: Health | undefined): BuilderChoice | null {
  const keys = health?.probes.find((p) => p.name === 'builders')?.data
  if (!keys) return null
  if (keys.anthropic) return { builder: 'claude_code', model: 'claude-sonnet-5', builder_config: {}, label: 'Claude Code · claude-sonnet-5 · API key (production)', production: true }
  if (keys.claude_code_cli) {
    return { builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, label: 'Claude Code · claude-sonnet-5 · the operator’s own CLI login (development and evaluation only)', production: false }
  }
  return null
}
