/**
 * Intake — the watched column on the team's own board, and what the product said back.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /factory/intake?repo=: one repository's intake listener (the
 *               consent gate, default OFF), the deployment's tracker connection with no
 *               secret in it, what the last read did, and every ticket in the watched
 *               column with its draft item, its label, the questions still open and the
 *               feedback the ticket itself carries.
 * What it does: Makes the entry point of the factory legible before any money is spent: a
 *               reader can see which ticket the product understood, as what kind of change
 *               and with what confidence, what it still needs answering, what the map says
 *               about work of that kind and size, and where the item went. An operator has
 *               three acts — switch the listener on or off, re-read the column now, post
 *               the feedback again — each with a success state naming what happened
 *               (tickets read, comments posted, items registered) and an error that says
 *               what to do (tracker unreachable, credential missing, the write refused).
 * How:          `useRepoParam({ defaultToLatest: true })` → `useIntake` (a pure read: no
 *               tracker is contacted) → `useSetIntakeListener` (PUT, operator) and
 *               `usePollIntake` (POST, operator; `force` is "post the feedback again").
 *               Every stop reason the server serves comes with the server's own advice, so
 *               this screen never invents a way forward. The row's feedback is the comment
 *               verbatim, so the screen and the ticket can never disagree.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
 * Works with:   ui/src/api/hooks.ts (`useIntake`, `useSetIntakeListener`, `usePollIntake`),
 *               ui/src/api/types.ts (`Intake`, `IntakeRow`),
 *               src/crb/server/routes/factory.py (the three routes),
 *               src/crb/server/intake.py (the listener these acts drive),
 *               ui/src/screens/Factory/FactoryPage.tsx (where a queued item goes next),
 *               ui/src/help/help.ts (the About block), ui/src/help/hints.ts (every element)
 * Tested by:    ui/src/screens/Factory/IntakePage.test.tsx, ui/e2e/walkthrough/12-intake.spec.ts
 * Touch when:   a field is added to the intake response (types first); a fifth label or a
 *               new stop reason appears (docs/API.md first).
 */

import { useState } from 'react'
import { Link } from 'react-router'
import { useAllRepos, useIntake, usePollIntake, useSetIntakeListener } from '../../api/hooks'
import type { Intake, IntakeRow } from '../../api/types'
import { Button, LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { TextField } from '../../components/Field'
import { Term } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { Details, NotificationBanner, SummaryList } from '../../components/govuk'
import type { HintId } from '../../help/hints'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtInt } from '../../lib/format'
import type { Tone } from '../../lib/verdict'

/** The four labels the product sets, as a reader meets them. The tone is the meaning: amber
 *  = it is waiting on you, red = it will be built but held back, green = it is on its way. */
const LABEL_DISPLAY: Record<string, { tone: Tone; label: string; hint: HintId }> = {
  'crb:needs-info': { tone: 'amber', label: 'needs information', hint: 'pill.intake.needs_info' },
  'crb:ready': { tone: 'blue', label: 'ready', hint: 'pill.intake.ready' },
  'crb:not-deliverable': { tone: 'red', label: 'not deliverable', hint: 'pill.intake.not_deliverable' },
  'crb:queued': { tone: 'green', label: 'queued', hint: 'pill.intake.queued' },
}

/** A stop the server named, with the server's own advice under it. Never our own words. */
function Stopped({ reason, advice }: { reason: string; advice: string }) {
  return (
    <NotificationBanner title="The listener stopped" tone="red">
      <p className="m-0">
        <Hint id="banner.intake.stopped">
          <span>
            Reason: <span className="font-mono">{reason}</span>
          </span>
        </Hint>
      </p>
      {advice && <p className="mb-0 mt-2 text-[16px]">{advice}</p>}
    </NotificationBanner>
  )
}

