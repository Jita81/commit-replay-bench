/**
 * The "Claude Code login" card — status for every role; paste, verify and remove for admins; the
 * value is never shown.
 *
 * Navigation
 * ----------
 * What it is:   The Settings card for the `claude setup-token` value the `auth: cli` builder
 *               mode uses.
 * What it does: Shows presence, the ≤ 4-character fingerprint and provenance (who set it,
 *               when) to any signed-in role; admins can paste a token (a `type="password"`
 *               field, cleared the moment the server accepts it — the value is not kept in
 *               state), verify it (the probe's status, model, CLI version and duration) and
 *               remove it. A shape rejection or a rate limit renders as the envelope without
 *               echoing the token.
 * How:          `useSecrets` → `StatusLine`; the form calls `useSaveClaudeCodeToken`;
 *               `CHECK_DISPLAY` maps a `LoginCheck` status to tone / glyph / wording.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Settings/claudeCodeLogin.ts (the hooks and types),
 *               ui/src/screens/Settings/SettingsPage.tsx (the host), ui/src/lib/auth.tsx
 *               (`can('admin')`), src/crb/server/routes/admin.py (the routes and their 422 /
 *               409 / 429 answers), src/crb/builders/claude_code.py (the `cli` auth mode
 *               that consumes the stored token)
 * Tested by:    ui/src/screens/Settings/ClaudeCodeLoginCard.test.tsx,
 *               ui/e2e/walkthrough/07-settings-and-a11y.spec.ts
 * Touch when:   a `LoginCheckStatus` is added on the server (src/crb/server/secrets.py) —
 *               add its `CHECK_DISPLAY` row; never for a new repository.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { TextField } from '../../components/Field'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { useAuth } from '../../lib/auth'
import { fmtDate } from '../../lib/format'
import type { Tone } from '../../lib/verdict'
import {
  LOGIN_TERMINAL,
  claudeCodeStatus,
  useCancelClaudeLogin,
  useClaudeLoginSession,
  useRemoveClaudeCodeToken,
  useSaveClaudeCodeToken,
  useSecrets,
  useStartClaudeLogin,
  useSubmitClaudeLoginCode,
  useVerifyClaudeCodeToken,
  type LoginCheck,
  type LoginCheckStatus,
  type LoginSession,
  type SecretStatus,
} from './claudeCodeLogin'

/** Tone / glyph / wording per verify outcome; only `ok` is green. */
const CHECK_DISPLAY: Record<LoginCheckStatus, { tone: Tone; glyph: string; label: string }> = {
  ok: { tone: 'green', glyph: '✓', label: 'ok — the login works' },
  invalid: { tone: 'red', glyph: '✕', label: 'invalid — the token was rejected (401)' },
  cli_missing: { tone: 'amber', glyph: '!', label: 'claude CLI not on the API host' },
  timeout: { tone: 'amber', glyph: '…', label: 'timed out' },
  error: { tone: 'amber', glyph: '!', label: 'error' },
}

/** Presence pill with the fingerprint and provenance, or "no token stored" with what `auth: cli` falls back to. */
function StatusLine({ status }: { status: SecretStatus | undefined }) {
  if (!status?.present) {
    return (
      <div className="flex flex-wrap items-center gap-2" data-testid="claude-login-status" data-present="false">
        <Pill tone="muted" glyph="–" label="Claude Code token: not stored">
          no token stored
        </Pill>
        <span className="text-xs text-on-surface-muted">
          <code>auth: cli</code> runs fall back to the worker&rsquo;s own <code>claude login</code>.
        </span>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="claude-login-status" data-present="true">
      <Pill tone="green" glyph="✓" label={`Claude Code token stored, ending ${status.fingerprint}`}>
        token stored · <span className="font-mono">…{status.fingerprint}</span>
      </Pill>
      <span className="text-xs text-on-surface-muted" data-testid="claude-login-provenance">
        set by <span className="font-semibold">{status.set_by || 'mounted file'}</span> · {fmtDate(status.set_at)}
      </span>
    </div>
  )
}

/** The verify probe's result line: status pill, detail, model, CLI version, duration. */
function CheckResult({ check }: { check: LoginCheck }) {
  const d = CHECK_DISPLAY[check.status] ?? CHECK_DISPLAY.error
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="claude-login-verify-result" data-status={check.status}>
      <Pill tone={d.tone} glyph={d.glyph} label={`Verify: ${d.label}`}>
        {d.label}
      </Pill>
      {check.detail && <span className="text-on-surface-muted">{check.detail}</span>}
      <span className="num font-mono text-on-surface-muted">
        {check.model}
        {check.cli_version ? ` · claude ${check.cli_version}` : ''} · {check.duration_s.toFixed(1)}s
      </span>
    </div>
  )
}

