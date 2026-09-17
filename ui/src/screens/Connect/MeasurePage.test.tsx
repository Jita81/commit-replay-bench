/**
 * MeasurePage — the spend is stated before the button; the run is what the button says.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the Measure page.
 * What it does: Pins that the estimate uses the repository's measured cost per attempt when
 *               it has one (30 attempts × $0.34 ±20 %), that the button names the upper
 *               amount, that picking 10 attempts and keeping worktrees changes the summary,
 *               that the POST carries `{kind: replay, mode: sighted, limit, retain}`, and
 *               that a viewer sees no button.
 * How:          `mockApi` + `renderApp` with `path` for `useParams`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
 * Works with:   ui/src/screens/Connect/MeasurePage.tsx
 * Tested by:    ui/src/screens/Connect/MeasurePage.test.tsx
 * Touch when:   the run request or the estimate changes.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PRINCIPAL, json, mockApi, renderApp } from '../../test/utils'
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
    expect(screen.getByRole('button', { name: 'Start the run and spend up to $12.24' })).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText(/10 attempts/))
    await userEvent.click(screen.getByLabelText('Keep worktrees for failed attempts'))
    expect(box).toHaveTextContent('worktrees kept until deleted')
    await userEvent.click(screen.getByRole('button', { name: 'Start the run and spend up to $4.08' }))
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
    expect(within(box).getByText('Starting a run needs the operator role.')).toBeInTheDocument()
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
    await userEvent.click(screen.getByRole('button', { name: 'Start the run and spend up to $2.86' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/runs')).toBe(true))
    expect(JSON.parse(String(calls.find((c) => c.method === 'POST')!.init?.body)).limit).toBe(7)
  })
})
