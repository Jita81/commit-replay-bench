/**
 * Form fields — labelled input, select and textarea, plus the inline toolbar select.
 *
 * Navigation
 * ----------
 * What it is:   The form primitives: `TextField`, `SelectField`, `TextArea` and `InlineSelect`.
 * What it does: Pairs every control with a real `<label for>` (generated id), renders a
 *               required marker as `Label *`, and wires `description` / `error` through
 *               `aria-describedby` and `aria-invalid` so validation is announced, not just
 *               coloured. `hint` (a registry id) makes the field the hover / focus / tap
 *               trigger for what the value is for: focusing the control opens it, and the
 *               control's `aria-describedby` then names both the description line and the
 *               hint bubble. `InlineSelect` is the compact labelled select toolbars use
 *               (`RepoPicker`, filters).
 * How:          `useId()` for the id when none is given; one shared class string for the
 *               control; the error replaces the description in the same slot, and all three
 *               stacked fields point `aria-describedby` at that slot (`<id>-desc`) and, with
 *               a hint, at `<id>-hint` (the bubble's id, passed to `<Hint bubbleId>`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Hint.tsx (the trigger), ui/src/help/hints.ts (`field.*`
 *               ids), ui/src/components/RepoPicker.tsx (`InlineSelect`),
 *               ui/src/screens/Repos/RepoConfigForm.tsx
 *               and ui/src/screens/Runs/RunNewDialog.tsx (the largest forms),
 *               ui/e2e/walkthrough/support.ts (`field(scope, 'Label')` matches the `Label *`
 *               rendering exactly)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx (the hint contract),
 *               ui/src/screens/Repos/RepoConfigTab.test.tsx (the `aria-describedby` wiring),
 *               ui/src/screens/Connect/GitHubConnectDialog.test.tsx (a select's hint as its
 *               accessible description), ui/src/screens/Runs/RunNewDialog.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe: labels and descriptions)
 * Touch when:   the required-marker rendering changes — update `field()` in
 *               ui/e2e/walkthrough/support.ts with it; never for a new repository.
 */
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import type { HintId } from '../help/hints'
import { Hint } from './Hint'

const control =
  'w-full rounded-[var(--radius-control)] border border-border bg-surface-container px-3 text-sm text-on-surface ' +
  'placeholder:text-on-surface-muted disabled:opacity-60'

interface BaseProps {
  label: string
  /** The visible line under the control (the field's `aria-describedby`); an `error` replaces it. */
  description?: ReactNode
  error?: string
  required?: boolean
  /** What the value is for — a registry id; the field becomes the hover / focus / tap trigger. */
  hint?: HintId
}

/** The control's `aria-describedby`: the description slot when it renders, plus the hint bubble when there is one. */
function describedBy(fid: string, hasDesc: boolean, hint: HintId | undefined): string | undefined {
  const ids = [hasDesc ? `${fid}-desc` : '', hint ? `${fid}-hint` : ''].filter(Boolean)
  return ids.length ? ids.join(' ') : undefined
}

/** The field's root: a `<Hint as="div">` when it carries an id, else a plain stack. */
function FieldRoot({ fid, hint, children }: { fid: string; hint: HintId | undefined; children: ReactNode }) {
  if (hint) {
    return (
      <Hint as="div" id={hint} bubbleId={`${fid}-hint`} className="space-y-1">
        {children}
      </Hint>
    )
  }
  return <div className="space-y-1">{children}</div>
}

/** A labelled `<input>`; `error` replaces `hint` in the description slot and sets `aria-invalid`. */
export function TextField({ label, description, error, required, hint, id, className = '', ...rest }: BaseProps & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId()
  const fid = id ?? auto
  const hasDesc = Boolean(description || error)
  return (
    <FieldRoot fid={fid} hint={hint}>
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <input
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, hasDesc, hint)}
        className={`${control} h-10 ${className}`}
        {...rest}
      />
      {hasDesc && (
        <div id={`${fid}-desc`} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>
          {error ?? description}
        </div>
      )}
    </FieldRoot>
  )
}

/** A labelled `<select>`; same hint / error contract as `TextField`. */
export function SelectField({
  label,
  description,
  error,
  required,
  hint,
  id,
  className = '',
  children,
  ...rest
}: BaseProps & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId()
  const fid = id ?? auto
  const hasDesc = Boolean(description || error)
  return (
    <FieldRoot fid={fid} hint={hint}>
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <select
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, hasDesc, hint)}
        className={`${control} h-10 ${className}`}
        {...rest}
      >
        {children}
      </select>
      {hasDesc && (
        <div id={`${fid}-desc`} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>
          {error ?? description}
        </div>
      )}
    </FieldRoot>
  )
}

/** A labelled `<textarea>`; same hint / error contract as `TextField`. */
export function TextArea({ label, description, error, required, hint, id, className = '', ...rest }: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId()
  const fid = id ?? auto
  const hasDesc = Boolean(description || error)
  return (
    <FieldRoot fid={fid} hint={hint}>
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <textarea
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, hasDesc, hint)}
        className={`${control} py-2 ${className}`}
        {...rest}
      />
      {hasDesc && (
        <div id={`${fid}-desc`} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>
          {error ?? description}
        </div>
      )}
    </FieldRoot>
  )
}

/** A compact inline select for toolbars (labelled, no stacked layout); `hint` makes the whole label the trigger. */
export function InlineSelect({ label, hint, id, className = '', children, ...rest }: { label: string; hint?: HintId } & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId()
  const fid = id ?? auto
  const cls = 'inline-flex items-center gap-2 text-xs text-on-surface-muted'
  const inner = (
    <>
      <span>{label}</span>
      <select
        id={fid}
        aria-describedby={hint ? `${fid}-hint` : undefined}
        className={`h-8 rounded-[var(--radius-control)] border border-border bg-surface-container px-2 text-xs text-on-surface ${className}`}
        {...rest}
      >
        {children}
      </select>
    </>
  )
  if (hint) {
    return (
      <Hint as="label" id={hint} bubbleId={`${fid}-hint`} htmlFor={fid} className={cls}>
        {inner}
      </Hint>
    )
  }
  return (
    <label htmlFor={fid} className={cls}>
      {inner}
    </label>
  )
}
