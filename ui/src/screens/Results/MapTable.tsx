/**
 * MapTable — the capability map as a class × size table with the route, n, the interval and
 * the sign-off state in every cell; and the sentence the map licenses.
 *
 * Navigation
 * ----------
 * What it is:   The design's A7 grid: one row per class, one column per size; each measured
 *               cell shows its route as a solid tag, `n=… on … tasks`, the point and the
 *               Wilson interval, and one more line — the reason code, or the sign-off state
 *               ("signed 15 Sep" / "sign-off due" / "sign-off stale"); an unmeasured cell
 *               says "not measured · no attempt sighted" on a pale ground and never zero.
 *               `licenseSentence` renders "What this licenses you to say" for a signed cell,
 *               with every qualifier the claims policy demands.
 * What it does: Puts the sign-off state where the reader's eye already is — on the cell —
 *               so "which cells are signed, due or stale" needs no second screen; and gives
 *               the governance reader the exact sentence they may quote.
 * How:          Pure rendering over `CapabilityMap.cells` + the repo's `Signoff[]`; the
 *               sizes are the map's `sizes`, the classes its `classes`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Results/ResultsPage.tsx (mounts it), ui/src/components/govuk.tsx
 *               (Tag), ui/src/screens/Decisions/decisions.ts (the same sign-off state rules),
 *               docs/EVIDENCE-AND-CLAIMS.md §6 (the permitted claim shape)
 * Tested by:    ui/src/screens/Results/MapTable.test.tsx
 * Touch when:   a cell field is added that a reader needs on the grid.
 */

import { Link } from 'react-router'
import { type CapabilityCell, type CapabilityMap, NOT_YET_MEASURED, type Signoff } from '../../api/types'
import type { ControlsVerdict } from '../Capability/contract'
import { Tag, type TagTone } from '../../components/govuk'

export type SignState = 'signed' | 'due' | 'stale' | 'none'

export function signStateOf(cell: CapabilityCell, signoffs: Signoff[]): { state: SignState; signoff?: Signoff } {
  const mine = signoffs.filter((s) => !s.revoked && s.cell.capability_class === cell.capability_class && s.cell.size === cell.size)
  const active = mine.find((s) => s.active !== false && !s.stale)
  if (active) return { state: 'signed', signoff: active }
  const stale = mine.find((s) => s.stale)
  if (stale) return { state: 'stale', signoff: stale }
  if (cell.route === 'deliver') return { state: 'due' }
  return { state: 'none' }
}

const ROUTE_TONE: Record<string, TagTone> = { deliver: 'green', human: 'amber', calibrate: 'grey', granularize: 'grey', do_not_ship: 'red' }

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
}

function shortDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

