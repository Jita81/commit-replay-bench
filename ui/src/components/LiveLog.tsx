/**
 * LiveLog — the virtualised StepEvent list behind a run's SSE stream.
 *
 * Navigation
 * ----------
 * What it is:   The `LiveLog` component: stream status pill, counters and a virtualised row
 *               list (time · stage · action · status glyph · task · duration · cost · payload,
 *               with one plain sentence per action underneath), plus `logRowDisplay`.
 * What it does: Renders only the visible window of a stream that may hold thousands of events,
 *               follows the tail while the reader is at the bottom and stops the moment they
 *               scroll up, and reports reconnects, malformed frames dropped and the stream
 *               error verbatim — the log never hides a gap. A `grade.belt` row reads as
 *               "<belt> ✓" or "<belt> ✗ — <cause>" from the payload (a failed belt is a
 *               verdict, so the envelope status stays ok; the glyph goes red anyway), and any
 *               event carrying `error_message` gets the red glyph with the message in place
 *               of the payload summary. Every row explains its action with `actionHelp`
 *               ("Explain each row", on by default, one checkbox to switch off).
 * How:          Fixed row height (taller with explanations on) → slice `[start, end)` from
 *               `scrollTop` with overscan → absolutely positioned rows inside a full-height
 *               spacer, so the explanation costs nothing per event; `role="log"`,
 *               `aria-live="polite"`, and the scroll region is focusable (WCAG 2.1.1).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Hint.tsx (the stream pill, the two checkboxes, every
 *               row's status glyph and task link carry a hint), ui/src/api/sse.ts (`SseStatus` and the snapshot fields this renders),
 *               ui/src/api/hooks.ts (`useRunEvents` — the source),
 *               ui/src/screens/Runs/RunDetailPage.tsx
 *               (the only consumer), ui/src/lib/verdict.ts (`stepStatusDisplay`,
 *               `actionHelp` — the sentence under each row), ui/src/lib/format.ts (`fmtTime`,
 *               `fmtMs`, `fmtUsd`), src/crb/core/grade.py (the `grade.belt` payload this reads:
 *               belt, value, new, rc, timed_out, detected)
 * Tested by:    ui/src/screens/Runs/RunDetailPage.test.tsx (events from a fake EventSource
 *               appear as rows; a failed belt and an error row are red; the explanation
 *               line and its toggle), ui/e2e/walkthrough/03-mine.spec.ts (`expectLogAction` on
 *               a real worker's events), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe
 *               on the run page)
 * Touch when:   `StepEvent` gains a field worth a column (ui/src/api/types.ts first); never for
 *               a new repository.
 */
import { useEffect, useRef, useState } from 'react'
import type { StepEvent } from '../api/types'
import type { SseStatus } from '../api/sse'
import { fmtMs, fmtTime, fmtUsd, shortId } from '../lib/format'
import { TONE_TEXT, actionHelp, stepStatusDisplay, type Display } from '../lib/verdict'
import { EmptyState } from './EmptyState'
import { Hint } from './Hint'
import { Pill } from './Pill'

interface LiveLogProps {
  events: readonly StepEvent[]
  status: SseStatus
  reconnects?: number
  dropped?: number
  error?: string | null
  height?: number
  onSelectTask?: (taskId: string) => void
}

/** Fixed row height in px — the virtualiser depends on every row being exactly this tall. */
const ROW_H = 26
/** Row height with the explanation line under it (`ROW_H` plus a 16 px sentence). */
const ROW_H_EXPLAINED = 42
/** Rows rendered beyond the visible window on each side, so fast scrolling never shows a blank band. */
const OVERSCAN = 12

/** Stream status → pill copy; `done` is the server's verdict, `closed` is ours. */
const STATUS_COPY: Record<SseStatus, { label: string; tone: 'green' | 'amber' | 'red' | 'primary' | 'muted'; glyph: string }> = {
  idle: { label: 'Idle', tone: 'muted', glyph: '·' },
  connecting: { label: 'Connecting', tone: 'primary', glyph: '…' },
  open: { label: 'Live', tone: 'green', glyph: '●' },
  reconnecting: { label: 'Reconnecting', tone: 'amber', glyph: '↻' },
  done: { label: 'Complete', tone: 'muted', glyph: '✓' },
  closed: { label: 'Closed', tone: 'muted', glyph: '—' },
}

