/**
 * The decisions inbox as data: every point where a human's sign-off or judgement is due.
 *
 * Navigation
 * ----------
 * What it is:   `decisionsFor` — the rows of the Decisions screen for one repository, derived
 *               from the capability map (routes), the active sign-offs and the factory tasks:
 *               a cell that routes `deliver` and is not yet signed (an attestation is due);
 *               a cell the rule sent to a human and why; a cell that must not ship; a factory
 *               item with an unsigned structural gap; an item routed to a human; a review that
 *               asked for rework; a delivery the route gate withheld.
 * What it does: Makes "the points where human sign-off is surfaced" one list, ordered by
 *               what is blocking what, each row naming the act, the evidence behind it and
 *               where the act happens — so an approver sees what matters when it matters and
 *               a viewer sees the same list read-only. Nothing here decides: every row is a
 *               fact from the ledger or the factory chain with a link to the surface that
 *               records the human's answer.
 * How:          Pure functions over the API types; no fetching. `kind` orders the rows;
 *               `act` is the verb the button shows; `href` is the screen with the cell / item
 *               preselected; a cell row also carries its `reasonCode` on its own so the
 *               screen can render it as a term with its meaning (`evidenceStats` is the
 *               evidence line without the code).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md (the routes and reason codes),
 *               docs/adr/0006-zero-raw-retention-and-evidence-packs.md (a sign-off is a
 *               human attestation anchored to evidence)
 * Works with:   ui/src/screens/Decisions/DecisionsPage.tsx (renders it),
 *               ui/src/screens/Capability/contract.ts (`REASON_DISPLAY` — the meaning of a
 *               `reasonCode`), ui/src/screens/Results/ResultsPage.tsx (the same rows for one
 *               repository),
 *               ui/src/screens/Signoff/SignoffPage.tsx (`?cell=` preselects the cell),
 *               ui/src/screens/Factory/FactoryPage.tsx (`?item=` scrolls to the item),
 *               src/crb/factory/loop.py (the route gate whose withholding shows here),
 *               src/crb/server/decisions.py (the same rows derived on the server, which keeps
 *               the clock: `kind` + `key` is the identity the ages join on)
 * Tested by:    ui/src/screens/Decisions/decisions.test.ts
 * Touch when:   a new human act is added to the product (a row kind here, its surface there).
 */

import type { CapabilityCell, FactoryTask, Signoff } from '../../api/types'

export type DecisionKind =
  | 'signoff_due' // a cell routes deliver and no active sign-off exists
  | 'routed_human' // the rule sent a cell to a human (oracle weak, controls, escapes)
  | 'do_not_ship' // false-Q1 in the cell — an instrument defect to investigate
  | 'gap_unsigned' // a factory item is blocked on a structural gap
  | 'item_human' // a factory item was routed to a human
  | 'rework' // a review asked for rework
  | 'delivery_withheld' // the route gate withheld a clean build's PR

export interface Decision {
  kind: DecisionKind
  repo: string
  /**
   * What the act is about — the cell (`<class>|<size>`) or the item id. With `kind` it is the
   * row's identity, and the SAME identity the server's own derivation computes
   * (`src/crb/server/decisions.py`), which is how `GET /decisions` ages join onto these rows.
   */
  key: string
  /** What is being decided, as the person would say it. */
  title: string
  /** The evidence line: n, interval, reason code, gaps. */
  evidence: string
  /** The routing reason code on a cell row (the tail of `evidence`), for rendering as a term. */
  reasonCode?: string
  /** The verb on the button. */
  act: string
  /** Where the act is recorded (an approver's surface) or read (a viewer's). */
  href: string
  /** The role that can perform the act. */
  role: 'approver' | 'operator' | 'viewer'
  /** When this row FIRST became due (ISO-8601), from `GET /decisions`; absent until it answers. */
  dueSince?: string
  /** How long it has been due, in whole seconds — the server's own clock, never the browser's. */
  ageS?: number
}

const ORDER: Record<DecisionKind, number> = {
  do_not_ship: 0,
  gap_unsigned: 1,
  signoff_due: 2,
  rework: 3,
  delivery_withheld: 4,
  item_human: 5,
  routed_human: 6,
}

function cellKeyOf(c: { capability_class: string; size: string }): string {
  return `${c.capability_class}|${c.size}`
}

