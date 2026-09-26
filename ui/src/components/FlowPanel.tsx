/**
 * FlowPanel — one value stream's own lead time, spend and counts, on the screen that owns it.
 *
 * Navigation
 * ----------
 * What it is:   The `FlowPanel` card: the MEASURE half of `docs/dod/streams/<stream>.md`,
 *               rendered from `GET /flow` on the screen that owns that stream.
 * What it does: Shows how long the stream's named milestones take (median, with its n and the
 *               range), what it spent (only the rows whose cost is a measurement, with how many
 *               are unpriced), its counts, and — named, never derived — the figures its
 *               definition of done asks for that nothing records, each with the gap that would
 *               close it. An unmeasured duration reads as a dash with the reason underneath,
 *               never as a zero.
 * How:          `useFlow(repo)` once per repository (five panels, one request) → the stream's
 *               entry → a `StatTile` per lead time and one for the spend, a definition list of
 *               counts, and the not-captured list; `fmtDuration` / `fmtUsd` do the formatting
 *               and the hint id comes from `FLOW_HINTS` keyed by the server's own key.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useFlow`), ui/src/api/types.ts (`Flow`, `StreamFlow`),
 *               ui/src/components/StatTile.tsx (every figure carries n and its apparatus),
 *               ui/src/help/hints.ts (the `flow.*` shared vocabulary this derives),
 *               ui/src/lib/format.ts (`fmtDuration`, `fmtUsd`, `fmtInt`),
 *               src/crb/server/routes/flow.py (the endpoint), docs/dod/streams/measure.md
 *               (the MEASURE criteria these figures answer)
 * Tested by:    ui/src/components/FlowPanel.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   a stream gains a milestone pair (add its `flow.<key>` hint — the panel picks the
 *               figure up on its own); never for a new repository.
 * Claims:       Every figure here is derived from stored records and carries its n
 *               (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
 */
import { useFlow } from '../api/hooks'
import type { LeadTime, StreamFlow } from '../api/types'
import type { HintId } from '../help/hints'
import { fmtDuration, fmtInt, fmtUsd } from '../lib/format'
import { Card } from './Card'
import { Hint } from './Hint'
import { StatTile } from './StatTile'

/** The hint for each milestone pair the server can name, keyed by its own `key`. */
const FLOW_HINTS: Record<string, HintId> = {
  registered_to_controls: 'flow.registered_to_controls',
  queued_to_graded: 'flow.queued_to_graded',
  first_row_to_bar: 'flow.first_row_to_bar',
  accepted_to_signed: 'flow.accepted_to_signed',
  registered_to_pr: 'flow.registered_to_pr',
  pr_to_merged: 'flow.pr_to_merged',
  registered_to_merged: 'flow.registered_to_merged',
  refusal_to_strengthening: 'flow.refusal_to_strengthening',
  password_set_to_signed_in: 'flow.password_set_to_signed_in',
}

/** `graded_rows` → `graded rows` — the counts are read, not parsed. */
function words(key: string): string {
  return key.replace(/_/g, ' ')
}

/** The range under a measured duration, or the server's sentence when nothing was measured. */
function footerOf(lt: LeadTime): string {
  if (lt.n === 0) return lt.reason
  const range = lt.min_s === null || lt.max_s === null ? '' : `fastest ${fmtDuration(lt.min_s)}, slowest ${fmtDuration(lt.max_s)}`
  const dropped = lt.dropped > 0 ? `${fmtInt(lt.dropped)} pair(s) had an unreadable or out-of-order stamp and were left out` : ''
  return [range, dropped].filter(Boolean).join(' · ')
}

interface FlowPanelProps {
  /** The stream id as `docs/dod/streams/` names it, e.g. `manufacture-and-deliver`. */
  stream: string
  /** The repository the reading is keyed by; '' while none is chosen. */
  repo: string
  /** The card's heading; defaults to the stream's own name from the server. */
  title?: string
}

/**
 * One stream's flow figures. Renders nothing while the query is in flight or the stream is
 * absent from the reading, so a screen never shows a half-built card; an error is left to the
 * screen's own boundary — this panel never invents a number to fill a gap.
 */
export function FlowPanel({ stream, repo, title }: FlowPanelProps) {
  const q = useFlow(repo)
  const reading = q.data
  const s: StreamFlow | undefined = reading?.streams.find((x) => x.stream === stream)
  if (!reading || !s) return null
  const apparatus = `apparatus ${reading.apparatus} · median · ${reading.method}`
  const counts = Object.entries(s.counts)
  return (
    <Card
      title={title ?? `How this flows: ${s.name}`}
      eyebrow="Derived from the records this product already keeps"
      eyebrowHint="flow.reading"
      id={`flow-${stream}`}
      className="mt-6"
    >
      <div className="flex flex-wrap gap-3" data-testid={`flow-tiles-${stream}`}>
        {s.lead_times.map((lt) => (
          <StatTile
            key={lt.key}
            label={lt.label}
            value={fmtDuration(lt.median_s)}
            n={lt.n}
            apparatus={apparatus}
            hint={FLOW_HINTS[lt.key] ?? 'flow.lead_time'}
            footer={footerOf(lt)}
            data-testid={`flow-${lt.key}`}
          />
        ))}
        <StatTile
          label="Spend"
          value={fmtUsd(s.spend.usd)}
          n={s.spend.rows_priced}
          apparatus={`apparatus ${reading.apparatus} · sum of the rows whose cost is a measurement`}
          hint="flow.spend"
          footer={`${s.spend_label}. ${s.spend.rows_unpriced > 0 ? `${fmtInt(s.spend.rows_unpriced)} row(s) reported no price and are not counted as zero, so this is a floor.` : 'Every row counted here reported its own price.'}`}
          data-testid={`flow-spend-${stream}`}
        />
        {s.per_unit_label !== '' && (
          <StatTile
            label={`Cost ${s.per_unit_label}`}
            value={fmtUsd(s.per_unit)}
            n={s.spend.rows_priced}
            apparatus={`apparatus ${reading.apparatus} · the priced rows divided by the deliveries`}
            hint="flow.per_unit"
            footer={s.per_unit === null ? 'Unmeasured: either nothing is priced yet or nothing has been delivered.' : s.spend_label}
            data-testid={`flow-per-unit-${stream}`}
          />
        )}
      </div>
      {counts.length > 0 && (
        <Hint as="dl" id="flow.counts" className="mt-4 grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 border-t border-border pt-3 text-[13px] sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto]">
          {counts.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="border-b border-border py-1 text-on-surface-muted">{words(key)}</dt>
              <dd className="num border-b border-border py-1 text-right">{fmtInt(value)}</dd>
            </div>
          ))}
        </Hint>
      )}
      {s.not_captured.length > 0 && (
        <Hint as="div" id="flow.not_captured" className="mt-4 border-t border-border pt-3">
          <h3 className="m-0 text-[13px] font-semibold">Not captured, so not shown</h3>
          <ul className="m-0 mt-1 list-none p-0 text-[13px] text-on-surface-muted">
            {s.not_captured.map((nc) => (
              <li key={nc.figure} className="py-0.5">
                {nc.figure} — {nc.why}. Gap {nc.gap}.
              </li>
            ))}
          </ul>
        </Hint>
      )}
    </Card>
  )
}
