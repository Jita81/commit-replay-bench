/**
 * The failure split, the model point and the controls pill — shown wherever a rate is shown.
 *
 * Navigation
 * ----------
 * What it is:   Three small components: `FailureSplitPills` (red · lint · budget · protocol ·
 *               harness · outage · DQ), `ModelPointLine` (the model's rate on fair attempts,
 *               next to the routing rate) and `ControlsPill` (the repo's controls verdict).
 * What it does: Puts the WHY behind every pass rate on the page: how many misses were the
 *               model's, how many the budget's, how many the instrument's (protocol /
 *               harness) and how many were disqualified. Zero counts stay visible so "no
 *               harness errors" is a statement; the model point is always smaller and beside
 *               the all-rows point, never instead of it.
 *               Each kind, the model point and the controls pill is a hover / focus / tap
 *               trigger for what it means (`kind.<key>`, `stat.shared.model_rate`,
 *               `controls.<state>`), derived here so no screen writes them; no native `title`
 *               remains.
 * How:          `KIND_DISPLAY` fixes the order and wording; counts come straight from the
 *               cell's `failure_split`; `controlsDisplay` gives the pill its state; `<Hint>`
 *               wraps each element with the id derived from its key or state.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/contract.ts (`KIND_DISPLAY`, `controlsDisplay`, the
 *               types), ui/src/components/Hint.tsx (the trigger), ui/src/help/hints.ts
 *               (`kind.*`, `controls.*`, `stat.shared.model_rate`),
 *               ui/src/screens/Capability/CapabilityPage.tsx and
 *               ui/src/screens/Routing/RoutingPage.tsx (a split per cell / decision),
 *               ui/src/screens/Runs/RunDetailPage.tsx (a run's split tiles),
 *               ui/src/screens/Signoff/SignoffPage.tsx (the evidence an approver sees),
 *               ui/src/components/Pill.tsx
 * Tested by:    ui/src/help/hints-ratchet.test.tsx (the hint contract), ui/src/screens/Capability/CapabilityPage.test.tsx (`kind-*`, `model-point`,
 *               `controls-*` test ids), ui/src/screens/Routing/RoutingPage.test.tsx
 * Touch when:   a failure kind is added — one row in `KIND_DISPLAY`
 *               (ui/src/screens/Capability/contract.ts); never for a new repository.
 */
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { HINTS, type HintId } from '../../help/hints'
import { fmtInt, fmtPct } from '../../lib/format'
import { TONE_TEXT } from '../../lib/verdict'
import { KIND_DISPLAY, controlsDisplay, type ControlsVerdict, type FailureSplit } from './contract'

/** `controls.<state>` for a verdict the registry knows; a state from a newer server reads as unmeasured. */
export function controlsHint(state: string): HintId {
  const id = `controls.${state}`
  return id in HINTS ? (id as HintId) : 'controls.unmeasured'
}

/**
 * The failure split — `red · budget · protocol · harness · DQ` — shown wherever a
 * rate is shown (review action #4). Colour never travels alone: every count has its
 * word, and the accessible label spells the kind out. Zero counts stay visible so
 * "no harness errors" is a statement, not an absence.
 */
export function FailureSplitPills({ split, size = 'xs', ...rest }: { split: FailureSplit; size?: 'xs' | 'sm'; 'data-testid'?: string }) {
  return (
    <span className="num inline-flex flex-wrap items-center gap-1" data-testid={rest['data-testid'] ?? 'failure-split'} aria-label={KIND_DISPLAY.map((k) => `${k.short} ${split[k.key] ?? 0}`).join(', ')}>
      {KIND_DISPLAY.map((k) => {
        const n = split[k.key] ?? 0
        return (
          <Hint key={k.key} id={`kind.${k.key}`} data-component="pill" data-testid={`kind-${k.key}`} className={`inline-flex items-baseline gap-0.5 ${size === 'xs' ? 'text-[10px]' : 'text-xs'} ${n > 0 ? TONE_TEXT[k.tone] : 'text-on-surface-muted'}`}>
            <span>{k.short}</span>
            <span className={n > 0 ? 'font-semibold' : ''}>{fmtInt(n)}</span>
          </Hint>
        )
      })}
    </span>
  )
}

/**
 * `model n/(n+red)` — the model's rate on fair, finished attempts, smaller and NEXT TO
 * the all-rows point, never instead of it. Reads "—" when no fair attempt exists.
 */
/**
 * The model's rate on fair, finished attempts, with everything a rendered rate keeps: its
 * n (`clean/modelN`), its Wilson 95% interval when the server gave one, and the apparatus
 * versions it was measured under. `null` renders as `—` (unmeasured — never a 0%).
 */
export function ModelPointLine({
  modelPoint,
  modelN,
  clean,
  ciLow = null,
  ciHigh = null,
  apparatus = [],
  size = 'xs',
}: {
  modelPoint: number | null
  modelN: number
  clean: number
  ciLow?: number | null
  ciHigh?: number | null
  apparatus?: string[]
  size?: 'xs' | 'sm'
}) {
  const cls = size === 'xs' ? 'text-[10px]' : 'text-xs'
  const interval = modelPoint !== null && ciLow !== null && ciHigh !== null ? ` [${fmtPct(ciLow, 0)}–${fmtPct(ciHigh, 0)}]` : ''
  const app = apparatus.length ? ` · apparatus ${apparatus.join(', ')}` : ''
  return (
    <Hint id="stat.shared.model_rate" className={`num ${cls} text-on-surface-muted`} data-testid="model-point" aria-label={`model rate ${modelPoint === null ? 'unmeasured' : fmtPct(modelPoint, 0)}, ${fmtInt(clean)} of ${fmtInt(modelN)}${interval}${app}`}>
      model {modelPoint === null ? '—' : fmtPct(modelPoint, 0)} <span>({fmtInt(clean)}/{fmtInt(modelN)}{interval})</span>
    </Hint>
  )
}

/** The repo-level controls verdict pill: passed k of N / FAILED / thin k of N / escapes / unmeasured. */
export function ControlsPill({ verdict, size = 'sm', reason, minShare }: { verdict: ControlsVerdict | null | undefined; size?: 'xs' | 'sm'; reason?: string; minShare?: number }) {
  const d = controlsDisplay(verdict, minShare)
  const state = verdict?.measured ? verdict.state : 'unmeasured'
  return (
    <Pill tone={d.tone} glyph={d.glyph} size={size} label={reason ? `${d.describe} ${reason}` : d.describe} hint={controlsHint(state)} data-testid={`controls-${state}`}>
      {d.label}
    </Pill>
  )
}
