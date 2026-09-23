/**
 * The GOV.UK / NHS service patterns the journey screens are built from.
 *
 * Navigation
 * ----------
 * What it is:   `Tag` (the solid status label), `TaskList` (numbered tasks with a status tag
 *               and "You have completed n of m"), `SummaryList` (key / value / change rows —
 *               the "check your answers" grammar), `NotificationBanner` ("Important" with a
 *               blue frame), `WarningCallout` (yellow, for what is NOT requested / NOT meant),
 *               `InsetText` (the blue-railed aside), `BackLink`, `ConfirmationPanel` (the
 *               green "recorded" panel with a reference), `StartButton` (green with the 4px
 *               shadow), `WarningButton` (red — spends money / irreversible) and `Details`
 *               (the GOV.UK details: a native `<details>` whose summary is the one line
 *               shown, for the why behind a screen).
 * What it does: Gives every governance moment the shape a UK public-sector reader already
 *               knows (docs/reviews/2026-09-17-enterprise-front-end.md §6): a task list for
 *               onboarding, summary lists for confirmation, a banner for what needs
 *               attention, a warning for what a signature does not mean, a confirmation
 *               with a reference after an irreversible act. All tokens from ui/src/index.css
 *               — nothing hard-coded, so the dark theme keeps working.
 *               A `hint` (a registry id) on a `Tag`, a `TaskItem` (its status tag), a
 *               `SummaryRow` (the whole row, so the value — the number — opens it as well
 *               as the key) or a button makes that element the hover / focus / tap
 *               trigger for what it means; `StartButton` and `WarningButton` carry
 *               `data-primary` so the ratchet can require one. `Details` reports `onToggle`
 *               so the About block can collect the hints on the screen when it opens.
 * How:          Plain React over Tailwind utilities bound to the theme tokens; `Tag` maps its
 *               own `TagTone` (green / blue / grey / amber / red / pale) to the NHS solid
 *               fills through the local `TAG` table — separate from the `Pill` tones in
 *               ui/src/lib/verdict.ts, which are the soft-fill verdict chips; a hinted element
 *               renders through `<Hint as>`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-042 adopted the NHS design system for the journey)
 * Works with:   ui/src/components/Hint.tsx (the trigger), ui/src/help/hints.ts (the ids),
 *               ui/src/components/Help.tsx (the About block is a `Details`),
 *               ui/src/screens/Home/HomePage.tsx (TaskList, NotificationBanner, InsetText, StartButton),
 *               ui/src/screens/Connect/MeasurePage.tsx (SummaryList, WarningButton, BackLink),
 *               ui/src/screens/Signoff/SignoffPage.tsx (WarningCallout, ConfirmationPanel, SummaryList, WarningButton),
 *               ui/src/screens/Posture/PosturePage.tsx (SummaryList; the other consumers are
 *               in docs/CODE-MAP.md), ui/src/components/Layout.tsx (the shell these sit in)
 * Tested by:    ui/src/components/govuk.test.tsx, ui/src/help/hints-ratchet.test.tsx (the hint contract)
 * Touch when:   a pattern is added (name it after the GOV.UK/NHS component it is).
 */

import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { HintId } from '../help/hints'
import { Hint } from './Hint'

export type TagTone = 'green' | 'blue' | 'grey' | 'amber' | 'red' | 'pale'

const TAG: Record<TagTone, string> = {
  green: 'bg-status-green text-on-primary',
  blue: 'bg-primary text-on-primary',
  grey: 'bg-on-surface-muted text-on-primary',
  amber: 'bg-status-amber-fill text-on-surface',
  red: 'bg-status-red text-on-primary',
  pale: 'bg-surface-high text-on-surface',
}

/** The solid status label — uppercase, bold, one of six tones; `hint` makes it the trigger for what the status means. */
export function Tag({ tone, children, className = '', hint, ...rest }: { tone: TagTone; children: ReactNode; className?: string; hint?: HintId; 'aria-label'?: string; 'data-testid'?: string }) {
  const cls = `inline-block rounded-[4px] px-2 py-1 text-[13px] font-bold uppercase leading-tight tracking-[.05em] whitespace-nowrap ${TAG[tone]} ${className}`
  if (hint) {
    return (
      <Hint id={hint} className={cls} data-component="pill" {...rest}>
        {children}
      </Hint>
    )
  }
  return (
    <span className={cls} data-component="pill" {...rest}>
      {children}
    </span>
  )
}

export interface TaskItem {
  num: string | number
  name: string
  status: string
  tone: TagTone
  /** A route to go to (rendered as a link) or an onClick (a button). */
  to?: string
  onClick?: () => void
  /** What the status tag of this row means — a registry id; the ratchet requires one on every task. */
  hint?: HintId
}

