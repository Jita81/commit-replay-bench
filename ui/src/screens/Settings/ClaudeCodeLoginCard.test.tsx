/**
 * ui/src/screens/Settings/ClaudeCodeLoginCard.tsx — a token value never appears in the page, in any state.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests for the Claude Code login card against a mocked API.
 * What it does: Pins the operator instruction and the absent status; presence with the
 *               ≤ 4-char fingerprint and provenance and never a value; a viewer sees status
 *               only (no form, no buttons, no host path); the paste field is a password input
 *               that is never echoed and is cleared after a save; a shape rejection renders
 *               without the token; Verify shows ok / invalid and the 429 when rate-limited;
 *               Remove returns the status to absent.
 * How:          `mockApi` with `SecretsStatusList` / `LoginCheck` fixtures; `userEvent` for
 *               the paste and clicks; assertions that the fake token string is absent from
 *               the DOM after every step.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/ClaudeCodeLoginCard.tsx and
 *               ui/src/screens/Settings/claudeCodeLogin.ts (the code under test),
 *               ui/src/test/utils.tsx, tests/test_server_routes_admin_secrets.py (the
 *               server-side half of the same property)
 * Tested by:    ui/src/screens/Settings/ClaudeCodeLoginCard.test.tsx
 * Touch when:   a status field or a verify outcome is added — extend the fixtures and keep
 *               the "never a value" assertion on every case.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal } from '../../api/types'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { ClaudeCodeLoginCard } from './ClaudeCodeLoginCard'
import type { LoginCheck, SecretStatus, SecretsStatusList } from './claudeCodeLogin'

const ADMIN: Principal = { ...PRINCIPAL, role: 'admin' }
const VIEWER: Principal = { ...PRINCIPAL, role: 'viewer' }
const TOKEN = 'sk-ant-oat01-' + 'Q'.repeat(70) + '-GOOD'
const PATH = '/settings/secrets/claude-code-token'

const ABSENT: SecretStatus = { name: 'claude_code_oauth_token', present: false, fingerprint: '', set_at: '', set_by: '' }
const PRESENT: SecretStatus = { name: 'claude_code_oauth_token', present: true, fingerprint: 'GOOD', set_at: '2026-09-13T10:00:00+00:00', set_by: 'root' }

function list(status: SecretStatus, dir = '/srv/crb/secrets'): SecretsStatusList {
  return { items: [status], secrets_dir: dir }
}

const OK: LoginCheck = { status: 'ok', detail: 'pong', source: 'explicit', fingerprint: 'GOOD', model: 'claude-haiku-4-5', cli_version: '2.1.132 (Claude Code)', duration_s: 2.4, cost_usd: 0 }
const INVALID: LoginCheck = { ...OK, status: 'invalid', detail: 'authentication failed (HTTP 401)' }

function setup(me: Principal, routes: Record<string, unknown>) {
  const api = mockApi({ 'GET /auth/me': me, ...routes })
  renderApp(<ClaudeCodeLoginCard />)
  return api
}

describe('ClaudeCodeLoginCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the exact operator instruction and the absent status', async () => {
    setup(ADMIN, { 'GET /settings/secrets': list(ABSENT) })
    const status = await screen.findByTestId('claude-login-status')
    expect(status).toHaveAttribute('data-present', 'false')
    expect(status).toHaveTextContent('no token stored')
    const text = screen.getByTestId('claude-login-instructions').textContent ?? ''
    expect(text).toContain('Run claude setup-token on any machine, paste the token here; it is stored owner-only on the API host under CRB_HOME/secrets and forwarded to builders only in auth: cli mode.')
    expect(text).toContain('/srv/crb/secrets')
    // nothing to verify or remove yet
    expect(screen.getByTestId('claude-login-verify')).toBeDisabled()
    expect(screen.getByTestId('claude-login-remove')).toBeDisabled()
  })

  it('shows presence, the ≤4-char fingerprint and provenance — never a value', async () => {
    setup(ADMIN, { 'GET /settings/secrets': list(PRESENT) })
    const status = await screen.findByTestId('claude-login-status')
    expect(status).toHaveAttribute('data-present', 'true')
    expect(status).toHaveTextContent('…GOOD')
    expect(screen.getByTestId('claude-login-provenance')).toHaveTextContent('set by root')
    expect(document.body.textContent).not.toContain(TOKEN)
    expect(screen.getByTestId('claude-login-verify')).toBeEnabled()
    expect(screen.getByTestId('claude-login-remove')).toBeEnabled()
  })

  it('viewer sees status only — no form, no buttons, no host path', async () => {
    setup(VIEWER, { 'GET /settings/secrets': list(PRESENT, '') })
    await screen.findByTestId('claude-login-status')
    expect(screen.getByTestId('claude-login-readonly')).toBeInTheDocument()
    expect(screen.queryByTestId('claude-login-token')).not.toBeInTheDocument()
    expect(screen.queryByTestId('claude-login-save')).not.toBeInTheDocument()
    expect(screen.queryByTestId('claude-login-verify')).not.toBeInTheDocument()
    expect(screen.queryByTestId('claude-login-remove')).not.toBeInTheDocument()
    expect(screen.getByTestId('claude-login-instructions').textContent).not.toContain('On this host')
  })

  it('the paste field is a password input that is never echoed and is cleared after a save', async () => {
    const user = userEvent.setup()
    let stored: SecretStatus = ABSENT
    const { calls } = setup(ADMIN, {
      'GET /settings/secrets': () => json(list(stored)),
      [`PUT ${PATH}`]: (_url: string, init: RequestInit | undefined) => {
        const body = JSON.parse(String(init?.body)) as { token: string }
        expect(body).toEqual({ token: TOKEN })
        stored = PRESENT
        return json(PRESENT)
      },
    })
    const field = await screen.findByTestId('claude-login-token')
    expect(field).toHaveAttribute('type', 'password')
    expect(field).toHaveAttribute('autocomplete', 'off')
    expect(screen.getByTestId('claude-login-save')).toBeDisabled()
    await user.type(field, `  ${TOKEN}  `)
    expect(screen.getByTestId('claude-login-save')).toBeEnabled()
    await user.click(screen.getByTestId('claude-login-save'))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.path === PATH)).toBe(true))
    await waitFor(() => expect(field).toHaveValue(''))
    await waitFor(() => expect(screen.getByTestId('claude-login-status')).toHaveAttribute('data-present', 'true'))
    // the value is in the request body and nowhere in the DOM
    expect(document.body.innerHTML).not.toContain(TOKEN)
    expect(document.body.innerHTML).not.toContain('Q'.repeat(20))
  })

  it('surfaces a shape rejection from the server without echoing the token', async () => {
    const user = userEvent.setup()
    setup(ADMIN, {
      'GET /settings/secrets': list(ABSENT),
      [`PUT ${PATH}`]: () => envelope(422, 'invalid_token', "a Claude Code token starts with 'sk-ant-oat01-' (mint one with `claude setup-token`)"),
    })
    const field = await screen.findByTestId('claude-login-token')
    await user.type(field, 'sk-ant-api03-not-a-setup-token-value-xxxxxxxx')
    await user.click(screen.getByTestId('claude-login-save'))
    expect(await screen.findByText(/starts with 'sk-ant-oat01-'/)).toBeInTheDocument()
    expect(field).toHaveValue('sk-ant-api03-not-a-setup-token-value-xxxxxxxx') // kept so it can be corrected
  })

  it('Verify shows ok / invalid and the 429 when rate-limited', async () => {
    const user = userEvent.setup()
    let n = 0
    setup(ADMIN, {
      'GET /settings/secrets': list(PRESENT),
      [`POST ${PATH}/verify`]: () => {
        n += 1
        if (n === 1) return json(OK)
        if (n === 2) return envelope(429, 'rate_limited', 'verify runs at most once every 10 s; retry in 10 s', { retry_after_s: 10 })
        return json(INVALID)
      },
    })
    const verify = await screen.findByTestId('claude-login-verify')
    await waitFor(() => expect(verify).toBeEnabled())
    await user.click(verify)
    const result = await screen.findByTestId('claude-login-verify-result')
    expect(result).toHaveAttribute('data-status', 'ok')
    expect(result).toHaveTextContent('ok — the login works')
    expect(result).toHaveTextContent('claude-haiku-4-5 · claude 2.1.132 (Claude Code) · 2.4s')
    await user.click(verify)
    expect(await screen.findByText(/retry in 10 s/)).toBeInTheDocument()
    await user.click(verify)
    await waitFor(() => expect(screen.getByTestId('claude-login-verify-result')).toHaveAttribute('data-status', 'invalid'))
    expect(screen.getByTestId('claude-login-verify-result')).toHaveTextContent('authentication failed (HTTP 401)')
  })

  it('Remove deletes the token and the status goes back to absent', async () => {
    const user = userEvent.setup()
    let stored: SecretStatus = PRESENT
    const { calls } = setup(ADMIN, {
      'GET /settings/secrets': () => json(list(stored)),
      [`DELETE ${PATH}`]: () => {
        stored = ABSENT
        return json(ABSENT)
      },
    })
    const remove = await screen.findByTestId('claude-login-remove')
    await waitFor(() => expect(remove).toBeEnabled())
    await user.click(remove)
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === PATH)).toBe(true))
    await waitFor(() => expect(screen.getByTestId('claude-login-status')).toHaveAttribute('data-present', 'false'))
  })
})
