import { useState, type FormEvent } from 'react'
import { useCreateRepo } from '../../api/hooks'
import { LANGUAGES, RUNNERS, type BeltScope, type Language, type RepoCreateRequest, type Runner } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { ErrorState } from '../../components/ErrorState'
import { formatJsonObject, parseJsonObject } from '../../lib/jsonObject'
import { REPO_PRESETS, findPreset } from '../../lib/repoPresets'

interface Props {
  open: boolean
  onClose: () => void
  onCreated?: (name: string) => void
}

type Source = 'url' | 'clone_path'
type BeltPolicy = 'TARGET_ONLY' | 'AFFECTED_DIRS' | 'BARE' | 'LIST'

const BELT_HELP: Record<BeltPolicy, string> = {
  TARGET_ONLY: 'Regression belt runs only the target tests (weakest; while calibrating a large suite).',
  AFFECTED_DIRS: 'Regression belt runs every test in the target tests’ directories.',
  BARE: 'Regression belt runs the runner’s default discovery (the whole suite).',
  LIST: 'Regression belt runs exactly these runner scopes, comma-separated.',
}

/**
 * `https://…`, `ssh://…`, `user@host:path` — the server’s clone policy, mirrored for
 * immediate feedback — plus `file://…`, which the server refuses unless it runs with
 * the developer switch `CRB_ALLOW_LOCAL_CLONE=1` (its 422 is rendered as-is). Bare
 * local paths and `http://` are refused here because no server ever accepts them.
 */
const URL_RE = /^(https:\/\/[^\s/@]+\/\S+|ssh:\/\/\S+\/\S+|file:\/\/\/\S+|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^/\s]\S*)$/i