/** One ticket: what it is, what the product understood, what is still missing, where it went. */
function Row({ row }: { row: IntakeRow }) {
  const display = LABEL_DISPLAY[row.label]
  const route = row.cell_route
  return (
    <li className="border-b border-border py-4 last:border-0" data-testid={`intake-row-${row.key}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <Hint id="item.intake.key">
          <span className="font-mono text-xs">{row.key}</span>
        </Hint>
        <span className="min-w-0 flex-1 truncate font-medium">{row.title || '(no title)'}</span>
        {display && (
          <Pill tone={display.tone} size="xs" label={`Label on the ticket: ${row.label}`} hint={display.hint}>
            {display.label}
          </Pill>
        )}
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div>
          <Hint id="item.intake.class">
            <span className="text-on-surface-muted">
              Kind of change: <span className="font-mono">{row.capability_class || 'unclassified'}</span> ({row.size || '—'}), confidence {row.confidence.toFixed(2)}
            </span>
          </Hint>
        </div>
        <div>
          <Hint id="item.intake.revision">
            <span className="text-on-surface-muted">
              Revision <span className="font-mono">{row.revision || '—'}</span>
              {row.read_at ? ` · read ${fmtDate(row.read_at)}` : ''}
            </span>
          </Hint>
        </div>
        <div>
          <Hint id="item.intake.cell_route">
            <span className="text-on-surface-muted">
              {route ? (
                <>
                  Route <span className="font-mono">{route.route}</span> on n = {fmtInt(route.n)}, interval {(route.ci_low * 100).toFixed(0)}–{(route.ci_high * 100).toFixed(0)} %
                </>
              ) : (
                'This cell has not been measured on this repository — it says nothing, not zero.'
              )}
            </span>
          </Hint>
        </div>
        <div>
          <Hint id="item.intake.item">
            <span className="text-on-surface-muted">
              {row.registered ? (
                <>
                  Registered as{' '}
                  <Link to={row.item_url} className="font-mono underline">
                    {row.item_id}
                  </Link>
                  {row.is_evolution ? ` (replaces ${row.supersedes})` : ''}
                </>
              ) : (
                <>
                  Would be registered as <span className="font-mono">{row.item_id}</span> — nothing is registered until the questions are answered.
                </>
              )}
            </span>
          </Hint>
        </div>
      </dl>
      {row.stopped && (
        <p className="mt-2 text-sm text-status-red">
          <Hint id="item.intake.stopped">
            <span>
              This ticket stopped at <span className="font-mono">{row.stopped}</span>. {row.stopped_advice}
            </span>
          </Hint>
        </p>
      )}
      {row.open_questions.length > 0 && (
        <Details summary={`${row.open_questions.length} question(s) the acceptance test needs answered`} className="mb-0 mt-3">
          <ul className="m-0 list-disc space-y-1 pl-5 text-sm">
            {row.open_questions.map((q) => (
              <li key={q.ref}>
                <span>{q.reason}</span>{' '}
                <span className="text-on-surface-muted">({q.severity === 'blocking' ? 'blocks the build' : 'routes the item, does not block'})</span>
              </li>
            ))}
          </ul>
        </Details>
      )}
      <Details summary="The comment on the ticket, word for word" className="mb-0 mt-2">
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap bg-surface-2 p-3 text-xs">{row.feedback || '(nothing posted yet)'}</pre>
      </Details>
      <div className="mt-3 flex flex-wrap gap-2">
        {row.url && (
          <LinkButton to={row.url} size="sm" hint="link.intake.ticket">
            Open the ticket
          </LinkButton>
        )}
        {row.registered && (
          <LinkButton to={row.item_url} size="sm" hint="link.intake.item">
            Open the item
          </LinkButton>
        )}
      </div>
    </li>
  )
}

export function IntakePage() {
  const [repo, setRepo] = useRepoParam({ defaultToLatest: true })
  const repos = useAllRepos()
  const { can } = useAuth()
  const intake = useIntake(repo)
  const setListener = useSetIntakeListener()
  const poll = usePollIntake()
  const [column, setColumn] = useState('')
  const [done, setDone] = useState('')

  const data: Intake | undefined = intake.data
  const listener = data?.listener
  const connection = data?.connection
  const last = data?.last_poll ?? null
  const operator = can('operator')

  function say(message: string) {
    setDone(message)
  }

  function toggle(enabled: boolean) {
    setDone('')
    setListener.mutate(
      { repo, enabled, column: column || listener?.column || '' },
      {
        onSuccess: (next) =>
          say(
            next.listener.enabled
              ? `The listener is on. It reads the column “${next.listener.column || next.connection.column}” every ${fmtInt(next.connection.poll_s)} seconds.`
              : 'The listener is off. Nothing on that board will be read or written until it is switched on again.',
          ),
      },
    )
  }

  function readNow(force: boolean) {
    setDone('')
    poll.mutate(
      { repo, force },
      {
        onSuccess: (next) => {
          const p = next.last_poll
          if (!p) return say('The column was read.')
          if (p.stopped) return say('')
          say(
            `Read the column “${p.column}”: ${fmtInt(p.seen)} ticket(s) seen, ${fmtInt(p.read)} read, ${fmtInt(p.commented)} commented on, ` +
              `${fmtInt(p.registered)} registered${p.queued ? `, ${fmtInt(p.queued)} waiting for the factory run to finish` : ''}.`,
          )
        },
      },
    )
  }

  return (
    <>
      <PageHeader
        eyebrow="Journey · 4 of 4 · Factory · intake"
        title="Work arriving from your board"
        purpose={
          <>
            A ticket moved into one watched column is the request to manufacture: the ticket <em>is</em> the backlog item, and the column is the consent gate. Before anything is
            built, the product tells the ticket what a good acceptance test still needs answering, and what it knows about changes of that kind and size (the{' '}
            <Term id="cell">cell</Term>’s <Term id="deliver">route</Term>, with its n and interval). It never edits any other field, never creates a ticket, and never reads a
            column it was not pointed at.
          </>
        }
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />

      {!repo && (
        <EmptyState
          title={repos.data && repos.data.items.length === 0 ? 'No repository connected yet' : 'Choose a repository'}
          reason={
            repos.data && repos.data.items.length === 0
              ? 'Intake watches one column per repository; nothing is connected on this deployment.'
              : 'Intake watches one column per repository: choose one from the picker above.'
          }
          action={repos.data && repos.data.items.length === 0 && operator ? <LinkButton to="/connect">Connect a repository</LinkButton> : undefined}
        />
      )}

      {repo && intake.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
      {repo && intake.isError && <ErrorState error={intake.error} onRetry={() => void intake.refetch()} />}

      {repo && data && connection && listener && (
        <>
          {done && (
            <NotificationBanner title="Done" tone="green">
              {/* a live region: a screen-reader user is told the outcome as it lands,
                  rather than having to scan back up the page for it */}
              <p className="m-0" role="status" data-testid="intake-success">
                {done}
              </p>
            </NotificationBanner>
          )}
          {setListener.isError && <ErrorState error={setListener.error} />}
          {poll.isError && <ErrorState error={poll.error} />}
          {last?.stopped && <Stopped reason={last.stopped} advice={last.advice} />}

          <Card title="The listener" eyebrow="one column · one repository · off until somebody switches it on">
            <SummaryList
              label="The listener and the connection"
              rows={[
                {
                  key: 'This repository',
                  value: listener.enabled ? 'Listening' : 'Not listening',
                  note: listener.enabled
                    ? `Switched on by ${listener.switched_by || 'an operator'}${listener.switched_at ? ` on ${fmtDate(listener.switched_at)}` : ''}.`
                    : 'Nothing on that board is read or written while this is off. That is the default for every repository.',
                  hint: 'stat.intake.listener',
                },
                {
                  key: 'Watched column',
                  value: listener.column || connection.column || '—',
                  note: listener.column ? 'This repository overrides the deployment’s column.' : 'The deployment’s column, used by every repository that does not override it.',
                  hint: 'stat.intake.column',
                },
                {
                  key: 'Tracker',
                  value: connection.tracker === 'none' ? 'Not configured' : `${connection.tracker} · ${connection.project}`,
                  note: connection.url || 'An admin sets the tracker, the project and the column for the whole deployment.',
                  hint: 'stat.intake.tracker',
                },
                {
                  key: 'Credential',
                  value: connection.credential_set ? `Stored (…${connection.credential_fingerprint})` : 'Not stored',
                  note: connection.credential_set
                    ? 'Held by the API host and never shown. Only its last characters are ever served.'
                    : 'An admin stores the tracker token on Settings; nothing can be read from the board until they do.',
                  hint: 'stat.intake.credential',
                },
                {
                  key: 'How often',
                  value: `every ${fmtInt(connection.poll_s)} seconds`,
                  note: 'The worker reads the column on this timer while the listener is on.',
                  hint: 'stat.intake.poll_s',
                },
                {
                  key: 'When a pull request merges',
                  value: Object.keys(connection.outcome_map).length ? Object.entries(connection.outcome_map).map(([k, v]) => `${k} → ${v}`).join(', ') : 'the ticket is not moved',
                  note: 'A deployment that configures no mapping never changes anybody’s ticket state.',
                  hint: 'stat.intake.outcome_map',
                },
              ]}
            />
            {operator && (
              <div className="mt-4 space-y-3">
                {!listener.enabled && (
                  <TextField
                    label="Watch a different column on this repository (optional)"
                    value={column}
                    onChange={(e) => setColumn(e.currentTarget.value)}
                    placeholder={connection.column}
                    hint="field.intake.column"
                  />
                )}
                <div className="flex flex-wrap gap-2">
                  {listener.enabled ? (
                    <Button onClick={() => toggle(false)} disabled={setListener.isPending} hint="button.intake.switch_off">
                      Switch the listener off
                    </Button>
                  ) : (
                    <Button variant="filled" onClick={() => toggle(true)} disabled={setListener.isPending || !connection.configured} hint="button.intake.switch_on">
                      Switch the listener on
                    </Button>
                  )}
                  <Button onClick={() => readNow(false)} disabled={poll.isPending || !listener.enabled} hint="button.intake.read_now">
                    Re-read the column now
                  </Button>
                  <Button onClick={() => readNow(true)} disabled={poll.isPending || !listener.enabled} hint="button.intake.repost">
                    Post the feedback again
                  </Button>
                </div>
                {!connection.configured && (
                  <p className="text-sm text-on-surface-muted">An admin configures the tracker for the whole deployment before a listener can be switched on.</p>
                )}
              </div>
            )}
            {!operator && <p className="mt-4 text-sm text-on-surface-muted">Only an operator can switch the listener or re-read the column.</p>}
          </Card>

          <Card title="The column" eyebrow={last ? `last read ${fmtDate(last.at)}` : 'not read yet'}>
            {last && (
              <p className="mb-4 text-sm text-on-surface-muted">
                <Hint id="stat.intake.last_poll">
                  <span>
                    {fmtInt(last.seen)} ticket(s) in the column, {fmtInt(last.read)} read this time, {fmtInt(last.skipped)} already handled at that revision, {fmtInt(last.registered)}{' '}
                    registered{last.queued ? `, ${fmtInt(last.queued)} waiting for a factory run to finish` : ''}.
                  </span>
                </Hint>
              </p>
            )}
            {data.rows.length === 0 ? (
              <EmptyState
                glyph="▤"
                title={listener.enabled ? 'No ticket has entered the watched column yet' : 'Nothing has been read'}
                reason={
                  listener.enabled
                    ? 'Move a ticket into the watched column on your board. The product reads it, tells it what a good acceptance test still needs, and registers it when the gaps close.'
                    : 'Switch the listener on to read the column. Until then nothing on that board is touched.'
                }
                data-testid="intake-empty"
              />
            ) : (
              <ul className="m-0 list-none p-0">
                {data.rows.map((row) => (
                  <Row key={row.key} row={row} />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </>
  )
}

export default IntakePage
