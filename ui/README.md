# Commit Replay Bench — UI

The observability front end for crb: repos, runs (with a live SSE log), the
capability map, routing, oracle adequacy, the ledger, sign-off, factory (P6)
and settings. It consumes **[docs/API.md](../docs/API.md)** and nothing else;
every screen fetches from that contract, and every number it shows carries
its `n`, its interval and its apparatus.

## Run

```sh
cd ui
npm install --legacy-peer-deps   # see "Install note" below
npm run dev                      # http://localhost:5173, proxies /api → http://127.0.0.1:8000
```

Point the proxy elsewhere with `CRB_API_ORIGIN=http://host:port npm run dev`.
Cookies (`crb_session`, `crb_csrf`) stay same-origin through the proxy, and the
SSE stream at `/api/v1/runs/{id}/events` is passed through unbuffered.

## Test / typecheck / build

```sh
npm run typecheck   # tsc -b (strict, noUncheckedIndexedAccess)
npm test            # vitest (jsdom) — unit + screen tests against a mocked fetch
npm run build       # tsc -b && vite build → ui/dist (served by the crb server)
npm run e2e         # Playwright smoke + axe (WCAG 2.1 AA); needs `npm run e2e:install` once
```

`npm run e2e` builds, serves `dist/` with `vite preview` on 127.0.0.1:4173 and
intercepts `/api/v1/**` with fixtures — it never contacts a real server.

**Install note.** `npm install` on npm 10.9 can fail with
`Cannot read properties of null (reading 'edgesOut')` while resolving
vitest's optional browser peers. `--legacy-peer-deps` sidesteps the bug; the
resolved tree is the same. Versions are pinned exactly in `package.json`.

## Stack

Vite 8 · React 19 · TypeScript 6 (strict) · react-router 7 · TanStack Query 5 ·
Tailwind v4 (`@tailwindcss/vite`) · vitest + Testing Library + jsdom ·
Playwright + `@axe-core/playwright`. No UI kit, no chart library: the
components under `src/components/` are the whole kit, and `Sparkline` is a
stub until a chart earns its place over a table.

## Layout

```
src/
  api/        client.ts (fetch wrapper) · types.ts (every response type in API.md)
              hooks.ts (one react-query hook per endpoint) · sse.ts (EventSource stream)
  components/ Layout · StatTile · BeltPills · VerdictPill · CiBar · DataTable · EmptyState
              ErrorState · GateBanner · Provenance · JsonView · LiveLog · Sparkline (stub)
              + primitives: Button · Card · Pill · Field · Dialog · PageHeader · RepoPicker · QueryBoundary
  lib/        format.ts (NaN-guarded formatters, Wilson) · verdict.ts (label/tone/glyph tables)
              theme.ts (light/dark/system) · auth.tsx (principal + route guard)
  screens/    Login · Repos (+RepoNewDialog, RepoDetail) · Runs (+RunNewDialog, RunDetailPage,
              EvidenceDrawer, TaskDetailPage) · Capability · Routing · Oracle · Ledger · Signoff
              · Factory · Settings · NotFound
  test/       setup.ts · utils.tsx (mockApi + renderApp)
e2e/          smoke.spec.ts (login + shell against a mocked API, axe WCAG 2.1 AA)
```

## The API client

- `api<T>(path, {method, body, signal, timeoutMs})` — prefixes `/api/v1`,
  sends `credentials: 'include'`, adds `X-CSRF-Token` from the `crb_csrf`
  cookie on POST/PUT/PATCH/DELETE, JSON-encodes bodies, and aborts after
  25 s.
- Failures are always an `ApiError { status, code, message, detail }` parsed
  from the contract's envelope. A timeout is `code: 'timeout'`, a network
  failure `code: 'network'`, a non-envelope body `code: 'invalid_response'`.
  `err.isFalseQ1Refused` is true for the reserved `409 false_q1_refused`.
- `useRunEvents(runId)` opens `GET /runs/{id}/events` as an `EventSource`,
  resumes with `?after=<seq>` on reconnect (capped exponential backoff), keeps
  a bounded buffer (5,000 events), drops malformed frames and counts them,
  and closes on `event: done` or unmount.

## Design laws (from the Ledger v2 standard)

