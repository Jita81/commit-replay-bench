/**
 * decisions.ts — every human act the product has becomes exactly one inbox row.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `decisionsFor`.
 * What it does: Pins that a `deliver` cell without an active sign-off is "sign-off due"
 *               (approver, deep-linked with `?cell=`), that a signed cell is not, that a
 *               revoked sign-off does not count as signed, that a `human` cell is "routed
 *               to a human" carrying its reason, that `do_not_ship` sorts first, that an
 *               unsigned structural gap on a factory item is a row for the approver, that
 *               a review verdict of accept-with-edit / reject is a rework row, that a clean
 *               build with no PR whose last event is `delivery.refused` is "delivery
 *               withheld", that an unmeasured cell (n = 0) never appears, the order, and
 *               the prevention loop's rows: a filed item nobody registered is "a prevention
 *               needs an owner" for an operator, a reopened class and a change retired for
 *               harm are rows anyone may read — each linking to the class on the Learn page.
 * How:          Plain unit tests over hand-built map cells, sign-offs and factory tasks.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/decisions.ts (under test)
 * Tested by:    ui/src/screens/Decisions/decisions.test.ts
 * Touch when:   a human act is added to the product.
 */

import { describe, expect, it } from 'vitest'
import type { CapabilityCell, FactoryTask, Signoff } from '../../api/types'
import { REGISTER } from '../Learn/register.fixture'
import { decisionsFor, evidenceStats } from './decisions'

function cell(over: Partial<CapabilityCell>): CapabilityCell {
  return { capability_class: 'bug.fix', size: 'XS', n: 22, n_tasks: 9, clean: 22, point: 1, ci_low: 0.851, ci_high: 1, false_q1: 0, route: 'deliver', reason: 'n=22 …', reason_code: 'deliver', ...over } as CapabilityCell
}
function signoff(over: Partial<Signoff>): Signoff {
  return { id: 's1', repo: 'alpha', cell: { capability_class: 'bug.fix', size: 'XS' }, revoked: false, ...over } as Signoff
}
function task(over: Partial<FactoryTask>): FactoryTask {
  return { id: 'I-1', title: 'Multiply', capability_class: 'bug.fix', size: 'XS', kind: 'code', status: 'ready', outcome_reason: '', dor_gaps: [], route_hint: 'build', red_proof: null, build_status: 'not_started', pr_url: null, review_verdict: null, last_event: 'readiness.assessed', cell_route: { route: 'deliver', reason_code: 'deliver', reason: 'ok', n: 22, point: 1, ci_low: 0.851, ci_high: 1, apparatus_versions: ['2.2'], deliverable: true }, ...over }
}

