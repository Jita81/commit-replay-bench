/**
 * An organisation's classes of work — its class sets, a page per class and the labelling screen.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /classes (`?org=`, `?v=`, `?class=` pick an organisation, a
 *               version and a class): every version with its status, sponsor, signer and
 *               whether it routes; the chosen version's split into derivation and confirmation
 *               commits, its classes and its validity report against ADR-0026's thresholds;
 *               the page for one class in the user's words (what the work is, example commits,
 *               what a ticket in it must carry, the context its builder would get and what is
 *               proven per size); the labelling screen; and the proposal form.
 * What it does: Lets an operator propose the organisation's next version (and so sponsor it),
 *               listing the global classes a class may refine; lets a person who is not the
 *               sponsor label derivation commits — the screen shows the commit's message, its
 *               linked ticket, a diff summary and what each class means, never the rule's class
 *               for that commit, another person's label or an outcome, and the agreement is
 *               withheld from them until their sample is done — and a DIFFERENT approver sign
 *               it; the sponsor's own Sign button is disabled and says why (the API refuses it
 *               too, 409 `same_person`). A revocation is appended with a reason. The route
 *               verdict is said in words wherever the version is shown, naming only the checks
 *               that stop routing. Every refusal and every failed read is shown in words; focus
 *               follows each act (the next commit after a label, the result after signing, the
 *               class's heading when its page opens).
 * How:          `useClassSets` + `useClassSetVersion` + `useClassPage` + `useLabelQueue` +
 *               `useClassSetAct`; tables through `DataTable` with a hint on every column; forms
 *               through `Field`; every element a reader meets is a hint trigger (`*.classes.*`).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 9),
 *               docs/adr/0016-two-person-rule-is-a-policy-clause-not-an-apparatus-move.md
 * Works with:   ui/src/screens/Classes/useClasses.ts (the reads and acts), ui/src/api/types.ts
 *               (`ClassSetIndex`, `ClassSetVersionDetail`, `ClassPage`, `ClassLabelQueue`),
 *               ui/src/help/hints.ts (the copy), ui/src/help/help.ts (the About block),
 *               ui/src/screens/Library/LibraryPage.tsx (the door, and each class's library page)
 * Tested by:    ui/src/screens/Classes/ClassesPage.test.tsx, ui/src/help/hints-ratchet.test.tsx,
 *               ui/e2e/walkthrough/15-classes.spec.ts
 * Touch when:   onboarding a client repository never needs it — a repository joins a class set
 *               when a version names it; a field of the page changes in docs/API.md#classes first.
 */
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { isApiError } from '../../api/client'
import type { ClassLabelQueue, ClassPage, ClassSetIndex, ClassSetMeasure, ClassSetStatus, ClassSetVersionDetail, ClassSetVersionSummary } from '../../api/types'
import { Card } from '../../components/Card'
import { type Column, DataTable } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { SelectField, TextArea, TextField } from '../../components/Field'
import { Hint } from '../../components/Hint'
import { Pill } from '../../components/Pill'
import { BackLink, Details, InsetText, Kicker, Lede, PageTitle, SecondaryButton, StartButton, Tag, type TagTone, WarningButton } from '../../components/govuk'
import { useAuth } from '../../lib/auth'
import { useClassPage, useClassSetAct, useClassSets, useClassSetVersion, useLabelQueue } from './useClasses'

const STATUS_TONE: Record<ClassSetStatus, TagTone> = { proposed: 'blue', signed: 'green', revoked: 'red' }
const MEASURE_LABEL: Record<ClassSetMeasure['name'], string> = {
  coverage: 'Coverage',
  agreement: 'Agreement with a person (κ)',
  stability: 'Stability',
  ticket_consistency: 'Ticket and message agree',
  size_agreement: 'Points agree with churn',
  measurability: 'Cells with enough confirmation commits',
  override_rate: 'Override rate',
}
const UNCLASSIFIED = '(unclassified)'

function who(name: string, id: string): string {
  return name || (id ? `${id.slice(0, 8)}…` : '—')
}

function value(m: ClassSetMeasure): string {
  if (m.value === null) return '—'
  if (m.name === 'agreement') return m.value.toFixed(2)
  if (m.name === 'measurability') return String(m.value)
  return `${(m.value * 100).toFixed(1)}%`
}

