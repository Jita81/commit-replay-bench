/**
 * Add a repository — POST /repos with a preset, a URL or clone path, layout, belt scope, probe and
 * runner options.
 *
 * Navigation
 * ----------
 * What it is:   The `RepoNewDialog` (the "Add repo" modal) and `URL_RE`, the clone-policy
 *               check.
 * What it does: Builds a `POST /repos` body: a preset fills the layout for a well-known shape
 *               (every field stays editable); a Git URL is checked against the server's clone
 *               policy (`https://`, `ssh://`, `user@host:path`; `file://` only under the
 *               server's dev switch) so a refusal is immediate — a bare local path is
 *               registered as a clone path, never cloned; runner options go through the
 *               shared editor with the runner's own keys. Only set fields are sent. A URL-only
 *               repo is cloned by the worker on its first run.
 * How:          Local state per field; `valid` gates the submit; `body()` assembles the
 *               request; on 201 the caller navigates to the new repo page.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useCreateRepo`), ui/src/api/types.ts
 *               (`RepoCreateRequest`), ui/src/lib/repoPresets.ts (`REPO_PRESETS`),
 *               ui/src/screens/Repos/runnerOpts.ts and ui/src/screens/Repos/RunnerOptsEditor.tsx
 *               (the options), ui/src/screens/Repos/repoConfigModel.ts (`BELT_HELP`,
 *               `parseScopeList`), src/crb/server/routes/repos.py (the URL policy this mirrors)
 * Tested by:    ui/src/screens/Repos/RepoNewDialog.test.tsx,
 *               ui/e2e/walkthrough/02-repo-onboard.spec.ts
 * Touch when:   the server's clone-URL policy changes (docs/API.md "POST /repos") — update
 *               `URL_RE` and its hint with it; a new `RepoConfig` field gets a control here
 *               AND in ui/src/screens/Repos/RepoConfigForm.tsx. For a new repository: use
 *               the dialog; add a preset in ui/src/lib/repoPresets.ts if its layout is new.
 */
import { useState, type FormEvent } from 'react'
import { useCreateRepo } from '../../api/hooks'
import { LANGUAGES, type BeltScope, type Language, type RepoCreateRequest, type Runner } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { SelectField, TextField } from '../../components/Field'
import { ErrorState } from '../../components/ErrorState'
import { REPO_PRESETS, findPreset } from '../../lib/repoPresets'
import { BELT_HELP, parseScopeList, type BeltPolicy } from './repoConfigModel'
import { DEFAULT_RUNNER, runnersFor, validateRunnerOpts } from './runnerOpts'
import { RunnerOptsEditor } from './RunnerOptsEditor'

interface Props {
  open: boolean
  onClose: () => void
  onCreated?: (name: string) => void
}

/** Where the repo comes from: a URL the worker clones, or a clone already on the server host. */
type Source = 'url' | 'clone_path'

export { parseScopeList }

/**
 * `https://…`, `ssh://…`, `user@host:path` — the server’s clone policy, mirrored for
 * immediate feedback — plus `file://…`, which the server refuses unless it runs with
 * the developer switch `CRB_ALLOW_LOCAL_CLONE=1` (its 422 is rendered as-is). Bare
 * local paths and `http://` are refused here because no server ever accepts them.
 */
