/**
 * Go-live attestations — where an admin records an operator act the product cannot see.
 *
 * Navigation
 * ----------
 * What it is:   The admin's card on /settings for the go-live lines only the operator can
 *               prove (the egress test, the rehearsed restore, the penetration test and the
 *               rest of DEPLOYMENT §8's "operator attests" lines).
 * What it does: Lists each of those lines with its state; records an attestation — which line,
 *               what was done and the day it was done — through `PUT /settings/attestations/
 *               {line}`, and says what it recorded, naming the line and the day; withdraws the
 *               attestation in force through `DELETE`, after asking, and says so. The server
 *               names who recorded it; the card never invents a record and offers no way to
 *               attest a line the product proves by its own check.
 * How:          `useGoLive` for the lines, `useAttest` and `useWithdrawAttestation` for the
 *               writes; a native date input capped at today; `ErrorState` shows the server's
 *               refusal in its own words.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0031-go-live-lines-are-proven-or-attested.md
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (mounts it for an admin),
 *               ui/src/screens/Posture/GoLiveList.tsx (where a reviewer reads the result),
 *               ui/src/api/hooks.ts (`useGoLive`, `useAttest`, `useWithdrawAttestation`),
 *               src/crb/server/routes/golive.py (the routes and their refusals),
 *               docs/DEPLOYMENT.md#81-record-what-only-you-can-prove (the guide)
 * Tested by:    ui/src/screens/Settings/AttestationsCard.test.tsx,
 *               ui/e2e/walkthrough/14-go-live.spec.ts
 * Touch when:   never for a new repository; the attestation body changes in
 *               src/crb/server/routes/golive.py.
 */
import { useState, type FormEvent } from 'react'
import { useAttest, useGoLive, useWithdrawAttestation } from '../../api/hooks'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { GOLIVE_STATE } from '../Posture/GoLiveList'

/** Today as the date input wants it (`YYYY-MM-DD`, the browser's own day). */
function today(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function AttestationsCard() {
  const golive = useGoLive()
  const attest = useAttest()
  const withdraw = useWithdrawAttestation()
  const [line, setLine] = useState('')
  const [statement, setStatement] = useState('')
  const [day, setDay] = useState(today())
  const [said, setSaid] = useState('')
  const [asking, setAsking] = useState('')

  return (
    <Card id="golive-attestations" title={<Hint id="tile.settings.attestations">Go-live attestations</Hint>} eyebrow="admin · DEPLOYMENT §8">
      <QueryBoundary query={golive} loading="Reading the go-live checklist…">
        {(g) => {
          const operator = g.lines.filter((l) => l.proves === 'operator')
          const chosen = line || operator[0]?.id || ''
          const title = (id: string) => operator.find((l) => l.id === id)?.title ?? id
          const submit = (e: FormEvent) => {
            e.preventDefault()
            setSaid('')
            attest.mutate(
              { line: chosen, statement, performed_on: day },
              {
                onSuccess: () => {
                  setSaid(`Recorded: “${title(chosen)}” was done on ${day}. The Deployment page now shows it as attested, with your name.`)
                  setStatement('')
                },
              },
            )
          }
          return (
            <div className="space-y-4">
              <p className="m-0 text-sm text-on-surface-muted">
                These lines are acts only you can do on your own infrastructure; the product cannot see them. Record each one when it is done: what was done, where its evidence is kept, and the day. The lines the product proves by its own check are not here — nobody can attest those. Guide: <DocLink to="DEPLOYMENT#81-record-what-only-you-can-prove">Record what only you can prove</DocLink>.
              </p>
              <ul className="m-0 list-none space-y-2 p-0" data-testid="attestations-list">
                {operator.map((l) => {
                  const st = GOLIVE_STATE[l.state]
                  return (
                    <li key={l.id} className="flex flex-wrap items-start gap-2 text-sm" data-testid={`attestation-${l.id}`}>
                      <Pill tone={st.tone} glyph={st.glyph} size="xs" label={`${l.title}: ${st.label}`} hint="pill.posture.golive_state">
                        {st.label}
                      </Pill>
                      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                        <span className="font-semibold">{l.title}</span>
                        <span className="block text-xs text-on-surface-muted">{l.detail}{l.attestation ? ` — “${l.attestation.statement}”` : ''}</span>
                      </span>
                      {l.attestation &&
                        (asking === l.id ? (
                          <span className="flex items-center gap-2">
                            <span className="text-xs">Withdraw it? The line reads unproven again.</span>
                            <Button
                              size="sm"
                              variant="filled"
                              hint="button.settings.withdraw_confirm"
                              disabled={withdraw.isPending}
                              data-testid={`withdraw-confirm-${l.id}`}
                              onClick={() =>
                                withdraw.mutate(
                                  { line: l.id },
                                  {
                                    onSuccess: () => {
                                      setAsking('')
                                      setSaid(`Withdrawn: “${l.title}” reads unproven again. The withdrawal is on record.`)
                                    },
                                  },
                                )
                              }
                            >
                              Withdraw
                            </Button>
                            <Button size="sm" hint="button.settings.withdraw_keep" onClick={() => setAsking('')}>
                              Keep it
                            </Button>
                          </span>
                        ) : (
                          <Button size="sm" hint="button.settings.withdraw" data-testid={`withdraw-${l.id}`} onClick={() => setAsking(l.id)}>
                            Withdraw…
                          </Button>
                        ))}
                    </li>
                  )
                })}
              </ul>
              <form onSubmit={submit} className="space-y-3" data-testid="attest-form">
                <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
                  <SelectField label="Line" hint="field.settings.attest_line" required value={chosen} onChange={(e) => setLine(e.target.value)} data-testid="attest-line">
                    {operator.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.title}
                      </option>
                    ))}
                  </SelectField>
                  <TextField label="Day it was done" hint="field.settings.attest_day" type="date" required max={today()} value={day} onChange={(e) => setDay(e.target.value)} data-testid="attest-day" />
                </div>
                <TextArea
                  label="What was done, and where its evidence is kept"
                  hint="field.settings.attest_statement"
                  required
                  maxLength={500}
                  rows={3}
                  value={statement}
                  onChange={(e) => setStatement(e.target.value)}
                  data-testid="attest-statement"
                />
                {attest.isError && <ErrorState compact error={attest.error} />}
                {withdraw.isError && <ErrorState compact error={withdraw.error} />}
                {said && (
                  <p role="status" className="m-0 text-sm" data-testid="attest-done">
                    {said}
                  </p>
                )}
                <Button type="submit" variant="filled" hint="button.settings.attest" disabled={attest.isPending || !chosen} data-testid="attest-submit">
                  {attest.isPending ? 'Recording…' : 'Record attestation'}
                </Button>
              </form>
            </div>
          )
        }}
      </QueryBoundary>
    </Card>
  )
}
