/**
 * The go-live checklist on the Deployment page — each line proven, attested or unproven.
 *
 * Navigation
 * ----------
 * What it is:   The "Go live" section of /posture: the lines of DEPLOYMENT §8 as `GET /golive`
 *               reads them, in two lists — the checks this product runs, and the acts the
 *               operator attests (most performed on their own infrastructure; two are this
 *               product's own host commands whose result the server cannot read), which an
 *               admin records.
 * What it does: Shows each line's state (proven, attested, unproven) as a pill with its words,
 *               the reason under it, where the state comes from, and for an attested line who
 *               recorded it, the day it was done and what was done; counts the lines that stand;
 *               links each line to its guide section and, for an admin, to Settings where an
 *               attestation is recorded. It records nothing itself: the page stays read-only.
 * How:          `useGoLive`; `SummaryList` rows with `note` for the source; `QueryBoundary`
 *               says when the checklist could not be read.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
 * Works with:   ui/src/screens/Posture/PosturePage.tsx (mounts it), ui/src/api/hooks.ts
 *               (`useGoLive`), src/crb/server/golive.py (every rule), ui/src/screens/Settings/
 *               AttestationsCard.tsx (where an admin records an act),
 *               docs/DEPLOYMENT.md#8-go-live-checklist (the lines it shows)
 * Tested by:    ui/src/screens/Posture/PosturePage.test.tsx, ui/e2e/walkthrough/14-go-live.spec.ts
 * Touch when:   never for a new repository; a line's shape changes in src/crb/server/golive.py.
 */
import { Link } from 'react-router'
import { useGoLive } from '../../api/hooks'
import type { GoLiveLine, GoLiveState } from '../../api/types'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { SummaryList, type SummaryRow } from '../../components/govuk'
import type { DocAnchor } from '../../help/docs'
import type { Tone } from '../../lib/verdict'

/** The state's words and colour; the words always travel with the colour. */
export const GOLIVE_STATE: Record<GoLiveState, { label: string; tone: Tone; glyph: string }> = {
  proven: { label: 'Proven', tone: 'green', glyph: '✓' },
  attested: { label: 'Attested', tone: 'blue', glyph: '✎' },
  unproven: { label: 'Unproven', tone: 'amber', glyph: '!' },
}

function row(ln: GoLiveLine, admin: boolean): SummaryRow {
  const st = GOLIVE_STATE[ln.state]
  const a = ln.attestation
  return {
    key: ln.title,
    hint: 'summary.posture.golive_line',
    value: (
      <span className="block [overflow-wrap:anywhere]" data-testid={`golive-${ln.id}`}>
        <Pill tone={st.tone} glyph={st.glyph} size="xs" label={`${ln.title}: ${st.label}`} hint="pill.posture.golive_state">
          {st.label}
        </Pill>{' '}
        <span className="text-[16px]">{ln.detail}</span>
        {a && (
          <span className="block text-[16px]" data-testid={`golive-${ln.id}-attestation`}>
            Done on {a.performed_on}, recorded by {a.by} on {a.recorded_at.slice(0, 10)}: “{a.statement}”
          </span>
        )}
        <span className="block text-[16px] text-on-surface-muted">
          <DocLink to={ln.doc as DocAnchor}>The checklist line (guide)</DocLink>
          {admin && ln.proves === 'operator' ? (
            <>
              {' '}
              ·{' '}
              <Hint as={Link} id="link.posture.attest" to="/settings#golive-attestations">
                Record or withdraw on Settings
              </Hint>
            </>
          ) : null}
        </span>
      </span>
    ),
    note: <>Source: {ln.source}</>,
  }
}

/** The section. `admin` adds the way to Settings on the operator's lines. */
export function GoLiveList({ admin }: { admin: boolean }) {
  const golive = useGoLive()
  return (
    <section className="mb-8 max-w-[60em]" aria-labelledby="posture-go-live" data-testid="posture-go-live">
      <h2 id="posture-go-live" className="mb-2 text-[24px] font-bold leading-[1.3]">
        Go live
      </h2>
      <QueryBoundary query={golive} loading="Reading the go-live checklist…">
        {(g) => {
          const product = g.lines.filter((l) => l.proves === 'product')
          const operator = g.lines.filter((l) => l.proves === 'operator')
          return (
            <>
              <p className="m-0 mb-4 text-[19px] leading-[1.47]">
                <Hint id="stat.posture.golive_counts" data-testid="golive-counts">
                  {g.counts.proven + g.counts.attested} of {g.counts.lines} go-live lines stand: {g.counts.proven} proven by this product, {g.counts.attested} attested by an admin, {g.counts.unproven} unproven.
                </Hint>{' '}
                Read on {g.checked_at.slice(0, 10)} against this deployment. The list is{' '}
                <DocLink to="DEPLOYMENT#8-go-live-checklist">the go-live checklist (DEPLOYMENT §8)</DocLink>; this page shows its state and changes nothing.
              </p>
              <h3 className="mb-2 text-[19px] font-bold">Checks this product runs</h3>
              <SummaryList rows={product.map((l) => row(l, admin))} label="Go-live lines the product proves" />
              <h3 className="mb-2 mt-6 text-[19px] font-bold" id="posture-not-performed">
                Acts the operator attests
              </h3>
              <p className="m-0 mb-2 text-[16px] leading-[1.5] text-on-surface-muted" data-testid="golive-operator-acts">
                The product cannot see whether these were done. Most are acts on the operator’s own infrastructure that this product does not perform; two, <code>crb doctor</code> and <code>crb repo probe</code>, are this product’s own commands, which the operator runs on each host where the server cannot read their result. Each reads unproven until an admin records it, with the day and what was done.
              </p>
              <SummaryList rows={operator.map((l) => row(l, admin))} label="Go-live acts the operator attests" />
            </>
          )
        }}
      </QueryBoundary>
    </section>
  )
}
