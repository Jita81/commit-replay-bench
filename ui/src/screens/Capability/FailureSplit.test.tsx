/**
 * The failure split says "your login" apart from "the provider" (pilot D1).
 *
 * Navigation
 * ----------
 * What it is:   The unit tests of `FailureSplitPills`' outage count and its login part.
 * What it does: Proves that when some outages were calls refused because this deployment's own
 *               login was rejected, the outage pill says how many — in its text and in the
 *               accessible label — and that a split with none says nothing extra.
 * How:          Renders the pills with a hand-built split through `renderApp` and reads the
 *               `kind-outage-auth` test id and the group's `aria-label`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Capability/FailureSplit.tsx (under test),
 *               ui/src/screens/Capability/contract.ts (`FailureSplit.outage_auth`),
 *               src/crb/core/ledger.py (`FailureSplit.outage_auth` — the count served)
 * Tested by:    ui/src/screens/Capability/FailureSplit.test.tsx
 * Touch when:   never for a new repository; when the outage causes change on the server.
 */
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../../test/utils'
import type { FailureSplit } from './contract'
import { FailureSplitPills } from './FailureSplit'

const BASE: FailureSplit = { builder_red: 0, budget: 0, protocol: 0, harness: 0, disqualified: 0 }

describe('FailureSplitPills — the cause of an outage', () => {
  it('says how many outages were this deployment’s own login, in the text and the label', () => {
    renderApp(<FailureSplitPills split={{ ...BASE, outage: 3, outage_auth: 2 }} />)
    expect(screen.getByTestId('kind-outage-auth')).toHaveTextContent('(login 2)')
    expect(screen.getByTestId('failure-split').getAttribute('aria-label')).toContain('outage 3 (login 2)')
  })

  it('adds nothing when no outage was a refused login', () => {
    renderApp(<FailureSplitPills split={{ ...BASE, outage: 3, outage_auth: 0 }} />)
    expect(screen.queryByTestId('kind-outage-auth')).toBeNull()
    expect(screen.getByTestId('failure-split').getAttribute('aria-label')).toContain('outage 3,')
  })
})
