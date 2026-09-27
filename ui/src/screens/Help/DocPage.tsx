/**
 * A bundled guide or decision record, rendered in the app at /help/docs/:name.
 *
 * Navigation
 * ----------
 * What it is:   The `/help/docs/:name` screen — the eight guides (`OPERATOR`, …) and the
 *               decision records (`ADR-0015`, …) share it.
 * What it does: Loads the named guide or record (a lazy chunk bundled at build time — the
 *               repository is private and deployments may have no egress) and renders it
 *               through the subset markdown renderer, so every heading has the id its slug
 *               gives and the screens' `readMore` anchors land on the section. Scrolls to
 *               `location.hash` once the text is in. The page has one h1, its header: the
 *               file's own headings render one level down (`headingOffset`), so the `#`
 *               title is the article's h2 — two h1s made the walkthrough's heading query
 *               ambiguous and gave a screen reader two page titles (P-176). Under the header
 *               it states what the page is not: a build-time, read-only copy of the
 *               repository's file (G-150). Three
 *               stops, each told apart: an unknown name renders the empty state with a way
 *               back to /help; a known name whose chunk fails to load renders the error
 *               envelope with Retry — the deployment failed, not the person's link (G-148);
 *               while loading it says so as a live status.
 * How:          `useParams` → `isDocName` / `isAdrName` → `loadDoc` / `loadAdr` in an effect
 *               keyed on the name and a retry counter → `renderMarkdown`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-074)
 * Works with:   ui/src/help/docs.ts (`loadDoc`, `DOC_TITLES`), ui/src/help/adrs.ts (`loadAdr`,
 *               the record titles), ui/src/help/markdown.ts (the renderer),
 *               ui/src/screens/Help/HelpPage.tsx (the index this returns to),
 *               ui/src/components/EmptyState.tsx (the unknown-name state),
 *               ui/src/components/ErrorState.tsx (the failed load, with Retry), ui/src/App.tsx
 *               (the route), ui/src/help/help.ts (the About block's `/help/docs/:name` entry)
 * Tested by:    ui/src/screens/Help/HelpPage.test.tsx, ui/e2e/walkthrough/13-orient.spec.ts
 *               (all eight guides and a record opened on the live stack)
 * Touch when:   never for a new repository; the guides gain a construct the renderer lacks (fix the
 *               renderer, not this page).
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { PageHeader } from '../../components/PageHeader'
import { Hint } from '../../components/Hint'
import { BackLink } from '../../components/govuk'
import { adrTitle, isAdrName, loadAdr } from '../../help/adrs'
import { DOC_TITLES, isDocName, loadDoc } from '../../help/docs'
import { renderMarkdown } from '../../help/markdown'

export function DocPage() {
  const { name = '' } = useParams()
  const { hash } = useLocation()
  const guide = isDocName(name)
  const record = !guide && isAdrName(name)
  const known = guide || record
  const [body, setBody] = useState<{ name: string; nodes: ReactNode } | null>(null)
  const [failed, setFailed] = useState<{ name: string; error: unknown } | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!known) return
    let live = true
    setFailed(null)
    ;(guide ? loadDoc(name) : loadAdr(name))
      .then((text) => {
        if (live) setBody({ name, nodes: renderMarkdown(text, { headingOffset: 1 }) })
      })
      .catch((error: unknown) => {
        if (live) setFailed({ name, error })
      })
    return () => {
      live = false
    }
  }, [known, guide, name, attempt])

  useEffect(() => {
    if (!hash || body?.name !== name) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash, body, name])

  if (!known) {
    return (
      <>
        <PageHeader eyebrow="Help" title="No guide with that name" />
        <EmptyState
          glyph="∅"
          title="No guide with that name"
          reason={<span className="font-mono text-xs">{name}</span>}
          action={
            <Hint as={Link} id="link.help.index" to="/help" className="text-primary underline">
              Glossary and guides
            </Hint>
          }
        />
      </>
    )
  }
  const what = guide ? 'guide' : 'decision record'
  return (
    <>
      <BackLink to="/help" hint="link.help.back">Back to glossary and guides</BackLink>
      {guide ? <PageHeader eyebrow="Help · guide" title={DOC_TITLES[name].title} purpose={DOC_TITLES[name].blurb} /> : <PageHeader eyebrow="Help · decision record" title={`${name} — ${adrTitle(name)}`} />}
      {/* the page's non-goals, where the reader stands (G-150) */}
      <p className="mb-6 mt-0 max-w-[44em] text-[16px] text-on-surface-muted">
        A copy of the repository’s {what}, built into this deployment when it was installed. Read-only: it is changed in the repository, not here.
      </p>
      {failed?.name === name ? (
        <div className="max-w-[44em]">
          <ErrorState error={failed.error} title={`The ${what} could not be loaded`} onRetry={() => setAttempt((n) => n + 1)}>
            <p className="m-0 text-sm">This deployment holds the {what}, but its file did not load. Retry, or reload the page. If it keeps failing, tell the person who runs this deployment: its web files may be incomplete.</p>
          </ErrorState>
        </div>
      ) : body?.name === name ? (
        <article className="prose-doc max-w-[44em]" data-prose>{body.nodes}</article>
      ) : (
        <p role="status" className="text-on-surface-muted">
          Loading the {what}…
        </p>
      )}
    </>
  )
}

export default DocPage
