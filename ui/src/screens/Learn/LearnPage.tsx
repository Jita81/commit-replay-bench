/**
 * Learn — the learning half of the loop: refusals → guard corpus, weak oracles →
 * strengthening backlog, apparatus change → re-measurement plan, and the three decisions a
 * named operator makes here instead of on the host (/learn).
 *
 * Navigation
 * ----------
 * What it is:   The screen at /learn: three derivations from one repo's ledger, each a card
 *               with tiles, a table and — for an operator — the one action that report hands
 *               off to.
 * What it does: Renders `GET /learn/refusals` (protocol rows grouped by guard, reason and
 *               command shape, every verdict "unsure", with the decisions a person has
 *               already made), `/learn/strengthen` (cells withheld from deliver for a weak
 *               oracle, as frozen-backlog-shaped items) and `/learn/remeasure` (cells whose
 *               rows predate the current apparatus, with the rows and spend still needed).
 *               An operator decides from the report that computed the thing: accept a
 *               refusal class into the guard corpus, register a strengthening item onto the
 *               backlog, queue a cell's re-measurement runs. The product still decides
 *               nothing — every one of the three is a person's act, recorded with their
 *               name, and each reports back what was written.
 * How:          Three local read hooks and three mutations (the shapes mirror
 *               `crb.core.learn` `to_dict()`s and the route's response models) → one section
 *               component each with tiles + `DataTable` + its action; the note the server
 *               attaches is shown verbatim under each table. The two decisions that need
 *               more than a click open a `Dialog` (a verdict needs a reason; queueing runs
 *               spends money, so it is confirmed against the plan's own estimate); the
 *               outcome is a green `NotificationBanner` with a `role="status"` line naming
 *               what was written, so a screen reader is told as it lands.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   docs/LEARNING-LOOP.md (what each report means and which decisions stay a
 *               person's), src/crb/core/learn.py (the three derivations),
 *               src/crb/server/routes/learn.py (the three reads and the three writes),
 *               ui/src/components/StatTile.tsx and ui/src/components/DataTable.tsx,
 *               ui/src/components/Dialog.tsx and ui/src/components/govuk.tsx
 *               (`NotificationBanner`, `WarningButton` — the money action), ui/src/lib/auth.tsx
 *               (`can('operator')` — the actions are role-gated in the UI as at the API),
 *               ui/src/screens/Oracle/OraclePage.tsx (where the strengthen report sends you)
 * Tested by:    ui/src/screens/Learn/LearnPage.test.tsx (plain eyebrows, the intro sentences,
 *               the terms, each action's success state, the viewer who is offered none);
 *               the derivations are pinned in tests/test_learn.py and the routes in
 *               tests/test_server_routes_learn.py
 * Touch when:   a report gains a field (src/crb/core/learn.py — mirror the interface here)
 *               or a fourth play is added to docs/LEARNING-LOOP.md; never for a new repository.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, ApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { DataTable, type Column } from '../../components/DataTable'
import { Dialog } from '../../components/Dialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { NotificationBanner, WarningButton } from '../../components/govuk'
import { Term } from '../../components/Help'
import { PageHeader } from '../../components/PageHeader'
import { Pill } from '../../components/Pill'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { Hint } from '../../components/Hint'
import { StatTile } from '../../components/StatTile'
import { useAuth } from '../../lib/auth'
import { fmtInt, fmtPct, fmtUsd } from '../../lib/format'

// ---------------------------------------------------------------------------
// Shapes (mirror crb.core.learn *.to_dict(); see docs/LEARNING-LOOP.md)
// ---------------------------------------------------------------------------

/** One refusal class: (guard prefix, reason, command shape) with its cost and the candidate corpus lines; `verdict` is always "unsure" here — a human writes honest / refuse. */
export interface RefusalGroup {
  group_id: string
  prefix: string
  reason: string
  shape: string
  n: number
  cost_usd: number
  minutes: number
  repos: string[]
  tasks: string[]
  examples: string[]
  truncated: boolean
  candidate_honest: string
  candidate_refused: string
  verdict: string
}

/** `GET /learn/refusals` — mirrors `crb.core.learn.RefusalReport.to_dict()`. */
export interface RefusalReport {
  repo: string
  rows_total: number
  rows_protocol: number
  protocol_share: number
  /** The same share with its n and Wilson 95% interval — the form a rate is rendered in. */
  share: RefusalShare
  /** The share per apparatus version — never blended across versions on screen. */
  by_apparatus: Array<RefusalShare & { apparatus_version: string }>
  cost_usd: number
  minutes: number
  unparsed: number
  apparatus_versions: string[]
  groups: RefusalGroup[]
  /** What a named person HAS decided, folded from the `learn.refusal.accepted` events. */
  decisions: RefusalDecisionRecord[]
  note: string
}

