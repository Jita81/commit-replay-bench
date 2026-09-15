/**
 * ui/src/screens/Repos/RepoConfigTab.tsx — only the changed fields are sent, validation mirrors the
 * API, the probe result is shown inline.
 *
 * Navigation
 * ----------
 * What it is:   Screen tests for the Configuration tab against a mocked API.
 * What it does: Pins that every stored field renders and Save stays disabled until something
 *               changes; that a viewer gets a read-only form with no actions; that switching
 *               the language limits the runner and swaps the options sub-form; that a save
 *               sends ONLY the changed fields (asserted on the PUT body), shows the toast and
 *               adds the diff event to the trail; that raw JSON round-trips with the form and
 *               a parse error blocks saving; that validation speaks the API's words; that a
 *               422 envelope renders; and that a probe after a save is followed to green or
 *               red with the run's reason.
 * How:          `mockApi` with the `REPO` fixture, `userEvent` interactions, assertions on
 *               the `repo-config-*` test ids and the recorded request bodies.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/RepoConfigTab.tsx (the code under test),
 *               ui/src/screens/Repos/repoConfigModel.test.ts (`REPO`), ui/src/test/utils.tsx
 *               (`mockApi`, `renderApp`, `envelope`, `json`)
 * Tested by:    ui/src/screens/Repos/RepoConfigTab.test.tsx
 * Touch when:   a field, a validation message or the audit payload changes — extend the
 *               matching case.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Principal, RepoDetail, Run, StepEvent } from '../../api/types'
import { PRINCIPAL, envelope, json, mockApi, renderApp } from '../../test/utils'
import { RepoConfigTab } from './RepoConfigTab'
import { REPO } from './repoConfigModel.test'

const OPERATOR: Principal = { ...PRINCIPAL, role: 'operator' }
const VIEWER: Principal = { ...PRINCIPAL, role: 'viewer' }

function event(seq: number, action: string, payload: Record<string, unknown>): StepEvent {
  return {
    event_id: `e${seq}`.padEnd(32, '0'),
    seq,
    timestamp: `2026-09-13T10:0${seq}:00+00:00`,
    trace_id: 't'.repeat(32),
    step_id: '',
    parent_step_id: '',
    stage: 'system',
    action,
    status: 'ok',
    actor: 'u1',
    repo: REPO.name,
    task_id: '',
    input_ref: '',
    output_ref: '',
    error_code: '',
    error_message: '',
    duration_ms: null,
    cost_usd: null,
    payload,
  }
}

const RUN_ID = 'b'.repeat(32)

function setup(opts: { me?: Principal; repo?: RepoDetail; putStatus?: number } = {}) {
  const repo = opts.repo ?? REPO
  let stored = repo
  const events: StepEvent[] = [event(1, 'repo.created', { config: repo.config })]
  const api = mockApi({
    'GET /auth/me': opts.me ?? OPERATOR,
    [`GET /repos/${repo.name}`]: () => json(stored),
    [`GET /repos/${repo.name}/events`]: () => json({ items: [...events].reverse(), total: events.length, limit: 50, offset: 0 }),
    [`PUT /repos/${repo.name}`]: (_url: string, init: RequestInit | undefined) => {
      if (opts.putStatus === 422) return envelope(422, 'validation_error', "invalid repo config: test_mode='suffix' requires test_suffix")
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      const cfg = { ...stored.config, ...body } as RepoDetail['config']
      stored = { ...stored, config: cfg, updated: `2026-09-13T11:00:0${events.length}+00:00` }
      events.push(event(events.length + 1, 'repo.updated', { fields: Object.keys(body).sort(), diff: Object.fromEntries(Object.keys(body).map((k) => [k, { from: (repo.config as unknown as Record<string, unknown>)[k], to: body[k] }])) }))
      return json(stored)
    },
    [`POST /repos/${repo.name}/probe`]: () => json({ id: RUN_ID, repo: repo.name, kind: 'probe', status: 'queued' } as Partial<Run>, 201),
    [`GET /runs/${RUN_ID}`]: () => json({ id: RUN_ID, repo: repo.name, kind: 'probe', status: 'succeeded', error: '' } as Partial<Run>),
  })
  const utils = renderApp(<RepoConfigTab repo={repo} />)
  return { ...api, ...utils }
}

async function putBody(calls: ReturnType<typeof mockApi>['calls']): Promise<Record<string, unknown>> {
  await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
  const call = calls.find((c) => c.method === 'PUT')!
  return JSON.parse(String(call.init?.body)) as Record<string, unknown>
}

describe('RepoConfigTab', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders every field from the stored config; Save is disabled until something changes', async () => {
    setup()
    await screen.findByTestId('repo-config-save')
    expect(screen.getByLabelText(/^Language/)).toHaveValue('python')
    expect(screen.getByTestId('repo-config-runner')).toHaveValue('pytest')
    expect(screen.getByLabelText(/^Clone path/)).toHaveValue('/srv/home/repos/walk-pyrepo')
    expect(screen.getByLabelText(/^Source prefix/)).toHaveValue('src/')
    expect(screen.getByLabelText(/^Test prefix/)).toHaveValue('tests/')
    expect(screen.getByLabelText(/^Extensions/)).toHaveValue('.py')
    expect(screen.getByTestId('repo-config-belt-AFFECTED_DIRS')).toBeChecked()
    expect(screen.getByLabelText(/^Probe scope/)).toHaveValue('tests/test_calc.py')
    expect(screen.getByLabelText(/^History depth/)).toHaveValue('50')
    // the pytest sub-form shows the pytest keys, and only those
    expect(screen.getByLabelText(/^Python interpreter/)).toHaveValue('/opt/py/bin/python')
    expect(screen.getByLabelText(/^PYTHONPATH suffix/)).toHaveValue('/src')
    expect(screen.queryByLabelText(/^Extra arguments/)).not.toBeInTheDocument()
    expect(screen.getByTestId('repo-config-save')).toBeDisabled()
    expect(screen.getByTestId('repo-config-probe-run')).toBeEnabled()
    // the audit trail lists the creation event
    await waitFor(() => expect(screen.getAllByTestId('repo-config-audit-event')).toHaveLength(1))
    expect(screen.getByTestId('repo-config-audit-event')).toHaveAttribute('data-action', 'repo.created')
  })

  it('a viewer sees a read-only form and no actions', async () => {
    setup({ me: VIEWER })
    await screen.findByTestId('repo-config-readonly')
    expect(screen.getByLabelText(/^Language/)).toBeDisabled()
    expect(screen.getByLabelText(/^Probe scope/)).toBeDisabled()
    expect(screen.queryByTestId('repo-config-save')).not.toBeInTheDocument()
    expect(screen.queryByTestId('repo-config-probe-run')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add item/ })).not.toBeInTheDocument()
  })

  it('switching the language limits the runner and swaps the runner sub-form; extra_args rows land in runner_opts', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await screen.findByTestId('repo-config-save')
    await user.selectOptions(screen.getByLabelText(/^Language/), 'javascript')
    const runner = screen.getByTestId('repo-config-runner')
    expect(runner).toHaveValue('mocha') // the language default
    expect(within(runner).getAllByRole('option').map((o) => o.textContent)).toEqual(['node', 'vitest', 'jest', 'mocha'])
    await user.selectOptions(runner, 'jest')
    // jest keys only; the pytest-only keys are preserved but listed as unread
    expect(screen.getByLabelText(/^npm binary/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Python interpreter/)).not.toBeInTheDocument()
    const extra = screen.getByTestId('runner-opts-extra')
    expect(extra).toHaveTextContent('python')
    expect(extra).toHaveTextContent('pythonpath_suffix')
    await user.click(screen.getByTestId('runner-opt-extra_args-add'))
    await user.type(screen.getByLabelText('Extra arguments 1'), '--selectProjects')
    await user.click(screen.getByTestId('runner-opt-extra_args-add'))
    await user.type(screen.getByLabelText('Extra arguments 2'), 'unit')
    await user.click(screen.getByTestId('runner-opt-env-add'))
    await user.type(screen.getByLabelText('Environment variables name 1'), 'PATH')
    await user.type(screen.getByLabelText('Environment variables value 1'), '/opt/node@24/bin:/usr/bin')
    expect(screen.getByTestId('repo-config-pending')).toHaveTextContent('language, runner, runner_opts')
    await user.click(screen.getByTestId('repo-config-save'))
    const body = await putBody(calls)
    expect(body).toEqual({
      language: 'javascript',
      runner: 'jest',
      runner_opts: { pythonpath_suffix: '/src', python: '/opt/py/bin/python', extra_args: ['--selectProjects', 'unit'], env: { PATH: '/opt/node@24/bin:/usr/bin' } },
    })
  })

  it('sends ONLY the changed fields, shows the toast, and the audit trail gains the diff event', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await screen.findByTestId('repo-config-save')
    await user.click(screen.getByTestId('repo-config-belt-LIST'))
    expect(screen.getByTestId('repo-config-save')).toBeDisabled() // an empty list is not a scope
    expect(screen.getByRole('alert')).toHaveTextContent(/list at least one scope/)
    await user.click(screen.getByTestId('repo-config-belt-list-add'))
    await user.type(screen.getByLabelText('Belt scope 1'), 'tests/')
    await user.click(screen.getByTestId('repo-config-belt-list-add'))
    await user.type(screen.getByLabelText('Belt scope 2'), 'tests/acceptance/')
    await user.clear(screen.getByLabelText(/^Probe scope/))
    await user.type(screen.getByLabelText(/^Probe scope/), 'tests/test_calc.py tests/test_ops.py')
    await user.click(screen.getByTestId('repo-config-save'))
    expect(await putBody(calls)).toEqual({ belt_scope: ['tests/', 'tests/acceptance/'], probe: 'tests/test_calc.py tests/test_ops.py' })
    const toast = await screen.findByTestId('repo-config-toast')
    expect(toast).toHaveTextContent('Saved belt_scope, probe')
    expect(screen.getByTestId('repo-config-save')).toBeDisabled() // the form now matches the store
    await waitFor(() => expect(screen.getAllByTestId('repo-config-audit-event')).toHaveLength(2))
    const [newest] = screen.getAllByTestId('repo-config-audit-event')
    expect(newest).toHaveAttribute('data-action', 'repo.updated')
    expect(within(newest!).getByTestId('repo-config-audit-fields')).toHaveTextContent('belt_scope')
    expect(within(newest!).getByTestId('repo-config-audit-fields')).toHaveTextContent('probe')
  })

  it('raw JSON round-trips: edits in JSON mode show up in the form and vice versa; a parse error blocks saving', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await screen.findByTestId('repo-config-save')
    await user.click(screen.getByTestId('runner-opts-mode-json'))
    const editor = screen.getByTestId('runner-opts-json')
    expect(editor).toHaveValue('{\n  "pythonpath_suffix": "/src",\n  "python": "/opt/py/bin/python"\n}')
    await user.clear(editor)
    await user.type(editor, '{{"python": "/opt/py/bin/python", "pip": [["-e", ".[[test]"], "uninstall": [["walk"]}')
    expect(editor).not.toHaveAttribute('aria-invalid')
    await user.click(screen.getByTestId('runner-opts-mode-form'))
    expect(screen.getByLabelText(/^PYTHONPATH suffix/)).toHaveValue('')
    expect(screen.getByLabelText('pip install arguments 1')).toHaveValue('-e')
    expect(screen.getByLabelText('pip install arguments 2')).toHaveValue('.[test]')
    expect(screen.getByLabelText('Uninstall after install 1')).toHaveValue('walk')
    await user.type(screen.getByLabelText(/^PYTHONPATH suffix/), '/src')
    await user.click(screen.getByTestId('runner-opts-mode-json'))
    expect(JSON.parse(String((screen.getByTestId('runner-opts-json') as HTMLTextAreaElement).value))).toEqual({
      python: '/opt/py/bin/python',
      pip: ['-e', '.[test]'],
      uninstall: ['walk'],
      pythonpath_suffix: '/src',
    })
    await user.type(screen.getByTestId('runner-opts-json'), '{{')
    expect(screen.getByTestId('runner-opts-json')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByTestId('repo-config-save')).toBeDisabled()
    // the form view cannot be entered while the draft does not parse
    await user.click(screen.getByTestId('runner-opts-mode-form'))
    expect(screen.getByTestId('runner-opts-json')).toBeInTheDocument()
    await user.type(screen.getByTestId('runner-opts-json'), '{Backspace}')
    expect(screen.getByTestId('repo-config-save')).toBeEnabled()
    await user.click(screen.getByTestId('repo-config-save'))
    expect(await putBody(calls)).toEqual({ runner_opts: { python: '/opt/py/bin/python', pip: ['-e', '.[test]'], uninstall: ['walk'], pythonpath_suffix: '/src' } })
  })

  it("validation mirrors the API: suffix mode needs suffixes, a non-integer cap, a runner option the runner can't read", async () => {
    const user = userEvent.setup()
    setup()
    await screen.findByTestId('repo-config-save')
    await user.selectOptions(screen.getByLabelText(/^Test mode/), 'suffix')
    const suffix = screen.getByLabelText(/^Test suffixes/)
    expect(suffix).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText("test_mode='suffix' requires test_suffix")).toBeInTheDocument()
    expect(screen.getByTestId('repo-config-save')).toBeDisabled()
    await user.type(suffix, '.test.ts|.test.tsx|.snap')
    expect(screen.getByTestId('repo-config-save')).toBeEnabled()
    await user.type(screen.getByLabelText(/^Hard-pool target/), '2.5')
    expect(screen.getByText('Input should be a valid integer')).toBeInTheDocument()
    expect(screen.getByTestId('repo-config-save')).toBeDisabled()
    await user.clear(screen.getByLabelText(/^Hard-pool target/))
    await user.type(screen.getByLabelText(/^Test timeout/), '12x')
    expect(screen.getByTestId('repo-config-save')).toBeDisabled()
    await user.clear(screen.getByLabelText(/^Test timeout/))
    await user.type(screen.getByLabelText(/^Test timeout/), '1200')
    expect(screen.getByTestId('repo-config-save')).toBeEnabled()
    expect(screen.getByTestId('repo-config-pending')).toHaveTextContent('runner_opts, test_mode, test_suffix')
  })

  it('renders the server 422 envelope when the API refuses the config', async () => {
    const user = userEvent.setup()
    setup({ putStatus: 422 })
    await screen.findByTestId('repo-config-save')
    await user.type(screen.getByLabelText(/^Layer/), 'platform')
    await user.click(screen.getByTestId('repo-config-save'))
    await waitFor(() => expect(screen.getByTestId('error-state')).toHaveTextContent(/requires test_suffix/))
    expect(screen.getByLabelText(/^Layer/)).toHaveValue('platform') // edits survive a refusal
  })

  it('Run probe after a save enqueues the probe and reports the terminal result inline', async () => {
    const user = userEvent.setup()
    const { calls } = setup()
    await screen.findByTestId('repo-config-save')
    await user.type(screen.getByLabelText(/^Layer/), 'platform')
    expect(screen.getByTestId('repo-config-probe-run')).toBeDisabled() // unsaved edits: the probe runs the STORED config
    await user.click(screen.getByTestId('repo-config-save'))
    await screen.findByTestId('repo-config-toast')
    await user.click(screen.getByTestId('repo-config-toast-probe'))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === `/repos/${REPO.name}/probe`)).toBe(true))
    const result = await screen.findByTestId('repo-config-probe-result')
    await waitFor(() => expect(screen.getByTestId('repo-config-probe-result')).toHaveAttribute('data-outcome', 'green'))
    expect(result).toHaveTextContent('Probe green')
    expect(screen.getByTestId('repo-config-probe-reason')).toHaveTextContent('5 passed in 0.02s')
    expect(screen.getByRole('link', { name: /^run b{8}$/ })).toHaveAttribute('href', `/runs/${RUN_ID}`)
  })

  it('a failed probe is red with the run error as the reason', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me': OPERATOR,
      [`GET /repos/${REPO.name}/events`]: { items: [], total: 0, limit: 50, offset: 0 },
      [`POST /repos/${REPO.name}/probe`]: () => json({ id: RUN_ID, repo: REPO.name, kind: 'probe', status: 'queued' }, 201),
      [`GET /runs/${RUN_ID}`]: () => json({ id: RUN_ID, repo: REPO.name, kind: 'probe', status: 'failed', error: 'probe not green: rc=1' }),
    })
    renderApp(<RepoConfigTab repo={REPO} />)
    await screen.findByTestId('repo-config-save')
    await user.click(screen.getByTestId('repo-config-probe-run'))
    await waitFor(() => expect(screen.getByTestId('repo-config-probe-result')).toHaveAttribute('data-outcome', 'red'))
    expect(screen.getByTestId('repo-config-probe-reason')).toHaveTextContent('probe not green: rc=1')
    expect(screen.getByTestId('repo-config-audit')).toBeInTheDocument()
  })
})