function activeSignedKeys(signoffs: Signoff[]): Set<string> {
  const keys = new Set<string>()
  for (const s of signoffs) {
    if (s.revoked) continue
    const cls = s.cell.capability_class
    const size = s.cell.size
    if (cls && size) keys.add(`${cls}|${size}`)
  }
  return keys
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`
}

/**
 * How long a decision has been waiting, in the units a person thinks in (G-516). Days once it
 * is past a day, because a wait measured in days is the thing worth seeing; `null` when the
 * server has not answered yet, which renders as nothing rather than as "0 s".
 */
export function waitedFor(ageS: number | undefined): string | null {
  if (ageS === undefined || !Number.isFinite(ageS) || ageS < 0) return null
  if (ageS < 60) return 'just now'
  if (ageS < 3600) return `${Math.floor(ageS / 60)} min`
  if (ageS < 86400) {
    const h = Math.floor(ageS / 3600)
    return `${h} hour${h === 1 ? '' : 's'}`
  }
  const d = Math.floor(ageS / 86400)
  return `${d} day${d === 1 ? '' : 's'}`
}

/** The evidence line without its trailing reason code — the screen renders the code as a term. */
export function evidenceStats(d: Pick<Decision, 'evidence' | 'reasonCode'>): string {
  const tail = d.reasonCode ? ` · ${d.reasonCode}` : ''
  return tail && d.evidence.endsWith(tail) ? d.evidence.slice(0, -tail.length) : d.evidence
}

/** The rows for one repository, ordered by what blocks what. */
export function decisionsFor(input: { repo: string; cells: CapabilityCell[]; signoffs: Signoff[]; tasks: FactoryTask[] }): Decision[] {
  const { repo } = input
  const q = `repo=${encodeURIComponent(repo)}`
  const out: Decision[] = []
  const signed = activeSignedKeys(input.signoffs)

  for (const c of input.cells) {
    if (c.n <= 0) continue
    const label = `${c.capability_class} × ${c.size}`
    const ev = `n=${c.n}${c.n_tasks !== undefined ? ` on ${c.n_tasks} tasks` : ''} · ${pct(c.point)} [${pct(c.ci_low)}, ${pct(c.ci_high)}]${c.reason_code ? ` · ${c.reason_code}` : ''}`
    const cellQ = `${q}&cell=${encodeURIComponent(cellKeyOf(c))}`
    const code = c.reason_code ? { reasonCode: c.reason_code } : {}
    if (c.route === 'do_not_ship') {
      out.push({ kind: 'do_not_ship', repo, key: cellKeyOf(c), title: `${label} must not ship — false-Q1 in the cell`, evidence: ev, ...code, act: 'Investigate', href: `/ledger?${q}`, role: 'viewer' })
    } else if (c.route === 'deliver' && !signed.has(cellKeyOf(c))) {
      out.push({ kind: 'signoff_due', repo, key: cellKeyOf(c), title: `${label} clears the bar — attest it or decline`, evidence: ev, ...code, act: 'Attest', href: `/signoff?${cellQ}`, role: 'approver' })
    } else if (c.route === 'human') {
      out.push({ kind: 'routed_human', repo, key: cellKeyOf(c), title: `${label} routed to a human — ${c.reason}`, evidence: ev, ...code, act: 'Read why', href: `/routing?${q}`, role: 'viewer' })
    }
  }

  for (const t of input.tasks) {
    const itemQ = `${q}&item=${encodeURIComponent(t.id)}`
    const label = `${t.id} ${t.title}`
    if (t.dor_gaps.length > 0) {
      out.push({
        kind: 'gap_unsigned',
        repo,
        key: t.id,
        title: `${label} is blocked on ${t.dor_gaps.length} structural gap${t.dor_gaps.length === 1 ? '' : 's'}`,
        evidence: t.dor_gaps.join(', '),
        act: 'Sign a gap',
        href: `/factory?${itemQ}`,
        role: 'approver',
      })
    } else if (t.route_hint === 'human' && t.status !== 'accepted') {
      out.push({ kind: 'item_human', repo, key: t.id, title: `${label} routed to a human`, evidence: `${t.capability_class} × ${t.size} · ${t.status}`, act: 'Decide', href: `/factory?${itemQ}`, role: 'operator' })
    }
    if (t.review_verdict === 'accept_with_edit' || t.review_verdict === 'reject') {
      out.push({ kind: 'rework', repo, key: t.id, title: `${label} — the review said ${t.review_verdict.replace(/_/g, ' ')}`, evidence: `build ${t.build_status} · ${t.status}`, act: 'Review', href: `/factory?${itemQ}`, role: 'operator' })
    }
    if (t.build_status === 'clean' && !t.pr_url && (t.status === 'accepted' || t.status === 'rejected') && t.last_event === 'delivery.refused') {
      out.push({ kind: 'delivery_withheld', repo, key: t.id, title: `${label} built clean — delivery withheld by the route`, evidence: `${t.capability_class} × ${t.size}`, act: 'See the route', href: `/factory?${itemQ}`, role: 'approver' })
    }
  }

  return out.sort((a, b) => ORDER[a.kind] - ORDER[b.kind] || a.title.localeCompare(b.title))
}

export const KIND_LABEL: Record<DecisionKind, string> = {
  signoff_due: 'Sign-off due',
  routed_human: 'Routed to a human',
  do_not_ship: 'Do not ship',
  gap_unsigned: 'Structural gap',
  item_human: 'Item needs a decision',
  rework: 'Rework requested',
  delivery_withheld: 'Delivery withheld',
}
