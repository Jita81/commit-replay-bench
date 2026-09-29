/**
 * intake.ts — where the manufacture stream starts, in one line: "Work enters from your board",
 * with the intake listener's state read from the API, shared by the Factory head and Home's task 8.
 *
 * Navigation
 * ----------
 * What it is:   `intakeState(intake, failed)` folds `GET /factory/{repo}/intake` into one of four
 *               states — `not_known` (the read failed), `not_configured` (no tracker on the
 *               deployment), `not_listening` (configured, the listener off) and `listening` (on
 *               `column`) — and `intakeLine(state)` gives the words each screen shows after
 *               "Work enters from your board:".
 * What it does: Says, wherever the stream is named, that work enters from the enterprise's own
 *               board and whether the product is listening to it (G-548), in the same words on
 *               both screens so they can never disagree. A failed read is "intake state not
 *               known", never "not configured": absence of an answer is not an answer. Nothing
 *               here implies a ticket WILL be built — a ready ticket waits for an operator's
 *               Register act (ADR-0022), and the entry gate decides after that (ADR-0026 item 8).
 * How:          Pure functions over the `Intake` shape; the screens wrap the words in a link to
 *               `/factory/intake?repo=` under their own hint ids (`stat.factory.intake_state`,
 *               `stat.home.intake_state`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md (the listener is the consent gate),
 *               docs/adr/0022-intake-approval-by-default.md (Register is a person’s act)
 * Works with:   ui/src/screens/Factory/FactoryPage.tsx (the line under the page header),
 *               ui/src/screens/Home/HomePage.tsx (task 8's note), ui/src/api/hooks.ts
 *               (`useIntake`), ui/src/api/types.ts (`Intake`),
 *               ui/src/screens/Factory/IntakePage.tsx (the screen the line links to)
 * Tested by:    ui/src/screens/Factory/FactoryPage.test.tsx, ui/src/screens/Home/HomePage.test.tsx
 * Touch when:   never for a new repository; the intake shape gains a state a reader must be told
 *               about (add it to `IntakeState` and its words here, and both screens follow).
 */

import type { Intake } from '../../api/types'

export type IntakeState = 'not_known' | 'not_configured' | 'not_listening' | 'listening'

/** The state and, when listening, the column it listens on. */
export interface IntakeReading {
  state: IntakeState
  column: string
}

/**
 * Fold the intake read into a state. `failed` is the query's own failure (any error: a
 * failed read is never read as "not configured"); `undefined` with no failure is still
 * loading, and reads as not known until the answer arrives.
 */
export function intakeState(intake: Intake | undefined, failed: boolean): IntakeReading {
  if (failed || !intake) return { state: 'not_known', column: '' }
  if (!intake.connection.configured) return { state: 'not_configured', column: '' }
  const column = intake.listener.column || intake.connection.column || ''
  if (!intake.listener.enabled) return { state: 'not_listening', column }
  return { state: 'listening', column }
}

/** The lead of the line, the same on every screen. */
export const INTAKE_LEAD = 'Work enters from your board:'

/**
 * The words after the lead. Each names the state and, for a person who can act, the act —
 * never that a ticket will be built: a ready ticket waits for an operator's Register act.
 */
export function intakeWords(reading: IntakeReading): string {
  switch (reading.state) {
    case 'not_known':
      return 'intake state not known — the intake read failed, so this page cannot say whether the board is being read'
    case 'not_configured':
      return 'not configured — an admin sets the tracker, the project and the column for the deployment, then an operator switches this repository’s listener on'
    case 'not_listening':
      return 'configured but not listening — an operator switches this repository’s listener on; nothing on the board is read or written until then'
    case 'listening':
      return `listening on “${reading.column || '—'}” — a ticket moved into that column is read and told what a good acceptance test still needs; a ready ticket waits for an operator’s Register act`
  }
}

/** The whole line: `Work enters from your board: <words>`. */
export function intakeLine(intake: Intake | undefined, failed: boolean): string {
  return `${INTAKE_LEAD} ${intakeWords(intakeState(intake, failed))}`
}
