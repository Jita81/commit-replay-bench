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
      <select id={fid} required={required} aria-invalid={error ? true : undefined} className={`${control} h-10 ${className}`} {...rest}>
        {children}
      </select>
      {(hint || error) && <div className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>{error ?? hint}</div>}
    </div>
  )
}

export function TextArea({ label, hint, error, required, id, className = '', ...rest }: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <div className="space-y-1">
      <label htmlFor={fid} className="block text-xs font-semibold text-on-surface-body">
        {label}
        {required && <span aria-hidden className="text-status-red"> *</span>}
      </label>
      <textarea id={fid} required={required} aria-invalid={error ? true : undefined} className={`${control} py-2 ${className}`} {...rest} />
      {(hint || error) && <div className={`text-xs ${error ? 'text-status-red' : 'text-on-surface-muted'}`}>{error ?? hint}</div>}
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
