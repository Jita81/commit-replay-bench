/**
 * ui/src/screens/Repos/runnerOpts.ts — the key table mirrors crb.core.runners and invents nothing.
 *
 * Navigation
 * ----------
 * What it is:   Unit tests for the runner-options vocabulary.
 * What it does: Pins that every registered runner has an entry and every language maps to
 *               registered runners (each runner to exactly one language), that each runner
 *               exposes exactly the keys its code reads, that `unknownKeys` lists only
 *               unread keys (sorted), that the `as*` coercions never invent a value, and that
 *               `validateRunnerOpts` flags an int / bool / choice / list / env of the wrong
 *               shape.
 * How:          Table assertions against `RUNNER_OPTS` and `RUNNERS_BY_LANGUAGE`; direct calls
 *               for the helpers.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/runnerOpts.ts (the code under test), ui/src/api/types.ts
 *               (`RUNNERS`, `LANGUAGES` — the closed sets these cases cross-check)
 * Tested by:    ui/src/screens/Repos/runnerOpts.test.ts
 * Touch when:   a runner gains or loses a key (src/crb/core/runners/*) — the "exactly the
 *               keys" case must be updated with the table.
 */
import { describe, expect, it } from 'vitest'
import { LANGUAGES, RUNNERS } from '../../api/types'
import { RUNNERS_BY_LANGUAGE, RUNNER_OPTS, asEnv, asList, runnersFor, specsFor, unknownKeys, validateRunnerOpts } from './runnerOpts'

const keysOf = (runner: keyof typeof RUNNER_OPTS) => RUNNER_OPTS[runner].map((s) => s.key)

describe('runnerOpts — the key table mirrors crb.core.runners', () => {
  it('every runner has an entry and every language maps to registered runners', () => {
    expect(Object.keys(RUNNER_OPTS).sort()).toEqual([...RUNNERS].sort())
    for (const l of LANGUAGES) expect(runnersFor(l).length).toBeGreaterThan(0)
    const all = Object.values(RUNNERS_BY_LANGUAGE).flat().sort()
    expect(all).toEqual([...RUNNERS].sort()) // each runner belongs to exactly one language
  })

  it('exposes exactly the keys each runner reads', () => {
    expect(keysOf('pytest')).toEqual(['python', 'pythonpath_suffix', 'pip', 'pip_fallback', 'uninstall', 'env'])
    expect(keysOf('node')).toEqual(['node', 'npm', 'env']) // node --test never reads extra_args
    expect(keysOf('jest')).toEqual(['npm', 'extra_args', 'env'])
    expect(keysOf('vitest')).toEqual(['npm', 'extra_args', 'env'])
    expect(keysOf('mocha')).toEqual(['npm', 'mocha_require', 'extra_args', 'env'])
    expect(keysOf('go')).toEqual(['go', 'cgo', 'gomodcache'])
    expect(keysOf('cargo')).toEqual(['cargo', 'offline', 'cargo_home'])
    expect(keysOf('maven')).toEqual(['mvn', 'maven_flags', 'java_home', 'offline', 'writable', 'maven_opts'])
    // the BaseRunner keys follow every runner's own
    expect(specsFor('go').map((s) => s.key)).toEqual(['go', 'cgo', 'gomodcache', 'timeout', 'setup_timeout'])
    expect(specsFor('').map((s) => s.key)).toEqual(['timeout', 'setup_timeout'])
  })

  it('unknownKeys lists what the runner never reads (sorted), never a known key', () => {
    expect(unknownKeys('jest', { extra_args: ['--ci'], python: '/x', pythonpath_suffix: '/src', timeout: 60 })).toEqual(['python', 'pythonpath_suffix'])
    expect(unknownKeys('pytest', { python: '/x', post_create: [] })).toEqual(['post_create'])
  })

  it('coerces stored shapes for the editors without inventing values', () => {
    expect(asList(['a', 1])).toEqual(['a', '1'])
    expect(asList('single')).toEqual(['single'])
    expect(asList(undefined)).toEqual([])
    expect(asEnv({ PATH: '/opt/node@24/bin', N: 1 })).toEqual([
      ['PATH', '/opt/node@24/bin'],
      ['N', '1'],
    ])
    expect(asEnv(['x'])).toEqual([])
  })

  it('validateRunnerOpts flags what the runner would choke on', () => {
    expect(validateRunnerOpts('pytest', { pip: ['pytest'], python: '/x', timeout: 900, env: { A: 'b' } })).toEqual({})
    expect(validateRunnerOpts('pytest', { pip: 'pytest -r req.txt' })).toEqual({ pip: expect.stringMatching(/should be a list/) })
    expect(validateRunnerOpts('jest', { extra_args: ['--selectProjects', ''] })).toEqual({ extra_args: expect.stringMatching(/Empty row/) })
    expect(validateRunnerOpts('jest', { timeout: 'abc' })).toEqual({ timeout: 'Input should be a valid integer' })
    expect(validateRunnerOpts('jest', { timeout: '900' })).toEqual({}) // int("900") is fine for the runner
    expect(validateRunnerOpts('cargo', { offline: 'no' })).toEqual({ offline: 'Input should be true or false' })
    expect(validateRunnerOpts('go', { cgo: '2' })).toEqual({ cgo: 'Input should be one of 0, 1' })
    expect(validateRunnerOpts('go', { cgo: 1 })).toEqual({}) // str(1) == "1"
    expect(validateRunnerOpts('mocha', { env: ['PATH'] })).toEqual({ env: expect.stringMatching(/object of NAME/) })
    expect(validateRunnerOpts('mocha', { env: { '': 'x' } })).toEqual({ env: 'Every variable needs a name' })
    expect(validateRunnerOpts('mocha', { mocha_require: { a: 1 } })).toEqual({ mocha_require: 'Input should be a string' })
    // keys the runner does not read are not judged
    expect(validateRunnerOpts('go', { pip: 'whatever' })).toEqual({})
  })
})