/** The server's words set as the page's: an apostrophe inside a word is typographic (’). */
function typeset(words: string): string {
  return words.replace(/(\p{L})'(\p{L})/gu, '$1’$2')
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

/** The State cell of one measure: the points check says what it decides, never "fail" (P-688). */
function measureTag(m: ClassSetMeasure) {
  if (m.name === 'size_agreement') {
    const used = m.state === 'pass'
    return (
      <Tag tone={used ? 'green' : 'grey'} hint="tag.classes.points" data-testid={`measure-${m.name}`}>
        {used ? 'points size tickets' : 'points not used'}
      </Tag>
    )
  }
  const tone: TagTone = m.state === 'pass' ? 'green' : m.state === 'fail' ? 'red' : 'grey'
  return (
    <Tag tone={tone} hint="tag.classes.measure_state" data-testid={`measure-${m.name}`}>
      {m.state === 'not_applicable' ? 'not applicable' : m.state}
    </Tag>
  )
}

function refusal(err: unknown): string {
  if (!err) return ''
  if (isApiError(err)) return typeset(err.message)
  return err instanceof Error ? err.message : String(err)
}

/** A refused act, said beside the control that made it and focused when it appears (P-397). */
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

function RouteLine({ route }: { route: ClassSetVersionSummary['route'] }) {
  return (
    <InsetText>
      <Tag tone={route.routes ? 'green' : 'grey'} hint="tag.classes.routes" data-testid="class-set-route">
        {route.routes ? 'Routes' : 'Routes nothing'}
      </Tag>{' '}
      {typeset(route.words)}
    </InsetText>
  )
}

function VersionSection({ detail, meId, onPage }: { detail: ClassSetVersionDetail; meId: string; onPage: (slug: string) => void }) {
  const { can } = useAuth()
  const sign = useClassSetAct()
  const revoke = useClassSetAct()
  const [reason, setReason] = useState('')
  const [asked, setAsked] = useState(false)
  const [signedWords, setSignedWords] = useState('')
  const signedRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (signedWords) signedRef.current?.focus()
  }, [signedWords])
  const counts = new Map(detail.class_counts.map((c) => [c.class, c]))
  const classes: Column<ClassSetVersionDetail['version']['classes'][number]>[] = [
    { key: 'class', header: 'Class', hint: 'col.classes.class', mono: true, cell: (c) => c.slug },
    { key: 'title', header: 'What it is', hint: 'col.classes.definition', cell: (c) => c.title },
    { key: 'parent', header: 'Global parent', hint: 'col.classes.parent', mono: true, cell: (c) => c.parent, hideBelowMd: true },
    { key: 'der', header: 'Derivation commits', hint: 'col.classes.derivation_n', numeric: true, cell: (c) => counts.get(c.slug)?.derivation ?? 0, hideBelowMd: true },
    { key: 'con', header: 'Confirmation commits', hint: 'col.classes.confirmation_n', numeric: true, cell: (c) => counts.get(c.slug)?.confirmation ?? 0 },
    {
      key: 'page',
      header: 'Page',
      hint: 'col.classes.page',
      cell: (c) => (
        <SecondaryButton hint="button.classes.page" onClick={() => onPage(c.slug)}>
          Read its page
        </SecondaryButton>
      ),
    },
  ]
  const measures: Column<ClassSetMeasure>[] = [
    { key: 'name', header: 'Measure', hint: 'col.classes.measure', cell: (m) => MEASURE_LABEL[m.name] },
    { key: 'value', header: 'Result', hint: 'col.classes.result', numeric: true, cell: (m) => value(m) },
    { key: 'n', header: 'Read over', hint: 'col.classes.n', numeric: true, cell: (m) => m.n, hideBelowMd: true },
    { key: 'state', header: 'State', hint: 'col.classes.state', cell: (m) => measureTag(m) },
    { key: 'words', header: 'What it means', hint: 'col.classes.words', cell: (m) => typeset(m.words) },
    { key: 'threshold', header: 'Threshold', hint: 'col.classes.threshold', cell: (m) => m.threshold, hideBelowMd: true },
  ]
  const split: Column<ClassSetVersionDetail['split'][number]>[] = [
    { key: 'repo', header: 'Repository', hint: 'col.classes.repo', cell: (s) => s.repo },
    { key: 'der', header: 'Derivation', hint: 'col.classes.derivation', numeric: true, cell: (s) => s.derivation },
    { key: 'con', header: 'Confirmation', hint: 'col.classes.confirmation', numeric: true, cell: (s) => s.confirmation },
  ]
  const own = detail.sponsor === meId
  const reasonError = asked && !reason.trim() ? 'Give the reason; it is kept on the record.' : undefined
  return (
    <Card title={`Class set ${detail.version_id}`} id="version">
      <p>
        Proposed by {who(detail.sponsor_name, detail.sponsor)}
        {detail.approver ? `, signed by ${who(detail.approver_name, detail.approver)}` : ', not signed yet'}.{' '}
        <Tag tone={STATUS_TONE[detail.status]} hint="tag.classes.status" data-testid="class-set-status">
          {detail.status}
        </Tag>
      </p>
      <RouteLine route={detail.route} />
      <h3 className="mt-6 text-lg font-bold">Its classes</h3>
      <DataTable rows={detail.version.classes} columns={classes} rowKey={(c) => c.slug} caption={`Classes of ${detail.version_id}`} empty="No class." dense />
      <h3 className="mt-6 text-lg font-bold">The validity report</h3>
      <p className="text-sm">A version routes nothing until every measure but the points check passes and a second person has signed it. Points agreeing with churn decides only whether story points size a ticket.</p>
      <DataTable rows={detail.report.measures} columns={measures} rowKey={(m) => m.name} caption={`Validity report of ${detail.version_id}`} empty="No measure." dense />
      <h3 className="mt-6 text-lg font-bold">Commits held out</h3>
      <p className="text-sm">
        Before any class was proposed, each commit was put in the derivation set (one in {Math.round(1 / detail.version.derivation_share)}) or the confirmation set by a seeded hash. Classes are checked on derivation commits and licensed only on confirmation commits.
      </p>
      <DataTable rows={detail.split} columns={split} rowKey={(s) => s.repo} caption={`Derivation and confirmation commits of ${detail.version_id}`} empty="No repository." dense />
      {can('approver') && detail.status === 'proposed' && (
        <div className="mt-6">
          <Refused error={sign.error} testId="class-set-sign-refused" />
          <StartButton
            hint={own ? 'button.classes.sign_own' : 'button.classes.sign'}
            disabled={own}
            pending={sign.isPending}
            onClick={() =>
              sign.mutate(
                { act: 'sign', org: detail.org, n: detail.n, digest: detail.digest },
                { onSuccess: (v) => setSignedWords(`You signed ${detail.version_id}. ${typeset((v as ClassSetVersionSummary).route.words)}`) },
              )
            }
          >
            Sign this class set
          </StartButton>
          {own && <p className="mt-1 text-sm">You sponsored this class set, so a second person must sign it.</p>}
        </div>
      )}
      <p ref={signedRef} tabIndex={-1} role="status" aria-live="polite" className="mt-3" data-testid="class-set-signed">
        {signedWords}
      </p>
      {can('approver') && detail.status !== 'revoked' && (
        <form className="mt-6 space-y-3" aria-label="Revoke this class set" onSubmit={(e) => e.preventDefault()}>
          <Refused error={revoke.error} testId="class-set-revoke-refused" />
          <TextField label="Reason to revoke" value={reason} onChange={(e) => setReason(e.target.value)} hint="field.classes.reason" error={reasonError} />
          <WarningButton
            hint="button.classes.revoke"
            pending={revoke.isPending}
            onClick={() => {
              setAsked(true)
              if (reason.trim() && !revoke.isPending) revoke.mutate({ act: 'revoke', org: detail.org, n: detail.n, reason: reason.trim() })
            }}
          >
            Revoke
          </WarningButton>
        </form>
      )}
    </Card>
  )
}

