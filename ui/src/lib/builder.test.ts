/**
 * builder.ts — the builder a screen measures or manufactures with follows the health probe.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `builderChoice`.
 * What it does: Pins that an Anthropic key gives Claude Code in production auth with an empty
 *               config; that only a Claude Code CLI login gives `{auth: "cli"}` and says it is
 *               a development posture; that a stack with no credentialed builder but the
 *               test-only `fixture_gold` registered measures with the fixture, named test-only
 *               and never a builder measurement, at a known $0 per attempt — and that any
 *               credentialed builder outranks it; that no usable builder, no builders probe or
 *               no health at all gives `null`; and that the key wins over the login when both
 *               are present.
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
import { FIXTURE_LABEL, builderChoice } from './builder'

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
      cost_per_attempt_usd: null,
    })
  })

  it('only a CLI login → Claude Code with {auth: cli}, a development posture', () => {
    const c = builderChoice(health({ anthropic: false, claude_code_cli: true }))
    expect(c).toMatchObject({ builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, production: false, cost_per_attempt_usd: null })
    expect(c?.label).toMatch(/development and evaluation only/)
  })

  it('a stack that registered the fixture builder measures with it, named test-only, at $0', () => {
    const c = builderChoice(health({ anthropic: false, claude_code_cli: false, fixture_gold: true }))
    expect(c).toEqual({ builder: 'fixture_gold', model: 'gold', builder_config: {}, label: FIXTURE_LABEL, production: false, cost_per_attempt_usd: 0 })
    // the label says what it is and what it is not, in words a reader of the money page needs
    expect(c?.label).toMatch(/test-only instrument check/)
    expect(c?.label).toMatch(/never a builder measurement/)
    // a known price of zero is a price, not a missing one
    expect(c?.cost_per_attempt_usd).toBe(0)
  })

  it('a credentialed builder outranks the fixture: the instrument check never prices the money page while a real builder is available', () => {
    expect(builderChoice(health({ anthropic: true, fixture_gold: true }))?.builder).toBe('claude_code')
    const cli = builderChoice(health({ anthropic: false, claude_code_cli: true, fixture_gold: true }))
    expect(cli?.builder).toBe('claude_code')
    expect(cli?.builder_config).toEqual({ auth: 'cli' })
    expect(cli?.cost_per_attempt_usd).toBeNull()
  })

  it('nothing usable, no builders probe, or no health → null', () => {
    expect(builderChoice(health({ anthropic: false, claude_code_cli: false }))).toBeNull()
    expect(builderChoice(health({ anthropic: false, claude_code_cli: false, fixture_gold: false }))).toBeNull()
    expect(builderChoice(health({}))).toBeNull()
    expect(builderChoice(health(null))).toBeNull()
    expect(builderChoice(undefined)).toBeNull()
  })
})