describe('decisionsFor', () => {
  it('a deliver cell without an active sign-off is a sign-off due for the approver, deep-linked', () => {
    const rows = decisionsFor({ repo: 'alpha', cells: [cell({})], signoffs: [], tasks: [] })
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ kind: 'signoff_due', role: 'approver', act: 'Attest', href: '/signoff?repo=alpha&cell=bug.fix%7CXS' })
    expect(rows[0]?.evidence).toBe('n=22 on 9 tasks · 100% [85%, 100%] · deliver')
    // the code travels on its own too, so the screen can render it as a term; the stats line drops it
    expect(rows[0]?.reasonCode).toBe('deliver')
    expect(evidenceStats(rows[0]!)).toBe('n=22 on 9 tasks · 100% [85%, 100%]')
    expect(evidenceStats({ evidence: 'method_path, response_shape' })).toBe('method_path, response_shape')
  })

  it('an active sign-off clears the row; a revoked one does not', () => {
    expect(decisionsFor({ repo: 'alpha', cells: [cell({})], signoffs: [signoff({})], tasks: [] })).toHaveLength(0)
    expect(decisionsFor({ repo: 'alpha', cells: [cell({})], signoffs: [signoff({ revoked: true })], tasks: [] })).toHaveLength(1)
  })

  it('human and do_not_ship cells are rows with their reason; unmeasured cells never are', () => {
    const rows = decisionsFor({
      repo: 'alpha',
      cells: [
        cell({ size: 'S', route: 'human', reason: 'oracle strength 0.76 < 0.80', reason_code: 'oracle_weak' }),
        cell({ size: 'M', route: 'do_not_ship', reason: '1 false-Q1 row', reason_code: 'false_q1', false_q1: 1 }),
        cell({ size: 'L', n: 0, route: 'NOT_YET_MEASURED' as never }),
        cell({ size: 'XL', route: 'calibrate', reason_code: 'n_below_min' }),
      ],
      signoffs: [],
      tasks: [],
    })
    expect(rows.map((r) => r.kind)).toEqual(['do_not_ship', 'routed_human'])
    expect(rows[1]?.title).toContain('oracle strength 0.76 < 0.80')
    expect(rows[1]).toMatchObject({ role: 'viewer', href: '/routing?repo=alpha' })
  })

  it('factory items: unsigned gaps, rework verdicts and a withheld delivery each become a row', () => {
    const rows = decisionsFor({
      repo: 'alpha',
      cells: [],
      signoffs: [],
      tasks: [
        task({ id: 'I-1', title: 'Divide', status: 'blocked', dor_gaps: ['method_path', 'response_shape'], route_hint: 'human' }),
        task({ id: 'I-2', title: 'Rework me', status: 'rework', build_status: 'clean', review_verdict: 'accept_with_edit' }),
        task({ id: 'I-3', title: 'Withheld', status: 'accepted', build_status: 'clean', review_verdict: 'accept', last_event: 'delivery.refused' }),
        task({ id: 'I-4', title: 'Fine', status: 'accepted', build_status: 'clean', pr_url: 'https://x/pr/1', review_verdict: 'accept', last_event: 'item.outcome' }),
      ],
    })
    expect(rows.map((r) => [r.kind, r.title.split(' ')[0]])).toEqual([
      ['gap_unsigned', 'I-1'],
      ['rework', 'I-2'],
      ['delivery_withheld', 'I-3'],
    ])
    expect(rows[0]).toMatchObject({ role: 'approver', act: 'Sign a gap', href: '/factory?repo=alpha&item=I-1', evidence: 'method_path, response_shape' })
    expect(rows[0]?.title).toBe('I-1 Divide is blocked on 2 structural gaps')
  })

  it('a prevention with no owner is a decision', () => {
    const rows = decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], register: REGISTER })
    const prev = rows.filter((r) => r.kind === 'prevention')
    // two unregistered items that can go on the backlog; the product-scoped one never becomes a row
    expect(prev).toHaveLength(2)
    expect(prev.every((r) => r.act === 'Register' && r.role === 'operator')).toBe(true)
    expect(prev.map((r) => r.href)).toContain('/learn?repo=alpha&class=protocol%3Anetwork%3Ago%20mod#prevention')
    expect(prev.some((r) => r.title.includes('Record a command'))).toBe(false)
    expect(prev[0]?.title).toMatch(/^A prevention needs an owner — /)
    // once registered, it is no longer waiting on anybody
    const registered = { ...REGISTER, entries: REGISTER.entries.map((e) => ({ ...e, proposals: e.proposals.map((p) => ({ ...p, registered: { registered_id: p.item_id } })) })) }
    expect(decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], register: registered }).filter((r) => r.kind === 'prevention')).toHaveLength(0)
  })

  it('a reopened class is a decision', () => {
    const e = REGISTER.entries[0]!
    const reopened = { ...REGISTER, entries: [{ ...e, proposals: [], qualifiers: ['reopened'], history: [...e.history, { kind: 'decided', record_id: 'r9', row_hash: '9'.repeat(64), created: '', actor: 'loop', on_behalf_of: 'op-1', summary: 'harm' }] }] }
    const rows = decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], register: reopened })
    expect(rows.map((r) => [r.title, r.act, r.role])).toEqual([
      ['A change for protocol:network:go mod was retired for harm', 'Read why', 'viewer'],
      ['protocol:network:go mod reopened after it was closed', 'Read why', 'viewer'],
    ])
    expect(rows[0]?.href).toBe('/learn?repo=alpha&class=protocol%3Anetwork%3Ago%20mod#prevention')
  })
})
