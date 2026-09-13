/**
 * Built-in layout presets for the add-repo dialog. A preset fills the layout fields
 * (runner, prefixes, extension, belt scope, runner options) for a well-known project
 * shape; every field stays editable afterwards. Values follow the census
 * `configs.json` conventions (`crb.core.spec.RepoConfig.from_dict`) and the runner
 * option vocabulary in `crb.core.runners.*`.
 *
 * `probe` is deliberately left to the operator: a known-green scope is a fact about
 * the specific repository, never about its layout.
 */

import type { BeltScope, Language, Runner } from '../api/types'

export interface RepoPreset {
  id: string
  label: string
  description: string
  language: Language
  runner: Runner
  src_prefix: string
  test_prefix: string
  ext: string
  belt_scope: BeltScope
  runner_opts: Record<string, unknown>
}

export const REPO_PRESETS: readonly RepoPreset[] = [
  {
    id: 'python-src-layout',
    label: 'Python · src/ layout (pytest)',
    description: 'Package under src/<pkg>/, tests under tests/. `pythonpath_suffix` puts src/ on the path; `pip` lists what the sandbox must install.',
    language: 'python',
    runner: 'pytest',
    src_prefix: 'src/',
    test_prefix: 'tests/',
    ext: '.py',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: { pythonpath_suffix: '/src', pip: ['pytest'] },
  },
  {
    id: 'python-flat',
    label: 'Python · flat layout (pytest)',
    description: 'Package at the repo root (<pkg>/), tests under tests/. Set the source prefix to the package directory.',
    language: 'python',
    runner: 'pytest',
    src_prefix: '',
    test_prefix: 'tests/',
    ext: '.py',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: { pip: ['pytest'] },
  },
  {
    id: 'go',
    label: 'Go · go test ./...',
    description: 'Tests are *_test.go beside their sources; the belt runs the affected packages.',
    language: 'go',
    runner: 'go',
    src_prefix: '',
    test_prefix: '',
    ext: '.go',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: {},
  },
  {
    id: 'node-test',
    label: 'JavaScript · node --test',
    description: 'lib/ + test/ with the built-in node test runner (no framework).',
    language: 'javascript',
    runner: 'node',
    src_prefix: 'lib/',
    test_prefix: 'test/',
    ext: '.js',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: {},
  },
  {
    id: 'vitest',
    label: 'JavaScript/TypeScript · vitest',
    description: 'src/ + test/ with vitest. For co-located *.test.ts files switch the test mode to suffix after applying.',
    language: 'javascript',
    runner: 'vitest',
    src_prefix: 'src/',
    test_prefix: 'test/',
    ext: '.ts',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: {},
  },
  {
    id: 'jest',
    label: 'JavaScript · jest',
    description: 'src/ + test/ with jest.',
    language: 'javascript',
    runner: 'jest',
    src_prefix: 'src/',
    test_prefix: 'test/',
    ext: '.js',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: {},
  },
  {
    id: 'mocha',
    label: 'JavaScript · mocha',
    description: 'lib/ + test/ with mocha. `mocha_require` names a setup module (e.g. test/support/env) when the suite needs one.',
    language: 'javascript',
    runner: 'mocha',
    src_prefix: 'lib/',
    test_prefix: 'test/',
    ext: '.js',
    belt_scope: 'AFFECTED_DIRS',
    runner_opts: {},
  },
  {
    id: 'maven',
    label: 'JVM · maven (surefire)',
    description: 'src/main/java + src/test/java. `maven_flags` are appended to every mvn invocation (e.g. -Denforcer.skip=true, -pl <module>).',
    language: 'jvm',
    runner: 'maven',
    src_prefix: 'src/main/java/',
    test_prefix: 'src/test/java/',
    ext: '.java',
    belt_scope: 'TARGET_ONLY',
    runner_opts: { maven_flags: [] },
  },
  {
    id: 'cargo',
    label: 'Rust · cargo test',
    description: 'src/ + tests/ with cargo.',
    language: 'rust',
    runner: 'cargo',
    src_prefix: 'src/',
    test_prefix: 'tests/',
    ext: '.rs',
    belt_scope: 'TARGET_ONLY',
    runner_opts: {},
  },
]

export function findPreset(id: string): RepoPreset | undefined {
  return REPO_PRESETS.find((p) => p.id === id)
}
