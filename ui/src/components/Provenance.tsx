/**
 * Provenance — apparatus version(s), belt set and where the rows came from; mixed apparatus is
 * flagged, never averaged.
 *
 * Navigation
 * ----------
 * What it is:   The `Provenance` chip (design law 6 in ui/README.md) shown next to every number
 *               and every pack.
 * What it does: Names the apparatus version(s) and belt set(s) a figure drew on and whether
 *               the rows were measured here or imported (census); when more than one
 *               apparatus or belt set is present it renders an amber "mixed" warning so a
 *               reader knows the figure blends instruments — the UI shows the fact, it does
 *               not hide it by averaging.
 * How:          Normalise the inputs to lists → pick tone / glyph (imported muted, mixed amber,
 *               measured primary) → a `Pill` with a full sentence plus the versions in mono.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
 * Works with:   ui/src/api/types.ts (`ApparatusStamp`, `GradeRow.provenance`,
 *               `CapabilityCell.apparatus_versions`), ui/src/screens/Runs/EvidenceDrawer.tsx
 *               (a pack's stamp), ui/src/screens/Capability/CapabilityPage.tsx and
 *               ui/src/screens/Signoff/SignoffPage.tsx (a cell's versions),
 *               ui/src/screens/Ledger/LedgerPage.tsx (per row)
 * Tested by:    ui/src/screens/Capability/CapabilityPage.test.tsx and
 *               ui/src/screens/Runs/RunDetailPage.test.tsx (`data-testid="provenance"` as
 *               rendered), ui/e2e/walkthrough/05-replay-fake.spec.ts
 * Touch when:   `APPARATUS_VERSION` is bumped (src/crb/core/version.py) — nothing changes here,
 *               the mixed flag will simply appear on blended figures; never for a new
 *               repository.
 * Claims:       Rows from different apparatus versions are never blended in a claim
 *               (docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires).
 */
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

/** Normalise a scalar-or-array prop to a list, dropping empties. */
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
