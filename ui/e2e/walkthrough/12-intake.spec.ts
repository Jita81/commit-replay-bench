/**
 * 12 — work arriving from the team's own board: a ticket enters the watched column, the
 * product says what is missing, a person answers it, and the ticket becomes a registered,
 * queued item. The pull-request note and the mapped outcome transition are NOT walked here —
 * reaching them needs a delivered pull request, and this spec spends nothing; they are proved
 * at unit and route level (`test_the_pull_request_link_reaches_the_ticket_it_came_from`,
 * `test_a_configured_outcome_map_moves_the_ticket_after_the_merge`) and the missing
 * walkthrough leg is G-931 in docs/dod/journeys/intake-from-a-ticket.md.
 *
 * **No real Azure DevOps or Jira is contacted by this spec or by CI.** The stack runs with
 * `CRB_ENABLE_FAKE_TRACKER=1` and `CRB_INTAKE__TRACKER=fake`, so the whole board is one
 * JSON file (`CRB_E2E_BOARD`) that this spec writes and reads. Everything above the six
 * tracker verbs — the readiness gate, the classifier, the comment, the label, the frozen
 * backlog, the evidence chain and the screen — is the product's own code, unchanged.
 *
 * Navigation
 * ----------
 * What it is:   Walkthrough spec 12 (intake: /factory/intake → /factory), tier 1 only; it
 *               spends nothing and calls no model.
 * What it does: Walks the journey as the operator. The listener starts OFF and the screen
 *               says so; switching it on is refused for a viewer and recorded for an
 *               operator. A ticket with a missing acceptance fact is read, labelled
 *               `crb:needs-info` on the board, and nothing is registered. The person edits
 *               the ticket (the board file) and its revision moves; the next read drafts it
 *               and registers nothing (ADR-0022); the operator presses Register, and it is
 *               registered, labelled `crb:queued` and linked. A second read of an unchanged
 *               column writes nothing. The screen shows every step at 375 px and 1280 px, and
 *               the listener goes off again at the end.
 *               The worker's own timed poll is parked by the stack (`CRB_INTAKE__POLL_S`
 *               a day), so every read here is one an operator asked for and the counts this
 *               spec asserts belong to that click; the timer is tests/test_intake_worker.py's.
 * How:          support.ts's `test` fixture, which has ALREADY signed in as the admin —
 *               calling `signIn` again would go to /login, which redirects an authenticated
 *               person away, and wait for a form that never renders; a viewer persona in its
 *               own context for the role gate; `POST /factory/{repo}/intake/poll` through the
 *               UI buttons; and Node's `fs` to write and read the fake board — the tracker's
 *               whole state.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md,
 *               docs/adr/0022-intake-approval-by-default.md
 * Works with:   ui/e2e/walkthrough/support.ts (`env.board`, the already-signed-in `test`
 *               fixture, `personaPassword`),
 *               ui/src/screens/Factory/IntakePage.tsx (under test),
 *               src/crb/intake/fake.py (the board this spec writes),
 *               src/crb/server/intake.py (the flow), scripts/walkthrough.sh (the stack),
 *               tests/test_server_routes_intake.py (the same journey at the API)
 * Tested by:    scripts/walkthrough.sh (runs it, tier 1)
 * Touch when:   a label or a stop reason is added; the screen's act labels change.
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { env, expect, primary, test } from './support'

test.describe.configure({ mode: 'serial' })

const REPO = primary().name
const KEY = '4711'
const COLUMN = 'Ready for manufacture'

interface Board {
  tickets: Record<string, Record<string, unknown>>
}

/** The ticket as it enters the column: a bug with one of its two acceptance facts missing. */
function thinTicket(): Board {
  return {
    tickets: {
      [KEY]: {
        title: 'Fix the crash when the cart is empty',
        body: 'steps to reproduce: open an empty cart. The page crashes.',
        acceptance_criteria: ['reproduction: open an empty cart and press Checkout'],
        type: 'Bug',
        tags: ['area:checkout'],
        points: 3,
        revision: '1',
        state: COLUMN,
        changed: '2026-09-22T09:00:00Z',
        url: 'https://tracker.invalid/4711',
      },
    },
  }
}

function readBoard(): Board {
  return JSON.parse(readFileSync(env.board, 'utf8')) as Board
}

function writeBoard(board: Board): void {
  writeFileSync(env.board, JSON.stringify(board, null, 1), 'utf8')
}

function tags(): string[] {
  return (readBoard().tickets[KEY]!.tags as string[]) ?? []
}

function comments(): Record<string, string> {
  return (readBoard().tickets[KEY]!.comments as Record<string, string>) ?? {}
}

/** Every comment this product has left on the ticket, concatenated. */
function commentText(): string {
  return Object.values(comments()).join('\n')
}

test.beforeAll(() => {
  test.skip(!env.board, 'CRB_E2E_BOARD is not set (the fake tracker is tier-1 only)')
  writeBoard(thinTicket())
})