/**
 * Sign in with a Claude account from the browser: start a session (the API runs
 * `claude setup-token`), open Anthropic's page in a new tab, paste the code it shows,
 * poll until the token is stored on the API host. The token never reaches this
 * component — only the session state and, once done, the fingerprint.
 *
 * The tab is opened synchronously on the click (a blank window the response then
 * navigates) so a popup blocker does not eat it after the async start.
 */
function SignInPanel({ onDone }: { onDone: () => void }) {
  const start = useStartClaudeLogin()
  const submit = useSubmitClaudeLoginCode()
  const cancel = useCancelClaudeLogin()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const tab = useRef<Window | null>(null)
  const session = useClaudeLoginSession(sessionId)
  const s: LoginSession | undefined = session.data ?? (start.data && start.data.id === sessionId ? start.data : undefined)
  const done = s?.state === 'done'
  // fire `onDone` once per session on the transition to done — the parent passes a fresh
  // closure each render, so the callback lives in a ref rather than the effect's deps
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone
  const notified = useRef<string | null>(null)
  useEffect(() => {
    if (done && sessionId && notified.current !== sessionId) {
      notified.current = sessionId
      onDoneRef.current()
    }
  }, [done, sessionId])

  const begin = () => {
    // opened now, while the click is still a user gesture; navigated when the URL arrives
    tab.current = window.open('', '_blank', 'noopener')
    start.mutate(undefined, {
      onSuccess: (sess) => {
        setSessionId(sess.id)
        setCode('')
        if (tab.current && !tab.current.closed && sess.url) tab.current.location.href = sess.url
        else if (sess.url) window.open(sess.url, '_blank', 'noopener')
      },
      onError: () => {
        if (tab.current && !tab.current.closed) tab.current.close()
      },
    })
  }
  const send = (e: FormEvent) => {
    e.preventDefault()
    if (!sessionId || !code.trim()) return
    submit.mutate({ id: sessionId, code: code.trim() }, { onSuccess: () => setCode('') })
  }
  const stop = () => {
    if (sessionId) cancel.mutate(sessionId)
    setSessionId(null)
    start.reset()
    submit.reset()
  }

  return (
    <div className="space-y-3 border-t border-border pt-4" data-testid="claude-signin" data-state={s?.state ?? 'idle'}>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="filled" onClick={begin} disabled={start.isPending || (Boolean(s) && !LOGIN_TERMINAL.has(s!.state))} data-testid="claude-signin-start">
          {start.isPending ? 'Starting sign-in…' : 'Sign in with your Claude account'}
        </Button>
        {s && !LOGIN_TERMINAL.has(s.state) && (
          <Button variant="outlined" size="sm" onClick={stop} data-testid="claude-signin-cancel">
            Cancel
          </Button>
        )}
        <span className="text-xs text-on-surface-muted">
          Opens Anthropic&rsquo;s sign-in page in a new tab; the token is minted on the API host and stored there — it never passes through this browser.
        </span>
      </div>
      {start.isError && <ErrorState compact error={start.error} />}
      {s && (s.state === 'awaiting_code' || s.state === 'exchanging') && (
        <form onSubmit={send} className="grid gap-3 sm:grid-cols-[1fr_auto]" aria-label="Paste the sign-in code">
          <TextField
            label="Code from Anthropic"
            type="password"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="paste the code the page shows after you approve"
            data-testid="claude-signin-code"
            hint={
              s.state === 'exchanging'
                ? 'Exchanging the code for a token…'
                : s.url
                  ? 'If the tab did not open, use the link below. Approve, then paste the code shown.'
                  : 'Approve in the tab, then paste the code shown.'
            }
          />
          <div className="flex items-end">
            <Button type="submit" variant="filled" disabled={submit.isPending || s.state === 'exchanging' || !code.trim()} data-testid="claude-signin-submit">
              {submit.isPending || s.state === 'exchanging' ? 'Exchanging…' : 'Finish sign-in'}
            </Button>
          </div>
          {s.state === 'awaiting_code' && s.url && (
            <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-xs sm:col-span-2" data-testid="claude-signin-url">
              Open the sign-in page ↗
            </a>
          )}
          {submit.isError && (
            <div className="sm:col-span-2">
              <ErrorState compact error={submit.error} />
            </div>
          )}
        </form>
      )}
      {s && LOGIN_TERMINAL.has(s.state) && (
        <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="claude-signin-result" data-state={s.state}>
          <Pill tone={s.state === 'done' ? 'green' : s.state === 'failed' ? 'red' : 'muted'} glyph={s.state === 'done' ? '✓' : s.state === 'failed' ? '✕' : '–'} label={`Sign-in ${s.state}`}>
            {s.state === 'done' ? `signed in · token stored …${s.fingerprint}` : s.state}
          </Pill>
          {s.detail && <span className="text-on-surface-muted">{s.detail}</span>}
        </div>
      )}
    </div>
  )
}