/** The first four payload keys as `k=v`, each value truncated — a glance line, with the full payload in the row's `title`. */
function payloadSummary(p: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(p)) {
    if (parts.length >= 4) {
      parts.push('…')
      break
    }
    const s = typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : Array.isArray(v) ? `[${v.length}]` : v === null ? 'null' : '{…}'
    parts.push(`${k}=${s.length > 40 ? `${s.slice(0, 40)}…` : s}`)
  }
  return parts.join('  ')
}

/** A row's glyph, tone and the text that stands in the payload column. */
export interface LogRowDisplay extends Display {
  /** The glance text: the payload summary, a belt verdict, or the error message. */
  summary: string
  /** `true` when the summary is an error message (rendered red). */
  isError: boolean
}

/** Why a belt failed, from the fields `grade.belt` carries (src/crb/core/grade.py): new failures, rc / timeout, the linter. */
function beltCause(p: Record<string, unknown>): string {
  if (Array.isArray(p.new)) return `${p.new.length} new failure${p.new.length === 1 ? '' : 's'}`
  if (p.timed_out === true) return 'timed out'
  if (typeof p.rc === 'number') return `rc ${p.rc}`
  if (typeof p.detected === 'string' && p.detected) return `${p.detected} rejected the change`
  return ''
}

/**
 * What one event row shows. An `error_message` wins: red glyph, the message as the
 * summary. A `grade.belt` event is a verdict, not an error (its envelope status is ok), so
 * the row reads "<belt> ✓" / "<belt> ✗ — <cause>" from the payload and only the glyph
 * turns red. Anything else keeps the envelope status and the `k=v` summary.
 */
export function logRowDisplay(ev: StepEvent): LogRowDisplay {
  if (ev.error_message) {
    return { label: 'error', tone: 'red', glyph: '✗', describe: 'error', summary: ev.error_message, isError: true }
  }
  const p = ev.payload
  if (ev.action === 'grade.belt' && typeof p.belt === 'string') {
    if (p.value === true) return { ...stepStatusDisplay('ok'), summary: `${p.belt} ✓`, isError: false }
    if (p.value === false) {
      const cause = beltCause(p)
      return { label: 'belt failed', tone: 'red', glyph: '✗', describe: 'belt failed', summary: `${p.belt} ✗${cause ? ` — ${cause}` : ''}`, isError: false }
    }
    return { label: 'belt not evaluated', tone: 'muted', glyph: '—', describe: 'belt not evaluated', summary: `${p.belt} —`, isError: false }
  }
  return { ...stepStatusDisplay(ev.status), summary: payloadSummary(p), isError: false }
}

/**
 * A virtualised event list for the SSE stream: fixed row height, only the
 * visible window rendered, follows the tail while the user is at the bottom
 * (and stops following the moment they scroll up). Each row: time · stage ·
 * action · status glyph · task · duration · cost · payload summary.
 */
