/**
 * MapTable — the capability map as a class × size table with the route, n, the interval and
 * the sign-off state in every cell; and the sentence the map licenses.
 *
 * Navigation
 * ----------
 * What it is:   The design's A7 grid: one row per class, one column per size; each measured
 *               cell shows its route as a solid tag, `n=… on … tasks`, the point and the
 *               Wilson interval, the apparatus version(s) the rows carry, and one more line
 *               — the reason code, or the sign-off state ("signed 15 Sep" / "sign-off due" /
 *               "sign-off stale", or "sign-off not loaded" when the sign-offs did not
 *               load); "sign-off due" is a link to the form only for a reader
 *               who can sign (`canSign`), plain text for everyone else — a viewer is never
 *               shown an action they cannot take. The five size tiers are the taxonomy (`SizeTier` in
 *               core), not the API's `sizes` (which lists only measured tiers): a tier with
 *               no row says "not measured · no attempt sighted" on a pale ground and never
 *               a number — the honest state, not a fabricated cell.
 *               `licenseSentence` renders "What this licenses you to say" for a signed cell,
 *               with every qualifier the claims policy demands. Every element in the grid is
 *               a hint trigger: the column headers (`col.map.class`, `col.map.size`), the
 *               class row headers, and in each cell the route tag, n, point, interval,
 *               apparatus and the sign-off line (`map.cell.*`); the per-cell numbers opt out
 *               of the tab order (`tabStop={false}` — a 50-cell grid is not 300 tab stops)
 *               while the route tag keeps it, so a keyboard reader still lands on every cell.
 * What it does: Puts the sign-off state where the reader's eye already is — on the cell —
 *               so "which cells are signed, due or stale" needs no second screen; and gives
 *               the governance reader the exact sentence they may quote.
 * How:          Pure rendering over `CapabilityMap.cells` + the repo's `Signoff[]`; the
 *               sizes are the map's `sizes`, the classes its `classes`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Results/ResultsPage.tsx (mounts it, passes `can('approver')`),
 *               ui/src/components/govuk.tsx (Tag), ui/src/components/Hint.tsx +
 *               ui/src/help/hints.ts (the triggers and copy), ui/src/screens/Decisions/decisions.ts (the
 *               same sign-off state rules), ui/src/lib/auth.tsx (`can` — the role rule),
 *               docs/EVIDENCE-AND-CLAIMS.md §6 (the permitted claim shape)
 * Tested by:    ui/src/screens/Results/MapTable.test.tsx
 * Touch when:   a cell field is added that a reader needs on the grid.
 */

import { Link } from 'react-router'
import { approverName, type CapabilityCell, type CapabilityMap, NOT_YET_MEASURED, type Signoff, signoffScopeMatches } from '../../api/types'
import type { ControlsVerdict } from '../Capability/contract'
import { Hint } from '../../components/Hint'
import { Tag, type TagTone } from '../../components/govuk'

export type SignState = 'signed' | 'due' | 'stale' | 'none'

