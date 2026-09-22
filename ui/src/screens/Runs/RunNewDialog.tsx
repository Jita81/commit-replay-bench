/**
 * Start a run — POST /runs: kind, builder, model, ladder, the run-level budget, object rungs,
 * builder config, sampling knobs.
 *
 * Navigation
 * ----------
 * What it is:   The `RunNewDialog` (the "Start run" modal) plus the exported vocabulary it
 *               mirrors from the server: `BUDGET_DEFAULTS`, `BLIND_SWEEP_TOOL_CALLS`, the
 *               claude_code model ids, and `budgetFromDraft`.
 * What it does: Builds a `POST /runs` body: for build kinds the builder / model / provider,
 *               the rung LABELS plus object rungs `{builder, model, provider?, budget?}` (the
 *               same model at 25 → 50 → 100 tool calls is the blind budget sweep preset —
 *               the tier every ledger row is stamped with), the run-level caps (only the
 *               typed ones are sent; blank = the builder's default shown), and a validated
 *               builder-config JSON with a one-click "Use my Claude Code login (dev)" toggle.
 *               A non-build kind hides all of that. The executor default shown is the
 *               server's `sandbox_mode` when the viewer may read `/settings`.
 * How:          Local state per field; `parseBuilderConfig` validates the JSON with the
 *               server's rules; `valid` gates the submit; `rungToEntry` and `budgetFromDraft`
 *               emit only what was set; on 201 the caller navigates to the run.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
 * Works with:   ui/src/api/hooks.ts (`useCreateRun`, `useSettings`), ui/src/api/types.ts
 *               (`RunCreateRequest`, `LadderRung`, `RunBudget`), ui/src/lib/jsonObject.ts
 *               (the builder-config rules), src/crb/server/schemas.py (`RunCreateRequest`
 *               validation, `BUDGET_DEFAULTS`), src/crb/builders/base.py (`Budget`
 *               defaults), src/crb/builders/claude_code.py (`DEFAULT_MODEL`, `KNOWN_MODELS`
 *               — mirrored in `CLAUDE_CODE_MODELS`), ui/src/screens/Runs/RunsPage.tsx and
 *               ui/src/screens/Repos/RepoDetail.tsx (the openers)
 * Tested by:    ui/src/screens/Runs/RunNewDialog.test.tsx, ui/e2e/walkthrough/03-mine.spec.ts
 *               (`startRun`), ui/e2e/walkthrough/09-budget-sweep.spec.ts (the sweep preset
 *               end to end)
 * Touch when:   a builder is registered or a model id changes (src/crb/builders/*) — update
 *               `BUILDER_NAMES` / `CLAUDE_CODE_MODELS` and `BUILDER_CONFIG_HELP`; a budget
 *               field is added (`RunBudget` in ui/src/api/types.ts first); never for a new
 *               repository.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useCreateRun, useRepos, useSettings } from '../../api/hooks'
import { RUN_KINDS, type GradeMode, type LadderEntry, type LadderRung, type Run, type RunBudget, type RunCreateRequest, type RunKind } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { Hint } from '../../components/Hint'
import { useAuth } from '../../lib/auth'
import { formatJsonObject, parseBuilderConfig } from '../../lib/jsonObject'

/** `crb.builders._REGISTRY` — the builder names a rung may name. (`/settings.builders` lists
 * CREDENTIAL probes — anthropic, cerebras, claude_code_cli … — not these names.) */
const BUILDER_NAMES = ['claude_code', 'openai_agent', 'editblock'] as const

/** `crb.builders.claude_code.DEFAULT_MODEL` / `KNOWN_MODELS` — the ids the adapter knows. */
export const CLAUDE_CODE_DEFAULT_MODEL = 'claude-sonnet-5'
export const CLAUDE_CODE_MODELS = ['claude-sonnet-5', 'claude-opus-5', 'claude-haiku-4-5', 'claude-opus-4-8'] as const

/**
 * `crb.builders.base.Budget` defaults (= `crb.server.schemas.BUDGET_DEFAULTS`): what an
 * attempt gets when neither the run nor its rung sets a cap. `0` tokens / `$0` = no cap.
 */
export const BUDGET_DEFAULTS: Required<RunBudget> = { max_turns: 25, max_tool_calls: 25, max_tokens: 0, max_cost_usd: 0, wall_clock_s: 900 }

