/**
 * The architecture decision records, bundled into the UI at build time and served at
 * /help/docs/ADR-nnnn beside the eight guides.
 *
 * Why bundle rather than link to the repository: a screen cites an ADR (ADR-0015 on the
 * sign-off, ADR-0016 on the two-person rule) and a reviewer following it must be able to read
 * it where they stand — the repository is private and a deployment may have no egress
 * (docs/SECURITY.md §2), exactly the reason the guides are bundled (DL-073).
 *
 * Navigation
 * ----------
 * What it is:   `ADR_TITLES` (number → title, the list /help shows), `isAdrName`, `adrNumber`,
 *               `adrTitle`, `adrHref` and `loadAdr`.
 * What it does: Declares the decision records the UI carries (`import.meta.glob` with `?raw`,
 *               lazy — a record's chunk loads only when it is opened), names each by its
 *               number and the title its own first heading gives, builds the in-app route
 *               `/help/docs/ADR-nnnn` and loads one by name. An unknown number rejects, so
 *               the page can say there is no such record rather than render nothing.
 * How:          The glob is resolved by Vite (`../../../docs/adr/…` is the repository's
 *               docs/adr); the dev server reads it through `server.fs.allow` (`../docs`), and
 *               the image build carries it because deploy/Dockerfile.dockerignore re-includes
 *               `docs/adr/*.md` (P-106 — before that the image shipped no guide at all).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none (DL-073)
 * Works with:   ui/src/screens/Help/HelpPage.tsx (lists `ADR_TITLES` as links),
 *               ui/src/screens/Help/DocPage.tsx (renders a record at /help/docs/ADR-nnnn),
 *               ui/src/help/markdown.ts (a guide's `adr/nnnn-….md` link becomes an in-app link),
 *               ui/src/help/docs.ts (the guides' twin registry and `slugify`),
 *               ui/vite.config.ts (`requireBundledDocs` fails the build when docs/adr is absent),
 *               docs/adr/README.md (the index this list mirrors)
 * Tested by:    ui/src/help/adrs.test.ts (the list is the directory: number and title, both
 *               ways — G-157), ui/src/screens/Help/HelpPage.test.tsx (rows link; a record
 *               renders)
 * Touch when:   an ADR is added, renamed or superseded — add or change its row here in the same
 *               change; adrs.test.ts fails until the list and docs/adr agree.
 */

/** Every record in docs/adr, by number, with the title its first heading gives (`# ADR-nnnn — <title>`). */
export const ADR_TITLES: ReadonlyArray<readonly [string, string]> = [
  ['0001', 'Four belts and false-Q1 = 0 enforced at write'],
  ['0002', 'Append-only, hash-chained ledger'],
  ['0003', 'One routing rule'],
  ['0004', 'Builder registry; sighted and blind modes'],
  ['0005', 'Fail-closed Docker sandbox for every test run'],
  ['0006', 'Zero raw retention by default; evidence packs'],
  ['0007', 'Cross-organisation learning: abstract cell export only'],
  ['0008', 'Standard-library core and downward-only layers'],
  ['0009', 'Text-level mutators for the non-Python languages'],
  ['0010', 'Polyglot negative controls (Go and JavaScript)'],
  ['0011', "Belt 5: the repository's own formatter/linter (`repo_lint_clean`)"],
  ['0012', 'The builder runs in a sealed container: an exported checkout, an allowlisted egress'],
  ['0013', "An external reviewer's verdict is recorded, advisory, and never an input to a verdict"],
  ['0014', 'The GitHub App is the connection; a personal access token is not'],
  ['0015', 'A sign-off expires with the apparatus: stale at read, never edited'],
  ['0016', 'The two-person rule is a policy clause, not an apparatus move'],
  ['0017', 'The ticket is the backlog item; the column is the consent gate'],
  ['0019', 'Qualification is posture-relative: a task is proven in the posture that grades it, its dependencies are provisioned per task outside the test container, and the model is blamed only with a witness from that posture'],
  ['0020', 'A bug is closed by prevention: every failure class gets the strongest change it admits, and is closed only when the attempts that saw the change stop showing it'],
  ['0021', 'The factory reviews before it delivers; only an accepted build opens a pull request'],
  ['0022', 'An operator approves a ticket before it is registered; one pass per repository'],
  ['0023', 'Production refuses the unsealed posture unless an evented override says so'],
  ['0024', '"Clean" means working, by construction: the format step, the finish gate, belt 6 `api_stable`, and one switchboard'],
  ['0026', 'The context standard: pre-registered context arms, a look rule with one error budget per cell, a leak guard, an entry gate, class sets held out by commit, and a library that reaches a brief only when measured'],
  ['0028', 'The moments the flow reading needs are recorded when they happen, never derived'],
]

/** `ADR-0015` — the name a record carries in the /help/docs route. */
export type AdrName = `ADR-${string}`

const ADRS = import.meta.glob('../../../docs/adr/[0-9][0-9][0-9][0-9]-*.md', { query: '?raw', import: 'default' }) as Record<string, () => Promise<string>>

/** `ADR-0015` → `0015`; `null` for anything that is not an ADR name. */
export function adrNumber(name: string): string | null {
  const m = /^ADR-(\d{4})$/.exec(name)
  return m ? m[1]! : null
}

/** True for `ADR-nnnn` when the list holds that number. */
export function isAdrName(name: string): name is AdrName {
  const num = adrNumber(name)
  return num !== null && ADR_TITLES.some(([n]) => n === num)
}

/** The record's title, from the list (empty for an unknown name). */
export function adrTitle(name: string): string {
  const num = adrNumber(name)
  return ADR_TITLES.find(([n]) => n === num)?.[1] ?? ''
}

/** `0015` → `/help/docs/ADR-0015`. */
export function adrHref(num: string): string {
  return `/help/docs/ADR-${num}`
}

/** The record's markdown, as a lazy chunk; rejects for a number the build does not carry. */
export async function loadAdr(name: string): Promise<string> {
  const num = adrNumber(name)
  const key = num && isAdrName(name) ? Object.keys(ADRS).find((k) => k.split('/').at(-1)!.startsWith(`${num}-`)) : undefined
  if (!key) throw new Error(`No decision record with that name: ${name}`)
  return ADRS[key]!()
}
