/**
 * MeasurePage — the spend is stated before the button; the run is what the button says.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Measure page.
 * What it does: Pins that the estimate uses the repository's measured cost per attempt when
 *               it has one (30 attempts × $0.34 ±20 %), that the button names the band as an
 *               estimate — never a cap the request does not carry (F5b) — and the Budget row
 *               says there is no spend cap yet, that picking 10 attempts and keeping
 *               worktrees changes the summary, that the POST carries `{kind: replay, mode:
 *               sighted, limit, retain}`, that a viewer sees no button, that the kicker counts
 *               Home's 8 tasks and the back-link names the walk (J-HEL-7, J-ONR-13), that a
 *               repository with no gold-clean task points at stage 3 of the walk, and that a
 *               replay already queued or running replaces the red button with a banner naming
 *               the run — never a second spend (J-ONR-4); and that every field, row and the
 *               button carry a hint, with the attempts radio opening on hover.
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
const MAP = { repo: 'cobra', by: ['capability_class', 'size'], classes: [], sizes: [], languages: [], models: [], cells: [{ capability_class: 'bug.fix', size: 'XS', n: 22, clean: 22, point: 1, ci_low: 0.85, ci_high: 1, false_q1: 0, route: 'deliver', reason: '', cost_usd_mean: 0.34, latency_s_mean: 200, verification_tier: 'automated-pass', apparatus_versions: ['2.2'] }], summary: { trusted_autonomy_coverage: 1, total_cells: 1, measured_cells: 1, deliver_cells: 1, n_total: 22, false_q1_total: 0, apparatus_versions: ['2.2'] }, policy: { min_n: 10, min_point: 0.9, min_ci_low: 0.8, min_oracle_strength: 0.8, granularize_sizes: ['XL'], version: 'routing.v1' } }

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
    // the button names an estimate, not a cap: the request carries none (F5b)
    expect(screen.getByRole('button', { name: 'Start the run — estimated $8.16 to $12.24' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /spend up to/ })).not.toBeInTheDocument()
    expect(box).toHaveTextContent('No spend cap on this run yet. Each attempt is capped on turns, tool calls and wall clock; you can cancel at any point and attempts already made are still charged.')
    expect(within(box).getByRole('link', { name: 'Measure: the money step' })).toHaveAttribute('href', '/help/docs/ONBOARDING-A-REPO#step-4--measure-operator-the-money-step')
    // the kicker counts Home's eight tasks; the back-link names the walk
    expect(screen.getByText('Journey · 1 of 4 · Connection · task 5 of 8 · this step spends money')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the walk for cobra' })).toHaveAttribute('href', '/connect/cobra')
    await userEvent.click(screen.getByLabelText(/10 attempts/))
    await userEvent.click(screen.getByLabelText('Keep worktrees for failed attempts'))
    expect(box).toHaveTextContent('worktrees kept until deleted')
    await userEvent.click(screen.getByRole('button', { name: 'Start the run — estimated $2.72 to $4.08' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(String(post.init?.body))).toEqual({ repo: 'cobra', kind: 'replay', mode: 'sighted', builder: 'claude_code', model: 'claude-sonnet-5', builder_config: { auth: 'cli' }, limit: 10, retain: { worktrees: true, transcripts: false } })
    expect(box).toHaveTextContent('the operator’s own CLI login (development and evaluation only)')
  })

  it('a viewer sees the page but no button; no measured mean falls back to the documented range', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'viewer' },
      'GET /repos/cobra': REPO,
      'GET /capability-map': { ...MAP, cells: [] },
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
    await userEvent.click(screen.getByRole('button', { name: 'Start the run — estimated $1.90 to $2.86' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body)).limit).toBe(7)
  })

  it('a repository with no gold-clean task points at stage 3 of the walk and disables the button', async () => {
    mockApi({
      'GET /auth/me': { ...PRINCIPAL, role: 'operator' },
      'GET /repos/cobra': { ...REPO, task_counts: { ...REPO.task_counts, gold_clean: 0 } },
      'GET /capability-map': { ...MAP, cells: [] },
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
    for (const id of ['link.measure.back', 'nav.measure.kicker', 'field.measure.retain_worktrees', 'field.measure.retain_transcripts', 'stat.measure.gold_cap', 'stat.measure.estimate', 'summary.measure.builder', 'link.measure.every_knob', 'summary.measure.budget_cap', 'summary.measure.retention', 'summary.measure.posture']) {
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
