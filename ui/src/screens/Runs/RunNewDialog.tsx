import { useEffect, useState, type FormEvent } from 'react'
import { useCreateRun, useRepos, useSettings } from '../../api/hooks'
import { RUN_KINDS, type GradeMode, type Run, type RunCreateRequest, type RunKind } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { useAuth } from '../../lib/auth'
import { formatJsonObject, parseBuilderConfig } from '../../lib/jsonObject'

/** `crb.builders._REGISTRY` — the builder names a rung may name. (`/settings.builders` lists
 * CREDENTIAL probes — anthropic, cerebras, claude_code_cli … — not these names.) */
const BUILDER_NAMES = ['claude_code', 'openai_agent', 'editblock'] as const

/** `crb.builders.claude_code.DEFAULT_MODEL` / `KNOWN_MODELS` — the ids the adapter knows. */
export const CLAUDE_CODE_DEFAULT_MODEL = 'claude-sonnet-5'
export const CLAUDE_CODE_MODELS = ['claude-sonnet-5', 'claude-opus-5', 'claude-haiku-4-5', 'claude-opus-4-8'] as const

interface Props {
  open: boolean
  onClose: () => void
  repo?: string
  initialKind?: RunKind
  onCreated?: (run: Run) => void
}

const KIND_HELP: Record<RunKind, string> = {
  mine: 'Walk history for replayable commits (RED at parent, GREEN with the commit).',
  replay: 'Sighted replay: the builder sees the target tests; graded under four belts.',
  blind: 'Blind replay: the builder sees only the parent + a description; tests are overlaid at grade time.',
  oracle: 'Measure oracle strength (mutation kill-rate) per task.',
  controls: 'Run the negative-control matrix (gold, noop, tamper, stub, …).',
  probe: 'Prove the toolchain on a known-green scope.',
}

const BUILD_KINDS: RunKind[] = ['replay', 'blind']

const BUILDER_CONFIG_HELP: Record<string, string> = {
  claude_code: 'claude_code keys: auth ("api_key" — production, --bare, needs ANTHROPIC_API_KEY on the worker; "cli" — the operator’s own CLI login, developer/evaluation only), effort, bare, keep_transcript, extra_args.',
  openai_agent: 'openai_agent keys: endpoint, temperature, max_tokens, keep_transcript (see the adapter).',
  editblock: 'editblock keys: endpoint, temperature, max_tokens (see the adapter).',
}

/**
 * `POST /runs` — kind / mode / builder / model / ladder, the sampling knobs, and an
 * optional builder config (constructor overrides applied to every rung). The
 * executor default shown is the server’s `sandbox_mode` when the viewer may read
 * `/settings` (admin); otherwise it reads "server default".
 */
