/**
 * Contextual help — the About block every screen carries, the inline term definition and the
 * link into a bundled guide.
 *
 * Navigation
 * ----------
 * What it is:   `AboutThisScreen`, `InlineDisclosure`, `Term` and `DocLink`.
 * What it does: `AboutThisScreen` is mounted once in the shell after the page content and
 *               reads the route and the signed-in role: a collapsed GOV.UK details with what
 *               this screen is for, what to do next for this role (falling down the ladder to
 *               the viewer's step), what the numbers mean, the terms on the screen and where
 *               to read more; it renders nothing where the registry has no entry.
 *               `InlineDisclosure` is the one disclosure primitive: a real button
 *               (`aria-expanded` / `aria-controls`) that toggles a `role="note"` inline under
 *               its label — click, Enter or Space; Escape closes; never a hover tooltip, so it
 *               works on touch and reflows at phone width. `Term` renders the glossary's
 *               definition through it; ui/src/screens/Capability/ReasonCode.tsx renders a
 *               reason code's sentence through it. `DocLink` links into a guide section at
 *               /help/docs.
 * How:          `useLocation` + `useAuth` + `helpFor`; `useId` for the controls id; state
 *               local to each disclosure. A disclosure must never sit inside another button.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/help.ts (the registry the About block renders),
 *               ui/src/help/glossary.ts (`TERMS`), ui/src/help/docs.ts (`docHref`),
 *               ui/src/components/govuk.tsx (`Details`), ui/src/components/Layout.tsx (mounts
 *               the About block once, after `<Outlet/>`), ui/src/screens/Help/HelpPage.tsx
 *               (where the glossary link lands), ui/src/screens/Capability/ReasonCode.tsx
 *               (the other `InlineDisclosure` client)
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
 * The one inline disclosure: a real `<button>` (`aria-expanded` / `aria-controls`) carrying
 * `label` and the ⓘ glyph; when open, `children` render as a `role="note"` block under it.
 * Click, Enter or Space toggle; Escape closes. `noteClassName` sets the note's type size.
 */
export function InlineDisclosure({ label, children, noteClassName = 'text-[16px]' }: { label: ReactNode; children: ReactNode; noteClassName?: string }) {
  const [open, setOpen] = useState(false)
  const noteId = useId()
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
        {label}
        <span aria-hidden> ⓘ</span>
      </button>
      {open && (
        <span id={noteId} role="note" className={`my-1 block max-w-[44em] border-l-4 border-primary pl-3 leading-[1.5] text-on-surface-body ${noteClassName}`}>
          {children}
        </span>
      )}
    </span>
  )
}

/**
 * A term with its definition one click away, inline: an `InlineDisclosure` whose note is
 * the glossary's short text, a Read more link and a link to the glossary entry.
 */
export function Term({ id, children }: { id: TermId; children?: ReactNode }) {
  const t = TERMS[id]
  return (
    <InlineDisclosure label={children ?? t.term}>
      {t.short}{' '}
      {t.readMore && (
        <>
          <Link to={docHref(t.readMore)}>Read more</Link>
          {' · '}
        </>
      )}
      <Link to={`/help#${id}`}>glossary</Link>
    </InlineDisclosure>
  )
}

/** A link into a bundled guide section — replaces every `<code>docs/X.md</code>` mention.
 *  Underlined: it sits inside a sentence, so colour alone may not mark it (WCAG 1.4.1;
 *  axe `link-in-text-block` on /settings). */
export function DocLink({ to, children }: { to: DocAnchor; children: ReactNode }) {
  return (
    <Link to={docHref(to)} className="underline underline-offset-4">
      {children}
    </Link>
  )
}
