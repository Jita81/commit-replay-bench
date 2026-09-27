/**
 * Help — the glossary, the guide index and the decisions, for every role.
 *
 * Navigation
 * ----------
 * What it is:   The `/help` screen: Glossary and guides.
 * What it does: Lists every term the screens use as a definition list with an `id` per term
 *               (so `<Term>` and the About block can link to `/help#wilson`), the eight
 *               bundled guides with one line each, and every decision record as a link to its
 *               bundled copy at /help/docs/ADR-nnnn (G-156; the list is `ADR_TITLES`, which a
 *               test holds to docs/adr — G-157). Nothing here reads the API beyond the session.
 * How:          `TERM_IDS` / `TERMS`, `DOC_NAMES` / `DOC_TITLES`, `ADR_TITLES`; on load it
 *               scrolls to `location.hash` so a term link lands on its entry.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-073)
 * Works with:   ui/src/help/glossary.ts (the terms), ui/src/help/docs.ts (the guides),
 *               ui/src/help/adrs.ts (the decision records),
 *               ui/src/screens/Help/DocPage.tsx (where a guide link lands),
 *               ui/src/components/Help.tsx (`Term` links here), ui/src/components/Layout.tsx
 *               (Help in the top bar and footer), ui/src/App.tsx (the route)
 * Tested by:    ui/src/screens/Help/HelpPage.test.tsx
 * Touch when:   a guide, a term or a decision record is added (edit the registries —
 *               glossary.ts, docs.ts, adrs.ts — not this page).
 */
import { useEffect } from 'react'
import { Link, useLocation } from 'react-router'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Lede } from '../../components/govuk'
import { ADR_TITLES, adrHref } from '../../help/adrs'
import { DOC_NAMES, DOC_TITLES, docHref } from '../../help/docs'
import { TERM_IDS, TERMS } from '../../help/glossary'

export function HelpPage() {
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash])
  return (
    <>
      <PageHeader eyebrow="Help" title="Glossary and guides" />
      <Lede>Every term the screens use, in plain English, with the number’s n, interval and apparatus where the term is a number.</Lede>
      <section aria-labelledby="terms-heading" id="terms" className="space-y-4">
        <h2 id="terms-heading">Terms</h2>
        <dl className="m-0 max-w-[44em] border-t border-border">
          {TERM_IDS.map((id) => {
            const t = TERMS[id]
            return (
              <div key={id} id={id} className="border-b border-border py-3 text-[16px] leading-[1.5]">
                <dt className="font-bold">{t.term}</dt>
                <dd className="m-0">
                  {t.short}
                  {t.readMore && (
                    <>
                      {' '}
                      {/* underlined: it sits inside a sentence, so colour alone may not mark it (WCAG 1.4.1; axe link-in-text-block) */}
                      <Hint as={Link} id="link.help.read_more" to={docHref(t.readMore)} className="underline underline-offset-4">
                        Read more
                      </Hint>
                    </>
                  )}
                </dd>
              </div>
            )
          })}
        </dl>
      </section>
      <section aria-labelledby="guides-heading" id="guides" className="space-y-4">
        <h2 id="guides-heading">Guides</h2>
        <ul className="m-0 max-w-[44em] list-none border-t border-border p-0">
          {DOC_NAMES.map((name) => (
            <li key={name} className="border-b border-border py-3 text-[16px] leading-[1.5]">
              <Hint as={Link} id="link.help.guide" to={docHref(name)} className="text-[19px] font-bold">
                {DOC_TITLES[name].title}
              </Hint>
              <p className="m-0 text-on-surface-muted">{DOC_TITLES[name].blurb}</p>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="decisions-heading" id="decisions" className="space-y-4">
        <h2 id="decisions-heading">Decisions (ADRs)</h2>
        <p className="m-0 max-w-[44em] text-[16px] leading-[1.5]">The architecture decision records live in the repository under docs/adr. Each is built into this deployment and opens here, read-only, so you can follow a decision a screen names.</p>
        <ul className="m-0 max-w-[44em] list-none border-t border-border p-0">
          {ADR_TITLES.map(([num, title]) => (
            <li key={num} className="border-b border-border py-2 text-[16px] leading-[1.5]">
              <Hint as={Link} id="link.help.adr" to={adrHref(num)} className="underline underline-offset-4">
                <span className="font-mono">ADR-{num}</span> — {title}
              </Hint>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}

export default HelpPage
