/**
 * Help — the glossary, the guide index and the decisions, for every role.
 *
 * Navigation
 * ----------
 * What it is:   The `/help` screen: Glossary and guides.
 * What it does: Lists every term the screens use as a definition list with an `id` per term
 *               (so `<Term>` and the About block can link to `/help#wilson`), the eight
 *               bundled guides with one line each, and the ADR index by title (ADRs are not
 *               bundled; they live in the repository under docs/adr). Nothing here reads the
 *               API beyond the session.
 * How:          `TERM_IDS` / `TERMS`, `DOC_NAMES` / `DOC_TITLES`; on load it scrolls to
 *               `location.hash` so a term link lands on its entry.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/glossary.ts (the terms), ui/src/help/docs.ts (the guides),
 *               ui/src/screens/Help/DocPage.tsx (where a guide link lands),
 *               ui/src/components/Help.tsx (`Term` links here), ui/src/components/Layout.tsx
 *               (Help in the top bar and footer), ui/src/App.tsx (the route)
 * Tested by:    ui/src/screens/Help/HelpPage.test.tsx
 * Touch when:   a guide or a term is added (edit the registries, not this page); an ADR is
 *               added (add its row to `ADRS`).
 */
import { useEffect } from 'react'
import { Link, useLocation } from 'react-router'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Lede } from '../../components/govuk'
import { DOC_NAMES, DOC_TITLES, docHref } from '../../help/docs'
import { TERM_IDS, TERMS } from '../../help/glossary'

/** The ADR index (docs/adr/README.md) by number and title — not bundled, so listed, not linked. */
const ADRS: Array<[string, string]> = [
  ['0001', 'Four belts and false-Q1 = 0 enforced at write'],
  ['0002', 'Append-only, hash-chained ledger'],
  ['0003', 'One routing rule'],
  ['0004', 'Builder registry; sighted and blind modes'],
  ['0005', 'Fail-closed Docker sandbox for every test run'],
  ['0006', 'Zero raw retention by default; evidence packs'],
  ['0007', 'Cross-organisation learning: abstract cell export only'],
  ['0008', 'Standard-library core and downward-only layers'],
  ['0009', 'Text-level mutators for the non-Python languages'],
  ['0010', 'Polyglot negative controls'],
  ['0011', 'Belt 5: the repository’s own formatter or linter'],
  ['0012', 'The builder runs in a sealed container'],
  ['0013', 'An external reviewer’s verdict is recorded and advisory'],
  ['0014', 'The GitHub App is the connection'],
  ['0015', 'A sign-off expires with the apparatus'],
  ['0016', 'The two-person rule is a policy clause, not an apparatus move'],
]

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
        <p className="m-0 max-w-[44em] text-[16px] leading-[1.5]">The architecture decision records are in the repository under docs/adr. They are listed here by title so a screen can name one.</p>
        <ul className="m-0 max-w-[44em] list-none border-t border-border p-0">
          {ADRS.map(([num, title]) => (
            <li key={num} className="border-b border-border py-2 text-[16px] leading-[1.5]">
              <span className="font-mono">ADR-{num}</span> — {title}
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}

export default HelpPage
