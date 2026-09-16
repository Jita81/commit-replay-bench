/**
 * Belt pills — the belts a row recorded, each ✓ / ✗ / —, one pill per belt with its full name.
 *
 * Navigation
 * ----------
 * What it is:   The `BeltPills` component: one pill per recorded belt.
 * What it does: Renders four belts (or five under belt set `v5`) as ✓ held / ✗ failed / — not
 *               recorded, each with the belt's full name in `aria-label`. A belt the row's
 *               apparatus never had is not rendered at all, so a missing belt can never read
 *               as failed; belt 5 on a repository with no linter reads "not evaluated".
 * How:          `beltNamesFor(beltSet, belts)` picks the belt list → `beltDisplay` gives each
 *               value its tone / glyph / sentence → a `Pill` per belt inside a labelled list.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md
 * Works with:   ui/src/api/types.ts (`Belts`, `beltNamesFor`), ui/src/lib/verdict.ts
 *               (`beltDisplay`, `BELT_LABELS`), ui/src/components/Pill.tsx (the primitive),
 *               ui/src/screens/Runs/RunDetailPage.tsx and ui/src/screens/Runs/EvidenceDrawer.tsx
 *               (the task table and the pack view), ui/src/screens/Ledger/LedgerPage.tsx (rows)
 * Tested by:    ui/src/components/BeltPills.test.tsx, ui/e2e/walkthrough/05-replay-fake.spec.ts
 *               (four ✓ on a clean fixture run)
 * Touch when:   a belt is added (an apparatus bump with its ADR) — add it to `ALL_BELT_NAMES`
 *               in ui/src/api/types.ts and `BELT_LABELS` in ui/src/lib/verdict.ts; never for
 *               a new repository.
 */
import { beltNamesFor, type Belts } from '../api/types'
import { BELT_LABELS, beltDisplay } from '../lib/verdict'
import { Pill } from './Pill'

interface BeltPillsProps {
  belts: Belts
  /**
   * The row's belt set: `v5` shows five belts, anything else four. Omit for a
   * `GradeResult` (an evidence pack): the presence of `repo_lint_clean` decides.
   */
  beltSet?: string | null
  /** Show the belt name next to the glyph (default true; false = glyph-only, name in aria). */
  showNames?: boolean
  size?: 'xs' | 'sm'
}

/**
 * The belts a row recorded, each ✓ / ✗ / — (null = not recorded, e.g. a legacy v3
 * row has no belt 4; or not evaluated — a v5 row whose repository has no linter).
 * A belt the row's apparatus never had is not rendered at all, so it can never
 * read as failed. Each pill carries the belt's full name for assistive tech.
 */
export function BeltPills({ belts, beltSet, showNames = true, size = 'xs' }: BeltPillsProps) {
  const names = beltNamesFor(beltSet, belts)
  return (
    <ul
      className={`m-0 flex list-none gap-1 p-0 ${showNames ? 'flex-wrap' : 'flex-nowrap'}`}
      aria-label={names.length === 5 ? 'Five belts' : 'Four belts'}
      data-belt-count={names.length}
    >
      {names.map((name) => {
        const value = belts[name]
        const d = beltDisplay(value, name)
        const labels = BELT_LABELS[name] ?? { short: name, long: name }
        return (
          <li key={name}>
            <Pill
              tone={d.tone}
              glyph={d.glyph}
              size={size}
              label={`${labels.long}: ${d.describe}`}
              data-testid={`belt-${name}`}
            >
              {showNames ? labels.short : d.label}
            </Pill>
          </li>
        )
      })}
    </ul>
  )
}
