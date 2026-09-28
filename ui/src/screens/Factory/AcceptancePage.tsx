/**
 * Held-out acceptance tests — the second person's part of a calibration build.
 *
 * Navigation
 * ----------
 * What it is:   The screen at /factory/acceptance?repo=: every ticket whose calibration build
 *               needs, or has, held-out acceptance tests a second person writes (ADR-0026
 *               item 8), and the form that writes them.
 * What it does: Shows each ticket as it was written — title, description, acceptance
 *               criteria, kind and size, who funded the build and when — and never its own
 *               failing test; there is no build to see yet. A person with the operator role or
 *               above who is not the ticket's author and not the approver who funded it writes
 *               the tests here, once per build; anyone else is told why they may not. A written
 *               record shows who wrote it, when and its digest — never the tests. After the
 *               build, the row says whether its first attempt passed them.
 * How:          `useRepoParam` → `useAcceptance` (GET, viewer) → one card per ticket →
 *               `useWriteAcceptance` (POST, operator) with the file path and the test text;
 *               a refusal is shown in the API's words beside the form.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         docs/adr/0026-the-context-standard.md (item 8)
 * Works with:   ui/src/api/hooks.ts (`useAcceptance`, `useWriteAcceptance`), ui/src/api/types.ts
 *               (`AcceptanceAssignment`), src/crb/server/routes/acceptance.py (the two routes),
 *               ui/src/screens/Factory/FactoryPage.tsx (links here from a funded calibration
 *               build), ui/src/help/hints.ts (every element), ui/src/help/help.ts (the About block)
 * Tested by:    ui/src/screens/Factory/AcceptancePage.test.tsx, ui/src/help/hints-ratchet.test.tsx,
 *               ui/e2e/walkthrough/10-factory.spec.ts
 * Touch when:   never for a new repository; a field of the assignment changes (docs/API.md and
 *               ui/src/api/types.ts first).
 */
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'
import { isApiError } from '../../api/client'
import { useAcceptance, useWriteAcceptance } from '../../api/hooks'
import type { AcceptanceAssignment } from '../../api/types'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { TextArea, TextField } from '../../components/Field'
import { Hint } from '../../components/Hint'
import { PageHeader } from '../../components/PageHeader'
import { RepoPicker, useRepoParam } from '../../components/RepoPicker'
import { InsetText, NotificationBanner, SummaryList, Tag, type TagTone } from '../../components/govuk'
import { fmtDate } from '../../lib/format'

const STATUS: Record<AcceptanceAssignment['status'], { tone: TagTone; label: string }> = {
  open: { tone: 'blue', label: 'tests needed' },
  written: { tone: 'green', label: 'tests written' },
  building: { tone: 'amber', label: 'being built' },
  graded: { tone: 'grey', label: 'graded' },
}

const RESULT: Record<string, string> = {
  pass: 'Its first attempt passed the held-out tests.',
  fail: 'Its first attempt did not pass the held-out tests: a miss for the forward reading.',
  error: 'The held-out tests could not be run: the ticket leaves the forward reading, never a miss.',
}

function refusal(err: unknown): string {
  if (!err) return ''
  if (isApiError(err)) return err.message
  return err instanceof Error ? err.message : String(err)
}

function who(id: string): string {
  const bare = id.replace(/^(operator|approver|user):/, '')
  return bare.length > 12 ? `${bare.slice(0, 8)}…` : bare || '—'
}

/** The saved state, kept by the page: saving refetches the list, the ticket then reads
 *  "tests written" and its form is gone, so the confirmation cannot live in the form. */
function Saved({ item }: { item: string }) {
  return (
    <NotificationBanner title="Saved" tone="green">
      <p className="m-0" role="status" data-testid={`acceptance-saved-${item}`}>
        Your held-out tests are stored under your name. The builder never sees them: they are run against the build’s first attempt after it finishes.
      </p>
    </NotificationBanner>
  )
}

function WriteForm({ repo, a, onSaved }: { repo: string; a: AcceptanceAssignment; onSaved: (item: string) => void }) {
  const write = useWriteAcceptance()
  const [path, setPath] = useState(`tests/test_${a.item_id.toLowerCase().replace(/[^a-z0-9]+/g, '_')}_held_out.py`)
  const [content, setContent] = useState('')
  const [asked, setAsked] = useState(false)
  function submit(e: FormEvent) {
    e.preventDefault()
    setAsked(true)
    if (!path.trim() || !content.trim()) return
    write.mutate({ repo, item: a.item_id, files: [{ path: path.trim(), content }] }, { onSuccess: () => onSaved(a.item_id) })
  }
  return (
    <form onSubmit={submit} aria-label={`Write the held-out tests for ${a.item_id}`} className="mt-4 space-y-3">
      <TextField
        label="Test file"
        description="A path inside the repository that its test runner treats as a test, and not the ticket’s own test file."
        value={path}
        onChange={(e) => setPath(e.target.value)}
        error={asked && !path.trim() ? 'Name the test file.' : undefined}
        hint="field.acceptance.path"
      />
      <TextArea
        label="Held-out acceptance tests"
        description="Tests a correct change must pass, written from the ticket alone. They are stored whole and never shown to the builder, the ticket’s author or this page again."
        rows={10}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        error={asked && !content.trim() ? 'Write at least one test.' : undefined}
        className="font-mono"
        hint="field.acceptance.content"
      />
      {write.isError && (
        <div role="alert" className="border-l-4 border-status-red p-3" data-testid={`acceptance-refused-${a.item_id}`}>
          {refusal(write.error)}
        </div>
      )}
      <Button type="submit" variant="filled" pending={write.isPending} hint="button.acceptance.save" data-primary>
        Save the held-out tests
      </Button>
    </form>
  )
}

