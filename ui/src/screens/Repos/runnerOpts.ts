/**
 * The `runner_opts` vocabulary, runner by runner — EXACTLY the keys the runner code
 * reads (`crb.core.runners.*`), no more. Anything else an operator puts in
 * `runner_opts` is preserved untouched (and listed as "not read by this runner") so
 * a hand-written key never silently disappears, but the form never invents one.
 *
 * Source of truth, key by key:
 *   base.py       `timeout`, `setup_timeout`                         (every runner)
 *   pytest_runner `python`, `pythonpath_suffix`, `pip`, `pip_fallback`, `uninstall`, `env`
 *   node_runners  `npm`, `env` (all four); `node` (node --test only);
 *                 `extra_args` (jest / vitest / mocha — not node); `mocha_require` (mocha)
 *   go_runner     `go`, `cgo`, `gomodcache` (docker)
 *   cargo_runner  `cargo`, `offline`, `cargo_home` (docker)
 *   jvm_runner    `mvn`, `maven_flags`, `java_home`, `maven_opts` (docker), `writable`, `offline`
 *
 * `post_create` (workspace hooks) is read by `crb.core.workspace`, not a runner; it
 * stays editable through the raw JSON view only.
 *
 * Navigation
 * ----------
 * What it is:   The `runner_opts` key table (`RUNNER_OPTS`, `COMMON_OPTS`), the language →
 *               runner map, and the coercion / validation helpers the options editor uses.
 * What it does: Offers an operator only the keys `crb.core.runners.<runner>` actually reads,
 *               each with the runner's behaviour as its hint; keeps any other key untouched
 *               and lists it as "not read by this runner" so a hand-written key never
 *               disappears; and refuses at edit time what the runner would choke on at run
 *               time (the API accepts any object — validation lives in the runner).
 * How:          One `OptSpec[]` per runner (kind: path / text / int / bool / choice / list /
 *               env) plus the `BaseRunner` common keys; `specsFor`, `unknownKeys`, `as*`
 *               coercions and `validateRunnerOpts` are pure.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   src/crb/core/runners/base.py (`timeout`, `setup_timeout`),
 *               src/crb/core/runners/pytest_runner.py, src/crb/core/runners/node_runners.py,
 *               src/crb/core/runners/go_runner.py, src/crb/core/runners/cargo_runner.py,
 *               src/crb/core/runners/jvm_runner.py (the source of truth, key by key),
 *               ui/src/screens/Repos/RunnerOptsEditor.tsx (renders the specs),
 *               ui/src/lib/repoPresets.ts (presets must use keys from this table)
 * Tested by:    ui/src/screens/Repos/runnerOpts.test.ts (the key table mirrors the runners;
 *               coercions invent nothing; validation flags the right shapes),
 *               ui/src/screens/Repos/RepoConfigTab.test.tsx
 * Touch when:   a runner starts reading a new `runner_opts` key (src/crb/core/runners/*) —
 *               add its `OptSpec` here in the same commit, or the form cannot offer it; a
 *               new runner needs its entry in `RUNNER_OPTS` and `RUNNERS_BY_LANGUAGE`. For a
 *               new repository: nothing here — set its options through the form
 *               (docs/OPERATOR.md#2-configure-a-repository).
 */

import type { Language, Runner } from '../../api/types'

/** Runners that make sense for a language (`crb.core.runners`: one module per language). */
export const RUNNERS_BY_LANGUAGE: Record<Language, readonly Runner[]> = {
  python: ['pytest'],
  go: ['go'],
  javascript: ['node', 'vitest', 'jest', 'mocha'],
  jvm: ['maven'],
  rust: ['cargo'],
}

/** `crb.core.spec._DEFAULT_RUNNER_FOR_LANGUAGE` — what an empty `runner` resolves to. */
export const DEFAULT_RUNNER: Record<Language, Runner> = {
  python: 'pytest',
  go: 'go',
  javascript: 'mocha',
  jvm: 'maven',
  rust: 'cargo',
}