export function MapTable({ map, signoffs, repo }: { map: CapabilityMap; signoffs: Signoff[]; repo: string }) {
  // every size tier, always — an absent column would hide the honest "not measured"
  const sizes = ['XS', 'S', 'M', 'L', 'XL']
  const classes = map.classes.length ? map.classes : Array.from(new Set(map.cells.map((c) => c.capability_class)))
  const byKey = new Map(map.cells.map((c) => [`${c.capability_class}|${c.size}`, c]))
  return (
    <div className="mb-6 overflow-x-auto">
      <table className="w-full min-w-[820px] border-collapse" aria-label={`Capability map for ${repo}`}>
        <thead>
          <tr>
            <th className="border-b-2 border-on-surface py-3 pr-2 text-left text-[16px] font-bold leading-[1.5]">Class</th>
            {sizes.map((sz) => (
              <th key={sz} className="border-b-2 border-on-surface px-2 py-3 text-left text-[16px] font-bold leading-[1.5]">
                {sz}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {classes.map((cls) => (
            <tr key={cls}>
              <th scope="row" className="border-b border-border py-3 pr-2 text-left align-top font-mono text-[16px] font-normal leading-[1.5]">
                {cls}
              </th>
              {sizes.map((sz) => {
                const c = byKey.get(`${cls}|${sz}`)
                const measured = c && c.route !== NOT_YET_MEASURED && c.n > 0
                if (!c || !measured) {
                  const granular = c && c.route === 'granularize'
                  return (
                    <td key={sz} className={`border-b border-l border-border px-2 py-3 align-top ${granular ? '' : 'bg-surface-high'}`} data-testid={`cell-${cls}-${sz}`}>
                      {granular ? (
                        <>
                          <Tag tone="grey">granularize</Tag>
                          <div className="mt-1.5 text-[14px] leading-[1.4] text-on-surface-muted">{sz} is split first</div>
                        </>
                      ) : (
                        <>
                          <span className="inline-block text-[13px] font-bold uppercase leading-tight tracking-[.04em]">not measured</span>
                          <div className="mt-1.5 text-[14px] leading-[1.4] text-on-surface-muted">no attempt sighted</div>
                        </>
                      )}
                    </td>
                  )
                }
                const sign = signStateOf(c, signoffs)
                const last =
                  sign.state === 'signed' && sign.signoff
                    ? `signed ${shortDate(sign.signoff.created)}`
                    : sign.state === 'stale'
                      ? 'sign-off stale'
                      : sign.state === 'due'
                        ? 'sign-off due'
                        : c.reason_code || ''
                return (
                  <td key={sz} className="border-b border-l border-border px-2 py-3 align-top" data-testid={`cell-${cls}-${sz}`}>
                    <Tag tone={ROUTE_TONE[c.route] ?? 'grey'}>{c.route.replace(/_/g, ' ')}</Tag>
                    <div className="mt-1.5 text-[15px] leading-[1.45]">
                      n={c.n}
                      {c.n_tasks !== undefined ? ` on ${c.n_tasks} tasks` : ''}
                    </div>
                    <div className="text-[15px] font-bold leading-[1.45]">{c.ci_high - c.ci_low > 0.6 ? '—' : pct(c.point)}</div>
                    <div className="text-[14px] leading-[1.4] text-on-surface-muted">{c.ci_high - c.ci_low > 0.6 ? 'interval too wide' : `[${pct(c.ci_low)}, ${pct(c.ci_high)}]`}</div>
                    <div className="text-[14px] leading-[1.4] text-on-surface-muted">
                      {sign.state === 'due' ? (
                        <Link to={`/signoff?repo=${encodeURIComponent(repo)}&cell=${encodeURIComponent(`${c.capability_class}|${c.size}`)}`}>{last}</Link>
                      ) : (
                        last
                      )}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * "What this licenses you to say": the one sentence a signed cell permits, with every
 * qualifier EVIDENCE-AND-CLAIMS §6 requires — repo, apparatus, belt set, the controls
 * gate, n and tasks, the class × size, the rate with its interval, who signed and when,
 * and what it says nothing about. Null when no cell is signed.
 */
export function licenseSentence(repo: string, map: CapabilityMap & { controls?: ControlsVerdict }, signoffs: Signoff[]): string | null {
  const signed = map.cells
    .map((c) => ({ c, s: signStateOf(c, signoffs) }))
    .filter((x) => x.s.state === 'signed' && x.s.signoff)
    .sort((a, b) => b.c.n - a.c.n)[0]
  if (!signed || !signed.s.signoff) return null
  const c = signed.c
  const so = signed.s.signoff
  const apparatus = c.apparatus_versions.join(', ') || '—'
  const belts = c.belt_sets?.join(', ') || '—'
  const gate = map.controls?.state ? `a ${map.controls.state} controls gate` : 'the controls gate'
  return `On ${repo} at apparatus ${apparatus}, under belt set ${belts} and ${gate}, ${c.clean} of ${c.n} sighted attempts at ${c.capability_class} × ${c.size}${c.n_tasks ? ` (${c.n_tasks} tasks)` : ''} were graded clean: ${pct(c.point)} (95% Wilson ${pct(c.ci_low)}–${pct(c.ci_high)}), signed by ${so.approver} on ${new Date(so.created).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}. It says nothing about any other repository, class or size.`
}
