/**
 * pending-focus — no control is disabled while its request runs (P-396).
 *
 * Navigation
 * ----------
 * What it is:   A source ratchet over every screen and component.
 * What it does: Fails when a non-test source disables a control on a query's or mutation's
 *               `isPending` (`disabled={x.isPending}`, `disabled={a || x.isPending}`): a
 *               disabled control that had focus drops it to <body>, so a keyboard or
 *               screen-reader user loses their place after every submit (the Wave 4 attack
 *               found it on every new form). The way is `pending={x.isPending}` on `Button`
 *               or a GOV.UK button, which keeps focus and ignores presses. The sources that
 *               did this before the ratchet are listed in `NOT_YET_MOVED` — a list that only
 *               shrinks: a file that no longer offends must be removed, and a new offender
 *               fails. The matcher is pinned on its own strings.
 * How:          `import.meta.glob` over the sources as `?raw` text; comments stripped; one regex.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Button.tsx (the `pending` prop),
 *               ui/src/components/govuk.tsx (the GOV.UK buttons' `pending` prop),
 *               docs/PREVENTION.md (P-396 and G-739, the class and what remains)
 * Tested by:    ui/src/test/pending-focus.test.ts
 * Touch when:   never for a new repository; a file in `NOT_YET_MOVED` is moved to `pending`
 *               (remove it).
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['../screens/**/*.tsx', '../components/**/*.tsx', '!../**/*.test.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** The files that disabled a control while pending when the ratchet was built (G-739). Only shrinks. */
const NOT_YET_MOVED: ReadonlySet<string> = new Set([
  'screens/Connect/GitHubConnectDialog.tsx',
  'screens/Connect/MeasurePage.tsx',
  'screens/Factory/FactoryPage.tsx',
  'screens/Factory/IntakePage.tsx',
  'screens/Learn/LearnPage.tsx',
  'screens/Learn/PreventionSection.tsx',
  'screens/Login/LoginPage.tsx',
  'screens/Repos/PosturePanel.tsx',
  'screens/Repos/RepoConfigTab.tsx',
  'screens/Repos/RepoDetail.tsx',
  'screens/Repos/RepoNewDialog.tsx',
  'screens/Runs/RunNewDialog.tsx',
  'screens/Settings/ChangeMyPasswordCard.tsx',
  'screens/Settings/ClaudeCodeLoginCard.tsx',
  'screens/Settings/GitHubAppCard.tsx',
  'screens/Settings/SetPasswordDialog.tsx',
  'screens/Settings/UsersCard.tsx',
  'screens/Signoff/SignoffPage.tsx',
])

/** Whether a source disables a control on a request's `isPending`. */
export function disablesWhilePending(source: string): boolean {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
  return /\bdisabled=\{[^}]*\bisPending\b[^}]*\}/.test(code)
}

describe('pending keeps focus (P-396)', () => {
  it('the matcher finds a control disabled while pending, and passes the pending prop', () => {
    expect(disablesWhilePending('<Button disabled={invite.isPending}>Invite</Button>')).toBe(true)
    expect(disablesWhilePending('<Button disabled={invite.isPending || expiry === null}>Invite</Button>')).toBe(true)
    expect(disablesWhilePending('<Button pending={invite.isPending} disabled={expiry === null}>Invite</Button>')).toBe(false)
    expect(disablesWhilePending('// disabled={x.isPending} in a comment')).toBe(false)
  })

  it('reads the screens it guards', () => {
    expect(Object.keys(SOURCES).some((p) => p.endsWith('/Settings/InviteApproverCard.tsx'))).toBe(true)
  })

  it('no control is disabled while its request runs, beyond the files not yet moved (a list that only shrinks)', () => {
    const offenders = Object.entries(SOURCES)
      .filter(([, src]) => disablesWhilePending(src))
      .map(([path]) => path.replace(/^\.\.\//, ''))
    expect(offenders.filter((o) => !NOT_YET_MOVED.has(o)), 'use pending={x.isPending}, which keeps focus').toEqual([])
    expect([...NOT_YET_MOVED].filter((o) => !offenders.includes(o)), 'this file no longer offends: remove it from the list').toEqual([])
  })
})