/** The runners a language allows (empty for an unknown language). */
export function runnersFor(language: Language): readonly Runner[] {
  return RUNNERS_BY_LANGUAGE[language] ?? []
}

/** How an option is edited and validated; mirrors the type the runner reads from `runner_opts`. */
export type OptKind =
  /** A host path or binary name (string). */
  | 'path'
  /** Free text (string). */
  | 'text'
  /** A whole number of seconds. */
  | 'int'
  /** A tri-state boolean: unset (runner default) / true / false. */
  | 'bool'
  /** One of a fixed set of strings. */
  | 'choice'
  /** A list of strings (one input per item). */
  | 'list'
  /** A string → string map (environment variables). */
  | 'env'

/** One `runner_opts` key: its kind, label, the runner's behaviour as hint, and the docker-only flag. */
export interface OptSpec {
  key: string
  kind: OptKind
  label: string
  /** What the runner does with it — quoted from the runner code's behaviour. */
  hint: string
  placeholder?: string
  /** `choice` only. */
  options?: readonly string[]
  /** `bool` only: what the runner assumes when the key is absent. */
  defaultBool?: boolean
  /** Read only under the docker executor. */
  dockerOnly?: boolean
}

/** `BaseRunner`: read by every runner. */
export const COMMON_OPTS: readonly OptSpec[] = [
  {
    key: 'timeout',
    kind: 'int',
    label: 'Test timeout (s)',
    hint: 'Wall clock for one test command (target or belt). Empty = the runner’s default (pytest 900, node 420, go 600, maven 1500, cargo 1200). A timeout is a failure, never a pass.',
    placeholder: '900',
  },
  {
    key: 'setup_timeout',
    kind: 'int',
    label: 'Setup timeout (s)',
    hint: 'Per-step wall clock for the environment setup phase (the only network phase). Empty = 1800.',
    placeholder: '1800',
  },
]

/** Shared `env` spec: every runner exports these into the test command. */
const ENV: OptSpec = {
  key: 'env',
  kind: 'env',
  label: 'Environment variables',
  hint: 'Added to the test command’s environment (and, for the node runners, to npm setup). Put a pinned toolchain first on PATH here, e.g. PATH=/opt/node@24/bin:/usr/bin:/bin.',
}

/** Shared `npm` spec for the four node runners. */
const NPM: OptSpec = {
  key: 'npm',
  kind: 'path',
  label: 'npm binary',
  hint: 'Used by setup (`npm ci` / `npm install`). Empty = the host’s npm on PATH.',
  placeholder: '/opt/node@24/bin/npm',
}

/** Shared `extra_args` spec (jest / vitest / mocha, not `node --test`). */
const EXTRA_ARGS = (runner: string): OptSpec => ({
  key: 'extra_args',
  kind: 'list',
  label: 'Extra arguments',
  hint: `Appended to every ${runner} invocation before the test paths — one argument per row, e.g. --selectProjects then unit (jest) to keep a browser project out of the belt.`,
  placeholder: '--selectProjects',
})

/** Shared tri-state `offline` spec (cargo, maven) with the runner's flags named in the hint. */
const OFFLINE = (tool: string, flagOn: string, flagOff: string): OptSpec => ({
  key: 'offline',
  kind: 'bool',
  label: 'Offline',
  hint: `Default true: ${tool} runs with ${flagOn} (resolve from the local cache only). false switches to ${flagOff}, which may reach the network — setup is meant to be the only network phase.`,
  defaultBool: true,
})

