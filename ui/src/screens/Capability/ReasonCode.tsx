/**
 * ReasonCode — a routing reason code whose sentence is one click away, inline.
 *
 * Navigation
 * ----------
 * What it is:   `ReasonCode`, the way the map and the routes table print a `reason_code`.
 * What it does: Renders the code as a real button (`aria-expanded` / `aria-controls`) that
 *               toggles the code's own sentence from `REASON_DISPLAY` under it, with a link
 *               to the glossary's "reason code" entry for what a reason code is. Click, Enter
 *               or Space; Escape closes; never a hover title, so it works on touch and reflows
 *               at phone width. The markup mirrors `Term` in ui/src/components/Help.tsx; it is
 *               not `Term` because the text that opens is the code's sentence, not the
 *               glossary's definition. Must never sit inside another button (the map tile
 *               prints its reason in the detail card, not the tile).
 * How:          `useState` + `useId`; `REASON_DISPLAY[code]` for the sentence; an unknown
 *               code from a newer server shows the code with the generic sentence.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/contract.ts (`REASON_DISPLAY`, `ReasonCode` type),
 *               ui/src/screens/Capability/CapabilityPage.tsx (the cell detail card),
 *               ui/src/screens/Routing/RoutingPage.tsx (the Why column),
 *               ui/src/components/Help.tsx (`Term`, the pattern this follows),
 *               ui/src/help/glossary.ts (`reason_code`)
 * Tested by:    ui/src/screens/Routing/RoutingPage.test.tsx (opens, closes on Escape, links the glossary)
 * Touch when:   a reason code is added (add its sentence to `REASON_DISPLAY` first).
 */
import { useId, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router'
import { REASON_DISPLAY, type ReasonCode as ReasonCodeId } from './contract'

/** The code as printed on the map and the routes table; its sentence opens inline under it. */
export function ReasonCode({ code }: { code: ReasonCodeId | string }) {
  const [open, setOpen] = useState(false)
  const noteId = useId()
  const sentence = REASON_DISPLAY[code as ReasonCodeId] ?? `a reason code this version of the UI has no sentence for (${code})`
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Escape' && open) {
      e.stopPropagation()
      setOpen(false)
    }
  }
  return (
    <span className="inline" onKeyDown={onKey}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={noteId}
        onClick={() => setOpen((o) => !o)}
        className="inline cursor-pointer border-0 bg-transparent p-0 underline decoration-dotted underline-offset-4"
      >
        <code className="rounded bg-surface-high px-1 py-0.5 font-mono text-[11px]" data-testid="reason-code">
          {code}
        </code>
        <span aria-hidden> ⓘ</span>
      </button>
      {open && (
        <span id={noteId} role="note" className="my-1 block max-w-[44em] border-l-4 border-primary pl-3 font-sans text-[14px] leading-[1.5] text-on-surface-body">
          {sentence}. <Link to="/help#reason_code">glossary</Link>
        </span>
      )}
    </span>
  )
}
