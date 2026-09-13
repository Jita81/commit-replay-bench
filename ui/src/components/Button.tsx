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

export function Button({ variant = 'outlined', size = 'md', className = '', type = 'button', ...rest }: ButtonProps) {
  return <button type={type} className={`${buttonClasses(variant, size)} ${className}`} {...rest} />
}

interface LinkButtonProps extends LinkProps {
  variant?: ButtonVariant
  size?: ButtonSize
}

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
