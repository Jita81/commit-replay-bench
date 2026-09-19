/**
 * A bundled guide, rendered in the app at /help/docs/:name.
 *
 * Navigation
 * ----------
 * What it is:   The `/help/docs/:name` screen.
 * What it does: Loads the named guide (a lazy chunk bundled at build time — the repository is
 *               private and deployments may have no egress) and renders it through the subset
 *               markdown renderer, so every heading has the id its slug gives and the screens'
 *               `readMore` anchors land on the section. Scrolls to `location.hash` once the
 *               text is in. An unknown name renders the empty state with a way back to /help.
 * How:          `useParams` → `isDocName` → `loadDoc` in an effect → `renderMarkdown`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/docs.ts (`loadDoc`, `DOC_TITLES`), ui/src/help/markdown.ts (the
 *               renderer), ui/src/screens/Help/HelpPage.tsx (the index this returns to),
 *               ui/src/components/EmptyState.tsx (the unknown-name state), ui/src/App.tsx (the route)
 * Tested by:    ui/src/screens/Help/HelpPage.test.tsx
 * Touch when:   the guides gain a construct the renderer lacks (fix the renderer, not this page).
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { EmptyState } from '../../components/EmptyState'
import { PageHeader } from '../../components/PageHeader'
import { BackLink } from '../../components/govuk'
import { DOC_TITLES, isDocName, loadDoc } from '../../help/docs'
import { renderMarkdown } from '../../help/markdown'

export function DocPage() {
  const { name = '' } = useParams()
  const { hash } = useLocation()
  const known = isDocName(name)
  const [body, setBody] = useState<{ name: string; nodes: ReactNode } | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!known) return
    let live = true
    setFailed(false)
    loadDoc(name)
      .then((text) => {
        if (live) setBody({ name, nodes: renderMarkdown(text) })
      })
      .catch(() => {
        if (live) setFailed(true)
      })
    return () => {
      live = false
    }
  }, [known, name])

  useEffect(() => {
    if (!hash || body?.name !== name) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash, body, name])

  if (!known || failed) {
    return (
      <>
        <PageHeader eyebrow="Help" title="No guide with that name" />
        <EmptyState glyph="∅" title="No guide with that name" reason={<span className="font-mono text-xs">{name}</span>} action={<Link to="/help">Glossary and guides</Link>} />
      </>
    )
  }
  return (
    <>
      <BackLink to="/help">Back to glossary and guides</BackLink>
      <PageHeader eyebrow="Help · guide" title={DOC_TITLES[name].title} purpose={DOC_TITLES[name].blurb} />
      {body?.name === name ? (
        <article className="prose-doc max-w-[44em]">{body.nodes}</article>
      ) : (
        <p role="status" className="text-on-surface-muted">
          Loading the guide…
        </p>
      )}
    </>
  )
}

export default DocPage