export function RunNewDialog({ open, onClose, repo: presetRepo, initialKind = 'replay', onCreated }: Props) {
  const repos = useRepos()
  const create = useCreateRun()
  const { can } = useAuth()
  const settings = useSettings(can('admin'))
  const [repo, setRepo] = useState(presetRepo ?? '')
  const [kind, setKind] = useState<RunKind>(initialKind)
  const [builder, setBuilder] = useState('')
  const [model, setModel] = useState('')
  const [provider, setProvider] = useState('')
  const [ladder, setLadder] = useState('r1')
  const [builderConfig, setBuilderConfig] = useState('')
  const [limit, setLimit] = useState('')
  const [pool, setPool] = useState('')
  const [executor, setExecutor] = useState('')
  const [timeout, setTimeoutS] = useState('')

  useEffect(() => {
    if (presetRepo) setRepo(presetRepo)
  }, [presetRepo])
  useEffect(() => {
    if (open) setKind(initialKind)
  }, [open, initialKind])

  const needsBuilder = BUILD_KINDS.includes(kind)
  const mode: GradeMode = kind === 'blind' ? 'blind' : 'sighted'
  const cfg = parseBuilderConfig(builderConfig)
  const cfgError = needsBuilder && !cfg.ok ? cfg.error : undefined
  const valid = repo && (!needsBuilder || (builder && cfg.ok))
  const serverExecutor = settings.data?.sandbox_mode || ''
  const builders = settings.data?.builders ?? []
  const isClaudeCode = builder === 'claude_code'
  const cliLogin = cfg.ok && cfg.value.auth === 'cli'

  /** One click: `{"auth": "cli"}` in the builder config (merged with whatever else is there). */
  const toggleCliLogin = (on: boolean) => {
    if (!cfg.ok) return
    const next = { ...cfg.value }
    if (on) next.auth = 'cli'
    else delete next.auth
    setBuilderConfig(formatJsonObject(next))
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const body: RunCreateRequest = { repo, kind }
    if (needsBuilder) {
      body.mode = mode
      body.builder = builder
      if (model) body.model = model
      if (provider) body.provider = provider
      const rungs = ladder
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      if (rungs.length) body.ladder = rungs
      if (cfg.ok && Object.keys(cfg.value).length) body.builder_config = cfg.value
    }
    if (limit) body.limit = Number(limit)
    if (pool) body.pool = pool
    if (executor) body.executor = executor
    if (timeout) body.timeout = Number(timeout)
    create.mutate(body, {
      onSuccess: (run) => {
        onCreated?.(run)
        onClose()
      },
    })
  }

  return (
    <Dialog
      open={open}
      title="Start a run"
      onClose={onClose}
      width="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="run-new-form" variant="filled" disabled={!valid || create.isPending}>
            {create.isPending ? 'Queuing…' : 'Queue run'}
          </Button>
        </>
      }
    >
      <form id="run-new-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Repo" required value={repo} onChange={(e) => setRepo(e.target.value)} disabled={Boolean(presetRepo)}>
          <option value="">Choose…</option>
          {(repos.data?.items ?? []).map((r) => (
            <option key={r.name} value={r.name}>
              {r.name}
            </option>
          ))}
          {presetRepo && !repos.data?.items.some((r) => r.name === presetRepo) && <option value={presetRepo}>{presetRepo}</option>}
        </SelectField>
        <SelectField label="Kind" required value={kind} onChange={(e) => setKind(e.target.value as RunKind)} hint={KIND_HELP[kind]}>
          {RUN_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </SelectField>
        {needsBuilder && (
          <>
            <TextField label="Mode" value={mode} readOnly hint="Derived from kind: replay = sighted, blind = blind" />
            <TextField
              label="Builder"
              required
              value={builder}
              onChange={(e) => setBuilder(e.target.value)}
              list="crb-builders"
              placeholder="editblock · openai_agent · claude_code"
              hint={
                builders.length
                  ? `Credentials on the server: ${builders.filter((b) => b.configured).map((b) => b.name).join(', ') || 'none'}`
                  : 'A builder registered on the server (see Settings)'
              }
            />
            <datalist id="crb-builders">
              {BUILDER_NAMES.map((b) => (
                <option key={b} value={b} />
              ))}
            </datalist>
            <TextField
              label="Model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              list={isClaudeCode ? 'crb-claude-models' : undefined}
              placeholder={isClaudeCode ? CLAUDE_CODE_DEFAULT_MODEL : 'e.g. gpt-oss-120b'}
              hint={isClaudeCode ? `Default ${CLAUDE_CODE_DEFAULT_MODEL} (the census’s measured path); claude-opus-5 is selectable` : undefined}
            />
            {isClaudeCode && (
              <datalist id="crb-claude-models">
                {CLAUDE_CODE_MODELS.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            )}
            <TextField label="Provider" value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="e.g. cerebras" />
            <TextField label="Ladder" value={ladder} onChange={(e) => setLadder(e.target.value)} hint="Comma-separated rung labels; each rung is one attempt (r1, r2 …)" />
            {isClaudeCode && (
              <div className="flex items-start gap-2 rounded-[var(--radius-control)] border border-border bg-surface-container px-3 py-2 sm:col-span-2">
                <input id="crb-cli-login" type="checkbox" className="mt-0.5" checked={cliLogin} disabled={!cfg.ok} onChange={(e) => toggleCliLogin(e.target.checked)} />
                <label htmlFor="crb-cli-login" className="text-xs text-on-surface-body">
                  <span className="font-semibold">Use my Claude Code login (dev)</span> — sets <code>{'{"auth": "cli"}'}</code>: the worker runs <code>claude</code> without <code>--bare</code> on the operator’s own subscription login instead of <code>ANTHROPIC_API_KEY</code>. Developer / evaluation only — the target repo’s CLAUDE.md is auto-discovered in this mode (its project settings and hooks are still excluded).
                </label>
              </div>
            )}
            <div className="sm:col-span-2">
              <TextArea
                label="Builder config (JSON, optional)"
                value={builderConfig}
                onChange={(e) => setBuilderConfig(e.target.value)}
                rows={4}
                spellCheck={false}
                className="font-mono text-xs"
                placeholder={'{\n  "auth": "cli",\n  "effort": "high"\n}'}
                error={cfgError}
                hint={`Constructor overrides applied to every rung and stamped into the run’s apparatus. ${BUILDER_CONFIG_HELP[builder] ?? 'model / provider and credential keys are refused — identity comes from the ladder, secrets from the worker’s environment.'}`}
              />
            </div>
          </>
        )}
        <TextField label="Task limit" type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} hint="Leave blank for all tasks" />
        <SelectField label="Pool" value={pool} onChange={(e) => setPool(e.target.value)}>
          <option value="">all</option>
          <option value="standard">standard</option>
          <option value="hard">hard</option>
        </SelectField>
        <SelectField label="Executor" value={executor} onChange={(e) => setExecutor(e.target.value)} hint="Docker fails closed when unavailable; there is no local fallback">
          <option value="">{serverExecutor ? `server default (${serverExecutor})` : 'server default'}</option>
          <option value="docker">docker (sandboxed)</option>
          <option value="local">local</option>
        </SelectField>
        <TextField label="Timeout (s)" type="number" min={1} value={timeout} onChange={(e) => setTimeoutS(e.target.value)} hint="Per test run; a timeout is a failure, never a pass" />
        {create.isError && (
          <div className="sm:col-span-2">
            <ErrorState compact error={create.error} />
          </div>
        )}
      </form>
    </Dialog>
  )
}
