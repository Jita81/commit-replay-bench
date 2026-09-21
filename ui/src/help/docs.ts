/**
 * The eight user-facing guides, bundled into the UI at build time and served at /help/docs.
 *
 * Why bundle rather than link to GitHub: the repository is private, enterprise deployments
 * run without egress (docs/SECURITY.md §2), and a bundled copy is pinned to the exact commit
 * the UI was built from. The guides load as lazy chunks, only when one is opened. ADRs are
 * not bundled: /help lists their titles.
 *
 * Navigation
 * ----------
 * What it is:   `DOC_NAMES` / `DocName` / `DocAnchor`, `loadDoc`, `docHref`, `isDocName`, `slugify`.
 * What it does: Declares which guides the UI carries (`import.meta.glob` with `?raw`, lazy),
 *               loads one by name, builds the in-app route for a `<name>#<slug>` anchor, and
 *               slugifies a heading the way GitHub does so the docs' own anchors resolve.
 *               An unknown name rejects so the page can say "No guide with that name".
 * How:          The glob is resolved by Vite (`../../../docs/…` is the repository's docs/);
 *               the dev server allows it through `server.fs.allow` in vite.config.ts.
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/screens/Help/DocPage.tsx (calls `loadDoc` and renders),
 *               ui/src/help/markdown.ts (rewrites relative links through `isDocName`),
 *               ui/src/help/help.ts and ui/src/help/glossary.ts (`DocAnchor` in `readMore`),
 *               ui/src/components/Help.tsx (`DocLink`), ui/vite.config.ts (`server.fs.allow`)
 * Tested by:    ui/src/help/docs.test.ts, ui/src/help/help.test.ts (every anchor resolves)
 * Touch when:   a guide is added for readers of the UI — add it to `DOC_NAMES`, the glob and
 *               `DOC_TITLES`; never for a new repository.
 */

/** The guides the UI bundles, in the order /help lists them. */
export const DOC_NAMES = ['ONBOARDING-A-REPO', 'OPERATOR', 'EVIDENCE-AND-CLAIMS', 'GITHUB-APP', 'SECURITY', 'DATA-RETENTION', 'LEARNING-LOOP', 'DEPLOYMENT'] as const

export type DocName = (typeof DOC_NAMES)[number]

/** `OPERATOR` or `OPERATOR#4-read-the-capability-map`. */
export type DocAnchor = DocName | `${DocName}#${string}`

/** One line per guide for the /help index. */
export const DOC_TITLES: Record<DocName, { title: string; blurb: string }> = {
  'ONBOARDING-A-REPO': { title: 'Using Commit Replay Bench on a repository', blurb: 'The eight steps from registering a repository to forward mode, and what you may claim afterwards.' },
  OPERATOR: { title: 'Operator guide', blurb: 'Install, configure a repository, run a sweep, read the map, sign off, export the ledger, stop conditions.' },
  'EVIDENCE-AND-CLAIMS': { title: 'Evidence and claims policy', blurb: 'What clean and false-Q1 mean, why every number carries its method, and what must never be said.' },
  'GITHUB-APP': { title: 'The GitHub App', blurb: 'Why an App and not a token; register it once, install it per organisation, connect a repository.' },
  SECURITY: { title: 'Security and threat model', blurb: 'Trust boundaries, the sandbox, credentials, sign-in and evidence integrity.' },
  'DATA-RETENTION': { title: 'Data retention and privacy', blurb: 'Zero raw retention by default, redaction, access, cross-organisation sharing and deletion.' },
  'LEARNING-LOOP': { title: 'The learning loop', blurb: 'What loops mechanically, what the product derives, and what a person still does.' },
  DEPLOYMENT: { title: 'Deployment guide', blurb: 'Deployment shapes, the image, Kubernetes, Azure, backup, upgrade and the go-live checklist.' },
}

const DOCS = import.meta.glob('../../../docs/{ONBOARDING-A-REPO,OPERATOR,EVIDENCE-AND-CLAIMS,GITHUB-APP,SECURITY,DATA-RETENTION,LEARNING-LOOP,DEPLOYMENT}.md', { query: '?raw', import: 'default' }) as Record<string, () => Promise<string>>

export function isDocName(name: string): name is DocName {
  return (DOC_NAMES as readonly string[]).includes(name)
}

/** The guide's markdown, as a lazy chunk; rejects for a name that is not bundled. */
export async function loadDoc(name: DocName): Promise<string> {
  const loader = DOCS[`../../../docs/${name}.md`]
  if (!loader || !isDocName(name)) throw new Error(`No guide with that name: ${name}`)
  return loader()
}

/** `OPERATOR#4-read-the-capability-map` → `/help/docs/OPERATOR#4-read-the-capability-map`. */
export function docHref(anchor: DocAnchor): string {
  const [name, slug] = anchor.split('#')
  return slug ? `/help/docs/${name}#${slug}` : `/help/docs/${name}`
}

/**
 * GitHub's heading slug: trim, lower-case, drop everything but letters, numbers, spaces and
 * hyphens, then spaces → hyphens (repeated hyphens are kept — the docs' own anchors depend on
 * it: `4. The apparatus stamp — evidence expires` → `4-the-apparatus-stamp--evidence-expires`).
 */
export function slugify(heading: string): string {
  return heading
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s/g, '-')
}