export function parseScopeList(text: string): string[] {
  return text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

/**
 * `POST /repos` — everything a `RepoConfig` carries: location (URL or an existing
 * clone on the server), layout, belt scope, probe, sandbox image and free-form
 * runner options. A preset fills the layout for a well-known shape; a URL-only repo
 * is cloned by the worker on its first run.
 */
export function RepoNewDialog({ open, onClose, onCreated }: Props) {
  const create = useCreateRepo()
  const [name, setName] = useState('')
  const [language, setLanguage] = useState<Language>('python')
  const [preset, setPreset] = useState('')
  const [source, setSource] = useState<Source>('url')
  const [location, setLocation] = useState('')
  const [runner, setRunner] = useState<Runner | ''>('')
  const [srcPrefix, setSrcPrefix] = useState('')
  const [testPrefix, setTestPrefix] = useState('')
  const [ext, setExt] = useState('')
  const [beltPolicy, setBeltPolicy] = useState<BeltPolicy>('TARGET_ONLY')
  const [beltList, setBeltList] = useState('')
  const [probe, setProbe] = useState('')
  const [sandboxImage, setSandboxImage] = useState('')
  const [runnerOpts, setRunnerOpts] = useState('')

  const nameOk = /^[a-z0-9][a-z0-9._-]*$/.test(name)
  const locationTrim = location.trim()
  const locationError =
    locationTrim && source === 'url' && !URL_RE.test(locationTrim)
      ? 'Use https://host/path, ssh://host/path or user@host:path (a local path is registered as a clone path, never cloned; file:// needs CRB_ALLOW_LOCAL_CLONE=1 on the server)'
      : undefined
  const opts = parseJsonObject(runnerOpts)
  const beltListError = beltPolicy === 'LIST' && parseScopeList(beltList).length === 0 ? 'List at least one runner scope' : undefined
  const valid = nameOk && Boolean(locationTrim) && !locationError && opts.ok && !beltListError

  const applyPreset = (id: string) => {
    setPreset(id)
    const p = findPreset(id)
    if (!p) return
    setLanguage(p.language)
    setRunner(p.runner)
    setSrcPrefix(p.src_prefix)
    setTestPrefix(p.test_prefix)
    setExt(p.ext)
    if (Array.isArray(p.belt_scope)) {
      setBeltPolicy('LIST')
      setBeltList(p.belt_scope.join(', '))
    } else {
      setBeltPolicy(p.belt_scope)
    }
    setRunnerOpts(formatJsonObject(p.runner_opts))
  }

  const body = (): RepoCreateRequest | null => {
    if (!valid || !opts.ok) return null
    const req: RepoCreateRequest = { name, language }
    if (source === 'clone_path') req.clone_path = locationTrim
    else req.url = locationTrim
    if (runner) req.runner = runner
    if (srcPrefix) req.src_prefix = srcPrefix
    if (testPrefix) req.test_prefix = testPrefix
    if (ext) req.ext = ext
    const belt: BeltScope = beltPolicy === 'LIST' ? parseScopeList(beltList) : beltPolicy
    req.belt_scope = belt
    if (probe) req.probe = probe
    if (sandboxImage) req.sandbox_image = sandboxImage
    if (Object.keys(opts.value).length) req.runner_opts = opts.value
    return req
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const req = body()
    if (!req) return
    create.mutate(req, {
      onSuccess: (repo) => {
        onCreated?.(repo.name)
        onClose()
      },
    })
  }

  const presetInfo = findPreset(preset)

  return (
    <Dialog
      open={open}
      title="Add a repository"
      onClose={onClose}
      width="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="repo-new-form" variant="filled" disabled={!valid || create.isPending}>
            {create.isPending ? 'Adding…' : 'Add repo'}
          </Button>
        </>
      }
    >
      <form id="repo-new-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Name"
          required
          value={name}
          onChange={(e) => setName(e.target.value.trim())}
          hint="Lowercase ledger key, e.g. sqlalchemy"
          error={name && !nameOk ? 'Lowercase letters, digits, . _ - only' : undefined}
        />
        <SelectField label="Preset" value={preset} onChange={(e) => applyPreset(e.target.value)} hint={presetInfo?.description ?? 'Fills the layout fields for a well-known project shape; every field stays editable'}>
          <option value="">(none — fill the layout by hand)</option>
          {REPO_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Language" required value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </SelectField>
        <SelectField label="Runner" value={runner} onChange={(e) => setRunner(e.target.value as Runner | '')} hint="Default: by language">
          <option value="">(default for language)</option>
          {RUNNERS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </SelectField>
        <SelectField label="Source" value={source} onChange={(e) => setSource(e.target.value as Source)} hint={source === 'url' ? 'The worker clones it (full history) on the repo’s first run' : 'An existing git clone on the server host'}>
          <option value="url">Git URL (https / ssh)</option>
          <option value="clone_path">Local clone path (on the server)</option>
        </SelectField>
        <TextField
          label={source === 'clone_path' ? 'Clone path' : 'Git URL'}
          required
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder={source === 'clone_path' ? '/srv/repos/sqlalchemy' : 'https://github.com/org/repo.git'}
          error={locationError}
        />
        <TextField label="Source prefix" value={srcPrefix} onChange={(e) => setSrcPrefix(e.target.value)} placeholder="src/" hint="A file is source if it starts here (empty = anything outside the test prefix)" />
        <TextField label="Test prefix" value={testPrefix} onChange={(e) => setTestPrefix(e.target.value)} placeholder="tests/" hint="A file is a test if it starts here (Go/Rust use their conventions)" />
        <TextField label="Extension" value={ext} onChange={(e) => setExt(e.target.value)} placeholder=".py" hint="Default: by language" />
        <SelectField label="Belt scope" value={beltPolicy} onChange={(e) => setBeltPolicy(e.target.value as BeltPolicy)} hint={BELT_HELP[beltPolicy]}>
          <option value="TARGET_ONLY">TARGET_ONLY</option>
          <option value="AFFECTED_DIRS">AFFECTED_DIRS</option>
          <option value="BARE">BARE</option>
          <option value="LIST">Explicit scopes…</option>
        </SelectField>
        {beltPolicy === 'LIST' && (
          <TextField label="Belt scopes" required value={beltList} onChange={(e) => setBeltList(e.target.value)} placeholder="tests/, tests/acceptance/" error={beltList ? beltListError : undefined} hint="Comma-separated runner scopes" />
        )}
        <TextField label="Probe scope" value={probe} onChange={(e) => setProbe(e.target.value)} placeholder="tests/test_smoke.py" hint="A known-green test scope to prove the toolchain (repo-specific; never filled by a preset)" />
        <TextField label="Sandbox image" value={sandboxImage} onChange={(e) => setSandboxImage(e.target.value)} placeholder="ghcr.io/org/repo-toolchain:2026-09" hint="Container image with toolchain + deps; the docker executor fails closed without one" />
        <div className="sm:col-span-2">
          <TextArea
            label="Runner options (JSON)"
            value={runnerOpts}
            onChange={(e) => setRunnerOpts(e.target.value)}
            rows={5}
            spellCheck={false}
            className="font-mono text-xs"
            placeholder={'{\n  "pythonpath_suffix": "/src",\n  "pip": ["pytest", "-r", "requirements/test.txt"]\n}'}
            error={opts.ok ? undefined : opts.error}
            hint="A JSON object of runner options: pip / python / pythonpath_suffix (pytest), maven_flags / java_home (maven), mocha_require (mocha), node, go, cargo… Leave empty for none."
          />
        </div>
        {create.isError && (
          <div className="sm:col-span-2">
            <ErrorState compact error={create.error} />
          </div>
        )}
      </form>
    </Dialog>
  )
}
