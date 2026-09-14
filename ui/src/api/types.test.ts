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
