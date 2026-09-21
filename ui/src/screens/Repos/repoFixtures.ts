/**
 * Test fixtures for the Repos screens — a plain module, so no spec imports another spec.
 *
 * Navigation
 * ----------
 * What it is:   `REPO`, the one `RepoDetail` the repo-config model test and the screen tests
 *               (RepoDetail, RepoConfigTab) share.
 * What it does: Holds the fixture and nothing else: importing a `*.test.ts` file from another
 *               spec would register its `describe`/`it` blocks a second time while Vitest
 *               collects the importer, so the fixture lives here.
 * How:          A typed constant; tests spread and override it.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/repoConfigModel.test.ts, ui/src/screens/Repos/RepoDetail.test.tsx,
 *               ui/src/screens/Repos/RepoConfigTab.test.tsx (the importers), ui/src/api/types.ts (`RepoDetail`)
 * Tested by:    the three importers
 * Touch when:   a `RepoConfig` field changes — update the fixture and the matching cases together.
 */
import type { RepoDetail } from '../../api/types'

export const REPO: RepoDetail = {
  name: 'walk-pyrepo',
  language: 'python',
  runner: 'pytest',
  url: 'file:///tmp/pyrepo.git',
  clone_path: '/srv/home/repos/walk-pyrepo',
  probe: { status: 'ok', run_id: 'a'.repeat(32), checked: '2026-09-13T10:00:00+00:00', detail: '.....\n5 passed in 0.02s' },
  task_counts: { total: 0, standard: 0, hard: 0, gold_clean: 0, gold_failed: 0, unchecked: 0 },
  last_run: null,
  created: '2026-09-13T09:00:00+00:00',
  updated: '2026-09-13T09:00:00+00:00',
  github_full_name: null,
  config: {
    name: 'walk-pyrepo',
    language: 'python',
    runner: 'pytest',
    src_prefix: 'src/',
    test_prefix: 'tests/',
    ext: '.py',
    test_mode: 'prefix',
    test_suffix: '',
    belt_scope: 'AFFECTED_DIRS',
    probe: 'tests/test_calc.py',
    url: 'file:///tmp/pyrepo.git',
    layer: '',
    runner_opts: { pythonpath_suffix: '/src', python: '/opt/py/bin/python' },
    sandbox_image: '',
    mining: { log_n: 50 } as RepoDetail['config']['mining'],
  },
}