/** One decision already on the record: the verdict, who made it and what it wrote. */
export interface RefusalDecisionRecord {
  group_id: string
  verdict: string
  /** The name written into the corpus comment (the account id is `decided_by_id`). */
  decided_by: string
  decided_by_id: string
  decided_at: string
  note: string
  lines: string[]
  already_present: boolean
}

/** `POST /learn/refusals/accept` — what the decision wrote, in the words the screen repeats. */
export interface RefusalAccepted {
  repo: string
  group_id: string
  verdict: string
  decided_by: string
  honest_added: string[]
  refused_added: string[]
  skipped: string[]
  already_present: boolean
  corpus_dir: string
  honest_path: string
  refused_path: string
}

/** `POST /learn/strengthen/register` — how each item landed on the backlog. */
export interface StrengthenRegistered {
  repo: string
  registered: Array<{ item_id: string; supersedes: string; how: 'frozen' | 'evolved' }>
  backlog_hash: string
  evolutions_hash: string
}

/** `POST /learn/remeasure/queue` — the runs queued and what the plan said they would cost. */
export interface RemeasureQueued {
  repo: string
  cell: string
  mode: string
  run_ids: string[]
  n_needed: number
  est_cost_usd: number
  cost_known: boolean
}

export interface RefusalShare {
  rows_total: number
  rows_protocol: number
  share: number
  ci_low: number
  ci_high: number
}

/** One strengthening proposal in the frozen-backlog shape (`test.add`, structural slots only). */
export interface StrengthenItem {
  id: string
  title: string
  description: string
  capability_class: string
  labels: Record<string, string>
}

/** `GET /learn/strengthen` — cells withheld from deliver for a weak oracle, and the items that would strengthen them. */
export interface StrengthenReport {
  repo: string
  threshold: number
  cells_flagged: string[]
  cells_without_scores: string[]
  items: StrengthenItem[]
  note: string
}

/** One cell with rows older than the current apparatus: how many are stale, how many current, how many still needed for n ≥ min_n, and the estimated spend. */
export interface RemeasureCell {
  label: string
  /** The mode this cell is planned for: the map never pools sighted and blind, so nor does the plan. */
  mode: string
  stale_versions: string[]
  n_stale: number
  n_current: number
  n_needed: number
  est_cost_usd: number
  est_minutes: number
  cost_known: boolean
  repos: string[]
  requests: Array<Record<string, unknown>>
}

/** `GET /learn/remeasure` — evidence expires with the apparatus (EVIDENCE-AND-CLAIMS §4). */
export interface RemeasurePlan {
  repo: string
  current_apparatus: string
  min_n: number
  rows_total: number
  rows_stale: number
  cells: RemeasureCell[]
  up_to_date: string[]
  summary: { cells_stale: number; n_needed_total: number; est_cost_usd_total: number; est_minutes_total: number; cost_known_cells: number }
  note: string
}

const enc = encodeURIComponent

