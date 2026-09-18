/**
 * Form fields — labelled input, select and textarea, plus the inline toolbar select.
 *
 * Navigation
 * ----------
 * What it is:   The form primitives: `TextField`, `SelectField`, `TextArea` and `InlineSelect`.
 * What it does: Pairs every control with a real `<label for>` (generated id), renders a
 *               required marker as `Label *`, and wires `hint` / `error` through
 *               `aria-describedby` and `aria-invalid` so validation is announced, not just
 *               coloured. `InlineSelect` is the compact labelled select toolbars use
 *               (`RepoPicker`, filters).
 * How:          `useId()` for the id when none is given; one shared class string for the
 *               control; the error replaces the hint in the same slot, and all three
 *               stacked fields point `aria-describedby` at that slot (`<id>-desc`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/RepoPicker.tsx (`InlineSelect`),
 *               ui/src/screens/Repos/RepoConfigForm.tsx
 *               and ui/src/screens/Runs/RunNewDialog.tsx (the largest forms),
 *               ui/e2e/walkthrough/support.ts (`field(scope, 'Label')` matches the `Label *`
 *               rendering exactly)
 * Tested by:    ui/src/screens/Repos/RepoConfigTab.test.tsx (the `aria-describedby` wiring),
 *               ui/src/screens/Connect/GitHubConnectDialog.test.tsx (a select's hint as its
 *               accessible description), ui/src/screens/Runs/RunNewDialog.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe: labels and descriptions)
 * Touch when:   the required-marker rendering changes — update `field()` in
 *               ui/e2e/walkthrough/support.ts with it; never for a new repository.
 */
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'

const control =
  'w-full rounded-[var(--radius-control)] border border-border bg-surface-container px-3 text-sm text-on-surface ' +
  'placeholder:text-on-surface-muted disabled:opacity-60'

interface BaseProps {
  label: string
  hint?: ReactNode
  error?: string
  required?: boolean
}

/** A labelled `<input>`; `error` replaces `hint` in the description slot and sets `aria-invalid`. */
export function TextField({ label, hint, error, required, id, className = '', ...rest }: BaseProps & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <div className="space-y-1">
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <input
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? `${fid}-desc` : undefined}
        className={`${control} h-10 ${className}`}
        {...rest}
      />
      {(hint || error) && (
        <div id={`${fid}-desc`} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>
          {error ?? hint}
        </div>
      )}
    </div>
  )
}

/** A labelled `<select>`; same hint / error contract as `TextField`. */
export function SelectField({
  label,
  hint,
  error,
  required,
  id,
  className = '',
  children,
  ...rest
}: BaseProps & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <div className="space-y-1">
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <select
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? `${fid}-desc` : undefined}
        className={`${control} h-10 ${className}`}
        {...rest}
      >
        {children}
      </select>
      {(hint || error) && (
        <div id={`${fid}-desc`} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>
          {error ?? hint}
        </div>
      )}
    </div>
  )
}

/** A labelled `<textarea>`; same hint / error contract as `TextField`. */
export function TextArea({ label, hint, error, required, id, className = '', ...rest }: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <div className="space-y-1">
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <textarea
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? `${fid}-desc` : undefined}
        className={`${control} py-2 ${className}`}
        {...rest}
      />
      {(hint || error) && (
        <div id={`${fid}-desc`} className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>
          {error ?? hint}
        </div>
      )}
    </div>
  )
}

/** A compact inline select for toolbars (labelled, no stacked layout). */
export function InlineSelect({ label, id, className = '', children, ...rest }: { label: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <label htmlFor={fid} className="inline-flex items-center gap-2 text-xs text-on-surface-muted">
      <span>{label}</span>
      <select id={fid} className={`h-8 rounded-[var(--radius-control)] border border-border bg-surface-container px-2 text-xs text-on-surface ${className}`} {...rest}>
        {children}
      </select>
    </label>
  )
}
