/**
 * The shell screens' entries for the hint ratchet — sign in, the help pages and an unknown
 * address, the four routes the ratchet used to skip by name.
 *
 * Navigation
 * ----------
 * What it is:   `SHELL_SCREENS`: one `{ route, path, element, api, roles }` per route that is
 *               not part of the journey — `/login`, `/help`, `/help/docs/:name` and `*` —
 *               spread into the ratchet's `SCREENS` table.
 * What it does: Closes G-909. Until this file existed the ratchet read App.tsx's route table
 *               and then dropped those four by name, so a new unhinted element on any of them
 *               failed no test, against the operator's ask that every element explains itself.
 *               Each entry gives the screen the state that renders every element it has: the
 *               login form with an organisation provider configured (both fields, both
 *               sign-in buttons), the glossary with its Read more and guide links, a bundled
 *               guide with its way back, and the 404 with its one way out.
 * How:          Plain fixture objects in the shapes the screen tests use (`mockApi` tables).
 *               `/login` and the help pages read nothing but the session, so their tables are
 *               small. The guide's rendered Markdown is marked `[data-prose]` and the
 *               collector leaves it alone: it is the help text, not a product element.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/help/hints-ratchet.test.tsx (spreads these into `SCREENS`),
 *               ui/src/help/hints.ts (`MIN_HINTS` — the floors these routes are held to),
 *               ui/src/screens/Login/LoginPage.tsx, ui/src/screens/Help/HelpPage.tsx,
 *               ui/src/screens/Help/DocPage.tsx, ui/src/screens/NotFoundPage.tsx (the
 *               screens rendered under these fixtures), ui/src/test/utils.tsx (`envelope`)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx
 * Touch when:   one of the four screens gains an element — add the fixture state that renders
 *               it and raise its `MIN_HINTS` floor.
 */
import type { ReactElement } from 'react'
import type { Role } from '../api/types'
import { DocPage } from '../screens/Help/DocPage'
import { HelpPage } from '../screens/Help/HelpPage'
import { LoginPage } from '../screens/Login/LoginPage'
import { NotFoundPage } from '../screens/NotFoundPage'
import { PRINCIPAL, envelope } from '../test/utils'

/** The shape the ratchet's `SCREENS` table takes (structurally the ratchet's own `ScreenEntry`). */
export interface ShellScreen {
  route: string
  path: string
  element: ReactElement
  api: Record<string, unknown>
  roles: Role[]
}

/** No session: the login form renders instead of redirecting to `next`. */
const SIGNED_OUT = {
  'GET /auth/me': () => envelope(401, 'unauthenticated', 'no session'),
  // a provider is configured, so the organisation button renders beside the local form
  'GET /version': { crb: '2.0.0a1', apparatus: '2.2', policy: 'routing.v1', oidc_enabled: true },
}

const SIGNED_IN = { 'GET /auth/me': PRINCIPAL }

export const SHELL_SCREENS: Record<string, ShellScreen> = {
  '/login': {
    route: '/login',
    path: '/login',
    element: <LoginPage />,
    api: SIGNED_OUT,
    // the screen is the same for everyone: nobody has a role until they are through it
    roles: ['viewer'],
  },
  '/help': {
    route: '/help',
    path: '/help',
    element: <HelpPage />,
    api: SIGNED_IN,
    roles: ['viewer', 'admin'],
  },
  '/help/docs/:name': {
    route: '/help/docs/OPERATOR',
    path: '/help/docs/:name',
    element: <DocPage />,
    api: SIGNED_IN,
    roles: ['viewer'],
  },
  '*': {
    route: '/nowhere/at/all',
    path: '*',
    element: <NotFoundPage />,
    api: SIGNED_IN,
    roles: ['viewer', 'operator'],
  },
}
