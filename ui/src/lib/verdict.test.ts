/**
 * verdict.ts — the route, band and gate sentences say what the policy licenses; every event
 * action has a plain sentence.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the presentation tables' copy and `actionHelp`.
 * What it does: Pins that the human route names all three causes (weak tests, controls gate
 *               failed, a cheat graded clean), that deliver and the strong band say "a branch
 *               and pull request under review" and never "auto-ship" / "merge"-as-licensed,
 *               that the gate labels are "Clears the bar" / "Review-gated" / "Needs a human",
 *               and that `actionHelp` returns one sentence for every action in the event
 *               vocabulary (grouped by stage) with a generic sentence for an unknown one.
 * How:          Plain assertions over the exported lookups.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/lib/verdict.ts, ui/src/components/LiveLog.tsx (renders `actionHelp`)
 * Tested by:    ui/src/lib/verdict.test.ts
 * Touch when:   a route, band, gate or event action is added on the server.
 */
import { describe, expect, it } from 'vitest'
import { ACTION_HELP, actionHelp, bandDisplay, gateDisplay, routeDisplay } from './verdict'

/** The vocabulary (scratch: journeys/telemetry-vocabulary.md), stage by stage. */
const VOCABULARY = [
  // system
  'run.claimed', 'run.executor', 'run.error', 'run.finish_refused', 'run.finished', 'run.outage_stop', 'run.skip', 'run.start', 'run.done',
  'run.cancel_requested', 'run.reclaimed', 'run.abandoned', 'repo.clone.start', 'repo.clone.done', 'probe.start', 'probe.done',
  // prep
  'setup.auto', 'setup.start', 'setup.step', 'setup.done', 'prep.start',
  // mine
  'mine.candidate', 'mine.red', 'mine.skip', 'mine.gold', 'mine.done', 'mine.task', 'mine.cancelled', 'label.task',
  // build
  'build.start', 'build.done', 'build.attempt', 'build.applied', 'build.turn', 'build.tool', 'build.event',
  'preflight.fixed', 'preflight.repaired', 'preflight.rejected', 'preflight.error',
  // grade
  'grade.belt', 'grade.tamper', 'grade.malformed_oracle', 'grade.error',
  // ledger
  'ledger.append', 'ledger.pack_missing', 'ledger.pack_store_error',
  // oracle
  'oracle.mutation.mutant', 'oracle.mutation.scored', 'oracle.mutation.uncompilable', 'oracle.mutation.unscoreable', 'oracle.mutation.error', 'oracle.score',
  'controls.control', 'controls.row', 'controls.skip', 'controls.error', 'controls.done', 'controls.report',
  // factory
  'item.start', 'item.done', 'item.error', 'item.blocked', 'item.outcome', 'readiness.assessed', 'readiness.refused', 'route.decided',
  'author.start', 'author.done', 'red.start', 'red.proved', 'red.refused', 'build.oracle_staged', 'build.graded',
  'delivery.skipped', 'delivery.withheld', 'delivery.override', 'delivery.error', 'delivery.opened', 'delivery.refused',
  'review.start', 'review.probe', 'review.verdict', 'review.recorded', 'rework.start', 'horizon.checkpoint',
  'backlog.frozen', 'backlog.evolved', 'gap.signoff', 'edit.permitted',
  // audit traces
  'repo.created', 'repo.updated', 'github.installation.recorded', 'signoff.created', 'signoff.refused', 'signoff.revoked', 'review.created', 'review.refused',
]

describe('route, band and gate copy', () => {
  it('the human route names every cause the rule has', () => {
    const d = routeDisplay('human').describe
    expect(d).toMatch(/tests are too weak/)
    expect(d).toMatch(/controls gate failed/)
    expect(d).toMatch(/cheat graded clean/)
  })

  it('deliver licenses a branch and pull request under review, never a merge', () => {
    expect(routeDisplay('deliver').describe).toMatch(/branch and pull request under review/)
    expect(routeDisplay('deliver').describe).toMatch(/never a claim the change is safe to merge/)
    expect(routeDisplay('calibrate').describe).toMatch(/more attempts or the controls run can change it/)
  })

  it('no band or gate says auto-ship', () => {
    for (const b of ['strong', 'adequate', 'weak', 'unscoreable']) expect(bandDisplay(b).describe).not.toMatch(/auto-?ship/i)
    for (const g of ['auto_ship', 'human_review', 'needs_human']) {
      expect(gateDisplay(g).label).not.toMatch(/auto-?ship/i)
      expect(gateDisplay(g).describe).not.toMatch(/auto-?ship/i)
    }
    expect(bandDisplay('strong').describe).toBe('Oracle strength: strong — the tests notice a wrong patch; clears the deliver bar')
    expect(bandDisplay('adequate').describe).toBe('Oracle strength: adequate — clears the bar; every change still goes to review')
    expect(bandDisplay('weak').describe).toBe('Oracle strength: weak — a green is low confidence; the cell routes to a human')
    expect(gateDisplay('auto_ship').label).toBe('Clears the bar')
    expect(gateDisplay('auto_ship').describe).toBe('Gate: clears the oracle bar for deliver — a branch and pull request under review, never a merge')
    expect(gateDisplay('human_review').label).toBe('Review-gated')
    expect(gateDisplay('needs_human').label).toBe('Needs a human')
  })

  it('describe sentences carry no trailing full stop (VerdictPill appends the reason after one)', () => {
    for (const r of ['deliver', 'calibrate', 'granularize', 'human', 'do_not_ship']) expect(routeDisplay(r).describe).not.toMatch(/\.$/)
  })
})

describe('actionHelp', () => {
  it('has one plain sentence for every action in the vocabulary', () => {
    for (const a of VOCABULARY) {
      const s = ACTION_HELP[a]
      expect(s, `no ACTION_HELP for ${a}`).toBeDefined()
      expect(s, a).toMatch(/^[A-Z].*\.$/)
      expect(s, a).not.toMatch(/!/)
      expect(actionHelp(a)).toBe(s)
    }
  })

  it('the three sentences the audit wrote are used verbatim', () => {
    expect(actionHelp('delivery.withheld')).toBe('Built clean, but the map does not route deliver for this cell: no branch, no pull request; the measured route is on the chain.')
    expect(actionHelp('build.turn')).toBe('One builder turn (a model call and its tool calls).')
    expect(actionHelp('grade.tamper')).toBe('A test file was changed; the row is disqualified, not counted.')
  })

  it('an unknown action gets a generic sentence naming the action, and a builder.* event its family', () => {
    expect(actionHelp('something.new')).toBe('An event the loop emitted as “something.new”; this version of the UI has no sentence for it.')
    expect(actionHelp('builder.tool_result')).toMatch(/builder/)
    expect(actionHelp('')).toMatch(/no sentence/)
  })
})
