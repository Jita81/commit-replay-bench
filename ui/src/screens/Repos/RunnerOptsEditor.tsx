/**
 * runner_opts as a runner-specific sub-form with a raw-JSON view that round-trips.
 *
 * Navigation
 * ----------
 * What it is:   The `RunnerOptsEditor`: Form mode (one control per key the runner reads) and
 *               Raw JSON mode (the whole object), sharing one value.
 * What it does: Offers exactly the runner's keys as typed controls, lists any other stored key
 *               as "not read by this runner" (kept on save, removable, editable in JSON), and
 *               lets the operator edit the raw object with live parsing — a parse error is
 *               reported and blocks the switch back to Form, never applied. Keys set to empty
 *               are removed, so a saved config carries no phantom keys.
 * How:          The object is the single source of truth; JSON text is derived from it on
 *               external change (a preset, a reset) but not on the editor's own emissions, so
 *               the operator's formatting survives while they type; `OptControl` renders by
 *               `OptSpec.kind`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/runnerOpts.ts (the specs, coercions and validation),
 *               ui/src/screens/Repos/ListEditors.tsx (list and env kinds),
 *               ui/src/lib/jsonObject.ts (`parseJsonObject`, `formatJsonObject`),
 *               ui/src/screens/Repos/repoConfigModel.ts (`sameJson`),
 *               ui/src/screens/Repos/RepoConfigForm.tsx and ui/src/screens/Repos/RepoNewDialog.tsx
 *               (the two hosts)
 * Tested by:    ui/src/screens/Repos/RepoConfigTab.test.tsx (round-trip, parse error blocks
 *               save), ui/src/screens/Repos/RepoNewDialog.test.tsx,
 *               ui/e2e/walkthrough/repo-config.spec.ts
 * Touch when:   an `OptKind` is added to ui/src/screens/Repos/runnerOpts.ts — add its control
 *               in `OptControl`; never for a new repository.
 */
import { useEffect, useRef, useState } from 'react'
import type { Runner } from '../../api/types'
import { Button } from '../../components/Button'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { formatJsonObject, parseJsonObject } from '../../lib/jsonObject'
import { KeyValueEditor, ListEditor } from './ListEditors'
import { sameJson } from './repoConfigModel'
import { asBool, asEnv, asList, asText, specsFor, unknownKeys, type OptSpec } from './runnerOpts'

/** Form (typed controls) or Raw JSON (the whole object). */
export type OptsMode = 'form' | 'json'

interface Props {
  runner: Runner | ''
  value: Record<string, unknown>
  onChange: (value: Record<string, unknown>) => void
  /** Per-key problems from `validateRunnerOpts` (rendered beside the control). */
  errors?: Record<string, string>
  /** Reported on every keystroke in JSON mode: `undefined` = the text parses to an object. */
  onJsonError?: (error: string | undefined) => void
  disabled?: boolean
  initialMode?: OptsMode
  /** The JSON textarea's label (the create dialog keeps its historical one). */
  jsonLabel?: string
  jsonPlaceholder?: string
  jsonRows?: number
}

/** The one-line explanation shown above the form view. */
const KIND_HELP = 'Only the keys this runner reads are offered; anything else stays untouched and is listed below.'

/**
 * `runner_opts` as a runner-specific sub-form — exactly the keys
 * `crb.core.runners.<runner>` reads — with a raw-JSON view that round-trips: the
 * object is the single source of truth; JSON mode edits it live (a parse error is
 * reported, never applied) and form mode renders it back key by key.
 */