/** `GET /learn/refusals?repo=`. */
function useLearnRefusals(repo: string): UseQueryResult<RefusalReport, ApiError> {
  return useQuery({
    queryKey: ['learn', repo, 'refusals'] as const,
    queryFn: () => api<RefusalReport>(`/learn/refusals?repo=${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /learn/strengthen?repo=`. */
function useLearnStrengthen(repo: string): UseQueryResult<StrengthenReport, ApiError> {
  return useQuery({
    queryKey: ['learn', repo, 'strengthen'] as const,
    queryFn: () => api<StrengthenReport>(`/learn/strengthen?repo=${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/** `GET /learn/remeasure?repo=`. */
function useLearnRemeasure(repo: string): UseQueryResult<RemeasurePlan, ApiError> {
  return useQuery({
    queryKey: ['learn', repo, 'remeasure'] as const,
    queryFn: () => api<RemeasurePlan>(`/learn/remeasure?repo=${enc(repo)}`),
    enabled: repo.length > 0,
    retry: false,
  })
}

/**
 * The decision an operator posts for one refusal class. There is no `decided_by`: the
 * signed-in operator is the decider, and the server takes their identity from the session,
 * so a decision can never be filed under somebody else's name.
 */
export interface RefusalDecisionInput {
  group_id: string
  verdict: 'honest' | 'refuse'
  note: string
  /** The full command, when every recorded example was cut by the recorder's cap. */
  command?: string
  /** The refused-corpus label, when the class's own guard family is not one it takes. */
  prefix?: string
}

/** `POST /learn/refusals/accept?repo=` — invalidates the report so the decision is read back. */
function useAcceptRefusal(repo: string): UseMutationResult<RefusalAccepted, ApiError, RefusalDecisionInput> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RefusalDecisionInput) =>
      api<RefusalAccepted>(`/learn/refusals/accept?repo=${enc(repo)}`, { method: 'POST', body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['learn', repo, 'refusals'] }),
  })
}

/** `POST /learn/strengthen/register?repo=` — the body names ids; the server re-derives them. */
function useRegisterStrengthening(repo: string): UseMutationResult<StrengthenRegistered, ApiError, string[]> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (itemIds: string[]) =>
      api<StrengthenRegistered>(`/learn/strengthen/register?repo=${enc(repo)}`, { method: 'POST', body: { item_ids: itemIds } }),
    // a prefix, so the factory's backlog, tasks and evidence queries all refetch: the item
    // is on that backlog now, and the Factory page must not show the record without it
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['factory', repo] }),
  })
}

/** `POST /learn/remeasure/queue?repo=` — one cell; the run bodies are the plan's, not ours. */
function useQueueRemeasurement(repo: string): UseMutationResult<RemeasureQueued, ApiError, { cell: string; mode: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { cell: string; mode: string }) =>
      api<RemeasureQueued>(`/learn/remeasure/queue?repo=${enc(repo)}`, { method: 'POST', body }),
    // the runs list is keyed ['runs', params]: the prefix reaches every filter of it
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['runs'] }),
  })
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

/** A decision's outcome: the green banner plus a polite live region naming what was written. */
function Outcome({ hint, children }: { hint: 'banner.learn.decision' | 'banner.learn.registered' | 'banner.learn.queued'; children: ReactNode }) {
  return (
    <NotificationBanner title="Done" tone="green" className="mb-0">
      <Hint as="p" id={hint} className="m-0 text-sm" role="status">
        {children}
      </Hint>
    </NotificationBanner>
  )
}

/** The loading line for a report; says what is being derived. */
function Pending({ what }: { what: string }) {
  return (
    <p role="status" className="text-sm text-on-surface-muted">
      Deriving {what}…
    </p>
  )
}

/** The refused corpus takes these guard families; anything else needs a `prefix` (a tamper is belt 1's). */
const REFUSED_PREFIXES = ['archaeology', 'network']

/**
 * The form behind a verdict (G-532). A corpus line is a policy change, so it is a form and
 * not a click: the class's own words are shown, the verdict is chosen, and a note says why —
 * that note is the provenance comment the next reader of the corpus file will find. A class
 * whose every example was cut by the recorder's cap asks for the full command, because a
 * truncated line would not be a usable corpus line; a class whose guard family the refused
 * corpus does not take asks which label to file it under.
 */
function DecideDialog({ repo, group, onClose }: { repo: string; group: RefusalGroup; onClose: () => void }) {
  const [verdict, setVerdict] = useState<'honest' | 'refuse'>('honest')
  const [note, setNote] = useState('')
  const [command, setCommand] = useState('')
  const [prefix, setPrefix] = useState(REFUSED_PREFIXES.includes(group.prefix) ? group.prefix : REFUSED_PREFIXES[0]!)
  const accept = useAcceptRefusal(repo)
  const needsCommand = group.truncated
  const needsPrefix = verdict === 'refuse' && !REFUSED_PREFIXES.includes(group.prefix)
  const done = accept.data
  return (
    <Dialog
      open
      width="lg"
      title={done ? 'Decision recorded' : 'Decide this refusal class'}
      onClose={onClose}
      footer={
        done ? (
          <Button hint="button.learn.close_decision" onClick={onClose}>
            Close
          </Button>
        ) : (
          <>
            <Button hint="button.learn.cancel_decision" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="filled"
              hint="button.learn.accept_refusal"
              // mistake-proofed at the input rather than refused at the server: a class whose
              // every example was cut short cannot make a usable corpus line without the whole
              // command, so the button does not offer to try
              disabled={accept.isPending || (needsCommand && !command.trim())}
              onClick={() =>
                accept.mutate({
                  group_id: group.group_id,
                  verdict,
                  note,
                  ...(needsCommand ? { command } : {}),
                  ...(needsPrefix ? { prefix } : {}),
                })
              }
            >
              {accept.isPending ? 'Recording…' : 'Record this decision'}
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="learn-decide-summary">
          <dt className="font-semibold">Guard</dt>
          <dd className="m-0">{group.prefix}</dd>
          <dt className="font-semibold">Reason</dt>
          <dd className="m-0">{group.reason}</dd>
          <dt className="font-semibold">Command shape</dt>
          <dd className="m-0 font-mono text-xs">{group.shape}</dd>
          <dt className="font-semibold">Rows</dt>
          <dd className="m-0">{fmtInt(group.n)}</dd>
        </dl>
        {done ? (
          <Outcome hint="banner.learn.decision">{decisionSentence(done)}</Outcome>
        ) : (
          <>
            <p className="m-0 text-sm text-on-surface-muted">
              Honest means the guard was wrong and this command must be allowed. Refused means the guard was right and it must keep refusing it. Either way the line is written into the guard corpus under your name, and the next reader of that file sees why.
            </p>
            <SelectField
              label="Your verdict"
              hint="field.learn.verdict"
              value={verdict}
              onChange={(e) => setVerdict(e.target.value as 'honest' | 'refuse')}
              description={verdict === 'honest' ? `Adds to the honest corpus: ${group.candidate_honest || 'the command below'}` : `Adds to the refused corpus: ${group.candidate_refused || 'the command below'}`}
            >
              <option value="honest">Honest — the guard should not have refused it</option>
              <option value="refuse">Refused — the guard was right</option>
            </SelectField>
            <TextArea
              label="Why (written into the corpus as a comment)"
              hint="field.learn.note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              description="One line a later reader can act on, such as “.git inside a quoted argument”."
            />
            {needsCommand && (
              <TextField
                label="The full command"
                hint="field.learn.command"
                required
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                description="Every recorded example of this class was cut short by the recorder’s cap. A cut command is not a usable corpus line, so type the whole one."
              />
            )}
            {needsPrefix && (
              <SelectField label="File the refusal under" hint="field.learn.prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} description="The refused corpus takes archaeology and network lines only.">
                {REFUSED_PREFIXES.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </SelectField>
            )}
            {accept.isError && <ErrorState error={accept.error} />}
          </>
        )}
      </div>
    </Dialog>
  )
}

/** What the decision wrote, as one sentence. Never “saved”: the words name the file it landed in. */
function decisionSentence(d: RefusalAccepted): string {
  const written = [...d.honest_added, ...d.refused_added]
  const where = d.verdict === 'honest' ? d.honest_path : d.refused_path
  if (!written.length) return `Recorded as ${d.verdict} by ${d.decided_by}. The line was already in the guard corpus, so nothing was written.`
  return `Recorded as ${d.verdict} by ${d.decided_by}. ${written.length === 1 ? 'One line was' : `${written.length} lines were`} written to ${where}. Run the guard corpus test to make it bind.`
}

/** Play 04: protocol rows → candidate guard-corpus lines (tiles + table); the share tile turns amber above 5 %. */
function RefusalsSection({ repo }: { repo: string }) {
  const q = useLearnRefusals(repo)
  const { can } = useAuth()
  const operator = can('operator')
  const [deciding, setDeciding] = useState('')
  const decided = useMemo(
    () => new Map((q.data?.decisions ?? []).map((d) => [d.group_id, d] as const)),
    [q.data],
  )
  const columns = useMemo<Column<RefusalGroup>[]>(
    () => [
      { key: 'n', header: 'n', hint: 'col.learn_refusals.n', numeric: true, sortValue: (g) => g.n, cell: (g) => fmtInt(g.n) },
      {
        key: 'prefix',
        header: 'Guard',
        hint: 'col.learn_refusals.guard',
        sortValue: (g) => g.prefix,
        cell: (g) => (
          <Pill tone={g.prefix === 'network' ? 'blue' : g.prefix === 'archaeology' ? 'violet' : 'muted'} size="xs" label={`Guard family: ${g.prefix}`} hint="pill.learn.guard" tabStop={false}>
            {g.prefix}
          </Pill>
        ),
      },
      { key: 'reason', header: 'Reason', hint: 'col.learn_refusals.reason_shape', cell: (g) => <span className="text-xs">{g.reason}</span> },
      { key: 'shape', header: 'Command shape', hint: 'col.learn_refusals.reason_shape', mono: true, cell: (g) => <span className="text-xs">{g.shape}{g.truncated ? ' …' : ''}</span> },
      { key: 'cost', header: '$ lost', hint: 'col.learn_refusals.cost', numeric: true, sortValue: (g) => g.cost_usd, cell: (g) => fmtUsd(g.cost_usd), hideBelowMd: true },
      {
        key: 'verdict',
        header: 'Verdict',
        hint: 'col.learn_refusals.verdict',
        sortValue: (g) => decided.get(g.group_id)?.verdict ?? g.verdict,
        cell: (g) => {
          const d = decided.get(g.group_id)
          if (!d)
            return (
              <Pill tone="amber" glyph="?" size="xs" label="The product never decides: a person writes honest or refused, and the decision is recorded with their name" hint="pill.learn.verdict" tabStop={false}>
                {g.verdict}
              </Pill>
            )
          return (
            <span className="inline-flex items-center gap-1.5">
              <Pill tone={d.verdict === 'honest' ? 'green' : 'blue'} size="xs" label={`Decided by ${d.decided_by}`} hint="pill.learn.decided" tabStop={false}>
                {d.verdict}
              </Pill>
              <span className="text-xs text-on-surface-muted">by {d.decided_by}</span>
            </span>
          )
        },
      },
      ...(operator
        ? [
            {
              key: 'decide',
              header: 'Decide',
              hint: 'col.learn_refusals.decide' as const,
              cell: (g: RefusalGroup) =>
                decided.has(g.group_id) ? (
                  <span className="text-xs text-on-surface-muted">recorded</span>
                ) : (
                  <Button size="sm" hint="button.learn.decide_refusal" onClick={() => setDeciding(g.group_id)}>
                    Decide
                  </Button>
                ),
            },
          ]
        : []),
    ],
    [decided, operator],
  )
  if (q.isPending) return <Pending what="the refusal triage" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const r = q.data
  const byApp = r.by_apparatus ?? []
  // One apparatus → the rate is that apparatus's, with its interval. Several → the tile
  // shows each version's own rate; the blended number is never the headline
  // (CodeRabbit on PR #6: a rate is never blended across apparatus versions).
  const single = byApp.length === 1 ? byApp[0]! : null
  const headline = single ?? r.share
  const apparatus = single ? `apparatus ${single.apparatus_version} · failure_kind = protocol · Wilson 95%` : byApp.length > 1 ? `${byApp.length} apparatus versions — see each below · failure_kind = protocol` : 'no rows'
  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-on-surface-muted">
        Rows the builder’s guards refused, grouped into classes with the spend they cost, per <Term id="apparatus">apparatus</Term> version. A person judges each class honest or refused and writes the line into the guard corpus, the list of refusals the guards then recognise; until then every verdict here is unsure. {operator ? 'Decide records your verdict, with your name, against the class you are reading.' : 'An operator records the verdict.'}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label={byApp.length > 1 ? 'Instrument-caused rows (per apparatus)' : 'Instrument-caused rows'}
          value={byApp.length > 1 ? byApp.map((a) => `${a.apparatus_version}: ${fmtPct(a.share)}`).join(' · ') : headline && headline.rows_total ? fmtPct(headline.share) : '—'}
          n={headline?.rows_total ?? r.rows_total}
          ci={byApp.length === 1 && headline.rows_total ? { low: headline.ci_low, high: headline.ci_high } : null}
          apparatus={byApp.length > 1 ? `${byApp.map((a) => `${a.apparatus_version}: ${a.rows_protocol}/${a.rows_total} [${fmtPct(a.ci_low, 0)}–${fmtPct(a.ci_high, 0)}]`).join(' · ')} · Wilson 95%` : apparatus}
          tone={byApp.some((a) => a.share > 0.05) ? 'amber' : 'green'}
          footer="review §7.5: read every one until this is < 5%"
          hint="stat.learn.refusal_share"
        />
        <StatTile label="Refusal classes" hint="stat.learn.refusal_classes" value={r.groups.length ? fmtInt(r.groups.length) : '—'} n={r.rows_protocol} apparatus="grouped by (guard, reason, command shape)" />
        <StatTile label="Spent on refusals" hint="stat.learn.refusal_cost" value={r.rows_protocol ? fmtUsd(r.cost_usd) : '—'} n={r.rows_protocol} apparatus={`${fmtInt(Math.round(r.minutes))} builder-minutes`} />
      </div>
      <DataTable
        rows={r.groups}
        columns={columns}
        rowKey={(g) => g.group_id}
        caption="Refusal classes — candidate guard-corpus lines, every verdict unsure"
        dense
        initialSort={{ key: 'n', dir: 'desc' }}
        empty={<EmptyState compact title="No protocol rows" reason="Nothing was refused by a guard in this repo's ledger." />}
      />
      <p className="text-xs text-on-surface-muted">{r.note}</p>
      {deciding && r.groups.some((g) => g.group_id === deciding) && (
        <DecideDialog repo={repo} group={r.groups.find((g) => g.group_id === deciding)!} onClose={() => setDeciding('')} />
      )}
    </div>
  )
}

/** What the registration did, as one sentence naming the item, the backlog and what it replaced. */
function registeredSentence(repo: string, d: StrengthenRegistered): string {
  const row = d.registered[0]
  if (!row) return `Nothing was registered on ${repo}’s backlog.`
  if (row.how === 'frozen') return `${row.item_id} is now the first item of ${repo}’s frozen backlog. A factory run builds it when you queue one.`
  if (row.supersedes) return `${row.item_id} was registered on ${repo}’s backlog as an evolution, superseding ${row.supersedes}. The record it replaces is kept.`
  return `${row.item_id} was registered on ${repo}’s backlog as an evolution. A factory run builds it when you queue one.`
}

/** Play 03: oracle-held cells → test work; links to the Oracle page for cells without per-task scores. */
function StrengthenSection({ repo }: { repo: string }) {
  const q = useLearnStrengthen(repo)
  const { can } = useAuth()
  const operator = can('operator')
  const register = useRegisterStrengthening(repo)
  const [pending, setPending] = useState('')
  const columns = useMemo<Column<StrengthenItem>[]>(
    () => [
      {
        key: 'id',
        header: 'Item',
        hint: 'col.learn_strengthen.item',
        mono: true,
        sortValue: (i) => i.id,
        // The description is a second line under the id, as text. It used to be a native
        // `title=`, which opens on hover alone: no keyboard and no touch reader could ever
        // read it (G-287). Nothing here is hover-only.
        cell: (i) => (
          <span className="block text-xs">
            {i.id}
            {i.description ? <span className="mt-0.5 block font-sans font-normal text-on-surface-muted">{i.description}</span> : null}
          </span>
        ),
      },
      { key: 'title', header: 'Title', hint: 'col.learn_strengthen.item', cell: (i) => <span className="text-xs">{i.title}</span> },
      { key: 'cell', header: 'Cell', hint: 'col.learn_strengthen.cell', mono: true, sortValue: (i) => i.labels.cell, cell: (i) => i.labels.cell },
      {
        key: 'reason',
        header: 'Held because',
        hint: 'col.learn_strengthen.reason',
        sortValue: (i) => i.labels.reason_code,
        cell: (i) => (
          <Pill tone="amber" size="xs" hint="pill.learn.held_reason" tabStop={false}>
            {i.labels.reason_code}
          </Pill>
        ),
      },
      { key: 'strength', header: 'Strength', hint: 'col.learn_strengthen.strength', numeric: true, sortValue: (i) => i.labels.oracle_strength, cell: (i) => `${i.labels.oracle_strength ?? '—'} / ${i.labels.threshold ?? '—'}` },
      { key: 'escaped', header: 'Escaped', hint: 'col.learn_strengthen.escaped', numeric: true, sortValue: (i) => Number(i.labels.escaped ?? -1), cell: (i) => i.labels.escaped ?? '—', hideBelowMd: true },
      ...(operator
        ? [
            {
              key: 'register',
              header: 'Register',
              hint: 'col.learn_strengthen.register' as const,
              cell: (i: StrengthenItem) => (
                <Button
                  size="sm"
                  hint="button.learn.register_item"
                  disabled={register.isPending}
                  onClick={() => {
                    setPending(i.id)
                    register.mutate([i.id])
                  }}
                >
                  {register.isPending && pending === i.id ? 'Registering…' : 'Register'}
                </Button>
              ),
            },
          ]
        : []),
    ],
    [operator, pending, register],
  )
  if (q.isPending) return <Pending what="the strengthening backlog" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const s = q.data
  return (
    <div className="space-y-4">
      {register.data && (
        <Outcome hint="banner.learn.registered">
          {registeredSentence(repo, register.data)}{' '}
          <Hint as={Link} id="link.learn.factory" to={`/factory?repo=${enc(repo)}`}>
            Factory
          </Hint>
        </Outcome>
      )}
      {register.isError && <ErrorState error={register.error} />}
      <p className="m-0 text-sm text-on-surface-muted">
        <Term id="cell">Cells</Term> withheld from deliver because their <Term id="oracle_strength">oracle strength</Term> is under the bar or their <Term id="negative_controls">negative controls</Term> escaped or were thin, each as a test-writing item in the backlog’s own shape. More attempts will not move these cells; stronger tests will. {operator ? 'Register puts an item on this repository’s backlog; registering one twice supersedes it rather than overwriting it.' : 'An operator registers an item on the backlog.'}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Oracle-held cells" hint="stat.learn.oracle_held" value={s.cells_flagged.length ? fmtInt(s.cells_flagged.length) : '—'} n={s.cells_flagged.length} apparatus={`routing.v1 · oracle threshold ${s.threshold.toFixed(2)}`} tone={s.cells_flagged.length ? 'amber' : 'green'} />
        <StatTile label="Strengthening items" hint="stat.learn.items" value={s.items.length ? fmtInt(s.items.length) : '—'} n={s.items.length} apparatus="test.add · structural slots only · DoR: build" />
        <StatTile
          label="Cells without per-task scores"
          hint="stat.learn.no_scores"
          value={s.cells_without_scores.length ? fmtInt(s.cells_without_scores.length) : '—'}
          n={s.cells_without_scores.length}
          apparatus="run an oracle run to list the escaped mutants"
          footer={
            <Hint as={Link} id="link.learn.oracle" to={`/oracle?repo=${enc(repo)}`}>
              Oracle
            </Hint>
          }
        />
      </div>
      <DataTable
        rows={s.items}
        columns={columns}
        rowKey={(i) => i.id}
        caption="Strengthening backlog — proposals in the frozen-backlog shape"
        dense
        empty={<EmptyState compact title="No oracle-held cells" reason="No cell is withheld from deliver for a weak oracle, a controls escape or thin controls." />}
      />
      <p className="text-xs text-on-surface-muted">{s.note}</p>
    </div>
  )
}

/** What was queued, as one sentence. The estimate is never shown as zero when it is unknown. */
function queuedSentence(d: RemeasureQueued): string {
  const runs = d.run_ids.length === 1 ? '1 run' : `${d.run_ids.length} runs`
  const cost = d.cost_known ? `The plan estimated ${fmtUsd(d.est_cost_usd)}.` : 'The cost is not known: no row of this cell recorded one.'
  return `Queued ${runs} for ${d.cell} (${d.mode}), for the ${fmtInt(d.n_needed)} row(s) the rule still needs. ${cost}`
}

/**
 * The confirmation before money is spent (G-532). Queueing is the one decision on this page
 * with a bill, so it repeats the plan's own numbers — the cell, the runs, the rows still
 * needed and the estimate, marked unknown where the cell recorded no cost — and the action is
 * a warning button. Nothing is sent until it is pressed.
 */
function QueueDialog({ repo, cell, onClose }: { repo: string; cell: RemeasureCell; onClose: () => void }) {
  const queue = useQueueRemeasurement(repo)
  const done = queue.data
  return (
    <Dialog
      open
      width="lg"
      title={done ? 'Runs queued' : 'Queue these re-measurement runs'}
      onClose={onClose}
      footer={
        done ? (
          <Button hint="button.learn.close_queue" onClick={onClose}>
            Close
          </Button>
        ) : (
          <>
            <Button hint="button.learn.cancel_queue" onClick={onClose}>
              Cancel
            </Button>
            <WarningButton hint="button.learn.confirm_queue" disabled={queue.isPending} onClick={() => queue.mutate({ cell: cell.label, mode: cell.mode })}>
              {queue.isPending ? 'Queueing…' : 'Queue the runs'}
            </WarningButton>
          </>
        )
      }
    >
      <div className="space-y-4">
        {done ? (
          <Outcome hint="banner.learn.queued">
            {queuedSentence(done)}{' '}
            <Hint as={Link} id="link.learn.queued_runs" to={`/runs?repo=${enc(repo)}`}>
              Runs
            </Hint>
          </Outcome>
        ) : (
          <>
            <p className="m-0 text-sm text-on-surface-muted">
              This spends the deployment’s budget. The bodies are the plan’s own, on the same commits the stale rows were graded on; nothing is sent until you press the button below.
            </p>
            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="learn-queue-summary">
              <dt className="font-semibold">Cell</dt>
              <dd className="m-0 font-mono text-xs">{cell.label}</dd>
              <dt className="font-semibold">Mode</dt>
              <dd className="m-0">{cell.mode}</dd>
              <dt className="font-semibold">Runs to queue</dt>
              <dd className="m-0">{fmtInt(cell.requests.length)}</dd>
              <dt className="font-semibold">Rows still needed</dt>
              <dd className="m-0">{fmtInt(cell.n_needed)}</dd>
              <dt className="font-semibold">Estimated spend</dt>
              <dd className="m-0">{cell.cost_known ? fmtUsd(cell.est_cost_usd) : 'not known — no row of this cell recorded a cost'}</dd>
            </dl>
            {queue.isError && <ErrorState error={queue.error} />}
          </>
        )}
      </div>
    </Dialog>
  )
}

/** Stale evidence → the runs to queue; the spend tile is a dash when no cell has a known cost. */
function RemeasureSection({ repo }: { repo: string }) {
  const q = useLearnRemeasure(repo)
  const { can } = useAuth()
  const operator = can('operator')
  const [queueing, setQueueing] = useState('')
  const columns = useMemo<Column<RemeasureCell>[]>(
    () => [
      { key: 'cell', header: 'Cell', hint: 'col.learn_remeasure.cell', mono: true, sortValue: (c) => c.label, cell: (c) => <span className="text-xs">{c.label}</span> },
      { key: 'stale', header: 'Stale', hint: 'col.learn_remeasure.counts', numeric: true, sortValue: (c) => c.n_stale, cell: (c) => `${fmtInt(c.n_stale)} (${c.stale_versions.join(', ')})` },
      { key: 'current', header: 'Current', hint: 'col.learn_remeasure.counts', numeric: true, sortValue: (c) => c.n_current, cell: (c) => fmtInt(c.n_current) },
      { key: 'needed', header: 'Needed', hint: 'col.learn_remeasure.counts', numeric: true, sortValue: (c) => c.n_needed, cell: (c) => fmtInt(c.n_needed) },
      { key: 'cost', header: 'Est. $', hint: 'col.learn_remeasure.cost', numeric: true, sortValue: (c) => (c.cost_known ? c.est_cost_usd : -1), cell: (c) => (c.cost_known ? fmtUsd(c.est_cost_usd) : '?') },
      { key: 'requests', header: 'Runs to queue', hint: 'col.learn_remeasure.runs', numeric: true, sortValue: (c) => c.requests.length, cell: (c) => fmtInt(c.requests.length), hideBelowMd: true },
      ...(operator
        ? [
            {
              key: 'queue',
              header: 'Queue',
              hint: 'col.learn_remeasure.queue' as const,
              cell: (c: RemeasureCell) => (
                <Button size="sm" hint="button.learn.queue_remeasure" onClick={() => setQueueing(`${c.label}|${c.mode}`)}>
                  Queue runs
                </Button>
              ),
            },
          ]
        : []),
    ],
    [operator],
  )
  if (q.isPending) return <Pending what="the re-measurement plan" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const p = q.data
  return (
    <div className="space-y-4">
      <p className="m-0 text-sm text-on-surface-muted">
        Cells whose rows predate the current <Term id="apparatus">apparatus</Term>. <Term id="stale">Stale</Term> evidence is kept as history and licenses nothing; the plan lists the runs to queue and what they would cost. {operator ? 'Queue runs sends one cell’s runs, after showing you the estimate it will spend.' : 'An operator queues the runs.'}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Stale rows" hint="stat.learn.stale_rows" value={p.rows_total ? fmtInt(p.rows_stale) : '—'} n={p.rows_total} apparatus={`older than apparatus ${p.current_apparatus}`} tone={p.rows_stale ? 'amber' : 'green'} />
        <StatTile label="Rows still needed" hint="stat.learn.needed" value={p.cells.length ? fmtInt(p.summary.n_needed_total) : '—'} n={p.cells.length} apparatus={`rule n ≥ ${p.min_n} per cell · ${fmtInt(p.summary.cells_stale)} cell(s)`} />
        <StatTile
          label="Estimated spend"
          hint="stat.learn.remeasure_cost"
          value={p.summary.cost_known_cells ? fmtUsd(p.summary.est_cost_usd_total) : '—'}
          n={p.summary.cost_known_cells}
          apparatus="each cell's own mean row cost × n needed"
          footer={
            <Hint as={Link} id="link.learn.runs" to={`/runs?repo=${enc(repo)}`}>
              Queue runs
            </Hint>
          }
        />
      </div>
      <DataTable
        rows={p.cells}
        columns={columns}
        rowKey={(c) => c.label}
        caption="Cells whose evidence predates the current apparatus"
        dense
        initialSort={{ key: 'needed', dir: 'desc' }}
        empty={<EmptyState compact title="Nothing stale" reason="Every row of this repo carries the current apparatus version." />}
      />
      <p className="text-xs text-on-surface-muted">{p.note}</p>
      {queueing && p.cells.some((c) => `${c.label}|${c.mode}` === queueing) && (
        <QueueDialog repo={repo} cell={p.cells.find((c) => `${c.label}|${c.mode}` === queueing)!} onClose={() => setQueueing('')} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/**
 * The learning half of the loop: three derivations from the ledger (docs/LEARNING-LOOP.md),
 * each stopping where a human decides — accepting a corpus line, registering a strengthening
 * item, queueing a re-measurement. Those three decisions are still a person's, and an
 * operator makes them here, beside the report that computed them, rather than as a command on
 * the host. A viewer is offered none of them.
 */
export function LearnPage() {
  const [repo, setRepo] = useRepoParam()
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Instrument · Learn"
        title="Learn"
        purpose="What the ledger teaches: refusals that should become guard tests, weak oracles that should become test work, stale evidence that should be re-measured. The product decides nothing; an operator decides here, and each decision is recorded with their name."
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      {!repo ? (
        <EmptyState title="Pick a repository" reason="The three reports are derived from one repository's ledger rows." />
      ) : (
        <>
          <Card eyebrow="Refusals" title="Refusals → guard corpus">
            <RefusalsSection repo={repo} />
          </Card>
          <Card eyebrow="Weak oracles" title="Weak oracles → strengthening backlog">
            <StrengthenSection repo={repo} />
          </Card>
          <Card eyebrow="Stale evidence" title="Apparatus change → re-measurement plan">
            <RemeasureSection repo={repo} />
          </Card>
        </>
      )}
    </div>
  )
}
