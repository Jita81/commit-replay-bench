/**
 * List and key/value editors — one input per item, the shape every "list of strings" and "env"
 * runner option shares.
 *
 * Navigation
 * ----------
 * What it is:   `ListEditor` (a list of strings: `pip`, `extra_args`, `maven_flags`, an
 *               explicit belt-scope list) and `KeyValueEditor` (the `env` map).
 * What it does: Edits ordered string lists and NAME=value maps as rows with add / remove,
 *               keeping the order the runner will see; each row is labelled "<label> N" for
 *               assistive tech; hint or error is attached to the group via
 *               `aria-describedby`; `disabled` renders the same rows read-only for a viewer.
 * How:          Controlled: the parent owns the array; every change emits a new array.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Repos/RunnerOptsEditor.tsx (the `list` and `env` kinds),
 *               ui/src/screens/Repos/RepoConfigForm.tsx (the belt-scope list),
 *               ui/src/components/Button.tsx
 * Tested by:    ui/src/screens/Repos/RepoConfigTab.test.tsx (rows added and sent),
 *               ui/e2e/walkthrough/repo-config.spec.ts (the belt-scope row editor in Chromium)
 * Touch when:   never for a new repository.
 */
import { useId, type ReactNode } from 'react'
import { Button } from '../../components/Button'

const control =
  'w-full rounded-[var(--radius-control)] border border-border bg-surface-container px-3 text-sm text-on-surface ' +
  'placeholder:text-on-surface-muted disabled:opacity-60 h-9'

interface ListEditorProps {
  label: string
  values: string[]
  onChange: (values: string[]) => void
  hint?: ReactNode
  error?: string
  placeholder?: string
  /** Prefix for the `data-testid`s: `<testid>-add`, `<testid>-item-<i>`, `<testid>-remove-<i>`. */
  testid: string
  disabled?: boolean
  addLabel?: string
  mono?: boolean
}

/**
 * One text input per item, a remove button beside each, an add button below — the
 * shape every "list of strings" runner option shares (`pip`, `extra_args`,
 * `maven_flags`, an explicit belt-scope list…). Items are labelled "<label> N" for
 * assistive tech and keyboard users; the order is the order the runner sees.
 */
export function ListEditor({ label, values, onChange, hint, error, placeholder, testid, disabled, addLabel = 'Add', mono = true }: ListEditorProps) {
  const id = useId()
  const descId = hint || error ? `${id}-desc` : undefined
  const set = (i: number, v: string) => onChange(values.map((x, j) => (j === i ? v : x)))
  const remove = (i: number) => onChange(values.filter((_, j) => j !== i))
  return (
    <div className="space-y-1" role="group" aria-labelledby={`${id}-label`} aria-describedby={descId} data-testid={testid}>
      <div id={`${id}-label`} className="text-xs font-semibold text-on-surface-body">
        {label}
      </div>
      {values.length === 0 && <div className="text-xs text-on-surface-muted">(none)</div>}
      <ul className="m-0 list-none space-y-1.5 p-0">
        {values.map((v, i) => (
          <li key={i} className="flex items-center gap-2">
            <input
              aria-label={`${label} ${i + 1}`}
              value={v}
              placeholder={placeholder}
              disabled={disabled}
              spellCheck={false}
              onChange={(e) => set(i, e.target.value)}
              className={`${control} ${mono ? 'font-mono text-xs' : ''}`}
              data-testid={`${testid}-item-${i}`}
            />
            {!disabled && (
              <Button size="sm" onClick={() => remove(i)} aria-label={`Remove ${label} ${i + 1}`} data-testid={`${testid}-remove-${i}`}>
                Remove
              </Button>
            )}
          </li>
        ))}
      </ul>
      {!disabled && (
        <Button size="sm" onClick={() => onChange([...values, ''])} data-testid={`${testid}-add`}>
          {addLabel}
        </Button>
      )}
      {(hint || error) && (
        <div id={descId} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`} role={error ? 'alert' : undefined}>
          {error ?? hint}
        </div>
      )}
    </div>
  )
}

interface KeyValueEditorProps {
  label: string
  entries: Array<[string, string]>
  onChange: (entries: Array<[string, string]>) => void
  hint?: ReactNode
  error?: string
  testid: string
  disabled?: boolean
}

/** Key/value rows for the `env` runner option (string → string). */
export function KeyValueEditor({ label, entries, onChange, hint, error, testid, disabled }: KeyValueEditorProps) {
  const id = useId()
  const descId = hint || error ? `${id}-desc` : undefined
  const setKey = (i: number, k: string) => onChange(entries.map((e, j) => (j === i ? [k, e[1]] : e)))
  const setVal = (i: number, v: string) => onChange(entries.map((e, j) => (j === i ? [e[0], v] : e)))
  const remove = (i: number) => onChange(entries.filter((_, j) => j !== i))
  return (
    <div className="space-y-1" role="group" aria-labelledby={`${id}-label`} aria-describedby={descId} data-testid={testid}>
      <div id={`${id}-label`} className="text-xs font-semibold text-on-surface-body">
        {label}
      </div>
      {entries.length === 0 && <div className="text-xs text-on-surface-muted">(none)</div>}
      <ul className="m-0 list-none space-y-1.5 p-0">
        {entries.map(([k, v], i) => (
          <li key={i} className="flex items-center gap-2">
            <input
              aria-label={`${label} name ${i + 1}`}
              value={k}
              placeholder="NAME"
              disabled={disabled}
              spellCheck={false}
              onChange={(e) => setKey(i, e.target.value)}
              className={`${control} max-w-[40%] font-mono text-xs`}
              data-testid={`${testid}-key-${i}`}
            />
            <span aria-hidden className="text-on-surface-muted">
              =
            </span>
            <input
              aria-label={`${label} value ${i + 1}`}
              value={v}
              placeholder="value"
              disabled={disabled}
              spellCheck={false}
              onChange={(e) => setVal(i, e.target.value)}
              className={`${control} font-mono text-xs`}
              data-testid={`${testid}-value-${i}`}
            />
            {!disabled && (
              <Button size="sm" onClick={() => remove(i)} aria-label={`Remove ${label} ${i + 1}`} data-testid={`${testid}-remove-${i}`}>
                Remove
              </Button>
            )}
          </li>
        ))}
      </ul>
      {!disabled && (
        <Button size="sm" onClick={() => onChange([...entries, ['', '']])} data-testid={`${testid}-add`}>
          Add variable
        </Button>
      )}
      {(hint || error) && (
        <div id={descId} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`} role={error ? 'alert' : undefined}>
          {error ?? hint}
        </div>
      )}
    </div>
  )
}
