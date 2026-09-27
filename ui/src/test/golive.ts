/**
 * A go-live reading for screen tests — one line of each state, as `GET /golive` serves it.
 *
 * Navigation
 * ----------
 * What it is:   The shared `GOLIVE` fixture (src/crb/server/golive.py's shape): a proven and an
 *               unproven product line, an attested and an unproven operator line.
 * What it does: Lets the Deployment page and the Settings card be tested against one reading.
 * How:          A typed constant.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0045-go-live-lines-are-proven-or-attested.md
 * Works with:   ui/src/components/govuk.test.tsx (the five groups),
 *               ui/src/screens/Posture/PosturePage.test.tsx (the go-live section),
 *               ui/src/screens/Settings/AttestationsCard.test.tsx (the recording),
 *               ui/src/help/hints-ratchet.instrument.tsx (the hint ratchet's screens)
 * Tested by:    the files above
 * Touch when:   never for a new repository; the go-live reading's shape changes.
 */
import type { GoLive } from '../api/types'

/** A go-live reading with one line of each state (src/crb/server/golive.py). */
export const GOLIVE: GoLive = {
  lines: [
    { id: 'health-green', title: 'The health check is green', proves: 'product', source: 'GET /health, read when this page was loaded', doc: 'DEPLOYMENT#8-go-live-checklist', state: 'proven', detail: '11 probes ok or skipped', attestation: null },
    { id: 'sealed-posture', title: 'Tests and the builder both run sealed in docker', proves: 'product', source: 'the posture of GET /health (ADR-0023)', doc: 'DEPLOYMENT#34-the-workers-sandbox--choose-deliberately', state: 'unproven', detail: 'tests run local, the builder runs host', attestation: null },
    { id: 'egress-denied', title: 'An egress test from a worker pod to a public address fails', proves: 'operator', source: 'an admin’s attestation (the test runs in the cluster, outside the product)', doc: 'DEPLOYMENT#8-go-live-checklist', state: 'attested', detail: 'root recorded on 2026-09-26 that it was done on 2026-09-25', attestation: { by: 'root', actor: 'u1', performed_on: '2026-09-25', recorded_at: '2026-09-26T10:00:00+00:00', statement: 'curl to 1.1.1.1 from worker-0 timed out; CHG-1042' } },
    { id: 'penetration-test', title: 'A penetration test of this deployment has been done and its findings handled', proves: 'operator', source: 'an admin’s attestation (the test is commissioned outside the product)', doc: 'SECURITY#5-what-this-document-does-not-claim', state: 'unproven', detail: 'no attestation is recorded', attestation: null },
  ],
  counts: { lines: 4, proven: 1, attested: 1, unproven: 2 },
  checked_at: '2026-09-27T09:00:00+00:00',
}
