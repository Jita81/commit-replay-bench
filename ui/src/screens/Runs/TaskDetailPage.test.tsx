/**
 * ui/src/screens/Runs/TaskDetailPage.tsx — a factory item is named as one.
 *
 * Navigation
 * ----------
 * What it is:   Tests for the task detail screen against a mocked API.
 * What it does: Pins that a task the factory built (`labels.process === 'factory'`) is
 *               introduced as one factory item with its backlog id and told where its id
 *               comes from (the authored test's sha), and that a replayed commit keeps the
 *               commit wording (J-FAC-18).
 * How:          `renderApp` at `/tasks/:repo/:taskId` with `mockApi` serving one task and
 *               no reviews; assertions on the spec card's copy.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Runs/TaskDetailPage.tsx (the code under test),
 *               ui/src/api/types.ts (`TaskSpec.labels`), src/crb/factory/build.py (the
 *               labels a factory task carries), ui/src/test/utils.tsx
 * Tested by:    ui/src/screens/Runs/TaskDetailPage.test.tsx
 * Touch when:   the factory writes a different label for its items, or the task page's
 *               provenance sentence changes.
 */
import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TaskDetail } from '../../api/types'
import { PRINCIPAL, mockApi, renderApp } from '../../test/utils'
import { TaskDetailPage } from './TaskDetailPage'

const TASK_ID = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0'

function task(labels: Record<string, string>): TaskDetail {
  return {
    spec: {
      task_id: TASK_ID,
      repo: 'alpha',
      subject: 'Add a divide helper',
      authored: '2026-09-13T09:00:00Z',
      test_files: ['tests/test_divide.py'],
      src_files: ['src/divide.py'],
      target_tests: ['tests/test_divide.py::test_divide'],
      belt_scope: ['tests'],
      pool: 'standard',
      src_churn: 12,
      size: 'S',
      capability_class: 'feature.add',
      language: 'python',
      baseline_failing: [],
      red_checked: true,
      gold_clean: null,
      gold_note: '',
      labels,
    },
    grades: [],
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TaskDetailPage', () => {
  it('a factory item says so, with its backlog id and where the task id comes from (J-FAC-18)', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [], total: 0, limit: 200, offset: 0 },
      [`GET /tasks/alpha/${TASK_ID}`]: task({ item_id: 'I-2', process: 'factory', red_proof: 'deadbeef' }),
      'GET /reviews': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<TaskDetailPage />, { route: `/tasks/alpha/${TASK_ID}`, path: '/tasks/:repo/:taskId' })
    expect(await screen.findByText('Add a divide helper')).toBeInTheDocument()
    expect(screen.getByText(/One factory item \(I-2\)/)).toBeInTheDocument()
    expect(screen.getByText(/the id is the authored test's sha/)).toBeInTheDocument()
    expect(screen.getByText('Factory item')).toBeInTheDocument()
    expect(screen.queryByText('Commit')).toBeNull()
    // the header's purpose — the first sentence read — agrees with the card: no "replayable commit"
    expect(screen.getByText(/^One factory item the loop built: its authored test/)).toBeInTheDocument()
    expect(screen.queryByText(/replayable commit/)).toBeNull()
  })

  it('a replayed commit keeps the commit wording', async () => {
    mockApi({
      'GET /auth/me': PRINCIPAL,
      'GET /repos': { items: [], total: 0, limit: 200, offset: 0 },
      [`GET /tasks/alpha/${TASK_ID}`]: task({}),
      'GET /reviews': { items: [], total: 0, limit: 200, offset: 0 },
    })
    renderApp(<TaskDetailPage />, { route: `/tasks/alpha/${TASK_ID}`, path: '/tasks/:repo/:taskId' })
    expect(await screen.findByText('Add a divide helper')).toBeInTheDocument()
    expect(screen.getByText('Commit')).toBeInTheDocument()
    // the hint bubbles are always in the DOM (hidden): only the page's own copy is asserted
    expect(screen.queryByText(/factory item/i, { ignore: '[role="tooltip"]' })).toBeNull()
    expect(screen.getByText(/^One replayable commit: its spec/)).toBeInTheDocument()
  })
})
