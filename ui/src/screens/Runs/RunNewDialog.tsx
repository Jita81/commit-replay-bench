import { useEffect, useState, type FormEvent } from 'react'
import { useCreateRun, useRepos } from '../../api/hooks'
import { RUN_KINDS, type GradeMode, type Run, type RunCreateRequest, type RunKind } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextField } from '../../components/Field'

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

/** `POST /runs` — kind / mode / builder / model / ladder and the sampling knobs. */
export function RunNewDialog({ open, onClose, repo: presetRepo, initialKind = 'replay', onCreated }: Props) {
  const repos = useRepos()
  const create = useCreateRun()
  const [repo, setRepo] = useState(presetRepo ?? '')
  const [kind, setKind] = useState<RunKind>(initialKind)
  const [builder, setBuilder] = useState('')
  const [model, setModel] = useState('')
  const [provider, setProvider] = useState('')
  const [ladder, setLadder] = useState('r1')
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
  const valid = repo && (!needsBuilder || builder)

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
            <TextField label="Builder" required value={builder} onChange={(e) => setBuilder(e.target.value)} placeholder="editblock · openai_agent · claude_code" hint="A builder registered on the server (see Settings)" />
            <TextField label="Model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. gpt-oss-120b" />
            <TextField label="Provider" value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="e.g. cerebras" />
            <TextField label="Ladder" value={ladder} onChange={(e) => setLadder(e.target.value)} hint="Comma-separated rung labels; each rung is one attempt (r1, r2 …)" />
          </>
        )}
        <TextField label="Task limit" type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} hint="Leave blank for all tasks" />
        <SelectField label="Pool" value={pool} onChange={(e) => setPool(e.target.value)}>
          <option value="">all</option>
          <option value="standard">standard</option>
          <option value="hard">hard</option>
        </SelectField>
        <SelectField label="Executor" value={executor} onChange={(e) => setExecutor(e.target.value)} hint="Docker fails closed when unavailable">
          <option value="">server default</option>
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
