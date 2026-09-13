import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal, Settings } from '../../api/types'
import { PRINCIPAL, json, mockApi, renderApp } from '../../test/utils'
import { RunNewDialog } from './RunNewDialog'

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
    await user.click(screen.getByRole('button', { name: 'Queue run' }))
    const body = await postedBody(calls)
    expect(body).toEqual({ repo: 'httpx', kind: 'mine' })
  })
})