function ClassSection({ page }: { page: ClassPage }) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    // opened from "Read its page" far above: bring its heading into view and say where you are
    headingRef.current?.scrollIntoView?.({ block: 'start' })
    headingRef.current?.focus()
  }, [page.slug])
  const sizes: Column<ClassPage['sizes'][number]>[] = [
    { key: 'repo', header: 'Repository', hint: 'col.classes.size_repo', cell: (s) => s.repo, hideBelowMd: true },
    { key: 'size', header: 'Size', hint: 'col.classes.size', cell: (s) => s.size },
    { key: 'con', header: 'Confirmation commits', hint: 'col.classes.size_confirmation', numeric: true, cell: (s) => s.confirmation },
    {
      key: 'standard',
      header: 'Proven standard',
      hint: 'col.classes.standard',
      cell: (s) => (s.standard ? `${s.standard.arm}${s.standard.ceiling ? ' (ceiling, forward-unvalidated)' : ''}` : 'No proven standard'),
    },
    { key: 'next', header: 'The next measurement', hint: 'col.classes.next', cell: (s) => typeset(s.next) || `reading ${s.standard?.reading_id ?? ''}` },
  ]
  const context: Column<ClassPage['context'][number]>[] = [
    { key: 'entry', header: 'Entry', hint: 'col.classes.entry', mono: true, cell: (c) => c.entry_id },
    { key: 'statement', header: 'What it says', hint: 'col.classes.statement', cell: (c) => c.statement },
    { key: 'people', header: 'Sponsor and signer', hint: 'col.classes.people', cell: (c) => `${who(c.sponsor_name, c.sponsor)} and ${who(c.approver_name, c.approver)}` },
    { key: 'effect', header: 'Measured effect', hint: 'col.classes.effect', cell: (c) => c.effect },
  ]
  return (
    <Card id="class">
      <h2 ref={headingRef} tabIndex={-1} className="mb-3 text-[16px] leading-6 font-bold" data-testid="class-heading">
        Class: {page.title}
      </h2>
      <RouteLine route={page.route} />
      <dl className="m-0 space-y-4">
        <Hint as="div" id="row.classes.definition" className="block">
          <dt className="font-bold">What the work is</dt>
          <dd className="m-0">
            {page.definition}{' '}
            <span className="text-on-surface-muted">
              (in {page.version_id}, a kind of <span className="font-mono text-xs">{page.parent}</span>: {page.parent_definition || 'a global class'})
            </span>
          </dd>
        </Hint>
        <Hint as="div" id="row.classes.rule" className="block">
          <dt className="font-bold">How a ticket is put in it</dt>
          <dd className="m-0" data-testid="class-rule">
            {typeset(page.rule_words)} A person can say otherwise with a crb:class={page.slug} label on the ticket, and every such override is counted.
          </dd>
        </Hint>
        <Hint as="div" id="row.classes.examples" className="block">
          <dt className="font-bold">Example commits</dt>
          <dd className="m-0">
            {page.examples.length === 0 ? (
              'No derivation commit is in this class yet.'
            ) : (
              <ul className="m-0 list-disc pl-5">
                {page.examples.map((x) => (
                  <li key={`${x.repo}/${x.sha}`}>
                    <Link to={`/tasks/${encodeURIComponent(x.repo)}/${encodeURIComponent(x.sha)}`} className="font-mono text-xs underline">
                      {x.sha.slice(0, 12)}
                    </Link>{' '}
                    {x.subject} ({x.size}
                    {x.proxy ? ', read from its message' : ', read from its ticket'})
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </Hint>
        <Hint as="div" id="row.classes.ticket" className="block">
          <dt className="font-bold">What a ticket in it must carry</dt>
          <dd className="m-0">
            {page.ticket_slots.length === 0 ? (
              <p className="m-0" data-testid="class-no-slots">
                No readiness question is set for {page.parent} yet, so a ticket in this class needs only its acceptance criteria. A signed work-type entry for this class can add questions in{' '}
                <Link to={`/library/${encodeURIComponent(page.library[0]?.repo ?? page.entry_repo)}?type=${encodeURIComponent(page.library[0]?.work_type ?? page.parent)}`} className="underline">
                  the library
                </Link>
                .
              </p>
            ) : (
              <ul className="m-0 list-disc pl-5">
                {page.ticket_slots.map((s) => (
                  <li key={s.name}>
                    <span className="font-mono text-xs">{s.name}</span> — {s.question}
                  </li>
                ))}
              </ul>
            )}
            {page.signed_slots.length > 0 && <p className="mt-2">Signed test-standard slots: {page.signed_slots.join(', ')}.</p>}
          </dd>
        </Hint>
        <Hint as="div" id="row.classes.context" className="block">
          <dt className="font-bold">The context its builder would get</dt>
          <dd className="m-0">
            The signed library entries scoped to this class or its parent, read on{' '}
            {page.library.map((l, i) => (
              <span key={l.repo}>
                {i > 0 ? ', ' : ''}
                <Link to={`/library/${encodeURIComponent(l.repo)}?type=${encodeURIComponent(l.work_type)}`} className="underline">
                  the {l.repo} library’s {l.work_type} page
                </Link>
              </span>
            ))}
            . None reaches a builder until an arm has measured it.
          </dd>
        </Hint>
      </dl>
      <DataTable rows={page.context} columns={context} rowKey={(c) => `${c.repo}/${c.entry_id}`} caption={`Signed context for ${page.slug}`} empty="No signed entry is scoped to this class yet." dense />
      <h3 className="mt-6 text-lg font-bold">What is proven, per size</h3>
      {!page.route.routes && <p className="text-sm">No size has a proven standard while the class set routes nothing: {typeset(page.route.words)}</p>}
      <DataTable rows={page.sizes} columns={sizes} rowKey={(s) => `${s.repo}/${s.size}`} caption={`Proven standard per size for ${page.slug}`} empty="No repository." dense />
    </Card>
  )
}

function LabelSection({ org, n, queue }: { org: string; n: number; queue: ClassLabelQueue }) {
  const act = useClassSetAct()
  const next = queue.items.find((x) => !x.my_label)
  const [klass, setKlass] = useState('')
  const [done, setDone] = useState('')
  const [moved, setMoved] = useState(0)
  const nextRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    // after a label, the next commit's message is where the labeller carries on (P-687)
    if (moved) nextRef.current?.focus()
  }, [moved])
  const titles = new Map(queue.classes.map((c) => [c.slug, c.title]))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!next || !klass || act.isPending) return
    const said = klass === UNCLASSIFIED ? 'none of these classes' : (titles.get(klass) ?? klass)
    act.mutate(
      { act: 'label', org, n, repo: next.repo, taskId: next.task_id, klass },
      {
        onSuccess: () => {
          setDone(`Saved: “${next.message}” is ${said}.`)
          setKlass('')
          setMoved((m) => m + 1)
        },
      },
    )
  }
  const short = Math.max(0, queue.sample_min - queue.items.length)
  return (
    <Card title="Label a sample" id="label">
      {queue.sponsor ? (
        <p data-testid="label-sponsor">You sponsored this class set. Its rule is your own words, so another person labels its sample: your labels would check the rule against its author.</p>
      ) : (
        <p>
          You have labelled {queue.labelled_by_me} of {plural(queue.items.length, 'derivation commit', 'derivation commits')}. The report needs at least {queue.sample_min} labelled commits and {queue.per_class_min} in each class. For each commit you see its message and ticket: never the class the rule gives it, another person’s label or whether a build passed, and the report’s agreement is withheld from you until you have labelled them all. The classes’ pages show each rule in words, and their example commits are never offered here, so label before you read them if you can.
        </p>
      )}
      {queue.sponsor ? null : next ? (
        <form onSubmit={submit} className="space-y-4" aria-label={`Label a commit for ${queue.version_id}`}>
          <Hint as="div" id="row.classes.label_message" className="block">
            <h3 ref={nextRef} tabIndex={-1} className="m-0 text-base font-bold" data-testid="label-next">
              The commit’s message
            </h3>
            <p className="m-0 font-mono text-sm" data-testid="label-message">
              {next.message}
            </p>
          </Hint>
          <Hint as="div" id="row.classes.label_ticket" className="block">
            <p className="m-0 font-bold">Its linked ticket</p>
            <p className="m-0 text-sm">{next.ticket ? `${next.ticket.work_item_type || 'ticket'} as it stood (${next.ticket.source}): ${next.ticket.text}` : 'No linked ticket: the message stands in for one.'}</p>
          </Hint>
          <Hint as="div" id="row.classes.label_diff" className="block">
            <p className="m-0 font-bold">What changed</p>
            <p className="m-0 text-sm">
              {plural(next.diff.source_files, 'source file', 'source files')} and {plural(next.diff.test_files, 'test file', 'test files')}, {plural(next.diff.churn, 'line', 'lines')} of source.
            </p>
          </Hint>
          <SelectField label="Which class is it?" value={klass} onChange={(e) => setKlass(e.target.value)} hint="field.classes.label">
            <option value="">Choose a class</option>
            {queue.classes.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.title} ({c.slug})
              </option>
            ))}
            <option value={UNCLASSIFIED}>None of these</option>
          </SelectField>
          <Hint as="div" id="row.classes.label_definitions" className="block">
            <p className="m-0 font-bold">What each class means</p>
            <dl className="m-0 space-y-1 text-sm" data-testid="label-definitions">
              {queue.classes.map((c) => (
                <div key={c.slug}>
                  <dt className="inline font-bold">{c.title}</dt>
                  <dd className="m-0 inline">
                    {' '}
                    ({c.slug}): {c.definition}
                  </dd>
                </div>
              ))}
            </dl>
          </Hint>
          <Refused error={act.error} testId="class-label-refused" />
          <StartButton type="submit" pending={act.isPending} hint="button.classes.label" disabled={!klass}>
            Save label
          </StartButton>
        </form>
      ) : queue.items.length === 0 ? (
        <p data-testid="label-empty">No derivation commit is ready to label yet. Mine more of the repositories’ history (Connect, then Measure), and the new commits appear here.</p>
      ) : (
        <p data-testid="label-done">
          You have labelled every derivation commit this version offers.
          {short > 0 && ` Its sample needs ${plural(short, 'more commit', 'more commits')} than its repositories hold: mine more of their history (Connect, then Measure) and label the new ones.`}
        </p>
      )}
      <p role="status" aria-live="polite" className="mt-3" data-testid="class-labelled">
        {done}
      </p>
    </Card>
  )
}

