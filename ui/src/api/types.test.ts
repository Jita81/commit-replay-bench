/**
 * ui/src/api/types.ts — `ladderEntryLabel`, the one-line rendering of a ladder entry.
 *
 * Navigation
 * ----------
 * What it is:   Unit test for `ladderEntryLabel` in ui/src/api/types.ts.
 * What it does: Pins that a string rung label passes through unchanged and an object rung
 *               renders as `builder:model[@provider]` followed only by the budget caps it
 *               actually set — an inherited (undefined) cap is not a cap, so two rungs that
 *               differ only by inheritance read the same.
 * How:          Direct calls with label strings and object rungs; one assertion per shape.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/types.ts (the code under test), ui/src/screens/Runs/RunDetailPage.tsx
 *               (renders the ladder with this label), ui/src/screens/Runs/RunNewDialog.tsx
 *               (builds the object rungs a budget sweep declares)
 * Tested by:    ui/src/api/types.test.ts
 * Touch when:   `RunBudget` gains a cap field or the rung label format changes (docs/API.md
 *               "POST /runs: ladder") — extend the cases with the new cap.
 */
import { describe, expect, it } from 'vitest'
import { ladderEntryLabel } from './types'

describe('ladderEntryLabel', () => {
  it('passes a label through and renders an object rung as identity + the caps it set', () => {
    expect(ladderEntryLabel('r1')).toBe('r1')
    expect(ladderEntryLabel('claude_code:claude-sonnet-5:anthropic')).toBe('claude_code:claude-sonnet-5:anthropic')
    expect(ladderEntryLabel({ builder: 'claude_code', model: 'claude-sonnet-5' })).toBe('claude_code:claude-sonnet-5')
    expect(ladderEntryLabel({ builder: 'editblock', model: 'gpt-oss-120b', provider: 'cerebras' })).toBe('editblock:gpt-oss-120b@cerebras')
    expect(ladderEntryLabel({ builder: 'claude_code', model: 'claude-sonnet-5', budget: { max_tool_calls: 50 } })).toBe('claude_code:claude-sonnet-5 [max_tool_calls=50]')
    expect(ladderEntryLabel({ builder: 'claude_code', model: 'm', provider: 'p', budget: { max_tool_calls: 100, wall_clock_s: 1800 } })).toBe(
      'claude_code:m@p [max_tool_calls=100 wall_clock_s=1800]',
    )
    // an inherited cap (undefined) is not a cap
    expect(ladderEntryLabel({ builder: 'b', model: 'm', budget: { max_turns: undefined } })).toBe('b:m')
  })
})
