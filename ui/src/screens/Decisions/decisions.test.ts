/**
 * decisions.ts — every human act the product has becomes exactly one inbox row.
 *
 * Navigation
 * ----------
 * What it is:   Tests for `decisionsFor`.
 * What it does: Pins that a `deliver` cell the entry gate does not read as signed (the
 *               served `signed`, never the tier — G-738) is "sign-off due" (approver,
 *               deep-linked with `?cell=`), that a cell it reads signed is not, that a cell
 *               served without that reading falls back to the active sign-offs (a revoked one
 *               does not count), that a `human` cell is "routed
 *               to a human" carrying its reason, that `do_not_ship` sorts first, that an
 *               unsigned structural gap on a factory item is a row for the approver, that
 *               a review verdict of accept-with-edit / reject is a rework row, that a clean
 *               build with no PR whose last event is `delivery.refused` is "delivery
 *               withheld", that an unmeasured cell (n = 0) never appears, the order, and
 *               the prevention loop's rows: a filed item nobody registered is "a prevention
 *               needs an owner" for an operator, a reopened class and a change retired for
 *               harm are rows anyone may read — each linking to the class on the Learn page; a
 *               cell held by its oracle or its controls is one `strengthen` row (G-535); and the
 *               fold produces the shared fixture's rows, the rows the server serves (F6).
 * How:          Plain unit tests over hand-built map cells, sign-offs and factory tasks, and
 *               `decisions.parity.json` (read by tests/test_server_decisions.py too).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Decisions/decisions.ts (under test)
 * Tested by:    ui/src/screens/Decisions/decisions.test.ts
 * Touch when:   never for a new repository; a human act is added to the product.
 */