/** One class per line: `slug; global parent; title; what it is; words, that, name, it`. */
function parseClasses(text: string) {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [slug = '', parent = '', title = '', definition = '', words = ''] = line.split(';').map((p) => p.trim())
      return { slug, parent, title, definition, rule: { words: words.split(',').map((w) => w.trim()).filter(Boolean) } }
    })
}

function ProposeForm({ orgs, repos, parents }: { orgs: string[]; repos: string[]; parents: ClassSetIndex['global_classes'] }) {
  const act = useClassSetAct()
  const [org, setOrg] = useState(orgs[0] ?? '')
  const [chosen, setChosen] = useState(repos.join(', '))
  const [lines, setLines] = useState('')
  const [done, setDone] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (act.isPending) return
    setDone('')
    const body = { repos: chosen.split(',').map((r) => r.trim()).filter(Boolean), classes: parseClasses(lines) }
    act.mutate(
      { act: 'propose', org: org.trim(), body },
      { onSuccess: (v) => setDone(`Proposed ${(v as ClassSetVersionSummary).version_id}. You are its sponsor; a different approver must sign it.`) },
    )
  }
  return (
    <Card title="Propose a class set" id="propose">
      <p>You become the version’s sponsor. Its rule reads only what a ticket carries, so a class is said in the ticket’s own words. The next number is given for you.</p>
      <form onSubmit={submit} className="space-y-4" aria-label="Propose a class set">
        <Refused error={act.error} testId="class-set-propose-refused" />
        <TextField label="Organisation" value={org} onChange={(e) => setOrg(e.target.value)} required hint="field.classes.org" description="Lower case letters, digits, dots and dashes." />
        <TextField label="Repositories" value={chosen} onChange={(e) => setChosen(e.target.value)} required hint="field.classes.repos" description="Comma-separated repository names." />
        <TextArea
          label="Classes, one per line"
          value={lines}
          onChange={(e) => setLines(e.target.value)}
          required
          hint="field.classes.lines"
          description="slug; global parent; title; what it is; words the ticket uses, comma-separated. For example: parser-fix; bug.fix; A fix to the parser; A change to how the parser reads input; parser, parse"
        />
        <Hint as="div" id="row.classes.global_parents" className="block">
          <Details summary={`The ${parents.length} global classes a class can refine`}>
            <dl className="m-0 space-y-1 text-sm" data-testid="global-parents">
              {parents.map((p) => (
                <div key={p.slug}>
                  <dt className="inline font-mono text-xs">{p.slug}</dt>
                  <dd className="m-0 inline"> — {p.definition}</dd>
                </div>
              ))}
            </dl>
          </Details>
        </Hint>
        <StartButton type="submit" pending={act.isPending} hint="button.classes.propose">
          Propose as sponsor
        </StartButton>
      </form>
      <div role="status" aria-live="polite" className="mt-3" data-testid="class-set-proposed">
        {done}
      </div>
    </Card>
  )
}