function Assignment({ repo, a, saved, onSaved }: { repo: string; a: AcceptanceAssignment; saved: boolean; onSaved: (item: string) => void }) {
  const st = STATUS[a.status]
  return (
    <Card title={`${a.item_id} · ${a.title}`} className="mb-6">
      <div data-testid={`acceptance-${a.item_id}`}>
        <p className="mb-3">
          <Tag tone={st.tone} hint="tag.acceptance.status" data-testid={`acceptance-status-${a.item_id}`}>
            {st.label}
          </Tag>
        </p>
        <SummaryList
          label={`The ticket ${a.item_id}`}
          rows={[
            { key: 'Kind of change', value: `${a.capability_class} · ${a.size}`, hint: 'stat.acceptance.cell' },
            { key: 'What it asks', value: a.description || '—', hint: 'stat.acceptance.description' },
            {
              key: 'Acceptance criteria',
              value: a.acceptance_criteria.length ? (
                <ul className="m-0 list-disc pl-5">
                  {a.acceptance_criteria.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              ) : (
                'none written'
              ),
              hint: 'stat.acceptance.criteria',
            },
            { key: 'Calibration build funded by', value: who(a.funded_by), note: a.funded_at ? fmtDate(a.funded_at) : undefined, hint: 'stat.acceptance.funded' },
            ...(a.record
              ? [
                  {
                    key: 'Held-out tests',
                    value: `written by ${who(a.record.author)} on ${fmtDate(a.record.written_at)}`,
                    note: `digest ${a.record.sha256.slice(0, 12)}… · ${a.record.paths.join(', ')}`,
                    hint: 'stat.acceptance.record' as const,
                  },
                ]
              : []),
            ...(a.result ? [{ key: 'First attempt', value: RESULT[a.result] ?? a.result, hint: 'stat.acceptance.result' as const }] : []),
          ]}
        />
        {saved ? (
          <Saved item={a.item_id} />
        ) : a.can_write ? (
          <WriteForm repo={repo} a={a} onSaved={onSaved} />
        ) : (
          a.why_not && (
            <p className="mt-4 text-sm text-on-surface-muted" data-testid={`acceptance-why-${a.item_id}`}>
              <Hint id="item.acceptance.why_not">
                <span>{a.why_not}.</span>
              </Hint>
            </p>
          )
        )}
      </div>
    </Card>
  )
}

export function AcceptancePage() {
  const [repo, setRepo] = useRepoParam({ defaultToLatest: true })
  const q = useAcceptance(repo)
  const items = q.data?.assignments ?? []
  const [saved, setSaved] = useState<string[]>([])
  const onSaved = (item: string) => setSaved((prev) => (prev.includes(item) ? prev : [...prev, item]))
  return (
    <>
      <PageHeader
        eyebrow="Journey · 4 of 4 · Factory · held-out tests"
        title="Held-out acceptance tests"
        purpose={
          <>
            Where a cell’s standard is only a ceiling, a ticket is built only as a calibration build, and a second person writes the tests its build is graded on. You see the ticket as it
            was written — not its own failing test, and no build, because none exists yet. The build’s first attempt is run against your tests after it finishes; a registered forward
            reading counts those results, and only it can turn the ceiling into a standard.
          </>
        }
        actions={<RepoPicker value={repo} onChange={setRepo} />}
      />
      <InsetText>
        <Hint id="banner.acceptance.second_person">
          <span>
            You may write them only if you did not write the ticket, did not fund its build and will not run it. Nothing here opens a pull request.{' '}
            <Link to={`/factory?repo=${encodeURIComponent(repo)}`}>Back to the factory</Link>
          </span>
        </Hint>
      </InsetText>
      {!repo && <EmptyState title="Choose a repository" reason="Held-out tests belong to one repository’s calibration builds: choose one from the picker above." />}
      {repo && q.isPending && <p className="text-sm text-on-surface-muted">Loading…</p>}
      {repo && q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {repo && q.data && items.length === 0 && (
        <EmptyState
          glyph="▤"
          title="No calibration build needs held-out tests"
          reason="A ticket appears here when an approver funds a calibration build of it and it carries a failing test a person attached."
          data-testid="acceptance-empty"
        />
      )}
      {repo && items.map((a) => <Assignment key={`${a.item_id}-${a.grant}`} repo={repo} a={a} saved={saved.includes(a.item_id)} onSaved={onSaved} />)}
    </>
  )
}