/**
 * The "Claude Code login" card. Any signed-in role sees the status (presence,
 * ≤4-char fingerprint, who/when); admins can sign in with a Claude account from the
 * browser (the API runs `claude setup-token` and stores the result), or paste a
 * `claude setup-token` value, verify it and remove it. The paste field is
 * `type="password"`, never echoed, and cleared the moment the server accepts it — the
 * value is not kept in state.
 */
export function ClaudeCodeLoginCard() {
  const { can } = useAuth()
  const admin = can('admin')
  const secrets = useSecrets()
  const save = useSaveClaudeCodeToken()
  const remove = useRemoveClaudeCodeToken()
  const verify = useVerifyClaudeCodeToken()
  const [token, setToken] = useState('')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const value = token.trim()
    if (!value) return
    verify.reset()
    save.mutate(value, { onSuccess: () => setToken('') })
  }

  return (
    <Card title="Claude Code login" eyebrow="claude setup-token · auth: cli">
      <div className="space-y-4">
        <QueryBoundary query={secrets} loading="Loading login status…">
          {(list) => <StatusLine status={claudeCodeStatus(list)} />}
        </QueryBoundary>
        <p className="m-0 text-sm text-on-surface-muted" data-testid="claude-login-instructions">
          Sign in with your Claude account below (the API host runs <code>claude setup-token</code> for you), or run it on any machine and paste the
          token; either way it is stored owner-only on the API host under <code>CRB_HOME/secrets</code> and forwarded to builders only in{' '}
          <code>auth: cli</code> mode.
          {admin && secrets.data?.secrets_dir && (
            <>
              {' '}
              On this host: <code className="break-all">{secrets.data.secrets_dir}</code>.
            </>
          )}
        </p>
        {admin ? (
          <>
            <SignInPanel onDone={() => verify.reset()} />
            <form onSubmit={submit} className="grid gap-3 border-t border-border pt-4 sm:grid-cols-[1fr_auto]" aria-label="Save Claude Code token">
              <TextField
                label="Token"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder="sk-ant-oat01-…"
                data-testid="claude-login-token"
                hint="Never shown again after saving; only the last four characters are reported."
              />
              <div className="flex items-end">
                <Button type="submit" variant="filled" disabled={save.isPending || !token.trim()} data-testid="claude-login-save">
                  {save.isPending ? 'Saving…' : 'Save token'}
                </Button>
              </div>
              {save.isError && (
                <div className="sm:col-span-2">
                  <ErrorState compact error={save.error} />
                </div>
              )}
            </form>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outlined"
                onClick={() => verify.mutate()}
                disabled={verify.isPending || !claudeCodeStatus(secrets.data)?.present}
                data-testid="claude-login-verify"
              >
                {verify.isPending ? 'Verifying…' : 'Verify login'}
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  verify.reset()
                  remove.mutate()
                }}
                disabled={remove.isPending || !claudeCodeStatus(secrets.data)?.present}
                data-testid="claude-login-remove"
              >
                {remove.isPending ? 'Removing…' : 'Remove token'}
              </Button>
              <span className="text-xs text-on-surface-muted">Verify runs one no-tool Haiku turn through the builder&rsquo;s own environment (at most once every 10 s).</span>
            </div>
            {verify.data && <CheckResult check={verify.data} />}
            {verify.isError && <ErrorState compact error={verify.error} />}
            {remove.isError && <ErrorState compact error={remove.error} />}
          </>
        ) : (
          <p className="m-0 text-xs text-on-surface-muted" data-testid="claude-login-readonly">
            Only an admin can save, verify or remove the token.
          </p>
        )}
      </div>
    </Card>
  )
}

export default ClaudeCodeLoginCard