/** The key table: exactly what each runner module reads, nothing more. */
export const RUNNER_OPTS: Record<Runner, readonly OptSpec[]> = {
  pytest: [
    {
      key: 'python',
      kind: 'path',
      label: 'Python interpreter',
      hint: 'An interpreter you manage yourself, used as given (a relative path with a directory part resolves against the clone). When set, setup never installs into it — it only checks that it imports pytest. Empty = the venv setup builds.',
      placeholder: '/srv/venvs/myrepo/bin/python',
    },
    {
      key: 'pythonpath_suffix',
      kind: 'text',
      label: 'PYTHONPATH suffix',
      hint: 'Appended to the worktree root on PYTHONPATH, e.g. /src for a src/ layout (`<root>/src`). The tests must import the worktree’s source, not an installed wheel.',
      placeholder: '/src',
    },
    {
      key: 'pip',
      kind: 'list',
      label: 'pip install arguments',
      hint: 'The primary install, one pip argument per row (e.g. -e, ., pytest, -r, requirements/test.txt). Empty = an editable install of the repo with its test extra, then pytest.',
      placeholder: '-e .[test]',
    },
    {
      key: 'pip_fallback',
      kind: 'list',
      label: 'pip fallback arguments',
      hint: 'A second pip argument list, tried only when the primary install fails.',
      placeholder: 'pytest',
    },
    {
      key: 'uninstall',
      kind: 'list',
      label: 'Uninstall after install',
      hint: 'Distributions removed after the install — the repo’s OWN package — so the worktree source on PYTHONPATH is what the tests import, never a stale wheel.',
      placeholder: 'myrepo',
    },
    ENV,
  ],
  node: [
    {
      key: 'node',
      kind: 'path',
      label: 'node binary',
      hint: 'The interpreter for `node --test`. Empty = the host’s node on PATH.',
      placeholder: '/opt/node@24/bin/node',
    },
    NPM,
    ENV,
  ],
  vitest: [NPM, EXTRA_ARGS('vitest'), ENV],
  jest: [NPM, EXTRA_ARGS('jest'), ENV],
  mocha: [
    NPM,
    {
      key: 'mocha_require',
      kind: 'text',
      label: 'mocha --require',
      hint: 'A setup module passed as `--require` (e.g. test/support/env) when the suite needs one.',
      placeholder: 'test/support/env',
    },
    EXTRA_ARGS('mocha'),
    ENV,
  ],
  go: [
    {
      key: 'go',
      kind: 'path',
      label: 'go binary',
      hint: 'Used for `go test -json` and setup (`go mod download`). Empty = the host’s go on PATH.',
      placeholder: '/usr/local/go/bin/go',
    },
    {
      key: 'cgo',
      kind: 'choice',
      label: 'CGO_ENABLED',
      hint: 'Default 0 (pure-Go build). Set 1 only when the tests need cgo and the host has a C toolchain.',
      options: ['0', '1'],
    },
    {
      key: 'gomodcache',
      kind: 'path',
      label: 'GOMODCACHE (docker)',
      hint: 'Module cache path inside the sandbox image. Default /tmp/gomod. Ignored by the local executor.',
      placeholder: '/tmp/gomod',
      dockerOnly: true,
    },
  ],
  cargo: [
    {
      key: 'cargo',
      kind: 'path',
      label: 'cargo binary',
      hint: 'Used for `cargo test` and setup (`cargo fetch`). Empty = the host’s cargo on PATH.',
      placeholder: '/usr/local/cargo/bin/cargo',
    },
    OFFLINE('cargo test', '--offline', '--locked'),
    {
      key: 'cargo_home',
      kind: 'path',
      label: 'CARGO_HOME (docker)',
      hint: 'Registry cache path inside the sandbox image. Default /tmp/cargo. Ignored by the local executor.',
      placeholder: '/tmp/cargo',
      dockerOnly: true,
    },
  ],
  maven: [
    {
      key: 'mvn',
      kind: 'path',
      label: 'mvn binary',
      hint: 'Used when the clone has no ./mvnw wrapper. Empty = the host’s mvn on PATH.',
      placeholder: '/opt/maven/bin/mvn',
    },
    {
      key: 'maven_flags',
      kind: 'list',
      label: 'Maven flags',
      hint: 'Appended to every mvn invocation (setup, readiness and the test runs), one per row — e.g. -pl then core, or -Denforcer.skip=true.',
      placeholder: '-Denforcer.skip=true',
    },
    {
      key: 'java_home',
      kind: 'path',
      label: 'JAVA_HOME',
      hint: 'Exported to every mvn invocation when set.',
      placeholder: '/usr/lib/jvm/java-21',
    },
    OFFLINE('mvn', '-o', '-U'),
    {
      key: 'writable',
      kind: 'list',
      label: 'Extra writable paths',
      hint: 'Repo-relative paths the sandbox may write besides target/ (and <module>/target/ derived from the source prefix).',
      placeholder: 'build',
    },
    {
      key: 'maven_opts',
      kind: 'text',
      label: 'MAVEN_OPTS (docker)',
      hint: 'Appended to `-Dmaven.repo.local=/tmp/m2` inside the sandbox image. Ignored by the local executor.',
      placeholder: '-Xmx2g',
      dockerOnly: true,
    },
  ],
}

