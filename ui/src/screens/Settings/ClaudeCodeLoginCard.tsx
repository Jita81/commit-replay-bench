import { useState, type FormEvent } from 'react'
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
  claudeCodeStatus,
  useRemoveClaudeCodeToken,
  useSaveClaudeCodeToken,
  useSecrets,
  useVerifyClaudeCodeToken,
  type LoginCheck,
  type LoginCheckStatus,
  type SecretStatus,
} from './claudeCodeLogin'

const CHECK_DISPLAY: Record<LoginCheckStatus, { tone: Tone; glyph: string; label: string }> = {
  ok: { tone: 'green', glyph: '✓', label: 'ok — the login works' },
  invalid: { tone: 'red', glyph: '✕', label: 'invalid — the token was rejected (401)' },
  cli_missing: { tone: 'amber', glyph: '!', label: 'claude CLI not on the API host' },
  timeout: { tone: 'amber', glyph: '…', label: 'timed out' },
  error: { tone: 'amber', glyph: '!', label: 'error' },
}

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
 * The "Claude Code login" card. Any signed-in role sees the status (presence,
 * ≤4-char fingerprint, who/when); admins can paste a `claude setup-token` value,
 * verify it and remove it. The paste field is `type="password"`, never echoed,
 * and cleared the moment the server accepts it — the value is not kept in state.
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
          Run <code>claude setup-token</code> on any machine, paste the token here; it is stored owner-only on the API host under{' '}
          <code>CRB_HOME/secrets</code> and forwarded to builders only in <code>auth: cli</code> mode.
          {admin && secrets.data?.secrets_dir && (
            <>
              {' '}
              On this host: <code className="break-all">{secrets.data.secrets_dir}</code>.
            </>
          )}
        </p>
        {admin ? (
          <>
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