export function signStateOf(cell: CapabilityCell, signoffs: Signoff[]): { state: SignState; signoff?: Signoff } {
  // the server's scope rule (`key_matches`): a `*` on the sign-off covers any value; a
  // sign-off narrower than this aggregate cell on some dimension does not cover it
  const mine = signoffs.filter((s) => !s.revoked && signoffScopeMatches(s.cell, cell as unknown as Record<string, string | undefined>))
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

/** A cell's sign-off line while the repository's sign-offs have not loaded (PR #54 review). */
const SIGNOFF_NOT_LOADED = 'sign-off not loaded'

/** `canSign`: the reader holds the approver role, so "sign-off due" may link to the form. Default off: a viewer-safe grid. */
export function MapTable({ map, signoffs, repo, canSign = false }: { map: CapabilityMap; signoffs: Signoff[] | null; repo: string; canSign?: boolean }) {
  // every size tier, always — an absent column would hide the honest "not measured"
  const sizes = ['XS', 'S', 'M', 'L', 'XL']
  const classes = map.classes.length ? map.classes : Array.from(new Set(map.cells.map((c) => c.capability_class)))
  const byKey = new Map(map.cells.map((c) => [`${c.capability_class}|${c.size}`, c]))
  // focusable: the 820 px table scrolls sideways at phone width (WCAG 2.1.1, axe scrollable-region-focusable at 375 px)
  return (
    <div className="mb-6 overflow-x-auto" tabIndex={0} role="region" aria-label={`Capability map for ${repo}, scrollable`}>
      <table className="w-full min-w-[820px] border-collapse" aria-label={`Capability map for ${repo}`}>
        <thead>
          <tr>
            <th scope="col" className="border-b-2 border-on-surface py-3 pr-2 text-left text-[16px] font-bold leading-[1.5]">
              <Hint id="col.map.class">Class</Hint>
            </th>
            {sizes.map((sz) => (
              <th key={sz} scope="col" className="border-b-2 border-on-surface px-2 py-3 text-left text-[16px] font-bold leading-[1.5]">
                <Hint id="col.map.size">{sz}</Hint>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {classes.map((cls) => (
            <tr key={cls}>
              <th scope="row" className="border-b border-border py-3 pr-2 text-left align-top font-mono text-[16px] font-normal leading-[1.5]">
                <Hint id="col.map.class" tabStop={false}>
                  {cls}
                </Hint>
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
                          <Tag tone="grey" hint="map.cell.granularize">
                            granularize
                          </Tag>
                          <div className="mt-1.5 text-[14px] leading-[1.4] text-on-surface-muted">{sz} is split first</div>
                        </>
                      ) : (
                        <>
                          <Hint id="map.cell.not_measured" tabStop={false} className="inline-block text-[13px] font-bold uppercase leading-tight tracking-[.04em]">
                            not measured
                          </Hint>
                          <div className="mt-1.5 text-[14px] leading-[1.4] text-on-surface-muted">no attempt sighted</div>
                        </>
                      )}
                    </td>
                  )
                }
                // no sign-offs loaded: the state is not known, so no cell reads signed or due
                const sign = signoffs === null ? null : signStateOf(c, signoffs)
                const last = !sign
                  ? SIGNOFF_NOT_LOADED
                  : sign.state === 'signed' && sign.signoff
                    ? `signed ${shortDate(sign.signoff.created)}`
                    : sign.state === 'stale'
                      ? 'sign-off stale'
                      : sign.state === 'due'
                        ? 'sign-off due'
                        : c.reason_code || ''
                return (
                  <td key={sz} className="border-b border-l border-border px-2 py-3 align-top" data-testid={`cell-${cls}-${sz}`}>
                    <Tag tone={ROUTE_TONE[c.route] ?? 'grey'} hint="map.cell.route">
                      {c.route.replace(/_/g, ' ')}
                    </Tag>
                    <Hint as="div" id="map.cell.n" tabStop={false} className="mt-1.5 text-[15px] leading-[1.45]">
                      n={c.n}
                      {c.n_tasks !== undefined ? ` on ${c.n_tasks} tasks` : ''}
                    </Hint>
                    <Hint as="div" id="map.cell.point" tabStop={false} className="text-[15px] font-bold leading-[1.45]">
                      {c.ci_high - c.ci_low > 0.6 ? '—' : pct(c.point)}
                    </Hint>
                    <Hint as="div" id="map.cell.interval" tabStop={false} className="text-[14px] leading-[1.4] text-on-surface-muted">
                      {c.ci_high - c.ci_low > 0.6 ? 'interval too wide' : `[${pct(c.ci_low)}, ${pct(c.ci_high)}]`}
                    </Hint>
                    {/* every rendered number carries its apparatus — the reader can tell which instrument produced it */}
                    <Hint as="div" id="map.cell.apparatus" tabStop={false} className="font-mono text-[12px] leading-[1.4] text-on-surface-muted">
                      app {c.apparatus_versions.join(', ') || '—'}
                    </Hint>
                    <Hint as="div" id="map.cell.signoff" tabStop={false} className="text-[14px] leading-[1.4] text-on-surface-muted">
                      {sign?.state === 'due' && canSign ? (
                        <Link to={`/signoff?repo=${encodeURIComponent(repo)}&cell=${encodeURIComponent(`${c.capability_class}|${c.size}`)}`}>{last}</Link>
                      ) : (
                        last
                      )}
                    </Hint>
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
 * gate, n, the class × size, the rate with its interval, who signed and when, and what it
 * says nothing about. Every figure comes from the sign-off's STAMPED snapshot (what the
 * approver attested, hash-covered), never from the cell as it reads now: rows added since
 * signing change the cell's statistics without changing what was signed. When the cell has
 * moved on, the sentence says so with the current n. Null when no cell is signed.
 */
export function licenseSentence(repo: string, map: CapabilityMap & { controls?: ControlsVerdict }, signoffs: Signoff[]): string | null {
  const signed = map.cells
    .map((c) => ({ c, s: signStateOf(c, signoffs) }))
    .filter((x) => x.s.state === 'signed' && x.s.signoff)
    .sort((a, b) => b.c.n - a.c.n)[0]
  if (!signed || !signed.s.signoff) return null
  const c = signed.c
  const so = signed.s.signoff
  const ev = so.evidence
  const apparatus = ev.apparatus_versions.join(', ') || '—'
  const belts = c.belt_sets?.join(', ') || '—'
  const gate = map.controls?.state ? `a ${map.controls.state} controls gate` : 'the controls gate'
  const moved = c.n !== ev.n ? ` The cell has since grown to n=${c.n} (${pct(c.point)}); that is not what was signed.` : ''
  return `On ${repo} at apparatus ${apparatus}, under belt set ${belts} and ${gate}, ${ev.n} sighted attempts at ${c.capability_class} × ${c.size} ${builderClause(map)} were graded clean at ${pct(ev.point)} (95% Wilson ${pct(ev.ci_low)}–${pct(ev.ci_high)}) with false-Q1 ${ev.false_q1}, as signed by ${approverName(so)} on ${new Date(so.created).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}.${moved} It says nothing about any other repository, class, size, builder or model.`
}

/**
 * The builder and model the rate is about — EVIDENCE-AND-CLAIMS §7 forbids any rate without
 * them. This table is the class × size projection, so a sign-off here spans every builder
 * (a sign-off scoped to one builder never covers a class × size cell —
 * `signoffScopeMatches`); the sentence says so and names the models the map's rows hold,
 * never a builder it invented. With no model on the map it points at the signed rows.
 */
function builderClause(map: CapabilityMap): string {
  const models = map.models.filter((m) => m && m !== '*')
  return models.length > 0 ? `across every builder on the map (${models.length === 1 ? 'model' : 'models'} ${models.join(', ')} — the signed rows name their builder; open the cell)` : 'by the builders and models recorded on the signed rows (open the cell)'
}
