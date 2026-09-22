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
 *               accident. Hover states keep AA contrast in every theme (a filled button
 *               darkens; it never fades — WCAG 1.4.3 applies to the hovered state too). With
 *               `hint` (a registry id) the button is the hover / focus / tap trigger for what
 *               pressing it does; the click always goes through. A filled or submit button
 *               carries `data-primary` so the ratchet can require a hint on every primary
 *               action.
 * How:          `buttonClasses(variant, size)` composes the Tailwind classes; each wrapper
 *               spreads the rest of its props onto the native element, through `<Hint as>`
 *               when it carries an id.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/components/Hint.tsx (the trigger), ui/src/help/hints.ts (`button.*`
 *               ids), ui/src/index.css (the tokens and the focus ring), ui/src/components/Dialog.tsx
 *               (close button), ui/src/components/ErrorState.tsx (retry),
 *               ui/src/screens/Ledger/LedgerPage.tsx (`AnchorButton` for the export URLs)
 * Tested by:    ui/src/help/hints-ratchet.test.tsx (the hint contract), ui/src/components/Hint.test.tsx
 *               (the click goes through), ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (axe on every screen), and
 *               every screen test that clicks a button by role
 * Touch when:   a variant or size is added; never for a new repository.
 */
import type { ButtonHTMLAttributes, AnchorHTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router'
import type { HintId } from '../help/hints'
import { Hint } from './Hint'

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
    // hover darkens the whole button (filter), never fades it: an opacity hover blends the
    // text and the fill toward the page and a filled sm button drops under 4.5:1 on hover
    // (axe color-contrast on /connect/:name when the pointer rests on Baseline)
    filled: 'bg-primary text-on-primary border border-primary hover:brightness-95',
    outlined: 'bg-surface-container text-on-surface border border-border hover:bg-surface-high',
    ghost: 'bg-transparent text-primary border border-transparent hover:bg-primary-container',
    danger: 'bg-surface-container text-status-red border border-status-red/40 hover:bg-status-red-soft',
  }
  return `${base} ${sizes[size]} ${variants[variant]}`
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** What pressing it does — a registry id; required by the ratchet on every primary (filled / submit) button. */
  hint?: HintId
}

/** `data-primary` marks the buttons the ratchet requires a hint on: filled, or a form's submit. */
function primary(variant: ButtonVariant, type?: string): '' | undefined {
  return variant === 'filled' || type === 'submit' ? '' : undefined
}

/** A `<button>`; `type="button"` unless told otherwise, so a button inside a form does not submit it. */
export function Button({ variant = 'outlined', size = 'md', className = '', type = 'button', hint, id, ...rest }: ButtonProps) {
  const cls = `${buttonClasses(variant, size)} ${className}`
  if (hint) return <Hint as="button" id={hint} elementId={id} type={type} className={cls} data-primary={primary(variant, type)} {...rest} />
  return <button id={id} type={type} className={cls} data-primary={primary(variant, type)} {...rest} />
}

interface LinkButtonProps extends LinkProps {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Where it goes and why — a registry id; required by the ratchet on a filled link. */
  hint?: HintId
}

/** A router `<Link>` styled as a button (in-app navigation that reads as an action). */
export function LinkButton({ variant = 'outlined', size = 'md', className = '', hint, id, ...rest }: LinkButtonProps) {
  const cls = `${buttonClasses(variant, size)} ${className}`
  if (hint) return <Hint as={Link} id={hint} elementId={id} className={cls} data-primary={primary(variant)} {...rest} />
  return <Link id={id} className={cls} data-primary={primary(variant)} {...rest} />
}

interface AnchorButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** What the download is — a registry id. */
  hint?: HintId
}

/** A plain anchor styled as a button — for API download URLs (export). */
export function AnchorButton({ variant = 'outlined', size = 'md', className = '', hint, id, ...rest }: AnchorButtonProps) {
  const cls = `${buttonClasses(variant, size)} ${className}`
  if (hint) return <Hint as="a" id={hint} elementId={id} className={cls} data-primary={primary(variant)} {...rest} />
  return <a id={id} className={cls} data-primary={primary(variant)} {...rest} />
}