/** The "Blind budget sweep" preset: one model, escalating tool-call caps, one attempt per rung until clean. */
export const BLIND_SWEEP_TOOL_CALLS = [25, 50, 100] as const

/** The five cap fields of `RunBudget`. */
type BudgetKey = keyof RunBudget
/** The caps as typed (text; blank = inherit). */
type BudgetDraft = Record<BudgetKey, string>
/** Form order of the caps. */
const BUDGET_KEYS: BudgetKey[] = ['max_turns', 'max_tool_calls', 'max_tokens', 'max_cost_usd', 'wall_clock_s']
/** Labels per cap. */
const BUDGET_LABELS: Record<BudgetKey, string> = {
  max_turns: 'Max turns',
  max_tool_calls: 'Max tool calls',
  max_tokens: 'Max tokens',
  max_cost_usd: 'Max cost (USD)',
  wall_clock_s: 'Wall clock (s)',
}
/** Nothing typed. */
const EMPTY_BUDGET: BudgetDraft = { max_turns: '', max_tool_calls: '', max_tokens: '', max_cost_usd: '', wall_clock_s: '' }

/** A rung row in the editor: identity + the tier caps (tool calls / turns / wall clock). */
interface RungDraft {
  builder: string
  model: string
  provider: string
  max_tool_calls: string
  max_turns: string
  wall_clock_s: string
}

/** Only the caps that were typed, as numbers; `undefined` when nothing was set. */
export function budgetFromDraft(draft: Partial<BudgetDraft>): RunBudget | undefined {
  const out: RunBudget = {}
  for (const key of BUDGET_KEYS) {
    const raw = (draft[key] ?? '').trim()
    if (raw === '') continue
    const n = Number(raw)
    if (!Number.isFinite(n)) continue
    out[key] = n
  }
  return Object.keys(out).length ? out : undefined
}

/** A draft → the object rung sent: trimmed identity, provider only if set, budget only for typed caps. */
function rungToEntry(r: RungDraft): LadderRung {
  const rung: LadderRung = { builder: r.builder.trim(), model: r.model.trim() }
  if (r.provider.trim()) rung.provider = r.provider.trim()
  const budget = budgetFromDraft({ max_tool_calls: r.max_tool_calls, max_turns: r.max_turns, wall_clock_s: r.wall_clock_s })
  if (budget) rung.budget = budget
  return rung
}

interface Props {
  open: boolean
  onClose: () => void
  repo?: string
  initialKind?: RunKind
  onCreated?: (run: Run) => void
}

/** One sentence per run kind, shown under the Kind select. */
const KIND_HELP: Record<RunKind, string> = {
  mine: 'Walk history for replayable commits (RED at parent, GREEN with the commit).',
  replay: 'Sighted replay: the builder sees the target tests; graded under four belts.',
  blind: 'Blind replay: the builder sees only the parent + a description; tests are overlaid at grade time.',
  oracle: 'Measure oracle strength (mutation kill-rate) per task.',
  controls: 'Run the negative-control matrix (gold, noop, tamper, stub, …).',
  label: 'Label mined tasks with an intent class (a model reads the diff; never a grade).',
  factory: 'Work the frozen backlog: readiness → RED proof → build → route-gated delivery → review.',
  probe: 'Prove the toolchain on a known-green scope.',
}

/** The kinds that need a builder (and show the builder / ladder / budget block). */
const BUILD_KINDS: RunKind[] = ['replay', 'blind']

/** The constructor keys each builder accepts, for the builder-config hint. */
const BUILDER_CONFIG_HELP: Record<string, string> = {
  claude_code: 'claude_code keys: auth ("api_key" — production, --bare, needs ANTHROPIC_API_KEY on the worker; "cli" — the operator’s own CLI login, developer/evaluation only), effort, bare, keep_transcript, extra_args.',
  openai_agent: 'openai_agent keys: endpoint, temperature, max_tokens, keep_transcript (see the adapter).',
  editblock: 'editblock keys: endpoint, temperature, max_tokens (see the adapter).',
}

