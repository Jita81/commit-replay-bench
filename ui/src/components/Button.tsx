/**
 * Buttons — one class set for <button>, <Link> and <a>, so every action renders identically.
 *
 * Navigation
 * ----------
 * What it is:   The button primitives: `Button`, `LinkButton` (router link), `AnchorButton`
 *               (plain anchor, for API download URLs) and the shared `buttonClasses`.
 * What it does: Four variants (filled / outlined / ghost / danger) and two sizes with a ≥40 px
 *               hit target at `md`, a visible focus ring from the global styles, and
 *               `type="button"` by default so a button inside a form never submits it by
 *               accident.
 * How:          `buttonClasses(variant, size)` composes the Tailwind classes; each wrapper
 *               spreads the rest of its props onto the native element.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/index.css (the tokens and the focus ring), ui/src/components/Dialog.tsx
 *               (close button), ui/src/components/ErrorState.tsx (retry),
 *               ui/src/screens/Ledger/LedgerPage.tsx (`AnchorButton` for the export URLs)
 * Tested by:    ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe on every screen), and
 *               every screen test that clicks a button by role
 * Touch when:   a variant or size is added; never for a new repository.
 */
import type { ButtonHTMLAttributes, AnchorHTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router'

export type ButtonVariant = 'filled' | 'outlined' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

/** Shared classes so <button>, <a> and <Link> render identically. Hit target ≥40px at md. */
export function buttonClasses(variant: ButtonVariant = 'outlined', size: ButtonSize = 'md'): string {
  const base =
    'inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-control)] font-semibold whitespace-nowrap ' +
    'transition-colors disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer select-none'
  const sizes: Record<ButtonSize, string> = {
    sm: 'h-8 px-3 text-xs',
    md: 'h-10 px-4 text-sm',
  }
  const variants: Record<ButtonVariant, string> = {
    filled: 'bg-primary text-on-primary border border-primary hover:opacity-90',
    outlined: 'bg-surface-container text-on-surface border border-border hover:bg-surface-high',
    ghost: 'bg-transparent text-primary border border-transparent hover:bg-primary-container',
    danger: 'bg-surface-container text-status-red border border-status-red/40 hover:bg-status-red-soft',
  }
  return `${base} ${sizes[size]} ${variants[variant]}`
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

/** A `<button>`; `type="button"` unless told otherwise, so a button inside a form does not submit it. */
export function Button({ variant = 'outlined', size = 'md', className = '', type = 'button', ...rest }: ButtonProps) {
  return <button type={type} className={`${buttonClasses(variant, size)} ${className}`} {...rest} />
}

interface LinkButtonProps extends LinkProps {
  variant?: ButtonVariant
  size?: ButtonSize
}

/** A router `<Link>` styled as a button (in-app navigation that reads as an action). */
export function LinkButton({ variant = 'outlined', size = 'md', className = '', ...rest }: LinkButtonProps) {
  return <Link className={`${buttonClasses(variant, size)} ${className}`} {...rest} />
}

interface AnchorButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

/** A plain anchor styled as a button — for API download URLs (export). */
export function AnchorButton({ variant = 'outlined', size = 'md', className = '', ...rest }: AnchorButtonProps) {
  return <a className={`${buttonClasses(variant, size)} ${className}`} {...rest} />
}