/** GOV.UK task list: "You have completed n of m tasks" and the numbered rows. */
export function TaskList({ tasks, completed, label = 'Tasks', summary }: { tasks: TaskItem[]; completed: number; label?: string; summary?: ReactNode }) {
  return (
    <div>
      <p className="m-0 mb-2 text-[19px] leading-[1.47]">
        {summary ?? `You have completed ${completed} of ${tasks.length} tasks.`}
      </p>
      <ol className="m-0 list-none border-t border-border p-0" aria-label={label}>
        {tasks.map((t) => {
          const inner = (
            <>
              <span className="min-w-[1.6em] text-[19px] leading-[1.47] text-on-surface-muted">{t.num}</span>
              <span className="flex-1 text-[19px] leading-[1.47] text-primary underline">{t.name}</span>
              <Tag tone={t.tone} hint={t.hint}>
                {t.status}
              </Tag>
            </>
          )
          const cls = 'flex w-full items-center gap-4 border-b border-border bg-transparent py-4 text-left no-underline hover:bg-surface-high'
          return (
            <li key={String(t.num)}>
              {t.to ? (
                <Link to={t.to} className={cls}>
                  {inner}
                </Link>
              ) : (
                <button type="button" onClick={t.onClick} className={cls}>
                  {inner}
                </button>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export interface SummaryRow {
  key: ReactNode
  value: ReactNode
  /** The greyed line under the value — the risk of getting this wrong, or the source. */
  note?: ReactNode
  /** "Change" — a route or a handler. */
  changeTo?: string
  onChange?: () => void
  changeLabel?: string
  /** What this row states — a registry id; the whole row (key and value) becomes the hover / focus / tap trigger. */
  hint?: HintId
}

/** GOV.UK summary list — the "check your answers" rows. */
export function SummaryList({ rows, label }: { rows: SummaryRow[]; label?: string }) {
  const rowCls = 'grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] items-baseline gap-4 border-b border-border py-3'
  return (
    <dl className="m-0 border-t border-border" aria-label={label}>
      {rows.map((r, i) => {
        // the whole row is the trigger, so the VALUE — where the number lives — opens the
        // hint as well as the key; a row with a Change link is not a tab stop of its own
        // (the link's focus opens it), a row without one is
        const cells = (
          <>
            <dt className="text-[19px] font-bold leading-[1.47]">{r.key}</dt>
            <dd className="m-0 text-[19px] leading-[1.47]">
              {r.value}
              {r.note && <div className="text-[16px] leading-[1.5] text-on-surface-muted">{r.note}</div>}
            </dd>
            <dd className="m-0 justify-self-end text-[19px] leading-[1.47]">
              {r.changeTo && (
                <Link to={r.changeTo}>
                  {r.changeLabel ?? 'Change'}
                  <span className="sr-only"> {typeof r.key === 'string' ? r.key : ''}</span>
                </Link>
              )}
              {!r.changeTo && r.onChange && (
                <button type="button" className="bg-transparent p-0 text-primary underline" onClick={r.onChange}>
                  {r.changeLabel ?? 'Change'}
                </button>
              )}
            </dd>
          </>
        )
        return r.hint ? (
          <Hint key={i} as="div" id={r.hint} className={rowCls} label={typeof r.key === 'string' ? r.key : undefined}>
            {cells}
          </Hint>
        ) : (
          <div key={i} className={rowCls}>
            {cells}
          </div>
        )
      })}
    </dl>
  )
}

/** GOV.UK notification banner: a blue frame with a title bar. */
export function NotificationBanner({ title = 'Important', children, tone = 'blue', className = '' }: { title?: string; children: ReactNode; tone?: 'blue' | 'green' | 'red'; className?: string }) {
  const frame = tone === 'green' ? 'border-status-green' : tone === 'red' ? 'border-status-red' : 'border-primary'
  const bar = tone === 'green' ? 'bg-status-green' : tone === 'red' ? 'bg-status-red' : 'bg-primary'
  return (
    <div className={`mb-8 max-w-[44em] border-[5px] ${frame} ${className}`} role={tone === 'red' ? 'alert' : 'region'} aria-label={title}>
      <div className={`${bar} px-4 py-2 text-[19px] font-bold leading-[1.4] text-on-primary`}>{title}</div>
      <div className="p-4 text-[19px] leading-[1.47] [&_a]:underline">{children}</div>
    </div>
  )
}

/** NHS warning callout: yellow, for what is NOT requested / NOT meant. */
export function WarningCallout({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={`mb-8 max-w-[44em] border-t-8 border-status-amber-fill bg-status-amber-soft p-6 ${className}`}>
      <h3 className="m-0 mb-2 text-[19px] font-bold uppercase leading-[1.4] tracking-[.05em] text-on-surface">{title}</h3>
      <div className="text-[19px] leading-[1.47] text-on-surface [&_a]:underline">{children}</div>
    </div>
  )
}

/** GOV.UK inset text — the blue-railed aside. */
export function InsetText({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`mb-8 max-w-[44em] border-l-8 border-primary py-2 pl-6 text-[19px] leading-[1.47] [&_a]:underline ${className}`}>{children}</div>
}

export function BackLink({ to, children, hint }: { to: string; children: ReactNode; hint?: HintId }) {
  const className = 'mb-4 inline-block text-[16px] leading-[1.5] text-primary underline'
  if (hint) {
    return (
      <Hint as={Link} id={hint} to={to} className={className}>
        {children}
      </Hint>
    )
  }
  return (
    <Link to={to} className={className}>
      {children}
    </Link>
  )
}

/** GOV.UK confirmation panel: the green block with a reference after an irreversible act. */
export function ConfirmationPanel({ title, reference, referenceLabel = 'Your reference' }: { title: string; reference: string; referenceLabel?: string }) {
  return (
    <div className="mb-8 max-w-[52em] bg-status-green px-6 py-10 text-center text-on-primary">
      <h1 className="m-0 mb-4 text-[32px] font-bold leading-[1.25] text-on-primary">{title}</h1>
      <p className="m-0 mb-2 text-[19px] leading-[1.47]">{referenceLabel}</p>
      <p className="m-0 font-mono text-[32px] font-bold leading-[1.25]">{reference}</p>
    </div>
  )
}

const BTN = 'inline-block rounded-[4px] border-0 px-4 py-3 text-[19px] leading-[1.2] text-on-primary no-underline cursor-pointer disabled:cursor-not-allowed disabled:opacity-45 mb-1'

interface GovButtonProps {
  children: ReactNode
  onClick?: () => void
  to?: string
  disabled?: boolean
  type?: 'button' | 'submit'
  /** What pressing it does — a registry id; the ratchet requires one on a Start or Warning button. */
  hint?: HintId
}

/** A link or a button in the GOV.UK button classes, through `<Hint as>` when it carries an id. */
function GovButton({ children, onClick, to, disabled, type = 'button', hint, cls, primary }: GovButtonProps & { cls: string; primary?: boolean }) {
  const mark = primary ? '' : undefined
  if (to) {
    if (hint) {
      return (
        <Hint as={Link} id={hint} to={to} className={cls} data-primary={mark}>
          {children}
        </Hint>
      )
    }
    return (
      <Link to={to} className={cls} data-primary={mark}>
        {children}
      </Link>
    )
  }
  if (hint) {
    return (
      <Hint as="button" id={hint} type={type} onClick={onClick} disabled={disabled} className={cls} data-primary={mark}>
        {children}
      </Hint>
    )
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={cls} data-primary={mark}>
      {children}
    </button>
  )
}

/** The green primary action with the 4px shadow (GOV.UK button). */
export function StartButton(props: GovButtonProps) {
  return <GovButton {...props} cls={`${BTN} bg-status-green shadow-[0_4px_0_#00401e] hover:brightness-95`} primary />
}

/** The red action — spends money or cannot be undone. */
export function WarningButton(props: Omit<GovButtonProps, 'to'>) {
  return <GovButton {...props} cls={`${BTN} bg-status-red shadow-[0_4px_0_#8a1c12] hover:brightness-95`} primary />
}

/** The grey secondary action. */
export function SecondaryButton(props: GovButtonProps) {
  return <GovButton {...props} cls={`${BTN} bg-on-surface-muted shadow-[0_4px_0_#24343c] hover:brightness-95`} />
}

/**
 * GOV.UK details — progressive disclosure for the why. A native `<details>`/`<summary>`, so
 * keyboard and screen-reader semantics come free; the summary is styled as the GOV.UK
 * details link (19 px, underlined, a ▸ marker that turns when open). Closed unless `open`.
 * With an `id`, the summary gets `<id>-summary` so a landmark can be labelled by it.
 */
export function Details({ summary, children, id, open, onToggle, className = '' }: { summary: string; children: ReactNode; id?: string; open?: boolean; onToggle?: (open: boolean) => void; className?: string }) {
  return (
    <details id={id} open={open} onToggle={onToggle ? (e) => onToggle((e.currentTarget as HTMLDetailsElement).open) : undefined} className={`group mb-6 max-w-[44em] text-[16px] leading-[1.5] ${className}`}>
      <summary id={id ? `${id}-summary` : undefined} className="inline-flex cursor-pointer list-none items-center gap-2 text-[19px] leading-[1.47] text-primary underline underline-offset-4 marker:hidden [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="inline-block text-[14px] transition-transform group-open:rotate-90">
          ▸
        </span>
        {summary}
      </summary>
      <div className="mt-3 border-l-4 border-border py-1 pl-5 [&_a]:underline">{children}</div>
    </details>
  )
}

/** The page's kicker line above the h1 ("cobra · trial", "Task 4 of 7 · spends no money"). */
export function Kicker({ children }: { children: ReactNode }) {
  return <span className="inline-block text-[19px] font-bold leading-[1.4] text-on-surface-muted">{children}</span>
}

/** The journey h1: 48px in the design, 36px here on narrower screens. */
export function PageTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <h1 className={`mb-6 mt-2 max-w-[22em] text-[36px] font-bold leading-[1.15] sm:text-[48px] ${className}`}>{children}</h1>
}

export function Lede({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <p className={`m-0 mb-8 max-w-[44em] text-[19px] leading-[1.47] [&_a]:underline ${className}`}>{children}</p>
}