import { describe, expect, it } from 'vitest'
import type { CapabilityCell, FactoryTask, LibraryIndex, PreventionRegister, Signoff } from '../../api/types'
import { REGISTER } from '../Learn/register.fixture'
import { LIBRARY, PROPOSED, SIGNED } from '../Library/library.fixture'
import { STRENGTHEN_REASONS, decisionsFor, evidenceStats, holdReason, waitedFor } from './decisions'
import PARITY from './decisions.parity.json?raw'

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

  it('the entry gate’s own reading, served as signed, decides: never the tier or the sign-off list (G-738)', () => {
    // the map lifted the cell and a sign-off is active, but the gate reads its standard unsigned: due
    const earned = cell({ verification_tier: 'human-verified', signed: false })
    const due = decisionsFor({ repo: 'alpha', cells: [earned], signoffs: [signoff({})], tasks: [] })
    expect(due.map((r) => [r.kind, r.key, r.role])).toEqual([['signoff_due', 'bug.fix|XS', 'approver']])
    // the gate reads it signed though nothing listed lifts the map: nobody is waiting
    const signed = cell({ verification_tier: 'automated-pass', signed: true })
    expect(decisionsFor({ repo: 'alpha', cells: [signed], signoffs: [], tasks: [] })).toHaveLength(0)
  })

  it('an active sign-off clears the row; a revoked one does not — for a cell served without the gate’s reading, the list is the fallback', () => {
    expect(decisionsFor({ repo: 'alpha', cells: [cell({})], signoffs: [signoff({})], tasks: [] })).toHaveLength(0)
    expect(decisionsFor({ repo: 'alpha', cells: [cell({})], signoffs: [signoff({ revoked: true })], tasks: [] })).toHaveLength(1)
  })

  it('human and do_not_ship cells are rows with their reason; unmeasured cells never are', () => {
    const rows = decisionsFor({
      repo: 'alpha',
      cells: [
        cell({ size: 'S', route: 'human', reason: 'the reading decided against the arm', reason_code: 'insufficient' }),
        cell({ size: 'M', route: 'do_not_ship', reason: '1 false-Q1 row', reason_code: 'false_q1', false_q1: 1 }),
        cell({ size: 'L', n: 0, route: 'NOT_YET_MEASURED' as never }),
        cell({ size: 'XL', route: 'calibrate', reason_code: 'n_below_min' }),
      ],
      signoffs: [],
      tasks: [],
    })
    expect(rows.map((r) => r.kind)).toEqual(['do_not_ship', 'routed_human'])
    expect(rows[1]?.title).toContain('the reading decided against the arm')
    expect(rows[1]).toMatchObject({ role: 'viewer', href: '/routing?repo=alpha' })
  })

  it('a cell held by its oracle or its controls is a strengthening decision that links to Learn', () => {
    // G-535: one row per held cell — never zero (it waits on a person), never two (not also "routed to a human")
    const weak = decisionsFor({ repo: 'alpha', cells: [cell({ size: 'S', route: 'human', reason: 'oracle strength 0.76 < 0.80', reason_code: 'oracle_weak' })], signoffs: [], tasks: [] })
    expect(weak).toHaveLength(1)
    expect(weak[0]).toMatchObject({ kind: 'strengthen', key: 'bug.fix|S', role: 'operator', act: 'Strengthen the tests', href: '/learn?repo=alpha#strengthen', reasonCode: 'oracle_weak' })
    expect(weak[0]?.title).toBe('bug.fix × S is held until its tests are stronger')
    // routing.v2 lists every failing clause: thin controls behind a pending reading still hold the cell, and the row names that clause
    const shortfall = { code: 'controls_thin', route: 'calibrate', observed: 0.2, threshold: 0.5, next: 'controls', count: 0, model_money: false }
    const thin = decisionsFor({ repo: 'alpha', cells: [cell({ size: 'M', route: 'calibrate', reason_code: 'reading_unregistered', shortfalls: [shortfall] })], signoffs: [], tasks: [] })
    expect(thin.map((r) => [r.kind, r.reasonCode])).toEqual([['strengthen', 'controls_thin']])
    expect(thin[0]?.evidence.endsWith(' · controls_thin')).toBe(true)
    // the reasons are the server's own (tests/test_decisions_kinds.py reads this tuple)
    expect([...STRENGTHEN_REASONS]).toEqual(['oracle_weak', 'controls_escapes', 'controls_thin'])
    expect(holdReason({ reason_code: 'controls_escapes' })).toBe('controls_escapes')
    expect(holdReason({ reason_code: 'insufficient', shortfalls: [] })).toBeNull()
  })

  it('the browser’s fold produces the shared fixture’s rows, the same rows the server serves (F6)', () => {
    const fx = JSON.parse(PARITY) as { repo: string; cells: CapabilityCell[]; signoffs: Signoff[]; tasks: FactoryTask[]; register: PreventionRegister; library: LibraryIndex; expected: Array<Record<string, string>> }
    const rows = decisionsFor({ repo: fx.repo, cells: fx.cells, signoffs: fx.signoffs, tasks: fx.tasks, register: fx.register, library: fx.library })
    const got = rows.map((r) => ({ kind: r.kind, key: r.key, title: r.title, role: r.role, evidence: r.evidence, reason_code: r.reasonCode ?? '', act: r.act, href: r.href }))
    expect(got).toEqual(fx.expected)
  })

  it('an item the entry gate did not build waits here: an approver may fund a calibration build; missing context is the operator’s (ADR-0026 item 8)', () => {
    const rows = decisionsFor({
      repo: 'alpha',
      cells: [],
      signoffs: [],
      tasks: [
        task({ id: 'I-5', title: 'No standard', status: 'no_proven_standard', route_hint: 'human', entry: { code: 'no_proven_standard', reason: 'r', reason_code: 'none', needs: [] }, way_forward: { action: 'fund_calibration', route: '/factory/alpha/items/I-5/calibration', supersedes: 'I-5' } }),
        task({ id: 'I-6', title: 'Needs a test', status: 'needs_context', route_hint: 'human', entry: { code: 'needs_context', reason: 'r', reason_code: 'S2', needs: ['a failing test'] } }),
        task({ id: 'I-7', title: 'Funded', status: 'no_proven_standard', route_hint: 'human', entry: { code: 'no_proven_standard', reason: 'r', reason_code: 'none', needs: [] }, calibration: { approver: 'ada', reason: 'measure', created: '', event: 'e' } }),
      ],
    })
    expect(rows.map((r) => [r.kind, r.title])).toEqual([
      ['not_built', 'I-5 No standard is not built — no proven standard'],
      ['not_built', 'I-6 Needs a test is not built — needs context'],
    ])
    expect(rows[0]).toMatchObject({ role: 'approver', act: 'Fund a calibration build', href: '/factory?repo=alpha&item=I-5' })
    expect(rows[1]).toMatchObject({ role: 'operator', act: 'Decide', evidence: 'bug.fix × XS · attach a failing test' })
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

  it('the library asks for a sponsor, a second signature, a re-signature, and reads a measured retirement', () => {
    const retired = { ...SIGNED, entry_id: 'convention/old', status: 'retired' as const, retired: { actor: 'system:library-arm', by: 'measurement' as const, reason: 'the pairs favour the arm without it', reading_id: 'r7', at: '' } }
    const byPerson = { ...SIGNED, entry_id: 'convention/gone', status: 'retired' as const, retired: { actor: 'u', by: 'person' as const, reason: 'no', reading_id: '', at: '' } }
    const rows = decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], library: { ...LIBRARY, entries: [...LIBRARY.entries, retired, byPerson] } })
    expect(rows.map((r) => [r.kind, r.act, r.role, r.title])).toEqual([
      ['entry_stale', 'Sign again or retire', 'approver', 'convention/lint went stale: .golangci.yml changed or went'],
      ['entry_to_sign', 'Sign', 'approver', 'convention/context-first waits for a second person to sign it'],
      ['entry_to_sign', 'Sponsor', 'operator', 'decision/adr-0001 was proposed by mined:adr@1 and needs a person to sponsor it'],
      ['entry_retired', 'Read why', 'viewer', 'convention/old was retired by measurement'],
    ])
    expect(rows.every((r) => r.href === '/library/alpha#index')).toBe(true)
    // a proposal whose file changed before anyone signed it says so, never "signed by" nobody
    const staleEntry = LIBRARY.entries.find((e) => e.status === 'stale')!
    const unsigned = { ...staleEntry, approver: '', approver_name: '', signed_at: '' }
    const [row] = decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], library: { ...LIBRARY, entries: [unsigned] } })
    expect(row?.evidence).toMatch(/· not yet signed$/)
  })

  it('an entry the viewer sponsored waits for another approver: never their Sign, never their re-signature', () => {
    const mine = PROPOSED.sponsor
    const rows = decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], library: LIBRARY, me: mine })
    const own = rows.filter((r) => r.kind !== 'entry_retired' && r.act !== 'Sponsor')
    expect(own.map((r) => [r.act, r.role, r.title])).toEqual([
      ['Read', 'viewer', 'convention/lint went stale: .golangci.yml changed or went — you sponsored it, so another approver signs it again'],
      ['Read', 'viewer', 'convention/context-first waits for another approver to sign it — you sponsored it'],
    ])
    // another approver still sees their Sign
    const theirs = decisionsFor({ repo: 'alpha', cells: [], signoffs: [], tasks: [], library: LIBRARY, me: 'someone-else' })
    expect(theirs.filter((r) => r.act === 'Sign')).toHaveLength(1)
  })

  it('every row carries the identity the server keeps the clock under (G-516)', () => {
    const rows = decisionsFor({
      repo: 'alpha',
      cells: [cell({ route: 'deliver' })],
      signoffs: [],
      tasks: [task({ id: 'I-1', dor_gaps: ['method_path'] })],
    })
    // `<class>|<size>` for a cell row and the item id for a factory row — the same keys
    // `src/crb/server/decisions.py` computes, which is how `GET /decisions` ages join on
    expect(rows.map((r) => [r.kind, r.key])).toEqual([
      ['gap_unsigned', 'I-1'],
      ['signoff_due', 'bug.fix|XS'],
    ])
  })
})

describe('waitedFor', () => {
  it('reads a wait in the units a person thinks in, and says nothing when nothing is known', () => {
    expect(waitedFor(undefined)).toBeNull()
    expect(waitedFor(-1)).toBeNull()
    expect(waitedFor(30)).toBe('just now')
    expect(waitedFor(60 * 5)).toBe('5 min')
    expect(waitedFor(3600)).toBe('1 hour')
    expect(waitedFor(3600 * 5)).toBe('5 hours')
    expect(waitedFor(86400)).toBe('1 day')
    expect(waitedFor(86400 * 11)).toBe('11 days')
  })
})
