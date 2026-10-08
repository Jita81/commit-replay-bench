/**
 * Where a person is in "Deploy and go live" — the eyebrow the Settings and Deployment pages
 * carry.
 *
 * Navigation
 * ----------
 * What it is:   `DEPLOY_STEPS` (the four in-product steps of
 *               docs/dod/journeys/deploy-and-go-live.md — sign in, Settings, Deployment, Home;
 *               the host install before them is step 0) and `deployEyebrow(to)`, the line that
 *               names the stream, the journey and the step.
 * What it does: Gives `/settings` and `/posture` one eyebrow each — "Run the platform · Deploy and
 *               go live · 2 of 4 · Settings" — so a screen names the platform stream and the
 *               person's place in the go-live journey, with the steps held in one list.
 * How:          A constant list and a lookup; `PageHeader` makes an eyebrow that starts with
 *               `DEPLOY_PREFIX` a `nav.deploy_position` hint trigger.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/PageHeader.tsx (renders it),
 *               ui/src/screens/Settings/SettingsPage.tsx and
 *               ui/src/screens/Posture/PosturePage.tsx (carry it), ui/src/components/Layout.tsx
 *               (`journeyEyebrow`, the connect-to-factory journey's twin)
 * Tested by:    ui/src/lib/deployJourney.test.ts
 * Touch when:   never for a new repository; a step is added to the go-live journey (its artefact
 *               first, then here).
 */

/** The stream and journey every eyebrow of this journey starts with. */
export const DEPLOY_PREFIX = 'Run the platform · Deploy and go live'

/** The in-product steps, in order (step 0, the host install, happens before any screen). */
export const DEPLOY_STEPS: readonly { label: string; to: string }[] = [
  { label: 'Sign in', to: '/login' },
  { label: 'Settings', to: '/settings' },
  { label: 'Deployment', to: '/posture' },
  { label: 'Home', to: '/home' },
]

/** "Run the platform · Deploy and go live · n of 4 · Label" for a step's route; '' for any other. */
export function deployEyebrow(to: string): string {
  const i = DEPLOY_STEPS.findIndex((s) => s.to === to)
  const step = DEPLOY_STEPS[i]
  return step ? `${DEPLOY_PREFIX} · ${i + 1} of ${DEPLOY_STEPS.length} · ${step.label}` : ''
}
