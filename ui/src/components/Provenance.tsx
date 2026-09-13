import { Pill } from './Pill'

interface ProvenanceProps {
  /** e.g. "2.0" — ApparatusStamp.apparatus_version or a cell's apparatus_versions. */
  apparatus: string | string[] | null | undefined
  /** "v4" | "v3-legacy" | mixed. */
  beltSet?: string | string[] | null
  /** "measured" | "imported:census" | … (GradeRow.provenance). */
  provenance?: string | null
  /** Optional policy version, e.g. "routing.v1". */
  policy?: string | null
  className?: string
}

function list(v: string | string[] | null | undefined): string[] {
  if (!v) return []
  return Array.isArray(v) ? v.filter(Boolean) : [v]
}

/**
 * The provenance glyph (STANDARD law 6): apparatus version(s), belt set and
 * where the row came from. Measured rows get the trust-soft chip; imported
 * (census) rows a neutral one; mixed apparatus is flagged, never averaged
 * away.
 */
export function Provenance({ apparatus, beltSet, provenance, policy, className = '' }: ProvenanceProps) {
  const apps = list(apparatus)
  const belts = list(beltSet)
  const imported = provenance ? provenance.startsWith('imported') : false
  const mixed = apps.length > 1 || belts.length > 1
  return (
    <span className={`inline-flex flex-wrap items-center gap-1 ${className}`} data-testid="provenance">
      <Pill
        tone={imported ? 'muted' : mixed ? 'amber' : 'primary'}
        glyph={imported ? '⇣' : mixed ? '⚠' : '✦'}
        size="xs"
        label={`Provenance: ${provenance ?? 'measured'}; apparatus ${apps.join(', ') || 'unknown'}${belts.length ? `; belt set ${belts.join(', ')}` : ''}${mixed ? '; mixed apparatus' : ''}`}
      >
        {imported ? provenance : mixed ? 'mixed' : 'measured'}
      </Pill>
      <span className="num font-mono text-[11px] text-on-surface-muted">
        app {apps.length ? apps.join('/') : '—'}
        {belts.length > 0 && ` · ${belts.join('/')}`}
        {policy && ` · ${policy}`}
      </span>
    </span>
  )
}
