import { useState, type FormEvent } from 'react'
import { useCreateRepo } from '../../api/hooks'
import { LANGUAGES, RUNNERS, type Language, type RepoCreateRequest, type Runner } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { SelectField, TextField } from '../../components/Field'
import { ErrorState } from '../../components/ErrorState'

interface Props {
  open: boolean
  onClose: () => void
  onCreated?: (name: string) => void
}

/** `POST /repos` — the minimum to register a repo; layout fields optional. */
export function RepoNewDialog({ open, onClose, onCreated }: Props) {
  const create = useCreateRepo()
  const [name, setName] = useState('')
  const [language, setLanguage] = useState<Language>('python')
  const [source, setSource] = useState<'clone_path' | 'url'>('clone_path')
  const [location, setLocation] = useState('')
  const [runner, setRunner] = useState<Runner | ''>('')
  const [srcPrefix, setSrcPrefix] = useState('')
  const [testPrefix, setTestPrefix] = useState('')
  const [ext, setExt] = useState('')
  const [probe, setProbe] = useState('')
  const [sandboxImage, setSandboxImage] = useState('')

  const nameOk = /^[a-z0-9][a-z0-9._-]*$/.test(name)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const body: RepoCreateRequest = { name, language }
    if (source === 'clone_path') body.clone_path = location
    else body.url = location
    if (runner) body.runner = runner
    if (srcPrefix) body.src_prefix = srcPrefix
    if (testPrefix) body.test_prefix = testPrefix
    if (ext) body.ext = ext
    if (probe) body.probe = probe
    if (sandboxImage) body.sandbox_image = sandboxImage
    create.mutate(body, {
      onSuccess: (repo) => {
        onCreated?.(repo.name)
        onClose()
      },
    })
  }

  return (
    <Dialog
      open={open}
      title="Add a repository"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="repo-new-form" variant="filled" disabled={!nameOk || !location || create.isPending}>
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
        <SelectField label="Language" required value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </SelectField>
        <SelectField label="Source" value={source} onChange={(e) => setSource(e.target.value as 'clone_path' | 'url')}>
          <option value="clone_path">Local clone path (on the server)</option>
          <option value="url">Git URL</option>
        </SelectField>
        <TextField
          label={source === 'clone_path' ? 'Clone path' : 'Git URL'}
          required
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder={source === 'clone_path' ? '/srv/repos/sqlalchemy' : 'https://…/repo.git'}
        />
        <SelectField label="Runner" value={runner} onChange={(e) => setRunner(e.target.value as Runner | '')} hint="Default: by language">
          <option value="">(default for language)</option>
          {RUNNERS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </SelectField>
        <TextField label="Probe scope" value={probe} onChange={(e) => setProbe(e.target.value)} hint="A known-green test scope to prove the toolchain" />
        <TextField label="Source prefix" value={srcPrefix} onChange={(e) => setSrcPrefix(e.target.value)} placeholder="src/" />
        <TextField label="Test prefix" value={testPrefix} onChange={(e) => setTestPrefix(e.target.value)} placeholder="tests/" />
        <TextField label="Extension" value={ext} onChange={(e) => setExt(e.target.value)} placeholder=".py" />
        <TextField label="Sandbox image" value={sandboxImage} onChange={(e) => setSandboxImage(e.target.value)} hint="Container image with toolchain + deps" />
        {create.isError && (
          <div className="sm:col-span-2">
            <ErrorState compact error={create.error} />
          </div>
        )}
      </form>
    </Dialog>
  )
}
