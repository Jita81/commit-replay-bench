/**
 * The decisions inbox as data: every point where a human's sign-off or judgement is due.
 *
 * Navigation
 * ----------
 * What it is:   The inbox's row type, its kinds and their labels (`KIND_LABEL`), and
 *               `decisionsFor` — the cell and item rows for ONE repository, folded in the browser
 *               for the Results page's "waiting on a person" panel: a cell that routes `deliver`
 *               and is not yet signed (an attestation is due); a cell held by its oracle or its
 *               controls (`strengthen`, G-535); a cell the rule sent to a human and why; a cell
 *               that must not ship; a factory item with an unsigned structural gap; an item the
 *               entry gate did not build (no proven standard, or missing context — ADR-0026
 *               item 8); an item routed to a human; a review that asked for rework; a delivery
 *               the route gate withheld.
 * What it does: Names every kind of point where human sign-off is surfaced, in the order of
 *               what blocks what, so the Decisions screen can label and render the rows the
 *               server serves (`GET /decisions`, F6 — the inbox is derived there once, not in
 *               every browser) and the Results page can fold its own panel. Nothing here
 *               decides: every row is a fact from the ledger or the factory chain with a link to
 *               the surface that records the human's answer. The server's derivation and
 *               `decisionsFor` read one fixture (`decisions.parity.json`) and must both produce
 *               its rows, so the two cannot drift apart unnoticed.
 * How:          Pure functions over the API types; no fetching. `kind` orders the rows;
 *               `act` is the verb the button shows; `href` is the screen with the cell / item
 *               preselected; a cell row also carries its `reasonCode` on its own so the
 *               screen can render it as a term with its meaning (`evidenceStats` is the
 *               evidence line without the code). `STRENGTHEN_REASONS` is
 *               `crb.core.learn.STRENGTHEN_REASONS`, pinned by tests/test_decisions_kinds.py.
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
 * Tested by:    ui/src/screens/Decisions/decisions.test.ts, tests/test_decisions_kinds.py,
 *               tests/test_server_decisions.py (the shared fixture)
 * Touch when:   never for a new repository; a new human act is added to the product (a row kind
 *               in src/crb/server/decisions.py first, its label and order here, its surface there).
 */

import type { CapabilityCell, FactoryTask, LibraryIndex, PreventionRegister, Signoff } from '../../api/types'

/**
 * The routing reasons test-strengthening work can move — a weak oracle, escaped or thin
 * negative controls. A cell held for one of them is a `strengthen` row (G-535), never a
 * `routed_human` row beside it. The same tuple as `crb.core.learn.STRENGTHEN_REASONS`.
 */
export const STRENGTHEN_REASONS = ['oracle_weak', 'controls_escapes', 'controls_thin'] as const

export type DecisionKind =
  | 'signoff_due' // a cell routes deliver and no active sign-off exists
  | 'routed_human' // the rule sent a cell to a human (oracle weak, controls, escapes)
  | 'do_not_ship' // false-Q1 in the cell — an instrument defect to investigate
  | 'gap_unsigned' // a factory item is blocked on a structural gap
  | 'not_built' // the entry gate stopped a factory item: no proven standard, or missing context (ADR-0026 item 8)
  | 'item_human' // a factory item was routed to a human
  | 'rework' // a review asked for rework
  | 'delivery_withheld' // the route gate withheld a clean build's PR
  | 'prevention' // the prevention loop filed an item nobody owns, a class reopened, or a change was retired for harm (ADR-0020)
  | 'entry_to_sign' // a library entry waits for its second person (or, when mined, for a sponsor) — ADR-0026 item 10
  | 'entry_stale' // a signed library entry's source file changed at the head; it counts for nothing until signed again
  | 'entry_retired' // a library entry was retired by measurement (its arm's reading) — read why
  | 'signoff_stale' // an attestation signed on an earlier instrument, or by a leaver: revoke or re-sign (ADR-0015)
  | 'strengthen' // a cell held by its oracle or its controls: strengthen the tests (G-535)
  | 'remeasure' // a cell whose evidence predates the apparatus in force: queue its re-measurement (server only)

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
  /** Whether the person reading can take the act (served by `GET /decisions`; absent on a browser fold). */
  canAct?: boolean
  /** On a `signoff_stale` row: the attestation as `GET /signoffs` serves it. */
  signoff?: Signoff
}

/** What blocks what — the same ranks as `ORDER` in src/crb/server/decisions.py (tests/test_decisions_kinds.py). */
export const ORDER: Record<DecisionKind, number> = {
  do_not_ship: 0,
  gap_unsigned: 1,
  not_built: 2,
  signoff_due: 3,
  signoff_stale: 4,
  rework: 5,
  delivery_withheld: 6,
  prevention: 7,
  entry_stale: 8,
  entry_to_sign: 9,
  item_human: 10,
  strengthen: 11,
  routed_human: 12,
  remeasure: 13,
  entry_retired: 14,
}

function isStrengthen(code: string | undefined): boolean {
  return (STRENGTHEN_REASONS as readonly string[]).includes(code ?? '')
}

