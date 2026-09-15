/**
 * ui/src/screens/Runs/RunNewDialog.tsx — the POST body carries exactly what was set: config, budget caps, rungs.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests for the run dialog against a mocked API.
 * What it does: Pins that `builder_config` is sent only when given and as a parsed object,
 *               that invalid JSON / an identity key / a credential key block submit with the
 *               reason, that the executor default and configured builders show for an admin
 *               and "server default" otherwise, that the Claude Code login toggle merges
 *               `{"auth": "cli"}` (and is disabled on invalid JSON), that non-build kinds hide
 *               the builder block, that the Budget section shows the defaults and sends only
 *               typed caps (omitted when all blank), that the blind sweep preset replaces the
 *               ladder with three object rungs at 25 → 50 → 100 tool calls, that object rungs
 *               follow the labels with provider and typed caps only, and that an empty
 *               ladder or an incomplete rung blocks submit.
 * How:          `mockApi` records the POST body; `userEvent` drives the form; assertions on
 *               the body and the field errors.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Runs/RunNewDialog.tsx (the code under test),
 *               ui/src/lib/jsonObject.ts (the rules the JSON cases pin), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Runs/RunNewDialog.test.tsx
 * Touch when:   a field is added to `POST /runs` (docs/API.md) — assert its presence and
 *               absence in the body.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal, Settings } from '../../api/types'
import { PRINCIPAL, json, mockApi, renderApp } from '../../test/utils'
import { BLIND_SWEEP_TOOL_CALLS, BUDGET_DEFAULTS, RunNewDialog, budgetFromDraft } from './RunNewDialog'

const ADMIN: Principal = { ...PRINCIPAL, role: 'admin' }
const SETTINGS: Settings = {
  // `/settings.builders` is the server's CREDENTIAL probe (crb.observability.probes)
  builders: [
    { name: 'anthropic', configured: true },
    { name: 'cerebras', configured: false },
    { name: 'claude_code_cli', configured: true },
  ],
  sandbox_mode: 'docker',
  retention: {},
  oidc_enabled: false,
  ledger_backend: 'sqlite',
  apparatus_version: '2.0',
  policy_version: 'p1',
}
const REPOS = { items: [{ name: 'httpx' }], total: 1, limit: 50, offset: 0 }

function setup(me: Principal = PRINCIPAL, withSettings = false) {
  const onCreated = vi.fn()
  const api = mockApi({
    'GET /auth/me': me,
    'GET /repos': REPOS,
    ...(withSettings ? { 'GET /settings': SETTINGS } : {}),
    'POST /runs': () => json({ id: 'run-9' }, 201),
  })
  renderApp(<RunNewDialog open onClose={() => {}} repo="httpx" onCreated={onCreated} />)
  return { ...api, onCreated }
}

async function postedBody(calls: ReturnType<typeof mockApi>['calls']): Promise<Record<string, unknown>> {
  await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
  const call = calls.find((c) => c.method === 'POST' && c.path === '/runs')!
  return JSON.parse(String(call.init?.body)) as Record<string, unknown>
}

describe('RunNewDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends builder_config only when given, as a parsed object', async () => {
    const user = userEvent.setup()
    const { calls, onCreated } = setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'claude_code')
    await user.type(screen.getByLabelText(/^Model/), 'claude-sonnet-5')
    await user.type(screen.getByLabelText(/Builder config/), '{{"auth": "cli", "effort": "high"}')
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body).toEqual({
      repo: 'httpx',
      kind: 'replay',
      mode: 'sighted',
      builder: 'claude_code',
      model: 'claude-sonnet-5',
      ladder: ['r1'],
      builder_config: { auth: 'cli', effort: 'high' },
    })
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
  })

  it('omits builder_config when the editor is blank', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'editblock')
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body).not.toHaveProperty('builder_config')
  })

  it('blocks submit on invalid JSON, an identity key or a credential key, with the reason', async () => {
    const user = userEvent.setup()
    setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'claude_code')
    const editor = screen.getByLabelText(/Builder config/)
    const submit = screen.getByRole('button', { name: 'Queue run' })
    await user.type(editor, '{{"auth": ')
    expect(editor).toHaveAttribute('aria-invalid', 'true')
    expect(submit).toBeDisabled()
    await user.clear(editor)
    await user.type(editor, '{{"model": "other"}')
    expect(screen.getByText(/recorded identity/)).toBeInTheDocument()
    expect(submit).toBeDisabled()
    await user.clear(editor)
    await user.type(editor, '{{"api_key": "sk-x"}')
    expect(screen.getByText(/looks like a credential/)).toBeInTheDocument()
    expect(submit).toBeDisabled()
    await user.clear(editor)
    await user.type(editor, '{{"effort": "high"}')
    expect(editor).not.toHaveAttribute('aria-invalid')
    expect(submit).toBeEnabled()
  })

  it('shows the server executor default and configured builders when the viewer is an admin', async () => {
    setup(ADMIN, true)
    await waitFor(() => expect(screen.getByRole('option', { name: 'server default (docker)' })).toBeInTheDocument())
    expect(screen.getByText(/Credentials on the server: anthropic, claude_code_cli/)).toBeInTheDocument()
  })

  it('reads "server default" when /settings is not readable', () => {
    setup()
    expect(screen.getByRole('option', { name: 'server default' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /docker\)/ })).not.toBeInTheDocument()
  })

  it('"Use my Claude Code login (dev)" toggles {"auth":"cli"} in the builder config, merging with other keys', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    expect(screen.queryByLabelText(/Use my Claude Code login/)).not.toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'claude_code')
    expect(screen.getByLabelText(/^Model/)).toHaveAttribute('placeholder', 'claude-sonnet-5')
    const editor = screen.getByLabelText(/Builder config/)
    await user.type(editor, '{{"effort": "high"}')
    const toggle = screen.getByLabelText(/Use my Claude Code login/)
    expect(toggle).not.toBeChecked()
    await user.click(toggle)
    expect(toggle).toBeChecked()
    expect(editor).toHaveValue('{\n  "effort": "high",\n  "auth": "cli"\n}')
    await user.click(toggle)
    expect(toggle).not.toBeChecked()
    expect(editor).toHaveValue('{\n  "effort": "high"\n}')
    await user.click(toggle)
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body.builder_config).toEqual({ effort: 'high', auth: 'cli' })
  })

  it('the toggle is disabled while the editor holds invalid JSON', async () => {
    const user = userEvent.setup()
    setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'claude_code')
    await user.type(screen.getByLabelText(/Builder config/), '{{"auth": ')
    expect(screen.getByLabelText(/Use my Claude Code login/)).toBeDisabled()
  })

  it('non-build kinds hide the builder block and never send builder_config', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.selectOptions(screen.getByLabelText(/^Kind/), 'mine')
    expect(screen.queryByLabelText(/Builder config/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('run-budget')).not.toBeInTheDocument()
    expect(screen.queryByTestId('run-ladder')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body).toEqual({ repo: 'httpx', kind: 'mine' })
  })

  // --- budget + ladder (C8) --------------------------------------------------------------------

  it('the Budget section shows the builder defaults and sends only the caps that were typed', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'claude_code')
    const budget = screen.getByTestId('run-budget')
    for (const [label, def] of [
      ['Max turns', 25],
      ['Max tool calls', 25],
      ['Max tokens', 0],
      ['Max cost (USD)', 0],
      ['Wall clock (s)', 900],
    ] as const) {
      expect(within(budget).getByLabelText(label)).toHaveAttribute('placeholder', String(def))
    }
    expect(BUDGET_DEFAULTS).toEqual({ max_turns: 25, max_tool_calls: 25, max_tokens: 0, max_cost_usd: 0, wall_clock_s: 900 })
    await user.type(within(budget).getByLabelText('Max tool calls'), '50')
    await user.type(within(budget).getByLabelText('Wall clock (s)'), '1800')
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body.budget).toEqual({ max_tool_calls: 50, wall_clock_s: 1800 })
    expect(body.ladder).toEqual(['r1'])
  })

  it('omits budget when every cap is blank', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'editblock')
    await user.type(screen.getByLabelText(/^Model/), 'gpt-oss-120b')
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body).not.toHaveProperty('budget')
    expect(budgetFromDraft({ max_turns: '', max_tool_calls: ' ' })).toBeUndefined()
    expect(budgetFromDraft({ max_turns: '3', max_cost_usd: '0.5', max_tokens: 'abc' })).toEqual({ max_turns: 3, max_cost_usd: 0.5 })
  })

  it('the blind sweep preset replaces the ladder with three object rungs of the same model at 25 → 50 → 100 tool calls', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.selectOptions(screen.getByLabelText(/^Kind/), 'blind')
    const preset = screen.getByRole('button', { name: 'Blind budget sweep 25 → 50 → 100 tool calls' })
    expect(preset).toBeDisabled() // no builder yet
    expect(screen.getByText('Name a builder and a model to add rungs.')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'claude_code')
    expect(preset).toBeEnabled() // claude_code has a default model
    await user.click(preset)
    const list = screen.getByRole('list', { name: 'Ladder rungs' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByLabelText(/^Ladder$/)).toHaveValue('') // the preset IS the ladder
    expect(within(list).getByLabelText('Rung 1 tool calls')).toHaveValue(25)
    expect(within(list).getByLabelText('Rung 3 tool calls')).toHaveValue(100)
    expect(within(list).getByLabelText(/^Rung 2 model/)).toHaveValue('claude-sonnet-5')
    expect(within(list).getByText('tier 50/25/900')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body).toEqual({
      repo: 'httpx',
      kind: 'blind',
      mode: 'blind',
      builder: 'claude_code',
      ladder: BLIND_SWEEP_TOOL_CALLS.map((n) => ({ builder: 'claude_code', model: 'claude-sonnet-5', budget: { max_tool_calls: n } })),
    })
  })

  it('object rungs are appended after the labels, carry provider + typed caps only, and can be removed', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'openai_agent')
    await user.type(screen.getByLabelText(/^Model/), 'gpt-oss-120b')
    await user.type(screen.getByLabelText(/^Provider/), 'cerebras')
    await user.click(screen.getByRole('button', { name: 'Add rung' }))
    await user.click(screen.getByRole('button', { name: 'Add rung' }))
    const list = screen.getByRole('list', { name: 'Ladder rungs' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    // rung 1: inherits everything (no budget sent); rung 2: a bigger cap and a different model
    await user.clear(within(list).getByLabelText(/^Rung 2 model/))
    await user.type(within(list).getByLabelText(/^Rung 2 model/), 'zai-glm-4.7')
    await user.type(within(list).getByLabelText('Rung 2 turns'), '60')
    await user.type(within(list).getByLabelText('Rung 2 wall clock (s)'), '1800')
    // a third rung, removed again
    await user.click(screen.getByRole('button', { name: 'Add rung' }))
    await user.click(screen.getByRole('button', { name: 'Remove rung 3' }))
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body.ladder).toEqual([
      'r1',
      { builder: 'openai_agent', model: 'gpt-oss-120b', provider: 'cerebras' },
      { builder: 'openai_agent', model: 'zai-glm-4.7', provider: 'cerebras', budget: { max_turns: 60, wall_clock_s: 1800 } },
    ])
  })

  it('an empty ladder (no labels, no rungs) or an incomplete rung blocks submit with the reason', async () => {
    const user = userEvent.setup()
    setup()
    await user.type(screen.getByPlaceholderText('editblock · openai_agent · claude_code'), 'editblock')
    await user.type(screen.getByLabelText(/^Model/), 'm')
    const submit = screen.getByRole('button', { name: 'Queue run' })
    const ladder = screen.getByLabelText(/^Ladder$/)
    await user.clear(ladder)
    expect(screen.getByText(/needs at least one rung/)).toBeInTheDocument()
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Add rung' }))
    expect(submit).toBeEnabled()
    const list = screen.getByRole('list', { name: 'Ladder rungs' })
    await user.clear(within(list).getByLabelText(/^Rung 1 model/))
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Clear rungs' }))
    await user.type(ladder, 'r1')
    expect(submit).toBeEnabled()
  })
})
