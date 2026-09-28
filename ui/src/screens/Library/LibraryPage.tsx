/**
 * The context library — one repository's nomenclature and one page per work type.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /library/:repo (`?type=` picks the work type): the page for one
 *               kind of change — what it is and example commits, what a ticket must carry, the
 *               signed context with sponsor, signer, date, provenance and effect, what is proven
 *               per size (or "no proven standard" and the next measurement), which switched-on
 *               checks evidence which ISO/IEC 25010 characteristic — then the nomenclature index
 *               of every entry with its status and the act due on it, the miners' card and the
 *               proposal form.
 * What it does: Lets an operator run the miners over the repository's files at a commit (each
 *               proposal arrives unsigned, with no sponsor), propose an entry (and so sponsor
 *               it), an operator adopt a
 *               miner's or a model's proposal, and a DIFFERENT approver sign it; revocation and
 *               retirement are appended with a reason. The sponsor's own Sign button is disabled
 *               and says why (the API refuses it too, 409 `same_person`). Every refusal is shown
 *               in the API's words BESIDE the form or table that made it, focused, and marks
 *               the field it names (P-397); a revocation or retirement says what it did and
 *               clears its form, and an empty press asks at the fields. The page says, in the
 *               lede and on its tag, that nothing here reaches a builder's brief until an arm
 *               measures it.
 * How:          `useLibrary` + `useWorkTypePage` + `useLibraryAct` + `useLibraryMine`; tables
 *               through `DataTable` with a hint on every column; forms through `Field`; every
 *               element a reader meets is a hint trigger (`*.library.*`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 10),
 *               docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
 * Works with:   ui/src/screens/Library/useLibrary.ts (the reads and acts), ui/src/api/types.ts
 *               (`LibraryIndex`, `WorkTypePage`), ui/src/help/hints.ts (the copy),
 *               ui/src/help/help.ts (the About block), ui/src/screens/Decisions/decisions.ts
 *               (the library rows link here),
 *               ui/src/screens/Repos/RepoDetail.tsx (the door from a repository)
 * Tested by:    ui/src/screens/Library/LibraryPage.test.tsx, ui/src/help/hints-ratchet.test.tsx,
 *               ui/e2e/walkthrough/14-library.spec.ts
 * Touch when:   never for a new repository; a field of the page changes in docs/API.md#library
 *               first.
 */
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { isApiError } from '../../api/client'
import type { LibraryEntry, LibraryKind, LibraryMineRun, LibraryStandard, LibraryStatus, WorkTypePage } from '../../api/types'
import { Card } from '../../components/Card'
import { type Column, DataTable } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { BackLink, InsetText, Kicker, Lede, PageTitle, SecondaryButton, StartButton, Tag, type TagTone, WarningButton } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { type LibraryAct, useLibrary, useLibraryAct, useLibraryMine, useWorkTypePage } from './useLibrary'

const STATUS_TONE: Record<LibraryStatus, TagTone> = { proposed: 'blue', signed: 'green', stale: 'amber', retired: 'grey', revoked: 'red' }
const KIND_LABEL: Record<LibraryKind, string> = {
  component: 'Component',
  'work-type': 'Work type',
  decision: 'Decision',
  convention: 'Convention',
  pattern: 'Pattern',
  standard: 'Standard',
}

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

function day(iso: string): string {
  return iso ? iso.slice(0, 10) : '—'
}

function who(name: string, id: string): string {
  return name || (id ? `${id.slice(0, 8)}…` : '—')
}

/** The API's refusal in words: the message, which already names the rule. */
function refusal(err: unknown): string {
  if (!err) return ''
  if (isApiError(err)) return err.message
  return err instanceof Error ? err.message : String(err)
}

/**
 * A refused act, said beside the form or table that made it — never at the top of the page,
 * out of sight of the person who pressed — and focused when it appears, so a keyboard user
 * and a screen reader land on it (P-397).
 */
