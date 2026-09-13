import { useState } from 'react'

interface JsonViewProps {
  value: unknown
  initiallyOpen?: boolean
  /** Depth at which nested objects start collapsed. */
  collapseBelow?: number
  label?: string
}

function isObj(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}

function Node({ k, v, depth, collapseBelow }: { k: string | null; v: unknown; depth: number; collapseBelow: number }) {
  const [open, setOpen] = useState(depth < collapseBelow)
  const key = k !== null ? <span className="text-status-violet">{JSON.stringify(k)}</span> : null
  const sep = k !== null ? <span className="text-on-surface-muted">: </span> : null

  if (Array.isArray(v) || isObj(v)) {
    const entries = Array.isArray(v) ? v.map((x, i) => [String(i), x] as const) : Object.entries(v)
    const [o, c] = Array.isArray(v) ? ['[', ']'] : ['{', '}']
    if (entries.length === 0) {
      return (
        <div>
          {key}
          {sep}
          <span className="text-on-surface-muted">
            {o}
            {c}
          </span>
        </div>
      )
    }
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen((x) => !x)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 rounded hover:bg-surface-high"
        >
          <span aria-hidden className="w-3 text-on-surface-muted">
            {open ? '▾' : '▸'}
          </span>
          {key}
          {sep}
          <span className="text-on-surface-muted">
            {o}
            {!open && ` … ${entries.length} `}
            {!open && c}
          </span>
        </button>
        {open && (
          <div className="ml-4 border-l border-border pl-2">
            {entries.map(([ek, ev]) => (
              <Node key={ek} k={Array.isArray(v) ? null : ek} v={ev} depth={depth + 1} collapseBelow={collapseBelow} />
            ))}
            <span className="text-on-surface-muted">{c}</span>
          </div>
        )}
      </div>
    )
  }

  let cls = 'text-on-surface'
  if (typeof v === 'string') cls = 'text-status-green'
  else if (typeof v === 'number') cls = 'text-status-blue'
  else if (typeof v === 'boolean') cls = v ? 'text-status-green' : 'text-status-red'
  else if (v === null) cls = 'text-on-surface-muted'
  return (
    <div className="break-all">
      {key}
      {sep}
      <span className={cls}>{JSON.stringify(v)}</span>
    </div>
  )
}

/** Collapsible JSON — for evidence packs and structured error detail. */
export function JsonView({ value, initiallyOpen = false, collapseBelow, label }: JsonViewProps) {
  const depth = collapseBelow ?? (initiallyOpen ? 2 : 1)
  return (
    <div
      className="num max-h-[60vh] overflow-auto rounded-[var(--radius-control)] border border-border bg-surface-high p-3 font-mono text-[11.5px] leading-5"
      aria-label={label ?? 'Structured data'}
      data-testid="json-view"
    >
      <Node k={null} v={value} depth={0} collapseBelow={depth} />
    </div>
  )
}
