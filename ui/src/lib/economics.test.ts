/**
 * economicsTile — the served economics fold as a tile: value, n, interval, apparatus (F35).
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for ui/src/lib/economics.ts.
 * What it does: Pins that a known $0 renders as $0.00 with its n and interval, that an unknown
 *               renders as the dash with the server's reason (never $0.00), that one known row
 *               shows the value with no interval and the reason, that a pooled apparatus is
 *               refused with the versions named, that the denominators are the known counts,
 *               and that a response with no economics block says so.
 * How:          Hand-built `Economics` objects; no rendering.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/economics.ts (under test), ui/src/api/types.ts (`Economics`),
 *               src/crb/core/economics.py (the reasons and method strings copied here)
 * Tested by:    ui/src/lib/economics.test.ts
 * Touch when:   an economics figure or its denominator sentence changes.
 */
import { describe, expect, it } from 'vitest'
import type { Economics, EconomicsEstimate } from '../api/types'
import { NO_ECONOMICS, economicsTile } from './economics'

const T_MEAN = 'Student-t 95% on the known rows (n-1 df), lower bound floored at 0'
const est = (over: Partial<EconomicsEstimate>): EconomicsEstimate => ({ n: 0, value: null, ci_low: null, ci_high: null, method: T_MEAN, reason: '', ...over })
const econ = (over: Partial<Economics>): Economics => ({
  n_attempts: 40,
  n_clean: 38,
  cost_known: 36,
  cost_known_clean: 34,
  latency_known: 40,
  latency_known_clean: 38,
  apparatus_versions: ['2.2'],
  pooled: false,
  cost_per_attempt: est({ n: 36, value: 0.12, ci_low: 0.1, ci_high: 0.14 }),
  cost_per_clean: est({ n: 34, value: 0.127, ci_low: 0.105, ci_high: 0.149 }),
  latency_per_attempt: est({ n: 40, value: 95, ci_low: 80, ci_high: 110 }),
  ...over,
})

describe('economicsTile', () => {
  it('carries the known count as n, the served interval in the unit and the method and apparatus', () => {
    const t = economicsTile(econ({}), 'cost_per_attempt')
    expect(t.value).toBe('$0.1200')
    expect(t.n).toBe(36)
    expect(t.ci).toEqual({ low: 0.1, high: 0.14 })
    expect(t.ciFormat(0.1)).toBe('$0.1000')
    expect(t.apparatus).toBe(`36 of 40 attempts with a known cost · ${T_MEAN} · apparatus 2.2`)
    const clean = economicsTile(econ({}), 'cost_per_clean')
    expect(clean.n).toBe(34)
    expect(clean.apparatus).toContain('34 clean of 36 attempts with a known cost')
    const lat = economicsTile(econ({}), 'latency_per_attempt')
    expect(lat.value).toBe('1 min 35 s')
    expect(lat.ciFormat(80)).toBe('1 min 20 s')
    expect(lat.apparatus).toContain('40 of 40 attempts with a known latency')
  })

  it('a known $0 is $0.00 with its n, never a dash', () => {
    const t = economicsTile(econ({ cost_per_attempt: est({ n: 4, value: 0, ci_low: 0, ci_high: 0 }) }), 'cost_per_attempt')
    expect(t.value).toBe('$0.00')
    expect(t.n).toBe(4)
    expect(t.ci).toEqual({ low: 0, high: 0 })
  })

  it('an unknown is the dash with the reason, never $0.00', () => {
    const reason = 'no attempt recorded a known cost'
    const t = economicsTile(econ({ cost_known: 0, cost_per_attempt: est({ n: 0, reason }) }), 'cost_per_attempt')
    expect(t.value).toBe('—')
    expect(t.n).toBe(0)
    expect(t.ci).toBeNull()
    expect(t.apparatus).toContain(reason)
  })

  it('one known row shows its value, no interval, and why', () => {
    const reason = 'one attempt with a known latency — an interval needs at least two'
    const t = economicsTile(econ({ latency_per_attempt: est({ n: 1, value: 12, reason }) }), 'latency_per_attempt')
    expect(t.value).toBe('12 s')
    expect(t.ci).toBeNull()
    expect(t.apparatus).toContain(reason)
  })

  it('a pooled apparatus is refused with the versions named', () => {
    const reason = 'rows from 2 apparatus versions (2.1, 2.2) — economics are never pooled across apparatus versions; read one apparatus'
    const t = economicsTile(econ({ pooled: true, apparatus_versions: ['2.1', '2.2'], cost_per_attempt: est({ n: 36, reason }) }), 'cost_per_attempt')
    expect(t.value).toBe('—')
    expect(t.apparatus).toContain('never pooled')
    expect(t.apparatus).toContain('apparatus 2.1, 2.2')
  })

  it('no economics block from the server says so', () => {
    const t = economicsTile(undefined, 'cost_per_clean')
    expect(t).toMatchObject({ value: '—', n: 0, ci: null, apparatus: NO_ECONOMICS })
  })
})
