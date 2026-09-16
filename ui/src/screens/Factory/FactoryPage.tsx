/**
 * Factory — the forward-mode surface: one repo's frozen backlog and the state of every item
 * (/factory).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /factory: the ACTIVE frozen backlog and the factory tasks for
 *               one repo, read-only (registering a backlog, signing a gap and running the loop
 *               are API / CLI actions — docs/API.md "Factory").
 * What it does: Reads `GET /factory/{repo}/backlog` and `/tasks` and renders them (frozen
 *               pill, backlog hash, per-item facts, per-task DoR gaps, route hint, RED proof,
 *               build status, PR link, review verdict, last event). A 404 on the backlog means
 *               no backlog is registered for the repo and is rendered as that instruction —
 *               never as an error, never as fabricated rows; any other error is the envelope.
 * How:          `useRepoParam` → the two hooks → per-card pending / error / data branches
 *               (`noBacklog` picks the 404 case). `/tasks` is a bare list, not a `Page`.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/api/hooks.ts (`useFactoryBacklog`, `useFactoryTasks`), ui/src/api/types.ts
 *               (`FactoryBacklog`, `FactoryBacklogItem`, `FactoryTask` — mirror
 *               `FactoryBacklogOut` / `FactoryTaskOut`), src/crb/server/routes/factory.py,
 *               src/crb/server/factory_state.py (`task_views` — what a task row folds from),
 *               docs/API.md (the "Factory" section)
 * Tested by:    ui/src/screens/Factory/FactoryPage.test.tsx
 * Touch when:   a factory action moves into the UI (freeze, sign a gap, queue the run) — add
 *               the mutation hook and the operator / approver gate; a field is added to
 *               `FactoryTaskOut`.
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

  // 404 `not_found` = no backlog registered for this repo (the server's documented answer)
  const noBacklog = (e: unknown) => e !== null && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404

  return (
    <>
      <PageHeader
        eyebrow="Factory · forward mode"
        title="Factory"
        purpose="Manufacture new work under the same governance as replay: a frozen backlog (hashed), Definition-of-Ready gaps signed by an approver, a RED proof before any build, a branch + PR in the customer's repo, and a review verdict — every step ledgered."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo && <EmptyState title="Choose a repo" reason="The factory works one repository at a time." action={<LinkButton to="/repos">Go to repos</LinkButton>} />}
      {repo && (
        <>
          <Card title="Backlog" eyebrow="frozen · hashed">
            {backlog.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
            {backlog.isError && (noBacklog(backlog.error) ? (
              <EmptyState
                glyph="⚙"
                title="No backlog registered for this repo"
                reason={`Freeze one with POST /factory/${repo}/backlog (or the CLI): the items are validated, hashed and recorded as the first event of the evidence chain; a factory run then works them in dependency order.`}
                data-testid="factory-no-backlog"
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
            {tasks.isError && (noBacklog(tasks.error) ? <EmptyState compact glyph="⚙" title="No factory tasks — no backlog registered" /> : <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />)}
            {tasks.data && tasks.data.length === 0 && <EmptyState compact title="No factory tasks yet" />}
            {tasks.data && tasks.data.length > 0 && (
              <ul className="m-0 list-none divide-y divide-border p-0 text-sm">
                {tasks.data.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center gap-2 py-1.5">
                    <span className="font-mono text-xs text-on-surface-muted">{t.id}</span>
                    <span>{t.title}</span>
                    <span className="font-mono text-xs text-on-surface-muted" title={`route hint: ${t.route_hint}`}>
                      {t.status} · {t.route_hint}
                    </span>
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
