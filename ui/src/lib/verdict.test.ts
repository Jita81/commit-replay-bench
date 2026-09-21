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
 *               and that `actionHelp` returns one sentence for every action in
 *               docs/API.md#event-vocabulary (read from the doc, the way
 *               tests/test_event_vocabulary.py reads it) and none for an action nothing
 *               emits, with a generic sentence for an unknown one.
 * How:          Plain assertions over the exported lookups; the doc as `?raw` text.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0003-one-routing-rule.md
 * Works with:   ui/src/lib/verdict.ts, ui/src/components/LiveLog.tsx (renders `actionHelp`),
 *               docs/API.md (the vocabulary table), tests/test_event_vocabulary.py (the
 *               server-side half of the same ratchet)
 * Tested by:    ui/src/lib/verdict.test.ts
 * Touch when:   a route, band, gate or event action is added on the server.
 */
import { describe, expect, it } from 'vitest'
import apiDoc from '../../../docs/API.md?raw'
import { HINTS } from '../help/hints'
import { ACTION_HELP, actionHelp, bandDisplay, beltDisplay, beltHint, gateDisplay, probeDisplay, routeDisplay, runStatusDisplay, tierDisplay } from './verdict'

/**
 * The vocabulary is docs/API.md#event-vocabulary — the table tests/test_event_vocabulary.py
 * keeps equal to what src/crb emits — read the way that test reads it (the second cell of
 * every six-cell row), so the UI's sentences cannot drift from the server's actions.
 */
function documentedActions(): string[] {
  const section = /^## Event vocabulary\n([\s\S]*?)(?=^## )/m.exec(apiDoc)?.[1] ?? ''
  const out = new Set<string>()
  for (const line of section.split('\n')) {
    const cells = line
      .trim()
      .replace(/^\||\|$/g, '')
      .split(/(?<!\\)\|/)
      .map((c) => c.trim())
    if (cells.length !== 6 || cells[0] === 'stage' || cells[0] === '---') continue
    for (const m of cells[1]!.matchAll(/`([a-z_]+(?:\.[a-z_]+)+)`/g)) out.add(m[1]!)
  }
  return Array.from(out).sort()
}
const VOCABULARY = documentedActions()

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

  it('every display a screen renders as a pill carries its hint id, and an unknown value falls back to a registry id, never to nothing', () => {
    for (const r of ['deliver', 'calibrate', 'granularize', 'human', 'do_not_ship']) expect(routeDisplay(r).hint).toBe(`route.${r}`)
    expect(routeDisplay(null).hint).toBe('route.not_yet_measured')
    expect(routeDisplay('new-route').hint).toBe('route.not_yet_measured')
    expect(runStatusDisplay('queued').hint).toBe('run.status')
    expect(runStatusDisplay('odd').hint).toBe('run.status')
    expect(probeDisplay('degraded').hint).toBe('probe.status')
    expect(bandDisplay('weak').hint).toBe('oracle.band')
    expect(gateDisplay('auto_ship').hint).toBe('oracle.gate')
    expect(tierDisplay('untrusted')?.hint).toBe('tier.verification')
    expect(beltDisplay(true, 'target_green').hint).toBe('belt.target_green')
    expect(beltDisplay(null, 'repo_lint_clean').hint).toBe('belt.repo_lint_clean')
    expect(beltHint('belt_from_the_future')).toBe('belt.tests_unmodified')
    for (const d of [routeDisplay('deliver'), runStatusDisplay('failed'), probeDisplay('ok'), bandDisplay('strong'), gateDisplay('needs_human'), tierDisplay('ab-confirmed')!]) {
      expect(d.hint && d.hint in HINTS, d.label).toBe(true)
    }
  })

  it('describe sentences carry no trailing full stop (VerdictPill appends the reason after one)', () => {
    for (const r of ['deliver', 'calibrate', 'granularize', 'human', 'do_not_ship']) expect(routeDisplay(r).describe).not.toMatch(/\.$/)
  })
})

describe('actionHelp', () => {
  it('has one plain sentence for every action in docs/API.md#event-vocabulary, and no sentence for an action nothing emits', () => {
    expect(VOCABULARY.length).toBeGreaterThan(90)
    expect(VOCABULARY).toContain('run.claimed')
    expect(VOCABULARY).toContain('builder.preflight.rejected')
    for (const a of VOCABULARY) {
      // a builder's own build.* event is written once, unprefixed; actionHelp strips the prefix
      const s = ACTION_HELP[a] ?? (a.startsWith('builder.build.') ? ACTION_HELP[a.slice('builder.'.length)] : undefined)
      expect(s, `no ACTION_HELP for ${a}`).toBeDefined()
      expect(s, a).toMatch(/^[A-Z].*\.$/)
      expect(s, a).not.toMatch(/!/)
      expect(actionHelp(a)).toBe(s)
    }
    const documented = new Set(VOCABULARY)
    const ghosts = Object.keys(ACTION_HELP).filter((k) => !documented.has(k))
    expect(ghosts, 'ACTION_HELP names actions the vocabulary table does not (nothing emits them)').toEqual([])
  })

  it('the belt-5 pre-flight and the sealed-container events are keyed as emitted — under the builder prefix', () => {
    expect(actionHelp('builder.preflight.rejected')).toBe('The patch was rejected before grading; the payload names why.')
    expect(actionHelp('builder.preflight.fixed')).toMatch(/fixed before grading/)
    expect(actionHelp('builder.sealed')).toMatch(/sealed in a container/)
    expect(ACTION_HELP['preflight.rejected']).toBeUndefined()
    expect(actionHelp('builder.build.turn')).toBe('One builder turn (a model call and its tool calls).')
  })

  it('an inherited key on an unvalidated event is not a sentence: the generic line, never Object.prototype', () => {
    // a malformed or pre-existing event could name `constructor` / `toString` / `__proto__` as its action;
    // `ACTION_HELP[action]` would then be a function or an object and LiveLog would hand it to JSX
    for (const a of ['constructor', 'toString', 'hasOwnProperty', '__proto__', 'builder.constructor', 'builder.__proto__']) {
      const s = actionHelp(a)
      expect(typeof s, a).toBe('string')
      expect(s, a).toMatch(a.startsWith('builder.') ? /^A builder-level event/ : /^An event the loop emitted as/)
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