export function RunnerOptsEditor({ runner, value, onChange, errors = {}, onJsonError, disabled, initialMode = 'form', jsonLabel = 'Runner options (JSON)', jsonPlaceholder, jsonRows = 8 }: Props) {
  const [mode, setMode] = useState<OptsMode>(initialMode)
  const [text, setText] = useState(() => formatJsonObject(value))
  const [jsonError, setJsonError] = useState<string | undefined>(undefined)
  const emitted = useRef<Record<string, unknown>>(value)

  // An external change (a preset, a reset after save) re-renders the JSON text; our
  // own emissions do not, so the operator's formatting survives while they type.
  useEffect(() => {
    if (!sameJson(emitted.current, value)) {
      emitted.current = value
      setText(formatJsonObject(value))
      setJsonError(undefined)
      onJsonError?.(undefined)
    }
  }, [value, onJsonError])

  const emit = (next: Record<string, unknown>) => {
    emitted.current = next
    onChange(next)
  }
  const setKey = (key: string, v: unknown) => {
    const next = { ...value }
    if (v === undefined) delete next[key]
    else next[key] = v
    emit(next)
  }

  const switchTo = (m: OptsMode) => {
    if (m === mode) return
    if (m === 'json') {
      setText(formatJsonObject(value))
      setJsonError(undefined)
      onJsonError?.(undefined)
    } else if (jsonError) {
      return // an unparsable draft cannot become a form; the error stays visible
    }
    setMode(m)
  }

  const onText = (t: string) => {
    setText(t)
    const r = parseJsonObject(t)
    if (r.ok) {
      setJsonError(undefined)
      onJsonError?.(undefined)
      if (!sameJson(r.value, value)) emit(r.value)
    } else {
      setJsonError(r.error)
      onJsonError?.(r.error)
    }
  }

  const specs = specsFor(runner)
  const extra = unknownKeys(runner, value)

  return (
    <div className="space-y-3" data-testid="runner-opts">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-on-surface-muted">
          {runner ? (
            <>
              Options read by the <span className="font-mono">{runner}</span> runner. {KIND_HELP}
            </>
          ) : (
            'Pick a runner to see its options.'
          )}
        </div>
        <div role="group" aria-label="Editor view" className="inline-flex overflow-hidden rounded-[var(--radius-control)] border border-border">
          {(['form', 'json'] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => switchTo(m)}
              data-testid={`runner-opts-mode-${m}`}
              className={`h-8 px-3 text-xs font-semibold ${mode === m ? 'bg-primary-container text-primary' : 'bg-surface-container text-on-surface-muted hover:text-on-surface'}`}
            >
              {m === 'form' ? 'Form' : 'Raw JSON'}
            </button>
          ))}
        </div>
      </div>

      {mode === 'json' ? (
        <TextArea
          label={jsonLabel}
          value={text}
          onChange={(e) => onText(e.target.value)}
          rows={jsonRows}
          spellCheck={false}
          disabled={disabled}
          className="font-mono text-xs"
          placeholder={jsonPlaceholder}
          error={jsonError}
          description="The whole runner_opts object, as stored. Edits apply as you type once the JSON parses; switch back to Form to see them key by key."
          data-testid="runner-opts-json"
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {specs.map((spec) => (
            <OptControl key={spec.key} spec={spec} value={value[spec.key]} error={errors[spec.key]} disabled={disabled} onChange={(v) => setKey(spec.key, v)} />
          ))}
          {extra.length > 0 && (
            <div className="sm:col-span-2 space-y-1" data-testid="runner-opts-extra">
              <div className="text-xs font-semibold text-on-surface-body">Not read by the {runner || 'selected'} runner</div>
              <ul className="m-0 list-none space-y-1 p-0">
                {extra.map((k) => (
                  <li key={k} className="flex items-center gap-2 text-xs">
                    <code className="font-mono">{k}</code>
                    <span className="min-w-0 flex-1 truncate font-mono text-on-surface-muted" title={JSON.stringify(value[k])}>
                      {JSON.stringify(value[k])}
                    </span>
                    {!disabled && (
                      <Button size="sm" onClick={() => setKey(k, undefined)} aria-label={`Remove ${k}`} data-testid={`runner-opts-extra-remove-${k}`}>
                        Remove
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
              <div className="text-xs text-on-surface-muted">Kept as they are on save (a different runner may read them; `post_create` hooks are read by the workspace). Edit them in Raw JSON.</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** One control per `OptKind`; an emptied control removes the key rather than storing `''`. */
function OptControl({ spec, value, error, disabled, onChange }: { spec: OptSpec; value: unknown; error?: string; disabled?: boolean; onChange: (v: unknown) => void }) {
  const hint = spec.dockerOnly ? `${spec.hint} (docker executor only)` : spec.hint
  const testid = `runner-opt-${spec.key}`
  switch (spec.kind) {
    case 'path':
    case 'text':
      return (
        <TextField
          label={spec.label}
          value={asText(value)}
          placeholder={spec.placeholder}
          description={hint}
          error={error}
          disabled={disabled}
          spellCheck={false}
          className="font-mono text-xs"
          onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)}
          data-testid={testid}
        />
      )
    case 'int':
      return (
        <TextField
          label={spec.label}
          value={asText(value)}
          placeholder={spec.placeholder}
          description={hint}
          error={error}
          disabled={disabled}
          inputMode="numeric"
          className="font-mono text-xs"
          onChange={(e) => {
            const t = e.target.value.trim()
            onChange(t === '' ? undefined : /^\d+$/.test(t) ? Number(t) : t)
          }}
          data-testid={testid}
        />
      )
    case 'bool':
      return (
        <SelectField label={spec.label} value={asBool(value)} description={hint} error={error} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value === 'true')} data-testid={testid}>
          <option value="">(default: {spec.defaultBool ? 'true' : 'false'})</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </SelectField>
      )
    case 'choice':
      return (
        <SelectField label={spec.label} value={asText(value)} description={hint} error={error} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)} data-testid={testid}>
          <option value="">(default)</option>
          {(spec.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </SelectField>
      )
    case 'list':
      return (
        <div className="sm:col-span-2">
          <ListEditor label={spec.label} values={asList(value)} placeholder={spec.placeholder} hint={hint} error={error} disabled={disabled} testid={testid} onChange={(vs) => onChange(vs.length ? vs : undefined)} addLabel="Add item" />
        </div>
      )
    case 'env':
      return (
        <div className="sm:col-span-2">
          <KeyValueEditor
            label={spec.label}
            entries={asEnv(value)}
            hint={hint}
            error={error}
            disabled={disabled}
            testid={testid}
            onChange={(entries) => onChange(entries.length ? Object.fromEntries(entries) : undefined)}
          />
        </div>
      )
  }
}