export function LiveLog({ events, status, reconnects = 0, dropped = 0, error, height = 360, onSelectTask }: LiveLogProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [follow, setFollow] = useState(true)
  const [explain, setExplain] = useState(true)
  const rowH = explain ? ROW_H_EXPLAINED : ROW_H

  // Follow the tail: every new event pins the scroll to the bottom while `follow` is on.
  useEffect(() => {
    const el = ref.current
    if (!el || !follow) return
    el.scrollTop = el.scrollHeight
  }, [events.length, follow])

  const total = events.length
  const start = Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN)
  const end = Math.min(total, Math.ceil((scrollTop + height) / rowH) + OVERSCAN)
  const slice = events.slice(start, end)
  const s = STATUS_COPY[status]

  return (
    <div className="space-y-2" data-testid="live-log">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-on-surface-muted">
        <div className="flex items-center gap-2">
          <Pill tone={s.tone} glyph={s.glyph} size="xs" label={`Stream: ${s.label}`} hint="pill.run.stream">
            <span className={status === 'open' ? 'crb-pulse' : ''}>{s.label}</span>
          </Pill>
          <span className="num">{total.toLocaleString('en-GB')} events</span>
          {reconnects > 0 && <span className="num">· {reconnects} reconnect{reconnects === 1 ? '' : 's'}</span>}
          {dropped > 0 && (
            <span className="num text-status-amber" role="status">
              · {dropped} malformed frame{dropped === 1 ? '' : 's'} dropped
            </span>
          )}
          {error && status !== 'done' && (
            <span className="text-status-amber" role="status">
              · {error}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Hint as="label" id="field.run.log_explain" className="inline-flex items-center gap-1.5">
            <input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} />
            Explain each row
          </Hint>
          <Hint as="label" id="field.run.log_follow" className="inline-flex items-center gap-1.5">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            Follow tail
          </Hint>
        </div>
      </div>
      <div
        ref={ref}
        role="log"
        aria-live="polite"
        aria-label="Run events"
        // A scrollable region must be reachable by keyboard (WCAG 2.1.1; axe
        // scrollable-region-focusable) — the rows themselves are not focusable.
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget
          setScrollTop(el.scrollTop)
          // Scrolling up (more than a row from the bottom) is the reader saying "stop
          // moving"; scrolling back to the bottom re-arms following without a click.
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < rowH
          if (!atBottom && follow) setFollow(false)
          if (atBottom && !follow) setFollow(true)
        }}
        className="num overflow-auto rounded-[var(--radius-control)] border border-border bg-surface-high font-mono text-[11.5px]"
        style={{ height }}
      >
        {total === 0 ? (
          <EmptyState
            compact
            glyph="◦"
            title={status === 'done' ? 'No events were recorded for this run' : 'Waiting for the first event'}
            reason={status === 'done' ? 'The run finished without emitting step events.' : 'Events appear here as each stage runs: prep, build, grade, ledger.'}
          />
        ) : (
          <div style={{ height: total * rowH, position: 'relative' }}>
            {slice.map((ev, i) => {
              const idx = start + i
              const d = logRowDisplay(ev)
              return (
                <div key={ev.event_id || `${ev.seq}-${idx}`} className="absolute left-0 right-0 px-2 hover:bg-surface-highest" style={{ top: idx * rowH, height: rowH }} data-testid="log-row">
                  <div className="flex items-center gap-2 whitespace-nowrap" style={{ height: ROW_H }}>
                    <span className="w-[86px] shrink-0 text-on-surface-muted">{fmtTime(ev.timestamp)}</span>
                    <span className="w-[54px] shrink-0 text-on-surface-muted">{ev.stage}</span>
                    <span className="w-[150px] shrink-0 truncate text-on-surface" title={ev.action}>
                      {ev.action}
                    </span>
                    {/* one glyph per row, hundreds of rows: hover and tap open the hint; the status text is the accessible name */}
                    <Hint id="pill.run.event_status" tabStop={false} className={`w-[14px] shrink-0 ${TONE_TEXT[d.tone]}`} aria-label={d.label} role="img">
                      {d.glyph}
                    </Hint>
                    {ev.task_id ? (
                      onSelectTask ? (
                        <Hint as="button" id="link.run.event_task" type="button" onClick={() => onSelectTask(ev.task_id)} className="w-[84px] shrink-0 text-left text-primary underline-offset-2 hover:underline" title={ev.task_id}>
                          {shortId(ev.task_id)}
                        </Hint>
                      ) : (
                        <span className="w-[84px] shrink-0 text-on-surface-muted" title={ev.task_id}>
                          {shortId(ev.task_id)}
                        </span>
                      )
                    ) : (
                      <span className="w-[84px] shrink-0 text-on-surface-muted">—</span>
                    )}
                    <span className="w-[60px] shrink-0 text-right text-on-surface-muted">{ev.duration_ms !== null ? fmtMs(ev.duration_ms) : ''}</span>
                    <span className="w-[64px] shrink-0 text-right text-on-surface-muted">{ev.cost_usd !== null ? fmtUsd(ev.cost_usd) : ''}</span>
                    <span className="min-w-0 flex-1 truncate text-on-surface-muted" title={d.isError ? d.summary : payloadSummary(ev.payload)}>
                      {d.isError ? <span className="text-status-red">{d.summary}</span> : d.summary}
                    </span>
                  </div>
                  {explain && (
                    <div className="truncate pl-[94px] font-sans text-[11px] leading-4 text-on-surface-muted" style={{ height: ROW_H_EXPLAINED - ROW_H }}>
                      {actionHelp(ev.action)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
