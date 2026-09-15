/**
 * Factory (phase P6) — the forward-mode surface, rendering an honest "not yet" until the phase
 * ships (/factory).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /factory: the frozen backlog and the factory tasks for one repo.
 * What it does: Reads `GET /factory/{repo}/backlog` and `/tasks` and renders them (frozen
 *               pill, backlog hash, per-task DoR gaps, RED proof, build status, PR link, review
 *               verdict). Until P6 lands the server answers 404 / 501; a 404 is rendered as
 *               the designed "not enabled yet" empty state and any other error as the
 *               envelope — nothing is fabricated in the meantime.
 * How:          `useRepoParam` → the two hooks → per-card pending / error / data branches
 *               (`notYet` picks the 404 case).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useFactoryBacklog`, `useFactoryTasks`), ui/src/api/types.ts
 *               (`FactoryBacklog`, `FactoryTask` — provisional shapes),
 *               src/crb/server/routes/factory.py
 *               (answers 501 `not_implemented` until P6), docs/API.md (the "Factory (phase P6)"
 *               section)
 * Tested by:    untested — the phase is not implemented server-side; the screen only renders
 *               the contract's empty / error states (tests/test_server_routes_factory.py pins
 *               the 501)
 * Touch when:   P6 lands — the shapes in ui/src/api/types.ts become final and this screen
 *               gains its actions (freeze, sign a gap); never for a new repository.
 */
import { useFactoryBacklog, useFactoryTasks } from '../../api/hooks'
import { LinkButton } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { fmtDate, fmtInt, shortId } from '../../lib/format'

/**
 * Factory (phase P6) — reads the contract's factory endpoints and renders an
 * honest "not yet" state. Manufacturing new work under the same governance
 * (frozen backlog hash → DoR gaps → RED proof → build → PR → review) lands
 * here once the phase ships; until then a 404 from the server is the
 * designed empty state, and any other error is shown as such.
 */
export function FactoryPage() {
  const [repo, setRepo] = useRepoParam()
  const backlog = useFactoryBacklog(repo)
  const tasks = useFactoryTasks(repo)

  const notYet = (e: unknown) => e !== null && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404

  return (
    <>
      <PageHeader
        eyebrow="Factory · phase P6"
        title="Factory"
        purpose="Manufacture new work under the same governance as replay: a frozen backlog (hashed), Definition-of-Ready gaps signed by an approver, a RED proof before any build, a branch + PR in the customer's repo, and a review verdict — every step ledgered."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo && <EmptyState title="Choose a repo" reason="The factory works one repository at a time." action={<LinkButton to="/repos">Go to repos</LinkButton>} />}
      {repo && (
        <>
          <Card title="Backlog" eyebrow="frozen · hashed">
            {backlog.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
            {backlog.isError && (notYet(backlog.error) ? (
              <EmptyState
                glyph="⚙"
                title="Factory not enabled yet (phase P6)"
                reason="This surface is wired to the contract's factory endpoints and will populate when the server ships phase P6. Nothing is fabricated in the meantime."
                data-testid="factory-not-yet"
              />
            ) : (
              <ErrorState error={backlog.error} onRetry={() => void backlog.refetch()} />
            ))}
            {backlog.data && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Pill tone={backlog.data.frozen_at ? 'primary' : 'amber'} glyph={backlog.data.frozen_at ? '❄' : '○'} size="xs" label={backlog.data.frozen_at ? `Frozen at ${fmtDate(backlog.data.frozen_at)}` : 'Not frozen'}>
                    {backlog.data.frozen_at ? 'frozen' : 'not frozen'}
                  </Pill>
                  <span className="font-mono text-xs" title={backlog.data.hash}>
                    hash {shortId(backlog.data.hash, 16)}
                  </span>
                  <span className="text-xs text-on-surface-muted">{fmtInt(backlog.data.items.length)} items</span>
                </div>
                {backlog.data.items.length === 0 ? (
                  <EmptyState compact title="Empty backlog" />
                ) : (
                  <ul className="m-0 list-none divide-y divide-border p-0 text-sm">
                    {backlog.data.items.map((i) => (
                      <li key={i.id} className="flex flex-wrap items-center gap-2 py-1.5">
                        <span className="font-mono text-xs text-on-surface-muted">{i.id}</span>
                        <span>{i.title}</span>
                        <span className="font-mono text-xs text-on-surface-muted">
                          {i.capability_class} · {i.size}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Card>
          <Card title="Tasks" eyebrow="DoR · RED proof · build · PR · review">
            {tasks.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
            {tasks.isError && (notYet(tasks.error) ? <EmptyState compact glyph="⚙" title="No factory tasks (phase P6)" /> : <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />)}
            {tasks.data && tasks.data.items.length === 0 && <EmptyState compact title="No factory tasks yet" />}
            {tasks.data && tasks.data.items.length > 0 && (
              <ul className="m-0 list-none divide-y divide-border p-0 text-sm">
                {tasks.data.items.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center gap-2 py-1.5">
                    <span className="font-mono text-xs text-on-surface-muted">{t.id}</span>
                    <span>{t.title}</span>
                    {t.dor_gaps.length > 0 && (
                      <Pill tone="amber" glyph="⚠" size="xs" label={`${t.dor_gaps.length} Definition-of-Ready gap(s)`}>
                        {t.dor_gaps.length} DoR gap{t.dor_gaps.length === 1 ? '' : 's'}
                      </Pill>
                    )}
                    <Pill tone={t.red_proof === true ? 'green' : t.red_proof === false ? 'red' : 'muted'} glyph={t.red_proof === true ? '✓' : t.red_proof === false ? '✗' : '·'} size="xs" label={`RED proof: ${t.red_proof === null ? 'not run' : t.red_proof ? 'held' : 'failed'}`}>
                      RED proof
                    </Pill>
                    <span className="font-mono text-xs">{t.build_status}</span>
                    {t.pr_url && (
                      <a href={t.pr_url} className="text-xs" target="_blank" rel="noreferrer">
                        PR ↗
                      </a>
                    )}
                    {t.review_verdict && <span className="text-xs text-on-surface-muted">review: {t.review_verdict}</span>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </>
  )
}

export default FactoryPage
