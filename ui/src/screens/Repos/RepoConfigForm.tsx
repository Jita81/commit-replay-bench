import type { ReactNode } from 'react'
import { LANGUAGES, type Language, type Runner } from '../../api/types'
import { SelectField, TextField } from '../../components/Field'
import { ListEditor } from './ListEditors'
import { BELT_HELP, MINING_HELP, MINING_KEYS, type BeltPolicy, type FormErrors, type RepoConfigForm as FormState } from './repoConfigModel'
import { DEFAULT_RUNNER, runnersFor, validateRunnerOpts } from './runnerOpts'
import { RunnerOptsEditor } from './RunnerOptsEditor'

interface Props {
  form: FormState
  onChange: (form: FormState) => void
  errors: FormErrors
  disabled?: boolean
  onJsonError?: (error: string | undefined) => void
}

function Group({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="m-0 min-w-0 border-0 p-0">
      <legend className="label mb-2 w-full border-b border-border pb-1">{title}</legend>
      {note && <div className="mb-3 text-xs text-on-surface-muted">{note}</div>}
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </fieldset>
  )
}

/**
 * Every `RepoConfig` field the API accepts on `PUT /repos/{name}`, grouped the way an
 * operator reasons about a repository: where it is, how source is told from test,
 * what the regression belt covers, how the toolchain is proven, and the runner's
 * own options. Controlled: the parent owns the state and the changed-field diff.
 */