const URL_RE = /^(https:\/\/[^\s/@]+\/\S+|ssh:\/\/\S+\/\S+|file:\/\/\/\S+|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^/\s]\S*)$/i

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
  const [runnerOpts, setRunnerOpts] = useState<Record<string, unknown>>({})
  const [runnerOptsJsonError, setRunnerOptsJsonError] = useState<string | undefined>(undefined)

  const nameOk = /^[a-z0-9][a-z0-9._-]*$/.test(name)
  const locationTrim = location.trim()
  const locationError =
    locationTrim && source === 'url' && !URL_RE.test(locationTrim)
      ? 'Use https://host/path, ssh://host/path or user@host:path (a local path is registered as a clone path, never cloned; file:// needs CRB_ALLOW_LOCAL_CLONE=1 on the server)'
      : undefined
  const effectiveRunner: Runner = runner || DEFAULT_RUNNER[language]
  const optErrors = validateRunnerOpts(effectiveRunner, runnerOpts)
  const optsOk = !runnerOptsJsonError && Object.keys(optErrors).length === 0
  const beltListError = beltPolicy === 'LIST' && parseScopeList(beltList).length === 0 ? 'List at least one runner scope' : undefined
  const valid = nameOk && Boolean(locationTrim) && !locationError && optsOk && !beltListError

  const changeLanguage = (l: Language) => {
    setLanguage(l)
    if (runner && !runnersFor(l).includes(runner)) setRunner('')
  }

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
    setRunnerOpts({ ...p.runner_opts })
  }

  const body = (): RepoCreateRequest | null => {
    if (!valid) return null
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
    if (Object.keys(runnerOpts).length) req.runner_opts = runnerOpts
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
          <Button type="submit" form="repo-new-form" variant="filled" disabled={!valid || create.isPending} hint="button.repo_new.submit">
            {create.isPending ? 'Adding…' : 'Add repo'}
          </Button>
        </>
      }
    >
      <form id="repo-new-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Name"
          hint="field.repo_new.name"
          required
          value={name}
          onChange={(e) => setName(e.target.value.trim())}
          description="Lowercase ledger key, e.g. sqlalchemy"
          error={name && !nameOk ? 'Lowercase letters, digits, . _ - only' : undefined}
        />
        <SelectField label="Preset" hint="field.repo_new.preset" value={preset} onChange={(e) => applyPreset(e.target.value)} description={presetInfo?.description ?? 'Fills the layout fields for a well-known project shape; every field stays editable'}>
          <option value="">(none — fill the layout by hand)</option>
          {REPO_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Language" hint="field.repo_new.language" required value={language} onChange={(e) => changeLanguage(e.target.value as Language)}>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </SelectField>
        <SelectField label="Runner" hint="field.repo_new.runner" value={runner} onChange={(e) => setRunner(e.target.value as Runner | '')} description={`Default: ${DEFAULT_RUNNER[language]}. Runners for ${language}: ${runnersFor(language).join(', ')}`}>
          <option value="">(default for language)</option>
          {runnersFor(language).map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </SelectField>
        <SelectField label="Source" hint="field.repo_new.source" value={source} onChange={(e) => setSource(e.target.value as Source)} description={source === 'url' ? 'The worker clones it (full history) on the repo’s first run' : 'An existing git clone on the server host'}>
          <option value="url">Git URL (https / ssh)</option>
          <option value="clone_path">Local clone path (on the server)</option>
        </SelectField>
        <TextField
          label={source === 'clone_path' ? 'Clone path' : 'Git URL'}
          hint="field.repo_new.location"
          required
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder={source === 'clone_path' ? '/srv/repos/sqlalchemy' : 'https://github.com/org/repo.git'}
          error={locationError}
        />
        <TextField label="Source prefix" hint="field.repo_new.src_prefix" value={srcPrefix} onChange={(e) => setSrcPrefix(e.target.value)} placeholder="src/" description="A file is source if it starts here (empty = anything outside the test prefix)" />
        <TextField label="Test prefix" hint="field.repo_new.test_prefix" value={testPrefix} onChange={(e) => setTestPrefix(e.target.value)} placeholder="tests/" description="A file is a test if it starts here (Go/Rust use their conventions)" />
        <TextField label="Extension" hint="field.repo_new.ext" value={ext} onChange={(e) => setExt(e.target.value)} placeholder=".py" description="Default: by language" />
        <SelectField label="Belt scope" hint="field.repo_new.belt_scope" value={beltPolicy} onChange={(e) => setBeltPolicy(e.target.value as BeltPolicy)} description={BELT_HELP[beltPolicy]}>
          <option value="TARGET_ONLY">TARGET_ONLY</option>
          <option value="AFFECTED_DIRS">AFFECTED_DIRS</option>
          <option value="BARE">BARE</option>
          <option value="LIST">Explicit scopes…</option>
        </SelectField>
        {beltPolicy === 'LIST' && (
          <TextField label="Belt scopes" hint="field.repo_new.belt_list" required value={beltList} onChange={(e) => setBeltList(e.target.value)} placeholder="tests/, tests/acceptance/" error={beltList ? beltListError : undefined} description="Comma-separated runner scopes" />
        )}
        <TextField label="Probe scope" hint="field.repo_new.probe" value={probe} onChange={(e) => setProbe(e.target.value)} placeholder="tests/test_smoke.py" description="A known-green test scope to prove the toolchain (repo-specific; never filled by a preset)" />
        <TextField label="Sandbox image" hint="field.repo_new.sandbox_image" value={sandboxImage} onChange={(e) => setSandboxImage(e.target.value)} placeholder="ghcr.io/org/repo-toolchain:2026-09" description="Container image with toolchain + deps; the docker executor fails closed without one" />
        <div className="sm:col-span-2">
          <RunnerOptsEditor
            runner={effectiveRunner}
            value={runnerOpts}
            onChange={setRunnerOpts}
            errors={optErrors}
            onJsonError={setRunnerOptsJsonError}
            initialMode="json"
            jsonRows={5}
            jsonPlaceholder={'{\n  "pythonpath_suffix": "/src",\n  "pip": ["pytest", "-r", "requirements/test.txt"]\n}'}
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
