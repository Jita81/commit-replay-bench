/**
 * The automatic sign-in banner — while a development stack signs a browser on its own machine
 * in without a password, every page says so.
 *
 * Navigation
 * ----------
 * What it is:   `DevAutologinBanner`, the full-width strip the shell and the sign-in page render
 *               above their content, and `DEV_AUTOLOGIN_SENTENCE`, the words it shows.
 * What it does: Reads `GET /version` (unauthenticated, so the sign-in page can read it before
 *               anyone has a role) and, when it reports `dev_autologin`, renders one hinted
 *               sentence in the warning colour with `role="status"`; renders nothing otherwise,
 *               including while `/version` is loading or has failed. Follows the stack, not the
 *               page load: `useVersion` refetches when the tab regains focus and after a
 *               minute, so an API restarted with the setting changed moves the banner too.
 * How:          `useVersion` → `dev_autologin === true` → a `Hint` with
 *               `banner.shell.dev_autologin`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0027-dev-autologin-on-loopback.md
 * Works with:   ui/src/api/hooks.ts (`useVersion`; `useMe` performs the sign-in itself),
 *               ui/src/components/Layout.tsx and ui/src/screens/Login/LoginPage.tsx (where it is
 *               mounted), ui/src/help/hints.ts (`banner.shell.dev_autologin`),
 *               src/crb/server/routes/system.py (the `dev_autologin` field on `/version`)
 * Tested by:    ui/src/components/DevAutologinBanner.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   never for a new repository (the banner reads the stack's own setting); when the
 *               sentence changes (docs/OPERATOR.md quotes it); never to hide the banner while
 *               the setting is on.
 */
import { useVersion } from '../api/hooks'
import { Hint } from './Hint'

/** The sentence, exactly as docs/OPERATOR.md quotes it. */
export const DEV_AUTOLOGIN_SENTENCE = 'Automatic sign-in is on for this development stack — never use in production'

/** Rendered on every page while `GET /version` reports `dev_autologin`; nothing otherwise. */
export function DevAutologinBanner() {
  const version = useVersion()
  if (version.data?.dev_autologin !== true) return null
  return (
    <div className="border-b-4 border-status-amber bg-status-amber-soft text-on-surface" role="status" data-testid="dev-autologin-banner">
      <div className="mx-auto max-w-[1400px] px-5 py-3 text-[16px] leading-[1.47]">
        <Hint as="strong" id="banner.shell.dev_autologin">
          {DEV_AUTOLOGIN_SENTENCE}
        </Hint>
      </div>
    </div>
  )
}

export default DevAutologinBanner