function Refused({ error, testId }: { error: unknown; testId: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (error) ref.current?.focus()
  }, [error])
  if (!error) return null
  return (
    <div ref={ref} role="alert" tabIndex={-1} className="my-3 border-l-4 border-status-red p-3" data-testid={testId}>
      {refusal(error)}
    </div>
  )
}

/** The refusal's words when they name ``field`` — shown at the field too (``aria-invalid``). */
function fieldRefusal(error: unknown, field: RegExp): string | undefined {
  const words = refusal(error)
  return words && field.test(words) ? words : undefined
}

const FORWARD_STATE: Record<string, string> = {
  look_pending: 'reading',
  deliver: 'delivered',
  insufficient: 'insufficient — the ceiling stands',
}

/** A ceiling's forward reading (ADR-0026 items 4 and 8): its state with its n, or that none
 *  is registered yet. */
function Forward({ std, size }: { std: LibraryStandard; size: string }) {
  const f = std.forward
  return (
    <Hint as="p" id="item.library.forward" className="m-0 mt-1 text-xs" data-testid={`forward-${size}`}>
      {f
        ? `Forward reading: ${FORWARD_STATE[f.state] ?? f.state} · n = ${f.counted} (${f.clean} passed the held-out tests)` +
          (f.state === 'look_pending' && f.next_look ? ` · ${f.needed} more to its look at ${f.next_look}` : '')
        : 'No forward reading is registered yet: an operator registers one before the first calibration build.'}
    </Hint>
  )
}