/**
 * The clause a held cell is held by: its reason code when that is one test-strengthening work can
 * move, else the first such shortfall (routing.v2 lists every failing clause) — `crb.core.learn.
 * hold_reason`. `null` when the cell is not held by its tests.
 */
export function holdReason(c: Pick<CapabilityCell, 'reason_code' | 'shortfalls'>): string | null {
  if (isStrengthen(c.reason_code)) return c.reason_code ?? null
  return (c.shortfalls ?? []).find((s) => isStrengthen(s.code))?.code ?? null
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

/**
 * The prevention loop's rows (ADR-0020 §9): a filed item nobody has registered ("a prevention
 * needs an owner" — an operator's act), a class that reopened after it closed, and a change the
 * loop retired for harm (both for anyone to read). Each links to the class on the Learn page.
 * The key is the class signature with what is due — `<signature>|owner|<item id>`,
 * `<signature>|reopened`, `<signature>|harm` — the identity `src/crb/server/decisions.py`
 * keeps the clock under.
 */
export function preventionDecisions(repo: string, register: PreventionRegister | null | undefined): Decision[] {
  if (!register) return []
  const out: Decision[] = []
  const at = (sig: string) => `/learn?repo=${encodeURIComponent(repo)}&class=${encodeURIComponent(sig)}#prevention`
  for (const e of register.entries) {
    const ev = `${e.stratum.k} of ${e.stratum.n} ${e.stratum.mode} first attempts on ${e.tasks} tasks · ${e.status}`
    for (const p of e.proposals) {
      if (p.registered || p.scope === 'product') continue
      out.push({ kind: 'prevention', repo, key: `${e.signature}|owner|${p.item_id}`, title: `A prevention needs an owner — ${e.signature}: ${p.title}`, evidence: `${ev} · ${p.level}`, act: 'Register', href: at(e.signature), role: 'operator' })
    }
    if (e.qualifiers.includes('reopened')) {
      out.push({ kind: 'prevention', repo, key: `${e.signature}|reopened`, title: `${e.signature} reopened after it was closed`, evidence: ev, act: 'Read why', href: at(e.signature), role: 'viewer' })
    }
    if (e.history.some((h) => h.kind === 'decided' && h.summary === 'harm')) {
      out.push({ kind: 'prevention', repo, key: `${e.signature}|harm`, title: `A change for ${e.signature} was retired for harm`, evidence: ev, act: 'Read why', href: at(e.signature), role: 'viewer' })
    }
  }
  return out
}

/**
 * The context library's rows (ADR-0026 item 10): an entry waiting for its second person to sign
 * (an approver's act — or, for a mined or drafted proposal nobody has adopted, an operator's
 * Sponsor), a signed entry whose source file changed (an approver re-signs or retires it), and
 * an entry the measurement retired (anyone reads why). Each links to the library's index.
 * `me` is the viewer's account id: an entry they sponsored is never theirs to sign or re-sign
 * (the API refuses it `same_person`), so its row is a read-only one naming who acts.
 */
export function libraryDecisions(repo: string, library: LibraryIndex | null | undefined, me = ''): Decision[] {
  if (!library) return []
  const out: Decision[] = []
  const href = `/library/${encodeURIComponent(repo)}#index`
  for (const e of library.entries) {
    const who = e.sponsor_name || e.sponsor
    const mine = me !== '' && e.sponsor === me
    if (e.status === 'proposed' && !e.sponsor) {
      out.push({ kind: 'entry_to_sign', repo, key: e.entry_id, title: `${e.entry_id} was proposed by ${e.entry.proposed_by} and needs a person to sponsor it`, evidence: `${e.entry.kind} · ${e.entry.title}`, act: 'Sponsor', href, role: 'operator' })
    } else if (e.status === 'proposed' && mine) {
      out.push({ kind: 'entry_to_sign', repo, key: e.entry_id, title: `${e.entry_id} waits for another approver to sign it — you sponsored it`, evidence: `sponsored by ${who} · ${e.entry.title}`, act: 'Read', href, role: 'viewer' })
    } else if (e.status === 'proposed') {
      out.push({ kind: 'entry_to_sign', repo, key: e.entry_id, title: `${e.entry_id} waits for a second person to sign it`, evidence: `sponsored by ${who} · ${e.entry.title}`, act: 'Sign', href, role: 'approver' })
    } else if (e.status === 'stale' && mine) {
      out.push({ kind: 'entry_stale', repo, key: e.entry_id, title: `${e.entry_id} went stale: ${e.stale?.path ?? 'its source file'} changed or went — you sponsored it, so another approver signs it again`, evidence: `at ${e.stale?.head_commit.slice(0, 12) ?? 'the head'} · ${e.approver ? `signed by ${e.approver_name || e.approver}` : 'not yet signed'}`, act: 'Read', href, role: 'viewer' })
    } else if (e.status === 'stale') {
      out.push({ kind: 'entry_stale', repo, key: e.entry_id, title: `${e.entry_id} went stale: ${e.stale?.path ?? 'its source file'} changed or went`, evidence: `at ${e.stale?.head_commit.slice(0, 12) ?? 'the head'} · ${e.approver ? `signed by ${e.approver_name || e.approver}` : 'not yet signed'}`, act: 'Sign again or retire', href, role: 'approver' })
    } else if (e.status === 'retired' && e.retired?.by === 'measurement') {
      out.push({ kind: 'entry_retired', repo, key: e.entry_id, title: `${e.entry_id} was retired by measurement`, evidence: `reading ${e.retired.reading_id} · ${e.retired.reason}`, act: 'Read why', href, role: 'viewer' })
    }
  }
  return out
}

/** The rows for one repository, ordered by what blocks what. */
export function decisionsFor(input: { repo: string; cells: CapabilityCell[]; signoffs: Signoff[]; tasks: FactoryTask[]; register?: PreventionRegister | null; library?: LibraryIndex | null; me?: string }): Decision[] {
  const { repo } = input
  const q = `repo=${encodeURIComponent(repo)}`
  const out: Decision[] = []
  const signed = activeSignedKeys(input.signoffs)

  for (const c of input.cells) {
    if (c.n <= 0) continue
    const label = `${c.capability_class} × ${c.size}`
    const held = c.route !== 'do_not_ship' ? holdReason(c) : null
    const reason = held ?? c.reason_code
    const ev = `n=${c.n}${c.n_tasks !== undefined ? ` on ${c.n_tasks} tasks` : ''} · ${pct(c.point)} [${pct(c.ci_low)}, ${pct(c.ci_high)}]${reason ? ` · ${reason}` : ''}`
    const cellQ = `${q}&cell=${encodeURIComponent(cellKeyOf(c))}`
    const code = reason ? { reasonCode: reason } : {}
    if (c.route === 'do_not_ship') {
      out.push({ kind: 'do_not_ship', repo, key: cellKeyOf(c), title: `${label} must not ship — false-Q1 in the cell`, evidence: ev, ...code, act: 'Investigate', href: `/ledger?${q}`, role: 'viewer' })
    } else if (c.route === 'deliver' && !signed.has(cellKeyOf(c))) {
      out.push({ kind: 'signoff_due', repo, key: cellKeyOf(c), title: `${label} clears the bar — attest it or decline`, evidence: ev, ...code, act: 'Attest', href: `/signoff?${cellQ}`, role: 'approver' })
    } else if (held) {
      // G-535: held by its oracle or its controls — one row, the strengthening work on Learn
      out.push({ kind: 'strengthen', repo, key: cellKeyOf(c), title: `${label} is held until its tests are stronger`, evidence: ev, ...code, act: 'Strengthen the tests', href: `/learn?${q}#strengthen`, role: 'operator' })
    } else if (c.route === 'human') {
      out.push({ kind: 'routed_human', repo, key: cellKeyOf(c), title: `${label} routed to a human — ${c.reason}`, evidence: ev, ...code, act: 'Read why', href: `/routing?${q}`, role: 'viewer' })
    }
  }

  for (const t of input.tasks) {
    const itemQ = `${q}&item=${encodeURIComponent(t.id)}`
    const label = `${t.id} ${t.title}`
    if (t.entry) {
      // ADR-0026 item 8 — the item waits here, NOT BUILT: an approver may fund one calibration
      // build (never a pull request), or the ticket gains what its cell's standard needs.
      // A funded calibration build waits on the next run and asks nobody for anything.
      if (!t.calibration) {
        const fund = t.way_forward?.action === 'fund_calibration'
        out.push({
          kind: 'not_built',
          repo,
          key: t.id,
          title: `${label} is not built — ${t.entry.code.replace(/_/g, ' ')}`,
          evidence: `${t.capability_class} × ${t.size}${t.entry.needs.length > 0 ? ` · attach ${t.entry.needs.join(', ')}` : ''}`,
          act: fund ? 'Fund a calibration build' : 'Decide',
          href: `/factory?${itemQ}`,
          role: fund ? 'approver' : 'operator',
        })
      }
    } else if (t.dor_gaps.length > 0) {
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

  out.push(...preventionDecisions(repo, input.register))
  out.push(...libraryDecisions(repo, input.library, input.me))

  return out.sort((a, b) => ORDER[a.kind] - ORDER[b.kind] || a.title.localeCompare(b.title))
}

export const KIND_LABEL: Record<DecisionKind, string> = {
  signoff_due: 'Sign-off due',
  routed_human: 'Routed to a human',
  do_not_ship: 'Do not ship',
  gap_unsigned: 'Structural gap',
  not_built: 'Not built',
  item_human: 'Item needs a decision',
  rework: 'Rework requested',
  delivery_withheld: 'Delivery withheld',
  prevention: 'Prevention',
  entry_to_sign: 'Library entry to sign',
  entry_stale: 'Library entry stale',
  entry_retired: 'Library entry retired',
  signoff_stale: 'Sign-off stale',
  strengthen: 'Strengthen the tests',
  remeasure: 'Re-measure',
}