export function RepoConfigForm({ form, onChange, errors, disabled, onJsonError }: Props) {
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => onChange({ ...form, [key]: value })
  const setLanguage = (language: Language) => {
    const allowed = runnersFor(language)
    const runner: Runner = allowed.includes(form.runner) ? form.runner : DEFAULT_RUNNER[language]
    onChange({ ...form, language, runner })
  }
  const runners = runnersFor(form.language)
  const optErrors = validateRunnerOpts(form.runner, form.runner_opts)

  return (
    <div className="space-y-6" data-testid="repo-config-form">
      <Group title="Toolchain">
        <SelectField label="Language" required value={form.language} error={errors.language} disabled={disabled} onChange={(e) => setLanguage(e.target.value as Language)} data-testid="repo-config-language" hint="Selects the source/test heuristics and the runners that can run it">
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </SelectField>
        <SelectField label="Runner" required value={form.runner} error={errors.runner} disabled={disabled} onChange={(e) => set('runner', e.target.value as Runner)} data-testid="repo-config-runner" hint={`Runners for ${form.language}: ${runners.join(', ')}`}>
          {runners.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </SelectField>
      </Group>

      <Group title="Location" note="Where the clone lives on the server host; the URL is what the worker clones when there is no clone yet (https:// or ssh:// only — the server refuses the rest at clone time).">
        <TextField label="Clone path" value={form.clone_path} error={errors.clone_path} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder="/srv/repos/myrepo" onChange={(e) => set('clone_path', e.target.value)} data-testid="repo-config-clone-path" hint="Empty until the worker's first run clones the URL" />
        <TextField label="Git URL" value={form.url} error={errors.url} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder="https://github.com/org/repo.git" onChange={(e) => set('url', e.target.value)} data-testid="repo-config-url" hint="Informational once a clone path exists" />
      </Group>

      <Group title="Layout" note="A file is SOURCE if it has one of the extensions and starts with the source prefix; a TEST is decided by the test mode. Go and Rust use their own conventions (_test.go, tests/*.rs) regardless.">
        <TextField label="Source prefix" value={form.src_prefix} error={errors.src_prefix} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder="src/" onChange={(e) => set('src_prefix', e.target.value)} data-testid="repo-config-src-prefix" hint="Empty = anything outside the test prefix" />
        <TextField label="Extensions" value={form.ext} error={errors.ext} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder=".ts|.tsx" onChange={(e) => set('ext', e.target.value)} data-testid="repo-config-ext" hint="|-separated alternatives, e.g. .js|.mjs|.ts|.tsx. Empty = the language default" />
        <SelectField label="Test mode" value={form.test_mode} error={errors.test_mode} disabled={disabled} onChange={(e) => set('test_mode', e.target.value as 'prefix' | 'suffix')} data-testid="repo-config-test-mode" hint={form.test_mode === 'suffix' ? 'suffix: a test is any file ending in one of the suffixes, wherever it lives (co-located *.test.ts)' : 'prefix: a test is a file with the extension under the test prefix'}>
          <option value="prefix">prefix — tests live under a directory</option>
          <option value="suffix">suffix — tests are named by their ending</option>
        </SelectField>
        {form.test_mode === 'suffix' ? (
          <TextField label="Test suffixes" required value={form.test_suffix} error={errors.test_suffix} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder=".test.ts|.test.tsx|.snap" onChange={(e) => set('test_suffix', e.target.value)} data-testid="repo-config-test-suffix" hint="|-separated endings, e.g. .unit.test.mjs|.jsdom.test.mjs; include .snap so snapshot-only commits keep their oracle" />
        ) : (
          <TextField label="Test prefix" value={form.test_prefix} error={errors.test_prefix} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder="tests/" onChange={(e) => set('test_prefix', e.target.value)} data-testid="repo-config-test-prefix" hint="A file is a test if it starts here" />
        )}
      </Group>

      <Group title="Regression belt" note="Belt 3 — no new failures — runs this scope after the target tests. The wider the belt, the more a green means.">
        <div className="sm:col-span-2">
          <div className="text-xs font-semibold text-on-surface-body">Belt scope</div>
          <div role="radiogroup" aria-label="Belt scope" className="mt-1 grid gap-2 sm:grid-cols-2">
            {(['TARGET_ONLY', 'AFFECTED_DIRS', 'BARE', 'LIST'] as BeltPolicy[]).map((p) => (
              <label key={p} className={`flex cursor-pointer items-start gap-2 rounded-[var(--radius-control)] border px-3 py-2 text-sm ${form.beltPolicy === p ? 'border-primary bg-primary-container' : 'border-border'}`}>
                <input type="radio" name="belt_scope" value={p} checked={form.beltPolicy === p} disabled={disabled} onChange={() => set('beltPolicy', p)} className="mt-1" data-testid={`repo-config-belt-${p}`} />
                <span className="min-w-0">
                  <span className="block font-mono text-xs font-semibold">{p === 'LIST' ? 'Explicit list' : p}</span>
                  <span className="block text-xs text-on-surface-muted">{BELT_HELP[p]}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
        {form.beltPolicy === 'LIST' && (
          <div className="sm:col-span-2">
            <ListEditor label="Belt scope" values={form.beltList} onChange={(v) => set('beltList', v)} error={errors.beltList} disabled={disabled} testid="repo-config-belt-list" placeholder="tests/" addLabel="Add scope" hint="One runner scope per row, in the form the runner addresses (a directory for pytest/jest, a package pattern for go, a surefire class glob for maven)" />
          </div>
        )}
      </Group>

      <Group title="Probe and sandbox">
        <TextField label="Probe scope" value={form.probe} error={errors.probe} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder="tests/test_smoke.py" onChange={(e) => set('probe', e.target.value)} data-testid="repo-config-probe" hint="A known-green scope (whitespace-separated runner scopes) the probe runs to prove the toolchain; empty = the runner's bare discovery" />
        <TextField label="Sandbox image" value={form.sandbox_image} error={errors.sandbox_image} disabled={disabled} spellCheck={false} className="font-mono text-xs" placeholder="ghcr.io/org/repo-toolchain:2026-09" onChange={(e) => set('sandbox_image', e.target.value)} data-testid="repo-config-sandbox-image" hint="Container image with toolchain + deps; the docker executor fails closed without one" />
        <TextField label="Layer" value={form.layer} error={errors.layer} disabled={disabled} spellCheck={false} placeholder="platform" onChange={(e) => set('layer', e.target.value)} data-testid="repo-config-layer" hint="A free label for grouping repos in reports (not read by any runner)" />
      </Group>

      <Group title="Mining caps" note="How far a mine run walks and how many replayable tasks it keeps per pool. Empty = the miner's default.">
        {MINING_KEYS.map((k) => (
          <TextField key={k} label={MINING_HELP[k].label} value={form.mining[k]} error={errors[`mining.${k}`]} disabled={disabled} inputMode="numeric" className="font-mono text-xs" placeholder={MINING_HELP[k].placeholder} onChange={(e) => set('mining', { ...form.mining, [k]: e.target.value })} data-testid={`repo-config-mining-${k}`} hint={MINING_HELP[k].hint} />
        ))}
      </Group>

      <fieldset className="m-0 min-w-0 border-0 p-0">
        <legend className="label mb-2 w-full border-b border-border pb-1">Runner options</legend>
        <RunnerOptsEditor runner={form.runner} value={form.runner_opts} onChange={(v) => set('runner_opts', v)} errors={optErrors} disabled={disabled} onJsonError={onJsonError} />
      </fieldset>
    </div>
  )
}