function WorkTypeSection({ page }: { page: WorkTypePage }) {
  const context: Column<WorkTypePage['context'][number]>[] = [
    { key: 'entry', header: 'Entry', hint: 'col.library.entry', cell: (c) => <span className="font-mono text-xs">{c.entry_id}</span> },
    { key: 'statement', header: 'What it says', hint: 'col.library.statement', cell: (c) => c.statement },
    { key: 'sponsor', header: 'Sponsor', hint: 'col.library.sponsor', cell: (c) => who(c.sponsor_name, c.sponsor) },
    { key: 'approver', header: 'Signed by', hint: 'col.library.approver', cell: (c) => who(c.approver_name, c.approver) },
    { key: 'date', header: 'Signed', hint: 'col.library.signed_at', cell: (c) => day(c.signed_at), hideBelowMd: true },
    { key: 'prov', header: 'Provenance', hint: 'col.library.provenance', cell: (c) => c.provenance_label, hideBelowMd: true },
    { key: 'effect', header: 'Measured effect', hint: 'col.library.effect', cell: (c) => c.effect },
  ]
  const sizes: Column<WorkTypePage['sizes'][number]>[] = [
    { key: 'size', header: 'Size', hint: 'col.library.size', cell: (s) => s.size },
    {
      key: 'standard',
      header: 'Proven standard',
      hint: 'col.library.standard',
      cell: (s) => (s.standard ? `${s.standard.arm}${s.standard.ceiling ? ' (ceiling only — forward-unvalidated)' : ''}` : <span>No proven standard</span>),
    },
    { key: 'commits', header: 'Distinct commits', hint: 'col.library.commits', numeric: true, cell: (s) => (s.standard ? `${s.standard.clean} of ${s.standard.n}` : `${s.tasks} mined`) },
    { key: 'interval', header: 'Interval', hint: 'col.library.interval', cell: (s) => (s.standard ? `${pct(s.standard.ci_low)} to ${pct(s.standard.ci_high)}` : '—') },
    {
      key: 'next',
      header: 'Apparatus, or the next measurement',
      hint: 'col.library.next',
      cell: (s) =>
        s.standard?.ceiling ? (
          <div data-testid={`ceiling-${s.size}`}>
            <p className="m-0">{s.next}</p>
            <Forward std={s.standard} size={s.size} />
          </div>
        ) : s.standard ? (
          `apparatus ${s.standard.apparatus}`
        ) : (
          s.next
        ),
    },
  ]
  const quality: Column<WorkTypePage['quality']['rows'][number]>[] = [
    { key: 'char', header: 'ISO/IEC 25010 characteristic', hint: 'col.library.characteristic', cell: (q) => q.characteristic },
    {
      key: 'checks',
      header: 'Switched-on checks that evidence part of it',
      hint: 'col.library.checks',
      cell: (q) => (q.checks.filter((c) => c.on).map((c) => c.label).join('; ') || 'none on this repository'),
    },
    { key: 'ev', header: 'Evidenced here', hint: 'col.library.evidenced', cell: (q) => (q.evidenced ? 'Part of it' : 'Not evidenced') },
  ]
  return (
    <Card title={`Work type: ${page.title}`} id="work-type">
      <dl className="m-0 space-y-4">
        <Hint as="div" id="row.library.definition" className="block">
          <dt className="font-bold">What it is</dt>
          <dd className="m-0">
            {page.definition}{' '}
            <span className="text-on-surface-muted">({page.definition_source === 'global' ? 'the global vocabulary' : `signed entry ${page.definition_source}`}; global parent {page.parent_class})</span>
          </dd>
        </Hint>
        <Hint as="div" id="row.library.examples" className="block">
          <dt className="font-bold">Example commits</dt>
          <dd className="m-0">
            {page.examples.length === 0 ? (
              'No commit of this kind has been mined yet.'
            ) : (
              <ul className="m-0 list-disc pl-5">
                {page.examples.map((x) => (
                  <li key={x.sha}>
                    <Link to={`/tasks/${encodeURIComponent(page.repo)}/${encodeURIComponent(x.sha)}`} className="font-mono text-xs">
                      {x.sha.slice(0, 12)}
                    </Link>{' '}
                    {x.subject} {x.size ? `(${x.size})` : ''}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </Hint>
        <Hint as="div" id="row.library.ticket" className="block">
          <dt className="font-bold">What a ticket must carry</dt>
          <dd className="m-0">
            {page.ticket_slots.length === 0 ? (
              'Readiness asks a ticket of this kind for nothing yet.'
            ) : (
              <ul className="m-0 list-disc pl-5">
                {page.ticket_slots.map((s) => (
                  <li key={s.name}>
                    <span className="font-mono text-xs">{s.name}</span> — {s.question} <Tag tone={s.kind === 'structural' ? 'blue' : 'grey'} hint="tag.library.slot_kind">{s.kind}</Tag>
                  </li>
                ))}
              </ul>
            )}
            {page.signed_slots.length > 0 && <p className="mt-2">Signed test-standard slots: {page.signed_slots.join(', ')}.</p>}
          </dd>
        </Hint>
      </dl>
      <h3 className="mt-6 text-lg font-bold">The signed context its builder would get</h3>
      <InsetText>
        None of it reaches a builder yet. An entry reaches a brief only inside a context arm whose effect was measured, and that switch is off.{' '}
        <Tag tone="grey" hint="tag.library.briefs">
          Reaches no brief
        </Tag>
      </InsetText>
      <DataTable rows={page.context} columns={context} rowKey={(c) => c.entry_id} caption={`Signed context for ${page.title}`} empty="No signed entry is scoped to this work type yet." dense />
      <h3 className="mt-6 text-lg font-bold">What is proven, per size</h3>
      <DataTable rows={page.sizes} columns={sizes} rowKey={(s) => s.size} caption={`Proven standard per size for ${page.title}`} empty="No size." dense />
      <h3 className="mt-6 text-lg font-bold">Which checks evidence which quality</h3>
      <p className="text-sm">Switched on here: {page.quality.switched_on.join(', ') || 'none'}. Named, never claimed: a clean row is not a claim that code conforms to ISO/IEC 25010.</p>
      {page.quality.served ? (
        <DataTable rows={page.quality.rows} columns={quality} rowKey={(q) => q.characteristic} caption="ISO/IEC 25010 characteristics and the checks that evidence part of them" empty="No characteristic." dense />
      ) : (
        <p className="text-sm" data-testid="quality-not-served">
          The characteristic-to-check table is not on this build, so this page names no characteristic as evidenced.
        </p>
      )}
      {page.quality.standards.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-sm">
          {page.quality.standards.map((s) => (
            <li key={s.entry_id}>
              {s.entry_id} {s.characteristic ? `refines ${s.characteristic}` : ''}{' '}
              <Tag tone={s.evidence === 'check' ? 'green' : 'amber'} hint="tag.library.evidence">
                {s.evidence === 'check' ? `evidenced by ${s.check}` : 'advisory — counts as no evidence'}
              </Tag>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function ProposeForm({ repo, kinds, characteristics, statementMax }: { repo: string; kinds: LibraryKind[]; characteristics: string[]; statementMax: number }) {
  // its own act: a refusal of this form is said in this form (P-397)
  const onAct = useLibraryAct(repo)
  const [kind, setKind] = useState<LibraryKind>('convention')
  const [slug, setSlug] = useState('')
  const [title, setTitle] = useState('')
  const [statement, setStatement] = useState('')
  const [workTypes, setWorkTypes] = useState('')
  const [characteristic, setCharacteristic] = useState('')
  const [check, setCheck] = useState('')
  const [parent, setParent] = useState('')
  const [done, setDone] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (onAct.isPending) return
    setDone('')
    const scope = workTypes
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    onAct.mutate(
      {
        act: 'propose',
        body: {
          kind,
          slug: slug.trim(),
          title,
          statement,
          work_types: kind === 'work-type' ? [] : scope,
          characteristic: kind === 'standard' || kind === 'convention' ? characteristic : '',
          check: kind === 'standard' || kind === 'convention' ? check.trim() : '',
          parent_class: kind === 'work-type' ? parent.trim() : '',
        },
      },
      { onSuccess: (entry) => setDone(`Proposed ${entry.entry_id}. You are its sponsor; a different approver must sign it.`) },
    )
  }
  return (
    <Card title="Propose an entry" id="propose">
      <p>You become the entry’s sponsor. A different person must sign it before it counts as signed.</p>
      <form onSubmit={submit} className="space-y-4" aria-label={`Propose an entry for ${repo}`}>
        <Refused error={onAct.error} testId="library-propose-refused" />
        <SelectField label="Kind" value={kind} onChange={(e) => setKind(e.target.value as LibraryKind)} hint="field.library.kind">
          {kinds.map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </SelectField>
        <TextField label="Short name (slug)" value={slug} onChange={(e) => setSlug(e.target.value)} required hint="field.library.slug" description="Lower case, digits, dots, dashes; it becomes the id kind/slug." error={fieldRefusal(onAct.error, /\bslug\b/i)} />
        <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} required hint="field.library.title" error={fieldRefusal(onAct.error, /\btitle\b/i)} />
        <TextArea
          label="Statement"
          value={statement}
          onChange={(e) => setStatement(e.target.value)}
          required
          maxLength={statementMax}
          hint="field.library.statement"
          description={`${statement.length} of ${statementMax} characters. No code and no secrets.`}
          error={fieldRefusal(onAct.error, /\bstatement\b/i)}
        />
        {kind === 'work-type' ? (
          <TextField label="Global parent class" value={parent} onChange={(e) => setParent(e.target.value)} hint="field.library.parent" description="For example bug.fix or feature.add." />
        ) : (
          <TextField label="Work types it applies to" value={workTypes} onChange={(e) => setWorkTypes(e.target.value)} hint="field.library.work_types" description="Comma-separated, for example bug.fix." />
        )}
        {(kind === 'standard' || kind === 'convention') && (
          <>
            <SelectField label="ISO/IEC 25010 characteristic" value={characteristic} onChange={(e) => setCharacteristic(e.target.value)} hint="field.library.characteristic">
              <option value="">{kind === 'standard' ? 'Choose one' : 'None'}</option>
              {characteristics.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </SelectField>
            <TextField label="Check that evidences it" value={check} onChange={(e) => setCheck(e.target.value)} hint="field.library.check" description="The check's name as the repository runs it. Without one the entry is advisory." />
          </>
        )}
        <StartButton type="submit" pending={onAct.isPending} hint="button.library.propose">
          Propose as sponsor
        </StartButton>
      </form>
      <div role="status" aria-live="polite" className="mt-3" data-testid="library-proposed">
        {done}
      </div>
    </Card>
  )
}

/** What a miner run did, in one sentence: the commit, the proposals and what waits on a person. */
function mineSummary(run: LibraryMineRun): string {
  const c = run.counts
  const others = (['held', 'refused', 'failed'] as const).filter((k) => c[k] > 0).map((k) => `${c[k]} ${k}`)
  const tail = others.length ? `, ${others.join(', ')}` : ''
  const lead = `Read ${run.repo} at ${run.commit.slice(0, 12)}: ${c.proposed} proposed, ${c.unchanged} unchanged, ${c.noted} noted${tail}.`
  return c.proposed > 0 ? `${lead} Each proposal waits for a person to sponsor it and a different approver to sign it.` : `${lead} Nothing new at this commit.`
}

function MineCard({ repo }: { repo: string }) {
  const [commit, setCommit] = useState('')
  const mine = useLibraryMine(repo)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (mine.isPending) return
    mine.mutate({ commit })
  }
  return (
    <Card title="Propose from the repository’s files" id="mine">
      <p>
        The miners read what the repository already holds at one commit — its decision records, code owners and layout, lint and formatter settings, tests and change history — and propose entries with the file and commit they came from. No model is called, and nothing is signed.
      </p>
      <form onSubmit={submit} className="space-y-4" aria-label={`Propose entries from ${repo}’s files`}>
        <TextField label="Commit (optional)" value={commit} onChange={(e) => setCommit(e.target.value)} hint="field.library.commit" description="A sha, branch or tag of the clone. Empty reads its head." />
        <SecondaryButton type="submit" pending={mine.isPending} hint="button.library.mine">
          {mine.isPending ? 'Reading the files…' : 'Propose from the files'}
        </SecondaryButton>
      </form>
      <div role="status" aria-live="polite" className="mt-3" data-testid="library-mined">
        {mine.data ? mineSummary(mine.data) : ''}
      </div>
      <Refused error={mine.error} testId="library-mine-refused" />
    </Card>
  )
}

function IndexSection({ repo, entries, meId }: { repo: string; entries: LibraryEntry[]; meId: string }) {
  const { can } = useAuth()
  // the table's acts (sponsor, sign) and the withdraw form's acts are said each beside their
  // own controls (P-397), so each has its own act
  const onAct = useLibraryAct(repo)
  const withdraw = useLibraryAct(repo)
  const [reason, setReason] = useState('')
  const [target, setTarget] = useState('')
  const [asked, setAsked] = useState(false)
  const [withdrawn, setWithdrawn] = useState('')
  const act = (a: LibraryAct) => {
    if (!onAct.isPending) onAct.mutate(a)
  }
  const signable = (e: LibraryEntry) => (e.status === 'proposed' || e.status === 'stale') && Boolean(e.sponsor)
  const columns: Column<LibraryEntry>[] = [
    { key: 'id', header: 'Id', hint: 'col.library.entry', mono: true, cell: (e) => e.entry_id, sortValue: (e) => e.entry_id },
    { key: 'kind', header: 'Kind', hint: 'col.library.kind', cell: (e) => KIND_LABEL[e.entry.kind], hideBelowMd: true },
    { key: 'title', header: 'Title', hint: 'col.library.title', cell: (e) => e.entry.title },
    {
      key: 'status',
      header: 'Status',
      hint: 'col.library.status',
      cell: (e) => (
        <Tag tone={STATUS_TONE[e.status]} hint="tag.library.status" data-testid={`status-${e.entry_id}`}>
          {e.status}
        </Tag>
      ),
    },
    { key: 'sponsor', header: 'Sponsor', hint: 'col.library.sponsor', cell: (e) => (e.sponsor ? who(e.sponsor_name, e.sponsor) : `none yet — proposed by ${e.entry.proposed_by}`) },
    { key: 'approver', header: 'Signed by', hint: 'col.library.approver', cell: (e) => who(e.approver_name, e.approver), hideBelowMd: true },
    {
      key: 'act',
      header: 'Act',
      hint: 'col.library.act',
      cell: (e) => {
        if (!e.sponsor && e.status === 'proposed' && can('operator')) {
          return (
            <SecondaryButton hint="button.library.sponsor" pending={onAct.isPending} onClick={() => act({ act: 'sponsor', entryId: e.entry_id, version: e.version })}>
              Sponsor
            </SecondaryButton>
          )
        }
        if (signable(e) && can('approver')) {
          const own = e.sponsor === meId
          return (
            <span className="block">
              <SecondaryButton hint={own ? 'button.library.sign_own' : 'button.library.sign'} disabled={own} pending={onAct.isPending} onClick={() => act({ act: 'sign', entryId: e.entry_id, version: e.version })}>
                {e.status === 'stale' ? 'Sign again' : 'Sign'}
              </SecondaryButton>
              {own && <span className="mt-1 block text-xs">You sponsored this entry, so a second person must sign it.</span>}
            </span>
          )
        }
        return <span className="text-sm text-on-surface-muted">{e.status === 'signed' ? 'Signed' : e.status === 'proposed' ? 'Waiting for an approver' : '—'}</span>
      },
    },
  ]
  const withdrawable = entries.filter((e) => e.status !== 'retired' && e.status !== 'revoked')
  // the chosen entry only while it can still be withdrawn: a retired one leaves the list, and
  // a press then acts on nothing the person can see
  const chosen = withdrawable.some((e) => e.entry_id === target) ? target : ''
  const entryError = asked && !chosen ? 'Choose the entry to revoke or retire.' : undefined
  const reasonError = asked && !reason.trim() ? 'Give the reason; it is kept on the record.' : undefined
  const withdrawAct = (a: 'revoke' | 'retire') => {
    setAsked(true)
    setWithdrawn('')
    if (!chosen || !reason.trim() || withdraw.isPending) return
    const why = reason.trim()
    withdraw.mutate(
      { act: a, entryId: chosen, reason: why },
      {
        onSuccess: () => {
          setWithdrawn(`${a === 'retire' ? 'Retired' : 'Revoked'} ${chosen}: ${why}. It is on the record.`)
          setTarget('')
          setReason('')
          setAsked(false)
        },
      },
    )
  }
  return (
    <Card title="Nomenclature index" id="index">
      <div data-testid="library-index">
      <p>Every entry of every kind, in one vocabulary. The id is kind/slug everywhere the product names it.</p>
      <DataTable rows={entries} columns={columns} rowKey={(e) => e.entry_id} caption={`Library entries for ${repo}`} empty="No entry yet. Propose the first one below." dense />
      <Refused error={onAct.error} testId="library-refused" />
      {can('approver') && (withdrawable.length > 0 || withdrawn) && (
        <form className="mt-6 space-y-3" aria-label="Revoke or retire an entry" onSubmit={(e) => e.preventDefault()}>
          <h3 className="text-lg font-bold">Revoke or retire an entry</h3>
          <p className="text-sm">Both are appended to the record; neither edits it. Revoke when it was wrong; retire when it no longer holds.</p>
          <Refused error={withdraw.error} testId="library-withdraw-refused" />
          <SelectField label="Entry" value={chosen} onChange={(e) => setTarget(e.target.value)} hint="field.library.entry" error={entryError}>
            <option value="">Choose an entry</option>
            {withdrawable.map((e) => (
              <option key={e.entry_id} value={e.entry_id}>
                {e.entry_id}
              </option>
            ))}
          </SelectField>
          <TextField label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} hint="field.library.reason" error={reasonError} />
          <div className="flex flex-wrap gap-3">
            <WarningButton hint="button.library.revoke" pending={withdraw.isPending} onClick={() => withdrawAct('revoke')}>
              Revoke
            </WarningButton>
            <SecondaryButton hint="button.library.retire" pending={withdraw.isPending} onClick={() => withdrawAct('retire')}>
              Retire
            </SecondaryButton>
          </div>
          <p role="status" className="m-0 text-sm" data-testid="library-withdrawn">
            {withdrawn}
          </p>
        </form>
      )}
      </div>
    </Card>
  )
}

export function LibraryPage() {
  const { repo = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const { can, me } = useAuth()
  const lib = useLibrary(repo)
  const types = lib.data?.work_types ?? []
  const chosen = params.get('type') ?? types[0]?.slug ?? ''
  const pageable = types.find((t) => t.slug === chosen && (t.status === 'global' || t.status === 'signed'))
  const page = useWorkTypePage(repo, pageable ? chosen : '')
  const counts = useMemo(() => {
    const entries = lib.data?.entries ?? []
    return { all: entries.length, signed: entries.filter((e) => e.status === 'signed').length }
  }, [lib.data])

  return (
    <>
      <BackLink to={`/repos/${encodeURIComponent(repo)}`} hint="link.library.back">
        Back to {repo}
      </BackLink>
      <Kicker>Context library · {repo}</Kicker>
      <PageTitle>What people know about {repo}</PageTitle>
      <Lede>
        What a test cannot say — its parts, its kinds of change, its decisions, conventions, designs and quality rules — in one vocabulary. Each entry needs two people: a sponsor who puts it forward and a different approver who signs it. Nothing here reaches a builder until an arm has measured it.
      </Lede>
      <div className="mb-6" data-testid="library-count" data-ready={lib.data ? 'true' : 'false'}>
        <Pill tone={counts.signed > 0 ? 'green' : 'primary'} size="sm" label={`${counts.all} entries, ${counts.signed} signed`} hint="stat.library.count">
          {lib.data ? `${counts.all} entries · ${counts.signed} signed` : 'counting…'}
        </Pill>
      </div>
      {lib.isError && <ErrorState error={lib.error} onRetry={() => void lib.refetch()} />}
      {lib.data && (
        <>
          <Card title="Work types" id="work-types">
            {types.length === 0 ? (
              <EmptyState compact title="No work type yet" reason="A work type appears once a commit of that kind is mined, or a work-type entry is proposed." />
            ) : (
              <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Work types">
                {types.map((t) => (
                  <li key={t.slug}>
                    <Hint
                      as="button"
                      id="link.library.work_type"
                      type="button"
                      onClick={() => setParams({ type: t.slug })}
                      aria-pressed={t.slug === chosen}
                      className={`rounded border px-3 py-1 text-sm ${t.slug === chosen ? 'border-on-surface font-bold' : 'border-border'}`}
                    >
                      {t.title} · {t.tasks} mined{t.status !== 'global' ? ` · ${t.status}` : ''}
                    </Hint>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {page.isError && <ErrorState error={page.error} compact />}
          {page.data && <WorkTypeSection page={page.data} />}
          {chosen && !pageable && types.some((t) => t.slug === chosen) && <p>This work type has no page until it is signed.</p>}
          <IndexSection repo={repo} entries={lib.data.entries} meId={me?.id ?? ''} />
          {can('operator') && <MineCard repo={repo} />}
          {can('operator') && <ProposeForm repo={repo} kinds={lib.data.kinds} characteristics={lib.data.characteristics} statementMax={lib.data.statement_max} />}
        </>
      )}
    </>
  )
}
