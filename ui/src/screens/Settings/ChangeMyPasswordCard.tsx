/**
 * Change my password — the self-service door of the recover-an-account journey, on the screen
 * every signed-in role can open (F23).
 *
 * Navigation
 * ----------
 * What it is:   The card on /settings for the account the reader is signed in as: the current
 *               password, the new one twice, and a success state that says this browser stays
 *               signed in while every other session of the account ends.
 * What it does: Sends `PUT /users/me/password`, which needs the current password — so a
 *               borrowed session cannot change it — and reports the server's own words on a
 *               refusal: 401 when the current password is wrong, 429 with the seconds to wait
 *               after five wrong attempts in a minute, 422 under the 12-character floor. An
 *               account issued by the organisation's identity provider has no password here:
 *               the card says it is managed by your identity provider and offers no form, the
 *               same thing the API says with 409 `not_local`.
 * How:          `useAuth().me` decides which of the two states renders (`issuer` is `local`
 *               for an account this deployment holds); `useChangeOwnPassword` for the write;
 *               both fields are `type=password` and cleared on success.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/SettingsPage.tsx (mounts it for every signed-in role),
 *               ui/src/api/hooks.ts (`useChangeOwnPassword` — `PUT /users/me/password`),
 *               ui/src/lib/auth.tsx (`useAuth` — the principal and its issuer),
 *               ui/src/components/Field.tsx (`TextField` and its hints),
 *               ui/src/help/hints.ts (`field.settings.my_*` — where the limiter and the
 *               12-character floor are stated), src/crb/server/routes/admin.py
 *               (`change_own_password` — the route, the limiter and `not_local`)
 * Tested by:    ui/src/screens/Settings/ChangeMyPasswordCard.test.tsx
 * Touch when:   the local issuer name changes (src/crb/server/auth.py `LOCAL_ISSUER`) or the
 *               limiter's shape changes — the hint states it.
 */
import { useState, type FormEvent } from 'react'
import { useChangeOwnPassword } from '../../api/hooks'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { TextField } from '../../components/Field'
import { DocLink } from '../../components/Help'
import { Hint } from '../../components/Hint'
import { useAuth } from '../../lib/auth'
import { MIN_PASSWORD_LENGTH } from './SetPasswordDialog'

/** The issuer a local account carries (`src/crb/server/auth.py` `LOCAL_ISSUER`). */
const LOCAL_ISSUER = 'local'

/**
 * The card. An identity-provider account reads one sentence and no form; a local account gets
 * the three fields and a success state naming what changed and what ended.
 */
export function ChangeMyPasswordCard() {
  const { me } = useAuth()
  const change = useChangeOwnPassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [local, setLocal] = useState('')
  const [done, setDone] = useState(false)

  if (!me) return null

  const isLocal = !me.issuer || me.issuer === LOCAL_ISSUER
  if (!isLocal) {
    return (
      <Card title="Change my password" eyebrow="your account">
        <p className="m-0 text-sm" data-testid="my-password-oidc">
          This account is managed by your identity provider. Its password is changed there, not here, and an admin of this deployment cannot set it. Guide: <DocLink to="SECURITY#34-authentication-and-authorisation--crbserverauth">How sign-in and roles work</DocLink>.
        </p>
      </Card>
    )
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setDone(false)
    if (next.length < MIN_PASSWORD_LENGTH) {
      setLocal(`Use at least ${MIN_PASSWORD_LENGTH} characters for the new password.`)
      return
    }
    if (next !== again) {
      setLocal('The two new passwords are not the same. Type the new one again.')
      return
    }
    setLocal('')
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setDone(true)
          setCurrent('')
          setNext('')
          setAgain('')
        },
      },
    )
  }

  return (
    <Card title={<Hint id="tile.settings.my_password">Change my password</Hint>} eyebrow="your account · local">
      <form onSubmit={submit} className="space-y-4" data-testid="my-password-form">
        <p className="m-0 text-sm text-on-surface-muted">
          Your current password proves the session is yours. After the change this browser stays signed in and every other session of your account ends. If you cannot sign in at all, an admin of this deployment sets a new password for you: <DocLink to="OPERATOR#9-users">Users, and what to do when nobody can sign in</DocLink>.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <TextField label="Current password" hint="field.settings.my_current_password" type="password" required autoComplete="current-password" data-testid="my-password-current" value={current} onChange={(e) => setCurrent(e.target.value)} />
          <TextField label="New password" hint="field.settings.my_new_password" type="password" required minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" data-testid="my-password-new" value={next} onChange={(e) => setNext(e.target.value)} />
          <TextField label="New password again" hint="field.settings.my_new_password_confirm" type="password" required minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" data-testid="my-password-again" value={again} onChange={(e) => setAgain(e.target.value)} />
        </div>
        {local && (
          <p role="alert" className="m-0 text-sm text-status-red" data-testid="my-password-refused">
            {local}
          </p>
        )}
        {change.isError && <ErrorState compact error={change.error} />}
        {done && (
          <p role="status" className="m-0 text-sm" data-testid="my-password-done">
            Your password is changed. This browser is still signed in as {me.display_name || me.email}; every other session of your account has ended.
          </p>
        )}
        <div>
          <Button type="submit" variant="filled" disabled={change.isPending} hint="button.settings.change_my_password" data-testid="my-password-submit">
            {change.isPending ? 'Changing…' : 'Change my password'}
          </Button>
        </div>
      </form>
    </Card>
  )
}