/** The runner's own keys followed by the common ones. */
export function specsFor(runner: Runner | ''): readonly OptSpec[] {
  const own = runner ? (RUNNER_OPTS[runner] ?? []) : []
  return [...own, ...COMMON_OPTS]
}

/** Keys present in `opts` that the runner never reads (kept, but shown as such). */
export function unknownKeys(runner: Runner | '', opts: Record<string, unknown>): string[] {
  const known = new Set(specsFor(runner).map((s) => s.key))
  return Object.keys(opts)
    .filter((k) => !known.has(k))
    .sort()
}

/** A stored value as the list the form edits (a string becomes a single item). */
export function asList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => String(x))
  if (typeof v === 'string' && v.length) return [v]
  return []
}

/** A stored value as the string → string map the form edits. */
export function asEnv(v: unknown): Array<[string, string]> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return []
  return Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, String(x)])
}

/** A stored value as text for a text/path/choice input. */
export function asText(v: unknown): string {
  if (v === undefined || v === null) return ''
  return typeof v === 'string' ? v : String(v)
}

/** A stored value as the tri-state a `bool` control shows. */
export function asBool(v: unknown): '' | 'true' | 'false' {
  if (v === true) return 'true'
  if (v === false) return 'false'
  return ''
}

/** A non-negative integer, as a number or as digit text (what an `int` input can hold). */
const isInt = (v: unknown): boolean => (typeof v === 'number' && Number.isInteger(v) && v >= 0) || (typeof v === 'string' && /^\d+$/.test(v))

/**
 * What the runner would choke on at run time — checked here because the API
 * accepts any `runner_opts` object (it is "free-form but validated by the runner").
 * Keyed by option; empty when everything the runner reads has the shape it reads.
 */
export function validateRunnerOpts(runner: Runner | '', opts: Record<string, unknown>): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const spec of specsFor(runner)) {
    if (!(spec.key in opts)) continue
    const v = opts[spec.key]
    switch (spec.kind) {
      case 'int':
        if (!isInt(v)) errors[spec.key] = 'Input should be a valid integer'
        break
      case 'bool':
        if (typeof v !== 'boolean') errors[spec.key] = 'Input should be true or false'
        break
      case 'choice':
        if (!(spec.options ?? []).includes(asText(v))) errors[spec.key] = `Input should be one of ${(spec.options ?? []).join(', ')}`
        break
      case 'list':
        if (!Array.isArray(v)) errors[spec.key] = 'Input should be a list — one item per row (a bare string is not split)'
        else if (v.some((x) => String(x).trim() === '')) errors[spec.key] = 'Empty row — fill it in or remove it'
        break
      case 'env':
        if (!v || typeof v !== 'object' || Array.isArray(v)) errors[spec.key] = 'Input should be an object of NAME: value'
        else if (Object.keys(v as object).some((k) => k.trim() === '')) errors[spec.key] = 'Every variable needs a name'
        break
      case 'path':
      case 'text':
        if (typeof v !== 'string' && typeof v !== 'number') errors[spec.key] = 'Input should be a string'
        break
    }
  }
  return errors
}