The tokens in `src/index.css` are the Athena "Ledger v2" palette ported
verbatim: paper `#FBFAF6`, ink `#1A1C1E`, muted `#5F646C` (the AA floor —
never lighter), hairline `#E7E2D6`, trust teal `#0E5C5B` as THE accent, status
green/amber/red `#1F7A43 / #9A5B0B / #A33A2E`, categorical blue/violet
`#1F5C8A / #5A3A8A`. Headings are the serif stack (Iowan Old Style /
Palatino / Georgia). Dark mode is keyed to **both** `[data-theme="dark"]` and
`prefers-color-scheme` (system = no attribute).

The rules every component honours:

1. **Numeric integrity** — `StatTile` has no variant without `n` and an
   apparatus line; every rate shows its Wilson interval (`CiBar` + text);
   formatters return `—` for absent values, never `NaN`/`0`.
2. **State-aware semantics** — colour never travels alone: `Pill` carries a
   glyph and an `aria-label`; `GateBanner` derives its tone and copy from its
   criteria (green only when all hold, red only on a refusal).
3. **Designed empty states** — `EmptyState` says what the surface will show,
   why it is empty, and the one CTA that fills it.
4. **No internals in chrome** — `ErrorState` renders the envelope's message
   first; the code/status is small mono text; `detail` is behind a
   disclosure. No endpoint paths or model jargon in eyebrows.
5. **404 inside the shell** — unknown routes render with the nav intact.
6. **Provenance glyph** — `Provenance` shows apparatus version(s), belt set
   and `measured` / `imported:…`; mixed apparatus is flagged, never averaged.
7. **Gates look like gates** — `GateBanner`: full-width, criteria check-rows,
   primary action disabled until every row holds; a `409 false_q1_refused`
   renders as a REFUSED gate, not a generic error (see `SignoffPage`).
8. **AA minimum, visible focus** — 2px trust focus ring on every interactive,
   ≥40px hit targets, one `h1` per page, proper `<th scope>` and captions.
9. **One brand** — "Commit Replay Bench" everywhere in chrome.
10. **Export top-right** — export/audit buttons live in the page header's
    action slot and link straight to the API's download URLs.

Honesty rules the screens enforce: a capability cell is either measured or
`NOT_YET_MEASURED` (dashed, muted, `n = 0`) — never an empty row; a false-Q1
count above 0 turns its cell, its tile and the page alert red; an unverified
evidence pack is labelled `hash mismatch`.

## Contract notes for the server team

`src/api/types.ts` marks with `@contract` every field that API.md describes
only in prose. The UI's reading, in brief:

- `GET /repos` items: `{name, language, runner, url, probe: {status, run_id,
  checked, detail}, task_counts: {total, standard, hard, gold_clean,
  gold_failed, unchecked}, last_run: {id, kind, status, finished} | null,
  created, updated}`; `GET /repos/{name}` adds `config` (`RepoConfig.to_dict()`).
- `GET /runs/{id}`: the run row plus `counts` (`RunSummary.to_dict()` fields)
  and `progress: {done, total, current_task_id}`.
- `GET /runs/{id}/tasks` items: `{task_id, capability_class, size, pool,
  trials, clean, disqualified, error, belts: {…4}, cost_usd, latency_s,
  pack_hashes[], row_ids[]}`.
- `GET /evidence/{hash}`: `{pack, verified}`; a body that inlines the pack
  next to `verified` is also accepted (`normaliseEvidence`).
- `GET /capability-map`: `{repo, by, classes, sizes, languages, models,
  cells[], summary: {trusted_autonomy_coverage, total_cells, measured_cells,
  deliver_cells, n_total, false_q1_total, apparatus_versions}, policy}`.
  Cells absent from `cells` (or with `route: "NOT_YET_MEASURED"`) render as
  not measured.
- `GET /routes`: `{repo, policy, decisions: RouteDecision.to_dict()[]}`.
- `GET /signoffs` items: `{id, repo, cell, note, approver, created, revoked,
  revoked_by, revoked_at, evidence: {n, point, ci_low, false_q1,
  apparatus_versions}}`.
- `GET /oracle/{repo}`: `{repo, policy: AdequacyPolicy, tasks: [{task_id,
  capability_class, size, strength, band, mutants, killed, gate}], cells:
  [{capability_class, size, n, strength_mean, band, gate}], apparatus_versions}`.
- `GET /settings`: `{builders: [{name, configured}], sandbox_mode, retention,
  oidc_enabled, ledger_backend, apparatus_version, policy_version}`.