export function ClassesPage() {
  const [params, setParams] = useSearchParams()
  const { can, me } = useAuth()
  const idx = useClassSets()
  const all = useMemo(() => (idx.data?.orgs ?? []).flatMap((o) => o.versions), [idx.data])
  const org = params.get('org') ?? all[0]?.org ?? ''
  const latest = all.find((v) => v.org === org)
  const n = Number(params.get('v') ?? latest?.n ?? 0)
  const slug = params.get('class') ?? ''
  const detail = useClassSetVersion(org, n)
  const page = useClassPage(org, n, slug)
  const queue = useLabelQueue(org, n, can('operator'))
  const routing = all.filter((v) => v.route.routes).length
  const pick = (next: Record<string, string>) => setParams(next)
  const versions: Column<ClassSetVersionSummary>[] = [
    // at 375 px only Version, Routes and Open show: the id breaks and the tag wraps, so the
    // Open button (the only way to switch version) stays on screen (P-687)
    { key: 'id', header: 'Version', hint: 'col.classes.version', mono: true, cell: (v) => <span className="break-all" data-testid="version-id">{v.version_id}</span> },
    {
      key: 'status',
      header: 'Status',
      hint: 'col.classes.status',
      cell: (v) => (
        <Tag tone={STATUS_TONE[v.status]} hint="tag.classes.status">
          {v.status}
        </Tag>
      ),
      hideBelowMd: true,
    },
    { key: 'sponsor', header: 'Sponsor', hint: 'col.classes.sponsor', cell: (v) => who(v.sponsor_name, v.sponsor), hideBelowMd: true },
    { key: 'approver', header: 'Signed by', hint: 'col.classes.approver', cell: (v) => who(v.approver_name, v.approver), hideBelowMd: true },
    {
      key: 'routes',
      header: 'Routes',
      hint: 'col.classes.routes',
      cell: (v) => (
        <Tag tone={v.route.routes ? 'green' : 'grey'} hint="tag.classes.routes" wrap data-testid="version-routes">
          {v.route.routes ? 'Routes' : 'Routes nothing'}
        </Tag>
      ),
    },
    {
      key: 'open',
      header: 'Open',
      hint: 'col.classes.open',
      cell: (v) => (
        <SecondaryButton hint="button.classes.open" onClick={() => pick({ org: v.org, v: String(v.n) })}>
          Open
        </SecondaryButton>
      ),
    },
  ]
  // back to the context library the page's door is on: the version's first repository's
  const home = detail.data?.version.repos[0] ?? idx.data?.repos[0] ?? ''
  return (
    <>
      <BackLink to={home ? `/library/${encodeURIComponent(home)}` : '/home'} hint="link.classes.back">
        Back to the context library
      </BackLink>
      <Kicker>Classes of work</Kicker>
      <PageTitle>Your organisation’s classes of work</PageTitle>
      <Lede>
        The kinds of change your organisation makes, in its own words, each a child of one global class. A sponsor proposes a set, people label a sample of commits, the report checks the rule against them, and a different approver signs it. A set routes nothing until both are done.
      </Lede>
      <div className="mb-6" data-testid="classes-count" data-ready={idx.data ? 'true' : 'false'}>
        <Pill tone={routing > 0 ? 'green' : 'primary'} size="sm" label={`${all.length} versions, ${routing} routing`} hint="stat.classes.count">
          {idx.data ? `${all.length} versions · ${routing} routing` : 'counting…'}
        </Pill>
      </div>
      {idx.isError && <ErrorState error={idx.error} onRetry={() => void idx.refetch()} />}
      {idx.data && (
        <Card title="Versions" id="versions">
          {all.length === 0 ? (
            <EmptyState compact title="No class set yet" reason="Until one is signed and its report passes, every repository is read by the global classes." />
          ) : (
            <DataTable rows={all} columns={versions} rowKey={(v) => v.version_id} caption="Class-set versions" empty="No version." dense />
          )}
        </Card>
      )}
      {detail.isError && <ErrorState error={detail.error} compact />}
      {detail.data && <VersionSection detail={detail.data} meId={me?.id ?? ''} onPage={(s) => pick({ org, v: String(n), class: s })} />}
      {page.isError && <ErrorState error={page.error} compact />}
      {page.data && <ClassSection page={page.data} />}
      {can('operator') && queue.isError && <ErrorState error={queue.error} compact />}
      {can('operator') && queue.data && <LabelSection org={org} n={n} queue={queue.data} />}
      {can('operator') && idx.data && <ProposeForm orgs={(idx.data.orgs ?? []).map((o) => o.org)} repos={idx.data.repos} parents={idx.data.global_classes ?? []} />}
    </>
  )
}
