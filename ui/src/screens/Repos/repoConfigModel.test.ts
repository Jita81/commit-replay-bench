/**
 * ui/src/screens/Repos/repoConfigModel.ts — stored config round-trips, only changes are sent,
 * validation speaks the server's words.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for the repo-config form model; also exports the `REPO` fixture
 *               the tab test reuses.
 * What it does: Pins that `formFromRepo` mirrors the stored config (an explicit belt list
 *               becomes LIST + rows; an unknown stored runner falls back to the language
 *               default, never an empty select), that `changedFields` is empty for an untouched
 *               form and names only what changed, that the wire helpers produce the server's
 *               shapes, that `validateForm` uses the server's messages, and that
 *               `parseScopeList` / `sameJson` behave.
 * How:          Direct calls on the `REPO` fixture and edited copies of its form.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/repoConfigModel.ts (the code under test),
 *               ui/src/screens/Repos/RepoConfigTab.test.tsx (imports `REPO`),
 *               src/crb/core/spec.py (the messages the validation cases quote)
 * Tested by:    ui/src/screens/Repos/repoConfigModel.test.ts
 * Touch when:   a `RepoConfig` field or validation message changes — update the fixture and
 *               the matching case.
 */
import { describe, expect, it } from 'vitest'
import type { RepoDetail } from '../../api/types'
import { beltScopeOf, changedFields, formFromRepo, miningOf, parseScopeList, requestOf, sameJson, validateForm } from './repoConfigModel'

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

describe('repoConfigModel', () => {
  it('formFromRepo mirrors the stored config; an explicit belt list becomes LIST + rows', () => {
    const f = formFromRepo(REPO)
    expect(f.language).toBe('python')
    expect(f.runner).toBe('pytest')
    expect(f.clone_path).toBe('/srv/home/repos/walk-pyrepo')
    expect(f.beltPolicy).toBe('AFFECTED_DIRS')
    expect(f.beltList).toEqual([])
    expect(f.mining).toEqual({ log_n: '50', max_candidates: '', target_valid: '', hard_target: '' })
    expect(f.runner_opts).toEqual({ pythonpath_suffix: '/src', python: '/opt/py/bin/python' })
    expect(f.runner_opts).not.toBe(REPO.config.runner_opts) // a copy, never the cached object
    const listed = formFromRepo({ ...REPO, config: { ...REPO.config, belt_scope: ['tests/', 'tests/acceptance/'] } })
    expect(listed.beltPolicy).toBe('LIST')
    expect(listed.beltList).toEqual(['tests/', 'tests/acceptance/'])
  })

  it('an unknown stored runner falls back to the language default rather than an empty select', () => {
    const f = formFromRepo({ ...REPO, config: { ...REPO.config, runner: '' } })
    expect(f.runner).toBe('pytest')
  })

  it('changedFields is empty for an untouched form and names only what changed', () => {
    const f = formFromRepo(REPO)
    expect(changedFields(f, REPO)).toEqual({})
    expect(changedFields({ ...f, probe: 'tests/test_calc.py ' }, REPO)).toEqual({}) // trimmed = same
    expect(changedFields({ ...f, runner_opts: { python: '/opt/py/bin/python', pythonpath_suffix: '/src' } }, REPO)).toEqual({}) // key order
    const edited = { ...f, beltPolicy: 'LIST' as const, beltList: ['tests/', ' '], runner_opts: { ...f.runner_opts, pip: ['pytest'] } }
    expect(changedFields(edited, REPO)).toEqual({
      belt_scope: ['tests/'],
      runner_opts: { pythonpath_suffix: '/src', python: '/opt/py/bin/python', pip: ['pytest'] },
    })
    expect(changedFields({ ...f, mining: { ...f.mining, log_n: '' } }, REPO)).toEqual({ mining: {} })
    expect(changedFields({ ...f, mining: { ...f.mining, hard_target: '7' } }, REPO)).toEqual({ mining: { log_n: 50, hard_target: 7 } })
    expect(changedFields({ ...f, language: 'javascript', runner: 'jest' }, REPO)).toEqual({ language: 'javascript', runner: 'jest' })
    expect(changedFields({ ...f, test_mode: 'suffix', test_suffix: '.test.ts|.snap' }, REPO)).toEqual({ test_mode: 'suffix', test_suffix: '.test.ts|.snap' })
  })

  it('requestOf / beltScopeOf / miningOf produce wire shapes', () => {
    const f = formFromRepo(REPO)
    expect(beltScopeOf({ beltPolicy: 'BARE', beltList: ['x'] })).toBe('BARE')
    expect(beltScopeOf({ beltPolicy: 'LIST', beltList: [' a ', '', 'b'] })).toEqual(['a', 'b'])
    expect(miningOf({ mining: { log_n: '10', max_candidates: 'x', target_valid: '', hard_target: '3' } })).toEqual({ log_n: 10, hard_target: 3 })
    const req = requestOf(f)
    expect(req.belt_scope).toBe('AFFECTED_DIRS')
    expect(req.mining).toEqual({ log_n: 50 })
    expect(req.clone_path).toBe('/srv/home/repos/walk-pyrepo')
  })

  it("validateForm speaks the server's words", () => {
    const f = formFromRepo(REPO)
    expect(validateForm(f)).toEqual({})
    expect(validateForm({ ...f, test_mode: 'suffix' })).toEqual({ test_suffix: "test_mode='suffix' requires test_suffix" })
    expect(validateForm({ ...f, beltPolicy: 'LIST', beltList: [' '] }).beltList).toMatch(/TARGET_ONLY \| AFFECTED_DIRS \| BARE \| \[scopes\]/)
    expect(validateForm({ ...f, ext: '.a'.repeat(20) }).ext).toBe('String should have at most 32 characters')
    expect(validateForm({ ...f, test_suffix: 'x'.repeat(129), test_mode: 'suffix' }).test_suffix).toBe('String should have at most 128 characters')
    expect(validateForm({ ...f, mining: { ...f.mining, log_n: '3.5' } })['mining.log_n']).toBe('Input should be a valid integer')
    expect(validateForm({ ...f, runner: 'jest' }).runner).toMatch(/does not run python; expected one of \(pytest\)/)
    expect(validateForm({ ...f, language: 'javascript', runner: 'jest' })).toEqual({})
  })

  it('parseScopeList splits on commas and newlines; sameJson ignores key order', () => {
    expect(parseScopeList('tests/, tests/acceptance/\n pkg/ ,,')).toEqual(['tests/', 'tests/acceptance/', 'pkg/'])
    expect(sameJson({ a: 1, b: [1, { c: 2, d: 3 }] }, { b: [1, { d: 3, c: 2 }], a: 1 })).toBe(true)
    expect(sameJson([1, 2], [2, 1])).toBe(false)
    expect(sameJson('1', 1)).toBe(false)
  })
})

describe('changedFields baseline is the stored config, not the normalised form', () => {
  it("reports a substituted default as a change so a stored '' runner can be saved over", () => {
    // a repo registered without a runner: the form shows the language default (pytest),
    // and that default IS a change relative to what the server holds (CodeRabbit on PR #6)
    const repo: RepoDetail = { ...REPO, config: { ...REPO.config, runner: '' } }
    const form = formFromRepo(repo)
    expect(form.runner).toBe('pytest')
    expect(changedFields(form, repo)).toEqual({ runner: 'pytest' })
    // a repo whose stored runner is known reads unchanged
    expect(changedFields(formFromRepo(REPO), REPO)).toEqual({})
  })
})
