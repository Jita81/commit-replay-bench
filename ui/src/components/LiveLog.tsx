import { useEffect, useRef, useState } from 'react'
import type { StepEvent } from '../api/types'
import type { SseStatus } from '../api/sse'
import { fmtMs, fmtTime, fmtUsd, shortId } from '../lib/format'
import { TONE_TEXT, stepStatusDisplay } from '../lib/verdict'
import { EmptyState } from './EmptyState'
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

const ROW_H = 26
const OVERSCAN = 12

const STATUS_COPY: Record<SseStatus, { label: string; tone: 'green' | 'amber' | 'red' | 'primary' | 'muted'; glyph: string }> = {
  idle: { label: 'Idle', tone: 'muted', glyph: '·' },
  connecting: { label: 'Connecting', tone: 'primary', glyph: '…' },
  open: { label: 'Live', tone: 'green', glyph: '●' },
  reconnecting: { label: 'Reconnecting', tone: 'amber', glyph: '↻' },
  done: { label: 'Complete', tone: 'muted', glyph: '✓' },
  closed: { label: 'Closed', tone: 'muted', glyph: '—' },
}

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

  useEffect(() => {
    const el = ref.current
    if (!el || !follow) return
    el.scrollTop = el.scrollHeight
  }, [events.length, follow])

  const total = events.length
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(total, Math.ceil((scrollTop + height) / ROW_H) + OVERSCAN)
  const slice = events.slice(start, end)
  const s = STATUS_COPY[status]

  return (
    <div className="space-y-2" data-testid="live-log">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-on-surface-muted">
        <div className="flex items-center gap-2">
          <Pill tone={s.tone} glyph={s.glyph} size="xs" label={`Stream: ${s.label}`}>
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
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          Follow tail
        </label>
      </div>
      <div
        ref={ref}
        role="log"
        aria-live="polite"
        aria-label="Run events"
        onScroll={(e) => {
          const el = e.currentTarget
          setScrollTop(el.scrollTop)
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < ROW_H
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
          <div style={{ height: total * ROW_H, position: 'relative' }}>
            {slice.map((ev, i) => {
              const idx = start + i
              const d = stepStatusDisplay(ev.status)
              return (
                <div
                  key={ev.event_id || `${ev.seq}-${idx}`}
                  className="absolute left-0 right-0 flex items-center gap-2 whitespace-nowrap px-2 hover:bg-surface-highest"
                  style={{ top: idx * ROW_H, height: ROW_H }}
                >
                  <span className="w-[86px] shrink-0 text-on-surface-muted">{fmtTime(ev.timestamp)}</span>
                  <span className="w-[54px] shrink-0 text-on-surface-muted">{ev.stage}</span>
                  <span className="w-[150px] shrink-0 truncate text-on-surface" title={ev.action}>
                    {ev.action}
                  </span>
                  <span className={`w-[14px] shrink-0 ${TONE_TEXT[d.tone]}`} title={d.label} aria-label={d.label} role="img">
                    {d.glyph}
                  </span>
                  {ev.task_id ? (
                    onSelectTask ? (
                      <button type="button" onClick={() => onSelectTask(ev.task_id)} className="w-[84px] shrink-0 text-left text-primary underline-offset-2 hover:underline" title={ev.task_id}>
                        {shortId(ev.task_id)}
                      </button>
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
                  <span className="min-w-0 flex-1 truncate text-on-surface-muted" title={ev.error_message || payloadSummary(ev.payload)}>
                    {ev.error_message ? <span className="text-status-red">{ev.error_message}</span> : payloadSummary(ev.payload)}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