test.describe('12 intake from a ticket (fake tracker)', () => {
  test('the listener is off on every repository until somebody switches it on', async ({ page }) => {
    await page.goto(`/factory/intake?repo=${REPO}`)
    await expect(page.getByRole('heading', { name: 'Work arriving from your board' })).toBeVisible()
    await expect(page.getByText('Not listening')).toBeVisible()
    await expect(page.getByText(/That is the default for every repository/)).toBeVisible()
    await expect(page.getByTestId('intake-empty')).toBeVisible()
    // nothing has been written to the board
    expect(tags()).toEqual(['area:checkout'])
  })

  test('switching the listener on is recorded under the name of the person who did it', async ({ page }) => {
    await page.goto(`/factory/intake?repo=${REPO}`)
    await page.getByRole('button', { name: 'Switch the listener on' }).click()
    await expect(page.getByTestId('intake-success')).toContainText(COLUMN)
    await expect(page.getByText('Listening')).toBeVisible()
    await expect(page.getByText(/Switched on by/)).toBeVisible()
  })

  test('a ticket missing an acceptance fact is told what is missing, and nothing is registered', async ({ page }) => {
    await page.goto(`/factory/intake?repo=${REPO}`)
    await page.getByRole('button', { name: 'Re-read the column now' }).click()
    await expect(page.getByTestId('intake-success')).toContainText('1 read')

    const row = page.getByTestId(`intake-row-${KEY}`)
    await expect(row).toContainText('needs information')
    await expect(row).toContainText('bug.fix')
    await expect(row).toContainText('nothing is registered until the questions are answered')

    // the ticket itself carries the label and the one marked comment
    expect(tags()).toContain('crb:needs-info')
    expect(Object.keys(comments())).toHaveLength(1)
    expect(commentText()).toContain('expected_behaviour')
    expect(commentText()).toContain('What is the correct behaviour instead?')
  })

  test('the comment names the cell’s route with its n and interval, read before any build', async () => {
    const text = commentText()
    expect(text).toContain('What we know about work like this')
    // Which branch is honest depends on the cell, and BOTH are asserted here, because
    // demanding a number from a cell nobody has measured is exactly the false reassurance
    // the floor exists to stop. Unmeasured: say so, and quote nothing — never a zero.
    // Measured: the route, its n and interval, and what the record says about false-Q1.
    if (/not been measured/.test(text)) {
      expect(text).toContain('It says nothing, not zero')
      expect(text).not.toContain('false-Q1')
    } else {
      expect(text).toMatch(/Route: \*\*/)
      expect(text).toContain('false-Q1')
    }
    // and the non-goals, so nobody fears a wider edit
    expect(text).toContain('never creates a ticket')
  })

  test('reading the same column again writes nothing to the ticket', async ({ page }) => {
    const before = JSON.stringify(readBoard())
    await page.goto(`/factory/intake?repo=${REPO}`)
    await page.getByRole('button', { name: 'Re-read the column now' }).click()
    await expect(page.getByTestId('intake-success')).toContainText('0 read')
    expect(JSON.stringify(readBoard())).toBe(before)
  })

  test('the person answers on the ticket; the next read drafts it, and an operator registers it', async ({ page }) => {
    const board = readBoard()
    const ticket = board.tickets[KEY]!
    ticket.acceptance_criteria = [
      'reproduction: open an empty cart and press Checkout',
      'expected_behaviour: the basket shows “Your basket is empty” and no error',
    ]
    ticket.revision = '2'
    ticket.changed = '2026-09-23T09:00:00Z'
    writeBoard(board)

    await page.goto(`/factory/intake?repo=${REPO}`)
    await page.getByRole('button', { name: 'Re-read the column now' }).click()
    // ADR-0022: a ready ticket is a DRAFT until an operator registers it — nothing yet
    await expect(page.getByTestId('intake-success')).toContainText('0 registered')
    await expect(page.getByTestId('intake-success')).toContainText('1 waiting for an operator to register them')
    const row = page.getByTestId(`intake-row-${KEY}`)
    await expect(row).toContainText('Waiting for an operator to register it')
    expect(tags()).not.toContain('crb:queued')

    // the operator reads the draft and registers it: the act is theirs, and it is recorded
    await row.getByRole('button', { name: 'Register this ticket' }).click()
    await expect(page.getByTestId('intake-success')).toContainText(`Registered ticket ${KEY} as fake-4711`)
    await expect(row).toContainText('queued')
    await expect(row).toContainText('fake-4711')

    expect(tags()).toContain('crb:queued')
    expect(commentText()).toContain('queued to be manufactured')
    expect(readBoard().tickets[KEY]!.links).toBeTruthy()
  })

  test('the item is in the frozen backlog the Factory screen shows', async ({ page }) => {
    await page.goto(`/factory?repo=${REPO}`)
    await expect(page.getByText('fake-4711').first()).toBeVisible()
  })

  test('“Post the feedback again” re-posts on a ticket whose comment was deleted', async ({ page }) => {
    const board = readBoard()
    delete board.tickets[KEY]!.comments
    writeBoard(board)

    await page.goto(`/factory/intake?repo=${REPO}`)
    await page.getByRole('button', { name: 'Post the feedback again' }).click()
    await expect(page.getByTestId('intake-success')).toContainText('1 read')
    expect(commentText()).toContain('Commit Replay Bench')
  })

  test('a viewer can read the column but cannot switch the listener or re-read it', async ({ browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    const { personaPassword, signIn } = await import('./support')
    await signIn(page, 'walk-viewer', personaPassword('walk-viewer'))
    await page.goto(`/factory/intake?repo=${REPO}`)
    await expect(page.getByText(/Only an operator can switch the listener/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Switch the listener on' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Re-read the column now' })).toHaveCount(0)
    await ctx.close()
  })

  test('at 375 px the intake screen does not scroll sideways', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 })
    await page.goto(`/factory/intake?repo=${REPO}`)
    await expect(page.getByRole('heading', { name: 'Work arriving from your board' })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })

  test('switching the listener off stops everything, and says so', async ({ page }) => {
    await page.goto(`/factory/intake?repo=${REPO}`)
    await page.getByRole('button', { name: 'Switch the listener off' }).click()
    await expect(page.getByTestId('intake-success')).toContainText('is off')
    await expect(page.getByRole('button', { name: 'Re-read the column now' })).toBeDisabled()
  })
})
