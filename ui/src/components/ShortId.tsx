/**
 * ShortId — a shortened id or hash whose full value is still in the accessible name.
 *
 * Navigation
 * ----------
 * What it is:   The one way the product shows the first characters of a task id, a row hash,
 *               a backlog hash, an evidence-pack hash or a patch sha256.
 * What it does: Renders the first `n` characters for the eye and the rest in a visually
 *               hidden span, so the element's text — and, inside a link or a button, its
 *               accessible name — is the whole value. It replaces the native `title=` those
 *               cells used to carry: a browser tooltip opens on hover only, so no keyboard
 *               and no touch user could ever read the full hash (DL-048, gap G-906). The
 *               column header's registry hint says what the value is and where the full one
 *               lives; this makes sure nothing is lost on the way.
 * How:          Two spans and `sr-only` (ui/src/index.css), the same mechanism the capability
 *               map's cell legend uses. A missing value renders the em dash `fmt` uses, so a
 *               caller never has to branch.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/lib/format.ts (`shortId`, `DASH` — the same shortening rule),
 *               ui/src/screens/Ledger/LedgerPage.tsx, ui/src/screens/Runs/RunDetailPage.tsx,
 *               ui/src/screens/Runs/TaskDetailPage.tsx, ui/src/screens/Runs/EvidenceDrawer.tsx,
 *               ui/src/screens/Runs/ReviewPanel.tsx, ui/src/screens/Repos/RepoDetail.tsx,
 *               ui/src/screens/Factory/FactoryPage.tsx, ui/src/screens/Oracle/OraclePage.tsx,
 *               ui/src/screens/Runs/RunsPage.tsx, ui/src/components/LiveLog.tsx (the cells
 *               that used to carry a `title=`), ui/src/help/hints-ratchet.test.tsx (the
 *               `TITLE_ALLOWLIST` this empties and the `TITLE_RE` that now names `Link`)
 * Tested by:    ui/src/components/ShortId.test.tsx
 * Touch when:   the shortening rule changes (change `shortId` too); never for a new screen.
 */
import { DASH, shortId } from '../lib/format'

/** The first `n` characters for the eye; the remainder visually hidden, so the text is the whole value. */
export function ShortId({ value, n = 10, className }: { value: string | null | undefined; n?: number; className?: string }) {
  if (!value) return <span className={className}>{DASH}</span>
  const head = shortId(value, n)
  const tail = value.slice(head.length)
  return (
    <span className={className}>
      {head}
      {tail && <span className="sr-only">{tail}</span>}
    </span>
  )
}

export default ShortId
