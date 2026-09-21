/**
 * ReasonCode — a routing reason code whose sentence is one click away, inline.
 *
 * Navigation
 * ----------
 * What it is:   `ReasonCode`, the way the map and the routes table print a `reason_code`.
 * What it does: Renders the code as an `InlineDisclosure` (ui/src/components/Help.tsx — the
 *               same real button, `aria-expanded` / `aria-controls`, Escape-closes, no hover
 *               title, as `Term`) whose note is the code's own sentence from `REASON_DISPLAY`
 *               with a link to the glossary's "reason code" entry. It is not `Term` because
 *               the text that opens is the code's sentence, not the glossary's definition.
 *               Must never sit inside another button (the map tile prints its reason in the
 *               detail card, not the tile).
 * How:          `InlineDisclosure` for the mechanics; `REASON_DISPLAY[code]` for the
 *               sentence; an unknown code from a newer server shows the code with the
 *               generic sentence.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/screens/Capability/contract.ts (`REASON_DISPLAY`, `ReasonCode` type),
 *               ui/src/screens/Capability/CapabilityPage.tsx (the cell detail card),
 *               ui/src/screens/Routing/RoutingPage.tsx (the Why column),
 *               ui/src/components/Help.tsx (`InlineDisclosure`, the primitive; `Term`),
 *               ui/src/help/glossary.ts (`reason_code`)
 * Tested by:    ui/src/screens/Routing/RoutingPage.test.tsx (opens, closes on Escape, links the glossary)
 * Touch when:   a reason code is added (add its sentence to `REASON_DISPLAY` first).
 */
import { Link } from 'react-router'
import { InlineDisclosure } from '../../components/Help'
import { REASON_DISPLAY, type ReasonCode as ReasonCodeId } from './contract'

/** The code as printed on the map and the routes table; its sentence opens inline under it. */
export function ReasonCode({ code }: { code: ReasonCodeId | string }) {
  const sentence = REASON_DISPLAY[code as ReasonCodeId] ?? `a reason code this version of the UI has no sentence for (${code})`
  return (
    <InlineDisclosure
      noteClassName="font-sans text-[14px]"
      label={
        <code className="rounded bg-surface-high px-1 py-0.5 font-mono text-[11px]" data-testid="reason-code">
          {code}
        </code>
      }
    >
      {sentence}. <Link to="/help#reason_code">glossary</Link>
    </InlineDisclosure>
  )
}
