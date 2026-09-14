import { Pill } from '../../components/Pill'
import { fmtInt, fmtPct } from '../../lib/format'
import { TONE_TEXT } from '../../lib/verdict'
import { KIND_DISPLAY, controlsDisplay, type ControlsVerdict, type FailureSplit } from './contract'

/**
 * The failure split — `red · budget · protocol · harness · DQ` — shown wherever a
 * rate is shown (review action #4). Colour never travels alone: every count has its
 * word, and the accessible label spells the kind out. Zero counts stay visible so
 * "no harness errors" is a statement, not an absence.
 */
export function FailureSplitPills({ split, size = 'xs', ...rest }: { split: FailureSplit; size?: 'xs' | 'sm'; 'data-testid'?: string }) {
  return (
    <span className="num inline-flex flex-wrap items-center gap-1" data-testid={rest['data-testid'] ?? 'failure-split'} aria-label={KIND_DISPLAY.map((k) => `${k.short} ${split[k.key]}`).join(', ')}>
      {KIND_DISPLAY.map((k) => {
        const n = split[k.key]
        return (
          <span key={k.key} title={k.long} data-testid={`kind-${k.key}`} className={`inline-flex items-baseline gap-0.5 ${size === 'xs' ? 'text-[10px]' : 'text-xs'} ${n > 0 ? TONE_TEXT[k.tone] : 'text-on-surface-muted/70'}`}>
            <span>{k.short}</span>
            <span className={n > 0 ? 'font-semibold' : ''}>{fmtInt(n)}</span>
          </span>
        )
      })}
    </span>
  )
}

/**
 * `model n/(n+red)` — the model's rate on fair, finished attempts, smaller and NEXT TO
 * the all-rows point, never instead of it. Reads "—" when no fair attempt exists.
 */
export function ModelPointLine({ modelPoint, modelN, clean, size = 'xs' }: { modelPoint: number | null; modelN: number; clean: number; size?: 'xs' | 'sm' }) {
  const cls = size === 'xs' ? 'text-[10px]' : 'text-xs'
  return (
    <span className={`num ${cls} text-on-surface-muted`} data-testid="model-point" title="clean / (clean + builder red): the model's rate where it got a fair, finished attempt — diagnostic, never the routing input">
      model {modelPoint === null ? '—' : fmtPct(modelPoint, 0)} <span className="opacity-80">({fmtInt(clean)}/{fmtInt(modelN)})</span>
    </span>
  )
}

/** The repo-level controls verdict pill: passed k of N / FAILED / thin k of N / escapes / unmeasured. */
export function ControlsPill({ verdict, size = 'sm', reason }: { verdict: ControlsVerdict | null | undefined; size?: 'xs' | 'sm'; reason?: string }) {
  const d = controlsDisplay(verdict)
  const state = verdict?.measured ? verdict.state : 'unmeasured'
  return (
    <Pill tone={d.tone} glyph={d.glyph} size={size} label={reason ? `${d.describe} ${reason}` : d.describe} data-testid={`controls-${state}`}>
      {d.label}
    </Pill>
  )
}