/**
 * `POST /runs` — kind / mode / builder / model / ladder, the sampling knobs, an optional
 * builder config (constructor overrides applied to every rung), the run-level **budget**
 * (five caps; blank = the builder's default) and a **ladder editor** that adds object
 * rungs `{builder, model, provider?, budget?}` — the same model at an escalating budget
 * is a ladder (preset: blind budget sweep 25 → 50 → 100 tool calls). The executor default
 * shown is the server’s `sandbox_mode` when the viewer may read `/settings` (admin);
 * otherwise it reads "server default".
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
  const [rungs, setRungs] = useState<RungDraft[]>([])
  const [budget, setBudget] = useState<BudgetDraft>(EMPTY_BUDGET)
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
  const isClaudeCode = builder === 'claude_code'
  /** The identity a new rung starts from: the run's builder + model (claude_code's default when blank). */
  const identityModel = model || (isClaudeCode ? CLAUDE_CODE_DEFAULT_MODEL : '')
  const rungsComplete = rungs.every((r) => r.builder.trim() && r.model.trim())
  const labels = ladder
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const ladderEmpty = needsBuilder && labels.length === 0 && rungs.length === 0
  const valid = repo && (!needsBuilder || (builder && cfg.ok && rungsComplete && !ladderEmpty))
  const serverExecutor = settings.data?.sandbox_mode || ''
  const builders = settings.data?.builders ?? []
  const cliLogin = cfg.ok && cfg.value.auth === 'cli'

  /** One click: `{"auth": "cli"}` in the builder config (merged with whatever else is there). */
  const toggleCliLogin = (on: boolean) => {
    if (!cfg.ok) return
    const next = { ...cfg.value }
    if (on) next.auth = 'cli'
    else delete next.auth
    setBuilderConfig(formatJsonObject(next))
  }

  const newRung = (caps: Partial<Pick<RungDraft, 'max_tool_calls' | 'max_turns' | 'wall_clock_s'>> = {}): RungDraft => ({
    builder,
    model: identityModel,
    provider,
    max_tool_calls: '',
    max_turns: '',
    wall_clock_s: '',
    ...caps,
  })
  const addRung = () => setRungs((rs) => [...rs, newRung()])
  const removeRung = (i: number) => setRungs((rs) => rs.filter((_, k) => k !== i))
  const updateRung = (i: number, patch: Partial<RungDraft>) => setRungs((rs) => rs.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  /** The preset REPLACES the ladder: the three rungs are the whole experiment, so the label list is cleared. */
  const applyBlindSweep = () => {
    setRungs(BLIND_SWEEP_TOOL_CALLS.map((n) => newRung({ max_tool_calls: String(n) })))
    setLadder('')
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const body: RunCreateRequest = { repo, kind }
    if (needsBuilder) {
      body.mode = mode
      body.builder = builder
      if (model) body.model = model
      if (provider) body.provider = provider
      const entries: LadderEntry[] = [...labels, ...rungs.map(rungToEntry)]
      if (entries.length) body.ladder = entries
      if (cfg.ok && Object.keys(cfg.value).length) body.builder_config = cfg.value
      const caps = budgetFromDraft(budget)
      if (caps) body.budget = caps
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
          <Button type="submit" form="run-new-form" variant="filled" disabled={!valid || create.isPending} hint="button.run_new.queue">
            {create.isPending ? 'Queuing…' : 'Queue run'}
          </Button>
        </>
      }
    >
      <form id="run-new-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Repo" hint="field.run_new.repo" required value={repo} onChange={(e) => setRepo(e.target.value)} disabled={Boolean(presetRepo)}>
          <option value="">Choose…</option>
          {(repos.data?.items ?? []).map((r) => (
            <option key={r.name} value={r.name}>
              {r.name}
            </option>
          ))}
          {presetRepo && !repos.data?.items.some((r) => r.name === presetRepo) && <option value={presetRepo}>{presetRepo}</option>}
        </SelectField>
        <SelectField label="Kind" hint="field.run_new.kind" required value={kind} onChange={(e) => setKind(e.target.value as RunKind)} description={KIND_HELP[kind]}>
          {RUN_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </SelectField>
        {needsBuilder && (
          <>
            <TextField label="Mode" hint="field.run_new.mode" value={mode} readOnly description="Derived from kind: replay = sighted, blind = blind" />
            <TextField
              label="Builder"
              hint="field.run_new.builder"
              required
              value={builder}
              onChange={(e) => setBuilder(e.target.value)}
              list="crb-builders"
              placeholder="editblock · openai_agent · claude_code"
              description={
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
              hint="field.run_new.model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              list={isClaudeCode ? 'crb-claude-models' : undefined}
              placeholder={isClaudeCode ? CLAUDE_CODE_DEFAULT_MODEL : 'e.g. gpt-oss-120b'}
              description={isClaudeCode ? `Default ${CLAUDE_CODE_DEFAULT_MODEL} (the census’s measured path); claude-opus-5 is selectable` : undefined}
            />
            {isClaudeCode && (
              <datalist id="crb-claude-models">
                {CLAUDE_CODE_MODELS.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            )}
            <TextField label="Provider" hint="field.run_new.provider" value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="e.g. cerebras" />
            <TextField
              label="Ladder"
              hint="field.run_new.ladder"
              value={ladder}
              onChange={(e) => setLadder(e.target.value)}
              error={ladderEmpty ? 'A run needs at least one rung: a label here or a rung below' : undefined}
              description="Comma-separated rung labels; each rung is one attempt (r1 = this builder + model, or builder:model[:provider]). Object rungs below are appended in order."
            />
            {isClaudeCode && (
              <Hint as="div" id="field.run_new.cli_login" className="flex items-start gap-2 rounded-[var(--radius-control)] border border-border bg-surface-container px-3 py-2 sm:col-span-2">
                <input id="crb-cli-login" type="checkbox" className="mt-0.5" checked={cliLogin} disabled={!cfg.ok} onChange={(e) => toggleCliLogin(e.target.checked)} />
                <label htmlFor="crb-cli-login" className="text-xs text-on-surface-body">
                  <span className="font-semibold">Use my Claude Code login (dev)</span> — sets <code>{'{"auth": "cli"}'}</code>: the worker runs <code>claude</code> without <code>--bare</code> on the operator’s own subscription login instead of <code>ANTHROPIC_API_KEY</code>. Developer / evaluation only — the target repo’s CLAUDE.md is auto-discovered in this mode (its project settings and hooks are still excluded).
                </label>
              </Hint>
            )}

            <fieldset className="space-y-2 rounded-[var(--radius-control)] border border-border p-3 sm:col-span-2" data-testid="run-budget">
              <legend className="px-1 text-xs font-semibold text-on-surface-body">Budget (per attempt)</legend>
              <p className="text-xs text-on-surface-muted">
                Blank = the builder’s default (shown). A rung’s own budget overrides these for that rung; 0 tokens / $0 = no cap. Every ledger row is stamped with the tier it ran under (
                <code>tool calls/turns/wall clock</code>) — a blind rate quoted without its budget tier is not a claim.
              </p>
              <div className="grid gap-3 sm:grid-cols-5">
                {BUDGET_KEYS.map((key) => (
                  <TextField
                    key={key}
                    label={BUDGET_LABELS[key]}
                    hint="field.run_new.budget"
                    type="number"
                    min={key === 'max_tokens' || key === 'max_cost_usd' ? 0 : 1}
                    step={key === 'max_cost_usd' ? '0.01' : 1}
                    value={budget[key]}
                    onChange={(e) => setBudget((b) => ({ ...b, [key]: e.target.value }))}
                    placeholder={String(BUDGET_DEFAULTS[key])}
                    description={`default ${BUDGET_DEFAULTS[key]}${key === 'max_tokens' || key === 'max_cost_usd' ? ' (no cap)' : ''}`}
                  />
                ))}
              </div>
            </fieldset>

            <fieldset className="space-y-2 rounded-[var(--radius-control)] border border-border p-3 sm:col-span-2" data-testid="run-ladder">
              <legend className="px-1 text-xs font-semibold text-on-surface-body">Ladder rungs (object rungs, in order)</legend>
              <p className="text-xs text-on-surface-muted">
                Each rung is one attempt — the next rung runs only when the previous one is not clean. A rung’s blank caps inherit the run budget above; token and cost caps are the run’s. The same
                model at an escalating budget is a budget ladder.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={addRung} disabled={!builder || !identityModel} hint="button.run_new.add_rung">
                  Add rung
                </Button>
                <Button size="sm" onClick={applyBlindSweep} disabled={!builder || !identityModel} hint="button.run_new.sweep">
                  Blind budget sweep 25 → 50 → 100 tool calls
                </Button>
                {rungs.length > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => setRungs([])} hint="button.run_new.clear_rungs">
                    Clear rungs
                  </Button>
                )}
              </div>
              {!builder || !identityModel ? <p className="text-xs text-on-surface-muted">Name a builder and a model to add rungs.</p> : null}
              {rungs.length > 0 && (
                <ol className="space-y-2" aria-label="Ladder rungs">
                  {rungs.map((r, i) => (
                    <li key={i} className="grid items-end gap-2 rounded-[var(--radius-control)] bg-surface-container p-2 sm:grid-cols-7" data-testid={`rung-${i}`}>
                      <div className="text-xs font-semibold text-on-surface-body sm:col-span-7">
                        Rung {i + 1}
                        <span className="ml-2 font-normal text-on-surface-muted">
                          tier {r.max_tool_calls || budget.max_tool_calls || BUDGET_DEFAULTS.max_tool_calls}/{r.max_turns || budget.max_turns || BUDGET_DEFAULTS.max_turns}/
                          {r.wall_clock_s || budget.wall_clock_s || BUDGET_DEFAULTS.wall_clock_s}
                        </span>
                      </div>
                      <TextField label={`Rung ${i + 1} builder`} hint="field.run_new.rung" required value={r.builder} onChange={(e) => updateRung(i, { builder: e.target.value })} list="crb-builders" />
                      <TextField label={`Rung ${i + 1} model`} hint="field.run_new.rung" required value={r.model} onChange={(e) => updateRung(i, { model: e.target.value })} />
                      <TextField label={`Rung ${i + 1} provider`} hint="field.run_new.rung" value={r.provider} onChange={(e) => updateRung(i, { provider: e.target.value })} placeholder="run’s" />
                      <TextField label={`Rung ${i + 1} tool calls`} hint="field.run_new.rung" type="number" min={1} value={r.max_tool_calls} onChange={(e) => updateRung(i, { max_tool_calls: e.target.value })} placeholder="inherit" />
                      <TextField label={`Rung ${i + 1} turns`} hint="field.run_new.rung" type="number" min={1} value={r.max_turns} onChange={(e) => updateRung(i, { max_turns: e.target.value })} placeholder="inherit" />
                      <TextField label={`Rung ${i + 1} wall clock (s)`} hint="field.run_new.rung" type="number" min={1} value={r.wall_clock_s} onChange={(e) => updateRung(i, { wall_clock_s: e.target.value })} placeholder="inherit" />
                      <Button size="sm" variant="ghost" onClick={() => removeRung(i)} aria-label={`Remove rung ${i + 1}`} hint="button.run_new.remove_rung">
                        Remove
                      </Button>
                    </li>
                  ))}
                </ol>
              )}
            </fieldset>

            <div className="sm:col-span-2">
              <TextArea
                label="Builder config (JSON, optional)"
                hint="field.run_new.builder_config"
                value={builderConfig}
                onChange={(e) => setBuilderConfig(e.target.value)}
                rows={4}
                spellCheck={false}
                className="font-mono text-xs"
                placeholder={'{\n  "auth": "cli",\n  "effort": "high"\n}'}
                error={cfgError}
                description={`Constructor overrides applied to every rung and stamped into the run’s apparatus. ${BUILDER_CONFIG_HELP[builder] ?? 'model / provider and credential keys are refused — identity comes from the ladder, secrets from the worker’s environment.'}`}
              />
            </div>
          </>
        )}
        <TextField label="Task limit" hint="field.run_new.limit" type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} description="Leave blank for all tasks" />
        <SelectField label="Pool" hint="field.run_new.pool" value={pool} onChange={(e) => setPool(e.target.value)}>
          <option value="">all</option>
          <option value="standard">standard</option>
          <option value="hard">hard</option>
        </SelectField>
        <SelectField label="Executor" hint="field.run_new.executor" value={executor} onChange={(e) => setExecutor(e.target.value)} description="Docker fails closed when unavailable; there is no local fallback">
          <option value="">{serverExecutor ? `server default (${serverExecutor})` : 'server default'}</option>
          <option value="docker">docker (sandboxed)</option>
          <option value="local">local</option>
        </SelectField>
        <TextField label="Timeout (s)" hint="field.run_new.timeout" type="number" min={1} value={timeout} onChange={(e) => setTimeoutS(e.target.value)} description="Per test run; a timeout is a failure, never a pass" />
        {create.isError && (
          <div className="sm:col-span-2">
            <ErrorState compact error={create.error} />
          </div>
        )}
      </form>
    </Dialog>
  )
}
