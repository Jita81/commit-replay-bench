/**
 * Contextual help — the About block every screen carries, the inline term definition and the
 * link into a bundled guide.
 *
 * Navigation
 * ----------
 * What it is:   `AboutThisScreen`, `Term` and `DocLink`.
 * What it does: `AboutThisScreen` is mounted once in the shell after the page content and
 *               reads the route and the signed-in role: a collapsed GOV.UK details with what
 *               this screen is for, what to do next for this role (falling down the ladder to
 *               the viewer's step), what the numbers mean, the terms on the screen and where
 *               to read more; it renders nothing where the registry has no entry. `Term` is a
 *               real button (`aria-expanded` / `aria-controls`) that toggles the glossary's
 *               definition inline under the word — click, Enter or Space; Escape closes; never
 *               a hover tooltip, so it works on touch and reflows at phone width. `DocLink`
 *               links into a guide section at /help/docs.
 * How:          `useLocation` + `useAuth` + `helpFor`; `useId` for the controls id; state
 *               local to each `Term`. `Term` must never sit inside another button.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/help.ts (the registry the About block renders),
 *               ui/src/help/glossary.ts (`TERMS`), ui/src/help/docs.ts (`docHref`),
 *               ui/src/components/govuk.tsx (`Details`), ui/src/components/Layout.tsx (mounts
 *               the About block once, after `<Outlet/>`), ui/src/screens/Help/HelpPage.tsx
 *               (where the glossary link lands)
 * Tested by:    ui/src/components/Help.test.tsx, ui/e2e/walkthrough/11-screens.spec.ts (the
 *               block renders on every authenticated route on the live stack)
 * Touch when:   the About block gains a part (add it to the registry type first); never for
 *               a new repository.
 */
import { useId, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import { ROLE_ORDER, type Role } from '../api/types'
import { docHref, type DocAnchor } from '../help/docs'
import { TERMS, type TermId } from '../help/glossary'
import { helpFor } from '../help/help'
import { useAuth } from '../lib/auth'
import { Details } from './govuk'

/** The next step for `role`: its own, else the nearest lower role's (a higher role can do what a lower one can). */
function nextFor(next: Partial<Record<Role, string>> & { viewer: string }, role: Role | undefined): string {
  const start = role ? ROLE_ORDER.indexOf(role) : 0
  for (let i = start; i >= 0; i -= 1) {
    const s = next[ROLE_ORDER[i]!]
    if (s) return s
  }
  return next.viewer
}

/**
 * "About this screen" — one collapsed details under the page content (the GOV.UK "help with
 * this page" position). Renders nothing when the registry has no entry for the route.
 */
export function AboutThisScreen() {
  const { pathname } = useLocation()
  const { me } = useAuth()
  const help = helpFor(pathname)
  if (!help) return null
  return (
    <section aria-labelledby="about-screen-summary" data-testid="about-this-screen" className="border-t border-border pt-6">
      <Details summary="About this screen" id="about-screen">
        <h3 className="mb-1 mt-0 text-[16px]">What this screen is for</h3>
        <p className="mb-4 mt-0">{help.purpose}</p>
        <h3 className="mb-1 mt-0 text-[16px]">What to do next</h3>
        <p className="mb-4 mt-0">{nextFor(help.next, me?.role)}</p>
        {help.numbers && (
          <>
            <h3 className="mb-1 mt-0 text-[16px]">What the numbers mean</h3>
            <p className="mb-4 mt-0">{help.numbers}</p>
          </>
        )}
        {help.terms && help.terms.length > 0 && (
          <>
            <h3 className="mb-1 mt-0 text-[16px]">Terms on this screen</h3>
            <dl className="mb-4 mt-0">
              {help.terms.map((id) => (
                <div key={id} className="mb-2">
                  <dt className="inline font-bold">
                    <Link to={`/help#${id}`} className="text-on-surface no-underline hover:underline">
                      {TERMS[id].term}
                    </Link>
                  </dt>
                  <dd className="ml-0 inline">
                    {' '}
                    — {TERMS[id].short}
                  </dd>
                </div>
              ))}
            </dl>
          </>
        )}
        <h3 className="mb-1 mt-0 text-[16px]">Read more</h3>
        <ul className="mb-4 mt-0 list-disc pl-5">
          {help.readMore.map((r) => (
            <li key={r.to}>
              <Link to={docHref(r.to)}>{r.label}</Link>
            </li>
          ))}
        </ul>
        <p className="m-0">
          <Link to="/help">Glossary and guides</Link>
        </p>
      </Details>
    </section>
  )
}

/**
 * A term with its definition one click away, inline. A real `<button>` with
 * `aria-expanded` / `aria-controls`; the open definition is a `role="note"` under the word
 * with the glossary's short text, a Read more link and a link to the glossary entry.
 */
export function Term({ id, children }: { id: TermId; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const noteId = useId()
  const t = TERMS[id]
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
        {children ?? t.term}
        <span aria-hidden> ⓘ</span>
      </button>
      {open && (
        <span id={noteId} role="note" className="my-1 block max-w-[44em] border-l-4 border-primary pl-3 text-[16px] leading-[1.5] text-on-surface-body">
          {t.short}{' '}
          {t.readMore && (
            <>
              <Link to={docHref(t.readMore)}>Read more</Link>
              {' · '}
            </>
          )}
          <Link to={`/help#${id}`}>glossary</Link>
        </span>
      )}
    </span>
  )
}

/** A link into a bundled guide section — replaces every `<code>docs/X.md</code>` mention. */
export function DocLink({ to, children }: { to: DocAnchor; children: ReactNode }) {
  return <Link to={docHref(to)}>{children}</Link>
}
