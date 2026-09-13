import { useMemo, useState, type ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: ReactNode
  /** Cell renderer. */
  cell: (row: T) => ReactNode
  /** Sort accessor; omit to make the column unsortable. */
  sortValue?: (row: T) => string | number | boolean | null | undefined
  /** Right-align + tabular numerals. */
  numeric?: boolean
  /** Mono (ids, SHAs, refs). */
  mono?: boolean
  width?: string
  /** Hide below md (keeps the table usable on narrow viewports). */
  hideBelowMd?: boolean
}

interface DataTableProps<T> {
  rows: readonly T[]
  columns: Column<T>[]
  rowKey: (row: T) => string
  /** Required: a table needs a caption for assistive tech (may be visually hidden). */
  caption: string
  captionVisible?: boolean
  /** Rendered inside the table when `rows` is empty. Always designed, never blank. */
  empty: ReactNode
  onRowClick?: (row: T) => void
  rowClassName?: (row: T) => string
  initialSort?: { key: string; dir: 'asc' | 'desc' }
  dense?: boolean
  /** Max height for the sticky-header scroll region. */
  maxHeight?: string
}

function compare(a: unknown, b: unknown): number {
  if (a === b) return 0
  if (a === null || a === undefined) return 1
  if (b === null || b === undefined) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b)
  return String(a).localeCompare(String(b))
}

/**
 * Sortable, sticky-header table with numeric right-alignment and tabular
 * numerals. Proper <th scope="col"> headers, aria-sort on the active column,
 * a caption, and a designed empty-state slot.
 */
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  captionVisible = false,
  empty,
  onRowClick,
  rowClassName,
  initialSort,
  dense = false,
  maxHeight = '70vh',
}: DataTableProps<T>) {
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(initialSort ?? null)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sortValue) return rows
    const acc = col.sortValue
    const out = [...rows].sort((a, b) => compare(acc(a), acc(b)))
    return sort.dir === 'asc' ? out : out.reverse()
  }, [rows, sort, columns])

  const toggle = (key: string) => {
    setSort((s) => (s?.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))
  }

  const pad = dense ? 'px-2 py-1.5' : 'px-3 py-2'

  return (
    <div className="overflow-auto rounded-[var(--radius-control)] border border-border" style={{ maxHeight }}>
      <table className="w-full border-collapse text-[13px]">
        <caption className={captionVisible ? 'px-3 py-2 text-left text-xs text-on-surface-muted' : 'sr-only'}>{caption}</caption>
        <thead className="sticky top-0 z-10 bg-surface-high">
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key
              const sortable = Boolean(c.sortValue)
              const ariaSort = active ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : sortable ? 'none' : undefined
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  style={c.width ? { width: c.width } : undefined}
                  className={`${pad} label border-b border-border text-left ${c.numeric ? 'text-right' : ''} ${c.hideBelowMd ? 'hidden md:table-cell' : ''}`}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => toggle(c.key)}
                      className={`inline-flex items-center gap-1 rounded px-0.5 hover:text-on-surface ${c.numeric ? 'flex-row-reverse' : ''}`}
                    >
                      <span>{c.header}</span>
                      <span aria-hidden className="text-[9px]">
                        {active ? (sort?.dir === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="p-0">
                {empty}
              </td>
            </tr>
          ) : (
            sorted.map((row) => {
              const clickable = Boolean(onRowClick)
              return (
                <tr
                  key={rowKey(row)}
                  onClick={clickable ? () => onRowClick?.(row) : undefined}
                  onKeyDown={
                    clickable
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            onRowClick?.(row)
                          }
                        }
                      : undefined
                  }
                  tabIndex={clickable ? 0 : undefined}
                  className={`border-b border-border last:border-b-0 ${clickable ? 'cursor-pointer hover:bg-surface-high focus-visible:bg-surface-high' : ''} ${rowClassName?.(row) ?? ''}`}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={`${pad} align-top ${c.numeric ? 'num text-right' : ''} ${c.mono ? 'font-mono text-xs' : ''} ${c.hideBelowMd ? 'hidden md:table-cell' : ''}`}
                    >
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
