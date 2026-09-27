/**
 * MeasurePage — the spend is stated before the button; the run is what the button says.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Measure page.
 * What it does: Pins that the estimate uses the repository's measured cost per attempt when it has
 *               one (30 attempts × $0.34 ±20 %), that the button names the band as an estimate and
 *               the spend cap the request carries (F5b), which starts at the top of the estimate
 *               and follows it until the operator types one, that no amount above $0 disables the
 *               button, that a last replay the cap stopped is said with its reason and its run,
 *               that picking 10 attempts and keeping worktrees changes the summary, that the POST
 *               carries `{kind: replay, mode: sighted, limit, retain, max_cost_usd}`, that a viewer
 *               sees no button, that the kicker counts Home's 8 tasks and the back-link names the
 *               walk (J-HEL-7, J-ONR-13), that a repository with no gold-clean task points at stage
 *               3 of the walk, and that a replay already queued or running replaces the red button
 *               with a banner naming the run — never a second spend (J-ONR-4); and that every
 *               field, row and the button carry a hint, with the attempts radio opening on hover;
 *               and that the estimate reads the map's economics fold, so a known $0 is quoted as
 *               $0.00 over the attempts with a known cost, never dropped for the planning range
 *               (P-064).
 * How:          `mockApi` + `renderApp` with `path` for `useParams`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/screens/Connect/MeasurePage.tsx, ui/src/help/hints.ts (the copy the
 *               hover test expects), ui/src/help/hints-collector.ts (`unhinted`)
 * Tested by:    ui/src/screens/Connect/MeasurePage.test.tsx
 * Touch when:   the run request or the estimate changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unhinted } from '../../help/hints-collector'
import { PRINCIPAL, expectHintOpens, json, mockApi, renderApp } from '../../test/utils'
import { MeasurePage } from './MeasurePage'

const REPO = { name: 'cobra', language: 'go', runner: 'go', url: 'https://github.com/spf13/cobra', clone_path: '', probe: { status: 'ok', run_id: 'r', checked: 'x', detail: '' }, task_counts: { total: 36, standard: 30, hard: 6, gold_clean: 32, gold_failed: 4, unchecked: 0 }, last_run: null, created: '', updated: '', config: {} }
// the map's own economics fold (F35): the spend estimate reads its cost per attempt over the KNOWN count
const est = (n: number, value: number | null, reason = '') => ({ n, value, ci_low: null, ci_high: null, method: 'Student-t 95% on the known rows (n-1 df), lower bound floored at 0', reason })
const econ = (n_attempts: number, cost_known: number, value: number | null, reason = '') => ({
  n_attempts, n_clean: n_attempts, cost_known, cost_known_clean: cost_known, latency_known: n_attempts, latency_known_clean: n_attempts,
  apparatus_versions: ['2.2'], posture_classes: [], checks_arms: ['off'], pooled: false, pooled_reason: '',
  cost_per_attempt: est(cost_known, value, reason), cost_per_clean: est(cost_known, value, reason), latency_per_attempt: est(n_attempts, 200),
})
const NONE_KNOWN = 'no attempt recorded a known cost'
const MAP = { repo: 'cobra', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [{ capability_class: 'bug.fix', size: 'XS', n: 22, clean: 22, point: 1, ci_low: 0.85, ci_high: 1, false_q1: 0, route: 'deliver', reason: '', cost_usd_mean: 0.34, latency_s_mean: 200, verification_tier: 'automated-pass', apparatus_versions: ['2.2'] }], summary: { trusted_autonomy_coverage: 1, total_cells: 1, measured_cells: 1, deliver_cells: 1, n_total: 22, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' }, economics: econ(22, 22, 0.34) }
const EMPTY_MAP = { ...MAP, cells: [], economics: econ(0, 0, null, NONE_KNOWN) }

describe('MeasurePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('states the spend from the measured mean and posts what the button says', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': REPO,
      'GET /capability-map': MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: 'configured: claude_code_cli', data: { anthropic: false, claude_code_cli: true } }] },
      'POST /runs': () => json({ id: 'run-1', repo: 'cobra', kind: 'replay', status: 'queued' }, 201),
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    await waitFor(() => expect(screen.getByTestId('before-you-start')).toHaveTextContent("this repository's measured mean"))
    const box = screen.getByTestId('before-you-start')
    expect(box).toHaveTextContent('$8.16 to $12.24 for 30 attempts, at about $0.34 each')
    expect(box).toHaveTextContent('sealed (docker) — countable as evidence')
    expect(box).toHaveTextContent('Nothing retained — grades and hashes only')
    // the button names the estimate AND the cap the request carries (F5b): the cap starts at
    // the top of the estimate, rounded up to the dollar
    expect(screen.getByRole('button', { name: 'Start the run — estimated $8.16 to $12.24, stops at $13.00' })).toBeInTheDocument()
    expect(screen.getByLabelText('Stop the run at $')).toHaveValue(13)
    expect(box).toHaveTextContent('$13.00 for the whole run. Before each attempt the run counts what it has spent plus what that attempt could cost, and stops if the sum would pass $13.00')
    expect(box).not.toHaveTextContent('No spend cap')
    expect(within(box).getByRole('link', { name: 'Measure: the money step' })).toHaveAttribute('href', '/help/docs/ONBOARDING-A-REPO#step-4--measure-operator-the-money-step')
    // the kicker counts Home's eight tasks; the back-link names the walk
    expect(screen.getByText('Journey · 1 of 4 · Connection · task 5 of 8 · this step spends money')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the walk for cobra' })).toHaveAttribute('href', '/connect/cobra')
    await userEvent.click(screen.getByLabelText(/10 attempts/))
    await userEvent.click(screen.getByLabelText('Keep worktrees for failed attempts'))
    expect(box).toHaveTextContent('worktrees kept until deleted')
    // the cap follows the estimate until the operator types one
    await userEvent.click(screen.getByRole('button', { name: 'Start the run — estimated $2.72 to $4.08, stops at $5.00' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ repo: 'cobra', kind: 'replay', mode: 'sighted', builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, limit: 10, retain: { worktrees: true, transcripts: false }, max_cost_usd: 5 })
    expect(box).toHaveTextContent('the operator’s own CLI login (development and evaluation only)')
  })

  it('quotes a known $0 as $0.00 over the attempts with a known cost, never the planning range (P-064)', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': REPO,
      // every attempt with a known cost cost $0 (a fixture, a metered subscription); two of 22 carry no price
      'GET /capability-map': { ...MAP, cells: [{ ...MAP.cells[0]!, cost_usd_mean: 0 }], economics: econ(22, 20, 0) },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    const box = await screen.findByTestId('before-you-start')
    await waitFor(() => expect(box).toHaveTextContent('$0.00 to $0.00 for 30 attempts, at about $0.00 each'))
    expect(box).toHaveTextContent("this repository's measured mean over n=20 attempts with a known cost at apparatus 2.2")
    expect(box).not.toHaveTextContent('a planning range, not a measured interval')
  })

  it('attempts with no known cost fall back to the range and say why, never n = 0', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': REPO,
      'GET /capability-map': { ...MAP, economics: econ(22, 0, null, NONE_KNOWN) },
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    const box = await screen.findByTestId('before-you-start')
    await waitFor(() => expect(box).toHaveTextContent('this repository has no measured mean yet (no attempt recorded a known cost)'))
  })

  it('a viewer sees the page but no button; no measured mean falls back to the documented range', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/cobra': REPO,
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'degraded', probes: [{ name: 'sandbox', status: 'degraded', detail: '', data: { executor: 'local' } }, { name: 'builders', status: 'degraded', detail: 'configured: none', data: { anthropic: false, claude_code_cli: false } }] },
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    await waitFor(() => expect(screen.getByTestId('before-you-start')).toHaveTextContent('a planning range, not a measured interval'))
    const box = screen.getByTestId('before-you-start')
    expect(box).toHaveTextContent('$6.00 to $18.00 for 30 attempts')
    await waitFor(() => expect(box).toHaveTextContent('local executor — a development reading, not evidence'))
    expect(screen.queryByRole('button', { name: /Start the run/ })).not.toBeInTheDocument()
    // the role is said under the title, and the choices are read-only lists, not live controls
    expect(screen.getByTestId('measure-role-note')).toHaveTextContent('Starting a run needs the operator role.')
    expect(screen.queryByRole('radio')).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getByText('30 attempts')).toBeInTheDocument()
    expect(screen.getByText('the first useful picture (the default)')).toBeInTheDocument()
    expect(box).toHaveTextContent('No builder is configured on this deployment')
  })

  it('a repository with fewer gold-clean tasks than the radio says prices, names and posts the capped count', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': { ...REPO, task_counts: { ...REPO.task_counts, gold_clean: 7 } },
      'GET /capability-map': MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'skipped', detail: 'not probed here', data: { executor: 'docker', role: 'api' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
      'POST /runs': () => json({ id: 'run-2', repo: 'cobra', kind: 'replay', status: 'queued' }, 201),
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    await waitFor(() => expect(screen.getByTestId('before-you-start')).toHaveTextContent('for 7 attempts'))
    const box = screen.getByTestId('before-you-start')
    // 7 × $0.34 × 0.8 … × 1.2 — the same 7 the request carries
    expect(box).toHaveTextContent('$1.90 to $2.86 for 7 attempts')
    expect(screen.getByText(/cobra has 7 gold-clean tasks, so this run makes 7 attempts/)).toBeInTheDocument()
    // an API-role process that skipped the sandbox probe does not claim "sealed"
    expect(box).toHaveTextContent('the worker’s own health check decides')
    expect(box).not.toHaveTextContent('countable as evidence')
    await userEvent.click(screen.getByRole('button', { name: 'Start the run — estimated $1.90 to $2.86, stops at $3.00' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body)).limit).toBe(7)
  })

  it('the operator names the spend cap the run is sent with; no amount above $0 disables the button', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': REPO,
      'GET /capability-map': MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
      'POST /runs': () => json({ id: 'run-3', repo: 'cobra', kind: 'replay', status: 'queued' }, 201),
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    const field = await screen.findByLabelText('Stop the run at $')
    await waitFor(() => expect(field).toHaveValue(13))
    await userEvent.clear(field)
    expect(screen.getByTestId('cap-invalid')).toHaveTextContent('Enter an amount above $0')
    expect(screen.getByRole('button', { name: /Start the run/ })).toBeDisabled()
    expect(screen.getByTestId('before-you-start')).toHaveTextContent('No valid cap yet')
    await userEvent.type(field, '9.5')
    await userEvent.click(screen.getByRole('button', { name: 'Start the run — estimated $8.16 to $12.24, stops at $9.50' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body)).max_cost_usd).toBe(9.5)
  })

  it('a last replay that stopped itself at its spend cap is said with its reason and its run (F5b)', async () => {
    const reason = 'spend cap: $9.20 of $10.00 spent; the next attempt could cost an amount no cap of its own bounds, counted at the dearest attempt this run has made, $0.90, which would pass the cap, so the run stopped before it'
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': { ...REPO, last_run: { id: 'run-9', kind: 'replay', status: 'failed', finished: '2026-09-27T10:00:00Z' } },
      'GET /capability-map': MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
      'GET /runs/run-9': { id: 'run-9', repo: 'cobra', kind: 'replay', status: 'failed', mode: 'sighted', builder: 'claude_code', model: 'claude-sonnet-5', provider: '', ladder: [], max_cost_usd: 10, executor: 'docker', timeout: 600, pool: '', limit: 30, task_ids: [], builder_config: {}, actor: 'op', created: '2026-09-27T09:00:00Z', started: '2026-09-27T09:00:20Z', finished: '2026-09-27T10:00:00Z', cancel_requested: false, error: reason, cost_usd: 9.2, apparatus_version: '2.3', counts: { tasks: 11, clean: 8, disqualified: 0, errors: 0, first_pass_clean: 8, rows: 11, stopped_reason: reason, stopped_code: 'spend_cap' }, progress: { done: 11, total: 30, current_task_id: null } },
    })
    const { container } = renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    const banner = await screen.findByRole('region', { name: 'Stopped at its spend cap' })
    await waitFor(() => expect(banner).toHaveTextContent('The last measurement of cobra stopped at its spend cap of $10.00: $9.20 spent over 11 attempts. The reason below says whether it stopped before an attempt that could have passed the cap, or after one with no cost cap of its own passed it.'))
    expect(screen.getByTestId('measure-cap-stop-reason')).toHaveTextContent(reason)
    expect(within(banner).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/runs/run-9')
    expect(container.querySelector('[data-hint="banner.measure.spend_cap_stop"]')).not.toBeNull()
    // a stop is not a run in flight: the page still offers the next measurement
    expect(screen.getByRole('button', { name: /Start the run/ })).toBeEnabled()
  })

  it('a repository with no gold-clean task points at stage 3 of the walk and disables the button', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': { ...REPO, task_counts: { ...REPO.task_counts, gold_clean: 0 } },
      'GET /capability-map': EMPTY_MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: '', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    await waitFor(() => expect(screen.getByTestId('no-gold')).toHaveTextContent('cobra has no gold-clean task to replay, so a run would make no attempt. Mine the repository first (stage 3 of the walk) and check its gold status under Configuration.'))
    expect(within(screen.getByTestId('no-gold')).getByRole('link', { name: 'Configuration' })).toHaveAttribute('href', '/repos/cobra')
    expect(screen.getByRole('button', { name: /Start the run/ })).toBeDisabled()
  })

  it('a replay already queued or running replaces the red button with a banner naming the run (J-ONR-4)', async () => {
    const { calls } = mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': { ...REPO, last_run: { id: 'run-1', kind: 'replay', status: 'running', finished: null } },
      'GET /capability-map': MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: '', data: { anthropic: true } }] },
      'GET /runs/run-1': { id: 'run-1', repo: 'cobra', kind: 'replay', status: 'running', mode: 'sighted', builder: 'claude_code', model: 'claude-sonnet-5', provider: '', ladder: [], executor: 'docker', timeout: 600, pool: '', limit: 10, task_ids: [], builder_config: {}, actor: 'op', created: '2026-09-19T10:00:00Z', started: '2026-09-19T10:00:20Z', finished: null, cancel_requested: false, error: '', cost_usd: 1.02, apparatus_version: '2.2', counts: { tasks: 3, clean: 3, disqualified: 0, errors: 0, first_pass_clean: 3, rows: 3 }, progress: { done: 3, total: 10, current_task_id: 't4' } },
    })
    renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    const banner = await screen.findByRole('region', { name: 'Important' })
    await waitFor(() => expect(banner).toHaveTextContent(/A measurement is already running for cobra\. Started \d{2}:\d{2}; 3 of 10 attempts made; \$1\.02 spent so far\./))
    expect(banner).toHaveTextContent('Start another run only when this one has finished or been cancelled.')
    expect(within(banner).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/runs/run-1')
    expect(within(banner).getByRole('link', { name: 'Back to the walk' })).toHaveAttribute('href', '/connect/cobra')
    // no red button, no estimate: nothing on the page can queue a second spend
    expect(screen.queryByRole('button', { name: /Start the run/ })).not.toBeInTheDocument()
    expect(screen.getByTestId('before-you-start')).not.toHaveTextContent('Estimated cost')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('every radio, checkbox, summary row, link and the red button carry a hint; the attempts radio opens on hover with the registry copy', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': { ...REPO, task_counts: { ...REPO.task_counts, gold_clean: 12 } },
      'GET /capability-map': MAP,
      'GET /health': { status: 'ok', probes: [{ name: 'sandbox', status: 'ok', detail: 'docker 28', data: { executor: 'docker' } }, { name: 'builders', status: 'ok', detail: 'configured: claude_code_cli', data: { anthropic: false, claude_code_cli: true } }] },
    })
    const { container } = renderApp(<MeasurePage />, { route: '/connect/cobra/measure', path: '/connect/:name/measure' })
    await waitFor(() => expect(screen.getByRole('button', { name: /Start the run/ })).toHaveAttribute('data-hint', 'button.measure.start'))
    expect(unhinted(container)).toEqual([])
    for (const id of ['link.measure.back', 'nav.measure.kicker', 'field.measure.spend_cap', 'field.measure.retain_worktrees', 'field.measure.retain_transcripts', 'stat.measure.gold_cap', 'stat.measure.estimate', 'summary.measure.builder', 'link.measure.every_knob', 'summary.measure.budget_cap', 'summary.measure.retention', 'summary.measure.posture']) {
      expect(container.querySelector(`[data-hint="${id}"]`), id).not.toBeNull()
    }
    // the radio's label is the trigger: the input keeps the tab stop, and focusing it opens the same bubble
    const radio = screen.getByLabelText(/10 attempts/)
    const label = radio.closest('[data-hint="field.measure.attempts"]')!
    expect(label).not.toHaveAttribute('tabindex')
    await expectHintOpens(label, 'field.measure.attempts')
    expect(screen.getByRole('link', { name: /Every knob/ })).toHaveAttribute('href', '/runs')
  })
})
