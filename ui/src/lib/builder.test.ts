/**
 * builder.ts — the builder a screen measures or manufactures with follows the health probe.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `builderChoice`.
 * What it does: Pins that an Anthropic key gives Claude Code in production auth with an empty
 *               config; that only a Claude Code CLI login gives `{auth: "cli"}` and says it is
 *               a development posture; that no usable builder, no builders probe or no health
 *               at all gives `null`; and that the key wins over the login when both are present.
 * How:          Plain calls with hand-built `Health` values.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/builder.ts, ui/src/screens/Connect/MeasurePage.test.tsx (the page
 *               that posts the choice)
 * Tested by:    ui/src/lib/builder.test.ts
 * Touch when:   a builder is added to the deployment's probe.
 */
import { describe, expect, it } from 'vitest'
import type { Health } from '../api/types'
import { builderChoice } from './builder'

function health(data: Record<string, unknown> | null): Health {
  const probes = [{ name: 'sandbox', status: 'ok' as const, detail: '', data: {} }]
  if (data) probes.push({ name: 'builders', status: 'ok' as const, detail: '', data })
  return { status: 'ok', probes }
}

describe('builderChoice', () => {
  it('an Anthropic key → Claude Code, production, no config', () => {
    expect(builderChoice(health({ anthropic: true, claude_code_cli: true }))).toEqual({
      builder: 'claude_code',
      model: 'claude-sonnet-5',
      builder_config: {},
      label: 'Claude Code · claude-sonnet-5 · API key (production)',
      production: true,
    })
  })

  it('only a CLI login → Claude Code with {auth: cli}, a development posture', () => {
    const c = builderChoice(health({ anthropic: false, claude_code_cli: true }))
    expect(c).toMatchObject({ builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, production: false })
    expect(c?.label).toMatch(/development and evaluation only/)
  })

  it('nothing usable, no builders probe, or no health → null', () => {
    expect(builderChoice(health({ anthropic: false, claude_code_cli: false }))).toBeNull()
    expect(builderChoice(health({}))).toBeNull()
    expect(builderChoice(health(null))).toBeNull()
    expect(builderChoice(undefined)).toBeNull()
  })
})
