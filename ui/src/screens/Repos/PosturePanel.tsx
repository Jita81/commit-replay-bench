/**
 * The repository's Posture panel — qualified N of M in the posture that will grade it
 * (ADR-0019), why the rest are not, and a Qualify button that spends nothing.
 *
 * Navigation
 * ----------
 * What it is:   The Overview card on /repos/:name that reads `GET /repos/{name}/posture`.
 * What it does: Shows the posture class, the image, the exact toolchain and whether dependency
 *               provisioning is on; how many tasks are proven there out of how many; each
 *               refusal code with how many tasks it keeps out, its fix and a guide link; why the
 *               record is stale; and — for an operator only — "Qualify for this posture — no
 *               model spend", which queues a `qualify` run and opens it.
 * How:          `useRepoPosture` + `useQualifyRepo`; every element carries a registry hint; the
 *               guide link turns the served `docs/OPERATOR.md#…` anchor into /help/docs.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0019-qualification-is-posture-relative.md
 * Works with:   ui/src/api/hooks.ts (`useRepoPosture`, `useQualifyRepo`), ui/src/api/types.ts
 *               (`RepoPosture`), ui/src/screens/Repos/RepoDetail.tsx (mounts it on Overview),
 *               ui/src/help/hints.ts (the `*.repo.posture*` ids), src/crb/server/posture_view.py
 *               (what the route serves)
 * Tested by:    ui/src/screens/Repos/PosturePanel.test.tsx, ui/src/help/hints-ratchet.test.tsx
 * Touch when:   `GET /repos/{name}/posture` gains a field a reader needs (type it first).
 */
import { Link, useNavigate } from 'react-router'
import { useQualifyRepo, useRepoPosture } from '../../api/hooks'
import type { RepoPosture } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { QueryBoundary } from '../../components/QueryBoundary'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtInt } from '../../lib/format'

/** `docs/OPERATOR.md#7a-…` → `/help/docs/OPERATOR#7a-…` (the bundled guide). */
export function guideHref(doc: string): string {
  const m = /^docs\/([A-Z-]+)\.md(#.*)?$/.exec(doc)
  return m ? `/help/docs/${m[1]}${m[2] ?? ''}` : '/help'
}

function Body({ p }: { p: RepoPosture }) {
  const provisioning = p.provisioning.enabled === true
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <StatTile
          label="Qualified in this posture"
          hint="stat.repo.qualified"
          value={`${fmtInt(p.qualified)} of ${fmtInt(p.total)}`}
          n={p.total}
          apparatus={p.posture_class ? `posture ${p.posture_class} · measured by a qualify run, no model spend` : 'no posture recorded yet'}
        />
      </div>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="posture-facts">
        <dt className="text-on-surface-muted">Class</dt>
        <dd>
          <Pill tone={p.posture_class ? 'blue' : 'muted'} glyph="◆" hint="pill.repo.posture_class" data-testid="posture-class">
            {p.posture_class || 'none recorded'}
          </Pill>
        </dd>
        <dt className="text-on-surface-muted">Image</dt>
        <dd className="break-all font-mono text-xs" data-testid="posture-image">
          <Hint id="text.repo.posture_image">{p.image_ref || (p.executor === 'local' ? 'the host (no image)' : 'none named')}</Hint>
        </dd>
        <dt className="text-on-surface-muted">Toolchain</dt>
        <dd className="font-mono text-xs" data-testid="posture-toolchain">
          <Hint id="text.repo.posture_toolchain">{p.posture.toolchain || 'not probed yet'}</Hint>
        </dd>
        <dt className="text-on-surface-muted">Provisioning</dt>
        <dd>
          <Pill tone={provisioning ? 'green' : 'muted'} glyph={provisioning ? '✓' : '·'} hint="pill.repo.provisioning" data-testid="posture-provisioning">
            {provisioning ? 'on' : 'off'}
          </Pill>
        </dd>
      </dl>
      {p.stale_reason && (
        <p className="text-sm text-on-surface-muted" data-testid="posture-stale">
          <Hint id="text.repo.posture_stale">{p.stale_reason}</Hint>
        </p>
      )}
      {p.refusals_by_code.length > 0 && (
        <ul className="space-y-2 text-sm" aria-label="Why tasks are not qualified here" data-testid="posture-refusals">
          {p.refusals_by_code.map((r) => (
            <li key={r.code} className="flex flex-wrap items-baseline gap-2" data-testid={`refusal-${r.code}`}>
              <Pill tone="amber" glyph="!" size="xs" hint="pill.repo.refusal_code" label={`${r.code}: ${r.n} task${r.n === 1 ? '' : 's'}`}>
                {r.code} · {fmtInt(r.n)}
              </Pill>
              <span>{r.fix}</span>
              {r.doc && (
                <Hint as={Link} id="link.repo.refusal_guide" to={guideHref(r.doc)} className="text-xs underline">
                  What to do
                </Hint>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** The Posture card (see the module docstring). */
export function PosturePanel({ name }: { name: string }) {
  const { can } = useAuth()
  const posture = useRepoPosture(name)
  const qualify = useQualifyRepo()
  const navigate = useNavigate()
  return (
    <Card
      title="Posture"
      actions={
        can('operator') && (
          <Button
            size="sm"
            variant="filled"
            hint="button.repo.qualify"
            disabled={qualify.isPending}
            onClick={() => qualify.mutate(name, { onSuccess: (run) => navigate(`/runs/${run.id}`) })}
          >
            {qualify.isPending ? 'Queuing…' : 'Qualify for this posture — no model spend'}
          </Button>
        )
      }
    >
      <QueryBoundary query={posture} loading="Reading the posture…">
        {(p) => <Body p={p} />}
      </QueryBoundary>
      {qualify.isError && (
        <div className="mt-3">
          <ErrorState compact error={qualify.error} />
        </div>
      )}
    </Card>
  )
}
