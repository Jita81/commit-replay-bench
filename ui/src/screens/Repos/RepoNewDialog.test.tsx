/**
 * ui/src/screens/Repos/RepoNewDialog.tsx — presets fill the body, the clone policy is enforced, bad JSON is refused.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests for the Add-repo dialog against a mocked API.
 * What it does: Pins that `parseScopeList` splits and trims; that a preset fills layout,
 *               runner options and belt scope and the POST body carries them; that invalid
 *               runner-options JSON and a non-object are refused and then recover; that a
 *               local path or `http://` is rejected as a URL but accepted as a clone path;
 *               that an explicit belt list needs at least one scope and is sent as a list;
 *               that the runner select follows the language; that the Form view offers the
 *               runner's own keys; and that a 422 envelope renders.
 * How:          `mockApi` records the POST body; `userEvent` drives the dialog; assertions on
 *               the request and on field errors.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/RepoNewDialog.tsx (the code under test),
 *               ui/src/lib/repoPresets.ts (the preset the cases apply), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Repos/RepoNewDialog.test.tsx
 * Touch when:   the clone policy, a preset or a field changes — extend the matching case.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RepoDetail } from '../../api/types'
import { PRINCIPAL, json, mockApi, renderApp } from '../../test/utils'
import { RepoNewDialog, parseScopeList } from './RepoNewDialog'

const CREATED: Partial<RepoDetail> = { name: 'httpx' }

function setup() {
  const onCreated = vi.fn()
  const api = mockApi({
    'GET /auth/me': PRINCIPAL,
    'POST /repos': () => json(CREATED, 201),
  })
  renderApp(<RepoNewDialog open onClose={() => {}} onCreated={onCreated} />)
  return { ...api, onCreated }
}

async function postedBody(calls: ReturnType<typeof mockApi>['calls']): Promise<Record<string, unknown>> {
  await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/repos')).toBe(true))
  const call = calls.find((c) => c.method === 'POST' && c.path === '/repos')!
  return JSON.parse(String(call.init?.body)) as Record<string, unknown>
}

describe('RepoNewDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('parseScopeList splits and trims', () => {
    expect(parseScopeList(' tests/, tests/acceptance/ ,, ')).toEqual(['tests/', 'tests/acceptance/'])
    expect(parseScopeList('')).toEqual([])
  })

  it('a preset fills the layout, runner options and belt scope; the body carries them', async () => {
    const user = userEvent.setup()
    const { calls, onCreated } = setup()
    await user.type(screen.getByLabelText(/^Name/), 'httpx')
    await user.selectOptions(screen.getByLabelText(/^Preset/), 'python-src-layout')
    expect(screen.getByLabelText(/^Language/)).toHaveValue('python')
    expect(screen.getByLabelText(/^Runner$/)).toHaveValue('pytest')
    expect(screen.getByLabelText(/^Source prefix/)).toHaveValue('src/')
    expect(screen.getByLabelText(/^Test prefix/)).toHaveValue('tests/')
    expect(screen.getByLabelText(/^Extension/)).toHaveValue('.py')
    expect(screen.getByLabelText(/^Belt scope/)).toHaveValue('AFFECTED_DIRS')
    expect(screen.getByLabelText(/Runner options/)).toHaveValue('{\n  "pythonpath_suffix": "/src",\n  "pip": [\n    "pytest"\n  ]\n}')
    await user.type(screen.getByLabelText(/^Git URL/), 'https://github.com/encode/httpx.git')
    await user.type(screen.getByLabelText(/^Probe scope/), 'tests/test_status.py')
    const submit = screen.getByRole('button', { name: 'Add repo' })
    expect(submit).toBeEnabled()
    await user.click(submit)
    const body = await postedBody(calls)
    expect(body).toEqual({
      name: 'httpx',
      language: 'python',
      url: 'https://github.com/encode/httpx.git',
      runner: 'pytest',
      src_prefix: 'src/',
      test_prefix: 'tests/',
      ext: '.py',
      belt_scope: 'AFFECTED_DIRS',
      probe: 'tests/test_status.py',
      runner_opts: { pythonpath_suffix: '/src', pip: ['pytest'] },
    })
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('httpx'))
  })

  it('refuses invalid runner-options JSON and a non-object, then recovers', async () => {
    const user = userEvent.setup()
    setup()
    await user.type(screen.getByLabelText(/^Name/), 'x')
    await user.type(screen.getByLabelText(/^Git URL/), 'https://github.com/o/r')
    const editor = screen.getByLabelText(/Runner options/)
    await user.type(editor, '{{"pip": ')
    expect(editor).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText(/Not valid JSON/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeDisabled()
    await user.clear(editor)
    await user.type(editor, '[[1, 2]')
    expect(screen.getByText(/Must be a JSON object/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeDisabled()
    await user.clear(editor)
    await user.type(editor, '{{"maven_flags": [["-pl", "gson"]}')
    expect(editor).not.toHaveAttribute('aria-invalid')
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeEnabled()
  })

  it('rejects a local path or http:// as a git URL but accepts it as a clone path', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByLabelText(/^Name/), 'x')
    const url = screen.getByLabelText(/^Git URL/)
    await user.type(url, '/srv/repos/x')
    expect(url).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeDisabled()
    await user.clear(url)
    await user.type(url, 'http://github.com/o/r')
    expect(url).toHaveAttribute('aria-invalid', 'true')
    await user.clear(url)
    await user.type(url, 'git@github.com:o/r.git')
    expect(url).not.toHaveAttribute('aria-invalid')
    await user.clear(url)
    await user.type(url, 'file:///srv/remotes/r.git') // the server decides (dev switch); not blocked here
    expect(url).not.toHaveAttribute('aria-invalid')
    await user.selectOptions(screen.getByLabelText(/^Source$/), 'clone_path')
    const path = screen.getByLabelText(/^Clone path/)
    await user.clear(path)
    await user.type(path, '/srv/repos/x')
    expect(path).not.toHaveAttribute('aria-invalid')
    await user.click(screen.getByRole('button', { name: 'Add repo' }))
    const body = await postedBody(calls)
    expect(body).toEqual({ name: 'x', language: 'python', clone_path: '/srv/repos/x', belt_scope: 'TARGET_ONLY' })
  })

  it('an explicit belt-scope list must name at least one scope and is sent as a list', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByLabelText(/^Name/), 'x')
    await user.type(screen.getByLabelText(/^Git URL/), 'https://github.com/o/r')
    await user.selectOptions(screen.getByLabelText(/^Belt scope/), 'LIST')
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeDisabled()
    await user.type(screen.getByLabelText(/^Belt scopes/), 'tests/, tests/acceptance/')
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Add repo' }))
    const body = await postedBody(calls)
    expect(body.belt_scope).toEqual(['tests/', 'tests/acceptance/'])
  })

  it('the runner select is limited to the language; a runner the new language cannot run falls back to the default', async () => {
    const user = userEvent.setup()
    setup()
    const runner = screen.getByLabelText(/^Runner$/)
    expect(within(runner).getAllByRole('option').map((o) => o.getAttribute('value'))).toEqual(['', 'pytest'])
    await user.selectOptions(screen.getByLabelText(/^Language/), 'javascript')
    expect(within(runner).getAllByRole('option').map((o) => o.getAttribute('value'))).toEqual(['', 'node', 'vitest', 'jest', 'mocha'])
    await user.selectOptions(runner, 'jest')
    await user.selectOptions(screen.getByLabelText(/^Language/), 'go')
    expect(runner).toHaveValue('')
    expect(within(runner).getAllByRole('option').map((o) => o.getAttribute('value'))).toEqual(['', 'go'])
  })

  it('the runner options editor shares the config form: the Form view offers the runner’s own keys and the body carries them', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await user.type(screen.getByLabelText(/^Name/), 'x')
    await user.type(screen.getByLabelText(/^Git URL/), 'https://github.com/o/r')
    await user.selectOptions(screen.getByLabelText(/^Language/), 'javascript')
    await user.selectOptions(screen.getByLabelText(/^Runner$/), 'jest')
    await user.click(screen.getByTestId('runner-opts-mode-form'))
    expect(screen.getByLabelText(/^npm binary/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Python interpreter/)).not.toBeInTheDocument()
    await user.click(screen.getByTestId('runner-opt-extra_args-add'))
    await user.type(screen.getByLabelText('Extra arguments 1'), '--selectProjects')
    await user.click(screen.getByTestId('runner-opt-extra_args-add'))
    expect(screen.getByRole('button', { name: 'Add repo' })).toBeDisabled() // an empty row is refused, as the runner would pass '' to jest
    await user.type(screen.getByLabelText('Extra arguments 2'), 'unit')
    await user.click(screen.getByTestId('runner-opts-mode-json'))
    expect(screen.getByLabelText(/Runner options \(JSON\)/)).toHaveValue('{\n  "extra_args": [\n    "--selectProjects",\n    "unit"\n  ]\n}')
    await user.click(screen.getByRole('button', { name: 'Add repo' }))
    const body = await postedBody(calls)
    expect(body).toEqual({ name: 'x', language: 'javascript', url: 'https://github.com/o/r', runner: 'jest', belt_scope: 'TARGET_ONLY', runner_opts: { extra_args: ['--selectProjects', 'unit'] } })
  })

  it('renders the server error envelope on a 422', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'POST /repos': () => json({ error: { code: 'validation_error', message: "invalid repo config: url: clone url scheme 'file' is refused", detail: {} } }, 422),
    })
    renderApp(<RepoNewDialog open onClose={() => {}} />)
    await user.type(screen.getByLabelText(/^Name/), 'x')
    await user.selectOptions(screen.getByLabelText(/^Source$/), 'clone_path')
    await user.type(screen.getByLabelText(/^Clone path/), '/srv/x')
    await user.click(screen.getByRole('button', { name: 'Add repo' }))
    await waitFor(() => expect(screen.getByText(/scheme 'file' is refused/)).toBeInTheDocument())
  })
})
