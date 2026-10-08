/**
 * Accept an invitation — the page the one-time link opens (/invite).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /invite, outside the authenticated shell: the only page a person
 *               who has no account yet ever sees apart from /login.
 * What it does: Turns a one-time link into an account the person controls. It reads the token
 *               from `?token=`, asks for a password twice (at least 12 characters; the two
 *               fields are compared in the browser so a mismatch is not a round trip, and the
 *               problem is said at the field it is about, which takes focus — P-397), posts
 *               `POST /invitations/accept`, and on success says which account is now live, in
 *               what role, and that the next step is to sign in with the password just chosen
 *               — no session is issued here, so the first thing the account does is prove it.
 *               Like /login it sits outside the shell, so it mounts its own "About this
 *               screen" block (the `/invite` entry in ui/src/help/help.ts).
 *               A link with no token, or one the server refuses (used, withdrawn, expired), is
 *               a plain sentence with a way forward: ask your admin for a new one.
 * How:          `useSearchParams` for the token → `useAcceptInvitation` on submit → the
 *               success panel replaces the form and links to /login. Nothing is stored in the
 *               browser and the token is never rendered.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
 *               (why the second person matters enough to have a page of their own)
 * Works with:   ui/src/api/hooks.ts (`useAcceptInvitation`), ui/src/App.tsx (the route, outside
 *               the shell, deliberately unlinked — see `App.reachability.test.ts`),
 *               ui/src/screens/Settings/InviteApproverCard.tsx (where the link comes from),
 *               ui/src/screens/Login/LoginPage.tsx (where it sends the person next),
 *               src/crb/server/routes/invitations.py (the route it posts to)
 * Tested by:    ui/src/screens/Invite/AcceptInvitePage.test.tsx
 * Touch when:   never for a new repository; the accept body or the minimum password length
 *               changes (they are the server's, `MIN_PASSWORD_LENGTH`).
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useAcceptInvitation } from '../../api/hooks'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { AboutThisScreen } from '../../components/Help'
import { TextField } from '../../components/Field'
import { Hint } from '../../components/Hint'
import { BRAND } from '../../components/Layout'

/** The server's own floor (`MIN_PASSWORD_LENGTH`); the browser says it before the round trip. */
export const MIN_PASSWORD = 12

/** What is wrong with the pair of passwords, or `''` when nothing is. */
export function passwordProblem(password: string, again: string): string {
  if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`
  if (password !== again) return 'The two passwords are not the same.'
  return ''
}

export function AcceptInvitePage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const accept = useAcceptInvitation()
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [touched, setTouched] = useState(false)
  const [asked, setAsked] = useState(0)
  const problem = passwordProblem(password, again)
  // the problem is said AT the field it is about (aria-invalid, described by it), and that
  // field takes focus on each refused submit; a server refusal takes focus too (P-397)
  const tooShort = touched && password.length < MIN_PASSWORD ? problem : undefined
  const mismatch = touched && !tooShort && problem ? problem : undefined
  const refused = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!asked) return
    const name = password.length < MIN_PASSWORD ? 'new-password' : 'new-password-again'
    document.querySelector<HTMLInputElement>(`input[name="${name}"]`)?.focus()
    // only on a submit: typing must never move the cursor
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asked])
  useEffect(() => {
    if (accept.isError) refused.current?.focus()
  }, [accept.isError, accept.error])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (accept.isPending) return
    setTouched(true)
    if (problem) {
      setAsked((n) => n + 1)
      return
    }
    accept.mutate({ token, password })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4 py-10 text-on-surface">
      <main className="w-full max-w-[420px] space-y-6">
        <header className="space-y-1 text-center">
          <div className="label">Accept your invitation</div>
          <h1 className="text-[26px] leading-8">{BRAND}</h1>
          <p className="text-sm text-on-surface-muted">Someone has invited you to review and sign off what this deployment measures. Choose a password and the account is yours.</p>
        </header>

        <section className="rounded-[var(--radius-card)] border border-border bg-surface-container p-6 shadow-[var(--shadow-card)]">
          {accept.isSuccess ? (
            <div className="space-y-4" data-testid="invite-accepted">
              <Hint as="p" id="stat.invite.accepted" className="m-0 text-[16px]">
                <strong>{accept.data.username}</strong> is now active as <strong>{accept.data.role}</strong>. Sign in with the password you have just chosen.
              </Hint>
              <Hint as={Link} id="link.invite.sign_in" to="/login" className="inline-block rounded-[4px] bg-primary px-4 py-3 text-[19px] leading-[1.2] text-on-primary no-underline">
                Sign in
              </Hint>
            </div>
          ) : !token ? (
            <Hint as="p" id="stat.invite.no_token" className="m-0 text-[16px]" data-testid="invite-no-token">
              This page needs the link from your invitation, and this address has no invitation in it. Open the link you were sent, or ask your admin for a new one.
            </Hint>
          ) : (
            <form onSubmit={submit} className="space-y-4" aria-label="Choose your password">
              <TextField
                label="New password"
                hint="field.invite.password"
                name="new-password"
                type="password"
                autoComplete="new-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                error={tooShort}
              />
              <TextField
                label="New password again"
                hint="field.invite.password_again"
                name="new-password-again"
                type="password"
                autoComplete="new-password"
                required
                value={again}
                onChange={(e) => setAgain(e.target.value)}
                error={mismatch}
              />
              {accept.isError && (
                <div ref={refused} tabIndex={-1} data-testid="invite-refused">
                  <ErrorState compact error={accept.error} title={accept.error.status === 401 ? 'This invitation link cannot be used' : undefined} />
                </div>
              )}
              <Button type="submit" variant="filled" hint="button.invite.accept" className="w-full" pending={accept.isPending}>
                {accept.isPending ? 'Setting your password…' : 'Set my password'}
              </Button>
            </form>
          )}
        </section>

        <p className="text-center text-[13px] text-on-surface-muted">An invitation link works once and expires. Nobody — including the admin who invited you — can read the password you choose here.</p>

        {/* Outside the shell, like /login: it mounts its own About block (G-926). */}
        <AboutThisScreen />
      </main>
    </div>
  )
}

export default AcceptInvitePage
