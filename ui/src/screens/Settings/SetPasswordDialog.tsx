/**
 * Set-password dialog — an admin gives one account a new password, twice, and is told what
 * the act did (F23's screen half; the recover-an-account journey's step 2).
 *
 * Navigation
 * ----------
 * What it is:   The dialog the Users card's "Set password" button opens: the new password
 *               typed twice, a 12-character floor checked before the request, and a success
 *               state that names the account and says its sessions ended.
 * What it does: Sends `PUT /users/{id}/password` once the two fields agree and are long
 *               enough, never echoes either value (both are `type=password`, both are
 *               cleared on success), and reports the server's own sentence on a refusal —
 *               409 `not_local` for an account the identity provider owns, 422 for a
 *               password under the floor. The success panel is the ACTIONS criterion: it
 *               names the account by username and says every session it held has ended, so
 *               the admin knows to tell the person to sign in again.
 * How:          `useSetUserPassword`; local state for the two fields and for the account the
 *               last success was for; `Dialog` (native `<dialog>`, focus trapped by the
 *               platform, content unmounted while closed so nothing is retained).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/UsersCard.tsx (opens it, one account at a time),
 *               ui/src/api/hooks.ts (`useSetUserPassword` — `PUT /users/{id}/password`),
 *               ui/src/components/Dialog.tsx (the modal shell), ui/src/components/Field.tsx
 *               (`TextField` — the two password inputs and their hints),
 *               ui/src/help/hints.ts (`field.settings.set_password*`,
 *               `button.settings.set_password_submit` — where the 12-character floor is
 *               stated), src/crb/server/routes/admin.py (`set_user_password` — the route and
 *               its refusals)
 * Tested by:    ui/src/screens/Settings/UsersCard.test.tsx (the mismatch, the floor, the
 *               success sentence, the 409 `not_local` path),
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts (an admin sets a persona's
 *               password and that persona signs in with it)
 * Touch when:   `MIN_PASSWORD_LENGTH` changes (src/crb/server/settings.py) — the floor here
 *               and the two hints that state it move with it.
 */
import { useState, type FormEvent } from 'react'
import { useSetUserPassword } from '../../api/hooks'
import type { User } from '../../api/types'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { ErrorState } from '../../components/ErrorState'
import { TextField } from '../../components/Field'

/** The server's floor (`MIN_PASSWORD_LENGTH`, src/crb/server/settings.py): checked here so a typo is refused before a request. */
export const MIN_PASSWORD_LENGTH = 12

interface Props {
  /** The account to set a password for; `null` keeps the dialog closed. */
  user: User | null
  onClose: () => void
}

/**
 * The dialog. It refuses locally on the two things a person gets wrong (a mismatch, a
 * password under the floor) and lets the server refuse everything else in its own words.
 */
export function SetPasswordDialog({ user, onClose }: Props) {
  const set = useSetUserPassword()
  const [pw, setPw] = useState('')
  const [again, setAgain] = useState('')
  const [local, setLocal] = useState('')
  const [done, setDone] = useState<string>('')

  // Closing clears everything, `done` included: this component stays mounted while the dialog is
  // shut, so a success left standing would greet the NEXT account opened with the last one's name.
  const close = () => {
    setPw('')
    setAgain('')
    setLocal('')
    setDone('')
    set.reset()
    onClose()
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!user) return
    if (pw.length < MIN_PASSWORD_LENGTH) {
      setLocal(`Use at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    if (pw !== again) {
      setLocal('The two passwords are not the same. Type the new one again.')
      return
    }
    setLocal('')
    set.mutate(
      { id: user.id, password: pw },
      {
        onSuccess: (u) => {
          setDone(u.username || u.display_name || u.id)
          setPw('')
          setAgain('')
        },
      },
    )
  }

  return (
    <Dialog open={user !== null} title={user ? `Set a password for ${user.username || user.display_name}` : 'Set a password'} onClose={close}>
      {user && (
        <form onSubmit={submit} className="space-y-4" data-testid="set-password-form">
          <p className="m-0 text-sm text-on-surface-muted">
            The password is sent once and never shown back. Every session this account holds ends on its next request, so tell the person to sign in again with the new password.
          </p>
          <TextField
            label="New password"
            hint="field.settings.set_password"
            type="password"
            required
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            data-testid="set-password-new"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
          />
          <TextField
            label="New password again"
            hint="field.settings.set_password_confirm"
            type="password"
            required
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            data-testid="set-password-again"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
          />
          {local && (
            <p role="alert" className="m-0 text-sm text-status-red" data-testid="set-password-refused">
              {local}
            </p>
          )}
          {set.isError && <ErrorState compact error={set.error} />}
          {done && (
            <p role="status" className="m-0 text-sm" data-testid="set-password-done">
              Password set for {done}. Every session that account held has ended — it signs in again with the new password.
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button onClick={close}>Close</Button>
            <Button type="submit" variant="filled" disabled={set.isPending} hint="button.settings.set_password_submit" data-testid="set-password-submit">
              {set.isPending ? 'Setting…' : 'Set password'}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  )
}
