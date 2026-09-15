/**
 * Built-in layout presets for the add-repo dialog. A preset fills the layout fields
 * (runner, prefixes, extension, belt scope, runner options) for a well-known project
 * shape; every field stays editable afterwards. Values follow the census
 * `configs.json` conventions (`crb.core.spec.RepoConfig.from_dict`) and the runner
 * option vocabulary in `crb.core.runners.*`.
 *
 * `probe` is deliberately left to the operator: a known-green scope is a fact about
 * the specific repository, never about its layout.
 *
 * Navigation
 * ----------
 * What it is:   The table of layout presets (`REPO_PRESETS`) the Add-repo dialog offers, and
 *               `findPreset`.
 * What it does: Fills runner, source / test prefixes, extension, belt scope and runner options
 *               for a well-known project shape (Python src/ or flat, Go, node / vitest / jest /
 *               mocha, Maven, Cargo); every field stays editable. It never sets `probe` — a
 *               known-green scope is a fact about one repository, not its layout.
 * How:          A static array; the dialog applies a preset by copying its fields into the
 *               form state.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/RepoNewDialog.tsx (the only consumer), ui/src/api/types.ts
 *               (`Language`, `Runner`, `BeltScope`), src/crb/core/spec.py (`RepoConfig` — the
 *               fields a preset fills), src/crb/core/runners/pytest_runner.py and
 *               src/crb/core/runners/node_runners.py (the `runner_opts` vocabulary the presets
 *               use)
 * Tested by:    ui/src/screens/Repos/RepoNewDialog.test.tsx,
 *               ui/e2e/walkthrough/02-repo-onboard.spec.ts
 * Touch when:   onboarding a repository whose layout no preset describes — add one here (its
 *               `runner_opts` keys must exist in the runner,
 *               docs/OPERATOR.md#2-configure-a-repository);
 *               a new `Runner` or `Language` in src/crb/core/spec.py should get a preset too.
 */

import type { BeltScope, Language, Runner } from '../api/types'

/** One preset = the layout fields of `RepoConfig` it fills; `probe` is deliberately absent. */
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

/** Display order in the dialog. Belt scope follows the runner: `AFFECTED_DIRS` where the runner can scope by directory, `TARGET_ONLY` where a full build is too slow (Maven, Cargo). */
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

/** Lookup by id (the dialog's `<select>` value); `undefined` for the "none" option. */
export function findPreset(id: string): RepoPreset | undefined {
  return REPO_PRESETS.find((p) => p.id === id)
}
